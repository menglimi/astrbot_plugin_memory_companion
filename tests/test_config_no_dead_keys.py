"""每一个配置项都必须在代码里真的有用途。

用户的原话是「不只看绿和不绿，要看每一个开关每一个功能有没有对应的能用的，
他用不用得上」。这条比「有没有被读」还严格一点，但先解决最要命的一类：
**声明了却全仓库零引用的假开关**。

已知被这条抓住过的：

- ``portrait.context_char_limit`` / ``context_message_limit``
- ``portrait.token_budget_per_person_day`` / ``token_budget_global_day``
  四个键在 ``.py`` / ``.js`` 里一次都没出现过，面板上却摆着四个滑块。
- ``private_companion_bridge.preserve_external_prompt_context``
  只在 ``page_api`` 的配置回显里出现过一次，控不住任何行为；
  它 hint 描述的那套清理其实由 ``clean_proactive_history`` 实现。

## 这条检查抓不到什么（必须说清楚）

它只认「字面量出现」。所以下面两类会漏：

1. **配置回显**：``page_api._schema_config_values()`` 遍历 schema 本身，
   对每个叶子调一次取值——那是给面板显示当前值用的，不是行为控制。
2. **跨函数的数据流黑洞**：读出来的值传给了一个自己不消费它的下游函数。
   静态判断不出来。

动态拼接的键（f-string 拼出来的）由 ``DYNAMIC_FAMILIES`` 显式列出展开依据，
不靠猜。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "_conf_schema.json"

# 会被 f-string / 常量元组拼出来的键。这些展开依据写在注释里，别改成「看起来像」
# 的东西——这份清单错一条，整条检查就失去意义了。
DYNAMIC_FAMILIES: dict[str, tuple[str, ...]] = {
    "scope_control": (
        # core/service.py: config_bool(f"scope_control.{scope}_{feature}_enabled")
        # 展开为 {private,group} × {capture,recall,topology} 共 6 项
        "private_capture_enabled", "private_recall_enabled", "private_topology_enabled",
        "group_capture_enabled", "group_recall_enabled", "group_topology_enabled",
    ),
    "conversation_memory_advanced": (
        # core/service.py: _context_bool/_context_int(f"conversation_memory.{key}")
        # 经 core/config.py 的 ALIASES 落到 *_advanced，共 16 项
        "cross_window_group_to_private_enabled", "cross_window_private_to_group_enabled",
        "cross_window_recent_continuity_enabled", "cross_window_recent_event_limit",
        "cross_window_recent_minutes", "group_actor_relevance_guard_enabled",
        "low_information_gap_minutes", "low_information_guard_enabled",
        "recent_events_for_followup", "recent_fact_guard_enabled",
        "recent_fact_guard_event_limit", "recent_fact_guard_hours",
        "recent_fact_guard_max_items", "suppress_memory_on_low_information",
        "suppress_memory_on_topic_shift", "time_window_timeline_limit",
        "topic_shift_guard_enabled", "topic_shift_guard_recent_events",
    ),
    "historical_chat_import": (
        # core/chat_import.py / core/qq_history.py: f"historical_chat_import.{key}"
        "detail_package_chars", "hard_gap_minutes", "max_retries", "max_segment_chars",
        "max_turns", "merge_seconds", "package_chars", "qq_max_messages", "qq_max_pages",
        "qq_max_range_days", "qq_page_size", "qq_request_timeout_seconds",
        "soft_gap_minutes",
    ),
    "memory_summary": (
        # core/service.py: _provider_attempts(f"{prefix}.{provider_key}")
        "provider_id", "fallback_provider_id", "private_provider_id",
        "private_fallback_provider_id", "group_provider_id", "group_fallback_provider_id",
    ),
    "private_companion_bridge": (
        # core/service.py: _p5_gate_enabled 三元表达式
        "enable_p5_b1_recall_gate", "enable_p5_b1_bridge_gate",
    ),
    "maintenance_decay": (
        # 代码读旧名 maintenance.memory_decay_*，由 core/config.py 的 ALIASES 落到本组
        "memory_decay_after_days", "memory_decay_idle_days", "memory_decay_max_candidates",
        "memory_decay_max_groups", "memory_decay_max_importance_percent",
        "memory_decay_max_items_per_summary", "memory_decay_min_items_per_summary",
        "memory_decay_score_threshold_percent", "memory_decay_summary_chars",
        "memory_decay_summary_input_chars",
    ),
    "retrieval_advanced": (
        # 代码读旧名 retrieval.embedding_*，由 ALIASES 落到本组
        "embedding_backfill_batch_size", "embedding_backfill_enabled",
        "embedding_backfill_interval_seconds", "embedding_candidate_limit",
        "embedding_max_text_chars", "embedding_score_threshold", "embedding_timeout_ms",
        "embedding_top_k", "embedding_weight", "current_window_candidate_limit",
        "keyword_fallback_min_fts_candidates", "rerank_timeout_ms",
    ),
    "context_orchestration_advanced": (
        # 代码读旧名 context_orchestration.*，由 ALIASES 落到本组
        "conversation_summary_limit", "current_window_limit", "intent_max_chars",
        "self_timeline_limit", "stable_memory_limit", "user_profile_limit",
    ),
}


def _leaf_keys() -> list[tuple[str, str]]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for group, body in schema.items():
        for key in body["items"]:
            out.append((group, key))
    return out


def _code_corpus() -> str:
    """所有非测试的 .py 与面板 .js/.html/.css 拼成一个大字符串。"""
    parts: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.parts
        if "__pycache__" in rel or ".git" in rel or rel[0] in {"tests", "benchmarks", "scripts", "docs"}:
            continue
        if path.suffix in {".py", ".js", ".html", ".css"}:
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                continue
    return "\n".join(parts)


class NoDeadConfigKeysTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.leaves = _leaf_keys()
        cls.corpus = _code_corpus()
        dynamic = {key for names in DYNAMIC_FAMILIES.values() for key in names}

    def test_schema_leaf_count_is_sane(self) -> None:
        """防「清单本身写坏了」——比值不对会让下面所有判断失去意义。"""
        self.assertGreater(len(self.leaves), 150, "叶子项数量异常，检查脚本本身")
        for group, keys in DYNAMIC_FAMILIES.items():
            declared = {k for g, k in self.leaves if g == group} | {
                k for g, k in self.leaves if k in keys and g != group
            }
            unknown = [k for k in keys if k not in {x[1] for x in self.leaves}]
            self.assertEqual([], unknown, f"{group} 的动态展开清单里有 schema 不存在的键")

    def test_no_declared_key_is_entirely_unreferenced(self) -> None:
        """核心断言：声明了却全仓库零字面量引用 = 假开关。"""
        dead: list[str] = []
        for group, key in self.leaves:
            if f'"{group}.{key}"' in self.corpus or f"'{group}.{key}'" in self.corpus:
                continue
            if f'"{key}"' in self.corpus or f"'{key}'" in self.corpus:
                continue
            # 动态拼接的键：只要展开清单里有它，且那个片段在代码里出现过
            if key in DYNAMIC_FAMILIES.get(group, ()):
                if any(f'"{k}"' in self.corpus for k in DYNAMIC_FAMILIES[group]):
                    continue
            dead.append(f"{group}.{key}")
        self.assertEqual(
            [], dead,
            "这些配置项全仓库没有任何引用，面板上却摆着控件：\n  " + "\n  ".join(dead),
        )


if __name__ == "__main__":
    unittest.main()
