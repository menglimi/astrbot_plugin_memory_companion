"""C4（注入内部）：memory_injection 内部的阶段拆分必须可观测。

``test_c4_hook_stage_split.py`` 钉住 ``capture.incoming`` 与注入之外的阶段；这里补
注入内部：guards / intent / retrieve / compose / publish 必须各自打点，否则只看到一段
``inject=Nms`` 仍然无法判断时间花在哪一层。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.service import (
    MemoryCompanionService,
    _HookStageTimer,
)


def context(**changes) -> SessionContext:
    return replace(
        SessionContext(
            scope="private",
            platform="qq",
            session_id="qq:FriendMessage:user",
            user_id="user",
            bot_id="bot",
            persona_id="persona",
            message_id="message-2",
            message_text="我之前说错了，我喜欢的是清淡口味。",
        ),
        **changes,
    )


def record(**changes) -> MemoryRecord:
    return replace(
        MemoryRecord(
            id="old",
            memory_type="memory",
            subject=EntityRef(kind="user", id="user"),
            object=EntityRef(kind="bot", id="bot"),
            owner_bot_id="bot",
            scope="private",
            platform="qq",
            session_id="qq:FriendMessage:user",
            visibility="private_pair",
            lifecycle="stable_memory",
            content="用户喜欢辣味。",
            evidence="我喜欢吃辣。",
            metadata={"persona_id": "persona", "owner_bot_id": "bot"},
        ),
        **changes,
    ).ensure_defaults()


@pytest.fixture
def service(tmp_path: Path):
    value = MemoryCompanionService(
        context=None,
        plugin_root=ROOT,
        data_dir=tmp_path,
        config={
            "memory_injection": {"max_chars": 3000, "enable_injection_logs": False},
            "retrieval": {"mode": "basic", "embedding_enabled": False},
            "conversation_memory_advanced": {
                "low_information_guard_enabled": False,
                "topic_shift_guard_enabled": False,
            },
        },
    )
    value._p5_gate = AsyncMock(return_value={"ok": True})
    yield value
    value.close()


def request() -> SimpleNamespace:
    return SimpleNamespace(
        prompt="用户原始请求",
        contexts=[{"role": "user", "content": "前面谈到口味"}],
        extra_user_content_parts=[],
    )


def stage_names(timer: _HookStageTimer) -> list[str]:
    return [name for name, _ms in timer._marks]


async def test_injection_reports_each_internal_stage(service) -> None:
    """guards/intent/retrieve/compose must be individually visible."""
    await service.store.insert_memory(record())
    timer = _HookStageTimer(True)
    service._hook_stage_timer = timer
    try:
        await service.inject_memories(context(), request(), event=None)
    finally:
        service._hook_stage_timer = None

    names = stage_names(timer)
    for expected in ("guards", "intent", "retrieve", "compose"):
        assert expected in names, f"缺少阶段打点 {expected}：{names}"

    # The split must stay ordered, otherwise the numbers cannot be attributed.
    assert names.index("guards") < names.index("intent")
    assert names.index("intent") < names.index("retrieve")
    assert names.index("retrieve") < names.index("compose")


async def test_injection_records_publish_and_log_stages(service) -> None:
    await service.store.insert_memory(record())
    timer = _HookStageTimer(True)
    service._hook_stage_timer = timer
    try:
        await service.inject_memories(context(), request(), event=None)
    finally:
        service._hook_stage_timer = None

    names = stage_names(timer)
    # publish covers the injection write, compose_log the injection-log write.
    assert "publish" in names, f"缺少 publish 打点：{names}"
    assert names.index("compose") < names.index("publish")


async def test_injection_without_a_timer_still_works(service) -> None:
    """Timing must stay optional: no timer means no crash and normal behaviour."""
    await service.store.insert_memory(record())
    service._hook_stage_timer = None

    await service.inject_memories(context(), request(), event=None)


async def test_disabled_timer_records_no_injection_stages(service) -> None:
    await service.store.insert_memory(record())
    timer = _HookStageTimer(False)
    service._hook_stage_timer = timer
    try:
        await service.inject_memories(context(), request(), event=None)
    finally:
        service._hook_stage_timer = None

    assert timer.summary() == "no_stages"
