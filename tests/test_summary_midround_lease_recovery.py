from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from .test_summary_batch_recovery import Provider


class SummaryMidroundLeaseRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {
            "startup": {"background_grace_seconds": 60},
            "memory_summary": {
                "enabled": True,
                "min_events": 1,
                "trigger_event_count": 1,
                "max_events_per_summary": 1,
                "max_retries": 3,
                "retry_backoff_seconds": 60,
                "max_calls_per_session_hour": 1,
                "request_max_retries": 1,
                "auto_drain_enabled": True,
            },
        }
        self.service = MemoryCompanionService(
            context=None,
            config=self.config,
            plugin_root=ROOT,
            data_dir=Path(self.temp.name),
        )
        self.addCleanup(self.service.close)
        self.service._schedule_memory_embedding = lambda *args: None
        self.ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            persona_id="persona-1",
        )

    async def seed_event(
        self,
        content: str = "小王和我聊了今天喝的无糖拿铁，觉得味道不错。",
        *,
        days_old: int = 0,
    ) -> str:
        occurred_at = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        return await self.service.store.add_timeline_event(
            event_type="user_message",
            session_id=self.ctx.session_id,
            scope=self.ctx.scope,
            subject_id=self.ctx.user_id,
            object_id=self.ctx.user_id,
            content=content,
            metadata={
                "platform": "qq",
                "owner_bot_id": "b1",
                "persona_id": "persona-1",
                "user_id": "u1",
                "sender_name": "小王",
            },
            occurred_at=occurred_at,
        )

    def payload(self, event_id: str, *, refs: list[str] | None = None, summary: str | None = None) -> dict:
        return {
            "outcome": "memory",
            "summary": "我和小王聊了无糖拿铁，觉得味道不错。" if summary is None else summary,
            "summary_refs": [event_id] if refs is None else refs,
            "key_facts": [],
            "importance": 0.5,
        }

    def use(self, *providers: Provider) -> None:
        async def attempts(*_args, **_kwargs):
            return [{"provider": p, "provider_id": str(i), "source": "primary"} for i, p in enumerate(providers)]

        self.service._summary_provider_attempts = attempts

    def batches(self) -> list[dict]:
        return [
            dict(row)
            for row in self.service.store._conn.execute("SELECT * FROM summary_batches ORDER BY created_at,id")
        ]

    async def test_midround_hourly_limit_after_usable_body_preserves_lease_and_saves_candidate(self) -> None:
        event_id = await self.seed_event()
        invalid = self.payload(event_id, refs=["missing-event"])
        provider = Provider([invalid, self.payload(event_id)])
        self.use(provider)

        memory_id = await self.service.maybe_summarize_session(self.ctx)

        self.assertTrue(memory_id)
        self.assertEqual(1, len(provider.calls))
        record = await self.service.store.get_memory(memory_id)
        self.assertIsNotNone(record)
        self.assertEqual("short_term_candidate", record.lifecycle)
        self.assertEqual("pending", record.review_status)
        batch = self.batches()[0]
        self.assertEqual("completed", batch["state"])
        self.assertEqual(1, batch["automatic_calls"])
        self.assertEqual("", batch["lease_token"])
        self.assertIsNone(batch["lease_expires_at"])
        self.assertIsNone(batch["next_retry_at"])
        self.assertEqual("", batch["retry_reason"])
        timeline = (await self.service.store.get_timeline_by_ids([event_id]))[event_id]
        self.assertFalse(timeline["summarized_at"])
        self.assertEqual("", await self.service.maybe_summarize_session(self.ctx))
        self.assertEqual(1, len(provider.calls))

    async def test_midround_hourly_limit_across_multiple_calls_after_usable_body(self) -> None:
        self.config["memory_summary"]["max_retries"] = 4
        self.config["memory_summary"]["max_calls_per_session_hour"] = 2
        self.config["memory_summary"]["retry_backoff_seconds"] = 0
        event_id = await self.seed_event()
        invalid = self.payload(event_id, refs=["missing-event"])
        provider = Provider([invalid, invalid, self.payload(event_id)])
        self.use(provider)

        memory_id = await self.service.maybe_summarize_session(self.ctx)

        self.assertTrue(memory_id)
        self.assertEqual(2, len(provider.calls))
        record = await self.service.store.get_memory(memory_id)
        self.assertEqual("short_term_candidate", record.lifecycle)
        self.assertEqual("pending", record.review_status)
        batch = self.batches()[0]
        self.assertEqual("completed", batch["state"])
        self.assertEqual(2, batch["automatic_calls"])
        self.assertEqual("", batch["lease_token"])
        self.assertIsNone(batch["next_retry_at"])
        self.assertEqual("", batch["retry_reason"])

    async def test_midround_hourly_limit_without_usable_body_releases_lease_and_defers_for_budget(self) -> None:
        self.config["memory_summary"]["retry_backoff_seconds"] = 0
        event_id = await self.seed_event()
        empty_body = self.payload(event_id, refs=["missing-event"], summary="")
        provider = Provider([empty_body, self.payload(event_id)])
        self.use(provider)

        memory_id = await self.service.maybe_summarize_session(self.ctx)

        self.assertEqual("", memory_id)
        self.assertEqual(1, len(provider.calls))
        batch = self.batches()[0]
        self.assertEqual("retry_pending", batch["state"])
        self.assertEqual(self.service.store.BUDGET_RETRY_REASON, batch["retry_reason"])
        self.assertIsNotNone(batch["next_retry_at"])
        self.assertEqual("", batch["lease_token"])
        self.assertIsNone(batch["lease_expires_at"])
        status = await self.service.summary_recovery_status()
        self.assertEqual({"hourly_budget": 1}, {k: v for k, v in status["waits"].items() if v})

    async def test_reserve_summary_call_hourly_limit_preserves_only_active_same_owner(self) -> None:
        event_id = await self.seed_event()
        rows = list((await self.service.store.get_timeline_by_ids([event_id])).values())
        batch_id = await self.service.store.create_summary_batch(self.ctx.session_id, self.ctx.scope, rows)

        self.assertTrue(
            await self.service.store.reserve_summary_call(
                batch_id, max_calls=3, hourly_limit=2, lease_seconds=3600, lease_token="worker-a"
            )
        )
        # Foreign worker cannot preserve or steal an active lease.
        self.assertFalse(
            await self.service.store.reserve_summary_call(
                batch_id, max_calls=3, hourly_limit=1, lease_token="worker-b", preserve_lease=True
            )
        )
        batch = await self.service.store.get_summary_batch(batch_id)
        self.assertEqual("worker-a", batch["lease_token"])

        # Same owner with preserve_lease=True keeps lease on budget refusal and can finish.
        self.assertFalse(
            await self.service.store.reserve_summary_call(
                batch_id, max_calls=3, hourly_limit=1, lease_token="worker-a", preserve_lease=True
            )
        )
        batch = await self.service.store.get_summary_batch(batch_id)
        self.assertEqual("worker-a", batch["lease_token"])
        self.assertEqual(self.service.store.BUDGET_RETRY_REASON, batch["retry_reason"])
        await self.service.store.finish_summary_batch(
            batch_id, [event_id], no_memory=True, lease_token="worker-a"
        )
        completed = await self.service.store.get_summary_batch(batch_id)
        self.assertEqual("no_memory", completed["state"])
        self.assertEqual("", completed["lease_token"])
        self.assertIsNone(completed["next_retry_at"])
        self.assertEqual("", completed["retry_reason"])

        # Expired lease must still be cleared on budget refusal and fail finish_summary_batch.
        event_id_2 = await self.seed_event("第二条测试消息，用于检查过期租约。")
        rows_2 = list((await self.service.store.get_timeline_by_ids([event_id_2])).values())
        batch_id_2 = await self.service.store.create_summary_batch(self.ctx.session_id, self.ctx.scope, rows_2)
        self.assertTrue(
            await self.service.store.reserve_summary_call(
                batch_id_2, max_calls=3, hourly_limit=6, lease_seconds=3600, lease_token="stale-worker"
            )
        )
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute(
                "UPDATE summary_batches SET next_retry_at=?, lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", batch_id_2),
            )
        self.assertFalse(
            await self.service.store.reserve_summary_call(
                batch_id_2, max_calls=3, hourly_limit=1, lease_token="stale-worker", preserve_lease=True
            )
        )
        stale_batch = await self.service.store.get_summary_batch(batch_id_2)
        self.assertEqual("", stale_batch["lease_token"])
        self.assertIsNone(stale_batch["lease_expires_at"])
        with self.assertRaisesRegex(RuntimeError, "lease ownership changed"):
            await self.service.store.finish_summary_batch(
                batch_id_2, [event_id_2], no_memory=True, lease_token="stale-worker"
            )

    async def test_summary_recovery_status_classifies_aged_backlog_windows(self) -> None:
        self.config["memory_summary"]["min_events"] = 20
        self.config["memory_summary"]["trigger_event_count"] = 20
        self.config["memory_summary"]["max_events_per_summary"] = 40
        self.config["memory_summary"]["max_calls_per_session_hour"] = 6
        await self.seed_event("三天前的消息一", days_old=3)
        await self.seed_event("三天前的消息二", days_old=3)

        status = await self.service.summary_recovery_status()
        self.assertEqual(2, status["unbatched"]["events"])
        self.assertEqual(0, status["unbatched"]["below_threshold_events"])
        self.assertEqual(2, status["unbatched"]["eligible_events"])
        self.assertEqual(1, status["unbatched"]["eligible_windows"])
        self.assertEqual(1, status["unbatched"]["waits"]["runnable"])

        # Recent below-threshold session still stays below_threshold_events.
        other_session = "qq:FriendMessage:u-fresh"
        for idx in range(2):
            await self.service.store.add_timeline_event(
                event_type="user_message",
                session_id=other_session,
                scope="private",
                subject_id="u-fresh",
                object_id="u-fresh",
                content=f"刚刚的消息 {idx}",
                metadata={"platform": "qq", "owner_bot_id": "b1", "persona_id": "persona-1", "user_id": "u-fresh"},
            )
        status_mixed = await self.service.summary_recovery_status()
        self.assertEqual(4, status_mixed["unbatched"]["events"])
        self.assertEqual(2, status_mixed["unbatched"]["below_threshold_events"])
        self.assertEqual(2, status_mixed["unbatched"]["eligible_events"])
        self.assertEqual(1, status_mixed["unbatched"]["eligible_windows"])

        # Turning off auto_drain_enabled restores threshold gating for below-threshold aged windows.
        self.config["memory_summary"]["auto_drain_enabled"] = False
        status_no_drain = await self.service.summary_recovery_status()
        self.assertEqual(4, status_no_drain["unbatched"]["below_threshold_events"])
        self.assertEqual(0, status_no_drain["unbatched"]["eligible_events"])
        self.assertEqual(0, status_no_drain["unbatched"]["eligible_windows"])


if __name__ == "__main__":
    unittest.main()
