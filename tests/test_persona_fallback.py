# -*- coding: utf-8 -*-
"""Regression tests for persona resolution when the event carries no persona.

AstrBot's ``AstrMessageEvent`` has no ``persona_id`` attribute and a
single-persona companion install leaves ``private_companion_persona_id`` unset,
so the resolver previously produced an empty persona.  ``memory_lifecycle`` then
rejected every persona-tagged memory as ``persona_context_missing`` even though
the bridge stamps a persona on write.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from .package_bootstrap import bootstrap_package

bootstrap_package()

from astrbot_plugin_memory_companion.core.identity import IdentityResolver


def plain_event():
    """An event shaped like AstrMessageEvent: no persona attributes at all."""
    return SimpleNamespace(
        unified_msg_origin="aiocqhttp:GroupMessage:1032290619",
        message_str="今天好累",
        get_platform_name=lambda: "aiocqhttp",
        get_group_id=lambda: "1032290619",
        get_group_name=lambda: "测试群",
        get_self_id=lambda: "3884021973",
        get_sender_id=lambda: "1538054427",
        get_sender_name=lambda: "有所思",
        get_message_str=lambda: "今天好累",
    )


def resolve(resolver, event):
    return asyncio.run(resolver.resolve_event_context(event))


def test_without_fallback_persona_stays_empty():
    ctx = resolve(IdentityResolver(), plain_event())
    assert ctx.persona_id == ""


def test_fallback_fills_missing_persona():
    async def fallback(_event):
        return "kazusa"

    ctx = resolve(IdentityResolver(persona_id_fallback=fallback), plain_event())
    assert ctx.persona_id == "kazusa"


def test_sync_fallback_is_supported():
    ctx = resolve(
        IdentityResolver(persona_id_fallback=lambda _event: "kazusa"),
        plain_event(),
    )
    assert ctx.persona_id == "kazusa"


@pytest.mark.parametrize("attribute", ["private_companion_persona_id", "persona_id"])
def test_event_persona_wins_over_fallback(attribute):
    event = plain_event()
    setattr(event, attribute, "companion_persona")

    async def fallback(_event):
        return "astrbot_persona"

    ctx = resolve(IdentityResolver(persona_id_fallback=fallback), event)
    assert ctx.persona_id == "companion_persona"


@pytest.mark.parametrize("case", ["raises", "returns_none", "returns_empty"])
def test_broken_fallback_degrades_to_empty(case):
    async def fallback(_event):
        if case == "raises":
            raise RuntimeError("persona manager unavailable")
        return None if case == "returns_none" else ""

    ctx = resolve(IdentityResolver(persona_id_fallback=fallback), plain_event())
    assert ctx.persona_id == ""


def test_fallback_result_is_cleaned_and_truncated():
    async def fallback(_event):
        return "  kazusa  "

    ctx = resolve(IdentityResolver(persona_id_fallback=fallback), plain_event())
    assert ctx.persona_id == "kazusa"


def test_fallback_does_not_disturb_other_identity_fields():
    async def fallback(_event):
        return "kazusa"

    ctx = resolve(IdentityResolver(persona_id_fallback=fallback), plain_event())
    assert ctx.session_id == "aiocqhttp:GroupMessage:1032290619"
    assert ctx.bot_id == "3884021973"
    assert ctx.user_id == "1538054427"
    assert ctx.scope == "group"
    assert ctx.platform == "aiocqhttp"
