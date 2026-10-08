from __future__ import annotations

import unittest
from typing import Any

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import MemoryRecord, SearchResult, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.time_intent import TimeIntent
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def _memory(memory_id: str, content: str, importance: float = 0.3) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        content=content,
        lifecycle="stable_memory",
        visibility="shareable",
        importance=importance,
    )


class _RoutingCandidateStore:
    """Fake store feeding separate recall channels for routing assertions."""

    def __init__(
        self,
        *,
        fts: list[MemoryRecord] | None = None,
        priority: list[MemoryRecord] | None = None,
        current: list[MemoryRecord] | None = None,
    ):
        self.fts = fts or []
        self.priority = priority or []
        self.current = current or []

    async def related_knowledge_terms(self, *_args, **_kwargs):
        return []

    async def list_candidate_memories(self, **_kwargs):
        return self.priority

    async def list_current_window_candidate_memories(self, **_kwargs):
        return self.current

    async def list_time_window_candidate_memories(self, *_args, **_kwargs):
        return []

    async def list_fts_candidate_memories(self, *_args, **_kwargs):
        return self.fts

    async def list_keyword_candidate_memories(self, *_args, **_kwargs):
        return []

    async def get_memories_by_ids(self, _memory_ids):
        return {}

    async def mark_accessed(self, _memory_ids):
        return None


class _ScriptedRerankProvider:
    model = "test/reranker"

    def __init__(self, results: list[dict[str, Any]]):
        self.results = results
        self.calls: list[dict[str, Any]] = []

    async def rerank(self, **kwargs):
        self.calls.append(kwargs)
        return {"results": self.results}


def _profile(min_hits: int = 1, exact_phrases: list[str] | None = None) -> dict[str, object]:
    return {
        "query_text": "蓝风铃 花语",
        "exact_phrases": exact_phrases or [],
        "min_hits": min_hits,
        "contextual_recall": False,
        "temporal_aggregate": False,
        "open_loop_followup": False,
    }


class RouteAgreementTests(unittest.TestCase):
    def test_bonus_requires_two_independent_families(self) -> None:
        self.assertEqual(0.0, RetrievalEngine._route_agreement_bonus(frozenset({"lexical"})))
        self.assertEqual(
            0.0,
            RetrievalEngine._route_agreement_bonus(RetrievalEngine._route_families({"fts", "keyword"})),
        )
        self.assertAlmostEqual(
            0.08, RetrievalEngine._route_agreement_bonus(frozenset({"lexical", "vector"}))
        )
        self.assertAlmostEqual(
            0.12,
            RetrievalEngine._route_agreement_bonus(frozenset({"lexical", "vector", "time"})),
        )

    def test_fts_and_keyword_collapse_into_one_lexical_family(self) -> None:
        families = RetrievalEngine._route_families({"fts", "keyword"})
        self.assertEqual(frozenset({"lexical"}), families)


class MutableFactHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RetrievalEngine(None, None)
        self.ctx = SessionContext(
            scope="private",
            session_id="qq:FriendMessage:u1",
            user_id="u1",
        )
        self.older = SearchResult(
            memory=MemoryRecord(
                id="older-email",
                content="小王的邮箱是 old@example.com",
                scope="private",
                visibility="private_pair",
                occurred_at="2025-01-01T00:00:00+00:00",
            ),
            score=0.7,
        )
        self.newer = SearchResult(
            memory=MemoryRecord(
                id="newer-email",
                content="小王的邮箱是 new@example.com",
                scope="private",
                visibility="private_pair",
                occurred_at="2026-01-01T00:00:00+00:00",
            ),
            score=0.8,
        )

    def test_historical_recall_keeps_older_mutable_fact(self) -> None:
        results, blocked = self.engine._collapse_mutable_fact_results(
            "小王以前的邮箱是什么？", self.ctx, [self.older, self.newer]
        )

        self.assertEqual(["older-email", "newer-email"], [item.memory.id for item in results])
        self.assertEqual([], blocked)

    def test_explicit_year_recall_keeps_older_mutable_fact(self) -> None:
        results, blocked = self.engine._collapse_mutable_fact_results(
            "小王在 2025 年的邮箱是什么？", self.ctx, [self.older, self.newer]
        )

        self.assertEqual(["older-email", "newer-email"], [item.memory.id for item in results])
        self.assertEqual([], blocked)

    def test_time_bounded_recall_keeps_all_versions_in_the_window(self) -> None:
        results, blocked = self.engine._collapse_mutable_fact_results(
            "邮箱",
            self.ctx,
            [self.older, self.newer],
            time_intent=TimeIntent(active=True, start_at="2025-01-01T00:00:00+00:00", end_at="2026-02-01T00:00:00+00:00"),
        )

        self.assertEqual(["older-email", "newer-email"], [item.memory.id for item in results])
        self.assertEqual([], blocked)

    def test_unqualified_current_query_still_prefers_latest_mutable_fact(self) -> None:
        results, blocked = self.engine._collapse_mutable_fact_results(
            "小王的邮箱", self.ctx, [self.older, self.newer]
        )

        self.assertEqual(["newer-email"], [item.memory.id for item in results])
        self.assertEqual("older-email", blocked[0]["id"])


class ImportanceGatingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RetrievalEngine(None, None)
        self.ctx = SessionContext(scope="private", session_id="qq:FriendMessage:u1", user_id="u1")
        self.terms = ["蓝风铃"]

    def _score(self, memory: MemoryRecord, profile: dict[str, object] | None = None) -> float:
        score, _reason = self.engine._score(memory, self.terms, self.ctx, profile or _profile(), {})
        return score

    def test_weak_evidence_halves_importance_pull(self) -> None:
        low = _memory("low", "用户聊过蓝风铃的养护", importance=0.3)
        high = _memory("high", "用户聊过蓝风铃的养护", importance=1.0)
        self.assertAlmostEqual(0.28 * 0.7, self._score(high) - self._score(low))

    def test_exact_evidence_keeps_full_importance_pull(self) -> None:
        profile = _profile(exact_phrases=["蓝风铃花语"])
        low = _memory("low", "蓝风铃花语象征温柔", importance=0.3)
        high = _memory("high", "蓝风铃花语象征温柔", importance=1.0)
        low_score, _ = self.engine._score(low, self.terms, self.ctx, profile, {})
        high_score, _ = self.engine._score(high, self.terms, self.ctx, profile, {})
        self.assertAlmostEqual(0.55 * 0.7, high_score - low_score)

    def test_contextual_followup_survives_single_term_overlap(self) -> None:
        memory = _memory("context", "之前聊过蓝风铃的养护")
        profile = {
            **_profile(min_hits=2),
            "contextual_recall": True,
            "query_text": "你再想想之前一直提什么蓝风铃花语原因",
        }
        score, reason = self.engine._score(
            memory,
            ["蓝风铃", "花语", "原因", "之前"],
            self.ctx,
            profile,
            {},
        )
        self.assertGreater(score, 0.0)
        self.assertNotIn("keyword_hit_too_weak", reason)


class RouteBonusInScoreTests(unittest.TestCase):
    def test_multi_route_bonus_adds_to_score_and_reason(self) -> None:
        engine = RetrievalEngine(None, None)
        ctx = SessionContext(scope="private", session_id="qq:FriendMessage:u1", user_id="u1")
        memory = _memory("m", "用户聊过蓝风铃的养护", importance=0.5)
        terms = ["蓝风铃"]

        single_score, single_reason = engine._score(
            memory, terms, ctx, _profile(), {}, route_families=frozenset({"lexical"})
        )
        dual_score, dual_reason = engine._score(
            memory, terms, ctx, _profile(), {}, route_families=frozenset({"lexical", "vector"})
        )

        self.assertAlmostEqual(0.08, dual_score - single_score)
        self.assertIn("routes=lexical+vector", dual_reason)
        self.assertIn("route_bonus=0.08", dual_reason)
        self.assertIn("routes=lexical", single_reason)
        self.assertIn("route_bonus=0.00", single_reason)


class RoutePlumbingTests(unittest.IsolatedAsyncioTestCase):
    async def test_rank_candidates_reports_route_families_per_memory(self) -> None:
        fts_memory = _memory("fts_hit", "用户聊过蓝风铃和它的花语")
        priority_memory = _memory("priority_only", "蓝风铃相关的花语旧记录", importance=0.9)
        store = _RoutingCandidateStore(fts=[fts_memory], priority=[priority_memory])
        engine = RetrievalEngine(
            store,
            VisibilityPolicy(enable_acl_rules=False),
            knowledge_graph_enabled=False,
        )

        results, blocked = await engine._rank_candidates(
            "蓝风铃 花语",
            SessionContext(scope="private", session_id="qq:FriendMessage:u1", user_id="u1"),
        )

        reasons = {item.memory.id: item.reason for item in results}
        self.assertIn("fts_hit", reasons)
        self.assertIn("routes=lexical;route_bonus=0.00", reasons["fts_hit"])
        self.assertIn("priority_only", reasons)
        self.assertIn("routes=-;route_bonus=0.00", reasons["priority_only"])
        self.assertEqual([], blocked)


class RerankConvexFusionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_leader_stays_first_and_anchor_floor_keeps_anchor_in_window(self) -> None:
        anchor = SearchResult(memory=_memory("anchor", "用户最喜欢蓝风铃，聊过它的花语"), score=0.72)
        leader = SearchResult(memory=_memory("leader", "关于花店的讨论"), score=0.80)
        other = SearchResult(memory=_memory("other", "今天天气不错"), score=0.70)
        provider = _ScriptedRerankProvider(
            [
                {"index": 1, "relevance_score": 0.9},
                {"index": 2, "relevance_score": 0.85},
                {"index": 0, "relevance_score": 0.1},
            ]
        )
        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="auto",
            rerank_provider=provider,
        )

        results = await engine._maybe_rerank_results("蓝风铃 花语", [anchor, leader, other], 2)

        self.assertEqual(
            ["leader", "anchor", "other"],
            [item.memory.id for item in results],
        )
        self.assertTrue(all(item.score <= 1.0 for item in results))
        self.assertIn("combined=", results[0].reason)
        self.assertEqual("rerank", engine.last_path_info["path"])
        self.assertEqual(1, engine.last_path_info["anchor_floor_applied"])
        self.assertEqual(1, engine.last_path_info["lexical_anchors"])

    async def test_anchor_already_in_window_does_not_invoke_floor(self) -> None:
        anchor = SearchResult(memory=_memory("anchor", "用户最喜欢蓝风铃，聊过它的花语"), score=0.9)
        other = SearchResult(memory=_memory("other", "今天天气不错"), score=0.6)
        provider = _ScriptedRerankProvider(
            [
                {"index": 0, "relevance_score": 0.9},
                {"index": 1, "relevance_score": 0.2},
            ]
        )
        engine = RetrievalEngine(
            None,
            None,
            retrieval_mode="auto",
            rerank_provider=provider,
        )

        results = await engine._maybe_rerank_results("蓝风铃 花语", [anchor, other], 2)

        self.assertEqual(["anchor", "other"], [item.memory.id for item in results])
        self.assertEqual(0, engine.last_path_info["anchor_floor_applied"])


if __name__ == "__main__":
    unittest.main()
