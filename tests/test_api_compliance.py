"""API 合规回归：工具 docstring、配置读取、生命周期闸门与历史清理边界。

对应 REPORT.md：P0-6（工具参数被 docstring 解析吞掉/写错）、A3（预算键读错）、
A6（terminate 后入口守卫）、A7（initialize 失败降级）、A8（工具撤销不可逆）、
A4（历史清理越界）、A14（TextPart 导入路径）、群聊 remember 默认拒绝。
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import docstring_parser
import pytest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
PLUGIN_MODULE = "astrbot_plugin_memory_companion.main"

# 宿主只按 docstring 生成工具参数（star_handler.register_llm_tool），少写一个参数
# 模型就永远传不进来，所以这里把每个工具的完整参数集合钉死。
EXPECTED_TOOL_PARAMS = {
    "memory_companion_recall": {"query", "top_k"},
    "memory_companion_query": {"operation", "parameters"},
    "memory_companion_discover_sources": {"query", "terms", "start_at", "end_at", "limit"},
    "memory_companion_sources": {
        "action", "terms", "start_at", "end_at", "source_ref", "direction",
        "cursor", "limit", "excerpt_offset", "query_note",
    },
    "memory_companion_events": {"plan"},
    "memory_companion_navigate": {
        "action", "query", "cue", "tag", "memory_ids", "node_type", "limit",
    },
    "memory_companion_remember": {
        "content", "note_type", "confidence", "importance", "durability",
        "valid_from", "valid_to", "evidence_refs", "rationale",
    },
    "memory_companion_core_memory": {
        "action", "label", "content", "kind", "priority", "enabled",
    },
    "memory_companion_person_weight": {
        "action", "weight", "label", "address", "note", "rationale",
    },
    "memory_companion_note_create": {"title", "content"},
    "memory_companion_note_read": {"query", "limit"},
    "memory_companion_note_delete": {"memory_id", "title"},
}

ALLOWED_SCALAR_TYPES = {"string", "number", "object", "array", "boolean"}
PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _main_module():
    return importlib.import_module(PLUGIN_MODULE)


def _parse_main_ast():
    return ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))


def _decorators(node):
    return [dec.func if isinstance(dec, ast.Call) else dec for dec in node.decorator_list]


def _tool_name(node) -> str:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return node.name


def _tool_nodes():
    """按 AST 找出 main.py 里所有 @filter.llm_tool 函数，返回 (工具名, 函数节点)。"""
    found = []
    for cls in (node for node in _parse_main_ast().body if isinstance(node, ast.ClassDef)):
        for node in cls.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(isinstance(dec, ast.Attribute) and dec.attr == "llm_tool" for dec in _decorators(node)):
                found.append((_tool_name(node), node))
    return found


def _plugin_shell(config_raw: dict | None = None):
    from astrbot_plugin_memory_companion.core.config import ConfigView

    main = _main_module()
    obj = main.MemoryCompanionPlugin.__new__(main.MemoryCompanionPlugin)
    obj.service = SimpleNamespace(config=ConfigView(config_raw or {}))
    obj._terminated = False
    obj._init_failed = False
    return obj


def _node_by_tool(tool_name: str):
    for name, node in _tool_nodes():
        if name == tool_name:
            return node
    raise AssertionError(f"main.py 里找不到工具 {tool_name}")


def test_tool_count_and_names_are_stable():
    names = [name for name, _node in _tool_nodes()]
    assert len(names) == len(EXPECTED_TOOL_PARAMS)
    assert len(set(names)) == len(names)
    assert set(names) == set(EXPECTED_TOOL_PARAMS)


def test_llm_tool_docstrings_are_host_parseable():
    main = _main_module()
    parsed_total = 0
    for cls in (node for node in _parse_main_ast().body if isinstance(node, ast.ClassDef)):
        for node in cls.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(dec, ast.Attribute) and dec.attr == "llm_tool" for dec in _decorators(node)):
                continue
            doc = ast.get_docstring(node)
            assert doc, f"{node.name} 缺少 docstring，宿主会注册成零参数工具"
            parsed = docstring_parser.parse(doc)
            assert (parsed.short_description or "").strip(), f"{node.name} 缺工具描述"
            # 宿主解析的是真实可调用对象的 __doc__；它必须与源码里的 docstring 等价，
            # 否则装饰器包装会让注册到宿主的参数漂移。
            runtime_doc = inspect.unwrap(getattr(getattr(main, cls.name), node.name)).__doc__ or ""
            assert inspect.cleandoc(runtime_doc) == doc, f"{node.name} 源码与运行时 docstring 不一致"
            runtime_parsed = docstring_parser.parse(runtime_doc)
            assert [p.arg_name for p in runtime_parsed.params] == [p.arg_name for p in parsed.params], (
                f"{node.name} 运行时解析出的参数与源码不一致"
            )
            parsed_total += len(parsed.params)
    assert parsed_total > 0


def test_llm_tool_params_match_expected_sets():
    main = _main_module()
    for node in [item for cls in (n for n in _parse_main_ast().body if isinstance(n, ast.ClassDef)) for item in cls.body
                 if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and any(isinstance(dec, ast.Attribute) and dec.attr == "llm_tool" for dec in _decorators(item))]:
        tool_name = _tool_name(node)
        assert tool_name in EXPECTED_TOOL_PARAMS, f"{node.name} 没有登记预期参数集合"
        parsed = docstring_parser.parse(ast.get_docstring(node) or "")
        param_names = [param.arg_name for param in parsed.params]
        assert len(param_names) == len(set(param_names)), f"{tool_name} 参数名重复: {param_names}"
        for param in parsed.params:
            name = param.arg_name
            assert "/" not in name, f"{tool_name}: 参数 {name!r} 被斜杠合并，宿主会生成假参数"
            assert " " not in name.strip(), f"{tool_name}: 参数 {name!r} 含空格"
            assert PARAM_NAME_RE.match(name), f"{tool_name}: 参数名 {name!r} 不是标准 snake_case"
            assert param.type_name, f"{tool_name}: 参数 {name!r} 缺类型，宿主注册会 ValueError"
            base_type = param.type_name.split("[", 1)[0]
            assert base_type in ALLOWED_SCALAR_TYPES, f"{tool_name}: 参数 {name!r} 类型 {param.type_name!r} 不受支持"
            assert (param.description or "").strip(), f"{tool_name}: 参数 {name!r} 缺描述"
        assert set(param_names) == EXPECTED_TOOL_PARAMS[tool_name], f"{tool_name} 参数集合与签名约定不一致"
        # 文档参数必须能被真实签名接住（Event 与 self 由宿主注入，**kwargs 工具除外）。
        signature = inspect.signature(inspect.unwrap(getattr(main.MemoryCompanionPlugin, node.name)))
        declared = {name for name in signature.parameters if name not in ("self", "event")}
        takes_kwargs = any(
            param.kind is param.VAR_KEYWORD for param in signature.parameters.values()
        )
        if takes_kwargs:
            # **kwargs 工具的参数名不在签名里，docstring 是宿主唯一来源，无需再校验。
            continue
        assert set(param_names) <= declared


def test_remember_keeps_four_independent_retention_params():
    """P0-6 核心：confidence/importance/valid_from/valid_to 必须各自独立解析。"""
    node = _node_by_tool("memory_companion_remember")
    parsed = docstring_parser.parse(ast.get_docstring(node) or "")
    params = {param.arg_name: param for param in parsed.params}
    assert {"confidence", "importance", "valid_from", "valid_to"} <= set(params)
    assert params["confidence"].type_name == "number"
    assert params["importance"].type_name == "number"
    assert params["valid_from"].type_name == "string"
    assert params["valid_to"].type_name == "string"
    assert not any("/" in name for name in params)
    assert len(params) == 9


def test_discover_sources_declares_query_param():
    """discover_sources 曾经整段缺 Args，宿主注册成零参数工具。"""
    node = _node_by_tool("memory_companion_discover_sources")
    parsed = docstring_parser.parse(ast.get_docstring(node) or "")
    assert [param.arg_name for param in parsed.params] == ["query", "terms", "start_at", "end_at", "limit"]


def test_every_llm_tool_entry_has_lifecycle_gate():
    """A6/A7：terminate 或 initialize 失败后，工具入口必须能提前返回。"""
    for tool_name, node in _tool_nodes():
        gated = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "_tool_gate"
            for child in ast.walk(node)
        )
        assert gated, f"{tool_name} 入口没有 _tool_gate() 守卫"


def test_no_private_tool_manager_mutation_left():
    """A8：撤销工具注册不可逆，main.py 里不能再出现这类调用。"""
    tree = _parse_main_ast()
    banned = [
        call.func.attr
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call))
        if isinstance(call.func, ast.Attribute) and call.func.attr in {"remove_func", "remove_tool"}
    ]
    assert not banned, f"main.py 仍在撤销工具注册（不可逆）: {banned}"
    assert any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "_log_disabled_tools"
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call))
    ), "main.py 缺少按配置记录禁用工具的日志入口"


def test_tool_gate_reports_terminated_and_init_failed():
    plugin = _plugin_shell()
    assert plugin._tool_gate() is None
    plugin._terminated = True
    value = json.loads(plugin._tool_gate())
    assert value["ok"] is False and value["code"] == "plugin_terminated"
    plugin._terminated = False
    plugin._init_failed = True
    value = json.loads(plugin._tool_gate())
    assert value["ok"] is False and value["code"] == "plugin_init_failed"


def test_terminated_property_reflects_flag():
    plugin = _plugin_shell()
    assert plugin.terminated is False
    plugin._terminated = True
    assert plugin.terminated is True


def test_budget_reads_nested_key_then_legacy_fallback():
    """A3：schema 里在 memory_injection 段下，读顶层旧键会恒为 0。"""
    nested = _plugin_shell({"memory_injection": {"hook_request_budget_seconds": 2.5}})
    assert nested._hook_request_budget_seconds() == pytest.approx(2.5)
    legacy = _plugin_shell({"hook_request_budget_seconds": 1.5})
    assert legacy._hook_request_budget_seconds() == pytest.approx(1.5)
    both = _plugin_shell({
        "memory_injection": {"hook_request_budget_seconds": 3},
        "hook_request_budget_seconds": 1.5,
    })
    assert both._hook_request_budget_seconds() == pytest.approx(3.0)
    assert _plugin_shell({})._hook_request_budget_seconds() == 0.0


@pytest.mark.asyncio
async def test_initialize_failure_degrades_instead_of_raising():
    """A7：initialize 抛异常时只降级，不能把宿主插件加载拖崩。"""
    plugin = _plugin_shell({})
    plugin.service.initialize_database = AsyncMock(side_effect=RuntimeError("db boom"))
    await plugin.initialize()  # 不抛异常
    assert plugin._init_failed is True


@pytest.mark.asyncio
async def test_initialize_early_return_is_not_marked_failed():
    plugin = _plugin_shell({})
    plugin.service.initialize_database = AsyncMock(return_value=False)
    await plugin.initialize()
    assert plugin._init_failed is False


@pytest.mark.asyncio
async def test_group_remember_is_rejected_by_default():
    """群聊写入：默认拒绝，只回结构化错误；开启开关后才真正落库。"""
    plugin = _plugin_shell({"memory_tools": {"enable_remember_tool": True}})
    plugin.service.tool_remember = AsyncMock(return_value={"ok": True})
    handler = inspect.unwrap(_main_module().MemoryCompanionPlugin.memory_companion_remember_tool)

    event = SimpleNamespace(get_group_id=lambda: "123456")
    value = json.loads(await handler(plugin, event, content="喜欢下雨天"))
    assert value == {
        "ok": False,
        "code": "group_remember_disabled",
        "message": "群聊里不主动记，私聊再说",
    }
    plugin.service.tool_remember.assert_not_awaited()

    allowed = _plugin_shell({
        "memory_tools": {"enable_remember_tool": True, "allow_group_remember": True},
    })
    allowed.service.tool_remember = AsyncMock(return_value={"ok": True})
    value = json.loads(await handler(allowed, event, content="喜欢下雨天"))
    assert value["ok"] is True
    allowed.service.tool_remember.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_remember_still_writes():
    plugin = _plugin_shell({"memory_tools": {"enable_remember_tool": True}})
    plugin.service.tool_remember = AsyncMock(return_value={"ok": True})
    handler = inspect.unwrap(_main_module().MemoryCompanionPlugin.memory_companion_remember_tool)
    value = json.loads(await handler(plugin, SimpleNamespace(get_group_id=lambda: None), content="喜欢下雨天"))
    assert value["ok"] is True
    plugin.service.tool_remember.assert_awaited_once()


def test_sanitize_request_history_defaults_to_no_touch():
    """A4：默认不动用户/宿主历史，连含 send_message_to_user 的行也不删。"""
    from astrbot_plugin_memory_companion.core import astrbot_compat

    user_text = "用户说：今天下雨了"
    foreign = {"role": "system", "content": "【内在约束】别的插件的约束\n正常一行"}
    host_line = "host log: send_message_to_user failed"
    req = SimpleNamespace(contexts=[user_text, foreign, host_line])
    result = astrbot_compat.sanitize_request_history(req)
    assert result == {"before": 0, "after": 0, "removed": 0, "cleaned": 0}
    assert req.contexts == [user_text, foreign, host_line]


def test_sanitize_request_history_only_touches_own_fragments():
    """开启后也只清带 private_companion 标记/临时标记的条目。"""
    from astrbot_plugin_memory_companion.core import astrbot_compat

    user_text = "用户说：今天下雨了"
    foreign = {"role": "system", "content": "【内在约束】别的插件的约束"}
    own = {
        "role": "user",
        "content": "<!-- private_companion_turn_fragments_start -->注入<!-- private_companion_turn_fragments_end -->",
    }
    req = SimpleNamespace(contexts=[user_text, foreign, own])
    result = astrbot_compat.sanitize_request_history(req, clean_proactive_guidance=True)
    assert result["removed"] == 1
    assert req.contexts[0] is user_text
    assert req.contexts[1] is foreign
    assert len(req.contexts) == 2


def test_textpart_import_converges_to_one_place():
    """A14：TextPart 只从 core.astrbot_compat 取，优先公共面、回退内部模块。"""
    from astrbot_plugin_memory_companion.core import astrbot_compat

    part = astrbot_compat.TextPart
    if part is None:
        pytest.skip("宿主未提供 TextPart，保持旧版兼容回退")
    try:
        from astrbot.api.message_components import TextPart as public_part
    except ImportError:
        public_part = None
    from astrbot.core.agent.message import TextPart as internal_part

    assert part is public_part or part is internal_part
