"""Exact, authorized vector search with bounded, disposable local snapshots.

Only IDs, text versions and normalized numeric blocks survive snapshot building.
The caller supplies the existing visibility/lifecycle decision, not a second ACL.

Two invariants keep this module honest:

* A snapshot always covers every row that was eligible at ``revision``. A
  snapshot that lost blocks is flagged ``complete=False`` and the missing rows
  are re-read from SQLite before scoring, so a cache hit can never answer from a
  subset of the authorized corpus. ``embedding_snapshot_partial`` in the
  diagnostics says when that happened.
* The byte budget is a retention policy, not a correctness knob: raising or
  lowering it only changes how much work a later turn reuses.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import heapq
import inspect
import math
import struct
import time
from typing import Any, Callable, Iterable

from .models import MemoryRecord, clean_text, memory_embedding_text_hash


# Retention budget for published snapshots. 64MB used to be hard-coded here,
# which made the cache dead on any real deployment: one 4096-dim provider with
# 11k rows needs ~350MB (a single authorized group subset is already ~73MB), so
# every build tripped the ceiling, threw the snapshot away and re-scanned the
# whole corpus each turn (~1.2s). The default is now sized for that reality and
# configurable via ``retrieval_advanced.vector_snapshot_cache_mb``.
CACHE_BYTES = 512 * 1024 * 1024
MIN_CACHE_BYTES = 64 * 1024 * 1024
MAX_CACHE_BYTES = 8 * 1024 * 1024 * 1024
MB = 1024 * 1024
BLOCK_BYTES = 4 * 1024 * 1024
CACHE_ENTRIES = 4


def bounded_cache_bytes(megabytes: Any) -> int:
    """Clamp a configured snapshot budget (in MB) to a usable byte range.

    Missing/zero/negative/garbage values fall back to ``CACHE_BYTES`` instead of
    silently disabling retention, mirroring ``bounded_model_call_timeout_ms``:
    a broken setting must degrade to the safe default, never to "cache nothing"
    or "cache everything".
    """
    if isinstance(megabytes, bool):
        return CACHE_BYTES
    try:
        configured = float(megabytes)
    except (TypeError, ValueError, OverflowError):
        return CACHE_BYTES
    if not math.isfinite(configured) or configured <= 0:
        return CACHE_BYTES
    return max(MIN_CACHE_BYTES, min(int(configured * MB), MAX_CACHE_BYTES))


class VectorSnapshotChanged(RuntimeError):
    """The caller must resolve current authorization again before retrying."""


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_iso_timestamp(value: Any) -> float | None:
    """Parse an ISO-8601 timestamp to UTC epoch seconds without OS range errors."""
    if not value:
        return None
    text = value if isinstance(value, str) else str(value)
    text = clean_text(text, 80) if ("\u3000" in text or "  " in text) else text.strip()[:80]
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - _EPOCH).total_seconds()


def memory_time_ranges(memory: MemoryRecord) -> tuple[tuple[float, float], ...]:
    """Extract time overlap intervals identical to ``_memory_overlaps_time_window``."""
    metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
    ranges: list[tuple[float, float]] = []
    start_at = parse_iso_timestamp(metadata.get("start_at"))
    end_at = parse_iso_timestamp(metadata.get("end_at"))
    if start_at is not None or end_at is not None:
        start = start_at if start_at is not None else end_at
        end = end_at if end_at is not None else start_at
        if start is not None and end is not None:
            if end <= start:
                end = start + 86400.0
            ranges.append((start, end))
    for value in (memory.occurred_at, memory.created_at, memory.updated_at):
        ts = parse_iso_timestamp(value)
        if ts is not None:
            ranges.append((ts, ts + 1.0))
    return tuple(ranges)


@dataclass(frozen=True, slots=True)
class VectorRef:
    memory_id: str
    text_hash: str
    updated_at: str
    memory_type: str = ""
    time_ranges: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class VectorBlock:
    refs: tuple[VectorRef, ...]
    values: bytes  # Immutable float64 buffer; numpy views cannot mutate it.
    dimension: int

    @property
    def byte_size(self) -> int:
        return len(self.values) + sum(
            256
            + len(r.memory_id.encode("utf-8"))
            + len(r.text_hash)
            + len(r.updated_at)
            + len(r.memory_type)
            + len(r.time_ranges) * 32
            for r in self.refs
        )


@dataclass(frozen=True, slots=True)
class VectorSnapshot:
    revision: str
    valid_until: float
    blocks: tuple[VectorBlock, ...]
    counts: tuple[tuple[str, int], ...]
    byte_size: int
    # False when the budget forced the oldest blocks out. Callers must then
    # re-read the rows that no longer have a block instead of trusting
    # ``blocks`` alone; ``candidate_ids`` is what makes that subset computable.
    complete: bool = True
    candidate_ids: frozenset[str] | None = None

    @property
    def retained_ids(self) -> frozenset[str]:
        return frozenset(ref.memory_id for block in self.blocks for ref in block.refs)


@lru_cache(maxsize=1)
def _numpy() -> Any:
    # No native index dependency or matrix allocation during plugin startup.
    try:
        import numpy
        return numpy
    except ImportError:
        return None


def block_scores(block: VectorBlock, query: list[float]) -> list[float]:
    np = _numpy()
    if np is not None:
        matrix = np.frombuffer(block.values, dtype="<f8").reshape(-1, block.dimension)
        # Avoid launching a BLAS thread team for each small matrix/vector product.
        return np.einsum("ij,j->i", matrix, np.asarray(query), optimize=False).tolist()
    rows = struct.iter_unpack(f"<{block.dimension}d", block.values)
    return [math.fsum(a * b for a, b in zip(row, query)) for row in rows]


def _normalized_bytes(raw: Any, dimension: int) -> tuple[bytes, str]:
    from .store import _normalize_embedding_vector_values, _unpack_embedding_vector

    if isinstance(raw, (bytes, bytearray, memoryview)):
        if len(raw) != dimension * 8:
            return b"", "embedding_invalid"
        np = _numpy()
        if np is not None:
            vector = np.frombuffer(raw, dtype="<f8")
            if not np.isfinite(vector).all():
                return b"", "embedding_invalid"
            scale = float(np.max(np.abs(vector)))
            if not scale:
                return b"", "embedding_invalid"
            # Scaling prevents overflow without Python per-component conversion.
            scaled = vector / scale
            norm = float(np.sqrt(np.einsum("i,i->", scaled, scaled)))
            return (scaled / norm).astype("<f8", copy=False).tobytes(), ""
    vector = _normalize_embedding_vector_values(_unpack_embedding_vector(raw))
    if not vector:
        return b"", "embedding_invalid"
    if len(vector) != dimension:
        return b"", "embedding_dim_mismatch"
    return struct.pack(f"<{dimension}d", *vector), ""


def _normalize_blob_batch(
    blobs: list[bytes | bytearray | memoryview],
    dimension: int,
    np: Any,
) -> tuple[list[memoryview | None], list[str]]:
    """Batch-normalize fixed-length float64 BLOBs with numpy."""
    row_bytes = dimension * 8
    count = len(blobs)
    mat = np.frombuffer(b"".join(blobs), dtype="<f8").reshape(count, dimension)
    finite_mask = np.isfinite(mat).all(axis=1)
    scales = np.max(np.abs(mat), axis=1)
    valid_mask = finite_mask & (scales > 0.0)
    results: list[memoryview | None] = [None] * count
    errors: list[str] = ["embedding_invalid"] * count

    valid_indices = np.flatnonzero(valid_mask)
    if len(valid_indices) == 0:
        return results, errors
    valid_mat = mat if len(valid_indices) == count else mat[valid_indices]
    valid_scales = scales if len(valid_indices) == count else scales[valid_indices]
    scaled = valid_mat / valid_scales[:, None]
    norms = np.sqrt(np.einsum("ij,ij->i", scaled, scaled))
    normalized_buf = (scaled / norms[:, None]).astype("<f8", copy=False).tobytes()
    mv = memoryview(normalized_buf)
    for out_idx, src_idx in enumerate(valid_indices.tolist()):
        start = out_idx * row_bytes
        results[src_idx] = mv[start : start + row_bytes]
        errors[src_idx] = ""
    return results, errors


def _next_boundary(memory: MemoryRecord, now: float) -> float:
    boundary = math.inf
    metadata = memory.metadata
    for name in ("valid_from", "valid_to"):
        value = getattr(memory, name, "") or (metadata.get(name, "") if isinstance(metadata, dict) else "")
        stamp = parse_iso_timestamp(value)
        if stamp is not None and stamp > now:
            boundary = min(boundary, stamp)
    return boundary


def cache_budget_bytes(store: Any) -> int:
    """Resolved retention budget: per-store override, else the module default."""
    configured = getattr(store, "vector_snapshot_cache_bytes", None)
    if isinstance(configured, int) and not isinstance(configured, bool) and configured > 0:
        return configured
    return int(CACHE_BYTES)


def _retain_blocks(
    blocks: Iterable[VectorBlock],
    budget: int,
    *,
    block: VectorBlock | None = None,
    retained: int | None = None,
) -> tuple[list[VectorBlock], int, int]:
    """Retain the newest blocks that fit within ``budget``, optionally appending ``block``.

    Replacing "clear everything the moment we go over" with "forget the oldest
    blocks" is what makes a too-large corpus partially cacheable instead of
    never cacheable: the newest rows survive and the caller re-reads only what
    was evicted. Passing ``block=None`` trims an already-built block sequence
    to a smaller budget without rescanning the corpus. At least one block is
    always kept, because a block is bounded by ``BLOCK_BYTES`` and the budget
    floor is far above it.

    Returns ``(retained_blocks, retained_bytes, evicted_blocks)``. The running
    total is threaded through ``_build_blocks`` instead of being recomputed,
    because ``byte_size`` walks every ref and that path runs once per block.
    """
    retained_blocks = blocks if isinstance(blocks, list) else list(blocks)
    if retained is None:
        retained = sum(item.byte_size for item in retained_blocks)
    if block is not None:
        retained_blocks.append(block)
        retained += block.byte_size
    evicted = 0
    while retained > budget and len(retained_blocks) > 1:
        retained -= retained_blocks.pop(0).byte_size
        evicted += 1
    return retained_blocks, retained, evicted


def _candidate_where(store: Any, include_pending: bool) -> str:
    where = f"e.provider_id=? AND m.lifecycle!='archived' AND {store._recallable_memory_sql('m')}"
    if not include_pending:
        where += " AND m.review_status!='pending'"
    return where


def _memory_select_columns(conn: Any) -> str:
    """Project stored ``memories`` columns so SQLite skips VIRTUAL columns."""
    try:
        info = conn.execute("PRAGMA table_info(memories)").fetchall()
    except Exception:
        info = ()
    if not info:
        return "m.*"
    names = [str(row[1]) for row in info if len(row) > 1 and row[1]]
    return ", ".join(f"m.{name}" for name in names) if names else "m.*"


def _row_batches(conn: Any, provider_id: str, where: str, batch_size: int,
                 restrict_ids: tuple[str, ...] = ()) -> Any:
    """Yield row batches from the candidate join, optionally restricted to ids.

    The full scan is one cursor; the restricted re-read splits the id list into
    900-wide bind groups to stay portable to SQLite builds with a 999-variable
    cap (the same limit the payload reads already honour).
    """
    m_cols = _memory_select_columns(conn)
    columns = (f"SELECT {m_cols}, e.dimension AS embedding_dimension, "
               "e.text_hash AS embedding_text_hash FROM memory_embeddings e "
               "JOIN memories m ON m.id=e.memory_id")
    if not restrict_ids:
        cursor = conn.execute(f"{columns} WHERE {where}", (provider_id,))
        while rows := cursor.fetchmany(batch_size):
            yield rows
        return
    for offset in range(0, len(restrict_ids), 900):
        part = restrict_ids[offset:offset + 900]
        placeholders = ",".join("?" for _ in part)
        cursor = conn.execute(
            f"{columns} WHERE {where} AND m.id IN ({placeholders})",
            (provider_id, *part),
        )
        while rows := cursor.fetchmany(batch_size):
            yield rows


ReusableRow = tuple[str, str, bytes, int, int]


def _collect_reusable_rows(
    cache: dict[tuple, VectorSnapshot],
    *,
    revision: str | None,
    provider_id: str,
    dimension: int,
    max_text_chars: int,
    exclude_key: tuple | None = None,
) -> dict[str, ReusableRow]:
    """Index normalized vector slices from cached snapshots.

    When ``revision`` is ``None``, slices are collected across revisions so a
    database write only re-normalizes rows whose ``text_hash`` or
    ``updated_at`` actually changed.  Stores zero-copy
    ``(text_hash, updated_at, block.values, offset, row_bytes)`` references into
    already-cached ``VectorBlock.values`` buffers.
    """
    row_bytes = dimension * 8
    reusable: dict[str, ReusableRow] = {}
    for cached_key, snapshot in cache.items():
        if cached_key == exclude_key:
            continue
        if revision is not None and snapshot.revision != revision:
            continue
        if not isinstance(cached_key, tuple) or len(cached_key) < 4:
            continue
        if cached_key[0] != provider_id or cached_key[1] != dimension or cached_key[3] != max_text_chars:
            continue
        for block in snapshot.blocks:
            if block.dimension != dimension or len(block.values) != len(block.refs) * row_bytes:
                continue
            buf = block.values
            for index, ref in enumerate(block.refs):
                reusable[ref.memory_id] = (
                    ref.text_hash,
                    ref.updated_at,
                    buf,
                    index * row_bytes,
                    row_bytes,
                )
    return reusable


def _build_blocks(
    store: Any,
    conn: Any,
    provider_id: str,
    dimension: int,
    batch_size: int,
    max_text_chars: int,
    eligible: Callable[[MemoryRecord], bool],
    selection_time: float,
    counts: dict[str, int],
    check_cancelled: Callable[[], None],
    accept: Callable[[VectorBlock], None],
    budget: int,
    where: str,
    restrict_ids: tuple[str, ...] = (),
    reusable_rows: dict[str, ReusableRow] | None = None,
    expected_revision: str = "",
) -> tuple[list[VectorBlock], float, bool, frozenset[str], int]:
    """Scan candidate rows, score every block, and retain as many as fit.

    Scoring always covers *every* authorized row (``accept``); the budget only
    decides which blocks survive for the next turn. Returns the retained
    blocks, the clock boundary that can change eligibility, whether eviction
    happened, the ids of all admitted candidates, and the retained byte total.
    """
    cached_parser = getattr(store, "_cached_from_row_light", None)
    use_cached_parser = callable(cached_parser)
    supports_copy = False
    if use_cached_parser:
        try:
            supports_copy = "copy" in inspect.signature(cached_parser).parameters
        except (TypeError, ValueError):
            supports_copy = False
    cached_hasher = getattr(store, "_cached_embedding_text_hash", None)
    use_cached_hasher = callable(cached_hasher)
    np = _numpy()
    row_bytes = dimension * 8
    blocks: list[VectorBlock] = []
    admitted: set[str] = set()
    truncated = False
    retained = 0
    valid_until = math.inf
    for rows in _row_batches(conn, provider_id, where, batch_size, restrict_ids):
        check_cancelled()
        allowed = []
        for row in rows:
            counts["embedding_scanned_rows"] += 1
            if use_cached_parser:
                memory = (
                    cached_parser(row, revision=expected_revision, copy=False)
                    if supports_copy
                    else cached_parser(row, revision=expected_revision)
                )
            else:
                memory = MemoryRecord.from_row_light(row)
            # Include not-yet-active entries so a clock boundary can
            # admit them without requiring a database write.
            valid_until = min(valid_until, _next_boundary(memory, selection_time))
            if not eligible(memory):
                counts["embedding_unauthorized_or_inactive"] += 1
                continue
            counts["embedding_candidates"] += 1
            text_hash = (
                cached_hasher(memory, max_chars=max_text_chars, revision=expected_revision)
                if use_cached_hasher
                else memory_embedding_text_hash(memory, max_chars=max_text_chars)
            )
            if not row["embedding_text_hash"] or row["embedding_text_hash"] != text_hash:
                counts["embedding_stale"] += 1
                continue
            if row["embedding_dimension"] != dimension:
                counts["embedding_dim_mismatch"] += 1
                continue
            allowed.append(
                VectorRef(
                    memory.id,
                    text_hash,
                    memory.updated_at,
                    memory.memory_type,
                    memory_time_ranges(memory),
                )
            )
        refs: list[VectorRef] = []
        chunks: list[bytes | memoryview] = []
        reused_slices: list[memoryview | None] = []
        if reusable_rows:
            missing_refs: list[VectorRef] = []
            for ref in allowed:
                cached_row = reusable_rows.get(ref.memory_id)
                if (cached_row is not None
                        and cached_row[0] == ref.text_hash
                        and cached_row[1] == ref.updated_at):
                    reused_slices.append(
                        memoryview(cached_row[2])[cached_row[3]:cached_row[3] + cached_row[4]]
                    )
                else:
                    reused_slices.append(None)
                    missing_refs.append(ref)
        else:
            missing_refs = allowed

        # Read vector payloads only after authorization and only for rows not
        # already normalized in a sibling snapshot. Keep bind batches portable
        # to SQLite builds with a 999-variable cap.
        payloads: dict[str, Any] = {}
        for offset in range(0, len(missing_refs), 900):
            check_cancelled()
            part = missing_refs[offset:offset + 900]
            placeholders = ",".join("?" for _ in part)
            payloads.update(dict(conn.execute(
                f"SELECT memory_id, vector FROM memory_embeddings WHERE provider_id=? "
                f"AND memory_id IN ({placeholders})", [provider_id] + [r.memory_id for r in part])))

        batch_packed: dict[int, memoryview] = {}
        batch_errors: dict[int, str] = {}
        if np is not None and missing_refs:
            blob_positions: list[int] = []
            blob_values: list[bytes | bytearray | memoryview] = []
            for idx, ref in enumerate(allowed):
                if reused_slices and reused_slices[idx] is not None:
                    continue
                raw = payloads.get(ref.memory_id)
                if isinstance(raw, (bytes, bytearray, memoryview)) and len(raw) == row_bytes:
                    blob_positions.append(idx)
                    blob_values.append(raw)
            if len(blob_values) >= 8:
                normed_slices, norm_errors = _normalize_blob_batch(blob_values, dimension, np)
                for pos, slice_val, err in zip(blob_positions, normed_slices, norm_errors):
                    if err:
                        batch_errors[pos] = err
                    elif slice_val is not None:
                        batch_packed[pos] = slice_val

        for idx, ref in enumerate(allowed):
            cached_slice = reused_slices[idx] if reused_slices else None
            if cached_slice is not None:
                packed: bytes | memoryview = cached_slice
                counts["embedding_reused_rows"] = counts.get("embedding_reused_rows", 0) + 1
            elif idx in batch_errors:
                counts[batch_errors[idx]] += 1
                continue
            elif idx in batch_packed:
                packed = batch_packed[idx]
            else:
                packed, error = _normalized_bytes(payloads.get(ref.memory_id), dimension)
                if error:
                    counts[error] += 1
                    continue
            refs.append(ref)
            chunks.append(packed)
            admitted.add(ref.memory_id)
        if not refs:
            continue
        block = VectorBlock(tuple(refs), b"".join(chunks), dimension)
        accept(block)
        blocks, retained, evicted = _retain_blocks(blocks, budget, block=block, retained=retained)
        if evicted:
            truncated = True
    return blocks, valid_until, truncated, frozenset(admitted), retained


def search_embeddings_sync(
    store: Any, provider_id: str, query: list[float], expected_revision: str,
    authorization_key: tuple, eligible: Callable[[MemoryRecord], bool],
    include_pending: bool, top_k: int, threshold: float, batch_size: int,
    max_text_chars: int, selection_time: float, cancelled: Any,
    excluded_memory_types: frozenset[str] = frozenset(),
    ref_filter: Callable[[VectorRef], bool] | None = None,
    post_filter: Callable[[MemoryRecord], bool] | None = None,
) -> tuple[list[MemoryRecord], dict[str, float], dict[str, Any]]:
    started = time.perf_counter()
    dimension = len(query)
    batch_size = min(max(1, batch_size), max(1, BLOCK_BYTES // (8 * dimension)))
    key = (provider_id, dimension, bool(include_pending), max_text_chars, authorization_key)
    budget = cache_budget_bytes(store)
    excluded_types = frozenset(excluded_memory_types) if excluded_memory_types else frozenset()
    selected: list[tuple[float, VectorRef]] = []
    counts = {"embedding_candidates": 0, "embedding_scanned_rows": 0,
              "embedding_stale": 0, "embedding_dim_mismatch": 0, "embedding_invalid": 0,
              "embedding_unauthorized_or_inactive": 0}

    def check_cancelled() -> None:
        if cancelled.is_set() or store._closing or store._closed:
            raise RuntimeError("embedding_search_cancelled")

    def accept(block: VectorBlock) -> None:
        check_cancelled()
        scores = block_scores(block, query)
        best = heapq.nsmallest(
            top_k,
            ((max(-1.0, min(1.0, score)), ref) for score, ref in zip(scores, block.refs)
             if math.isfinite(score) and score >= threshold
             and not (excluded_types and ref.memory_type in excluded_types)
             and (ref_filter is None or ref_filter(ref))),
            key=lambda item: (-item[0], item[1].memory_id),
        )
        selected[:] = heapq.nsmallest(top_k, selected + best,
                                     key=lambda item: (-item[0], item[1].memory_id))

    # Serialize snapshot publication; writers keep their independent WAL connection.
    with store._vector_search_lock:
        check_cancelled()
        # A dedicated read connection: this scan runs concurrently with the
        # candidate bundle under ``asyncio.gather``, and sharing the bundle's
        # connection/lock made the two phases strictly sequential.
        conn, lock = store._vector_read_connection()
        with lock:
            conn.execute("BEGIN")
            reusable: dict[str, ReusableRow] | None = None
            try:
                row = conn.execute("SELECT revision FROM retrieval_revision WHERE singleton=1").fetchone()
                revision = str(row[0]) if row else "0"
                if revision != expected_revision:
                    raise VectorSnapshotChanged("embedding_revision_changed")
                cached = store._vector_search_cache.get(key)
                cache_hit = (
                    cached is not None
                    and cached.revision == revision
                    and cached.valid_until > selection_time
                )
                if not cache_hit or (cached is not None and not cached.complete):
                    reusable = _collect_reusable_rows(
                        store._vector_search_cache,
                        revision=None,
                        provider_id=provider_id,
                        dimension=dimension,
                        max_text_chars=max_text_chars,
                        exclude_key=key if cache_hit else None,
                    )
                for cached_key, value in list(store._vector_search_cache.items()):
                    if value.revision != revision or value.valid_until <= selection_time:
                        del store._vector_search_cache[cached_key]
                snapshot = cached if cache_hit else None
                publish = None
                reread_rows = 0
                reused_rows = 0
                if cache_hit and cached is not None:
                    if cached.byte_size > budget:
                        trimmed_blocks, trimmed_bytes, evicted = _retain_blocks(cached.blocks, budget)
                        if evicted:
                            trimmed_complete = (
                                len(trimmed_blocks) == len(cached.blocks) and cached.complete
                            )
                            all_candidates = (
                                cached.candidate_ids
                                if cached.candidate_ids is not None
                                else cached.retained_ids
                            )
                            snapshot = VectorSnapshot(
                                cached.revision,
                                cached.valid_until,
                                tuple(trimmed_blocks),
                                cached.counts,
                                trimmed_bytes,
                                complete=trimmed_complete,
                                candidate_ids=None if trimmed_complete else all_candidates,
                            )
                            publish = snapshot
                    counts.update(dict(snapshot.counts))
                    valid_until = snapshot.valid_until
                    for block in snapshot.blocks:
                        accept(block)
                    if not snapshot.complete:
                        # The budget forced the oldest blocks out of the cached
                        # snapshot. Score those rows again from SQLite so the
                        # answer still covers the whole authorized corpus. The
                        # re-read uses a scratch tally: the snapshot counts
                        # already describe the full scan and must not double.
                        missing = tuple(sorted(
                            (snapshot.candidate_ids or frozenset()) - snapshot.retained_ids
                        ))
                        if missing:
                            scratch = {name: 0 for name in counts}
                            _blocks, _until, _truncated, admitted, _retained = _build_blocks(
                                store, conn, provider_id, dimension, batch_size, max_text_chars,
                                eligible, selection_time, scratch, check_cancelled, accept, budget,
                                _candidate_where(store, include_pending), missing,
                                reusable_rows=reusable,
                                expected_revision=expected_revision,
                            )
                            reread_rows = len(admitted)
                            reused_rows = scratch.pop("embedding_reused_rows", 0)
                else:
                    blocks, valid_until, truncated, admitted, retained = _build_blocks(
                        store, conn, provider_id, dimension, batch_size, max_text_chars,
                        eligible, selection_time, counts, check_cancelled, accept, budget,
                        _candidate_where(store, include_pending),
                        reusable_rows=reusable,
                        expected_revision=expected_revision,
                    )
                    reused_rows = counts.pop("embedding_reused_rows", 0)
                    publish = VectorSnapshot(
                        revision, valid_until, tuple(blocks), tuple(counts.items()),
                        retained,
                        complete=not truncated,
                        candidate_ids=None if not truncated else admitted,
                    )

                ids = [ref.memory_id for _, ref in selected]
                memories = {}
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    for row in conn.execute(f"SELECT * FROM memories WHERE id IN ({placeholders})", ids):
                        memory = MemoryRecord.from_row(row)
                        memories[memory.id] = memory
                results, scores = [], {}
                for score, ref in selected:
                    memory = memories.get(ref.memory_id)
                    if (memory is None or memory.updated_at != ref.updated_at
                            or memory_embedding_text_hash(memory, max_chars=max_text_chars) != ref.text_hash
                            or not eligible(memory)
                            or (excluded_types and memory.memory_type in excluded_types)
                            or (post_filter is not None and not post_filter(memory))):
                        raise VectorSnapshotChanged("embedding_selected_record_changed")
                    results.append(memory)
                    scores[memory.id] = score
            finally:
                if reusable is not None:
                    reusable.clear()
                conn.rollback()
        check_cancelled()
        if store._memory_revision_sync() != expected_revision or time.time() >= valid_until:
            raise VectorSnapshotChanged("embedding_revision_or_clock_changed")
        target = publish if publish is not None else (snapshot if cache_hit else None)
        if target is not None:
            # Pop ``key`` before summing so shrinking or LRU promotion does not
            # double-count the previous snapshot and evict unrelated entries.
            store._vector_search_cache.pop(key, None)
            while store._vector_search_cache and (
                len(store._vector_search_cache) >= CACHE_ENTRIES
                or sum(s.byte_size for s in store._vector_search_cache.values()) + target.byte_size > budget
            ):
                store._vector_search_cache.pop(next(iter(store._vector_search_cache)))
            store._vector_search_cache[key] = target
        counts.update({"embedding_reason": "applied", "embedding_hits": len(results),
                       "embedding_search": "authorized_exact", "embedding_cache_hit": cache_hit,
                       "embedding_cache_retained": target is not None,
                       "embedding_snapshot_partial": bool(target is not None and not target.complete),
                       "embedding_reread_rows": reread_rows,
                       "embedding_reused_rows": reused_rows,
                       "embedding_snapshot_budget_bytes": budget,
                       "embedding_rows_materialized": len(memories), "embedding_batch_size": batch_size,
                       "embedding_snapshot_rows": counts["embedding_scanned_rows"],
                       "embedding_scanned_rows": 0 if cache_hit else counts["embedding_scanned_rows"],
                       "embedding_backend": "numpy_exact" if _numpy() is not None else "python_exact",
                       "embedding_search_ms": round((time.perf_counter() - started) * 1000, 3),
                       "embedding_revision": expected_revision, "embedding_threshold": threshold})
        return results, scores, counts
