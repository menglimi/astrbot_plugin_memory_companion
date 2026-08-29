from __future__ import annotations

from typing import Any

from . import bot_personal_contract
from .bot_personal_dto import BotPersonalArchiveDTO, build_bot_personal_archive
from .models import EntityRef, clean_text


class ExternalRecordBridgeFamily:
    """Concrete bridge capability family backed by one façade owner."""

    __slots__ = ("_owner",)

    def __init__(self, owner: Any):
        self._owner = owner

    async def record_event(
        self,
        *,
        content: str,
        memory_type: str = "external_event",
        scope: str = "unknown",
        session_id: str = "",
        platform: str = "",
        message_id: str = "",
        group_id: str = "",
        subject: dict[str, Any] | None = None,
        object: dict[str, Any] | None = None,
        visibility: str = "bot_self",
        sayability: str = "direct",
        reality_level: str = "bot_action",
        lifecycle: str = "stable_memory",
        confidence: float = 0.85,
        importance: float = 0.5,
        review_status: str = "auto",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        source_plugin: str = "external",
        memory_id: str = "",
        occurred_at: str = "",
    ) -> str:
        return await self._owner._plugin.record_external_event(
            content=content,
            memory_type=memory_type,
            scope=scope,
            session_id=session_id,
            platform=platform,
            message_id=message_id,
            group_id=group_id,
            subject=self._owner._entity(subject) if subject else EntityRef.bot_self(),
            object=self._owner._entity(object) if object else EntityRef(kind="session", id=session_id, role="target_session"),
            visibility=visibility,
            sayability=sayability,
            reality_level=reality_level,
            lifecycle=lifecycle,
            confidence=confidence,
            importance=importance,
            review_status=review_status,
            tags=tags or [],
            metadata=metadata or {},
            source_plugin=source_plugin,
            memory_id=memory_id,
            occurred_at=occurred_at,
        )

    async def record_bot_action(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "self_action")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("source_plugin", kwargs.get("source_plugin", "external"))
        return await self._owner.record_event(content=content, **kwargs)

    async def record_persona_life(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "persona_life")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "persona_life")
        kwargs.setdefault("sayability", "indirect")
        return await self._owner.record_event(content=content, **kwargs)

    async def record_proactive_message(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "proactive_message")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["proactive", "bot_action"])
        kwargs.setdefault("importance", 0.55)
        return await self._owner.record_event(content=content, **kwargs)

    async def record_visible_turn(self, *, role: str, content: str, **kwargs: Any) -> str:
        """Record a real visible chat turn into the short-term timeline only."""
        return await self._owner._plugin.record_visible_turn(role=role, content=content, **kwargs)

    async def record_shared_experience(
        self,
        *,
        content: str,
        experience_type: str,
        bot_id: str = "",
        bot_name: str = "",
        user_id: str = "",
        user_name: str = "",
        scope: str = "private",
        session_id: str = "",
        platform: str = "",
        source_plugin: str = "external",
        memory_id: str = "",
        confidence: float = 0.9,
        importance: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record one distilled call/watch experience with explicit ownership."""
        normalized_type = clean_text(experience_type, 40).lower()
        if normalized_type in {"watch", "shared_watch", "video"}:
            memory_type = "shared_watch"
            experience_tag = "watch"
        elif normalized_type in {"call", "shared_call", "voice"}:
            memory_type = "shared_call"
            experience_tag = "call"
        else:
            memory_type = "shared_experience"
            experience_tag = normalized_type or "shared"
        subject = EntityRef.bot_self(bot_id=bot_id, bot_name=bot_name)
        target = EntityRef(
            kind="user",
            id=clean_text(user_id, 120),
            name=clean_text(user_name, 80),
            role="shared_experience_partner",
        )
        return await self._owner.record_event(
            content=content,
            memory_type=memory_type,
            scope=scope,
            session_id=session_id,
            platform=platform,
            subject={
                "kind": subject.kind,
                "id": subject.id,
                "name": subject.name,
                "role": subject.role,
            },
            object={
                "kind": target.kind,
                "id": target.id,
                "name": target.name,
                "role": target.role,
            },
            visibility="bot_self",
            sayability="direct",
            reality_level="bot_action",
            lifecycle="stable_memory",
            confidence=confidence,
            importance=importance,
            review_status="auto",
            tags=["shared_experience", experience_tag, "bot_action"],
            metadata=metadata or {},
            source_plugin=source_plugin,
            memory_id=memory_id,
        )

    async def record_search_action(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "search_action")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["search", "bot_action"])
        kwargs.setdefault("importance", 0.62)
        return await self._owner.record_event(content=content, **kwargs)

    async def record_creative_work(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "creative_work")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "fictional_content")
        kwargs.setdefault("sayability", "direct")
        kwargs.setdefault("tags", ["creative_work"])
        kwargs.setdefault("importance", 0.72)
        return await self._owner.record_event(content=content, **kwargs)

    async def record_image_action(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "image_action")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["image", "bot_action"])
        kwargs.setdefault("importance", 0.6)
        return await self._owner.record_event(content=content, **kwargs)

    async def record_qzone_action(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "qzone_action")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["qzone", "bot_action"])
        kwargs.setdefault("importance", 0.58)
        return await self._owner.record_event(content=content, **kwargs)

    async def record_reading(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "reading_memory")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["reading", "bot_action"])
        kwargs.setdefault("importance", 0.55)
        return await self._owner.record_event(content=content, **kwargs)

    async def record_schedule_fragment(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "schedule_fragment")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "persona_life")
        kwargs.setdefault("sayability", "indirect")
        kwargs.setdefault("tags", ["schedule", "persona_life"])
        kwargs.setdefault("importance", 0.45)
        return await self._owner.record_event(content=content, **kwargs)

    async def record_bot_personal_archive(
        self,
        envelope: BotPersonalArchiveDTO | dict[str, Any],
        *,
        producer_capability: Any = None,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Send one validated Bot Personal archive envelope without leaking failures."""
        base = {
            "ok": False,
            "record_id": "",
            "deduplicated": False,
            "version": 0,
            "error_code": None,
            "state": "degraded",
        }
        authority = producer_capability if producer_capability is not None else producer_context
        if not self._owner._is_valid_private_companion_capability(authority):
            return {**base, "state": "forbidden", "error_code": "producer_capability_required"}
        try:
            dto = build_bot_personal_archive(envelope)
        except Exception as exc:
            return {**base, "state": "invalid", "error_code": getattr(exc, "error_code", "invalid")}
        if dto.canonical_schema_version >= bot_personal_contract.BOT_PERSONAL_CANONICAL_SCHEMA_VERSION:
            capability = self._owner._producer_capability_from(authority)
            producer = getattr(capability, "_producer", None)
            bot_getter = getattr(producer, "_memory_companion_bridge_bot_id", None)
            persona_getter = getattr(producer, "_memory_companion_archive_persona_id", None)
            try:
                expected_bot_id = clean_text(bot_getter(), 120) if callable(bot_getter) else ""
                expected_persona_id = clean_text(persona_getter(), 96) if callable(persona_getter) else ""
            except Exception:
                expected_bot_id = expected_persona_id = ""
            if (
                not expected_bot_id
                or not expected_persona_id
                or dto.owner_bot_id != expected_bot_id
                or dto.persona_id != expected_persona_id
            ):
                return {**base, "state": "forbidden", "error_code": "producer_namespace_mismatch"}
        try:
            recorder = getattr(self._owner._plugin, "record_bot_personal_archive", None)
        except Exception:
            recorder = None
        if not callable(recorder):
            return {**base, "error_code": "bridge_method_unavailable", "state": "degraded"}
        try:
            result = await recorder(dto)
        except Exception:
            return {**base, "error_code": "bridge_exception", "state": "degraded"}
        if not isinstance(result, dict):
            return {**base, "error_code": "invalid_bridge_response", "state": "degraded"}
        normalized = dict(base)
        for key in base:
            if key in result:
                normalized[key] = result[key]
        normalized["ok"] = bool(result.get("ok"))
        normalized["deduplicated"] = bool(result.get("deduplicated"))
        normalized["version"] = int(result.get("version") or 0)
        if normalized["ok"]:
            normalized["state"] = "deduplicated" if normalized["deduplicated"] else "sent"
        elif normalized["state"] == "ready":
            normalized["state"] = "degraded"
        return normalized

    async def record_bot_personal_memory(
        self,
        *,
        memory_type: str,
        payload: dict[str, Any] | None = None,
        producer_capability: Any = None,
        producer_context: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Compatibility alias that still crosses the structured archive boundary."""
        try:
            envelope = build_bot_personal_archive(memory_type=memory_type, payload=payload or {}, **kwargs)
        except Exception as exc:
            return {
                "ok": False, "record_id": "", "deduplicated": False, "version": 0,
                "error_code": getattr(exc, "error_code", "invalid"), "state": "invalid",
            }
        return await self._owner.record_bot_personal_archive(
            envelope,
            producer_capability=producer_capability,
            producer_context=producer_context,
        )
