"""模块配置全中文美化、14 套浅色色板选中态对比度与全局配置搜索契约测试。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "pages" / "记忆面板"
SCHEMA = ROOT / "_conf_schema.json"
METADATA = ROOT / "metadata.yaml"
APP_JS = PANEL / "app.js"
APP_CSS = PANEL / "app.css"
SEARCH_ENGINE_JS = PANEL / "search-engine.js"
LEGACY_HTML = PANEL / "legacy.html"
NODE_TEST_FILE = ROOT / "tests" / "test_config_search_and_ui.cjs"

PALETTE_KEYS = (
    "huangbaiyou",
    "tianpiao",
    "haitianxia",
    "yingying",
    "oubi",
    "qingming",
    "zipu",
    "shanlan",
    "qielan",
    "tuihong",
    "congqing",
    "yuebai",
    "mocan",
    "gupiao",
)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    raw = hex_color.strip().lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _rel_luminance(rgb: tuple[float, float, float]) -> float:
    def ch(v: float) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast_ratio(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    l1 = _rel_luminance(fg)
    l2 = _rel_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _blend_rgba_on_rgb(
    rgba: tuple[int, int, int, float], bg: tuple[int, int, int]
) -> tuple[float, float, float]:
    r, g, b, a = rgba
    return (
        r * a + bg[0] * (1.0 - a),
        g * a + bg[1] * (1.0 - a),
        b * a + bg[2] * (1.0 - a),
    )


class ModuleConfigAndGlobalSearchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.app_js = APP_JS.read_text(encoding="utf-8")
        cls.app_css = APP_CSS.read_text(encoding="utf-8")
        cls.legacy_html = LEGACY_HTML.read_text(encoding="utf-8")
        cls.search_js = SEARCH_ENGINE_JS.read_text(encoding="utf-8")

    def test_all_schema_modules_have_pure_chinese_labels_and_fallback(self) -> None:
        block = re.search(r"const MODULE_LABELS = \{([\s\S]*?)\};", self.app_js)
        self.assertIsNotNone(block, "缺少 MODULE_LABELS")
        labels = dict(re.findall(r"([a-z0-9_]+)\s*:\s*\"([^\"]+)\"", block.group(1)))

        for mod_id in self.schema:
            with self.subTest(module=mod_id):
                self.assertIn(mod_id, labels, f"MODULE_LABELS 漏配模块: {mod_id}")
                self.assertRegex(labels[mod_id], r"[\u4e00-\u9fff]", f"{mod_id} 应为中文名")
                self.assertNotRegex(
                    labels[mod_id],
                    r"[A-Za-z_]",
                    f"{mod_id} 侧栏标题不应裸露英文: {labels[mod_id]}",
                )

        self.assertIn("function moduleLabel(", self.app_js)
        self.assertIn("function moduleSubtitle(", self.app_js)
        self.assertEqual("拟人化记忆", labels["memory_humanization"])
        self.assertEqual("记得这个人", labels["persona_memory"])
        self.assertEqual("跨平台身份", labels["identity"])
        self.assertEqual("旧版记忆迁移", labels["livingmemory_migration"])

    def test_config_common_keys_include_identity_cross_group_and_vector_precision(self) -> None:
        block = re.search(r"const CONFIG_COMMON_KEYS = \{([\s\S]*?)\};", self.app_js)
        self.assertIsNotNone(block)
        body = block.group(1)
        self.assertIn('identity: ["merge_platform_accounts"]', body)
        self.assertIn('"cross_window_group_to_group_enabled"', body)
        self.assertIn('"vector_precision"', body)

    def test_all_14_light_palettes_derive_accent_soft_and_line_from_light_accent_with_wcag_contrast(self) -> None:
        for key in PALETTE_KEYS:
            with self.subTest(palette=key):
                pattern = rf'\[data-palette="{re.escape(key)}"\]\[data-theme="light"\]\s*\{{([^}}]*)\}}'
                match = re.search(pattern, self.app_css)
                self.assertIsNotNone(match, f"缺少浅色主题块: {key}")
                body = match.group(1)

                accent_m = re.search(r"--accent:\s*(#[0-9a-fA-F]{6})\s*;", body)
                accent2_m = re.search(r"--accent-2:\s*(#[0-9a-fA-F]{6})\s*;", body)
                surface_m = re.search(r"--surface:\s*(#[0-9a-fA-F]{6})\s*;", body)
                soft_m = re.search(
                    r"--accent-soft:\s*rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)\s*;",
                    body,
                )
                line_m = re.search(
                    r"--accent-line:\s*rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)\s*;",
                    body,
                )
                self.assertIsNotNone(accent_m, f"{key} 缺少 --accent")
                self.assertIsNotNone(accent2_m, f"{key} 缺少 --accent-2")
                self.assertIsNotNone(surface_m, f"{key} 缺少 --surface")
                self.assertIsNotNone(soft_m, f"{key} 缺少 --accent-soft")
                self.assertIsNotNone(line_m, f"{key} 缺少 --accent-line")

                accent_rgb = _hex_to_rgb(accent_m.group(1))
                soft_rgb = (int(soft_m.group(1)), int(soft_m.group(2)), int(soft_m.group(3)))
                soft_alpha = float(soft_m.group(4))
                line_rgb = (int(line_m.group(1)), int(line_m.group(2)), int(line_m.group(3)))
                line_alpha = float(line_m.group(4))

                self.assertEqual(
                    accent_rgb,
                    soft_rgb,
                    f"{key} 浅色 --accent-soft 必须基于浅色自身 --accent({accent_m.group(1)}) 而非暗色粉彩",
                )
                self.assertEqual(accent_rgb, line_rgb, f"{key} 浅色 --accent-line 必须基于 --accent")
                self.assertGreaterEqual(soft_alpha, 0.11)
                self.assertGreaterEqual(line_alpha, 0.30)

                # 校验选中态底色与纯白卡片可肉眼区分，且文字对比度满足 WCAG AA (>= 4.5)
                surface_rgb = _hex_to_rgb(surface_m.group(1))
                active_bg = _blend_rgba_on_rgb((*soft_rgb, soft_alpha), surface_rgb)
                accent2_rgb = _hex_to_rgb(accent2_m.group(1))
                text_contrast = _contrast_ratio(accent2_rgb, active_bg)
                self.assertGreaterEqual(
                    text_contrast,
                    4.5,
                    f"{key} 浅色选中态文字对比度偏低: {text_contrast:.2f}",
                )
                # 校验底色相对纯白表面有清晰色差（非 1.02:1 隐形）
                bg_delta = sum(abs(surface_rgb[i] - active_bg[i]) for i in range(3))
                self.assertGreaterEqual(bg_delta, 30.0, f"{key} 浅色选中态底色过浅不可见")

    def test_config_nav_active_has_left_bar_and_hover_does_not_compete(self) -> None:
        self.assertIn(".config-nav button[data-module].is-active {", self.app_css)
        self.assertIn("box-shadow: inset 3px 0 0 var(--accent);", self.app_css)
        self.assertIn(".config-nav button[data-module]:hover:not(.is-active)", self.app_css)

    def test_choice_field_layout_pulse_no_jump_and_cinema_opaque_modal(self) -> None:
        # 向量精度等分段选择卡占满全宽，避免桌面双栏挤压折行
        choice_field = re.search(r"\.config-field\.is-choice-field\s*\{([^}]*)\}", self.app_css)
        self.assertIsNotNone(choice_field)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", choice_field.group(1))
        self.assertIn("repeat(auto-fit, minmax(min(220px, 100%), 1fr))", self.app_css)

        # 搜索命中高亮使用负外边距抵消内边距，避免 10px 垂直跳动
        hit_rule = re.search(r"\.config-field\.is-search-hit\s*\{([^}]*)\}", self.app_css)
        self.assertIsNotNone(hit_rule)
        self.assertIn("margin: -10px -10px 0;", hit_rule.group(1))
        self.assertIn(".config-field:last-child.is-search-hit", self.app_css)
        self.assertIn("margin-bottom: -13px;", self.app_css)

        # 隐藏 Chromium/WebKit 原生搜索取消按钮，避免与自定义清除键重叠
        self.assertIn(".cfg-search-input::-webkit-search-cancel-button", self.app_css)
        self.assertIn("-webkit-appearance: none;", self.app_css)
        self.assertIn("pointer-events: none;", self.app_css)

        # 全站弹窗 / 抽屉遮罩 / 灯箱 / 高级项折叠框均具备双向平滑过渡与减少动效适配
        self.assertIn(".config-advanced-body", self.app_css)
        self.assertIn(".config-advanced[open] > summary::before", self.app_css)
        self.assertIn(".config-advanced[open]:not(.is-closing) > summary::before", self.app_css)
        self.assertIn(".scrim.is-open", self.app_css)
        self.assertIn(".inline-confirm-overlay.is-open", self.app_css)
        self.assertIn(".lightbox.is-open", self.app_css)
        self.assertIn("function bindSmoothDetails(", self.app_js)
        self.assertIn("function closeLightbox(", self.app_js)

        # 关闭态抽屉必须真正不可见且不可点击，且 reduced-motion 不得把 .drawer 的 transform 覆写成 none
        tail_css = self.app_css[self.app_css.rindex("/* ---------- 7.") :]
        drawer_closed = re.search(r"^\.drawer\s*\{([^}]*)\}", tail_css, re.M)
        self.assertIsNotNone(drawer_closed)
        self.assertIn("visibility: hidden;", drawer_closed.group(1))
        self.assertIn("pointer-events: none;", drawer_closed.group(1))
        drawer_open = re.search(r"^\.drawer\.is-open\s*\{([^}]*)\}", tail_css, re.M)
        self.assertIsNotNone(drawer_open)
        self.assertIn("visibility: visible;", drawer_open.group(1))
        self.assertIn("pointer-events: auto;", drawer_open.group(1))
        rm_block = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$", tail_css)
        self.assertIsNotNone(rm_block)
        # 校验 reduced-motion 中包含 transform: none 的规则只作用于居中弹窗/灯箱图，绝不包含 .drawer 或 summary::before
        for rule_match in re.finditer(r"([^{}]+)\{([^}]*)\}", rm_block.group(1)):
            if "transform: none" in rule_match.group(2):
                self.assertNotIn(".drawer", rule_match.group(1))
                self.assertNotIn("summary::before", rule_match.group(1))

        # 全局配置搜索弹窗桌面端舒展黄金尺寸，窄屏与矮屏优雅自适应
        dialog_rule = re.search(r"^\.cfg-search-dialog\s*\{([^}]*)\}", self.app_css, re.M)
        self.assertIsNotNone(dialog_rule)
        self.assertIn("width: min(840px, 90vw);", dialog_rule.group(1))
        self.assertIn("max-height: min(78vh, 700px);", dialog_rule.group(1))
        body_rule = re.search(r"^\.cfg-search-body\s*\{([^}]*)\}", self.app_css, re.M)
        self.assertIsNotNone(body_rule)
        self.assertIn("min-height: 360px;", body_rule.group(1))
        self.assertIn("@media (max-height: 620px)", self.app_css)

        # cinema 终端模式弹窗底色/头部/页脚使用不透明档案纸底，避免 58% 半透明浑浊
        cinema_dialog = re.search(r'html\[data-ui-mode="cinema"\]\s+\.cfg-search-dialog\s*\{([^}]*)\}', self.app_css)
        self.assertIsNotNone(cinema_dialog)
        self.assertIn("background: #f4f1ea;", cinema_dialog.group(1))
        self.assertIn('html[data-ui-mode="cinema"] .cfg-search-head', self.app_css)
        self.assertIn('html[data-ui-mode="cinema"] .cfg-search-foot', self.app_css)

        # 浅色与 cinema 下的拼音/容错徽章前景色满足 WCAG AA 对比度 (>= 4.5)
        self.assertIn('[data-theme="light"] .cfg-search-tag.is-fuzzy', self.app_css)
        self.assertIn('html[data-ui-mode="cinema"] .cfg-search-tag.is-pinyin', self.app_css)
        self.assertIn('html[data-ui-mode="cinema"] .cfg-search-tag.is-fuzzy', self.app_css)
        self.assertGreaterEqual(_contrast_ratio(_hex_to_rgb("#0369a1"), _hex_to_rgb("#f4f1ea")), 4.5)
        self.assertGreaterEqual(_contrast_ratio(_hex_to_rgb("#92400e"), _hex_to_rgb("#f4f1ea")), 4.5)

    def test_search_engine_asset_version_aligned_with_metadata(self) -> None:
        ver_match = re.search(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)", METADATA.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(ver_match)
        version = ver_match.group(1)
        self.assertIn(f'./search-engine.js?v={version}', self.legacy_html)
        self.assertIn(f'./app.js?v={version}', self.legacy_html)
        self.assertLess(
            self.legacy_html.index(f'./search-engine.js?v={version}'),
            self.legacy_html.index(f'./app.js?v={version}'),
        )

    @unittest.skipIf(shutil.which("node") is None, "当前环境无 node，跳过 JS 语法与单测")
    def test_js_syntax_and_node_unit_tests_pass(self) -> None:
        for script in (SEARCH_ENGINE_JS, APP_JS):
            check = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True, timeout=60)
            self.assertEqual(0, check.returncode, check.stdout + check.stderr)

        run = subprocess.run(
            ["node", "--test", str(NODE_TEST_FILE)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
