"""Contracts for keeping request context and durable memory continuous.

The module is intentionally storage- and model-agnostic.  It validates the
small query plan that a model may propose and builds a bounded snapshot from
the evidence that the Memory owner has already returned.  It never performs a
query, writes a memory record, or stores the current message body.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


QUERY_PLAN_SCHEMA = "memory.query-plan.v1"
CONTEXT_SNAPSHOT_SCHEMA = "memory.context-snapshot.v1"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
_HEX_RE = re.compile(r"^[0-9a-f]{16,128}$")
_STATUSES = frozenset({"active", "superseded", "expired", "invalidated", "pending", "source_missing"})
_REF_KINDS = frozenset({"fact", "proposal", "source", "temporary"})
_PLAN_PROFILES = {
    "continuity.relevant.v1": frozenset({"search_candidates", "expand_source", "revalidate"}),
    "continuity.range.v1": frozenset(
        {
            "time_resolve",
            "search_candidates",
            "range_read",
            "expand_source",
            "associate",
            "semantic_extract",
            "aggregate",
            "revalidate",
        }
    ),
}
_PLAN_OPERATIONS = frozenset().union(*_PLAN_PROFILES.values())
_SNAPSHOT_STATES = frozenset({"ready", "degraded", "stale", "pending"})


class ContinuityContractError(ValueError):
    """Raised when a plan, reference, or snapshot violates the contract."""


def _text(value: Any, *, name: str, required: bool = False, limit: int = 256) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ContinuityContractError(f"{name}_required")
    if len(result) > limit or "\x00" in result:
        raise ContinuityContractError(f"{name}_invalid")
    return result


def _id(value: Any, *, name: str, required: bool = True) -> str:
    result = _text(value, name=name, required=required, limit=128).lower()
    if result and not _ID_RE.fullmatch(result):
        raise ContinuityContractError(f"{name}_invalid")
    return result


def _nonnegative(value: Any, *, name: str, maximum: int = 100000) -> int:
    if isinstance(value, bool):
        raise ContinuityContractError(f"{name}_invalid")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContinuityContractError(f"{name}_invalid") from exc
    if result < 0 or result > maximum:
        raise ContinuityContractError(f"{name}_invalid")
    return result


def _tuple_text(values: Sequence[Any] | None, *, name: str, limit: int = 24, item_limit: int = 160) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        values = (values,)
    result: list[str] = []
    for value in values:
        text = _text(value, name=name, limit=item_limit)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any, *, size: int = 64) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:size]


def _iso(value: Any, *, name: str, required: bool = False) -> str:
    result = _text(value, name=name, required=required, limit=64)
    if not result:
        return ""
    try:
        datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContinuityContractError(f"{name}_invalid") from exc
    return result


@dataclass(frozen=True, slots=True)
class QueryBudget:
    """One total budget shared by planning, retrieval, and any follow-up."""

    max_items: int = 8
    max_chars: int = 2400
    max_tokens: int = 1200
    max_operations: int = 8
    max_model_calls: int = 1
    deadline_ms: int = 1200

    def __post_init__(self) -> None:
        for name, maximum in (
            ("max_items", 200),
            ("max_chars", 20000),
            ("max_tokens", 12000),
            ("max_operations", 32),
            ("max_model_calls", 4),
            ("deadline_ms", 120000),
        ):
            value = _nonnegative(getattr(self, name), name=name, maximum=maximum)
            if name != "max_model_calls" and value == 0:
                raise ContinuityContractError(f"{name}_must_be_positive")
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_items": self.max_items,
            "max_chars": self.max_chars,
            "max_tokens": self.max_tokens,
            "max_operations": self.max_operations,
            "max_model_calls": self.max_model_calls,
            "deadline_ms": self.deadline_ms,
        }


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A resolved interval; an empty bound means the source is unbounded."""

    start: str = ""
    end: str = ""
    timezone: str = "UTC"
    precision: str = "instant"
    anchor_ref: str = ""

    def __post_init__(self) -> None:
        start = _iso(self.start, name="time_start")
        end = _iso(self.end, name="time_end")
        if start and end:
            left = datetime.fromisoformat(start.replace("Z", "+00:00"))
            right = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if left > right:
                raise ContinuityContractError("time_range_reversed")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "timezone", _text(self.timezone, name="timezone", required=True, limit=64))
        object.__setattr__(self, "precision", _id(self.precision, name="precision"))
        object.__setattr__(self, "anchor_ref", _text(self.anchor_ref, name="anchor_ref", limit=160))

    def to_dict(self) -> dict[str, str]:
        return {
            "start": self.start,
            "end": self.end,
            "timezone": self.timezone,
            "precision": self.precision,
            "anchor_ref": self.anchor_ref,
        }


@dataclass(frozen=True, slots=True)
class QueryOperation:
    operation_id: str
    operation: str
    depends_on: tuple[str, ...] = ()
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _id(self.operation_id, name="operation_id"))
        object.__setattr__(self, "operation", _id(self.operation, name="operation"))
        if self.operation not in _PLAN_OPERATIONS:
            raise ContinuityContractError("operation_unsupported")
        object.__setattr__(self, "depends_on", _tuple_text(self.depends_on, name="depends_on", item_limit=128))
        if not isinstance(self.arguments, Mapping):
            raise ContinuityContractError("operation_arguments_invalid")
        encoded = _canonical(dict(self.arguments))
        if len(encoded.encode("utf-8")) > 4096:
            raise ContinuityContractError("operation_arguments_too_large")
        object.__setattr__(self, "arguments", dict(self.arguments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation": self.operation,
            "depends_on": list(self.depends_on),
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """A model-proposed plan constrained to known, read-only operations."""

    profile: str
    purpose: str
    scope_key: str
    query_intent: str
    operations: tuple[QueryOperation, ...]
    session_id: str = ""
    anchor_ref: str = ""
    time_window: TimeWindow | None = None
    required_features: tuple[str, ...] = ()
    include_pending: bool = False
    conflict_policy: str = "current_only"
    cursor: str = ""
    budget: QueryBudget = field(default_factory=QueryBudget)

    def __post_init__(self) -> None:
        profile = _id(self.profile, name="profile")
        if profile not in _PLAN_PROFILES:
            raise ContinuityContractError("profile_unsupported")
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "purpose", _id(self.purpose, name="purpose"))
        object.__setattr__(self, "scope_key", _text(self.scope_key, name="scope_key", required=True, limit=160))
        object.__setattr__(self, "query_intent", _text(self.query_intent, name="query_intent", required=True, limit=1400))
        if not isinstance(self.budget, QueryBudget):
            raise ContinuityContractError("budget_invalid")
        operations = tuple(self.operations or ())
        if not operations or len(operations) > self.budget.max_operations:
            raise ContinuityContractError("operation_budget_exceeded")
        allowed = _PLAN_PROFILES[profile]
        seen: set[str] = set()
        for item in operations:
            if not isinstance(item, QueryOperation) or item.operation not in allowed:
                raise ContinuityContractError("operation_not_allowed_for_profile")
            if item.operation_id in seen:
                raise ContinuityContractError("operation_id_duplicate")
            if any(dep not in seen for dep in item.depends_on):
                raise ContinuityContractError("operation_dependency_invalid")
            seen.add(item.operation_id)
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "session_id", _text(self.session_id, name="session_id", limit=160))
        object.__setattr__(self, "anchor_ref", _text(self.anchor_ref, name="anchor_ref", limit=160))
        object.__setattr__(self, "required_features", _tuple_text(self.required_features, name="required_features", item_limit=128))
        if self.include_pending and not self.session_id:
            raise ContinuityContractError("pending_requires_session")
        conflict_policy = _id(self.conflict_policy, name="conflict_policy")
        if conflict_policy not in {"current_only", "include_history"}:
            raise ContinuityContractError("conflict_policy_invalid")
        object.__setattr__(self, "conflict_policy", conflict_policy)
        object.__setattr__(self, "cursor", _text(self.cursor, name="cursor", limit=512))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUERY_PLAN_SCHEMA,
            "profile": self.profile,
            "purpose": self.purpose,
            "scope_key": self.scope_key,
            "query_intent": self.query_intent,
            "session_id": self.session_id,
            "anchor_ref": self.anchor_ref,
            "time_window": self.time_window.to_dict() if self.time_window else None,
            "operations": [item.to_dict() for item in self.operations],
            "required_features": list(self.required_features),
            "include_pending": self.include_pending,
            "conflict_policy": self.conflict_policy,
            "cursor": self.cursor,
            "budget": self.budget.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ContinuityRef:
    """A source reference that can be safely projected into one request."""

    ref_id: str
    version: str
    source_ref: str
    scope_key: str
    purpose: str
    ref_kind: str = "fact"
    status: str = "active"
    valid_from: str = ""
    valid_to: str = ""
    expires_at: str = ""
    confidence: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _text(self.ref_id, name="ref_id", required=True, limit=160))
        object.__setattr__(self, "version", _text(self.version, name="version", required=True, limit=128))
        object.__setattr__(self, "source_ref", _text(self.source_ref, name="source_ref", limit=240))
        object.__setattr__(self, "scope_key", _text(self.scope_key, name="scope_key", required=True, limit=160))
        object.__setattr__(self, "purpose", _id(self.purpose, name="purpose"))
        kind = _id(self.ref_kind, name="ref_kind")
        if kind not in _REF_KINDS:
            raise ContinuityContractError("ref_kind_invalid")
        object.__setattr__(self, "ref_kind", kind)
        status = _id(self.status, name="status")
        if status not in _STATUSES:
            raise ContinuityContractError("ref_status_invalid")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "valid_from", _iso(self.valid_from, name="valid_from"))
        object.__setattr__(self, "valid_to", _iso(self.valid_to, name="valid_to"))
        object.__setattr__(self, "expires_at", _iso(self.expires_at, name="expires_at"))
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContinuityContractError("confidence_invalid") from exc
        if not 0 <= confidence <= 1:
            raise ContinuityContractError("confidence_invalid")
        object.__setattr__(self, "confidence", confidence)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, default_scope_key: str = "", default_purpose: str = "reply") -> "ContinuityRef":
        if not isinstance(value, Mapping):
            raise ContinuityContractError("ref_invalid")
        ref_id = value.get("ref_id") or value.get("memory_id") or value.get("id") or value.get("proposal_id")
        version = value.get("version") or value.get("revision")
        source_ref = value.get("source_ref") or value.get("message_id") or ""
        scope_key = value.get("scope_key") or default_scope_key
        purpose = value.get("purpose") or default_purpose
        return cls(
            ref_id=ref_id,
            version=version,
            source_ref=source_ref,
            scope_key=scope_key,
            purpose=purpose,
            ref_kind=value.get("ref_kind") or value.get("item_kind") or "fact",
            status=value.get("status") or value.get("fact_status") or "active",
            valid_from=value.get("valid_from") or "",
            valid_to=value.get("valid_to") or "",
            expires_at=value.get("expires_at") or "",
            confidence=value.get("confidence") if value.get("confidence") is not None else 0.0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "version": self.version,
            "source_ref": self.source_ref,
            "scope_key": self.scope_key,
            "purpose": self.purpose,
            "ref_kind": self.ref_kind,
            "status": self.status,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "expires_at": self.expires_at,
            "confidence": self.confidence,
        }


def scope_key_for_context(ctx: Any) -> str:
    """Fingerprint the legacy context; this is not RuntimeScope authorization."""

    payload = {
        "scope": str(getattr(ctx, "scope", "") or ""),
        "platform": str(getattr(ctx, "platform", "") or ""),
        "user_id": str(getattr(ctx, "user_id", "") or ""),
        "group_id": str(getattr(ctx, "group_id", "") or ""),
        "bot_id": str(getattr(ctx, "bot_id", "") or ""),
        "persona_id": str(getattr(ctx, "persona_id", "") or ""),
    }
    return "scope:" + _digest(payload, size=32)


def _safe_strings(values: Sequence[Any] | None, *, limit: int = 12, item_limit: int = 160) -> tuple[str, ...]:
    result: list[str] = []
    for value in values or ():
        text = str(value or "").strip()[:item_limit]
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """References to the context available while compiling one request."""

    snapshot_id: str
    scope_key: str
    session_id: str
    session_revision: int
    context_revision: str
    memory_revision: str
    current_turn_digest: str
    continuity_refs: tuple[ContinuityRef, ...] = ()
    immediate_refs: tuple[str, ...] = ()
    open_loops: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    coverage: Mapping[str, Any] = field(default_factory=dict)
    usage: Mapping[str, Any] = field(default_factory=dict)
    state: str = "ready"
    generated_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, name="snapshot_id", required=True, limit=180))
        object.__setattr__(self, "scope_key", _text(self.scope_key, name="scope_key", required=True, limit=160))
        object.__setattr__(self, "session_id", _text(self.session_id, name="session_id", limit=160))
        object.__setattr__(self, "session_revision", _nonnegative(self.session_revision, name="session_revision"))
        object.__setattr__(self, "context_revision", _text(self.context_revision, name="context_revision", required=True, limit=128))
        object.__setattr__(self, "memory_revision", _text(self.memory_revision, name="memory_revision", limit=128))
        digest = _text(self.current_turn_digest, name="current_turn_digest", limit=128)
        if digest and not _HEX_RE.fullmatch(digest):
            raise ContinuityContractError("current_turn_digest_invalid")
        object.__setattr__(self, "current_turn_digest", digest)
        refs = tuple(self.continuity_refs or ())
        seen: set[tuple[str, str]] = set()
        for ref in refs:
            if not isinstance(ref, ContinuityRef):
                raise ContinuityContractError("continuity_ref_invalid")
            if ref.scope_key != self.scope_key:
                raise ContinuityContractError("continuity_scope_mismatch")
            key = (ref.ref_id, ref.version)
            if key in seen:
                raise ContinuityContractError("continuity_ref_duplicate")
            seen.add(key)
        object.__setattr__(self, "continuity_refs", refs)
        object.__setattr__(self, "immediate_refs", _safe_strings(self.immediate_refs))
        object.__setattr__(self, "open_loops", _safe_strings(self.open_loops))
        object.__setattr__(self, "unresolved", _safe_strings(self.unresolved))
        for name in ("coverage", "usage"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ContinuityContractError(f"{name}_invalid")
            encoded = _canonical(dict(value))
            if len(encoded.encode("utf-8")) > 4096:
                raise ContinuityContractError(f"{name}_too_large")
            object.__setattr__(self, name, dict(value))
        state = _id(self.state, name="state")
        if state not in _SNAPSHOT_STATES:
            raise ContinuityContractError("snapshot_state_invalid")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "generated_at", _iso(self.generated_at, name="generated_at"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_SNAPSHOT_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "scope_key": self.scope_key,
            "session_id": self.session_id,
            "session_revision": self.session_revision,
            "context_revision": self.context_revision,
            "memory_revision": self.memory_revision,
            "current_turn_digest": self.current_turn_digest,
            "continuity_refs": [item.to_dict() for item in self.continuity_refs],
            "immediate_refs": list(self.immediate_refs),
            "open_loops": list(self.open_loops),
            "unresolved": list(self.unresolved),
            "coverage": dict(self.coverage),
            "usage": dict(self.usage),
            "state": self.state,
            "generated_at": self.generated_at,
        }


def build_context_snapshot(
    ctx: Any,
    *,
    memory_refs: Sequence[Mapping[str, Any]] | None = None,
    current_message: str | None = None,
    session_revision: int = 0,
    memory_revision: str = "",
    purpose: str = "reply",
    immediate_refs: Sequence[str] | None = None,
    open_loops: Sequence[str] | None = None,
    unresolved: Sequence[str] | None = None,
    coverage: Mapping[str, Any] | None = None,
    usage: Mapping[str, Any] | None = None,
    state: str = "ready",
    generated_at: str = "",
) -> ContextSnapshot:
    """Build a snapshot from owner-returned references without retaining text."""

    scope_key = scope_key_for_context(ctx)
    session_id = _text(getattr(ctx, "session_id", "") or "", name="session_id", limit=160)
    message = str(current_message if current_message is not None else getattr(ctx, "message_text", "") or "")
    current_digest = hashlib.sha256(message.encode("utf-8")).hexdigest() if message else ""
    refs: list[ContinuityRef] = []
    omitted = 0
    for raw in memory_refs or ():
        try:
            ref = ContinuityRef.from_mapping(raw, default_scope_key=scope_key, default_purpose=purpose)
        except ContinuityContractError:
            omitted += 1
            continue
        if ref.scope_key != scope_key:
            omitted += 1
            continue
        if all((item.ref_id, item.version) != (ref.ref_id, ref.version) for item in refs):
            refs.append(ref)
    safe_coverage = dict(coverage or {})
    if omitted:
        safe_coverage["omitted_refs"] = omitted
        if state == "ready":
            state = "degraded"
    safe_coverage["missing_source_refs"] = sum(not ref.source_ref for ref in refs)
    safe_usage = dict(usage or {})
    safe_usage.setdefault("selected_items", len(refs))
    revision_payload = {
        "scope_key": scope_key,
        "session_id": session_id,
        "session_revision": max(0, int(session_revision or 0)),
        "memory_revision": str(memory_revision or ""),
        "current_turn_digest": current_digest,
        "message_id": str(getattr(ctx, "message_id", "") or ""),
        "refs": [item.to_dict() for item in refs],
        "immediate_refs": list(_safe_strings(immediate_refs)),
        "open_loops": list(_safe_strings(open_loops)),
        "unresolved": list(_safe_strings(unresolved)),
        "coverage": safe_coverage,
        "usage": safe_usage,
        "state": state,
    }
    context_revision = _digest(revision_payload, size=32)
    snapshot_id = f"context:{scope_key.removeprefix('scope:')[:12]}:{context_revision[:16]}"
    return ContextSnapshot(
        snapshot_id=snapshot_id,
        scope_key=scope_key,
        session_id=session_id,
        session_revision=session_revision,
        context_revision=context_revision,
        memory_revision=str(memory_revision or ""),
        current_turn_digest=current_digest,
        continuity_refs=tuple(refs),
        immediate_refs=tuple(_safe_strings(immediate_refs)),
        open_loops=tuple(_safe_strings(open_loops)),
        unresolved=tuple(_safe_strings(unresolved)),
        coverage=safe_coverage,
        usage=safe_usage,
        state=state,
        generated_at=generated_at,
    )


__all__ = [
    "CONTEXT_SNAPSHOT_SCHEMA",
    "QUERY_PLAN_SCHEMA",
    "ContinuityContractError",
    "QueryBudget",
    "TimeWindow",
    "QueryOperation",
    "QueryPlan",
    "ContinuityRef",
    "ContextSnapshot",
    "build_context_snapshot",
    "scope_key_for_context",
]
