from __future__ import annotations

"""Deterministic retrieval lifecycle policy for Memory Atom v2.

This module deliberately has no store dependency.  It can evaluate both v2
rows and legacy rows whose governance values still live in metadata.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import MemoryRecord, SessionContext, clean_text, clamp_float


ACTIVE_STATUSES = frozenset({"active"})
NON_RETRIEVABLE_STATUSES = frozenset(
    {"superseded", "expired", "archived", "deleted", "quarantined"}
)
HALF_LIFE_DAYS = {
    "ephemeral": 1.0,
    "short": 14.0,
    "normal": 120.0,
    "durable": 730.0,
    "pinned": math.inf,
}


@dataclass(frozen=True, slots=True)
class LifecycleScore:
    eligible: bool
    reason: str
    decay_factor: float
    salience: float
    reinforcement: float


def _metadata(memory: MemoryRecord) -> dict[str, Any]:
    value = getattr(memory, "metadata", {})
    return value if isinstance(value, dict) else {}


def _field(memory: MemoryRecord, name: str, default: Any = "") -> Any:
    value = getattr(memory, name, None)
    if value not in (None, ""):
        return value
    return _metadata(memory).get(name, default)


def _moment(value: Any) -> datetime | None:
    text = clean_text(value, 96)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _durability(memory: MemoryRecord) -> str:
    value = clean_text(_field(memory, "durability", ""), 32).lower()
    if value in HALF_LIFE_DAYS:
        return value
    metadata = _metadata(memory)
    mode = clean_text(metadata.get("decay_mode"), 48).lower()
    tags = {clean_text(tag, 64).lower() for tag in (memory.tags or [])}
    if mode == "no_decay" or tags & {"pinned", "manual_keep", "never_forget"}:
        return "pinned"
    if mode in {"scar_slow_decay", "creative_milestone", "slow_decay"}:
        return "durable"
    if memory.memory_type in {
        "user_profile", "user_preference", "relationship_claim", "manual_memory",
        "explicit_memory", "promise", "open_loop",
    }:
        return "durable"
    if memory.memory_type in {"emotion_state", "current_state", "schedule_fragment", "bot_detail_fragment"}:
        return "short"
    return "normal"


def evaluate_memory_lifecycle(
    memory: MemoryRecord,
    ctx: SessionContext,
    *,
    now: datetime | None = None,
    admin_read_all: bool = False,
) -> LifecycleScore:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    status = clean_text(_field(memory, "validity_status", "active"), 32).lower() or "active"
    if status in NON_RETRIEVABLE_STATUSES or status not in ACTIVE_STATUSES:
        return LifecycleScore(False, f"validity={status}", 0.0, 0.0, 0.0)

    valid_from = _moment(_field(memory, "valid_from", ""))
    valid_to = _moment(_field(memory, "valid_to", ""))
    if valid_from is not None and current < valid_from:
        return LifecycleScore(False, "validity=not_started", 0.0, 0.0, 0.0)
    if valid_to is not None and current >= valid_to:
        return LifecycleScore(False, "validity=expired", 0.0, 0.0, 0.0)

    sensitivity = clean_text(_field(memory, "sensitivity", "internal"), 32).lower() or "internal"
    if sensitivity == "restricted":
        return LifecycleScore(False, "sensitivity=restricted", 0.0, 0.0, 0.0)

    if not admin_read_all:
        owner_bot_id = clean_text(_field(memory, "owner_bot_id", ""), 160)
        context_bot_id = clean_text(getattr(ctx, "bot_id", ""), 160)
        # ``self`` is the official owner-neutral sentinel used when a producer
        # has no concrete bot id.  Admin bypass must not regress that normal
        # recall compatibility rule.
        if owner_bot_id and owner_bot_id != "self" and (
            not context_bot_id or owner_bot_id != context_bot_id
        ):
            return LifecycleScore(False, "owner_bot_mismatch", 0.0, 0.0, 0.0)
        persona_id = clean_text(_field(memory, "persona_id", ""), 96)
        context_persona_id = clean_text(getattr(ctx, "persona_id", ""), 96)
        if persona_id and persona_id != "legacy":
            if not context_persona_id:
                return LifecycleScore(False, "persona_context_missing", 0.0, 0.0, 0.0)
            if persona_id != context_persona_id:
                return LifecycleScore(False, "persona_mismatch", 0.0, 0.0, 0.0)

    durability = _durability(memory)
    half_life = HALF_LIFE_DAYS[durability]
    occurred = _moment(memory.occurred_at or memory.updated_at or memory.created_at)
    age_days = max(0.0, (current - occurred).total_seconds() / 86400.0) if occurred else 0.0
    decay_factor = 1.0 if math.isinf(half_life) else math.exp(-math.log(2.0) * age_days / half_life)
    # Soft decay may lower rank but never silently delete an otherwise active
    # fact.  Archive/expiration decisions live in the maintenance pipeline.
    decay_factor = max(0.05, min(1.0, decay_factor))
    salience = clamp_float(_field(memory, "salience", memory.importance), default=memory.importance)
    reinforcement = clamp_float(_field(memory, "reinforcement_score", 0.0), default=0.0)
    return LifecycleScore(
        True,
        f"validity=active;durability={durability};sensitivity={sensitivity}",
        decay_factor,
        salience,
        reinforcement,
    )


def apply_lifecycle_score(base_score: float, lifecycle: LifecycleScore) -> float:
    if not lifecycle.eligible:
        return 0.0
    freshness_multiplier = 0.65 + (0.35 * lifecycle.decay_factor)
    salience_bonus = lifecycle.salience * 0.12
    reinforcement_bonus = min(0.12, lifecycle.reinforcement * 0.12)
    return max(0.0, (float(base_score) * freshness_multiplier) + salience_bonus + reinforcement_bonus)


__all__ = [
    "ACTIVE_STATUSES",
    "HALF_LIFE_DAYS",
    "LifecycleScore",
    "NON_RETRIEVABLE_STATUSES",
    "apply_lifecycle_score",
    "evaluate_memory_lifecycle",
]
