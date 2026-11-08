"""人卡：把"她记得的这个人"拼成一小段，每次开口前放在她眼前。

它回答的不是"聊过什么"，而是"眼前这个人，我认得吗、我对她是什么心"。
名字、称呼、关系、分量、几件要紧的事——够她认出人就行，别把人塞成一堆条目。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .memory_tier import (
    TIER_IMPRINT,
    TIER_IMPORTANT,
    TIER_NORMAL,
    tier_of,
    tier_rank,
)

CARD_OPEN = "<person_memory>"
CARD_CLOSE = "</person_memory>"

TIER_LABELS = {
    TIER_IMPRINT: "刻骨",
    TIER_IMPORTANT: "记得",
    TIER_NORMAL: "印象",
}

SCOPE_LABELS = {
    "private": "私聊",
    "group_member": "群聊",
    "group_shared": "群里",
    "persona_global": "一直",
    "unknown": "",
}


def _text(value: Any, limit: int = 240) -> str:
    """统一清洗：压空白、限长，并把尖括号转义掉。

    人卡是塞进提示词标签块里的，记忆正文里若带 </person_memory> 之类的字面量，
    不转义就等于让人（或别的插件写入的内容）截断这一块、伪造后面的指令。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text[: max(1, int(limit or 240))]


def _first_text(values: Iterable[Any], limit: int = 240, count: int = 6) -> list[str]:
    result: list[str] = []
    for item in values or []:
        text = _text(item, limit)
        if text and text not in result:
            result.append(text)
        if len(result) >= count:
            break
    return result


def _day(value: Any) -> str:
    text = _text(value, 40)
    if not text:
        return ""
    return text[:10]


# 档案里这些键是「记录用的元数据」，不是这个人身上的事，不能当事实念出来。
PROFILE_META_KEYS = {
    "updated_at",
    "created_at",
    "id",
    "person_id",
    "relation_source",
    "relation_seen_at",
    "relation_note_source",
    "source",
    "confidence",
    "platform",
    "user_id",
    "bot_id",
}

PROFILE_LABELS = {
    "display_name": "名字",
    "relation_label": "关系",
    "relation_address": "称呼",
    "relation_note": "相处",
    "occupation": "工作",
    "education": "学业",
    "birthday": "生日",
    "residence": "住哪",
    "zodiac": "星座",
    "blood_type": "血型",
    "preference": "喜欢",
    "dislike": "不喜欢",
    "dietary_restriction": "忌口",
    "habit": "习惯",
    "boundary": "界限",
    "commitment": "约定",
    "health": "身体",
    "schedule": "作息",
    "relation": "关系",
}


def _profile_facts(profile: Any, limit: int = 4) -> list[str]:
    if isinstance(profile, str):
        try:
            import json as _json

            profile = _json.loads(profile)
        except Exception:
            return []
    if not isinstance(profile, Mapping):
        return []
    facts: list[str] = []
    for key, value in profile.items():
        raw_key = _text(key, 40)
        if not raw_key or raw_key in PROFILE_META_KEYS or raw_key.endswith("_at"):
            continue
        name = PROFILE_LABELS.get(raw_key, raw_key)
        if isinstance(value, (list, tuple)):
            text = "、".join(_first_text(value, 60, 4))
        elif isinstance(value, Mapping):
            continue
        else:
            text = _text(value, 120)
        if text:
            facts.append(f"{name}：{text}")
        if len(facts) >= limit:
            break
    return facts


def _anchor_from_row(row: Mapping[str, Any], limit: int = 120) -> dict[str, Any] | None:
    text = _text(row.get("content"), limit)
    if not text:
        return None
    tier = tier_of(row)
    when = _day(row.get("occurred_at")) or _day(row.get("created_at"))
    scope = _text(row.get("scope"), 24)
    return {
        "id": _text(row.get("id"), 64),
        "text": text,
        "tier": tier,
        "when": when,
        "place": SCOPE_LABELS.get(scope, ""),
        "importance": float(row.get("importance") or 0.0),
    }


def build_person_card(
    *,
    user_id: Any = "",
    user_name: Any = "",
    platform: Any = "",
    bot_id: Any = "",
    identity: Mapping[str, Any] | None = None,
    memories: Sequence[Mapping[str, Any]] | None = None,
    preferred_address: Any = "",
    relationship_label: Any = "",
    relationship_score: Any = None,
    relationship_phase: Any = "",
    memory_total: Any = None,
    max_anchors: int = 8,
) -> dict[str, Any]:
    """把散在各处的线索拼成一张卡。缺什么就缺着，别编。"""
    identity = identity if isinstance(identity, Mapping) else {}
    rows = [row for row in (memories or []) if isinstance(row, Mapping)]

    display_name = _text(identity.get("display_name"), 80) or _text(user_name, 80)
    aliases = _first_text(identity.get("aliases") or [], 60, 6)
    if display_name and display_name not in aliases:
        aliases.insert(0, display_name)

    anchors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        anchor = _anchor_from_row(row)
        if not anchor:
            continue
        key = anchor["text"][:48]
        if key in seen:
            continue
        seen.add(key)
        anchors.append(anchor)
    anchors.sort(
        key=lambda item: (
            tier_rank(item["tier"]),
            float(item.get("importance") or 0.0),
            item.get("when") or "",
        ),
        reverse=True,
    )
    anchors = anchors[: max(1, int(max_anchors or 1))]

    dates = sorted(
        {
            _day(row.get("occurred_at")) or _day(row.get("created_at"))
            for row in rows
            if (_day(row.get("occurred_at")) or _day(row.get("created_at")))
        }
    )

    try:
        score_value: int | None = int(relationship_score) if relationship_score is not None else None
    except (TypeError, ValueError):
        score_value = None

    try:
        total_value = int(memory_total) if memory_total is not None else 0
    except (TypeError, ValueError):
        total_value = 0

    return {
        "person_id": _text(identity.get("person_id"), 80) or _text(user_id, 80),
        "user_id": _text(user_id, 80),
        "bot_id": _text(bot_id, 80),
        "platform": _text(platform, 40),
        "display_name": display_name,
        "aliases": aliases,
        "address": _text(preferred_address, 60),
        "relationship_label": _text(relationship_label, 40),
        "relationship_score": score_value,
        "relationship_phase": _text(relationship_phase, 40),
        "first_seen": dates[0] if dates else "",
        "last_seen": dates[-1] if dates else "",
        "memory_count": len(rows),
        "memory_total": max(len(rows), total_value),
        "anchors": anchors,
        "facts": _profile_facts(identity.get("profile")),
    }


def _has_anything(card: Mapping[str, Any]) -> bool:
    return bool(
        card.get("display_name")
        or card.get("aliases")
        or card.get("anchors")
        or card.get("relationship_label")
        or card.get("facts")
    )


def render_person_card(
    card: Mapping[str, Any],
    *,
    max_chars: int = 420,
    max_items: int = 4,
    max_item_chars: int = 90,
) -> str:
    """把卡写成一小段话。超预算就先砍条数、再缩每条，最后只留抬头。"""
    if not isinstance(card, Mapping) or not _has_anything(card):
        return ""

    budget = max(120, int(max_chars or 420))
    items_limit = max(1, int(max_items or 4))

    lines: list[str] = []
    name_line = ""
    if card.get("display_name"):
        name_line = f"名字：{_text(card.get('display_name'), 40)}"
        others = [item for item in card.get("aliases") or [] if item != card.get("display_name")]
        if card.get("address"):
            name_line += f"（她叫你「{_text(card.get('address'), 30)}」）"
        elif others:
            name_line += f"（也叫过：{'、'.join(others[:3])}）"
    elif card.get("address"):
        name_line = f"称呼：{_text(card.get('address'), 30)}"

    relation_bits: list[str] = []
    if card.get("relationship_label"):
        relation_bits.append(_text(card.get("relationship_label"), 20))
    if card.get("relationship_phase"):
        relation_bits.append(_text(card.get("relationship_phase"), 20))
    if card.get("relationship_score") is not None:
        relation_bits.append(f"好感 {card.get('relationship_score')}")
    relation_line = f"关系：{' · '.join(relation_bits)}" if relation_bits else ""

    time_bits: list[str] = []
    if card.get("first_seen"):
        time_bits.append(f"第一次说话 {card.get('first_seen')}")
    if card.get("last_seen"):
        time_bits.append(f"上次说话 {card.get('last_seen')}")
    stored = card.get("memory_total") or card.get("memory_count")
    if stored:
        time_bits.append(f"留着 {stored} 件事")
    time_line = f"时间：{' · '.join(time_bits)}" if time_bits else ""

    for line in (name_line, relation_line, time_line):
        if line:
            lines.append(line)
    if card.get("facts"):
        lines.append("她说过：" + "；".join(_first_text(card.get("facts"), 60, 3)))

    header = "\n".join(lines)
    anchors = list(card.get("anchors") or [])[:items_limit]
    anchor_lines: list[str] = []
    for anchor in anchors:
        text = _text(anchor.get("text"), max(1, int(max_item_chars or 90)))
        if not text:
            continue
        label = TIER_LABELS.get(anchor.get("tier") or TIER_NORMAL, "印象")
        tail_bits = []
        if anchor.get("when"):
            tail_bits.append(str(anchor.get("when")))
        if anchor.get("place"):
            tail_bits.append(str(anchor.get("place")))
        tail = f"（{' · '.join(tail_bits)}）" if tail_bits else ""
        anchor_lines.append(f"- [{label}] {text}{tail}")

    body = header
    if anchor_lines:
        body = body + "\n要紧的事：\n" + "\n".join(anchor_lines)

    block = CARD_OPEN + "\n她记得这个人：\n" + body + "\n" + CARD_CLOSE

    if len(block) <= budget:
        return block

    # 超了就一层层减：先减条数，再缩每条，最后只留抬头。
    for count in range(len(anchor_lines), -1, -1):
        trimmed = header
        if count:
            trimmed = (
                header
                + "\n要紧的事：\n"
                + "\n".join(
                    _text(line, max(24, int(max_item_chars or 90)))
                    for line in anchor_lines[:count]
                )
            )
        candidate = CARD_OPEN + "\n她记得这个人：\n" + trimmed + "\n" + CARD_CLOSE
        if len(candidate) <= budget:
            return candidate
    head_only = CARD_OPEN + "\n" + header + "\n" + CARD_CLOSE
    if len(head_only) <= budget:
        return head_only
    return head_only[:budget]
