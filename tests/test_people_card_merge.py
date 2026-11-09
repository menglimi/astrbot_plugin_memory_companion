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

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord  # noqa: E402
from astrbot_plugin_memory_companion.core.store import MemoryStore  # noqa: E402


def _record(
    doc_id: str,
    user_id: str,
    content: str,
    *,
    owner_bot_id: str = "bot-a",
    platform: str = "qq",
):
    return MemoryRecord(
        id=doc_id,
        memory_type="conversation_summary",
        subject=EntityRef(kind="user", id=user_id),
        object=EntityRef(kind="bot", id=owner_bot_id or "none"),
        platform=platform,
        scope="private",
        visibility="private_pair",
        lifecycle="stable_memory",
        owner_bot_id=owner_bot_id,
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

    async def test_bot_tabs_count_each_person_once(self) -> None:
        # 同一个人、同一个 bot、两个平台：下拉框的「N 人」要按人算，不按行算。
        await self.store.insert_memory(_record("m1", "u1", "记得。"))
        await self.store.person_weight(user_id="u1", platform="qq", bot_id="bot-a")
        await self.store.person_weight(user_id="u1", platform="lark", bot_id="bot-a")

        data = await self.store.list_person_cards()
        self.assertEqual(1, data["total"])
        self.assertEqual([{"bot_id": "bot-a", "people": 1}], data["bots"])

    async def test_merged_card_counts_memories_across_bots(self) -> None:
        # 合并后的卡代表「这个人」，件事数要把各个 bot 的桶加在一起，
        # 否则会出现「1 件事」配着两条最近记忆。
        await self.store.insert_memory(_record("m1", "u1", "甲。", owner_bot_id="bot-a"))
        await self.store.insert_memory(_record("m2", "u1", "乙。", owner_bot_id=""))
        await self.store.person_weight(user_id="u1", platform="qq", bot_id="bot-a")
        await self.store.person_weight(user_id="u1", platform="", bot_id="")

        card = (await self.store.list_person_cards())["items"][0]
        self.assertEqual(2, card["memory_count"])
        self.assertEqual(len(card["top"]), card["memory_count"])

        # 按 bot 筛选时仍然只算这个 bot 的记忆，和筛选语义保持一致。
        scoped = (await self.store.list_person_cards(bot_id="bot-a"))["items"][0]
        self.assertEqual(1, scoped["memory_count"])

    async def test_card_follows_the_heaviest_row(self) -> None:
        await self.store.insert_memory(
            _record("m1", "u1", "甲。", owner_bot_id="bot-a", platform="qq")
        )
        await self.store.insert_memory(
            _record("m2", "u1", "乙。", owner_bot_id="", platform="lark")
        )
        await self.store.person_weight(user_id="u1", platform="qq", bot_id="bot-a")
        await self.store.person_weight(user_id="u1", platform="lark", bot_id="")
        await self.store.set_person_weight(
            user_id="u1", weight=60, platform="qq", bot_id="bot-a"
        )
        await self.store.set_person_weight(
            user_id="u1", weight=20, platform="lark", bot_id=""
        )

        card = (await self.store.list_person_cards())["items"][0]
        self.assertEqual("bot-a", card["bot_id"])
        self.assertEqual("qq", card["platform"])
        self.assertEqual(60, card["weight"])
        self.assertEqual(["qq", "lark"], card["platforms"])
        self.assertEqual(["bot-a"], card["bot_ids"])

    async def test_detail_keeps_the_name_for_import_platforms(self) -> None:
        # 主行落在导入来源（livingmemory）上时，按平台查不到 identities，
        # 详情页不该把名字退化成 user_id。
        await self.store.insert_memory(
            _record("m1", "u1", "记得。", owner_bot_id="", platform="livingmemory")
        )
        await self.store.upsert_identity(
            platform="qq", entity=EntityRef(kind="user", id="u1", name="小王")
        )
        await self.store.person_weight(user_id="u1", platform="livingmemory", bot_id="")

        card = (await self.store.list_person_cards())["items"][0]
        self.assertEqual("livingmemory", card["platform"])
        detail = await self.store.person_panel_detail(
            user_id=card["user_id"], platform=card["platform"], bot_id=card["bot_id"]
        )
        self.assertEqual("小王", detail["display_name"])
        self.assertEqual("qq", detail["platform"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
