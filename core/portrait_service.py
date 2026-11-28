"""Memory-owned REQ-036 portrait capture, governance, and read boundary."""
from __future__ import annotations

from typing import Any

try:
    from ..unified_profile_contract import build_person_ref, build_profile_dto, validate_profile_dto
except ImportError:  # Existing standalone core.* test/import compatibility.
    from unified_profile_contract import (  # type: ignore[no-redef]
        build_person_ref,
        build_profile_dto,
        validate_profile_dto,
    )
from .local_time import local_now
from .models import EntityRef, SessionContext, clean_text
from .person_context_contract import build_identity_key, person_id_for_identity
from .portrait import (
    build_evidence,
    cross_scene_whitelisted_fact,
    extract_explicit_candidates,
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

    async def _self_built_memories(self, ctx: SessionContext, platform: str) -> list[dict[str, str]]:
        """Read the person's existing memories as portrait seed material.

        Only ids and contents are read here; the content is passed transiently
        to the deterministic extractor and never copied into portrait tables.
        """
        if not hasattr(self.store, "person_snapshot"):
            return []
        try:
            snapshot = await self.store.person_snapshot(
                user_id=clean_text(ctx.user_id, 120),
                platform=platform,
                bot_id=clean_text(ctx.bot_id, 120),
                limit=8,
                scope="private",
                group_id="",
                hide_pending=True,
                include_raw_events=False,
            )
        except Exception:
            return []
        rows = snapshot.get("memories") if isinstance(snapshot, dict) else None
        if not isinstance(rows, list):
            return []
        result: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            memory_id = clean_text(row.get("id"), 120)
            content = clean_text(row.get("content"), 2000)
            if memory_id and content:
                result.append({"id": memory_id, "content": content})
        return result

    async def _self_built_profile_dto(self, ctx: SessionContext, *, legacy_scope: str) -> dict[str, Any] | None:
        """Build the unified-profile DTO from data this plugin actually owns.

        Production bridges do not populate private_companion_unified_profile_context
        today, so the portrait subsystem reads the identity profile and existing
        memories instead.  With no identity profile there is nothing trustworthy
        to build from, and the caller skips gracefully instead of leaving dead code
        behind a property nobody writes.
        """
        if ctx is None or ctx.scope != "private":
            return None
        platform = clean_text(ctx.platform, 40).lower()
        user_id = clean_text(ctx.user_id, 120)
        if not platform or not user_id:
            return None
        entity = EntityRef(kind="user", id=user_id, name=clean_text(ctx.user_name, 80))
        try:
            profile = await self.store.identity_profile(platform=platform, entity=entity)
        except Exception:
            return None
        if not isinstance(profile, dict) or not profile:
            return None
        persona = clean_text(ctx.persona_id, 80)
        subject_namespace = "private" if not persona else f"private:persona:{persona}"
        identity = {
            "companion_instance_id": f"memory-companion:{clean_text(ctx.bot_id, 80) or platform}",
            "bot_account_id": clean_text(ctx.bot_id, 80) or "self",
            "adapter_instance_id": platform,
            "subject_namespace": subject_namespace,
            "platform_subject_id": user_id,
        }
        try:
            identity_key = build_identity_key(identity)
            person_id = person_id_for_identity(identity)
        except (KeyError, TypeError, ValueError):
            return None
        person_ref = {
            "person_id": person_id,
            "resolved_identity_key": identity_key,
            "projection_revision": 1,
            "identity_assurance": "observed",
            "profile_status": "active",
        }
        memories = await self._self_built_memories(ctx, platform)
        identity_summary = {
            "display_name": clean_text(ctx.user_name, 80),
            "relation_label": clean_text(profile.get("relation_label"), 80),
            "relation_address": clean_text(profile.get("relation_address"), 80),
            "relation_source": clean_text(profile.get("relation_source"), 40),
            "profile_source": "identity_profile",
        }
        expression_summary = {
            "memory_count": len(memories),
            "scope": clean_text(legacy_scope, 40),
            "source": "memory_self_built",
        }
        dto = build_profile_dto(
            person_ref=person_ref,
            identity_summary={key: value for key, value in identity_summary.items() if value},
            expression_summary=expression_summary,
            capability_summary={
                "private_companion_enabled": True,
                "proactive_private_enabled": False,
                "portrait_mode": "learn_and_use",
                "grant_source": "memory_self_built",
            },
            bridge_status={"mode": "memory_self_built", "namespace": subject_namespace},
        )
        if validate_profile_dto(dto):
            return None
        return {"dto": dto, "person_ref": build_person_ref(dto["person_ref"]), "memories": memories}

    async def sync_profile_context(
        self,
        *,
        event: Any = None,
        req: Any = None,
        legacy_scope: str = "private",
        ctx: SessionContext | None = None,
    ) -> dict[str, Any]:
        self_built: dict[str, Any] | None = None
        dto = self._profile_context(event, req)
        if dto is None and ctx is not None:
            self_built = await self._self_built_profile_dto(ctx, legacy_scope=legacy_scope)
            if self_built is None:
                return {"ok": False, "code": "portrait_profile_unavailable", "errors": [], "dto": None}
            dto = self_built["dto"]
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
            "self_built": self_built is not None,
            "seed_memories": list((self_built or {}).get("memories") or []),
        }

    async def _record_candidates(
        self,
        *,
        person_ref: dict[str, Any],
        scope: str,
        session_id: str,
        message_id: str,
        text: str,
    ) -> tuple[int, dict[str, Any]]:
        """Turn one piece of the person's own text into portrait facts."""
        candidates = extract_explicit_candidates(text)
        if not candidates:
            return 0, {}
        evidence = build_evidence(
            person_ref=person_ref,
            scope=scope,
            session_id=session_id,
            message_id=message_id,
            source_identity_key=person_ref["resolved_identity_key"],
            text=text,
        )
        evidence_result = await self.store.add_portrait_evidence(evidence)
        if not evidence_result.get("ok") or not evidence_result.get("created"):
            return 0, evidence_result
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
        return created, {}

    async def capture_user_message(self, ctx: SessionContext, *, event: Any = None, req: Any = None) -> dict[str, Any]:
        """Capture only a sender's own message as portrait evidence.

        The raw message is used transiently to derive a hash and deterministic
        explicit candidate.  It is never copied to the portrait tables.
        """
        scope = self._scope_for_context(ctx)
        if not scope:
            return {"ok": False, "code": "bridge_person_mismatch", "facts": 0}
        synced = await self.sync_profile_context(event=event, req=req, legacy_scope=scope, ctx=ctx)
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
        source_scope = str(synced.get("source_scope") or "")
        seeds = list(synced.get("seed_memories") or [])
        has_current = bool(extract_explicit_candidates(ctx.message_text))
        if not has_current and not seeds:
            return {
                "ok": True,
                "code": "portrait_no_candidate",
                "facts": 0,
                "person_id": person_ref["person_id"],
            }
        created, evidence_result = await self._record_candidates(
            person_ref=person_ref,
            scope=source_scope,
            session_id=ctx.session_id,
            message_id=ctx.message_id,
            text=ctx.message_text,
        )
        for memory in seeds:
            if not isinstance(memory, dict):
                continue
            memory_id = clean_text(memory.get("id"), 120)
            content = clean_text(memory.get("content"), 2000)
            if not memory_id or not content:
                continue
            more, _seed_result = await self._record_candidates(
                person_ref=person_ref,
                scope=source_scope,
                session_id=ctx.session_id,
                message_id=f"memory:{memory_id}",
                text=content,
            )
            created += more
        if created == 0 and evidence_result:
            return {
                "ok": bool(evidence_result.get("ok")),
                "code": evidence_result.get("code", "portrait_evidence_recorded"),
                "facts": 0,
                "person_id": person_ref["person_id"],
            }
        return {"ok": True, "code": "portrait_evidence_recorded", "facts": created, "person_id": person_ref["person_id"]}

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
            day = local_now().date().isoformat()
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
