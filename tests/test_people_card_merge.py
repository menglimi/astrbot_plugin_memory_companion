# -*- coding: utf-8 -*-
"""人物面板：同一个人只出一张卡（按 user_id 合并 bot/平台多行）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.store import MemoryStore  # noqa: E402


def _record(doc_id: str, user_id: str, content: str):
    from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord

    return MemoryRecord(
        id=doc_id,
        memory_type="conversation_summary",
        subject=EntityRef(kind="user", id=user_id),
        object=EntityRef(kind="bot", id="bot-a"),
        platform="qq",
        scope="private",
        visibility="private_pair",
        lifecycle="stable_memory",
        owner_bot_id="bot-a",
        durability="normal",
        content=content,
        occurred_at="",
    )


class PeopleCardMergeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory_companion.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def test_same_user_across_bots_and_platforms_gets_one_card(self) -> None:
        user = "302578963"
        await self.store.insert_memory(_record("m1", user, "她记得我。"))
        # 真实数据库里的 6 行：空 bot_id / QQ / 飞书 / 导入来源，各算一份分量
        for bot_id, platform in (
            ("470488586", "qq"),
            ("", "qq"),
            ("ou_7857268f", "lark"),
            ("", "lark"),
            ("", ""),
            ("", "livingmemory"),
        ):
            await self.store.person_weight(user_id=user, platform=platform, bot_id=bot_id)

        data = await self.store.list_person_cards()
        self.assertEqual(1, data["total"], "同一个人不应该拆成多张卡")
        card = data["items"][0]
        self.assertEqual(user, card["user_id"])
        self.assertGreaterEqual(len(card["platforms"]), 2)
        self.assertIn("qq", card["platforms"])
        self.assertIn("lark", card["platforms"])
        bot_counts = {item["bot_id"]: item["people"] for item in data["bots"]}
        self.assertEqual(1, bot_counts[""])
        self.assertEqual(1, bot_counts["470488586"])
        self.assertEqual(1, bot_counts["ou_7857268f"])

    async def test_bot_filter_still_works(self) -> None:
        await self.store.insert_memory(_record("m1", "u1", "记得。"))
        await self.store.person_weight(user_id="u1", platform="qq", bot_id="bot-a")
        await self.store.person_weight(user_id="u1", platform="qq", bot_id="bot-b")

        only_a = await self.store.list_person_cards(bot_id="bot-a")
        self.assertEqual(["u1"], [item["user_id"] for item in only_a["items"]])
        self.assertEqual(1, only_a["total"])

    async def test_different_people_stay_separate(self) -> None:
        await self.store.insert_memory(_record("m1", "u1", "甲。"))
        await self.store.insert_memory(_record("m2", "u2", "乙。"))
        await self.store.person_weight(user_id="u1", platform="qq", bot_id="bot-a")
        await self.store.person_weight(user_id="u2", platform="qq", bot_id="bot-a")

        data = await self.store.list_person_cards(bot_id="bot-a")
        self.assertEqual(2, data["total"])
        self.assertEqual({"u1", "u2"}, {item["user_id"] for item in data["items"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
