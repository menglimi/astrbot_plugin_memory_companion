"""当轮情绪状态：valence / arousal / debt，随时间衰减，被事件更新。

H10 的缺口：检索打分里早就有 `emotional_weight`，但「她此刻是什么情绪」
从来没有被建模过——所以情绪只能来自记忆条目的静态标签，不能来自刚刚发生的事。

这一层补的就是这个缺口，只回答一个问题——「她现在是什么心情」：

  valence  -1..1   此刻偏冷还是偏暖
  arousal   0..1   起伏有多大（越高越冲动，也越不适合长篇大论）
  debt      0..1   心里还欠着多少没说完的（道歉、承诺、委屈的残留）

状态从 `emotion_events` 表里的真实事件聚合（按强度 x 置信度加权、按半衰期衰减），
不新增表、不改 core/store.py；需要落盘时用 to_dict()/from_dict() 塞进 metadata，
或用 save_state()/load_state() 写一个独立小文件。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

EMOTION_STATE_VERSION = "emotion_state.v1"

VALENCE_MIN = -1.0
VALENCE_MAX = 1.0
AROUSAL_MIN = 0.0
AROUSAL_MAX = 1.0
DEBT_MIN = 0.0
DEBT_MAX = 1.0

# 基线：没有事件时她是平静的，不欠谁什么。
BASELINE_VALENCE = 0.0
BASELINE_AROUSAL = 0.0
BASELINE_DEBT = 0.0

# 半衰期。情绪是短命的东西：开心/难过几小时就淡一半；
# 「欠着的那句话」拖得久一点，十二小时才淡一半。
VALENCE_HALF_LIFE_SECONDS = 3 * 3600
AROUSAL_HALF_LIFE_SECONDS = 2 * 3600
DEBT_HALF_LIFE_SECONDS = 12 * 3600

# 衰减到这个幅度以下就直接归位，避免长期拖着 0.0003 的假情绪。
DECAY_FLOOR = 0.01

# 事件类型 -> 情感极性先验。事件自带 valence_hint 时以 hint 为准；
# hint 是 0（很多事件只有类型、没有数值）时才用这张表，否则「hurt」会被当成中性。
EVENT_VALENCE_PRIORS = {
    "neutral": 0.0,
    "hurt": -0.6,
    "apology": 0.1,
    "comfort": 0.4,
    "praise": 0.5,
    "comfort_need": -0.2,
    "external_negative": -0.5,
    "scar_touched": -0.55,
    "warm_memory": 0.5,
    "vulnerable_resonance": 0.2,
    "play": 0.35,
    "intimacy": 0.6,
    "boundary": -0.3,
}

# 修复类事件：它们能抵掉一部分情绪债。
REPAIR_EVENT_TYPES = frozenset({"apology", "comfort", "warm_memory", "play"})

# 加权平均在总权重这么小时还没「攒够」，按比例收缩到基线，
# 免得一条弱事件就把整轮情绪拉满。
MASS_FULL = 1.2

MOOD_LABELS = {
    "calm": "平静",
    "warm": "温和",
    "bright": "雀跃",
    "low": "低落",
    "tense": "憋着事",
}


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def _timestamp(value: Any) -> float | None:
    """把 ISO 字符串 / epoch 秒收成 unix 秒；认不出来就返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        # 毫秒时间戳也认。
        return number / 1000.0 if number > 1e11 else number
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def now_seconds() -> float:
    return datetime.now(timezone.utc).timestamp()


def decay_value(
    value: Any,
    *,
    baseline: float = 0.0,
    elapsed_seconds: Any = 0.0,
    half_life_seconds: Any = VALENCE_HALF_LIFE_SECONDS,
) -> float:
    """指数衰减到基线：过了一个半衰期，离基线的距离剩一半。"""
    try:
        elapsed = float(elapsed_seconds)
    except (TypeError, ValueError):
        elapsed = 0.0
    try:
        half_life = float(half_life_seconds)
    except (TypeError, ValueError):
        half_life = float(VALENCE_HALF_LIFE_SECONDS)
    if not math.isfinite(elapsed) or elapsed <= 0:
        return float(value)
    if not math.isfinite(half_life) or half_life <= 0:
        return float(baseline)
    remaining = math.pow(0.5, elapsed / half_life)
    return baseline + (float(value) - baseline) * remaining


def event_valence(event: Mapping[str, Any]) -> float:
    """这条事件是暖的还是冷的。hint 优先，没有 hint 才看类型先验。"""
    hint = _clamp(event.get("valence_hint"), -1.0, 1.0, 0.0)
    if abs(hint) > 0.01:
        return hint
    event_type = str(event.get("event_type") or "").strip().lower()
    return _clamp(EVENT_VALENCE_PRIORS.get(event_type, 0.0), -1.0, 1.0, 0.0)


def event_arousal(event: Mapping[str, Any]) -> float:
    """起伏：自带 arousal_hint 就用它，否则用强度兜底。"""
    hint = _clamp(event.get("arousal_hint"), 0.0, 1.0, 0.0)
    if hint > 0.01:
        return hint
    return _clamp(_clamp(event.get("intensity"), 0.0, 1.0, 0.0) * 0.6, 0.0, 1.0, 0.0)


def event_strength(event: Mapping[str, Any]) -> float:
    """事件的分量 = 强度 x 置信度。两个都缺时给一个很弱但非零的底。

    什么都没带（没有类型、没有强度、没有极性）的空事件不算数，返回 0。
    """
    if not event:
        return 0.0
    has_type = bool(str(event.get("event_type") or "").strip())
    intensity = _clamp(event.get("intensity"), 0.0, 1.0, 0.0)
    confidence = _clamp(event.get("confidence"), 0.0, 1.0, 0.0)
    if not has_type and intensity <= 0 and confidence <= 0:
        return 0.0
    return (intensity if intensity > 0 else 0.3) * (confidence if confidence > 0 else 0.5)


@dataclass(frozen=True)
class EmotionState:
    """一轮对话里的情绪快照。不可变，更新一律返回新对象。"""

    valence: float = BASELINE_VALENCE
    arousal: float = BASELINE_AROUSAL
    debt: float = BASELINE_DEBT
    updated_at: float = 0.0
    events: int = 0
    confidence: float = 0.0
    source_event_ids: tuple[str, ...] = ()

    def normalized(self) -> "EmotionState":
        return replace(
            self,
            valence=_clamp(self.valence, VALENCE_MIN, VALENCE_MAX, BASELINE_VALENCE),
            arousal=_clamp(self.arousal, AROUSAL_MIN, AROUSAL_MAX, BASELINE_AROUSAL),
            debt=_clamp(self.debt, DEBT_MIN, DEBT_MAX, BASELINE_DEBT),
            events=max(0, int(self.events or 0)),
            confidence=_clamp(self.confidence, 0.0, 1.0, 0.0),
        )

    def decayed(self, now: Any = None) -> "EmotionState":
        """把状态衰减到 now；没有 updated_at（还没开始记）就原样返回。"""
        current = self.normalized()
        target = now_seconds() if now is None else _timestamp(now)
        if target is None or current.updated_at <= 0:
            return current
        elapsed = max(0.0, float(target) - float(current.updated_at))
        if elapsed <= 0:
            return current
        valence = decay_value(
            current.valence,
            baseline=BASELINE_VALENCE,
            elapsed_seconds=elapsed,
            half_life_seconds=VALENCE_HALF_LIFE_SECONDS,
        )
        arousal = decay_value(
            current.arousal,
            baseline=BASELINE_AROUSAL,
            elapsed_seconds=elapsed,
            half_life_seconds=AROUSAL_HALF_LIFE_SECONDS,
        )
        debt = decay_value(
            current.debt,
            baseline=BASELINE_DEBT,
            elapsed_seconds=elapsed,
            half_life_seconds=DEBT_HALF_LIFE_SECONDS,
        )
        if abs(valence - BASELINE_VALENCE) < DECAY_FLOOR:
            valence = BASELINE_VALENCE
        if abs(arousal - BASELINE_AROUSAL) < DECAY_FLOOR:
            arousal = BASELINE_AROUSAL
        if abs(debt - BASELINE_DEBT) < DECAY_FLOOR:
            debt = BASELINE_DEBT
        return replace(current, valence=valence, arousal=arousal, debt=debt, updated_at=float(target))

    def to_dict(self) -> dict[str, Any]:
        state = self.normalized()
        return {
            "schema_version": EMOTION_STATE_VERSION,
            "valence": round(state.valence, 4),
            "arousal": round(state.arousal, 4),
            "debt": round(state.debt, 4),
            "updated_at": float(state.updated_at or 0.0),
            "events": int(state.events or 0),
            "confidence": round(state.confidence, 4),
            "source_event_ids": list(state.source_event_ids),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "EmotionState":
        """老数据 / 坏数据都收：认不出来就回到基线，绝不抛。"""
        source = value if isinstance(value, Mapping) else {}
        raw_ids = source.get("source_event_ids")
        ids: list[str] = []
        if isinstance(raw_ids, (list, tuple)):
            for item in raw_ids[:12]:
                text = str(item or "").strip()[:96]
                if text and text not in ids:
                    ids.append(text)
        updated = _timestamp(source.get("updated_at"))
        try:
            events = max(0, int(source.get("events") or 0))
        except (TypeError, ValueError):
            events = 0
        return cls(
            valence=_clamp(source.get("valence"), VALENCE_MIN, VALENCE_MAX, BASELINE_VALENCE),
            arousal=_clamp(source.get("arousal"), AROUSAL_MIN, AROUSAL_MAX, BASELINE_AROUSAL),
            debt=_clamp(source.get("debt"), DEBT_MIN, DEBT_MAX, BASELINE_DEBT),
            updated_at=float(updated or 0.0),
            events=events,
            confidence=_clamp(source.get("confidence"), 0.0, 1.0, 0.0),
            source_event_ids=tuple(ids),
        )


def baseline_state() -> EmotionState:
    return EmotionState()


def state_from_events(
    events: Iterable[Any] | None,
    *,
    now: Any = None,
    half_life_seconds: float = VALENCE_HALF_LIFE_SECONDS,
) -> EmotionState:
    """把一串真实事件压成一个情绪状态。

    每条的权重 = 强度 x 置信度 x 半衰期衰减；valence / arousal 取加权平均，
    总权重不够时向基线收缩（一条弱事件不会把整轮情绪拉满）；debt 只由负向事件
    累积，修复类事件能抵掉一部分。
    """
    current = now_seconds() if now is None else (_timestamp(now) or now_seconds())
    total_weight = 0.0
    valence_mass = 0.0
    arousal_mass = 0.0
    debt_mass = 0.0
    ids: list[str] = []
    count = 0
    for raw in list(events or [])[:64]:
        event = raw if isinstance(raw, Mapping) else {}
        if not event:
            continue
        strength = event_strength(event)
        if strength <= 0:
            continue
        occurred = _timestamp(event.get("occurred_at"))
        age = max(0.0, current - occurred) if occurred is not None else 0.0
        weight = strength * math.pow(0.5, age / max(1.0, float(half_life_seconds)))
        if weight <= 0:
            continue
        valence = event_valence(event)
        arousal = event_arousal(event)
        vulnerability = _clamp(event.get("vulnerability_hint"), 0.0, 1.0, 0.0)
        total_weight += weight
        valence_mass += weight * valence
        arousal_mass += weight * arousal
        if valence < 0:
            debt_mass += weight * abs(valence) * (1.0 + 0.5 * vulnerability)
        elif str(event.get("event_type") or "").strip().lower() in REPAIR_EVENT_TYPES:
            debt_mass -= 0.7 * weight * abs(valence)
        count += 1
        event_id = str(event.get("event_id") or "").strip()[:96]
        if event_id and event_id not in ids and len(ids) < 12:
            ids.append(event_id)

    if total_weight <= 0:
        return EmotionState(updated_at=float(current))

    shrink = min(1.0, total_weight / MASS_FULL)
    valence = BASELINE_VALENCE + shrink * (valence_mass / total_weight)
    arousal = BASELINE_AROUSAL + shrink * (arousal_mass / total_weight)
    debt = BASELINE_DEBT + 0.8 * max(0.0, debt_mass)
    confidence = min(1.0, total_weight / 2.0)
    return EmotionState(
        valence=_clamp(valence, VALENCE_MIN, VALENCE_MAX, BASELINE_VALENCE),
        arousal=_clamp(arousal, AROUSAL_MIN, AROUSAL_MAX, BASELINE_AROUSAL),
        debt=_clamp(debt, DEBT_MIN, DEBT_MAX, BASELINE_DEBT),
        updated_at=float(current),
        events=count,
        confidence=confidence,
        source_event_ids=tuple(ids),
    )


def apply_event(state: Any, event: Any, *, now: Any = None) -> EmotionState:
    """一条新事件进来：先按时间衰减旧状态，再按事件分量做指数滑动更新。"""
    base = state if isinstance(state, EmotionState) else EmotionState.from_dict(state)
    current = now_seconds() if now is None else (_timestamp(now) or now_seconds())
    decayed = base.decayed(current)
    payload = event if isinstance(event, Mapping) else {}
    strength = event_strength(payload)
    if strength <= 0:
        return decayed
    alpha = _clamp(0.15 + 0.55 * strength, 0.15, 0.7, 0.15)
    valence = event_valence(payload)
    arousal = event_arousal(payload)
    vulnerability = _clamp(payload.get("vulnerability_hint"), 0.0, 1.0, 0.0)
    new_valence = decayed.valence + (valence - decayed.valence) * alpha
    new_arousal = decayed.arousal + (arousal - decayed.arousal) * alpha
    new_debt = decayed.debt
    if valence < 0:
        new_debt += 0.5 * strength * abs(valence) * (1.0 + 0.5 * vulnerability)
    elif str(payload.get("event_type") or "").strip().lower() in REPAIR_EVENT_TYPES:
        new_debt -= 0.6 * strength * abs(valence)
    ids = list(decayed.source_event_ids)
    event_id = str(payload.get("event_id") or "").strip()[:96]
    if event_id and event_id not in ids:
        ids = (ids + [event_id])[-12:]
    return EmotionState(
        valence=_clamp(new_valence, VALENCE_MIN, VALENCE_MAX, BASELINE_VALENCE),
        arousal=_clamp(new_arousal, AROUSAL_MIN, AROUSAL_MAX, BASELINE_AROUSAL),
        debt=_clamp(new_debt, DEBT_MIN, DEBT_MAX, BASELINE_DEBT),
        updated_at=float(current),
        events=max(1, decayed.events + 1),
        confidence=min(1.0, decayed.confidence + 0.25 * strength),
        source_event_ids=tuple(ids),
    )


async def state_for_session(
    store: Any,
    *,
    bot_id: str = "",
    session_id: str = "",
    limit: int = 20,
    now: Any = None,
) -> EmotionState:
    """从现有 store 读最近的情绪事件，压成当轮状态（检索/注入的接入口）。

    只依赖 store.list_emotion_events，不需要新表、不改 store.py；
    store 没有这个方法（老版本/替身）时安静地回到基线。
    """
    reader = getattr(store, "list_emotion_events", None)
    if not callable(reader):
        return baseline_state()
    try:
        rows = await reader(bot_id=bot_id, session_id=session_id, limit=max(1, min(200, int(limit or 20))))
    except Exception:
        return baseline_state()
    return state_from_events(rows, now=now)


def mood_label(state: Any) -> str:
    """一句话档位：calm / warm / bright / low / tense。"""
    snapshot = state if isinstance(state, EmotionState) else EmotionState.from_dict(state)
    snapshot = snapshot.normalized()
    if snapshot.debt >= 0.5:
        return "tense"
    if snapshot.valence <= -0.3:
        return "low"
    if snapshot.valence >= 0.35 and snapshot.arousal >= 0.4:
        return "bright"
    if snapshot.valence >= 0.15:
        return "warm"
    return "calm"


def describe(state: Any) -> str:
    """给人看的一句（面板/调试用），不出现小数和英文枚举。"""
    snapshot = state if isinstance(state, EmotionState) else EmotionState.from_dict(state)
    snapshot = snapshot.normalized()
    label = MOOD_LABELS[mood_label(snapshot)]
    if snapshot.debt >= 0.5:
        return f"{label}，心里还欠着一句没说完的话"
    if snapshot.arousal >= 0.55:
        return f"{label}，起伏比平时大"
    return label


def save_state(path: str | Path, state: Any) -> bool:
    """落到一个独立小文件（原子替换）。失败只返回 False，不打断对话。"""
    payload = state if isinstance(state, EmotionState) else EmotionState.from_dict(state)
    target = Path(path)
    temp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(payload.to_dict(), ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target)
        return True
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def load_state(path: str | Path) -> EmotionState:
    """读回状态；文件不在或坏了都回到基线，绝不抛。"""
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return baseline_state()
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return baseline_state()
    return EmotionState.from_dict(parsed)


__all__ = [
    "AROUSAL_HALF_LIFE_SECONDS",
    "BASELINE_AROUSAL",
    "BASELINE_DEBT",
    "BASELINE_VALENCE",
    "DEBT_HALF_LIFE_SECONDS",
    "EMOTION_STATE_VERSION",
    "EVENT_VALENCE_PRIORS",
    "EmotionState",
    "MOOD_LABELS",
    "REPAIR_EVENT_TYPES",
    "VALENCE_HALF_LIFE_SECONDS",
    "apply_event",
    "baseline_state",
    "decay_value",
    "describe",
    "event_arousal",
    "event_strength",
    "event_valence",
    "load_state",
    "mood_label",
    "now_seconds",
    "save_state",
    "state_for_session",
    "state_from_events",
]
