"""Database-free capability state and negative-cache helpers for C4.

This module deliberately knows only about the shared bot-personal contract.  It
does not inspect plugin modules, touch storage, or perform capability probing
itself; callers can use the cache to decide when a probe is worth attempting.
"""

from __future__ import annotations

import copy
import sys
import time
from collections.abc import Iterable, Mapping
from typing import Any


CAPABILITY_STATES = ("unprobed", "available", "degraded", "negative")

# 陪伴插件的插件名。宿主注册表、模块别名、目录名三处都要认。
COMPANION_PLUGIN_ID = "astrbot_plugin_private_companion"
# 只有宿主没有注册表 API 时才会用到的模块别名。走 import 前**先查 sys.modules**，
# 不要直接 import_module：那样会在插件没装时凭空造出一个空模块。
COMPANION_MODULE_ALIASES = (
    "data.plugins.astrbot_plugin_private_companion.main",
    "astrbot_plugin_private_companion.main",
)


def _text_of(value: object) -> str:
    try:
        return str(value or "").strip()
    except Exception:
        return ""


def _companion_identity_matches(value: object) -> bool:
    """判断一个星注册项的某个属性是不是陪伴插件。

    名字里可能带目录形态（``astrbot_plugin_private_companion``）也可能带显示名，
    所以两种写法都认；显示名带空格，用包含匹配而不是相等。
    """
    text = _text_of(value)
    if not text:
        return False
    return COMPANION_PLUGIN_ID in text or "private companion" in text.lower()


def _companion_api_usable(api: object) -> bool:
    """API 对象现在是不是真的可用。

    陪伴插件自己的 ``get_private_companion_api()`` 已经做过「插件活着吗 / 桥接
    active 吗」两道检查，所以拿到它返回的东西就信。直接摸 ``extension_api``
    时要自己补上第二道：它暴露 ``bridge_lifecycle_status()``，``active`` 不为
    true 说明桥接还没就绪。没有这个方法的对象一律按可用算——不要因为对方
    将来换了个形状就误报成「没装」。
    """
    if api is None:
        return False
    lifecycle = getattr(api, "bridge_lifecycle_status", None)
    if not callable(lifecycle):
        return True
    try:
        status = lifecycle()
    except Exception:
        return False
    return isinstance(status, dict) and status.get("active") is True


def _companion_api_from_object(candidate: object) -> object | None:
    """从模块或实例上取陪伴插件的 API，取不到就返回 None。

    优先走模块级 ``get_private_companion_api()``——那是陪伴插件对外的正式入口，
    它自己就做完了活性检查，判定标准不会在我们这边走样。
    """
    if candidate is None:
        return None
    getter = getattr(candidate, "get_private_companion_api", None)
    if callable(getter):
        try:
            api = getter() or None
        except Exception:
            api = None
        if _companion_api_usable(api):
            return api
    for attr in ("extension_api", "_extension_api"):
        api = getattr(candidate, attr, None)
        if _companion_api_usable(api):
            return api
    return None


def _companion_api_from_star(metadata: object) -> object | None:
    if metadata is None or not bool(getattr(metadata, "activated", True)):
        return None
    api = _companion_api_from_object(getattr(metadata, "star_cls", None))
    if api is not None:
        return api
    return _companion_api_from_object(getattr(metadata, "module", None))


def _companion_api_from_registry(context: object) -> tuple[object | None, bool]:
    """走宿主注册表找**当前活着的**陪伴插件实例。

    返回 ``(api, registry_available)``。``registry_available`` 为真表示宿主给出了
    注册表 API —— 此时**找不到就是真的没有**，不能再去翻 ``sys.modules``。
    """
    get_all_stars = getattr(context, "get_all_stars", None)
    get_registered_star = getattr(context, "get_registered_star", None)
    registry_available = callable(get_all_stars) or callable(get_registered_star)
    if not registry_available:
        return None, False

    seen: set[int] = set()

    def inspect(metadata: object) -> object | None:
        if metadata is None or id(metadata) in seen:
            return None
        seen.add(id(metadata))
        try:
            matched = any(
                _companion_identity_matches(getattr(metadata, attr, ""))
                for attr in ("name", "display_name", "root_dir_name", "module_path")
            )
        except Exception:
            matched = False
        if not matched:
            return None
        return _companion_api_from_star(metadata)

    if callable(get_all_stars):
        try:
            stars = list(get_all_stars() or [])
        except Exception:
            stars = []
        for metadata in stars:
            api = inspect(metadata)
            if api is not None:
                return api, True
    if callable(get_registered_star):
        try:
            api = inspect(get_registered_star(COMPANION_PLUGIN_ID))
        except Exception:
            api = None
        if api is not None:
            return api, True
    return None, True


def _companion_api_from_modules() -> object | None:
    for name in COMPANION_MODULE_ALIASES:
        module = sys.modules.get(name)
        if module is None:
            continue
        api = _companion_api_from_object(module)
        if api is not None:
            return api
    return None


def detect_companion_plugin(context: object = None) -> dict[str, object]:
    """真实探测陪伴插件是否已装且已激活。

    ``capability_descriptor(available=True)`` 只校验**记忆侧自己那份** contract 文件，
    跟陪伴插件在不在宿主里毫无关系，所以它恒为真。面板若拿它当「已安装」显示，
    就是一个无论装没装都说装了的话。

    探测顺序是有讲究的：

    1. **先查宿主注册表**（``context.get_all_stars()`` / ``get_registered_star()``），
       要的是当前**活着的**插件实例。
    2. 注册表可用却没找到，就是真的没装，**到此为止**。绝不能再去翻 ``sys.modules``：
       插件重载后旧模块会留在 ``sys.modules`` 里冒充还在，而
       ``importlib.import_module`` 更是会在根本没装时凭空造一个空模块出来——
       这正是 2.2.1 之前「装了也显示未安装、没装却显示已连接」两个方向的错因。
    3. 只有宿主压根没有注册表 API（老版本 AstrBot、单测环境）才退回模块别名。

    判定标准是陪伴插件的运行时入口返回非 ``None``：它答的是「现在真的能用」，
    而不是「磁盘上有这个目录」。模块能 import 但桥接未就绪，仍然报未装。
    """
    api, registry_available = _companion_api_from_registry(context)
    if api is None and not registry_available:
        api = _companion_api_from_modules()
    installed = api is not None
    return {
        "companion_installed": installed,
        "companion_plugin_name": COMPANION_PLUGIN_ID if installed else "",
    }


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
    "COMPANION_MODULE_ALIASES",
    "PROFILE_NAMES",
    "CapabilityCache",
    "build_capability_snapshot",
    "detect_companion_plugin",
]
