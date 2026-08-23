"""Read-only, provenance-aware rendering of approved portrait facts.

``PortraitService.read_summary`` remains the policy boundary.  This module
only formats the already filtered result; it never writes facts, evidence,
queue entries, capabilities, or suppression markers.  The renderer accepts
only facts carrying opaque fact/evidence references so every natural-language
sentence can be audited without copying historical message text.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Awaitable, Callable, Mapping


PORTRAIT_RENDER_SCHEMA = "portrait.render.v1"
LOW_SENSITIVITY = "low"

# Keep this allowlist deliberately small.  New dimensions must be reviewed
# before becoming visible in an administrator/agent portrait projection.
DIMENSION_CATEGORIES: dict[str, tuple[str, str]] = {
    "preferred_address": ("stable_facts", "称呼偏好"),
    "birthday": ("stable_facts", "生日"),
    "occupation": ("stable_facts", "职业"),
    "education": ("stable_facts", "专业/学业"),
    "zodiac": ("stable_facts", "星座"),
    "blood_type": ("stable_facts", "血型"),
    "preference": ("preferences", "偏好"),
    "interest": ("interests", "兴趣"),
    "communication_preference": ("communication_style", "沟通习惯"),
    "interaction_preference": ("interaction_preferences", "互动偏好"),
    "habit": ("habits", "习惯"),
    "dietary_restriction": ("boundaries", "饮食边界"),
    "boundary": ("boundaries", "沟通边界"),
}

CATEGORY_ORDER = (
    "stable_facts",
    "habits",
    "preferences",
    "interests",
    "communication_style",
    "interaction_preferences",
    "boundaries",
)
_CATEGORY_INDEX = {name: index for index, name in enumerate(CATEGORY_ORDER)}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: Any, limit: int = 240) -> str:
    if value is None or isinstance(value, bool):
        return ""
    text = str(value).replace("\x00", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _fact_id(value: Any) -> str:
    # Store-generated IDs are opaque references; do not expose arbitrary
    # caller-provided long strings in an audit projection.
    return _text(value, 120)


def _evidence_refs(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    refs: list[str] = []
    for item in value[:16]:
        ref = _text(item, 80).lower()
        if _HASH_RE.fullmatch(ref) and ref not in refs:
            refs.append(ref)
    return refs


def _punctuate(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    return value if value.endswith(("。", "！", "？", ".", "!", "?")) else f"{value}。"


def _sentence_for_fact(fact: Mapping[str, Any], label: str) -> str:
    summary = _text(fact.get("summary"), 180)
    if not summary:
        return ""
    epistemic = _text(fact.get("epistemic_status"), 40).lower()
    if epistemic == "inferred":
        # Keep inferred facts visibly tentative even if a producer happened to
        # omit a hedge from ``claim_summary``.
        return _punctuate(f"从多条独立证据看，{label}：{summary}")
    return _punctuate(f"{label}：{summary}")


def _safe_fact(item: Any) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(item, Mapping):
        return None, "malformed"
    dimension = _text(item.get("dimension"), 80).lower()
    category_label = DIMENSION_CATEGORIES.get(dimension)
    if category_label is None:
        return None, "unsupported_dimension"
    if _text(item.get("sensitivity"), 24).lower() != LOW_SENSITIVITY:
        return None, "sensitivity"
    if _text(item.get("status"), 40) not in {"", "active"}:
        return None, "inactive"
    epistemic = _text(item.get("epistemic_status"), 40).lower()
    if epistemic not in {"explicit", "inferred"}:
        return None, "epistemic_status"
    # Interests are intentionally more restrictive than ordinary low-risk
    # preferences: an inferred interest is not a supported portrait claim.
    if dimension == "interest" and epistemic != "explicit":
        return None, "interest_requires_explicit"
    summary = _text(item.get("summary"), 180)
    provenance = item.get("provenance")
    if not isinstance(provenance, Mapping):
        return None, "provenance_missing"
    fact_id = _fact_id(provenance.get("fact_id"))
    evidence_refs = _evidence_refs(provenance.get("evidence_refs"))
    if not fact_id:
        return None, "fact_reference_missing"
    if not evidence_refs:
        return None, "evidence_reference_missing"
    if not summary:
        return None, "summary_missing"
    category, label = category_label
    try:
        confidence = float(item.get("confidence") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return None, "confidence_invalid"
    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        return None, "confidence_invalid"
    fact = {
        "fact_id": fact_id,
        "dimension": dimension,
        "category": category,
        "summary": summary,
        "portrait_tier": _text(item.get("portrait_tier"), 24),
        "epistemic_status": epistemic,
        "confidence": confidence,
        "sensitivity": LOW_SENSITIVITY,
        "usable_scope": _text(item.get("usable_scope"), 80),
        "updated_at": _text(item.get("updated_at"), 80),
        "provenance": {
            "fact_id": fact_id,
            "evidence_refs": evidence_refs,
            "source_scope": _text(provenance.get("source_scope"), 80),
            "first_evidence_at": _text(provenance.get("first_evidence_at"), 80),
            "last_evidence_at": _text(provenance.get("last_evidence_at"), 80),
        },
    }
    fact["sentence"] = _sentence_for_fact(fact, label)
    if not fact["sentence"]:
        return None, "summary_missing"
    return fact, ""


def render_portrait_items(
    items: Any,
    *,
    portrait_revision: int = 0,
    last_synced_at: Any = "",
    person_id: Any = "",
    code: str = "profile_exact",
    ok: bool = True,
) -> dict[str, Any]:
    """Render an already governed summary without performing any I/O.

    The input is expected to be the ``items`` list returned by
    ``MemoryStore.portrait_summary(..., include_provenance=True)``.  Rows that
    do not carry a traceable reference are omitted rather than rendered as
    un-auditable prose.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    omitted: dict[str, int] = defaultdict(int)
    seen: set[tuple[str, str, str]] = set()
    for item in items if isinstance(items, list) else []:
        fact, reason = _safe_fact(item)
        if fact is None:
            omitted[reason or "invalid"] += 1
            continue
        key = (fact["fact_id"], fact["dimension"], fact["summary"])
        if key in seen:
            omitted["duplicate"] += 1
            continue
        seen.add(key)
        grouped[fact["dimension"]].append(fact)

    for dimension, facts in grouped.items():
        facts.sort(
            key=lambda value: (
                -float(value.get("confidence") or 0.0),
                _text(value.get("updated_at"), 80),
                _text(value.get("fact_id"), 120),
            )
        )
    dimensions = {
        dimension: grouped[dimension]
        for dimension in sorted(
            grouped,
            key=lambda value: (
                _CATEGORY_INDEX.get(DIMENSION_CATEGORIES[value][0], 999),
                value,
            ),
        )
    }
    facts = [fact for dimension in dimensions.values() for fact in dimension]
    sentences = [
        {
            "text": fact["sentence"],
            "fact_id": fact["fact_id"],
            "dimension": fact["dimension"],
            "evidence_refs": list(fact["provenance"]["evidence_refs"]),
        }
        for fact in facts
    ]
    for fact in facts:
        fact.pop("sentence", None)
    natural_language = " ".join(item["text"] for item in sentences)
    return {
        "ok": bool(ok),
        "read_only": True,
        "code": _text(code, 80) or "profile_exact",
        "schema_version": PORTRAIT_RENDER_SCHEMA,
        "person_id": _text(person_id, 80),
        "portrait_revision": _nonnegative_int(portrait_revision),
        "last_synced_at": _text(last_synced_at, 80),
        "dimensions": dimensions,
        "structured": dimensions,
        "facts": facts,
        "sentences": sentences,
        "natural_language": natural_language,
        "text": natural_language,
        "governance": {
            "approved_only": True,
            "active_only": True,
            "max_sensitivity": LOW_SENSITIVITY,
            "provenance_required": True,
        },
        "omitted": {
            "count": sum(omitted.values()),
            "reasons": dict(sorted(omitted.items())),
        },
    }


class PortraitRenderer:
    """Read-only adapter over ``PortraitService.read_summary``."""

    def __init__(self, portrait_service: Any):
        self.portrait_service = portrait_service

    async def render(self, request: dict[str, Any], *, limit: int = 16) -> dict[str, Any]:
        """Authorize and render one subject without changing store state."""
        reader: Callable[..., Awaitable[dict[str, Any]]] = self.portrait_service.read_summary
        result = await reader(
            request,
            limit=max(1, min(32, int(limit))),
            include_provenance=True,
        )
        if not isinstance(result, dict):
            return render_portrait_items([], ok=False, code="bridge_degraded")
        target = request.get("target_person_id") if isinstance(request, dict) else ""
        return render_portrait_items(
            result.get("items"),
            portrait_revision=result.get("portrait_revision", 0),
            last_synced_at=result.get("last_synced_at", ""),
            person_id=target if bool(result.get("ok")) else "",
            code=_text(result.get("code"), 80) or "bridge_degraded",
            ok=bool(result.get("ok")),
        )


__all__ = [
    "CATEGORY_ORDER",
    "DIMENSION_CATEGORIES",
    "PORTRAIT_RENDER_SCHEMA",
    "PortraitRenderer",
    "render_portrait_items",
]
