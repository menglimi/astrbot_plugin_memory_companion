"""Bounded, owner-authorized discovery over source semantic projections."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
import math
import sqlite3
import struct
import time
from typing import Any, Mapping

from .query_session import query_context
from .source_evidence import message_source_version, record_source_read
from .source_query import source_partition
from .source_semantic import (
    build_semantic_window,
    find_active_generation,
    generation_status,
    read_semantic_neighbors,
    read_semantic_source,
    validate_semantic_snapshot,
)
from .vector_search import BLOCK_BYTES, VectorBlock, VectorRef, block_scores


PROFILE = "memory.local-source-discovery.v1"
_RRF_K = 60


def _empty(status: str = "rejected", error: str = "") -> dict[str, Any]:
    return {
        "profile": PROFILE, "ok": False, "status": status, "error": error,
        "matches": [], "sources": [], "coverage": {}, "usage": {},
    }


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("invalid_time_range")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid_time_range") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("time_range_requires_timezone")
    return parsed.astimezone(timezone.utc)


def _time_key(value: Any) -> float | None:
    parsed = _timestamp(value)
    return parsed.timestamp() if parsed is not None else None


def _inside_range(value: Any, start: datetime | None, end: datetime | None) -> bool:
    stamp = _time_key(value)
    if stamp is None:
        return start is None and end is None
    return not (start is not None and stamp < start.timestamp()
                or end is not None and stamp >= end.timestamp())


def _source_position(source: Mapping[str, Any]) -> tuple[float, str, str]:
    stamp = source.get("source_sort_time")
    try:
        sort_time = float(stamp)
    except (TypeError, ValueError):
        parsed = _timestamp(source.get("occurred_at"))
        if parsed is None:
            raise ValueError("semantic_window_time_untrusted")
        sort_time = parsed.timestamp()
    return sort_time, str(source.get("created_at") or ""), str(source.get("source_id") or "")


def _normalized_vector_blob(raw: Any, dimension: int) -> bytes | None:
    if not isinstance(raw, (bytes, bytearray, memoryview)) or len(raw) != dimension * 8:
        return None
    try:
        values = struct.unpack(f"<{dimension}d", raw)
    except struct.error:
        return None
    if not values or any(not math.isfinite(value) for value in values):
        return None
    scale = max(abs(value) for value in values)
    if not scale:
        return None
    scaled = [value / scale for value in values]
    norm = math.sqrt(math.fsum(value * value for value in scaled))
    if not math.isfinite(norm) or norm <= 0:
        return None
    return struct.pack(f"<{dimension}d", *(value / norm for value in scaled))


def _dependency_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("source_id"), item.get("source_version"), item.get("char_start"),
        item.get("char_end"), item.get("role"),
    )


def _project_semantic_document(
    conn: sqlite3.Connection,
    service: Any,
    ctx: Any,
    generation: str,
    fence: Mapping[str, Any],
    row: Mapping[str, Any],
    configuration: Mapping[str, Any],
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any] | None:
    source_id = str(row["anchor_source_id"])
    try:
        anchor = read_semantic_source(
            conn, generation, source_id, str(row["anchor_source_version"]),
            authorize_source=service._source_semantic_authorizer(ctx),
            project_text=service._project_semantic_source_text,
        )
        start_offset, end_offset = int(row["char_start"]), int(row["char_end"])
        if not 0 <= start_offset <= end_offset <= len(anchor["text"]):
            return None
        persisted = [dict(item) for item in conn.execute(
            "SELECT * FROM source_semantic_dependencies WHERE document_id=? ORDER BY dependency_order",
            (row["document_id"],),
        ).fetchall()]
        if row["view_kind"] == "fragment":
            input_text = anchor["text"][start_offset:end_offset]
            dependencies = [{
                "source_id": anchor["source_id"], "source_version": anchor["source_version"],
                "char_start": start_offset, "char_end": end_offset, "role": "anchor",
            }]
        elif row["view_kind"] == "window":
            neighbors = read_semantic_neighbors(
                conn, generation, anchor,
                authorize_source=service._source_semantic_authorizer(ctx),
                project_text=service._project_semantic_source_text,
            )
            anchor_position = _source_position(anchor)
            previous = following = None
            for item in neighbors:
                position = _source_position(item)
                if position < anchor_position and (previous is None or position > _source_position(previous)):
                    previous = item
                elif position > anchor_position and (following is None or position < _source_position(following)):
                    following = item
            built = build_semantic_window(
                anchor, char_start=start_offset, char_end=end_offset,
                previous=previous, following=following,
                max_chars=int(configuration["window_max_chars"]),
            )
            input_text, dependencies = built["input_text"], built["dependencies"]
        else:
            return None
        if [_dependency_key(item) for item in persisted] != [
                _dependency_key(item) for item in dependencies]:
            return None
        if hashlib.sha256(input_text.encode("utf-8")).hexdigest() != row["input_hash"]:
            return None
        checked = validate_semantic_snapshot(
            conn,
            generation=generation,
            expected_config_hash=str(fence["config_hash"]),
            source_change_sequence=int(fence["source_revision"]),
            view_kind=str(row["view_kind"]),
            anchor_source_id=source_id,
            anchor_source_version=str(row["anchor_source_version"]),
            char_start=start_offset,
            char_end=end_offset,
            input_text=input_text,
            dependencies=dependencies,
            authorize_source=service._source_semantic_authorizer(ctx),
            project_text=service._project_semantic_source_text,
        )
        # The time range selects semantic anchors.  A bounded window may need
        # to retain an adjacent message outside that range so the anchor's
        # stored input can still be revalidated; filtering the whole document
        # here would incorrectly discard an in-range anchor.  Keep the
        # out-of-range context ids for the response layer, where they can be
        # omitted and reported without weakening the anchor filter.
        checked_sources = [item[6] for item in checked]
        anchor_sources = [item[6] for item in checked if item[5] == "anchor"]
        if any(not _inside_range(item.get("occurred_at"), start, end) for item in anchor_sources):
            return None
        outside_context_ids = [
            item[1] for item in checked
            if item[5] == "context" and not _inside_range(item[6].get("occurred_at"), start, end)
        ]
        return {
            "dependencies": dependencies,
            "checked_sources": checked_sources,
            "outside_time_range_context_ids": outside_context_ids,
        }
    except (ValueError, TypeError, KeyError, sqlite3.Error):
        return None


def _semantic_candidates(
    conn: sqlite3.Connection,
    service: Any,
    ctx: Any,
    generation_row: Mapping[str, Any],
    query_vector: list[float],
    *,
    limit: int,
    scan_limit: int,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    generation = str(generation_row["generation"])
    configuration = json.loads(generation_row["config_json"])
    fence_row = conn.execute(
        "SELECT revision FROM source_semantic_revision WHERE singleton=1",
    ).fetchone()
    if fence_row is None:
        return {"candidates": [], "complete": False, "scanned": 0, "compared": 0}
    fence = {
        "config_hash": generation_row["config_hash"],
        "source_revision": int(fence_row[0]),
    }
    dimension = len(query_vector)
    block_rows = max(1, BLOCK_BYTES // max(8, dimension * 8))
    rows = conn.execute(
        """SELECT * FROM source_semantic_documents
           WHERE generation=? AND state='ready' AND vector_blob IS NOT NULL
           ORDER BY anchor_source_id,view_kind,char_start,char_end,document_id""",
        (generation,),
    )
    top: list[dict[str, Any]] = []
    scanned = compared = 0
    complete = True
    current_source = ""
    current_best: dict[str, Any] | None = None
    block_items: list[dict[str, Any]] = []
    block_vectors = bytearray()

    def flush_source() -> None:
        nonlocal current_best
        if current_best is None:
            return
        top.append(current_best)
        top.sort(key=lambda item: (-item["score"], item["source_id"]))
        del top[limit:]
        current_best = None

    def score_block() -> None:
        nonlocal current_source, current_best, compared, block_items, block_vectors
        if not block_items:
            return
        refs = tuple(VectorRef(
            str(item["document_id"]), str(item["input_hash"]), "",
        ) for item in block_items)
        scores = block_scores(VectorBlock(refs, bytes(block_vectors), dimension), query_vector)
        for item, score in zip(block_items, scores):
            compared += 1
            source_id = item["source_id"]
            if current_source and source_id != current_source:
                flush_source()
            current_source = source_id
            candidate = {**item, "score": max(-1.0, min(1.0, float(score)))}
            if (current_best is None or candidate["score"] > current_best["score"]
                    or (candidate["score"] == current_best["score"]
                        and candidate["document_id"] < current_best["document_id"])):
                current_best = candidate
        block_items = []
        block_vectors = bytearray()

    while True:
        raw = rows.fetchone()
        if raw is None:
            break
        if scanned >= scan_limit:
            complete = False
            break
        scanned += 1
        projected = _project_semantic_document(
            conn, service, ctx, generation, fence, dict(raw), configuration, start, end,
        )
        if projected is None:
            continue
        vector_blob = _normalized_vector_blob(raw["vector_blob"], dimension)
        if vector_blob is None or int(raw["vector_dimension"] or 0) != dimension:
            continue
        anchor = next((item for item in projected["dependencies"] if item["role"] == "anchor"), None)
        if anchor is None:
            continue
        block_items.append({
            "document_id": str(raw["document_id"]), "input_hash": str(raw["input_hash"]),
            "source_id": str(raw["anchor_source_id"]),
            "source_version": str(raw["anchor_source_version"]),
            "view_kind": str(raw["view_kind"]), "char_start": int(raw["char_start"]),
            "char_end": int(raw["char_end"]), "dependencies": projected["dependencies"],
            "outside_time_range_context_ids": projected["outside_time_range_context_ids"],
        })
        block_vectors.extend(vector_blob)
        if len(block_items) >= block_rows:
            score_block()
    score_block()
    flush_source()
    return {"candidates": top, "complete": complete, "scanned": scanned, "compared": compared}


def _literal_candidates(
    conn: sqlite3.Connection,
    ctx: Any,
    terms: tuple[str, ...],
    *,
    limit: int,
    scan_limit: int,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    if not terms:
        return {"candidates": [], "complete": True, "scanned": 0}
    partition, params = source_partition(ctx)
    clauses = [partition]
    time_params: list[Any] = []
    if start is not None or end is not None:
        clauses.append("julianday(t.occurred_at) IS NOT NULL")
    if start is not None:
        clauses.append("julianday(t.occurred_at)>=julianday(?)")
        time_params.append(start.isoformat())
    if end is not None:
        clauses.append("julianday(t.occurred_at)<julianday(?)")
        time_params.append(end.isoformat())
    match_sql = " OR ".join("instr(lower(t.content),lower(?))>0" for _ in terms)
    hit_sql = " + ".join("CASE WHEN instr(lower(t.content),lower(?))>0 THEN 1 ELSE 0 END" for _ in terms)
    clauses.append(f"({match_sql})")
    sql = f"""SELECT t.*,julianday(t.occurred_at) AS source_sort_time,({hit_sql}) AS term_hits
              FROM timeline t WHERE {' AND '.join(clauses)}
              ORDER BY term_hits DESC,julianday(t.occurred_at) DESC,t.created_at DESC,t.id DESC"""
    cursor = conn.execute(sql, list(terms) + params + time_params + list(terms))
    candidates: list[dict[str, Any]] = []
    scanned = 0
    while scanned <= scan_limit:
        row = cursor.fetchone()
        if row is None:
            return {"candidates": candidates, "complete": True, "scanned": scanned}
        if scanned == scan_limit:
            return {"candidates": candidates, "complete": False, "scanned": scanned}
        scanned += 1
        candidates.append({"row": dict(row), "term_hits": int(row["term_hits"] or 0)})
        if len(candidates) > limit:
            candidates.pop()
    return {"candidates": candidates, "complete": False, "scanned": scanned}


def _search_snapshot(
    service: Any,
    ctx: Any,
    generation_row: Mapping[str, Any] | None,
    query_vector: list[float] | None,
    terms: tuple[str, ...],
    *,
    limit: int,
    scan_limit: int,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    conn, lock = service.store._read_connection_for_bundle()
    with lock:
        conn.execute("BEGIN")
        try:
            revisions = conn.execute(
                "SELECT s.revision AS source_revision,m.revision AS policy_revision "
                "FROM source_query_revision s CROSS JOIN retrieval_revision m "
                "WHERE s.singleton=1 AND m.singleton=1"
            ).fetchone()
            if revisions is None:
                raise ValueError("source_index_unavailable")
            semantic = {"candidates": [], "complete": False, "scanned": 0, "compared": 0}
            generation_info = None
            if generation_row is not None:
                current = conn.execute(
                    "SELECT * FROM source_semantic_generations WHERE generation=?",
                    (generation_row["generation"],),
                ).fetchone()
                if current is not None and current["state"] in {"building", "ready"}:
                    generation_info = generation_status(conn, str(current["generation"]))
                    if query_vector is not None:
                        semantic = _semantic_candidates(
                            conn, service, ctx, dict(current), query_vector,
                            limit=limit, scan_limit=scan_limit, start=start, end=end,
                        )
            literal = _literal_candidates(
                conn, ctx, terms, limit=limit, scan_limit=scan_limit, start=start, end=end,
            ) if terms else {"candidates": [], "complete": True, "scanned": 0}
            return {
                "source_revision": str(revisions["source_revision"]),
                "policy_revision": str(revisions["policy_revision"]),
                "semantic": semantic, "literal": literal,
                "generation": generation_info,
            }
        finally:
            if conn.in_transaction:
                conn.rollback()


def _normalize_terms(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 6:
        raise ValueError("terms_must_be_array_up_to_6")
    terms = []
    for item in value:
        if not isinstance(item, str) or "\x00" in item:
            raise ValueError("invalid_term")
        term = item.strip()
        if not term or len(term) > 80:
            raise ValueError("invalid_term")
        if term not in terms:
            terms.append(term)
    return tuple(terms)


async def discover_sources(
    service: Any,
    event: Any,
    *,
    query: str,
    terms: Any = None,
    start_at: str = "",
    end_at: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    started = time.monotonic()
    if not service.config.bool("memory_reconstruction.enabled", True):
        return _empty("unavailable", "source_discovery_disabled")
    if not service.config.bool("source_semantic.enabled", False):
        return _empty("unavailable", "source_semantic_disabled")
    if not isinstance(query, str) or not query.strip() or "\x00" in query:
        return _empty("rejected", "invalid_query")
    query = query.strip()
    query_limit = max(1, min(2000, service.config.int("source_semantic.query_max_chars", 1000)))
    if len(query) > query_limit:
        return _empty("rejected", "query_too_long")
    try:
        normalized_terms = _normalize_terms(terms)
        start, end = _timestamp(start_at), _timestamp(end_at)
        if start is not None and end is not None and start >= end:
            raise ValueError("time_range_reversed_or_empty")
    except ValueError as exc:
        return _empty("rejected", str(exc))
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        return _empty("rejected", "invalid_limit")

    try:
        ctx = service._normalized_session_context(await query_context(service, event))
        if not service._scope_feature_enabled(ctx, "recall"):
            return _empty("unavailable", "scope_recall_disabled")
        source_partition(ctx)
    except Exception:
        return _empty("unavailable", "source_scope_unavailable")

    result_limit = service._reconstruction_per_step_limit(limit)
    signature = hashlib.sha256(json.dumps([
        "discover", query, normalized_terms, start.isoformat() if start else "",
        end.isoformat() if end else "", result_limit,
    ], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    budget = await service._reserve_reconstruction_step(event, ctx, signature)
    if not budget["accepted"]:
        return {**_empty("rejected", budget["error"]), "usage": {
            "step": budget["step"], "remaining_steps": budget["remaining_steps"],
        }}

    provider_id = str(service.config.get("source_semantic.provider_id", "") or "").strip()
    configuration = service._source_semantic_build_configuration(ctx, provider_id)
    if configuration is None:
        return {**_empty("unavailable", "source_semantic_configuration_incomplete"), "usage": {
            "step": budget["step"], "remaining_steps": budget["remaining_steps"],
        }}
    config_hash = service._source_semantic_config_hash(configuration)
    generation_row = await service._source_semantic_database(
        lambda conn: find_active_generation(conn, config_hash)
    )
    provider = await service._embedding_provider_by_id(provider_id) if provider_id else None
    query_embedding_attempted = False
    query_vector: list[float] | None = None
    semantic_error = ""
    if provider is None or generation_row is None:
        semantic_error = "semantic_provider_or_index_unavailable"
    elif generation_row.get("state") not in {"building", "ready"}:
        semantic_error = "semantic_generation_unavailable"
    else:
        query_embedding_attempted = True
        service._source_semantic_query_waiters += 1
        waiting_for_slot = True
        try:
            await service._embedding_background_semaphore.acquire()
            service._source_semantic_query_waiters -= 1
            waiting_for_slot = False
            vector = await service._embed_text_with_provider(
                provider, query, provider_id=provider_id,
                usage_task="source_semantic_query_embedding", strict_input=True,
                input_limit=query_limit,
            )
            query_vector = _normalize_vector(vector)
            if len(query_vector) != int(configuration["dimensions"]):
                query_vector = None
                semantic_error = "semantic_query_dimension_mismatch"
        except asyncio.CancelledError:
            raise
        except Exception:
            semantic_error = "semantic_query_embedding_unavailable"
        finally:
            if waiting_for_slot:
                service._source_semantic_query_waiters = max(0, service._source_semantic_query_waiters - 1)
            else:
                service._embedding_background_semaphore.release()
    if service._source_semantic_build_configuration(ctx, provider_id) != configuration:
        query_vector = None
        semantic_error = "semantic_configuration_changed"

    scan_limit = max(64, min(20000, service.config.int("source_semantic.documents_per_query", 5000)))
    snapshot = await service.store._run_recoverable_database_operation(
        partial(
            _search_snapshot, service, ctx, generation_row, query_vector, normalized_terms,
            limit=result_limit, scan_limit=scan_limit, start=start, end=end,
        )
    )
    semantic = snapshot["semantic"]
    literal = snapshot["literal"]

    semantic_ranked = semantic["candidates"] if query_vector is not None else []
    literal_ranked = literal["candidates"]
    fused: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(semantic_ranked, 1):
        fused[item["source_id"]] = {
            "source_id": item["source_id"], "semantic": item, "literal": None,
            "rrf": 1.0 / (_RRF_K + rank),
        }
    for rank, item in enumerate(literal_ranked, 1):
        source_id = str(item["row"]["id"])
        candidate = fused.setdefault(source_id, {
            "source_id": source_id, "semantic": None, "literal": None, "rrf": 0.0,
        })
        candidate["literal"] = item
        candidate["rrf"] += 1.0 / (_RRF_K + rank)
    ranked = sorted(fused.values(), key=lambda item: (-item["rrf"], item["source_id"]))[:result_limit]

    requested_ids: list[str] = []
    expected_versions: dict[str, str] = {}
    for candidate in ranked:
        semantic_item = candidate["semantic"]
        if semantic_item:
            for dep in semantic_item["dependencies"]:
                source_id = str(dep["source_id"])
                expected_versions[source_id] = str(dep["source_version"])
                requested_ids.append(source_id)
        literal_item = candidate["literal"]
        if literal_item:
            source_id = str(literal_item["row"]["id"])
            expected_versions[source_id] = str(literal_item["row"].get("source_version") or "")
            requested_ids.append(source_id)
    rows = await service.store.get_timeline_by_ids(list(dict.fromkeys(requested_ids))) if requested_ids else {}

    sources: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    included: dict[tuple[str, str], int] = {}
    context_only: set[tuple[str, str]] = set()
    for candidate in ranked:
        anchor_id = candidate["source_id"]
        semantic_item = candidate["semantic"]
        literal_item = candidate["literal"]
        anchor_dep = next((dep for dep in semantic_item["dependencies"] if dep["role"] == "anchor"), None) if semantic_item else None
        anchor_row = rows.get(anchor_id)
        if not isinstance(anchor_row, dict):
            continue
        anchor_version = expected_versions.get(anchor_id, "")
        if anchor_version and message_source_version(anchor_row) != anchor_version:
            return _empty("rejected", "source_changed_retry")
        excerpt_offset = int(anchor_dep["char_start"]) if anchor_dep else 0
        excerpt_limit = min(800, max(1, int(anchor_dep["char_end"]) - excerpt_offset)) if anchor_dep else 800
        source = service._serialize_navigation_source(
            ctx, anchor_row, excerpt_offset=excerpt_offset, terms=normalized_terms,
            excerpt_limit=excerpt_limit,
        )
        if source is None:
            continue
        source_key = (source["source_ref"], source["source_version"])
        if source_key not in included:
            if len(sources) >= result_limit:
                break
            sources.append(source)
            included[source_key] = len(sources) - 1
        elif source_key in context_only:
            # An anchor outranks a window context when both point at the same
            # source. Keep one source-level entry and prefer the anchor span.
            sources[included[source_key]] = source
            context_only.discard(source_key)
        branch_list = [name for name, value in (("semantic", semantic_item), ("literal", literal_item)) if value]
        context_refs: list[dict[str, Any]] = []
        context_status = "not_applicable"
        context_deps = [dep for dep in semantic_item["dependencies"] if dep["role"] == "context"] if semantic_item else []
        if context_deps:
            context_status = "shown"
            context_statuses: set[str] = set()
            outside_context_ids = set(
                semantic_item.get("outside_time_range_context_ids", ())
                if semantic_item else ()
            )
            for dep in context_deps:
                context_id = str(dep["source_id"])
                if context_id in outside_context_ids:
                    context_statuses.add("outside_time_range")
                    continue
                context_row = rows.get(context_id)
                if not isinstance(context_row, dict):
                    context_statuses.add("unavailable")
                    continue
                if message_source_version(context_row) != dep["source_version"]:
                    return _empty("rejected", "source_changed_retry")
                start_offset = int(dep["char_start"])
                context_source = service._serialize_navigation_source(
                    ctx, context_row, excerpt_offset=start_offset,
                    excerpt_limit=min(800, max(1, int(dep["char_end"]) - start_offset)),
                )
                if context_source is None:
                    context_statuses.add("unavailable")
                    continue
                key = (context_source["source_ref"], context_source["source_version"])
                if key not in included:
                    # Count only a genuinely new source against the response
                    # budget.  A context that is already an anchor (or was
                    # emitted by an earlier match) is free to reference.
                    if len(sources) >= result_limit:
                        context_statuses.add("not_returned_budget")
                        continue
                    sources.append(context_source)
                    included[key] = len(sources) - 1
                    context_only.add(key)
                visible_context = sources[included[key]]
                context_refs.append({
                    "source_ref": visible_context["source_ref"],
                    "source_version": visible_context["source_version"],
                    "offset": visible_context["excerpt_offset"],
                    "end": visible_context["excerpt_end"],
                    "role": "context",
                })
            if "not_returned_budget" in context_statuses:
                context_status = "not_returned_budget"
            elif "unavailable" in context_statuses:
                context_status = "unavailable"
            elif "outside_time_range" in context_statuses:
                context_status = "outside_time_range"
        matches.append({
            "source_ref": source["source_ref"], "source_version": source["source_version"],
            "offset": source["excerpt_offset"], "end": source["excerpt_end"],
            "branches": branch_list, "context": context_refs, "context_status": context_status,
        })

    # A context can be emitted before the same source is later selected as an
    # anchor. Refresh references so every context points at the one serialized
    # source span that the caller actually receives.
    for match in matches:
        for context_ref in match.get("context", []):
            key = (context_ref.get("source_ref"), context_ref.get("source_version"))
            index = included.get(key)
            if index is None:
                continue
            visible = sources[index]
            context_ref["offset"] = visible["excerpt_offset"]
            context_ref["end"] = visible["excerpt_end"]

    current_revisions = await service.store.query_progress_revisions()
    expected_revisions = (snapshot["source_revision"], snapshot["policy_revision"])
    if tuple(current_revisions) != expected_revisions:
        return _empty("rejected", "source_changed_retry")

    generation_info = snapshot["generation"]
    if query_vector is None or generation_info is None:
        index_coverage = "unavailable" if semantic_error else "unknown"
    else:
        generation_config = json.loads(generation_row["config_json"])
        is_complete = (
            generation_config.get("coverage_mode") == "session_history"
            and generation_info.get("state") == "ready"
            and generation_info.get("scan_complete") is True
            and not any(generation_info.get(key, 0) for key in (
                "dirty_count", "order_change_count", "pending_documents", "stale_documents",
            ))
        )
        index_coverage = "complete" if is_complete else "partial"
    ranking_complete = bool(semantic["complete"] and (not normalized_terms or literal["complete"]))
    if query_vector is None:
        ranking_complete = False
    coverage = {
        "selection": "ranked_candidates", "order": "relevance",
        "index_coverage": index_coverage, "ranking_complete": ranking_complete,
        "semantic_status": "available" if query_vector is not None else "unavailable",
        "literal_status": "available" if normalized_terms and literal["complete"] else (
            "partial" if normalized_terms else "not_requested"
        ),
        "event_coverage": "not_established",
        "time_basis": "message_observation",
        "start_at": start.isoformat() if start else "",
        "end_at": end.isoformat() if end else "",
        "context_gap": "not_returned_when_budgeted" if any(
            item.get("context_status") == "not_returned_budget" for item in matches
        ) else "",
    }
    if semantic_error and not normalized_terms:
        status = "unavailable"
    elif not matches and (index_coverage != "complete" or not ranking_complete):
        status = "partial"
    elif matches and (index_coverage != "complete" or not ranking_complete):
        status = "partial"
    elif matches:
        status = "candidates"
    else:
        status = "empty"
    turn_key = service._reconstruction_budget_key(event, ctx)
    async with service._reconstruction_lock:
        state = service._reconstruction_states.get(turn_key)
        if state is None or service._closing:
            return _empty("rejected", "query_state_changed")
        record_source_read(
            state, sources, source_revision=snapshot["source_revision"],
            policy_revision=snapshot["policy_revision"], expires_at=started + 120.0,
            coverage=coverage, event=event, ctx=ctx,
        )
    usage = {
        "step": budget["step"], "remaining_steps": budget["remaining_steps"],
        "query_embedding_attempted": query_embedding_attempted,
        "query_embedding_calls": int(query_embedding_attempted),
        "compared_documents": int(semantic.get("compared", 0)),
        "returned_sources": len(sources), "model_calls": int(query_embedding_attempted),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
    }
    return {
        **_empty(status), "ok": status in {"candidates", "partial", "empty"},
        "error": semantic_error if status == "unavailable" else "",
        "matches": matches, "sources": sources, "coverage": coverage, "usage": usage,
    }


def _normalize_vector(values: Any) -> list[float]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("semantic_query_vector_invalid")
    vector = [float(value) for value in values]
    if any(not math.isfinite(value) for value in vector):
        raise ValueError("semantic_query_vector_invalid")
    scale = max(abs(value) for value in vector)
    if scale <= 0:
        raise ValueError("semantic_query_vector_invalid")
    scaled = [value / scale for value in vector]
    norm = math.sqrt(math.fsum(value * value for value in scaled))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("semantic_query_vector_invalid")
    return [value / norm for value in scaled]
