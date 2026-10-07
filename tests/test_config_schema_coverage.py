from __future__ import annotations

import json
import unittest
from pathlib import Path

from core.config import ConfigView
from core.coordination_status import build_p5_status


ROOT = Path(__file__).resolve().parents[1]


class ConfigSchemaCoverageTests(unittest.TestCase):
    def test_runtime_controls_have_user_config_schema_entries(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        expected = {
            "retrieval": {"embedding_index_pending"},
            "memory_injection": {"hook_request_budget_seconds", "injection_cache_ttl_seconds"},
            "visibility": {"hide_pending_review"},
            "maintenance_decay": {
                "memory_decay_scan_limit",
                "memory_decay_include_bot_self",
                "memory_decay_include_tool_memories",
            },
            "context_orchestration": {
                "contextual_query_expansion_enabled",
                "contextual_query_recent_events",
                "contextual_query_anchor_limit",
            },
            "livingmemory_migration": {"default_review_status"},
            "startup": {"background_grace_seconds"},
        }

        for section, keys in expected.items():
            with self.subTest(section=section):
                self.assertTrue(keys <= set(schema[section]["items"]))

    def test_unconsumed_controls_are_not_exposed(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertFalse(
            {
                "token_budget_per_person_day",
                "token_budget_global_day",
                "context_message_limit",
                "context_char_limit",
            }
            & set(schema["portrait"]["items"])
        )
        self.assertNotIn("memory_decay_max_access_count", schema["maintenance_decay"]["items"])

    def test_p5_status_reads_the_configured_namespaced_gates(self) -> None:
        status = build_p5_status(
            ConfigView(
                {
                    "private_companion_bridge": {
                        "enable_p5_b1_recall_gate": True,
                        "enable_p5_b1_bridge_gate": False,
                    }
                }
            )
        )
        self.assertEqual(
            {"health": "degraded", "mode": "partial", "enabled_count": 1, "total_count": 2, "reason_code": "partial_coverage"},
            status["attestation_read"],
        )
        self.assertEqual("contract_not_available", status["sink_boundary"]["reason_code"])
        self.assertEqual("contract_not_available", status["security_recovery"]["reason_code"])
