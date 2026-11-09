from __future__ import annotations

import json
import re
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .memory_atom import (
    clamp_score,
    durability_for_memory_type,
    durability_from_legacy_metadata,
    nonnegative_int,
    normalize_durability,
    normalize_sensitivity,
    normalize_validity_status,
    row_value,
    scoped_canonical_key,
    scoped_content_fingerprint,
)
from .sensitive_data import redact_sensitive_text, redact_sensitive_value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def clean_text(value: Any, limit: int = 2000) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
    if len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def normalize_explicit_person_binding(person_id: Any, identity_assurance: Any) -> tuple[str, str]:
    normalized_id = clean_text(person_id, 80)
    assurance = clean_text(identity_assurance, 40)
    if assurance != "explicit_linked" or re.fullmatch(r"person_[0-9a-f]{24}", normalized_id) is None:
        return "", ""
    return normalized_id, assurance


def is_valid_person_id(person_id: Any) -> bool:
    return re.fullmatch(r"person_[0-9a-f]{24}", clean_text(person_id, 80)) is not None


def is_memory_placeholder(memory: Any) -> bool:
    """Return whether a record is an internal, non-recallable placeholder.

    Bot Personal archives are kept in the memory table so the dedicated
    profile bridge can serve their structured metadata.  Their display text
    is only a storage reference, however, and must never behave like a normal
    memory document.  The content check also catches rows written by older
    versions before ``source_plugin`` was standardized.
    """
    source_plugin = clean_text(getattr(memory, "source_plugin", ""), 120).casefold()
    if source_plugin == "bot_personal_bridge":
        return True
    content = clean_text(getattr(memory, "content", ""), 400).casefold()
    return bool(re.fullmatch(r"bot personal archive reference \[[^\]]+\]", content))


def clamp_float(value: Any, low: float = 0.0, high: float = 1.0, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        number = default
    return max(low, min(high, number))


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def stable_fingerprint(*parts: Any) -> str:
    raw = "|".join(clean_text(part, 1000).lower() for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


@dataclass(slots=True)
class EntityRef:
    kind: str = "user"
    id: str = ""
    name: str = ""
    role: str = "unknown"

    @classmethod
    def bot_self(cls, bot_id: str = "", bot_name: str = "") -> "EntityRef":
        return cls(kind="bot", id=clean_text(bot_id, 120) or "self", name=clean_text(bot_name, 80) or "Bot", role="bot_self")


@dataclass(slots=True)
class SessionContext:
    session_id: str = ""
    scope: str = "unknown"
    platform: str = ""
    user_id: str = ""
    user_name: str = ""
    group_id: str = ""
    group_name: str = ""
    bot_id: str = ""
    persona_id: str = ""
    message_id: str = ""
    message_text: str = ""
    strict_session_only: bool = False
    preferred_address: str = ""
    preferred_address_locked: bool = False
    relationship_authority_source: str = ""
    companion_relationship_score: int = 0
    companion_relationship_phase_key: str = ""
    companion_relationship_phase_label: str = ""
    companion_relationship_tone: str = ""
    companion_relationship_address_level: str = ""
    companion_interaction_dynamics_version: str = ""
    companion_interaction_band: str = ""
    companion_interaction_recovery_band: str = ""
    companion_interaction_expires_at: float = 0.0
    companion_interaction_projection_revision: int = 0
    companion_expression_contract: str = ""
    companion_expression_band: str = ""
    companion_expression_allowed_behaviors: tuple[str, ...] = ()
    companion_expression_safety_mode: str = ""
    companion_expression_blocker: str = ""
    companion_expression_reason_codes: tuple[str, ...] = ()
    companion_expression_pacing: str = ""
    companion_expression_directness: str = ""
    companion_expression_validation_style: str = ""
    companion_expression_self_disclosure: str = ""
    companion_expression_humor_mode: str = ""
    companion_expression_topic_initiative: str = ""
    subject_person_id: str = ""
    identity_assurance: str = ""

    @property
    def current_target_id(self) -> str:
        return self.group_id if self.scope == "group" else self.user_id

    @property
    def label(self) -> str:
        if self.scope == "group":
            group = self.group_name or self.group_id or "unknown"
            return f"群聊 {group} / 发言人 {self.user_name or self.user_id or 'unknown'}"
        if self.scope == "private":
            return f"私聊 {self.user_name or self.user_id or 'unknown'}"
        return self.session_id or "unknown"


@dataclass(slots=True)
class MemoryRecord:
    id: str = ""
    memory_type: str = "observation"
    subject: EntityRef = field(default_factory=EntityRef)
    object: EntityRef = field(default_factory=EntityRef)
    scope: str = "unknown"
    session_id: str = ""
    platform: str = ""
    message_id: str = ""
    group_id: str = ""
    visibility: str = "internal"
    sayability: str = "indirect"
    reality_level: str = "imported_summary"
    lifecycle: str = "raw_event"
    content: str = ""
    evidence: str = ""
    confidence: float = 0.5
    importance: float = 0.3
    owner_bot_id: str = ""
    validity_status: str = "active"
    valid_from: str = ""
    valid_to: str = ""
    salience: float = 0.3
    durability: str = "normal"
    sensitivity: str = "private"
    reinforcement_score: float = 0.0
    injection_count: int = 0
    last_injected_at: str = ""
    canonical_key: str = ""
    review_status: str = "auto"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    occurred_at: str = ""
    last_accessed_at: str = ""
    access_count: int = 0
    source_plugin: str = "memory_companion"
    import_batch_id: str = ""
    content_fingerprint: str = ""
    merged_count: int = 1
    supersedes_id: str = ""
    subject_person_id: str = ""
    identity_assurance: str = ""

    def ensure_defaults(self) -> "MemoryRecord":
        now = utc_now()
        if not self.id:
            self.id = new_id("mem")
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = self.created_at
        if not self.occurred_at:
            self.occurred_at = self.created_at
        self.content = clean_text(redact_sensitive_text(self.content), 4000)
        self.evidence = clean_text(redact_sensitive_text(self.evidence), 4000)
        self.confidence = clamp_float(self.confidence, default=0.5)
        self.importance = clamp_float(self.importance, default=0.3)
        if not isinstance(self.metadata, dict):
            self.metadata = {}
        self.metadata = redact_sensitive_value(self.metadata)
        metadata = self.metadata
        self.owner_bot_id = clean_text(
            self.owner_bot_id or metadata.get("owner_bot_id"),
            120,
        )
        if self.scope == "private" and self.visibility == "private_pair":
            self.subject_person_id, self.identity_assurance = normalize_explicit_person_binding(
                self.subject_person_id,
                self.identity_assurance,
            )
        else:
            self.subject_person_id = ""
            self.identity_assurance = ""
        validity_source = self.validity_status
        if validity_source == "active" and metadata.get("validity_status"):
            validity_source = metadata.get("validity_status")
        if self.lifecycle == "archived" and validity_source == "active":
            validity_source = "archived"
        self.validity_status = normalize_validity_status(validity_source)
        self.valid_from = clean_text(self.valid_from or metadata.get("valid_from"), 80)
        self.valid_to = clean_text(self.valid_to or metadata.get("valid_to"), 80)
        salience_source: Any = self.salience
        if self.salience == 0.3:
            salience_source = metadata.get("salience", self.importance)
        self.salience = clamp_score(salience_source, self.importance)
        durability_source = self.durability
        if durability_source == "normal":
            durability_source = durability_from_legacy_metadata(metadata)
            if durability_source == "normal":
                durability_source = durability_for_memory_type(self.memory_type, durability_source)
        self.durability = normalize_durability(durability_source)
        sensitivity_source = self.sensitivity
        if sensitivity_source == "private" and metadata.get("sensitivity"):
            sensitivity_source = metadata.get("sensitivity")
        self.sensitivity = normalize_sensitivity(sensitivity_source)
        reinforcement_source: Any = self.reinforcement_score
        if self.reinforcement_score == 0.0 and metadata.get("reinforcement_score") is not None:
            reinforcement_source = metadata.get("reinforcement_score")
        self.reinforcement_score = clamp_score(reinforcement_source, 0.0)
        injection_source: Any = self.injection_count
        if self.injection_count == 0 and metadata.get("injection_count") is not None:
            injection_source = metadata.get("injection_count")
        self.injection_count = nonnegative_int(injection_source)
        self.last_injected_at = clean_text(
            self.last_injected_at or metadata.get("last_injected_at"),
            80,
        )
        self.tags = [clean_text(tag, 80) for tag in self.tags if clean_text(tag, 80)]
        canonical_seed = self.canonical_key or metadata.get("canonical_key") or ""
        self.canonical_key = scoped_canonical_key(
            owner_bot_id=self.owner_bot_id,
            platform=self.platform,
            scope=self.scope,
            session_id=self.session_id,
            group_id=self.group_id,
            subject_kind=self.subject.kind,
            subject_id=self.subject.id,
            object_kind=self.object.kind,
            object_id=self.object.id,
            memory_type=self.memory_type,
            content=self.content,
            seed=canonical_seed,
        )
        self.content_fingerprint = scoped_content_fingerprint(
            owner_bot_id=self.owner_bot_id,
            platform=self.platform,
            scope=self.scope,
            session_id=self.session_id,
            group_id=self.group_id,
            subject_kind=self.subject.kind,
            subject_id=self.subject.id,
            object_kind=self.object.kind,
            object_id=self.object.id,
            memory_type=self.memory_type,
            visibility=self.visibility,
            reality_level=self.reality_level,
            content=self.content,
            canonical_key=self.canonical_key,
            seed=self.content_fingerprint,
        )
        self.merged_count = max(1, int(self.merged_count or 1))
        return self

    def to_db(self) -> dict[str, Any]:
        self.ensure_defaults()
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "subject_kind": self.subject.kind,
            "subject_id": self.subject.id,
            "subject_name": self.subject.name,
            "subject_role": self.subject.role,
            "object_kind": self.object.kind,
            "object_id": self.object.id,
            "object_name": self.object.name,
            "object_role": self.object.role,
            "scope": self.scope,
            "session_id": self.session_id,
            "platform": self.platform,
            "message_id": self.message_id,
            "group_id": self.group_id,
            "visibility": self.visibility,
            "sayability": self.sayability,
            "reality_level": self.reality_level,
            "lifecycle": self.lifecycle,
            "content": self.content,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "importance": self.importance,
            "owner_bot_id": self.owner_bot_id,
            "subject_person_id": self.subject_person_id,
            "identity_assurance": self.identity_assurance,
            "validity_status": self.validity_status,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "salience": self.salience,
            "durability": self.durability,
            "sensitivity": self.sensitivity,
            "reinforcement_score": self.reinforcement_score,
            "injection_count": self.injection_count,
            "last_injected_at": self.last_injected_at,
            "canonical_key": self.canonical_key,
            "review_status": self.review_status,
            "tags": json_dumps(self.tags),
            "metadata": json_dumps(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "occurred_at": self.occurred_at,
            "last_accessed_at": self.last_accessed_at,
            "access_count": int(self.access_count or 0),
            "source_plugin": self.source_plugin,
            "import_batch_id": self.import_batch_id,
            "content_fingerprint": self.content_fingerprint,
            "merged_count": self.merged_count,
            "supersedes_id": self.supersedes_id,
        }

    @classmethod
    def _from_row_raw(cls, row: Any) -> "MemoryRecord":
        metadata = json_loads(row_value(row, "metadata", "{}"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            id=row_value(row, "id", ""),
            memory_type=row_value(row, "memory_type", "observation"),
            subject=EntityRef(
                row_value(row, "subject_kind", "user"),
                row_value(row, "subject_id", ""),
                row_value(row, "subject_name", ""),
                row_value(row, "subject_role", "unknown"),
            ),
            object=EntityRef(
                row_value(row, "object_kind", "user"),
                row_value(row, "object_id", ""),
                row_value(row, "object_name", ""),
                row_value(row, "object_role", "unknown"),
            ),
            scope=row_value(row, "scope", "unknown"),
            session_id=row_value(row, "session_id", ""),
            platform=row_value(row, "platform", ""),
            message_id=row_value(row, "message_id", ""),
            group_id=row_value(row, "group_id", ""),
            visibility=row_value(row, "visibility", "internal"),
            sayability=row_value(row, "sayability", "indirect"),
            reality_level=row_value(row, "reality_level", "imported_summary"),
            lifecycle=row_value(row, "lifecycle", "raw_event"),
            content=row_value(row, "content", ""),
            evidence=row_value(row, "evidence", ""),
            confidence=float(row_value(row, "confidence", 0.5) or 0.0),
            importance=float(row_value(row, "importance", 0.3) or 0.0),
            owner_bot_id=row_value(row, "owner_bot_id", ""),
            subject_person_id=row_value(row, "subject_person_id", ""),
            identity_assurance=row_value(row, "identity_assurance", ""),
            validity_status=row_value(row, "validity_status", "active"),
            valid_from=row_value(row, "valid_from", ""),
            valid_to=row_value(row, "valid_to", ""),
            salience=float(row_value(row, "salience", 0.3) or 0.0),
            durability=row_value(row, "durability", "normal"),
            sensitivity=row_value(row, "sensitivity", "private"),
            reinforcement_score=float(row_value(row, "reinforcement_score", 0.0) or 0.0),
            injection_count=int(row_value(row, "injection_count", 0) or 0),
            last_injected_at=row_value(row, "last_injected_at", ""),
            canonical_key=row_value(row, "canonical_key", ""),
            review_status=row_value(row, "review_status", "auto"),
            tags=json_loads(row_value(row, "tags", "[]"), []),
            metadata=metadata,
            created_at=row_value(row, "created_at", ""),
            updated_at=row_value(row, "updated_at", ""),
            occurred_at=row_value(row, "occurred_at", ""),
            last_accessed_at=row_value(row, "last_accessed_at", ""),
            access_count=int(row_value(row, "access_count", 0) or 0),
            source_plugin=row_value(row, "source_plugin", "memory_companion"),
            import_batch_id=row_value(row, "import_batch_id", ""),
            content_fingerprint=row_value(row, "content_fingerprint", ""),
            merged_count=int(row_value(row, "merged_count", 1) or 1),
            supersedes_id=row_value(row, "supersedes_id", ""),
        )

    @classmethod
    def from_row(cls, row: Any) -> "MemoryRecord":
        return cls._from_row_raw(row).ensure_defaults()

    @classmethod
    def from_row_light(cls, row: Any) -> "MemoryRecord":
        """Build a record from a stored row without re-running ``ensure_defaults``.

        Candidate-loading read paths materialize thousands of rows per hook.
        The stored columns are already normalized, redacted and hashed at
        write time (``to_db`` runs ``ensure_defaults``), so re-deriving them on
        read is redundant work — dominated by ``redact_sensitive_value`` over
        the metadata dict. This constructor trusts the stored scalar columns,
        parses the JSON columns, and applies only the cheap tag cleaning that
        ``ensure_defaults`` also performs, so its output is identical to
        ``from_row`` for any row written through the store. Verified
        idempotent across the eligible population (see
        test_candidate_bundle equivalence tests).
        """
        record = cls._from_row_raw(row)
        record.tags = [clean_text(tag, 80) for tag in record.tags if clean_text(tag, 80)]
        return record


@dataclass(slots=True)
class SearchResult:
    memory: MemoryRecord
    score: float
    reason: str = ""


def memory_embedding_text(record: MemoryRecord, *, max_chars: int = 1200) -> str:
    """Build the canonical text used for both embedding writes and retrieval validation."""

    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    parts = [
        f"类型: {record.memory_type}",
        f"范围: {record.scope}/{record.visibility}",
        f"标签: {' '.join(record.tags or [])}",
        f"内容: {record.content}",
    ]
    for key in (
        "canonical_summary",
        "persona_summary",
        "key_facts",
        "routine_check_notes",
        "topics",
    ):
        value = metadata.get(key)
        if isinstance(value, list):
            value = " ".join(str(item) for item in value if item)
        value_text = clean_text(value, 1000)
        if value_text:
            parts.append(f"{key}: {value_text}")
    if record.evidence:
        parts.append(f"证据: {record.evidence}")
    try:
        limit = max(200, int(max_chars or 1200))
    except (TypeError, ValueError):
        limit = 1200
    return clean_text("\n".join(parts), limit)


def memory_embedding_text_hash(record: MemoryRecord, *, max_chars: int = 1200) -> str:
    text = memory_embedding_text(record, max_chars=max_chars)
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
