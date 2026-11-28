"""Regression tests for honoring configured rerank and embedding timeouts."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import retrieval as retrieval_mod
from astrbot_plugin_memory_companion.core.latency import (
    DEFAULT_MODEL_CALL_TIMEOUT_MS,
    MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS,
    MAX_MODEL_CALL_TIMEOUT_MS,
    await_with_timeout,
    bounded_model_call_timeout_ms,
)
from astrbot_plugin_memory_companion.core.models import (
    MemoryRecord,
    SearchResult,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


def _result(memory_id: str, content: str, score: float) -> SearchResult:
    return SearchResult(memory=MemoryRecord(id=memory_id, content=content), score=score)


class RerankTimeoutConfigTests(unittest.IsolatedAsyncioTestCase):
    def test_bounded_model_call_timeout_honors_explicit_config_up_to_cap(self) -> None:
        self.assertEqual(2000, MAX_MODEL_CALL_TIMEOUT_MS)
        self.assertEqual(2000, DEFAULT_MODEL_CALL_TIMEOUT_MS)
        self.assertEqual(10000, MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS)

        for raw, expected in (
            (500, 500),
            (2000, 2000),
            (5000, 5000),
            ("5000", 5000),
            (9000, 9000),
            (10000, 10000),
            (10001, MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS),
            (30000, MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(expected, bounded_model_call_timeout_ms(raw))

        for invalid in (0, -1, -5000, None, "", "bad", True, False, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                self.assertEqual(
                    DEFAULT_MODEL_CALL_TIMEOUT_MS,
                    bounded_model_call_timeout_ms(invalid),
                )

    def test_bounded_model_call_timeout_respects_custom_cap(self) -> None:
        self.assertEqual(5000, bounded_model_call_timeout_ms(8000, max_timeout_ms=5000))
        self.assertEqual(1500, bounded_model_call_timeout_ms(0, max_timeout_ms=1500))
        self.assertEqual(
            MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS,
            bounded_model_call_timeout_ms(50000, max_timeout_ms=50000),
        )
        self.assertEqual(5000, bounded_model_call_timeout_ms(5000, max_timeout_ms=True))
        self.assertEqual(5000, bounded_model_call_timeout_ms(5000, max_timeout_ms=0))

    def test_schema_bounds_align_with_runtime_timeout_cap(self) -> None:
        schema = json.loads((Path(ROOT) / "_conf_schema.json").read_text(encoding="utf-8"))
        advanced = schema["retrieval_advanced"]["items"]
        for key in ("embedding_timeout_ms", "rerank_timeout_ms"):
            with self.subTest(key=key):
                item = advanced[key]
                self.assertEqual(DEFAULT_MODEL_CALL_TIMEOUT_MS, item["default"])
                self.assertEqual(MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS, item["max"])
                self.assertEqual(MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS, item["slider"]["max"])

    async def test_service_retrieval_engine_honors_retrieval_advanced_timeout_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryCompanionService(
                context=None,
                config={
                    "retrieval": {"mode": "basic", "embedding_enabled": False},
                    "retrieval_advanced": {
                        "rerank_timeout_ms": 5000,
                        "embedding_timeout_ms": 4500,
                    },
                },
                plugin_root=Path(ROOT),
                data_dir=Path(tmp),
            )
            try:
                ctx = SessionContext(
                    session_id="qq:FriendMessage:u1",
                    scope="private",
                    platform="qq",
                    user_id="u1",
                    bot_id="b1",
                )
                engine = await service._retrieval_engine(ctx)
                self.assertEqual(5000, engine.rerank_timeout_ms)
                self.assertEqual(4500, engine.embedding_timeout_ms)
                self.assertEqual(4500, service._embedding_timeout_ms())

                # Unset values still default safely to 2000 ms.
                service.config.raw["retrieval_advanced"] = {}
                default_engine = await service._retrieval_engine(ctx)
                self.assertEqual(DEFAULT_MODEL_CALL_TIMEOUT_MS, default_engine.rerank_timeout_ms)
                self.assertEqual(DEFAULT_MODEL_CALL_TIMEOUT_MS, default_engine.embedding_timeout_ms)

                # Oversized values clamp safely at the configured upper cap.
                service.config.raw["retrieval_advanced"] = {
                    "rerank_timeout_ms": 60000,
                    "embedding_timeout_ms": 60000,
                }
                capped_engine = await service._retrieval_engine(ctx)
                self.assertEqual(MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS, capped_engine.rerank_timeout_ms)
                self.assertEqual(MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS, capped_engine.embedding_timeout_ms)
            finally:
                service.close()

    async def test_rerank_call_passes_configured_5000ms_timeout_without_clamping_to_2000ms(self) -> None:
        class FastRerankProvider:
            async def rerank(
                self,
                *,
                query: str,
                documents: list[str],
                top_n: int | None = None,
            ) -> dict[str, Any]:
                return {
                    "results": [
                        {"index": 1, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.4},
                    ]
                }

        observed_timeouts: list[float] = []

        async def recording_wait(awaitable: Any, timeout_seconds: float) -> Any:
            observed_timeouts.append(timeout_seconds)
            return await await_with_timeout(awaitable, timeout_seconds)

        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=FastRerankProvider(),
            rerank_timeout_ms=5000,
        )
        ranked = [
            _result("m1", "普通记录", 0.9),
            _result("m2", "更匹配的记录", 0.6),
        ]

        with patch.object(retrieval_mod, "await_with_timeout", side_effect=recording_wait):
            results = await engine._maybe_rerank_results("匹配记录", ranked, 2)

        self.assertEqual([5.0], observed_timeouts)
        self.assertEqual(["m2", "m1"], [item.memory.id for item in results])
        self.assertEqual("rerank", engine.last_path_info["path"])
        self.assertEqual(5000, engine.rerank_timeout_ms)

    async def test_rerank_with_5000ms_timeout_allows_multi_doc_batch_over_2s(self) -> None:
        class RealisticBatchRerankProvider:
            async def rerank(
                self,
                *,
                query: str,
                documents: list[str],
                top_n: int | None = None,
            ) -> dict[str, Any]:
                await asyncio.sleep(2.15)
                return {
                    "results": [
                        {"index": 1, "relevance_score": 0.92},
                        {"index": 0, "relevance_score": 0.35},
                    ]
                }

        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=RealisticBatchRerankProvider(),
            rerank_timeout_ms=5000,
        )
        ranked = [
            _result("first", "候选记忆一", 0.8),
            _result("second", "候选记忆二", 0.7),
        ]

        results = await engine._maybe_rerank_results("查询", ranked, 2)

        self.assertEqual(["second", "first"], [item.memory.id for item in results])
        self.assertEqual("rerank", engine.last_path_info["path"])
        self.assertEqual(5000, engine.rerank_timeout_ms)

    async def test_rerank_genuinely_exceeding_configured_timeout_falls_back_cleanly(self) -> None:
        class StalledRerankProvider:
            async def rerank(
                self,
                *,
                query: str,
                documents: list[str],
                top_n: int | None = None,
            ) -> dict[str, Any]:
                await asyncio.sleep(1.0)
                return {"results": [{"index": 0, "relevance_score": 0.9}]}

        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=StalledRerankProvider(),
            rerank_timeout_ms=120,
        )
        ranked = [
            _result("m1", "候选一", 0.9),
            _result("m2", "候选二", 0.4),
        ]

        results = await engine._maybe_rerank_results("查询", ranked, 2)

        self.assertEqual(["m1", "m2"], [item.memory.id for item in results])
        self.assertEqual("fallback_basic", engine.last_path_info["path"])
        self.assertEqual("TimeoutError", engine.last_path_info["rerank_error_type"])
        self.assertEqual(120, engine.last_path_info["rerank_timeout_ms"])

    async def test_embedding_call_passes_configured_5000ms_timeout_without_clamping(self) -> None:
        class FastEmbeddingProvider:
            async def get_embedding(self, _text: str) -> list[float]:
                return [0.5, 0.5]

        observed_timeouts: list[float] = []

        async def recording_wait(awaitable: Any, timeout_seconds: float) -> Any:
            observed_timeouts.append(timeout_seconds)
            return await await_with_timeout(awaitable, timeout_seconds)

        engine = RetrievalEngine(
            None,
            None,
            embedding_provider=FastEmbeddingProvider(),
            embedding_enabled=True,
            embedding_timeout_ms=5000,
        )

        with patch.object(retrieval_mod, "await_with_timeout", side_effect=recording_wait):
            vector = await engine._call_embedding_provider("查询语句")

        self.assertEqual([0.5, 0.5], vector)
        self.assertEqual(1, len(observed_timeouts))
        self.assertGreater(observed_timeouts[0], 4.5)
        self.assertLessEqual(observed_timeouts[0], 5.0)
        self.assertEqual(5000, engine.embedding_timeout_ms)


if __name__ == "__main__":
    unittest.main()
