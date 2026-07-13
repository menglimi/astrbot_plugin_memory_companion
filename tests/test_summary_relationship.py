from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core.bridge import MemoryCompanionBridge
from astrbot_plugin_remember_you.core.models import EntityRef, MemoryRecord, SearchResult, SessionContext
from astrbot_plugin_remember_you.core.service import MemoryCompanionService
from astrbot_plugin_remember_you.core.summarizer import MemorySummarizer


class _Response:
    def __init__(self, text: str):
        self.completion_text = text


class _TextProvider:
    def __init__(self, text: str, delay: float = 0.0):
        self.text = text
        self.delay = delay

    async def text_chat(self, **_kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return _Response(self.text)


class SummaryAndRelationshipTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_async_close_finishes_background_cancellation_before_store_close(self) -> None:
        service = self.make_service()
        started = asyncio.Event()
        finalized = asyncio.Event()

        async def background_work() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finalized.set()

        task = service._spawn_background(background_work(), label="shutdown_test")
        self.assertIsNotNone(task)
        await started.wait()

        await service.aclose()

        self.assertTrue(finalized.is_set())
        self.assertTrue(task.done())
        self.assertTrue(service.store._closed)

    async def test_fast_context_capabilities_can_be_rolled_back_independently(self) -> None:
        service = self.make_service(
            {
                "private_companion_bridge": {
                    "enabled": True,
                    "schedule_fast_context_enabled": False,
                    "outfit_fast_context_enabled": True,
                }
            }
        )

        status = service.companion_coordination_status()

        self.assertFalse(status["schedule_fast_context"])
        self.assertTrue(status["outfit_fast_context"])

    async def test_schedule_fast_context_skips_semantic_providers_and_unrelated_memory(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            message_text="Private Companion 日程连续性",
        )
        await service.store.insert_memory(
            MemoryRecord(
                id="fast-schedule",
                memory_type="schedule_fragment",
                subject=EntityRef.bot_self(),
                object=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id=ctx.session_id,
                visibility="bot_self",
                reality_level="persona_life",
                lifecycle="stable_memory",
                content="傍晚回来继续剪视频。",
            )
        )
        await service.store.insert_memory(
            MemoryRecord(
                id="unrelated-summary",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1"),
                object=EntityRef.bot_self(),
                scope="private",
                session_id=ctx.session_id,
                visibility="private_pair",
                lifecycle="stable_memory",
                content="一段与日程无关的旧聊天。",
            )
        )
        await service.store.insert_memory(
            MemoryRecord(
                id="unrelated-manual",
                memory_type="manual_memory",
                subject=EntityRef(kind="user", id="u1"),
                object=EntityRef.bot_self(),
                scope="private",
                session_id=ctx.session_id,
                visibility="private_pair",
                lifecycle="stable_memory",
                content="用户明确记住过一条与日程无关的内衣话题。",
            )
        )
        await service.store.insert_memory(
            MemoryRecord(
                id="unrelated-preference",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="u1"),
                object=EntityRef.bot_self(),
                scope="private",
                session_id=ctx.session_id,
                visibility="private_pair",
                lifecycle="stable_memory",
                content="用户喜欢胖次话题。",
            )
        )

        async def fail_if_called(*_args, **_kwargs):
            raise AssertionError("generic retrieval engine must not run for schedule_fast")

        service._retrieval_engine = fail_if_called
        text = await service.bridge_compose_context(
            query=ctx.message_text,
            session_context=ctx,
            top_k=5,
            max_chars=1200,
            retrieval_profile="schedule_fast",
        )

        self.assertIn("傍晚回来继续剪视频", text)
        self.assertNotIn("与日程无关的旧聊天", text)
        self.assertNotIn("内衣话题", text)
        self.assertNotIn("胖次话题", text)
        self.assertEqual("schedule_fast_local", service._last_retrieval_path_info["path"])
        self.assertEqual("skipped_schedule_fast", service._last_retrieval_path_info["embedding_reason"])

    async def test_outfit_fast_context_balances_history_schedule_preference_and_photo(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            message_text="今日穿搭、历史穿搭、服装偏好和最近自拍",
        )
        records = [
            MemoryRecord(
                id="outfit-schedule",
                memory_type="schedule_fragment",
                subject=EntityRef.bot_self(),
                object=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id=ctx.session_id,
                visibility="bot_self",
                reality_level="persona_life",
                lifecycle="stable_memory",
                content="今天下午需要出门，天气偏凉。",
            ),
            MemoryRecord(
                id="private_companion_daily_outfit_2026-07-13",
                memory_type="persona_life",
                subject=EntityRef.bot_self(),
                scope="unknown",
                session_id="private_companion:daily_outfit",
                visibility="bot_self",
                reality_level="persona_life",
                lifecycle="stable_memory",
                content="昨天的每日穿搭图使用了白色短袖和深蓝半裙。",
                tags=["daily_outfit", "clothing"],
            ),
            MemoryRecord(
                id="outfit-preference",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="u1"),
                object=EntityRef.bot_self(),
                scope="private",
                session_id=ctx.session_id,
                visibility="private_pair",
                lifecycle="stable_memory",
                content="用户更喜欢浅蓝色外套和简洁配色。",
            ),
            MemoryRecord(
                id="outfit-photo",
                memory_type="image_action",
                subject=EntityRef.bot_self(),
                object=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id=ctx.session_id,
                visibility="bot_self",
                reality_level="bot_action",
                lifecycle="stable_memory",
                content="最近一张自拍是在窗边拍的半身照。",
            ),
            MemoryRecord(
                id="outfit-unrelated",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1"),
                object=EntityRef.bot_self(),
                scope="private",
                session_id=ctx.session_id,
                visibility="private_pair",
                lifecycle="stable_memory",
                content="一段与穿搭完全无关的旧聊天。",
            ),
            MemoryRecord(
                id="outfit-unrelated-image",
                memory_type="image_action",
                subject=EntityRef.bot_self(),
                object=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id=ctx.session_id,
                visibility="bot_self",
                reality_level="bot_action",
                lifecycle="stable_memory",
                content="最近生成了一张数据库架构示意图。",
            ),
        ]
        for record in records:
            await service.store.insert_memory(record)

        async def fail_if_called(*_args, **_kwargs):
            raise AssertionError("generic retrieval engine must not run for outfit_fast")

        service._retrieval_engine = fail_if_called
        text = await service.bridge_compose_context(
            query=ctx.message_text,
            session_context=ctx,
            top_k=5,
            max_chars=1400,
            retrieval_profile="outfit_fast",
        )

        self.assertIn("天气偏凉", text)
        self.assertIn("白色短袖和深蓝半裙", text)
        self.assertIn("浅蓝色外套和简洁配色", text)
        self.assertIn("窗边拍的半身照", text)
        self.assertNotIn("与穿搭完全无关", text)
        self.assertNotIn("数据库架构", text)
        self.assertEqual("outfit_fast_local", service._last_retrieval_path_info["path"])
        self.assertEqual("skipped_outfit_fast", service._last_retrieval_path_info["embedding_reason"])
        self.assertTrue(service.companion_coordination_status()["outfit_fast_context"])

    async def test_non_json_summary_is_rejected(self) -> None:
        summarizer = MemorySummarizer(provider_timeout_seconds=1)
        rows = [{"content": "一条需要总结的消息", "scope": "private", "subject_id": "u1"}]
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            await summarizer.summarize_with_provider(
                _TextProvider("这不是 JSON，只是一段自由文本"),
                rows=rows,
                session_label="私聊 u1",
            )

    async def test_summary_provider_timeout_is_enforced(self) -> None:
        summarizer = MemorySummarizer(provider_timeout_seconds=0.01)
        rows = [{"content": "一条需要总结的消息", "scope": "private", "subject_id": "u1"}]
        with self.assertRaises(TimeoutError):
            await summarizer.summarize_with_provider(
                _TextProvider('{"summary":"ok"}', delay=0.1),
                rows=rows,
                session_label="私聊 u1",
            )

    async def test_retry_exhaustion_preserves_unsummarized_timeline(self) -> None:
        service = self.make_service(
            {
                "memory_summary": {
                    "enabled": True,
                    "min_events": 1,
                    "trigger_event_count": 1,
                    "max_retries": 1,
                }
            }
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
        )
        timeline_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id=ctx.session_id,
            scope=ctx.scope,
            subject_id=ctx.user_id,
            object_id=ctx.user_id,
            content="不能丢失的原始时间线",
            metadata={"message_id": "m-dead-letter"},
        )
        await service.store.record_summary_failure(
            session_id=ctx.session_id,
            scope=ctx.scope,
            start_timeline_id=timeline_id,
            end_timeline_id=timeline_id,
            error="provider failed",
        )

        self.assertEqual("", await service.maybe_summarize_session(ctx))
        row = service.store._conn.execute(
            "SELECT summarized_at FROM timeline WHERE id=?", (timeline_id,)
        ).fetchone()
        self.assertEqual("", row["summarized_at"])
        failure = await service.store.get_summary_failure(ctx.session_id)
        self.assertEqual("dead_letter", failure["metadata"]["state"])

    async def test_one_message_advances_relationship_at_most_once(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_id="turn-1",
        )
        results = [
            SearchResult(
                MemoryRecord(id=f"m{index}", metadata={"emotional_weight": 0.9, "relationship_weight": 0.7}),
                score=1.0,
            )
            for index in range(3)
        ]

        service._maybe_record_persona_touch(ctx, results)
        service._maybe_record_persona_touch(ctx, results)
        state = service._get_relationship_phase(ctx)
        self.assertEqual(1, state["touch_count"])
        self.assertEqual(["turn-1"], state["recent_touch_message_ids"])
        saved = json.loads(service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8"))
        self.assertIn(service._phase_key(ctx), saved)

    async def test_intermediate_relationship_phase_can_downgrade(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )
        state = {"phase": "close", "momentum": -0.25, "touch_count": 10}
        service._maybe_transition_phase(ctx, state)
        self.assertEqual("familiar", state["phase"])

    async def test_phase_key_isolates_bot_and_group_member_and_bridge_normalizes(self) -> None:
        service = self.make_service()
        first = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            group_id="g1",
            user_id="u1",
            bot_id="b1",
        )
        second_member = SessionContext(
            session_id=first.session_id,
            scope="group",
            platform="qq",
            group_id="g1",
            user_id="u2",
            bot_id="b1",
        )
        second_bot = SessionContext(
            session_id=first.session_id,
            scope="group",
            platform="qq",
            group_id="g1",
            user_id="u1",
            bot_id="b2",
        )
        self.assertNotEqual(service._phase_key(first), service._phase_key(second_member))
        self.assertNotEqual(service._phase_key(first), service._phase_key(second_bot))

        private = SessionContext(
            session_id="qq:FriendMessage:u9",
            scope="private",
            platform="qq",
            user_id="u9",
            bot_id="b1",
        )
        state = service._get_relationship_phase(private)
        state["phase"] = "close"
        bridge = MemoryCompanionBridge(service)
        bridged = bridge.get_relationship_phase(session_id=private.session_id, scope="private")
        self.assertIs(state, bridged)


if __name__ == "__main__":
    unittest.main()
