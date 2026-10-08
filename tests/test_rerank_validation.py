from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import MemoryRecord, SearchResult
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
