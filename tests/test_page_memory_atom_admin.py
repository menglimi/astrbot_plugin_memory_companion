from __future__ import annotations

import importlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")
    quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = quart_stub

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi


class _JsonResponse(dict):
    status_code = 200


class PageMemoryAtomAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_exposes_summary_progress_without_review_candidates(self) -> None:
        progress = {"raw_events": 40, "conversation_memories": 2, "quarantined_batches": 1}
        store = SimpleNamespace(
            stats=AsyncMock(return_value={"total_memories": 3, "pending_review": 1}),
            summary_progress=AsyncMock(return_value=progress),
        )
        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=store)))
        with patch.object(page_api_module, "jsonify", side_effect=lambda body: body):
            response = await api.stats()
        self.assertEqual(progress, response["stats"]["summary_progress"])
        self.assertNotIn("pending_review", response["stats"])

    async def invoke(self, payload: dict, *, current=None):
        if current is None:
            current = SimpleNamespace(valid_from="", valid_to="")
        store = SimpleNamespace(
            get_memory=AsyncMock(return_value=current),
            update_memory_payload=AsyncMock(return_value=True),
        )
        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=store)))
        fake_request = SimpleNamespace(get_json=AsyncMock(return_value=payload))
        with (
            patch.object(page_api_module, "request", fake_request),
            patch.object(page_api_module, "jsonify", side_effect=lambda body: _JsonResponse(body)),
        ):
            response = await api.memory_update()
        return response, store

    async def test_atom_fields_are_validated_and_forwarded(self) -> None:
        response, store = await self.invoke(
            {
                "id": "memory-1",
                "content": "修正后的事实",
                "validity_status": "superseded",
                "valid_from": "2026-08-01T00:00:00+08:00",
                "valid_to": "2026-08-31T00:00:00+08:00",
                "salience": 0.73,
                "durability": "durable",
                "sensitivity": "restricted",
            }
        )

        self.assertEqual(200, response.status_code)
        self.assertTrue(response["success"])
        kwargs = store.update_memory_payload.await_args.kwargs
        self.assertEqual("superseded", kwargs["validity_status"])
        self.assertEqual("2026-08-01T00:00:00+08:00", kwargs["valid_from"])
        self.assertEqual("2026-08-31T00:00:00+08:00", kwargs["valid_to"])
        self.assertEqual(0.73, kwargs["salience"])
        self.assertEqual("durable", kwargs["durability"])
        self.assertEqual("restricted", kwargs["sensitivity"])

    async def test_invalid_enum_does_not_reach_store_update(self) -> None:
        response, store = await self.invoke(
            {"id": "memory-1", "validity_status": "revived-by-typo"}
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("invalid validity_status", response["error"])
        store.update_memory_payload.assert_not_awaited()

    async def test_invalid_or_reversed_time_range_is_rejected(self) -> None:
        invalid, invalid_store = await self.invoke(
            {"id": "memory-1", "valid_from": "not-a-time"}
        )
        reversed_range, reversed_store = await self.invoke(
            {
                "id": "memory-1",
                "valid_from": "2026-09-01T00:00:00+08:00",
                "valid_to": "2026-08-01T00:00:00+08:00",
            }
        )

        self.assertEqual(400, invalid.status_code)
        self.assertIn("ISO-8601", invalid["error"])
        invalid_store.update_memory_payload.assert_not_awaited()
        self.assertEqual(400, reversed_range.status_code)
        self.assertEqual("valid_from must not be later than valid_to", reversed_range["error"])
        reversed_store.update_memory_payload.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
