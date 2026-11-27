"""Tests for summary transient fault resilience, global fallback inheritance,
historical transient-quarantine auto-recovery, and self-correcting source query errors.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jsonschema import Draft202012Validator

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.query_session import (
    CONTRACT_ROOT as QUERY_V1_ROOT,
    CONTRACT_ROOT_V3 as QUERY_V3_ROOT,
)
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.source_query import diagnose_source_query_parameters
from astrbot_plugin_memory_companion.core.source_query_v2 import CONTRACT_ROOT as SOURCE_V2_ROOT
from .test_summary_batch_recovery import Provider


SOURCE_V1_ROOT = ROOT / "docs/contracts/source-query/v1"
QUERY_V2_ROOT = ROOT / "docs/contracts/query-session/v2"

SOURCE_V1_RESULT_VALIDATOR = Draft202012Validator(
    json.loads((SOURCE_V1_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
)
SOURCE_V2_RESULT_VALIDATOR = Draft202012Validator(
    json.loads((SOURCE_V2_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
)
QUERY_V1_RESULT_VALIDATOR = Draft202012Validator(
    json.loads((QUERY_V1_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
)
QUERY_V2_RESULT_VALIDATOR = Draft202012Validator(
    json.loads((QUERY_V2_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
)
QUERY_V3_RESULT_VALIDATOR = Draft202012Validator(
    json.loads((QUERY_V3_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
)


class ServerError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class _NamedProvider(Provider):
    def __init__(self, provider_id: str, responses):
        super().__init__(responses)
        self.provider_config = {"id": provider_id}


class _FakeAstrBotContext:
    def __init__(self, *, providers: dict[str, Any], current_provider: Any, config: dict):
        self._providers = providers
        self._current = current_provider
        self._config = config

    def get_provider_by_id(self, provider_id: str):
        return self._providers.get(provider_id)

    def get_using_provider(self, umo: str = ""):
        return self._current

    def get_config(self, umo: str = ""):
        return self._config


class SummaryTransientResilienceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {
            "startup": {"background_grace_seconds": 60},
            "memory_summary": {
                "enabled": True,
                "min_events": 1,
                "trigger_event_count": 1,
                "max_events_per_summary": 8,
                "max_retries": 3,
                "retry_backoff_seconds": 60,
                "transient_retry_cooldown_minutes": 10,
                "max_calls_per_session_hour": 30,
                "request_max_retries": 1,
            },
        }
        self.service = MemoryCompanionService(
            context=None,
            config=self.config,
            plugin_root=ROOT,
            data_dir=Path(self.temp.name),
        )
        self.addCleanup(self.service.close)
        self.service._schedule_memory_embedding = lambda *args: None
        self.ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:100001",
            scope="group",
            platform="onebot_qq",
            group_id="100001",
            bot_id="bot-main",
            persona_id="default-persona",
        )

    async def seed_event(self, content: str = "今天群里聊了晚饭吃拉面。") -> str:
        return await self.service.store.add_timeline_event(
            event_type="user_message",
            session_id=self.ctx.session_id,
            scope=self.ctx.scope,
            subject_id="u100",
            object_id=self.ctx.group_id,
            content=content,
            metadata={
                "platform": self.ctx.platform,
                "owner_bot_id": self.ctx.bot_id,
                "persona_id": self.ctx.persona_id,
                "group_id": self.ctx.group_id,
                "sender_name": "群友A",
            },
            occurred_at="2026-11-27T00:10:00+00:00",
        )

    def payload(self, event_id: str) -> dict:
        return {
            "outcome": "memory",
            "summary": "群里聊到晚饭想吃拉面。",
            "summary_refs": [event_id],
            "key_facts": [],
            "importance": 0.5,
        }

    def batches(self) -> list[dict]:
        return [
            dict(row)
            for row in self.service.store._conn.execute("SELECT * FROM summary_batches ORDER BY created_at,id")
        ]

    def make_batch_due(self, batch_id: str) -> None:
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute(
                "UPDATE summary_batches SET next_retry_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", batch_id),
            )

    def test_transient_classifier_distinguishes_infra_5xx_429_from_content_errors(self) -> None:
        transient_samples = [
            "ServerError: 500 当前无可用凭证",
            "HTTP 500 Internal Server Error",
            "Error code: 500 - upstream failed",
            "status_code=500",
            "HTTP 429 Too Many Requests",
            "502 Bad Gateway",
            "503 Service Unavailable",
            "504 Gateway Timeout",
            "ReadTimeout: timed out",
            "APIConnectionError: Connection reset by peer",
            "网络中断，暂时不可用",
        ]
        for sample in transient_samples:
            with self.subTest(transient=sample):
                self.assertTrue(MemoryCompanionService._summary_failure_is_transient(sample))

        non_transient_samples = [
            "",
            "repair:invalid JSON response",
            "repair:用户提到了错误码 500 和 timeout",
            "invalid JSON response",
            "empty summary content",
            "RuntimeError: 400 Invalid request parameter",
            "ValueError: prompt exceeds 500 tokens",
            "401 Unauthorized",
            "403 Forbidden",
        ]
        for sample in non_transient_samples:
            with self.subTest(non_transient=sample):
                self.assertFalse(MemoryCompanionService._summary_failure_is_transient(sample))

    async def test_transient_500_429_timeout_never_quarantines_and_uses_exponential_cooldown(self) -> None:
        event_id = await self.seed_event()
        faults = [
            ServerError("500 当前无可用凭证", status_code=500),
            RuntimeError("HTTP 429 Too Many Requests"),
            RuntimeError("HTTP 502 Bad Gateway"),
            TimeoutError("ReadTimeout"),
            ConnectionError("Connection reset by peer"),
            self.payload(event_id),
        ]
        provider = Provider(faults)

        async def attempts(*_args, **_kwargs):
            return [{"source": "primary", "provider_id": "main-llm", "provider": provider}]

        self.service._summary_provider_attempts = attempts
        expected_delays = [600, 1200, 2400, 3600, 3600]

        for idx, expected_delay in enumerate(expected_delays, start=1):
            started = datetime.now(timezone.utc)
            self.assertEqual("", await self.service.maybe_summarize_session(self.ctx))
            batch = self.batches()[0]
            self.assertEqual("retry_pending", batch["state"], f"round {idx} must never quarantine")
            self.assertEqual(0, batch["automatic_calls"], "transient fault must not count toward quarantine calls")
            self.assertEqual(f"transient:{idx}", batch["retry_reason"])
            self.assertEqual("", batch["lease_token"])
            next_retry = datetime.fromisoformat(batch["next_retry_at"])
            self.assertGreaterEqual(next_retry, started + timedelta(seconds=expected_delay - 2))
            self.assertLessEqual(next_retry, started + timedelta(seconds=expected_delay + 15))
            self.make_batch_due(batch["id"])

        # Once upstream recovers, the exact same batch succeeds cleanly without manual intervention.
        memory_id = await self.service.maybe_summarize_session(self.ctx)
        self.assertTrue(memory_id)
        batch = self.batches()[0]
        self.assertEqual("completed", batch["state"])
        self.assertEqual(1, batch["automatic_calls"])
        self.assertEqual("", batch["retry_reason"])

    async def test_empty_fallback_inherits_astrbot_global_fallback_chain_and_fails_over(self) -> None:
        event_id = await self.seed_event()
        primary = _NamedProvider("provider-a/primary", [ServerError("500 当前无可用凭证", status_code=500)])
        fallback_1 = _NamedProvider("provider-a/fallback-1", [RuntimeError("HTTP 503 Service Unavailable")])
        fallback_2 = _NamedProvider("provider-a/fallback-2", [self.payload(event_id)])
        fake_ctx = _FakeAstrBotContext(
            providers={
                "provider-a/primary": primary,
                "provider-a/fallback-1": fallback_1,
                "provider-a/fallback-2": fallback_2,
            },
            current_provider=primary,
            config={
                "agent_runner": {
                    "config": {
                        "model": {
                            "provider_id": "provider-a/primary",
                            "fallback_provider_ids": [
                                "provider-a/primary",  # duplicate of current must be deduplicated
                                "provider-a/fallback-1",
                                "missing-provider",
                                "provider-a/fallback-2",
                            ],
                        }
                    }
                }
            },
        )
        self.service.context = fake_ctx

        attempts = await self.service._summary_provider_attempts(self.ctx)
        self.assertEqual(
            ["current_session", "host_fallback", "host_fallback"],
            [item["source"] for item in attempts],
        )
        self.assertEqual(
            ["provider-a/primary", "provider-a/fallback-1", "provider-a/fallback-2"],
            [item["provider_id"] for item in attempts],
        )

        # In a single round, primary 500 -> fallback_1 503 -> fallback_2 succeeds!
        memory_id = await self.service.maybe_summarize_session(self.ctx)
        self.assertTrue(memory_id)
        self.assertEqual(1, len(primary.calls))
        self.assertEqual(1, len(fallback_1.calls))
        self.assertEqual(1, len(fallback_2.calls))
        batch = self.batches()[0]
        self.assertEqual("completed", batch["state"])
        self.assertEqual(1, batch["automatic_calls"])

    async def test_explicit_fallback_provider_does_not_inject_host_fallbacks(self) -> None:
        primary = _NamedProvider("p-main", [])
        explicit_fb = _NamedProvider("p-explicit", [])
        host_fb = _NamedProvider("p-host", [])
        self.config["memory_summary"]["fallback_provider_id"] = "p-explicit"
        self.service.context = _FakeAstrBotContext(
            providers={"p-main": primary, "p-explicit": explicit_fb, "p-host": host_fb},
            current_provider=primary,
            config={"agent_runner": {"config": {"model": {"fallback_provider_ids": ["p-host"]}}}},
        )
        attempts = await self.service._summary_provider_attempts(self.ctx)
        self.assertEqual(["p-explicit", "p-main"], [item["provider_id"] for item in attempts])

    async def test_startup_recovery_unfreezes_only_transient_quarantined_batches(self) -> None:
        ev_500 = await self.seed_event("因上游 500 被误隔离的正常聊天")
        ev_429 = await self.seed_event("因上游 429 被误隔离的正常聊天")
        ev_bad = await self.seed_event("真内容解析失败的批次")
        ev_empty_err = await self.seed_event("无错误记录的隔离批次")

        async def create_quarantined(event_id: str, error_text: str) -> str:
            rows = list((await self.service.store.get_timeline_by_ids([event_id])).values())
            bid = await self.service.store.create_summary_batch(self.ctx.session_id, self.ctx.scope, rows)
            await self.service.store.defer_summary_batch(bid, error_text, quarantine=True, delay=0)
            return bid

        b_500 = await create_quarantined(ev_500, "ServerError: 500 当前无可用凭证")
        b_429 = await create_quarantined(ev_429, "HTTP 429 Too Many Requests")
        b_bad = await create_quarantined(ev_bad, "repair:invalid JSON response")
        b_empty = await create_quarantined(ev_empty_err, "")

        recovered = await self.service.recover_transient_quarantined_batches()
        self.assertTrue(recovered["ok"])
        self.assertEqual(2, recovered["released"])
        self.assertEqual({b_500, b_429}, set(recovered["batch_ids"]))

        for bid, expected_ev in ((b_500, ev_500), (b_429, ev_429)):
            batch = await self.service.store.get_summary_batch(bid)
            self.assertEqual("retry_pending", batch["state"])
            self.assertEqual(0, batch["automatic_calls"])
            self.assertIsNone(batch["next_retry_at"])
            self.assertEqual("", batch["last_error"])
            # Events remain attached so recovery picks up the exact batch immediately.
            rows = await self.service.store.summary_batch_rows(bid)
            self.assertEqual([expected_ev], [row["id"] for row in rows])

        # True content error and blank error MUST remain quarantined.
        self.assertEqual("quarantined", (await self.service.store.get_summary_batch(b_bad))["state"])
        self.assertEqual("quarantined", (await self.service.store.get_summary_batch(b_empty))["state"])

    async def test_transient_failover_refunds_round_calls_for_subsequent_fallback_chain(self) -> None:
        event_id = await self.seed_event()
        self.config["memory_summary"]["max_calls_per_batch"] = 2
        self.config["memory_summary"]["fallback_provider_id"] = ""
        p1 = _NamedProvider("provider-a/p1", [ServerError("500 当前无可用凭证", status_code=500)])
        p2 = _NamedProvider("provider-a/p2", [RuntimeError("HTTP 503 Service Unavailable")])
        p3 = _NamedProvider("provider-a/p3", [RuntimeError("400 bad request payload")])
        p4 = _NamedProvider("provider-a/p4", [self.payload(event_id)])
        self.service.context = _FakeAstrBotContext(
            providers={"provider-a/p1": p1, "provider-a/p2": p2, "provider-a/p3": p3, "provider-a/p4": p4},
            current_provider=p1,
            config={
                "agent_runner": {
                    "config": {
                        "model": {
                            "provider_id": "provider-a/p1",
                            "fallback_provider_ids": ["provider-a/p2", "provider-a/p3", "provider-a/p4"],
                        }
                    }
                }
            },
        )
        memory_id = await self.service.maybe_summarize_session(self.ctx)
        self.assertTrue(memory_id)
        self.assertEqual(1, len(p1.calls))
        self.assertEqual(1, len(p2.calls))
        self.assertEqual(1, len(p3.calls))
        self.assertEqual(1, len(p4.calls))
        batch = self.batches()[0]
        self.assertEqual("completed", batch["state"])
        self.assertEqual(2, batch["automatic_calls"])


class SourceQueryValidationHintTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {
            "startup": {"background_grace_seconds": 60},
            "memory_reconstruction": {"enabled": True},
            "memory_tools": {
                "enable_reconstruction_tool": True,
                "enable_query_progress": True,
                "enable_source_query_v2": True,
            },
        }
        self.service = MemoryCompanionService(
            context=None,
            config=self.config,
            plugin_root=ROOT,
            data_dir=Path(self.temp.name),
        )
        self.addCleanup(self.service.close)
        self.ctx = SessionContext(
            session_id="qq:FriendMessage:hint-user",
            scope="private",
            platform="qq",
            user_id="hint-user",
            bot_id="hint-bot",
            persona_id="hint-persona",
            message_id="turn-hint-1",
        )
        self.service.identity.resolve_event_context = AsyncMock(return_value=self.ctx)

    async def test_range_missing_start_at_returns_self_correcting_detail_and_hint_across_envelopes(self) -> None:
        event = SimpleNamespace()
        # 1) Query session v1 (default memory_companion_sources path via query_for_model)
        v1 = await self.service.query_for_model(event, "sources", action="range", limit=10)
        QUERY_V1_RESULT_VALIDATOR.validate(v1)
        self.assertFalse(v1["ok"])
        self.assertEqual("invalid_query_arguments", v1["error"])
        self.assertIn("start_at", v1["detail"])
        self.assertIn("start_at", v1["hint"])
        self.assertIn("action='search'", v1["hint"])

        # 2) Query session v3
        v3 = await self.service.tool_query_v3(event, "sources", {"action": "range", "limit": 10})
        QUERY_V3_RESULT_VALIDATOR.validate(v3)
        self.assertFalse(v3["ok"])
        self.assertEqual("invalid_query_arguments", v3["error"])
        self.assertIn("start_at", v3["detail"])
        self.assertIn("start_at", v3["hint"])

        # 3) Direct tool_sources (when enable_query_progress=False)
        direct = await self.service.tool_sources(event, action="range", limit=10)
        SOURCE_V1_RESULT_VALIDATOR.validate(direct)
        self.assertFalse(direct["ok"])
        self.assertEqual("range_requires_start_end_without_terms", direct["error"])
        self.assertIn("start_at", direct["detail"])
        self.assertIn("start_at", direct["hint"])

    async def test_other_common_source_argument_mistakes_return_clear_hints_and_valid_schema(self) -> None:
        event = SimpleNamespace()
        schema_rejected_cases = [
            ({"action": "search"}, "terms"),
            ({"action": "range", "start_at": "2026-11-25 10:00:00"}, "时区"),
            ({"action": "context"}, "source_ref"),
            ({"cursor": "src_abc", "terms": ["拿铁"]}, "cursor"),
            ({"action": "search", "terms": ["拿铁"], "bogus": 1}, "bogus"),
        ]
        for params, expected_token in schema_rejected_cases:
            with self.subTest(params=params):
                wrapped = await self.service.tool_query(event, "sources", params)
                QUERY_V1_RESULT_VALIDATOR.validate(wrapped)
                self.assertFalse(wrapped["ok"])
                self.assertEqual("invalid_query_arguments", wrapped["error"])
                combined = wrapped.get("detail", "") + " " + wrapped.get("hint", "")
                self.assertIn(expected_token, combined)

        # Reversed time range passes JSON schema and is rejected by source_query with detail/hint.
        reversed_wrapped = await self.service.tool_query(
            event,
            "sources",
            {
                "action": "range",
                "start_at": "2026-11-25T10:00:00+08:00",
                "end_at": "2026-11-25T09:00:00+08:00",
            },
        )
        QUERY_V1_RESULT_VALIDATOR.validate(reversed_wrapped)
        self.assertFalse(reversed_wrapped["ok"])
        owner_result = reversed_wrapped["result"]
        SOURCE_V1_RESULT_VALIDATOR.validate(owner_result)
        self.assertEqual("time_range_reversed_or_empty", owner_result["error"])
        self.assertIn("start_at", owner_result["detail"])
        self.assertIn("start_at", owner_result["hint"])

    async def test_range_batch_direct_rejection_includes_hint_and_passes_v2_schema(self) -> None:
        event = SimpleNamespace()
        event._memory_source_query_v2 = True
        event._memory_source_query_v2_key = self.service._reconstruction_budget_key(event, self.ctx)
        rejected = await self.service.tool_sources(event, action="range_batch")
        SOURCE_V2_RESULT_VALIDATOR.validate(rejected)
        self.assertFalse(rejected["ok"])
        self.assertEqual("range_requires_start_end_without_terms", rejected["error"])
        self.assertIn("start_at", rejected["detail"])
        self.assertIn("start_at", rejected["hint"])

        detail, hint = diagnose_source_query_parameters(
            {"action": "range_batch", "start_at": "2026-11-25T10:00:00+08:00", "limit": 10}
        )
        self.assertIn("limit", detail)
        self.assertIn("limit", hint)


if __name__ == "__main__":
    unittest.main()
