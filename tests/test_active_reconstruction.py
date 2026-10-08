from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


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
        self.assertEqual("no_source_refs", event_context["evidence"][0]["source_coverage"]["status"])
        self.assertEqual([], event_context["evidence"][0]["sources"])

    async def add_source(self, service, *, metadata=None, **changes):
        values = {
            "event_type": "bot_response", "session_id": "qq:FriendMessage:u1",
            "scope": "private", "subject_id": "b1", "object_id": "u1",
            "content": "今天喝的是无糖拿铁。", "occurred_at": "2026-09-07T19:41:21+00:00",
            "metadata": {"owner_bot_id": "b1", "platform": "qq", "persona_id": "", **(metadata or {})},
        }
        values.update(changes)
        return await service.store.add_timeline_event(**values)

    async def test_time_navigation_reads_original_source_and_keeps_time_semantics(self):
        service = self.make_service()
        ref = await self.add_source(service)
        record = self.summary_memory()
        record.occurred_at = "2026-09-13T08:00:00+00:00"
        record.metadata["source_event_ids"] = [ref]
        await self.insert_indexed(service, record)
        service.identity.resolve_event_context = AsyncMock(return_value=self.private_context())

        result = await service.tool_navigate(SimpleNamespace(), "event_time", memory_ids=[record.id])

        evidence = result["evidence"][0]
        source = evidence["sources"][0]
        self.assertEqual(f"timeline:{ref}", source["source_ref"])
        self.assertTrue(source["source_version"])
        self.assertEqual("2026-09-08 03:41:21", source["message_at_local"])
        self.assertEqual("assistant", source["speaker_role"])
        self.assertEqual("今天喝的是无糖拿铁。", source["excerpt"])
        self.assertEqual("summary_time", evidence["time_semantics"]["occurred_at_kind"])
        self.assertEqual("requires_source_interpretation", evidence["time_semantics"]["event_time_status"])
        self.assertEqual("not_established", evidence["source_coverage"]["event_coverage"])

    async def test_sources_are_independently_scoped_even_under_a_visible_summary(self):
        variants = [
            {"session_id": "qq:FriendMessage:u2"},
            {"scope": "group"},
            {"metadata": {"platform": "other"}},
            {"metadata": {"owner_bot_id": "b2"}},
            {"metadata": {"owner_bot_id": ""}},
            {"metadata": {"persona_id": "other-persona"}},
            {"subject_id": "b2"},
            {"object_id": "u2"},
            {"event_type": "user_message", "subject_id": "u2"},
            {"metadata": {"participant_user_id": "u2"}},
        ]
        for index, changes in enumerate(variants):
            with self.subTest(changes=changes):
                service = self.make_service()
                ref = await self.add_source(service, content="不可泄露的来源", **changes)
                record = self.summary_memory(memory_id=f"scope-{index}")
                record.metadata["source_event_ids"] = [ref]
                await self.insert_indexed(service, record)
                service.identity.resolve_event_context = AsyncMock(return_value=self.private_context(message_id=f"scope-msg-{index}"))

                result = await service.tool_navigate(SimpleNamespace(), "event_context", memory_ids=[record.id])

                evidence = result["evidence"][0]
                self.assertEqual([], evidence["sources"])
                self.assertEqual(1, evidence["source_coverage"]["unavailable_count"])
                self.assertNotIn("不可泄露的来源", str(result))
                self.assertNotIn(ref, str(result))

    async def test_missing_source_and_unbound_persona_remain_gaps(self):
        service = self.make_service()
        legacy_ref = await self.add_source(service)
        record = self.summary_memory()
        record.metadata["source_event_ids"] = ["tl_missing", legacy_ref]
        record.metadata["source_expired_event_ids"] = ["tl_missing"]
        await self.insert_indexed(service, record)
        ctx = self.private_context()
        ctx.persona_id = "p1"
        service.identity.resolve_event_context = AsyncMock(return_value=ctx)

        result = await service.tool_navigate(SimpleNamespace(), "event_context", memory_ids=[record.id])

        evidence = result["evidence"][0]
        self.assertEqual([], evidence["sources"])
        self.assertEqual("partial", evidence["source_coverage"]["status"])
        self.assertEqual(2, evidence["source_coverage"]["unavailable_count"])
        self.assertEqual(1, evidence["source_coverage"]["expired_count"])

    async def test_source_budget_prioritizes_fact_refs_and_reports_truncation(self):
        service = self.make_service()
        refs = [await self.add_source(service, content=f"第 {index} 条。" + "后续文字" * 230) for index in range(6)]
        record = self.summary_memory()
        record.metadata.update({
            "source_event_ids": refs,
            "key_facts_with_refs": [{"fact": "一次喝咖啡", "refs": [refs[-1]]}],
            "evidence_refs": [{"source_ref": f"timeline:{refs[-1]}"}, {"message_id": "not-a-timeline"}],
        })
        await self.insert_indexed(service, record)
        service.identity.resolve_event_context = AsyncMock(return_value=self.private_context())
        service.store.get_timeline_by_ids = AsyncMock(wraps=service.store.get_timeline_by_ids)

        result = await service.tool_navigate(SimpleNamespace(), "event_context", memory_ids=[record.id])

        evidence = result["evidence"][0]
        self.assertEqual(f"timeline:{refs[-1]}", evidence["sources"][0]["source_ref"])
        self.assertEqual(4, len(service.store.get_timeline_by_ids.call_args.args[0]))
        self.assertEqual(4, len(evidence["sources"]))
        self.assertTrue(all(source["excerpt_truncated"] for source in evidence["sources"]))
        self.assertTrue(all(len(source["excerpt"]) <= 800 for source in evidence["sources"]))
        self.assertEqual(2, evidence["source_coverage"]["omitted_count"])
        self.assertEqual("partial", evidence["source_coverage"]["status"])

    async def test_graph_context_expands_sources_and_redacts_raw_text(self):
        service = self.make_service()
        ref = await self.add_source(service, content="password: super-secret-123456789")
        record = self.summary_memory()
        record.metadata["source_event_ids"] = [ref]
        await self.insert_indexed(service, record)
        service.identity.resolve_event_context = AsyncMock(return_value=self.private_context())

        result = await service.tool_navigate(SimpleNamespace(), "event_context", cue="午后咖啡", tag="饮食偏好")

        self.assertEqual(1, len(result["evidence"][0]["sources"]))
        self.assertNotIn("super-secret-123456789", str(result))
        self.assertIn("[已隐藏]", str(result))

    async def test_visible_turn_records_identity_for_later_source_lookup(self):
        service = self.make_service()
        service._schedule_session_summary = Mock()
        ref = await service.record_visible_turn(
            role="assistant", content="无糖拿铁。", scope="private", session_id="qq:FriendMessage:u1",
            platform="qq", user_id="u1", metadata={"bot_id": "b1", "persona_id": "p1"},
        )
        row = (await service.store.get_timeline_by_ids([ref]))[ref]
        metadata = json.loads(row["metadata"])
        ctx = self.private_context()
        ctx.persona_id = "p1"

        self.assertTrue(service._navigation_source_visible(ctx, row, metadata))
        self.assertEqual("u1", metadata["participant_user_id"])
        self.assertEqual("p1", service._schedule_session_summary.call_args.args[0].persona_id)

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
        with patch("astrbot_plugin_memory_companion.core.astrbot_compat.TextPart", None):
            service._apply_reconstruction_contract(recall_req, recall)
            service._apply_reconstruction_contract(recall_req, recall)

        self.assertEqual(1, recall_req.system_prompt.count("<MemoryCompanion-Reconstruction-Contract>"))
        turn_state = "\n".join(
            getattr(part, "text", "")
            for part in getattr(recall_req, "extra_user_content_parts", [])
        )
        self.assertIn("正常检索已选出 2 条", recall_req.system_prompt + turn_state)
        self.assertIn("实际注入条数：未确认", recall_req.system_prompt + turn_state)
        self.assertIn("获得足够证据后立即停止", recall_req.system_prompt)

    def test_reconstruction_prompt_separates_selected_and_injected_counts(self):
        service = self.make_service()
        req = SimpleNamespace(system_prompt="", memory_companion_injection_state={
            "selected_memory_ids": ["m1", "m2", "m3"], "injected_memory_ids": ["m1"],
        })
        service._apply_reconstruction_contract(req, self.private_context())
        turn_state = "\n".join(
            getattr(part, "text", "")
            for part in getattr(req, "extra_user_content_parts", [])
        )
        self.assertIn("已选出 3 条候选，实际注入条数：1", req.system_prompt + turn_state)

    def test_turn_state_is_temporary_and_does_not_change_system_prompt(self):
        class FakeTextPart:
            def __init__(self, text: str) -> None:
                self.text = text
                self.temporary = False

            def mark_as_temp(self):
                self.temporary = True
                return self

        service = self.make_service()
        ctx = self.private_context()
        req = SimpleNamespace(
            system_prompt="原始提示",
            memory_companion_injection_state={
                "selected_memory_ids": ["m1", "m2"],
                "injected_memory_ids": ["m1"],
            },
        )
        with patch(
            "astrbot_plugin_memory_companion.core.astrbot_compat.TextPart",
            FakeTextPart,
        ):
            service._apply_reconstruction_contract(req, ctx)
            first_prompt = req.system_prompt
            service._apply_reconstruction_contract(req, ctx)

        self.assertEqual(first_prompt, req.system_prompt)
        self.assertNotIn("已选出 2 条候选", req.system_prompt)
        parts = getattr(req, "extra_user_content_parts", [])
        self.assertEqual(1, len(parts))
        self.assertIn("已选出 2 条候选，实际注入条数：1", parts[0].text)
        self.assertTrue(parts[0].temporary)

    def test_scar_scene_gate_marks_high_scar_memory_before_injection(self):
        service = self.make_service()
        memory = self.summary_memory()
        memory.metadata.update({"scar_weight": 0.7, "mention_policy": "soft_echo"})
        item = SearchResult(memory=memory, score=1.0)

        result = service._apply_scar_scene_gate(
            self.private_context(),
            {"stable_memory": [item]},
            companion_bot_energy=25,
            time_of_day="afternoon",
        )

        self.assertEqual("tone_only", result["stable_memory"][0].memory.metadata["mention_policy"])
        self.assertTrue(result["stable_memory"][0].memory.metadata["_scene_gated"])

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

    def test_unrecognized_recall_gets_guidance_without_forcing_search(self) -> None:
        from astrbot.core.agent.tool import FunctionTool, ToolSet

        service = self.make_service()
        for query in (
            "9月8日问你胖次那回，后来改口后到底是什么颜色和款式？",
            "9月7日到13日我问过你哪几次胖次？每次最终答的是什么？按询问日期整理，没记录的别补。",
        ):
            with self.subTest(query=query):
                ctx = self.private_context()
                ctx.message_text = query
                self.assertFalse(service._should_offer_memory_reconstruction(ctx))
                tools = ToolSet(tools=[FunctionTool(name="memory_companion_sources", description="sources", parameters={})])
                req = SimpleNamespace(system_prompt="原始提示", func_tool=tools)
                service.search_context_slots = AsyncMock()
                service._apply_reconstruction_contract(req, ctx)
                service._apply_reconstruction_contract(req, ctx)
                self.assertEqual(1, req.system_prompt.count("<MemoryCompanion-Recall-Guidance>"))
                self.assertNotIn("<MemoryCompanion-Reconstruction-Contract>", req.system_prompt)
                self.assertIs(req.func_tool, tools)
                self.assertEqual({}, service._reconstruction_states)
                service.search_context_slots.assert_not_awaited()

    def test_guidance_tracks_tool_availability_and_does_not_duplicate_detailed_contract(self) -> None:
        from astrbot.core.agent.tool import FunctionTool, ToolSet

        service = self.make_service()
        ctx = self.private_context()
        req = SimpleNamespace(system_prompt="原始提示", func_tool=ToolSet(tools=[
            FunctionTool(name="memory_companion_sources", description="sources", parameters={}),
        ]))
        ctx.message_text = "你好呀"
        service._apply_reconstruction_contract(req, ctx)
        self.assertIn("<MemoryCompanion-Recall-Guidance>", req.system_prompt)
        self.assertNotIn("<MemoryCompanion-Reconstruction-Contract>", req.system_prompt)
        ctx.message_text = "你还记得上次是哪一天吗？"
        service._apply_reconstruction_contract(req, ctx)
        self.assertIn("<MemoryCompanion-Reconstruction-Contract>", req.system_prompt)
        self.assertNotIn("<MemoryCompanion-Recall-Guidance>", req.system_prompt)
        ctx.message_text = "你好呀"
        req.func_tool.tools[0].active = False
        service._apply_reconstruction_contract(req, ctx)
        self.assertEqual("原始提示", req.system_prompt.strip())
        self.assertFalse(req.func_tool.tools[0].active)

    def test_guidance_respects_reconstruction_switches(self) -> None:
        from astrbot.core.agent.tool import FunctionTool, ToolSet

        for config in ({"memory_reconstruction": {"enabled": False}},
                       {"memory_tools": {"enable_reconstruction_tool": False}}):
            with self.subTest(config=config):
                service = self.make_service(config)
                ctx = self.private_context()
                ctx.message_text = "按之前的情况整理一下"
                req = SimpleNamespace(system_prompt="原始提示", func_tool=ToolSet(tools=[
                    FunctionTool(name="memory_companion_sources", description="sources", parameters={}),
                ]))
                service._apply_reconstruction_contract(req, ctx)
                self.assertEqual("原始提示", req.system_prompt)
                self.assertEqual({}, service._reconstruction_states)


if __name__ == "__main__":
    unittest.main()
