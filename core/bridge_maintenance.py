from __future__ import annotations

from typing import Any


class MaintenanceBridgeFamily:
    """Concrete bridge capability family backed by one façade owner."""

    __slots__ = ("_owner",)

    def __init__(self, owner: Any):
        self._owner = owner

    def p5_capability_status(self) -> dict[str, Any]:
        getter = getattr(self._owner._plugin, "p5_capability_status", None)
        if not callable(getter):
            return {"state": "degraded", "error_code": "p5_status_unavailable"}
        try:
            result = getter()
        except Exception:
            return {"state": "degraded", "error_code": "p5_status_exception"}
        return dict(result) if isinstance(result, dict) else {"state": "degraded", "error_code": "p5_status_invalid"}

    def provenance_snapshot(self) -> dict[str, Any]:
        getter = getattr(self._owner._plugin, "provenance_snapshot", None)
        if not callable(getter):
            return {"records": {}, "operation_count": 0, "state": "degraded"}
        result = getter()
        return dict(result) if isinstance(result, dict) else {"records": {}, "operation_count": 0, "state": "degraded"}

    def provenance_preview(self, candidates: list[dict[str, Any]], *, operation_ref_hash: str) -> dict[str, Any]:
        getter = getattr(self._owner._plugin, "provenance_preview", None)
        if not callable(getter):
            return {"mode": "preview", "readonly": True, "write_count": 0, "error_codes": ["unavailable"]}
        result = getter(candidates, operation_ref_hash=operation_ref_hash)
        return dict(result) if isinstance(result, dict) else {"mode": "preview", "readonly": True, "write_count": 0, "error_codes": ["invalid_result"]}

    async def provenance_apply(self, operation: dict[str, Any]) -> dict[str, Any]:
        getter = getattr(self._owner._plugin, "provenance_apply", None)
        if not callable(getter):
            return {"ok": False, "state": "degraded", "error_code": "unavailable"}
        result = await getter(operation)
        return dict(result) if isinstance(result, dict) else {"ok": False, "state": "degraded", "error_code": "invalid_result"}

    async def provenance_backup(self) -> dict[str, Any]:
        getter = getattr(self._owner._plugin, "provenance_backup", None)
        if not callable(getter):
            return {"ok": False, "state": "degraded", "error_code": "unavailable"}
        result = await getter()
        return dict(result) if isinstance(result, dict) else {"ok": False, "state": "degraded", "error_code": "invalid_result"}

    async def provenance_rollback(self, operation: dict[str, Any]) -> dict[str, Any]:
        getter = getattr(self._owner._plugin, "provenance_rollback", None)
        if not callable(getter):
            return {"ok": False, "state": "degraded", "error_code": "unavailable"}
        result = await getter(operation)
        return dict(result) if isinstance(result, dict) else {"ok": False, "state": "degraded", "error_code": "invalid_result"}

    async def create_note(self, *, event: Any, title: str, content: str = "") -> dict[str, Any]:
        return await self._owner._plugin.tool_note_create(event, title, content)

    async def read_notes(self, *, event: Any, query: str = "", limit: int = 5) -> dict[str, Any]:
        return await self._owner._plugin.tool_note_read(event, query, limit=limit)

    async def delete_note(self, *, event: Any, memory_id: str = "", title: str = "") -> dict[str, Any]:
        return await self._owner._plugin.tool_note_delete(event, memory_id, title=title)

    def coordination_status(self) -> dict[str, Any]:
        try:
            getter = getattr(self._owner._plugin, "companion_coordination_status", None)
        except Exception:
            return {"available": False, "state": "degraded", "degraded": True, "reason": "bridge_exception"}
        if not callable(getter):
            return {"available": False, "state": "degraded", "degraded": True, "reason": "method_missing"}
        try:
            result = getter()
        except Exception as exc:
            return {"available": False, "state": "degraded", "degraded": True, "reason": "bridge_exception", "error": str(exc)[:160]}
        if not isinstance(result, dict):
            return {"available": False, "state": "degraded", "degraded": True, "reason": "invalid_status"}
        result = dict(result)
        result.setdefault("available", True)
        result.setdefault("state", "ready")
        result.setdefault("degraded", False)
        return result

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
        return await self._owner._plugin.store.create_cross_window_thread(
            from_session=from_session,
            to_session=to_session,
            topic=topic,
            content=content,
            visibility=visibility,
            metadata=metadata or {},
        )
