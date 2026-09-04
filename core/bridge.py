from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from typing import Any
from zoneinfo import ZoneInfo

from . import bot_personal_contract
from .bot_personal_dto import BotPersonalArchiveDTO, build_bot_personal_archive
from .capability_probe import CapabilityCache, PROFILE_NAMES as C4_PROFILE_NAMES, build_capability_snapshot
from .context_consumer import consume_context_projection
from .models import EntityRef, MemoryRecord, SessionContext, clean_text
from .namespace_capability import namespace_capability_descriptor
from .namespace import build_namespace_context, validate_namespace_context
from .person_projection import consume_person_projection
from .scoped_store import ScopedStore, ScopedStoreError


LOCAL_TZ = ZoneInfo("Asia/Shanghai")

_PRIVATE_COMPANION_ROOT = "astrbot_plugin_private_companion"
_PRIVATE_COMPANION_NAMES = {"PrivateCompanion", "private_companion"}
_EMOTION_INGRESS_ORIGINS = {"interaction", "system_condition"}
_EMOTION_DELIVERY_CONSUMER = "private_companion.daily_state"
_COMPANION_PROJECTION_SECRET = secrets.token_bytes(32)


class _AuthenticatedCompanionProjection(dict):
    """Signed request-scoped dict accepted only after bridge attestation."""

    __slots__ = (
        "_bot_id",
        "_kind",
        "_person_id",
        "_platform",
        "_scope",
        "_session_id",
        "_signature",
    )

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        kind: str,
        bot_id: str,
        platform: str,
        person_id: str,
        scope: str,
        session_id: str,
        signature: str,
    ) -> None:
        dict.__init__(self, payload)
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_bot_id", bot_id)
        object.__setattr__(self, "_platform", platform)
        object.__setattr__(self, "_person_id", person_id)
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_session_id", session_id)
        object.__setattr__(self, "_signature", signature)

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("authenticated Companion projections are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __setattr__ = _immutable
    __delattr__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _companion_projection_signature(
    payload: dict[str, Any],
    *,
    kind: str,
    bot_id: str,
    platform: str,
    person_id: str,
    scope: str,
    session_id: str,
) -> str:
    body = json.dumps(
        {
            "kind": kind,
            "bot_id": bot_id,
            "platform": platform,
            "person_id": person_id,
            "scope": scope,
            "session_id": session_id,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_COMPANION_PROJECTION_SECRET, body, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class _EmotionProducerCapability:
    """Non-serializable capability bound to one live Companion plugin instance."""

    _bridge: Any
    _producer: Any
    _token: object


@dataclass(frozen=True, slots=True)
class _EmotionPageAdminCapability:
    """Non-serializable capability bound to this bridge's Page API instance."""

    _bridge: Any
    _page_api: Any
    _token: object


@dataclass(frozen=True, slots=True)
class _EmotionProducerContext:
    """Opaque, scoped authorization context for Companion emotion ingress."""

    _bridge: Any
    _capability: _EmotionProducerCapability
    bot_id: str
    platform: str
    scope: str
    session_id: str
    user_id: str


@dataclass(frozen=True, slots=True)
class _EmotionDeliveryContext:
    """Opaque, scoped authorization context for afterglow delivery and ack."""

    _bridge: Any
    _capability: _EmotionProducerCapability
    allow_cross_window: bool
    bot_id: str
    consumer_id: str
    platform: str
    scope: str
    session_id: str
    user_id: str


@dataclass(frozen=True, slots=True)
class _EmotionAdminContext:
    """Opaque, scoped authorization context for redacted admin diagnostics."""

    _bridge: Any
    _capability: _EmotionPageAdminCapability
    bot_id: str
    scope: str
    session_id: str

_COMPANION_RELATIONSHIP_PHASES = {
    "deeply_distant",
    "strongly_distant",
    "distant",
    "acquaintance",
    "familiar",
    "close",
    "intimate",
    "deeply_bonded",
}
_COMPANION_INTERACTION_BANDS = {
    "avoidant",
    "hurt",
    "relaxed",
    "lively",
    "warm",
    "close",
    "affectionate",
}
_COMPANION_EXPRESSION_CONTRACTS = {"companion_interaction_expression.v1", "companion_interaction_expression.v2"}
_COMPANION_EXPRESSION_PACING = {"slow", "steady", "bright"}
_COMPANION_EXPRESSION_DIRECTNESS = {"indirect", "natural", "direct"}
_COMPANION_EXPRESSION_VALIDATION = {"none", "acknowledge", "support_first"}
_COMPANION_EXPRESSION_DISCLOSURE = {"none", "light", "allowed"}
_COMPANION_EXPRESSION_HUMOR = {"off", "light", "playful"}
_COMPANION_EXPRESSION_TOPIC = {"reply_only", "followup", "shared_topic"}
_COMPANION_EXPRESSION_BEHAVIORS = {
    "acknowledge",
    "brief_reply",
    "give_space",
    "reply",
    "clarify",
    "light_humor",
    "followup",
    "support",
    "shared_ritual",
    "affectionate_expression",
}
_COMPANION_EXPRESSION_SAFETY_MODES = {
    "normal",
    "contact_boundary_passive",
    "contact_boundary",
    "p4_blocked",
}
_COMPANION_EXPRESSION_BLOCKERS = {"contact_boundary", "p4_safety"}
_COMPANION_EXPRESSION_REASON_CODES = {
    "relationship_baseline_retained",
    "interaction_band_applied",
    "administrator_override_applied",
    "owner_role_required",
    "contact_boundary_passive_reengagement",
    "p4_warmth_cap_applied",
    "relationship_tone_applied",
    "relationship_address_applied",
    "relationship_followup_cap",
    "intent_followup_suppressed",
    "low_energy_expression_cap",
    "down_mood_expression_cap",
    "up_mood_expression_lift",
    "affect_modulation_applied",
    "relationship_proactive_cap",
    "interaction_proactive_suppressed",
    "schedule_proactive_suppressed",
    "p4_blocked",
    "contact_boundary",
}


def sanitize_companion_expression_decision(value: Any) -> dict[str, Any]:
    """Accept only the bounded, request-scoped Companion expression contract."""

    fallback = {"status": "invalid", "read_only": True, "decision": {}}
    if type(value) is not dict or value.get("contract") not in _COMPANION_EXPRESSION_CONTRACTS:
        return fallback
    expression_band = value.get("expression_band")
    if type(expression_band) is not str or expression_band not in _COMPANION_INTERACTION_BANDS:
        return fallback
    allowed_behaviors = value.get("allowed_behaviors")
    if type(allowed_behaviors) not in {list, tuple} or len(allowed_behaviors) > 12:
        return fallback
    if any(type(item) is not str or item not in _COMPANION_EXPRESSION_BEHAVIORS for item in allowed_behaviors):
        return fallback
    if len(set(allowed_behaviors)) != len(allowed_behaviors):
        return fallback
    safety_mode = value.get("safety_mode")
    if type(safety_mode) is not str or safety_mode not in _COMPANION_EXPRESSION_SAFETY_MODES:
        return fallback
    blocker = value.get("blocker")
    if blocker is not None and (type(blocker) is not str or blocker not in _COMPANION_EXPRESSION_BLOCKERS):
        return fallback
    reason_codes = value.get("reason_codes")
    if type(reason_codes) not in {list, tuple} or len(reason_codes) > 24:
        return fallback
    if any(type(item) is not str or item not in _COMPANION_EXPRESSION_REASON_CODES for item in reason_codes):
        return fallback
    if type(value.get("followup")) is not bool:
        return fallback
    contract = value.get("contract")
    dimensions: dict[str, str] = {}
    if contract == "companion_interaction_expression.v2":
        dimension_specs = {
            "pacing": _COMPANION_EXPRESSION_PACING,
            "directness": _COMPANION_EXPRESSION_DIRECTNESS,
            "validation_style": _COMPANION_EXPRESSION_VALIDATION,
            "self_disclosure": _COMPANION_EXPRESSION_DISCLOSURE,
            "humor_mode": _COMPANION_EXPRESSION_HUMOR,
            "topic_initiative": _COMPANION_EXPRESSION_TOPIC,
        }
        for key, allowed in dimension_specs.items():
            item = value.get(key)
            if type(item) is not str or item not in allowed:
                return fallback
            dimensions[key] = item
    return {
        "status": "accepted",
        "read_only": True,
        "decision": {
            "contract": contract,
            "expression_band": expression_band,
            "allowed_behaviors": list(allowed_behaviors),
            "safety_mode": safety_mode,
            "blocker": blocker,
            "reason_codes": list(reason_codes),
            "followup": value["followup"],
            **dimensions,
        },
    }


def sanitize_companion_relationship_projection(value: Any) -> dict[str, Any]:
    fallback = {"status": "invalid", "read_only": True, "projection": {}}
    if type(value) is not dict:
        return fallback
    if value.get("schema_version") != "chat.relationship_projection.v1":
        return fallback
    if value.get("authority") != "private_companion.relationship_score" or value.get("read_only") is not True:
        return fallback
    phase_key = value.get("phase_key")
    if type(phase_key) is not str or phase_key not in _COMPANION_RELATIONSHIP_PHASES:
        return fallback
    score = value.get("score")
    if type(score) is not int or not -1200 <= score <= 1200:
        return fallback
    soft = value.get("soft_behaviors")
    if type(soft) is not dict or any(type(item) is not bool for item in soft.values()):
        return fallback
    try:
        proactive_care_limit = int(value.get("proactive_care_limit") or 0)
    except (TypeError, ValueError):
        proactive_care_limit = 0
    projection = {
        "schema_version": "chat.relationship_projection.v1",
        "authority": "private_companion.relationship_score",
        "read_only": True,
        "score": score,
        "phase_key": phase_key,
        "phase_label": clean_text(value.get("phase_label"), 40),
        "tone": clean_text(value.get("tone"), 160),
        "address_level": clean_text(value.get("address_level"), 120),
        "proactive_care_limit": max(0, min(30, proactive_care_limit)),
        "soft_behaviors": {
            key: bool(soft.get(key, False))
            for key in (
                "allow_playful_jokes",
                "allow_followup",
                "allow_memory_mention",
                "allow_daily_care",
            )
        },
    }
    relationship_mode = value.get("relationship_mode")
    if relationship_mode in {"normal", "owner_exclusive"}:
        projection["relationship_mode"] = relationship_mode
    current_interaction = value.get("current_interaction")
    if type(current_interaction) is dict:
        expression_band = current_interaction.get("expression_band")
        if type(expression_band) is str and expression_band in _COMPANION_INTERACTION_BANDS:
            interaction_projection = {
                "expression_band": expression_band,
                "label": clean_text(current_interaction.get("label"), 40),
                "source": clean_text(current_interaction.get("source"), 40),
                "reason": clean_text(current_interaction.get("reason"), 120),
                "manual_override": current_interaction.get("manual_override") is True,
            }
            dynamics_version = current_interaction.get("dynamics_version")
            recovery_band = current_interaction.get("recovery_band")
            expires_at = current_interaction.get("expires_at")
            projection_revision = current_interaction.get("projection_revision")
            if dynamics_version == "interaction_dynamics.v1" and recovery_band in {"steady", "recovering", "reinforced"}:
                if type(expires_at) not in {int, float} or type(expires_at) is bool:
                    return fallback
                if type(projection_revision) is not int or not 1 <= projection_revision <= 1000000:
                    return fallback
                interaction_projection.update({
                    "dynamics_version": dynamics_version,
                    "recovery_band": recovery_band,
                    "expires_at": max(0.0, min(10**12, float(expires_at))),
                    "projection_revision": projection_revision,
                })
            projection["current_interaction"] = interaction_projection
    return {"status": "accepted", "read_only": True, "projection": projection}


def consume_authenticated_companion_projection(
    value: Any,
    *,
    kind: str,
    expected_person_id: str = "",
    expected_scope: str = "",
    expected_session_id: str = "",
    expected_platform: str = "",
    expected_bot_id: str = "",
) -> dict[str, Any]:
    """Verify a bridge-sealed projection and then apply its schema sanitizer."""

    fallback = {"status": "invalid", "read_only": True}
    if type(value) is not _AuthenticatedCompanionProjection:
        return {**fallback, "error_code": "projection_attestation_required"}
    attrs = {
        "person_id": value._person_id,
        "scope": value._scope,
        "session_id": value._session_id,
        "platform": value._platform,
        "bot_id": value._bot_id,
    }
    expected = {
        "person_id": clean_text(expected_person_id, 160),
        "scope": clean_text(expected_scope, 24).lower(),
        "session_id": clean_text(expected_session_id, 220),
        "platform": clean_text(expected_platform, 80),
        "bot_id": clean_text(expected_bot_id, 160),
    }
    for key, expected_value in expected.items():
        if expected_value and attrs[key] != expected_value:
            return {**fallback, "error_code": f"projection_{key}_mismatch"}
    if (
        not attrs["person_id"]
        or attrs["scope"] != "private"
        or not attrs["session_id"]
        or not attrs["platform"]
        or not attrs["bot_id"]
        or not attrs["session_id"].startswith(f"{attrs['platform']}:")
        or value._kind != kind
    ):
        return {**fallback, "error_code": "projection_domain_invalid"}
    try:
        expected_signature = _companion_projection_signature(
            dict(value),
            kind=value._kind,
            bot_id=attrs["bot_id"],
            platform=attrs["platform"],
            person_id=attrs["person_id"],
            scope=attrs["scope"],
            session_id=attrs["session_id"],
        )
    except (TypeError, ValueError, OverflowError):
        return {**fallback, "error_code": "projection_signature_invalid"}
    if not hmac.compare_digest(expected_signature, value._signature):
        return {**fallback, "error_code": "projection_signature_invalid"}
    if kind == "relationship":
        return sanitize_companion_relationship_projection(dict(value))
    if kind == "expression":
        return sanitize_companion_expression_decision(dict(value))
    return {**fallback, "error_code": "projection_kind_invalid"}


def _local_time_label(value: Any) -> str:
    text = clean_text(value, 80)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return text


class MemoryCompanionBridge:
    """Public bridge for other plugins.

    The bridge intentionally accepts structured fields. A caller should say
    whether something is a bot action, a persona-life fragment, a real user
    fact, or an imported summary instead of handing over vague prose.
    """

    def __init__(self, plugin: Any):
        self._plugin = plugin
        self.__scoped_store: ScopedStore | None = None
        self.__scoped_store_resolved = False
        self._capability_cache = CapabilityCache()
        self._emotion_producer_token = object()
        self._emotion_page_admin_token = object()
        self._active = True

    @property
    def _scoped_store(self) -> ScopedStore | None:
        """Resolve the namespace store only when a namespace API is used.

        Bot-personal capability probes are pure contract probes and must not
        touch plugin services or databases merely because a Bridge object was
        constructed.
        """
        if not self.__scoped_store_resolved:
            candidate = getattr(self._plugin, "scoped_store", None)
            self.__scoped_store = candidate if isinstance(candidate, ScopedStore) else None
            self.__scoped_store_resolved = True
        return self.__scoped_store

    def bridge_lifecycle_status(self) -> dict[str, Any]:
        """Expose only whether this in-process bridge can still serve calls."""
        return {"active": self._active}

    def deactivate(self) -> None:
        """Revoke all issued capabilities before plugin service shutdown."""
        self._active = False
        self._emotion_producer_token = object()
        self._emotion_page_admin_token = object()

    def register_emotion_producer(self, producer: Any) -> Any | None:
        """Issue a private Companion capability only to a live registered plugin."""

        if not self._active or not self._is_registered_private_companion(producer):
            return None
        return _EmotionProducerCapability(self, producer, self._emotion_producer_token)

    def register_private_companion(self, producer: Any) -> Any | None:
        """Issue the shared producer capability used by protected Companion APIs."""

        return self.register_emotion_producer(producer)

    def register_bot_personal_producer(self, producer: Any) -> Any | None:
        """Compatibility name for the same scoped Private Companion capability."""

        return self.register_emotion_producer(producer)

    def create_emotion_producer_context(
        self,
        capability: Any,
        *,
        bot_id: str,
        scope: str,
        platform: str,
        user_id: str,
        session_id: str,
    ) -> Any | None:
        """Bind a Companion capability to one private user/Bot delivery domain."""

        if not self._is_valid_emotion_producer_capability(capability):
            return None
        normalized = self._normalize_emotion_domain(
            bot_id=bot_id,
            scope=scope,
            platform=platform,
            user_id=user_id,
            session_id=session_id,
        )
        if normalized is None:
            return None
        return _EmotionProducerContext(self, capability, **normalized)

    def create_emotion_delivery_context(
        self,
        capability: Any,
        *,
        bot_id: str,
        scope: str,
        platform: str,
        user_id: str,
        session_id: str,
        consumer_id: str = _EMOTION_DELIVERY_CONSUMER,
        allow_cross_window: bool = False,
    ) -> Any | None:
        """Bind Companion afterglow delivery to one trusted private identity domain."""

        if not self._is_valid_emotion_producer_capability(capability):
            return None
        if clean_text(consumer_id, 80) != _EMOTION_DELIVERY_CONSUMER:
            return None
        if type(allow_cross_window) is not bool:
            return None
        if allow_cross_window and not self._cross_window_emotion_enabled():
            return None
        normalized = self._normalize_emotion_domain(
            bot_id=bot_id,
            scope=scope,
            platform=platform,
            user_id=user_id,
            session_id=session_id,
        )
        if normalized is None:
            return None
        return _EmotionDeliveryContext(
            self,
            capability,
            consumer_id=_EMOTION_DELIVERY_CONSUMER,
            allow_cross_window=allow_cross_window,
            **normalized,
        )

    def bind_emotion_page_api(self, page_api: Any) -> Any | None:
        """Issue a private diagnostic capability to this Memory plugin's Page API."""

        if not self._active:
            return None
        page_plugin = getattr(page_api, "plugin", None)
        if page_plugin is not self._plugin and getattr(page_plugin, "service", None) is not self._plugin:
            return None
        return _EmotionPageAdminCapability(self, page_api, self._emotion_page_admin_token)

    def create_emotion_admin_context(
        self,
        capability: Any,
        *,
        bot_id: str,
        scope: str,
        session_id: str,
    ) -> Any | None:
        """Create a scoped redacted-diagnostic context after page auth succeeds."""

        if not self._is_valid_emotion_page_admin_capability(capability):
            return None
        normalized_bot_id = clean_text(bot_id, 160)
        normalized_scope = clean_text(scope, 24).lower()
        normalized_session_id = clean_text(session_id, 220)
        if not normalized_bot_id or normalized_scope not in {"private", "group"} or not normalized_session_id:
            return None
        return _EmotionAdminContext(
            self,
            capability,
            bot_id=normalized_bot_id,
            scope=normalized_scope,
            session_id=normalized_session_id,
        )

    def _is_registered_private_companion(self, producer: Any) -> bool:
        context = getattr(self._plugin, "context", None)
        getter = getattr(context, "get_all_stars", None)
        if not callable(getter):
            return False
        try:
            stars = getter()
        except Exception:
            return False
        if not isinstance(stars, (list, tuple)):
            return False
        for metadata in stars:
            registered_instance = getattr(metadata, "star_cls", None)
            registered_type = getattr(metadata, "star_cls_type", None)
            # AstrBot's StarMetadata stores the live plugin object in
            # ``star_cls`` and its class in ``star_cls_type``.  Companion's
            # adapter registers ``type(self)``; accept that exact class only
            # when it is paired with the exact live instance.  Keep the
            # instance form for older adapters, but never fall back to names
            # or ``isinstance`` checks.
            producer_matches = producer is registered_instance
            if producer is registered_type:
                producer_matches = (
                    registered_instance is not None
                    and type(registered_instance) is registered_type
                )
            elif producer_matches and registered_type is not None:
                producer_matches = type(registered_instance) is registered_type
            if not producer_matches:
                continue
            if getattr(metadata, "activated", True) is not True:
                continue
            root = clean_text(getattr(metadata, "root_dir_name", ""), 120)
            name = clean_text(getattr(metadata, "name", ""), 120)
            if root == _PRIVATE_COMPANION_ROOT or name in _PRIVATE_COMPANION_NAMES:
                return True
        return False

    def _is_valid_emotion_producer_capability(self, capability: Any) -> bool:
        return (
            self._active
            and type(capability) is _EmotionProducerCapability
            and capability._bridge is self
            and capability._token is self._emotion_producer_token
            and self._is_registered_private_companion(capability._producer)
        )

    def _producer_capability_from(self, value: Any) -> Any:
        if type(value) in {_EmotionProducerContext, _EmotionDeliveryContext}:
            return value._capability
        return value

    def _is_valid_private_companion_capability(self, value: Any) -> bool:
        return self._is_valid_emotion_producer_capability(
            self._producer_capability_from(value)
        )

    def _cross_window_emotion_enabled(self) -> bool:
        config = getattr(self._plugin, "config", None)
        getter = getattr(config, "bool", None)
        if not callable(getter):
            return False
        try:
            return getter(
                "private_companion_bridge.cross_window_emotional_continuity_enabled",
                False,
            ) is True
        except Exception:
            return False

    def _is_valid_emotion_page_admin_capability(self, capability: Any) -> bool:
        return (
            self._active
            and type(capability) is _EmotionPageAdminCapability
            and capability._bridge is self
            and capability._token is self._emotion_page_admin_token
            and (
                getattr(capability._page_api, "plugin", None) is self._plugin
                or getattr(getattr(capability._page_api, "plugin", None), "service", None) is self._plugin
            )
        )

    @staticmethod
    def _normalize_emotion_domain(
        *,
        bot_id: Any,
        scope: Any,
        platform: Any,
        user_id: Any,
        session_id: Any,
    ) -> dict[str, str] | None:
        normalized = {
            "bot_id": clean_text(bot_id, 160),
            "scope": clean_text(scope, 24).lower(),
            "platform": clean_text(platform, 80),
            "user_id": clean_text(user_id, 160),
            "session_id": clean_text(session_id, 220),
        }
        if not all(normalized.values()) or normalized["scope"] != "private":
            return None
        if not normalized["session_id"].startswith(f"{normalized['platform']}:"):
            return None
        return normalized

    def _is_valid_emotion_producer_context(self, context: Any) -> bool:
        return (
            type(context) is _EmotionProducerContext
            and context._bridge is self
            and self._is_valid_emotion_producer_capability(context._capability)
            and self._normalize_emotion_domain(
                bot_id=context.bot_id,
                scope=context.scope,
                platform=context.platform,
                user_id=context.user_id,
                session_id=context.session_id,
            ) is not None
        )

    def _is_valid_emotion_delivery_context(self, context: Any) -> bool:
        return (
            type(context) is _EmotionDeliveryContext
            and context._bridge is self
            and self._is_valid_emotion_producer_capability(context._capability)
            and context.consumer_id == _EMOTION_DELIVERY_CONSUMER
            and type(context.allow_cross_window) is bool
            and (not context.allow_cross_window or self._cross_window_emotion_enabled())
            and self._normalize_emotion_domain(
                bot_id=context.bot_id,
                scope=context.scope,
                platform=context.platform,
                user_id=context.user_id,
                session_id=context.session_id,
            ) is not None
        )

    def _is_valid_emotion_admin_context(self, context: Any) -> bool:
        return (
            type(context) is _EmotionAdminContext
            and context._bridge is self
            and self._is_valid_emotion_page_admin_capability(context._capability)
            and bool(clean_text(context.bot_id, 160))
            and clean_text(context.scope, 24).lower() in {"private", "group"}
            and bool(clean_text(context.session_id, 220))
        )

    def _seal_companion_projection(
        self,
        projection: Any,
        *,
        kind: str,
        capability: Any,
        bot_id: Any,
        platform: Any,
        user_id: Any,
        scope: Any,
        session_id: Any,
    ) -> dict[str, Any]:
        if not self._is_valid_private_companion_capability(capability):
            return {"status": "invalid", "read_only": True, "error_code": "producer_capability_required"}
        if type(capability) is _EmotionProducerContext:
            bound = {
                "bot_id": capability.bot_id,
                "platform": capability.platform,
                "user_id": capability.user_id,
                "scope": capability.scope,
                "session_id": capability.session_id,
            }
            supplied = {
                "bot_id": clean_text(bot_id, 160),
                "platform": clean_text(platform, 80),
                "user_id": clean_text(user_id, 160),
                "scope": clean_text(scope, 24).lower(),
                "session_id": clean_text(session_id, 220),
            }
            if any(supplied[key] and supplied[key] != bound[key] for key in supplied):
                return {"status": "invalid", "read_only": True, "error_code": "projection_context_mismatch"}
            bot_id = bound["bot_id"]
            platform = bound["platform"]
            user_id = bound["user_id"]
            scope = bound["scope"]
            session_id = bound["session_id"]
        domain = self._normalize_emotion_domain(
            bot_id=bot_id,
            scope=scope,
            platform=platform,
            user_id=user_id,
            session_id=session_id,
        )
        if domain is None:
            return {"status": "invalid", "read_only": True, "error_code": "projection_domain_invalid"}
        sanitizer = (
            sanitize_companion_relationship_projection
            if kind == "relationship"
            else sanitize_companion_expression_decision
        )
        consumed = sanitizer(projection)
        if consumed.get("status") != "accepted":
            return consumed
        key = "projection" if kind == "relationship" else "decision"
        payload = consumed.get(key)
        if not isinstance(payload, dict):
            return {"status": "invalid", "read_only": True, "error_code": "projection_payload_invalid"}
        signature = _companion_projection_signature(
            payload,
            kind=kind,
            bot_id=domain["bot_id"],
            platform=domain["platform"],
            person_id=domain["user_id"],
            scope=domain["scope"],
            session_id=domain["session_id"],
        )
        sealed = _AuthenticatedCompanionProjection(
            payload,
            kind=kind,
            bot_id=domain["bot_id"],
            platform=domain["platform"],
            person_id=domain["user_id"],
            scope=domain["scope"],
            session_id=domain["session_id"],
            signature=signature,
        )
        return {"status": "accepted", "read_only": True, key: sealed}

    def consume_relationship_projection(
        self,
        projection: Any,
        *,
        producer_capability: Any = None,
        producer_context: Any = None,
        bot_id: str = "",
        platform: str = "",
        user_id: str = "",
        scope: str = "private",
        session_id: str = "",
    ) -> dict[str, Any]:
        """Validate and seal a Companion relationship projection for one request."""

        authority = producer_capability if producer_capability is not None else producer_context
        return self._seal_companion_projection(
            projection,
            kind="relationship",
            capability=authority,
            bot_id=bot_id,
            platform=platform,
            user_id=user_id,
            scope=scope,
            session_id=session_id,
        )

    def consume_expression_decision(
        self,
        decision: Any,
        *,
        producer_capability: Any = None,
        producer_context: Any = None,
        bot_id: str = "",
        platform: str = "",
        user_id: str = "",
        scope: str = "private",
        session_id: str = "",
    ) -> dict[str, Any]:
        """Validate and seal a Companion expression decision for one request."""

        authority = producer_capability if producer_capability is not None else producer_context
        return self._seal_companion_projection(
            decision,
            kind="expression",
            capability=authority,
            bot_id=bot_id,
            platform=platform,
            user_id=user_id,
            scope=scope,
            session_id=session_id,
        )

    def create_user_memory_context(self, capability: Any, **kwargs: Any) -> Any | None:
        """Name the scoped context explicitly for user-summary consumers."""

        return self.create_emotion_producer_context(capability, **kwargs)

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
            occurred_at=occurred_at,
        )

    async def record_external_memory(
        self,
        *,
        user_id: str = "",
        content: str = "",
        summary: str = "",
        payload: dict[str, Any] | None = None,
        memory_type: str = "external_memory",
        source_plugin: str = "external",
        occurred_at: str = "",
        idempotency_key: str = "",
        memory_id: str = "",
        importance: float = 0.62,
        confidence: float = 0.82,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        long_term: bool = True,
    ) -> dict[str, Any]:
        """Write one user-scoped long-term memory from an external source.

        ``user_id`` is intentionally the only required identity field.  The
        memory service fixes the record to that user's private scope, so an
        external plugin cannot accidentally write a group/public memory by
        passing arbitrary session fields.
        """
        writer = getattr(self._plugin, "record_external_memory", None)
        if not callable(writer):
            return {
                "ok": False,
                "state": "unsupported",
                "memory_id": "",
                "deduplicated": False,
                "error_code": "record_external_memory_unavailable",
            }
        result = await writer(
            user_id=user_id,
            content=content,
            summary=summary,
            payload=payload,
            memory_type=memory_type,
            source_plugin=source_plugin,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            memory_id=memory_id,
            importance=importance,
            confidence=confidence,
            tags=tags,
            metadata=metadata,
            long_term=long_term,
        )
        if isinstance(result, dict):
            return dict(result)
        return {
            "ok": bool(result),
            "state": "stored" if result else "degraded",
            "memory_id": clean_text(result, 120),
            "deduplicated": False,
            "error_code": None if result else "invalid_result",
        }

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
        return await self.record_event(
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
        if not self._is_valid_private_companion_capability(authority):
            return {**base, "state": "forbidden", "error_code": "producer_capability_required"}
        try:
            dto = build_bot_personal_archive(envelope)
        except Exception as exc:
            return {**base, "state": "invalid", "error_code": getattr(exc, "error_code", "invalid")}
        if dto.canonical_schema_version >= bot_personal_contract.BOT_PERSONAL_CANONICAL_SCHEMA_VERSION:
            capability = self._producer_capability_from(authority)
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
            recorder = getattr(self._plugin, "record_bot_personal_archive", None)
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
        return await self.record_bot_personal_archive(
            envelope,
            producer_capability=producer_capability,
            producer_context=producer_context,
        )

    async def record_group_moment_portrait(
        self,
        person_ref: dict[str, Any],
        candidates: list[dict[str, Any]],
        *,
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
        message_id: str = "",
        producer_capability: Any = None,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """接受私伴群聊名场面收敛的画像候选，沉降到画像车道（group_moment）。

        与自述画像车道隔离：维度仅限 communication_preference / boundary，
        事实 producer_kind=group_moment、epistemic_status=observed，可参与每日
        聚合但不被当作客观事实。私有 Companion 能力校验失败时 fail-closed。
        """
        base = {
            "ok": False,
            "facts": 0,
            "person_id": "",
            "state": "degraded",
            "error_code": None,
        }
        authority = producer_capability if producer_capability is not None else producer_context
        if not self._is_valid_private_companion_capability(authority):
            return {**base, "state": "forbidden", "error_code": "producer_capability_required"}
        portraits = getattr(getattr(self._plugin, "service", None), "portraits", None)
        if portraits is None or not callable(getattr(portraits, "record_group_moment_portrait", None)):
            return {**base, "error_code": "portrait_service_unavailable"}
        try:
            result = await portraits.record_group_moment_portrait(
                person_ref,
                candidates,
                scope=scope,
                session_id=session_id,
                group_id=group_id,
                message_id=message_id,
            )
        except Exception as exc:
            return {**base, "error_code": "portrait_bridge_exception"}
        if not isinstance(result, dict):
            return {**base, "error_code": "invalid_portrait_response"}
        return {
            "ok": bool(result.get("ok")),
            "facts": int(result.get("facts") or 0),
            "person_id": clean_text(result.get("person_id"), 80),
            "state": "recorded" if result.get("ok") else "degraded",
            "error_code": result.get("code"),
        }

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
            if not self._is_valid_private_companion_capability(producer_capability):
                return {**base, "state": "forbidden", "degraded": False, "pending": False, "error_code": "producer_capability_required"}
            capability = self._producer_capability_from(producer_capability)
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
            getter = getattr(self._plugin, "read_bot_personal_profile", None)
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
        if not self._is_valid_emotion_producer_context(requester_context):
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
            getter = getattr(self._plugin, "read_user_memory_summary", None)
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
        getter = getattr(self._plugin, "read_unified_profile_portrait", None)
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
        getter = getattr(self._plugin, "unified_profile_portrait_status", None)
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
        getter = getattr(self._plugin, "run_unified_profile_portrait_batch", None)
        if not callable(getter):
            return {"ok": False, "code": "bridge_unavailable"}
        try:
            result = await getter(clean_text(person_id, 80), run_day=clean_text(run_day, 16))
        except Exception:
            return {"ok": False, "code": "bridge_degraded"}
        return dict(result) if isinstance(result, dict) else {"ok": False, "code": "bridge_degraded"}

    async def search_bot_personal_profile(
        self,
        query: str = "",
        *,
        limit: int = 10,
        producer_capability: Any = None,
    ) -> dict[str, Any]:
        return await self.read_bot_personal_profile(
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
        locked_authorized = self._is_valid_private_companion_capability(authority)
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
            getter = getattr(self._plugin, "read_bot_profile", None)
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

        return await self.read_bot_profile(profile, query=query, **kwargs)

    async def search(
        self,
        query: str,
        *,
        session_context: SessionContext | dict[str, Any] | None = None,
        top_k: int | None = None,
        p5_attestation: Any = None,
        p5_attestation_consumer: Any = None,
    ) -> list[dict[str, Any]]:
        return await self._plugin.bridge_search(
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
        return await self._plugin.bridge_compose_injection(
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
        return await self._plugin.bridge_compose_context(
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
        return await self._plugin.tool_remember(event, content, note_type=note_type)

    async def recall(
        self,
        *,
        event: Any,
        query: str,
        top_k: int = 5,
        p5_attestation: Any = None,
        p5_attestation_consumer: Any = None,
    ) -> dict[str, Any]:
        return await self._plugin.tool_recall(
            event,
            query,
            top_k=top_k,
            p5_attestation=p5_attestation,
            p5_attestation_consumer=p5_attestation_consumer,
        )

    def p5_capability_status(self) -> dict[str, Any]:
        getter = getattr(self._plugin, "p5_capability_status", None)
        if not callable(getter):
            return {"state": "degraded", "error_code": "p5_status_unavailable"}
        try:
            result = getter()
        except Exception:
            return {"state": "degraded", "error_code": "p5_status_exception"}
        return dict(result) if isinstance(result, dict) else {"state": "degraded", "error_code": "p5_status_invalid"}

    def provenance_snapshot(self) -> dict[str, Any]:
        getter = getattr(self._plugin, "provenance_snapshot", None)
        if not callable(getter):
            return {"records": {}, "operation_count": 0, "state": "degraded"}
        result = getter()
        return dict(result) if isinstance(result, dict) else {"records": {}, "operation_count": 0, "state": "degraded"}

    def provenance_preview(self, candidates: list[dict[str, Any]], *, operation_ref_hash: str) -> dict[str, Any]:
        getter = getattr(self._plugin, "provenance_preview", None)
        if not callable(getter):
            return {"mode": "preview", "readonly": True, "write_count": 0, "error_codes": ["unavailable"]}
        result = getter(candidates, operation_ref_hash=operation_ref_hash)
        return dict(result) if isinstance(result, dict) else {"mode": "preview", "readonly": True, "write_count": 0, "error_codes": ["invalid_result"]}

    async def provenance_apply(self, operation: dict[str, Any]) -> dict[str, Any]:
        getter = getattr(self._plugin, "provenance_apply", None)
        if not callable(getter):
            return {"ok": False, "state": "degraded", "error_code": "unavailable"}
        result = await getter(operation)
        return dict(result) if isinstance(result, dict) else {"ok": False, "state": "degraded", "error_code": "invalid_result"}

    async def provenance_backup(self) -> dict[str, Any]:
        getter = getattr(self._plugin, "provenance_backup", None)
        if not callable(getter):
            return {"ok": False, "state": "degraded", "error_code": "unavailable"}
        result = await getter()
        return dict(result) if isinstance(result, dict) else {"ok": False, "state": "degraded", "error_code": "invalid_result"}

    async def provenance_rollback(self, operation: dict[str, Any]) -> dict[str, Any]:
        getter = getattr(self._plugin, "provenance_rollback", None)
        if not callable(getter):
            return {"ok": False, "state": "degraded", "error_code": "unavailable"}
        result = await getter(operation)
        return dict(result) if isinstance(result, dict) else {"ok": False, "state": "degraded", "error_code": "invalid_result"}

    async def create_note(self, *, event: Any, title: str, content: str = "") -> dict[str, Any]:
        return await self._plugin.tool_note_create(event, title, content)

    async def read_notes(self, *, event: Any, query: str = "", limit: int = 5) -> dict[str, Any]:
        return await self._plugin.tool_note_read(event, query, limit=limit)

    async def delete_note(self, *, event: Any, memory_id: str = "", title: str = "") -> dict[str, Any]:
        return await self._plugin.tool_note_delete(event, memory_id, title=title)

    def coordination_status(self) -> dict[str, Any]:
        try:
            getter = getattr(self._plugin, "companion_coordination_status", None)
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

    def consume_person_projection(
        self,
        projection: Any,
        expected_identity_key: str = "",
        expected_person_id: str = "",
        *,
        companion_available: bool = True,
    ) -> dict[str, Any]:
        """Validate a companion-owned person projection without writing memory state."""
        return consume_person_projection(
            projection,
            expected_identity_key=expected_identity_key,
            expected_person_id=expected_person_id,
            companion_available=companion_available,
        )

    def consume_context_projection(
        self,
        context: Any,
        expected_person_id: str = "",
        expected_scope: str = "",
        *,
        companion_available: bool = True,
    ) -> dict[str, Any]:
        """Validate a P3 projection without creating people or storing raw text."""
        return consume_context_projection(
            context,
            expected_person_id=expected_person_id,
            expected_scope=expected_scope,
            companion_available=companion_available,
        )

    def probe_capability_snapshot(self) -> dict[str, Any]:
        """Return the C4 capability snapshot without touching plugin state or storage.

        The probe is intentionally based only on the shared contract module. It
        must remain safe to call from ordinary chat paths even when the contract
        is stale or the local module is otherwise malformed.
        """
        if not self._active:
            return self._negative_personal_capability_probe("bridge_inactive")
        if self._capability_cache.snapshot().get("state") == "negative":
            return self.capability_status()
        try:
            descriptor = bot_personal_contract.capability_descriptor(
                available=True,
                read_only=False,
            )
        except Exception:
            return self._negative_personal_capability_probe("contract_descriptor_exception")

        if not isinstance(descriptor, dict):
            return self._negative_personal_capability_probe("contract_descriptor_invalid")

        result = dict(descriptor)
        try:
            problems = bot_personal_contract.contract_self_check()
        except Exception:
            return self._negative_personal_capability_probe(
                "contract_self_check_exception",
                base=result,
            )

        if not isinstance(problems, list):
            return self._negative_personal_capability_probe(
                "contract_self_check_invalid",
                base=result,
            )
        if problems:
            warnings = ["contract_self_check_failed"]
            known_codes = {
                "contract_fingerprint_stale",
                "duplicate_window_slug",
                "type_contracts_out_of_sync",
                "window_coverage_gap",
                "alias_points_to_unknown_window",
            }
            for problem in problems:
                code = str(problem).split(":", 1)[0]
                if code in known_codes and code not in warnings:
                    warnings.append(code)
            return self._negative_personal_capability_probe(
                "contract_self_check_failed",
                base=result,
                warnings=warnings,
            )

        result["available"] = True
        result["state"] = "available"
        result["degraded"] = False
        self._add_personal_capability_contract_aliases(result)
        c4_snapshot = build_capability_snapshot(
            available=True,
            state="available",
            contract_module=bot_personal_contract,
            methods=result.get("methods", []),
            profiles=C4_PROFILE_NAMES,
            warnings=result.get("warnings", []),
        )
        result.update(c4_snapshot)
        result["memory_domain"] = bot_personal_contract.BOT_PERSONAL_MEMORY_DOMAIN
        result["domain"] = bot_personal_contract.BOT_PERSONAL_MEMORY_DOMAIN
        result["contract_revision"] = bot_personal_contract.CONTRACT_REVISION
        result["capability_schema_version"] = bot_personal_contract.BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION
        result["payload_schema_version"] = bot_personal_contract.BOT_PERSONAL_PAYLOAD_SCHEMA_VERSION
        result["capability_state"] = "available"
        # Capability discovery must remain static: callers use it before the
        # plugin service is safe to query, and C1 guarantees no storage access.
        result["p5"] = {"state": "unprobed", "error_code": "p5_status_not_probed"}
        self._capability_cache.mark_available(c4_snapshot)
        result.setdefault("warnings", [])
        return result

    def probe_bot_personal_memory_capabilities(self) -> dict[str, Any]:
        """Backward-compatible C1 probe; C4 state is exposed as capability_state."""

        result = dict(self.probe_capability_snapshot())
        if result.get("capability_state") == "available":
            result["state"] = "ready"
        result["legacy_state"] = result.get("state", "degraded")
        return result

    def probe_namespace_context_capabilities(self) -> dict[str, Any]:
        """Advertise ready only after the store and active epoch are bound."""
        status = self._scoped_store.epoch_status() if self._scoped_store is not None else {"bound": False}
        ready = self._active and status.get("bound") is True
        return namespace_capability_descriptor(
            available=ready,
            methods=(
                "list_scoped_records",
                "read_scoped_record",
                "erase_scoped_group_scopes",
                "erase_scoped_persona_scopes",
                "tombstone_scoped_identity_scopes",
                "tombstone_scoped_namespace",
                "tombstone_scoped_record",
                "upsert_scoped_record",
            ) if ready else (),
            error_code=(
                "" if ready
                else "bridge_inactive" if not self._active
                else "namespace_scoped_api_not_bound"
            ),
        )

    def bind_namespace_migration_epoch(
        self,
        capability: Any,
        *,
        operation_id: str,
        expected_previous_epoch: str,
        migration_epoch: str,
        policy_version: str,
    ) -> dict[str, Any]:
        if not self._active:
            return {"ok": False, "state": "degraded", "code": "bridge_inactive"}
        if not self._is_valid_private_companion_capability(capability):
            return {"ok": False, "state": "forbidden", "code": "producer_capability_required"}
        if self._scoped_store is None:
            return {"ok": False, "state": "degraded", "code": "namespace_scoped_store_unavailable"}
        try:
            result = self._scoped_store.bind_epoch(
                operation_id=operation_id,
                expected_previous_epoch=expected_previous_epoch,
                migration_epoch=migration_epoch,
                policy_version=policy_version,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {
            "ok": True,
            "state": "ready",
            "code": result,
            "epoch": self._scoped_store.epoch_status(),
        }

    def _authorized_scoped_context(
        self, capability: Any, namespace: Any
    ) -> tuple[Any | None, dict[str, Any] | None]:
        if not self._active:
            return None, {"ok": False, "state": "degraded", "code": "bridge_inactive"}
        if not self._is_valid_private_companion_capability(capability):
            return None, {"ok": False, "state": "forbidden", "code": "producer_capability_required"}
        if self._scoped_store is None:
            return None, {"ok": False, "state": "degraded", "code": "namespace_scoped_store_unavailable"}
        if self._scoped_store.epoch_status().get("bound") is not True:
            return None, {"ok": False, "state": "degraded", "code": "namespace_scoped_api_not_bound"}
        errors = validate_namespace_context(namespace)
        if errors:
            return None, {"ok": False, "state": "rejected", "code": errors[0]}
        context = build_namespace_context(namespace)
        if context is None:
            return None, {"ok": False, "state": "rejected", "code": "namespace_context_invalid"}
        return context, None

    def upsert_scoped_record(
        self,
        capability: Any,
        namespace: Any,
        *,
        record_kind: str,
        record_id: str,
        revision: int,
        payload: dict[str, Any],
        event_id: str,
    ) -> dict[str, Any]:
        context, denied = self._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            result = self._scoped_store.upsert(
                context, record_kind=record_kind, record_id=record_id, revision=revision,
                payload=payload, event_id=event_id,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", "code": result}

    def read_scoped_record(
        self, capability: Any, namespace: Any, *, record_kind: str, record_id: str
    ) -> dict[str, Any]:
        context, denied = self._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            record = self._scoped_store.read(context, record_kind=record_kind, record_id=record_id)
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", "code": "found" if record is not None else "not_found", "record": record}

    def list_scoped_records(
        self, capability: Any, namespace: Any, *, record_kind: str, limit: int = 100
    ) -> dict[str, Any]:
        context, denied = self._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            records = self._scoped_store.list_records(context, record_kind=record_kind, limit=limit)
        except (ScopedStoreError, TypeError, ValueError, OverflowError) as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", "code": "listed", "records": records}

    def tombstone_scoped_record(
        self,
        capability: Any,
        namespace: Any,
        *,
        record_kind: str,
        record_id: str,
        revision: int,
        event_id: str,
    ) -> dict[str, Any]:
        context, denied = self._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            result = self._scoped_store.tombstone(
                context, record_kind=record_kind, record_id=record_id, revision=revision, event_id=event_id,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", "code": result}

    def tombstone_scoped_namespace(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        context, denied = self._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            result = self._scoped_store.tombstone_namespace(
                context, operation_id=operation_id, reason_code=reason_code,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", **result}

    def tombstone_scoped_identity_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        context, denied = self._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            result = self._scoped_store.tombstone_identity_scopes(
                context, operation_id=operation_id, reason_code=reason_code,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", **result}

    def erase_scoped_group_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str = "group_reset",
    ) -> dict[str, Any]:
        context, denied = self._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            result = self._scoped_store.erase_group_scopes(
                context, operation_id=operation_id, reason_code=reason_code,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", **result}

    def erase_scoped_persona_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str = "persona_reset",
    ) -> dict[str, Any]:
        context, denied = self._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            result = self._scoped_store.erase_persona_scopes(
                context, operation_id=operation_id, reason_code=reason_code,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", **result}

    def capability_status(self) -> dict[str, Any]:
        """Return the bounded C4 cache state without probing storage."""

        snapshot = self._capability_cache.snapshot()
        snapshot["read_only"] = False
        snapshot["contract_name"] = bot_personal_contract.CONTRACT_NAME
        snapshot["max_payload_bytes"] = bot_personal_contract.BOT_PERSONAL_MAX_PAYLOAD_BYTES
        snapshot["memory_domain"] = bot_personal_contract.BOT_PERSONAL_MEMORY_DOMAIN
        snapshot["domain"] = snapshot["memory_domain"]
        snapshot["contract_revision"] = bot_personal_contract.CONTRACT_REVISION
        snapshot["capability_schema_version"] = bot_personal_contract.BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION
        snapshot["payload_schema_version"] = bot_personal_contract.BOT_PERSONAL_PAYLOAD_SCHEMA_VERSION
        snapshot["capability_state"] = snapshot.get("state", "unprobed")
        return snapshot

    def mark_capability_negative(self, reason: str) -> dict[str, Any]:
        """Temporarily suppress repeated capability failures at the bridge edge."""

        self._capability_cache.mark_negative(clean_text(reason, 120) or "capability_negative")
        return self.capability_status()

    @staticmethod
    def _add_personal_capability_contract_aliases(result: dict[str, Any]) -> dict[str, Any]:
        """Expose stable C1 aliases without changing the shared contract copy."""

        result.setdefault("domain", result.get("memory_domain", ""))
        result.setdefault("domains", [result.get("memory_domain", "")])
        result.setdefault("profiles", list(C4_PROFILE_NAMES))
        result.setdefault("legacy_profiles", ["bot_personal_archive"])
        result.setdefault(
            "methods",
            [
                "record_event",
                "record_external_memory",
                "record_visible_turn",
                "register_private_companion",
                "register_bot_personal_producer",
                "create_user_memory_context",
                "record_bot_personal_archive",
                "record_bot_personal_memory",
                "read_bot_personal_profile",
                "search_bot_personal_profile",
                "search",
                "compose_injection",
                "compose_context",
                "remember",
                "recall",
                "consume_person_projection",
                "consume_context_projection",
                "consume_relationship_projection",
                "consume_expression_decision",
                "read_bot_profile",
                "read_profile",
                "read_unified_profile_portrait",
                "unified_profile_portrait_status",
                "run_unified_profile_portrait_batch",
                "p5_capability_status",
                "provenance_snapshot",
                "provenance_preview",
                "provenance_apply",
                "provenance_backup",
                "provenance_rollback",
                "probe_capability_snapshot",
                "probe_bot_personal_memory_capabilities",
            ],
        )
        result.setdefault("contract_version", str(result.get("contract_revision", "")))
        result.setdefault("schema_version", str(result.get("capability_schema_version", "")))
        return result

    def _negative_personal_capability_probe(
        self,
        reason: str,
        *,
        base: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return a bounded failure and suppress repeated probes for the TTL."""

        safe_reason = clean_text(reason, 120) or "capability_negative"
        result = self._degraded_personal_capability_probe(
            safe_reason,
            base=base,
            warnings=warnings,
        )
        cached = self._capability_cache.mark_negative(safe_reason)
        for key in ("available", "state", "degraded", "pending", "error_code"):
            if key in cached:
                result[key] = cached[key]
        result["available"] = False
        result["state"] = "negative"
        result["capability_state"] = "negative"
        result["degraded"] = True
        result["pending"] = False
        result["error_code"] = safe_reason
        result["p5"] = {"state": "degraded", "error_code": safe_reason}
        return result

    @staticmethod
    def _degraded_personal_capability_probe(
        reason: str,
        *,
        base: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        result = {
            "available": False,
            "read_only": False,
            "memory_domain": getattr(bot_personal_contract, "BOT_PERSONAL_MEMORY_DOMAIN", ""),
            "contract_name": getattr(bot_personal_contract, "CONTRACT_NAME", ""),
            "contract_revision": getattr(bot_personal_contract, "CONTRACT_REVISION", 0),
            "contract_fingerprint": getattr(bot_personal_contract, "CONTRACT_FINGERPRINT", ""),
            "capability_schema_version": getattr(
                bot_personal_contract, "BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION", ""
            ),
            "payload_schema_version": getattr(
                bot_personal_contract, "BOT_PERSONAL_PAYLOAD_SCHEMA_VERSION", ""
            ),
            "windows": list(getattr(bot_personal_contract, "WINDOW_SLUGS", ())),
            "memory_types": list(getattr(bot_personal_contract, "BOT_PERSONAL_MEMORY_TYPES", ())),
            "max_payload_bytes": getattr(bot_personal_contract, "BOT_PERSONAL_MAX_PAYLOAD_BYTES", 0),
            "warnings": [],
        }
        result.update(base or {})
        result.update(
            {
                "available": False,
                "state": "degraded",
                "degraded": True,
                "warnings": list(warnings or [reason]),
            }
        )
        MemoryCompanionBridge._add_personal_capability_contract_aliases(result)
        c4_snapshot = build_capability_snapshot(
            available=False,
            state="degraded",
            contract_module=bot_personal_contract,
            methods=result.get("methods", []),
            profiles=C4_PROFILE_NAMES,
            warnings=result.get("warnings", []),
            error_code=reason,
        )
        result.update(c4_snapshot)
        result["memory_domain"] = getattr(bot_personal_contract, "BOT_PERSONAL_MEMORY_DOMAIN", "")
        result["domain"] = result["memory_domain"]
        result["contract_revision"] = getattr(bot_personal_contract, "CONTRACT_REVISION", 0)
        result["capability_schema_version"] = getattr(
            bot_personal_contract, "BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION", ""
        )
        result["payload_schema_version"] = getattr(
            bot_personal_contract, "BOT_PERSONAL_PAYLOAD_SCHEMA_VERSION", ""
        )
        result["capability_state"] = "degraded"
        result["p5"] = {"state": "degraded", "error_code": reason}
        return result

    def get_token_usage_summary(self) -> dict[str, Any]:
        getter = getattr(self._plugin, "token_usage_summary", None)
        if callable(getter):
            result = getter()
            return result if isinstance(result, dict) else {}
        return {}

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

    def get_emotional_events(self, *, session_id: str = "", limit: int = 5) -> list[dict[str, Any]]:
        """Temporary exact-window compatibility path for pre-capability callers."""

        safe_session = clean_text(session_id, 220)
        if not safe_session or ":" not in safe_session:
            return []
        getter = getattr(self._plugin, "bridge_get_emotional_events", None)
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

        if not self._is_valid_emotion_delivery_context(delivery_context):
            return self._emotion_delivery_forbidden_result("delivery_context_required")
        return await self._plugin.store.list_emotion_event_deliveries(
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

        if not self._is_valid_emotion_delivery_context(delivery_context):
            return self._emotion_ack_forbidden_result("delivery_context_required")
        return await self._plugin.store.ack_emotion_event_deliveries(
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

        if not self._is_valid_emotion_producer_context(producer_context):
            return self._emotion_forbidden_result("producer_context_required")
        return await self._plugin.store.upsert_emotion_event(
            self._attested_emotion_event(event, producer_context)
        )

    async def revise_emotion_event(
        self,
        event: dict[str, Any],
        *,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Persist a later Companion revision only inside its attested domain."""

        if not self._is_valid_emotion_producer_context(producer_context):
            return self._emotion_forbidden_result("producer_context_required")
        return await self._plugin.store.upsert_emotion_event(
            self._attested_emotion_event(event, producer_context)
        )

    async def get_emotion_trace(
        self,
        trace_id: str,
        *,
        requester_context: Any = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return only the scoped, redacted diagnostic projection for a trusted admin."""

        return await self.get_emotion_trace_diagnostic(
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
        if not self._is_valid_emotion_admin_context(context):
            return {"state": "forbidden", "read_only": True, "items": [], "error_code": "admin_required"}
        items = await self._plugin.store.get_emotion_trace_diagnostic(
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
        if not self._is_valid_emotion_admin_context(context):
            return {"state": "forbidden", "read_only": True, "items": [], "next_cursor": "", "error_code": "admin_required"}
        result = await self._plugin.store.get_emotion_trace_summary(
            bot_id=context.bot_id,
            scope=context.scope,
            session_id=context.session_id,
            cursor=clean_text(cursor, 20),
            limit=max(1, min(100, int(limit or 20))),
        )
        return {"state": "ready", "read_only": True, **result}

    @staticmethod
    def _emotion_forbidden_result(error_code: str) -> dict[str, Any]:
        return {
            "ok": False,
            "state": "forbidden",
            "read_only": False,
            "event_id": "",
            "error_code": error_code,
        }

    @staticmethod
    def _emotion_delivery_forbidden_result(error_code: str) -> dict[str, Any]:
        return {
            "schema_version": "emotion_afterglow_delivery.v1",
            "state": "forbidden",
            "read_only": True,
            "events": [],
            "next_cursor": "",
            "has_more": False,
            "error_code": error_code,
        }

    @staticmethod
    def _emotion_ack_forbidden_result(error_code: str) -> dict[str, Any]:
        return {
            "state": "forbidden",
            "acked": 0,
            "error_code": error_code,
        }

    @staticmethod
    def _attested_emotion_event(event: Any, context: _EmotionProducerContext) -> dict[str, Any]:
        source = dict(event) if isinstance(event, dict) else {}
        origin = clean_text(source.get("origin_kind"), 40).lower()
        if origin not in _EMOTION_INGRESS_ORIGINS:
            origin = "interaction"
        source.update(
            {
                "producer_plugin": "private_companion",
                "origin_kind": origin,
                "bot_id": context.bot_id,
                "scope": context.scope,
                "platform": context.platform,
                "session_id": context.session_id,
                "actor_ref": {"kind": "user", "id": context.user_id, "role": "speaker"},
                "target_ref": {"kind": "bot", "id": context.bot_id, "role": "bot_self"},
                "quoted_target_ref": {},
            }
        )
        return source

    async def search_open_loops(self, *, session_id: str = "", limit: int = 3) -> list[dict[str, Any]]:
        """Search for unresolved open-loop / promise memories for proactive companionship."""
        return await self._plugin.bridge_search_open_loops(session_id=session_id, limit=limit)

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
        getter = getattr(self._plugin, "_get_relationship_phase", None)
        if not callable(getter):
            return {"phase": "unknown", "momentum": 0.0}
        normalizer = getattr(self._plugin, "session_context_from_bridge", None)
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
            getter = getattr(self._plugin, "_peek_relationship_phase", None)
            if not callable(getter):
                return fallback
            normalizer = getattr(self._plugin, "session_context_from_bridge", None)
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
    key_facts_with_refs = (
        metadata.get("key_facts_with_refs")
        if isinstance(metadata.get("key_facts_with_refs"), list)
        else []
    )
    routine_check_notes = metadata.get("routine_check_notes") if isinstance(metadata.get("routine_check_notes"), list) else []
    topics = metadata.get("topics") if isinstance(metadata.get("topics"), list) else []
    participants = metadata.get("participants") if isinstance(metadata.get("participants"), list) else []
    persona_weight_keys = [
        "persona_importance",
        "relationship_weight",
        "emotional_weight",
        "promise_weight",
        "open_loop_weight",
        "creative_weight",
        "preference_weight",
        "self_continuity_weight",
        "freshness_weight",
        "scar_weight",
        "emotional_debt_weight",
        "intimacy_weight",
        "vulnerability_weight",
    ]
    persona_weights = {
        key: metadata.get(key)
        for key in persona_weight_keys
        if metadata.get(key) is not None
    }
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
        "owner_bot_id": record.owner_bot_id,
        "persona_id": clean_text(metadata.get("persona_id"), 120),
        "validity_status": record.validity_status,
        "valid_from": record.valid_from,
        "valid_to": record.valid_to,
        "salience": record.salience,
        "durability": record.durability,
        "sensitivity": record.sensitivity,
        "reinforcement_score": record.reinforcement_score,
        "injection_count": record.injection_count,
        "last_injected_at": record.last_injected_at,
        "canonical_key": record.canonical_key,
        "content": record.content,
        "evidence_preview": clean_text(record.evidence, 520),
        "canonical_summary": clean_text(metadata.get("canonical_summary"), 420),
        "key_facts": [clean_text(item, 180) for item in key_facts if clean_text(item, 180)][:4],
        "key_facts_with_refs": [
            {
                "fact": clean_text(item.get("fact"), 180),
                "refs": [
                    clean_text(ref, 160)
                    for ref in item.get("refs", [])
                    if clean_text(ref, 160)
                ][:6],
            }
            for item in key_facts_with_refs
            if isinstance(item, dict) and clean_text(item.get("fact"), 180)
        ][:8],
        "routine_check_notes": [clean_text(item, 180) for item in routine_check_notes if clean_text(item, 180)][:4],
        "topics": [clean_text(item, 80) for item in topics if clean_text(item, 80)][:5],
        "participants": [clean_text(item, 80) for item in participants if clean_text(item, 80)][:5],
        "memory_reason": clean_text(metadata.get("memory_reason"), 260),
        "mention_policy": clean_text(metadata.get("mention_policy"), 60),
        "mentionability_score": metadata.get("mentionability_score"),
        "relationship_phase": clean_text(metadata.get("relationship_phase"), 80),
        "decay_mode": clean_text(metadata.get("decay_mode"), 80),
        "active_dimensions": [
            clean_text(item, 80)
            for item in metadata.get("active_dimensions", [])
            if clean_text(item, 80)
        ][:6] if isinstance(metadata.get("active_dimensions"), list) else [],
        "persona_weights": persona_weights,
        "mention_feedback": metadata.get("mention_feedback") if isinstance(metadata.get("mention_feedback"), dict) else {},
        "confidence": record.confidence,
        "importance": record.importance,
        "review_status": record.review_status,
        "tags": record.tags,
        "source_plugin": record.source_plugin,
        "import_batch_id": record.import_batch_id,
        "created_at": record.created_at,
        "created_at_local": _local_time_label(record.created_at),
        "updated_at": record.updated_at,
        "updated_at_local": _local_time_label(record.updated_at),
        "occurred_at": record.occurred_at,
        "occurred_at_local": _local_time_label(record.occurred_at),
        "time_range": {
            "start_at": clean_text(metadata.get("start_at"), 80),
            "end_at": clean_text(metadata.get("end_at"), 80),
            "start_at_local": clean_text(metadata.get("start_at_local"), 80) or _local_time_label(metadata.get("start_at")),
            "end_at_local": clean_text(metadata.get("end_at_local"), 80) or _local_time_label(metadata.get("end_at")),
            "timezone": "Asia/Shanghai",
        },
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
