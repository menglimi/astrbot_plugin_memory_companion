"""REQ-036 portrait facts, evidence normalization, and pre-retrieval policy."""
from __future__ import annotations

import hashlib
import re
from typing import Any

try:
    from ..unified_profile_contract import (
        LOW_SENSITIVITY,
        build_person_ref,
        validate_person_ref,
        validate_portrait_request,
    )
except ImportError:  # Existing standalone core.* test/import compatibility.
    from unified_profile_contract import (  # type: ignore[no-redef]
        LOW_SENSITIVITY,
        build_person_ref,
        validate_person_ref,
        validate_portrait_request,
    )
from .models import clean_text
from .profile_quality import RULE_EXTRACTOR, extract_profile_candidates

PORTRAIT_TIERS = frozenset({"base", "intelligent"})
SENSITIVITY_LEVELS = frozenset({"low", "sensitive", "high"})
SUPPRESSION_STATUSES = frozenset({"active", "reconfirmation_pending", "revoked", "superseded", "expired"})
PURPOSE_RESULT_CODES = {
    "adapt_for_subject": "profile_exact",
    "summarize_to_subject": "profile_exact",
    "disclose_to_third_party": "portrait_third_party_forbidden",
}

_SENSITIVE_TOKENS = (
    "疾病", "病史", "病情", "病历", "生病", "患病", "看病", "过敏", "治疗", "药物",
    "用药", "吃药", "服药", "医院", "政治", "宗教", "信仰", "性别", "性取向",
    "性生活", "性行为", "性经历", "性病", "性侵", "性骚扰", "住址", "地址", "定位",
    "行程", "财务", "工资", "密码", "账号", "身份证", "创伤", "自杀",
)
_CROSS_SCENE_PREFERENCE_MARKERS = (
    "吃", "喝", "食物", "料理", "烤肉", "火锅", "甜品", "咖啡", "茶",
    "音乐", "歌曲", "乐队", "电影", "影视", "剧", "动漫", "游戏", "桌游",
    "画画", "阅读", "摄影", "跑步", "运动",
)
_CROSS_SCENE_COMMUNICATION_MARKERS = (
    "简短", "详细", "直接", "委婉", "表情", "emoji", "中文", "英文", "日文",
    "语言", "语气", "称呼", "沟通", "回复",
)
_CROSS_SCENE_DENY_MARKERS = (
    "工作", "上班", "学习", "学校", "凌晨", "早上", "晚上", "睡", "作息",
    "地点", "住", "城市", "家", "朋友", "恋人", "健康",
)


def _text(value: Any, limit: int = 240) -> str:
    return clean_text(value, limit) if value is not None else ""


def normalized_claim_hash(dimension: Any, claim: Any) -> str:
    normalized = re.sub(r"\s+", "", _text(claim, 160).lower())
    raw = f"{_text(dimension, 80).lower()}:{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evidence_hash(*, person_id: Any, scope: Any, session_id: Any, message_id: Any, text: Any) -> str:
    raw = "|".join(
        (
            _text(person_id, 80),
            _text(scope, 80),
            _text(session_id, 200),
            _text(message_id, 120),
            _text(text, 1800),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def statement_fingerprint(text: Any) -> str:
    """Hash a normalized source statement without retaining its body.

    Message IDs keep event evidence auditable.  This separate fingerprint keeps
    mechanically repeated statements from becoming artificial independent
    evidence for one portrait claim.
    """
    normalized = re.sub(r"\s+", "", _text(text, 1800).lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def classify_sensitivity(claim: Any) -> str:
    text = _text(claim, 160).lower()
    if any(token.lower() in text for token in _SENSITIVE_TOKENS):
        return "high"
    return LOW_SENSITIVITY


def cross_scene_whitelisted_fact(
    *,
    dimension: Any,
    claim_summary: Any,
    sensitivity: Any,
    source_scope: Any,
) -> bool:
    """Return whether a fact may leave its source scope for its own subject.

    The first REQ-036 release is deliberately allowlist-only.  Low sensitivity
    alone is insufficient because work, schedule, location, and relationship
    details can be low-labelled yet still violate the frozen cross-scene policy.
    """
    normalized_scope = _text(source_scope, 80)
    if (
        _text(sensitivity, 24) != LOW_SENSITIVITY
        or not (normalized_scope == "private" or normalized_scope.startswith("private@"))
    ):
        return False
    normalized_dimension = _text(dimension, 80).lower()
    summary = _text(claim_summary, 180).lower()
    if not summary or any(marker in summary for marker in _CROSS_SCENE_DENY_MARKERS):
        return False
    if normalized_dimension == "preferred_address":
        return True
    if normalized_dimension == "communication_preference":
        return any(marker in summary for marker in _CROSS_SCENE_COMMUNICATION_MARKERS)
    if normalized_dimension == "preference":
        return any(marker in summary for marker in _CROSS_SCENE_PREFERENCE_MARKERS)
    return False


def extract_explicit_candidates(text: Any) -> list[dict[str, Any]]:
    """Extract only self-contained first-person statements without context text."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in extract_profile_candidates(text):
        dimension = _text(candidate.get("profile_dimension"), 80)
        kind = _text(candidate.get("kind"), 40)
        value = _text(candidate.get("profile_value"), 80)
        normalized_value = _text(candidate.get("normalized_value"), 80)
        summary = _text(candidate.get("claim_summary"), 180)
        if (
            not dimension
            or not kind
            or not value
            or not normalized_value
            or not summary
        ):
            continue
        claim_hash = normalized_claim_hash(dimension, f"{kind}:{normalized_value}")
        if claim_hash in seen:
            continue
        seen.add(claim_hash)
        item = {
            "dimension": dimension,
            "profile_dimension": dimension,
            "profile_value": value,
            "normalized_value": normalized_value,
            "profile_polarity": kind,
            "profile_cardinality": _text(candidate.get("profile_cardinality"), 16)
            or "multi",
            "normalized_claim_hash": claim_hash,
            "claim_summary": summary,
            "sensitivity": classify_sensitivity(f"{value} {summary}"),
            "producer_kind": "rule_explicit",
            "producer_version": "req036.rule.v2",
            "extractor": RULE_EXTRACTOR,
            "derivation_kind": "explicit_statement",
            "epistemic_status": "explicit",
            "extraction_quality": _text(candidate.get("extraction_quality"), 40)
            or "explicit",
            "extraction_quality_score": float(
                candidate.get("extraction_quality_score") or 0.0
            ),
            "evidence_strength": _text(candidate.get("evidence_strength"), 40)
            or "direct_statement",
            "profile_state": _text(candidate.get("profile_state"), 40) or "candidate",
            "quality_gate_passed": bool(candidate.get("quality_gate_passed")),
        }
        results.append(item)
    return results


def build_evidence(
    *,
    person_ref: Any,
    scope: Any,
    session_id: Any,
    message_id: Any,
    source_identity_key: Any,
    text: Any,
    context_refs: list[str] | None = None,
) -> dict[str, Any]:
    ref = build_person_ref(person_ref)
    return {
        "person_id": ref["person_id"],
        "origin_identity_key": _text(source_identity_key, 96) or ref["resolved_identity_key"],
        "scope": _text(scope, 80),
        "session_id": _text(session_id, 200),
        "message_id": _text(message_id, 120),
        "evidence_hash": evidence_hash(
            person_id=ref["person_id"],
            scope=scope,
            session_id=session_id,
            message_id=message_id,
            text=text,
        ),
        "statement_fingerprint": statement_fingerprint(text),
        "context_refs": [_text(item, 160) for item in (context_refs or []) if _text(item, 160)][:8],
    }


def portrait_access_decision(request: Any) -> dict[str, Any]:
    """Return before candidate retrieval; callers must obey candidates_allowed."""
    errors = validate_portrait_request(request)
    if errors:
        return {
            "allowed": False,
            "candidates_allowed": False,
            "code": "bridge_contract_mismatch",
            "errors": errors,
            "max_sensitivity": "",
        }
    payload = request if isinstance(request, dict) else {}
    person_ref = payload.get("person_ref") if isinstance(payload.get("person_ref"), dict) else {}
    ref_errors = validate_person_ref(person_ref)
    if ref_errors:
        return {
            "allowed": False,
            "candidates_allowed": False,
            "code": "bridge_person_mismatch",
            "errors": ref_errors,
            "max_sensitivity": "",
        }
    requester = _text(payload.get("requester_person_id"), 80)
    target = _text(payload.get("target_person_id"), 80)
    purpose = _text(payload.get("purpose"), 80)
    if purpose == "disclose_to_third_party" or not requester or requester != target:
        return {
            "allowed": False,
            "candidates_allowed": False,
            "code": "portrait_third_party_forbidden",
            "errors": [],
            "max_sensitivity": "",
        }
    if person_ref.get("person_id") != target or person_ref.get("profile_status") != "active":
        return {
            "allowed": False,
            "candidates_allowed": False,
            "code": "bridge_person_mismatch",
            "errors": [],
            "max_sensitivity": "",
        }
    if person_ref.get("identity_assurance") not in {"observed", "verified", "explicit_linked"}:
        return {
            "allowed": False,
            "candidates_allowed": False,
            "code": "bridge_person_mismatch",
            "errors": [],
            "max_sensitivity": "",
        }
    return {
        "allowed": True,
        "candidates_allowed": True,
        "code": PURPOSE_RESULT_CODES.get(purpose, "bridge_contract_mismatch"),
        "errors": [],
        "max_sensitivity": LOW_SENSITIVITY,
    }


def suppression_key(person_id: Any, dimension: Any, claim_hash: Any, scope: Any) -> str:
    raw = "|".join((_text(person_id, 80), _text(dimension, 80), _text(claim_hash, 80), _text(scope, 80)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [name for name in globals() if name.isupper() or name in {
    "build_evidence", "classify_sensitivity", "evidence_hash", "extract_explicit_candidates",
    "cross_scene_whitelisted_fact", "normalized_claim_hash", "portrait_access_decision", "statement_fingerprint", "suppression_key",
}]
