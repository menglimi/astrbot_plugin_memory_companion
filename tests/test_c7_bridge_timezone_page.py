from __future__ import annotations

import inspect
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from core import bot_personal_contract
from core.bridge import MemoryCompanionBridge


ROOT = Path(__file__).resolve().parents[1]


class BridgeNegativeProbeTests(unittest.TestCase):
    def test_contract_failure_is_negative_cached_and_not_reprobed(self):
        bridge = MemoryCompanionBridge(object())
        with patch.object(
            bot_personal_contract,
            "contract_self_check",
            side_effect=[RuntimeError("private prompt must not escape"), []],
        ) as checker:
            first = bridge.probe_capability_snapshot()
            second = bridge.probe_capability_snapshot()

        self.assertEqual("negative", first["capability_state"])
        self.assertEqual("negative", first["state"])
        self.assertFalse(first["available"])
        self.assertEqual("contract_self_check_exception", first["error_code"])
        self.assertEqual(1, checker.call_count)
        self.assertEqual("negative", second["capability_state"])

    def test_negative_probe_expires_and_allows_recovery(self):
        bridge = MemoryCompanionBridge(object())
        with patch.object(bot_personal_contract, "contract_self_check", side_effect=RuntimeError("broken")):
            first = bridge.probe_capability_snapshot()
        self.assertEqual("negative", first["state"])

        bridge._capability_cache._negative_at = time.monotonic() - 61.0
        with patch.object(bot_personal_contract, "contract_self_check", return_value=[]):
            recovered = bridge.probe_capability_snapshot()
        self.assertEqual("available", recovered["state"])
        self.assertTrue(recovered["available"])


class C7StaticBoundaryTests(unittest.TestCase):
    def test_service_uses_configured_local_timezone_for_wall_clock_checks(self):
        source = (ROOT / "core" / "service.py").read_text(encoding="utf-8")
        self.assertIn('LOCAL_TZ = ZoneInfo("Asia/Shanghai")', source)
        self.assertIn("datetime.now(LOCAL_TZ)", source)
        self.assertNotIn("datetime.now()", source)

    def test_page_endpoints_return_real_errors_without_exception_text(self):
        source = (ROOT / "page_api.py").read_text(encoding="utf-8")
        for endpoint in ("timeline", "relations", "graph", "threads", "logs"):
            self.assertIn(f'self._err("{endpoint}_unavailable", 500)', source)
        self.assertNotIn('return self._ok({"items": []})', source)

    def test_frontend_transport_surfaces_http_and_page_api_errors(self):
        source = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        # 2.0.0 重写时知识图谱视图连同 renderContextPanelErrors 一起被移除，旧断言锚定
        # 的元素已不存在。等价契约仍是「HTTP 层失败必须抛出可见错误」「视图或子请求
        # 失败必须有显式错误出口，不能退化成静默空数据」，断言因此锚定到当前实现里
        # 承担该职责的请求层、视图层与子请求层三处代码。
        # 请求层：非 2xx 或业务 success=false 必须抛出，并带上 HTTP 状态码。
        self.assertIn("if (!response.ok || (data && data.success === false)) {", source)
        self.assertIn("error.status = response.status;", source)
        self.assertIn('if (data && data.status === "error") {', source)
        self.assertIn('throw new Error(data.message || data.error || "请求失败");', source)
        # 视图层：视图整体加载失败必须渲染可见错误，而不是空白。
        self.assertIn("这个视图没能加载出来", source)
        # 子请求层：作为上下文之一的请求失败时必须切到显式错误/不可用分支。
        self.assertIn('return card("互动协同不可用", "读取失败"', source)
        self.assertIn('if (!result) return { error: "权限矩阵读取失败" };', source)
        self.assertIn(
            'if (data.error) return card("权限拓扑", "", emptyState("读取失败", data.error));',
            source,
        )
        self.assertIn("if (result.available === false) {", source)
        self.assertIn("return { available: false, reason: compact(result.reason)", source)


if __name__ == "__main__":
    unittest.main()
