from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def core_record(memory_id: str, label: str, content: str, priority: int = 50) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        memory_type="core_memory",
        subject=EntityRef(kind="user", id="u1"),
        object=EntityRef.bot_self("bot1"),
        scope="private",
        session_id="qq:private:u1",
        platform="qq",
        visibility="private_pair",
        lifecycle="stable_memory",
        content=content,
        evidence="panel",
        confidence=1.0,
        importance=priority / 100,
        owner_bot_id="bot1",
        durability="pinned",
        review_status="manual",
        metadata={
            "core_memory": True,
            "core_enabled": True,
            "core_label": label,
            "core_kind": "rule",
            "core_scope": "private",
            "core_priority": priority,
            "target_id": "u1",
            "owner_bot_id": "bot1",
        },
    )


class CoreMemoryStoreTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    async def test_revision_guard_and_priority_order(self) -> None:
        store = self.make_store()
        first = core_record("core-low", "address", "称呼用户为小林", 40)
        high = core_record("core-high", "boundary", "不要主动追问隐私", 90)

        created = await store.save_core_memory(first, expected_revision=0)
        await store.save_core_memory(high, expected_revision=0)
        conflict = await store.save_core_memory(
            core_record("core-low", "address", "称呼用户为林林", 40),
            expected_revision=0,
        )
        updated = await store.save_core_memory(
            core_record("core-low", "address", "称呼用户为林林", 40),
            expected_revision=1,
        )

        self.assertEqual({"ok": True, "id": "core-low", "revision": 1}, created)
        self.assertEqual("revision_conflict", conflict["code"])
        self.assertEqual(1, conflict["current_revision"])
        self.assertEqual(2, updated["revision"])
        records = await store.list_core_memories()
        self.assertEqual(["core-high", "core-low"], [record.id for record in records])
        self.assertEqual("称呼用户为林林", records[1].content)

    async def test_core_memory_read_does_not_wait_for_primary_write_lock(self) -> None:
        store = self.make_store()
        store._lock.acquire()
        try:
            records = await asyncio.wait_for(store.list_core_memories(), timeout=1.0)
        finally:
            store._lock.release()

        self.assertEqual([], records)

    async def test_recent_timeline_read_does_not_wait_for_primary_write_lock(self) -> None:
        store = self.make_store()
        store._lock.acquire()
        try:
            rows = await asyncio.wait_for(store.recent_timeline(limit=10), timeout=1.0)
        finally:
            store._lock.release()

        self.assertEqual([], rows)
        self.assertFalse(store.shutdown_state()["timeline_read_conn_closed"])
        store.close()
        self.assertTrue(store.shutdown_state()["timeline_read_conn_closed"])

    async def test_recent_timeline_read_does_not_wait_for_candidate_read_lock(self) -> None:
        store = self.make_store()
        store._read_lock.acquire()
        try:
            rows = await asyncio.wait_for(store.recent_timeline(limit=10), timeout=1.0)
        finally:
            store._read_lock.release()

        self.assertEqual([], rows)


class StaticMemoryContextReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_static_context_reads_start_concurrently(self) -> None:
        service = MemoryCompanionService.__new__(MemoryCompanionService)
        context = SessionContext(
            session_id="qq:private:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="bot1",
        )
        started: set[str] = set()
        all_started = asyncio.Event()
        release = asyncio.Event()

        async def read(name: str, result: object) -> object:
            started.add(name)
            if len(started) == 3:
                all_started.set()
            await release.wait()
            return result

        service.core_memories_for_context = lambda _ctx: read("core_memories", [])
        service._recent_fact_guard_context = lambda _ctx: read("recent_fact", "facts")
        service._recent_cross_window_context = lambda _ctx: read("cross_window", "continuity")

        task = asyncio.create_task(service._load_static_memory_context(context, None))
        await asyncio.wait_for(all_started.wait(), timeout=1.0)
        release.set()
        result = await task

        self.assertEqual({"core_memories", "recent_fact", "cross_window"}, started)
        self.assertEqual(([], "facts", "continuity"), result)


class CoreMemoryInjectionTests(unittest.TestCase):
    def test_core_memory_is_rendered_without_retrieval_results(self) -> None:
        included: list[str] = []
        text = InjectionComposer().compose(
            SessionContext(
                session_id="qq:private:u1",
                scope="private",
                platform="qq",
                user_id="u1",
                bot_id="bot1",
                message_text="你好",
            ),
            [],
            max_chars=1800,
            core_memories=[core_record("core-1", 'name"rule', "不要输出 <internal> 标签", 80)],
            core_memory_max_chars=700,
            included_memory_ids=included,
        )

        self.assertIn("<core_memory>", text)
        self.assertIn('label="name&quot;rule"', text)
        self.assertIn("不要输出 &lt;internal&gt; 标签", text)
        self.assertIn("用户本轮明确纠正", text)
        self.assertEqual(["core-1"], included)

    def test_core_memory_is_not_a_dynamic_retrieval_candidate(self) -> None:
        engine = RetrievalEngine(
            store=None,
            policy=VisibilityPolicy(),
            retrieval_mode="basic",
        )
        allowed, reason = engine._profile_retrieval_decision(
            core_record("core-1", "boundary", "不要主动追问隐私", 90)
        )

        self.assertFalse(allowed)
        self.assertEqual("static_core_memory", reason)


class CoreMemoryToolTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def service_for(ctx: SessionContext) -> MemoryCompanionService:
        service = MemoryCompanionService.__new__(MemoryCompanionService)
        service.config = SimpleNamespace(bool=lambda _key, default=True: default)
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        service._normalized_session_context = lambda value: value
        service.core_memories_for_context = AsyncMock(return_value=[])
        service.save_core_memory_block = AsyncMock(return_value={"ok": True, "id": "core-1", "revision": 1})
        service.delete_core_memory_block = AsyncMock(return_value={"ok": True})
        service._bot_subject_id = lambda value: value.bot_id or "self"
        return service

    async def test_set_is_bound_to_current_private_user(self) -> None:
        service = self.service_for(
            SessionContext(
                session_id="qq:private:u1",
                scope="private",
                platform="qq",
                user_id="u1",
                user_name="小林",
                bot_id="bot1",
                persona_id="persona1",
            )
        )

        result = await MemoryCompanionService.tool_core_memory(
            service,
            object(),
            action="set",
            label="address",
            content="称呼用户为林林",
            kind="preference",
            priority=80,
        )

        self.assertTrue(result["ok"])
        payload = service.save_core_memory_block.await_args.args[0]
        self.assertEqual("private", payload["scope"])
        self.assertEqual("u1", payload["target_id"])
        self.assertEqual("bot1", payload["bot_id"])
        self.assertEqual("persona1", payload["persona_id"])

    async def test_group_context_cannot_mutate_core_blocks(self) -> None:
        service = self.service_for(
            SessionContext(session_id="qq:group:g1", scope="group", group_id="g1")
        )

        result = await MemoryCompanionService.tool_core_memory(
            service,
            object(),
            action="delete",
            label="boundary",
        )

        self.assertEqual("private_scope_required", result["code"])
        service.save_core_memory_block.assert_not_awaited()
        service.delete_core_memory_block.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
