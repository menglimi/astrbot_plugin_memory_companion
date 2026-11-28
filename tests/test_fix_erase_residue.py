from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from core.memory_revision import memory_ref
from core.models import EntityRef, MemoryRecord, SessionContext
from core.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    value = MemoryStore(tmp_path / "memory.db")
    value.initialize()
    yield value
    value.close()


def context(user_id: str = "user", **changes):
    return replace(
        SessionContext(
            scope="private",
            platform="qq",
            session_id="qq:FriendMessage:user",
            user_id=user_id,
            bot_id="bot",
            persona_id="persona",
            message_id="message-2",
            message_text="我喜欢辣味。",
        ),
        **changes,
    )


def record(memory_id: str = "mem-old", user_id: str = "user", content: str = "用户喜欢辣味。", **changes):
    return replace(
        MemoryRecord(
            id=memory_id,
            memory_type="memory",
            subject=EntityRef(kind="user", id=user_id),
            object=EntityRef(kind="bot", id="bot"),
            owner_bot_id="bot",
            scope="private",
            platform="qq",
            session_id="qq:FriendMessage:user",
            visibility="private_pair",
            lifecycle="stable_memory",
            content=content,
            evidence="我喜欢辣味。",
            metadata={"persona_id": "persona", "owner_bot_id": "bot"},
        ),
        **changes,
    ).ensure_defaults()


def node_labels(store: MemoryStore) -> set[str]:
    return {row["label"] for row in store._conn.execute("SELECT label FROM knowledge_nodes").fetchall()}


@pytest.mark.asyncio
async def test_erase_removes_knowledge_graph_projection_of_the_memory(store):
    item = record()
    await store.insert_memory(item)
    memory_node = await store.upsert_knowledge_node(
        node_type="memory",
        label=item.content,
        scope="private",
        session_id="qq:FriendMessage:user",
        metadata={"memory_id": item.id},
    )
    person_node = await store.upsert_knowledge_node(
        node_type="person",
        label="user",
        scope="private",
        session_id="qq:FriendMessage:user",
        metadata={"source_memory_id": item.id},
    )
    await store.upsert_knowledge_edge(
        source_node_id=memory_node,
        target_node_id=person_node,
        relation_type="about",
        scope="private",
        session_id="qq:FriendMessage:user",
        source_memory_id=item.id,
        evidence="我喜欢辣味。",
    )
    assert store._conn.execute("SELECT COUNT(*) FROM knowledge_edges").fetchone()[0] == 1

    result = await store.erase_person_data(user_id="user", platform="qq")

    assert result["ok"] is True
    assert result["deleted"]["knowledge_nodes"] >= 2
    labels = node_labels(store)
    assert item.content not in labels
    assert "user" not in labels
    assert store._conn.execute("SELECT COUNT(*) FROM knowledge_edges").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_erase_keeps_knowledge_nodes_shared_with_another_person(store):
    mine = record(memory_id="mem-mine", content="用户喜欢辣味。")
    other = record(memory_id="mem-other", user_id="other", content="别人喜欢甜味。")
    await store.insert_memory(mine)
    await store.insert_memory(other)
    shared = await store.upsert_knowledge_node(node_type="topic", label="口味", scope="private")
    my_node = await store.upsert_knowledge_node(
        node_type="memory", label=mine.content, scope="private", metadata={"memory_id": mine.id}
    )
    other_node = await store.upsert_knowledge_node(
        node_type="memory", label=other.content, scope="private", metadata={"memory_id": other.id}
    )
    await store.upsert_knowledge_edge(
        source_node_id=my_node,
        target_node_id=shared,
        relation_type="mentions",
        scope="private",
        source_memory_id=mine.id,
    )
    await store.upsert_knowledge_edge(
        source_node_id=other_node,
        target_node_id=shared,
        relation_type="mentions",
        scope="private",
        source_memory_id=other.id,
    )

    await store.erase_person_data(user_id="user", platform="qq")

    labels = node_labels(store)
    assert mine.content not in labels
    assert other.content in labels
    assert "口味" in labels, "被别人的记忆共用的节点不能跟着删掉"
    remaining = store._conn.execute("SELECT source_memory_id FROM knowledge_edges").fetchall()
    assert {row["source_memory_id"] for row in remaining} == {other.id}


@pytest.mark.asyncio
async def test_erase_removes_correction_receipts_that_quote_the_memory(store):
    old = record()
    await store.insert_memory(old)
    await store.correct_user_memory(
        context(),
        memory_id=old.id,
        expected_version=memory_ref(old)["version"],
        correction_id="change-1",
        content="用户喜欢清淡口味。",
        trace_id="trace-1",
    )
    assert store._conn.execute("SELECT COUNT(*) FROM memory_correction_receipts").fetchone()[0] == 1

    result = await store.erase_person_data(user_id="user", platform="qq")

    assert result["deleted"]["memory_correction_receipts"] == 1
    assert store._conn.execute("SELECT COUNT(*) FROM memory_correction_receipts").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_erase_removes_only_this_users_injection_logs(store):
    await store.add_injection_log(
        session_id="qq:GroupMessage:g1",
        scope="group",
        query="用户喜欢什么",
        selected_memory_ids=["mem-old"],
        blocked_reasons=[],
        injection_chars=12,
        user_id="user",
        bot_id="bot",
    )
    await store.add_injection_log(
        session_id="qq:GroupMessage:g1",
        scope="group",
        query="别人喜欢什么",
        selected_memory_ids=[],
        blocked_reasons=[],
        injection_chars=3,
        user_id="other",
        bot_id="bot",
    )
    await store.add_injection_log(
        session_id="qq:GroupMessage:user-legacy",
        scope="group",
        query="旧数据没有 user_id",
        selected_memory_ids=[],
        blocked_reasons=[],
        injection_chars=1,
    )

    result = await store.erase_person_data(user_id="user", platform="qq")

    rows = store._conn.execute("SELECT user_id, session_id FROM injection_logs").fetchall()
    assert [row["user_id"] for row in rows] == ["other"]
    assert result["deleted"]["injection_logs"] == 2


@pytest.mark.asyncio
async def test_erase_does_not_touch_another_persons_memories_or_nodes(store):
    mine = record(memory_id="mem-mine")
    other = record(memory_id="mem-other", user_id="other", content="别人喜欢甜味。")
    await store.insert_memory(mine)
    await store.insert_memory(other)
    await store.upsert_knowledge_node(
        node_type="person", label="other", scope="private", metadata={"source_memory_id": other.id}
    )
    await store.upsert_knowledge_node(
        node_type="person", label="user", scope="private", metadata={"source_memory_id": mine.id}
    )

    await store.erase_person_data(user_id="user", platform="qq")

    remaining = {
        row["id"]
        for row in store._conn.execute("SELECT id FROM memories").fetchall()
    }
    assert remaining == {other.id}
    assert "other" in node_labels(store)


def test_initialize_migrates_legacy_injection_logs_table(tmp_path):
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE injection_logs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                selected_memory_ids TEXT NOT NULL DEFAULT '[]',
                blocked_reasons TEXT NOT NULL DEFAULT '[]',
                injection_chars INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO injection_logs(id, session_id) VALUES('inj_legacy','qq:FriendMessage:user')"
        )
        conn.commit()
    finally:
        conn.close()

    store = MemoryStore(db_path)
    store.initialize()
    try:
        columns = {
            row["name"]
            for row in store._conn.execute("PRAGMA table_info(injection_logs)").fetchall()
        }
        assert {"user_id", "bot_id"} <= columns
        row = store._conn.execute(
            "SELECT user_id, bot_id FROM injection_logs WHERE id='inj_legacy'"
        ).fetchone()
        assert row["user_id"] == "" and row["bot_id"] == ""
    finally:
        store.close()


@pytest.mark.asyncio
async def test_legacy_injection_log_without_owner_is_still_erased_by_session(store):
    store._conn.execute(
        "INSERT INTO injection_logs(id, session_id, scope, query, selected_memory_ids, "
        "blocked_reasons, injection_chars, created_at) "
        "VALUES('inj_old','qq:GroupMessage:user','group','旧日志','[]','[]',1,'2026-01-01')"
    )
    store._conn.commit()

    result = await store.erase_person_data(user_id="user", platform="qq")

    assert result["deleted"]["injection_logs"] == 1
    assert store._conn.execute("SELECT COUNT(*) FROM injection_logs").fetchone()[0] == 0
