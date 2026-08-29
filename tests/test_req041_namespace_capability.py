from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.bridge import MemoryCompanionBridge
from core.namespace_capability import (
    API_METHODS,
    namespace_capability_descriptor,
    negotiate_namespace_capability,
    validate_namespace_capability,
)
from core.service import MemoryCompanionService


class NamespaceCapabilityTests(unittest.TestCase):
    def test_complete_descriptor_negotiates_ready(self) -> None:
        descriptor = namespace_capability_descriptor(available=True, methods=API_METHODS)
        self.assertEqual([], validate_namespace_capability(descriptor))
        self.assertTrue(negotiate_namespace_capability(descriptor)["available"])

    def test_bridge_is_honest_until_scoped_api_is_bound(self) -> None:
        bridge = MemoryCompanionBridge(SimpleNamespace())
        descriptor = bridge.probe_namespace_context_capabilities()
        self.assertFalse(descriptor["available"])
        self.assertEqual("namespace_scoped_api_not_bound", descriptor["error_code"])
        self.assertEqual([], validate_namespace_capability(descriptor, require_available=False))
        self.assertEqual("namespace_capability_unavailable", negotiate_namespace_capability(descriptor)["code"])

    def test_scoped_store_initialization_failure_keeps_primary_store_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("core.service.ScopedStore", side_effect=RuntimeError("scoped unavailable")):
                service = MemoryCompanionService(
                    context=None,
                    config={},
                    plugin_root=Path(temp_dir),
                    data_dir=Path(temp_dir),
                )

            self.assertIsNone(service.scoped_store)
            self.assertEqual(
                {
                    "state": "degraded",
                    "error_code": "namespace_scoped_store_initialize_failed",
                },
                service.scoped_store_status,
            )
            self.assertFalse(service.store._closed)
            self.assertEqual(1, service.store._conn.execute("SELECT 1").fetchone()[0])

            descriptor = MemoryCompanionBridge(service).probe_namespace_context_capabilities()
            self.assertFalse(descriptor["available"])
            self.assertEqual(
                "namespace_scoped_store_initialize_failed",
                descriptor["error_code"],
            )

            asyncio.run(service.aclose())
            service.close()
            self.assertTrue(service.store._closed)

    def test_contract_mismatch_and_extra_field_fail_closed(self) -> None:
        descriptor = namespace_capability_descriptor(available=True, methods=API_METHODS)
        descriptor["namespace_contract_version"] = "2.0"
        descriptor["extra"] = "unsafe"
        errors = validate_namespace_capability(descriptor)
        self.assertIn("namespace_capability_fields_invalid", errors)
        self.assertIn("namespace_contract_version_mismatch", errors)


if __name__ == "__main__":
    unittest.main()
