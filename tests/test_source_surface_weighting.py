"""来源降权的打分行为：默认中性、按来源面乘系数、非法配置回落。

用 RetrievalEngine._score() 直接断言，不跑整轮召回：结果确定、可复现，
且能同时钉住「默认配置下分数与诊断串逐字节一致」。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.models import MemoryRecord, SessionContext
from core.retrieval import RetrievalEngine
from core.store import MemoryStore
from core.visibility import VisibilityPolicy

QUERY_TERMS = ["天气"]
REGISTERED = ("minecraft", "qq")


def make_engine(**kwargs) -> RetrievalEngine:
    temp_dir = tempfile.TemporaryDirectory()
    store = MemoryStore(Path(temp_dir.name) / "test.db")
    store.close()
    return RetrievalEngine(
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
        source_surface_names=REGISTERED,
        **kwargs,
    )


def record(surface=None, *, memory_type="observation", content="今天天气多云转晴。") -> MemoryRecord:
    metadata = {} if surface is None else {"source_surface": surface}
    return MemoryRecord(
        id="m-%s" % (surface or "none"),
        memory_type=memory_type,
        scope="private",
        visibility="private_pair",
        content=content,
        confidence=0.7,
        importance=0.5,
        metadata=metadata,
    )


CTX = SessionContext(
    session_id="qq:FriendMessage:u1",
    scope="private",
    platform="qq",
    user_id="u1",
    bot_id="b1",
    message_text="天气",
)


def score(engine: RetrievalEngine, memory: MemoryRecord) -> tuple[float, str]:
    profile = engine._query_profile("天气", QUERY_TERMS)
    return engine._score(memory, QUERY_TERMS, CTX, profile, {})


class DefaultIsNeutralTests(unittest.TestCase):
    def test_equal_default_is_byte_identical(self):
        memory = record("minecraft")
        default_score, default_reason = score(make_engine(), memory)
        explicit_score, explicit_reason = score(
            make_engine(source_surface_priority="equal", source_surface_weight=1.0), memory
        )
        self.assertEqual(default_score, explicit_score)
        self.assertEqual(default_reason, explicit_reason)
        self.assertNotIn("source=", default_reason)

    def test_legacy_and_unknown_rows_are_untouched(self):
        engine = make_engine(source_surface_priority="qq", source_surface_weight=0.2)
        baseline = score(make_engine(), record(None))[0]
        for surface in (None, "unknown", "mixed"):
            with self.subTest(surface=surface):
                self.assertEqual(baseline, score(engine, record(surface))[0])


class PriorityTests(unittest.TestCase):
    def test_qq_priority_demotes_minecraft_rows(self):
        baseline = score(make_engine(), record("minecraft"))[0]
        engine = make_engine(source_surface_priority="qq", source_surface_weight=0.5)
        self.assertAlmostEqual(baseline * 0.5, score(engine, record("minecraft"))[0], places=9)
        self.assertEqual(baseline, score(engine, record("qq"))[0])

    def test_minecraft_priority_is_symmetric(self):
        baseline = score(make_engine(), record("qq"))[0]
        engine = make_engine(source_surface_priority="minecraft", source_surface_weight=0.4)
        self.assertAlmostEqual(baseline * 0.4, score(engine, record("qq"))[0], places=9)
        self.assertEqual(
            score(make_engine(), record("minecraft"))[0],
            score(engine, record("minecraft"))[0],
        )

    def test_explicit_weights_override_priority(self):
        baseline = score(make_engine(), record("minecraft"))[0]
        engine = make_engine(
            source_surface_priority="qq",
            source_surface_weight=0.5,
            source_surface_weights={"minecraft": 0.2},
        )
        self.assertAlmostEqual(baseline * 0.2, score(engine, record("minecraft"))[0], places=9)

    def test_undeclared_surface_stays_neutral(self):
        baseline = score(make_engine(), record("discord"))[0]
        engine = make_engine(source_surface_priority="qq", source_surface_weight=0.1)
        self.assertEqual(baseline, score(engine, record("discord"))[0])


class ConfigFallbackTests(unittest.TestCase):
    def test_invalid_priority_falls_back_to_equal(self):
        engine = make_engine(source_surface_priority="ff14", source_surface_weight=0.5)
        self.assertEqual("equal", engine.source_surface_priority)
        baseline = score(make_engine(), record("minecraft"))[0]
        self.assertEqual(baseline, score(engine, record("minecraft"))[0])

    def test_weight_is_clamped_and_non_numeric_falls_back(self):
        self.assertEqual(1.0, make_engine(source_surface_weight=2.5).source_surface_weight)
        self.assertEqual(1.0, make_engine(source_surface_weight="abc").source_surface_weight)
        self.assertEqual(0.0, make_engine(source_surface_weight=-3).source_surface_weight)
        self.assertEqual(0.0, make_engine(source_surface_weight=0).source_surface_weight)

    def test_reason_reports_source_only_when_discounted(self):
        engine = make_engine(source_surface_priority="qq", source_surface_weight=0.5)
        _score_value, reason = score(engine, record("minecraft"))
        self.assertIn("source=minecraft;w=0.50", reason)
        _score_value, kept_reason = score(engine, record("qq"))
        self.assertNotIn("source=", kept_reason)


if __name__ == "__main__":
    unittest.main()
