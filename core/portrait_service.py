"""Memory-owned REQ-036 portrait capture, governance, and read boundary."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from ..unified_profile_contract import build_person_ref, validate_profile_dto
except ImportError:  # Existing standalone core.* test/import compatibility.
    from unified_profile_contract import build_person_ref, validate_profile_dto  # type: ignore[no-redef]
from .models import SessionContext, clean_text
from .portrait import (
    build_evidence,
    cross_scene_whitelisted_fact,
    extract_explicit_candidates,
    normalized_claim_hash,
    portrait_access_decision,
)
from .portrait_namespace import portrait_namespace_decision


class PortraitService:
    def __init__(self, store: Any, config: Any) -> None:
        self.store = store
        self.config = config

    @staticmethod
    def _profile_context(event: Any = None, req: Any = None) -> dict[str, Any] | None:
        for source in (event, req):
            value = getattr(source, "private_companion_unified_profile_context", None) if source is not None else None
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _namespace_context(event: Any = None, req: Any = None) -> tuple[bool, Any]:
        for source in (event, req):
            if source is None:
                continue
            if isinstance(source, dict) and "namespace_context" in source:
                return True, source.get("namespace_context")
            if hasattr(source, "private_companion_namespace_context"):
                return True, getattr(source, "private_companion_namespace_context", None)
        return False, None

    async def sync_profile_context(
        self,
        *,
        event: Any = None,
        req: Any = None,
        legacy_scope: str = "private",
    ) -> dict[str, Any]:
        dto = self._profile_context(event, req)
        errors = validate_profile_dto(dto)
        if errors:
            return {"ok": False, "code": "bridge_contract_mismatch", "errors": errors, "dto": None}
        assert isinstance(dto, dict)
        person_ref = build_person_ref(dto["person_ref"])
        namespace_present, namespace_value = self._namespace_context(event, req)
        namespace = portrait_namespace_decision(
            namespace_value,
            person_id=person_ref.get("person_id"),
            legacy_scope=legacy_scope,
            purpose="profile_write",
            namespace_present=namespace_present,
        )
        if not namespace.get("ok"):
            return {"ok": False, "code": namespace.get("code"), "errors": [], "dto": dto}
        result = await self.store.upsert_portrait_person_projection(
            person_ref,
            dto["capability_summary"],
            source_scope=str(namespace.get("source_scope") or ""),
        )
        if not result.get("ok"):
            return {"ok": False, "code": result.get("code", "bridge_degraded"), "errors": [], "dto": dto}
        if person_ref["profile_status"] != "active" or person_ref["identity_assurance"] not in {"observed", "verified", "explicit_linked"}:
            return {"ok": False, "code": "bridge_person_mismatch", "errors": [], "dto": dto}
        return {
            "ok": True,
            "code": "profile_exact",
            "errors": [],
            "dto": dto,
            "person_ref": person_ref,
            "source_scope": str(namespace.get("source_scope") or ""),
            "legacy_scope": str(namespace.get("legacy_scope") or ""),
        }

    async def capture_user_message(self, ctx: SessionContext, *, event: Any = None, req: Any = None) -> dict[str, Any]:
        """Capture only a sender's own message as portrait evidence.

        The raw message is used transiently to derive a hash and deterministic
        explicit candidate.  It is never copied to the portrait tables.
        """
        scope = self._scope_for_context(ctx)
        if not scope:
            return {"ok": False, "code": "bridge_person_mismatch", "facts": 0}
        synced = await self.sync_profile_context(event=event, req=req, legacy_scope=scope)
        if not synced.get("ok"):
            return {"ok": False, "code": synced.get("code", "bridge_degraded"), "facts": 0}
        person_ref = synced["person_ref"]
        capabilities = synced["dto"].get("capability_summary", {})
        if not bool(capabilities.get("portrait_learning_enabled")):
            return {
                "ok": False,
                "code": "portrait_learning_disabled",
                "facts": 0,
                "person_id": person_ref["person_id"],
            }
        candidates = extract_explicit_candidates(ctx.message_text)
        if not candidates:
            return {
                "ok": True,
                "code": "portrait_no_candidate",
                "facts": 0,
                "person_id": person_ref["person_id"],
            }
        scope = str(synced.get("source_scope") or "")
        evidence = build_evidence(
            person_ref=person_ref,
            scope=scope,
            session_id=ctx.session_id,
            message_id=ctx.message_id,
            source_identity_key=person_ref["resolved_identity_key"],
            text=ctx.message_text,
        )
        evidence_result = await self.store.add_portrait_evidence(evidence)
        if not evidence_result.get("ok") or not evidence_result.get("created"):
            return {"ok": bool(evidence_result.get("ok")), "code": evidence_result.get("code", "portrait_evidence_recorded"), "facts": 0}
        created = 0
        for candidate in candidates:
            fact = {
                **candidate,
                "person_id": person_ref["person_id"],
                "portrait_tier": "base",
                "source_scope": scope,
                "usable_scope": "self_low_global"
                if cross_scene_whitelisted_fact(
                    dimension=candidate["dimension"],
                    claim_summary=candidate["claim_summary"],
                    sensitivity=candidate["sensitivity"],
                    source_scope=scope,
                )
                else "source_only",
                "confidence": float(candidate.get("extraction_quality_score") or 0.0),
                "status": clean_text(candidate.get("profile_state"), 40) or "candidate",
                "evidence_hashes": [evidence["evidence_hash"]],
                "context_refs": evidence["context_refs"],
                "operation_id": f"portrait.explicit:{evidence['evidence_hash'][:24]}",
            }
            result = await self.store.upsert_portrait_fact(fact)
            if result.get("ok"):
                created += 1
                await self.store.enqueue_portrait_learning(
                    person_id=person_ref["person_id"],
                    fact_id=result["fact_id"],
                    evidence_hash=evidence["evidence_hash"],
                )
        return {"ok": True, "code": "portrait_evidence_recorded", "facts": created, "person_id": person_ref["person_id"]}

    async def record_group_moment_portrait(
        self,
        person_ref: Any,
        candidates: list[dict[str, Any]],
        *,
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
        message_id: str = "",
    ) -> dict[str, Any]:
        """把私伴群聊名场面收敛的画像候选沉降到画像车道。

        只接受"群内互动型"维度（communication_preference / boundary），并把
        事实标记为 ``producer_kind="group_moment"``、``epistemic_status="observed"``，
        与用户自述（explicit/inferred）车道隔离，避免把名场面当作客观事实。
        证据与事实照常走 hash 化 + portrait_learning_queue，可参与每日聚合。
        """
        ref = build_person_ref(person_ref) if isinstance(person_ref, dict) else {}
        person_id = clean_text(ref.get("person_id"), 80)
        if not person_id:
            return {"ok": False, "code": "bridge_person_mismatch", "facts": 0}
        if not isinstance(candidates, list) or not candidates:
            return {"ok": True, "code": "portrait_no_candidate", "facts": 0, "person_id": person_id}
        allowed_dimensions = {"communication_preference", "boundary"}
        created = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            dimension = clean_text(candidate.get("dimension"), 80).lower()
            if dimension not in allowed_dimensions:
                continue
            claim_summary = clean_text(candidate.get("claim"), 300)
            evidence_text = clean_text(candidate.get("evidence_text"), 300)
            if not claim_summary or not evidence_text:
                continue
            normalized_claim = clean_text(candidate.get("claim_summary"), 300) or claim_summary
            claim_hash = normalized_claim_hash(dimension, f"group_moment:{normalized_claim}")
            evidence = build_evidence(
                person_ref=ref,
                scope=clean_text(scope, 80),
                session_id=clean_text(session_id, 200),
                message_id=clean_text(message_id, 120),
                source_identity_key=ref.get("resolved_identity_key"),
                text=evidence_text,
                context_refs=[f"group:{clean_text(group_id, 160)}"] if group_id else [],
            )
            evidence_result = await self.store.add_portrait_evidence(evidence)
            if not evidence_result.get("ok") or not evidence_result.get("created"):
                continue
            fact = {
                "person_id": person_id,
                "dimension": dimension,
                "normalized_claim_hash": claim_hash,
                "claim_summary": normalized_claim,
                "portrait_tier": "base",
                "producer_kind": "group_moment",
                "producer_version": "group_moments.v1",
                "derivation_kind": "observed",
                "epistemic_status": "observed",
                "source_scope": clean_text(scope, 80),
                "usable_scope": "source_only",
                "confidence": 0.55,
                "sensitivity": "low" if dimension != "boundary" else "sensitive",
                "status": "active",
                "evidence_hashes": [evidence["evidence_hash"]],
                "context_refs": evidence["context_refs"],
                "operation_id": f"portrait.group_moment:{evidence['evidence_hash'][:24]}",
            }
            fact_result = await self.store.upsert_portrait_fact(fact)
            if fact_result.get("ok"):
                created += 1
                await self.store.enqueue_portrait_learning(
                    person_id=person_id,
                    fact_id=fact_result["fact_id"],
                    evidence_hash=evidence["evidence_hash"],
                )
        return {"ok": True, "code": "portrait_group_moment_recorded", "facts": created, "person_id": person_id}

    async def read_summary(self, request: dict[str, Any], *, limit: int = 8) -> dict[str, Any]:
        decision = portrait_access_decision(request)
        if not decision["candidates_allowed"]:
            return {"ok": False, "code": decision["code"], "items": [], "decision": decision}
        person_ref = request.get("person_ref") if isinstance(request.get("person_ref"), dict) else {}
        namespace = portrait_namespace_decision(
            request.get("namespace_context"),
            person_id=request.get("target_person_id"),
            legacy_scope=request.get("scope"),
            purpose="profile_read",
            namespace_present="namespace_context" in request,
        )
        if not namespace.get("ok"):
            return {
                "ok": False,
                "code": namespace.get("code", "portrait_namespace_invalid"),
                "items": [],
                "decision": decision,
            }
        projection = await self.store.portrait_projection_decision(person_ref)
        if not projection.get("ok"):
            return {
                "ok": False,
                "code": clean_text(projection.get("code"), 80) or "bridge_degraded",
                "items": [],
                "decision": decision,
            }
        target = clean_text(request.get("target_person_id"), 80)
        result = await self.store.portrait_summary(
            target,
            scope=str(namespace.get("source_scope") or ""),
            legacy_scope=str(namespace.get("legacy_scope") or ""),
            limit=max(1, min(16, int(limit))),
            low_only=True,
            usage_min_confidence=self.config.float("portrait.usage_min_confidence", 0.75),
            inferred_freshness_days=self.config.int("portrait.inferred_freshness_days", 90),
        )
        return {**result, "decision": decision}

    @staticmethod
    def _scope_for_context(ctx: SessionContext) -> str:
        if ctx.scope == "private":
            return "private"
        if ctx.scope != "group":
            return ""
        platform = clean_text(ctx.platform, 40).lower()
        group_id = clean_text(ctx.group_id, 120)
        if not platform or not group_id:
            return ""
        return f"group:{platform}:{group_id}"

    async def run_daily_batch(self, person_id: str, *, run_day: str = "") -> dict[str, Any]:
        day = clean_text(run_day, 16)
        if not day:
            day = datetime.now(timezone.utc).astimezone().date().isoformat()
        return await self.store.run_portrait_daily_batch(
            person_id=person_id,
            run_day=day,
            min_independent_evidence=self.config.int("portrait.min_independent_evidence", 3),
            success_limit=self.config.int("portrait.daily_success_limit_per_person", 1),
            attempt_limit=self.config.int("portrait.daily_attempt_limit_per_person", 2),
        )

    async def list_governance_profiles(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return await self.store.list_portrait_people(limit=limit)

    async def status(self, person_id: str) -> dict[str, Any]:
        return await self.store.portrait_status(clean_text(person_id, 80))

    async def governance_detail(self, person_id: str) -> dict[str, Any]:
        return await self.store.portrait_governance_detail(clean_text(person_id, 80))

    async def govern_fact(
        self,
        *,
        person_id: str,
        fact_id: str,
        action: str,
        actor: str = "page_administrator",
        operation_id: str,
        expires_at: str = "",
    ) -> dict[str, Any]:
        """Apply only non-reopening administrator governance actions.

        A user denial is never silently reopened here.  Any later replacement
        needs an authorized self-confirmation flow or a separate reviewed
        operation that creates a new fact.
        """
        return await self.store.govern_portrait_fact(
            person_id=clean_text(person_id, 80),
            fact_id=clean_text(fact_id, 120),
            action=clean_text(action, 40),
            actor=clean_text(actor, 80) or "page_administrator",
            operation_id=clean_text(operation_id, 120),
            expires_at=clean_text(expires_at, 80),
        )

    async def migrate_legacy(self, *, operation_id: str, dry_run: bool = True) -> dict[str, Any]:
        return await self.store.portrait_migration(
            operation_id=clean_text(operation_id, 120),
            dry_run=bool(dry_run),
        )

    async def rollback_legacy_migration(self, *, operation_id: str) -> dict[str, Any]:
        return await self.store.rollback_portrait_migration(operation_id=clean_text(operation_id, 120))
