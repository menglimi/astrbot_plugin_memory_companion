from __future__ import annotations

from typing import Any

from .models import SessionContext, clean_text


class RecallBridgeFamily:
    """Concrete bridge capability family backed by one façade owner."""

    __slots__ = ("_owner",)

    def __init__(self, owner: Any):
        self._owner = owner

    async def read_bot_personal_profile(
        self,
        query: str = "",
        *,
        limit: int = 10,
        producer_capability: Any = None,
    ) -> dict[str, Any]:
        """Read only safe Bot Personal summaries; never return archive payloads."""
        base = {"ok": False, "read_only": True, "state": "degraded", "degraded": True, "pending": True, "items": []}
        owner_bot_id = ""
        persona_id = ""
        if producer_capability is not None:
            if not self._owner._is_valid_private_companion_capability(producer_capability):
                return {**base, "state": "forbidden", "degraded": False, "pending": False, "error_code": "producer_capability_required"}
            capability = self._owner._producer_capability_from(producer_capability)
            producer = getattr(capability, "_producer", None)
            bot_getter = getattr(producer, "_memory_companion_bridge_bot_id", None)
            persona_getter = getattr(producer, "_memory_companion_archive_persona_id", None)
            try:
                owner_bot_id = clean_text(bot_getter(), 120) if callable(bot_getter) else ""
                persona_id = clean_text(persona_getter(), 96) if callable(persona_getter) else ""
            except Exception:
                owner_bot_id = persona_id = ""
            if not owner_bot_id or not persona_id:
                return {**base, "state": "forbidden", "degraded": False, "pending": False, "error_code": "producer_namespace_unavailable"}
        try:
            getter = getattr(self._owner._plugin, "read_bot_personal_profile", None)
        except Exception:
            getter = None
        if not callable(getter):
            return {**base, "error_code": "bridge_method_unavailable"}
        try:
            result = await getter(
                query=query,
                limit=limit,
                owner_bot_id=owner_bot_id,
                persona_id=persona_id,
            )
        except Exception:
            return {**base, "error_code": "bridge_exception"}
        if not isinstance(result, dict):
            return {**base, "error_code": "invalid_bridge_response"}
        safe_keys = {
            "record_id", "memory_type", "memory_domain", "subject", "date", "window", "occurred_at",
            "source_kind", "source_refs", "evidence_level", "status", "version", "summary", "reference",
        }
        items = result.get("items", result.get("memories", []))
        safe_items: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            safe_items.append({key: item[key] for key in safe_keys if key in item and key not in {"payload", "content"}})
        return {
            "ok": bool(result.get("ok", True)), "read_only": True,
            "state": "ready" if result.get("state") in (None, "ready") else result.get("state"),
            "degraded": bool(result.get("degraded", False)), "pending": bool(result.get("pending", False)),
            "items": safe_items,
        }

    async def search_bot_personal_profile(
        self,
        query: str = "",
        *,
        limit: int = 10,
        producer_capability: Any = None,
    ) -> dict[str, Any]:
        return await self._owner.read_bot_personal_profile(
            query=query,
            limit=limit,
            producer_capability=producer_capability,
        )

    async def read_bot_profile(
        self,
        profile: str,
        query: str = "",
        *,
        limit: int = 10,
        current_date: str = "",
        current_window: str = "",
        authorized: bool = False,
        producer_capability: Any = None,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Read a C4 Bot Profile through a privacy-limited bridge boundary."""

        base = {
            "ok": False,
            "read_only": True,
            "state": "degraded",
            "degraded": True,
            "pending": True,
            "profile": clean_text(profile, 80),
            "items": [],
            "warnings": [],
        }
        authority = producer_capability if producer_capability is not None else producer_context
        owner_bot_id = ""
        persona_id = ""
        locked_authorized = False
        if authority is not None:
            if not self._owner._is_valid_private_companion_capability(authority):
                return {
                    **base,
                    "state": "forbidden",
                    "degraded": False,
                    "pending": False,
                    "warnings": ["authorization_required"],
                    "error_code": "producer_capability_required",
                }
            capability = self._owner._producer_capability_from(authority)
            producer = getattr(capability, "_producer", None)
            bot_getter = getattr(producer, "_memory_companion_bridge_bot_id", None)
            persona_getter = getattr(producer, "_memory_companion_archive_persona_id", None)
            try:
                owner_bot_id = clean_text(bot_getter(), 120) if callable(bot_getter) else ""
                persona_id = clean_text(persona_getter(), 96) if callable(persona_getter) else ""
            except Exception:
                owner_bot_id = persona_id = ""
            if not owner_bot_id or not persona_id:
                return {
                    **base,
                    "state": "forbidden",
                    "degraded": False,
                    "pending": False,
                    "error_code": "producer_namespace_unavailable",
                }
            locked_authorized = True
        if base["profile"] == "locked_frame_personal" and not locked_authorized:
            return {
                **base,
                "state": "forbidden",
                "degraded": False,
                "pending": False,
                "warnings": ["authorization_required"],
                "error_code": "producer_capability_required",
            }
        _ = authorized
        try:
            getter = getattr(self._owner._plugin, "read_bot_profile", None)
        except Exception:
            getter = None
        if not callable(getter):
            return {**base, "error_code": "bridge_method_unavailable"}
        try:
            result = await getter(
                profile,
                query=query,
                limit=limit,
                current_date=current_date,
                current_window=current_window,
                authorized=locked_authorized,
                owner_bot_id=owner_bot_id if locked_authorized else None,
                persona_id=persona_id if locked_authorized else None,
                legacy_namespace_only=not locked_authorized,
            )
        except Exception:
            return {**base, "error_code": "bridge_exception"}
        if not isinstance(result, dict):
            return {**base, "error_code": "invalid_bridge_response"}
        safe_item_keys = {
            "record_id", "memory_domain", "memory_type", "subject", "date", "window",
            "occurred_at", "source_kind", "source_refs", "evidence_level", "status",
            "version", "summary", "reference",
        }
        safe_items: list[dict[str, Any]] = []
        items = result.get("items", [])
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                safe_items.append({key: item[key] for key in safe_item_keys if key in item})
        return {
            "ok": bool(result.get("ok", True)),
            "read_only": True,
            "state": clean_text(result.get("state"), 40) or "ready",
            "degraded": bool(result.get("degraded", False)),
            "pending": bool(result.get("pending", False)),
            "profile": clean_text(result.get("profile") or profile, 80),
            "items": safe_items,
            "warnings": [clean_text(item, 160) for item in result.get("warnings", []) if clean_text(item, 160)][:8]
            if isinstance(result.get("warnings"), list) else [],
        }

    async def read_profile(self, profile: str, query: str = "", **kwargs: Any) -> dict[str, Any]:
        """Short alias for callers that use the generic Profile API name."""

        return await self._owner.read_bot_profile(profile, query=query, **kwargs)

    async def search(
        self,
        query: str,
        *,
        session_context: SessionContext | dict[str, Any] | None = None,
        top_k: int | None = None,
        p5_attestation: Any = None,
        p5_attestation_consumer: Any = None,
    ) -> list[dict[str, Any]]:
        return await self._owner._plugin.bridge_search(
            query,
            session_context=session_context,
            top_k=top_k,
            p5_attestation=p5_attestation,
            p5_attestation_consumer=p5_attestation_consumer,
        )

    async def compose_injection(
        self,
        query: str,
        *,
        session_context: SessionContext | dict[str, Any] | None = None,
        top_k: int | None = None,
        max_chars: int | None = None,
        companion_bot_mood: str = "",
        companion_bot_energy: float = 0.0,
        p5_attestation: Any = None,
        p5_attestation_consumer: Any = None,
    ) -> str:
        return await self._owner._plugin.bridge_compose_injection(
            query,
            session_context=session_context,
            top_k=top_k,
            max_chars=max_chars,
            companion_bot_mood=companion_bot_mood,
            companion_bot_energy=companion_bot_energy,
            p5_attestation=p5_attestation,
            p5_attestation_consumer=p5_attestation_consumer,
        )

    async def compose_context(
        self,
        *,
        query: str = "",
        session_context: SessionContext | dict[str, Any] | None = None,
        top_k: int | None = None,
        max_chars: int | None = None,
        companion_bot_mood: str = "",
        companion_bot_energy: float = 0.0,
        retrieval_profile: str = "",
        p5_attestation: Any = None,
        p5_attestation_consumer: Any = None,
    ) -> str:
        return await self._owner._plugin.bridge_compose_context(
            query=query,
            session_context=session_context,
            top_k=top_k,
            max_chars=max_chars,
            companion_bot_mood=companion_bot_mood,
            companion_bot_energy=companion_bot_energy,
            retrieval_profile=retrieval_profile,
            p5_attestation=p5_attestation,
            p5_attestation_consumer=p5_attestation_consumer,
        )

    async def remember(self, *, event: Any, content: str, note_type: str = "memory") -> dict[str, Any]:
        return await self._owner._plugin.tool_remember(event, content, note_type=note_type)

    async def recall(
        self,
        *,
        event: Any,
        query: str,
        top_k: int = 5,
        p5_attestation: Any = None,
        p5_attestation_consumer: Any = None,
    ) -> dict[str, Any]:
        return await self._owner._plugin.tool_recall(
            event,
            query,
            top_k=top_k,
            p5_attestation=p5_attestation,
            p5_attestation_consumer=p5_attestation_consumer,
        )

    def get_token_usage_summary(self) -> dict[str, Any]:
        getter = getattr(self._owner._plugin, "token_usage_summary", None)
        if callable(getter):
            result = getter()
            return result if isinstance(result, dict) else {}
        return {}

    def should_defer_private_companion_section(self, section: str) -> bool:
        checker = getattr(self._owner._plugin, "should_private_companion_defer_section", None)
        if callable(checker):
            return bool(checker(section))
        return False

    async def mark_visibility(self, memory_id: str, visibility: str) -> bool:
        return await self._owner._plugin.store.update_memory_visibility(memory_id, visibility)

    async def search_open_loops(self, *, session_id: str = "", limit: int = 3) -> list[dict[str, Any]]:
        """Search for unresolved open-loop / promise memories for proactive companionship."""
        return await self._owner._plugin.bridge_search_open_loops(session_id=session_id, limit=limit)
