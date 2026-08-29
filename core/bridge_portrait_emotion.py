from __future__ import annotations

from typing import Any

from .models import SessionContext, clean_text


class PortraitEmotionBridgeFamily:
    """Concrete bridge capability family backed by one façade owner."""

    __slots__ = ("_owner",)

    def __init__(self, owner: Any):
        self._owner = owner

    async def read_user_memory_summary(
        self,
        user_id: str,
        *,
        session_id: str = "",
        limit: int = 6,
        requester_context: Any = None,
    ) -> dict[str, Any]:
        """Read a strict, exact-user Memory summary without exposing memory text."""

        identity = clean_text(user_id, 120)
        safe_session = clean_text(session_id, 200)
        base = {
            "contract": "memory.user_memory_summary.v1",
            "ok": False,
            "read_only": True,
            "state": "degraded",
            "degraded": True,
            "pending": True,
            "user_id": identity,
            "session_id": safe_session,
            "counts": {"profile": 0, "preference": 0, "relationship": 0, "private_conversation": 0, "other": 0, "total": 0},
            "summaries": [],
            "workspace": {"kind": "memory_user_workspace", "route_hint": "user_memory", "user_id": identity},
        }
        if not identity:
            return {**base, "error_code": "missing_user_id"}
        if not self._owner._is_valid_emotion_producer_context(requester_context):
            return {
                **base,
                "state": "forbidden",
                "degraded": False,
                "pending": False,
                "error_code": "requester_context_required",
            }
        if requester_context.user_id != identity:
            return {
                **base,
                "state": "forbidden",
                "degraded": False,
                "pending": False,
                "error_code": "requester_identity_mismatch",
            }
        if safe_session and requester_context.session_id != safe_session:
            return {
                **base,
                "state": "forbidden",
                "degraded": False,
                "pending": False,
                "error_code": "requester_session_mismatch",
            }
        safe_session = requester_context.session_id
        base["session_id"] = safe_session
        try:
            getter = getattr(self._owner._plugin, "read_user_memory_summary", None)
        except Exception:
            getter = None
        if not callable(getter):
            return {**base, "error_code": "bridge_method_unavailable"}
        try:
            result = await getter(identity, session_id=safe_session, limit=limit)
        except Exception:
            return {**base, "error_code": "bridge_exception"}
        if not isinstance(result, dict) or result.get("contract") != base["contract"]:
            return {**base, "error_code": "invalid_bridge_response"}

        counts = dict(base["counts"])
        raw_counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        for key in counts:
            try:
                counts[key] = max(0, int(raw_counts.get(key, 0)))
            except (TypeError, ValueError, OverflowError):
                counts[key] = 0
        summaries: list[dict[str, Any]] = []
        for item in result.get("summaries", []) if isinstance(result.get("summaries"), list) else []:
            if not isinstance(item, dict):
                continue
            category = clean_text(item.get("category"), 40)
            if category not in {"profile", "preference", "relationship", "private_conversation", "other"}:
                continue
            summaries.append(
                {
                    "category": category,
                    "memory_type": clean_text(item.get("memory_type"), 80),
                    "occurred_at": clean_text(item.get("occurred_at"), 80),
                    "summary": clean_text(item.get("summary"), 100),
                    "content_redacted": True,
                    "truncated": True,
                }
            )
            if len(summaries) >= 8:
                break
        state = clean_text(result.get("state"), 40)
        return {
            **base,
            "ok": bool(result.get("ok")) and state == "ready",
            "state": "ready" if state == "ready" else "degraded",
            "degraded": state != "ready" or bool(result.get("degraded", False)),
            "pending": state != "ready" or bool(result.get("pending", False)),
            "user_id": identity,
            "session_id": safe_session,
            "counts": counts,
            "summaries": summaries,
            "workspace": base["workspace"],
            **({"error_code": clean_text(result.get("error_code"), 80)} if state != "ready" and clean_text(result.get("error_code"), 80) else {}),
        }

    async def read_unified_profile_portrait(self, request: dict[str, Any], *, limit: int = 8) -> dict[str, Any]:
        """Return only a pre-authorized low-sensitivity portrait summary."""
        base = {
            "ok": False,
            "read_only": True,
            "code": "bridge_unavailable",
            "items": [],
        }
        getter = getattr(self._owner._plugin, "read_unified_profile_portrait", None)
        if not callable(getter):
            return base
        try:
            result = await getter(request if isinstance(request, dict) else {}, limit=max(1, min(16, int(limit))))
        except Exception:
            return {**base, "code": "bridge_degraded"}
        if not isinstance(result, dict):
            return {**base, "code": "bridge_degraded"}
        items: list[dict[str, Any]] = []
        for item in result.get("items", []) if isinstance(result.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            if clean_text(item.get("sensitivity"), 24) != "low":
                continue
            items.append(
                {
                    "dimension": clean_text(item.get("dimension"), 80),
                    "summary": clean_text(item.get("summary"), 180),
                    "portrait_tier": clean_text(item.get("portrait_tier"), 24),
                    "epistemic_status": clean_text(item.get("epistemic_status"), 40),
                    "confidence": float(item.get("confidence") or 0),
                    "updated_at": clean_text(item.get("updated_at"), 80),
                }
            )
        return {
            "ok": bool(result.get("ok")),
            "read_only": True,
            "code": clean_text(result.get("code"), 80) or "bridge_degraded",
            "items": items,
            "portrait_revision": int(result.get("portrait_revision") or 0),
        }

    async def unified_profile_portrait_status(self, person_id: str) -> dict[str, Any]:
        """Return only bridge synchronization metadata, never portrait text."""
        getter = getattr(self._owner._plugin, "unified_profile_portrait_status", None)
        if not callable(getter):
            return {"ok": False, "read_only": True, "code": "bridge_unavailable", "last_synced_at": "", "portrait_revision": 0}
        try:
            result = await getter(clean_text(person_id, 80))
        except Exception:
            return {"ok": False, "read_only": True, "code": "bridge_degraded", "last_synced_at": "", "portrait_revision": 0}
        if not isinstance(result, dict):
            return {"ok": False, "read_only": True, "code": "bridge_degraded", "last_synced_at": "", "portrait_revision": 0}
        return {
            "ok": bool(result.get("ok")),
            "read_only": True,
            "code": clean_text(result.get("code"), 80) or "bridge_degraded",
            "last_synced_at": clean_text(result.get("last_synced_at"), 80),
            "portrait_revision": int(result.get("portrait_revision") or 0),
        }

    async def run_unified_profile_portrait_batch(self, person_id: str, *, run_day: str = "") -> dict[str, Any]:
        getter = getattr(self._owner._plugin, "run_unified_profile_portrait_batch", None)
        if not callable(getter):
            return {"ok": False, "code": "bridge_unavailable"}
        try:
            result = await getter(clean_text(person_id, 80), run_day=clean_text(run_day, 16))
        except Exception:
            return {"ok": False, "code": "bridge_degraded"}
        return dict(result) if isinstance(result, dict) else {"ok": False, "code": "bridge_degraded"}

    def get_emotional_events(self, *, session_id: str = "", limit: int = 5) -> list[dict[str, Any]]:
        """Temporary exact-window compatibility path for pre-capability callers."""

        safe_session = clean_text(session_id, 220)
        if not safe_session or ":" not in safe_session:
            return []
        getter = getattr(self._owner._plugin, "bridge_get_emotional_events", None)
        if not callable(getter):
            return []
        try:
            events = getter(session_id=safe_session, limit=limit)
        except Exception:
            return []
        return events if isinstance(events, list) else []

    async def list_emotion_events(
        self,
        *,
        delivery_context: Any = None,
        cursor: str = "",
        limit: int = 10,
        **_legacy: Any,
    ) -> dict[str, Any]:
        """List afterglow events only for one opaque Companion delivery context."""

        if not self._owner._is_valid_emotion_delivery_context(delivery_context):
            return self._owner._emotion_delivery_forbidden_result("delivery_context_required")
        return await self._owner._plugin.store.list_emotion_event_deliveries(
            consumer_id=delivery_context.consumer_id,
            bot_id=delivery_context.bot_id,
            scope=delivery_context.scope,
            platform=delivery_context.platform,
            user_id=delivery_context.user_id,
            session_id=delivery_context.session_id,
            allow_cross_window=delivery_context.allow_cross_window,
            cursor=cursor,
            limit=limit,
        )

    async def ack_emotion_events(
        self,
        event_refs: list[dict[str, Any]],
        *,
        delivery_context: Any = None,
        **_legacy: Any,
    ) -> dict[str, Any]:
        """Acknowledge only events delivered inside one opaque identity domain."""

        if not self._owner._is_valid_emotion_delivery_context(delivery_context):
            return self._owner._emotion_ack_forbidden_result("delivery_context_required")
        return await self._owner._plugin.store.ack_emotion_event_deliveries(
            consumer_id=delivery_context.consumer_id,
            event_refs=event_refs,
            bot_id=delivery_context.bot_id,
            scope=delivery_context.scope,
            platform=delivery_context.platform,
            user_id=delivery_context.user_id,
            session_id=delivery_context.session_id,
            allow_cross_window=delivery_context.allow_cross_window,
        )

    async def record_emotion_event(
        self,
        event: dict[str, Any],
        *,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Persist a Companion event only inside an attested private user/Bot domain."""

        if not self._owner._is_valid_emotion_producer_context(producer_context):
            return self._owner._emotion_forbidden_result("producer_context_required")
        return await self._owner._plugin.store.upsert_emotion_event(
            self._owner._attested_emotion_event(event, producer_context)
        )

    async def revise_emotion_event(
        self,
        event: dict[str, Any],
        *,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Persist a later Companion revision only inside its attested domain."""

        if not self._owner._is_valid_emotion_producer_context(producer_context):
            return self._owner._emotion_forbidden_result("producer_context_required")
        return await self._owner._plugin.store.upsert_emotion_event(
            self._owner._attested_emotion_event(event, producer_context)
        )

    async def get_emotion_trace(
        self,
        trace_id: str,
        *,
        requester_context: Any = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return only the scoped, redacted diagnostic projection for a trusted admin."""

        return await self._owner.get_emotion_trace_diagnostic(
            trace_id,
            requester_context,
            limit=limit,
        )

    async def get_emotion_trace_diagnostic(
        self,
        trace_id: str,
        requester_context: Any,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        context = requester_context
        if not self._owner._is_valid_emotion_admin_context(context):
            return {"state": "forbidden", "read_only": True, "items": [], "error_code": "admin_required"}
        items = await self._owner._plugin.store.get_emotion_trace_diagnostic(
            trace_id,
            bot_id=context.bot_id,
            scope=context.scope,
            session_id=context.session_id,
            limit=max(1, min(100, int(limit or 100))),
        )
        return {"state": "ready", "read_only": True, "items": items}

    async def get_emotion_trace_summary(
        self,
        requester_context: Any,
        *,
        cursor: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        context = requester_context
        if not self._owner._is_valid_emotion_admin_context(context):
            return {"state": "forbidden", "read_only": True, "items": [], "next_cursor": "", "error_code": "admin_required"}
        result = await self._owner._plugin.store.get_emotion_trace_summary(
            bot_id=context.bot_id,
            scope=context.scope,
            session_id=context.session_id,
            cursor=clean_text(cursor, 20),
            limit=max(1, min(100, int(limit or 20))),
        )
        return {"state": "ready", "read_only": True, **result}

    def get_relationship_phase(
        self,
        *,
        session_id: str = "",
        scope: str = "private",
        platform: str = "",
        user_id: str = "",
        group_id: str = "",
        bot_id: str = "",
    ) -> dict[str, Any]:
        """Return current relationship phase state for a session."""
        getter = getattr(self._owner._plugin, "_get_relationship_phase", None)
        if not callable(getter):
            return {"phase": "unknown", "momentum": 0.0}
        normalizer = getattr(self._owner._plugin, "session_context_from_bridge", None)
        payload = {
            "session_id": session_id,
            "scope": scope,
            "platform": platform,
            "user_id": user_id,
            "group_id": group_id,
            "bot_id": bot_id,
        }
        ctx = normalizer(payload) if callable(normalizer) else SessionContext(**payload)
        return getter(ctx)

    def peek_relationship_phase(
        self,
        *,
        session_id: str = "",
        scope: str = "private",
        platform: str = "",
        user_id: str = "",
        group_id: str = "",
        bot_id: str = "",
    ) -> dict[str, Any]:
        """Read an existing phase projection without creating default state."""
        fallback = {"observed": False, "phase": "unknown", "momentum_band": "unknown"}
        payload = {
            "session_id": session_id,
            "scope": scope,
            "platform": platform,
            "user_id": user_id,
            "group_id": group_id,
            "bot_id": bot_id,
        }
        if any(type(value) is not str for value in payload.values()):
            return fallback
        try:
            getter = getattr(self._owner._plugin, "_peek_relationship_phase", None)
            if not callable(getter):
                return fallback
            normalizer = getattr(self._owner._plugin, "session_context_from_bridge", None)
            ctx = normalizer(payload) if callable(normalizer) else SessionContext(**payload)
            result = getter(ctx)
        except Exception:
            return fallback
        if type(result) is not dict:
            return fallback
        for key in result:
            if type(key) is not str:
                return fallback

        observed = result.get("observed")
        phase = result.get("phase")
        momentum_band = result.get("momentum_band")
        if type(observed) is not bool or type(phase) is not str or type(momentum_band) is not str:
            return fallback
        if phase not in {"acquaintance", "familiar", "close", "intimate", "deeply_bonded"}:
            return fallback
        if momentum_band not in {"rising", "cooling", "steady"}:
            return fallback
        if not observed:
            return fallback
        projection: dict[str, Any] = {
            "observed": True,
            "phase": phase,
            "momentum_band": momentum_band,
        }
        touch_count = result.get("touch_count")
        if touch_count is not None:
            if type(touch_count) is not int or not 0 <= touch_count <= 256:
                return fallback
            projection["touch_count"] = touch_count
        return projection

    def get_recent_emotional_state(
        self,
        *,
        exclude_session_id: str = "",
        window_seconds: float = 1800.0,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Explain why the identity-free cross-window aggregate is unavailable."""
        _ = (exclude_session_id, window_seconds, limit)
        return {
            "enabled": False,
            "state": "migration_required",
            "error_code": "delivery_context_required",
            "total": 0,
            "scar_count": 0,
            "warm_count": 0,
            "vulnerable_count": 0,
        }
