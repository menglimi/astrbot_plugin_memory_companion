/* 她记得的人：以人为主的面板。
   打开先看人，点开一个人能改称呼、纠正分量、让她忘掉某件事，
   也可以把她对这个人的一切整个擦掉（需要输入确认词）。
   数据来自 /people /person /person/weight /person/erase，
   动作复用 /memory/update 与 /memory/delete。 */
const API = "/api/plug/astrbot_plugin_memory_companion/page";
const PAGE_ENDPOINT_PREFIX = "page";

const state = { items: [], bots: [], total: 0, query: "", sort: "weight", botId: "", selected: null, loading: false };

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

async function load() {
  if (state.loading) return;
  state.loading = true;
  loading.hidden = false;
  empty.hidden = true;
  grid.innerHTML = "";
  try {
    const data = await request("GET", "people", personParams({ q: state.query, sort: state.sort, limit: 120 }));
    state.items = Array.isArray(data.items) ? data.items : [];
    state.total = Number(data.total || state.items.length);
    state.bots = Array.isArray(data.bots) ? data.bots : [];
    renderSummary();
    renderBotFilter();
    renderGrid();
  } catch (error) {
    loading.hidden = true;
    subtitle.textContent = "没连上她…";
    toast(`翻记忆失败：${error.message || error}`);
    empty.hidden = false;
  } finally {
    state.loading = false;
    loading.hidden = true;
  }
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

function renderGrid() {
  if (!state.items.length) {
    const hasQuery = Boolean(state.query || state.botId);
    empty.hidden = false;
    empty.innerHTML = hasQuery
      ? "<h2>这个人她还没记住</h2><p>换个名字试试，或者清掉筛选。她只会记住真的聊过的人。</p>"
      : `<h2>她还没记住谁</h2><p>等有人跟她多聊几次，人就会自己长出来。这里不用配置，她本来就在记。</p><p class="dim">想看她把每句话记成了什么？去 <a href="./legacy.html">完整控制台</a> 翻记忆库。</p>`;
    return;
  }
  empty.hidden = true;
  grid.innerHTML = state.items.map((item) => {
    const top = Array.isArray(item.top) ? item.top.slice(0, 2) : [];
    const chips = [`<span class="chip band ${bandClass(item.band)}">${esc(item.band_label)}</span>`];
    if (item.address) chips.push(`<span class="chip">叫她「${esc(item.address)}」</span>`);
    if (item.relation_label) chips.push(`<span class="chip">${esc(item.relation_label)}</span>`);
    return `<button class="card" type="button" data-user="${esc(item.user_id)}" data-platform="${esc(item.platform)}" data-bot="${esc(item.bot_id)}">
      <div class="card-head">
        <span class="avatar">${esc(initials(item.display_name))}</span>
        <div class="who"><div class="name">${esc(item.display_name)}</div><div class="sub">${esc(fmtDays(item.days_since_last))}</div></div>
      </div>
      <div class="chips">${chips.join("")}</div>
      <div class="bar" title="分量 ${esc(item.weight)}"><span style="width:${Math.max(3, Math.min(100, Number(item.weight) || 0))}%"></span></div>
      <div class="meta">${item.memory_count} 件事${item.imprint_count ? ` · ${item.imprint_count} 件刻骨` : ""}</div>
      ${top.length ? `<ul class="memories">${top.map((entry) => `<li>${esc(entry.content)}</li>`).join("")}</ul>` : ""}
    </button>`;
  }).join("");
  grid.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", () => openPerson(card.dataset.user, card.dataset.platform, card.dataset.bot));
  });
}

function closeDrawer() {
  drawer.hidden = true;
  scrim.hidden = true;
  state.selected = null;
}

async function openPerson(userId, platform, botId) {
  drawer.hidden = false;
  scrim.hidden = false;
  drawerBody.innerHTML = `<p class="loading">正在翻开她的记忆…</p>`;
  try {
    const data = await request("GET", "person", { user_id: userId, platform: platform || "", bot_id: botId || "" });
    state.selected = data;
    renderDrawer(data);
  } catch (error) {
    drawerBody.innerHTML = `<p class="loading">翻不开了：${esc(error.message || error)}</p>`;
  }
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
  const payload = {
    user_id: data.user_id,
    platform: data.platform || "",
    bot_id: data.bot_id || "",
    weight,
    address: el("addressInput").value.trim(),
    label: el("relationInput").value.trim(),
    note: el("noteInput").value.trim(),
    // 危险路由的确认口令：后端按 CONFIRM:<route> 校验。
    confirm: "CONFIRM:/person/weight",
  };
  try {
    await request("POST", "person/weight", null, payload);
    toast("记住了");
    await load();
    await openPerson(data.user_id, data.platform, data.bot_id);
  } catch (error) {
    toast(`没存上：${error.message || error}`);
  }
}

async function resetWeight() {
  const data = state.selected;
  if (!data) return;
  try {
    await request("POST", "person/weight", null, { user_id: data.user_id, platform: data.platform || "", bot_id: data.bot_id || "", weight: null, confirm: "CONFIRM:/person/weight" });
    toast("分量交回给她自己算");
    await load();
    await openPerson(data.user_id, data.platform, data.bot_id);
  } catch (error) {
    toast(`没改成功：${error.message || error}`);
  }
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
  hint.hidden = false;
  hint.textContent = "正在擦，别关面板…";
  if (!window.confirm(`真的要把「${name}」从她的记忆里整个擦掉吗？分量、称呼和记得的事都会没，找不回来。`)) {
    hint.textContent = "好，那就先不擦。";
    return;
  }
  try {
    await request("POST", "person/erase", null, {
      user_id: data.user_id,
      platform: data.platform || "",
      bot_id: data.bot_id || "",
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
  if (!window.confirm("让她以后不再主动想起这条？原文不会丢，还能在控制台翻回来。")) return;
  const data = state.selected;
  try {
    await request("POST", "memory/update", null, { id: memoryId, durability: "short" });
    toast("这条放轻了");
    if (data) await openPerson(data.user_id, data.platform, data.bot_id);
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
el("refresh").addEventListener("click", load);
el("close").addEventListener("click", closeDrawer);
scrim.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });

load();
