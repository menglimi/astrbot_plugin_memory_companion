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
    emotional_tone: str = "neutral"
    intimacy_level: float = 0.0


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
AFFECTION_TARGET_SUFFIXES = ("酱", "宝", "宝宝", "宝贝", "老婆", "亲", "达令", "亲爱的")
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
    "对",
    "是",
    "收到",
    "了解",
    "明白",
    "知道啦",
    "好嘞",
    "好滴",
    "嗯呢",
    "嗯哼",
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

# --- 情绪基调检测标记 ---
WARM_MARKERS = (
    "早点休息",
    "注意身体",
    "别太累",
    "照顾好自己",
    "你还好吗",
    "没事吧",
    "别担心",
    "别怕",
    "有我在",
    "陪你",
    "心疼",
    "乖",
    "摸摸头",
    "抱一下",
    "别着凉",
    "好好吃饭",
    "早点睡",
    "别熬夜",
    "注意安全",
    "慢慢来",
    "不着急",
    "没关系",
    "不要紧",
    "辛苦了",
    "谢谢你",
    "感谢",
    "你在就好了",
    "有你在",
)
PLAYFUL_MARKERS = (
    "哈哈哈",
    "你真逗",
    "笑死",
    "逗比",
    "好可爱",
    "太逗了",
    "笑不活了",
    "乐死",
    "你可真",
    "调皮",
    "捣蛋",
    "坏蛋",
    "小笨蛋",
    "笨蛋",
    "憨憨",
    "傻乎乎",
    "可爱的",
    "好玩",
    "有趣",
    "有意思",
    "嘿嘿",
    "嘻嘻",
    "略略",
    "嘤嘤",
    "汪汪",
    "喵喵",
    "哼",
    "哼唧",
    "嘚瑟",
    "得瑟",
)
SERIOUS_MARKERS = (
    "我需要",
    "认真说",
    "说真的",
    "重要",
    "正经",
    "说实话",
    "认真",
    "严肃",
    "正式",
    "必须",
    "一定要",
    "关键",
    "认真地问",
    "有个事",
    "有件事",
    "跟你说",
    "说一下",
    "讨论",
    "商量",
)
VULNERABLE_MARKERS = (
    "我好累",
    "不开心",
    "想哭",
    "害怕",
    "孤独",
    "难过",
    "撑不住",
    "好难过",
    "好累",
    "好难过",
    "心里难受",
    "心里不好受",
    "不知道怎么办",
    "好迷茫",
    "好无助",
    "好委屈",
    "好想哭",
    "崩溃",
    "抑郁",
    "焦虑",
    "睡不着",
    "做噩梦",
    "没安全感",
    "好孤单",
    "好寂寞",
    "没人理",
    "没人懂",
    "好压抑",
    "好窒息",
    "想消失",
    "没意义",
    "好绝望",
)
DISTRESSED_MARKERS = (
    "气死",
    "烦死了",
    "受不了",
    "太烦了",
    "烦透了",
    "气死我了",
    "气炸了",
    "被气到",
    "好生气",
    "好气",
    "烦人",
    "恶心",
    "无语",
    "服了",
    "醉了",
    "离谱",
    "太过分",
    "不可理喻",
    "岂有此理",
    "受不了了",
    "要疯了",
    "要崩溃",
)
NOSTALGIC_MARKERS = (
    "还记得",
    "以前",
    "那时候",
    "怀念",
    "好想念",
    "从前",
    "过去",
    "当初",
    "原来",
    "曾经",
    "那年",
    "那天",
    "好想念以前",
    "好怀念",
    "忆当年",
    "回忆起",
    "想起",
    "记起",
    "印象中",
    "依稀记得",
)
INTIMACY_MARKERS = (
    "我想你",
    "好想你",
    "喜欢你",
    "爱你",
    "好喜欢",
    "舍不得",
    "不想分开",
    "依赖你",
    "离不开你",
    "你是我的",
    "只对你",
    "只有你",
    "特别的人",
    "最重要",
    "最信任",
    "最亲近",
    "说心里话",
    "心里话",
    "跟你讲个秘密",
    "偷偷告诉你",
    "没跟别人说过",
    "只跟你说过",
    "你是第一个",
    "你是唯一",
    "我好在意",
    "真的很在乎",
    "怕失去你",
    "怕你不要我",
    "不想让你失望",
    "怕你生气",
)


def analyze_turn_signal(text: str) -> TurnSignal:
    compact = _compact_message(text)
    terms = message_terms(text)
    context_dependent = _has_context_dependent_marker(compact)
    standalone_request = _has_standalone_request_marker(compact)
    emotional_tone = _detect_emotional_tone(compact)
    intimacy_level = _detect_intimacy_level(compact)
    if not compact:
        return TurnSignal(
            kind="empty",
            low_information=True,
            reason="empty_message",
            terms=terms,
            emotional_tone="neutral",
            intimacy_level=0.0,
        )
    if _is_reaction_only(compact):
        return TurnSignal(
            kind="reaction",
            low_information=True,
            reason="reaction_only",
            terms=terms,
            emotional_tone="playful" if any(m in compact for m in ("哈", "嘻", "嘿", "草", "乐")) else "neutral",
            intimacy_level=intimacy_level,
        )
    if _is_affection_only(compact):
        return TurnSignal(
            kind="affection",
            low_information=True,
            reason="affection_only",
            terms=terms,
            emotional_tone="warm",
            intimacy_level=max(intimacy_level, 0.72),
        )
    if _is_correction_only(compact):
        return TurnSignal(
            kind="correction",
            low_information=True,
            context_dependent=True,
            reason="correction_only",
            terms=terms,
            emotional_tone="serious",
            intimacy_level=intimacy_level,
        )
    return TurnSignal(
        terms=terms,
        context_dependent=context_dependent,
        standalone_request=standalone_request,
        emotional_tone=emotional_tone,
        intimacy_level=intimacy_level,
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


def _detect_emotional_tone(compact: str) -> str:
    """Detect the emotional tone of a message for persona-aware injection."""
    if not compact:
        return "neutral"
    scores = {
        "vulnerable": sum(1 for m in VULNERABLE_MARKERS if m in compact),
        "distressed": sum(1 for m in DISTRESSED_MARKERS if m in compact),
        "nostalgic": sum(1 for m in NOSTALGIC_MARKERS if m in compact),
        "warm": sum(1 for m in WARM_MARKERS if m in compact),
        "playful": sum(1 for m in PLAYFUL_MARKERS if m in compact),
        "serious": sum(1 for m in SERIOUS_MARKERS if m in compact),
    }
    best_tone = max(scores, key=scores.get)
    if scores[best_tone] <= 0:
        return "neutral"
    return best_tone


def _detect_intimacy_level(compact: str) -> float:
    """Estimate intimacy level (0.0-1.0) based on vulnerability and closeness markers."""
    if not compact:
        return 0.0
    intimacy_hits = sum(1 for m in INTIMACY_MARKERS if m in compact)
    vulnerable_hits = sum(1 for m in VULNERABLE_MARKERS if m in compact)
    warm_hits = sum(1 for m in WARM_MARKERS if m in compact)
    playful_hits = sum(1 for m in PLAYFUL_MARKERS if m in compact)
    affection_hits = sum(1 for unit in AFFECTION_UNITS if unit in compact)
    level = 0.0
    level += min(0.45, intimacy_hits * 0.22)
    level += min(0.25, vulnerable_hits * 0.12)
    level += min(0.18, warm_hits * 0.09)
    level += min(0.12, affection_hits * 0.10)
    level += min(0.08, playful_hits * 0.04)
    return max(0.0, min(1.0, round(level, 3)))
