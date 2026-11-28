"""C1：来源采集写入不得阻塞事件循环。

``CaptureRuntime.incoming``/``submit`` 与后台 ``loop`` 每一次落库都会打开
``BEGIN IMMEDIATE`` 事务并 commit，属于纯阻塞 I/O。这些用例用「并发心跳」证明
写入期间事件循环仍在推进：心跳任务在采集写入进行中记录自己的 tick 间隔，只要
写操作跑在循环线程上，间隔就会被拉长到与写耗时同量级。

用例同时钉住修复前的可观测差异：``_store_call_threads`` 记录每个 store 调用实际
运行在哪个线程，未修复时全部落在主线程（事件循环线程）。
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class Plain:
    def __init__(self, text: str):
        self.text = text


def event(text: str, message_id: str = "c1-native-1") -> SimpleNamespace:
    return SimpleNamespace(
        message_obj=SimpleNamespace(message_id=message_id, message=[Plain(text)], timestamp=0),
        message_str=text,
    )


@pytest.fixture
def service(tmp_path: Path):
    value = MemoryCompanionService(
        context=None,
        plugin_root=ROOT,
        data_dir=tmp_path,
        config={
            "memory_capture": {"source_capture_enabled": True, "reliable_sources_enabled": True},
            "retrieval": {"mode": "basic", "embedding_enabled": False},
            "memory_injection": {"enable_injection_logs": False},
        },
    )
    value.identity.resolve_event_context = AsyncMock(
        return_value=SessionContext(
            session_id="qq:FriendMessage:c1-user",
            scope="private",
            platform="qq",
            user_id="c1-user",
            bot_id="c1-bot",
            persona_id="c1-persona",
            message_id="c1-turn",
        )
    )
    yield value
    value.close()


def store_call_threads(capture) -> list[tuple[str, int]]:
    """Record the thread each capture store call runs on, then delegate."""
    recorded: list[tuple[str, int]] = []
    for name in (
        "source_capture_enabled",
        "prepare",
        "stage",
        "commit",
        "purge_expired",
        "due",
        "retry",
    ):
        original = getattr(capture.store, name)

        def wrapper(*args, __original=original, __name=name, **kwargs):
            recorded.append((__name, threading.get_ident()))
            return __original(*args, **kwargs)

        setattr(capture.store, name, wrapper)
    return recorded


async def test_incoming_writes_leave_the_event_loop_thread(service) -> None:
    capture = service.capture
    capture.set_source_capture_enabled(True, actor="c1-test")
    recorded = store_call_threads(capture)

    receipt = await capture.incoming(
        event("C1 采集写入应离开事件循环线程"),
        service._normalized_session_context(
            await service.identity.resolve_event_context(None)
        ),
    )

    assert receipt["status"] == "committed", receipt
    self_thread = threading.get_ident()
    touched = {name: ident for name, ident in recorded}
    assert {"source_capture_enabled", "prepare", "stage", "commit"} <= set(touched)
    for name in ("source_capture_enabled", "prepare", "stage", "commit"):
        assert touched[name] != self_thread, f"{name} 仍在事件循环线程上执行"


async def test_incoming_keeps_the_event_loop_responsive_while_writing(service) -> None:
    """A concurrent heartbeat must keep ticking inside the budget of one write."""
    capture = service.capture
    capture.set_source_capture_enabled(True, actor="c1-test")
    original_stage = capture.store.stage

    ticks: list[float] = []

    def slow_stage(*args, **kwargs):
        # Stand in for a contended BEGIN IMMEDIATE + commit: the loop has to stay
        # responsive for this whole window, which is what C1 fixes.
        deadline = time.perf_counter() + 0.25
        while time.perf_counter() < deadline:
            pass
        return original_stage(*args, **kwargs)

    capture.store.stage = slow_stage

    async def heartbeat() -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            ticks.append(now - last)
            last = now

    pulse = asyncio.create_task(heartbeat())
    try:
        ctx = service._normalized_session_context(await service.identity.resolve_event_context(None))
        receipt = await capture.incoming(event("C1 写入期间心跳应继续推进"), ctx)
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)

    assert receipt["status"] == "committed", receipt
    assert ticks, "心跳任务一次都没有被调度：事件循环被写入完全占住"
    # The blocking window is 0.25s; a responsive loop ticks many times inside it.
    assert max(ticks) < 0.20, f"心跳被写入拖慢到 {max(ticks):.3f}s"


async def test_capture_loop_writes_leave_the_event_loop_thread(service) -> None:
    """The retry worker also commits on the store; it may not block the loop."""
    capture = service.capture
    capture.set_source_capture_enabled(True, actor="c1-test")
    ctx = service._normalized_session_context(await service.identity.resolve_event_context(None))
    identity = capture.identity(ctx, direction="incoming", message="c1-loop-1")
    prepared = capture.store.prepare(identity, body="C1 后台重试路径", observed_at="2026-11-18T00:00:00+00:00")
    capture.store.stage(prepared, generation=capture.generation)

    recorded = store_call_threads(capture)
    service._closing = False

    async def run_one_iteration() -> None:
        # Reproduce one pass of CaptureRuntime.loop without its 60s wait.
        await asyncio.sleep(0)
        capture.wake.set()
        worker = asyncio.create_task(capture.loop())
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if service.store._conn.execute(
                    "SELECT count(*) FROM capture_operations WHERE state='committed'"
                ).fetchone()[0]:
                    return
                await asyncio.sleep(0.02)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    await run_one_iteration()

    commits = [ident for name, ident in recorded if name == "commit"]
    assert commits, "后台 loop 没有提交任何待处理来源"
    self_thread = threading.get_ident()
    assert all(ident != self_thread for ident in commits), "后台 loop 的 commit 仍在事件循环线程上"


async def test_capture_loop_retry_runs_off_loop_and_survives_retry_exception(service) -> None:
    """``store.retry()`` must run off-loop and never kill ``loop()`` on error."""
    capture = service.capture
    capture.set_source_capture_enabled(True, actor="c1-test")
    ctx = service._normalized_session_context(await service.identity.resolve_event_context(None))
    identity = capture.identity(ctx, direction="incoming", message="c1-retry-err-1")
    prepared = capture.store.prepare(
        identity, body="C1 重试异常隔离", observed_at="2026-11-18T00:00:00+00:00"
    )
    capture.store.stage(prepared, generation=capture.generation)

    loop_thread = threading.get_ident()
    retry_threads: list[int] = []
    retry_done = threading.Event()
    fail_commit = True
    original_commit = capture.store.commit

    def flaky_commit(*args, **kwargs):
        if fail_commit:
            raise RuntimeError("transient commit error")
        return original_commit(*args, **kwargs)

    def failing_retry(operation, generation):
        retry_threads.append(threading.get_ident())
        retry_done.set()
        raise ValueError("capture_authority_changed")

    capture.store.commit = flaky_commit
    capture.store.retry = failing_retry
    service._closing = False

    capture.wake.set()
    worker = asyncio.create_task(capture.loop())
    try:
        assert await asyncio.to_thread(retry_done.wait, 3.0) is True
        await asyncio.sleep(0.02)
        assert not worker.done(), "store.retry() 抛异常后后台 loop 协程被直接杀死了"
        assert retry_threads, "store.retry() 从未被调用"
        assert all(ident != loop_thread for ident in retry_threads), (
            "store.retry() 仍在事件循环线程上执行"
        )

        # Recover commit and verify the SAME worker loop still processes the next pass.
        fail_commit = False
        capture.wake.set()
        deadline = time.monotonic() + 3.0
        committed = 0
        while time.monotonic() < deadline:
            committed = service.store._conn.execute(
                "SELECT count(*) FROM capture_operations WHERE state='committed'"
            ).fetchone()[0]
            if committed:
                break
            await asyncio.sleep(0.02)
        assert committed == 1, "loop 协程在 retry() 异常后未能继续处理后续来源"
        assert not worker.done()
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
