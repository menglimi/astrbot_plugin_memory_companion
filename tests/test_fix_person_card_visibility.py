from __future__ import annotations

"""L14：人卡（person_snapshot）必须和 VisibilityPolicy 同一口径。

private 场景默认不看 group_public；只有 allow_group_public_in_private=True 才放行，
且群场景只看本群的 group_public。之前人卡自己写了一份 private 可见性 SQL，绕过了
这个开关，于是别的群里的 group_public 记忆会漏到私聊人卡上。
"""

from dataclasses import replace

import pytest

from core.models import EntityRef, MemoryRecord
from core.store import MemoryStore
from core.visibility import visibility_prefilter_sql


@pytest.fixture
def store(tmp_path):
    value = MemoryStore(tmp_path / "memory.db")
    value.initialize()
    yield value
    value.close()


def record(memory_id: str, *, scope: str, group_id: str, visibility: str, content: str):
    return replace(
        MemoryRecord(
            id=memory_id,
            memory_type="memory",
            subject=EntityRef(kind="user", id="user"),
            object=EntityRef(kind="bot", id="bot"),
            owner_bot_id="bot",
            scope=scope,
            group_id=group_id,
            platform="qq",
            session_id="qq:GroupMessage:" + (group_id or "user"),
            visibility=visibility,
            lifecycle="stable_memory",
            content=content,
            metadata={"owner_bot_id": "bot"},
        )
    ).ensure_defaults()


async def seed(store: MemoryStore) -> None:
    await store.insert_memory(record("mem-private", scope="private", group_id="", visibility="private_pair", content="私下说的。"))
    await store.insert_memory(record("mem-shareable", scope="private", group_id="", visibility="shareable", content="可以分享的。"))
    await store.insert_memory(record("mem-g1-public", scope="group", group_id="g1", visibility="group_public", content="G1 公开的。"))
    await store.insert_memory(record("mem-g2-public", scope="group", group_id="g2", visibility="group_public", content="G2 公开的。"))


def ids(snapshot: dict) -> set[str]:
    return {row["id"] for row in snapshot["memories"]}


def test_person_card_visibility_uses_the_shared_rule() -> None:
    for scope, group_id in (("private", ""), ("group", "g1"), ("", "")):
        for allow in (False, True):
            assert MemoryStore._person_snapshot_visibility_sql(scope, group_id, allow) == visibility_prefilter_sql(
                scope, group_id, allow_group_public_in_private=allow
            )


@pytest.mark.asyncio
async def test_private_card_hides_group_public_memories_by_default(store):
    await seed(store)
    snapshot = await store.person_snapshot(user_id="user", scope="private")
    assert ids(snapshot) == {"mem-private", "mem-shareable"}


@pytest.mark.asyncio
async def test_private_card_can_opt_into_group_public_memories(store):
    await seed(store)
    snapshot = await store.person_snapshot(
        user_id="user", scope="private", allow_group_public_in_private=True
    )
    assert ids(snapshot) == {"mem-private", "mem-shareable", "mem-g1-public", "mem-g2-public"}


@pytest.mark.asyncio
async def test_group_card_only_shows_its_own_group_public_memories(store):
    await seed(store)
    snapshot = await store.person_snapshot(user_id="user", scope="group", group_id="g1")
    assert ids(snapshot) == {"mem-shareable", "mem-g1-public"}
