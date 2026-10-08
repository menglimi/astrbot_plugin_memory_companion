"""Validate source-backed model interpretations and reduce temporary event groups.

No topic recognizer, semantic model call, SQL from the caller, or memory write.
The caller supplies semantics; the owner validates provenance and calculates.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .source_query import SourceQueryError, _instant, source_partition
from .query_session import query_context


PROFILE = "memory.local-event-query.v1"
CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "docs/contracts/event-query/v1"
MAX_PLAN_BYTES = 48000
MAX_ROWS = 48
MAX_SOURCES = 96


class EventQueryError(ValueError):
    pass


def _object(value: Any, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or not required <= set(value):
        raise EventQueryError("invalid_plan_shape")
    return value


def _string(value: Any, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or (not empty and not value.strip()):
        raise EventQueryError("invalid_plan_text")
    return value.strip()


def _choice(value: Any, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise EventQueryError("unsupported_plan_value")
    return value


def _zone(value: Any) -> ZoneInfo:
    name = _string(value, 80)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise EventQueryError("unknown_timezone") from exc


def _utc(value: Any) -> datetime:
    try:
        parsed = _instant(value)
        if not parsed:
            raise ValueError
        return datetime.fromisoformat(parsed)
    except (ValueError, TypeError) as exc:
        raise EventQueryError("time_requires_iso8601_with_timezone") from exc


def _time_spec(value: Any) -> dict[str, Any]:
    value = _object(value, {"kind", "date", "at", "start_at", "end_at", "timezone", "source_ref", "days"}, {"kind"})
    kind = _choice(value["kind"], {"unknown", "date", "relative_day", "instant", "interval"})
    fields = {
        "unknown": {"kind"}, "date": {"kind", "date", "timezone", "source_ref"},
        "relative_day": {"kind", "source_ref", "days", "timezone"},
        "instant": {"kind", "at", "source_ref"},
        "interval": {"kind", "start_at", "end_at", "source_ref"},
    }[kind]
    if set(value) != fields:
        raise EventQueryError("invalid_event_time_shape")
    if kind != "unknown":
        _string(value["source_ref"], 180)
    if "timezone" in value:
        _zone(value["timezone"])
    if kind == "date":
        try:
            parsed = date.fromisoformat(value["date"])
            if parsed.isoformat() != value["date"]:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise EventQueryError("invalid_event_date") from exc
    if kind == "relative_day":
        days = value["days"]
        if isinstance(days, bool) or not isinstance(days, int) or not -36600 <= days <= 36600:
            raise EventQueryError("invalid_day_offset")
    if kind == "instant":
        _utc(value["at"])
    if kind == "interval" and _utc(value["start_at"]) >= _utc(value["end_at"]):
        raise EventQueryError("time_range_reversed_or_empty")
    return deepcopy(value)


def parse_plan(value: Any) -> dict[str, Any]:
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise EventQueryError("invalid_plan_json") from exc
    if size > MAX_PLAN_BYTES:
        raise EventQueryError("event_plan_too_large")
    plan = _object(value, {"goal", "unit", "operation", "timezone", "window", "select", "rows"},
                   {"goal", "unit", "operation", "timezone", "select", "rows"})
    result = {"goal": _string(plan["goal"], 240), "unit": _string(plan["unit"], 120),
              "operation": _choice(plan["operation"], {"list", "count", "latest", "earliest", "by_day"}),
              "timezone": _zone(plan["timezone"]).key, "window": None, "rows": []}
    if plan.get("window") is not None:
        window = _object(plan["window"], {"start_at", "end_at"}, {"start_at", "end_at"})
        start, end = _utc(window["start_at"]), _utc(window["end_at"])
        if start >= end:
            raise EventQueryError("time_range_reversed_or_empty")
        result["window"] = {"start_at": start.isoformat(), "end_at": end.isoformat()}
    if result["operation"] == "by_day" and result["window"] is None:
        raise EventQueryError("by_day_requires_event_window")
    selection = _object(plan["select"], {"subject", "world", "occurrences"}, {"subject", "world", "occurrences"})
    occurrence_values = {"occurred", "not_occurred", "planned", "cancelled", "unknown"}
    occurrences = selection["occurrences"]
    if not isinstance(occurrences, list) or not 1 <= len(occurrences) <= 4:
        raise EventQueryError("invalid_occurrence_selection")
    result["select"] = {
        "subject": _choice(selection["subject"], {"current_user", "assistant", "other", "any"}),
        "world": _choice(selection["world"], {"real", "fictional", "any"}),
        "occurrences": list(dict.fromkeys(_choice(item, occurrence_values - {"unknown"}) for item in occurrences)),
    }
    if not isinstance(plan["rows"], list) or not 1 <= len(plan["rows"]) <= MAX_ROWS:
        raise EventQueryError("event_rows_require_1_to_48")
    ids: set[str] = set()
    refs: set[str] = set()
    required = {"row_id", "event_key", "description", "subject", "world", "occurrence", "relevance", "identity", "resolution", "time", "evidence"}
    for raw in plan["rows"]:
        raw = _object(raw, required | {"supersedes"}, required)
        row = {key: _string(raw[key], 80 if key != "description" else 240) for key in ("row_id", "event_key", "description")}
        if row["row_id"] in ids:
            raise EventQueryError("duplicate_row_id")
        ids.add(row["row_id"])
        for key, allowed in {
            "subject": {"current_user", "assistant", "other", "unknown"},
            "world": {"real", "fictional", "unknown"}, "occurrence": occurrence_values,
            "relevance": {"match", "not_match", "uncertain"}, "identity": {"clear", "uncertain"},
            "resolution": {"resolved", "uncertain", "conflicting"},
        }.items():
            row[key] = _choice(raw[key], allowed)
        row["time"] = _time_spec(raw["time"])
        evidence = raw["evidence"]
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 6:
            raise EventQueryError("event_requires_1_to_6_citations")
        row["evidence"] = []
        for citation in evidence:
            _object(citation, {"source_ref", "source_version", "quote"}, {"source_ref", "source_version", "quote"})
            item = {key: _string(citation[key], length) for key, length in (("source_ref", 180), ("source_version", 128), ("quote", 800))}
            if not item["source_ref"].startswith("timeline:tl_"):
                raise EventQueryError("invalid_source_ref")
            refs.add(item["source_ref"])
            row["evidence"].append(item)
        if row["time"].get("source_ref") and row["time"]["source_ref"] not in {item["source_ref"] for item in row["evidence"]}:
            raise EventQueryError("time_anchor_requires_citation")
        replacements = raw.get("supersedes", [])
        if not isinstance(replacements, list) or len(replacements) > MAX_ROWS:
            raise EventQueryError("invalid_supersedes")
        row["supersedes"] = list(dict.fromkeys(_string(item, 80) for item in replacements))
        result["rows"].append(row)
    if len(refs) > MAX_SOURCES:
        raise EventQueryError("too_many_cited_sources")
    by_id = {row["row_id"]: row for row in result["rows"]}
    visited: set[str] = set()
    def visit(row_id: str, path: set[str]) -> None:
        if row_id in path:
            raise EventQueryError("cyclic_correction")
        if row_id in visited:
            return
        row = by_id[row_id]
        for target in row["supersedes"]:
            if target not in by_id or by_id[target]["event_key"] != row["event_key"]:
                raise EventQueryError("correction_requires_same_event")
            visit(target, path | {row_id})
        visited.add(row_id)
    for row_id in by_id:
        visit(row_id, set())
    return result


def _resolve_time(spec: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    kind = spec["kind"]
    if kind == "unknown":
        return None
    try:
        if kind == "instant":
            start = end = _utc(spec["at"])
        elif kind == "interval":
            start, end = _utc(spec["start_at"]), _utc(spec["end_at"])
        else:
            zone = _zone(spec["timezone"])
            day = date.fromisoformat(spec["date"]) if kind == "date" else (
                _utc(sources[spec["source_ref"]]["message_at"]).astimezone(zone).date() + timedelta(days=spec["days"])
            )
            start = datetime.combine(day, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
            end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
        return {"start_at": start.isoformat(), "end_at": end.isoformat(),
                "precision": "instant" if start == end else ("day" if kind in {"date", "relative_day"} else "interval"),
                "basis": "model_interpretation_of_cited_source"}
    except (EventQueryError, OverflowError, ValueError):
        return None


def _bounds(value: dict[str, Any]) -> tuple[datetime, datetime]:
    return datetime.fromisoformat(value["start_at"]), datetime.fromisoformat(value["end_at"])


def _intersect(times: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, bool]:
    if not times:
        return None, False
    bounds = [_bounds(item) for item in times]
    start, end = max(pair[0] for pair in bounds), min(pair[1] for pair in bounds)
    if start > end or (start == end and not all(a == b == start or a <= start < b for a, b in bounds)):
        return None, True
    whole_day = all(item["precision"] == "day" and _bounds(item) == (start, end) for item in times)
    precision = "instant" if start == end else ("day" if whole_day else "interval")
    return {"start_at": start.isoformat(), "end_at": end.isoformat(), "precision": precision,
            "basis": "model_interpretation_of_cited_source"}, False


def _window_relation(value: dict[str, Any] | None, window: dict[str, Any] | None) -> str:
    if window is None:
        return "inside"
    if value is None:
        return "unknown"
    start, end = _bounds(value)
    lower, upper = _bounds(window)
    if start == end:
        return "inside" if lower <= start < upper else "outside"
    if end <= lower or start >= upper:
        return "outside"
    return "inside" if lower <= start and end <= upper else "overlap"


def reduce_events(plan: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in plan["rows"]:
        groups.setdefault(row["event_key"], []).append(row)
    events, excluded, unresolved = [], [], []
    for event_key, rows in groups.items():
        superseded = {target for row in rows for target in row["supersedes"]}
        active = [row for row in rows if row["row_id"] not in superseded]
        times = [value for row in active if (value := _resolve_time(row["time"], sources))]
        event_time, time_conflict = _intersect(times)
        item = {"event_key": event_key, "kind": "temporary_event", "interpretation_by": "current_model",
                "row_ids": [row["row_id"] for row in rows], "superseded_row_ids": sorted(superseded),
                "descriptions": list(dict.fromkeys(row["description"] for row in active)),
                "time": event_time, "evidence": [], "reasons": []}
        for row in rows:
            for citation in row["evidence"]:
                if citation not in item["evidence"]:
                    item["evidence"].append(citation)
        reasons = item["reasons"]
        for field in ("subject", "world", "occurrence", "relevance", "identity", "resolution"):
            values = {row[field] for row in active}
            item[field] = next(iter(values)) if len(values) == 1 else "conflict"
            if len(values) != 1:
                reasons.append(field + "_conflict")
        if time_conflict:
            reasons.append("event_time_conflict")
        if reasons:
            unresolved.append(item)
            continue
        if item["relevance"] == "not_match":
            reasons.append("not_matching_goal")
        for field in ("subject", "world"):
            requested = plan["select"][field]
            if requested != "any" and item[field] not in {requested, "unknown"}:
                reasons.append(field + "_outside_selection")
        if item["occurrence"] != "unknown" and item["occurrence"] not in plan["select"]["occurrences"]:
            reasons.append("occurrence_outside_selection")
        relation = _window_relation(event_time, plan["window"])
        if relation == "outside":
            reasons.append("outside_event_window")
        if reasons:
            excluded.append(item)
            continue
        if item["relevance"] == "uncertain" or item["identity"] == "uncertain":
            reasons.append("semantic_identity_or_match_unresolved")
        if item["resolution"] != "resolved":
            reasons.append("model_reported_unresolved_interpretation")
        if any(item[field] == "unknown" for field in ("subject", "world", "occurrence")):
            reasons.append("semantic_attributes_unresolved")
        if relation in {"unknown", "overlap"}:
            reasons.append("event_window_membership_unresolved")
        if reasons:
            unresolved.append(item)
        else:
            events.append(item)
    # Stable display order is not a proof that overlapping intervals are ordered.
    events.sort(key=lambda item: (_bounds(item["time"])[0] if item["time"] else datetime.max.replace(tzinfo=timezone.utc), item["event_key"]))
    latest: list[str] = []
    earliest: list[str] = []
    timed = [item for item in events if item["time"]]
    def definitely_before(a: dict[str, Any], b: dict[str, Any]) -> bool:
        a_start, a_end = _bounds(a["time"])
        b_start, _ = _bounds(b["time"])
        return a_end < b_start or (a_end == b_start and a_start != a_end)
    for item in timed:
        if not any(definitely_before(item, other) for other in timed if other is not item):
            latest.append(item["event_key"])
        if not any(definitely_before(other, item) for other in timed if other is not item):
            earliest.append(item["event_key"])
    by_day: dict[str, list[dict[str, Any]]] = {}
    unplaced = []
    zone = _zone(plan["timezone"])
    for item in events:
        if not item["time"]:
            unplaced.append(item["event_key"])
            continue
        start, end = _bounds(item["time"])
        first = start.astimezone(zone).date()
        last = (end - timedelta(microseconds=1) if start != end else start).astimezone(zone).date()
        if first != last:
            unplaced.append(item["event_key"])
        else:
            by_day.setdefault(first.isoformat(), []).append(item)
    missing_days: list[str] = []
    day_grid = "not_requested"
    if plan["operation"] == "by_day" and plan["window"]:
        lower, upper = _bounds(plan["window"])
        first, last = lower.astimezone(zone).date(), (upper - timedelta(microseconds=1)).astimezone(zone).date()
        size = (last - first).days + 1
        day_grid = "enumerated" if size <= 31 else "omitted_over_31_days"
        if size <= 31:
            missing_days = [(first + timedelta(days=i)).isoformat() for i in range(size)
                            if (first + timedelta(days=i)).isoformat() not in by_day]
    return {
        "events": events, "excluded": excluded, "unresolved": unresolved,
        "aggregate": {
            "unit": plan["unit"], "count_basis": "model_resolved_event_groups_in_supplied_rows",
            "count": len(events), "by_occurrence": dict(Counter(item["occurrence"] for item in events)),
            "latest_candidates": latest, "earliest_candidates": earliest,
            "ordering": "unresolved" if unresolved or len(timed) != len(events) else "interval_partial_order",
            "by_day": [{"date": day, "event_keys": [item["event_key"] for item in values], "count": len(values),
                        "by_occurrence": dict(Counter(item["occurrence"] for item in values))} for day, values in sorted(by_day.items())],
            "unplaced_event_keys": unplaced, "days_without_resolved_events": missing_days,
            "day_grid": day_grid, "absence_meaning": "no_resolved_event_in_supplied_rows_not_proof_of_no_event",
        },
    }


def rejected(error: str) -> dict[str, Any]:
    return {"profile": PROFILE, "ok": False, "status": "rejected", "error": error,
            "events": [], "excluded": [], "unresolved": [], "aggregate": {}, "coverage": {}, "usage": {}}


async def query_events(service: Any, event: Any, plan: Any) -> dict[str, Any]:
    started = time.monotonic()
    try:
        if not service.config.bool("memory_reconstruction.enabled", True) or not service.config.bool("memory_tools.enable_reconstruction_tool", True):
            raise EventQueryError("event_query_disabled")
        plan = parse_plan(plan)
        ctx = service._normalized_session_context(await query_context(service, event))
        if not service._scope_feature_enabled(ctx, "recall"):
            raise EventQueryError("scope_recall_disabled")
        source_partition(ctx)
        turn_key = service._reconstruction_budget_key(event, ctx)
        async with service._reconstruction_lock:
            live = service._reconstruction_states.get(turn_key, {})
            state = {key: deepcopy(live.get(key, default)) for key, default in (("issued_sources", {}), ("source_reads", []))}
        issued = state.get("issued_sources", {})
        cited = {item["source_ref"]: item["source_version"] for row in plan["rows"] for item in row["evidence"]}
        for row in plan["rows"]:
            for citation in row["evidence"]:
                receipt = issued.get(citation["source_ref"])
                if not receipt or receipt["source_version"] != citation["source_version"] or time.monotonic() > receipt["expires_at"]:
                    raise EventQueryError("source_not_observed_this_turn_or_expired")
        signature = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        budget = await service._reserve_reconstruction_step(event, ctx, "event_query:" + signature)
        if not budget["accepted"]:
            raise EventQueryError(budget["error"])
        policy, revision = await service.store.memory_revision(), await service.store.source_revision()
        if any(issued[ref]["policy_revision"] != policy or issued[ref]["source_revision"] != revision for ref in cited):
            raise EventQueryError("source_changed_retry")
        rows = await service.store.get_timeline_by_ids([ref[len("timeline:"):] for ref in cited])
        current = {}
        texts = {}
        for ref, version in cited.items():
            row = rows.get(ref[len("timeline:"):])
            source = service._serialize_navigation_source(ctx, row) if row else None
            if not source or source["source_version"] != version:
                raise EventQueryError("source_unavailable_or_changed")
            current[ref] = source
            metadata = json.loads(row.get("metadata") or "{}")
            texts[ref] = (row.get("content") or "") if metadata.get("capture_profile") == "memory.source-capture.v1" else service.injection._redact_sensitive_text(row.get("content") or "")
        for row in plan["rows"]:
            for citation in row["evidence"]:
                ref = citation["source_ref"]
                if not any(citation["quote"] in texts[ref][start:end] for start, end in issued[ref]["spans"]):
                    raise EventQueryError("quote_not_in_observed_fragment")
        result = reduce_events(plan, current)
        if not service._scope_feature_enabled(ctx, "recall") or policy != await service.store.memory_revision() or revision != await service.store.source_revision():
            raise EventQueryError("source_changed_retry")
        async with service._reconstruction_lock:
            live_state = service._reconstruction_states.get(turn_key)
            if live_state is None or any(ref not in live_state.get("issued_sources", {}) for ref in cited):
                raise EventQueryError("source_not_observed_this_turn_or_expired")
        if any(time.monotonic() > issued[ref]["expires_at"] for ref in cited):
            raise EventQueryError("source_not_observed_this_turn_or_expired")
        now = time.monotonic()
        reads = [{
            "selection": read["selection"], "source_revision": read["source_revision"],
            "start_at": read.get("start_at", ""), "end_at": read.get("end_at", ""),
            "more_available": read.get("more_available"),
            "returned_count": len(read["source_refs"]),
            "excerpt_truncated_count": read.get("excerpt_truncated_count"),
        } for read in state.get("source_reads", [])
            if read["source_revision"] == revision and read["policy_revision"] == policy and read["expires_at"] >= now]
        valid_observed = {ref for ref, receipt in issued.items() if receipt["source_revision"] == revision
                          and receipt["policy_revision"] == policy and receipt["expires_at"] >= now}
        coverage = {
            "scope": "current_session_only", "event_window": plan["window"],
            "source_revision": revision, "event_coverage": "not_established",
            "semantics": "model_interpretation_not_verified_by_program",
            "citations": "observed_fragments_revalidated", "input_rows": len(plan["rows"]),
            "cited_source_count": len(cited), "observed_uncited_source_count": len(valid_observed - set(cited)),
            "source_reads": reads, "not_checked": ["semantic_exhaustiveness", "capture_completeness", "cross_session_sources"],
        }
        return {"profile": PROFILE, "ok": True, "status": "computed", "error": "",
                "operation": plan["operation"], "goal": plan["goal"], "select": plan["select"],
                **result, "coverage": coverage,
                "usage": {"step": budget["step"], "remaining_steps": budget["remaining_steps"],
                          "model_calls": 0, "source_reads": len(rows), "memory_writes": 0,
                          "elapsed_ms": round((time.monotonic() - started) * 1000)}}
    except (EventQueryError, SourceQueryError) as exc:
        return rejected(str(exc))


def bind_event_tool_schema(manager: Any, module_path: str) -> bool:
    """Use the reviewed nested schema; the docstring parser only sees an object."""
    tool = manager.get_func("memory_companion_events")
    if tool is None or tool.handler_module_path != module_path:
        return False
    schema = json.loads((CONTRACT_ROOT / "schemas/request.schema.json").read_text(encoding="utf-8"))
    tool.parameters = {key: value for key, value in schema.items() if key not in {"$schema", "$id", "title"}}
    return True
