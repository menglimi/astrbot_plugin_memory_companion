from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any
from zoneinfo import ZoneInfo

from .models import MemoryRecord, clean_text


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class _AuthenticatedCompanionProjection(dict):
    """Signed request-scoped dict accepted only after bridge attestation."""

    __slots__ = (
        "_bot_id",
        "_kind",
        "_person_id",
        "_platform",
        "_scope",
        "_session_id",
        "_signature",
    )

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        kind: str,
        bot_id: str,
        platform: str,
        person_id: str,
        scope: str,
        session_id: str,
        signature: str,
    ) -> None:
        dict.__init__(self, payload)
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_bot_id", bot_id)
        object.__setattr__(self, "_platform", platform)
        object.__setattr__(self, "_person_id", person_id)
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_session_id", session_id)
        object.__setattr__(self, "_signature", signature)

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("authenticated Companion projections are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __setattr__ = _immutable
    __delattr__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _canonical_companion_projection_message(
    payload: dict[str, Any],
    *,
    kind: str,
    bot_id: str,
    platform: str,
    person_id: str,
    scope: str,
    session_id: str,
) -> bytes:
    return json.dumps(
        {
            "kind": kind,
            "bot_id": bot_id,
            "platform": platform,
            "person_id": person_id,
            "scope": scope,
            "session_id": session_id,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_companion_projection_signature(
    payload: dict[str, Any],
    *,
    secret: bytes,
    kind: str,
    bot_id: str,
    platform: str,
    person_id: str,
    scope: str,
    session_id: str,
) -> str:
    body = _canonical_companion_projection_message(
        payload,
        kind=kind,
        bot_id=bot_id,
        platform=platform,
        person_id=person_id,
        scope=scope,
        session_id=session_id,
    )
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def _verify_companion_projection_signature(
    payload: dict[str, Any],
    signature: str,
    *,
    secret: bytes,
    kind: str,
    bot_id: str,
    platform: str,
    person_id: str,
    scope: str,
    session_id: str,
) -> bool:
    expected = _canonical_companion_projection_signature(
        payload,
        secret=secret,
        kind=kind,
        bot_id=bot_id,
        platform=platform,
        person_id=person_id,
        scope=scope,
        session_id=session_id,
    )
    return hmac.compare_digest(expected, signature)


_COMPANION_RELATIONSHIP_PHASES = {
    "deeply_distant",
    "strongly_distant",
    "distant",
    "acquaintance",
    "familiar",
    "close",
    "intimate",
    "deeply_bonded",
}
_COMPANION_INTERACTION_BANDS = {
    "avoidant",
    "hurt",
    "relaxed",
    "lively",
    "warm",
    "close",
    "affectionate",
}
_COMPANION_EXPRESSION_CONTRACTS = {
    "companion_interaction_expression.v1",
    "companion_interaction_expression.v2",
}
_COMPANION_EXPRESSION_PACING = {"slow", "steady", "bright"}
_COMPANION_EXPRESSION_DIRECTNESS = {"indirect", "natural", "direct"}
_COMPANION_EXPRESSION_VALIDATION = {"none", "acknowledge", "support_first"}
_COMPANION_EXPRESSION_DISCLOSURE = {"none", "light", "allowed"}
_COMPANION_EXPRESSION_HUMOR = {"off", "light", "playful"}
_COMPANION_EXPRESSION_TOPIC = {"reply_only", "followup", "shared_topic"}
_COMPANION_EXPRESSION_BEHAVIORS = {
    "acknowledge",
    "brief_reply",
    "give_space",
    "reply",
    "clarify",
    "light_humor",
    "followup",
    "support",
    "shared_ritual",
    "affectionate_expression",
}
_COMPANION_EXPRESSION_SAFETY_MODES = {
    "normal",
    "contact_boundary_passive",
    "contact_boundary",
    "p4_blocked",
}
_COMPANION_EXPRESSION_BLOCKERS = {"contact_boundary", "p4_safety"}
_COMPANION_EXPRESSION_REASON_CODES = {
    "relationship_baseline_retained",
    "interaction_band_applied",
    "administrator_override_applied",
    "owner_role_required",
    "contact_boundary_passive_reengagement",
    "p4_warmth_cap_applied",
    "relationship_tone_applied",
    "relationship_address_applied",
    "relationship_followup_cap",
    "intent_followup_suppressed",
    "low_energy_expression_cap",
    "down_mood_expression_cap",
    "up_mood_expression_lift",
    "affect_modulation_applied",
    "relationship_proactive_cap",
    "interaction_proactive_suppressed",
    "schedule_proactive_suppressed",
    "p4_blocked",
    "contact_boundary",
}


def sanitize_companion_expression_decision(value: Any) -> dict[str, Any]:
    """Accept only the bounded, request-scoped Companion expression contract."""

    fallback = {"status": "invalid", "read_only": True, "decision": {}}
    if (
        type(value) is not dict
        or value.get("contract") not in _COMPANION_EXPRESSION_CONTRACTS
    ):
        return fallback
    expression_band = value.get("expression_band")
    if (
        type(expression_band) is not str
        or expression_band not in _COMPANION_INTERACTION_BANDS
    ):
        return fallback
    allowed_behaviors = value.get("allowed_behaviors")
    if type(allowed_behaviors) not in {list, tuple} or len(allowed_behaviors) > 12:
        return fallback
    if any(
        type(item) is not str or item not in _COMPANION_EXPRESSION_BEHAVIORS
        for item in allowed_behaviors
    ):
        return fallback
    if len(set(allowed_behaviors)) != len(allowed_behaviors):
        return fallback
    safety_mode = value.get("safety_mode")
    if (
        type(safety_mode) is not str
        or safety_mode not in _COMPANION_EXPRESSION_SAFETY_MODES
    ):
        return fallback
    blocker = value.get("blocker")
    if blocker is not None and (
        type(blocker) is not str or blocker not in _COMPANION_EXPRESSION_BLOCKERS
    ):
        return fallback
    reason_codes = value.get("reason_codes")
    if type(reason_codes) not in {list, tuple} or len(reason_codes) > 24:
        return fallback
    if any(
        type(item) is not str or item not in _COMPANION_EXPRESSION_REASON_CODES
        for item in reason_codes
    ):
        return fallback
    if type(value.get("followup")) is not bool:
        return fallback
    contract = value.get("contract")
    dimensions: dict[str, str] = {}
    if contract == "companion_interaction_expression.v2":
        dimension_specs = {
            "pacing": _COMPANION_EXPRESSION_PACING,
            "directness": _COMPANION_EXPRESSION_DIRECTNESS,
            "validation_style": _COMPANION_EXPRESSION_VALIDATION,
            "self_disclosure": _COMPANION_EXPRESSION_DISCLOSURE,
            "humor_mode": _COMPANION_EXPRESSION_HUMOR,
            "topic_initiative": _COMPANION_EXPRESSION_TOPIC,
        }
        for key, allowed in dimension_specs.items():
            item = value.get(key)
            if type(item) is not str or item not in allowed:
                return fallback
            dimensions[key] = item
    return {
        "status": "accepted",
        "read_only": True,
        "decision": {
            "contract": contract,
            "expression_band": expression_band,
            "allowed_behaviors": list(allowed_behaviors),
            "safety_mode": safety_mode,
            "blocker": blocker,
            "reason_codes": list(reason_codes),
            "followup": value["followup"],
            **dimensions,
        },
    }


def sanitize_companion_relationship_projection(value: Any) -> dict[str, Any]:
    fallback = {"status": "invalid", "read_only": True, "projection": {}}
    if type(value) is not dict:
        return fallback
    if value.get("schema_version") != "chat.relationship_projection.v1":
        return fallback
    if (
        value.get("authority") != "private_companion.relationship_score"
        or value.get("read_only") is not True
    ):
        return fallback
    phase_key = value.get("phase_key")
    if (
        type(phase_key) is not str
        or phase_key not in _COMPANION_RELATIONSHIP_PHASES
    ):
        return fallback
    score = value.get("score")
    if type(score) is not int or not -1200 <= score <= 1200:
        return fallback
    soft = value.get("soft_behaviors")
    if type(soft) is not dict or any(
        type(item) is not bool for item in soft.values()
    ):
        return fallback
    try:
        proactive_care_limit = int(value.get("proactive_care_limit") or 0)
    except (TypeError, ValueError):
        proactive_care_limit = 0
    projection = {
        "schema_version": "chat.relationship_projection.v1",
        "authority": "private_companion.relationship_score",
        "read_only": True,
        "score": score,
        "phase_key": phase_key,
        "phase_label": clean_text(value.get("phase_label"), 40),
        "tone": clean_text(value.get("tone"), 160),
        "address_level": clean_text(value.get("address_level"), 120),
        "proactive_care_limit": max(0, min(30, proactive_care_limit)),
        "soft_behaviors": {
            key: bool(soft.get(key, False))
            for key in (
                "allow_playful_jokes",
                "allow_followup",
                "allow_memory_mention",
                "allow_daily_care",
            )
        },
    }
    relationship_mode = value.get("relationship_mode")
    if relationship_mode in {"normal", "owner_exclusive"}:
        projection["relationship_mode"] = relationship_mode
    current_interaction = value.get("current_interaction")
    if type(current_interaction) is dict:
        expression_band = current_interaction.get("expression_band")
        if (
            type(expression_band) is str
            and expression_band in _COMPANION_INTERACTION_BANDS
        ):
            interaction_projection = {
                "expression_band": expression_band,
                "label": clean_text(current_interaction.get("label"), 40),
                "source": clean_text(current_interaction.get("source"), 40),
                "reason": clean_text(current_interaction.get("reason"), 120),
                "manual_override": current_interaction.get("manual_override") is True,
            }
            dynamics_version = current_interaction.get("dynamics_version")
            recovery_band = current_interaction.get("recovery_band")
            expires_at = current_interaction.get("expires_at")
            projection_revision = current_interaction.get("projection_revision")
            if (
                dynamics_version == "interaction_dynamics.v1"
                and recovery_band in {"steady", "recovering", "reinforced"}
            ):
                if (
                    type(expires_at) not in {int, float}
                    or type(expires_at) is bool
                ):
                    return fallback
                if (
                    type(projection_revision) is not int
                    or not 1 <= projection_revision <= 1000000
                ):
                    return fallback
                interaction_projection.update(
                    {
                        "dynamics_version": dynamics_version,
                        "recovery_band": recovery_band,
                        "expires_at": max(0.0, min(10**12, float(expires_at))),
                        "projection_revision": projection_revision,
                    }
                )
            projection["current_interaction"] = interaction_projection
    return {"status": "accepted", "read_only": True, "projection": projection}


def _local_time_label(value: Any) -> str:
    text = clean_text(value, 80)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return text


def serialize_memory(
    record: MemoryRecord,
    score: float | None = None,
    reason: str = "",
) -> dict[str, Any]:
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    key_facts = (
        metadata.get("key_facts")
        if isinstance(metadata.get("key_facts"), list)
        else []
    )
    key_facts_with_refs = (
        metadata.get("key_facts_with_refs")
        if isinstance(metadata.get("key_facts_with_refs"), list)
        else []
    )
    routine_check_notes = (
        metadata.get("routine_check_notes")
        if isinstance(metadata.get("routine_check_notes"), list)
        else []
    )
    topics = (
        metadata.get("topics")
        if isinstance(metadata.get("topics"), list)
        else []
    )
    participants = (
        metadata.get("participants")
        if isinstance(metadata.get("participants"), list)
        else []
    )
    persona_weight_keys = [
        "persona_importance",
        "relationship_weight",
        "emotional_weight",
        "promise_weight",
        "open_loop_weight",
        "creative_weight",
        "preference_weight",
        "self_continuity_weight",
        "freshness_weight",
        "scar_weight",
        "emotional_debt_weight",
        "intimacy_weight",
        "vulnerability_weight",
    ]
    persona_weights = {
        key: metadata.get(key)
        for key in persona_weight_keys
        if metadata.get(key) is not None
    }
    data = {
        "id": record.id,
        "memory_type": record.memory_type,
        "scope": record.scope,
        "session_id": record.session_id,
        "group_id": record.group_id,
        "visibility": record.visibility,
        "sayability": record.sayability,
        "reality_level": record.reality_level,
        "lifecycle": record.lifecycle,
        "owner_bot_id": record.owner_bot_id,
        "persona_id": clean_text(metadata.get("persona_id"), 120),
        "validity_status": record.validity_status,
        "valid_from": record.valid_from,
        "valid_to": record.valid_to,
        "salience": record.salience,
        "durability": record.durability,
        "sensitivity": record.sensitivity,
        "reinforcement_score": record.reinforcement_score,
        "injection_count": record.injection_count,
        "last_injected_at": record.last_injected_at,
        "canonical_key": record.canonical_key,
        "content": record.content,
        "evidence_preview": clean_text(record.evidence, 520),
        "canonical_summary": clean_text(metadata.get("canonical_summary"), 420),
        "key_facts": [
            clean_text(item, 180)
            for item in key_facts
            if clean_text(item, 180)
        ][:4],
        "key_facts_with_refs": [
            {
                "fact": clean_text(item.get("fact"), 180),
                "refs": [
                    clean_text(ref, 160)
                    for ref in item.get("refs", [])
                    if clean_text(ref, 160)
                ][:6],
            }
            for item in key_facts_with_refs
            if isinstance(item, dict) and clean_text(item.get("fact"), 180)
        ][:8],
        "routine_check_notes": [
            clean_text(item, 180)
            for item in routine_check_notes
            if clean_text(item, 180)
        ][:4],
        "topics": [
            clean_text(item, 80) for item in topics if clean_text(item, 80)
        ][:5],
        "participants": [
            clean_text(item, 80)
            for item in participants
            if clean_text(item, 80)
        ][:5],
        "memory_reason": clean_text(metadata.get("memory_reason"), 260),
        "mention_policy": clean_text(metadata.get("mention_policy"), 60),
        "mentionability_score": metadata.get("mentionability_score"),
        "relationship_phase": clean_text(metadata.get("relationship_phase"), 80),
        "decay_mode": clean_text(metadata.get("decay_mode"), 80),
        "active_dimensions": [
            clean_text(item, 80)
            for item in metadata.get("active_dimensions", [])
            if clean_text(item, 80)
        ][:6]
        if isinstance(metadata.get("active_dimensions"), list)
        else [],
        "persona_weights": persona_weights,
        "mention_feedback": metadata.get("mention_feedback")
        if isinstance(metadata.get("mention_feedback"), dict)
        else {},
        "confidence": record.confidence,
        "importance": record.importance,
        "review_status": record.review_status,
        "tags": record.tags,
        "source_plugin": record.source_plugin,
        "import_batch_id": record.import_batch_id,
        "created_at": record.created_at,
        "created_at_local": _local_time_label(record.created_at),
        "updated_at": record.updated_at,
        "updated_at_local": _local_time_label(record.updated_at),
        "occurred_at": record.occurred_at,
        "occurred_at_local": _local_time_label(record.occurred_at),
        "time_range": {
            "start_at": clean_text(metadata.get("start_at"), 80),
            "end_at": clean_text(metadata.get("end_at"), 80),
            "start_at_local": clean_text(metadata.get("start_at_local"), 80)
            or _local_time_label(metadata.get("start_at")),
            "end_at_local": clean_text(metadata.get("end_at_local"), 80)
            or _local_time_label(metadata.get("end_at")),
            "timezone": "Asia/Shanghai",
        },
        "subject": {
            "kind": record.subject.kind,
            "id": record.subject.id,
            "name": record.subject.name,
            "role": record.subject.role,
        },
        "object": {
            "kind": record.object.kind,
            "id": record.object.id,
            "name": record.object.name,
            "role": record.object.role,
        },
    }
    if score is not None:
        data["score"] = score
    if reason:
        data["reason"] = reason
    return data
