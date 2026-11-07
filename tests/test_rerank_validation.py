from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
from typing import Any


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import MemoryRecord, SearchResult
from astrbot_plugin_memory_companion.core.latency import (
    MAX_MEMORY_HOOK_BUDGET_SECONDS,
    MAX_MODEL_CALL_TIMEOUT_MS,
    await_with_memory_hook_budget,
    bounded_memory_hook_budget_seconds,
    bounded_model_call_timeout_ms,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine


class _RecordingRerankProvider:
    def __init__(self, response: Any = None):
        self.response = response if response is not None else {"results": []}
        self.calls: list[dict[str, Any]] = []

    async def rerank(self, *, query: str, documents: list[str], top_n: int | None = None) -> Any:
        self.calls.append({"query": query, "documents": documents, "top_n": top_n})
        return self.response


def _result(memory_id: str, content: str, score: float) -> SearchResult:
    return SearchResult(memory=MemoryRecord(id=memory_id, content=content), score=score)


class RerankInputValidationTests(unittest.IsolatedAsyncioTestCase):
    def test_latency_budgets_cannot_exceed_the_configured_caps(self) -> None:
        self.assertEqual(1.0, bounded_memory_hook_budget_seconds(5.0))
        self.assertEqual(0.25, bounded_memory_hook_budget_seconds(0.25))
        self.assertEqual(MAX_MEMORY_HOOK_BUDGET_SECONDS, bounded_memory_hook_budget_seconds(0))
        self.assertEqual(800, bounded_model_call_timeout_ms(800))
        self.assertEqual(MAX_MODEL_CALL_TIMEOUT_MS, bounded_model_call_timeout_ms(9000))
        self.assertEqual(MAX_MODEL_CALL_TIMEOUT_MS, bounded_model_call_timeout_ms(0))

    def test_retrieval_engine_caps_provider_timeouts(self) -> None:
        engine = RetrievalEngine(None, None, rerank_timeout_ms=9000, embedding_timeout_ms=0)

        self.assertEqual(MAX_MODEL_CALL_TIMEOUT_MS, engine.rerank_timeout_ms)
        self.assertEqual(MAX_MODEL_CALL_TIMEOUT_MS, engine.embedding_timeout_ms)

    async def test_memory_hook_budget_excludes_embedding_and_rerank_waits(self) -> None:
        class SlowEmbeddingProvider:
            async def get_embedding(self, _text: str) -> list[float]:
                await asyncio.sleep(0.12)
                return [1.0, 0.0]

        class SlowRerankProvider:
            async def rerank(
                self,
                *,
                query: str,
                documents: list[str],
                top_n: int | None = None,
            ) -> dict[str, Any]:
                await asyncio.sleep(0.12)
                return {"results": [{"index": 0, "relevance_score": 0.9}]}

        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=SlowRerankProvider(),
            embedding_provider=SlowEmbeddingProvider(),
            embedding_enabled=True,
            embedding_timeout_ms=500,
            rerank_timeout_ms=500,
        )

        async def handle_request() -> None:
            await asyncio.sleep(0.02)
            self.assertEqual([1.0, 0.0], await engine._call_embedding_provider("问题"))
            await engine._call_rerank_provider("问题", ["记忆"])
            await asyncio.sleep(0.02)

        started = time.monotonic()
        await await_with_memory_hook_budget(handle_request(), 0.15)

        self.assertGreater(time.monotonic() - started, 0.22)

    async def test_memory_hook_budget_still_limits_plugin_processing(self) -> None:
        started = time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):
            await await_with_memory_hook_budget(asyncio.sleep(0.1), 0.02)

        self.assertLess(time.monotonic() - started, 0.08)

    async def test_rerank_deadline_does_not_wait_for_provider_cancel_cleanup(self) -> None:
        provider_finished = asyncio.Event()

        class CancellationResistantProvider:
            async def rerank(self, *, query: str, documents: list[str], top_n: int | None = None):
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    await asyncio.sleep(0.3)
                    provider_finished.set()
                    return {"results": []}

        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=CancellationResistantProvider(),
            rerank_timeout_ms=20,
        )
        started = time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):
            await engine._call_rerank_provider("查询", ["候选"])

        self.assertLess(time.monotonic() - started, 0.15)
        await asyncio.wait_for(provider_finished.wait(), timeout=1.0)

    async def test_sync_embedding_timeout_does_not_block_event_loop(self) -> None:
        class BlockingProvider:
            def get_embedding(self, _text: str):
                time.sleep(0.2)
                return [1.0, 0.0]

        engine = RetrievalEngine(
            None,
            None,
            embedding_provider=BlockingProvider(),
            embedding_timeout_ms=30,
        )
        loop_work = asyncio.create_task(asyncio.sleep(0.01, result=True))

        with self.assertRaises(asyncio.TimeoutError):
            await engine._call_embedding_provider("一个问题")

        self.assertTrue(await loop_work)

    async def test_sync_provider_timeout_does_not_block_event_loop(self) -> None:
        class BlockingProvider:
            def rerank(self, *, query: str, documents: list[str], top_n: int | None = None):
                time.sleep(0.2)
                return {"results": [{"index": 0, "relevance_score": 0.9}]}

        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=BlockingProvider(),
            rerank_timeout_ms=30,
        )
        loop_work = asyncio.create_task(asyncio.sleep(0.01, result=True))

        with self.assertRaises(asyncio.TimeoutError):
            await engine._call_rerank_provider("一个问题", ["一条候选记忆"])

        self.assertTrue(await loop_work)

    async def test_default_timeout_allows_slow_provider_to_finish(self) -> None:
        class SlowProvider:
            async def rerank(self, *, query: str, documents: list[str], top_n: int | None = None):
                await asyncio.sleep(1.5)
                return {"results": [{"index": 0, "relevance_score": 0.9}]}

        engine = RetrievalEngine(None, None, retrieval_mode="rerank", rerank_provider=SlowProvider())
        ranked = [_result("first", "一条候选记忆", 1.0)]

        results = await engine._maybe_rerank_results("一个问题", ranked, 1)

        self.assertEqual(["first"], [item.memory.id for item in results])
        self.assertEqual("rerank", engine.last_path_info["path"])
        self.assertEqual(2000, engine.rerank_timeout_ms)

    async def test_empty_query_skips_provider_and_keeps_basic_order(self) -> None:
        provider = _RecordingRerankProvider()
        engine = RetrievalEngine(None, None, retrieval_mode="auto", rerank_provider=provider)
        ranked = [_result("first", "第一条记忆", 1.0)]

        results = await engine._maybe_rerank_results(" \t\u3000", ranked, 1)

        self.assertEqual(["first"], [item.memory.id for item in results])
        self.assertEqual([], provider.calls)
        self.assertEqual("basic", engine.last_path_info["path"])
        self.assertEqual("rerank_skipped_empty_query", engine.last_path_info["reason"])

    async def test_empty_documents_are_filtered_without_breaking_response_indexes(self) -> None:
        provider = _RecordingRerankProvider(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            }
        )
        engine = RetrievalEngine(None, None, retrieval_mode="auto", rerank_provider=provider)
        ranked = [
            _result("first", "第一条有效记忆", 0.8),
            _result("empty", "", 0.7),
            _result("third", "第三条有效记忆", 0.6),
        ]

        results = await engine._maybe_rerank_results("无关查询", ranked, 3)

        self.assertEqual(["third", "first", "empty"], [item.memory.id for item in results])
        self.assertEqual(1, len(provider.calls))
        self.assertEqual(2, provider.calls[0]["top_n"])
        self.assertEqual(2, len(provider.calls[0]["documents"]))
        self.assertTrue(all(document.strip() for document in provider.calls[0]["documents"]))
        self.assertEqual(2, engine.last_path_info["rerank_pool"])
        self.assertEqual(1, engine.last_path_info["rerank_filtered"])

    async def test_low_level_call_rejects_blank_documents_before_provider(self) -> None:
        provider = _RecordingRerankProvider()
        engine = RetrievalEngine(None, None, retrieval_mode="auto", rerank_provider=provider)

        with self.assertRaisesRegex(ValueError, "documents"):
            await engine._call_rerank_provider("有效查询", ["有效候选", " \t"])

        self.assertEqual([], provider.calls)

    async def test_empty_timeout_error_keeps_fallback_and_reports_exception_type(self) -> None:
        class TimeoutProvider:
            async def rerank(self, *, query: str, documents: list[str], top_n: int | None = None):
                raise TimeoutError()

        engine = RetrievalEngine(None, None, retrieval_mode="rerank", rerank_provider=TimeoutProvider(), rerank_timeout_ms=1200)
        ranked = [_result("first", "一条候选记忆", 1.0)]

        results = await engine._maybe_rerank_results("一个问题", ranked, 1)

        self.assertEqual(ranked, results)
        self.assertEqual("fallback_basic", engine.last_path_info["path"])
        self.assertIn("TimeoutError", engine.last_path_info["reason"])
        self.assertEqual("TimeoutError", engine.last_path_info["rerank_error_type"])
        self.assertEqual(1200, engine.last_path_info["rerank_timeout_ms"])


if __name__ == "__main__":
    unittest.main()
