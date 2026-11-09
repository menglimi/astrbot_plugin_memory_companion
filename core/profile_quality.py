"""Shared rule-v2 profile extraction and quality gates.

This module deliberately works with plain dictionaries and duck-typed memory
objects.  The classifier, portrait service, retrieval, and injection paths can
therefore share the same policy without importing one another.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from typing import Any

RULE_EXTRACTOR = "rule_v2"
PROFILE_MEMORY_TYPES = frozenset({"user_profile", "user_preference", "user_habit"})
PROFILE_STATES = frozenset({"candidate", "active", "rejected", "superseded"})

_TRIM_CHARS = " \t\r\n，,。！？!?；;：:、"
_QUOTE_PAIRS = (
    ("“", "”"),
    ("‘", "’"),
    ('"', '"'),
    ("'", "'"),
    ("「", "」"),
    ("『", "』"),
)
_TAIL_PARTICLES = (
    "就可以了",
    "就好了",
    "就行了",
    "就好",
    "就行",
    "即可",
    "可以了",
    "好了",
    "吧",
    "呀",
    "啊",
    "呢",
    "哦",
    "嘛",
    "啦",
    "呗",
    "哟",
    "喔",
)
_LEADING_FILLER_RE = re.compile(
    r"^(?:(?:嗯+|唔+|呃+|那个|对了|其实|顺便说|话说|好的?|行吧?|拜托)[\s，,、]*)+"
)
_REPORT_PREFIX_RE = re.compile(
    r"(?:老板娘|老板|他|她|他们|她们|同事|别人|有人|朋友|同学|家人|妈妈|爸爸)"
    r".{0,16}(?:说|讲|告诉|表示|认为|觉得|问|叫|喊|称呼|提到|提及|描述|介绍|转述)"
)
_REPORT_MARKERS = (
    "听说",
    "据说",
    "转述",
    "引用",
    "原话",
    "聊天记录",
    "消息里说",
)
_QUESTION_WORD_RE = re.compile(
    r"(?:什么|啥|多少|哪(?:个|种|些)?|谁|怎么|为何|为什么|干嘛|是否|还是|"
    r"几(?:月|号|日|点|岁|次|个|种|些|本|杯|碗|年|天|周|位|条|件|份|时|分))"
)
_SECOND_PERSON_ONLY_RE = re.compile(
    r"(?:你们?|您们?|you)(?:自己|本人)?(?:呀|啊|呢|哦|嘛|啦|喔|咯|呗|哟|吧)*",
    re.IGNORECASE,
)
# A bare pronoun is a reference, not a stable profile value: "我喜欢的人是
# 她" reads fine in chat but would store 她 as a durable preference.
_THIRD_PERSON_ONLY_RE = re.compile(
    r"(?:他们?|她们?|它们?)(?:自己|本人)?(?:呀|啊|呢|哦|嘛|啦|喔|咯|呗|哟|吧)*"
)
_ADDRESS_ACTION_RE = re.compile(r"(?:去|来|跟车|跟着|跟|上班|工作|做|让我)")
_ADDRESS_REJECT_RE = re.compile(
    r"(?:不许|不准|不能|别|不要|禁止|怎么还|为何还|为什么还|老是|总是|"
    r"叫我几声|喊我几声|几声|(?:一|两|三|\d+)声|一次|一下)"
)
_TEMPORARY_RE = re.compile(r"(?:今天|现在|刚才|这会儿|最近|这阵子|暂时|临时|目前|当下)")
_ONE_OFF_CONTEXT_RE = re.compile(
    r"(?:这次|本次|这一回|这一轮|刚刚|今晚|今早|今晨|这顿|这一顿|这杯|当前)"
)
_UNCERTAIN_RE = re.compile(r"(?:大概|可能|也许|好像|似乎|说不定|没准)")
_PROFILE_ATTEMPT_RE = re.compile(
    r"(?:叫我|喊我|称呼我|我(?:真的|很|最|超|特别|有点|超级|最近|现在|今天|可能|也许)?"
    r"(?:喜欢|最爱|超爱|不喜欢|不爱|讨厌)|我的(?:生日|职业|专业|星座|血型)|"
    r"我(?:从事|担任|习惯|通常|一般|经常|不能吃|不能碰))"
)

_ADDRESS_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^(?:请|麻烦|劳驾|拜托)?(?:以后|之后|往后)?(?:你|您)?(?:就)?(?:叫|喊)我(?:为|作|做)?[：:\s]*(?P<value>.+)$",
        r"^(?:请|麻烦|劳驾|拜托)?(?:你|您)(?:以后|之后|往后)(?:就)?(?:叫|喊)我(?:为|作|做)?[：:\s]*(?P<value>.+)$",
        r"^(?:请|麻烦|劳驾|拜托)?(?:你|您)?(?:以后|之后|往后)?(?:称呼)我(?:为|作|做)?[：:\s]*(?P<value>.+)$",
        r"^我(?:希望|想让|希望以后|想请)(?:你|您)?(?:以后|之后|往后)?(?:叫|喊|称呼)我(?:为|作|做)?[：:\s]*(?P<value>.+)$",
        r"^我叫[：:\s]*(?P<value>.+)$",
    )
)

_LIKE_RE = re.compile(
    r"^(?:我|咱|俺)(?:真的好|真的|很|最|超|特别|有点|超级)?"
    r"(?:喜欢|最爱|超爱|特别喜欢|真的好爱|很爱|爱)(?P<value>.+)$",
    re.IGNORECASE,
)
# "我喜欢的人是周杰伦" must capture the person, not "的人是周杰伦".
# Tried before the generic _LIKE_RE so the predicate tail is never treated as
# the value.
_LIKE_PERSON_RE = re.compile(
    r"^(?:我|咱|俺)(?:真的好|真的|很|最|超|特别|超级)?"
    r"(?:喜欢|爱)(?:的)?(?:那个人|人)(?:是|叫|就是|叫做|名叫|为)[：:\s]*(?P<value>.+)$",
    re.IGNORECASE,
)
# "我最喜欢的是烤肉" / "我喜欢的就是周杰伦" -> explicit object clause.
_LIKE_OBJECT_RE = re.compile(
    r"^(?:我|咱|俺)(?:真的好|真的|很|最|超|特别|超级)?"
    r"(?:喜欢|爱)(?:的)?(?:是|就是)[：:\s]*(?P<value>.+)$",
    re.IGNORECASE,
)
# A leading action verb is stripped from a preference object; the result is
# useful but inferred rather than a literal statement, so it is recorded as a
# fuzzy candidate instead of an active stable fact.
_LIKE_ACTION_PREFIXES = (
    "吃",
    "喝",
    "玩",
    "看",
    "听",
    "打",
    "去",
    "上",
    "养",
    "收集",
    "收藏",
    "追",
)
_LIKE_UNCLEAN_PREFIXES = ("不", "没", "别", "讨厌", "的人", "的是")
_DISLIKE_RE = re.compile(
    r"^(?:我|咱|俺)(?:真的|很|最|超|特别|有点)?"
    r"(?:不太喜欢|不喜欢|不爱|讨厌)(?P<value>.+)$",
    re.IGNORECASE,
)
_ALLERGY_RE = re.compile(
    r"^(?:我|咱|俺)(?:对|对于)(?P<value>.+?)(?:过敏|不能吃|不能碰|受不了)$"
)
_CANNOT_EAT_RE = re.compile(r"^(?:我|咱|俺)(?:不能吃|不能碰)(?P<value>.+)$")
_BIRTHDAY_RE = re.compile(
    r"^(?:我|咱|俺)(?:的)?生日(?:是|在|为|：|:)?\s*(?P<value>.+)$"
)
_OCCUPATION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^(?:我|咱|俺)(?:的)?职业(?:是|为|：|:)\s*(?P<value>.+)$",
        r"^(?:我|咱|俺)(?:从事|担任|当)(?:一名|一个)?\s*(?P<value>.+)$",
        r"^(?:我|咱|俺)是(?:做|干)(?P<value>.+)$",
        r"^(?:我|咱|俺)是(?:一名|一个)\s*(?P<value>.+)$",
    )
)
# Education used to be "everything after 我是/我在学", so "我是学生"
# produced education="生".  Degree words are now matched as whole words and the
# generic tail pattern is gone; anything that does not form a clean value is
# dropped rather than stored.
_EDUCATION_DEGREE_TERMS = (
    "博士后",
    "博士研究生",
    "博士生",
    "博士",
    "硕士研究生",
    "硕士生",
    "硕士",
    "研究生",
    "本科生",
    "大学生",
    "大专生",
    "专科生",
    "中专生",
    "高中生",
    "初中生",
    "小学生",
    "学生",
)
_EDUCATION_DEGREE_RE = re.compile(
    r"^(?:我|咱|俺)(?:目前|现在)?"
    r"(?:是一名|是一个|是个|是|在读的是|在读|正在读|正在上)?\s*"
    r"(?P<value>"
    + "|".join(_EDUCATION_DEGREE_TERMS)
    + r")(?:一枚|一个|在读|在读中)?$"
)
_EDUCATION_ENROLLED_RE = re.compile(
    r"^(?:我|咱|俺)(?:在|正在)(?:读|上)"
    r"(?P<value>大学|研究生|硕士|博士|高中|初中|小学|本科|专科)(?:阶段|期间)?$"
)
_EDUCATION_ENROLLED_MAP = {
    "大学": "大学生",
    "研究生": "研究生",
    "硕士": "硕士研究生",
    "博士": "博士研究生",
    "高中": "高中生",
    "初中": "初中生",
    "小学": "小学生",
    "本科": "本科生",
    "专科": "专科生",
}
_EDUCATION_MAJOR_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^(?:我|咱|俺)(?:的)?专业(?:是|为|：|:)\s*(?P<value>.+)$",
        r"^(?:我|咱|俺)(?:是|在)(?:学|读)(?P<value>.+?)(?:专业|系)(?:的)?$",
        r"^(?:我|咱|俺)是(?P<value>.+?)专业(?:的)?$",
    )
)
# "我是学计算机的" keeps 计算机 but is an inference (the sentence names a field
# of study, not a degree), so it is a fuzzy candidate.
_EDUCATION_FIELD_RE = re.compile(r"^(?:我|咱|俺)是学(?P<value>.+?)的$")
_ZODIAC_RE = re.compile(r"^(?:我|咱|俺)(?:的)?星座(?:是|为|：|:)?\s*(?P<value>.+)$")
_BLOOD_TYPE_RE = re.compile(
    r"^(?:我|咱|俺)(?:的)?血型(?:是|为|：|:)?\s*(?P<value>.+)$", re.IGNORECASE
)
_HABIT_RE = re.compile(r"^(?:我|咱|俺)(?:一般|通常|习惯|每次|总是|经常)(?P<value>.+)$")
_BOUNDARY_RE = re.compile(r"^(?:我|咱|俺)(?:不喜欢别人|讨厌别人|不希望)(?P<value>.+)$")
_AVOID_RE = re.compile(r"^(?:请)?(?:别问我|不要问我|不想聊)(?P<value>.*)$")


def _source_text(value: Any, limit: int = 1800) -> str:
    if value is None:
        return ""
    source = str(value).replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    source = re.sub(r"[\t\f\v ]+", " ", source)
    source = re.sub(r" *\n *", "\n", source)
    return source[:limit].strip()


def _clean_text(value: Any, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
    return text[:limit]


def _strip_matching_quotes(value: str) -> str:
    text = value.strip()
    changed = True
    while changed and len(text) >= 2:
        changed = False
        for opening, closing in _QUOTE_PAIRS:
            if text.startswith(opening) and text.endswith(closing):
                text = text[len(opening) : len(text) - len(closing)].strip()
                changed = True
                break
    return text


def _clean_value(
    value: Any,
    *,
    limit: int = 80,
    strip_terminal_de: bool = False,
    stop_at_colon: bool = False,
    tail_particles: tuple[str, ...] = (),
) -> str:
    text = _clean_text(value, limit + 32).strip(_TRIM_CHARS)
    if stop_at_colon:
        text = re.split(r"[：:]", text, maxsplit=1)[0].rstrip()
    text = _strip_matching_quotes(text)
    changed = bool(tail_particles)
    while changed and text:
        changed = False
        for particle in tail_particles:
            if text.endswith(particle) and len(text) > len(particle):
                text = text[: -len(particle)].rstrip()
                changed = True
                break
    if strip_terminal_de and text.endswith("的") and len(text) > 1:
        text = text[:-1].rstrip()
    return _strip_matching_quotes(text.strip(_TRIM_CHARS))[:limit]


def normalize_profile_value(value: Any) -> str:
    """Return the canonical comparison value while preserving readable text."""
    return re.sub(r"\s+", " ", _clean_value(value, limit=80).casefold()).strip()


def reported_speech_prefix(prefix: str) -> bool:
    """Whether a clause reports somebody else's words rather than the user's."""
    return _reported_prefix(prefix)


def _reported_prefix(prefix: str) -> bool:
    compact = re.sub(r"\s+", "", prefix)
    if not compact:
        return False
    return any(marker in compact for marker in _REPORT_MARKERS) or bool(
        _REPORT_PREFIX_RE.search(compact)
    )


def _carries_report_context(sentence: str) -> bool:
    compact = re.sub(r"\s+", "", sentence)
    return _reported_prefix(compact) and compact.endswith(
        (
            "：",
            ":",
            "说",
            "表示",
            "提到",
            "提及",
            "描述",
            "介绍",
            "转述",
            "原话",
            "如下",
            "内容",
        )
    )


def _iter_clauses(source: str) -> Iterator[tuple[str, str, bool]]:
    """Yield (clause, prior sentence prefix, is_question)."""
    carried_prefix = ""
    for sentence_match in re.finditer(
        r"([^。.!！？?；;\n]+)([。.!！？?；;\n]*)", source
    ):
        sentence = sentence_match.group(1)
        terminator = sentence_match.group(2)
        for clause_match in re.finditer(r"[^，,]+", sentence):
            raw_clause = clause_match.group(0).strip()
            if not raw_clause:
                continue
            prefix = carried_prefix + sentence[: clause_match.start()]
            clause = _LEADING_FILLER_RE.sub("", raw_clause).strip()
            if clause:
                yield clause, prefix, "?" in terminator or "？" in terminator
        carried_prefix = sentence if _carries_report_context(sentence) else ""


def _is_quoted_clause(clause: str) -> bool:
    return bool(clause) and clause[0] in "“‘\"'「『"


def _is_question(clause: str, sentence_is_question: bool) -> bool:
    compact = re.sub(r"\s+", "", clause)
    return (
        sentence_is_question
        or compact.endswith(("吗", "么"))
        or bool(_QUESTION_WORD_RE.search(compact))
    )


def _valid_general_value(value: str, *, maximum: int = 40) -> bool:
    if not value or len(value) > maximum:
        return False
    if _SECOND_PERSON_ONLY_RE.fullmatch(value.strip()):
        return False
    if _THIRD_PERSON_ONLY_RE.fullmatch(value.strip()):
        return False
    if _QUESTION_WORD_RE.search(value):
        return False
    return not any(mark in value for mark in ("\n", "\r"))


def _candidate(
    *,
    dimension: str,
    memory_type: str,
    label: str,
    kind: str,
    value: str,
    claim_summary: str,
    score: float,
    importance: float,
    quality: str = "explicit",
    state: str = "",
) -> dict[str, Any]:
    normalized = normalize_profile_value(value)
    cardinality = (
        "single"
        if dimension
        in {
            "preferred_address",
            "birthday",
            "occupation",
            "education",
            "zodiac",
            "blood_type",
        }
        else "multi"
    )
    state = state or ("active" if quality == "explicit" else "candidate")
    evidence_strength = "direct_statement"
    payload: dict[str, Any] = {
        "memory_type": memory_type,
        "label": label,
        "kind": kind,
        "profile_polarity": kind,
        "dimension": dimension,
        "profile_dimension": dimension,
        "value": value,
        "profile_value": value,
        "normalized_value": normalized,
        "profile_cardinality": cardinality,
        "claim_summary": _clean_text(claim_summary, 180),
        "extractor": RULE_EXTRACTOR,
        "extraction_quality": quality,
        "extraction_quality_score": round(max(0.0, min(1.0, score)), 3),
        "evidence_strength": evidence_strength,
        "profile_state": state,
        "status": state,
        "quality_gate_passed": False,
        "confidence": round(max(0.0, min(1.0, score)), 3),
        "importance": round(max(0.0, min(1.0, importance)), 3),
    }
    # The gate flag is derived from the payload itself, never hard-coded.  An
    # active fact must clear the 0.75 activation threshold; a fuzzy candidate
    # only has to clear the 0.5 candidate threshold and can therefore never be
    # written as stable_memory (its state stays "candidate").
    passed, _reason = profile_quality_decision(
        payload,
        require_active=state == "active",
        minimum_score=0.75 if state == "active" else 0.5,
    )
    payload["quality_gate_passed"] = bool(passed)
    return payload


def _address_from_clause(clause: str) -> dict[str, Any] | None:
    compact = re.sub(r"\s+", "", clause)
    if _ADDRESS_REJECT_RE.search(compact):
        return None
    for pattern in _ADDRESS_PATTERNS:
        match = pattern.fullmatch(clause)
        if not match:
            continue
        value = _clean_value(
            match.group("value"),
            limit=24,
            stop_at_colon=True,
            tail_particles=_TAIL_PARTICLES,
        )
        normalized = normalize_profile_value(value)
        if not normalized or len(normalized) > 12:
            return None
        if _ADDRESS_ACTION_RE.search(normalized) or _ADDRESS_REJECT_RE.search(
            normalized
        ):
            return None
        return _candidate(
            dimension="preferred_address",
            memory_type="user_profile",
            label="称呼",
            kind="address",
            value=value,
            claim_summary=f"希望被称为 {value}",
            score=0.97,
            importance=0.74,
        )
    return None


def extract_preferred_address(text: Any) -> dict[str, Any] | None:
    """Extract one unambiguous direct address request or self-declaration."""
    source = _source_text(text)
    for clause, prefix, question in _iter_clauses(source):
        if (
            _reported_prefix(prefix)
            or _is_quoted_clause(clause)
            or _is_question(clause, question)
        ):
            continue
        candidate = _address_from_clause(clause)
        if candidate is not None:
            return candidate
    return None


def _match_value(
    pattern: re.Pattern[str], clause: str, *, strip_terminal_de: bool = False
) -> str:
    match = pattern.fullmatch(clause)
    if not match:
        return ""
    return _clean_value(
        match.group("value"), limit=80, strip_terminal_de=strip_terminal_de
    )


def _clean_like_value(value: Any) -> str:
    """Trim like-object politeness without eating a real noun's last character.

    "我喜欢酒吧" ends with the noun 酒吧; the generic particle stripper used to
    turn it into 酒.  Keep "吧" only for one-character remainders, still strip
    it from real sentences such as "我喜欢烤肉吧".
    """
    particles = tuple(particle for particle in _TAIL_PARTICLES if particle != "吧")
    text = _clean_value(
        value, limit=40, strip_terminal_de=True, tail_particles=particles
    )
    if text.endswith("吧") and len(text) > 2:
        text = _clean_value(
            text[:-1], limit=40, strip_terminal_de=True, tail_particles=particles
        )
    return text


def _like_candidates(clause: str) -> list[dict[str, Any]]:
    for pattern in (_LIKE_PERSON_RE, _LIKE_OBJECT_RE):
        match = pattern.fullmatch(clause)
        if not match:
            continue
        value = _clean_like_value(match.group("value"))
        if not _valid_general_value(value, maximum=30):
            return []
        return [
            _candidate(
                dimension="preference",
                memory_type="user_preference",
                label="喜欢",
                kind="like",
                value=value,
                claim_summary=f"喜欢 {value}",
                score=0.9,
                importance=0.66,
            )
        ]
    match = _LIKE_RE.fullmatch(clause)
    if not match:
        return []
    value = _clean_like_value(match.group("value"))
    if not value:
        return []
    # An unhandled "的人是…" tail is exactly the corruption this fix removes;
    # drop it instead of storing "的人是周杰伦".
    if any(value.startswith(prefix) for prefix in _LIKE_UNCLEAN_PREFIXES):
        return []
    if "的人" in value or "的是" in value:
        return []
    fuzzy = False
    for prefix in _LIKE_ACTION_PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix) + 1:
            value = value[len(prefix) :].strip()
            fuzzy = True
            break
    if not _valid_general_value(value, maximum=30):
        return []
    return [
        _candidate(
            dimension="preference",
            memory_type="user_preference",
            label="喜欢",
            kind="like",
            value=value,
            claim_summary=f"喜欢 {value}",
            score=0.6 if fuzzy else 0.9,
            importance=0.6 if fuzzy else 0.66,
            quality="inferred" if fuzzy else "explicit",
        )
    ]


def _education_candidates(clause: str) -> list[dict[str, Any]]:
    match = _EDUCATION_DEGREE_RE.fullmatch(clause)
    if match:
        value = _clean_value(match.group("value"), limit=20)
        if _valid_general_value(value, maximum=20):
            return [
                _candidate(
                    dimension="education",
                    memory_type="user_profile",
                    label="专业/学业",
                    kind="education",
                    value=value,
                    claim_summary=f"学业身份是 {value}",
                    score=0.9,
                    importance=0.68,
                )
            ]
        return []
    match = _EDUCATION_ENROLLED_RE.fullmatch(clause)
    if match:
        value = _EDUCATION_ENROLLED_MAP.get(match.group("value"), "")
        if _valid_general_value(value, maximum=20):
            return [
                _candidate(
                    dimension="education",
                    memory_type="user_profile",
                    label="专业/学业",
                    kind="education",
                    value=value,
                    claim_summary=f"学业身份是 {value}",
                    score=0.9,
                    importance=0.68,
                )
            ]
        return []
    for pattern in _EDUCATION_MAJOR_PATTERNS:
        match = pattern.fullmatch(clause)
        if not match:
            continue
        value = _clean_value(
            match.group("value"),
            limit=40,
            strip_terminal_de=True,
            tail_particles=_TAIL_PARTICLES,
        )
        if _valid_general_value(value, maximum=30) and not _TEMPORARY_RE.search(clause):
            return [
                _candidate(
                    dimension="education",
                    memory_type="user_profile",
                    label="专业/学业",
                    kind="education",
                    value=value,
                    claim_summary=f"专业/学业是 {value}",
                    score=0.9,
                    importance=0.68,
                )
            ]
        return []
    match = _EDUCATION_FIELD_RE.fullmatch(clause)
    if match:
        value = _clean_value(
            match.group("value"),
            limit=30,
            strip_terminal_de=True,
            tail_particles=_TAIL_PARTICLES,
        )
        if _valid_general_value(value, maximum=20):
            return [
                _candidate(
                    dimension="education",
                    memory_type="user_profile",
                    label="专业/学业",
                    kind="education",
                    value=value,
                    claim_summary=f"所学的领域是 {value}",
                    score=0.6,
                    importance=0.6,
                    quality="inferred",
                )
            ]
    return []


def _non_address_candidates(clause: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if _UNCERTAIN_RE.search(clause):
        return results
    transient_context = bool(
        _TEMPORARY_RE.search(clause) or _ONE_OFF_CONTEXT_RE.search(clause)
    )

    value = _match_value(_DISLIKE_RE, clause)
    if (
        _valid_general_value(value)
        and not transient_context
        and "的人" not in value
        and "的是" not in value
    ):
        results.append(
            _candidate(
                dimension="preference",
                memory_type="user_preference",
                label="不喜欢",
                kind="dislike",
                value=value,
                claim_summary=f"不喜欢 {value}",
                score=0.93,
                importance=0.66,
            )
        )
        return results

    if not transient_context:
        results.extend(_like_candidates(clause))
        if results:
            return results

    value = _match_value(_ALLERGY_RE, clause) or _match_value(_CANNOT_EAT_RE, clause)
    if _valid_general_value(value, maximum=30) and not transient_context:
        results.append(
            _candidate(
                dimension="dietary_restriction",
                memory_type="user_preference",
                label="过敏/禁忌",
                kind="avoid",
                value=value,
                claim_summary=f"饮食禁忌：{value}",
                score=0.96,
                importance=0.82,
            )
        )
        return results

    value = _match_value(_BIRTHDAY_RE, clause)
    birthday_like = bool(
        re.search(r"(?:月|日|号|年|/|\d|一|二|三|四|五|六|七|八|九|十)", value)
    )
    if (
        _valid_general_value(value, maximum=20)
        and birthday_like
        and not _TEMPORARY_RE.search(value)
    ):
        results.append(
            _candidate(
                dimension="birthday",
                memory_type="user_profile",
                label="生日",
                kind="birthday",
                value=value,
                claim_summary=f"生日是 {value}",
                score=0.96,
                importance=0.76,
            )
        )
        return results

    # Education must run before the generic "我是一名X" occupation rule so
    # "我是一名研究生" is not typed as an occupation.
    if not _TEMPORARY_RE.search(clause):
        results.extend(_education_candidates(clause))
        if results:
            return results

    for pattern in _OCCUPATION_PATTERNS:
        value = _match_value(pattern, clause, strip_terminal_de=True)
        if _valid_general_value(value) and not _TEMPORARY_RE.search(clause):
            results.append(
                _candidate(
                    dimension="occupation",
                    memory_type="user_profile",
                    label="职业",
                    kind="occupation",
                    value=value,
                    claim_summary=f"职业是 {value}",
                    score=0.92,
                    importance=0.7,
                )
            )
            return results

    value = _match_value(_ZODIAC_RE, clause, strip_terminal_de=True)
    if value.endswith("座"):
        value = value[:-1].rstrip()
    if _valid_general_value(value, maximum=12):
        results.append(
            _candidate(
                dimension="zodiac",
                memory_type="user_profile",
                label="星座",
                kind="zodiac",
                value=value,
                claim_summary=f"星座是 {value}",
                score=0.94,
                importance=0.64,
            )
        )
        return results

    value = _match_value(_BLOOD_TYPE_RE, clause, strip_terminal_de=True)
    if _valid_general_value(value, maximum=12):
        results.append(
            _candidate(
                dimension="blood_type",
                memory_type="user_profile",
                label="血型",
                kind="blood_type",
                value=value,
                claim_summary=f"血型是 {value}",
                score=0.94,
                importance=0.7,
            )
        )
        return results

    value = _match_value(_HABIT_RE, clause)
    if _valid_general_value(value) and not _TEMPORARY_RE.search(clause):
        results.append(
            _candidate(
                dimension="communication_preference",
                memory_type="user_habit",
                label="习惯",
                kind="habit",
                value=value,
                claim_summary=f"沟通习惯：{value}",
                score=0.88,
                importance=0.61,
            )
        )
        return results

    value = _match_value(_BOUNDARY_RE, clause)
    if _valid_general_value(value) and not transient_context:
        results.append(
            _candidate(
                dimension="boundary",
                memory_type="user_preference",
                label="边界",
                kind="avoid",
                value=value,
                claim_summary=f"边界：{value}",
                score=0.94,
                importance=0.75,
            )
        )
        return results

    avoid_match = _AVOID_RE.fullmatch(clause)
    if avoid_match:
        value = _clean_value(avoid_match.group("value"), limit=40)
        if (not value or _valid_general_value(value)) and not transient_context:
            summary = f"不希望聊 {value}" if value else "有明确不想聊的内容"
            results.append(
                _candidate(
                    dimension="boundary",
                    memory_type="user_preference",
                    label="雷区",
                    kind="avoid",
                    value=value or "未指明话题",
                    claim_summary=summary,
                    score=0.94,
                    importance=0.75,
                )
            )
    return results


def extract_profile_candidates(text: Any) -> list[dict[str, Any]]:
    """Extract explicit, self-attributed stable profile candidates.

    Rejected, reported, quoted, temporary, and interrogative statements are not
    returned.  Their source message remains available to the ordinary timeline.
    """
    source = _source_text(text)
    if not source:
        return []
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for clause, prefix, question in _iter_clauses(source):
        if (
            _reported_prefix(prefix)
            or _is_quoted_clause(clause)
            or _is_question(clause, question)
        ):
            continue
        candidates: list[dict[str, Any]] = []
        address = _address_from_clause(clause)
        if address is not None:
            candidates.append(address)
        else:
            candidates.extend(_non_address_candidates(clause))
        for candidate in candidates:
            key = (
                str(candidate["profile_dimension"]),
                str(candidate["kind"]),
                str(candidate["normalized_value"]),
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(candidate)
    return results


def profile_rejection_reason(text: Any) -> str:
    """Classify profile-like text rejected before the write gate.

    This is intentionally diagnostic-only. It never creates a candidate and
    therefore cannot weaken the extraction policy.
    """
    source = _source_text(text)
    if not source or extract_profile_candidates(source):
        return ""
    compact = re.sub(r"\s+", "", source)
    if not _PROFILE_ATTEMPT_RE.search(compact):
        return ""
    address_attempt = bool(re.search(r"(?:叫我|喊我|称呼我)", compact))
    if address_attempt and _ADDRESS_ACTION_RE.search(compact):
        return "action_context"
    if _reported_prefix(compact) or any(
        marker in compact for marker in _REPORT_MARKERS
    ):
        return "third_party_statement"
    return "profile_quality_rejected"


def profile_candidate_metadata(
    candidate: Any, *, source_memory_id: str = ""
) -> dict[str, Any]:
    payload = candidate if isinstance(candidate, dict) else {}
    state = _clean_text(payload.get("profile_state"), 40) or "candidate"
    metadata: dict[str, Any] = {
        "extractor": RULE_EXTRACTOR,
        "profile_dimension": _clean_text(
            payload.get("profile_dimension") or payload.get("dimension"), 80
        ),
        "profile_value": _clean_text(
            payload.get("profile_value") or payload.get("value"), 80
        ),
        "normalized_value": normalize_profile_value(
            payload.get("normalized_value")
            or payload.get("profile_value")
            or payload.get("value")
        ),
        "profile_polarity": _clean_text(payload.get("kind"), 40),
        "profile_cardinality": _clean_text(payload.get("profile_cardinality"), 16)
        or "multi",
        "extraction_quality": _clean_text(payload.get("extraction_quality"), 40)
        or "explicit",
        "extraction_quality_score": float(
            payload.get("extraction_quality_score") or 0.0
        ),
        "evidence_strength": _clean_text(payload.get("evidence_strength"), 40)
        or "direct_statement",
        "profile_state": state,
        "quality_gate_passed": False,
        "source_memory_id": _clean_text(source_memory_id, 120),
    }
    # Recompute the gate from the metadata itself instead of copying a caller
    # supplied boolean.  This is what makes "quality_gate_passed" a result
    # rather than a self-certification.
    passed, _reason = profile_quality_decision(
        {
            "memory_type": payload.get("memory_type") or "user_profile",
            "metadata": metadata,
        },
        require_active=state == "active",
        minimum_score=0.75 if state == "active" else 0.5,
    )
    metadata["quality_gate_passed"] = bool(passed)
    return metadata


def _memory_and_metadata(value: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(value, dict):
        nested = value.get("metadata")
        if isinstance(nested, dict):
            return _clean_text(value.get("memory_type"), 80), nested
        return _clean_text(value.get("memory_type"), 80), value
    metadata = getattr(value, "metadata", None)
    return _clean_text(getattr(value, "memory_type", ""), 80), metadata if isinstance(
        metadata, dict
    ) else {}


def _rule_profile_parts(
    memory_or_metadata: Any,
) -> tuple[str, dict[str, Any], bool]:
    memory_type, metadata = _memory_and_metadata(memory_or_metadata)
    extractor = _clean_text(metadata.get("extractor"), 80).lower()
    producer_kind = _clean_text(metadata.get("producer_kind"), 80).lower()
    has_rule_metadata = any(
        key in metadata
        for key in (
            "profile_state",
            "profile_dimension",
            "profile_value",
            "normalized_value",
            "extraction_quality",
            "extraction_quality_score",
            "evidence_strength",
        )
    )
    rule_source = extractor.startswith("rule_") or producer_kind.startswith("rule_")
    is_rule_profile = rule_source and (
        memory_type in PROFILE_MEMORY_TYPES or has_rule_metadata
    )
    return memory_type, metadata, is_rule_profile


def _has_profile_conflict(metadata: dict[str, Any]) -> bool:
    if metadata.get("profile_conflict") or metadata.get("conflict_reason"):
        return True
    conflicts = metadata.get("conflicts_with")
    if isinstance(conflicts, (list, tuple, set, frozenset)):
        return bool(conflicts)
    return bool(_clean_text(conflicts, 200))


def _profile_payload_checks(
    metadata: dict[str, Any],
    *,
    minimum_score: float,
    require_inferred_evidence: bool,
) -> tuple[bool, str]:
    dimension = _clean_text(
        metadata.get("profile_dimension") or metadata.get("dimension"), 80
    )
    value = _clean_text(metadata.get("profile_value") or metadata.get("value"), 80)
    normalized = normalize_profile_value(metadata.get("normalized_value"))
    if not dimension:
        return False, "profile_dimension_missing"
    if not value:
        return False, "profile_value_missing"
    if not normalized:
        return False, "profile_normalized_value_missing"
    if normalized != normalize_profile_value(value):
        return False, "profile_normalized_value_mismatch"
    if _has_profile_conflict(metadata):
        return False, "profile_conflict"
    try:
        score = float(metadata.get("extraction_quality_score"))
    except (TypeError, ValueError):
        return False, "profile_quality_score_missing"
    if not math.isfinite(score) or score < minimum_score or score > 1.0:
        return False, "profile_quality_rejected"
    quality = _clean_text(metadata.get("extraction_quality"), 40).lower()
    if quality not in {"explicit", "confirmed", "corroborated", "inferred"}:
        return False, "profile_extraction_quality_missing"
    evidence = _clean_text(metadata.get("evidence_strength"), 60).lower()
    if evidence not in {
        "direct_statement",
        "user_confirmed",
        "multiple_independent_evidence",
        "independent_evidence",
    }:
        return False, "profile_evidence_missing"
    if require_inferred_evidence and quality == "inferred":
        try:
            evidence_count = int(
                metadata.get("independent_evidence_count")
                or metadata.get("evidence_count")
                or 0
            )
        except (TypeError, ValueError):
            evidence_count = 0
        if evidence_count < 2 and evidence not in {
            "user_confirmed",
            "multiple_independent_evidence",
        }:
            return False, "profile_evidence_insufficient"
    return True, "profile_quality_passed"


def profile_quality_decision(
    memory_or_metadata: Any,
    *,
    require_active: bool = True,
    minimum_score: float = 0.75,
) -> tuple[bool, str]:
    """Validate rule-produced profile metadata while preserving manual records.

    The verdict is always recomputed from the real payload.  A caller cannot
    pass the gate by writing "quality_gate_passed": True, because that flag is
    no longer an input.
    """
    _memory_type, metadata, is_rule_profile = _rule_profile_parts(
        memory_or_metadata
    )
    if not is_rule_profile:
        return True, "profile_quality_compatible"

    state = _clean_text(
        metadata.get("profile_state") or metadata.get("status"), 40
    ).lower()
    if not state:
        return False, "profile_state_missing"
    if state == "pending":
        return False, f"profile_state_{state}"
    if state in {"rejected", "superseded", "archived"}:
        return False, f"profile_state_{state}"
    if state not in PROFILE_STATES:
        return False, "profile_state_invalid"
    if require_active and state != "active":
        return False, f"profile_state_{state}"

    allowed, reason = _profile_payload_checks(
        metadata,
        minimum_score=minimum_score,
        require_inferred_evidence=state == "active",
    )
    if not allowed:
        return False, reason
    return True, "profile_quality_passed"


def profile_quality_activation_check(
    memory_or_metadata: Any,
) -> tuple[bool, str]:
    """Check whether a rule candidate may be promoted to active.

    This reads the real stored state instead of overwriting it with "active".
    It is the function a store write gate should call before a promotion.
    """
    _memory_type, metadata, is_rule_profile = _rule_profile_parts(
        memory_or_metadata
    )
    if not is_rule_profile:
        return True, "profile_quality_compatible"
    state = _clean_text(
        metadata.get("profile_state") or metadata.get("status"), 40
    ).lower()
    if state not in {"candidate", "active"}:
        if not state:
            return False, "profile_state_missing"
        if state in {"rejected", "superseded", "archived", "pending"}:
            return False, f"profile_state_{state}"
        return False, "profile_state_invalid"
    return _profile_payload_checks(
        metadata,
        minimum_score=0.75,
        require_inferred_evidence=True,
    )


def profile_quality_gate_passed(
    memory_or_metadata: Any,
    *,
    require_active: bool = True,
    minimum_score: float = 0.75,
) -> bool:
    """Convenience boolean wrapper around profile_quality_decision."""
    passed, _reason = profile_quality_decision(
        memory_or_metadata,
        require_active=require_active,
        minimum_score=minimum_score,
    )
    return bool(passed)


__all__ = [
    "PROFILE_MEMORY_TYPES",
    "PROFILE_STATES",
    "RULE_EXTRACTOR",
    "extract_preferred_address",
    "extract_profile_candidates",
    "normalize_profile_value",
    "profile_candidate_metadata",
    "profile_quality_activation_check",
    "profile_quality_decision",
    "profile_quality_gate_passed",
    "profile_rejection_reason",
]
