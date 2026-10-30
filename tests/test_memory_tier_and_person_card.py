"""2.3.7：记得这个人（分层、人卡可见范围、旧数据补档）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.memory_tier import (
    TIER_IMPORTANT,
    TIER_IMPRINT,
    TIER_NORMAL,
    classify_tier,
)
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore

BOT_ID = "b1"


class MemoryTierTests(unittest.TestCase):
    def test_single_intimate_word_is_not_imprint(self) -> None:
        # 真实库里「床」「抱我」一天能出现几十次；一个词不该把摘要钉死。
        self.assertEqual(
            classify_tier("今天她说想早点上床睡觉。", memory_type="conversation_summary"),
            TIER_NORMAL,
        )

    def test_two_intimate_markers_are_imprint(self) -> None:
        self.assertEqual(
            classify_tier(
                "她抱着我，说到床上的时候声音很低。",
                memory_type="conversation_summary",
            ),
            TIER_IMPRINT,
        )

    def test_strong_type_with_one_intimate_marker_is_only_important(self) -> None:
        # S9：这条以前断言 imprint。但那正是缺陷本身——「她自己要记住的类型」
        # 加一个亲密词就把记忆钉成永不归档，一条消息判错就再也改不回来。
        # 现在要求两个独立信号，单信号只到 important。
        self.assertEqual(
            classify_tier("她亲你了一下。", memory_type="explicit_memory"),
            TIER_IMPORTANT,
        )

    def test_strong_type_with_two_independent_signals_is_imprint(self) -> None:
        self.assertEqual(
            classify_tier("我答应你，下次见面还这样亲你。", memory_type="explicit_memory"),
            TIER_IMPRINT,
        )

    def test_strong_type_alone_is_important(self) -> None:
        self.assertEqual(
            classify_tier("她住在杭州。", memory_type="assertion"),
            TIER_IMPORTANT,
        )

    def test_high_importance_alone_no_longer_promotes(self) -> None:
        # 真实库 68% 的行拥挤在 0.8-0.9，importance 抬档等于没有轻重。
        self.assertEqual(
            classify_tier("今天吃了面。", memory_type="conversation_summary", importance=0.95),
            TIER_NORMAL,
        )

    def test_protected_tag_still_imprint(self) -> None:
        self.assertEqual(
            classify_tier("随便一句话。", tags=["manual"]),
            TIER_IMPRINT,
        )


class PersonSnapshotVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory_companion.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def _insert(
        self,
        memory_id: str,
        *,
        content: str,
        scope: str,
        visibility: str,
        group_id: str = "",
        memory_type: str = "conversation_summary",
    ) -> None:
        await self.store.insert_memory(
            MemoryRecord(
                id=memory_id,
                memory_type=memory_type,
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef(kind="bot", id=BOT_ID),
                scope=scope,
                group_id=group_id,
                visibility=visibility,
                lifecycle="stable_memory",
                owner_bot_id=BOT_ID,
                content=content,
            )
        )

    async def test_group_card_does_not_leak_private_memories(self) -> None:
        await self._insert(
            "private-secret", content="私聊里她说她怕黑。", scope="private", visibility="private_pair"
        )
        await self._insert(
            "group-own",
            content="群里她说周末去爬山。",
            scope="group",
            visibility="group_public",
            group_id="g1",
        )
        await self._insert(
            "group-other",
            content="别的群里她说她要搬家。",
            scope="group",
            visibility="group_public",
            group_id="g2",
        )
        snapshot = await self.store.person_snapshot(
            user_id="u1", bot_id=BOT_ID, scope="group", group_id="g1"
        )
        ids = {row["id"] for row in snapshot["memories"]}
        self.assertIn("group-own", ids)
        self.assertNotIn("private-secret", ids)
        self.assertNotIn("group-other", ids)
        self.assertEqual(snapshot["total"], 1)

    async def test_private_card_keeps_private_memories(self) -> None:
        await self._insert(
            "private-secret", content="私聊里她说她怕黑。", scope="private", visibility="private_pair"
        )
        snapshot = await self.store.person_snapshot(
            user_id="u1", bot_id=BOT_ID, scope="private"
        )
        ids = {row["id"] for row in snapshot["memories"]}
        self.assertIn("private-secret", ids)

    async def test_unknown_scope_only_shareable(self) -> None:
        await self._insert(
            "private-secret", content="私聊里她说她怕黑。", scope="private", visibility="private_pair"
        )
        await self._insert(
            "shareable-one", content="她喜欢无糖拿铁。", scope="group", visibility="shareable"
        )
        snapshot = await self.store.person_snapshot(user_id="u1", bot_id=BOT_ID)
        ids = {row["id"] for row in snapshot["memories"]}
        self.assertEqual(ids, {"shareable-one"})


class MemoryTierBackfillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory_companion.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def _insert(self, memory_id: str, content: str, memory_type: str = "conversation_summary") -> None:
        await self.store.insert_memory(
            MemoryRecord(
                id=memory_id,
                memory_type=memory_type,
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef(kind="bot", id=BOT_ID),
                scope="private",
                visibility="private_pair",
                lifecycle="stable_memory",
                owner_bot_id=BOT_ID,
                content=content,
            )
        )

    def _reset_tier(self, memory_id: str) -> None:
        with self.store._lock:
            self.store._conn.execute(
                "UPDATE memories SET durability='normal', metadata='{}' WHERE id=?",
                (memory_id,),
            )
            self.store._conn.execute(
                "DELETE FROM schema_metadata WHERE key='memory_tier_backfill_version'"
            )
            self.store._conn.commit()

    def _durability(self, memory_id: str) -> str:
        with self.store._lock:
            row = self.store._conn.execute(
                "SELECT durability FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
        return str(row["durability"] if row else "")

    async def test_backfill_pins_imprint_without_touching_content(self) -> None:
        await self._insert("keep", "她抱着我，说到床上的时候声音很低。")
        await self._insert("daily", "今天吃了面。")
        self._reset_tier("keep")
        self._reset_tier("daily")

        changed = self.store._backfill_memory_tier_sync()

        self.assertGreaterEqual(changed, 1)
        self.assertEqual(self._durability("keep"), "pinned")
        self.assertEqual(self._durability("daily"), "normal")
        with self.store._lock:
            row = self.store._conn.execute(
                "SELECT content FROM memories WHERE id='keep'"
            ).fetchone()
        self.assertEqual(row["content"], "她抱着我，说到床上的时候声音很低。")

    async def test_backfill_is_idempotent(self) -> None:
        await self._insert("keep", "她抱着我，说到床上的时候声音很低。")
        self._reset_tier("keep")
        self.store._backfill_memory_tier_sync()
        self.assertEqual(self._durability("keep"), "pinned")
        self.assertEqual(self.store._backfill_memory_tier_sync(), 0)
