from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.importance import ImportanceEvaluator
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.time_intent import parse_time_intent


class PrivateToGroupAclRecallTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={
                "retrieval": {"mode": "basic"},
                "visibility": {"enable_acl_rules": True},
                "memory_injection": {"enable_injection_logs": False, "max_chars": 3200},
            },
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def private_memory(
        content: str = "小王明确说过：中午吃了番茄鸡蛋面。",
        *,
        memory_type: str = "explicit_memory",
        occurred_at: str = "",
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_type=memory_type,
            subject=EntityRef(kind="user", id="u1", name="小王"),
            object=EntityRef.bot_self("b1"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            platform="qq",
            visibility="private_pair",
            sayability="indirect" if memory_type == "tool_memory" else "direct",
            reality_level="real_user_fact",
            lifecycle="stable_memory",
            content=content,
            evidence="请记住这件事。",
            confidence=0.9,
            importance=0.9,
            tags=["stable_fact", memory_type],
            metadata={"mention_policy": "direct", "mentionability_score": 0.9},
            occurred_at=occurred_at,
        )

    @staticmethod
    def group_context(
        *,
        user_id: str = "u1",
        message_text: str = "我中午吃了什么？",
        platform: str = "qq",
        bot_id: str = "b1",
    ) -> SessionContext:
        return SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform=platform,
            user_id=user_id,
            user_name="小王" if user_id == "u1" else "小李",
            group_id="g1",
            group_name="测试群",
            bot_id=bot_id,
            message_text=message_text,
        )

    async def allow_private_to_group(self, service: MemoryCompanionService) -> dict:
        return await service.store.upsert_acl_rule(
            owner_scope="private",
            owner_id="u1",
            reader_scope="group",
            reader_id="g1",
            effect="allow",
        )

    async def test_acl_shared_explicit_memory_answers_natural_group_question(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory())
        await self.allow_private_to_group(service)
        ctx = self.group_context()

        injection = await service._compose_memory_injection(
            ctx,
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("番茄鸡蛋面", injection)
        self.assertIn("acl_allowed", injection)
        self.assertIn("权限只表示该记忆可作为候选", injection)
        self.assertIn("普通陈述或意图不清时忽略", injection)
        self.assertIn("当前发言者的核心意图", injection)

    async def test_scar_scene_gate_runs_in_the_actual_injection_path(self) -> None:
        service = self.make_service()
        memory = self.private_memory()
        memory.metadata["scar_weight"] = 0.8
        memory_id = await service.store.insert_memory(memory)
        await self.allow_private_to_group(service)
        with patch.object(service, "_compute_time_of_day", return_value="late_night"), patch.object(
            service, "_apply_scar_scene_gate", wraps=service._apply_scar_scene_gate,
        ) as gate:
            await service._compose_memory_injection(self.group_context(), max_chars=3200, write_log=False)
        gate.assert_called_once()
        self.assertEqual("late_night", gate.call_args.kwargs["time_of_day"])
        selected = [item.memory for items in gate.call_args.args[1].values() for item in items]
        scar = next(item for item in selected if item.id == memory_id)
        self.assertEqual("tone_only", scar.metadata["mention_policy"])
        self.assertTrue(scar.metadata["_scene_gated"])
        # The scene projection belongs to this turn, not the stored fact.
        self.assertNotIn("_scene_gated", (await service.store.get_memory(memory_id)).metadata)

    async def test_acl_shared_tool_memory_is_kept_by_recent_state_guard(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory(memory_type="tool_memory"))
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(),
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("番茄鸡蛋面", injection)
        self.assertIn("普通陈述或意图不清时忽略", injection)

    async def test_production_remember_tool_record_is_recalled_across_acl(self) -> None:
        service = self.make_service()
        private_ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_text="请记住我喜欢的面馆是云杉面馆",
        )
        service.identity.resolve_event_context = AsyncMock(return_value=private_ctx)
        stored = await service.tool_remember(
            object(),
            "小王喜欢的面馆是云杉面馆。",
            note_type="preference",
        )
        self.assertIs(stored.get("ok"), True)
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(message_text="我喜欢哪家面馆？"),
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("云杉面馆", injection)
        self.assertNotIn("只影响语气，禁止复述", injection)
        self.assertIn("普通陈述或意图不清时忽略", injection)

    async def test_acl_shared_preference_can_be_used_without_recall_keywords(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(
            self.private_memory(
                "小王喜欢的面馆是云杉面馆。",
                memory_type="user_preference",
            )
        )
        await self.allow_private_to_group(service)
        ctx = self.group_context(message_text="我喜欢哪家面馆？")

        injection = await service._compose_memory_injection(
            ctx,
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("云杉面馆", injection)
        self.assertIn("普通陈述或意图不清时忽略", injection)

    async def test_no_forward_acl_reverse_acl_and_unrelated_query_stay_private(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory())
        ctx = self.group_context()

        without_acl = await service._compose_memory_injection(ctx, max_chars=3200, write_log=False)
        self.assertNotIn("番茄鸡蛋面", without_acl)

        await service.store.upsert_acl_rule(
            owner_scope="group",
            owner_id="g1",
            reader_scope="private",
            reader_id="u1",
            effect="allow",
        )
        reverse_only = await service._compose_memory_injection(ctx, max_chars=3200, write_log=False)
        self.assertNotIn("番茄鸡蛋面", reverse_only)

        await self.allow_private_to_group(service)
        unrelated = await service._compose_memory_injection(
            self.group_context(message_text="今天天气怎么样？"),
            max_chars=3200,
            write_log=False,
        )
        self.assertNotIn("番茄鸡蛋面", unrelated)

    async def test_related_group_statement_is_prompt_guarded_instead_of_keyword_blocked(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(
            self.private_memory(
                "小王喜欢的面馆是云杉面馆。",
                memory_type="user_preference",
            )
        )
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(message_text="云杉面馆最近在群里挺火"),
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("小王喜欢的面馆", injection)
        self.assertIn("否则不要主动公开或复述", injection)

    async def test_natural_request_without_fixed_question_words_can_use_acl_candidate(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(
            self.private_memory(
                "小王喜欢的面馆是云杉面馆。",
                memory_type="user_preference",
            )
        )
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(message_text="说说我喜欢的面馆"),
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("云杉面馆", injection)
        self.assertIn("不要依赖固定疑问词判断用户意图", injection)

    async def test_omitted_subject_recall_is_not_rejected_by_pronoun_rules(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory())
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(message_text="中午吃的是啥来着？"),
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("番茄鸡蛋面", injection)
        self.assertIn("普通陈述或意图不清时忽略", injection)

    async def test_private_acl_does_not_cross_bot_or_platform(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory())
        await self.allow_private_to_group(service)

        other_bot = await service._compose_memory_injection(
            self.group_context(bot_id="b2"),
            max_chars=3200,
            write_log=False,
        )
        other_platform = await service._compose_memory_injection(
            self.group_context(platform="other-platform"),
            max_chars=3200,
            write_log=False,
        )

        self.assertNotIn("番茄鸡蛋面", other_bot)
        self.assertNotIn("番茄鸡蛋面", other_platform)

    async def test_legacy_default_platform_private_memory_is_recalled_for_same_user(self) -> None:
        service = self.make_service()
        memory = self.private_memory("迁移摘要：中午吃过番茄鸡蛋面。")
        memory.platform = "default"
        memory.session_id = "default:FriendMessage:u1"
        await service.store.insert_memory(memory)
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(),
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("番茄鸡蛋面", injection)

    async def test_qq_memory_is_recalled_through_aiocqhttp_platform_alias(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory("QQ 历史记录：中午吃过番茄鸡蛋面。"))
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(platform="aiocqhttp"),
            max_chars=3200,
            write_log=False,
        )

        self.assertIn("番茄鸡蛋面", injection)

    def test_explicit_contextual_memory_query_keeps_recall_markers(self) -> None:
        service = self.make_service()
        self.assertFalse(
            service._should_replace_current_query_with_anchors(
                "还记得水蜜桃是什么情况吗",
                type("Signal", (), {"context_dependent": True, "low_information": False})(),
                ["水蜜桃", "情况"],
            )
        )

    async def test_seamless_acl_use_is_limited_to_private_memory_owner(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory())
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(user_id="u2", message_text="小王中午吃了什么？"),
            max_chars=3200,
            write_log=False,
        )

        self.assertNotIn("番茄鸡蛋面", injection)

    async def test_naming_another_member_never_opens_that_members_private_memory(self) -> None:
        service = self.make_service()
        other = self.private_memory("小李私聊里说过的保密餐点：松露披萨。")
        other.subject = EntityRef(kind="user", id="u2", name="小李")
        other.session_id = "qq:FriendMessage:u2"
        await service.store.insert_memory(other)
        await service.store.upsert_acl_rule(
            owner_scope="private",
            owner_id="u2",
            reader_scope="group",
            reader_id="g1",
            effect="allow",
        )

        injection = await service._compose_memory_injection(
            self.group_context(message_text="你还记得小李私聊里说过什么吗？"),
            max_chars=3200,
            write_log=False,
        )

        self.assertNotIn("松露披萨", injection)

    async def test_acl_revoke_removes_cached_private_group_result(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory())
        rule = await self.allow_private_to_group(service)
        ctx = self.group_context()

        first = await service._compose_memory_injection(ctx, max_chars=3200, write_log=False)
        second = await service._compose_memory_injection(ctx, max_chars=3200, write_log=False)
        self.assertIn("番茄鸡蛋面", first)
        self.assertIn("番茄鸡蛋面", second)

        await service.store.delete_acl_rule(rule["id"])
        revoked = await service._compose_memory_injection(ctx, max_chars=3200, write_log=False)
        self.assertNotIn("番茄鸡蛋面", revoked)

    async def test_recall_tool_uses_same_group_actor_guard(self) -> None:
        service = self.make_service()
        await service.store.insert_memory(self.private_memory())
        await self.allow_private_to_group(service)

        service.identity.resolve_event_context = AsyncMock(return_value=self.group_context())
        owner_result = await service.tool_recall(object(), "我中午吃了什么？")
        self.assertEqual(["小王明确说过：中午吃了番茄鸡蛋面。"], [item["content"] for item in owner_result["memories"]])
        self.assertIn("条件候选", owner_result["usage"])

        service.identity.resolve_event_context = AsyncMock(
            return_value=self.group_context(user_id="u2", message_text="小王中午吃了什么？")
        )
        other_result = await service.tool_recall(object(), "小王中午吃了什么？")
        self.assertEqual([], other_result["memories"])

    async def test_recall_tool_keeps_other_memory_slots_when_schedules_rank_first(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_text="共同召回锚点",
        )
        for index in range(8):
            await service.store.insert_memory(
                MemoryRecord(
                    id=f"schedule-{index}",
                    memory_type="schedule_fragment",
                    subject=EntityRef.bot_self("b1"),
                    object=EntityRef(kind="user", id="u1", name="小王"),
                    scope="private",
                    session_id=ctx.session_id,
                    platform="qq",
                    visibility="bot_self",
                    reality_level="persona_life",
                    lifecycle="stable_memory",
                    content=f"共同召回锚点日程 {index}",
                    confidence=1.0,
                    importance=1.0,
                    metadata={"owner_bot_id": "b1"},
                )
            )
        await service.store.insert_memory(
            MemoryRecord(
                id="profile-anchor",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self("b1"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="共同召回锚点对应用户喜欢无糖拿铁。",
                confidence=0.8,
                importance=0.6,
                metadata={"owner_bot_id": "b1"},
            )
        )
        await service.store.insert_memory(
            MemoryRecord(
                id="summary-anchor",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self("b1"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="共同召回锚点对应一次咖啡偏好对话。",
                confidence=0.8,
                importance=0.6,
                metadata={"owner_bot_id": "b1"},
            )
        )
        service.identity.resolve_event_context = AsyncMock(return_value=ctx)

        result = await service.tool_recall(object(), "共同召回锚点", top_k=5)
        memory_types = [item["memory_type"] for item in result["memories"]]

        self.assertIn("user_preference", memory_types)
        self.assertIn("conversation_summary", memory_types)
        self.assertLessEqual(memory_types.count("schedule_fragment"), 2)

    async def test_slot_fallback_does_not_overfill_schedule_results(self) -> None:
        service = self.make_service()
        evaluator = ImportanceEvaluator()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_text="泛化召回锚点",
        )
        for index in range(8):
            record = evaluator.calibrate(
                MemoryRecord(
                    id=f"only-schedule-{index}",
                    memory_type="schedule_fragment",
                    subject=EntityRef.bot_self("b1"),
                    object=EntityRef(kind="user", id="u1", name="小王"),
                    scope="private",
                    session_id=ctx.session_id,
                    platform="qq",
                    visibility="bot_self",
                    reality_level="persona_life",
                    lifecycle="stable_memory",
                    content=f"泛化召回锚点：明天提醒处理日程记录 {index}",
                    confidence=1.0,
                    importance=1.0,
                    metadata={"owner_bot_id": "b1"},
                ),
                source="schedule_test",
            )
            self.assertGreaterEqual(float(record.metadata.get("promise_weight") or 0.0), 0.35)
            await service.store.insert_memory(
                record
            )
        results, _blocked, slot_map = await service.search_context_slots(
            "泛化召回锚点",
            ctx,
            top_k=8,
            admin_read_all=True,
        )

        self.assertEqual(2, len(results))
        self.assertEqual({"schedule_fragment"}, {item.memory.memory_type for item in results})
        self.assertEqual(2, len(slot_map.get("self_timeline", [])))
        self.assertEqual([], slot_map.get("open_loop", []))

    async def test_non_schedule_slot_can_fill_remaining_results(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_text="偏好扩展锚点",
        )
        for index in range(8):
            await service.store.insert_memory(
                MemoryRecord(
                    id=f"profile-only-{index}",
                    memory_type="user_preference",
                    subject=EntityRef(kind="user", id="u1", name="小王"),
                    object=EntityRef.bot_self("b1"),
                    scope="private",
                    session_id=ctx.session_id,
                    platform="qq",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    content=f"偏好扩展锚点记录 {index}",
                    confidence=1.0,
                    importance=1.0,
                    metadata={"owner_bot_id": "b1"},
                )
            )

        results, _blocked, slot_map = await service.search_context_slots(
            "偏好扩展锚点",
            ctx,
            top_k=8,
            admin_read_all=True,
        )

        self.assertEqual(8, len(results))
        self.assertEqual(8, len(slot_map.get("user_profile", [])))

    async def test_slot_selection_gives_each_available_slot_a_first_chance(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_text="全槽召回锚点",
        )
        records = (
            MemoryRecord(
                id="all-slots-open-loop",
                memory_type="timeline_event",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self("b1"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="全槽召回锚点未完成事项",
                importance=1.0,
                metadata={"owner_bot_id": "b1", "open_loop_weight": 0.9},
            ),
            MemoryRecord(
                id="all-slots-self-timeline",
                memory_type="schedule_fragment",
                subject=EntityRef.bot_self("b1"),
                object=EntityRef(kind="user", id="u1", name="小王"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="bot_self",
                reality_level="persona_life",
                lifecycle="stable_memory",
                content="全槽召回锚点日程",
                importance=1.0,
                metadata={"owner_bot_id": "b1"},
            ),
            MemoryRecord(
                id="all-slots-user-profile",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self("b1"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="全槽召回锚点用户偏好",
                importance=1.0,
                metadata={"owner_bot_id": "b1"},
            ),
            MemoryRecord(
                id="all-slots-current-window",
                memory_type="timeline_event",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self("b1"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="全槽召回锚点当前窗口",
                importance=1.0,
                metadata={"owner_bot_id": "b1"},
            ),
            MemoryRecord(
                id="all-slots-summary",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self("b1"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="全槽召回锚点对话总结",
                importance=1.0,
                metadata={"owner_bot_id": "b1"},
            ),
            MemoryRecord(
                id="all-slots-stable",
                memory_type="timeline_event",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef(kind="group", id="g1", name="测试群"),
                scope="group",
                session_id="qq:GroupMessage:g1",
                platform="qq",
                group_id="g1",
                visibility="group_public",
                lifecycle="stable_memory",
                content="全槽召回锚点稳定记忆",
                importance=1.0,
                metadata={"owner_bot_id": "b1"},
            ),
        )
        for record in records:
            await service.store.insert_memory(record)

        results, _blocked, slot_map = await service.search_context_slots(
            "全槽召回锚点",
            ctx,
            top_k=6,
            admin_read_all=True,
        )

        self.assertEqual(6, len(results))
        self.assertEqual(
            {
                "open_loop",
                "self_timeline",
                "user_profile",
                "current_window",
                "conversation_summary",
                "stable_memory",
            },
            set(slot_map),
        )

    def test_self_timeline_overflow_intent_boundaries(self) -> None:
        service = self.make_service()
        cases = {
            "项目计划是什么？": False,
            "你的项目计划有哪些？": False,
            "下周版本发布安排是什么？": False,
            "我的日程有哪些？": False,
            "我今天的安排是什么？": False,
            "你能查一下我的日程吗？": False,
            "你记得我今天的安排吗？": False,
            "你知道我的下周计划吗？": False,
            "你觉得我明天有空吗？": False,
            "小王的日程有哪些？": False,
            "小王明天有安排吗？": False,
            "会议日程有哪些？": False,
            "群活动安排是什么？": False,
            "明天考试有什么安排？": False,
            "课程安排有哪些？": False,
            "请规划一份日程": False,
            "行程规划算法": False,
            "my schedule": False,
            "project schedule": False,
            "现在几点？": False,
            "今天是什么日子？": False,
            "你知道今天几点了吗？": False,
            "你的日程有哪些？": True,
            "你今天的安排是什么？": True,
            "今晚你有空吗？": True,
            "明天有空吗？": True,
            "明天有安排吗？": True,
            "你什么时候上班？": True,
            "你什么时候有空？": True,
            "你的任务安排是什么？": True,
            "b1 的日程": True,
            "your schedule": True,
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                intent = parse_time_intent(query)
                self.assertEqual(
                    expected,
                    service._query_focuses_self_timeline(
                        query,
                        time_intent=intent if intent.active else None,
                        bot_id="b1",
                    ),
                )

    async def test_calibrated_open_loop_records_obey_default_slot_cap(self) -> None:
        service = self.make_service()
        evaluator = ImportanceEvaluator()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_text="开放事项召回锚点",
        )
        for index in range(8):
            record = evaluator.calibrate(
                MemoryRecord(
                    id=f"calibrated-open-loop-{index}",
                    memory_type="timeline_event",
                    subject=EntityRef(kind="user", id="u1", name="小王"),
                    object=EntityRef.bot_self("b1"),
                    scope="private",
                    session_id=ctx.session_id,
                    platform="qq",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    content=f"开放事项召回锚点：明天提醒处理记录 {index}",
                    confidence=1.0,
                    importance=1.0,
                    metadata={"owner_bot_id": "b1"},
                ),
                source="schedule_test",
            )
            self.assertGreaterEqual(float(record.metadata.get("open_loop_weight") or 0.0), 0.35)
            await service.store.insert_memory(record)

        results, _blocked, slot_map = await service.search_context_slots(
            "开放事项召回锚点",
            ctx,
            top_k=8,
            admin_read_all=True,
        )

        self.assertEqual(1, len(slot_map.get("open_loop", [])))
        self.assertEqual(1, len(results))

    async def test_bot_schedule_identity_beats_calibrated_open_loop_weight(self) -> None:
        service = self.make_service()
        evaluator = ImportanceEvaluator()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_text="Bot日程召回锚点",
        )
        for index in range(5):
            record = evaluator.calibrate(
                MemoryRecord(
                    id=f"bot-open-loop-schedule-{index}",
                    memory_type="self_action",
                    subject=EntityRef.bot_self("b1"),
                    object=EntityRef(kind="user", id="u1", name="小王"),
                    scope="private",
                    session_id=ctx.session_id,
                    platform="qq",
                    visibility="bot_self",
                    reality_level="bot_action",
                    lifecycle="stable_memory",
                    content=f"Bot日程召回锚点：明天提醒处理安排 {index}",
                    confidence=1.0,
                    importance=1.0,
                    metadata={"owner_bot_id": "b1"},
                ),
                source="schedule_test",
            )
            self.assertGreaterEqual(float(record.metadata.get("open_loop_weight") or 0.0), 0.35)
            await service.store.insert_memory(record)

        results, _blocked, slot_map = await service.search_context_slots(
            "Bot日程召回锚点",
            ctx,
            top_k=5,
            admin_read_all=True,
        )

        self.assertEqual(5, len(results))
        self.assertEqual(5, len(slot_map.get("self_timeline", [])))
        self.assertEqual([], slot_map.get("open_loop", []))

    async def test_explicit_schedule_query_can_fill_self_timeline_slot(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_text="你的日程锚点有哪些？",
        )
        for index in range(8):
            await service.store.insert_memory(
                MemoryRecord(
                    id=f"focused-schedule-{index}",
                    memory_type="schedule_fragment",
                    subject=EntityRef.bot_self("b1"),
                    object=EntityRef(kind="user", id="u1", name="小王"),
                    scope="private",
                    session_id=ctx.session_id,
                    platform="qq",
                    visibility="bot_self",
                    reality_level="persona_life",
                    lifecycle="stable_memory",
                    content=f"日程锚点安排 {index}",
                    confidence=1.0,
                    importance=1.0,
                    metadata={"owner_bot_id": "b1"},
                )
            )
        await service.store.insert_memory(
            MemoryRecord(
                id="focused-profile",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self("b1"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="日程锚点相关的用户时间偏好。",
                confidence=0.8,
                importance=0.7,
                metadata={"owner_bot_id": "b1"},
            )
        )
        await service.store.insert_memory(
            MemoryRecord(
                id="focused-summary",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self("b1"),
                scope="private",
                session_id=ctx.session_id,
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="日程锚点相关的一次安排对话。",
                confidence=0.8,
                importance=0.7,
                metadata={"owner_bot_id": "b1"},
            )
        )

        results, _blocked, slot_map = await service.search_context_slots(
            "你的日程锚点有哪些？",
            ctx,
            top_k=8,
            admin_read_all=True,
        )

        self.assertEqual(8, len(results))
        self.assertEqual(6, len(slot_map.get("self_timeline", [])))
        self.assertEqual(1, len(slot_map.get("user_profile", [])))
        self.assertEqual(1, len(slot_map.get("conversation_summary", [])))

    async def test_old_explicit_meal_memory_is_not_mistaken_for_current_state(self) -> None:
        service = self.make_service()
        old_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
        await service.store.insert_memory(self.private_memory(occurred_at=old_time))
        await self.allow_private_to_group(service)

        injection = await service._compose_memory_injection(
            self.group_context(),
            max_chars=3200,
            write_log=False,
        )

        self.assertNotIn("番茄鸡蛋面", injection)

        recalled = await service._compose_memory_injection(
            self.group_context(message_text="你还记得我上次中午吃了什么吗？"),
            max_chars=3200,
            write_log=False,
        )
        self.assertIn("番茄鸡蛋面", recalled)


if __name__ == "__main__":
    unittest.main()
