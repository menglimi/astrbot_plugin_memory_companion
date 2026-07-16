from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PanelRegressionTests(unittest.TestCase):
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
        self.assertIn("function previewQQHistoryImport", script)
        self.assertIn('{ id: "conversation-import", label: "历史聊天导入"', script)
        self.assertIn('section === "conversation-import"', script)
        self.assertIn('apiGet("/conversation-import/qq/capabilities")', script)
        self.assertIn('apiPost("/conversation-import/qq/preview"', script)
        self.assertIn("function historicalChatValidationMessage", script)
        self.assertIn('roles.filter((role) => role === "bot").length !== 1', script)
        self.assertIn("historicalChatIdentityConfirmed", script)
        self.assertNotIn('$("#chatEntity"', script)
        self.assertIn("min-height:44px", styles)
        self.assertIn(".chat-import-stage-track", styles)
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
        self.assertIn("app.css?v=20260716-album-full", page)


if __name__ == "__main__":
    unittest.main()
