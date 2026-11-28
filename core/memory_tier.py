"""记忆的轻重分层：刻骨的留住原文，日常的到时候模糊。

这一层只回答一个问题——"这条记忆，她该记多久"。
答案不看时间，看它在两个人的关系里有多重：
  imprint   刻骨的（亲密、承诺、第一次、吵过又和好）——原文留着，永不归档
  important 要紧的（她明确说喜欢/在意/发生过什么）——留得久，慢慢模糊
  normal    日常的——照常衰减

落库时算一次（写入漏斗唯一），归档时再看一眼（归档 SQL 豁免）。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

TIER_IMPRINT = "imprint"
TIER_IMPORTANT = "important"
TIER_NORMAL = "normal"
TIER_CHOICES = (TIER_IMPRINT, TIER_IMPORTANT, TIER_NORMAL)

DURABILITY_BY_TIER = {
    TIER_IMPRINT: "pinned",
    TIER_IMPORTANT: "durable",
    TIER_NORMAL: "normal",
}

TIER_BY_DURABILITY = {
    "pinned": TIER_IMPRINT,
    "durable": TIER_IMPORTANT,
    "normal": TIER_NORMAL,
    "short": TIER_NORMAL,
    "ephemeral": TIER_NORMAL,
}

PROTECTED_TAGS = frozenset({"manual", "protected", "keep", "no_decay"})

# 亲密 / 身体 —— 用户要的是"这种话保留原文"：原话怎么说的，就怎么留着。
# 注意：不收单字「胸/床/裸/脱」。它们会把「胸牌」「胸闷」「脱发」「裸色」
# 「硬床」这类日常话误判成刻骨记忆，而一旦判错就被钉成永不归档（S9/S10）。
INTIMATE_MARKERS = (
    "做爱", "上床", "床事", "同床", "床上", "睡你", "睡我", "和你睡", "抱你睡",
    "亲你", "舌吻", "深吻", "摸你", "摸我", "你的身体", "我的身体",
    "赤裸", "裸体", "全裸", "脱衣", "脱光", "脱下", "脱掉", "内衣", "内裤", "高潮",
    "呻吟", "喘息", "色色", "涩涩", "性欲", "发情", "湿了", "硬了", "射了",
    "想要你", "占有你", "舔", "吻你", "胸部", "摸胸", "揉胸", "胸罩", "腿间",
    "怀孕", "避孕", "套子", "调教", "抱我", "抱着我", "撒娇要",
)

# 承诺 / 誓言 —— 说出口的话，比心情重要。
COMMITMENT_MARKERS = (
    "答应你", "答应我", "我保证", "我发誓", "发誓", "承诺", "约定", "说好了",
    "不会离开", "不会丢下", "永远", "一直陪", "陪着你", "等着你", "回来找你",
    "不会忘", "记住", "别忘",
)

# 里程碑 —— 第一次，是回头能看见的路标。
MILESTONE_MARKERS = (
    "第一次", "初见", "初次", "定情", "告白", "在一起", "纪念日", "生日",
)

# 冲突 / 和好 —— 有过裂缝又补上的地方，最不该忘。
CONFLICT_MARKERS = (
    "吵架", "吵了", "冷战", "生气", "委屈", "道歉", "对不起", "和好", "原谅",
    "误会", "哭", "难过", "受伤", "不安",
)

IMPRINT_MARKERS = (
    INTIMATE_MARKERS + COMMITMENT_MARKERS + MILESTONE_MARKERS + CONFLICT_MARKERS
)

# 这些类型的记忆本身就是"她自己决定要记住的"，进来就高一档。
STRONG_MEMORY_TYPES = frozenset(
    {
        "manual_memory",
        "explicit_memory",
        "assertion",
        "user_preference",
        "relationship_claim",
        "core_memory",
    }
)


def compact(text: Any, limit: int = 4000) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value[: max(1, int(limit or 4000))]


def marker_hits(text: str, markers: Iterable[str]) -> int:
    """数"命中了几个不同的说法"，长词优先，避免「上床」连带「床」算两次。"""
    if not text:
        return 0
    remaining = text
    hits = 0
    for marker in sorted((m for m in markers if m), key=len, reverse=True):
        if marker in remaining:
            hits += 1
            # 命中过的片段不再参与后面的匹配：短语重叠不该重复计分。
            remaining = remaining.replace(marker, "\u0000")
    return hits


def classify_tier(
    content: Any,
    *,
    memory_type: str = "",
    durability: str = "normal",
    importance: float = 0.0,
    tags: Iterable[Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """定这条记忆的档位。已经被人为标高的不往回降。"""
    declared = str(durability or "").strip().lower()
    meta = metadata if isinstance(metadata, Mapping) else {}
    recorded = str(meta.get("memory_tier") or "").strip().lower()
    memory_type_key = str(memory_type or "").strip().lower()
    # 只有「人手动定的档」才不可推翻（S10）。自动算出来的档位每次都重算，
    # 这样规则改严以后，以前的误判能被改回来，而不是永久钉死。
    # 人工痕迹：管理端钉的核心记忆、显式加的保护标签、或此前被标记 manual。
    manual_mark = bool(meta.get("memory_tier_manual"))
    if str(meta.get("managed_by") or "").strip().lower() in {"memory_panel", "panel", "user"}:
        manual_mark = True
    if memory_type_key == "core_memory":
        manual_mark = True
    if recorded in TIER_CHOICES and manual_mark:
        return recorded
    # 记过档位（哪怕是 pinned 这种物化结果）说明它当初是按内容判出来的，
    # 允许按新规则重算；只有「从没记过档位」的记录才拿 durability 兜底。
    if recorded not in TIER_CHOICES and declared in {"pinned", "durable"}:
        return TIER_BY_DURABILITY[declared]

    tag_set = {str(tag).strip().casefold() for tag in (tags or []) if str(tag).strip()}
    if tag_set & PROTECTED_TAGS:
        return TIER_IMPRINT

    text = compact(content)
    if not text:
        return TIER_NORMAL

    strong_type = str(memory_type or "").strip().lower() in STRONG_MEMORY_TYPES
    intimate = marker_hits(text, INTIMATE_MARKERS)
    commitment = marker_hits(text, COMMITMENT_MARKERS)
    milestone = marker_hits(text, MILESTONE_MARKERS)
    conflict = marker_hits(text, CONFLICT_MARKERS)

    # 一个词不算数：真实库里「床」「抱我」这种词一天能出现几十次，
    # 单命中就钉住会把八成摘要变成永不松动的石头（实测 imprint 曾冲到 1269 条、
    # 占可检索行的 18%）。所以亲密/承诺都要攒够分量，且多数档位要求
    # 这条记忆本身是她「决定要记住的」类型（strong_type）。
    if intimate >= 2:
        return TIER_IMPRINT
    # S9：一个亲密词 + 「她自己决定要记住的类型」不再直接钉成刻骨。
    # 那条短路径等于让一条消息就能把记忆推到 imprint → pinned → 永不归档，
    # 判错一次就再也改不回来。现在要求两个互相独立的信号：
    #   * 亲密 + 承诺/里程碑（两个不同类别的内容信号），或
    #   * 她自己决定要记住的类型 + 亲密 + 冲突（吵过又和好的那种）。
    # 冲突词（生气/难过/哭）在摘要里太常见，所以单独配亲密词不够，
    # 必须再加 strong_type，否则日常摘要会被误判成刻骨。
    if intimate >= 1 and (commitment >= 1 or milestone >= 1):
        return TIER_IMPRINT
    if strong_type and intimate >= 1 and conflict >= 1:
        return TIER_IMPRINT
    if commitment >= 3:
        return TIER_IMPRINT
    if milestone and commitment >= 2:
        return TIER_IMPRINT
    if milestone and strong_type:
        return TIER_IMPRINT
    if conflict >= 2 and strong_type:
        return TIER_IMPRINT

    # importance 不再用来抬档：真实库里 68% 的行拥挤在 0.8-0.9（天花板饱和），
    # 拿它当「重要」判据等于所有记忆一样重要，也就等于没有轻重。
    if strong_type:
        return TIER_IMPORTANT
    if commitment >= 2:
        return TIER_IMPORTANT
    if milestone >= 2:
        return TIER_IMPORTANT
    if milestone and conflict:
        return TIER_IMPORTANT
    return TIER_NORMAL


def durability_for_tier(tier: str) -> str:
    return DURABILITY_BY_TIER.get(str(tier or "").strip().lower(), "normal")


def tier_of(memory: Mapping[str, Any] | None) -> str:
    """从一行记忆里读出档位。"""
    if not isinstance(memory, Mapping):
        return TIER_NORMAL
    metadata = memory.get("metadata")
    if isinstance(metadata, str):
        try:
            import json as _json

            metadata = _json.loads(metadata)
        except Exception:
            metadata = None
    if isinstance(metadata, Mapping):
        recorded = str(metadata.get("memory_tier") or "").strip().lower()
        if recorded in TIER_CHOICES:
            return recorded
    return TIER_BY_DURABILITY.get(str(memory.get("durability") or "").strip().lower(), TIER_NORMAL)


def tier_rank(tier: str) -> int:
    order = {TIER_NORMAL: 1, TIER_IMPORTANT: 2, TIER_IMPRINT: 3}
    return order.get(str(tier or "").strip().lower(), 1)


def is_protected_from_retention(
    *,
    durability: Any = "",
    tags: Iterable[Any] | None = None,
    metadata: Any = None,
) -> bool:
    """这条记忆能不能被清理掉（归档/过期）。"""
    if str(durability or "").strip().lower() in {"pinned", "durable"}:
        return True
    tag_set = {str(tag).strip().casefold() for tag in (tags or []) if str(tag).strip()}
    if tag_set & PROTECTED_TAGS:
        return True
    if isinstance(metadata, Mapping):
        tier = str(metadata.get("memory_tier") or "").strip().lower()
        if tier in {TIER_IMPRINT, TIER_IMPORTANT}:
            return True
        if metadata.get("keep_forever"):
            return True
    return False


def apply_tier_to_record(record: Any) -> str:
    """在写入漏斗里给记录定档：只升不降，并记下档位。"""
    try:
        tier = classify_tier(
            getattr(record, "content", ""),
            memory_type=str(getattr(record, "memory_type", "") or ""),
            durability=str(getattr(record, "durability", "normal") or "normal"),
            importance=float(getattr(record, "importance", 0.0) or 0.0),
            tags=getattr(record, "tags", None),
            metadata=getattr(record, "metadata", None),
        )
    except Exception:
        return TIER_NORMAL

    metadata = getattr(record, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        try:
            record.metadata = metadata
        except Exception:
            return tier
    metadata["memory_tier"] = tier
    # 人手动定的档打个记号，之后不再被自动重算推翻；自动档位不记号，允许修正。
    protected = bool(metadata.get("memory_tier_manual"))
    try:
        tag_set = {str(tag).strip().casefold() for tag in (getattr(record, "tags", None) or [])}
    except Exception:
        tag_set = set()
    if tier == TIER_IMPRINT and (tag_set & PROTECTED_TAGS):
        metadata["memory_tier_manual"] = True
        protected = True

    current = str(getattr(record, "durability", "normal") or "normal").strip().lower()
    wanted = durability_for_tier(tier)
    rank = {"ephemeral": 0, "short": 1, "normal": 2, "durable": 3, "pinned": 4}
    # 升档永远允许；降档只允许「自动算的档位」——手动钉住的不动（S10）。
    if rank.get(wanted, 2) > rank.get(current, 2):
        try:
            record.durability = wanted
        except Exception:
            pass
    elif rank.get(wanted, 2) < rank.get(current, 2) and not protected:
        try:
            record.durability = wanted
        except Exception:
            pass
    return tier
