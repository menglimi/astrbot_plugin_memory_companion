from __future__ import annotations

from typing import Any


class ConfigView:
    ALIASES = {}

    def __init__(self, raw: Any):
        self.raw = raw or {}

    def get(self, dotted: str, default: Any = None) -> Any:
        marker = object()
        value = self._get_exact(dotted, marker)
        if value is not marker:
            return value
        for alias in self.ALIASES.get(dotted, ()):
            value = self._get_exact(alias, marker)
            if value is not marker:
                return value
        return default

    def _get_exact(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if isinstance(cur, dict):
                if part not in cur:
                    return default
                cur = cur.get(part)
            else:
                getter = getattr(cur, "get", None)
                if callable(getter):
                    cur = getter(part, default)
                    if cur is default:
                        return default
                else:
                    return default
            if cur is None:
                return default
        return cur

    def bool(self, dotted: str, default: bool) -> bool:
        value = self.get(dotted, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "开", "开启"}
        return bool(value)

    def int(self, dotted: str, default: int) -> int:
        try:
            return int(self.get(dotted, default))
        except Exception:
            return default

    def float(self, dotted: str, default: float) -> float:
        try:
            return float(self.get(dotted, default))
        except Exception:
            return default
