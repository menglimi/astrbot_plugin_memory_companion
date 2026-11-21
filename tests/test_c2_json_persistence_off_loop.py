"""C2（写入原语）：大 JSON 必须原子替换、可并发、且不在调用线程序列化。

``test_c2_service_json_writes.py`` 钉住 service 的接线；这里钉住原语本身。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


@pytest.fixture
def persistence():
    from astrbot_plugin_memory_companion.core import json_persistence

    return json_persistence


def big_document(entries: int = 1200) -> dict:
    return {
        "by_hour": {
            f"2026-09-{index % 28 + 1:02d}T{index % 24:02d}:00": {"calls": index}
            for index in range(entries)
        },
        "recent": [{"ts": index, "task": "memory_summary"} for index in range(240)],
        "updated_at": "2026-11-18 00:00:00",
    }


@pytest.fixture
def service(tmp_path: Path):
    value = MemoryCompanionService(
        context=None,
        plugin_root=ROOT,
        data_dir=tmp_path,
        config={"retrieval": {"mode": "basic", "embedding_enabled": False}},
    )
    yield value
    value.close()


def test_plain_json_copy_detaches_containers(persistence) -> None:
    document = big_document(8)
    snapshot = persistence.plain_json_copy(document)

    assert snapshot == document
    assert snapshot is not document
    assert snapshot["by_hour"] is not document["by_hour"]
    assert snapshot["recent"][0] is not document["recent"][0]

    # Mutating the live document must not change an already taken snapshot.
    document["by_hour"]["2026-09-01T00:00"] = {"calls": -1}
    document["recent"][0]["task"] = "changed"
    assert snapshot["by_hour"]["2026-09-01T00:00"] == {"calls": 0}
    assert snapshot["recent"][0]["task"] == "memory_summary"


def test_plain_json_copy_rejects_values_json_cannot_encode(persistence) -> None:
    with pytest.raises(TypeError):
        persistence.plain_json_copy({"bad": object()})


def test_atomic_write_leaves_no_partial_file_and_no_staging_litter(tmp_path: Path, persistence) -> None:
    target = tmp_path / "state.json"
    persistence.write_json_atomically(target, '{"ok": true}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}

    with patch(
        "astrbot_plugin_memory_companion.core.json_persistence.os.replace",
        side_effect=OSError("swap refused"),
    ):
        with pytest.raises(OSError):
            persistence.write_json_atomically(target, '{"ok": false}')

    leftovers = [item.name for item in tmp_path.iterdir() if item.name != "state.json"]
    assert leftovers == [], f"失败写入留下了暂存文件：{leftovers}"
    # The previously published document must survive a failed replacement.
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


async def test_concurrent_writes_never_tear_the_document(tmp_path: Path, persistence) -> None:
    """Many writers hammering one path must always leave a parseable document."""
    target = tmp_path / "state.json"
    payloads = [
        json.dumps({"writer": index, "body": "x" * (200 * (index + 1))}) for index in range(40)
    ]

    await asyncio.gather(
        *(asyncio.to_thread(persistence.write_json_atomically, target, payload) for payload in payloads)
    )

    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["writer"] in range(40)
    assert set(written) == {"writer", "body"}
    assert not [item.name for item in tmp_path.iterdir() if item.name != "state.json"]


async def test_service_writer_coalesces_bursts_and_keeps_the_last_update(service) -> None:
    target = service.token_usage_path
    writer = service._token_usage_writer
    service._token_usage = {"totals": {"calls": 0}}

    writes = 0
    original = writer._write_if_newest

    def counting_write(target_gen, payload, **kwargs):
        nonlocal writes
        writes += 1
        return original(target_gen, payload, **kwargs)

    writer._write_if_newest = counting_write

    for index in range(50):
        service._token_usage["totals"]["calls"] = index + 1
        service._token_usage_last_save_at = 0.0
        service._save_token_usage()
    await writer.flush_async()

    assert json.loads(target.read_text(encoding="utf-8"))["totals"]["calls"] == 50
    assert writes < 50, f"未合并请求：{writes} 次写盘"


async def test_stale_write_cannot_overwrite_a_newer_snapshot(service) -> None:
    """A slow in-flight write starts immediately inside grace and never clobbers a newer flush."""
    target = service.token_usage_path
    writer = service._token_usage_writer
    service._token_usage = {"totals": {"calls": 1}}

    started = threading.Event()
    release = threading.Event()

    original_serialise = writer._serialise

    def slow_serialise(document):
        if document["totals"]["calls"] == 1:
            started.set()
            release.wait(timeout=10)
        return original_serialise(document)

    writer._serialise = slow_serialise
    service._token_usage_last_save_at = 0.0
    t0 = time.monotonic()
    service._save_token_usage()
    # Even within the 60s startup grace window, persistence tasks launch immediately.
    assert await asyncio.to_thread(started.wait, 5) is True
    assert time.monotonic() - t0 < 2.0, "后台持久化任务未在毫秒级即时启动"
    inflight_task = writer._task

    service._token_usage["totals"]["calls"] = 2
    assert await writer.flush_async() is True
    release.set()
    if inflight_task is not None:
        await inflight_task

    assert json.loads(target.read_text(encoding="utf-8"))["totals"]["calls"] == 2


async def test_writer_serialises_on_a_worker_thread_not_the_loop(service) -> None:
    threads: list[int] = []
    writer = service._token_usage_writer
    service._token_usage = big_document(200)
    original = writer._serialise
    writer._serialise = lambda document: threads.append(threading.get_ident()) or original(document)

    await writer.flush_async()

    assert threads
    assert all(ident != threading.get_ident() for ident in threads)


async def test_flush_async_and_flush_if_dirty_snapshot_on_loop_and_write_off_loop(
    tmp_path: Path, persistence
) -> None:
    """``snapshot()`` must always run on the loop thread, never inside ``to_thread``."""
    target = tmp_path / "loop_snapshot.json"
    loop_thread = threading.get_ident()
    state = {"count": 1}
    snapshot_threads: list[int] = []
    serialise_threads: list[int] = []

    def snapshot():
        snapshot_threads.append(threading.get_ident())
        return persistence.plain_json_copy(state)

    def serialise(doc):
        serialise_threads.append(threading.get_ident())
        return json.dumps(doc)

    writer = persistence.BackgroundJsonWriter(
        path=lambda: target,
        snapshot=snapshot,
        serialise=serialise,
        spawn=lambda coro: asyncio.create_task(coro),
        label="snapshot-thread-check",
    )

    # Clean state: flush_if_dirty must be a zero-snapshot, zero-thread-switch no-op.
    assert await writer.flush_if_dirty() is False
    assert snapshot_threads == []
    assert serialise_threads == []
    assert not target.exists()

    # flush_async: snapshot on loop thread, serialise/write on worker thread.
    assert await writer.flush_async() is True
    assert snapshot_threads == [loop_thread]
    assert len(serialise_threads) == 1 and serialise_threads[0] != loop_thread
    assert json.loads(target.read_text(encoding="utf-8")) == {"count": 1}

    # Dirty via mark_dirty: flush_if_dirty snapshots on loop thread and writes on worker thread.
    state["count"] = 2
    writer.mark_dirty()
    assert writer.dirty is True
    assert await writer.flush_if_dirty() is True
    assert snapshot_threads == [loop_thread, loop_thread]
    assert len(serialise_threads) == 2 and serialise_threads[1] != loop_thread
    assert json.loads(target.read_text(encoding="utf-8")) == {"count": 2}
    assert writer.dirty is False


async def test_aclose_only_flushes_dirty_writers_on_worker_thread(
    tmp_path: Path, persistence
) -> None:
    """Clean writers do zero I/O on ``aclose()``; dirty writers flush off-loop."""
    loop_thread = threading.get_ident()

    clean_path = tmp_path / "clean.json"
    clean_snapshots = 0
    clean_serialises = 0

    def clean_snap():
        nonlocal clean_snapshots
        clean_snapshots += 1
        return {}

    def clean_ser(doc):
        nonlocal clean_serialises
        clean_serialises += 1
        return json.dumps(doc)

    clean_writer = persistence.BackgroundJsonWriter(
        path=lambda: clean_path,
        snapshot=clean_snap,
        serialise=clean_ser,
        spawn=lambda coro: asyncio.create_task(coro),
        label="clean-aclose",
    )
    await clean_writer.aclose()
    assert clean_snapshots == 0
    assert clean_serialises == 0
    assert not clean_path.exists()

    dirty_path = tmp_path / "dirty.json"
    dirty_state = {"calls": 9}
    snap_threads: list[int] = []
    write_threads: list[int] = []

    def refuse_spawn(coro):
        coro.close()
        return None

    dirty_writer = persistence.BackgroundJsonWriter(
        path=lambda: dirty_path,
        snapshot=lambda: (snap_threads.append(threading.get_ident()), dict(dirty_state))[1],
        serialise=lambda doc: (write_threads.append(threading.get_ident()), json.dumps(doc))[1],
        spawn=refuse_spawn,
        label="dirty-aclose",
    )
    # Even when spawn returns None, dirty state is preserved and flushed on aclose().
    dirty_writer.request()
    assert dirty_writer.dirty is True

    await dirty_writer.aclose()
    assert snap_threads == [loop_thread]
    assert len(write_threads) == 1 and write_threads[0] != loop_thread
    assert json.loads(dirty_path.read_text(encoding="utf-8")) == {"calls": 9}
    assert dirty_writer.dirty is False

    # A second aclose() is a no-op with zero extra disk writes.
    await dirty_writer.aclose()
    assert len(snap_threads) == 1
    assert len(write_threads) == 1


async def test_service_aclose_flushes_only_dirty_instantiated_writers(tmp_path: Path) -> None:
    svc = MemoryCompanionService(
        context=None,
        plugin_root=ROOT,
        data_dir=tmp_path,
        config={"retrieval": {"mode": "basic", "embedding_enabled": False}},
    )
    svc._token_usage = {"totals": {"calls": 42}}
    # Inside 30s throttle interval: mark_dirty records pending token state without immediate I/O.
    svc._token_usage_last_save_at = time.time()
    svc._save_token_usage()
    assert not svc.token_usage_path.exists()

    await svc.aclose()

    assert json.loads(svc.token_usage_path.read_text(encoding="utf-8"))["totals"]["calls"] == 42
    assert "_relationship_phase_writer_instance" not in svc.__dict__
    assert not svc._RELATIONSHIP_PHASE_FILE.exists()


async def test_drain_failure_preserves_dirty_state_without_spinning(
    tmp_path: Path, persistence
) -> None:
    target = tmp_path / "retry.json"
    state = {"version": 1}
    attempts = 0
    writer = persistence.BackgroundJsonWriter(
        path=lambda: target,
        snapshot=lambda: dict(state),
        serialise=json.dumps,
        spawn=lambda coro: asyncio.create_task(coro),
        label="fail-then-recover",
    )

    def failing_replace(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise OSError("disk temporarily busy")

    with patch(
        "astrbot_plugin_memory_companion.core.json_persistence.os.replace",
        side_effect=failing_replace,
    ):
        writer.request()
        task = writer._task
        assert task is not None
        await task

    assert attempts == 1, "写盘失败后不应在后台死循环忙等"
    assert writer.dirty is True
    assert not target.exists()

    # Subsequent flush succeeds and clears dirty state.
    assert await writer.flush_async() is True
    assert writer.dirty is False
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}


async def test_off_loop_write_keeps_the_event_loop_schedulable(service) -> None:
    """Serialising a large document must not stall the loop (the C2 defect)."""
    writer = service._token_usage_writer
    service._token_usage = big_document(2400)
    ticks: list[float] = []

    async def heartbeat() -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            ticks.append(now - last)
            last = now

    pulse = asyncio.create_task(heartbeat())
    try:
        for _ in range(6):
            service._token_usage_last_save_at = 0.0
            service._save_token_usage()
            await asyncio.sleep(0.01)
        await writer.flush_async()
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)

    assert ticks, "写入期间事件循环一次都没有被调度"
    assert max(ticks) < 0.10, f"事件循环被序列化拖慢到 {max(ticks):.3f}s"


async def test_concurrent_readers_never_observe_a_torn_document(service) -> None:
    """Readers polling the file must never parse a partial document.

    Windows refuses a replace while another handle has the destination open, so
    this also proves a failed swap does not drop the update: the final document
    still carries every request.
    """
    target = service.token_usage_path
    writer = service._token_usage_writer
    service._token_usage = {"totals": {"calls": 0}, "by_hour": {f"h{index}": {"calls": index} for index in range(600)}}

    torn: list[str] = []
    reads = [0]
    # Windows may refuse a read while the swap is in flight; that is a sharing
    # violation, not corruption, so it is retried rather than counted.
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                text = target.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            except PermissionError:
                continue
            except OSError as exc:
                torn.append(f"oserror:{exc}")
                continue
            reads[0] += 1
            try:
                document = json.loads(text)
            except ValueError:
                torn.append(text[:80])
                continue
            if set(document) != {"totals", "by_hour"} or len(document["by_hour"]) != 600:
                torn.append(f"shape:{sorted(document)}")

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for thread in threads:
        thread.start()
    flushed_during_reads = False
    try:
        for index in range(120):
            service._token_usage["totals"]["calls"] = index + 1
            service._token_usage_last_save_at = 0.0
            service._save_token_usage()
            if index % 7 == 0:
                await asyncio.sleep(0)
        flushed_during_reads = await writer.flush_async()
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)

    if not flushed_during_reads:
        # Windows may refuse every os.replace retry while 4 tight-loop readers
        # continuously hold the handle; dirty state must survive and flush next.
        assert writer.dirty is True
        assert await writer.flush_async() is True

    assert torn == [], f"读到撕裂/形状异常的文件：{torn[:3]}"
    assert reads[0] > 0, "读线程一次都没读到文件"
    final = json.loads(target.read_text(encoding="utf-8"))
    assert final["totals"]["calls"] == 120, "并发读取期间丢失了更新"
    assert len(final["by_hour"]) == 600
    staging = [item.name for item in target.parent.iterdir() if item.name.startswith(f".{target.name}.")]
    assert staging == [], f"残留暂存文件：{staging}"
