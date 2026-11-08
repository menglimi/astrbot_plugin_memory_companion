"""R1/R2/R3/R5/R6/R7/R10/R12/R13/S6/S7 回归测试（retrieval-fixer）。

每条用例都断言可观察的真实行为，不写「只跑不报错」的空测试：
- R1  真 BM25：文档长度归一化 + ASCII 词边界计数
- R2  无查询词不再用 importance 硬排兜底，直接返回空召回
- R3  停用词表不再包含评测句碎片（得糖/端吗/骨吗/的胖/次颜）
- R5  人工词法锚定默认关闭，显式开启才改写 top-k
- R6  scope 偏置可配，默认不再 +0.25 硬偏置
- R7  MMR 去冗余权重默认 0.35
- R10 注入预算按相关度优先分配，而不是槽位顺序先到先得
- R12 注入正文不写检索模式/关键词/心理能量等内部遥测
- R13 注入预算统一到常量族
- S6  importance 词表外置 + 未命中词表给中性分 + explain 可解释
- S7  核心记忆不再把 priority 同时写进 salience（避免生命周期双计）
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.context_orchestrator import RetrievalIntent
from astrbot_plugin_memory_companion.core.importance import ImportanceEvaluator
from astrbot_plugin_memory_companion.core.injection import (
    DEFAULT_CORE_MEMORY_CHARS,
    DEFAULT_INJECTION_CHARS,
    DEFAULT_MAX_ITEM_CHARS,
    INJECTION_BUDGETS,
    MAX_INJECTION_CHARS,
    MIN_INJECTION_CHARS,
    SHORT_REPLY_INJECTION_CHARS,
    TEMPORAL_INJECTION_CHARS,
    InjectionComposer,
)
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SearchResult,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def _memory(
    memory_id: str,
    content: str,
    *,
    importance: float = 0.3,
    memory_type: str = "observation",
    metadata: dict[str, Any] | None = None,
    session_id: str = "",
    subject_id: str = "",
    scope: str = "private",
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        content=content,
        memory_type=memory_type,
        lifecycle="stable_memory",
        visibility="shareable",
        importance=importance,
        metadata=metadata or {},
        session_id=session_id,
        scope=scope,
        subject=EntityRef(kind="user", id=subject_id) if subject_id else EntityRef(),
    )


def _ctx(session_id: str = "s1", user_id: str = "u1") -> SessionContext:
    return SessionContext(scope="private", session_id=session_id, user_id=user_id)


class _RoutingCandidateStore:
    """Fake store feeding separate recall channels (same shape as other tests)."""

    def __init__(self, *, fts=None, priority=None, current=None):
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

    async def list_acl_rules(self, enabled_only=True):
        return []

    async def list_acl_policies(self):
        return []

    async def mark_accessed(self, _memory_ids):
        return None


class Bm25ScoringTests(unittest.TestCase):
    """R1：真 BM25（长度归一化 + 词边界），不再是 haystack.count(term)。"""

    def setUp(self) -> None:
        self.engine = RetrievalEngine(None, None)
        self.ctx = _ctx()

    def test_ascii_terms_use_word_boundaries(self) -> None:
        self.assertEqual(2, self.engine._term_frequency("cat category cat.", "cat"))
        self.assertEqual(0, self.engine._term_frequency("category scatter", "cat"))
        self.assertEqual(2, self.engine._term_frequency("天气不错天气", "天气"))

    def test_longer_document_scores_lower_for_same_term(self) -> None:
        short = _memory("short", "天气不错")
        long = _memory("long", "天气" + "很长的填充内容" * 60)
        stats, average = self.engine._term_document_stats([short, long], ["天气"])
        profile = self.engine._query_profile("天气", ["天气"])
        short_score, _ = self.engine._score(
            short, ["天气"], self.ctx, profile, stats, average_doc_len=average
        )
        long_score, _ = self.engine._score(
            long, ["天气"], self.ctx, profile, stats, average_doc_len=average
        )
        self.assertGreater(short_score, long_score)

    def test_b_zero_disables_length_normalisation(self) -> None:
        plain = RetrievalEngine(None, None, bm25_b=0.0)
        short = _memory("short", "天气不错")
        long = _memory("long", "天气" + "很长的填充内容" * 60)
        stats, average = plain._term_document_stats([short, long], ["天气"])
        profile = plain._query_profile("天气", ["天气"])
        short_score, _ = plain._score(
            short, ["天气"], self.ctx, profile, stats, average_doc_len=average
        )
        long_score, _ = plain._score(
            long, ["天气"], self.ctx, profile, stats, average_doc_len=average
        )
        self.assertAlmostEqual(short_score, long_score, places=6)


class NoQueryTermsTests(unittest.IsolatedAsyncioTestCase):
    """R2：没有查询词时返回空召回，而不是用 importance 硬排。"""

    def test_score_without_terms_is_zero(self) -> None:
        engine = RetrievalEngine(None, None)
        profile = engine._query_profile("", [])
        score, reason = engine._score(_memory("hot", "随便写点", importance=1.0), [], _ctx(), profile, {})
        self.assertEqual(0.0, score)
        self.assertEqual("no_query_terms", reason)

    async def test_search_without_query_returns_nothing(self) -> None:
        store = _RoutingCandidateStore(priority=[_memory("hot", "随便写点", importance=1.0)])
        engine = RetrievalEngine(store, VisibilityPolicy())
        results, blocked = await engine.search_with_diagnostics("", _ctx(), 6)
        self.assertEqual([], results)
        self.assertIn("no_query_terms", {item.get("reason", "") for item in blocked})


class QueryScaffoldTermTests(unittest.TestCase):
    """R3：停用词表只留通用中文停用词，不再含评测句碎片。"""

    def setUp(self) -> None:
        self.engine = RetrievalEngine(None, None)

    def test_evaluation_fragments_are_not_scaffold_terms(self) -> None:
        for fragment in ("得糖", "端吗", "骨吗", "的胖", "次颜"):
            self.assertFalse(self.engine._is_query_scaffold_term(fragment), fragment)

    def test_common_scaffold_words_still_filtered(self) -> None:
        for word in ("什么", "之前", "上次", "记得"):
            self.assertTrue(self.engine._is_query_scaffold_term(word), word)


class AnchorFloorTests(unittest.TestCase):
    """R5：人工词法锚定默认关闭，显式开启才生效。"""

    def _items(self) -> tuple[list[SearchResult], list[SearchResult]]:
        merged = [
            SearchResult(memory=_memory("m1", "一"), score=0.9),
            SearchResult(memory=_memory("m2", "二"), score=0.8),
            SearchResult(memory=_memory("m3", "三"), score=0.3),
        ]
        anchors = [SearchResult(memory=_memory("anchor", "锚点"), score=0.5)]
        return merged, anchors

    def test_anchor_floor_disabled_by_default(self) -> None:
        engine = RetrievalEngine(None, None)
        self.assertFalse(engine.anchor_floor_enabled)
        merged, anchors = self._items()
        before = [item.memory.id for item in merged]
        self.assertEqual(0, engine._apply_anchor_floor(merged, anchors, [], 2))
        self.assertEqual(before, [item.memory.id for item in merged])

    def test_anchor_floor_applies_when_enabled(self) -> None:
        engine = RetrievalEngine(None, None, anchor_floor_enabled=True)
        merged, anchors = self._items()
        self.assertEqual(1, engine._apply_anchor_floor(merged, anchors, [], 2))
        self.assertIn("anchor", [item.memory.id for item in merged[:2]])


class ScopeBonusTests(unittest.TestCase):
    """R6：scope 偏置可配，默认缩放后不再硬偏置 0.25。"""

    def _scores(self, engine: RetrievalEngine) -> tuple[float, float]:
        ctx = _ctx()
        same = _memory("same", "我们一起去看画展", session_id="s1", subject_id="u1")
        other = _memory("other", "我们一起去看画展", session_id="s9", subject_id="u9")
        stats, average = engine._term_document_stats([same, other], ["画展"])
        profile = engine._query_profile("画展", ["画展"])
        same_score, _ = engine._score(
            same, ["画展"], ctx, profile, stats, average_doc_len=average
        )
        other_score, _ = engine._score(
            other, ["画展"], ctx, profile, stats, average_doc_len=average
        )
        return same_score, other_score

    def test_default_scale_keeps_bias_small(self) -> None:
        engine = RetrievalEngine(None, None)
        self.assertAlmostEqual(0.2, engine.scope_bonus_scale, places=6)
        same_score, other_score = self._scores(engine)
        diff = same_score - other_score
        self.assertGreater(diff, 0.0)
        self.assertLess(diff, 0.2)

    def test_zero_scale_removes_bias_entirely(self) -> None:
        engine = RetrievalEngine(None, None, scope_bonus_scale=0.0)
        same_score, other_score = self._scores(engine)
        self.assertAlmostEqual(same_score, other_score, places=6)


class MmrDiversityTests(unittest.TestCase):
    """R7：MMR 去冗余权重默认 0.35，高冗余条目不再挤进 top_k。"""

    def test_redundant_item_is_not_selected_twice(self) -> None:
        engine = RetrievalEngine(None, None)
        self.assertAlmostEqual(0.35, engine.mmr_redundancy_weight, places=6)
        items = [
            SearchResult(memory=_memory("a", "蓝风铃的花语是温柔的爱"), score=0.9),
            SearchResult(memory=_memory("b", "蓝风铃的花语是温柔的爱"), score=0.89),
            SearchResult(memory=_memory("c", "小王下周要交画稿"), score=0.7),
            SearchResult(memory=_memory("d", "今天下雨"), score=0.2),
        ]
        selected = engine._mmr_diversify(items, 2)
        # _mmr_diversify 先给出选中的前 selection_limit 条，尾部按原顺序补齐；
        # 断言只看真正进入 top_k 的部分：高冗余的 b 不得占第二个位置。
        self.assertEqual(["a", "c"], [item.memory.id for item in selected[:2]])


class DedupeOrderTests(unittest.TestCase):
    """R4：去重保留最高分条目的原始位置，不把它挪到队尾被 top_k 截掉。"""

    def test_higher_score_duplicate_keeps_its_slot(self) -> None:
        engine = RetrievalEngine(None, None)
        ranked = [
            SearchResult(memory=_memory("low", "蓝风铃的花语是温柔的爱"), score=0.5),
            SearchResult(memory=_memory("high", "蓝风铃 的花语是温柔的爱"), score=0.9),
            SearchResult(memory=_memory("other", "今天下雨"), score=0.7),
        ]
        deduped = engine._dedupe_by_content(ranked, 0.9)
        self.assertEqual(["high", "other"], [item.memory.id for item in deduped])
        self.assertEqual(0.9, deduped[0].score)
        self.assertEqual("high", deduped[0].memory.id)


class InjectionBudgetPriorityTests(unittest.TestCase):
    """R10：预算按相关度优先分配，低分槽位不能先占预算挤掉高分条目。"""

    def test_higher_ranked_item_wins_tight_budget(self) -> None:
        composer = InjectionComposer()
        low = SearchResult(
            memory=_memory(
                "low",
                "未完成的约定" * 6,
                memory_type="open_loop",
                metadata={"open_loop_weight": 0.9},
                importance=0.1,
            ),
            score=0.9,
        )
        high = SearchResult(
            memory=_memory("high", "用户叫小王", memory_type="user_profile", importance=0.9),
            score=0.95,
        )
        included: list[str] = []
        lines = composer._build_grouped_memory_lines(
            [low, high],
            slot_sections=[("open_loop", [low]), ("memory", [high])],
            compact=False,
            base_lines=["base"],
            closing_lines=["close"],
            inner_limit=240,
            included_memory_ids=included,
        )
        self.assertEqual(["high"], included)
        text = "\n".join(lines)
        self.assertIn("用户叫小王", text)
        self.assertNotIn("未完成的约定", text)

    def test_low_item_still_fits_alone(self) -> None:
        composer = InjectionComposer()
        low = SearchResult(
            memory=_memory(
                "low",
                "未完成的约定" * 6,
                memory_type="open_loop",
                metadata={"open_loop_weight": 0.9},
                importance=0.1,
            ),
            score=0.9,
        )
        included: list[str] = []
        composer._build_grouped_memory_lines(
            [low],
            slot_sections=[("open_loop", [low])],
            compact=False,
            base_lines=["base"],
            closing_lines=["close"],
            inner_limit=240,
            included_memory_ids=included,
        )
        self.assertEqual(["low"], included)


class InjectionTelemetryTests(unittest.TestCase):
    """R12：注入正文不写检索模式/关键词/心理能量等内部遥测。"""

    def _intent(self) -> RetrievalIntent:
        return RetrievalIntent(
            query="你还记得我说得糖放哪了吗",
            topic="找东西",
            keywords=["得糖"],
            query_mode="topic_shift",
            companion_bot_energy=42.0,
        )

    def test_injection_text_hides_internal_telemetry(self) -> None:
        text = self._intent().format_for_injection()
        self.assertIn("当前话题：找东西", text)
        for banned in ("检索模式", "检索关键词", "Bot心理能量"):
            self.assertNotIn(banned, text)

    def test_diagnostics_entry_keeps_telemetry(self) -> None:
        text = self._intent().format_for_injection(520, include_diagnostics=True)
        for expected in ("检索模式", "检索关键词", "Bot心理能量"):
            self.assertIn(expected, text)


class InjectionBudgetConstantTests(unittest.TestCase):
    """R13：注入预算统一到常量族，compose 默认值取自常量。"""

    def test_budget_constants_are_consistent(self) -> None:
        self.assertEqual(MAX_INJECTION_CHARS, INJECTION_BUDGETS["total"])
        self.assertEqual(DEFAULT_INJECTION_CHARS, INJECTION_BUDGETS["default"])
        self.assertEqual(MIN_INJECTION_CHARS, INJECTION_BUDGETS["min"])
        self.assertEqual(SHORT_REPLY_INJECTION_CHARS, INJECTION_BUDGETS["short_reply"])
        self.assertEqual(TEMPORAL_INJECTION_CHARS, INJECTION_BUDGETS["temporal"])
        self.assertEqual(DEFAULT_CORE_MEMORY_CHARS, INJECTION_BUDGETS["core_memory"])
        self.assertEqual(DEFAULT_MAX_ITEM_CHARS, INJECTION_BUDGETS["max_item"])
        self.assertLessEqual(DEFAULT_INJECTION_CHARS, MAX_INJECTION_CHARS)
        self.assertLessEqual(SHORT_REPLY_INJECTION_CHARS, MAX_INJECTION_CHARS)

    def test_compose_defaults_follow_constants(self) -> None:
        params = inspect.signature(InjectionComposer.compose).parameters
        self.assertEqual(DEFAULT_INJECTION_CHARS, params["max_chars"].default)
        self.assertEqual(DEFAULT_CORE_MEMORY_CHARS, params["core_memory_max_chars"].default)
        self.assertEqual(DEFAULT_MAX_ITEM_CHARS, params["max_item_chars"].default)

    def test_compose_respects_total_budget(self) -> None:
        results = [
            SearchResult(memory=_memory(f"m{index}", "很长的记忆内容" * 40), score=1.0 - index * 0.01)
            for index in range(12)
        ]
        ctx = SessionContext(scope="private", session_id="s1", user_id="u1", message_text="你好")
        text = InjectionComposer().compose(ctx, results, max_chars=MAX_INJECTION_CHARS)
        self.assertTrue(text)
        self.assertLessEqual(len(text), MAX_INJECTION_CHARS)


class ImportanceLexiconTests(unittest.TestCase):
    """S6：重要度词表外置到 core/lexicon，未命中给中性分，打分可解释。"""

    def test_lexicon_file_is_external(self) -> None:
        path = Path(ImportanceEvaluator._lexicon_path())
        self.assertTrue(path.is_file(), str(path))
        self.assertEqual("lexicon", path.parent.name)
        evaluator = ImportanceEvaluator()
        dimensions = evaluator.lexicon.get("dimensions")
        self.assertIsInstance(dimensions, dict)
        self.assertEqual(9, len(dimensions))

    def test_unmatched_dimension_gets_neutral_score(self) -> None:
        evaluator = ImportanceEvaluator()
        neutral = evaluator._neutral_score
        self.assertGreater(neutral, 0.0)
        self.assertEqual(neutral, evaluator._dimension_score("完全无关的文本", "preference"))
        self.assertGreater(evaluator._dimension_score("我最喜欢你", "preference"), neutral)

    def test_custom_lexicon_is_honoured(self) -> None:
        evaluator = ImportanceEvaluator(
            lexicon={"dimensions": {"preference": ["测试词"]}}
        )
        self.assertGreater(
            evaluator._dimension_score("这里出现测试词", "preference"),
            evaluator._neutral_score,
        )
        self.assertEqual(
            evaluator._neutral_score, evaluator._dimension_score("没有命中", "preference")
        )

    def test_explain_lists_feature_contributions(self) -> None:
        evaluator = ImportanceEvaluator()
        record = _memory("explain", "用户喜欢猫，我们约定下周一起画设定图", importance=0.4)
        explanation = evaluator.explain(record)
        features = explanation["features"]
        self.assertEqual(
            {
                "memory_type",
                "lifecycle",
                "markers",
                "metadata",
                "persona",
                "freshness",
                "scar",
                "intimacy",
                "vulnerability",
                "length",
                "confidence",
                "low_value",
            },
            set(features),
        )
        self.assertAlmostEqual(evaluator.evaluate(record), explanation["final"], places=3)
        calibrated = evaluator.calibrate(_memory("calibrated", "用户喜欢猫", importance=0.4))
        self.assertEqual(set(features), set(calibrated.metadata["importance_features"]))

    def test_missing_lexicon_degrades_to_neutral(self) -> None:
        cached = ImportanceEvaluator._LEXICON_CACHE
        ImportanceEvaluator._LEXICON_CACHE = {}
        try:
            evaluator = ImportanceEvaluator()
            self.assertEqual({}, evaluator.lexicon)
            self.assertEqual(evaluator._neutral_score, evaluator._dimension_score("喜欢", "preference"))
            self.assertGreaterEqual(evaluator.evaluate(_memory("degraded", "喜欢猫", importance=0.5)), 0.0)
        finally:
            ImportanceEvaluator._LEXICON_CACHE = cached


class _CoreMemoryStore:
    def __init__(self) -> None:
        self.saved: MemoryRecord | None = None
        self.calls: list[tuple[MemoryRecord, int | None]] = []

    async def list_core_memories(self, limit: int = 1000):
        return []

    async def save_core_memory(self, record: MemoryRecord, expected_revision: int | None = None):
        self.saved = record
        self.calls.append((record, expected_revision))
        return {"ok": True, "id": record.id}


class CoreMemorySalienceTests(unittest.IsolatedAsyncioTestCase):
    """S7：核心记忆的 priority 只写 importance，不再同源写 salience。"""

    async def test_priority_is_not_copied_into_salience(self) -> None:
        store = _CoreMemoryStore()
        service = SimpleNamespace(store=store, stable_id=lambda *parts: "generated")
        service.save_core_memory_block = MemoryCompanionService.save_core_memory_block.__get__(service)
        result = await service.save_core_memory_block(
            {
                "label": "称呼",
                "content": "用户希望被叫小王",
                "scope": "private",
                "target_id": "u1",
                "kind": "preference",
                "priority": 80,
            }
        )
        self.assertTrue(result.get("ok"))
        saved = store.saved
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertAlmostEqual(0.8, saved.importance, places=6)
        self.assertNotEqual(saved.importance, saved.salience)
        self.assertAlmostEqual(0.3, saved.salience, places=6)


if __name__ == "__main__":
    unittest.main()
