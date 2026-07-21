# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from astrbot_plugin_remember_you.core.bridge import MemoryCompanionBridge


class _Service:
    def __init__(self) -> None:
        self.payload = None

    async def record_external_event(self, **kwargs):
        self.payload = kwargs
        return kwargs.get("memory_id") or "memory-id"


class SharedExperienceBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_watch_keeps_exact_bot_and_user_ownership(self) -> None:
        service = _Service()
        bridge = MemoryCompanionBridge(service)

        memory_id = await bridge.record_shared_experience(
            content="我和流星一起看完了测试影片，都很喜欢结尾的留白。",
            experience_type="watch",
            bot_id="12345678",
            bot_name="小星",
            user_id="87654321",
            user_name="流星",
            session_id="together_companion:87654321",
            platform="together_companion",
            source_plugin="astrbot_plugin_together_companion",
            memory_id="shared-watch-1",
        )

        self.assertEqual("shared-watch-1", memory_id)
        self.assertEqual("shared_watch", service.payload["memory_type"])
        self.assertEqual("12345678", service.payload["subject"].id)
        self.assertEqual("bot_self", service.payload["subject"].role)
        self.assertEqual("87654321", service.payload["object"].id)
        self.assertEqual("shared_experience_partner", service.payload["object"].role)
        self.assertEqual("bot_self", service.payload["visibility"])
        self.assertIn("shared_experience", service.payload["tags"])


if __name__ == "__main__":
    unittest.main()
