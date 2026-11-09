"""A1 / A5 / A12 / A13 / A14 的回归测试。

对应 REPORT.md §0.1 的缺陷条目：

* A1  main.py 只注册 GROUP_MESSAGE，私聊消息没有采集入口
* A5  core/astrbot_compat.py 的 manage_request_contexts 是零调用死码
* A12 main.py 的 memory_companion_query 对非 dict parameters 走死分支
* A13 metadata.yaml 的 astrbot_version 声明与代码实际下限不符
* A14 TextPart 只在 core/astrbot_compat.py 单点解析（公共面优先、内部模块兜底）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml
from packaging.specifiers import SpecifierSet

from astrbot.core.config.default import VERSION as ASTRBOT_VERSION
from astrbot.core.platform.message_type import MessageType
from astrbot.core.star.filter.event_message_type import EventMessageType, EventMessageTypeFilter
from astrbot.core.star.star_handler import star_handlers_registry

from core import astrbot_compat
from scripts.evaluate_recall_model import load_plugin


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = [ROOT / "main.py", *sorted((ROOT / "core").rglob("*.py"))]


def plugin_module():
    return load_plugin()


def _bound_plugin(service, **flags):
    """最小 self：只带真实钩子会用到的 service 和 _observe_message_event 绑定。"""

    plugin = plugin_module()
    bound = SimpleNamespace(service=service, **flags)
    bound._observe_message_event = plugin.MemoryCompanionPlugin._observe_message_event.__get__(bound)
    return bound


def _event_message_type_filters(handler) -> list[EventMessageTypeFilter]:
    full_name = f"{handler.__module__}_{handler.__name__}"
    metadata = star_handlers_registry.get_handler_by_full_name(full_name)
    assert metadata is not None, f"{full_name} 未注册到 star_handlers_registry"
    return [item for item in metadata.event_filters if isinstance(item, EventMessageTypeFilter)]


# --------------------------------------------------------------------------- A1


def test_private_message_hook_is_registered_for_friend_messages():
    """A1：私聊钩子必须真的被宿主注册，并且匹配 friend/private 消息。"""

    plugin = plugin_module()
    filters = _event_message_type_filters(plugin.MemoryCompanionPlugin.on_private_message)
    assert filters, "on_private_message 没有 event_message_type 过滤器"

    private = SimpleNamespace(get_message_type=lambda: MessageType.FRIEND_MESSAGE)
    group = SimpleNamespace(get_message_type=lambda: MessageType.GROUP_MESSAGE)
    assert any(item.filter(private, None) for item in filters), "私聊钩子不接受 FRIEND_MESSAGE"
    assert not any(item.filter(group, None) for item in filters), "私聊钩子不应该接群聊消息"

    registered = EventMessageType.PRIVATE_MESSAGE
    assert any(item.event_message_type & registered for item in filters)


def test_group_message_hook_still_registered_and_unchanged():
    """A1 回归：群聊钩子仍是 GROUP_MESSAGE，且不接受私聊消息。"""

    plugin = plugin_module()
    filters = _event_message_type_filters(plugin.MemoryCompanionPlugin.on_group_message)
    private = SimpleNamespace(get_message_type=lambda: MessageType.FRIEND_MESSAGE)
    group = SimpleNamespace(get_message_type=lambda: MessageType.GROUP_MESSAGE)
    assert any(item.filter(group, None) for item in filters)
    assert not any(item.filter(private, None) for item in filters)


class _RecordingService:
    """只记录调用顺序的假 service：用来证明钩子把事件交给了共用采集链路。"""

    def __init__(self) -> None:
        self.calls: list[object] = []

    async def initialize_database(self) -> bool:
        self.calls.append("initialize_database")
        return True

    async def handle_group_message(self, event) -> None:
        self.calls.append(("handle_group_message", event))


@pytest.mark.asyncio
async def test_private_hook_delegates_to_shared_observation_chain():
    """A1：私聊消息走同一条采集链路（service.handle_group_message）。"""

    plugin = plugin_module()
    service = _RecordingService()
    bound = _bound_plugin(service)
    event = SimpleNamespace(message_str="私聊内容")

    await plugin.MemoryCompanionPlugin.on_private_message(bound, event)

    assert service.calls == ["initialize_database", ("handle_group_message", event)]


@pytest.mark.asyncio
async def test_group_and_private_hooks_share_the_same_dispatch():
    """A1：两个钩子的调用序列完全一致，没有各写一份门槛逻辑。"""

    plugin = plugin_module()
    sequences = []
    for handler in (
        plugin.MemoryCompanionPlugin.on_group_message,
        plugin.MemoryCompanionPlugin.on_private_message,
    ):
        service = _RecordingService()
        event = SimpleNamespace(message_str="同一事件")
        await handler(_bound_plugin(service), event)
        sequences.append(service.calls)
    assert sequences[0] == sequences[1]
    assert len(sequences[0]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["_terminated", "_init_failed"])
async def test_message_hooks_stop_after_terminate(flag):
    """A1 回归：terminate/初始化失败后私聊钩子同样直接返回。"""

    plugin = plugin_module()
    service = _RecordingService()
    bound = _bound_plugin(service, **{flag: True})
    await plugin.MemoryCompanionPlugin.on_private_message(bound, SimpleNamespace())
    assert service.calls == []


@pytest.mark.asyncio
async def test_private_hook_survives_initialize_database_failure():
    """A1：数据库初始化失败时不抛异常、不进入采集链路。"""

    plugin = plugin_module()

    class _Failing(_RecordingService):
        async def initialize_database(self) -> bool:
            self.calls.append("initialize_database")
            return False

    service = _Failing()
    await plugin.MemoryCompanionPlugin.on_private_message(_bound_plugin(service), SimpleNamespace())
    assert service.calls == ["initialize_database"]


# -------------------------------------------------------------------------- A12


class _QueryService:
    """记录 query_for_model 的入参；tool_query 一旦被调用就说明死分支又回来了。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def query_for_model(self, event, operation, **parameters):
        self.calls.append((operation, parameters))
        return {"ok": True, "operation": operation, "parameters": parameters}

    async def tool_query(self, *args, **kwargs):  # pragma: no cover - 只在回归时触发
        raise AssertionError("A12 回归：非 dict parameters 又走了 tool_query 死分支")


async def _call_query_tool(parameters, operation="sources"):
    plugin = plugin_module()
    service = _QueryService()
    bound = SimpleNamespace(service=service)
    raw = await plugin.MemoryCompanionPlugin.memory_companion_query_tool(
        bound, SimpleNamespace(), operation=operation, parameters=parameters,
    )
    return service, json.loads(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        ({"terms": ["拿铁"]}, {"terms": ["拿铁"]}),
        ({"terms": ["拿铁"], "limit": 3}, {"terms": ["拿铁"], "limit": 3}),
        ('{"terms": ["拿铁"], "limit": 3}', {"terms": ["拿铁"], "limit": 3}),
        ('  {"terms": ["拿铁"]}  ', {"terms": ["拿铁"]}),
        (None, {}),
        ("", {}),
        ("   ", {}),
        ({}, {}),
    ],
)
async def test_query_tool_accepts_dict_json_string_and_none(parameters, expected):
    """A12：dict / JSON 字符串 / None 都归一成关键字参数。"""

    service, payload = await _call_query_tool(parameters)
    assert payload["ok"] is True, payload
    assert payload["parameters"] == expected
    assert service.calls == [("sources", expected)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameters",
    ["not json", "[1, 2]", "42", "null", 42, ["terms"], True],
)
async def test_query_tool_rejects_unusable_parameters_explicitly(parameters):
    """A12：无法归一的值直接给明确错误，不再把非 object 塞进请求校验。"""

    service, payload = await _call_query_tool(parameters)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_query_arguments"
    assert payload["operation"] == "sources"
    assert payload["hint"]
    assert service.calls == []


@pytest.mark.asyncio
async def test_query_tool_status_default_needs_no_parameters():
    """A12 回归：status 省略 parameters 时仍按默认 operation 走正常路径。"""

    service, payload = await _call_query_tool(None, operation="status")
    assert payload["ok"] is True
    assert service.calls == [("status", {})]


# --------------------------------------------------------------------------- A5


def test_dead_manage_request_contexts_is_gone():
    """A5：零调用的 manage_request_contexts 已删除，且仓库里没有残留引用。"""

    assert not hasattr(astrbot_compat, "manage_request_contexts")
    name = "manage_request" + "_contexts"
    offenders = [path.relative_to(ROOT).as_posix() for path in SOURCE_FILES if name in path.read_text(encoding="utf-8")]
    assert offenders == []


def test_strip_marked_request_text_still_handles_contexts():
    """A5 回归：真正在用的上下文清理入口没被误删。"""

    req = SimpleNamespace(
        prompt="用户原始请求",
        extra_user_content_parts=[],
        contexts=[{"role": "user", "content": "<!-- private_companion_state_v1 -->状态\n<!-- private_companion_state_end_v1 -->"}],
    )
    removed = astrbot_compat.remove_temp_text(
        req, "<!-- private_companion_state_v1 -->", "<!-- private_companion_state_end_v1 -->",
    )
    assert removed >= 1
    assert req.contexts == []


# -------------------------------------------------------------------------- A13


def test_metadata_declares_the_real_astrbot_floor():
    """A13：astrbot_version 必须是合法的 PEP 440 范围，且与 CI 的 astrbot>=4.27,<5 对齐。"""

    metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    specifier = metadata["astrbot_version"]
    assert isinstance(specifier, str)
    spec = SpecifierSet(specifier)  # 非法范围会在这里抛 InvalidSpecifier
    assert ASTRBOT_VERSION in spec, f"{ASTRBOT_VERSION} 不满足插件声明的 {specifier}"
    assert "4.22.0" not in spec, "旧的 >=4.22.0 下限没有依据（代码没有 4.22 兼容分支）"
    assert "5.0.0" not in spec, "必须排除 5.x，CI 只覆盖 astrbot>=4.27,<5"


def test_metadata_version_string_untouched():
    """A13 回归：只动 astrbot_version；版本号三处必须同一批 bump、互相一致。"""

    metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    plugin_version = re.search(
        r'PLUGIN_VERSION\s*=\s*"([^"]+)"', (ROOT / "main.py").read_text(encoding="utf-8")
    )
    assert plugin_version is not None
    assert metadata["version"] == plugin_version.group(1)


# -------------------------------------------------------------------------- A14


def _fake_module(name: str, **attributes) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def test_text_part_is_resolved_from_the_public_surface_first(monkeypatch):
    """A14：公共面导出 TextPart 后必须优先用它。"""

    public = type("PublicTextPart", (), {})
    internal = type("InternalTextPart", (), {})
    monkeypatch.setitem(sys.modules, "astrbot.api.message_components", _fake_module("astrbot.api.message_components", TextPart=public))
    monkeypatch.setitem(sys.modules, "astrbot.core.agent.message", _fake_module("astrbot.core.agent.message", TextPart=internal))
    assert astrbot_compat._resolve_text_part() is public


def test_text_part_falls_back_to_the_internal_module(monkeypatch):
    """A14：公共面没有 TextPart（4.29.3 现状）时回退内部模块。"""

    internal = type("InternalTextPart", (), {})
    monkeypatch.setitem(sys.modules, "astrbot.api.message_components", _fake_module("astrbot.api.message_components"))
    monkeypatch.setitem(sys.modules, "astrbot.core.agent.message", _fake_module("astrbot.core.agent.message", TextPart=internal))
    assert astrbot_compat._resolve_text_part() is internal


def test_text_part_is_none_when_both_surfaces_are_missing(monkeypatch):
    """A14：两条路径都没有时返回 None，由调用方降级而不是导入期崩溃。"""

    monkeypatch.setitem(sys.modules, "astrbot.api.message_components", _fake_module("astrbot.api.message_components"))
    monkeypatch.setitem(sys.modules, "astrbot.core.agent.message", _fake_module("astrbot.core.agent.message"))
    assert astrbot_compat._resolve_text_part() is None


def test_text_part_matches_the_module_level_symbol():
    """A14：模块级 TextPart 就是解析函数的结果（调用方仍可 patch 这个符号）。"""

    resolved = astrbot_compat._resolve_text_part()
    assert resolved is astrbot_compat.TextPart
    assert resolved is not None


def test_text_part_is_only_imported_in_the_compat_layer():
    """A14：其它模块不再直接 import 内部模块的 TextPart。"""

    offenders = []
    for path in SOURCE_FILES:
        text = path.read_text(encoding="utf-8")
        if "import TextPart" in text and path.name != "astrbot_compat.py":
            offenders.append(path.relative_to(ROOT).as_posix())
        if "astrbot.core.agent.message" in text and path.name != "astrbot_compat.py":
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
