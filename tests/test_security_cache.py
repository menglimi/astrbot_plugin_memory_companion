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

    async def test_note_tools_keep_read_and_delete_scoped_to_current_bot(self) -> None:
        service = self.make_service({"retrieval": {"embedding_enabled": False}})

        async def resolve_event_context(event):
            return event

        service.identity = SimpleNamespace(resolve_event_context=resolve_event_context)
        current = SessionContext(session_id="qq:FriendMessage:u1", scope="private", bot_id="b1")
        other = SessionContext(session_id="qq:FriendMessage:u2", scope="private", bot_id="b2")
        own = await service.tool_note_create(current, "当前 Bot 的笔记", "只允许 b1 读取和删除")
        foreign = await service.tool_note_create(other, "另一个 Bot 的笔记", "只允许 b2 读取和删除")
        ordinary = await service.store.insert_memory(self.group_memory("普通长期记忆不能由笔记工具删除"))

        visible = await service.tool_note_read(current, "", limit=20)
        self.assertEqual([own["memory_id"]], [item["id"] for item in visible["notes"]])

        denied = await service.tool_note_delete(current, foreign["memory_id"])
        self.assertEqual({"ok": False, "error": "note not found"}, denied)
        self.assertIsNotNone(await service.store.get_memory(foreign["memory_id"]))

        wrong_type = await service.tool_note_delete(current, ordinary)
        self.assertEqual({"ok": False, "error": "note not found"}, wrong_type)
        self.assertIsNotNone(await service.store.get_memory(ordinary))

        deleted = await service.tool_note_delete(current, own["memory_id"])
        self.assertTrue(deleted["ok"])
        self.assertTrue(deleted["deleted"])
        self.assertIsNone(await service.store.get_memory(own["memory_id"]))

    async def test_note_delete_requires_unique_exact_title_or_memory_id(self) -> None:
        service = self.make_service({"retrieval": {"embedding_enabled": False}})

        async def resolve_event_context(event):
            return event

        service.identity = SimpleNamespace(resolve_event_context=resolve_event_context)
        ctx = SessionContext(session_id="qq:FriendMessage:u1", scope="private", bot_id="b1")
        first = await service.tool_note_create(ctx, "周末计划", "第一版")
        second = await service.tool_note_create(ctx, "周末计划", "第二版")
        unique = await service.tool_note_create(ctx, "阅读清单", "读完测试文档")

        ambiguous = await service.tool_note_delete(ctx, title="周末计划")
        self.assertFalse(ambiguous["ok"])
        self.assertEqual("ambiguous note title", ambiguous["error"])
        self.assertEqual({first["memory_id"], second["memory_id"]}, {item["memory_id"] for item in ambiguous["matches"]})

        fuzzy = await service.tool_note_delete(ctx, title="阅读")
        self.assertFalse(fuzzy["ok"])
        self.assertEqual("title match requires confirmation", fuzzy["error"])
        self.assertEqual(unique["memory_id"], fuzzy["matches"][0]["memory_id"])
        self.assertIsNotNone(await service.store.get_memory(unique["memory_id"]))

        deleted = await service.tool_note_delete(ctx, title="阅读清单")
        self.assertTrue(deleted["ok"])
        self.assertIsNone(await service.store.get_memory(unique["memory_id"]))

    def test_note_delete_llm_tool_is_registered_and_documented(self) -> None:
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        schema = (ROOT / "_conf_schema.json").read_text(encoding="utf-8")

        self.assertIn('@filter.llm_tool(name="memory_companion_note_delete")', main)
        self.assertIn("memory_tools.enable_note_tools", main)
        self.assertIn("memory_companion_note_delete", readme)
        self.assertIn("创建、读取和删除当前 Bot", schema)

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
