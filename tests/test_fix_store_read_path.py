from __future__ import annotations

"""S1：纯读路径（list_memories）不再抢全局写锁。

store.py 里 174 处 `with self._lock` 把读也串在写后面。这里只拆最热的一条：
list_memories 走专用只读连接 + 自己的读锁；但两种情况下必须退回主连接，
否则语义会变：只读库（主连接本身就是 ro）、主连接有未提交事务（读己之写）。
"""

import asyncio
import threading
import time
from dataclasses import replace

import pytest

from core.models import EntityRef, MemoryRecord
from core.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    value = MemoryStore(tmp_path / "memory.db")
    value.initialize()
    yield value
    value.close()


def record(memory_id: str, content: str = "用户喜欢辣味。"):
    return replace(
        MemoryRecord(
            id=memory_id,
            memory_type="memory",
            subject=EntityRef(kind="user", id="user"),
            object=EntityRef(kind="bot", id="bot"),
            owner_bot_id="bot",
            scope="private",
            platform="qq",
            session_id="qq:FriendMessage:user",
            visibility="private_pair",
            lifecycle="stable_memory",
            content=content,
        )
    ).ensure_defaults()


@pytest.mark.asyncio
async def test_list_memories_uses_the_dedicated_read_connection(store):
    await store.insert_memory(record("mem-1"))
    calls = []
    original = store._ensure_read_connection

    def counting_ensure():
        calls.append(1)
        return original()

    store._ensure_read_connection = counting_ensure
    rows = await store.list_memories(limit=10)
    assert [row.id for row in rows] == ["mem-1"]
    assert calls, "list_memories 应该走 _read_connection_for_bundle()"
    assert store._read_conn is not None
    # 只读连接确实拿得到数据（WAL 下提交后立即可见）。
    assert store._read_conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_list_memories_reads_its_own_uncommitted_writes(store):
    store._conn.execute("BEGIN IMMEDIATE")
    try:
        store._insert_memory_sync(record("mem-pending"), _commit=False)
        assert store._conn.in_transaction is True
        rows = await store.list_memories(limit=10)
        assert [row.id for row in rows] == ["mem-pending"]
    finally:
        store._conn.rollback()
    assert await store.list_memories(limit=10) == []


@pytest.mark.asyncio
async def test_list_memories_does_not_wait_for_the_main_write_lock(store):
    await store.insert_memory(record("mem-1"))
    held = threading.Event()
    release = threading.Event()

    def hold_write_lock() -> None:
        with store._lock:
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold_write_lock, daemon=True)
    holder.start()
    try:
        assert held.wait(5)
        rows = await asyncio.wait_for(store.list_memories(limit=10), timeout=2.0)
        assert [row.id for row in rows] == ["mem-1"]
    finally:
        release.set()
        holder.join(5)


@pytest.mark.asyncio
async def test_list_memories_stays_consistent_while_writes_land(store):
    await store.insert_memory(record("mem-0"))
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        index = 1
        while not stop.is_set():
            try:
                store._insert_memory_sync(record(f"mem-{index}", content=f"内容 {index}"))
                index += 1
            except BaseException as exc:  # pragma: no cover - 失败时断言里会打印
                errors.append(exc)
                return

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        for _ in range(30):
            rows = await store.list_memories(limit=100)
            assert len(rows) == len({row.id for row in rows})
            assert all(row.content for row in rows)
    finally:
        stop.set()
        thread.join(5)
    assert errors == []
    final = await store.list_memories(limit=500)
    assert len(final) >= 2
