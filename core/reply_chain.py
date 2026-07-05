from __future__ import annotations

import html
import json
import re
from typing import Any

from .identity import maybe_await
from .models import clean_text


class ReplyChainResolver:
    """Resolve quoted-message chains without depending on another plugin."""

    CACHE_ATTRS = (
        "memory_companion_reply_chain",
        "_memory_companion_reply_chain",
        "private_companion_reply_message_chain",
        "_private_companion_reply_message_chain",
    )

    async def resolve(self, event: Any, *, max_depth: int = 3) -> list[dict[str, Any]]:
        cached = self._cached_chain(event)
        if cached:
            self._remember(event, cached)
            return cached

        queue: list[tuple[str, int]] = [(message_id, 1) for message_id in self._event_reply_message_ids(event)]
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_depth = max(1, int(max_depth or 1))

        while queue and len(rows) < max_depth:
            message_id, depth = queue.pop(0)
            message_id = clean_text(message_id, 120)
            if not message_id or message_id in seen or depth > max_depth:
                continue
            seen.add(message_id)

            message_obj = await self._get_message_obj_by_id(event, message_id)
            if not message_obj:
                continue
            raw_message = self._raw_message_from_message_obj(message_obj)
            text = self._message_obj_text_preview(raw_message, limit=280)
            rows.append({"message_id": message_id, "depth": depth, "raw_message": raw_message, "text": text})

            for next_id in self._message_obj_reply_message_ids(raw_message):
                if next_id and next_id not in seen:
                    queue.append((next_id, depth + 1))

        self._remember(event, rows)
        return rows

    def format_for_query(self, chain: list[dict[str, Any]], *, max_chars: int = 640) -> str:
        if not chain:
            return ""
        parts: list[str] = []
        for row in chain[:3]:
            depth = self._safe_int(row.get("depth"), 1)
            text = clean_text(row.get("text"), 220)
            if not text:
                continue
            label = "直接被引用" if depth == 1 else f"第{depth}层引用"
            parts.append(f"{label}: {text}")
        return clean_text("；".join(parts), max_chars)

    def cached_context_for_event(self, event: Any, *, max_chars: int = 640) -> str:
        return self.format_for_query(self._cached_chain(event), max_chars=max_chars)

    def metadata(self, chain: list[dict[str, Any]]) -> dict[str, Any]:
        if not chain:
            return {}
        return {
            "reply_chain_depth": max(self._safe_int(row.get("depth"), 1) for row in chain),
            "reply_chain_message_ids": [
                clean_text(row.get("message_id"), 120)
                for row in chain[:3]
                if clean_text(row.get("message_id"), 120)
            ],
            "reply_chain_preview": self.format_for_query(chain, max_chars=520),
        }

    def _cached_chain(self, event: Any) -> list[dict[str, Any]]:
        if event is None:
            return []
        for attr in self.CACHE_ATTRS:
            raw = getattr(event, attr, None)
            normalized = self._normalize_chain(raw)
            if normalized:
                return normalized
        return []

    def _normalize_chain(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(raw[:3], start=1):
            if not isinstance(item, dict):
                continue
            text = clean_text(item.get("text") or item.get("preview") or item.get("content"), 280)
            raw_message = item.get("raw_message") if "raw_message" in item else item.get("message")
            if not text and raw_message is not None:
                text = self._message_obj_text_preview(raw_message, limit=280)
            rows.append(
                {
                    "message_id": clean_text(item.get("message_id") or item.get("id"), 120),
                    "depth": self._safe_int(item.get("depth"), index),
                    "raw_message": raw_message,
                    "text": text,
                }
            )
        return rows

    def _remember(self, event: Any, chain: list[dict[str, Any]]) -> None:
        if event is None:
            return
        for attr in ("memory_companion_reply_chain", "_memory_companion_reply_chain"):
            try:
                setattr(event, attr, list(chain))
            except Exception:
                pass

    def _event_components(self, event: Any) -> list[Any]:
        if event is None:
            return []
        getter = getattr(event, "get_messages", None)
        if callable(getter):
            try:
                value = getter()
                if isinstance(value, (list, tuple)):
                    return list(value)
            except Exception:
                pass
        message_obj = getattr(event, "message_obj", None)
        chain = getattr(message_obj, "message", None) if message_obj is not None else None
        if isinstance(chain, (list, tuple)):
            return list(chain)
        raw = getattr(message_obj, "raw_message", None) if message_obj is not None else None
        if isinstance(raw, dict):
            chain = raw.get("message")
            if isinstance(chain, (list, tuple)):
                return list(chain)
        return []

    def _event_reply_message_ids(self, event: Any) -> list[str]:
        ids: list[str] = []
        for item in self._event_components(event):
            type_name = self._component_type_name(item)
            if type_name != "reply" and "reply" not in type_name:
                continue
            self._add_unique(ids, self._extract_reply_message_id(item))
        message_obj = getattr(event, "message_obj", None) if event is not None else None
        raw = getattr(message_obj, "raw_message", None) if message_obj is not None else None
        self._message_obj_reply_message_ids(raw, out=ids)
        return ids

    def _message_obj_reply_message_ids(self, message_obj: Any, *, out: list[str] | None = None) -> list[str]:
        ids = out if out is not None else []

        def visit(value: Any, *, depth: int = 0) -> None:
            if value is None or depth > 8:
                return
            if isinstance(value, str):
                for match in re.finditer(r"\[CQ:reply,[^\]]*(?:id|message_id|msg_id)=([^,\]]+)", value, flags=re.I):
                    self._add_unique(ids, html.unescape(match.group(1)).strip())
                parsed = self._decode_possible_json_text(value)
                if parsed is not None:
                    visit(parsed, depth=depth + 1)
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    visit(item, depth=depth + 1)
                return
            type_name = self._component_type_name(value)
            if type_name == "reply" or "reply" in type_name:
                self._add_unique(ids, self._extract_reply_message_id(value))
            if isinstance(value, dict):
                data = self._component_data(value)
                if data is not value:
                    visit(data, depth=depth + 1)
                for key in ("message", "raw_message", "content", "messages"):
                    nested = value.get(key)
                    if nested is not value:
                        visit(nested, depth=depth + 1)
                return
            data = self._component_data(value)
            if data:
                visit(data, depth=depth + 1)

        visit(message_obj)
        return ids

    def _message_obj_text_preview(self, message_obj: Any, *, limit: int = 260) -> str:
        parts: list[str] = []

        def add(value: Any) -> None:
            text = clean_text(value, 180)
            if text:
                parts.append(text)

        def visit(value: Any, *, depth: int = 0) -> None:
            if value is None or depth > 6 or len(parts) >= 8:
                return
            if isinstance(value, str):
                cleaned = re.sub(r"\[CQ:reply,[^\]]+\]", "[引用]", value)
                cleaned = re.sub(r"\[CQ:image[^\]]+\]", "[图片]", cleaned)
                cleaned = re.sub(r"\[CQ:record[^\]]+\]", "[语音]", cleaned)
                add(cleaned)
                parsed = self._decode_possible_json_text(value)
                if parsed is not None:
                    visit(parsed, depth=depth + 1)
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    visit(item, depth=depth + 1)
                return
            type_name = self._component_type_name(value)
            data = self._component_data(value)
            if type_name in {"text", "plain"}:
                add(getattr(value, "text", "") or data.get("text") or data.get("content"))
                return
            if type_name == "image":
                add("[图片]")
                return
            if type_name == "record":
                add("[语音]")
                return
            if type_name == "reply" or "reply" in type_name:
                return
            if isinstance(value, dict):
                for key in ("text", "content", "summary", "title", "desc", "prompt"):
                    if key in value:
                        add(value.get(key))
                for key in ("message", "raw_message", "messages", "data"):
                    nested = value.get(key)
                    if nested is not value:
                        visit(nested, depth=depth + 1)
                return
            for attr in ("text", "message", "content"):
                add(getattr(value, attr, ""))
            if data:
                visit(data, depth=depth + 1)

        visit(message_obj)
        return clean_text(" ".join(part for part in parts if part), limit)

    async def _get_message_obj_by_id(self, event: Any, message_id: str) -> Any:
        bot = getattr(event, "bot", None)
        api = getattr(bot, "api", None)
        call_action = getattr(api, "call_action", None)
        if not callable(call_action):
            return None
        attempts: list[Any] = [message_id]
        if str(message_id).isdigit():
            attempts.insert(0, int(message_id))
        for value in attempts:
            try:
                result = await maybe_await(call_action("get_msg", message_id=value))
            except Exception:
                result = None
            if result:
                return result
        return None

    def _raw_message_from_message_obj(self, message_obj: Any) -> Any:
        if isinstance(message_obj, dict):
            for key in ("message", "raw_message", "content", "messages"):
                value = message_obj.get(key)
                if value is not None:
                    return value
        return message_obj

    def _component_type_name(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("type") or "").strip().lower()
        return str(getattr(item, "type", "") or item.__class__.__name__).strip().lower()

    def _component_data(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            data = item.get("data", {})
            return data if isinstance(data, dict) else {}
        data = getattr(item, "data", {}) or {}
        return data if isinstance(data, dict) else {}

    def _extract_reply_message_id(self, reply_seg: Any) -> str:
        candidates = [
            getattr(reply_seg, "id", None),
            getattr(reply_seg, "message_id", None),
            getattr(reply_seg, "msg_id", None),
        ]
        data = self._component_data(reply_seg)
        candidates.extend([data.get("id"), data.get("message_id"), data.get("msg_id")])
        if isinstance(reply_seg, dict):
            candidates.extend([reply_seg.get("id"), reply_seg.get("message_id"), reply_seg.get("msg_id")])
        for value in candidates:
            text = clean_text(value, 120)
            if text:
                return text
        return ""

    def _decode_possible_json_text(self, value: Any) -> Any:
        text = html.unescape(str(value or "")).strip()
        if not text:
            return None
        text = text.replace("\\/", "/")
        text = text.replace("\\u0026", "&").replace("\\u003d", "=").replace("\\u003f", "?")
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            try:
                text = json.loads(text)
            except Exception:
                pass
        if isinstance(text, str) and text.strip().startswith(("{", "[")):
            try:
                return json.loads(text)
            except Exception:
                return None
        return None

    def _add_unique(self, target: list[str], value: Any) -> None:
        text = clean_text(value, 120)
        if text and text not in target:
            target.append(text)

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default
