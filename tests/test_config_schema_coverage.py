from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from core.config import ConfigView
from core.coordination_status import build_p5_status


ROOT = Path(__file__).resolve().parents[1]


# ---- L5：每个 schema 键要么真有读取点，要么在 DEAD_KEYS 里显式登记 ---------
# 旧实现把 memory_injection.hook_request_budget_seconds 这类键直接写进「已覆盖」
# 的期望集合：键在 schema 里存在就算过，从不检查生产代码读不读它。现在真正的
# 白名单只剩 DEAD_KEYS：每个条目必须写明为什么留着，条目数量由
# EXPECTED_DEAD_KEY_COUNT 钉死，只许减不许增。
DEAD_KEYS: dict[str, str] = {
    # 目前没有已登记的已知死键：injection_cache_ttl_seconds 已随 L1 从 schema 删除。
}
EXPECTED_DEAD_KEY_COUNT = 0



def _schema_leaves() -> list[tuple[str, str]]:
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    return [(group, key) for group, body in schema.items() for key in body["items"]]


def _production_py_files() -> list[Path]:
    """生产 .py；排除测试、脚本与运行时目录，和 test_config_no_dead_keys 口径一致。"""
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*.py")):
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            continue
        if not rel.parts or rel.parts[0] in {"tests", "benchmarks", "scripts", "docs", "data"}:
            continue
        if "__pycache__" in rel.parts:
            continue
        files.append(path)
    return files


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """模块/类/函数的首行字符串不算引用（旧实现被注释和 docstring 喂饱过）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            ids.add(id(first.value))
    return ids


def _production_code_literals() -> set[str]:
    """生产 .py 可执行代码里的字符串字面量，外加 ConfigView.ALIASES 的键与目标。

    不逐个校验「这是不是一次 config 读取调用」，因为配置键在生产代码里有多条
    合法路径，逐个识别调用形态会漏报：
    - core/chat_import.py 的 value("hard_gap_minutes", ...) 走 helper，前缀
      "historical_chat_import." 在别处拼；
    - core/injection.py 的 _HUMANIZE_KEYS 映射表、core/service.py 的 P5 双 gate
      三元表达式把键名放在常量里，再由别的函数去读；
    - core/config.py 的 ConfigView.ALIASES 把旧名映射到 schema 新名。

    所以这里采「键名（完整名或裸名）必须作为字符串字面量出现在生产可执行代码
    里」这一条底线，并跳过 docstring；注释/文档/schema 本身不算。
    """
    literals: set[str] = set()
    for path in _production_py_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                literals.add(node.value)
    for old, targets in ConfigView.ALIASES.items():
        literals.add(old)
        literals.update(targets)
    return literals


class ConfigSchemaCoverageTests(unittest.TestCase):
    def test_runtime_controls_have_user_config_schema_entries(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        expected = {
            "retrieval": {"embedding_index_pending"},
            "source_semantic": {
                "enabled", "provider_id", "model_revision", "dimensions",
                "history_backfill_enabled", "sources_per_run", "provider_calls_per_run",
            },
            "memory_injection": {"hook_request_budget_seconds"},
            "visibility": {"hide_pending_review"},
            "maintenance_decay": {
                "memory_decay_scan_limit",
                "memory_decay_include_bot_self",
                "memory_decay_include_tool_memories",
            },
            "context_orchestration": {
                "contextual_query_expansion_enabled",
                "contextual_query_recent_events",
                "contextual_query_anchor_limit",
            },
            "livingmemory_migration": {"default_review_status"},
            "startup": {"background_grace_seconds"},
        }

        for section, keys in expected.items():
            with self.subTest(section=section):
                self.assertTrue(keys <= set(schema[section]["items"]))

        hook_budget = schema["memory_injection"]["items"]["hook_request_budget_seconds"]
        self.assertEqual("float", hook_budget["type"])
        self.assertEqual(1.0, hook_budget["default"])
        self.assertEqual(2000, schema["retrieval_advanced"]["items"]["embedding_timeout_ms"]["default"])
        self.assertEqual(2000, schema["retrieval_advanced"]["items"]["rerank_timeout_ms"]["default"])

    def test_unconsumed_controls_are_not_exposed(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertFalse(
            {
                "token_budget_per_person_day",
                "token_budget_global_day",
                "context_message_limit",
                "context_char_limit",
            }
            & set(schema["portrait"]["items"])
        )
        self.assertNotIn("memory_decay_max_access_count", schema["maintenance_decay"]["items"])

    def test_every_schema_leaf_is_read_or_explicitly_dead(self) -> None:
        """L5 核心：schema 里的每个键都必须有真实读取点，或者被显式认定为死键。

        这条替代了旧版「把键写进期望集合就算覆盖」的白名单式断言：
        memory_injection.hook_request_budget_seconds、injection_cache_ttl_seconds
        曾经就是这样被当成已覆盖的，实际上一个读错层级、一个生产零引用。
        """
        literals = _production_code_literals()
        leaves = _schema_leaves()
        leaf_names = {f"{group}.{key}" for group, key in leaves}
        covered: set[str] = set()
        for group, key in leaves:
            full = f"{group}.{key}"
            # 完整命名空间（config.get("group.key")）或裸键名（config_bool("key")）都算。
            if full in literals or key in literals:
                covered.add(full)
        unexplained = sorted(leaf_names - covered - set(DEAD_KEYS))
        self.assertEqual(
            [],
            unexplained,
            "这些配置键在 schema 里声明了，但生产代码没有对应的配置读取点，"
            "也不在 DEAD_KEYS 里登记为已知死键（面板上就是假开关）：\n  "
            + "\n  ".join(unexplained),
        )
        # 白名单只许减不许增：想加条目必须同时解释理由并调这个数字。
        self.assertEqual(EXPECTED_DEAD_KEY_COUNT, len(DEAD_KEYS))
        stale = sorted(set(DEAD_KEYS) - leaf_names)
        self.assertEqual([], stale, f"DEAD_KEYS 滚出了 schema，白名单该删：{stale}")

    def test_p5_status_reads_the_configured_namespaced_gates(self) -> None:
        status = build_p5_status(
            ConfigView(
                {
                    "private_companion_bridge": {
                        "enable_p5_b1_recall_gate": True,
                        "enable_p5_b1_bridge_gate": False,
                    }
                }
            )
        )
        self.assertEqual(
            {"health": "degraded", "mode": "partial", "enabled_count": 1, "total_count": 2, "reason_code": "partial_coverage"},
            status["attestation_read"],
        )
        self.assertEqual("contract_not_available", status["sink_boundary"]["reason_code"])
        self.assertEqual("contract_not_available", status["security_recovery"]["reason_code"])
