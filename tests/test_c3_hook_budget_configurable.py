"""C3：注入钩子预算必须真的可配置。

旧实现把上限焊死在 1 秒，配置项填 3 也只会得到 1，用户调整预算形同虚设。
这些用例钉住三件事：可配置区间确实生效、非法值仍回落到默认值、schema 与代码
的上限/默认值/步长必须一致（避免文档与实现再次漂移）。
"""
from __future__ import annotations

import json
import math
import unittest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import latency as latency_module
from astrbot_plugin_memory_companion.core.latency import (
    bounded_memory_hook_budget_seconds,
)


# 这些名字是 C3 引入的；用 getattr 取，保证本用例在未修复代码上会以
# 行为断言失败（而不是收集期 ImportError），复现证据才可信。
MIN_MEMORY_HOOK_BUDGET_SECONDS = getattr(
    latency_module, "MIN_MEMORY_HOOK_BUDGET_SECONDS", 0.0
)
DEFAULT_MEMORY_HOOK_BUDGET_SECONDS = getattr(
    latency_module, "DEFAULT_MEMORY_HOOK_BUDGET_SECONDS", 1.0
)
MAX_MEMORY_HOOK_BUDGET_SECONDS = getattr(
    latency_module, "MAX_MEMORY_HOOK_BUDGET_SECONDS", 1.0
)


class HookBudgetConfigurabilityTests(unittest.TestCase):
    def test_configured_budget_above_one_second_is_honoured(self) -> None:
        """The reported defect: a configured 3s could never take effect."""
        self.assertEqual(3.0, bounded_memory_hook_budget_seconds(3))
        self.assertEqual(2.0, bounded_memory_hook_budget_seconds(2.0))
        self.assertGreater(
            bounded_memory_hook_budget_seconds(3), DEFAULT_MEMORY_HOOK_BUDGET_SECONDS
        )

    def test_configured_budget_below_one_second_is_still_honoured(self) -> None:
        self.assertEqual(0.1, bounded_memory_hook_budget_seconds(0.1))
        self.assertEqual(0.5, bounded_memory_hook_budget_seconds(0.5))
        self.assertEqual(0.75, bounded_memory_hook_budget_seconds("0.75"))
        self.assertEqual(0.1, bounded_memory_hook_budget_seconds(0.01))

    def test_values_above_the_safety_cap_are_clamped(self) -> None:
        """The cap stays: local failure must never hold a reply indefinitely."""
        self.assertEqual(5.0, bounded_memory_hook_budget_seconds(5.0))
        self.assertEqual(8.0, bounded_memory_hook_budget_seconds(8.0))
        self.assertEqual(MAX_MEMORY_HOOK_BUDGET_SECONDS, bounded_memory_hook_budget_seconds(30))
        self.assertEqual(MAX_MEMORY_HOOK_BUDGET_SECONDS, bounded_memory_hook_budget_seconds(8.5))
        self.assertLessEqual(MAX_MEMORY_HOOK_BUDGET_SECONDS, 8.0)

    def test_non_finite_values_are_treated_as_unset(self) -> None:
        """``inf`` is not a usable duration, so it falls back like any invalid value."""
        for value in (math.inf, -math.inf, float("nan")):
            with self.subTest(value=value):
                self.assertEqual(
                    DEFAULT_MEMORY_HOOK_BUDGET_SECONDS,
                    bounded_memory_hook_budget_seconds(value),
                )

    def test_invalid_boolean_or_non_positive_values_fall_back_to_the_default(self) -> None:
        for value in (True, False, 0, -1, -0.5, None, "", "abc", float("nan"), object()):
            with self.subTest(value=value):
                self.assertEqual(
                    DEFAULT_MEMORY_HOOK_BUDGET_SECONDS,
                    bounded_memory_hook_budget_seconds(value),
                )

    def test_default_is_inside_the_published_range(self) -> None:
        self.assertGreater(DEFAULT_MEMORY_HOOK_BUDGET_SECONDS, 0)
        self.assertGreaterEqual(DEFAULT_MEMORY_HOOK_BUDGET_SECONDS, MIN_MEMORY_HOOK_BUDGET_SECONDS)
        self.assertLessEqual(DEFAULT_MEMORY_HOOK_BUDGET_SECONDS, MAX_MEMORY_HOOK_BUDGET_SECONDS)

    def test_schema_matches_the_code_cap_and_default(self) -> None:
        """The schema used to advertise 10s while the code capped at 1s."""
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        entry = schema["memory_injection"]["items"]["hook_request_budget_seconds"]

        self.assertEqual("float", entry["type"])
        self.assertEqual(DEFAULT_MEMORY_HOOK_BUDGET_SECONDS, entry["default"])
        self.assertEqual(0.0, entry["min"])
        self.assertEqual(8.0, entry["max"])
        self.assertEqual({"min": 0.0, "max": 8.0, "step": 0.1}, entry["slider"])
        self.assertLessEqual(entry["min"], DEFAULT_MEMORY_HOOK_BUDGET_SECONDS)
        self.assertIn(str(MAX_MEMORY_HOOK_BUDGET_SECONDS).rstrip("0").rstrip("."), entry["hint"])

        timing_hint = schema["memory_injection"]["items"]["debug_stage_timing_enabled"]["hint"]
        self.assertIn("来源采集", timing_hint)

    def test_schema_hint_states_the_exclusions_and_the_default(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        hint = schema["memory_injection"]["items"]["hook_request_budget_seconds"]["hint"]

        self.assertIn("模型调用等待", hint)
        self.assertIn("默认", hint)
        # Fail-safe semantics must stay documented, not turned into "raise it".
        self.assertIn("放行", hint)


if __name__ == "__main__":
    unittest.main()
