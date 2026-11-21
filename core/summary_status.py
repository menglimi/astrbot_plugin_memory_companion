"""Aggregate recovery waits without dispatching work or exposing source data."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import json_loads, utc_now


WAIT_LABELS = {
    'runnable': '可以尝试整理',
    'hourly_budget': '等待每小时额度',
    'running': '正在整理',
    'retry': '等待错误重试',
    'identity': '来源身份缺失或冲突',
    'paused': '已暂停或仅允许指定批次试跑',
    'disabled': '自动总结已关闭',
    'capture_disabled': '此范围未开启记忆记录',
    'global_slot': '等待其他会话整理完成',
    'session_busy': '等待本会话当前任务完成',
    'call_limit': '本批调用次数已用完，等待隔离处理',
}


class SummaryStatusMethods:
    async def summary_recovery_status(self) -> dict[str, Any]:
        """Only database reads and existing in-memory state are consulted.

        Runnable means source/admission/budget/queue ready. Provider resolution
        remains the dispatcher's job; a status read never contacts a model.
        """
        snapshot = await self.store.summary_status_snapshot(
            max_events=self.config.int('memory_summary.max_events_per_summary', 40),
        )
        now = datetime.now(timezone.utc)
        timestamp = utc_now()
        enabled = self.config.bool('memory_summary.enabled', True)
        hourly = max(1, self.config.int('memory_summary.max_calls_per_session_hour', 24))
        max_calls = max(1, self.config.int('memory_summary.max_retries', 5))
        gate = self._summary_admission
        waits = {key: 0 for key in WAIT_LABELS}
        oldest = ''
        busy_sessions = {
            session for session, task in self._summary_workers.items() if task is not None and not task.done()
        } | {session for session, lock in self._summary_locks.items() if lock.locked()}

        def admission_reason(context):
            if not enabled:
                return 'disabled'
            if not gate.normal:
                return 'paused'
            if not self._scope_feature_enabled(context, 'capture'):
                return 'capture_disabled'
            if snapshot['budgets'].get(context.session_id, 0) >= hourly:
                return 'hourly_budget'
            if context.session_id in busy_sessions:
                return 'session_busy'
            if self._summary_call_semaphore.locked():
                return 'global_slot'
            return 'runnable'

        for batch in snapshot['batches']:
            context, _ = self._summary_context_from_sources(
                batch['session_id'], batch['scope'], json_loads(batch['metadata'], {}),
                snapshot['sources'][batch['id']],
            )
            lease_active = bool(batch['lease_token'] and batch['lease_expires_at'] and batch['lease_expires_at'] > timestamp)
            if context is None:
                reason = 'identity'
            elif lease_active or (gate.current_batch == batch['id'] and gate.owner is not None):
                reason = 'running'
            elif not enabled or not gate.normal:
                reason = 'disabled' if not enabled else 'paused'
            elif batch['automatic_calls'] >= max_calls:
                reason = 'call_limit'
            elif snapshot['budgets'].get(context.session_id, 0) >= hourly:
                reason = 'hourly_budget'
            elif not batch['due']:
                reason = 'hourly_budget' if batch['retry_reason'] == self.store.BUDGET_RETRY_REASON else 'retry'
            else:
                reason = admission_reason(context)
            waits[reason] += 1
            if reason != 'running' and (not oldest or batch['created_at'] < oldest):
                oldest = batch['created_at']

        originals = {'events': 0, 'eligible_events': 0, 'eligible_windows': 0,
                     'identity_blocked_events': 0, 'capture_blocked_events': 0,
                     'below_threshold_events': 0, 'waits': {key: 0 for key in WAIT_LABELS}}
        for (session, scope), window in snapshot['originals'].items():
            originals['events'] += window['total']
            if not self._summary_window_ready(window, force=False):
                originals['below_threshold_events'] += window['total']
                continue
            context, _ = self._summary_context_from_sources(session, scope, {}, window['rows'])
            first = window['rows'][0]['created_at']
            if not oldest or first < oldest:
                oldest = first
            if context is None:
                reason = 'identity'
                originals['identity_blocked_events'] += len(window['rows'])
            elif not self._scope_feature_enabled(context, 'capture'):
                reason = 'capture_disabled'
                originals['capture_blocked_events'] += len(window['rows'])
            else:
                # Validate only the next bounded window, never its unread tail.
                originals['eligible_events'] += len(window['rows'])
                originals['eligible_windows'] += 1
                reason = admission_reason(context)
            originals['waits'][reason] += 1

        oldest_seconds = 0
        if oldest:
            oldest_time = datetime.fromisoformat(oldest)
            if oldest_time.tzinfo is None:
                oldest_time = oldest_time.replace(tzinfo=timezone.utc)
            oldest_seconds = max(0, int((now - oldest_time).total_seconds()))
        counts = snapshot['counts']
        memories = snapshot['memories']
        return {
            'observed_at': timestamp,
            'admission': gate.state['mode'],
            'summary_enabled': enabled,
            'recovery_enabled': self.config.bool('memory_summary.recovery_enabled', True),
            'dispatcher_state': self._summary_recovery_status['state'],
            'pending_batches': len(snapshot['batches']),
            'waits': waits,
            'wait_labels': WAIT_LABELS,
            'oldest_wait_seconds': oldest_seconds,
            'unbatched': originals,
            'progress': {
                'raw_events': snapshot['raw_events'],
                'completed_batches': counts.get('completed', 0),
                'no_memory_batches': counts.get('no_memory', 0),
                'quarantined_batches': counts.get('quarantined', 0),
                'adopted_memories': memories.get('adopted', 0),
                'review_candidates': memories.get('pending', 0),
            },
            'limits': {'calls_per_session_hour': hourly,
                       'global_concurrency': max(1, self.config.int('memory_summary.max_concurrent_calls', 1))},
        }
