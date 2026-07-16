from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


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


class _CapturingProvider:
    def __init__(self, text: str):
        self.text = text
        self.prompt = ""

    async def text_chat(self, **kwargs):
        self.prompt = str(kwargs.get("prompt") or "")
        return _Response(self.text)


class SummaryAndRelationshipTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None, *, context=None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=context,
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

    async def test_short_group_reply_chain_keeps_only_quote_relevant_memories(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            group_id="g1",
            user_id="u1",
            bot_id="b1",
            message_text="让比折给你送",
        )
        event = SimpleNamespace(
            private_companion_reply_message_chain=[
                {
                    "message_id": "quoted-1",
                    "depth": 1,
                    "text": "可不是嘛，界园欠我一个送包子的信使呢！",
                }
            ]
        )
        relevant_open_loop = SearchResult(
            MemoryRecord(id="package-promise", content="答应等信使打完界园后送包子。"),
            2.4,
        )
        unrelated_schedule = SearchResult(
            MemoryRecord(id="unrelated-school", content="Bot 自称不是小机器人而是普通高中生。"),
            2.3,
        )
        relevant_action = SearchResult(
            MemoryRecord(id="package-action", content="建议先找零食，等界园里的信使送包子。"),
            2.2,
        )
        relevant_summary = SearchResult(
            MemoryRecord(id="package-summary", content="群里讨论了界园路线和送包子的安排。"),
            2.1,
        )
        blocked: list[dict] = []

        anchor = service._short_reply_chain_anchor(ctx, event)
        filtered = service._filter_short_reply_chain_slots(
            {
                "open_loop": [relevant_open_loop],
                "self_timeline": [unrelated_schedule, relevant_action],
                "conversation_summary": [relevant_summary],
            },
            anchor,
            blocked,
        )
        selected_ids = {item.memory.id for items in filtered.values() for item in items}

        self.assertIn("界园", anchor)
        self.assertEqual({"package-promise", "package-action", "package-summary"}, selected_ids)
        self.assertTrue(any(item.get("id") == "unrelated-school" for item in blocked))
        self.assertLessEqual(sum(len(items) for items in filtered.values()), 3)

    async def test_main_injection_applies_short_quote_limits_and_actor_guard(self) -> None:
        service = self.make_service(
            {
                "memory_injection": {"enable_injection_logs": False, "max_chars": 1800},
                "conversation_memory_advanced": {
                    "low_information_guard_enabled": False,
                    "topic_shift_guard_enabled": False,
                },
            }
        )
        ctx = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            group_id="g1",
            user_id="u1",
            bot_id="b1",
            message_text="让比折给你送",
        )
        event = SimpleNamespace(
            private_companion_reply_message_chain=[
                {
                    "message_id": "quoted-1",
                    "depth": 1,
                    "text": "可不是嘛，界园欠我一个送包子的信使呢！",
                }
            ]
        )
        relevant_open_loop = SearchResult(
            MemoryRecord(id="package-promise", content="答应等信使打完界园后送包子。"),
            2.4,
        )
        unrelated_schedule = SearchResult(
            MemoryRecord(id="unrelated-school", content="Bot 自称不是小机器人而是普通高中生。"),
            2.3,
        )
        relevant_action = SearchResult(
            MemoryRecord(id="package-action", content="建议先找零食，等界园里的信使送包子。"),
            2.2,
        )
        relevant_summary = SearchResult(
            MemoryRecord(id="package-summary", content="群里讨论了界园路线和送包子的安排。"),
            2.1,
        )
        relevant_window = SearchResult(
            MemoryRecord(id="package-window", content="刚才仍在聊界园和包子。"),
            2.0,
        )

        async def fake_search_context_slots(*_args, **_kwargs):
            slot_map = {
                "open_loop": [relevant_open_loop],
                "self_timeline": [unrelated_schedule, relevant_action],
                "conversation_summary": [relevant_summary],
                "current_window": [relevant_window],
            }
            return list(slot_map.values())[0], [], slot_map

        service.search_context_slots = fake_search_context_slots
        captured: dict[str, object] = {}
        original_compose = service.injection.compose

        def capture_compose(*args, **kwargs):
            captured.update(kwargs)
            if len(args) >= 3:
                captured["max_chars"] = args[2]
            return original_compose(*args, **kwargs)

        service.injection.compose = capture_compose
        req = SimpleNamespace(prompt="", system_prompt="", contexts=[], extra_user_content_parts=[])

        await service.inject_memories(ctx, req, event=event)

        state = getattr(req, "memory_companion_injection_state", {})
        self.assertTrue(state.get("injected"))
        self.assertEqual(
            {"package-promise", "package-action", "package-summary"},
            set(state.get("selected_memory_ids") or []),
        )
        self.assertNotIn("unrelated-school", state.get("selected_memory_ids") or [])
        self.assertLessEqual(int(captured.get("max_chars") or 0), 1050)
        self.assertTrue(captured.get("compact_memory"))
        self.assertIn("人物、动作和地点尽量按原句对应", str(captured.get("intent_context") or ""))

    async def test_recent_fact_guard_keeps_shower_fact_and_bot_acknowledgement(self) -> None:
        self.assertEqual(set(), MemoryCompanionService._recent_fact_categories("你刚洗完澡吗？"))
        self.assertEqual(set(), MemoryCompanionService._recent_fact_categories("我问你洗澡了吗？"))
        self.assertEqual(
            {"meal", "bath"},
            MemoryCompanionService._recent_fact_categories("早吃过啦~刚才洗澡去了~"),
        )
        service = self.make_service(
            {
                "conversation_memory_advanced": {
                    "recent_fact_guard_enabled": True,
                    "recent_fact_guard_hours": 3,
                    "recent_fact_guard_event_limit": 24,
                    "recent_fact_guard_max_items": 4,
                }
            }
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_text="我哪里凶你了，你不要冤枉人",
        )
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id=ctx.session_id,
            scope=ctx.scope,
            subject_id=ctx.user_id,
            object_id=ctx.user_id,
            content="早吃过啦~刚才洗澡去了~",
            metadata={"message_id": "shower-user"},
        )
        await service.store.add_timeline_event(
            event_type="bot_response",
            session_id=ctx.session_id,
            scope=ctx.scope,
            subject_id=ctx.bot_id,
            object_id=ctx.user_id,
            content="洗完澡是不是舒服多啦？",
            metadata={"message_id": "shower-bot"},
        )

        recent_context = await service._recent_fact_guard_context(ctx)
        injected = service.injection.compose(
            ctx,
            [],
            max_chars=1800,
            recent_fact_context=recent_context,
        )
        bridged = await service.bridge_compose_injection(
            "不是这样",
            session_context=ctx,
            max_chars=1800,
        )

        self.assertIn("刚才洗澡去了", recent_context)
        self.assertIn("Bot 随后已围绕此事回应", recent_context)
        self.assertIn("洗完澡是不是舒服多啦", recent_context)
        self.assertIn("<recent_fact_context>", injected)
        self.assertIn("<recent_fact_context>", bridged)
        self.assertIn("优先自然承认刚才没接住", injected)

    async def test_topic_shift_guard_does_not_trim_astrbot_conversation_history(self) -> None:
        service = self.make_service(
            {
                "memory_injection": {"enable_injection_logs": False},
                "retrieval": {"mode": "basic"},
                "conversation_memory_advanced": {
                    "topic_shift_guard_enabled": True,
                    "suppress_memory_on_topic_shift": True,
                },
            }
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_text="给我发一张自拍",
        )
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id=ctx.session_id,
            scope=ctx.scope,
            subject_id=ctx.user_id,
            object_id=ctx.user_id,
            content="刚才吃过晚饭，已经回宿舍了。",
            metadata={"message_id": "state-before-photo"},
        )
        original_contexts = [
            {"role": "user", "content": "早吃过啦，刚才洗澡去了。"},
            {"role": "assistant", "content": "洗完澡舒服多啦？"},
            {"role": "user", "content": "想看看你的自拍。"},
            {"role": "assistant", "content": "等我一下。"},
            {"role": "user", "content": "拍好了吗？"},
            {"role": "assistant", "content": "快好啦。"},
        ]
        req = SimpleNamespace(
            prompt="",
            system_prompt="",
            contexts=[dict(item) for item in original_contexts],
            extra_user_content_parts=[],
        )

        await service.inject_memories(ctx, req)

        self.assertEqual(original_contexts, req.contexts)

    async def test_cold_joke_request_skips_group_long_term_retrieval(self) -> None:
        service = self.make_service({"memory_injection": {"enable_injection_logs": False}})
        ctx = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            group_id="g1",
            user_id="u1",
            bot_id="b1",
            message_text="给我讲个冷笑话",
        )

        async def fail_if_called(*_args, **_kwargs):
            raise AssertionError("standalone generation must not start long-term retrieval")

        service.search_context_slots = fail_if_called
        captured: dict[str, object] = {}
        original_compose = service.injection.compose

        def capture_compose(*args, **kwargs):
            captured["result_count"] = len(args[1]) if len(args) > 1 else -1
            captured["intent_context"] = kwargs.get("intent_context", "")
            return original_compose(*args, **kwargs)

        service.injection.compose = capture_compose
        req = SimpleNamespace(prompt="", system_prompt="", contexts=[], extra_user_content_parts=[])

        await service.inject_memories(ctx, req)

        self.assertEqual(0, captured.get("result_count"))
        self.assertIn("独立的轻量创作请求", str(captured.get("intent_context") or ""))
        state = getattr(req, "memory_companion_injection_state", {})
        self.assertEqual([], state.get("selected_memory_ids") or [])

    async def test_personalized_story_request_still_runs_long_term_retrieval(self) -> None:
        service = self.make_service({"memory_injection": {"enable_injection_logs": False}})
        ctx = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            group_id="g1",
            user_id="u1",
            bot_id="b1",
            message_text="给我讲个符合我性格的故事",
        )
        called = False

        async def fake_search(*_args, **_kwargs):
            nonlocal called
            called = True
            return [], [], {}

        service.search_context_slots = fake_search
        req = SimpleNamespace(prompt="", system_prompt="", contexts=[], extra_user_content_parts=[])

        await service.inject_memories(ctx, req)

        self.assertTrue(called)
        state = getattr(req, "memory_companion_injection_state", {})
        self.assertTrue(state.get("injected"))

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
        with self.assertRaisesRegex(TimeoutError, "总结模型在 0.01 秒内未返回"):
            await summarizer.summarize_with_provider(
                _TextProvider('{"summary":"ok"}', delay=0.1),
                rows=rows,
                session_label="私聊 u1",
            )

    async def test_summary_provider_attempts_do_not_repeat_same_runtime_provider(self) -> None:
        provider = _TextProvider('{"summary":"ok"}')

        async def get_provider_by_id(_provider_id):
            return provider

        async def get_using_provider(_session_id):
            return provider

        context = SimpleNamespace(
            get_provider_by_id=get_provider_by_id,
            get_using_provider=get_using_provider,
        )
        service = self.make_service(
            {
                "memory_summary": {
                    "provider_id": "ollama-summary",
                    "fallback_provider_id": "ollama-fallback",
                }
            },
            context=context,
        )

        attempts = await service._summary_provider_attempts(
            SessionContext(session_id="qq:FriendMessage:u1", scope="private", user_id="u1")
        )

        self.assertEqual(1, len(attempts))
        self.assertEqual("primary", attempts[0]["source"])
        self.assertIs(provider, attempts[0]["provider"])

    async def test_summary_reports_only_rows_actually_sent_to_provider(self) -> None:
        summarizer = MemorySummarizer(max_input_chars=1000, provider_timeout_seconds=1)
        rows = [
            {
                "id": f"event-{index}",
                "event_type": "user_message",
                "scope": "private",
                "subject_id": "u1",
                "content": f"第{index}条" + ("很长的消息" * 120),
                "occurred_at": f"2026-07-15T0{index}:00:00+08:00",
            }
            for index in range(1, 4)
        ]
        provider = _CapturingProvider(
            json.dumps(
                {
                    "summary": "只总结实际看到的消息。",
                    "canonical_summary": "已消费事件摘要。",
                    "key_facts": ["事件有明确证据"],
                    "importance": 0.6,
                },
                ensure_ascii=False,
            )
        )

        payload = await summarizer.summarize_with_provider(provider, rows=rows, session_label="测试")

        consumed = payload.get("_consumed_event_ids") or []
        self.assertGreaterEqual(len(consumed), 1)
        self.assertLess(len(consumed), len(rows))
        self.assertIn(consumed[-1], provider.prompt)
        self.assertNotIn(rows[-1]["id"], provider.prompt)

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
