"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..");
const PANEL_DIR = path.join(ROOT, "pages", "记忆面板");
const SCHEMA_PATH = path.join(ROOT, "_conf_schema.json");
const ENGINE_PATH = path.join(PANEL_DIR, "search-engine.js");
const APP_JS_PATH = path.join(PANEL_DIR, "app.js");
const LEGACY_HTML_PATH = path.join(PANEL_DIR, "legacy.html");

const engine = require(ENGINE_PATH);
const realSchema = JSON.parse(fs.readFileSync(SCHEMA_PATH, "utf8"));

function cloneSchemaWithVectorPrecision(optionsKey = "options") {
  const schema = JSON.parse(JSON.stringify(realSchema));
  const fieldDef = {
    type: "string",
    default: "float32",
    description: "向量存储精度",
    hint: "控制记忆向量在数据库与内存快照中的保存精度。标准精度 float32 精度无损，半精度 float16 空间直降 75%。",
  };
  fieldDef[optionsKey] = ["float32", "float16"];
  schema.retrieval_advanced.items.vector_precision = fieldDef;
  return schema;
}

function loadAppConfigRuntime() {
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");
  const startMarker = "/* ============================================================\r\n   视图：模块配置";
  const startAlt = "/* ============================================================\n   视图：模块配置";
  const startIdx = appSource.indexOf(startMarker) >= 0 ? appSource.indexOf(startMarker) : appSource.indexOf(startAlt);
  const endMarker = "/* ============================================================\r\n   视图：权限拓扑";
  const endAlt = "/* ============================================================\n   视图：权限拓扑";
  const endIdx = appSource.indexOf(endMarker) >= 0 ? appSource.indexOf(endMarker) : appSource.indexOf(endAlt);
  assert.ok(startIdx > 0 && endIdx > startIdx, "应能在 app.js 中定位模块配置与全局配置搜索区块");

  const slice = appSource.slice(startIdx, endIdx);
  const views = {};
  const timers = [];
  const state = {
    view: "overview",
    group: "overview",
    theme: "light",
    mode: "standard",
    configSchema: null,
    configModule: "appearance",
  };
  const goCalls = [];
  const sandbox = {
    window: {
      MemorySearchEngine: engine,
      setTimeout: (fn, ms) => {
        timers.push({ fn, ms, cleared: false });
        return timers.length;
      },
      clearTimeout: (id) => {
        if (id > 0 && timers[id - 1]) timers[id - 1].cleared = true;
      },
      matchMedia: () => ({ matches: false }),
    },
    navigator: { platform: "Win32", userAgent: "Win64" },
    document: {
      activeElement: null,
      contains: () => true,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: () => {},
      createElement: () => ({
        addEventListener: () => {},
        classList: { add: () => {}, remove: () => {}, toggle: () => {} },
        setAttribute: () => {},
      }),
      body: { appendChild: () => {} },
    },
    requestAnimationFrame: (fn) => fn(),
    prefersReducedMotion: () => false,
    state,
    NAV: [
      { id: "overview", label: "总览", icon: "gauge", views: ["overview"] },
      { id: "settings", label: "设置", icon: "sliders", views: ["config", "acl"] },
    ],
    VIEWS: views,
    defineView: (id, cfg) => {
      views[id] = Object.assign({ id }, cfg);
    },
    $: () => null,
    $$: () => [],
    esc: engine.escapeHtml,
    compact: (v, fallback) => {
      const t = String(v ?? "").trim();
      return t || (fallback === undefined ? "" : fallback);
    },
    clip: (v, max) => {
      const t = String(v ?? "").trim();
      return t.length > max ? t.slice(0, max) + "…" : t;
    },
    fmtInt: (v) => String(Math.round(Number(v) || 0)),
    icon: (name, cls) => `<span class="${cls || "nav-icon"}">${name}</span>`,
    card: (title, sub, body, actions, extra) =>
      `<section class="card ${extra || ""}"><div class="card-head"><div><h3>${engine.escapeHtml(title)}</h3>` +
      (sub ? `<div class="card-sub">${engine.escapeHtml(sub)}</div>` : "") +
      `</div><div class="card-head-actions">${actions || ""}</div></div>${body || ""}</section>`,
    emptyState: (t, s) => `<div class="empty"><b>${engine.escapeHtml(t)}</b><span>${engine.escapeHtml(s)}</span></div>`,
    apiGet: async () => state.configSchema,
    apiPost: async () => ({ ok: true }),
    withBusy: async (_t, fn) => fn(),
    toast: () => {},
    invalidatePool: () => {},
    syncPalette: () => {},
    go: async (view, opts) => {
      goCalls.push({ view, opts, module: state.configModule });
      state.view = view;
    },
  };
  views.overview = { id: "overview", title: "总览", navLabel: "总览", hint: "记忆库整体状态" };
  views.acl = { id: "acl", title: "权限拓扑", navLabel: "权限拓扑", hint: "窗口授权矩阵" };

  vm.runInNewContext(
    slice +
      "\nthis.__exports = { MODULE_LABELS, moduleLabel, moduleSubtitle, CONFIG_COMMON_KEYS, CONFIG_OPTION_LABELS, CONFIG_CHOICE_CARDS, orderedCommonKeys, renderChoiceCards, buildConfigSearchCatalog, runConfigSearchQuery, applyPendingConfigFocus, configSearchState, activateConfigSearchHit, openConfigSearch, closeConfigSearch, bindSmoothDetails };",
    sandbox
  );

  return {
    exports: sandbox.__exports,
    views,
    state,
    goCalls,
    timers,
  };
}

test("search-engine: 5-layer fuzzy search covers exact, synonym, pinyin, bigram, and 1-char typo", () => {
  const schema = cloneSchemaWithVectorPrecision("options");
  const rt = loadAppConfigRuntime();
  const data = {
    schema,
    values: {},
    protected_keys: ["visibility.allow_group_public_in_private"],
    protected_modules: ["visibility"],
  };
  const { catalog, moduleCount, fieldCount } = rt.exports.buildConfigSearchCatalog(data);
  const schemaModules = Object.keys(schema);
  const expectedFields = schemaModules.reduce((n, m) => n + Object.keys(schema[m].items || {}).length, 0);

  assert.equal(moduleCount, schemaModules.length);
  assert.equal(fieldCount, expectedFields);
  assert.ok(moduleCount >= 29);
  assert.ok(fieldCount >= 280);

  const t0 = performance.now();
  const index = engine.prepare(catalog, {
    getTitle: (it) => it.title,
    getDesc: (it) => it.desc,
    getKey: (it) => it.key,
    getGroup: (it) => it.group,
    getAliases: (it) => it.aliases,
    getPriority: (it) => it.priority,
  });
  const prepMs = performance.now() - t0;
  assert.ok(prepMs < 200, `索引构建耗时过长: ${prepMs.toFixed(1)}ms`);

  const cases = [
    ["向量精度", "retrieval_advanced.vector_precision"],
    ["float16", "retrieval_advanced.vector_precision"],
    ["省内存", "retrieval_advanced.vector_precision"],
    ["xljd", "retrieval_advanced.vector_precision"],
    ["xiangliangjingdu", "retrieval_advanced.vector_precision"],
    ["向良精度", "retrieval_advanced.vector_precision"],
    ["flaot16", "retrieval_advanced.vector_precision"],
    ["拟人化", "memory_humanization"],
    ["模糊记忆", "memory_humanization"],
    ["nrh", "memory_humanization"],
    ["拟人华", "memory_humanization"],
    ["跨群", "conversation_memory_advanced.cross_window_group_to_group_enabled"],
    ["群聊衔接", "conversation_memory_advanced.cross_window_group_to_group_enabled"],
    ["kuaqun", "conversation_memory_advanced.cross_window_group_to_group_enabled"],
    ["跨群街接", "conversation_memory_advanced.cross_window_group_to_group_enabled"],
    ["小黑屋", "hide_pending_review|quarantine|pending"],
    ["待复核", "pending"],
    ["dfh", "pending"],
    ["LivingMemory", "livingmemory_migration"],
    ["旧版迁移", "livingmemory_migration"],
    ["记得这个人", "persona_memory"],
    ["jdzgr", "persona_memory"],
    ["跨平台", "identity"],
    ["合并账号", "identity"],
    ["chongpai", "retrieval"],
    ["cp", "retrieval"],
    ["shuaidian", "decay"],
  ];

  for (const [query, expectedPattern] of cases) {
    const s0 = performance.now();
    const hits = engine.search(index, query, { limit: 5 });
    const elapsed = performance.now() - s0;
    assert.ok(hits.length > 0, `查询「${query}」应有命中结果`);
    assert.ok(elapsed < 40, `查询「${query}」耗时过长: ${elapsed.toFixed(2)}ms`);
    const re = new RegExp(expectedPattern, "i");
    const top3Keys = hits.slice(0, 3).map((h) => h.item.key);
    assert.ok(
      top3Keys.some((k) => re.test(k)),
      `查询「${query}」Top-3 应包含 /${expectedPattern}/，实际为: ${top3Keys.join(", ")}`
    );
  }
});

test("search-engine: highlight() is strictly XSS-safe and merges overlapping/adjacent terms cleanly", () => {
  const malicious = '<img src=x onerror="alert(1)"> 向量存储精度 & <script>evil()</script>';
  const html = engine.highlight(malicious, ["向量", "存储精度", "<script>", "onerror"]);
  assert.ok(!html.includes("<img"), "未转义 <img> 标签");
  assert.ok(!html.includes("<script>"), "未转义 <script> 标签");
  assert.ok(html.includes("&lt;img"), "应转义 HTML 尖括号");
  assert.ok(
    html.includes('<mark class="cfg-search-mark">向量存储精度</mark>'),
    "相邻/重叠命中词应合并为单个整洁 <mark> 高亮块"
  );
  assert.ok(
    html.includes('<mark class="cfg-search-mark">&lt;script&gt;</mark>'),
    "匹配到尖括号标签时也必须严格 HTML 转义后再包 <mark>"
  );
  assert.equal((html.match(/<mark\b/g) || []).length, (html.match(/<\/mark>/g) || []).length, "mark 标签必须成对闭合");

  const separated = engine.highlight("检索进阶中的向量存储精度开关", ["检索", "精度"]);
  assert.ok(separated.includes('<mark class="cfg-search-mark">检索</mark>'));
  assert.ok(separated.includes('<mark class="cfg-search-mark">精度</mark>'));
});

test("module config mount: choice cards update hidden input and support keyboard radio navigation", () => {
  const rt = loadAppConfigRuntime();
  const schema = cloneSchemaWithVectorPrecision("options");
  rt.state.configModule = "retrieval_advanced";

  const hiddenInput = { value: "float32" };
  function makeCard(val, active) {
    const listeners = {};
    const classes = new Set(active ? ["is-active"] : []);
    const attrs = { "aria-checked": active ? "true" : "false" };
    return {
      disabled: false,
      focused: false,
      dataset: { choiceKey: "vector_precision", choiceVal: val },
      classList: {
        toggle: (cls, force) => (force ? classes.add(cls) : classes.delete(cls)),
        contains: (cls) => classes.has(cls),
      },
      setAttribute: (k, v) => { attrs[k] = v; },
      getAttribute: (k) => attrs[k],
      focus: function () { this.focused = true; },
      addEventListener: (type, fn) => { listeners[type] = fn; },
      fire: (type, ev) => listeners[type] && listeners[type](ev || {}),
    };
  }
  const card32 = makeCard("float32", true);
  const card16 = makeCard("float16", false);
  const group = { dataset: { choiceGroup: "vector_precision" } };

  const listenersBySel = {
    ".cfg-choice-group": [group],
    ".cfg-choice-card": [card32, card16],
  };
  const origQuery = {
    $: (sel, root) => (sel === "#cfg_vector_precision" && root === group ? hiddenInput : null),
    $$: (sel, root) => (root === group && sel === ".cfg-choice-card" ? [card32, card16] : listenersBySel[sel] || []),
  };
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");
  const mountStart = appSource.indexOf("/* ============================================================\r\n   视图：模块配置");
  const mountAlt = appSource.indexOf("/* ============================================================\n   视图：模块配置");
  const sIdx = mountStart >= 0 ? mountStart : mountAlt;
  const endM = appSource.indexOf("/* ============================================================\r\n   视图：权限拓扑");
  const endAlt = appSource.indexOf("/* ============================================================\n   视图：权限拓扑");
  const eIdx = endM >= 0 ? endM : endAlt;
  const views2 = {};
  const state2 = { view: "config", group: "settings", theme: "light", mode: "standard", configSchema: null, configModule: "retrieval_advanced" };
  vm.runInNewContext(appSource.slice(sIdx, eIdx), {
    window: { MemorySearchEngine: engine, setTimeout: () => 1, clearTimeout: () => {}, matchMedia: () => ({ matches: false }) },
    navigator: { platform: "Win32", userAgent: "Win64" },
    document: { activeElement: null, contains: () => true, querySelector: () => null, querySelectorAll: () => [], addEventListener: () => {}, body: { appendChild: () => {} } },
    requestAnimationFrame: (fn) => fn(),
    prefersReducedMotion: () => false,
    state: state2,
    NAV: [],
    VIEWS: views2,
    defineView: (id, cfg) => { views2[id] = Object.assign({ id }, cfg); },
    $: origQuery.$,
    $$: origQuery.$$,
    esc: engine.escapeHtml,
    compact: (v, f) => String(v ?? "").trim() || (f === undefined ? "" : f),
    clip: (v) => String(v ?? ""),
    fmtInt: (v) => String(v),
    icon: () => "",
    card: () => "",
    emptyState: () => "",
    apiGet: async () => ({}),
    apiPost: async () => ({}),
    withBusy: async (_t, fn) => fn(),
    toast: () => {},
    invalidatePool: () => {},
    syncPalette: () => {},
    go: async () => {},
  });

  views2.config.mount({}, { schema, values: { retrieval_advanced: { vector_precision: "float32" } } });

  card16.fire("click");
  assert.equal(hiddenInput.value, "float16");
  assert.equal(card16.getAttribute("aria-checked"), "true");
  assert.equal(card32.getAttribute("aria-checked"), "false");

  let prevented = false;
  card16.fire("keydown", { key: "ArrowLeft", preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(hiddenInput.value, "float32");
  assert.equal(card32.getAttribute("aria-checked"), "true");
  assert.equal(card32.focused, true);
});

test("module config: all 30 schema modules have pure-Chinese labels and fallback helper works", () => {
  const rt = loadAppConfigRuntime();
  const { MODULE_LABELS, moduleLabel, moduleSubtitle, CONFIG_COMMON_KEYS } = rt.exports;
  const moduleIds = Object.keys(realSchema);

  assert.equal(moduleIds.length, 30);
  for (const modId of moduleIds) {
    const label = moduleLabel(modId, realSchema[modId]);
    assert.ok(MODULE_LABELS[modId], `MODULE_LABELS 缺少模块: ${modId}`);
    assert.ok(/[\u4e00-\u9fff]/.test(label), `模块 ${modId} 标题应包含中文: ${label}`);
    assert.ok(!/[A-Za-z_]/.test(label), `模块 ${modId} 侧栏中文名不应夹带英文或下划线: ${label}`);
  }

  assert.equal(moduleLabel("performance", realSchema.performance), "性能调优");
  assert.equal(moduleLabel("memory_humanization", realSchema.memory_humanization), "拟人化记忆");
  assert.equal(moduleLabel("persona_memory", realSchema.persona_memory), "记得这个人");
  assert.equal(moduleLabel("identity", realSchema.identity), "跨平台身份");
  assert.equal(moduleLabel("livingmemory_migration", realSchema.livingmemory_migration), "旧版记忆迁移");
  assert.equal(moduleLabel("unmapped_future_mod", { description: "未来新模块" }), "未来新模块");
  assert.equal(moduleLabel("unmapped_bare_mod", {}), "unmapped_bare_mod");

  // 副标题优先 hint，不再回落暴露英文 key
  assert.equal(moduleSubtitle("memory_humanization", realSchema.memory_humanization), realSchema.memory_humanization.hint);
  assert.equal(moduleSubtitle("identity", realSchema.identity), "");

  // CONFIG_COMMON_KEYS 补齐核验
  assert.ok(CONFIG_COMMON_KEYS.identity.includes("merge_platform_accounts"));
  assert.ok(CONFIG_COMMON_KEYS.conversation_memory_advanced.includes("cross_window_group_to_group_enabled"));
  assert.equal(CONFIG_COMMON_KEYS.retrieval_advanced[0], "vector_precision");
});

test("module config render: Chinese card title, no bottom section-note, and intuitive vector_precision choice cards for both options and enum", () => {
  for (const keyKind of ["options", "enum"]) {
    const rt = loadAppConfigRuntime();
    const schema = cloneSchemaWithVectorPrecision(keyKind);
    rt.state.configModule = "retrieval_advanced";
    const html = rt.views.config.render({
      schema,
      values: { retrieval_advanced: { vector_precision: "float16" } },
      protected_keys: [],
      protected_modules: [],
    });

    assert.ok(html.includes("<h3>检索进阶</h3>"), "主标题应为中文模块名");
    assert.ok(html.includes(schema.retrieval_advanced.hint), "副标题应展示模块大白话说明");
    assert.ok(!html.includes('class="section-note"'), "不应再渲染底部重复的孤立 section-note");
    assert.ok(html.includes('aria-current="page"'), "当前选中模块应带 aria-current");
    assert.ok(html.includes('data-open-config-search'), "模块导航顶部应含全局配置快搜入口");

    // 向量存储精度应位于明面常规项（在 <details class="config-advanced"> 之前）并渲染分段单选卡
    const advPos = html.indexOf('<details class="config-advanced">');
    const vpPos = html.indexOf('data-config-field="vector_precision"');
    assert.ok(vpPos > 0 && vpPos < advPos, `(${keyKind}) 向量存储精度应直接位于明面区域而非折叠高级项中`);
    assert.ok(html.includes('role="radiogroup" data-choice-group="vector_precision"'), `(${keyKind}) 应渲染分段单选组`);
    assert.ok(html.includes("标准精度"), `(${keyKind}) 应展示 float32 标准精度大白话卡片`);
    assert.ok(html.includes("半精度省流"), `(${keyKind}) 应展示 float16 半精度省流大白话卡片`);
    assert.ok(
      html.includes('data-choice-val="float16"') && html.includes('aria-checked="true"'),
      `(${keyKind}) 当前值 float16 应处于选中态`
    );

    // 侧栏中 0 裸露英文 key
    for (const rawId of ["memory_humanization", "persona_memory", "identity", "LivingMemory 迁移"]) {
      assert.ok(!html.includes("<span>" + rawId + "</span>"), `侧栏不应再出现 ${rawId}`);
    }
  }
});

test("config search jump: expands collapsed advanced details, scrolls to target field, and clears pulse timer cleanly", async () => {
  const rt = loadAppConfigRuntime();
  const schema = cloneSchemaWithVectorPrecision("options");
  rt.state.configSchema = { schema, values: {}, protected_keys: [], protected_modules: [] };

  // 选一个位于「高级项」折叠区内的真实字段
  await rt.exports.activateConfigSearchHit({
    item: {
      kind: "field",
      moduleId: "retrieval_advanced",
      fieldKey: "vector_snapshot_cache_mb",
      isAdvanced: true,
    },
  });

  assert.equal(rt.state.configModule, "retrieval_advanced");
  assert.equal(rt.goCalls.length, 1);
  assert.equal(rt.goCalls[0].view, "config");

  const classes = new Set();
  const detailsNode = { open: false };
  let scrolled = null;
  let focused = false;
  const focusControl = { focus: () => { focused = true; } };
  const fieldNode = {
    offsetWidth: 100,
    closest: (sel) => (sel === "details.config-advanced" ? detailsNode : null),
    scrollIntoView: (opts) => { scrolled = opts; },
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
    },
    querySelector: () => focusControl,
  };
  const fakeRoot = {
    querySelector: (sel) => (sel.includes("vector_snapshot_cache_mb") ? fieldNode : null),
  };

  rt.exports.applyPendingConfigFocus(fakeRoot);

  assert.equal(detailsNode.open, true, "跳向高级项时必须自动展开 details.config-advanced");
  assert.ok(scrolled && scrolled.block === "center", "必须平滑滚动居中");
  assert.equal(focused, true, "必须自动聚焦可编辑控件");
  assert.ok(classes.has("is-search-hit"), "必须施加脉冲高亮类");
  assert.equal(rt.timers.length, 1);
  assert.equal(rt.timers[0].ms, 2200);
  rt.timers[0].fn();
  assert.ok(!classes.has("is-search-hit"), "2.2s 后应自动移除脉冲高亮类");
});

test("search-engine: punctuation-only queries return empty results and punctuation tokens do not break multi-term search", () => {
  const schema = cloneSchemaWithVectorPrecision("options");
  const rt = loadAppConfigRuntime();
  const { catalog } = rt.exports.buildConfigSearchCatalog({
    schema,
    values: {},
    protected_keys: [],
    protected_modules: [],
  });
  const index = engine.prepare(catalog, {
    getTitle: (it) => it.title,
    getDesc: (it) => it.desc,
    getKey: (it) => it.key,
    getGroup: (it) => it.group,
    getAliases: (it) => it.aliases,
    getPriority: (it) => it.priority,
  });

  for (const raw of [".", "-", "（", "___", "···", "  -  ", "？！", "()"]) {
    assert.deepEqual(engine.search(index, raw), [], `纯标点查询 ${JSON.stringify(raw)} 必须返回空数组`);
  }

  const hits = engine.search(index, "检索 · 精度", { limit: 3 });
  assert.ok(hits.length > 0 && hits[0].item.key === "retrieval_advanced.vector_precision", "夹带标点的多词查询应正常命中向量存储精度");
});

test("module config save: immediately syncs state.configSchema.values before module switch", async () => {
  const schema = cloneSchemaWithVectorPrecision("options");
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");
  const sIdx = appSource.indexOf("/* ============================================================\r\n   视图：模块配置");
  const sAlt = appSource.indexOf("/* ============================================================\n   视图：模块配置");
  const start = sIdx >= 0 ? sIdx : sAlt;
  const eIdx = appSource.indexOf("/* ============================================================\r\n   视图：权限拓扑");
  const eAlt = appSource.indexOf("/* ============================================================\n   视图：权限拓扑");
  const end = eIdx >= 0 ? eIdx : eAlt;

  const views = {};
  const state = {
    view: "config",
    group: "settings",
    theme: "light",
    mode: "standard",
    configSchema: { schema, values: { retrieval_advanced: { vector_precision: "float32" } } },
    configModule: "retrieval_advanced",
  };
  let saveClickHandler = null;
  let goAwaited = false;
  const saveBtn = { addEventListener: (t, fn) => { if (t === "click") saveClickHandler = fn; } };
  const vpInput = { type: "hidden", value: "float16" };

  vm.runInNewContext(appSource.slice(start, end), {
    window: { MemorySearchEngine: engine, setTimeout: () => 1, clearTimeout: () => {}, matchMedia: () => ({ matches: false }) },
    navigator: { platform: "Win32", userAgent: "Win64" },
    document: { activeElement: null, contains: () => true, querySelector: () => null, querySelectorAll: () => [], addEventListener: () => {}, body: { appendChild: () => {} } },
    requestAnimationFrame: (fn) => fn(),
    prefersReducedMotion: () => false,
    state,
    NAV: [],
    VIEWS: views,
    defineView: (id, cfg) => { views[id] = Object.assign({ id }, cfg); },
    $: (sel) => (sel === "#configSaveBtn" ? saveBtn : sel === "#cfg_vector_precision" ? vpInput : null),
    $$: () => [],
    esc: engine.escapeHtml,
    compact: (v, f) => String(v ?? "").trim() || (f === undefined ? "" : f),
    clip: (v) => String(v ?? ""),
    fmtInt: (v) => String(v),
    icon: () => "",
    card: () => "",
    emptyState: () => "",
    apiGet: async () => state.configSchema,
    apiPost: async (_path, payload) => ({ values: payload.values }),
    withBusy: async (_t, fn) => fn(),
    toast: () => {},
    invalidatePool: () => {},
    syncPalette: () => {},
    go: async () => { goAwaited = true; },
  });

  views.config.mount({}, state.configSchema);
  assert.ok(typeof saveClickHandler === "function");
  await saveClickHandler();
  assert.equal(state.configSchema.values.retrieval_advanced.vector_precision, "float16", "保存后必须立即同步本地 configSchema 缓存值");
  assert.equal(goAwaited, true, "保存后必须 await go('config')");
});

test("config search modal: smooth open/close transition respects reduced motion and cancels stale close timer on reopen", () => {
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");
  const sIdx = appSource.indexOf("/* ============================================================\r\n   视图：模块配置");
  const sAlt = appSource.indexOf("/* ============================================================\n   视图：模块配置");
  const start = sIdx >= 0 ? sIdx : sAlt;
  const eIdx = appSource.indexOf("/* ============================================================\r\n   视图：权限拓扑");
  const eAlt = appSource.indexOf("/* ============================================================\n   视图：权限拓扑");
  const end = eIdx >= 0 ? eIdx : eAlt;

  let reducedMotion = false;
  const timers = [];
  const modalClasses = new Set();
  const fakeModal = {
    hidden: true,
    offsetWidth: 840,
    classList: {
      add: (c) => modalClasses.add(c),
      remove: (c) => modalClasses.delete(c),
      contains: (c) => modalClasses.has(c),
    },
  };
  const fakeInput = { value: "", focus: () => {}, select: () => {} };
  const fakeBody = { innerHTML: "" };
  const fakeCount = { textContent: "" };
  const fakeClear = { hidden: true };

  const sandbox = {
    window: {
      MemorySearchEngine: engine,
      setTimeout: (fn, ms) => {
        timers.push({ fn, ms, cleared: false });
        return timers.length;
      },
      clearTimeout: (id) => {
        if (id > 0 && timers[id - 1]) timers[id - 1].cleared = true;
      },
      matchMedia: () => ({ matches: reducedMotion }),
    },
    navigator: { platform: "Win32", userAgent: "Win64" },
    document: { activeElement: null, contains: () => true, addEventListener: () => {}, body: { appendChild: () => {} } },
    requestAnimationFrame: (fn) => fn(),
    prefersReducedMotion: () => reducedMotion,
    state: { view: "overview", group: "overview", theme: "light", mode: "standard", configSchema: { schema: realSchema, values: {} }, configModule: "appearance" },
    NAV: [],
    VIEWS: {},
    defineView: () => {},
    $: (sel) => {
      if (sel === "#configSearchModal") return fakeModal;
      if (sel === "#configSearchInput") return fakeInput;
      if (sel === "#configSearchBody") return fakeBody;
      if (sel === "#configSearchCount") return fakeCount;
      if (sel === "#configSearchClear") return fakeClear;
      return null;
    },
    $$: () => [],
    esc: engine.escapeHtml,
    compact: (v, f) => String(v ?? "").trim() || (f === undefined ? "" : f),
    clip: (v) => String(v ?? ""),
    fmtInt: (v) => String(v),
    icon: () => "",
    card: () => "",
    emptyState: () => "",
    apiGet: async () => ({}),
    apiPost: async () => ({}),
    withBusy: async (_t, fn) => fn(),
    toast: () => {},
    invalidatePool: () => {},
    syncPalette: () => {},
    go: async () => {},
  };

  vm.runInNewContext(
    appSource.slice(start, end) + "\nthis.__api = { openConfigSearch, closeConfigSearch };",
    sandbox
  );

  // 正常动效：打开即显示并加 is-open；关闭移除 is-open 并在 180ms 后隐藏
  sandbox.__api.openConfigSearch();
  assert.equal(fakeModal.hidden, false);
  assert.equal(modalClasses.has("is-open"), true);

  sandbox.__api.closeConfigSearch();
  assert.equal(modalClasses.has("is-open"), false);
  assert.equal(fakeModal.hidden, false, "退场动画期间暂不立即 hidden");
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, 180);

  // 关闭动画中途重新打开：必须取消旧定时器，保持可见
  sandbox.__api.openConfigSearch();
  assert.equal(timers[0].cleared, true);
  assert.equal(fakeModal.hidden, false);
  assert.equal(modalClasses.has("is-open"), true);

  // 再次关闭并让定时器走完后隐藏
  sandbox.__api.closeConfigSearch();
  timers[1].fn();
  assert.equal(fakeModal.hidden, true);

  // 减少动效时关闭立即 hidden，不挂定时器
  reducedMotion = true;
  sandbox.__api.openConfigSearch();
  assert.equal(modalClasses.has("is-open"), true);
  const beforeTimers = timers.length;
  sandbox.__api.closeConfigSearch();
  assert.equal(fakeModal.hidden, true);
  assert.equal(timers.length, beforeTimers);
});

test("config advanced collapsible: smooth bidirectional open/close clears inline height/overflow and cancels cleanly on jump", () => {
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");
  const sIdx = appSource.indexOf("/* ============================================================\r\n   视图：模块配置");
  const sAlt = appSource.indexOf("/* ============================================================\n   视图：模块配置");
  const start = sIdx >= 0 ? sIdx : sAlt;
  const eIdx = appSource.indexOf("/* ============================================================\r\n   视图：权限拓扑");
  const eAlt = appSource.indexOf("/* ============================================================\n   视图：权限拓扑");
  const end = eIdx >= 0 ? eIdx : eAlt;

  const timers = [];
  let clickFn = null;
  let currentRenderedHeight = 0;
  const detailsClasses = new Set();
  const bodyStyle = { height: "", opacity: "", overflow: "", transition: "" };
  const fakeBody = {
    style: bodyStyle,
    scrollHeight: 320,
    offsetHeight: 320,
    getBoundingClientRect: () => ({ height: currentRenderedHeight }),
  };
  const fakeSummary = { addEventListener: (t, fn) => { if (t === "click") clickFn = fn; } };
  const fakeDetails = {
    open: false,
    classList: {
      add: (...cs) => cs.forEach((c) => detailsClasses.add(c)),
      remove: (...cs) => cs.forEach((c) => detailsClasses.delete(c)),
      contains: (c) => detailsClasses.has(c),
    },
    querySelector: (sel) => (sel.includes("summary") ? fakeSummary : fakeBody),
  };

  const sandbox = {
    window: {
      MemorySearchEngine: engine,
      setTimeout: (fn, ms) => {
        timers.push({ fn, ms, cleared: false });
        return timers.length;
      },
      clearTimeout: (id) => {
        if (id > 0 && timers[id - 1]) timers[id - 1].cleared = true;
      },
      matchMedia: () => ({ matches: false }),
    },
    navigator: { platform: "Win32", userAgent: "Win64" },
    document: { activeElement: null, contains: () => true, addEventListener: () => {}, body: { appendChild: () => {} } },
    requestAnimationFrame: (fn) => fn(),
    prefersReducedMotion: () => false,
    state: { view: "config", group: "settings", theme: "light", mode: "standard", configSchema: null, configModule: "retrieval_advanced" },
    NAV: [],
    VIEWS: {},
    defineView: () => {},
    $: () => null,
    $$: (sel) => (sel === "details.config-advanced" ? [fakeDetails] : []),
    esc: engine.escapeHtml,
    compact: (v, f) => String(v ?? "").trim() || (f === undefined ? "" : f),
    clip: (v) => String(v ?? ""),
    fmtInt: (v) => String(v),
    icon: () => "",
    card: () => "",
    emptyState: () => "",
    apiGet: async () => ({}),
    apiPost: async () => ({}),
    withBusy: async (_t, fn) => fn(),
    toast: () => {},
    invalidatePool: () => {},
    syncPalette: () => {},
    go: async () => {},
  };

  vm.runInNewContext(appSource.slice(start, end) + "\nthis.__bind = bindSmoothDetails;", sandbox);
  sandbox.__bind({});
  assert.ok(typeof clickFn === "function");

  // 1) 展开动画
  let prevented = false;
  clickFn({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(fakeDetails.open, true);
  assert.equal(bodyStyle.height, "320px");
  assert.equal(bodyStyle.opacity, "1");
  assert.equal(timers.length, 1);
  // 动画结束后必须清空 height 和 overflow，保证绝不裁切内容
  timers[0].fn();
  assert.equal(bodyStyle.height, "");
  assert.equal(bodyStyle.overflow, "");

  // 2) 收起动画中途（is-closing）再次点击：必须立即反向重开，而不是再次误关
  currentRenderedHeight = 320;
  clickFn({ preventDefault: () => {} });
  assert.equal(fakeDetails.open, true, "收起退场期间暂保 open 以呈现平滑高度收缩");
  assert.equal(detailsClasses.has("is-closing"), true);
  assert.equal(bodyStyle.height, "0px");
  assert.equal(bodyStyle.opacity, "0");

  // 模拟收起至 140px 时用户立即再点展开
  currentRenderedHeight = 140;
  clickFn({ preventDefault: () => {} });
  assert.equal(timers[1].cleared, true, "收起中途重开必须取消旧收起定时器");
  assert.equal(detailsClasses.has("is-closing"), false, "收起中途重开必须移除 is-closing");
  assert.equal(fakeDetails.open, true);
  assert.equal(bodyStyle.height, "320px", "应从当前渲染高度平滑展开至目标 scrollHeight");
  assert.equal(bodyStyle.opacity, "1");
  timers[2].fn();
  assert.equal(bodyStyle.height, "");
  assert.equal(bodyStyle.overflow, "");

  // 3) 完整收起流程
  currentRenderedHeight = 320;
  clickFn({ preventDefault: () => {} });
  timers[3].fn();
  assert.equal(fakeDetails.open, false);
  assert.equal(bodyStyle.height, "");
  assert.equal(bodyStyle.overflow, "");
});

test("drawer and confirmation dialog: blur/inert on drawer close and restore focus cleanly", async () => {
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");
  const start = appSource.indexOf("let toastTimer = 0;");
  const end = appSource.indexOf("/* ------------------------------------------------------------\r\n   主题");
  const endAlt = appSource.indexOf("/* ------------------------------------------------------------\n   主题");
  const sliceEnd = end >= 0 ? end : endAlt;
  assert.ok(start > 0 && sliceEnd > start);

  const timers = [];
  const drawerClasses = new Set();
  const scrimClasses = new Set();
  const drawerAttrs = { "aria-hidden": "true" };
  let blurred = false;
  let triggerFocused = false;
  const triggerBtn = { focus: () => { triggerFocused = true; } };
  const insideBtn = { blur: () => { blurred = true; } };
  const fakeDrawer = {
    inert: true,
    classList: {
      add: (c) => drawerClasses.add(c),
      remove: (c) => drawerClasses.delete(c),
      contains: (c) => drawerClasses.has(c),
    },
    setAttribute: (k, v) => { drawerAttrs[k] = v; },
    contains: (el) => el === insideBtn,
  };
  const fakeScrim = {
    hidden: true,
    offsetWidth: 100,
    classList: {
      add: (c) => scrimClasses.add(c),
      remove: (c) => scrimClasses.delete(c),
    },
  };
  const docListeners = {};
  const fakeDoc = {
    activeElement: triggerBtn,
    contains: () => true,
    addEventListener: (t, fn) => { docListeners[t] = fn; },
    removeEventListener: (t) => { delete docListeners[t]; },
    createElement: () => {
      const ovClasses = new Set();
      const ov = {
        className: "",
        innerHTML: "",
        offsetWidth: 420,
        removed: false,
        classList: {
          add: (c) => ovClasses.add(c),
          remove: (c) => ovClasses.delete(c),
          contains: (c) => ovClasses.has(c),
        },
        addEventListener: () => {},
        remove: function () { this.removed = true; },
      };
      return ov;
    },
    body: { appendChild: () => {} },
  };
  const nodes = {
    "#drawer": fakeDrawer,
    "#scrim": fakeScrim,
    "#drawerEyebrow": { textContent: "" },
    "#drawerTitle": { textContent: "" },
    "#drawerBody": { innerHTML: "" },
  };
  const sandbox = {
    window: {
      setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
      clearTimeout: () => {},
      matchMedia: () => ({ matches: false }),
    },
    document: fakeDoc,
    requestAnimationFrame: (fn) => fn(),
    $: (sel) => nodes[sel] || null,
    esc: engine.escapeHtml,
  };
  vm.runInNewContext(
    appSource.slice(start, sliceEnd) + "\nthis.__api = { openDrawer, closeDrawer, showInlineConfirmation };",
    sandbox
  );

  // 打开抽屉：inert=false，记录焦点
  sandbox.__api.openDrawer("记忆标题", "记忆详情", "<p>正文</p>");
  assert.equal(fakeDrawer.inert, false);
  assert.equal(drawerAttrs["aria-hidden"], "false");
  assert.equal(fakeScrim.hidden, false);

  // 关闭抽屉：若内部按钮有焦点必须先 blur，设 inert=true 并归还焦点
  fakeDoc.activeElement = insideBtn;
  sandbox.__api.closeDrawer();
  assert.equal(blurred, true, "关闭抽屉设置 aria-hidden 前必须 blur 内部焦点");
  assert.equal(fakeDrawer.inert, true);
  assert.equal(drawerAttrs["aria-hidden"], "true");
  assert.equal(triggerFocused, true, "关闭抽屉后应归还触发元素焦点");

  // 确认弹窗：Escape 取消并归还焦点
  let confirmTriggerFocused = false;
  fakeDoc.activeElement = { focus: () => { confirmTriggerFocused = true; } };
  const p = sandbox.__api.showInlineConfirmation("删除确认", "确定删除？", "删除");
  assert.ok(typeof docListeners.keydown === "function");
  docListeners.keydown({ key: "Escape", preventDefault: () => {} });
  const res = await p;
  assert.equal(res, false);
  assert.equal(confirmTriggerFocused, true, "关闭确认弹窗后应归还触发元素焦点");
});

test("legacy.html loads the versioned search engine before the panel app", () => {
  const html = fs.readFileSync(LEGACY_HTML_PATH, "utf8");
  const search = /src="\.\/search-engine\.js\?v=([^"]+)"/.exec(html);
  const app = /src="\.\/app\.js\?v=([^"]+)"/.exec(html);
  assert.ok(search && app, "搜索脚本和面板脚本都必须带缓存版本");
  assert.equal(search[1], app[1], "搜索脚本和面板脚本的缓存版本必须一致");
  assert.ok(search.index < app.index, "search-engine.js 必须在 app.js 之前加载");
});

test("search-engine: performance tuning tiers and DB health/slimming shortcuts are discoverable via plain-Chinese aliases", async () => {
  const rt = loadAppConfigRuntime();
  const { catalog } = rt.exports.buildConfigSearchCatalog({
    schema: realSchema,
    values: {},
    protected_keys: [],
    protected_modules: [],
  });
  const index = engine.prepare(catalog, {
    getTitle: (it) => it.title,
    getDesc: (it) => it.desc,
    getKey: (it) => it.key,
    getGroup: (it) => it.group,
    getAliases: (it) => it.aliases,
    getPriority: (it) => it.priority,
  });

  const perfAndDbCases = [
    ["性能调优", "performance"],
    ["低配机", "performance"],
    ["机械硬盘", "performance"],
    ["卡顿", "performance|budget"],
    ["瘦身", "maintenance\\.db_optimize"],
    ["体检", "maintenance\\.db_optimize"],
    ["释放空间", "maintenance\\.db_optimize"],
    ["VACUUM", "maintenance\\.db_optimize"],
    ["压缩", "maintenance\\.db_optimize"],
  ];

  for (const [query, pattern] of perfAndDbCases) {
    const hits = engine.search(index, query, { limit: 5 });
    assert.ok(hits.length > 0, `查询「${query}」应有命中结果`);
    const re = new RegExp(pattern, "i");
    const top3 = hits.slice(0, 3).map((h) => h.item.key);
    assert.ok(
      top3.some((k) => re.test(k)),
      `查询「${query}」Top-3 应包含 /${pattern}/，实际为: ${top3.join(", ")}`
    );
  }

  // Clicking DB health shortcut routes cleanly to migrate view with target anchor
  const dbHit = engine.search(index, "数据库体检", { limit: 3 }).find((h) => h.item.key === "maintenance.db_optimize");
  assert.ok(dbHit, "「数据库体检」应命中 maintenance.db_optimize 快捷入口");
  await rt.exports.activateConfigSearchHit(dbHit);
  assert.equal(rt.goCalls[rt.goCalls.length - 1].view, "migrate");
  assert.equal(rt.state.pendingViewFocus.viewId, "migrate");
  assert.equal(rt.state.pendingViewFocus.target, "dbHealthCard");
});

test("performance view and migrate DB health card: render semantic markup and zero hardcoded hex in new CSS", () => {
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");
  const cssSource = fs.readFileSync(path.join(PANEL_DIR, "app.css"), "utf8");

  // 1) Verify performance view renders hero, clamp banner, 5 tiers, collapsible 12 params, and DB strip
  const perfStart = appSource.indexOf("/* ============================================================\r\n   视图：性能调优");
  const perfAlt = appSource.indexOf("/* ============================================================\n   视图：性能调优");
  const pStart = perfStart >= 0 ? perfStart : perfAlt;
  const bootStart = appSource.indexOf("/* ============================================================\r\n   启动");
  const bootAlt = appSource.indexOf("/* ============================================================\n   启动");
  const pEnd = bootStart >= 0 ? bootStart : bootAlt;
  assert.ok(pStart > 0 && pEnd > pStart, "应在 app.js 中找到 视图：性能调优 区块");

  const views = {};
  vm.runInNewContext(appSource.slice(pStart, pEnd), {
    window: { setTimeout: () => 1, clearTimeout: () => {} },
    state: { view: "performance", pendingViewFocus: null, configSchema: null },
    defineView: (id, cfg) => { views[id] = cfg; },
    $: () => null,
    $$: () => [],
    esc: engine.escapeHtml,
    compact: (v, f) => String(v ?? "").trim() || (f === undefined ? "" : f),
    num: (v, d) => Number(v).toFixed(d || 0).replace(/\.0+$/, ""),
    int: (v) => Math.round(Number(v) || 0),
    fmtInt: (v) => String(Math.round(Number(v) || 0)),
    fmtBytes: (b) => `${Math.round(Number(b) / 1048576)} MB`,
    icon: (name) => `<i>${name}</i>`,
    card: (t, s, b, a, ex) => `<section class="card ${ex || ""}"><h3>${t}</h3><p>${s}</p>${b}${a || ""}</section>`,
    apiGet: async () => ({}),
    apiPost: async () => ({}),
    withBusy: async (_t, fn) => fn(),
    toast: () => {},
    invalidatePool: () => {},
    bindSmoothDetails: () => {},
    prefersReducedMotion: () => false,
    requestAnimationFrame: (fn) => fn(),
    go: async () => {},
  });

  const sampleTuning = {
    profile: "eco",
    profile_label: "省资源",
    effective_tier: "eco",
    effective_tier_label: "省资源",
    override_count: 1,
    overrides: { "performance.sqlite_cache_size_mb": 102 },
    clamped_fields: [
      { key: "performance.sqlite_cache_size_mb", label: "数据库页缓存", reason: "防爆内存保护：已限幅至 102 MB" },
    ],
    hardware: {
      effective_memory_mb: 1024,
      cpu_count: 2,
      memory_source: "cgroup_v2",
      is_32bit: false,
      recommended_tier: "eco",
      recommendation_reason: "检测到容器内存 1.0 GiB，推荐省资源档位。",
    },
    tiers: [
      { id: "auto", label: "智能自动", badge: "默认推荐", tagline: "自动识别", target_scene: "通用", highlights: ["自动识别"] },
      { id: "eco", label: "省资源", badge: "1–2G", tagline: "低内存", target_scene: "小服", highlights: ["float16"] },
      { id: "balanced", label: "均衡推荐", badge: "4–8G", tagline: "均衡", target_scene: "常规", highlights: ["float32"] },
      { id: "turbo", label: "高性能", badge: "16G+", tagline: "高并发", target_scene: "大库", highlights: ["mmap"] },
      { id: "compat", label: "慢盘兼容", badge: "HDD", tagline: "稳妥", target_scene: "机械盘", highlights: ["FULL"] },
    ],
    groups: [{ id: "sqlite", label: "数据库引擎", desc: "引擎参数" }],
    params: [
      {
        key: "performance.sqlite_cache_size_mb",
        group: "sqlite",
        label: "数据库页缓存",
        value_type: "int",
        unit: "MB",
        display_scale: 1,
        min: 4,
        max: 256,
        step: 4,
        hot_reload: true,
        effect_scope: "保存后立即生效",
        summary: "热页缓存",
        up_effect: "调大：读盘更少",
        down_effect: "调小：更省内存",
        tier_default: 8,
        effective_value: 102,
        overridden: true,
        clamped: { key: "performance.sqlite_cache_size_mb", reason: "已限幅" },
      },
    ],
    db_summary: { primary_db_bytes: 52428800, wal_bytes: 1048576, scoped_total_bytes: 2097152, grand_total_bytes: 55574528 },
  };
  const perfHtml = views.performance.render(sampleTuning);
  assert.ok(perfHtml.includes("基于「省资源」· 已微调 1 项"));
  assert.ok(perfHtml.includes("已触发防爆内存安全限幅"));
  assert.ok(perfHtml.includes('data-perf-tier="compat"'));
  assert.ok(perfHtml.includes("展开高级性能微调"));
  assert.ok(perfHtml.includes("调大：读盘更少"));
  assert.ok(perfHtml.includes("前往数据库体检与一键瘦身"));

  // 2) Verify migrate view renderDbHealthCard renders KPIs, vector bar, recommendations, preflight warning, and shrink report
  const migStart = appSource.indexOf("/* ============================================================\r\n   视图：维护与迁移");
  const migAlt = appSource.indexOf("/* ============================================================\n   视图：维护与迁移");
  const mStart = migStart >= 0 ? migStart : migAlt;
  const qStart = appSource.indexOf("/* ============================================================\r\n   视图：待修复批次");
  const qAlt = appSource.indexOf("/* ============================================================\n   视图：待修复批次");
  const mEnd = qStart >= 0 ? qStart : qAlt;
  assert.ok(mStart > 0 && mEnd > mStart, "应在 app.js 中找到 视图：维护与迁移 区块");

  const migViews = {};
  vm.runInNewContext(appSource.slice(mStart, mEnd) + "\nthis.__renderDbHealthCard = renderDbHealthCard;", {
    window: { setTimeout: () => 1, clearTimeout: () => {} },
    state: { view: "migrate", pendingViewFocus: null },
    defineView: (id, cfg) => { migViews[id] = cfg; },
    $: () => null,
    $$: () => [],
    esc: engine.escapeHtml,
    compact: (v, f) => String(v ?? "").trim() || (f === undefined ? "" : f),
    int: (v) => Math.round(Number(v) || 0),
    fmtInt: (v) => String(Math.round(Number(v) || 0)),
    fmtBytes: (b) => `${Math.round(Number(b) / 1048576)} MB`,
    jsonPreview: (o) => JSON.stringify(o),
    card: (t, s, b, a, ex) => `<section class="card ${ex || ""}"><h3>${t}</h3><p>${s}</p>${b}${a || ""}</section>`,
    emptyState: (t, s) => `<div>${t}:${s}</div>`,
    apiTry: async (fn, fb) => fb,
    apiGet: async () => ({}),
    apiPost: async () => ({}),
    withBusy: async (_t, fn) => fn(),
    showInlineConfirmation: async () => true,
    toast: () => {},
    invalidatePool: () => {},
    prefersReducedMotion: () => false,
    requestAnimationFrame: (fn) => fn(),
    go: async () => {},
  });

  const migHtml = migViews.migrate.render({
    preset: { preset: "standard" },
    dbHealth: {
      ok: true,
      health: {
        configured_vector_precision: "float32",
        primary: {
          total_bytes: 104857600,
          files: { db_bytes: 94371840, wal_bytes: 10485760 },
          freelist_bytes: 12582912,
          freelist_count: 3072,
          auto_vacuum: 2,
          vector_precision: "float32",
          embeddings: {
            total_rows: 1000,
            float64_rows: 400,
            float32_rows: 500,
            float16_rows: 100,
            json_rows: 0,
            archived_orphan_rows: 15,
            vector_bytes: 20971520,
            estimated_transcode_savings_bytes: 5242880,
          },
          disk_preflight: { ok: false, message: "磁盘剩余空间不足 2.2 倍主库大小" },
          recommendations: ["检测到 400 条旧版 float64 向量"],
        },
        scoped: { total_bytes: 4194304 },
      },
    },
    dbShrinkReport: {
      ok: true,
      primary: {
        before_bytes: 104857600,
        after_bytes: 73400320,
        bytes_reclaimed: 31457280,
        vacuum_mode: "incremental_vacuum",
        transcode: { transcoded: 400, purged_orphans: 15 },
      },
      notice: "",
    },
    output: null,
  });
  assert.ok(migHtml.includes("数据库体检与一键瘦身"));
  assert.ok(migHtml.includes("一键常规无损瘦身（推荐）"));
  assert.ok(migHtml.includes("深度整理压缩（全量 VACUUM）"));
  assert.ok(migHtml.includes("磁盘剩余空间不足 2.2 倍主库大小"));
  assert.ok(migHtml.includes("最近一次瘦身结果"));
  assert.ok(migHtml.includes("增量无损回收"));
  assert.ok(
    migHtml.includes("仅整理向量存储、清理已归档/无主向量索引与超期内部回执，绝不删除任何记忆、聊天原文、人物关系或配置"),
    "体检卡瘦身说明必须明确提示绝不删除任何业务数据"
  );

  // Also verify scoped disk_preflight warning renders when primary preflight passes
  const scopedWarnHtml = migViews.migrate.render({
    preset: { preset: "standard" },
    dbHealth: {
      ok: true,
      health: {
        configured_vector_precision: "float32",
        primary: {
          total_bytes: 10485760,
          files: { db_bytes: 10485760, wal_bytes: 0 },
          freelist_bytes: 0,
          freelist_count: 0,
          auto_vacuum: 2,
          vector_precision: "float32",
          embeddings: { total_rows: 0, float64_rows: 0, float32_rows: 0, float16_rows: 0, json_rows: 0, archived_orphan_rows: 0, vector_bytes: 0, estimated_transcode_savings_bytes: 0 },
          disk_preflight: { ok: true, available_free_bytes: 512 * 1048576, required_free_bytes: 96 * 1048576 },
          recommendations: [],
        },
        scoped: {
          total_bytes: 4194304,
          disk_preflight: { ok: false, reason: "disk_usage_unavailable", message: "无法读取副库磁盘剩余空间，已安全阻断副库全量 VACUUM。" },
        },
      },
    },
    dbShrinkReport: null,
    output: null,
  });
  assert.ok(scopedWarnHtml.includes("副库深度压缩空间预检未通过"));
  assert.ok(scopedWarnHtml.includes("无法读取副库磁盘剩余空间"));

  // 3) Verify new CSS section 8 has ZERO hardcoded hex colors and covers mobile touch & narrow-screen rules
  const sec8Idx = cssSource.indexOf("/* ---------- 8. 性能调优视图与数据库体检瘦身卡片");
  assert.ok(sec8Idx > 0, "app.css 应包含第 8 节性能调优与数据库体检样式");
  const sec8Css = cssSource.slice(sec8Idx);
  assert.equal(sec8Css.match(/#[0-9a-fA-F]{3,8}\b/g), null, "新增性能调优与数据库体检 CSS 严禁包含硬编码色值");
  assert.ok(sec8Css.includes("@media (max-width: 520px)") && sec8Css.includes("repeat(2, minmax(0, 1fr))"), "<=520px .db-kpi-grid 应为 2 列网格");
  assert.ok(sec8Css.includes("@media (max-width: 340px)") && sec8Css.includes("grid-template-columns: minmax(0, 1fr)"), "<=340px .db-kpi-grid 应退化为单列");
  assert.ok(sec8Css.includes(".db-action-btns .btn") && sec8Css.includes("min-height: 38px"), "移动端长文案瘦身按钮应允许换行且触控高 >=38px");
  assert.ok(sec8Css.includes(".perf-param-ctrl select") && sec8Css.includes("min-height: 36px"), "移动端参数下拉与输入框应满宽且触控高 >=36px");
  assert.ok(sec8Css.includes(".db-health-card .card-head-actions"), "移动端数据库体检卡片按钮组应允许折行");
  assert.ok(sec8Css.includes(".content > .is-inplace-refresh") && sec8Css.includes("animation: none"), "原地局部刷新容器应禁用 viewIn 滑入动画重播");
});

test("go(viewId, { inPlace: true }) skips skeleton flash, suppresses viewIn animation, and preserves scroll & focus", async () => {
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");
  const routeStart = appSource.indexOf("/* ------------------------------------------------------------\r\n   路由");
  const routeAlt = appSource.indexOf("/* ------------------------------------------------------------\n   路由");
  const rStart = routeStart >= 0 ? routeStart : routeAlt;
  const compStart = appSource.indexOf("/* ------------------------------------------------------------\r\n   组件片段");
  const compAlt = appSource.indexOf("/* ------------------------------------------------------------\n   组件片段");
  const rEnd = compStart >= 0 ? compStart : compAlt;
  assert.ok(rStart > 0 && rEnd > rStart, "应在 app.js 中找到 路由 区块");

  const skeletonWrites = [];
  let innerHtmlHistory = [];
  let mountedNode = null;
  let focusCalls = [];
  const makeFakeEl = (id) => {
    const classes = new Set();
    return {
      id: id || "",
      disabled: false,
      _html: "",
      children: [],
      get firstElementChild() { return this.children[0] || null; },
      get innerHTML() { return this._html; },
      set innerHTML(v) {
        this._html = String(v);
        if (this.id === "content") {
          innerHtmlHistory.push(this._html);
          if (this._html.includes("skeleton")) skeletonWrites.push(this._html);
        }
        if (this._html === "") this.children = [];
      },
      appendChild(child) { this.children.push(child); mountedNode = child; return child; },
      classList: {
        add(c) { classes.add(c); },
        contains(c) { return classes.has(c); },
      },
      contains(target) { return Boolean(target && target.__insideHost); },
      scrollTop: 0,
      focus(opts) { focusCalls.push({ id: this.id, opts }); },
    };
  };

  const host = makeFakeEl("content");
  const saveBtn = makeFakeEl("perfSaveBtn");
  saveBtn.__insideHost = true;
  const toasts = [];
  let loadCount = 0;
  let failNext = false;
  let scrollToCalls = [];

  const sandbox = {
    NAV_KEY: "mc_nav",
    VIEWS: {
      performance: {
        title: "性能调优",
        eyebrow: "Settings · Performance",
        hint: "hint",
        async load() {
          loadCount += 1;
          if (failNext) throw new Error("network down");
          return { rev: loadCount };
        },
        render(payload) { return `<div data-rev="${payload.rev}">rev ${payload.rev}</div>`; },
        mount() {},
      },
    },
    state: { view: "", group: "", mode: "standard" },
    findGroupOf: () => "settings",
    renderRail: () => {},
    esc: engine.escapeHtml,
    toast: (msg, tone) => toasts.push({ msg, tone }),
    $: (sel, root) => {
      if (sel === "#content") return host;
      if (sel === "#perfSaveBtn" && root) return saveBtn;
      if (sel === "#viewEyebrow" || sel === "#viewTitle" || sel === "#viewHint") return { textContent: "" };
      return null;
    },
    document: {
      title: "",
      activeElement: null,
      createElement: () => makeFakeEl(""),
    },
    window: {
      localStorage: { setItem() {} },
      scrollY: 0,
      scrollTo(x, y) { scrollToCalls.push([x, y]); },
    },
  };
  vm.runInNewContext(appSource.slice(rStart, rEnd) + "\nthis.__go = go;", sandbox);

  // 1) Initial navigation shows skeleton and does NOT tag is-inplace-refresh
  await sandbox.__go("performance");
  assert.equal(skeletonWrites.length, 1);
  assert.equal(mountedNode.classList.contains("is-inplace-refresh"), false);

  // 2) In-place refresh on the same view: zero skeleton write, tagged is-inplace-refresh, restores scroll & focus
  host.scrollTop = 345;
  sandbox.window.scrollY = 180;
  sandbox.document.activeElement = saveBtn;
  await sandbox.__go("performance", { inPlace: true });
  assert.equal(skeletonWrites.length, 1, "inPlace 刷新不得写入 220px skeleton 骨架屏");
  assert.equal(mountedNode.classList.contains("is-inplace-refresh"), true, "inPlace 刷新容器必须带 is-inplace-refresh");
  assert.equal(host.scrollTop, 345, "inPlace 刷新必须保留 #content scrollTop");
  assert.deepEqual(scrollToCalls[scrollToCalls.length - 1], [0, 180], "inPlace 刷新在移动端应保留 window.scrollY");
  assert.equal(focusCalls.length, 1);
  assert.equal(focusCalls[0].id, "perfSaveBtn");

  // 3) Reload failure during inPlace preserves existing DOM and emits an error toast
  const prevChild = host.firstElementChild;
  failNext = true;
  await sandbox.__go("performance", { inPlace: true });
  assert.equal(host.firstElementChild, prevChild, "inPlace 刷新失败时不得销毁当前页面");
  assert.ok(toasts.some((t) => t.tone === "error" && t.msg.includes("network down")));
});

test("performance save triggers inPlace refresh; migrate DB health & shrink update in place without clearing form inputs", async () => {
  const appSource = fs.readFileSync(APP_JS_PATH, "utf8");

  // --- Part 1: performance view applyTuning calls go('performance', { inPlace: true }) ---
  const perfStart = appSource.indexOf("/* ============================================================\r\n   视图：性能调优");
  const perfAlt = appSource.indexOf("/* ============================================================\n   视图：性能调优");
  const pStart = perfStart >= 0 ? perfStart : perfAlt;
  const bootStart = appSource.indexOf("/* ============================================================\r\n   启动");
  const bootAlt = appSource.indexOf("/* ============================================================\n   启动");
  const pEnd = bootStart >= 0 ? bootStart : bootAlt;

  const perfGoCalls = [];
  const perfListeners = {};
  const makeBtn = (id) => ({
    id,
    disabled: false,
    textContent: "",
    addEventListener(type, fn) { perfListeners[`${id}:${type}`] = fn; },
  });
  const perfViews = {};
  vm.runInNewContext(appSource.slice(pStart, pEnd), {
    window: { setTimeout: () => 1, clearTimeout: () => {} },
    state: { view: "performance", pendingViewFocus: null, configSchema: {} },
    defineView: (id, cfg) => { perfViews[id] = cfg; },
    $: (sel) => {
      if (sel === "#perfSaveBtn") return makeBtn("perfSaveBtn");
      if (sel === "#perfResetAllBtn") return makeBtn("perfResetAllBtn");
      return null;
    },
    $$: () => [],
    esc: engine.escapeHtml,
    compact: (v, f) => String(v ?? "").trim() || (f === undefined ? "" : f),
    num: (v) => String(v),
    int: (v) => Math.round(Number(v) || 0),
    fmtInt: (v) => String(Math.round(Number(v) || 0)),
    fmtBytes: (b) => `${b} B`,
    icon: () => "",
    card: (_t, _s, b) => b,
    apiGet: async () => ({}),
    apiPost: async () => ({ tuning: { hot_reload: { read_pool_generation: 2 }, clamped_fields: [] } }),
    withBusy: async (_t, fn) => fn(),
    toast: () => {},
    invalidatePool: () => {},
    bindSmoothDetails: () => {},
    prefersReducedMotion: () => false,
    requestAnimationFrame: (fn) => fn(),
    go: async (viewId, opts) => { perfGoCalls.push({ viewId, opts }); },
  });
  perfViews.performance.mount({}, { profile: "balanced", override_count: 0, overrides: {}, params: [] });
  await perfListeners["perfSaveBtn:click"]();
  await perfListeners["perfResetAllBtn:click"]();
  assert.equal(perfGoCalls.length, 2);
  assert.equal(perfGoCalls[0].viewId, "performance");
  assert.equal(Boolean(perfGoCalls[0].opts && perfGoCalls[0].opts.inPlace), true, "性能调优保存必须使用 inPlace 刷新");
  assert.equal(Boolean(perfGoCalls[1].opts && perfGoCalls[1].opts.inPlace), true, "恢复档位默认必须使用 inPlace 刷新");

  // --- Part 2: migrate view DB health refresh / shrink / preview preserve #portablePath, #lmPath, #releaseBatchId ---
  const migStart = appSource.indexOf("/* ============================================================\r\n   视图：维护与迁移");
  const migAlt = appSource.indexOf("/* ============================================================\n   视图：维护与迁移");
  const mStart = migStart >= 0 ? migStart : migAlt;
  const qStart = appSource.indexOf("/* ============================================================\r\n   视图：待修复批次");
  const qAlt = appSource.indexOf("/* ============================================================\n   视图：待修复批次");
  const mEnd = qStart >= 0 ? qStart : qAlt;

  const migViews = {};
  const migGoCalls = [];
  const migToasts = [];
  const confirmCalls = [];
  let healthFetchCount = 0;
  let optimizePayloads = [];

  const makeSlotEl = (id) => ({
    id,
    innerHTML: "",
    contains: () => false,
  });
  const dbHealthSlot = makeSlotEl("dbHealthSlot");
  const migrateOutputSlot = makeSlotEl("migrateOutputSlot");
  const portablePathInput = { id: "portablePath", value: "/data/my_export.jsonl" };
  const lmPathInput = { id: "lmPath", value: "/data/livingmemory.db" };
  const releaseBatchInput = { id: "releaseBatchId", value: "sb_keep_me_99" };

  let slotButtons = {};
  const makeSlotButton = (id) => {
    const btn = {
      id,
      disabled: false,
      textContent: id === "dbHealthRefreshBtn" ? "刷新体检" : id,
      handlers: {},
      addEventListener(type, fn) { this.handlers[type] = fn; },
    };
    slotButtons[id] = btn;
    return btn;
  };
  let staticButtons = {};
  const makeStaticButton = (id) => {
    if (!staticButtons[id]) {
      staticButtons[id] = {
        id,
        handlers: {},
        addEventListener(type, fn) { this.handlers[type] = fn; },
      };
    }
    return staticButtons[id];
  };
  const resetSlotButtons = () => {
    slotButtons = {};
    makeSlotButton("dbHealthRefreshBtn");
    makeSlotButton("dbGoPerfBtn");
    makeSlotButton("dbShrinkRegularBtn");
    makeSlotButton("dbShrinkFullBtn");
  };
  resetSlotButtons();
  const origSlotDesc = { value: "" };
  Object.defineProperty(dbHealthSlot, "innerHTML", {
    get() { return origSlotDesc.value; },
    set(v) {
      origSlotDesc.value = String(v);
      resetSlotButtons();
    },
  });

  vm.runInNewContext(appSource.slice(mStart, mEnd), {
    window: { setTimeout: () => 1, clearTimeout: () => {} },
    document: { activeElement: portablePathInput },
    state: { view: "migrate", pendingViewFocus: null },
    defineView: (id, cfg) => { migViews[id] = cfg; },
    $: (sel, root) => {
      if (sel === "#dbHealthSlot") return dbHealthSlot;
      if (sel === "#migrateOutputSlot") return migrateOutputSlot;
      if (sel === "#portablePath") return portablePathInput;
      if (sel === "#lmPath") return lmPathInput;
      if (sel === "#releaseBatchId") return releaseBatchInput;
      if (sel === "#dbHealthRefreshBtn") return slotButtons.dbHealthRefreshBtn;
      if (sel === "#dbGoPerfBtn") return slotButtons.dbGoPerfBtn;
      if (sel === "#dbShrinkRegularBtn") return slotButtons.dbShrinkRegularBtn;
      if (sel === "#dbShrinkFullBtn") return slotButtons.dbShrinkFullBtn;
      if (sel.startsWith("#")) return makeStaticButton(sel.slice(1));
      return null;
    },
    $$: () => [],
    esc: engine.escapeHtml,
    compact: (v, f) => String(v ?? "").trim() || (f === undefined ? "" : f),
    int: (v) => Math.round(Number(v) || 0),
    fmtInt: (v) => String(Math.round(Number(v) || 0)),
    fmtBytes: (b) => `${Math.round(Number(b) / 1048576)} MB`,
    jsonPreview: (o) => JSON.stringify(o),
    card: (t, s, b, a, ex) => `<section class="card ${ex || ""}"><h3>${t}</h3><p>${s}</p>${b}${a || ""}</section>`,
    emptyState: (t, s) => `<div>${t}:${s}</div>`,
    apiTry: async (fn, fb) => fb,
    apiGet: async (url) => {
      if (url === "/maintenance/db_health") {
        healthFetchCount += 1;
        return {
          health: {
            configured_vector_precision: "float16",
            primary: {
              total_bytes: (100 - healthFetchCount * 10) * 1048576,
              files: { db_bytes: 80 * 1048576, wal_bytes: 2 * 1048576 },
              freelist_bytes: 0,
              freelist_count: 0,
              auto_vacuum: 2,
              vector_precision: "float16",
              embeddings: { total_rows: 10, float64_rows: 0, float32_rows: 0, float16_rows: 10, json_rows: 0, archived_orphan_rows: 0, vector_bytes: 1024, estimated_transcode_savings_bytes: 0 },
              recommendations: [],
            },
            scoped: { total_bytes: 0 },
          },
        };
      }
      if (url.startsWith("/data/import/preview")) {
        return { preview: true, count: 7 };
      }
      return {};
    },
    apiPost: async (url, body) => {
      if (url === "/maintenance/db_optimize") {
        optimizePayloads.push(body);
        return {
          ok: true,
          primary: {
            before_bytes: 90 * 1048576,
            after_bytes: 60 * 1048576,
            bytes_reclaimed: 30 * 1048576,
            vacuum_mode: body.run_full_vacuum ? "full_vacuum_incremental_enabled" : "incremental_vacuum",
            transcode: { transcoded: 12, purged_orphans: 2 },
          },
        };
      }
      return { ok: true };
    },
    withBusy: async (_t, fn) => fn(),
    showInlineConfirmation: async (title, msg, confirmLabel) => {
      confirmCalls.push({ title, msg, confirmLabel });
      return true;
    },
    toast: (msg, tone) => migToasts.push({ msg, tone }),
    invalidatePool: () => {},
    prefersReducedMotion: () => false,
    requestAnimationFrame: (fn) => fn(),
    go: async (viewId, opts) => { migGoCalls.push({ viewId, opts }); },
  });

  const rootNode = { isConnected: true };
  migViews.migrate.mount(rootNode);

  // 1) Click 刷新体检 -> partial update of #dbHealthSlot only, zero go() call, form values untouched
  await slotButtons.dbHealthRefreshBtn.handlers.click();
  assert.equal(migGoCalls.length, 0, "点击刷新体检不得触发整页 go('migrate')");
  assert.equal(healthFetchCount, 1);
  assert.ok(dbHealthSlot.innerHTML.includes("90 MB"), "体检卡应原地刷新为最新体积");
  assert.equal(portablePathInput.value, "/data/my_export.jsonl");
  assert.equal(lmPathInput.value, "/data/livingmemory.db");
  assert.equal(releaseBatchInput.value, "sb_keep_me_99");

  // 2) Click 一键常规无损瘦身 (on the rebound button!) -> partial update of output & health slot, zero go()
  await slotButtons.dbShrinkRegularBtn.handlers.click();
  assert.equal(migGoCalls.length, 0, "常规瘦身不得触发整页 go('migrate')");
  assert.equal(optimizePayloads.length, 1);
  assert.equal(optimizePayloads[0].run_full_vacuum, false);
  assert.ok(dbHealthSlot.innerHTML.includes("最近一次瘦身结果"), "瘦身后体检卡应原地展示瘦身报告");
  assert.ok(migrateOutputSlot.innerHTML.includes("incremental_vacuum"), "输出区应原地更新瘦身 JSON");
  assert.equal(portablePathInput.value, "/data/my_export.jsonl");
  assert.equal(lmPathInput.value, "/data/livingmemory.db");
  assert.equal(releaseBatchInput.value, "sb_keep_me_99");

  // 3) Click 深度整理压缩 -> partial update, zero go(), form values still intact, confirmation explicitly states non-destructive
  await slotButtons.dbShrinkFullBtn.handlers.click();
  assert.equal(migGoCalls.length, 0, "深度压缩不得触发整页 go('migrate')");
  assert.equal(confirmCalls.length, 1);
  assert.ok(
    confirmCalls[0].msg.includes("仅整理向量存储、清理已归档/无主向量索引与超期内部回执，绝不删除任何记忆、聊天原文、人物关系或配置"),
    "深度压缩确认弹窗必须明确注明绝不删除任何业务数据"
  );
  assert.equal(optimizePayloads.length, 2);
  assert.equal(optimizePayloads[1].run_full_vacuum, true);
  assert.ok(migrateOutputSlot.innerHTML.includes("full_vacuum_incremental_enabled"));
  assert.equal(portablePathInput.value, "/data/my_export.jsonl");
  assert.equal(lmPathInput.value, "/data/livingmemory.db");
  assert.equal(releaseBatchInput.value, "sb_keep_me_99");

  // 4) Click 预览导入 -> output updates in place without wiping #portablePath / #lmPath / #releaseBatchId
  await staticButtons.portablePreviewBtn.handlers.click();
  assert.equal(migGoCalls.length, 0, "预览导入不得触发整页 go('migrate')");
  assert.ok(migrateOutputSlot.innerHTML.includes("&quot;count&quot;:7"));
  assert.equal(portablePathInput.value, "/data/my_export.jsonl");
  assert.equal(lmPathInput.value, "/data/livingmemory.db");
  assert.equal(releaseBatchInput.value, "sb_keep_me_99");
});
