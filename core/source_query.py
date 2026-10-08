"""Bounded, read-only source queries used by the current response model.

This local profile does not implement the public MemoryAtom query protocol.
Identity comes from the host event; cursors live in the shared turn budget.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import secrets
import time
from typing import Any

from .models import clean_text, stable_fingerprint
from .source_evidence import record_source_read
from .query_session import query_context


PROFILE = "memory.local-source-query.v1"


class SourceQueryError(ValueError):
    pass


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise SourceQueryError("invalid_parameter")
    return value.strip()


def _instant(value: str) -> str:
    value = _text(value, 80)
    if not value:
        return ""
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.utcoffset() is None:
            raise ValueError("timezone required")
        return instant.astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise SourceQueryError("time_requires_iso8601_with_timezone") from exc


@dataclass(frozen=True)
class SourceQuery:
    action: str = "search"
    terms: tuple[str, ...] = ()
    start_at: str = ""
    end_at: str = ""
    source_ref: str = ""
    direction: str = "around"
    excerpt_offset: int = 0

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "SourceQuery":
        if set(value) - {"action", "terms", "start_at", "end_at", "source_ref", "direction", "excerpt_offset"}:
            raise SourceQueryError("unknown_parameter")
        action = _text(value.get("action", "search"), 20)
        if action not in {"search", "range", "context", "read"}:
            raise SourceQueryError("unsupported_action")
        terms = value.get("terms")
        if terms is None:
            terms = []
        if not isinstance(terms, list) or len(terms) > 6:
            raise SourceQueryError("terms_must_be_array_up_to_6")
        terms = tuple(dict.fromkeys(_text(term, 80) for term in terms))
        if any(not term for term in terms):
            raise SourceQueryError("empty_term")
        start, end = _instant(value.get("start_at", "")), _instant(value.get("end_at", ""))
        if start and end and datetime.fromisoformat(start) >= datetime.fromisoformat(end):
            raise SourceQueryError("time_range_reversed_or_empty")
        source_ref = _text(value.get("source_ref", ""), 180)
        direction = _text(value.get("direction", "around"), 16)
        offset = value.get("excerpt_offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise SourceQueryError("invalid_excerpt_offset")
        if direction not in {"around", "before", "after"}:
            raise SourceQueryError("unsupported_direction")
        if action in {"context", "read"}:
            if not source_ref.startswith("timeline:tl_") or terms or start or end:
                raise SourceQueryError("context_requires_source_ref_only")
            if action == "read" and direction != "around":
                raise SourceQueryError("read_requires_source_ref_and_offset")
            if action != "read" and offset:
                raise SourceQueryError("excerpt_offset_requires_read")
        elif source_ref or direction != "around":
            raise SourceQueryError("source_ref_direction_require_context")
        elif offset:
            raise SourceQueryError("excerpt_offset_requires_read")
        elif action == "search" and not terms:
            raise SourceQueryError("search_requires_terms")
        elif action == "range" and (terms or not start or not end):
            raise SourceQueryError("range_requires_start_end_without_terms")
        return cls(action, terms, start, end, source_ref, direction, offset)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["terms"] = list(self.terms)
        return value


def source_visible(ctx: Any, row: dict[str, Any], metadata: dict[str, Any]) -> bool:
    """Never derive raw-source authority from a parent summary or supplied ID."""
    if (ctx.scope not in {"private", "group"} or not ctx.session_id
            or row.get("scope") != ctx.scope or row.get("session_id") != ctx.session_id
            or row.get("event_type") not in {"user_message", "bot_response"}):
        return False
    owner = clean_text(metadata.get("owner_bot_id"), 120)
    if not owner or owner == "self" or owner != clean_text(ctx.bot_id, 120):
        return False
    if clean_text(metadata.get("bot_id"), 120) not in {"", owner}:
        return False
    if clean_text(metadata.get("platform"), 80) != clean_text(ctx.platform, 80):
        return False
    if clean_text(metadata.get("persona_id"), 96) != clean_text(ctx.persona_id, 96):
        return False
    if row.get("event_type") == "bot_response" and row.get("subject_id") != owner:
        return False
    if ctx.scope == "private":
        if not ctx.user_id or row.get("object_id") != ctx.user_id:
            return False
        if row.get("event_type") == "user_message" and row.get("subject_id") != ctx.user_id:
            return False
        if clean_text(metadata.get("participant_user_id"), 120) not in {"", ctx.user_id}:
            return False
    elif not ctx.group_id or row.get("object_id") != ctx.group_id:
        return False
    return True


def source_partition(ctx: Any) -> tuple[str, list[str]]:
    """SQL equivalent of source_visible, applied before page/candidate limits."""
    if ctx.scope not in {"private", "group"} or not all((ctx.session_id, ctx.bot_id, ctx.platform)) or ctx.bot_id == "self":
        raise SourceQueryError("source_scope_unavailable")
    target = ctx.user_id if ctx.scope == "private" else ctx.group_id
    if not target:
        raise SourceQueryError("source_scope_unavailable")
    # Invalid legacy metadata is unavailable, never re-attributed to the caller.
    meta = "CASE WHEN json_valid(t.metadata) THEN t.metadata ELSE '{}' END"
    def field(name: str) -> str:
        return f"COALESCE(json_extract({meta}, '$.{name}'), '')"
    clauses = [
        "t.scope=?", "t.session_id=?", "t.object_id=?",
        "t.event_type IN ('user_message','bot_response')",
        f"{field('owner_bot_id')}=?", f"{field('platform')}=?", f"{field('persona_id')}=?",
        f"{field('bot_id')} IN ('',?)",
        "(t.event_type!='bot_response' OR t.subject_id=?)",
    ]
    params = [ctx.scope, ctx.session_id, target, ctx.bot_id, ctx.platform, ctx.persona_id, ctx.bot_id, ctx.bot_id]
    if ctx.scope == "private":
        clauses.extend(["(t.event_type!='user_message' OR t.subject_id=?)", f"{field('participant_user_id')} IN ('',?)"])
        params.extend([ctx.user_id, ctx.user_id])
    return " AND ".join(clauses), params


async def query_sources(service: Any, event: Any, *, cursor: str = "", limit: int = 0, **parameters: Any) -> dict[str, Any]:
    """Execute one source page; no model call and no source/fact mutation."""
    if parameters.get("action") == "range_batch" or (isinstance(cursor, str) and cursor.startswith("srcb_")):
        from .source_query_v2 import query_range_batch
        return await query_range_batch(service, event, cursor=cursor, limit=limit, **parameters)
    started = time.monotonic()
    empty = {"profile": PROFILE, "ok": False, "status": "rejected", "error": "",
             "sources": [], "next_cursor": None, "context_cursors": {}, "coverage": {}, "usage": {}}
    try:
        if not service.config.bool("memory_reconstruction.enabled", True) or not service.config.bool("memory_tools.enable_reconstruction_tool", True):
            raise SourceQueryError("source_query_disabled")
        ctx = service._normalized_session_context(await query_context(service, event))
        if not service._scope_feature_enabled(ctx, "recall"):
            raise SourceQueryError("scope_recall_disabled")
        source_partition(ctx)  # Reject unknown authority before querying.
        cursor = _text(cursor, 160)
        turn_key = service._reconstruction_budget_key(event, ctx)
        previous = None
        if cursor:
            # All filter parameters belong to the server-issued cursor.
            if set(parameters) - {"action", "terms", "start_at", "end_at", "source_ref", "direction", "excerpt_offset"} or any(parameters.get(name) for name in ("terms", "start_at", "end_at", "source_ref", "excerpt_offset")) or parameters.get("action", "search") != "search" or parameters.get("direction", "around") != "around" or limit:
                raise SourceQueryError("cursor_requires_no_query_parameters")
            async with service._reconstruction_lock:
                state = service._reconstruction_states.get(turn_key, {})
                previous = state.get("source_cursors", {}).get(cursor)
            if not previous or time.monotonic() > previous["expires_at"]:
                raise SourceQueryError("cursor_invalid")
            query = SourceQuery.parse(previous["query"])
            page_limit = previous["limit"]
        else:
            query = SourceQuery.parse(parameters)
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise SourceQueryError("invalid_limit")
            page_limit = service._reconstruction_per_step_limit(limit)
        signature = stable_fingerprint("source_query", cursor or json.dumps(query.as_dict(), sort_keys=True), page_limit)
        budget = await service._reserve_reconstruction_step(event, ctx, signature)
        if not budget["accepted"]:
            raise SourceQueryError(budget["error"])
        # Cursor pages cannot refresh this deadline. Different queries still
        # consume the shared per-turn navigation step/row/character ceilings.
        expires_at = previous["expires_at"] if previous else started + 120.0
        policy = await service.store.memory_revision()
        if previous and policy != previous["policy_revision"]:
            raise SourceQueryError("cursor_invalid")
        page = await service.store.query_source_page(
            ctx, query, limit=page_limit,
            boundary=previous["boundary"] if previous else None,
            expected_revision=previous["source_revision"] if previous else None,
        )
        if time.monotonic() > expires_at or not service._scope_feature_enabled(ctx, "recall"):
            raise SourceQueryError("source_query_expired_or_disabled")
        if policy != await service.store.memory_revision() or page["revision"] != await service.store.source_revision():
            raise SourceQueryError("source_changed_retry")
        sources = [value for row in page["rows"] if (value := service._serialize_navigation_source(
            ctx, row, excerpt_offset=query.excerpt_offset, terms=query.terms,
        ))]
        cursors: dict[str, str] = {}
        async with service._reconstruction_lock:
            state = service._reconstruction_states.get(turn_key)
            if state is None:
                raise SourceQueryError("cursor_invalid")
            for direction, boundary in page["continuations"].items():
                token = "src_" + secrets.token_urlsafe(24)
                next_query = replace(query, direction=direction) if query.action == "context" else query
                state.setdefault("source_cursors", {})[token] = {
                    "query": next_query.as_dict(), "boundary": boundary, "limit": page_limit,
                    "source_revision": page["revision"], "policy_revision": policy, "expires_at": expires_at,
                }
                cursors[direction] = token
        coverage = {
            "scope": "current_session_only", "time_basis": "message_observation",
            "start_at": query.start_at, "end_at": query.end_at, "interval": "[start,end)",
            "order": "message_time_asc" if query.action == "context" else ("single_message" if query.action == "read" else "message_time_desc"),
            "selection": "literal_terms_any" if query.action == "search" else query.action,
            "more_available": bool(cursors), "source_revision": page["revision"],
            "read_count": page["read_count"], "returned_count": len(sources),
            "suppressed_count": len(page["rows"]) - len(sources),
            "excerpt_truncated_count": sum(value["excerpt_truncated"] for value in sources),
            "event_coverage": "not_established", "path": page["path"],
            "unknown_message_time": "excluded_from_time_order",
        }
        usage = {"step": budget["step"], "remaining_steps": budget["remaining_steps"],
                 "model_calls": 0, "returned_chars": sum(len(value["excerpt"]) for value in sources),
                 "elapsed_ms": round((time.monotonic() - started) * 1000)}
        async with service._reconstruction_lock:
            state = service._reconstruction_states.get(turn_key)
            if state is None:
                raise SourceQueryError("cursor_invalid")
            record_source_read(state, sources, source_revision=page["revision"], policy_revision=policy,
                               expires_at=expires_at, coverage=coverage, event=event, ctx=ctx)
        return {**empty, "ok": True, "error": "", "status": "page" if sources else "empty",
                "sources": sources, "coverage": coverage, "usage": usage,
                "query": query.as_dict(), "next_cursor": cursors.get("next"),
                "context_cursors": {key: value for key, value in cursors.items() if key != "next"}}
    except SourceQueryError as exc:
        return {**empty, "error": str(exc)}
