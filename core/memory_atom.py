from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any


MEMORY_ATOM_KEY_PREFIX = "mav2"
VALIDITY_STATUSES = frozenset(
    {"active", "superseded", "expired", "archived", "deleted", "quarantined"}
)
DURABILITY_LEVELS = frozenset({"ephemeral", "short", "normal", "durable", "pinned"})
SENSITIVITY_LEVELS = frozenset({"public", "internal", "private", "restricted"})

_SCOPED_KEY_RE = re.compile(r"^mav2:([0-9a-f]{24}):([0-9a-f]{40})$")


def row_value(row: Any, key: str, default: Any = None) -> Any:
    """Read a sqlite Row or mapping without assuming a newly added column exists."""

    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return default


def normalize_validity_status(value: Any, default: str = "active") -> str:
    text = _text(value, 24).lower()
    if not text:
        return default
    return text if text in VALIDITY_STATUSES else "quarantined"


def normalize_durability(value: Any, default: str = "normal") -> str:
    text = _text(value, 24).lower()
    return text if text in DURABILITY_LEVELS else default


def normalize_sensitivity(value: Any, default: str = "private") -> str:
    text = _text(value, 24).lower()
    if not text:
        return default
    return text if text in SENSITIVITY_LEVELS else "restricted"


def clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, number)


def durability_from_legacy_metadata(metadata: Mapping[str, Any]) -> str:
    explicit = _text(metadata.get("durability"), 24).lower()
    if explicit:
        return normalize_durability(explicit)
    decay_mode = _text(metadata.get("decay_mode"), 40).lower()
    if decay_mode == "no_decay":
        return "pinned"
    if decay_mode in {"scar_slow_decay", "creative_milestone", "slow_decay"}:
        return "durable"
    if decay_mode == "summary_decay":
        return "short"
    return "normal"


def durability_for_memory_type(memory_type: Any, fallback: str = "normal") -> str:
    kind = _text(memory_type, 80).lower()
    if kind in {"manual_memory", "explicit_memory"}:
        return "pinned"
    if kind in {
        "user_profile",
        "user_preference",
        "relationship_claim",
        "promise",
        "open_loop",
        "creative_work",
    }:
        return "durable"
    if kind in {
        "emotion_state",
        "current_state",
        "schedule_fragment",
        "bot_detail_fragment",
        "proactive_message",
    }:
        return "short"
    if kind in {"raw_event", "timeline_event"}:
        return "ephemeral"
    return normalize_durability(fallback)


def scoped_canonical_key(
    *,
    owner_bot_id: Any,
    platform: Any,
    scope: Any,
    session_id: Any,
    group_id: Any,
    subject_kind: Any,
    subject_id: Any,
    object_kind: Any,
    object_id: Any,
    memory_type: Any,
    content: Any,
    seed: Any = "",
) -> str:
    domain = _domain_digest(
        owner_bot_id,
        platform,
        scope,
        session_id,
        group_id,
        subject_kind,
        subject_id,
        object_kind,
        object_id,
    )
    semantic = _existing_semantic_digest(seed)
    if not semantic:
        semantic = _digest("canonical", memory_type, seed or content)
    return f"{MEMORY_ATOM_KEY_PREFIX}:{domain}:{semantic}"


def scoped_content_fingerprint(
    *,
    owner_bot_id: Any,
    platform: Any,
    scope: Any,
    session_id: Any,
    group_id: Any,
    subject_kind: Any,
    subject_id: Any,
    object_kind: Any,
    object_id: Any,
    memory_type: Any,
    visibility: Any,
    reality_level: Any,
    content: Any,
    canonical_key: Any,
    seed: Any = "",
) -> str:
    domain = _domain_digest(
        owner_bot_id,
        platform,
        scope,
        session_id,
        group_id,
        subject_kind,
        subject_id,
        object_kind,
        object_id,
    )
    semantic = _existing_semantic_digest(seed)
    if not semantic:
        # A caller-provided legacy fingerprint remains an idempotency seed, but
        # the v2 wrapper binds it to the current owner/platform/scope domain.
        material = seed or content
        semantic = _digest(
            "content",
            memory_type,
            canonical_key,
            visibility,
            reality_level,
            material,
        )
    return f"{MEMORY_ATOM_KEY_PREFIX}:{domain}:{semantic}"


def validity_where_clause(
    *,
    statuses: Iterable[str] | None = None,
    valid_at: str = "",
    table_alias: str = "",
) -> tuple[str, list[Any]]:
    """Build a reusable fail-closed status/time predicate for memory reads."""

    prefix = f"{table_alias}." if table_alias else ""
    normalized = []
    for value in statuses or ("active",):
        text = _text(value, 24).lower()
        if text in VALIDITY_STATUSES and text not in normalized:
            normalized.append(text)
    if not normalized:
        normalized = ["active"]
    placeholders = ",".join("?" for _ in normalized)
    clauses = [f"{prefix}validity_status IN ({placeholders})"]
    params: list[Any] = list(normalized)
    at = _text(valid_at, 80)
    if at:
        clauses.extend(
            [
                (
                    f"({prefix}valid_from='' OR "
                    f"(julianday({prefix}valid_from) IS NOT NULL "
                    f"AND julianday({prefix}valid_from)<=julianday(?)))"
                ),
                (
                    f"({prefix}valid_to='' OR "
                    f"(julianday({prefix}valid_to) IS NOT NULL "
                    f"AND julianday({prefix}valid_to)>julianday(?)))"
                ),
            ]
        )
        params.extend([at, at])
    return " AND ".join(clauses), params


def _existing_semantic_digest(value: Any) -> str:
    match = _SCOPED_KEY_RE.fullmatch(_text(value, 160).lower())
    return match.group(2) if match else ""


def _domain_digest(*parts: Any) -> str:
    return _digest("domain", *parts)[:24]


def _digest(*parts: Any) -> str:
    raw = "|".join(_text(part, 2000).casefold() for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _text(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
    return text[:limit]


__all__ = [
    "DURABILITY_LEVELS",
    "MEMORY_ATOM_KEY_PREFIX",
    "SENSITIVITY_LEVELS",
    "VALIDITY_STATUSES",
    "clamp_score",
    "durability_from_legacy_metadata",
    "nonnegative_int",
    "normalize_durability",
    "normalize_sensitivity",
    "normalize_validity_status",
    "row_value",
    "scoped_canonical_key",
    "scoped_content_fingerprint",
    "validity_where_clause",
]
