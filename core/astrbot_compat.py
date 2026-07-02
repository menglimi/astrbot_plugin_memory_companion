from __future__ import annotations

import logging
import re
from typing import Any

try:
    from astrbot.api import logger  # type: ignore
except Exception:  # pragma: no cover - useful for local syntax/unit checks
    logger = logging.getLogger("MemoryCompanion")

try:
    from astrbot.core.agent.message import TextPart
except Exception:  # pragma: no cover - old AstrBot or local checks
    TextPart = None  # type: ignore


def remove_marked_text(text: str, header: str, footer: str) -> str:
    if not text or header not in text or footer not in text:
        return text or ""
    result = text
    while header in result and footer in result:
        start = result.find(header)
        end = result.find(footer, start)
        if start < 0 or end < 0:
            break
        result = result[:start] + result[end + len(footer) :]
    return "\n\n".join(part.strip() for part in result.split("\n\n") if part.strip())


PRIVATE_COMPANION_MARKERS = (
    "<!-- private_companion_turn_fragments_start -->",
    "<!-- private_companion_state_v1 -->",
    "<!-- private_companion_group_context_v1 -->",
    "<!-- private_companion_self_timeline_v1 -->",
    "<!-- private_companion_recall_query_v1 -->",
    "<!-- private_companion_reply_image_anchor_v1 -->",
)

PRIVATE_COMPANION_PROACTIVE_BLOCK_HEADINGS = (
    "【主动消息回复上下文】",
    "【候选主动消息】",
    "【原主动消息】",
    "【最近私聊记录】",
    "【本轮主动来源】",
    "【内在约束】",
)


def private_companion_proactive_text_is_internal(text: Any) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return False
    compact = re.sub(r"\s+", "", raw).lower()
    lowered = raw.lower()
    if "主动承接占位" in raw and ("用户还没发来新消息" in raw or "bot主动" in compact):
        return True
    if "这不是用户消息" in raw and "private companion" in lowered and "主动消息" in raw:
        return True
    if "你是主动私聊发送前的价值复核模型" in raw:
        return True
    if "主动消息人格/世界观判定器" in raw:
        return True
    if "这是一次用户已授权的主动陪伴行为" in raw:
        return True
    if "PrivateCompanion captured send_message_to_user payload" in raw:
        return True
    if any(raw.strip().startswith(heading) for heading in PRIVATE_COMPANION_PROACTIVE_BLOCK_HEADINGS):
        return True
    if "send_message_to_user" in lowered and any(
        token in raw
        for token in (
            "主动消息",
            "主动陪伴",
            "主动私聊",
            "框架唤醒链",
            "必须使用",
            "工具调用",
            "用户已授权",
        )
    ):
        return True
    if "send_message_to_user" in lowered and any(
        token in lowered
        for token in (
            "captured",
            "tool result",
            "tool call",
            "message captured",
            "privatecompanion",
        )
    ):
        return True
    if (
        ("你现在要在同一段私聊会话里" in raw or "真正会发给对方的一条私聊消息" in raw)
        and "主动" in raw
        and any(token in raw for token in ("只输出", "不要解释", "send_message_to_user"))
    ):
        return True
    if ("[主动消息]" in raw or "【主动消息】" in raw) and sum(
        1 for marker in ("触发原因", "行为结果", "内部动机", "动作摘要", "候选主动消息") if marker in raw
    ) >= 2:
        return True
    if ("工具调用限制" in raw or "agent reached max steps" in lowered) and any(
        token in lowered for token in ("send_message_to_user", "发消息", "主动")
    ):
        return True
    return False


def _drop_private_companion_proactive_blocks(text: str) -> tuple[str, bool]:
    """Remove multi-line proactive framework blocks while preserving visible chat."""
    if not text:
        return "", False

    lines = text.replace("\r", "\n").splitlines()
    kept: list[str] = []
    changed = False
    dropping_block = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if dropping_block:
                changed = True
                dropping_block = False
                continue
            kept.append(line)
            continue

        if any(stripped.startswith(heading) for heading in PRIVATE_COMPANION_PROACTIVE_BLOCK_HEADINGS):
            changed = True
            dropping_block = True
            continue

        if dropping_block:
            changed = True
            continue

        kept.append(line)

    return "\n".join(kept), changed


def clean_private_companion_history_text(text: Any) -> tuple[str, bool, bool]:
    raw = str(text or "")
    if not raw:
        return "", False, False
    if private_companion_proactive_text_is_internal(raw):
        return "", True, True

    cleaned = raw
    cleaned = re.sub(r"\[\[TTSBLOCK:[^\]]*\]\]", "", cleaned)
    cleaned = re.sub(r"\[\[PCTTS:[^\]]*\]\]", "", cleaned)
    cleaned = re.sub(r"<timer\b[^>]*>.*?</timer>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<tts\b[^>]*>.*?</tts>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"【主动承接占位】[^\n]*(?:\n|$)", "", cleaned)
    cleaned = re.sub(
        r"<!--\s*private_companion_[^>]*(?:proactive|turn_fragments)[^>]*-->",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned, removed_block = _drop_private_companion_proactive_blocks(cleaned)

    kept_lines: list[str] = []
    removed_line = removed_block
    for line in cleaned.replace("\r", "\n").splitlines():
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue
        if private_companion_proactive_text_is_internal(stripped):
            removed_line = True
            continue
        lowered = stripped.lower()
        if "send_message_to_user" in lowered or "tool `send_message_to_user`" in lowered:
            removed_line = True
            continue
        if any(stripped.startswith(heading) for heading in PRIVATE_COMPANION_PROACTIVE_BLOCK_HEADINGS):
            removed_line = True
            continue
        if "主动消息专用模式下" in stripped and "Private Companion 工具" in stripped:
            removed_line = True
            continue
        kept_lines.append(line)

    cleaned = "\n".join(kept_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    changed = cleaned != raw or removed_line
    if changed and not cleaned:
        return "", True, True
    return cleaned, changed, False


def _plain_request_text(value: Any, *, depth: int = 0) -> str:
    if value is None or depth > 4:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(value, "content", None)
    if content is not None and content is not value:
        return _plain_request_text(content, depth=depth + 1)
    if isinstance(value, list):
        return "\n".join(_plain_request_text(item, depth=depth + 1) for item in value)
    if isinstance(value, tuple):
        return "\n".join(_plain_request_text(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "content", "value", "marker", "source", "metadata"):
            if key in value:
                parts.append(_plain_request_text(value.get(key), depth=depth + 1))
        return "\n".join(part for part in parts if part)
    return ""


def _is_temp_or_plugin_context(item: Any) -> bool:
    text = _plain_request_text(item)
    if "private_companion_" in text or any(marker in text for marker in PRIVATE_COMPANION_MARKERS):
        return True
    if not isinstance(item, dict):
        return False
    if bool(item.get("_no_save") or item.get("no_save") or item.get("temporary") or item.get("temp")):
        return True
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        source = str(metadata.get("source") or metadata.get("plugin") or metadata.get("source_plugin") or "")
        if source in {"private_companion", "astrbot_plugin_private_companion"}:
            return True
    source = str(item.get("source") or item.get("plugin") or item.get("source_plugin") or "")
    return source in {"private_companion", "astrbot_plugin_private_companion"}


def _sanitize_context_content(value: Any) -> tuple[Any, bool, bool]:
    if value is None:
        return value, False, False
    if isinstance(value, str):
        return clean_private_companion_history_text(value)
    if isinstance(value, list):
        cleaned_items: list[Any] = []
        changed = False
        for item in value:
            cleaned_item, item_changed, drop = _sanitize_context_content(item)
            changed = changed or item_changed or drop
            if not drop:
                cleaned_items.append(cleaned_item)
        return cleaned_items, changed, not cleaned_items and bool(value)
    if isinstance(value, tuple):
        cleaned_list, changed, drop = _sanitize_context_content(list(value))
        return tuple(cleaned_list), changed, drop
    if isinstance(value, dict):
        changed = False
        cleaned = dict(value)
        had_payload = any(key in cleaned for key in ("content", "text", "value"))
        for key in ("content", "text", "value"):
            if key not in cleaned:
                continue
            new_value, item_changed, drop = _sanitize_context_content(cleaned.get(key))
            changed = changed or item_changed
            if drop:
                cleaned.pop(key, None)
            else:
                cleaned[key] = new_value
        if not any(cleaned.get(key) not in (None, "", [], {}) for key in ("content", "text", "value")):
            if had_payload and changed:
                return cleaned, True, True
            text = _plain_request_text(cleaned)
            if text and private_companion_proactive_text_is_internal(text):
                return cleaned, True, True
        return cleaned, changed, False

    for attr in ("content", "text"):
        current = getattr(value, attr, None)
        if current is None:
            continue
        new_value, changed, drop = _sanitize_context_content(current)
        if drop:
            return value, True, True
        if changed:
            try:
                setattr(value, attr, new_value)
            except Exception:
                return value, False, False
            return value, True, False
    text = _plain_request_text(value)
    if text and private_companion_proactive_text_is_internal(text):
        return value, True, True
    return value, False, False


def sanitize_request_history(req: Any, *, clean_proactive_guidance: bool = True) -> dict[str, int]:
    if not clean_proactive_guidance:
        return {"before": 0, "after": 0, "removed": 0, "cleaned": 0}
    contexts = getattr(req, "contexts", None)
    if not isinstance(contexts, list):
        return {"before": 0, "after": 0, "removed": 0, "cleaned": 0}

    cleaned_contexts: list[Any] = []
    cleaned_count = 0
    removed = 0
    for item in contexts:
        cleaned_item, changed, drop = _sanitize_context_content(item)
        if drop:
            removed += 1
            continue
        if changed:
            cleaned_count += 1
        cleaned_contexts.append(cleaned_item)
    if removed or cleaned_count:
        req.contexts = cleaned_contexts
    return {
        "before": len(contexts),
        "after": len(cleaned_contexts),
        "removed": removed,
        "cleaned": cleaned_count,
    }


def remove_temp_text(req: Any, header: str, footer: str) -> int:
    removed = 0
    parts = getattr(req, "extra_user_content_parts", None)
    if isinstance(parts, list):
        kept = []
        for part in parts:
            text = getattr(part, "text", "")
            if isinstance(text, str) and header in text and footer in text:
                removed += 1
                continue
            kept.append(part)
        req.extra_user_content_parts = kept

    prompt = getattr(req, "prompt", None)
    if isinstance(prompt, str) and header in prompt and footer in prompt:
        cleaned = remove_marked_text(prompt, header, footer)
        if cleaned != prompt:
            req.prompt = cleaned
            removed += 1

    contexts = getattr(req, "contexts", None)
    if isinstance(contexts, list):
        kept = []
        for item in contexts:
            text = _plain_request_text(item)
            if isinstance(text, str) and header in text and footer in text:
                removed += 1
                continue
            kept.append(item)
        if len(kept) != len(contexts):
            req.contexts = kept
    return removed


def manage_request_contexts(
    req: Any,
    mode: str = "trim",
    keep_recent: int = 2,
    *,
    preserve_external_temp: bool = True,
) -> dict[str, int | str]:
    contexts = getattr(req, "contexts", None)
    if not isinstance(contexts, list):
        return {"mode": mode, "before": 0, "after": 0, "removed": 0, "preserved": 0}

    before = len(contexts)
    normalized_mode = mode if mode in {"keep", "trim", "clear"} else "trim"
    if normalized_mode == "keep":
        return {"mode": normalized_mode, "before": before, "after": before, "removed": 0, "preserved": 0}

    preserve_indices: set[int] = set()
    if preserve_external_temp:
        preserve_indices = {index for index, item in enumerate(contexts) if _is_temp_or_plugin_context(item)}

    if normalized_mode == "clear":
        kept_indices = preserve_indices
    else:
        keep = max(0, int(keep_recent or 0))
        ordinary_indices = [index for index in range(before) if index not in preserve_indices]
        kept_indices = set(ordinary_indices[-keep:] if keep else [])
        kept_indices.update(preserve_indices)
    req.contexts = [item for index, item in enumerate(contexts) if index in kept_indices]
    after = len(getattr(req, "contexts", []) or [])
    return {
        "mode": normalized_mode,
        "before": before,
        "after": after,
        "removed": max(0, before - after),
        "preserved": len(preserve_indices),
    }


def detect_private_companion_request(req: Any) -> dict[str, Any]:
    texts: list[str] = []
    for attr in ("system_prompt", "prompt"):
        value = getattr(req, attr, "")
        if isinstance(value, str) and value:
            texts.append(value)

    parts = getattr(req, "extra_user_content_parts", None)
    if isinstance(parts, list):
        texts.extend(_plain_request_text(part) for part in parts)

    contexts = getattr(req, "contexts", None)
    if isinstance(contexts, list):
        texts.extend(_plain_request_text(item) for item in contexts)

    fragments = getattr(req, "_private_companion_turn_prompt_fragments", None)
    if isinstance(fragments, list):
        texts.extend(_plain_request_text(item) for item in fragments)

    surface = "\n".join(text for text in texts if text)
    markers = [marker for marker in PRIVATE_COMPANION_MARKERS if marker in surface]
    return {
        "has_any": bool("private_companion_" in surface or markers or fragments),
        "has_state": "<!-- private_companion_state_v1 -->" in surface,
        "has_group_context": "<!-- private_companion_group_context_v1 -->" in surface,
        "has_self_timeline": "<!-- private_companion_self_timeline_v1 -->" in surface,
        "has_recall_query": "<!-- private_companion_recall_query_v1 -->" in surface,
        "has_turn_fragments": "<!-- private_companion_turn_fragments_start -->" in surface or isinstance(fragments, list),
        "markers": markers,
    }


def append_temp_text(req: Any, text: str) -> bool:
    if TextPart is None:
        return False
    if not hasattr(req, "extra_user_content_parts") or getattr(req, "extra_user_content_parts", None) is None:
        req.extra_user_content_parts = []
    part = TextPart(text=text)
    mark_as_temp = getattr(part, "mark_as_temp", None)
    if callable(mark_as_temp):
        part = mark_as_temp()
    req.extra_user_content_parts.append(part)
    return True
