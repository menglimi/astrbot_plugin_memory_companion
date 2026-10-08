from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class AsyncDatabaseStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_deferred_initialization_runs_database_setup_off_loop(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
            defer_database_initialization=True,
        )
        self.addCleanup(service.close)
        initialized_threads: list[str] = []
        initialize = service.store.initialize

        def observe_initialize() -> None:
            initialized_threads.append(threading.current_thread().name)
            initialize()

        service.store.initialize = observe_initialize
        self.assertFalse(service.scoped_store._initialized)
        self.assertIsNone(
            service.store._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
        )

        await service.initialize_database()
        await service.initialize_database()

        self.assertTrue(service._database_initialized)
        self.assertTrue(service.scoped_store._initialized)
        self.assertIsNotNone(service.capture)
        self.assertEqual(1, len(initialized_threads))
        self.assertNotEqual("MainThread", initialized_threads[0])
        self.assertIsNotNone(
            service.store._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
        )

    async def test_initialization_failure_keeps_store_retryable(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
            defer_database_initialization=True,
        )
        self.addCleanup(service.close)
        initialize = service.store.initialize
        fail_once = True

        def fail_once_then_initialize() -> None:
            nonlocal fail_once
            if fail_once:
                fail_once = False
                raise sqlite3.OperationalError("temporary initialization failure")
            initialize()

        service.store.initialize = fail_once_then_initialize
        with self.assertRaisesRegex(RuntimeError, "temporary initialization failure"):
            await service.initialize_database()

        self.assertFalse(service.store._closed)
        self.assertIsNotNone(service.store._conn.execute("PRAGMA schema_version").fetchone())
        self.assertTrue(await service.initialize_database())

    async def test_shutdown_waits_for_inflight_initialization(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
            defer_database_initialization=True,
        )
        self.addCleanup(service.close)
        initialized = service.store.initialize
        started = threading.Event()
        release = threading.Event()

        def block_initialization() -> None:
            started.set()
            if not release.wait(5.0):
                raise TimeoutError("test initialization was not released")
            initialized()

        service.store.initialize = block_initialization
        initialize_task = asyncio.create_task(service.initialize_database())
        self.assertTrue(await asyncio.to_thread(started.wait, 2.0))

        close_task = asyncio.create_task(service.aclose())
        await asyncio.sleep(0)
        self.assertTrue(service._closing)
        release.set()

        self.assertFalse(await asyncio.wait_for(initialize_task, timeout=10))
        await asyncio.wait_for(close_task, timeout=10)
        self.assertTrue(service.store._closed)
        self.assertFalse(await service.initialize_database())


if __name__ == "__main__":
    unittest.main()
