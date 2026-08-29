from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Any

from . import bot_personal_contract
from .bot_personal_dto import BotPersonalArchiveDTO, build_bot_personal_archive
from .bridge_external_record import ExternalRecordBridgeFamily as _ExternalRecordBridgeFamily
from .bridge_maintenance import MaintenanceBridgeFamily as _MaintenanceBridgeFamily
from .bridge_portrait_emotion import PortraitEmotionBridgeFamily as _PortraitEmotionBridgeFamily
from .bridge_producer import ProducerBridgeFamily as _ProducerBridgeFamily
from .bridge_recall import RecallBridgeFamily as _RecallBridgeFamily
from .bridge_scoped_namespace import ScopedNamespaceBridgeFamily as _ScopedNamespaceBridgeFamily
from .bridge_contract import (
    LOCAL_TZ,
    _AuthenticatedCompanionProjection,
    _canonical_companion_projection_message,
    _canonical_companion_projection_signature,
    _local_time_label,
    _verify_companion_projection_signature,
    sanitize_companion_expression_decision,
    sanitize_companion_relationship_projection,
    serialize_memory,
)
from .capability_probe import CapabilityCache, PROFILE_NAMES as C4_PROFILE_NAMES, build_capability_snapshot
from .context_consumer import consume_context_projection
from .models import EntityRef, SessionContext, clean_text
from .namespace_capability import namespace_capability_descriptor
from .namespace import build_namespace_context, validate_namespace_context
from .person_projection import consume_person_projection
from .scoped_store import ScopedStore, ScopedStoreError

_PRIVATE_COMPANION_ROOT = "astrbot_plugin_private_companion"
_PRIVATE_COMPANION_NAMES = {"PrivateCompanion", "private_companion"}
_EMOTION_INGRESS_ORIGINS = {"interaction", "system_condition"}
_EMOTION_DELIVERY_CONSUMER = "private_companion.daily_state"
_COMPANION_PROJECTION_SECRET = secrets.token_bytes(32)


@dataclass(frozen=True, slots=True)
class _EmotionProducerCapability:
    """Non-serializable capability bound to one live Companion plugin instance."""

    _bridge: Any
    _producer: Any
    _token: object


@dataclass(frozen=True, slots=True)
class _ExternalMemoryProducerCapability:
    """Non-serializable authority bound to one live registered plugin."""

    _bridge: Any
    _producer: Any
    _producer_id: str
    _token: object


@dataclass(frozen=True, slots=True)
class _ExternalMemoryProducerContext:
    """Opaque authority for one producer and one private user domain."""

    _bridge: Any
    _capability: _ExternalMemoryProducerCapability
    producer_id: str
    scope: str
    session_id: str
    user_id: str


def consume_external_memory_producer_context(value: Any) -> dict[str, str] | None:
    """Return server-owned scope fields only for a live opaque context."""

    if type(value) is not _ExternalMemoryProducerContext:
        return None
    validator = getattr(value._bridge, "_is_valid_external_memory_producer_context", None)
    if not callable(validator) or validator(value) is not True:
        return None
    return {
        "producer_id": value.producer_id,
        "scope": value.scope,
        "session_id": value.session_id,
        "user_id": value.user_id,
    }


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
        _canonical_companion_projection_message(
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
    if not _verify_companion_projection_signature(
        dict(value),
        value._signature,
        secret=_COMPANION_PROJECTION_SECRET,
        kind=value._kind,
        bot_id=attrs["bot_id"],
        platform=attrs["platform"],
        person_id=attrs["person_id"],
        scope=attrs["scope"],
        session_id=attrs["session_id"],
    ):
        return {**fallback, "error_code": "projection_signature_invalid"}
    if kind == "relationship":
        return sanitize_companion_relationship_projection(dict(value))
    if kind == "expression":
        return sanitize_companion_expression_decision(dict(value))
    return {**fallback, "error_code": "projection_kind_invalid"}


class MemoryCompanionBridge:
    """Public bridge for other plugins.

    The bridge intentionally accepts structured fields. A caller should say
    whether something is a bot action, a persona-life fragment, a real user
    fact, or an imported summary instead of handing over vague prose.
    """

    def __init__(
        self,
        plugin: Any,
        *,
        active: bool = True,
        instance_generation: int = 0,
    ):
        self._plugin = plugin
        self.__scoped_store: ScopedStore | None = None
        self.__scoped_store_resolved = False
        self._capability_cache = CapabilityCache()
        self._emotion_producer_token = object()
        self._external_memory_producer_token = object()
        self._emotion_page_admin_token = object()
        self._active = active is True
        self._instance_generation = (
            instance_generation
            if isinstance(instance_generation, int) and instance_generation > 0
            else 0
        )
        self._recall_family = _RecallBridgeFamily(self)
        self._external_record_family = _ExternalRecordBridgeFamily(self)
        self._scoped_namespace_family = _ScopedNamespaceBridgeFamily(self)
        self._portrait_emotion_family = _PortraitEmotionBridgeFamily(self)
        self._producer_family = _ProducerBridgeFamily(self)
        self._maintenance_family = _MaintenanceBridgeFamily(self)

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

    def _scoped_store_initialization_error_code(self) -> str:
        status = getattr(self._plugin, "scoped_store_status", None)
        if (
            isinstance(status, dict)
            and status.get("state") == "degraded"
            and status.get("error_code") == "namespace_scoped_store_initialize_failed"
        ):
            return "namespace_scoped_store_initialize_failed"
        return ""

    def _scoped_mutation_denied(self) -> dict[str, Any] | None:
        service = self._plugin
        if (
            getattr(service, "_closing", False)
            or getattr(service, "_closed", False)
            or (
                hasattr(service, "_capture_admission_open")
                and getattr(service, "_capture_admission_open") is not True
            )
        ):
            return {
                "ok": False,
                "state": "degraded",
                "code": "scoped_write_fenced",
            }
        return None

    def bridge_lifecycle_status(self) -> dict[str, Any]:
        """Expose only whether this in-process bridge can still serve calls."""
        return {
            "active": self._active,
            "state": "ready" if self._active else "inactive",
            "instance_generation": self._instance_generation,
        }

    def _activate(self) -> None:
        """Make a fully initialized bridge eligible for capability issuance."""
        self._active = True
        self._capability_cache.clear()

    def deactivate(self) -> None:
        """Revoke all issued capabilities before plugin service shutdown."""
        self._active = False
        self._capability_cache.clear()
        self._emotion_producer_token = object()
        self._external_memory_producer_token = object()
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

    def register_external_memory_producer(self, producer: Any) -> Any | None:
        """Issue an external-memory writer capability to one allowed live plugin."""

        if not self._active:
            return None
        producer_id = self._registered_external_memory_producer_id(producer)
        if not producer_id:
            return None
        return _ExternalMemoryProducerCapability(
            self,
            producer,
            producer_id,
            self._external_memory_producer_token,
        )

    def create_external_memory_context(
        self,
        capability: Any,
        *,
        user_id: str,
    ) -> Any | None:
        """Bind an external-memory producer to one server-generated private domain."""

        if not self._is_valid_external_memory_producer_capability(capability):
            return None
        normalized_user_id = clean_text(user_id, 160)
        if not normalized_user_id:
            return None
        producer_id = capability._producer_id
        return _ExternalMemoryProducerContext(
            self,
            capability,
            producer_id=producer_id,
            scope="private",
            session_id=f"external:{producer_id}:{normalized_user_id}",
            user_id=normalized_user_id,
        )

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

    def _external_memory_producer_allowlist(self) -> set[str]:
        config = getattr(self._plugin, "config", None)
        getter = getattr(config, "get", None)
        if not callable(getter):
            return set()
        try:
            configured = getter(
                "private_companion_bridge.external_memory_producer_allowlist",
                "",
            )
        except Exception:
            return set()
        if isinstance(configured, str):
            values = configured.replace("\n", ",").split(",")
        elif isinstance(configured, (list, tuple, set, frozenset)):
            values = configured
        else:
            return set()
        return {
            producer_id
            for item in values
            if (producer_id := clean_text(item, 120))
        }

    def _registered_external_memory_producer_id(self, producer: Any) -> str:
        """Resolve one exact live Star instance to its server-owned producer id."""

        context = getattr(self._plugin, "context", None)
        getter = getattr(context, "get_all_stars", None)
        if not callable(getter):
            return ""
        try:
            stars = getter()
        except Exception:
            return ""
        if not isinstance(stars, (list, tuple)):
            return ""
        allowed = self._external_memory_producer_allowlist()
        for metadata in stars:
            registered_instance = getattr(metadata, "star_cls", None)
            registered_type = getattr(metadata, "star_cls_type", None)
            if producer is not registered_instance:
                continue
            if registered_type is not None and type(registered_instance) is not registered_type:
                continue
            if getattr(metadata, "activated", False) is not True:
                continue
            root = clean_text(getattr(metadata, "root_dir_name", ""), 120)
            name = clean_text(getattr(metadata, "name", ""), 120)
            if root == _PRIVATE_COMPANION_ROOT or name in _PRIVATE_COMPANION_NAMES:
                return root or _PRIVATE_COMPANION_ROOT
            if root and root in allowed:
                return root
        return ""

    def _is_valid_external_memory_producer_capability(self, capability: Any) -> bool:
        return (
            self._active
            and type(capability) is _ExternalMemoryProducerCapability
            and capability._bridge is self
            and capability._token is self._external_memory_producer_token
            and capability._producer_id
            == self._registered_external_memory_producer_id(capability._producer)
        )

    def _is_valid_external_memory_producer_context(self, context: Any) -> bool:
        if (
            type(context) is not _ExternalMemoryProducerContext
            or context._bridge is not self
            or not self._is_valid_external_memory_producer_capability(context._capability)
        ):
            return False
        user_id = clean_text(context.user_id, 160)
        producer_id = context._capability._producer_id
        return (
            bool(user_id)
            and context.producer_id == producer_id
            and context.scope == "private"
            and context.session_id == f"external:{producer_id}:{user_id}"
        )

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
        signature = _canonical_companion_projection_signature(
            payload,
            secret=_COMPANION_PROJECTION_SECRET,
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
        return await self._external_record_family.record_event(
            content=content,
            memory_type=memory_type,
            scope=scope,
            session_id=session_id,
            platform=platform,
            message_id=message_id,
            group_id=group_id,
            subject=subject,
            object=object,
            visibility=visibility,
            sayability=sayability,
            reality_level=reality_level,
            lifecycle=lifecycle,
            confidence=confidence,
            importance=importance,
            review_status=review_status,
            tags=tags,
            metadata=metadata,
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
        producer_capability: Any = None,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Write one user-scoped long-term memory from an external source.

        Legacy keyword fields remain accepted for capability discovery, but
        producer identity and the private user domain come only from a live
        server-issued context.
        """
        base = {
            "ok": False,
            "state": "forbidden",
            "memory_id": "",
            "deduplicated": False,
            "long_term": bool(long_term),
            "scope": "private",
            "visibility": "private_pair",
            "error_code": "producer_capability_required",
        }
        authority = producer_context if producer_context is not None else producer_capability
        if type(authority) is _ExternalMemoryProducerContext:
            bound_context = authority if self._is_valid_external_memory_producer_context(authority) else None
        elif type(authority) is _ExternalMemoryProducerCapability:
            bound_context = self.create_external_memory_context(authority, user_id=user_id)
        else:
            bound_context = None
        if bound_context is None:
            return base
        supplied_user_id = clean_text(user_id, 160)
        if supplied_user_id and supplied_user_id != bound_context.user_id:
            return {**base, "error_code": "producer_context_mismatch"}

        writer = getattr(self._plugin, "record_external_memory", None)
        if not callable(writer):
            return {
                **base,
                "state": "unsupported",
                "error_code": "record_external_memory_unavailable",
            }
        result = await writer(
            user_id=bound_context.user_id,
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
            producer_context=bound_context,
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
        return await self._external_record_family.record_bot_action(content=content, **kwargs)

    async def record_persona_life(self, *, content: str, **kwargs: Any) -> str:
        return await self._external_record_family.record_persona_life(content=content, **kwargs)

    async def record_proactive_message(self, *, content: str, **kwargs: Any) -> str:
        return await self._external_record_family.record_proactive_message(
            content=content,
            **kwargs,
        )

    async def record_visible_turn(self, *, role: str, content: str, **kwargs: Any) -> str:
        """Record a real visible chat turn into the short-term timeline only."""
        return await self._external_record_family.record_visible_turn(
            role=role,
            content=content,
            **kwargs,
        )

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
        return await self._external_record_family.record_shared_experience(
            content=content,
            experience_type=experience_type,
            bot_id=bot_id,
            bot_name=bot_name,
            user_id=user_id,
            user_name=user_name,
            scope=scope,
            session_id=session_id,
            platform=platform,
            source_plugin=source_plugin,
            memory_id=memory_id,
            confidence=confidence,
            importance=importance,
            metadata=metadata,
        )

    async def record_search_action(self, *, content: str, **kwargs: Any) -> str:
        return await self._external_record_family.record_search_action(content=content, **kwargs)

    async def record_creative_work(self, *, content: str, **kwargs: Any) -> str:
        return await self._external_record_family.record_creative_work(content=content, **kwargs)

    async def record_image_action(self, *, content: str, **kwargs: Any) -> str:
        return await self._external_record_family.record_image_action(content=content, **kwargs)

    async def record_qzone_action(self, *, content: str, **kwargs: Any) -> str:
        return await self._external_record_family.record_qzone_action(content=content, **kwargs)

    async def record_reading(self, *, content: str, **kwargs: Any) -> str:
        return await self._external_record_family.record_reading(content=content, **kwargs)

    async def record_schedule_fragment(self, *, content: str, **kwargs: Any) -> str:
        return await self._external_record_family.record_schedule_fragment(
            content=content,
            **kwargs,
        )

    async def record_bot_personal_archive(
        self,
        envelope: BotPersonalArchiveDTO | dict[str, Any],
        *,
        producer_capability: Any = None,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Send one validated Bot Personal archive envelope without leaking failures."""
        return await self._external_record_family.record_bot_personal_archive(
            envelope,
            producer_capability=producer_capability,
            producer_context=producer_context,
        )

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
        return await self._external_record_family.record_bot_personal_memory(
            memory_type=memory_type,
            payload=payload,
            producer_capability=producer_capability,
            producer_context=producer_context,
            **kwargs,
        )

    async def read_bot_personal_profile(
        self,
        query: str = "",
        *,
        limit: int = 10,
        producer_capability: Any = None,
    ) -> dict[str, Any]:
        """Read only safe Bot Personal summaries; never return archive payloads."""
        return await self._recall_family.read_bot_personal_profile(
            query,
            limit=limit,
            producer_capability=producer_capability,
        )

    async def read_user_memory_summary(
        self,
        user_id: str,
        *,
        session_id: str = "",
        limit: int = 6,
        requester_context: Any = None,
    ) -> dict[str, Any]:
        """Read a strict, exact-user Memory summary without exposing memory text."""
        # Keep the façade-level contract marker used by static consumers: content_redacted.
        return await self._portrait_emotion_family.read_user_memory_summary(
            user_id,
            session_id=session_id,
            limit=limit,
            requester_context=requester_context,
        )

    async def read_unified_profile_portrait(self, request: dict[str, Any], *, limit: int = 8) -> dict[str, Any]:
        """Return only a pre-authorized low-sensitivity portrait summary."""
        return await self._portrait_emotion_family.read_unified_profile_portrait(
            request,
            limit=limit,
        )

    async def unified_profile_portrait_status(self, person_id: str) -> dict[str, Any]:
        """Return only bridge synchronization metadata, never portrait text."""
        return await self._portrait_emotion_family.unified_profile_portrait_status(person_id)

    async def run_unified_profile_portrait_batch(self, person_id: str, *, run_day: str = "") -> dict[str, Any]:
        return await self._portrait_emotion_family.run_unified_profile_portrait_batch(
            person_id,
            run_day=run_day,
        )

    async def search_bot_personal_profile(
        self,
        query: str = "",
        *,
        limit: int = 10,
        producer_capability: Any = None,
    ) -> dict[str, Any]:
        return await self._recall_family.search_bot_personal_profile(
            query,
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
        return await self._recall_family.read_bot_profile(
            profile,
            query,
            limit=limit,
            current_date=current_date,
            current_window=current_window,
            authorized=authorized,
            producer_capability=producer_capability,
            producer_context=producer_context,
        )

    async def read_profile(self, profile: str, query: str = "", **kwargs: Any) -> dict[str, Any]:
        """Short alias for callers that use the generic Profile API name."""
        return await self._recall_family.read_profile(profile, query, **kwargs)

    async def search(
        self,
        query: str,
        *,
        session_context: SessionContext | dict[str, Any] | None = None,
        top_k: int | None = None,
        p5_attestation: Any = None,
        p5_attestation_consumer: Any = None,
    ) -> list[dict[str, Any]]:
        return await self._recall_family.search(
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
        return await self._recall_family.compose_injection(
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
        return await self._recall_family.compose_context(
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
        return await self._recall_family.remember(event=event, content=content, note_type=note_type)

    async def recall(
        self,
        *,
        event: Any,
        query: str,
        top_k: int = 5,
        p5_attestation: Any = None,
        p5_attestation_consumer: Any = None,
    ) -> dict[str, Any]:
        return await self._recall_family.recall(
            event=event,
            query=query,
            top_k=top_k,
            p5_attestation=p5_attestation,
            p5_attestation_consumer=p5_attestation_consumer,
        )

    def p5_capability_status(self) -> dict[str, Any]:
        return self._maintenance_family.p5_capability_status()

    def provenance_snapshot(self) -> dict[str, Any]:
        return self._maintenance_family.provenance_snapshot()

    def provenance_preview(self, candidates: list[dict[str, Any]], *, operation_ref_hash: str) -> dict[str, Any]:
        return self._maintenance_family.provenance_preview(
            candidates,
            operation_ref_hash=operation_ref_hash,
        )

    async def provenance_apply(self, operation: dict[str, Any]) -> dict[str, Any]:
        return await self._maintenance_family.provenance_apply(operation)

    async def provenance_backup(self) -> dict[str, Any]:
        return await self._maintenance_family.provenance_backup()

    async def provenance_rollback(self, operation: dict[str, Any]) -> dict[str, Any]:
        return await self._maintenance_family.provenance_rollback(operation)

    async def create_note(self, *, event: Any, title: str, content: str = "") -> dict[str, Any]:
        return await self._maintenance_family.create_note(event=event, title=title, content=content)

    async def read_notes(self, *, event: Any, query: str = "", limit: int = 5) -> dict[str, Any]:
        return await self._maintenance_family.read_notes(event=event, query=query, limit=limit)

    async def delete_note(self, *, event: Any, memory_id: str = "", title: str = "") -> dict[str, Any]:
        return await self._maintenance_family.delete_note(
            event=event,
            memory_id=memory_id,
            title=title,
        )

    def coordination_status(self) -> dict[str, Any]:
        return self._maintenance_family.coordination_status()

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
        return self._producer_family.probe_capability_snapshot()

    def probe_bot_personal_memory_capabilities(self) -> dict[str, Any]:
        """Backward-compatible C1 probe; C4 state is exposed as capability_state."""
        return self._producer_family.probe_bot_personal_memory_capabilities()

    def probe_namespace_context_capabilities(self) -> dict[str, Any]:
        """Advertise ready only after the store and active epoch are bound."""
        return self._scoped_namespace_family.probe_namespace_context_capabilities()

    def bind_namespace_migration_epoch(
        self,
        capability: Any,
        *,
        operation_id: str,
        expected_previous_epoch: str,
        migration_epoch: str,
        policy_version: str,
    ) -> dict[str, Any]:
        return self._scoped_namespace_family.bind_namespace_migration_epoch(
            capability,
            operation_id=operation_id,
            expected_previous_epoch=expected_previous_epoch,
            migration_epoch=migration_epoch,
            policy_version=policy_version,
        )

    def _authorized_scoped_context(
        self, capability: Any, namespace: Any
    ) -> tuple[Any | None, dict[str, Any] | None]:
        if not self._active:
            return None, {"ok": False, "state": "degraded", "code": "bridge_inactive"}
        if not self._is_valid_private_companion_capability(capability):
            return None, {"ok": False, "state": "forbidden", "code": "producer_capability_required"}
        if self._scoped_store is None:
            return None, {
                "ok": False,
                "state": "degraded",
                "code": self._scoped_store_initialization_error_code()
                or "namespace_scoped_store_unavailable",
            }
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
        return self._scoped_namespace_family.upsert_scoped_record(
            capability,
            namespace,
            record_kind=record_kind,
            record_id=record_id,
            revision=revision,
            payload=payload,
            event_id=event_id,
        )

    def read_scoped_record(
        self, capability: Any, namespace: Any, *, record_kind: str, record_id: str
    ) -> dict[str, Any]:
        return self._scoped_namespace_family.read_scoped_record(
            capability,
            namespace,
            record_kind=record_kind,
            record_id=record_id,
        )

    def list_scoped_records(
        self, capability: Any, namespace: Any, *, record_kind: str, limit: int = 100
    ) -> dict[str, Any]:
        return self._scoped_namespace_family.list_scoped_records(
            capability,
            namespace,
            record_kind=record_kind,
            limit=limit,
        )

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
        return self._scoped_namespace_family.tombstone_scoped_record(
            capability,
            namespace,
            record_kind=record_kind,
            record_id=record_id,
            revision=revision,
            event_id=event_id,
        )

    def tombstone_scoped_namespace(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        return self._scoped_namespace_family.tombstone_scoped_namespace(
            capability,
            namespace,
            operation_id=operation_id,
            reason_code=reason_code,
        )

    def tombstone_scoped_identity_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        return self._scoped_namespace_family.tombstone_scoped_identity_scopes(
            capability,
            namespace,
            operation_id=operation_id,
            reason_code=reason_code,
        )

    def erase_scoped_group_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str = "group_reset",
    ) -> dict[str, Any]:
        return self._scoped_namespace_family.erase_scoped_group_scopes(
            capability,
            namespace,
            operation_id=operation_id,
            reason_code=reason_code,
        )

    def erase_scoped_persona_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str = "persona_reset",
    ) -> dict[str, Any]:
        return self._scoped_namespace_family.erase_scoped_persona_scopes(
            capability,
            namespace,
            operation_id=operation_id,
            reason_code=reason_code,
        )

    def capability_status(self) -> dict[str, Any]:
        """Return the bounded C4 cache state without probing storage."""
        return self._producer_family.capability_status()

    def mark_capability_negative(self, reason: str) -> dict[str, Any]:
        """Temporarily suppress repeated capability failures at the bridge edge."""
        return self._producer_family.mark_capability_negative(reason)

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
                "register_external_memory_producer",
                "create_external_memory_context",
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
        return self._recall_family.get_token_usage_summary()

    def should_defer_private_companion_section(self, section: str) -> bool:
        return self._recall_family.should_defer_private_companion_section(section)

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
        return await self._maintenance_family.create_cross_window_thread(
            from_session=from_session,
            to_session=to_session,
            topic=topic,
            content=content,
            visibility=visibility,
            metadata=metadata,
        )

    async def mark_visibility(self, memory_id: str, visibility: str) -> bool:
        return await self._recall_family.mark_visibility(memory_id, visibility)

    def get_emotional_events(self, *, session_id: str = "", limit: int = 5) -> list[dict[str, Any]]:
        """Temporary exact-window compatibility path for pre-capability callers."""
        return self._portrait_emotion_family.get_emotional_events(
            session_id=session_id,
            limit=limit,
        )

    async def list_emotion_events(
        self,
        *,
        delivery_context: Any = None,
        cursor: str = "",
        limit: int = 10,
        **_legacy: Any,
    ) -> dict[str, Any]:
        """List afterglow events only for one opaque Companion delivery context."""
        return await self._portrait_emotion_family.list_emotion_events(
            delivery_context=delivery_context,
            cursor=cursor,
            limit=limit,
            **_legacy,
        )

    async def ack_emotion_events(
        self,
        event_refs: list[dict[str, Any]],
        *,
        delivery_context: Any = None,
        **_legacy: Any,
    ) -> dict[str, Any]:
        """Acknowledge only events delivered inside one opaque identity domain."""
        return await self._portrait_emotion_family.ack_emotion_events(
            event_refs,
            delivery_context=delivery_context,
            **_legacy,
        )

    async def record_emotion_event(
        self,
        event: dict[str, Any],
        *,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Persist a Companion event only inside an attested private user/Bot domain."""
        return await self._portrait_emotion_family.record_emotion_event(
            event,
            producer_context=producer_context,
        )

    async def revise_emotion_event(
        self,
        event: dict[str, Any],
        *,
        producer_context: Any = None,
    ) -> dict[str, Any]:
        """Persist a later Companion revision only inside its attested domain."""
        return await self._portrait_emotion_family.revise_emotion_event(
            event,
            producer_context=producer_context,
        )

    async def get_emotion_trace(
        self,
        trace_id: str,
        *,
        requester_context: Any = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return only the scoped, redacted diagnostic projection for a trusted admin."""
        return await self._portrait_emotion_family.get_emotion_trace(
            trace_id,
            requester_context=requester_context,
            limit=limit,
        )

    async def get_emotion_trace_diagnostic(
        self,
        trace_id: str,
        requester_context: Any,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        return await self._portrait_emotion_family.get_emotion_trace_diagnostic(
            trace_id,
            requester_context,
            limit=limit,
        )

    async def get_emotion_trace_summary(
        self,
        requester_context: Any,
        *,
        cursor: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        return await self._portrait_emotion_family.get_emotion_trace_summary(
            requester_context,
            cursor=cursor,
            limit=limit,
        )

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
        return await self._recall_family.search_open_loops(session_id=session_id, limit=limit)

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
        return self._portrait_emotion_family.get_relationship_phase(
            session_id=session_id,
            scope=scope,
            platform=platform,
            user_id=user_id,
            group_id=group_id,
            bot_id=bot_id,
        )

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
        return self._portrait_emotion_family.peek_relationship_phase(
            session_id=session_id,
            scope=scope,
            platform=platform,
            user_id=user_id,
            group_id=group_id,
            bot_id=bot_id,
        )

    def get_recent_emotional_state(
        self,
        *,
        exclude_session_id: str = "",
        window_seconds: float = 1800.0,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Explain why the identity-free cross-window aggregate is unavailable."""
        return self._portrait_emotion_family.get_recent_emotional_state(
            exclude_session_id=exclude_session_id,
            window_seconds=window_seconds,
            limit=limit,
        )

    def _entity(self, payload: dict[str, Any]) -> EntityRef:
        return EntityRef(
            kind=str(payload.get("kind") or "user"),
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            role=str(payload.get("role") or "unknown"),
        )
