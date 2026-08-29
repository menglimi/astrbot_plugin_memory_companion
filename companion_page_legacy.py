# -*- coding: utf-8 -*-
"""One-release, isolated N-1 Companion Page compatibility adapter.

This is the only Memory module allowed to unwrap the historical Companion
facade.  Its public results use the same bounded, path-free wire as the formal
producer; host objects and filesystem paths never leave this module.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import inspect
import os
import re
import secrets
import stat
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .companion_page_bridge import (
    COMPANION_MODULE_NAMES,
    COMPANION_PLUGIN_ID,
    CompanionPageBridgeError,
    MEMORY_PAGE_PHOTO_MAX_BYTES,
    MEMORY_PAGE_PHOTO_VERSION,
    MEMORY_PAGE_SNAPSHOT_VERSION,
    MEMORY_PLUGIN_ID,
    seal_memory_page_snapshot,
    validate_memory_page_snapshot,
)


_LEGACY_REQUIRED_API_METHODS = (
    "get_p6_readonly_status",
    "story_migration_capabilities",
    "export_story_migration_snapshot",
    "get_bot_identity",
)
_PHOTO_REF_RE = re.compile(r"^mphoto_([0-9a-f]{12})_([A-Za-z0-9_-]{22})$")
_SAFE_CODE_RE = re.compile(r"[^a-z0-9_]+")
_MAX_PHOTO_REFS = 256
_PHOTO_TTL_SECONDS = 900.0


@dataclass(frozen=True, slots=True)
class _LegacyPhoto:
    root: Path
    parts: tuple[str, ...]
    device: int
    inode: int
    size: int
    mtime_ns: int
    sha256: str
    mime_type: str
    expires_at: float


def _fail(code: str) -> None:
    raise CompanionPageBridgeError(code)


def _text(value: Any, maximum: int) -> str:
    if value is None:
        return ""
    text = "".join(
        " " if unicodedata.category(character) in {"Cs", "Cc"} else character
        for character in str(value)
    )
    text = " ".join(text.split())
    return text[:maximum]


def _date(value: Any) -> str:
    text = _text(value, 16)
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return ""


def _timestamp(value: Any) -> int:
    try:
        result = int(float(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
    return result if 0 <= result <= 10**10 else 0


def _date_from_timestamp(value: Any) -> str:
    stamp = _timestamp(value)
    if not stamp:
        return ""
    try:
        return datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai")).date().isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def _safe_code(value: Any, fallback: str = "") -> str:
    code = _SAFE_CODE_RE.sub("_", _text(value, 64).lower()).strip("_")
    if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
        return code
    return fallback


def _opaque_identifier(secret: bytes, value: str) -> str:
    digest = hmac.new(secret, value.encode("utf-8"), hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _string_list(value: Any, *, count: int, maximum: int) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        text = _text(item, maximum)
        if text and text not in rows:
            rows.append(text)
        if len(rows) >= count:
            break
    return rows


def _event_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _text(
                item.get("event")
                or item.get("content")
                or item.get("text")
                or item.get("topic")
                or item.get("why")
                or item.get("reason")
                or item.get("action"),
                180,
            )
        else:
            text = _text(item, 180)
        if text and text not in rows:
            rows.append(text)
        if len(rows) >= 5:
            break
    return rows


def _plan_item(value: Any, index: int | None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "index": index,
        "time": _text(raw.get("time"), 20),
        "activity": _text(raw.get("activity") or raw.get("title"), 180),
        "mood": _text(raw.get("mood"), 80),
        "message_seed": _text(raw.get("message_seed"), 220),
    }


def _plan(value: Any, *, source: str = "none") -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    normalized = [
        _plan_item(item, index)
        for index, item in enumerate(items[:18])
        if isinstance(item, dict)
    ]
    return {
        "date": _date(raw.get("date")),
        "source": source if source in {"live", "history", "none"} else "none",
        "items": normalized,
    }


def _history_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for sample in value:
        text = _text(sample, 260)
        if not text:
            continue
        parts = text.split(maxsplit=1)
        time_value = parts[0] if parts and ":" in parts[0] else ""
        activity = parts[1] if time_value and len(parts) > 1 else text
        rows.append(
            {
                "index": len(rows),
                "time": _text(time_value, 20),
                "activity": _text(activity, 180),
                "mood": "",
                "message_seed": "",
            }
        )
        if len(rows) >= 18:
            break
    return rows


def _plan_for_date(data: dict[str, Any], selected_date: str) -> dict[str, Any]:
    current = data.get("daily_plan")
    if isinstance(current, dict) and _date(current.get("date")) == selected_date:
        return _plan(current, source="live")
    history = data.get("daily_plan_history")
    if isinstance(history, list):
        for entry in reversed(history):
            if not isinstance(entry, dict) or _date(entry.get("date")) != selected_date:
                continue
            nested = entry.get("plan")
            if isinstance(nested, dict):
                candidate = dict(nested)
                candidate.setdefault("date", selected_date)
                return _plan(candidate, source="history")
            if isinstance(entry.get("items"), list):
                return _plan(entry, source="history")
            return {
                "date": selected_date,
                "source": "history",
                "items": _history_samples(entry.get("sample")),
            }
    return {"date": "", "source": "none", "items": []}


def _details_for_date(
    data: dict[str, Any],
    selected_date: str,
    secret: bytes,
) -> list[dict[str, Any]]:
    sources: list[Any] = []
    if _date(data.get("detail_enhanced_day")) == selected_date:
        sources.append(data.get("detail_enhanced_segments"))
    else:
        history = data.get("detail_enhanced_history")
        if isinstance(history, list):
            for entry in reversed(history[-512:]):
                if isinstance(entry, dict) and _date(entry.get("date")) == selected_date:
                    sources.append(entry.get("segments"))
                    break
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        if isinstance(source, dict):
            iterable = list(source.items())
        elif isinstance(source, list):
            iterable = [(str(index), item) for index, item in enumerate(source)]
        else:
            iterable = []
        for key, item in iterable:
            if not isinstance(item, dict):
                continue
            raw_key = _text(key, 80)
            opaque = _opaque_identifier(
                secret,
                f"{selected_date}:{raw_key}:{len(rows)}",
            )
            identifier = f"detail_{opaque}"
            if identifier in seen:
                continue
            seen.add(identifier)
            key_match = re.fullmatch(
                r"\d{4}-\d{2}-\d{2}:(\d{1,3}):(\d{1,2}:\d{2})",
                raw_key,
            )
            raw_index = item.get("index")
            index_value = (
                raw_index
                if type(raw_index) is int and 0 <= raw_index <= 17
                else None
            )
            if index_value is None and key_match is not None:
                parsed_index = int(key_match.group(1))
                index_value = parsed_index if parsed_index <= 17 else None
            raw_status = _safe_code(item.get("status"), "unknown")
            status_value = {
                "done": "ready",
                "complete": "ready",
                "completed": "ready",
                "pending": "planned",
                "generating": "planned",
                "failed": "degraded",
            }.get(raw_status, raw_status)
            if status_value not in {
                "planned",
                "ready",
                "observed",
                "degraded",
                "story_plan",
                "unknown",
            }:
                status_value = "unknown"
            time_value = _text(item.get("time") or item.get("start_time"), 20)
            if not time_value and key_match is not None:
                time_value = key_match.group(2)
            rows.append(
                {
                    "id": identifier,
                    "index": index_value,
                    "status": status_value,
                    "time": time_value,
                    "summary": _text(item.get("summary"), 180),
                    "today_events": _event_list(item.get("today_events")),
                    "proactive_events": _event_list(item.get("proactive_events")),
                    "state_variables": _event_list(item.get("state_variables")),
                }
            )
            if len(rows) >= 18:
                return rows

    story = data.get("daily_story_plan")
    if not isinstance(story, dict) or _date(story.get("date")) != selected_date:
        story = None
        story_history = data.get("daily_story_plan_history")
        if isinstance(story_history, list):
            for entry in reversed(story_history):
                if isinstance(entry, dict) and _date(entry.get("date")) == selected_date:
                    story = entry
                    break
    if isinstance(story, dict) and len(rows) < 18:
        grouped: dict[str, dict[str, list[str]]] = {}
        for field in ("today_events", "proactive_events"):
            events = story.get(field) if isinstance(story.get(field), list) else []
            for item in events:
                if not isinstance(item, dict):
                    continue
                window = _text(
                    item.get("window") or item.get("time") or item.get("range"),
                    20,
                )
                bucket = grouped.setdefault(
                    window or "story",
                    {"today_events": [], "proactive_events": []},
                )
                text = _text(
                    item.get("event")
                    or item.get("content")
                    or item.get("text")
                    or item.get("topic")
                    or item.get("why")
                    or item.get("reason")
                    or item.get("action"),
                    180,
                )
                if text and text not in bucket[field] and len(bucket[field]) < 5:
                    bucket[field].append(text)
        for window, bucket in grouped.items():
            opaque = _opaque_identifier(secret, f"story:{selected_date}:{window}")
            rows.append(
                {
                    "id": f"detail_{opaque}",
                    "index": None,
                    "status": "story_plan",
                    "time": window,
                    "summary": (bucket["today_events"] or bucket["proactive_events"] or [""])[0],
                    "today_events": bucket["today_events"],
                    "proactive_events": bucket["proactive_events"],
                    "state_variables": [],
                }
            )
            if len(rows) >= 18:
                break
    return rows[:18]


def _diaries_for_date(data: dict[str, Any], selected_date: str) -> list[dict[str, Any]]:
    values = data.get("bot_diaries")
    if not isinstance(values, list):
        return []
    rows: list[dict[str, Any]] = []
    for diary in reversed(values):
        if not isinstance(diary, dict) or _date(diary.get("date")) != selected_date:
            continue
        story = diary.get("story_plan") if isinstance(diary.get("story_plan"), dict) else {}
        rows.append(
            {
                "date": selected_date,
                "summary": _text(diary.get("summary"), 220),
                "body": _text(diary.get("body"), 520),
                "share_seed": _text(diary.get("share_seed"), 180),
                "tags": _string_list(diary.get("tags"), count=8, maximum=40),
                "today_events": _event_list(
                    diary.get("today_events") or story.get("today_events")
                ),
                "proactive_events": _event_list(
                    diary.get("proactive_events") or story.get("proactive_events")
                ),
                "long_term_events": _event_list(
                    diary.get("long_term_events") or story.get("long_term_events")
                ),
            }
        )
        if len(rows) >= 4:
            break
    return rows


def _available_dates(data: dict[str, Any]) -> list[str]:
    rows: set[str] = set()

    def add(value: Any) -> None:
        normalized = _date(value)
        if normalized:
            rows.add(normalized)

    current = data.get("daily_plan")
    if isinstance(current, dict):
        add(current.get("date"))
    for field in (
        "daily_plan_history",
        "detail_enhanced_history",
        "daily_story_plan_history",
        "bot_diaries",
    ):
        values = data.get(field)
        if isinstance(values, list):
            for item in values[-512:]:
                if isinstance(item, dict):
                    add(item.get("date"))
    add(data.get("detail_enhanced_day"))
    add(data.get("state_generated_day"))
    story = data.get("daily_story_plan")
    if isinstance(story, dict):
        add(story.get("date"))
    state = data.get("daily_state")
    if isinstance(state, dict):
        add(state.get("date"))
    outfit = data.get("daily_outfit_photo")
    if isinstance(outfit, dict):
        add(outfit.get("date") or _date_from_timestamp(outfit.get("generated_at")))
    outfit_history = data.get("daily_outfit_history")
    if isinstance(outfit_history, list):
        for item in outfit_history[-512:]:
            if isinstance(item, dict):
                add(item.get("date") or _date_from_timestamp(item.get("generated_at")))
    recent = data.get("recent_photo_generations")
    if isinstance(recent, list):
        for item in recent[:256]:
            if isinstance(item, dict):
                add(item.get("date") or _date_from_timestamp(item.get("generated_at") or item.get("ts")))
    return sorted(rows, reverse=True)[:180]


def _bounded_data_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    """Detach only the N-1 fields consumed by this adapter, with history caps."""

    result: dict[str, Any] = {}
    for field in (
        "daily_plan",
        "daily_state",
        "daily_story_plan",
        "daily_outfit_photo",
    ):
        value = data.get(field)
        if isinstance(value, dict):
            result[field] = copy.deepcopy(value)
    segments = data.get("detail_enhanced_segments")
    if isinstance(segments, dict):
        bounded_segments: dict[Any, Any] = {}
        for index, (key, value) in enumerate(segments.items()):
            if index >= 64:
                break
            bounded_segments[key] = value
        result["detail_enhanced_segments"] = copy.deepcopy(bounded_segments)
    for field in ("detail_enhanced_day", "state_generated_day"):
        value = data.get(field)
        if isinstance(value, str):
            result[field] = value
    for field, limit, newest_at_end in (
        ("daily_plan_history", 512, True),
        ("detail_enhanced_history", 512, True),
        ("daily_story_plan_history", 512, True),
        ("bot_diaries", 512, True),
        ("daily_outfit_history", 512, True),
        ("recent_photo_generations", 256, False),
    ):
        value = data.get(field)
        if not isinstance(value, list):
            continue
        bounded = value[-limit:] if newest_at_end else value[:limit]
        result[field] = copy.deepcopy(bounded)
    return result


class LegacyCompanionPageAdapter:
    """Project one exact known N-1 facade into the formal wire."""

    def __init__(self, api: Any) -> None:
        if not self.matches(api):
            _fail("memory_page_legacy_unsupported")
        self._api = api
        self._plugin = api._plugin
        self._data_lock = self._plugin._data_lock
        self._current_item_getter_static = inspect.getattr_static(
            self._plugin,
            "_get_current_plan_item",
        )
        self._host_generation = api._story_migration_generation
        self.instance_generation = secrets.token_hex(16)
        self._secret = secrets.token_bytes(32)
        self._lock = threading.RLock()
        self._closed = False
        self._photos: OrderedDict[str, _LegacyPhoto] = OrderedDict()

    @classmethod
    def matches(cls, api: Any) -> bool:
        try:
            if (
                api is None
                or api.__class__.__name__ != "PrivateCompanionExtensionAPI"
                or api.__class__.__module__ not in COMPANION_MODULE_NAMES
            ):
                return False
            missing = object()
            if any(
                inspect.getattr_static(api, name, missing) is not missing
                for name in (
                    "memory_page_capabilities",
                    "export_memory_page_snapshot",
                    "read_memory_page_photo",
                )
            ):
                return False
            methods = {
                name: getattr(api, name, None)
                for name in _LEGACY_REQUIRED_API_METHODS
            }
            if any(not callable(method) for method in methods.values()):
                return False
            if any(
                inspect.signature(methods[name]).parameters
                for name in (
                    "get_p6_readonly_status",
                    "story_migration_capabilities",
                    "get_bot_identity",
                )
            ):
                return False
            export_method = methods["export_story_migration_snapshot"]
            export_parameters = list(inspect.signature(export_method).parameters.values())
            if (
                inspect.iscoroutinefunction(export_method) is not True
                or len(export_parameters) != 1
                or export_parameters[0].name != "lease_token"
                or export_parameters[0].kind is not inspect.Parameter.KEYWORD_ONLY
                or export_parameters[0].default != ""
            ):
                return False
            if any(
                inspect.iscoroutinefunction(methods[name])
                for name in (
                    "get_p6_readonly_status",
                    "story_migration_capabilities",
                    "get_bot_identity",
                )
            ):
                return False
            generation = getattr(api, "_story_migration_generation", None)
            lifecycle = getattr(api, "_story_migration_state", None)
            if (
                not isinstance(generation, str)
                or re.fullmatch(r"[0-9a-f]{32}", generation) is None
                or lifecycle != "ready"
            ):
                return False
            plugin = getattr(api, "_plugin", None)
            data_lock = getattr(plugin, "_data_lock", None)
            identity = getattr(plugin, "plugin_identity", None)
            current_item_getter = getattr(plugin, "_get_current_plan_item", None)
            current_parameters = (
                list(inspect.signature(current_item_getter).parameters.values())
                if callable(current_item_getter)
                else []
            )
            return bool(
                plugin is not None
                and plugin.__class__.__name__ == "PrivateCompanionPlugin"
                and plugin.__class__.__module__ in COMPANION_MODULE_NAMES
                and type(identity) is dict
                and identity.get("plugin_id") == COMPANION_PLUGIN_ID
                and identity.get("version") == "6.4.1"
                and type(getattr(plugin, "data", None)) is dict
                and data_lock is not None
                and hasattr(data_lock, "__aenter__")
                and hasattr(data_lock, "__aexit__")
                and callable(current_item_getter)
                and not inspect.iscoroutinefunction(current_item_getter)
                and len(current_parameters) == 1
                and current_parameters[0].name == "plan"
                and current_parameters[0].kind
                is inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
        except Exception:
            return False

    def _live_plugin(self) -> Any:
        with self._lock:
            if self._closed:
                _fail("memory_page_service_closed")
        identity = getattr(self._plugin, "plugin_identity", None)
        if (
            getattr(self._api, "_plugin", None) is not self._plugin
            or getattr(self._plugin, "_data_lock", None) is not self._data_lock
            or inspect.getattr_static(
                self._plugin,
                "_get_current_plan_item",
                None,
            )
            is not self._current_item_getter_static
            or type(identity) is not dict
            or identity.get("plugin_id") != COMPANION_PLUGIN_ID
            or identity.get("version") != "6.4.1"
            or getattr(self._api, "_story_migration_generation", None)
            != self._host_generation
            or getattr(self._api, "_story_migration_state", None) != "ready"
        ):
            _fail("memory_page_service_closed")
        return self._plugin

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._photos.clear()

    def assert_live(self) -> None:
        self._live_plugin()

    def _coordination(self, plugin: Any) -> dict[str, Any]:
        getter = getattr(plugin, "_memory_companion_coordination_status", None)
        if not callable(getter):
            return {
                "available": False,
                "state": "unavailable",
                "reason_code": "legacy_bridge_status_unavailable",
            }
        try:
            value = getter()
        except Exception:
            return {
                "available": False,
                "state": "degraded",
                "reason_code": "legacy_bridge_status_unreadable",
            }
        raw = value if isinstance(value, dict) else {}
        state_value = _safe_code(raw.get("state"), "degraded")
        if state_value not in {
            "ready",
            "degraded",
            "local_only",
            "disabled",
            "inactive",
            "unavailable",
        }:
            state_value = "degraded"
        available = bool(
            raw.get("available")
            and state_value not in {"degraded", "local_only", "disabled", "inactive", "unavailable"}
            and not raw.get("degraded")
        )
        reason = _safe_code(
            raw.get("reason") or raw.get("error_code"),
            "" if available else "legacy_bridge_degraded",
        )
        return {"available": available, "state": state_value, "reason_code": reason}

    def _roots(self, plugin: Any) -> tuple[Path, ...]:
        candidates = [
            getattr(plugin, "data_dir", None),
            getattr(plugin, "plugin_data_dir", None),
        ]
        data_file = getattr(plugin, "data_file", None)
        if data_file:
            candidates.append(Path(str(data_file)).parent)
        roots: list[Path] = []
        for candidate in candidates:
            if not candidate:
                continue
            try:
                source = Path(str(candidate)).expanduser()
                source_state = source.lstat()
                if stat.S_ISLNK(source_state.st_mode) or not stat.S_ISDIR(source_state.st_mode):
                    continue
                resolved = source.resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved not in roots:
                roots.append(resolved)
        return tuple(roots)

    @staticmethod
    def _mime(content: bytes) -> str:
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

    @staticmethod
    def _open_nofollow(root: Path, parts: tuple[str, ...], *, changed: bool) -> int:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if nofollow is None or directory is None or not parts:
            _fail("memory_page_photo_changed" if changed else "memory_page_photo_unavailable")
        cloexec = getattr(os, "O_CLOEXEC", 0)
        nonblock = getattr(os, "O_NONBLOCK", 0)
        directory_flags = os.O_RDONLY | directory | nofollow | cloexec
        file_flags = os.O_RDONLY | nofollow | cloexec | nonblock
        opened_directory = -1
        try:
            opened_directory = os.open(os.fspath(root), directory_flags)
            for part in parts[:-1]:
                next_directory = os.open(part, directory_flags, dir_fd=opened_directory)
                os.close(opened_directory)
                opened_directory = next_directory
            return os.open(parts[-1], file_flags, dir_fd=opened_directory)
        except OSError:
            _fail("memory_page_photo_changed" if changed else "memory_page_photo_unavailable")
        finally:
            if opened_directory >= 0:
                try:
                    os.close(opened_directory)
                except OSError:
                    pass

    @classmethod
    def _read_descriptor(
        cls,
        root: Path,
        parts: tuple[str, ...],
        *,
        expected: _LegacyPhoto | None = None,
    ) -> tuple[bytes, os.stat_result]:
        descriptor = cls._open_nofollow(root, parts, changed=expected is not None)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
                _fail(
                    "memory_page_photo_changed"
                    if expected is not None
                    else "memory_page_photo_unavailable"
                )
            if before.st_size > MEMORY_PAGE_PHOTO_MAX_BYTES:
                _fail("memory_page_photo_too_large")
            if expected is not None and (
                before.st_dev != expected.device
                or before.st_ino != expected.inode
                or before.st_size != expected.size
                or before.st_mtime_ns != expected.mtime_ns
            ):
                _fail("memory_page_photo_changed")
            payload = bytearray()
            while len(payload) <= MEMORY_PAGE_PHOTO_MAX_BYTES:
                block = os.read(
                    descriptor,
                    min(1024 * 1024, MEMORY_PAGE_PHOTO_MAX_BYTES + 1 - len(payload)),
                )
                if not block:
                    break
                payload.extend(block)
            after = os.fstat(descriptor)
            if len(payload) > MEMORY_PAGE_PHOTO_MAX_BYTES:
                _fail("memory_page_photo_too_large")
            if (
                len(payload) != after.st_size
                or after.st_dev != before.st_dev
                or after.st_ino != before.st_ino
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
            ):
                _fail("memory_page_photo_changed")
            return bytes(payload), before
        except CompanionPageBridgeError:
            raise
        except OSError:
            _fail(
                "memory_page_photo_changed"
                if expected is not None
                else "memory_page_photo_unavailable"
            )
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def _safe_candidate(
        self,
        raw_path: Any,
        plugin: Any,
    ) -> tuple[Path, tuple[str, ...]]:
        if not isinstance(raw_path, (str, os.PathLike)):
            _fail("memory_page_photo_unavailable")
        try:
            text = os.fspath(raw_path)
        except TypeError:
            _fail("memory_page_photo_unavailable")
        if not isinstance(text, str) or not text or "\x00" in text:
            _fail("memory_page_photo_unavailable")
        raw_parts = [text]
        for separator in tuple(item for item in (os.sep, os.altsep) if item):
            raw_parts = [piece for part in raw_parts for piece in part.split(separator)]
        if any(part in {".", ".."} for part in raw_parts):
            _fail("memory_page_photo_unavailable")
        source = Path(text).expanduser()
        roots = self._roots(plugin)
        if not roots:
            _fail("memory_page_photo_unavailable")
        for root in roots:
            try:
                candidate = Path(
                    os.path.abspath(source if source.is_absolute() else root / source)
                )
                relative = candidate.relative_to(root)
            except (OSError, ValueError):
                continue
            parts = relative.parts
            try:
                invalid_parts = not parts or len(parts) > 32 or any(
                    not part
                    or part in {".", ".."}
                    or len(part.encode("utf-8")) > 255
                    for part in parts
                )
            except UnicodeEncodeError:
                invalid_parts = True
            if invalid_parts:
                continue
            current = root
            safe = True
            try:
                for part in parts:
                    current = current / part
                    value = current.lstat()
                    if stat.S_ISLNK(value.st_mode):
                        safe = False
                        break
            except (OSError, RuntimeError, ValueError):
                continue
            if safe:
                return root, tuple(parts)
        _fail("memory_page_photo_unavailable")

    def _stage_photo_sync(self, raw_path: Any) -> tuple[str, _LegacyPhoto]:
        plugin = self._live_plugin()
        root, parts = self._safe_candidate(raw_path, plugin)
        content, identity = self._read_descriptor(root, parts)
        mime_type = self._mime(content)
        digest = hashlib.sha256(content).hexdigest()
        material = (
            f"{self.instance_generation}:{identity.st_dev}:{identity.st_ino}:"
            f"{identity.st_size}:"
            f"{identity.st_mtime_ns}:{digest}"
        ).encode("ascii")
        token = base64.urlsafe_b64encode(
            hmac.new(self._secret, material, hashlib.sha256).digest()[:16]
        ).decode("ascii").rstrip("=")
        photo_ref = f"mphoto_{self.instance_generation[:12]}_{token}"
        record = _LegacyPhoto(
            root=root,
            parts=parts,
            device=identity.st_dev,
            inode=identity.st_ino,
            size=identity.st_size,
            mtime_ns=identity.st_mtime_ns,
            sha256=digest,
            mime_type=mime_type,
            expires_at=0.0,
        )
        return photo_ref, record

    def _commit_photo_refs(self, staged: list[tuple[str, _LegacyPhoto]]) -> None:
        now = time.monotonic()
        self._live_plugin()
        with self._lock:
            previous = self._photos.copy()
            try:
                self._live_plugin()
                for reference, record in staged:
                    self._photos[reference] = _LegacyPhoto(
                        root=record.root,
                        parts=record.parts,
                        device=record.device,
                        inode=record.inode,
                        size=record.size,
                        mtime_ns=record.mtime_ns,
                        sha256=record.sha256,
                        mime_type=record.mime_type,
                        expires_at=now + _PHOTO_TTL_SECONDS,
                    )
                    self._photos.move_to_end(reference)
                while len(self._photos) > _MAX_PHOTO_REFS:
                    self._photos.popitem(last=False)
                self._live_plugin()
            except BaseException:
                self._photos.clear()
                self._photos.update(previous)
                raise

    async def _thread_call(
        self,
        callback: Any,
        *args: Any,
    ) -> Any:
        worker = asyncio.create_task(asyncio.to_thread(callback, *args))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError as cancellation:
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise cancellation

    async def _photos_for_date(
        self,
        data: dict[str, Any],
        selected_date: str,
    ) -> tuple[list[dict[str, Any]], list[tuple[str, _LegacyPhoto]]]:
        sources: list[tuple[dict[str, Any], str]] = []
        outfit = data.get("daily_outfit_photo")
        if isinstance(outfit, dict):
            sources.append((outfit, "daily_outfit"))
        outfit_history = data.get("daily_outfit_history")
        if isinstance(outfit_history, list):
            sources.extend(
                (item, "daily_outfit")
                for item in reversed(outfit_history[-128:])
                if isinstance(item, dict)
            )
        recent = data.get("recent_photo_generations")
        if isinstance(recent, list):
            sources.extend(
                (item, "recent_photo")
                for item in recent[:256]
                if isinstance(item, dict)
            )

        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for index, (item, default_kind) in enumerate(sources):
            item_date = _date(item.get("date")) or _date_from_timestamp(
                item.get("generated_at") or item.get("ts")
            )
            if item_date != selected_date:
                continue
            raw_path = item.get("path")
            path_identity = (
                os.fspath(raw_path)
                if isinstance(raw_path, (str, os.PathLike))
                else ""
            )
            raw_kind = _text(item.get("kind"), 40).lower()
            kind = (
                "life_photo"
                if default_kind == "recent_photo" and "life" in raw_kind
                else default_kind
            )
            identity_key = (kind, item_date, path_identity)
            if identity_key in seen:
                continue
            seen.add(identity_key)
            opaque = _opaque_identifier(
                self._secret,
                (
                    f"photo|{self.instance_generation}|{item_date}|{kind}|"
                    f"{index}|{path_identity}"
                ),
            )
            candidates.append(
                {
                    "id": f"photo_{opaque}",
                    "date": item_date,
                    "kind": kind,
                    "generated_at": _timestamp(
                        item.get("generated_at") or item.get("ts")
                    ),
                    "raw_path": raw_path,
                }
            )
        candidates.sort(key=lambda item: item["generated_at"], reverse=True)

        rows: list[dict[str, Any]] = []
        staged: list[tuple[str, _LegacyPhoto]] = []
        for candidate in candidates[:8]:
            photo_ref = ""
            available = False
            error_code = "memory_page_photo_unavailable"
            raw_path = candidate["raw_path"]
            if raw_path:
                try:
                    photo_ref, record = await self._thread_call(
                        self._stage_photo_sync,
                        raw_path,
                    )
                    staged.append((photo_ref, record))
                    available = True
                    error_code = ""
                except asyncio.CancelledError:
                    raise
                except CompanionPageBridgeError as exc:
                    error_code = exc.code
            rows.append(
                {
                    "id": candidate["id"],
                    "date": candidate["date"],
                    "kind": candidate["kind"],
                    "generated_at": candidate["generated_at"],
                    "available": available,
                    "error_code": error_code,
                    "photo_ref": photo_ref,
                }
            )
        return rows, staged

    async def export_snapshot(self, selected_date: str = "") -> dict[str, Any]:
        plugin = self._live_plugin()
        data_lock = self._data_lock
        if (
            data_lock is None
            or not hasattr(data_lock, "__aenter__")
            or not hasattr(data_lock, "__aexit__")
        ):
            _fail("memory_page_snapshot_state_unavailable")
        try:
            async with data_lock:
                self._live_plugin()
                data = _bounded_data_snapshot(plugin.data)
                daily_plan_enabled = getattr(plugin, "enable_daily_plan", None) is True
                detail_enhancement_enabled = (
                    getattr(plugin, "enable_detail_enhancement", None) is True
                )
                bot_name = _text(getattr(plugin, "bot_name", ""), 80)
                current_item_getter = getattr(plugin, "_get_current_plan_item", None)
                dates = _available_dates(data)
                selected = selected_date or (dates[0] if dates else "")
                plan = _plan_for_date(data, selected) if selected else {
                    "date": "",
                    "source": "none",
                    "items": [],
                }
                current_item = _plan_item({}, None)
                current_plan = data.get("daily_plan")
                if (
                    selected
                    and isinstance(current_plan, dict)
                    and _date(current_plan.get("date")) == selected
                    and callable(current_item_getter)
                ):
                    try:
                        candidate = current_item_getter(current_plan)
                    except Exception:
                        candidate = None
                    if isinstance(candidate, dict):
                        current_index = None
                        items = current_plan.get("items")
                        if isinstance(items, list):
                            for candidate_index, item in enumerate(items[:18]):
                                if item is candidate or item == candidate:
                                    current_index = candidate_index
                                    break
                        current_item = _plan_item(candidate, current_index)
                self._live_plugin()
        except asyncio.CancelledError:
            raise
        except CompanionPageBridgeError:
            raise
        except Exception:
            _fail("memory_page_snapshot_state_unavailable")
        self._live_plugin()
        coordination = self._coordination(plugin)
        self._live_plugin()
        daily = data.get("daily_state")
        state_date = (
            _date(daily.get("date")) or _date(data.get("state_generated_day"))
            if isinstance(daily, dict)
            else ""
        )
        if not selected or not isinstance(daily, dict) or state_date != selected:
            daily = {}
            state_date = ""
        try:
            energy = int(daily.get("energy")) if daily.get("energy") is not None else None
        except (TypeError, ValueError):
            energy = None
        if energy is not None and not 0 <= energy <= 100:
            energy = None
        photos, staged_photo_refs = await self._photos_for_date(data, selected)
        self._live_plugin()
        payload = {
            "version": MEMORY_PAGE_SNAPSHOT_VERSION,
            "source_plugin_id": COMPANION_PLUGIN_ID,
            "instance_generation": self.instance_generation,
            "selected_date": selected,
            "available_dates": dates,
            "features": {
                "daily_plan_enabled": daily_plan_enabled,
                "detail_enhancement_enabled": detail_enhancement_enabled,
            },
            "coordination": coordination,
            "day": {
                "date": selected,
                "bot_name": bot_name,
                "plan": plan,
                "current_item": current_item,
                "daily_state": {
                    "date": state_date,
                    "energy": energy,
                    "mood_bias": _text(daily.get("mood_bias") or daily.get("mood"), 80),
                    "sleep": _text(daily.get("sleep"), 80),
                    "weather": _text(daily.get("weather"), 80),
                    "note": _text(daily.get("note") or daily.get("summary"), 180),
                },
                "details": _details_for_date(data, selected, self._secret),
                "photos": photos,
                "diaries": _diaries_for_date(data, selected),
            },
        }
        sealed = seal_memory_page_snapshot(payload)
        validated = validate_memory_page_snapshot(
            sealed,
            expected_generation=self.instance_generation,
            expected_selected_date=selected_date,
        )
        self._live_plugin()
        self._commit_photo_refs(staged_photo_refs)
        return validated

    def _read_photo_sync(self, photo_ref: str, record: _LegacyPhoto) -> bytes:
        if time.monotonic() >= record.expires_at:
            _fail("memory_page_photo_ref_expired")
        content, identity = self._read_descriptor(
            record.root,
            record.parts,
            expected=record,
        )
        if (
            identity.st_dev != record.device
            or identity.st_ino != record.inode
            or identity.st_size != record.size
            or identity.st_mtime_ns != record.mtime_ns
            or hashlib.sha256(content).hexdigest() != record.sha256
            or self._mime(content) != record.mime_type
        ):
            _fail("memory_page_photo_changed")
        return content

    async def read_photo(self, photo_ref: str) -> dict[str, Any]:
        match = _PHOTO_REF_RE.fullmatch(photo_ref)
        if match is None:
            _fail("memory_page_photo_ref_invalid")
        if match.group(1) != self.instance_generation[:12]:
            _fail("memory_page_photo_ref_stale")
        self._live_plugin()
        with self._lock:
            record = self._photos.get(photo_ref)
            if record is None:
                _fail("memory_page_photo_ref_expired")
            if time.monotonic() >= record.expires_at:
                self._photos.pop(photo_ref, None)
                _fail("memory_page_photo_ref_expired")
            self._photos.move_to_end(photo_ref)
        content = await self._thread_call(self._read_photo_sync, photo_ref, record)
        self._live_plugin()
        now = time.monotonic()
        with self._lock:
            current = self._photos.get(photo_ref)
            if current is not record:
                _fail("memory_page_photo_ref_expired")
            if record.expires_at <= now:
                self._photos.pop(photo_ref, None)
                _fail("memory_page_photo_ref_expired")
        return {
            "version": MEMORY_PAGE_PHOTO_VERSION,
            "source_plugin_id": COMPANION_PLUGIN_ID,
            "instance_generation": self.instance_generation,
            "photo_ref": photo_ref,
            "mime_type": record.mime_type,
            "size": len(content),
            "sha256": record.sha256,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }


__all__ = ["LegacyCompanionPageAdapter"]
