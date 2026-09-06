from __future__ import annotations

import unittest

from .package_bootstrap import bootstrap_package

bootstrap_package()

from astrbot_plugin_memory_companion.core.memory_proposal import MemoryProposal


class MemoryProposalTests(unittest.TestCase):
    def test_normalizes_model_values_without_lexical_triggers(self) -> None:
        proposal = MemoryProposal.from_payload(
            "  用户喜欢在周末跑步  ",
            {
                "confidence": 2,
                "importance": -1,
                "durability": "durable",
                "validity_status": "active",
                "evidence_refs": ["event-1", "", "event-2"],
                "rationale": "多轮明确表达",
            },
        )
        self.assertEqual("用户喜欢在周末跑步", proposal.content)
        self.assertEqual(1.0, proposal.confidence)
        self.assertEqual(0.0, proposal.importance)
        self.assertEqual(("event-1", "event-2"), proposal.evidence_refs)
        self.assertEqual("memory-proposal-v1", proposal.as_metadata()["proposal_schema"])

    def test_invalid_governance_values_fail_closed_to_safe_defaults(self) -> None:
        proposal = MemoryProposal.from_payload("fact", {"durability": "made-up", "validity_status": "made-up"})
        self.assertEqual("normal", proposal.durability)
        self.assertEqual("quarantined", proposal.validity_status)

    def test_note_type_alias_inherits_memory_lifecycle_defaults(self) -> None:
        proposal = MemoryProposal.from_payload("喜欢蓝风铃", {"note_type": "preference"})
        self.assertEqual("user_preference", proposal.memory_type)
        self.assertEqual("durable", proposal.durability)

    def test_boolean_strings_are_normalized(self) -> None:
        proposal = MemoryProposal.from_payload("仅本轮", {"requested_persistence": "false"})
        self.assertFalse(proposal.requested_persistence)


if __name__ == "__main__":
    unittest.main()
