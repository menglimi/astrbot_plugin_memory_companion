# -*- coding: utf-8 -*-
"""Regression tests for persona resolution when the event carries no persona.

AstrBot's ``AstrMessageEvent`` has no ``persona_id`` attribute and a
single-persona companion install leaves ``private_companion_persona_id`` unset,
so the resolver previously produced an empty persona.  ``memory_lifecycle`` then
rejected every persona-tagged memory as ``persona_context_missing`` even though
the runtime applied one.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.identity import IdentityResolver
from astrbot_plugin_memory_companion.core.memory_lifecycle import evaluate_memory_lifecycle
from astrbot_plugin_memory_companion.core.models import MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.source_query import source_visible


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


@pytest.fixture(autouse=True)
def session_service_config(monkeypatch):
    """Patch the host preference store AstrBot reads for per-session personas."""
    import astrbot.api

    state = {"config": {}}

    async def get_async(*, scope, scope_id, key, default=None):
        return state["config"] if key == "session_service_config" else default

    monkeypatch.setattr(astrbot.api.sp, "get_async", get_async)
    return state


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


def host_persona_manager(default_personality, personas=None):
    """Return the real AstrBot persona manager the plugin resolves against.

    Args:
        default_personality: Persona id configured as the session default;
            ``None`` leaves ``default_personality`` unset.
        personas: Personas the manager knows about; defaults to one persona.

    Returns:
        A ``PersonaManager`` backed by an in-memory configuration manager.
    """
    import astrbot.api  # noqa: F401  # persona_mgr re-enters astrbot.api; load the host graph first
    from astrbot.core.persona_mgr import PersonaManager

    class ConfigManager:
        """One configuration profile for every session origin."""

        def __init__(self):
            settings = (
                {}
                if default_personality is None
                else {"default_personality": default_personality}
            )
            self.default_conf = {"provider_settings": settings}

        def get_conf(self, umo=None):
            return self.default_conf

    manager = PersonaManager(db_helper=None, acm=ConfigManager())
    manager.personas_v3 = list(
        personas if personas is not None else [{"name": "kazusa", "prompt": "你叫和纱。"}]
    )
    return manager


def conversation_manager(persona_id):
    """Return a host conversation manager pinning one persona."""

    class Manager:
        async def get_curr_conversation_id(self, umo):
            return "conversation-1"

        async def get_conversation(self, umo, conversation_id):
            return SimpleNamespace(persona_id=persona_id)

    return Manager()


def resolve_through_service(persona_manager, event, *, conversation_persona_id=None):
    """Resolve one event through the service wiring and its host persona manager.

    Args:
        persona_manager: Host persona manager exposed by the AstrBot context, or
            ``None`` for a host that exposes no persona manager at all.
        event: The message event to resolve.
        conversation_persona_id: Persona pinned on the active conversation.

    Returns:
        The ``SessionContext`` the service builds for that event.
    """
    temp_dir = tempfile.TemporaryDirectory()
    context = None
    if persona_manager is not None:
        context = SimpleNamespace(persona_manager=persona_manager)
        if conversation_persona_id is not None:
            context.conversation_manager = conversation_manager(conversation_persona_id)
    service = MemoryCompanionService(
        context=context,
        config={},
        plugin_root=ROOT,
        data_dir=Path(temp_dir.name),
        defer_database_initialization=True,
    )
    try:
        return asyncio.run(service.identity.resolve_event_context(event))
    finally:
        service.close()
        temp_dir.cleanup()


@pytest.mark.parametrize("default_personality", ["kazusa", "yuki"])
def test_service_resolves_the_persona_astrbot_applies(default_personality):
    ctx = resolve_through_service(host_persona_manager(default_personality), plain_event())

    assert ctx.persona_id == default_personality


def test_service_follows_the_session_persona(session_service_config):
    session_service_config["config"] = {"persona_id": "kazusa"}

    ctx = resolve_through_service(host_persona_manager("default"), plain_event())

    assert ctx.persona_id == "kazusa"


def test_service_follows_the_conversation_persona():
    ctx = resolve_through_service(
        host_persona_manager("default"),
        plain_event(),
        conversation_persona_id="kazusa",
    )

    assert ctx.persona_id == "kazusa"


@pytest.mark.parametrize("configured", ["[%None]", None])
def test_service_keeps_the_persona_empty_when_none_applies(configured):
    ctx = resolve_through_service(host_persona_manager(configured), plain_event())

    assert ctx.persona_id == ""


def test_persona_gate_reports_missing_context_only_without_a_runtime_persona():
    archive = MemoryRecord(
        id="companion-archive",
        content="人格范围的归档记忆",
        owner_bot_id="3884021973",
        metadata={"persona_id": "kazusa"},
    )

    unresolved = resolve_through_service(None, plain_event())
    assert unresolved.persona_id == ""
    assert evaluate_memory_lifecycle(archive, unresolved).reason == "persona_context_missing"

    disabled = resolve_through_service(host_persona_manager("[%None]"), plain_event())
    assert disabled.persona_id == ""
    assert evaluate_memory_lifecycle(archive, disabled).reason == "persona_context_missing"

    resolved = resolve_through_service(host_persona_manager("kazusa"), plain_event())
    assert resolved.persona_id == "kazusa"
    assert evaluate_memory_lifecycle(archive, resolved).eligible


def test_foreign_persona_memory_is_reported_as_mismatch():
    archive = MemoryRecord(
        id="other-persona-archive",
        content="另一个人格的归档记忆",
        owner_bot_id="3884021973",
        metadata={"persona_id": "yuki"},
    )

    ctx = resolve_through_service(host_persona_manager("kazusa"), plain_event())

    assert evaluate_memory_lifecycle(archive, ctx).reason == "persona_mismatch"


def test_legacy_source_rows_without_persona_stay_visible():
    ctx = SessionContext(
        session_id="qq:FriendMessage:source-user",
        scope="private",
        platform="qq",
        user_id="source-user",
        bot_id="source-bot",
        persona_id="default",
    )
    row = {
        "scope": "private",
        "session_id": ctx.session_id,
        "event_type": "user_message",
        "object_id": ctx.user_id,
        "subject_id": ctx.user_id,
    }
    metadata = {"owner_bot_id": ctx.bot_id, "platform": ctx.platform, "persona_id": ""}
    assert source_visible(ctx, row, metadata)

    metadata["persona_id"] = "other-persona"
    assert not source_visible(ctx, row, metadata)


def test_service_degrades_to_an_empty_persona_when_the_host_fails():
    class BrokenManager:
        async def resolve_selected_persona(self, **kwargs):
            raise RuntimeError("persona manager unavailable")

        async def get_default_persona_v3(self, umo=None):
            raise RuntimeError("persona manager unavailable")

    assert resolve_through_service(BrokenManager(), plain_event()).persona_id == ""
