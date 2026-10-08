from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if "astrbot_plugin_remember_you" not in sys.modules:
    package = types.ModuleType("astrbot_plugin_remember_you")
    package.__path__ = [str(ROOT)]
    sys.modules["astrbot_plugin_remember_you"] = package
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core import bot_personal_contract as contract


class C1ContractTests(unittest.TestCase):
    def test_frozen_contract_values_and_self_check(self) -> None:
        self.assertEqual("ecf1d69406a8445d", contract.CONTRACT_FINGERPRINT)
        self.assertEqual(3, contract.CONTRACT_REVISION)
        self.assertEqual("1.3", contract.BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION)
        self.assertEqual(3, contract.BOT_PERSONAL_CANONICAL_SCHEMA_VERSION)
        self.assertEqual("1.0", contract.BOT_PERSONAL_PAYLOAD_SCHEMA_VERSION)
        self.assertEqual("bot_self_schedule", contract.BOT_PERSONAL_MEMORY_DOMAIN)
        self.assertEqual(12, len(contract.BOT_PERSONAL_MEMORY_TYPES))
        self.assertEqual(set(contract.TYPE_CONTRACTS), set(contract.BOT_PERSONAL_MEMORY_TYPES))
        self.assertEqual([], contract.contract_self_check())
        self.assertEqual(contract.CONTRACT_FINGERPRINT, contract.compute_contract_fingerprint())

    def test_five_window_boundaries_and_midnight_wrap(self) -> None:
        expected = {
            0: "late_night",
            359: "late_night",
            360: "morning",
            659: "morning",
            660: "noon",
            869: "noon",
            870: "afternoon",
            1079: "afternoon",
            1080: "evening",
            1259: "evening",
            1260: "late_night",
            1439: "late_night",
        }
        for minutes, slug in expected.items():
            self.assertEqual(slug, contract.window_for_minutes(minutes))
        self.assertEqual("late_night", contract.window_for_minutes(-1))
        self.assertEqual("late_night", contract.window_for_minutes(24 * 60))

    def test_normalize_window_and_legacy_migration_never_guesses_without_timestamp(self) -> None:
        self.assertEqual("morning", contract.normalize_window(" MORNING "))
        self.assertEqual("late_night", contract.normalize_window("凌晨"))
        self.assertEqual("", contract.normalize_window("unknown"))
        self.assertEqual("late_night", contract.migrate_legacy_window("late_night"))
        self.assertEqual("", contract.migrate_legacy_window("morning"))
        self.assertEqual("", contract.migrate_legacy_window("afternoon"))
        self.assertEqual("", contract.migrate_legacy_window("evening"))
        self.assertEqual("noon", contract.migrate_legacy_window("morning", 11 * 60))

    def test_descriptor_fields_are_self_consistent(self) -> None:
        descriptor = contract.capability_descriptor()
        self.assertTrue(descriptor["available"])
        self.assertFalse(descriptor["read_only"])
        self.assertEqual("ecf1d69406a8445d", descriptor["contract_fingerprint"])
        self.assertEqual(3, descriptor["contract_revision"])
        self.assertEqual("1.3", descriptor["capability_schema_version"])
        self.assertEqual(3, descriptor["canonical_schema_version"])
        self.assertEqual("1.0", descriptor["payload_schema_version"])
        self.assertEqual("bot_self_schedule", descriptor["memory_domain"])
        self.assertEqual(list(contract.WINDOW_SLUGS), descriptor["windows"])
        self.assertEqual(12, len(descriptor["memory_types"]))
