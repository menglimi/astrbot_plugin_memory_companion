"""Database-free capability state and negative-cache helpers for C4.

This module deliberately knows only about the shared bot-personal contract.  It
does not inspect plugin modules, touch storage, or perform capability probing
itself; callers can use the cache to decide when a probe is worth attempting.
"""

from __future__ import annotations

import copy
import importlib
import time
from collections.abc import Iterable, Mapping
from typing import Any


CAPABILITY_STATES = ("unprobed", "available", "degraded", "negative")

# 陪伴插件在宿主里的两种模块名：AstrBot 加载插件时用的是 ``data.plugins.<插件名>``，
# 直接按插件名 import 只在测试与脚本里成立。两者都要试。
COMPANION_PLUGIN_MODULES = (
    "data.plugins.astrbot_plugin_private_companion.main",
    "astrbot_plugin_private_companion.main",
)
COMPANION_PLUGIN_ID = "astrbot_plugin_private_companion"


def detect_companion_plugin() -> dict[str, object]:
    """真实探测陪伴插件是否已装且已激活。

    ``capability_descriptor(available=True)`` 只校验**记忆侧自己那份** contract 文件，
    跟陪伴插件在不在宿主里毫无关系，所以它恒为真。面板若拿它当「已安装」显示，
    就是一个无论装没装都说装了的话。

    这里改成真去问陪伴插件的运行时入口：``get_private_companion_api()`` 在插件未加载、
    未激活或桥接未就绪时返回 ``None``，因此它答的是「现在真的能用」而不是
    「磁盘上有这个目录」。

    探测不到就报未装。宁可显示「未安装」让用户去装，也不要虚标一个用不了的联动。
    """
    for module_name in COMPANION_PLUGIN_MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        getter = getattr(module, "get_private_companion_api", None)
        if not callable(getter):
            continue
        try:
            api = getter()
        except Exception:
            continue
        if api is not None:
            return {"companion_installed": True, "companion_plugin_name": COMPANION_PLUGIN_ID}
    return {"companion_installed": False, "companion_plugin_name": ""}

# Stable C4 capability profiles.  Keep this tuple closed: callers may report
# only profiles understood by both companion plugins.
PROFILE_NAMES = (
    "bot_schedule_current",
    "bot_schedule_history",
    "bot_creative",
    "bot_subjective",
    "locked_frame_personal",
)

_SNAPSHOT_KEYS = (
    "available",
    "state",
    "degraded",
    "pending",
    "contract_fingerprint",
    "contract_version",
    "schema_version",
    "windows",
    "memory_types",
    "domains",
    "profiles",
    "methods",
    "warnings",
    "error_code",
    "companion_installed",
    "companion_plugin_name",
)
_MAX_ITEMS = 64
_MAX_TEXT = 256

# Public name for the same closed set: it is the page-facing capability contract,
# so page consumers may read these keys and nothing else.  Kept as an alias so the
# existing `_SNAPSHOT_KEYS` callers keep working unchanged.
CAPABILITY_SNAPSHOT_FIELDS = _SNAPSHOT_KEYS


def _text(value: object, *, limit: int = _MAX_TEXT) -> str:
    try:
        return str(value or "")[:limit]
    except Exception:
        return ""


def _unique_texts(values: object, *, allowed: set[str] | None = None) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        return []
    result: list[str] = []
    try:
        for value in values:
            item = _text(value)
            if not item or (allowed is not None and item not in allowed) or item in result:
                continue
            result.append(item)
            if len(result) >= _MAX_ITEMS:
                break
    except Exception:
        return result
    return result


def _contract_value(module: object, name: str, default: object) -> object:
    try:
        return getattr(module, name)
    except Exception:
        return default


def _safe_contract_data(contract_module: object | None) -> dict[str, object]:
    if contract_module is None:
        try:
            from . import bot_personal_contract as contract_module
        except Exception:
            contract_module = None

    windows = _unique_texts(_contract_value(contract_module, "WINDOW_SLUGS", ()))
    memory_types = _unique_texts(_contract_value(contract_module, "BOT_PERSONAL_MEMORY_TYPES", ()))
    domain = _text(_contract_value(contract_module, "BOT_PERSONAL_MEMORY_DOMAIN", ""))
    domains = [domain] if domain else []
    return {
        "contract_fingerprint": _text(_contract_value(contract_module, "CONTRACT_FINGERPRINT", "")),
        "contract_version": _text(_contract_value(contract_module, "CONTRACT_REVISION", "")),
        "schema_version": _text(
            _contract_value(contract_module, "BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION", "")
        ),
        "windows": windows,
        "memory_types": memory_types,
        "domains": domains,
    }


def _state(value: object) -> str:
    candidate = _text(value).lower()
    return candidate if candidate in CAPABILITY_STATES else "unprobed"


def build_capability_snapshot(
    *,
    available: bool = False,
    state: str = "unprobed",
    contract_module: object | None = None,
    methods: Iterable[object] = (),
    domains: Iterable[object] = (),
    profiles: Iterable[object] = PROFILE_NAMES,
    warnings: Iterable[object] = (),
    error_code: object = "",
    companion_installed: bool = False,
    companion_plugin_name: object = "",
) -> dict[str, object]:
    """Build a bounded, JSON-safe capability snapshot.

    Pure by design: it never imports plugin modules.  ``companion_installed``
    therefore defaults to the conservative ``False`` and is filled in by
    :func:`detect_companion_plugin` at the call site that is allowed to touch
    the runtime.
    """

    contract = _safe_contract_data(contract_module)
    resolved_state = _state(state)
    if available:
        resolved_state = "available"
    elif resolved_state == "available":
        resolved_state = "degraded"

    supplied_domains = _unique_texts(domains)
    if not supplied_domains:
        supplied_domains = list(contract["domains"])

    result: dict[str, object] = {
        "available": resolved_state == "available",
        "state": resolved_state,
        "degraded": resolved_state in {"degraded", "negative"},
        "pending": resolved_state == "unprobed",
        "contract_fingerprint": contract["contract_fingerprint"],
        "contract_version": contract["contract_version"],
        "schema_version": contract["schema_version"],
        "windows": list(contract["windows"]),
        "memory_types": list(contract["memory_types"]),
        "domains": supplied_domains,
        "profiles": _unique_texts(profiles, allowed=set(PROFILE_NAMES)),
        "methods": _unique_texts(methods),
        "warnings": _unique_texts(warnings),
        "error_code": _text(error_code),
        "companion_installed": companion_installed is True,
        "companion_plugin_name": _text(companion_plugin_name, limit=80),
    }
    return {key: result[key] for key in _SNAPSHOT_KEYS}


class CapabilityCache:
    """In-memory capability state with a TTL-limited negative result."""

    def __init__(self, negative_ttl: float = 60.0, clock: object | None = None) -> None:
        try:
            self._negative_ttl = max(0.0, float(negative_ttl))
        except (TypeError, ValueError):
            self._negative_ttl = 60.0
        self._clock = clock if callable(clock) else time.monotonic
        self._snapshot = build_capability_snapshot()
        self._negative_at: float | None = None

    def _now(self) -> float:
        try:
            return float(self._clock())
        except Exception:
            return time.monotonic()

    def snapshot(self) -> dict[str, object]:
        if self._snapshot["state"] == "negative" and self._negative_at is not None:
            if self._now() - self._negative_at >= self._negative_ttl:
                self._snapshot = build_capability_snapshot()
                self._negative_at = None
        return copy.deepcopy(self._snapshot)

    def mark_available(self, snapshot: Mapping[str, object]) -> dict[str, object]:
        values = dict(snapshot) if isinstance(snapshot, Mapping) else {}
        self._snapshot = build_capability_snapshot(
            available=True,
            state="available",
            methods=values.get("methods", ()),
            domains=values.get("domains", ()),
            profiles=values.get("profiles", PROFILE_NAMES),
            warnings=values.get("warnings", ()),
            error_code=values.get("error_code", ""),
            contract_module=_MappingContract(values),
        )
        self._negative_at = None
        return self.snapshot()

    def mark_degraded(self, reason: object) -> dict[str, object]:
        current = self.snapshot()
        self._snapshot = build_capability_snapshot(
            state="degraded",
            methods=current["methods"],
            domains=current["domains"],
            profiles=current["profiles"],
            warnings=[*current["warnings"], _text(reason)] if _text(reason) else current["warnings"],
            error_code=_text(reason),
            contract_module=_MappingContract(current),
        )
        self._negative_at = None
        return self.snapshot()

    def mark_negative(self, reason: object) -> dict[str, object]:
        current = self.snapshot()
        self._snapshot = build_capability_snapshot(
            state="negative",
            methods=current["methods"],
            domains=current["domains"],
            profiles=current["profiles"],
            warnings=[*current["warnings"], _text(reason)] if _text(reason) else current["warnings"],
            error_code=_text(reason),
            contract_module=_MappingContract(current),
        )
        self._negative_at = self._now()
        return self.snapshot()

    def clear(self) -> dict[str, object]:
        self._snapshot = build_capability_snapshot()
        self._negative_at = None
        return self.snapshot()


class _MappingContract:
    """Attribute adapter used to preserve contract metadata across cache updates."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self.CONTRACT_FINGERPRINT = values.get("contract_fingerprint", "")
        self.CONTRACT_REVISION = values.get("contract_version", "")
        self.BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION = values.get("schema_version", "")
        self.WINDOW_SLUGS = values.get("windows", ())
        self.BOT_PERSONAL_MEMORY_TYPES = values.get("memory_types", ())
        domains = values.get("domains", ())
        self.BOT_PERSONAL_MEMORY_DOMAIN = domains[0] if isinstance(domains, list) and domains else ""


__all__ = [
    "CAPABILITY_SNAPSHOT_FIELDS",
    "CAPABILITY_STATES",
    "COMPANION_PLUGIN_ID",
    "COMPANION_PLUGIN_MODULES",
    "PROFILE_NAMES",
    "CapabilityCache",
    "build_capability_snapshot",
    "detect_companion_plugin",
]
