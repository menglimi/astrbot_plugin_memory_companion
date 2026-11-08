"""LLM 工具的参数名必须是 provider 能接受的键名。

AstrBot 解析 docstring 时把 ``Args:`` 里的 ``name(type):`` **原样**当成属性名
（`astrbot/core/star/register/star_handler.py` 的 docstring 解析）。所以
``confidence/importance(number): ...`` 这种「斜杠合并」写法会生成带 ``/`` 的
属性，Anthropic 系 provider 的属性名正则 ``^[a-zA-Z0-9_.-]{1,64}$`` 不认，
带该工具的整轮请求直接 400。

这层约束只能在 docstring 上守：插件没有机会改写 docstring 解析出来的属性名。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from docstring_parser import parse


PLUGIN_MAIN = Path(__file__).parents[1] / "main.py"
PROPERTY_NAME = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def _tool_docstrings():
    tree = ast.parse(PLUGIN_MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if docstring and "Args:" in docstring:
            yield node.name, docstring


TOOLS = list(_tool_docstrings())


def test_docstring_scan_covers_the_tool_set():
    assert len(TOOLS) >= 8


@pytest.mark.parametrize("name,docstring", TOOLS, ids=[name for name, _ in TOOLS])
def test_docstring_parameter_names_are_provider_safe(name, docstring):
    invalid = [param.arg_name for param in parse(docstring).params
               if not PROPERTY_NAME.match(param.arg_name or "")]

    assert invalid == [], f"{name} 的参数名会被 provider 拒收: {invalid}"


def test_remember_tool_exposes_split_parameter_names():
    name, docstring = next(item for item in TOOLS if item[0] == "memory_companion_remember_tool")
    names = [param.arg_name for param in parse(docstring).params]

    assert "confidence" in names and "importance" in names
    assert "valid_from" in names and "valid_to" in names
    assert not any("/" in param for param in names)
