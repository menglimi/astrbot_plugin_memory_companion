from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.importance import ImportanceEvaluator
from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SearchResult, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService, MemoryRouteDecision
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.time_intent import TimeIntent
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def make_engine(**kwargs: object) -> RetrievalEngine:
    """Build a RetrievalEngine backed by a throwaway store (retrieval disabled)."""
    temp_dir = tempfile.TemporaryDirectory()
    store = MemoryStore(Path(temp_dir.name) / "test.db")
    store.close()
    engine = RetrievalEngine(
        store,
        VisibilityPolicy(
            allow_self_timeline_everywhere=True,
            allow_group_public_in_private=False,
            hide_pending_review=True,
            include_raw_events=False,
            enable_acl_rules=True,
        ),
        retrieval_mode="basic",
        embedding_enabled=False,
        knowledge_graph_enabled=False,
        **kwargs,
    )
    return engine


class MentionPolicyRelaxTests(unittest.TestCase):
    def test_bot_self_background_promoted_when_relax_enabled(self) -> None:
        """Bot 自我时间线背景记忆：relax 开启后 mention_policy 从 tone_only 提为 soft_echo。"""
        weights = {"open_loop_weight": 0.2, "promise_weight": 0.2}  # < 0.58 → 背景分支
        record = MemoryRecord(
            id="m1",
            memory_type="observation",
            scope="private",
            visibility="bot_self",
            reality_level="bot_action",
            content="Bot 自己在家看家的记录。",
            confidence=0.6,
            importance=0.5,
            metadata=weights,
        )
        strict = ImportanceEvaluator(mention_policy_relax=False)
        relaxed = ImportanceEvaluator(mention_policy_relax=True)
        self.assertEqual("tone_only", strict._mention_policy(record, weights)[0])
        self.assertEqual("soft_echo", relaxed._mention_policy(record, weights)[0])

    def test_emotional_memory_promoted_when_relax_enabled(self) -> None:
        """情绪较重记忆：relax 开启后 mention_policy 从 tone_only 提为 soft_echo。"""
        weights = {"scar_weight": 0.7, "emotional_debt_weight": 0.5}  # max >= 0.66
        record = MemoryRecord(
            id="m2",
            memory_type="observation",
            scope="private",
            visibility="private_pair",
            reality_level="real_user_fact",
            content="用户情绪波动较大的一次记录。",
            confidence=0.6,
            importance=0.5,
            metadata=weights,
        )
        strict = ImportanceEvaluator(mention_policy_relax=False)
        relaxed = ImportanceEvaluator(mention_policy_relax=True)
        self.assertEqual("tone_only", strict._mention_policy(record, weights)[0])
        self.assertEqual("soft_echo", relaxed._mention_policy(record, weights)[0])

    def test_high_value_branch_unchanged_when_relax_enabled(self) -> None:
        """高价值分支（open_loop >= 0.58）本来就 soft_echo，relax 不改变结果。"""
        weights = {"open_loop_weight": 0.8}
        record = MemoryRecord(
            id="m3",
            memory_type="observation",
            scope="private",
            visibility="bot_self",
            reality_level="bot_action",
            content="Bot 承诺过的事。",
            confidence=0.6,
            importance=0.5,
            metadata=weights,
        )
        for relax in (False, True):
            self.assertEqual(
                "soft_echo",
                ImportanceEvaluator(mention_policy_relax=relax)._mention_policy(record, weights)[0],
            )


class ToneAbstractionToggleTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, tone_abstraction: bool) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={"memory_injection": {"enable_tone_abstraction": tone_abstraction}},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def _decide(service: MemoryCompanionService) -> tuple[str, str]:
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_text="随便聊聊",
        )
        memory = MemoryRecord(
            id="s1",
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="user"),
            object=EntityRef.bot_self("b1"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            visibility="private_pair",
            reality_level="llm_summary",
            lifecycle="stable_memory",
            content="用户和 Bot 昨天聊了特调配方。",
            confidence=0.72,
            importance=0.9,
        )
        item = SearchResult(memory=memory, score=1.2)
        decision = MemoryRouteDecision(layer="current_message")
        return service._memory_expression_decision(
            ctx, memory, item, "conversation_summary", decision, TimeIntent()
        )

    async def test_toggle_off_returns_candidate_for_summary(self) -> None:
        """总闸关闭后，非显式回忆的总结记忆直接给正文（candidate），不再折叠为 tone。"""
        service = self.make_service(tone_abstraction=False)
        expression, reason = self._decide(service)
        self.assertEqual("candidate", expression)
        self.assertEqual("tone_abstraction_disabled", reason)

    async def test_toggle_on_summary_non_explicit_is_tone(self) -> None:
        """总闸默认开启（作者逻辑）：非显式回忆的总结记忆仍折叠为 tone 占位。"""
        service = self.make_service(tone_abstraction=True)
        expression, reason = self._decide(service)
        self.assertEqual("tone", expression)
        self.assertIn("conversation_continuity_background", reason)


class KeywordMinHitsRelaxTests(unittest.TestCase):
    def test_relax_keyword_min_hits_lowers_min_hits(self) -> None:
        """普通多词查询（len(terms) >= 4 分支）默认 min_hits=2，relax 后降到 1。"""
        # 用无连续中文短语的 query，确保走 len(terms)>=4 分支而非 exact_phrases 分支
        query = "hi there friend hello"
        terms = ["hi", "there", "friend", "hello"]
        strict = make_engine(relax_keyword_min_hits=False)
        relaxed = make_engine(relax_keyword_min_hits=True)
        self.assertEqual(2, strict._query_profile(query, terms)["min_hits"])
        self.assertEqual(1, relaxed._query_profile(query, terms)["min_hits"])

    def test_relax_keeps_explicit_branches_unchanged(self) -> None:
        """current_state 分支本就 min_hits=1，relax 不改变（保持兼容）。"""
        terms = ["在", "吗"]
        strict = make_engine(relax_keyword_min_hits=False)
        relaxed = make_engine(relax_keyword_min_hits=True)
        self.assertEqual(1, strict._query_profile("在吗", terms)["min_hits"])
        self.assertEqual(1, relaxed._query_profile("在吗", terms)["min_hits"])


class ProactiveMessagePenaltyTests(unittest.TestCase):
    def _score(self, engine: RetrievalEngine) -> float:
        memory = MemoryRecord(
            id="proactive",
            memory_type="proactive_message",
            scope="private",
            visibility="private_pair",
            content="Bot 主动发送：今天天气多云转晴。",
            confidence=0.7,
            importance=0.5,
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_text="hi",
        )
        profile = engine._query_profile("天气", ["天气"])
        # R2：无查询词时不再用 importance 兜底打分（直接 0 分/空召回），
        # 所以这条降权用例必须带真实查询词才有分可乘。
        score, _reason = engine._score(memory, ["天气"], ctx, profile, {})
        return score

    def test_proactive_message_penalty_scales_score(self) -> None:
        """penalty < 1.0 时 proactive_message 记忆评分被乘，默认 1.0 不降权。"""
        default = make_engine(proactive_message_score_penalty=1.0)
        damped = make_engine(proactive_message_score_penalty=0.3)
        self.assertGreater(self._score(default), self._score(damped))


class DedupeContentTests(unittest.TestCase):
    def test_dedupe_keeps_highest_score_of_near_identical(self) -> None:
        """规范化文本相似度 >= 阈值时只保留评分最高的一条。"""
        engine = make_engine()
        a = SearchResult(
            memory=MemoryRecord(id="a", content="哥哥不喜欢被催睡觉，不要提醒作息安排。"),
            score=1.0,
        )
        b = SearchResult(
            memory=MemoryRecord(id="b", content="哥哥不喜欢被催睡觉不要提醒作息安排"),
            score=0.5,
        )
        out = engine._dedupe_by_content([a, b], 0.8)
        self.assertEqual(1, len(out))
        self.assertEqual("a", out[0].memory.id)

    def test_dedupe_keeps_distinct_contents(self) -> None:
        """内容差异大的候选不去重。"""
        engine = make_engine()
        a = SearchResult(
            memory=MemoryRecord(id="a", content="哥哥喜欢喝菠萝干姜特调。"),
            score=1.0,
        )
        b = SearchResult(
            memory=MemoryRecord(id="b", content="哥哥大学时玩过生化危机村庄。"),
            score=0.9,
        )
        out = engine._dedupe_by_content([a, b], 0.8)
        self.assertEqual(2, len(out))


if __name__ == "__main__":
    unittest.main()
