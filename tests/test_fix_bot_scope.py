from __future__ import annotations

"""S13：bot 归属统一口径。

2.5.0 之前的行没有 bot_id，落成 ''；这些行按「公共可读」处理，否则老库升级后
谁都读不到自己的记忆。非空且不等于当前 bot 的行一律读不到。
"""

from dataclasses import replace

import pytest

from core.models import EntityRef, MemoryRecord
from core.store import MemoryStore


BOT_A = "bot-a"
BOT_B = "bot-b"


@pytest.fixture
def store(tmp_path):
    value = MemoryStore(tmp_path / "memory.db")
    value.initialize()
    yield value
    value.close()


def record(memory_id: str, *, owner_bot_id: str, content: str = "记一笔。", **changes):
    return replace(
        MemoryRecord(
            id=memory_id,
            memory_type="memory",
            subject=EntityRef(kind="user", id="user"),
            object=EntityRef(kind="bot", id=owner_bot_id or BOT_A),
            owner_bot_id=owner_bot_id,
            scope="private",
            platform="qq",
            session_id="qq:FriendMessage:user",
            visibility="private_pair",
            lifecycle="stable_memory",
            content=content,
            metadata={"owner_bot_id": owner_bot_id},
        ),
        **changes,
    ).ensure_defaults()


async def seed(store: MemoryStore) -> None:
    await store.insert_memory(record("mem-own", owner_bot_id=BOT_A, content="A 记得的。"))
    await store.insert_memory(record("mem-other", owner_bot_id=BOT_B, content="B 记得的。"))
    await store.insert_memory(record("mem-legacy", owner_bot_id="", content="老数据。"))


def test_bot_scope_clause_is_a_no_op_without_a_bot() -> None:
    clause, params = MemoryStore._bot_scope_clause("owner_bot_id", "")
    assert clause == ""
    assert params == []


def test_bot_scope_clause_is_parameterised() -> None:
    clause, params = MemoryStore._bot_scope_clause("owner_bot_id", "bot-a")
    assert clause == " AND (owner_bot_id=? OR owner_bot_id='')"
    assert params == ["bot-a"]
    # 列名只接受合法标识符，注入用的分号/关键字一律被拒。
    clause, params = MemoryStore._bot_scope_clause("owner_bot_id; DROP TABLE memories", "bot-a")
    assert clause == ""
    assert params == []


@pytest.mark.asyncio
async def test_list_memories_hides_other_bots_rows(store):
    await seed(store)
    ids = {item.id for item in await store.list_memories(limit=50, owner_bot_id=BOT_A)}
    assert ids == {"mem-own", "mem-legacy"}


@pytest.mark.asyncio
async def test_list_memories_without_bot_filter_still_sees_everything(store):
    await seed(store)
    ids = {item.id for item in await store.list_memories(limit=50)}
    assert ids == {"mem-own", "mem-other", "mem-legacy"}


@pytest.mark.asyncio
async def test_person_snapshot_hides_other_bots_rows(store):
    await seed(store)
    snapshot = await store.person_snapshot(user_id="user", bot_id=BOT_A, scope="private")
    ids = {row["id"] for row in snapshot["memories"]}
    assert ids == {"mem-own", "mem-legacy"}
    assert snapshot["total"] == 2


@pytest.mark.asyncio
async def test_person_weight_stats_ignore_other_bots_rows(store):
    await seed(store)
    stats = store._person_weight_stats_sync("user", "", BOT_A)
    assert stats["memory_count"] == 2
    stats = store._person_weight_stats_sync("user", "", BOT_B)
    assert stats["memory_count"] == 2
    stats = store._person_weight_stats_sync("user", "", "")
    assert stats["memory_count"] == 3


@pytest.mark.asyncio
async def test_recent_timeline_hides_other_bots_events(store):
    for event_id, owner in (("tl-a", BOT_A), ("tl-b", BOT_B), ("tl-legacy", "")):
        await store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:user",
            scope="private",
            subject_id="user",
            object_id=owner or BOT_A,
            content=event_id,
            metadata={"owner_bot_id": owner},
        )
    rows = await store.recent_timeline(limit=20, scope="private", session_id="qq:FriendMessage:user", bot_id=BOT_A)
    contents = {row["content"] for row in rows}
    assert "tl-a" in contents
    assert "tl-legacy" in contents
    assert "tl-b" not in contents


@pytest.mark.asyncio
async def test_recent_timeline_entity_split_hides_other_bots_events(store):
    for event_id, owner in (("tl-a", BOT_A), ("tl-b", BOT_B), ("tl-legacy", "")):
        await store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:user",
            scope="private",
            subject_id="user",
            object_id=owner or BOT_A,
            content=event_id,
            metadata={"owner_bot_id": owner},
        )
    rows = await store.recent_timeline(
        limit=20,
        scope="private",
        session_id="qq:FriendMessage:user",
        entity_id="user",
        bot_id=BOT_A,
    )
    contents = {row["content"] for row in rows}
    assert "tl-a" in contents
    assert "tl-legacy" in contents
    assert "tl-b" not in contents
