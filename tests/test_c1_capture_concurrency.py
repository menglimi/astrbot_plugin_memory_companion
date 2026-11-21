"""C1（并发）：采集写入移出事件循环后不得引入竞态。

``CaptureRuntime.incoming`` 现在从工作线程调用 ``store.prepare/stage/commit``。
每个写单元仍然持有 ``store._lock`` 并各自开启 ``BEGIN IMMEDIATE``，因此并发采集
必须满足：不丢条、不重复、不出现半提交的事务、SQLite 不报 ``database is locked``。
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

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


def event(text: str, message_id: str) -> SimpleNamespace:
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
    yield value
    value.close()


def session_context(index: int) -> SessionContext:
    return SessionContext(
        session_id=f"qq:FriendMessage:c1-user-{index}",
        scope="private",
        platform="qq",
        user_id=f"c1-user-{index}",
        bot_id="c1-bot",
        persona_id="c1-persona",
        message_id=f"c1-turn-{index}",
    )


async def test_concurrent_captures_all_commit_without_interleaving(service) -> None:
    """Parallel captures must each produce exactly one committed source."""
    capture = service.capture
    capture.set_source_capture_enabled(True, actor="c1-concurrency")
    total = 16

    results = await asyncio.gather(
        *(
            capture.incoming(event(f"并发采集原文 {index}", f"c1-concurrent-{index}"), session_context(index))
            for index in range(total)
        )
    )

    assert all(item is not None for item in results)
    committed = [item for item in results if item["status"] == "committed"]
    assert len(committed) == total, [item["status"] for item in results]

    # Exactly one source and one chunk row per capture: no duplicated or
    # partially written units survived the thread hand-off.
    assert service.store._conn.execute("SELECT count(*) FROM capture_sources").fetchone()[0] == total
    assert service.store._conn.execute("SELECT count(*) FROM capture_chunks").fetchone()[0] == total
    assert service.store._conn.execute(
        "SELECT count(*) FROM capture_operations WHERE state='committed'"
    ).fetchone()[0] == total
    # Committed operations must have released their envelope (the store clears it
    # inside the same transaction), which proves no unit was left half applied.
    stale = service.store._conn.execute(
        "SELECT count(*) FROM capture_operations WHERE state='committed' AND envelope!='{}'"
    ).fetchone()[0]
    assert stale == 0

    bodies = {
        row["body"]
        for row in service.store._conn.execute("SELECT body FROM capture_chunks").fetchall()
    }
    assert bodies == {f"并发采集原文 {index}" for index in range(total)}


async def test_concurrent_duplicate_captures_stay_idempotent(service) -> None:
    """The same operation submitted twice concurrently must commit once."""
    capture = service.capture
    capture.set_source_capture_enabled(True, actor="c1-concurrency")
    ctx = session_context(99)
    duplicate = event("重复投递的同一条原文", "c1-duplicate-1")

    results = await asyncio.gather(*(capture.incoming(duplicate, ctx) for _ in range(6)))

    assert all(item is not None and item["status"] == "committed" for item in results), results
    assert service.store._conn.execute("SELECT count(*) FROM capture_sources").fetchone()[0] == 1
    assert service.store._conn.execute("SELECT count(*) FROM capture_chunks").fetchone()[0] == 1
    # All callers must observe the same receipt, not divergent state.
    assert len({json.dumps(item, sort_keys=True) for item in results}) == 1


async def test_concurrent_captures_run_on_worker_threads(service) -> None:
    """Concurrency must not collapse back onto the event loop thread."""
    capture = service.capture
    capture.set_source_capture_enabled(True, actor="c1-concurrency")
    loop_thread = threading.get_ident()
    threads: set[int] = set()
    lock = threading.Lock()

    original = capture.store.commit

    def recording_commit(*args, **kwargs):
        with lock:
            threads.add(threading.get_ident())
        return original(*args, **kwargs)

    capture.store.commit = recording_commit

    await asyncio.gather(
        *(
            capture.incoming(event(f"线程归属验证 {index}", f"c1-thread-{index}"), session_context(index))
            for index in range(8)
        )
    )

    assert threads, "没有任何 commit 发生"
    assert loop_thread not in threads, "commit 仍在事件循环线程上执行"
