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
const PALETTE_KEY = "memory_companion_palette";

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

function fmtBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return "-";
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let idx = 0;
  let current = value;
  while (current >= 1024 && idx < units.length - 1) {
    current /= 1024;
    idx += 1;
  }
  const digits = idx === 0 ? 0 : current >= 100 ? 0 : current >= 10 ? 1 : 2;
  return num(current, digits) + " " + units[idx];
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
  search: '<circle cx="7.2" cy="7.2" r="4.5"/><path d="M10.6 10.6L14 14"/>',
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
  // 2.6.0：危险动作的确认口令与写操作的 CSRF 令牌统一在这里补齐，调用点保持原样。
  if (method !== "GET") {
    options.body = await withCsrfToken(options.body);
    options.body = await withConfirmation(path, options.body);
  }
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
  return guardPayload(data.data !== undefined ? data.data : data, path);
}

// 与后端 _wrap_route 的确认口径一一对应：
// 删除类 DELETE:<id>、清空类 CLEAR:<scope>、擦人类 ERASE:<user_id>、
// 其余危险路由 CONFIRM:<route>。只有危险路由才注入，普通写入不受影响。
const CONFIRMATION_ROUTES = new Set([
  "/memory/delete",
  "/core-memory/delete",
  "/person/erase",
  "/person/weight",
  "/portrait/govern",
  "/maintenance/audit/apply",
  "/maintenance/audit/rollback",
  "/data/import/run",
  "/conversation-import/rollback",
  "/maintenance/clear_all",
  "/maintenance/clear_scope",
  "/import/livingmemory/run",
  "/config/module/update",
]);

function canonicalConfirmation(route, payload) {
  if (route === "/memory/delete" || route === "/core-memory/delete") {
    return "DELETE:" + (payload.id || "");
  }
  if (route === "/person/erase") {
    return "ERASE:" + (payload.user_id || "");
  }
  if (route === "/maintenance/clear_all") {
    return "CLEAR:all";
  }
  if (route === "/maintenance/clear_scope") {
    return "CLEAR:" + (payload.target_type || payload.type || payload.scope || "");
  }
  return "CONFIRM:" + route;
}

// P13：写操作要带 CSRF 令牌。令牌由 GET /ui/csrf 下发（15 分钟有效）；
// 桥接通道无法自定义请求头，所以统一放进 body.csrf_token，服务端两种都收。
let csrfTokenCache = { token: "", expiresAt: 0 };

function payloadOf(data) {
  return data && data.data !== undefined ? data.data : data;
}

// 不经过 apiRequest 的底层请求：取令牌/取 nonce 时不能再次触发注入逻辑。
async function rawApiRequest(path, method, body) {
  const bridge = getBridge() || await waitForBridge();
  if (bridge && typeof bridge.apiGet === "function" && typeof bridge.apiPost === "function") {
    return bridgeRequest(bridge, path, method, body);
  }
  if (canUseHttpFallback()) return httpRequest(path, method, body);
  return null;
}

async function ensureCsrfToken(force) {
  const now = Date.now();
  if (!force && csrfTokenCache.token && csrfTokenCache.expiresAt > now + 5000) {
    return csrfTokenCache.token;
  }
  let data = null;
  try {
    data = await rawApiRequest("/ui/csrf", "GET", null);
  } catch (error) {
    return "";
  }
  const body = payloadOf(data);
  const token = body && typeof body.token === "string" ? body.token : "";
  if (!token) return "";
  const ttl = Number(body.expires_in) > 0 ? Number(body.expires_in) : 900;
  csrfTokenCache = { token: token, expiresAt: now + ttl * 1000 };
  return token;
}

async function withCsrfToken(body) {
  const payload = Object.assign({}, body || {});
  const token = await ensureCsrfToken(false);
  if (token) payload.csrf_token = token;
  return payload;
}

async function requestConfirmationNonce(route, payload) {
  let data = null;
  try {
    const token = await ensureCsrfToken(false);
    const requestBody = { route: route, payload: payload || {} };
    if (token) requestBody.csrf_token = token;
    data = await rawApiRequest("/ui/confirm-nonce", "POST", requestBody);
  } catch (error) {
    return "";
  }
  const body = payloadOf(data);
  return body && typeof body.confirm === "string" ? body.confirm : "";
}

// P9：确认串改为一次性 nonce——先向服务端要 "<canonical>:<nonce>"，取不到时
// 回退到固定串（非浏览器上下文仍然接受，便于本地脚本与排查）。
async function withConfirmation(path, body) {
  const route = String(path || "").split("?")[0];
  if (!CONFIRMATION_ROUTES.has(route)) return body;
  const payload = Object.assign({}, body || {});
  const canonical = canonicalConfirmation(route, payload);
  const nonce = await requestConfirmationNonce(route, payload);
  payload.confirm = nonce || canonical;
  return payload;
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
   字段护栏（只检测，不阻止）
   开发模式下用 Proxy 包装 apiRequest 的返回值，读取响应里不存在的字段时
   console.error 并上报，把「静默显示错误值」变成「可见错误」。开启方式：
   window.__MC_FIELD_GUARD__ = true。它不阻止错误发生；编译期强制需要
   JSDoc + tsc --checkJs 或迁移 TypeScript，成本远超收益，明确不做。
   ------------------------------------------------------------ */
const guardedFieldReads = new Set();

function guardPayload(payload, path) {
  if (typeof window === "undefined" || window.__MC_FIELD_GUARD__ !== true) return payload;
  if (payload === null || typeof payload !== "object") return payload;
  const endpoint = String(path || "").split("?")[0];
  return new Proxy(payload, {
    get(target, key, receiver) {
      if (typeof key === "string" && !(key in target)) {
        const marker = endpoint + " · " + key;
        if (!guardedFieldReads.has(marker)) {
          guardedFieldReads.add(marker);
          console.error(
            "[记忆面板] 读取了响应中不存在的字段：" + marker +
            "；字段归属以 page_api.ENDPOINT_FIELD_CONTRACT 为准。"
          );
          if (typeof window.__MC_FIELD_REPORT__ === "function") window.__MC_FIELD_REPORT__(marker);
        }
      }
      return Reflect.get(target, key, receiver);
    },
  });
}

/* ------------------------------------------------------------
   陪伴插件联动状态的唯一取数入口
   每个字段只从声明了它的端点读取，视图不再直接摸 caps.* / personal.*：
     installed        ← /capabilities/bot-personal · companion_installed
     pluginName       ← /companion/personal-memory · plugin_name
     dailyPlanEnabled ← /companion/personal-memory · daily_plan_enabled
     detailEnabled    ← /companion/personal-memory · detail_enabled
     reason           ← /companion/personal-memory · reason / bridge_reason

   **installed 不能读 caps.available。** 那个字段的含义是「记忆侧自己的 contract
   自检通过」，也就是「我准备好了、可以跟陪伴侧对话」，跟对方装没装毫无关系，
   它恒为 true。过去面板拿它当「已安装」显示，于是根本没装
   astrbot_plugin_private_companion 的宿主上也显示「已连接」。
   installed 只认 companion_installed —— 那个字段由后端真的去 import 陪伴插件的
   运行时入口 get_private_companion_api() 得到，答的是「现在真的能用」。
   ------------------------------------------------------------ */
const REASON_TEXT = {
  bridge_status_unavailable: "联动状态读取失败",
  bridge_config_unavailable: "无法读取插件配置",
  bridge_config_unreadable: "配置读取出错",
  bridge_config_invalid: "配置格式不正确",
  bridge_disabled: "联动已在配置中关闭",
  companion_api_unavailable: "未检测到陪伴插件 astrbot_plugin_private_companion",
  companion_p6_producer_unavailable: "陪伴插件未提供状态接口",
  companion_p6_producer_unreadable: "陪伴插件状态接口读取失败",
  companion_p6_producer_stale: "陪伴插件状态已过期",
  companion_p6_unverifiable: "陪伴插件状态无法核实",
  companion_bridge_available: "联动正常",
  manifest_registry_unavailable: "扩展清单不可用",
  coordination_input_unverifiable: "部分联动项无法核实",
  coordination_degraded: "部分联动项降级",
  coordination_ready: "联动正常",
  runtime_compatible: "契约完全兼容",
  runtime_degraded: "契约降级运行",
  runtime_unsupported: "契约版本不受支持",
  runtime_status_unavailable: "运行时状态不可读",
};

/* 内部原因码是给日志看的，直接甩到面板上等于让用户猜。认不出来的码原样返回，
   宁可难看也不能吞掉——那说明后端又加了新码。 */
function bridgeReasonText(code) {
  const key = compact(code);
  if (!key) return "";
  return REASON_TEXT[key] || key;
}

const HEALTH_TEXT = { ready: "正常", degraded: "降级", unverifiable: "无法核实" };

/* health 同样是内部词（ready/degraded/unverifiable），直接显示等于让用户查字典。
   原始码仍保留在联动的 title 里，排查时看得到。 */
function healthText(value) {
  const key = compact(value);
  return HEALTH_TEXT[key] || key || "未知";
}

function bridgeHealthText(bridge) {
  if (!bridge || typeof bridge !== "object") return "未知";
  return healthText(bridge.health);
}

function runtimeHealthText(runtime) {
  if (!runtime || typeof runtime !== "object") return "未知";
  const reason = bridgeReasonText(runtime.reason_code);
  return reason ? healthText(runtime.health) + " · " + reason : healthText(runtime.health);
}

function companionStatus(capsPayload, personalPayload) {
  const caps = capsPayload && typeof capsPayload === "object" ? capsPayload : {};
  const personal = personalPayload && typeof personalPayload === "object" ? personalPayload : {};
  const installed = caps.companion_installed === true;
  const linked = personal.available === true;
  return {
    installed: installed,
    available: installed && linked,
    pluginName: compact(personal.plugin_name) || (installed ? compact(caps.companion_plugin_name) : ""),
    dailyPlanEnabled: installed && linked && personal.daily_plan_enabled === true,
    detailEnabled: installed && linked && personal.detail_enabled === true,
    reason: !installed
      ? "未安装陪伴插件 astrbot_plugin_private_companion"
      : compact(personal.reason) || bridgeReasonText(personal.bridge_reason) || (linked ? "" : "陪伴插件已安装，桥接尚未就绪"),
  };
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
  filters: { scope: "", q: "", visibility: "", lifecycle: "", memoryType: "", ownerBot: "" },
  selected: null,
  configSchema: null,
  configModule: "appearance",
  companion: null,
  acl: null,
  assemblyViewer: null,
  lastHostIsDark: null,
  explicitTheme: "",
  manualThemeToggled: false,
};

/* ------------------------------------------------------------
   提示 / 忙碌 / 抽屉
   ------------------------------------------------------------ */
let toastTimer = 0;
let scrimTimer = 0;
let drawerLastFocus = null;
let assemblyViewerTicket = 0;

function prefersReducedMotion() {
  try {
    return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch (error) {
    return false;
  }
}

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

async function withBusy(text, fn, minMs) {
  busy(true, text);
  const startedAt = Date.now();
  try {
    return await fn();
  } finally {
    const remaining = (Number(minMs) || 0) - (Date.now() - startedAt);
    if (remaining > 0) await new Promise((resolve) => window.setTimeout(resolve, remaining));
    busy(false);
  }
}

function setBusyText(text) {
  const el = $("#busyText");
  if (el && text) el.textContent = text;
}

function openDrawer(title, eyebrow, html) {
  const drawer = $("#drawer");
  const scrim = $("#scrim");
  if (drawer && !drawer.classList.contains("is-open")) {
    drawerLastFocus = document.activeElement;
  }
  $("#drawerEyebrow").textContent = eyebrow || "记忆";
  $("#drawerTitle").textContent = title || "未选择";
  $("#drawerBody").innerHTML = html;
  window.clearTimeout(scrimTimer);
  scrimTimer = 0;
  if (scrim) {
    scrim.hidden = false;
    if (prefersReducedMotion()) {
      scrim.classList.add("is-open");
    } else {
      void scrim.offsetWidth;
      requestAnimationFrame(() => {
        if (drawer && drawer.classList.contains("is-open")) scrim.classList.add("is-open");
      });
    }
  }
  if (drawer) {
    drawer.inert = false;
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
  }
}

function closeDrawer() {
  const drawer = $("#drawer");
  const scrim = $("#scrim");
  if (drawer) {
    const active = document.activeElement;
    if (active && typeof drawer.contains === "function" && drawer.contains(active) && typeof active.blur === "function") {
      active.blur();
    }
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    drawer.inert = true;
  }
  if (scrim) {
    window.clearTimeout(scrimTimer);
    scrimTimer = 0;
    scrim.classList.remove("is-open");
    if (prefersReducedMotion()) {
      scrim.hidden = true;
    } else {
      scrimTimer = window.setTimeout(() => {
        scrimTimer = 0;
        if (!drawer || !drawer.classList.contains("is-open")) scrim.hidden = true;
      }, 240);
    }
  }
  const prev = drawerLastFocus;
  drawerLastFocus = null;
  if (prev && typeof prev.focus === "function" && document.contains(prev)) {
    try { prev.focus({ preventScroll: true }); } catch (error) { /* 忽略 */ }
  }
}

function showInlineConfirmation(title, message, confirmLabel) {
  return new Promise((resolve) => {
    const prevFocus = document.activeElement;
    const overlay = document.createElement("div");
    overlay.className = "inline-confirm-overlay";
    overlay.innerHTML =
      '<section class="inline-confirm" role="dialog" aria-modal="true" aria-labelledby="inlineConfirmTitle">' +
      '<h2 id="inlineConfirmTitle">' + esc(title || "请确认") + "</h2>" +
      '<p>' + esc(message || "确认继续此操作？") + "</p>" +
      '<div class="inline-confirm-actions"><button type="button" data-confirm-cancel>取消</button><button type="button" class="is-danger" data-confirm-ok>' +
      esc(confirmLabel || "继续") + "</button></div></section>";
    let settled = false;
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    };
    const finish = (value) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKeyDown);
      overlay.classList.remove("is-open");
      if (prefersReducedMotion()) {
        overlay.remove();
      } else {
        window.setTimeout(() => overlay.remove(), 180);
      }
      if (prevFocus && typeof prevFocus.focus === "function" && document.contains(prevFocus)) {
        try { prevFocus.focus({ preventScroll: true }); } catch (error) { /* 忽略 */ }
      }
      resolve(value);
    };
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay || event.target.closest("[data-confirm-cancel]")) finish(false);
      if (event.target.closest("[data-confirm-ok]")) finish(true);
    });
    document.addEventListener("keydown", onKeyDown);
    document.body.appendChild(overlay);
    if (prefersReducedMotion()) {
      overlay.classList.add("is-open");
    } else {
      void overlay.offsetWidth;
      requestAnimationFrame(() => {
        if (!settled) overlay.classList.add("is-open");
      });
    }
    const ok = $("[data-confirm-ok]", overlay);
    if (ok) ok.focus();
  });
}

/* ------------------------------------------------------------
   主题
   ------------------------------------------------------------ */
/* appearance.theme 过去是纯死配置：后端把 14 个中国传统色名映射成 key 传给前端，
   前端谁都没读，配了也不变色。这里把 key 打到 <html> 上，由 app.css 的
   [data-palette="…"] 规则接管。index.html 在跳转前也会打一次，避免首帧闪色。 */
const PALETTE_KEYS = new Set([
  "huangbaiyou", "tianpiao", "haitianxia", "yingying", "oubi", "qingming",
  "zipu", "shanlan", "qielan", "tuihong", "congqing", "yuebai", "mocan", "gupiao",
]);

function applyPalette(key) {
  const value = compact(key).toLowerCase();
  if (PALETTE_KEYS.has(value)) {
    document.documentElement.dataset.palette = value;
    try { window.localStorage.setItem(PALETTE_KEY, value); } catch (error) { /* 忽略存储禁用 */ }
    return value;
  }
  delete document.documentElement.dataset.palette;
  try { window.localStorage.removeItem(PALETTE_KEY); } catch (error) { /* 忽略存储禁用 */ }
  return "";
}

async function syncPalette() {
  const payload = await apiTry(() => apiGet("/ui-preferences"), null);
  if (payload) {
    applyPalette(payload.palette);
    return;
  }
  // 后端暂时不可达时退回上次缓存，避免面板莫名变回默认紫色
  try {
    const cached = window.localStorage.getItem(PALETTE_KEY);
    if (cached) applyPalette(cached);
  } catch (error) { /* 忽略存储禁用 */ }
}

function currentPageSearch() {
  if (typeof location !== "undefined" && location && typeof location.search === "string") {
    return location.search;
  }
  if (typeof window !== "undefined" && window && window.location && typeof window.location.search === "string") {
    return window.location.search;
  }
  return "";
}

function peopleHref() {
  const search = currentPageSearch();
  if (!search) return "./people.html";
  try {
    if (typeof URLSearchParams === "function") {
      const params = new URLSearchParams(search);
      if (params.has("theme") && (state.theme === "light" || state.theme === "dark")) {
        params.set("theme", state.theme);
        const serialized = params.toString();
        return "./people.html" + (serialized ? "?" + serialized : "");
      }
    }
  } catch (error) { /* 忽略非法查询串 */ }
  return "./people.html" + search;
}

function syncPeopleLinks() {
  if (typeof document === "undefined" || !document || typeof document.querySelectorAll !== "function") return;
  const href = peopleHref();
  $$('a[data-people-link], a[href^="./people.html"]').forEach((link) => {
    if (link && typeof link.setAttribute === "function") link.setAttribute("href", href);
  });
}

function applyTheme(theme, options = {}) {
  state.theme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = state.theme;
  const label = $("#themeToggleLabel");
  if (label) label.textContent = state.theme === "dark" ? "深色" : "浅色";
  const meta = typeof document.querySelector === "function" ? $('meta[name="theme-color"]') : null;
  if (meta && typeof meta.setAttribute === "function") {
    meta.setAttribute("content", state.theme === "light" ? "#f6f7fa" : "#0b0d12");
  }
  syncPeopleLinks();
  try {
    window.localStorage.setItem(THEME_KEY, state.theme);
  } catch (error) {
    /* 忽略存储禁用 */
  }
  window.dispatchEvent(new CustomEvent("mc:theme", { detail: state.theme }));
  // 2.6.6：localStorage 在部分 WebView 里会被清掉，主题再落一份到插件数据目录
  if (options.persist !== false) {
    state.manualThemeToggled = true;
    state.explicitTheme = state.theme;
    apiPost("/ui-preferences/save", { dark_mode: state.theme === "dark" }).catch(() => {});
  }
}

function handleBridgeContext(ctx) {
  if (!ctx || typeof ctx !== "object" || typeof ctx.isDark !== "boolean") return;
  const hostTheme = ctx.isDark ? "dark" : "light";
  const prevHostIsDark = state.lastHostIsDark;
  state.lastHostIsDark = ctx.isDark;
  if (prevHostIsDark !== null && prevHostIsDark !== ctx.isDark) {
    state.explicitTheme = "";
    applyTheme(hostTheme, { persist: false });
    return;
  }
  if (state.manualThemeToggled || state.explicitTheme) {
    applyTheme(state.explicitTheme || state.theme, { persist: false });
    return;
  }
  if (hostTheme !== state.theme) {
    applyTheme(hostTheme, { persist: false });
  }
}

async function bindBridgeContext() {
  const bridge = getBridge() || (await waitForBridge());
  if (!bridge) return;
  if (typeof bridge.onContext === "function") {
    bridge.onContext(handleBridgeContext);
  } else if (typeof bridge.getContext === "function") {
    handleBridgeContext(bridge.getContext());
  }
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
    views: ["microscope", "synergy"],
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
    views: ["chatimport", "migrate", "queue", "quarantine", "processed"],
  },
  {
    id: "settings",
    label: "设置",
    icon: "sliders",
    views: ["config", "performance", "acl"],
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
  if (!host) return;
  const peopleEntry =
    '<div class="nav-people-wrap">' +
    '<a class="nav-item nav-people" id="railPeopleLink" data-people-link href="' + esc(peopleHref()) + '" title="返回「她记得的人」人物面板">' +
    icon("heart") +
    '<span class="nav-label">她记得的人</span>' +
    '<span class="nav-ext" aria-hidden="true">↗</span>' +
    "</a></div>";
  host.innerHTML = peopleEntry + NAV.map((group) => {
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
function kpi(label, value, foot, tone, goto, iconName, filter) {
  const inner =
    (iconName ? icon(iconName, "kpi-icon") : "") +
    '<span class="kpi-label">' + esc(label) + "</span>" +
    '<span class="kpi-value">' + esc(value) + "</span>" +
    (foot ? '<span class="kpi-foot">' + esc(foot) + "</span>" : "");
  const toneAttr = tone ? ' data-tone="' + esc(tone) + '"' : "";
  if (goto) {
    return (
      '<button class="kpi is-link" type="button"' + toneAttr +
      ' data-goto="' + esc(goto) + '"' +
      (filter ? ' data-filter="' + esc(filter) + '"' : "") + ">" +
      inner +
      '<span class="kpi-go" aria-hidden="true">›</span></button>'
    );
  }
  return '<article class="kpi"' + toneAttr + ">" + inner + "</article>";
}

function badge(text, tone) {
  return '<span class="badge' + (tone ? '" data-tone="' + esc(tone) : "") + '">' + esc(text) + "</span>";
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
function summaryWaitDuration(seconds) {
  const value = Math.max(0, int(seconds));
  if (value === 0) return "无";
  if (value < 60) return "不足 1 分钟";
  if (value >= 86400) return Math.floor(value / 86400) + " 天 " + Math.floor(value % 86400 / 3600) + " 小时";
  if (value >= 3600) return Math.floor(value / 3600) + " 小时 " + Math.floor(value % 3600 / 60) + " 分钟";
  return Math.floor(value / 60) + " 分钟";
}

function summaryWaitTone(key) {
  if (key === "identity" || key === "retry" || key === "paused" || key === "disabled") return "warn";
  if (key === "call_limit") return "danger";
  if (key === "running") return "ok";
  return "fact";
}

function summaryRecoveryCard(status) {
  if (!status || typeof status !== "object") {
    return card("记忆整理进度", "只读状态", emptyState("状态暂不可用", "请使用已登录的管理员面板刷新。"), "", "recovery-card");
  }
  const waits = status.waits || {};
  const originals = status.unbatched || {};
  const progress = status.progress || {};
  const labels = status.wait_labels || {};
  const rows = Object.keys(labels).filter((key) => int(waits[key]) > 0).map((key) =>
    '<div class="row"><div class="row-main"><div class="row-title" title="' + esc(labels[key]) + '">' + esc(labels[key]) +
    '</div></div><div class="row-meta">' + badge(fmtInt(waits[key]) + " 批", summaryWaitTone(key)) + "</div></div>"
  ).join("");
  const originalWaits = Object.keys(labels).filter((key) => int((originals.waits || {})[key]) > 0)
    .map((key) => labels[key] + " " + fmtInt(originals.waits[key]) + " 个窗口").join(" · ");
  const mode = !status.summary_enabled ? "自动总结已关闭"
    : status.admission !== "normal" ? "已暂停常规整理"
    : !status.recovery_enabled ? "后台恢复已关闭，聊天仍可触发整理"
    : status.dispatcher_state === "degraded" ? "后台恢复已开启（调度器异常）"
    : "后台恢复已开启";
  return card("记忆整理进度", mode,
    '<div class="pill-row">' +
      badge("待处理 " + fmtInt(status.pending_batches) + " 批", "accent") +
      badge("最老等待 " + summaryWaitDuration(status.oldest_wait_seconds), "fact") +
      badge("每会话每小时 " + ((status.limits || {}).calls_per_session_hour === 0 ? "不限" : fmtInt((status.limits || {}).calls_per_session_hour) + " 次")) +
      badge("全局并发 " + fmtInt((status.limits || {}).global_concurrency)) +
    '</div><div class="row-list">' + (rows || emptyState("没有有效待处理批次", "空白历史行不计入积压。")) + '</div>' +
    '<p class="section-note">未分批原文 ' + fmtInt(originals.events) + " 条；下一轮达到条件且身份有效 " +
      fmtInt(originals.eligible_events) + " 条（" + fmtInt(originals.eligible_windows) + " 个窗口）。这些原文尚未计入批次。" +
      (originalWaits ? " 当前：" + esc(originalWaits) + "。" : "") + '</p>' +
    '<p class="section-note">正式会话记忆 ' + fmtInt(progress.adopted_memories) + " 条 · 待审候选 " +
      fmtInt(progress.review_candidates) + " 条 · 已处理批次 " + fmtInt(progress.completed_batches) +
      " 批 · 无新增记忆 " + fmtInt(progress.no_memory_batches) + " 批 · 隔离批次 " +
      fmtInt(progress.quarantined_batches) + ' 批。</p>' +
    '<p class="section-note">可以尝试整理表示队列条件已满足；模型是否可用会在实际整理时检查。查看状态不会发起模型调用或通过候选。</p>',
    "", "recovery-card");
}

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
    '</section>' + summaryRecoveryCard(data.recovery);
}

defineView("overview", {
  title: "总览",
  navLabel: "总览",
  eyebrow: "Overview",
  hint: "记忆库规模、范围分布与联动状态的整体快照",
  async load() {
    const [statsPayload, buckets, core, caps, coord, memories, personal, injectionLogs, botsPayload, recoveryPayload] = await Promise.all([
      apiGet("/stats"),
      apiTry(() => apiGet("/buckets?limit=160"), { buckets: [] }),
      apiTry(() => apiGet("/core-memory"), { blocks: [] }),
      apiTry(() => apiGet("/capabilities/bot-personal"), {}),
      apiTry(() => apiGet("/coordination/status"), { status: {} }),
      // 列表接口必须带范围；总览用显式的 scope=all 表示“所有范围”。
      apiTry(() => apiGet("/memories?scope=all&limit=80"), { memories: [] }),
      apiTry(() => apiGet("/companion/personal-memory?limit=1"), null),
      apiTry(() => apiGet("/logs?limit=12"), { items: [] }),
      apiTry(() => apiGet("/bots"), { bots: [] }),
      apiTry(() => apiGet("/maintenance/summary_status"), null),
    ]);
    const stats = (statsPayload && statsPayload.stats) || {};
    state.stats = stats;
    state.buckets = Array.isArray(buckets.buckets) ? buckets.buckets : [];
    return {
      stats,
      recovery: recoveryPayload && recoveryPayload.status,
      buckets: state.buckets,
      core: core.blocks || [],
      caps,
      personal,
      coord: coord.status || {},
      memories: memories.memories || [],
      injectionLogs: Array.isArray(injectionLogs.items) ? injectionLogs.items : [],
      bots: Array.isArray(botsPayload.bots) ? botsPayload.bots : [],
    };
  },
  render(data) {
    if (state.mode === "cinema") return renderCinemaOverview(data);
    const stats = data.stats || {};
    const byScope = stats.by_scope || {};
    const recovery = data.recovery && typeof data.recovery === "object" ? data.recovery : null;
    const recoveryProgress = recovery && recovery.progress && typeof recovery.progress === "object" ? recovery.progress : null;
    const storageMb = (int(stats.memory_storage_bytes) / 1048576).toFixed(1);
    const privateCount = int(byScope.private);
    const groupCount = int(byScope.group);

    const kpis = [
      kpi("记忆总量", fmtInt(stats.total_memories), storageMb + " MB 存储", "accent", "inspect", "db"),
      kpi("私聊记忆", fmtInt(privateCount), "一对一会话", "private", "inspect", "user", "scope:private"),
      kpi("群聊记忆", fmtInt(groupCount), "群窗口沉淀", "group", "inspect", "users", "scope:group"),
      kpi("用户档案", fmtInt(stats.identities), "已识别身份", "relation", "inspect", "tag", "profile"),
      kpi("核心记忆", fmtInt((data.core || []).length), "强制注入块", "gold", "core", "star"),
      kpi("开放线程", fmtInt(stats.open_threads), "跨窗口续接", "fact", "navigate", "link"),
      kpi("原文已记录", recoveryProgress ? fmtInt(recoveryProgress.raw_events) : "—", "不含空白历史行", "group", "inspect", "library"),
      kpi("正式会话记忆", recoveryProgress ? fmtInt(recoveryProgress.adopted_memories) : "—", "待审候选另列", "fact", "inspect", "chat"),
      kpi("待处理批次", recovery ? fmtInt(recovery.pending_batches) : "—", "等待原因见整理进度", "accent", "queue", "clock"),
      kpi("待修复批次", recoveryProgress ? fmtInt(recoveryProgress.quarantined_batches) : "—", "总结失败被隔离", "gold", "quarantine", "shield"),
      kpi("已处理，无新增记忆", recoveryProgress ? fmtInt(recoveryProgress.no_memory_batches) : "—", "原文保留，不重复总结", "private", "processed", "box"),
    ].join("");

    const peopleEntry =
      '<a class="row" data-people-link href="' + esc(peopleHref()) + '">' +
      icon("heart", "scope-icon") +
      '<div class="row-main"><div class="row-title">她记得的人</div>' +
      '<div class="row-sub">按人查看分量、称呼与她记得的事</div></div>' +
      '<div class="row-meta"><span class="badge">前往 ↗</span></div></a>';

    const entries = peopleEntry + [
      ["navigate", "记忆导航", "按私聊 / 群聊 / 个人等范围进入", "scope"],
      ["inspect", "记忆检视", "逐条查看并修正记忆参数", "db"],
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
    const personalStatus = companionStatus(data.caps, data.personal);
    const bridgeHealth = compact(coordStatus.bridge && coordStatus.bridge.health) || "unknown";
    /* 联动要分三态，别把「没装」画成「坏了」：没装是与用户无关的中性灰点，
       装了但桥接降级才是需要去看的黄点，全红留给真出错。 */
    bridges.push([
      !personalStatus.installed ? "is-off" : bridgeHealth === "ready" ? "is-ok" : bridgeHealth === "degraded" ? "is-warn" : "is-bad",
      "陪伴插件联动",
      !personalStatus.installed
        ? "未安装陪伴插件"
        : bridgeHealth === "ready" ? "已连接" : bridgeReasonText(coordStatus.bridge && coordStatus.bridge.reason_code) || "未连接",
    ]);
    bridges.push([
      !personalStatus.installed ? "is-off" : personalStatus.available ? "is-ok" : "is-warn",
      "Bot 个人记忆",
      !personalStatus.installed
        ? "装上陪伴插件后可用"
        : personalStatus.available
          ? (personalStatus.dailyPlanEnabled ? "日程已启用" : "日程未启用") + " · " + (personalStatus.detailEnabled ? "细化已启用" : "细化未启用")
          : personalStatus.reason || "不可用",
    ]);
    const injectionLogCount = Number(stats.injection_logs) || 0;
    bridges.push([
      injectionLogCount > 0 ? "is-ok" : "is-off",
      "外部写入接口",
      injectionLogCount > 0 ? injectionLogCount + " 条注入日志" : "暂无注入日志",
    ]);
    const linkageNote = personalStatus.installed
      ? ""
      : '<p class="section-note">未检测到 astrbot_plugin_private_companion。<b>记忆功能不受影响</b>，'
        + '装上陪伴插件后这里会显示它的日程、相册与表达权威归属。'
        + '<button class="btn is-sm" type="button" data-goto="companion" style="margin-left:8px">查看联动页</button></p>';

    const injectionLogs = Array.isArray(data.injectionLogs) ? data.injectionLogs : [];
    const injectionRows = injectionLogs
      .slice(0, 12)
      .map((item) => {
        const selected = Array.isArray(item.selected_memories) ? item.selected_memories : [];
        const blocked = Array.isArray(item.blocked_reasons) ? item.blocked_reasons : [];
        const retrieval = item.retrieval_info && typeof item.retrieval_info === "object" ? item.retrieval_info : {};
        const slotCounts = retrieval.slot_counts && typeof retrieval.slot_counts === "object" ? retrieval.slot_counts : {};
        const slotLimits = retrieval.slot_limits && typeof retrieval.slot_limits === "object" ? retrieval.slot_limits : {};
        const slotSummary = Object.keys(slotCounts)
          .map((slot) => slot + " " + Number(slotCounts[slot] || 0) + "/" +
            (slotLimits[slot] == null ? "-" : Number(slotLimits[slot] || 0)))
          .join(" · ");
        const capped = Array.isArray(retrieval.capped_slots) ? retrieval.capped_slots : [];
        const cappedCandidates = blocked
          .filter((entry) => String(entry.reason || "").startsWith("slot_capped:"))
          .map((entry) => String(entry.id || "") + (entry.score == null ? "" : " (" + entry.score + ")"))
          .filter(Boolean)
          .slice(0, 3);
        const query = compact(item.query) || "无检索词";
        const scopeTag = (memory) => {
          const key = compact(memory.scope);
          if (key === "group") return "群聊·";
          if (key === "private") return "私聊·";
          if (key === "profile") return "档案·";
          if (key === "personal") return "Bot·";
          return "";
        };
        const selectedText = selected.length
          ? selected
              .slice(0, 2)
              .map((memory) => {
                const logSession = compact(item.session_id);
                const memorySession = compact(memory.session_id);
                const cross = logSession && memorySession && logSession !== memorySession ? "↔跨窗口 " : "";
                return cross + scopeTag(memory) + memoryTitle(memory);
              })
              .join("；")
          : blocked.length
            ? "未注入记忆 · 过滤 " + blocked.length + " 项"
            : "未注入记忆";
        const detailText = [
          selectedText,
          slotSummary ? "槽位 " + slotSummary : "",
          capped.length ? "受限 " + capped.join(", ") : "",
          cappedCandidates.length ? "限流候选 " + cappedCandidates.join(", ") : "",
        ].filter(Boolean).join(" · ");
        return (
          '<div class="row" style="cursor:default;align-items:flex-start">' +
            '<div class="row-main" style="min-width:0">' +
              '<div class="row-title" title="' + esc(query) + '">' + esc(clip(query, 72)) + "</div>" +
              '<div class="row-sub">' + esc(fmtTime(item.created_at)) + " · " +
                esc(selected.length + " 条记忆 · " + int(item.injection_chars) + " 字") + "</div>" +
              '<div class="section-note" style="margin-top:5px;white-space:normal">' + esc(clip(detailText, 280)) + "</div>" +
            "</div>" +
            '<div class="row-meta">' +
              badge(selected.length ? "已注入" : "未注入", selected.length ? "ok" : "warn") +
              (blocked.length ? badge("过滤 " + blocked.length, "") : "") +
            "</div>" +
          "</div>"
        );
      })
      .join("");
    const fallbackOwners = (stats && stats.by_owner_bot) || {};
    const botOwners = Array.isArray(data.bots) && data.bots.length
      ? data.bots
      : Object.keys(fallbackOwners).map((key) => ({
          id: key === "<empty>" ? "" : key,
          name: "",
          count: int(fallbackOwners[key]),
        }));
    const personaName = compact(data.persona);
    const botTotal = botOwners.reduce((sum, item) => sum + int(item.count), 0) || 1;
    const botRows = botOwners
      .map((item) => {
        const count = int(item.count);
        const botId = compact(item.id);
        const ownerKey = botId || "__empty__";
        const title = compact(item.name) || personaName || (botId ? "Bot " + botId : "未标记归属");
        const sub = botId && compact(item.name) ? botId : "";
        return (
          '<button class="row is-clickable" type="button" data-goto="inspect" data-owner-bot="' + esc(ownerKey) + '">' +
            '<div class="row-main" style="min-width:0">' +
              '<div class="row-title">' + esc(title) + (sub ? ' <span class="bot-id">' + esc(sub) + "</span>" : "") + "</div>" +
              '<div class="bot-bar"><span style="width:' + Math.max(3, Math.round((count / botTotal) * 100)) + '%"></span></div>' +
            "</div>" +
            '<div class="row-meta">' + badge(fmtInt(count) + " 条", "fact") + "</div>" +
          "</button>"
        );
      })
      .join("");
    const botCard = botOwners.length
      ? card("Bot 记忆分布", "共 " + botOwners.length + " 个归属 · 点名字看这个 Bot 的记忆", '<div class="row-list">' + botRows + "</div>", '<button class="btn is-sm is-ghost" type="button" data-goto="inspect" data-filter="all">全部记忆</button>')
      : card("Bot 记忆分布", "还没有归属数据", emptyState("暂无归属", "记忆写入后会按 Bot 归属统计。"));

    const drainInfo = (stats && stats.summary_drain) || {};
    const drainLabel =
      drainInfo.state === "running" ? "正在消化积压"
      : drainInfo.state === "degraded" ? "上一轮出错"
      : drainInfo.state === "scheduled" ? "等待下一轮"
      : "未启动";
    const drainCard = card(
      "自动消化",
      "后台定时扫未总结的原文",
      '<div class="row-list">' +
        '<div class="row"><div class="row-main"><div class="row-title">' + esc(drainLabel) + "</div>" +
          '<div class="row-sub">' + esc(compact(drainInfo.last_result) || "还没有跑过") + "</div></div>" +
          '<div class="row-meta">' + esc(compact(drainInfo.last_completed_at) || "—") + "</div></div>" +
        (compact(drainInfo.last_error)
          ? '<div class="row"><div class="row-main"><div class="row-title">最近错误</div><div class="row-sub">' + esc(drainInfo.last_error) + "</div></div></div>"
          : "") +
      "</div>",
      '<button class="btn is-sm is-ghost" type="button" data-goto="queue">看排队中</button>'
    );

    const injectionCard = card(
      "最近注入",
      injectionLogs.length ? "最近 12 轮主链注入记录" : "暂无可展示的注入记录",
      injectionRows || emptyState("暂无注入记录", "开启记忆注入并产生请求后，这里会显示最近轮次。"),
      '<button class="btn is-sm is-ghost" type="button" data-refresh-injection>刷新</button>'
    );

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
              "</div>" + linkageNote
          ) +
        "</div>" +
      "</div>" +
      botCard +
      drainCard +
      summaryRecoveryCard(recovery) +
      '<div class="grid g4">' +
        kpi("稳定记忆", fmtInt(stats.stable_memories), "lifecycle=stable_memory", "fact", "inspect", "heart") +
        kpi("时间线事件", fmtInt(stats.timeline_events), "结构化事件流", "group", "navigate", "clock") +
        kpi("关系边", fmtInt(stats.relationships), "实体间关系", "relation", "navigate", "link") +
        kpi("ACL 规则", fmtInt(stats.acl_rules), "跨窗口读写授权", "gold", "acl", "shield") +
      "</div>" +
      injectionCard +
      "</div>"
    );
  },
  mount(node) {
    $("[data-refresh-injection]", node)?.addEventListener("click", () => refresh());
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
  const result = await apiGet("/memories?scope=all&limit=200");
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
    if (filters.ownerBot) params.push("owner_bot=" + encodeURIComponent(filters.ownerBot));
    if (filters.target) {
      if (filters.scope === "group") params.push("group_id=" + encodeURIComponent(filters.target));
      else params.push("entity_id=" + encodeURIComponent(filters.target));
    }
    // 没有指定范围时用显式 scope=all，而不是让后端默认放开全量。
    if (!filters.scope && !filters.target) params.push("scope=all");
    const botsPayload = await apiTry(() => apiGet("/bots"), { bots: [], persona: "" });
    const result = await apiGet("/memories?" + params.join("&"));
    let memories = Array.isArray(result.memories) ? result.memories : [];
    if (filters.scope === "profile") {
      memories = memories.filter((m) => [
        "profile", "user_profile", "user_habit",
        "preference", "user_preference",
        "relationship", "relationship_claim", "relationship_phase_summary",
      ].includes(compact(m.memory_type)));
    }
    return { memories, filters, bots: Array.isArray(botsPayload.bots) ? botsPayload.bots : [], persona: botsPayload.persona || "" };
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

    const botPills = (data.bots || []).length
      ? '<div class="pill-row">' +
        '<button class="pill' + (!filters.ownerBot ? " is-active" : "") + '" type="button" data-filter-key="ownerBot" data-filter-value="">全部 Bot</button>' +
        (data.bots || []).map((bot) => {
          const key = compact(bot.id) || "__empty__";
          const name = compact(bot.name) || compact(data.persona) || (compact(bot.id) ? "Bot " + bot.id : "未标记归属");
          return '<button class="pill' + (filters.ownerBot === key ? " is-active" : "") + '" type="button" data-filter-key="ownerBot" data-filter-value="' + esc(key) + '">' + esc(name) + " · " + fmtInt(bot.count) + "</button>";
        }).join("") +
        "</div>"
      : "";

    const activeChips = [];
    if (filters.q) activeChips.push("关键词：" + filters.q);
    if (filters.target) activeChips.push("目标：" + filters.target);
    if (filters.ownerBot) activeChips.push("Bot：" + (filters.ownerBot === "__empty__" ? "未标记归属" : filters.ownerBot));

    const rows = memories.length
      ? memories.map((memory, index) => memoryRow(memory, index)).join("")
      : emptyState("没有匹配的记忆", "试着放宽筛选条件，或清空关键词后重新加载。");

    return (
      '<div class="grid" style="gap:14px">' +
      '<section class="card is-tight">' +
        (botPills ? '<div style="display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-bottom:10px">' + botPills + "</div>" : "") +
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
          '<button class="btn is-sm is-danger" type="button" id="coreDeleteBtn" disabled>删除此块</button>' +
          '<button class="btn is-sm is-ghost" type="button" id="coreResetBtn">重置</button>' +
          '<button class="btn is-sm is-primary" type="submit">保存核心块</button>' +
        "</div>" +
      "</div>" +
      "</form>";

    return (
      '<div class="grid split-2">' +
        card(
          "核心记忆块",
          (data.blocks || []).length + " 个 · 按优先级排序",
          '<div class="row-actions" style="margin-bottom:10px">' +
            '<button class="btn is-sm" type="button" id="coreExtractBtn">从记忆提炼核心块</button>' +
            '<span class="cf-desc" style="margin-left:8px">按私聊 / 群聊 / 档案 / 全局汇总最稳定的事实</span>' +
          "</div>" +
          '<div class="row-list">' + rows + "</div>"
        ) +
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
      const deleteBtn = $("#coreDeleteBtn", node);
      if (deleteBtn) deleteBtn.disabled = !block;
    };

    $$("[data-core]", node).forEach((row) => {
      row.addEventListener("click", () => fill(blocks[row.dataset.core]));
    });

    $("#coreResetBtn", node).addEventListener("click", () => fill(null));
    $("#coreDeleteBtn", node).addEventListener("click", async () => {
      const id = $("#coreId", node).value.trim();
      if (!id) {
        toast("先选中一个核心记忆块", "warn");
        return;
      }
      const confirmed = await showInlineConfirmation("删除核心记忆块", "删除后该块不再参与注入，且不可恢复。确定删除？", "删除");
      if (!confirmed) return;
      await withBusy("正在删除…", async () => {
        const result = await apiPost("/core-memory/delete", { id: id });
        if (result && result.ok === false) {
          toast("删除失败：" + (result.code || "未知原因"), "error");
          return;
        }
        invalidatePool();
        toast("核心记忆块已删除", "ok");
        fill(null);
        refresh();
      }, 3000);
    });

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

    const extractBtn = $("#coreExtractBtn", node);
    if (extractBtn) {
      extractBtn.addEventListener("click", async () => {
        extractBtn.disabled = true;
        try {
          const pool = await apiGet("/memories?scope=all&limit=200");
          const list = Array.isArray(pool.memories) ? pool.memories : [];
          if (!list.length) {
            toast("还没有记忆可提炼，先聊几轮或导入历史", "warn");
            return;
          }
          const buckets = { private: [], group: [], profile: [], global: [] };
          list.forEach((memory) => {
            const key = compact(memory.scope) || "global";
            (buckets[key] || buckets.global).push(memory);
          });
          const labels = { private: "私聊稳定事实", group: "群聊稳定事实", profile: "用户档案要点", global: "全局规则与偏好" };
          const candidates = Object.keys(labels)
            .map((scope) => {
              const items = buckets[scope] || [];
              if (!items.length) return null;
              const facts = [];
              items
                .slice()
                .sort((a, b) => (Number(b.salience) || 0) - (Number(a.salience) || 0))
                .forEach((memory) => {
                  const keyFacts = Array.isArray(memory.key_facts) ? memory.key_facts : [];
                  if (keyFacts.length) {
                    keyFacts.forEach((fact) => {
                      if (compact(fact)) facts.push(compact(fact));
                    });
                  } else if (compact(memory.content)) {
                    facts.push(clip(compact(memory.content), 60));
                  }
                });
              const unique = Array.from(new Set(facts.filter(Boolean))).slice(0, 8);
              if (!unique.length) return null;
              return {
                label: labels[scope],
                kind: "fact",
                scope: scope === "profile" ? "global" : scope,
                priority: 60,
                content: unique.join("；"),
                enabled: true,
              };
            })
            .filter(Boolean);
          if (!candidates.length) {
            toast("没提炼出可用的事实", "warn");
            return;
          }
          const previewText = candidates.map((item) => item.label + "：" + clip(item.content, 46)).join("；");
          const confirmed = await showInlineConfirmation(
            "从记忆提炼核心块",
            "将生成 " + candidates.length + " 个核心块，可在列表里再改或删。" + previewText,
            "写入 " + candidates.length + " 个"
          );
          if (!confirmed) return;
          await withBusy("正在写入…", async () => {
            let done = 0;
            for (const candidate of candidates) {
              const result = await apiPost("/core-memory/upsert", candidate);
              if (result && result.ok !== false) done += 1;
            }
            invalidatePool();
            toast("已写入 " + done + " 个核心块", done ? "ok" : "warn");
            refresh();
          }, 900);
        } catch (error) {
          toast("提炼失败：" + (error.message || error), "error");
        } finally {
          extractBtn.disabled = false;
        }
      });
    }
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

function closeLightbox(box) {
  if (!box || box.dataset.closing === "1") return;
  box.dataset.closing = "1";
  box.classList.remove("is-open");
  if (prefersReducedMotion()) {
    box.remove();
  } else {
    window.setTimeout(() => box.remove(), 180);
  }
}

function openLightbox(src, caption) {
  const box = document.createElement("div");
  box.className = "lightbox";
  box.innerHTML = '<img src="' + esc(src) + '" alt="" /><div class="lightbox-cap">' + esc(caption || "") + "</div>";
  box.addEventListener("click", () => closeLightbox(box));
  document.body.appendChild(box);
  if (prefersReducedMotion()) {
    box.classList.add("is-open");
  } else {
    void box.offsetWidth;
    requestAnimationFrame(() => {
      if (box.dataset.closing !== "1") box.classList.add("is-open");
    });
  }
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



function hexAlpha(hex, alpha) {
  const value = compact(hex).replace("#", "");
  const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value;
  const r = parseInt(full.slice(0, 2), 16) || 0;
  const g = parseInt(full.slice(2, 4), 16) || 0;
  const b = parseInt(full.slice(4, 6), 16) || 0;
  return "rgba(" + r + "," + g + "," + b + "," + clamp(alpha, 0, 1).toFixed(3) + ")";
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
    const coord = data.coord || {};
    const bridge = coord.bridge || {};
    const status = companionStatus(data.caps, data.personal);

    const installed = status.installed;
    const offOr = (ok, warn) => (installed ? (ok ? "is-ok" : warn ? "is-warn" : "is-bad") : "is-off");

    const items = [];
    items.push([
      installed ? (status.available ? "is-ok" : "is-warn") : "is-off",
      "插件安装",
      installed ? status.pluginName || "已安装" : "未安装 astrbot_plugin_private_companion",
    ]);
    items.push([
      !installed ? "is-off" : bridge.health === "ready" ? "is-ok" : bridge.health === "degraded" ? "is-warn" : "is-bad",
      "桥接状态",
      !installed ? "需先安装陪伴插件" : bridgeHealthText(bridge),
    ]);
    items.push([
      offOr(status.dailyPlanEnabled, true),
      "每日日程",
      installed ? (status.dailyPlanEnabled ? "已启用" : "未启用") : "不可用",
    ]);
    items.push([
      offOr(status.detailEnabled, true),
      "细化增强",
      installed ? (status.detailEnabled ? "已启用" : "未启用") : "不可用",
    ]);
    if (installed && data.personal && data.personal.available) {
      items.push(["is-ok", "可选日期", (data.personal.dates || []).length + " 天有记录"]);
      items.push(["is-ok", "相册", ((data.personal.snapshot || {}).album || []).length + " 张"]);
    }

    const bridgeReason = compact(bridge.reason_code);
    const p6 = coord.p6 || null;
    const runtime = coord.runtime || {};
    const runtimeLabel = runtimeHealthText(runtime);

    return (
      '<div class="grid" style="gap:16px">' +
      '<div class="grid split-2">' +
        card(
          "联动状态",
          !installed ? "未安装陪伴插件" : status.available ? "已连接" : "已安装但未连通",
          '<div class="row-list" style="gap:6px">' +
            items.map((item) => '<div class="link-item ' + item[0] + '"><span class="link-dot"></span><b>' + esc(item[1]) + "</b><span>" + esc(item[2]) + "</span></div>").join("") +
            "</div>" +
            (bridgeReason && installed
              ? '<p class="section-note"' + (REASON_TEXT[bridgeReason] ? ' title="' + esc(bridgeReason) + '"' : "") + ">"
                + esc(REASON_TEXT[bridgeReason] || bridgeReason) + "</p>"
              : !installed ? '<p class="section-note">未安装陪伴插件 astrbot_plugin_private_companion。记忆与注入照常工作，日程、相册与表达权威归属需要它。安装并启用后本页会自动显示真实状态。</p>' : "") +
            (installed
              ? '<div class="pill-row" style="margin-top:12px"><button class="btn is-sm" type="button" data-goto="botlife">查看 Bot 日程与相册</button></div>'
              : "")
        ) +
        card(
          "协调契约",
          "只读投影 · 不在本插件持久化",
          '<dl class="kv">' +
            "<dt>契约版本</dt><dd>" + esc(compact(coord.schema_version) || "-") + "</dd>" +
            "<dt>契约指纹</dt><dd>" + esc(compact(coord.contract_fingerprint) || "-") + "</dd>" +
            "<dt>兼容等级</dt><dd>" + esc(runtimeLabel) + "</dd>" +
            "<dt>桥接状态</dt><dd>" + esc(bridgeHealthText(bridge)) + "</dd>" +
            (installed
              ? "<dt>表达权威</dt><dd>private_companion</dd>"
              : "<dt>表达权威</dt><dd>无（未安装陪伴插件）</dd>") +
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
      '<label class="field"><span>关联人物 ID</span><input id="impPersonId" type="text" placeholder="person_...（可留空）" /></label>' +
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
    const adapters = Array.isArray(caps.adapters) ? caps.adapters : [];
    const available = caps.available === true;
    const adapterError = adapters.map((item) => compact(item.error)).find((value) => value) || "";

    const qqPanel =
      '<div class="config-form">' +
      '<label class="field"><span>当前 Bot 连接</span><select id="qqPlatform"' + (available ? "" : " disabled") + ">" +
        (adapters.length
          ? adapters.map((p) => '<option value="' + esc(compact(p.platform_id)) + '">' + esc(compact(p.platform_name) || compact(p.platform_id)) + "</option>").join("")
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
      (caps.available === false ? '<p class="section-note">' + esc(adapterError || "当前连接不支持读取历史") + "</p>" : "") +
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
          try {
            const result = await apiPost("/conversation-import/qq/preview", payload);
            const preview = result.result || result;
            const previewStats = preview && preview.stats && typeof preview.stats === "object" ? preview.stats : {};
            const messageCount = int(previewStats.message_count ?? previewStats.messages ?? 0);
            if (!preview || messageCount <= 0) {
              toast("没读到这个 QQ 号的历史消息：确认号是否填对、时间范围覆盖到聊天、当前连接支持读取历史", "warn");
              return;
            }
            importState.preview = preview;
            toast("预览已生成：" + messageCount + " 条消息", "ok");
            go("chatimport");
          } catch (error) {
            toast("读取失败：" + (error.message || error), "error");
          }
        }, 1200);
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
          subject_person_id: $("#impPersonId", node).value.trim(),
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
let migrateDbShrinkReport = null;

function describeAutoVacuum(mode) {
  const n = Number(mode);
  if (n === 2) return "增量回收已开启";
  if (n === 1) return "全量自动回收";
  return "未开启增量回收";
}

function describeVacuumMode(mode) {
  const text = compact(mode);
  if (!text || text === "none") return "无须回收";
  if (text === "incremental_vacuum") return "增量无损回收";
  if (text === "full_vacuum_incremental_enabled") return "深度压缩（全量 VACUUM）并开启增量回收";
  if (text.indexOf("insufficient_disk_space") >= 0) return "磁盘剩余空间不足已取消深度压缩";
  return text;
}

function renderDbHealthCard(dbHealthRes, shrinkReport) {
  const actions =
    '<button class="btn is-sm" type="button" id="dbHealthRefreshBtn">刷新体检</button>' +
    '<button class="btn is-sm" type="button" id="dbGoPerfBtn">前往性能调优 →</button>';

  if (!dbHealthRes || !dbHealthRes.ok) {
    const errText = compact(dbHealthRes && dbHealthRes.error) || "无法读取数据库体检信息";
    const isAdminErr = /admin_required|管理员/i.test(errText);
    const body =
      '<div class="db-health-notice">' +
        '<b>' + esc(isAdminErr ? "需要面板管理员身份" : "暂未获取到体检快照") + "</b>" +
        "<p>" + esc(isAdminErr ? "请以 AstrBot 面板管理员账号登录后查看数据库体积体检与执行一键瘦身。" : errText) + "</p>" +
      "</div>";
    return '<div id="dbHealthCard" class="db-health-wrap">' + card("数据库体检与一键瘦身", "查看主库 / WAL / 副库占用与向量精度分布，无损释放空闲空间", body, actions, "db-health-card") + "</div>";
  }

  const health = dbHealthRes.health || {};
  const primary = health.primary || {};
  const files = primary.files || {};
  const scoped = health.scoped || {};
  const emb = primary.embeddings || {};
  const preflight = primary.disk_preflight || null;
  const recs = Array.isArray(primary.recommendations) ? primary.recommendations : [];
  const targetPrecision = compact(primary.vector_precision || health.configured_vector_precision, "float32");

  const kpis =
    '<div class="db-kpi-grid">' +
      '<div class="db-kpi">' +
        '<span class="db-kpi-label">主库总占用</span>' +
        '<strong class="db-kpi-val">' + esc(fmtBytes(primary.total_bytes)) + "</strong>" +
        '<span class="db-kpi-sub">主库 ' + esc(fmtBytes(files.db_bytes)) + " · WAL " + esc(fmtBytes(files.wal_bytes)) + "</span>" +
      "</div>" +
      '<div class="db-kpi">' +
        '<span class="db-kpi-label">副库占用</span>' +
        '<strong class="db-kpi-val">' + esc(fmtBytes(scoped.total_bytes || 0)) + "</strong>" +
        '<span class="db-kpi-sub">范围状态与操作副库</span>' +
      "</div>" +
      '<div class="db-kpi">' +
        '<span class="db-kpi-label">可回收空闲页</span>' +
        '<strong class="db-kpi-val">' + esc(fmtBytes(primary.freelist_bytes || 0)) + "</strong>" +
        '<span class="db-kpi-sub">' + esc(fmtInt(primary.freelist_count || 0)) + " 页 · " + esc(describeAutoVacuum(primary.auto_vacuum)) + "</span>" +
      "</div>" +
      '<div class="db-kpi">' +
        '<span class="db-kpi-label">预计转码可省</span>' +
        '<strong class="db-kpi-val' + (Number(emb.estimated_transcode_savings_bytes || 0) > 0 ? " is-highlight" : "") + '">' + esc(fmtBytes(emb.estimated_transcode_savings_bytes || 0)) + "</strong>" +
        '<span class="db-kpi-sub">当前配置精度：' + esc(targetPrecision) + "</span>" +
      "</div>" +
    "</div>";

  const totalRows = Math.max(0, int(emb.total_rows));
  const f64 = Math.max(0, int(emb.float64_rows));
  const f32 = Math.max(0, int(emb.float32_rows));
  const f16 = Math.max(0, int(emb.float16_rows));
  const jsonRows = Math.max(0, int(emb.json_rows));
  const orphans = Math.max(0, int(emb.archived_orphan_rows));
  const pct = (n) => (totalRows > 0 ? Math.max(n > 0 ? 2 : 0, Math.round((n / totalRows) * 1000) / 10) : 0);

  const vecBar =
    '<div class="db-vec-section">' +
      '<div class="db-vec-head">' +
        '<span class="db-vec-title">向量存储精度分布（共 ' + esc(fmtInt(totalRows)) + " 条 · 约 " + esc(fmtBytes(emb.vector_bytes || 0)) + "）</span>" +
        (orphans > 0 ? '<span class="db-vec-orphan">含 ' + esc(fmtInt(orphans)) + " 条已归档/孤儿向量可清理</span>" : '<span class="db-vec-clean">无孤儿向量残留</span>') +
      "</div>" +
      '<div class="db-vec-bar" aria-label="向量存储精度占比">' +
        (totalRows > 0
          ? (f64 > 0 ? '<i class="seg-f64" style="width:' + pct(f64) + '%" title="float64: ' + f64 + '"></i>' : "") +
            (f32 > 0 ? '<i class="seg-f32" style="width:' + pct(f32) + '%" title="float32: ' + f32 + '"></i>' : "") +
            (f16 > 0 ? '<i class="seg-f16" style="width:' + pct(f16) + '%" title="float16: ' + f16 + '"></i>' : "") +
            (jsonRows > 0 ? '<i class="seg-json" style="width:' + pct(jsonRows) + '%" title="JSON: ' + jsonRows + '"></i>' : "")
          : '<i class="seg-empty" style="width:100%"></i>') +
      "</div>" +
      '<div class="db-vec-legend">' +
        '<span><em class="dot-f64"></em>旧版 float64：' + esc(fmtInt(f64)) + "</span>" +
        '<span><em class="dot-f32"></em>标准 float32：' + esc(fmtInt(f32)) + "</span>" +
        '<span><em class="dot-f16"></em>半精度 float16：' + esc(fmtInt(f16)) + "</span>" +
        '<span><em class="dot-json"></em>旧 JSON：' + esc(fmtInt(jsonRows)) + "</span>" +
      "</div>" +
    "</div>";

  const recHtml = recs.length
    ? '<ul class="db-rec-list">' + recs.map((item) => "<li>" + esc(item) + "</li>").join("") + "</ul>"
    : '<div class="db-rec-ok">数据库体积与索引状态健康，当前无需强制整理。</div>';

  let preflightHtml = "";
  if (preflight && preflight.ok === false) {
    preflightHtml =
      '<div class="db-preflight-warn">' +
        "<b>深度压缩空间预检未通过</b>" +
        "<span>" + esc(preflight.message || "磁盘剩余空间不足 2.2 倍主库大小 + 64 MiB，已阻止全量 VACUUM。") + "</span>" +
      "</div>";
  } else if (preflight && preflight.available_free_bytes != null) {
    preflightHtml =
      '<div class="db-preflight-ok">' +
        "磁盘当前剩余约 " + esc(fmtBytes(preflight.available_free_bytes)) +
        "（满足深度压缩 2.2× 安全门槛 " + esc(fmtBytes(preflight.required_free_bytes)) + "）" +
      "</div>";
  }

  let reportHtml = "";
  if (shrinkReport && shrinkReport.ok) {
    const pRes = shrinkReport.primary || {};
    const tc = pRes.transcode || {};
    reportHtml =
      '<div class="db-shrink-report">' +
        '<b>最近一次瘦身结果：' + esc(fmtBytes(pRes.before_bytes)) + " → " + esc(fmtBytes(pRes.after_bytes)) +
        "（释放 " + esc(fmtBytes(pRes.bytes_reclaimed)) + "）</b>" +
        "<span>转码向量 " + esc(fmtInt(tc.transcoded || 0)) + " 条 · 清理孤儿 " + esc(fmtInt(tc.purged_orphans || 0)) +
        " 条 · 回收方式：" + esc(describeVacuumMode(pRes.vacuum_mode)) + "</span>" +
        (shrinkReport.notice ? '<span class="db-shrink-notice">' + esc(shrinkReport.notice) + "</span>" : "") +
      "</div>";
  }

  const actionBar =
    '<div class="db-action-bar">' +
      '<div class="db-action-btns">' +
        '<button class="btn is-primary" type="button" id="dbShrinkRegularBtn">一键常规无损瘦身（推荐）</button>' +
        '<button class="btn is-warn-outline" type="button" id="dbShrinkFullBtn">深度整理压缩（全量 VACUUM）</button>' +
      "</div>" +
      '<div class="db-action-hint">常规瘦身在线执行不卡聊天（转码旧向量 + 清理孤儿 + 增量回收 + 截断 WAL）；深度压缩会重建主库文件彻底归还硬盘空间，期间写入短暂暂停数秒。</div>' +
    "</div>";

  return (
    '<div id="dbHealthCard" class="db-health-wrap">' +
    card(
      "数据库体检与一键瘦身",
      "实时查看主库、WAL、副库占用与向量精度分布，一键安全释放冗余体积",
      kpis + vecBar + recHtml + preflightHtml + reportHtml + actionBar,
      actions,
      "db-health-card"
    ) +
    "</div>"
  );
}

defineView("migrate", {
  title: "维护与迁移",
  navLabel: "维护与迁移",
  eyebrow: "Import · Maintenance",
  hint: "数据库体检瘦身、功能预设、运维诊断、可移植数据、LivingMemory 迁移与可回滚审计",
  async load() {
    const [preset, dbHealth] = await Promise.all([
      apiTry(() => apiGet("/operations/preset"), { preset: {} }),
      apiGet("/maintenance/db_health")
        .then((res) => ({ ok: true, health: (res && res.health) || res || null }))
        .catch((err) => ({ ok: false, error: (err && err.message) || "数据库体检读取失败" })),
    ]);
    return {
      preset: preset.preset || {},
      dbHealth,
      dbShrinkReport: migrateDbShrinkReport,
      output: migrateOutput,
    };
  },
  render(data) {
    const preset = data.preset || {};
    const current = compact(preset.preset) || compact(preset.current) || "-";

    const dbHealthCard = renderDbHealthCard(data.dbHealth, data.dbShrinkReport);

    const presets =
      '<div class="tool-block"><b>1. 功能预设（轻量 / 标准 / 陪伴）</b>' +
      "<p>控制「记多少、用哪些能力」：轻量关闭外部检索调用；标准平衡功能与成本；陪伴提高关系与连续性记忆预算。与「设置 → 性能调优」互不冲突，已有 Provider 选择不会被覆盖。</p>" +
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
        title: "7. 汇总批次释放",
        desc: "被证据门禁隔离的批次会永远持有其时间线事件，那些原文不会再进入任何后续批次。填批次 ID 后由人工复核决定：重新排队（事件交还，可被新批次消费）或放弃（永久删除原文，无法通过重新排队恢复）。",
        input: "releaseBatchId",
        placeholder: "sb_... 批次 ID",
        actions: [
          ["releaseRetryBtn", "重新排队"],
          ["releaseDiscardBtn", "放弃并关闭"],
        ],
      },
      {
        title: "8. 可回滚记忆审计",
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
        title: "9. 危险清理",
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
      dbHealthCard +
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

    const refreshHealthBtn = $("#dbHealthRefreshBtn", node);
    if (refreshHealthBtn) {
      refreshHealthBtn.addEventListener("click", () => go("migrate"));
    }
    const goPerfBtn = $("#dbGoPerfBtn", node);
    if (goPerfBtn) {
      goPerfBtn.addEventListener("click", () => go("performance"));
    }
    const runDbShrink = async (fullVacuum) => {
      if (fullVacuum) {
        const confirmed = await showInlineConfirmation(
          "确认执行深度整理压缩（全量 VACUUM）",
          "将重写整座记忆主库并开启增量回收，以彻底归还空闲磁盘空间。执行期间记忆写入会短暂暂停数秒（不影响日常聊天放行），且系统会自动检查磁盘剩余空间 ≥ 2.2 倍主库大小 + 64 MiB。确定继续？",
          "开始深度压缩"
        );
        if (!confirmed) return;
      }
      const label = fullVacuum ? "深度整理压缩" : "一键常规无损瘦身";
      await withBusy(label + "中…", async () => {
        try {
          const res = await apiPost("/maintenance/db_optimize", { run_full_vacuum: Boolean(fullVacuum) });
          migrateDbShrinkReport = res;
          migrateOutput = res;
          const reclaimed = res && res.primary ? fmtBytes(res.primary.bytes_reclaimed || 0) : "0 B";
          toast(label + "完成（释放 " + reclaimed + "）", "ok");
          invalidatePool();
        } catch (error) {
          migrateOutput = { error: error.message };
          toast(label + "失败：" + error.message, "error");
        }
        await go("migrate");
      });
    };
    const shrinkRegularBtn = $("#dbShrinkRegularBtn", node);
    if (shrinkRegularBtn) shrinkRegularBtn.addEventListener("click", () => runDbShrink(false));
    const shrinkFullBtn = $("#dbShrinkFullBtn", node);
    if (shrinkFullBtn) shrinkFullBtn.addEventListener("click", () => runDbShrink(true));

    if (state.pendingViewFocus && state.pendingViewFocus.viewId === "migrate") {
      const targetId = state.pendingViewFocus.target;
      state.pendingViewFocus = null;
      const targetEl = targetId ? $("#" + targetId, node) : null;
      if (targetEl) {
        requestAnimationFrame(() => {
          try { targetEl.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" }); } catch (err) { /* 忽略 */ }
          targetEl.classList.add("is-search-hit");
          window.setTimeout(() => targetEl.classList.remove("is-search-hit"), 2200);
        });
      }
    }

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
    bind("#releaseRetryBtn", () => {
      const batchId = $("#releaseBatchId", node).value.trim();
      if (!batchId) throw new Error("请先填写批次 ID");
      return apiPost("/maintenance/release_summary_batch", { batch_id: batchId, mode: "retry" });
    }, "释放批次事件");
    bind("#releaseDiscardBtn", async () => {
      const batchId = $("#releaseBatchId", node).value.trim();
      if (!batchId) throw new Error("请先填写批次 ID");
      const confirmed = await showInlineConfirmation(
        "放弃该批次的事件",
        "这些原始消息将被永久删除，不会进入长期记忆，且无法通过重新排队恢复。确定继续？",
        "放弃"
      );
      if (!confirmed) throw new Error("已取消");
      return apiPost("/maintenance/release_summary_batch", { batch_id: batchId, mode: "discard" });
    }, "放弃批次事件");
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
   视图：待修复批次
   ============================================================ */
const QUARANTINE_PAGE_SIZE = 50;
let quarantineOffset = 0;
let queueOffset = 0;
let processedOffset = 0;
let quarantineTab = "quarantined";

const BATCH_TAB_META = {
  quarantined: {
    title: "待修复批次",
    eyebrow: "Quarantine · Review",
    hint: "被隔离的总结批次：原文事件已冻结，需人工复核后重新排队或放弃",
  },
  pending: {
    title: "排队处理",
    eyebrow: "Queue · Pending",
    hint: "排队等待整理的批次，只读；具体等待原因见整理进度，总结失败的会进入「待修复」",
  },
  processed: {
    title: "已处理批次",
    eyebrow: "Processed · History",
    hint: "已经总结完的批次：产出记忆或确认没有新增，只读",
  },
};

const batchesView = (fixedTab, viewId, getOffset, setOffset) => {
  const meta = BATCH_TAB_META[fixedTab];
  const isRepair = fixedTab === "quarantined";
  return {
    title: meta.title,
    navLabel: meta.title,
    eyebrow: meta.eyebrow,
    hint: meta.hint,
    async load() {
      const [batches, recovery] = await Promise.all([
        apiTry(() => apiGet("/maintenance/summary_batches?state=" + fixedTab + "&limit=" + QUARANTINE_PAGE_SIZE + "&offset=" + getOffset()), { total: 0, legacy_failures: 0, batches: [] }),
        fixedTab === "pending" ? apiTry(() => apiGet("/maintenance/summary_status"), null) : null,
      ]);
      return { ...batches, recovery: recovery && recovery.status };
    },
    render(data) {
      const total = int(data.total);
      const legacy = int(data.legacy_failures);
      const batches = Array.isArray(data.batches) ? data.batches : [];
      const offset = getOffset();
      const pageTo = offset + batches.length;

      const tone = isRepair ? "gold" : fixedTab === "pending" ? "accent" : "private";
      const summary =
        '<div class="pill-row" style="gap:8px;margin-bottom:12px">' +
        badge(meta.title + " " + fmtInt(total), tone) +
        (isRepair ? badge("旧版失败记录 " + fmtInt(legacy), "fact") : "") +
        "</div>";

      const bulk = isRepair
        ? '<div class="tool-actions" style="margin-bottom:12px">' +
          '<button class="btn is-sm" type="button" id="qRetryAllBtn">全部重新排队</button>' +
          '<button class="btn is-sm is-danger" type="button" id="qDiscardAllBtn">全部放弃</button>' +
          '<button class="btn is-sm" type="button" id="qRefreshBtn">刷新</button>' +
          '<button class="btn is-sm" type="button" data-goto="queue">看排队处理</button>' +
          '<button class="btn is-sm" type="button" data-goto="processed">看已处理</button>' +
          "</div>"
        : '<div class="tool-actions" style="margin-bottom:12px">' +
          '<span class="kpi-foot" style="align-self:center">' +
          (fixedTab === "pending"
            ? "请结合整理进度查看等待原因；身份缺失或冲突的批次不会自动调用模型。"
            : "这些批次已经处理完，仅供查阅；失败的会进「待修复」。") +
          "</span>" +
          '<button class="btn is-sm" type="button" id="qRefreshBtn">刷新</button>' +
          '<button class="btn is-sm" type="button" data-goto="quarantine">去待修复</button>' +
          (fixedTab === "pending"
            ? '<button class="btn is-sm" type="button" data-goto="processed">看已处理</button>'
            : '<button class="btn is-sm" type="button" data-goto="queue">看排队处理</button>') +
          "</div>";

      const pager =
        '<div class="pill-row" style="justify-content:space-between;align-items:center;margin-top:12px">' +
        '<button class="btn is-sm" type="button" id="qPrevBtn"' + (offset <= 0 ? " disabled" : "") + ">上一页</button>" +
        '<span class="kpi-foot">' + (batches.length ? offset + 1 + "–" + pageTo + " / " + fmtInt(total) : "无记录") + "</span>" +
        '<button class="btn is-sm" type="button" id="qNextBtn"' + (pageTo >= total ? " disabled" : "") + ">下一页</button>" +
        "</div>";

      const rows = batches.length
        ? '<div class="row-list">' +
          batches
            .map((item) =>
              '<div class="row">' +
              '<div class="row-main">' +
              '<div class="row-title">' + esc(compact(item.session_id)) + "</div>" +
              '<div class="row-sub">' + esc(compact(item.last_error) || "（无错误摘要）") + "</div>" +
              '<div class="row-sub" style="font-family:var(--font-mono)">' + esc(item.id) + "</div>" +
              '<div class="row-meta">' +
              badge("事件 " + fmtInt(item.event_count), "group") +
              badge(compact(item.scope), "fact") +
              (fixedTab === "processed"
                ? badge(item.state === "no_memory" ? "无新增记忆" : "已总结", item.state === "no_memory" ? "gold" : "accent")
                : "") +
              badge(String(item.updated_at || "").slice(0, 16), "private") +
              "</div></div>" +
              (isRepair
                ? '<div class="tool-actions" style="margin-top:0">' +
                  '<button class="btn is-sm" type="button" data-q-action="retry" data-q-batch="' + esc(item.id) + '">重新排队</button>' +
                  '<button class="btn is-sm is-danger" type="button" data-q-action="discard" data-q-batch="' + esc(item.id) + '">放弃</button>' +
                  "</div>"
                : "") + "</div>"
            )
            .join("") +
          "</div>"
        : isRepair
          ? emptyState("没有待修复批次", "被隔离的总结批次会出现在这里，可逐条或整批重新排队 / 放弃。")
          : fixedTab === "pending"
            ? emptyState("没有排队中的批次", "未分批原文另见整理进度，不能据此判断所有原文已处理。")
            : emptyState("没有已处理批次", "总结完成的批次会出现在这里。");

      return (
        '<div class="grid">' +
        (fixedTab === "pending" ? summaryRecoveryCard(data.recovery) : "") +
        card(
          meta.title,
          isRepair
            ? "隔离批次持有其原文事件，释放后事件才会重新进入总结流程"
            : fixedTab === "pending"
              ? "排队等待整理的批次，只读；具体等待原因见上方整理进度，总结失败的会进入「待修复」"
              : "已完成的总结批次，仅供查阅",
          summary + bulk + rows + pager
        ) +
        "</div>"
      );
    },
    mount(node) {
      const run = async (label, fn, minMs) => {
        await withBusy(label + "…", async () => {
          try {
            const result = await fn();
            const payload = result && typeof result === "object"
              ? (result.data && typeof result.data === "object" ? result.data : result)
              : {};
            const released = payload.released;
            toast(label + (released !== undefined ? "：" + released + " 条" : "完成"), "ok");
          } catch (error) {
            toast(label + "失败：" + error.message, "error");
          }
          go(viewId);
        }, minMs === undefined ? 3000 : minMs);
      };
      const bulkRelease = async (mode, label) => {
        const info = await apiTry(() => apiGet("/maintenance/summary_batches?state=quarantined&limit=1&offset=0"), { total: 0 });
        const total = int(info.total);
        let done = 0;
        let guard = 0;
        while (guard < 500) {
          guard += 1;
          setBusyText(label + " " + done + " / " + total);
          const result = await apiPost("/maintenance/release_summary_batches", { all: true, mode, limit: 10 });
          const payload = result && typeof result === "object"
            ? (result.data && typeof result.data === "object" ? result.data : result)
            : {};
          const released = int(payload.released);
          if (released <= 0) break;
          done += released;
        }
        setBusyText(label + " " + done + " / " + total + " · 完成");
        return { data: { released: done, total } };
      };
      const bind = (id, fn, label, minMs) => {
        const button = $(id, node);
        if (button) button.addEventListener("click", () => run(label, fn, minMs));
      };
      bind("#qRefreshBtn", () => Promise.resolve({}), "刷新");
      if (isRepair) {
        bind("#qRetryAllBtn", async () => {
          const confirmed = await showInlineConfirmation("全部重新排队", "把全部待修复批次的事件交还，交给后续会话重新总结。确定继续？", "重新排队");
          if (!confirmed) throw new Error("已取消");
          return bulkRelease("retry", "已重新排队");
        }, "全部重新排队", 800);
        bind("#qDiscardAllBtn", async () => {
          const confirmed = await showInlineConfirmation("全部放弃", "全部待修复批次的原始消息将被永久删除，不会进入长期记忆，且无法通过重新排队恢复。确定继续？", "全部放弃");
          if (!confirmed) throw new Error("已取消");
          return bulkRelease("discard", "已放弃");
        }, "全部放弃", 800);
      }
      const prev = $("#qPrevBtn", node);
      if (prev) prev.addEventListener("click", () => { setOffset(Math.max(0, getOffset() - QUARANTINE_PAGE_SIZE)); go(viewId); });
      const next = $("#qNextBtn", node);
      if (next) next.addEventListener("click", () => { setOffset(getOffset() + QUARANTINE_PAGE_SIZE); go(viewId); });
      $$("[data-q-action]", node).forEach((button) => {
        button.addEventListener("click", () => {
          const batchId = button.dataset.qBatch;
          if (button.dataset.qAction === "discard") {
            run("放弃批次", async () => {
              const confirmed = await showInlineConfirmation("放弃该批次", "该批次的原始消息将被永久删除，不会进入长期记忆，且无法通过重新排队恢复。确定继续？", "放弃");
              if (!confirmed) throw new Error("已取消");
              return apiPost("/maintenance/release_summary_batches", { batch_ids: [batchId], mode: "discard" });
            });
          } else {
            run("重新排队", () => apiPost("/maintenance/release_summary_batches", { batch_ids: [batchId], mode: "retry" }));
          }
        });
      });
    },
  };
};

defineView("quarantine", batchesView("quarantined", "quarantine", () => quarantineOffset, (value) => { quarantineOffset = value; }));
defineView("queue", batchesView("pending", "queue", () => queueOffset, (value) => { queueOffset = value; }));
defineView("processed", batchesView("processed", "processed", () => processedOffset, (value) => { processedOffset = value; }));

/* ============================================================
   视图：模块配置
   ============================================================ */
const MODULE_LABELS = {
  appearance: "外观",
  memory_capture: "记忆捕获",
  scope_control: "范围控制",
  portrait: "统一画像",
  memory_assertions: "记忆断言",
  memory_summary: "记忆摘要",
  historical_chat_import: "历史聊天导入",
  retrieval: "检索",
  retrieval_advanced: "检索进阶",
  source_semantic: "原文语义",
  memory_injection: "记忆注入",
  memory_humanization: "拟人化记忆",
  conversation_memory: "对话记忆",
  conversation_memory_advanced: "对话记忆进阶",
  core_memory: "核心记忆",
  context_orchestration: "上下文编排",
  context_orchestration_advanced: "上下文编排进阶",
  persona_memory: "记得这个人",
  private_companion_bridge: "陪伴桥接",
  visibility: "可见性",
  memory_tools: "记忆工具",
  memory_reconstruction: "记忆重建",
  knowledge_graph: "知识图谱",
  livingmemory_migration: "旧版记忆迁移",
  maintenance: "维护",
  maintenance_audit: "记忆审计",
  maintenance_decay: "记忆衰减",
  startup: "启动",
  performance: "性能调优",
  identity: "跨平台身份",
};

function moduleLabel(id, moduleSchema) {
  if (MODULE_LABELS[id]) return MODULE_LABELS[id];
  const desc = compact(moduleSchema && moduleSchema.description);
  return desc || compact(id);
}

function moduleSubtitle(id, moduleSchema) {
  const title = moduleLabel(id, moduleSchema);
  const hint = compact(moduleSchema && moduleSchema.hint);
  if (hint) return hint;
  const desc = compact(moduleSchema && moduleSchema.description);
  return desc && desc !== title ? desc : "";
}

// 2.6.2：面板里只把每个模块最常用的几项摆在明面上，其余收进「高级项」折叠，
// 免得一个模块几十个输入框糊一屏、找不到该改哪一项。完整配置仍在 AstrBot 配置页。
const CONFIG_COMMON_KEYS = {
  appearance: ["theme", "ui_style"],
  memory_capture: ["enabled", "capture_user_messages", "capture_bot_responses", "extract_stable_facts"],
  scope_control: [
    "private_capture_enabled",
    "group_capture_enabled",
    "private_recall_enabled",
    "group_recall_enabled",
    "private_topology_enabled",
    "group_topology_enabled",
  ],
  portrait: ["daily_dispatch_enabled", "min_independent_evidence", "daily_success_limit_per_person"],
  memory_assertions: ["enabled", "max_per_batch"],
  memory_summary: [
    "enabled",
    "provider_id",
    "private_provider_id",
    "group_provider_id",
    "trigger_event_count",
    "trigger_interval_minutes",
    "max_summary_chars",
  ],
  historical_chat_import: ["qq_max_range_days", "qq_max_messages", "max_retries"],
  retrieval: ["embedding_enabled", "embedding_provider_id", "mode", "rerank_provider_id"],
  retrieval_advanced: [
    "vector_precision",
    "vector_storage_precision",
    "embedding_top_k",
    "embedding_weight",
    "embedding_score_threshold",
    "mmr_redundancy_weight",
  ],
  source_semantic: ["enabled", "provider_id"],
  memory_injection: ["enabled", "top_k", "max_chars", "enable_injection_logs"],
  memory_humanization: ["enabled", "vivid_full_days", "no_recall_hint_enabled"],
  conversation_memory: ["enabled", "capture_private_messages", "capture_group_messages", "idle_gap_minutes"],
  conversation_memory_advanced: [
    "cross_window_group_to_private_enabled",
    "cross_window_private_to_group_enabled",
    "cross_window_group_to_group_enabled",
    "recent_fact_guard_enabled",
    "topic_shift_guard_enabled",
  ],
  core_memory: ["enabled", "max_blocks", "max_chars"],
  context_orchestration: ["enabled", "query_mode", "include_intent_context"],
  context_orchestration_advanced: ["stable_memory_limit", "user_profile_limit", "current_window_limit"],
  persona_memory: ["enabled", "max_chars", "max_items"],
  private_companion_bridge: ["enabled", "prefer_memory_companion_memory", "accept_external_records"],
  visibility: ["allow_group_public_in_private", "hide_pending_review", "enable_acl_rules"],
  memory_tools: ["enable_recall_tool", "enable_remember_tool", "allow_group_remember", "enable_query_progress"],
  memory_reconstruction: ["enabled", "max_steps", "per_step_limit"],
  knowledge_graph: ["enabled", "retrieval_expansion_enabled"],
  livingmemory_migration: ["import_limit", "livingmemory_db_path"],
  maintenance: ["memory_decay_enabled", "auto_schedule_enabled", "retention_raw_event_days", "backup_before_import"],
  maintenance_audit: ["enabled", "max_candidates"],
  maintenance_decay: ["memory_decay_after_days", "memory_decay_idle_days", "memory_decay_gradual_enabled"],
  startup: ["background_grace_seconds"],
  performance: [
    "profile",
    "sqlite_cache_size_mb",
    "sqlite_mmap_size_mb",
    "sqlite_read_pool_size",
    "sqlite_synchronous",
  ],
  identity: ["merge_platform_accounts"],
};

const CONFIG_OPTION_LABELS = {
  "retrieval.mode": {
    auto: "自动（有重排模型时自动启用）",
    basic: "基础检索（语义 + 关键词）",
    rerank: "强制重排",
  },
  "memory_capture.proposal_mode": {
    hybrid: "混合模式（推荐）",
    summary_first: "阶段总结优先",
    explicit_only: "仅显式记住",
  },
  "context_orchestration.query_mode": {
    current_message: "按当前消息检索",
    guarded_companion: "带保护的陪伴协同",
    companion_augmented: "陪伴上下文增强",
  },
  "livingmemory_migration.default_review_status": {
    auto: "直接生效（auto）",
    pending: "进入待复核（pending）",
  },
  "retrieval_advanced.vector_precision": {
    float32: "标准精度（float32 · 推荐）",
    float16: "半精度省流（float16 · 空间直降 75%）",
  },
  "retrieval_advanced.vector_storage_precision": {
    float32: "标准精度（float32 · 推荐）",
    float16: "半精度省流（float16 · 空间直降 75%）",
  },
  "performance.profile": {
    auto: "智能自动（按机器与容器内存自动推荐）",
    eco: "省资源（1–2G 低配云服 / Docker 容器）",
    balanced: "均衡推荐（4–8G 日常主机）",
    turbo: "高性能（16G+ 桌面机 / 大记忆库）",
    compat: "慢盘 / 稳妥兼容（机械硬盘 / NAS / 弱网）",
  },
  "performance.sqlite_synchronous": {
    auto: "跟随性能档位（auto）",
    NORMAL: "NORMAL（速度与安全兼顾 · 推荐）",
    FULL: "FULL（每次提交强刷磁盘 · 防断电）",
  },
};

const PERFORMANCE_PROFILE_CHOICES = {
  auto: {
    title: "智能自动",
    tag: "推荐",
    code: "auto",
    desc: "自动识别物理内存与 Docker 限额，按需分配资源",
  },
  eco: {
    title: "省资源",
    tag: "1–2G 低配",
    code: "eco",
    desc: "半精度向量 + 关 mmap，压低内存杜绝 OOM",
  },
  balanced: {
    title: "均衡推荐",
    tag: "4–8G 主机",
    code: "balanced",
    desc: "标准精度无损召回，速度与内存均衡平稳",
  },
  turbo: {
    title: "高性能",
    tag: "16G+ 大库",
    code: "turbo",
    desc: "大页缓存 + 最高 1GB mmap + 并发读池全开",
  },
  compat: {
    title: "慢盘兼容",
    tag: "机械盘 / 弱网",
    code: "compat",
    desc: "关 mmap + FULL 严格落盘 + 5 秒宽裕等待预算",
  },
};

const VECTOR_PRECISION_CHOICES = {
  float32: {
    title: "标准精度",
    tag: "推荐",
    code: "float32",
    desc: "精度无损，空间减半 · 日常首选",
  },
  float16: {
    title: "半精度省流",
    tag: "省 75% 空间",
    code: "float16",
    desc: "空间直降 75%，召回几乎无感 · 低配云服推荐",
  },
};

const CONFIG_CHOICE_CARDS = {
  "retrieval_advanced.vector_precision": VECTOR_PRECISION_CHOICES,
  "retrieval_advanced.vector_storage_precision": VECTOR_PRECISION_CHOICES,
  "performance.profile": PERFORMANCE_PROFILE_CHOICES,
};

function fieldOptions(item) {
  if (item && Array.isArray(item.options) && item.options.length) return item.options;
  if (item && Array.isArray(item.enum) && item.enum.length) return item.enum;
  return null;
}

function renderChoiceCards(key, options, value, choiceMap, locked) {
  const current = String(value === undefined || value === null || value === "" ? options[0] : value);
  const cards = options
    .map((opt) => {
      const optStr = String(opt);
      const info = choiceMap[optStr] || { title: optStr, tag: "", code: optStr, desc: "" };
      const active = current === optStr;
      return (
        '<button type="button" class="cfg-choice-card' + (active ? " is-active" : "") + '"' +
        ' role="radio" aria-checked="' + (active ? "true" : "false") + '"' +
        ' data-choice-key="' + esc(key) + '" data-choice-val="' + esc(optStr) + '"' +
        (locked ? " disabled" : "") + ">" +
        '<span class="cfg-choice-head">' +
          '<span class="cfg-choice-dot" aria-hidden="true"></span>' +
          '<strong class="cfg-choice-title">' + esc(info.title) + "</strong>" +
          (info.tag ? '<span class="cfg-choice-tag">' + esc(info.tag) + "</span>" : "") +
          (info.code ? '<code class="cfg-choice-code">' + esc(info.code) + "</code>" : "") +
        "</span>" +
        (info.desc ? '<span class="cfg-choice-desc">' + esc(info.desc) + "</span>" : "") +
        "</button>"
      );
    })
    .join("");
  return (
    '<div class="cfg-choice-group" role="radiogroup" data-choice-group="' + esc(key) + '">' +
    '<input type="hidden" id="cfg_' + esc(key) + '" value="' + esc(current) + '"' + (locked ? " disabled" : "") + " />" +
    cards +
    "</div>"
  );
}

// P8：后端下发的受保护键（可见性 / 桥接闸门 / 凭据类）在面板里只读，
// 保存时也不提交——面板不能成为修改安全键的通道。
function protectedConfigSets(data) {
  const keys = data && Array.isArray(data.protected_keys) ? data.protected_keys : [];
  const modules = data && Array.isArray(data.protected_modules) ? data.protected_modules : [];
  return { keys: new Set(keys), modules: new Set(modules) };
}

function isProtectedConfigKey(guard, moduleId, key) {
  return guard.modules.has(moduleId) || guard.keys.has(moduleId + "." + key);
}

function orderedCommonKeys(moduleId, items) {
  const preferred = CONFIG_COMMON_KEYS[moduleId] || [];
  const out = [];
  const seen = new Set();
  for (let i = 0; i < preferred.length; i += 1) {
    const key = preferred[i];
    if (Object.prototype.hasOwnProperty.call(items, key) && !seen.has(key)) {
      seen.add(key);
      out.push(key);
    }
  }
  return out;
}

defineView("config", {
  title: "模块配置",
  navLabel: "模块配置",
  eyebrow: "Settings · Config",
  hint: "按模块调整检索、注入、编排与维护策略，保存后立即写入插件配置",
  async load(opts) {
    if (opts && opts.useCachedSchema && state.configSchema && state.configSchema.schema) {
      return state.configSchema;
    }
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
    const guard = protectedConfigSets(data);
    const totalFields = modules.reduce((sum, key) => sum + Object.keys((schema[key] || {}).items || {}).length, 0);

    const navSearch =
      '<button type="button" class="config-nav-search" data-open-config-search aria-label="全局搜索所有配置项">' +
      icon("search", "config-nav-search-icon") +
      "<span>搜索全部 " + fmtInt(totalFields) + " 项…</span>" +
      '<kbd class="cfg-kbd">' + esc(shortcutBadgeText()) + "</kbd>" +
      "</button>";

    const nav =
      navSearch +
      modules
        .map((key) => {
          const active = key === moduleId;
          return (
            '<button type="button" class="' + (active ? "is-active" : "") + '"' +
            (active ? ' aria-current="page"' : "") +
            ' data-module="' + esc(key) + '">' +
            "<span>" + esc(moduleLabel(key, schema[key])) + "</span>" +
            "<em>" + Object.keys((schema[key] || {}).items || {}).length + "</em></button>"
          );
        })
        .join("");

    const commonKeys = orderedCommonKeys(moduleId, items);
    const commonKeySet = new Set(commonKeys);
    const advancedKeys = Object.keys(items).filter((key) => !commonKeySet.has(key));
    const renderFields = (keys) =>
      keys
        .map((key) => {
          const item = items[key] || {};
          const value = moduleValues[key] === undefined ? item.default : moduleValues[key];
          const desc = compact(item.description) || key;
          const hint = compact(item.hint);
          const locked = isProtectedConfigKey(guard, moduleId, key);
          const choiceMap = CONFIG_CHOICE_CARDS[moduleId + "." + key] || null;
          const optionList = fieldOptions(item);
          const optionLabelMap = CONFIG_OPTION_LABELS[moduleId + "." + key] || null;
          const isChoiceField = Boolean(choiceMap && optionList && optionList.length);
          let input;
          if (isChoiceField) {
            input = renderChoiceCards(key, optionList, value, choiceMap, locked);
          } else if (Array.isArray(item.options) && item.options.length) {
            input =
              '<select id="cfg_' + esc(key) + '">' +
              item.options
                .map((opt) => {
                  const text = (optionLabelMap && optionLabelMap[String(opt)]) || String(opt);
                  return '<option value="' + esc(opt) + '"' + (String(value) === String(opt) ? " selected" : "") + ">" + esc(text) + "</option>";
                })
                .join("") +
              "</select>";
          } else if (Array.isArray(item.enum) && item.enum.length) {
            input =
              '<select id="cfg_' + esc(key) + '">' +
              item.enum
                .map((opt) => {
                  const text = (optionLabelMap && optionLabelMap[String(opt)]) || String(opt);
                  return '<option value="' + esc(opt) + '"' + (String(value) === String(opt) ? " selected" : "") + ">" + esc(text) + "</option>";
                })
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
          if (locked && !isChoiceField) input = input.replace(/<(input|select)/, "<$1 disabled");
          return (
            '<div class="config-field' + (isChoiceField ? " is-choice-field" : "") + '" data-config-field="' + esc(key) + '"><div><div class="cf-label">' + esc(desc) +
            (locked ? ' <span class="cf-desc">（安全键 · 只读）</span>' : "") + "</div>" +
            (hint ? '<div class="cf-desc">' + esc(hint) + "</div>" : "") +
            '<div class="cf-desc mono" style="opacity:.66;margin-top:4px">' + esc(key) + "</div></div>" +
            '<div class="cf-input">' + input + "</div></div>"
          );
        })
        .join("");
    const fields = renderFields(commonKeys);
    const advancedFields = renderFields(advancedKeys);

    return (
      '<div class="config-layout">' +
      '<nav class="config-nav" aria-label="配置模块">' + nav + "</nav>" +
      '<div class="config-main">' +
        card(
          moduleLabel(moduleId, moduleSchema),
          moduleSubtitle(moduleId, moduleSchema),
          '<form id="configForm" class="config-form">' +
  (fields || (advancedFields ? "" : emptyState("该模块没有可配置项", ""))) +
  (advancedFields
    ? '<details class="config-advanced"><summary>高级项（' + advancedKeys.length + ' 个）· 一般不用改</summary><div class="config-advanced-body"><div class="config-advanced-inner">' + advancedFields + "</div></div></details>"
    : "") +
  "</form>",
          '<button class="btn is-primary is-sm" type="button" id="configSaveBtn">保存本模块</button>',
          "config-card"
        ) +
      "</div>" +
      "</div>"
    );
  },
  mount(node, data) {
    const schema = data.schema || {};
    $$("[data-module]", node).forEach((button) => {
      button.addEventListener("click", () => {
        state.configModule = button.dataset.module;
        go("config", { useCachedSchema: true });
      });
    });

    $$("[data-open-config-search]", node).forEach((button) => {
      button.addEventListener("click", () => openConfigSearch());
    });

    $$(".cfg-choice-group", node).forEach((group) => {
      const key = group.dataset.choiceGroup;
      const hiddenInput = $("#cfg_" + key, group);
      const cards = $$(".cfg-choice-card", group);
      const pick = (cardEl, shouldFocus) => {
        if (!cardEl || cardEl.disabled) return;
        const val = cardEl.dataset.choiceVal;
        if (hiddenInput) hiddenInput.value = val;
        cards.forEach((btn) => {
          const isSel = btn === cardEl;
          btn.classList.toggle("is-active", isSel);
          btn.setAttribute("aria-checked", isSel ? "true" : "false");
        });
        if (shouldFocus && typeof cardEl.focus === "function") cardEl.focus();
      };
      cards.forEach((btn, idx) => {
        btn.addEventListener("click", () => pick(btn, false));
        btn.addEventListener("keydown", (event) => {
          if (event.key === "ArrowRight" || event.key === "ArrowDown") {
            event.preventDefault();
            pick(cards[(idx + 1) % cards.length], true);
          } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
            event.preventDefault();
            pick(cards[(idx - 1 + cards.length) % cards.length], true);
          }
        });
      });
    });

    const saveBtn = $("#configSaveBtn", node);
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        const moduleId = state.configModule;
        const items = (schema[moduleId] || {}).items || {};
        const guard = protectedConfigSets(data);
        const values = {};
        Object.keys(items).forEach((key) => {
          if (isProtectedConfigKey(guard, moduleId, key)) return;
          const item = items[key] || {};
          const el = $("#cfg_" + key, node);
          if (!el) return;
          if (el.type === "checkbox") values[key] = el.checked;
          else if (el.type === "number") values[key] = el.value === "" ? null : Number(el.value);
          else if (Array.isArray(item.options) || Array.isArray(item.enum)) values[key] = el.value;
          else if (item.type === "list" || Array.isArray(items[key].default)) {
            values[key] = el.value.trim() === "" ? [] : el.value.split(",").map((v) => v.trim());
          } else values[key] = el.value;
        });
        await withBusy("正在保存…", async () => {
          const saved = await apiPost("/config/module/update", { module: moduleId, values });
          if (state.configSchema && state.configSchema.values) {
            state.configSchema.values[moduleId] =
              saved && saved.values && typeof saved.values === "object"
                ? saved.values
                : Object.assign({}, state.configSchema.values[moduleId] || {}, values);
          }
          toast("已保存 " + moduleLabel(moduleId, schema[moduleId]), "ok");
          invalidatePool();
          // 配色改完当场生效，不用刷新页面——不然用户会以为这项又没生效
          if (moduleId === "appearance") syncPalette();
          await go("config");
        });
      });
    }

    $$(".switch input", node).forEach((input) => {
      input.addEventListener("change", () => {
        const label = input.parentElement.querySelector("span:last-child");
        if (label) label.textContent = input.checked ? "已启用" : "已关闭";
      });
    });

    bindSmoothDetails(node);

    const activeNav = $(".config-nav button.is-active", node);
    if (activeNav && typeof activeNav.scrollIntoView === "function") {
      try { activeNav.scrollIntoView({ block: "nearest" }); } catch (error) { /* 忽略 */ }
    }
    applyPendingConfigFocus(node);
  },
});

function bindSmoothDetails(rootNode) {
  $$("details.config-advanced", rootNode).forEach((details) => {
    const summary = details.querySelector(":scope > summary") || details.querySelector("summary");
    const body = details.querySelector(":scope > .config-advanced-body") || details.querySelector(".config-advanced-body");
    if (!summary || !body) return;
    let animTimer = 0;
    let animToken = 0;

    const clearInline = () => {
      body.style.height = "";
      body.style.opacity = "";
      body.style.overflow = "";
      body.style.transition = "";
      details.classList.remove("is-animating", "is-closing");
    };

    details.__cancelSmoothAnim = () => {
      animToken += 1;
      window.clearTimeout(animTimer);
      animTimer = 0;
      clearInline();
    };

    const renderedHeight = () => {
      const rect = typeof body.getBoundingClientRect === "function" ? body.getBoundingClientRect() : null;
      const h = rect && Number.isFinite(rect.height) ? rect.height : Number(body.offsetHeight);
      return Number.isFinite(h) && h > 0 ? h : 0;
    };

    summary.addEventListener("click", (event) => {
      if (prefersReducedMotion()) return;
      event.preventDefault();
      animToken += 1;
      const token = animToken;
      window.clearTimeout(animTimer);
      animTimer = 0;

      const shouldOpen = !details.open || details.classList.contains("is-closing");
      if (shouldOpen) {
        const wasOpen = Boolean(details.open);
        const startHeight = wasOpen ? renderedHeight() : 0;
        details.open = true;
        details.classList.remove("is-closing");
        details.classList.add("is-animating");
        body.style.transition = "none";
        body.style.overflow = "hidden";
        body.style.height = startHeight + "px";
        if (!wasOpen) body.style.opacity = "0";
        void body.offsetHeight;
        const targetHeight = body.scrollHeight;
        body.style.transition = "height 0.24s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.2s cubic-bezier(0.22, 1, 0.36, 1)";
        body.style.height = targetHeight + "px";
        body.style.opacity = "1";
        animTimer = window.setTimeout(() => {
          if (token !== animToken) return;
          animTimer = 0;
          clearInline();
        }, 260);
      } else {
        const startHeight = renderedHeight() || body.scrollHeight;
        details.classList.add("is-animating", "is-closing");
        body.style.transition = "none";
        body.style.overflow = "hidden";
        body.style.height = startHeight + "px";
        body.style.opacity = "1";
        void body.offsetHeight;
        body.style.transition = "height 0.18s cubic-bezier(0.4, 0, 1, 1), opacity 0.15s cubic-bezier(0.4, 0, 1, 1)";
        body.style.height = "0px";
        body.style.opacity = "0";
        animTimer = window.setTimeout(() => {
          if (token !== animToken) return;
          animTimer = 0;
          details.open = false;
          clearInline();
        }, 190);
      }
    });
  });
}

/* ============================================================
   全局配置搜索（Ctrl+K / Cmd+K / / 快捷键 + 侧栏入口）
   ============================================================ */
const configSearchState = {
  open: false,
  query: "",
  selectedIndex: 0,
  loading: false,
  error: "",
  schemaRef: null,
  moduleCount: 0,
  fieldCount: 0,
  catalog: [],
  index: null,
  hits: [],
  pendingTarget: null,
  hitTimer: 0,
  closeTimer: 0,
  lastFocus: null,
  fetchPromise: null,
  initialized: false,
};

const CONFIG_SEARCH_QUICK_CHIPS = [
  "性能调优",
  "一键瘦身",
  "向量存储精度",
  "跨群衔接",
  "拟人化记忆",
  "记得这个人",
  "配色主题",
  "总结模型",
  "待复核",
  "旧版记忆迁移",
];

const CONFIG_SEARCH_SHORTCUTS = [
  {
    key: "performance.tuning",
    viewId: "performance",
    focusTarget: "",
    title: "性能调优（5 档一键配置）",
    group: "快捷入口 · 设置",
    desc: "自动识别本机/Docker 内存，在智能自动、省资源、均衡推荐、高性能、慢盘兼容间一键切换，也可展开微调 12 项底层参数。",
    aliases: [
      "性能调优",
      "性能档位",
      "省资源",
      "均衡推荐",
      "高性能",
      "慢盘兼容",
      "稳妥兼容",
      "智能自动",
      "低配机",
      "机械硬盘",
      "NAS",
      "卡顿",
      "OOM",
      "防爆内存",
      "performance",
      "eco",
      "balanced",
      "turbo",
      "compat",
      "auto",
    ],
    priority: 24,
  },
  {
    key: "performance.tier.auto",
    viewId: "performance",
    focusTarget: "tier:auto",
    title: "性能档位 · 智能自动（默认推荐）",
    group: "性能调优",
    desc: "自动探测物理内存与容器 cgroup 内存上限，自动选择最稳妥档位并开启防爆限幅。",
    aliases: ["智能自动", "自动档", "自动识别", "容器内存", "cgroup", "auto"],
    priority: 10,
  },
  {
    key: "performance.tier.eco",
    viewId: "performance",
    focusTarget: "tier:eco",
    title: "性能档位 · 省资源（1–2G 低配云服 / 容器）",
    group: "性能调优",
    desc: "向量半精度省 75% 空间、关闭 mmap 与启动预热、缩小页缓存与并发读连接池，防止低配机器 OOM。",
    aliases: ["省资源", "低配机", "低内存", "省内存", "1G", "2G", "容器", "Docker", "eco", "OOM"],
    priority: 10,
  },
  {
    key: "performance.tier.balanced",
    viewId: "performance",
    focusTarget: "tier:balanced",
    title: "性能档位 · 均衡推荐（4–8G 日常主机）",
    group: "性能调优",
    desc: "标准精度无损召回，32MB 页缓存 + 256MB mmap + 3–6 路并发读池，速度与内存兼顾。",
    aliases: ["均衡推荐", "均衡", "常规", "4G", "8G", "balanced"],
    priority: 10,
  },
  {
    key: "performance.tier.turbo",
    viewId: "performance",
    focusTarget: "tier:turbo",
    title: "性能档位 · 高性能（16G+ 桌面机 / 大记忆库）",
    group: "性能调优",
    desc: "64MB 页缓存 + 最高 1GB 内存映射 + 6–12 路并行读连接池，海量记忆与多群高并发依然丝滑。",
    aliases: ["高性能", "狂暴", "大内存", "16G", "32G", "大库", "多群", "turbo"],
    priority: 10,
  },
  {
    key: "performance.tier.compat",
    viewId: "performance",
    focusTarget: "tier:compat",
    title: "性能档位 · 慢盘 / 稳妥兼容（机械硬盘 / NAS / 弱网）",
    group: "性能调优",
    desc: "关闭 mmap、开启 FULL 严格落盘保护，并将回复前记忆等待上限放宽至 5 秒减少偶发超时。",
    aliases: ["慢盘", "慢盘兼容", "稳妥兼容", "机械硬盘", "HDD", "NAS", "弱网", "防断电", "卡顿", "compat"],
    priority: 10,
  },
  {
    key: "maintenance.db_optimize",
    viewId: "migrate",
    focusTarget: "dbHealthCard",
    title: "数据库体检与一键瘦身",
    group: "快捷入口 · 维护与迁移",
    desc: "查看主库 / WAL / 副库体积、可回收空闲页与向量精度分布；支持一键常规无损瘦身与深度整理压缩（全量 VACUUM）。",
    aliases: [
      "数据库体检",
      "一键瘦身",
      "数据库瘦身",
      "瘦身",
      "体检",
      "压缩",
      "深度压缩",
      "深度整理压缩",
      "释放空间",
      "空闲页",
      "VACUUM",
      "vacuum",
      "freelist",
      "db_health",
      "db_optimize",
      "省空间",
      "转码",
    ],
    priority: 24,
  },
];

function isMacPlatform() {
  try {
    const p = (navigator && (navigator.platform || navigator.userAgent)) || "";
    return /mac|iphone|ipad|ipod/i.test(p);
  } catch (error) {
    return false;
  }
}

function shortcutBadgeText() {
  return isMacPlatform() ? "⌘ K" : "Ctrl K";
}

function isEditableElement(target) {
  if (!target || typeof target !== "object") return false;
  const tag = String(target.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return false;
}

function buildConfigSearchCatalog(data) {
  const schema = (data && data.schema) || {};
  const guard = protectedConfigSets(data);
  const catalog = [];
  const moduleIds = Object.keys(schema);
  let fieldCount = 0;

  for (let m = 0; m < moduleIds.length; m += 1) {
    const moduleId = moduleIds[m];
    const modSchema = schema[moduleId] || {};
    const modLabel = moduleLabel(moduleId, modSchema);
    const modSub = moduleSubtitle(moduleId, modSchema);
    const items = modSchema.items || {};
    const fieldKeys = Object.keys(items);
    const commonSet = new Set(orderedCommonKeys(moduleId, items));

    const modAliases = [moduleId];
    if (compact(modSchema.description) && compact(modSchema.description) !== modLabel) {
      modAliases.push(compact(modSchema.description));
    }

    catalog.push({
      kind: "module",
      moduleId,
      moduleLabel: modLabel,
      fieldKey: "",
      title: modLabel,
      group: "模块配置",
      desc: modSub || ("包含 " + fieldKeys.length + " 个配置项"),
      key: moduleId,
      aliases: modAliases,
      fieldCount: fieldKeys.length,
      isAdvanced: false,
      locked: false,
      priority: 22,
    });

    for (let f = 0; f < fieldKeys.length; f += 1) {
      const fieldKey = fieldKeys[f];
      const item = items[fieldKey] || {};
      fieldCount += 1;
      const title = compact(item.description) || fieldKey;
      const hint = compact(item.hint);
      const isAdvanced = !commonSet.has(fieldKey);
      const locked = isProtectedConfigKey(guard, moduleId, fieldKey);
      const opts = fieldOptions(item) || [];
      const optLabelMap = CONFIG_OPTION_LABELS[moduleId + "." + fieldKey] || null;
      const choiceMap = CONFIG_CHOICE_CARDS[moduleId + "." + fieldKey] || null;
      const aliases = [moduleId, fieldKey, moduleId + "." + fieldKey];
      for (let o = 0; o < opts.length; o += 1) {
        const optStr = String(opts[o]);
        aliases.push(optStr);
        if (optLabelMap && optLabelMap[optStr]) aliases.push(optLabelMap[optStr]);
        if (choiceMap && choiceMap[optStr]) {
          if (choiceMap[optStr].title) aliases.push(choiceMap[optStr].title);
          if (choiceMap[optStr].tag) aliases.push(choiceMap[optStr].tag);
          if (choiceMap[optStr].desc) aliases.push(choiceMap[optStr].desc);
        }
      }

      catalog.push({
        kind: "field",
        moduleId,
        moduleLabel: modLabel,
        fieldKey,
        title,
        group: modLabel,
        desc: hint,
        key: moduleId + "." + fieldKey,
        aliases,
        isAdvanced,
        locked,
        priority: isAdvanced ? 0 : 12,
      });
    }
  }

  // 附带高价值快捷操作入口（性能调优 5 档与数据库体检一键瘦身）
  for (let s = 0; s < CONFIG_SEARCH_SHORTCUTS.length; s += 1) {
    const sc = CONFIG_SEARCH_SHORTCUTS[s];
    catalog.push({
      kind: "action",
      viewId: sc.viewId,
      focusTarget: sc.focusTarget || "",
      moduleId: "",
      moduleLabel: sc.group,
      fieldKey: "",
      title: sc.title,
      group: sc.group,
      desc: sc.desc,
      key: sc.key,
      aliases: sc.aliases || [],
      isAdvanced: false,
      locked: false,
      priority: sc.priority || 10,
    });
  }

  // 附带控制台功能视图入口，便于一键切换页面
  for (let g = 0; g < NAV.length; g += 1) {
    const group = NAV[g];
    for (let v = 0; v < group.views.length; v += 1) {
      const viewId = group.views[v];
      const view = VIEWS[viewId];
      if (!view || view.hidden || viewId === "config") continue;
      catalog.push({
        kind: "view",
        viewId,
        moduleId: "",
        moduleLabel: group.label,
        fieldKey: "",
        title: view.title || view.navLabel || viewId,
        group: "面板视图 · " + group.label,
        desc: compact(view.hint),
        key: viewId,
        aliases: [group.label, view.navLabel || "", view.eyebrow || ""].filter(Boolean),
        isAdvanced: false,
        locked: false,
        priority: -4,
      });
    }
  }

  return { catalog, moduleCount: moduleIds.length, fieldCount };
}

function ensureConfigSearchIndex() {
  const data = state.configSchema;
  if (!data || !data.schema) return null;
  if (configSearchState.schemaRef === data && configSearchState.index) {
    return configSearchState.index;
  }
  const built = buildConfigSearchCatalog(data);
  configSearchState.schemaRef = data;
  configSearchState.catalog = built.catalog;
  configSearchState.moduleCount = built.moduleCount;
  configSearchState.fieldCount = built.fieldCount;
  const engine = window.MemorySearchEngine;
  if (engine && typeof engine.prepare === "function") {
    configSearchState.index = engine.prepare(built.catalog, {
      getTitle: (it) => it.title,
      getDesc: (it) => it.desc,
      getKey: (it) => it.key,
      getGroup: (it) => it.group,
      getAliases: (it) => it.aliases,
      getPriority: (it) => it.priority,
    });
  } else {
    configSearchState.index = { fallback: true, items: built.catalog };
  }
  return configSearchState.index;
}

function runConfigSearchQuery(rawQuery) {
  const query = compact(rawQuery);
  const index = ensureConfigSearchIndex();
  if (!query || !index) return [];
  const engine = window.MemorySearchEngine;
  if (engine && typeof engine.search === "function" && !index.fallback) {
    return engine.search(index, query, { limit: 36 });
  }
  const lower = query.toLowerCase();
  return (index.items || [])
    .filter((it) => {
      const hay = [it.group, it.title, it.key, it.desc].concat(it.aliases || []).join(" ").toLowerCase();
      return hay.includes(lower);
    })
    .slice(0, 36)
    .map((item) => ({ item, score: 100, matchKind: "exact", reason: "", matchedAlias: "", matchedTerms: [query] }));
}

function highlightConfigText(text, matchedTerms) {
  const engine = window.MemorySearchEngine;
  if (engine && typeof engine.highlight === "function") {
    return engine.highlight(text, matchedTerms, { markClass: "cfg-search-mark" });
  }
  return esc(text);
}

async function ensureConfigSchemaLoaded() {
  if (state.configSchema && state.configSchema.schema) return state.configSchema;
  if (!configSearchState.fetchPromise) {
    configSearchState.loading = true;
    configSearchState.error = "";
    renderConfigSearchResults();
    configSearchState.fetchPromise = apiGet("/config/schema")
      .then((result) => {
        state.configSchema = result;
        configSearchState.error = "";
        return result;
      })
      .catch((error) => {
        configSearchState.error = (error && error.message) || "配置索引加载失败";
        return null;
      })
      .finally(() => {
        configSearchState.loading = false;
        configSearchState.fetchPromise = null;
        if (configSearchState.open) renderConfigSearchResults();
      });
  }
  return configSearchState.fetchPromise;
}

function ensureConfigSearchModal() {
  let modal = $("#configSearchModal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.id = "configSearchModal";
  modal.className = "cfg-search-overlay";
  modal.hidden = true;
  modal.innerHTML =
    '<div class="cfg-search-dialog" role="dialog" aria-modal="true" aria-labelledby="cfgSearchTitle">' +
      '<div class="cfg-search-head">' +
        '<span class="cfg-search-icon" aria-hidden="true">' +
          '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
            '<circle cx="7.2" cy="7.2" r="4.5"/><path d="M10.6 10.6L14 14"/>' +
          "</svg>" +
        "</span>" +
        '<input id="configSearchInput" class="cfg-search-input" type="search" placeholder="搜索全部配置项：中文、简称、拼音、英文键或别名（如 向量精度 / xljd / float16 / 跨群）" autocomplete="off" spellcheck="false" aria-label="全局配置搜索" />' +
        '<button type="button" class="cfg-search-clear" id="configSearchClear" aria-label="清空搜索" hidden>×</button>' +
        '<span class="cfg-search-count" id="configSearchCount"></span>' +
        '<button type="button" class="cfg-search-esc" id="configSearchClose" aria-label="关闭配置搜索">Esc</button>' +
      "</div>" +
      '<span id="cfgSearchTitle" class="sr-only">全局配置搜索</span>' +
      '<div class="cfg-search-body" id="configSearchBody" role="listbox" aria-label="配置搜索结果"></div>' +
      '<div class="cfg-search-foot">' +
        '<span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>' +
        '<span><kbd>Enter</kbd> 直达并定位</span>' +
        '<span><kbd>Esc</kbd> 关闭</span>' +
        '<span class="cfg-search-foot-right">支持同义词 · 拼音首字母 · 错字容错</span>' +
      "</div>" +
    "</div>";

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeConfigSearch();
      return;
    }
    const chip = event.target.closest("[data-search-chip]");
    if (chip) {
      const input = $("#configSearchInput", modal);
      if (input) {
        input.value = chip.dataset.searchChip || "";
        configSearchState.query = input.value;
        configSearchState.selectedIndex = 0;
        renderConfigSearchResults();
        input.focus();
      }
      return;
    }
    const retry = event.target.closest("[data-search-retry]");
    if (retry) {
      ensureConfigSchemaLoaded();
      return;
    }
    const row = event.target.closest("[data-search-hit]");
    if (row) {
      const idx = Number(row.dataset.searchHit);
      if (Number.isFinite(idx) && configSearchState.hits[idx]) {
        activateConfigSearchHit(configSearchState.hits[idx]);
      }
      return;
    }
    const modBtn = event.target.closest("[data-search-module]");
    if (modBtn) {
      activateConfigSearchHit({ item: { kind: "module", moduleId: modBtn.dataset.searchModule } });
    }
  });

  modal.addEventListener("mousemove", (event) => {
    const row = event.target.closest("[data-search-hit]");
    if (!row) return;
    const idx = Number(row.dataset.searchHit);
    if (Number.isFinite(idx) && idx !== configSearchState.selectedIndex) {
      configSearchState.selectedIndex = idx;
      syncConfigSearchSelection(modal, false);
    }
  });

  const input = $("#configSearchInput", modal);
  const clearBtn = $("#configSearchClear", modal);
  const closeBtn = $("#configSearchClose", modal);

  input.addEventListener("input", () => {
    configSearchState.query = input.value;
    configSearchState.selectedIndex = 0;
    renderConfigSearchResults();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      if (!configSearchState.hits.length) return;
      event.preventDefault();
      configSearchState.selectedIndex = (configSearchState.selectedIndex + 1) % configSearchState.hits.length;
      syncConfigSearchSelection(modal, true);
    } else if (event.key === "ArrowUp") {
      if (!configSearchState.hits.length) return;
      event.preventDefault();
      configSearchState.selectedIndex =
        (configSearchState.selectedIndex - 1 + configSearchState.hits.length) % configSearchState.hits.length;
      syncConfigSearchSelection(modal, true);
    } else if (event.key === "Home" && configSearchState.hits.length) {
      event.preventDefault();
      configSearchState.selectedIndex = 0;
      syncConfigSearchSelection(modal, true);
    } else if (event.key === "End" && configSearchState.hits.length) {
      event.preventDefault();
      configSearchState.selectedIndex = configSearchState.hits.length - 1;
      syncConfigSearchSelection(modal, true);
    } else if (event.key === "Enter") {
      const hit = configSearchState.hits[configSearchState.selectedIndex];
      if (hit) {
        event.preventDefault();
        activateConfigSearchHit(hit);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeConfigSearch();
    }
  });

  clearBtn.addEventListener("click", () => {
    input.value = "";
    configSearchState.query = "";
    configSearchState.selectedIndex = 0;
    renderConfigSearchResults();
    input.focus();
  });

  closeBtn.addEventListener("click", () => closeConfigSearch());

  document.body.appendChild(modal);
  return modal;
}

function syncConfigSearchSelection(modal, shouldScroll) {
  const rows = $$("[data-search-hit]", modal);
  rows.forEach((row, idx) => {
    const active = idx === configSearchState.selectedIndex;
    row.classList.toggle("is-selected", active);
    row.setAttribute("aria-selected", active ? "true" : "false");
    if (active && shouldScroll && typeof row.scrollIntoView === "function") {
      try { row.scrollIntoView({ block: "nearest" }); } catch (error) { /* 忽略 */ }
    }
  });
}

function renderConfigSearchResults() {
  const modal = $("#configSearchModal");
  if (!modal) return;
  const body = $("#configSearchBody", modal);
  const countEl = $("#configSearchCount", modal);
  const clearBtn = $("#configSearchClear", modal);
  const query = compact(configSearchState.query);
  if (clearBtn) clearBtn.hidden = !configSearchState.query;

  if (configSearchState.loading && !state.configSchema) {
    configSearchState.hits = [];
    if (countEl) countEl.textContent = "索引中…";
    body.innerHTML = '<div class="cfg-search-empty"><b>正在载入全部配置项索引…</b><span>涵盖全部模块与折叠高级项</span></div>';
    return;
  }

  if (configSearchState.error && !state.configSchema) {
    configSearchState.hits = [];
    if (countEl) countEl.textContent = "加载失败";
    body.innerHTML =
      '<div class="cfg-search-empty"><b>配置索引未能加载</b><span>' + esc(configSearchState.error) + "</span>" +
      '<button type="button" class="btn is-sm" data-search-retry style="margin-top:10px">重试加载</button></div>';
    return;
  }

  ensureConfigSearchIndex();

  if (!query) {
    configSearchState.hits = [];
    if (countEl) {
      countEl.textContent = configSearchState.moduleCount + " 模块 · " + configSearchState.fieldCount + " 项";
    }
    const chipsHtml = CONFIG_SEARCH_QUICK_CHIPS
      .map((label) => '<button type="button" class="cfg-search-chip" data-search-chip="' + esc(label) + '">' + esc(label) + "</button>")
      .join("");
    const schema = (state.configSchema && state.configSchema.schema) || {};
    const featuredIds = [
      "retrieval_advanced",
      "conversation_memory_advanced",
      "memory_humanization",
      "persona_memory",
      "appearance",
      "memory_summary",
      "identity",
      "livingmemory_migration",
    ].filter((id) => Object.prototype.hasOwnProperty.call(schema, id));
    const modGrid = featuredIds
      .map((id) => {
        const mod = schema[id] || {};
        const count = Object.keys(mod.items || {}).length;
        return (
          '<button type="button" class="cfg-search-modcard" data-search-module="' + esc(id) + '">' +
          '<b>' + esc(moduleLabel(id, mod)) + "</b>" +
          '<em>' + count + " 项</em>" +
          '<span>' + esc(clip(moduleSubtitle(id, mod) || "点击进入该模块配置", 36)) + "</span>" +
          "</button>"
        );
      })
      .join("");
    body.innerHTML =
      '<div class="cfg-search-welcome">' +
        '<div class="cfg-search-sec-label">快捷直达</div>' +
        '<div class="cfg-search-chips">' + chipsHtml + "</div>" +
        (modGrid ? '<div class="cfg-search-sec-label" style="margin-top:14px">常用配置模块</div><div class="cfg-search-modgrid">' + modGrid + "</div>" : "") +
      "</div>";
    return;
  }

  const hits = runConfigSearchQuery(query);
  configSearchState.hits = hits;
  if (configSearchState.selectedIndex >= hits.length) configSearchState.selectedIndex = 0;
  if (countEl) countEl.textContent = "命中 " + hits.length + " 项";

  if (!hits.length) {
    const chipsHtml = CONFIG_SEARCH_QUICK_CHIPS.slice(0, 5)
      .map((label) => '<button type="button" class="cfg-search-chip" data-search-chip="' + esc(label) + '">' + esc(label) + "</button>")
      .join("");
    body.innerHTML =
      '<div class="cfg-search-empty">' +
        '<b>未找到与「' + esc(query) + '」匹配的配置</b>' +
        "<span>可以尝试简称、同义词（如 省内存 / 小黑屋 / 跨群）、拼音首字母（如 xljd / nrh）或英文键名</span>" +
        '<div class="cfg-search-chips" style="justify-content:center;margin-top:12px">' + chipsHtml + "</div>" +
      "</div>";
    return;
  }

  body.innerHTML = hits
    .map((hit, idx) => {
      const it = hit.item;
      const selected = idx === configSearchState.selectedIndex;
      const tags = [];
      if (hit.matchKind === "alias" && hit.reason) {
        tags.push('<span class="cfg-search-tag is-alias">' + esc(hit.reason) + "</span>");
      } else if (hit.matchKind === "pinyin") {
        tags.push('<span class="cfg-search-tag is-pinyin">拼音</span>');
      } else if (hit.matchKind === "fuzzy") {
        tags.push('<span class="cfg-search-tag is-fuzzy">容错</span>');
      }
      if (it.kind === "module") {
        tags.push('<span class="cfg-search-tag is-mod">模块 · ' + esc(it.fieldCount) + " 项</span>");
      } else if (it.kind === "action") {
        tags.push('<span class="cfg-search-tag is-mod">直达</span>');
      } else if (it.kind === "view") {
        tags.push('<span class="cfg-search-tag is-mod">视图</span>');
      } else {
        if (it.isAdvanced) tags.push('<span class="cfg-search-tag is-adv">高级项</span>');
        if (it.locked) tags.push('<span class="cfg-search-tag is-lock">只读</span>');
      }

      const crumb =
        it.kind === "field"
          ? '<span class="cfg-search-mod">' + highlightConfigText(it.moduleLabel, hit.matchedTerms) + "</span>" +
            '<span class="cfg-search-sep" aria-hidden="true">›</span>' +
            '<strong class="cfg-search-title">' + highlightConfigText(it.title, hit.matchedTerms) + "</strong>"
          : '<span class="cfg-search-mod">' + esc(it.group) + "</span>" +
            '<span class="cfg-search-sep" aria-hidden="true">›</span>' +
            '<strong class="cfg-search-title">' + highlightConfigText(it.title, hit.matchedTerms) + "</strong>";

      return (
        '<button type="button" class="cfg-search-item' + (selected ? " is-selected" : "") + '"' +
        ' role="option" aria-selected="' + (selected ? "true" : "false") + '"' +
        ' data-search-hit="' + idx + '">' +
        '<div class="cfg-search-row-top">' +
          '<div class="cfg-search-crumb">' + crumb + "</div>" +
          (tags.length ? '<div class="cfg-search-tags">' + tags.join("") + "</div>" : "") +
        "</div>" +
        (it.desc ? '<div class="cfg-search-desc">' + highlightConfigText(it.desc, hit.matchedTerms) + "</div>" : "") +
        '<div class="cfg-search-key mono">' + highlightConfigText(it.key, hit.matchedTerms) + "</div>" +
        "</button>"
      );
    })
    .join("");
}

function openConfigSearch(initialQuery) {
  const modal = ensureConfigSearchModal();
  window.clearTimeout(configSearchState.closeTimer);
  configSearchState.closeTimer = 0;
  if (!configSearchState.open) {
    configSearchState.lastFocus = document.activeElement;
  }
  configSearchState.open = true;
  modal.hidden = false;
  if (prefersReducedMotion()) {
    modal.classList.add("is-open");
  } else {
    void modal.offsetWidth;
    requestAnimationFrame(() => {
      if (configSearchState.open) modal.classList.add("is-open");
    });
  }
  const input = $("#configSearchInput", modal);
  if (typeof initialQuery === "string") {
    configSearchState.query = initialQuery;
    if (input) input.value = initialQuery;
  } else if (input) {
    input.value = configSearchState.query;
  }
  configSearchState.selectedIndex = 0;
  renderConfigSearchResults();
  if (!state.configSchema || !state.configSchema.schema) {
    ensureConfigSchemaLoaded();
  }
  if (input) {
    input.focus();
    if (input.value) input.select();
  }
}

function closeConfigSearch(options) {
  const modal = $("#configSearchModal");
  if (!modal || !configSearchState.open) return;
  configSearchState.open = false;
  window.clearTimeout(configSearchState.closeTimer);
  configSearchState.closeTimer = 0;
  modal.classList.remove("is-open");
  if (prefersReducedMotion() || (options && options.immediate)) {
    modal.hidden = true;
  } else {
    configSearchState.closeTimer = window.setTimeout(() => {
      configSearchState.closeTimer = 0;
      if (!configSearchState.open) modal.hidden = true;
    }, 180);
  }
  if (!options || options.restoreFocus !== false) {
    const prev = configSearchState.lastFocus;
    configSearchState.lastFocus = null;
    if (prev && typeof prev.focus === "function" && document.contains(prev)) {
      try { prev.focus({ preventScroll: true }); } catch (error) { /* 忽略 */ }
    }
  } else {
    configSearchState.lastFocus = null;
  }
}

async function activateConfigSearchHit(hit) {
  const item = hit && hit.item;
  if (!item) return;
  closeConfigSearch({ restoreFocus: false });
  if ((item.kind === "view" || item.kind === "action") && item.viewId) {
    if (item.focusTarget) {
      state.pendingViewFocus = { viewId: item.viewId, target: item.focusTarget };
    }
    await go(item.viewId);
    return;
  }
  if (item.moduleId) {
    state.configModule = item.moduleId;
    if (item.kind === "field" && item.fieldKey) {
      configSearchState.pendingTarget = {
        moduleId: item.moduleId,
        fieldKey: item.fieldKey,
        isAdvanced: Boolean(item.isAdvanced),
      };
    } else {
      configSearchState.pendingTarget = null;
    }
    await go("config", { useCachedSchema: Boolean(state.configSchema && state.configSchema.schema) });
  }
}

function applyPendingConfigFocus(rootNode) {
  const target = configSearchState.pendingTarget;
  if (!target || target.moduleId !== state.configModule) return;
  configSearchState.pendingTarget = null;

  const scope = rootNode || $("#content");
  if (!scope) return;
  const safeKey = String(target.fieldKey || "").replace(/["\\]/g, "\\$&");
  const fieldEl = scope.querySelector('[data-config-field="' + safeKey + '"]');
  if (!fieldEl) return;

  const details = fieldEl.closest("details.config-advanced");
  if (details) {
    if (typeof details.__cancelSmoothAnim === "function") details.__cancelSmoothAnim();
    if (!details.open) details.open = true;
  }

  let reducedMotion = false;
  try {
    reducedMotion = Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch (error) { /* 忽略 */ }

  requestAnimationFrame(() => {
    if (typeof fieldEl.scrollIntoView === "function") {
      try {
        fieldEl.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
      } catch (error) {
        fieldEl.scrollIntoView();
      }
    }
    $$(".config-field.is-search-hit", scope).forEach((el) => el.classList.remove("is-search-hit"));
    void fieldEl.offsetWidth;
    fieldEl.classList.add("is-search-hit");
    window.clearTimeout(configSearchState.hitTimer);
    configSearchState.hitTimer = window.setTimeout(() => {
      fieldEl.classList.remove("is-search-hit");
    }, 2200);

    const focusable =
      fieldEl.querySelector('.cfg-choice-card.is-active:not([disabled])') ||
      fieldEl.querySelector('input:not([type="hidden"]):not([disabled]), select:not([disabled]), button:not([disabled])');
    if (focusable && typeof focusable.focus === "function") {
      try { focusable.focus({ preventScroll: true }); } catch (error) { /* 忽略 */ }
    }
  });
}

function mountConfigSearchTrigger() {
  if ($("#configSearchBtn")) return;
  const foot = $(".rail-foot");
  if (!foot) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "configSearchBtn";
  btn.className = "rail-search-btn";
  btn.title = "搜索全部配置项 (" + shortcutBadgeText() + ")";
  btn.setAttribute("aria-label", "搜索配置");
  btn.innerHTML =
    icon("search", "rail-search-icon") +
    '<span class="rail-search-label">搜索配置</span>' +
    '<kbd class="rail-search-kbd">' + esc(shortcutBadgeText()) + "</kbd>";
  btn.addEventListener("click", () => openConfigSearch());
  foot.insertBefore(btn, foot.firstChild);
}

function initConfigSearch() {
  if (configSearchState.initialized) return;
  configSearchState.initialized = true;
  mountConfigSearchTrigger();

  document.addEventListener("keydown", (event) => {
    const key = String(event.key || "");
    if ((event.ctrlKey || event.metaKey) && !event.altKey && key.toLowerCase() === "k") {
      event.preventDefault();
      if (configSearchState.open) {
        const input = $("#configSearchInput");
        if (input) {
          input.focus();
          input.select();
        }
      } else {
        openConfigSearch();
      }
      return;
    }

    if (key === "Escape" && configSearchState.open) {
      event.preventDefault();
      closeConfigSearch();
      return;
    }

    if (
      key === "/" &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey &&
      !configSearchState.open &&
      !isEditableElement(event.target) &&
      !(state.mode === "cinema" && state.view === "overview")
    ) {
      event.preventDefault();
      openConfigSearch();
    }
  });
}

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
   视图：性能调优
   ============================================================ */
const perfUiState = {
  draftProfile: "",
  preserveOnSwitch: false,
  advancedOpen: false,
  lastHotReload: null,
};

function fmtMemMb(mb) {
  const n = Number(mb);
  if (!Number.isFinite(n) || n <= 0) return "未知内存";
  if (n < 1024) return Math.round(n) + " MiB";
  return num(n / 1024, 1) + " GiB";
}

function fmtPerfValue(param, rawVal) {
  if (param.value_type === "bool") return rawVal ? "已开启" : "已关闭";
  if (param.value_type === "enum") return compact(rawVal, "-");
  const scale = Number(param.display_scale) || 1;
  const numeric = Number(rawVal);
  if (!Number.isFinite(numeric)) return "-";
  const shown = scale > 1 ? num(numeric / scale, 1) : num(numeric, param.value_type === "float" ? 1 : 0);
  return param.unit ? shown + " " + param.unit : shown;
}

function toDisplayInputValue(param, rawVal) {
  const scale = Number(param.display_scale) || 1;
  if (param.value_type === "int" || param.value_type === "float") {
    const numeric = Number(rawVal);
    if (!Number.isFinite(numeric)) return "";
    if (scale > 1) return String(Math.round(numeric / scale));
    return String(numeric);
  }
  return String(rawVal ?? "");
}

function parseInputToRawValue(param, el) {
  if (!el) return null;
  if (param.value_type === "bool") return Boolean(el.checked);
  if (param.value_type === "enum") return String(el.value || "");
  const numeric = Number(el.value);
  if (!Number.isFinite(numeric)) return null;
  const scale = Number(param.display_scale) || 1;
  if (param.value_type === "int") return Math.round(numeric * scale);
  return Math.round(numeric * 100) / 100;
}

function perfValuesEqual(param, a, b) {
  if (param.value_type === "bool") return Boolean(a) === Boolean(b);
  if (param.value_type === "float") return Math.abs(Number(a) - Number(b)) < 1e-6;
  if (param.value_type === "int") return Math.round(Number(a)) === Math.round(Number(b));
  return String(a ?? "").trim().toLowerCase() === String(b ?? "").trim().toLowerCase();
}

defineView("performance", {
  title: "性能调优",
  navLabel: "性能调优",
  eyebrow: "Settings · Performance",
  hint: "按机器配置选择 5 档统一性能策略，也可展开微调数据库与检索底层参数",
  async load() {
    perfUiState.draftProfile = "";
    perfUiState.preserveOnSwitch = false;
    const res = await apiGet("/performance/tuning");
    return (res && res.tuning) || res || {};
  },
  render(data) {
    const hw = data.hardware || {};
    const tiers = Array.isArray(data.tiers) ? data.tiers : [];
    const groups = Array.isArray(data.groups) ? data.groups : [];
    const params = Array.isArray(data.params) ? data.params : [];
    const clamped = Array.isArray(data.clamped_fields) ? data.clamped_fields : [];
    const dbSummary = data.db_summary || {};
    const savedProfile = compact(data.profile, "auto");
    const activeProfile = perfUiState.draftProfile || savedProfile;
    const effectiveTierLabel = compact(data.effective_tier_label || data.effective_tier, "均衡推荐");
    const profileLabel = compact(data.profile_label || savedProfile, "智能自动");
    const overrideCount = Math.max(0, int(data.override_count));
    const switchingWithOverrides = activeProfile !== savedProfile && overrideCount > 0;

    const memSourceTag = {
      cgroup_v2: "容器 cgroup v2 限额",
      cgroup_v1: "容器 cgroup v1 限额",
      windows: "主机物理内存",
      proc_meminfo: "主机物理内存",
      sysconf: "主机物理内存",
    }[hw.memory_source] || "自动识别";

    const statusBadgeText = overrideCount > 0
      ? "基于「" + effectiveTierLabel + "」· 已微调 " + overrideCount + " 项"
      : savedProfile === "auto"
      ? "智能自动 · 当前生效：" + effectiveTierLabel
      : "当前生效：" + profileLabel;

    const hero =
      '<section class="card perf-hero">' +
        '<div class="perf-hero-top">' +
          '<div class="perf-hero-copy">' +
            '<div class="perf-hw-chips">' +
              '<span class="perf-chip is-accent">可用内存：' + esc(fmtMemMb(hw.effective_memory_mb)) + "</span>" +
              '<span class="perf-chip">CPU：' + esc(fmtInt(hw.cpu_count || 2)) + " 核</span>" +
              '<span class="perf-chip">' + esc(memSourceTag) + "</span>" +
              (hw.is_32bit ? '<span class="perf-chip is-warn">32 位环境 · 自动关 mmap</span>' : "") +
            "</div>" +
            '<p class="perf-hero-reason">' + esc(compact(hw.recommendation_reason, "已根据当前硬件自动评估推荐性能档位。")) + "</p>" +
            '<p class="perf-orthogonal-note">' + esc(compact(data.orthogonal_notice, "功能预设管「记多少、用哪些能力」，性能档位管「跑多快、占多少内存硬盘」，两者互不冲突。")) + "</p>" +
          "</div>" +
          '<div class="perf-status-pill' + (overrideCount > 0 ? " is-overridden" : "") + '">' +
            '<span class="perf-status-dot" aria-hidden="true"></span>' +
            '<span>' + esc(statusBadgeText) + "</span>" +
          "</div>" +
        "</div>" +
      "</section>";

    const clampBanner = clamped.length
      ? '<section class="perf-clamp-banner" role="status">' +
          '<div class="perf-clamp-head"><b>已触发防爆内存安全限幅（' + clamped.length + ' 项）</b><span>为防止低配机器 OOM 崩溃，系统已按本机可用内存自动收紧下列参数：</span></div>' +
          '<ul class="perf-clamp-list">' +
            clamped.map((c) => "<li>" + esc(c.reason || (c.label + " 已自动限幅")) + "</li>").join("") +
          "</ul>" +
        "</section>"
      : "";

    const tierCards = tiers
      .map((tier) => {
        const isSel = tier.id === activeProfile;
        const isRecommended = tier.id === hw.recommended_tier;
        const extraTag = tier.id === "auto"
          ? "自动匹配：" + (tiers.find((t) => t.id === hw.recommended_tier)?.label || effectiveTierLabel)
          : isRecommended
          ? "本机推荐"
          : tier.badge;
        return (
          '<button type="button" class="perf-tier-card' + (isSel ? " is-active" : "") + '"' +
          ' role="radio" aria-checked="' + (isSel ? "true" : "false") + '"' +
          ' data-perf-tier="' + esc(tier.id) + '">' +
            '<div class="perf-tier-head">' +
              '<span class="cfg-choice-dot" aria-hidden="true"></span>' +
              '<strong class="perf-tier-title">' + esc(tier.label) + "</strong>" +
              (extraTag ? '<span class="perf-tier-badge' + (isRecommended || tier.id === "auto" ? " is-rec" : "") + '">' + esc(extraTag) + "</span>" : "") +
            "</div>" +
            '<div class="perf-tier-tagline">' + esc(tier.tagline) + "</div>" +
            '<div class="perf-tier-scene">' + esc(tier.target_scene) + "</div>" +
            '<div class="perf-tier-highlights">' +
              (Array.isArray(tier.highlights) ? tier.highlights.map((h) => "<span>" + esc(h) + "</span>").join("") : "") +
            "</div>" +
          "</button>"
        );
      })
      .join("");

    const switchBar =
      '<div class="perf-switch-bar" id="perfSwitchBar"' + (switchingWithOverrides ? "" : " hidden") + ">" +
        '<span class="perf-switch-msg">检测到当前有 <b>' + overrideCount + "</b> 项手动微调，切换到新档位时：</span>" +
        '<div class="perf-switch-choices" role="radiogroup" aria-label="切换档位时的微调处理">' +
          '<button type="button" class="btn is-sm' + (!perfUiState.preserveOnSwitch ? " is-primary" : "") + '" data-perf-preserve="0">全部恢复新档位默认（推荐）</button>' +
          '<button type="button" class="btn is-sm' + (perfUiState.preserveOnSwitch ? " is-primary" : "") + '" data-perf-preserve="1">保留我的微调项</button>' +
        "</div>" +
      "</div>";

    const renderParamControl = (param) => {
      const id = "perf_field_" + param.key.replace(/[^a-zA-Z0-9_]/g, "_");
      const val = param.effective_value;
      if (param.value_type === "bool") {
        return (
          '<label class="switch">' +
            '<input type="checkbox" id="' + esc(id) + '" data-perf-input="' + esc(param.key) + '"' + (val ? " checked" : "") + " />" +
            '<span class="switch-track"></span>' +
            '<span class="perf-switch-text">' + (val ? "已开启" : "已关闭") + "</span>" +
          "</label>"
        );
      }
      if (param.value_type === "enum") {
        const opts = Array.isArray(param.options) ? param.options : [];
        return (
          '<select id="' + esc(id) + '" data-perf-input="' + esc(param.key) + '">' +
            opts
              .map((opt) => '<option value="' + esc(opt.value) + '"' + (String(val) === String(opt.value) ? " selected" : "") + ">" + esc(opt.label) + "</option>")
              .join("") +
          "</select>"
        );
      }
      const scale = Number(param.display_scale) || 1;
      const minAttr = param.min != null ? ' min="' + esc(scale > 1 ? Math.round(param.min / scale) : param.min) + '"' : "";
      const maxAttr = param.max != null ? ' max="' + esc(scale > 1 ? Math.round(param.max / scale) : param.max) + '"' : "";
      const stepAttr = param.step != null ? ' step="' + esc(scale > 1 ? Math.max(1, Math.round(param.step / scale)) : param.step) + '"' : "";
      return (
        '<div class="perf-num-wrap">' +
          '<input type="number" id="' + esc(id) + '" data-perf-input="' + esc(param.key) + '" value="' + esc(toDisplayInputValue(param, val)) + '"' + minAttr + maxAttr + stepAttr + " />" +
          (param.unit ? '<span class="perf-unit">' + esc(param.unit) + "</span>" : "") +
        "</div>"
      );
    };

    const groupsHtml = groups
      .map((grp) => {
        const grpParams = params.filter((p) => p.group === grp.id);
        if (!grpParams.length) return "";
        const rows = grpParams
          .map((p) => {
            const overridden = Boolean(p.overridden);
            const isClamped = Boolean(p.clamped);
            return (
              '<div class="perf-param' + (overridden ? " is-overridden" : "") + (isClamped ? " is-clamped" : "") + '" data-perf-param="' + esc(p.key) + '">' +
                '<div class="perf-param-info">' +
                  '<div class="perf-param-head">' +
                    '<strong class="perf-param-label">' + esc(p.label) + "</strong>" +
                    '<span class="perf-override-pill' + (overridden ? " is-on" : "") + '" data-perf-override-pill="' + esc(p.key) + '">' +
                      (overridden ? "● 已微调" : "跟随档位") +
                    "</span>" +
                    '<span class="perf-scope-pill' + (p.hot_reload ? " is-hot" : "") + '">' + esc(p.effect_scope || (p.hot_reload ? "立即生效" : "下次重启生效")) + "</span>" +
                    (isClamped ? '<span class="perf-clamp-pill">已安全限幅</span>' : "") +
                  "</div>" +
                  '<div class="perf-param-summary">' + esc(p.summary) + "</div>" +
                  '<div class="perf-param-effects">' +
                    '<span><b>▲</b> ' + esc(p.up_effect) + "</span>" +
                    '<span><b>▼</b> ' + esc(p.down_effect) + "</span>" +
                  "</div>" +
                  '<div class="perf-param-meta">' +
                    '<span>当前生效：<b>' + esc(fmtPerfValue(p, p.effective_value)) + "</b></span>" +
                    '<span>档位默认：' + esc(fmtPerfValue(p, p.tier_default)) + "</span>" +
                    '<code class="mono">' + esc(p.key) + "</code>" +
                  "</div>" +
                "</div>" +
                '<div class="perf-param-ctrl">' +
                  renderParamControl(p) +
                  '<button type="button" class="btn is-sm perf-reset-one" data-perf-reset-key="' + esc(p.key) + '"' + (overridden ? "" : " disabled") + ">恢复跟随档位</button>" +
                "</div>" +
              "</div>"
            );
          })
          .join("");
        return (
          '<section class="perf-group">' +
            '<div class="perf-group-head"><h4>' + esc(grp.label) + "</h4><span>" + esc(grp.desc) + "</span></div>" +
            '<div class="perf-group-list">' + rows + "</div>" +
          "</section>"
        );
      })
      .join("");

    const advancedDetails =
      '<details class="config-advanced perf-advanced" id="perfAdvancedDetails"' + (perfUiState.advancedOpen ? " open" : "") + ">" +
        "<summary>" +
          "<span>展开高级性能微调（" + params.length + " 项）</span>" +
          (overrideCount > 0 ? '<span class="perf-summary-badge">已微调 ' + overrideCount + " 项</span>" : '<span class="perf-summary-hint">一般选上面 5 档即可，有特殊需求再微调</span>') +
        "</summary>" +
        '<div class="config-advanced-body"><div class="config-advanced-inner">' +
          '<div class="perf-adv-toolbar">' +
            '<span>绿色标签项保存后立即热刷新连接池与缓存；灰色标签项在下次重启 AstrBot 时生效。</span>' +
            '<button type="button" class="btn is-sm" id="perfResetAllBtn"' + (overrideCount > 0 ? "" : " disabled") + ">全部恢复档位默认</button>" +
          "</div>" +
          groupsHtml +
        "</div></div>" +
      "</details>";

    const saveBar =
      '<div class="perf-save-bar">' +
        '<div class="perf-save-hint">' +
          (perfUiState.lastHotReload
            ? "上次热刷新：读连接池代次 #" + esc(fmtInt(perfUiState.lastHotReload.read_pool_generation || 0)) +
              "（" + esc(fmtInt(perfUiState.lastHotReload.read_pool_max || 0)) + " 路 · 页缓存 " +
              esc(fmtInt(perfUiState.lastHotReload.cache_size_mb || 0)) + " MB · mmap " +
              esc(fmtInt(perfUiState.lastHotReload.mmap_size_mb || 0)) + " MB）"
            : "保存后立即写入插件配置并热刷新 SQLite 缓存、并发读连接池与检索预算。") +
        "</div>" +
        '<div class="perf-save-actions">' +
          '<button type="button" class="btn is-sm" id="perfResetAllFooterBtn"' + (overrideCount > 0 ? "" : " disabled") + ">全部恢复档位默认</button>" +
          '<button type="button" class="btn is-primary" id="perfSaveBtn">保存并立即生效</button>' +
        "</div>" +
      "</div>";

    const dbStrip =
      '<section class="card perf-db-strip">' +
        '<div class="perf-db-strip-copy">' +
          '<div class="perf-db-strip-title">' + icon("db", "perf-db-icon") + "<b>数据库体积速览</b>" +
            '<span class="perf-db-total">' + esc(fmtBytes(dbSummary.grand_total_bytes || dbSummary.primary_total_bytes || 0)) + "</span>" +
          "</div>" +
          '<div class="perf-db-strip-meta">' +
            "主库 " + esc(fmtBytes(dbSummary.primary_db_bytes || 0)) +
            " · WAL " + esc(fmtBytes(dbSummary.wal_bytes || 0)) +
            " · 副库 " + esc(fmtBytes(dbSummary.scoped_total_bytes || 0)) +
            " — 切换半精度 float16 或感觉库偏大时，可前往一键无损瘦身。" +
          "</div>" +
        "</div>" +
        '<button type="button" class="btn is-sm" id="perfGoDbHealthBtn">前往数据库体检与一键瘦身 →</button>' +
      "</section>";

    return (
      '<div class="perf-view">' +
        hero +
        clampBanner +
        card(
          "选择性能档位",
          "点选最贴合你机器配置的档位；不确定时直接选「智能自动」即可",
          '<div class="perf-tier-grid" role="radiogroup" aria-label="性能档位选择">' + tierCards + "</div>" +
            switchBar +
            advancedDetails +
            saveBar,
          "",
          "perf-main-card"
        ) +
        dbStrip +
      "</div>"
    );
  },
  mount(node, data) {
    const params = Array.isArray(data.params) ? data.params : [];
    const paramMap = {};
    params.forEach((p) => { paramMap[p.key] = p; });
    const savedProfile = compact(data.profile, "auto");
    let selectedProfile = perfUiState.draftProfile || savedProfile;
    const overrideCount = Math.max(0, int(data.override_count));

    // Track per-field edits made inside this view before clicking Save.
    const editedOverrides = Object.assign({}, data.overrides || {});
    const dirtyOverrides = {};

    const syncTierCards = (nextProfile, shouldFocus) => {
      selectedProfile = nextProfile;
      perfUiState.draftProfile = nextProfile;
      const cards = $$(".perf-tier-card", node);
      cards.forEach((btn) => {
        const active = btn.dataset.perfTier === nextProfile;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-checked", active ? "true" : "false");
        if (active && shouldFocus && typeof btn.focus === "function") btn.focus();
      });
      const shouldShowSwitchBar = nextProfile !== savedProfile && overrideCount > 0;
      const existingBar = $("#perfSwitchBar", node);
      if (existingBar) {
        existingBar.hidden = !shouldShowSwitchBar;
      }
    };

    const tierButtons = $$(".perf-tier-card", node);
    tierButtons.forEach((btn, idx) => {
      btn.addEventListener("click", () => syncTierCards(btn.dataset.perfTier, false));
      btn.addEventListener("keydown", (event) => {
        if (event.key === "ArrowRight" || event.key === "ArrowDown") {
          event.preventDefault();
          const next = tierButtons[(idx + 1) % tierButtons.length];
          syncTierCards(next.dataset.perfTier, true);
        } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
          event.preventDefault();
          const prev = tierButtons[(idx - 1 + tierButtons.length) % tierButtons.length];
          syncTierCards(prev.dataset.perfTier, true);
        }
      });
    });

    $$("[data-perf-preserve]", node).forEach((btn) => {
      btn.addEventListener("click", () => {
        perfUiState.preserveOnSwitch = btn.dataset.perfPreserve === "1";
        $$("[data-perf-preserve]", node).forEach((b) => {
          b.classList.toggle("is-primary", (b.dataset.perfPreserve === "1") === perfUiState.preserveOnSwitch);
        });
      });
    });

    const syncParamRow = (key, rawVal) => {
      const param = paramMap[key];
      if (!param) return;
      const isDiff = rawVal !== null && !perfValuesEqual(param, rawVal, param.tier_default);
      if (isDiff) {
        editedOverrides[key] = rawVal;
        dirtyOverrides[key] = rawVal;
      } else {
        editedOverrides[key] = null;
        dirtyOverrides[key] = null;
      }
      const row = $('[data-perf-param="' + key.replace(/["\\]/g, "\\$&") + '"]', node);
      if (row) row.classList.toggle("is-overridden", isDiff);
      const pill = $('[data-perf-override-pill="' + key.replace(/["\\]/g, "\\$&") + '"]', node);
      if (pill) {
        pill.classList.toggle("is-on", isDiff);
        pill.textContent = isDiff ? "● 已微调" : "跟随档位";
      }
      const resetBtn = $('[data-perf-reset-key="' + key.replace(/["\\]/g, "\\$&") + '"]', node);
      if (resetBtn) resetBtn.disabled = !isDiff;
      const anyOverridden = Object.keys(editedOverrides).some((k) => editedOverrides[k] !== null && editedOverrides[k] !== undefined);
      const r1 = $("#perfResetAllBtn", node);
      const r2 = $("#perfResetAllFooterBtn", node);
      if (r1) r1.disabled = !anyOverridden;
      if (r2) r2.disabled = !anyOverridden;
    };

    $$("[data-perf-input]", node).forEach((input) => {
      const key = input.dataset.perfInput;
      const param = paramMap[key];
      if (!param) return;
      const onChange = () => {
        if (param.value_type === "bool") {
          const lbl = input.parentElement && input.parentElement.querySelector(".perf-switch-text");
          if (lbl) lbl.textContent = input.checked ? "已开启" : "已关闭";
        }
        syncParamRow(key, parseInputToRawValue(param, input));
      };
      input.addEventListener("change", onChange);
      if (input.type === "number") input.addEventListener("input", onChange);
    });

    $$("[data-perf-reset-key]", node).forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.perfResetKey;
        const param = paramMap[key];
        if (!param) return;
        const input = $('[data-perf-input="' + key.replace(/["\\]/g, "\\$&") + '"]', node);
        if (input) {
          if (param.value_type === "bool") {
            input.checked = Boolean(param.tier_default);
            const lbl = input.parentElement && input.parentElement.querySelector(".perf-switch-text");
            if (lbl) lbl.textContent = input.checked ? "已开启" : "已关闭";
          } else if (param.value_type === "enum") {
            input.value = String(param.tier_default);
          } else {
            input.value = toDisplayInputValue(param, param.tier_default);
          }
        }
        syncParamRow(key, null);
      });
    });

    const advDetails = $("#perfAdvancedDetails", node);
    if (advDetails) {
      advDetails.addEventListener("toggle", () => {
        perfUiState.advancedOpen = Boolean(advDetails.open);
      });
    }
    bindSmoothDetails(node);

    const applyTuning = async (resetAll) => {
      const profileChanged = selectedProfile !== savedProfile;
      const payload = {
        profile: selectedProfile,
        reset_overrides: Boolean(resetAll),
        preserve_overrides: resetAll ? false : (profileChanged ? Boolean(perfUiState.preserveOnSwitch) : true),
      };
      if (!resetAll) {
        const sourceMap = (!profileChanged || perfUiState.preserveOnSwitch) ? editedOverrides : dirtyOverrides;
        const delta = {};
        Object.keys(sourceMap).forEach((k) => {
          delta[k] = sourceMap[k];
        });
        if (Object.keys(delta).length) payload.overrides = delta;
      }
      await withBusy(resetAll ? "正在恢复档位默认…" : "正在应用性能调优…", async () => {
        try {
          const res = await apiPost("/performance/tuning", payload);
          const tuning = (res && res.tuning) || res || {};
          perfUiState.draftProfile = "";
          perfUiState.preserveOnSwitch = false;
          perfUiState.lastHotReload = tuning.hot_reload || null;
          state.configSchema = null;
          invalidatePool();
          const clampedCount = Array.isArray(tuning.clamped_fields) ? tuning.clamped_fields.length : 0;
          if (clampedCount > 0) {
            toast("性能调优已生效（" + clampedCount + " 项已触发防爆内存限幅）", "ok");
          } else {
            toast(resetAll ? "已恢复所选档位全部默认参数" : "性能调优已保存并热生效", "ok");
          }
          await go("performance");
        } catch (error) {
          toast("性能调优保存失败：" + error.message, "error");
        }
      });
    };

    const saveBtn = $("#perfSaveBtn", node);
    if (saveBtn) saveBtn.addEventListener("click", () => applyTuning(false));
    const resetAllBtn = $("#perfResetAllBtn", node);
    if (resetAllBtn) resetAllBtn.addEventListener("click", () => applyTuning(true));
    const resetAllFooterBtn = $("#perfResetAllFooterBtn", node);
    if (resetAllFooterBtn) resetAllFooterBtn.addEventListener("click", () => applyTuning(true));

    const goDbBtn = $("#perfGoDbHealthBtn", node);
    if (goDbBtn) {
      goDbBtn.addEventListener("click", () => {
        state.pendingViewFocus = { viewId: "migrate", target: "dbHealthCard" };
        go("migrate");
      });
    }

    if (state.pendingViewFocus && state.pendingViewFocus.viewId === "performance") {
      const target = compact(state.pendingViewFocus.target);
      state.pendingViewFocus = null;
      if (target.startsWith("tier:")) {
        const tierId = target.slice(5);
        const cardEl = $('[data-perf-tier="' + tierId.replace(/["\\]/g, "\\$&") + '"]', node);
        if (cardEl) {
          requestAnimationFrame(() => {
            try { cardEl.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "center" }); } catch (err) { /* 忽略 */ }
            cardEl.classList.add("is-search-hit");
            window.setTimeout(() => cardEl.classList.remove("is-search-hit"), 2200);
          });
        }
      }
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

  const drawerNode = $("#drawer");
  if (drawerNode && !drawerNode.classList.contains("is-open")) drawerNode.inert = true;
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

  initConfigSearch();

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
    const peopleLink =
      event && event.target && typeof event.target.closest === "function"
        ? event.target.closest('a[data-people-link], a[href^="./people.html"]')
        : null;
    if (peopleLink && typeof peopleLink.setAttribute === "function") {
      peopleLink.setAttribute("href", peopleHref());
      return;
    }
    const target = event.target.closest("[data-goto]");
    if (!target) return;
    const view = target.dataset.goto;
    const filter = compact(target.dataset.filter);
    const options = {};
    if (compact(target.dataset.scope)) options.scope = target.dataset.scope;
    if (compact(target.dataset.target)) options.target = target.dataset.target;
    const ownerBot = compact(target.dataset.ownerBot);
    if (ownerBot) {
      state.filters = { scope: "", q: "", visibility: "", lifecycle: "", memoryType: "", target: "", ownerBot: ownerBot };
    } else if (filter === "all") {
      state.filters = { scope: "", q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };
    } else if (filter) {
      if (filter.indexOf("scope:") === 0) {
        state.filters = { scope: filter.slice(6), q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };
      } else if (filter === "profile") {
        state.filters = { scope: "profile", q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };
      } else if (filter.indexOf("external:") === 0) {
        state.filters = { scope: "", q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };
      } else if (filter.indexOf("tab:") === 0) {
        quarantineTab = filter.slice(4) === "pending" ? "pending" : "quarantined";
        quarantineOffset = 0;
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
      if (box) closeLightbox(box);
    }
  });
}

async function boot() {
  bindShell();
  applyTheme(state.theme, { persist: false });
  applyMode(state.mode);
  renderRail();
  bindBridgeContext();
  setRailStatus("loading", "正在连接…");

  const initial = document.documentElement.dataset.initialNav;
  const target = state.mode === "cinema" ? "overview" : (initial && VIEWS[initial] ? initial : "overview");

  let prefsLoaded = false;
  try {
    await apiGet("/stats");
    setRailStatus("ok", "已连接");
    // 2.6.6：浏览器存储被清过也能恢复上次的深色/浅色选择
    const prefs = await apiGet("/ui-preferences").catch(() => null);
    if (prefs) {
      prefsLoaded = true;
      if (typeof prefs.palette === "string") applyPalette(prefs.palette);
      if (typeof prefs.dark_mode === "boolean" && prefs.dark_mode_saved !== false) {
        const want = prefs.dark_mode ? "dark" : "light";
        state.explicitTheme = want;
        if (!state.manualThemeToggled && want !== state.theme) {
          applyTheme(want, { persist: false });
        }
      }
    }
  } catch (error) {
    setRailStatus("bad", "连接失败");
  }

  state.ready = true;
  await go(target);
  // 配色放最后：不阻塞首屏，失败也不影响面板可用
  if (!prefsLoaded) syncPalette();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
