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


if __name__ == "__main__":
    unittest.main()
