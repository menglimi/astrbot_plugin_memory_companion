from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import SessionContext, clean_text, json_loads


@dataclass(slots=True)
class RetrievalIntent:
    """Structured query hints collected before memory retrieval."""

    query: str = ""
    source: str = "message"
    topic: str = ""
    intent: str = ""
    entities: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    query_mode: str = "current_message"
    companion_hint_status: str = ""
    companion_bot_mood: str = ""
    companion_bot_energy: float = 0.0

    def terms(self) -> list[str]:
        values: list[str] = []
        for value in [self.topic, self.intent, *self.entities, *self.facts, *self.keywords]:
            text = clean_text(value, 80)
            if text:
                values.append(text)
        return list(dict.fromkeys(values))

    def format_for_injection(self, max_chars: int = 520) -> str:
        lines: list[str] = []
        if self.query_mode and self.query_mode != "current_message":
            lines.append(f"- 检索模式：{self.query_mode}")
        if self.companion_hint_status and self.companion_hint_status not in {"none", "ignored"}:
            lines.append(f"- 陪伴线索：{self.companion_hint_status}")
        if self.topic:
            lines.append(f"- 当前话题：{self.topic}")
        if self.intent:
            lines.append(f"- 对话意图：{self.intent}")
        if self.entities:
            lines.append("- 相关对象：" + "、".join(self.entities[:8]))
        if self.facts:
            lines.append("- 检索事实：" + " / ".join(self.facts[:4]))
        if self.keywords:
            lines.append("- 检索关键词：" + "、".join(self.keywords[:8]))
        if self.notes:
            lines.append("- 陪伴线索：" + " / ".join(self.notes[:3]))
        if self.companion_bot_mood:
            lines.append(f"- Bot当前情绪底色：{self.companion_bot_mood}")
        if self.companion_bot_energy > 0:
            lines.append(f"- Bot心理能量：{self.companion_bot_energy:.0f}/100")
        text = "\n".join(lines)
        return clean_text(text, max_chars)


class RetrievalIntentBuilder:
    """Builds a retrieval query from the current message and optional companion hints."""

    CONTEXT_ATTRS = (
        "memory_companion_context",
        "memorycompanion_context",
        "angelheart_context",
        "angelmemory_context",
        "companion_context",
        "private_companion_context",
    )

    def build(
        self,
        ctx: SessionContext,
        *,
        req: Any = None,
        event: Any = None,
        explicit_query: str = "",
        query_mode: str = "",
    ) -> RetrievalIntent:
        message_query = clean_text(
            explicit_query
            or ctx.message_text
            or clean_text(getattr(req, "prompt", "") if req is not None else "", 1200),
            1200,
        )
        normalized_mode = self._normalize_query_mode(query_mode)
        parse_companion = normalized_mode in {"guarded_companion", "companion_augmented"}
        payloads = self._context_payloads(event) if parse_companion else []
        merged = self._merge_payloads(payloads)

        topic = self._first_text(merged, ("topic", "title", "subject", "current_topic"))
        intent = self._first_text(merged, ("intent", "reply_intent", "semantic_kind", "reason", "action"))
        entities = self._list_field(merged, ("entities", "entity", "participants", "users"))
        facts = self._list_field(merged, ("facts", "key_facts", "recent_facts", "memory_facts"))
        keywords = self._list_field(merged, ("keywords", "keyword", "main_topics", "topics"))
        notes = self._list_field(
            merged,
            (
                "motive",
                "scene",
                "topic_summary",
                "planned_proactive_motive",
                "planned_proactive_reason",
                "schedule",
            ),
        )

        companion_bot_mood = self._first_text(
            merged,
            ("mood_bias", "mood", "bot_mood", "emotion", "bot_emotion", "emotional_state"),
        )
        try:
            companion_bot_energy = float(
                self._first_text(merged, ("energy", "bot_energy", "psychological_energy"))
                or 0.0
            )
        except Exception:
            companion_bot_energy = 0.0

        companion_terms = [topic, *entities, *facts[:4], *keywords[:8]]
        companion_used = False
        companion_status = "none"
        if parse_companion and companion_terms:
            companion_status = "ignored"
            if normalized_mode == "companion_augmented":
                companion_used = True
                companion_status = "expanded_query"
            elif self._companion_overlaps_message(message_query, companion_terms):
                companion_used = True
                companion_status = "guarded_overlap"
            else:
                topic = ""
                intent = ""
                entities = []
                facts = []
                keywords = []
                notes = []
                companion_status = "guarded_no_overlap"

        query_parts = [*companion_terms, message_query] if companion_used else [message_query]
        query = clean_text(" ".join(part for part in query_parts if clean_text(part, 120)), 1400)
        if not query:
            query = message_query
        source = "companion" if companion_used else "message"
        return RetrievalIntent(
            query=query,
            source=source,
            topic=topic,
            intent=intent,
            entities=entities,
            facts=facts,
            keywords=keywords,
            notes=notes,
            query_mode=normalized_mode,
            companion_hint_status=companion_status,
            companion_bot_mood=companion_bot_mood,
            companion_bot_energy=companion_bot_energy,
        )

    def _normalize_query_mode(self, query_mode: str) -> str:
        mode = clean_text(query_mode, 40).lower()
        if mode in {"current_message", "guarded_companion", "companion_augmented"}:
            return mode
        return "current_message"

    def _companion_overlaps_message(self, message_query: str, companion_terms: list[str]) -> bool:
        message_terms = self._overlap_terms([message_query])
        hint_terms = self._overlap_terms(companion_terms)
        if not message_terms or not hint_terms:
            return False
        return bool(message_terms & hint_terms)

    def _overlap_terms(self, values: list[str]) -> set[str]:
        text = " ".join(clean_text(value, 160) for value in values if clean_text(value, 160)).lower()
        terms: set[str] = set()
        for word in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", text):
            if re.fullmatch(r"[\u4e00-\u9fff]{4,}", word):
                terms.update(word[i : i + 2] for i in range(0, len(word) - 1))
            if len(word) >= 2:
                terms.add(word)
        return terms

    def _context_payloads(self, event: Any) -> list[dict[str, Any]]:
        if event is None:
            return []
        payloads: list[dict[str, Any]] = []
        for attr in self.CONTEXT_ATTRS:
            if not hasattr(event, attr):
                continue
            parsed = self._parse_context(getattr(event, attr))
            if parsed:
                payloads.append(parsed)
        return payloads

    def _parse_context(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            value = raw.strip()
            if not value:
                return {}
            parsed = json_loads(value, {})
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _merge_payloads(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for payload in payloads:
            self._merge_one(merged, payload)
            for nested_key in ("secretary_decision", "rag", "retrieval", "context", "decision"):
                nested = payload.get(nested_key)
                if isinstance(nested, dict):
                    self._merge_one(merged, nested)
        return merged

    def _merge_one(self, merged: dict[str, Any], payload: dict[str, Any]) -> None:
        for key, value in payload.items():
            if value in (None, "", [], {}):
                continue
            old = merged.get(key)
            if old is None:
                merged[key] = value
            elif isinstance(old, list):
                old.extend(self._coerce_list(value))
            elif isinstance(value, list):
                merged[key] = [old, *value]

    def _first_text(self, payload: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                value = next((item for item in value if clean_text(item, 120)), "")
            text = clean_text(value, 120)
            if text:
                return text
        return ""

    def _list_field(self, payload: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
        result: list[str] = []
        for key in keys:
            result.extend(self._coerce_list(payload.get(key)))
        return list(dict.fromkeys(clean_text(item, 100) for item in result if clean_text(item, 100)))[:12]

    def _coerce_list(self, value: Any) -> list[str]:
        if value in (None, "", [], {}):
            return []
        if isinstance(value, list):
            return [clean_text(item, 120) for item in value if clean_text(item, 120)]
        if isinstance(value, dict):
            return [clean_text(v, 120) for v in value.values() if clean_text(v, 120)]
        text = clean_text(value, 240)
        if not text:
            return []
        if "|" in text:
            return [clean_text(part, 120) for part in text.split("|") if clean_text(part, 120)]
        return [text]
