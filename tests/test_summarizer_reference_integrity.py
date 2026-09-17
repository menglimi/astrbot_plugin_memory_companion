from __future__ import annotations

import json
import unittest


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer


class _Response:
    def __init__(self, text: str):
        self.completion_text = text


class _StaticProvider:
    def __init__(self, payload: dict):
        self.payload = payload

    async def text_chat(self, **kwargs):
        return _Response(json.dumps(self.payload, ensure_ascii=False))


class SummarizerReferenceIntegrityTests(unittest.IsolatedAsyncioTestCase):
    """Regression coverage for the reference-shape defects of 解决方案输出.md §6.8.

    Both cases below produced a *false* validation failure: the batch was
    correct, but the same fact or the same event_id was compared through two
    different representations inside one payload.
    """

    @staticmethod
    def rows() -> list[dict]:
        return [
            {
                "id": "event-1",
                "event_type": "user_message",
                "scope": "private",
                "subject_id": "u1",
                "content": "2026-07-15 中午小王喝了无糖拿铁。",
                "occurred_at": "2026-07-15T12:00:00+08:00",
            }
        ]

    async def _normalize(self, payload: dict) -> dict:
        summarizer = MemorySummarizer(provider_timeout_seconds=1)
        result = await summarizer.summarize_with_provider(
            _StaticProvider(payload),
            rows=self.rows(),
            session_label="私聊 小王",
        )
        assert result is not None
        return result

    async def test_duplicate_key_facts_do_not_report_missing_references(self) -> None:
        """§6.8-1: a repeated fact must not make the traced list longer than the fact list.

        ``validation_errors`` compares ``len(key_facts_with_refs)`` with the
        de-duplicated ``key_facts`` list.  When the duplicate entered the traced
        list but not the fact list, every correctly referenced batch that
        happened to repeat a fact was rejected with
        "关键事实缺少有效引用".
        """
        result = await self._normalize(
            {
                "summary": "2026-07-15 中午小王喝了无糖拿铁。",
                "canonical_summary": "小王喝过无糖拿铁。",
                "summary_refs": ["event-1"],
                "key_facts": [
                    {"fact": "小王喝了无糖拿铁", "refs": ["event-1"]},
                    {"fact": "小王喝了无糖拿铁", "refs": ["event-1"]},
                ],
            }
        )

        self.assertEqual(1, len(result.get("key_facts_with_refs") or []))
        self.assertEqual(1, len(result.get("key_facts") or []))
        self.assertNotIn("关键事实缺少有效引用", result.get("_validation_errors") or [])

    def test_absolute_date_claim_is_supported_by_relative_wording(self) -> None:
        """§6.4/§6.7 修复 4: the temporal check must share the normalization's date vocabulary.

        The prompt forbids relative time words and demands "YYYY-MM-DD 中午",
        while ``_normalize_relative_time_mentions`` derives that date from the
        rows' own timestamps.  The temporal check compared the claim against the
        raw message bodies only, so obeying the prompt was itself the failure.
        """
        rows = [
            {
                "id": "event-1",
                "event_type": "user_message",
                "scope": "private",
                "subject_id": "u1",
                "content": "今天中午小王喝了无糖拿铁。",
                "occurred_at": "2026-07-15T12:00:00+08:00",
            }
        ]

        self.assertTrue(
            MemorySummarizer.fact_supported_by_rows("2026-07-15 中午小王喝了无糖拿铁", rows)
        )

    def test_absolute_date_absent_from_the_rows_is_still_rejected(self) -> None:
        """The alignment must not degrade into accepting any date at all."""
        rows = [
            {
                "id": "event-1",
                "event_type": "user_message",
                "scope": "private",
                "subject_id": "u1",
                "content": "今天中午小王喝了无糖拿铁。",
                "occurred_at": "2026-07-15T12:00:00+08:00",
            }
        ]

        self.assertFalse(
            MemorySummarizer.fact_supported_by_rows("2026-08-01 中午小王喝了无糖拿铁", rows)
        )

    async def test_summary_refs_are_normalized_like_key_fact_refs(self) -> None:
        """§6.8-4: summary_refs must be normalized with the same helper as key_facts refs.

        ``summary_refs`` was compared as the raw ``str(ref)`` while
        ``key_facts[].refs`` used ``clean_text``.  An event_id that only carried
        surrounding whitespace therefore matched in key_facts but was reported
        as "summary_refs 含本批次不存在的 event_id".
        """
        result = await self._normalize(
            {
                "summary": "2026-07-15 中午小王喝了无糖拿铁。",
                "canonical_summary": "小王喝过无糖拿铁。",
                "summary_refs": ["  event-1  "],
                "key_facts": [{"fact": "小王喝了无糖拿铁", "refs": [" event-1 "]}],
            }
        )

        self.assertEqual(["event-1"], result.get("summary_refs"))
        self.assertNotIn("summary_refs 含本批次不存在的 event_id", result.get("_validation_errors") or [])


if __name__ == "__main__":
    unittest.main()
