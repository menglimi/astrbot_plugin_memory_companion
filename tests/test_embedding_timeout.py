from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class EmbeddingTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_embedding_timeout_keeps_event_loop_responsive(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={"retrieval": {"embedding_timeout_ms": 30}},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)

        class BlockingProvider:
            def get_embedding(self, _text: str):
                time.sleep(0.1)
                return [1.0, 0.0, 0.0]

        loop_work = asyncio.create_task(asyncio.sleep(0.01, result=True))
        with self.assertRaises(asyncio.TimeoutError):
            await service._embed_text_with_provider(BlockingProvider(), "测试嵌入")

        self.assertTrue(await loop_work)
        await asyncio.sleep(0.1)
        service.config.raw["retrieval"]["embedding_timeout_ms"] = 9000
        self.assertEqual(2000, service._embedding_timeout_ms())


if __name__ == "__main__":
    unittest.main()
