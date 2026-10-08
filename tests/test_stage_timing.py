"""阶段计时诊断（memory_injection.debug_stage_timing_enabled）单元测试。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.service import _HookStageTimer


class HookStageTimerTests(unittest.TestCase):
    def test_disabled_timer_is_noop(self):
        timer = _HookStageTimer(False)
        timer.mark("a")
        timer.mark("b")
        self.assertEqual(timer.summary(), "no_stages")
        self.assertEqual(timer.total_ms(), 0)
        self.assertFalse(timer.enabled)

    def test_enabled_timer_records_marks(self):
        # Inject the nanosecond clock so rounding behavior is deterministic.
        with patch(
            "astrbot_plugin_memory_companion.core.service.time.perf_counter_ns",
            side_effect=[1_000_000_000, 1_000_400_000, 5_999_800_000],
        ):
            timer = _HookStageTimer(True)
            timer.mark("first")
            timer.mark("second")
        summary = timer.summary()
        self.assertIn("first=", summary)
        self.assertIn("second=", summary)
        self.assertEqual("first=0ms second=4999ms", summary)
        self.assertEqual(4999, timer.total_ms())

    def test_enabled_timer_zero_initial_state(self):
        timer = _HookStageTimer(True)
        self.assertEqual(timer.summary(), "no_stages")
        self.assertEqual(timer.total_ms(), 0)

    def test_schema_declares_flag_default_false(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        items = schema["memory_injection"]["items"]
        self.assertIn("debug_stage_timing_enabled", items)
        flag = items["debug_stage_timing_enabled"]
        self.assertEqual(flag["type"], "bool")
        self.assertFalse(flag["default"])


if __name__ == "__main__":
    unittest.main()
