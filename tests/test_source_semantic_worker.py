from __future__ import annotations

import asyncio
import hashlib
import struct
import time
from types import SimpleNamespace

import pytest

from core.source_semantic import retire_generation
from .test_source_semantic import add_row_with_id, ctx, service


pytestmark = pytest.mark.asyncio


class _EmbeddingProvider:
    def __init__(self, *, blocked: bool = False, response=None):
        self.inputs: list[str] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.blocked = blocked
        self.response = response

    def meta(self):
        return {"id": "semantic-test-provider"}

    async def get_embedding(self, text: str):
        self.inputs.append(text)
        self.entered.set()
        if self.blocked:
            await self.release.wait()
        return self.response if self.response is not None else [3.0, 4.0, 0.0]


def enable_semantic(service, provider: _EmbeddingProvider, *, history: bool = False, calls: int = 8):
    service.config.raw["source_semantic"] = {
        "enabled": True,
        "provider_id": "semantic-test-provider",
        "model_revision": "semantic-test-r1",
        "dimensions": 3,
        "history_backfill_enabled": history,
        "sources_per_run": 4,
        "provider_calls_per_run": calls,
        "fragment_target_chars": 600,
        "fragment_overlap_chars": 80,
        "window_max_chars": 1800,
        "processing_version": "source-redaction-v1",
    }
    service.context = SimpleNamespace(
        get_embedding_provider_by_id=lambda _provider_id: provider,
    )


def docs(service, generation: str):
    with service.store._lock:
        return [dict(row) for row in service.store._conn.execute(
            "SELECT * FROM source_semantic_documents WHERE generation=? ORDER BY anchor_source_id,view_kind,char_start",
            (generation,),
        ).fetchall()]


async def test_incremental_worker_indexes_exact_projected_text_and_becomes_ready(service, ctx):
    provider = _EmbeddingProvider()
    enable_semantic(service, provider)
    source_id = await add_row_with_id(
        service, ctx, "semantic-worker-source", "我把船票改成了高铁票。", "invalid-time",
    )

    await service._run_source_semantic_maintenance(ctx, source_id, "test-session")

    status = await service.source_semantic_status()
    indexed = docs(service, status["generation"])
    assert status["state"] == "ready", status
    assert status["worker"]["last_result"]["coverage_mode"] == "incremental_only"
    assert len(indexed) == 1 and indexed[0]["state"] == "ready"
    assert provider.inputs == ["我把船票改成了高铁票。"]
    assert struct.unpack("<3d", indexed[0]["vector_blob"]) == pytest.approx((0.6, 0.8, 0.0))
    assert indexed[0]["input_hash"] == hashlib.sha256(provider.inputs[0].encode("utf-8")).hexdigest()


async def test_backfill_checkpoint_has_durable_queue_and_resumes_after_call_budget(service, ctx):
    provider = _EmbeddingProvider()
    enable_semantic(service, provider, history=True, calls=1)
    first = await add_row_with_id(service, ctx, "semantic-backfill-a", "第一段", "invalid-time")
    second = await add_row_with_id(service, ctx, "semantic-backfill-b", "第二段", "invalid-time")

    await service._run_source_semantic_maintenance(ctx, "", "test-session")
    first_status = await service.source_semantic_status()
    assert first_status["state"] == "building"
    assert first_status["scan_complete"]
    assert first_status["dirty_count"] == 1
    assert {row["anchor_source_id"] for row in docs(service, first_status["generation"])} == {first}

    service._background_grace_seconds = 0
    assert await service.resume_source_semantic(first_status["generation"])
    for _ in range(20):
        latest = await service.source_semantic_status(first_status["generation"])
        if latest["state"] == "ready":
            break
        await asyncio.sleep(0.01)
    assert latest["state"] == "ready"
    assert latest["dirty_count"] == 0
    assert {row["anchor_source_id"] for row in docs(service, first_status["generation"])} == {first, second}
    assert len(provider.inputs) == 2


async def test_source_arriving_during_active_batch_gets_a_followup_run(service, ctx):
    provider = _EmbeddingProvider(blocked=True)
    enable_semantic(service, provider)
    service._background_grace_seconds = 0.02
    service._service_created_at = time.monotonic()
    first = await add_row_with_id(
        service, ctx, "semantic-overlap-first", "先进入当前批次", "invalid-time",
    )
    service._schedule_source_semantic_maintenance(ctx, first)
    await asyncio.wait_for(provider.entered.wait(), timeout=2)
    generation = service._source_semantic_status["last_generation"]

    second = await add_row_with_id(
        service, ctx, "semantic-overlap-second", "在 provider 等待期间到达", "invalid-time",
    )
    service._schedule_source_semantic_maintenance(ctx, second)
    provider.release.set()

    for _ in range(100):
        latest = await service.source_semantic_status(generation)
        if latest["state"] == "ready" and latest["dirty_count"] == 0:
            break
        await asyncio.sleep(0.01)

    assert latest["state"] == "ready"
    assert latest["dirty_count"] == 0
    assert {row["anchor_source_id"] for row in docs(service, generation)} == {first, second}
    assert provider.inputs.count("先进入当前批次") == 2
    assert provider.inputs.count("在 provider 等待期间到达") == 1


async def test_worker_rejects_multiple_vectors_for_single_source_input(service, ctx):
    provider = _EmbeddingProvider(response=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    enable_semantic(service, provider)
    source_id = await add_row_with_id(
        service, ctx, "semantic-shape-source", "响应必须只有一个向量", "invalid-time",
    )

    await service._run_source_semantic_maintenance(ctx, source_id, "test-session")

    status = await service.source_semantic_status()
    indexed = docs(service, status["generation"])
    assert status["state"] == "building"
    assert status["worker"]["last_error"] == "ValueError: semantic_embedding_response_count_mismatch"
    assert indexed and indexed[0]["state"] == "pending" and indexed[0]["vector_blob"] is None
    assert status["dirty_count"] == 1


async def test_retired_generation_rejects_provider_result_that_returns_late(service, ctx):
    provider = _EmbeddingProvider(blocked=True)
    enable_semantic(service, provider)
    source_id = await add_row_with_id(
        service, ctx, "semantic-late-source", "迟到的向量不能发布", "invalid-time",
    )
    task = asyncio.create_task(service._run_source_semantic_maintenance(ctx, source_id, "test-session"))
    await asyncio.wait_for(provider.entered.wait(), timeout=2)
    generation = service._source_semantic_status["last_generation"]
    assert generation
    await service._source_semantic_database(
        lambda conn: retire_generation(conn, generation, updated_at="2026-10-08T00:00:00+00:00")
    )
    provider.release.set()
    await asyncio.wait_for(task, timeout=2)

    status = await service.source_semantic_status(generation)
    indexed = docs(service, generation)
    assert status["state"] == "retired"
    assert indexed and indexed[0]["state"] == "pending" and indexed[0]["vector_blob"] is None
    assert status["dirty_count"] == 1


async def test_source_revision_change_rejects_late_embedding_result(service, ctx):
    provider = _EmbeddingProvider(blocked=True)
    enable_semantic(service, provider)
    source_id = await add_row_with_id(
        service, ctx, "semantic-revised-source", "原始措辞", "invalid-time",
    )
    task = asyncio.create_task(service._run_source_semantic_maintenance(ctx, source_id, "test-session"))
    await asyncio.wait_for(provider.entered.wait(), timeout=2)
    generation = service._source_semantic_status["last_generation"]
    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute(
            "UPDATE timeline SET content=? WHERE id=?", ("更新后的措辞", source_id),
        )
    provider.release.set()
    await asyncio.wait_for(task, timeout=2)

    status = await service.source_semantic_status(generation)
    indexed = docs(service, generation)
    with service.store._lock:
        dirty = service.store._conn.execute(
            "SELECT change_sequence FROM source_semantic_dirty WHERE generation=? AND source_id=?",
            (generation, source_id),
        ).fetchone()
    assert status["state"] == "building"
    assert indexed and indexed[0]["state"] == "stale" and indexed[0]["vector_blob"] is None
    assert dirty is not None and dirty[0] > 0


async def test_pause_cancels_inflight_provider_and_resume_continues(service, ctx):
    provider = _EmbeddingProvider(blocked=True)
    enable_semantic(service, provider)
    source_id = await add_row_with_id(
        service, ctx, "semantic-paused-source", "先暂停，再继续", "invalid-time",
    )
    task = asyncio.create_task(service._run_source_semantic_maintenance(ctx, source_id, "test-session"))
    await asyncio.wait_for(provider.entered.wait(), timeout=2)
    generation = service._source_semantic_status["last_generation"]

    assert await service.pause_source_semantic(generation)
    assert task.cancelled()
    paused = await service.source_semantic_status(generation)
    assert paused["state"] == "paused"
    assert paused["dirty_count"] == 1
    assert docs(service, generation)[0]["state"] == "pending"

    provider.blocked = False
    service._background_grace_seconds = 0
    assert await service.resume_source_semantic(generation)
    for _ in range(20):
        latest = await service.source_semantic_status(generation)
        if latest["state"] == "ready":
            break
        await asyncio.sleep(0.01)
    assert latest["state"] == "ready"
    assert latest["dirty_count"] == 0
    assert docs(service, generation)[0]["state"] == "ready"
