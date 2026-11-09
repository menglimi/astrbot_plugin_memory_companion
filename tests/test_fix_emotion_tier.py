"""S9 回归：单条消息不能再把记忆推到 imprint（pinned / 永不归档）。

缺陷：core/memory_tier.py 里 `strong_type and intimate >= 1 -> imprint` 的短路径
让「她自己决定要记住的类型」+ 一个亲密词就直接钉成刻骨，判错一次就再也改不回来。
现在要求两个互相独立的信号。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.memory_tier import (  # noqa: E402
    TIER_IMPORTANT,
    TIER_IMPRINT,
    TIER_NORMAL,
    apply_tier_to_record,
    classify_tier,
)
from core.models import MemoryRecord  # noqa: E402


class SingleSignalCannotPinTests(unittest.TestCase):
    def test_strong_type_with_one_intimate_marker_is_not_imprint(self) -> None:
        # 旧行为：explicit_memory + 「亲你」→ imprint。这正是 S9 的短路径。
        self.assertEqual(
            TIER_IMPORTANT,
            classify_tier("她亲你了一下。", memory_type="explicit_memory"),
        )

    def test_strong_type_with_two_intimate_markers_is_imprint(self) -> None:
        self.assertEqual(
            TIER_IMPRINT,
            classify_tier("她抱着我，说到床上的时候声音很低。", memory_type="explicit_memory"),
        )

    def test_two_independent_signals_are_imprint(self) -> None:
        # 亲密 + 承诺：两个不同类别的信号，够刻骨。
        self.assertEqual(
            TIER_IMPRINT,
            classify_tier("我答应你，下次见面还这样亲你。", memory_type="explicit_memory"),
        )
        # 亲密 + 冲突：也是两个独立信号。
        self.assertEqual(
            TIER_IMPRINT,
            classify_tier("那天亲你之后我们吵架了。", memory_type="explicit_memory"),
        )

    def test_intimate_plus_conflict_in_summary_is_not_imprint(self) -> None:
        # 冲突词（生气/难过/哭）在摘要里太常见，亲密 + 冲突不足以钉成刻骨。
        self.assertEqual(
            TIER_NORMAL,
            classify_tier("她亲了你一下，你有点生气。", memory_type="conversation_summary"),
        )

    def test_one_intimate_marker_in_summary_is_still_normal(self) -> None:
        self.assertEqual(
            TIER_NORMAL,
            classify_tier("今天她说想早点上床睡觉。", memory_type="conversation_summary"),
        )

    def test_short_single_character_words_do_not_pin(self) -> None:
        # S9 的另一半：单字 marker 删掉以后，日常词不该被误判成刻骨。
        for text in ("胸口别着胸牌。", "最近脱发有点严重。", "她喜欢裸色口红。", "这张床太硬了。"):
            with self.subTest(text=text):
                self.assertEqual(TIER_NORMAL, classify_tier(text, memory_type="conversation_summary"))

    def test_single_message_cannot_reach_pinned_durability(self) -> None:
        record = MemoryRecord(content="她亲你了一下。", memory_type="explicit_memory")
        tier = apply_tier_to_record(record)
        self.assertEqual(TIER_IMPORTANT, tier)
        self.assertNotEqual("pinned", record.durability)
        self.assertEqual("durable", record.durability)
        self.assertEqual(TIER_IMPORTANT, record.metadata.get("memory_tier"))

    def test_two_signal_message_still_reaches_pinned(self) -> None:
        record = MemoryRecord(content="我答应你，下次见面还这样亲你。", memory_type="explicit_memory")
        tier = apply_tier_to_record(record)
        self.assertEqual(TIER_IMPRINT, tier)
        self.assertEqual("pinned", record.durability)


if __name__ == "__main__":
    unittest.main()
