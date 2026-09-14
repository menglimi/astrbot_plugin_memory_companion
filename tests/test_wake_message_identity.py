# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from .package_bootstrap import bootstrap_package

bootstrap_package()

from astrbot_plugin_memory_companion.core.identity import IdentityResolver


def event_with_snapshot():
    return SimpleNamespace(
        message_str="呢",
        message_obj=SimpleNamespace(message_str="星缘呢"),
        _private_companion_wake_message_context={
            "original_text": "星缘呢", "routed_text": "呢", "wake_prefix": "星缘",
        },
    )


@pytest.mark.parametrize("getter_type", ["sync", "async", "missing", "broken"])
def test_original_text_with_supported_event_getters(getter_type):
    event = event_with_snapshot()

    async def async_getter():
        return event.message_str

    def broken_getter():
        raise RuntimeError("adapter getter unavailable")

    if getter_type == "sync":
        event.get_message_str = lambda: event.message_str
    elif getter_type == "async":
        event.get_message_str = async_getter
    elif getter_type == "broken":
        event.get_message_str = broken_getter
    assert asyncio.run(IdentityResolver()._message_text(event)) == "星缘呢"
    assert event.message_str == "呢"


@pytest.mark.parametrize("case", ["no_bridge", "rewritten", "changed_source", "synthetic", "bad_prefix", "bad_text"])
def test_missing_or_stale_bridge_keeps_current_message(case):
    event = event_with_snapshot()
    if case == "no_bridge":
        del event._private_companion_wake_message_context
    elif case == "rewritten":
        event.message_str = "另一个插件的正文"
    elif case == "changed_source":
        event.message_obj.message_str = "另一条消息"
    elif case == "synthetic":
        event.private_companion_proactive_framework = True
    elif case == "bad_prefix":
        event._private_companion_wake_message_context["wake_prefix"] = "其他名字"
    else:
        event._private_companion_wake_message_context["original_text"] = {"text": "星缘呢"}
    assert asyncio.run(IdentityResolver()._message_text(event)) == event.message_str
