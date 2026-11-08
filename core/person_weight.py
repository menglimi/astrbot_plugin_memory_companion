"""她在心里给一个人留多大位置。

这一层只回答一个问题——「这个人对我要紧吗」。

不看时间：时间只是背景，不会让一个人凭空变重或变轻。
看的是处出来的东西：认识多久、说过多少、有没有刻骨的事、吵过还是只是照面。

算出来的分数是 0-100，落成六个档位（路过的人 → 刻骨的那一个）。
分数可以被她自己改口（用户说「我们没那么熟」就下调），但不会归零：
一个人只要留下过记忆，就不会从她心里消失，只会变淡。

这个模块不碰数据库，纯函数；落库与刷新在 core/store.py 的 person_weights 表。
"""

from __future__ import annotations

from typing import Any, Mapping

# 六个档位，从轻到重。名字要能直接说出口，不要用「tier_1」这种。
BAND_STRANGER = "stranger"
BAND_ACQUAINTANCE = "acquaintance"
BAND_FAMILIAR = "familiar"
BAND_CLOSE = "close"
BAND_IMPORTANT = "important"
BAND_IMPRINT = "imprint"
BAND_CHOICES = (
    BAND_STRANGER,
    BAND_ACQUAINTANCE,
    BAND_FAMILIAR,
    BAND_CLOSE,
    BAND_IMPORTANT,
    BAND_IMPRINT,
)

# 档位分界（含下界）：0-9 路过，10-24 认识，25-44 熟，45-64 亲近，65-84 重要，85+ 刻骨。
BAND_THRESHOLDS = (
    (85, BAND_IMPRINT),
    (65, BAND_IMPORTANT),
    (45, BAND_CLOSE),
    (25, BAND_FAMILIAR),
    (10, BAND_ACQUAINTANCE),
    (0, BAND_STRANGER),
)

# 给人看的一句话（人卡、注入都用这个，不要给用户看数字）。
BAND_LABELS = {
    BAND_STRANGER: "路过的人",
    BAND_ACQUAINTANCE: "认识的人",
    BAND_FAMILIAR: "熟人",
    BAND_CLOSE: "亲近的人",
    BAND_IMPORTANT: "很重要的人",
    BAND_IMPRINT: "刻骨的人",
}

# 档位 → 衰减快慢系数：重的人门槛拉长，轻的人更快淡掉，但都有底。
# 乘在 min_age / min_idle 上（normal 档 1.0）。
BAND_DECAY_FACTOR = {
    BAND_STRANGER: 0.55,
    BAND_ACQUAINTANCE: 0.75,
    BAND_FAMILIAR: 1.0,
    BAND_CLOSE: 1.35,
    BAND_IMPORTANT: 1.7,
    BAND_IMPRINT: 2.4,
}

# 分数上下限。0 分代表「还没记住」，一旦有记忆最低 1 分（不归零）。
WEIGHT_MIN = 0
WEIGHT_MAX = 100


def clamp_weight(value: Any, default: int = 0) -> int:
    """把任何输入收成 0-100 的整数。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(WEIGHT_MIN, min(WEIGHT_MAX, int(round(number))))


def band_of(weight: Any) -> str:
    """分数落在哪个档位。"""
    score = clamp_weight(weight)
    for floor, band in BAND_THRESHOLDS:
        if score >= floor:
            return band
    return BAND_STRANGER


def band_label(band: Any) -> str:
    return BAND_LABELS.get(str(band or "").strip(), BAND_LABELS[BAND_STRANGER])


def decay_factor(weight: Any) -> float:
    """分量换成「她多久才舍得淡掉」。轻的人更快忘，重的人拖得更久。"""
    return BAND_DECAY_FACTOR.get(band_of(weight), 1.0)


def _safe_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(part: float, whole: float) -> float:
    if whole <= 0:
        return 0.0
    return max(0.0, min(1.0, part / whole))


def _evidence_score(value: Any) -> float | None:
    """从 store 传来的证据包里取出 0-1 的净证据强度。

    没有证据包（老调用方、老数据、外部插件）返回 None，调用方按老口径算，
    行为完全不变；有证据包但字段坏了也返回 None，绝不因为解析失败把分数归零。
    """
    if not isinstance(value, Mapping):
        return None
    number = _safe_float(value.get("score"))
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def compute_person_weight(
    *,
    memory_count: Any = 0,
    imprint_count: Any = 0,
    important_count: Any = 0,
    active_days: Any = 0,
    days_since_first: Any = None,
    days_since_last: Any = None,
    conflict_count: Any = 0,
    commitment_count: Any = 0,
    correction: Any = 0,
    source: str = "auto",
    confidence: Any = 1.0,
    evidence: Any = None,
) -> dict[str, Any]:
    """按记忆证据算这个人在她心里的分量。

    四块加起来，最高 100：
      广度 0-25  —— 说过多少（记忆条数，收益递减）
      深度 0-35  —— 有没有刻骨的要紧事
      时间 0-20  —— 认识多久、来过多频繁
      关系 0-20  —— 承诺，加上真实情绪事件算出来的净证据强度
                    （吵过会压、道歉和好会补；没有证据包时退回按冲突计数算）

    然后按「多久没来」轻微打折（最多打八五折，绝不归零），
    再加上用户亲口纠正的修正值 correction（-100 到 100）。
    """
    total_memories = _safe_int(memory_count)
    imprint = _safe_int(imprint_count)
    important = _safe_int(important_count)
    days_known = _safe_float(days_since_first)
    days_idle = _safe_float(days_since_last)
    active = _safe_int(active_days)
    conflicts = _safe_int(conflict_count)
    commitments = _safe_int(commitment_count)
    evidence_strength = _evidence_score(evidence)

    if total_memories <= 0:
        # 一条记忆都没有：既不认识，也不该占位置。
        base = 0.0
        parts = {"breadth": 0.0, "depth": 0.0, "time": 0.0, "bond": 0.0}
    else:
        # 广度：40 条记满一大半，160 条基本顶格，再多也不涨多少。
        breadth = 25.0 * (1.0 - 0.55 ** (total_memories / 40.0))
        breadth = min(25.0, breadth + min(6.0, (total_memories - 1) * 0.15))

        # 深度：刻骨的每条 6 分，要紧的每条 1.2 分，封顶 35。
        depth = min(35.0, imprint * 6.0 + important * 1.2)

        # 时间：认识的天数按 120 天算满 12 分，活跃天数按 60 天算满 8 分。
        known_ratio = _ratio(days_known or 0.0, 180.0)
        active_ratio = _ratio(active, 45.0)
        time_point = min(20.0, known_ratio * 12.0 + active_ratio * 8.0)

        # 关系：一次吵架又和好比十句「你好」重。
        # 有证据包时按真实证据算：evidence_score 是 0-1 的净强度（负面事件已经压过，
        # 修复类事件已经补回），承诺另算；没有证据包时保持老的计数口径不变。
        if evidence_strength is None:
            bond = min(20.0, conflicts * 4.0 + commitments * 2.5)
        else:
            bond = min(20.0, evidence_strength * 20.0 + commitments * 2.5)

        base = breadth + depth + time_point + bond
        parts = {
            "breadth": round(breadth, 2),
            "depth": round(depth, 2),
            "time": round(time_point, 2),
            "bond": round(bond, 2),
        }

    # 久不来的轻微打折：一年没来打八五折，两年也一样（不叠加、不归零）。
    idle_factor = 1.0
    if days_idle is not None and days_idle > 0:
        idle_factor = 1.0 - 0.15 * _ratio(days_idle, 365.0)
    score = base * idle_factor

    correction_value = 0
    try:
        correction_value = int(round(float(correction or 0)))
    except (TypeError, ValueError):
        correction_value = 0
    score += correction_value

    weight = clamp_weight(score)
    if total_memories > 0:
        weight = max(1, weight)
    confidence_value = _safe_float(confidence)
    if confidence_value is None:
        confidence_value = 1.0

    parts["idle_factor"] = round(idle_factor, 3)
    parts["correction"] = correction_value
    parts["memory_count"] = total_memories
    if evidence_strength is not None:
        # 把净证据强度落进 components，人卡/调试面板能看到这次分数是按证据算的。
        parts["evidence"] = round(evidence_strength, 3)

    return {
        "weight": int(weight),
        "band": band_of(weight),
        "band_label": band_label(band_of(weight)),
        "source": str(source or "auto").strip() or "auto",
        "confidence": max(0.0, min(1.0, confidence_value)),
        "components": parts,
    }


def should_update(
    *,
    current_weight: Any = None,
    current_source: str = "",
    new_weight: Any = None,
    new_source: str = "auto",
    delta: int = 3,
) -> bool:
    """这次算出来的分量值不值得写库。

    自动算的分只在变化超过 delta 时才写（避免每轮对话都写一次）；
    用户亲口改过的（source == "user"）不许被上一级的自动值随便冲掉。
    """
    if current_weight is None:
        return True
    if str(current_source or "").strip() == "user" and str(new_source or "") != "user":
        return False
    try:
        return abs(clamp_weight(new_weight) - clamp_weight(current_weight)) >= max(1, int(delta))
    except (TypeError, ValueError):
        return True


def describe(weight: Any) -> str:
    """一句人话，供注入/面板使用，例如「她心里：亲近的人（52）」。"""
    score = clamp_weight(weight)
    return f"{band_label(band_of(score))}（{score}）"


def merge_external_weight(
    local: Mapping[str, Any] | None,
    external_score: Any = None,
    *,
    external_phase: str = "",
    external_source: str = "companion",
) -> dict[str, Any]:
    """外部插件（人形化/关系插件）报来的分量优先于本插件自算。

    没报就用自己的；报了就记下来源，人卡与衰减都用它。
    """
    score = clamp_weight(external_score, default=-1)
    if external_score is None or score < 0:
        return dict(local or {})
    merged = dict(local or {})
    merged["weight"] = score
    merged["band"] = band_of(score)
    merged["band_label"] = band_label(band_of(score))
    merged["source"] = str(external_source or "companion").strip() or "companion"
    if external_phase:
        merged["phase"] = str(external_phase)[:40]
    return merged
