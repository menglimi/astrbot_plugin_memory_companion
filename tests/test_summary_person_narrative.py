"""2.4.0：摘要按人写（叙事落在人身上，不是一堆事件）。"""

from __future__ import annotations

import json
import unittest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer


def _row(event_id: str, subject_id: str, name: str, content: str, when: str = "2026-10-01 20:00:00") -> dict:
    return {
        "id": event_id,
        "event_type": "message",
        "subject_id": subject_id,
        "metadata": json.dumps({"sender_name": name}, ensure_ascii=False),
        "occurred_at": when,
        "created_at": when,
        "content": content,
        "scope": "group",
    }


class SummaryPersonNarrativeTests(unittest.TestCase):
    def prompt(self) -> str:
        summarizer = MemorySummarizer()
        rows = [
            _row("e1", "u1", "阿哲", "我在阿莉娜面前就是恋人，叫我阿哲就好。"),
            _row("e2", "u2", "小李", "阿哲昨晚又熬夜了，劝他早点睡。"),
        ]
        return summarizer._build_prompt(rows, "qq 群聊")

    def test_prompt_asks_for_people_not_a_pile_of_events(self) -> None:
        prompt = self.prompt()

        self.assertIn("按人分开写", prompt)
        self.assertIn("不要混成「大家」「有人」", prompt)
        self.assertIn("Bot 自己的事写在她自己身上", prompt)

    def test_transcript_keeps_who_said_what(self) -> None:
        prompt = self.prompt()

        self.assertIn("阿哲", prompt)
        self.assertIn("小李", prompt)
        # 说话人 ID 必须在材料里，摘要才有办法把事实贴回人身上。
        self.assertIn("u1", prompt)
        self.assertIn("u2", prompt)


if __name__ == "__main__":
    unittest.main()