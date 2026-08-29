from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.explicit_memory_action import (
    explicit_recall_query_from_text,
    explicit_remember_content_from_text,
    handle_explicit_memory_action,
    request_tool_names,
)


class _Tool:
    def __init__(self, name: str):
        self.name = name


class _ToolSet:
    def __init__(self, *names: str):
        self.tools = [_Tool(name) for name in names]

    def names(self):
        return [tool.name for tool in self.tools]

    def remove_tool(self, name: str) -> None:
        self.tools = [tool for tool in self.tools if tool.name != name]


class _Config:
    def bool(self, path: str, default: bool = False) -> bool:
        return True if path == "memory_tools.enable_remember_tool" else default


class ExplicitMemoryActionTests(unittest.IsolatedAsyncioTestCase):
    def test_public_memory_tools_have_explicit_arguments(self) -> None:
        module = ast.parse(
            (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        )
        methods = {
            node.name: node
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in ("memory_companion_recall_tool", "memory_companion_remember_tool"):
            method = methods[name]
            self.assertIsNone(method.args.kwarg, name)
            self.assertGreaterEqual(len(method.args.args), 3, name)

    def test_parser_accepts_explicit_commands_and_rejects_negation(self) -> None:
        self.assertEqual(
            "我的验收口令是琥珀云-C9047。",
            explicit_remember_content_from_text(
                "请把下面内容保存到长期记忆：我的验收口令是琥珀云-C9047。"
                "本轮必须调用 memory_companion_remember；只有工具返回 ok=true 后才能说保存成功。"
            ),
        )
        self.assertEqual("", explicit_remember_content_from_text("不要记住我的口令"))
        self.assertTrue(explicit_recall_query_from_text("请从长期记忆回忆我的验收口令。"))

    async def test_explicit_save_is_local_idempotent_and_removes_only_remember_tool(self) -> None:
        event = SimpleNamespace(message_str="请记住我的验收口令是琥珀云-C9047")
        req = SimpleNamespace(
            func_tool=_ToolSet(
                "memory_companion_remember",
                "memory_companion_recall",
                "safe_tool",
            ),
            prompt="原始请求",
            extra_user_content_parts=[],
        )
        service = SimpleNamespace(
            config=_Config(),
            tool_remember=AsyncMock(return_value={"ok": True, "memory_id": "hidden"}),
        )

        first = await handle_explicit_memory_action(service=service, event=event, req=req)
        second = await handle_explicit_memory_action(service=service, event=event, req=req)

        self.assertEqual(first, second)
        service.tool_remember.assert_awaited_once_with(
            event,
            "我的验收口令是琥珀云-C9047",
            note_type="memory",
        )
        self.assertEqual(
            ["memory_companion_recall", "safe_tool"],
            request_tool_names(req.func_tool),
        )
        self.assertEqual("saved", first["code"])
        self.assertNotIn("hidden", str(first))


if __name__ == "__main__":
    unittest.main()
