from __future__ import annotations

import asyncio
import math
import re
import sys
import tempfile
import unittest
import hashlib
from pathlib import Path


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import (
    MemoryRecord,
    SearchResult,
    SessionContext,
    clean_text,
    memory_embedding_text,
    memory_embedding_text_hash,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def _memory(memory_id: str, content: str = "anchor token") -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        content=content,
        lifecycle="stable_memory",
        visibility="shareable",
        importance=0.8,
    )


class _CandidateStore:
    def __init__(
        self,
        *,
        fts: list[MemoryRecord] | None = None,
        current: list[MemoryRecord] | None = None,
    ):
        self.fts = fts or []
        self.current = current or []
        self.keyword_calls = 0

    async def related_knowledge_terms(self, *_args, **_kwargs):
        return []

    async def list_candidate_memories(self, **_kwargs):
        return []

    async def list_current_window_candidate_memories(self, **_kwargs):
        return self.current

    async def list_time_window_candidate_memories(self, *_args, **_kwargs):
        return []

    async def list_fts_candidate_memories(self, *_args, **_kwargs):
        return self.fts

    async def list_keyword_candidate_memories(self, *_args, **_kwargs):
        self.keyword_calls += 1
        return []

    async def get_memories_by_ids(self, _memory_ids):
        return {}

    async def mark_accessed(self, _memory_ids):
        return None


class _EmptyRerankProvider:
    model = "BAAI/bge-reranker-v2-m3"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def rerank(self, **kwargs):
        self.calls.append(kwargs)
        return []


def _legacy_mmr(engine: RetrievalEngine, ranked: list[SearchResult], selection_limit: int) -> list[SearchResult]:
    """Reference copy of the pre-optimization MMR algorithm (HEAD baseline)."""
    if len(ranked) < 2 or selection_limit <= 1:
        return ranked
    head_size = min(len(ranked), max(int(selection_limit or 1) * 4, 16))
    pool = list(ranked[:head_size])
    scores = [float(item.score) for item in pool]
    minimum = min(scores)
    maximum = max(scores)

    def relevance(item: SearchResult) -> float:
        if maximum <= minimum:
            return 1.0
        return (float(item.score) - minimum) / (maximum - minimum)

    def features(item: SearchResult) -> set[str]:
        memory = item.memory
        text = re.sub(r"\s+", "", engine._haystack(memory))
        cjk = {text[index : index + 2] for index in range(max(0, len(text) - 1)) if text[index : index + 2]}
        latin = set(re.findall(r"[a-z0-9_]{2,}", text))
        tags = {f"tag:{clean_text(tag, 40).lower()}" for tag in (memory.tags or []) if clean_text(tag, 40)}
        source = clean_text(memory.source_plugin, 60).lower()
        return set(sorted(cjk)[:180]) | latin | tags | ({f"source:{source}"} if source else set())

    feature_map = {id(item): features(item) for item in pool}

    def similarity(left: SearchResult, right: SearchResult) -> float:
        left_features = feature_map[id(left)]
        right_features = feature_map[id(right)]
        union = left_features | right_features
        return (len(left_features & right_features) / len(union)) if union else 0.0

    selected: list[SearchResult] = [pool.pop(0)]
    target = min(len(ranked), max(1, int(selection_limit or 1)))
    while pool and len(selected) < target:
        best_index = 0
        best_value = -math.inf
        for index, item in enumerate(pool):
            redundancy = max(similarity(item, chosen) for chosen in selected)
            # R7：去冗余权重已可配，参考实现必须跟着引擎的取值走，否则这条
            # 「优化不改变算法」的对照测试会锁死旧常数 0.16。
            value = (0.84 * relevance(item)) - (engine.mmr_redundancy_weight * redundancy)
            if value > best_value:
                best_value = value
                best_index = index
        selected.append(pool.pop(best_index))
    selected_ids = {id(item) for item in selected}
    tail = [item for item in ranked if id(item) not in selected_ids]
    return [*selected, *tail]


class RetrievalPerformanceTests(unittest.IsolatedAsyncioTestCase):
    def test_embedding_document_keeps_routine_check_notes_in_sync(self) -> None:
        record = _memory("routine-note", "检查午间状态")
        record.metadata = {
            "canonical_summary": "完成午间例行检查",
            "routine_check_notes": ["已确认用户午饭后状态正常"],
            "topics": ["日常"],
        }
        engine = RetrievalEngine(
            _CandidateStore(),
            VisibilityPolicy(enable_acl_rules=False),
            embedding_max_text_chars=1200,
        )

        self.assertEqual(
            memory_embedding_text(record, max_chars=1200),
            engine._embedding_document_text(record),
        )
        self.assertEqual(
            engine._embedding_text_hash(record),
            hashlib.sha1(
                memory_embedding_text(record, max_chars=1200).encode("utf-8")
            ).hexdigest(),
        )

    async def test_rerank_filters_empty_documents_and_reports_safe_request_shape(self) -> None:
        provider = _EmptyRerankProvider()
        engine = RetrievalEngine(
            _CandidateStore(),
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="rerank",
            rerank_provider=provider,
            rerank_provider_id="reranker",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
        )
        ranked = [
            SearchResult(memory=_memory("empty", ""), score=2.0),
            SearchResult(memory=_memory("valid", "有效候选文本"), score=1.0),
        ]

        results = await engine._maybe_rerank_results("有效查询", ranked, 2)

        self.assertEqual(1, len(provider.calls))
        self.assertEqual(1, len(provider.calls[0]["documents"]))
        self.assertEqual(ranked, results)
        self.assertEqual("rerank_empty_response", engine.last_path_info["reason"])
        self.assertGreater(engine.last_path_info["rerank_query_chars"], 0)
        self.assertEqual(1, engine.last_path_info["rerank_document_count"])
        self.assertGreater(engine.last_path_info["rerank_document_min_chars"], 0)
        self.assertGreater(engine.last_path_info["rerank_model_chars"], 0)
    async def test_current_window_candidates_are_merged_even_without_global_hits(self) -> None:
        current = _memory("current-1", "current window anchor")
        store = _CandidateStore(current=[current])
        engine = RetrievalEngine(
            store,
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
        )
        ctx = SessionContext(session_id="qq:FriendMessage:u1", scope="private", user_id="u1")

        results, _blocked = await engine._rank_candidates("current window anchor", ctx)
        self.assertIn("current-1", {item.memory.id for item in results})
        self.assertEqual(1, engine._rank_path_info["current_window_candidates"])

    async def test_wide_keyword_fallback_is_skipped_when_fts_is_sufficient(self) -> None:
        fts = [_memory(f"fts-{index}") for index in range(80)]
        store = _CandidateStore(fts=fts)
        engine = RetrievalEngine(
            store,
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
            keyword_fallback_min_fts_candidates=80,
        )
        ctx = SessionContext(session_id="s1", scope="private", user_id="u1")

        await engine._rank_candidates("anchor token", ctx)
        self.assertEqual(0, store.keyword_calls)
        self.assertFalse(engine._rank_path_info["keyword_fallback_used"])

    async def test_common_preference_equivalence_is_recalled_without_embedding(self) -> None:
        current = _memory("preference-1", "用户喝拿铁时不要加糖。")
        store = _CandidateStore(current=[current])
        engine = RetrievalEngine(
            store,
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
        )
        ctx = SessionContext(session_id="s1", scope="private", user_id="u1")

        results, _blocked = await engine._rank_candidates("无糖拿铁", ctx)

        self.assertIn("preference-1", {item.memory.id for item in results})
        self.assertIn("不要加糖", engine._terms("无糖拿铁"))

    async def test_vector_candidate_cache_is_copy_safe_and_revisioned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            store.initialize()
            try:
                record = _memory("vector-1", "vector content v1")
                await store.insert_memory(record)
                await store.upsert_memory_embedding(
                    memory_id=record.id,
                    provider_id="embedder",
                    text_hash="hash-1",
                    vector=[1.0, 0.0],
                )

                first = await store.list_embedding_candidate_rows(provider_id="embedder")
                first[0][1][0] = 99.0
                second = await store.list_embedding_candidate_rows(provider_id="embedder")
                self.assertEqual([1.0, 0.0], second[0][1])

                await store.update_memory_payload(record.id, content="vector content v2")
                third = await store.list_embedding_candidate_rows(provider_id="embedder")
                self.assertEqual("vector content v2", third[0][0].content)
                stale = await store.list_memories_missing_embeddings(
                    provider_id="embedder",
                    limit=1,
                )
                self.assertEqual([record.id], [item.id for item in stale])
                scanned, next_offset, exhausted = await store.scan_memories_missing_embeddings(
                    provider_id="embedder",
                    limit=1,
                    offset=0,
                )
                self.assertEqual([record.id], [item.id for item in scanned])
                self.assertGreaterEqual(next_offset, 1)
                self.assertTrue(exhausted)
                await store.upsert_memory_embedding(
                    memory_id=record.id,
                    provider_id="embedder",
                    text_hash=memory_embedding_text_hash(
                        third[0][0],
                        max_chars=1200,
                    ),
                    vector=[1.0, 0.0],
                )
                self.assertEqual(
                    [],
                    await store.list_memories_missing_embeddings(
                        provider_id="embedder",
                        limit=1,
                    ),
                )
            finally:
                store.close()

    def test_mmr_optimization_matches_legacy_selection_and_order(self) -> None:
        engine = RetrievalEngine(
            _CandidateStore(),
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
        )
        ranked = [
            SearchResult(memory=_memory(f"m-{index}", content), score=score)
            for index, (content, score) in enumerate(
                [
                    ("蓝风铃在午夜盛开", 0.95),
                    ("蓝风铃的香气很淡", 0.90),
                    ("蓝风铃的香气很淡", 0.85),
                    ("用户喜欢喝拿铁不加糖", 0.60),
                    ("latte no sugar please", 0.55),
                    ("完全不同的长句用于测试特征", 0.30),
                ]
            )
        ]
        for item in ranked:
            item.memory.tags = ["flower"] if "蓝风铃" in item.memory.content else []
            item.memory.source_plugin = "memory_companion"

        for limit in (2, 3, 4, 6):
            expected = _legacy_mmr(engine, list(ranked), limit)
            actual = engine._mmr_diversify(list(ranked), limit)
            self.assertEqual(
                [item.memory.id for item in expected],
                [item.memory.id for item in actual],
                f"MMR order diverged at limit={limit}",
            )
            self.assertEqual(
                {item.memory.id for item in expected},
                {item.memory.id for item in actual},
                f"MMR membership diverged at limit={limit}",
            )

    def test_mmr_optimization_preserves_long_memory_bigram_cap(self) -> None:
        engine = RetrievalEngine(
            _CandidateStore(),
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
        )
        long_text = "甲" * 300 + "乙" * 300 + "丙"
        ranked = [
            SearchResult(memory=_memory("long-1", long_text), score=1.0),
            SearchResult(memory=_memory("long-2", "丙丙丙丙丙"), score=0.9),
        ]
        self.assertEqual(
            [item.memory.id for item in _legacy_mmr(engine, list(ranked), 2)],
            [item.memory.id for item in engine._mmr_diversify(list(ranked), 2)],
        )

    async def test_mmr_offload_does_not_mutate_input_and_stays_responsive(self) -> None:
        import time as _time

        engine = RetrievalEngine(
            _CandidateStore(),
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
        )
        ranked = [
            SearchResult(memory=_memory("a", "第一段记忆"), score=1.0),
            SearchResult(memory=_memory("b", "第二段记忆"), score=0.5),
        ]
        original = [id(item) for item in ranked]

        def slow_mmr(candidates, limit):
            _time.sleep(0.05)
            return list(candidates)

        engine._mmr_diversify = slow_mmr

        ticks: list[int] = []

        async def heartbeat() -> None:
            for _ in range(40):
                ticks.append(1)
                await asyncio.sleep(0.005)

        task = asyncio.create_task(heartbeat())
        result = await engine._mmr_diversify_async(ranked, 2)
        await task

        self.assertEqual(original, [id(item) for item in ranked])
        self.assertEqual([item.memory.id for item in ranked], [item.memory.id for item in result])
        self.assertGreaterEqual(len(ticks), 5)

    async def test_rank_candidates_is_deterministic_across_offloaded_runs(self) -> None:
        current = _memory("stable-1", "蓝风铃的香气")
        store = _CandidateStore(current=[current])
        engine = RetrievalEngine(
            store,
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
        )
        ctx = SessionContext(session_id="s1", scope="private", user_id="u1")

        first, first_blocked = await engine._rank_candidates("蓝风铃", ctx)
        second, second_blocked = await engine._rank_candidates("蓝风铃", ctx)

        self.assertEqual(
            [(item.memory.id, item.score) for item in first],
            [(item.memory.id, item.score) for item in second],
        )
        self.assertEqual(first_blocked, second_blocked)
        self.assertGreaterEqual(engine._rank_path_info["candidate_count"], 1)
        self.assertTrue(engine._rank_path_info["ranking_offloaded"])


if __name__ == "__main__":
    unittest.main()
