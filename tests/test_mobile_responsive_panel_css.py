"""Mobile viewport layout and zero-horizontal-overflow contracts for app.css and people.css."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "pages" / "记忆面板"
APP_CSS = PANEL_DIR / "app.css"
PEOPLE_CSS = PANEL_DIR / "people.css"


def _extract_balanced_block(source: str, header_pattern: str) -> str:
    match = re.search(header_pattern, source)
    if match is None:
        raise AssertionError(f"missing CSS block matching: {header_pattern}")
    start = match.end()
    depth = 1
    idx = start
    while idx < len(source) and depth > 0:
        ch = source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        idx += 1
    if depth != 0:
        raise AssertionError(f"unbalanced braces in CSS block: {header_pattern}")
    return source[start : idx - 1]


class MobileResponsivePanelCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app_css = APP_CSS.read_text(encoding="utf-8")
        cls.people_css = PEOPLE_CSS.read_text(encoding="utf-8")
        cls.app_mobile = _extract_balanced_block(
            cls.app_css,
            r"/\*\s*-+\s*4\.\s*移动端\s*-+\s*\*/\s*@media\s*\(max-width:\s*640px\)\s*\{",
        )
        cls.people_mobile = _extract_balanced_block(
            cls.people_css,
            r"@media\s*\(max-width:\s*720px\)\s*\{",
        )

    def test_app_css_mobile_unlocks_vertical_scroll_and_safe_area(self) -> None:
        html_body = re.search(r"html,\s*body\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(html_body, "<=640px 必须覆盖 html, body 解锁整页垂直滚动")
        body_rules = html_body.group(1)
        self.assertIn("height: auto;", body_rules)
        self.assertIn("min-height: 100%;", body_rules)
        self.assertIn("overflow-x: hidden;", body_rules)
        self.assertIn("overflow-y: auto;", body_rules)

        shell_rule = re.search(r"\.shell\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(shell_rule)
        self.assertIn("min-height: 100dvh;", shell_rule.group(1))

        content_rule = re.search(r"\.content\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(content_rule)
        self.assertIn("overflow: visible;", content_rule.group(1))

        rail_rule = re.search(r"\.rail\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(rail_rule)
        self.assertIn("env(safe-area-inset-bottom)", rail_rule.group(1))

        main_rule = re.search(r"\.main\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(main_rule)
        self.assertIn("env(safe-area-inset-bottom)", main_rule.group(1))

    def test_app_css_mobile_restores_nav_sub_label_text_and_safe_bottom_offset(self) -> None:
        nav_subs = re.search(r"\.nav-subs\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(nav_subs)
        self.assertIn("bottom: calc(58px + env(safe-area-inset-bottom));", nav_subs.group(1))

        nav_sub = re.search(r"\.nav-sub\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(nav_sub)
        rules = nav_sub.group(1)
        self.assertIn("font-size: 12.5px;", rules)
        self.assertIn("line-height: 1.3;", rules)
        self.assertIn("gap: 6px;", rules)
        self.assertIn("white-space: nowrap;", rules)
        self.assertIn("min-height: 34px;", rules)

    def test_app_css_mobile_wraps_card_head_and_actions(self) -> None:
        card_head = re.search(r"\.card-head\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(card_head)
        self.assertIn("flex-wrap: wrap;", card_head.group(1))
        self.assertIn("gap: 8px;", card_head.group(1))

        head_actions = re.search(r"\.card-head-actions\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(head_actions)
        self.assertIn("width: 100%;", head_actions.group(1))
        self.assertIn("flex-wrap: wrap;", head_actions.group(1))

    def test_people_css_prevents_grid_and_webkit_box_horizontal_overflow(self) -> None:
        self.assertIn(
            "grid-template-columns: repeat(auto-fill, minmax(min(340px, 100%), 1fr));",
            self.people_css,
        )
        card_rule = re.search(r"^\.card\s*\{([^}]*)\}", self.people_css, re.M)
        self.assertIsNotNone(card_rule)
        for decl in ("width: 100%;", "min-width: 0;", "max-width: 100%;", "overflow: hidden;"):
            self.assertIn(decl, card_rule.group(1))

        who_rule = re.search(r"^\.who\s*\{([^}]*)\}", self.people_css, re.M)
        self.assertIsNotNone(who_rule)
        self.assertIn("min-width: 0;", who_rule.group(1))
        self.assertIn("overflow: hidden;", who_rule.group(1))

        memories_rule = re.search(r"^\.memories\s*\{([^}]*)\}", self.people_css, re.M)
        self.assertIsNotNone(memories_rule)
        for decl in ("grid-template-columns: minmax(0, 1fr);", "min-width: 0;", "width: 100%;", "max-width: 100%;"):
            self.assertIn(decl, memories_rule.group(1))

        memories_li = re.search(r"^\.memories li\s*\{([^}]*)\}", self.people_css, re.M)
        self.assertIsNotNone(memories_li)
        self.assertNotIn("-webkit-box", memories_li.group(1), "不应再使用 -webkit-box 触发 Chromium min-content 溢出")
        for decl in ("display: block;", "min-width: 0;", "max-width: 100%;", "white-space: nowrap;", "overflow: hidden;", "text-overflow: ellipsis;"):
            self.assertIn(decl, memories_li.group(1))

        for selector, expected in (
            (r"^\.brand > div\s*\{([^}]*)\}", ("min-width: 0;",)),
            (r"^\.tools select\s*\{([^}]*)\}", ("max-width: 100%;", "min-width: 0;")),
            (r"^\.chips\s*\{([^}]*)\}", ("min-width: 0;", "width: 100%;", "max-width: 100%;")),
            (r"^\.chip\s*\{([^}]*)\}", ("max-width: 100%;", "overflow-wrap: anywhere;")),
            (r"^\.meta\s*\{([^}]*)\}", ("max-width: 100%;", "overflow-wrap: anywhere;")),
            (r"^\.person-head > div\s*\{([^}]*)\}", ("min-width: 0;",)),
            (r"^\.detail-list \.text\s*\{([^}]*)\}", ("overflow-wrap: anywhere;",)),
            (r"^\.toast\s*\{([^}]*)\}", ("max-width: calc(100vw - 24px);",)),
            (r"^\.drawer\s*\{([^}]*)\}", ("width: min(520px, 100%);", "height: 100dvh;")),
        ):
            m = re.search(selector, self.people_css, re.M)
            self.assertIsNotNone(m, f"people.css 缺少规则: {selector}")
            for decl in expected:
                self.assertIn(decl, m.group(1), f"{selector} 缺少声明: {decl}")

        # Mobile <=720px media query uses minmax(0, 1fr) and full-width search bar
        self.assertIn("grid-template-columns: minmax(0, 1fr);", self.people_mobile)
        self.assertNotIn("grid-template-columns: 1fr;", self.people_mobile)
        self.assertIn("flex: 1 1 100%;", self.people_mobile)
        self.assertIn("padding: 16px 14px 10px;", self.people_mobile)
        self.assertIn("env(safe-area-inset-bottom)", self.people_mobile)


if __name__ == "__main__":
    unittest.main()
