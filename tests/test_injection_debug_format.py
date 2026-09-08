from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class _Config:
    def bool(self, _key: str, _default: bool = False) -> bool:
        return True

    def int(self, _key: str, default: int = 0) -> int:
        return default


class InjectionDebugFormatTests(unittest.TestCase):
    def test_debug_log_preserves_text_instead_of_splitting_every_character(self) -> None:
        service = MemoryCompanionService.__new__(MemoryCompanionService)
        service.config = _Config()
        service.injection = SimpleNamespace(_redact_sensitive_text=lambda value: str(value))
        ctx = SimpleNamespace(
            session_id="session",
            scope="private",
            label="target",
            bot_id="bot",
            message_text="问候",
        )
        intent = SimpleNamespace(source="message", query="你好")

        with patch("astrbot_plugin_memory_companion.core.service.logger.info") as log_info:
            service._log_injection_debug(
                ctx=ctx,
                intent=intent,
                results=[],
                slot_map={},
                blocked=[],
                conversation_memory="",
                intent_context="",
                injection="甲\r\n乙\r丙",
                note="test",
            )

        summary = log_info.call_args.args[1]
        self.assertIn("甲\n乙\n丙", summary)
