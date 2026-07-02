from __future__ import annotations

from typing import Any

from .models import EntityRef, MemoryRecord, SessionContext, clean_text


class MemoryCompanionBridge:
    """Public bridge for other plugins.

    The bridge intentionally accepts structured fields. A caller should say
    whether something is a bot action, a persona-life fragment, a real user
    fact, or an imported summary instead of handing over vague prose.
    """

    def __init__(self, plugin: Any):
        self._plugin = plugin

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
    ) -> str:
        return await self._plugin.record_external_event(
            content=content,
            memory_type=memory_type,
            scope=scope,
            session_id=session_id,
            platform=platform,
            message_id=message_id,
            group_id=group_id,
            subject=self._entity(subject) if subject else EntityRef.bot_self(),
            object=self._entity(object) if object else EntityRef(kind="session", id=session_id, role="target_session"),
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
        )

    async def record_bot_action(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "self_action")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("source_plugin", kwargs.get("source_plugin", "external"))
        return await self.record_event(content=content, **kwargs)

    async def record_persona_life(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "persona_life")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "persona_life")
        kwargs.setdefault("sayability", "indirect")
        return await self.record_event(content=content, **kwargs)

    async def record_proactive_message(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "proactive_message")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["proactive", "bot_action"])
        kwargs.setdefault("importance", 0.55)
        return await self.record_event(content=content, **kwargs)

    async def record_visible_turn(self, *, role: str, content: str, **kwargs: Any) -> str:
        """Record a real visible chat turn into the short-term timeline only."""
        return await self._plugin.record_visible_turn(role=role, content=content, **kwargs)

    async def record_search_action(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "search_action")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["search", "bot_action"])
        kwargs.setdefault("importance", 0.62)
        return await self.record_event(content=content, **kwargs)

    async def record_creative_work(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "creative_work")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "fictional_content")
        kwargs.setdefault("sayability", "direct")
        kwargs.setdefault("tags", ["creative_work"])
        kwargs.setdefault("importance", 0.72)
        return await self.record_event(content=content, **kwargs)

    async def record_image_action(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "image_action")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["image", "bot_action"])
        kwargs.setdefault("importance", 0.6)
        return await self.record_event(content=content, **kwargs)

    async def record_qzone_action(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "qzone_action")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["qzone", "bot_action"])
        kwargs.setdefault("importance", 0.58)
        return await self.record_event(content=content, **kwargs)

    async def record_reading(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "reading_memory")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "bot_action")
        kwargs.setdefault("tags", ["reading", "bot_action"])
        kwargs.setdefault("importance", 0.55)
        return await self.record_event(content=content, **kwargs)

    async def record_schedule_fragment(self, *, content: str, **kwargs: Any) -> str:
        kwargs.setdefault("memory_type", "schedule_fragment")
        kwargs.setdefault("visibility", "bot_self")
        kwargs.setdefault("reality_level", "persona_life")
        kwargs.setdefault("sayability", "indirect")
        kwargs.setdefault("tags", ["schedule", "persona_life"])
        kwargs.setdefault("importance", 0.45)
        return await self.record_event(content=content, **kwargs)

    async def search(
        self,
        query: str,
        *,
        session_context: SessionContext | dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return await self._plugin.bridge_search(query, session_context=session_context, top_k=top_k)

    async def compose_injection(
        self,
        query: str,
        *,
        session_context: SessionContext | dict[str, Any] | None = None,
        top_k: int | None = None,
        max_chars: int | None = None,
    ) -> str:
        return await self._plugin.bridge_compose_injection(
            query,
            session_context=session_context,
            top_k=top_k,
            max_chars=max_chars,
        )

    async def compose_context(
        self,
        *,
        query: str = "",
        session_context: SessionContext | dict[str, Any] | None = None,
        top_k: int | None = None,
        max_chars: int | None = None,
    ) -> str:
        return await self._plugin.bridge_compose_context(
            query=query,
            session_context=session_context,
            top_k=top_k,
            max_chars=max_chars,
        )

    async def remember(self, *, event: Any, content: str, note_type: str = "memory") -> dict[str, Any]:
        return await self._plugin.tool_remember(event, content, note_type=note_type)

    async def recall(self, *, event: Any, query: str, top_k: int = 5) -> dict[str, Any]:
        return await self._plugin.tool_recall(event, query, top_k=top_k)

    async def create_note(self, *, event: Any, title: str, content: str = "") -> dict[str, Any]:
        return await self._plugin.tool_note_create(event, title, content)

    async def read_notes(self, *, event: Any, query: str = "", limit: int = 5) -> dict[str, Any]:
        return await self._plugin.tool_note_read(event, query, limit=limit)

    def coordination_status(self) -> dict[str, Any]:
        getter = getattr(self._plugin, "companion_coordination_status", None)
        if callable(getter):
            return getter()
        return {"available": True}

    def should_defer_private_companion_section(self, section: str) -> bool:
        checker = getattr(self._plugin, "should_private_companion_defer_section", None)
        if callable(checker):
            return bool(checker(section))
        return False

    async def create_cross_window_thread(
        self,
        *,
        from_session: str,
        to_session: str,
        topic: str,
        content: str,
        visibility: str = "shareable",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return await self._plugin.store.create_cross_window_thread(
            from_session=from_session,
            to_session=to_session,
            topic=topic,
            content=content,
            visibility=visibility,
            metadata=metadata or {},
        )

    async def mark_visibility(self, memory_id: str, visibility: str) -> bool:
        return await self._plugin.store.update_memory_visibility(memory_id, visibility)

    def _entity(self, payload: dict[str, Any]) -> EntityRef:
        return EntityRef(
            kind=str(payload.get("kind") or "user"),
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            role=str(payload.get("role") or "unknown"),
        )

def serialize_memory(record: MemoryRecord, score: float | None = None, reason: str = "") -> dict[str, Any]:
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    key_facts = metadata.get("key_facts") if isinstance(metadata.get("key_facts"), list) else []
    topics = metadata.get("topics") if isinstance(metadata.get("topics"), list) else []
    participants = metadata.get("participants") if isinstance(metadata.get("participants"), list) else []
    data = {
        "id": record.id,
        "memory_type": record.memory_type,
        "scope": record.scope,
        "session_id": record.session_id,
        "group_id": record.group_id,
        "visibility": record.visibility,
        "sayability": record.sayability,
        "reality_level": record.reality_level,
        "lifecycle": record.lifecycle,
        "content": record.content,
        "evidence_preview": clean_text(record.evidence, 520),
        "canonical_summary": clean_text(metadata.get("canonical_summary"), 420),
        "key_facts": [clean_text(item, 180) for item in key_facts if clean_text(item, 180)][:4],
        "topics": [clean_text(item, 80) for item in topics if clean_text(item, 80)][:5],
        "participants": [clean_text(item, 80) for item in participants if clean_text(item, 80)][:5],
        "confidence": record.confidence,
        "importance": record.importance,
        "review_status": record.review_status,
        "tags": record.tags,
        "source_plugin": record.source_plugin,
        "import_batch_id": record.import_batch_id,
        "created_at": record.created_at,
        "occurred_at": record.occurred_at,
        "subject": {
            "kind": record.subject.kind,
            "id": record.subject.id,
            "name": record.subject.name,
            "role": record.subject.role,
        },
        "object": {
            "kind": record.object.kind,
            "id": record.object.id,
            "name": record.object.name,
            "role": record.object.role,
        },
    }
    if score is not None:
        data["score"] = score
    if reason:
        data["reason"] = reason
    return data
