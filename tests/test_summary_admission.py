from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.summary_admission import SummaryAdmission
from .test_summary_batch_recovery import Provider


class SummaryAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {"startup": {"background_grace_seconds": 60}, "memory_summary": {
            "min_events": 1, "trigger_event_count": 1, "max_events_per_summary": 1,
            "max_retries": 3, "max_calls_per_session_hour": 6, "max_concurrent_calls": 1,
            "request_max_retries": 1, "retry_backoff_seconds": 0,
        }}
        self.service = MemoryCompanionService(
            context=None, config=self.config, plugin_root=ROOT, data_dir=Path(self.temp.name),
        )
        self.addCleanup(self.service.close)
        self.service._schedule_memory_embedding = lambda *args: None
        self.contexts = []
        self.provider = Provider([])

        async def attempts(ctx):
            self.contexts.append(ctx)
            return [{"provider": self.provider, "provider_id": "fake-summary", "source": "current_session"}]
        self.service._summary_provider_attempts = attempts

    async def batch(self, index=0, *, valid=True):
        identity = {"platform": "qq", "owner_bot_id": "b1", "persona_id": "persona-1", "user_id": "u1"}
        if not valid:
            identity.pop("persona_id")
        event_id = await self.service.store.add_timeline_event(
            event_type="user_message", session_id="qq:FriendMessage:u1", scope="private",
            subject_id="u1", object_id="u1", content=f"只用于恢复测试的无糖拿铁记录 {index}", metadata=identity,
        )
        rows = list((await self.service.store.get_timeline_by_ids([event_id])).values())
        batch_id = await self.service.store.create_summary_batch(
            "qq:FriendMessage:u1", "private", rows, metadata=identity,
        )
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute(
                "UPDATE summary_batches SET created_at=? WHERE id=?", (f"2026-01-01T00:00:{index:02d}+00:00", batch_id),
            )
        self.provider.responses.append({"outcome": "no_memory", "summary_refs": [event_id],
                                        "key_facts": [], "no_memory_reason": "仅有重复确认"})
        return batch_id, event_id

    def ctx(self):
        return SessionContext(session_id="qq:FriendMessage:u1", scope="private", platform="qq",
                              user_id="u1", bot_id="b1", persona_id="persona-1")

    async def test_five_oldest_same_session_only_and_no_fresh_batch(self):
        batches = [await self.batch(i) for i in range(7)]
        await self.service.store.add_timeline_event(
            event_type="user_message", session_id=self.ctx().session_id, scope="private",
            subject_id="u1", object_id="u1", content="新聊天不能挤入试跑", metadata={},
        )
        result = await self.service.run_summary_recovery_trial()
        self.assertEqual("paused", result["mode"])
        self.assertEqual("", result["stop_reason"])
        self.assertEqual([item[0] for item in batches[:5]], [item["id"] for item in result["batches"]])
        self.assertEqual(5, len(self.provider.calls))
        self.assertTrue(all((ctx.bot_id, ctx.user_id, ctx.persona_id) == ("b1", "u1", "persona-1") for ctx in self.contexts))
        rows = self.service.store._conn.execute("SELECT batch_id,automatic FROM summary_batch_calls").fetchall()
        self.assertEqual({item[0] for item in batches[:5]}, {row[0] for row in rows})
        self.assertTrue(all(row[1] == 1 for row in rows))
        self.assertEqual(7, self.service.store._conn.execute("SELECT COUNT(*) FROM summary_batches").fetchone()[0])

    async def test_paused_restart_blocks_ordinary_force_exact_and_scheduler(self):
        batch_id, _ = await self.batch()
        await self.service.pause_summary_admission()
        self.service._summary_admission = SummaryAdmission(self.service._summary_admission.path)
        for kwargs in ({}, {"force": True}, {"recovery_batch_id": batch_id}):
            self.assertEqual("", await self.service.maybe_summarize_session(self.ctx(), **kwargs))
        self.service._schedule_session_summary(self.ctx(), reason="incoming")
        self.service._ensure_summary_recovery_dispatcher()
        self.assertFalse(self.contexts)
        self.assertFalse(self.service._summary_workers)
        self.assertIsNone(self.service._summary_recovery_task)
        self.assertEqual(0, self.service.store._conn.execute("SELECT COUNT(*) FROM summary_batch_calls").fetchone()[0])

    async def test_crashed_trial_restart_does_not_resume_or_allow_exact_manual(self):
        batch_id, _ = await self.batch()
        gate = self.service._summary_admission
        gate.save(mode="trial", batches=[{"id": batch_id}])
        self.service._summary_admission = SummaryAdmission(gate.path)
        self.assertEqual("", await self.service.maybe_summarize_session(self.ctx(), recovery_batch_id=batch_id))
        self.assertEqual("", await self.service.maybe_summarize_session(self.ctx(), force=True))
        self.assertFalse(self.provider.calls)

    async def test_ordinary_and_force_calls_cannot_join_live_trial(self):
        batch_id, _ = await self.batch()
        unrelated, _ = await self.batch(1)
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.provider.text_chat

        async def blocking(**kwargs):
            entered.set()
            await release.wait()
            return await original(**kwargs)
        self.provider.text_chat = blocking
        task = asyncio.create_task(self.service.run_summary_recovery_trial(limit=1))
        await asyncio.wait_for(entered.wait(), 2)
        for kwargs in ({}, {"force": True}, {"recovery_batch_id": batch_id}, {"recovery_batch_id": unrelated}):
            self.assertEqual("", await self.service.maybe_summarize_session(self.ctx(), **kwargs))
        self.service._schedule_session_summary(self.ctx(), reason="incoming")
        release.set()
        result = await task
        self.assertEqual(1, len(self.provider.calls))
        self.assertEqual("paused", result["mode"])
        self.assertEqual("pending", (await self.service.store.get_summary_batch(unrelated))["state"])

    async def test_invalid_oldest_identity_stops_without_replacement(self):
        await self.batch(valid=False)
        await self.batch(1)
        result = await self.service.run_summary_recovery_trial()
        self.assertEqual("paused", result["mode"])
        self.assertEqual("trial_identity:persona_missing", result["stop_reason"])
        self.assertFalse(self.provider.calls)

    async def test_source_or_provider_change_stops_before_any_reservation(self):
        await self.batch()
        original = self.service._summary_trial_snapshot
        calls = 0

        async def changed(batch):
            nonlocal calls
            calls += 1
            ctx, snapshot = await original(batch)
            if calls > 1:
                snapshot["providers_hash"] = "changed"
            return ctx, snapshot
        self.service._summary_trial_snapshot = changed
        result = await self.service.run_summary_recovery_trial()
        self.assertEqual("trial_source_or_provider_changed", result["stop_reason"])
        self.assertFalse(self.provider.calls)
        self.assertEqual(0, self.service.store._conn.execute("SELECT COUNT(*) FROM summary_batch_calls").fetchone()[0])

    async def test_full_hourly_budget_stops_selected_ids_without_reset(self):
        first, _ = await self.batch()
        second, _ = await self.batch(1)
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute("""INSERT INTO summary_batch_calls(batch_id,session_id,attempted_at,automatic)
                SELECT id,session_id,strftime('%Y-%m-%dT%H:%M:%S+00:00','now'),1 FROM summary_batches WHERE id=?""", (first,))
        self.config["memory_summary"]["max_calls_per_session_hour"] = 1
        result = await self.service.run_summary_recovery_trial()
        self.assertEqual("trial_batch_incomplete:pending", result["stop_reason"])
        self.assertEqual([first, second], [item["id"] for item in result["batches"]])
        self.assertEqual(1, len(result["results"]))
        self.assertFalse(self.provider.calls)
        self.assertEqual(1, self.service.store._conn.execute("SELECT COUNT(*) FROM summary_batch_calls").fetchone()[0])

    async def test_unlimited_trial_selects_previously_budget_deferred_batch(self):
        batch_id, _ = await self.batch()
        self.assertTrue(await self.service.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=1))
        await self.service.store.defer_summary_batch(batch_id, 'temporary', delay=0)
        self.assertFalse(await self.service.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=1))
        self.config['memory_summary']['max_calls_per_session_hour'] = 0
        result = await self.service.run_summary_recovery_trial(limit=1)
        self.assertEqual('', result['stop_reason'])
        self.assertEqual([batch_id], [item['id'] for item in result['batches']])
        self.assertEqual('no_memory', (await self.service.store.get_summary_batch(batch_id))['state'])

    async def test_switched_current_session_provider_with_empty_id_stops_trial(self):
        await self.batch()
        replacement = Provider([])
        calls = 0

        async def attempts(ctx):
            nonlocal calls
            calls += 1
            provider = self.provider if calls == 1 else replacement
            return [{"provider": provider, "provider_id": "", "source": "current_session"}]
        self.service._summary_provider_attempts = attempts
        result = await self.service.run_summary_recovery_trial()
        self.assertEqual("trial_source_or_provider_changed", result["stop_reason"])
        self.assertFalse(self.provider.calls)
        self.assertFalse(replacement.calls)

    async def test_trial_fallback_and_repair_are_automatic_and_share_budget(self):
        batch_id, event_id = await self.batch()
        first = Provider([TimeoutError("fake provider timeout")])
        self.provider.responses.insert(0, "invalid json")

        async def attempts(ctx):
            return [{"provider": p, "provider_id": name, "source": "configured"}
                    for p, name in ((first, "primary"), (self.provider, "fallback"))]
        self.service._summary_provider_attempts = attempts
        result = await self.service.run_summary_recovery_trial()
        self.assertEqual("", result["stop_reason"])
        self.assertEqual(3, len(first.calls) + len(self.provider.calls))
        self.assertEqual(3, self.service.store._conn.execute("SELECT COUNT(*) FROM summary_batch_calls WHERE automatic=1").fetchone()[0])
        self.assertEqual(3, (await self.service.store.get_summary_batch(batch_id))["automatic_calls"])
        self.assertIn(event_id, self.provider.calls[-1]["prompt"])

    async def test_pause_waits_for_inflight_manual_work_before_freeze(self):
        batch_id, _ = await self.batch()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.provider.text_chat

        async def blocking(**kwargs):
            entered.set()
            await release.wait()
            return await original(**kwargs)
        self.provider.text_chat = blocking
        manual = asyncio.create_task(self.service.maybe_summarize_session(self.ctx(), force=True))
        await asyncio.wait_for(entered.wait(), 2)
        trial = asyncio.create_task(self.service.run_summary_recovery_trial())
        await asyncio.sleep(0)
        self.assertEqual("paused", self.service._summary_admission.state["mode"])
        self.assertFalse(trial.done())
        release.set()
        await manual
        result = await trial
        self.assertEqual([], result["batches"])
        self.assertEqual(1, len(self.provider.calls))
