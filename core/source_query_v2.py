"""Opt-in chronological batches of authorized stored message text."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import re
import secrets
import time
from typing import Any

from .models import json_dumps, stable_fingerprint
from .query_session import query_context
from .source_evidence import record_source_read
from .source_query import SourceQueryError, _instant, _text, source_partition


SOURCE_QUERY_PROFILE_V2 = "memory.local-source-query.v2"
CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "docs/contracts/source-query/v2"
_FIELDS = {"action", "terms", "start_at", "end_at", "source_ref", "direction", "excerpt_offset"}


@lru_cache(maxsize=1)
def request_schema() -> dict[str, Any]:
    return json.loads((CONTRACT_ROOT / "schemas/request.schema.json").read_text(encoding="utf-8"))


def is_batch_request(parameters: dict[str, Any]) -> bool:
    return parameters.get("action") == "range_batch" or (
        isinstance(parameters.get("cursor"), str) and parameters["cursor"].startswith("srcb_")
    )


def binding_matches(service: Any, event: Any, ctx: Any) -> bool:
    return (getattr(event, "_memory_source_query_v2", False) is True
            and getattr(event, "_memory_source_query_v2_key", None)
            == service._reconstruction_budget_key(event, ctx))


def rejected(error: str) -> dict[str, Any]:
    return {"profile": SOURCE_QUERY_PROFILE_V2, "ok": False, "status": "rejected",
            "error": error, "sources": [], "batch": {}, "coverage": {}, "usage": {}}


def _parse(parameters: dict[str, Any], cursor: str, limit: Any) -> tuple[str, str]:
    if set(parameters) - _FIELDS:
        raise SourceQueryError("unknown_parameter")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit != 0:
        raise SourceQueryError("range_batch_uses_server_budget")
    if (parameters.get("terms") not in (None, [])
            or parameters.get("source_ref", "") != ""
            or parameters.get("direction", "around") != "around"
            or type(parameters.get("excerpt_offset", 0)) is not int
            or parameters.get("excerpt_offset", 0) != 0):
        raise SourceQueryError("range_batch_requires_time_range_only")
    action = parameters.get("action", "search")
    if cursor:
        if not re.fullmatch(r"srcb_[A-Za-z0-9_-]+", cursor):
            raise SourceQueryError("cursor_invalid")
        if action != "search" or parameters.get("start_at", "") != "" or parameters.get("end_at", "") != "":
            raise SourceQueryError("cursor_requires_no_query_parameters")
        return "", ""
    if action != "range_batch":
        raise SourceQueryError("unsupported_action")
    start, end = _instant(parameters.get("start_at", "")), _instant(parameters.get("end_at", ""))
    if not start or not end:
        raise SourceQueryError("range_requires_start_end_without_terms")
    if datetime.fromisoformat(start) >= datetime.fromisoformat(end):
        raise SourceQueryError("time_range_reversed_or_empty")
    return start, end


def _limits(service: Any) -> dict[str, int]:
    return {
        "max_bytes": max(1, min(262144, service.config.int("memory_reconstruction.range_batch_max_bytes", 12288))),
        "max_messages": max(1, min(256, service.config.int("memory_reconstruction.range_batch_max_messages", 48))),
        "max_fragments": max(1, min(256, service.config.int("memory_reconstruction.range_batch_max_fragments", 64))),
        "excerpt_chars": max(1, min(800, service.config.int("memory_reconstruction.range_batch_excerpt_chars", 800))),
    }


def _bytes(value: Any) -> int:
    return len(json_dumps(value).encode("utf-8"))


def _meter(result: dict[str, Any]) -> int:
    # The byte counter is itself part of the serialized result.
    for _ in range(8):
        size = _bytes(result)
        if size == result["usage"]["returned_bytes"]:
            return size
        result["usage"]["returned_bytes"] = size
    raise SourceQueryError("source_query_failed")


async def query_range_batch(service: Any, event: Any, *, cursor: str = "", limit: int = 0,
                            **parameters: Any) -> dict[str, Any]:
    started = time.monotonic()
    try:
        if (not service.config.bool("memory_reconstruction.enabled", True)
                or not service.config.bool("memory_tools.enable_reconstruction_tool", True)):
            raise SourceQueryError("source_query_disabled")
        ctx = service._normalized_session_context(await query_context(service, event))
        if not service._scope_feature_enabled(ctx, "recall"):
            raise SourceQueryError("scope_recall_disabled")
        source_partition(ctx)
        if (not service.config.bool("memory_tools.enable_source_query_v2", False)
                or not binding_matches(service, event, ctx)):
            raise SourceQueryError("source_query_v2_not_offered")
        cursor = _text(cursor, 160)
        start, end = _parse(parameters, cursor, limit)
        turn_key = service._reconstruction_budget_key(event, ctx)
        previous = None
        if cursor:
            async with service._reconstruction_lock:
                state = service._reconstruction_states.get(turn_key, {})
                previous = deepcopy(state.get("source_batch_cursors", {}).get(cursor))
            if not previous or time.monotonic() >= previous["expires_at"]:
                raise SourceQueryError("cursor_invalid")
            start, end = previous["query"]["start_at"], previous["query"]["end_at"]
        limits = previous["limits"] if previous else _limits(service)
        query = {"action": "range_batch", "start_at": start, "end_at": end}
        signature = stable_fingerprint("source_range_batch", cursor or json_dumps(query), json_dumps(limits))
        budget = await service._reserve_reconstruction_step(event, ctx, signature)
        if not budget["accepted"]:
            raise SourceQueryError(budget["error"])
        expires_at = previous["expires_at"] if previous else started + 120.0
        expires_label = previous["expires_label"] if previous else datetime.fromtimestamp(
            time.time() + max(0, expires_at - time.monotonic()), timezone.utc,
        ).isoformat()
        policy = await service.store.memory_revision()
        if previous and previous["policy_revision"] != policy:
            raise SourceQueryError("cursor_invalid")
        page = await service.store.query_source_range_batch(
            ctx, start_at=start, end_at=end, limit=limits["max_messages"],
            boundary=previous["boundary"] if previous else None,
            expected_revision=previous["source_revision"] if previous else None,
        )
        next_cursor = "srcb_" + secrets.token_urlsafe(24)
        totals = dict(previous["totals"]) if previous else {
            "traversed_messages": 0, "completed_messages": 0, "suppressed_messages": 0,
            "returned_fragments": 0, "returned_chars": 0,
        }
        sequence = previous["sequence"] + 1 if previous else 1
        result: dict[str, Any] = {
            "profile": SOURCE_QUERY_PROFILE_V2, "ok": True, "status": "partial", "error": "",
            "query": query, "sources": [],
            "batch": {"batch_id": "sbb_" + secrets.token_hex(8), "work_id": "sbw_" + secrets.token_hex(8),
                      "sequence": sequence, "stop_reason": "fragment_budget", "next_batch_cursor": next_cursor,
                      "expires_at": expires_label},
            "coverage": {
                "traversal": {"scope": "current_session_only", "time_basis": "message_observation",
                              "interval": "[start,end)", "order": "message_time_asc", "eof": False,
                              "processed_messages": 0, "cumulative_messages": 0,
                              "first_source_ref": None, "last_source_ref": None,
                              "unknown_message_time": "excluded_from_time_order"},
                "presentation": {"status": "incomplete", "returned_messages": 0, "returned_fragments": 0,
                                 "suppressed_messages": 0, "cumulative_completed_messages": 0,
                                 "cumulative_fragments": 0, "cumulative_chars": 0,
                                 "cumulative_suppressed_messages": 0, "pending_excerpt": False},
                "interpretation": {"event_coverage": "not_established", "current_context": "unknown",
                                   "capture_coverage": "not_established"},
                "dependencies": {"validity_mode": "global", "source_revision": page["revision"],
                                 "policy_revision": policy},
            },
            "usage": {"step": budget["step"], "remaining_steps": budget["remaining_steps"], "model_calls": 0,
                      "read_count": page["read_count"], "returned_chars": 0, "returned_bytes": 0,
                      "elapsed_ms": 0, "limits": limits, "host_context_budget": "unknown"},
        }
        sources: list[dict[str, Any]] = result["sources"]
        source_bytes = 2
        offset = previous["excerpt_offset"] if previous else 0
        resume_boundary = page["next_boundary"]
        resume_offset = 0
        processed = suppressed = 0
        returned_refs: set[str] = set()
        first_ref = previous["first_source_ref"] if previous else None
        last_ref = previous["last_source_ref"] if previous else None
        eof = page["eof"] and not page["rows"]
        reason = "eof" if page["eof"] else "message_budget"
        # Reserve only envelope fields that can grow while later rows are processed.
        envelope = deepcopy(result)
        envelope["coverage"]["traversal"].update(
            processed_messages=len(page["rows"]), cumulative_messages=totals["traversed_messages"] + len(page["rows"]),
            first_source_ref=first_ref or ("timeline:" + page["rows"][0]["id"] if page["rows"] else None),
            last_source_ref=max(("timeline:" + row["id"] for row in page["rows"]), key=len, default=last_ref),
        )
        envelope["coverage"]["presentation"].update(
            returned_messages=limits["max_messages"], returned_fragments=limits["max_fragments"],
            suppressed_messages=limits["max_messages"],
            cumulative_completed_messages=totals["completed_messages"] + limits["max_messages"],
            cumulative_fragments=totals["returned_fragments"] + limits["max_fragments"],
            cumulative_chars=totals["returned_chars"] + limits["max_fragments"] * limits["excerpt_chars"],
            cumulative_suppressed_messages=totals["suppressed_messages"] + limits["max_messages"],
        )
        envelope["usage"].update(returned_chars=limits["max_fragments"] * limits["excerpt_chars"],
                                 returned_bytes=limits["max_bytes"], elapsed_ms=120000)
        envelope_bytes = _bytes(envelope) - 2
        for index, row in enumerate(page["rows"]):
            position = [row["source_sort_time"], row["created_at"], row["id"]]
            if (row["source_content_chars"] or 0) > 262144 or (row["source_metadata_chars"] or 0) > 65536:
                raise SourceQueryError("source_processing_budget_exceeded")
            text = service._navigation_source_text(ctx, row)
            template = service._serialize_navigation_source(ctx, row, prepared_text=text) if text else None
            visited = offset > 0
            if template is None:
                suppressed += 1
                totals["suppressed_messages"] += 1
                totals["traversed_messages"] += int(not visited)
                visited = True
            else:
                if offset >= len(text):
                    raise SourceQueryError("cursor_invalid")
                while offset < len(text):
                    if len(sources) >= limits["max_fragments"]:
                        reason = "fragment_budget"
                        break
                    size_limit = min(limits["excerpt_chars"], len(text) - offset)

                    def fragment(chars: int) -> dict[str, Any]:
                        stop = offset + chars
                        return {**template, "excerpt": text[offset:stop], "excerpt_offset": offset,
                                "excerpt_end": stop, "next_excerpt_offset": stop if stop < len(text) else None,
                                "excerpt_truncated": offset > 0 or stop < len(text)}

                    fitting = fragment(size_limit)
                    if envelope_bytes + source_bytes + _bytes(fitting) + int(bool(sources)) <= limits["max_bytes"]:
                        low, high = 1, 0
                    else:
                        # Completing a body removes the next offset and can be smaller than its penultimate fragment.
                        low, high, fitting = 1, size_limit - 1, None
                    while low <= high:
                        middle = (low + high) // 2
                        candidate = fragment(middle)
                        candidate_bytes = _bytes(candidate) + int(bool(sources))
                        if envelope_bytes + source_bytes + candidate_bytes <= limits["max_bytes"]:
                            fitting = candidate
                            low = middle + 1
                        else:
                            high = middle - 1
                    if fitting is None:
                        if not sources:
                            raise SourceQueryError("range_batch_budget_too_small")
                        reason = "byte_budget"
                        break
                    source_bytes += _bytes(fitting) + int(bool(sources))
                    sources.append(fitting)
                    returned_refs.add(fitting["source_ref"])
                    totals["traversed_messages"] += int(not visited)
                    visited = True
                    offset = fitting["excerpt_end"]
                    totals["returned_fragments"] += 1
                    totals["returned_chars"] += len(fitting["excerpt"])
                if offset == len(text):
                    totals["completed_messages"] += 1
            if visited:
                processed += 1
                ref = "timeline:" + row["id"]
                first_ref = first_ref or ref
                last_ref = ref
                eof = page["eof"] and index == len(page["rows"]) - 1
            if template is not None and offset < len(text):
                resume_boundary, resume_offset = position, offset
                break
            offset = 0
        has_more = resume_boundary is not None
        result["batch"].update(stop_reason=reason, next_batch_cursor=next_cursor if has_more else None)
        result["coverage"]["traversal"].update(
            eof=eof, processed_messages=processed, cumulative_messages=totals["traversed_messages"],
            first_source_ref=first_ref, last_source_ref=last_ref,
        )
        incomplete = has_more or totals["suppressed_messages"] > 0
        result["coverage"]["presentation"].update(
            status="incomplete" if incomplete else "complete", returned_messages=len(returned_refs),
            returned_fragments=len(sources), suppressed_messages=suppressed,
            cumulative_completed_messages=totals["completed_messages"], cumulative_fragments=totals["returned_fragments"],
            cumulative_chars=totals["returned_chars"], cumulative_suppressed_messages=totals["suppressed_messages"],
            pending_excerpt=resume_offset > 0,
        )
        result["status"] = "partial" if incomplete else ("batch" if sources else "empty")
        result["usage"].update(returned_chars=sum(len(item["excerpt"]) for item in sources),
                                elapsed_ms=max(0, round((time.monotonic() - started) * 1000)))
        if _meter(result) > limits["max_bytes"]:
            raise SourceQueryError("range_batch_budget_too_small")
        if time.monotonic() >= expires_at or not service._scope_feature_enabled(ctx, "recall"):
            raise SourceQueryError("source_query_expired_or_disabled")
        if (not service.config.bool("memory_tools.enable_source_query_v2", False)
                or not binding_matches(service, event, ctx)):
            raise SourceQueryError("source_query_v2_not_offered")
        if policy != await service.store.memory_revision() or page["revision"] != await service.store.source_revision():
            raise SourceQueryError("source_changed_retry")
        async with service._reconstruction_lock:
            state = service._reconstruction_states.get(turn_key)
            if state is None or time.monotonic() >= expires_at:
                raise SourceQueryError("cursor_invalid")
            if has_more:
                state.setdefault("source_batch_cursors", {})[next_cursor] = {
                    "query": query, "limits": limits, "boundary": resume_boundary, "excerpt_offset": resume_offset,
                    "source_revision": page["revision"], "policy_revision": policy, "expires_at": expires_at,
                    "expires_label": expires_label, "sequence": sequence, "totals": totals,
                    "first_source_ref": first_ref, "last_source_ref": last_ref,
                }
            if cursor:
                state.setdefault("consumed_source_cursors", set()).add(cursor)
            record_source_read(state, sources, source_revision=page["revision"], policy_revision=policy,
                               expires_at=expires_at, coverage=result["coverage"], event=event, ctx=ctx)
        return result
    except SourceQueryError as exc:
        return rejected(str(exc))
