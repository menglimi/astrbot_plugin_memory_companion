from __future__ import annotations

from contextlib import ExitStack

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.assertions import (
    ASSERTION_MEMORY_TYPE,
    assertion_is_promotable,
    cardinality_for,
    claim_is_personal_fact,
    normalize_assertion,
)
from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore


CHAT = [
    "naliling 我今天真的好累啊 加班到现在才吃上饭",
    "naliling 昨晚我一共才睡了六个小时 一直在想事情",
    "naliling 我不是不开心 就是有点累",
    "naliling 明天还要早起 真的不想去上班",
    "naliling 我一累就咬后槽牙 小时候就这样",
    "naliling 我最喜欢喝冰美式 不加糖",
    "naliling 我不吃香菜 一点点都不行",
    "naliling 我妈忌日是每年十一月三号",
    "naliling 我睡觉必须开着白噪音 不开就睡不着",
    "naliling 我跟他说过一次就够了 不喜欢重复",
    "naliling 他生气的时候会先沉默三秒 然后才说话",
]

CTX = SessionContext(
    session_id="qq:FriendMessage:u1", scope="private", platform="qq",
    user_id="naliling", user_name="naliling", bot_id="b1",
)


def _rows(event_ids):
    return [
        {
            "id": event_id, "content": content, "event_type": "user_message",
            "scope": "private", "subject_id": "naliling",
            "occurred_at": f"2026-10-03T20:{index:02d}:00+08:00",
        }
        for index, (event_id, content) in enumerate(zip(event_ids, CHAT))
    ]


def _payload(event_ids):
    return {
        "outcome": "memory",
        "summary": (
            "naliling 跟我说了他加班到很晚才吃上饭、昨晚只睡了六个小时，"
            "也很抗拒第二天早起去上班。他还说了一些自己一直的习惯：不加糖的冰美式、"
            "不吃香菜、累的时候咬后槽牙、睡觉要开白噪音，还有同一件事只说一次。"
        ),
        "canonical_summary": "naliling 反馈疲惫，并说明了饮食与作息习惯。",
        "summary_refs": list(event_ids),
        "topics": ["近况", "习惯"],
        "assertions": [
            {"subject": "naliling", "predicate": "habit",
             "value": "累的时候会咬后槽牙", "polarity": "positive",
             "durability": "stable", "refs": [event_ids[4]]},
            {"subject": "naliling", "predicate": "habit",
             "value": "生气时会先沉默三秒再说话", "polarity": "positive",
             "durability": "stable", "refs": [event_ids[10]]},
            {"subject": "naliling", "predicate": "preference",
             "value": "喜欢喝冰美式且不加糖", "polarity": "positive",
             "durability": "stable", "refs": [event_ids[5]]},
            {"subject": "naliling", "predicate": "dietary_restriction",
             "value": "不能吃香菜", "polarity": "positive",
             "durability": "stable", "refs": [event_ids[6]]},
            {"subject": "naliling", "predicate": "health",
             "value": "母亲的忌日是每年十一月三号", "polarity": "positive",
             "durability": "stable", "refs": [event_ids[7]]},
            {"subject": "naliling", "predicate": "habit",
             "value": "睡觉必须开着白噪音", "polarity": "positive",
             "durability": "stable", "refs": [event_ids[8]]},
            {"subject": "naliling", "predicate": "commitment",
             "value": "同一件事只说一次，不喜欢重复", "polarity": "negative",
             "durability": "stable", "refs": [event_ids[9]]},
            # Nothing in the window supports this one.
            {"subject": "naliling", "predicate": "habit",
             "value": "养了三只仓鼠每天早上喂", "polarity": "positive",
             "durability": "stable", "refs": [event_ids[0]]},
        ],
        "key_facts": [], "associations": [], "routine_check_notes": [],
        "sentiment": "neutral", "importance": 0.6,
    }


class _Provider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def text_chat(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(completion_text=json.dumps(self.payload, ensure_ascii=False))


class AssertionExtractionTests(unittest.IsolatedAsyncioTestCase):
    """The details a conversation-summary layer structurally cannot keep.

    Before this layer existed, every one of these had to match a regex shaped
    like "I like X" and was otherwise dropped with no fallback.
    """

    def test_details_the_regex_extractor_missed_survive_normalization(self) -> None:
        cases = {
            "habit": "累的时候会咬后槽牙",
            "habit": "生气时会先沉默三秒再说话",
            "health": "母亲的忌日是每年十一月三号",
            "habit": "睡觉必须开着白噪音",
            "commitment": "同一件事只说一次，不喜欢重复",
        }
        for dimension, value in cases.items():
            assertion = normalize_assertion({
                "subject": "naliling", "predicate": dimension, "value": value,
                "polarity": "positive", "durability": "stable", "refs": ["e1"],
            })
            self.assertTrue(assertion, value)
            self.assertEqual(dimension, assertion["dimension"])

    def test_unknown_dimension_and_missing_subject_are_dropped(self) -> None:
        self.assertEqual({}, normalize_assertion({
            "subject": "naliling", "predicate": "自创维度", "value": "x",
            "polarity": "positive", "durability": "stable", "refs": ["e1"],
        }))
        self.assertEqual({}, normalize_assertion({
            "subject": "", "predicate": "habit", "value": "缺主体",
            "polarity": "positive", "durability": "stable", "refs": ["e1"],
        }))

    def test_normalization_is_idempotent(self) -> None:
        """The payload carries normalized keys, so re-normalizing must not drop it."""
        once = normalize_assertion({
            "subject": "naliling", "predicate": "habit", "value": "累的时候会咬后槽牙",
            "polarity": "positive", "durability": "stable", "refs": ["e1"],
        })
        self.assertEqual(once["dimension"], normalize_assertion(once)["dimension"])

    async def test_unsupported_assertion_is_dropped_without_failing_the_batch(self) -> None:
        summarizer = MemorySummarizer()
        rows = _rows([f"e{i}" for i in range(len(CHAT))])
        event_ids = [row["id"] for row in rows]
        kept, warnings = summarizer._normalize_assertions(
            _payload(event_ids)["assertions"], rows
        )
        values = {item["value"] for item in kept}
        self.assertIn("累的时候会咬后槽牙", values)
        self.assertNotIn("养了三只仓鼠每天早上喂", values)
        self.assertTrue(warnings, "dropping an unsupported assertion must be reported")


class PersonalFactGateTests(unittest.TestCase):
    """A claim can be literally in the transcript and still not be a fact.

    Reported speech, role-play, a temporary state and an intention all pass a
    source check. The model was asked to tell them apart, but when it does not,
    only this gate stands between them and long-term memory.
    """

    @staticmethod
    def _assertion(value, *, polarity="positive", durability="stable"):
        return normalize_assertion({
            "subject": "naliling", "predicate": "habit", "value": value,
            "polarity": polarity, "durability": durability, "refs": ["e1"],
        })

    def test_a_real_long_term_detail_stays_promotable(self) -> None:
        self.assertTrue(assertion_is_promotable(
            self._assertion("累的时候会咬后槽牙"), ["他一累就咬后槽牙 小时候就这样"]))
        self.assertTrue(assertion_is_promotable(
            self._assertion("母亲的忌日是每年十一月三号"), ["我妈忌日是每年十一月三号"]))

    def test_reported_speech_is_refused_even_after_the_rewrite(self) -> None:
        """The model drops "他说" when it rewrites; the original still has it."""
        assertion = self._assertion("naliling 最讨厌香菜")
        self.assertFalse(assertion_is_promotable(
            assertion, ["他说他最讨厌香菜 我觉得可能是瞎说"]))
        self.assertEqual(
            "reported_speech",
            claim_is_personal_fact("naliling", "naliling 最讨厌香菜",
                                   ["他说他最讨厌香菜 我觉得可能是瞎说"])[1],
        )

    def test_role_play_temporary_state_and_intent_are_refused(self) -> None:
        cases = [
            ("代号十七今晚要行动", "（角色扮演）我是刺客代号十七 今晚行动", "role_play"),
            ("有点累", "今天有点累 明天就好了", "temporary_state"),
            ("每天跑五公里", "我打算下周开始每天跑五公里", "intent"),
        ]
        for value, message, reason in cases:
            with self.subTest(value=value):
                ok, why = claim_is_personal_fact("naliling", value, [message])
                self.assertFalse(ok)
                self.assertEqual(reason, why)

    def test_a_third_person_claim_about_someone_else_is_refused(self) -> None:
        ok, why = claim_is_personal_fact("naliling", "他去洗澡了")
        self.assertFalse(ok)
        self.assertEqual("subject_mismatch", why)

    def test_a_user_describing_themselves_in_third_person_is_not_refused(self) -> None:
        """Refusing this would lose the exact detail the layer exists to keep."""
        self.assertTrue(claim_is_personal_fact(
            "naliling", "累的时候会咬后槽牙", ["他一累就咬后槽牙 小时候就这样"])[0])

    def test_a_situational_claim_never_becomes_stable_however_it_is_written(self) -> None:
        assertion = normalize_assertion({
            "subject": "naliling", "predicate": "habit", "value": "今天有点累",
            "polarity": "positive", "durability": "stable", "refs": ["e1"],
        })
        self.assertFalse(assertion_is_promotable(assertion, ["今天有点累 明天就好了"]))



class AssertionMergeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name) / "test.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    def _record(self, dimension, value, *, polarity="positive", refs=("e1",)):
        import re
        return MemoryRecord(
            id=f"assertion_{abs(hash((dimension, value, polarity))) % 10 ** 12}",
            memory_type=ASSERTION_MEMORY_TYPE,
            subject=EntityRef(kind="user", id="u1", name="naliling"),
            object=EntityRef.bot_self(bot_id="b1"),
            scope="private", session_id="qq:FriendMessage:u1", platform="qq",
            visibility="private_pair", lifecycle="stable_memory", review_status="auto",
            content=value, evidence="原始消息", confidence=0.8, importance=0.5,
            owner_bot_id="b1", durability="normal", sensitivity="internal",
            metadata={
                "profile_dimension": dimension, "profile_polarity": polarity,
                "profile_value": value,
                "normalized_value": re.sub(r"\s+", " ", value.casefold()).strip(),
                "profile_cardinality": cardinality_for(dimension),
                "assertion_evidence_refs": list(refs),
            },
        )

    async def test_the_same_claim_from_two_becomes_one_row_with_two_sources(self) -> None:
        first = await self.store.upsert_assertion(self._record("habit", "累的时候会咬后槽牙", refs=("e1",)))
        second = await self.store.upsert_assertion(self._record("habit", "累的时候会咬后槽牙", refs=("e7",)))
        self.assertEqual(first["memory_id"], second["memory_id"])
        self.assertFalse(second["created"])
        self.assertEqual(2, second["merged_sources"])
        self.assertEqual(
            1,
            self.store._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE memory_type='assertion'"
            ).fetchone()[0],
        )

    async def test_two_different_habits_both_survive(self) -> None:
        await self.store.upsert_assertion(self._record("habit", "累的时候会咬后槽牙"))
        await self.store.upsert_assertion(self._record("habit", "生气时会先沉默三秒"))
        rows = self.store._conn.execute(
            "SELECT lifecycle FROM memories WHERE memory_type='assertion' "
            "AND json_extract(metadata,'$.profile_dimension')='habit'"
        ).fetchall()
        self.assertEqual(2, len(rows))
        self.assertTrue(all(row["lifecycle"] == "stable_memory" for row in rows))

    async def test_changing_a_single_value_supersedes_the_previous_one(self) -> None:
        old = await self.store.upsert_assertion(self._record("preferred_address", "住在上海"))
        new = await self.store.upsert_assertion(self._record("preferred_address", "现在住在北京"))
        previous = self.store._conn.execute(
            "SELECT lifecycle, supersedes_id FROM memories WHERE id=?", (old["memory_id"],)
        ).fetchone()
        self.assertEqual("archived", previous["lifecycle"])
        self.assertEqual(new["memory_id"], previous["supersedes_id"])
        self.assertIn(old["memory_id"], new["superseded"])

    async def test_non_assertion_rows_are_rejected(self) -> None:
        record = self._record("habit", "累的时候会咬后槽牙")
        record.memory_type = "conversation_summary"
        result = await self.store.upsert_assertion(record)
        self.assertFalse(result["ok"])
        self.assertEqual("assertion_invalid", result["code"])


class AssertionInjectionTests(unittest.TestCase):
    def test_the_fact_answering_the_question_is_not_cut_off_by_earlier_ones(self) -> None:
        """§M-03: the answer stored last used to lose to whatever was stored first."""
        facts = [
            "小王的资料整理背景A",
            "小王的资料整理背景B",
            "小王的资料整理背景C",
            "蓝色文件夹放在第三个抽屉",
        ]
        selected = InjectionComposer._select_relevant_facts(facts, query="蓝色文件夹放在哪")
        self.assertEqual("蓝色文件夹放在第三个抽屉", selected[0])

    def test_without_a_question_the_original_order_is_kept(self) -> None:
        facts = ["第一条", "第二条", "第三条"]
        self.assertEqual(facts, InjectionComposer._select_relevant_facts(facts, query=""))


class LatencyBudgetTests(unittest.IsolatedAsyncioTestCase):
    """Speed must come from dropping optional model calls, never from results."""

    @staticmethod
    def _results(count: int):
        return [
            SimpleNamespace(
                memory=MemoryRecord(
                    id=f"m{i}", memory_type="conversation_summary",
                    subject=EntityRef(kind="user", id="u1"),
                    object=EntityRef.bot_self(bot_id="b1"),
                    scope="private", session_id="s", platform="qq",
                    visibility="private_pair", content=f"记忆{i}关于蓝风铃",
                    lifecycle="stable_memory", review_status="auto",
                ),
                score=0.5,
            )
            for i in range(count)
        ]

    async def test_a_spent_budget_skips_rerank_but_keeps_every_candidate(self) -> None:
        import time

        calls = []

        class Reranker:
            async def rerank(self, query, documents, **kwargs):
                calls.append(1)
                return {"results": [{"index": i, "score": 1.0} for i in range(len(documents))]}

        candidates = self._results(5)
        engine = RetrievalEngine(
            None, None, retrieval_mode="rerank", rerank_provider=Reranker(),
            rerank_timeout_ms=1000, latency_budget_ms=0,
        )
        engine.start_latency_budget()
        await engine._maybe_rerank_results("蓝风铃", candidates, 3)
        self.assertEqual(1, len(calls))

        spent = RetrievalEngine(
            None, None, retrieval_mode="rerank", rerank_provider=Reranker(),
            rerank_timeout_ms=1000, latency_budget_ms=1,
        )
        spent.start_latency_budget()
        time.sleep(0.01)
        kept = await spent._maybe_rerank_results("蓝风铃", candidates, 3)
        self.assertEqual(1, len(calls))
        self.assertEqual(len(candidates), len(kept))
        self.assertEqual("latency_budget_spent", spent.last_path_info.get("reason"))

    async def test_a_repeated_question_reuses_its_vector(self) -> None:
        calls = []

        class Embedder:
            async def get_embedding(self, text):
                calls.append(text)
                return [0.1, 0.2, 0.3]

        engine = RetrievalEngine(
            None, None, embedding_provider=Embedder(), embedding_enabled=True,
            query_vector_cache_ttl_seconds=60,
        )
        first = await engine._call_embedding_provider("同一个问题")
        again = await engine._call_embedding_provider("同一个问题")
        await engine._call_embedding_provider("另一个问题")
        self.assertEqual(first, again)
        self.assertEqual(2, len(calls))


class AssertionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_window_produces_both_the_summary_and_the_assertions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as cleanup:
            config = {
                "startup": {"background_grace_seconds": 60},
                "memory_summary": {
                    "min_events": 1, "trigger_event_count": 1,
                    "max_events_per_summary": 20, "max_retries": 3,
                    "retry_backoff_seconds": 0, "max_calls_per_session_hour": 60,
                },
            }
            service = MemoryCompanionService(
                context=None, config=config, plugin_root=ROOT, data_dir=Path(tmp))
            cleanup.callback(service.close)
            service._schedule_memory_embedding = lambda *args: None
            event_ids = []
            for index, content in enumerate(CHAT):
                event_ids.append(await service.store.add_timeline_event(
                    event_type="user_message", session_id=CTX.session_id, scope=CTX.scope,
                    subject_id=CTX.user_id, object_id=CTX.bot_id, content=content,
                    metadata={"sender_name": "naliling"},
                    occurred_at=f"2026-10-03T20:{index:02d}:00+08:00"))
            provider = _Provider(_payload(event_ids))

            async def attempts(*args, **kwargs):
                return [{"provider": provider, "provider_id": "0", "source": "primary"}]

            service._summary_provider_attempts = attempts
            summary_id = await service.maybe_summarize_session(CTX)
            self.assertTrue(summary_id)
            # One provider call covers both layers.
            self.assertEqual(1, provider.calls)

            rows = service.store._conn.execute(
                "SELECT content AS content, "
                "json_extract(metadata,'$.profile_dimension') AS dimension, "
                "json_extract(metadata,'$.assertion_cross_scene') AS cross_scene "
                "FROM memories WHERE memory_type=? ORDER BY dimension", (ASSERTION_MEMORY_TYPE,)
            ).fetchall()
            values = {row["content"] for row in rows}
            self.assertIn("累的时候会咬后槽牙", values)
            self.assertIn("不能吃香菜", values)
            self.assertNotIn("养了三只仓鼠每天早上喂", values)

            # Only the whitelisted dimensions may leave their window.
            cross = {row["dimension"]: row["cross_scene"] for row in rows}
            self.assertEqual(1, cross["preference"])
            self.assertEqual(1, cross["dietary_restriction"])
            self.assertEqual(0, cross["habit"])
            self.assertEqual(0, cross["health"])

    async def test_disabling_the_layer_falls_back_to_the_old_behaviour(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as cleanup:
            config = {
                "startup": {"background_grace_seconds": 60},
                "memory_assertions": {"enabled": False},
                "memory_summary": {
                    "min_events": 1, "trigger_event_count": 1,
                    "max_events_per_summary": 20, "max_retries": 3,
                    "retry_backoff_seconds": 0, "max_calls_per_session_hour": 60,
                },
            }
            service = MemoryCompanionService(
                context=None, config=config, plugin_root=ROOT, data_dir=Path(tmp))
            cleanup.callback(service.close)
            service._schedule_memory_embedding = lambda *args: None
            event_ids = []
            for index, content in enumerate(CHAT):
                event_ids.append(await service.store.add_timeline_event(
                    event_type="user_message", session_id=CTX.session_id, scope=CTX.scope,
                    subject_id=CTX.user_id, object_id=CTX.bot_id, content=content,
                    metadata={"sender_name": "naliling"},
                    occurred_at=f"2026-10-03T20:{index:02d}:00+08:00"))
            provider = _Provider(_payload(event_ids))

            async def attempts(*args, **kwargs):
                return [{"provider": provider, "provider_id": "0", "source": "primary"}]

            service._summary_provider_attempts = attempts
            self.assertTrue(await service.maybe_summarize_session(CTX))
            self.assertEqual(
                0,
                service.store._conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE memory_type=?",
                    (ASSERTION_MEMORY_TYPE,),
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
