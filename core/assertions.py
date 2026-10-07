"""Distilled assertions: the second memory layer.

A conversation summary answers "what did we talk about".  An assertion
answers "what is true about this person right now, and what evidence says so",
which is what a memory has to answer later.

The summarizer already extracts facts inside the same provider call that
produces the summary, so this layer reuses that call: it never adds one.  An
assertion becomes an ordinary ``memories`` row rather than a row in
``portrait_facts``, because recall and injection only ever read ``memories``.
Writing assertions anywhere else would build the same disconnected island the
conversation summary already suffers from.

Merging is keyed on (subject, dimension, polarity, normalized value), which the
store already uses to fold repeated facts into one canonical record.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .models import clean_text
from .profile_quality import normalize_profile_value, reported_speech_prefix


#: A claim can be literally present in the transcript and still must not become
#: a long-term fact about the user. Reported speech, role-play, a temporary
#: state, and a plan are the four shapes that pass a source check and are wrong
#: anyway, so they are refused here rather than left to the model's judgement.
REPORTED_SPEECH_MARKERS: tuple[str, ...] = (
    "他说", "她说", "他们说", "别人说", "据说", "听说", "听说他", "听说她",
    "转述", "原话", "据说",
)

ROLE_PLAY_MARKERS: tuple[str, ...] = (
    "角色扮演", "rp", "扮演", "台词", "剧本", "设定里", "人设",
)

TEMPORAL_STATE_MARKERS: tuple[str, ...] = (
    "今天有点", "有点累", "现在有点", "临时", "暂时", "就这一次",
    "一会儿", "等会儿", "今晚先", "先这样", "我去洗澡",
)

INTENT_MARKERS: tuple[str, ...] = (
    "打算", "准备", "计划", "想要试试", "考虑", "可能会", "下周开始",
    "打算要", "想要开始",
)

#: Prefixes that mark the claim as belonging to somebody other than the subject.
_SUBJECT_LEAD = ("他", "她", "他们", "她们", "别人", "大家")


def claim_is_personal_fact(
    subject: str,
    value: str,
    evidence: list[str] | None = None,
) -> tuple[bool, str]:
    """Decide whether a claim may be stored as a long-term fact about ``subject``.

    Returns ``(ok, reason)``.  ``reason`` is ``""`` when the claim is a personal
    fact, otherwise one of ``reported_speech`` / ``role_play`` /
    ``temporary_state`` / ``intent`` / ``subject_mismatch``.

    The decision is made against the *cited messages*, not the claim text.
    A model that rewrites "他说他最讨厌香菜" as "naliling 最讨厌香菜" strips the
    reporting frame and leaves nothing to refuse, while the original message
    still says it plainly.  Judging the claim alone therefore passed exactly the
    cases this gate exists to catch.
    """
    text = clean_text(value, 200)
    if not text or not subject:
        return False, "subject_mismatch"
    sources = [clean_text(item, 2000) for item in (evidence or []) if clean_text(item, 2000)]
    if not sources:
        sources = [text]
    claim_compact = re.sub(r"\s+", "", text)
    evidence_compact = []
    for item in sources:
        clauses = [part for part in re.split(r"[。．.!！?？;；,，\n]+|\s+(?=[\u4e00-\u9fff])", item) if part.strip()]
        compact_clauses = [re.sub(r"\s+", "", part) for part in clauses]
        if not compact_clauses:
            continue
        scores = [SequenceMatcher(None, claim_compact, part, autojunk=False).find_longest_match().size for part in compact_clauses]
        best = max(range(len(scores)), key=scores.__getitem__)
        relevant = compact_clauses[best]
        # Preserve an explicit framing prefix such as "角色扮演：...", while
        # allowing a separate sentence about today's plan or fatigue to coexist
        # with a supported long-term habit in the same message.
        if best and compact_clauses[best - 1].strip("（）()[]【】:") in {
            *ROLE_PLAY_MARKERS, *REPORTED_SPEECH_MARKERS,
        }:
            relevant = compact_clauses[best - 1] + relevant
        evidence_compact.append(relevant)
    combined = [claim_compact, *evidence_compact]

    for compact in combined:
        if any(marker in compact for marker in ROLE_PLAY_MARKERS if marker != "rp") or re.search(r"(?<![a-z])rp(?![a-z])", compact.lower()):
            return False, "role_play"
        if reported_speech_prefix(compact) or any(
            marker in compact for marker in REPORTED_SPEECH_MARKERS
        ):
            return False, "reported_speech"
        if any(marker in compact for marker in TEMPORAL_STATE_MARKERS):
            return False, "temporary_state"
        if any(marker in compact for marker in INTENT_MARKERS):
            return False, "intent"

    # Who the claim is about is read from the claim, never from the cited
    # message: people talk about themselves in the third person all the time,
    # and a user describing their own habit as "他..." is not about anybody
    # else.  This only refuses a claim whose own subject contradicts the owner.
    if claim_compact.startswith(_SUBJECT_LEAD) and subject not in ("他", "她", "他们", "她们"):
        return False, "subject_mismatch"
    return True, ""


#: Prompt vocabulary.  Kept identical to the enumeration in rule 19 so the
#: model cannot invent a dimension that silently becomes its own merge slot.
#: The single-value dimensions are listed explicitly because conflating them
#: into one generic "profile" slot is what makes "I moved to Beijing" look like
#: a second fact instead of replacing the first.
ASSERTION_DIMENSIONS: frozenset[str] = frozenset({
    "birthday",
    "occupation",
    "education",
    "preferred_address",
    "residence",
    "zodiac",
    "blood_type",
    "preference",
    "dietary_restriction",
    "habit",
    "boundary",
    "commitment",
    "health",
    "relation",
    "schedule",
    "dislike",
})

#: Dimensions where a new value replaces the old one.  Anything else is a set:
#: two different cats are not two versions of one fact, and superseding them
#: would lose history that past-tense questions still need.
SINGLE_VALUE_DIMENSIONS: frozenset[str] = frozenset({
    "birthday",
    "birth_date",
    "occupation",
    "profession",
    "education",
    "major",
    "name",
    "preferred_address",
    "residence",
    "zodiac",
    "zodiac_or_blood_type",
    "blood_type",
})

MULTI_VALUE_DIMENSIONS: frozenset[str] = frozenset({
    "habit",
    "boundary",
    "commitment",
    "health",
    "relation",
    "schedule",
    "dislike",
})

#: Dimensions allowed to leave their source window.  Everything else stays
#: inside the conversation that produced it.
CROSS_SCENE_DIMENSIONS: frozenset[str] = frozenset({
    "preference",
    "dietary_restriction",
})

ASSERTION_MEMORY_TYPE = "assertion"

MAX_ASSERTIONS_PER_BATCH = 6
MAX_ASSERTION_VALUE_CHARS = 120


def normalize_predicate(raw: Any) -> str:
    """Map a model-supplied predicate onto the controlled dimension set."""
    value = clean_text(raw, 40).lower().replace("-", "_").replace(" ", "_")
    if value in ASSERTION_DIMENSIONS:
        return value
    aliases = {
        "profile": "habit",
        "profile_fact": "habit",
        "fact": "habit",
        "identity": "habit",
        "like": "preference",
        "likes": "preference",
        "favourite": "preference",
        "favorite": "preference",
        "taste": "preference",
        "diet": "dietary_restriction",
        "allergy": "dietary_restriction",
        "cannot_eat": "dietary_restriction",
        "habits": "habit",
        "routine": "habit",
        "limit": "boundary",
        "limits": "boundary",
        "boundary_rule": "boundary",
        "promise": "commitment",
        "agreement": "commitment",
        "appointment": "schedule",
        "plan": "schedule",
        "person": "relation",
        "relationship": "relation",
        "family": "relation",
        "health_condition": "health",
        "illness": "health",
        "dislikes": "dislike",
        "hate": "dislike",
        "address": "residence",
        "home": "residence",
        "住址": "residence",
        "居住地": "residence",
        "nickname": "preferred_address",
        "preferred_name": "preferred_address",
        "称呼": "preferred_address",
        "职业": "occupation",
        "job": "occupation",
        "profession": "occupation",
        "生日": "birthday",
        "星座": "zodiac",
        "血型": "blood_type",
        "学历": "education",
        "专业": "education",
    }
    return aliases.get(value, "")


def normalize_polarity(raw: Any, *, value: str) -> str:
    """Keep the polarity the evidence carries; never invent the opposite."""
    text = clean_text(raw, 20).lower()
    if text in {"positive", "negative"}:
        return text
    negative_markers = ("不喜欢", "不吃", "不能", "不要", "讨厌", "拒绝", "没有", "不再", "从不")
    return "negative" if any(marker in value for marker in negative_markers) else "positive"


def cardinality_for(dimension: str) -> str:
    return "single" if dimension in SINGLE_VALUE_DIMENSIONS else "multi"


def clean_assertion_value(raw: Any) -> str:
    """Reduce an assertion to a self-contained short clause.

    A value that has to be read together with the summary to make sense is a
    summary fragment, not an assertion, and must not be promoted.
    """
    text = clean_text(raw, MAX_ASSERTION_VALUE_CHARS)
    if not text:
        return ""
    text = text.strip().strip("。．.！!？?；;，,、 ")
    return text


def normalize_assertion(raw: Any) -> dict[str, Any]:
    """Return a normalized assertion, or ``{}`` when it cannot stand alone.

    Deliberately conservative: an assertion that fails here is dropped from the
    batch instead of failing it, because losing one claim must not cost the
    whole conversation its memory.
    """
    if not isinstance(raw, dict):
        return {}
    subject = clean_text(raw.get("subject"), 80)
    # Accept both the model's key and an already-normalized one, so applying
    # this twice is a no-op instead of silently dropping every assertion.
    predicate = normalize_predicate(raw.get("predicate") or raw.get("dimension"))
    value = clean_assertion_value(raw.get("value"))
    if not subject or not predicate or len(value) < 2:
        return {}
    polarity = normalize_polarity(raw.get("polarity"), value=value)
    durability = clean_text(raw.get("durability"), 20).lower()
    if durability not in {"stable", "situational"}:
        durability = "situational"
    refs = raw.get("refs")
    refs = [refs] if isinstance(refs, str) else refs
    if not isinstance(refs, list):
        refs = []
    refs = list(dict.fromkeys(
        clean_text(item, 160) for item in refs if clean_text(item, 160)
    ))[:4]
    qualifier = clean_text(raw.get("qualifier"), 120)
    return {
        "subject": subject,
        "dimension": predicate,
        "value": value,
        "polarity": polarity,
        "durability": durability,
        "qualifier": qualifier,
        "refs": refs,
        "normalized_value": normalize_profile_value(value),
    }


def assertion_is_promotable(
    assertion: dict[str, Any],
    evidence: list[str] | None = None,
) -> bool:
    """Only a durable, sourced, self-contained personal fact becomes memory.

    Everything else stays a candidate in the same batch, so widening the
    extractor can no longer inject an unsourced claim, a claim about somebody
    else, a temporary state, or an intention the user never carried out.
    """
    if not assertion:
        return False
    if assertion["durability"] != "stable":
        return False
    if not assertion.get("refs"):
        return False
    if len(assertion.get("value", "")) < 4:
        return False
    return claim_is_personal_fact(
        assertion.get("subject", ""), assertion.get("value", ""), evidence
    )[0]


__all__ = [
    "ASSERTION_DIMENSIONS",
    "ASSERTION_MEMORY_TYPE",
    "CROSS_SCENE_DIMENSIONS",
    "MAX_ASSERTIONS_PER_BATCH",
    "MULTI_VALUE_DIMENSIONS",
    "SINGLE_VALUE_DIMENSIONS",
    "assertion_is_promotable",
    "cardinality_for",
    "claim_is_personal_fact",
    "clean_assertion_value",
    "normalize_assertion",
    "normalize_polarity",
    "normalize_predicate",
]
