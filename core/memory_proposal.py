"""AI-facing memory proposal contract.

The model decides *what* is worth remembering.  This small value object only
normalizes the proposal before the storage layer applies scope, privacy and
size invariants.  It intentionally contains no trigger words or classifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .memory_atom import (
    clamp_score,
    durability_for_memory_type,
    normalize_durability,
    normalize_validity_status,
)
from .models import clean_text


_TYPE_ALIASES = {
    "memory": "tool_memory",
    "preference": "user_preference",
    "profile": "user_profile",
    "habit": "user_habit",
    "relationship": "relationship_claim",
    "promise": "promise",
    "event": "timeline_event",
}


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"0", "false", "no", "off", "否", "不要"}:
            return False
        if text in {"1", "true", "yes", "on", "是", "要"}:
            return True
        return default
    if value is None:
        return default
    return bool(value)


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    """A bounded, evidence-carrying request to write a memory atom."""

    content: str
    memory_type: str = "tool_memory"
    confidence: float = 0.62
    importance: float = 0.66
    durability: str = "normal"
    validity_status: str = "active"
    valid_from: str = ""
    valid_to: str = ""
    rationale: str = ""
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    requested_persistence: bool = True

    @classmethod
    def from_payload(cls, content: Any, payload: Mapping[str, Any] | None = None) -> "MemoryProposal":
        data = payload if isinstance(payload, Mapping) else {}
        refs = data.get("evidence_refs", data.get("evidence", ()))
        if isinstance(refs, str):
            refs = (refs,)
        elif not isinstance(refs, (list, tuple, set)):
            refs = ()
        normalized_refs = tuple(
            item for item in (clean_text(value, 160) for value in refs) if item
        )[:16]
        raw_type = clean_text(data.get("memory_type") or data.get("note_type") or "tool_memory", 80).lower()
        raw_durability = data.get("durability")
        canonical_type = _TYPE_ALIASES.get(raw_type, raw_type)
        default_durability = durability_for_memory_type(canonical_type, "normal")
        return cls(
            content=clean_text(content, 3000),
            memory_type=_TYPE_ALIASES.get(raw_type, raw_type) or "tool_memory",
            confidence=clamp_score(data.get("confidence"), 0.62),
            importance=clamp_score(data.get("importance"), 0.66),
            durability=normalize_durability(raw_durability, default_durability),
            validity_status=normalize_validity_status(data.get("validity_status"), "active"),
            valid_from=clean_text(data.get("valid_from"), 80),
            valid_to=clean_text(data.get("valid_to"), 80),
            rationale=clean_text(data.get("rationale") or data.get("reason"), 300),
            evidence_refs=normalized_refs,
            requested_persistence=_coerce_bool(
                data.get("requested_persistence", data.get("persist", True)),
                True,
            ),
        )

    def as_metadata(self) -> dict[str, Any]:
        return {
            "proposal_schema": "memory-proposal-v1",
            "proposal_memory_type": self.memory_type,
            "proposal_confidence": self.confidence,
            "proposal_importance": self.importance,
            "proposal_durability": self.durability,
            "proposal_validity_status": self.validity_status,
            "proposal_rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
            "requested_persistence": self.requested_persistence,
        }


__all__ = ["MemoryProposal"]
