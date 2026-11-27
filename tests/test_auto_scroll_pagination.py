"""Regression tests for shared auto-scroll pagination across memories, people, and summary batches."""
from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
PAGES = ROOT / "pages" / "记忆面板"

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload if payload is not None else kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")
    quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = quart_stub

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi


class _FakeResponse:
    status_code = 200

    def __init__(self, payload) -> None:
        self.payload = payload


def _fake_jsonify(payload=None, **kwargs):
    return _FakeResponse(payload if payload is not None else kwargs)


class AutoScrollBackendPaginationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory_companion.db")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=self.store)))

    async def test_memories_endpoint_offset_pagination_breaks_120_limit_and_reports_has_more(self) -> None:
        # Seed 150 normal memories + 5 external memories to test both scope=all and scope=external.
        for idx in range(150):
            await self.store.insert_memory(
                MemoryRecord(
                    id=f"mem-{idx:03d}",
                    memory_type="conversation_summary",
                    subject=EntityRef(kind="user", id="u1"),
                    object=EntityRef(kind="bot", id="bot-a"),
                    platform="qq",
                    scope="private",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    owner_bot_id="bot-a",
                    source_plugin=page_api_module.PLUGIN_NAME,
                    content=f"记忆内容 #{idx:03d}",
                    occurred_at=f"2026-11-{(idx % 28) + 1:02d}T10:{idx % 60:02d}:00+00:00",
                )
            )
        for idx in range(5):
            await self.store.insert_memory(
                MemoryRecord(
                    id=f"ext-{idx:02d}",
                    memory_type="conversation_summary",
                    subject=EntityRef(kind="user", id="u1"),
                    object=EntityRef(kind="bot", id="bot-a"),
                    platform="qq",
                    scope="private",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    owner_bot_id="bot-a",
                    source_plugin="other_plugin",
                    content=f"外部记忆 #{idx:02d}",
                    occurred_at=f"2026-11-01T00:{idx:02d}:00+00:00",
                )
            )

        collected: list[str] = []
        offset = 0
        pages = 0
        while True:
            with patch.object(
                page_api_module, "request", SimpleNamespace(args={"scope": "all", "limit": "60", "offset": str(offset)})
            ), patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
                body = (await self.api.memories()).payload
            self.assertTrue(body["success"])
            batch = body["memories"]
            collected.extend(item["id"] for item in batch)
            pages += 1
            if not body["has_more"]:
                self.assertIsNone(body["next_offset"])
                break
            self.assertEqual(offset + len(batch), body["next_offset"])
            offset = body["next_offset"]
            self.assertLess(pages, 10)

        self.assertEqual(155, len(collected))
        self.assertEqual(155, len(set(collected)))
        self.assertEqual(3, pages)

        # Verify scope=external paginates accurately in SQL across offset boundaries.
        ext_ids: list[str] = []
        ext_offset = 0
        while True:
            with patch.object(
                page_api_module, "request", SimpleNamespace(args={"scope": "external", "limit": "2", "offset": str(ext_offset)})
            ), patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
                body = (await self.api.memories()).payload
            ext_ids.extend(item["id"] for item in body["memories"])
            if not body["has_more"]:
                break
            ext_offset = body["next_offset"]
        self.assertEqual(5, len(ext_ids))
        self.assertEqual({f"ext-{i:02d}" for i in range(5)}, set(ext_ids))

    async def test_people_endpoint_offset_pagination_walks_past_120_profiles(self) -> None:
        for idx in range(145):
            uid = f"user-{idx:03d}"
            await self.store.upsert_identity(platform="qq", entity=EntityRef(kind="user", id=uid, name=f"人物{idx:03d}"))
            await self.store.person_weight(user_id=uid, platform="qq", bot_id="bot-a")

        seen: list[str] = []
        offset = 0
        total = 0
        while True:
            with patch.object(
                page_api_module, "request", SimpleNamespace(args={"limit": "48", "offset": str(offset), "sort": "weight"})
            ), patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
                body = (await self.api.people()).payload
            self.assertTrue(body["success"])
            total = body["total"]
            batch = body["items"]
            seen.extend(item["user_id"] for item in batch)
            offset += len(batch)
            if not batch or offset >= total:
                break
        self.assertEqual(145, total)
        self.assertEqual(145, len(seen))
        self.assertEqual(145, len(set(seen)))


class AutoScrollFrontendBehaviorTests(unittest.TestCase):
    def test_assets_wire_versioned_auto_scroll_module_without_storage_leak_in_people(self) -> None:
        version = re.search(
            r'PLUGIN_VERSION\s*=\s*"([^"]+)"', (ROOT / "main.py").read_text(encoding="utf-8")
        ).group(1)
        legacy_html = (PAGES / "legacy.html").read_text(encoding="utf-8")
        people_html = (PAGES / "people.html").read_text(encoding="utf-8")
        people_js = (PAGES / "people.js").read_text(encoding="utf-8")
        self.assertIn(f'./auto-scroll.js?v={version}', legacy_html)
        self.assertIn(f'./auto-scroll.js?v={version}', people_html)
        self.assertLess(
            legacy_html.index(f'src="./auto-scroll.js?v={version}"'),
            legacy_html.index(f'src="./app.js?v={version}"'),
        )
        self.assertLess(
            people_html.index(f'src="./auto-scroll.js?v={version}"'),
            people_html.index(f'src="./people.js?v={version}"'),
        )
        # Preserve sandbox storage contract for people.html / people.js.
        self.assertNotIn("localStorage", people_html)
        self.assertNotIn("localStorage", people_js)
        self.assertNotIn("sessionStorage", people_html)
        self.assertNotIn("sessionStorage", people_js)

    def test_auto_scroll_module_debounce_lock_circuit_breaker_sandbox_and_retry(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for auto-scroll.js behavior verification")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");

  let sentinelTop = 200;
  function makeElement(tag) {
    const attrs = {};
    const listeners = {};
    const el = {
      tagName: tag.toUpperCase(),
      className: "",
      hidden: false,
      children: [],
      parentNode: null,
      parentElement: null,
      scrollTop: 500,
      _html: "",
      get innerHTML() { return this._html; },
      set innerHTML(v) { this._html = String(v); },
      appendChild(child) {
        child.parentNode = el;
        child.parentElement = el;
        el.children.push(child);
        return child;
      },
      removeChild(child) {
        el.children = el.children.filter((c) => c !== child);
        child.parentNode = null;
        child.parentElement = null;
      },
      setAttribute(k, v) { attrs[k] = String(v); },
      getAttribute(k) { return attrs[k]; },
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      removeEventListener(type, fn) {
        listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
      },
      dispatch(type, evt) { (listeners[type] || []).forEach((fn) => fn(evt || {})); },
      getBoundingClientRect() {
        if (el.className === "mc-as-sentinel") return { top: sentinelTop, bottom: sentinelTop + 1 };
        return { top: 0, bottom: 700 };
      },
      scrollTo(opts) { el.scrollTop = typeof opts === "object" ? Number(opts.top || 0) : 0; },
    };
    return el;
  }

(async () => {
  let ioCallback = null;
  let ioDisconnected = false;
  let ioRoot = null;
  class FakeIO {
    constructor(cb, opts) { ioCallback = cb; ioRoot = opts && opts.root; }
    observe() {}
    disconnect() { ioDisconnected = true; }
  }

  const scrollRoot = makeElement("div");
  const host = makeElement("div");
  scrollRoot.appendChild(host);

  const ctx = vm.createContext({
    setTimeout,
    clearTimeout,
    Date,
    IntersectionObserver: FakeIO,
    document: {
      body: makeElement("body"),
      documentElement: makeElement("html"),
      createElement: makeElement,
    },
    window: {
      innerHeight: 800,
      get localStorage() { throw new Error("SecurityError: sandbox blocked"); },
      getComputedStyle(node) {
        return { overflowY: node === scrollRoot ? "auto" : "visible" };
      },
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {},
    },
  });
  ctx.window.IntersectionObserver = FakeIO;
  vm.runInContext(source, ctx);

  const api = ctx.window.MemoryAutoScroll;
  let cursor = 0;
  let count = 20;
  let hasMore = true;
  let failNext = false;
  let calls = 0;
  let stallNext = false;

  const ctrl = api.mount({
    host,
    scrollRoot: () => scrollRoot,
    minIntervalMs: 30,
    itemLabel: "条",
    getCursor: () => cursor,
    hasMore: () => hasMore,
    isLoading: () => false,
    hasError: () => false,
    getCount: () => count,
    getTotal: () => 60,
    async onLoadMore() {
      calls += 1;
      await new Promise((r) => setTimeout(r, 25));
      if (failNext) {
        failNext = false;
        throw new Error("network down");
      }
      if (stallNext) {
        stallNext = false;
        return;
      }
      cursor += 20;
      count += 20;
      sentinelTop = 1800;
      if (count >= 60) hasMore = false;
    },
  });

  // 1) Auto-enabled by default even when localStorage throws SecurityError
  const defaultAuto = ctrl.isAutoEnabled();
  const detectedNestedRoot = ioRoot === scrollRoot;

  // 2) Rapid repeated intersections are debounced & concurrency-locked into 1 call
  sentinelTop = 500;
  ioCallback([{ isIntersecting: true }]);
  ioCallback([{ isIntersecting: true }]);
  ioCallback([{ isIntersecting: true }]);
  await new Promise((r) => setTimeout(r, 40));
  ioCallback([{ isIntersecting: false }]);
  await new Promise((r) => setTimeout(r, 50));
  const afterFirstBurst = { calls, count, cursor };

  // 3) Failure trips circuit breaker; subsequent intersection does NOT auto-fire
  failNext = true;
  sentinelTop = 500;
  ioCallback([{ isIntersecting: true }]);
  await new Promise((r) => setTimeout(r, 40));
  sentinelTop = 1800;
  ioCallback([{ isIntersecting: false }]);
  await new Promise((r) => setTimeout(r, 50));
  const callsAfterError = calls;
  const barHtmlOnError = host.children[0].children[1].innerHTML;
  sentinelTop = 500;
  ioCallback([{ isIntersecting: true }]);
  await new Promise((r) => setTimeout(r, 60));
  sentinelTop = 1800;
  ioCallback([{ isIntersecting: false }]);
  const callsBlockedByCircuitBreaker = calls;

  // 4) Clicking retry clears circuit breaker and completes remaining page
  const bar = host.children[0].children[1];
  bar.dispatch("click", { target: { closest: () => ({ getAttribute: () => "retry" }) } });
  await new Promise((r) => setTimeout(r, 70));
  const afterRetry = { calls, count, hasMore, barHtml: bar.innerHTML };

  // 5) Clicking "top" scrolls nested scrollRoot to 0
  scrollRoot.scrollTop = 780;
  bar.dispatch("click", { target: { closest: () => ({ getAttribute: () => "top" }) } });
  const scrollTopAfterTopClick = scrollRoot.scrollTop;

  // 6) Clicking toggle flips auto preference in memory fallback
  bar.dispatch("click", { target: { closest: () => ({ getAttribute: () => "toggle" }) } });
  const afterToggle = ctrl.isAutoEnabled();

  // 7) Destroy disconnects IntersectionObserver cleanly
  ctrl.destroy();

  process.stdout.write(JSON.stringify({
    defaultAuto,
    detectedNestedRoot,
    afterFirstBurst,
    callsAfterError,
    barHasRetry: barHtmlOnError.includes("点击重试") && barHtmlOnError.includes("network down"),
    callsBlockedByCircuitBreaker,
    afterRetry,
    scrollTopAfterTopClick,
    afterToggle,
    ioDisconnected,
  }));
})();
"""
        proc = subprocess.run([node, "-e", code, str(PAGES / "auto-scroll.js")], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, proc.returncode, f"Node harness failed:\n{proc.stderr}\n{proc.stdout}")
        out = json.loads(proc.stdout)
        self.assertTrue(out["defaultAuto"])
        self.assertTrue(out["detectedNestedRoot"])
        self.assertEqual(1, out["afterFirstBurst"]["calls"])
        self.assertEqual(40, out["afterFirstBurst"]["count"])
        self.assertEqual(2, out["callsAfterError"])
        self.assertTrue(out["barHasRetry"])
        self.assertEqual(2, out["callsBlockedByCircuitBreaker"], "circuit breaker must stop auto-loads after error")
        self.assertEqual(3, out["afterRetry"]["calls"])
        self.assertEqual(60, out["afterRetry"]["count"])
        self.assertFalse(out["afterRetry"]["hasMore"])
        self.assertIn("已展示全部 60 条", out["afterRetry"]["barHtml"])
        self.assertEqual(0, out["scrollTopAfterTopClick"])
        self.assertFalse(out["afterToggle"])
        self.assertTrue(out["ioDisconnected"])

    def test_auto_scroll_module_does_not_burst_when_slow_load_pushes_sentinel_out_of_view(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for auto-scroll.js runtime verification")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const src = fs.readFileSync(process.argv[1], "utf8");

(async () => {
  let ioCallback = null;
  let sentinelTop = 500;
  function makeEl(tag) {
    const attrs = {};
    const listeners = {};
    const el = {
      tagName: tag.toUpperCase(),
      className: "",
      hidden: false,
      children: [],
      parentElement: null,
      parentNode: null,
      innerHTML: "",
      scrollTop: 0,
      setAttribute(k, v) { attrs[k] = String(v); },
      getAttribute(k) { return attrs[k]; },
      appendChild(c) { c.parentElement = el; c.parentNode = el; el.children.push(c); return c; },
      removeChild(c) { el.children = el.children.filter((x) => x !== c); c.parentNode = null; },
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      removeEventListener() {},
      getBoundingClientRect() {
        if (el.className === "mc-as-sentinel") return { top: sentinelTop, bottom: sentinelTop + 1 };
        return { top: 0, bottom: 700 };
      },
    };
    return el;
  }
  const scrollRoot = makeEl("div");
  const host = makeEl("div");
  scrollRoot.appendChild(host);

  const ctx = vm.createContext({
    setTimeout,
    clearTimeout,
    Date,
    CustomEvent: function CustomEvent(t, init) { this.type = t; this.detail = init && init.detail; },
    document: { body: makeEl("body"), documentElement: makeEl("html"), createElement: makeEl },
    window: {
      innerHeight: 700,
      getComputedStyle: (el) => ({ overflowY: el === scrollRoot ? "auto" : "visible" }),
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {},
      matchMedia: () => ({ matches: true }),
    },
    IntersectionObserver: function FakeIO(cb) {
      ioCallback = cb;
      this.observe = () => {};
      this.disconnect = () => {};
    },
  });
  vm.runInContext(src, ctx);

  let calls = 0;
  let cursor = 0;
  const ctrl = ctx.window.MemoryAutoScroll.mount({
    host,
    minIntervalMs: 50,
    maxAutoBurst: 5,
    hasMore: () => cursor < 300,
    getCount: () => cursor,
    getCursor: () => cursor,
    onLoadMore: async () => {
      calls += 1;
      await new Promise((r) => setTimeout(r, 65));
      cursor += 60;
      sentinelTop += 2800;
    },
  });

  // Trigger once without dispatching fake IO exit callback: slow load pushes sentinel to 3300px,
  // auto-scroll MUST re-measure rect and strictly stop after 1 page.
  ioCallback([{ isIntersecting: true }]);
  await new Promise((r) => setTimeout(r, 260));
  const afterSlowLoad = { calls, cursor, sentinelTop };
  ctrl.destroy();
  process.stdout.write(JSON.stringify({ afterSlowLoad }));
})();
"""
        proc = subprocess.run([node, "-e", code, str(PAGES / "auto-scroll.js")], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, proc.returncode, f"Node harness failed:\n{proc.stderr}\n{proc.stdout}")
        out = json.loads(proc.stdout)
        self.assertEqual(1, out["afterSlowLoad"]["calls"], "慢请求将哨兵推出视口后严禁连发失控")
        self.assertEqual(60, out["afterSlowLoad"]["cursor"])

    def test_people_js_incremental_offset_pagination_breaks_120_cap_and_resets_on_filter(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for people.js pagination verification")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const autoScrollSrc = fs.readFileSync(process.argv[1], "utf8");
const peopleSrc = fs.readFileSync(process.argv[2], "utf8");

(async () => {
  const nodes = {};
  const makeNode = (id) => {
    const attrs = {};
    const listeners = {};
    const node = {
      id,
      hidden: false,
      _html: "",
      textContent: "",
      value: "",
      children: [],
      dataset: {},
      get innerHTML() { return this._html; },
      set innerHTML(v) { this._html = String(v); },
      insertAdjacentHTML(_pos, html) { this._html += String(html); },
      appendChild(child) { node.children.push(child); return child; },
      removeChild(child) { node.children = node.children.filter((c) => c !== child); },
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      removeEventListener() {},
      dispatch(type, evt) { (listeners[type] || []).forEach((fn) => fn(evt || {})); },
      setAttribute(k, v) { attrs[k] = String(v); },
      getAttribute(k) { return attrs[k]; },
      querySelectorAll() { return []; },
      getBoundingClientRect() { return { top: 2400, bottom: 2401 }; },
      focus() {},
    };
    return node;
  };

  const allPeople = Array.from({ length: 150 }, (_, i) => ({
    user_id: `u${i + 1}`,
    display_name: i < 5 ? `关键词人${i + 1}` : `朋友${i + 1}`,
    weight: 100 - (i % 80),
    band: i === 0 ? "imprint" : "close",
    band_label: i === 0 ? "刻骨的人" : "亲近的人",
    memory_count: 3,
    imprint_count: i === 0 ? 1 : 0,
    days_since_last: 1,
    top: [{ content: `记忆${i + 1}` }],
  }));

  const calls = [];
  const bridge = {
    onContext() { return () => {}; },
    apiGet(endpoint, params) {
      if (endpoint === "page/people") {
        calls.push(Object.assign({}, params));
        const q = String((params && params.q) || "");
        const filtered = q ? allPeople.filter((p) => p.display_name.includes(q)) : allPeople;
        const limit = Number((params && params.limit) || 48);
        const offset = Number((params && params.offset) || 0);
        return Promise.resolve({
          success: true,
          data: { items: filtered.slice(offset, offset + limit), bots: [], total: filtered.length },
        });
      }
      if (endpoint === "page/ui-preferences") return Promise.resolve({ success: true, data: {} });
      if (endpoint === "page/maintenance/summary_status") return Promise.resolve({ success: true, data: { status: null } });
      return Promise.resolve({ success: true, data: {} });
    },
  };

  const ctx = vm.createContext({
    location: { search: "", origin: "null" },
    URLSearchParams,
    setTimeout,
    clearTimeout,
    Date,
    document: {
      documentElement: { dataset: {} },
      body: makeNode("body"),
      getElementById(id) { return nodes[id] || (nodes[id] = makeNode(id)); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
      createElement: undefined,
    },
    window: {
      AstrBotPluginPage: bridge,
      innerHeight: 900,
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {},
    },
  });
  ctx.document.createElement = (tag) => makeNode(tag);
  vm.runInContext(autoScrollSrc, ctx);
  vm.runInContext(peopleSrc, ctx);
  await new Promise((r) => setTimeout(r, 30));

  const page1 = vm.runInContext("({count: state.items.length, total: state.total, offset: state.offset, hasMore: state.hasMore})", ctx);
  await vm.runInContext("loadMore()", ctx);
  await vm.runInContext("loadMore()", ctx);
  await vm.runInContext("loadMore()", ctx);
  const allLoaded = vm.runInContext("({count: state.items.length, total: state.total, offset: state.offset, hasMore: state.hasMore})", ctx);

  // Changing filter resets offset to 0 and loads filtered list cleanly
  vm.runInContext('state.query = "关键词人";', ctx);
  await vm.runInContext("load()", ctx);
  const afterFilter = vm.runInContext("({count: state.items.length, total: state.total, offset: state.offset, hasMore: state.hasMore})", ctx);

  process.stdout.write(JSON.stringify({ page1, allLoaded, afterFilter, calls }));
})();
"""
        proc = subprocess.run(
            [node, "-e", code, str(PAGES / "auto-scroll.js"), str(PAGES / "people.js")],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(0, proc.returncode, f"Node harness failed:\n{proc.stderr}\n{proc.stdout}")
        out = json.loads(proc.stdout)
        self.assertEqual({"count": 48, "total": 150, "offset": 48, "hasMore": True}, out["page1"])
        self.assertEqual({"count": 150, "total": 150, "offset": 150, "hasMore": False}, out["allLoaded"])
        self.assertEqual({"count": 5, "total": 5, "offset": 5, "hasMore": False}, out["afterFilter"])
        self.assertEqual([0, 48, 96, 144, 0], [c["offset"] for c in out["calls"]])

    def test_app_js_inspect_and_batch_views_syntax_and_pagination_helpers(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for app.js verification")
        # Syntax check for all 3 JS files
        for filename in ("auto-scroll.js", "app.js", "people.js"):
            res = subprocess.run([node, "--check", str(PAGES / filename)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(0, res.returncode, f"{filename} syntax error:\n{res.stderr}")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const ctx = vm.createContext({
  document: { documentElement: { dataset: {} }, readyState: "loading", addEventListener() {} },
  window: { addEventListener() {} },
});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const res = vm.runInContext(`({
  inspectPageSize: INSPECT_PAGE_SIZE,
  paramsPage0: buildInspectParams({ scope: "", q: "拿铁", visibility: "", lifecycle: "", memoryType: "", target: "", ownerBot: "" }, 0, 60),
  paramsPage2: buildInspectParams({ scope: "group", target: "g1", q: "" }, 120, 60),
  inspectHtml: VIEWS.inspect.render({ memories: [{ id: "m1", content: "hello", memory_type: "fact", scope: "private", importance: 0.5 }], filters: {}, hasMore: true, nextOffset: 60, bots: [] }),
  quarantineHtml: VIEWS.quarantine.render({ total: 120, legacy_failures: 0, batches: [{ id: "sb_1", session_id: "s1", scope: "private", event_count: 5, last_error: "err", updated_at: "2026-11-27" }] }),
  queueHtml: VIEWS.queue.render({ total: 80, batches: [{ id: "sb_2", session_id: "s1", scope: "private", event_count: 5, last_error: "", updated_at: "2026-11-27" }], recovery: null }),
  processedHtml: VIEWS.processed.render({ total: 90, batches: [{ id: "sb_3", session_id: "s1", scope: "private", state: "completed", event_count: 5, last_error: "", updated_at: "2026-11-27" }] }),
})`, ctx);
process.stdout.write(JSON.stringify(res));
"""
        proc = subprocess.run([node, "-e", code, str(PAGES / "app.js")], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, proc.returncode, f"Node harness failed:\n{proc.stderr}\n{proc.stdout}")
        out = json.loads(proc.stdout)
        self.assertEqual(60, out["inspectPageSize"])
        self.assertIn("limit=60&offset=0", out["paramsPage0"])
        self.assertIn("scope=all", out["paramsPage0"])
        self.assertIn("limit=60&offset=120", out["paramsPage2"])
        self.assertIn("group_id=g1", out["paramsPage2"])
        self.assertIn('id="inspectAutoScroll"', out["inspectHtml"])
        self.assertIn('id="inspectCount"', out["inspectHtml"])
        for key in ("quarantineHtml", "queueHtml", "processedHtml"):
            self.assertIn('id="batchAutoScroll"', out[key])
            self.assertIn('id="batchRowsList"', out[key])
            self.assertNotIn("qPrevBtn", out[key])
            self.assertNotIn("qNextBtn", out[key])


if __name__ == "__main__":
    unittest.main()
