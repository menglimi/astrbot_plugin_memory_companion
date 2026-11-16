from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from .test_summary_concurrency import _ConcurrentProvider


class SummaryAutoDrainBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.service = MemoryCompanionService(
            context=None,
            config={"memory_summary": {
                "enabled": True,
                "min_events": 20,
                "trigger_event_count": 20,
                "max_events_per_summary": 40,
                "max_retries": 2,
                "max_calls_per_session_hour": 1,
                "max_concurrent_calls": 1,
                "call_queue_timeout_seconds": 1,
            }},
            plugin_root=ROOT,
            data_dir=Path(temp.name),
        )
        self.addCleanup(self.service.close)
        self.service._schedule_memory_embedding = lambda *_args: None
        self.service.auto_distill_core_memory = AsyncMock(return_value={})
        self.provider = _ConcurrentProvider(delay=0)

        async def attempts(*_args, **_kwargs):
            return [{"source": "primary", "provider_id": "test", "provider": self.provider}]

        self.service._summary_provider_attempts = attempts
        self.ctx = SessionContext(session_id="qq:FriendMessage:u1", scope="private", bot_id="b1")

    async def seed(self, n=2, *, days_old=3):
        ids = []
        for i in range(n):
            ids.append(await self.service.store.add_timeline_event(
                event_type="user_message",
                session_id=self.ctx.session_id,
                scope=self.ctx.scope,
                subject_id="u1",
                object_id=self.ctx.bot_id,
                content=f"小王正在分享无糖拿铁的味道。第 {i} 条",
                occurred_at=(datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat(),
                metadata={"owner_bot_id": self.ctx.bot_id},
            ))
        return ids

    async def run_round(self):
        async def sleep(delay):
            if delay == 2:
                self.service._closing = True

        with patch("astrbot_plugin_memory_companion.core.service.asyncio.sleep", new=sleep), patch(
            "astrbot_plugin_memory_companion.core.service.logger.info"
        ) as info:
            await self.service._summary_drain_dispatch_loop()
        self.service._closing = False
        return [args[0] for args, _kwargs in info.call_args_list]

    def batches(self):
        return [dict(row) for row in self.service.store._conn.execute(
            "SELECT * FROM summary_batches ORDER BY created_at,id"
        )]

    async def assert_pending(self, ids):
        rows = await self.service.store.get_timeline_by_ids(ids)
        self.assertEqual(len(ids), len(rows))
        self.assertTrue(all(not row["summarized_at"] for row in rows.values()))

    async def test_two_old_events_drain_below_threshold_with_automatic_accounting(self):
        ids = await self.seed()
        logs = await self.run_round()
        self.assertEqual(1, self.provider.calls)
        self.assertEqual("completed", self.batches()[0]["state"])
        self.assertEqual(1, self.batches()[0]["automatic_calls"])
        self.assertEqual([(1,)], [tuple(row) for row in self.service.store._conn.execute(
            "SELECT automatic FROM summary_batch_calls"
        )])
        self.assertTrue(any("自动消化完成" in line for line in logs))
        rows = await self.service.store.get_timeline_by_ids(ids)
        self.assertTrue(all(row["summarized_at"] for row in rows.values()))

    async def test_exhausted_hourly_budget_retains_work_without_reporting_completion(self):
        spent_ids = await self.seed(n=1)
        rows = await self.service.store.get_timeline_by_ids(spent_ids)
        spent = await self.service.store.create_summary_batch(
            self.ctx.session_id, self.ctx.scope, list(rows.values())
        )
        self.assertTrue(await self.service.store.reserve_summary_call(
            spent, max_calls=2, hourly_limit=1
        ))
        ids = await self.seed()
        logs = await self.run_round()
        self.assertEqual(0, self.provider.calls)
        self.assertFalse(any("自动消化完成" in line for line in logs))
        await self.assert_pending(ids)
        deferred = next(batch for batch in self.batches() if batch["id"] != spent)
        self.assertEqual(0, deferred["automatic_calls"])
        self.assertEqual(self.service.store.BUDGET_RETRY_REASON, deferred["retry_reason"])
        self.assertNotIn(deferred["state"], {"completed", "no_memory", "quarantined"})
        self.assertEqual(1, self.service.store._conn.execute(
            "SELECT COUNT(*) FROM summary_batch_calls"
        ).fetchone()[0])

    async def test_occupied_global_slot_retains_work_until_a_later_round(self):
        ids = await self.seed()
        await self.service._summary_call_semaphore.acquire()
        try:
            logs = await self.run_round()
            self.assertEqual(0, self.provider.calls)
            self.assertFalse(any("自动消化完成" in line for line in logs))
            await self.assert_pending(ids)
            self.assertEqual(0, self.batches()[0]["automatic_calls"])
        finally:
            self.service._summary_call_semaphore.release()
        self.assertTrue(await self.service.maybe_summarize_session(self.ctx, allow_aged_backlog=True))
        self.assertEqual(1, self.provider.calls)
        self.assertEqual("completed", self.batches()[0]["state"])

    async def test_old_work_keeps_summary_disable_switch(self):
        ids = await self.seed()
        self.service.config.raw["memory_summary"]["enabled"] = False
        await self.run_round()
        self.assertEqual(0, self.provider.calls)
        self.assertEqual([], self.batches())
        await self.assert_pending(ids)

    async def test_single_old_event_still_waits_for_minimum_backlog(self):
        ids = await self.seed(n=1)
        await self.run_round()
        self.assertEqual(0, self.provider.calls)
        await self.assert_pending(ids)

    async def test_recent_small_window_still_waits_for_normal_threshold(self):
        ids = await self.seed(days_old=1)
        await self.run_round()
        self.assertEqual(0, self.provider.calls)
        await self.assert_pending(ids)

    async def test_automatic_drain_does_not_reopen_quarantine(self):
        old_ids = await self.seed()
        rows = await self.service.store.get_timeline_by_ids(old_ids)
        batch_id = await self.service.store.create_summary_batch(
            self.ctx.session_id, self.ctx.scope, list(rows.values())
        )
        await self.service.store.defer_summary_batch(batch_id, "needs review", quarantine=True)
        await self.seed()
        await self.run_round()
        self.assertEqual(1, self.provider.calls)
        old = await self.service.store.get_summary_batch(batch_id)
        self.assertEqual("quarantined", old["state"])
        self.assertEqual(0, old["automatic_calls"])
        await self.assert_pending(old_ids)

    async def test_automatic_drain_keeps_retry_cooldown(self):
        old_ids = await self.seed()
        rows = await self.service.store.get_timeline_by_ids(old_ids)
        batch_id = await self.service.store.create_summary_batch(
            self.ctx.session_id, self.ctx.scope, list(rows.values())
        )
        await self.service.store.defer_summary_batch(batch_id, "temporary failure", delay=3600)
        await self.seed()
        await self.run_round()
        self.assertEqual(1, self.provider.calls)
        old = await self.service.store.get_summary_batch(batch_id)
        self.assertEqual("retry_pending", old["state"])
        self.assertEqual(0, old["automatic_calls"])
        await self.assert_pending(old_ids)
