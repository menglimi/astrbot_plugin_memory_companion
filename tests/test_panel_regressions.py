from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "pages" / "记忆面板"


def read_panel(name: str) -> str:
    return (PANEL / name).read_text(encoding="utf-8")


class PanelRegressionTests(unittest.TestCase):
    """面板回归断言。

    `index.html` 在 2.1.0 之后只是风格分流页，真正的实现页是 `legacy.html`
    （外壳）与 `app.js`（视图由 JS 渲染，不再有静态 view 容器）。因此断言锚点
    从 index.html 的静态 id 改到这两个文件，被守护的行为保持不变。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = read_panel("app.js")
        cls.styles = read_panel("app.css")
        cls.page = read_panel("legacy.html")
        cls.entry = read_panel("index.html")

    def test_summary_models_have_private_and_group_configuration(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        summary_items = schema["memory_summary"]["items"]
        for key in (
            "private_provider_id",
            "private_fallback_provider_id",
            "group_provider_id",
            "group_fallback_provider_id",
        ):
            self.assertEqual("select_provider", summary_items[key]["_special"])
        # 面板不再为模型选择写死控件，改为按 /config/schema 的 options 渲染下拉框；
        # 摘要模块必须在模块表里有入口，否则这些键没有可编辑的界面。
        self.assertIn('memory_summary: "记忆摘要"', self.script)
        self.assertIn("if (Array.isArray(item.options) && item.options.length) {", self.script)
        self.assertIn("'<select id=\"cfg_' + esc(key) + '\">' +", self.script)

    def test_webview_actions_do_not_depend_on_native_dialogs(self) -> None:
        self.assertIsNone(re.search(r"\b(?:confirm|alert|prompt)\s*\(", self.script))
        self.assertIn("function showInlineConfirmation(title, message, confirmLabel)", self.script)
        self.assertIn("const confirmed = await showInlineConfirmation(", self.script)
        self.assertIn('await showInlineConfirmation("删除记忆"', self.script)
        self.assertIn('await showInlineConfirmation("清空全部记忆"', self.script)
        # LivingMemory 迁移入口仍然存在，且走页面 API 而不是原生对话框。
        self.assertIn("bind(\"#lmRunBtn\"", self.script)
        self.assertIn('apiPost("/import/livingmemory/run"', self.script)

    def test_personal_memory_failures_are_visible_and_recoverable(self) -> None:
        self.assertIn('apiTry(() => apiGet("/companion/personal-memory" + params), { available: false })', self.script)
        # 读取失败必须落到显式的「不可用」分支并带上原因，而不是渲染空快照。
        self.assertIn("if (result.available === false) {", self.script)
        self.assertIn("return { available: false, reason: compact(result.reason)", self.script)
        self.assertIn("if (!data.available) {", self.script)
        # 日期切换必须重新取数：失败后不得把选中日期写脏。
        self.assertIn("if (opts.date) botLifeDate = opts.date;", self.script)
        self.assertIn("if (result.selected_date) botLifeDate = result.selected_date;", self.script)
        self.assertIn("go(\"botlife\", { date: button.dataset.date })", self.script)

    def test_memory_management_uses_one_update_request(self) -> None:
        start = self.script.index("function bindMemoryActions(memoryId)")
        end = self.script.index("async function openMemory(memoryId)", start)
        block = self.script[start:end]

        self.assertEqual(1, block.count('apiPost("/memory/update"'))
        self.assertNotIn('apiPost("/memory/visibility"', block)
        self.assertNotIn('apiPost("/memory/lifecycle"', block)
        # 可见性与生命周期必须随同一次更新提交，而不是各自再发一次请求。
        self.assertIn('visibility: $("#editVisibility").value,', block)
        self.assertIn('lifecycle: $("#editLifecycle").value,', block)

    def test_panel_uses_authenticated_same_origin_http_when_page_bridge_is_unavailable(self) -> None:
        self.assertIn("function canUseHttpFallback()", self.script)
        self.assertIn("const httpAvailable = canUseHttpFallback();", self.script)
        self.assertIn("} else if (httpAvailable) {", self.script)
        self.assertIn('credentials: "same-origin"', self.script)
        self.assertIn('throw new Error("未检测到 AstrBot 页面桥接，且当前页面不能使用同源 Web API")', self.script)
        self.assertNotIn('get("debug_http")', self.script)

    def test_retrieval_config_save_requires_backend_confirmation(self) -> None:
        # 旧实现用专用端点与专用确认字段；2.1.0 起检索配置并入 /config/schema
        # 的通用保存路径，因此断言改为校验「保存必须 await 且后端失败必须上抛」。
        self.assertIn('retrieval: "检索"', self.script)
        start = self.script.index('const saveBtn = $("#configSaveBtn", node);')
        end = self.script.index('$$(".switch input", node).forEach((input) => {', start)
        block = self.script[start:end]

        self.assertIn('await apiPost("/config/module/update", { module: moduleId, values });', block)
        self.assertIn("toast(", block)
        self.assertIn('if (!data || data.success === false) throw new Error(', self.script)
        self.assertIn('if (data && data.status === "error") {', self.script)
        self.assertIn('throw new Error(data.message || data.error || "请求失败");', self.script)

    def test_non_qq_private_sessions_are_not_labeled_as_qq_users(self) -> None:
        # 窗口类型改由后端 target_kind 判定，面板原样展示，不再用 id 猜平台。
        self.assertIn('esc(compact(bucket.target_kind) || "window")', self.script)
        self.assertNotIn("/^\\d+$/.test(String(id))", self.script)
        store_source = (ROOT / "core" / "store.py").read_text(encoding="utf-8")
        self.assertIn('return "legacy_live2d"', store_source)
        self.assertIn('return "qq"', store_source)

    def test_historical_chat_import_is_a_guarded_responsive_wizard(self) -> None:
        self.assertIn('defineView("chatimport"', self.script)
        self.assertIn("const importState = { tab:", self.script)
        self.assertIn('data-tab="', self.script)
        # 文件导入必须是带说明与类型限定的拖放区，而不是裸 input。
        self.assertIn('<label class="dropzone" id="fileDrop" for="fileInput">', self.script)
        self.assertIn('accept=".txt,.log,.md,.json,text/plain,text/markdown,application/json"', self.script)
        self.assertIn('id="qqCapBtn"', self.script)
        self.assertIn('id="qqPreviewBtn"', self.script)
        self.assertIn('id="filePreviewBtn"', self.script)
        self.assertIn("apiTry(() => apiGet(\"/conversation-import/qq/capabilities\"), null)", self.script)
        self.assertIn('apiPost("/conversation-import/qq/preview", payload)', self.script)
        self.assertIn('apiPost("/conversation-import/upload", {', self.script)
        self.assertIn('apiPost("/conversation-import/start", payload)', self.script)
        self.assertIn('apiPost("/conversation-import/" + action, { batch_id: importState.batchId })', self.script)
        self.assertIn(".dropzone", self.styles)
        self.assertIn("@media (max-width: 900px) {", self.styles)

    def test_memory_rows_expand_to_show_full_content(self) -> None:
        # 列表行按设计截断（单行省略号），完整正文必须在抽屉里无截断展示。
        row_title = re.search(r"\.row-title\s*\{([^}]*)\}", self.styles)
        drawer_content = re.search(r"\.drawer-content\s*\{([^}]*)\}", self.styles)
        self.assertIsNotNone(row_title)
        self.assertIsNotNone(drawer_content)
        self.assertIn("text-overflow: ellipsis", row_title.group(1))
        self.assertIn("overflow: hidden", row_title.group(1))
        self.assertIn("white-space: pre-wrap", drawer_content.group(1))
        self.assertIn("word-break: break-word", drawer_content.group(1))
        self.assertNotIn("line-clamp", drawer_content.group(1))
        self.assertIn("overflow-y: auto", self.styles)
        self.assertIn("function memoryDetailHtml(memory)", self.script)
        self.assertIn('id="editContent"', self.script)

    def test_album_detail_contains_full_image_in_a_definite_frame(self) -> None:
        grid_block = re.search(r"\.album-grid\s*\{([^}]*)\}", self.styles)
        shot_block = re.search(r"\.album-shot img\s*\{([^}]*)\}", self.styles)
        lightbox_block = re.search(r"\.lightbox\s*\{([^}]*)\}", self.styles)
        lightbox_img = re.search(r"\.lightbox img\s*\{([^}]*)\}", self.styles)

        self.assertIsNotNone(grid_block)
        self.assertIsNotNone(shot_block)
        self.assertIsNotNone(lightbox_block)
        self.assertIsNotNone(lightbox_img)
        self.assertIn("repeat(auto-fill, minmax(124px, 1fr))", grid_block.group(1))
        self.assertIn("position: relative", re.search(r"\.album-shot\s*\{([^}]*)\}", self.styles).group(1))
        self.assertIn("aspect-ratio: 3 / 4", re.search(r"\.album-shot\s*\{([^}]*)\}", self.styles).group(1))
        self.assertIn("object-fit: cover", shot_block.group(1))
        # 放大视图必须是覆盖全屏的定帧，且整张图片完整可见。
        self.assertIn("position: fixed", lightbox_block.group(1))
        self.assertIn("inset: 0", lightbox_block.group(1))
        self.assertIn("place-items: center", lightbox_block.group(1))
        self.assertIn("max-width: 100%", lightbox_img.group(1))
        self.assertIn("max-height: 100%", lightbox_img.group(1))
        self.assertIn("function openLightbox(src, caption)", self.script)
        self.assertIn("if (source) openLightbox(source, figure.dataset.cap);", self.script)
        self.assertIn("</html>", self.page)

    def test_microscope_has_explicit_context_and_non_overlapping_results(self) -> None:
        self.assertIn('id="microQuery"', self.script)
        self.assertIn('id="microScope"', self.script)
        self.assertIn('["all", "全部可检索记忆（管理检索）"]', self.script)
        self.assertIn('id="microUser"', self.script)
        self.assertIn('id="microGroup"', self.script)
        self.assertIn('id="microTopK"', self.script)
        # 召回范围必须显式转成 context_mode，不能让"全部"退化成默认会话检索。
        self.assertIn('scope: microState.scope === "all" ? "unknown" : microState.scope,', self.script)
        self.assertIn('context_mode: microState.scope === "all" ? "all" : "session",', self.script)
        self.assertIn('microState.scope = $("#microScope", node).value;', self.script)
        # 命中与过滤结果分组渲染，互不覆盖。
        self.assertIn("const rows = Array.isArray(result.results) ? result.results : [];", self.script)
        self.assertIn("const blockedRows = Array.isArray(result.blocked) ? result.blocked : [];", self.script)
        self.assertIn(".micro-grid { grid-template-columns: minmax(0, 1fr); }", self.styles)

    def test_mobile_workspace_uses_page_scroll_instead_of_clipping_content(self) -> None:
        # 内容区自身滚动，视图不再各自设固定高度裁剪内容。
        content_block = re.search(r"\.content\s*\{([^}]*)\}", self.styles)
        self.assertIsNotNone(content_block)
        self.assertIn("overflow-y: auto", content_block.group(1))
        self.assertIn(".shell { grid-template-columns: 64px minmax(0, 1fr); }", self.styles)
        self.assertIn(".grid.split-2, .grid.split-3 { grid-template-columns: minmax(0, 1fr); }", self.styles)
        self.assertIn(".config-layout { grid-template-columns: minmax(0, 1fr); }", self.styles)
        self.assertIn(".config-field { grid-template-columns: minmax(0, 1fr); }", self.styles)
        self.assertIn(".drawer-body { flex: 1; overflow-y: auto;", self.styles)
        self.assertIn("max-height: 460px", self.styles)

    def test_mobile_controls_and_schedule_preserve_native_touch_behavior(self) -> None:
        self.assertIn("viewport-fit=cover", self.page)
        self.assertIn("@media (max-width: 900px) {", self.styles)
        self.assertIn("@media (max-width: 700px) {", self.styles)
        self.assertIn("@media (max-width: 760px) {", self.styles)
        self.assertIn("@media (prefers-reduced-motion: reduce) {", self.styles)
        # 画布类交互必须关闭浏览器手势，避免移动端点按被滚动抢走。
        self.assertIn("touch-action: none", self.styles)
        self.assertIn("min-height: calc(100vh - 92px)", self.styles)

    def test_overview_layout_switch_is_visible_persistent_and_accessible(self) -> None:
        self.assertIn('id="modeToggle"', self.page)
        self.assertIn('id="modeToggleLabel"', self.page)
        self.assertIn('class="tool-btn mode-toggle"', self.page)
        self.assertIn('aria-pressed="false"', self.page)
        self.assertIn("memory_companion_mode", self.page)
        # 模式必须在样式表之前恢复，否则会先渲染错误主题。
        self.assertLess(self.page.index("memory_companion_mode"), self.page.index('rel="stylesheet"'))
        self.assertIn("function applyMode(mode)", self.script)
        self.assertIn("const modeToggle = $(\"#modeToggle\");", self.script)
        self.assertIn("modeToggle.addEventListener(\"click\", () => {", self.script)
        self.assertIn("window.localStorage.setItem(MODE_KEY, state.mode);", self.script)
        self.assertIn("document.documentElement.dataset.uiMode = state.mode;", self.script)
        self.assertIn('html[data-ui-mode="cinema"]', self.styles)

        ids = re.findall(r'\bid="([^"]+)"', self.page)
        self.assertEqual(len(ids), len(set(ids)), "记忆面板不能包含重复 HTML id")

    def test_memory_atom_and_audit_operations_are_reachable_from_ui(self) -> None:
        self.assertIn('id="editSalience"', self.script)
        self.assertIn('id="editImportance"', self.script)
        self.assertIn('id="editConfidence"', self.script)
        self.assertIn("defineView(\"migrate\"", self.script)
        self.assertIn('id="auditLimit"', self.script)
        self.assertIn('id="auditBatch"', self.script)
        self.assertIn('bind("#auditPreviewBtn"', self.script)
        self.assertIn('bind("#auditStatusBtn"', self.script)
        self.assertIn('bind("#auditApplyBtn"', self.script)
        self.assertIn('bind("#auditRollbackBtn"', self.script)
        self.assertIn('apiPost("/maintenance/audit/preview"', self.script)
        self.assertIn('apiGet("/maintenance/audit/status?batch_id="', self.script)
        self.assertIn('apiPost("/maintenance/audit/apply"', self.script)
        self.assertIn('apiPost("/maintenance/audit/rollback"', self.script)

    def test_user_profile_and_private_memory_share_one_user_workspace(self) -> None:
        self.assertIn('defineView("navigate"', self.script)
        self.assertIn('profile: { label: "用户档案"', self.script)
        self.assertIn('{ key: "profile", meta: SCOPE_META.profile, jump: "inspect", filter: "profile", exact: true }', self.script)
        self.assertIn('{ key: "private", meta: SCOPE_META.private, jump: "inspect", filter: "scope:private", exact: true }', self.script)
        self.assertIn('{ key: "personal", meta: SCOPE_META.personal, jump: "botlife", filter: "", exact: false }', self.script)
        # 档案与私聊记忆共用同一个检视视图与筛选参数。
        self.assertIn('defineView("inspect"', self.script)
        self.assertIn('state.filters = { scope: filter.slice(6), q: "", visibility: "", lifecycle: "", memoryType: "", target: "" };', self.script)
        self.assertIn('if (filter === "profile") {', self.script)

    def test_relations_view_keeps_portrait_and_memory_sections_in_flow(self) -> None:
        # 关系视图在 2.1.0 被知识星图与互动协同取代，滚动与溢出语义随之迁移：
        # 星图区必须有确定高度，卡片不得被内容撑破。
        starmap_card = re.search(r"\.starmap-card\s*\{([^}]*)\}", self.styles)
        self.assertIsNotNone(starmap_card)
        self.assertIn("overflow: hidden", starmap_card.group(1))
        self.assertIn("min-height: 560px", starmap_card.group(1))
        self.assertIn("height: 620px", re.search(r"\.starmap-canvas\s*\{([^}]*)\}", self.styles).group(1))
        self.assertIn(".starmap-canvas { height: 480px; }", self.styles)
        self.assertIn(".starmap-wrap { grid-template-columns: minmax(0, 1fr); }", self.styles)
        self.assertIn('defineView("starmap"', self.script)
        self.assertIn("class GalaxyView {", self.script)
        self.assertIn("function buildGalaxy(memories, centerId)", self.script)
        self.assertIn("function relationScore(center, other)", self.script)


if __name__ == "__main__":
    unittest.main()
