"""Summary-batch observability: every freeze and every release must be logged.

Two paths used to be invisible. A transient provider failure (429/503) that
exhausted the call budget quarantined the batch from inside the retry loop and
returned before the shared warning ran; a successful manual release only
returned its payload. Operators could not tell from the logs which batch was
frozen or released, so the tests below pin one structured line per event.
"""
from __future__ import annotations

import importlib
import json
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")
    quart_stub.send_file = lambda path: path
    sys.modules["quart"] = quart_stub

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
service_module = importlib.import_module("astrbot_plugin_memory_companion.core.service")
PluginPageApi = page_api_module.PluginPageApi
MemoryCompanionService = service_module.MemoryCompanionService

from astrbot_plugin_memory_companion.core.models import SessionContext


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


class SummaryBatchObservabilityTests(unittest.IsolatedAsyncioTestCase):
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
        self.ctx = SessionContext(session_id='qq:FriendMessage:obs', scope='private', platform='qq', user_id='u1', bot_id='b1')

    async def event(self, content='小王和我聊了今天喝的无糖拿铁，觉得味道不错。'):
        return await self.service.store.add_timeline_event(
            event_type='user_message', session_id=self.ctx.session_id, scope=self.ctx.scope,
            subject_id=self.ctx.user_id, object_id=self.ctx.bot_id, content=content, metadata={'sender_name': '小王'},
            occurred_at='2026-09-15T01:00:00+00:00',
        )

    def use(self, *providers):
        async def attempts(*args, **kwargs):
            return [{'provider': p, 'provider_id': str(i), 'source': 'primary'} for i, p in enumerate(providers)]
        self.service._summary_provider_attempts = attempts

    def batches(self):
        return [dict(row) for row in self.service.store._conn.execute('SELECT * FROM summary_batches ORDER BY created_at,id')]

    async def test_transient_failure_exhausting_the_budget_logs_the_freeze(self):
        event_id = await self.event()
        provider = Provider([TimeoutError('503 Service Unavailable')] * 3)
        self.use(provider, provider, provider)

        # The host provides its own logger object rather than a stdlib Logger, so
        # swap in a normal channel to read the record the plugin emits.
        test_logger = logging.getLogger('MemoryCompanion.SummaryBatchTest')
        with (
            patch.object(service_module, 'logger', test_logger),
            self.assertLogs(test_logger, level='WARNING') as captured,
        ):
            self.assertEqual('', await self.service.maybe_summarize_session(self.ctx))

        batch = self.batches()[0]
        self.assertEqual('quarantined', batch['state'])
        self.assertFalse((await self.service.store.get_timeline_by_ids([event_id]))[event_id]['summarized_at'])
        warnings = [record.getMessage() for record in captured.records if '批次已隔离' in record.getMessage()]
        self.assertEqual(1, len(warnings), warnings)
        self.assertIn(batch['id'], warnings[0])
        self.assertIn(self.ctx.session_id, warnings[0])
        self.assertIn('event_count=1', warnings[0])
        self.assertIn('calls=3', warnings[0])
        self.assertIn('reason=TimeoutError:', warnings[0])

    async def test_release_logs_batch_mode_event_count_and_resulting_state(self):
        event_id = await self.event()
        rows = list((await self.service.store.get_timeline_by_ids([event_id])).values())
        batch_id = await self.service.store.create_summary_batch(self.ctx.session_id, self.ctx.scope, rows)
        await self.service.store.defer_summary_batch(batch_id, 'provider 503 unavailable', quarantine=True)

        api = PluginPageApi(SimpleNamespace(service=self.service))
        fake_request = SimpleNamespace(get_json=AsyncMock(return_value={'batch_id': batch_id, 'mode': 'retry'}))
        with (
            patch.object(page_api_module, 'request', fake_request),
            patch.object(page_api_module, 'jsonify', side_effect=lambda body: body),
            self.assertLogs(page_api_module.logger, level='INFO') as captured,
        ):
            response = await api.release_summary_batch()

        self.assertTrue(response['success'])
        self.assertEqual(batch_id, response['data']['batch_id'])
        self.assertEqual('retry_pending', response['data']['state'])
        releases = [record.getMessage() for record in captured.records if '批次已释放' in record.getMessage()]
        self.assertEqual(1, len(releases), releases)
        self.assertIn(batch_id, releases[0])
        self.assertIn('mode=retry', releases[0])
        self.assertIn('released_events=1', releases[0])
        self.assertIn('state=retry_pending', releases[0])
