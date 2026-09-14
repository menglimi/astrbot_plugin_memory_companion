// Reuse the terminal footer for a lightweight, read-only summary progress line.
(() => {
  async function refresh() {
    if (document.hidden) return;
    const footer = document.querySelector('.system-footer > span');
    const bridge = window.AstrBotPluginPage;
    if (!footer || !bridge?.apiGet || window.parent === window) return;
    try {
      const result = await Promise.race([
        bridge.apiGet('page/stats'),
        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 5000)),
      ]);
      const progress = (result?.data ?? result)?.stats?.summary_progress;
      if (!progress) return;
      const count = (key) => Number(progress[key] || 0).toLocaleString();
      footer.textContent = `原文 ${count('raw_events')} · 会话记忆 ${count('conversation_memories')} · 待处理 ${count('pending_batches')} · 待修复 ${count('quarantined_batches')}`;
      footer.title = `已处理且无新增记忆的批次：${count('no_memory_batches')}。待修复批次保留原文，后续会话继续处理。`;
    } catch (_) {
      // A status refresh must never interrupt the terminal scene.
    }
  }
  window.addEventListener('load', refresh, { once: true });
  document.addEventListener('visibilitychange', refresh);
  setInterval(refresh, 60000);
})();
