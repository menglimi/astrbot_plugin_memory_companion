from __future__ import annotations

import unittest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.config import ConfigView, schema_default


class ConfigSchemaAuthorityTests(unittest.TestCase):
    def test_public_missing_values_use_schema_instead_of_stale_callsite_defaults(self) -> None:
        config = ConfigView({})

        self.assertEqual(20, config.int("memory_summary.min_events", 8))
        self.assertEqual(20, config.int("memory_summary.trigger_event_count", 12))
        self.assertEqual(
            "current_message",
            config.get("context_orchestration.query_mode", ""),
        )

    def test_explicit_and_unknown_values_keep_round_trip_semantics(self) -> None:
        marker = object()
        config = ConfigView(
            {
                "memory_summary": {"min_events": 31},
                "future_module": {"future_key": {"nested": True}},
            }
        )

        self.assertEqual(31, config.int("memory_summary.min_events", 8))
        self.assertEqual(
            {"nested": True},
            config.get("future_module.future_key", marker),
        )
        self.assertIs(marker, schema_default("future_module.missing", marker))


if __name__ == "__main__":
    unittest.main()
