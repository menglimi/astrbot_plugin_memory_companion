from __future__ import annotations

import unittest


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer


def _row(event_id: str, content: str, occurred_at: str) -> dict:
    """合成消息行：content 是对话正文，occurred_at 是该条消息自身的绝对时间。"""
    return {
        "id": event_id,
        "event_type": "user_message",
        "scope": "private",
        "subject_id": "u1",
        "content": content,
        "occurred_at": occurred_at,
    }


class SummaryEvidenceClaimTests(unittest.TestCase):
    """断言级证据校验：绝对时间只认消息自身的时间戳，极性只认被照抄的那一句。

    设计来源：docs/MEMORY_PRECISION_REVIEW_20260906.md 的 M-02（错误断言不能仅凭
    词语重合通过证据验证）。本文件同时守护「反例必须被拒」与「带绝对时间的正常断言
    不能被误杀」两个方向；用例均为合成数据。
    """

    # 合成批次：2026-07-15 是周三；tl_demo_evening 本地 22:27，tl_demo_morning 本地 08:42
    @staticmethod
    def rows() -> list[dict]:
        return [
            _row("tl_demo_dentist", "小林预约周三下午三点看牙医", "2026-07-15T07:00:00+00:00"),
            _row("tl_demo_coriander", "小林不喜欢香菜", "2026-07-15T07:05:00+00:00"),
            _row("tl_demo_evening", "我不想研究这个方案了", "2026-07-15T14:27:30+00:00"),
            _row("tl_demo_morning", "我醒啦，闹钟响了三次", "2026-07-16T00:42:52+00:00"),
        ]

    def test_absolute_date_and_period_are_proved_by_message_timestamps(self) -> None:
        """正文里没有日期串，但提示词要求断言写绝对时间：日期必须由时间戳证明。"""
        rows = self.rows()
        claim = "2026-07-15 晚上，小林说不想研究这个方案，我在旁边听着。"
        self.assertTrue(MemorySummarizer.fact_supported_by_rows(claim, [rows[2]]))
        self.assertTrue(MemorySummarizer.fact_supported_by_rows(claim, rows))

    def test_wrong_date_is_rejected(self) -> None:
        rows = self.rows()
        claim = "2026-07-14 晚上，小林说不想研究这个方案，我在旁边听着。"
        self.assertFalse(MemorySummarizer.fact_supported_by_rows(claim, [rows[2]]))

    def test_date_mentioned_in_message_text_is_supported(self) -> None:
        """正文里被讨论的日期（计划/新闻/约定）是有依据的，不能被判无依据。"""
        rows = [
            _row(
                "tl_demo_news",
                "小林说他关注的新作 2027/6/5 才上架，先加了愿望单",
                "2026-07-15T07:10:00+00:00",
            )
        ]
        # 同一日期的不同写法（2027/6/5 ↔ 2027-06-05）必须互相认账
        self.assertTrue(
            MemorySummarizer.fact_supported_by_rows("小林关注的新作 2027-06-05 才上架。", rows)
        )
        # 证据里没有的日期 → 仍然拒
        self.assertFalse(
            MemorySummarizer.fact_supported_by_rows("小林关注的新作 2028-01-09 才上架。", rows)
        )

    def test_slash_date_in_message_text_supports_iso_claim(self) -> None:
        """回归：正文写 8/22、断言写 2026年8月22日（真实批次里被判无依据的那种）。"""
        rows = [
            _row("tl_demo_slash", "小林说 8/22 第一杯、8/28 第二杯都是他调的", "2026-08-24T02:00:00+00:00")
        ]
        claim = "「特调」是 2026年8月22 第一杯、8月28日第二杯都由小林亲手调。"
        self.assertTrue(MemorySummarizer.fact_supported_by_rows(claim, rows))

    def test_relative_time_hint_relaxes_date_check(self) -> None:
        """正文说「明天/明年/月底」时，断言里的绝对日期是换算出来的 → 不判矛盾。"""
        rows = [_row("tl_demo_tomorrow", "小林说明天要去复诊", "2026-07-15T07:00:00+00:00")]
        claim = "小林 2026-07-16 要去复诊。"
        self.assertTrue(MemorySummarizer.fact_supported_by_rows(claim, rows))

    def test_period_and_clock_alone_do_not_reject(self) -> None:
        """时段/钟点不参与拒绝（转述里常跨事件漂移，且不构成硬事实）；只有日期/周几才拒。"""
        rows = self.rows()  # tl_demo_evening 本地时间 22:27
        self.assertTrue(MemorySummarizer.fact_supported_by_rows("2026-07-15 22点不想研究方案", [rows[2]]))
        self.assertTrue(MemorySummarizer.fact_supported_by_rows("2026-07-15 23点不想研究方案", [rows[2]]))

    def test_weekday_flip_is_rejected(self) -> None:
        """M-02 的时间反例：证据是周三下午三点，断言改成周五下午五点。"""
        rows = self.rows()
        self.assertTrue(MemorySummarizer.fact_supported_by_rows("小林预约周三下午三点看牙医", [rows[0]]))
        self.assertFalse(MemorySummarizer.fact_supported_by_rows("小林预约周五下午五点看牙医", [rows[0]]))

    def test_polarity_flip_is_rejected_but_restatement_is_supported(self) -> None:
        """M-02 的极性反例：证据是否定，断言写肯定。"""
        rows = self.rows()
        self.assertTrue(MemorySummarizer.fact_supported_by_rows("小林不喜欢香菜", [rows[1]]))
        self.assertFalse(MemorySummarizer.fact_supported_by_rows("小林喜欢香菜", [rows[1]]))

    def test_long_paraphrase_is_not_rejected_by_unrelated_negation(self) -> None:
        """回归：证据段落里出现「不」（不想研究）不再否证一条跨事件的转述式断言。"""
        rows = self.rows()
        claim = "小林在 2026-07-15 晚上说不想研究这个方案，第二天 2026-07-16 早上说闹钟响了三次"
        self.assertTrue(MemorySummarizer.fact_supported_by_rows(claim, rows))

    def test_normalize_payload_keeps_date_bearing_fact_and_explains_drop(self) -> None:
        rows = self.rows()
        summarizer = MemorySummarizer()
        payload = {
            "outcome": "memory",
            "summary": "2026-07-15 晚上，我陪着小林把不想研究的方案先放一放。",
            "summary_refs": ["tl_demo_evening"],
            "canonical_summary": "2026-07-15 晚上小林不想研究方案。",
            "topics": ["闲聊"],
            "key_facts": [
                {"fact": "2026-07-15 晚上小林说不想研究这个方案。", "refs": ["tl_demo_evening"]},
                {"fact": "2026-07-14 晚上小林说不想研究这个方案。", "refs": ["tl_demo_evening"]},
            ],
            "importance": 0.7,
            "sentiment": "neutral",
        }
        normalized = summarizer._normalize_payload(payload, rows)
        self.assertEqual(
            ["2026-07-15 晚上小林说不想研究这个方案。"],
            normalized["key_facts"],
        )
        errors = normalized["_validation_errors"]
        self.assertTrue(any("2026-07-14" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
