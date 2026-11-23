"""Bounded extraction and shared-cache reuse for QQ/OneBot merged forward messages.

This module has zero cross-plugin imports:
- First reuses the cross-layer ``_astrbot_parsed_forwards`` payload on ``event``
  when AstrBot Core or another plugin has already resolved the forward cards
  (zero duplicate ``get_forward_msg`` RPCs).
- Falls back to bounded standalone extraction (inline ``Node``/``Nodes`` or
  OneBot ``get_forward_msg`` with strict wall-clock, card, node, and depth caps)
  and caches the normalized result back onto ``event`` for downstream hooks.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import math
import re
import time
from typing import Any

from .identity import maybe_await
from .latency import await_with_timeout, exclude_model_call_wait
from .models import clean_text

SHARED_EXTRA_KEY = "_astrbot_parsed_forwards"
FORWARD_PROTOCOL_VERSION = 1
FORWARD_FALLBACK_PLACEHOLDER = "[合并转发聊天记录]"
FORWARD_HEADER_PREFIX = "[合并转发聊天记录"

DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_MAX_FORWARDS = 12
DEFAULT_MAX_NODES = 120
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_FETCHES = 16
DEFAULT_CARD_MAX_CHARS = 4000
DEFAULT_COMBINED_MAX_CHARS = 16000
DEFAULT_MAX_IMAGE_URLS = 16
TIMELINE_FORWARD_MAX_CHARS = 1000
CAPTURE_FORWARD_MAX_BYTES = 240 * 1024

_CQ_CODE_RE = re.compile(r"\[CQ:([a-zA-Z0-9_]+)(?:,([^\]]*))?\]")
_FORWARD_DIGEST_RE = re.compile(r"\[合并转发聊天记录[^\]]*\].*", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ForwardCard:
    forward_id: str = ""
    message_id: str = ""
    node_count: int = 0
    truncated: bool = False
    summary_text: str = ""
    title: str = ""
    timestamp: str = ""
    image_urls: tuple[str, ...] = ()
    fallback: bool = False

    def to_extra_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "forward_id": self.forward_id,
            "node_count": self.node_count,
            "truncated": self.truncated,
            "summary_text": self.summary_text,
        }
        if self.message_id:
            data["message_id"] = self.message_id
        if self.title:
            data["title"] = self.title
        if self.timestamp:
            data["timestamp"] = self.timestamp
        if self.image_urls:
            data["image_urls"] = list(self.image_urls)
        if self.fallback:
            data["fallback"] = True
        return data


@dataclass(frozen=True, slots=True)
class ParsedForwards:
    version: int = FORWARD_PROTOCOL_VERSION
    source: str = "memory_companion"
    cards: tuple[ForwardCard, ...] = ()
    combined_text: str = ""
    total_nodes: int = 0
    image_urls: tuple[str, ...] = ()
    truncated: bool = False

    def to_extra_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source": self.source,
            "cards": [card.to_extra_dict() for card in self.cards],
            "combined_text": self.combined_text,
            "total_nodes": self.total_nodes,
            "image_urls": list(self.image_urls),
            "truncated": self.truncated,
        }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value) and value > 0:
            try:
                return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
            except (TypeError, ValueError, OverflowError, OSError):
                return ""
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.isdigit():
        return _normalize_timestamp(int(text))
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.utcoffset() is None:
            return ""
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return ""


def _clip_multiline(value: Any, limit: int) -> str:
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in raw.split("\n")]
    compact = "\n".join(line for line in lines if line).strip()
    if limit <= 0 or len(compact) <= limit:
        return compact
    if limit <= 1:
        return compact[:limit]
    return compact[: limit - 1].rstrip() + "…"


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    if max_bytes <= 4:
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    suffix = "…"
    budget = max_bytes - len(suffix.encode("utf-8"))
    return encoded[:budget].decode("utf-8", errors="ignore").rstrip() + suffix


def _component_type_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("type") or "").strip().lower()
    raw_type = getattr(item, "type", None)
    if raw_type is not None:
        val = getattr(raw_type, "value", raw_type)
        name = str(val or "").strip().lower()
        if "." in name:
            name = name.rsplit(".", 1)[-1]
        if name:
            return name
    return item.__class__.__name__.strip().lower()


def _component_data(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        data = item.get("data")
        return data if isinstance(data, dict) else item
    data = getattr(item, "data", None)
    return data if isinstance(data, dict) else {}


def _dedupe_cards(cards: list[ForwardCard]) -> tuple[ForwardCard, ...]:
    deduped: list[ForwardCard] = []
    seen_keys: dict[tuple[str, str], int] = {}
    for card in cards:
        msg_id = card.message_id
        fwd_id = card.forward_id
        key: tuple[str, str] | None = None
        if msg_id or fwd_id:
            key = (msg_id, fwd_id)
        if key is not None and key in seen_keys:
            idx = seen_keys[key]
            existing = deduped[idx]
            if len(card.summary_text) > len(existing.summary_text) or (existing.fallback and not card.fallback):
                deduped[idx] = card
            continue
        if key is not None:
            seen_keys[key] = len(deduped)
        deduped.append(card)
    return tuple(deduped)


def _merge_image_urls(cards: tuple[ForwardCard, ...], extra_urls: Any = None, *, limit: int = DEFAULT_MAX_IMAGE_URLS) -> tuple[str, ...]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(raw: Any) -> None:
        if len(urls) >= limit or not isinstance(raw, str):
            return
        url = raw.strip()
        if not url or url in seen or len(url) > 1024:
            return
        seen.add(url)
        urls.append(url)

    if isinstance(extra_urls, (list, tuple)):
        for item in extra_urls:
            add(item)
    for card in cards:
        for item in card.image_urls:
            add(item)
    return tuple(urls)


def _normalize_cached_payload(raw: Any) -> ParsedForwards | None:
    if isinstance(raw, ParsedForwards):
        return raw if (raw.cards or raw.combined_text) else None
    if not isinstance(raw, dict):
        return None
    version = _safe_int(raw.get("version"), FORWARD_PROTOCOL_VERSION)
    source = clean_text(raw.get("source"), 80) or "shared_cache"
    raw_cards = raw.get("cards")
    cards_list: list[ForwardCard] = []
    cache_cards_truncated = False
    if isinstance(raw_cards, (list, tuple)):
        if len(raw_cards) > 32:
            cache_cards_truncated = True
        for item in raw_cards[:32]:
            if not isinstance(item, dict):
                continue
            fwd_id = clean_text(item.get("forward_id") or item.get("id") or "", 160)
            msg_id = clean_text(item.get("message_id") or "", 120)
            node_count = max(0, _safe_int(item.get("node_count"), 0))
            truncated = bool(item.get("truncated", False))
            summary = _clip_multiline(
                item.get("summary_text") or item.get("text") or item.get("content") or "",
                DEFAULT_CARD_MAX_CHARS,
            )
            title = clean_text(item.get("title") or "", 160)
            ts = _normalize_timestamp(
                item.get("timestamp") or item.get("occurred_at") or item.get("message_at") or ""
            )
            raw_imgs = item.get("image_urls")
            imgs = tuple(
                str(u).strip()
                for u in (raw_imgs if isinstance(raw_imgs, (list, tuple)) else ())
                if isinstance(u, str) and u.strip() and len(u.strip()) <= 1024
            )[:DEFAULT_MAX_IMAGE_URLS]
            fallback = bool(item.get("fallback", False)) or (not summary and node_count == 0)
            if not summary:
                summary = FORWARD_FALLBACK_PLACEHOLDER
            cards_list.append(
                ForwardCard(
                    forward_id=fwd_id,
                    message_id=msg_id,
                    node_count=node_count,
                    truncated=truncated,
                    summary_text=summary,
                    title=title,
                    timestamp=ts,
                    image_urls=imgs,
                    fallback=fallback,
                )
            )

    combined_text = _clip_multiline(raw.get("combined_text") or "", DEFAULT_COMBINED_MAX_CHARS)
    total_nodes = max(0, _safe_int(raw.get("total_nodes"), 0))
    truncated = bool(raw.get("truncated", False))

    if not cards_list and combined_text:
        cards_list.append(
            ForwardCard(
                node_count=total_nodes,
                truncated=truncated,
                summary_text=_clip_multiline(combined_text, DEFAULT_CARD_MAX_CHARS),
                fallback=combined_text == FORWARD_FALLBACK_PLACEHOLDER and total_nodes == 0,
            )
        )
    if not cards_list:
        return None

    cards = _dedupe_cards(cards_list)
    sum_nodes = sum(card.node_count for card in cards)
    effective_nodes = max(total_nodes, sum_nodes)
    effective_truncated = truncated or cache_cards_truncated or any(card.truncated for card in cards)
    if not combined_text:
        combined_text = _compose_combined_text(cards, max_chars=DEFAULT_COMBINED_MAX_CHARS)
    image_urls = _merge_image_urls(cards, raw.get("image_urls"))
    return ParsedForwards(
        version=version if version >= 1 else FORWARD_PROTOCOL_VERSION,
        source=source,
        cards=cards,
        combined_text=combined_text,
        total_nodes=effective_nodes,
        image_urls=image_urls,
        truncated=effective_truncated,
    )


def read_cached_forwards(event: Any) -> ParsedForwards | None:
    """Read already-resolved forward cards from ``event`` without making any RPC."""
    if event is None:
        return None
    raw = None
    get_extra = getattr(event, "get_extra", None)
    if callable(get_extra):
        try:
            raw = get_extra(SHARED_EXTRA_KEY)
        except Exception:
            raw = None
    if raw is None:
        raw = getattr(event, SHARED_EXTRA_KEY, None)
    return _normalize_cached_payload(raw)


def write_cached_forwards(event: Any, parsed: ParsedForwards) -> None:
    """Publish resolved forward cards onto ``event`` for downstream reuse."""
    if event is None:
        return
    payload = parsed.to_extra_dict()
    set_extra = getattr(event, "set_extra", None)
    if callable(set_extra):
        try:
            set_extra(SHARED_EXTRA_KEY, payload)
            return
        except Exception:
            pass
    try:
        setattr(event, SHARED_EXTRA_KEY, payload)
    except Exception:
        pass


def _event_components(event: Any) -> list[Any]:
    if event is None:
        return []
    message_obj = getattr(event, "message_obj", None)
    parts = getattr(message_obj, "message", None)
    if isinstance(parts, (list, tuple)) and parts:
        return list(parts)
    get_messages = getattr(event, "get_messages", None)
    if callable(get_messages):
        try:
            res = get_messages()
            if isinstance(res, (list, tuple)) and res:
                return list(res)
        except Exception:
            pass
    raw_msg = getattr(message_obj, "raw_message", None)
    if isinstance(raw_msg, dict):
        raw_parts = raw_msg.get("message")
        if isinstance(raw_parts, list) and raw_parts:
            return list(raw_parts)
    return []


def has_forward_components(event: Any) -> bool:
    """O(N) zero-allocation check for top-level forward components or cached forwards."""
    if read_cached_forwards(event) is not None:
        return True
    for comp in _event_components(event):
        if _component_type_name(comp) in {"forward", "node", "nodes"}:
            return True
    return False


def _top_level_forward_specs(event: Any, *, max_forwards: int) -> tuple[list[dict[str, Any]], bool]:
    specs: list[dict[str, Any]] = []
    truncated = False
    for comp in _event_components(event):
        tname = _component_type_name(comp)
        if tname not in {"forward", "node", "nodes"}:
            continue
        if len(specs) >= max_forwards:
            truncated = True
            break
        data = _component_data(comp)
        if tname == "forward":
            fwd_id = clean_text(
                getattr(comp, "id", "")
                or getattr(comp, "res_id", "")
                or data.get("id")
                or data.get("res_id")
                or data.get("forward_id")
                or "",
                160,
            )
            inline_nodes = (
                getattr(comp, "nodes", None)
                or getattr(comp, "messages", None)
                or (getattr(comp, "content", None) if isinstance(getattr(comp, "content", None), list) else None)
                or (data.get("content") if isinstance(data.get("content"), list) else None)
                or (data.get("messages") if isinstance(data.get("messages"), list) else None)
            )
            specs.append({"kind": "forward", "forward_id": fwd_id, "inline_nodes": inline_nodes})
        elif tname == "nodes":
            raw_nodes = (
                getattr(comp, "nodes", None)
                or data.get("nodes")
                or data.get("messages")
                or []
            )
            nodes_list = list(raw_nodes) if isinstance(raw_nodes, (list, tuple)) else []
            specs.append({"kind": "nodes", "forward_id": "", "inline_nodes": nodes_list})
        elif tname == "node":
            specs.append({"kind": "node", "forward_id": "", "inline_nodes": [comp]})
    return specs, truncated


def _resolve_call_action(event: Any) -> Any | None:
    bot = getattr(event, "bot", None)
    if bot is None:
        return None
    api = getattr(bot, "api", None)
    call_action = getattr(api, "call_action", None)
    if callable(call_action):
        return call_action
    direct = getattr(bot, "call_action", None)
    return direct if callable(direct) else None


def _extract_messages_from_rpc_result(result: Any) -> list[Any]:
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return []
    containers: list[Any] = [result]
    data = result.get("data")
    if isinstance(data, dict):
        containers.insert(0, data)
    elif isinstance(data, list):
        return data
    for container in containers:
        for key in ("messages", "message", "nodes", "content"):
            val = container.get(key)
            if isinstance(val, list) and val:
                return val
    return []


async def _fetch_forward_messages(
    call_action: Any,
    forward_id: str,
    *,
    deadline_mono: float,
) -> list[Any] | None:
    fid = clean_text(forward_id, 160)
    if not fid or not callable(call_action):
        return None
    param_attempts: list[dict[str, Any]] = [{"id": fid}, {"message_id": fid}]
    if fid.isdigit():
        int_id = int(fid)
        param_attempts.extend([{"id": int_id}, {"message_id": int_id}])
    for params in param_attempts:
        remaining = deadline_mono - time.monotonic()
        if remaining <= 0.02:
            return None
        try:
            async with exclude_model_call_wait():
                result = await await_with_timeout(
                    maybe_await(call_action("get_forward_msg", **params)),
                    remaining,
                )
        except asyncio.TimeoutError:
            return None
        except Exception:
            continue
        messages = _extract_messages_from_rpc_result(result)
        if messages:
            return messages
    return None


def _decode_cq_text(raw: str) -> str:
    if not raw:
        return ""

    def replace_cq(match: re.Match[str]) -> str:
        cq_type = match.group(1).lower()
        params_str = match.group(2) or ""
        if cq_type == "image":
            return "[图片]"
        if cq_type in {"face", "mface", "bface", "sface"}:
            return "[表情]"
        if cq_type == "at":
            m_name = re.search(r"(?:^|,)name=([^,\]]+)", params_str)
            m_qq = re.search(r"(?:^|,)qq=([^,\]]+)", params_str)
            target = (m_name.group(1) if m_name else "") or (m_qq.group(1) if m_qq else "")
            target = html.unescape(target).strip()
            if target.lower() == "all":
                return "[@全体成员]"
            return f"[@{target}]" if target else "[@]"
        if cq_type == "reply":
            return "[回复]"
        if cq_type == "record":
            return "[语音]"
        if cq_type == "video":
            return "[视频]"
        if cq_type == "file":
            return "[文件]"
        if cq_type == "forward":
            return "[嵌套转发消息]"
        if cq_type in {"json", "xml"}:
            return "[卡片消息]"
        return "[非文本消息]"

    rendered = _CQ_CODE_RE.sub(replace_cq, raw)
    return html.unescape(rendered)


def _extract_card_json_preview(raw_payload: Any) -> str:
    text = str(raw_payload or "").strip()
    if not text:
        return "[卡片消息]"
    try:
        parsed = json.loads(html.unescape(text))
    except Exception:
        return "[卡片消息]"
    if isinstance(parsed, dict):
        for key in ("prompt", "desc", "title"):
            val = clean_text(parsed.get(key), 120)
            if val:
                return f"[卡片:{val}]"
        meta = parsed.get("meta")
        if isinstance(meta, dict):
            for section in meta.values():
                if isinstance(section, dict):
                    for key in ("title", "desc", "summary"):
                        val = clean_text(section.get(key), 120)
                        if val:
                            return f"[卡片:{val}]"
    return "[卡片消息]"


def _node_sender_and_content(node: Any) -> tuple[str, Any]:
    if isinstance(node, dict):
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        sender_obj = node.get("sender") if isinstance(node.get("sender"), dict) else {}
        data_sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
        sender = clean_text(
            data.get("nickname")
            or data.get("name")
            or data_sender.get("card")
            or data_sender.get("nickname")
            or sender_obj.get("card")
            or sender_obj.get("nickname")
            or node.get("nickname")
            or node.get("name")
            or data.get("user_id")
            or data.get("uin")
            or sender_obj.get("user_id")
            or node.get("user_id")
            or "",
            60,
        )
        content = (
            data.get("content")
            if data.get("content") is not None
            else (
                data.get("message")
                if data.get("message") is not None
                else (
                    node.get("content")
                    if node.get("content") is not None
                    else (
                        node.get("message")
                        if node.get("message") is not None
                        else node.get("raw_message")
                    )
                )
            )
        )
        return sender, content

    sender = clean_text(
        getattr(node, "name", "")
        or getattr(node, "nickname", "")
        or getattr(node, "uin", "")
        or getattr(node, "user_id", "")
        or "",
        60,
    )
    content = getattr(node, "content", None)
    if content is None:
        content = getattr(node, "message", None)
    return sender, content


async def _parse_node_list(
    nodes: list[Any],
    *,
    call_action: Any | None,
    depth: int,
    max_depth: int,
    budget: dict[str, Any],
    seen_forward_ids: set[str],
    lines: list[str],
    image_urls: list[str],
) -> None:
    for node in nodes:
        if budget["nodes"] >= budget["max_nodes"]:
            budget["truncated"] = True
            return
        sender, content = _node_sender_and_content(node)
        budget["nodes"] += 1
        parts: list[str] = []
        nested_forwards: list[tuple[str, list[Any] | None]] = []

        if isinstance(content, str):
            decoded = clean_text(_decode_cq_text(content), 600)
            if decoded:
                parts.append(decoded)
        elif isinstance(content, (list, tuple)):
            for seg in content:
                if isinstance(seg, str):
                    decoded = clean_text(_decode_cq_text(seg), 600)
                    if decoded:
                        parts.append(decoded)
                    continue
                tname = _component_type_name(seg)
                data = _component_data(seg)
                if tname in {"plain", "text"}:
                    txt = clean_text(getattr(seg, "text", "") or data.get("text") or "", 600)
                    if txt:
                        parts.append(txt)
                elif tname == "image":
                    parts.append("[图片]")
                    url = clean_text(getattr(seg, "url", "") or data.get("url") or data.get("file") or "", 1024)
                    if url.startswith(("http://", "https://")) and len(image_urls) < DEFAULT_MAX_IMAGE_URLS and url not in image_urls:
                        image_urls.append(url)
                elif tname in {"face", "mface", "marketface", "bface", "sface"}:
                    parts.append("[表情]")
                elif tname == "at":
                    target = clean_text(
                        getattr(seg, "name", "")
                        or data.get("name")
                        or getattr(seg, "qq", "")
                        or data.get("qq")
                        or "",
                        60,
                    )
                    if target.lower() == "all":
                        parts.append("[@全体成员]")
                    else:
                        parts.append(f"[@{target}]" if target else "[@]")
                elif tname == "atall":
                    parts.append("[@全体成员]")
                elif tname == "reply":
                    parts.append("[回复]")
                elif tname == "record":
                    parts.append("[语音]")
                elif tname == "video":
                    parts.append("[视频]")
                elif tname == "file":
                    fname = clean_text(getattr(seg, "name", "") or data.get("name") or data.get("file") or "", 80)
                    parts.append(f"[文件:{fname}]" if fname else "[文件]")
                elif tname in {"json", "xml"}:
                    raw_card = getattr(seg, "data", "") if isinstance(getattr(seg, "data", None), str) else (data.get("data") or "")
                    parts.append(_extract_card_json_preview(raw_card))
                elif tname == "forward":
                    nested_id = clean_text(
                        getattr(seg, "id", "") or data.get("id") or data.get("res_id") or "",
                        160,
                    )
                    inline = (
                        getattr(seg, "nodes", None)
                        or (data.get("content") if isinstance(data.get("content"), list) else None)
                        or (data.get("messages") if isinstance(data.get("messages"), list) else None)
                    )
                    if depth < max_depth and (inline or (nested_id and nested_id not in seen_forward_ids)):
                        nested_forwards.append((nested_id, list(inline) if isinstance(inline, (list, tuple)) else None))
                    else:
                        parts.append("[嵌套转发消息]")
                elif tname in {"node", "nodes"}:
                    raw_sub = getattr(seg, "nodes", None) or data.get("nodes") or ([seg] if tname == "node" else [])
                    if depth < max_depth and isinstance(raw_sub, (list, tuple)) and raw_sub:
                        nested_forwards.append(("", list(raw_sub)))
                    else:
                        parts.append("[嵌套转发消息]")
                else:
                    parts.append("[非文本消息]")
        elif content is not None:
            tname = _component_type_name(content)
            if tname in {"plain", "text"}:
                txt = clean_text(getattr(content, "text", ""), 600)
                if txt:
                    parts.append(txt)

        line_body = clean_text(" ".join(p for p in parts if p), 600)
        if line_body:
            prefix = "  " * max(0, depth - 1)
            lines.append(f"{prefix}{sender}: {line_body}" if sender else f"{prefix}{line_body}")

        for nested_id, inline_nodes in nested_forwards:
            if budget["nodes"] >= budget["max_nodes"]:
                budget["truncated"] = True
                return
            sub_nodes = inline_nodes
            if sub_nodes is None and nested_id:
                if nested_id in seen_forward_ids or budget["fetches"] >= budget["max_fetches"]:
                    lines.append(f"{'  ' * depth}[嵌套转发消息]")
                    continue
                seen_forward_ids.add(nested_id)
                budget["fetches"] += 1
                sub_nodes = await _fetch_forward_messages(
                    call_action,
                    nested_id,
                    deadline_mono=budget["deadline_mono"],
                )
            if sub_nodes:
                await _parse_node_list(
                    sub_nodes,
                    call_action=call_action,
                    depth=depth + 1,
                    max_depth=max_depth,
                    budget=budget,
                    seen_forward_ids=seen_forward_ids,
                    lines=lines,
                    image_urls=image_urls,
                )
            else:
                lines.append(f"{'  ' * depth}[嵌套转发消息]")


def _compose_combined_text(cards: tuple[ForwardCard, ...], *, max_chars: int = DEFAULT_COMBINED_MAX_CHARS) -> str:
    parts = [format_single_card_text(card, max_chars=DEFAULT_CARD_MAX_CHARS, single_line=False) for card in cards]
    joined = "\n\n".join(part for part in parts if part)
    return _clip_multiline(joined, max_chars)


async def extract_forwards(
    event: Any,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_forwards: int = DEFAULT_MAX_FORWARDS,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_fetches: int = DEFAULT_MAX_FETCHES,
) -> ParsedForwards | None:
    """Resolve merged forward cards from shared cache first, else bounded standalone RPC."""
    cached = read_cached_forwards(event)
    if cached is not None:
        return cached

    safe_max_forwards = max(1, min(32, int(max_forwards or DEFAULT_MAX_FORWARDS)))
    specs, cards_truncated = _top_level_forward_specs(event, max_forwards=safe_max_forwards)
    if not specs:
        return None

    safe_timeout = (
        max(0.05, min(float(timeout_seconds), DEFAULT_TIMEOUT_SECONDS))
        if isinstance(timeout_seconds, (int, float)) and math.isfinite(timeout_seconds) and timeout_seconds > 0
        else DEFAULT_TIMEOUT_SECONDS
    )
    safe_max_nodes = max(1, min(300, int(max_nodes or DEFAULT_MAX_NODES)))
    safe_max_depth = max(1, min(6, int(max_depth or DEFAULT_MAX_DEPTH)))
    safe_max_fetches = max(1, min(32, int(max_fetches or DEFAULT_MAX_FETCHES)))
    call_action = _resolve_call_action(event)
    outer_msg_id = clean_text(
        getattr(getattr(event, "message_obj", None), "message_id", "") or "",
        120,
    )
    outer_ts = _normalize_timestamp(getattr(getattr(event, "message_obj", None), "timestamp", None))
    deadline_mono = time.monotonic() + safe_timeout

    budget: dict[str, Any] = {
        "nodes": 0,
        "max_nodes": safe_max_nodes,
        "fetches": 0,
        "max_fetches": safe_max_fetches,
        "truncated": cards_truncated,
        "deadline_mono": deadline_mono,
    }
    seen_forward_ids: set[str] = set()
    cards_list: list[ForwardCard] = []

    for spec in specs:
        fwd_id = str(spec.get("forward_id") or "")
        inline_nodes = spec.get("inline_nodes")
        raw_nodes: list[Any] | None = list(inline_nodes) if isinstance(inline_nodes, (list, tuple)) and inline_nodes else None
        if raw_nodes is None and fwd_id:
            if fwd_id in seen_forward_ids:
                continue
            seen_forward_ids.add(fwd_id)
            if budget["fetches"] < budget["max_fetches"]:
                budget["fetches"] += 1
                raw_nodes = await _fetch_forward_messages(
                    call_action,
                    fwd_id,
                    deadline_mono=deadline_mono,
                )

        if not raw_nodes:
            cards_list.append(
                ForwardCard(
                    forward_id=fwd_id,
                    message_id=outer_msg_id,
                    node_count=0,
                    truncated=False,
                    summary_text=FORWARD_FALLBACK_PLACEHOLDER,
                    timestamp=outer_ts,
                    fallback=True,
                )
            )
            continue

        nodes_before = budget["nodes"]
        truncated_before = budget["truncated"]
        card_lines: list[str] = []
        card_images: list[str] = []
        await _parse_node_list(
            raw_nodes,
            call_action=call_action,
            depth=1,
            max_depth=safe_max_depth,
            budget=budget,
            seen_forward_ids=seen_forward_ids,
            lines=card_lines,
            image_urls=card_images,
        )
        card_node_count = max(0, budget["nodes"] - nodes_before)
        card_truncated = bool(budget["truncated"] and not truncated_before) or (
            budget["nodes"] >= budget["max_nodes"] and len(raw_nodes) > card_node_count
        )
        summary = _clip_multiline("\n".join(card_lines), DEFAULT_CARD_MAX_CHARS)
        is_fallback = not summary
        if not summary:
            summary = FORWARD_FALLBACK_PLACEHOLDER
        cards_list.append(
            ForwardCard(
                forward_id=fwd_id,
                message_id=outer_msg_id,
                node_count=card_node_count,
                truncated=card_truncated,
                summary_text=summary,
                timestamp=outer_ts,
                image_urls=tuple(card_images[:DEFAULT_MAX_IMAGE_URLS]),
                fallback=is_fallback,
            )
        )

    if not cards_list:
        return None
    cards = _dedupe_cards(cards_list)
    parsed = ParsedForwards(
        version=FORWARD_PROTOCOL_VERSION,
        source="memory_companion",
        cards=cards,
        combined_text=_compose_combined_text(cards, max_chars=DEFAULT_COMBINED_MAX_CHARS),
        total_nodes=sum(card.node_count for card in cards),
        image_urls=_merge_image_urls(cards),
        truncated=bool(budget["truncated"] or any(card.truncated for card in cards)),
    )
    write_cached_forwards(event, parsed)
    return parsed


def format_single_card_header(card: ForwardCard) -> str:
    if card.node_count > 0:
        return f"[合并转发聊天记录({card.node_count}条)]"
    return FORWARD_FALLBACK_PLACEHOLDER


def format_single_card_text(
    card: ForwardCard,
    *,
    max_chars: int = TIMELINE_FORWARD_MAX_CHARS,
    single_line: bool = True,
) -> str:
    header = format_single_card_header(card)
    body = card.summary_text.strip()
    if not body or body == FORWARD_FALLBACK_PLACEHOLDER:
        return header
    if body.startswith(FORWARD_HEADER_PREFIX):
        return clean_text(body, max_chars) if single_line else _clip_multiline(body, max_chars)
    if single_line:
        flat_body = " | ".join(line.strip() for line in body.splitlines() if line.strip())
        return clean_text(f"{header} {flat_body}", max_chars)
    return _clip_multiline(f"{header}\n{body}", max_chars)


def format_forward_timeline_text(
    parsed: ParsedForwards,
    *,
    max_chars: int = TIMELINE_FORWARD_MAX_CHARS,
) -> str:
    """Format a compact, clearly-framed timeline projection (<= max_chars)."""
    if not parsed.cards:
        return FORWARD_FALLBACK_PLACEHOLDER
    if len(parsed.cards) == 1:
        return format_single_card_text(parsed.cards[0], max_chars=max_chars, single_line=True)
    count = len(parsed.cards)
    header = (
        f"[合并转发聊天记录({count}组/共{parsed.total_nodes}条)]"
        if parsed.total_nodes > 0
        else f"[合并转发聊天记录({count}组)]"
    )
    per_card_budget = max(80, (max_chars - len(header) - 8) // count)
    snippets: list[str] = []
    for idx, card in enumerate(parsed.cards, start=1):
        body = " | ".join(line.strip() for line in card.summary_text.splitlines() if line.strip())
        if body.startswith(FORWARD_HEADER_PREFIX):
            body = re.sub(r"^\[合并转发聊天记录[^\]]*\]\s*", "", body).strip()
        if not body or body == FORWARD_FALLBACK_PLACEHOLDER:
            snippets.append(f"#{idx}: [合并转发聊天记录]")
        else:
            snippets.append(f"#{idx}: {clean_text(body, per_card_budget)}")
    return clean_text(f"{header} " + " || ".join(snippets), max_chars)


def format_forward_capture_body(
    plain_text: str,
    parsed: ParsedForwards,
    *,
    max_bytes: int = CAPTURE_FORWARD_MAX_BYTES,
) -> str:
    """Build a bounded full capture body for ``capture_sources`` (UTF-8 safe)."""
    parts: list[str] = []
    own = str(plain_text or "").strip()
    if own:
        parts.append(own)
    for idx, card in enumerate(parsed.cards, start=1):
        rendered = format_single_card_text(card, max_chars=DEFAULT_CARD_MAX_CHARS, single_line=False)
        if len(parsed.cards) > 1:
            parts.append(f"[转发#{idx}] {rendered}")
        else:
            parts.append(rendered)
    return _truncate_utf8("\n".join(part for part in parts if part), max_bytes)


def build_forward_media_refs(cards: tuple[ForwardCard, ...] | list[ForwardCard]) -> list[dict[str, str]]:
    """Build bounded ``SourceCapture.prepare(media=...)`` forward references."""
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for idx, card in enumerate(cards, start=1):
        if len(refs) >= 32:
            break
        ref = clean_text(card.forward_id or card.message_id or f"card_{idx}", 160)
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append({"kind": "forward", "ref": ref})
    return refs


def split_distinct_card_entries(
    parsed: ParsedForwards,
    *,
    outer_message_id: str,
    has_own_text: bool,
) -> tuple[list[ForwardCard], list[ForwardCard]]:
    """Partition cards into separate-message cards vs cards belonging to the outer event.

    When a debounce layer aggregates multiple earlier pure-forward events (each with
    its own ``message_id``) onto a final event, separate-message cards are captured
    individually under their real ``message_id`` so deduplication and range recall
    stay exact per card.
    """
    outer_id = clean_text(outer_message_id, 120)
    separate: list[ForwardCard] = []
    attached: list[ForwardCard] = []
    if any(card.message_id and card.message_id != outer_id for card in parsed.cards):
        for card in parsed.cards:
            if card.message_id and (card.message_id != outer_id or not has_own_text):
                separate.append(card)
            else:
                attached.append(card)
        return separate, attached
    return separate, list(parsed.cards)


def strip_forward_digest_segments(text: Any) -> str:
    """Strip ``[合并转发聊天记录...]`` projections before rule-based user profile extraction."""
    raw = str(text or "")
    if not raw or FORWARD_HEADER_PREFIX not in raw:
        return raw
    return _FORWARD_DIGEST_RE.sub("", raw).strip()


def timeline_row_has_forward(row: dict[str, Any], metadata: dict[str, Any] | None = None) -> bool:
    """Detect whether a timeline row carries a forwarded chat log projection."""
    meta = metadata if isinstance(metadata, dict) else {}
    if bool(meta.get("has_forward")):
        return True
    media = meta.get("media")
    if isinstance(media, list):
        for item in media:
            if isinstance(item, dict) and str(item.get("kind") or "").strip().lower() == "forward":
                return True
    content = str(row.get("content") or "").lstrip()
    return content.startswith(FORWARD_HEADER_PREFIX)
