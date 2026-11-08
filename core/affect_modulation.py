"""Bounded affect modulation DTO shared across companion plugins.

H11：这个文件以前只有 `normalize_affect_modulation` 一个取值函数——名字叫
「情绪调制」，实际是个 DTO。现在它真的调制：

  输入：一个情绪状态（core/emotion_state.EmotionState，或任意带
        valence/arousal/debt 的 Mapping）
  输出：检索权重倍率（emotional_weight 该放大还是缩小）、
        欠账跟进强度（debt_followup_boost）、注入语气档位（tone）

所有输出都夹在固定区间里（倍率 0.7-1.6、语气 0-1），并支持先按时间衰减再调制，
所以情绪再极端也不会把检索权重推到失控，过一段时间会自己回到 1.0。
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any, Mapping

AFFECT_MODULATION_VERSION = "affect_modulation.v1"
AFFECT_MODULATION_FIELDS = ("schema_version", "valence", "arousal", "vulnerability", "confidence", "source_event_ids", "computed_at")
AFFECT_MODULATION_FINGERPRINT = hashlib.sha256("|".join(AFFECT_MODULATION_FIELDS).encode("ascii")).hexdigest()[:20]

# 调制器自己的版本号：DTO 契约（上面的 v1）不动，调制规则另算一版。
AFFECT_MODULATOR_VERSION = "affect_modulator.v1"

# 检索权重倍率的硬边界。低于 0.7 会把情绪当成否决票，高于 1.6 会让情绪盖过相关性。
RETRIEVAL_MULTIPLIER_MIN = 0.7
RETRIEVAL_MULTIPLIER_MAX = 1.6
# 欠账跟进最多额外加这么多分（0-1 归一化后的权重）。
DEBT_FOLLOWUP_BOOST_MAX = 0.35

# 语气档位。
TONE_LABELS = {
    "calm": "平稳",
    "warm": "温和",
    "bright": "轻快",
    "low": "低落",
    "tense": "憋着事",
}
TONE_GUIDANCE = {
    "calm": "语气平稳，正常说话，别刻意煽情。",
    "warm": "可以软一点，多接一句对方的话。",
    "bright": "语气轻快，别铺太长。",
    "low": "先接住情绪，少开玩笑，别急着讲道理。",
    "tense": "别绕开没说完的那件事，先问一句。",
}


def _number(value: Any, default: float, low: float, high: float) -> float:
    if type(value) not in {int, float}:
        return default
    numeric = float(value)
    if not math.isfinite(numeric):
        return default
    return round(max(low, min(high, numeric)), 4)


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return max(low, min(high, numeric))


def normalize_affect_modulation(value: Any) -> dict[str, Any]:
    source = dict(value) if isinstance(value, Mapping) else {}
    raw_ids = source.get("source_event_ids")
    ids: list[str] = []
    if isinstance(raw_ids, (list, tuple)):
        for item in raw_ids[:12]:
            if type(item) is not str:
                continue
            cleaned = " ".join(item.split())[:96]
            if cleaned and cleaned not in ids:
                ids.append(cleaned)
    computed_at = source.get("computed_at")
    return {
        "schema_version": AFFECT_MODULATION_VERSION,
        "valence": _number(source.get("valence"), 0.0, -1.0, 1.0),
        "arousal": _number(source.get("arousal"), 0.0, 0.0, 1.0),
        "vulnerability": _number(source.get("vulnerability"), 0.0, 0.0, 1.0),
        "confidence": _number(source.get("confidence"), 0.0, 0.0, 1.0),
        "source_event_ids": ids,
        "computed_at": float(computed_at) if type(computed_at) in {int, float} and math.isfinite(float(computed_at)) else 0.0,
    }


def _field(state: Any, name: str, default: float) -> float:
    """从 dataclass 或 Mapping 里取一项，取不到就给默认值。"""
    if isinstance(state, Mapping):
        return _clamp(state.get(name), -1.0, 1.0, default)
    return _clamp(getattr(state, name, default), -1.0, 1.0, default)


def _state_tuple(state: Any) -> tuple[float, float, float]:
    """(valence, arousal, debt)，全部先夹到自己的区间。"""
    valence = _clamp(_field(state, "valence", 0.0), -1.0, 1.0, 0.0)
    arousal = _clamp(_field(state, "arousal", 0.0), 0.0, 1.0, 0.0)
    debt = _clamp(_field(state, "debt", 0.0), 0.0, 1.0, 0.0)
    return valence, arousal, debt


def _decayed(state: Any, now: Any) -> Any:
    """状态自己会衰减就先衰减（EmotionState.decayed）；不会就算了。"""
    if now is None:
        return state
    decay = getattr(state, "decayed", None)
    if not callable(decay):
        return state
    try:
        return decay(now)
    except Exception:
        return state


def _computed_at(state: Any, now: Any) -> float:
    """这条情绪读数是什么时候的：优先 now，其次状态自己的 updated_at。"""
    if now is not None:
        if type(now) in {int, float}:
            return float(now)
        if isinstance(now, str):
            try:
                parsed = datetime.fromisoformat(now.strip().replace("Z", "+00:00"))
            except ValueError:
                return 0.0
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        return 0.0
    if isinstance(state, Mapping):
        stamp = state.get("updated_at")
    else:
        stamp = getattr(state, "updated_at", None)
    return float(stamp) if type(stamp) in {int, float} and stamp > 0 else 0.0


def emotional_weight_multiplier(state: Any) -> float:
    """检索时 emotional_weight 该乘多少。

    心里欠着事（debt 高）→ 更愿意翻出相关旧账；
    此刻偏暖 → 略放大；此刻偏冷 → 收一点，别反复揭伤疤；
    起伏大（arousal 高）→ 稍微更愿意想起有情绪的记忆。
    中性状态恒等于 1.0。
    """
    valence, arousal, debt = _state_tuple(state)
    multiplier = (
        1.0
        + 0.45 * debt
        + 0.20 * max(0.0, valence)
        - 0.18 * max(0.0, -valence)
        + 0.15 * arousal
    )
    return round(_clamp(multiplier, RETRIEVAL_MULTIPLIER_MIN, RETRIEVAL_MULTIPLIER_MAX, 1.0), 4)


def debt_followup_boost(state: Any) -> float:
    """「没说完的那件事」该额外加多少分，0 到 0.35。"""
    valence, _arousal, debt = _state_tuple(state)
    boost = 0.30 * debt + 0.08 * max(0.0, -valence)
    return round(_clamp(boost, 0.0, DEBT_FOLLOWUP_BOOST_MAX, 0.0), 4)


def mood_label(state: Any) -> str:
    """语气档位。和 core/emotion_state.mood_label 同口径，但不 import 它，
    这样本模块单独被别的插件引用时也不会拖进一整个包。"""
    valence, arousal, debt = _state_tuple(state)
    if debt >= 0.5:
        return "tense"
    if valence <= -0.3:
        return "low"
    if valence >= 0.35 and arousal >= 0.4:
        return "bright"
    if valence >= 0.15:
        return "warm"
    return "calm"


def tone_profile(state: Any) -> dict[str, Any]:
    """注入语气：warmth（多软）/ brevity（多短）/ 档位与一句可拼进提示词的话。"""
    valence, arousal, debt = _state_tuple(state)
    warmth = _clamp(0.5 + 0.5 * valence - 0.25 * debt, 0.0, 1.0, 0.5)
    brevity = _clamp(0.35 + 0.45 * arousal + 0.2 * debt, 0.0, 1.0, 0.35)
    label = mood_label(state)
    return {
        "label": label,
        "label_text": TONE_LABELS.get(label, TONE_LABELS["calm"]),
        "warmth": round(warmth, 4),
        "brevity": round(brevity, 4),
        "guidance": TONE_GUIDANCE.get(label, TONE_GUIDANCE["calm"]),
    }


def apply_emotional_weight(value: Any, state: Any, *, ceiling: float = 1.0) -> float:
    """把一个 0-1 的 emotional_weight 按当轮情绪调权，并夹在 [0, ceiling]。"""
    base = _clamp(value, 0.0, 1.0, 0.0)
    return round(_clamp(base * emotional_weight_multiplier(state), 0.0, max(0.0, ceiling), 0.0), 4)


def modulate(state: Any, *, now: Any = None) -> dict[str, Any]:
    """一次算完：检索权重倍率 + 欠账跟进 + 注入语气。

    now 给了就先按时间衰减（state 得是 EmotionState 或能 decayed(now) 的对象）。
    """
    effective = _decayed(state, now)
    valence, arousal, debt = _state_tuple(effective)
    affect = normalize_affect_modulation(
        {
            "valence": valence,
            "arousal": arousal,
            "vulnerability": debt,
            "confidence": _clamp(getattr(effective, "confidence", 0.0) if not isinstance(effective, Mapping) else effective.get("confidence"), 0.0, 1.0, 0.0),
            "source_event_ids": list(getattr(effective, "source_event_ids", ()) or ())[:12]
            if not isinstance(effective, Mapping)
            else list(effective.get("source_event_ids") or [])[:12],
            "computed_at": _computed_at(effective, now),
        }
    )
    return {
        "schema_version": AFFECT_MODULATOR_VERSION,
        "affect": affect,
        "retrieval": {
            "emotional_weight_multiplier": emotional_weight_multiplier(effective),
            "debt_followup_boost": debt_followup_boost(effective),
        },
        "tone": tone_profile(effective),
        "source_event_ids": list(affect["source_event_ids"]),
    }


__all__ = [
    "AFFECT_MODULATION_FIELDS",
    "AFFECT_MODULATION_FINGERPRINT",
    "AFFECT_MODULATION_VERSION",
    "AFFECT_MODULATOR_VERSION",
    "DEBT_FOLLOWUP_BOOST_MAX",
    "RETRIEVAL_MULTIPLIER_MAX",
    "RETRIEVAL_MULTIPLIER_MIN",
    "TONE_GUIDANCE",
    "TONE_LABELS",
    "apply_emotional_weight",
    "debt_followup_boost",
    "emotional_weight_multiplier",
    "modulate",
    "mood_label",
    "normalize_affect_modulation",
    "tone_profile",
]
