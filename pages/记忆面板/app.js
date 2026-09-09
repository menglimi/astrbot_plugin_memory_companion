/* ============================================================
   记忆面板 · 我会牢牢记住你 · UI v2
   核心层：API / 状态 / 路由 / 主题 / 骨架
   ============================================================ */
"use strict";

// Keep the fallback on AstrBot's authenticated extension API.  The legacy
// /api/plug route is available across dashboard versions and does not depend
// on a dashboard cookie inside mobile WebViews; the page bridge remains the
// preferred transport when the page is embedded by AstrBot.
const API = "/api/plug/astrbot_plugin_memory_companion/page";
const PAGE_ENDPOINT_PREFIX = "page";
const TRANSPARENT_IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";
const THEME_KEY = "memory_companion_theme";
const NAV_KEY = "memory_companion_nav";
const MODE_KEY = "memory_companion_mode";

/* ------------------------------------------------------------
   基础工具
   ------------------------------------------------------------ */
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function compact(value, fallback) {
  const text = String(value ?? "").trim();
  return text || (fallback === undefined ? "" : fallback);
}

function num(value, digits) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "-";
  const fixed = digits === undefined ? parsed.toFixed(2) : parsed.toFixed(digits);
  return fixed.replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

function int(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed) : 0;
}

function fmtInt(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "-";
  return Math.round(parsed).toLocaleString("zh-CN");
}

function fmtTime(value) {
  const text = compact(value);
  if (!text) return "-";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleString("zh-CN", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDate(value) {
  const text = compact(value);
  if (!text) return "-";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function shortId(value) {
  const text = compact(value);
  if (!text) return "-";
  if (text.length <= 16) return text;
  return text.slice(0, 8) + "…" + text.slice(-4);
}

function clip(value, max) {
  const text = compact(value);
  if (!text) return "-";
  return text.length > max ? text.slice(0, max).trimEnd() + "…" : text;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function arraysEqual(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b)) return false;
  if (a.length !== b.length) return false;
  return a.every((item, index) => item === b[index]);
}

/* ------------------------------------------------------------
   图标
   ------------------------------------------------------------ */
const ICON_PATHS = {
  gauge: '<circle cx="8" cy="8" r="6"/><path d="M8 5.4v2.9l2 1.2"/>',
  library: '<path d="M3 3.4h3.4v11H3z"/><path d="M8 3.4h3v11H8z"/><path d="M11.6 4.6l2.8-.7v8.5l-2.8.7z"/>',
  spark: '<path d="M8 1.8l1.6 4.1 4.1 1.6-4.1 1.6L8 13.2 6.4 9.1 2.3 7.5l4.1-1.6z"/><path d="M13.2 2.2v2.2M14.3 3.3h-2.2"/>',
  link: '<path d="M6.6 9.4l2.8-2.8"/><path d="M9.2 4.4l1.1-1.1a2.6 2.6 0 013.7 3.7l-1.1 1.1"/><path d="M6.8 11.6l-1.1 1.1a2.6 2.6 0 01-3.7-3.7l1.1-1.1"/>',
  download: '<path d="M8 2.4v7.2"/><path d="M4.9 6.7L8 9.8l3.1-3.1"/><path d="M2.6 12.2h10.8"/>',
  sliders: '<path d="M3 4.6h10M3 8h10M3 11.4h10"/><circle cx="6.2" cy="4.6" r="1.5"/><circle cx="10.4" cy="8" r="1.5"/><circle cx="5.4" cy="11.4" r="1.5"/>',
  chat: '<path d="M13.4 8.4c0 2.5-2.4 4.5-5.4 4.5-.7 0-1.4-.1-2-.3L2.6 13.6l.9-2.3A4.3 4.3 0 012.6 8.4c0-2.5 2.4-4.5 5.4-4.5s5.4 2 5.4 4.5z"/>',
  users: '<circle cx="6" cy="5.6" r="2.2"/><path d="M2.2 13.2c.3-2 1.9-3.2 3.8-3.2s3.5 1.2 3.8 3.2"/><path d="M11 3.6a2.2 2.2 0 010 4.2M12 10.4c1.5.3 2.5 1.4 2.7 2.8"/>',
  user: '<circle cx="8" cy="5.6" r="2.6"/><path d="M3.2 13.4c.5-2.2 2.4-3.5 4.8-3.5s4.3 1.3 4.8 3.5"/>',
  sun: '<circle cx="8" cy="8" r="2.8"/><path d="M8 1.6v1.6M8 12.8v1.6M1.6 8h1.6M12.8 8h1.6M3.5 3.5l1.1 1.1M11.4 11.4l1.1 1.1M12.5 3.5l-1.1 1.1M4.6 11.4l-1.1 1.1"/>',
  camera: '<path d="M2.4 5.6h2.2l1-1.6h4.8l1 1.6h2.2v7.2H2.4z"/><circle cx="8" cy="9" r="2.2"/>',
  star: '<path d="M8 2.2l1.8 3.9 4.2.5-3.1 2.9.8 4.2L8 11.6l-3.7 2.1.8-4.2L2 6.6l4.2-.5z"/>',
  scope: '<circle cx="8" cy="8" r="5.4"/><circle cx="8" cy="8" r="1.4"/><path d="M8 1.4v2M8 12.6v2M1.4 8h2M12.6 8h2"/>',
  shield: '<path d="M8 2.2l4.6 1.8v4c0 3-1.9 5-4.6 5.8C5.3 12.9 3.4 11 3.4 8v-4z"/><path d="M6.1 8l1.4 1.4 2.6-2.8"/>',
  plug: '<path d="M6 2.4v3.2M10 2.4v3.2"/><path d="M4 5.6h8v2.2a4 4 0 01-8 0z"/><path d="M8 11.8v1.8"/>',
  box: '<path d="M2.6 5.4L8 2.6l5.4 2.8v5.2L8 13.4 2.6 10.6z"/><path d="M2.6 5.4L8 8.2l5.4-2.8M8 8.2v5.2"/>',
  heart: '<path d="M8 13.2S2.6 10 2.6 6.2A2.9 2.9 0 018 4.9a2.9 2.9 0 015.4 1.3c0 3.8-5.4 7-5.4 7z"/>',
  clock: '<circle cx="8" cy="8" r="5.6"/><path d="M8 4.8V8l2.4 1.5"/>',
  tag: '<path d="M8.6 2.6H13v4.4l-6 6-4.4-4.4z"/><circle cx="10.4" cy="5.2" r="0.9"/>',
  db: '<ellipse cx="8" cy="4.2" rx="5" ry="2"/><path d="M3 4.2v7.6c0 1.1 2.2 2 5 2s5-.9 5-2V4.2"/><path d="M3 8c0 1.1 2.2 2 5 2s5-.9 5-2"/>',
};

function icon(name, cls) {
  const path = ICON_PATHS[name] || ICON_PATHS.box;
  return (
    '<span class="' + (cls || "nav-icon") + '" aria-hidden="true">' +
    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" ' +
    'stroke-linecap="round" stroke-linejoin="round">' + path + "</svg></span>"
  );
}

/* ------------------------------------------------------------
   API 层
   ------------------------------------------------------------ */
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

function canUseHttpFallback() {
  return ["http:", "https:"].includes(window.location.protocol) && typeof window.fetch === "function";
}

async function waitForBridge() {
  for (let i = 0; i < 24; i += 1) {
    const bridge = getBridge();
    if (bridge && typeof bridge.apiGet === "function" && typeof bridge.apiPost === "function") return bridge;
    await sleep(80);
  }
  return null;
}

async function apiGet(path) {
  return apiRequest(path, { method: "GET" });
}

async function apiPost(path, payload) {
  return apiRequest(path, { method: "POST", body: payload || {} });
}

async function apiRequest(path, options) {
  const method = (options.method || "GET").toUpperCase();
  const httpAvailable = canUseHttpFallback();
  const bridge = getBridge() || await waitForBridge();
  let data;
  if (bridge && typeof bridge.apiGet === "function" && typeof bridge.apiPost === "function") {
    data = await bridgeRequest(bridge, path, method, options.body);
  } else if (httpAvailable) {
    data = await httpRequest(path, method, options.body);
  } else {
    throw new Error("未检测到 AstrBot 页面桥接，且当前页面不能使用同源 Web API");
  }
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch (error) {
      throw new Error(data);
    }
  }
  if (data && data.status === "error") {
    throw new Error(data.message || data.error || "请求失败");
  }
  if (!data || data.success === false) throw new Error(data && data.error ? data.error : "请求失败");
  return data.data !== undefined ? data.data : data;
}

async function bridgeRequest(bridge, path, method, body) {
  const url = new URL(String(path || ""), "https://astrbot-plugin-page.local/");
  const endpoint = (PAGE_ENDPOINT_PREFIX + "/" + url.pathname.replace(/^\/+/, ""))
    .replace(/\/{2,}/g, "/");
  if (method === "GET") {
    const params = Object.fromEntries(url.searchParams.entries());
    return bridge.apiGet(endpoint, Object.keys(params).length ? params : undefined);
  }
  return bridge.apiPost(endpoint, body || {});
}

async function httpRequest(path, method, body) {
  const response = await fetch(API + path, {
    method,
    cache: "no-store",
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    if (!response.ok) throw new Error("请求失败（HTTP " + response.status + "）");
    throw new Error("页面 API 返回了无效 JSON");
  }
  if (!response.ok || (data && data.success === false)) {
    const error = new Error((data && data.error) || "请求失败（HTTP " + response.status + "）");
    error.status = response.status;
    throw error;
  }
  return data;
}

async function apiTry(fn, fallback) {
  try {
    return await fn();
  } catch (error) {
    return fallback;
  }
}

/* ------------------------------------------------------------
   全局状态
   ------------------------------------------------------------ */
const state = {
  view: "overview",
  group: "overview",
  theme: document.documentElement.dataset.theme || "dark",
  mode: document.documentElement.dataset.initialMode === "cinema" ? "cinema" : "standard",
  ready: false,
  stats: null,
  buckets: [],
  filters: { scope: "", q: "", visibility: "", lifecycle: "", memoryType: "" },
  selected: null,
  starmap: null,
  configSchema: null,
  configModule: "appearance",
  companion: null,
  acl: null,
  assemblyViewer: null,
};

/* ------------------------------------------------------------
   提示 / 忙碌 / 抽屉
   ------------------------------------------------------------ */
let toastTimer = 0;
let assemblyViewerTicket = 0;

function toast(message, tone) {
  const node = $("#toast");
  if (!node) return;
  node.textContent = message;
  node.dataset.tone = tone || "";
  node.classList.add("is-on");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => node.classList.remove("is-on"), 2600);
}

let busyCount = 0;

function busy(on, text) {
  busyCount = Math.max(0, busyCount + (on ? 1 : -1));
  const layer = $("#busyLayer");
  if (!layer) return;
  if (text) $("#busyText").textContent = text;
  layer.classList.toggle("is-on", busyCount > 0);
}

async function withBusy(text, fn) {
  busy(true, text);
  try {
    return await fn();
  } finally {
    busy(false);
  }
}

function openDrawer(title, eyebrow, html) {
  $("#drawerEyebrow").textContent = eyebrow || "记忆";
  $("#drawerTitle").textContent = title || "未选择";
  $("#drawerBody").innerHTML = html;
  $("#drawer").classList.add("is-open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#scrim").hidden = false;
}

function closeDrawer() {
  $("#drawer").classList.remove("is-open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true;
}

function showInlineConfirmation(title, message, confirmLabel) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "inline-confirm-overlay";
    overlay.innerHTML =
      '<section class="inline-confirm" role="dialog" aria-modal="true" aria-labelledby="inlineConfirmTitle">' +
      '<h2 id="inlineConfirmTitle">' + esc(title || "请确认") + "</h2>" +
      '<p>' + esc(message || "确认继续此操作？") + "</p>" +
      '<div class="inline-confirm-actions"><button type="button" data-confirm-cancel>取消</button><button type="button" class="is-danger" data-confirm-ok>' +
      esc(confirmLabel || "继续") + "</button></div></section>";
    const finish = (value) => {
      overlay.remove();
      resolve(value);
    };
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay || event.target.closest("[data-confirm-cancel]")) finish(false);
      if (event.target.closest("[data-confirm-ok]")) finish(true);
    });
    document.body.appendChild(overlay);
    const ok = $("[data-confirm-ok]", overlay);
    if (ok) ok.focus();
  });
}

/* ------------------------------------------------------------
   主题
   ------------------------------------------------------------ */
function applyTheme(theme) {
  state.theme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = state.theme;
  const label = $("#themeToggleLabel");
  if (label) label.textContent = state.theme === "dark" ? "深色" : "浅色";
  try {
    window.localStorage.setItem(THEME_KEY, state.theme);
  } catch (error) {
    /* 忽略存储禁用 */
  }
  window.dispatchEvent(new CustomEvent("mc:theme", { detail: state.theme }));
}

/* ------------------------------------------------------------
   导航结构
   ------------------------------------------------------------ */
const NAV = [
  { id: "overview", label: "总览", icon: "gauge", views: ["overview"] },
  {
    id: "library",
    label: "记忆库",
    icon: "library",
    views: ["navigate", "inspect", "core", "botlife"],
  },
  {
    id: "insight",
    label: "洞察",
    icon: "spark",
    views: ["starmap", "microscope", "synergy"],
  },
  {
    id: "bridge",
    label: "联动",
    icon: "link",
    views: ["companion", "external"],
  },
  {
    id: "import",
    label: "导入",
    icon: "download",
    views: ["chatimport", "migrate"],
  },
  {
    id: "settings",
    label: "设置",
    icon: "sliders",
    views: ["config", "acl"],
  },
];

const VIEWS = {};

function defineView(id, config) {
  VIEWS[id] = Object.assign({ id }, config);
}

function findGroupOf(viewId) {
  for (const group of NAV) {
    if (group.views.includes(viewId)) return group.id;
  }
  return "overview";
}

/* ------------------------------------------------------------
   侧栏渲染
   ------------------------------------------------------------ */
function renderRail() {
  const host = $("#railNav");
  host.innerHTML = NAV.map((group) => {
    const isOpen = group.id === state.group;
    const groupIcon = icon(group.icon);
    const subs = group.views
      .map((viewId) => {
        const view = VIEWS[viewId];
        if (!view || view.hidden) return "";
        const active = state.view === viewId ? " is-active" : "";
        return (
          '<button class="nav-sub' + active + '" type="button" data-view="' + viewId + '">' +
          esc(view.navLabel || view.title) +
          "</button>"
        );
      })
      .join("");
    const hasSubs = subs.trim().length > 0;
    const item =
      '<button class="nav-item' + (group.id === state.group ? " is-active" : "") + '" type="button" ' +
      'data-group="' + group.id + '" data-view="' + group.views[0] + '">' +
      groupIcon +
      '<span class="nav-label">' + esc(group.label) + "</span>" +
      (hasSubs
        ? '<span class="nav-chevron" aria-hidden="true"><svg viewBox="0 0 16 16" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5L10.5 8 6 12.5"/></svg></span>'
        : "") +
      "</button>";
    return (
      '<div class="nav-group' + (isOpen ? " is-open" : "") + '" data-group-wrap="' + group.id + '">' +
      item +
      (hasSubs ? '<div class="nav-subs"><div class="nav-subs-inner">' + subs + "</div></div>" : "") +
      "</div>"
    );
  }).join("");
}

function setRailStatus(kind, text) {
  const node = $("#railStatus");
  if (!node) return;
  node.className = "rail-status" + (kind ? " is-" + kind : "");
  const label = $("#railStatusText");
  if (label) label.textContent = text;
}

/* ------------------------------------------------------------
   路由
   ------------------------------------------------------------ */
let renderToken = 0;

async function go(viewId, options) {
  const view = VIEWS[viewId];
  if (!view || view.hidden) return;
  const opts = options || {};
  state.view = viewId;
  state.group = findGroupOf(viewId);
  try {
    window.localStorage.setItem(NAV_KEY, viewId);
  } catch (error) {
    /* 忽略 */
  }

  const cinemaOverview = state.mode === "cinema" && viewId === "overview";
  $("#viewEyebrow").textContent = cinemaOverview ? "MEMORY COMPANION / ARCHIVE OS" : (view.eyebrow || "Memory Companion");
  $("#viewTitle").textContent = cinemaOverview ? "记忆终端" : view.title;
  $("#viewHint").textContent = cinemaOverview ? "档案阵列、通道筛选与实时记忆状态" : (view.hint || "");
  document.title = (cinemaOverview ? "记忆终端" : view.title) + " · 记忆面板";
  renderRail();

  const token = renderToken + 1;
  renderToken = token;
  const host = $("#content");
  host.innerHTML = '<div class="skeleton" style="height:220px;border-radius:13px"></div>';

  try {
    const payload = await view.load(opts);
    if (token !== renderToken) return;
    host.innerHTML = "";
    const node = document.createElement("div");
    node.innerHTML = view.render(payload, opts);
    host.appendChild(node);
    if (typeof view.mount === "function") view.mount(node, payload, opts);
  } catch (error) {
    if (token !== renderToken) return;
    host.innerHTML =
      '<div class="empty"><b>这个视图没能加载出来</b><span>' + esc(error.message || "未知错误") + "</span></div>";
  }
}

function refresh() {
  go(state.view, { silent: true });
}

/* ------------------------------------------------------------
   组件片段
   ------------------------------------------------------------ */
function kpi(label, value, foot, tone) {
  return (
    '<article class="kpi"' + (tone ? ' data-tone="' + tone + '"' : "") + ">" +
    '<span class="kpi-label">' + esc(label) + "</span>" +
    '<span class="kpi-value">' + esc(value) + "</span>" +
    (foot ? '<span class="kpi-foot">' + esc(foot) + "</span>" : "") +
    "</article>"
  );
}

function badge(text, tone) {
  return '<span class="badge' + (tone ? '" data-tone="' + tone : "") + '">' + esc(text) + "</span>";
}

function emptyState(title, text) {
  return '<div class="empty"><b>' + esc(title) + "</b><span>" + esc(text) + "</span></div>";
}

function card(title, sub, bodyHtml, actionsHtml, extraClass) {
  return (
    '<section class="card ' + (extraClass || "") + '">' +
    '<div class="card-head"><div><h3>' + esc(title) + "</h3>" +
    (sub ? '<div class="card-sub">' + esc(sub) + "</div>" : "") +
    "</div>" +
    (actionsHtml ? '<div class="card-head-actions">' + actionsHtml + "</div>" : "") +
    "</div>" +
    (bodyHtml || "") +
    "</section>"
  );
}

function meter(label, value, max) {
  const pct = clamp(((Number(value) || 0) / (Number(max) || 1)) * 100, 0, 100);
  return (
    '<div class="meter"><div class="meter-head"><span>' + esc(label) + "</span><b>" + esc(num(value)) + "</b></div>" +
    '<div class="meter-track"><div class="meter-fill" style="width:' + pct.toFixed(1) + '%"></div></div></div>'
  );
}

const SCOPE_META = {
  private: { label: "私聊", tone: "private", icon: "chat", desc: "一对一会话中沉淀的记忆" },
  group: { label: "群聊", tone: "group", icon: "users", desc: "群窗口内的公共与成员记忆" },
  profile: { label: "用户档案", tone: "relation", icon: "user", desc: "画像 / 偏好 / 关系的统一档案" },
  personal: { label: "Bot 个人记忆", tone: "personal", icon: "sun", desc: "Bot 自身日程、相册与主观记忆" },
  core: { label: "核心记忆", tone: "gold", icon: "star", desc: "强制注入的稳定事实与规则" },
  external: { label: "外部接口", tone: "external", icon: "plug", desc: "由其他插件经 bridge 写入" },
};

const TYPE_LABEL = {
  profile: "画像",
  user_profile: "画像",
  user_habit: "习惯",
  preference: "偏好",
  user_preference: "偏好",
  relationship: "关系",
  relationship_claim: "关系",
  relationship_phase_summary: "关系阶段",
  fact: "事实",
  stable_fact: "稳定事实",
  user_fact: "用户事实",
  manual_memory: "手动记忆",
  explicit_memory: "明确记忆",
  event: "事件",
  conversation_event: "会话事件",
  important_event: "重要事件",
  timeline_event: "时间线事件",
  state: "稳定状态",
  current_state: "当前状态",
  stable_state: "稳定状态",
  plan: "计划",
  promise: "承诺",
  emotion: "情绪",
  schedule: "日程",
  schedule_fragment: "日程片段",
  daily_digest: "每日摘要",
  action: "行为",
  image_action: "图像行为",
  thought: "想法",
  companion_note: "陪伴想法",
  internal_note: "内部想法",
  summary: "摘要",
  note: "备注",
  rule: "规则",
  boundary: "边界",
};

const VISIBILITY_LABEL = {
  public: "公开",
  private: "私有",
  group_shared: "群内共享",
  bot_self: "仅 Bot 自身",
  restricted: "受限",
};

const LIFECYCLE_LABEL = {
  active: "活跃",
  stable: "稳定",
  fading: "淡出",
  archived: "归档",
  expired: "过期",
};

const VALIDITY_LABEL = {
  current: "当前有效",
  historical: "历史有效",
  unknown: "待确认",
  superseded: "已被取代",
};

const DURABILITY_LABEL = { permanent: "永久", durable: "长期", transient: "短期" };
const SENSITIVITY_LABEL = { low: "低", normal: "普通", high: "高", critical: "敏感" };
const REALITY_LABEL = { real: "真实", fictional: "虚构", uncertain: "不确定" };

const WEIGHT_LABEL = {
  persona_importance: "人格重要性",
  relationship_weight: "关系",
  emotional_weight: "情绪",
  promise_weight: "承诺",
  open_loop_weight: "未完成",
  creative_weight: "创作",
  preference_weight: "偏好",
  self_continuity_weight: "自我连续",
  freshness_weight: "新鲜度",
  scar_weight: "伤痕",
  emotional_debt_weight: "情绪债",
  intimacy_weight: "亲密度",
  vulnerability_weight: "脆弱",
};

function memoryTone(memory) {
  const scope = compact(memory.scope);
  if (scope === "private") return "private";
  if (scope === "group") return "group";
  const type = compact(memory.memory_type);
  if (type === "relationship") return "relation";
  if (type === "preference" || type === "profile") return "relation";
  if (type === "fact" || type === "state") return "fact";
  if (compact(memory.source_plugin) && compact(memory.source_plugin) !== "self") return "external";
  return "";
}

function memoryTitle(memory) {
  const summary = compact(memory.canonical_summary);
  if (summary) return summary;
  const content = compact(memory.content);
  if (!content) return "（空内容）";
  const firstLine = content.split(/\r?\n/)[0].trim();
  return firstLine || content.slice(0, 60);
}

function memoryRow(memory, index) {
  const tone = memoryTone(memory);
  const title = memoryTitle(memory);
  const typeLabel = TYPE_LABEL[compact(memory.memory_type)] || compact(memory.memory_type) || "记忆";
  const scopeLabel = SCOPE_META[compact(memory.scope)] ? SCOPE_META[compact(memory.scope)].label : compact(memory.scope) || "未分类";
  const parts = [typeLabel, scopeLabel];
  if (compact(memory.subject && memory.subject.name)) parts.push(compact(memory.subject.name));
  if (compact(memory.updated_at_local)) parts.push(compact(memory.updated_at_local));
  return (
    '<button class="row" type="button" data-memory="' + esc(memory.id) + '">' +
    '<div class="row-main"><div class="row-title">' + esc(clip(title, 96)) + "</div>" +
    '<div class="row-sub">' + esc(parts.join(" · ")) + "</div></div>" +
    '<div class="row-meta">' +
    (tone ? badge(scopeLabel, tone) : "") +
    badge("重要 " + num(compact(memory.importance, 0)), "accent") +
    "</div></button>"
  );
}

/* ============================================================
   记忆详情抽屉
   ============================================================ */
function memoryDetailHtml(memory) {
  const type = compact(memory.memory_type);
  const scope = compact(memory.scope);
  const tone = memoryTone(memory);
  const weights = memory.persona_weights && typeof memory.persona_weights === "object" ? memory.persona_weights : {};
  const weightKeys = Object.keys(weights).filter((key) => Number.isFinite(Number(weights[key])));
  const tags = Array.isArray(memory.tags) ? memory.tags : [];
  const topics = Array.isArray(memory.topics) ? memory.topics : [];
  const facts = Array.isArray(memory.key_facts) ? memory.key_facts : [];
  const range = memory.time_range && typeof memory.time_range === "object" ? memory.time_range : {};

  const section = (title, body) =>
    body ? '<div class="drawer-section"><h4>' + esc(title) + "</h4>" + body + "</div>" : "";

  const kv = (pairs) =>
    '<dl class="kv">' +
    pairs
      .filter((pair) => compact(pair[1]) !== "")
      .map((pair) => "<dt>" + esc(pair[0]) + "</dt><dd>" + esc(pair[1]) + "</dd>")
      .join("") +
    "</dl>";

  const rows = [
    section(
      "内容",
      '<div class="drawer-content">' + esc(compact(memory.content, "（空）")) + "</div>"
    ),
    section(
      "摘要",
      compact(memory.canonical_summary)
        ? '<div class="drawer-content">' + esc(memory.canonical_summary) + "</div>"
        : ""
    ),
    facts.length
      ? section(
          "关键事实",
          '<div class="row-list">' +
            facts.map((fact) => '<div class="row" style="cursor:default"><div class="row-main"><div class="row-title" style="white-space:normal">' + esc(fact) + "</div></div></div>").join("") +
            "</div>"
        )
      : "",
    section("证据", compact(memory.evidence_preview) ? '<div class="drawer-content">' + esc(memory.evidence_preview) + "</div>" : ""),
    section(
      "分类与来源",
      kv([
        ["记忆 ID", compact(memory.id)],
        ["类型", (TYPE_LABEL[type] || type || "-") + (type ? "（" + type + "）" : "")],
        ["范围", (SCOPE_META[scope] ? SCOPE_META[scope].label : scope || "-")],
        ["会话", compact(memory.session_id)],
        ["群 ID", compact(memory.group_id)],
        ["来源插件", compact(memory.source_plugin) || "本插件"],
        ["导入批次", compact(memory.import_batch_id)],
        ["主体", compact(memory.subject && memory.subject.name) + (compact(memory.subject && memory.subject.role) ? "（" + compact(memory.subject.role) + "）" : "")],
        ["客体", compact(memory.object && memory.object.name)],
        ["人格 ID", compact(memory.persona_id)],
        ["归属 Bot", compact(memory.owner_bot_id)],
      ])
    ),
    section(
      "权重",
      kv([
        ["重要性", num(memory.importance)],
        ["置信度", num(memory.confidence)],
        ["显著性", num(memory.salience)],
        ["强化分", num(memory.reinforcement_score)],
        ["注入次数", String(int(memory.injection_count))],
        ["最近注入", fmtTime(memory.last_injected_at)],
      ]) +
        (weightKeys.length
          ? '<div class="tag-row" style="margin-top:9px">' +
            weightKeys
              .slice(0, 12)
              .map((key) => badge((WEIGHT_LABEL[key] || key) + " " + num(weights[key]), "accent"))
              .join("") +
            "</div>"
          : "")
    ),
    section(
      "生命周期",
      kv([
        ["可见性", (VISIBILITY_LABEL[compact(memory.visibility)] || compact(memory.visibility) || "-")],
        ["可说性", compact(memory.sayability)],
        ["现实层级", (REALITY_LABEL[compact(memory.reality_level)] || compact(memory.reality_level) || "-")],
        ["生命周期", (LIFECYCLE_LABEL[compact(memory.lifecycle)] || compact(memory.lifecycle) || "-")],
        ["时效状态", (VALIDITY_LABEL[compact(memory.validity_status)] || compact(memory.validity_status) || "-")],
        ["有效区间", (compact(memory.valid_from) || "…") + " → " + (compact(memory.valid_to) || "…")],
        ["持久度", (DURABILITY_LABEL[compact(memory.durability)] || compact(memory.durability) || "-")],
        ["敏感度", (SENSITIVITY_LABEL[compact(memory.sensitivity)] || compact(memory.sensitivity) || "-")],
        ["记忆理由", compact(memory.memory_reason)],
        ["提及策略", compact(memory.mention_policy)],
        ["可提及分", memory.mentionability_score === null || memory.mentionability_score === undefined ? "" : num(memory.mentionability_score)],
        ["关系阶段", compact(memory.relationship_phase)],
        ["衰减模式", compact(memory.decay_mode)],
        ["时间范围", compact(range.start_at_local) ? compact(range.start_at_local) + " → " + compact(range.end_at_local) : ""],
      ])
    ),
    section(
      "时间",
      kv([
        ["创建", fmtTime(memory.created_at) + "（" + compact(memory.created_at_local) + "）"],
        ["更新", fmtTime(memory.updated_at) + "（" + compact(memory.updated_at_local) + "）"],
        ["发生", fmtTime(memory.occurred_at) + "（" + compact(memory.occurred_at_local) + "）"],
      ])
    ),
    section(
      "标签与主题",
      (tags.length ? '<div class="tag-row">' + tags.map((tag) => badge(tag, "fact")).join("") + "</div>" : "") +
        (topics.length ? '<div class="tag-row" style="margin-top:6px">' + topics.map((tag) => badge(tag, "gold")).join("") + "</div>" : "")
    ),
    section(
      "去重与合并",
      kv([
        ["规范键", compact(memory.canonical_key)],
        ["合并条数", String(int(memory.merged_count))],
        ["内容指纹", compact(memory.content_fingerprint)],
        ["复核状态", compact(memory.review_status)],
      ])
    ),
  ].join("");

  const actions =
    '<div class="drawer-section"><h4>操作</h4>' +
    '<div class="card is-tight" style="background:var(--surface-2)">' +
    '<div class="config-form">' +
    '<button class="btn is-sm assembly-open-btn" type="button" id="openAssemblyViewerBtn">打开三维结构</button>' +
    '<div class="field"><span>内容</span><textarea id="editContent" rows="5">' + esc(compact(memory.content)) + "</textarea></div>" +
    '<div class="field is-inline"><span>重要性</span><input id="editImportance" type="number" step="0.01" min="0" max="1" value="' + esc(num(memory.importance, 2) === "-" ? "0.5" : num(memory.importance, 2)) + '" /></div>' +
    '<div class="field is-inline"><span>置信度</span><input id="editConfidence" type="number" step="0.01" min="0" max="1" value="' + esc(num(memory.confidence, 2) === "-" ? "0.5" : num(memory.confidence, 2)) + '" /></div>' +
    '<div class="field is-inline"><span>显著性</span><input id="editSalience" type="number" step="0.01" min="0" max="1" value="' + esc(num(memory.salience, 2) === "-" ? "0.5" : num(memory.salience, 2)) + '" /></div>' +
    '<div class="field is-inline"><span>可见性</span><select id="editVisibility">' +
      Object.keys(VISIBILITY_LABEL).map((key) => '<option value="' + key + '"' + (compact(memory.visibility) === key ? " selected" : "") + ">" + VISIBILITY_LABEL[key] + "</option>").join("") +
    "</select></div>" +
    '<div class="field is-inline"><span>生命周期</span><select id="editLifecycle">' +
      Object.keys(LIFECYCLE_LABEL).map((key) => '<option value="' + key + '"' + (compact(memory.lifecycle) === key ? " selected" : "") + ">" + LIFECYCLE_LABEL[key] + "</option>").join("") +
    "</select></div>" +
    '<div class="pill-row" style="justify-content:flex-end;margin-top:4px">' +
      '<button class="btn is-sm is-danger" type="button" id="deleteMemoryBtn">删除</button>' +
      '<button class="btn is-sm is-primary" type="button" id="saveMemoryBtn">保存修改</button>' +
    "</div></div></div></div>";

  return rows + actions;
}

function bindMemoryActions(memoryId) {
  const viewerBtn = $("#openAssemblyViewerBtn");
  if (viewerBtn) viewerBtn.addEventListener("click", () => openAssemblyViewer(memoryId));
  const saveBtn = $("#saveMemoryBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const payload = {
        id: memoryId,
        content: $("#editContent").value,
        importance: Number($("#editImportance").value),
        confidence: Number($("#editConfidence").value),
        salience: Number($("#editSalience").value),
        visibility: $("#editVisibility").value,
        lifecycle: $("#editLifecycle").value,
      };
      await withBusy("正在保存…", async () => {
        await apiPost("/memory/update", payload);
        invalidatePool();
        toast("记忆已更新", "ok");
        closeDrawer();
        refresh();
      });
    });
  }
  const delBtn = $("#deleteMemoryBtn");
  if (delBtn) {
    delBtn.addEventListener("click", async () => {
      const confirmed = await showInlineConfirmation("删除记忆", "确定删除这条记忆？该操作不可撤销。", "删除");
      if (!confirmed) return;
      await withBusy("正在删除…", async () => {
        await apiPost("/memory/delete", { id: memoryId });
        invalidatePool();
        toast("记忆已删除", "ok");
        closeDrawer();
        refresh();
      });
    });
  }
}

async function openMemory(memoryId) {
  await withBusy("正在读取记忆…", async () => {
    const response = await apiGet("/memory?id=" + encodeURIComponent(memoryId));
    // The page API wraps detail responses as { memory: ... }; normalize it
    // here so all detail renderers receive the actual memory object.
    const memory = response && response.memory ? response.memory : response;
    if (!memory || typeof memory !== "object") throw new Error("记忆详情为空");
    openDrawer(clip(memoryTitle(memory), 42), "记忆详情", memoryDetailHtml(memory));
    bindMemoryActions(memoryId);
  });
}

async function openAssemblyViewer(memoryId) {
  const viewer = $("#assemblyViewer");
  const canvas = $("#assemblyViewerCanvas");
  if (!viewer || !canvas) return;
  const ticket = ++assemblyViewerTicket;
  const title = $("#drawerTitle")?.textContent || "档案结构";
  $("#assemblyViewerTitle").textContent = title;
  $("#assemblyViewerFile").textContent = "FILE " + compact(memoryId) + " / INTERNAL DATABASE";
  viewer.hidden = false;
  viewer.setAttribute("aria-hidden", "false");
  document.body.classList.add("assembly-viewer-open");
  $("#assemblyViewerLoading").hidden = false;
  $("#assemblyViewerRetry").hidden = true;
  const mount = () => window.MemoryCinema3D?.mountAssemblyViewer(canvas, {
    onState: (value) => { const node = $("#assemblyViewerState"); if (node) node.textContent = value; },
    onError: () => { const node = $("#assemblyViewerRetry"); if (node) node.hidden = false; },
  });
  let mounted;
  if (window.MemoryCinema3D?.mountAssemblyViewer) mounted = await mount();
  else {
    await Promise.race([
      new Promise((resolve) => window.addEventListener("memory-cinema-ready", resolve, { once: true })),
      sleep(8000),
    ]);
    if (!window.MemoryCinema3D?.mountAssemblyViewer) {
      canvas.innerHTML = '<span class="scene-loading">ASSEMBLY VIEWER / UNAVAILABLE</span>';
      $("#assemblyViewerLoading").hidden = true;
      $("#assemblyViewerRetry").hidden = false;
      return;
    }
    mounted = await mount();
  }
  if (ticket !== assemblyViewerTicket || viewer.hidden) {
    mounted?.dispose?.();
    return;
  }
  state.assemblyViewer = mounted;
  $("#assemblyViewerLoading").hidden = true;
}

function closeAssemblyViewer() {
  assemblyViewerTicket += 1;
  state.assemblyViewer?.dispose?.();
  state.assemblyViewer = null;
  const viewer = $("#assemblyViewer");
  if (viewer) {
    viewer.hidden = true;
    viewer.setAttribute("aria-hidden", "true");
  }
  document.body.classList.remove("assembly-viewer-open");
}

function applyMode(mode) {
  state.mode = mode === "cinema" ? "cinema" : "standard";
  document.documentElement.dataset.uiMode = state.mode;
  const button = $("#modeToggle");
  const label = $("#modeToggleLabel");
  if (button) button.setAttribute("aria-pressed", state.mode === "cinema" ? "true" : "false");
  if (label) label.textContent = state.mode === "cinema" ? "标准模式" : "终端模式";
  try {
    window.localStorage.setItem(MODE_KEY, state.mode);
  } catch (error) {
    /* 忽略存储禁用 */
  }
}

/* ============================================================
   视图：总览
   ============================================================ */
function renderCinemaOverview(data) {
  const stats = data.stats || {};
  const memories = Array.isArray(data.memories) ? data.memories : [];
  const coreRecords = (data.core || []).map((block) => ({
    id: block.id,
    scope: "core",
    memory_type: block.kind || "fact",
    canonical_summary: block.label || "核心记忆",
    content: block.content,
    isCore: true,
  }));
  const buckets = Array.isArray(data.buckets) ? data.buckets : [];
  const records = memories.length ? memories.slice(0, 32).concat(coreRecords.slice(0, 8)) : buckets.slice(0, 24).map((bucket, index) => ({
    id: "bucket-" + index,
    scope: bucket.scope,
    target_id: bucket.target_id,
    canonical_summary: bucket.label || bucket.target_name || bucket.target_id,
    content: bucket.sample_session_id || "此档案窗口暂未提供摘要",
    memory_count: bucket.memory_count,
    updated_at_local: bucket.last_activity_at || bucket.updated_at,
    isBucket: true,
  }));
  const cinemaChannel = (memory) => {
    const scope = compact(memory.scope);
    const type = compact(memory.memory_type);
    const visibility = compact(memory.visibility);
    if (scope === "core") return "core";
    if (scope === "personal" || visibility === "bot_self" || type === "companion_note" || type === "schedule") return "personal";
    if (scope === "profile" || type === "profile" || type === "preference" || type === "user_profile") return "profile";
    if (type === "relationship" || type === "relationship_claim" || type === "relationship_phase_summary") return "relationship";
    return "session";
  };
  const channelLabels = { session: "会话存档", profile: "用户画像", relationship: "关系脉络", core: "核心记忆", personal: "Bot 生活" };
  const recordButtons = records.map((memory, index) => {
    const scope = compact(memory.scope) || "private";
    const channel = cinemaChannel(memory);
    const type = compact(memory.memory_type) || (memory.isBucket ? "archive" : "memory");
    const title = memoryTitle(memory);
    const detail = memory.isBucket
      ? (compact(memory.target_id) || "未命名窗口") + " · " + fmtInt(memory.memory_count) + " 条记录"
      : (TYPE_LABEL[type] || type) + " · " + (SCOPE_META[scope] ? SCOPE_META[scope].label : scope);
    return '<button class="terminal-record" type="button" data-terminal-index="' + index + '" data-memory="' + esc(memory.isBucket || memory.isCore ? "" : memory.id) + '" data-core="' + esc(memory.isCore ? memory.id : "") + '" data-terminal-channel="' + esc(channel) + '" data-terminal-text="' + esc(title + " " + detail) + '">' +
      '<span class="terminal-record-id mono">' + String(index + 1).padStart(3, "0") + '</span><span class="terminal-record-channel">' + esc(channelLabels[channel] || channel) + '</span><strong>' + esc(clip(title, 72)) + '</strong><span class="terminal-record-meta">' + esc(detail) + '</span><i class="terminal-record-signal">●</i></button>';
  }).join("");
  return '<section class="terminal-stage" aria-label="Rhine Lab 记忆终端">' +
    '<div class="terminal-stage-top"><span class="terminal-kicker">RHINE LAB / MEMORY ARCHIVE</span><span class="terminal-session mono">SESSION M-' + String(int(stats.total_memories)).padStart(6, "0") + ' <i></i> AUTHORIZED</span></div>' +
    '<div class="terminal-scene-wrap"><div class="cinema-scene" id="cinemaScene" aria-label="三维档案阵列"><span class="scene-loading">ARCHIVE SCENE / LOADING</span></div><div class="terminal-scanline" aria-hidden="true"></div></div>' +
    '<div class="terminal-callout"><div class="terminal-label">INTERNAL DATABASE <span>/</span> <b id="terminalCategory">记忆档案</b></div><button class="terminal-file-title" id="terminalFileTitle" type="button"><span>FILE NUMBER: </span><strong id="terminalFileId">M-001</strong><span>↗</span></button><div class="terminal-rule"><i></i></div><div class="terminal-summary"><strong id="terminalSelectedTitle">等待档案</strong><span id="terminalSelectedMeta">MEMORY CHANNEL</span></div><button class="terminal-access" id="terminalAccess" type="button">ACCESS MEMORY <span>→</span></button></div>' +
    '<div class="terminal-feed-head"><span class="terminal-label">ARCHIVE STREAM / 记录带</span><label><span>/</span><input id="terminalSearch" type="search" placeholder="检索记录" autocomplete="off" /></label><b id="terminalResultCount">' + fmtInt(records.length) + ' RECORDS</b></div>' +
    '<div class="terminal-feed" id="terminalFeed">' + (recordButtons || emptyState("暂无记录", "连接后会在这里展开记忆流。")) + '</div>' +
    '<div class="terminal-controls"><div class="terminal-counter"><span>ARCHIVE / SELECT</span><strong><b id="terminalSelectedNumber">01</b><i>/</i><b>' + String(Math.max(records.length, 1)).padStart(2, "0") + '</b></strong></div><div class="terminal-arrows"><button type="button" data-terminal-prev aria-label="上一个记忆">↑</button><button type="button" data-terminal-next aria-label="下一个记忆">↓</button></div><div class="terminal-column"><button type="button" data-terminal-column-prev aria-label="上一记忆通道">←</button><span><small>MEMORY CHANNEL</small><b id="terminalChannel">ALL RECORDS</b></span><button type="button" data-terminal-column-next aria-label="下一记忆通道">→</button></div><span class="terminal-hint"><kbd>←</kbd><kbd>→</kbd> 通道 <span>/</span> <kbd>↑</kbd><kbd>↓</kbd> 档案 <span>/</span> <kbd>ENTER</kbd> 读取</span></div>' +
    '<div class="terminal-marquee"><span>ARCHIVE CHANNEL CONNECTED</span><i>●</i><span>PERSONAL CONTEXT READY</span><i>●</i><span>RECALL ENGINE STANDBY</span><i>●</i><span>ARCHIVE CHANNEL CONNECTED</span></div>' +
    '</section>';
}

defineView("overview", {
  title: "总览",
  navLabel: "总览",
  eyebrow: "Overview",
  hint: "记忆库规模、范围分布与联动状态的整体快照",
  async load() {
    const [statsPayload, buckets, core, personal, coord, memories] = await Promise.all([
      apiGet("/stats"),
      apiTry(() => apiGet("/buckets?limit=160"), { buckets: [] }),
      apiTry(() => apiGet("/core-memory"), { blocks: [] }),
      apiTry(() => apiGet("/capabilities/bot-personal"), {}),
      apiTry(() => apiGet("/coordination/status"), { status: {} }),
      apiTry(() => apiGet("/memories?limit=80"), { memories: [] }),
    ]);
    const stats = (statsPayload && statsPayload.stats) || {};
    state.stats = stats;
    state.buckets = Array.isArray(buckets.buckets) ? buckets.buckets : [];
    return { stats, buckets: state.buckets, core: core.blocks || [], personal, coord: coord.status || {}, memories: memories.memories || [] };
  },
  render(data) {
    if (state.mode === "cinema") return renderCinemaOverview(data);
    const stats = data.stats || {};
    const byScope = stats.by_scope || {};
    const storageMb = (int(stats.memory_storage_bytes) / 1048576).toFixed(1);
    const privateCount = int(byScope.private);
    const groupCount = int(byScope.group);

    const kpis = [
      kpi("记忆总量", fmtInt(stats.total_memories), storageMb + " MB 存储", "accent"),
      kpi("私聊记忆", fmtInt(privateCount), "一对一会话", "private"),
      kpi("群聊记忆", fmtInt(groupCount), "群窗口沉淀", "group"),
      kpi("用户档案", fmtInt(stats.identities), "已识别身份", "relation"),
      kpi("核心记忆", fmtInt((data.core || []).length), "强制注入块", "gold"),
      kpi("开放线程", fmtInt(stats.open_threads), "跨窗口续接", "fact"),
    ].join("");

    const entries = [
      ["navigate", "记忆导航", "按私聊 / 群聊 / 个人等范围进入", "scope"],
      ["inspect", "记忆检视", "逐条查看并修正记忆参数", "db"],
      ["starmap", "知识星图", "以星系模型浏览关联记忆", "star"],
      ["microscope", "记忆显微镜", "模拟一次真实召回", "scope"],
      ["botlife", "Bot 日程与相册", "Bot 自身的生活记录", "camera"],
      ["config", "模块配置", "按模块调整检索与注入策略", "sliders"],
    ]
      .map(
        (item) =>
          '<button class="row" type="button" data-goto="' + item[0] + '">' +
          icon(item[3], "scope-icon") +
          '<div class="row-main"><div class="row-title">' + esc(item[1]) + "</div>" +
          '<div class="row-sub">' + esc(item[2]) + "</div></div>" +
          '<div class="row-meta"><span class="badge">进入 ›</span></div></button>'
      )
      .join("");

    const recent = (data.buckets || [])
      .slice()
      .sort((a, b) => String(b.last_activity_at || b.updated_at || "").localeCompare(String(a.last_activity_at || a.updated_at || "")))
      .slice(0, 8)
      .map((bucket) => {
        const scope = compact(bucket.scope);
        const meta = SCOPE_META[scope] || { label: scope || "未分类", tone: "" };
        return (
          '<button class="row" type="button" data-goto="inspect" data-scope="' + esc(scope) + '" data-target="' + esc(compact(bucket.target_id)) + '">' +
          '<div class="row-main"><div class="row-title">' + esc(compact(bucket.label) || compact(bucket.target_name) || compact(bucket.target_id) || "未命名窗口") + "</div>" +
          '<div class="row-sub">' + esc(compact(bucket.sample_session_id) || compact(bucket.target_id) || "-") + "</div></div>" +
          '<div class="row-meta">' + badge(meta.label, meta.tone) + badge(fmtInt(bucket.memory_count) + " 条") + "</div></button>"
        );
      })
      .join("");

    const bridges = [];
    const coordStatus = data.coord || {};
    const bridgeHealth = compact(coordStatus.bridge && coordStatus.bridge.health) || "unknown";
    bridges.push([
      bridgeHealth === "ready" ? "is-ok" : bridgeHealth === "degraded" ? "is-warn" : "is-bad",
      "陪伴插件联动",
      bridgeHealth === "ready" ? "已连接" : compact(coordStatus.bridge && coordStatus.bridge.reason_code) || "未连接",
    ]);
    const personalOk = data.personal && data.personal.available !== false;
    bridges.push([
      personalOk ? "is-ok" : "is-bad",
      "Bot 个人记忆",
      personalOk
        ? (data.personal.daily_plan_enabled ? "日程已启用" : "日程未启用") + " · " + (data.personal.detail_enabled ? "细化已启用" : "细化未启用")
        : compact(data.personal && data.personal.reason) || "不可用",
    ]);
    bridges.push(["is-ok", "外部写入接口", compact(stats.injection_logs) + " 条注入日志"]);

    return (
      '<div class="grid" style="gap:16px">' +
      '<div class="kpi-row">' + kpis + "</div>" +
      '<div class="grid split-2">' +
        card("功能入口", "六个常用工作区", '<div class="row-list">' + entries + "</div>") +
        '<div style="display:grid;gap:16px">' +
          card("最近活跃范围", (data.buckets || []).length + " 个窗口", '<div class="row-list">' + (recent || emptyState("暂无范围", "还没有可展示的记忆窗口。")) + "</div>") +
          card(
            "联动状态",
            "陪伴插件与外部接口",
            '<div class="row-list" style="gap:6px">' +
              bridges.map((item) => '<div class="link-item ' + item[0] + '"><span class="link-dot"></span><b>' + esc(item[1]) + "</b><span>" + esc(item[2]) + "</span></div>").join("") +
              "</div>"
          ) +
        "</div>" +
      "</div>" +
      '<div class="grid g4">' +
        kpi("稳定记忆", fmtInt(stats.stable_memories), "lifecycle=stable_memory", "fact") +
        kpi("时间线事件", fmtInt(stats.timeline_events), "结构化事件流", "group") +
        kpi("关系边", fmtInt(stats.relationships), "实体间关系", "relation") +
        kpi("ACL 规则", fmtInt(stats.acl_rules), "跨窗口读写授权", "gold") +
      "</div>" +
      "</div>"
    );
  },
  mount(node) {
    const sceneRoot = $("#cinemaScene", node);
    if (sceneRoot) {
      const mountScene = () => window.MemoryCinema3D && window.MemoryCinema3D.mountArchiveScene(sceneRoot);
      if (window.MemoryCinema3D) mountScene();
      else window.addEventListener("memory-cinema-ready", mountScene, { once: true });
      if (!window.MemoryCinema3D) sceneRoot.dataset.waitingForScene = "true";
      /* Static module loading is rewritten by AstrBot to include its asset token. */
      window.setTimeout(() => {
        if (!window.MemoryCinema3D && sceneRoot.isConnected) sceneRoot.innerHTML = '<span class="scene-loading">ARCHIVE SCENE / UNAVAILABLE</span>';
      }, 8000);
    }
    const records = $$(".terminal-record", node);
    const search = $("#terminalSearch", node);
    const resultCount = $("#terminalResultCount", node);
    const channels = ["all", "session", "profile", "relationship", "core", "personal"];
    let selectedIndex = 0;
    let channelIndex = 0;
    const select = (index, focus = false) => {
      if (!records.length) return;
      selectedIndex = (index + records.length) % records.length;
      const record = records[selectedIndex];
      records.forEach((item) => item.classList.toggle("is-selected", item === record));
      if (sceneRoot) sceneRoot.dataset.selectedIndex = String(selectedIndex);
      const title = $("#terminalSelectedTitle", node);
      const meta = $("#terminalSelectedMeta", node);
      const id = $("#terminalFileId", node);
      const number = $("#terminalSelectedNumber", node);
      const category = $("#terminalCategory", node);
      const channel = $("#terminalChannel", node);
      if (title) title.textContent = $("strong", record)?.textContent || "等待档案";
      if (meta) meta.textContent = $(".terminal-record-meta", record)?.textContent || "MEMORY CHANNEL";
      if (id) id.textContent = "M-" + String(selectedIndex + 1).padStart(3, "0");
      if (number) number.textContent = String(selectedIndex + 1).padStart(2, "0");
      if (category) category.textContent = $(".terminal-record-channel", record)?.textContent || "记忆档案";
      if (channel) channel.textContent = $(".terminal-record-channel", record)?.textContent || "ALL RECORDS";
      if (focus) record.focus({ preventScroll: true });
    };
    const applySearch = () => {
      const query = compact(search?.value).toLowerCase();
      let visible = 0;
      records.forEach((record) => {
        const shown = !query || compact(record.dataset.terminalText).toLowerCase().includes(query);
        record.hidden = !shown;
        if (shown) visible += 1;
      });
      if (resultCount) resultCount.textContent = visible + " RECORDS";
    };
    search?.addEventListener("input", applySearch);
    records.forEach((record, index) => record.addEventListener("click", () => {
      select(index);
      if (record.dataset.memory) openMemory(record.dataset.memory);
      else if (record.dataset.core) go("core");
      else go("inspect");
    }));
    $("#terminalFileTitle", node)?.addEventListener("click", () => records[selectedIndex]?.click());
    $("#terminalAccess", node)?.addEventListener("click", () => records[selectedIndex]?.click());
    $("[data-terminal-prev]", node)?.addEventListener("click", () => select(selectedIndex - 1, true));
    $("[data-terminal-next]", node)?.addEventListener("click", () => select(selectedIndex + 1, true));
    $("[data-terminal-column-prev]", node)?.addEventListener("click", () => {
      channelIndex = (channelIndex + channels.length - 1) % channels.length;
      const target = channels[channelIndex];
      const index = target === "all" ? 0 : records.findIndex((record) => record.dataset.terminalChannel === target);
      if (index >= 0) select(index, true);
    });
    $("[data-terminal-column-next]", node)?.addEventListener("click", () => {
      channelIndex = (channelIndex + 1) % channels.length;
      const target = channels[channelIndex];
      const index = target === "all" ? 0 : records.findIndex((record) => record.dataset.terminalChannel === target);
      if (index >= 0) select(index, true);
    });
    applySearch();
    select(0);
  },
});

/* ============================================================
   视图：记忆导航
   ============================================================ */
async function loadPool() {
  if (state.pool) return state.pool;
  const result = await apiGet("/memories?limit=800");
  state.pool = Array.isArray(result.memories) ? result.memories : [];
  return state.pool;
}

function invalidatePool() {
  state.pool = null;
}

defineView("navigate", {
  title: "记忆导航",
  navLabel: "记忆导航",
  eyebrow: "Library · Navigate",
  hint: "按记忆归属进入：私聊、群聊、用户档案、Bot 个人、核心记忆与外部接口",
  async load() {
    await withBusy("正在读取记忆分布…", async () => {});
    const [statsPayload, core, pool, buckets] = await Promise.all([
      apiGet("/stats"),
      apiTry(() => apiGet("/core-memory"), { blocks: [] }),
      apiTry(loadPool, []),
      apiTry(() => apiGet("/buckets?limit=160"), { buckets: [] }),
    ]);
    const statsData = (statsPayload && statsPayload.stats) || {};
    const byScope = statsData.by_scope || {};
    const personalCount = pool.filter((m) => compact(m.visibility) === "bot_self").length;
    const externalCount = pool.filter((m) => {
      const source = compact(m.source_plugin);
      return source && source !== "self" && source !== "astrbot_plugin_memory_companion";
    }).length;
    const externalCapped = externalCount >= pool.length && pool.length >= 800;
    const personalCapped = personalCount >= pool.length && pool.length >= 800;
    return {
      counts: {
        private: int(byScope.private),
        group: int(byScope.group),
        profile: int(statsData.identities),
        personal: int(personalCount),
        core: int((core.blocks || []).length),
        external: int(externalCount),
      },
      capped: { personal: personalCapped, external: externalCapped },
      poolSize: pool.length,
      buckets: Array.isArray(buckets.buckets) ? buckets.buckets : [],
      pool,
    };
  },
  render(data) {
    const counts = data.counts || {};
    const max = Math.max(1, ...Object.values(counts).map((v) => int(v)));

    const scopes = [
      { key: "private", meta: SCOPE_META.private, jump: "inspect", filter: "scope:private", exact: true },
      { key: "group", meta: SCOPE_META.group, jump: "inspect", filter: "scope:group", exact: true },
      { key: "profile", meta: SCOPE_META.profile, jump: "inspect", filter: "profile", exact: true },
      { key: "personal", meta: SCOPE_META.personal, jump: "botlife", filter: "", exact: false },
      { key: "core", meta: SCOPE_META.core, jump: "core", filter: "", exact: true },
      { key: "external", meta: SCOPE_META.external, jump: "external", filter: "", exact: false },
    ];

    const cards = scopes
      .map((item) => {
        const count = int(counts[item.key]);
        const capped = Boolean(data.capped && data.capped[item.key]);
        const note = item.exact ? "精确统计" : capped ? "≥ " + fmtInt(count) + "（抽样下限）" : "基于 " + fmtInt(data.poolSize) + " 条抽样";
        return (
          '<button class="scope-card" type="button" data-tone="' + item.meta.tone + '" data-goto="' + item.jump + '" data-filter="' + esc(item.filter) + '">' +
          '<div class="scope-top">' + icon(item.meta.icon, "scope-icon") +
          '<span class="scope-count">' + fmtInt(count) + " 条</span></div>" +
          '<div class="scope-body"><div class="scope-name">' + esc(item.meta.label) + "</div>" +
          '<div class="scope-desc">' + esc(item.meta.desc) + "</div></div>" +
          '<div class="scope-bar"><i style="width:' + ((count / max) * 100).toFixed(1) + '%"></i></div>' +
          '<div class="scope-foot"><span>' + esc(note) + "</span>" +
          "<span>进入 ›</span></div></button>"
        );
      })
      .join("");

    const recent = (data.buckets || [])
      .slice()
      .sort((a, b) => int(b.memory_count) - int(a.memory_count))
      .slice(0, 10)
      .map((bucket) => {
        const scope = compact(bucket.scope);
        const meta = SCOPE_META[scope] || { label: scope || "未分类", tone: "" };
        return (
          '<button class="row" type="button" data-goto="inspect" data-scope="' + esc(scope) + '" data-target="' + esc(compact(bucket.target_id)) + '">' +
          '<div class="row-main"><div class="row-title">' + esc(compact(bucket.label) || compact(bucket.target_name) || compact(bucket.target_id) || "未命名窗口") + "</div>" +
          '<div class="row-sub">' + esc(compact(bucket.target_kind) || "window") + " · " + esc(compact(bucket.sample_session_id) || "-") + "</div></div>" +
          '<div class="row-meta">' + badge(meta.label, meta.tone) + badge(fmtInt(bucket.memory_count) + " 条") + "</div></button>"
        );
      })
      .join("");

    const typeBreakdown = {};
    (data.pool || []).forEach((memory) => {
      const key = compact(memory.memory_type) || "unknown";
      typeBreakdown[key] = (typeBreakdown[key] || 0) + 1;
    });
    const typeRows = Object.entries(typeBreakdown)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map((entry) => meter(TYPE_LABEL[entry[0]] || entry[0], fmtInt(entry[1]), Math.max(1, data.pool.length)))
      .join("");

    const visBreakdown = {};
    (data.pool || []).forEach((memory) => {
      const key = compact(memory.visibility) || "unknown";
      visBreakdown[key] = (visBreakdown[key] || 0) + 1;
    });
    const visRows = Object.entries(visBreakdown)
      .sort((a, b) => b[1] - a[1])
      .map((entry) => meter(VISIBILITY_LABEL[entry[0]] || entry[0], fmtInt(entry[1]), Math.max(1, data.pool.length)))
      .join("");

    return (
      '<div class="grid" style="gap:16px">' +
      '<div class="section-label"><h2>记忆归属</h2><span class="section-note">点击任一范围进入对应检视视图</span></div>' +
      '<div class="grid g3">' + cards + "</div>" +
      '<div class="grid split-2">' +
        card("最近活跃范围", (data.buckets || []).length + " 个窗口 · 按记忆量排序", '<div class="row-list">' + (recent || emptyState("暂无范围", "还没有可展示的记忆窗口。")) + "</div>") +
        '<div style="display:grid;gap:16px">' +
          card("记忆类型构成", "基于最近 " + fmtInt(data.poolSize) + " 条抽样", '<div style="display:grid;gap:9px">' + (typeRows || "—") + "</div>") +
          card("可见性构成", "决定谁能读到这条记忆", '<div style="display:grid;gap:9px">' + (visRows || "—") + "</div>") +
        "</div>" +
      "</div>" +
      "</div>"
    );
  },
});

/* ============================================================
   视图：记忆检视
   ============================================================ */
defineView("inspect", {
  title: "记忆检视",
  navLabel: "记忆检视",
  eyebrow: "Library · Inspect",
  hint: "按范围、类型、可见性和生命周期筛选，逐条核对 46 项记忆参数",
  async load(options) {
    const opts = options || {};
    if (opts.scope) state.filters.scope = opts.scope;
    if (opts.target) state.filters.target = opts.target;
    const filters = state.filters;
    const params = ["limit=120"];
    if (filters.scope) params.push("scope=" + encodeURIComponent(filters.scope));
    if (filters.visibility) params.push("visibility=" + encodeURIComponent(filters.visibility));
    if (filters.lifecycle) params.push("lifecycle=" + encodeURIComponent(filters.lifecycle));
    if (filters.memoryType) params.push("memory_type=" + encodeURIComponent(filters.memoryType));
    if (filters.q) params.push("q=" + encodeURIComponent(filters.q));
    if (filters.target) {
      if (filters.scope === "group") params.push("group_id=" + encodeURIComponent(filters.target));
      else params.push("entity_id=" + encodeURIComponent(filters.target));
    }
    const result = await apiGet("/memories?" + params.join("&"));
    let memories = Array.isArray(result.memories) ? result.memories : [];
    if (filters.scope === "profile") {
      memories = memories.filter((m) => [
        "profile", "user_profile", "user_habit",
        "preference", "user_preference",
        "relationship", "relationship_claim", "relationship_phase_summary",
      ].includes(compact(m.memory_type)));
    }
    return { memories, filters };
  },
  render(data) {
    const filters = data.filters || {};
    const memories = data.memories || [];

    const scopePills = ["", "private", "group", "profile", "external"]
      .map((key) => {
        const label = key === "" ? "全部" : key === "external" ? "外部接口" : (SCOPE_META[key] ? SCOPE_META[key].label : key);
        return '<button class="pill' + ((filters.scope || "") === key ? " is-active" : "") + '" type="button" data-filter-key="scope" data-filter-value="' + esc(key) + '">' + esc(label) + "</button>";
      })
      .join("");

    const typePills = ["", "profile", "preference", "relationship", "fact", "event", "state", "promise", "schedule", "thought"]
      .map((key) => {
        const label = key === "" ? "全部类型" : TYPE_LABEL[key] || key;
        return '<button class="pill' + ((filters.memoryType || "") === key ? " is-active" : "") + '" type="button" data-filter-key="memoryType" data-filter-value="' + esc(key) + '">' + esc(label) + "</button>";
      })
      .join("");

    const visPills = ["", "public", "private", "group_shared", "bot_self", "restricted"]
      .map((key) => {
        const label = key === "" ? "全部可见性" : VISIBILITY_LABEL[key] || key;
        return '<button class="pill' + ((filters.visibility || "") === key ? " is-active" : "") + '" type="button" data-filter-key="visibility" data-filter-value="' + esc(key) + '">' + esc(label) + "</button>";
      })
      .join("");

    const lifePills = ["", "active", "stable", "fading", "archived", "expired"]
      .map((key) => {
        const label = key === "" ? "全部生命周期" : LIFECYCLE_LABEL[key] || key;
        return '<button class="pill' + ((filters.lifecycle || "") === key ? " is-active" : "") + '" type="button" data-filter-key="lifecycle" data-filter-value="' + esc(key) + '">' + esc(label) + "</button>";
      })
      .join("");

    const activeChips = [];
    if (filters.q) activeChips.push("关键词：" + filters.q);
    if (filters.target) activeChips.push("目标：" + filters.target);

    const rows = memories.length
      ? memories.map((memory, index) => memoryRow(memory, index)).join("")
      : emptyState("没有匹配的记忆", "试着放宽筛选条件，或清空关键词后重新加载。");

    return (
      '<div class="grid" style="gap:14px">' +
      '<section class="card is-tight">' +
        '<div style="display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center">' +
          '<div class="pill-row">' + scopePills + "</div>" +
        "</div>" +
        '<div style="display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-top:10px">' +
          '<div class="pill-row">' + typePills + "</div>" +
        "</div>" +
        '<div style="display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-top:10px">' +
          '<div class="pill-row">' + visPills + "</div>" +
          '<div class="pill-row">' + lifePills + "</div>" +
        "</div>" +
        '<div style="display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap">' +
          '<input id="inspectQuery" type="search" placeholder="按内容或证据过滤" value="' + esc(filters.q || "") + '" style="flex:1;min-width:200px;height:32px;padding:0 12px;border:1px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--text);font-size:12.5px;outline:none" />' +
          '<button class="btn is-sm" type="button" id="applyQueryBtn">应用</button>' +
          '<button class="btn is-sm is-ghost" type="button" id="clearFiltersBtn">清空筛选</button>' +
          '<span style="margin-left:auto;font-size:11.5px;color:var(--text-3)">' + fmtInt(memories.length) + " 条" + (activeChips.length ? " · " + esc(activeChips.join(" · ")) : "") + "</span>" +
        "</div>" +
      "</section>" +
      '<div class="row-list" id="inspectList">' + rows + "</div>" +
      "</div>"
    );
  },
  mount(node) {
    $$("[data-filter-key]", node).forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.filterKey;
        const value = button.dataset.filterValue;
        state.filters[key] = value;
        if (key === "scope") state.filters.target = "";
        go("inspect");
      });
    });
    const applyBtn = $("#applyQueryBtn", node);
    if (applyBtn) {
      applyBtn.addEventListener("click", () => {
        state.filters.q = $("#inspectQuery", node).value.trim();
        go("inspect");
      });
      $("#inspectQuery", node).addEventListener("keydown", (event) => {
        if (event.key === "Enter") applyBtn.click();
      });
    }
    const clearBtn = $("#clearFiltersBtn", node);
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        state.filters = { scope: "", q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };
        go("inspect");
      });
    }
    $$("[data-memory]", node).forEach((row) => {
      row.addEventListener("click", () => openMemory(row.dataset.memory));
    });
  },
});

/* ============================================================
   视图：核心记忆
   ============================================================ */
const CORE_KINDS = { rule: "规则", boundary: "边界", preference: "偏好", profile: "画像", fact: "事实", state: "稳定状态" };
const CORE_SCOPES = { global: "全局 / Bot", private: "私聊用户", group: "群聊" };

defineView("core", {
  title: "核心记忆",
  navLabel: "核心记忆",
  eyebrow: "Library · Core",
  hint: "始终参与注入的稳定事实、规则与边界，按作用域与优先级排序",
  async load() {
    const result = await apiTry(() => apiGet("/core-memory"), { blocks: [] });
    const blocks = Array.isArray(result.blocks) ? result.blocks : [];
    blocks.sort((a, b) => int(b.priority) - int(a.priority));
    return { blocks };
  },
  render(data) {
    const blocks = data.blocks || [];
    const rows = blocks.length
      ? blocks
          .map(
            (block) =>
              '<button class="row" type="button" data-core="' + esc(block.id) + '">' +
              '<div class="row-main"><div class="row-title">' + esc(compact(block.label) || "未命名块") + "</div>" +
              '<div class="row-sub">' + esc(clip(compact(block.content), 84)) + "</div></div>" +
              '<div class="row-meta">' +
                badge(CORE_KINDS[compact(block.kind)] || compact(block.kind) || "事实", "gold") +
                badge(CORE_SCOPES[compact(block.scope)] || compact(block.scope) || "全局", "fact") +
                badge("P" + int(block.priority), "accent") +
                (block.enabled ? "" : badge("已停用", "warn")) +
              "</div></button>"
          )
          .join("")
      : emptyState("还没有核心记忆块", "核心记忆会在每次对话时优先注入，适合放稳定的人设规则与长期事实。");

    const form =
      '<form id="coreForm" class="config-form" autocomplete="off">' +
      '<input type="hidden" name="id" id="coreId" />' +
      '<input type="hidden" name="expected_revision" id="coreRevision" value="0" />' +
      '<div class="grid g3" style="gap:10px">' +
        '<label class="field"><span>Label</span><input name="label" id="coreLabel" type="text" maxlength="80" placeholder="例如 preferred_address" required /></label>' +
        '<label class="field"><span>类型</span><select name="kind" id="coreKind">' + Object.keys(CORE_KINDS).map((k) => '<option value="' + k + '">' + CORE_KINDS[k] + "</option>").join("") + "</select></label>" +
        '<label class="field"><span>作用域</span><select name="scope" id="coreScope">' + Object.keys(CORE_SCOPES).map((k) => '<option value="' + k + '">' + CORE_SCOPES[k] + "</option>").join("") + "</select></label>" +
        '<label class="field"><span>目标 ID</span><input name="target_id" id="coreTarget" type="text" maxlength="160" placeholder="私聊用户或群聊 ID" /></label>' +
        '<label class="field"><span>Bot ID</span><input name="bot_id" id="coreBot" type="text" maxlength="120" placeholder="留空表示全部 Bot" /></label>' +
        '<label class="field"><span>人格 ID</span><input name="persona_id" id="corePersona" type="text" maxlength="120" placeholder="留空表示全部人格" /></label>' +
      "</div>" +
      '<label class="field"><span>内容</span><textarea name="content" id="coreContent" rows="4" maxlength="4000" placeholder="要长期记住的内容" required></textarea></label>' +
      '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">' +
        '<label class="field is-inline" style="width:auto"><span>优先级</span><input name="priority" id="corePriority" type="number" min="0" max="100" step="1" value="50" style="width:88px" /></label>' +
        '<label class="switch"><input type="checkbox" id="coreEnabled" checked /><span class="switch-track"></span><span>启用注入</span></label>' +
        '<div class="pill-row" style="margin-left:auto">' +
          '<button class="btn is-sm is-ghost" type="button" id="coreResetBtn">重置</button>' +
          '<button class="btn is-sm is-primary" type="submit">保存核心块</button>' +
        "</div>" +
      "</div>" +
      "</form>";

    return (
      '<div class="grid split-2">' +
        card("核心记忆块", (data.blocks || []).length + " 个 · 按优先级排序", '<div class="row-list">' + rows + "</div>") +
        card("编辑核心块", "留空 ID 表示新建", form) +
      "</div>"
    );
  },
  mount(node, data) {
    const blocks = (data.blocks || []).reduce((acc, block) => {
      acc[block.id] = block;
      return acc;
    }, {});

    const fill = (block) => {
      $("#coreId", node).value = block ? compact(block.id) : "";
      $("#coreRevision", node).value = block ? int(block.revision) : 0;
      $("#coreLabel", node).value = block ? compact(block.label) : "";
      $("#coreKind", node).value = block ? compact(block.kind) || "fact" : "fact";
      $("#coreScope", node).value = block ? compact(block.scope) || "global" : "global";
      $("#coreTarget", node).value = block ? compact(block.target_id) : "";
      $("#coreBot", node).value = block ? compact(block.bot_id) : "";
      $("#corePersona", node).value = block ? compact(block.persona_id) : "";
      $("#coreContent", node).value = block ? compact(block.content) : "";
      $("#corePriority", node).value = block ? int(block.priority) : 50;
      $("#coreEnabled", node).checked = block ? block.enabled !== false : true;
    };

    $$("[data-core]", node).forEach((row) => {
      row.addEventListener("click", () => fill(blocks[row.dataset.core]));
    });

    $("#coreResetBtn", node).addEventListener("click", () => fill(null));

    $("#coreForm", node).addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = {
        id: $("#coreId", node).value.trim(),
        expected_revision: int($("#coreRevision", node).value),
        label: $("#coreLabel", node).value.trim(),
        kind: $("#coreKind", node).value,
        scope: $("#coreScope", node).value,
        target_id: $("#coreTarget", node).value.trim(),
        bot_id: $("#coreBot", node).value.trim(),
        persona_id: $("#corePersona", node).value.trim(),
        content: $("#coreContent", node).value.trim(),
        priority: int($("#corePriority", node).value),
        enabled: $("#coreEnabled", node).checked,
      };
      if (!payload.label || !payload.content) {
        toast("Label 与内容都不能为空", "error");
        return;
      }
      await withBusy("正在保存…", async () => {
        const result = await apiPost("/core-memory/upsert", payload);
        if (result && result.ok === false) {
          toast("保存失败：" + (result.code || "未知原因"), "error");
          return;
        }
        invalidatePool();
        toast("核心记忆已保存", "ok");
        fill(null);
        refresh();
      });
    });
  },
});

/* ============================================================
   视图：Bot 日程与相册
   ============================================================ */
let botLifeDate = "";

defineView("botlife", {
  title: "Bot 日程与相册",
  navLabel: "Bot 日程与相册",
  eyebrow: "Library · Bot Self",
  hint: "Bot 自己的一天：日程安排、每日状态、相册、主观记忆与细化片段",
  async load(options) {
    const opts = options || {};
    if (opts.date) botLifeDate = opts.date;
    const params = botLifeDate ? "?date=" + encodeURIComponent(botLifeDate) + "&limit=80" : "?limit=80";
    const result = await apiTry(() => apiGet("/companion/personal-memory" + params), { available: false });
    if (result.available === false) {
      const caps = await apiTry(() => apiGet("/capabilities/bot-personal"), null);
      return { available: false, reason: compact(result.reason) || "未检测到主动陪伴插件", caps };
    }
    if (result.selected_date) botLifeDate = result.selected_date;
    return Object.assign({ available: true }, result);
  },
  render(data) {
    if (!data.available) {
      return (
        '<div class="grid g3">' +
        card(
          "Bot 个人记忆不可用",
          "需要主动陪伴插件",
          emptyState("未检测到陪伴插件", compact(data.reason) || "安装并启用 astrbot_plugin_private_companion 后，这里会显示 Bot 的日程、相册与主观记忆。")
        ) +
        "</div>"
      );
    }
    const snap = data.snapshot || {};
    const plan = snap.plan || {};
    const items = Array.isArray(plan.items) ? plan.items : [];
    const current = snap.current_item || {};
    const dailyState = snap.daily_state || {};
    const album = Array.isArray(snap.album) ? snap.album : [];
    const subjective = Array.isArray(snap.subjective_memories) ? snap.subjective_memories : [];
    const details = Array.isArray(snap.details) ? snap.details : [];
    const dates = Array.isArray(data.dates) ? data.dates : [];

    const datePills = dates
      .slice(0, 14)
      .map((d) => '<button class="pill' + (d === data.selected_date ? " is-active" : "") + '" type="button" data-date="' + esc(d) + '">' + esc(fmtDate(d)) + "</button>")
      .join("");

    const schedule = items.length
      ? '<div class="schedule-list">' +
        items
          .map((item) => {
            const isNow = compact(item.time) && compact(current.time) === compact(item.time);
            return (
              '<div class="schedule-item' + (isNow ? " is-now" : "") + '">' +
              '<div class="schedule-time">' + esc(compact(item.time) || "--:--") + "</div>" +
              "<div><div class=\"schedule-title\">" + esc(compact(item.activity) || "未安排") +
              (compact(item.mood) ? " · " + esc(item.mood) : "") + "</div>" +
              (compact(item.message_seed) ? '<div class="schedule-note">' + esc(clip(item.message_seed, 80)) + "</div>" : "") +
              "</div></div>"
            );
          })
          .join("") +
        "</div>"
      : emptyState("这一天还没有日程", "陪伴插件未生成当日计划，或该日期尚无记录。");

    const stateRows = [
      ["日期", compact(dailyState.date) || data.selected_date],
      ["精力", compact(dailyState.energy)],
      ["心情倾向", compact(dailyState.mood_bias)],
      ["睡眠", compact(dailyState.sleep)],
      ["天气", compact(dailyState.weather)],
      ["备注", compact(dailyState.note)],
    ].filter((row) => row[1]);

    const albumHtml = album.length
      ? '<div class="album-grid">' +
        album
          .map(
            (photo) =>
              photo.exists
                ? '<figure class="album-shot" data-cap="' + esc(compact(photo.title) + " · " + compact(photo.generated_at)) + '" style="margin:0">' +
                  '<img src="' + TRANSPARENT_IMAGE + '" data-album-image-src="' + esc(compact(photo.image_data_url) || compact(photo.url)) + '" alt="' + esc(compact(photo.title)) + '" loading="lazy" />' +
                  '<figcaption class="shot-cap"><b>' + esc(compact(photo.title)) + "</b><span>" + esc(compact(photo.generated_at) || compact(photo.date)) + "</span></figcaption></figure>"
                : '<div class="album-shot is-missing">' + esc(compact(photo.error) || "图片不可用") + "</div>"
          )
          .join("") +
        "</div>"
      : emptyState("相册还是空的", "Bot 生成每日穿搭图或生活分享图后，会出现在这里。");

    const subjectiveHtml = subjective.length
      ? '<div class="row-list">' +
        subjective
          .map(
            (item) =>
              '<div class="row" style="cursor:default;align-items:flex-start"><div class="row-main">' +
              '<div class="row-title">' + esc(compact(item.summary) || "主观记忆") + "</div>" +
              '<div class="row-sub" style="white-space:normal">' + esc(clip(compact(item.body), 150)) + "</div>" +
              (Array.isArray(item.tags) && item.tags.length ? '<div class="tag-row" style="margin-top:6px">' + item.tags.map((tag) => badge(tag, "personal")).join("") + "</div>" : "") +
              "</div></div>"
          )
          .join("") +
        "</div>"
      : emptyState("暂无主观记忆", "Bot 的日记与梦境碎片会汇总在这里。");

    const detailsHtml = details.length
      ? '<div class="row-list">' +
        details
          .map(
            (item) =>
              '<div class="row" style="cursor:default;align-items:flex-start"><div class="row-main">' +
              '<div class="row-title">' + esc(compact(item.time) || compact(item.key) || "片段") + " · " + esc(compact(item.status) || "进行中") + "</div>" +
              '<div class="row-sub" style="white-space:normal">' + esc(clip(compact(item.summary) || (item.today_events || []).join(" / "), 150)) + "</div>" +
              "</div></div>"
          )
          .join("") +
        "</div>"
      : emptyState("暂无细化片段", "启用陪伴插件的细化增强后，会按时间段记录 Bot 的具体经历。");

    return (
      '<div class="grid" style="gap:16px">' +
      '<div class="section-label"><h2>' + esc(compact(snap.bot_name) || "Bot") + " 的这一天</h2>" +
        '<span class="section-note">' + esc(compact(data.selected_date) || "") + (compact(plan.source) ? " · 来源 " + compact(plan.source) : "") + "</span></div>" +
      '<div class="pill-row">' + (datePills || '<span class="badge">仅此一天</span>') + "</div>" +
      '<div class="grid split-2">' +
        card("当日日程", items.length + " 个时段" + (compact(current.activity) ? " · 当前：" + compact(current.activity) : ""), schedule) +
        '<div style="display:grid;gap:16px">' +
          card("每日状态", "Bot 自身状态快照", stateRows.length ? '<dl class="kv">' + stateRows.map((row) => "<dt>" + esc(row[0]) + "</dt><dd>" + esc(row[1]) + "</dd>").join("") + "</dl>" : emptyState("暂无状态", "陪伴插件尚未写入当日状态。")) +
          card("相册", album.length + " 张", albumHtml) +
        "</div>" +
      "</div>" +
      '<div class="grid g2">' +
        card("主观记忆", "日记 · 梦境 · 感受", subjectiveHtml) +
        card("细化片段", details.length + " 段", detailsHtml) +
      "</div>" +
      "</div>"
    );
  },
  mount(node) {
    hydratePersonalAlbumImages(node);
    $$("[data-date]", node).forEach((button) => {
      button.addEventListener("click", () => go("botlife", { date: button.dataset.date }));
    });
    $$(".album-shot:not(.is-missing)", node).forEach((figure) => {
      figure.addEventListener("click", () => {
        const image = $("img", figure);
        const source = image && image.dataset.loaded === "1" ? image.currentSrc || image.src : "";
        if (source) openLightbox(source, figure.dataset.cap);
      });
    });
  },
});

function albumImageDataPath(source) {
  const raw = String(source || "");
  if (!raw || raw.startsWith("data:")) return raw;
  try {
    const url = new URL(raw, window.location.origin);
    if (url.pathname.endsWith("/companion/personal-photo-data")) return "/companion/personal-photo-data" + url.search;
    if (url.pathname.endsWith("/companion/personal-photo")) return "/companion/personal-photo-data" + url.search;
  } catch (error) {
    const marker = "/companion/personal-photo";
    const index = raw.indexOf(marker);
    if (index >= 0) return "/companion/personal-photo-data" + raw.slice(index + marker.length);
  }
  return raw;
}

async function hydratePersonalAlbumImages(root) {
  const images = $$("img[data-album-image-src]", root);
  await Promise.all(images.map(async (img) => {
    const source = img.dataset.albumImageSrc || "";
    if (!source || img.dataset.loaded === "1") return;
    img.dataset.loading = "1";
    try {
      const endpoint = albumImageDataPath(source);
      if (endpoint.startsWith("data:")) {
        img.src = endpoint;
      } else if (endpoint.startsWith("/companion/personal-photo-data")) {
        const result = await apiGet(endpoint);
        if (!result || !result.data_url) throw new Error("图片数据为空");
        img.src = result.data_url;
      } else {
        img.src = source;
      }
      img.dataset.loaded = "1";
    } catch (error) {
      img.dataset.loaded = "0";
      const fallback = document.createElement("div");
      fallback.className = "album-photo-error";
      fallback.textContent = "图片加载失败";
      const figure = img.closest(".album-shot");
      if (figure) figure.classList.add("is-missing");
      img.replaceWith(fallback);
    } finally {
      img.dataset.loading = "0";
    }
  }));
}

function openLightbox(src, caption) {
  const box = document.createElement("div");
  box.className = "lightbox";
  box.innerHTML = '<img src="' + esc(src) + '" alt="" /><div class="lightbox-cap">' + esc(caption || "") + "</div>";
  box.addEventListener("click", () => box.remove());
  document.body.appendChild(box);
}

/* ============================================================
   知识星图 · 星系模型
   中央恒星 = 选中的核心记忆；卫星 = 关联记忆，按关联强度落在
   内 / 中 / 外三条星轨上，带透视与流动尾迹。
   ============================================================ */
const ORBIT_TIERS = [
  { key: "inner", label: "内轨 · 强关联", ratio: 0.34, speed: 4.0, color: "#a99bff" },
  { key: "mid", label: "中轨 · 相关", ratio: 0.56, speed: 2.6, color: "#7c6cf0" },
  { key: "outer", label: "外轨 · 弱相关", ratio: 0.79, speed: 1.7, color: "#4c5a7a" },
];

const TYPE_COLORS = {
  profile: "#f472b6",
  preference: "#f472b6",
  relationship: "#f472b6",
  fact: "#60a5fa",
  state: "#60a5fa",
  event: "#2dd4bf",
  action: "#2dd4bf",
  image_action: "#fb923c",
  schedule: "#fb923c",
  promise: "#fcd34d",
  emotion: "#f87171",
  thought: "#a99bff",
};

function satelliteColor(memory) {
  const source = compact(memory.source_plugin);
  if (source && source !== "self" && source !== "astrbot_plugin_memory_companion") return "#7dd3fc";
  return TYPE_COLORS[compact(memory.memory_type)] || "#a99bff";
}

function typeLabel(memory) {
  const type = compact(memory.memory_type);
  return TYPE_LABEL[type] || type || "记忆";
}

function memoryTimestamp(memory) {
  const value = compact(memory.occurred_at) || compact(memory.created_at) || compact(memory.updated_at);
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function relationScore(center, other) {
  if (!center || !other || center.id === other.id) return 0;
  let score = 0;
  const centerTags = new Set((Array.isArray(center.tags) ? center.tags : []).map((t) => compact(t)).filter(Boolean));
  const otherTags = Array.isArray(other.tags) ? other.tags : [];
  const sharedTags = otherTags.filter((tag) => centerTags.has(compact(tag)));
  score += Math.min(3, sharedTags.length) * 0.22;

  const centerSubject = compact(center.subject && center.subject.id);
  const otherSubject = compact(other.subject && other.subject.id);
  if (centerSubject && centerSubject === otherSubject) score += 0.3;

  const centerSession = compact(center.session_id);
  if (centerSession && centerSession === compact(other.session_id)) score += 0.2;
  const centerGroup = compact(center.group_id);
  if (centerGroup && centerGroup === compact(other.group_id)) score += 0.16;

  if (compact(center.scope) === compact(other.scope)) score += 0.1;
  if (compact(center.memory_type) === compact(other.memory_type)) score += 0.08;

  const batch = compact(center.import_batch_id);
  if (batch && batch === compact(other.import_batch_id)) score += 0.18;

  const ct = memoryTimestamp(center);
  const ot = memoryTimestamp(other);
  if (ct && ot) {
    const days = Math.abs(ct - ot) / 86400000;
    if (days <= 1) score += 0.16;
    else if (days <= 7) score += 0.1;
    else if (days <= 30) score += 0.05;
  }
  return clamp(score, 0, 1);
}

function buildGalaxy(memories, centerId) {
  const pool = (memories || []).filter((m) => compact(m.id));
  if (!pool.length) return null;
  let center = centerId ? pool.find((m) => m.id === centerId) : null;
  if (!center) {
    center = pool.slice().sort((a, b) => {
      const diff = Number(b.importance || 0) - Number(a.importance || 0);
      if (Math.abs(diff) > 0.0001) return diff;
      return memoryTimestamp(b) - memoryTimestamp(a);
    })[0];
  }
  const scored = pool
    .filter((m) => m.id !== center.id)
    .map((memory) => ({ memory, score: relationScore(center, memory) }))
    .filter((item) => item.score > 0.08)
    .sort((a, b) => b.score - a.score || Number(b.memory.importance || 0) - Number(a.memory.importance || 0))
    .slice(0, 12);

  const nodes = scored.map((item, index) => {
    const tier = item.score >= 0.62 ? 0 : item.score >= 0.36 ? 1 : 2;
    const count = scored.filter((s, i) => (s.score >= 0.62 ? 0 : s.score >= 0.36 ? 1 : 2) === tier).length;
    return {
      id: item.memory.id,
      memory: item.memory,
      score: item.score,
      tier,
      color: satelliteColor(item.memory),
      angle: (index / Math.max(1, scored.length)) * Math.PI * 2 + tier * 0.7,
      size: 4.4 + Number(item.memory.importance || 0) * 5.2 + item.score * 2.4,
      slotIndex: index,
      tierCount: count,
    };
  });
  return { center, nodes, pool };
}

function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

class GalaxyView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    this.w = 0;
    this.h = 0;
    this.galaxy = null;
    this.pending = null;
    this.transition = null;
    this.hoverId = "";
    this.paused = false;
    this.destroyed = false;
    this.starfield = [];
    this.lastFrame = 0;
    this.tip = null;
    this.onSelect = null;
    this.onHover = null;
    this.resize();
    this.bindEvents();
    this.loop = this.loop.bind(this);
    requestAnimationFrame(this.loop);
  }

  destroy() {
    this.destroyed = true;
    window.removeEventListener("resize", this.resizeHandler);
    this.canvas.removeEventListener("mousemove", this.moveHandler);
    this.canvas.removeEventListener("mouseleave", this.leaveHandler);
    this.canvas.removeEventListener("click", this.clickHandler);
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.w = Math.max(320, Math.round(rect.width));
    this.h = Math.max(320, Math.round(rect.height || 620));
    this.canvas.width = Math.round(this.w * this.dpr);
    this.canvas.height = Math.round(this.h * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.buildStarfield();
  }

  buildStarfield() {
    const count = Math.round((this.w * this.h) / 5200);
    const stars = [];
    let seed = 20260829;
    const rand = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    for (let i = 0; i < count; i += 1) {
      stars.push({
        x: rand() * this.w,
        y: rand() * this.h,
        r: 0.35 + rand() * 0.95,
        a: 0.12 + rand() * 0.42,
        tw: rand() * Math.PI * 2,
      });
    }
    this.starfield = stars;
  }

  bindEvents() {
    this.resizeHandler = () => this.resize();
    window.addEventListener("resize", this.resizeHandler);

    this.moveHandler = (event) => {
      const rect = this.canvas.getBoundingClientRect();
      const mx = event.clientX - rect.left;
      const my = event.clientY - rect.top;
      const found = this.hitTest(mx, my);
      const id = found ? found.id : "";
      if (id !== this.hoverId) {
        this.hoverId = id;
        this.canvas.style.cursor = id ? "pointer" : "default";
        if (this.onHover) this.onHover(found ? found.node : null, mx, my);
      } else if (id && this.onHover) {
        this.onHover(found.node, mx, my);
      }
    };
    this.leaveHandler = () => {
      this.hoverId = "";
      this.canvas.style.cursor = "default";
      if (this.onHover) this.onHover(null, 0, 0);
    };
    this.clickHandler = (event) => {
      const rect = this.canvas.getBoundingClientRect();
      const found = this.hitTest(event.clientX - rect.left, event.clientY - rect.top);
      if (found && this.onSelect) this.onSelect(found.node);
    };
    this.canvas.addEventListener("mousemove", this.moveHandler);
    this.canvas.addEventListener("mouseleave", this.leaveHandler);
    this.canvas.addEventListener("click", this.clickHandler);
  }

  setGalaxy(galaxy) {
    if (!galaxy) return;
    if (!this.galaxy || !this.galaxy.center || galaxy.center.id === this.galaxy.center.id) {
      const keepAngles = {};
      if (this.galaxy) this.galaxy.nodes.forEach((node) => (keepAngles[node.id] = node.angle));
      galaxy.nodes.forEach((node) => {
        if (keepAngles[node.id] !== undefined) node.angle = keepAngles[node.id];
        node.born = 1;
      });
      this.galaxy = galaxy;
      return;
    }
    const outgoing = this.galaxy;
    const incoming = galaxy;
    const clicked = outgoing.nodes.find((node) => node.id === galaxy.center.id);
    incoming.nodes.forEach((node) => {
      node.born = 0;
    });
    this.transition = {
      t: 0,
      outgoing,
      incoming,
      clicked: clicked || null,
      startX: clicked ? this.nodeX(clicked) : this.w / 2,
      startY: clicked ? this.nodeY(clicked) : this.h / 2,
      startSize: clicked ? clicked.size : 6,
      startColor: clicked ? clicked.color : "#a99bff",
    };
  }

  cx() {
    return this.w / 2;
  }
  cy() {
    return this.h / 2 - 6;
  }
  orbitRadius(tier) {
    const base = Math.min(this.w, this.h) * 0.5;
    return base * ORBIT_TIERS[tier].ratio;
  }
  nodeX(node) {
    const r = this.orbitRadius(node.tier);
    return this.cx() + Math.cos(node.angle) * r;
  }
  nodeY(node) {
    const r = this.orbitRadius(node.tier);
    return this.cy() + Math.sin(node.angle) * r * 0.7;
  }
  depthOf(angle) {
    return (Math.sin(angle) + 1) / 2;
  }

  hitTest(mx, my) {
    if (!this.galaxy) return null;
    const nodes = this.galaxy.nodes;
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      const node = nodes[i];
      if (node.born < 0.4) continue;
      const x = this.nodeX(node);
      const y = this.nodeY(node);
      const r = Math.max(11, node.size + 7);
      if ((mx - x) ** 2 + (my - y) ** 2 <= r * r) return { id: node.id, node };
    }
    const cx = this.cx();
    const cy = this.cy();
    if ((mx - cx) ** 2 + (my - cy) ** 2 <= 26 * 26) return null;
    return null;
  }

  loop(now) {
    if (this.destroyed) return;
    const dt = this.lastFrame ? Math.min(64, now - this.lastFrame) : 16;
    this.lastFrame = now;
    this.step(dt);
    this.draw(now);
    requestAnimationFrame(this.loop);
  }

  step(dt) {
    if (this.transition) {
      this.transition.t = Math.min(1, this.transition.t + dt / 1050);
      const e = easeInOutCubic(this.transition.t);
      this.transition.incoming.nodes.forEach((node, index) => {
        const delay = clamp((index / Math.max(1, this.transition.incoming.nodes.length)) * 0.5, 0, 0.5);
        node.born = clamp((e - delay) / (1 - delay), 0, 1);
      });
      if (this.transition.t >= 1) {
        this.transition.incoming.nodes.forEach((node) => (node.born = 1));
        this.galaxy = this.transition.incoming;
        this.transition = null;
        this.hoverId = "";
      }
      return;
    }
    if (this.paused || this.userPaused || !this.galaxy) return;
    const seconds = dt / 1000;
    this.galaxy.nodes.forEach((node) => {
      const dir = node.tier % 2 === 0 ? 1 : -1;
      node.angle += ((ORBIT_TIERS[node.tier].speed * Math.PI) / 180) * seconds * dir;
      if (node.angle > Math.PI * 4) node.angle -= Math.PI * 4;
      if (node.angle < -Math.PI * 4) node.angle += Math.PI * 4;
    });
  }

  draw(now) {
    const ctx = this.ctx;
    const isDark = document.documentElement.dataset.theme !== "light";
    ctx.clearRect(0, 0, this.w, this.h);

    const bg = ctx.createLinearGradient(0, 0, 0, this.h);
    if (isDark) {
      bg.addColorStop(0, "#05070d");
      bg.addColorStop(0.55, "#080b14");
      bg.addColorStop(1, "#05070d");
    } else {
      bg.addColorStop(0, "#eef2f9");
      bg.addColorStop(0.55, "#e6ecf7");
      bg.addColorStop(1, "#eef2f9");
    }
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, this.w, this.h);

    this.drawStarfield(now, isDark);
    this.drawDisk(isDark);
    this.drawOrbits(isDark);
    this.drawTransition(now, isDark);
    if (!this.transition) this.drawSystem(this.galaxy, now, isDark);
  }

  drawStarfield(now, isDark) {
    const ctx = this.ctx;
    const time = now / 1000;
    this.starfield.forEach((star) => {
      const tw = 0.65 + 0.35 * Math.sin(time * 0.7 + star.tw);
      ctx.globalAlpha = star.a * tw;
      ctx.fillStyle = isDark ? "#dfe6f5" : "#7d8aa5";
      ctx.beginPath();
      ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.globalAlpha = 1;
  }

  drawDisk(isDark) {
    const ctx = this.ctx;
    const r = this.orbitRadius(2) * 1.16;
    const gradient = ctx.createRadialGradient(this.cx(), this.cy(), r * 0.06, this.cx(), this.cy(), r);
    if (isDark) {
      gradient.addColorStop(0, "rgba(124,108,240,0.16)");
      gradient.addColorStop(0.42, "rgba(90,110,200,0.07)");
      gradient.addColorStop(1, "rgba(10,14,26,0)");
    } else {
      gradient.addColorStop(0, "rgba(124,108,240,0.14)");
      gradient.addColorStop(0.45, "rgba(120,140,210,0.07)");
      gradient.addColorStop(1, "rgba(230,236,247,0)");
    }
    ctx.save();
    ctx.translate(this.cx(), this.cy());
    ctx.scale(1, 0.7);
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fillStyle = gradient;
    ctx.fill();
    ctx.restore();
  }

  drawOrbits(isDark) {
    const ctx = this.ctx;
    ORBIT_TIERS.forEach((tier, index) => {
      const rx = this.orbitRadius(index);
      const ry = rx * 0.7;
      ctx.save();
      ctx.translate(this.cx(), this.cy());
      ctx.beginPath();
      ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
      ctx.strokeStyle = isDark ? "rgba(255,255,255,0.055)" : "rgba(16,24,40,0.07)";
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.beginPath();
      ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI);
      ctx.strokeStyle = isDark ? "rgba(255,255,255,0.13)" : "rgba(16,24,40,0.14)";
      ctx.lineWidth = 1.1;
      ctx.stroke();
      ctx.restore();
    });
  }

  drawSystem(galaxy, now, isDark) {
    if (!galaxy) return;
    this.drawCenter(galaxy.center, this.cx(), this.cy(), 1, 1, isDark, now);
    const sorted = galaxy.nodes.slice().sort((a, b) => Math.sin(a.angle) - Math.sin(b.angle));
    sorted.forEach((node) => {
      const born = node.born === undefined ? 1 : node.born;
      if (born <= 0.01) return;
      this.drawSatellite(node, born, isDark, now);
    });
  }

  drawTransition(now, isDark) {
    const tr = this.transition;
    if (!tr) return;
    const e = easeInOutCubic(tr.t);

    tr.outgoing.nodes.forEach((node) => {
      if (tr.clicked && node.id === tr.clicked.id) return;
      const fade = 1 - clamp(tr.t / 0.55, 0, 1);
      const born = clamp(1 - fade * 0.92, 0.08, 1);
      this.drawSatellite(node, born, isDark, now, 1 - fade * 0.9);
    });

    const oldCenterFade = 1 - clamp(tr.t / 0.5, 0, 1);
    if (oldCenterFade > 0.01) {
      this.drawCenter(tr.outgoing.center, this.cx(), this.cy(), 1 - e * 0.45, oldCenterFade, isDark, now);
    }

    if (tr.clicked) {
      const x = tr.startX + (this.cx() - tr.startX) * e;
      const y = tr.startY + (this.cy() - tr.startY) * e;
      const scale = 1 + e * 1.5;
      ctx_save(this.ctx);
      this.drawMoving(x, y, tr.startSize * scale, tr.startColor, isDark);
      ctx_restore(this.ctx);
    }

    if (e > 0.45) {
      const appear = clamp((e - 0.45) / 0.55, 0, 1);
      this.drawCenter(tr.incoming.center, this.cx(), this.cy(), 0.6 + appear * 0.4, appear, isDark, now);
    }

    tr.incoming.nodes.forEach((node) => {
      if (node.born <= 0.01) return;
      this.drawSatellite(node, node.born, isDark, now);
    });
  }

  drawMoving(x, y, size, color, isDark) {
    const ctx = this.ctx;
    const glow = ctx.createRadialGradient(x, y, 0, x, y, size * 4.2);
    glow.addColorStop(0, hexAlpha(color, 0.5));
    glow.addColorStop(0.45, hexAlpha(color, 0.16));
    glow.addColorStop(1, hexAlpha(color, 0));
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(x, y, size * 4.2, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = isDark ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.85)";
    ctx.beginPath();
    ctx.arc(x - size * 0.26, y - size * 0.3, size * 0.3, 0, Math.PI * 2);
    ctx.fill();
  }

  drawCenter(memory, x, y, scale, alpha, isDark, now) {
    const ctx = this.ctx;
    if (!memory) return;
    const pulse = 1 + Math.sin(now / 1400) * 0.045;
    const base = 13 * scale * pulse;
    const color = satelliteColor(memory);

    const halo = ctx.createRadialGradient(x, y, 0, x, y, base * 6);
    halo.addColorStop(0, hexAlpha(color, 0.34 * alpha));
    halo.addColorStop(0.3, hexAlpha(color, 0.13 * alpha));
    halo.addColorStop(1, hexAlpha(color, 0));
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(x, y, base * 6, 0, Math.PI * 2);
    ctx.fill();

    const core = ctx.createRadialGradient(x - base * 0.3, y - base * 0.34, base * 0.1, x, y, base);
    core.addColorStop(0, hexAlpha("#ffffff", 0.98 * alpha));
    core.addColorStop(0.42, hexAlpha(color, 0.95 * alpha));
    core.addColorStop(1, hexAlpha(color, 0.6 * alpha));
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(x, y, base, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = hexAlpha(color, 0.5 * alpha);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, base * 1.72, 0, Math.PI * 2);
    ctx.stroke();

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = isDark ? "rgba(242,245,250,0.9)" : "rgba(16,19,25,0.86)";
    ctx.font = '600 11px "Sarasa Gothic SC", "PingFang SC", system-ui, sans-serif';
    ctx.textAlign = "center";
    ctx.fillText(clip(memoryTitle(memory), 20), x, y + base * 1.72 + 16);
    ctx.font = '400 10px "JetBrains Mono", monospace';
    ctx.fillStyle = isDark ? "rgba(152,163,184,0.72)" : "rgba(85,96,122,0.78)";
    ctx.fillText(
      (TYPE_LABEL[compact(memory.memory_type)] || compact(memory.memory_type) || "记忆") +
        " · 重要 " + num(memory.importance),
      x,
      y + base * 1.72 + 30
    );
    ctx.restore();
  }

  drawSatellite(node, born, isDark, now, alphaOverride) {
    const ctx = this.ctx;
    const rx = this.orbitRadius(node.tier);
    const ry = rx * 0.7;
    const x = this.cx() + Math.cos(node.angle) * rx * (0.35 + 0.65 * born);
    const y = this.cy() + Math.sin(node.angle) * ry * (0.35 + 0.65 * born);
    const depth = this.depthOf(node.angle);
    const isHover = this.hoverId === node.id;
    const sizeScale = (0.74 + depth * 0.4) * (0.5 + 0.5 * born) * (isHover ? 1.42 : 1);
    const size = Math.max(2, node.size * sizeScale);
    const alpha = clamp((alphaOverride === undefined ? 0.48 + depth * 0.52 : alphaOverride) * born, 0, 1);

    const dir = node.tier % 2 === 0 ? 1 : -1;
    const rEff = (rx + ry) / 2;
    const step = (24 / Math.max(60, rEff)) * dir;
    const trailScale = [0.5, 0.37, 0.26, 0.17];
    const trailAlpha = [0.44, 0.3, 0.18, 0.09];
    for (let i = 0; i < 4; i += 1) {
      const ta = node.angle - step * (i + 1);
      const tx = this.cx() + Math.cos(ta) * rx * (0.35 + 0.65 * born);
      const ty = this.cy() + Math.sin(ta) * ry * (0.35 + 0.65 * born);
      const tDepth = this.depthOf(ta);
      ctx.globalAlpha = trailAlpha[i] * born * (0.55 + tDepth * 0.45);
      ctx.fillStyle = node.color;
      ctx.beginPath();
      ctx.arc(tx, ty, Math.max(0.8, size * trailScale[i]), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    const glowR = size * (isHover ? 5.4 : 3.6);
    const glow = ctx.createRadialGradient(x, y, 0, x, y, glowR);
    glow.addColorStop(0, hexAlpha(node.color, (isHover ? 0.55 : 0.34) * alpha));
    glow.addColorStop(1, hexAlpha(node.color, 0));
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(x, y, glowR, 0, Math.PI * 2);
    ctx.fill();

    ctx.globalAlpha = alpha;
    ctx.fillStyle = node.color;
    ctx.beginPath();
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = hexAlpha("#ffffff", 0.55 * alpha);
    ctx.beginPath();
    ctx.arc(x - size * 0.28, y - size * 0.32, size * 0.32, 0, Math.PI * 2);
    ctx.fill();

    if (isHover || born > 0.85) {
      ctx.globalAlpha = alpha * (isHover ? 1 : 0.62);
      ctx.strokeStyle = hexAlpha(node.color, isHover ? 0.9 : 0.4);
      ctx.lineWidth = isHover ? 1.4 : 1;
      ctx.beginPath();
      ctx.arc(x, y, size + (isHover ? 7 : 3.4), 0, Math.PI * 2);
      ctx.stroke();
    }

    if (isHover || born > 0.9) {
      ctx.globalAlpha = alpha;
      ctx.fillStyle = isDark ? "rgba(242,245,250,0.94)" : "rgba(16,19,25,0.9)";
      ctx.font = '500 10.5px "Sarasa Gothic SC", "PingFang SC", system-ui, sans-serif';
      ctx.textAlign = "center";
      ctx.fillText(clip(memoryTitle(node.memory), 16), x, y + size + 15);
    }
    ctx.globalAlpha = 1;
  }
}

function ctx_save(ctx) { ctx.save(); }
function ctx_restore(ctx) { ctx.restore(); }

function hexAlpha(hex, alpha) {
  const value = compact(hex).replace("#", "");
  const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value;
  const r = parseInt(full.slice(0, 2), 16) || 0;
  const g = parseInt(full.slice(2, 4), 16) || 0;
  const b = parseInt(full.slice(4, 6), 16) || 0;
  return "rgba(" + r + "," + g + "," + b + "," + clamp(alpha, 0, 1).toFixed(3) + ")";
}

/* ------------------------------------------------------------
   知识星图视图
   ------------------------------------------------------------ */
let galaxyInstance = null;

defineView("starmap", {
  title: "知识星图",
  navLabel: "知识星图",
  eyebrow: "Insight · Star Map",
  hint: "选中的记忆是中央恒星，关联记忆按强度落在内 / 中 / 外三条星轨上；点击卫星即可升为新的恒星",
  async load(options) {
    const opts = options || {};
    const pool = await loadPool();
    const centerId = opts.center || (state.starmap && state.starmap.centerId) || "";
    const galaxy = buildGalaxy(pool, centerId);
    return { galaxy, poolSize: pool.length };
  },
  render(data) {
    const galaxy = data.galaxy;
    if (!galaxy) {
      return emptyState("记忆库还是空的", "先产生一些记忆，星图才有可以围绕的恒星。");
    }
    const legend = ORBIT_TIERS.map(
      (tier) =>
        '<span class="legend-item" style="color:' + tier.color + '"><i></i><span style="color:var(--text-3)">' + esc(tier.label) + "</span></span>"
    ).join("");

    return (
      '<div class="starmap-wrap">' +
        '<div class="starmap-card" id="starmapCard">' +
          '<div class="starmap-hud"><span class="hud-title">知识星图</span>' +
            '<span class="hud-sub">' + fmtInt(data.poolSize) + " 条记忆参与关联计算 · 悬停暂停公转</span></div>" +
          '<div class="starmap-tools">' +
            '<button class="pill" type="button" id="starPauseBtn">暂停公转</button>' +
            '<button class="pill" type="button" id="starReseedBtn">换一颗恒星</button>' +
          "</div>" +
          '<canvas class="starmap-canvas" id="starmapCanvas"></canvas>' +
          '<div class="starmap-tip" id="starmapTip"></div>' +
          '<div class="star-legend">' + legend + "</div>" +
        "</div>" +
        '<div class="star-panel" id="starPanel">' + starPanelHtml(galaxy) + "</div>" +
      "</div>"
    );
  },
  mount(node, data) {
    const canvas = $("#starmapCanvas", node);
    if (!canvas) return;
    if (galaxyInstance) galaxyInstance.destroy();
    galaxyInstance = new GalaxyView(canvas);
    galaxyInstance.setGalaxy(data.galaxy);
    state.starmap = { centerId: data.galaxy.center.id };

    const tip = $("#starmapTip", node);

    galaxyInstance.onHover = (hoverNode, mx, my) => {
      galaxyInstance.paused = Boolean(hoverNode);
      if (!hoverNode) {
        tip.classList.remove("is-on");
        return;
      }
      const memory = hoverNode.memory;
      const weights = memory.persona_weights && typeof memory.persona_weights === "object" ? memory.persona_weights : {};
      const weightKeys = Object.keys(weights).slice(0, 4);
      tip.innerHTML =
        '<div class="tip-head">' +
          badge(typeLabel(memory), toneOfColor(hoverNode.color)) +
          badge("关联 " + num(hoverNode.score), "accent") +
        "</div>" +
        '<div class="tip-body">' + esc(clip(memoryTitle(memory), 62)) + "</div>" +
        (weightKeys.length
          ? '<div class="tip-weights">' + weightKeys.map((key) => badge((WEIGHT_LABEL[key] || key) + " " + num(weights[key]), "accent")).join("") + "</div>"
          : "") +
        '<div class="tip-hint">悬停暂停公转 · 点击升为恒星</div>';
      tip.style.left = clamp(mx, 130, galaxyInstance.w - 130) + "px";
      tip.style.top = my + "px";
      tip.classList.add("is-on");
    };

    galaxyInstance.onSelect = (selectedNode) => {
      if (!selectedNode) return;
      tip.classList.remove("is-on");
      go("starmap", { center: selectedNode.id });
    };

    const pauseBtn = $("#starPauseBtn", node);
    if (pauseBtn) {
      pauseBtn.addEventListener("click", () => {
        galaxyInstance.userPaused = !galaxyInstance.userPaused;
        if (galaxyInstance.userPaused) galaxyInstance.paused = true;
        pauseBtn.classList.toggle("is-active", galaxyInstance.userPaused);
        pauseBtn.textContent = galaxyInstance.userPaused ? "继续公转" : "暂停公转";
      });
    }
    const reseedBtn = $("#starReseedBtn", node);
    if (reseedBtn) {
      reseedBtn.addEventListener("click", () => {
        const pool = state.pool || [];
        if (!pool.length) return;
        const current = state.starmap ? state.starmap.centerId : "";
        const ranked = pool.slice().sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0));
        const next = ranked.find((m) => m.id !== current && m.id !== (data.galaxy.center && data.galaxy.center.id));
        if (next) go("starmap", { center: next.id });
      });
    }

    $$("[data-star-open]", node).forEach((button) => {
      button.addEventListener("click", () => openMemory(button.dataset.starOpen));
    });
  },
});

function toneOfColor(color) {
  const map = {
    "#f472b6": "relation",
    "#60a5fa": "fact",
    "#2dd4bf": "group",
    "#fb923c": "personal",
    "#fcd34d": "gold",
    "#7dd3fc": "external",
    "#a99bff": "private",
  };
  return map[color] || "accent";
}

function starPanelHtml(galaxy) {
  const center = galaxy.center;
  const weights = center.persona_weights && typeof center.persona_weights === "object" ? center.persona_weights : {};
  const weightKeys = Object.keys(weights).filter((key) => Number.isFinite(Number(weights[key])));
  const tags = Array.isArray(center.tags) ? center.tags : [];

  const paramRows = [
    ["记忆 ID", shortId(center.id)],
    ["类型", typeLabel(center) + "（" + compact(center.memory_type) + "）"],
    ["范围", (SCOPE_META[compact(center.scope)] ? SCOPE_META[compact(center.scope)].label : compact(center.scope)) || "-"],
    ["主体", compact(center.subject && center.subject.name) || "-"],
    ["重要性", num(center.importance)],
    ["置信度", num(center.confidence)],
    ["显著性", num(center.salience)],
    ["强化分", num(center.reinforcement_score)],
    ["注入次数", String(int(center.injection_count))],
    ["最近注入", compact(center.last_injected_at) ? fmtTime(center.last_injected_at) : "从未"],
    ["可见性", VISIBILITY_LABEL[compact(center.visibility)] || compact(center.visibility) || "-"],
    ["生命周期", LIFECYCLE_LABEL[compact(center.lifecycle)] || compact(center.lifecycle) || "-"],
    ["时效", VALIDITY_LABEL[compact(center.validity_status)] || compact(center.validity_status) || "-"],
    ["持久度", DURABILITY_LABEL[compact(center.durability)] || compact(center.durability) || "-"],
    ["敏感度", SENSITIVITY_LABEL[compact(center.sensitivity)] || compact(center.sensitivity) || "-"],
    ["现实层级", REALITY_LABEL[compact(center.reality_level)] || compact(center.reality_level) || "-"],
    ["可提及分", center.mentionability_score === null || center.mentionability_score === undefined ? "-" : num(center.mentionability_score)],
    ["关系阶段", compact(center.relationship_phase) || "-"],
    ["来源插件", compact(center.source_plugin) || "本插件"],
    ["导入批次", compact(center.import_batch_id) || "-"],
    ["会话", compact(center.session_id) || "-"],
    ["发生时间", compact(center.occurred_at_local) || fmtTime(center.occurred_at)],
    ["更新时间", compact(center.updated_at_local) || fmtTime(center.updated_at)],
  ]
    .map((row) => '<div class="param-row"><span>' + esc(row[0]) + "</span><div>" + esc(row[1]) + "</div></div>")
    .join("");

  const orbitRows = ORBIT_TIERS.map((tier, index) => {
    const nodes = galaxy.nodes.filter((node) => node.tier === index);
    return (
      '<div style="margin-bottom:4px"><div class="orbit-row" style="cursor:default;background:transparent;padding:4px 2px">' +
      '<i style="background:' + tier.color + '"></i><b style="color:var(--text-2)">' + esc(tier.label) + "</b>" +
      "<span>" + nodes.length + " 颗卫星</span></div>" +
      (nodes.length
        ? '<div style="display:grid;gap:3px;padding-left:14px">' +
          nodes
            .slice(0, 6)
            .map(
              (node) =>
                '<button class="orbit-row" type="button" data-star-open="' + esc(node.id) + '">' +
                '<i style="background:' + node.color + '"></i>' +
                "<span>" + esc(clip(memoryTitle(node.memory), 22)) + "</span>" +
                "<em>" + num(node.score) + "</em></button>"
            )
            .join("") +
          "</div>"
        : "") +
      "</div>"
    );
  }).join("");

  return (
    '<section class="star-core">' +
      '<span class="core-kicker">当前恒星 · 关联 ' + galaxy.nodes.length + " 条</span>" +
      '<h3 class="core-title">' + esc(clip(memoryTitle(center), 46)) + "</h3>" +
      '<p class="core-content">' + esc(clip(compact(center.content), 220)) + "</p>" +
      '<div class="pill-row" style="margin-top:11px;position:relative">' +
        badge(typeLabel(center), toneOfColor(satelliteColor(center))) +
        badge("重要 " + num(center.importance), "accent") +
        '<button class="btn is-sm is-ghost" type="button" data-star-open="' + esc(center.id) + '">完整参数</button>' +
      "</div>" +
    "</section>" +
    card(
      "选中记忆 · 参数明细",
      weightKeys.length ? "含 " + weightKeys.length + " 项人格权重" : "基础属性",
      '<div class="star-params">' + paramRows + "</div>" +
        (weightKeys.length
          ? '<div class="tag-row" style="margin-top:10px">' + weightKeys.map((key) => badge((WEIGHT_LABEL[key] || key) + " " + num(weights[key]), "accent")).join("") + "</div>"
          : "") +
        (tags.length ? '<div class="tag-row" style="margin-top:8px">' + tags.map((tag) => badge(tag, "fact")).join("") + "</div>" : "")
    ) +
    card("星轨构成", "点击任一行查看该记忆", orbitRows || emptyState("暂无关联记忆", "这条记忆与其他记忆没有足够的属性重合。"))
  );
}

/* ============================================================
   视图：记忆显微镜
   ============================================================ */
const microState = { query: "", scope: "all", userId: "", groupId: "", topK: 8 };
let microResult = null;

function jsonPreview(value, maxDepth) {
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > 4200 ? text.slice(0, 4200) + "\n…（已截断）" : text;
  } catch (error) {
    return String(value);
  }
}

defineView("microscope", {
  title: "记忆显微镜",
  navLabel: "记忆显微镜",
  eyebrow: "Insight · Microscope",
  hint: "模拟一次真实召回：看哪些记忆被选中、拿到多少分，以及哪些被过滤掉",
  async load() {
    return { result: microResult, form: microState };
  },
  render(data) {
    const form = data.form || microState;
    const result = data.result;

    const queryPanel =
      '<div class="config-form">' +
      '<label class="field"><span>模拟提问</span><textarea id="microQuery" rows="4" placeholder="例如：你最近写了什么 / 那个蓝色渐变小猪是什么">' +
      esc(form.query) + "</textarea></label>" +
      '<label class="field"><span>检索范围</span><select id="microScope">' +
        [["all", "全部可检索记忆（管理检索）"], ["private", "指定私聊窗口"], ["group", "指定群聊窗口"]]
          .map((row) => '<option value="' + row[0] + '"' + (form.scope === row[0] ? " selected" : "") + ">" + row[1] + "</option>")
          .join("") +
      "</select></label>" +
      '<label class="field is-inline"><span>用户 ID</span><input id="microUser" type="text" value="' + esc(form.userId) + '" placeholder="私聊时填写" /></label>' +
      '<label class="field is-inline"><span>群 ID</span><input id="microGroup" type="text" value="' + esc(form.groupId) + '" placeholder="群聊时填写" /></label>' +
      '<label class="field is-inline"><span>召回条数</span><input id="microTopK" type="number" min="1" max="50" value="' + int(form.topK || 8) + '" /></label>' +
      '<div class="pill-row"><button class="btn is-primary" type="button" id="microRunBtn">开始检索</button>' +
      '<button class="btn is-ghost" type="button" id="microClearBtn">清空结果</button></div>' +
      "</div>";

    let hits = emptyState("还没有检索结果", "输入一句模拟提问，看看记忆库会召回什么。");
    let blocked = emptyState("暂无过滤记录", "召回过程中被 ACL、作用域或策略拦截的记忆会列在这里。");
    let retrieval = "";

    if (result) {
      const rows = Array.isArray(result.results) ? result.results : [];
      hits = rows.length
        ? rows
            .map((memory, index) => {
              const tone = memoryTone(memory);
              return (
                '<button class="hit" type="button" data-memory="' + esc(memory.id) + '" data-rank="' + (index + 1) + '">' +
                '<span class="hit-rank">' + (index + 1) + "</span>" +
                '<span class="hit-main"><span class="hit-content">' + esc(clip(memoryTitle(memory), 110)) + "</span>" +
                '<span class="hit-meta">' +
                  badge(typeLabel(memory), tone || "fact") +
                  badge(VISIBILITY_LABEL[compact(memory.visibility)] || compact(memory.visibility) || "-") +
                  (compact(memory.reason) ? badge(clip(memory.reason, 24)) : "") +
                  '<span class="hit-score">' + num(memory.score) + "</span>" +
                "</span></span></button>"
              );
            })
            .join("")
        : emptyState("没有召回任何记忆", "这句话没有命中记忆库，可以换个说法或放宽范围再试。");

      const blockedRows = Array.isArray(result.blocked) ? result.blocked : [];
      blocked = blockedRows.length
        ? blockedRows
            .slice(0, 12)
            .map((item) => {
              const text =
                typeof item === "string"
                  ? item
                  : compact(item.reason) || compact(item.memory_type) || jsonPreview(item);
              const title =
                typeof item === "object" && item !== null
                  ? clip(compact(item.content) || compact(item.title) || compact(item.id), 60)
                  : "";
              return '<div class="block-row"><span>' + esc(text) + (title ? "<br /><b>" + esc(title) + "</b>" : "") + "</span></div>";
            })
            .join("")
        : emptyState("没有过滤记录", "本次召回没有记忆被拦截。");

      const info = result.retrieval || {};
      const slotCounts = info.slot_counts || {};
      retrieval =
        '<dl class="kv" style="margin-bottom:10px">' +
        "<dt>检索模式</dt><dd>" + esc(compact((result.search_context || {}).mode) || "-") + "</dd>" +
        "<dt>编排</dt><dd>" + (info.orchestration_enabled ? "已启用" : "未启用") + "</dd>" +
        "<dt>Top K</dt><dd>" + int(info.top_k) + "</dd>" +
        "<dt>命中</dt><dd>" + ((result.results || []).length) + " 条</dd>" +
        "</dl>" +
        (Object.keys(slotCounts).length
          ? '<div class="tag-row">' + Object.keys(slotCounts).map((slot) => badge(slot + " " + int(slotCounts[slot]), "accent")).join("") + "</div>"
          : "") +
        ((info.capped_slots || []).length
          ? '<div class="tag-row" style="margin-top:6px">' + info.capped_slots.map((slot) => badge("受限 " + slot, "warn")).join("") + "</div>"
          : "");
    }

    return (
      '<div class="micro-grid">' +
      card("召回测试", "模拟一次真实提问", queryPanel + (retrieval ? '<div style="margin-top:14px">' + retrieval + "</div>" : "")) +
      card("命中记忆", result ? (result.results || []).length + " 条" : "待运行", '<div class="row-list">' + hits + "</div>") +
      card("过滤原因", "被拦截的记忆", '<div style="display:grid;gap:6px">' + blocked + "</div>") +
      "</div>"
    );
  },
  mount(node) {
    const run = async () => {
      microState.query = $("#microQuery", node).value.trim();
      microState.scope = $("#microScope", node).value;
      microState.userId = $("#microUser", node).value.trim();
      microState.groupId = $("#microGroup", node).value.trim();
      microState.topK = int($("#microTopK", node).value) || 8;
      if (!microState.query) {
        toast("请先输入一句模拟提问", "error");
        return;
      }
      await withBusy("正在召回…", async () => {
        microResult = await apiPost("/search", {
          query: microState.query,
          scope: microState.scope === "all" ? "unknown" : microState.scope,
          user_id: microState.userId,
          group_id: microState.groupId,
          top_k: microState.topK,
          context_mode: microState.scope === "all" ? "all" : "session",
        });
        toast("召回完成", "ok");
        go("microscope");
      });
    };
    $("#microRunBtn", node).addEventListener("click", run);
    $("#microClearBtn", node).addEventListener("click", () => {
      microResult = null;
      go("microscope");
    });
    $$("[data-memory]", node).forEach((row) => {
      row.addEventListener("click", () => openMemory(row.dataset.memory));
    });
  },
});

/* ============================================================
   视图：互动协同
   ============================================================ */
defineView("synergy", {
  title: "互动协同",
  navLabel: "互动协同",
  eyebrow: "Insight · Synergy",
  hint: "表达权威归属、记忆触动趋势与情绪连续性 —— 只读，由陪伴插件主导",
  async load() {
    const [persona, coord] = await Promise.all([
      apiTry(() => apiGet("/persona-state"), null),
      apiTry(() => apiGet("/coordination/status"), { status: {} }),
    ]);
    return { persona, coord: (coord && coord.status) || {} };
  },
  render(data) {
    const persona = data.persona;
    if (!persona) {
      return card("互动协同不可用", "读取失败", emptyState("无法读取互动协同数据", "请确认插件运行正常后重试。"));
    }
    const expr = persona.expression_coordination || {};
    const trends = Array.isArray(persona.memory_touch_trends) ? persona.memory_touch_trends : [];
    const events = Array.isArray(persona.memory_touch_events) ? persona.memory_touch_events : [];
    const cross = persona.cross_window_emotional_state || {};
    const legacyLabels = persona.legacy_context_labels || {};
    const todLabels = persona.time_of_day_labels || {};

    const authority =
      '<dl class="kv">' +
      "<dt>契约</dt><dd>" + esc(compact(expr.contract) || "-") + "</dd>" +
      "<dt>模式</dt><dd>" + esc(compact(expr.mode) || "-") + "</dd>" +
      "<dt>表达权威</dt><dd>" + badge(compact(expr.expression_authority) || "-", "accent") + "</dd>" +
      "<dt>记忆角色</dt><dd>" + esc(compact(expr.memory_role) || "-") + "</dd>" +
      "<dt>是否持久化</dt><dd>" + (expr.persistent ? "是" : "否（请求级只读）") + "</dd>" +
      "</dl>";

    const trendRows = trends.length
      ? trends
          .slice(0, 10)
          .map((item) => {
            const tone = item.trend_band === "rising" ? "ok" : item.trend_band === "cooling" ? "warn" : "";
            const bandLabel = item.trend_band === "rising" ? "升温" : item.trend_band === "cooling" ? "降温" : "平稳";
            return (
              '<button class="row" type="button" style="cursor:default">' +
              '<div class="row-main"><div class="row-title">' + esc(clip(compact(item.session_label), 46)) + "</div>" +
              '<div class="row-sub">' + esc(legacyLabels[compact(item.legacy_context)] || compact(item.legacy_context) || "未定阶段") +
              " · 触动 " + int(item.touch_count) + " 次</div></div>" +
              '<div class="row-meta">' + badge(bandLabel, tone) + badge(fmtTime(item.updated_at)) + "</div></button>"
            );
          })
          .join("")
      : emptyState("暂无触动趋势", "还没有记录到记忆被表达层触动的趋势。");

    const eventRows = events.length
      ? events
          .slice(0, 10)
          .map(
            (item) =>
              '<div class="row" style="cursor:default;align-items:flex-start"><div class="row-main">' +
              '<div class="row-title">' + esc(compact(item.event_type) || "情绪事件") + " · " + esc(compact(item.mood_hint) || "—") + "</div>" +
              '<div class="row-sub">' + esc(clip(compact(item.content_preview), 56)) + (compact(item.energy_delta) ? " · 能量 " + num(item.energy_delta) : "") + "</div>" +
              "</div>" + badge(shortId(item.session_id)) + "</div>"
          )
          .join("")
      : emptyState("暂无情绪事件", "近期没有记录到情绪事件。");

    const crossCards = [
      kpi("跨窗口总量", fmtInt(cross.total), "", "accent"),
      kpi("伤痕", fmtInt(cross.scar_count), "scar", "relation"),
      kpi("温暖", fmtInt(cross.warm_count), "warm", "personal"),
      kpi("脆弱", fmtInt(cross.vulnerable_count), "vulnerable", "fact"),
    ].join("");

    const coordStatus = data.coord || {};
    const bridge = coordStatus.bridge || {};
    const links = [
      bridge.health === "ready" ? "is-ok" : bridge.health === "degraded" ? "is-warn" : "is-bad",
      "陪伴桥接",
      compact(bridge.reason_code) || compact(bridge.health) || "未知",
    ];

    return (
      '<div class="grid" style="gap:16px">' +
      '<div class="section-label"><h2>表达协同</h2><span class="section-note">当前时段：' + esc(todLabels[compact(persona.time_of_day)] || compact(persona.time_of_day) || "未知") + "</span></div>" +
      '<div class="grid split-2">' +
        card("表达权威", "谁决定怎么说话", authority) +
        '<div style="display:grid;gap:16px">' +
          card("记忆触动趋势", trends.length + " 个窗口", '<div class="row-list">' + trendRows + "</div>") +
          card("联动状态", "", '<div class="row-list"><div class="link-item ' + links[0] + '"><span class="link-dot"></span><b>' + esc(links[1]) + "</b><span>" + esc(links[2]) + "</span></div></div>") +
        "</div>" +
      "</div>" +
      '<div class="kpi-row">' + crossCards + "</div>" +
      card("近期情绪事件", events.length + " 条 · 只读投影", '<div class="row-list">' + eventRows + "</div>") +
      "</div>"
    );
  },
});

/* ============================================================
   视图：陪伴插件联动
   ============================================================ */
defineView("companion", {
  title: "陪伴插件联动",
  navLabel: "陪伴插件",
  eyebrow: "Bridge · Companion",
  hint: "主动陪伴插件的桥接状态、能力开关与个人记忆产出",
  async load() {
    const [caps, coord, personal] = await Promise.all([
      apiTry(() => apiGet("/capabilities/bot-personal"), null),
      apiTry(() => apiGet("/coordination/status"), { status: {} }),
      apiTry(() => apiGet("/companion/personal-memory?limit=40"), null),
    ]);
    return { caps, coord: (coord && coord.status) || {}, personal };
  },
  render(data) {
    const caps = data.caps || {};
    const coord = data.coord || {};
    const bridge = coord.bridge || {};
    const available = caps.available === true || (data.personal && data.personal.available === true);

    const items = [];
    items.push([
      available ? "is-ok" : "is-bad",
      "插件加载",
      available ? compact(caps.plugin_name) || "astrbot_plugin_private_companion" : compact(caps.reason) || "未检测到",
    ]);
    items.push([
      bridge.health === "ready" ? "is-ok" : bridge.health === "degraded" ? "is-warn" : "is-bad",
      "桥接健康度",
      compact(bridge.health) || "未知",
    ]);
    items.push([
      caps.daily_plan_enabled ? "is-ok" : "is-warn",
      "每日日程",
      caps.daily_plan_enabled ? "已启用" : "未启用",
    ]);
    items.push([
      caps.detail_enabled ? "is-ok" : "is-warn",
      "细化增强",
      caps.detail_enabled ? "已启用" : "未启用",
    ]);
    if (data.personal && data.personal.available) {
      items.push(["is-ok", "可选日期", (data.personal.dates || []).length + " 天有记录"]);
      items.push(["is-ok", "相册", ((data.personal.snapshot || {}).album || []).length + " 张"]);
    }

    const bridgeReason = compact(bridge.reason_code);
    const p6 = coord.p6 || coord.p6_status || null;

    return (
      '<div class="grid" style="gap:16px">' +
      '<div class="grid split-2">' +
        card(
          "联动状态",
          available ? "已连接" : "未连接",
          '<div class="row-list" style="gap:6px">' +
            items.map((item) => '<div class="link-item ' + item[0] + '"><span class="link-dot"></span><b>' + esc(item[1]) + "</b><span>" + esc(item[2]) + "</span></div>").join("") +
            "</div>" +
            (bridgeReason ? '<p style="margin-top:12px;font-size:11.5px;color:var(--text-3)">原因码：' + esc(bridgeReason) + "</p>" : "") +
            '<div class="pill-row" style="margin-top:12px"><button class="btn is-sm" type="button" data-goto="botlife">查看 Bot 日程与相册</button></div>'
        ) +
        card(
          "协调契约",
          "只读投影 · 不在本插件持久化",
          '<dl class="kv">' +
            "<dt>契约版本</dt><dd>" + esc(compact(coord.contract) || "companion_coordination.v1") + "</dd>" +
            "<dt>兼容等级</dt><dd>" + esc(compact(coord.compatibility_level) || "-") + "</dd>" +
            "<dt>桥接状态</dt><dd>" + esc(compact(bridge.health) || "-") + "</dd>" +
            "<dt>表达权威</dt><dd>private_companion</dd>" +
            "<dt>记忆角色</dt><dd>召回可见性与提及上限</dd>" +
            (p6 ? "<dt>P6 状态</dt><dd>" + esc(compact(p6.health) || compact(p6.state) || "-") + "</dd>" : "") +
            "</dl>"
        ) +
      "</div>" +
      (p6
        ? card("P6 只读状态", "由陪伴插件产出", '<pre style="margin:0;font-size:11.5px;line-height:1.6;color:var(--text-2);white-space:pre-wrap;word-break:break-all">' + esc(jsonPreview(p6)) + "</pre>")
        : "") +
      "</div>"
    );
  },
});

/* ============================================================
   视图：外部接口记忆
   ============================================================ */
defineView("external", {
  title: "外部接口记忆",
  navLabel: "外部接口",
  eyebrow: "Bridge · External",
  hint: "由其他插件经 bridge 写入的记忆，按来源插件归类并可单独检索",
  async load() {
    const pool = await loadPool();
    const external = pool.filter((memory) => {
      const source = compact(memory.source_plugin);
      return source && source !== "self" && source !== "astrbot_plugin_memory_companion";
    });
    const bySource = {};
    external.forEach((memory) => {
      const source = compact(memory.source_plugin);
      bySource[source] = bySource[source] || { count: 0, types: {}, latest: "" };
      bySource[source].count += 1;
      const type = compact(memory.memory_type) || "unknown";
      bySource[source].types[type] = (bySource[source].types[type] || 0) + 1;
      const ts = compact(memory.created_at);
      if (ts > bySource[source].latest) bySource[source].latest = ts;
    });
    return { external, bySource, poolSize: pool.length, capped: external.length >= pool.length && pool.length >= 800 };
  },
  render(data) {
    const external = data.external || [];
    const bySource = data.bySource || {};
    const sources = Object.keys(bySource).sort((a, b) => bySource[b].count - bySource[a].count);

    const sourceCards = sources.length
      ? sources
          .map((source) => {
            const info = bySource[source];
            const types = Object.entries(info.types)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3)
              .map((entry) => (TYPE_LABEL[entry[0]] || entry[0]) + " " + entry[1])
              .join(" · ");
            return (
              '<button class="scope-card" type="button" data-tone="external" data-goto="inspect" data-filter="external:' + esc(source) + '">' +
              '<div class="scope-top">' + icon("plug", "scope-icon") + '<span class="scope-count">' + fmtInt(info.count) + " 条</span></div>" +
              '<div class="scope-body"><div class="scope-name">' + esc(source) + "</div>" +
              '<div class="scope-desc">' + esc(types || "无类型信息") + "</div></div>" +
              '<div class="scope-bar"><i style="width:' + ((info.count / Math.max(1, external.length)) * 100).toFixed(1) + '%"></i></div>' +
              '<div class="scope-foot"><span>最近 ' + esc(fmtDate(info.latest)) + "</span><span>查看 ›</span></div></button>"
            );
          })
          .join("")
      : emptyState("没有外部写入的记忆", "其他插件通过 bridge 写入记忆后，会按来源插件归类显示在这里。");

    const rows = external.length
      ? external
          .slice(0, 60)
          .map((memory) => memoryRow(memory))
          .join("")
      : "";

    return (
      '<div class="grid" style="gap:16px">' +
      (data.capped
        ? card("抽样提示", "", '<p style="font-size:12px;color:var(--text-2)">当前统计基于最近 ' + fmtInt(data.poolSize) + " 条记忆抽样，实际数量可能更多。</p>")
        : "") +
      '<div class="section-label"><h2>来源插件</h2><span class="section-note">' + sources.length + " 个来源 · 共 " + fmtInt(external.length) + " 条</span></div>" +
      '<div class="grid g3">' + sourceCards + "</div>" +
      (rows ? card("最近写入", "最多显示 60 条", '<div class="row-list">' + rows + "</div>") : "") +
      "</div>"
    );
  },
  mount(node) {
    $$("[data-memory]", node).forEach((row) => {
      row.addEventListener("click", () => openMemory(row.dataset.memory));
    });
  },
});

/* ============================================================
   视图：历史聊天导入
   ============================================================ */
const importState = { tab: "qq", caps: null, preview: null, status: null, batchId: "" };

function previewSummary(result) {
  if (!result || typeof result !== "object") return "";
  const stats = result.stats && typeof result.stats === "object" ? result.stats : {};
  const speakers = Array.isArray(stats.speakers) ? stats.speakers : Object.keys(stats.speakers || {});
  const pairs = [
    ["来源", compact(result.source_name)],
    ["类型", compact(result.source_kind)],
    ["消息数", int(stats.message_count ?? stats.messages ?? stats.total ?? 0)],
    ["说话人", speakers.length ? speakers.join(" / ") : "-"],
    ["时间跨度", compact(stats.first_time) && compact(stats.last_time) ? compact(stats.first_time) + " → " + compact(stats.last_time) : "-"],
    ["截断", result.truncated ? "是" : "否"],
  ].filter((row) => row[1] !== "" && row[1] !== "-" || row[0] === "截断");
  return '<dl class="kv">' + pairs.map((row) => "<dt>" + esc(row[0]) + "</dt><dd>" + esc(row[1]) + "</dd>").join("") + "</dl>";
}

function speakerConfirmHtml(result) {
  const stats = (result && result.stats && typeof result.stats === "object" ? result.stats : {});
  const speakers = Array.isArray(stats.speakers) ? stats.speakers : Object.keys(stats.speakers || {});
  const suggestions = Array.isArray(result.speaker_suggestions) ? result.speaker_suggestions : [];
  const identity = (result && result.identity_context && typeof result.identity_context === "object") ? result.identity_context : {};
  const matches = identity.matches && typeof identity.matches === "object" ? identity.matches : {};
  const botInfo = identity.bot && typeof identity.bot === "object" ? identity.bot : {};

  const rows = speakers
    .map((speaker) => {
      const suggestion = suggestions.find((item) => compact(item.speaker) === compact(speaker));
      const role = compact(suggestion && suggestion.role) || (matches[speaker] ? "bot" : "user");
      const entity = compact(suggestion && suggestion.entity_id) || compact(matches[speaker] && (matches[speaker].entity_id || matches[speaker].id)) || "";
      return (
        '<div class="acl-row" style="grid-template-columns:minmax(0,1fr) 110px minmax(0,1fr)">' +
        '<div class="acl-node"><b>' + esc(speaker) + "</b></div>" +
        '<select data-speaker="' + esc(speaker) + '" class="speaker-role" style="height:30px;padding:0 8px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:12px">' +
          '<option value="user"' + (role === "bot" ? "" : " selected") + ">用户</option>" +
          '<option value="bot"' + (role === "bot" ? " selected" : "") + ">Bot</option>" +
        "</select>" +
        '<input data-speaker-id="' + esc(speaker) + '" class="speaker-entity" type="text" value="' + esc(entity) + '" placeholder="实体 ID（可留空）" style="height:30px;padding:0 8px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:12px" />' +
        "</div>"
      );
    })
    .join("");

  return (
    '<div class="section-label" style="margin-top:4px"><h2>确认身份</h2><span class="section-note">必须恰好一个 Bot，至少一个用户</span></div>' +
    (rows || '<p class="section-note">未能解析出说话人。</p>') +
    '<div class="grid g3" style="margin-top:12px">' +
      '<label class="field"><span>目标用户 ID</span><input id="impUserId" type="text" placeholder="例如 QQ 号" /></label>' +
      '<label class="field"><span>目标用户名称</span><input id="impUserName" type="text" placeholder="可留空" /></label>' +
      '<label class="field"><span>目标 Bot ID</span><input id="impBotId" type="text" placeholder="多 Bot 时必填" value="' + esc(compact(botInfo.bot_id) || compact(botInfo.id)) + '" /></label>' +
      '<label class="field"><span>平台</span><input id="impPlatform" type="text" value="qq" /></label>' +
      '<label class="field"><span>会话 ID</span><input id="impSession" type="text" placeholder="留空自动推断" /></label>' +
    "</div>" +
    '<div class="pill-row" style="margin-top:12px">' +
      '<button class="btn is-primary" type="button" id="impStartBtn">开始生成记忆</button>' +
      '<button class="btn is-ghost" type="button" id="impDiscardBtn">放弃预览</button>' +
    "</div>"
  );
}

defineView("chatimport", {
  title: "历史聊天导入",
  navLabel: "历史聊天",
  eyebrow: "Import · Chat",
  hint: "从当前 QQ 连接读取时段记录，或导入已有聊天文件，确认身份后再生成记忆",
  async load() {
    if (importState.tab === "qq" && !importState.caps) {
      importState.caps = await apiTry(() => apiGet("/conversation-import/qq/capabilities"), null);
    }
    if (importState.batchId) {
      importState.status = await apiTry(
        () => apiGet("/conversation-import/status?batch_id=" + encodeURIComponent(importState.batchId)),
        null
      );
    }
    return { caps: importState.caps, preview: importState.preview, status: importState.status, tab: importState.tab };
  },
  render(data) {
    const caps = data.caps || {};
    const platforms = Array.isArray(caps.platforms) ? caps.platforms : [];
    const available = caps.available === true || platforms.length > 0;

    const qqPanel =
      '<div class="config-form">' +
      '<label class="field"><span>当前 Bot 连接</span><select id="qqPlatform"' + (available ? "" : " disabled") + ">" +
        (platforms.length
          ? platforms.map((p) => '<option value="' + esc(compact(p.platform_id) || compact(p.id)) + '">' + esc(compact(p.name) || compact(p.platform_id) || compact(p.id)) + "</option>").join("")
          : '<option value="">等待能力检测</option>') +
      "</select></label>" +
      '<label class="field"><span>目标好友 QQ</span><input id="qqUserId" type="text" inputmode="numeric" placeholder="输入纯数字 QQ 号" /></label>' +
      '<div class="grid g2" style="gap:10px">' +
        '<label class="field"><span>开始时间</span><input id="qqStart" type="datetime-local" /></label>' +
        '<label class="field"><span>结束时间</span><input id="qqEnd" type="datetime-local" /></label>' +
      "</div>" +
      '<div class="pill-row">' +
        '<button class="btn is-sm is-ghost" type="button" id="qqCapBtn">重新检测</button>' +
        '<button class="btn is-primary" type="button" id="qqPreviewBtn">读取并生成预览</button>' +
      "</div>" +
      (caps.available === false ? '<p class="section-note">' + esc(compact(caps.reason) || "当前连接不支持读取历史") + "</p>" : "") +
      "</div>";

    const filePanel =
      '<div class="config-form">' +
      '<label class="dropzone" id="fileDrop" for="fileInput">' +
        '<span aria-hidden="true" style="font-size:20px">＋</span>' +
        "<b>拖入聊天记录，或点击选择文件</b>" +
        "<small>支持 TXT、LOG、Markdown 和 QQChatExporter 私聊 JSON，最大 8 MiB</small>" +
      "</label>" +
      '<input id="fileInput" type="file" accept=".txt,.log,.md,.json,text/plain,text/markdown,application/json" style="display:none" />' +
      '<label class="field is-inline"><span>缺失年份</span><input id="fileBaseYear" type="number" min="1970" max="2200" placeholder="通常留空" /></label>' +
      '<div class="pill-row"><button class="btn is-primary" type="button" id="filePreviewBtn" disabled>解析并预览</button></div>' +
      '<p class="section-note" id="fileMeta">尚未选择文件</p>' +
      "</div>";

    const recentPanel =
      '<div class="config-form">' +
      '<div class="pill-row"><button class="btn is-sm" type="button" id="recentRefreshBtn">刷新状态</button></div>' +
      '<div id="recentList"><p class="section-note">点击刷新读取当前导入状态。</p></div>' +
      "</div>";

    const tabs = [
      ["qq", "QQ 直接读取"],
      ["file", "文件导入"],
      ["recent", "最近任务"],
    ]
      .map((item) => '<button class="pill' + (data.tab === item[0] ? " is-active" : "") + '" type="button" data-tab="' + item[0] + '">' + esc(item[1]) + "</button>")
      .join("");

    const output = data.preview
      ? card(
          "预览结果",
          compact(data.preview.source_name),
          previewSummary(data.preview) +
            ((data.preview.warnings || []).length
              ? '<div class="tag-row" style="margin-top:8px">' + data.preview.warnings.map((w) => badge(clip(w, 40), "warn")).join("") + "</div>"
              : "") +
            speakerConfirmHtml(data.preview)
        )
      : emptyState("预览会显示在这里", "先选择 QQ 时段或聊天文件。系统只会在你确认身份后开始生成记忆。");

    const statusCard = data.status
      ? card("导入进度", compact(data.status.state) || "进行中", '<pre style="margin:0;font-size:11.5px;line-height:1.6;color:var(--text-2);white-space:pre-wrap;word-break:break-all">' + esc(jsonPreview(data.status.result || data.status)) + "</pre>" +
          (importState.batchId
            ? '<div class="pill-row" style="margin-top:12px">' +
              '<button class="btn is-sm" type="button" id="impPauseBtn">暂停</button>' +
              '<button class="btn is-sm" type="button" id="impResumeBtn">继续</button>' +
              '<button class="btn is-sm is-danger" type="button" id="impRollbackBtn">回滚批次</button>' +
              "</div>"
            : ""))
      : "";

    return (
      '<div class="grid" style="gap:16px">' +
      '<div class="section-label"><h2>选择来源</h2><span class="section-note">两种来源共用身份确认与记忆整理流程</span></div>' +
      '<div class="pill-row">' + tabs + "</div>" +
      '<div class="grid split-2">' +
        card(
          data.tab === "qq" ? "QQ 直接读取" : data.tab === "file" ? "文件导入" : "最近任务",
          data.tab === "qq" ? "通过 NapCat / aiocqhttp 好友历史接口读取" : data.tab === "file" ? "适合接口不可用或已有导出文件" : "查看、继续或回滚批次",
          data.tab === "qq" ? qqPanel : data.tab === "file" ? filePanel : recentPanel
        ) +
        '<div style="display:grid;gap:16px">' + output + statusCard + "</div>" +
      "</div>" +
      "</div>"
    );
  },
  mount(node) {
    $$("[data-tab]", node).forEach((button) => {
      button.addEventListener("click", () => {
        importState.tab = button.dataset.tab;
        go("chatimport");
      });
    });

    const qqCap = $("#qqCapBtn", node);
    if (qqCap) {
      qqCap.addEventListener("click", async () => {
        await withBusy("正在检测能力…", async () => {
          importState.caps = await apiTry(() => apiGet("/conversation-import/qq/capabilities"), null);
          toast("能力检测完成", "ok");
          go("chatimport");
        });
      });
    }

    const qqPreview = $("#qqPreviewBtn", node);
    if (qqPreview) {
      qqPreview.addEventListener("click", async () => {
        const payload = {
          platform_id: $("#qqPlatform", node).value,
          user_id: $("#qqUserId", node).value.trim(),
          start_at: $("#qqStart", node).value,
          end_at: $("#qqEnd", node).value,
        };
        if (!payload.user_id) {
          toast("请填写目标好友 QQ", "error");
          return;
        }
        await withBusy("正在读取历史…", async () => {
          const result = await apiPost("/conversation-import/qq/preview", payload);
          importState.preview = result.result || result;
          toast("预览已生成", "ok");
          go("chatimport");
        });
      });
    }

    const fileInput = $("#fileInput", node);
    if (fileInput) {
      fileInput.addEventListener("change", () => {
        const file = fileInput.files && fileInput.files[0];
        const meta = $("#fileMeta", node);
        const btn = $("#filePreviewBtn", node);
        if (!file) return;
        meta.textContent = file.name + " · " + (file.size / 1048576).toFixed(2) + " MiB";
        btn.disabled = false;
      });
    }

    const filePreview = $("#filePreviewBtn", node);
    if (filePreview) {
      filePreview.addEventListener("click", async () => {
        const file = fileInput.files && fileInput.files[0];
        if (!file) return;
        const buffer = await file.arrayBuffer();
        let binary = "";
        const bytes = new Uint8Array(buffer);
        for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
        await withBusy("正在解析文件…", async () => {
          const result = await apiPost("/conversation-import/upload", {
            filename: file.name,
            content_base64: window.btoa(binary),
            base_year: int($("#fileBaseYear", node).value) || 0,
          });
          importState.preview = result.result || result;
          toast("预览已生成", "ok");
          go("chatimport");
        });
      });
    }

    const recentRefresh = $("#recentRefreshBtn", node);
    if (recentRefresh) {
      recentRefresh.addEventListener("click", async () => {
        await withBusy("正在读取状态…", async () => {
          const result = await apiTry(() => apiGet("/conversation-import/status"), null);
          const list = $("#recentList", node);
          const payload = result && result.result ? result.result : result;
          list.innerHTML =
            '<pre style="margin:0;font-size:11.5px;line-height:1.6;color:var(--text-2);white-space:pre-wrap;word-break:break-all">' +
            esc(jsonPreview(payload)) +
            "</pre>";
        });
      });
    }

    const startBtn = $("#impStartBtn", node);
    if (startBtn) {
      startBtn.addEventListener("click", async () => {
        const speakerMap = {};
        $$(".speaker-role", node).forEach((select) => {
          const idInput = $('[data-speaker-id="' + CSS.escape(select.dataset.speaker) + '"]', node);
          speakerMap[select.dataset.speaker] = {
            role: select.value,
            entity_id: idInput ? idInput.value.trim() : "",
            display_name: select.dataset.speaker,
          };
        });
        const payload = {
          upload_id: compact(importState.preview.upload_id),
          speaker_map: speakerMap,
          user_id: $("#impUserId", node).value.trim(),
          user_name: $("#impUserName", node).value.trim(),
          bot_id: $("#impBotId", node).value.trim(),
          bot_name: "Bot",
          platform: $("#impPlatform", node).value.trim() || "qq",
          session_id: $("#impSession", node).value.trim(),
        };
        if (!payload.user_id || !payload.bot_id) {
          toast("请填写目标用户 ID 与 Bot ID", "error");
          return;
        }
        await withBusy("正在生成记忆…", async () => {
          const result = await apiPost("/conversation-import/start", payload);
          const body = result.result || result;
          importState.batchId = compact(body.batch_id) || compact(body.id);
          importState.preview = null;
          invalidatePool();
          toast("导入已启动", "ok");
          go("chatimport");
        });
      });
    }

    const discard = $("#impDiscardBtn", node);
    if (discard) {
      discard.addEventListener("click", () => {
        importState.preview = null;
        go("chatimport");
      });
    }

    const bindBatch = (id, action) => {
      const button = $(id, node);
      if (!button) return;
      button.addEventListener("click", async () => {
        await withBusy("正在处理…", async () => {
          await apiPost("/conversation-import/" + action, { batch_id: importState.batchId });
          toast("操作已提交", "ok");
          go("chatimport");
        });
      });
    };
    bindBatch("#impPauseBtn", "pause");
    bindBatch("#impResumeBtn", "resume");
    bindBatch("#impRollbackBtn", "rollback");
  },
});

/* ============================================================
   视图：维护与迁移
   ============================================================ */
const PRESET_LABELS = { light: "轻量", standard: "标准", companion: "陪伴" };
let migrateOutput = null;

defineView("migrate", {
  title: "维护与迁移",
  navLabel: "维护与迁移",
  eyebrow: "Import · Maintenance",
  hint: "运行预设、运维诊断、可移植数据、LivingMemory 迁移与可回滚审计",
  async load() {
    const preset = await apiTry(() => apiGet("/operations/preset"), { preset: {} });
    return { preset: preset.preset || {}, output: migrateOutput };
  },
  render(data) {
    const preset = data.preset || {};
    const current = compact(preset.preset) || compact(preset.current) || "-";

    const presets =
      '<div class="tool-block"><b>1. 运行预设</b>' +
      "<p>轻量关闭外部检索调用；标准平衡功能与成本；陪伴提高关系与连续性记忆预算。已有 Provider 选择不会被覆盖。</p>" +
      '<div class="tool-actions">' +
      Object.keys(PRESET_LABELS)
        .map((key) => '<button class="btn is-sm' + (current === key ? " is-primary" : "") + '" type="button" data-preset="' + key + '">' + PRESET_LABELS[key] + "</button>")
        .join("") +
      '<span class="badge" style="margin-left:auto">当前：' + esc(PRESET_LABELS[current] || current) + "</span>" +
      "</div></div>";

    const tools = [
      {
        title: "2. 运维诊断",
        desc: "查看检索路径、缓存命中率、模型 Token 与耗时。",
        action: "diagnosticsBtn",
        label: "生成诊断",
      },
      {
        title: "3. 可移植数据",
        desc: "仅用于本插件导出的 UTF-8 JSONL，包含记忆、身份、关系、时间线与 ACL。",
        input: "portablePath",
        placeholder: "导入时填写 JSONL 路径；导出无需填写",
        actions: [
          ["portableExportBtn", "导出"],
          ["portablePreviewBtn", "预览"],
          ["portableImportBtn", "导入"],
        ],
      },
      {
        title: "4. LivingMemory 导入",
        desc: "先预览可导入数量和跳过原因，再执行导入。当前策略只导入完整摘要。",
        input: "lmPath",
        placeholder: "LivingMemory 数据库路径，可留空自动扫描",
        actions: [
          ["lmPreviewBtn", "预览导入"],
          ["lmRunBtn", "执行导入"],
        ],
      },
      {
        title: "5. 内容修复",
        desc: "修复早期导入后只剩旧库编号的记忆。",
        input: "lmRepairPath",
        placeholder: "LivingMemory 数据库路径，可留空自动扫描",
        actions: [["lmRepairBtn", "修复内容"]],
      },
      {
        title: "6. 维护检查",
        desc: "修复索引、刷新统计并整理数据库状态。",
        actions: [["maintenanceBtn", "运行维护"]],
      },
      {
        title: "7. 可回滚记忆审计",
        desc: "先生成证据约束的预览，再明确应用；已应用批次可回滚。",
        audits: true,
        actions: [
          ["auditPreviewBtn", "生成预览"],
          ["auditStatusBtn", "读取状态"],
          ["auditApplyBtn", "应用"],
          ["auditRollbackBtn", "回滚"],
        ],
      },
      {
        title: "8. 危险清理",
        desc: "清空会先备份数据库，再删除记忆、权限规则、时间线、关系、身份与注入日志。",
        danger: true,
        actions: [["clearAllBtn", "清空全部记忆"]],
      },
    ]
      .map((tool) => {
        const input = tool.input
          ? '<input id="' + tool.input + '" type="text" placeholder="' + esc(tool.placeholder || "") + '" style="height:30px;padding:0 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:12px" />'
          : "";
        const audits = tool.audits
          ? '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
            '<input id="auditLimit" type="number" min="0" max="100" value="0" style="width:92px;height:30px;padding:0 8px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:12px" />' +
            '<input id="auditBatch" type="text" placeholder="audit_..." style="flex:1;min-width:150px;height:30px;padding:0 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:12px" />' +
            "</div>"
          : "";
        return (
          '<div class="tool-block"><b>' + esc(tool.title) + "</b><p>" + esc(tool.desc) + "</p>" +
          input + audits +
          '<div class="tool-actions">' +
          (tool.actions || [])
            .map((row) => '<button class="btn is-sm' + (tool.danger ? " is-danger" : "") + '" type="button" id="' + row[0] + '">' + esc(row[1]) + "</button>")
            .join("") +
          "</div></div>"
        );
      })
      .join("");

    return (
      '<div class="grid split-2">' +
      card("维护工具", "按顺序执行更稳妥", presets + tools) +
      card(
        "输出",
        "最近一次操作结果",
        data.output
          ? '<pre style="margin:0;font-size:11.5px;line-height:1.6;color:var(--text-2);white-space:pre-wrap;word-break:break-all">' + esc(jsonPreview(data.output)) + "</pre>"
          : emptyState("还没有输出", "执行任一操作后，结果会显示在这里。")
      ) +
      "</div>"
    );
  },
  mount(node) {
    const run = async (label, fn) => {
      await withBusy(label + "…", async () => {
        try {
          migrateOutput = await fn();
          toast(label + "完成", "ok");
        } catch (error) {
          migrateOutput = { error: error.message };
          toast(label + "失败：" + error.message, "error");
        }
        go("migrate");
      });
    };

    $$("[data-preset]", node).forEach((button) => {
      button.addEventListener("click", () => run("应用预设", () => apiPost("/operations/preset", { preset: button.dataset.preset })));
    });

    const bind = (id, fn, label) => {
      const button = $(id, node);
      if (button) button.addEventListener("click", () => run(label, fn));
    };

    bind("#diagnosticsBtn", () => apiGet("/operations/diagnostics"), "生成诊断");
    bind("#portableExportBtn", () => apiPost("/data/export", {}), "导出数据");
    bind("#portablePreviewBtn", () => {
      const path = $("#portablePath", node).value.trim();
      if (!path) throw new Error("请先填写 JSONL 路径");
      return apiGet("/data/import/preview?path=" + encodeURIComponent(path));
    }, "预览导入");
    bind("#portableImportBtn", () => {
      const path = $("#portablePath", node).value.trim();
      if (!path) throw new Error("请先填写 JSONL 路径");
      return apiPost("/data/import/run", { path });
    }, "导入数据");
    bind("#lmPreviewBtn", () => {
      const input = $("#lmPath", node);
      const path = input ? input.value.trim() : "";
      return apiGet("/import/livingmemory/preview?path=" + encodeURIComponent(path));
    }, "预览迁移");
    bind("#lmRunBtn", () => apiPost("/import/livingmemory/run", { path: $("#lmPath", node).value.trim() }), "执行迁移");
    bind("#lmRepairBtn", () => apiPost("/maintenance/repair_livingmemory_content", { path: $("#lmRepairPath", node).value.trim() }), "修复内容");
    bind("#maintenanceBtn", () => apiPost("/maintenance", {}), "运行维护");
    bind("#auditPreviewBtn", () => apiPost("/maintenance/audit/preview", { limit: int($("#auditLimit", node).value) }), "生成审计预览");
    bind("#auditStatusBtn", () => apiGet("/maintenance/audit/status?batch_id=" + encodeURIComponent($("#auditBatch", node).value.trim())), "读取审计状态");
    bind("#auditApplyBtn", () => apiPost("/maintenance/audit/apply", { batch_id: $("#auditBatch", node).value.trim(), confirm: "应用" }), "应用审计");
    bind("#auditRollbackBtn", () => apiPost("/maintenance/audit/rollback", { batch_id: $("#auditBatch", node).value.trim(), confirm: "回滚" }), "回滚审计");
    bind("#clearAllBtn", async () => {
      const confirmed = await showInlineConfirmation("清空全部记忆", "将清空全部记忆数据（会先备份数据库）。确定继续？", "清空");
      if (!confirmed) throw new Error("已取消");
      return apiPost("/maintenance/clear_all", { confirm: "清空" });
    }, "清空记忆");
  },
});

/* ============================================================
   视图：模块配置
   ============================================================ */
const MODULE_LABELS = {
  appearance: "外观",
  memory_capture: "记忆捕获",
  scope_control: "范围控制",
  portrait: "统一画像",
  memory_summary: "记忆摘要",
  historical_chat_import: "历史聊天导入",
  retrieval: "检索",
  retrieval_advanced: "检索进阶",
  memory_injection: "记忆注入",
  conversation_memory: "对话记忆",
  conversation_memory_advanced: "对话记忆进阶",
  core_memory: "核心记忆",
  context_orchestration: "上下文编排",
  context_orchestration_advanced: "上下文编排进阶",
  private_companion_bridge: "陪伴桥接",
  visibility: "可见性",
  memory_tools: "记忆工具",
  memory_reconstruction: "记忆重建",
  knowledge_graph: "知识图谱",
  livingmemory_migration: "LivingMemory 迁移",
  maintenance: "维护",
  maintenance_audit: "记忆审计",
  maintenance_decay: "记忆衰减",
};

defineView("config", {
  title: "模块配置",
  navLabel: "模块配置",
  eyebrow: "Settings · Config",
  hint: "按模块调整检索、注入、编排与维护策略，保存后立即写入插件配置",
  async load() {
    const result = await apiGet("/config/schema");
    state.configSchema = result;
    return result;
  },
  render(data) {
    const schema = data.schema || {};
    const values = data.values || {};
    const modules = Object.keys(schema);
    if (!modules.includes(state.configModule)) state.configModule = modules[0] || "appearance";
    const moduleId = state.configModule;
    const moduleSchema = schema[moduleId] || { items: {} };
    const moduleValues = values[moduleId] || {};
    const items = moduleSchema.items || {};

    const nav = modules
      .map(
        (key) =>
          '<button type="button" class="' + (key === moduleId ? "is-active" : "") + '" data-module="' + esc(key) + '">' +
          "<span>" + esc(MODULE_LABELS[key] || key) + "</span>" +
          "<em>" + Object.keys((schema[key] || {}).items || {}).length + "</em></button>"
      )
      .join("");

    const fields = Object.keys(items)
      .map((key) => {
        const item = items[key] || {};
        const value = moduleValues[key] === undefined ? item.default : moduleValues[key];
        const desc = compact(item.description) || key;
        const hint = compact(item.hint);
        let input;
        if (Array.isArray(item.options) && item.options.length) {
          input =
            '<select id="cfg_' + esc(key) + '">' +
            item.options
              .map((opt) => '<option value="' + esc(opt) + '"' + (String(value) === String(opt) ? " selected" : "") + ">" + esc(opt) + "</option>")
              .join("") +
            "</select>";
        } else if (item.type === "bool" || item.type === "boolean") {
          input =
            '<label class="switch"><input type="checkbox" id="cfg_' + esc(key) + '"' + (value ? " checked" : "") + ' /><span class="switch-track"></span><span>' + (value ? "已启用" : "已关闭") + "</span></label>";
        } else if (item.type === "int" || item.type === "float" || item.type === "number") {
          input = '<input type="number" id="cfg_' + esc(key) + '" value="' + esc(value === undefined || value === null ? "" : value) + '" step="' + (item.type === "float" ? "0.01" : "1") + '" />';
        } else if (item.type === "list" || Array.isArray(value)) {
          input = '<input type="text" id="cfg_' + esc(key) + '" value="' + esc(Array.isArray(value) ? value.join(",") : compact(value)) + '" />';
        } else {
          input = '<input type="text" id="cfg_' + esc(key) + '" value="' + esc(value === undefined || value === null ? "" : value) + '" />';
        }
        return (
          '<div class="config-field"><div><div class="cf-label">' + esc(desc) + "</div>" +
          (hint ? '<div class="cf-desc">' + esc(hint) + "</div>" : "") +
          '<div class="cf-desc mono" style="opacity:.7;margin-top:4px">' + esc(key) + "</div></div>" +
          '<div class="cf-input">' + input + "</div></div>"
        );
      })
      .join("");

    return (
      '<div class="config-layout">' +
      '<nav class="config-nav">' + nav + "</nav>" +
      '<div style="display:grid;gap:14px">' +
        card(
          MODULE_LABELS[moduleId] || moduleId,
          compact(moduleSchema.description) || moduleId,
          '<form id="configForm" class="config-form">' + (fields || emptyState("该模块没有可配置项", "")) + "</form>",
          '<button class="btn is-primary is-sm" type="button" id="configSaveBtn">保存本模块</button>'
        ) +
        (moduleSchema.hint ? '<p class="section-note">' + esc(moduleSchema.hint) + "</p>" : "") +
      "</div>" +
      "</div>"
    );
  },
  mount(node, data) {
    const schema = data.schema || {};
    $$("[data-module]", node).forEach((button) => {
      button.addEventListener("click", () => {
        state.configModule = button.dataset.module;
        go("config");
      });
    });

    const saveBtn = $("#configSaveBtn", node);
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        const moduleId = state.configModule;
        const items = (schema[moduleId] || {}).items || {};
        const values = {};
        Object.keys(items).forEach((key) => {
          const item = items[key] || {};
          const el = $("#cfg_" + key, node);
          if (!el) return;
          if (el.type === "checkbox") values[key] = el.checked;
          else if (el.type === "number") values[key] = el.value === "" ? null : Number(el.value);
          else if (Array.isArray(item.options)) values[key] = el.value;
          else if (item.type === "list" || Array.isArray(items[key].default)) {
            values[key] = el.value.trim() === "" ? [] : el.value.split(",").map((v) => v.trim());
          } else values[key] = el.value;
        });
        await withBusy("正在保存…", async () => {
          await apiPost("/config/module/update", { module: moduleId, values });
          toast("已保存 " + (MODULE_LABELS[moduleId] || moduleId), "ok");
          invalidatePool();
          go("config");
        });
      });
    }

    $$(".switch input", node).forEach((input) => {
      input.addEventListener("change", () => {
        const label = input.parentElement.querySelector("span:last-child");
        if (label) label.textContent = input.checked ? "已启用" : "已关闭";
      });
    });
  },
});

/* ============================================================
   视图：权限拓扑
   ============================================================ */
const ACL_MODE_LABELS = { whitelist: "白名单", blacklist: "黑名单" };

const SCOPE_SWITCHES = [
  ["private_capture_enabled", "私聊捕获"],
  ["group_capture_enabled", "群聊捕获"],
  ["private_recall_enabled", "私聊召回"],
  ["group_recall_enabled", "群聊召回"],
  ["private_topology_enabled", "私聊参与拓扑"],
  ["group_topology_enabled", "群聊参与拓扑"],
];

const ACL_MAX_MATRIX = 8;
const ACL_MAX_EXPANDED = 16;

const aclState = { query: "", onlyLinked: false, selected: "", expanded: false };

function winKey(scope, id) {
  return compact(scope) + ":" + compact(id);
}

function winName(win) {
  return compact(win.label) || compact(win.target_name) || compact(win.id) || "未命名窗口";
}

function winColor(scope) {
  return compact(scope) === "private" ? "var(--c-private)" : compact(scope) === "group" ? "var(--c-group)" : "var(--text-3)";
}

function winTone(scope) {
  return compact(scope) === "private" ? "private" : compact(scope) === "group" ? "group" : "";
}

defineView("acl", {
  title: "权限拓扑",
  navLabel: "权限拓扑",
  eyebrow: "Settings · ACL",
  hint: "谁可以读到哪个窗口的记忆 —— 授权矩阵、单个窗口策略与全局范围开关",
  async load() {
    const result = await apiTry(() => apiGet("/acl/matrix"), null);
    if (!result) return { error: "权限矩阵读取失败" };
    return result;
  },
  render(data) {
    if (data.error) return card("权限拓扑", "", emptyState("读取失败", data.error));

    const windows = Array.isArray(data.windows) ? data.windows : [];
    const rules = Array.isArray(data.rules) ? data.rules : [];
    const policies = Array.isArray(data.policies) ? data.policies : [];
    const scopeControl = data.scope_control || {};

    const ruleMap = {};
    rules.forEach((rule) => {
      ruleMap[winKey(rule.owner_scope, rule.owner_id) + ">" + winKey(rule.reader_scope, rule.reader_id)] = rule;
    });
    const policyMap = {};
    policies.forEach((policy) => {
      policyMap[winKey(policy.window_scope, policy.window_id)] = policy;
    });

    const outDeg = {};
    const inDeg = {};
    rules.forEach((rule) => {
      const owner = winKey(rule.owner_scope, rule.owner_id);
      const reader = winKey(rule.reader_scope, rule.reader_id);
      outDeg[owner] = (outDeg[owner] || 0) + 1;
      inDeg[reader] = (inDeg[reader] || 0) + 1;
    });

    const query = aclState.query.trim().toLowerCase();
    let candidates = windows.slice();
    if (aclState.onlyLinked) {
      candidates = candidates.filter(
        (win) => (outDeg[winKey(win.scope, win.id)] || 0) + (inDeg[winKey(win.scope, win.id)] || 0) > 0
      );
    }
    if (query) {
      candidates = candidates.filter((win) => (winName(win) + " " + compact(win.id)).toLowerCase().indexOf(query) >= 0);
    }
    candidates.sort((a, b) => int(b.memory_count) - int(a.memory_count));

    const cap = aclState.expanded ? ACL_MAX_EXPANDED : ACL_MAX_MATRIX;
    const shown = candidates.slice(0, cap);

    if (!shown.some((win) => winKey(win.scope, win.id) === aclState.selected)) {
      const ranked = shown.slice().sort((a, b) => {
        const ka = winKey(a.scope, a.id);
        const kb = winKey(b.scope, b.id);
        const diff = (outDeg[kb] || 0) + (inDeg[kb] || 0) - ((outDeg[ka] || 0) + (inDeg[ka] || 0));
        return diff !== 0 ? diff : int(b.memory_count) - int(a.memory_count);
      });
      aclState.selected = ranked.length ? winKey(ranked[0].scope, ranked[0].id) : "";
    }
    const selKey = aclState.selected;
    const selected = shown.find((win) => winKey(win.scope, win.id) === selKey) || null;

    /* ---------- 矩阵 ---------- */
    let matrix = "";
    if (!shown.length) {
      matrix = emptyState("没有可展示的窗口", "调整筛选条件，或先在记忆库里产生一些窗口。");
    } else {
      const cols = "grid-template-columns: 138px repeat(" + shown.length + ", 68px)";
      const headRow =
        '<div class="mx-corner">被读方 ＼ 读取方</div>' +
        shown
          .map(
            (win, index) =>
              '<div class="mx-ch" data-c="' + index + '"><b>' + esc(shortId(win.id)) + "</b><span>" +
              esc(clip(winName(win), 8)) + "</span></div>"
          )
          .join("");
      const bodyRows = shown
        .map((owner, r) => {
          const ownerKey = winKey(owner.scope, owner.id);
          const rowHead =
            '<button class="mx-rh' + (ownerKey === selKey ? " is-sel" : "") + '" type="button" data-r="' + r +
            '" data-pick="' + esc(ownerKey) + '"><i style="background:' + winColor(owner.scope) + '"></i><b>' +
            esc(winName(owner)) + "</b></button>";
          const cells = shown
            .map((reader, c) => {
              if (r === c) return '<div class="mx-cell" data-state="self">自身</div>';
              const rule = ruleMap[ownerKey + ">" + winKey(reader.scope, reader.id)];
              const state = rule ? (rule.effect === "deny" ? "deny" : "allow") : "";
              const glyph =
                state === "allow"
                  ? '<span class="dot"></span>'
                  : state === "deny"
                  ? '<span class="cross">×</span>'
                  : "";
              return (
                '<button class="mx-cell" type="button" data-state="' + state + '" data-r="' + r + '" data-c="' + c + '"' +
                ' data-owner-scope="' + esc(owner.scope) + '" data-owner-id="' + esc(owner.id) + '"' +
                ' data-reader-scope="' + esc(reader.scope) + '" data-reader-id="' + esc(reader.id) + '"' +
                (rule ? ' data-rule="' + esc(rule.id) + '"' : "") +
                ' aria-label="' + esc(winName(owner) + " 授权给 " + winName(reader)) + '">' + glyph + "</button>"
              );
            })
            .join("");
          return rowHead + cells;
        })
        .join("");
      matrix =
        '<div class="mx-scroll"><div class="mx" id="mxGrid" style="' + cols + '">' + headRow + bodyRows + "</div>" +
        '<div class="mx-tip" id="mxTip"></div></div>';
    }

    /* ---------- 授权密度 ---------- */
    const density = candidates
      .slice(0, 12)
      .map((win) => {
        const key = winKey(win.scope, win.id);
        return (
          '<button class="density-chip' + (key === selKey ? " is-sel" : "") + '" type="button" data-pick="' + esc(key) + '">' +
          esc(winName(win)) + "<em>出 " + int(outDeg[key]) + " · 入 " + int(inDeg[key]) + "</em></button>"
        );
      })
      .join("");

    /* ---------- 选中窗口 ---------- */
    let windowCard = "";
    if (selected) {
      const key = winKey(selected.scope, selected.id);
      const policy = policyMap[key] || null;
      const defaultMode = compact(selected.scope) === "group" ? "blacklist" : "whitelist";
      const readMode = compact(policy && policy.read_mode) || defaultMode;
      const shareMode = compact(policy && policy.share_mode) || defaultMode;
      const captureOn = policy && policy.capture_enabled === false ? false : true;
      const recallOn = policy && policy.recall_enabled === false ? false : true;

      const outbound = rules.filter((rule) => winKey(rule.owner_scope, rule.owner_id) === key);
      const inbound = rules.filter((rule) => winKey(rule.reader_scope, rule.reader_id) === key);

      const ruleRow = (rule, direction) =>
        '<div class="row" style="cursor:default"><div class="row-main">' +
        '<div class="row-title">' + esc(shortId(direction === "out" ? rule.reader_id : rule.owner_id)) + "</div>" +
        '<div class="row-sub">' + esc(SCOPE_META[compact(direction === "out" ? rule.reader_scope : rule.owner_scope)] ? SCOPE_META[compact(direction === "out" ? rule.reader_scope : rule.owner_scope)].label : compact(direction === "out" ? rule.reader_scope : rule.owner_scope)) + "</div></div>" +
        '<div class="row-meta">' +
        badge(rule.effect === "deny" ? "拒绝" : "允许", rule.effect === "deny" ? "danger" : "ok") +
        (rule.enabled ? "" : badge("停用", "warn")) +
        '<button class="btn is-sm is-ghost" type="button" data-del-acl="' + esc(rule.id) + '">删除</button>' +
        "</div></div>";

      const otherOptions = candidates
        .filter((win) => winKey(win.scope, win.id) !== key)
        .map(
          (win) =>
            '<option value="' + esc(winKey(win.scope, win.id)) + '">' + esc(winName(win)) + "（" +
            esc(SCOPE_META[compact(win.scope)] ? SCOPE_META[compact(win.scope)].label : compact(win.scope)) + "）</option>"
        )
        .join("");

      windowCard =
        card(
          "选中窗口",
          policy ? "已单独设置策略" : "沿用范围默认",
          '<div style="display:flex;align-items:center;gap:9px;margin-bottom:12px">' +
            '<span style="width:8px;height:8px;border-radius:99px;background:' + winColor(selected.scope) + ';flex:none"></span>' +
            '<div style="min-width:0"><div style="font-size:14px;font-weight:620">' + esc(winName(selected)) + "</div>" +
            '<div class="mono" style="font-size:11px;color:var(--text-3)">' + esc(compact(selected.id)) + " · " + fmtInt(selected.memory_count) + " 条记忆</div></div>" +
            badge(SCOPE_META[compact(selected.scope)] ? SCOPE_META[compact(selected.scope)].label : compact(selected.scope), winTone(selected.scope)) +
          "</div>" +
          '<div class="section-label" style="margin:2px 0 8px"><h2 style="font-size:11px">出站授权</h2><span class="section-note">谁可以读这里的记忆 · ' + outbound.length + " 条</span></div>" +
          (outbound.length
            ? '<div class="row-list">' + outbound.map((rule) => ruleRow(rule, "out")).join("") + "</div>"
            : '<p class="section-note" style="margin-bottom:10px">还没有把这里的记忆授权给任何窗口。</p>') +
          '<div class="section-label" style="margin:14px 0 8px"><h2 style="font-size:11px">入站授权</h2><span class="section-note">这里能读到哪些记忆 · ' + inbound.length + " 条</span></div>" +
          (inbound.length
            ? '<div class="row-list">' + inbound.map((rule) => ruleRow(rule, "in")).join("") + "</div>"
            : '<p class="section-note" style="margin-bottom:10px">这里还不能读到其他窗口的记忆。</p>') +
          '<div class="section-label" style="margin:14px 0 8px"><h2 style="font-size:11px">快速授权</h2></div>' +
          '<div style="display:grid;grid-template-columns:minmax(0,1fr) 96px auto;gap:7px;align-items:center">' +
            '<select id="aclAddTarget" style="height:32px;padding:0 9px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:12px">' +
            (otherOptions || '<option value="">没有其他窗口</option>') + "</select>" +
            '<select id="aclAddEffect" style="height:32px;padding:0 9px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:12px">' +
              '<option value="allow">允许</option><option value="deny">拒绝</option>' +
            "</select>" +
            '<button class="btn is-sm is-primary" type="button" id="aclAddBtn">添加</button>' +
          "</div>" +
          '<p class="section-note" style="margin-top:7px">等价于在矩阵里点这一格：从「本窗口」授权给所选窗口。</p>'
        ) +
        card(
          "窗口策略",
          policy ? "已单独设置" : "沿用范围默认（" + ACL_MODE_LABELS[defaultMode] + "）",
          '<div class="config-form">' +
            '<div class="field is-inline"><span>读取模式</span><select id="aclReadMode">' +
              Object.keys(ACL_MODE_LABELS).map((key) => '<option value="' + key + '"' + (readMode === key ? " selected" : "") + ">" + ACL_MODE_LABELS[key] + "</option>").join("") +
            "</select></div>" +
            '<div class="field is-inline"><span>共享模式</span><select id="aclShareMode">' +
              Object.keys(ACL_MODE_LABELS).map((key) => '<option value="' + key + '"' + (shareMode === key ? " selected" : "") + ">" + ACL_MODE_LABELS[key] + "</option>").join("") +
            "</select></div>" +
            '<label class="switch"><input type="checkbox" id="aclCapture"' + (captureOn ? " checked" : "") + ' /><span class="switch-track"></span><span>捕获新记忆</span></label>' +
            '<label class="switch"><input type="checkbox" id="aclRecall"' + (recallOn ? " checked" : "") + ' /><span class="switch-track"></span><span>参与召回</span></label>' +
            '<div class="pill-row" style="justify-content:flex-end">' +
              '<button class="btn is-sm is-primary" type="button" id="aclPolicySave">保存策略</button>' +
            "</div>" +
          "</div>"
        );
    } else {
      windowCard = card("选中窗口", "", emptyState("没有可选窗口", "先在左侧矩阵里选择一个窗口。")) +
        card("窗口策略", "", emptyState("无策略", "选择窗口后可单独设置读写模式。"));
    }

    /* ---------- 范围开关 ---------- */
    const scopeGrid =
      '<div class="grid g3" style="gap:10px 14px">' +
      SCOPE_SWITCHES.map(
        (row) =>
          '<label class="switch"><input type="checkbox" data-scope-control="' + row[0] + '"' +
          (scopeControl[row[0]] ? " checked" : "") + ' /><span class="switch-track"></span><span>' + esc(row[1]) + "</span></label>"
      ).join("") +
      "</div>";

    const denyCount = rules.filter((rule) => rule.effect === "deny").length;

    return (
      '<div class="grid" style="gap:14px">' +
      '<div class="kpi-row">' +
        kpi("参与拓扑的窗口", fmtInt(windows.length), "矩阵展示 " + fmtInt(shown.length) + " 个", "fact") +
        kpi("授权规则", fmtInt(rules.length), "跨窗口读写授权", "gold") +
        kpi("其中拒绝", fmtInt(denyCount), "显式禁止读取", denyCount ? "relation" : "fact") +
        kpi("窗口策略", fmtInt(policies.length), "未设置走范围默认", "accent") +
      "</div>" +
      '<div class="grid split-2">' +
        card(
          "授权矩阵",
          "行＝被读方 · 列＝读取方",
          '<div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-bottom:11px">' +
            '<div class="pill-row">' +
              '<button class="pill' + (aclState.onlyLinked ? "" : " is-active") + '" type="button" data-acl-filter="all">全部窗口</button>' +
              '<button class="pill' + (aclState.onlyLinked ? " is-active" : "") + '" type="button" data-acl-filter="linked">仅显示有规则</button>' +
            "</div>" +
            '<input id="aclQuery" type="search" placeholder="搜索窗口名或 ID" value="' + esc(aclState.query) +
              '" style="flex:1;min-width:150px;height:30px;padding:0 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:12px;outline:none" />' +
            (candidates.length > shown.length || aclState.expanded
              ? '<button class="pill" type="button" data-acl-filter="expand">' +
                (aclState.expanded ? "收起" : "显示全部 " + fmtInt(candidates.length) + " 个 ›") + "</button>"
              : "") +
          "</div>" +
          matrix +
          '<div class="pill-row" style="margin-top:11px;font-size:11px;color:var(--text-3)">' +
            '<span class="badge" data-tone="ok">● 允许读取</span>' +
            '<span class="badge" data-tone="danger">× 拒绝读取</span>' +
            '<span class="badge">空 未显式授权</span>' +
            '<span class="badge">自身 同窗口无需授权</span>' +
          "</div>" +
          '<p class="section-note" style="margin-top:9px">点击格子循环切换：未授权 → 允许 → 拒绝 → 未授权。灰色空格不代表禁止，由两侧窗口策略共同判定。</p>' +
          (density
            ? '<div class="section-label" style="margin:16px 0 8px"><h2 style="font-size:11px">窗口授权密度</h2><span class="section-note">出站 / 入站</span></div>' +
              '<div class="density-wrap">' + density + "</div>"
            : "")
        ) +
        '<div style="display:grid;gap:14px;align-content:start">' + windowCard + "</div>" +
      "</div>" +
      card(
        "范围开关",
        "关闭只停用对应能力，不删除已有记忆；参与拓扑关闭后，该范围的窗口不再出现在矩阵里",
        scopeGrid,
        '<button class="btn is-sm is-primary" type="button" id="aclScopeSave">保存范围开关</button>'
      ) +
      "</div>"
    );
  },
  mount(node) {
    const grid = $("#mxGrid", node);
    const tip = $("#mxTip", node);

    if (grid) {
      const clearHot = () => {
        $$(".is-hot", grid).forEach((item) => item.classList.remove("is-hot"));
      };
      grid.addEventListener("mouseover", (event) => {
        const cell = event.target.closest(".mx-cell");
        if (!cell || cell.dataset.state === "self") {
          clearHot();
          if (tip) tip.classList.remove("is-on");
          return;
        }
        const r = cell.dataset.r;
        const c = cell.dataset.c;
        clearHot();
        $$('.mx-cell[data-r="' + r + '"], .mx-cell[data-c="' + c + '"]', grid).forEach((item) =>
          item.classList.add("is-hot")
        );
        const rowHead = $('.mx-rh[data-r="' + r + '"]', grid);
        if (rowHead) rowHead.classList.add("is-hot");
        const colHead = $('.mx-ch[data-c="' + c + '"]', grid);
        if (colHead) colHead.classList.add("is-hot");
        cell.classList.add("is-hot");
        if (tip) {
          const state = cell.dataset.state;
          const now =
            state === "allow"
              ? "当前：允许读取"
              : state === "deny"
              ? "当前：拒绝读取"
              : "当前：未显式授权（按双方策略判定）";
          const next =
            state === "allow" ? "点击改为「拒绝」" : state === "deny" ? "点击「清除规则」" : "点击授权「允许」";
          tip.innerHTML =
            '<div class="tip-title">' + esc(cell.getAttribute("aria-label") || "") + "</div>" +
            '<div class="tip-now">' + esc(now) + "</div>" +
            '<div class="tip-hint">' + esc(next) + "</div>";
          tip.style.left = cell.offsetLeft + cell.offsetWidth / 2 + "px";
          tip.style.top = cell.offsetTop + "px";
          tip.classList.add("is-on");
        }
      });
      grid.addEventListener("mouseleave", () => {
        clearHot();
        if (tip) tip.classList.remove("is-on");
      });
    }

    const cycle = async (cell) => {
      const payload = {
        owner_scope: cell.dataset.ownerScope,
        owner_id: cell.dataset.ownerId,
        reader_scope: cell.dataset.readerScope,
        reader_id: cell.dataset.readerId,
      };
      const state = cell.dataset.state;
      const ruleId = compact(cell.dataset.rule);
      if (state === "allow") {
        await apiPost("/acl/upsert", Object.assign({ effect: "deny", enabled: true }, payload));
        toast("已改为拒绝读取", "ok");
      } else if (state === "deny") {
        if (!ruleId) {
          toast("找不到对应规则，请刷新后重试", "error");
          return;
        }
        await apiPost("/acl/delete", { id: ruleId });
        toast("已清除授权规则", "ok");
      } else {
        await apiPost("/acl/upsert", Object.assign({ effect: "allow", enabled: true }, payload));
        toast("已授权读取", "ok");
      }
      invalidatePool();
      go("acl");
    };

    $$(".mx-cell[data-owner-id]", node).forEach((cell) => {
      cell.addEventListener("click", async () => {
        await withBusy("正在更新授权…", () => cycle(cell));
      });
    });

    $$("[data-pick]", node).forEach((button) => {
      button.addEventListener("click", () => {
        aclState.selected = button.dataset.pick;
        go("acl");
      });
    });

    $$("[data-acl-filter]", node).forEach((button) => {
      button.addEventListener("click", () => {
        const mode = button.dataset.aclFilter;
        if (mode === "all") aclState.onlyLinked = false;
        else if (mode === "linked") aclState.onlyLinked = true;
        else if (mode === "expand") aclState.expanded = !aclState.expanded;
        go("acl");
      });
    });

    const queryInput = $("#aclQuery", node);
    if (queryInput) {
      const apply = () => {
        aclState.query = queryInput.value.trim();
        go("acl");
      };
      queryInput.addEventListener("change", apply);
      queryInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") apply();
      });
    }

    $$("[data-del-acl]", node).forEach((button) => {
      button.addEventListener("click", async () => {
        await withBusy("正在删除…", async () => {
          await apiPost("/acl/delete", { id: button.dataset.delAcl });
          invalidatePool();
          toast("规则已删除", "ok");
          go("acl");
        });
      });
    });

    const addBtn = $("#aclAddBtn", node);
    if (addBtn) {
      addBtn.addEventListener("click", async () => {
        const target = $("#aclAddTarget", node).value;
        const effect = $("#aclAddEffect", node).value;
        const parts = target.split(":");
        if (parts.length < 2) {
          toast("请先选择目标窗口", "error");
          return;
        }
        const current = compact(aclState.selected).split(":");
        await withBusy("正在添加…", async () => {
          await apiPost("/acl/upsert", {
            owner_scope: current[0] || "",
            owner_id: current.slice(1).join(":") || "",
            reader_scope: parts[0] || "",
            reader_id: parts.slice(1).join(":") || "",
            effect,
            enabled: true,
          });
          invalidatePool();
          toast("授权已添加", "ok");
          go("acl");
        });
      });
    }

    const policySave = $("#aclPolicySave", node);
    if (policySave) {
      policySave.addEventListener("click", async () => {
        const current = compact(aclState.selected).split(":");
        await withBusy("正在保存…", async () => {
          await apiPost("/acl/policy", {
            window_scope: current[0] || "",
            window_id: current.slice(1).join(":") || "",
            read_mode: $("#aclReadMode", node).value,
            share_mode: $("#aclShareMode", node).value,
            capture_enabled: $("#aclCapture", node).checked,
            recall_enabled: $("#aclRecall", node).checked,
          });
          invalidatePool();
          toast("窗口策略已保存", "ok");
          go("acl");
        });
      });
    }

    const scopeSave = $("#aclScopeSave", node);
    if (scopeSave) {
      scopeSave.addEventListener("click", async () => {
        const values = {};
        SCOPE_SWITCHES.forEach((row) => {
          const input = $('[data-scope-control="' + row[0] + '"]', node);
          if (input) values[row[0]] = input.checked;
        });
        await withBusy("正在保存…", async () => {
          await apiPost("/config/module/update", { module: "scope_control", values });
          invalidatePool();
          toast("范围开关已保存", "ok");
          go("acl");
        });
      });
    }
  },
});

/* ============================================================
   启动
   ============================================================ */
function bindShell() {
  $("#themeToggle").addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });

  window.addEventListener("mc:theme", () => {
    if (galaxyInstance) galaxyInstance.buildStarfield();
  });

  $("#drawerClose").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  $("#assemblyViewerClose")?.addEventListener("click", closeAssemblyViewer);
  $("#assemblyViewerRetry")?.addEventListener("click", () => {
    const id = $("#assemblyViewerFile")?.textContent.replace(/^FILE\s+|\s+\/.*$/g, "").trim();
    if (id) openAssemblyViewer(id);
  });
  $("#assemblyExplode")?.addEventListener("click", () => state.assemblyViewer?.setExploded(true));
  $("#assemblyAssemble")?.addEventListener("click", () => state.assemblyViewer?.setExploded(false));
  $("#assemblyReset")?.addEventListener("click", () => state.assemblyViewer?.reset());

  $("#refreshBtn").addEventListener("click", () => {
    invalidatePool();
    refresh();
  });

  const modeToggle = $("#modeToggle");
  if (modeToggle) {
    modeToggle.addEventListener("click", () => {
      applyMode(state.mode === "cinema" ? "standard" : "cinema");
      toast(state.mode === "cinema" ? "已进入终端模式" : "已切回标准模式", "ok");
      go(state.mode === "cinema" ? "overview" : state.view);
    });
  }

  const search = $("#globalSearch");
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const value = search.value.trim();
    if (!value) return;
    state.filters = { scope: "", q: value, visibility: "", lifecycle: "", memoryType: "", target: "" };
    go("inspect");
  });

  $("#railNav").addEventListener("click", (event) => {
    const item = event.target.closest("[data-view]");
    if (!item) return;
    go(item.dataset.view);
  });

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-goto]");
    if (!target) return;
    const view = target.dataset.goto;
    const filter = compact(target.dataset.filter);
    const options = {};
    if (compact(target.dataset.scope)) options.scope = target.dataset.scope;
    if (compact(target.dataset.target)) options.target = target.dataset.target;
    if (filter) {
      if (filter.indexOf("scope:") === 0) {
        state.filters = { scope: filter.slice(6), q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };
      } else if (filter === "profile") {
        state.filters = { scope: "profile", q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };
      } else if (filter.indexOf("external:") === 0) {
        state.filters = { scope: "", q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };
      }
    }
    go(view, options);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#assemblyViewer")?.hidden) {
      event.preventDefault();
      closeAssemblyViewer();
      return;
    }
    if (state.mode === "cinema" && state.view === "overview") {
      const searchBox = $("#terminalSearch");
      if (event.key === "/" && document.activeElement !== searchBox) {
        event.preventDefault();
        searchBox && searchBox.focus();
        return;
      }
      const prevColumn = $("[data-terminal-column-prev]");
      const nextColumn = $("[data-terminal-column-next]");
      const prevRecord = $("[data-terminal-prev]");
      const nextRecord = $("[data-terminal-next]");
      const records = $$("#terminalFeed .terminal-record:not([hidden])");
      if (event.key === "ArrowLeft" && prevColumn) {
        event.preventDefault();
        prevColumn.click();
        return;
      }
      if (event.key === "ArrowRight" && nextColumn) {
        event.preventDefault();
        nextColumn.click();
        return;
      }
      if (event.key === "ArrowUp" && prevRecord) {
        event.preventDefault();
        prevRecord.click();
        return;
      }
      if (event.key === "ArrowDown" && nextRecord) {
        event.preventDefault();
        nextRecord.click();
        return;
      }
      if (event.key === "Enter" && document.activeElement?.classList.contains("terminal-record")) {
        event.preventDefault();
        document.activeElement.click();
        return;
      }
    }
    if (event.key === "Escape") {
      closeDrawer();
      const box = $(".lightbox");
      if (box) box.remove();
    }
  });
}

async function boot() {
  bindShell();
  applyTheme(state.theme);
  applyMode(state.mode);
  renderRail();
  setRailStatus("loading", "正在连接…");

  const initial = document.documentElement.dataset.initialNav;
  const target = state.mode === "cinema" ? "overview" : (initial && VIEWS[initial] ? initial : "overview");

  try {
    await apiGet("/stats");
    setRailStatus("ok", "已连接");
  } catch (error) {
    setRailStatus("bad", "连接失败");
  }

  state.ready = true;
  await go(target);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
