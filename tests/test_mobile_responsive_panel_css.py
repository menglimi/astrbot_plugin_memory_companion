"""Mobile viewport layout and zero-horizontal-overflow contracts for app.css and people.css."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "pages" / "记忆面板"
LEGACY_HTML = PANEL_DIR / "legacy.html"
APP_CSS = PANEL_DIR / "app.css"
APP_JS = PANEL_DIR / "app.js"
PEOPLE_CSS = PANEL_DIR / "people.css"
PEOPLE_JS = PANEL_DIR / "people.js"


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
        cls.legacy_html = LEGACY_HTML.read_text(encoding="utf-8")
        cls.app_css = APP_CSS.read_text(encoding="utf-8")
        cls.app_js = APP_JS.read_text(encoding="utf-8")
        cls.people_css = PEOPLE_CSS.read_text(encoding="utf-8")
        cls.app_mobile = _extract_balanced_block(
            cls.app_css,
            r"/\*\s*-+\s*4\.\s*移动端\s*-+\s*\*/\s*@media\s*\(max-width:\s*640px\)\s*\{",
        )
        cls.people_mobile = _extract_balanced_block(
            cls.people_css,
            r"@media\s*\(max-width:\s*720px\)\s*\{",
        )

    def test_compact_layout_uses_css_variables_without_specificity_hijack(self) -> None:
        # 紧凑模式必须只通过 html:not([data-ui-mode="cinema"]) 声明 CSS 变量，
        # 绝不能再用 html:not([data-ui-mode="cinema"]) .topbar/.content/.btn 压过移动端断点。
        self.assertIsNone(
            re.search(
                r'html:not\(\[data-ui-mode="cinema"\]\)\s+\.(?:topbar|content|btn|kpi-row|card|nav-item|grid)\b',
                self.app_css,
            ),
            "紧凑布局不应使用高优先级子选择器覆写，应改用 --mc-* CSS 变量",
        )
        for token in (
            "--mc-content-pad:",
            "--mc-topbar-pad:",
            "--mc-search-h:",
            "--mc-btn-h:",
            "--mc-kpi-cols:",
        ):
            self.assertIn(token, self.app_css)

        # 级联顺序必须严格为：默认紧凑变量块 -> <=900px 平板变量覆写 -> <=640px 移动端变量覆写
        default_compact_pos = self.app_css.index('--mc-topbar-pad: 13px 20px 11px;')
        tablet_900_pos = self.app_css.index('--mc-topbar-pad: 16px 18px 14px;')
        mobile_640_pos = self.app_css.index('--mc-topbar-pad: 12px 14px 10px;')
        self.assertLess(default_compact_pos, tablet_900_pos, "<=900px 变量覆写必须位于默认紧凑变量块之后")
        self.assertLess(tablet_900_pos, mobile_640_pos, "<=640px 变量覆写必须位于 <=900px 变量覆写之后")

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

        content_rule = re.search(r"\.content,\s*html\[data-ui-mode=\"cinema\"\]\s*\.content\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(content_rule)
        self.assertIn("overflow: visible;", content_rule.group(1))

        rail_rule = re.search(r"\.rail\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(rail_rule)
        self.assertIn("env(safe-area-inset-bottom)", rail_rule.group(1))

        main_rule = re.search(r"\.main\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(main_rule)
        self.assertIn("env(safe-area-inset-bottom)", main_rule.group(1))

    def test_mobile_dual_row_topbar_five_slot_rail_and_inflow_subnav(self) -> None:
        # 1) HTML 结构含顶栏操作分组、移动端主题切换按钮、流内子导航与「更多」抽屉
        for snippet in (
            'class="topbar-actions"',
            'id="topbarThemeBtn"',
            'id="mobileSubnav"',
            'id="mobileMoreSheet"',
        ):
            self.assertIn(snippet, self.legacy_html)

        # 2) 顶栏双行网格：第一行标题+图标按钮不换行，第二行全宽搜索框
        topbar = re.search(r"\.topbar\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(topbar)
        self.assertIn('"copy actions"', topbar.group(1))
        self.assertIn('"search search"', topbar.group(1))

        actions_btn = re.search(r"\.topbar-actions\s+\.tool-btn\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(actions_btn)
        self.assertIn("min-width: 44px;", actions_btn.group(1))
        self.assertIn("min-height: 44px;", actions_btn.group(1))

        # 3) 底部导航 5 槽均分无横向滚动条，且不再使用 fixed 悬空 .nav-subs
        rail_nav = re.search(r"\.rail-nav\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(rail_nav)
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr));", rail_nav.group(1))
        self.assertIn("overflow: hidden;", rail_nav.group(1))
        self.assertNotIn("position: fixed; left: 0; right: 0; bottom:", self.app_mobile)

        # 4) 流内 .mobile-subnav 在 [hidden] 时隐藏，且具备足够触控高度
        subnav = re.search(r"\.mobile-subnav\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(subnav)
        self.assertIn("display: flex;", subnav.group(1))
        self.assertIn(".mobile-subnav[hidden] { display: none; }", self.app_mobile)
        subnav_pill = re.search(r"\.mobile-subnav-pill\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(subnav_pill)
        self.assertIn("min-height: 40px;", subnav_pill.group(1))

    def test_app_css_mobile_full_site_sweep_and_touch_targets(self) -> None:
        # 裸单列网格容器必须显式声明 grid-template-columns: minmax(0, 1fr)，
        # 防止隐式 auto 轨道被子项撑宽在移动端被 body { overflow-x: hidden } 右侧裁切。
        grid_rule = re.search(r"^\.grid\s*\{([^}]*)\}", self.app_css, re.M)
        self.assertIsNotNone(grid_rule)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", grid_rule.group(1))
        config_main_rule = re.search(r"^\.config-main\s*\{([^}]*)\}", self.app_css, re.M)
        self.assertIsNotNone(config_main_rule)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", config_main_rule.group(1))
        self.assertIn('[style*="display:grid"]:not([style*="grid-template-columns"])', self.app_css)

        # 表格滚动容器、ACL 粘性首列 + 触屏信息栏、表单/参数行/导入映射、3D 终端溢出与灯箱关闭键
        self.assertIn(".table-scroll {", self.app_css)
        self.assertIn("wrapResponsiveTables", self.app_js)

        mx_rule = re.search(r"\.mx\s*\{([^}]*)\}", self.app_css)
        self.assertIsNotNone(mx_rule)
        self.assertIn("var(--mx-head-w, 138px)", mx_rule.group(1))
        self.assertIn("var(--mx-cell-w, 68px)", mx_rule.group(1))

        mx_rh = re.search(r"\.mx-rh\s*\{([^}]*)\}", self.app_css)
        self.assertIsNotNone(mx_rh)
        self.assertIn("position: sticky;", mx_rh.group(1))
        self.assertIn("left: 0;", mx_rh.group(1))

        # 移动端关闭悬停浮层，改用触屏信息栏
        self.assertRegex(self.app_css, r"@media\s*\(max-width:\s*640px\),\s*\(pointer:\s*coarse\)\s*\{[^}]*\.mx-tip\s*\{\s*display:\s*none;\s*\}")
        self.assertIn(".mx-touch-info", self.app_css)

        # 设置模块目录 <=1100px 取消竖向 sticky 并横向滚动
        cfg_1100 = _extract_balanced_block(
            self.app_css,
            r"\.cfg-kbd\s*\{[^}]*\}\s*@media\s*\(max-width:\s*1100px\)\s*\{",
        )
        self.assertIn("position: static;", cfg_1100)
        self.assertIn("flex-direction: row;", cfg_1100)
        self.assertIn("overflow-x: auto;", cfg_1100)

        # 移动端禁止硬编码内联死宽与负外边距溢出
        self.assertNotIn("grid-template-columns: 138px repeat(", self.app_js)
        self.assertNotIn("grid-template-columns:minmax(0,1fr) 110px minmax(0,1fr)", self.app_js)
        self.assertNotIn("grid-template-columns:minmax(0,1fr) 96px auto", self.app_js)
        self.assertIn('html[data-ui-mode="cinema"] .cinema-marquee { margin: 0;', self.app_mobile)
        self.assertIn(".terminal-scene-wrap { margin: 0;", self.app_mobile)
        self.assertIn(".lightbox-close", self.app_css)
        self.assertIn(".param-row > div { white-space: normal; overflow-wrap: anywhere;", self.app_mobile)
        self.assertIn(".field.is-inline { flex-direction: column;", self.app_mobile)
        self.assertIn("min-height: 44px;", self.app_mobile)

        card_head = re.search(r"\.card-head\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(card_head)
        self.assertIn("flex-wrap: wrap;", card_head.group(1))
        self.assertIn("gap: 8px;", card_head.group(1))

        head_actions = re.search(r"\.card-head-actions\s*\{([^}]*)\}", self.app_mobile)
        self.assertIsNotNone(head_actions)
        self.assertIn("width: 100%;", head_actions.group(1))
        self.assertIn("flex-wrap: wrap;", head_actions.group(1))

    def test_app_js_mobile_subnav_only_renders_when_group_has_multiple_views(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for app.js mobile subnav behavior check")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const railHost = { innerHTML: "" };
const subnavHost = { hidden: true, innerHTML: "", querySelector() { return null; } };
const moreSheet = { hidden: true, innerHTML: "", classList: { add() {}, remove() {} }, offsetWidth: 0 };
const moreScrim = { hidden: true, classList: { add() {}, remove() {} } };
const ctx = vm.createContext({
  location: { search: "" },
  URLSearchParams,
  setTimeout,
  clearTimeout,
  CustomEvent: function CustomEvent(type, init) { this.type = type; this.detail = init && init.detail; },
  document: {
    documentElement: { dataset: { theme: "dark" } },
    readyState: "loading",
    addEventListener() {},
    querySelector(sel) {
      if (sel === "#railNav") return railHost;
      if (sel === "#mobileSubnav") return subnavHost;
      if (sel === "#mobileMoreSheet") return moreSheet;
      if (sel === "#mobileMoreScrim") return moreScrim;
      if (sel === "#themeToggleLabel") return { textContent: "" };
      return null;
    },
    querySelectorAll() { return []; },
  },
  window: {
    addEventListener() {},
    dispatchEvent() {},
    matchMedia: () => ({ matches: true }),
    setTimeout,
    clearTimeout,
  },
});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const res = vm.runInContext(`(() => {
  const rail = document.querySelector("#railNav");
  const subnav = document.querySelector("#mobileSubnav");
  const sheet = document.querySelector("#mobileMoreSheet");
  state.group = "overview";
  state.view = "overview";
  renderRail();
  const onOverview = { hidden: subnav.hidden, html: subnav.innerHTML, hasMoreBtn: rail.innerHTML.includes('id="mobileMoreBtn"') };

  state.group = "library";
  state.view = "inspect";
  renderRail();
  const onLibrary = { hidden: subnav.hidden, html: subnav.innerHTML };

  state.group = "import";
  state.view = "quarantine";
  renderRail();
  const onImport = { hidden: subnav.hidden, html: subnav.innerHTML, moreActive: rail.innerHTML.includes('mobile-more-btn is-active') };

  setMobileMoreOpen(true);
  const sheetHtml = sheet.innerHTML;
  setMobileMoreOpen(false);
  return { onOverview, onLibrary, onImport, sheetHtml, sheetHiddenAfterClose: sheet.hidden };
})()`, ctx);
process.stdout.write(JSON.stringify(res));
"""
        proc = subprocess.run(
            [node, "-e", code, str(APP_JS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, proc.returncode, f"Node harness failed:\n{proc.stderr}\n{proc.stdout}")
        out = json.loads(proc.stdout)
        self.assertTrue(out["onOverview"]["hidden"], "总览分组仅有 1 个视图，移动端不得显示悬空子导航")
        self.assertEqual("", out["onOverview"]["html"])
        self.assertTrue(out["onOverview"]["hasMoreBtn"])
        self.assertFalse(out["onLibrary"]["hidden"])
        self.assertIn('data-view="inspect"', out["onLibrary"]["html"])
        self.assertIn("is-active", out["onLibrary"]["html"])
        self.assertFalse(out["onImport"]["hidden"])
        self.assertTrue(out["onImport"]["moreActive"], "进入导入/联动分组时，底部「更多」槽位应高亮")
        self.assertIn('data-more-view="quarantine"', out["sheetHtml"])
        self.assertIn('data-more-view="companion"', out["sheetHtml"])
        self.assertIn('data-more-action="config-search"', out["sheetHtml"])
        self.assertTrue(out["sheetHiddenAfterClose"])

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

        # Mobile <=720px media query uses minmax(0, 1fr), full-width search bar, sticky 44x44 close button & 44px forget button
        self.assertIn("grid-template-columns: minmax(0, 1fr);", self.people_mobile)
        self.assertNotIn("grid-template-columns: 1fr;", self.people_mobile)
        self.assertIn("flex: 1 1 100%;", self.people_mobile)
        self.assertIn("padding: 16px 14px 10px;", self.people_mobile)
        self.assertIn("env(safe-area-inset-bottom)", self.people_mobile)
        self.assertIn("position: sticky;", self.people_mobile)
        self.assertIn("width: 44px;", self.people_mobile)
        self.assertIn("height: 44px;", self.people_mobile)
        self.assertIn(".detail-list .line button", self.people_mobile)
        self.assertIn("min-height: 44px;", self.people_mobile)

    def test_people_js_drawer_mutations_refresh_in_place_and_preserve_scroll_top(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for people.js drawer behavior verification")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");

(async () => {
  const nodes = {};
  const drawerBodyWrites = [];
  const gridClears = [];
  const loadingShows = [];
  let forgetButtons = [];
  const makeNode = (id) => {
    const attrs = {};
    const listeners = {};
    const node = {
      id,
      hidden: id === "drawer" || id === "scrim" || id === "toast",
      _html: "",
      textContent: "",
      value: "",
      scrollTop: 0,
      disabled: false,
      attrs,
      dataset: {},
      get innerHTML() { return this._html; },
      set innerHTML(v) {
        const next = String(v);
        this._html = next;
        if (id === "drawerBody") {
          drawerBodyWrites.push(next);
          for (const childId of ["weightInput", "weightValue", "addressInput", "relationInput", "noteInput", "saveBtn", "resetWeightBtn", "erasePersonBtn", "eraseConfirmInput", "eraseHint"]) {
            delete nodes[childId];
          }
          const matches = [...next.matchAll(/data-forget="([^"]+)"/g)];
          forgetButtons = matches.map((m) => {
            const btn = makeNode(`forget_${m[1]}`);
            btn.dataset = { forget: m[1] };
            return btn;
          });
        }
        if (id === "grid" && next === "") gridClears.push(true);
      },
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      dispatch(type, evt) { return Promise.all((listeners[type] || []).map((fn) => fn(evt || {}))); },
      setAttribute(k, v) { attrs[k] = String(v); },
      getAttribute(k) { return attrs[k]; },
      contains() { return false; },
      querySelectorAll(sel) {
        if (id === "drawerBody" && sel === "[data-forget]") return forgetButtons;
        return [];
      },
      focus() {},
    };
    if (id === "loading") {
      let hiddenVal = true;
      Object.defineProperty(node, "hidden", {
        get() { return hiddenVal; },
        set(v) {
          hiddenVal = Boolean(v);
          if (!hiddenVal) loadingShows.push(true);
        },
      });
    }
    if (id === "personConfirm") {
      let onClose = null;
      node.open = false;
      node.showModal = () => { node.open = true; };
      node.addEventListener = (type, fn) => { if (type === "close") onClose = fn; };
      node.close = (value) => {
        node.open = false;
        if (value !== undefined) node.returnValue = value;
        const handler = onClose;
        onClose = null;
        handler();
      };
    }
    return node;
  };

  let weightVal = 60;
  let memories = [
    { id: "m1", content: "第一条记忆", tier: "important", memory_type: "fact", occurred_at: "2026-11-20" },
    { id: "m2", content: "第二条记忆", tier: "normal", memory_type: "fact", occurred_at: "2026-11-21" },
  ];
  let failNextPerson = false;
  let holdPersonResolve = null;
  const erasePosts = [];

  const personDetail = (uid) => ({
    user_id: uid,
    display_name: uid === "u1" ? "阿哲" : "小李",
    platform: "qq",
    profile: { relation_address: uid === "u1" ? "阿哲" : "", relation_label: "朋友", relation_note: "" },
    weight: { weight: weightVal, band: "close", band_label: "亲近的人" },
    total: memories.length,
    memories: memories.slice(),
  });

  const bridge = {
    onContext() { return () => {}; },
    apiGet(endpoint, params) {
      if (endpoint === "page/ui-preferences") return Promise.resolve({ success: true, data: { dark_mode: true } });
      if (endpoint === "page/ui/csrf") return Promise.resolve({ success: true, data: { token: "csrf-1", expires_in: 900 } });
      if (endpoint === "page/people") {
        return Promise.resolve({
          success: true,
          data: {
            items: [{ user_id: "u1", display_name: "阿哲", weight: weightVal, band: "close", band_label: "亲近的人", memory_count: memories.length, imprint_count: 0, days_since_last: 1, top: memories.slice(0, 1) }],
            bots: [],
            total: 1,
          },
        });
      }
      if (endpoint === "page/person") {
        if (holdPersonResolve) {
          return new Promise((resolve) => { holdPersonResolve = () => resolve({ success: true, data: personDetail(params.user_id) }); });
        }
        if (failNextPerson) {
          failNextPerson = false;
          return Promise.reject(new Error("temp network hiccup"));
        }
        return Promise.resolve({ success: true, data: personDetail(params.user_id) });
      }
      if (endpoint === "page/maintenance/summary_status") return Promise.resolve({ success: true, data: { status: null } });
      return Promise.resolve({ success: true, data: {} });
    },
    apiPost(endpoint, body) {
      if (endpoint === "page/ui/confirm-nonce") {
        return Promise.resolve({ success: true, data: { confirm: "nonce-for-" + body.route } });
      }
      if (endpoint === "page/person/erase") {
        erasePosts.push(body);
        return Promise.resolve({ success: true, data: { ok: true } });
      }
      if (endpoint === "page/person/weight") {
        weightVal = body.weight === null ? 50 : Number(body.weight);
        return Promise.resolve({ success: true, data: { ok: true } });
      }
      if (endpoint === "page/memory/update") {
        memories = memories.filter((m) => m.id !== body.id);
        return Promise.resolve({ success: true, data: { ok: true } });
      }
      return Promise.resolve({ success: true, data: {} });
    },
  };

  const ctx = vm.createContext({
    location: { search: "", origin: "null" },
    URLSearchParams,
    setTimeout,
    clearTimeout,
    document: {
      documentElement: { dataset: {} },
      activeElement: null,
      getElementById(id) { return nodes[id] || (nodes[id] = makeNode(id)); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
    },
    window: {
      AstrBotPluginPage: bridge,
      addEventListener() {},
    },
  });
  vm.runInContext(source, ctx);
  await new Promise((r) => setTimeout(r, 30));

  // 1) Initial open shows loading and resets scrollTop to 0
  nodes.drawer.scrollTop = 99;
  await vm.runInContext('openPerson("u1", "qq", "")', ctx);
  const initialWrites = drawerBodyWrites.slice();
  const initialScroll = nodes.drawer.scrollTop;

  // 2) Scroll down inside open drawer; test savePerson, resetWeight, forgetMemory
  drawerBodyWrites.length = 0;
  gridClears.length = 0;
  loadingShows.length = 0;
  nodes.drawer.scrollTop = 420;
  ctx.document.getElementById("weightInput").value = "88";
  ctx.document.getElementById("addressInput").value = "阿哲";
  ctx.document.getElementById("relationInput").value = "恋人";
  ctx.document.getElementById("noteInput").value = "备注";
  await ctx.document.getElementById("saveBtn").dispatch("click");
  const afterSave = {
    scrollTop: nodes.drawer.scrollTop,
    loadingFlashed: drawerBodyWrites.some((h) => h.includes('class="loading"')),
    gridCleared: gridClears.length > 0,
    pageLoadingFlashed: loadingShows.length > 0,
    hasUpdatedWeight: nodes.drawerBody.innerHTML.includes("88 ·"),
  };

  drawerBodyWrites.length = 0;
  gridClears.length = 0;
  loadingShows.length = 0;
  nodes.drawer.scrollTop = 360;
  await ctx.document.getElementById("resetWeightBtn").dispatch("click");
  const afterReset = {
    scrollTop: nodes.drawer.scrollTop,
    loadingFlashed: drawerBodyWrites.some((h) => h.includes('class="loading"')),
    gridCleared: gridClears.length > 0,
    pageLoadingFlashed: loadingShows.length > 0,
    hasResetWeight: nodes.drawerBody.innerHTML.includes("50 ·"),
  };

  drawerBodyWrites.length = 0;
  nodes.drawer.scrollTop = 510;
  const forget = forgetButtons[0].dispatch("click");
  nodes.personConfirm.close("confirm");
  await forget;
  const afterForget = {
    scrollTop: nodes.drawer.scrollTop,
    loadingFlashed: drawerBodyWrites.some((h) => h.includes('class="loading"')),
    memoryRemoved: !nodes.drawerBody.innerHTML.includes("第一条记忆"),
    secondKept: nodes.drawerBody.innerHTML.includes("第二条记忆"),
  };

  // 3) Silent refresh failure keeps open drawer intact and shows toast
  drawerBodyWrites.length = 0;
  failNextPerson = true;
  await vm.runInContext('openPerson("u1", "qq", "", { silent: true, preserveScroll: true })', ctx);
  const afterSilentFail = {
    keptContent: nodes.drawerBody.innerHTML.includes("第二条记忆"),
    noErrorWipe: !nodes.drawerBody.innerHTML.includes("翻不开了"),
    toastText: nodes.toast.textContent,
  };

  // 4) Opening a DIFFERENT person shows loading placeholder and resets scrollTop to 0
  drawerBodyWrites.length = 0;
  nodes.drawer.scrollTop = 300;
  await vm.runInContext('openPerson("u2", "qq", "")', ctx);
  const afterSwitchPerson = {
    showedLoading: drawerBodyWrites.some((h) => h.includes('class="loading"')),
    scrollTop: nodes.drawer.scrollTop,
    renderedNewPerson: nodes.drawerBody.innerHTML.includes("小李"),
  };

  // 5) Stale response after closeDrawer() is ignored
  holdPersonResolve = () => {};
  const inflight = vm.runInContext('openPerson("u1", "qq", "")', ctx);
  await new Promise((r) => setTimeout(r, 10));
  vm.runInContext("closeDrawer()", ctx);
  const triggerResolve = holdPersonResolve;
  holdPersonResolve = null;
  triggerResolve();
  await inflight;
  const afterStaleClose = {
    drawerHidden: nodes.drawer.hidden,
    selectedIsNull: vm.runInContext("state.selected === null", ctx),
  };

  // 6) Erase requires typed confirmation and a positive dialog response.
  await vm.runInContext('openPerson("u1", "qq", "")', ctx);
  await nodes.erasePersonBtn.dispatch("click");
  const typedRequired = !nodes.personConfirm.open && erasePosts.length === 0;
  nodes.eraseConfirmInput.value = "擦掉";
  const cancelErase = nodes.erasePersonBtn.dispatch("click");
  const eraseDialogOpened = nodes.personConfirm.open;
  nodes.personConfirm.close();
  await cancelErase;
  const cancelWithoutWrite = erasePosts.length === 0 && !nodes.drawer.hidden;
  const confirmErase = nodes.erasePersonBtn.dispatch("click");
  nodes.personConfirm.close("confirm");
  await confirmErase;

  process.stdout.write(JSON.stringify({
    initialShowedLoading: initialWrites.some((h) => h.includes('class="loading"')),
    initialScroll,
    afterSave,
    afterReset,
    afterForget,
    afterSilentFail,
    afterSwitchPerson,
    afterStaleClose,
    typedRequired,
    eraseDialogOpened,
    cancelWithoutWrite,
    erasePosts,
  }));
})();
"""
        proc = subprocess.run(
            [node, "-e", code, str(PEOPLE_JS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, proc.returncode, f"Node harness failed:\n{proc.stderr}\n{proc.stdout}")
        out = json.loads(proc.stdout)

        self.assertTrue(out["initialShowedLoading"])
        self.assertEqual(0, out["initialScroll"])

        self.assertEqual(420, out["afterSave"]["scrollTop"])
        self.assertFalse(out["afterSave"]["loadingFlashed"], "保存后不得闪出 <p class='loading'>")
        self.assertFalse(out["afterSave"]["gridCleared"], "保存后静默更新列表不得清空背景 grid")
        self.assertFalse(out["afterSave"]["pageLoadingFlashed"])
        self.assertTrue(out["afterSave"]["hasUpdatedWeight"])

        self.assertEqual(360, out["afterReset"]["scrollTop"])
        self.assertFalse(out["afterReset"]["loadingFlashed"], "重置分量后不得闪出 <p class='loading'>")
        self.assertFalse(out["afterReset"]["gridCleared"])
        self.assertFalse(out["afterReset"]["pageLoadingFlashed"])
        self.assertTrue(out["afterReset"]["hasResetWeight"])

        self.assertEqual(510, out["afterForget"]["scrollTop"])
        self.assertFalse(out["afterForget"]["loadingFlashed"], "让她忘掉这条后不得闪出 <p class='loading'>")
        self.assertTrue(out["afterForget"]["memoryRemoved"])
        self.assertTrue(out["afterForget"]["secondKept"])

        self.assertTrue(out["afterSilentFail"]["keptContent"])
        self.assertTrue(out["afterSilentFail"]["noErrorWipe"])
        self.assertIn("没刷新上", out["afterSilentFail"]["toastText"])

        self.assertTrue(out["afterSwitchPerson"]["showedLoading"])
        self.assertEqual(0, out["afterSwitchPerson"]["scrollTop"])
        self.assertTrue(out["afterSwitchPerson"]["renderedNewPerson"])

        self.assertTrue(out["afterStaleClose"]["drawerHidden"])
        self.assertTrue(out["afterStaleClose"]["selectedIsNull"])
        self.assertTrue(out["typedRequired"])
        self.assertTrue(out["eraseDialogOpened"])
        self.assertTrue(out["cancelWithoutWrite"])
        self.assertEqual(
            [{
                "user_id": "u1",
                "platform": "qq",
                "bot_id": "",
                "csrf_token": "csrf-1",
                "confirm": "nonce-for-/person/erase",
            }],
            out["erasePosts"],
        )


if __name__ == "__main__":
    unittest.main()
