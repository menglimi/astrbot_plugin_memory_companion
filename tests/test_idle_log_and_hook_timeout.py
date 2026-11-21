"""Regression tests for idle auto-drain skip log level and hook-bounded remote call timeouts."""

from __future__ import annotations

import asyncio
import gc
import importlib.util
import logging
import sys
import tempfile
import time
import types
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import latency as latency_mod
from astrbot_plugin_memory_companion.core import service as service_mod
from astrbot_plugin_memory_companion.core.latency import (
    MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS,
    MAX_HOOK_MODEL_CALL_WAIT_SECONDS,
    _ActiveTimeBudget,
    await_with_memory_hook_budget,
    await_with_timeout,
    bounded_model_call_timeout_ms,
    effective_model_call_timeout_seconds,
    exclude_model_call_wait,
)
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SearchResult,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


class _HangingEmbeddingProvider:
    def __init__(self, delay_seconds: float = 5.0) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    async def get_embedding(self, _text: str) -> list[float]:
        self.calls += 1
        await asyncio.sleep(self.delay_seconds)
        return [1.0, 0.0]


class _HangingRerankProvider:
    def __init__(self, delay_seconds: float = 5.0) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        await asyncio.sleep(self.delay_seconds)
        return {"results": [{"index": 0, "relevance_score": 0.9}]}


class IdleSkipLogAndHookTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_drain_skip_logs_at_debug_while_completion_stays_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryCompanionService(
                context=None,
                config={
                    "memory_summary": {
                        "auto_drain_enabled": True,
                        "auto_drain_interval_minutes": 1,
                    }
                },
                plugin_root=Path(ROOT),
                data_dir=Path(tmp),
            )
            try:
                fake_sessions = [
                    {
                        "session_id": "qq:FriendMessage:idle-u1",
                        "scope": "private",
                        "bot_id": "b1",
                        "pending_events": 1,
                        "oldest": "",
                    },
                    {
                        "session_id": "qq:FriendMessage:done-u2",
                        "scope": "private",
                        "bot_id": "b1",
                        "pending_events": 4,
                        "oldest": "",
                    },
                ]
                results = iter(["", "mem_summary_done_1"])

                drain_rounds = 0

                async def fake_list_summary_backlog_sessions(limit: int = 5):
                    nonlocal drain_rounds
                    drain_rounds += 1
                    return list(fake_sessions)

                processed_sessions = 0

                async def fake_maybe_summarize(
                    ctx: SessionContext,
                    force: bool = False,
                    allow_aged_backlog: bool = False,
                ) -> str:
                    nonlocal processed_sessions
                    processed_sessions += 1
                    return next(results)

                async def fake_sleep(seconds: float) -> None:
                    # Stop after the first drain cycle completes (bounded even on unexpected errors).
                    if (processed_sessions >= len(fake_sessions) or drain_rounds >= 1) and seconds >= 60:
                        service._closing = True
                    return

                debug_records: list[str] = []
                info_records: list[str] = []

                def record_debug(msg: str, *args: Any, **kwargs: Any) -> None:
                    debug_records.append(msg % args if args else str(msg))

                def record_info(msg: str, *args: Any, **kwargs: Any) -> None:
                    info_records.append(msg % args if args else str(msg))

                with (
                    patch.object(service.store, "list_summary_backlog_sessions", side_effect=fake_list_summary_backlog_sessions),
                    patch.object(service.store, "close_orphan_retry_batches", return_value=0),
                    patch.object(service, "auto_distill_core_memory", return_value={}),
                    patch.object(service, "maybe_summarize_session", side_effect=fake_maybe_summarize),
                    patch.object(service_mod.asyncio, "sleep", side_effect=fake_sleep),
                    patch.object(service_mod.logger, "debug", side_effect=record_debug),
                    patch.object(service_mod.logger, "info", side_effect=record_info),
                ):
                    await service._summary_drain_dispatch_loop()

                self.assertTrue(
                    any("自动消化跳过" in line and "idle-u1" in line and "force=" not in line for line in debug_records),
                    f"expected skip log at DEBUG without force=, got debug={debug_records} info={info_records}",
                )
                self.assertFalse(
                    any("自动消化跳过" in line for line in info_records),
                    f"skip log must not be emitted at INFO, got info={info_records}",
                )
                self.assertTrue(
                    any("自动消化完成" in line and "mem_summary_done_1" in line for line in info_records),
                    f"completion log must remain at INFO, got info={info_records}",
                )
            finally:
                service.close()

    async def test_effective_model_call_timeout_excludes_prior_wait_and_enforces_ceiling(self) -> None:
        # Outside any active hook budget: configured timeout stays intact.
        self.assertEqual(15.0, effective_model_call_timeout_seconds(15.0))
        self.assertEqual(0.0, effective_model_call_timeout_seconds(float("nan")))
        self.assertEqual(0.0, effective_model_call_timeout_seconds(-1.0))

        # Inside hook budget WITHOUT remote-wait ceiling or fraction: legacy behavior unchanged.
        async def without_cap() -> float:
            return effective_model_call_timeout_seconds(15.0)

        self.assertEqual(15.0, await await_with_memory_hook_budget(without_cap(), 0.2))

        # Inside hook budget WITH max_model_call_wait_seconds=12.0 and default 1.0s local budget:
        # 1.2s of excluded embedding wait must NOT starve a downstream 5.0s rerank call,
        # while an oversized 30.0s request is still capped by the remaining 10.8s hard ceiling.
        observed_wait_cap: dict[str, float] = {}

        async def after_excluded_embedding() -> None:
            async with exclude_model_call_wait():
                await asyncio.sleep(1.2)
            observed_wait_cap["rerank_5s"] = effective_model_call_timeout_seconds(5.0)
            observed_wait_cap["huge_30s"] = effective_model_call_timeout_seconds(30.0)

        await await_with_memory_hook_budget(
            after_excluded_embedding(),
            1.0,
            max_model_call_wait_seconds=MAX_HOOK_MODEL_CALL_WAIT_SECONDS,
        )
        self.assertEqual(5.0, observed_wait_cap["rerank_5s"])
        self.assertGreater(observed_wait_cap["huge_30s"], 9.5)
        self.assertLessEqual(observed_wait_cap["huge_30s"], 11.0)

        # When model_call_budget_fraction IS explicitly set, excluded waits must not
        # drain budget.remaining either.
        observed_fraction: dict[str, float] = {}

        async def with_fraction_after_excluded_wait() -> None:
            async with exclude_model_call_wait():
                await asyncio.sleep(0.18)
            observed_fraction["capped"] = effective_model_call_timeout_seconds(15.0)
            observed_fraction["small"] = effective_model_call_timeout_seconds(0.05)

        await await_with_memory_hook_budget(
            with_fraction_after_excluded_wait(),
            0.3,
            model_call_budget_fraction=0.7,
        )
        self.assertGreater(observed_fraction["capped"], 0.15)
        self.assertLessEqual(observed_fraction["capped"], 0.21 + 0.01)
        self.assertEqual(0.05, observed_fraction["small"])

    async def test_excluded_embedding_wait_does_not_starve_downstream_rerank(self) -> None:
        class SlowButHealthyEmbeddingProvider:
            async def get_embedding(self, _text: str) -> list[float]:
                await asyncio.sleep(0.18)
                return [1.0, 0.0]

        class SlowButHealthyRerankProvider:
            async def rerank(
                self,
                *,
                query: str,
                documents: list[str],
                top_n: int | None = None,
            ) -> dict[str, Any]:
                await asyncio.sleep(0.16)
                return {
                    "results": [
                        {"index": 1, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.3},
                    ]
                }

        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            embedding_enabled=True,
            embedding_provider=SlowButHealthyEmbeddingProvider(),
            embedding_timeout_ms=1000,
            rerank_provider=SlowButHealthyRerankProvider(),
            rerank_timeout_ms=1000,
            knowledge_graph_enabled=False,
        )
        ranked = [
            SearchResult(memory=MemoryRecord(id="m1", content="候选记忆一"), score=0.9),
            SearchResult(memory=MemoryRecord(id="m2", content="候选记忆二"), score=0.5),
        ]

        async def run_pipeline() -> list[SearchResult]:
            vec = await engine._call_embedding_provider("查询")
            self.assertEqual([1.0, 0.0], vec)
            return await engine._maybe_rerank_results("查询", ranked, 2)

        # Even when local hook budget (0.15s) is smaller than the prior excluded embedding
        # wait (0.18s), rerank still succeeds under the shared excluded-wait ceiling.
        results = await await_with_memory_hook_budget(
            run_pipeline(),
            0.15,
            max_model_call_wait_seconds=1.0,
        )
        self.assertEqual(["m2", "m1"], [item.memory.id for item in results])
        self.assertEqual("rerank", engine.last_path_info.get("path"))

    async def test_slow_embedding_degrades_to_local_fts_within_hook_wait_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                record = MemoryRecord(
                    id="mem-local-fallback-1",
                    memory_type="user_preference",
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    platform="qq",
                    owner_bot_id="b1",
                    subject=EntityRef(kind="user", id="u1", name="测试用户"),
                    content="测试用户最喜欢喝冰美式和抹茶拿铁",
                    visibility="private_pair",
                    lifecycle="long_term",
                    confidence=0.95,
                    importance=0.9,
                    metadata={"persona_id": "p1"},
                )
                await store.insert_memory(record)

                embedding_provider = _HangingEmbeddingProvider(delay_seconds=5.0)
                engine = RetrievalEngine(
                    store,
                    VisibilityPolicy(),
                    retrieval_mode="basic",
                    embedding_enabled=True,
                    embedding_provider=embedding_provider,
                    embedding_provider_id="slow-embed",
                    embedding_timeout_ms=2000,
                    knowledge_graph_enabled=False,
                )
                ctx = SessionContext(
                    session_id="qq:FriendMessage:u1",
                    scope="private",
                    platform="qq",
                    user_id="u1",
                    bot_id="b1",
                    persona_id="p1",
                    message_text="我喜欢喝什么咖啡和抹茶",
                )

                started = time.monotonic()
                results, _blocked = await await_with_memory_hook_budget(
                    engine.search_with_diagnostics("冰美式 抹茶拿铁", ctx, 5),
                    0.4,
                    max_model_call_wait_seconds=0.2,
                )
                elapsed = time.monotonic() - started

                self.assertEqual(1, embedding_provider.calls)
                self.assertLess(elapsed, 0.65)
                self.assertEqual("local_fts_keyword", engine.last_path_info.get("embedding_fallback"))
                self.assertIn("TimeoutError", str(engine.last_path_info.get("embedding_reason") or ""))
                self.assertTrue(
                    any(item.memory.id == "mem-local-fallback-1" for item in results),
                    f"expected local keyword fallback result, got {results}",
                )
            finally:
                store.close()

    async def test_slow_rerank_degrades_to_basic_within_hook_wait_ceiling(self) -> None:
        rerank_provider = _HangingRerankProvider(delay_seconds=5.0)
        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=rerank_provider,
            rerank_provider_id="slow-rerank",
            rerank_timeout_ms=2000,
            knowledge_graph_enabled=False,
        )
        ranked = [
            SearchResult(memory=MemoryRecord(id="m1", content="周末去爬山"), score=0.9),
            SearchResult(memory=MemoryRecord(id="m2", content="周一开晨会"), score=0.5),
        ]

        started = time.monotonic()
        results = await await_with_memory_hook_budget(
            engine._maybe_rerank_results("周末安排", ranked, 2),
            0.4,
            max_model_call_wait_seconds=0.2,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(1, rerank_provider.calls)
        self.assertLess(elapsed, 0.55)
        self.assertEqual(["m1", "m2"], [item.memory.id for item in results])
        self.assertEqual("fallback_basic", engine.last_path_info.get("path"))

    async def test_on_llm_request_enables_hook_model_call_wait_ceiling(self) -> None:
        def _fake_astrbot_modules() -> dict[str, types.ModuleType]:
            astrbot_mod = types.ModuleType("astrbot")
            api_mod = types.ModuleType("astrbot.api")
            api_mod.logger = logging.getLogger("test_hook_timeout_plugin")
            event_mod = types.ModuleType("astrbot.api.event")
            event_mod.AstrMessageEvent = type("AstrMessageEvent", (), {})
            event_mod.MessageEventResult = type("MessageEventResult", (), {})
            filter_mod = types.ModuleType("astrbot.api.event.filter")
            filter_mod.PermissionType = SimpleNamespace(ADMIN="ADMIN", MEMBER="MEMBER")
            filter_mod.EventMessageType = SimpleNamespace(GROUP_MESSAGE="GROUP", PRIVATE_MESSAGE="PRIVATE")
            filter_mod.permission_type = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.command_group = lambda *_a, **_k: (
                lambda _fn: SimpleNamespace(command=lambda *_ca, **_ck: (lambda sub: sub))
            )
            filter_mod.command = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.on_llm_request = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.on_llm_response = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.event_message_type = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.llm_tool = lambda *_a, **_k: (lambda fn: fn)
            event_mod.filter = filter_mod
            provider_mod = types.ModuleType("astrbot.api.provider")
            provider_mod.LLMResponse = type("LLMResponse", (), {})
            provider_mod.ProviderRequest = type("ProviderRequest", (), {})
            star_mod = types.ModuleType("astrbot.api.star")
            star_mod.Context = type("Context", (), {})
            star_mod.Star = type("Star", (), {"__init__": lambda self, *_a, **_k: None})
            star_mod.StarTools = SimpleNamespace(get_data_dir=lambda _name: tempfile.gettempdir())
            star_mod.register = lambda *_a, **_k: (lambda cls: cls)
            return {
                "astrbot": astrbot_mod,
                "astrbot.api": api_mod,
                "astrbot.api.event": event_mod,
                "astrbot.api.event.filter": filter_mod,
                "astrbot.api.provider": provider_mod,
                "astrbot.api.star": star_mod,
            }

        with patch.dict(sys.modules, _fake_astrbot_modules()):
            spec = importlib.util.spec_from_file_location(
                "astrbot_plugin_memory_companion._isolated_main_hook_timeout",
                Path(ROOT) / "main.py",
            )
            self.assertIsNotNone(spec)
            assert spec is not None and spec.loader is not None
            isolated_main = importlib.util.module_from_spec(spec)
            isolated_main.__package__ = "astrbot_plugin_memory_companion"
            spec.loader.exec_module(isolated_main)

            plugin = object.__new__(isolated_main.MemoryCompanionPlugin)
            plugin._terminated = False
            plugin._init_failed = False

            observed_timeout: dict[str, float] = {}

            async def fake_initialize_database() -> bool:
                return True

            async def fake_handle_llm_request(_event: Any, _req: Any) -> None:
                async with exclude_model_call_wait():
                    await asyncio.sleep(0.12)
                observed_timeout["rerank_5s"] = effective_model_call_timeout_seconds(5.0)
                observed_timeout["oversized_30s"] = effective_model_call_timeout_seconds(30.0)

            plugin.service = SimpleNamespace(
                config=SimpleNamespace(float=lambda _key, _default=0.0: 0.4),
                initialize_database=fake_initialize_database,
                handle_llm_request=fake_handle_llm_request,
            )

            await plugin.on_llm_request(SimpleNamespace(), SimpleNamespace())
            self.assertEqual(5.0, observed_timeout["rerank_5s"])
            self.assertGreater(observed_timeout["oversized_30s"], MAX_HOOK_MODEL_CALL_WAIT_SECONDS - 1.0)
            self.assertLessEqual(observed_timeout["oversized_30s"], MAX_HOOK_MODEL_CALL_WAIT_SECONDS)

    async def test_await_with_timeout_fails_fast_when_local_budget_or_wait_ceiling_exhausted(self) -> None:
        async def slow_remote() -> str:
            await asyncio.sleep(1.0)
            return "late"

        # Case 1: shared excluded-wait ceiling already consumed by earlier remote I/O.
        async def run_wait_ceiling_exhausted() -> None:
            async with exclude_model_call_wait():
                await asyncio.sleep(0.12)
            self.assertEqual(0.0, effective_model_call_timeout_seconds(5.0))
            with self.assertRaises(asyncio.TimeoutError):
                await await_with_timeout(slow_remote(), 5.0)

        started = time.monotonic()
        await await_with_memory_hook_budget(
            run_wait_ceiling_exhausted(),
            0.5,
            max_model_call_wait_seconds=0.08,
        )
        self.assertLess(time.monotonic() - started, 0.35)

        # Case 2: active local hook budget already exhausted (remaining == 0).
        exhausted_budget = _ActiveTimeBudget(0.0, max_model_call_wait_seconds=12.0)
        token = latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.set(exhausted_budget)
        started = time.monotonic()
        try:
            self.assertEqual(0.0, effective_model_call_timeout_seconds(5.0))
            with self.assertRaises(asyncio.TimeoutError):
                await await_with_timeout(slow_remote(), 5.0)
        finally:
            latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.reset(token)
        self.assertLess(time.monotonic() - started, 0.25)

    async def test_background_tasks_spawned_inside_hook_do_not_inherit_hook_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryCompanionService(
                context=None,
                config={"retrieval": {"embedding_timeout_ms": 2000}},
                plugin_root=Path(ROOT),
                data_dir=Path(tmp),
            )
            service._background_grace_seconds = 0
            try:
                class HealthyEmbeddingProvider:
                    async def get_embedding(self, _text: str) -> list[float]:
                        await asyncio.sleep(0.03)
                        return [0.25, 0.75]

                bg_observed: dict[str, Any] = {}
                persist_observed: dict[str, Any] = {}
                raw_observed: dict[str, Any] = {}
                hook_done = asyncio.Event()
                bg_started = asyncio.Event()

                async def background_work() -> None:
                    bg_observed["during_hook"] = effective_model_call_timeout_seconds(5.0)
                    bg_started.set()
                    await hook_done.wait()
                    await asyncio.sleep(0.12)
                    bg_observed["after_hook_expired"] = effective_model_call_timeout_seconds(5.0)
                    bg_observed["vector"] = await service._embed_text_with_provider(
                        HealthyEmbeddingProvider(),
                        "后台向量索引不应受请求钩子预算污染",
                    )

                async def persistence_work() -> None:
                    persist_observed["during_hook"] = effective_model_call_timeout_seconds(5.0)
                    await hook_done.wait()
                    await asyncio.sleep(0.12)
                    persist_observed["after_hook_expired"] = effective_model_call_timeout_seconds(5.0)

                async def raw_stray_task() -> None:
                    await hook_done.wait()
                    await asyncio.sleep(0.12)
                    raw_observed["after_hook_closed"] = effective_model_call_timeout_seconds(5.0)

                tasks: list[asyncio.Task[Any]] = []

                async def hook_body() -> None:
                    bg_task = service._spawn_background(background_work(), label="audit-bg-embed")
                    persist_task = service._spawn_persistence_task(
                        persistence_work(),
                        label="audit-bg-persist",
                    )
                    stray_task = asyncio.create_task(raw_stray_task())
                    self.assertIsNotNone(bg_task)
                    self.assertIsNotNone(persist_task)
                    assert bg_task is not None and persist_task is not None
                    tasks.extend([bg_task, persist_task, stray_task])
                    await bg_started.wait()
                    # Hook's own context still retains the active ceiling.
                    self.assertLessEqual(effective_model_call_timeout_seconds(5.0), 0.08)

                await await_with_memory_hook_budget(
                    hook_body(),
                    0.08,
                    max_model_call_wait_seconds=0.08,
                )
                hook_done.set()
                await asyncio.gather(*tasks)

                self.assertEqual(5.0, bg_observed["during_hook"])
                self.assertEqual(5.0, bg_observed["after_hook_expired"])
                self.assertEqual([0.25, 0.75], bg_observed["vector"])
                self.assertEqual(5.0, persist_observed["during_hook"])
                self.assertEqual(5.0, persist_observed["after_hook_expired"])
                self.assertEqual(5.0, raw_observed["after_hook_closed"])
            finally:
                await service.aclose()

    async def test_await_with_timeout_zero_or_nonfinite_fails_fast_without_starting_coroutine(self) -> None:
        started = 0

        async def side_effect_remote() -> str:
            nonlocal started
            started += 1
            await asyncio.sleep(1.0)
            return "late"

        async def immediate_remote() -> str:
            nonlocal started
            started += 1
            return "instant"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            for raw_timeout in (0.0, -1.0, float("nan"), float("-inf")):
                with self.subTest(raw_timeout=raw_timeout):
                    with self.assertRaises(asyncio.TimeoutError):
                        await await_with_timeout(side_effect_remote(), raw_timeout)
                    with self.assertRaises(asyncio.TimeoutError):
                        await await_with_timeout(immediate_remote(), raw_timeout)

            pending_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            with self.assertRaises(asyncio.TimeoutError):
                await await_with_timeout(pending_future, 0.0)
            self.assertTrue(pending_future.cancelled())

        self.assertEqual(0, started)
        self.assertFalse(
            any("was never awaited" in str(item.message) for item in caught),
            f"unexpected unawaited coroutine warning: {[str(item.message) for item in caught]}",
        )

    async def test_nested_exclude_model_call_wait_concurrent_hooks_and_unwind(self) -> None:
        # 1. Nested exclude_model_call_wait keeps active budget frozen until outer exits,
        # tracks wall union without double-counting, and unwinds cleanly on inner exception.
        observed: dict[str, Any] = {}

        async def nested_waits() -> None:
            budget = latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get()
            self.assertIsNotNone(budget)
            assert budget is not None
            async with exclude_model_call_wait():
                await asyncio.sleep(0.06)
                with self.assertRaisesRegex(RuntimeError, "inner boom"):
                    async with exclude_model_call_wait():
                        await asyncio.sleep(0.06)
                        raise RuntimeError("inner boom")
                # Outer pause must still be active after inner exception unwind.
                self.assertEqual(1, budget._pause_depth)
                await asyncio.sleep(0.06)
            observed["pause_depth_after"] = budget._pause_depth
            observed["remaining_after"] = budget.remaining
            observed["excluded_elapsed"] = budget.excluded_elapsed

        await await_with_memory_hook_budget(
            nested_waits(),
            0.12,
            max_model_call_wait_seconds=2.0,
        )
        self.assertEqual(0, observed["pause_depth_after"])
        self.assertGreater(observed["remaining_after"], 0.04)
        self.assertGreaterEqual(observed["excluded_elapsed"], 0.14)
        self.assertLess(observed["excluded_elapsed"], 0.5)
        self.assertIsNone(latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get())

        # 2. Concurrent hooks have isolated ContextVars with distinct ceilings.
        barrier = asyncio.Event()

        async def worker(wait_ceiling: float, probe_timeout: float) -> float:
            if wait_ceiling < 1.0:
                await barrier.wait()
            else:
                barrier.set()
            return effective_model_call_timeout_seconds(probe_timeout)

        short_cap, long_cap = await asyncio.gather(
            await_with_memory_hook_budget(worker(0.25, 10.0), 0.5, max_model_call_wait_seconds=0.25),
            await_with_memory_hook_budget(worker(8.0, 10.0), 0.5, max_model_call_wait_seconds=8.0),
        )
        self.assertLessEqual(short_cap, 0.25)
        self.assertGreater(short_cap, 0.0)
        self.assertGreater(long_cap, 7.0)
        self.assertLessEqual(long_cap, 8.0)

        # 3. External cancellation unwinds pause depth and resets ContextVar cleanly.
        entered_pause = asyncio.Event()
        cancelled_budget_holder: list[_ActiveTimeBudget] = []

        async def cancellable_hook() -> None:
            budget = latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get()
            assert budget is not None
            cancelled_budget_holder.append(budget)
            async with exclude_model_call_wait():
                entered_pause.set()
                await asyncio.sleep(5.0)

        hook_task = asyncio.create_task(
            await_with_memory_hook_budget(
                cancellable_hook(),
                0.5,
                max_model_call_wait_seconds=5.0,
            )
        )
        await entered_pause.wait()
        hook_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await hook_task
        await asyncio.sleep(0)
        self.assertTrue(cancelled_budget_holder[0].closed)
        self.assertEqual(0, cancelled_budget_holder[0]._pause_depth)
        self.assertIsNone(latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get())

        # 4. Invalid awaitable and NaN/negative budget durations do not leak ContextVar.
        with self.assertRaises(TypeError):
            await await_with_memory_hook_budget("not-an-awaitable", 1.0)
        self.assertIsNone(latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get())

        for invalid_budget in (float("nan"), -1.0, 0.0):
            with self.subTest(invalid_budget=invalid_budget):
                with self.assertRaises(asyncio.TimeoutError):
                    await await_with_memory_hook_budget(asyncio.sleep(0.5), invalid_budget)
                self.assertIsNone(latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get())

        # Non-finite ceilings disable the cap without crashing.
        async def probe_nonfinite_cap() -> float:
            return effective_model_call_timeout_seconds(9.5)

        for nonfinite in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(nonfinite=nonfinite):
                result = await await_with_memory_hook_budget(
                    probe_nonfinite_cap(),
                    0.5,
                    max_model_call_wait_seconds=nonfinite,
                    model_call_budget_fraction=nonfinite,
                )
                self.assertEqual(9.5, result)

    async def test_configured_10s_timeouts_integrate_cleanly_with_12s_hook_ceiling(self) -> None:
        max_configured_seconds = bounded_model_call_timeout_ms(MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS) / 1000.0
        self.assertEqual(10.0, max_configured_seconds)
        self.assertEqual(12.0, MAX_HOOK_MODEL_CALL_WAIT_SECONDS)
        self.assertEqual(10.0, effective_model_call_timeout_seconds(max_configured_seconds))

        observed: dict[str, float] = {}

        async def check_10s_under_12s_ceiling() -> None:
            observed["initial_10s"] = effective_model_call_timeout_seconds(max_configured_seconds)
            async with exclude_model_call_wait():
                await asyncio.sleep(0.15)
            observed["after_short_embed_10s"] = effective_model_call_timeout_seconds(max_configured_seconds)
            observed["oversized_20s"] = effective_model_call_timeout_seconds(20.0)

        await await_with_memory_hook_budget(
            check_10s_under_12s_ceiling(),
            1.0,
            max_model_call_wait_seconds=MAX_HOOK_MODEL_CALL_WAIT_SECONDS,
        )
        self.assertEqual(10.0, observed["initial_10s"])
        self.assertEqual(10.0, observed["after_short_embed_10s"])
        self.assertLessEqual(observed["oversized_20s"], MAX_HOOK_MODEL_CALL_WAIT_SECONDS)
        self.assertGreater(observed["oversized_20s"], MAX_HOOK_MODEL_CALL_WAIT_SECONDS - 1.0)

    async def test_hook_budget_zero_or_nonfinite_fails_fast_without_starting_coroutine(self) -> None:
        started = 0

        async def immediate_hook() -> str:
            nonlocal started
            started += 1
            return "instant"

        async def suspending_hook() -> str:
            nonlocal started
            started += 1
            await asyncio.sleep(1.0)
            return "late"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            for invalid_budget in (0.0, -1.0, float("nan"), float("-inf")):
                with self.subTest(invalid_budget=invalid_budget):
                    with self.assertRaises(asyncio.TimeoutError):
                        await await_with_memory_hook_budget(immediate_hook(), invalid_budget)
                    with self.assertRaises(asyncio.TimeoutError):
                        await await_with_memory_hook_budget(suspending_hook(), invalid_budget)
                    self.assertIsNone(latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get())

            pending_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            with self.assertRaises(asyncio.TimeoutError):
                await await_with_memory_hook_budget(pending_future, 0.0)
            self.assertTrue(pending_future.cancelled())

            with self.assertRaises(TypeError):
                await await_with_memory_hook_budget("not-an-awaitable", 0.0)
            with self.assertRaises(TypeError):
                await await_with_timeout("not-an-awaitable", 0.0)
            self.assertIsNone(latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get())

        self.assertEqual(0, started)
        self.assertFalse(
            any("was never awaited" in str(item.message) for item in caught),
            f"unexpected unawaited coroutine warning: {[str(item.message) for item in caught]}",
        )

    async def test_same_tick_task_exception_and_outer_cancellation_leaves_no_unretrieved_exception(
        self,
    ) -> None:
        loop = asyncio.get_running_loop()
        unhandled: list[dict[str, Any]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, ctx: unhandled.append(ctx))
        try:
            ready = asyncio.Event()

            async def fail_on_resume() -> None:
                await ready.wait()
                raise RuntimeError("same-tick failure")

            outer = asyncio.create_task(
                await_with_memory_hook_budget(fail_on_resume(), 1.0)
            )
            await asyncio.sleep(0)
            ready.set()
            outer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await outer
            await asyncio.sleep(0)
            gc.collect()
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        self.assertEqual([], unhandled, f"unexpected unhandled loop exceptions: {unhandled}")
        self.assertIsNone(latency_mod._ACTIVE_MEMORY_HOOK_BUDGET.get())


if __name__ == "__main__":
    unittest.main()
