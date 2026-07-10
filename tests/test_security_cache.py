from __future__ import annotations

import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")

    async def _send_file(path):
        return path

    quart_stub.send_file = _send_file
    sys.modules["quart"] = quart_stub

from astrbot_plugin_remember_you.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_remember_you.core.service import MemoryCompanionService
from astrbot_plugin_remember_you.page_api import PluginPageApi


class SecurityAndCacheTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config=config or {},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def group_memory(content: str = "唯一锚点蓝风铃") -> MemoryRecord:
        return MemoryRecord(
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="group-user", name="群成员"),
            object=EntityRef(kind="group", id="g1", name="测试群"),
            scope="group",
            session_id="qq:GroupMessage:g1",
            platform="qq",
            group_id="g1",
            visibility="group_public",
            lifecycle="stable_memory",
            content=content,
            importance=0.9,
        )

    async def test_acl_revoke_invalidates_cached_search(self) -> None:
        service = self.make_service(
            {
                "retrieval": {"mode": "basic"},
                "visibility": {
                    "enable_acl_rules": True,
                    "allow_group_public_in_private": False,
                },
            }
        )
        memory_id = await service.store.insert_memory(self.group_memory())
        rule = await service.store.upsert_acl_rule(
            owner_scope="group",
            owner_id="g1",
            reader_scope="private",
            reader_id="u1",
            effect="allow",
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )

        first = await service.search("蓝风铃", ctx)
        second = await service.search("蓝风铃", ctx)
        self.assertIn(memory_id, {item.memory.id for item in first})
        self.assertIn(memory_id, {item.memory.id for item in second})
        self.assertGreaterEqual(service._retrieval_result_cache_stats["hits"], 1)

        await service.store.delete_acl_rule(rule["id"])
        revoked = await service.search("蓝风铃", ctx)
        self.assertNotIn(memory_id, {item.memory.id for item in revoked})

    async def test_visibility_config_change_cannot_reuse_old_cache(self) -> None:
        config = {
            "retrieval": {"mode": "basic"},
            "visibility": {
                "enable_acl_rules": False,
                "allow_group_public_in_private": True,
            },
        }
        service = self.make_service(config)
        memory_id = await service.store.insert_memory(self.group_memory("配置切换锚点绿松石"))
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )
        visible = await service.search("绿松石", ctx)
        self.assertIn(memory_id, {item.memory.id for item in visible})

        config["visibility"]["allow_group_public_in_private"] = False
        hidden = await service.search("绿松石", ctx)
        self.assertNotIn(memory_id, {item.memory.id for item in hidden})

    async def test_access_tracking_does_not_invalidate_retrieval_revision(self) -> None:
        service = self.make_service()
        memory_id = await service.store.insert_memory(self.group_memory("版本锚点"))
        before = await service.store.memory_revision()
        await service.store.mark_accessed([memory_id])
        self.assertEqual(before, await service.store.memory_revision())

    async def test_service_clear_resets_persisted_and_runtime_state(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.group_memory("清空状态"))
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )
        service._get_relationship_phase(ctx)["phase"] = "close"
        service._save_relationship_phase_state()
        service._emotional_event_queue[ctx.session_id] = [{"ts": 1.0}]
        service._retrieval_result_cache["cached"] = {"payload": {}}

        result = await service.clear_all_memory_data()
        self.assertIn("backup", result)
        self.assertEqual({}, service._relationship_phase_state)
        self.assertEqual({}, service._emotional_event_queue)
        self.assertEqual({}, service._retrieval_result_cache)
        self.assertEqual({}, json.loads(service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8")))

    async def test_cross_window_emotional_reads_are_opt_in(self) -> None:
        config: dict = {"private_companion_bridge": {}}
        service = self.make_service(config)
        service._emotional_event_queue["qq:FriendMessage:u1"] = [
            {
                "id": "emotion-1",
                "session_id": "qq:FriendMessage:u1",
                "event_type": "warm_memory",
                "ts": time.time(),
            }
        ]
        self.assertEqual([], service.bridge_get_emotional_events(session_id=""))
        self.assertEqual(1, len(service._emotional_event_queue["qq:FriendMessage:u1"]))

        config["private_companion_bridge"]["cross_window_emotional_continuity_enabled"] = True
        events = service.bridge_get_emotional_events(session_id="")
        self.assertEqual(["emotion-1"], [item["id"] for item in events])

    def test_photo_path_is_confined_and_local_path_is_not_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            allowed = base / "companion-data"
            own_data = base / "memory-data"
            allowed.mkdir()
            own_data.mkdir()
            inside = allowed / "inside.jpg"
            outside = base / "outside.jpg"
            inside.write_bytes(b"jpeg-placeholder")
            outside.write_bytes(b"jpeg-placeholder")

            page_plugin = SimpleNamespace(service=SimpleNamespace(data_dir=own_data))
            companion = SimpleNamespace(data_dir=allowed, data_file=allowed / "companions.json")
            api = PluginPageApi(page_plugin)

            self.assertEqual(inside.resolve(), api._safe_companion_photo_path(inside, companion))
            self.assertEqual(inside.resolve(), api._safe_companion_photo_path("inside.jpg", companion))
            self.assertIsNone(api._safe_companion_photo_path(outside, companion))

            album = api._private_companion_album(
                {"daily_outfit_photo": {"path": str(inside), "date": "2026-07-10"}},
                "2026-07-10",
                plugin=companion,
            )
            self.assertEqual(1, len(album))
            self.assertNotIn("path", album[0])
            self.assertNotIn("_local_path", album[0])


if __name__ == "__main__":
    unittest.main()
