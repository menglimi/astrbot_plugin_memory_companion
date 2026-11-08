from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

try:
    from astrbot.api import logger  # type: ignore
except Exception:  # pragma: no cover - useful for local syntax/unit checks
    logger = logging.getLogger("MemoryCompanion")


# TextPart 统一在这里解析，插件其它模块只从本模块取（A14）。
# 4.29.3 的公共面 astrbot/api/message_components.py 目前只 re-export
# core.message.components，TextPart 仍定义在 astrbot.core.agent.message 里，所以
# 实际会走到回退分支；等上游把 TextPart 导出到公共面后，这里自动切过去，
# 调用方不用跟着改。解析逻辑抽成 _resolve_text_part() 以便单独断言回退顺序。
def _resolve_text_part() -> Any:
    """解析 TextPart：公共面优先，失败再退内部模块，都失败返回 None。"""

    try:
        from astrbot.api.message_components import TextPart as public_text_part
    except ImportError:  # pragma: no cover - 4.29.3 公共面尚未导出 TextPart
        public_text_part = None
    if public_text_part is not None:
        return public_text_part
    try:
        from astrbot.core.agent.message import TextPart as internal_text_part
    except ImportError:  # pragma: no cover - old AstrBot or local checks
        return None
    return internal_text_part


TextPart = _resolve_text_part()


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
    "<!-- private_companion_static_v1 -->",
    "<!-- private_companion_reply_style_v1 -->",
    "<!-- private_companion_environment_v1 -->",
    "<!-- private_companion_group_context_v1 -->",
    "<!-- private_companion_self_timeline_v1 -->",
    "<!-- private_companion_recall_query_v1 -->",
    "<!-- private_companion_reply_image_anchor_v1 -->",
    "<!-- private_companion_reply_chain_v1 -->",
    "<!-- private_companion_forward_message_v1 -->",
    "<!-- private_companion_group_injection_guard_v1 -->",
    "<!-- private_companion_relation_lookup_v1 -->",
    "<!-- private_companion_atrelay_tools_v1 -->",
    "<!-- private_companion_qzone_tools_v1 -->",
    "<!-- private_companion_photo_generation_tool_v1 -->",
    "<!-- private_companion_cross_user_memory_v1 -->",
    "<!-- private_companion_group_persona_denoise_v1 -->",
    "<!-- private_companion_group_high_intensity_reply_guard_v1 -->",
    "<!-- private_companion_rest_backlog_v1 -->",
    "<!-- private_companion_atrelay_target_summary_v1 -->",
    "<!-- private_companion_worldbook_mentions_v1 -->",
    "<!-- private_companion_non_target_private_guard_v1 -->",
    "<!-- private_companion_capability_boundary_v1 -->",
)

_PRIVATE_COMPANION_BLOCK_RE = re.compile(
    r"\n*\s*<!--\s*private_companion_[a-z0-9_]+_v1\s*-->.*?"
    r"(?=\n\s*<!--\s*private_companion_[a-z0-9_]+_v1\s*-->|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_PRIVATE_COMPANION_TURN_FRAGMENT_RE = re.compile(
    r"\n*\s*<!--\s*private_companion_turn_fragments_start\s*-->.*?"
    r"<!--\s*private_companion_turn_fragments_end\s*-->\s*",
    re.IGNORECASE | re.DOTALL,
)

PRIVATE_COMPANION_PROACTIVE_BLOCK_HEADINGS = (
    "【主动消息回复上下文】",
    "【候选主动消息】",
    "【原主动消息】",
    "【最近私聊记录】",
    "【本轮主动来源】",
    "【内在约束】",
)

# AstrBot core 定时任务（active_agent cron）的执行汇报前缀，见
# astrbot/core/cron/manager.py 的 summary_note 与 core/utils/history_saver.py。
# 这类记录是用户可见的对话历史，不属于主动消息框架残留，不能被清理掉。
CRON_JOB_HISTORY_PREFIXES = ("[CronJob]", "【CronJob】")

# 只有当同一行还带有主动消息框架标记时，才把提到 send_message_to_user 的行当作
# 框架残留删除。单独出现工具名的行可能是正常对话或定时任务汇报，不能仅凭工具名
# 判定（否则会把 [CronJob] 记录整条删掉）。
PRIVATE_COMPANION_TOOL_LINE_MARKERS = (
    "privatecompanion",
    "private companion",
    "private_companion",
    "工具调用限制",
    "agent reached max steps",
    "主动消息",
    "主动陪伴",
    "主动私聊",
    "主动承接占位",
    "候选主动消息",
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


def _strip_private_companion_marked_blocks(text: str) -> tuple[str, bool]:
    if not text or "private_companion_" not in text:
        return text or "", False
    cleaned = _PRIVATE_COMPANION_TURN_FRAGMENT_RE.sub("\n", text)
    cleaned = _PRIVATE_COMPANION_BLOCK_RE.sub("\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, cleaned != text


def clean_private_companion_history_text(text: Any) -> tuple[str, bool, bool]:
    raw = str(text or "")
    if not raw:
        return "", False, False
    if raw.lstrip().startswith(CRON_JOB_HISTORY_PREFIXES):
        # 定时任务汇报原样保留，只清无风险的 TTS 标签，绝不按行删除或整条丢弃。
        cleaned = re.sub(r"\[\[TTSBLOCK:[^\]]*\]\]", "", raw)
        cleaned = re.sub(r"\[\[PCTTS:[^\]]*\]\]", "", cleaned).strip()
        return cleaned, cleaned != raw, False
    if private_companion_proactive_text_is_internal(raw):
        return "", True, True

    cleaned = raw
    cleaned = re.sub(r"\[\[TTSBLOCK:[^\]]*\]\]", "", cleaned)
    cleaned = re.sub(r"\[\[PCTTS:[^\]]*\]\]", "", cleaned)
    cleaned = re.sub(r"<timer\b[^>]*>.*?</timer>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<tts\b[^>]*>.*?</tts>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"【主动承接占位】[^\n]*(?:\n|$)", "", cleaned)
    cleaned, removed_companion_block = _strip_private_companion_marked_blocks(cleaned)
    cleaned = re.sub(
        r"\s*<!--\s*private_companion_[^>]*-->\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned, removed_block = _drop_private_companion_proactive_blocks(cleaned)

    kept_lines: list[str] = []
    removed_line = removed_block or removed_companion_block
    for line in cleaned.replace("\r", "\n").splitlines():
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue
        if private_companion_proactive_text_is_internal(stripped):
            removed_line = True
            continue
        lowered = stripped.lower()
        if "send_message_to_user" in lowered and any(
            marker in lowered or marker in stripped
            for marker in PRIVATE_COMPANION_TOOL_LINE_MARKERS
        ):
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


class _RetrievalHistoryParser(HTMLParser):
    """Exclude host reminder blocks without treating their metadata as chat."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.reminder_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "system_reminder":
            self.reminder_depth += 1
        elif not self.reminder_depth:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if tag == "system_reminder":
            self.reminder_depth = max(0, self.reminder_depth - 1)
            if not self.reminder_depth:
                self.parts.append("\n")
        elif not self.reminder_depth:
            self.parts.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "system_reminder" and not self.reminder_depth:
            self.parts.append(self.get_starttag_text())

    def handle_data(self, data: str) -> None:
        if not self.reminder_depth:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.handle_data(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.handle_data(f"<!{decl}>")


def retrieval_history_text(value: Any, *, depth: int = 0) -> str:
    """Project visible dialogue text; leave the actual provider history intact."""
    if value is None or depth > 4:
        return ""
    if isinstance(value, (list, tuple)):
        text = "\n".join(retrieval_history_text(item, depth=depth + 1) for item in value)
    elif isinstance(value, dict):
        text = retrieval_history_text(value.get("text", value.get("content")), depth=depth + 1)
    elif isinstance(value, str):
        text = value
    else:
        content = getattr(value, "text", None)
        if content is None:
            content = getattr(value, "content", None)
        return retrieval_history_text(content, depth=depth + 1)
    if "<system_reminder" in text.lower():
        parser = _RetrievalHistoryParser()
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    cleaned, _changed, drop = clean_private_companion_history_text(text)
    return "" if drop else cleaned


def _is_temp_or_plugin_context(item: Any) -> bool:
    if bool(getattr(item, "_private_companion_turn_fragments", False)):
        return True
    if bool(getattr(item, "_no_save", False) or getattr(item, "no_save", False)):
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


def _is_own_proactive_fragment(item: Any) -> bool:
    """这一项是否本插件生态自己注入的临时件。

    只有带 private_companion 标记、或带 no_save/turn_fragments 等临时标记的条目
    才允许清理；用户历史和别的插件写进来的内容一律视为别人的，不碰。
    """
    if _is_temp_or_plugin_context(item):
        return True
    return "private_companion_" in _plain_request_text(item)


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


def sanitize_request_history(req: Any, *, clean_proactive_guidance: bool = False) -> dict[str, int]:
    """只清理本插件自己注入到请求历史里的临时片段。

    以前默认开启时，这里会直接改写 req.contexts：删掉含 send_message_to_user 的
    整行、把【内在约束】等标题块吞到空行——这些内容可能是用户历史或别的插件写
    的，等于和宿主/其它插件抢上下文。现在只处理能证明是本插件生态写入的条目
    （见 _is_own_proactive_fragment），其余原样保留；整个开关默认关闭。
    """
    zero = {"before": 0, "after": 0, "removed": 0, "cleaned": 0}
    if not clean_proactive_guidance:
        return zero
    contexts = getattr(req, "contexts", None)
    if not isinstance(contexts, list):
        return zero

    cleaned_contexts: list[Any] = []
    cleaned_count = 0
    removed = 0
    for item in contexts:
        if not _is_own_proactive_fragment(item):
            cleaned_contexts.append(item)
            continue
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
