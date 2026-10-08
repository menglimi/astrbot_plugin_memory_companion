from __future__ import annotations

import unittest

from core.chat_import import HistoricalChatSegmenter, OPENING_MARKERS
from core.portrait import classify_sensitivity, extract_explicit_candidates
from core.profile_quality import extract_profile_candidates
from core.turn_signal import analyze_turn_signal


class Issue43RegressionTests(unittest.TestCase):
    def test_common_words_containing_single_character_sensitive_terms_stay_low(self) -> None:
        for text in ("他的性格很开朗", "这个属性值偏高", "性能不错", "性格测试"):
            with self.subTest(text=text):
                self.assertEqual("low", classify_sensitivity(text))

    def test_explicit_health_and_sexual_sensitivity_terms_remain_high(self) -> None:
        for text in ("有过敏史", "最近生病了", "有相关病史", "咨询性取向", "性生活健康"):
            with self.subTest(text=text):
                self.assertEqual("high", classify_sensitivity(text))

    def test_agreement_is_not_a_correction(self) -> None:
        self.assertEqual("reaction", analyze_turn_signal("没错").kind)
        self.assertEqual("correction", analyze_turn_signal("不对").kind)

    def test_single_character_morning_marker_does_not_split_unrelated_text(self) -> None:
        for text in ("早点睡", "早就说过了", "早上那场"):
            with self.subTest(text=text):
                self.assertFalse(HistoricalChatSegmenter._has_marker(text, OPENING_MARKERS))
        self.assertTrue(HistoricalChatSegmenter._has_marker("早安", OPENING_MARKERS))

    def test_second_person_address_is_not_saved_as_user_preference(self) -> None:
        for text in ("我喜欢你", "我喜欢您", "我喜欢你呀", "我喜欢 you"):
            with self.subTest(text=text):
                self.assertEqual([], extract_profile_candidates(text))
                self.assertEqual([], extract_explicit_candidates(text))


if __name__ == "__main__":
    unittest.main()
