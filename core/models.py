from __future__ import annotations

import json
import re
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


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
    def bot_self(cls) -> "EntityRef":
        return cls(kind="bot", id="self", name="Bot", role="bot_self")


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
    message_id: str = ""
    message_text: str = ""

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
        self.content = clean_text(self.content, 4000)
        self.evidence = clean_text(self.evidence, 4000)
        self.confidence = clamp_float(self.confidence, default=0.5)
        self.importance = clamp_float(self.importance, default=0.3)
        self.tags = [clean_text(tag, 80) for tag in self.tags if clean_text(tag, 80)]
        if not self.content_fingerprint:
            self.content_fingerprint = stable_fingerprint(
                self.memory_type,
                self.scope,
                self.session_id,
                self.group_id,
                self.subject.kind,
                self.subject.id,
                self.object.kind,
                self.object.id,
                self.visibility,
                self.reality_level,
                self.content,
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
    def from_row(cls, row: Any) -> "MemoryRecord":
        get = row.__getitem__
        return cls(
            id=get("id"),
            memory_type=get("memory_type"),
            subject=EntityRef(get("subject_kind"), get("subject_id"), get("subject_name"), get("subject_role")),
            object=EntityRef(get("object_kind"), get("object_id"), get("object_name"), get("object_role")),
            scope=get("scope"),
            session_id=get("session_id"),
            platform=get("platform"),
            message_id=get("message_id"),
            group_id=get("group_id"),
            visibility=get("visibility"),
            sayability=get("sayability"),
            reality_level=get("reality_level"),
            lifecycle=get("lifecycle"),
            content=get("content"),
            evidence=get("evidence"),
            confidence=float(get("confidence") or 0.0),
            importance=float(get("importance") or 0.0),
            review_status=get("review_status"),
            tags=json_loads(get("tags"), []),
            metadata=json_loads(get("metadata"), {}),
            created_at=get("created_at"),
            updated_at=get("updated_at"),
            occurred_at=get("occurred_at"),
            last_accessed_at=get("last_accessed_at"),
            access_count=int(get("access_count") or 0),
            source_plugin=get("source_plugin"),
            import_batch_id=get("import_batch_id"),
            content_fingerprint=get("content_fingerprint"),
            merged_count=int(get("merged_count") or 1),
            supersedes_id=get("supersedes_id"),
        )


@dataclass(slots=True)
class SearchResult:
    memory: MemoryRecord
    score: float
    reason: str = ""
