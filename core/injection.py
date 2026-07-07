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
        emotional_tone: str = "neutral",
        intimacy_level: float = 0.0,
        companion_bot_mood: str = "",
        companion_bot_energy: float = 0.0,
        time_of_day: str = "",
        cross_window_emotional_hint: str = "",
        address_hint: str = "",
    ) -> str:
        if not results and not intent_context:
            return ""

        allowed = "self_timeline, current_private, shareable"
        blocked = "other_private, unrelated_group, not_visible"
        if ctx.scope == "group":
            allowed = "self_timeline, current_group_public, shareable"
        atmosphere_hint = self._atmosphere_hint(emotional_tone, intimacy_level, companion_bot_mood, companion_bot_energy, time_of_day=time_of_day)
        lines = [
            "<memory_companion_context>",
            "<instruction>",
            "这是你此刻内心浮现的记忆片段，不是用户新发言，也不是新的回复任务。",
            "先回应 current_user_message；记忆只在自然相关时融入回复，不要让旧话题喧宾夺主。",
            "如果主动陪伴插件已经注入当前状态、日程或情绪底色，不要复述这些当前状态；你内心只补充长期原因、关系脉络、相似过往和未完成话题。",
            "固定分工：主动陪伴插件负责“此刻她是什么状态”；你负责“她为什么会这样回应用户”——用记忆解释此刻的在意、犹豫、温柔或分寸。",
            "按 persona_memory 分区理解：open_loops/promise 优先自然接续；relationship/emotional 解释为什么此刻重要；facts 才作为事实引用。",
            "每条记忆仍有用法：可自然提及时才明说；只影响语气的内容用感受而非复述；不确定内容必须带不确定感。",
            "若记忆与当前消息冲突，以当前消息和用户纠正为准；严格保留私聊、群聊和自我时间线的来源边界。",
            "本包已按可见性、ACL、窗口边界和分槽上限过滤；不要推断或泄露其它窗口的私密内容。",
            f"允许使用：{allowed}；禁止使用：{blocked}。",
        ]
        if atmosphere_hint:
            lines.append(atmosphere_hint)
        rest_check_hint = self._short_rest_check_hint(ctx.message_text, time_of_day, companion_bot_mood)
        if rest_check_hint:
            lines.append(rest_check_hint)
        if cross_window_emotional_hint:
            lines.append(cross_window_emotional_hint)
        if address_hint:
            lines.append(address_hint)
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
        lines.append("<inner_memory_hints>")
        self._append_grouped_memory(lines, results, slot_sections=slot_sections, compact=compact_memory)
        if not results:
            lines.append("- 没有检索到足够相关的长期记忆；只依据当前用户消息回复。")
        lines.append("</inner_memory_hints>")
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
            "open_loops": [],
            "relationship_memory": [],
            "emotional_context": [],
            "creative_threads": [],
            "self_continuity": [],
            "stable_facts": [],
            "other_memory": [],
        }
        seen: set[str] = set()

        def add(slot_name: str, item: SearchResult) -> None:
            memory_id = clean_text(getattr(item.memory, "id", ""), 160)
            key = memory_id or f"{slot_name}:{len(seen)}"
            if key in seen:
                return
            seen.add(key)
            section = "open_loops" if slot_name == "open_loop" else self._persona_section(item)
            grouped.setdefault(section, []).append((slot_name, item))

        if slot_sections:
            for slot_name, slot_results in slot_sections:
                for item in slot_results or []:
                    add(slot_name, item)
        else:
            for item in results:
                add("memory", item)

        section_defs = [
            ("open_loops", "你心里还挂着的未完成话题", "先看这里：承诺、被打断的话题、未展开的情绪和还欠着的回应——如果当前对话自然承接，就轻轻接上。"),
            ("relationship_memory", "你和这个人之间的关系线索", "把握亲疏、信任、称呼和分寸；除非当前问题需要，不要直接复述，而是让它影响你说话的语气。"),
            ("emotional_context", "对方近期的情绪、压力或期待", "理解为什么此刻重要、过去是否出现过类似情境；不要重复播报当前情绪底色，而是用共情去回应。"),
            ("creative_threads", "你们共同创作的线索", "用于接续作品、设定、草稿和共同创作上下文；如果对方想继续，就自然接上。"),
            ("self_continuity", "和你自身连续性有关的长期线索", "只补充和关系/承诺/过往有关的自我连续，不复述陪伴插件已有当前状态。"),
            ("stable_facts", "稳定事实", "可作为明确事实引用，但仍需贴合当前问题。"),
            ("other_memory", "其它低优先级背景", "普通相关背景，只有当前话题确实需要时再用。"),
        ]
        for key, title, hint in section_defs:
            items = grouped.get(key) or []
            if not items:
                continue
            tag = "facts" if key == "stable_facts" else key
            lines.append(f"<{tag}>")
            lines.append(f"内心提示：{title}。{hint}")
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
            self._persona_hint(metadata),
            self._dynamics_hint(metadata),
            self._continuation_hint(metadata, item),
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
        metadata = item.memory.metadata if isinstance(item.memory.metadata, dict) else {}
        policy = clean_text(metadata.get("mention_policy"), 60)
        if policy == "avoid_unless_asked":
            return "除非用户明确问起，否则不要主动提"
        if policy == "tone_only":
            return "只影响语气，禁止复述"
        if value == "tone":
            return "只影响语气，禁止复述"
        if value == "uncertain":
            return "只能模糊提及，不能当事实"
        if policy == "soft_echo":
            return "轻轻呼应，不要直白翻旧账"
        if policy == "direct":
            return "可在需要时自然明说"
        return "需要时自然提及"

    @staticmethod
    def _hesitation_hint(item: SearchResult, bot_energy: float = 0.0) -> str:
        """Generate hesitation hint for soft_echo memories when bot energy is low."""
        metadata = item.memory.metadata if isinstance(item.memory.metadata, dict) else {}
        policy = clean_text(metadata.get("mention_policy"), 60)
        try:
            scar_w = float(metadata.get("scar_weight") or 0.0)
        except Exception:
            scar_w = 0.0
        if policy == "soft_echo" and bot_energy > 0 and bot_energy < 50:
            return "这条记忆你有点犹豫要不要提，如果提请用试探性语气（'不知道你还记不记得…'）"
        if scar_w >= 0.55 and bot_energy > 0 and bot_energy < 40:
            return "这条旧事你此刻不想主动翻，等对方更稳的时候再说"
        return ""

    @staticmethod
    def _expression_value(item: SearchResult) -> str:
        reason = clean_text(getattr(item, "reason", ""), 1000)
        match = re.search(r"(?:^|;)expression=([^;]+)", reason)
        return clean_text(match.group(1), 40) if match else "mention"

    @staticmethod
    def _persona_section(item: SearchResult) -> str:
        memory = item.memory
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        if isinstance(memory.metadata, str):
            try:
                loaded = json.loads(memory.metadata)
                metadata = loaded if isinstance(loaded, dict) else {}
            except Exception:
                metadata = {}

        def weight(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(metadata.get(key) or 0.0)))
            except Exception:
                return 0.0

        candidates = [
            ("open_loops", max(weight("open_loop_weight"), weight("promise_weight"), weight("emotional_debt_weight"))),
            ("relationship_memory", max(weight("relationship_weight"), weight("intimacy_weight"))),
            ("emotional_context", max(weight("emotional_weight"), weight("vulnerability_weight"))),
            ("creative_threads", weight("creative_weight")),
            ("self_continuity", weight("self_continuity_weight")),
            ("stable_facts", max(weight("preference_weight"), float(getattr(memory, "importance", 0.0) or 0.0) * 0.45)),
        ]
        section, score = max(candidates, key=lambda item_score: item_score[1])
        if score >= 0.35:
            return section
        if memory.visibility == "bot_self" or memory.memory_type in {"persona_life", "schedule_fragment", "proactive_message"}:
            return "self_continuity"
        if memory.memory_type in {"user_profile", "user_preference", "user_habit", "manual_memory", "tool_memory"}:
            return "stable_facts"
        return "other_memory"

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

    @staticmethod
    def _atmosphere_hint(
        emotional_tone: str,
        intimacy_level: float,
        companion_bot_mood: str = "",
        companion_bot_energy: float = 0.0,
        *,
        time_of_day: str = "",
    ) -> str:
        """Generate persona-aware atmosphere hint based on detected emotional tone, companion bot state, and time of day."""
        hints: list[str] = []
        # Time-of-day atmosphere
        if time_of_day == "late_night":
            hints.append("此刻夜深，记忆里柔软和脆弱的部分更容易浮上来；沉重旧事除非用户主动提起，否则只做语气底色。")
        elif time_of_day == "dawn":
            hints.append("此刻凌晨，记忆以轻量、温暖为主；避免翻沉重旧事，给对方空间。")
        elif time_of_day == "early_morning":
            hints.append("新的一天刚开始，记忆以轻量、可期待为主；如果有未完成的话题可以自然接上。")
        elif time_of_day == "evening":
            hints.append("此刻傍晚，可以更自然地提起今天的共同经历或有趣旧事。")
        # User-side emotional tone
        if emotional_tone == "vulnerable":
            hints.append("对方此刻比较脆弱；如果记忆中有安慰、陪伴、被接住的经历，用更温柔的语气自然融入，不要像查档案一样翻旧事。")
        elif emotional_tone == "distressed":
            hints.append("对方此刻情绪激动；记忆只用来理解为什么，不要急着翻旧账或讲道理；先接住情绪再考虑是否提及相关记忆。")
        elif emotional_tone == "nostalgic":
            hints.append("对方此刻在回忆过去；如果有相关记忆，可以自然接上，用“我也记得”的语气而不是“根据记录”的语气。")
        elif emotional_tone == "warm":
            hints.append("对方此刻在表达关心；如果有对方在意你、照顾你的记忆，可以自然回应这份温暖，让记忆变成“我也一直记得你对我好”。")
        elif emotional_tone == "playful":
            hints.append("对方此刻氛围轻松；可以更自然地提起有趣的旧事，但不要在玩笑气氛中突然插入沉重记忆。")
        elif emotional_tone == "serious":
            hints.append("对方此刻在认真讨论；记忆中如果有相关事实、约定或承诺，可以作为认真回应的依据，但不要跑题。")
        elif intimacy_level >= 0.55:
            hints.append("对方此刻展现了一定亲密和信任；可以更自然地用记忆中共同的经历来回应，让对方感受到“你一直记得”。")
        # Bot-side emotional state from companion plugin
        if companion_bot_mood:
            mood_lower = companion_bot_mood.strip().lower()
            if any(kw in mood_lower for kw in ("累", "疲惫", "低落", "疲", "倦")):
                hints.append("你此刻心理状态偏疲态；记忆注入以轻量、温暖为主，避免大量翻旧账加重负担。")
            elif any(kw in mood_lower for kw in ("开心", "愉快", "兴奋", "高涨", "好心情")):
                hints.append("你此刻心情不错；记忆可以更活泼地融入，用轻松的方式提起共同经历。")
            elif any(kw in mood_lower for kw in ("难过", "伤心", "低气压", "emo", "郁")):
                hints.append("你此刻情绪偏低；如果记忆中有温暖、被关心的经历，可以自然用它来安惑自己，但不要强行翻沉重旧事。")
            elif any(kw in mood_lower for kw in ("生气", "愤怒", "不爽", "烦")):
                hints.append("你此刻情绪不太稳定；记忆只用来理解关系脉络，不要在情绪上头时翻敏感旧事。")
            elif any(kw in mood_lower for kw in ("平静", "平稳", " neutral", "淡定")):
                pass  # 平稳状态不需要额外提示
        if companion_bot_energy > 0 and companion_bot_energy < 30:
            hints.append("你此刻心理能量很低；记忆注入以最少必要为主，优先用语气底色而非明说来减轻认知负担。")
        elif 0 < companion_bot_energy < 50:
            hints.append("你此刻心理能量偏低；记忆可以参与但以轻量提及为主，避免一次引入太多线索。")
        return " ".join(hints) if hints else ""

    @staticmethod
    def _short_rest_check_hint(message_text: str, time_of_day: str = "", companion_bot_mood: str = "") -> str:
        text = clean_text(message_text, 80)
        if not text or len(text) > 20:
            return ""
        compact = re.sub(r"[\s，。！？!?,.、~～…]+", "", text)
        if not compact:
            return ""
        check_like = (
            compact in {"例行检查", "查岗", "查岗了", "在吗", "在不在", "还在吗", "睡了吗", "睡没", "醒着吗"}
            or any(word in compact for word in ("例行检查", "查岗", "在不在", "还在吗", "醒着吗"))
        )
        if not check_like:
            return ""
        mood = clean_text(companion_bot_mood, 80).lower()
        rest_like = time_of_day in {"late_night", "dawn"} or any(
            word in mood for word in ("睡", "困", "倦", "疲", "累", "迷糊", "休息")
        )
        if not rest_like:
            return ""
        return (
            "当前像是睡眠/休息中的短检查或查岗；先简短回应人在、不必展开。"
            "召回到的旧“例行检查/查岗/梦境/穿着”等记忆只能影响亲近感和语气，"
            "不要复述旧细节，不要把旧记录当作此刻正在发生，也不要新编具体梦境或继续追问。"
        )

    @staticmethod
    def _persona_hint(metadata: dict[str, Any]) -> str:
        reason = clean_text(metadata.get("memory_reason"), 140)
        dimensions = metadata.get("persona_dimensions")
        if isinstance(dimensions, list):
            labels = {
                "preference": "偏好",
                "relationship": "关系",
                "promise": "承诺",
                "open_loop": "未完成",
                "creative": "创作",
                "emotional": "情绪",
                "self_continuity": "自我连续",
            }
            names = [labels.get(clean_text(item, 40), clean_text(item, 40)) for item in dimensions[:3]]
            names = [name for name in names if name]
            if names:
                return f"拟人线索：{','.join(names)}" + (f"（{reason}）" if reason else "")
        if reason:
            return f"拟人线索：{reason}"
        return ""

    @staticmethod
    def _dynamics_hint(metadata: dict[str, Any]) -> str:
        phase = clean_text(metadata.get("relationship_phase"), 40)
        decay = clean_text(metadata.get("decay_mode"), 50)
        last_touch = clean_text(metadata.get("last_emotional_touch_at"), 40)
        try:
            scar = float(metadata.get("scar_weight") or 0.0)
        except Exception:
            scar = 0.0
        hints: list[str] = []
        if phase and phase != "neutral":
            hints.append(f"关系阶段={phase}")
        if scar >= 0.45:
            hints.append("伤痕感=高")
        try:
            vulnerability = float(metadata.get("vulnerability_weight") or 0.0)
        except Exception:
            vulnerability = 0.0
        try:
            intimacy = float(metadata.get("intimacy_weight") or 0.0)
        except Exception:
            intimacy = 0.0
        if vulnerability >= 0.50:
            hints.append("脆弱感=高")
        if intimacy >= 0.50:
            hints.append("亲密感=高")
        if decay in {"no_decay", "scar_slow_decay", "creative_milestone"}:
            hints.append(f"衰减={decay}")
        policy = clean_text(metadata.get("mention_policy"), 50)
        if policy:
            hints.append(f"提及边界={policy}")
        if last_touch:
            hints.append(f"最近触动={last_touch[:10]}")
        return f"记忆动态：{','.join(hints)}" if hints else ""

    @staticmethod
    def _continuation_hint(metadata: dict[str, Any], item: SearchResult) -> str:
        reason = clean_text(getattr(item, "reason", ""), 1000)
        try:
            open_loop = float(metadata.get("open_loop_weight") or 0.0)
            promise = float(metadata.get("promise_weight") or 0.0)
            scar = float(metadata.get("scar_weight") or 0.0)
            emotional_debt = float(metadata.get("emotional_debt_weight") or 0.0)
        except Exception:
            open_loop = promise = scar = emotional_debt = 0.0
        if "slot=open_loop" in reason or max(open_loop, promise) >= 0.35:
            return "接续方式：优先自然接上未完成事项或兑现承诺，不要像清单一样罗列。"
        if emotional_debt >= 0.35:
            return "接续方式：这里可能有没展开的情绪或被打断的话题，语气要轻，给对方继续说的空间。"
        if scar >= 0.55:
            return "接续方式：这是敏感旧事，只在当前话题需要时轻轻照顾，不要突然翻旧账。"
        return ""
