from __future__ import annotations

import re
from dataclasses import dataclass

from .models import clean_text


@dataclass(slots=True)
class TurnSignal:
    kind: str = "normal"
    low_information: bool = False
    reason: str = ""
    terms: list[str] | None = None
    context_dependent: bool = False
    standalone_request: bool = False


AFFECTION_CHARS = "摸贴抱蹭亲揉拍戳"
AFFECTION_UNITS = (
    "摸摸",
    "贴贴",
    "抱抱",
    "蹭蹭",
    "亲亲",
    "揉揉",
    "拍拍",
    "戳戳",
    "rua",
)
AFFECTION_TARGETS = {
    "你",
    "你呀",
    "你哦",
    "星缘",
    "缘缘",
    "诺星缘",
    "小星缘",
    "小缘",
    "宝宝",
    "宝贝",
    "老婆",
    "姐姐",
    "妹妹",
    "头",
    "脑袋",
}
AFFECTION_TARGET_SUFFIXES = ("酱", "宝", "宝宝", "宝贝", "老婆")
REACTION_TOKENS = {
    "嗯",
    "嗯嗯",
    "啊",
    "哦",
    "噢",
    "好",
    "好的",
    "行",
    "草",
    "乐",
    "哈",
    "哈哈",
    "哈哈哈",
    "？",
    "?",
    "什么",
    "啥",
}
CORRECTION_TOKENS = {
    "不对",
    "不是",
    "错了",
    "不对吧",
    "不是吧",
    "不对啊",
    "不是啊",
    "不对呀",
    "不是呀",
    "并不是",
    "没错",
}
CORRECTION_MARKERS = (
    "你说错",
    "说错了",
    "答错了",
    "不是这个",
    "不是这样",
    "不对劲",
    "理解错",
    "搞错了",
    "记错了",
)
CONTEXT_DEPENDENT_MARKERS = (
    "刚才",
    "上面",
    "前面",
    "上一",
    "这",
    "那",
    "它",
    "他",
    "她",
    "继续",
    "接着",
    "再来",
    "再发",
    "再画",
    "也来",
    "同样",
    "换个",
    "还有",
    "为什么",
    "咋回事",
    "怎么回事",
    "啥意思",
)
STANDALONE_REQUEST_MARKERS = (
    "发一张",
    "来一张",
    "给我来",
    "给我发",
    "自拍",
    "自拍照",
    "照片",
    "图片",
    "人设图",
    "参考图",
    "上传",
    "生成",
    "画",
    "搜索",
    "查询",
    "查一下",
    "总结",
    "解释",
    "修",
    "改",
)
TERM_STOPWORDS = {
    "给我",
    "你的",
    "一张",
    "一下",
    "这个",
    "那个",
    "什么",
    "怎么",
    "为什么",
    "可以",
    "是不是",
    "有没有",
    "知道",
    "当前",
    "用户",
}


def analyze_turn_signal(text: str) -> TurnSignal:
    compact = _compact_message(text)
    terms = message_terms(text)
    context_dependent = _has_context_dependent_marker(compact)
    standalone_request = _has_standalone_request_marker(compact)
    if not compact:
        return TurnSignal(kind="empty", low_information=True, reason="empty_message", terms=terms)
    if _is_affection_only(compact):
        return TurnSignal(kind="affection", low_information=True, reason="affection_only", terms=terms)
    if _is_reaction_only(compact):
        return TurnSignal(kind="reaction", low_information=True, reason="reaction_only", terms=terms)
    if _is_correction_only(compact):
        return TurnSignal(
            kind="correction",
            low_information=True,
            context_dependent=True,
            reason="correction_only",
            terms=terms,
        )
    return TurnSignal(
        terms=terms,
        context_dependent=context_dependent,
        standalone_request=standalone_request,
    )


def _compact_message(text: str) -> str:
    value = clean_text(text, 1200)
    value = re.sub(r"\[At:\d+\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"@\S+", "", value)
    value = re.sub(r"[\s,，。.!！~～…、:：;；\"'“”‘’()（）\[\]【】<>《》]+", "", value)
    return value.lower()


def _is_affection_only(compact: str) -> bool:
    if not compact:
        return False
    rest = compact
    for unit in AFFECTION_UNITS:
        rest = rest.replace(unit, "")
    if not rest:
        return True
    if _is_affection_target(rest):
        return True
    if len(compact) >= 2 and all(ch in AFFECTION_CHARS for ch in compact):
        return True
    return False


def _is_affection_target(rest: str) -> bool:
    if not rest:
        return True
    if rest in AFFECTION_TARGETS:
        return True
    if len(rest) <= 4 and re.fullmatch(r"[\u4e00-\u9fff]+", rest):
        if len(rest) == 2 and rest[0] == rest[1]:
            return True
        if any(rest.endswith(suffix) for suffix in AFFECTION_TARGET_SUFFIXES):
            return True
    return False


def _is_reaction_only(compact: str) -> bool:
    if compact in REACTION_TOKENS:
        return True
    if len(compact) <= 12 and re.fullmatch(r"(哈|呵|嘿|嘻|嗯|啊|哦|噢|唔|哇|草|乐)+", compact):
        return True
    return False


def _is_correction_only(compact: str) -> bool:
    if compact in CORRECTION_TOKENS:
        return True
    return len(compact) <= 12 and any(marker in compact for marker in CORRECTION_MARKERS)


def message_terms(text: str, *, limit: int = 40) -> list[str]:
    compact = _compact_message(text)
    if not compact:
        return []
    terms: list[str] = []
    terms.extend(re.findall(r"[a-z0-9_]{2,}", compact))
    chinese = re.findall(r"[\u4e00-\u9fff]+", compact)
    for block in chinese:
        if len(block) <= 1:
            continue
        if len(block) <= 4:
            terms.append(block)
        for size in (2, 3, 4):
            if len(block) < size:
                continue
            terms.extend(block[index : index + size] for index in range(0, len(block) - size + 1))
    filtered = [
        term
        for term in terms
        if len(term) >= 2 and term not in TERM_STOPWORDS and not _is_stopword_like(term)
    ]
    return list(dict.fromkeys(filtered))[:limit]


def _has_context_dependent_marker(compact: str) -> bool:
    return any(marker in compact for marker in CONTEXT_DEPENDENT_MARKERS)


def _has_standalone_request_marker(compact: str) -> bool:
    return any(marker in compact for marker in STANDALONE_REQUEST_MARKERS)


def _is_stopword_like(term: str) -> bool:
    if term in TERM_STOPWORDS:
        return True
    if re.fullmatch(r"[的是了嘛吗呢吧呀哦啊]+", term):
        return True
    return False
