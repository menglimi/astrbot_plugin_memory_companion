from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .astrbot_compat import logger
from .models import MemoryRecord, clean_text


class ImportanceEvaluator:
    """Calibrate memory importance around long-term conversational value."""

    version = "persona_dimensions_v6"
    # S6：重要度特征词表外置到 core/lexicon/importance_lexicon.json。代码里不再
    # 硬编码中文词表与特征权重：词表缺失/损坏时退回「无词表」模式（所有维度
    # 取中性分），只降级、不抛错，保证老部署仍能正常写入记忆。
    LEXICON_FILENAME = "importance_lexicon.json"
    _LEXICON_CACHE: dict[str, Any] | None = None

    def __init__(
        self,
        mention_policy_relax: bool = False,
        *,
        lexicon: dict[str, Any] | None = None,
    ) -> None:
        # mention_policy_relax=False 时行为与历史版本完全一致；
        # 开启后放宽写入侧 mention_policy 的 tone_only 降级（见 _mention_policy）。
        self.mention_policy_relax = mention_policy_relax
        self.lexicon = lexicon if isinstance(lexicon, dict) and lexicon else self._load_lexicon()
        self._semantic_base = self._scoring_value("semantic_base", 0.30)
        self._hit_base = self._scoring_value("hit_base", 0.26)
        self._hit_step = self._scoring_value("hit_step", 0.16)
        self._hit_ceiling = self._scoring_value("hit_ceiling", 0.85)
        # 中性分：词表没命中时给「没有证据」的中性值，而不是 0.0（0.0 等于
        # 明确判定「不含该维度」，会把词表外的正常记忆一起压到底）。
        self._neutral_score = self._scoring_value("neutral_score", 0.12)
        self._marker_ceiling = self._scoring_value("marker_bonus_ceiling", 0.30)
        self._base_mix = self._evaluate_weight("base_mix", 0.52)
        self._semantic_mix = self._evaluate_weight("semantic_mix", 0.48)

    @classmethod
    def _lexicon_path(cls) -> Path:
        return Path(__file__).resolve().with_name("lexicon") / cls.LEXICON_FILENAME

    @classmethod
    def _load_lexicon(cls) -> dict[str, Any]:
        """读取外置词表；失败时返回空词表（降级为中性打分，不抛错）。"""

        if cls._LEXICON_CACHE is not None:
            return cls._LEXICON_CACHE
        data: dict[str, Any] = {}
        try:
            with cls._lexicon_path().open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError("lexicon root must be a JSON object")
            data = loaded
        except Exception as exc:  # noqa: BLE001 - 词表坏了不能让写记忆失败
            logger.warning(
                "[MemoryCompanion] 重要度词表加载失败，降级为无词表中性打分: %s", exc
            )
        cls._LEXICON_CACHE = data
        return data

    def _scoring_value(self, key: str, default: float) -> float:
        scoring = self.lexicon.get("scoring")
        value = scoring.get(key) if isinstance(scoring, dict) else None
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _evaluate_weight(self, key: str, default: float) -> float:
        weights = self.lexicon.get("evaluate_weights")
        value = weights.get(key) if isinstance(weights, dict) else None
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _dimension_markers(self, dimension: str) -> tuple[str, ...]:
        dimensions = self.lexicon.get("dimensions")
        values = dimensions.get(dimension) if isinstance(dimensions, dict) else None
        if not isinstance(values, (list, tuple)):
            return ()
        return tuple(
            text for text in (clean_text(value, 40) for value in values) if text
        )

    def _guard_markers(self, key: str) -> tuple[str, ...]:
        """S6：伤痕/情绪债/关系阶段/持久短语的守卫词表，同样外置可配。"""

        guards = self.lexicon.get("guards")
        values = guards.get(key) if isinstance(guards, dict) else None
        if not isinstance(values, (list, tuple)):
            return ()
        return tuple(
            text for text in (clean_text(value, 40) for value in values) if text
        )

    def calibrate(self, record: MemoryRecord, *, source: str = "") -> MemoryRecord:
        base = self._base_importance(record.importance)
        dimensions = self.persona_dimensions(record)
        # S6：把逐项特征贡献一并写进 metadata，事后可以解释「为什么这条记忆重要」。
        text = self._memory_text(record)
        compact = re.sub(r"\s+", "", text.lower())
        features = self._semantic_features(record, compact, text, dimensions)
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
        metadata["importance_features"] = {
            key: round(value, 4) for key, value in features.items()
        }
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
        # S6：语义分改为「基线 + 逐项命名特征贡献」，权重全部来自外置词表，
        # 并可用 explain() 逐项复盘（旧实现把 12 个加权项串成一坨加法，改不了也看不出）。
        features = self._semantic_features(record, compact, text, dimensions)
        semantic = self._semantic_base + sum(features.values())

        final = base_score * self._base_mix + semantic * self._semantic_mix
        final = max(final, self._source_preserved_floor(record, base_score))
        final = max(self._min_floor(record), min(self._max_ceiling(record, compact), final))
        return round(max(0.0, min(1.0, final)), 3)

    def _semantic_features(
        self,
        record: MemoryRecord,
        compact: str,
        text: str,
        dimensions: dict[str, Any],
    ) -> dict[str, float]:
        """S6：语义分的逐项特征贡献（相加即语义分，正负号自带语义）。"""

        def dimension_weight(name: str) -> float:
            return float(dimensions.get(name, 0.0) or 0.0)

        return {
            "memory_type": self._memory_type_bonus(record),
            "lifecycle": self._lifecycle_bonus(record),
            "markers": self._marker_bonus(compact),
            "metadata": self._metadata_bonus(record),
            "persona": dimension_weight("persona_importance") * self._evaluate_weight("persona", 0.18),
            "freshness": dimension_weight("freshness_weight") * self._evaluate_weight("freshness", 0.05),
            "scar": dimension_weight("scar_weight") * self._evaluate_weight("scar", 0.06),
            "intimacy": dimension_weight("intimacy_weight") * self._evaluate_weight("intimacy", 0.04),
            "vulnerability": dimension_weight("vulnerability_weight") * self._evaluate_weight("vulnerability", 0.05),
            "length": self._length_bonus(text),
            "confidence": self._confidence_bonus(record),
            "low_value": -self._low_value_penalty(compact, record),
        }

    def explain(self, record: MemoryRecord) -> dict[str, Any]:
        """S6：可解释打分——返回每一项特征贡献与最终分，便于排查/调词表。"""

        base = self._base_importance(record.importance)
        dimensions = self.persona_dimensions(record)
        text = self._memory_text(record)
        compact = re.sub(r"\s+", "", text.lower())
        features = self._semantic_features(record, compact, text, dimensions)
        semantic = self._semantic_base + sum(features.values())
        return {
            "version": self.version,
            "lexicon": str(self._lexicon_path()),
            "base_importance": round(base, 3),
            "semantic_base": round(self._semantic_base, 3),
            "features": {key: round(value, 4) for key, value in features.items()},
            "semantic_score": round(semantic, 3),
            "dimensions": dimensions,
            "final": self.evaluate(record, base=base, dimensions=dimensions),
        }

    def persona_dimensions(self, record: MemoryRecord) -> dict[str, Any]:
        text = self._memory_text(record)
        compact = re.sub(r"\s+", "", text.lower())
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        memory_type = clean_text(record.memory_type, 120).lower()
        tags = {clean_text(tag, 80).lower() for tag in record.tags or []}
        occurred_at = self._event_time(record)

        # S6：维度词表已外置到 core/lexicon/importance_lexicon.json，这里只传维度名，
        # 词表命中数与打分曲线由 _dimension_score 统一处理（可解释、可配置）。
        preference = self._dimension_score(compact, "preference")
        relationship = self._dimension_score(compact, "relationship")
        promise = self._dimension_score(compact, "promise")
        open_loop = self._dimension_score(compact, "open_loop")
        creative = self._dimension_score(compact, "creative")
        emotional = self._dimension_score(compact, "emotional")
        self_continuity = self._dimension_score(compact, "self_continuity")
        intimacy = self._dimension_score(compact, "intimacy")
        vulnerability = self._dimension_score(compact, "vulnerability")

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

    def _mention_policy(self, record: MemoryRecord, weights: dict[str, Any]) -> tuple[str, float]:
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
            # relax：Bot 自我时间线背景记忆从 tone_only 提为 soft_echo，让注入侧有内容可用
            if self.mention_policy_relax:
                return "soft_echo", 0.52
            return "tone_only", 0.34
        if max(scar, emotional_debt, emotional) >= 0.66:
            # relax：情绪重的记忆从 tone_only 提为 soft_echo（conversation_summary 主来源）
            if self.mention_policy_relax:
                return "soft_echo", 0.50
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

    def _dimension_score(self, compact: str, dimension: str | tuple[str, ...]) -> float:
        """单个维度的特征分（S6：可解释 + 词表可配）。

        - dimension 传维度名时从 core/lexicon/importance_lexicon.json 取词表；
          传显式词序列时直接用调用方给的词（兼容旧调用）。
        - 未命中任何词返回中性分（默认 0.12）而不是 0.0：0.0 等于「明确判定
          不含该维度」，会把词表之外的正常记忆一起压到最低分；中性分表示
          「没有证据」，既不抬高也不判负。
        """

        if isinstance(dimension, str):
            markers = self._dimension_markers(dimension)
        else:
            markers = tuple(dimension)
        hits = sum(1 for marker in markers if marker and marker in compact)
        if hits <= 0:
            return self._neutral_score
        return min(self._hit_ceiling, self._hit_base + hits * self._hit_step)

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

    def _scar_weight(
        self,
        compact: str,
        relationship: float,
        emotional: float,
        promise: float,
        open_loop: float,
        creative: float,
        phase: str,
    ) -> float:
        scar_markers = self._guard_markers("scar_markers")
        marker_score = 0.22 if any(marker in compact for marker in scar_markers) else 0.0
        if phase in {"conflict", "repair", "comfort"}:
            marker_score += 0.18
        blended = max(emotional * 0.58 + relationship * 0.30, promise * 0.45 + open_loop * 0.35, creative * 0.25)
        return min(0.95, marker_score + blended)

    def _emotional_debt_weight(
        self,
        compact: str,
        emotional: float,
        relationship: float,
        open_loop: float,
        promise: float,
        phase: str,
    ) -> float:
        debt_markers = self._guard_markers("debt_markers")
        marker_score = 0.0
        hits = sum(1 for marker in debt_markers if marker in compact)
        if hits:
            marker_score = min(0.42, 0.18 + hits * 0.08)
        if phase in {"conflict", "repair", "comfort", "sensitive"}:
            marker_score += 0.12
        return min(0.95, marker_score + emotional * 0.44 + relationship * 0.18 + max(open_loop, promise) * 0.20)

    def _relationship_phase(self, compact: str, relationship: float, emotional: float, promise: float) -> str:
        if any(marker in compact for marker in self._guard_markers("phase_conflict")):
            return "conflict"
        if any(marker in compact for marker in self._guard_markers("phase_repair")):
            return "repair"
        if any(marker in compact for marker in self._guard_markers("phase_comfort")):
            return "comfort"
        if any(marker in compact for marker in self._guard_markers("phase_closeness")):
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

    def _marker_bonus(self, compact: str) -> float:
        """S6：关键短语加权，词表与权重读 core/lexicon/importance_lexicon.json。"""

        groups = self.lexicon.get("marker_bonus_groups")
        bonus = 0.0
        if isinstance(groups, (list, tuple)):
            for entry in groups:
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                try:
                    value = float(entry[0])
                except (TypeError, ValueError):
                    continue
                markers = entry[1] if isinstance(entry[1], (list, tuple)) else ()
                if any(
                    marker and clean_text(marker, 40) in compact for marker in markers
                ):
                    bonus += value
        return min(self._marker_ceiling, bonus)

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

    def _low_value_penalty(self, compact: str, record: MemoryRecord) -> float:
        if not compact:
            return 0.12
        penalty = 0.0
        # S6：低信息量词表也外置，改词表不用改代码。
        raw_low = self.lexicon.get("low_value_markers")
        low_markers = (
            tuple(clean_text(marker, 40) for marker in raw_low if clean_text(marker, 40))
            if isinstance(raw_low, (list, tuple))
            else ()
        )
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

    def _max_ceiling(self, record: MemoryRecord, compact: str) -> float:
        durable_markers = self._guard_markers("durable_markers")
        if record.lifecycle == "raw_event" and not any(marker in compact for marker in durable_markers):
            return 0.56
        if record.memory_type == "memory_decay_summary":
            return 0.82
        if record.memory_type in {"manual_memory", "explicit_memory"}:
            return 0.95
        return 0.90
