"""Exact, authorized vector search with shared incremental corpus and bounded snapshots.

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

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
import heapq
import inspect
import math
import sqlite3
import struct
import time
from typing import Any, Callable, Iterable

from .memory_atom import row_value
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
_MAX_DELTA_SYNC_ROWS = 2000
_SELECTION_CACHE_MAX_ENTRIES = 32


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
    for start_key, end_key in (("start_at", "end_at"), ("source_start_at", "source_end_at")):
        start_at = parse_iso_timestamp(metadata.get(start_key))
        end_at = parse_iso_timestamp(metadata.get(end_key))
        if start_at is not None or end_at is not None:
            start = start_at if start_at is not None else end_at
            end = end_at if end_at is not None else start_at
            if start is not None and end is not None:
                if end <= start:
                    end = start + 86400.0
                ranges.append((start, end))
    occurred_ts = parse_iso_timestamp(memory.occurred_at)
    if occurred_ts is None:
        occurred_ts = parse_iso_timestamp(memory.created_at)
    if occurred_ts is not None:
        ranges.append((occurred_ts, occurred_ts + 1.0))
    return tuple(ranges)


@dataclass(frozen=True, slots=True)
class VectorRef:
    memory_id: str
    text_hash: str
    updated_at: str
    memory_type: str = ""
    time_ranges: tuple[tuple[float, float], ...] = ()
    embedding_updated_at: str = ""


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
            + len(r.embedding_updated_at)
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


@dataclass(slots=True)
class CorpusEntry:
    """Cached metadata and validity window for one valid corpus record."""

    ref: VectorRef
    memory: MemoryRecord
    valid_from_ts: float | None
    valid_to_ts: float | None


@dataclass(frozen=True, slots=True)
class SelectionCacheEntry:
    """Cached per-authorization eligibility selection for a fixed corpus & ACL revision."""

    built_at: float
    valid_until: float
    selected_ids: tuple[str, ...]
    candidates_count: int
    unauthorized_count: int


@dataclass(slots=True)
class VectorCorpus:
    """Process-local shared vector corpus invariant across authorization keys."""

    corpus_key: tuple[str, int, bool, int]
    corpus_revision: int | None
    retrieval_revision: str
    last_change_seq: int
    batch_size: int
    entries: dict[str, CorpusEntry] = field(default_factory=dict)
    bad_status: dict[str, str] = field(default_factory=dict)
    vector_blocks: list[VectorBlock] = field(default_factory=list)
    vector_index: dict[str, tuple[int, int]] = field(default_factory=dict)
    vector_bytes: int = 0
    partial_evicted: bool = False
    eager_vectors: bool = False
    selection_cache: OrderedDict[tuple, SelectionCacheEntry] = field(default_factory=OrderedDict)

    def clone_for_update(self) -> "VectorCorpus":
        """Create a shallow working copy so aborted/cancelled updates stay atomic."""
        return VectorCorpus(
            corpus_key=self.corpus_key,
            corpus_revision=self.corpus_revision,
            retrieval_revision=self.retrieval_revision,
            last_change_seq=self.last_change_seq,
            batch_size=self.batch_size,
            entries=dict(self.entries),
            bad_status=dict(self.bad_status),
            vector_blocks=list(self.vector_blocks),
            vector_index=dict(self.vector_index),
            vector_bytes=self.vector_bytes,
            partial_evicted=self.partial_evicted,
            eager_vectors=self.eager_vectors,
            selection_cache=OrderedDict(self.selection_cache),
        )


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
    """Batch-normalize fixed-length float64 BLOBs into one contiguous numpy buffer."""
    count = len(blobs)
    if count == 0 or dimension <= 0:
        return [None] * count, ["embedding_invalid"] * count
    row_bytes = dimension * 8
    mat = np.empty((count, dimension), dtype="<f8")
    raw_view = mat.view(np.uint8).reshape(count, row_bytes)
    for idx, blob in enumerate(blobs):
        raw_view[idx] = np.frombuffer(blob, dtype=np.uint8)
    finite_mask = np.isfinite(mat).all(axis=1)
    scales = np.max(np.abs(mat), axis=1)
    valid_mask = finite_mask & (scales > 0.0)
    results: list[memoryview | None] = [None] * count
    errors: list[str] = ["embedding_invalid"] * count

    if valid_mask.all():
        mat /= scales[:, None]
        norms = np.sqrt(np.einsum("ij,ij->i", mat, mat))
        norm_valid = np.isfinite(norms) & (norms > 0.0)
        if norm_valid.all():
            mat /= norms[:, None]
            mv = memoryview(mat.tobytes())
            for idx in range(count):
                start = idx * row_bytes
                results[idx] = mv[start : start + row_bytes]
                errors[idx] = ""
            return results, errors
        keep = np.flatnonzero(norm_valid)
        if len(keep) == 0:
            return results, errors
        kept_mat = mat[keep]
        kept_mat /= norms[keep, None]
        mv = memoryview(kept_mat.astype("<f8", copy=False).tobytes())
        for out_idx, src_idx in enumerate(keep.tolist()):
            start = out_idx * row_bytes
            results[src_idx] = mv[start : start + row_bytes]
            errors[src_idx] = ""
        return results, errors

    valid_indices = np.flatnonzero(valid_mask)
    if len(valid_indices) == 0:
        return results, errors
    valid_mat = mat[valid_indices]
    valid_mat /= scales[valid_indices, None]
    norms = np.sqrt(np.einsum("ij,ij->i", valid_mat, valid_mat))
    norm_valid = np.isfinite(norms) & (norms > 0.0)
    if not norm_valid.all():
        keep = np.flatnonzero(norm_valid)
        if len(keep) == 0:
            return results, errors
        valid_indices = valid_indices[keep]
        valid_mat = valid_mat[keep]
        norms = norms[keep]
    valid_mat /= norms[:, None]
    mv = memoryview(valid_mat.astype("<f8", copy=False).tobytes())
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


def _entry_timestamps(memory: MemoryRecord) -> tuple[float | None, float | None]:
    metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
    raw_from = getattr(memory, "valid_from", "") or metadata.get("valid_from", "")
    raw_to = getattr(memory, "valid_to", "") or metadata.get("valid_to", "")
    return parse_iso_timestamp(raw_from), parse_iso_timestamp(raw_to)


def _boundary_from_timestamps(
    valid_from_ts: float | None,
    valid_to_ts: float | None,
    now: float,
) -> float:
    boundary = math.inf
    if valid_from_ts is not None and valid_from_ts > now:
        boundary = min(boundary, valid_from_ts)
    if valid_to_ts is not None and valid_to_ts > now:
        boundary = min(boundary, valid_to_ts)
    return boundary


def _entry_next_boundary(entry: CorpusEntry, now: float) -> float:
    return _boundary_from_timestamps(entry.valid_from_ts, entry.valid_to_ts, now)


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
               "e.text_hash AS embedding_text_hash, "
               "e.updated_at AS embedding_updated_at FROM memory_embeddings e "
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


ReusableRow = tuple[str, str, str, bytes, int, int]


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
    database write only re-normalizes rows whose ``text_hash``,
    ``updated_at``, or ``embedding_updated_at`` actually changed.  Stores
    zero-copy ``(text_hash, updated_at, embedding_updated_at, block.values,
    offset, row_bytes)`` references into already-cached ``VectorBlock.values``
    buffers.
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
                    ref.embedding_updated_at,
                    buf,
                    index * row_bytes,
                    row_bytes,
                )
    return reusable


def _collect_corpus_reusable_rows(
    corpus: VectorCorpus | None,
    dimension: int,
) -> dict[str, ReusableRow]:
    """Index retained normalized slices from an existing ``VectorCorpus``."""
    if corpus is None or not corpus.vector_blocks:
        return {}
    row_bytes = dimension * 8
    reusable: dict[str, ReusableRow] = {}
    for block in corpus.vector_blocks:
        if block.dimension != dimension or len(block.values) != len(block.refs) * row_bytes:
            continue
        buf = block.values
        for index, ref in enumerate(block.refs):
            reusable[ref.memory_id] = (
                ref.text_hash,
                ref.updated_at,
                ref.embedding_updated_at,
                buf,
                index * row_bytes,
                row_bytes,
            )
    return reusable


def _make_row_parser(store: Any) -> tuple[Callable[[Any], MemoryRecord], Callable[..., str]]:
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

    def parse_row(row: Any, expected_revision: str) -> MemoryRecord:
        if use_cached_parser:
            if supports_copy:
                return cached_parser(row, revision=expected_revision, copy=False)
            return cached_parser(row, revision=expected_revision)
        return MemoryRecord.from_row_light(row)

    def hash_memory(memory: MemoryRecord, max_chars: int, expected_revision: str) -> str:
        if use_cached_hasher:
            return cached_hasher(memory, max_chars=max_chars, revision=expected_revision)
        return memory_embedding_text_hash(memory, max_chars=max_chars)

    return parse_row, hash_memory


def _normalize_ref_payloads(
    conn: Any,
    provider_id: str,
    dimension: int,
    allowed: list[VectorRef],
    reusable_rows: dict[str, ReusableRow] | None,
    np: Any,
    check_cancelled: Callable[[], None],
    counts: dict[str, int],
) -> tuple[list[VectorRef], list[bytes | memoryview]]:
    """Fetch uncached vector BLOBs in batches and return normalized row buffers."""
    row_bytes = dimension * 8
    reused_slices: list[memoryview | None] = []
    missing_refs: list[VectorRef] = []
    if reusable_rows:
        for ref in allowed:
            cached_row = reusable_rows.get(ref.memory_id)
            if (
                cached_row is not None
                and cached_row[0] == ref.text_hash
                and cached_row[1] == ref.updated_at
                and cached_row[2] == ref.embedding_updated_at
            ):
                reused_slices.append(
                    memoryview(cached_row[3])[cached_row[4] : cached_row[4] + cached_row[5]]
                )
            else:
                reused_slices.append(None)
                missing_refs.append(ref)
    else:
        missing_refs = allowed

    payloads: dict[str, Any] = {}
    for offset in range(0, len(missing_refs), 900):
        check_cancelled()
        part = missing_refs[offset : offset + 900]
        placeholders = ",".join("?" for _ in part)
        payloads.update(
            dict(
                conn.execute(
                    f"SELECT memory_id, vector FROM memory_embeddings WHERE provider_id=? "
                    f"AND memory_id IN ({placeholders})",
                    [provider_id] + [r.memory_id for r in part],
                )
            )
        )

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

    refs: list[VectorRef] = []
    chunks: list[bytes | memoryview] = []
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
    return refs, chunks


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
    parse_row, hash_memory = _make_row_parser(store)
    np = _numpy()
    blocks: list[VectorBlock] = []
    admitted: set[str] = set()
    truncated = False
    retained = 0
    valid_until = math.inf
    fetch_batch = max(batch_size, 900) if (batch_size >= 8 and not restrict_ids) else batch_size
    for rows in _row_batches(conn, provider_id, where, fetch_batch, restrict_ids):
        check_cancelled()
        allowed: list[VectorRef] = []
        for row in rows:
            counts["embedding_scanned_rows"] += 1
            memory = parse_row(row, expected_revision)
            # Include not-yet-active entries so a clock boundary can
            # admit them without requiring a database write.
            valid_until = min(valid_until, _next_boundary(memory, selection_time))
            if not eligible(memory):
                counts["embedding_unauthorized_or_inactive"] += 1
                continue
            counts["embedding_candidates"] += 1
            text_hash = hash_memory(memory, max_text_chars, expected_revision)
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
                    str(row_value(row, "embedding_updated_at", "") or ""),
                )
            )
        refs, chunks = _normalize_ref_payloads(
            conn,
            provider_id,
            dimension,
            allowed,
            reusable_rows,
            np,
            check_cancelled,
            counts,
        )
        if not refs:
            continue
        for start in range(0, len(refs), batch_size):
            end = start + batch_size
            part_refs = refs[start:end]
            part_chunks = chunks[start:end]
            for ref in part_refs:
                admitted.add(ref.memory_id)
            block = VectorBlock(tuple(part_refs), b"".join(part_chunks), dimension)
            accept(block)
            blocks, retained, evicted = _retain_blocks(blocks, budget, block=block, retained=retained)
            if evicted:
                truncated = True
    return blocks, valid_until, truncated, frozenset(admitted), retained


def _cache_sync_signature(store: Any) -> tuple[int, dict[tuple, int], int]:
    search_cache = getattr(store, "_vector_search_cache", None)
    if not isinstance(search_cache, dict):
        return (0, {}, 0)
    custom_parser = store.__dict__.get("_cached_from_row_light") if hasattr(store, "__dict__") else None
    return (
        id(search_cache),
        {k: id(v) for k, v in search_cache.items()},
        id(custom_parser) if custom_parser is not None else 0,
    )


def _ensure_store_vector_caches(store: Any) -> tuple[dict[tuple, VectorSnapshot], dict[tuple, VectorCorpus]]:
    search_cache = getattr(store, "_vector_search_cache", None)
    if not isinstance(search_cache, dict):
        search_cache = {}
        store._vector_search_cache = search_cache
    corpus_cache = getattr(store, "_vector_corpus_cache", None)
    if not isinstance(corpus_cache, dict):
        corpus_cache = {}
        store._vector_corpus_cache = corpus_cache
    sig = _cache_sync_signature(store)
    prev_sig = getattr(store, "_vector_cache_sync_sig", None)
    if prev_sig is not None and sig != prev_sig:
        # Detect external .clear(), dict replacement, snapshot mutation, or parser override.
        if sig[0] != prev_sig[0] or sig[2] != prev_sig[2]:
            corpus_cache.clear()
        elif not search_cache and prev_sig[1]:
            corpus_cache.clear()
        elif any(prev_sig[1].get(k) != v for k, v in sig[1].items() if k in prev_sig[1]):
            corpus_cache.clear()
    return search_cache, corpus_cache


def _record_cache_sync_signature(store: Any) -> None:
    store._vector_cache_sync_sig = _cache_sync_signature(store)


def _read_corpus_revisions(conn: Any) -> tuple[str, int | None, int | None, int, int, int]:
    """Read retrieval, corpus, acl revisions and delta bounds inside a read transaction."""
    row = conn.execute("SELECT revision FROM retrieval_revision WHERE singleton=1").fetchone()
    retrieval_rev = str(row[0]) if row else "0"
    corpus_rev: int | None = None
    acl_rev: int | None = None
    min_seq = 0
    max_seq = 0
    change_count = 0
    try:
        c_row = conn.execute("SELECT revision FROM vector_corpus_revision WHERE singleton=1").fetchone()
        if c_row is not None:
            corpus_rev = int(c_row[0] or 0)
        a_row = conn.execute("SELECT revision FROM acl_revision WHERE singleton=1").fetchone()
        if a_row is not None:
            acl_rev = int(a_row[0] or 0)
        bounds = conn.execute(
            "SELECT COALESCE(MIN(seq), 0), COALESCE(MAX(seq), 0), COUNT(*) FROM vector_corpus_changes"
        ).fetchone()
        if bounds is not None:
            min_seq = int(bounds[0] or 0)
            max_seq = int(bounds[1] or 0)
            change_count = int(bounds[2] or 0)
    except sqlite3.OperationalError:
        # Legacy read_only=True databases without Perf4 triggers safely fall back.
        corpus_rev = None
        acl_rev = None
    return retrieval_rev, corpus_rev, acl_rev, min_seq, max_seq, change_count


def _delta_changed_ids(
    conn: Any,
    corpus: VectorCorpus,
    current_corpus_rev: int | None,
    min_seq: int,
    max_seq: int,
    change_count: int,
) -> tuple[tuple[str, ...], int] | None:
    """Return ``(changed_ids, new_last_seq)``, or ``None`` if full rebuild is required."""
    if corpus.corpus_revision is None or current_corpus_rev is None:
        return None
    if current_corpus_rev < corpus.corpus_revision:
        return None
    if current_corpus_rev == corpus.corpus_revision:
        return (), corpus.last_change_seq
    if change_count == 0 or max_seq <= corpus.last_change_seq:
        return None
    if min_seq > corpus.last_change_seq + 1:
        return None
    rows = conn.execute(
        "SELECT seq, memory_id FROM vector_corpus_changes WHERE seq > ? ORDER BY seq LIMIT ?",
        (corpus.last_change_seq, _MAX_DELTA_SYNC_ROWS + 1),
    ).fetchall()
    if not rows or len(rows) > _MAX_DELTA_SYNC_ROWS:
        return None
    ids = tuple(dict.fromkeys(str(row[1]) for row in rows if row[1]))
    new_last_seq = int(rows[-1][0])
    return ids, new_last_seq


def _rebuild_vector_index(corpus: VectorCorpus) -> None:
    index: dict[str, tuple[int, int]] = {}
    total_bytes = 0
    for blk_idx, block in enumerate(corpus.vector_blocks):
        total_bytes += block.byte_size
        for row_idx, ref in enumerate(block.refs):
            index[ref.memory_id] = (blk_idx, row_idx)
    corpus.vector_index = index
    corpus.vector_bytes = total_bytes


def _append_corpus_blocks(
    corpus: VectorCorpus,
    refs: list[VectorRef],
    chunks: list[bytes | memoryview],
    dimension: int,
    budget: int,
    on_block: Callable[[VectorBlock], None] | None = None,
) -> None:
    """Append newly normalized vector blocks into ``corpus`` respecting ``budget``."""
    if not refs:
        return
    step = max(1, corpus.batch_size)
    for start in range(0, len(refs), step):
        part_refs = tuple(refs[start : start + step])
        part_chunks = chunks[start : start + step]
        block = VectorBlock(part_refs, b"".join(part_chunks), dimension)
        if on_block is not None:
            on_block(block)
        corpus.vector_blocks, corpus.vector_bytes, evicted = _retain_blocks(
            corpus.vector_blocks,
            budget,
            block=block,
            retained=corpus.vector_bytes,
        )
        if evicted:
            corpus.partial_evicted = True
    _rebuild_vector_index(corpus)


def _trim_corpus_to_budget(corpus: VectorCorpus, budget: int) -> bool:
    if not corpus.vector_blocks or corpus.vector_bytes <= budget:
        return False
    corpus.vector_blocks, corpus.vector_bytes, evicted = _retain_blocks(
        corpus.vector_blocks,
        budget,
        retained=corpus.vector_bytes,
    )
    if evicted:
        corpus.partial_evicted = True
        _rebuild_vector_index(corpus)
        return True
    return False


def _remove_ids_from_corpus(corpus: VectorCorpus, remove_ids: set[str], dimension: int) -> None:
    """Remove deleted or changed IDs from ``corpus`` metadata and vector blocks."""
    for mid in remove_ids:
        corpus.entries.pop(mid, None)
        corpus.bad_status.pop(mid, None)
    if not any(mid in corpus.vector_index for mid in remove_ids):
        return
    updated_blocks: list[VectorBlock] = []
    row_bytes = dimension * 8
    np = _numpy()
    for block in corpus.vector_blocks:
        keep_indices = [idx for idx, ref in enumerate(block.refs) if ref.memory_id not in remove_ids]
        if not keep_indices:
            continue
        if len(keep_indices) == len(block.refs):
            updated_blocks.append(block)
            continue
        kept_refs = tuple(block.refs[idx] for idx in keep_indices)
        if np is not None:
            mat = np.frombuffer(block.values, dtype="<f8").reshape(len(block.refs), dimension)
            kept_bytes = mat[keep_indices].tobytes()
        else:
            mv = memoryview(block.values)
            kept_bytes = b"".join(mv[idx * row_bytes : (idx + 1) * row_bytes] for idx in keep_indices)
        updated_blocks.append(VectorBlock(kept_refs, kept_bytes, dimension))
    corpus.vector_blocks = updated_blocks
    _rebuild_vector_index(corpus)


def _publish_corpus(
    corpus_cache: dict[tuple, VectorCorpus],
    corpus: VectorCorpus,
    budget: int,
) -> None:
    corpus_cache.pop(corpus.corpus_key, None)
    while corpus_cache and (
        len(corpus_cache) >= CACHE_ENTRIES
        or sum(c.vector_bytes for c in corpus_cache.values()) + corpus.vector_bytes > budget
    ):
        corpus_cache.pop(next(iter(corpus_cache)))
    corpus_cache[corpus.corpus_key] = corpus


def _populate_corpus_from_rows(
    store: Any,
    conn: Any,
    corpus: VectorCorpus,
    provider_id: str,
    dimension: int,
    max_text_chars: int,
    where: str,
    restrict_ids: tuple[str, ...],
    eligible: Callable[[MemoryRecord], bool] | None,
    reusable_rows: dict[str, ReusableRow] | None,
    budget: int,
    expected_revision: str,
    check_cancelled: Callable[[], None],
    *,
    materialize_all: bool,
    selection_time: float = 0.0,
    on_block: Callable[[VectorBlock], None] | None = None,
) -> tuple[set[str], set[str], dict[str, int], float]:
    """Scan ``memories JOIN memory_embeddings`` and populate ``corpus`` entries & vectors."""
    parse_row, hash_memory = _make_row_parser(store)
    np = _numpy()
    fetch_batch = max(corpus.batch_size, 900) if (corpus.batch_size >= 8 and not restrict_ids) else corpus.batch_size
    eligible_ids: set[str] = set()
    freshly_normalized_ids: set[str] = set()
    valid_until = math.inf
    counts = {
        "embedding_candidates": 0,
        "embedding_scanned_rows": 0,
        "embedding_stale": 0,
        "embedding_dim_mismatch": 0,
        "embedding_invalid": 0,
        "embedding_unauthorized_or_inactive": 0,
        "embedding_reused_rows": 0,
    }
    for rows in _row_batches(conn, provider_id, where, fetch_batch, restrict_ids):
        check_cancelled()
        to_normalize: list[VectorRef] = []
        for row in rows:
            counts["embedding_scanned_rows"] += 1
            memory = parse_row(row, expected_revision)
            mid = memory.id
            vf_ts, vt_ts = _entry_timestamps(memory)
            valid_until = min(valid_until, _boundary_from_timestamps(vf_ts, vt_ts, selection_time))
            text_hash = hash_memory(memory, max_text_chars, expected_revision)
            if not row["embedding_text_hash"] or row["embedding_text_hash"] != text_hash:
                corpus.bad_status[mid] = "stale"
                if eligible is None or eligible(memory):
                    counts["embedding_candidates"] += 1
                    counts["embedding_stale"] += 1
                else:
                    counts["embedding_unauthorized_or_inactive"] += 1
                continue
            if row["embedding_dimension"] != dimension:
                corpus.bad_status[mid] = "dim_mismatch"
                if eligible is None or eligible(memory):
                    counts["embedding_candidates"] += 1
                    counts["embedding_dim_mismatch"] += 1
                else:
                    counts["embedding_unauthorized_or_inactive"] += 1
                continue
            ref = VectorRef(
                mid,
                text_hash,
                memory.updated_at,
                memory.memory_type,
                memory_time_ranges(memory),
                str(row_value(row, "embedding_updated_at", "") or ""),
            )
            corpus.entries[mid] = CorpusEntry(ref=ref, memory=memory, valid_from_ts=vf_ts, valid_to_ts=vt_ts)
            if materialize_all or (eligible is not None and eligible(memory)):
                counts["embedding_candidates"] += 1
                to_normalize.append(ref)
            else:
                counts["embedding_unauthorized_or_inactive"] += 1
        if to_normalize:
            norm_counts = {"embedding_invalid": 0, "embedding_dim_mismatch": 0, "embedding_reused_rows": 0}
            refs, chunks = _normalize_ref_payloads(
                conn,
                provider_id,
                dimension,
                to_normalize,
                reusable_rows,
                np,
                check_cancelled,
                norm_counts,
            )
            counts["embedding_reused_rows"] += norm_counts["embedding_reused_rows"]
            counts["embedding_invalid"] += norm_counts["embedding_invalid"]
            counts["embedding_dim_mismatch"] += norm_counts["embedding_dim_mismatch"]
            valid_set = {r.memory_id for r in refs}
            eligible_ids.update(valid_set)
            for ref in to_normalize:
                if ref.memory_id not in valid_set:
                    corpus.entries.pop(ref.memory_id, None)
                    corpus.bad_status[ref.memory_id] = "invalid"
                elif not reusable_rows or ref.memory_id not in reusable_rows:
                    freshly_normalized_ids.add(ref.memory_id)
                else:
                    cached_row = reusable_rows[ref.memory_id]
                    if (
                        cached_row[0] != ref.text_hash
                        or cached_row[1] != ref.updated_at
                        or cached_row[2] != ref.embedding_updated_at
                    ):
                        freshly_normalized_ids.add(ref.memory_id)
            _append_corpus_blocks(corpus, refs, chunks, dimension, budget, on_block=on_block)
    return eligible_ids, freshly_normalized_ids, counts, valid_until


def _corpus_base_counts(corpus: VectorCorpus) -> dict[str, int]:
    stale = sum(1 for v in corpus.bad_status.values() if v == "stale")
    dim_mismatch = sum(1 for v in corpus.bad_status.values() if v == "dim_mismatch")
    invalid = sum(1 for v in corpus.bad_status.values() if v == "invalid")
    return {
        "embedding_scanned_rows": len(corpus.entries) + len(corpus.bad_status),
        "embedding_stale": stale,
        "embedding_dim_mismatch": dim_mismatch,
        "embedding_invalid": invalid,
    }


def _select_corpus_entries(
    corpus: VectorCorpus,
    authorization_key: tuple,
    acl_rev: int | None,
    retrieval_rev: str,
    eligible: Callable[[MemoryRecord], bool],
    selection_time: float,
) -> SelectionCacheEntry:
    corpus_rev_token = (
        corpus.corpus_revision
        if corpus.corpus_revision is not None
        else corpus.retrieval_revision
    )
    acl_rev_token = acl_rev if acl_rev is not None else retrieval_rev
    sel_key = (authorization_key, corpus_rev_token, acl_rev_token)
    cached = corpus.selection_cache.get(sel_key)
    if cached is not None and cached.built_at <= selection_time < cached.valid_until:
        corpus.selection_cache.move_to_end(sel_key)
        return cached

    selected: list[str] = []
    valid_until = math.inf
    unauthorized = 0
    for mid, entry in corpus.entries.items():
        valid_until = min(valid_until, _entry_next_boundary(entry, selection_time))
        if eligible(entry.memory):
            selected.append(mid)
        else:
            unauthorized += 1

    entry_obj = SelectionCacheEntry(
        built_at=selection_time,
        valid_until=valid_until,
        selected_ids=tuple(selected),
        candidates_count=len(selected),
        unauthorized_count=unauthorized,
    )
    corpus.selection_cache[sel_key] = entry_obj
    corpus.selection_cache.move_to_end(sel_key)
    while len(corpus.selection_cache) > _SELECTION_CACHE_MAX_ENTRIES:
        corpus.selection_cache.popitem(last=False)
    return entry_obj


def _build_snapshot_blocks_from_corpus(
    corpus: VectorCorpus,
    selected_ids: tuple[str, ...],
    dimension: int,
    budget: int,
    accept: Callable[[VectorBlock], None],
    *,
    step_size: int | None = None,
) -> tuple[list[VectorBlock], bool, frozenset[str], int]:
    """Slice contiguous normalized rows from ``corpus`` into snapshot ``VectorBlock``s."""
    np = _numpy()
    row_bytes = dimension * 8
    selected_set = set(selected_ids)
    blocks: list[VectorBlock] = []
    admitted: set[str] = set()
    truncated = False
    retained = 0
    step = max(1, step_size if step_size is not None else corpus.batch_size)

    # Group selected IDs by corpus block to reuse whole blocks zero-copy or
    # extract contiguous slices via numpy without touching SQLite.
    by_block: dict[int, list[int]] = {}
    for mid in selected_ids:
        pos = corpus.vector_index.get(mid)
        if pos is None:
            continue
        blk_idx, row_idx = pos
        by_block.setdefault(blk_idx, []).append(row_idx)

    pending_refs: list[VectorRef] = []
    pending_slices: list[bytes | memoryview] = []

    def emit_block(block: VectorBlock) -> None:
        nonlocal blocks, retained, truncated
        for ref in block.refs:
            admitted.add(ref.memory_id)
        accept(block)
        blocks, retained, evicted = _retain_blocks(blocks, budget, block=block, retained=retained)
        if evicted:
            truncated = True

    def flush_pending() -> None:
        nonlocal pending_refs, pending_slices
        if not pending_refs:
            return
        while pending_refs:
            take = min(step, len(pending_refs))
            chunk_refs = tuple(pending_refs[:take])
            chunk_slices = pending_slices[:take]
            del pending_refs[:take]
            del pending_slices[:take]
            emit_block(VectorBlock(chunk_refs, b"".join(chunk_slices), dimension))

    for blk_idx, cblock in enumerate(corpus.vector_blocks):
        local_rows = by_block.get(blk_idx)
        if not local_rows:
            continue
        if len(local_rows) == len(cblock.refs) and len(cblock.refs) <= step and not pending_refs:
            # Zero-copy reuse when every row in the corpus block is eligible.
            if all(ref.memory_id in selected_set for ref in cblock.refs):
                emit_block(cblock)
                continue
        if np is not None:
            mat = np.frombuffer(cblock.values, dtype="<f8").reshape(len(cblock.refs), dimension)
            for start in range(0, len(local_rows), step):
                part = local_rows[start : start + step]
                part_refs = [cblock.refs[idx] for idx in part]
                part_bytes = mat[part].tobytes()
                if not pending_refs and len(part_refs) == step:
                    emit_block(VectorBlock(tuple(part_refs), part_bytes, dimension))
                else:
                    pending_refs.extend(part_refs)
                    pending_slices.append(part_bytes)
                    if len(pending_refs) >= step:
                        flush_pending()
        else:
            mv = memoryview(cblock.values)
            for idx in local_rows:
                pending_refs.append(cblock.refs[idx])
                pending_slices.append(mv[idx * row_bytes : (idx + 1) * row_bytes])
                if len(pending_refs) >= step:
                    flush_pending()
    flush_pending()
    return blocks, truncated, frozenset(admitted), retained


def prewarm_vector_corpus_sync(
    store: Any,
    *,
    provider_id: str = "",
    dimension: int = 0,
    include_pending: bool = False,
    batch_size: int = 1200,
    max_text_chars: int = 1200,
    cancelled: Any = None,
) -> dict[str, Any]:
    """Warm ``_record_light_cache`` and shared ``VectorCorpus`` without embedding API calls."""
    started = time.perf_counter()

    def check_cancelled() -> None:
        if (cancelled is not None and cancelled.is_set()) or store._closing or store._closed:
            raise RuntimeError("embedding_warmup_cancelled")

    with store._vector_search_lock:
        check_cancelled()
        search_cache, corpus_cache = _ensure_store_vector_caches(store)
        conn, lock = store._vector_read_connection()
        with lock:
            conn.execute("BEGIN")
            try:
                resolved_provider = clean_text(provider_id, 160)
                resolved_dim = max(0, int(dimension or 0))
                if not resolved_provider:
                    row = conn.execute(
                        "SELECT provider_id, dimension FROM memory_embeddings "
                        "GROUP BY provider_id, dimension ORDER BY COUNT(*) DESC LIMIT 1"
                    ).fetchone()
                    if row is None:
                        return {"warmed": False, "reason": "no_embeddings"}
                    resolved_provider = clean_text(row[0], 160)
                    resolved_dim = max(0, int(row[1] or 0))
                elif resolved_dim <= 0:
                    row = conn.execute(
                        "SELECT dimension FROM memory_embeddings WHERE provider_id=? "
                        "GROUP BY dimension ORDER BY COUNT(*) DESC LIMIT 1",
                        (resolved_provider,),
                    ).fetchone()
                    if row is None:
                        return {"warmed": False, "reason": "no_embeddings"}
                    resolved_dim = max(0, int(row[0] or 0))
                if not resolved_provider or resolved_dim <= 0:
                    return {"warmed": False, "reason": "invalid_embedding_shape"}

                safe_batch = min(max(1, batch_size), max(1, BLOCK_BYTES // (8 * resolved_dim)))
                budget = cache_budget_bytes(store)
                corpus_key = (resolved_provider, resolved_dim, bool(include_pending), max_text_chars)
                rev, corpus_rev, _acl_rev, min_seq, max_seq, chg_count = _read_corpus_revisions(conn)
                existing = corpus_cache.get(corpus_key)
                if existing is not None and not existing.partial_evicted and existing.eager_vectors:
                    up_to_date = (
                        (corpus_rev is not None and existing.corpus_revision == corpus_rev)
                        or (corpus_rev is None and existing.retrieval_revision == rev)
                    )
                    if up_to_date and len(existing.vector_index) == len(existing.entries):
                        _trim_corpus_to_budget(existing, budget)
                        return {
                            "warmed": True,
                            "reused": True,
                            "provider_id": resolved_provider,
                            "dimension": resolved_dim,
                            "rows": len(existing.entries),
                            "partial": existing.partial_evicted,
                        }

                reusable = _collect_corpus_reusable_rows(existing, resolved_dim)
                if search_cache:
                    snap_reusable = _collect_reusable_rows(
                        search_cache,
                        revision=None,
                        provider_id=resolved_provider,
                        dimension=resolved_dim,
                        max_text_chars=max_text_chars,
                    )
                    if snap_reusable:
                        snap_reusable.update(reusable)
                        reusable = snap_reusable

                corpus = VectorCorpus(
                    corpus_key=corpus_key,
                    corpus_revision=corpus_rev,
                    retrieval_revision=rev,
                    last_change_seq=max_seq,
                    batch_size=safe_batch,
                    eager_vectors=True,
                )
                where = _candidate_where(store, include_pending)
                _populate_corpus_from_rows(
                    store,
                    conn,
                    corpus,
                    resolved_provider,
                    resolved_dim,
                    max_text_chars,
                    where,
                    (),
                    None,
                    reusable or None,
                    budget,
                    rev,
                    check_cancelled,
                    materialize_all=True,
                )
            finally:
                conn.rollback()

        check_cancelled()
        _publish_corpus(corpus_cache, corpus, budget)
        _record_cache_sync_signature(store)
        return {
            "warmed": True,
            "reused": False,
            "provider_id": resolved_provider,
            "dimension": resolved_dim,
            "rows": len(corpus.entries),
            "blocks": len(corpus.vector_blocks),
            "partial": corpus.partial_evicted,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def _search_via_warm_corpus(
    store: Any,
    conn: Any,
    corpus: VectorCorpus,
    *,
    provider_id: str,
    dimension: int,
    batch_size: int,
    max_text_chars: int,
    include_pending: bool,
    authorization_key: tuple,
    revision: str,
    corpus_rev: int | None,
    acl_rev: int | None,
    min_seq: int,
    max_seq: int,
    chg_count: int,
    eligible: Callable[[MemoryRecord], bool],
    selection_time: float,
    budget: int,
    check_cancelled: Callable[[], None],
    accept: Callable[[VectorBlock], None],
    get_reusable: Callable[[], dict[str, ReusableRow] | None],
    counts: dict[str, int],
) -> tuple[VectorCorpus, VectorSnapshot, int, int, float] | None:
    """Incrementally sync ``corpus`` and build an authorized snapshot, or return ``None``."""
    if corpus.partial_evicted:
        return None
    delta = _delta_changed_ids(conn, corpus, corpus_rev, min_seq, max_seq, chg_count)
    if delta is None:
        return None
    changed_ids, new_last_seq = delta
    working = corpus.clone_for_update()
    where = _candidate_where(store, include_pending)
    freshly_normalized_ids: set[str] = set()
    delta_rows = len(changed_ids)
    if changed_ids:
        _remove_ids_from_corpus(working, set(changed_ids), dimension)
        _elig, freshly_normalized_ids, _pop_counts, _vu = _populate_corpus_from_rows(
            store,
            conn,
            working,
            provider_id,
            dimension,
            max_text_chars,
            where,
            changed_ids,
            None if working.eager_vectors else eligible,
            None,
            budget,
            revision,
            check_cancelled,
            materialize_all=working.eager_vectors,
            selection_time=selection_time,
        )
        working.selection_cache.clear()
    working.corpus_revision = corpus_rev
    working.last_change_seq = new_last_seq
    working.retrieval_revision = revision
    if working.partial_evicted:
        return None

    sel = _select_corpus_entries(
        working,
        authorization_key,
        acl_rev,
        revision,
        eligible,
        selection_time,
    )
    valid_until = sel.valid_until
    counts.update(_corpus_base_counts(working))
    counts["embedding_candidates"] = sel.candidates_count
    counts["embedding_unauthorized_or_inactive"] = sel.unauthorized_count

    missing_vec_refs = [
        working.entries[mid].ref
        for mid in sel.selected_ids
        if mid not in working.vector_index
    ]
    if missing_vec_refs:
        norm_counts = {
            "embedding_invalid": 0,
            "embedding_dim_mismatch": 0,
            "embedding_reused_rows": 0,
        }
        new_refs, new_chunks = _normalize_ref_payloads(
            conn,
            provider_id,
            dimension,
            missing_vec_refs,
            get_reusable(),
            _numpy(),
            check_cancelled,
            norm_counts,
        )
        valid_new_ids = {r.memory_id for r in new_refs}
        newly_invalid = 0
        for ref in missing_vec_refs:
            if ref.memory_id not in valid_new_ids:
                working.entries.pop(ref.memory_id, None)
                working.bad_status[ref.memory_id] = "invalid"
                newly_invalid += 1
        counts["embedding_invalid"] += norm_counts["embedding_invalid"]
        counts["embedding_dim_mismatch"] += norm_counts["embedding_dim_mismatch"]
        if newly_invalid:
            working.selection_cache.clear()
            sel = _select_corpus_entries(
                working,
                authorization_key,
                acl_rev,
                revision,
                eligible,
                selection_time,
            )
            counts["embedding_candidates"] = sel.candidates_count
        _append_corpus_blocks(working, new_refs, new_chunks, dimension, budget)
        already_cached = sum(
            1
            for mid in sel.selected_ids
            if mid not in freshly_normalized_ids
            and mid in working.vector_index
            and mid not in valid_new_ids
        )
        reused_rows = already_cached + norm_counts["embedding_reused_rows"]
    else:
        reused_rows = sum(
            1
            for mid in sel.selected_ids
            if mid not in freshly_normalized_ids
        )

    if working.partial_evicted:
        return None

    blocks, truncated, admitted, retained = _build_snapshot_blocks_from_corpus(
        working,
        sel.selected_ids,
        dimension,
        budget,
        accept,
        step_size=batch_size,
    )
    publish = VectorSnapshot(
        revision,
        valid_until,
        tuple(blocks),
        tuple(counts.items()),
        retained,
        complete=not truncated,
        candidate_ids=None if not truncated else admitted,
    )
    return working, publish, delta_rows, reused_rows, valid_until


def _build_corpus_cold_snapshot(
    store: Any,
    conn: Any,
    corpus: VectorCorpus | None,
    *,
    corpus_key: tuple[str, int, bool, int],
    provider_id: str,
    dimension: int,
    batch_size: int,
    max_text_chars: int,
    include_pending: bool,
    authorization_key: tuple,
    expected_revision: str,
    revision: str,
    corpus_rev: int | None,
    acl_rev: int | None,
    max_seq: int,
    eligible: Callable[[MemoryRecord], bool],
    selection_time: float,
    budget: int,
    check_cancelled: Callable[[], None],
    accept: Callable[[VectorBlock], None],
    reusable_rows: dict[str, ReusableRow] | None,
    counts: dict[str, int],
) -> tuple[VectorCorpus | None, VectorSnapshot, int, float]:
    """Perform a full corpus scan and build both ``VectorSnapshot`` and ``VectorCorpus``."""
    where = _candidate_where(store, include_pending)
    if corpus is None or not corpus.partial_evicted:
        working = VectorCorpus(
            corpus_key=corpus_key,
            corpus_revision=corpus_rev,
            retrieval_revision=revision,
            last_change_seq=max_seq,
            batch_size=batch_size,
            eager_vectors=bool(corpus.eager_vectors) if corpus is not None else False,
        )
        eligible_ids, _fresh, pop_counts, valid_until = _populate_corpus_from_rows(
            store,
            conn,
            working,
            provider_id,
            dimension,
            max_text_chars,
            where,
            (),
            eligible,
            reusable_rows,
            budget,
            revision,
            check_cancelled,
            materialize_all=False,
            selection_time=selection_time,
            on_block=accept,
        )
        counts.update(
            {
                "embedding_candidates": pop_counts["embedding_candidates"],
                "embedding_scanned_rows": pop_counts["embedding_scanned_rows"],
                "embedding_stale": pop_counts["embedding_stale"],
                "embedding_dim_mismatch": pop_counts["embedding_dim_mismatch"],
                "embedding_invalid": pop_counts["embedding_invalid"],
                "embedding_unauthorized_or_inactive": pop_counts["embedding_unauthorized_or_inactive"],
            }
        )
        reused_rows = pop_counts["embedding_reused_rows"]
        ordered_selected = tuple(mid for mid in working.entries if mid in eligible_ids)
        blocks = tuple(working.vector_blocks)
        retained = working.vector_bytes
        truncated = working.partial_evicted
        admitted = frozenset(eligible_ids)
        publish = VectorSnapshot(
            revision,
            valid_until,
            blocks,
            tuple(counts.items()),
            retained,
            complete=not truncated,
            candidate_ids=None if not truncated else admitted,
        )
        if not working.partial_evicted:
            working.selection_cache[
                (
                    authorization_key,
                    working.corpus_revision if working.corpus_revision is not None else working.retrieval_revision,
                    acl_rev if acl_rev is not None else revision,
                )
            ] = SelectionCacheEntry(
                built_at=selection_time,
                valid_until=valid_until,
                selected_ids=ordered_selected,
                candidates_count=len(ordered_selected),
                unauthorized_count=counts["embedding_unauthorized_or_inactive"],
            )
        return working, publish, reused_rows, valid_until

    blocks, valid_until, truncated, admitted, retained = _build_blocks(
        store,
        conn,
        provider_id,
        dimension,
        batch_size,
        max_text_chars,
        eligible,
        selection_time,
        counts,
        check_cancelled,
        accept,
        budget,
        where,
        reusable_rows=reusable_rows,
        expected_revision=expected_revision,
    )
    reused_rows = counts.pop("embedding_reused_rows", 0)
    publish = VectorSnapshot(
        revision,
        valid_until,
        tuple(blocks),
        tuple(counts.items()),
        retained,
        complete=not truncated,
        candidate_ids=None if not truncated else admitted,
    )
    return None, publish, reused_rows, valid_until


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
    corpus_key = (provider_id, dimension, bool(include_pending), max_text_chars)
    budget = cache_budget_bytes(store)
    excluded_types = frozenset(excluded_memory_types) if excluded_memory_types else frozenset()
    selected: list[tuple[float, VectorRef]] = []
    counts = {
        "embedding_candidates": 0,
        "embedding_scanned_rows": 0,
        "embedding_stale": 0,
        "embedding_dim_mismatch": 0,
        "embedding_invalid": 0,
        "embedding_unauthorized_or_inactive": 0,
    }

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
        search_cache, corpus_cache = _ensure_store_vector_caches(store)
        conn, lock = store._vector_read_connection()
        with lock:
            conn.execute("BEGIN")
            reusable: dict[str, ReusableRow] | None = None
            reusable_built = False
            evicted_snapshots: dict[tuple, VectorSnapshot] = {}
            corpus_to_publish: VectorCorpus | None = None
            corpus_hit = False
            corpus_delta_rows = 0
            corpus_full_scan = False
            try:
                revision, corpus_rev, acl_rev, min_seq, max_seq, chg_count = _read_corpus_revisions(conn)
                if revision != expected_revision:
                    raise VectorSnapshotChanged("embedding_revision_changed")
                cached = search_cache.get(key)
                cache_hit = (
                    cached is not None
                    and cached.revision == revision
                    and cached.valid_until > selection_time
                )
                corpus = corpus_cache.get(corpus_key)
                if corpus is not None:
                    _trim_corpus_to_budget(corpus, budget)

                def get_reusable() -> dict[str, ReusableRow] | None:
                    nonlocal reusable, reusable_built
                    if reusable_built:
                        return reusable
                    reusable_built = True
                    combined_snapshots = (
                        {**evicted_snapshots, **search_cache}
                        if evicted_snapshots
                        else search_cache
                    )
                    collected = _collect_reusable_rows(
                        combined_snapshots,
                        revision=None,
                        provider_id=provider_id,
                        dimension=dimension,
                        max_text_chars=max_text_chars,
                        exclude_key=key if cache_hit else None,
                    )
                    if corpus is not None and corpus.vector_blocks:
                        corpus_reusable = _collect_corpus_reusable_rows(corpus, dimension)
                        if collected:
                            corpus_reusable.update(collected)
                        collected = corpus_reusable
                    reusable = collected
                    return reusable

                for cached_key, value in list(search_cache.items()):
                    if value.revision != revision or value.valid_until <= selection_time:
                        evicted_snapshots[cached_key] = value
                        del search_cache[cached_key]
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
                        missing = tuple(sorted(
                            (snapshot.candidate_ids or frozenset()) - snapshot.retained_ids
                        ))
                        if missing:
                            scratch = {name: 0 for name in counts}
                            _blocks, _until, _truncated, admitted, _retained = _build_blocks(
                                store, conn, provider_id, dimension, batch_size, max_text_chars,
                                eligible, selection_time, scratch, check_cancelled, accept, budget,
                                _candidate_where(store, include_pending), missing,
                                reusable_rows=get_reusable(),
                                expected_revision=expected_revision,
                            )
                            reread_rows = len(admitted)
                            reused_rows = scratch.pop("embedding_reused_rows", 0)
                else:
                    warm_res = (
                        _search_via_warm_corpus(
                            store,
                            conn,
                            corpus,
                            provider_id=provider_id,
                            dimension=dimension,
                            batch_size=batch_size,
                            max_text_chars=max_text_chars,
                            include_pending=include_pending,
                            authorization_key=authorization_key,
                            revision=revision,
                            corpus_rev=corpus_rev,
                            acl_rev=acl_rev,
                            min_seq=min_seq,
                            max_seq=max_seq,
                            chg_count=chg_count,
                            eligible=eligible,
                            selection_time=selection_time,
                            budget=budget,
                            check_cancelled=check_cancelled,
                            accept=accept,
                            get_reusable=get_reusable,
                            counts=counts,
                        )
                        if corpus is not None
                        else None
                    )
                    if warm_res is not None:
                        corpus_to_publish, publish, corpus_delta_rows, reused_rows, valid_until = warm_res
                        corpus_hit = True
                    else:
                        corpus_full_scan = True
                        corpus_delta_rows = 0
                        selected.clear()
                        corpus_to_publish, publish, reused_rows, valid_until = _build_corpus_cold_snapshot(
                            store,
                            conn,
                            corpus,
                            corpus_key=corpus_key,
                            provider_id=provider_id,
                            dimension=dimension,
                            batch_size=batch_size,
                            max_text_chars=max_text_chars,
                            include_pending=include_pending,
                            authorization_key=authorization_key,
                            expected_revision=expected_revision,
                            revision=revision,
                            corpus_rev=corpus_rev,
                            acl_rev=acl_rev,
                            max_seq=max_seq,
                            eligible=eligible,
                            selection_time=selection_time,
                            budget=budget,
                            check_cancelled=check_cancelled,
                            accept=accept,
                            reusable_rows=get_reusable(),
                            counts=counts,
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
                evicted_snapshots.clear()
                conn.rollback()
        check_cancelled()
        if store._memory_revision_sync() != expected_revision or time.time() >= valid_until:
            raise VectorSnapshotChanged("embedding_revision_or_clock_changed")
        if corpus_to_publish is not None:
            _publish_corpus(corpus_cache, corpus_to_publish, budget)
        target = publish if publish is not None else (snapshot if cache_hit else None)
        if target is not None:
            # Pop ``key`` before summing so shrinking or LRU promotion does not
            # double-count the previous snapshot and evict unrelated entries.
            search_cache.pop(key, None)
            while search_cache and (
                len(search_cache) >= CACHE_ENTRIES
                or sum(s.byte_size for s in search_cache.values()) + target.byte_size > budget
            ):
                search_cache.pop(next(iter(search_cache)))
            search_cache[key] = target
        _record_cache_sync_signature(store)
        scanned_out = 0 if (cache_hit or (corpus_hit and corpus_delta_rows == 0)) else counts["embedding_scanned_rows"]
        snapshot_rows_out = len(corpus_to_publish.entries) if corpus_to_publish is not None and corpus_hit else counts["embedding_scanned_rows"]
        if corpus_hit and corpus_delta_rows > 0:
            scanned_out = corpus_delta_rows
        counts.update({
            "embedding_reason": "applied",
            "embedding_hits": len(results),
            "embedding_search": "authorized_exact",
            "embedding_cache_hit": cache_hit,
            "embedding_corpus_hit": corpus_hit,
            "embedding_corpus_delta_rows": corpus_delta_rows,
            "embedding_corpus_full_scan": corpus_full_scan,
            "embedding_cache_retained": target is not None,
            "embedding_snapshot_partial": bool(target is not None and not target.complete),
            "embedding_reread_rows": reread_rows,
            "embedding_reused_rows": reused_rows,
            "embedding_snapshot_budget_bytes": budget,
            "embedding_rows_materialized": len(memories),
            "embedding_batch_size": batch_size,
            "embedding_snapshot_rows": snapshot_rows_out,
            "embedding_scanned_rows": scanned_out,
            "embedding_backend": "numpy_exact" if _numpy() is not None else "python_exact",
            "embedding_search_ms": round((time.perf_counter() - started) * 1000, 3),
            "embedding_revision": expected_revision,
            "embedding_threshold": threshold,
        })
        return results, scores, counts
