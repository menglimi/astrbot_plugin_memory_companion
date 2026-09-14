from __future__ import annotations

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class _Response:
    def __init__(self, text: str):
        self.completion_text = text


class _ConcurrentProvider:
    """Tracks how many text_chat calls are in flight at once."""

    def __init__(self, delay: float = 0.15):
        self.delay = delay
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def text_chat(self, **_kwargs):
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return _Response(
                json.dumps(
                    {
                        "summary": "小王正在分享无糖拿铁的味道。",
                        "summary_refs": re.findall(r'"event_id"\s*:\s*"([^"\n]+)"', _kwargs.get("prompt", "").split("<untrusted_messages_jsonl>")[-1]),
                        "canonical_summary": "整理后的会话。",
                        "key_facts": [],
                        "importance": 0.5,
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            self.in_flight -= 1


class SummaryConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config=config or {},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    async def seed_session(self, service: MemoryCompanionService, session_id: str, n: int = 1) -> SessionContext:
        ctx = SessionContext(
            session_id=session_id,
            scope="group",
            platform="qq",
            group_id="g-" + session_id,
            user_id="u1",
        )
        for i in range(n):
            await service.store.add_timeline_event(
                event_type="user_message",
                session_id=ctx.session_id,
                scope=ctx.scope,
                subject_id=ctx.user_id,
                object_id=ctx.group_id,
                content=f"小王正在分享无糖拿铁的味道。第 {i} 条",
                occurred_at=f"2026-08-20T00:{i:02d}:00+00:00",
            )
        return ctx

    async def test_global_slot_serializes_concurrent_summary_calls(self) -> None:
        service = self.make_service(
            {
                "memory_summary": {
                    "enabled": True,
                    "min_events": 1,
                    "trigger_event_count": 1,
                    "max_retries": 1,
                    "max_concurrent_calls": 1,
                    "call_queue_timeout_seconds": 5,
                }
            }
        )
        provider = _ConcurrentProvider(delay=0.15)

        async def attempts(*_args, **_kwargs):
            return [{"source": "primary", "provider_id": "test", "provider": provider}]

        service._summary_provider_attempts = attempts
        ctx1 = await self.seed_session(service, "s1")
        ctx2 = await self.seed_session(service, "s2")
        ctx3 = await self.seed_session(service, "s3")

        memory_ids = await asyncio.gather(
            service.maybe_summarize_session(ctx1),
            service.maybe_summarize_session(ctx2),
            service.maybe_summarize_session(ctx3),
        )
        self.assertEqual(3, sum(1 for mid in memory_ids if mid), memory_ids)
        self.assertEqual(3, provider.calls)
        self.assertEqual(1, provider.max_in_flight)

    async def test_slot_busy_skips_round_and_waits_for_next_trigger(self) -> None:
        service = self.make_service(
            {
                "memory_summary": {
                    "enabled": True,
                    "min_events": 1,
                    "trigger_event_count": 1,
                    "max_retries": 1,
                    "max_concurrent_calls": 1,
                    "call_queue_timeout_seconds": 1,
                }
            }
        )
        provider = _ConcurrentProvider(delay=0.0)

        async def attempts(*_args, **_kwargs):
            return [{"source": "primary", "provider_id": "test", "provider": provider}]

        service._summary_provider_attempts = attempts
        ctx = await self.seed_session(service, "busy")

        # Hold the only slot: the background round must skip, not block the
        # event loop, and must not consume the provider.
        await service._summary_call_semaphore.acquire()
        try:
            memory_id = await service.maybe_summarize_session(ctx)
            self.assertEqual("", memory_id)
            self.assertEqual(0, provider.calls)
        finally:
            service._summary_call_semaphore.release()

        # Once the slot frees, the next trigger proceeds normally.
        memory_id = await service.maybe_summarize_session(ctx)
        self.assertTrue(memory_id)
        self.assertEqual(1, provider.calls)

    async def test_force_run_bypasses_slot_queue(self) -> None:
        service = self.make_service(
            {
                "memory_summary": {
                    "enabled": True,
                    "min_events": 1,
                    "trigger_event_count": 1,
                    "max_retries": 1,
                    "max_concurrent_calls": 1,
                    "call_queue_timeout_seconds": 1,
                }
            }
        )
        provider = _ConcurrentProvider(delay=0.0)

        async def attempts(*_args, **_kwargs):
            return [{"source": "primary", "provider_id": "test", "provider": provider}]

        service._summary_provider_attempts = attempts
        ctx = await self.seed_session(service, "force")

        await service._summary_call_semaphore.acquire()
        try:
            memory_id = await service.maybe_summarize_session(ctx, force=True)
            self.assertTrue(memory_id)
            self.assertEqual(1, provider.calls)
        finally:
            service._summary_call_semaphore.release()


if __name__ == "__main__":
    unittest.main()
