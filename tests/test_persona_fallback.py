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
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.identity import IdentityResolver
from astrbot_plugin_memory_companion.core.memory_lifecycle import evaluate_memory_lifecycle
from astrbot_plugin_memory_companion.core.models import MemoryRecord
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


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


def host_persona_manager(default_personality, personas=None):
    """Return the real AstrBot persona manager the plugin resolves against.

    The service-level fallback talks to the host API, not to a hand-written
    double, so the test fails when a supported AstrBot release stops exposing
    ``get_default_persona_v3`` with a ``name`` field.

    Args:
        default_personality: Persona id configured as the session default.
        personas: Personas the manager knows about; defaults to one persona.

    Returns:
        A ``PersonaManager`` backed by an in-memory configuration manager.
    """
    import astrbot.api  # noqa: F401  # persona_mgr re-enters astrbot.api; load the host graph first
    from astrbot.core.persona_mgr import PersonaManager

    class ConfigManager:
        """One configuration profile for every session origin."""

        def __init__(self):
            self.default_conf = {
                "provider_settings": {"default_personality": default_personality}
            }

        def get_conf(self, umo=None):
            return self.default_conf

    manager = PersonaManager(db_helper=None, acm=ConfigManager())
    manager.personas_v3 = list(
        personas if personas is not None else [{"name": "kazusa", "prompt": "你叫和纱。"}]
    )
    return manager


def resolve_through_service(persona_manager, event):
    """Resolve one event through the service wiring and its host persona manager.

    Args:
        persona_manager: Host persona manager exposed by the AstrBot context, or
            ``None`` for a host that exposes no persona manager at all.
        event: The message event to resolve.

    Returns:
        The ``SessionContext`` the service builds for that event.
    """
    temp_dir = tempfile.TemporaryDirectory()
    service = MemoryCompanionService(
        context=(
            SimpleNamespace(persona_manager=persona_manager)
            if persona_manager is not None
            else None
        ),
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


def test_service_resolves_the_persona_astrbot_runs():
    manager = host_persona_manager("kazusa")

    ctx = resolve_through_service(manager, plain_event())

    expected = asyncio.run(manager.get_default_persona_v3(umo=ctx.session_id))
    # The resolver must pick the persona id out of the host payload, not the
    # whole v3 record, or the gate compares apples to oranges.
    assert expected["name"] == "kazusa"
    assert ctx.persona_id == "kazusa"


def test_persona_gate_opens_only_when_the_host_reports_a_persona():
    archive = MemoryRecord(
        id="companion-archive",
        content="人格范围的归档记忆",
        owner_bot_id="3884021973",
        metadata={"persona_id": "kazusa"},
    )

    unresolved = resolve_through_service(None, plain_event())
    assert unresolved.persona_id == ""
    assert evaluate_memory_lifecycle(archive, unresolved).reason == "persona_context_missing"

    resolved = resolve_through_service(host_persona_manager("kazusa"), plain_event())
    assert resolved.persona_id == "kazusa"
    assert evaluate_memory_lifecycle(archive, resolved).eligible


def test_service_degrades_to_an_empty_persona_when_the_host_fails():
    class BrokenManager:
        async def get_default_persona_v3(self, umo=None):
            raise RuntimeError("persona manager unavailable")

    assert resolve_through_service(BrokenManager(), plain_event()).persona_id == ""
