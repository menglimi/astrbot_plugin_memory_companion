from __future__ import annotations

import json
import re
from typing import Any

from .models import SearchResult, SessionContext, clean_text

MEMORY_COMPANION_INJECTION_HEADER = "<MemoryCompanion-Context>"
MEMORY_COMPANION_INJECTION_FOOTER = "</MemoryCompanion-Context>"


class InjectionComposer:
    def compose(
        self,
        ctx: SessionContext,
        results: list[SearchResult],
        max_chars: int = 1800,
        *,
        intent_context: str = "",
        slot_sections: list[tuple[str, list[SearchResult]]] | None = None,
        compact_memory: bool = False,
        time_context: str = "",
    ) -> str:
        if not results and not intent_context:
            return ""

        allowed = "self_timeline, current_private, shareable"
        blocked = "other_private, unrelated_group, not_visible"
        if ctx.scope == "group":
            allowed = "self_timeline, current_group_public, shareable"
        lines = [
            "<memory_companion_context>",
            "<instruction>",
            "这是本轮临时记忆资料，不是用户新发言，也不是新的回复任务。",
            "先回答 current_user_message；记忆只在直接相关时补充，不要让旧话题抢答。",
            "按 memory 分组使用：mention_memory 可自然提及；tone_memory 只调语气不复述；uncertain_memory 只能带不确定感。",
            "若记忆与当前消息冲突，以当前消息和用户纠正为准；严格保留私聊、群聊和 Bot 自我时间线的来源边界。",
            "本包已按可见性、ACL、窗口边界和分槽上限过滤；不要推断或泄露其它窗口的私密内容。",
            f"允许使用：{allowed}；禁止使用：{blocked}。",
        ]
        if compact_memory:
            lines.append("当前是多条记忆聚合查询；请按证据逐条归纳，缺失的日期或项目必须说不确定，不要为了凑完整列表而编造。")
            lines.append("记忆条目已经按表达用途分组，优先读取日期、内容和来源。")
        lines.extend(
            [
                "</instruction>",
                "",
                "<current_user_message>",
                clean_text(ctx.message_text, 500) or "未读取到文本；以 AstrBot 当前轮真实用户消息为准。",
                "</current_user_message>",
                "",
                "<current_window>",
                f"会话类型：{ctx.scope or 'unknown'}",
                f"当前对象：{ctx.label}",
                "</current_window>",
                "",
            ]
        )
        if intent_context:
            lines.extend(
                [
                    "<retrieval_intent>",
                    intent_context,
                    "</retrieval_intent>",
                    "",
                ]
            )
        if time_context:
            lines.extend(
                [
                    "<time_window>",
                    f"以下资料限定在 {clean_text(time_context, 80)} 的相关记忆与时间线。",
                    "</time_window>",
                    "",
                ]
            )
        lines.append("<long_term_memory>")
        self._append_grouped_memory(lines, results, slot_sections=slot_sections, compact=compact_memory)
        if not results:
            lines.append("- 没有检索到足够相关的长期记忆；只依据当前用户消息回复。")
        lines.append("</long_term_memory>")
        lines.extend(
            [
                "",
                "</memory_companion_context>",
            ]
        )

        limit = max(300, int(max_chars or 1800))
        inner_limit = max(120, limit - len(MEMORY_COMPANION_INJECTION_HEADER) - len(MEMORY_COMPANION_INJECTION_FOOTER) - 2)
        text = "\n".join(lines)
        if len(text) > inner_limit:
            text = text[: inner_limit - 1].rstrip() + "…"
        return f"{MEMORY_COMPANION_INJECTION_HEADER}\n{text}\n{MEMORY_COMPANION_INJECTION_FOOTER}"

    def _append_grouped_memory(
        self,
        lines: list[str],
        results: list[SearchResult],
        *,
        slot_sections: list[tuple[str, list[SearchResult]]] | None = None,
        compact: bool = False,
    ) -> None:
        grouped = {
            "mention": [],
            "tone": [],
            "uncertain": [],
        }
        if slot_sections:
            for slot_name, slot_results in slot_sections:
                for item in slot_results or []:
                    grouped.setdefault(self._expression_value(item), []).append((slot_name, item))
        else:
            for item in results:
                grouped.setdefault(self._expression_value(item), []).append(("memory", item))

        section_defs = [
            ("mention", "明说记忆", "这些内容与当前问题直接相关，可以自然提及。"),
            ("tone", "语气底色", "这些内容只用于调整语气、关系感和分寸，不要复述具体内容。"),
            ("uncertain", "不确定记忆", "这些内容置信较低或较久远，只能用“我印象里/不太确定”的方式模糊提及。"),
        ]
        for key, title, hint in section_defs:
            items = grouped.get(key) or []
            if not items:
                continue
            tag = f"{key}_memory"
            lines.append(f"<{tag}>")
            lines.append(f"{title}：{hint}")
            for slot_name, item in items:
                self._append_memory_item(lines, item, slot_name=slot_name, compact=compact)
            lines.append(f"</{tag}>")

    def _append_memory_item(self, lines: list[str], item: SearchResult, *, slot_name: str, compact: bool = False) -> None:
        memory = item.memory
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        if isinstance(memory.metadata, str):
            try:
                loaded = json.loads(memory.metadata)
                metadata = loaded if isinstance(loaded, dict) else {}
            except Exception:
                metadata = {}
        key_facts = metadata.get("key_facts")
        if isinstance(key_facts, list):
            fact_text = "；".join(clean_text(value, 120) for value in key_facts if clean_text(value, 120))
        else:
            fact_text = ""
        canonical = clean_text(metadata.get("canonical_summary"), 180)
        content_limit = 260 if compact else 360
        content = clean_text(memory.content, content_limit)
        evidence = clean_text(memory.evidence, 180)
        detail = clean_text(fact_text or canonical or content, content_limit)
        if evidence and evidence != detail and evidence not in detail and not compact:
            detail = clean_text(f"{detail}（证据：{evidence}）", content_limit + 120)
        parts = [
            f"内容：{detail}",
            f"时间：{self._time_label(memory)}",
            f"来源：{self._source_label(memory)}",
            f"分槽：{clean_text(slot_name, 60)}",
            f"类型：{clean_text(memory.memory_type, 60)}",
            f"可信度：{self._confidence_label(memory.confidence)}",
            f"用法：{self._expression_usage(item)}",
        ]
        lines.append("- " + "；".join(part for part in parts if part))

    @staticmethod
    def _expression_label(item: SearchResult) -> str:
        value = InjectionComposer._expression_value(item)
        labels = {
            "mention": "明说",
            "tone": "语气底色",
            "uncertain": "谨慎不确定",
        }
        return labels.get(value, "明说")

    @staticmethod
    def _expression_usage(item: SearchResult) -> str:
        value = InjectionComposer._expression_value(item)
        if value == "tone":
            return "只影响语气，禁止复述"
        if value == "uncertain":
            return "只能模糊提及，不能当事实"
        return "需要时自然提及"

    @staticmethod
    def _expression_value(item: SearchResult) -> str:
        reason = clean_text(getattr(item, "reason", ""), 1000)
        match = re.search(r"(?:^|;)expression=([^;]+)", reason)
        return clean_text(match.group(1), 40) if match else "mention"

    def _source_label(self, memory) -> str:
        if memory.scope == "group":
            return f"群聊:{memory.group_id or memory.session_id or 'unknown'}"
        if memory.scope == "private":
            if getattr(memory.subject, "kind", "") == "user" and getattr(memory.subject, "id", "") not in {"", "self"}:
                target = memory.subject.name or memory.subject.id
            else:
                target = memory.object.name or memory.object.id or memory.session_id or "unknown"
            return f"私聊:{target}"
        if memory.visibility == "bot_self":
            return "Bot自我时间线"
        return memory.source_plugin or "unknown"

    @staticmethod
    def _time_label(memory) -> str:
        value = clean_text(getattr(memory, "occurred_at", "") or getattr(memory, "updated_at", "") or getattr(memory, "created_at", ""), 40)
        if not value:
            return "未知"
        return clean_text(value[:16].replace("T", " "), 20)

    @staticmethod
    def _confidence_label(value: Any) -> str:
        try:
            confidence = float(value)
        except Exception:
            confidence = 0.0
        if confidence >= 0.82:
            return "高"
        if confidence >= 0.58:
            return "中"
        return "低"
