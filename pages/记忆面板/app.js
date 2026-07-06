const API = "/astrbot_plugin_memory_companion/page";
const PAGE_ENDPOINT_PREFIX = "page";
const TRANSPARENT_IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

const VIEWS = {
  objects: { title: "知识图谱", hint: "查看关系边、跨窗口线程、时间线、记忆节点和拟人维度概览。" },
  film: { title: "群聊记忆", hint: "查看群聊范围内可召回、可管理的结构化记忆。" },
  microscope: { title: "记忆显微镜", hint: "输入一句话，模拟当前对象下的召回和过滤。" },
  relations: { title: "用户记忆", hint: "聚焦用户画像、偏好、称呼和关系声明。" },
  review: { title: "个人记忆", hint: "查看 Bot 自身的每日生活日程、相册、主观记忆和细化片段。" },
  archive: { title: "维护 / 迁移 / 配置", hint: "执行维护、迁移、清理和导入修复。" },
  maintain: { title: "私聊记忆", hint: "查看私聊范围内的对话、偏好、事实和稳定记忆。" },
};

const PERSONAL_MEMORY_VIEW = {
  available: {
    title: "个人记忆",
    hint: "查看 Bot 自身的每日生活日程、相册、主观记忆和细化片段。",
    small: "日程 · 相册 · 主观",
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
    { id: "persona", label: "拟人维度", sublabel: "关系阶段 · 情绪连续性 · 称呼演进", badge: "拟人" },
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
    { id: "config:memory_capture", label: "记忆捕获", sublabel: "记录用户消息与稳定事实", badge: "捕获" },
    { id: "config:memory_summary", label: "长期总结", sublabel: "阶段总结模型与阈值", badge: "总结" },
    { id: "config:conversation_memory", label: "连续对话", sublabel: "群聊片段与低信息保护", badge: "连续" },
    { id: "retrieval", label: "检索召回", sublabel: "候选、Embedding、Rerank", badge: "召回" },
    { id: "config:memory_injection", label: "记忆注入", sublabel: "注入数量、字数与日志", badge: "注入" },
    { id: "config:context_orchestration", label: "注入编排", sublabel: "分槽调度与当前状态保护", badge: "编排" },
    { id: "config:private_companion_bridge", label: "陪伴协同", sublabel: "桥接、去重与提示清理", badge: "联动" },
    { id: "config:visibility", label: "可见性", sublabel: "跨窗口默认边界", badge: "权限" },
    { id: "topology", label: "权限拓扑", sublabel: "可视化记忆权限矩阵", badge: "拓扑" },
    { id: "config:knowledge_graph", label: "图谱关联", sublabel: "节点、边与检索扩展", badge: "图谱" },
    { id: "config:memory_tools", label: "主动工具", sublabel: "回忆、记住、陪伴笔记", badge: "工具" },
    { id: "config:maintenance", label: "维护策略", sublabel: "备份、保留与自然衰减", badge: "维护" },
    { id: "maintenance", label: "维护 / 迁移 / 清理", sublabel: "维护、修复、导入与清理", badge: "维护" },
    { id: "config:appearance", label: "外观", sublabel: "拓展页主题", badge: "主题" },
  ],
};

const CONFIG_ADVANCED_MODULES = {
  conversation_memory: "conversation_memory_advanced",
  context_orchestration: "context_orchestration_advanced",
  maintenance: "maintenance_decay",
};

const CONFIG_ADVANCED_FALLBACKS = {
  "config:conversation_memory_advanced": "config:conversation_memory",
  "config:context_orchestration_advanced": "config:context_orchestration",
  "config:maintenance_decay": "config:maintenance",
  "config:livingmemory_migration": "maintenance",
  migration: "maintenance",
  clear: "maintenance",
};

const CONFIG_MODULE_GUIDES = {
  retrieval: {
    purpose: "决定候选记忆怎么被找出来：本地检索负责稳，Embedding 负责语义补召回，Rerank 负责二阶段重排。",
    tune: "召回太少时启用 Embedding 或提高候选；召回太杂时提高相似度阈值或切回本地检索。",
    avoid: "权限问题不要用召回参数解决；无权限记忆不会进入候选池。",
  },
  memory_capture: {
    purpose: "控制是否把用户消息、Bot 回复、稳定事实和关系边写入记忆流水。",
    tune: "想减少数据库增长时先调最短记录字数或关闭普通消息记录；稳定事实通常建议保留。",
    avoid: "不要随意关闭稳定事实抽取，否则偏好、称呼、生日等长期信息会断档。",
  },
  memory_summary: {
    purpose: "把时间线整理成长期可召回的阶段性记忆，是从流水到长期记忆的主要入口。",
    tune: "总结太慢时提高触发阈值；总结不及时或连续性弱时降低最少事件数和触发条数。",
    avoid: "不要把单次总结事件上限调得过大，输入太长会降低总结质量。",
  },
  memory_injection: {
    purpose: "控制每轮主链请求前注入多少记忆、最多多少字，以及是否记录注入日志。",
    tune: "模型忽略记忆时提高条数或字数；被旧事带偏时降低 TopK 或关闭原始事件注入。",
    avoid: "记忆只是辅助资料，不应该替代当前用户消息。",
  },
  conversation_memory: {
    purpose: "记录连续对话线索，用于承接“继续”“还有呢”“刚才那个”等短句。",
    tune: "群聊承接弱时保留群聊普通发言记录；旧话题污染时加强低信息和新话题保护。",
    avoid: "它不是把最近 N 轮原文硬塞回模型，而是用于后续总结和检索。",
  },
  context_orchestration: {
    purpose: "把自我时间线、用户画像、当前窗口、阶段总结和稳定记忆分槽编排进注入包。",
    tune: "需要更强陪伴线索时调高对应分槽；当前状态问题被旧记忆抢答时保持相关性保护开启。",
    avoid: "不要让所有分槽都过大，总注入仍应服务当前问题。",
  },
  private_companion_bridge: {
    purpose: "与主动陪伴插件协调自我状态、私聊上下文和旧记忆提示，减少重复注入。",
    tune: "看到主动提示或当前状态重复时保持去重开启；排障要看原始上下文时再临时保留外部片段。",
    avoid: "不要让两个插件同时注入同一类状态，否则模型容易把临时状态当长期事实。",
  },
  visibility: {
    purpose: "控制私聊、群聊、自我时间线之间的默认可见边界。",
    tune: "跨窗口共享优先用权限拓扑配置对象级规则；全局开关只适合明确要整体放宽时使用。",
    avoid: "不要用全局共享解决单个群或单个人的问题。",
  },
  memory_tools: {
    purpose: "允许模型主动回忆、写入长期记忆或整理 Bot 自己的陪伴笔记。",
    tune: "需要模型自主记录时开启记住工具；担心误写时先只开回忆工具并观察日志。",
    avoid: "主动记忆工具不应替代阶段性总结，二者用途不同。",
  },
  knowledge_graph: {
    purpose: "从阶段性记忆中建立人物、话题和事实关联，用于图谱展示和检索扩展。",
    tune: "搜索人物/话题时漏召回可开启图谱一跳扩展；召回过宽时降低扩展上限。",
    avoid: "图谱扩展不会绕过权限，不要把它当权限共享开关。",
  },
  livingmemory_migration: {
    purpose: "控制 LivingMemory 旧库导入路径和单次导入上限。",
    tune: "迁移前先预览；旧库很大时分批导入并观察跳过原因。",
    avoid: "不要直接复制旧 SQLite 覆盖当前数据库。",
  },
  maintenance: {
    purpose: "控制备份、原始事件保留和长期旧记忆自然衰减。",
    tune: "数据库增长快时调整原始事件保留；旧碎片太多时开启自然衰减并设置合理阈值。",
    avoid: "自然衰减会归档旧碎片，首次开启前建议备份。",
  },
  appearance: {
    purpose: "控制拓展页主题显示。",
    tune: "只影响管理页外观，不影响记忆行为。",
    avoid: "外观配置不会改变召回、注入或权限逻辑。",
  },
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
  selectedPersonalAlbumIndex: "",
  selectedSubjectiveMemoryIndex: "",
  personalViewport: "schedule",
  personalViewportSwitching: false,
  secondaryNavSwitching: false,
  animatePersonalViewportRail: false,
  personalSnapshot: null,
  personalData: null,
  animatePersonalDateRail: false,
  pendingPersonalFilmReveal: false,
  personalEntranceRevealRequested: false,
  personalAlignTimer: 0,
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

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function percentLabel(value) {
  return `${Math.round(Math.max(0, Math.min(1, finiteNumber(value))) * 100)}%`;
}

function mentionPolicyLabel(policy) {
  if (policy === "direct") return "可直接提及";
  if (policy === "soft_echo") return "轻触回声";
  if (policy === "tone_only") return "只作语气";
  if (policy === "avoid_unless_asked") return "被问再说";
  return policy ? String(policy) : "未评估";
}

function mentionPolicyTone(policy) {
  if (policy === "direct") return "teal";
  if (policy === "soft_echo") return "blue";
  if (policy === "tone_only") return "gold";
  if (policy === "avoid_unless_asked") return "red";
  return "violet";
}

function dimensionLabel(name) {
  const labels = {
    persona_importance: "拟人权重",
    relationship: "关系",
    relationship_weight: "关系",
    emotional: "情绪",
    emotional_weight: "情绪",
    promise: "承诺",
    promise_weight: "承诺",
    open_loop: "未完成",
    open_loop_weight: "未完成",
    creative: "创作",
    creative_weight: "创作",
    preference: "偏好",
    preference_weight: "偏好",
    self_continuity: "自我连续",
    self_continuity_weight: "自我连续",
    freshness_weight: "新鲜感",
    scar_weight: "伤痕感",
    emotional_debt_weight: "情感债务",
    intimacy: "亲密信任",
    intimacy_weight: "亲密信任",
    vulnerability: "脆弱时刻",
    vulnerability_weight: "脆弱时刻",
  };
  return labels[name] || name;
}

function decayModeLabel(mode) {
  const labels = {
    normal: "普通衰减",
    slow_decay: "慢衰减",
    no_decay: "不衰减",
    scar_slow_decay: "伤痕慢衰减",
    creative_milestone: "创作节点",
    ephemeral: "短期淡化",
  };
  return labels[mode] || mode;
}

function reactionLabel(reaction) {
  const labels = {
    accepted: "接受",
    comforted: "被安慰到",
    touched: "感动",
    nostalgic: "怀念",
    awkward: "尴尬",
    denied: "否认",
    corrected: "纠正",
  };
  return labels[reaction] || reaction;
}

function personaWeights(memory) {
  const source = memory.persona_weights || memory.metadata || {};
  const keys = [
    "persona_importance",
    "relationship_weight",
    "emotional_weight",
    "promise_weight",
    "open_loop_weight",
    "creative_weight",
    "preference_weight",
    "self_continuity_weight",
    "freshness_weight",
    "scar_weight",
    "emotional_debt_weight",
    "intimacy_weight",
    "vulnerability_weight",
  ];
  return keys
    .map((key) => ({ key, value: finiteNumber(source[key], NaN) }))
    .filter((item) => Number.isFinite(item.value) && item.value > 0.01);
}

function memorySignalBadges(memory, max = 4) {
  const metadata = memory.metadata || {};
  const policy = memory.mention_policy || metadata.mention_policy || "";
  const mentionability = memory.mentionability_score ?? metadata.mentionability_score;
  const weights = personaWeights(memory)
    .filter((item) => item.key !== "persona_importance" && item.value >= 0.35)
    .sort((a, b) => b.value - a.value)
    .slice(0, Math.max(0, max - (policy ? 1 : 0)));
  const badges = [];
  if (policy) {
    const score = mentionability !== undefined && mentionability !== null ? ` ${percentLabel(mentionability)}` : "";
    badges.push(`<span class="badge ${escapeHtml(mentionPolicyTone(policy))}">${escapeHtml(mentionPolicyLabel(policy) + score)}</span>`);
  }
  weights.forEach((item) => {
    badges.push(`<span class="badge violet">${escapeHtml(`${dimensionLabel(item.key)} ${percentLabel(item.value)}`)}</span>`);
  });
  return badges.join("");
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

function bucketByWindow(scope, id) {
  return state.buckets.find((bucket) => bucket.scope === scope && bucket.target_id === id);
}

function windowIdentifierLabel(scope, id) {
  if (!id) return scope === "group" ? "群号未知" : "QQ 未知";
  return scope === "group" ? `群号 ${id}` : `QQ ${id}`;
}

function stripLabeledPrefix(value) {
  return String(value ?? "")
    .replace(/\b(?:Group\s*ID|Group\s*Name|Name|User\s*ID|User\s*Name|QQ)\s*[:：]\s*/gi, "")
    .trim();
}

function cleanWindowDisplayName(value) {
  return stripLabeledPrefix(value)
    .replace(/\s+(?:Avatar|Owner\s*ID|Admin\s*IDs?|Member\s*Count|Max\s*Member\s*Count|Description)\s*[:：].*$/i, "")
    .trim();
}

function splitWindowBucketTitle(bucket = {}) {
  const scope = bucket.scope || "";
  const targetId = compact(bucket.target_id || bucket.group_id, "");
  const rawLabel = cleanWindowDisplayName(bucket.label || "");
  const rawSublabel = cleanWindowDisplayName(bucket.sublabel || "");
  const escapedId = targetId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const nameFromLabel = escapedId
    ? rawLabel.replace(new RegExp(`\\b${escapedId}\\b`, "g"), "").replace(/\s+/g, " ").trim()
    : rawLabel;
  const explicitName = cleanWindowDisplayName(bucket.target_name || bucket.display_name || "");
  const inferredName = cleanWindowDisplayName(nameFromLabel || "");
  const genericNames = new Set(["群聊", "私聊", "用户", "好友"]);
  const name = explicitName || (genericNames.has(inferredName) ? "" : inferredName);
  if (scope === "group") {
    return {
      primary: targetId ? `群号 ${targetId}` : "群号未知",
      secondary: name && name !== targetId ? name : (rawSublabel && rawSublabel !== targetId ? rawSublabel : "未记录群名"),
    };
  }
  if (scope === "private") {
    return {
      primary: targetId ? `QQ ${targetId}` : "QQ 未知",
      secondary: name && name !== targetId ? name : (rawSublabel && rawSublabel !== targetId ? rawSublabel : "未记录昵称"),
    };
  }
  return { primary: rawLabel || bucket.label || "未命名", secondary: rawSublabel || "" };
}

function windowDisplayLabel(scope, id, name = "") {
  const displayName = compact(name, "");
  if (displayName && displayName !== id) return displayName;
  return scope === "group" ? `群聊 ${id || "未知群聊"}` : `私聊 ${id || "未知用户"}`;
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
  if (view === "archive" && active === "repair") {
    state.secondaryNav[view] = "maintenance";
    return "maintenance";
  }
  if (view === "archive" && CONFIG_ADVANCED_FALLBACKS[active]) {
    state.secondaryNav[view] = CONFIG_ADVANCED_FALLBACKS[active];
    return state.secondaryNav[view];
  }
  if (items.some((item) => item.id === active)) return active;
  state.secondaryNav[view] = items[0].id;
  return items[0].id;
}

function activeSecondaryItem(view = state.activeView) {
  const active = activeSecondaryNav(view);
  return secondaryNavItems(view).find((item) => item.id === active) || null;
}

function secondaryNavRenderItems(view = state.activeView) {
  const items = secondaryNavItems(view);
  const active = activeSecondaryNav(view);
  return items.map((item, index) => ({
    ...item,
    renderKey: `${item.id}-${index}`,
    isActiveLoopItem: item.id === active,
  }));
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
  if (railTitle) railTitle.textContent = view === "archive" ? "配置列表" : "二级导航";
  if (clearButton) clearButton.textContent = view === "archive" ? "回到顶部" : "默认";
  const renderItems = secondaryNavRenderItems(view);
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
  const prevActive = state.secondaryNav[view];
  if (prevActive === id || state.secondaryNavSwitching) return;
  state.secondaryNav[view] = id;
  try {
    state.secondaryNavSwitching = true;
    const list = $("#bucketList");
    if (list) {
      list.querySelectorAll(".secondary-nav-item").forEach((el) => {
        const isActive = el.dataset.secondaryNav === id;
        el.classList.toggle("is-active", isActive);
        el.setAttribute("aria-current", isActive ? "true" : "false");
      });
      const activeItem = activeSecondaryItem(view);
      $("#activeTarget").textContent = activeItem ? `${VIEWS[view]?.title || "二级页"} · ${activeItem.label}` : (VIEWS[view]?.title || "二级页");
    }
    moveSecondaryNavToStandard(false);
    clearDetail();
    await loadActiveView();
    scrollActiveWorkspaceToTop({ immediate: true });
  } finally {
    state.secondaryNavSwitching = false;
  }
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

function scrollActiveWorkspaceToTop(options = {}) {
  const behavior = options.immediate || prefersReducedMotion() ? "auto" : "smooth";
  const activeView = document.querySelector(`#view-${state.activeView}`);
  const candidates = [
    activeView?.querySelector(".archive-grid"),
    activeView?.querySelector(".config-panel-stack"),
    activeView?.querySelector(".page-panel-stack"),
    activeView?.querySelector(".row-list"),
    activeView?.querySelector(".track-strip"),
    activeView,
    document.querySelector(".workspace-main"),
  ].filter(Boolean);
  const seen = new Set();
  candidates.forEach((element) => {
    if (seen.has(element)) return;
    seen.add(element);
    if (typeof element.scrollTo === "function") {
      element.scrollTo({ top: 0, left: 0, behavior });
    }
  });
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
    const name = cleanWindowDisplayName(item.target_name || item.display_name || "");
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
  const windowTitle = isWindowBucket(bucket) ? splitWindowBucketTitle(bucket) : null;
  const title = windowTitle ? `
      <span class="bucket-title-lines">
        <b>${escapeHtml(windowTitle.primary)}</b>
        <em>${escapeHtml(windowTitle.secondary)}</em>
      </span>
    ` : `<b>${escapeHtml(bucket.label)}</b>`;
  return `
    <article class="bucket${active}${windowTitle ? " bucket-window-card" : ""}" data-bucket-id="${escapeHtml(bucket.id)}" role="button" tabindex="0" aria-current="${bucket.id === state.activeBucketId ? "true" : "false"}">
      ${title}
      ${windowTitle ? "" : `<small>${escapeHtml(bucket.sublabel || "")}</small>`}
      <div class="badges">
        <span class="badge blue">${escapeHtml(bucket.memory_count || 0)} 条</span>
      </div>
    </article>
  `;
}

function scopedRailConfig(scope) {
  if (scope === "group") {
    return { title: "群聊列表", clear: "全部群聊", label: "全部群聊", sublabel: "不限定群聊", badge: "群聊" };
  }
  return { title: "私聊用户", clear: "全部私聊", label: "全部私聊", sublabel: "不限定用户", badge: "私聊" };
}

function bindBucketListInteractions() {
  $$("#bucketList [data-bucket-id]").forEach((item) => {
    item.addEventListener("click", (event) => {
      selectBucket(item.dataset.bucketId);
    });
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectBucket(item.dataset.bucketId);
      }
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

function renderScopedModeControls(view = state.activeView) {
  const scope = scopedViewScope(view);
  if (!scope) return;
  const title = view === "film" ? $("#groupMemoryTitle") : $("#privateMemoryTitle");
  const hint = view === "film" ? $("#groupMemoryHint") : $("#privateMemoryHint");
  if (title) title.textContent = `${windowKindLabel(scope)}记忆`;
  if (hint) hint.textContent = VIEWS[view]?.hint || "";
  updateScopedClearButton(view);
}

function updateScopedClearButton(view = state.activeView) {
  const button = view === "film" ? $("#clearCurrentGroupMemoryBtn") : view === "maintain" ? $("#clearCurrentPrivateMemoryBtn") : null;
  const bucket = activeBucket();
  const scope = scopedViewScope(view);
  const canClear = Boolean(bucket && bucket.id !== "all" && bucket.scope === scope && bucket.target_id);
  if (button) {
    button.disabled = !canClear;
    button.title = canClear ? `清空 ${bucket.label} 的记忆` : `请先选择具体${scope === "group" ? "群聊" : "私聊用户"}`;
  }
  if (view === "film") {
    const memberInput = $("#clearGroupMemberUserId");
    const memberButton = $("#clearGroupMemberMemoryBtn");
    if (memberInput) {
      memberInput.disabled = !canClear;
      memberInput.placeholder = canClear ? "群成员 QQ" : "先选择具体群聊";
    }
    if (memberButton) {
      memberButton.disabled = !canClear;
      memberButton.title = canClear ? `清空 ${bucket.label} 中某个成员的记忆` : "请先选择具体群聊";
    }
  }
}

function renderScopedBucketRail(scope) {
  const rail = document.querySelector(".object-rail");
  rail?.classList.remove("is-secondary-nav", "is-looped-secondary-nav");
  rail?.classList.add("is-scoped-rail");
  $("#app")?.style.removeProperty("--secondary-nav-shift");
  renderScopedModeControls();
  const config = scopedRailConfig(scope);
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
  updateScopedClearButton();
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
  // Event delegation: single handler for all bucket cards
  if (objectCards) {
    objectCards.onclick = (event) => {
      const card = event.target.closest("[data-bucket-id]");
      if (card && objectCards.contains(card)) {
        selectBucket(card.dataset.bucketId);
      }
    };
    objectCards.onkeydown = (event) => {
      const card = event.target.closest("[data-bucket-id]");
      if (card && objectCards.contains(card) && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        selectBucket(card.dataset.bucketId);
      }
    };
  }
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
  const keepReelMotion = state.animatePersonalViewportRail && !prefersReducedMotion();
  if (app && list && !animate && !keepReelMotion) {
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
  const changed = nextDate && nextDate !== state.selectedPersonalDate;
  if (!changed) return;
  if (changed && state.personalViewport !== "album") {
    await retractScheduleFilmBeforeDateMove();
  }
  state.selectedPersonalDate = nextDate;
  state.selectedScheduleIndex = "";
  state.selectedPersonalAlbumIndex = "";
  state.selectedSubjectiveMemoryIndex = "";
  state.animatePersonalDateRail = true;
  if (state.personalViewport === "album" && changed) {
    await switchPersonalAlbumDate();
    resetRailCoverflow();
    return;
  }
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
      await loadScopedMemories("#groupMemoryList", "group", "正在读取群聊记忆...", "还没有群聊范围内的记忆。");
    } else if (state.activeView === "microscope") {
      applyMicroscopeView();
    } else if (state.activeView === "relations") {
      await loadUserMemory();
    } else if (state.activeView === "review") {
      await loadPersonalMemory();
    } else if (state.activeView === "maintain") {
      await loadScopedMemories("#privateMemoryList", "private", "正在读取私聊记忆...", "还没有私聊范围内的记忆。");
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
          ${memorySignalBadges(memory, 3)}
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

const MEMORY_RENDER_BATCH = 20;

function renderMemoryList(selector, memories, emptyText) {
  const target = $(selector);
  if (!target) return;
  target.className = "row-list";
  if (!memories.length) {
    target.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
    return;
  }
  // Progressive rendering: render first batch, then load more on scroll
  let renderedCount = 0;
  target.innerHTML = "";
  // Event delegation: single click listener on container
  target.onclick = (event) => {
    const row = event.target.closest("[data-memory-id]");
    if (row && target.contains(row)) {
      showMemory(row.dataset.memoryId);
    }
  };

  const sentinel = document.createElement("div");
  sentinel.className = "progressive-sentinel";
  sentinel.style.minHeight = "1px";

  function renderBatch() {
    const end = Math.min(renderedCount + MEMORY_RENDER_BATCH, memories.length);
    const html = memories.slice(renderedCount, end).map(memoryRow).join("");
    if (renderedCount === 0) {
      target.innerHTML = html;
    } else {
      target.insertAdjacentHTML("beforeend", html);
    }
    renderedCount = end;
    // Add or remove sentinel
    if (renderedCount < memories.length) {
      if (!target.contains(sentinel)) {
        target.appendChild(sentinel);
      }
    } else if (target.contains(sentinel)) {
      sentinel.remove();
    }
  }

  renderBatch();

  // Observe sentinel to load more when scrolled into view
  if (renderedCount < memories.length) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && renderedCount < memories.length) {
          renderBatch();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(sentinel);
    // Store observer for cleanup
    target._progressiveObserver = observer;
  } else if (target._progressiveObserver) {
    target._progressiveObserver.disconnect();
    target._progressiveObserver = null;
  }
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

function hasMemoryType(memory, types) {
  return types.includes(memory.memory_type);
}

function isUserMemory(memory) {
  return hasMemoryType(memory, ["user_profile", "user_preference", "explicit_memory", "relationship_claim"]);
}

function isPersonalMemory(memory) {
  return memory.visibility === "bot_self"
    && (
      hasMemoryType(memory, [
        "schedule_fragment",
        "persona_life",
        "self_action",
        "proactive_message",
        "search_action",
        "creative_work",
        "image_action",
        "qzone_action",
        "reading_memory",
      ])
      || memory.source_plugin === "private_companion"
      || (memory.tags || []).includes("schedule")
      || (memory.tags || []).includes("persona_life")
      || (memory.tags || []).includes("qzone")
      || (memory.tags || []).includes("qzone_publish")
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
  } else if (section === "persona") {
    target.innerHTML = `<div id="personaStatePanel" class="persona-state-panel"></div>`;
    await loadPersonaState();
  } else {
    const results = await Promise.allSettled([
      apiGet(`/graph?${params.toString()}`),
      apiGet(`/relations?${params.toString()}`),
      apiGet(`/threads?${new URLSearchParams({ ...Object.fromEntries(params), status: "all" }).toString()}`),
      apiGet(`/timeline?${params.toString()}`),
      apiGet(`/logs?${params.toString()}`),
    ]);
    const settled = (idx) => results[idx].status === "fulfilled" ? (results[idx].value?.items || []) : [];
    const failures = results.filter(r => r.status === "rejected");
    if (failures.length === results.length) {
      throw results[0].reason || new Error("所有知识图谱 API 请求失败");
    }
    target.innerHTML = renderKnowledgeOverview({
      graph: settled(0),
      relations: settled(1),
      threads: settled(2),
      timeline: settled(3),
      logs: settled(4),
    });
    if (failures.length > 0) {
      const failedNames = ["图谱边", "身份关系", "跨窗口线程", "时间线", "注入日志"].filter((_, i) => results[i].status === "rejected");
      showToast(`${failedNames.join("、")}加载失败，已显示可用数据`, "error");
    }
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

function renderKnowledgeOverview({ graph = [], relations = [], threads = [], timeline = [], logs = [] } = {}) {
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
    ${renderContextLogs(logs)}
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

function providerStateLabel(current, hasProvider, enabled = true) {
  if (!enabled) return "未启用";
  if (current) return current;
  return hasProvider ? "自动探测" : "未检测到";
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

function blockedReasonLabel(reason) {
  const text = String(reason || "");
  if (text.includes("private_pair_not_current_private")) return "私聊隔离";
  if (text.includes("other_group_public")) return "其他群聊";
  if (text.includes("prefiltered_out_of_search_range")) return "范围外";
  if (text.includes("companion_current_state_overlap")) return "陪伴状态重叠";
  if (text.includes("mention_policy")) return "提及边界";
  if (text.includes("current_state_relevance_guard")) return "当前状态保护";
  if (text.includes("not_visible") || text.includes("visibility")) return "可见性";
  if (text.includes("duplicate") || text.includes("redundant")) return "重复折叠";
  return text.split(":")[0].replaceAll("_", " ") || "过滤";
}

function blockedReasonBadges(blocked = []) {
  const counts = new Map();
  blocked.forEach((item) => {
    const label = blockedReasonLabel(item.reason || item);
    counts.set(label, (counts.get(label) || 0) + 1);
  });
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([label, count]) => `<span class="badge ${count > 20 ? "red" : "teal"}">${escapeHtml(label)} ${escapeHtml(count)}</span>`)
    .join("");
}

function renderSelectedMemoryChips(memories = [], limit = 4) {
  return memories.slice(0, limit).map((memory) => {
    const title = compact(memory.canonical_summary || memory.content, memory.id);
    const policy = memory.mention_policy || "";
    return `
      <span class="memory-chip" title="${escapeHtml(title)}">
        ${escapeHtml(compact(memory.memory_type, "memory"))}
        ${policy ? `<small>${escapeHtml(mentionPolicyLabel(policy))}</small>` : ""}
      </span>
    `;
  }).join("");
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
          <article class="row-item memory-frame" data-raw="${escapeHtml(JSON.stringify(item))}" data-detail-title="注入记录详情">
            <div class="memory-frame-time">
              <b>${escapeHtml(formatTime(item.created_at))}</b>
              <span>${escapeHtml(item.scope || "unknown")}</span>
            </div>
            <div class="memory-frame-main">
              <div class="memory-frame-text">
                <span class="item-title">${escapeHtml(item.query || "未记录查询文本")}</span>
                <div class="memory-chip-row">${renderSelectedMemoryChips(item.selected_memories || [])}</div>
              </div>
              <div class="badges">
                <span class="badge blue">选中 ${escapeHtml((item.selected_memory_ids || []).length)} 条</span>
                <span class="badge teal">过滤 ${escapeHtml((item.blocked_reasons || []).length)} 条</span>
                <span class="badge gold">${escapeHtml(shortId(item.session_id || "-"))}</span>
                ${blockedReasonBadges(item.blocked_reasons || [])}
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
  const data = await fetchPersonalMemoryData();
  updatePersonalMemoryAvailability(Boolean(data.available));
  if (!data.available) {
    target.innerHTML = renderPersonalMemoryUnavailable(data.reason || "未检测到已加载的主动陪伴插件");
    return;
  }
  state.selectedPersonalDate = data.selected_date || state.selectedPersonalDate || "";
  state.personalSnapshot = data.snapshot || {};
  state.personalData = data;
  if (shouldAnimateEntrance) state.animatePersonalDateRail = true;
  renderPersonalDateRail(data.dates || [], state.selectedPersonalDate);
  target.innerHTML = renderPersonalMemoryWorkspace(data.snapshot || {}, data);
  bindPersonalMemoryWorkspace(target, data.snapshot || {}, data);
  hydratePersonalAlbumImages(target);
}

function personalMemoryQueryParams() {
  const query = $("#globalSearch")?.value.trim() || "";
  const params = new URLSearchParams({ limit: "80" });
  if (query) params.set("q", query);
  if (state.selectedPersonalDate) params.set("date", state.selectedPersonalDate);
  return params;
}

async function fetchPersonalMemoryData() {
  return apiGet(`/companion/personal-memory?${personalMemoryQueryParams().toString()}`);
}

function bindPersonalMemoryWorkspace(target, snapshot, data) {
  target.querySelectorAll("[data-personal-viewport]").forEach((button) => {
    button.addEventListener("click", async () => {
      const next = button.dataset.personalViewport || "schedule";
      if (next === state.personalViewport) return;
      await switchPersonalViewport(next, target, state.personalSnapshot || snapshot, state.personalData || data);
    });
  });

  target.querySelectorAll("[data-memory-id]").forEach((row) => {
    row.addEventListener("click", () => showMemory(row.dataset.memoryId));
  });
  bindPersonalAlbumCards(target, snapshot, data);
  target.querySelectorAll("[data-subjective-index]").forEach((card) => {
    const selectSubjective = () => {
      state.selectedSubjectiveMemoryIndex = card.dataset.subjectiveIndex || "";
      target.querySelectorAll("[data-subjective-index]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.subjectiveIndex === state.selectedSubjectiveMemoryIndex);
      });
      showPersonalSubjectiveDetail(snapshot, data, { animate: true });
    };
    card.addEventListener("click", selectSubjective);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectSubjective();
      }
    });
  });
  if (state.personalViewport !== "schedule") {
    removeRailMountedScheduleFilm();
    state.pendingPersonalFilmReveal = false;
    resetPersonalFilmLayout();
    if (state.personalViewport === "album") {
      showPersonalAlbumDetail(snapshot, data);
      hydratePersonalAlbumImages(target);
    }
    if (state.personalViewport === "subjective") showPersonalSubjectiveDetail(snapshot, data);
    if (state.personalViewport === "actions") showPersonalActionsDetail(data);
    return;
  }
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

function bindPersonalAlbumCards(target, snapshot, data) {
  target.querySelectorAll("[data-album-index]").forEach((card) => {
    const selectAlbum = () => {
      state.selectedPersonalAlbumIndex = card.dataset.albumIndex || "";
      target.querySelectorAll("[data-album-index]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.albumIndex === state.selectedPersonalAlbumIndex);
      });
      showPersonalAlbumDetail(snapshot, data, { animate: true });
    };
    card.addEventListener("click", selectAlbum);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectAlbum();
      }
    });
  });
}

async function switchPersonalAlbumDate() {
  const target = $("#personalMemoryList");
  const viewport = target?.querySelector(".personal-viewport[data-personal-viewport-panel='album']");
  if (!target || !viewport) {
    await loadPersonalMemory();
    return;
  }
  const currentPanel = viewport.querySelector(".companion-album");
  if (currentPanel && !prefersReducedMotion()) {
    currentPanel.classList.add("is-album-date-leaving");
    await waitForMotion(180);
  }
  const data = await fetchPersonalMemoryData();
  updatePersonalMemoryAvailability(Boolean(data.available));
  if (!data.available) {
    target.innerHTML = renderPersonalMemoryUnavailable(data.reason || "未检测到已加载的主动陪伴插件");
    return;
  }
  state.selectedPersonalDate = data.selected_date || state.selectedPersonalDate || "";
  state.selectedPersonalAlbumIndex = "";
  state.personalSnapshot = data.snapshot || {};
  state.personalData = data;
  state.animatePersonalDateRail = true;
  renderPersonalDateRail(data.dates || [], state.selectedPersonalDate);
  viewport.innerHTML = renderPersonalViewportPanel("album", data.snapshot || {}, data);
  const nextPanel = viewport.querySelector(".companion-album");
  nextPanel?.classList.add("is-album-date-entering");
  bindPersonalAlbumCards(target, data.snapshot || {}, data);
  showPersonalAlbumDetail(data.snapshot || {}, data, { animate: true });
  hydratePersonalAlbumImages(viewport);
  requestAnimationFrame(() => nextPanel?.classList.remove("is-album-date-entering"));
}

async function switchPersonalViewport(next, target, snapshot, data) {
  if (state.personalViewportSwitching) return;
  state.personalViewportSwitching = true;
  const rail = document.querySelector(".object-rail");
  const render = () => {
    try {
      state.animatePersonalViewportRail = true;
      renderPersonalDateRail(state.personalDates, state.selectedPersonalDate);
    } finally {
      state.animatePersonalViewportRail = false;
    }
    target.innerHTML = renderPersonalMemoryWorkspace(snapshot, data);
    bindPersonalMemoryWorkspace(target, snapshot, data);
  };
  try {
    await retractScheduleFilmBeforeDateMove();
    removeRailMountedScheduleFilm();
    if (!prefersReducedMotion()) {
      rail?.classList.add("is-reel-rolling-out");
      await waitForMotion(220);
      rail?.classList.remove("is-reel-rolling-out");
    }
    state.personalViewport = next;
    state.pendingPersonalFilmReveal = next === "schedule" && !prefersReducedMotion();
    resetPersonalFilmLayout();
    render();
    if (!prefersReducedMotion()) {
      rail?.classList.add("is-reel-rolling-in");
      await waitForMotion(540);
      rail?.classList.remove("is-reel-rolling-in");
    }
    if (next === "schedule") requestAnimationFrame(alignPersonalScheduleToReel);
  } finally {
    rail?.classList.remove("is-reel-rolling-out", "is-reel-rolling-in");
    state.personalViewportSwitching = false;
  }
}

function resetPersonalFilmLayout() {
  const app = $("#app");
  if (!app) return;
  app.style.removeProperty("--personal-film-lift");
  app.style.removeProperty("--personal-film-shift");
  app.style.removeProperty("--personal-detail-offset");
  app.style.removeProperty("--personal-main-height");
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
      <p>这里用于联动主动陪伴插件，展示 Bot 自身的每日生活日程、相册、主观记忆、日程细化片段和由陪伴插件写入的个人记忆。</p>
    </div>
  `;
}

function renderPersonalMemoryWorkspace(snapshot, status) {
  const active = personalViewport();
  return `
    <section class="personal-memory-workspace">
      ${renderPersonalViewportSwitch(active)}
      <div class="personal-viewport" data-personal-viewport-panel="${escapeHtml(active)}">
        ${renderPersonalViewportPanel(active, snapshot, status)}
      </div>
    </section>
  `;
}

function personalViewport() {
  const views = ["schedule", "album", "subjective", "actions"];
  if (!views.includes(state.personalViewport)) state.personalViewport = "schedule";
  return state.personalViewport;
}

function renderPersonalViewportSwitch(active) {
  const tabs = [
    { id: "schedule", label: "日程" },
    { id: "album", label: "相册" },
    { id: "subjective", label: "主观记忆" },
    { id: "actions", label: "行动" },
  ];
  return `
    <div class="personal-view-switch" role="tablist" aria-label="个人记忆视窗">
      ${tabs.map((tab) => `
        <button class="personal-view-tab${tab.id === active ? " is-active" : ""}" type="button" role="tab" aria-selected="${tab.id === active ? "true" : "false"}" data-personal-viewport="${escapeHtml(tab.id)}">
          ${escapeHtml(tab.label)}
        </button>
      `).join("")}
    </div>
  `;
}

function renderPersonalViewportPanel(active, snapshot, status) {
  if (active === "album") return renderCompanionAlbumPanel(snapshot, status);
  if (active === "subjective") return renderSubjectiveMemoryPanel(snapshot, status);
  if (active === "actions") return renderPersonalActionsPanel(status);
  return renderCompanionSchedulePanel(snapshot, status);
}

function renderPersonalActionsPanel(status) {
  const actions = Array.isArray(status.actions) ? status.actions : [];
  const date = status.selected_date || "";
  return `
    <section class="personal-zone personal-actions-panel">
      <div class="personal-zone-head">
        <h4>行动</h4>
        <span>${escapeHtml(date || "全部日期")} · ${escapeHtml(actions.length)} 条</span>
      </div>
      ${actions.length ? `
        <div class="personal-action-list">
          ${actions.map((item) => renderPersonalActionCard(item)).join("")}
        </div>
      ` : `
        <div class="album-empty">
          <b>这一天还没有行动记忆</b>
          <span>发说说、搜索、创作、生图、阅读和主动消息等 Bot 行动会出现在这里。</span>
        </div>
      `}
    </section>
  `;
}

function renderPersonalActionCard(memory) {
  const metadata = memory.metadata || {};
  const tags = Array.isArray(memory.tags) ? memory.tags.filter(Boolean).slice(0, 5) : [];
  const metaParts = [
    metadata.action_label || personalActionTypeLabel(memory.memory_type),
    formatTime(memory.occurred_at || memory.created_at),
    metadata.tid ? `tid ${metadata.tid}` : "",
    Number(metadata.image_count || 0) > 0 ? `${metadata.image_count} 张图` : "",
  ].filter(Boolean);
  return `
    <article class="row-item memory-frame personal-action-card" data-memory-id="${escapeHtml(memory.id)}">
      <div class="memory-frame-time">
        <b>${escapeHtml(metaParts[0] || "行动")}</b>
        <span>${escapeHtml(metaParts.slice(1).join(" · ") || shortId(memory.id))}</span>
      </div>
      <div class="memory-frame-main">
        <div class="memory-frame-text">
          <span class="item-title">${escapeHtml(compact(memory.content, "(空内容)"))}</span>
          ${metadata.text && metadata.text !== memory.content ? `<p class="memory-preview">${escapeHtml(metadata.text)}</p>` : ""}
        </div>
        <div class="badges">
          <span class="badge teal">${escapeHtml(memory.memory_type || "action")}</span>
          <span class="badge blue">${escapeHtml(memory.reality_level || "bot_action")}</span>
          ${tags.map((tag) => `<span class="badge gold">${escapeHtml(tag)}</span>`).join("")}
        </div>
      </div>
    </article>
  `;
}

function personalActionTypeLabel(type) {
  const labels = {
    self_action: "自我行动",
    proactive_message: "主动消息",
    search_action: "搜索",
    creative_work: "创作",
    image_action: "生图",
    qzone_action: "QQ 空间",
    reading_memory: "阅读",
    persona_life: "生活片段",
  };
  return labels[type] || type || "行动";
}

function renderCompanionAlbumPanel(snapshot, status) {
  const album = Array.isArray(snapshot.album) ? snapshot.album : [];
  const selected = activeAlbumIndex(album);
  const kindLabels = album.map((item) => item.kind || "");
  const hasOutfit = kindLabels.some((k) => k === "daily_outfit");
  const hasLife = kindLabels.some((k) => k === "life_photo");
  const subtitleParts = [status.selected_date || snapshot.plan?.date || "-"];
  if (hasOutfit) subtitleParts.push("穿搭");
  if (hasLife) subtitleParts.push("生活分享");
  if (!hasOutfit && !hasLife) subtitleParts.push("照片");
  return `
    <section class="personal-zone companion-album">
      <div class="personal-zone-head">
        <h4>相册</h4>
        <span>${escapeHtml(subtitleParts.join(" · "))}</span>
      </div>
      ${album.length ? `
        <div class="album-strip">
          ${album.map((item, index) => renderAlbumCard(item, index, String(index) === selected)).join("")}
        </div>
      ` : `
        <div class="album-empty">
          <b>这一天还没有照片</b>
          <span>生成穿搭图或生活分享图后会出现在这里。</span>
        </div>
      `}
    </section>
  `;
}

function renderAlbumCard(item, index = 0, active = false) {
  const title = item.title || "照片";
  const meta = [item.generated_at, item.backend].filter(Boolean).join(" · ");
  const image = item.exists && (item.image_data_url || item.url)
    ? albumImageTag(item, title)
    : `<div class="album-missing">${escapeHtml(item.error || "图片文件不可用")}</div>`;
  return `
    <article class="album-card${active ? " is-active" : ""}" style="--album-i:${escapeHtml(index)}" data-album-index="${escapeHtml(index)}" role="button" tabindex="0">
      <div class="album-image">${image}</div>
      <div class="album-caption">
        <b>${escapeHtml(title)}</b>
        ${meta ? `<span>${escapeHtml(meta)}</span>` : ""}
        ${item.note ? `<small>${escapeHtml(item.note)}</small>` : ""}
      </div>
    </article>
  `;
}

function albumImageTag(item, title) {
  const source = item?.image_data_url || item?.url || "";
  if (!source) return `<div class="album-missing">图片文件不可用</div>`;
  return `<img src="${TRANSPARENT_IMAGE}" data-album-image-src="${escapeHtml(source)}" alt="${escapeHtml(title)}" loading="lazy">`;
}

function albumImageDataPath(source) {
  const raw = String(source || "");
  if (!raw || raw.startsWith("data:")) return raw;
  try {
    const url = new URL(raw, window.location.origin);
    if (url.pathname.endsWith("/companion/personal-photo-data")) {
      return `/companion/personal-photo-data${url.search}`;
    }
    if (url.pathname.endsWith("/companion/personal-photo")) {
      return `/companion/personal-photo-data${url.search}`;
    }
  } catch (error) {
    const dataMarker = "/companion/personal-photo-data?";
    const photoMarker = "/companion/personal-photo?";
    const dataIndex = raw.indexOf(dataMarker);
    if (dataIndex >= 0) return `/companion/personal-photo-data?${raw.slice(dataIndex + dataMarker.length)}`;
    const photoIndex = raw.indexOf(photoMarker);
    if (photoIndex >= 0) return `/companion/personal-photo-data?${raw.slice(photoIndex + photoMarker.length)}`;
  }
  return raw;
}

async function hydratePersonalAlbumImages(root = document) {
  const images = [...root.querySelectorAll("img[data-album-image-src]")];
  await Promise.all(images.map(async (img) => {
    if (img.dataset.loaded === "1" || img.dataset.loading === "1") return;
    const source = img.dataset.albumImageSrc || "";
    if (!source) return;
    img.dataset.loading = "1";
    const endpoint = albumImageDataPath(source);
    try {
      if (endpoint.startsWith("data:")) {
        img.src = endpoint;
      } else if (endpoint.startsWith("/companion/personal-photo-data")) {
        const result = await apiGet(endpoint);
        if (!result?.data_url) throw new Error("图片数据为空");
        img.src = result.data_url;
      } else {
        img.src = source;
      }
      img.dataset.loaded = "1";
    } catch (error) {
      img.dataset.loaded = "0";
      const fallback = document.createElement("div");
      fallback.className = "album-missing";
      fallback.textContent = "图片加载失败";
      img.replaceWith(fallback);
    } finally {
      img.dataset.loading = "0";
    }
  }));
}

function activeAlbumIndex(album) {
  if (!album.length) {
    state.selectedPersonalAlbumIndex = "";
    return "";
  }
  const current = String(state.selectedPersonalAlbumIndex || "");
  if (current && album[Number(current)]) return current;
  state.selectedPersonalAlbumIndex = "0";
  return "0";
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

function firstMinute(value) {
  const match = String(value || "").match(/(\d{1,2}):(\d{2})/);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null;
  return hour * 60 + minute;
}

function scheduleWindowForIndex(items, selectedIndex) {
  const index = items.findIndex((candidate, fallback) => scheduleIndex(candidate, fallback) === String(selectedIndex));
  const item = index >= 0 ? items[index] : null;
  const start = firstMinute(item?.time);
  const end = firstMinute(items[index + 1]?.time);
  return { start, end };
}

function detailMatchesSchedule(detail, item, selectedIndex, window = {}) {
  if (!detail || !item || !selectedIndex) return false;
  const index = String(selectedIndex);
  const key = String(detail.key || "");
  const time = String(item.time || "");
  const detailStart = firstMinute(detail.time || key);
  return String(detail.index) === index
    || (
      window.start !== null
      && detailStart !== null
      && detailStart >= window.start
      && (window.end === null || detailStart < window.end)
    )
    || key.includes(`:${index}:`)
    || Boolean(time && (key.includes(`:${time}`) || String(detail.time || "").startsWith(time)));
}

function detailsForSchedule(details, item, selectedIndex, items = []) {
  if (!item || !selectedIndex || !Array.isArray(details)) return [];
  const window = scheduleWindowForIndex(items, selectedIndex);
  const matched = details
    .filter((detail) => detailMatchesSchedule(detail, item, selectedIndex, window))
    .sort((a, b) => (firstMinute(a?.time || a?.key) ?? 99999) - (firstMinute(b?.time || b?.key) ?? 99999));
  if (matched.length) return matched;
  const fallback = details.find((detail) => String(detail.index) === String(selectedIndex))
    || details.find((detail) => String(detail.key || "").includes(`:${selectedIndex}:`))
    || details.find((detail) => item.time && String(detail.key || "").includes(`:${item.time}`));
  return fallback ? [fallback] : [];
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
  const selectedDetails = detailsForSchedule(details, selectedItem, selectedIndex, items);
  const drawer = $("#detailDrawer");
  const render = () => {
    drawer.className = selectedItem ? "detail-drawer is-schedule-detail" : "detail-drawer empty";
    drawer.innerHTML = `<div class="personal-detail-content">${renderSelectedDetail(selectedItem, selectedDetails, items)}</div>`;
  };
  if (options.animate) {
    swapPanelContent(drawer, render);
  } else {
    render();
  }
}

function renderSelectedDetail(item, details, items) {
  if (!item) {
    return `
      <div class="detail-empty">
        <b>选择日程段</b>
        <span>点击上方日程表里的时间段，在这里查看对应细化。</span>
      </div>
    `;
  }
  const selectedDetails = Array.isArray(details) ? details.filter(Boolean) : (details ? [details] : []);
  if (!selectedDetails.length) {
    return `
      <div class="empty-state">这个时间段还没有细化。</div>
    `;
  }
  return `
    <article class="selected-detail">
      ${selectedDetails.length > 1 ? `<span class="detail-count">${escapeHtml(selectedDetails.length)} 条细化</span>` : ""}
      <div class="detail-segment-list">
        ${selectedDetails.map((detail) => renderDetailSegment(detail)).join("")}
      </div>
    </article>
  `;
}

function renderDetailSegment(detail) {
  const detailTime = detail?.time ? detail.time : "";
  return `
    <section class="detail-segment">
      ${detailTime ? `<span class="detail-time">${escapeHtml(detailTime)}</span>` : ""}
      ${detail.summary ? `<b class="detail-summary">${escapeHtml(detail.summary)}</b>` : ""}
      ${renderDetailLines(detail)}
    </section>
  `;
}

function renderSubjectiveMemories(snapshot, options = {}) {
  const memories = Array.isArray(snapshot.subjective_memories) ? snapshot.subjective_memories : [];
  const selected = options.selectable ? activeSubjectiveIndex(memories) : "";
  if (!memories.length) {
    return `
      <article class="subjective-memory empty-subjective">
        <b>主观记忆</b>
        <span>这一天还没有 Bot 日记或主观片段。</span>
      </article>
    `;
  }
  return `
    <section class="subjective-memory">
      <div class="subjective-head">
        <b>主观记忆</b>
        <span>${escapeHtml(memories[0].date || "")}</span>
      </div>
      ${memories.map((item, index) => `
        <article class="subjective-card${options.selectable && String(index) === selected ? " is-active" : ""}"${options.selectable ? ` data-subjective-index="${escapeHtml(index)}" role="button" tabindex="0"` : ""}>
          ${item.summary ? `<b>${escapeHtml(item.summary)}</b>` : ""}
          ${item.body ? `<p>${escapeHtml(item.body)}</p>` : ""}
          ${item.share_seed ? `<small>${escapeHtml(item.share_seed)}</small>` : ""}
          ${renderSubjectiveTags(item.tags)}
          ${renderSubjectiveLines(item)}
        </article>
      `).join("")}
    </section>
  `;
}

function renderSubjectiveMemoryPanel(snapshot, status) {
  const date = status.selected_date || snapshot.plan?.date || "";
  return `
    <section class="personal-zone subjective-memory-panel">
      <div class="personal-zone-head">
        <h4>主观记忆</h4>
        <span>${escapeHtml(date || "-")} · Bot 日记</span>
      </div>
      ${renderSubjectiveMemories(snapshot, { selectable: true })}
    </section>
  `;
}

function activeSubjectiveIndex(memories) {
  if (!memories.length) {
    state.selectedSubjectiveMemoryIndex = "";
    return "";
  }
  const current = String(state.selectedSubjectiveMemoryIndex || "");
  if (current && memories[Number(current)]) return current;
  state.selectedSubjectiveMemoryIndex = "0";
  return "0";
}

function showPersonalAlbumDetail(snapshot, status, options = {}) {
  if (state.activeView !== "review") return;
  const album = Array.isArray(snapshot.album) ? snapshot.album : [];
  const selectedIndex = activeAlbumIndex(album);
  const selected = album[Number(selectedIndex)] || null;
  const drawer = $("#detailDrawer");
  const render = () => {
    drawer.className = selected ? "detail-drawer is-album-detail" : "detail-drawer empty";
    drawer.innerHTML = `<div class="personal-detail-content">${renderAlbumDetail(selected, status)}</div>`;
    requestAnimationFrame(() => hydratePersonalAlbumImages(drawer));
  };
  if (options.animate) {
    swapPanelContent(drawer, render);
  } else {
    render();
  }
}

function renderAlbumDetail(item, status) {
  if (!item) {
    return `
      <div class="detail-empty">
        <b>相册为空</b>
        <span>${escapeHtml(status.selected_date || "这一天")} 还没有照片。</span>
      </div>
    `;
  }
  const title = item.title || "照片";
  const meta = [item.generated_at, item.backend].filter(Boolean).join(" · ");
  const image = item.exists && (item.image_data_url || item.url)
    ? albumImageTag(item, title)
    : `<div class="album-missing">${escapeHtml(item.error || "图片文件不可用")}</div>`;
  return `
    <article class="album-detail">
      <div class="album-detail-image">${image}</div>
      <div class="album-detail-copy">
        <b>${escapeHtml(title)}</b>
        ${meta ? `<span>${escapeHtml(meta)}</span>` : ""}
        ${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}
      </div>
    </article>
  `;
}

function showPersonalSubjectiveDetail(snapshot, status, options = {}) {
  if (state.activeView !== "review") return;
  const memories = Array.isArray(snapshot.subjective_memories) ? snapshot.subjective_memories : [];
  const selectedIndex = activeSubjectiveIndex(memories);
  const selected = memories[Number(selectedIndex)] || null;
  const drawer = $("#detailDrawer");
  const render = () => {
    drawer.className = selected ? "detail-drawer" : "detail-drawer empty";
    drawer.innerHTML = `<div class="personal-detail-content">${renderSubjectiveDetail(selected, status)}</div>`;
  };
  if (options.animate) {
    swapPanelContent(drawer, render);
  } else {
    render();
  }
}

function showPersonalActionsDetail(status) {
  if (state.activeView !== "review") return;
  const actions = Array.isArray(status.actions) ? status.actions : [];
  const drawer = $("#detailDrawer");
  drawer.className = "detail-drawer empty";
  drawer.innerHTML = `
    <div class="detail-empty">
      <b>${actions.length ? "选择一条行动" : "行动记忆为空"}</b>
      <span>${actions.length ? "点击左侧行动卡片查看完整记录、标签和元数据。" : `${status.selected_date || "这一天"} 还没有 Bot 行动记忆。`}</span>
    </div>
  `;
}

function renderSubjectiveDetail(item, status) {
  if (!item) {
    return `
      <div class="detail-empty">
        <b>主观记忆为空</b>
        <span>${escapeHtml(status.selected_date || "这一天")} 还没有 Bot 日记或主观片段。</span>
      </div>
    `;
  }
  return `
    <article class="selected-detail subjective-detail">
      ${item.date ? `<span class="detail-time">${escapeHtml(item.date)}</span>` : ""}
      ${item.summary ? `<b class="detail-summary">${escapeHtml(item.summary)}</b>` : ""}
      ${item.body ? `<p>${escapeHtml(item.body)}</p>` : ""}
      ${item.share_seed ? `<small>${escapeHtml(item.share_seed)}</small>` : ""}
      ${renderSubjectiveTags(item.tags)}
      ${renderSubjectiveLines(item)}
    </article>
  `;
}

function renderSubjectiveTags(tags) {
  if (!Array.isArray(tags) || !tags.length) return "";
  return `<div class="subjective-tags">${tags.slice(0, 6).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>`;
}

function renderSubjectiveLines(item) {
  const lines = [
    ...(item.today_events || []),
    ...(item.proactive_events || []),
    ...(item.long_term_events || []),
  ].slice(0, 5);
  if (!lines.length) return "";
  return `<ul class="detail-lines subjective-lines">${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`;
}

function renderDetailLines(item) {
  const lines = [
    ...(item.today_events || []),
    ...(item.proactive_events || []),
    ...(item.state_variables || []),
  ];
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
            ${memorySignalBadges(item, 4)}
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
  const section = activeSecondaryNav("archive");
  setArchiveSection(section);
  if (section.startsWith("config:")) {
    const module = section.slice("config:".length);
    $("#selfMemoryList").innerHTML = loadingState("正在读取模块配置...");
    const data = await apiGet("/config/schema");
    $("#selfMemoryList").innerHTML = renderSchemaConfigModule(data, module);
    bindSchemaConfigForm($("#selfMemoryList"), data);
    return;
  }
  if (section === "topology") {
    await loadAclTopology();
    return;
  }
  if (section !== "retrieval") return;
  $("#selfMemoryList").innerHTML = loadingState("正在读取检索配置...");
  const config = await apiGet("/context/config");
  $("#selfMemoryList").innerHTML = renderArchiveConfig(config);
  bindRetrievalConfigForm($("#selfMemoryList"));
}

function bindArchiveJumpButtons(root = document) {
  root.querySelectorAll("[data-archive-jump]").forEach((button) => {
    button.addEventListener("click", () => selectSecondaryNav(button.dataset.archiveJump));
  });
}

function setArchiveSection(section) {
  const visibleSection = section.startsWith("config:") ? "retrieval" : section;
  $$("#view-archive [data-archive-section]").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.archiveSection === visibleSection);
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

function renderSchemaConfigModule(data = {}, module = "") {
  const schema = data.schema?.[module];
  const values = data.values?.[module] || {};
  if (!schema?.items) {
    return `<div class="empty-state error-state"><b>配置模块不存在</b><span>${escapeHtml(module || "unknown")}</span></div>`;
  }
  const advancedModule = CONFIG_ADVANCED_MODULES[module] || "";
  const advancedSchema = advancedModule ? data.schema?.[advancedModule] : null;
  const advancedValues = advancedModule ? (data.values?.[advancedModule] || {}) : {};
  const fields = Object.entries(schema.items)
    .map(([key, item]) => renderSchemaConfigField(module, key, item || {}, values[key], data))
    .join("");
  const advancedFields = advancedSchema?.items
    ? Object.entries(advancedSchema.items)
      .map(([key, item]) => renderSchemaConfigField(advancedModule, key, item || {}, advancedValues[key], data))
      .join("")
    : "";
  return `
    <form class="context-form schema-config-form" data-config-module="${escapeHtml(module)}" data-config-advanced-module="${escapeHtml(advancedFields ? advancedModule : "")}" autocomplete="off">
      <section class="context-form-section">
        <div class="context-form-section-head">
          <b>${escapeHtml(schema.description || module)}</b>
          <span>${escapeHtml(schema.hint || "按官方配置 schema 渲染，保存后写入插件配置文件。")}</span>
        </div>
        ${renderConfigInlineGuide(module)}
        ${fields}
      </section>
      ${advancedFields ? `
        <details class="context-advanced">
          <summary>${escapeHtml(advancedSchema.description || "高级参数")}</summary>
          <div class="context-advanced-note">${escapeHtml(advancedSchema.hint || "日常使用可保持默认。")}</div>
          ${advancedFields}
        </details>
      ` : ""}
      <div class="context-form-actions">
        <span>${advancedFields ? "保存当前模块及其折叠高级参数；其他模块不会被改动。" : "只保存当前模块；其他模块不会被改动。"}</span>
        <button type="submit">保存${escapeHtml(schema.description || "配置")}</button>
      </div>
    </form>
  `;
}

function renderConfigInlineGuide(module) {
  const guide = CONFIG_MODULE_GUIDES[module];
  if (!guide) return "";
  return `
    <div class="config-inline-guide">
      <dl>
        <div><dt>作用</dt><dd>${escapeHtml(guide.purpose)}</dd></div>
        <div><dt>什么时候调</dt><dd>${escapeHtml(guide.tune)}</dd></div>
        <div><dt>注意点</dt><dd>${escapeHtml(guide.avoid)}</dd></div>
      </dl>
    </div>
  `;
}

function renderSchemaConfigField(module, key, item = {}, value, data = {}) {
  const type = item.type || "string";
  const label = item.description || key;
  const hint = item.hint || `${module}.${key}`;
  const current = value ?? item.default ?? "";
  let control = "";
  if (type === "bool") {
    control = contextSwitch(key, Boolean(current));
  } else if (type === "int") {
    control = `<input name="${escapeHtml(key)}" type="number" step="1" value="${escapeHtml(current)}" />`;
  } else if (type === "float") {
    control = `<input name="${escapeHtml(key)}" type="number" step="0.01" value="${escapeHtml(current)}" />`;
  } else if (Array.isArray(item.options) && item.options.length) {
    control = `
      <select name="${escapeHtml(key)}">
        ${item.options.map((option) => `<option value="${escapeHtml(option)}"${String(option) === String(current) ? " selected" : ""}>${escapeHtml(option)}</option>`).join("")}
      </select>
    `;
  } else if (item._special === "select_provider") {
    const options = Array.isArray(data.provider_options) ? [...data.provider_options] : [];
    if (current && !options.some((option) => option.id === current)) {
      options.push({ id: current, label: `${current}（当前配置）` });
    }
    control = `
      <div class="provider-inline retrieval-provider-picker">
        <select data-config-provider-select="${escapeHtml(key)}">
          ${options.map((option) => `<option value="${escapeHtml(option.id || "")}"${String(option.id || "") === String(current || "") ? " selected" : ""}>${escapeHtml(option.label || option.id || "不指定")}</option>`).join("")}
        </select>
        <input name="${escapeHtml(key)}" type="text" value="${escapeHtml(current)}" placeholder="留空使用当前会话模型" />
      </div>
    `;
  } else {
    control = `<input name="${escapeHtml(key)}" type="text" value="${escapeHtml(current)}" />`;
  }
  return contextField({ label, hint, control, wide: type === "string" && !Array.isArray(item.options) });
}

function bindSchemaConfigForm(root, schemaData = {}) {
  const form = root.querySelector(".schema-config-form");
  if (!form) return;
  form.querySelectorAll("[data-config-provider-select]").forEach((select) => {
    const input = form.querySelector(`[name='${select.dataset.configProviderSelect}']`);
    bindProviderPicker(select, input);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    withButton(form.querySelector("button[type='submit']"), "保存中", () => saveSchemaConfigModule(form, schemaData));
  });
}

async function saveSchemaConfigModule(form, schemaData = {}) {
  const module = form.dataset.configModule || "";
  const advancedModule = form.dataset.configAdvancedModule || "";
  const data = new FormData(form);
  const values = schemaValuesFromForm(data, schemaData.schema?.[module]?.items || {});
  await apiPost("/config/module/update", { module, values });
  if (advancedModule) {
    const advancedValues = schemaValuesFromForm(data, schemaData.schema?.[advancedModule]?.items || {});
    await apiPost("/config/module/update", { module: advancedModule, values: advancedValues });
  }
  if (module === "appearance") {
    applyTheme(values.theme);
  }
  showToast("配置模块已保存");
  await loadArchive();
}

function schemaValuesFromForm(data, schema = {}) {
  const values = {};
  for (const [key, item] of Object.entries(schema)) {
    const type = item?.type || "string";
    if (type === "bool") {
      values[key] = data.get(key) === "on";
    } else if (type === "int") {
      const value = Number(data.get(key));
      values[key] = Number.isFinite(value) ? Math.round(value) : Number(item.default || 0);
    } else if (type === "float") {
      const value = Number(data.get(key));
      values[key] = Number.isFinite(value) ? value : Number(item.default || 0);
    } else {
      values[key] = String(data.get(key) ?? "");
    }
  }
  return values;
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
  const rerankState = providerStateLabel(currentProvider, hasProvider);
  const embeddingState = providerStateLabel(currentEmbeddingProvider, hasEmbeddingProvider, Boolean(retrieval.embedding_enabled));
  return `
    <form id="retrievalConfigForm" class="context-form retrieval-config-form" autocomplete="off">
      <nav class="config-module-switcher" aria-label="配置模块">
        <button type="button" class="is-active">
          <b>检索召回</b>
          <span>候选、Embedding、Rerank</span>
        </button>
        <button type="button" data-archive-jump="topology">
          <b>权限边界</b>
          <span>窗口读取关系</span>
        </button>
        <button type="button" data-archive-jump="maintenance">
          <b>维护迁移</b>
          <span>修复、导入、清理</span>
        </button>
      </nav>
      <div class="retrieval-hero">
        <div class="retrieval-hero-copy">
          <b>检索配置</b>
          <p>控制记忆候选、向量补召回和二阶段重排。窗口间读取权限请在权限拓扑中调整。</p>
        </div>
        <div class="retrieval-status-grid">
          <span><em>路径</em><strong data-retrieval-status="mode">${escapeHtml(retrievalModeLabel(mode))}</strong></span>
          <span><em>Rerank</em><strong data-retrieval-status="rerank">${escapeHtml(rerankState)}</strong></span>
          <span><em>Embedding</em><strong data-retrieval-status="embedding">${escapeHtml(embeddingState)}</strong></span>
          <span><em>候选</em><strong data-retrieval-status="candidates">${escapeHtml(`${retrieval.rerank_candidate_limit ?? 32} / ${retrieval.embedding_top_k ?? 32}`)}</strong></span>
        </div>
        <div class="retrieval-flow">
          <span>权限过滤</span>
          <span>本地/向量候选</span>
          <span>可选重排</span>
          <span>注入组织</span>
        </div>
      </div>
      ${renderConfigInlineGuide("retrieval")}
      <section class="retrieval-quick-panel">
        <div class="context-form-section-head">
          <b>推荐档位</b>
          <span>预设只会填入当前表单，保存后才生效。</span>
        </div>
        <div class="retrieval-preset-grid">
          <button type="button" data-retrieval-preset="safe">
            <b>保守</b>
            <span>本地优先，少调用模型</span>
          </button>
          <button type="button" data-retrieval-preset="balanced">
            <b>平衡</b>
            <span>自动重排，启用向量补召回</span>
          </button>
          <button type="button" data-retrieval-preset="deep">
            <b>深召回</b>
            <span>扩大候选，适合旧记忆库</span>
          </button>
        </div>
      </section>
      <section class="context-form-section retrieval-core-section">
        <div class="context-form-section-head">
          <b>核心路径</b>
          <span>日常只需要调这里；高级参数可保持默认。</span>
        </div>
        ${contextField({
          label: "检索实现路径",
          hint: "推荐自动选择。没有候选、没有 provider、超时或报错时会回退本地检索。",
          control: `
            <select name="mode">
              <option value="auto"${(retrieval.mode || "auto") === "auto" ? " selected" : ""}>自动选择</option>
              <option value="rerank"${retrieval.mode === "rerank" ? " selected" : ""}>强制重排</option>
              <option value="basic"${retrieval.mode === "basic" ? " selected" : ""}>本地检索</option>
            </select>
          `,
        })}
        ${contextField({
          label: "启用嵌入召回",
          hint: "在关键词之外补充语义相近记忆；没有 Embedding Provider 或调用失败时会自动回退。",
          control: contextSwitch("embedding_enabled", Boolean(retrieval.embedding_enabled)),
        })}
      </section>
      <section class="context-form-section retrieval-provider-section">
        <div class="context-form-section-head">
          <b>模型选择</b>
          <span>下拉用于快速选择，右侧输入框支持手动填写 Provider ID。</span>
        </div>
        ${contextField({
          label: "Rerank Provider",
          hint: "只列出具备 rerank() 能力的提供商。留空时自动扫描可用重排 Provider。",
          control: `
            <div class="provider-inline retrieval-provider-picker">
              <select name="rerank_provider_select">
                <option value="">自动探测 / 不指定</option>
                ${options.map((option) => `<option value="${escapeHtml(option.id || "")}"${(option.id || "") === currentProvider ? " selected" : ""}>${escapeHtml(option.label || option.id || "自动探测 / 不指定")}</option>`).join("")}
              </select>
              <input name="rerank_provider_id" type="text" value="${escapeHtml(currentProvider)}" placeholder="留空自动选择可用重排 Provider" />
            </div>
          `,
          wide: true,
        })}
        ${contextField({
          label: "Embedding Provider",
          hint: "只列出尽量检测到的嵌入提供商。留空时自动扫描第一个可用 Provider。",
          control: `
            <div class="provider-inline retrieval-provider-picker">
              <select name="embedding_provider_select">
                <option value="">自动探测 / 不指定</option>
                ${embeddingProviderOptions.map((option) => `<option value="${escapeHtml(option.id || "")}"${(option.id || "") === currentEmbeddingProvider ? " selected" : ""}>${escapeHtml(option.label || option.id || "自动探测 / 不指定")}</option>`).join("")}
              </select>
              <input name="embedding_provider_id" type="text" value="${escapeHtml(currentEmbeddingProvider)}" placeholder="留空自动选择可用嵌入 Provider" />
            </div>
          `,
          wide: true,
        })}
      </section>
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
        <span>保存后下一次检索或工具读取生效；注入日志会显示实际路径。</span>
        <button id="saveRetrievalConfigBtn" type="submit">保存检索配置</button>
      </div>
    </form>
  `;
}

function bindRetrievalConfigForm(root) {
  const form = root.querySelector("#retrievalConfigForm");
  if (!form) return;
  bindArchiveJumpButtons(form);
  const select = form.querySelector("[name='rerank_provider_select']");
  const input = form.querySelector("[name='rerank_provider_id']");
  bindProviderPicker(select, input);
  bindProviderPicker(
    form.querySelector("[name='embedding_provider_select']"),
    form.querySelector("[name='embedding_provider_id']"),
  );
  form.querySelectorAll("input, select").forEach((field) => {
    field.addEventListener("input", () => updateRetrievalDraftStatus(form));
    field.addEventListener("change", () => updateRetrievalDraftStatus(form));
  });
  form.querySelectorAll("[data-retrieval-preset]").forEach((button) => {
    button.addEventListener("click", () => applyRetrievalPreset(form, button.dataset.retrievalPreset));
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    withButton(form.querySelector("#saveRetrievalConfigBtn"), "保存中", () => saveRetrievalConfig(form));
  });
  updateRetrievalDraftStatus(form);
}

function setFormValue(form, name, value) {
  const field = form.querySelector(`[name='${name}']`);
  if (!field) return;
  if (field.type === "checkbox") {
    field.checked = Boolean(value);
  } else {
    field.value = String(value);
  }
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
}

function applyRetrievalPreset(form, preset) {
  const presets = {
    safe: {
      mode: "basic",
      embedding_enabled: false,
      rerank_candidate_multiplier: 3,
      rerank_candidate_limit: 24,
      rerank_timeout_ms: 1000,
      embedding_candidate_limit: 800,
      embedding_top_k: 24,
      embedding_score_threshold: 0.38,
      embedding_weight: 0.45,
      embedding_timeout_ms: 1200,
      embedding_backfill_enabled: false,
      embedding_backfill_batch_size: 24,
    },
    balanced: {
      mode: "auto",
      embedding_enabled: true,
      rerank_candidate_multiplier: 4,
      rerank_candidate_limit: 32,
      rerank_timeout_ms: 1400,
      embedding_candidate_limit: 1200,
      embedding_top_k: 32,
      embedding_score_threshold: 0.34,
      embedding_weight: 0.55,
      embedding_timeout_ms: 1500,
      embedding_backfill_enabled: true,
      embedding_backfill_batch_size: 50,
    },
    deep: {
      mode: "auto",
      embedding_enabled: true,
      rerank_candidate_multiplier: 5,
      rerank_candidate_limit: 48,
      rerank_timeout_ms: 2000,
      embedding_candidate_limit: 2200,
      embedding_top_k: 48,
      embedding_score_threshold: 0.30,
      embedding_weight: 0.70,
      embedding_timeout_ms: 2200,
      embedding_backfill_enabled: true,
      embedding_backfill_batch_size: 80,
    },
  };
  const values = presets[preset];
  if (!values) return;
  Object.entries(values).forEach(([name, value]) => setFormValue(form, name, value));
  form.querySelectorAll("[data-retrieval-preset]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.retrievalPreset === preset);
  });
  updateRetrievalDraftStatus(form);
  showToast("已套用预设，保存后生效");
}

function updateRetrievalDraftStatus(form) {
  const value = (name, fallback = "") => String(form.querySelector(`[name='${name}']`)?.value ?? fallback);
  const checked = (name) => Boolean(form.querySelector(`[name='${name}']`)?.checked);
  const set = (key, text) => {
    const target = form.querySelector(`[data-retrieval-status='${key}']`);
    if (target) target.textContent = text;
  };
  set("mode", retrievalModeLabel(value("mode", "auto")));
  set("rerank", value("rerank_provider_id") || "自动探测");
  set("embedding", checked("embedding_enabled") ? (value("embedding_provider_id") || "自动探测") : "未启用");
  set("candidates", `${value("rerank_candidate_limit", "32")} / ${value("embedding_top_k", "32")}`);
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
  const policy = memory.mention_policy || metadata.mention_policy || "";
  const mentionability = memory.mentionability_score ?? metadata.mentionability_score;
  const memoryReason = memory.memory_reason || metadata.memory_reason || "";
  const phase = memory.relationship_phase || metadata.relationship_phase || "";
  const decayMode = memory.decay_mode || metadata.decay_mode || "";
  const activeDimensions = Array.isArray(memory.active_dimensions) && memory.active_dimensions.length
    ? memory.active_dimensions
    : (Array.isArray(metadata.active_dimensions) ? metadata.active_dimensions : []);
  const weights = personaWeights(memory).sort((a, b) => b.value - a.value);
  const feedback = memory.mention_feedback || metadata.mention_feedback || {};
  const correction = metadata.user_correction || {};
  const hasPersona = policy || memoryReason || phase || decayMode || activeDimensions.length || weights.length || feedback.last_reaction || correction.text;
  if (!keyFacts.length && !topics.length && !participants.length && !canonical && !hasPersona) return "";
  return `
    <section class="memory-structured-panel">
      ${hasPersona ? `
        <div class="memory-structured-block">
          <b>提及策略</b>
          <div class="memory-diagnostics-grid">
            ${policy ? `<span><em>策略</em><strong>${escapeHtml(mentionPolicyLabel(policy))}</strong></span>` : ""}
            ${mentionability !== undefined && mentionability !== null ? `<span><em>可提及性</em><strong>${escapeHtml(percentLabel(mentionability))}</strong></span>` : ""}
            ${phase ? `<span><em>关系阶段</em><strong>${escapeHtml(phase)}</strong></span>` : ""}
            ${decayMode ? `<span><em>衰减</em><strong>${escapeHtml(decayModeLabel(decayMode))}</strong></span>` : ""}
            ${feedback.last_reaction ? `<span><em>上次反馈</em><strong>${escapeHtml(reactionLabel(feedback.last_reaction))}</strong></span>` : ""}
          </div>
          ${memoryReason ? `<p class="memory-reason">${escapeHtml(memoryReason)}</p>` : ""}
          ${activeDimensions.length ? `<div class="memory-structured-tags">${activeDimensions.slice(0, 8).map((item) => `<span class="badge violet">${escapeHtml(dimensionLabel(item))}</span>`).join("")}</div>` : ""}
          ${weights.length ? `
            <div class="weight-meter-list">
              ${weights.slice(0, 8).map((item) => `
                <span class="weight-meter">
                  <i style="--w:${Math.round(Math.max(0, Math.min(1, item.value)) * 100)}%"></i>
                  <b>${escapeHtml(dimensionLabel(item.key))}</b>
                  <em>${escapeHtml(percentLabel(item.value))}</em>
                </span>
              `).join("")}
            </div>
          ` : ""}
          ${correction.text ? `<p class="memory-reason is-warning">用户纠正：${escapeHtml(correction.text)}</p>` : ""}
        </div>
      ` : ""}
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

function showInjectionLogDetail(payload) {
  const selected = Array.isArray(payload.selected_memories) ? payload.selected_memories : [];
  const blocked = Array.isArray(payload.blocked_reasons) ? payload.blocked_reasons : [];
  $("#detailDrawer").className = "detail-drawer";
  $("#detailDrawer").innerHTML = `
    <div class="memory-manage-head">
      <div>
        <h3>注入记录</h3>
        <p class="item-meta">${escapeHtml(formatTime(payload.created_at))} · ${escapeHtml(payload.scope || "unknown")} · ${escapeHtml(shortId(payload.session_id || "-"))}</p>
      </div>
      <div class="badges">
        <span class="badge blue">选中 ${escapeHtml((payload.selected_memory_ids || []).length)} 条</span>
        <span class="badge teal">过滤 ${escapeHtml(blocked.length)} 条</span>
        <span class="badge gold">${escapeHtml(payload.injection_chars || 0)} chars</span>
      </div>
    </div>
    <section class="memory-structured-panel">
      <div class="memory-structured-block">
        <b>本轮查询</b>
        <p>${escapeHtml(payload.query || "未记录查询文本")}</p>
      </div>
      ${selected.length ? `
        <div class="memory-structured-block">
          <b>进入注入的记忆</b>
          <div class="log-memory-list">
            ${selected.map((memory) => `
              <button type="button" class="log-memory-item" data-memory-id="${escapeHtml(memory.id)}">
                <span>${escapeHtml(compact(memory.canonical_summary || memory.content, memory.id))}</span>
                <small>${escapeHtml(memory.memory_type || "memory")} · ${escapeHtml(mentionPolicyLabel(memory.mention_policy || ""))}</small>
              </button>
            `).join("")}
          </div>
        </div>
      ` : `<div class="empty-state">这一轮没有实际注入长期记忆。</div>`}
      ${blocked.length ? `
        <div class="memory-structured-block">
          <b>过滤原因</b>
          <div class="badges">${blockedReasonBadges(blocked)}</div>
          <ul class="log-blocked-list">
            ${blocked.slice(0, 12).map((item) => `<li><b>${escapeHtml(blockedReasonLabel(item.reason || item))}</b><span>${escapeHtml(item.reason || JSON.stringify(item))}</span></li>`).join("")}
          </ul>
        </div>
      ` : ""}
    </section>
    <details class="memory-raw-detail">
      <summary>原始日志</summary>
      <pre>${escapeHtml(JSON.stringify(payload || {}, null, 2))}</pre>
    </details>
  `;
  $$("#detailDrawer [data-memory-id]").forEach((button) => {
    button.addEventListener("click", () => showMemory(button.dataset.memoryId));
  });
}

function showGenericDetail(title, payload) {
  if (title === "注入记录详情") {
    showInjectionLogDetail(payload || {});
    return;
  }
  $("#detailDrawer").classList.remove("empty");
  $("#detailDrawer").innerHTML = `
    <h3>${escapeHtml(title)}</h3>
    <pre>${escapeHtml(JSON.stringify(payload || {}, null, 2))}</pre>
  `;
}

function clearDetail() {
  $("#detailDrawer").className = "detail-drawer empty";
  $("#detailDrawer").innerHTML = `
    <div class="detail-empty">
      <b>等待选片</b>
      <span>选择左侧对象，再点一条记忆或记录查看详情。</span>
    </div>
  `;
}

function livingMemoryPathValue() {
  const activeInputs = Array.from(document.querySelectorAll("#view-archive .archive-section.is-active .livingmemory-path"));
  const filled = activeInputs.find((input) => input.value.trim());
  if (filled) return filled.value.trim();
  const fallbackInput = activeInputs[0] || $("#view-archive .livingmemory-path");
  return fallbackInput?.value.trim() || "";
}

function sumLivingMemoryRows(tables = [], importable = true) {
  return tables
    .filter((table) => Boolean(table.importable) === importable)
    .reduce((total, table) => total + Math.max(0, Number(table.count) || 0), 0);
}

function archiveResultCard(label, value, note = "", tone = "blue") {
  return `
    <article class="archive-result-card">
      <span class="badge ${escapeHtml(tone)}">${escapeHtml(label)}</span>
      <b>${escapeHtml(value)}</b>
      ${note ? `<small>${escapeHtml(note)}</small>` : ""}
    </article>
  `;
}

function renderArchiveResultDetails(value) {
  return `
    <details class="memory-raw-detail archive-raw-detail">
      <summary>原始结果</summary>
      <pre>${escapeHtml(JSON.stringify(value || {}, null, 2))}</pre>
    </details>
  `;
}

function renderLivingMemoryPreview(report = {}) {
  const candidates = Array.isArray(report.candidates) ? report.candidates : [];
  if (!candidates.length) {
    return `
      <section class="archive-result-panel">
        <div class="archive-result-head">
          <b>未找到 LivingMemory 数据库</b>
          <span>可以填写数据库路径后重新预览。</span>
        </div>
        ${renderArchiveResultDetails(report)}
      </section>
    `;
  }
  const primary = candidates[0] || {};
  const tables = Array.isArray(primary.tables) ? primary.tables : [];
  const importableRows = sumLivingMemoryRows(tables, true);
  const skippedRows = sumLivingMemoryRows(tables, false);
  const importableTables = tables.filter((table) => table.importable);
  const skippedTables = tables.filter((table) => !table.importable);
  return `
    <section class="archive-result-panel">
      <div class="archive-result-head">
        <b>LivingMemory 预览</b>
        <span>${escapeHtml(primary.path || "未记录来源路径")}</span>
      </div>
      <div class="archive-result-grid">
        ${archiveResultCard("可导入", `${importableRows} 条`, `${importableTables.length} 张表`, "teal")}
        ${archiveResultCard("将跳过", `${skippedRows} 条`, "派生碎片或空表", "gold")}
        ${archiveResultCard("候选库", `${candidates.length} 个`, candidates.length > 1 ? "默认导入第一项" : "已锁定来源", "blue")}
      </div>
      ${importableTables.length ? `
        <div class="archive-table-list">
          <b>将导入的表</b>
          ${importableTables.slice(0, 6).map((table) => `
            <span><strong>${escapeHtml(table.name || "-")}</strong><em>${escapeHtml(table.count || 0)} 行</em></span>
          `).join("")}
        </div>
      ` : `<div class="empty-state">没有可导入的完整摘要表。</div>`}
      ${skippedTables.length ? `
        <div class="archive-table-list is-muted">
          <b>跳过的碎片</b>
          ${skippedTables.slice(0, 6).map((table) => `
            <span><strong>${escapeHtml(table.name || "-")}</strong><em>${escapeHtml(table.note || "not_importable")}</em></span>
          `).join("")}
        </div>
      ` : ""}
      ${renderArchiveResultDetails(report)}
    </section>
  `;
}

function renderLivingMemoryImportResult(result = {}) {
  if (result.reason && !result.source_path) {
    return `
      <section class="archive-result-panel">
        <div class="archive-result-head">
          <b>导入未执行</b>
          <span>${escapeHtml(result.reason)}</span>
        </div>
        ${renderArchiveResultDetails(result)}
      </section>
    `;
  }
  return `
    <section class="archive-result-panel">
      <div class="archive-result-head">
        <b>LivingMemory 导入完成</b>
        <span>${escapeHtml(result.source_path || "未记录来源路径")}</span>
      </div>
      <div class="archive-result-grid">
        ${archiveResultCard("已导入", `${result.imported || 0} 条`, result.batch_id ? `批次 ${shortId(result.batch_id)}` : "", "teal")}
        ${archiveResultCard("异常跳过", `${result.skipped || 0} 条`, "空内容或无法识别", Number(result.skipped || 0) ? "gold" : "blue")}
        ${archiveResultCard("审核状态", `${result.default_review_status || "auto"}`, "导入策略", "violet")}
      </div>
      ${Array.isArray(result.importable_tables) && result.importable_tables.length ? `
        <div class="archive-table-list">
          <b>导入明细</b>
          ${result.importable_tables.slice(0, 8).map((table) => `
            <span><strong>${escapeHtml(table.name || "-")}</strong><em>${escapeHtml(table.imported || 0)} / ${escapeHtml(table.count || 0)}</em></span>
          `).join("")}
        </div>
      ` : ""}
      ${renderArchiveResultDetails(result)}
    </section>
  `;
}

function renderLivingMemoryRepairResult(result = {}) {
  return `
    <section class="archive-result-panel">
      <div class="archive-result-head">
        <b>内容修复结果</b>
        <span>${escapeHtml(result.source_path || result.reason || "未记录来源路径")}</span>
      </div>
      <div class="archive-result-grid">
        ${archiveResultCard("已修复", `${result.updated || 0} 条`, "旧编号内容已替换", "teal")}
        ${archiveResultCard("跳过", `${result.skipped || 0} 条`, result.error || "没有匹配内容", Number(result.skipped || 0) ? "gold" : "blue")}
      </div>
      ${renderArchiveResultDetails(result)}
    </section>
  `;
}

function renderGenericArchiveResult(value = {}, title = "执行结果") {
  const entries = Object.entries(value || {}).filter(([, item]) => typeof item !== "object");
  return `
    <section class="archive-result-panel">
      <div class="archive-result-head">
        <b>${escapeHtml(title)}</b>
        <span>操作已返回结果。</span>
      </div>
      ${entries.length ? `
        <div class="archive-result-grid">
          ${entries.slice(0, 6).map(([key, item]) => archiveResultCard(key, String(item), "", "blue")).join("")}
        </div>
      ` : ""}
      ${renderArchiveResultDetails(value)}
    </section>
  `;
}

function showArchiveResult(value, kind = "generic") {
  const box = $("#importResult");
  if (!box) return;
  box.hidden = false;
  if (kind === "preview") {
    box.innerHTML = renderLivingMemoryPreview(value);
  } else if (kind === "import") {
    box.innerHTML = renderLivingMemoryImportResult(value);
  } else if (kind === "repair") {
    box.innerHTML = renderLivingMemoryRepairResult(value);
  } else {
    box.innerHTML = renderGenericArchiveResult(value, kind === "maintenance" ? "维护结果" : "执行结果");
  }
}

async function runMaintenance() {
  const data = await apiPost("/maintenance");
  await refreshAll();
  showArchiveResult(data.result, "maintenance");
  showToast("维护已完成");
}

async function repairLivingMemoryContent() {
  const path = livingMemoryPathValue();
  const data = await apiPost("/maintenance/repair_livingmemory_content", { path });
  await refreshAll();
  showArchiveResult(data.result, "repair");
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

function scopedClearPayload(scope) {
  const bucket = activeBucket();
  const requiredScope = scope === "group_member" ? "group" : scope;
  if (!bucket || bucket.id === "all" || bucket.scope !== requiredScope || !bucket.target_id) return null;
  if (scope === "group" || scope === "group_member") {
    const groupId = bucket.group_id || bucket.target_id;
    if (scope === "group_member") {
      const userId = String($("#clearGroupMemberUserId")?.value || "").trim();
      if (!userId) return null;
      return {
        target_type: "group_member",
        group_id: groupId,
        user_id: userId,
        label: `${bucket.label} 中的用户 ${userId}`,
      };
    }
    return {
      target_type: "group",
      group_id: groupId,
      label: bucket.label,
    };
  }
  return {
    target_type: "private",
    user_id: bucket.target_id,
    label: bucket.label,
  };
}

function clearScopeCountsText(counts = {}) {
  const labels = {
    memories: "长期记忆",
    timeline: "时间线",
    relationship_edges: "关系边",
    knowledge_nodes: "图谱节点",
    knowledge_edges: "图谱边",
    injection_logs: "注入日志",
    summary_failures: "总结失败记录",
    cross_window_threads: "跨窗口线程",
  };
  return Object.entries(labels)
    .map(([key, label]) => `${label} ${Number(counts[key] || 0)}`)
    .join(" / ");
}

function showScopedClearConfirm(payload, counts = {}) {
  const drawer = $("#detailDrawer");
  if (!drawer) return;
  drawer.className = "detail-drawer";
  drawer.innerHTML = `
    <div class="clear-confirm scoped-clear-confirm">
      <b>确认清空范围记忆</b>
      <p>将清空：<strong>${escapeHtml(payload.label || "当前范围")}</strong></p>
      <p class="scoped-clear-counts">${escapeHtml(clearScopeCountsText(counts))}</p>
      <input id="clearScopeConfirmText" type="text" placeholder="输入 清空 后执行" autocomplete="off" />
      <div class="inline-actions">
        <button id="executeClearScopeMemoryBtn" class="danger" type="button" disabled>执行清空</button>
        <button id="cancelClearScopeMemoryBtn" type="button">取消</button>
      </div>
    </div>
  `;
  const input = $("#clearScopeConfirmText");
  const execute = $("#executeClearScopeMemoryBtn");
  const cancel = $("#cancelClearScopeMemoryBtn");
  const update = () => {
    execute.disabled = input.value.trim() !== "清空";
  };
  input.addEventListener("input", update);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !execute.disabled) {
      withBusy("正在清空范围记忆...", () => executeScopedClearMemory(payload));
    }
  });
  execute.addEventListener("click", () => withBusy("正在清空范围记忆...", () => executeScopedClearMemory(payload)));
  cancel.addEventListener("click", () => {
    clearDetail();
    showToast("已取消清空操作");
  });
  input.focus();
  showToast("请在右侧输入“清空”确认");
}

async function executeScopedClearMemory(payload) {
  const confirmText = $("#clearScopeConfirmText")?.value.trim();
  if (confirmText !== "清空") {
    showToast("请输入“清空”后再执行", "error");
    return;
  }
  const data = await apiPost("/maintenance/clear_scope", { ...payload, confirm: "清空" });
  state.activeBucketId = "all";
  await refreshAll();
  showGenericDetail("范围清理结果", data.result);
  showToast("范围记忆已清空");
}

async function clearCurrentScopedMemory(scope) {
  const payload = scopedClearPayload(scope);
  if (!payload) {
    const message = scope === "group_member" ? "请先选择具体群聊并填写群成员 QQ" : `请先选择具体${scope === "group" ? "群聊" : "私聊用户"}`;
    showToast(message, "error");
    return;
  }
  const preview = await apiPost("/maintenance/clear_scope", { ...payload, preview: true });
  const counts = preview.result?.counts || {};
  const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
  if (total <= 0) {
    showToast("这个范围内没有可清理的数据");
    return;
  }
  showScopedClearConfirm(payload, counts);
}

async function previewImport() {
  const path = livingMemoryPathValue();
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  const data = await apiGet(`/import/livingmemory/preview?${params.toString()}`);
  showArchiveResult(data.report, "preview");
  showToast("预览已生成");
}

async function runImport() {
  const path = livingMemoryPathValue();
  if (!confirm("确认开始导入？导入内容默认会按保守策略处理。")) return;
  const data = await apiPost("/import/livingmemory/run", { path });
  await refreshAll();
  showArchiveResult(data.result, "import");
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
  $("#clearCurrentGroupMemoryBtn")?.addEventListener("click", () => withBusy("正在预览范围清理...", () => clearCurrentScopedMemory("group")));
  $("#clearGroupMemberMemoryBtn")?.addEventListener("click", () => withBusy("正在预览群成员记忆清理...", () => clearCurrentScopedMemory("group_member")));
  $("#clearCurrentPrivateMemoryBtn")?.addEventListener("click", () => withBusy("正在预览范围清理...", () => clearCurrentScopedMemory("private")));
  $("#previewImportBtn").addEventListener("click", () => withBusy("正在扫描 LivingMemory...", previewImport));
  $("#runImportBtn").addEventListener("click", () => withBusy("正在导入 LivingMemory...", runImport));
  $("#globalSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadActiveView();
  });
  $("#bucketList").addEventListener("scroll", requestRailCoverflow, { passive: true });
  $("#bucketList").addEventListener("pointermove", requestRailCoverflow, { passive: true });
  window.addEventListener("resize", requestRailCoverflow);
}

async function loadPersonaState() {
  const panel = $("#personaStatePanel");
  if (!panel) return;
  panel.innerHTML = `<div class="persona-loading">正在读取拟人维度数据...</div>`;
  let data;
  try {
    data = await apiGet("/persona-state");
  } catch (err) {
    panel.innerHTML = `<div class="persona-error">读取失败：${escapeHtml(err?.message || "未知错误")}</div>`;
    return;
  }
  panel.innerHTML = renderPersonaState(data || {});
}

function renderPersonaState(d) {
  const phases = d.phases || [];
  const events = d.pending_emotional_events || [];
  const crossState = d.cross_window_emotional_state || {};
  const timeOfDay = d.time_of_day || "";
  const phaseLabels = d.phase_labels || {};
  const addressLabels = d.address_phase_labels || {};
  const timeLabels = d.time_of_day_labels || {};
  const botAddress = d.bot_address_suggestions || {};
  const phaseDefs = d.phase_definitions || {};
  const allPhases = phaseDefs.phases || ["acquaintance", "familiar", "close", "intimate", "deeply_bonded"];
  const thresholds = phaseDefs.thresholds || [0.0, 0.20, 0.45, 0.65, 0.85];

  const timeLabel = timeLabels[timeOfDay] || timeOfDay || "未知";
  const crossTotal = crossState.total || 0;
  const crossScar = crossState.scar_count || 0;
  const crossWarm = crossState.warm_count || 0;
  const crossVuln = crossState.vulnerable_count || 0;

  let html = '<div class="persona-grid">';

  // 1. Time-of-day and cross-window summary card
  html += `
    <div class="persona-card persona-card-wide">
      <div class="persona-card-head">
        <b>当前时段</b>
        <span class="persona-badge persona-badge-time">${escapeHtml(timeLabel)}</span>
      </div>
      <div class="persona-card-body">
        <div class="persona-cross-window">
          <span class="persona-cw-label">跨窗口情绪余波</span>
          <div class="persona-cw-stats">
            <span class="persona-cw-stat ${crossTotal > 0 ? 'is-active' : ''}">总计 ${crossTotal}</span>
            ${crossScar > 0 ? `<span class="persona-cw-stat persona-cw-scar">伤痕 ${crossScar}</span>` : ''}
            ${crossWarm > 0 ? `<span class="persona-cw-stat persona-cw-warm">温暖 ${crossWarm}</span>` : ''}
            ${crossVuln > 0 ? `<span class="persona-cw-stat persona-cw-vuln">脆弱 ${crossVuln}</span>` : ''}
          </div>
          ${crossTotal === 0 ? '<small class="persona-cw-empty">近 30 分钟内无跨窗口情绪残留</small>' : '<small class="persona-cw-active">情绪正在跨窗口传递中</small>'}
        </div>
      </div>
    </div>
  `;

  // 2. Relationship phases
  if (phases.length === 0) {
    html += `
      <div class="persona-card persona-card-wide">
        <div class="persona-card-head"><b>关系阶段</b></div>
        <div class="persona-card-body">
          <p class="persona-empty">还没有足够的关系互动数据。随着对话积累，关系阶段会自然演进。</p>
        </div>
      </div>
    `;
  } else {
    html += `
      <div class="persona-card persona-card-wide">
        <div class="persona-card-head"><b>关系阶段演进</b><span class="persona-badge">${phases.length} 个会话</span></div>
        <div class="persona-card-body">
          <div class="persona-phase-list">
            ${phases.map(p => renderPersonaPhaseItem(p, allPhases, thresholds, phaseLabels, addressLabels, botAddress)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  // 3. Pending emotional events
  if (events.length > 0) {
    html += `
      <div class="persona-card persona-card-wide">
        <div class="persona-card-head"><b>情绪事件队列</b><span class="persona-badge">${events.length} 条待处理</span></div>
        <div class="persona-card-body">
          <div class="persona-event-list">
            ${events.map(e => renderPersonaEventItem(e)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  html += '</div>';
  return html;
}

function renderPersonaPhaseItem(p, allPhases, thresholds, phaseLabels, addressLabels, botAddress) {
  const phase = p.phase || 'acquaintance';
  const momentum = p.momentum || 0;
  const phaseLabel = phaseLabels[phase] || phase;
  const touchCount = p.touch_count || 0;
  const addressPhase = p.current_address_phase || '';
  const addressLabel = addressLabels[addressPhase] || '';
  const updatedAt = p.updated_at || '';
  const sessionKey = p.session_key || '';
  const shortSession = sessionKey.length > 40 ? sessionKey.slice(0, 37) + '...' : sessionKey;

  // Find current phase index for progress bar
  const phaseIdx = allPhases.indexOf(phase);
  const phasePercent = phaseIdx >= 0 ? ((phaseIdx + 1) / allPhases.length) * 100 : 20;

  // Momentum bar: map [-0.3, 1.0] to [0%, 100%]
  const momentumPercent = Math.max(0, Math.min(100, ((momentum + 0.3) / 1.3) * 100));
  const momentumClass = momentum >= 0.45 ? 'is-high' : momentum >= 0.15 ? 'is-mid' : momentum < 0 ? 'is-low' : '';

  // Bot address suggestion
  const botSuggestion = botAddress[phase] || {};
  const botTone = botSuggestion.tone || '';
  const botHint = botSuggestion.hint || '';

  // Address log
  const addressLog = p.address_log || [];
  const hasAddressLog = addressLog.length > 0;

  return `
    <div class="persona-phase-item">
      <div class="persona-phase-header">
        <div class="persona-phase-info">
          <span class="persona-phase-name">${escapeHtml(phaseLabel)}</span>
          <small class="persona-phase-session">${escapeHtml(shortSession)}</small>
        </div>
        <div class="persona-phase-meta">
          <span class="persona-phase-touch">${touchCount} 次触动</span>
          ${addressLabel ? `<span class="persona-phase-address">称呼：${escapeHtml(addressLabel)}</span>` : ''}
        </div>
      </div>
      <div class="persona-phase-progress">
        <div class="persona-phase-bar">
          <div class="persona-phase-bar-fill" style="width:${phasePercent}%"></div>
        </div>
        <div class="persona-phase-steps">
          ${allPhases.map((ph, i) => `<span class="persona-phase-step ${i <= phaseIdx ? 'is-active' : ''}">${escapeHtml(phaseLabels[ph] || ph)}</span>`).join('')}
        </div>
      </div>
      <div class="persona-momentum">
        <span class="persona-momentum-label">动量</span>
        <div class="persona-momentum-bar">
          <div class="persona-momentum-fill ${momentumClass}" style="width:${momentumPercent}%"></div>
        </div>
        <span class="persona-momentum-value">${momentum.toFixed(3)}</span>
      </div>
      ${botTone ? `
        <div class="persona-bot-address">
          <span class="persona-bot-tone">${escapeHtml(botTone)}</span>
          ${botHint ? `<small class="persona-bot-hint">${escapeHtml(botHint)}</small>` : ''}
        </div>
      ` : ''}
      ${hasAddressLog ? `
        <details class="persona-address-log">
          <summary>称呼演变记录 (${addressLog.length})</summary>
          <div class="persona-address-timeline">
            ${addressLog.map(log => `
              <div class="persona-address-entry">
                <span class="persona-address-time">${escapeHtml((log.ts || '').slice(0, 16))}</span>
                <span class="persona-address-change">${escapeHtml(addressLabels[log.previous] || log.previous || '—')} → ${escapeHtml(addressLabels[log.phase] || log.phase || '')}</span>
              </div>
            `).join('')}
          </div>
        </details>
      ` : ''}
      ${updatedAt ? `<small class="persona-phase-updated">更新于 ${escapeHtml(updatedAt.slice(0, 16))}</small>` : ''}
    </div>
  `;
}

function renderPersonaEventItem(e) {
  const type = e.event_type || '';
  const delta = Number(e.energy_delta) || 0;
  const hint = e.mood_hint || '';
  const preview = e.content_preview || '';
  const sessionId = e.session_id || '';
  const shortSession = sessionId.length > 30 ? sessionId.slice(0, 27) + '...' : sessionId;
  const typeLabels = {
    'scar_touched': { label: '伤痕触动', class: 'is-scar' },
    'warm_memory': { label: '温暖记忆', class: 'is-warm' },
    'vulnerable_resonance': { label: '脆弱共鸣', class: 'is-vuln' },
  };
  const typeInfo = typeLabels[type] || { label: type, class: '' };
  const deltaSign = delta >= 0 ? '+' : '';
  const deltaClass = delta >= 0 ? 'is-positive' : 'is-negative';

  return `
    <div class="persona-event-item ${typeInfo.class}">
      <div class="persona-event-head">
        <span class="persona-event-type">${escapeHtml(typeInfo.label)}</span>
        <span class="persona-event-delta ${deltaClass}">${deltaSign}${delta.toFixed(1)}</span>
      </div>
      <div class="persona-event-body">
        ${hint ? `<span class="persona-event-hint">${escapeHtml(hint)}</span>` : ''}
        ${preview ? `<small class="persona-event-preview">${escapeHtml(preview)}</small>` : ''}
        <small class="persona-event-session">${escapeHtml(shortSession)}</small>
      </div>
    </div>
  `;
}

/* ====== 权限拓扑可视化 ====== */

let _topologyState = { data: null, selectedNode: null, selectedPair: null, busy: false };

async function loadAclTopology() {
  const container = $("#aclTopologyContainer");
  if (!container) return;
  container.innerHTML = loadingState("正在读取权限矩阵...");
  try {
    const data = await apiGet("/acl/matrix");
    _topologyState.data = data;
    _topologyState.selectedNode = null;
    _topologyState.selectedPair = null;
    _topologyState.busy = false;
    container.innerHTML = renderAclTopology(data);
    bindAclTopologyInteractions(container);
  } catch (err) {
    container.innerHTML = `<div class="persona-error">权限矩阵读取失败：${escapeHtml(err?.message || "未知错误")}</div>`;
  }
}

function _policyFor(policies, scope, id) {
  const found = policies.find(p => p.window_scope === scope && p.window_id === id);
  if (found) return { read_mode: found.read_mode, share_mode: found.share_mode };
  const defaultMode = scope === "group" ? "blacklist" : "whitelist";
  return { read_mode: defaultMode, share_mode: defaultMode };
}

function _findRule(rules, ownerScope, ownerId, readerScope, readerId) {
  return rules.find(r =>
    r.owner_scope === ownerScope && r.owner_id === ownerId &&
    r.reader_scope === readerScope && r.reader_id === readerId && r.enabled
  );
}

function _permissionState(owner, reader, rules, policies) {
  const rule = _findRule(rules, owner.scope, owner.id, reader.scope, reader.id);
  if (rule) return rule.effect === "deny" ? "deny" : "allow";
  return "default";
}

function _defaultEffect(owner, reader, policies) {
  const ownerPolicy = _policyFor(policies, owner.scope, owner.id);
  const readerPolicy = _policyFor(policies, reader.scope, reader.id);
  const requiresExplicit = owner.scope === "private" && reader.scope === "group";
  if (requiresExplicit) return "deny";
  if (ownerPolicy.share_mode === "blacklist" && readerPolicy.read_mode === "blacklist") return "allow";
  return "deny";
}

function _permStateInfo(state, defaultEffect) {
  if (state === "allow") return { color: "var(--acl-allow, #4a9)", label: "手动允许", solid: true };
  if (state === "deny") return { color: "var(--acl-deny, #c43)", label: "手动屏蔽", solid: true };
  // default
  if (defaultEffect === "allow") return { color: "var(--acl-default-allow, #7ba)", label: "默认放行", solid: false };
  return { color: "var(--acl-default-deny, #e95)", label: "默认禁止", solid: false };
}

function _topologyNodeKey(w) { return `${w.scope}:${w.id}`; }

function _shortId(id, max) {
  if (!id) return "";
  const s = String(id);
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

function _topologyNodeLabels(node) {
  const bucketTitle = splitWindowBucketTitle({
    scope: node.scope,
    target_id: node.id,
    group_id: node.scope === "group" ? node.id : "",
    label: node.label || "",
    sublabel: node.identifier_label || "",
    target_name: node.target_name || node.display_name || "",
  });
  const missingName = node.scope === "group" ? "未记录群名" : "未记录昵称";
  const name = bucketTitle.secondary && bucketTitle.secondary !== bucketTitle.primary
    ? bucketTitle.secondary
    : missingName;
  return {
    name,
    id: bucketTitle.primary || windowIdentifierLabel(node.scope, node.id),
  };
}

function _topologyMidArrow(pathPoint, fromPoint, toPoint, ownerKey, readerKey, info, extraClass = "") {
  const angle = Math.atan2(toPoint.y - fromPoint.y, toPoint.x - fromPoint.x) * 180 / Math.PI;
  return `<text class="topo-mid-arrow ${extraClass}" x="${pathPoint.x}" y="${pathPoint.y}" transform="rotate(${angle} ${pathPoint.x} ${pathPoint.y})" fill="${info.color}" data-owner="${escapeHtml(ownerKey)}" data-reader="${escapeHtml(readerKey)}">➤</text>`;
}

function _topologyNodeBadgeClass(node) {
  return node?.scope === "group" ? "topo-node-group-badge" : "topo-node-private-badge";
}

function _layoutNodes(windows) {
  const groups = windows.filter(w => w.scope === "group");
  const privates = windows.filter(w => w.scope === "private");
  const colGap = 500;
  const rowGap = 108;
  const startY = 74;
  const groupX = 120;
  const privateX = groupX + colGap;
  const nodes = [];
  groups.forEach((w, i) => {
    nodes.push({ ...w, key: _topologyNodeKey(w), x: groupX, y: startY + i * rowGap });
  });
  privates.forEach((w, i) => {
    nodes.push({ ...w, key: _topologyNodeKey(w), x: privateX, y: startY + i * rowGap });
  });
  const maxCount = Math.max(groups.length, privates.length);
  const width = Math.max(760, privateX + 160);
  const height = Math.max(360, startY + maxCount * rowGap + 86);
  return { nodes, width, height, groupCount: groups.length, privateCount: privates.length };
}

function renderAclTopology(data) {
  const windows = data.windows || [];
  const rules = data.rules || [];
  const policies = data.policies || [];

  if (windows.length < 2) {
    return `<div class="empty-state">至少需要 2 个窗口才能配置权限。当前有 ${windows.length} 个窗口。</div>`;
  }

  const { nodes, width, height } = _layoutNodes(windows);
  const nodeMap = new Map(nodes.map(n => [n.key, n]));

  const pairs = [];
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const ab = _permissionState(a, b, rules, policies);
      const ba = _permissionState(b, a, rules, policies);
      const abDefault = ab === "default" ? _defaultEffect(a, b, policies) : "";
      const baDefault = ba === "default" ? _defaultEffect(b, a, policies) : "";
      pairs.push({ a, b, ab, ba, abDefault, baDefault });
    }
  }

  const selectedKey = _topologyState.selectedNode;
  const selectedPair = _topologyState.selectedPair;

  let arrowsHtml = "";
  let arrowHitsHtml = "";
  let nodesHtml = "";

  for (const pair of pairs) {
    const { a, b, ab, ba, abDefault, baDefault } = pair;
    const isPairSelected = selectedPair && (
      (selectedPair[0] === a.key && selectedPair[1] === b.key) ||
      (selectedPair[0] === b.key && selectedPair[1] === a.key)
    );
    const involvesSelected = selectedKey && (a.key === selectedKey || b.key === selectedKey);
    const dim = !isPairSelected && !involvesSelected ? " is-dim" : "";
    const highlight = isPairSelected ? " is-highlighted" : "";
    const hitDisabled = selectedPair && !isPairSelected ? " is-disabled" : "";
    const arrowDisabled = selectedPair && !isPairSelected ? " is-locked" : "";

    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const ox = -dy / dist * 18;
    const oy = dx / dist * 18;
    const ox2 = -dy / dist * 34;
    const oy2 = dx / dist * 34;

    const abInfo = _permStateInfo(ab, abDefault);
    const baInfo = _permStateInfo(ba, baDefault);

    // a -> b curve (upper)
    const ax1 = a.x + ox, ay1 = a.y + oy;
    const bx1 = b.x + ox, by1 = b.y + oy;
    const mx1 = (a.x + b.x) / 2 + ox2, my1 = (a.y + b.y) / 2 + oy2;
    const pathAb = `M ${ax1} ${ay1} Q ${mx1} ${my1} ${bx1} ${by1}`;
    const midAb = { x: 0.25 * ax1 + 0.5 * mx1 + 0.25 * bx1, y: 0.25 * ay1 + 0.5 * my1 + 0.25 * by1 };
    const abDashAttr = abInfo.solid ? "" : 'stroke-dasharray="5 4"';
    const abMarkerId = ab === "default" ? `topo-m-default-${abDefault}` : `topo-m-${ab}`;
    arrowsHtml += `<path class="topo-arrow${dim}${highlight}${arrowDisabled}" d="${pathAb}" data-owner="${escapeHtml(a.key)}" data-reader="${escapeHtml(b.key)}" data-state="${ab}" stroke="${abInfo.color}" fill="none" stroke-width="${abInfo.solid ? 2.5 : 1.8}" marker-end="url(#${abMarkerId})" ${abDashAttr}><title>${escapeHtml(a.label)} → ${escapeHtml(b.label)}: ${abInfo.label}</title></path>`;
    arrowsHtml += _topologyMidArrow(midAb, { x: ax1, y: ay1 }, { x: bx1, y: by1 }, a.key, b.key, abInfo, `${dim}${highlight}${hitDisabled}`);
    arrowHitsHtml += `<path class="topo-arrow-hit${hitDisabled}" d="${pathAb}" data-owner="${escapeHtml(a.key)}" data-reader="${escapeHtml(b.key)}" fill="none"><title>${escapeHtml(a.label)} → ${escapeHtml(b.label)}: 点击切换权限</title></path>`;

    // b -> a curve (lower)
    const ax2 = a.x - ox, ay2 = a.y - oy;
    const bx2 = b.x - ox, by2 = b.y - oy;
    const mx2 = (a.x + b.x) / 2 - ox2, my2 = (a.y + b.y) / 2 - oy2;
    const pathBa = `M ${bx2} ${by2} Q ${mx2} ${my2} ${ax2} ${ay2}`;
    const midBa = { x: 0.25 * bx2 + 0.5 * mx2 + 0.25 * ax2, y: 0.25 * by2 + 0.5 * my2 + 0.25 * ay2 };
    const baDashAttr = baInfo.solid ? "" : 'stroke-dasharray="5 4"';
    const baMarkerId = ba === "default" ? `topo-m-default-${baDefault}` : `topo-m-${ba}`;
    arrowsHtml += `<path class="topo-arrow${dim}${highlight}${arrowDisabled}" d="${pathBa}" data-owner="${escapeHtml(b.key)}" data-reader="${escapeHtml(a.key)}" data-state="${ba}" stroke="${baInfo.color}" fill="none" stroke-width="${baInfo.solid ? 2.5 : 1.8}" marker-end="url(#${baMarkerId})" ${baDashAttr}><title>${escapeHtml(b.label)} → ${escapeHtml(a.label)}: ${baInfo.label}</title></path>`;
    arrowsHtml += _topologyMidArrow(midBa, { x: bx2, y: by2 }, { x: ax2, y: ay2 }, b.key, a.key, baInfo, `${dim}${highlight}${hitDisabled}`);
    arrowHitsHtml += `<path class="topo-arrow-hit${hitDisabled}" d="${pathBa}" data-owner="${escapeHtml(b.key)}" data-reader="${escapeHtml(a.key)}" fill="none"><title>${escapeHtml(b.label)} → ${escapeHtml(a.label)}: 点击切换权限</title></path>`;
  }

  // Column headers
  nodesHtml += `
    <text class="topo-col-header" x="120" y="30" text-anchor="middle">群聊</text>
    <text class="topo-col-header" x="620" y="30" text-anchor="middle">私聊</text>`;

  // Nodes
  for (const n of nodes) {
    const isSelected = n.key === selectedKey;
    const isInPair = selectedPair && (selectedPair[0] === n.key || selectedPair[1] === n.key);
    const cls = `topo-node topo-node-${n.scope}${isSelected ? " is-selected" : ""}${isInPair ? " is-paired" : ""}`;
    const r = 24;
    const icon = n.scope === "group" ? "#" : "♡";
    const label = _topologyNodeLabels(n);
    const textX = n.scope === "group" ? 42 : -42;
    const anchor = n.scope === "group" ? "start" : "end";
    nodesHtml += `
      <g class="${cls}" data-node-key="${escapeHtml(n.key)}" transform="translate(${n.x},${n.y})">
        <circle r="${r}" />
        <text class="topo-node-icon" y="3">${escapeHtml(icon)}</text>
        <text class="topo-node-label" x="${textX}" y="-8" text-anchor="${anchor}">${escapeHtml(compact(label.name, 18))}</text>
        <text class="topo-node-id" x="${textX}" y="10" text-anchor="${anchor}">${escapeHtml(compact(label.id, 24))}</text>
        <text class="topo-node-count" x="${textX}" y="27" text-anchor="${anchor}">${n.memory_count || 0} 条记忆</text>
      </g>`;
  }

  return `
    <div class="topo-wrapper">
      <div class="topo-legend">
        <span class="topo-legend-item"><span class="topo-legend-line topo-allow"></span>手动允许</span>
        <span class="topo-legend-item"><span class="topo-legend-line topo-deny"></span>手动屏蔽</span>
        <span class="topo-legend-item"><span class="topo-legend-line topo-default-allow"></span>默认放行</span>
        <span class="topo-legend-item"><span class="topo-legend-line topo-default-deny"></span>默认禁止</span>
        <span class="topo-legend-hint">点击两个节点选中，再点击箭头切换</span>
      </div>
      <div class="topo-canvas-wrap">
        <svg class="topo-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMin meet">
          <defs>
            <marker id="topo-m-allow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acl-allow, #4a9)" /></marker>
            <marker id="topo-m-deny" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acl-deny, #c43)" /></marker>
            <marker id="topo-m-default-allow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acl-default-allow, #7ba)" /></marker>
            <marker id="topo-m-default-deny" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acl-default-deny, #e95)" /></marker>
          </defs>
          <g class="topo-arrows">${arrowsHtml}</g>
          <g class="topo-arrow-hits">${arrowHitsHtml}</g>
          <g class="topo-nodes">${nodesHtml}</g>
        </svg>
      </div>
    </div>`;
}

function bindAclTopologyInteractions(container) {
  // Node click
  container.querySelectorAll("[data-node-key]").forEach(el => {
    el.addEventListener("click", () => {
      const key = el.dataset.nodeKey;
      if (_topologyState.selectedNode === key) {
        _topologyState.selectedNode = null;
        _topologyState.selectedPair = null;
      } else if (_topologyState.selectedNode && _topologyState.selectedNode !== key) {
        _topologyState.selectedPair = [_topologyState.selectedNode, key];
        _topologyState.selectedNode = null;
      } else {
        _topologyState.selectedNode = key;
        _topologyState.selectedPair = null;
      }
      _rerenderTopology();
    });
  });

  // Arrow click
  container.querySelectorAll(".topo-arrow[data-owner][data-reader], .topo-arrow-hit[data-owner][data-reader], .topo-mid-arrow[data-owner][data-reader]").forEach(el => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (_topologyState.busy) return;
      const ownerKey = el.dataset.owner;
      const readerKey = el.dataset.reader;
      if (
        _topologyState.selectedPair
        && !(
          (_topologyState.selectedPair[0] === ownerKey && _topologyState.selectedPair[1] === readerKey)
          || (_topologyState.selectedPair[0] === readerKey && _topologyState.selectedPair[1] === ownerKey)
        )
      ) {
        return;
      }
      if (!_topologyState.selectedPair) {
        _topologyState.selectedPair = [ownerKey, readerKey];
      }
      _toggleTopologyPermission(ownerKey, readerKey);
    });
  });

}

function _rerenderTopology() {
  const container = $("#aclTopologyContainer");
  if (!container || !_topologyState.data) return;
  container.innerHTML = renderAclTopology(_topologyState.data);
  bindAclTopologyInteractions(container);
}

async function _toggleTopologyPermission(ownerKey, readerKey) {
  const data = _topologyState.data;
  if (!data) return;
  if (_topologyState.busy) return;
  _topologyState.busy = true;
  _rerenderTopology();
  const ownerIdx = ownerKey.indexOf(":");
  const ownerScope = ownerIdx >= 0 ? ownerKey.slice(0, ownerIdx) : ownerKey;
  const ownerId = ownerIdx >= 0 ? ownerKey.slice(ownerIdx + 1) : "";
  const readerIdx = readerKey.indexOf(":");
  const readerScope = readerIdx >= 0 ? readerKey.slice(0, readerIdx) : readerKey;
  const readerId = readerIdx >= 0 ? readerKey.slice(readerIdx + 1) : "";
  const rules = data.rules || [];
  const policies = data.policies || [];
  const existing = _findRule(rules, ownerScope, ownerId, readerScope, readerId);
  const owner = { scope: ownerScope, id: ownerId };
  const reader = { scope: readerScope, id: readerId };
  const currentState = _permissionState(owner, reader, rules, policies);

  // Three-state cycle: allow → deny → default → allow → ...
  let action;
  if (currentState === "allow") {
    action = "to_deny";
  } else if (currentState === "deny") {
    action = "to_default";
  } else {
    // default → allow
    action = "to_allow";
  }

  try {
    if (action === "to_default" && existing) {
      await apiPost("/acl/delete", { id: existing.id });
      showToast("已恢复默认策略");
    } else if (action === "to_allow") {
      await apiPost("/acl/upsert", {
        owner_scope: ownerScope, owner_id: ownerId,
        reader_scope: readerScope, reader_id: readerId,
        effect: "allow", enabled: true,
      });
      showToast("已手动允许");
    } else if (action === "to_deny") {
      await apiPost("/acl/upsert", {
        owner_scope: ownerScope, owner_id: ownerId,
        reader_scope: readerScope, reader_id: readerId,
        effect: "deny", enabled: true,
      });
      showToast("已手动屏蔽");
    }
    const fresh = await apiGet("/acl/matrix");
    _topologyState.data = fresh;
    _topologyState.busy = false;
    _rerenderTopology();
  } catch (err) {
    _topologyState.busy = false;
    _rerenderTopology();
    showToast(err?.message || "权限切换失败", "error");
  }
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
