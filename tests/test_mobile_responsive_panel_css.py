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
APP_CSS = PANEL_DIR / "app.css"
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
    return node;
  };

  let weightVal = 60;
  let memories = [
    { id: "m1", content: "第一条记忆", tier: "important", memory_type: "fact", occurred_at: "2026-11-20" },
    { id: "m2", content: "第二条记忆", tier: "normal", memory_type: "fact", occurred_at: "2026-11-21" },
  ];
  let failNextPerson = false;
  let holdPersonResolve = null;

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
      confirm: () => true,
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
  await forgetButtons[0].dispatch("click");
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

  process.stdout.write(JSON.stringify({
    initialShowedLoading: initialWrites.some((h) => h.includes('class="loading"')),
    initialScroll,
    afterSave,
    afterReset,
    afterForget,
    afterSilentFail,
    afterSwitchPerson,
    afterStaleClose,
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


if __name__ == "__main__":
    unittest.main()
