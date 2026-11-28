from __future__ import annotations

import unittest

from core.classifier import MemoryClassifier
from core.models import SessionContext
from core.profile_quality import (
    extract_profile_candidates,
    normalize_profile_value,
    profile_candidate_metadata,
    profile_quality_activation_check,
    profile_quality_decision,
    profile_quality_gate_passed,
)


_EDUCATION_TERMS = {
    "博士后",
    "博士研究生",
    "博士生",
    "博士",
    "硕士研究生",
    "硕士生",
    "硕士",
    "研究生",
    "本科生",
    "大学生",
    "大专生",
    "专科生",
    "中专生",
    "高中生",
    "初中生",
    "小学生",
    "学生",
}


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


def first_candidate(text: str) -> dict:
    candidates = extract_profile_candidates(text)
    if not candidates:
        raise AssertionError(f"expected a profile candidate for {text!r}")
    return candidates[0]


def rule_memory(text: str, *, state: str = "") -> dict:
    candidate = first_candidate(text)
    metadata = profile_candidate_metadata(candidate, source_memory_id="source-1")
    if state:
        metadata["profile_state"] = state
    metadata["extractor"] = "rule_v2"
    return {"memory_type": candidate["memory_type"], "metadata": metadata}


class H9RuleExtractionTests(unittest.TestCase):
    """REPORT line 245: the rule extractor sliced words and over-trusted itself."""

    def test_full_word_education_terms_are_kept_whole(self) -> None:
        cases = {
            "我是学生": "学生",
            "我是大学生": "大学生",
            "我是一名研究生": "研究生",
            "我是个博士生": "博士生",
            "我在读大学": "大学生",
            "我在读研究生": "研究生",
            "我的专业是计算机": "计算机",
            "我是计算机专业的": "计算机",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                candidate = first_candidate(text)
                self.assertEqual("education", candidate["profile_dimension"])
                self.assertEqual(expected, candidate["profile_value"])
                # A clean direct statement: explicit, 0.9, active, gate passed.
                self.assertEqual("explicit", candidate["extraction_quality"])
                self.assertEqual("active", candidate["profile_state"])
                self.assertGreaterEqual(candidate["extraction_quality_score"], 0.9)
                self.assertTrue(candidate["quality_gate_passed"])

    def test_education_never_slices_the_student_character(self) -> None:
        for text in ("我是学生", "我是研究生", "我是大学生"):
            with self.subTest(text=text):
                values = [
                    candidate["profile_value"]
                    for candidate in extract_profile_candidates(text)
                ]
                self.assertNotIn("生", values)
                self.assertTrue(all(value in _EDUCATION_TERMS for value in values))

    def test_ambiguous_or_unclean_education_is_dropped(self) -> None:
        for text in (
            "我在学计算机",
            "我是学",
            "我是在读",
            "我的专业是",
            "我是学生吗",
            "我的专业是什么",
        ):
            with self.subTest(text=text):
                self.assertEqual([], extract_profile_candidates(text))

    def test_fuzzy_education_major_is_candidate_not_stable(self) -> None:
        candidate = first_candidate("我是学计算机的")
        self.assertEqual("education", candidate["profile_dimension"])
        self.assertEqual("计算机", candidate["profile_value"])
        self.assertEqual("candidate", candidate["profile_state"])
        self.assertEqual("inferred", candidate["extraction_quality"])
        self.assertGreaterEqual(candidate["extraction_quality_score"], 0.5)
        self.assertLess(candidate["extraction_quality_score"], 0.75)

    def test_like_person_takes_the_person_not_the_tail(self) -> None:
        cases = {
            "我喜欢的人是周杰伦": "周杰伦",
            "我最喜欢的人是周杰伦": "周杰伦",
            "我喜欢的人叫林俊杰": "林俊杰",
            "我喜欢的人就是她": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                candidates = extract_profile_candidates(text)
                if expected is None:
                    self.assertEqual([], candidates)
                    continue
                self.assertEqual(1, len(candidates))
                candidate = candidates[0]
                self.assertEqual("preference", candidate["profile_dimension"])
                self.assertEqual("like", candidate["kind"])
                self.assertEqual(expected, candidate["profile_value"])
                self.assertEqual("active", candidate["profile_state"])
                self.assertGreaterEqual(candidate["extraction_quality_score"], 0.9)

    def test_like_object_is_cleaned_of_the_tail(self) -> None:
        cases = {
            "我喜欢的是烤肉": ("烤肉", "active", "explicit"),
            "我喜欢烤肉": ("烤肉", "active", "explicit"),
            "我喜欢吃苹果": ("苹果", "candidate", "inferred"),
            "我喜欢酒吧": ("酒吧", "active", "explicit"),
            "我喜欢烤肉吧": ("烤肉", "active", "explicit"),
        }
        for text, (expected, state, quality) in cases.items():
            with self.subTest(text=text):
                candidate = first_candidate(text)
                self.assertEqual(expected, candidate["profile_value"])
                self.assertEqual(state, candidate["profile_state"])
                self.assertEqual(quality, candidate["extraction_quality"])

    def test_unclean_like_tails_are_dropped(self) -> None:
        for text in (
            "我喜欢的人不是他",
            "我不喜欢的人是张三",
            "我喜欢的人是",
            "我喜欢的人是?",
        ):
            with self.subTest(text=text):
                self.assertEqual([], extract_profile_candidates(text))

    def test_english_sentences_are_not_force_sliced(self) -> None:
        # The rule table is Chinese-only; English input must stay untouched
        # rather than producing a sliced half-word profile.
        for text in (
            "I am a student",
            "I am a college student",
            "I like Jay Chou",
            "My major is computer science",
        ):
            with self.subTest(text=text):
                self.assertEqual([], extract_profile_candidates(text))

    def test_fuzzy_candidates_never_become_stable_memory(self) -> None:
        classifier = MemoryClassifier()
        for text in ("我是学计算机的", "我喜欢吃苹果", "我是学生物的"):
            with self.subTest(text=text):
                records = classifier.derived_user_memories(
                    context(text), source_memory_id="source-1"
                )
                self.assertTrue(records)
                for record in records:
                    self.assertEqual("candidate", record.metadata["profile_state"])
                    self.assertNotEqual("stable_memory", record.lifecycle)
                    self.assertEqual("pending", record.review_status)

    def test_clean_candidates_stay_active_and_stable(self) -> None:
        classifier = MemoryClassifier()
        records = classifier.derived_user_memories(
            context("我是学生"), source_memory_id="source-1"
        )
        self.assertEqual(1, len(records))
        self.assertEqual("active", records[0].metadata["profile_state"])
        self.assertEqual("stable_memory", records[0].lifecycle)
        self.assertEqual("auto", records[0].review_status)


class H8QualityGateTests(unittest.TestCase):
    """REPORT line 244: quality_gate_passed was a constant and state was faked."""

    def test_quality_gate_passed_is_computed_by_the_candidate(self) -> None:
        candidate = first_candidate("我是学生")
        self.assertTrue(candidate["quality_gate_passed"])
        self.assertEqual(
            (True, "profile_quality_passed"),
            profile_quality_decision(candidate),
        )

    def test_forged_quality_gate_flag_cannot_pass_the_real_checks(self) -> None:
        metadata = rule_memory("我是学生")["metadata"]
        self.assertTrue(metadata["quality_gate_passed"])

        forged = {**metadata, "quality_gate_passed": True, "profile_state": "candidate"}
        self.assertEqual(
            (False, "profile_state_candidate"),
            profile_quality_decision(forged),
        )

        forged = {**metadata, "quality_gate_passed": True, "extraction_quality_score": 0.3}
        self.assertEqual(
            (False, "profile_quality_rejected"),
            profile_quality_decision(forged),
        )

        forged = {**metadata, "quality_gate_passed": True, "profile_dimension": ""}
        self.assertEqual(
            (False, "profile_dimension_missing"),
            profile_quality_decision(forged),
        )

        forged = {**metadata, "quality_gate_passed": True, "profile_value": ""}
        self.assertEqual(
            (False, "profile_value_missing"),
            profile_quality_decision(forged),
        )

        forged = {**metadata, "quality_gate_passed": True, "normalized_value": "别的值"}
        self.assertEqual(
            (False, "profile_normalized_value_mismatch"),
            profile_quality_decision(forged),
        )

        forged = {**metadata, "quality_gate_passed": True, "profile_conflict": True}
        self.assertEqual(
            (False, "profile_conflict"),
            profile_quality_decision(forged),
        )

        for score in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(score=score):
                self.assertEqual(
                    (False, "profile_quality_rejected"),
                    profile_quality_decision(
                        {**metadata, "quality_gate_passed": True, "extraction_quality_score": score}
                    ),
                )

    def test_profile_candidate_metadata_recomputes_the_flag(self) -> None:
        valid = first_candidate("我是学生")
        forged_low = {**valid, "quality_gate_passed": False, "extraction_quality_score": 0.3}
        metadata = profile_candidate_metadata(forged_low)
        self.assertFalse(metadata["quality_gate_passed"])

        forged_high = {**valid, "quality_gate_passed": False}
        metadata = profile_candidate_metadata(forged_high)
        self.assertTrue(metadata["quality_gate_passed"])

        forged_claim = {**valid, "quality_gate_passed": True, "profile_state": "candidate"}
        metadata = profile_candidate_metadata(forged_claim)
        # A candidate may pass the candidate-level gate, but the state is kept
        # as candidate rather than forged into active.
        self.assertEqual("candidate", metadata["profile_state"])
        self.assertTrue(metadata["quality_gate_passed"])
        self.assertEqual(
            (False, "profile_state_candidate"),
            profile_quality_decision(metadata),
        )

    def test_activation_check_reads_the_real_state(self) -> None:
        metadata = rule_memory("我是学生")["metadata"]
        self.assertEqual(
            (True, "profile_quality_passed"),
            profile_quality_activation_check(metadata),
        )

        candidate = {**metadata, "profile_state": "candidate"}
        self.assertEqual(
            (True, "profile_quality_passed"),
            profile_quality_activation_check(candidate),
        )

        for state in ("rejected", "superseded", "archived", "pending"):
            with self.subTest(state=state):
                self.assertEqual(
                    (False, f"profile_state_{state}"),
                    profile_quality_activation_check({**metadata, "profile_state": state}),
                )

        missing = {key: value for key, value in metadata.items() if key != "profile_state"}
        missing["status"] = ""
        self.assertEqual(
            (False, "profile_state_missing"),
            profile_quality_activation_check(missing),
        )

    def test_boolean_wrapper_matches_the_decision(self) -> None:
        self.assertTrue(profile_quality_gate_passed(rule_memory("我是学生")))
        self.assertFalse(
            profile_quality_gate_passed(
                {**rule_memory("我是学生"), "metadata": {**rule_memory("我是学生")["metadata"], "extraction_quality_score": 0.2}}
            )
        )
        # Non-rule memories stay compatible.
        self.assertTrue(profile_quality_gate_passed({"memory_type": "explicit_memory", "metadata": {}}))

    def test_normalized_value_matches_the_clean_value(self) -> None:
        candidate = first_candidate("我喜欢的人是周杰伦")
        self.assertEqual(
            normalize_profile_value(candidate["profile_value"]),
            candidate["normalized_value"],
        )


if __name__ == "__main__":
    unittest.main()
