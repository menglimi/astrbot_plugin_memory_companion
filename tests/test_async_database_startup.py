from __future__ import annotations

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
        self.assertEqual(1, len(initialized_threads))
        self.assertNotEqual("MainThread", initialized_threads[0])
        self.assertIsNotNone(
            service.store._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
        )


if __name__ == "__main__":
    unittest.main()
