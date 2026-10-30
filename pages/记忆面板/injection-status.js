/*
 * Memory OS keeps its main archive renderer in a bundled asset.  Keep the
 * injection trace as a small independent surface so the release can show
 * operational evidence without rebuilding that bundle for every API change.
 */
(() => {
  "use strict";

  const LIMIT = 6;
  const API = "/api/plug/astrbot_plugin_memory_companion/page";

  const escapeHtml = (value) => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  const compact = (value, fallback = "") => {
    const text = String(value ?? "").trim();
    return text || fallback;
  };

  const clip = (value, limit) => {
    const text = compact(value);
    if (!text) return "无检索词";
    return text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text;
  };

  const number = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : 0;
  };

  const formatTime = (value) => {
    const text = compact(value);
    if (!text) return "时间未知";
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text;
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const getBridge = () => {
    if (window.AstrBotPluginPage) return window.AstrBotPluginPage;
    try {
      if (window.parent && window.parent !== window && window.parent.AstrBotPluginPage) {
        return window.parent.AstrBotPluginPage;
      }
    } catch (_) {
      return null;
    }
    return null;
  };

  async function readLogs() {
    const bridge = getBridge();
    let payload;
    if (bridge && typeof bridge.apiGet === "function") {
      payload = await bridge.apiGet("page/logs", { limit: LIMIT });
    } else {
      const response = await fetch(`${API}/logs?limit=${LIMIT}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      payload = await response.json();
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.error || `请求失败（HTTP ${response.status}）`);
      }
    }
    if (payload?.status === "error") {
      throw new Error(payload.message || payload.error || "注入日志读取失败");
    }
    const data = payload?.data !== undefined ? payload.data : payload;
    return Array.isArray(data?.items) ? data.items : [];
  }

  function rowHtml(item) {
    const selected = Array.isArray(item?.selected_memories) ? item.selected_memories : [];
    const blocked = Array.isArray(item?.blocked_reasons) ? item.blocked_reasons : [];
    const injected = selected.length > 0 || number(item?.injection_chars) > 0;
    return (
      '<li class="mc-injection-row">' +
        '<div class="mc-injection-row-main">' +
          '<strong title="' + escapeHtml(compact(item?.query) || "无检索词") + '">' +
            escapeHtml(clip(item?.query, 58)) +
          '</strong>' +
          '<span>' + escapeHtml(formatTime(item?.created_at)) + " · " +
            escapeHtml(`${selected.length} 条记忆 · ${number(item?.injection_chars)} 字`) +
          '</span>' +
        '</div>' +
        '<div class="mc-injection-row-meta">' +
          '<b data-state="' + (injected ? "ok" : "empty") + '">' +
            (injected ? "已注入" : "未注入") +
          '</b>' +
          (blocked.length ? '<i>过滤 ' + blocked.length + '</i>' : "") +
        '</div>' +
      '</li>'
    );
  }

  function createPanel() {
    const node = document.createElement("aside");
    node.id = "memory-injection-status";
    node.setAttribute("aria-label", "最近注入");
    node.innerHTML =
      '<div class="mc-injection-head">' +
        '<div><span>INJECTION TRACE</span><strong>最近注入</strong></div>' +
        '<button type="button" data-refresh-injection aria-label="刷新注入记录" title="刷新注入记录">↻</button>' +
      '</div>' +
      '<p class="mc-injection-status" data-injection-status>正在读取…</p>' +
      '<ol class="mc-injection-list" data-injection-list></ol>';
    return node;
  }

  function setMessage(panel, message, error = false) {
    const status = panel.querySelector("[data-injection-status]");
    const list = panel.querySelector("[data-injection-list]");
    if (status) {
      status.textContent = message;
      status.hidden = false;
      status.dataset.error = error ? "true" : "false";
    }
    if (list) list.innerHTML = "";
  }

  async function refresh(panel) {
    const status = panel.querySelector("[data-injection-status]");
    const list = panel.querySelector("[data-injection-list]");
    const button = panel.querySelector("[data-refresh-injection]");
    if (button) button.disabled = true;
    if (status) status.textContent = "正在读取…";
    try {
      const items = await readLogs();
      if (!items.length) {
        setMessage(panel, "暂无注入记录。产生一轮主链请求后会显示在这里。");
      } else {
        if (status) {
          status.textContent = `最近 ${items.length} 轮主链注入`;
          status.hidden = false;
          status.dataset.error = "false";
        }
        if (list) list.innerHTML = items.map(rowHtml).join("");
      }
    } catch (error) {
      setMessage(panel, error?.message || "注入日志读取失败", true);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function mount() {
    const stage = document.querySelector("#stage");
    if (!stage || document.querySelector("#memory-injection-status")) return;
    // The bundled module populates #stage asynchronously. Wait until it has
    // selected its first mode so its initial innerHTML cannot replace us.
    if (!stage.dataset.mode) {
      const observer = new MutationObserver(() => {
        if (stage.dataset.mode) {
          observer.disconnect();
          mount();
        }
      });
      observer.observe(stage, { attributes: true, childList: true });
      window.setTimeout(() => observer.disconnect(), 10000);
      return;
    }
    const panel = createPanel();
    stage.appendChild(panel);
    panel.querySelector("[data-refresh-injection]")?.addEventListener("click", () => refresh(panel));
    refresh(panel);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();
