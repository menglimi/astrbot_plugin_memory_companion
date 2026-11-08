"""The single source of truth for the wall-clock timezone this plugin reports.

AstrBot exposes one global ``timezone`` setting and reads it for its own
datetime prompt.  Hard-coding ``Asia/Shanghai`` here made the memory plugin
disagree with the host whenever the administrator chose another zone: timeline
rows are stored in UTC, but they were still *displayed and interpreted* as
Shanghai, so a summary could attribute a message to the wrong time of day and
even to the wrong date across midnight.

The host value is resolved through a provider the service binds at startup, so
this module stays import-safe (no host access at import time) and every caller
just asks :func:`local_tz` / :func:`timezone_name`.
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Fallback used before the host provider is bound and whenever the host value is
# missing or not a valid IANA name.  Kept equal to AstrBot's own default so the
# plugin behaves the same on a host that never touched the setting.
DEFAULT_TIMEZONE_NAME = "Asia/Shanghai"

_REFRESH_SECONDS = 30.0

_provider = None
_cached_name = DEFAULT_TIMEZONE_NAME
_cached_tz = ZoneInfo(DEFAULT_TIMEZONE_NAME)
_refreshed_at = 0.0


def bind_timezone_provider(provider) -> None:
    """Register the callable that returns the host timezone name (or "")."""
    global _provider
    _provider = provider
    refresh(force=True)


def refresh(*, force: bool = False) -> str:
    """Re-read the host timezone; returns the resolved IANA name.

    Cached for ``_REFRESH_SECONDS`` so the hot paths do not call the host on
    every message, while a settings change still takes effect without a plugin
    reload.
    """
    global _cached_name, _cached_tz, _refreshed_at
    now = time.monotonic()
    if not force and now - _refreshed_at < _REFRESH_SECONDS:
        return _cached_name
    _refreshed_at = now
    name = _host_name()
    if name == _cached_name:
        return _cached_name
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        # Keep the last usable zone instead of failing every time caller.
        return _cached_name
    _cached_name = name
    _cached_tz = zone
    return _cached_name


def timezone_name() -> str:
    refresh()
    return _cached_name


def local_tz() -> ZoneInfo:
    refresh()
    return _cached_tz


def local_now() -> datetime:
    return datetime.now(local_tz())


def _host_name() -> str:
    if _provider is None:
        return DEFAULT_TIMEZONE_NAME
    try:
        candidate = _provider()
    except Exception:
        return DEFAULT_TIMEZONE_NAME
    candidate = str(candidate or "").strip()
    return candidate or DEFAULT_TIMEZONE_NAME
