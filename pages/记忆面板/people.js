/* 她记得的人：以人为主的面板。
   打开先看人，点开一个人能改称呼、纠正分量、让她忘掉某件事，
   也可以把她对这个人的一切整个擦掉（需要输入确认词）。
   数据来自 /people /person /person/weight /person/erase，
   动作复用 /memory/update 与 /memory/delete。 */
const API = "/api/plug/astrbot_plugin_memory_companion/page";
const PAGE_ENDPOINT_PREFIX = "page";
const PALETTE_KEYS = new Set([
  "huangbaiyou", "tianpiao", "haitianxia", "yingying", "oubi", "qingming",
  "zipu", "shanlan", "qielan", "tuihong", "congqing", "yuebai", "mocan", "gupiao",
]);
const THEME_META_COLORS = { dark: "#0f1218", light: "#f6f7fa" };

function currentSearch() {
  return typeof location !== "undefined" && location && typeof location.search === "string"
    ? location.search
    : "";
}

function readUrlTheme() {
  try {
    const searchText = currentSearch();
    if (!searchText || typeof URLSearchParams !== "function") return "";
    const value = new URLSearchParams(searchText).get("theme");
    return value === "light" || value === "dark" ? value : "";
  } catch (_) {
    return "";
  }
}

function resolveInitialTheme() {
  const fromUrl = readUrlTheme();
  if (fromUrl) return fromUrl;
  const root = typeof document !== "undefined" && document ? document.documentElement : null;
  const preset = root && root.dataset ? root.dataset.theme : "";
  if (preset === "light" || preset === "dark") return preset;
  try {
    if (typeof window !== "undefined" && window && typeof window.matchMedia === "function") {
      if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
    }
  } catch (_) {}
  return "dark";
}

const PEOPLE_PAGE_SIZE = 48;

const state = {
  items: [],
  bots: [],
  total: 0,
  offset: 0,
  hasMore: false,
  loadingMore: false,
  loadError: "",
  loadEpoch: 0,
  query: "",
  sort: "weight",
  botId: "",
  selected: null,
  selectedScope: { platform: "", bot_id: "" },
  loading: false,
  theme: resolveInitialTheme(),
  palette: "",
  hasHostTheme: Boolean(readUrlTheme()),
  lastHostIsDark: null,
  explicitTheme: "",
  manualThemeToggled: false,
};
let peopleAutoScroll = null;

const el = (id) => document.getElementById(id);
const grid = el("grid");
const empty = el("empty");
const loading = el("loading");
const summary = el("summary");
const subtitle = el("subtitle");
const search = el("search");
const sortSelect = el("sort");
const botFilter = el("botFilter");
const drawer = el("drawer");
const drawerBody = el("drawerBody");
const scrim = el("scrim");
const themeToggle = el("themeToggle");
const themeToggleLabel = el("themeToggleLabel");

function pageHref(targetPath) {
  const searchText = currentSearch();
  if (!searchText) return targetPath;
  const hashIndex = targetPath.indexOf("#");
  const base = hashIndex >= 0 ? targetPath.slice(0, hashIndex) : targetPath;
  const hash = hashIndex >= 0 ? targetPath.slice(hashIndex) : "";
  if (base.includes("?")) return targetPath;
  try {
    if (typeof URLSearchParams === "function") {
      const params = new URLSearchParams(searchText);
      if (params.has("theme") && (state.theme === "light" || state.theme === "dark")) {
        params.set("theme", state.theme);
        const serialized = params.toString();
        return `${base}${serialized ? `?${serialized}` : ""}${hash}`;
      }
    }
  } catch (_) {}
  return `${base}${searchText}${hash}`;
}

function syncConsoleLinks() {
  if (typeof document === "undefined" || !document || typeof document.querySelectorAll !== "function") return;
  const href = pageHref("./legacy.html");
  document.querySelectorAll('a[data-console-link], a[href^="./legacy.html"]').forEach((link) => {
    if (link && typeof link.setAttribute === "function") link.setAttribute("href", href);
  });
}

function resolveThemeMetaColor(theme) {
  const fallback = theme === "light" ? THEME_META_COLORS.light : THEME_META_COLORS.dark;
  const root = typeof document !== "undefined" && document ? document.documentElement : null;
  if (root && typeof window !== "undefined" && window && typeof window.getComputedStyle === "function") {
    try {
      const bg = String(window.getComputedStyle(root).getPropertyValue("--bg") || "").trim();
      if (/^#[0-9a-f]{3,8}$/i.test(bg)) return bg;
    } catch (_) {}
  }
  return fallback;
}

function syncThemeChrome(theme) {
  const isLight = theme === "light";
  const meta =
    typeof document !== "undefined" && document && typeof document.querySelector === "function"
      ? document.querySelector('meta[name="theme-color"]')
      : null;
  if (meta && typeof meta.setAttribute === "function") {
    meta.setAttribute("content", resolveThemeMetaColor(theme));
  }
  if (themeToggle && typeof themeToggle.setAttribute === "function") {
    themeToggle.setAttribute("aria-pressed", isLight ? "false" : "true");
    themeToggle.setAttribute("title", isLight ? "当前浅色，点击切换为深色主题" : "当前深色，点击切换为浅色主题");
  }
  if (themeToggleLabel) {
    themeToggleLabel.textContent = isLight ? "浅色" : "深色";
  }
  syncConsoleLinks();
}

function applyPalette(key) {
  const value = String(key || "").trim().toLowerCase();
  const root = typeof document !== "undefined" && document ? document.documentElement : null;
  if (PALETTE_KEYS.has(value)) {
    state.palette = value;
    if (root && root.dataset) root.dataset.palette = value;
    else if (root && typeof root.setAttribute === "function") root.setAttribute("data-palette", value);
    syncThemeChrome(state.theme);
    return value;
  }
  state.palette = "";
  if (root && root.dataset) delete root.dataset.palette;
  else if (root && typeof root.removeAttribute === "function") root.removeAttribute("data-palette");
  syncThemeChrome(state.theme);
  return "";
}

function applyTheme(theme, options) {
  const opts = options && typeof options === "object" ? options : {};
  const next = theme === "light" ? "light" : "dark";
  state.theme = next;
  const root = typeof document !== "undefined" && document ? document.documentElement : null;
  if (root && root.dataset) root.dataset.theme = next;
  else if (root && typeof root.setAttribute === "function") root.setAttribute("data-theme", next);
  syncThemeChrome(next);
  if (opts.persist === true) {
    state.manualThemeToggled = true;
    state.explicitTheme = next;
    request("POST", "ui-preferences/save", null, { dark_mode: next === "dark" }).catch(() => {});
  }
}

function handleBridgeContext(ctx) {
  if (!ctx || typeof ctx !== "object" || typeof ctx.isDark !== "boolean") return;
  const hostTheme = ctx.isDark ? "dark" : "light";
  const prevHostIsDark = state.lastHostIsDark;
  state.lastHostIsDark = ctx.isDark;
  state.hasHostTheme = true;

  // 宿主实时切换主题：立即跟随宿主当前深浅模式。
  if (prevHostIsDark !== null && prevHostIsDark !== ctx.isDark) {
    state.explicitTheme = "";
    applyTheme(hostTheme, { persist: false });
    return;
  }

  // 首次收到宿主上下文：若用户已手动切换或后端已有显式偏好，恢复该偏好。
  if (state.manualThemeToggled || state.explicitTheme) {
    applyTheme(state.explicitTheme || state.theme, { persist: false });
    return;
  }
  applyTheme(hostTheme, { persist: false });
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

async function loadPreferences() {
  try {
    const prefs = await request("GET", "ui-preferences");
    if (!prefs || typeof prefs !== "object") return;
    if (typeof prefs.palette === "string") {
      applyPalette(prefs.palette);
    }
    if (typeof prefs.dark_mode === "boolean" && prefs.dark_mode_saved !== false) {
      const want = prefs.dark_mode ? "dark" : "light";
      state.explicitTheme = want;
      if (!state.manualThemeToggled) {
        applyTheme(want, { persist: false });
      }
    }
  } catch (_) {}
}

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
}

function initials(name) {
  const text = String(name || "").trim();
  if (!text) return "?";
  const ch = Array.from(text)[0];
  return /[a-zA-Z]/.test(ch) ? ch.toUpperCase() : ch;
}

function fmtDays(days) {
  if (days == null) return "还没说过话";
  if (days < 1) return "今天说过话";
  if (days < 2) return "昨天说过话";
  if (days < 31) return `${Math.round(days)} 天前说过话`;
  if (days < 365) return `${Math.round(days / 30)} 个月前说过话`;
  return `${Math.round(days / 365)} 年前说过话`;
}

function bandClass(band) {
  return ["imprint", "important", "close"].includes(band) ? band : "";
}

function toast(message) {
  const node = el("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.hidden = true; }, 2600);
}

function getBridge() {
  if (window.AstrBotPluginPage) return window.AstrBotPluginPage;
  try {
    if (window.parent && window.parent !== window && window.parent.AstrBotPluginPage) return window.parent.AstrBotPluginPage;
  } catch (_) {}
  return null;
}

async function waitForBridge() {
  for (let index = 0; index < 40; index += 1) {
    const bridge = getBridge();
    if (bridge) return bridge;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return null;
}

function unwrap(payload) {
  if (payload && typeof payload === "object" && payload.status === "error") {
    throw new Error(payload.message || payload.error || "请求失败");
  }
  if (payload && typeof payload === "object" && payload.success === false) {
    throw new Error(payload.error || "请求失败");
  }
  if (payload && typeof payload === "object" && payload.data !== undefined && payload.data !== null && typeof payload.data === "object") {
    return payload.data;
  }
  return payload;
}

// P13/P9：写操作统一补 CSRF 令牌与一次性确认 nonce。
// rawRequest 是底层通道，取令牌/取 nonce 时不能再次触发注入逻辑。
const WRITE_CONFIRM_ROUTES = new Set([
  "person/weight",
  "person/erase",
  "memory/delete",
  "core-memory/delete",
  "maintenance/clear_all",
  "maintenance/clear_scope",
  "import/livingmemory/run",
  "data/import/run",
  "portrait/govern",
  "maintenance/audit/apply",
  "maintenance/audit/rollback",
  "conversation-import/rollback",
  "config/module/update",
]);

let csrfTokenCache = { token: "", expiresAt: 0 };

async function ensureCsrfToken() {
  const now = Date.now();
  if (csrfTokenCache.token && csrfTokenCache.expiresAt > now + 5000) {
    return csrfTokenCache.token;
  }
  try {
    const data = await rawRequest("GET", "ui/csrf", null, null);
    if (data && typeof data.token === "string" && data.token) {
      const ttl = Number(data.expires_in) > 0 ? Number(data.expires_in) : 900;
      csrfTokenCache = { token: data.token, expiresAt: now + ttl * 1000 };
      return data.token;
    }
  } catch (error) {
    return "";
  }
  return "";
}

async function requestNonce(route, payload, token) {
  try {
    const body = { route: "/" + route, payload: payload || {} };
    if (token) body.csrf_token = token;
    const data = await rawRequest("POST", "ui/confirm-nonce", null, body);
    return data && typeof data.confirm === "string" ? data.confirm : "";
  } catch (error) {
    return "";
  }
}

async function secureWriteBody(path, body) {
  const route = String(path || "").replace(/^\/+/, "");
  const payload = Object.assign({}, body || {});
  const token = await ensureCsrfToken();
  if (token) payload.csrf_token = token;
  if (WRITE_CONFIRM_ROUTES.has(route)) {
    const nonce = await requestNonce(route, payload, token);
    if (nonce) payload.confirm = nonce;
  }
  return payload;
}

async function request(method, path, params, body) {
  const payload = method === "GET" ? body : await secureWriteBody(path, body);
  return rawRequest(method, path, params, payload);
}

async function rawRequest(method, path, params, body) {
  const bridge = getBridge() || (await waitForBridge());
  if (bridge && typeof bridge.apiGet === "function") {
    if (method === "GET") {
      const query = params && Object.keys(params).length ? params : undefined;
      const data = await bridge.apiGet(`${PAGE_ENDPOINT_PREFIX}/${path}`, query);
      return unwrap(data);
    }
    const data = await bridge.apiPost(`${PAGE_ENDPOINT_PREFIX}/${path}`, body || {});
    return unwrap(data);
  }
  const url = new URL(`${API}/${path}`, location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== "" && value != null) url.searchParams.set(key, value);
  });
  const response = await fetch(url.toString(), {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: method === "GET" ? undefined : { "Content-Type": "application/json" },
    body: method === "GET" ? undefined : JSON.stringify(body || {}),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return unwrap(await response.json());
}

function personParams(extra) {
  const params = Object.assign({}, extra || {});
  if (state.botId) params.bot_id = state.botId;
  return params;
}

function personCardHtml(item) {
  const top = Array.isArray(item.top) ? item.top.slice(0, 1) : [];
  const chips = [`<span class="chip band ${bandClass(item.band)}">${esc(item.band_label)}</span>`];
  if (item.address) chips.push(`<span class="chip">叫她「${esc(item.address)}」</span>`);
  if (item.relation_label) chips.push(`<span class="chip">${esc(item.relation_label)}</span>`);
  // 一张卡代表一个人：这个人要是在多个 bot / 平台下都被记过，点开时
  // 不能再按主行的 bot/平台过滤，不然详情只显示其中一份。
  const spansRows =
    (Array.isArray(item.platforms) ? item.platforms.length : 0) > 1 ||
    (Array.isArray(item.bot_ids) ? item.bot_ids.length : 0) > 1;
  const platform = spansRows ? "" : item.platform || "";
  const botId = spansRows ? "" : item.bot_id || "";
  return `<button class="card" type="button" data-user="${esc(item.user_id)}" data-platform="${esc(platform)}" data-bot="${esc(botId)}">
    <div class="card-head">
      <span class="avatar">${esc(initials(item.display_name))}</span>
      <div class="who"><div class="name">${esc(item.display_name)}</div><div class="sub">${esc(fmtDays(item.days_since_last))}</div></div>
    </div>
    <div class="chips">${chips.join("")}</div>
    <div class="bar" title="分量 ${esc(item.weight)}"><span style="width:${Math.max(3, Math.min(100, Number(item.weight) || 0))}%"></span></div>
    <div class="meta">${item.memory_count} 件事${item.imprint_count ? ` · ${item.imprint_count} 件刻骨` : ""}</div>
    ${top.length ? `<ul class="memories">${top.map((entry) => `<li>${esc(entry.content)}</li>`).join("")}</ul>` : ""}
  </button>`;
}

function bindCardElements(cards) {
  if (!cards || typeof cards.forEach !== "function") return;
  cards.forEach((card) => {
    if (!card || card._mcCardBound) return;
    card._mcCardBound = true;
    card.addEventListener("click", () => openPerson(card.dataset.user, card.dataset.platform, card.dataset.bot));
  });
}

function refreshPeopleAutoScroll() {
  if (peopleAutoScroll && typeof peopleAutoScroll.refresh === "function") {
    peopleAutoScroll.refresh();
  }
}

function resetPeopleAutoScroll() {
  if (peopleAutoScroll && typeof peopleAutoScroll.reset === "function") {
    peopleAutoScroll.reset();
  }
}

async function fetchPeopleSlice(limit, offset) {
  return request("GET", "people", personParams({
    q: state.query,
    sort: state.sort,
    limit,
    offset,
  }));
}

async function load(options) {
  const silent = Boolean(options && options.silent);
  if (state.loading && silent) return;
  const epoch = ++state.loadEpoch;
  state.loading = true;
  state.loadingMore = false;
  state.loadError = "";
  if (!silent) {
    state.offset = 0;
    state.hasMore = false;
    resetPeopleAutoScroll();
    loading.hidden = false;
    empty.hidden = true;
    grid.innerHTML = "";
  }
  try {
    const targetCount = silent ? Math.max(PEOPLE_PAGE_SIZE, state.items.length) : PEOPLE_PAGE_SIZE;
    const collected = [];
    const seen = new Set();
    let fetchedRaw = 0;
    let total = 0;
    let bots = state.bots;
    while (fetchedRaw < targetCount) {
      const chunkLimit = Math.min(120, targetCount - fetchedRaw);
      const data = await fetchPeopleSlice(chunkLimit, fetchedRaw);
      if (epoch !== state.loadEpoch) return;
      const batch = Array.isArray(data.items) ? data.items : [];
      if (fetchedRaw === 0) {
        total = Number(data.total || batch.length);
        bots = Array.isArray(data.bots) ? data.bots : [];
      } else if (data.total != null && Number.isFinite(Number(data.total))) {
        total = Number(data.total);
      }
      for (const item of batch) {
        const uid = String((item && item.user_id) || "");
        if (uid && seen.has(uid)) continue;
        if (uid) seen.add(uid);
        collected.push(item);
      }
      fetchedRaw += batch.length;
      if (batch.length < chunkLimit || fetchedRaw >= total) break;
    }
    if (epoch !== state.loadEpoch) return;
    state.items = collected;
    state.total = Math.max(collected.length, total);
    state.bots = bots;
    state.offset = fetchedRaw;
    state.hasMore = state.offset < state.total && fetchedRaw > 0;
    renderSummary();
    renderBotFilter();
    renderGrid();
    refreshPeopleAutoScroll();
  } catch (error) {
    if (epoch !== state.loadEpoch) return;
    loading.hidden = true;
    if (!silent || !state.items.length) {
      subtitle.textContent = "没连上她…";
      empty.hidden = false;
    }
    toast(`翻记忆失败：${error.message || error}`);
  } finally {
    if (epoch === state.loadEpoch) {
      state.loading = false;
      loading.hidden = true;
      refreshPeopleAutoScroll();
    }
  }
}

async function loadMore() {
  if (state.loading || state.loadingMore || !state.hasMore) return;
  const epoch = state.loadEpoch;
  const reqOffset = state.offset;
  state.loadingMore = true;
  state.loadError = "";
  try {
    const data = await fetchPeopleSlice(PEOPLE_PAGE_SIZE, reqOffset);
    if (epoch !== state.loadEpoch) return;
    const batch = Array.isArray(data.items) ? data.items : [];
    const seen = new Set(state.items.map((item) => String((item && item.user_id) || "")).filter(Boolean));
    const fresh = [];
    for (const item of batch) {
      const uid = String((item && item.user_id) || "");
      if (uid && seen.has(uid)) continue;
      if (uid) seen.add(uid);
      fresh.push(item);
    }
    if (data.total != null && Number.isFinite(Number(data.total))) {
      state.total = Math.max(state.items.length + fresh.length, Number(data.total));
    }
    if (fresh.length) {
      state.items = state.items.concat(fresh);
      appendGridCards(fresh);
    }
    state.offset = reqOffset + batch.length;
    state.hasMore = state.offset < state.total && batch.length > 0;
    renderSummary();
  } catch (error) {
    if (epoch !== state.loadEpoch) return;
    state.loadError = error && error.message ? error.message : String(error || "请求失败");
    toast(`加载更多人物失败：${state.loadError}`);
    throw error;
  } finally {
    if (epoch === state.loadEpoch) {
      state.loadingMore = false;
      refreshPeopleAutoScroll();
    }
  }
}

let recoveryTicket = 0;

async function loadRecoveryStatus() {
  const ticket = ++recoveryTicket;
  const node = el("recovery");
  try {
    const payload = await request("GET", "maintenance/summary_status");
    if (ticket !== recoveryTicket) return;
    renderRecoveryStatus(payload && payload.status);
  } catch (_error) {
    if (ticket !== recoveryTicket) return;
    if (node) node.hidden = true;
  }
}

function safeInt(value) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.max(0, Math.round(n)) : 0;
}

function formatWaitDuration(seconds) {
  const value = safeInt(seconds);
  if (value === 0) return "无";
  if (value < 60) return "不足 1 分钟";
  if (value >= 86400) return `${Math.floor(value / 86400)} 天 ${Math.floor((value % 86400) / 3600)} 小时`;
  if (value >= 3600) return `${Math.floor(value / 3600)} 小时 ${Math.floor((value % 3600) / 60)} 分钟`;
  return `${Math.floor(value / 60)} 分钟`;
}

function renderRecoveryStatus(status) {
  const node = el("recovery");
  if (!node || !status || typeof status !== "object") {
    if (node) node.hidden = true;
    return;
  }
  const progress = status.progress && typeof status.progress === "object" ? status.progress : {};
  const originals = status.unbatched && typeof status.unbatched === "object" ? status.unbatched : {};
  const labels = status.wait_labels && typeof status.wait_labels === "object" ? status.wait_labels : {};
  const waitsMap = status.waits && typeof status.waits === "object" ? status.waits : {};
  const waits = Object.keys(labels)
    .filter((key) => safeInt(waitsMap[key]) > 0)
    .map((key) => `${esc(labels[key])} ${safeInt(waitsMap[key])} 批`)
    .join(" · ");
  node.hidden = false;
  node.innerHTML = `<summary>记忆整理：待处理 <b>${safeInt(status.pending_batches)}</b> 批</summary>
    <p>全局状态，包含所有机器人。最老等待 ${formatWaitDuration(status.oldest_wait_seconds)}。
    ${waits || "没有有效待处理批次"}。</p>
    <p>未分批原文 ${safeInt(originals.events)} 条，下一轮达到条件且身份有效 ${safeInt(originals.eligible_events)} 条。
    正式会话记忆 ${safeInt(progress.adopted_memories)} 条，待审候选 ${safeInt(progress.review_candidates)} 条，隔离批次 ${safeInt(progress.quarantined_batches)} 批。</p>
    <p>查看状态不会调用模型或通过候选。<a data-console-link href="${esc(pageHref("./legacy.html"))}">在完整控制台查看详细等待原因</a></p>`;
}

function renderSummary() {
  const imprint = state.items.filter((item) => item.band === "imprint").length;
  summary.hidden = false;
  summary.innerHTML = state.total
    ? `她心里记着 <b>${state.total}</b> 个人${imprint ? `，其中 <b>${imprint}</b> 个是刻骨的` : ""}。`
    : "";
  subtitle.textContent = state.total ? "点开任何一个人，都能改她怎么叫、怎么想这个人。" : "正在想…";
}

function renderBotFilter() {
  if (state.bots.length <= 1) {
    botFilter.hidden = true;
    return;
  }
  botFilter.hidden = false;
  botFilter.innerHTML = [`<option value="">所有 bot</option>`].concat(
    state.bots.map((bot) => `<option value="${esc(bot.bot_id)}"${bot.bot_id === state.botId ? " selected" : ""}>${esc(bot.bot_id)}（${bot.people} 人）</option>`),
  ).join("");
}

function appendGridCards(items) {
  if (!items || !items.length) return;
  const html = items.map(personCardHtml).join("");
  if (typeof document !== "undefined" && typeof document.createElement === "function" && typeof grid.appendChild === "function") {
    const bucket = document.createElement("div");
    bucket.innerHTML = html;
    const nodes = Array.from(bucket.children || []);
    bindCardElements(nodes);
    for (const card of nodes) grid.appendChild(card);
    return;
  }
  if (typeof grid.insertAdjacentHTML === "function") {
    grid.insertAdjacentHTML("beforeend", html);
  } else {
    grid.innerHTML += html;
  }
  if (typeof grid.querySelectorAll === "function") {
    bindCardElements(grid.querySelectorAll(".card"));
  }
}

function renderGrid() {
  if (!state.items.length) {
    const hasQuery = Boolean(state.query || state.botId);
    empty.hidden = false;
    empty.innerHTML = hasQuery
      ? "<h2>这个人她还没记住</h2><p>换个名字试试，或者清掉筛选。她只会记住真的聊过的人。</p>"
      : `<h2>她还没记住谁</h2><p>等有人跟她多聊几次，人就会自己长出来。这里不用配置，她本来就在记。</p><p class="dim">想看她把每句话记成了什么？去 <a data-console-link href="${esc(pageHref("./legacy.html"))}">完整控制台</a> 翻记忆库。</p>`;
    return;
  }
  empty.hidden = true;
  grid.innerHTML = state.items.map(personCardHtml).join("");
  bindCardElements(grid.querySelectorAll(".card"));
}

let drawerRequestSeq = 0;

function closeDrawer() {
  drawerRequestSeq += 1;
  drawer.hidden = true;
  scrim.hidden = true;
  state.selected = null;
  state.selectedScope = { platform: "", bot_id: "" };
}

async function openPerson(userId, platform, botId, options) {
  const opts = options || {};
  const nextPlatform = platform || "";
  const nextBotId = botId || "";
  const prevScope = state.selectedScope || {};
  const sameOpenPerson =
    !drawer.hidden &&
    state.selected &&
    String(state.selected.user_id || "") === String(userId || "") &&
    (prevScope.platform || "") === nextPlatform &&
    (prevScope.bot_id || "") === nextBotId;
  const silent = Boolean(opts.silent) || sameOpenPerson;
  const preserveScroll = Boolean(opts.preserveScroll || silent);
  const prevScrollTop = preserveScroll ? (drawer.scrollTop || 0) : 0;
  const activeEl = silent && typeof document !== "undefined" ? document.activeElement : null;
  const prevActiveId =
    activeEl && activeEl.id && typeof drawer.contains === "function" && drawer.contains(activeEl)
      ? activeEl.id
      : "";
  const eraseInputEl = silent ? el("eraseConfirmInput") : null;
  const prevEraseDraft = eraseInputEl ? (eraseInputEl.value || "") : "";

  const reqSeq = drawerRequestSeq + 1;
  drawerRequestSeq = reqSeq;
  drawer.hidden = false;
  scrim.hidden = false;
  if (!silent) {
    drawerBody.innerHTML = `<p class="loading">正在翻开她的记忆…</p>`;
    drawer.scrollTop = 0;
  }
  // 记住这次是从哪个范围点开的：合并卡点开时是空的，表示「这个人」，
  // 后续改分量、擦除都该按人算，而不是按详情回填的某个平台。
  state.selectedScope = { platform: nextPlatform, bot_id: nextBotId };
  try {
    const data = await request("GET", "person", { user_id: userId, platform: nextPlatform, bot_id: nextBotId });
    if (reqSeq !== drawerRequestSeq || drawer.hidden) return;
    state.selected = data;
    renderDrawer(data);
    if (silent && prevEraseDraft) {
      const nextErase = el("eraseConfirmInput");
      if (nextErase) nextErase.value = prevEraseDraft;
    }
    if (preserveScroll) {
      drawer.scrollTop = prevScrollTop;
    }
    if (prevActiveId) {
      const nextActive = el(prevActiveId);
      if (nextActive && !nextActive.disabled && typeof nextActive.focus === "function") {
        try { nextActive.focus({ preventScroll: true }); } catch (_) { nextActive.focus(); }
      }
    }
  } catch (error) {
    if (reqSeq !== drawerRequestSeq || drawer.hidden) return;
    if (silent) {
      toast(`没刷新上：${error.message || error}`);
      return;
    }
    drawerBody.innerHTML = `<p class="loading">翻不开了：${esc(error.message || error)}</p>`;
  }
}

function personScope() {
  const scope = state.selectedScope || {};
  return { platform: scope.platform || "", bot_id: scope.bot_id || "" };
}

function weightText(weight) {
  const value = Number(weight) || 0;
  return value >= 85 ? "刻骨的人" : value >= 65 ? "很重要的人" : value >= 45 ? "亲近的人" : value >= 25 ? "熟人" : value >= 10 ? "认识的人" : "路过的人";
}

function renderDrawer(data) {
  const profile = data.profile && typeof data.profile === "object" ? data.profile : {};
  const weight = data.weight && typeof data.weight === "object" ? data.weight : {};
  const memories = Array.isArray(data.memories) ? data.memories : [];
  const name = data.display_name || data.user_id;
  const chips = [`<span class="chip band ${bandClass(weight.band)}">${esc(weight.band_label || weightText(weight.weight))}</span>`];
  if (profile.relation_label) chips.push(`<span class="chip">${esc(profile.relation_label)}</span>`);
  const memoryItems = memories.length
    ? memories.map((item) => {
      const tier = item.tier === "imprint" ? "刻骨" : item.tier === "important" ? "重要" : "普通";
      return `<li>
        <div class="text">${esc(item.content)}</div>
        <div class="line"><span>${esc(tier)}</span><span>·</span><span>${esc(item.memory_type || "")}</span><span>·</span><span>${esc(item.occurred_at || "")}</span>
          <button type="button" data-forget="${esc(item.id)}">让她忘掉这条</button>
        </div>
      </li>`;
    }).join("")
    : `<li><div class="text">她还没给这个人写下什么。</div></li>`;
  drawerBody.innerHTML = `
    <div class="person-head">
      <span class="avatar">${esc(initials(name))}</span>
      <div><h2>${esc(name)}</h2><div class="sub">${esc(data.user_id)}${data.platform ? ` · ${esc(data.platform)}` : ""}</div></div>
    </div>
    <div class="chips">${chips.join("")}</div>
    <div class="block">
      <h3>她心里的分量</h3>
      <div class="weight-row">
        <input id="weightInput" type="range" min="0" max="100" step="1" value="${Math.max(0, Math.min(100, Number(weight.weight) || 0))}" />
        <span id="weightValue" class="weight-value">${Number(weight.weight) || 0} · ${esc(weightText(weight.weight))}</span>
      </div>
      <p class="tip">这是她私下掂量的，不会挂在嘴边。你觉得不对，就直接改，她会记住你的判断。</p>
    </div>
    <div class="block">
      <h3>她怎么称呼这个人</h3>
      <div class="form">
        <div class="row"><label for="addressInput">称呼</label><input id="addressInput" type="text" maxlength="40" placeholder="比如：阿哲、老板、他" value="${esc(profile.relation_address || "")}" /></div>
        <div class="row"><label for="relationInput">关系</label><input id="relationInput" type="text" maxlength="40" placeholder="比如：恋人、老同学、同事" value="${esc(profile.relation_label || "")}" /></div>
        <div class="row"><label for="noteInput">备注</label><input id="noteInput" type="text" maxlength="80" placeholder="只准叫他名字之类" value="${esc(profile.relation_note || "")}" /></div>
      </div>
      <div class="actions">
        <button id="saveBtn" class="primary" type="button">记住这些</button>
        <button id="resetWeightBtn" class="quiet" type="button">分量交还给她自己算</button>
      </div>
    </div>
    <div class="block">
      <h3>她记得这个人的事（${Number(data.total) || memories.length} 条）</h3>
      <ul class="detail-list">${memoryItems}</ul>
      <p class="tip">「让她忘掉这条」只是把这条放轻（不再主动想起），原文还在记忆库里，随时能翻回来。</p>
    </div>
    <div class="block danger">
      <h3>擦掉这个人</h3>
      <p class="tip">会把她对 ${esc(name)} 的分量、称呼、关系、备注和相关记忆一起删掉，删了找不回来。要是只想让她少提，用上面「让她忘掉这条」就够了。</p>
      <div class="form">
        <div class="row"><label for="eraseConfirmInput">确认词</label><input id="eraseConfirmInput" type="text" placeholder="输入：擦掉" autocomplete="off" /></div>
      </div>
      <div class="actions">
        <button id="erasePersonBtn" class="danger" type="button">擦掉这个人的一切</button>
      </div>
      <p id="eraseHint" class="tip" hidden></p>
    </div>
  `;
  const weightInput = el("weightInput");
  const weightValue = el("weightValue");
  weightInput.addEventListener("input", () => {
    weightValue.textContent = `${weightInput.value} · ${weightText(weightInput.value)}`;
  });
  el("saveBtn").addEventListener("click", savePerson);
  el("resetWeightBtn").addEventListener("click", resetWeight);
  el("erasePersonBtn").addEventListener("click", erasePerson);
  el("eraseConfirmInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") erasePerson();
  });
  drawerBody.querySelectorAll("[data-forget]").forEach((button) => {
    button.addEventListener("click", () => forgetMemory(button.dataset.forget));
  });
}

async function savePerson() {
  const data = state.selected;
  if (!data) return;
  const weight = Number(el("weightInput").value);
  const scope = personScope();
  const payload = {
    user_id: data.user_id,
    platform: scope.platform,
    bot_id: scope.bot_id,
    weight,
    // 危险路由的确认口令：后端按 CONFIRM:<route> 校验。
    confirm: "CONFIRM:/person/weight",
  };
  const profile = data.profile || {};
  for (const [field, inputId] of [["address", "addressInput"], ["label", "relationInput"], ["note", "noteInput"]]) {
    const value = el(inputId).value.trim();
    if (value !== (profile[`relation_${field}`] || "")) payload[field] = value;
  }
  try {
    await request("POST", "person/weight", null, payload);
    toast("记住了");
    await Promise.all([
      load({ silent: true }),
      openPerson(data.user_id, scope.platform, scope.bot_id, { silent: true, preserveScroll: true }),
    ]);
  } catch (error) {
    toast(`没存上：${error.message || error}`);
  }
}

async function resetWeight() {
  const data = state.selected;
  if (!data) return;
  const scope = personScope();
  try {
    await request("POST", "person/weight", null, { user_id: data.user_id, platform: scope.platform, bot_id: scope.bot_id, weight: null, confirm: "CONFIRM:/person/weight" });
    toast("分量交回给她自己算");
    await Promise.all([
      load({ silent: true }),
      openPerson(data.user_id, scope.platform, scope.bot_id, { silent: true, preserveScroll: true }),
    ]);
  } catch (error) {
    toast(`没改成功：${error.message || error}`);
  }
}

function confirmPersonAction(title, message, confirmLabel, danger = false) {
  const dialog = el("personConfirm");
  if (dialog.open) return Promise.resolve(false);
  el("personConfirmTitle").textContent = title;
  el("personConfirmMessage").textContent = message;
  const action = el("personConfirmAction");
  action.textContent = confirmLabel;
  action.className = danger ? "danger" : "primary";
  dialog.returnValue = "";
  dialog.showModal();
  el("personConfirmCancel").focus();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
  });
}

async function erasePerson() {
  const data = state.selected;
  if (!data) return;
  const hint = el("eraseHint");
  // 第一步：输入确认词；第二步：再确认一次。两道都过了才真的删。
  const typed = (el("eraseConfirmInput").value || "").trim();
  if (typed !== "擦掉") {
    hint.hidden = false;
    hint.textContent = "还差一步：在确认词里输入「擦掉」，才会真的删。";
    el("eraseConfirmInput").focus();
    return;
  }
  const name = data.display_name || data.user_id;
  const scope = personScope();
  const confirmed = await confirmPersonAction(
    "擦掉这个人的一切",
    `擦掉「${name}」后，分量、称呼和记得的事都无法恢复。`,
    "擦掉",
    true,
  );
  if (state.selected !== data) return;
  hint.hidden = false;
  if (!confirmed) {
    hint.textContent = "好，那就先不擦。";
    return;
  }
  hint.textContent = "正在擦，别关面板…";
  try {
    await request("POST", "person/erase", null, {
      user_id: data.user_id,
      platform: scope.platform,
      bot_id: scope.bot_id,
      confirm: `ERASE:${data.user_id}`,
    });
    toast(`已经把「${name}」擦掉了`);
    closeDrawer();
    await load();
  } catch (error) {
    hint.textContent = `没擦成：${error.message || error}`;
    toast("没擦成，她还记得这个人");
  }
}

async function forgetMemory(memoryId) {
  if (!memoryId) return;
  const data = state.selected;
  const scope = personScope();
  const confirmed = await confirmPersonAction(
    "放轻记忆",
    "她以后不会再主动想起这条，仍可在控制台查看原文。",
    "放轻记忆",
  );
  if (!confirmed || state.selected !== data) return;
  try {
    await request("POST", "memory/update", null, { id: memoryId, durability: "short" });
    toast("这条放轻了");
    if (data) await openPerson(data.user_id, scope.platform, scope.bot_id, { silent: true, preserveScroll: true });
  } catch (error) {
    toast(`没改成：${error.message || error}`);
  }
}

let searchTimer = null;
search.addEventListener("input", () => {
  state.query = search.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(load, 260);
});
sortSelect.addEventListener("change", () => { state.sort = sortSelect.value; load(); });
botFilter.addEventListener("change", () => { state.botId = botFilter.value; load(); });
el("refresh").addEventListener("click", () => {
  load();
  loadRecoveryStatus();
});
if (themeToggle && typeof themeToggle.addEventListener === "function") {
  themeToggle.addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark", { persist: true });
  });
}
document.addEventListener("click", (event) => {
  const target = event && event.target && typeof event.target.closest === "function"
    ? event.target.closest('a[data-console-link], a[href^="./legacy.html"]')
    : null;
  if (target && typeof target.setAttribute === "function") {
    target.setAttribute("href", pageHref("./legacy.html"));
  }
});
el("close").addEventListener("click", closeDrawer);
scrim.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !el("personConfirm").open) closeDrawer();
});

function initPeopleAutoScroll() {
  const host = el("peopleAutoScroll");
  if (!host || typeof window === "undefined" || !window.MemoryAutoScroll || typeof window.MemoryAutoScroll.mount !== "function") {
    return;
  }
  peopleAutoScroll = window.MemoryAutoScroll.mount({
    host,
    scrollRoot: null,
    itemLabel: "人",
    getCursor: () => state.offset,
    hasMore: () => state.hasMore,
    isLoading: () => state.loading || state.loadingMore,
    hasError: () => Boolean(state.loadError),
    getErrorMessage: () => state.loadError,
    getCount: () => state.items.length,
    getTotal: () => state.total,
    onLoadMore: loadMore,
  });
}

applyTheme(state.theme, { persist: false });
bindBridgeContext();
loadPreferences();
initPeopleAutoScroll();
load();
loadRecoveryStatus();
