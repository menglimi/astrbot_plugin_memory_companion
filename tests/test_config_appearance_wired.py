"""配置项不许是「配了没用」。

这一版的起因是用户发现 ``appearance.theme``（14 个中国传统色）怎么配都不生效。
查下来是：配置里有、后端也把色名映射成了 key，但**前端从来没有消费过那个 key**，
项目里甚至不存在任何一份配色定义——一个纯粹的空壳配置项。

光修这一次不够，下次加配置的人照样会忘。所以这里立一条通用规矩：

    凡是 schema 里声明成「选项列表」的键，必须同时满足
      1. 后端有 name -> key 的映射；
      2. app.css 里有对应的 [data-palette="key"] 规则；
      3. 前端把 key 打到 DOM 上（data-palette）。
    少任何一条，测试就红。

这样以后再加配色选项，忘了写 CSS 会立刻被拦下，而不是等用户来报「没生效」。
"""

from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "_conf_schema.json"
PAGE_API = ROOT / "page_api.py"
PANEL = ROOT / "pages" / "记忆面板"
APP_CSS = PANEL / "app.css"
APP_JS = PANEL / "app.js"
INDEX_HTML = PANEL / "index.html"


def _theme_map() -> dict[str, str]:
    """从 page_api.py 的 AST 里取 THEME_NAME_TO_KEY，不导入模块（避免依赖宿主 astrbot）。"""
    tree = ast.parse(PAGE_API.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if not isinstance(target, ast.Name) or target.id != "THEME_NAME_TO_KEY":
            continue
        return {
            k.value: v.value
            for k, v in zip(node.value.keys, node.value.values)
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
        }
    return {}


class SchemaIsWellFormedTests(unittest.TestCase):
    """配置 schema 本身的形状检查。

    这里查的不是「键有没有被读」，而是**文件本身有没有坏**：
    ``memory_summary.candidate_valid_days`` 曾经在 JSON 里出现了两次
    （逐字相同）。JSON 允许重复键、后者覆盖前者，所以 AstrBot 读到的永远是
    第二份，第一份纯属噪音；而任何按行 diff 的人工审计都会把它当成两个不同的项，
    或者干脆漏掉。重复键不会有任何报错，只会在有人改其中一份时静默失效。
    """

    RAW = SCHEMA.read_text(encoding="utf-8")

    def test_no_duplicate_keys_anywhere(self) -> None:
        import collections

        def hook(pairs):
            counts = collections.Counter(key for key, _ in pairs)
            dupes = [key for key, n in counts.items() if n > 1]
            if dupes:
                raise AssertionError(f"重复键: {dupes}")
            return dict(pairs)

        json.loads(self.RAW, object_pairs_hook=hook)

    def test_every_leaf_declares_a_type_and_a_default(self) -> None:
        schema = json.loads(self.RAW)
        problems: list[str] = []
        for group, body in schema.items():
            self.assertEqual("object", body.get("type"), group)
            for key, item in body["items"].items():
                if item.get("type") not in {"int", "bool", "string", "float"}:
                    problems.append(f"{group}.{key} 缺 type")
                if "default" not in item:
                    problems.append(f"{group}.{key} 缺 default")
        self.assertEqual([], problems, f"{len(problems)} 个叶子项声明不完整")

    def test_option_lists_are_not_empty(self) -> None:
        """有 options 的键必须真的列出可选项，且默认值在其中。"""
        schema = json.loads(self.RAW)
        problems: list[str] = []
        for group, body in schema.items():
            for key, item in body["items"].items():
                options = item.get("options")
                if not options:
                    continue
                if item.get("default") not in options:
                    problems.append(f"{group}.{key} 默认值不在 options 里")
        self.assertEqual([], problems)


class AppearanceThemeIsActuallyWiredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.theme_item = cls.schema["appearance"]["items"]["theme"]
        cls.options = list(cls.theme_item["options"])
        cls.map = _theme_map()
        cls.css = APP_CSS.read_text(encoding="utf-8")
        cls.js = APP_JS.read_text(encoding="utf-8")
        cls.index = INDEX_HTML.read_text(encoding="utf-8")

    def test_every_declared_option_has_a_backend_key(self) -> None:
        self.assertEqual(
            sorted(self.options),
            sorted(self.map),
            "schema 里的配色选项与后端 THEME_NAME_TO_KEY 必须一一对应",
        )

    def test_default_option_is_in_the_map(self) -> None:
        self.assertIn(self.theme_item["default"], self.options, "默认值必须是自己选项之一")

    def test_every_backend_key_has_real_css(self) -> None:
        """这一条就是「配了没用」的那道闸。"""
        missing = [
            key for key in self.map.values()
            if f'[data-palette="{key}"]' not in self.css
        ]
        self.assertEqual([], missing, f"这些配色没有对应 CSS，配了不会变色：{missing}")

    def test_palette_covers_both_light_and_dark(self) -> None:
        missing = [
            key for key in self.map.values()
            if f'[data-palette="{key}"][data-theme="light"]' not in self.css
        ]
        self.assertEqual([], missing, f"这些配色缺浅色变体：{missing}")

    def test_palette_rules_actually_define_colors(self) -> None:
        """不能只写个空壳选择器糊弄过去。"""
        for key in self.map.values():
            m = re.search(
                r'\[data-palette="' + re.escape(key) + r'"\] \{([^}]*)\}', self.css
            )
            self.assertIsNotNone(m, key)
            decls = [d.strip() for d in m.group(1).split(";") if d.strip()]
            self.assertGreaterEqual(len(decls), 10, f"{key} 的配色块太空了")
            for needed in ("--bg:", "--surface:", "--text:", "--accent:"):
                self.assertTrue(
                    any(d.startswith(needed) for d in decls),
                    f"{key} 缺少 {needed}",
                )

    def test_frontend_actually_applies_the_key(self) -> None:
        self.assertIn("applyPalette", self.js, "app.js 必须有应用配色的函数")
        self.assertIn("dataset.palette", self.js, "app.js 必须把 key 写到 DOM 上")
        for key in self.map.values():
            self.assertRegex(self.js, rf'"{key}"', f"app.js 的白名单缺 {key}")
        # 首屏那一页也要在跳转前打上，否则会先闪一下默认色
        self.assertIn("applyPalette", self.index, "index.html 要在跳转前应用配色")

    def test_backend_serves_the_palette_key_to_the_first_screen(self) -> None:
        source = PAGE_API.read_text(encoding="utf-8")
        m = re.search(r"async def ui_preferences\(self\):(.*?)\n    async def ", source, re.S)
        self.assertIsNotNone(m, "找不到 ui_preferences")
        body = m.group(1)
        self.assertIn('"palette"', body, "ui-preferences 必须返回 palette")
        self.assertIn("appearance.theme", body, "ui-preferences 必须读 appearance.theme")


if __name__ == "__main__":
    unittest.main()
