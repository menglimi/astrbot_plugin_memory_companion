from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from core.classifier import MemoryClassifier
from core.models import SessionContext
from core.portrait import extract_explicit_candidates
from core.portrait_service import PortraitService
from core.profile_quality import (
    extract_profile_candidates,
    profile_candidate_metadata,
    profile_quality_decision,
    profile_rejection_reason,
)
from core.store import MemoryStore
from unified_profile_contract import build_profile_dto

PERSON_REF = {
    "person_id": "person_" + "1" * 24,
    "resolved_identity_key": "chat-origin-v1:" + "2" * 64,
    "projection_revision": 1,
    "identity_assurance": "observed",
    "profile_status": "active",
}


class _Config:
    @staticmethod
    def float(_key: str, default: float) -> float:
        return default

    @staticmethod
    def int(_key: str, default: int) -> int:
        return default


def context(text: str) -> SessionContext:
    return SessionContext(
        session_id="onebot:FriendMessage:u1",
        scope="private",
        platform="onebot",
        user_id="u1",
        user_name="小王",
        bot_id="bot-1",
        message_id="message-1",
        message_text=text,
    )


class ProfileNoiseExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = MemoryClassifier()

    def assert_paths(self, text: str, expected: list[tuple[str, str]]) -> None:
        records = self.classifier.derived_user_memories(
            context(text), source_memory_id="source-1"
        )
        classifier_values = [
            (
                record.metadata.get("profile_dimension"),
                record.metadata.get("profile_value"),
            )
            for record in records
            if record.metadata.get("profile_dimension")
        ]
        portrait_values = [
            (candidate.get("profile_dimension"), candidate.get("profile_value"))
            for candidate in extract_explicit_candidates(text)
        ]
        self.assertEqual(expected, classifier_values)
        self.assertEqual(expected, portrait_values)

    def test_direct_address_requests_share_one_extractor(self) -> None:
        for text, value in (
            ("叫我宝宝", "宝宝"),
            ("以后你叫我主人", "主人"),
            ("你以后叫我阿岚", "阿岚"),
            ("以后请叫我星桥M29", "星桥M29"),
            ("请喊我小王吧", "小王"),
            ("称呼我为墨飞", "墨飞"),
        ):
            with self.subTest(text=text):
                self.assert_paths(text, [("preferred_address", value)])

    def test_address_noise_is_rejected_by_both_paths(self) -> None:
        for text in (
            "老板娘叫我去跟车呢",
            "他总叫我笨蛋",
            "叫我去上班",
            "不许叫我大色狼",
            "叫我几声宝宝",
            "怎么还叫我小王",
        ):
            with self.subTest(text=text):
                self.assert_paths(text, [])

    def test_sentence_boundaries_and_particles_are_normalized(self) -> None:
        self.assert_paths(
            "好的，我喜欢烤肉。以后叫我宝宝就好！",
            [("preference", "烤肉"), ("preferred_address", "宝宝")],
        )
        self.assert_paths("我喜欢酒吧", [("preference", "酒吧")])

    def test_reported_quoted_and_interrogative_facts_are_rejected(self) -> None:
        for text in (
            "她说，我喜欢烤肉",
            "听说，我的生日是八月一日",
            "同事说，‘我通常用简短回复’",
            "她说：\n我喜欢烤肉",
            "引用如下：\n我的生日是八月一日",
            "我喜欢什么？",
            "我的生日你还记得吗？",
            "我的生日是几月几号",
            "我通常几点睡",
            "我喜欢咖啡还是茶",
            "我喜欢啥",
            "她提到，我喜欢烤肉",
            "同事描述，我的生日是八月一日",
            "据她介绍，叫我宝宝",
        ):
            with self.subTest(text=text):
                self.assert_paths(text, [])

    def test_other_direct_profile_dimensions_remain_available(self) -> None:
        for text, expected in (
            ("我的生日是八月一日", [("birthday", "八月一日")]),
            ("我从事软件开发", [("occupation", "软件开发")]),
            ("我的专业是计算机", [("education", "计算机")]),
            ("我通常用简短回复", [("communication_preference", "用简短回复")]),
        ):
            with self.subTest(text=text):
                self.assert_paths(text, expected)

    def test_temporary_state_and_current_action_do_not_become_profiles(self) -> None:
        for text in (
            "我今天很累",
            "我现在很焦虑",
            "我今天在做测试",
            "我在做一个项目",
            "我最近喜欢烤肉",
            "我可能喜欢烤肉",
            "我不喜欢今天的工作安排",
            "我喜欢今天的午饭",
            "我讨厌这次互动",
            "我不能吃今天的午饭",
            "我不能碰这杯咖啡",
        ):
            with self.subTest(text=text):
                self.assert_paths(text, [])

    def test_rejected_profile_attempts_have_observable_gate_reasons(self) -> None:
        cases = {
            "叫我去上班": "action_context",
            "他总叫我笨蛋": "third_party_statement",
            "不许叫我大色狼": "profile_quality_rejected",
            "我喜欢什么？": "profile_quality_rejected",
            "我最近喜欢烤肉": "profile_quality_rejected",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(expected, profile_rejection_reason(text))
        self.assertEqual("", profile_rejection_reason("今天天气不错"))
        self.assertEqual("", profile_rejection_reason("以后叫我宝宝"))

    def test_rule_v2_metadata_and_scores_are_not_fixed(self) -> None:
        address = self.classifier.derived_user_memories(
            context("以后叫我宝宝"), "source-1"
        )[0]
        habit = self.classifier.derived_user_memories(
            context("我通常用简短回复"), "source-2"
        )[0]

        self.assertEqual("rule_v2", address.metadata["extractor"])
        self.assertEqual("preferred_address", address.metadata["profile_dimension"])
        self.assertEqual("宝宝", address.metadata["profile_value"])
        self.assertEqual("宝宝", address.metadata["normalized_value"])
        self.assertEqual("explicit", address.metadata["extraction_quality"])
        self.assertEqual("direct_statement", address.metadata["evidence_strength"])
        self.assertEqual("active", address.metadata["profile_state"])
        self.assertEqual("source-1", address.metadata["source_memory_id"])
        self.assertEqual("stable_memory", address.lifecycle)
        self.assertEqual("auto", address.review_status)
        self.assertGreater(address.confidence, habit.confidence)
        self.assertEqual(
            (True, "profile_quality_passed"), profile_quality_decision(address)
        )

    def test_quality_gate_has_stable_state_reasons_and_manual_compatibility(
        self,
    ) -> None:
        candidate = extract_profile_candidates("以后叫我宝宝")[0]
        metadata = profile_candidate_metadata(candidate, source_memory_id="source-1")
        self.assertEqual(
            (True, "profile_quality_passed"), profile_quality_decision(metadata)
        )

        for state in ("candidate", "rejected", "superseded"):
            with self.subTest(state=state):
                changed = {**metadata, "profile_state": state}
                self.assertEqual(
                    (False, f"profile_state_{state}"), profile_quality_decision(changed)
                )
        self.assertEqual(
            (True, "profile_quality_passed"),
            profile_quality_decision(
                {**metadata, "profile_state": "candidate"}, require_active=False
            ),
        )
        pending = {**metadata, "profile_state": "pending"}
        self.assertEqual(
            (False, "profile_state_pending"), profile_quality_decision(pending)
        )
        low_quality = {**metadata, "extraction_quality_score": 0.3}
        self.assertEqual(
            (False, "profile_quality_rejected"), profile_quality_decision(low_quality)
        )
        for score in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(score=score):
                self.assertEqual(
                    (False, "profile_quality_rejected"),
                    profile_quality_decision(
                        {**metadata, "extraction_quality_score": score}
                    ),
                )
        self.assertEqual(
            (True, "profile_quality_compatible"),
            profile_quality_decision(
                {"memory_type": "user_profile", "metadata": {"tool": "remember"}}
            ),
        )
        self.assertEqual(
            (True, "profile_quality_compatible"),
            profile_quality_decision(
                {
                    "memory_type": "user_profile",
                    "metadata": {
                        "tool": "remember",
                        "profile_dimension": "preferred_address",
                        "profile_value": "阿岚",
                        "normalized_value": "阿岚",
                        "profile_state": "active",
                        "extraction_quality_score": 0.1,
                    },
                }
            ),
        )
        self.assertEqual(
            (True, "profile_quality_compatible"),
            profile_quality_decision(
                {"memory_type": "explicit_memory", "metadata": {"extractor": "rule_v2"}}
            ),
        )


class PortraitEvidenceNoiseTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_text_does_not_enter_portrait_evidence(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = MemoryStore(Path(temp.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        service = PortraitService(store, _Config())
        dto = build_profile_dto(
            person_ref=PERSON_REF,
            capability_summary={
                "private_companion_enabled": True,
                "proactive_private_enabled": False,
                "portrait_mode": "learn_and_use",
                "grant_source": "administrator",
            },
        )
        event = types.SimpleNamespace(private_companion_unified_profile_context=dto)

        result = await service.capture_user_message(
            context("老板娘叫我去跟车呢"), event=event
        )

        self.assertTrue(result["ok"])
        self.assertEqual("portrait_no_candidate", result["code"])
        self.assertEqual(
            [], await store.list_portrait_evidence(PERSON_REF["person_id"])
        )


if __name__ == "__main__":
    unittest.main()
