from __future__ import annotations

import unittest
from pathlib import Path


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import MemoryRecord, EntityRef
from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer
from astrbot_plugin_memory_companion.core.store import MemoryStore


class CitationGateTests(unittest.TestCase):
    """A claim the plugin's own prompt produces must survive its own gate.

    Rule 8 tells the model to write "YYYY-MM-DD 晚上", and
    ``_normalize_relative_time_mentions`` mints the same expression out of the
    rows' timestamps.  The temporal check used to demand the time-of-day word
    from the message body, so obeying the prompt failed validation.
    """

    @staticmethod
    def row(content: str, hour: int) -> dict:
        return {
            "id": "event-1",
            "content": content,
            "occurred_at": f"2026-10-03T{hour:02d}:30:00+08:00",
        }

    def test_time_of_day_claim_needs_no_literal_word_in_the_message(self) -> None:
        rows = [self.row("naliling 我今天真的好累啊 加班到现在才吃上饭", 20)]
        self.assertEqual(
            "supported",
            MemorySummarizer.citation_check(
                "2026-10-03 晚上 naliling 说加班到现在才吃上饭", rows
            )[0],
        )

    def test_time_of_day_contradicted_by_the_row_timestamp_is_still_rejected(self) -> None:
        rows = [self.row("naliling 我今天真的好累啊 加班到现在才吃上饭", 11)]
        self.assertEqual(
            "unsupported",
            MemorySummarizer.citation_check(
                "2026-10-03 凌晨 naliling 说加班到现在才吃上饭", rows
            )[0],
        )

    def test_paraphrase_that_drops_a_negation_is_not_a_contradiction(self) -> None:
        """The old check compared one negation boolean for the whole batch.

        Rewriting "不想去上班" as "很抗拒去上班" is a faithful paraphrase, but a
        batch-wide negation boolean saw 不 in the evidence and 不 in no part of
        the claim, and rejected it.
        """
        rows = [
            {"id": "event-1", "content": "naliling 明天还要早起 真的不想去上班",
             "occurred_at": "2026-10-03T11:25:00+08:00"},
            # An unrelated negation elsewhere in the batch must not matter.
            {"id": "event-2", "content": "naliling 我不吃香菜 一点点都不行",
             "occurred_at": "2026-10-03T11:26:00+08:00"},
        ]
        self.assertEqual(
            "supported",
            MemorySummarizer.citation_check("naliling 提到明天要早起，很抗拒去上班", rows)[0],
        )

    def test_date_outside_the_rows_is_still_rejected(self) -> None:
        rows = [self.row("今天中午小王喝了无糖拿铁。", 12)]
        self.assertFalse(
            MemorySummarizer.fact_supported_by_rows("2026-08-01 中午小王喝了无糖拿铁", rows)
        )

    def test_fabrication_without_any_lexical_ground_is_rejected(self) -> None:
        rows = [self.row("naliling 我今天真的好累啊 加班到现在才吃上饭", 11)]
        self.assertEqual(
            "unsupported",
            MemorySummarizer.citation_check("naliling 说自己养了三只仓鼠", rows)[0],
        )

    def test_unreferenced_fact_is_attributed_to_the_matching_message(self) -> None:
        summarizer = MemorySummarizer()
        traced, warnings, errors = summarizer._normalize_key_facts_with_validation(
            ["小王喜欢无糖拿铁"],
            [{"id": "event-1", "content": "小王喜欢无糖拿铁。"}],
        )
        self.assertEqual([{"fact": "小王喜欢无糖拿铁", "refs": ["event-1"], "evidence": [{"ref": "event-1", "quote": "小王喜欢无糖拿铁"}]}], traced)
        self.assertEqual([], errors)


class PendingCandidateRetentionTests(unittest.IsolatedAsyncioTestCase):
    """A candidate that is never reviewed must not live forever.

    Every recall query filters ``review_status!='pending'`` and the decay pool
    used to filter it out too, so nothing could ever resolve these rows.
    """

    async def asyncSetUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name) / "test.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    @staticmethod
    def record(memory_id: str, *, lifecycle: str, review_status: str) -> MemoryRecord:
        return MemoryRecord(
            id=memory_id,
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="小王"),
            object=EntityRef.bot_self(bot_id="b1"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            platform="qq",
            visibility="private_pair",
            lifecycle=lifecycle,
            content="小王聊了无糖拿铁",
            evidence="小王喜欢无糖拿铁",
            review_status=review_status,
            owner_bot_id="b1",
            occurred_at="2026-01-01T00:00:00+00:00",
        )

    async def test_pending_candidate_is_reachable_by_the_decay_pool(self) -> None:
        await self.store.insert_memory(
            self.record("mem-pending", lifecycle="short_term_candidate", review_status="pending")
        )
        stable = self.record("mem-stable", lifecycle="stable_memory", review_status="auto")
        stable.content = "小王说项目最后没做成"
        await self.store.insert_memory(stable)
        pool = await self.store.list_decay_candidate_pool(limit=10)
        self.assertEqual({"mem-pending", "mem-stable"}, {item.id for item in pool})

    async def test_stale_pending_candidate_is_archived_and_leaves_the_queue(self) -> None:
        await self.store.insert_memory(
            self.record("mem-pending", lifecycle="short_term_candidate", review_status="pending")
        )
        archived = await self.store.archive_stale_pending_memories("2026-06-01T00:00:00+00:00")
        self.assertEqual(1, archived)
        record = await self.store.get_memory("mem-pending")
        self.assertEqual("archived", record.lifecycle)
        queue = await self.store.list_review_queue(limit=10)
        self.assertEqual([], [item for item in queue if item["status"] == "pending"])
        # A fresh candidate is left alone.
        fresh = self.record("mem-fresh", lifecycle="short_term_candidate", review_status="pending")
        fresh.content = "小王最近在住院"
        await self.store.insert_memory(fresh)
        self.assertEqual(
            0, await self.store.archive_stale_pending_memories("2020-01-01T00:00:00+00:00")
        )


class UnsummarizedTimelineRetentionTests(unittest.IsolatedAsyncioTestCase):
    """Rows that never became a memory were outside the timeline cleanup."""

    async def asyncSetUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name) / "test.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def test_unsummarized_rows_are_kept_until_the_cutoff_is_set(self) -> None:
        old = await self.store.add_timeline_event(
            event_type="user_message", session_id="qq:FriendMessage:u1", scope="private",
            subject_id="u1", object_id="b1", content="很久以前的一条消息",
            occurred_at="2026-01-01T00:00:00+00:00")
        result = await self.store.prune_retained_rows(
            summarized_timeline_cutoff="2026-06-01T00:00:00+00:00")
        self.assertEqual(0, result["timeline"])
        self.assertTrue(await self.store.get_timeline_by_ids([old]))

    async def test_unsummarized_rows_are_pruned_once_the_cutoff_is_set(self) -> None:
        old = await self.store.add_timeline_event(
            event_type="user_message", session_id="qq:FriendMessage:u1", scope="private",
            subject_id="u1", object_id="b1", content="很久以前的一条消息",
            occurred_at="2026-01-01T00:00:00+00:00")
        result = await self.store.prune_retained_rows(
            unsummarized_timeline_cutoff="2026-06-01T00:00:00+00:00")
        self.assertEqual(1, result["timeline"])
        self.assertFalse(await self.store.get_timeline_by_ids([old]))

    async def test_events_owned_by_a_batch_are_never_pruned(self) -> None:
        old = await self.store.add_timeline_event(
            event_type="user_message", session_id="qq:FriendMessage:u1", scope="private",
            subject_id="u1", object_id="b1", content="还在等总结的消息",
            occurred_at="2026-01-01T00:00:00+00:00")
        rows = list((await self.store.get_timeline_by_ids([old])).values())
        await self.store.create_summary_batch("qq:FriendMessage:u1", "private", rows)
        result = await self.store.prune_retained_rows(
            unsummarized_timeline_cutoff="2026-06-01T00:00:00+00:00")
        self.assertEqual(0, result["timeline"])
        self.assertTrue(await self.store.get_timeline_by_ids([old]))


if __name__ == "__main__":
    unittest.main()