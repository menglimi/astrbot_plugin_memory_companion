from __future__ import annotations

import unittest

from .package_bootstrap import bootstrap_package

bootstrap_package()

from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SearchResult, SessionContext


class InjectionFactSelectionTests(unittest.TestCase):
    def test_query_relevant_fact_is_rendered_whole_within_item_budget(self) -> None:
        query = "蓝色文件夹放在哪里？"
        target = "蓝色文件夹放在书桌抽屉里。"
        memory = MemoryRecord(
            id="fact-selection",
            memory_type="explicit_memory",
            subject=EntityRef(kind="user", id="u1", name="小王"),
            object=EntityRef.bot_self("b1"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            platform="qq",
            visibility="private_pair",
            lifecycle="stable_memory",
            content="小王的几项稳定信息。",
            confidence=0.95,
            importance=0.9,
            metadata={
                "key_facts": [
                    "小王喜欢无糖拿铁，也会在周末去爬山。",
                    "小王最近在整理书架并收集旧书。",
                    target,
                ]
            },
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_text=query,
        )

        injected = InjectionComposer().compose(
            ctx,
            [SearchResult(memory=memory, score=0.9, reason="expression=mention")],
            max_chars=1800,
            max_item_chars=48,
        )

        self.assertIn(target, injected)

    def test_unmatched_facts_keep_original_order_and_are_not_partially_cut(self) -> None:
        composer = InjectionComposer()

        selected = composer._select_key_facts_for_query(
            ["第一条完整事实。", "第二条完整事实。"],
            query_text="没有对应的查询线索",
            max_chars=12,
        )

        self.assertEqual("第一条完整事实。", selected)


if __name__ == "__main__":
    unittest.main()
