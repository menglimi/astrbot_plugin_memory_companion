"""Exact, authorized vector search with bounded, disposable local snapshots.

Only IDs, text versions and normalized numeric blocks survive snapshot building.
The caller supplies the existing visibility/lifecycle decision, not a second ACL.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import heapq
import math
import struct
import time
from typing import Any, Callable

from .models import MemoryRecord, memory_embedding_text_hash


CACHE_BYTES = 64 * 1024 * 1024
BLOCK_BYTES = 4 * 1024 * 1024
CACHE_ENTRIES = 4


class VectorSnapshotChanged(RuntimeError):
    """The caller must resolve current authorization again before retrying."""


@dataclass(frozen=True, slots=True)
class VectorRef:
    memory_id: str
    text_hash: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class VectorBlock:
    refs: tuple[VectorRef, ...]
    values: bytes  # Immutable float64 buffer; numpy views cannot mutate it.
    dimension: int

    @property
    def byte_size(self) -> int:
        return len(self.values) + sum(256 + len(r.memory_id.encode("utf-8"))
                                      + len(r.text_hash) + len(r.updated_at) for r in self.refs)


@dataclass(frozen=True, slots=True)
class VectorSnapshot:
    revision: str
    valid_until: float
    blocks: tuple[VectorBlock, ...]
    counts: tuple[tuple[str, int], ...]
    byte_size: int


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


def _next_boundary(memory: MemoryRecord, now: float) -> float:
    boundary = math.inf
    for name in ("valid_from", "valid_to"):
        value = getattr(memory, name, "") or (memory.metadata or {}).get(name, "")
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            stamp = dt.timestamp()
        except (ValueError, TypeError, OverflowError):
            continue
        if stamp > now:
            boundary = min(boundary, stamp)
    return boundary


def search_embeddings_sync(
    store: Any, provider_id: str, query: list[float], expected_revision: str,
    authorization_key: tuple, eligible: Callable[[MemoryRecord], bool],
    include_pending: bool, top_k: int, threshold: float, batch_size: int,
    max_text_chars: int, selection_time: float, cancelled: Any,
) -> tuple[list[MemoryRecord], dict[str, float], dict[str, Any]]:
    started = time.perf_counter()
    dimension = len(query)
    batch_size = min(max(1, batch_size), max(1, BLOCK_BYTES // (8 * dimension)))
    key = (provider_id, dimension, bool(include_pending), max_text_chars, authorization_key)
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
             if math.isfinite(score) and score >= threshold),
            key=lambda item: (-item[0], item[1].memory_id),
        )
        selected[:] = heapq.nsmallest(top_k, selected + best,
                                     key=lambda item: (-item[0], item[1].memory_id))

    # Serialize snapshot publication; writers keep their independent WAL connection.
    with store._vector_search_lock:
        check_cancelled()
        conn, lock = store._read_connection_for_bundle()
        with lock:
            conn.execute("BEGIN")
            try:
                row = conn.execute("SELECT revision FROM retrieval_revision WHERE singleton=1").fetchone()
                revision = str(row[0]) if row else "0"
                if revision != expected_revision:
                    raise VectorSnapshotChanged("embedding_revision_changed")
                for cached_key, value in list(store._vector_search_cache.items()):
                    if value.revision != revision or value.valid_until <= selection_time:
                        del store._vector_search_cache[cached_key]
                snapshot = store._vector_search_cache.get(key)
                cache_hit = snapshot is not None
                publish = None
                if snapshot is not None:
                    counts.update(dict(snapshot.counts))
                    valid_until = snapshot.valid_until
                    for block in snapshot.blocks:
                        accept(block)
                    # Move this entry to the newest position without copying buffers.
                    store._vector_search_cache.pop(key)
                    store._vector_search_cache[key] = snapshot
                else:
                    where = f"e.provider_id=? AND m.lifecycle!='archived' AND {store._recallable_memory_sql('m')}"
                    if not include_pending:
                        where += " AND m.review_status!='pending'"
                    cursor = conn.execute(
                        f"SELECT m.*, e.dimension AS embedding_dimension, "
                        f"e.text_hash AS embedding_text_hash FROM memory_embeddings e "
                        f"JOIN memories m ON m.id=e.memory_id WHERE {where}", (provider_id,),
                    )
                    blocks: list[VectorBlock] = []
                    retained_bytes = 0
                    cacheable = True
                    valid_until = math.inf
                    while rows := cursor.fetchmany(batch_size):
                        check_cancelled()
                        allowed = []
                        for row in rows:
                            counts["embedding_scanned_rows"] += 1
                            memory = MemoryRecord.from_row_light(dict(row))
                            # Include not-yet-active entries so a clock boundary can
                            # admit them without requiring a database write.
                            valid_until = min(valid_until, _next_boundary(memory, selection_time))
                            if not eligible(memory):
                                counts["embedding_unauthorized_or_inactive"] += 1
                                continue
                            counts["embedding_candidates"] += 1
                            text_hash = memory_embedding_text_hash(memory, max_chars=max_text_chars)
                            if not row["embedding_text_hash"] or row["embedding_text_hash"] != text_hash:
                                counts["embedding_stale"] += 1
                                continue
                            if row["embedding_dimension"] != dimension:
                                counts["embedding_dim_mismatch"] += 1
                                continue
                            allowed.append(VectorRef(memory.id, text_hash, memory.updated_at))
                        refs, values = [], bytearray()
                        # Read vector payloads only after authorization. Keep bind
                        # batches portable to SQLite builds with a 999-variable cap.
                        for offset in range(0, len(allowed), 900):
                            check_cancelled()
                            part = allowed[offset:offset + 900]
                            placeholders = ",".join("?" for _ in part)
                            payloads = dict(conn.execute(
                                f"SELECT memory_id, vector FROM memory_embeddings WHERE provider_id=? "
                                f"AND memory_id IN ({placeholders})", [provider_id] + [r.memory_id for r in part]))
                            for ref in part:
                                packed, error = _normalized_bytes(payloads.get(ref.memory_id), dimension)
                                if error:
                                    counts[error] += 1
                                    continue
                                refs.append(ref)
                                values.extend(packed)
                        if not refs:
                            continue
                        block = VectorBlock(tuple(refs), bytes(values), dimension)
                        accept(block)
                        if cacheable:
                            retained_bytes += block.byte_size
                            if retained_bytes > CACHE_BYTES:
                                blocks.clear()
                                cacheable = False
                            else:
                                blocks.append(block)
                    if cacheable:
                        publish = VectorSnapshot(revision, valid_until, tuple(blocks),
                                                 tuple(counts.items()), retained_bytes)

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
                            or not eligible(memory)):
                        raise VectorSnapshotChanged("embedding_selected_record_changed")
                    results.append(memory)
                    scores[memory.id] = score
            finally:
                conn.rollback()
        check_cancelled()
        if store._memory_revision_sync() != expected_revision or time.time() >= valid_until:
            raise VectorSnapshotChanged("embedding_revision_or_clock_changed")
        if publish is not None:
            while store._vector_search_cache and (
                len(store._vector_search_cache) >= CACHE_ENTRIES
                or sum(s.byte_size for s in store._vector_search_cache.values()) + publish.byte_size > CACHE_BYTES
            ):
                store._vector_search_cache.pop(next(iter(store._vector_search_cache)))
            store._vector_search_cache[key] = publish
        counts.update({"embedding_reason": "applied", "embedding_hits": len(results),
                       "embedding_search": "authorized_exact", "embedding_cache_hit": cache_hit,
                       "embedding_cache_retained": cache_hit or publish is not None,
                       "embedding_rows_materialized": len(memories), "embedding_batch_size": batch_size,
                       "embedding_snapshot_rows": counts["embedding_scanned_rows"],
                       "embedding_scanned_rows": 0 if cache_hit else counts["embedding_scanned_rows"],
                       "embedding_backend": "numpy_exact" if _numpy() is not None else "python_exact",
                       "embedding_search_ms": round((time.perf_counter() - started) * 1000, 3),
                       "embedding_revision": expected_revision, "embedding_threshold": threshold})
        return results, scores, counts
