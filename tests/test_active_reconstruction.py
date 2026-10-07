from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SearchResult, SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class ActiveReconstructionTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        merged = {
            "retrieval": {"mode": "basic"},
            "visibility": {"enable_acl_rules": True},
            "memory_injection": {"enable_injection_logs": False},
            "memory_reconstruction": {
                "enabled": True,
                "max_steps": 3,
                "per_step_limit": 6,
                "candidate_scan_limit": 96,
            },
            "memory_tools": {"enable_reconstruction_tool": True},
        }
        if config:
            for key, value in config.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
        service = MemoryCompanionService(
            context=None,
            config=merged,
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def private_context(*, message_id: str = "msg-1", platform: str = "qq", bot_id: str = "b1") -> SessionContext:
        return SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform=platform,
            user_id="u1",
            user_name="小王",
            bot_id=bot_id,
            message_id=message_id,
            message_text="你还记得我喜欢什么咖啡吗？",
        )

    @staticmethod
    def group_context(*, user_id: str = "u1", message_id: str = "group-msg-1") -> SessionContext:
        return SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id=user_id,
            user_name="小王" if user_id == "u1" else "小李",
            group_id="g1",
            group_name="测试群",
            bot_id="b1",
            message_id=message_id,
            message_text="你还记得我喜欢什么咖啡吗？" if user_id == "u1" else "小王喜欢什么咖啡？",
        )

    @staticmethod
    def summary_memory(
        *,
        memory_id: str = "summary-1",
        platform: str = "qq",
        bot_id: str = "b1",
        visibility: str = "private_pair",
    ) -> MemoryRecord:
        return MemoryRecord(
            id=memory_id,
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="小王"),
            object=EntityRef.bot_self(bot_id),
            scope="private",
            session_id="qq:FriendMessage:u1",
            platform=platform,
            visibility=visibility,
            sayability="direct",
            reality_level="llm_summary",
            lifecycle="stable_memory",
            content="小王喜欢无糖拿铁。",
            evidence="小王说：我喝拿铁不加糖。",
            confidence=0.86,
            importance=0.8,
            occurred_at="2026-08-01T04:30:00+00:00",
            metadata={
                "owner_bot_id": bot_id,
                "start_at": "2026-08-01T04:00:00+00:00",
                "end_at": "2026-08-01T05:00:00+00:00",
                "start_at_local": "2026-08-01 12:00",
                "end_at_local": "2026-08-01 13:00",
                "topics": ["咖啡"],
                "key_facts": ["小王喜欢无糖拿铁"],
                "participants": ["小王"],
                "associations": [
                    {
                        "cue": "午后咖啡",
                        "tag": "饮食偏好",
                        "content": "小王喜欢无糖拿铁",
                        "layer": "semantic",
                    }
                ],
            },
        )

    async def insert_indexed(self, service: MemoryCompanionService, record: MemoryRecord) -> None:
        await service.store.insert_memory(record)
        await service._index_summary_knowledge_graph_inner(
            self.private_context(bot_id=record.metadata.get("owner_bot_id") or "b1"),
            record,
            record.metadata,
            record.id,
        )

    async def test_association_is_indexed_as_cue_tag_content_route(self) -> None:
        service = self.make_service()
        record = self.summary_memory()
        await self.insert_indexed(service, record)

        paths = await service.store.query_knowledge_paths(["午后咖啡"], tag="饮食偏好")

        self.assertEqual(1, len(paths))
        self.assertEqual("summary-1", paths[0]["source_memory_id"])
        self.assertEqual("cue", paths[0]["source_type"])
        self.assertEqual("饮食偏好", paths[0]["edge_metadata"]["associative_tag"])
        self.assertEqual("semantic", paths[0]["edge_metadata"]["content_layer"])

    async def test_current_visible_path_is_not_starved_by_other_users_graphs(self) -> None:
        service = self.make_service()
        visible = self.summary_memory(memory_id="visible-current")
        await self.insert_indexed(service, visible)

        for index in range(110):
            user_id = f"hidden-user-{index}"
            hidden = self.summary_memory(memory_id=f"hidden-{index}")
            hidden.subject = EntityRef(kind="user", id=user_id, name=f"隐藏用户 {index}")
            hidden.session_id = f"qq:FriendMessage:{user_id}"
            hidden.content = f"隐藏用户 {index} 喜欢浓缩咖啡。"
            hidden.metadata["key_facts"] = [hidden.content]
            hidden.metadata["participants"] = [hidden.subject.name]
            hidden.metadata["associations"][0]["content"] = hidden.content
            hidden_ctx = SessionContext(
                session_id=hidden.session_id,
                scope="private",
                platform="qq",
                user_id=user_id,
                user_name=hidden.subject.name,
                bot_id="b1",
            )
            await service.store.insert_memory(hidden)
            await service._index_summary_knowledge_graph_inner(
                hidden_ctx,
                hidden,
                hidden.metadata,
                hidden.id,
            )

        service.identity.resolve_event_context = AsyncMock(
            return_value=self.private_context(message_id="dense-graph-msg")
        )
        result = await service.tool_navigate(
            SimpleNamespace(),
            "tag_events",
            cue="午后咖啡",
            tag="饮食偏好",
        )

        self.assertEqual("evidence_found", result["status"])
        self.assertIn("visible-current", {item["memory_id"] for item in result["evidence"]})
        self.assertFalse(
            {f"hidden-{index}" for index in range(110)}
            & {item["memory_id"] for item in result["evidence"]}
        )

    async def test_first_evidence_can_drive_reverse_cue_second_step(self) -> None:
        service = self.make_service()
        await self.insert_indexed(service, self.summary_memory())
        ctx = self.private_context()
        service.identity.resolve_event_context = AsyncMock(return_value=ctx)
        event = SimpleNamespace()

        first = await service.tool_navigate(
            event,
            "tag_events",
            cue="午后咖啡",
            tag="饮食偏好",
        )
        second = await service.tool_navigate(
            event,
            "reverse_cues",
            memory_ids=[first["evidence"][0]["memory_id"]],
        )

        self.assertEqual("evidence_found", first["status"])
        self.assertEqual("小王喜欢无糖拿铁。", first["evidence"][0]["content"])
        self.assertEqual("午后咖啡", first["navigation_hints"][0]["cue"])
        self.assertEqual(2, second["step"])
        self.assertEqual({"午后咖啡"}, {item["cue"] for item in second["navigation_hints"]})

    async def test_event_time_and_context_use_filtered_memory_records(self) -> None:
        service = self.make_service()
        await self.insert_indexed(service, self.summary_memory())
        service.identity.resolve_event_context = AsyncMock(return_value=self.private_context(message_id="time-msg"))
        event = SimpleNamespace()

        event_time = await service.tool_navigate(event, "event_time", memory_ids=["summary-1"])
        event_context = await service.tool_navigate(event, "event_context", memory_ids=["summary-1"])

        self.assertEqual("2026-08-01T04:30:00+00:00", event_time["evidence"][0]["occurred_at"])
        self.assertEqual("2026-08-01 12:30:00", event_time["evidence"][0]["occurred_at_local"])
        self.assertNotIn("evidence_preview", event_time["evidence"][0])
        self.assertIn("我喝拿铁不加糖", event_context["evidence"][0]["evidence_preview"])

    async def test_direct_memory_id_keeps_acl_authorized_group_event_time(self) -> None:
        service = self.make_service()
        await self.insert_indexed(service, self.summary_memory())
        await service.store.upsert_acl_rule(
            owner_scope="private",
            owner_id="u1",
            reader_scope="group",
            reader_id="g1",
            effect="allow",
        )
        group_ctx = self.group_context(message_id="group-time-msg")
        group_ctx.message_text = "昨天的咖啡是几点？"
        service.identity.resolve_event_context = AsyncMock(return_value=group_ctx)

        result = await service.tool_navigate(
            SimpleNamespace(),
            "event_time",
            memory_ids=["summary-1"],
        )

        self.assertEqual("evidence_found", result["status"])
        self.assertEqual(["summary-1"], [item["memory_id"] for item in result["evidence"]])

    async def test_navigation_evidence_redacts_sensitive_content_and_graph_hints(self) -> None:
        service = self.make_service()
        record = self.summary_memory()
        record.content = "密码是 super-secret-123456789。"
        record.evidence = "password: super-secret-123456789"
        record.metadata["canonical_summary"] = "token: abcdefghijklmnop"
        record.metadata["associations"][0]["content"] = "api key: abcdefghijklmnop"
        await self.insert_indexed(service, record)
        service.identity.resolve_event_context = AsyncMock(return_value=self.private_context(message_id="redact-msg"))

        result = await service.tool_navigate(
            SimpleNamespace(),
            "tag_events",
            cue="午后咖啡",
            tag="饮食偏好",
        )

        serialized = str(result)
        for secret in ("super-secret-123456789", "abcdefghijklmnop"):
            self.assertNotIn(secret, serialized)
        self.assertIn("[已隐藏]", serialized)

    async def test_navigation_output_keeps_hints_within_step_budget(self) -> None:
        service = self.make_service()
        record = self.summary_memory()
        item = SearchResult(
            memory=record,
            score=1.0,
        )
        paths = [
            {
                "source_type": "cue",
                "source_label": f"线索-{index}",
                "target_type": "memory",
                "target_label": "摘要",
                "relation_type": "associated_with",
                "evidence": f"证据-{index}",
                "edge_metadata": {"associative_tag": "标签", "content_layer": "semantic"},
            }
            for index in range(8)
        ]

        payload = service._serialize_navigation_evidence(item, action="tag_events", paths=paths)

        self.assertLessEqual(len(payload.get("associations", [])), 1)

    async def test_duplicate_and_step_budget_do_not_replay_evidence(self) -> None:
        service = self.make_service()
        service.identity.resolve_event_context = AsyncMock(return_value=self.private_context(message_id="budget-msg"))
        event = SimpleNamespace()

        first = await service.tool_navigate(event, "search", query="第一条线索")
        duplicate = await service.tool_navigate(event, "search", query="第一条线索")
        second = await service.tool_navigate(event, "search", query="第二条线索")
        third = await service.tool_navigate(event, "search", query="第三条线索")
        exhausted = await service.tool_navigate(event, "search", query="第四条线索")

        self.assertEqual(1, first["step"])
        self.assertFalse(duplicate["ok"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(1, duplicate["step"])
        self.assertNotIn("evidence", duplicate)
        self.assertEqual(2, second["step"])
        self.assertEqual(3, third["step"])
        self.assertEqual("navigation step budget exhausted", exhausted["error"])

    async def test_navigation_blocks_other_platform_and_other_bot_even_when_shareable(self) -> None:
        service = self.make_service()
        await self.insert_indexed(
            service,
            self.summary_memory(memory_id="other-platform", platform="other", visibility="shareable"),
        )
        await self.insert_indexed(
            service,
            self.summary_memory(memory_id="other-bot", bot_id="b2", visibility="shareable"),
        )
        service.identity.resolve_event_context = AsyncMock(return_value=self.private_context(message_id="isolation-msg"))

        result = await service.tool_navigate(
            SimpleNamespace(),
            "tag_events",
            cue="午后咖啡",
            tag="饮食偏好",
        )

        self.assertEqual("no_visible_evidence", result["status"])
        self.assertEqual([], result["evidence"])
        self.assertEqual([], result["navigation_hints"])
        self.assertNotIn("blocked", result)

    async def test_acl_owner_can_navigate_but_other_speaker_cannot(self) -> None:
        service = self.make_service()
        await self.insert_indexed(service, self.summary_memory())
        await service.store.upsert_acl_rule(
            owner_scope="private",
            owner_id="u1",
            reader_scope="group",
            reader_id="g1",
            effect="allow",
        )

        service.identity.resolve_event_context = AsyncMock(return_value=self.group_context(user_id="u1"))
        owner = await service.tool_navigate(
            SimpleNamespace(),
            "tag_events",
            cue="午后咖啡",
            tag="饮食偏好",
        )
        service.identity.resolve_event_context = AsyncMock(return_value=self.group_context(user_id="u2"))
        other = await service.tool_navigate(
            SimpleNamespace(),
            "tag_events",
            cue="午后咖啡",
            tag="饮食偏好",
        )

        self.assertEqual("evidence_found", owner["status"])
        self.assertEqual("no_visible_evidence", other["status"])
        self.assertEqual([], other["evidence"])

    async def test_acl_revocation_is_rechecked_on_later_step(self) -> None:
        service = self.make_service()
        await self.insert_indexed(service, self.summary_memory())
        rule = await service.store.upsert_acl_rule(
            owner_scope="private",
            owner_id="u1",
            reader_scope="group",
            reader_id="g1",
            effect="allow",
        )
        service.identity.resolve_event_context = AsyncMock(return_value=self.group_context(message_id="revoke-msg"))
        event = SimpleNamespace()

        first = await service.tool_navigate(
            event,
            "tag_events",
            cue="午后咖啡",
            tag="饮食偏好",
        )
        await service.store.delete_acl_rule(rule["id"])
        revoked = await service.tool_navigate(event, "reverse_cues", memory_ids=["summary-1"])

        self.assertEqual("evidence_found", first["status"])
        self.assertEqual("no_visible_evidence", revoked["status"])
        self.assertEqual([], revoked["evidence"])
        self.assertEqual([], revoked["navigation_hints"])

    def test_prompt_contract_is_idempotent_and_skips_ordinary_chat(self) -> None:
        service = self.make_service()
        ordinary = self.private_context()
        ordinary.message_text = "你好呀"
        ordinary_req = SimpleNamespace(system_prompt="原始提示")
        service._apply_reconstruction_contract(ordinary_req, ordinary)
        self.assertNotIn("MemoryCompanion-Reconstruction-Contract", ordinary_req.system_prompt)

        recall = self.private_context()
        recall_req = SimpleNamespace(
            system_prompt="原始提示",
            memory_companion_injection_state={"selected_memory_ids": ["m1", "m2"]},
        )
        service._apply_reconstruction_contract(recall_req, recall)
        service._apply_reconstruction_contract(recall_req, recall)

        self.assertEqual(1, recall_req.system_prompt.count("<MemoryCompanion-Reconstruction-Contract>"))
        self.assertIn("正常检索已选出 2 条", recall_req.system_prompt)
        self.assertIn("获得足够证据后立即停止", recall_req.system_prompt)

    def test_dynamic_line_leaves_system_prompt_when_temp_parts_available(self) -> None:
        """宿主提供 TextPart 时，逐轮变化的动态行不再进 system_prompt。

        system prompt 是整条请求里最应当恒定的前缀，逐轮变化会让变化点之后的
        前缀缓存每轮都失配。tests/ 不导入 astrbot，所以这里注入一个假 TextPart
        来覆盖真实宿主那条分支。
        """

        class _FakeTextPart:
            def __init__(self, text: str) -> None:
                self.text = text
                self.temp = False

            def mark_as_temp(self) -> "_FakeTextPart":
                self.temp = True
                return self

        service = self.make_service()
        recall = self.private_context()
        recall_req = SimpleNamespace(
            system_prompt="原始提示",
            memory_companion_injection_state={"selected_memory_ids": ["m1", "m2"]},
        )
        with patch(
            "astrbot_plugin_memory_companion.core.astrbot_compat.TextPart",
            _FakeTextPart,
        ):
            service._apply_reconstruction_contract(recall_req, recall)

        self.assertEqual(
            1, recall_req.system_prompt.count("<MemoryCompanion-Reconstruction-Contract>")
        )
        self.assertIn("获得足够证据后立即停止", recall_req.system_prompt)
        self.assertNotIn("正常检索已选出 2 条", recall_req.system_prompt)

        parts = getattr(recall_req, "extra_user_content_parts", [])
        self.assertEqual(1, len(parts))
        self.assertIn("正常检索已选出 2 条", parts[0].text)
        self.assertTrue(getattr(parts[0], "temp", False))

    def test_tool_and_configuration_are_registered(self) -> None:
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        schema = (ROOT / "_conf_schema.json").read_text(encoding="utf-8")
        self.assertIn('@filter.llm_tool(name="memory_companion_navigate")', main)
        self.assertIn("memory_ids: list[str] | None = None", main)
        self.assertIn("memory_ids(array[string])", main)
        self.assertNotIn(
            "memory_companion_navigate_tool(self, event: AstrMessageEvent, **kwargs",
            main,
        )
        self.assertIn("memory_tools.enable_reconstruction_tool", main)
        self.assertIn('"memory_reconstruction"', schema)


if __name__ == "__main__":
    unittest.main()
