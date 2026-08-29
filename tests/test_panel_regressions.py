from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PanelRegressionTests(unittest.TestCase):
    def test_config_and_clear_partial_failures_remain_visible(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        config_start = script.index("async function saveSchemaConfigModule")
        config_end = script.index("function schemaValuesFromForm", config_start)
        config_block = script[config_start:config_end]
        self.assertIn("const succeeded = []", config_block)
        self.assertIn("const failed = []", config_block)
        self.assertIn("已保存：", config_block)
        self.assertIn("需重载生效：", config_block)
        self.assertIn("配置页刷新", config_block)
        self.assertIn("全库清理未完整成功", script)
        self.assertIn("范围清理未完整成功", script)
        self.assertIn("data.result?.databases", script)
        self.assertIn("Number(counts.total)", script)
        self.assertIn('memory: "REQ-041 记忆"', script)

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
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        self.assertIn('sublabel: "私聊 / 群聊模型与阈值"', script)
        self.assertIn('key === "private_provider_id" || key === "group_provider_id"', script)

    def test_webview_actions_do_not_depend_on_native_dialogs(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")

        self.assertIsNone(re.search(r"\b(?:confirm|alert|prompt)\s*\(", script))
        self.assertIn("function showInlineConfirmation", script)
        self.assertIn('title: "导入 LivingMemory"', script)
        self.assertIn("executeLivingMemoryImport", script)

    def test_personal_memory_failures_are_visible_and_recoverable(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")

        self.assertIn('withBusy("正在切换个人记忆日期..."', script)
        self.assertIn("state.selectedPersonalDate = previous.date", script)
        self.assertIn("renderPersonalMemoryDetectionError", script)
        self.assertIn("data-retry-companion-detection", script)

    def test_memory_management_uses_one_update_request(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        start = script.index("async function saveMemoryManagement")
        end = script.index("function showInjectionLogDetail", start)
        block = script[start:end]

        self.assertEqual(1, block.count('apiPost("/memory/update"'))
        self.assertNotIn('apiPost("/memory/visibility"', block)
        self.assertNotIn('apiPost("/memory/lifecycle"', block)

    def test_panel_uses_authenticated_same_origin_http_when_page_bridge_is_unavailable(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function canUsePageHttpFallback", script)
        self.assertIn("const httpFallbackAvailable = canUsePageHttpFallback();", script)
        self.assertIn("getBridge() || (httpFallbackAvailable ? null : await waitForBridge())", script)
        self.assertIn("} else if (httpFallbackAvailable) {", script)
        self.assertIn('credentials: "same-origin"', script)
        self.assertNotIn('get("debug_http")', script)

    def test_retrieval_config_save_requires_backend_confirmation(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        start = script.index("async function saveRetrievalConfig")
        end = script.index("async function showMemory", start)
        block = script[start:end]

        self.assertIn('const result = await apiPost("/retrieval/config/update", payload);', block)
        self.assertIn('if (!result?.retrieval) throw new Error("检索配置未返回确认结果");', block)
        self.assertIn("result?.restart_required", block)
        self.assertIn("检索配置已保存；需重载生效", block)
        self.assertIn('showToast("检索配置已保存并立即生效")', block)
        self.assertIn("检索配置已保存，但刷新页面数据失败", block)

    def test_non_qq_private_sessions_are_not_labeled_as_qq_users(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")

        self.assertIn('targetKind === "legacy_live2d"', script)
        self.assertIn('primary: "旧 Live2D 会话"', script)
        self.assertIn('targetKind === "qq" || /^\\d+$/.test(String(id))', script)
        self.assertIn('return `私聊会话 ${id}`', script)

    def test_historical_chat_import_is_a_guarded_responsive_wizard(self) -> None:
        page = (ROOT / "pages" / "记忆面板" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "pages" / "记忆面板" / "app.css").read_text(encoding="utf-8")

        self.assertIn('id="historicalChatDropzone"', page)
        self.assertIn('.json,text/plain,text/markdown,application/json', page)
        self.assertIn('QQChatExporter 私聊 JSON', page)
        self.assertIn('QQChatExporter 聊天记录 JSON 请使用“历史聊天导入 / 文件导入”', page)
        self.assertIn('id="historicalChatRecentTopBtn"', page)
        self.assertIn('class="chat-import-steps"', page)
        self.assertNotIn('id="view-import"', page)
        self.assertNotIn('data-view="import"', page)
        self.assertIn('data-archive-section="conversation-import"', page)
        self.assertIn('data-import-source="qq"', page)
        self.assertIn('data-import-source="file"', page)
        self.assertIn('data-import-source="recent"', page)
        archive_view = page[page.index('id="view-archive"'):]
        self.assertIn('id="historicalChatDropzone"', archive_view)
        self.assertIn('data-import-source-tab="qq"', archive_view)
        self.assertIn('data-import-source-tab="file"', archive_view)
        self.assertIn('data-import-source-tab="recent"', archive_view)
        self.assertIn("function selectHistoricalChatFile", script)
        self.assertIn('/\\.(txt|log|md|json)$/i', script)
        self.assertIn('historicalChatPreviewSource: ""', script)
        self.assertIn('state.historicalChatPreviewSource !== conversationImportSource()', script)
        self.assertIn('function showConversationImportError', script)
        self.assertIn('该 JSON 是群聊记录，当前不能导入单用户私聊记忆', script)
        self.assertIn("function previewQQHistoryImport", script)
        self.assertIn('{ id: "conversation-import", label: "历史聊天导入"', script)
        self.assertIn('section === "conversation-import"', script)
        self.assertIn('apiGet("/conversation-import/qq/capabilities")', script)
        self.assertIn('apiPost("/conversation-import/qq/preview"', script)
        self.assertIn("function historicalChatValidationMessage", script)
        self.assertIn('roles.filter((role) => role === "bot").length !== 1', script)
        self.assertIn("historicalChatIdentityConfirmed", script)
        self.assertIn('historicalChatTargetContextId: ""', script)
        self.assertIn("function historicalChatPrivateContexts", script)
        self.assertIn('apiGet("/conversation-import/targets")', script)
        self.assertIn("historicalChatTargetBuckets", script)
        self.assertIn("function historicalChatContextPicker", script)
        self.assertIn("const exactChoices = botIds.size ? exactBot : exact", script)
        self.assertIn("同名候选", script)
        self.assertIn('class="chat-import-advanced-identity"', script)
        self.assertIn('<details class="chat-import-advanced-identity" ${selectedContext ? "" : "open"}>', script)
        self.assertIn("if (advancedIdentity) advancedIdentity.open = !context", script)
        self.assertIn("function historicalChatRebindPanel", script)
        self.assertIn('apiPost("/conversation-import/rebind"', script)
        self.assertIn("归属不对？修正到已有私聊", script)
        self.assertIn("升级前已完成的批次也可修正", script)
        self.assertIn('upgrade_legacy: "0"', script)
        self.assertIn("当前历史对话任务", script)
        self.assertNotIn("最近一次历史对话任务", script)
        self.assertNotIn('$("#chatEntity"', script)
        self.assertIn("min-height:44px", styles)
        self.assertIn(".chat-import-stage-track", styles)
        self.assertIn(".chat-import-context-picker", styles)
        self.assertIn(".chat-import-advanced-identity", styles)
        self.assertIn(".chat-import-rebind", styles)
        self.assertIn(".conversation-import-layout", styles)
        self.assertIn(".conversation-import-tabs", styles)
        self.assertIn("is-conversation-import", script)
        self.assertIn(".film-app.is-workspace.is-conversation-import .workspace-main", styles)

    def test_memory_rows_expand_to_show_full_content(self) -> None:
        styles = (ROOT / "pages" / "记忆面板" / "app.css").read_text(encoding="utf-8")
        main_block = re.search(r"\.memory-frame-main\s*\{([^}]*)\}", styles)
        title_block = re.search(r"\.memory-frame \.item-title\s*\{([^}]*)\}", styles)

        self.assertIsNotNone(main_block)
        self.assertIsNotNone(title_block)
        self.assertIn("grid-template-rows:auto auto", main_block.group(1))
        self.assertIn("align-content:start", main_block.group(1))
        self.assertIn("display:block", title_block.group(1))
        self.assertIn("overflow-wrap:anywhere", title_block.group(1))
        self.assertNotIn("line-clamp", title_block.group(1))

    def test_album_detail_contains_full_image_in_a_definite_frame(self) -> None:
        page = (ROOT / "pages" / "记忆面板" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "pages" / "记忆面板" / "app.css").read_text(encoding="utf-8")
        frame_block = re.search(r"\.album-detail-image\s*\{([^}]*)\}", styles)
        image_block = re.search(r"\.album-detail-image img\s*\{([^}]*)\}", styles)
        drawer_block = re.search(
            r"\.film-app\.is-personal-memory \.detail-drawer\.is-album-detail\s*\{([^}]*)\}",
            styles,
        )

        self.assertIsNotNone(frame_block)
        self.assertIsNotNone(image_block)
        self.assertIsNotNone(drawer_block)
        self.assertIn("position:relative", frame_block.group(1))
        self.assertIn("position:absolute", image_block.group(1))
        self.assertIn("inset:8px", image_block.group(1))
        self.assertIn("width:calc(100% - 16px)", image_block.group(1))
        self.assertIn("height:calc(100% - 16px)", image_block.group(1))
        self.assertIn("object-fit:contain", image_block.group(1))
        self.assertIn("height:clamp(480px, 62vh, 820px)", drawer_block.group(1))
        self.assertIn("app.css?v=1.10.5-ui-v1", page)

    def test_microscope_has_explicit_context_and_non_overlapping_results(self) -> None:
        page = (ROOT / "pages" / "记忆面板" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "pages" / "记忆面板" / "app.css").read_text(encoding="utf-8")
        layout = re.search(
            r"\.film-app\.is-workspace:not\(\.is-personal-memory\) #view-microscope\.is-active\s*\{([^}]*)\}",
            styles,
        )

        self.assertIn('id="microscopeContext"', page)
        self.assertIn('for="microscopeContext"', page)
        self.assertIn('aria-describedby="microscopeContextMeta"', page)
        self.assertIn('id="searchResult" class="result-grid" aria-live="polite"', page)
        self.assertIn('microscopeBucketId: "all"', script)
        self.assertIn("function renderMicroscopeContexts", script)
        self.assertIn("state.buckets.filter(isWindowBucket)", script)
        self.assertIn('context_mode: "all"', script)
        self.assertIn('payload.context_mode = "session"', script)
        self.assertIn('payload.bot_id = bucket.bot_id || ""', script)
        self.assertIn("function microscopeBuckets()", script)
        self.assertIn("microscope_contexts: microscopeContexts", script)
        self.assertIn("microscope_id: microscopeContextId(bucket, sample.bot_id)", script)
        self.assertIn('invalidateMicroscopeSearch("检索范围已切换，请重新检索。")', script)
        self.assertIn('invalidateMicroscopeSearch("检索内容已修改，请重新检索。")', script)
        self.assertIn('invalidateMicroscopeSearch(\n      microscopeContextStillAvailable', script)
        self.assertIn("const loadToken = ++state.bucketLoadToken", script)
        self.assertIn("if (loadToken !== state.bucketLoadToken) return false", script)
        self.assertIn('setMicroscopeSearchBusy(false)', script)
        self.assertIn('$("#runSearchBtn").addEventListener("click", runSearch)', script)
        self.assertNotIn('$("#runSearchBtn").addEventListener("click", (event) => withButton', script)
        self.assertIn("if (searchToken !== state.microscopeSearchToken) return;", script)
        self.assertIn("data.search_context || {}", script)
        self.assertIn("data.retrieval || {}", script)
        self.assertIn("retrieval.capped_slots || []", script)
        self.assertIn('class="microscope-slot-summary"', script)
        self.assertIsNotNone(layout)
        self.assertIn("grid-template-rows:auto auto minmax(0,1fr)", layout.group(1))
        self.assertIn("#view-microscope.is-active>.section-head{grid-row:1}", styles)
        self.assertIn("#view-microscope.is-active>.microscope-box{grid-row:2}", styles)
        self.assertIn("#view-microscope.is-active>#searchResult{grid-row:3}", styles)
        self.assertIn(".microscope-context-bar", styles)
        self.assertIn(".microscope-result-context", styles)
        self.assertIn(".microscope-slot-summary", styles)
        self.assertRegex(
            styles,
            r'#searchResult\[data-microscope-section="hits"\] \[data-result-section="hits"\],\s*'
            r'#searchResult\[data-microscope-section="blocked"\] \[data-result-section="blocked"\]\{\s*'
            r'grid-column:1/-1;',
        )

    def test_mobile_workspace_uses_page_scroll_instead_of_clipping_content(self) -> None:
        styles = (ROOT / "pages" / "记忆面板" / "app.css").read_text(encoding="utf-8")
        tablet_start = styles.index("@media(max-width:1080px)")
        phone_start = styles.index("@media(max-width:760px)", tablet_start)
        responsive_workspace = styles[tablet_start:phone_start]

        self.assertIn(
            ".film-app.is-workspace .workspace-frame{\n    max-height:none;\n  }",
            responsive_workspace,
        )
        self.assertIn(
            ".film-app.is-workspace:not(.is-personal-memory) .workspace-main{\n"
            "    min-height:320px;\n"
            "    height:auto;\n"
            "    max-height:none;\n"
            "    overflow:visible;\n"
            "  }",
            responsive_workspace,
        )
        self.assertIn(
            ".film-app.is-workspace:not(.is-personal-memory) .view.is-active{\n"
            "    display:block;\n"
            "    height:auto;\n"
            "    min-height:0;\n"
            "    overflow:visible;\n"
            "  }",
            responsive_workspace,
        )

    def test_mobile_controls_and_schedule_preserve_native_touch_behavior(self) -> None:
        page = (ROOT / "pages" / "记忆面板" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "pages" / "记忆面板" / "app.css").read_text(encoding="utf-8")
        phone_start = styles.index("@media(max-width:760px)")
        narrow_start = styles.index("@media(max-width:420px)", phone_start)
        phone_styles = styles[phone_start:narrow_start]

        self.assertIn("viewport-fit=cover", page)
        self.assertIn("min-height:100dvh", styles)
        self.assertIn("touch-action:pan-y", styles)
        self.assertIn("font-size:16px", phone_styles)
        self.assertIn("min-height:44px", phone_styles)
        self.assertIn("-webkit-overflow-scrolling:touch", phone_styles)
        self.assertIn("overscroll-behavior:contain", phone_styles)
        self.assertIn('dragAxis = Math.abs(dx) > Math.abs(dy) ? "horizontal" : "vertical"', script)
        self.assertIn('#view-persona{\n    max-height:none;\n    overflow:visible;', styles)

    def test_overview_layout_switch_is_visible_persistent_and_accessible(self) -> None:
        page = (ROOT / "pages" / "记忆面板" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "pages" / "记忆面板" / "app.css").read_text(encoding="utf-8")

        self.assertIn('id="overviewLayoutSwitch"', page)
        self.assertIn('role="radiogroup"', page)
        self.assertEqual(2, page.count('class="overview-layout-option"'))
        self.assertIn('data-overview-layout="standard"', page)
        self.assertIn('data-overview-layout="cinema"', page)
        self.assertIn("简洁管理", page)
        self.assertIn("放映馆界面", page)
        self.assertIn('aria-controls="standardOverview workspace"', page)
        self.assertIn('aria-controls="cinemaOverview workspace"', page)
        self.assertIn('role="radio"', page)
        self.assertIn('id="standardOverview"', page)
        self.assertIn('id="cinemaOverview"', page)
        self.assertIn('id="standardStats"', page)
        self.assertIn('id="standardRecentBuckets"', page)
        self.assertIn("memory_companion_overview_layout", page)
        self.assertLess(page.index("memory_companion_overview_layout"), page.index('rel="stylesheet"'))
        self.assertIn("function setOverviewLayout", script)
        self.assertIn("async function loadUiCapabilities", script)
        self.assertIn("function syncPersonalLayoutForUiMode", script)
        self.assertIn('UI_CONTRACT_VERSION = "memory.page.ui.v2"', script)
        self.assertIn("function renderStandardRecentBuckets", script)
        self.assertIn("state.stats", script)
        self.assertIn("state.buckets", script)
        self.assertIn('event.key === "ArrowLeft"', script)
        self.assertIn(':root[data-overview-layout="standard"] .projection-stage', styles)
        self.assertIn(".film-app.is-workspace .overview-layout-switch", styles)
        self.assertIn(':root[data-overview-layout="standard"] .film-app.is-workspace .object-rail', styles)
        self.assertIn(':root[data-overview-layout="standard"] .film-app.is-personal-memory .schedule-film', styles)
        self.assertIn("@media(max-width:760px)", styles)
        self.assertIn("app.js?v=1.10.5-ui-v1", page)

        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)), "记忆面板不能包含重复 HTML id")

    def test_memory_atom_and_audit_operations_are_reachable_from_ui(self) -> None:
        page = (ROOT / "pages" / "记忆面板" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="uiCompatibilityBanner"', page)
        self.assertIn('id="memoryAuditPreviewBtn"', page)
        self.assertIn('id="memoryAuditStatusBtn"', page)
        self.assertIn('name="validity_status"', script)
        self.assertIn('name="salience"', script)
        self.assertIn('name="durability"', script)
        self.assertIn('name="sensitivity"', script)
        self.assertIn('name="valid_from"', script)
        self.assertIn('name="valid_to"', script)
        self.assertIn('apiPost("/maintenance/audit/preview"', script)
        self.assertIn('apiPost("/thread/status"', script)

    def test_user_profile_and_private_memory_share_one_user_workspace(self) -> None:
        page = (ROOT / "pages" / "记忆面板" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")

        self.assertIn("用户档案与记忆", page)
        self.assertIn('data-overview-view="relations" data-user-memory-filter="private"', page)
        self.assertIn('id="userMemoryTitle"', page)
        self.assertIn('data-user-memory-filter="profile"', page)
        self.assertIn('data-user-memory-filter="private"', page)
        self.assertIn('if (view === "maintain")', script)
        self.assertIn('view = "relations"', script)
        self.assertIn('if (state.activeView === "relations") return "private"', script)
        self.assertIn('scopedMemoryParams("private", { limit: 180 })', script)
        self.assertIn('params.delete("session_id")', script)
        self.assertIn('正在读取画像详情...', script)
        self.assertIn('当前同步结果显示统一画像能力全部关闭', script)
        self.assertIn('.portrait-governance-detail, .portrait-governance-detail-slot', script)
        self.assertLess(
            script.index('${renderPortraitGovernanceDetail(state.portraitGovernanceDetail, state.portraitGovernanceLoading)}'),
            script.index('${renderPortraitProfileList(items)}', script.index('async function loadPortraitGovernance()')),
        )
        self.assertNotIn('id="clearCurrentPrivateMemoryBtn" class="danger subtle" type="button" disabled>清空当前用户</button>\n            </div>\n            <div id="privateMemoryList"', page)

    def test_relations_view_keeps_portrait_and_memory_sections_in_flow(self) -> None:
        styles = (ROOT / "pages" / "记忆面板" / "app.css").read_text(encoding="utf-8")

        self.assertIn(
            ".film-app.is-workspace:not(.is-personal-memory) #view-relations.is-active{\n"
            "  display:flex;\n"
            "  flex-direction:column;",
            styles,
        )
        self.assertIn(
            ".film-app.is-workspace:not(.is-personal-memory) #view-relations.is-active > #portraitGovernance{\n"
            "  overflow:visible;\n"
            "}",
            styles,
        )
        self.assertIn(
            ".film-app.is-workspace:not(.is-personal-memory) #view-relations.is-active > #relationList{\n"
            "  overflow:visible;\n"
            "}",
            styles,
        )


if __name__ == "__main__":
    unittest.main()
