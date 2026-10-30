"""吸收外部关系插件递来的 <relation> 提示（纯文本、无数据库）。"""
from __future__ import annotations

import unittest
from datetime import datetime

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.absorb import (
    RELATION_BLOCK_RE,
    RELATION_SOURCE_CONTEXT,
    RELATION_SOURCE_USER,
    merge_relation_profile,
    parse_relation_hints,
    relation_from_phrase,
)

# user_tag 插件拼出来的标准块：称呼「灰凝」，关系「病娇」，外加一句备注。
STANDARD_BLOCK = (
    "<relation>我在灰凝面前就是病娇：黏人又爱吃醋。"
    "他补的一句：别在灰凝面前提她前任。以本条为准。</relation>"
)


class RelationPhraseTests(unittest.TestCase):
    def test_standard_phrase_yields_relation_and_address(self) -> None:
        self.assertEqual(relation_from_phrase("我在灰凝面前就是病娇"), ("病娇", "灰凝"))

    def test_punctuation_is_trimmed(self) -> None:
        self.assertEqual(
            relation_from_phrase("我在「灰凝」面前就是「病娇」。"),
            ("病娇", "灰凝"),
        )

    def test_pronoun_address_is_not_a_name(self) -> None:
        # 「他」是代词不是称呼；关系名仍然要留下。
        self.assertEqual(relation_from_phrase("我在他面前就是朋友"), ("朋友", ""))

    def test_clause_without_perspective_yields_empty(self) -> None:
        # 没有视角句就分不清哪半是关系名、哪半是称呼——宁可不记，也不瞎猜。
        self.assertEqual(relation_from_phrase("恋人"), ("", ""))
        self.assertEqual(relation_from_phrase("恋人：她是我恋人。"), ("", ""))
        self.assertEqual(relation_from_phrase(""), ("", ""))
        self.assertEqual(relation_from_phrase(None), ("", ""))

    def test_relation_and_address_lengths_are_capped(self) -> None:
        relation, address = relation_from_phrase("我在" + "灰" * 60 + "面前就是" + "病" * 60)
        self.assertEqual(len(relation), 40)
        self.assertEqual(len(address), 40)


class ParseRelationHintsTests(unittest.TestCase):
    def test_standard_block_parses_relation_and_address(self) -> None:
        self.assertIsNotNone(RELATION_BLOCK_RE.search(STANDARD_BLOCK))
        hints = parse_relation_hints([STANDARD_BLOCK])
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["relation"], "病娇")
        self.assertEqual(hints[0]["address"], "灰凝")
        self.assertEqual(hints[0]["source"], RELATION_SOURCE_CONTEXT)

    def test_block_spanning_multiple_lines_is_matched(self) -> None:
        block = (
            "<relation>\n我在灰凝面前就是病娇：\n黏人。\n"
            "他补的一句：别惹她。\n以本条为准。\n</relation>"
        )
        hints = parse_relation_hints([block])
        self.assertEqual(len(hints), 1)
        self.assertEqual(
            (hints[0]["relation"], hints[0]["address"], hints[0]["note"]),
            ("病娇", "灰凝", "别惹她"),
        )

    def test_note_is_extracted_without_trailing_period(self) -> None:
        hints = parse_relation_hints([STANDARD_BLOCK])
        self.assertEqual(hints[0]["note"], "别在灰凝面前提她前任")

    def test_missing_note_is_empty(self) -> None:
        hints = parse_relation_hints(
            ["<relation>我在灰凝面前就是恋人：关系很好。以本条为准。</relation>"]
        )
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["relation"], "恋人")
        self.assertEqual(hints[0]["note"], "")

    def test_multiple_texts_and_duplicate_blocks_are_deduped(self) -> None:
        duplicate = (
            "<relation>我在灰凝面前就是病娇：另一段重复块。"
            "他补的一句：后到的备注。以本条为准。</relation>"
        )
        hints = parse_relation_hints(
            [
                "系统提示里先塞了一段：" + STANDARD_BLOCK,
                "extra_user_content_parts 里又塞了一段：" + duplicate,
            ]
        )
        # 同一个 (relation, address) 只留第一次出现的：备注不能被后到的块覆盖。
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["note"], "别在灰凝面前提她前任")

    def test_multiple_distinct_blocks_in_one_text_are_all_parsed(self) -> None:
        text = (
            "<relation>我在灰凝面前就是病娇：很黏人。以本条为准。</relation>\n"
            "<relation>我在他面前就是朋友：普通朋友。以本条为准。</relation>"
        )
        hints = parse_relation_hints([text])
        self.assertEqual(
            [(hint["relation"], hint["address"]) for hint in hints],
            [("病娇", "灰凝"), ("朋友", "")],
        )

    def test_non_string_and_empty_inputs_are_safe(self) -> None:
        self.assertEqual(parse_relation_hints([]), [])
        self.assertEqual(parse_relation_hints(()), [])
        self.assertEqual(parse_relation_hints(None), [])
        self.assertEqual(parse_relation_hints(""), [])
        self.assertEqual(
            parse_relation_hints(
                [None, 123, "<relation>我在灰凝面前就是病娇</relation>".encode("utf-8"), {}, []]
            ),
            [],
        )
        self.assertEqual(parse_relation_hints(["没有关系块的一段话。"]), [])

    def test_unclosed_or_illegal_blocks_do_not_raise(self) -> None:
        texts = [
            "<relation>我在灰凝面前就是病娇：没有闭合",
            "</relation>我在灰凝面前就是病娇",
            "<relation></relation>",
            "<relation>恋人：她是我恋人。以本条为准。</relation>",
            "<relation>我在他面前就是：缺关系名。以本条为准。</relation>",
        ]
        self.assertEqual(parse_relation_hints(texts), [])

    def test_relation_address_and_note_lengths_are_capped(self) -> None:
        block = (
            "<relation>我在" + "灰" * 60 + "面前就是" + "病" * 60
            + "：描述。他补的一句：" + "备" * 120 + "。以本条为准。</relation>"
        )
        hints = parse_relation_hints([block])
        self.assertEqual(len(hints), 1)
        self.assertEqual(len(hints[0]["relation"]), 40)
        self.assertEqual(len(hints[0]["address"]), 40)
        self.assertEqual(len(hints[0]["note"]), 80)


class MergeRelationProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hint = parse_relation_hints([STANDARD_BLOCK])[0]
        self.old = {
            "display_name": "灰凝",
            "relation_label": "朋友",
            "relation_address": "灰凝",
            "relation_note": "旧备注",
            "relation_source": RELATION_SOURCE_CONTEXT,
            "relation_seen_at": "2026-10-01T08:00:00+00:00",
        }

    def test_merge_writes_relation_fields_without_mutating_inputs(self) -> None:
        before = dict(self.old)
        merged = merge_relation_profile(self.old, self.hint)

        self.assertEqual(self.old, before)  # 入参没被改
        self.assertIsNot(merged, self.old)
        self.assertEqual(merged["relation_label"], "病娇")
        self.assertEqual(merged["relation_address"], "灰凝")
        self.assertEqual(merged["relation_note"], "别在灰凝面前提她前任")
        self.assertEqual(merged["relation_source"], RELATION_SOURCE_CONTEXT)
        self.assertNotEqual(merged["relation_seen_at"], self.old["relation_seen_at"])
        # profile 里的其他键原样带走，不做删减。
        self.assertEqual(merged["display_name"], "灰凝")

    def test_empty_hint_fields_do_not_override_old_values(self) -> None:
        hint = {"relation": "", "address": "", "note": "", "source": RELATION_SOURCE_CONTEXT}
        merged = merge_relation_profile(self.old, hint)

        self.assertEqual(merged["relation_label"], "朋友")
        self.assertEqual(merged["relation_address"], "灰凝")
        self.assertEqual(merged["relation_note"], "旧备注")
        self.assertEqual(merged["relation_seen_at"], self.old["relation_seen_at"])

    def test_user_declared_relation_wins_over_context_inference(self) -> None:
        user_profile = dict(
            self.old,
            relation_label="恋人",
            relation_note="她亲口说的",
            relation_source=RELATION_SOURCE_USER,
        )
        merged = merge_relation_profile(user_profile, self.hint)

        self.assertEqual(merged["relation_label"], "恋人")
        self.assertEqual(merged["relation_address"], "灰凝")
        self.assertEqual(merged["relation_note"], "她亲口说的")
        self.assertEqual(merged["relation_source"], RELATION_SOURCE_USER)
        self.assertEqual(merged["relation_seen_at"], user_profile["relation_seen_at"])

    def test_merge_into_empty_profile_creates_fields(self) -> None:
        merged = merge_relation_profile({}, self.hint)

        self.assertEqual(merged["relation_label"], "病娇")
        self.assertEqual(merged["relation_address"], "灰凝")
        self.assertEqual(merged["relation_note"], "别在灰凝面前提她前任")
        self.assertEqual(merged["relation_source"], RELATION_SOURCE_CONTEXT)

    def test_relation_seen_at_is_iso_with_timezone(self) -> None:
        merged = merge_relation_profile({}, self.hint)
        seen = merged["relation_seen_at"]

        parsed = datetime.fromisoformat(seen)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)
        self.assertRegex(seen, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_non_mapping_inputs_are_tolerated(self) -> None:
        self.assertEqual(merge_relation_profile(None, None), {})


if __name__ == "__main__":
    unittest.main()
