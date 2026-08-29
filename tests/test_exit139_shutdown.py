"""exit=139 (SIGSEGV) 修复的单元测试（EXIT_139_FIX_PLAN.md §5.1）。

覆盖 F1（capture_async 注册）、F2（store 关闭屏障）、F3（aclose 等待
summary workers）、F4（shutdown_complete 结构化证据）。
"""
from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore


def make_store() -> tuple[MemoryStore, tempfile.TemporaryDirectory]:
    temp_dir = tempfile.TemporaryDirectory()
    store = MemoryStore(Path(temp_dir.name) / "memory.db")
    store.initialize()
    return store, temp_dir


def make_service(
    data_dir: Path,
) -> MemoryCompanionService:
    return MemoryCompanionService(
        context=None,
        config={},
        plugin_root=Path(ROOT),
        data_dir=data_dir,
    )


class StoreCloseBarrierTests(unittest.IsolatedAsyncioTestCase):
    """F2: close() 等待在飞操作归零，且新操作在 closing 后被拒绝。"""

    def _blocking_op(self, started: threading.Event, release: threading.Event):
        started.set()
        release.wait(5.0)

    async def test_close_with_inflight_read(self) -> None:
        store, temp_dir = make_store()
        self.addCleanup(temp_dir.cleanup)
        started = threading.Event()
        release = threading.Event()
        # 模拟一个在飞的只读 bundle 查询（持有计数）。
        task = asyncio.create_task(
            asyncio.to_thread(
                store._guard_operation_sync,
                self._blocking_op,
                started,
                release,
            )
        )
        await asyncio.to_thread(started.wait, 2.0)
        self.assertTrue(started.is_set(), "在飞操作应已启动")
        close_task = asyncio.create_task(asyncio.to_thread(store.close))
        await asyncio.sleep(0.1)
        self.assertFalse(close_task.done(), "close() 不应在操作在飞时提前返回")
        release.set()
        await asyncio.wait_for(task, timeout=10)
        await asyncio.wait_for(close_task, timeout=10)
        state = store.shutdown_state()
        self.assertEqual(state["tracked_ops"], 0)
        self.assertTrue(state["main_conn_closed"])

    async def test_close_with_inflight_write(self) -> None:
        store, temp_dir = make_store()
        self.addCleanup(temp_dir.cleanup)
        started = threading.Event()
        release = threading.Event()
        task = asyncio.create_task(
            store._run_tracked_operation(
                self._blocking_op,
                started,
                release,
            )
        )
        await asyncio.to_thread(started.wait, 2.0)
        self.assertTrue(started.is_set(), "在飞写操作应已启动")
        close_task = asyncio.create_task(asyncio.to_thread(store.close))
        await asyncio.sleep(0.1)
        self.assertFalse(close_task.done(), "close() 不应在写操作在飞时提前返回")
        release.set()
        await asyncio.wait_for(task, timeout=10)
        await asyncio.wait_for(close_task, timeout=10)
        state = store.shutdown_state()
        self.assertEqual(state["tracked_ops"], 0)
        self.assertTrue(state["main_conn_closed"])

    async def test_new_operation_rejected_after_closing(self) -> None:
        store, temp_dir = make_store()
        self.addCleanup(temp_dir.cleanup)
        try:
            store._closing = True
            with self.assertRaises(Exception):
                await asyncio.to_thread(
                    store._guard_operation_sync,
                    lambda: None,
                )
        finally:
            store._closing = False
            store.close()

    async def test_recoverable_operation_under_barrier(self) -> None:
        """F2: _run_recoverable_database_operation 路径也被关闭屏障覆盖。"""
        store, temp_dir = make_store()
        self.addCleanup(temp_dir.cleanup)
        try:
            result = await store._run_recoverable_database_operation(lambda: 42)
            self.assertEqual(result, 42)
            state = store.shutdown_state()
            self.assertEqual(state["tracked_ops"], 0)
        finally:
            store.close()

    async def test_timeline_event_under_barrier(self) -> None:
        """F2: add_timeline_event（裸 to_thread 写路径）也受屏障保护。"""
        store, temp_dir = make_store()
        self.addCleanup(temp_dir.cleanup)
        try:
            memory_id = await store.add_timeline_event(
                event_type="user_message",
                session_id="s-1",
                scope="private",
                subject_id="u-1",
                object_id="",
                content="hello",
                metadata={},
            )
            self.assertTrue(memory_id)
            state = store.shutdown_state()
            self.assertEqual(state["tracked_ops"], 0)
        finally:
            store.close()


class CaptureAsyncRegistrationTests(unittest.IsolatedAsyncioTestCase):
    """F1: 采集写入任务经 _spawn_background 注册，terminate 后可被取消。"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self._service = make_service(Path(self._temp_dir.name))

    def tearDown(self) -> None:
        self._service._closed = True
        self._service.store.close()

    async def test_spawn_background_registers_and_cleans(self) -> None:
        async def noop() -> None:
            return None
        task = self._service._spawn_background(noop(), label="capture-async")
        self.assertIsNotNone(task)
        self.assertIn(task, self._service._background_tasks)
        await task
        self.assertNotIn(task, self._service._background_tasks)

    async def test_aclose_cancels_background_tasks(self) -> None:
        async def never_finishes() -> None:
            await asyncio.Event().wait()
        task = self._service._spawn_background(
            never_finishes(), label="capture-async"
        )
        self.assertIsNotNone(task)
        await self._service.aclose()
        self.assertTrue(task.done())
        self.assertEqual(len(self._service._background_tasks), 0)


class AcloseSummaryWorkerTests(unittest.IsolatedAsyncioTestCase):
    """F3: aclose 显式等待 _summary_workers 归零。"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self._service = make_service(Path(self._temp_dir.name))

    def tearDown(self) -> None:
        self._service._closed = True
        self._service.store.close()

    async def test_aclose_waits_summary_workers(self) -> None:
        async def never_finishes() -> None:
            await asyncio.Event().wait()
        task = asyncio.create_task(never_finishes())
        self._service._summary_workers["session-x"] = task
        await self._service.aclose()
        self.assertTrue(task.done())
        self.assertEqual(len(self._service._summary_workers), 0)
        self.assertEqual(len(self._service._summary_pending), 0)


class ShutdownEvidenceTests(unittest.IsolatedAsyncioTestCase):
    """F4: shutdown_evidence / shutdown_complete 结构化证据。"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self._service = make_service(Path(self._temp_dir.name))

    def tearDown(self) -> None:
        self._service._closed = True
        self._service.store.close()

    async def test_shutdown_evidence_shape(self) -> None:
        await self._service.aclose()
        evidence = self._service.shutdown_evidence()
        self.assertIn("background_tasks", evidence)
        self.assertIn("summary_workers", evidence)
        self.assertIn("summary_pending", evidence)
        self.assertIn("store", evidence)
        self.assertIsInstance(evidence["store"], dict)
        self.assertIn("tracked_ops", evidence["store"])
        self.assertIn("main_conn_closed", evidence["store"])
        self.assertIn("read_conn_closed", evidence["store"])

    async def test_aclose_twice_idempotent(self) -> None:
        """连续两次 aclose 不崩、第二次 no-op。"""
        await self._service.aclose()
        await self._service.aclose()
        self.assertTrue(self._service._closed)


if __name__ == "__main__":
    unittest.main()
