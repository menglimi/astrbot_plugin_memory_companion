from __future__ import annotations

"""S4 / S5：把「函数作用在列上」的扫描换成生成列 + 索引。

S4：归档引用（bot personal archive reference [...]）以前在 14 处调用点各拼一次
    `lower(content) NOT LIKE ...`，索引完全用不上。
S5：时间线引用扫描以前是 SELECT 全表 + 逐行 json.loads（8000 行 58ms）。
"""

from dataclasses import replace
from pathlib import Path

import pytest

from core.models import EntityRef, MemoryRecord
from core.store import MemoryStore


CORE_DIR = Path(__file__).resolve().parent.parent / "core"


@pytest.fixture
def store(tmp_path):
    value = MemoryStore(tmp_path / "memory.db")
    value.initialize()
    yield value
    value.close()


def record(memory_id: str, *, content: str = "普通记忆。", metadata=None, **changes):
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
            metadata=metadata or {},
        ),
        **changes,
    ).ensure_defaults()


def query_plan(store: MemoryStore, sql: str, params=()) -> str:
    rows = store._conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return " | ".join(str(row["detail"]) for row in rows)


# ---------------------------------------------------------------- S4


def test_archive_ref_is_a_generated_column(store):
    import asyncio

    asyncio.run(store.insert_memory(record("mem-archive", content="Bot personal archive reference [abc]")))
    asyncio.run(store.insert_memory(record("mem-normal", content="用户喜欢辣味。")))
    rows = {
        row["id"]: row["is_archive_ref"]
        for row in store._conn.execute("SELECT id, is_archive_ref FROM memories").fetchall()
    }
    assert rows == {"mem-archive": 1, "mem-normal": 0}


def test_recallable_predicate_is_an_integer_comparison(store):
    sql = store._recallable_memory_sql()
    assert "is_archive_ref = 0" in sql
    assert "lower(content)" not in sql
    # 别名形式也要一起走生成列。
    aliased = store._recallable_memory_sql("m")
    assert "m.is_archive_ref = 0" in aliased


def test_recallable_view_hides_archive_rows(store):
    import asyncio

    asyncio.run(store.insert_memory(record("mem-archive", content="Bot personal archive reference [abc]")))
    asyncio.run(store.insert_memory(record("mem-normal", content="用户喜欢辣味。")))
    ids = {
        row["id"]
        for row in store._conn.execute(
            f"SELECT id FROM {MemoryStore.RECALLABLE_MEMORY_VIEW}"
        ).fetchall()
    }
    assert ids == {"mem-normal"}


def test_archive_ref_predicate_is_not_hand_rolled_any_more():
    # 14 处手拼字符串是这条报告的原始问题；除了 helper 的兜底分支（老库/只读快照）
    # 和 docstring 里对历史的说明，源码里不该再有第二份可执行谓词。
    executable = 0
    for path in CORE_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if "NOT LIKE 'bot personal archive reference" not in stripped:
                continue
            if stripped.startswith("#") or stripped.startswith('"""') or "以前这里是" in stripped:
                continue
            executable += 1
    assert executable == 1


# ---------------------------------------------------------------- S5


async def seed_timeline_refs(store: MemoryStore) -> None:
    for index in range(40):
        await store.insert_memory(record(f"mem-plain-{index}", content=f"普通记忆 {index}。"))
    # 内容必须各不相同，否则插入时的合并逻辑会把三行并成一行。
    await store.insert_memory(
        record("mem-ref-a", content="引用 A。", metadata={"source_event_id": "tl_event_a"})
    )
    await store.insert_memory(
        record("mem-ref-b", content="引用 B。", metadata={"source_event_ids": ["timeline:tl_event_b"]})
    )
    await store.insert_memory(
        record("mem-ref-c", content="引用 C。", metadata={"nested": {"refs": ["tl_event_c", "not_a_ref"]}})
    )


@pytest.mark.asyncio
async def test_timeline_ref_scan_only_touches_candidate_rows(store):
    await seed_timeline_refs(store)
    total = store._conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]
    candidates = store._conn.execute(
        "SELECT COUNT(*) AS n FROM memories WHERE has_timeline_ref = 1"
    ).fetchone()["n"]
    assert total == 43
    assert candidates == 3

    plan = query_plan(
        store,
        "SELECT id, metadata FROM memories WHERE has_timeline_ref = 1",
    )
    assert "idx_memories_timeline_ref" in plan

    matches = store._timeline_reference_memories_sync({"tl_event_a", "tl_event_c"})
    assert {memory_id for memory_id, _ in matches} == {"mem-ref-a", "mem-ref-c"}


@pytest.mark.asyncio
async def test_timeline_ref_scan_matches_the_bruteforce_result(store):
    await seed_timeline_refs(store)
    event_ids = {"tl_event_a", "tl_event_b", "tl_event_c", "tl_missing"}

    def brute_force() -> set[str]:
        found: set[str] = set()
        for row in store._conn.execute("SELECT id, metadata FROM memories").fetchall():
            metadata = MemoryStore._timeline_ids_in_metadata(
                __import__("json").loads(row["metadata"] or "{}")
            )
            if event_ids & metadata:
                found.add(row["id"])
        return found

    optimized = {memory_id for memory_id, _ in store._timeline_reference_memories_sync(event_ids)}
    assert optimized == brute_force() == {"mem-ref-a", "mem-ref-b", "mem-ref-c"}


@pytest.mark.asyncio
async def test_expiring_a_timeline_source_still_reaches_referencing_memories(store):
    await seed_timeline_refs(store)
    changed = store._mark_timeline_sources_expired_sync(["tl_event_a"])
    assert changed == 1
    metadata = __import__("json").loads(
        store._conn.execute("SELECT metadata FROM memories WHERE id='mem-ref-a'").fetchone()["metadata"]
    )
    assert metadata["source_expired_event_ids"] == ["tl_event_a"]


def test_timeline_ref_column_is_detected_on_old_databases(tmp_path):
    # 老库没有生成列：先建库再模拟「迁移没跑过」的只读快照，谓词必须退回全表扫描。
    path = tmp_path / "memory.db"
    store = MemoryStore(path)
    store.initialize()
    try:
        assert store._memory_timeline_ref_available_sync() is True
        store._timeline_ref_column_available = False
        assert store._timeline_reference_memories_sync({"tl_x"}) == []
    finally:
        store.close()
