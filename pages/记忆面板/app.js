const API = "/astrbot_plugin_memory_companion/page";
const PAGE_ENDPOINT_PREFIX = "page";

const VIEWS = {
  objects: { title: "知识图谱", hint: "查看关系边、跨窗口线程、时间线和记忆节点概览。" },
  film: { title: "群聊记忆", hint: "查看群聊范围内可召回、可管理的结构化记忆。" },
  microscope: { title: "记忆显微镜", hint: "输入一句话，模拟当前对象下的召回和过滤。" },
  relations: { title: "用户记忆", hint: "聚焦用户画像、偏好、称呼和关系声明。" },
  review: { title: "个人记忆", hint: "查看 Bot 自身的每日生活日程、当前状态和细化片段。" },
  archive: { title: "维护 / 迁移 / 配置", hint: "执行维护、迁移、清理和导入修复。" },
  maintain: { title: "私聊记忆", hint: "查看私聊范围内的对话、偏好、事实和稳定记忆。" },
};

const PERSONAL_MEMORY_VIEW = {
  available: {
    title: "个人记忆",
    hint: "查看 Bot 自身的每日生活日程、当前状态和细化片段。",
    small: "日程 · 细化",
  },
  unavailable: {
    title: "个人记忆不可用",
    hint: "需要安装并启用主动陪伴插件后，才能查看 Bot 自身的日程与细化。",
    small: "需要陪伴插件",
  },
};

const SECONDARY_NAV = {
  objects: [
    { id: "overview", label: "图谱总览", sublabel: "关系、线程与时间线", badge: "总览" },
    { id: "relations", label: "图谱边", sublabel: "人物、话题、事实与记忆关联", badge: "图谱" },
    { id: "threads", label: "跨窗口线程", sublabel: "不同私聊/群聊之间的待办线索", badge: "线程" },
    { id: "timeline", label: "时间线", sublabel: "最近记录的事件节点", badge: "时间" },
  ],
  microscope: [
    { id: "query", label: "召回测试", sublabel: "输入一句话模拟检索", badge: "测试" },
    { id: "hits", label: "命中记忆", sublabel: "查看检索结果", badge: "命中" },
    { id: "blocked", label: "过滤原因", sublabel: "查看被挡下的记忆", badge: "过滤" },
  ],
  relations: [
    { id: "all", label: "全部用户记忆", sublabel: "画像、偏好与关系", badge: "全部" },
    { id: "profile", label: "用户画像", sublabel: "稳定画像片段", badge: "画像" },
    { id: "preference", label: "偏好", sublabel: "喜好、习惯、倾向", badge: "偏好" },
    { id: "relationship", label: "关系声明", sublabel: "身份和关系线索", badge: "关系" },
    { id: "explicit", label: "明确记住", sublabel: "用户主动要求记住", badge: "记住" },
  ],
  archive: [
    { id: "retrieval", label: "检索配置", sublabel: "本地检索 / 重排路径", badge: "配置" },
    { id: "maintenance", label: "维护索引", sublabel: "修复索引和数据状态", badge: "维护" },
    { id: "repair", label: "内容修复", sublabel: "修复 LivingMemory 导入内容", badge: "修复" },
    { id: "migration", label: "迁移导入", sublabel: "LivingMemory 预览与导入", badge: "迁移" },
    { id: "clear", label: "危险清理", sublabel: "清空全部记忆数据", badge: "清理" },
  ],
};

const state = {
  stats: {},
  buckets: [],
  activeView: "objects",
  activeBucketId: "all",
  activeMemoryId: "",
  secondaryNav: {},
  companionPersonalAvailable: null,
  personalDates: [],
  selectedPersonalDate: "",
  selectedScheduleIndex: "",
  animatePersonalDateRail: false,
  pendingPersonalFilmReveal: false,
  personalEntranceRevealRequested: false,
  personalAlignTimer: 0,
  scopedModes: {
    film: "memory",
    maintain: "memory",
  },
};

const DEFAULT_THEME = "yuebai";
const THEME_OPTIONS = [
  "huangbaiyou", "tianpiao", "haitianxia", "yingying", "oubi", "qingming", "zipu",
  "shanlan", "qielan", "tuihong", "congqing", "yuebai", "mocan", "gupiao",
];
const THEME_ALIASES = {
  黄白游: "huangbaiyou",
  天缥: "tianpiao",
  海天霞: "haitianxia",
  盈盈: "yingying",
  欧碧: "oubi",
  青冥: "qingming",
  紫蒲: "zipu",
  山岚: "shanlan",
  窃蓝: "qielan",
  退红: "tuihong",
  葱倩: "congqing",
  月白: "yuebai",
  墨黪: "mocan",
  骨缥: "gupiao",
};
const TRANSITION_FACES = [
  "(๑•̀ㅂ•́)و✧",
  "(。・ω・。)",
  "(*´▽`*)",
  "( •̀ ω •́ )✧",
  "(｡･∀･)ﾉﾞ",
  "(｀・ω・´)",
  "(つ≧▽≦)つ",
  "(＾▽＾)",
  "(´｡• ᵕ •｡`)",
  "(๑˃̵ᴗ˂̵)و",
  "(￣▽￣)ノ",
  "(ง •_•)ง",
  "喵~",
  "你瞅啥",
  "这是一个彩蛋",
];

const SCREEN_FILM_EXTRA_HOLD_MS = 300;
const OVERVIEW_TO_WORKSPACE_WIPE_WAIT_MS = 520 + SCREEN_FILM_EXTRA_HOLD_MS;
const WORKSPACE_WIPE_CLEANUP_MS = 620 + SCREEN_FILM_EXTRA_HOLD_MS;
const HOME_WIPE_SWAP_WAIT_MS = 320 + SCREEN_FILM_EXTRA_HOLD_MS;
const HOME_WIPE_TOTAL_WAIT_MS = 980 + SCREEN_FILM_EXTRA_HOLD_MS;
const SECONDARY_NAV_LOOP_RADIUS = 5;

let railCoverflowFrame = 0;
let workspaceTransitionToken = 0;
let homeReturnRunning = false;

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
}

function waitForMotion(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, prefersReducedMotion() ? 0 : ms));
}

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function refreshTransitionFace() {
  const face = $("#transitionFace");
  if (!face) return;
  face.textContent = TRANSITION_FACES[Math.floor(Math.random() * TRANSITION_FACES.length)];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function compact(value, fallback = "-") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortId(value) {
  const text = compact(value, "");
  if (!text) return "-";
  if (text.length <= 14) return text;
  return `${text.slice(0, 8)}...${text.slice(-4)}`;
}

function isNumericOnlyContent(value) {
  return /^[0-9]+$/.test(String(value ?? "").trim());
}

async function apiGet(path) {
  return apiRequest(path, { method: "GET" });
}

async function apiPost(path, payload = {}) {
  return apiRequest(path, { method: "POST", body: payload });
}

async function apiRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const bridge = await waitForBridge();
  let data;
  if (bridge && typeof bridge.apiGet === "function" && typeof bridge.apiPost === "function") {
    data = await bridgeRequest(bridge, path, method, options.body);
  } else if (new URLSearchParams(window.location.search).get("debug_http") === "1") {
    data = await httpRequest(path, method, options.body);
  } else {
    throw new Error("未检测到 AstrBot 官方插件 Page 桥接，请从 AstrBot 后台的插件拓展页打开");
  }
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch (error) {
      throw new Error(data);
    }
  }
  if (!data || data.success === false) throw new Error(data?.error || "请求失败");
  return data.data ?? data;
}

async function waitForBridge() {
  for (let i = 0; i < 24; i += 1) {
    const bridge = getBridge();
    if (bridge && typeof bridge.apiGet === "function" && typeof bridge.apiPost === "function") {
      return bridge;
    }
    await sleep(80);
  }
  return null;
}

function getBridge() {
  if (window.AstrBotPluginPage) return window.AstrBotPluginPage;
  try {
    if (window.parent && window.parent !== window && window.parent.AstrBotPluginPage) {
      return window.parent.AstrBotPluginPage;
    }
  } catch (error) {
    return null;
  }
  return null;
}

async function bridgeRequest(bridge, path, method, body) {
  const url = new URL(path, "https://astrbot-plugin-page.local/");
  const endpoint = `${PAGE_ENDPOINT_PREFIX}/${url.pathname.replace(/^\/+/, "")}`.replace(/\/+/g, "/");
  if (method === "GET") {
    const params = Object.fromEntries(url.searchParams.entries());
    return bridge.apiGet(endpoint, Object.keys(params).length ? params : undefined);
  }
  return bridge.apiPost(endpoint, body || {});
}

async function httpRequest(path, method, body) {
  const response = await fetch(`${API}${path}`, {
    method,
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return response.json();
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function setMessage(text) {
  $("#subtitle").textContent = text;
}

function setBusy(active, text = "正在处理...") {
  const app = $("#app");
  const layer = $("#busyLayer");
  if (!app || !layer) return;
  app.classList.toggle("is-busy", active);
  layer.setAttribute("aria-hidden", active ? "false" : "true");
  $("#busyText").textContent = text;
}

function normalizeTheme(theme) {
  const value = String(theme || "").trim();
  return THEME_OPTIONS.includes(value) ? value : (THEME_ALIASES[value] || DEFAULT_THEME);
}

function applyTheme(theme) {
  const next = normalizeTheme(theme);
  document.documentElement.dataset.theme = next;
  $("#app")?.setAttribute("data-theme", next);
}

async function loadConfiguredTheme() {
  applyTheme(DEFAULT_THEME);
  try {
    const data = await apiGet("/context/config");
    applyTheme(data.appearance?.theme_key || data.appearance?.theme);
  } catch (error) {
    applyTheme(DEFAULT_THEME);
  }
}

function showToast(text, tone = "info") {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = text;
  toast.dataset.tone = tone;
  toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.classList.remove("is-visible");
  }, tone === "error" ? 4200 : 2400);
}

function loadingState(text = "正在读取胶片...") {
  return `<div class="loading-state"><span></span><b>${escapeHtml(text)}</b></div>`;
}

function panelError(error, retryLabel = "重试") {
  return `
    <div class="empty-state error-state">
      <b>读取失败</b>
      <span>${escapeHtml(error?.message || error || "未知错误")}</span>
      <button data-retry-active type="button">${escapeHtml(retryLabel)}</button>
    </div>
  `;
}

async function withBusy(text, task) {
  try {
    setBusy(true, text);
    return await task();
  } catch (error) {
    showToast(error.message || "操作失败", "error");
    return undefined;
  } finally {
    setBusy(false);
  }
}

async function withButton(button, text, task) {
  const original = button.textContent;
  button.disabled = true;
  button.classList.add("is-loading");
  button.textContent = text;
  try {
    return await task();
  } catch (error) {
    showToast(error.message || "操作失败", "error");
    return undefined;
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.textContent = original;
  }
}

function activeBucket() {
  return state.buckets.find((bucket) => bucket.id === state.activeBucketId) || state.buckets[0];
}

function bucketLabel(bucket = activeBucket()) {
  return bucket?.label || "全部记忆";
}

function isWindowBucket(bucket) {
  return Boolean(bucket && ["group", "private"].includes(bucket.scope) && bucket.target_id);
}

function windowKindLabel(scope) {
  return scope === "group" ? "群聊" : "私聊";
}

function windowOptionValue(scope, id) {
  return `${scope}:${id}`;
}

function parseWindowOption(value) {
  const parts = String(value || "").split(":");
  const scope = parts.shift() || "";
  return { scope, id: parts.join(":") };
}

function bucketByWindow(scope, id) {
  return state.buckets.find((bucket) => bucket.scope === scope && bucket.target_id === id);
}

function windowLabel(scope, id) {
  const bucket = bucketByWindow(scope, id);
  return bucket?.label || `${windowKindLabel(scope)} ${id || "未知窗口"}`;
}

function windowIdentifierLabel(scope, id) {
  if (!id) return scope === "group" ? "群号未知" : "QQ 未知";
  return scope === "group" ? `群号 ${id}` : `QQ ${id}`;
}

function windowDisplayLabel(scope, id, name = "") {
  const displayName = compact(name, "");
  if (displayName && displayName !== id) return displayName;
  return scope === "group" ? `群聊 ${id || "未知群聊"}` : `私聊 ${id || "未知用户"}`;
}

function permissionTargets(bucket) {
  return state.buckets
    .filter((item) => isWindowBucket(item) && !(item.scope === bucket.scope && item.target_id === bucket.target_id))
    .sort((a, b) => {
      if (a.scope !== b.scope) return a.scope === "group" ? -1 : 1;
      return a.label.localeCompare(b.label, "zh-CN");
    });
}

function secondaryNavItems(view = state.activeView) {
  return SECONDARY_NAV[view] || [];
}

function defaultSecondaryNav(view = state.activeView) {
  return secondaryNavItems(view)[0]?.id || "";
}

function activeSecondaryNav(view = state.activeView) {
  const items = secondaryNavItems(view);
  if (!items.length) return "";
  const active = state.secondaryNav[view];
  if (items.some((item) => item.id === active)) return active;
  state.secondaryNav[view] = items[0].id;
  return items[0].id;
}

function activeSecondaryItem(view = state.activeView) {
  const active = activeSecondaryNav(view);
  return secondaryNavItems(view).find((item) => item.id === active) || null;
}

function loopedSecondaryNavItems(view = state.activeView) {
  const items = secondaryNavItems(view);
  if (items.length <= 1) {
    return items.map((item, index) => ({ ...item, renderKey: `${item.id}-${index}`, isActiveLoopItem: true }));
  }
  const active = activeSecondaryNav(view);
  const activeIndex = Math.max(0, items.findIndex((item) => item.id === active));
  const looped = [];
  for (let offset = -SECONDARY_NAV_LOOP_RADIUS; offset <= SECONDARY_NAV_LOOP_RADIUS; offset += 1) {
    const sourceIndex = (activeIndex + offset + items.length * 16) % items.length;
    const item = items[sourceIndex];
    looped.push({
      ...item,
      renderKey: `${item.id}-${offset + SECONDARY_NAV_LOOP_RADIUS}`,
      isActiveLoopItem: offset === 0,
    });
  }
  return looped;
}

function renderSecondaryNav(view = state.activeView, immediate = false) {
  if (view === "review") return;
  const items = secondaryNavItems(view);
  if (!items.length) {
    renderBuckets();
    return;
  }
  const rail = document.querySelector(".object-rail");
  const railTitle = document.querySelector(".rail-head b");
  const clearButton = $("#clearTargetBtn");
  rail?.classList.remove("is-scoped-rail");
  rail?.classList.add("is-secondary-nav", "is-looped-secondary-nav");
  if (railTitle) railTitle.textContent = "二级导航";
  if (clearButton) clearButton.textContent = "默认";
  const renderItems = loopedSecondaryNavItems(view);
  $("#bucketList").innerHTML = renderItems.map((item) => `
    <button class="bucket secondary-nav-item${item.isActiveLoopItem ? " is-active" : ""}" data-secondary-nav="${escapeHtml(item.id)}" data-loop-key="${escapeHtml(item.renderKey)}" type="button" aria-current="${item.isActiveLoopItem ? "true" : "false"}">
      <b>${escapeHtml(item.label)}</b>
      <small>${escapeHtml(item.sublabel)}</small>
      <div class="badges"><span class="badge blue">${escapeHtml(item.badge)}</span></div>
    </button>
  `).join("");
  $$("#bucketList [data-secondary-nav]").forEach((item) => {
    item.addEventListener("click", () => selectSecondaryNav(item.dataset.secondaryNav));
  });
  const activeItem = activeSecondaryItem(view);
  $("#activeTarget").textContent = activeItem ? `${VIEWS[view]?.title || "二级页"} · ${activeItem.label}` : (VIEWS[view]?.title || "二级页");
  resetRailCoverflow();
  requestAnimationFrame(() => moveSecondaryNavToStandard(immediate));
}

async function selectSecondaryNav(id) {
  const view = state.activeView;
  if (!secondaryNavItems(view).some((item) => item.id === id)) return;
  state.secondaryNav[view] = id;
  renderSecondaryNav(view);
  clearDetail();
  await loadActiveView();
}

function moveSecondaryNavToStandard(immediate = false) {
  if (state.activeView === "review") return;
  const app = $("#app");
  const list = $("#bucketList");
  const rail = document.querySelector(".object-rail.is-secondary-nav");
  if (!app || !list || !rail) return;
  const items = Array.from(list.querySelectorAll(".secondary-nav-item"));
  const active = list.querySelector(".secondary-nav-item.is-active");
  if (!active || !items.length) return;
  const currentShift = parseFloat(getComputedStyle(app).getPropertyValue("--secondary-nav-shift")) || 0;
  const standard = items[Math.min(1, items.length - 1)];
  const activeTop = active.getBoundingClientRect().top - currentShift;
  const standardTop = standard.getBoundingClientRect().top - currentShift;
  list.style.transition = immediate ? "none" : "";
  app.style.setProperty("--secondary-nav-shift", `${Math.round(standardTop - activeTop)}px`);
  if (immediate) {
    list.offsetHeight;
    list.style.transition = "";
  }
}

function contextParams(extra = {}) {
  const bucket = activeBucket();
  const params = new URLSearchParams();
  Object.entries(extra).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim()) {
      params.set(key, String(value).trim());
    }
  });
  if (!bucket || bucket.id === "all") return params;
  if (bucket.id === "self") {
    params.set("visibility", "bot_self");
    return params;
  }
  if (bucket.scope) params.set("scope", bucket.scope);
  if (bucket.scope === "private") {
    if (bucket.target_id) params.set("entity_id", bucket.target_id);
    if (bucket.session_id) params.set("session_id", bucket.session_id);
  } else if (bucket.scope === "group") {
    if (bucket.group_id) {
      params.set("group_id", bucket.group_id);
    } else if (bucket.target_id) {
      params.set("entity_id", bucket.target_id);
    }
    if (bucket.session_id) params.set("session_id", bucket.session_id);
  }
  return params;
}

function contextPayload(query) {
  const bucket = activeBucket();
  const payload = { query, top_k: 8, scope: "unknown" };
  if (!bucket || bucket.id === "all") return payload;
  if (bucket.id === "self") {
    payload.session_id = "bot_self";
    payload.scope = "unknown";
    return payload;
  }
  payload.scope = bucket.scope || "unknown";
  payload.session_id = bucket.session_id || "";
  if (bucket.scope === "private") {
    payload.user_id = bucket.target_id || "";
  }
  if (bucket.scope === "group") {
    payload.group_id = bucket.group_id || bucket.target_id || "";
  }
  return payload;
}

function renderStats(stats) {
  const items = [
    ["记忆", stats.total_memories],
    ["群聊记忆", stats.by_scope?.group ?? 0],
    ["私聊记忆", stats.by_scope?.private ?? 0],
    ["稳定记忆", stats.stable_memories ?? 0],
  ];
  $("#stats").innerHTML = items.map(([label, value]) => `
    <article class="stat"><b>${escapeHtml(value ?? 0)}</b><span>${escapeHtml(label)}</span></article>
  `).join("");
}

function normalizeBuckets(rawBuckets) {
  const normalized = [
    {
      id: "all",
      label: "全部记忆",
      sublabel: "不限定对象",
      memory_count: state.stats.total_memories || 0,
      latest_at: "",
    },
    {
      id: "self",
      label: "Bot 自己",
      sublabel: "行动、创作、搜索、阅读",
      memory_count: 0,
      latest_at: "",
    },
  ];
  for (const item of rawBuckets || []) {
    const scope = compact(item.scope, "unknown");
    const targetId = compact(item.target_id, "");
    if (!targetId) continue;
    const name = compact(item.target_name, "");
    const label = windowDisplayLabel(scope, targetId, name);
    const identifierLabel = windowIdentifierLabel(scope, targetId);
    normalized.push({
      id: `${scope}:${targetId}`,
      scope,
      target_id: targetId,
      display_name: name,
      identifier_label: identifierLabel,
      group_id: item.sample_group_id || (scope === "group" ? targetId : ""),
      session_id: item.sample_session_id || "",
      label,
      sublabel: identifierLabel,
      memory_count: item.memory_count || 0,
      archived_count: item.archived_count || 0,
      latest_at: item.latest_at || "",
    });
  }
  return normalized;
}

function bucketCard(bucket) {
  const active = bucket.id === state.activeBucketId ? " is-active" : "";
  const settingsTarget = isScopedSettingsMode() && isWindowBucket(bucket);
  return `
    <article class="bucket${active}${settingsTarget ? " is-settings-target" : ""}" data-bucket-id="${escapeHtml(bucket.id)}" role="button" tabindex="0" aria-current="${bucket.id === state.activeBucketId ? "true" : "false"}">
      <b>${escapeHtml(bucket.label)}</b>
      <small>${escapeHtml(bucket.sublabel || "")}</small>
      <div class="badges">
        <span class="badge blue">${escapeHtml(bucket.memory_count || 0)} 条</span>
        ${settingsTarget ? `<span class="badge gold">权限</span>` : ""}
      </div>
    </article>
  `;
}

function scopedRailConfig(scope, settingsMode = false) {
  if (scope === "group") {
    return settingsMode
      ? { title: "群聊设置", clear: "说明", label: "设置说明", sublabel: "选择具体群聊配置权限", badge: "群聊" }
      : { title: "群聊列表", clear: "全部群聊", label: "全部群聊", sublabel: "不限定群聊", badge: "群聊" };
  }
  return settingsMode
    ? { title: "私聊设置", clear: "说明", label: "设置说明", sublabel: "选择具体用户配置权限", badge: "私聊" }
    : { title: "私聊用户", clear: "全部私聊", label: "全部私聊", sublabel: "不限定用户", badge: "私聊" };
}

function bindBucketListInteractions() {
  $$("#bucketList [data-bucket-id]").forEach((item) => {
    item.addEventListener("click", (event) => {
      if (event.target.closest("[data-acl-bucket]")) return;
      selectBucket(item.dataset.bucketId);
    });
    item.addEventListener("keydown", (event) => {
      if (event.target.closest("[data-acl-bucket]")) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectBucket(item.dataset.bucketId);
      }
    });
  });
  $$("#bucketList [data-acl-bucket]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openBucketPermissions(button.dataset.aclBucket);
    });
  });
}

function currentRailScope() {
  if (state.activeView === "film") return "group";
  if (state.activeView === "maintain") return "private";
  return "";
}

function scopedViewScope(view = state.activeView) {
  if (view === "film") return "group";
  if (view === "maintain") return "private";
  return "";
}

function scopedViewTarget(view = state.activeView) {
  if (view === "film") return "#groupMemoryList";
  if (view === "maintain") return "#privateMemoryList";
  return "";
}

function scopedMode(view = state.activeView) {
  return state.scopedModes[view] === "settings" ? "settings" : "memory";
}

function isScopedSettingsMode(view = state.activeView) {
  return scopedMode(view) === "settings";
}

function scopedDefaultModeLabel(scope) {
  return scope === "group" ? "默认黑名单" : "默认白名单";
}

function scopedSettingsHint(scope) {
  return scope === "group"
    ? "群聊窗口默认黑名单模式：默认可跨群聊读取，加入名单后禁止读取；私聊流向群聊仍需要显式白名单。"
    : "私聊窗口默认白名单模式：默认不开放给其它窗口，只有加入白名单后才能读取。";
}

function renderScopedModeControls(view = state.activeView) {
  const scope = scopedViewScope(view);
  if (!scope) return;
  const isSettings = isScopedSettingsMode(view);
  $("#app")?.classList.toggle("is-scoped-settings-mode", isSettings);
  const button = view === "film" ? $("#groupMemoryModeBtn") : $("#privateMemoryModeBtn");
  const title = view === "film" ? $("#groupMemoryTitle") : $("#privateMemoryTitle");
  const hint = view === "film" ? $("#groupMemoryHint") : $("#privateMemoryHint");
  if (title) title.textContent = isSettings ? `${windowKindLabel(scope)}设置` : `${windowKindLabel(scope)}记忆`;
  if (button) {
    button.textContent = isSettings ? `${windowKindLabel(scope)}记忆` : `${windowKindLabel(scope)}设置`;
    button.classList.toggle("is-active", isSettings);
    button.setAttribute("aria-pressed", isSettings ? "true" : "false");
  }
  if (hint) {
    hint.textContent = isSettings
      ? `点击左侧${scope === "group" ? "群聊" : "私聊用户"}，配置记忆读取黑名单/白名单。${scopedDefaultModeLabel(scope)}。`
      : VIEWS[view]?.hint || "";
  }
}

async function toggleScopedMode(view) {
  if (!scopedViewScope(view)) return;
  state.scopedModes[view] = isScopedSettingsMode(view) ? "memory" : "settings";
  renderScopedModeControls(view);
  renderScopedBucketRail(scopedViewScope(view));
  clearDetail();
  await loadActiveView();
}

function renderScopedBucketRail(scope) {
  const rail = document.querySelector(".object-rail");
  rail?.classList.remove("is-secondary-nav", "is-looped-secondary-nav");
  rail?.classList.add("is-scoped-rail");
  $("#app")?.style.removeProperty("--secondary-nav-shift");
  renderScopedModeControls();
  const settingsMode = isScopedSettingsMode();
  const config = scopedRailConfig(scope, settingsMode);
  const railTitle = document.querySelector(".rail-head b");
  const clearButton = $("#clearTargetBtn");
  if (railTitle) railTitle.textContent = config.title;
  if (clearButton) clearButton.textContent = config.clear;

  const scopedBuckets = state.buckets.filter((bucket) => bucket.scope === scope);
  if (state.activeBucketId !== "all" && !scopedBuckets.some((bucket) => bucket.id === state.activeBucketId)) {
    state.activeBucketId = "all";
  }
  const totalCount = scopedBuckets.reduce((sum, bucket) => sum + Number(bucket.memory_count || 0), 0);
  const allBucket = {
    id: "all",
    label: config.label,
    sublabel: config.sublabel,
    memory_count: totalCount,
  };
  $("#bucketList").innerHTML = [allBucket, ...scopedBuckets].map((bucket) => bucketCard(bucket)).join("");
  bindBucketListInteractions();
  $("#activeTarget").textContent = state.activeBucketId === "all" ? config.label : bucketLabel();
  requestRailCoverflow();
  centerActiveBucket();
}

function renderBuckets() {
  const rail = document.querySelector(".object-rail");
  rail?.classList.remove("is-secondary-nav", "is-looped-secondary-nav");
  rail?.classList.remove("is-scoped-rail");
  $("#app")?.style.removeProperty("--secondary-nav-shift");
  const railTitle = document.querySelector(".rail-head b");
  const clearButton = $("#clearTargetBtn");
  if (railTitle) railTitle.textContent = "观察对象";
  if (clearButton) clearButton.textContent = "全部";
  $("#bucketList").innerHTML = state.buckets.map(bucketCard).join("");
  const objectCards = $("#objectCards");
  if (objectCards) {
    objectCards.innerHTML = state.buckets.map((bucket) => `
      <article class="object-card${bucket.id === state.activeBucketId ? " is-active" : ""}" data-bucket-id="${escapeHtml(bucket.id)}" role="button" tabindex="0" aria-current="${bucket.id === state.activeBucketId ? "true" : "false"}">
        <span class="item-title">${escapeHtml(bucket.label)}</span>
        <div class="item-meta">${escapeHtml(bucket.sublabel || "全局范围")} · 最近 ${escapeHtml(formatTime(bucket.latest_at))}</div>
        <div class="badges">
          <span class="badge blue">${escapeHtml(bucket.memory_count || 0)} 条记忆</span>
        </div>
      </article>
    `).join("");
  }
  bindBucketListInteractions();
  $$("#objectCards [data-bucket-id]").forEach((item) => {
    item.addEventListener("click", () => selectBucket(item.dataset.bucketId));
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectBucket(item.dataset.bucketId);
      }
    });
  });
  $("#activeTarget").textContent = bucketLabel();
  requestRailCoverflow();
  centerActiveBucket();
}

function renderPersonalDateRail(dates, selectedDate) {
  const app = $("#app");
  const list = $("#bucketList");
  const rail = document.querySelector(".object-rail");
  rail?.classList.remove("is-secondary-nav", "is-looped-secondary-nav");
  rail?.classList.remove("is-scoped-rail");
  app?.style.removeProperty("--secondary-nav-shift");
  const animate = state.animatePersonalDateRail && !prefersReducedMotion();
  if (app && list && !animate) {
    list.style.transition = "none";
    app.style.removeProperty("--personal-reel-shift");
    list.offsetHeight;
    list.style.transition = "";
  }
  state.personalDates = Array.isArray(dates) ? dates : [];
  state.selectedPersonalDate = selectedDate || state.personalDates[0] || "";
  const railTitle = document.querySelector(".rail-head b");
  const clearButton = $("#clearTargetBtn");
  if (railTitle) railTitle.textContent = "日期胶卷";
  if (clearButton) clearButton.textContent = "今天";
  $("#bucketList").innerHTML = state.personalDates.length ? state.personalDates.map((date) => {
    const active = date === state.selectedPersonalDate ? " is-active" : "";
    const label = date === todayKey() ? "今天" : formatDateLabel(date);
    return `
      <button class="bucket date-reel${active}" data-personal-date="${escapeHtml(date)}" type="button" aria-current="${date === state.selectedPersonalDate ? "true" : "false"}">
        <b>${escapeHtml(label)}</b>
        <small>${escapeHtml(date)}</small>
      </button>
    `;
  }).join("") : `<div class="empty-state">还没有可选择的日期。</div>`;
  $$("#bucketList [data-personal-date]").forEach((item) => {
    item.addEventListener("click", () => selectPersonalDate(item.dataset.personalDate));
  });
  $("#activeTarget").textContent = state.selectedPersonalDate ? `个人记忆 · ${state.selectedPersonalDate}` : "个人记忆";
  resetRailCoverflow();
  state.pendingPersonalFilmReveal = animate;
  state.animatePersonalDateRail = false;
  requestAnimationFrame(() => movePersonalDateToStandard(!animate));
}

async function selectPersonalDate(date) {
  const nextDate = date || "";
  if (nextDate && nextDate !== state.selectedPersonalDate) {
    await retractScheduleFilmBeforeDateMove();
  }
  state.selectedPersonalDate = nextDate;
  state.selectedScheduleIndex = "";
  state.animatePersonalDateRail = true;
  clearDetail();
  await loadPersonalMemory();
  resetRailCoverflow();
}

function movePersonalDateToStandard(immediate = false) {
  if (state.activeView !== "review") return;
  const app = $("#app");
  const list = $("#bucketList");
  if (!app || !list) return;
  const reels = Array.from(list.querySelectorAll(".bucket.date-reel"));
  const active = list.querySelector(".bucket.date-reel.is-active");
  if (!active || !reels.length) return;
  const currentShift = parseFloat(getComputedStyle(app).getPropertyValue("--personal-reel-shift")) || 0;
  const standard = reels[Math.min(1, reels.length - 1)];
  const activeTop = active.getBoundingClientRect().top - currentShift;
  const standardTop = standard.getBoundingClientRect().top - currentShift;
  list.style.transition = immediate ? "none" : "";
  app.style.setProperty("--personal-reel-shift", `${Math.round(standardTop - activeTop)}px`);
  if (immediate) {
    list.offsetHeight;
    list.style.transition = "";
  }
  schedulePersonalScheduleAlign(immediate);
}

function schedulePersonalScheduleAlign(immediate = false) {
  const list = $("#bucketList");
  window.clearTimeout(state.personalAlignTimer);
  if (immediate || !list) {
    requestAnimationFrame(alignPersonalScheduleToReel);
    return;
  }
  const finish = (event) => {
    if (event.target !== list || event.propertyName !== "transform") return;
    window.clearTimeout(state.personalAlignTimer);
    alignPersonalScheduleToReel();
  };
  list.addEventListener("transitionend", finish, { once: true });
  state.personalAlignTimer = window.setTimeout(alignPersonalScheduleToReel, 780);
}

function todayKey() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDateLabel(date) {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date || "-";
  return parsed.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function centerActiveBucket() {
  const active = $("#bucketList .bucket.is-active");
  if (!active || !$("#app").classList.contains("is-workspace") || state.activeView === "review" || document.querySelector(".object-rail")?.classList.contains("is-secondary-nav")) return;
  window.setTimeout(() => {
    if (state.activeView === "review" || document.querySelector(".object-rail")?.classList.contains("is-secondary-nav")) return;
    active.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
    requestRailCoverflow();
  }, 40);
}

function requestRailCoverflow() {
  const rail = document.querySelector(".object-rail");
  if (
    state.activeView === "review"
    || rail?.classList.contains("is-secondary-nav")
    || rail?.classList.contains("is-scoped-rail")
  ) {
    resetRailCoverflow();
    return;
  }
  if (railCoverflowFrame) return;
  railCoverflowFrame = window.requestAnimationFrame(() => {
    railCoverflowFrame = 0;
    updateRailCoverflow();
  });
}

function resetRailCoverflow() {
  $("#bucketList")?.querySelectorAll(".bucket").forEach((bucket) => {
    ["--cf-rot", "--cf-scale", "--cf-z", "--cf-x", "--cf-opacity"].forEach((name) => {
      bucket.style.removeProperty(name);
    });
    bucket.style.removeProperty("z-index");
    bucket.classList.remove("is-cover-center");
  });
}

function updateRailCoverflow() {
  const list = $("#bucketList");
  if (!list || !$("#app").classList.contains("is-workspace") || state.activeView === "review") return;
  const listRect = list.getBoundingClientRect();
  const centerY = listRect.top + listRect.height / 2;
  const half = listRect.height / 2 || 1;
  list.querySelectorAll(".bucket").forEach((bucket) => {
    const rect = bucket.getBoundingClientRect();
    const bucketY = rect.top + rect.height / 2;
    const distance = Math.max(-1, Math.min(1, (bucketY - centerY) / half));
    const amount = Math.abs(distance);
    const rotate = Math.max(-58, Math.min(58, distance * 62));
    const scale = 1.08 - amount * 0.22;
    const depth = -amount * 110;
    const shift = -amount * 12;
    bucket.style.setProperty("--cf-rot", `${rotate.toFixed(2)}deg`);
    bucket.style.setProperty("--cf-scale", scale.toFixed(3));
    bucket.style.setProperty("--cf-z", `${depth.toFixed(1)}px`);
    bucket.style.setProperty("--cf-x", `${shift.toFixed(1)}px`);
    bucket.style.setProperty("--cf-opacity", String((1 - amount * 0.42).toFixed(3)));
    bucket.style.zIndex = String(1000 - Math.round(amount * 900));
    bucket.classList.toggle("is-cover-center", amount < 0.23);
  });
}

async function loadStats() {
  const data = await apiGet("/stats");
  state.stats = data.stats || {};
  renderStats(state.stats);
  setMessage("");
}

async function loadBuckets() {
  const data = await apiGet("/buckets?limit=180");
  state.buckets = normalizeBuckets(data.buckets || []);
  if (!state.buckets.some((bucket) => bucket.id === state.activeBucketId)) {
    state.activeBucketId = "all";
  }
  const scope = currentRailScope();
  if ($("#app")?.classList.contains("is-workspace") && scope) {
    renderScopedBucketRail(scope);
  } else if ($("#app")?.classList.contains("is-workspace") && state.activeView !== "review") {
    renderSecondaryNav(state.activeView, true);
  } else if (state.activeView !== "review") {
    renderBuckets();
  }
}

async function selectBucket(id) {
  state.activeBucketId = id || "all";
  const scope = currentRailScope();
  if (scope) {
    renderScopedBucketRail(scope);
  } else {
    renderBuckets();
  }
  clearDetail();
  await loadActiveView();
  requestRailCoverflow();
}

function prepareOverviewStripReturn() {
  $$(".filmstrip").forEach((strip, index) => {
    const style = strip.getAttribute("style") || "";
    const off = parseFloat((style.match(/--off:\s*(-?[\d.]+)px/) || [0, 0])[1]);
    const direction = off < 0 ? -1 : 1;
    strip.style.removeProperty("transition");
    strip.style.removeProperty("transform");
    strip.style.removeProperty("--exit-axis");
    strip.style.removeProperty("--exit-y");
    strip.style.removeProperty("--exit-delay");
    strip.style.setProperty("--return-from-off", `${off + direction * 720}px`);
    strip.style.setProperty("--return-delay", `${Math.min(index * 42, 260)}ms`);
  });
}

function prepareOverviewStripExit(view) {
  const distance = Math.max(window.innerWidth || 0, window.innerHeight || 0, 960) + 5200;
  $$(".filmstrip").forEach((strip) => {
    const style = strip.getAttribute("style") || "";
    const axis = parseFloat((style.match(/--tx:\s*(-?[\d.]+)px/) || [0, 0])[1]);
    strip.style.removeProperty("transition");
    strip.style.removeProperty("transform");
    strip.style.setProperty("--exit-axis", `${axis + distance}px`);
    strip.style.removeProperty("--exit-y");
    strip.style.setProperty("--exit-delay", "0ms");
  });
}

function playInitialOverviewEntrance() {
  const app = $("#app");
  if (!app || prefersReducedMotion() || app.classList.contains("is-workspace")) return;
  prepareOverviewStripReturn();
  app.classList.add("is-overview-restoring", "is-overview-booting");
  window.setTimeout(() => {
    app.classList.remove("is-overview-restoring", "is-overview-booting");
  }, 1180);
}

async function playOverviewToWorkspace(view) {
  const app = $("#app");
  if (!app || prefersReducedMotion()) return;
  prepareOverviewStripExit(view);
  refreshTransitionFace();
  app.offsetHeight;
  app.classList.add("is-overview-exiting", "is-workspace-wipe");
  await waitForMotion(OVERVIEW_TO_WORKSPACE_WIPE_WAIT_MS);
}

async function playWorkspaceSwitchOut() {
  const app = $("#app");
  const rail = document.querySelector(".object-rail");
  if (!app || prefersReducedMotion()) return;
  app.classList.add("is-view-switching", "is-view-exiting");
  rail?.classList.add("is-reel-rolling-out");
  await waitForMotion(210);
  app.classList.remove("is-view-exiting");
  rail?.classList.remove("is-reel-rolling-out");
}

function playWorkspaceSwitchIn() {
  const app = $("#app");
  const rail = document.querySelector(".object-rail");
  if (!app || prefersReducedMotion()) return;
  app.classList.add("is-view-entering");
  rail?.classList.add("is-reel-rolling-in");
  window.setTimeout(() => {
    app.classList.remove("is-view-entering", "is-view-switching");
    rail?.classList.remove("is-reel-rolling-in");
  }, 560);
}

async function playScopedRailSwitchOut() {
  const app = $("#app");
  const rail = document.querySelector(".object-rail");
  if (!app || prefersReducedMotion()) return;
  app.classList.add("is-scoped-view-switching", "is-scoped-view-exiting");
  rail?.classList.add("is-reel-rolling-out");
  await waitForMotion(210);
  app.classList.remove("is-scoped-view-exiting");
  rail?.classList.remove("is-reel-rolling-out");
}

function playScopedRailSwitchIn() {
  const app = $("#app");
  const rail = document.querySelector(".object-rail");
  if (!app || prefersReducedMotion()) return;
  app.classList.add("is-scoped-view-entering");
  rail?.classList.add("is-reel-rolling-in");
  window.setTimeout(() => {
    app.classList.remove("is-scoped-view-entering", "is-scoped-view-switching");
    rail?.classList.remove("is-reel-rolling-in");
  }, 560);
}

async function playRailRefreshTransition(task) {
  const app = $("#app");
  const button = $("#refreshBtn");
  const isWorkspace = app?.classList.contains("is-workspace");
  const isPersonalRefresh = isWorkspace && state.activeView === "review";
  let armedPersonalRefresh = false;
  button.disabled = true;
  button.classList.add("is-loading");
  try {
    if (isPersonalRefresh) {
      await retractScheduleFilmBeforeDateMove();
      state.animatePersonalDateRail = true;
      armedPersonalRefresh = true;
    }
    if (isWorkspace && !prefersReducedMotion()) {
      document.querySelector(".object-rail")?.classList.add("is-reel-refreshing-out");
      await waitForMotion(180);
    }
    await task();
    armedPersonalRefresh = false;
    if (isWorkspace && !prefersReducedMotion()) {
      const rail = document.querySelector(".object-rail");
      rail?.classList.remove("is-reel-refreshing-out");
      rail?.classList.add("is-reel-refreshing-in");
      requestRailCoverflow();
      await waitForMotion(540);
      rail?.classList.remove("is-reel-refreshing-in");
      if (isPersonalRefresh) requestAnimationFrame(alignPersonalScheduleToReel);
    }
    showToast("胶卷已刷新");
  } catch (error) {
    showToast(error.message || "刷新失败", "error");
  } finally {
    if (armedPersonalRefresh) state.animatePersonalDateRail = false;
    button.disabled = false;
    button.classList.remove("is-loading");
    document.querySelector(".object-rail")?.classList.remove("is-reel-refreshing-out", "is-reel-refreshing-in");
  }
}

async function openView(view) {
  const app = $("#app");
  const wasWorkspace = app.classList.contains("is-workspace");
  const switchingWorkspaceView = wasWorkspace && state.activeView !== view;
  const scopedRailSwitch = switchingWorkspaceView && Boolean(scopedViewScope(state.activeView)) && Boolean(scopedViewScope(view));
  const enteringPersonalMemory = view === "review" && (!wasWorkspace || state.activeView !== "review");
  const token = ++workspaceTransitionToken;
  if (wasWorkspace && state.activeView === view) return;
  if (!wasWorkspace) {
    await playOverviewToWorkspace(view);
    if (token !== workspaceTransitionToken) return;
  } else if (scopedRailSwitch) {
    await playScopedRailSwitchOut();
    if (token !== workspaceTransitionToken) return;
  } else if (switchingWorkspaceView) {
    await playWorkspaceSwitchOut();
    if (token !== workspaceTransitionToken) return;
  }
  if (view !== "review") removeRailMountedScheduleFilm();
  state.personalEntranceRevealRequested = enteringPersonalMemory;
  state.activeView = view;
  if (view !== "review") state.activeBucketId = "all";
  app.classList.add("is-workspace");
  app.classList.toggle("is-workspace-entering", !wasWorkspace);
  app.classList.remove("is-workspace-ready");
  if (!wasWorkspace) app.classList.remove("is-workspace-settled");
  app.classList.toggle("is-personal-memory", view === "review");
  app.classList.toggle("is-scoped-settings-mode", Boolean(scopedViewScope(view)) && isScopedSettingsMode(view));
  app.dataset.workspaceView = view;
  $("#backHomeBtn").classList.remove("hidden");
  $$(".filmstrip").forEach((strip) => {
    strip.classList.toggle("is-locked", strip.dataset.view === view);
  });
  $$(".view").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `view-${view}`);
  });
  $("#workspaceTitle").textContent = VIEWS[view]?.title || "记忆面板";
  $("#workspaceHint").textContent = VIEWS[view]?.hint || "";
  renderScopedModeControls(view);
  if (view === "film") {
    renderScopedBucketRail("group");
  } else if (view === "maintain") {
    renderScopedBucketRail("private");
  } else if (view !== "review") {
    renderSecondaryNav(view, !switchingWorkspaceView);
  }
  const loading = loadActiveView();
  requestRailCoverflow();
  await loading;
  if (!wasWorkspace) {
    app.offsetHeight;
    app.classList.add("is-workspace-ready", "is-workspace-settled");
  }
  if (scopedRailSwitch) {
    playScopedRailSwitchIn();
  } else if (switchingWorkspaceView) {
    playWorkspaceSwitchIn();
  }
  if (!wasWorkspace) {
    window.setTimeout(() => {
      app.classList.remove("is-overview-exiting", "is-workspace-wipe", "is-workspace-entering", "is-workspace-ready");
    }, prefersReducedMotion() ? 0 : WORKSPACE_WIPE_CLEANUP_MS);
  }
}
  
async function returnHome() {
  const app = $("#app");
  if (!app.classList.contains("is-workspace") || homeReturnRunning) return;
  homeReturnRunning = true;
  workspaceTransitionToken++;
  $("#backHomeBtn").disabled = true;
  refreshTransitionFace();
  app.classList.add("is-home-wipe");
  await waitForMotion(HOME_WIPE_SWAP_WAIT_MS);
  removeRailMountedScheduleFilm();
  app.classList.remove("is-workspace");
  app.classList.remove("is-personal-memory");
  app.classList.remove("is-scoped-settings-mode");
  app.classList.remove("is-workspace-entering", "is-workspace-ready", "is-workspace-settled");
  app.classList.remove("is-view-switching", "is-view-exiting", "is-view-entering");
  app.classList.remove("is-scoped-view-switching", "is-scoped-view-exiting", "is-scoped-view-entering");
  app.style.removeProperty("--secondary-nav-shift");
  delete app.dataset.workspaceView;
  prepareOverviewStripReturn();
  $("#backHomeBtn").classList.add("hidden");
  $("#backHomeBtn").disabled = false;
  $$(".filmstrip").forEach((strip) => strip.classList.remove("is-locked"));
  requestRailCoverflow();
  app.classList.add("is-overview-restoring");
  await waitForMotion(HOME_WIPE_TOTAL_WAIT_MS);
  app.classList.remove("is-overview-restoring", "is-home-wipe");
  homeReturnRunning = false;
}

async function loadActiveView() {
  try {
    if (state.activeView === "objects") {
      await loadContextPanel();
    } else if (state.activeView === "film") {
      if (isScopedSettingsMode("film")) {
        await loadScopedSettings("#groupMemoryList", "group");
      } else {
        await loadScopedMemories("#groupMemoryList", "group", "正在读取群聊记忆...", "还没有群聊范围内的记忆。");
      }
    } else if (state.activeView === "microscope") {
      applyMicroscopeView();
    } else if (state.activeView === "relations") {
      await loadUserMemory();
    } else if (state.activeView === "review") {
      await loadPersonalMemory();
    } else if (state.activeView === "maintain") {
      if (isScopedSettingsMode("maintain")) {
        await loadScopedSettings("#privateMemoryList", "private");
      } else {
        await loadScopedMemories("#privateMemoryList", "private", "正在读取私聊记忆...", "还没有私聊范围内的记忆。");
      }
    } else if (state.activeView === "archive") {
      await loadArchive();
    }
  } catch (error) {
    renderViewError(error);
    showToast(error.message || "读取失败", "error");
  }
}

function renderViewError(error) {
  const targets = {
    objects: "#contextPanel",
    film: "#groupMemoryList",
    relations: "#relationList",
    review: "#personalMemoryList",
    maintain: "#privateMemoryList",
    archive: "#importResult",
  };
  const selector = targets[state.activeView];
  if (!selector) return;
  const target = $(selector);
  if (!target) return;
  if (target.hidden) target.hidden = false;
  target.innerHTML = panelError(error);
  const retry = target.querySelector("[data-retry-active]");
  if (retry) retry.addEventListener("click", () => loadActiveView());
}

function memoryRow(memory) {
  const content = compact(memory.content, "(空内容)");
  const canonical = compact(memory.canonical_summary, "");
  const keyFacts = Array.isArray(memory.key_facts) ? memory.key_facts.filter(Boolean).slice(0, 2) : [];
  const evidence = compact(memory.evidence_preview, "");
  const previewParts = [];
  if (canonical && canonical !== content) previewParts.push(canonical);
  keyFacts.forEach((fact) => {
    if (fact && fact !== content && !previewParts.includes(fact)) previewParts.push(fact);
  });
  if (evidence && evidence !== content && !previewParts.includes(evidence)) previewParts.push(evidence);
  const preview = previewParts.join(" / ");
  const topicTags = Array.isArray(memory.topics) ? memory.topics.filter(Boolean).slice(0, 2) : [];
  return `
    <article class="row-item memory-frame" data-memory-id="${escapeHtml(memory.id)}">
      <div class="memory-frame-time">
        <b>${escapeHtml(formatTime(memory.occurred_at || memory.created_at))}</b>
        <span>${escapeHtml(shortId(memory.id))}</span>
      </div>
      <div class="memory-frame-main">
        <div class="memory-frame-text">
          <span class="item-title">${escapeHtml(content)}</span>
          ${preview ? `<p class="memory-preview">${escapeHtml(preview)}</p>` : ""}
        </div>
        <div class="badges">
          <span class="badge teal">${escapeHtml(memory.memory_type)}</span>
          <span class="badge blue">${escapeHtml(memory.visibility)}</span>
          <span class="badge gold">${escapeHtml(memory.reality_level)}</span>
          ${topicTags.map((tag) => `<span class="badge blue">${escapeHtml(tag)}</span>`).join("")}
        </div>
      </div>
    </article>
  `;
}

async function loadMemories(extra = {}) {
  const query = $("#globalSearch").value.trim();
  const params = contextParams({ limit: extra.limit || 80, q: query, ...extra });
  const data = await apiGet(`/memories?${params.toString()}`);
  return data.memories || [];
}

function scopedMemoryParams(scope, extra = {}) {
  const query = $("#globalSearch").value.trim();
  const params = new URLSearchParams();
  params.set("limit", String(extra.limit || 100));
  if (query) params.set("q", query);
  if (scope) params.set("scope", scope);
  Object.entries(extra).forEach(([key, value]) => {
    if (key !== "limit" && value !== undefined && value !== null && String(value).trim()) {
      params.set(key, String(value).trim());
    }
  });

  const bucket = activeBucket();
  if (!bucket || bucket.id === "all") return { params, incompatible: false };
  if (bucket.id === "self") return { params, incompatible: Boolean(scope) };
  if (scope && bucket.scope && bucket.scope !== scope) return { params, incompatible: true };

  if (bucket.scope) params.set("scope", bucket.scope);
  if (bucket.scope === "private") {
    if (bucket.target_id) params.set("entity_id", bucket.target_id);
    if (bucket.session_id) params.set("session_id", bucket.session_id);
  } else if (bucket.scope === "group") {
    if (bucket.group_id) params.set("group_id", bucket.group_id);
    if (bucket.session_id) params.set("session_id", bucket.session_id);
  }
  return { params, incompatible: false };
}

function renderMemoryList(selector, memories, emptyText) {
  const target = $(selector);
  if (!target) return;
  target.className = "row-list";
  target.innerHTML = memories.length
    ? memories.map(memoryRow).join("")
    : `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
  target.querySelectorAll("[data-memory-id]").forEach((row) => {
    row.addEventListener("click", () => showMemory(row.dataset.memoryId));
  });
}

function relationTypesForSecondary() {
  const active = activeSecondaryNav("relations");
  const map = {
    profile: ["user_profile"],
    preference: ["user_preference"],
    relationship: ["relationship_claim"],
    explicit: ["explicit_memory"],
  };
  return map[active] || ["user_profile", "user_preference", "explicit_memory", "relationship_claim"];
}

async function loadScopedMemories(selector, scope, loadingText, emptyText, extra = {}) {
  const target = $(selector);
  if (!target) return;
  target.className = "row-list";
  target.innerHTML = loadingState(loadingText);
  const { params, incompatible } = scopedMemoryParams(scope, { limit: 120, ...extra });
  if (incompatible) {
    const label = scope === "group" ? "群聊" : "私聊";
    target.innerHTML = `<div class="empty-state">当前观察对象不属于${escapeHtml(label)}范围。请选择${escapeHtml(label)}对象或切回全部。</div>`;
    return;
  }
  const data = await apiGet(`/memories?${params.toString()}`);
  renderMemoryList(selector, data.memories || [], emptyText);
}

async function loadScopedSettings(selector, scope) {
  const target = $(selector);
  if (!target) return;
  target.className = "settings-placeholder is-empty";
  const bucket = activeBucket();
  if (!isWindowBucket(bucket) || bucket.scope !== scope) {
    target.innerHTML = "";
    $("#detailDrawer").className = "detail-drawer permission-drawer empty";
    $("#detailDrawer").innerHTML = renderScopedSettingsLanding(scope);
    return;
  }
  target.innerHTML = "";
  await showBucketPermissions(bucket.id, "#detailDrawer");
}

function renderScopedSettingsLanding(scope) {
  const scopedBuckets = state.buckets.filter((bucket) => bucket.scope === scope);
  return `
    <section class="permission-landing">
      <div>
        <b>${escapeHtml(windowKindLabel(scope))}记忆设置</b>
        <p>${escapeHtml(scopedSettingsHint(scope))}</p>
      </div>
      <div class="badges">
        <span class="badge gold">${escapeHtml(scopedDefaultModeLabel(scope))}</span>
        <span class="badge blue">${escapeHtml(scopedBuckets.length)} 个对象</span>
      </div>
      <p class="permission-instruction">请从左侧${escapeHtml(scope === "group" ? "群聊列表" : "私聊用户列表")}选择具体对象；右侧上方面板会显示读取权限、被读取权限和黑白名单配置。</p>
    </section>
  `;
}

function hasMemoryType(memory, types) {
  return types.includes(memory.memory_type);
}

function isUserMemory(memory) {
  return hasMemoryType(memory, ["user_profile", "user_preference", "explicit_memory", "relationship_claim"]);
}

function isPersonalMemory(memory) {
  return memory.visibility === "bot_self"
    && (
      hasMemoryType(memory, ["schedule_fragment", "persona_life"])
      || memory.source_plugin === "private_companion"
      || (memory.tags || []).includes("schedule")
      || (memory.tags || []).includes("persona_life")
    );
}

async function loadContextPanel() {
  const target = $("#contextPanel");
  if (!target) return;
  target.className = "page-panel-stack";
  const section = activeSecondaryNav("objects");
  target.innerHTML = loadingState("正在读取知识图谱...");
  const params = contextParams({ limit: section === "overview" ? 8 : 60 });
  if (section === "relations") {
    const data = await apiGet(`/graph?${params.toString()}`);
    target.innerHTML = renderKnowledgeGraphEdges(data.items || []);
  } else if (section === "threads") {
    params.set("status", "all");
    const data = await apiGet(`/threads?${params.toString()}`);
    target.innerHTML = renderKnowledgeThreads(data.items || []);
  } else if (section === "timeline") {
    const data = await apiGet(`/timeline?${params.toString()}`);
    target.innerHTML = renderKnowledgeTimeline(data.items || []);
  } else {
    const [graph, relations, threads, timeline] = await Promise.all([
      apiGet(`/graph?${params.toString()}`),
      apiGet(`/relations?${params.toString()}`),
      apiGet(`/threads?${new URLSearchParams({ ...Object.fromEntries(params), status: "all" }).toString()}`),
      apiGet(`/timeline?${params.toString()}`),
    ]);
    target.innerHTML = renderKnowledgeOverview({
      graph: graph.items || [],
      relations: relations.items || [],
      threads: threads.items || [],
      timeline: timeline.items || [],
    });
  }
  bindKnowledgeGraphRows(target);
}

function bindKnowledgeGraphRows(target) {
  target.querySelectorAll("[data-raw]").forEach((row) => {
    row.addEventListener("click", () => {
      const title = row.dataset.detailTitle || "图谱节点";
      showGenericDetail(title, JSON.parse(row.dataset.raw || "{}"));
    });
  });
}

function rawAttr(value) {
  return escapeHtml(JSON.stringify(value || {}));
}

function renderKnowledgeOverview({ graph = [], relations = [], threads = [], timeline = [] } = {}) {
  const activeThreads = threads.filter((item) => (item.status || "open") === "open").length;
  return `
    <section class="context-section film-panel">
      <h4>知识图谱总览</h4>
      <div class="config-grid">
        ${configCard("图谱边", `${graph.length} 条`, "从阶段性记忆抽出的节点关联", "teal", "图谱")}
        ${configCard("身份关系", `${relations.length} 条`, "明确关系声明和身份边界", "violet", "关系")}
        ${configCard("开放线程", `${activeThreads} 条`, "需要跨私聊/群聊承接的线索", "gold", "线程")}
        ${configCard("时间线节点", `${timeline.length} 条`, "最近记录的事件、消息和整理结果", "blue", "时间")}
      </div>
    </section>
    ${renderKnowledgeGraphEdges(graph, "最近图谱边")}
    ${renderKnowledgeRelations(relations, "最近身份关系")}
    ${renderKnowledgeThreads(threads, "最近跨窗口线程")}
    ${renderKnowledgeTimeline(timeline, "最近时间线")}
  `;
}

function renderKnowledgeGraphEdges(items, title = "图谱边") {
  return `
    <section class="context-section film-panel">
      <h4>${escapeHtml(title)}</h4>
      <div class="row-list compact">
        ${items.length ? items.map((item) => `
          <article class="row-item memory-frame" data-raw="${rawAttr(item)}" data-detail-title="知识图谱边详情">
            <div class="memory-frame-time">
              <b>${escapeHtml(formatTime(item.updated_at || item.created_at))}</b>
              <span>${escapeHtml(shortId(item.id))}</span>
            </div>
            <div class="memory-frame-main">
              <span class="item-title">${escapeHtml(compact(item.source_label, "未知节点"))} -> ${escapeHtml(compact(item.target_label, "未知节点"))}</span>
              <p>${escapeHtml(compact(item.evidence, "暂无证据文本"))}</p>
              <div class="badges">
                <span class="badge teal">${escapeHtml(compact(item.relation_type, "edge"))}</span>
                <span class="badge blue">${escapeHtml(compact(item.source_type, "node"))} -> ${escapeHtml(compact(item.target_type, "node"))}</span>
                <span class="badge gold">置信 ${escapeHtml(Math.round(Number(item.confidence || 0) * 100))}%</span>
              </div>
            </div>
          </article>
        `).join("") : `<div class="empty-state">当前范围还没有图谱边。阶段性总结生成后会自动建立。</div>`}
      </div>
    </section>
  `;
}

function renderKnowledgeRelations(items, title = "关系边") {
  return `
    <section class="context-section film-panel">
      <h4>${escapeHtml(title)}</h4>
      <div class="row-list compact">
        ${items.length ? items.map((item) => `
          <article class="row-item memory-frame" data-raw="${rawAttr(item)}" data-detail-title="关系边详情">
            <div class="memory-frame-time">
              <b>${escapeHtml(formatTime(item.updated_at || item.created_at))}</b>
              <span>${escapeHtml(shortId(item.id))}</span>
            </div>
            <div class="memory-frame-main">
              <span class="item-title">${escapeHtml(compact(item.subject_name || item.subject_id, "未知对象"))} -> ${escapeHtml(compact(item.object_name || item.object_id, "未知对象"))}</span>
              <p>${escapeHtml(compact(item.evidence, "暂无证据文本"))}</p>
              <div class="badges">
                <span class="badge teal">${escapeHtml(compact(item.relation_type, "relation"))}</span>
                <span class="badge blue">${escapeHtml(compact(item.scope, "scope"))}</span>
                <span class="badge gold">置信 ${escapeHtml(Math.round(Number(item.confidence || 0) * 100))}%</span>
              </div>
            </div>
          </article>
        `).join("") : `<div class="empty-state">当前范围还没有关系边。</div>`}
      </div>
    </section>
  `;
}

function renderKnowledgeThreads(items, title = "跨窗口线程") {
  return `
    <section class="context-section film-panel">
      <h4>${escapeHtml(title)}</h4>
      <div class="row-list compact">
        ${items.length ? items.map((item) => `
          <article class="row-item memory-frame" data-raw="${rawAttr(item)}" data-detail-title="跨窗口线程详情">
            <div class="memory-frame-time">
              <b>${escapeHtml(formatTime(item.updated_at || item.created_at))}</b>
              <span>${escapeHtml(shortId(item.id))}</span>
            </div>
            <div class="memory-frame-main">
              <span class="item-title">${escapeHtml(compact(item.topic, "未命名线程"))}</span>
              <p>${escapeHtml(compact(item.content, "暂无线程内容"))}</p>
              <div class="badges">
                <span class="badge ${item.status === "closed" ? "violet" : "teal"}">${escapeHtml(item.status || "open")}</span>
                <span class="badge blue">${escapeHtml(shortId(item.from_session))} -> ${escapeHtml(shortId(item.to_session))}</span>
                <span class="badge gold">${escapeHtml(item.visibility || "shareable")}</span>
              </div>
            </div>
          </article>
        `).join("") : `<div class="empty-state">当前范围还没有跨窗口线程。</div>`}
      </div>
    </section>
  `;
}

function renderKnowledgeTimeline(items, title = "时间线") {
  return `
    <section class="context-section film-panel">
      <h4>${escapeHtml(title)}</h4>
      <div class="row-list compact">
        ${items.length ? items.map((item) => `
          <article class="row-item memory-frame" data-raw="${rawAttr(item)}" data-detail-title="时间线节点详情">
            <div class="memory-frame-time">
              <b>${escapeHtml(formatTime(item.occurred_at || item.created_at))}</b>
              <span>${escapeHtml(shortId(item.id))}</span>
            </div>
            <div class="memory-frame-main">
              <span class="item-title">${escapeHtml(compact(item.content, "空时间线节点"))}</span>
              <div class="badges">
                <span class="badge teal">${escapeHtml(compact(item.event_type, "event"))}</span>
                <span class="badge blue">${escapeHtml(compact(item.scope, "scope"))}</span>
                <span class="badge gold">${escapeHtml(shortId(item.session_id))}</span>
              </div>
            </div>
          </article>
        `).join("") : `<div class="empty-state">当前范围还没有时间线节点。</div>`}
      </div>
    </section>
  `;
}

function boolLabel(value) {
  return value ? "开启" : "关闭";
}

function queryModeLabel(mode) {
  if (mode === "guarded_companion") return "受保护陪伴";
  if (mode === "companion_augmented") return "增强检索";
  return "当前消息";
}

function queryModeNote(mode) {
  if (mode === "guarded_companion") return "线索与当前消息重叠时才扩展检索";
  if (mode === "companion_augmented") return "直接拼接陪伴线索，适合强联动场景";
  return "只用当前用户消息检索，记忆作为附加资料";
}

function queryModeTone(mode) {
  if (mode === "companion_augmented") return "gold";
  if (mode === "guarded_companion") return "teal";
  return "blue";
}

function retrievalModeLabel(mode) {
  if (mode === "basic") return "本地检索";
  if (mode === "rerank") return "强制重排";
  return "自动选择";
}

function retrievalModeNote(retrieval = {}) {
  const mode = retrieval.mode || "auto";
  const provider = retrieval.rerank_provider_id || "自动探测";
  const limit = retrieval.rerank_candidate_limit ?? 32;
  if (mode === "basic") return "不额外调用重排模型，完全使用本地可解释排序";
  if (mode === "rerank") return `Provider ${provider} · 候选上限 ${limit}`;
  return `有 rerank provider 时二阶段重排，否则回退本地 · 候选上限 ${limit}`;
}

function retrievalModeTone(mode) {
  if (mode === "basic") return "blue";
  if (mode === "rerank") return "violet";
  return "teal";
}

function configCard(title, value, note, tone = "blue", badge = "配置") {
  return `
    <article class="config-card">
      <div class="config-card-top">
        <span class="item-title">${escapeHtml(title)}</span>
        <span class="badge ${escapeHtml(tone)}">${escapeHtml(badge)}</span>
      </div>
      <b>${escapeHtml(value)}</b>
      <small>${escapeHtml(note)}</small>
    </article>
  `;
}

function contextSwitch(name, checked = false) {
  return `
    <label class="context-switch">
      <input name="${escapeHtml(name)}" type="checkbox"${checked ? " checked" : ""} />
      <span></span>
    </label>
  `;
}

function contextField({ label, hint, control, wide = false }) {
  return `
    <div class="context-form-row${wide ? " is-wide" : ""}">
      <span>
        <b>${escapeHtml(label)}</b>
        <small>${escapeHtml(hint)}</small>
      </span>
      <div class="context-control">${control}</div>
    </div>
  `;
}

function renderContextLogs(logs) {
  return `
    <section class="context-section context-logs film-panel">
      <div class="personal-zone-head">
        <h4>最近注入记录</h4>
        <span>${escapeHtml(logs.length)} Frames</span>
      </div>
      <div class="row-list">
        ${logs.length ? logs.map((item) => `
          <article class="row-item memory-frame" data-raw="${escapeHtml(JSON.stringify(item))}">
            <div class="memory-frame-time">
              <b>${escapeHtml(formatTime(item.created_at))}</b>
              <span>${escapeHtml(item.scope || "unknown")}</span>
            </div>
            <div class="memory-frame-main">
              <span class="item-title">${escapeHtml(item.query || "未记录查询文本")}</span>
              <div class="badges">
                <span class="badge blue">选中 ${escapeHtml((item.selected_memory_ids || []).length)} 条</span>
                <span class="badge teal">过滤 ${escapeHtml((item.blocked_reasons || []).length)} 条</span>
                <span class="badge gold">${escapeHtml(shortId(item.session_id || "-"))}</span>
              </div>
            </div>
          </article>
        `).join("") : `<div class="empty-state">当前范围还没有注入日志。</div>`}
      </div>
    </section>
  `;
}

async function loadUserMemory() {
  const target = $("#relationList");
  if (!target) return;
  target.innerHTML = loadingState("正在读取用户记忆...");
  const types = relationTypesForSecondary();
  const memories = (await loadMemories({ limit: 160 })).filter((memory) => hasMemoryType(memory, types));
  renderMemoryList("#relationList", memories, "当前范围还没有用户画像、偏好或关系声明。");
}

async function loadPersonalMemory() {
  const target = $("#personalMemoryList");
  if (!target) return;
  removeRailMountedScheduleFilm();
  const shouldAnimateEntrance = state.personalEntranceRevealRequested;
  state.personalEntranceRevealRequested = false;
  if (state.companionPersonalAvailable === false) {
    updatePersonalMemoryAvailability(false);
    target.innerHTML = renderPersonalMemoryUnavailable("未检测到已加载的主动陪伴插件");
    return;
  }
  target.innerHTML = loadingState("正在读取个人记忆...");
  const query = $("#globalSearch").value.trim();
  const params = new URLSearchParams({ limit: "80" });
  if (query) params.set("q", query);
  if (state.selectedPersonalDate) params.set("date", state.selectedPersonalDate);
  const data = await apiGet(`/companion/personal-memory?${params.toString()}`);
  updatePersonalMemoryAvailability(Boolean(data.available));
  if (!data.available) {
    target.innerHTML = renderPersonalMemoryUnavailable(data.reason || "未检测到已加载的主动陪伴插件");
    return;
  }
  state.selectedPersonalDate = data.selected_date || state.selectedPersonalDate || "";
  if (shouldAnimateEntrance) state.animatePersonalDateRail = true;
  renderPersonalDateRail(data.dates || [], state.selectedPersonalDate);
  target.innerHTML = renderPersonalMemoryWorkspace(data.snapshot || {}, data);
  bindPersonalMemoryWorkspace(target, data.snapshot || {}, data);
}

function bindPersonalMemoryWorkspace(target, snapshot, data) {
  target.querySelectorAll("[data-memory-id]").forEach((row) => {
    row.addEventListener("click", () => showMemory(row.dataset.memoryId));
  });
  const film = target.querySelector("[data-schedule-film]");
  const selectSchedule = (index, options = {}) => {
    state.selectedScheduleIndex = index || "";
    target.querySelectorAll(".schedule-frame").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.scheduleIndex === state.selectedScheduleIndex);
    });
    updateScheduleSummary(target, snapshot, { animate: true });
    showPersonalScheduleDetail(snapshot, data, { animate: true });
    if (!options.preserveOffset) centerScheduleFrame(film, state.selectedScheduleIndex);
  };
  target.querySelectorAll("[data-schedule-index]").forEach((row) => {
    row.addEventListener("click", () => {
      if (row.closest("[data-schedule-film]")?.dataset.draggingClick === "1") return;
      selectSchedule(row.dataset.scheduleIndex);
    });
  });
  setupScheduleFilmDrag(film, selectSchedule);
  mountScheduleFilmToRail(film);
  const shouldRevealAfterReel = state.pendingPersonalFilmReveal;
  state.pendingPersonalFilmReveal = false;
  if (shouldRevealAfterReel) {
    prepareScheduleFilmPeek(film);
    revealScheduleFilmAfterReel(film);
  } else {
    requestAnimationFrame(() => applyScheduleFilmOffset(film, 0, true));
    requestAnimationFrame(alignPersonalScheduleToReel);
  }
  updateScheduleSummary(target, snapshot);
  showPersonalScheduleDetail(snapshot, data);
}

function mountScheduleFilmToRail(film) {
  const rail = document.querySelector(".object-rail");
  if (!film || !rail || film.classList.contains("is-rail-mounted")) return;
  film.classList.add("is-rail-mounted");
  rail.appendChild(film);
}

function removeRailMountedScheduleFilm() {
  document.querySelector(".schedule-film.is-rail-mounted")?.remove();
}

function prepareScheduleFilmPeek(film) {
  if (!film) return;
  film.classList.add("is-peeking");
  film.style.transition = "none";
  film.style.minWidth = "0px";
  film.style.width = "0px";
  film.offsetHeight;
  film.style.transition = "";
}

function retractScheduleFilmBeforeDateMove() {
  const film = document.querySelector(".schedule-film.is-rail-mounted");
  if (!film || film.classList.contains("is-peeking")) return Promise.resolve();
  const currentWidth = Math.round(film.getBoundingClientRect().width);
  if (currentWidth <= 2) return Promise.resolve();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.clearTimeout(film._retractTimer);
      film.removeEventListener("transitionend", onEnd);
      film.style.transition = "";
      resolve();
    };
    const onEnd = (event) => {
      if (event.target !== film || event.propertyName !== "width") return;
      finish();
    };
    window.clearTimeout(film._retractTimer);
    film.classList.add("is-peeking", "is-retracting");
    film.style.minWidth = "0px";
    film.style.width = `${currentWidth}px`;
    film.style.transition = "width .38s cubic-bezier(.34,.02,.18,1)";
    film.offsetHeight;
    film.addEventListener("transitionend", onEnd);
    requestAnimationFrame(() => {
      film.style.width = "0px";
    });
    film._retractTimer = window.setTimeout(finish, 460);
  });
}

function revealScheduleFilmAfterReel(film) {
  if (!film) return;
  const list = $("#bucketList");
  let done = false;
  const reveal = () => {
    if (done) return;
    done = true;
    window.clearTimeout(film?._revealTimer);
    list?.removeEventListener("transitionend", onMotionEnd);
    list?.removeEventListener("animationend", onMotionEnd);
    alignPersonalScheduleToReel();
    requestAnimationFrame(() => revealScheduleFilmPeek(film));
  };
  const onMotionEnd = (event) => {
    if (event.target !== list) return;
    if (event.type === "transitionend" && event.propertyName !== "transform") return;
    reveal();
  };
  requestAnimationFrame(() => {
    list?.addEventListener("transitionend", onMotionEnd);
    list?.addEventListener("animationend", onMotionEnd);
    film._revealTimer = window.setTimeout(reveal, 820);
  });
}

function revealScheduleFilmPeek(film) {
  if (!film) return;
  applyScheduleFilmOffset(film, 0, false);
  window.clearTimeout(film._peekTimer);
  film._peekTimer = window.setTimeout(() => {
    film.classList.remove("is-peeking");
    film.style.minWidth = "";
  }, 760);
}

function alignPersonalScheduleToReel() {
  const app = $("#app");
  const film = document.querySelector("[data-schedule-film]");
  const reel = document.querySelector(".bucket.date-reel.is-active");
  if (!app || !film || !reel || state.activeView !== "review") {
    app?.style.removeProperty("--personal-film-lift");
    app?.style.removeProperty("--personal-film-shift");
    app?.style.removeProperty("--personal-detail-offset");
    app?.style.removeProperty("--personal-main-height");
    return;
  }
  const styles = getComputedStyle(app);
  const currentLift = parseFloat(styles.getPropertyValue("--personal-film-lift")) || 0;
  const currentShift = parseFloat(styles.getPropertyValue("--personal-film-shift")) || 0;
  const filmRect = film.getBoundingClientRect();
  const reelRect = reel.getBoundingClientRect();
  if (film.classList.contains("is-rail-mounted")) {
    const rail = document.querySelector(".object-rail");
    const railRect = rail?.getBoundingClientRect();
    if (!railRect) return;
    app.style.removeProperty("--personal-film-lift");
    app.style.removeProperty("--personal-film-shift");
    if (getComputedStyle(film).position !== "absolute") {
      alignPersonalPanelsAroundFilm(film.getBoundingClientRect().top, film.getBoundingClientRect().bottom);
      return;
    }
    const top = reelRect.top + reelRect.height / 2 - filmRect.height / 2 - railRect.top;
    const left = reelRect.left + 48 - railRect.left;
    film.style.setProperty("--personal-film-top", `${Math.round(top)}px`);
    film.style.setProperty("--personal-film-left", `${Math.round(left)}px`);
    alignPersonalPanelsAroundFilm(railRect.top + top, railRect.top + top + filmRect.height);
    return;
  }
  const unshiftedTop = filmRect.top - currentLift;
  const unshiftedLeft = filmRect.left - currentShift;
  const targetTop = reelRect.top + reelRect.height / 2 - filmRect.height / 2;
  const targetLeft = reelRect.left + 48;
  const lift = Math.round(targetTop - unshiftedTop);
  const shift = Math.round(targetLeft - unshiftedLeft);
  app.style.setProperty("--personal-film-lift", `${lift}px`);
  app.style.setProperty("--personal-film-shift", `${shift}px`);
  const filmTop = reelRect.top + reelRect.height / 2 - filmRect.height / 2;
  alignPersonalPanelsAroundFilm(filmTop, filmTop + filmRect.height);
}

function alignPersonalPanelsAroundFilm(filmTop, filmBottom) {
  alignPersonalSummaryAboveFilm(filmTop);
  document.querySelector(".workspace-main")?.offsetHeight;
  alignPersonalDetailBelowFilm(filmBottom);
}

function alignPersonalSummaryAboveFilm(filmTop) {
  const app = $("#app");
  const main = document.querySelector(".workspace-main");
  if (!app || !main || state.activeView !== "review") return;
  if (window.matchMedia("(max-width: 1080px)").matches) {
    app.style.removeProperty("--personal-main-height");
    return;
  }
  const mainRect = main.getBoundingClientRect();
  const height = Math.max(154, Math.round(filmTop - mainRect.top));
  app.style.setProperty("--personal-main-height", `${height}px`);
}

function alignPersonalDetailBelowFilm(filmBottom) {
  const app = $("#app");
  const detail = $("#detailDrawer");
  if (!app || !detail || state.activeView !== "review") return;
  if (app.style.getPropertyValue("--personal-detail-offset")) return;
  const currentOffset = parseFloat(getComputedStyle(app).getPropertyValue("--personal-detail-offset")) || 0;
  const detailRect = detail.getBoundingClientRect();
  const unshiftedTop = detailRect.top - currentOffset;
  const targetTop = Math.round(filmBottom + 16);
  const offset = Math.round(targetTop - unshiftedTop);
  const next = window.matchMedia("(max-width: 1080px)").matches ? Math.max(0, offset) : offset;
  app.style.setProperty("--personal-detail-offset", `${next}px`);
}

function setupScheduleFilmDrag(film, selectSchedule) {
  if (!film) return;
  const track = film.querySelector("[data-schedule-track]");
  if (!track) return;
  let isDown = false;
  let startX = 0;
  let startOffset = 0;
  let moved = 0;
  let lastSelected = "";
  const selectNearestAtMarker = () => {
    const nearest = nearestScheduleFrame(film);
    if (!nearest || nearest.dataset.scheduleIndex === lastSelected) return;
    lastSelected = nearest.dataset.scheduleIndex;
    selectSchedule(lastSelected, { preserveOffset: true });
  };
  applyScheduleFilmOffset(film, Number(film.dataset.offset || 0), true);
  selectNearestAtMarker();
  film.addEventListener("pointerdown", (event) => {
    if (event.button !== undefined && event.button !== 0) return;
    isDown = true;
    moved = 0;
    startX = event.clientX;
    startOffset = Number(film.dataset.offset || 0);
    film.classList.add("is-dragging");
    film.setPointerCapture?.(event.pointerId);
  });
  film.addEventListener("pointermove", (event) => {
    if (!isDown) return;
    event.preventDefault();
    const dx = event.clientX - startX;
    moved = Math.max(moved, Math.abs(dx));
    applyScheduleFilmOffset(film, startOffset + dx);
    selectNearestAtMarker();
  });
  const finish = (event) => {
    if (!isDown) return;
    isDown = false;
    const nearest = moved > 8 ? nearestScheduleFrame(film) : null;
    film.classList.remove("is-dragging");
    film.releasePointerCapture?.(event.pointerId);
    if (moved > 8) {
      film.dataset.draggingClick = "1";
      if (nearest) selectSchedule(nearest.dataset.scheduleIndex, { preserveOffset: true });
      window.setTimeout(() => {
        delete film.dataset.draggingClick;
      }, 80);
    }
  };
  film.addEventListener("pointerup", finish);
  film.addEventListener("pointercancel", finish);
  film.addEventListener("mouseleave", (event) => {
    if (isDown) finish(event);
  });
  film.addEventListener("wheel", (event) => {
    event.preventDefault();
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    applyScheduleFilmOffset(film, Number(film.dataset.offset || 0) + delta);
    selectNearestAtMarker();
    window.clearTimeout(film._snapTimer);
    film._snapTimer = window.setTimeout(() => {
      const nearest = nearestScheduleFrame(film);
      if (nearest) selectSchedule(nearest.dataset.scheduleIndex, { preserveOffset: true });
    }, 160);
  }, { passive: false });
  window.addEventListener("resize", () => {
    applyScheduleFilmOffset(film, Number(film.dataset.offset || 0), true);
    alignPersonalScheduleToReel();
  });
}

function nearestScheduleFrame(film) {
  const frames = Array.from(film.querySelectorAll(".schedule-frame"));
  if (!frames.length) return null;
  const filmRect = film.getBoundingClientRect();
  const focus = filmRect.left + scheduleFilmMarkerX(film);
  return frames.reduce((nearest, frame) => {
    const rect = frame.getBoundingClientRect();
    const distance = Math.abs(rect.right - focus);
    if (!nearest || distance < nearest.distance) return { frame, distance };
    return nearest;
  }, null)?.frame || frames[0];
}

function scheduleFilmMaxOffset(film) {
  const frames = Array.from(film?.querySelectorAll(".schedule-frame") || []);
  if (!film || !frames.length) return 0;
  const latest = frames[0];
  const earliest = frames[frames.length - 1];
  const frameWidth = latest.offsetWidth || 260;
  const latestAlignOffset = earliest.offsetLeft - latest.offsetLeft;
  const max = latestAlignOffset + frameWidth;
  return Math.max(0, max);
}

function applyScheduleFilmOffset(film, offset, immediate = false) {
  const track = film?.querySelector("[data-schedule-track]");
  if (!film || !track) return;
  const next = Math.max(0, Math.min(scheduleFilmMaxOffset(film), Number(offset) || 0));
  const base = scheduleFilmBaseWidth(film);
  const visibleWidth = base + next;
  const frames = Array.from(film.querySelectorAll(".schedule-frame"));
  const frameWidth = frames[0]?.offsetWidth || 260;
  const earliest = frames[frames.length - 1];
  const earliestEdge = earliest ? earliest.offsetLeft + frameWidth : track.scrollWidth;
  const trackShift = scheduleFilmMarkerX(film) - earliestEdge + next;
  film.dataset.offset = String(next);
  film.dataset.dragOffset = String(next);
  film.style.setProperty("--schedule-film-pull", `${next}px`);
  film.style.setProperty("--schedule-film-drag", "0px");
  film.style.transition = immediate ? "none" : "";
  film.style.width = `${visibleWidth}px`;
  film.classList.toggle("is-extended", next > 8);
  track.style.transition = immediate ? "none" : "";
  track.style.transform = `translate3d(${trackShift}px,0,0)`;
  if (immediate) {
    track.offsetHeight;
    film.style.transition = "";
    track.style.transition = "";
  }
}

function scheduleFilmBaseWidth(film) {
  const raw = getComputedStyle(film).getPropertyValue("--schedule-film-base");
  return parseFloat(raw) || 150;
}

function scheduleFilmMarkerX(film) {
  const raw = getComputedStyle(film).getPropertyValue("--schedule-marker-x");
  return parseFloat(raw) || scheduleFilmBaseWidth(film) / 2;
}

function centerScheduleFrame(film, index, immediate = false) {
  if (!film || !index) return;
  const frame = Array.from(film.querySelectorAll("[data-schedule-index]"))
    .find((item) => item.dataset.scheduleIndex === String(index));
  if (!frame) return;
  const frames = Array.from(film.querySelectorAll(".schedule-frame"));
  const earliest = frames[frames.length - 1];
  const target = earliest ? earliest.offsetLeft - frame.offsetLeft : 0;
  applyScheduleFilmOffset(film, target, immediate);
}

async function loadCompanionAvailability() {
  try {
    const data = await apiGet("/companion/personal-memory?limit=0");
    updatePersonalMemoryAvailability(Boolean(data.available));
  } catch (error) {
    updatePersonalMemoryAvailability(false);
  }
}

function updatePersonalMemoryAvailability(available) {
  state.companionPersonalAvailable = available;
  const view = available ? PERSONAL_MEMORY_VIEW.available : PERSONAL_MEMORY_VIEW.unavailable;
  VIEWS.review.title = view.title;
  VIEWS.review.hint = view.hint;
  const strip = document.querySelector('[data-view="review"]');
  if (strip) {
    strip.dataset.tipTitle = view.title;
    strip.dataset.tipSub = view.hint;
    const label = strip.querySelector(".strip-label b");
    const small = strip.querySelector(".strip-label small");
    if (label) label.textContent = view.title;
    if (small) small.textContent = view.small;
  }
  const head = $("#view-review .section-head");
  if (head) {
    const title = head.querySelector("h3");
    const hint = head.querySelector("p");
    if (title) title.textContent = view.title;
    if (hint) hint.textContent = view.hint;
  }
  if (state.activeView === "review") {
    $("#workspaceTitle").textContent = view.title;
    $("#workspaceHint").textContent = view.hint;
  }
}

function renderPersonalMemoryUnavailable(reason) {
  return `
    <div class="empty-state unavailable-state">
      <b>个人记忆不可用</b>
      <span>${escapeHtml(reason)}</span>
      <p>这里用于联动主动陪伴插件，展示 Bot 自身的每日生活日程、当前状态、日程细化片段和由陪伴插件写入的个人记忆。</p>
    </div>
  `;
}

function renderPersonalMemoryWorkspace(snapshot, status) {
  return `
    <section class="personal-memory-workspace">
      ${renderCompanionSchedulePanel(snapshot, status)}
    </section>
  `;
}

function renderCompanionSchedulePanel(snapshot, status) {
  const plan = snapshot.plan || {};
  const items = Array.isArray(plan.items) ? plan.items : [];
  const visualItems = items.map((item, index) => ({ item, index })).reverse();
  const activeIndex = activeScheduleIndex(items);
  const active = selectedScheduleItem(items, activeIndex);
  return `
    <section class="personal-zone companion-overview">
      <div class="personal-zone-head">
        <h4>时间胶片</h4>
        <span>${escapeHtml(snapshot.bot_name || "Bot")} · ${escapeHtml(plan.date || status.selected_date || "-")}</span>
      </div>
      <div class="schedule-summary" data-schedule-summary>
        ${renderScheduleSummary(active.item, items, active.index)}
      </div>
      <div class="schedule-film" data-schedule-film>
        <div class="schedule-film-track" data-schedule-track>
        ${visualItems.length ? visualItems.map(({ item, index }) => {
          const itemIndex = scheduleIndex(item, index);
          return `
          <button class="schedule-frame${itemIndex === activeIndex ? " is-active" : ""}" data-schedule-index="${escapeHtml(itemIndex)}" type="button">
            <span>${escapeHtml(scheduleRange(items, index))}</span>
          </button>
        `}).join("") : `<div class="empty-state">这一天没有日程。</div>`}
        </div>
        <div class="schedule-marker" aria-hidden="true"></div>
      </div>
    </section>
  `;
}

function updateScheduleSummary(target, snapshot, options = {}) {
  const summary = target.querySelector("[data-schedule-summary]");
  if (!summary) return;
  const plan = snapshot.plan || {};
  const items = Array.isArray(plan.items) ? plan.items : [];
  const active = selectedScheduleItem(items, activeScheduleIndex(items));
  const render = () => {
    summary.innerHTML = renderScheduleSummary(active.item, items, active.index);
  };
  if (options.animate) {
    swapPanelContent(summary, render);
  } else {
    render();
  }
}

function swapPanelContent(element, render) {
  if (!element) return;
  window.clearTimeout(element._swapTimer);
  window.clearTimeout(element._swapDoneTimer);
  element.classList.add("is-switching");
  element._swapTimer = window.setTimeout(() => {
    render();
    element.classList.add("is-switching");
    element.offsetHeight;
    requestAnimationFrame(() => {
      element.classList.remove("is-switching");
      element.classList.add("is-switch-settling");
      element._swapDoneTimer = window.setTimeout(() => {
        element.classList.remove("is-switch-settling");
      }, 220);
    });
  }, 120);
}

function selectedScheduleItem(items, selectedIndex) {
  const index = items.findIndex((item, fallback) => scheduleIndex(item, fallback) === String(selectedIndex));
  return {
    item: index >= 0 ? items[index] : null,
    index,
  };
}

function renderScheduleSummary(item, items, index) {
  if (!item) {
    return `<b>未选择时段</b><span>拖动胶片选择一段日程。</span>`;
  }
  const range = index >= 0 ? scheduleRange(items, index) : (item.time || "");
  const meta = [item.mood, item.message_seed].filter(Boolean).join(" · ");
  return `
    <b>${escapeHtml(range)}</b>
    <span>${escapeHtml(item.activity || "未命名日程")}</span>
    ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
  `;
}

function scheduleIndex(item, fallback) {
  const value = item?.index;
  if (value !== undefined && value !== null && String(value) !== "") return String(value);
  return String(fallback);
}

function activeScheduleIndex(items) {
  if (!items.length) return "";
  const available = items.map((item, index) => scheduleIndex(item, index));
  if (available.includes(String(state.selectedScheduleIndex))) return String(state.selectedScheduleIndex);
  state.selectedScheduleIndex = available[0] || "";
  return state.selectedScheduleIndex;
}

function detailForSchedule(details, item, selectedIndex) {
  if (!item || !selectedIndex) return null;
  return details.find((detail) => String(detail.index) === String(selectedIndex))
    || details.find((detail) => String(detail.key || "").includes(`:${selectedIndex}:`))
    || details.find((detail) => item.time && String(detail.key || "").includes(`:${item.time}`))
    || null;
}

function scheduleRange(items, index) {
  const item = items[index] || {};
  const start = item.time || "--:--";
  const next = items[index + 1]?.time || "";
  return next ? `${start} - ${next}` : `${start} 后`;
}

function showPersonalScheduleDetail(snapshot, status, options = {}) {
  if (state.activeView !== "review") return;
  const plan = snapshot.plan || {};
  const items = Array.isArray(plan.items) ? plan.items : [];
  const details = Array.isArray(snapshot.details) ? snapshot.details : [];
  const selectedIndex = activeScheduleIndex(items);
  const selectedItem = items.find((item, index) => scheduleIndex(item, index) === selectedIndex) || null;
  const selectedDetail = detailForSchedule(details, selectedItem, selectedIndex);
  const drawer = $("#detailDrawer");
  const render = () => {
    drawer.className = selectedItem ? "detail-drawer" : "detail-drawer empty";
    drawer.innerHTML = `<div class="personal-detail-content">${renderSelectedDetail(selectedItem, selectedDetail, items)}</div>`;
  };
  if (options.animate) {
    swapPanelContent(drawer, render);
  } else {
    render();
  }
}

function renderSelectedDetail(item, detail, items) {
  if (!item) {
    return `
      <div class="detail-empty">
        <b>选择日程段</b>
        <span>点击上方日程表里的时间段，在这里查看对应细化。</span>
      </div>
    `;
  }
  const index = items.findIndex((candidate, fallback) => scheduleIndex(candidate, fallback) === String(state.selectedScheduleIndex));
  const range = index >= 0 ? scheduleRange(items, index) : (item.time || "");
  const detailTime = detail?.time ? detail.time : "";
  if (!detail) {
    return `
      <div class="empty-state">这个时间段还没有细化。</div>
    `;
  }
  return `
    <article class="selected-detail">
      ${detailTime ? `<span class="detail-time">${escapeHtml(detailTime)}</span>` : ""}
      ${detail.summary ? `<b class="detail-summary">${escapeHtml(detail.summary)}</b>` : ""}
      ${renderDetailLines(detail)}
    </article>
  `;
}

function renderDetailLines(item) {
  const lines = [
    ...(item.today_events || []),
    ...(item.proactive_events || []),
    ...(item.state_variables || []),
  ].slice(0, 4);
  if (!lines.length) return "";
  return `<ul class="detail-lines">${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`;
}

function applyMicroscopeView() {
  const active = activeSecondaryNav("microscope");
  const box = $("#view-microscope .microscope-box");
  const result = $("#searchResult");
  if (!box || !result) return;
  box.classList.toggle("hidden", active !== "query");
  result.dataset.microscopeSection = active;
  if (active !== "query" && !result.innerHTML.trim()) {
    result.innerHTML = `<div class="empty-state">先在“召回测试”里运行一次检索。</div>`;
  }
}

async function runSearch() {
  const query = $("#searchQuery").value.trim();
  if (!query) {
    $("#searchResult").innerHTML = `<div class="empty-state">先输入一句要测试的话。</div>`;
    return;
  }
  $("#searchResult").innerHTML = loadingState("正在模拟召回...");
  const data = await apiPost("/search", contextPayload(query));
  const results = data.results || [];
  const blocked = data.blocked || [];
  $("#searchResult").innerHTML = `
    <section class="result-section film-panel" data-result-section="hits">
      <div class="personal-zone-head">
        <h4>命中记忆</h4>
        <span>${escapeHtml(results.length)} Hits</span>
      </div>
      ${results.length ? results.map((item) => `
        <article class="search-card" data-memory-id="${escapeHtml(item.id)}">
          <span class="item-title">${escapeHtml(item.content)}</span>
          <div class="item-meta">score ${escapeHtml(item.score)} · ${escapeHtml(item.reason || "")}</div>
          <div class="badges">
            <span class="badge teal">${escapeHtml(item.memory_type)}</span>
            <span class="badge blue">${escapeHtml(item.visibility)}</span>
          </div>
        </article>
      `).join("") : `<div class="empty-state">没有命中可读取记忆。</div>`}
    </section>
    <section class="result-section film-panel" data-result-section="blocked">
      <div class="personal-zone-head">
        <h4>过滤原因</h4>
        <span>${escapeHtml(blocked.length)} Blocked</span>
      </div>
      ${blocked.length ? blocked.map((item) => `
        <article class="search-card">
          <span class="item-title">${escapeHtml(item.memory_id || item.id || "blocked")}</span>
          <div class="item-meta">${escapeHtml(item.reason || JSON.stringify(item))}</div>
        </article>
      `).join("") : `<div class="empty-state">没有过滤记录。</div>`}
    </section>
  `;
  $$("#searchResult [data-memory-id]").forEach((card) => {
    card.addEventListener("click", () => showMemory(card.dataset.memoryId));
  });
  applyMicroscopeView();
}

async function loadArchive() {
  $("#selfMemoryList").innerHTML = loadingState("正在读取检索配置...");
  const config = await apiGet("/context/config");
  $("#selfMemoryList").innerHTML = renderArchiveConfig(config);
  bindRetrievalConfigForm($("#selfMemoryList"));
  setArchiveSection(activeSecondaryNav("archive"));
}

function setArchiveSection(section) {
  $$("#view-archive [data-archive-section]").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.archiveSection === section);
  });
  const result = $("#importResult");
  if (result) {
    result.hidden = true;
    result.innerHTML = "";
  }
}

function renderArchiveConfig(config) {
  const retrieval = config.retrieval || {};
  const rerankOptions = Array.isArray(config.rerank_provider_options) ? config.rerank_provider_options : [];
  const embeddingOptions = Array.isArray(config.embedding_provider_options) ? config.embedding_provider_options : [];
  return renderRetrievalConfigForm(retrieval, rerankOptions, embeddingOptions);
}

function renderRetrievalConfigForm(retrieval = {}, rerankOptions = [], embeddingOptions = []) {
  const currentProvider = retrieval.rerank_provider_id || "";
  const options = Array.isArray(rerankOptions) ? [...rerankOptions] : [];
  const hasProvider = options.some((item) => item.id);
  const currentEmbeddingProvider = retrieval.embedding_provider_id || "";
  const embeddingProviderOptions = Array.isArray(embeddingOptions) ? [...embeddingOptions] : [];
  const hasEmbeddingProvider = embeddingProviderOptions.some((item) => item.id);
  const mode = retrieval.mode || "auto";
  if (currentProvider && !options.some((item) => item.id === currentProvider)) {
    options.push({ id: currentProvider, label: `${currentProvider}（当前配置）` });
  }
  if (currentEmbeddingProvider && !embeddingProviderOptions.some((item) => item.id === currentEmbeddingProvider)) {
    embeddingProviderOptions.push({ id: currentEmbeddingProvider, label: `${currentEmbeddingProvider}（当前配置）` });
  }
  return `
    <form id="retrievalConfigForm" class="context-form retrieval-config-form" autocomplete="off">
      <div class="retrieval-explain">
        <div>
          <b>检索模型的作用</b>
          <p>嵌入负责补充语义候选，Rerank 负责二阶段重排；两者都不保存记忆，也不突破权限。流程是：权限/黑白名单预过滤 -> 本地粗排与向量候选 -> 可选 Rerank -> 取 TopK 返回。</p>
        </div>
        <div class="retrieval-flow">
          <span>可见记忆</span>
          <span>本地/向量候选</span>
          <span>Rerank</span>
          <span>TopK 读取</span>
        </div>
        <div class="context-summary-strip">
          <span>当前模式：${escapeHtml(retrievalModeLabel(mode))}</span>
          <span>Rerank：${escapeHtml(currentProvider || (hasProvider ? "自动探测" : "未检测到"))}</span>
          <span>Embedding：${escapeHtml(retrieval.embedding_enabled ? (currentEmbeddingProvider || (hasEmbeddingProvider ? "自动探测" : "未检测到")) : "未启用")}</span>
          <span>日志看 retrieval_path 是否为 rerank</span>
        </div>
      </div>
      ${contextField({
        label: "检索实现路径",
        hint: "推荐 auto。没有候选、没有 provider、超时或报错时都会回退 basic；这时重排模型不会实际参与。",
        control: `
          <select name="mode">
            <option value="auto"${(retrieval.mode || "auto") === "auto" ? " selected" : ""}>自动选择</option>
            <option value="rerank"${retrieval.mode === "rerank" ? " selected" : ""}>强制重排</option>
            <option value="basic"${retrieval.mode === "basic" ? " selected" : ""}>本地检索</option>
          </select>
        `,
      })}
      ${contextField({
        label: "Rerank Provider",
        hint: "只列出真正具备 rerank() 能力的提供商。留空时 auto 会自动扫描；官方配置页若不能选择 rerank，可在这里填 Provider ID。",
        control: `
          <div class="provider-inline retrieval-provider-picker">
            <select name="rerank_provider_select">
              ${options.map((option) => `<option value="${escapeHtml(option.id || "")}"${(option.id || "") === currentProvider ? " selected" : ""}>${escapeHtml(option.label || option.id || "自动探测 / 不指定")}</option>`).join("")}
            </select>
            <input name="rerank_provider_id" type="text" value="${escapeHtml(currentProvider)}" placeholder="例如 vllm_rerank 或 siliconflow_rerank" />
          </div>
        `,
        wide: true,
      })}
      ${contextField({
        label: "启用嵌入召回",
        hint: "开启后会为记忆建立向量索引，并在本地关键词候选之外补充语义相近记忆；没有 Embedding Provider 或调用失败时会自动回退。",
        control: contextSwitch("embedding_enabled", Boolean(retrieval.embedding_enabled)),
      })}
      ${contextField({
        label: "Embedding Provider",
        hint: "参考 Rerank Provider 的选择方式。下拉只尽量列出具备 embedding 能力的提供商；留空时自动扫描第一个可用 Provider。",
        control: `
          <div class="provider-inline retrieval-provider-picker">
            <select name="embedding_provider_select">
              ${embeddingProviderOptions.map((option) => `<option value="${escapeHtml(option.id || "")}"${(option.id || "") === currentEmbeddingProvider ? " selected" : ""}>${escapeHtml(option.label || option.id || "自动探测 / 不指定")}</option>`).join("")}
            </select>
            <input name="embedding_provider_id" type="text" value="${escapeHtml(currentEmbeddingProvider)}" placeholder="例如 openai_embedding 或 siliconflow_embedding" />
          </div>
        `,
        wide: true,
      })}
      <details class="context-advanced retrieval-advanced">
        <summary>高级重排参数</summary>
        <div class="context-advanced-note">候选倍率和上限只影响送给 rerank 的候选池大小，不改变最终读取 TopK；TopK 仍沿用记忆注入配置中的条数。</div>
        ${contextField({
          label: "重排候选倍率",
          hint: "实际读取 TopK 的多少倍进入重排。建议 3-5。",
          control: `<input name="rerank_candidate_multiplier" type="number" min="1" step="1" value="${escapeHtml(retrieval.rerank_candidate_multiplier ?? 4)}" />`,
        })}
        ${contextField({
          label: "重排候选上限",
          hint: "每轮最多送入重排模型的候选数量。建议 24-40。",
          control: `<input name="rerank_candidate_limit" type="number" min="1" step="1" value="${escapeHtml(retrieval.rerank_candidate_limit ?? 32)}" />`,
        })}
        ${contextField({
          label: "重排超时毫秒",
          hint: "超时会回退本地检索。建议 1200-2000。",
          control: `<input name="rerank_timeout_ms" type="number" min="0" step="100" value="${escapeHtml(retrieval.rerank_timeout_ms ?? 1200)}" />`,
        })}
      </details>
      <details class="context-advanced retrieval-advanced">
        <summary>高级嵌入参数</summary>
        <div class="context-advanced-note">嵌入只负责补充候选和软加分，最终仍会经过可见性过滤、本地排序和可选重排。</div>
        ${contextField({
          label: "向量候选扫描上限",
          hint: "每轮最多扫描多少条已有向量。记忆库较大时可降低；想扩大旧记忆覆盖面可提高。",
          control: `<input name="embedding_candidate_limit" type="number" min="1" step="50" value="${escapeHtml(retrieval.embedding_candidate_limit ?? 1200)}" />`,
        })}
        ${contextField({
          label: "向量合并数量",
          hint: "相似度最高的多少条进入候选池。建议 24-48。",
          control: `<input name="embedding_top_k" type="number" min="1" step="1" value="${escapeHtml(retrieval.embedding_top_k ?? 32)}" />`,
        })}
        ${contextField({
          label: "相似度阈值",
          hint: "建议 0.30-0.42；过高会漏召回，过低会引入无关记忆。",
          control: `<input name="embedding_score_threshold" type="number" min="0" max="1" step="0.01" value="${escapeHtml(retrieval.embedding_score_threshold ?? 0.34)}" />`,
        })}
        ${contextField({
          label: "向量评分权重",
          hint: "向量相似度在本地评分中的软加分。建议 0.45-0.75。",
          control: `<input name="embedding_weight" type="number" min="0" max="2" step="0.05" value="${escapeHtml(retrieval.embedding_weight ?? 0.55)}" />`,
        })}
        ${contextField({
          label: "嵌入超时毫秒",
          hint: "查询向量或记忆向量生成超时后会回退/跳过。0 表示不限制。",
          control: `<input name="embedding_timeout_ms" type="number" min="0" step="100" value="${escapeHtml(retrieval.embedding_timeout_ms ?? 1500)}" />`,
        })}
        ${contextField({
          label: "单条记忆字符上限",
          hint: "送入 Embedding Provider 的单条记忆文本长度上限。",
          control: `<input name="embedding_max_text_chars" type="number" min="200" step="100" value="${escapeHtml(retrieval.embedding_max_text_chars ?? 1200)}" />`,
        })}
        ${contextField({
          label: "后台补齐旧记忆向量",
          hint: "开启后检索时会小批量补齐旧记忆向量索引，不阻塞当前回复。",
          control: contextSwitch("embedding_backfill_enabled", retrieval.embedding_backfill_enabled !== false),
        })}
        ${contextField({
          label: "补索引批量",
          hint: "每次后台最多补齐多少条旧记忆向量。",
          control: `<input name="embedding_backfill_batch_size" type="number" min="1" step="1" value="${escapeHtml(retrieval.embedding_backfill_batch_size ?? 50)}" />`,
        })}
      </details>
      <div class="context-form-actions">
        <span>保存后下一次检索或工具读取生效；调试日志会显示 retrieval_path。</span>
        <button id="saveRetrievalConfigBtn" type="submit">保存检索配置</button>
      </div>
    </form>
  `;
}

function bindRetrievalConfigForm(root) {
  const form = root.querySelector("#retrievalConfigForm");
  if (!form) return;
  const select = form.querySelector("[name='rerank_provider_select']");
  const input = form.querySelector("[name='rerank_provider_id']");
  bindProviderPicker(select, input);
  bindProviderPicker(
    form.querySelector("[name='embedding_provider_select']"),
    form.querySelector("[name='embedding_provider_id']"),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    withButton(form.querySelector("#saveRetrievalConfigBtn"), "保存中", () => saveRetrievalConfig(form));
  });
}

function bindProviderPicker(select, input) {
  if (!select || !input) return;
  select.addEventListener("change", () => {
    input.value = select.value || "";
  });
  input.addEventListener("input", () => {
    const matched = Array.from(select.options).some((option) => option.value === input.value);
    if (matched) select.value = input.value;
  });
}

async function saveRetrievalConfig(form) {
  const data = new FormData(form);
  const num = (name, fallback = 0) => {
    const value = Number(data.get(name));
    return Number.isFinite(value) ? value : fallback;
  };
  const payload = {
    mode: String(data.get("mode") || "auto"),
    rerank_provider_id: String(data.get("rerank_provider_id") || ""),
    rerank_candidate_multiplier: Math.max(1, Math.round(num("rerank_candidate_multiplier", 4))),
    rerank_candidate_limit: Math.max(1, Math.round(num("rerank_candidate_limit", 32))),
    rerank_timeout_ms: Math.max(0, Math.round(num("rerank_timeout_ms", 1200))),
    embedding_enabled: data.get("embedding_enabled") === "on",
    embedding_provider_id: String(data.get("embedding_provider_id") || ""),
    embedding_candidate_limit: Math.max(1, Math.round(num("embedding_candidate_limit", 1200))),
    embedding_top_k: Math.max(1, Math.round(num("embedding_top_k", 32))),
    embedding_score_threshold: Math.min(1, Math.max(0, num("embedding_score_threshold", 0.34))),
    embedding_weight: Math.min(2, Math.max(0, num("embedding_weight", 0.55))),
    embedding_timeout_ms: Math.max(0, Math.round(num("embedding_timeout_ms", 1500))),
    embedding_max_text_chars: Math.max(200, Math.round(num("embedding_max_text_chars", 1200))),
    embedding_backfill_enabled: data.get("embedding_backfill_enabled") === "on",
    embedding_backfill_batch_size: Math.max(1, Math.round(num("embedding_backfill_batch_size", 50))),
  };
  await apiPost("/retrieval/config/update", payload);
  showToast("检索配置已保存");
  await loadArchive();
}

async function openBucketPermissions(bucketId) {
  const bucket = state.buckets.find((item) => item.id === bucketId);
  if (!isWindowBucket(bucket)) {
    showToast("只有私聊/群聊卡片可以配置权限", "error");
    return;
  }
  $("#detailDrawer").className = "detail-drawer";
  $("#detailDrawer").innerHTML = loadingState("正在读取权限...");
  try {
    if (state.activeBucketId !== bucket.id) {
      state.activeBucketId = bucket.id;
      const scope = currentRailScope();
      if (scope) {
        renderScopedBucketRail(scope);
      } else {
        renderBuckets();
      }
      await loadActiveView();
    }
    await showBucketPermissions(bucket.id);
  } catch (error) {
    $("#detailDrawer").innerHTML = panelError(error, "重新读取权限");
    const retry = $("#detailDrawer [data-retry-active]");
    if (retry) retry.addEventListener("click", () => openBucketPermissions(bucketId));
    showToast(error.message || "权限读取失败", "error");
  }
}

async function showBucketPermissions(bucketId, targetSelector = "#detailDrawer") {
  const bucket = state.buckets.find((item) => item.id === bucketId);
  if (!isWindowBucket(bucket)) return;
  const detail = $(targetSelector);
  if (!detail) return;
  const inDrawer = targetSelector === "#detailDrawer";
  if (inDrawer) {
    detail.className = "detail-drawer permission-drawer";
  } else {
    detail.className = "row-list permission-page";
  }
  detail.innerHTML = loadingState("正在读取权限...");
  const params = new URLSearchParams({ scope: bucket.scope, id: bucket.target_id });
  const data = await apiGet(`/acl?${params.toString()}`);
  detail.classList.remove("empty");
  detail.innerHTML = renderBucketPermissionPanel(bucket, data);
  bindBucketPermissionPanel(bucket, targetSelector);
}

function renderBucketPermissionPanel(bucket, data) {
  const canRead = data.can_read || [];
  const canBeReadBy = data.can_be_read_by || [];
  const policy = data.policy || {};
  const readMode = normalizeAclMode(policy.read_mode);
  const shareMode = normalizeAclMode(policy.share_mode);
  const targets = permissionTargets(bucket);
  return `
    <div class="permission-drawer-head">
      <h3>${escapeHtml(bucket.label)} · 记忆权限</h3>
      ${isScopedSettingsMode() ? `<button class="mini" type="button" data-scope-mode-toggle="${escapeHtml(state.activeView)}">返回记忆</button>` : ""}
    </div>
    <div class="badges">
      <span class="badge blue">${escapeHtml(windowKindLabel(bucket.scope))}</span>
      <span class="badge teal">${escapeHtml(bucket.target_id)}</span>
      <span class="badge gold">读取 ${escapeHtml(aclModeLabel(readMode))}</span>
      <span class="badge violet">被读 ${escapeHtml(aclModeLabel(shareMode))}</span>
    </div>
    <div class="privacy-note ${bucket.scope === "group" ? "neutral" : ""}">${escapeHtml(scopedSettingsHint(bucket.scope))}</div>
    ${bucket.scope === "private" ? `<div class="privacy-note">隐私保护：私聊记忆流向群聊必须显式加入白名单，黑名单默认放行不会自动开放给群聊。</div>` : ""}
    <section class="permission-panel">
      ${renderAclSection("can_read", "当前窗口可读", canRead, targets, readMode)}
      ${renderAclSection("can_be_read_by", "可读取当前窗口", canBeReadBy, targets, shareMode)}
    </section>
  `;
}

function normalizeAclMode(value) {
  return value === "blacklist" ? "blacklist" : "whitelist";
}

function aclModeLabel(mode) {
  return normalizeAclMode(mode) === "blacklist" ? "黑名单" : "白名单";
}

function aclEffectForMode(mode) {
  return normalizeAclMode(mode) === "blacklist" ? "deny" : "allow";
}

function aclPolicyField(sectionMode) {
  return sectionMode === "can_read" ? "read_mode" : "share_mode";
}

function aclSectionNote(sectionMode, listMode) {
  if (sectionMode === "can_read") {
    return listMode === "blacklist" ? "名单内不可读" : "只读名单内";
  }
  return listMode === "blacklist" ? "名单内不可读当前" : "名单内可读当前";
}

function renderAclModeSwitch(sectionMode, listMode) {
  const field = aclPolicyField(sectionMode);
  return `
    <div class="permission-mode" role="group" aria-label="${escapeHtml(aclModeLabel(listMode))}">
      <button class="${listMode === "whitelist" ? "is-active" : ""}" data-acl-policy="${escapeHtml(field)}" data-acl-policy-value="whitelist" type="button">白名单</button>
      <button class="${listMode === "blacklist" ? "is-active" : ""}" data-acl-policy="${escapeHtml(field)}" data-acl-policy-value="blacklist" type="button">黑名单</button>
    </div>
  `;
}

function renderAclSection(mode, title, rules, targets, listMode = "whitelist") {
  const normalizedMode = normalizeAclMode(listMode);
  const effect = aclEffectForMode(normalizedMode);
  const visibleRules = rules.filter((rule) => (rule.effect || "allow") === effect);
  const disabled = targets.length ? "" : " disabled";
  const rows = visibleRules.length ? visibleRules.map((rule) => renderAclRuleRow(rule, mode)).join("") : `
    <div class="empty-state compact">${normalizedMode === "blacklist" ? "暂无阻止项。" : "暂无允许项。"}</div>
  `;
  return `
    <section class="permission-section">
      <div class="personal-zone-head">
        <h4>${escapeHtml(title)}</h4>
        <span>${escapeHtml(aclSectionNote(mode, normalizedMode))}</span>
      </div>
      ${renderAclModeSwitch(mode, normalizedMode)}
      <div class="permission-add">
        <select data-acl-select="${escapeHtml(mode)}"${disabled}>
          ${targets.map((target) => `
            <option value="${escapeHtml(windowOptionValue(target.scope, target.target_id))}">
              ${escapeHtml(windowKindLabel(target.scope))} · ${escapeHtml(target.label)}
            </option>
          `).join("")}
        </select>
        <button data-acl-add="${escapeHtml(mode)}" data-acl-effect="${escapeHtml(effect)}" type="button"${disabled}>${normalizedMode === "blacklist" ? "加入黑名单" : "加入白名单"}</button>
      </div>
      <div class="permission-list">${rows}</div>
    </section>
  `;
}

function renderAclRuleRow(rule, mode) {
  const scope = mode === "can_read" ? rule.owner_scope : rule.reader_scope;
  const id = mode === "can_read" ? rule.owner_id : rule.reader_id;
  return `
    <article class="permission-row">
      <div>
        <b>${escapeHtml(windowLabel(scope, id))}</b>
        <small>${escapeHtml(windowKindLabel(scope))} · ${escapeHtml(id)}</small>
      </div>
      <button class="ghost mini" data-acl-delete="${escapeHtml(rule.id)}" type="button">移除</button>
    </article>
  `;
}

function bindBucketPermissionPanel(bucket, rootSelector = "#detailDrawer") {
  bindScopedModeToggleButtons(rootSelector);
  $$(`${rootSelector} [data-acl-add]`).forEach((button) => {
    button.addEventListener("click", () => addBucketAclRule(bucket, button.dataset.aclAdd, button, rootSelector));
  });
  $$(`${rootSelector} [data-acl-delete]`).forEach((button) => {
    button.addEventListener("click", () => deleteBucketAclRule(bucket, button.dataset.aclDelete, button, rootSelector));
  });
  $$(`${rootSelector} [data-acl-policy]`).forEach((button) => {
    button.addEventListener("click", () => updateBucketAclPolicy(bucket, button.dataset.aclPolicy, button.dataset.aclPolicyValue, button, rootSelector));
  });
}

function bindScopedModeToggleButtons(rootSelector = document) {
  const root = typeof rootSelector === "string" ? $(rootSelector) : rootSelector;
  if (!root) return;
  root.querySelectorAll("[data-scope-mode-toggle]").forEach((button) => {
    if (button.dataset.scopeModeBound === "1") return;
    button.dataset.scopeModeBound = "1";
    button.addEventListener("click", () => withBusy("正在切换页面模式...", () => toggleScopedMode(button.dataset.scopeModeToggle)));
  });
}

async function addBucketAclRule(bucket, mode, button, rootSelector = "#detailDrawer") {
  const select = $(`${rootSelector} [data-acl-select="${mode}"]`);
  const target = parseWindowOption(select?.value || "");
  if (!target.scope || !target.id) {
    showToast("没有可添加的目标窗口", "error");
    return;
  }
  const current = { scope: bucket.scope, id: bucket.target_id };
  const payload = mode === "can_read"
    ? { owner_scope: target.scope, owner_id: target.id, reader_scope: current.scope, reader_id: current.id }
    : { owner_scope: current.scope, owner_id: current.id, reader_scope: target.scope, reader_id: target.id };
  await withButton(button, "保存中", async () => {
    await apiPost("/acl/upsert", { ...payload, effect: button.dataset.aclEffect || "allow", enabled: true });
    showToast(button.dataset.aclEffect === "deny" ? "黑名单已更新" : "白名单已更新");
    await showBucketPermissions(bucket.id, rootSelector);
  });
}

async function updateBucketAclPolicy(bucket, field, value, button, rootSelector = "#detailDrawer") {
  const payload = { scope: bucket.scope, id: bucket.target_id };
  payload[field] = value;
  await withButton(button, "切换中", async () => {
    await apiPost("/acl/policy", payload);
    showToast("名单模式已更新");
    await showBucketPermissions(bucket.id, rootSelector);
  });
}

async function deleteBucketAclRule(bucket, ruleId, button, rootSelector = "#detailDrawer") {
  await withButton(button, "移除中", async () => {
    await apiPost("/acl/delete", { id: ruleId });
    showToast("权限已移除");
    await showBucketPermissions(bucket.id, rootSelector);
  });
}

async function showMemory(id) {
  state.activeMemoryId = id;
  $("#detailDrawer").className = "detail-drawer";
  $("#detailDrawer").innerHTML = loadingState("正在展开详情...");
  let memory;
  try {
    const data = await apiGet(`/memory?id=${encodeURIComponent(id)}`);
    memory = data.memory;
  } catch (error) {
    $("#detailDrawer").innerHTML = panelError(error, "重新读取");
    const retry = $("#detailDrawer [data-retry-active]");
    if (retry) retry.addEventListener("click", () => showMemory(id));
    showToast(error.message || "详情读取失败", "error");
    return;
  }
  $("#detailDrawer").classList.remove("empty");
  $("#detailDrawer").innerHTML = `
    <div class="memory-manage-head">
      <div>
        <h3>${escapeHtml(memory.memory_type)}</h3>
        <p class="item-meta">${escapeHtml(memory.id)} · ${escapeHtml(formatTime(memory.occurred_at || memory.created_at))}</p>
      </div>
      <div class="badges">
        <span class="badge teal">${escapeHtml(memory.visibility)}</span>
        <span class="badge blue">${escapeHtml(memory.reality_level)}</span>
        <span class="badge gold">${escapeHtml(memory.lifecycle)}</span>
      </div>
    </div>
    ${memory.source_plugin === "livingmemory" && isNumericOnlyContent(memory.content) ? `<div class="empty-state error-state"><b>导入内容未修复</b><span>这条记录目前只有旧库编号，请先在维护工具中执行“修复 LivingMemory 内容”。</span></div>` : ""}
    ${renderMemoryStructuredMetadata(memory)}
    <form id="memoryManageForm" class="memory-manage-form" autocomplete="off">
      <label>
        <span>记忆类型</span>
        <input name="memory_type" type="text" value="${escapeHtml(memory.memory_type || "")}" />
      </label>
      <label>
        <span>内容</span>
        <textarea name="content" rows="6">${escapeHtml(memory.content || "")}</textarea>
      </label>
      <label>
        <span>证据</span>
        <textarea name="evidence" rows="4">${escapeHtml(memory.evidence || "")}</textarea>
      </label>
      <div class="memory-manage-grid">
        <label>
          <span>可见性</span>
          <select name="visibility">
            ${memoryOption("private_pair", "私聊可见", memory.visibility)}
            ${memoryOption("group_public", "群聊可见", memory.visibility)}
            ${memoryOption("bot_self", "自我档案", memory.visibility)}
            ${memoryOption("internal", "内部", memory.visibility)}
            ${memoryOption("shareable", "可共享", memory.visibility)}
          </select>
        </label>
        <label>
          <span>生命周期</span>
          <select name="lifecycle">
            ${memoryOption("stable_memory", "稳定记忆", memory.lifecycle)}
            ${memoryOption("raw_event", "原始事件", memory.lifecycle)}
            ${memoryOption("archived", "归档", memory.lifecycle)}
          </select>
        </label>
        <label>
          <span>重要度</span>
          <input name="importance" type="number" min="0" max="1" step="0.01" value="${escapeHtml(memory.importance ?? 0.3)}" />
        </label>
        <label>
          <span>置信度</span>
          <input name="confidence" type="number" min="0" max="1" step="0.01" value="${escapeHtml(memory.confidence ?? 0.5)}" />
        </label>
      </div>
      <div class="memory-manage-actions">
        <button id="saveMemoryBtn" type="submit">保存这条记忆</button>
        <button class="danger" data-delete="1" type="button">删除</button>
      </div>
    </form>
    <details class="memory-raw-detail">
      <summary>归属与元数据</summary>
      <h4>归属</h4>
      <pre>${escapeHtml(JSON.stringify({ subject: memory.subject, object: memory.object, scope: memory.scope, session_id: memory.session_id, group_id: memory.group_id }, null, 2))}</pre>
      <h4>元数据</h4>
      <pre>${escapeHtml(JSON.stringify(memory.metadata || {}, null, 2))}</pre>
    </details>
  `;
  const form = $("#memoryManageForm");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    withButton($("#saveMemoryBtn"), "保存中", () => saveMemoryManagement(id, form));
  });
  $("#detailDrawer [data-delete]").addEventListener("click", async () => {
    if (!confirm("确认删除这条记忆？")) return;
    await apiPost("/memory/delete", { id });
    clearDetail();
    await refreshAll();
  });
}

function renderMemoryStructuredMetadata(memory) {
  const metadata = memory.metadata || {};
  const keyFacts = Array.isArray(metadata.key_facts) ? metadata.key_facts.filter(Boolean) : [];
  const topics = Array.isArray(metadata.topics) ? metadata.topics.filter(Boolean) : [];
  const participants = Array.isArray(metadata.participants) ? metadata.participants.filter(Boolean) : [];
  const canonical = compact(metadata.canonical_summary, "");
  if (!keyFacts.length && !topics.length && !participants.length && !canonical) return "";
  return `
    <section class="memory-structured-panel">
      ${canonical ? `
        <div class="memory-structured-block">
          <b>检索摘要</b>
          <p>${escapeHtml(canonical)}</p>
        </div>
      ` : ""}
      ${keyFacts.length ? `
        <div class="memory-structured-block">
          <b>关键事实</b>
          <ul>${keyFacts.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </div>
      ` : ""}
      ${topics.length || participants.length ? `
        <div class="memory-structured-tags">
          ${topics.map((item) => `<span class="badge blue">${escapeHtml(item)}</span>`).join("")}
          ${participants.map((item) => `<span class="badge teal">${escapeHtml(item)}</span>`).join("")}
        </div>
      ` : ""}
    </section>
  `;
}

function memoryOption(value, label, current) {
  return `<option value="${escapeHtml(value)}"${value === current ? " selected" : ""}>${escapeHtml(label)}</option>`;
}

async function saveMemoryManagement(id, form) {
  const data = new FormData(form);
  const num = (name, fallback) => {
    const value = Number(data.get(name));
    return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : fallback;
  };
  await apiPost("/memory/update", {
    id,
    memory_type: String(data.get("memory_type") || ""),
    content: String(data.get("content") || ""),
    evidence: String(data.get("evidence") || ""),
    importance: num("importance", 0.3),
    confidence: num("confidence", 0.5),
  });
  await apiPost("/memory/visibility", {
    id,
    visibility: String(data.get("visibility") || "internal"),
  });
  await apiPost("/memory/lifecycle", {
    id,
    lifecycle: String(data.get("lifecycle") || "stable_memory"),
  });
  showToast("这条记忆已保存");
  await refreshAll();
  await showMemory(id);
}

function showGenericDetail(title, payload) {
  $("#detailDrawer").classList.remove("empty");
  $("#detailDrawer").innerHTML = `
    <h3>${escapeHtml(title)}</h3>
    <pre>${escapeHtml(JSON.stringify(payload || {}, null, 2))}</pre>
  `;
}

function clearDetail() {
  const settingsMode = isScopedSettingsMode();
  $("#detailDrawer").className = "detail-drawer empty";
  $("#detailDrawer").innerHTML = `
    <div class="detail-empty">
      <b>${settingsMode ? "权限设置模式" : "等待选片"}</b>
      <span>${settingsMode ? "点击左侧具体对象后，在右侧上方面板配置记忆黑名单/白名单。" : "选择左侧对象，再点一条记忆或记录查看详情。"}</span>
    </div>
  `;
}

function livingMemoryPathValue() {
  const activeInput = $("#view-archive .archive-section.is-active .livingmemory-path");
  const fallbackInput = $("#view-archive .livingmemory-path");
  return (activeInput || fallbackInput)?.value.trim() || "";
}

function showArchiveResult(value) {
  const box = $("#importResult");
  if (!box) return;
  box.hidden = false;
  box.innerHTML = `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
}

async function runMaintenance() {
  const data = await apiPost("/maintenance");
  await refreshAll();
  showArchiveResult(data.result);
  showToast("维护已完成");
}

async function repairLivingMemoryContent() {
  const path = livingMemoryPathValue();
  const data = await apiPost("/maintenance/repair_livingmemory_content", { path });
  await refreshAll();
  showArchiveResult(data.result);
  showToast(`已修复 ${data.result?.updated || 0} 条 LivingMemory 内容`);
}

async function clearAllMemoryData() {
  const box = $("#importResult");
  const warning = "这会清空全部记忆、权限规则、关系、时间线、身份、注入日志和导入批次。执行前会自动备份数据库。";
  if (!box) return;
  box.hidden = false;
  box.innerHTML = `
    <div class="clear-confirm">
      <b>确认清空全部记忆</b>
      <p>${escapeHtml(warning)}</p>
      <input id="clearAllConfirmText" type="text" placeholder="输入 清空 后执行" autocomplete="off" />
      <div class="inline-actions">
        <button id="executeClearAllMemoryBtn" class="danger" type="button" disabled>执行清空</button>
        <button id="cancelClearAllMemoryBtn" type="button">取消</button>
      </div>
    </div>
  `;
  const input = $("#clearAllConfirmText");
  const execute = $("#executeClearAllMemoryBtn");
  const cancel = $("#cancelClearAllMemoryBtn");
  const update = () => {
    execute.disabled = input.value.trim() !== "清空";
  };
  input.addEventListener("input", update);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !execute.disabled) {
      withBusy("正在清空全部记忆...", executeClearAllMemoryData);
    }
  });
  execute.addEventListener("click", () => withBusy("正在清空全部记忆...", executeClearAllMemoryData));
  cancel.addEventListener("click", () => {
    box.innerHTML = "";
    showToast("已取消清空操作");
  });
  input.focus();
  showToast("请在下方输入“清空”确认");
}

async function executeClearAllMemoryData() {
  const confirmText = $("#clearAllConfirmText")?.value.trim();
  if (confirmText !== "清空") {
    showToast("请输入“清空”后再执行", "error");
    return;
  }
  const data = await apiPost("/maintenance/clear_all", { confirm: "清空" });
  state.activeBucketId = "all";
  clearDetail();
  await refreshAll();
  showArchiveResult(data.result);
  showToast("全部记忆已清空");
}

async function previewImport() {
  const path = livingMemoryPathValue();
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  const data = await apiGet(`/import/livingmemory/preview?${params.toString()}`);
  showArchiveResult(data.report);
  showToast("预览已生成");
}

async function runImport() {
  const path = livingMemoryPathValue();
  if (!confirm("确认开始导入？导入内容默认会按保守策略处理。")) return;
  const data = await apiPost("/import/livingmemory/run", { path });
  await refreshAll();
  showArchiveResult(data.result);
  showToast("导入已完成");
}

async function refreshAll() {
  await loadCompanionAvailability();
  await loadStats();
  await loadBuckets();
  await loadActiveView();
}

function bindActions() {
  const stage = document.querySelector(".projection-stage");
  $$(".filmstrip").forEach((strip) => {
    const style = strip.getAttribute("style") || "";
    const ang = parseFloat((style.match(/--a:\s*(-?[\d.]+)deg/) || [0,0])[1]);
    const off = parseFloat((style.match(/--off:\s*(-?[\d.]+)px/) || [0,0])[1]);
    const initialAxis = parseFloat((style.match(/--tx:\s*(-?[\d.]+)px/) || [0,0])[1]);
    const a   = ang * Math.PI / 180;
    const label = strip.querySelector(".strip-label");
    let baseAxisOffset = 0;
    let labelBaseShift = 0;
    const measureStrip = () => {
      const r = stage.getBoundingClientRect();
      const s = strip.getBoundingClientRect();
      const cx = s.left + s.width / 2 - r.left - r.width / 2;
      const cy = s.top + s.height / 2 - r.top - r.height / 2;
      baseAxisOffset = cx * Math.cos(a) + cy * Math.sin(a);
      const labelCenter = label ? label.offsetLeft + label.offsetWidth / 2 : strip.clientWidth / 2;
      labelBaseShift = strip.clientWidth / 2 - labelCenter;
    };
    measureStrip();
    const setStripTransform = (offset, axis = initialAxis, duration = ".86s") => {
      strip.style.transition = `transform ${duration} cubic-bezier(.16,.72,.18,1)`;
      strip.style.transform = `rotate(${ang}deg) translateY(${offset}px) translateX(${axis}px)`;
    };
    strip.addEventListener("mouseenter", measureStrip);
    strip.addEventListener("mousemove", (e) => {
      const r = stage.getBoundingClientRect();
      const dx = e.clientX - r.left - r.width/2;
      const dy = e.clientY - r.top  - r.height/2;
      // 仅沿胶卷轴向移动，并把胶卷标签带到鼠标投影位置。
      const raw = dx * Math.cos(a) + dy * Math.sin(a) - baseAxisOffset;
      const axis = initialAxis + raw + labelBaseShift;
      setStripTransform(off, axis, ".86s");
    });
    strip.addEventListener("mouseleave", () => {
      strip.style.transition = "transform .95s cubic-bezier(.18,.88,.22,1)";
      strip.style.transform  = `rotate(${ang}deg) translateY(${off}px) translateX(${initialAxis}px)`;
    });
    strip.addEventListener("click", () => openView(strip.dataset.view));
  });
  $("#backHomeBtn").addEventListener("click", returnHome);
  $("#refreshBtn").addEventListener("click", () => playRailRefreshTransition(refreshAll));
  $("#loadActiveBtn").addEventListener("click", () => withBusy("正在重载当前帧...", loadActiveView));
  $("#clearTargetBtn").addEventListener("click", () => {
    if (state.activeView === "review") {
      selectPersonalDate(todayKey());
    } else if (currentRailScope()) {
      selectBucket("all");
    } else if (secondaryNavItems(state.activeView).length) {
      selectSecondaryNav(defaultSecondaryNav(state.activeView));
    } else {
      selectBucket("all");
    }
  });
  $("#runSearchBtn").addEventListener("click", (event) => withButton(event.currentTarget, "检索中", runSearch));
  $("#maintenanceBtn").addEventListener("click", () => withBusy("正在运行维护...", runMaintenance));
  $("#repairLivingMemoryBtn").addEventListener("click", () => withBusy("正在修复 LivingMemory 内容...", repairLivingMemoryContent));
  $("#clearAllMemoryBtn").addEventListener("click", clearAllMemoryData);
  $("#previewImportBtn").addEventListener("click", () => withBusy("正在扫描 LivingMemory...", previewImport));
  $("#runImportBtn").addEventListener("click", () => withBusy("正在导入 LivingMemory...", runImport));
  bindScopedModeToggleButtons(document);
  $("#globalSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadActiveView();
  });
  $("#bucketList").addEventListener("scroll", requestRailCoverflow, { passive: true });
  $("#bucketList").addEventListener("pointermove", requestRailCoverflow, { passive: true });
  window.addEventListener("resize", requestRailCoverflow);
}

async function init() {
  bindActions();
  playInitialOverviewEntrance();
  await loadConfiguredTheme();
  try {
    await loadCompanionAvailability();
    await loadStats();
    await loadBuckets();
    renderBuckets();
  } catch (error) {
    setMessage(`页面 API 暂不可用：${error.message}`);
    state.buckets = normalizeBuckets([]);
    renderBuckets();
  }
}

init();
