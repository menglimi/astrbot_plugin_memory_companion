from __future__ import annotations

"""Deterministic credential scrubber for memory storage and export boundaries."""

import re
from typing import Any, Mapping


REDACTED = "[REDACTED]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]+ PRIVATE KEY-----.*?-----END [^-\r\n]+ PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"authorization|client[_-]?secret|private[_-]?key)\b(\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;\r\n]+)"
)
_URL_CREDENTIAL = re.compile(r"(?i)(https?://[^:/\s]+:)([^@/\s]+)(@)")
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "client_secret",
        "private_key",
        "credential",
        "credentials",
    }
)


def _key_name(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _is_sensitive_key(value: Any) -> bool:
    name = _key_name(value)
    if name in _SENSITIVE_KEYS:
        return True
    return name.endswith(
        (
            "_password",
            "_passwd",
            "_api_key",
            "_access_token",
            "_refresh_token",
            "_authorization",
            "_client_secret",
            "_private_key",
            "_credential",
            "_credentials",
        )
    )


def redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{16,})\b", REDACTED, text)
    text = re.sub(r"(?i)((?:密码|口令|暗号|验证码|令牌|pin|passcode|token|密钥|秘钥)\s*(?:是|为|[:：=]|is)\s*)([^；，。！？!?\r\n]{1,80})", lambda m:m[1]+REDACTED,text)
    text = _PRIVATE_KEY.sub(REDACTED, text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _URL_CREDENTIAL.sub(rf"\1{REDACTED}\3", text)
    return _CREDENTIAL_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        text,
    )


def redact_sensitive_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        return REDACTED
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _is_sensitive_key(key):
                result[key] = REDACTED
            else:
                result[key] = redact_sensitive_value(raw_value, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [redact_sensitive_value(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive_text(value)


__all__ = ["REDACTED", "redact_sensitive_text", "redact_sensitive_value"]
