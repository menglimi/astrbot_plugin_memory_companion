from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json

from .models import MemoryRecord, SessionContext, clean_text, utc_now
from .profile_quality import normalize_profile_value


class MemoryRevisionError(ValueError):
    pass


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def memory_ref(record: MemoryRecord) -> dict[str, str]:
    # Access/embedding bookkeeping does not change the evidence a consumer saw.
    fields = ("id", "memory_type", "subject", "object", "scope", "session_id", "platform", "group_id",
              "owner_bot_id", "visibility", "sayability", "reality_level", "lifecycle", "content", "evidence",
              "validity_status", "valid_from", "valid_to", "review_status", "sensitivity", "supersedes_id",
              "message_id", "confidence", "occurred_at")
    data = asdict(record)
    semantic = {key: data[key] for key in fields}
    metadata = record.metadata or {}
    semantic["metadata"] = {
        key: value for key, value in metadata.items()
        if key.startswith(("profile_", "core_")) or key in {
            "persona_id", "owner_bot_id", "canonical_summary", "key_facts", "key_facts_with_refs",
            "source_expired_event_ids",
            "normalized_value", "summary", "mention_policy", "evidence_refs", "source_memory_id",
            "source_memory_ids", "correction_ref", "superseded_by", "quality_gate_passed",
            "expires_at", "core_enabled", "core_scope", "target_id", "source_ref",
        }
    }
    return {"id": record.id, "version": digest(semantic)}


class MemoryContext(str):
    """Keep the existing text API, with refs to the rows actually rendered."""

    def __new__(cls, text: str, refs=(), *, continuity_snapshot=None, role_input_complete=False):
        value = super().__new__(cls, text)
        value.memory_refs = deepcopy(list(refs))
        value.role_input_complete = bool(role_input_complete)
        # Keep the compatibility string API while exposing a request-scoped,
        # reference-only continuity snapshot to adapters that understand it.
        # The snapshot is optional and never changes the rendered prompt.
        value.continuity_snapshot = deepcopy(continuity_snapshot) if continuity_snapshot is not None else None
        return value


def current_memory(record: MemoryRecord) -> bool:
    if record.validity_status != "active" or record.lifecycle == "archived" or record.review_status == "rejected":
        return False
    if (record.metadata or {}).get("profile_state") in {"superseded", "rejected"}:
        return False
    now = datetime.now(timezone.utc)
    for value, is_end in ((record.valid_from, False), (record.valid_to, True),
                          ((record.metadata or {}).get("expires_at"), True)):
        if not value:
            continue
        try:
            bound = datetime.fromisoformat(value.replace("Z", "+00:00"))
            bound = bound.replace(tzinfo=timezone.utc) if bound.tzinfo is None else bound
        except ValueError:
            return False
        if (is_end and now >= bound) or (not is_end and now < bound):
            return False
    return True


def correction_owner(ctx: SessionContext, record: MemoryRecord) -> bool:
    metadata = record.metadata or {}
    users = {entity.id for entity in (record.subject, record.object) if entity.kind == "user"}
    return bool(
        ctx.scope == record.scope == "private" and not ctx.group_id and not record.group_id
        and ctx.session_id and ctx.session_id == record.session_id
        and ctx.user_id and users == {ctx.user_id}
        and record.visibility == "private_pair"
        and ctx.bot_id and ctx.bot_id == (record.owner_bot_id or metadata.get("owner_bot_id"))
        and (not metadata.get("persona_id") or metadata.get("persona_id") == "legacy"
             or ctx.persona_id == str(metadata["persona_id"]))
    )


def correction_scope(ctx: SessionContext) -> str:
    return digest([ctx.platform, ctx.session_id, ctx.user_id, ctx.bot_id, ctx.persona_id])


def revised_memory(old: MemoryRecord, ctx: SessionContext, *, content: str,
                   profile_value: str, profile_polarity: str, correction_ref: str, new_id: str) -> MemoryRecord:
    profiles = {"user_profile", "user_preference", "user_habit"}
    if old.memory_type not in profiles | {"memory", "observation", "companion_note"}:
        raise MemoryRevisionError("memory_type_requires_domain_revision")
    old_meta = old.metadata or {}
    is_profile = old.memory_type in profiles
    if is_profile and (not profile_value or not old_meta.get("profile_dimension")):
        raise MemoryRevisionError("structured_profile_value_required")
    if is_profile and not profile_polarity:
        raise MemoryRevisionError("structured_profile_polarity_required")
    if not content or not ctx.message_text or not ctx.message_id:
        raise MemoryRevisionError("correction_evidence_required")
    record = deepcopy(old)
    now = utc_now()
    record.id, record.supersedes_id = new_id, old.id
    record.content, record.evidence, record.message_id = content, ctx.message_text, ctx.message_id
    record.created_at = record.updated_at = record.occurred_at = now
    record.last_accessed_at = record.last_injected_at = ""
    record.access_count = record.injection_count = 0
    record.reinforcement_score = 0.0
    record.merged_count = 1
    record.canonical_key = record.content_fingerprint = ""
    record.validity_status, record.lifecycle, record.review_status = "active", "stable_memory", "auto"
    record.valid_from, record.valid_to = now, ""
    record.reality_level = "real_user_fact"
    record.tags = ["user_correction", ctx.scope]
    record.metadata = {
        "owner_bot_id": ctx.bot_id, "persona_id": str(old_meta.get("persona_id") or ""),
        "correction_ref": correction_ref, "source_message_id": ctx.message_id,
        "tool": "pc_correct_user_memory", "evidence_strength": "direct_statement",
    }
    if is_profile:
        record.metadata.update({key: old_meta[key] for key in (
            "profile_dimension", "profile_cardinality", "extractor",
        ) if key in old_meta})
        record.metadata.update(
            profile_value=profile_value, normalized_value=normalize_profile_value(profile_value),
            profile_polarity=profile_polarity,
            profile_state="active", profile_status="active", quality_gate_passed=True,
            extraction_quality="explicit", extraction_quality_score=1.0, profile_evidence_refs=[ctx.message_id],
        )
    return record.ensure_defaults()
