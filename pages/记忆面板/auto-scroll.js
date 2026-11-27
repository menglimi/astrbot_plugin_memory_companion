/* 共享零依赖自动滚动增量加载模块（MemoryAutoScroll）
   用于「记忆检视」「她记得的人」「待修复 / 排队处理 / 已处理」等长列表。
   特性：
   - IntersectionObserver 自动适配嵌套滚动容器（桌面 #content）与视口滚动（移动端 / 人物页）
   - 260ms 防抖节流、并发锁、游标进度校验与连续自动触发安全阀
   - 报错自动熔断停止轮询，底部提供一键点击重试
   - 记忆用户「自动滚动加载」偏好（默认开启，沙箱禁用存储时自动降级内存态）
   - 底部统一状态条与平滑「回到顶部」 */
(function (root) {
  "use strict";

  const DEFAULT_STORAGE_KEY = "memory_companion_auto_scroll_v1";
  const PREF_EVENT = "mc:autoscroll-pref";
  const memoryPrefs = new Map();

  function safeReadPref(key, fallback) {
    const k = String(key || DEFAULT_STORAGE_KEY);
    try {
      const storage = typeof window !== "undefined" && window ? window.localStorage : null;
      if (storage && typeof storage.getItem === "function") {
        const raw = storage.getItem(k);
        if (raw === "1" || raw === "true") return true;
        if (raw === "0" || raw === "false") return false;
      }
    } catch (_) {
      /* 沙箱 iframe 禁用 Web Storage 时静默降级到内存态 */
    }
    return memoryPrefs.has(k) ? Boolean(memoryPrefs.get(k)) : Boolean(fallback);
  }

  function safeWritePref(key, value) {
    const k = String(key || DEFAULT_STORAGE_KEY);
    const enabled = Boolean(value);
    memoryPrefs.set(k, enabled);
    try {
      const storage = typeof window !== "undefined" && window ? window.localStorage : null;
      if (storage && typeof storage.setItem === "function") {
        storage.setItem(k, enabled ? "1" : "0");
      }
    } catch (_) {
      /* 忽略沙箱存储限制 */
    }
    try {
      if (typeof window !== "undefined" && window && typeof window.dispatchEvent === "function" && typeof CustomEvent === "function") {
        window.dispatchEvent(new CustomEvent(PREF_EVENT, { detail: { key: k, enabled } }));
      }
    } catch (_) {}
    return enabled;
  }

  function prefersReducedMotion() {
    try {
      return Boolean(
        typeof window !== "undefined" &&
        window &&
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches
      );
    } catch (_) {
      return false;
    }
  }

  function isScrollableElement(node) {
    if (!node || typeof node !== "object" || node === document.body || node === document.documentElement) {
      return false;
    }
    if (typeof window === "undefined" || !window || typeof window.getComputedStyle !== "function") {
      return false;
    }
    try {
      const style = window.getComputedStyle(node);
      if (!style) return false;
      const overflowY = String(style.overflowY || style.overflow || "").toLowerCase();
      if (!/^(auto|scroll|overlay)$/.test(overflowY)) return false;
      return true;
    } catch (_) {
      return false;
    }
  }

  function resolveScrollRoot(host, explicitRoot) {
    if (typeof explicitRoot === "function") {
      try {
        const resolved = explicitRoot();
        return isScrollableElement(resolved) ? resolved : null;
      } catch (_) {
        return null;
      }
    }
    if (explicitRoot && explicitRoot !== "auto") {
      return isScrollableElement(explicitRoot) ? explicitRoot : null;
    }
    let cursor = host ? host.parentElement : null;
    while (cursor && cursor !== document.body && cursor !== document.documentElement) {
      if (isScrollableElement(cursor)) return cursor;
      cursor = cursor.parentElement;
    }
    return null;
  }

  function escHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
    })[ch]);
  }

  function formatInt(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "0";
    try {
      return Math.max(0, Math.round(n)).toLocaleString("zh-CN");
    } catch (_) {
      return String(Math.max(0, Math.round(n)));
    }
  }

  function mount(options) {
    const opts = options && typeof options === "object" ? options : {};
    const host = opts.host;
    if (!host) {
      return {
        refresh() {},
        reset() {},
        destroy() {},
        isAutoEnabled() { return true; },
        setAutoEnabled() {},
        triggerLoad() { return Promise.resolve(); },
      };
    }

    const storageKey = String(opts.storageKey || DEFAULT_STORAGE_KEY);
    const rootMargin = String(opts.rootMargin || "280px 0px");
    const minIntervalMs = Math.max(0, Number(opts.minIntervalMs != null ? opts.minIntervalMs : 260));
    const maxAutoBurst = Math.max(1, Number(opts.maxAutoBurst != null ? opts.maxAutoBurst : 12));
    const topThreshold = Math.max(1, Number(opts.topThreshold != null ? opts.topThreshold : 16));
    const itemLabel = String(opts.itemLabel || "项");

    const hasMoreFn = typeof opts.hasMore === "function" ? opts.hasMore : () => false;
    const isLoadingFn = typeof opts.isLoading === "function" ? opts.isLoading : () => false;
    const hasErrorFn = typeof opts.hasError === "function" ? opts.hasError : () => false;
    const getErrorMessageFn = typeof opts.getErrorMessage === "function" ? opts.getErrorMessage : () => "";
    const getCountFn = typeof opts.getCount === "function" ? opts.getCount : () => 0;
    const getTotalFn = typeof opts.getTotal === "function" ? opts.getTotal : () => null;
    const getCursorFn = typeof opts.getCursor === "function" ? opts.getCursor : null;
    const onLoadMore = typeof opts.onLoadMore === "function" ? opts.onLoadMore : () => {};

    let destroyed = false;
    let autoEnabled = safeReadPref(storageKey, true);
    let inFlight = false;
    let burstCount = 0;
    let lastTriggerAt = 0;
    let debounceTimer = null;
    let cursorStalled = false;
    let internalError = "";
    let observer = null;
    let observedRoot = undefined;
    let scrollListenerTarget = null;
    let resizeBound = false;
    let sentinelIntersecting = false;

    const wrap = document.createElement("div");
    wrap.className = "mc-autoscroll";
    wrap.setAttribute("data-mc-autoscroll", "1");

    const sentinel = document.createElement("div");
    sentinel.className = "mc-as-sentinel";
    sentinel.setAttribute("aria-hidden", "true");

    const bar = document.createElement("div");
    bar.className = "mc-as-bar";
    bar.setAttribute("role", "status");
    bar.setAttribute("aria-live", "polite");

    wrap.appendChild(sentinel);
    wrap.appendChild(bar);
    host.innerHTML = "";
    host.appendChild(wrap);

    function currentErrorText() {
      const external = String(getErrorMessageFn() || "").trim();
      return external || internalError;
    }

    function isCircuitBroken() {
      return Boolean(hasErrorFn() || internalError);
    }

    function getActiveScrollTop() {
      const scrollRoot = resolveScrollRoot(host, opts.scrollRoot);
      if (scrollRoot) return Number(scrollRoot.scrollTop || 0);
      if (typeof window !== "undefined" && window) {
        return Number(window.scrollY || (document.documentElement && document.documentElement.scrollTop) || 0);
      }
      return 0;
    }

    function scrollToTop() {
      const behavior = prefersReducedMotion() ? "auto" : "smooth";
      let target = null;
      if (typeof opts.scrollTopTarget === "function") {
        try { target = opts.scrollTopTarget(); } catch (_) {}
      } else if (opts.scrollTopTarget) {
        target = opts.scrollTopTarget;
      } else {
        target = resolveScrollRoot(host, opts.scrollRoot);
      }
      if (target && typeof target.scrollTo === "function") {
        try {
          target.scrollTo({ top: 0, behavior });
        } catch (_) {
          target.scrollTop = 0;
        }
        return;
      }
      if (target && "scrollTop" in target) {
        target.scrollTop = 0;
        return;
      }
      if (typeof window !== "undefined" && window && typeof window.scrollTo === "function") {
        try {
          window.scrollTo({ top: 0, behavior });
        } catch (_) {
          window.scrollTo(0, 0);
        }
      }
    }

    function countSummary(count, total) {
      if (total != null && Number.isFinite(Number(total)) && Number(total) > 0) {
        return formatInt(count) + " / " + formatInt(total) + " " + itemLabel;
      }
      return formatInt(count) + " " + itemLabel;
    }

    function renderBar() {
      if (destroyed) return;
      const count = Math.max(0, Number(getCountFn() || 0));
      const rawTotal = getTotalFn();
      const total = rawTotal != null && Number.isFinite(Number(rawTotal)) ? Math.max(0, Number(rawTotal)) : null;
      const more = Boolean(hasMoreFn());
      const loadingNow = Boolean(inFlight || isLoadingFn());
      const errored = isCircuitBroken();
      const showTop = count >= topThreshold || getActiveScrollTop() > 420;

      if (count === 0 && !loadingNow && !more && !errored) {
        wrap.hidden = true;
        return;
      }
      wrap.hidden = false;

      let statusHtml = "";
      let actionHtml = "";

      if (loadingNow) {
        statusHtml =
          '<span class="mc-as-dots" aria-hidden="true"><i></i><i></i><i></i></span>' +
          '<span class="mc-as-text">正在加载更多…</span>' +
          (count > 0 ? '<span class="mc-as-count">已加载 ' + escHtml(countSummary(count, total)) + "</span>" : "");
      } else if (errored) {
        const reason = currentErrorText();
        statusHtml =
          '<span class="mc-as-dot is-error" aria-hidden="true"></span>' +
          '<span class="mc-as-text is-error">加载失败' + (reason ? "：" + escHtml(reason) : "") + "</span>";
        actionHtml = '<button class="mc-as-btn is-retry" type="button" data-as-action="retry">点击重试</button>';
      } else if (more) {
        const pausedByGuard = autoEnabled && (burstCount >= maxAutoBurst || cursorStalled);
        const hint = !autoEnabled
          ? "已加载 " + countSummary(count, total)
          : pausedByGuard
            ? "已加载 " + countSummary(count, total) + " · 点击继续加载"
            : "已加载 " + countSummary(count, total) + " · 下滑自动加载";
        statusHtml = '<span class="mc-as-text">' + escHtml(hint) + "</span>";
        if (!autoEnabled || pausedByGuard) {
          actionHtml = '<button class="mc-as-btn" type="button" data-as-action="load">加载更多</button>';
        }
      } else {
        const doneLabel = total != null && total > 0
          ? "已展示全部 " + formatInt(Math.max(count, total)) + " " + itemLabel
          : "已展示全部 " + formatInt(count) + " " + itemLabel;
        statusHtml =
          '<span class="mc-as-rule" aria-hidden="true"></span>' +
          '<span class="mc-as-text is-done">' + escHtml(doneLabel) + "</span>" +
          '<span class="mc-as-rule" aria-hidden="true"></span>';
      }

      const topBtn = showTop
        ? '<button class="mc-as-btn is-ghost" type="button" data-as-action="top" aria-label="回到顶部">↑ 回到顶部</button>'
        : "";

      const toggleBtn =
        '<button class="mc-as-toggle' + (autoEnabled ? " is-on" : "") + '" type="button" role="switch" ' +
        'aria-checked="' + (autoEnabled ? "true" : "false") + '" data-as-action="toggle" ' +
        'title="' + (autoEnabled ? "当前已开启自动滚动加载，点击切换为手动点击加载" : "当前已关闭自动滚动加载，点击重新开启") + '">' +
        '<span class="mc-as-switch" aria-hidden="true"><span class="mc-as-knob"></span></span>' +
        '<span>自动滚动加载</span>' +
        "</button>";

      bar.innerHTML =
        '<div class="mc-as-status">' + statusHtml + "</div>" +
        '<div class="mc-as-controls">' + actionHtml + topBtn + toggleBtn + "</div>";
    }

    async function executeLoad(manual) {
      if (destroyed) return;
      if (inFlight || isLoadingFn()) return;
      if (!hasMoreFn()) {
        renderBar();
        return;
      }
      if (!manual) {
        if (!autoEnabled || isCircuitBroken() || cursorStalled || burstCount >= maxAutoBurst) {
          renderBar();
          return;
        }
      } else {
        internalError = "";
        cursorStalled = false;
        burstCount = 0;
      }

      const beforeCursor = getCursorFn ? getCursorFn() : undefined;
      const beforeCount = Number(getCountFn() || 0);

      inFlight = true;
      lastTriggerAt = Date.now();
      if (!manual) burstCount += 1;
      renderBar();

      try {
        await onLoadMore();
        if (destroyed) return;
        internalError = "";
        const afterCursor = getCursorFn ? getCursorFn() : undefined;
        const afterCount = Number(getCountFn() || 0);
        if (
          !hasErrorFn() &&
          hasMoreFn() &&
          getCursorFn &&
          beforeCursor !== undefined &&
          afterCursor === beforeCursor &&
          afterCount <= beforeCount
        ) {
          cursorStalled = true;
        } else {
          cursorStalled = false;
        }
      } catch (err) {
        if (destroyed) return;
        internalError = err && err.message ? String(err.message) : String(err || "请求异常");
      } finally {
        inFlight = false;
        if (!destroyed) {
          renderBar();
          if (typeof sentinel.getBoundingClientRect === "function") {
            sentinelIntersecting = isSentinelNearViewport();
          } else {
            sentinelIntersecting = false;
          }
          if (autoEnabled && !isCircuitBroken() && !cursorStalled && hasMoreFn() && sentinelIntersecting && burstCount < maxAutoBurst) {
            scheduleAutoLoad();
          }
        }
      }
    }

    function scheduleAutoLoad() {
      if (destroyed || !autoEnabled || inFlight || isLoadingFn() || isCircuitBroken() || cursorStalled || !hasMoreFn()) {
        return;
      }
      if (burstCount >= maxAutoBurst) {
        renderBar();
        return;
      }
      if (debounceTimer) return;
      const elapsed = Date.now() - lastTriggerAt;
      const waitMs = Math.max(minIntervalMs - elapsed, 16);
      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        if (destroyed) return;
        if (typeof sentinel.getBoundingClientRect === "function") {
          if (!isSentinelNearViewport()) {
            sentinelIntersecting = false;
            return;
          }
        } else if (!sentinelIntersecting) {
          return;
        }
        executeLoad(false);
      }, waitMs);
    }

    function isSentinelNearViewport() {
      if (destroyed || wrap.hidden || typeof sentinel.getBoundingClientRect !== "function") return false;
      const rect = sentinel.getBoundingClientRect();
      const scrollRoot = resolveScrollRoot(host, opts.scrollRoot);
      const marginPx = parseInt(rootMargin, 10) || 280;
      if (scrollRoot && typeof scrollRoot.getBoundingClientRect === "function") {
        const rootRect = scrollRoot.getBoundingClientRect();
        return rect.top <= rootRect.bottom + marginPx && rect.bottom >= rootRect.top - marginPx;
      }
      const vh = typeof window !== "undefined" && window ? (window.innerHeight || 800) : 800;
      return rect.top <= vh + marginPx && rect.bottom >= -marginPx;
    }

    function handleUserScroll() {
      if (destroyed) return;
      if (burstCount >= maxAutoBurst) {
        burstCount = 0;
      }
      if (autoEnabled && hasMoreFn() && !isCircuitBroken() && isSentinelNearViewport()) {
        sentinelIntersecting = true;
        scheduleAutoLoad();
      }
    }

    function bindObserver() {
      if (destroyed) return;
      const nextRoot = resolveScrollRoot(host, opts.scrollRoot);
      if (observer && observedRoot === nextRoot) return;

      if (observer) {
        try { observer.disconnect(); } catch (_) {}
        observer = null;
      }
      if (scrollListenerTarget && typeof scrollListenerTarget.removeEventListener === "function") {
        scrollListenerTarget.removeEventListener("scroll", handleUserScroll);
        scrollListenerTarget = null;
      }

      observedRoot = nextRoot;
      scrollListenerTarget = nextRoot || (typeof window !== "undefined" ? window : null);
      if (scrollListenerTarget && typeof scrollListenerTarget.addEventListener === "function") {
        scrollListenerTarget.addEventListener("scroll", handleUserScroll, { passive: true });
      }

      if (typeof IntersectionObserver === "function") {
        try {
          observer = new IntersectionObserver(
            (entries) => {
              const hit = entries.some((entry) => entry && entry.isIntersecting);
              sentinelIntersecting = hit;
              if (hit) scheduleAutoLoad();
            },
            { root: nextRoot || null, rootMargin }
          );
          observer.observe(sentinel);
        } catch (_) {
          observer = null;
        }
      }
    }

    function onResize() {
      if (destroyed) return;
      bindObserver();
    }

    function onPrefBroadcast(event) {
      if (destroyed || !event || !event.detail || event.detail.key !== storageKey) return;
      const next = Boolean(event.detail.enabled);
      if (next === autoEnabled) return;
      autoEnabled = next;
      burstCount = 0;
      renderBar();
      if (autoEnabled && hasMoreFn() && !isCircuitBroken() && isSentinelNearViewport()) {
        sentinelIntersecting = true;
        scheduleAutoLoad();
      }
    }

    bar.addEventListener("click", (event) => {
      const btn = event && event.target && typeof event.target.closest === "function"
        ? event.target.closest("[data-as-action]")
        : null;
      if (!btn) return;
      const action = btn.getAttribute("data-as-action");
      if (action === "load" || action === "retry") {
        executeLoad(true);
      } else if (action === "top") {
        scrollToTop();
      } else if (action === "toggle") {
        autoEnabled = safeWritePref(storageKey, !autoEnabled);
        burstCount = 0;
        cursorStalled = false;
        renderBar();
        if (autoEnabled && hasMoreFn() && !isCircuitBroken() && isSentinelNearViewport()) {
          sentinelIntersecting = true;
          scheduleAutoLoad();
        }
      }
    });

    if (typeof window !== "undefined" && window && typeof window.addEventListener === "function") {
      window.addEventListener("resize", onResize, { passive: true });
      window.addEventListener(PREF_EVENT, onPrefBroadcast);
      resizeBound = true;
    }

    bindObserver();
    renderBar();

    return {
      refresh() {
        if (destroyed) return;
        if (!hasErrorFn()) internalError = "";
        bindObserver();
        renderBar();
        if (autoEnabled && !isCircuitBroken() && !cursorStalled && hasMoreFn() && isSentinelNearViewport()) {
          sentinelIntersecting = true;
          scheduleAutoLoad();
        }
      },
      reset() {
        if (destroyed) return;
        burstCount = 0;
        cursorStalled = false;
        internalError = "";
        sentinelIntersecting = false;
        if (debounceTimer) {
          clearTimeout(debounceTimer);
          debounceTimer = null;
        }
        renderBar();
      },
      triggerLoad() {
        return executeLoad(true);
      },
      isAutoEnabled() {
        return autoEnabled;
      },
      setAutoEnabled(enabled) {
        autoEnabled = safeWritePref(storageKey, Boolean(enabled));
        burstCount = 0;
        cursorStalled = false;
        renderBar();
      },
      destroy() {
        destroyed = true;
        if (debounceTimer) {
          clearTimeout(debounceTimer);
          debounceTimer = null;
        }
        if (observer) {
          try { observer.disconnect(); } catch (_) {}
          observer = null;
        }
        if (scrollListenerTarget && typeof scrollListenerTarget.removeEventListener === "function") {
          scrollListenerTarget.removeEventListener("scroll", handleUserScroll);
          scrollListenerTarget = null;
        }
        if (resizeBound && typeof window !== "undefined" && window && typeof window.removeEventListener === "function") {
          window.removeEventListener("resize", onResize);
          window.removeEventListener(PREF_EVENT, onPrefBroadcast);
          resizeBound = false;
        }
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
      },
    };
  }

  const api = {
    mount,
    readPreference: safeReadPref,
    writePreference: safeWritePref,
    DEFAULT_STORAGE_KEY,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root && typeof root === "object") {
    root.MemoryAutoScroll = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
