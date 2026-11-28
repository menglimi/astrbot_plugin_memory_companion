"""吸收外部关系插件塞进请求里的关系提示：她在这人面前是谁。

关系插件（user_tag）会在 on_llm_request 阶段往请求上挂一段临时文本：

    <relation>我在{称呼}面前就是{关系名}：{关系描述}。他补的一句：{备注}。以本条为准。</relation>

它可能夹在 system_prompt 里，也可能躺在 extra_user_content_parts 的文本里。
这一层只做纯文本的拆解与合并，不碰数据库、不发请求、不留状态：
  RELATION_BLOCK_RE        从任意一段文本里抠出 <relation> 块
  relation_from_phrase     从「我在X面前就是Y」里拆出（关系名，称呼）
  parse_relation_hints     把若干段文本变成去重后的候选关系
  merge_relation_profile   把候选并进 identities.profile，用户亲口说的优先

原则只有一条：外部插件的推断只是候选，用户本人说过的关系永远更硬。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Mapping

# 关系是从哪来的：用户亲口说的，还是关系插件在请求里提示的。
RELATION_SOURCE_USER = "user"
RELATION_SOURCE_CONTEXT = "context"

RELATION_MAX_CHARS = 40
ADDRESS_MAX_CHARS = 40
NOTE_MAX_CHARS = 80

# <relation> 块：跨行、非贪婪；前一个块不会把后一个块一起吞掉。
RELATION_BLOCK_RE = re.compile(r"<relation>(.*?)</relation>", re.DOTALL | re.IGNORECASE)

# 视角句：「我在{称呼}面前就是{关系名}」。
_PERSPECTIVE_RE = re.compile(
    r"我在\s*(?P<address>.+?)\s*面前\s*(?:就是|是)\s*(?P<relation>.+?)\s*$"
)

# 块内第一个分句到冒号为止：冒号后面是关系描述，不参与拆名。
_CLAUSE_SPLIT_RE = re.compile(r"[：:]")

# 备注句：「他补的一句：xxx。」——到句号 / 固定后缀 / 行尾为止。
_NOTE_RE = re.compile(
    r"(?:他|她|ta)?\s*补的一句\s*[：:]\s*(?P<note>.*?)(?:以本条为准|[。！？\n]|$)",
    re.DOTALL | re.IGNORECASE,
)

# 代词不是称呼：「我在他面前就是朋友」不该把「他」当人名存下来。
_PRONOUN_ADDRESSES = frozenset({"他", "她", "它", "你", "您", "我", "ta", "对方", "人家", "别人"})

# 外部插件拼出来的称呼 / 关系名未必干净，首尾这些标点一律削掉。
_TRIM_CHARS = " \t\r\n\u3000，。、；：！？,.;:!?·…—－-\"'“”‘’《》【】()（）[]{}「」『』~～"

# merge 时认识的来源：其余来源一律当成插件推断。
_HINT_SOURCES = frozenset({RELATION_SOURCE_USER, RELATION_SOURCE_CONTEXT})


def _clean(value: Any, limit: int) -> str:
    """去掉首尾空白与常见标点，再按上限截断。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return text.strip(_TRIM_CHARS).strip()[: max(1, int(limit))]


def _iter_texts(texts: Any) -> Iterator[str]:
    """把入参摊平成字符串序列；None、非字符串、空串都跳过。"""
    if isinstance(texts, str):
        if texts.strip():
            yield texts
        return
    if texts is None:
        return
    try:
        iterator = iter(texts)
    except TypeError:
        return
    for item in iterator:
        if isinstance(item, str) and item.strip():
            yield item


def relation_from_phrase(phrase: str) -> tuple[str, str]:
    """从「我在{称呼}面前就是{关系名}」这个分句里拆出（关系名, 称呼）。

    只认视角句：没有「我在……面前就是……」的块（例如「恋人：……」）返回
    ("", "")——分不清哪半是关系名、哪半是称呼时，宁可不记，也不瞎猜。
    称呼是代词（他 / 她 / 你 / 我 …）时视同没有称呼。
    """
    text = str(phrase or "").strip()
    if not text:
        return "", ""
    # 只认第一个分句：调用方把整块传进来时，冒号后面的描述不能带偏拆名。
    text = _CLAUSE_SPLIT_RE.split(text, 1)[0].strip()
    match = _PERSPECTIVE_RE.search(text)
    if match is None:
        return "", ""
    relation = _clean(match.group("relation"), RELATION_MAX_CHARS)
    address = _clean(match.group("address"), ADDRESS_MAX_CHARS)
    if address.casefold() in _PRONOUN_ADDRESSES:
        address = ""
    if not relation:
        return "", ""
    return relation, address


def _note_from_block(block: str) -> str:
    """抠出「他补的一句：xxx」里的备注，没有就返回空串。"""
    match = _NOTE_RE.search(block)
    if match is None:
        return ""
    return _clean(match.group("note"), NOTE_MAX_CHARS)


def _parse_relation_hint(block: str) -> dict:
    """拆单个 <relation> 块；关系名为空时由调用方丢弃。"""
    body = str(block or "").strip()
    relation, address = relation_from_phrase(body)
    return {
        "relation": relation,
        "address": address,
        "note": _note_from_block(body),
        "source": RELATION_SOURCE_CONTEXT,
    }


def parse_relation_hints(texts: Iterable[str]) -> list[dict]:
    """把若干段文本里的 <relation> 块拆成去重后的关系候选。

    返回 [{"relation": str, "address": str, "note": str, "source": "context"}]：
      * 只保留能拆出关系名的块（没有视角句的不算）；
      * 同一个 (relation, address) 只留第一次出现的那条，后面的备注不覆盖；
      * 非字符串 / 空文本直接跳过，不抛异常。
    """
    hints: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for text in _iter_texts(texts):
        for match in RELATION_BLOCK_RE.finditer(text):
            hint = _parse_relation_hint(match.group(1))
            if not hint["relation"]:
                continue
            key = (hint["relation"], hint["address"])
            if key in seen:
                continue
            seen.add(key)
            hints.append(hint)
    return hints


def merge_relation_profile(existing: Mapping[str, Any], hint: Mapping[str, Any]) -> dict:
    """把一个关系候选并进 identities.profile 用的字典，返回新 dict。

    规则：
      * 旧 profile 的 relation_source 是 user（用户亲口说的）时整套保留——
        插件推断再新鲜也盖不过本人说法；
      * hint 里为空的字段不覆盖旧值；
      * 入参不改，返回的是新字典；profile 里的其他键原样带走。
    """
    profile: dict = dict(existing) if isinstance(existing, Mapping) else {}
    if str(profile.get("relation_source") or "").strip() == RELATION_SOURCE_USER:
        return profile

    hint_map = hint if isinstance(hint, Mapping) else {}
    relation = _clean(hint_map.get("relation"), RELATION_MAX_CHARS)
    address = _clean(hint_map.get("address"), ADDRESS_MAX_CHARS)
    note = _clean(hint_map.get("note"), NOTE_MAX_CHARS)
    if not (relation or address or note):
        # 空提示不碰旧值，也不刷新 seen_at：没见过东西就不算见过。
        return profile

    if relation:
        profile["relation_label"] = relation
    if address:
        profile["relation_address"] = address
    if note:
        profile["relation_note"] = note
    source = _clean(hint_map.get("source"), 16)
    profile["relation_source"] = source if source in _HINT_SOURCES else RELATION_SOURCE_CONTEXT
    profile["relation_seen_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return profile


__all__ = [
    "RELATION_BLOCK_RE",
    "RELATION_MAX_CHARS",
    "ADDRESS_MAX_CHARS",
    "NOTE_MAX_CHARS",
    "RELATION_SOURCE_USER",
    "RELATION_SOURCE_CONTEXT",
    "relation_from_phrase",
    "parse_relation_hints",
    "merge_relation_profile",
]
