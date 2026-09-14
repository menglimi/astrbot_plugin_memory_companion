from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.models import SessionContext
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

    async def test_one_bad_batch_does_not_block_new_messages_or_get_retried(self):
        old = await self.event()
        bad = Provider(['bad json', 'bad json'])
        self.use(bad)
        self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))
        self.assertEqual(2, len(bad.calls))
        self.assertIn('invalid JSON', bad.calls[1]['prompt'])
        self.assertIn('bad json', bad.calls[1]['prompt'])
        self.assertEqual('quarantined', self.batches()[0]['state'])
        for _ in range(3):
            await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual(2, len(bad.calls))
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
        self.assertTrue(all(c['request_max_retries'] == 0 for c in p1.calls + p2.calls))
        store = self.service.store
        db_path = store.db_path
        store.close()
        replacement = MemoryStore(db_path)
        replacement.initialize()
        self.service.store = replacement
        await self.service.maybe_summarize_session(self.ctx)
        self.assertEqual(3, len(p1.calls) + len(p2.calls))
        self.assertEqual('quarantined', self.batches()[0]['state'])

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

    async def test_reserved_call_and_repair_survive_cancellation(self):
        event_id = await self.event()
        rows = list((await self.service.store.get_timeline_by_ids([event_id])).values())
        batch_id = await self.service.store.create_summary_batch(self.ctx.session_id, self.ctx.scope, rows)
        self.assertTrue(await self.service.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=6, repair=True))
        self.assertFalse(await self.service.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=6, repair=True))
        batch = await self.service.store.get_summary_batch(batch_id)
        self.assertEqual(1, batch['automatic_calls'])
        self.assertEqual('quarantined', batch['state'])

    async def test_completion_releases_unconsumed_events(self):
        ids = [await self.event(), await self.event()]
        rows = list((await self.service.store.get_timeline_by_ids(ids)).values())
        batch_id = await self.service.store.create_summary_batch(self.ctx.session_id, self.ctx.scope, rows)
        await self.service.store.finish_summary_batch(batch_id, ids[:1], no_memory=True)
        window = await self.service.store.unsummarized_timeline_window(session_id=self.ctx.session_id, exclude_assigned=True)
        self.assertEqual([ids[1]], [r['id'] for r in window['rows']])

    async def test_manual_repair_does_not_reset_automatic_budget(self):
        event_id = await self.event()
        p = Provider(['bad json', 'bad json', self.payload(event_id)])
        self.use(p)
        await self.service.maybe_summarize_session(self.ctx)
        self.assertTrue(await self.service.maybe_summarize_session(self.ctx, force=True))
        self.assertEqual(2, self.batches()[0]['automatic_calls'])
        self.assertEqual(3, len(p.calls))

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
