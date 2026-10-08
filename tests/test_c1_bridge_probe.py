from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if "astrbot_plugin_remember_you" not in sys.modules:
    package = types.ModuleType("astrbot_plugin_remember_you")
    package.__path__ = [str(ROOT)]
    sys.modules["astrbot_plugin_remember_you"] = package
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core import bot_personal_contract
from astrbot_plugin_remember_you.core.bridge import MemoryCompanionBridge
from astrbot_plugin_remember_you.core.config import ConfigView
from astrbot_plugin_remember_you.core.service import MemoryCompanionService


class _PluginMustNotBeTouched:
    def __getattr__(self, name: str):
        raise AssertionError(f"probe touched plugin capability: {name}")


class C1BridgeProbeTests(unittest.TestCase):
    def test_probe_returns_ready_contract_snapshot_without_plugin_or_database_access(self) -> None:
        result = MemoryCompanionBridge(_PluginMustNotBeTouched()).probe_bot_personal_memory_capabilities()

        self.assertTrue(result["available"])
        self.assertFalse(result["read_only"])
        self.assertEqual("ready", result["state"])
        self.assertFalse(result["degraded"])
        self.assertEqual([], result["warnings"])
        self.assertEqual(bot_personal_contract.BOT_PERSONAL_MEMORY_DOMAIN, result["memory_domain"])
        self.assertEqual(bot_personal_contract.CONTRACT_NAME, result["contract_name"])
        self.assertEqual(bot_personal_contract.CONTRACT_REVISION, result["contract_revision"])
        self.assertEqual(bot_personal_contract.CONTRACT_FINGERPRINT, result["contract_fingerprint"])
        self.assertEqual(bot_personal_contract.BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION, result["capability_schema_version"])
        self.assertEqual(bot_personal_contract.BOT_PERSONAL_PAYLOAD_SCHEMA_VERSION, result["payload_schema_version"])
        self.assertEqual(list(bot_personal_contract.WINDOW_SLUGS), result["windows"])
        self.assertEqual(list(bot_personal_contract.BOT_PERSONAL_MEMORY_TYPES), result["memory_types"])
        self.assertEqual(bot_personal_contract.BOT_PERSONAL_MAX_PAYLOAD_BYTES, result["max_payload_bytes"])
        self.assertEqual({"state": "unprobed", "error_code": "p5_status_not_probed"}, result["p5"])

    def test_probe_returns_stable_degraded_shape_when_contract_self_check_fails(self) -> None:
        with patch.object(bot_personal_contract, "contract_self_check", return_value=["contract_fingerprint_stale: hidden"]):
            result = MemoryCompanionBridge(_PluginMustNotBeTouched()).probe_bot_personal_memory_capabilities()

        self.assertFalse(result["available"])
        self.assertEqual("negative", result["state"])
        self.assertEqual("negative", result["capability_state"])
        self.assertTrue(result["degraded"])
        self.assertIn("contract_self_check_failed", result["warnings"])
        self.assertIn("contract_fingerprint_stale", result["warnings"])
        self.assertNotIn("hidden", result["warnings"])

    def test_probe_converts_contract_check_exception_to_degraded_result(self) -> None:
        with patch.object(
            bot_personal_contract,
            "contract_self_check",
            side_effect=RuntimeError("raw prompt, user identity, session content, database object"),
        ):
            result = MemoryCompanionBridge(_PluginMustNotBeTouched()).probe_bot_personal_memory_capabilities()

        self.assertFalse(result["available"])
        self.assertEqual("negative", result["state"])
        self.assertEqual("negative", result["capability_state"])
        self.assertTrue(result["degraded"])
        self.assertEqual(["contract_self_check_exception"], result["warnings"])
        for secret in ("raw prompt", "user identity", "database object"):
            self.assertNotIn(secret, str(result))

    def test_official_bridge_switch_is_not_overridden_by_legacy_flat_flag(self) -> None:
        service = object.__new__(MemoryCompanionService)
        service.config = ConfigView(
            {
                "enable_memory_companion_bridge": True,
                "private_companion_bridge": {"enabled": False},
            }
        )

        status = service.companion_coordination_status()

        self.assertFalse(status["bridge_enabled"])
        self.assertEqual("local_only", status["state"])
