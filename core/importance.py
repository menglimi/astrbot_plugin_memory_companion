from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import MemoryRecord, clean_text


class ImportanceEvaluator:
    """Calibrate memory importance around long-term conversational value."""

    version = "persona_dimensions_v5"

    def calibrate(self, record: MemoryRecord, *, source: str = "") -> MemoryRecord:
        base = self._base_importance(record.importance)
        dimensions = self.persona_dimensions(record)
        score = self.evaluate(record, base=base, dimensions=dimensions)
        record.importance = score
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        metadata.setdefault("base_importance", round(base, 3))
        metadata["importance_evaluator"] = self.version
        metadata["persona_importance"] = dimensions["persona_importance"]
        metadata["relationship_weight"] = dimensions["relationship_weight"]
        metadata["emotional_weight"] = dimensions["emotional_weight"]
        metadata["promise_weight"] = dimensions["promise_weight"]
        metadata["open_loop_weight"] = dimensions["open_loop_weight"]
        metadata["creative_weight"] = dimensions["creative_weight"]
        metadata["preference_weight"] = dimensions["preference_weight"]
        metadata["self_continuity_weight"] = dimensions["self_continuity_weight"]
        metadata["freshness_weight"] = dimensions["freshness_weight"]
        metadata["scar_weight"] = dimensions["scar_weight"]
        metadata["emotional_debt_weight"] = dimensions["emotional_debt_weight"]
        metadata["last_emotional_touch_at"] = dimensions["last_emotional_touch_at"]
        metadata["relationship_phase"] = dimensions["relationship_phase"]
        metadata["decay_mode"] = dimensions["decay_mode"]
        metadata.setdefault("mention_policy", dimensions["mention_policy"])
        metadata.setdefault("mentionability_score", dimensions["mentionability_score"])
        metadata.setdefault("mention_policy_source", self.version)
        metadata["memory_reason"] = dimensions["memory_reason"]
        metadata["persona_dimensions"] = dimensions["active_dimensions"]
        metadata["intimacy_weight"] = dimensions["intimacy_weight"]
        metadata["vulnerability_weight"] = dimensions["vulnerability_weight"]
        if source:
            metadata["importance_source"] = clean_text(source, 80)
        record.metadata = metadata
        return record

    def evaluate(
        self,
        record: MemoryRecord,
        *,
        base: float | None = None,
        dimensions: dict[str, Any] | None = None,
    ) -> float:
        base_score = self._base_importance(record.importance if base is None else base)
        text = self._memory_text(record)
        compact = re.sub(r"\s+", "", text.lower())
        dimensions = dimensions or self.persona_dimensions(record)
        semantic = 0.30

        semantic += self._memory_type_bonus(record)
        semantic += self._lifecycle_bonus(record)
        semantic += self._marker_bonus(compact)
        semantic += self._metadata_bonus(record)
        semantic += float(dimensions.get("persona_importance", 0.0) or 0.0) * 0.18
        semantic += float(dimensions.get("freshness_weight", 0.0) or 0.0) * 0.05
        semantic += float(dimensions.get("scar_weight", 0.0) or 0.0) * 0.06
        semantic += float(dimensions.get("intimacy_weight", 0.0) or 0.0) * 0.04
        semantic += float(dimensions.get("vulnerability_weight", 0.0) or 0.0) * 0.05
        semantic += self._length_bonus(text)
        semantic += self._confidence_bonus(record)
        semantic -= self._low_value_penalty(compact, record)

        final = base_score * 0.52 + semantic * 0.48
        final = max(final, self._source_preserved_floor(record, base_score))
        final = max(self._min_floor(record), min(self._max_ceiling(record, compact), final))
        return round(max(0.0, min(1.0, final)), 3)

    def persona_dimensions(self, record: MemoryRecord) -> dict[str, Any]:
        text = self._memory_text(record)
        compact = re.sub(r"\s+", "", text.lower())
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        memory_type = clean_text(record.memory_type, 120).lower()
        tags = {clean_text(tag, 80).lower() for tag in record.tags or []}
        occurred_at = self._event_time(record)

        preference = self._dimension_score(
            compact,
            ("喜欢", "讨厌", "不喜欢", "偏好", "生日", "名字", "称呼", "叫我", "我是", "习惯", "口味", "雷点"),
        )
        relationship = self._dimension_score(
            compact,
            ("关系", "朋友", "主人", "信任", "陪", "在意", "依赖", "亲近", "疏远", "和好", "误会", "吃醋", "边界", "称呼"),
        )
        promise = self._dimension_score(
            compact,
            ("约定", "承诺", "答应", "说好", "以后", "记住", "别忘", "提醒", "下次", "明天", "保证", "要做", "会继续"),
        )
        open_loop = self._dimension_score(
            compact,
            (
                "未完成",
                "没完成",
                "没做完",
                "没写完",
                "未写完",
                "没整理完",
                "还没",
                "继续",
                "下次",
                "待续",
                "回头",
                "待办",
                "待补",
                "todo",
                "提醒",
                "之后再",
                "先记着",
                "没展开",
                "没有展开",
                "没聊完",
                "被打断",
                "打断",
                "欠着",
                "欠",
            ),
        )
        creative = self._dimension_score(
            compact,
            ("作品", "设定", "角色", "剧情", "画", "写了", "创作", "文档", "脚本", "草稿", "世界观", "分镜", "人设", "命名"),
        )
        emotional = self._dimension_score(
            compact,
            (
                "难过",
                "开心",
                "生气",
                "害怕",
                "压力",
                "低落",
                "崩溃",
                "委屈",
                "感动",
                "安心",
                "哭",
                "累",
                "情绪",
                "转折",
                "冲突",
                "吵架",
                "道歉",
                "安慰",
                "受伤",
                "失望",
            ),
        )
        self_continuity = self._dimension_score(
            compact,
            ("日程", "计划", "自主", "主动", "我做了", "我想", "我记得", "睡眠", "休息", "状态"),
        )
        intimacy = self._dimension_score(
            compact,
            (
                "想你",
                "喜欢你",
                "爱你",
                "舍不得",
                "依赖",
                "离不开",
                "信任",
                "在意",
                "在乎",
                "珍惜",
                "特别",
                "唯一",
                "最重要",
                "心里话",
                "秘密",
                "只跟你",
                "没跟别人说过",
                "依靠",
                "倾诉",
                "贴贴",
                "抱抱",
                "依靠你",
                "不想分开",
                "你是我的",
            ),
        )
        vulnerability = self._dimension_score(
            compact,
            (
                "累",
                "难过",
                "哭",
                "害怕",
                "孤独",
                "委屈",
                "崩溃",
                "焦虑",
                "压力",
                "不安",
                "迷茫",
                "无助",
                "压抑",
                "绝望",
                "没安全感",
                "睡不着",
                "噩梦",
                "撑不住",
                "想消失",
                "没意义",
                "没人懂",
                "好寂寞",
                "好孤单",
                "心疼",
            ),
        )

        if memory_type in {"user_profile", "user_preference", "user_habit"}:
            preference = max(preference, 0.72)
        if memory_type in {"creative_work"} or "creative_work" in tags:
            creative = max(creative, 0.74)
        if memory_type in {"schedule_fragment", "persona_life", "proactive_message"}:
            self_continuity = max(self_continuity, 0.55)
        if memory_type in {"manual_memory", "tool_memory", "explicit_memory"}:
            promise = max(promise, 0.42)
        if memory_type.endswith("graph:relationship") or "relationship" in tags:
            relationship = max(relationship, 0.70)
        if memory_type in {"conversation_summary"}:
            relationship = max(relationship, 0.20)

        sentiment = clean_text(metadata.get("sentiment"), 40)
        if sentiment in {"positive", "negative"}:
            emotional = max(emotional, 0.46)
        for key, target in (
            ("open_loops", "open_loop"),
            ("relationship_notes", "relationship"),
            ("emotional_turning_points", "emotional"),
            ("creative_threads", "creative"),
            ("routine_check_notes", "open_loop"),
        ):
            value = metadata.get(key)
            if isinstance(value, list) and value:
                if target == "open_loop":
                    open_loop = max(open_loop, 0.62 if key == "routine_check_notes" else 0.70)
                    if key == "routine_check_notes":
                        self_continuity = max(self_continuity, 0.42)
                elif target == "relationship":
                    relationship = max(relationship, 0.62)
                elif target == "emotional":
                    emotional = max(emotional, 0.62)
                elif target == "creative":
                    creative = max(creative, 0.62)

        # Group summaries may use a first-person observer voice while describing
        # several members. They remain useful context but cannot become the Bot's
        # personal plan or open loop; verified Bot facts are stored separately.
        is_group_summary = memory_type == "conversation_summary" and (
            record.scope == "group" or clean_text(record.visibility, 80).lower() == "group_public"
        )
        if is_group_summary:
            promise = min(promise, 0.25)
            open_loop = min(open_loop, 0.25)
            self_continuity = min(self_continuity, 0.20)

        weights = {
            "preference_weight": preference,
            "relationship_weight": relationship,
            "promise_weight": promise,
            "open_loop_weight": open_loop,
            "creative_weight": creative,
            "emotional_weight": emotional,
            "self_continuity_weight": self_continuity,
            "intimacy_weight": intimacy,
            "vulnerability_weight": vulnerability,
        }
        persona_importance = max(weights.values())
        if relationship >= 0.45 and emotional >= 0.35:
            persona_importance = max(persona_importance, min(0.95, (relationship + emotional) / 2 + 0.12))
        if promise >= 0.45 and open_loop >= 0.45:
            persona_importance = max(persona_importance, min(0.95, (promise + open_loop) / 2 + 0.14))
        if intimacy >= 0.45 and vulnerability >= 0.35:
            persona_importance = max(persona_importance, min(0.95, (intimacy + vulnerability) / 2 + 0.10))
        phase = self._relationship_phase(compact, relationship, emotional, promise)
        scar = self._scar_weight(compact, relationship, emotional, promise, open_loop, creative, phase)
        emotional_debt = self._emotional_debt_weight(compact, emotional, relationship, open_loop, promise, phase)
        freshness = self._freshness_weight(occurred_at, emotional, relationship, open_loop, promise)
        decay_weights = dict(weights)
        decay_weights["emotional_weight"] = emotional
        decay_weights["emotional_debt_weight"] = emotional_debt
        decay_mode = self._decay_mode(record, decay_weights, scar, phase)

        active = [
            name.removesuffix("_weight")
            for name, value in weights.items()
            if float(value or 0.0) >= 0.35
        ]
        rounded = {key: round(max(0.0, min(1.0, value)), 3) for key, value in weights.items()}
        rounded["persona_importance"] = round(max(0.0, min(1.0, persona_importance)), 3)
        rounded["freshness_weight"] = round(max(0.0, min(1.0, freshness)), 3)
        rounded["scar_weight"] = round(max(0.0, min(1.0, scar)), 3)
        rounded["emotional_debt_weight"] = round(max(0.0, min(1.0, emotional_debt)), 3)
        rounded["intimacy_weight"] = round(max(0.0, min(1.0, intimacy)), 3)
        rounded["vulnerability_weight"] = round(max(0.0, min(1.0, vulnerability)), 3)
        rounded["last_emotional_touch_at"] = occurred_at if max(emotional, relationship, promise, open_loop, scar, emotional_debt) >= 0.35 else ""
        rounded["relationship_phase"] = phase
        rounded["decay_mode"] = decay_mode
        mention_policy, mentionability = self._mention_policy(record, rounded)
        rounded["mention_policy"] = mention_policy
        rounded["mentionability_score"] = mentionability
        rounded["active_dimensions"] = active
        rounded["memory_reason"] = self._memory_reason(active, rounded)
        return rounded

    @staticmethod
    def _mention_policy(record: MemoryRecord, weights: dict[str, Any]) -> tuple[str, float]:
        memory_type = clean_text(record.memory_type, 120).lower()
        visibility = clean_text(record.visibility, 80).lower()
        reality = clean_text(record.reality_level, 80).lower()
        phase = clean_text(weights.get("relationship_phase"), 80).lower()
        decay_mode = clean_text(weights.get("decay_mode"), 80).lower()
        tags = {clean_text(tag, 80).lower() for tag in record.tags or []}

        def weight(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(weights.get(key) or 0.0)))
            except Exception:
                return 0.0

        scar = weight("scar_weight")
        emotional_debt = weight("emotional_debt_weight")
        emotional = weight("emotional_weight")
        relationship = weight("relationship_weight")
        open_loop = weight("open_loop_weight")
        promise = weight("promise_weight")
        creative = weight("creative_weight")
        preference = weight("preference_weight")

        if "avoid_unless_asked" in tags or (phase == "conflict" and max(scar, emotional_debt) >= 0.78):
            return "avoid_unless_asked", 0.18
        if visibility == "bot_self" or reality in {"bot_action", "persona_life", "fictional_content"}:
            if max(open_loop, promise, creative) >= 0.58:
                return "soft_echo", 0.56
            return "tone_only", 0.34
        if max(scar, emotional_debt, emotional) >= 0.66:
            return "tone_only", 0.36
        vulnerability = weight("vulnerability_weight")
        intimacy = weight("intimacy_weight")
        if vulnerability >= 0.58 and scar < 0.35:
            return "soft_echo", 0.48
        if max(open_loop, promise, relationship, creative, intimacy) >= 0.45 or decay_mode in {"no_decay", "scar_slow_decay", "creative_milestone"}:
            return "soft_echo", 0.58
        if memory_type in {"manual_memory", "explicit_memory", "user_profile", "user_preference", "user_habit"} or preference >= 0.58:
            return "direct", 0.72
        if record.sayability == "direct" and record.confidence >= 0.72 and scar < 0.35:
            return "direct", 0.66
        return "soft_echo", 0.50

    @staticmethod
    def _dimension_score(compact: str, markers: tuple[str, ...]) -> float:
        hits = sum(1 for marker in markers if marker in compact)
        if hits <= 0:
            return 0.0
        return min(0.85, 0.26 + hits * 0.16)

    @staticmethod
    def _memory_reason(active: list[str], weights: dict[str, Any]) -> str:
        labels = {
            "preference": "用户偏好/画像",
            "relationship": "关系意义",
            "promise": "承诺或约定",
            "open_loop": "未完成事项",
            "creative": "创作连续性",
            "emotional": "情绪转折",
            "self_continuity": "Bot自我连续性",
            "intimacy": "亲密信任",
            "vulnerability": "脆弱时刻",
        }
        chosen = [labels.get(item, item) for item in active[:3]]
        phase = clean_text(weights.get("relationship_phase"), 40)
        decay = clean_text(weights.get("decay_mode"), 40)
        scar = float(weights.get("scar_weight") or 0.0)
        suffix: list[str] = []
        if phase and phase != "neutral":
            suffix.append(f"关系阶段={phase}")
        if scar >= 0.45:
            suffix.append("带伤痕感，召回时应更克制")
        if decay in {"no_decay", "scar_slow_decay", "creative_milestone"}:
            suffix.append(f"衰减策略={decay}")
        if not chosen:
            base = "普通长期记忆，按事实相关性使用。"
        else:
            base = "；".join(chosen) + "较强，回复时应保留连续感和分寸。"
        return base + ((" " + "；".join(suffix) + "。") if suffix else "")

    @staticmethod
    def _event_time(record: MemoryRecord) -> str:
        return clean_text(record.occurred_at or record.updated_at or record.created_at, 80)

    def _freshness_weight(
        self,
        occurred_at: str,
        emotional: float,
        relationship: float,
        open_loop: float,
        promise: float,
    ) -> float:
        days = self._age_days(occurred_at)
        if days is None:
            return 0.0
        sensitivity = max(emotional, relationship * 0.82, open_loop * 0.9, promise * 0.88, 0.18)
        return sensitivity * self._exp_decay(days, 10.0)

    @staticmethod
    def _scar_weight(
        compact: str,
        relationship: float,
        emotional: float,
        promise: float,
        open_loop: float,
        creative: float,
        phase: str,
    ) -> float:
        scar_markers = (
            "冲突",
            "吵架",
            "误会",
            "和好",
            "道歉",
            "安慰",
            "受伤",
            "失望",
            "崩溃",
            "委屈",
            "哭",
            "别再",
            "不要再",
        )
        marker_score = 0.22 if any(marker in compact for marker in scar_markers) else 0.0
        if phase in {"conflict", "repair", "comfort"}:
            marker_score += 0.18
        blended = max(emotional * 0.58 + relationship * 0.30, promise * 0.45 + open_loop * 0.35, creative * 0.25)
        return min(0.95, marker_score + blended)

    @staticmethod
    def _emotional_debt_weight(
        compact: str,
        emotional: float,
        relationship: float,
        open_loop: float,
        promise: float,
        phase: str,
    ) -> float:
        debt_markers = (
            "没展开",
            "没有展开",
            "没说完",
            "没聊完",
            "被打断",
            "打断",
            "之后再说",
            "下次再说",
            "先不说",
            "不想说",
            "算了",
            "低落",
            "难过",
            "委屈",
            "崩溃",
            "压力",
            "安慰",
        )
        marker_score = 0.0
        hits = sum(1 for marker in debt_markers if marker in compact)
        if hits:
            marker_score = min(0.42, 0.18 + hits * 0.08)
        if phase in {"conflict", "repair", "comfort", "sensitive"}:
            marker_score += 0.12
        return min(0.95, marker_score + emotional * 0.44 + relationship * 0.18 + max(open_loop, promise) * 0.20)

    @staticmethod
    def _relationship_phase(compact: str, relationship: float, emotional: float, promise: float) -> str:
        if any(marker in compact for marker in ("冲突", "吵架", "误会", "生气", "失望", "受伤", "别再", "不要再")):
            return "conflict"
        if any(marker in compact for marker in ("和好", "道歉", "解释清楚", "重新", "修复")):
            return "repair"
        if any(marker in compact for marker in ("安慰", "陪着", "抱抱", "安心", "没事了", "被理解")):
            return "comfort"
        if any(marker in compact for marker in ("信任", "依赖", "亲近", "在意", "重要")):
            return "closeness"
        if promise >= 0.45:
            return "promise"
        if relationship >= 0.35 or emotional >= 0.42:
            return "sensitive"
        return "neutral"

    @staticmethod
    def _decay_mode(record: MemoryRecord, weights: dict[str, float], scar: float, phase: str) -> str:
        memory_type = clean_text(record.memory_type, 120).lower()
        tags = {clean_text(tag, 80).lower() for tag in record.tags or []}

        def weight(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(weights.get(key) or 0.0)))
            except Exception:
                return 0.0

        if memory_type in {"manual_memory", "explicit_memory", "relationship_claim"} or tags & {"manual", "protected", "no_decay", "keep"}:
            return "no_decay"
        if max(weight("promise_weight"), weight("open_loop_weight"), weight("emotional_debt_weight")) >= 0.70:
            return "no_decay"
        if scar >= 0.55 or phase in {"conflict", "repair", "comfort"}:
            return "scar_slow_decay"
        if memory_type == "creative_work" or weight("creative_weight") >= 0.66 or "creative_work" in tags:
            return "creative_milestone"
        if max(weight("relationship_weight"), weight("emotional_weight"), weight("preference_weight"), weight("intimacy_weight")) >= 0.52:
            return "slow_decay"
        if memory_type in {"conversation_summary", "memory_decay_summary"}:
            return "summary_decay"
        return "normal_decay"

    @staticmethod
    def _age_days(iso_text: str) -> float | None:
        text = clean_text(iso_text, 80)
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
        except Exception:
            return None

    @staticmethod
    def _exp_decay(days: float, half_like_days: float) -> float:
        return max(0.0, min(1.0, 2.0 ** (-max(0.0, days) / max(1.0, half_like_days))))

    @staticmethod
    def _base_importance(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return 0.3

    @staticmethod
    def _memory_text(record: MemoryRecord) -> str:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        parts: list[str] = [
            record.memory_type,
            record.reality_level,
            record.lifecycle,
            record.content,
            record.evidence,
            " ".join(record.tags or []),
        ]
        for key in (
            "canonical_summary",
            "persona_summary",
            "key_facts",
            "topics",
            "participants",
            "title",
            "note_type",
        ):
            value = metadata.get(key)
            if isinstance(value, list):
                value = " ".join(str(item) for item in value if item)
            parts.append(clean_text(value, 1200))
        return clean_text(" ".join(part for part in parts if part), 5000)

    @staticmethod
    def _memory_type_bonus(record: MemoryRecord) -> float:
        memory_type = clean_text(record.memory_type, 120).lower()
        reality = clean_text(record.reality_level, 120).lower()
        tags = {clean_text(tag, 80).lower() for tag in record.tags or []}
        bonus = 0.0
        if memory_type in {"manual_memory", "explicit_memory"} or "explicit_memory" in tags:
            bonus += 0.20
        if memory_type in {"user_profile", "user_preference"} or {"user_profile", "user_preference"} & tags:
            bonus += 0.16
        if memory_type == "conversation_summary":
            bonus += 0.11
        if memory_type in {"tool_memory", "companion_note"}:
            bonus += 0.10
        if memory_type in {"creative_work", "image_action", "search_action", "qzone_action"}:
            bonus += 0.08
        if memory_type in {"schedule_fragment", "persona_life"}:
            bonus += 0.05
        if memory_type == "proactive_message":
            bonus += 0.04
        if memory_type.endswith("graph:relationship") or "relationship" in tags:
            bonus += 0.07
        if reality in {"real_user_fact", "persona_life", "llm_summary"}:
            bonus += 0.05
        if record.lifecycle == "raw_event":
            bonus -= 0.07
        return bonus

    @staticmethod
    def _lifecycle_bonus(record: MemoryRecord) -> float:
        if record.lifecycle == "stable_memory":
            return 0.04
        if record.lifecycle == "raw_event":
            return -0.04
        if record.lifecycle == "archived":
            return -0.08
        return 0.0

    @staticmethod
    def _marker_bonus(compact: str) -> float:
        groups = (
            (0.14, ("记住", "别忘", "你要记得", "以后", "约定", "承诺", "答应", "密码")),
            (0.12, ("喜欢", "讨厌", "不喜欢", "偏好", "生日", "名字", "称呼", "叫我", "我是")),
            (0.10, ("关系", "朋友", "主人", "重要", "在意", "难过", "开心", "生气", "害怕", "压力")),
            (0.08, ("日程", "计划", "安排", "待办", "提醒", "明天", "下周", "今天")),
            (0.08, ("作品", "设定", "角色", "剧情", "画", "写了", "创作", "文档")),
            (0.06, ("决定", "结论", "原因", "复盘", "总结", "进展")),
        )
        bonus = 0.0
        for value, markers in groups:
            if any(marker in compact for marker in markers):
                bonus += value
        return min(0.30, bonus)

    @staticmethod
    def _metadata_bonus(record: MemoryRecord) -> float:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        bonus = 0.0
        if clean_text(metadata.get("canonical_summary"), 800):
            bonus += 0.04
        key_facts = metadata.get("key_facts")
        if isinstance(key_facts, list) and key_facts:
            bonus += min(0.10, 0.025 * len(key_facts))
        topics = metadata.get("topics")
        if isinstance(topics, list) and topics:
            bonus += min(0.05, 0.015 * len(topics))
        if clean_text(metadata.get("sentiment"), 40) in {"positive", "negative"}:
            bonus += 0.03
        source_count = metadata.get("source_memory_count") or metadata.get("summary_event_count")
        try:
            count = int(source_count or 0)
        except Exception:
            count = 0
        if count >= 8:
            bonus += 0.04
        if count >= 20:
            bonus += 0.04
        return min(0.18, bonus)

    @staticmethod
    def _length_bonus(text: str) -> float:
        length = len(text)
        if length >= 800:
            return 0.05
        if length >= 300:
            return 0.035
        if length >= 80:
            return 0.02
        return 0.0

    @staticmethod
    def _confidence_bonus(record: MemoryRecord) -> float:
        try:
            confidence = max(0.0, min(1.0, float(record.confidence)))
        except Exception:
            confidence = 0.5
        return (confidence - 0.5) * 0.10

    @staticmethod
    def _low_value_penalty(compact: str, record: MemoryRecord) -> float:
        if not compact:
            return 0.12
        penalty = 0.0
        low_markers = ("哈哈", "草", "笑死", "嗯嗯", "好的", "收到", "摸摸", "早安", "晚安")
        if len(compact) <= 12 and any(marker in compact for marker in low_markers):
            penalty += 0.10
        if record.lifecycle == "raw_event" and len(compact) <= 24:
            penalty += 0.08
        if "[图片]" in compact or "[语音]" in compact or "[视频]" in compact:
            penalty += 0.04
        return min(0.20, penalty)

    @staticmethod
    def _min_floor(record: MemoryRecord) -> float:
        if record.memory_type in {"manual_memory", "explicit_memory"}:
            return 0.72
        if record.memory_type == "conversation_summary":
            return 0.48
        if record.lifecycle == "stable_memory":
            return 0.30
        return 0.05

    @staticmethod
    def _source_preserved_floor(record: MemoryRecord, base_score: float) -> float:
        memory_type = clean_text(record.memory_type, 120).lower()
        if memory_type in {"manual_memory", "explicit_memory"}:
            return base_score * 0.98
        if memory_type in {"tool_memory", "companion_note"}:
            return base_score * 0.94
        if memory_type == "conversation_summary":
            return base_score * 0.92
        if record.lifecycle == "stable_memory" and record.reality_level == "real_user_fact":
            return base_score * 0.92
        return 0.0

    @staticmethod
    def _max_ceiling(record: MemoryRecord, compact: str) -> float:
        durable_markers = ("记住", "别忘", "喜欢", "生日", "约定", "承诺", "冲突", "和好", "安慰", "作品", "设定", "继续")
        if record.lifecycle == "raw_event" and not any(marker in compact for marker in durable_markers):
            return 0.56
        if record.memory_type == "memory_decay_summary":
            return 0.82
        if record.memory_type in {"manual_memory", "explicit_memory"}:
            return 0.95
        return 0.90
