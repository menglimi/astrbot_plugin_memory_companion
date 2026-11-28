# -*- coding: utf-8 -*-
"""A11：Bridge 写入口（record_external_memory / mark_visibility / provenance_*）
必须校验 Private Companion capability。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.bridge import MemoryCompanionBridge


class _FakePlugin:
    """最小插件替身：配置闸门 + 已注册的 PrivateCompanion 星标。"""

    def __init__(self, bridge_gate: bool = False) -> None:
        self.bridge_gate = bridge_gate
        self.config = SimpleNamespace(bool=self._bool, get=lambda key, default=None: default)
        self.producer = SimpleNamespace(name="PrivateCompanion")
        self.metadata = SimpleNamespace(
            star_cls=self.producer,
            star_cls_type=type(self.producer),
            activated=True,
            root_dir_name="",
            name="PrivateCompanion",
        )
        self.context = SimpleNamespace(get_all_stars=lambda: [self.metadata])
        self.record_external_memory = AsyncMock(
            return_value={"ok": True, "state": "stored", "memory_id": "m-1", "deduplicated": False}
        )
        self.provenance_snapshot = Mock(
            return_value={"records": {"m-1": {"provenance_state": "observed"}}, "operation_count": 1, "state": "ready"}
        )
        self.provenance_preview = Mock(
            return_value={"mode": "preview", "readonly": True, "write_count": 0, "error_codes": []}
        )
        self.provenance_apply = AsyncMock(return_value={"ok": True, "status": "applied"})
        self.provenance_backup = AsyncMock(return_value={"ok": True, "created": True})
        self.provenance_rollback = AsyncMock(return_value={"ok": True, "status": "rolled_back"})
        self.store = SimpleNamespace(update_memory_visibility=AsyncMock(return_value=True))

    def _bool(self, key, default=False):
        if key.endswith("enable_p5_b1_bridge_gate"):
            return self.bridge_gate
        return default


def make_bridge(bridge_gate: bool = False) -> tuple[MemoryCompanionBridge, _FakePlugin]:
    plugin = _FakePlugin(bridge_gate=bridge_gate)
    return MemoryCompanionBridge(plugin), plugin


class BridgeCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_write_without_capability_is_refused_when_gate_is_on(self) -> None:
        bridge, plugin = make_bridge(bridge_gate=True)
        result = await bridge.record_external_memory(user_id="u1", content="外部写入")
        self.assertFalse(result["ok"])
        self.assertEqual("forbidden", result["state"])
        self.assertEqual("producer_capability_required", result["error_code"])
        plugin.record_external_memory.assert_not_called()

    async def test_external_write_with_a_foreign_capability_is_refused(self) -> None:
        bridge, plugin = make_bridge(bridge_gate=True)
        foreign = object()
        result = await bridge.record_external_memory(
            user_id="u1", content="外部写入", producer_capability=foreign
        )
        self.assertEqual("producer_capability_required", result["error_code"])
        plugin.record_external_memory.assert_not_called()

    async def test_external_write_with_a_foreign_capability_is_refused_even_without_gate(self) -> None:
        bridge, plugin = make_bridge(bridge_gate=False)
        result = await bridge.record_external_memory(
            user_id="u1", content="外部写入", producer_capability=object()
        )
        self.assertEqual("producer_capability_required", result["error_code"])
        plugin.record_external_memory.assert_not_called()

    async def test_external_write_with_a_live_capability_succeeds(self) -> None:
        bridge, plugin = make_bridge(bridge_gate=True)
        capability = bridge.register_private_companion(plugin.producer)
        self.assertIsNotNone(capability)
        result = await bridge.record_external_memory(
            user_id="u1", content="外部写入", producer_capability=capability
        )
        self.assertTrue(result["ok"])
        self.assertEqual("m-1", result["memory_id"])
        plugin.record_external_memory.assert_awaited_once()

    async def test_legacy_callers_keep_working_when_the_gate_is_off(self) -> None:
        # 默认 private_companion_bridge.enable_p5_b1_bridge_gate=false：
        # 未接入陪伴侧的部署不能被这次加固打断（向后兼容）。
        bridge, plugin = make_bridge(bridge_gate=False)
        result = await bridge.record_external_memory(user_id="u1", content="外部写入")
        self.assertTrue(result["ok"])
        plugin.record_external_memory.assert_awaited_once()

    async def test_deactivated_bridge_refuses_even_valid_callers(self) -> None:
        bridge, plugin = make_bridge(bridge_gate=True)
        capability = bridge.register_private_companion(plugin.producer)
        bridge.deactivate()
        result = await bridge.record_external_memory(
            user_id="u1", content="外部写入", producer_capability=capability
        )
        self.assertFalse(result["ok"])
        self.assertIn(result["error_code"], {"bridge_inactive", "producer_capability_required"})
        plugin.record_external_memory.assert_not_called()

    async def test_provenance_entry_points_require_a_capability(self) -> None:
        bridge, plugin = make_bridge(bridge_gate=True)
        snapshot = bridge.provenance_snapshot()
        self.assertEqual("forbidden", snapshot["state"])
        self.assertEqual("producer_capability_required", snapshot["error_code"])
        plugin.provenance_snapshot.assert_not_called()

        preview = bridge.provenance_preview([], operation_ref_hash="h" * 64)
        self.assertEqual(["producer_capability_required"], preview["error_codes"])
        plugin.provenance_preview.assert_not_called()

        for call in (
            bridge.provenance_apply({}),
            bridge.provenance_backup(),
            bridge.provenance_rollback({}),
        ):
            result = await call
            self.assertFalse(result["ok"])
            self.assertEqual("producer_capability_required", result["error_code"])
        plugin.provenance_apply.assert_not_called()
        plugin.provenance_backup.assert_not_called()
        plugin.provenance_rollback.assert_not_called()

    async def test_provenance_entry_points_accept_a_live_capability(self) -> None:
        bridge, plugin = make_bridge(bridge_gate=True)
        capability = bridge.register_private_companion(plugin.producer)
        self.assertEqual("ready", bridge.provenance_snapshot(producer_capability=capability)["state"])
        self.assertTrue((await bridge.provenance_apply({}, producer_capability=capability))["ok"])
        self.assertTrue((await bridge.provenance_backup(producer_capability=capability))["ok"])
        self.assertTrue((await bridge.provenance_rollback({}, producer_capability=capability))["ok"])

    async def test_mark_visibility_requires_a_capability(self) -> None:
        bridge, plugin = make_bridge(bridge_gate=True)
        self.assertFalse(await bridge.mark_visibility("m-1", "group_public"))
        plugin.store.update_memory_visibility.assert_not_called()
        capability = bridge.register_private_companion(plugin.producer)
        self.assertTrue(
            await bridge.mark_visibility("m-1", "group_public", producer_capability=capability)
        )
        plugin.store.update_memory_visibility.assert_awaited_once_with("m-1", "group_public")


if __name__ == "__main__":
    unittest.main()
