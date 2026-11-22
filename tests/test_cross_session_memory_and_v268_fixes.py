from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jsonschema import Draft202012Validator

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.assertions import (
    SITUATIONAL_ASSERTION_TTL_DAYS,
    assertion_is_promotable,
    assertion_is_short_term_visible,
    normalize_assertion,
)
from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.query_session import (
    bind_query_tool_v3_schema,
    offer_query_tool,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer
from astrbot_plugin_memory_companion.core.time_intent import TimeIntent
from astrbot_plugin_memory_companion.core.vector_search import memory_time_ranges

CONTRACT_ROOT = ROOT / "docs/contracts/source-query/v1"
SOURCE_RESULT_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACT_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
)


class Plain:
    def __init__(self, text: str):
        self.text = text


class At:
    def __init__(self, qq: str):
        self.qq = qq


class _QueuedProvider:
    def __init__(self, responses: list[dict | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(completion_text=json.dumps(item, ensure_ascii=False))


class _DummyTool:
    def __init__(self, name: str, handler, path: str = "memory.test.main"):
        self.name = name
        self.handler = handler
        self.handler_module_path = path
        self.parameters: dict = {}
        self.description = "tool"
        self.active = True


class _DummyToolSet:
    def __init__(self, tools: list[_DummyTool]):
        self.tools = list(tools)

    def names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    def get_tool(self, name: str):
        return next((tool for tool in self.tools if tool.name == name), None)


def _make_v3_toolset() -> tuple[_DummyToolSet, SimpleNamespace]:
    async def wrapper(event, operation="status", parameters=None):
        return ""

    async def discover(event, query, terms=None, start_at="", end_at="", limit=0):
        return ""

    tools = [
        _DummyTool("memory_companion_query", wrapper),
        _DummyTool("memory_companion_discover_sources", discover),
    ]
    for op in ("recall", "sources", "navigate", "events"):
        async def legacy(event, **kwargs):
            return ""

        tools.append(_DummyTool(f"memory_companion_{op}", legacy))
    manager = SimpleNamespace(
        get_func=lambda name: next((tool for tool in tools if tool.name == name), None)
    )
    assert bind_query_tool_v3_schema(manager, "memory.test.main")
    return _DummyToolSet(tools), manager


class CrossSessionMemoryAndV268FixesTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base_config: dict = {
            "startup": {"background_grace_seconds": 60},
            "retrieval": {"mode": "basic"},
            "memory_injection": {"enable_injection_logs": False, "max_chars": 2400},
            "memory_summary": {
                "min_events": 1,
                "trigger_event_count": 1,
                "max_events_per_summary": 20,
                "max_retries": 3,
                "retry_backoff_seconds": 0,
                "max_calls_per_session_hour": 60,
            },
            "conversation_memory": {
                "capture_group_messages": True,
                "group_capture_engagement_only": False,
                "capture_private_messages": True,
            },
            "conversation_memory_advanced": {
                "cross_window_recent_continuity_enabled": True,
                "cross_window_recent_minutes": 30,
                "cross_window_recent_event_limit": 6,
                "cross_window_group_to_private_enabled": True,
                "cross_window_private_to_group_enabled": True,
                "cross_window_group_to_group_enabled": True,
                "low_information_guard_enabled": False,
                "topic_shift_guard_enabled": False,
            },
        }
        if config:
            for section, values in config.items():
                if isinstance(values, dict) and isinstance(base_config.get(section), dict):
                    base_config[section] = {**base_config[section], **values}
                else:
                    base_config[section] = values
        service = MemoryCompanionService(
            context=None,
            config=base_config,
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        service._schedule_memory_embedding = lambda *args, **kwargs: None
        return service

    @staticmethod
    def _meta(
        *,
        bot_id: str,
        user_id: str,
        platform: str = "onebot_qq",
        persona_id: str = "persona-main",
        sender_name: str = "",
    ) -> dict[str, str]:
        data = {
            "owner_bot_id": bot_id,
            "bot_id": bot_id,
            "platform": platform,
            "persona_id": persona_id,
            "participant_user_id": user_id,
            "participant_user_name": sender_name or user_id,
        }
        if sender_name:
            data["sender_name"] = sender_name
        return data

    # ------------------------------------------------------------------
    # Summary generic-person warning, lightweight style repair,
    # and short-TTL auto-visible situational assertions
    # ------------------------------------------------------------------

    def test_collective_group_member_phrase_with_real_nickname_is_not_flagged(self) -> None:
        summarizer = MemorySummarizer()
        rows = [
            {
                "id": "tl_1",
                "event_type": "user_message",
                "scope": "group",
                "subject_id": "u_alice",
                "content": "今天刚才又交了21个PR，中午要辗转百来公里，晚上还有个饭局。",
                "metadata": {"sender_name": "小思"},
                "occurred_at": "2026-11-22T10:53:36+08:00",
            }
        ]
        normalized = summarizer._normalize_payload(
            {
                "outcome": "memory",
                "summary": "观察到群成员的日常交流：小思今天交了21个PR，中午需要辗转百来公里，晚上还有一场饭局。",
                "canonical_summary": "小思提交了21个PR，中午要跑百来公里，晚上有饭局。",
                "summary_refs": ["tl_1"],
                "key_facts": [
                    {
                        "fact": "小思今天中午需要辗转百来公里，晚上有饭局",
                        "refs": ["tl_1"],
                        "evidence": [{"ref": "tl_1", "quote": "中午要辗转百来公里，晚上还有个饭局"}],
                    }
                ],
            },
            rows,
        )
        self.assertEqual([], normalized["_validation_errors"])
        self.assertEqual([], normalized["_quality_warnings"])
        self.assertEqual([], normalized["_style_warnings"])
        self.assertEqual("normal", summarizer.summary_quality(normalized))

    def test_quoted_generic_word_from_user_transcript_is_not_flagged(self) -> None:
        summarizer = MemorySummarizer()
        rows = [
            {
                "id": "tl_q1",
                "event_type": "user_message",
                "scope": "group",
                "subject_id": "u_alice",
                "content": "今天晚上有人约我去吃面皮。",
                "metadata": {"sender_name": "小思"},
                "occurred_at": "2026-11-22T11:00:00+08:00",
            }
        ]
        normalized = summarizer._normalize_payload(
            {
                "outcome": "memory",
                "summary": "小思提到今天晚上有人约他去吃面皮。",
                "summary_refs": ["tl_q1"],
                "key_facts": [],
            },
            rows,
        )
        self.assertEqual([], normalized["_style_warnings"])
        self.assertEqual("normal", summarizer.summary_quality(normalized))

    async def test_style_warning_triggers_single_repair_and_never_hides_in_pending(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g_main",
            scope="group",
            platform="onebot_qq",
            user_id="u_alice",
            user_name="小思",
            group_id="g_main",
            group_name="测试交流群",
            bot_id="b_main",
            persona_id="persona-main",
        )
        ev_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id=ctx.session_id,
            scope="group",
            subject_id=ctx.user_id,
            object_id=ctx.group_id,
            content="中午要辗转百来公里，晚上还有个饭局",
            metadata=self._meta(bot_id=ctx.bot_id, user_id=ctx.user_id, sender_name="小思"),
            occurred_at="2026-11-22T10:53:36+08:00",
        )
        provider = _QueuedProvider(
            [
                {
                    "outcome": "memory",
                    "summary": "某人说中午要辗转百来公里，晚上还有个饭局。",
                    "summary_refs": [ev_id],
                    "key_facts": [],
                },
                {
                    "outcome": "memory",
                    "summary": "小思说中午要辗转百来公里，晚上还有个饭局。",
                    "summary_refs": [ev_id],
                    "key_facts": [],
                },
            ]
        )

        async def attempts(_ctx):
            return [{"provider": provider, "provider_id": "test", "source": "primary"}]

        service._summary_provider_attempts = attempts
        memory_id = await service.maybe_summarize_session(ctx)
        self.assertTrue(memory_id)
        self.assertEqual(2, len(provider.calls))
        record = await service.store.get_memory(memory_id)
        self.assertIsNotNone(record)
        self.assertEqual("auto", record.review_status)
        self.assertEqual("stable_memory", record.lifecycle)
        self.assertIn("小思", record.content)

    async def test_unrepaired_style_warning_still_lands_as_auto_not_pending(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g_style",
            scope="group",
            platform="onebot_qq",
            user_id="u_alice",
            user_name="小思",
            group_id="g_style",
            bot_id="b_main",
            persona_id="persona-main",
        )
        ev_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id=ctx.session_id,
            scope="group",
            subject_id=ctx.user_id,
            object_id=ctx.group_id,
            content="中午要辗转百来公里，晚上还有个饭局",
            metadata=self._meta(bot_id="b_main", user_id="u_alice", sender_name="小思"),
            occurred_at="2026-11-22T10:53:36+08:00",
        )
        provider = _QueuedProvider(
            [
                {
                    "outcome": "memory",
                    "summary": "某人说中午要辗转百来公里，晚上还有个饭局。",
                    "summary_refs": [ev_id],
                    "key_facts": [],
                },
                {
                    "outcome": "memory",
                    "summary": "群成员说中午要辗转百来公里，晚上还有个饭局。",
                    "summary_refs": [ev_id],
                    "key_facts": [],
                },
            ]
        )

        async def attempts(_ctx):
            return [{"provider": provider, "provider_id": "test", "source": "primary"}]

        service._summary_provider_attempts = attempts
        memory_id = await service.maybe_summarize_session(ctx)
        self.assertTrue(memory_id)
        self.assertEqual(2, len(provider.calls))
        record = await service.store.get_memory(memory_id)
        self.assertIsNotNone(record)
        self.assertEqual("auto", record.review_status)
        self.assertEqual("stable_memory", record.lifecycle)
        self.assertTrue(record.metadata.get("style_warnings"))

    async def test_situational_schedule_assertion_is_auto_with_short_ttl_and_safe_guards(self) -> None:
        schedule_claim = normalize_assertion(
            {
                "subject": "u_alice",
                "predicate": "schedule",
                "value": "2026-11-22 中午需要辗转百来公里",
                "polarity": "positive",
                "durability": "situational",
                "refs": ["e1"],
            }
        )
        self.assertFalse(assertion_is_promotable(schedule_claim, ["中午要辗转百来公里，晚上还有个饭局"]))
        self.assertTrue(assertion_is_short_term_visible(schedule_claim, ["中午要辗转百来公里，晚上还有个饭局"]))

        plan_schedule = normalize_assertion(
            {
                "subject": "u_alice",
                "predicate": "schedule",
                "value": "2026-11-22 晚上计划去参加饭局",
                "polarity": "positive",
                "durability": "situational",
                "refs": ["e1"],
            }
        )
        self.assertTrue(assertion_is_short_term_visible(plan_schedule, ["晚上计划去参加饭局"]))

        # Single-value profile slots, role-play, and reported speech must stay pending.
        residence = normalize_assertion(
            {"subject": "u_alice", "predicate": "residence", "value": "住在北京", "durability": "situational", "refs": ["e1"]}
        )
        roleplay = normalize_assertion(
            {"subject": "u_alice", "predicate": "schedule", "value": "代号十七今晚行动", "durability": "situational", "refs": ["e1"]}
        )
        reported = normalize_assertion(
            {"subject": "u_alice", "predicate": "schedule", "value": "今天晚上有饭局", "durability": "situational", "refs": ["e1"]}
        )
        self.assertFalse(assertion_is_short_term_visible(residence, ["我打算住在北京"]))
        self.assertFalse(assertion_is_short_term_visible(roleplay, ["（角色扮演）我是刺客代号十七 今晚行动"]))
        self.assertFalse(assertion_is_short_term_visible(reported, ["他说他今天晚上有饭局"]))

        service = self.make_service({"visibility": {"hide_pending_review": True}})
        ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g_main",
            scope="group",
            platform="onebot_qq",
            user_id="u_alice",
            user_name="小思",
            group_id="g_main",
            bot_id="b_main",
            persona_id="persona-main",
        )
        rows = [
            {
                "id": "e1",
                "event_type": "user_message",
                "subject_id": "u_alice",
                "subject_name": "小思",
                "content": "中午要辗转百来公里，晚上还有个饭局",
                "occurred_at": "2026-11-22T10:53:36+08:00",
            }
        ]
        ids = await service._persist_assertions(
            ctx,
            {
                "assertions": [
                    {
                        "subject": "u_alice",
                        "predicate": "schedule",
                        "value": "2026-11-22 中午需要辗转百来公里",
                        "polarity": "positive",
                        "durability": "situational",
                        "refs": ["e1"],
                    },
                    {
                        "subject": "u_alice",
                        "predicate": "schedule",
                        "value": "2026-11-22 晚上有一个饭局",
                        "polarity": "positive",
                        "durability": "situational",
                        "refs": ["e1"],
                    },
                ]
            },
            "sum_1",
            rows,
        )
        self.assertEqual(2, len(ids))
        for mem_id in ids:
            rec = await service.store.get_memory(mem_id)
            self.assertIsNotNone(rec)
            self.assertEqual("auto", rec.review_status)
            self.assertEqual("short_term_candidate", rec.lifecycle)
            self.assertEqual("short", rec.durability)
            self.assertEqual(SITUATIONAL_ASSERTION_TTL_DAYS, rec.metadata.get("situational_ttl_days"))
            self.assertTrue(rec.valid_to)
            expires = datetime.fromisoformat(rec.valid_to.replace("Z", "+00:00"))
            delta_days = (expires - datetime.now(timezone.utc)).total_seconds() / 86400.0
            self.assertGreaterEqual(delta_days, 3.0)
            self.assertLessEqual(delta_days, 7.1)

    # ------------------------------------------------------------------
    # Time window retrieval excludes background maintenance updated_at
    # ------------------------------------------------------------------

    async def test_time_window_never_matches_updated_at_from_background_decay(self) -> None:
        service = self.make_service({"visibility": {"allow_group_public_in_private": True}})
        for idx in range(12):
            await service.store.insert_memory(
                MemoryRecord(
                    id=f"mem_old_{idx}",
                    memory_type="conversation_summary",
                    subject=EntityRef(kind="user", id="u_alice", name="小思"),
                    object=EntityRef.bot_self("b_main"),
                    scope="private",
                    session_id="onebot_qq:FriendMessage:u_alice",
                    platform="onebot_qq",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    review_status="auto",
                    content=f"上个月旧安排记录 {idx}：十月份的会议和聚餐",
                    confidence=0.9,
                    importance=0.95,
                    owner_bot_id="b_main",
                    occurred_at=f"2026-10-22T10:{idx:02d}:00+08:00",
                    created_at=f"2026-10-22T10:{idx:02d}:00+08:00",
                    updated_at="2026-11-22T08:32:21+08:00",
                )
            )
        today_rec = MemoryRecord(
            id="mem_today_real",
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u_alice", name="小思"),
            object=EntityRef(kind="group", id="g_main", name="测试交流群"),
            scope="group",
            session_id="onebot_qq:GroupMessage:g_main",
            platform="onebot_qq",
            group_id="g_main",
            visibility="group_public",
            lifecycle="stable_memory",
            review_status="auto",
            content="小思今天中午需要辗转百来公里，晚上还有一场饭局。",
            confidence=0.8,
            importance=0.7,
            owner_bot_id="b_main",
            occurred_at="2026-11-22T10:55:40+08:00",
            created_at="2026-11-22T10:55:40+08:00",
            updated_at="2026-11-22T10:55:40+08:00",
        )
        await service.store.insert_memory(today_rec)
        with service.store._lock, service.store._transaction_sync():
            service.store._conn.execute(
                "UPDATE memories SET updated_at=? WHERE id LIKE 'mem_old_%'",
                ("2026-11-22T08:32:21+08:00",),
            )

        time_intent = TimeIntent(
            active=True,
            label="今天",
            source="test",
            start_at="2026-11-22T00:00:00+08:00",
            end_at="2026-11-23T00:00:00+08:00",
            display_start="2026-11-22",
            display_end="2026-11-22",
        )
        old_loaded = await service.store.get_memory("mem_old_0")
        self.assertIsNotNone(old_loaded)

        engine = RetrievalEngine(service.store, None)
        self.assertFalse(engine._memory_overlaps_time_window(old_loaded, time_intent))
        self.assertTrue(engine._memory_overlaps_time_window(today_rec, time_intent))

        span_rec = MemoryRecord(
            id="mem_span",
            memory_type="conversation_summary",
            occurred_at="2026-11-21T23:00:00+08:00",
            created_at="2026-11-21T23:00:00+08:00",
            updated_at="2026-12-01T00:00:00+08:00",
            metadata={
                "source_start_at": "2026-11-21T23:00:00+08:00",
                "source_end_at": "2026-11-22T01:00:00+08:00",
            },
        )
        self.assertTrue(engine._memory_overlaps_time_window(span_rec, time_intent))

        old_ranges = memory_time_ranges(old_loaded)
        self.assertTrue(
            all(start < datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp() for start, _ in old_ranges)
        )

        rows = service.store._time_window_candidate_rows(
            service.store._conn, time_intent.start_at, time_intent.end_at, 20, False
        )
        self.assertEqual(["mem_today_real"], [row["id"] for row in rows])

    # ------------------------------------------------------------------
    # Cross-window group-to-group switch & per-group exclusion blacklist
    # ------------------------------------------------------------------

    async def test_cross_window_group_to_group_switch_really_disables_when_false(self) -> None:
        cfg = {
            "conversation_memory_advanced": {
                "cross_window_group_to_group_enabled": False,
            }
        }
        view = ConfigView(cfg)
        self.assertFalse(view.bool("conversation_memory.cross_window_group_to_group_enabled", True))

        service = self.make_service(cfg)
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="onebot_qq:GroupMessage:g1",
            scope="group",
            subject_id="u1",
            object_id="g1",
            content="我在群1说了一段话。",
            metadata=self._meta(bot_id="b1", user_id="u1"),
        )
        ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g2",
            scope="group",
            platform="onebot_qq",
            user_id="u1",
            group_id="g2",
            bot_id="b1",
            message_text="我来了",
        )
        self.assertEqual("", await service._recent_cross_window_context(ctx))

    async def test_cross_window_excluded_groups_blocks_outbound_and_inbound(self) -> None:
        service = self.make_service(
            {
                "conversation_memory_advanced": {
                    "cross_window_group_to_group_enabled": True,
                    "cross_window_group_to_private_enabled": True,
                    "cross_window_excluded_groups": "g_secret, g_work",
                }
            }
        )
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="onebot_qq:GroupMessage:g_secret",
            scope="group",
            subject_id="u1",
            object_id="g_secret",
            content="保密群里的内部机密讨论。",
            metadata=self._meta(bot_id="b1", user_id="u1"),
        )
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="onebot_qq:GroupMessage:g_public",
            scope="group",
            subject_id="u1",
            object_id="g_public",
            content="普通群里聊的周末聚餐。",
            metadata=self._meta(bot_id="b1", user_id="u1"),
        )

        other_group_ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g_other",
            scope="group",
            platform="onebot_qq",
            user_id="u1",
            group_id="g_other",
            bot_id="b1",
            message_text="继续聊",
        )
        ctx_text = await service._recent_cross_window_context(other_group_ctx)
        self.assertIn("周末聚餐", ctx_text)
        self.assertNotIn("内部机密", ctx_text)

        private_ctx = SessionContext(
            session_id="onebot_qq:FriendMessage:u1",
            scope="private",
            platform="onebot_qq",
            user_id="u1",
            bot_id="b1",
            message_text="继续聊",
        )
        priv_text = await service._recent_cross_window_context(private_ctx)
        self.assertIn("周末聚餐", priv_text)
        self.assertNotIn("内部机密", priv_text)

        work_group_ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g_work",
            scope="group",
            platform="onebot_qq",
            user_id="u1",
            group_id="g_work",
            bot_id="b1",
            message_text="继续聊",
        )
        self.assertEqual("", await service._recent_cross_window_context(work_group_ctx))

    # ------------------------------------------------------------------
    # Active group SQL pushdown, private->group fallback, and header text
    # ------------------------------------------------------------------

    async def test_active_group_sql_pushdown_prevents_limit_48_starvation(self) -> None:
        service = self.make_service()
        now = datetime.now(timezone.utc)
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="onebot_qq:GroupMessage:g1",
            scope="group",
            subject_id="u_target",
            object_id="g1",
            content="目标用户跨群发言：蓝绿发布方案已确认。",
            metadata=self._meta(bot_id="b1", user_id="u_target"),
            occurred_at=(now - timedelta(minutes=12)).isoformat(timespec="seconds"),
        )
        await service.store.add_timeline_event(
            event_type="bot_response",
            session_id="onebot_qq:GroupMessage:g1",
            scope="group",
            subject_id="b1",
            object_id="g1",
            content="好的，记录下蓝绿发布方案。",
            metadata=self._meta(bot_id="b1", user_id="u_target"),
            occurred_at=(now - timedelta(minutes=11)).isoformat(timespec="seconds"),
        )
        for i in range(60):
            await service.store.add_timeline_event(
                event_type="user_message",
                session_id="onebot_qq:GroupMessage:g1",
                scope="group",
                subject_id=f"u_noise_{i}",
                object_id="g1",
                content=f"活跃群闲聊噪音 {i}",
                metadata=self._meta(bot_id="b1", user_id=f"u_noise_{i}"),
                occurred_at=(now - timedelta(seconds=300 - i)).isoformat(timespec="seconds"),
            )
            if i < 20:
                await service.store.add_timeline_event(
                    event_type="bot_response",
                    session_id="onebot_qq:GroupMessage:g1",
                    scope="group",
                    subject_id="b1",
                    object_id="g1",
                    content=f"Bot 回复噪音 {i}",
                    metadata=self._meta(bot_id="b1", user_id=f"u_noise_{i}"),
                    occurred_at=(now - timedelta(seconds=200 - i)).isoformat(timespec="seconds"),
                )

        g2_ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g2",
            scope="group",
            platform="onebot_qq",
            user_id="u_target",
            group_id="g2",
            bot_id="b1",
            message_text="继续说",
        )
        g2_text = await service._recent_cross_window_context(g2_ctx)
        self.assertIn("蓝绿发布方案已确认", g2_text)
        self.assertNotIn("记录下蓝绿发布方案", g2_text)
        self.assertNotIn("活跃群闲聊噪音", g2_text)
        self.assertIn("不含 Bot 回复", g2_text)
        self.assertNotIn("仅含当前用户与同一 Bot 的片段", g2_text)

        priv_ctx = SessionContext(
            session_id="onebot_qq:FriendMessage:u_target",
            scope="private",
            platform="onebot_qq",
            user_id="u_target",
            bot_id="b1",
            message_text="刚才群里那个方案",
        )
        priv_text = await service._recent_cross_window_context(priv_ctx)
        self.assertIn("蓝绿发布方案已确认", priv_text)
        self.assertIn("记录下蓝绿发布方案", priv_text)
        self.assertNotIn("活跃群闲聊噪音", priv_text)
        self.assertNotIn("Bot 回复噪音", priv_text)

    async def test_private_authorization_with_empty_private_falls_back_to_group_to_group(self) -> None:
        service = self.make_service()
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="onebot_qq:GroupMessage:g1",
            scope="group",
            subject_id="u1",
            object_id="g1",
            content="刚才在另一个群里提到的咖啡店地址。",
            metadata=self._meta(bot_id="b1", user_id="u1"),
        )
        ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g2",
            scope="group",
            platform="onebot_qq",
            user_id="u1",
            group_id="g2",
            bot_id="b1",
            message_text="把刚才私聊的内容带到群里继续说吧。",
        )
        self.assertTrue(service._message_explicitly_shares_private_context(ctx.message_text))
        result = await service._recent_cross_window_context(ctx)
        self.assertIn("咖啡店地址", result)
        self.assertIn("其他群", result)

    # ------------------------------------------------------------------
    # Deduplication between group_conversation_observer and source-capture
    # ------------------------------------------------------------------

    async def test_observer_and_source_capture_deduplicate_both_orders(self) -> None:
        service = self.make_service()
        ctx1 = SessionContext(
            session_id="onebot_qq:GroupMessage:g_main",
            scope="group",
            platform="onebot_qq",
            user_id="u_alice",
            user_name="小思",
            group_id="g_main",
            group_name="测试交流群",
            bot_id="b_main",
            persona_id="persona-main",
            message_id="msg_dedupe_1",
            message_text="中午要辗转百来公里，晚上还有个饭局",
        )
        event1 = SimpleNamespace(
            get_self_id=lambda: "b_main",
            get_messages=lambda: [Plain(ctx1.message_text)],
            message_obj=SimpleNamespace(
                message_id="msg_dedupe_1",
                message=[Plain(ctx1.message_text)],
                timestamp=1795316016,
            ),
            message_str=ctx1.message_text,
        )
        service.identity.resolve_event_context = AsyncMock(return_value=ctx1)
        service.identity.resolve_persona_id = AsyncMock(return_value="persona-main")
        service._schedule_session_summary = lambda *args, **kwargs: None

        await service.handle_group_message(event1)
        receipt1 = await service.capture.incoming(event1, ctx1)
        self.assertEqual("committed", receipt1["status"])
        count1 = service.store._conn.execute(
            "SELECT COUNT(*) FROM timeline WHERE session_id=? AND message_id=?",
            (ctx1.session_id, "msg_dedupe_1"),
        ).fetchone()[0]
        self.assertEqual(1, count1)
        row1 = service.store._conn.execute(
            "SELECT id, bot_id, metadata FROM timeline WHERE session_id=? AND message_id=?",
            (ctx1.session_id, "msg_dedupe_1"),
        ).fetchone()
        self.assertEqual(f"timeline:{row1['id']}", receipt1["source_ref"])
        self.assertEqual("b_main", row1["bot_id"])
        meta1 = json.loads(row1["metadata"])
        self.assertEqual("memory.source-capture.v1", meta1["capture_profile"])
        self.assertEqual("小思", meta1["sender_name"])
        self.assertEqual("u_alice", meta1["participant_user_id"])

        ctx2 = SessionContext(
            session_id="onebot_qq:GroupMessage:g_main",
            scope="group",
            platform="onebot_qq",
            user_id="u_alice",
            user_name="小思",
            group_id="g_main",
            group_name="测试交流群",
            bot_id="b_main",
            persona_id="persona-main",
            message_id="msg_dedupe_2",
            message_text="今天又交了21个PR",
        )
        event2 = SimpleNamespace(
            get_self_id=lambda: "b_main",
            get_messages=lambda: [Plain(ctx2.message_text)],
            message_obj=SimpleNamespace(
                message_id="msg_dedupe_2",
                message=[Plain(ctx2.message_text)],
                timestamp=1795315866,
            ),
            message_str=ctx2.message_text,
        )
        service.identity.resolve_event_context = AsyncMock(return_value=ctx2)
        receipt2 = await service.capture.incoming(event2, ctx2)
        self.assertEqual("committed", receipt2["status"])
        await service.handle_group_message(event2)
        count2 = service.store._conn.execute(
            "SELECT COUNT(*) FROM timeline WHERE session_id=? AND message_id=?",
            (ctx2.session_id, "msg_dedupe_2"),
        ).fetchone()[0]
        self.assertEqual(1, count2)

    # ------------------------------------------------------------------
    # Cross-window time_window_timeline & memory_companion_sources
    # with strict sender-only privacy isolation
    # ------------------------------------------------------------------

    async def test_private_timeline_and_sources_strictly_filter_to_self_in_authorized_groups(self) -> None:
        service = self.make_service(
            {
                "visibility": {
                    "allow_group_public_in_private": False,
                    "enable_acl_rules": True,
                }
            }
        )
        private_ctx = SessionContext(
            session_id="onebot_qq:FriendMessage:u_alice",
            scope="private",
            platform="onebot_qq",
            user_id="u_alice",
            user_name="小思",
            bot_id="b_main",
            persona_id="persona-main",
            message_id="priv-turn-1",
            message_text="我今天中午有什么安排？",
        )
        service.identity.resolve_event_context = AsyncMock(return_value=private_ctx)

        self_msg_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id="onebot_qq:GroupMessage:g_allow",
            scope="group",
            subject_id="u_alice",
            object_id="g_allow",
            content="中午要辗转百来公里，晚上还有个饭局",
            metadata=self._meta(bot_id="b_main", user_id="u_alice", sender_name="小思"),
            occurred_at="2026-11-22T10:53:36+08:00",
        )
        other_msg_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id="onebot_qq:GroupMessage:g_allow",
            scope="group",
            subject_id="u_other",
            object_id="g_allow",
            content="别人中午要辗转百来公里去秘密地点",
            metadata=self._meta(bot_id="b_main", user_id="u_other", sender_name="路人甲"),
            occurred_at="2026-11-22T10:54:00+08:00",
        )
        await service.store.add_timeline_event(
            event_type="bot_response",
            session_id="onebot_qq:GroupMessage:g_allow",
            scope="group",
            subject_id="b_main",
            object_id="g_allow",
            content="Bot 在群里回复了关于百来公里的内容",
            metadata=self._meta(bot_id="b_main", user_id="u_other"),
            occurred_at="2026-11-22T10:54:10+08:00",
        )
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="onebot_qq:GroupMessage:g_other",
            scope="group",
            subject_id="u_alice",
            object_id="g_other",
            content="未授权群里提到的百来公里备忘",
            metadata=self._meta(bot_id="b_main", user_id="u_alice", sender_name="小思"),
            occurred_at="2026-11-22T10:55:00+08:00",
        )

        day_intent = TimeIntent(
            active=True,
            label="今天",
            source="test",
            start_at="2026-11-22T00:00:00+08:00",
            end_at="2026-11-23T00:00:00+08:00",
            display_start="2026-11-22",
            display_end="2026-11-22",
        )

        # Without allow_group_public_in_private or ACL: zero group rows visible.
        slots_before: dict = {}
        await service._add_time_window_timeline_slot(private_ctx, slots_before, day_intent)
        self.assertEqual([], slots_before.get("time_window_timeline", []))
        res_before = await service.tool_sources(SimpleNamespace(), terms=["百来公里"])
        SOURCE_RESULT_VALIDATOR.validate(res_before)
        self.assertEqual([], res_before["sources"])

        # Explicit ACL allow group:g_allow -> private:u_alice.
        await service.store.upsert_acl_rule(
            owner_scope="group",
            owner_id="g_allow",
            reader_scope="private",
            reader_id="u_alice",
            effect="allow",
        )
        slots_acl: dict = {}
        await service._add_time_window_timeline_slot(private_ctx, slots_acl, day_intent)
        timeline_contents = [item.memory.content for item in slots_acl.get("time_window_timeline", [])]
        self.assertEqual(1, len(timeline_contents))
        self.assertIn("中午要辗转百来公里", timeline_contents[0])
        self.assertNotIn("秘密地点", "\n".join(timeline_contents))
        self.assertNotIn("未授权群", "\n".join(timeline_contents))

        private_ctx_acl = replace(private_ctx, message_id="priv-turn-2")
        service.identity.resolve_event_context = AsyncMock(return_value=private_ctx_acl)
        res_search = await service.tool_sources(SimpleNamespace(), terms=["百来公里"])
        SOURCE_RESULT_VALIDATOR.validate(res_search)
        self.assertTrue(res_search["ok"])
        self.assertEqual([f"timeline:{self_msg_id}"], [item["source_ref"] for item in res_search["sources"]])
        self.assertNotIn("秘密地点", json.dumps(res_search, ensure_ascii=False))
        self.assertNotIn("未授权群", json.dumps(res_search, ensure_ascii=False))

        # Context query anchored on self's group message must never leak another member's message.
        res_ctx = await service.tool_sources(
            SimpleNamespace(), action="context", source_ref=f"timeline:{self_msg_id}", limit=6,
        )
        SOURCE_RESULT_VALIDATOR.validate(res_ctx)
        self.assertEqual([f"timeline:{self_msg_id}"], [item["source_ref"] for item in res_ctx["sources"]])
        self.assertNotIn(other_msg_id, json.dumps(res_ctx, ensure_ascii=False))

        # Global allow_group_public_in_private=True still respects cross_window_excluded_groups.
        service.config.raw["visibility"]["allow_group_public_in_private"] = True
        service.config.raw["conversation_memory_advanced"]["cross_window_excluded_groups"] = "g_other"
        private_ctx_global = replace(private_ctx, message_id="priv-turn-3")
        service.identity.resolve_event_context = AsyncMock(return_value=private_ctx_global)
        res_global = await service.tool_sources(SimpleNamespace(), terms=["百来公里"])
        SOURCE_RESULT_VALIDATOR.validate(res_global)
        self.assertEqual([f"timeline:{self_msg_id}"], [item["source_ref"] for item in res_global["sources"]])
        self.assertNotIn("未授权群", json.dumps(res_global, ensure_ascii=False))
        self.assertNotIn("秘密地点", json.dumps(res_global, ensure_ascii=False))

        # strict_session_only=True blocks all cross-window group reads.
        strict_ctx = SessionContext(
            session_id=private_ctx.session_id,
            scope="private",
            platform="onebot_qq",
            user_id="u_alice",
            bot_id="b_main",
            persona_id="persona-main",
            message_id="priv-turn-strict",
            strict_session_only=True,
        )
        service.identity.resolve_event_context = AsyncMock(return_value=strict_ctx)
        res_strict = await service.tool_sources(SimpleNamespace(), terms=["百来公里"])
        SOURCE_RESULT_VALIDATOR.validate(res_strict)
        self.assertEqual([], res_strict["sources"])

    # ------------------------------------------------------------------
    # Tool availability and dedicated source fallback step budget
    # ------------------------------------------------------------------

    def test_discover_sources_removed_from_tool_list_when_source_semantic_disabled(self) -> None:
        service = self.make_service({"source_semantic": {"enabled": False}})
        ctx = SessionContext(
            session_id="onebot_qq:FriendMessage:u_alice",
            scope="private",
            platform="onebot_qq",
            user_id="u_alice",
            bot_id="b_main",
            persona_id="persona-main",
            message_id="turn-1",
        )
        tools, _manager = _make_v3_toolset()
        original_names = list(tools.names())
        self.assertIn("memory_companion_discover_sources", original_names)
        req = SimpleNamespace(func_tool=tools, system_prompt="")
        offer_query_tool(service, req, ctx, SimpleNamespace())

        self.assertNotIn("memory_companion_discover_sources", req.func_tool.names())
        self.assertIn("memory_companion_sources", req.func_tool.names())
        self.assertEqual(original_names, tools.names())

        service.config.raw.setdefault("memory_tools", {})["enable_query_progress"] = False
        req2 = SimpleNamespace(func_tool=tools, system_prompt="")
        offer_query_tool(service, req2, ctx, SimpleNamespace())
        self.assertNotIn("memory_companion_discover_sources", req2.func_tool.names())
        self.assertNotIn("memory_companion_query", req2.func_tool.names())

        service.config.raw["memory_tools"]["enable_query_progress"] = True
        service.config.raw["source_semantic"] = {
            "enabled": True,
            "provider_id": "test-provider",
            "model_revision": "test-model",
            "dimensions": 3,
            "processing_version": "test-processing",
        }
        req3 = SimpleNamespace(func_tool=tools, system_prompt="")
        offer_query_tool(service, req3, ctx, SimpleNamespace())
        self.assertIn("memory_companion_discover_sources", req3.func_tool.names())

    async def test_sources_has_dedicated_fallback_budget_after_navigate_exhaustion(self) -> None:
        service = self.make_service({"memory_reconstruction": {"max_steps": 3}})
        ctx = SessionContext(
            session_id="onebot_qq:FriendMessage:u_alice",
            scope="private",
            platform="onebot_qq",
            user_id="u_alice",
            bot_id="b_main",
            persona_id="persona-main",
            message_id="budget-turn-1",
        )
        service.identity.resolve_event_context = AsyncMock(return_value=ctx)
        row_a = await service.store.add_timeline_event(
            event_type="user_message",
            session_id=ctx.session_id,
            scope="private",
            subject_id=ctx.user_id,
            object_id=ctx.user_id,
            content="中午要辗转百来公里",
            metadata=self._meta(bot_id=ctx.bot_id, user_id=ctx.user_id),
            occurred_at="2026-11-22T10:53:36+08:00",
        )
        row_b = await service.store.add_timeline_event(
            event_type="user_message",
            session_id=ctx.session_id,
            scope="private",
            subject_id=ctx.user_id,
            object_id=ctx.user_id,
            content="晚上还有个饭局",
            metadata=self._meta(bot_id=ctx.bot_id, user_id=ctx.user_id),
            occurred_at="2026-11-22T10:54:00+08:00",
        )
        event = SimpleNamespace()

        for i in range(3):
            nav = await service.tool_navigate(event, "search", query=f"线索 {i}")
            self.assertTrue(nav["ok"])
        nav_blocked = await service.tool_navigate(event, "search", query="第四次导航")
        self.assertFalse(nav_blocked["ok"])
        self.assertEqual("navigation step budget exhausted", nav_blocked["error"])

        src1 = await service.tool_sources(event, terms=["百来公里"])
        SOURCE_RESULT_VALIDATOR.validate(src1)
        self.assertTrue(src1["ok"])
        self.assertEqual([f"timeline:{row_a}"], [item["source_ref"] for item in src1["sources"]])
        self.assertEqual(4, src1["usage"]["step"])
        self.assertEqual(1, src1["usage"]["remaining_steps"])

        src2 = await service.tool_sources(event, terms=["饭局"])
        SOURCE_RESULT_VALIDATOR.validate(src2)
        self.assertTrue(src2["ok"])
        self.assertEqual([f"timeline:{row_b}"], [item["source_ref"] for item in src2["sources"]])
        self.assertEqual(5, src2["usage"]["step"])
        self.assertEqual(0, src2["usage"]["remaining_steps"])

        src3 = await service.tool_sources(event, terms=["不存在"])
        SOURCE_RESULT_VALIDATOR.validate(src3)
        self.assertFalse(src3["ok"])
        self.assertEqual("navigation step budget exhausted", src3["error"])

    # ------------------------------------------------------------------
    # End-to-end cross-session group -> private recall regression
    # ------------------------------------------------------------------

    async def test_e2e_group_to_private_full_recall_beyond_short_window(self) -> None:
        service = self.make_service(
            {
                "visibility": {
                    "allow_group_public_in_private": True,
                    "hide_pending_review": True,
                    "enable_acl_rules": True,
                },
                "source_semantic": {"enabled": False},
                "memory_reconstruction": {"enabled": True, "max_steps": 3},
                "conversation_memory_advanced": {
                    "cross_window_recent_minutes": 30,
                    "time_window_timeline_limit": 12,
                },
            }
        )
        await service.store.upsert_acl_rule(
            owner_scope="group",
            owner_id="g_main",
            reader_scope="private",
            reader_id="u_alice",
            effect="allow",
        )

        # Morning decay touched 12 older memories from the previous month.
        for idx in range(12):
            await service.store.insert_memory(
                MemoryRecord(
                    id=f"mem_oct_{idx}",
                    memory_type="conversation_summary",
                    subject=EntityRef(kind="user", id="u_alice", name="小思"),
                    object=EntityRef.bot_self("b_main"),
                    scope="private",
                    session_id="onebot_qq:FriendMessage:u_alice",
                    platform="onebot_qq",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    review_status="auto",
                    content=f"十月旧记忆 {idx}：2026-10-22 讨论过旧版本计划。",
                    confidence=0.9,
                    importance=0.95,
                    owner_bot_id="b_main",
                    occurred_at=f"2026-10-22T09:{idx:02d}:00+08:00",
                    created_at=f"2026-10-22T09:{idx:02d}:00+08:00",
                    updated_at="2026-11-22T08:32:21+08:00",
                )
            )
        with service.store._lock, service.store._transaction_sync():
            service.store._conn.execute(
                "UPDATE memories SET updated_at=? WHERE id LIKE 'mem_oct_%'",
                ("2026-11-22T08:32:21+08:00",),
            )

        group_ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g_main",
            scope="group",
            platform="onebot_qq",
            user_id="u_alice",
            user_name="小思",
            group_id="g_main",
            group_name="测试交流群",
            bot_id="b_main",
            persona_id="persona-main",
        )
        service._schedule_session_summary = lambda *args, **kwargs: None

        msg_specs = [
            ("msg_1051", "今天，在刚才，又交了21个pr）", 1795315866),
            ("msg_1053", "中午要辗转百来公里，晚上还有个饭局.....", 1795316016),
        ]
        ev_ids: list[str] = []
        for msg_id, text, unix_ts in msg_specs:
            turn_ctx = replace(group_ctx, message_id=msg_id, message_text=text)
            ev = SimpleNamespace(
                get_self_id=lambda: "b_main",
                get_messages=lambda t=text: [At("b_main"), Plain(t)],
                message_obj=SimpleNamespace(message_id=msg_id, message=[Plain(text)], timestamp=unix_ts),
                message_str=text,
            )
            service.identity.resolve_event_context = AsyncMock(return_value=turn_ctx)
            service.identity.resolve_persona_id = AsyncMock(return_value="persona-main")
            await service.handle_group_message(ev)
            receipt = await service.capture.incoming(ev, turn_ctx)
            self.assertEqual("committed", receipt["status"])
            ev_ids.append(receipt["source_ref"].removeprefix("timeline:"))

        # Another group member's message in the same group must never leak into private recall.
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id=group_ctx.session_id,
            scope="group",
            subject_id="u_bob",
            object_id="g_main",
            content="群友乙中午去秘密爬山",
            metadata=self._meta(bot_id="b_main", user_id="u_bob", sender_name="群友乙"),
            occurred_at="2026-11-22T10:54:00+08:00",
        )

        # Deduplication: only 2 rows for u_alice instead of 4.
        self_count = service.store._conn.execute(
            "SELECT COUNT(*) FROM timeline WHERE session_id=? AND subject_id=?",
            (group_ctx.session_id, "u_alice"),
        ).fetchone()[0]
        self.assertEqual(2, self_count)

        provider = _QueuedProvider(
            [
                {
                    "outcome": "memory",
                    "summary": "观察到群成员的日常交流：小思今天交了21个PR，中午需要辗转百来公里，晚上还有一场饭局。",
                    "canonical_summary": "小思今天交了21个PR，中午需要辗转百来公里，晚上有饭局。",
                    "summary_refs": ev_ids,
                    "topics": ["日程", "开发"],
                    "key_facts": [
                        {
                            "fact": "小思中午需要辗转百来公里，晚上还有个饭局",
                            "refs": [ev_ids[1]],
                            "evidence": [{"ref": ev_ids[1], "quote": "中午要辗转百来公里，晚上还有个饭局"}],
                        }
                    ],
                    "assertions": [
                        {
                            "subject": "u_alice",
                            "predicate": "schedule",
                            "value": "2026-11-22 中午需要辗转百来公里",
                            "polarity": "positive",
                            "durability": "situational",
                            "refs": [ev_ids[1]],
                        },
                        {
                            "subject": "u_alice",
                            "predicate": "schedule",
                            "value": "2026-11-22 晚上有一个饭局",
                            "polarity": "positive",
                            "durability": "situational",
                            "refs": [ev_ids[1]],
                        },
                    ],
                }
            ]
        )

        async def attempts(_ctx):
            return [{"provider": provider, "provider_id": "summary-llm", "source": "primary"}]

        service._summary_provider_attempts = attempts
        summary_id = await service.maybe_summarize_session(group_ctx)
        self.assertTrue(summary_id)
        summary_rec = await service.store.get_memory(summary_id)
        self.assertEqual("auto", summary_rec.review_status)
        self.assertEqual("stable_memory", summary_rec.lifecycle)

        private_ctx = SessionContext(
            session_id="onebot_qq:FriendMessage:u_alice",
            scope="private",
            platform="onebot_qq",
            user_id="u_alice",
            user_name="小思",
            bot_id="b_main",
            persona_id="persona-main",
            message_id="priv_1208",
            message_text="你还记得我今天中午和晚上有什么安排吗？",
        )
        service.identity.resolve_event_context = AsyncMock(return_value=private_ctx)

        day_intent = TimeIntent(
            active=True,
            label="今天",
            source="test",
            start_at="2026-11-22T00:00:00+08:00",
            end_at="2026-11-23T00:00:00+08:00",
            display_start="2026-11-22",
            display_end="2026-11-22",
        )
        _results, _blocked, slot_map = await service.search_context_slots(
            private_ctx.message_text,
            private_ctx,
            top_k=9,
            time_intent=day_intent,
        )
        await service._add_time_window_timeline_slot(private_ctx, slot_map, day_intent)

        all_text = "\n".join(
            item.memory.content
            for items in slot_map.values()
            for item in items
        )
        self.assertIn("百来公里", all_text)
        self.assertIn("饭局", all_text)
        self.assertNotIn("十月旧记忆", all_text)
        self.assertNotIn("秘密爬山", all_text)

        tools, _manager = _make_v3_toolset()
        req = SimpleNamespace(func_tool=tools, system_prompt="")
        turn_event = SimpleNamespace()
        service._apply_reconstruction_contract(req, private_ctx, event=turn_event)
        self.assertNotIn("memory_companion_discover_sources", req.func_tool.names())

        for i in range(3):
            await service.tool_navigate(turn_event, "search", query=f"今天安排 {i}")
        src = await service.tool_sources(turn_event, terms=["百来公里"])
        SOURCE_RESULT_VALIDATOR.validate(src)
        self.assertTrue(src["ok"])
        self.assertEqual(1, len(src["sources"]))
        self.assertIn("中午要辗转百来公里", src["sources"][0]["excerpt"])
        self.assertNotIn("秘密爬山", json.dumps(src, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
