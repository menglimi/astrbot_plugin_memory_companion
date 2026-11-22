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
      "\nthis.__exports = { MODULE_LABELS, moduleLabel, moduleSubtitle, CONFIG_COMMON_KEYS, CONFIG_OPTION_LABELS, CONFIG_CHOICE_CARDS, orderedCommonKeys, renderChoiceCards, buildConfigSearchCatalog, runConfigSearchQuery, applyPendingConfigFocus, configSearchState, activateConfigSearchHit };",
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

test("module config: all 29 schema modules have pure-Chinese labels and fallback helper works", () => {
  const rt = loadAppConfigRuntime();
  const { MODULE_LABELS, moduleLabel, moduleSubtitle, CONFIG_COMMON_KEYS } = rt.exports;
  const moduleIds = Object.keys(realSchema);

  assert.equal(moduleIds.length, 29);
  for (const modId of moduleIds) {
    const label = moduleLabel(modId, realSchema[modId]);
    assert.ok(MODULE_LABELS[modId], `MODULE_LABELS 缺少模块: ${modId}`);
    assert.ok(/[\u4e00-\u9fff]/.test(label), `模块 ${modId} 标题应包含中文: ${label}`);
    assert.ok(!/[A-Za-z_]/.test(label), `模块 ${modId} 侧栏中文名不应夹带英文或下划线: ${label}`);
  }

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

test("legacy.html loads search-engine.js?v=2.6.8 before app.js?v=2.6.8", () => {
  const html = fs.readFileSync(LEGACY_HTML_PATH, "utf8");
  const seIdx = html.indexOf('./search-engine.js?v=2.6.8');
  const appIdx = html.indexOf('./app.js?v=2.6.8');
  assert.ok(seIdx > 0, "legacy.html 必须引入 ./search-engine.js?v=2.6.8");
  assert.ok(appIdx > seIdx, "search-engine.js 必须在 app.js 之前加载");
});
