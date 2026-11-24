from __future__ import annotations

"""Deterministic credential scrubber for memory storage and export boundaries."""

import re
from typing import Any, Mapping


REDACTED = "[REDACTED]"

_TOKEN_PREFIX = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{16,})\b"
)
_CHINESE_CREDENTIAL = re.compile(
    r"(?i)((?:密码|口令|暗号|验证码|令牌|pin|passcode|token|密钥|秘钥)\s*(?:是|为|[:：=]|is)\s*)([^；，。！？!?\r\n]{1,80})"
)
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
_SENSITIVE_QUICK_CHECK = re.compile(
    r"(?i)(?:gh[pousr]_|github_pat_|sk-|bearer\s|https?://|-----begin |"
    r"password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"authorization|client[_-]?secret|private[_-]?key|"
    r"密码|口令|暗号|验证码|令牌|pin|passcode|token|密钥|秘钥)"
)
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
_SENSITIVE_KEY_SUFFIXES = (
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


def _key_name(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _is_sensitive_key(value: Any) -> bool:
    if type(value) is str and value.islower() and "-" not in value and value == value.strip():
        name = value
    else:
        name = _key_name(value)
    if name in _SENSITIVE_KEYS:
        return True
    return name.endswith(_SENSITIVE_KEY_SUFFIXES)


def _replace_chinese_credential(match: re.Match[str]) -> str:
    return match.group(1) + REDACTED


def _replace_credential_assignment(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}{REDACTED}"


def redact_sensitive_text(value: Any) -> str:
    if type(value) is str:
        text = value
    elif not value:
        return ""
    else:
        text = str(value)
    if not text or len(text) < 3:
        return text
    if len(text) <= 32 and text.isascii() and text.isdigit():
        return text
    if _SENSITIVE_QUICK_CHECK.search(text) is None:
        return text
    text = _TOKEN_PREFIX.sub(REDACTED, text)
    text = _CHINESE_CREDENTIAL.sub(_replace_chinese_credential, text)
    text = _PRIVATE_KEY.sub(REDACTED, text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _URL_CREDENTIAL.sub(rf"\1{REDACTED}\3", text)
    return _CREDENTIAL_ASSIGNMENT.sub(_replace_credential_assignment, text)


def redact_sensitive_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        return REDACTED
    val_type = type(value)
    if val_type is str:
        return redact_sensitive_text(value)
    if value is None or val_type is int or val_type is float or val_type is bool:
        return value
    if val_type is dict:
        next_depth = depth + 1
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = raw_key if type(raw_key) is str else str(raw_key)
            if _is_sensitive_key(key):
                result[key] = REDACTED
            else:
                result[key] = redact_sensitive_value(raw_value, depth=next_depth)
        return result
    if val_type is list:
        next_depth = depth + 1
        return [redact_sensitive_value(item, depth=next_depth) for item in value]
    if val_type is tuple:
        next_depth = depth + 1
        return [redact_sensitive_value(item, depth=next_depth) for item in value]
    if isinstance(value, Mapping):
        next_depth = depth + 1
        result = {}
        for raw_key, raw_value in value.items():
            key = raw_key if type(raw_key) is str else str(raw_key)
            if _is_sensitive_key(key):
                result[key] = REDACTED
            else:
                result[key] = redact_sensitive_value(raw_value, depth=next_depth)
        return result
    if isinstance(value, (list, tuple)):
        next_depth = depth + 1
        return [redact_sensitive_value(item, depth=next_depth) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive_text(value)


__all__ = ["REDACTED", "redact_sensitive_text", "redact_sensitive_value"]
