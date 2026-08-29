# -*- coding: utf-8 -*-
"""Strict, generation-aware consumer for Companion's Memory Page API.

The bridge deliberately resolves the published facade for every operation.  It
never returns that facade (or its host object) to the page layer, and it keeps
the one-release legacy adapter behind an explicit anti-downgrade latch.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import hashlib
import hmac
import inspect
import json
import re
import sys
import threading
import unicodedata
from dataclasses import dataclass
from datetime import date
from types import ModuleType
from typing import Any, Mapping


MEMORY_PLUGIN_ID = "astrbot_plugin_memory_companion"
COMPANION_PLUGIN_ID = "astrbot_plugin_private_companion"
MEMORY_PAGE_API_FAMILY = "companion.memory-page"
MEMORY_PAGE_API_VERSION = "companion.memory-page-api.v1"
MEMORY_PAGE_SNAPSHOT_VERSION = "companion.memory-page-snapshot.v1"
MEMORY_PAGE_PHOTO_VERSION = "companion.memory-page-photo.v1"

MEMORY_PAGE_SUPPORTED_TASK_VERSIONS = (
    MEMORY_PAGE_SNAPSHOT_VERSION,
    MEMORY_PAGE_PHOTO_VERSION,
)
MEMORY_PAGE_REQUIRED_CAPABILITIES = frozenset(
    {
        "memory.page.snapshot.export",
        "memory.page.snapshot.path-free",
        "memory.page.snapshot.read-only",
        "memory.page.photo.read",
    }
)
MEMORY_PAGE_FORMAL_METHODS = (
    "memory_page_capabilities",
    "export_memory_page_snapshot",
    "read_memory_page_photo",
)
COMPANION_MODULE_NAMES = (
    "data.plugins.astrbot_plugin_private_companion.main",
    "astrbot_plugin_private_companion.main",
)

MEMORY_PAGE_SNAPSHOT_MAX_BYTES = 256 * 1024
MEMORY_PAGE_PHOTO_MAX_BYTES = 8 * 1024 * 1024
MEMORY_PAGE_PHOTO_BASE64_MAX_CHARS = 11_184_812
MEMORY_PAGE_PHOTO_RESULT_MAX_BYTES = 12 * 1024 * 1024

_DESCRIPTOR_FIELDS = frozenset(
    {
        "plugin_id",
        "instance_generation",
        "api_family",
        "api_version",
        "supported_task_versions",
        "capabilities",
        "lifecycle_state",
        "degraded_reasons",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "version",
        "source_plugin_id",
        "instance_generation",
        "selected_date",
        "available_dates",
        "features",
        "coordination",
        "day",
        "snapshot_id",
        "snapshot_sha256",
    }
)
_SNAPSHOT_HASHED_FIELDS = (
    "version",
    "source_plugin_id",
    "instance_generation",
    "selected_date",
    "available_dates",
    "features",
    "coordination",
    "day",
)
_FEATURE_FIELDS = frozenset(
    {"daily_plan_enabled", "detail_enhancement_enabled"}
)
_COORDINATION_FIELDS = frozenset({"available", "state", "reason_code"})
_DAY_FIELDS = frozenset(
    {
        "date",
        "bot_name",
        "plan",
        "current_item",
        "daily_state",
        "details",
        "photos",
        "diaries",
    }
)
_PLAN_FIELDS = frozenset({"date", "source", "items"})
_PLAN_ITEM_FIELDS = frozenset(
    {"index", "time", "activity", "mood", "message_seed"}
)
_DAILY_STATE_FIELDS = frozenset(
    {"date", "energy", "mood_bias", "sleep", "weather", "note"}
)
_DETAIL_FIELDS = frozenset(
    {
        "id",
        "index",
        "status",
        "time",
        "summary",
        "today_events",
        "proactive_events",
        "state_variables",
    }
)
_PHOTO_FIELDS = frozenset(
    {
        "id",
        "date",
        "kind",
        "generated_at",
        "available",
        "error_code",
        "photo_ref",
    }
)
_DIARY_FIELDS = frozenset(
    {
        "date",
        "summary",
        "body",
        "share_seed",
        "tags",
        "today_events",
        "proactive_events",
        "long_term_events",
    }
)
_PHOTO_RESULT_FIELDS = frozenset(
    {
        "version",
        "source_plugin_id",
        "instance_generation",
        "photo_ref",
        "mime_type",
        "size",
        "sha256",
        "content_base64",
    }
)

_GENERATION_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_ID_RE = re.compile(r"^memorypagesnap_[0-9a-f]{64}$")
_PHOTO_REF_RE = re.compile(r"^mphoto_([0-9a-f]{12})_([A-Za-z0-9_-]{22})$")
_OPAQUE_ID_RE = re.compile(r"^(?:detail|photo)_[A-Za-z0-9_-]{22}$")
_REASON_RE = re.compile(r"^(?:|[a-z][a-z0-9_]{0,63})$")

_LIFECYCLE_STATES = frozenset({"created", "ready", "superseded", "closed"})
_COORDINATION_STATES = frozenset(
    {"ready", "degraded", "local_only", "disabled", "inactive", "unavailable"}
)
_DETAIL_STATES = frozenset(
    {"planned", "ready", "observed", "degraded", "story_plan", "unknown"}
)
_PHOTO_KINDS = frozenset({"daily_outfit", "recent_photo", "life_photo"})
_PLAN_SOURCES = frozenset({"live", "history", "none"})

_KNOWN_PRODUCER_CODES = frozenset(
    {
        "memory_page_target_mismatch",
        "memory_page_service_closed",
        "memory_page_snapshot_invalid_date",
        "memory_page_snapshot_state_unavailable",
        "memory_page_snapshot_too_large",
        "memory_page_snapshot_build_failed",
        "memory_page_photo_ref_invalid",
        "memory_page_photo_ref_stale",
        "memory_page_photo_ref_expired",
        "memory_page_photo_unavailable",
        "memory_page_photo_too_large",
        "memory_page_photo_changed",
        "memory_page_photo_unsupported",
        "memory_page_photo_read_failed",
    }
)

_COMPANION_PAGE_RUNTIME_KEY = (
    "_astrbot_memory_companion_page_consumer_runtime_v1"
)


def _install_companion_page_runtime() -> ModuleType:
    candidate = ModuleType(_COMPANION_PAGE_RUNTIME_KEY)
    candidate.lock = threading.RLock()
    candidate.formal_seen = False
    return sys.modules.setdefault(_COMPANION_PAGE_RUNTIME_KEY, candidate)


_COMPANION_PAGE_RUNTIME = _install_companion_page_runtime()


class CompanionPageBridgeError(ValueError):
    """A stable refusal without producer exception bodies."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _GenerationChanged(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CompanionPageSnapshot:
    payload: dict[str, Any]
    mode: str


@dataclass(frozen=True, slots=True)
class CompanionPagePhoto:
    photo_ref: str
    mime_type: str
    size: int
    sha256: str
    content_base64: str
    content: bytes
    mode: str


@dataclass(frozen=True, slots=True)
class _ResolvedAPI:
    api: Any
    module_name: str


def _fail(code: str) -> None:
    raise CompanionPageBridgeError(code)


def _exact_mapping(value: Any, fields: frozenset[str], *, code: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        _fail(code)
    if any(type(key) is not str for key in value) or set(value) != fields:
        _fail(code)
    return value


def _text(
    value: Any,
    maximum: int,
    *,
    code: str,
    required: bool = False,
) -> str:
    if type(value) is not str or len(value) > maximum:
        _fail(code)
    if required and not value:
        _fail(code)
    for character in value:
        category = unicodedata.category(character)
        if category in {"Cs", "Cc"}:
            _fail(code)
    return value


def _integer(
    value: Any,
    minimum: int,
    maximum: int,
    *,
    code: str,
    nullable: bool = False,
) -> int | None:
    if nullable and value is None:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(code)
    return value


def _iso_date(value: Any, *, code: str, allow_empty: bool = True) -> str:
    text = _text(value, 10, code=code)
    if not text and allow_empty:
        return ""
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        _fail(code)
    if parsed.isoformat() != text:
        _fail(code)
    return text


def _text_list(
    value: Any,
    *,
    count: int,
    maximum: int,
    code: str,
    unique: bool = False,
) -> list[str]:
    if type(value) is not list or len(value) > count:
        _fail(code)
    rows = [_text(item, maximum, code=code) for item in value]
    if unique and len(set(rows)) != len(rows):
        _fail(code)
    return rows


def _canonical_json(value: Any, *, code: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", "strict")
    except (TypeError, ValueError, UnicodeEncodeError):
        _fail(code)


def snapshot_payload_sha256(value: Mapping[str, Any]) -> str:
    hashed = {field: value[field] for field in _SNAPSHOT_HASHED_FIELDS}
    return hashlib.sha256(
        _canonical_json(hashed, code="memory_page_snapshot_malformed")
    ).hexdigest()


def seal_memory_page_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal the eight hash-covered fields for the isolated legacy adapter."""

    if type(value) is not dict or set(value) != set(_SNAPSHOT_HASHED_FIELDS):
        _fail("memory_page_snapshot_malformed")
    detached = copy.deepcopy(value)
    digest = snapshot_payload_sha256(detached)
    detached["snapshot_id"] = f"memorypagesnap_{digest}"
    detached["snapshot_sha256"] = digest
    return detached


def validate_memory_page_descriptor(value: Any) -> dict[str, Any]:
    code = "memory_page_contract_malformed"
    raw = _exact_mapping(value, _DESCRIPTOR_FIELDS, code=code)
    if _text(raw["plugin_id"], 120, code=code, required=True) != COMPANION_PLUGIN_ID:
        _fail(code)
    generation = _text(raw["instance_generation"], 32, code=code, required=True)
    if _GENERATION_RE.fullmatch(generation) is None:
        _fail(code)
    if _text(raw["api_family"], 80, code=code, required=True) != MEMORY_PAGE_API_FAMILY:
        _fail("memory_page_contract_unsupported")
    if _text(raw["api_version"], 80, code=code, required=True) != MEMORY_PAGE_API_VERSION:
        _fail("memory_page_contract_unsupported")
    versions = raw["supported_task_versions"]
    if type(versions) is not list or versions != list(MEMORY_PAGE_SUPPORTED_TASK_VERSIONS):
        _fail("memory_page_contract_unsupported")
    capabilities = _text_list(
        raw["capabilities"], count=32, maximum=100, code=code, unique=True
    )
    if not MEMORY_PAGE_REQUIRED_CAPABILITIES.issubset(capabilities):
        _fail("memory_page_contract_unsupported")
    lifecycle = _text(raw["lifecycle_state"], 24, code=code, required=True)
    if lifecycle not in _LIFECYCLE_STATES:
        _fail(code)
    degraded = _text_list(
        raw["degraded_reasons"], count=8, maximum=100, code=code, unique=True
    )
    if lifecycle == "ready":
        if degraded:
            _fail("memory_page_snapshot_state_unavailable")
    elif degraded != ["memory_page_snapshot_service_not_ready"]:
        _fail(code)
    return copy.deepcopy(raw)


def _validate_plan_item(value: Any, *, nullable_index: bool, code: str) -> None:
    raw = _exact_mapping(value, _PLAN_ITEM_FIELDS, code=code)
    _integer(raw["index"], 0, 17, code=code, nullable=nullable_index)
    _text(raw["time"], 20, code=code)
    _text(raw["activity"], 180, code=code)
    _text(raw["mood"], 80, code=code)
    _text(raw["message_seed"], 220, code=code)


def _validate_detail(value: Any, *, code: str) -> None:
    raw = _exact_mapping(value, _DETAIL_FIELDS, code=code)
    identifier = _text(raw["id"], 127, code=code, required=True)
    if _OPAQUE_ID_RE.fullmatch(identifier) is None or not identifier.startswith("detail_"):
        _fail(code)
    _integer(raw["index"], 0, 17, code=code, nullable=True)
    status = _text(raw["status"], 24, code=code, required=True)
    if status not in _DETAIL_STATES:
        _fail(code)
    _text(raw["time"], 20, code=code)
    _text(raw["summary"], 180, code=code)
    for field in ("today_events", "proactive_events", "state_variables"):
        _text_list(raw[field], count=5, maximum=180, code=code, unique=True)


def _validate_snapshot_photo(
    value: Any,
    *,
    generation: str,
    selected_date: str,
    code: str,
) -> None:
    raw = _exact_mapping(value, _PHOTO_FIELDS, code=code)
    identifier = _text(raw["id"], 126, code=code, required=True)
    if _OPAQUE_ID_RE.fullmatch(identifier) is None or not identifier.startswith("photo_"):
        _fail(code)
    if _iso_date(raw["date"], code=code) != selected_date:
        _fail(code)
    kind = _text(raw["kind"], 40, code=code, required=True)
    if kind not in _PHOTO_KINDS:
        _fail(code)
    _integer(raw["generated_at"], 0, 10**10, code=code)
    if type(raw["available"]) is not bool:
        _fail(code)
    reason = _text(raw["error_code"], 64, code=code)
    if _REASON_RE.fullmatch(reason) is None:
        _fail(code)
    photo_ref = _text(raw["photo_ref"], 48, code=code)
    if photo_ref:
        match = _PHOTO_REF_RE.fullmatch(photo_ref)
        if match is None or match.group(1) != generation[:12]:
            _fail(code)
    if raw["available"] is True:
        if not photo_ref or reason:
            _fail(code)
    elif not reason or photo_ref:
        _fail(code)


def _validate_diary(value: Any, *, selected_date: str, code: str) -> None:
    raw = _exact_mapping(value, _DIARY_FIELDS, code=code)
    if _iso_date(raw["date"], code=code) != selected_date:
        _fail(code)
    _text(raw["summary"], 220, code=code)
    _text(raw["body"], 520, code=code)
    _text(raw["share_seed"], 180, code=code)
    _text_list(raw["tags"], count=8, maximum=40, code=code, unique=True)
    for field in ("today_events", "proactive_events", "long_term_events"):
        _text_list(raw[field], count=5, maximum=180, code=code, unique=True)


def validate_memory_page_snapshot(
    value: Any,
    *,
    expected_generation: str,
    expected_selected_date: str = "",
) -> dict[str, Any]:
    code = "memory_page_snapshot_malformed"
    raw = _exact_mapping(value, _SNAPSHOT_FIELDS, code=code)
    if _text(raw["version"], 80, code=code, required=True) != MEMORY_PAGE_SNAPSHOT_VERSION:
        _fail("memory_page_contract_unsupported")
    if _text(raw["source_plugin_id"], 120, code=code, required=True) != COMPANION_PLUGIN_ID:
        _fail(code)
    generation = _text(raw["instance_generation"], 32, code=code, required=True)
    if generation != expected_generation or _GENERATION_RE.fullmatch(generation) is None:
        _fail(code)
    selected_date = _iso_date(raw["selected_date"], code=code)
    if expected_selected_date and selected_date != expected_selected_date:
        _fail(code)
    dates = raw["available_dates"]
    if type(dates) is not list or len(dates) > 180:
        _fail(code)
    checked_dates = [_iso_date(item, code=code, allow_empty=False) for item in dates]
    if len(set(checked_dates)) != len(checked_dates) or checked_dates != sorted(
        checked_dates, reverse=True
    ):
        _fail(code)
    if not expected_selected_date and selected_date != (
        checked_dates[0] if checked_dates else ""
    ):
        _fail(code)

    features = _exact_mapping(raw["features"], _FEATURE_FIELDS, code=code)
    if any(type(features[field]) is not bool for field in _FEATURE_FIELDS):
        _fail(code)
    coordination = _exact_mapping(raw["coordination"], _COORDINATION_FIELDS, code=code)
    if type(coordination["available"]) is not bool:
        _fail(code)
    state = _text(coordination["state"], 20, code=code, required=True)
    reason = _text(coordination["reason_code"], 64, code=code)
    if state not in _COORDINATION_STATES or _REASON_RE.fullmatch(reason) is None:
        _fail(code)
    if state != "ready" and not reason:
        _fail(code)

    day = _exact_mapping(raw["day"], _DAY_FIELDS, code=code)
    day_date = _iso_date(day["date"], code=code)
    if selected_date != day_date:
        _fail(code)
    _text(day["bot_name"], 80, code=code)
    plan = _exact_mapping(day["plan"], _PLAN_FIELDS, code=code)
    plan_date = _iso_date(plan["date"], code=code)
    if day_date and plan_date and day_date != plan_date:
        _fail(code)
    source = _text(plan["source"], 20, code=code, required=True)
    if source not in _PLAN_SOURCES:
        _fail(code)
    if type(plan["items"]) is not list or len(plan["items"]) > 18:
        _fail(code)
    if source == "none":
        if plan_date or plan["items"]:
            _fail(code)
    elif plan_date != day_date:
        _fail(code)
    previous_index = -1
    for item in plan["items"]:
        _validate_plan_item(item, nullable_index=False, code=code)
        if item["index"] <= previous_index:
            _fail(code)
        previous_index = item["index"]
    _validate_plan_item(day["current_item"], nullable_index=True, code=code)
    current_index = day["current_item"]["index"]
    if current_index is not None:
        matching = next(
            (
                item
                for item in plan["items"]
                if item["index"] == current_index
            ),
            None,
        )
        if source != "live" or day["current_item"] != matching:
            _fail(code)
    elif source != "live" and any(
        day["current_item"][field]
        for field in ("time", "activity", "mood", "message_seed")
    ):
        _fail(code)

    daily_state = _exact_mapping(day["daily_state"], _DAILY_STATE_FIELDS, code=code)
    state_date = _iso_date(daily_state["date"], code=code)
    if state_date not in {"", day_date}:
        _fail(code)
    _integer(daily_state["energy"], 0, 100, code=code, nullable=True)
    _text(daily_state["mood_bias"], 80, code=code)
    _text(daily_state["sleep"], 80, code=code)
    _text(daily_state["weather"], 80, code=code)
    _text(daily_state["note"], 180, code=code)
    if not state_date and any(
        daily_state[field] not in {None, ""}
        for field in ("energy", "mood_bias", "sleep", "weather", "note")
    ):
        _fail(code)

    if type(day["details"]) is not list or len(day["details"]) > 18:
        _fail(code)
    detail_ids: set[str] = set()
    for item in day["details"]:
        _validate_detail(item, code=code)
        identifier = item["id"]
        if identifier in detail_ids:
            _fail(code)
        detail_ids.add(identifier)

    if type(day["photos"]) is not list or len(day["photos"]) > 8:
        _fail(code)
    photo_ids: set[str] = set()
    for item in day["photos"]:
        _validate_snapshot_photo(
            item,
            generation=generation,
            selected_date=selected_date,
            code=code,
        )
        if item["id"] in photo_ids:
            _fail(code)
        photo_ids.add(item["id"])

    if type(day["diaries"]) is not list or len(day["diaries"]) > 4:
        _fail(code)
    for item in day["diaries"]:
        _validate_diary(item, selected_date=selected_date, code=code)

    snapshot_id = _text(raw["snapshot_id"], 79, code=code, required=True)
    digest = _text(raw["snapshot_sha256"], 64, code=code, required=True)
    if _SNAPSHOT_ID_RE.fullmatch(snapshot_id) is None or _SHA256_RE.fullmatch(digest) is None:
        _fail(code)
    expected_digest = snapshot_payload_sha256(raw)
    if (
        snapshot_id != f"memorypagesnap_{digest}"
        or not hmac.compare_digest(digest, expected_digest)
    ):
        _fail(code)
    encoded = _canonical_json(raw, code=code)
    if len(encoded) > MEMORY_PAGE_SNAPSHOT_MAX_BYTES:
        _fail("memory_page_snapshot_too_large")
    return copy.deepcopy(raw)


def _photo_magic(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"BM"):
        return "image/bmp"
    if (
        len(content) >= 12
        and content[4:8] == b"ftyp"
        and content[8:12] in {b"avif", b"avis"}
    ):
        return "image/avif"
    _fail("memory_page_photo_unsupported")


def validate_memory_page_photo(
    value: Any,
    *,
    expected_generation: str,
    expected_photo_ref: str,
) -> CompanionPagePhoto:
    code = "memory_page_photo_malformed"
    raw = _exact_mapping(value, _PHOTO_RESULT_FIELDS, code=code)
    if _text(raw["version"], 80, code=code, required=True) != MEMORY_PAGE_PHOTO_VERSION:
        _fail("memory_page_contract_unsupported")
    if _text(raw["source_plugin_id"], 120, code=code, required=True) != COMPANION_PLUGIN_ID:
        _fail(code)
    generation = _text(raw["instance_generation"], 32, code=code, required=True)
    if generation != expected_generation or _GENERATION_RE.fullmatch(generation) is None:
        _fail("memory_page_photo_ref_stale")
    photo_ref = _text(raw["photo_ref"], 48, code=code, required=True)
    if photo_ref != expected_photo_ref:
        _fail(code)
    match = _PHOTO_REF_RE.fullmatch(photo_ref)
    if match is None or match.group(1) != generation[:12]:
        _fail("memory_page_photo_ref_stale")
    mime_type = _text(raw["mime_type"], 40, code=code, required=True)
    size = _integer(raw["size"], 1, MEMORY_PAGE_PHOTO_MAX_BYTES, code=code)
    digest = _text(raw["sha256"], 64, code=code, required=True)
    if _SHA256_RE.fullmatch(digest) is None:
        _fail(code)
    encoded = _text(
        raw["content_base64"],
        MEMORY_PAGE_PHOTO_BASE64_MAX_CHARS,
        code=code,
        required=True,
    )
    if len(_canonical_json(raw, code=code)) > MEMORY_PAGE_PHOTO_RESULT_MAX_BYTES:
        _fail("memory_page_photo_too_large")
    try:
        content = base64.b64decode(encoded.encode("ascii", "strict"), validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error):
        _fail(code)
    if (
        len(content) != size
        or base64.b64encode(content).decode("ascii") != encoded
        or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest)
    ):
        _fail(code)
    detected = _photo_magic(content)
    if mime_type != detected:
        _fail("memory_page_photo_unsupported")
    return CompanionPagePhoto(
        photo_ref=photo_ref,
        mime_type=mime_type,
        size=size,
        sha256=digest,
        content_base64=encoded,
        content=content,
        mode="formal",
    )


class CompanionPageBridge:
    """Resolve and consume the current Companion facade without retaining it."""

    def __init__(self, owner: Any | None = None) -> None:
        self._owner = owner
        self._lock = threading.RLock()
        self._legacy_api: Any | None = None
        self._legacy_adapter: Any | None = None

    @property
    def formal_seen(self) -> bool:
        with _COMPANION_PAGE_RUNTIME.lock:
            return _COMPANION_PAGE_RUNTIME.formal_seen is True

    @staticmethod
    def _registry_identity_matches(metadata: Any) -> bool:
        expected = COMPANION_PLUGIN_ID.casefold().replace("-", "_")
        values = (
            getattr(metadata, "name", ""),
            getattr(metadata, "root_dir_name", ""),
            getattr(metadata, "module_path", ""),
            getattr(getattr(metadata, "module", None), "__name__", ""),
            getattr(getattr(metadata, "star_cls", None), "plugin_id", ""),
            getattr(type(getattr(metadata, "star_cls", None)), "__module__", ""),
        )
        for value in values:
            try:
                text = str(value or "").casefold().replace("-", "_").replace("/", ".")
            except Exception:
                continue
            if expected in {part for part in text.split(".") if part}:
                return True
        return False

    def _resolve_api(self) -> _ResolvedAPI:
        candidates: list[_ResolvedAPI] = []
        getter_failed = False
        getter_returned_none = False

        def add_candidate(api: Any, source: str) -> None:
            if api is not None and all(candidate.api is not api for candidate in candidates):
                candidates.append(_ResolvedAPI(api=api, module_name=source))

        context = getattr(self._owner, "context", None)
        get_all = getattr(context, "get_all_stars", None)
        get_one = getattr(context, "get_registered_star", None)
        registry_available = callable(get_all) or callable(get_one)
        registry_entries: list[tuple[Any, bool]] = []
        positions: dict[int, int] = {}
        if callable(get_all):
            try:
                stars = list(get_all() or [])
            except Exception:
                getter_failed = True
                stars = []
            for metadata in stars:
                if metadata is None or id(metadata) in positions:
                    continue
                positions[id(metadata)] = len(registry_entries)
                registry_entries.append((metadata, False))
        if callable(get_one):
            try:
                metadata = get_one(COMPANION_PLUGIN_ID)
            except Exception:
                getter_failed = True
                metadata = None
            if metadata is not None:
                position = positions.get(id(metadata))
                if position is None:
                    registry_entries.append((metadata, True))
                else:
                    registry_entries[position] = (metadata, True)

        for metadata, exact_match in registry_entries:
            if not bool(getattr(metadata, "activated", True)):
                continue
            if not exact_match and not self._registry_identity_matches(metadata):
                continue
            module = getattr(metadata, "module", None)
            if module is not None:
                try:
                    getter = getattr(module, "get_private_companion_api", None)
                except Exception:
                    getter_failed = True
                else:
                    if callable(getter):
                        try:
                            api = getter()
                        except Exception:
                            getter_failed = True
                        else:
                            if api is None:
                                getter_returned_none = True
                            else:
                                add_candidate(api, str(getattr(module, "__name__", "registry")))
            instance = getattr(metadata, "star_cls", None)
            if instance is None and exact_match and hasattr(metadata, "extension_api"):
                instance = metadata
            try:
                instance_api = getattr(instance, "extension_api", None)
            except Exception:
                getter_failed = True
            else:
                if instance_api is not None:
                    add_candidate(instance_api, "registry")

        # A current-plugin registry is authoritative. Module aliases can
        # survive unload/reload and must never resurrect an old generation.
        if not registry_available:
            for module_name in COMPANION_MODULE_NAMES:
                module = sys.modules.get(module_name)
                if module is None:
                    continue
                try:
                    getter = getattr(module, "get_private_companion_api", None)
                except Exception:
                    getter_failed = True
                    continue
                if not callable(getter):
                    getter_failed = True
                    continue
                try:
                    api = getter()
                except Exception:
                    getter_failed = True
                    continue
                if api is None:
                    getter_returned_none = True
                    continue
                add_candidate(api, module_name)
        if len(candidates) > 1:
            if any(
                CompanionPageBridge._formal_surface(candidate.api)
                for candidate in candidates
            ):
                with _COMPANION_PAGE_RUNTIME.lock:
                    _COMPANION_PAGE_RUNTIME.formal_seen = True
            _fail("memory_page_companion_ambiguous")
        if getter_failed or (candidates and getter_returned_none):
            if candidates and CompanionPageBridge._formal_surface(candidates[0].api):
                with _COMPANION_PAGE_RUNTIME.lock:
                    _COMPANION_PAGE_RUNTIME.formal_seen = True
            _fail("memory_page_companion_unreadable")
        if candidates:
            return candidates[0]
        _fail("memory_page_companion_unavailable")

    @staticmethod
    def _formal_surface(api: Any) -> bool:
        missing = object()
        markers = [
            inspect.getattr_static(api, name, missing) is not missing
            for name in MEMORY_PAGE_FORMAL_METHODS
        ]
        return any(markers)

    def _select_surface(self, resolved: _ResolvedAPI) -> str:
        formal = self._formal_surface(resolved.api)
        with _COMPANION_PAGE_RUNTIME.lock:
            if formal:
                _COMPANION_PAGE_RUNTIME.formal_seen = True
            formal_seen = _COMPANION_PAGE_RUNTIME.formal_seen is True
        if formal:
            self._retire_legacy()
            return "formal"
        if formal_seen:
            self._retire_legacy()
            _fail("memory_page_contract_downgrade")
        return "legacy"

    def _retire_legacy(self) -> None:
        with self._lock:
            adapter = self._legacy_adapter
            self._legacy_api = None
            self._legacy_adapter = None
        if adapter is not None:
            adapter.close()

    @staticmethod
    def _formal_methods(api: Any) -> tuple[Any, Any, Any]:
        methods: list[Any] = []
        for name in MEMORY_PAGE_FORMAL_METHODS:
            try:
                method = getattr(api, name)
            except Exception:
                _fail("memory_page_contract_malformed")
            if not callable(method):
                _fail("memory_page_contract_malformed")
            methods.append(method)
        return methods[0], methods[1], methods[2]

    @staticmethod
    def _producer_error(exc: Exception, fallback: str) -> CompanionPageBridgeError:
        code = getattr(exc, "code", None)
        if type(code) is str and code in _KNOWN_PRODUCER_CODES:
            return CompanionPageBridgeError(code)
        return CompanionPageBridgeError(fallback)

    def _legacy_for(self, api: Any, *, create: bool) -> Any:
        from .companion_page_legacy import LegacyCompanionPageAdapter

        adapter: Any | None = None
        previous: Any | None = None
        error = ""
        with _COMPANION_PAGE_RUNTIME.lock:
            with self._lock:
                if _COMPANION_PAGE_RUNTIME.formal_seen is True:
                    previous = self._legacy_adapter
                    self._legacy_api = None
                    self._legacy_adapter = None
                    error = "memory_page_contract_downgrade"
                elif self._legacy_api is api and self._legacy_adapter is not None:
                    try:
                        self._legacy_adapter.assert_live()
                    except CompanionPageBridgeError as exc:
                        if exc.code == "memory_page_service_closed":
                            adapter = self._legacy_adapter
                        else:
                            error = exc.code
                    else:
                        if LegacyCompanionPageAdapter.matches(api):
                            adapter = self._legacy_adapter
                        else:
                            previous = self._legacy_adapter
                            self._legacy_api = None
                            self._legacy_adapter = None
                            error = "memory_page_legacy_unsupported"
                else:
                    previous = self._legacy_adapter
                    self._legacy_api = None
                    self._legacy_adapter = None
                    if not LegacyCompanionPageAdapter.matches(api):
                        error = "memory_page_legacy_unsupported"
                    elif not create:
                        error = "memory_page_photo_ref_stale"
                    else:
                        adapter = LegacyCompanionPageAdapter(api)
                        self._legacy_api = api
                        self._legacy_adapter = adapter
        if previous is not None and previous is not adapter:
            previous.close()
        if error:
            _fail(error)
        return adapter

    def _same_api(self, before: _ResolvedAPI) -> _ResolvedAPI:
        try:
            after = self._resolve_api()
        except CompanionPageBridgeError:
            raise _GenerationChanged from None
        if after.api is not before.api:
            raise _GenerationChanged
        return after

    def _same_formal_generation(
        self,
        resolved: _ResolvedAPI,
        capabilities: Any,
        generation: str,
    ) -> None:
        self._same_api(resolved)
        try:
            descriptor = validate_memory_page_descriptor(capabilities())
        except CompanionPageBridgeError:
            self._same_api(resolved)
            raise
        except Exception:
            self._same_api(resolved)
            _fail("memory_page_contract_malformed")
        if (
            descriptor["instance_generation"] != generation
            or descriptor["lifecycle_state"] != "ready"
        ):
            raise _GenerationChanged
        self._same_api(resolved)

    def _same_legacy_generation(
        self,
        resolved: _ResolvedAPI,
        adapter: Any,
    ) -> None:
        self._same_api(resolved)
        try:
            adapter.assert_live()
        except CompanionPageBridgeError as exc:
            if exc.code != "memory_page_service_closed":
                raise
            from .companion_page_legacy import LegacyCompanionPageAdapter

            if LegacyCompanionPageAdapter.matches(resolved.api):
                raise _GenerationChanged from None
            raise
        self._same_api(resolved)

    async def _formal_snapshot_once(
        self,
        resolved: _ResolvedAPI,
        selected_date: str,
    ) -> CompanionPageSnapshot:
        try:
            capabilities, exporter, _reader = self._formal_methods(resolved.api)
        except CompanionPageBridgeError:
            self._same_api(resolved)
            raise
        try:
            descriptor = validate_memory_page_descriptor(capabilities())
        except CompanionPageBridgeError:
            self._same_api(resolved)
            raise
        except Exception:
            self._same_api(resolved)
            _fail("memory_page_contract_malformed")
        self._same_api(resolved)
        if descriptor["lifecycle_state"] != "ready":
            _fail("memory_page_snapshot_state_unavailable")
        generation = descriptor["instance_generation"]
        try:
            pending = exporter(
                target_plugin_id=MEMORY_PLUGIN_ID,
                selected_date=selected_date,
            )
            if not inspect.isawaitable(pending):
                _fail("memory_page_contract_malformed")
            raw = await pending
        except asyncio.CancelledError:
            raise
        except CompanionPageBridgeError:
            self._same_formal_generation(resolved, capabilities, generation)
            raise
        except Exception as exc:
            self._same_formal_generation(resolved, capabilities, generation)
            raise self._producer_error(exc, "memory_page_snapshot_build_failed") from None
        self._same_formal_generation(resolved, capabilities, generation)
        payload = validate_memory_page_snapshot(
            raw,
            expected_generation=generation,
            expected_selected_date=selected_date,
        )
        return CompanionPageSnapshot(payload=payload, mode="formal")

    async def _legacy_snapshot_once(
        self,
        resolved: _ResolvedAPI,
        selected_date: str,
    ) -> CompanionPageSnapshot:
        adapter: Any | None = None
        try:
            adapter = self._legacy_for(resolved.api, create=True)
            raw = await adapter.export_snapshot(selected_date)
        except asyncio.CancelledError:
            raise
        except CompanionPageBridgeError as exc:
            if adapter is not None and exc.code == "memory_page_service_closed":
                try:
                    self._same_legacy_generation(resolved, adapter)
                except _GenerationChanged:
                    raise
                except CompanionPageBridgeError:
                    self._retire_legacy()
                    raise
                self._retire_legacy()
            else:
                self._same_api(resolved)
            raise
        except Exception:
            try:
                self._same_api(resolved)
            except _GenerationChanged:
                raise
            _fail("memory_page_snapshot_build_failed")
        try:
            self._same_legacy_generation(resolved, adapter)
            if self._select_surface(resolved) != "legacy":
                raise _GenerationChanged
            payload = validate_memory_page_snapshot(
                raw,
                expected_generation=adapter.instance_generation,
                expected_selected_date=selected_date,
            )
            self._same_legacy_generation(resolved, adapter)
        except CompanionPageBridgeError as exc:
            if exc.code == "memory_page_service_closed":
                self._retire_legacy()
            raise
        return CompanionPageSnapshot(payload=payload, mode="legacy")

    async def export_snapshot(
        self,
        selected_date: str = "",
        *,
        expected_mode: str | None = None,
    ) -> CompanionPageSnapshot:
        selected = _iso_date(
            selected_date,
            code="memory_page_snapshot_invalid_date",
        )
        if expected_mode not in {None, "formal", "legacy"}:
            _fail("memory_page_photo_ref_invalid")
        for attempt in range(2):
            resolved = self._resolve_api()
            surface = self._select_surface(resolved)
            if expected_mode is not None and surface != expected_mode:
                _fail("memory_page_photo_ref_stale")
            try:
                if surface == "formal":
                    return await self._formal_snapshot_once(resolved, selected)
                return await self._legacy_snapshot_once(resolved, selected)
            except _GenerationChanged:
                self._retire_legacy()
                if attempt == 0:
                    continue
                _fail("memory_page_generation_changed")
        _fail("memory_page_generation_changed")

    async def _formal_photo(
        self,
        resolved: _ResolvedAPI,
        photo_ref: str,
    ) -> CompanionPagePhoto:
        try:
            capabilities, _exporter, reader = self._formal_methods(resolved.api)
        except CompanionPageBridgeError:
            try:
                self._same_api(resolved)
            except _GenerationChanged:
                _fail("memory_page_photo_ref_stale")
            raise
        try:
            descriptor = validate_memory_page_descriptor(capabilities())
        except CompanionPageBridgeError:
            try:
                self._same_api(resolved)
            except _GenerationChanged:
                _fail("memory_page_photo_ref_stale")
            raise
        except Exception:
            try:
                self._same_api(resolved)
            except _GenerationChanged:
                _fail("memory_page_photo_ref_stale")
            _fail("memory_page_contract_malformed")
        try:
            self._same_api(resolved)
        except _GenerationChanged:
            _fail("memory_page_photo_ref_stale")
        generation = descriptor["instance_generation"]
        match = _PHOTO_REF_RE.fullmatch(photo_ref)
        if match is None:
            _fail("memory_page_photo_ref_invalid")
        if match.group(1) != generation[:12]:
            _fail("memory_page_photo_ref_stale")
        if descriptor["lifecycle_state"] != "ready":
            _fail("memory_page_service_closed")
        try:
            pending = reader(
                target_plugin_id=MEMORY_PLUGIN_ID,
                photo_ref=photo_ref,
            )
            if not inspect.isawaitable(pending):
                _fail("memory_page_contract_malformed")
            raw = await pending
        except asyncio.CancelledError:
            raise
        except CompanionPageBridgeError:
            try:
                self._same_formal_generation(
                    resolved,
                    capabilities,
                    generation,
                )
            except _GenerationChanged:
                _fail("memory_page_photo_ref_stale")
            raise
        except Exception as exc:
            try:
                self._same_formal_generation(
                    resolved,
                    capabilities,
                    generation,
                )
            except _GenerationChanged:
                _fail("memory_page_photo_ref_stale")
            raise self._producer_error(exc, "memory_page_photo_read_failed") from None
        try:
            self._same_formal_generation(
                resolved,
                capabilities,
                generation,
            )
        except _GenerationChanged:
            _fail("memory_page_photo_ref_stale")
        return validate_memory_page_photo(
            raw,
            expected_generation=generation,
            expected_photo_ref=photo_ref,
        )

    async def read_photo(
        self,
        photo_ref: str,
        *,
        expected_mode: str | None = None,
    ) -> CompanionPagePhoto:
        reference = _text(
            photo_ref,
            48,
            code="memory_page_photo_ref_invalid",
            required=True,
        )
        if _PHOTO_REF_RE.fullmatch(reference) is None:
            _fail("memory_page_photo_ref_invalid")
        if expected_mode not in {None, "formal", "legacy"}:
            _fail("memory_page_photo_ref_invalid")
        resolved = self._resolve_api()
        surface = self._select_surface(resolved)
        if expected_mode is not None and surface != expected_mode:
            _fail("memory_page_photo_ref_stale")
        if surface == "formal":
            return await self._formal_photo(resolved, reference)
        adapter = self._legacy_for(resolved.api, create=False)
        if not reference.startswith(f"mphoto_{adapter.instance_generation[:12]}_"):
            _fail("memory_page_photo_ref_stale")
        try:
            raw = await adapter.read_photo(reference)
        except asyncio.CancelledError:
            raise
        except CompanionPageBridgeError as exc:
            try:
                self._same_legacy_generation(resolved, adapter)
            except (CompanionPageBridgeError, _GenerationChanged):
                self._retire_legacy()
                _fail("memory_page_photo_ref_stale")
            raise
        except Exception:
            try:
                self._same_api(resolved)
            except _GenerationChanged:
                self._retire_legacy()
                _fail("memory_page_photo_ref_stale")
            _fail("memory_page_photo_read_failed")
        try:
            self._same_legacy_generation(resolved, adapter)
            if self._select_surface(resolved) != "legacy":
                _fail("memory_page_photo_ref_stale")
        except _GenerationChanged:
            self._retire_legacy()
            _fail("memory_page_photo_ref_stale")
        except CompanionPageBridgeError as exc:
            if exc.code in {
                "memory_page_contract_downgrade",
                "memory_page_service_closed",
            }:
                self._retire_legacy()
                _fail("memory_page_photo_ref_stale")
            raise
        try:
            photo = validate_memory_page_photo(
                raw,
                expected_generation=adapter.instance_generation,
                expected_photo_ref=reference,
            )
            self._same_legacy_generation(resolved, adapter)
        except _GenerationChanged:
            self._retire_legacy()
            _fail("memory_page_photo_ref_stale")
        except CompanionPageBridgeError as exc:
            if exc.code == "memory_page_service_closed":
                self._retire_legacy()
                _fail("memory_page_photo_ref_stale")
            raise
        return CompanionPagePhoto(
            photo_ref=photo.photo_ref,
            mime_type=photo.mime_type,
            size=photo.size,
            sha256=photo.sha256,
            content_base64=photo.content_base64,
            content=photo.content,
            mode="legacy",
        )

    def read_p6_status(self) -> Any:
        resolved = self._resolve_api()
        try:
            self._select_surface(resolved)
        except CompanionPageBridgeError as exc:
            if exc.code == "memory_page_contract_downgrade":
                _fail("companion_p6_producer_stale")
            raise
        try:
            getter = getattr(resolved.api, "get_p6_readonly_status")
        except Exception:
            _fail("companion_p6_producer_unavailable")
        if not callable(getter):
            _fail("companion_p6_producer_unavailable")
        try:
            value = getter()
        except Exception:
            _fail("companion_p6_producer_unreadable")
        try:
            self._same_api(resolved)
        except _GenerationChanged:
            _fail("companion_p6_producer_stale")
        try:
            return copy.deepcopy(value)
        except Exception:
            _fail("companion_p6_producer_unreadable")


__all__ = [
    "COMPANION_MODULE_NAMES",
    "COMPANION_PLUGIN_ID",
    "CompanionPageBridge",
    "CompanionPageBridgeError",
    "CompanionPagePhoto",
    "CompanionPageSnapshot",
    "MEMORY_PAGE_API_FAMILY",
    "MEMORY_PAGE_API_VERSION",
    "MEMORY_PAGE_PHOTO_MAX_BYTES",
    "MEMORY_PAGE_PHOTO_VERSION",
    "MEMORY_PAGE_SNAPSHOT_VERSION",
    "MEMORY_PAGE_SUPPORTED_TASK_VERSIONS",
    "MEMORY_PLUGIN_ID",
    "seal_memory_page_snapshot",
    "snapshot_payload_sha256",
    "validate_memory_page_descriptor",
    "validate_memory_page_photo",
    "validate_memory_page_snapshot",
]
