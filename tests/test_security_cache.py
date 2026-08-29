from __future__ import annotations

import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")

    async def _send_file(path):
        return path

    quart_stub.send_file = _send_file
    sys.modules["quart"] = quart_stub

import astrbot_plugin_memory_companion.page_api as page_api_module
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SearchResult, SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.page_api import PluginPageApi


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

    async def page_search(self, payload: dict):
        service = SimpleNamespace(
            search_with_diagnostics=AsyncMock(return_value=([], [])),
            config=SimpleNamespace(bool=lambda *_args: True),
        )
        api = PluginPageApi(SimpleNamespace(service=service))
        fake_request = SimpleNamespace(get_json=AsyncMock(return_value=payload))

        class JsonResponse(dict):
            status_code = 200

        with (
            patch.object(page_api_module, "request", fake_request),
            patch.object(page_api_module, "jsonify", side_effect=lambda body: JsonResponse(body)),
        ):
            response = await api.search()
        return response, service.search_with_diagnostics

    async def test_page_search_uses_slot_orchestration_when_service_supports_it(self) -> None:
        item = SearchResult(memory=self.group_memory("共同召回锚点"), score=1.0, reason="slot=conversation_summary")
        service = SimpleNamespace(
            search_context_slots=AsyncMock(return_value=([item], [], {"conversation_summary": [item]})),
            search_with_diagnostics=AsyncMock(return_value=([], [])),
            _slot_limits=lambda *_args, **_kwargs: {
                "self_timeline": 2,
                "conversation_summary": 2,
            },
            _slot_capped_slots=lambda *_args, **_kwargs: {"self_timeline"},
            config=SimpleNamespace(bool=lambda *_args: True),
        )
        api = PluginPageApi(SimpleNamespace(service=service))
        fake_request = SimpleNamespace(
            get_json=AsyncMock(return_value={"query": "共同召回锚点", "context_mode": "all"})
        )

        class JsonResponse(dict):
            status_code = 200

        with (
            patch.object(page_api_module, "request", fake_request),
            patch.object(page_api_module, "jsonify", side_effect=lambda body: JsonResponse(body)),
        ):
            response = await api.search()

        self.assertEqual(["共同召回锚点"], [item["content"] for item in response["results"]])
        self.assertEqual({"conversation_summary": 1}, response["retrieval"]["slot_counts"])
        self.assertEqual(2, response["retrieval"]["slot_limits"]["self_timeline"])
        self.assertEqual(["self_timeline"], response["retrieval"]["capped_slots"])
        self.assertTrue(response["retrieval"]["orchestration_enabled"])
        service.search_context_slots.assert_awaited_once()
        service.search_with_diagnostics.assert_not_awaited()

    async def test_conversation_import_targets_use_complete_private_bucket_set(self) -> None:
        store = SimpleNamespace(
            list_memory_buckets=AsyncMock(return_value=[
                {"scope": "private", "target_id": "private-user", "pending_count": 3},
                {"scope": "group", "target_id": "group-id"},
            ])
        )
        service = SimpleNamespace(
            store=store,
            config=SimpleNamespace(bool=lambda *_args: False),
        )
        api = PluginPageApi(SimpleNamespace(service=service))

        class JsonResponse(dict):
            status_code = 200

        with patch.object(page_api_module, "jsonify", side_effect=lambda body: JsonResponse(body)):
            response = await api.conversation_import_targets()

        store.list_memory_buckets.assert_awaited_once_with(
            limit=None,
            include_raw_events=False,
        )
        self.assertEqual(["private-user"], [item["target_id"] for item in response["buckets"]])
        self.assertNotIn("pending_count", response["buckets"][0])

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

    async def test_injection_reinforcement_does_not_invalidate_retrieval_revision(self) -> None:
        service = self.make_service()
        memory_id = await service.store.insert_memory(self.group_memory("强化锚点"))
        before = await service.store.memory_revision()
        await service.store.mark_injected([memory_id])
        self.assertEqual(before, await service.store.memory_revision())

    async def test_new_memory_and_content_change_bump_retrieval_revision(self) -> None:
        service = self.make_service()
        before = await service.store.memory_revision()
        memory_id = await service.store.insert_memory(self.group_memory("新增锚点"))
        after_insert = await service.store.memory_revision()
        self.assertNotEqual(before, after_insert)

        await service.store.update_memory_payload(memory_id, content="内容变更锚点")
        after_update = await service.store.memory_revision()
        self.assertNotEqual(after_insert, after_update)

    async def test_page_search_without_context_uses_authenticated_admin_scope(self) -> None:
        response, search = await self.page_search({"query": "显微镜锚点", "scope": "unknown"})

        self.assertTrue(search.await_args.kwargs["admin_read_all"])
        context = search.await_args.args[1]
        self.assertEqual("unknown", context.scope)
        self.assertEqual("", context.session_id)
        self.assertEqual("all", response["search_context"]["mode"])
        self.assertFalse(response["retrieval"]["orchestration_enabled"])

        response, search = await self.page_search(
            {
                "query": "显微镜锚点",
                "context_mode": "all",
                "bot_id": "不应进入管理检索上下文",
            }
        )
        context = search.await_args.args[1]
        self.assertEqual("", context.bot_id)
        self.assertEqual("", response["search_context"]["bot_id"])

    async def test_page_search_preserves_private_and_group_visibility_contexts(self) -> None:
        cases = (
            (
                {
                    "query": "私聊锚点",
                    "scope": "private",
                    "session_id": "qq:FriendMessage:u1",
                    "user_id": "u1",
                    "bot_id": "bot-private",
                    "admin_read_all": True,
                },
                "private",
                "u1",
                "",
                "bot-private",
            ),
            (
                {
                    "query": "群聊锚点",
                    "context_mode": "session",
                    "scope": "group",
                    "session_id": "qq:GroupMessage:g1",
                    "group_id": "g1",
                    "bot_id": "bot-group",
                    "admin_read_all": True,
                },
                "group",
                "",
                "g1",
                "bot-group",
            ),
        )
        for payload, scope, user_id, group_id, bot_id in cases:
            with self.subTest(scope=scope):
                response, search = await self.page_search(payload)
                self.assertFalse(search.await_args.kwargs["admin_read_all"])
                context = search.await_args.args[1]
                self.assertEqual(scope, context.scope)
                self.assertEqual(user_id, context.user_id)
                self.assertEqual(group_id, context.group_id)
                self.assertEqual(bot_id, context.bot_id)
                self.assertEqual("session", response["search_context"]["mode"])
                self.assertEqual(bot_id, response["search_context"]["bot_id"])

    async def test_page_search_rejects_incomplete_or_invalid_context_intent(self) -> None:
        for payload in (
            {"query": "锚点", "context_mode": "session", "scope": "private"},
            {"query": "锚点", "scope": "group"},
            {"query": "锚点", "bot_id": "bot-without-session"},
            {
                "query": "锚点",
                "context_mode": "session",
                "scope": "group",
                "session_id": "qq:FriendMessage:u1",
                "group_id": "g1",
            },
            {
                "query": "锚点",
                "context_mode": "session",
                "scope": "private",
                "session_id": "qq:FriendMessage:u1",
                "user_id": "u2",
            },
            {"query": "锚点", "context_mode": "invalid"},
        ):
            with self.subTest(payload=payload):
                response, search = await self.page_search(payload)
                self.assertEqual(400, response.status_code)
                search.assert_not_awaited()

    async def test_session_diagnostics_uses_bucket_bot_owner(self) -> None:
        service = self.make_service({"retrieval": {"mode": "basic"}})
        first = self.group_memory("多 Bot 甲号所有权锚点")
        first.id = "multi-bot-a"
        first.occurred_at = "2026-07-20T10:00:00+00:00"
        first.metadata = {"owner_bot_id": "bot-a"}
        first_id = await service.store.insert_memory(first)
        second = self.group_memory("多 Bot 乙号所有权锚点")
        second.id = "multi-bot-b"
        second.occurred_at = "2026-07-21T10:00:00+00:00"
        second.metadata = {"owner_bot_id": "bot-b"}
        second_id = await service.store.insert_memory(second)
        archived = self.group_memory("已归档 Bot 不得抢占样本")
        archived.id = "multi-bot-archived"
        archived.occurred_at = "2026-07-25T10:00:00+00:00"
        archived.lifecycle = "archived"
        archived.metadata = {"owner_bot_id": "bot-archived"}
        await service.store.insert_memory(archived)
        internal = self.group_memory("内部记录不得生成可检索上下文")
        internal.id = "multi-bot-internal"
        internal.occurred_at = "2026-07-26T10:00:00+00:00"
        internal.visibility = "internal"
        internal.metadata = {"owner_bot_id": "bot-internal"}
        await service.store.insert_memory(internal)
        raw_event = self.group_memory("默认关闭的原始事件不得生成可检索上下文")
        raw_event.id = "multi-bot-raw-event"
        raw_event.occurred_at = "2026-07-27T10:00:00+00:00"
        raw_event.lifecycle = "raw_event"
        raw_event.metadata = {"owner_bot_id": "bot-raw"}
        await service.store.insert_memory(raw_event)

        buckets = await service.store.list_memory_buckets()
        bucket = next(item for item in buckets if item["target_id"] == "g1")
        self.assertEqual("bot-b", bucket["sample_bot_id"])
        contexts = {item["bot_id"]: item for item in bucket["sample_contexts"]}
        self.assertEqual(
            {"bot-a", "bot-b", "bot-archived", "bot-internal", "bot-raw"},
            set(contexts),
        )
        self.assertEqual(2, bucket["searchable_count"])
        self.assertEqual(1, contexts["bot-a"]["searchable_count"])
        self.assertEqual(1, contexts["bot-b"]["searchable_count"])
        self.assertEqual(0, contexts["bot-archived"]["searchable_count"])
        self.assertEqual(0, contexts["bot-internal"]["searchable_count"])
        self.assertEqual(0, contexts["bot-raw"]["searchable_count"])

        raw_enabled_buckets = await service.store.list_memory_buckets(
            include_raw_events=True,
        )
        raw_enabled_bucket = next(
            item for item in raw_enabled_buckets if item["target_id"] == "g1"
        )
        raw_enabled_contexts = {
            item["bot_id"]: item for item in raw_enabled_bucket["sample_contexts"]
        }
        self.assertEqual("bot-raw", raw_enabled_bucket["sample_bot_id"])
        self.assertEqual(1, raw_enabled_contexts["bot-raw"]["searchable_count"])

        first_context = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            group_id="g1",
            bot_id="bot-a",
        )
        second_context = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            group_id="g1",
            bot_id="bot-b",
        )
        other_context = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            group_id="g1",
            bot_id="bot-other",
        )
        first_visible, _ = await service.search_with_diagnostics(
            "多 Bot 甲号所有权锚点",
            first_context,
            8,
        )
        second_visible, _ = await service.search_with_diagnostics(
            "多 Bot 乙号所有权锚点",
            second_context,
            8,
        )
        hidden, blocked = await service.search_with_diagnostics(
            "多 Bot 甲号所有权锚点",
            other_context,
            8,
        )

        self.assertIn(first_id, {item.memory.id for item in first_visible})
        self.assertIn(second_id, {item.memory.id for item in second_visible})
        self.assertNotIn(first_id, {item.memory.id for item in hidden})
        self.assertTrue(any("other_bot_owner" in item.get("reason", "") for item in blocked))

    async def test_admin_diagnostics_can_retrieve_private_and_group_memories(self) -> None:
        service = self.make_service({"retrieval": {"mode": "basic"}})
        private_id = await service.store.insert_memory(
            MemoryRecord(
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1", name="测试用户"),
                object=EntityRef(kind="bot", id="self", name="Bot"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="显微镜全库锚点来自私聊",
                importance=0.9,
                owner_bot_id="bot-a",
                metadata={"persona_id": "persona-a"},
            )
        )
        group_memory = self.group_memory("显微镜全库锚点来自群聊")
        group_memory.owner_bot_id = "bot-b"
        group_memory.metadata = {"persona_id": "persona-b"}
        group_id = await service.store.insert_memory(group_memory)
        internal_id = await service.store.insert_memory(
            MemoryRecord(
                memory_type="internal_note",
                subject=EntityRef(kind="bot", id="self", name="Bot"),
                object=EntityRef(kind="bot", id="self", name="Bot"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                visibility="internal",
                lifecycle="stable_memory",
                content="显微镜全库锚点内部记录",
                importance=0.9,
            )
        )
        archived_id = await service.store.insert_memory(
            MemoryRecord(
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u2", name="归档用户"),
                object=EntityRef(kind="bot", id="self", name="Bot"),
                scope="private",
                session_id="qq:FriendMessage:u2",
                visibility="private_pair",
                lifecycle="archived",
                content="显微镜全库锚点归档记录",
                importance=0.9,
            )
        )
        context = SessionContext(session_id="", scope="unknown", message_text="显微镜全库锚点")

        regular, _ = await service.search_with_diagnostics("显微镜全库锚点", context, 10)
        admin, _ = await service.search_with_diagnostics(
            "显微镜全库锚点",
            context,
            10,
            admin_read_all=True,
        )

        self.assertFalse({private_id, group_id} & {item.memory.id for item in regular})
        admin_ids = {item.memory.id for item in admin}
        self.assertTrue({private_id, group_id}.issubset(admin_ids))
        self.assertNotIn(internal_id, admin_ids)
        self.assertNotIn(archived_id, admin_ids)

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

    async def test_cross_window_emotional_reads_without_context_are_disabled(self) -> None:
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
        self.assertEqual([], service.bridge_get_emotional_events(session_id=""))
        self.assertEqual(1, len(service._emotional_event_queue["qq:FriendMessage:u1"]))

        exact = service.bridge_get_emotional_events(
            session_id="qq:FriendMessage:u1", limit=3
        )
        self.assertEqual(["emotion-1"], [item["id"] for item in exact])
        self.assertNotIn("session_id", exact[0])
        self.assertEqual([], service._emotional_event_queue["qq:FriendMessage:u1"])

        service._emotional_event_queue["qq:FriendMessage:u1"] = [
            {
                "id": "emotion-2",
                "session_id": "qq:FriendMessage:u1",
                "event_type": "warm_memory",
                "ts": time.time(),
            }
        ]
        config["private_companion_bridge"]["legacy_emotion_compatibility_enabled"] = False
        self.assertEqual(
            [],
            service.bridge_get_emotional_events(session_id="qq:FriendMessage:u1"),
        )
        self.assertEqual(1, len(service._emotional_event_queue["qq:FriendMessage:u1"]))

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

    def test_companion_page_formal_path_has_no_private_host_or_local_path_access(self) -> None:
        source = (ROOT / "page_api.py").read_text(encoding="utf-8")
        legacy = (ROOT / "companion_page_legacy.py").read_text(encoding="utf-8")

        self.assertNotIn('getattr(api, "_plugin"', source)
        self.assertNotIn("_safe_companion_photo_path", source)
        self.assertNotIn("_local_path", source)
        self.assertNotIn("plugin.data", source)
        self.assertIn("self._plugin = api._plugin", legacy)
        self.assertIn("O_NOFOLLOW", legacy)


if __name__ == "__main__":
    unittest.main()
