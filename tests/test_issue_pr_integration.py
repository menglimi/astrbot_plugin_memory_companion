from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.assertions import (
    assertion_is_promotable, claim_is_personal_fact, normalize_assertion,
)
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer


class IssuePRIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        service = MemoryCompanionService(
            context=None, config={}, plugin_root=ROOT, data_dir=Path(directory.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def ctx():
        return SessionContext(
            session_id="qq:FriendMessage:u1", scope="private", platform="qq",
            user_id="u1", user_name="小林", bot_id="b1",
        )

    @staticmethod
    def claim(value, ref, *, subject="u1", dimension="habit", durability="stable"):
        return normalize_assertion({
            "subject": subject, "predicate": dimension, "value": value,
            "refs": [ref], "durability": durability, "polarity": "positive",
        })

    @staticmethod
    def row(value, ref, actor="u1"):
        return {"id": ref, "content": value, "subject_id": actor, "event_type": "user_message"}

    async def test_group_assertions_keep_each_cited_speaker(self):
        service = self.make_service()
        ctx = replace(self.ctx(), scope="group", session_id="qq:GroupMessage:g1", group_id="g1", user_id="trigger")
        rows = [self.row("我喜欢喝冰美式", "e1", "u1"), self.row("我喜欢喝冰美式", "e2", "u2")]
        raw = [self.claim("喜欢喝冰美式", "e1"), self.claim("喜欢喝冰美式", "e2", subject="u2")]
        assertions, _ = MemorySummarizer._normalize_assertions(raw, rows)
        self.assertEqual(2, len(assertions))
        ids = await service._persist_assertions(ctx, {"assertions": assertions}, "summary", rows)
        records = [await service.store.get_memory(memory_id) for memory_id in ids]
        self.assertEqual({"u1", "u2"}, {record.subject.id for record in records})
        self.assertTrue(all(record.review_status != "pending" for record in records))

    async def test_assertion_ids_and_merges_are_scoped_by_bot(self):
        service = self.make_service()
        value = "睡觉必须开着白噪音"
        payload = {"assertions": [self.claim(value, "e1")]}
        first = await service._persist_assertions(self.ctx(), payload, "summary", [self.row(value, "e1")])
        second = await service._persist_assertions(replace(self.ctx(), bot_id="b2"), payload, "summary", [self.row(value, "e1")])
        self.assertNotEqual(first, second)
        first_record = await service.store.get_memory(first[0])
        self.assertEqual("b1", first_record.owner_bot_id)
        self.assertEqual(2, (await service.store.stats())["total_memories"])

    async def test_uncertain_new_residence_does_not_replace_an_accepted_value(self):
        service = self.make_service()
        async def persist(value, ref, evidence, durability="stable"):
            return await service._persist_assertions(
                self.ctx(), {"assertions": [self.claim(value, ref, dimension="residence", durability=durability)]},
                "summary-" + ref, [self.row(evidence, ref)],
            )
        old = await persist("住在上海", "e1", "我住在上海")
        candidate = await persist("住在北京", "e2", "我打算住在北京", "situational")
        self.assertEqual("stable_memory", (await service.store.get_memory(old[0])).lifecycle)
        self.assertEqual("pending", (await service.store.get_memory(candidate[0])).review_status)
        confirmed = await persist("住在北京", "e3", "我现在住在北京")
        self.assertEqual(candidate, confirmed)
        self.assertEqual("stable_memory", (await service.store.get_memory(confirmed[0])).lifecycle)
        self.assertEqual("superseded", (await service.store.get_memory(old[0])).validity_status)

    async def test_missing_or_foreign_citations_cannot_be_promoted(self):
        service = self.make_service()
        claim = self.claim("睡觉必须开着白噪音", "missing")
        ids = await service._persist_assertions(self.ctx(), {"assertions": [claim]}, "s1", [])
        self.assertEqual([], ids)
        claim = self.claim("睡觉必须开着白噪音", "e1", subject="someone-else")
        ids = await service._persist_assertions(self.ctx(), {"assertions": [claim]}, "s2", [self.row(claim["value"], "e1")])
        self.assertEqual([], ids)

    async def test_assertion_database_write_runs_off_the_event_loop(self):
        service = self.make_service()
        threads = []
        original = service.store._upsert_assertion_sync
        def observe(record):
            threads.append(threading.current_thread().name)
            return original(record)
        value = "睡觉必须开着白噪音"
        with patch.object(service.store, "_upsert_assertion_sync", side_effect=observe):
            await service._persist_assertions(self.ctx(), {"assertions": [self.claim(value, "e1")]}, "s", [self.row(value, "e1")])
        self.assertEqual(1, len(threads))
        self.assertNotEqual(threading.current_thread().name, threads[0])

    async def test_time_window_finds_offset_event_even_when_ingestion_is_later(self):
        service = self.make_service()
        record = MemoryRecord(
            id="backfill", memory_type="conversation_summary", subject=EntityRef(kind="user", id="u1"),
            scope="private", session_id=self.ctx().session_id, platform="qq", visibility="private_pair",
            lifecycle="stable_memory", content="回填的历史事件", occurred_at="2026-08-27T21:56:12+08:00",
            created_at="2026-09-01T00:00:00+00:00", updated_at="2026-09-01T00:00:00+00:00",
        )
        await service.store.insert_memory(record)
        rows = service.store._time_window_candidate_rows(
            service.store._conn, "2026-08-27T13:30:00+00:00", "2026-08-27T14:30:00+00:00", 10, False,
        )
        self.assertEqual(["backfill"], [row["id"] for row in rows])

    def test_unrelated_plan_does_not_disqualify_a_sourced_habit(self):
        ok, reason = claim_is_personal_fact("u1", "睡觉必须开着白噪音", ["今天有点累，打算周末去玩；我睡觉必须开着白噪音"])
        self.assertTrue(ok, reason)

    def test_durability_is_not_invented_and_residence_is_not_a_name(self):
        assertion = normalize_assertion({"subject": "u1", "predicate": "home", "value": "住在上海", "refs": ["e1"]})
        self.assertEqual("residence", assertion["dimension"])
        self.assertEqual("situational", assertion["durability"])
        self.assertFalse(assertion_is_promotable(assertion, ["我住在上海"]))

    def test_following_negation_does_not_change_the_preceding_preference(self):
        row = self.row("我最喜欢喝冰美式 不加糖", "e1")
        verdict, reason = MemorySummarizer.citation_check("喜欢喝冰美式且不加糖", [row])
        self.assertEqual("supported", verdict, reason)
        verdict, _ = MemorySummarizer.citation_check("喜欢喝冰美式", [self.row("我不喜欢喝冰美式", "e2")])
        self.assertEqual("conflicted", verdict)


if __name__ == "__main__":
    unittest.main()
