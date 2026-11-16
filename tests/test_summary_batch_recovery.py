from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore


class Provider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return SimpleNamespace(completion_text=json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else result)


class SummaryBatchRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {'startup': {'background_grace_seconds': 60}, 'memory_summary': {
            'min_events': 1, 'trigger_event_count': 1, 'max_events_per_summary': 1,
            'max_retries': 3, 'retry_backoff_seconds': 0, 'max_calls_per_session_hour': 6,
            # 单次请求的 SDK 重试次数：2.6.0 起可配置（R14），这里钉住 1 保持旧回归语义。
            'request_max_retries': 1,
        }}
        self.service = MemoryCompanionService(context=None, config=self.config, plugin_root=ROOT, data_dir=Path(self.temp.name))
        self.addCleanup(self.service.close)
        self.service._schedule_memory_embedding = lambda *args: None
        self.ctx = SessionContext(session_id='qq:FriendMessage:u1', scope='private', platform='qq', user_id='u1', bot_id='b1')

    async def event(self, content='小王和我聊了今天喝的无糖拿铁，觉得味道不错。', *, ctx=None):
        ctx = ctx or self.ctx
        return await self.service.store.add_timeline_event(
            event_type='user_message', session_id=ctx.session_id, scope=ctx.scope,
            subject_id=ctx.user_id, object_id=ctx.bot_id, content=content, metadata={'sender_name': '小王'},
            occurred_at='2026-09-15T01:00:00+00:00',
        )

    def payload(self, event_id):
        return {'outcome': 'memory', 'summary': '我和小王聊了无糖拿铁，觉得味道不错。',
                'summary_refs': [event_id], 'key_facts': [], 'importance': .5}

    def use(self, *providers):
        async def attempts(*args, **kwargs):
            return [{'provider': p, 'provider_id': str(i), 'source': 'primary'} for i, p in enumerate(providers)]
        self.service._summary_provider_attempts = attempts

    def batches(self):
        return [dict(r) for r in self.service.store._conn.execute('SELECT * FROM summary_batches ORDER BY created_at,id')]

    async def persisted_batch(self, *, scope, session_id, batch_metadata, events):
        event_ids = []
        for index, event in enumerate(events):
            event_ids.append(await self.service.store.add_timeline_event(
                event_type='user_message',
                session_id=session_id,
                scope=scope,
                subject_id=event.get('subject_id', ''),
                object_id=event['object_id'],
                content=f'恢复校验测试事件 {index}',
                metadata=event.get('metadata', {}),
            ))
        timeline = await self.service.store.get_timeline_by_ids(event_ids)
        batch_id = await self.service.store.create_summary_batch(
            session_id,
            scope,
            [timeline[event_id] for event_id in event_ids],
            metadata=batch_metadata,
        )
        return await self.service.store.get_summary_batch(batch_id)

    async def test_one_bad_batch_does_not_block_new_messages_or_get_retried(self):
        old = await self.event()
        bad = Provider(['bad json', 'bad json', 'bad json'])
        self.use(bad)
        self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))
        self.assertEqual(3, len(bad.calls))
        self.assertIn('invalid JSON', bad.calls[1]['prompt'])
        self.assertIn('bad json', bad.calls[1]['prompt'])
        self.assertEqual('quarantined', self.batches()[0]['state'])
        for _ in range(3):
            await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual(3, len(bad.calls))
        new = await self.event()
        good = Provider([self.payload(new)])
        self.use(good)
        self.assertTrue(await self.service.maybe_summarize_session(self.ctx))
        records = await self.service.store.get_timeline_by_ids([old, new])
        self.assertFalse(records[old]['summarized_at'])
        self.assertTrue(records[new]['summarized_at'])
        self.assertEqual({'completed', 'quarantined'}, {b['state'] for b in self.batches()})

    async def test_valid_conversation_without_stable_facts_is_saved(self):
        event_id = await self.event()
        provider = Provider([self.payload(event_id)])
        self.use(provider)
        memory_id = await self.service.maybe_summarize_session(self.ctx)
        self.assertTrue(memory_id)
        self.assertEqual(1, len(provider.calls))
        row = self.service.store._conn.execute('SELECT visibility,review_status FROM memories WHERE id=?', (memory_id,)).fetchone()
        self.assertEqual(('private_pair', 'auto'), tuple(row))

    async def test_unsupported_fact_is_corrected_with_body(self):
        event_id = await self.event()
        bad = self.payload(event_id)
        bad.update(summary='小王每天都喝三杯无糖拿铁。', key_facts=[{'fact': '小王每天喝三杯拿铁', 'refs': ['nonexistent']}])
        provider = Provider([bad, self.payload(event_id)])
        self.use(provider)
        memory_id = await self.service.maybe_summarize_session(self.ctx)
        self.assertTrue(memory_id)
        prompt = provider.calls[1]['prompt']
        self.assertIn('同步', prompt)
        row = self.service.store._conn.execute('SELECT content FROM memories WHERE id=?', (memory_id,)).fetchone()
        self.assertNotIn('三杯', row[0])
        self.assertEqual(1, self.batches()[0]['repair_used'])

    async def test_weak_summary_body_is_saved_for_review_and_keeps_source(self):
        event_id = await self.event()
        weak = self.payload(event_id)
        weak['summary'] = '这次讨论了一项完全不同的旅行计划，安排十分具体。'
        provider = Provider([weak])
        self.use(provider)

        memory_id = await self.service.maybe_summarize_session(self.ctx)

        self.assertTrue(memory_id)
        record = await self.service.store.get_memory(memory_id)
        self.assertEqual('short_term_candidate', record.lifecycle)
        self.assertEqual('pending', record.review_status)
        self.assertIn('词面对应较弱', record.metadata['quality_warnings'][0])
        timeline = (await self.service.store.get_timeline_by_ids([event_id]))[event_id]
        self.assertFalse(timeline['summarized_at'])

    async def test_multiple_repair_attempts_use_the_configured_batch_budget(self):
        event_id = await self.event()
        invalid = self.payload(event_id)
        invalid['summary_refs'] = ['missing-event']
        provider = Provider([invalid, invalid, self.payload(event_id)])
        self.use(provider)

        memory_id = await self.service.maybe_summarize_session(self.ctx)

        self.assertTrue(memory_id)
        self.assertEqual(3, len(provider.calls))
        self.assertIn('summary_refs 含本批次不存在的 event_id', provider.calls[1]['prompt'])
        self.assertIn('summary_refs 含本批次不存在的 event_id', provider.calls[2]['prompt'])
        self.assertEqual('completed', self.batches()[0]['state'])

    async def test_no_memory_is_completed_without_fabricating_summary_or_deleting_raw(self):
        event_id = await self.event('嗯嗯')
        provider = Provider([{'outcome': 'no_memory', 'summary': '', 'summary_refs': [event_id],
                             'key_facts': [], 'no_memory_reason': '只有重复确认，无新增信息'}])
        self.use(provider)
        for _ in range(3):
            self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))
        self.assertEqual(1, len(provider.calls))
        self.assertEqual('no_memory', self.batches()[0]['state'])
        self.assertTrue(await self.service.store.get_timeline_by_ids([event_id]))
        self.assertEqual(0, self.service.store._conn.execute('SELECT COUNT(*) FROM memories').fetchone()[0])
        self.assertEqual(1, (await self.service.store.summary_progress())['no_memory_batches'])

    async def test_retries_and_fallbacks_share_persistent_batch_budget(self):
        await self.event()
        p1, p2 = Provider([TimeoutError('timeout')] * 5), Provider([TimeoutError('timeout')] * 5)
        self.use(p1, p2)
        for _ in range(5):
            await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual(3, len(p1.calls) + len(p2.calls))
        self.assertTrue(all(c['request_max_retries'] == 1 for c in p1.calls + p2.calls))
        store = self.service.store
        db_path = store.db_path
        store.close()
        replacement = MemoryStore(db_path)
        replacement.initialize()
        self.service.store = replacement
        await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual(3, len(p1.calls) + len(p2.calls))
        self.assertEqual('quarantined', self.batches()[0]['state'])

    async def test_request_failure_waits_for_backoff_and_recovers_without_repair(self):
        self.config['memory_summary']['retry_backoff_seconds'] = 60
        event_id = await self.event()
        error = RuntimeError('400 Invalid request parameter')
        error.response = SimpleNamespace(status_code=400)
        provider = Provider([error, self.payload(event_id)])
        self.use(provider)

        self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))

        batch = self.batches()[0]
        self.assertEqual(1, len(provider.calls))
        self.assertEqual(1, batch['automatic_calls'])
        self.assertEqual('retry_pending', batch['state'])
        self.assertEqual(0, batch['repair_used'])
        self.assertIn('400 Invalid request parameter', batch['last_error'])
        self.assertFalse(batch['last_error'].startswith('repair:'))
        self.assertGreater(datetime.fromisoformat(batch['next_retry_at']), datetime.now(timezone.utc))
        self.assertFalse((await self.service.store.get_timeline_by_ids([event_id]))[event_id]['summarized_at'])
        self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))
        self.assertEqual(1, len(provider.calls))

        self.service.store._conn.execute(
            "UPDATE summary_batches SET next_retry_at=? WHERE id=?",
            ('2000-01-01T00:00:00+00:00', batch['id']),
        )
        self.service.store._conn.commit()
        self.assertTrue(await self.service.maybe_summarize_session(self.ctx))
        self.assertEqual(2, len(provider.calls))
        self.assertNotIn('validation_errors', provider.calls[1]['prompt'])
        self.assertEqual('completed', self.batches()[0]['state'])

    async def test_request_failure_uses_fallback_without_repeating_the_failed_provider(self):
        self.config['memory_summary']['retry_backoff_seconds'] = 60
        event_id = await self.event()
        primary = Provider([RuntimeError('400 Invalid request parameter')])
        fallback = Provider([self.payload(event_id)])
        self.use(primary, fallback)

        self.assertTrue(await self.service.maybe_summarize_session(self.ctx))

        self.assertEqual(1, len(primary.calls))
        self.assertEqual(1, len(fallback.calls))
        self.assertNotIn('validation_errors', fallback.calls[0]['prompt'])
        self.assertEqual(2, self.batches()[0]['automatic_calls'])
        self.assertEqual(0, self.batches()[0]['repair_used'])
        self.assertEqual('completed', self.batches()[0]['state'])

    async def test_request_failures_keep_the_batch_budget_across_rounds(self):
        event_id = await self.event()
        provider = Provider([RuntimeError('400 Invalid request parameter')] * 3)
        self.use(provider)

        for calls in range(1, 4):
            self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))
            self.assertEqual(calls, len(provider.calls))
            batch = self.batches()[0]
            self.assertEqual(calls, batch['automatic_calls'])
            self.assertEqual('quarantined' if calls == 3 else 'retry_pending', batch['state'])
        self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))
        self.assertEqual(3, len(provider.calls))
        self.assertFalse((await self.service.store.get_timeline_by_ids([event_id]))[event_id]['summarized_at'])
        self.assertEqual([event_id], [row['id'] for row in await self.service.store.summary_batch_rows(batch['id'])])

    async def test_fallback_keeps_validation_feedback_after_a_repair_request_fails(self):
        event_id = await self.event()
        invalid = self.payload(event_id)
        invalid['summary_refs'] = ['missing-event']
        primary = Provider([invalid, RuntimeError('400 Invalid request parameter')])
        fallback = Provider([self.payload(event_id)])
        self.use(primary, fallback)

        self.assertTrue(await self.service.maybe_summarize_session(self.ctx))

        self.assertEqual(2, len(primary.calls))
        self.assertEqual(1, len(fallback.calls))
        self.assertIn('summary_refs 含本批次不存在的 event_id', fallback.calls[0]['prompt'])
        self.assertNotIn('Invalid request parameter', fallback.calls[0]['prompt'])
        self.assertEqual('completed', self.batches()[0]['state'])

    async def test_request_failure_after_a_repair_keeps_the_reviewable_body(self):
        self.config['memory_summary']['max_retries'] = 2
        event_id = await self.event()
        invalid = self.payload(event_id)
        invalid['summary_refs'] = ['missing-event']
        provider = Provider([invalid, TimeoutError('503 Service Unavailable')])
        self.use(provider)

        memory_id = await self.service.maybe_summarize_session(self.ctx)

        self.assertTrue(memory_id)
        record = await self.service.store.get_memory(memory_id)
        self.assertEqual('short_term_candidate', record.lifecycle)
        self.assertEqual('pending', record.review_status)
        self.assertEqual(2, len(provider.calls))
        self.assertEqual('completed', self.batches()[0]['state'])

    async def test_request_max_retries_is_configurable(self):
        """R14：单次请求重试次数不再是写死的 1，而是读 memory_summary.request_max_retries。"""
        self.config['memory_summary']['request_max_retries'] = 4
        service = MemoryCompanionService(
            context=None, config=self.config, plugin_root=ROOT, data_dir=Path(self.temp.name) / 'retry',
        )
        self.addCleanup(service.close)
        self.assertEqual(4, service.summarizer.request_max_retries)

    async def test_hourly_budget_spans_batches_but_not_sessions(self):
        self.config['memory_summary']['max_calls_per_session_hour'] = 1
        first = await self.event()
        p = Provider([self.payload(first)])
        self.use(p)
        await self.service.maybe_summarize_session(self.ctx)
        await self.event()
        await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual(1, len(p.calls))
        other = SessionContext(session_id='qq:FriendMessage:u2', scope='private', platform='qq', user_id='u2', bot_id='b1')
        event_id = await self.event(ctx=other)
        p.responses.append(self.payload(event_id))
        self.assertTrue(await self.service.maybe_summarize_session(other))
        self.assertEqual(2, len(p.calls))

    async def test_legacy_quarantine_migrates_once_and_new_work_goes_first(self):
        old = await self.event()
        await self.service.store.record_summary_failure(session_id=self.ctx.session_id, scope=self.ctx.scope,
            start_timeline_id=old, end_timeline_id=old, error='evidence_gate_rejected',
            metadata={'state': 'evidence_quarantine', 'candidate_memory_id': 'legacy-candidate', 'cooldown_seconds': 0})
        new = await self.event()
        p = Provider([self.payload(new), self.payload(old)])
        self.use(p)
        self.assertTrue(await self.service.maybe_summarize_session(self.ctx))
        self.assertIn(new, p.calls[0]['prompt'])
        self.assertNotIn(old, p.calls[0]['prompt'])
        self.assertTrue(await self.service.maybe_summarize_session(self.ctx))
        self.assertIn('纠正', p.calls[1]['prompt'])
        self.assertIsNone(await self.service.store.get_summary_failure(self.ctx.session_id))
        self.assertEqual(2, len(self.batches()))
        await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual(2, len(p.calls))

    async def test_repair_reservations_share_the_persisted_call_budget(self):
        event_id = await self.event()
        rows = list((await self.service.store.get_timeline_by_ids([event_id])).values())
        batch_id = await self.service.store.create_summary_batch(self.ctx.session_id, self.ctx.scope, rows)
        self.assertTrue(await self.service.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=6, repair=True))
        self.assertTrue(await self.service.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=6, repair=True))
        self.assertTrue(await self.service.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=6, repair=True))
        self.assertFalse(await self.service.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=6, repair=True))
        batch = await self.service.store.get_summary_batch(batch_id)
        self.assertEqual(3, batch['automatic_calls'])
        self.assertEqual('quarantined', batch['state'])

    async def test_unverifiable_citations_keep_the_batch_as_a_reviewable_candidate(self):
        """A summary the gate distrusts must not be thrown away, nor freeze the window."""
        event_id = await self.event()
        # Unsupported every round: the body never matches the cited messages.
        bad = self.payload(event_id)
        bad.update(summary='小王养了三只仓鼠，每天早上都要喂。')
        provider = Provider([bad, bad, bad])
        self.use(provider)
        memory_id = await self.service.maybe_summarize_session(self.ctx)
        self.assertTrue(memory_id)
        row = self.service.store._conn.execute(
            'SELECT lifecycle,review_status FROM memories WHERE id=?', (memory_id,)
        ).fetchone()
        self.assertEqual(('short_term_candidate', 'pending'), tuple(row))
        self.assertEqual('completed', self.batches()[0]['state'])
        # The events were represented, so the window is not stuck behind them.
        self.assertTrue((await self.service.store.get_timeline_by_ids([event_id]))[event_id]['summarized_at'])

    async def test_completion_releases_unconsumed_events(self):
        ids = [await self.event(), await self.event()]
        rows = list((await self.service.store.get_timeline_by_ids(ids)).values())
        batch_id = await self.service.store.create_summary_batch(self.ctx.session_id, self.ctx.scope, rows)
        await self.service.store.finish_summary_batch(batch_id, ids[:1], no_memory=True)
        window = await self.service.store.unsummarized_timeline_window(session_id=self.ctx.session_id, exclude_assigned=True)
        self.assertEqual([ids[1]], [r['id'] for r in window['rows']])

    async def test_expired_pending_candidates_are_archived_but_pinned_items_remain(self):
        now = datetime.now(timezone.utc)
        old_at = (now - timedelta(days=60)).isoformat(timespec='seconds')
        cutoff = (now - timedelta(days=30)).isoformat(timespec='seconds')
        for memory_id, durability in (('candidate-old', 'short'), ('candidate-pinned', 'pinned')):
            await self.service.store.insert_memory(MemoryRecord(
                id=memory_id,
                memory_type='conversation_summary',
                subject=EntityRef(kind='user', id='u1', name='小王'),
                object=EntityRef.bot_self('b1'),
                scope='private',
                session_id=self.ctx.session_id,
                platform='qq',
                visibility='private_pair',
                lifecycle='short_term_candidate',
                review_status='pending',
                durability=durability,
                content=f'待人工确认的摘要内容 {memory_id}。',
                created_at=old_at,
                metadata={'owner_bot_id': 'b1'},
            ))

        archived = await self.service.store.archive_expired_pending_candidates(cutoff)

        self.assertEqual(1, archived)
        expired = await self.service.store.get_memory('candidate-old')
        pinned = await self.service.store.get_memory('candidate-pinned')
        self.assertEqual(('archived', 'expired'), (expired.lifecycle, expired.review_status))
        self.assertEqual(('short_term_candidate', 'pending'), (pinned.lifecycle, pinned.review_status))
        self.assertEqual(['candidate-pinned'], [row['memory_id'] for row in await self.service.store.list_review_queue()])

    async def test_manual_repair_does_not_reset_automatic_budget(self):
        event_id = await self.event()
        p = Provider(['bad json', 'bad json', 'bad json', self.payload(event_id)])
        self.use(p)
        self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))
        self.assertTrue(await self.service.maybe_summarize_session(self.ctx, force=True))
        self.assertEqual(3, self.batches()[0]['automatic_calls'])
        self.assertEqual(4, len(p.calls))

    async def test_invalid_no_memory_cannot_consume_unchecked_events(self):
        event_id = await self.event()
        result = {'outcome': 'no_memory', 'summary_refs': [], 'no_memory_reason': '无内容', 'key_facts': []}
        p = Provider([result, result])
        self.use(p)
        await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual('quarantined', self.batches()[0]['state'])
        self.assertFalse((await self.service.store.get_timeline_by_ids([event_id]))[event_id]['summarized_at'])

    async def test_completion_rolls_back_memory_and_progress_together(self):
        event_id = await self.event()
        p = Provider([self.payload(event_id)])
        self.use(p)
        original = self.service.store._mark_timeline_summarized_sync
        def fail(*args, **kwargs):
            raise RuntimeError('injected commit failure')
        self.service.store._mark_timeline_summarized_sync = fail
        with self.assertRaisesRegex(RuntimeError, 'injected commit failure'):
            await self.service.maybe_summarize_session(self.ctx)
        self.service.store._mark_timeline_summarized_sync = original
        self.assertEqual(0, self.service.store._conn.execute('SELECT COUNT(*) FROM memories').fetchone()[0])
        self.assertNotEqual('completed', self.batches()[0]['state'])

    async def test_clear_removes_work_queue_and_source_links(self):
        event_id = await self.event()
        p = Provider(['bad json', 'bad json'])
        self.use(p)
        await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual(1, len(self.batches()))
        await self.service.store.clear_all_memory_data()
        for table in ['summary_batches', 'summary_batch_events', 'summary_batch_calls', 'timeline']:
            self.assertEqual(0, self.service.store._conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])

    async def test_budget_recovers_after_hour_without_resetting_batch_count(self):
        self.config['memory_summary']['max_calls_per_session_hour'] = 1
        first = await self.event()
        p = Provider([self.payload(first)])
        self.use(p)
        await self.service.maybe_summarize_session(self.ctx)
        second = await self.event()
        await self.service.maybe_summarize_session(self.ctx)
        self.service.store._conn.execute("UPDATE summary_batch_calls SET attempted_at='2000-01-01T00:00:00+00:00'")
        self.service.store._conn.commit()
        p.responses.append(self.payload(second))
        self.assertTrue(await self.service.maybe_summarize_session(self.ctx))
        self.assertEqual([1, 1], [b['automatic_calls'] for b in self.batches()])

    async def test_recovery_context_checks_every_private_event_target(self):
        identity = {
            'platform': 'qq',
            'owner_bot_id': 'b1',
            'persona_id': 'persona-1',
            'participant_user_id': 'u1',
        }
        batch = await self.persisted_batch(
            scope='private',
            session_id='qq:FriendMessage:u1',
            batch_metadata=identity,
            events=[
                {'subject_id': 'u1', 'object_id': 'other-user', 'metadata': identity},
                {'subject_id': 'u1', 'object_id': 'u1', 'metadata': identity},
            ],
        )

        context, reason = await self.service._summary_recovery_context(batch)

        self.assertIsNone(context)
        self.assertEqual('private_target_mismatch', reason)

    async def test_recovery_context_checks_private_user_message_subject(self):
        identity = {
            'platform': 'qq',
            'owner_bot_id': 'b1',
            'persona_id': 'persona-1',
            'participant_user_id': 'u1',
        }
        batch = await self.persisted_batch(
            scope='private',
            session_id='qq:FriendMessage:u1',
            batch_metadata=identity,
            events=[
                {'subject_id': 'other-user', 'object_id': 'u1', 'metadata': identity},
            ],
        )

        context, reason = await self.service._summary_recovery_context(batch)

        self.assertIsNone(context)
        self.assertEqual('private_subject_mismatch', reason)

    async def test_recovery_defer_does_not_overwrite_newer_lease_or_completion(self):
        identity = {
            'platform': 'qq',
            'owner_bot_id': 'b1',
            'persona_id': 'persona-1',
            'participant_user_id': 'u1',
        }
        batch = await self.persisted_batch(
            scope='private',
            session_id='qq:FriendMessage:u1',
            batch_metadata=identity,
            events=[{'subject_id': 'u1', 'object_id': 'u1', 'metadata': identity}],
        )

        self.assertTrue(await self.service.store.reserve_summary_call(
            batch['id'], max_calls=3, hourly_limit=6, lease_seconds=3600,
        ))
        self.assertFalse(await self.service.store.defer_summary_batch(
            batch['id'], 'stale recovery result', delay=0, only_if_due=True,
        ))
        leased = await self.service.store.get_summary_batch(batch['id'])
        self.assertEqual('retry_pending', leased['state'])
        self.assertEqual('', leased['last_error'])

        completed_event = await self.event()
        completed_rows = await self.service.store.get_timeline_by_ids([completed_event])
        completed_batch_id = await self.service.store.create_summary_batch(
            self.ctx.session_id,
            self.ctx.scope,
            [completed_rows[completed_event]],
        )
        await self.service.store.finish_summary_batch(
            completed_batch_id, [completed_event], no_memory=True,
        )
        self.assertFalse(await self.service.store.defer_summary_batch(
            completed_batch_id, 'stale recovery result', delay=0, only_if_due=True,
        ))
        completed = await self.service.store.get_summary_batch(completed_batch_id)
        self.assertEqual('no_memory', completed['state'])

    async def test_stale_summary_worker_cannot_defer_or_complete_after_lease_expiry(self):
        identity = {
            'platform': 'qq',
            'owner_bot_id': 'b1',
            'persona_id': 'persona-1',
            'participant_user_id': 'u1',
        }
        batch = await self.persisted_batch(
            scope='private',
            session_id='qq:FriendMessage:u1',
            batch_metadata=identity,
            events=[{'subject_id': 'u1', 'object_id': 'u1', 'metadata': identity}],
        )
        owner = 'stale-worker'
        self.assertTrue(await self.service.store.reserve_summary_call(
            batch['id'], max_calls=3, hourly_limit=6,
            lease_seconds=3600, lease_token=owner,
        ))
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute(
                "UPDATE summary_batches SET lease_expires_at=? WHERE id=?",
                ('2000-01-01T00:00:00+00:00', batch['id']),
            )

        self.assertFalse(await self.service.store.defer_summary_batch(
            batch['id'], 'stale recovery result', delay=0, lease_token=owner,
        ))
        rows = await self.service.store.summary_batch_rows(batch['id'])
        with self.assertRaisesRegex(RuntimeError, 'lease ownership changed'):
            await self.service.store.finish_summary_batch(
                batch['id'], [row['id'] for row in rows],
                no_memory=True, lease_token=owner,
            )
        current = await self.service.store.get_summary_batch(batch['id'])
        self.assertEqual('retry_pending', current['state'])
        self.assertEqual(owner, current['lease_token'])

    async def test_group_recovery_accepts_multiple_members_without_member_context(self):
        batch_identity = {
            'platform': 'qq',
            'owner_bot_id': 'b1',
            'persona_id': 'persona-1',
            'source_group_id': 'g1',
            'participant_user_id': 'member-a',
        }
        second_event = {
            'platform': 'qq',
            'owner_bot_id': 'b1',
            'persona_id': 'persona-1',
            'source_group_id': 'g1',
            'user_id': 'member-c',
            'participant_user_id': 'member-b',
        }
        batch = await self.persisted_batch(
            scope='group',
            session_id='qq:GroupMessage:g1',
            batch_metadata=batch_identity,
            events=[
                {'subject_id': 'member-a', 'object_id': 'g1', 'metadata': batch_identity},
                {'subject_id': 'member-b', 'object_id': 'g1', 'metadata': second_event},
            ],
        )

        context, reason = await self.service._summary_recovery_context(batch)

        self.assertEqual('', reason)
        self.assertIsNotNone(context)
        self.assertEqual('g1', context.group_id)
        self.assertEqual('qq', context.platform)
        self.assertEqual('b1', context.bot_id)
        self.assertEqual('', context.user_id)
        self.assertEqual('', context.user_name)

    async def test_group_recovery_rejects_mismatched_event_group_target(self):
        identity = {
            'platform': 'qq',
            'owner_bot_id': 'b1',
            'persona_id': 'persona-1',
            'source_group_id': 'g1',
        }
        batch = await self.persisted_batch(
            scope='group',
            session_id='qq:GroupMessage:g1',
            batch_metadata=identity,
            events=[
                {'subject_id': 'member-a', 'object_id': 'g1', 'metadata': {**identity, 'participant_user_id': 'member-a'}},
                {'subject_id': 'member-b', 'object_id': 'g2', 'metadata': {**identity, 'participant_user_id': 'member-b'}},
            ],
        )

        context, reason = await self.service._summary_recovery_context(batch)

        self.assertIsNone(context)
        self.assertEqual('group_target_mismatch', reason)

    async def test_database_initialization_starts_single_recovery_dispatcher_and_reports_shutdown(self):
        self.config['memory_summary'].update({
            'recovery_startup_delay_seconds': 3600,
        })
        self.service._background_grace_seconds = 0

        self.assertTrue(await self.service.initialize_database())
        dispatcher = self.service._summary_recovery_task
        self.assertIsNotNone(dispatcher)
        self.assertTrue(await self.service.initialize_database())

        self.assertIs(self.service._summary_recovery_task, dispatcher)
        self.assertEqual(1, sum(
            task.get_name() == 'memory_companion:summary_recovery_dispatcher'
            for task in self.service._background_tasks
        ))

        await self.service.aclose()
        evidence = self.service.shutdown_evidence()
        self.assertTrue(dispatcher.done())
        self.assertEqual('stopped', evidence['summary_recovery_dispatcher']['state'])
        self.assertFalse(evidence['summary_recovery_dispatcher']['running'])

    async def test_capture_disabled_batch_is_deferred_while_other_session_is_scheduled(self):
        self.config['memory_summary'].update({
            'recovery_startup_delay_seconds': 0,
            'recovery_sessions_per_round': 2,
            'recovery_disabled_retry_seconds': 3600,
        })
        self.service._background_grace_seconds = 0
        disabled_identity = {
            'platform': 'qq', 'owner_bot_id': 'b1', 'persona_id': 'persona-1',
            'participant_user_id': 'u-disabled',
        }
        enabled_identity = {
            'platform': 'qq', 'owner_bot_id': 'b1', 'persona_id': 'persona-1',
            'participant_user_id': 'u-enabled',
        }
        disabled_batch = await self.persisted_batch(
            scope='private', session_id='qq:FriendMessage:u-disabled',
            batch_metadata=disabled_identity,
            events=[{'subject_id': 'u-disabled', 'object_id': 'u-disabled', 'metadata': disabled_identity}],
        )
        enabled_batch = await self.persisted_batch(
            scope='private', session_id='qq:FriendMessage:u-enabled',
            batch_metadata=enabled_identity,
            events=[{'subject_id': 'u-enabled', 'object_id': 'u-enabled', 'metadata': enabled_identity}],
        )
        original_scope_enabled = self.service._scope_feature_enabled

        def scope_enabled(scope_or_ctx, feature):
            if getattr(scope_or_ctx, 'session_id', '') == 'qq:FriendMessage:u-disabled' and feature == 'capture':
                return False
            return original_scope_enabled(scope_or_ctx, feature)

        scheduled = asyncio.Event()
        scheduled_sessions = []

        async def record_schedule(ctx, batch_id):
            scheduled_sessions.append((ctx.session_id, batch_id))
            scheduled.set()

        self.service._scope_feature_enabled = scope_enabled
        self.service._background_recover_summary_batch = record_schedule
        self.service._ensure_summary_recovery_dispatcher()
        await asyncio.wait_for(scheduled.wait(), timeout=2)

        deferred = await self.service.store.get_summary_batch(disabled_batch['id'])
        self.assertEqual('recovery_capture_disabled', deferred['last_error'])
        self.assertGreater(deferred['next_retry_at'], datetime.now(timezone.utc).isoformat(timespec='seconds'))
        self.assertEqual([('qq:FriendMessage:u-enabled', enabled_batch['id'])], scheduled_sessions)

    async def test_summary_lease_allows_same_worker_fallback_but_blocks_other_worker(self):
        event_id = await self.event()
        rows = list((await self.service.store.get_timeline_by_ids([event_id])).values())
        batch_id = await self.service.store.create_summary_batch(
            self.ctx.session_id, self.ctx.scope, rows
        )

        self.assertTrue(await self.service.store.reserve_summary_call(
            batch_id, max_calls=3, hourly_limit=6, lease_token='worker-a',
        ))
        await self.service.store.defer_summary_batch(
            batch_id, 'temporary provider failure', delay=3600,
            lease_token='worker-a',
        )

        self.assertFalse(await self.service.store.reserve_summary_call(
            batch_id, max_calls=3, hourly_limit=6, lease_token='worker-b',
        ))
        self.assertTrue(await self.service.store.reserve_summary_call(
            batch_id, max_calls=3, hourly_limit=6, repair=True,
            lease_token='worker-a',
        ))
        batch = await self.service.store.get_summary_batch(batch_id)
        self.assertEqual(2, batch['automatic_calls'])
