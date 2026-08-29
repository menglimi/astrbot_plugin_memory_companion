from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .astrbot_compat import append_temp_text


ACTION_STATE_ATTR = "memory_companion_explicit_action_state"

_REMEMBER_NEGATION_RE = re.compile(
    r"(?:不要|不用|无需|不必|请勿|千万别|取消)[^。！？!?；;]{0,16}"
    r"(?:记住|长期记忆|保存|写入|存入)|别[^。！？!?；;]{0,8}(?:记住|保存|写入|存入)"
)
_REMEMBER_DIRECT_RE = re.compile(
    r"^(?:请|麻烦|拜托|劳驾)?(?:你)?(?:帮我|替我)?(?:长期)?记住"
    r"(?:一下|这件事|这条)?[，,\s]*(?P<content>.+)$"
)
_REMEMBER_WISH_RE = re.compile(
    r"^(?:我希望你|我想让你|我要你)(?:帮我|替我)?(?:长期)?记住"
    r"(?:一下)?[，,\s]*(?P<content>.+)$"
)
_REMEMBER_ENVELOPE_RE = re.compile(
    r"^(?:请|麻烦|拜托|劳驾)?(?:你)?(?:帮我|替我)?(?:把|将)"
    r"(?P<content>.+?)(?:作为长期记忆(?:保存|记录)?|保存(?:为|到|进)长期记忆|"
    r"写入长期记忆|存入长期记忆)[。.!！]?$"
)
_DONT_FORGET_RE = re.compile(
    r"^(?:请|麻烦|拜托)?(?:你)?别忘(?:了|记得)?[，,\s]*(?P<content>.+)$"
)
_RECALL_ACTION_RE = re.compile(
    r"请回忆|帮我回忆|替我回忆|回忆一下|从长期记忆(?:中)?(?:回忆|检索|查询)|"
    r"在长期记忆中(?:回忆|检索|查询)|查询长期记忆|检索长期记忆|你还记得|还记得我|还记得吗"
)
_RECALL_NEGATION_RE = re.compile(
    r"(?:不要|不用|无需|不必|请勿|千万别|取消|别)[^。！？!?；;]{0,16}"
    r"(?:回忆|检索长期记忆|查询长期记忆|想起)"
)
_PROTOCOL_SUFFIX_RE = re.compile(
    r"(?<=[。！？!?；;])\s*(?:本轮(?:必须|需要|请)|这轮(?:必须|需要|请)|"
    r"必须调用\s*memory_companion_|只有工具返回|只有\s*memory_companion_|"
    r"否则请(?:明确)?说保存(?:成功|失败))",
    re.IGNORECASE,
)
_DISCUSSION_CUES = (
    "是什么意思", "怎么翻译", "翻译成", "分析这句", "分析这句话", "解释这句",
    "解释这句话", "改写这句", "举个例", "只是举例", "作为例子", "他说", "她说",
    "他们说", "有人说",
)
_PLACEHOLDER_CONTENT = {
    "这条", "这件事", "这个", "以下", "以下内容", "下面", "下面内容", "接下来的内容"
}

_REMEMBER_OK_STATUS = (
    "<!-- memory_companion_explicit_action_v1 -->\n"
    "【记忆动作结果】本地长期记忆已写入成功。可以简短确认；不要再次调用记忆工具。"
)
_REMEMBER_FAILED_STATUS = (
    "<!-- memory_companion_explicit_action_v1 -->\n"
    "【记忆动作结果】本地长期记忆没有写入成功。请明确说明保存失败；不要再次调用记忆工具。"
)
_RECALL_READY_STATUS = (
    "<!-- memory_companion_explicit_action_v1 -->\n"
    "【记忆动作结果】本轮长期记忆检索已经完成，直接使用已临时注入的候选回答；不要再次调用记忆工具。"
)
_RECALL_EMPTY_STATUS = (
    "<!-- memory_companion_explicit_action_v1 -->\n"
    "【记忆动作结果】本轮长期记忆检索已经完成，但没有可用候选。请如实说未找到，不要猜测或再次调用记忆工具。"
)


def event_message_text(event: Any) -> str:
    return str(getattr(event, "message_str", "") or "").strip()


def _single_line(value: Any, limit: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _discusses_or_quotes(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("\"", "'", "“", "‘", "《")) or any(
        cue in text for cue in _DISCUSSION_CUES
    )


def _usable_content(content: Any) -> str:
    value = _single_line(content, 3200)
    match = _PROTOCOL_SUFFIX_RE.search(value)
    if match:
        value = value[: match.start()]
    value = value.strip(" \t:：,，")[:3000].strip()
    return "" if value.rstrip("。.!！") in _PLACEHOLDER_CONTENT else value


def explicit_remember_content_from_text(text: Any) -> str:
    cleaned = _single_line(text)
    if not cleaned or _REMEMBER_NEGATION_RE.search(cleaned) or _discusses_or_quotes(cleaned):
        return ""
    colon = re.search(r"[:：]", cleaned)
    if colon and re.search(r"(?:记住|长期记忆|保存|写入|存入)", cleaned[: colon.start()]):
        return _usable_content(cleaned[colon.end() :])
    for pattern in (
        _REMEMBER_ENVELOPE_RE,
        _REMEMBER_DIRECT_RE,
        _REMEMBER_WISH_RE,
        _DONT_FORGET_RE,
    ):
        match = pattern.match(cleaned)
        if match:
            return _usable_content(match.group("content"))
    return ""


def explicit_recall_query_from_text(text: Any) -> str:
    cleaned = _single_line(text)
    if (
        not cleaned
        or _RECALL_NEGATION_RE.search(cleaned)
        or not _RECALL_ACTION_RE.search(cleaned)
        or _discusses_or_quotes(cleaned)
    ):
        return ""
    if not re.match(
        r"^(?:请|麻烦|拜托|劳驾|帮我|替我|回忆|从长期记忆|在长期记忆|"
        r"查询长期记忆|检索长期记忆|你还记得|还记得)",
        cleaned,
    ):
        return ""
    return cleaned


def request_tool_names(tool_set: Any) -> list[str]:
    names: list[str] = []
    for tool in getattr(tool_set, "tools", None) or ():
        name = str(getattr(tool, "name", "") or "").strip()[:120]
        if name and name not in names:
            names.append(name)
    getter = getattr(tool_set, "names", None)
    if callable(getter):
        try:
            for raw_name in getter() or ():
                name = str(raw_name or "").strip()[:120]
                if name and name not in names:
                    names.append(name)
        except Exception:
            pass
    return names


def remove_request_tools(req: Any, names: Iterable[str]) -> list[str]:
    tool_set = getattr(req, "func_tool", None)
    wanted = {str(name or "").strip() for name in names if str(name or "").strip()}
    present = set(request_tool_names(tool_set))
    remover = getattr(tool_set, "remove_tool", None)
    tools = getattr(tool_set, "tools", None)
    for name in sorted(wanted & present):
        try:
            if callable(remover):
                remover(name)
            elif isinstance(tools, list):
                tools[:] = [
                    tool
                    for tool in tools
                    if str(getattr(tool, "name", "") or "").strip() != name
                ]
        except Exception:
            continue
    remaining = set(request_tool_names(tool_set))
    return sorted((wanted & present) - remaining)


def _state(target: Any) -> dict[str, Any]:
    value = getattr(target, ACTION_STATE_ATTR, None)
    return value if isinstance(value, dict) else {}


def _set_state(event: Any, req: Any, state: dict[str, Any]) -> None:
    for target in (event, req):
        if target is not None:
            try:
                setattr(target, ACTION_STATE_ATTR, dict(state))
            except Exception:
                pass


def _append_status(req: Any, status: str) -> None:
    if append_temp_text(req, status):
        return
    prompt = str(getattr(req, "prompt", "") or "")
    req.prompt = f"{prompt}\n\n{status}" if prompt else status


def _injection_state(event: Any, req: Any) -> dict[str, Any]:
    for target in (req, event):
        value = getattr(target, "memory_companion_injection_state", None)
        if isinstance(value, dict):
            return value
    return {}


async def handle_explicit_memory_action(
    *,
    service: Any,
    event: Any,
    req: Any,
) -> dict[str, Any] | None:
    """Handle unambiguous save/recall requests without relying on model choice."""

    prior = _state(event) or _state(req)
    if prior.get("handled") or prior.get("in_progress"):
        return dict(prior)

    content = explicit_remember_content_from_text(event_message_text(event))
    if content:
        pending = {
            "action": "remember",
            "handled": False,
            "in_progress": True,
            "ok": False,
            "code": "in_progress",
        }
        _set_state(event, req, pending)
        enabled = bool(service.config.bool("memory_tools.enable_remember_tool", True))
        result: Any = None
        if enabled:
            try:
                result = await service.tool_remember(event, content, note_type="memory")
            except Exception:
                result = None
        ok = bool(isinstance(result, dict) and result.get("ok") is True)
        removed = remove_request_tools(req, ("memory_companion_remember",))
        record = {
            "action": "remember",
            "handled": True,
            "in_progress": False,
            "ok": ok,
            "code": "saved" if ok else "remember_disabled" if not enabled else "write_failed",
            "removed_tools": removed,
            "content_chars": len(content),
        }
        _set_state(event, req, record)
        _append_status(req, _REMEMBER_OK_STATUS if ok else _REMEMBER_FAILED_STATUS)
        return record

    recall_query = explicit_recall_query_from_text(event_message_text(event))
    injection = _injection_state(event, req)
    if recall_query and injection.get("active") is True:
        injected = bool(injection.get("injected"))
        removed = remove_request_tools(
            req,
            ("memory_companion_recall", "memory_companion_navigate"),
        )
        record = {
            "action": "recall",
            "handled": True,
            "in_progress": False,
            "ok": True,
            "code": "reuse_injected" if injected else "no_injected_memory",
            "removed_tools": removed,
            "content_chars": 0,
        }
        _set_state(event, req, record)
        _append_status(req, _RECALL_READY_STATUS if injected else _RECALL_EMPTY_STATUS)
        return record
    return None


__all__ = [
    "ACTION_STATE_ATTR",
    "event_message_text",
    "explicit_recall_query_from_text",
    "explicit_remember_content_from_text",
    "handle_explicit_memory_action",
    "remove_request_tools",
    "request_tool_names",
]
