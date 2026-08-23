"""Memory-owned REQ-036 portrait capture, governance, and read boundary."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from ..unified_profile_contract import build_person_ref, validate_profile_dto
except ImportError:  # Existing standalone core.* test/import compatibility.
    from unified_profile_contract import (  # type: ignore[no-redef]
        build_person_ref,
        validate_profile_dto,
    )
from .models import SessionContext, clean_text
from .portrait import (
    build_evidence,
    cross_scene_whitelisted_fact,
    extract_explicit_candidates,
    portrait_access_decision,
    statement_fingerprint,
)
from .portrait_namespace import portrait_namespace_decision
from .portrait_renderer import render_portrait_items


class _PortraitServiceCore:
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

    async def read_summary(
        self,
        request: dict[str, Any],
        *,
        limit: int = 8,
        include_provenance: bool = False,
    ) -> dict[str, Any]:
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
            include_provenance=include_provenance,
        )
        return {**result, "decision": decision}

    async def render_readonly_portrait(
        self, request: dict[str, Any], *, limit: int = 16
    ) -> dict[str, Any]:
        """Render a traceable structured/text portrait over the read boundary."""
        from .portrait_renderer import PortraitRenderer

        return await PortraitRenderer(self).render(request, limit=limit)

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


@dataclass(frozen=True, slots=True)
class PortraitBackfillRequest:
    """Explicit, single-person historical portrait operation request."""

    target_person_id: str
    target_identity: str
    source_scopes: tuple[str, ...] = ("private",)
    from_time: str = ""
    to_time: str = ""
    operation_id: str = ""
    dry_run: bool = False

    @staticmethod
    def _normalize_utc_time(value: Any) -> str:
        """Normalize valid request bounds for lexicographic UTC SQL comparisons."""
        raw = clean_text(value, 80)
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            # Keep the original invalid value so ``validate`` reports the
            # request error instead of silently treating it as unbounded.
            return raw
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    def __post_init__(self) -> None:
        scopes = sorted(
            {
                clean_text(scope, 80)
                for scope in self.source_scopes
                if clean_text(scope, 80)
            }
        )
        object.__setattr__(self, "source_scopes", tuple(scopes[:16]))
        object.__setattr__(self, "from_time", self._normalize_utc_time(self.from_time))
        object.__setattr__(self, "to_time", self._normalize_utc_time(self.to_time))

    @classmethod
    def from_value(cls, value: Any) -> PortraitBackfillRequest:
        if isinstance(value, cls):
            return value
        source = value if isinstance(value, dict) else {}
        raw_scopes = source.get("source_scopes", ("private",))
        if isinstance(raw_scopes, str):
            raw_scopes = [raw_scopes]
        scopes: list[str] = []
        if isinstance(raw_scopes, (list, tuple, set)):
            for item in raw_scopes:
                scope = clean_text(item, 80)
                if scope and scope not in scopes:
                    scopes.append(scope)
        if not scopes:
            scopes = ["private"]
        # Scope sets are semantically unordered.  Canonicalizing them keeps
        # retries with the same scope set idempotent even when the caller's
        # input order differs.
        scopes = sorted(scopes)

        return cls(
            target_person_id=clean_text(source.get("target_person_id"), 80),
            target_identity=clean_text(source.get("target_identity"), 160),
            source_scopes=tuple(scopes[:16]),
            from_time=source.get("from_time"),
            to_time=source.get("to_time"),
            operation_id=clean_text(source.get("operation_id"), 120),
            dry_run=source.get("dry_run") is True,
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.target_person_id:
            errors.append("missing_target_person_id")
        if not self.target_identity:
            errors.append("missing_target_identity")
        if not self.operation_id:
            errors.append("missing_operation_id")
        if not self.source_scopes:
            errors.append("missing_source_scopes")
        for scope in self.source_scopes:
            if scope != "private" and not scope.startswith("private@") and not scope.startswith("group:"):
                errors.append("scope_not_allowed")
            if scope.startswith("private@") and not scope.split("@", 1)[1].strip():
                errors.append("scope_not_allowed")
            if scope.startswith("group:"):
                parts = scope.split(":", 2)
                if len(parts) < 3 or not parts[1].strip() or not parts[2].strip():
                    errors.append("scope_not_allowed")
        if any(scope == "group" for scope in self.source_scopes):
            errors.append("scope_not_allowed")
        if self.from_time:
            try:
                datetime.fromisoformat(self.from_time.replace("Z", "+00:00"))
            except (TypeError, ValueError, OverflowError):
                errors.append("from_time_invalid")
        if self.to_time:
            try:
                datetime.fromisoformat(self.to_time.replace("Z", "+00:00"))
            except (TypeError, ValueError, OverflowError):
                errors.append("to_time_invalid")
        if self.from_time and self.to_time:
            try:
                start = datetime.fromisoformat(self.from_time.replace("Z", "+00:00"))
                end = datetime.fromisoformat(self.to_time.replace("Z", "+00:00"))
                if start > end:
                    errors.append("time_range_invalid")
            except (TypeError, ValueError, OverflowError):
                pass
        return list(dict.fromkeys(errors))

    def payload(self) -> dict[str, Any]:
        return {
            "target_person_id": self.target_person_id,
            "target_identity": self.target_identity,
            "source_scopes": list(self.source_scopes),
            "from_time": self.from_time,
            "to_time": self.to_time,
            "operation_id": self.operation_id,
            "dry_run": bool(self.dry_run),
        }


class _PortraitBackfillMixin:
    """Implementation kept separate so existing capture/read paths stay stable."""

    @staticmethod
    def _backfill_truthy(value: Any) -> bool:
        if value is True:
            return True
        return clean_text(value, 24).lower() in {"1", "true", "yes", "y", "on"}

    @classmethod
    def _backfill_identity_values(cls, row: dict[str, Any]) -> set[str]:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        values = {clean_text(row.get("subject_id"), 160)}
        for key in (
            "source_identity_key", "origin_identity_key", "authenticated_identity",
            "author_identity_key", "identity_key", "sender_identity_key",
            "subject_identity_key", "authenticated_subject", "author_id", "sender_id",
        ):
            value = metadata.get(key)
            if isinstance(value, dict):
                value = value.get("key") or value.get("identity_key") or value.get("id")
            text = clean_text(value, 160)
            if text:
                values.add(text)
        identity = metadata.get("identity")
        if isinstance(identity, dict):
            for key in ("key", "identity_key", "authenticated", "author"):
                text = clean_text(identity.get(key), 160)
                if text:
                    values.add(text)
        for container_key in ("authenticated", "author", "sender"):
            container = metadata.get(container_key)
            if isinstance(container, dict):
                for key in ("key", "id", "identity_key", "authenticated_identity", "author_id", "sender_id"):
                    text = clean_text(container.get(key), 160)
                    if text:
                        values.add(text)
        return {value for value in values if value}

    @classmethod
    def _backfill_skip_reason(cls, row: dict[str, Any], target_identity: str) -> str:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        event_type = clean_text(row.get("event_type"), 80).lower()
        subject_kind = clean_text(row.get("subject_kind"), 40).lower()
        subject_role = clean_text(row.get("subject_role"), 40).lower()
        if (
            event_type.startswith(("bot", "assistant", "system"))
            or subject_kind in {"bot", "assistant", "system"}
            or subject_role in {"bot", "bot_self", "assistant", "system"}
            or cls._backfill_truthy(metadata.get("bot_generated"))
            or cls._backfill_truthy(metadata.get("is_bot"))
        ):
            return "bot_subject"
        for key in (
            "quoted", "is_quoted", "quote", "quoted_message", "reply", "replied", "is_reply", "reply_to",
            "forwarded", "is_forwarded", "forward", "forwarded_content", "synthetic", "unresolved",
            "identity_ambiguous", "third_party", "third_party_author", "context_only", "concatenated_context",
        ):
            value = metadata.get(key)
            if (isinstance(value, (dict, list, tuple, set)) and bool(value)) or cls._backfill_truthy(value):
                return "excluded_context"
        role = clean_text(metadata.get("author_role") or metadata.get("sender_role"), 40).lower()
        if role in {"bot", "assistant", "system", "third_party", "unknown"} or clean_text(metadata.get("sender_kind"), 40).lower() in {"bot", "assistant", "system"}:
            return "third_party"
        # If an authenticated identity field is present, it is authoritative;
        # a matching subject_id alone cannot override a contradictory sender
        # identity carried by an imported record.
        explicit_identity_values: set[str] = set()
        for key in (
            "source_identity_key", "origin_identity_key", "authenticated_identity",
            "author_identity_key", "identity_key", "sender_identity_key",
            "subject_identity_key", "authenticated_subject", "author_id", "sender_id",
        ):
            value = metadata.get(key)
            if isinstance(value, dict):
                value = value.get("key") or value.get("identity_key") or value.get("id")
            text = clean_text(value, 160)
            if text:
                explicit_identity_values.add(text)
        for container_key in ("identity", "authenticated", "author", "sender"):
            container = metadata.get(container_key)
            if isinstance(container, dict):
                for key in ("key", "id", "identity_key", "authenticated_identity", "author_id", "sender_id"):
                    text = clean_text(container.get(key), 160)
                    if text:
                        explicit_identity_values.add(text)
        if explicit_identity_values and (
            target_identity not in explicit_identity_values
            or any(value != target_identity for value in explicit_identity_values)
        ):
            return "identity_mismatch"
        if target_identity not in cls._backfill_identity_values(row):
            return "identity_mismatch"
        return ""

    @staticmethod
    def _backfill_source_key(row: dict[str, Any]) -> str:
        """Build a stable source key even when an imported record lacks a message ID."""
        source_kind = clean_text(row.get("source_kind"), 16) or "unknown"
        scope = clean_text(row.get("scope"), 80)
        message_id = clean_text(row.get("message_id"), 160)
        if message_id:
            return f"message:{source_kind}:{scope}:{message_id}"
        source_id = clean_text(row.get("source_id"), 160)
        content_hash = statement_fingerprint(row.get("content"))
        if content_hash:
            occurred_at = clean_text(row.get("occurred_at"), 80)
            return f"content:{source_kind}:{scope}:{occurred_at}:{content_hash}"
        return f"source:{source_kind}:{scope}:{source_id}" if source_id else ""

    async def _backfill_validate(self, req: PortraitBackfillRequest) -> tuple[dict[str, Any], dict[str, Any]]:
        errors = req.validate()
        if errors:
            return {"ok": False, "code": "invalid_request", "errors": errors}, {}
        person = await self.store.portrait_backfill_person(req.target_person_id, req.target_identity)
        if not person.get("ok"):
            return {"ok": False, "code": person.get("code", "identity_mismatch"), "errors": []}, {}
        for scope in req.source_scopes:
            capability = await self.store.portrait_backfill_scope_capability(req.target_person_id, scope)
            if scope.startswith("group:") and not bool(capability.get("configured")):
                return {"ok": False, "code": "scope_not_allowed", "scope": scope, "errors": []}, person
            if not bool(capability.get("portrait_learning_enabled")):
                return {"ok": False, "code": "scope_not_allowed", "scope": scope, "errors": []}, person
        return {"ok": True, "code": "profile_exact"}, person

    async def _backfill_scan(
        self,
        req: PortraitBackfillRequest,
        *,
        person: dict[str, Any],
        offset: int = 0,
        max_records: int = 5000,
        page_size: int = 100,
    ) -> dict[str, Any]:
        counts: dict[str, Any] = {
            "scanned": 0, "eligible_sources": 0, "candidate_count": 0,
            "proposed_fact_count": 0, "skipped": {}, "dimensions": {},
            "characters_read": 0, "next_offset": max(0, int(offset)), "exhausted": False,
        }
        started_at = time.monotonic()
        runtime_limit = max(1, min(3600, self.config.int("portrait.backfill_max_runtime_seconds", 30)))
        character_limit = max(1, min(10_000_000, self.config.int("portrait.backfill_max_characters", 200_000)))
        dimension_limit = max(1, min(128, self.config.int("portrait.backfill_max_dimensions", 32)))
        seen_sources: set[str] = set()
        while counts["scanned"] < max(1, int(max_records)):
            page = await self.store.list_portrait_history_sources(
                source_scopes=list(req.source_scopes), from_time=req.from_time, to_time=req.to_time,
                offset=counts["next_offset"], limit=min(page_size, max_records - counts["scanned"]),
            )
            if not page:
                counts["exhausted"] = True
                break
            counts["next_offset"] += len(page)
            for row in page:
                counts["scanned"] += 1
                source_id = clean_text(row.get("source_id"), 160)
                source_key = self._backfill_source_key(row)
                if source_key and source_key in seen_sources:
                    counts["skipped"]["duplicate_source"] = counts["skipped"].get("duplicate_source", 0) + 1
                    continue
                if source_key:
                    seen_sources.add(source_key)
                content = clean_text(row.get("content"), 4000)
                if counts["characters_read"] + len(content) > character_limit:
                    counts["skipped"]["character_limit"] = counts["skipped"].get("character_limit", 0) + 1
                    counts["paused_reason"] = "character_limit"
                    return counts
                counts["characters_read"] += len(content)
                if clean_text(row.get("scope"), 80) not in req.source_scopes:
                    reason = "scope_not_allowed"
                else:
                    reason = self._backfill_skip_reason(row, req.target_identity)
                if reason:
                    counts["skipped"][reason] = counts["skipped"].get(reason, 0) + 1
                    continue
                counts["eligible_sources"] += 1
                candidates = extract_explicit_candidates(row.get("content"))
                for candidate in candidates:
                    # Keep the existing explicit extractor and governance gate
                    # authoritative; no semantic/LLM extraction is introduced.
                    if candidate.get("quality_gate_passed") is False:
                        counts["skipped"]["quality_gate"] = counts["skipped"].get("quality_gate", 0) + 1
                        continue
                    if clean_text(candidate.get("sensitivity"), 24) == "high":
                        counts["skipped"]["sensitivity_gate"] = counts["skipped"].get("sensitivity_gate", 0) + 1
                        continue
                    counts["candidate_count"] += 1
                    dimension = clean_text(candidate.get("dimension"), 80)
                    if dimension not in counts["dimensions"] and len(counts["dimensions"]) >= dimension_limit:
                        counts["skipped"]["dimension_limit"] = counts["skipped"].get("dimension_limit", 0) + 1
                        continue
                    counts["dimensions"][dimension] = counts["dimensions"].get(dimension, 0) + 1
                    counts["proposed_fact_count"] += 1
                if time.monotonic() - started_at >= runtime_limit:
                    counts["skipped"]["runtime_limit"] = counts["skipped"].get("runtime_limit", 0) + 1
                    return counts
            if counts["scanned"] >= max_records or len(page) < page_size:
                # A short page is the only bounded exhaustion signal available
                # from the store's offset API.
                counts["exhausted"] = True
                break
        return counts

    @staticmethod
    def _backfill_public_counts(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "scanned": int(snapshot.get("scanned", 0) or 0),
            "eligible_sources": int(snapshot.get("eligible_sources", 0) or 0),
            "candidate_count": int(snapshot.get("candidate_count", 0) or 0),
            "accepted_fact_count": int(snapshot.get("accepted_fact_count", 0) or 0),
            "inferred_fact_count": int(snapshot.get("inferred_fact_count", 0) or 0),
            "characters_read": int(snapshot.get("characters_read", 0) or 0),
            "skipped": dict(snapshot.get("skipped", {})) if isinstance(snapshot.get("skipped"), dict) else {},
            "dimensions": dict(snapshot.get("dimensions", {})) if isinstance(snapshot.get("dimensions"), dict) else {},
            "paused_reason": clean_text(snapshot.get("paused_reason"), 80),
        }

    async def _backfill_process(self, req: PortraitBackfillRequest, person: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        max_records = max(1, min(50000, self.config.int("portrait.backfill_max_records", 5000)))
        page_size = max(1, min(500, self.config.int("portrait.backfill_page_size", 100)))
        runtime_limit = max(1, min(3600, self.config.int("portrait.backfill_max_runtime_seconds", 30)))
        character_limit = max(1, min(10_000_000, self.config.int("portrait.backfill_max_characters", 200_000)))
        dimension_limit = max(1, min(128, self.config.int("portrait.backfill_max_dimensions", 32)))
        invocation_characters = 0
        started_at = time.monotonic()
        offset = max(0, int(snapshot.get("next_offset", 0) or 0))
        # ``paused_reason`` describes the current invocation only.  Keeping a
        # previous budget marker here would make every resumed run pause again
        # even when the new invocation has fresh limits.
        snapshot.pop("paused_reason", None)
        target_ref = {
            "person_id": req.target_person_id,
            "resolved_identity_key": req.target_identity,
            "projection_revision": int(person.get("projection_revision") or 1),
            "identity_assurance": clean_text(person.get("identity_assurance"), 40),
            "profile_status": clean_text(person.get("profile_status"), 40),
        }
        snapshot.setdefault("created_fact_ids", [])
        snapshot.setdefault("created_fact_snapshots", {})
        snapshot.setdefault("touched_fact_ids", [])
        snapshot.setdefault("touched_fact_snapshots", {})
        snapshot.setdefault("created_evidence_hashes", [])
        snapshot.setdefault("created_queue_ids", [])
        snapshot.setdefault("skipped", {})
        snapshot.setdefault("dimensions", {})
        while snapshot.get("scanned", 0) < max_records and not bool(snapshot.get("exhausted")):
            if time.monotonic() - started_at >= runtime_limit:
                snapshot["paused_reason"] = "runtime_limit"
                break
            state = await self.store.portrait_backfill_operation(req.operation_id)
            if state and state.get("state") in {"cancelled", "rolled_back", "complete", "failed"}:
                snapshot["cancelled"] = True
                return snapshot
            for scope in req.source_scopes:
                capability = await self.store.portrait_backfill_scope_capability(
                    req.target_person_id, scope
                )
                if not bool(capability.get("portrait_learning_enabled")):
                    snapshot["paused_reason"] = "capability_disabled"
                    break
            if snapshot.get("paused_reason") == "capability_disabled":
                await self.store.update_portrait_backfill_operation(
                    req.operation_id, snapshot, state="paused"
                )
                return snapshot
            page = await self.store.list_portrait_history_sources(
                source_scopes=list(req.source_scopes), from_time=req.from_time, to_time=req.to_time,
                offset=offset, limit=min(page_size, max_records - int(snapshot.get("scanned", 0) or 0)),
            )
            if not page:
                snapshot["exhausted"] = True
                break
            page_offset = offset
            for row_index, row in enumerate(page):
                row_next_offset = page_offset + row_index + 1
                snapshot["scanned"] = int(snapshot.get("scanned", 0) or 0) + 1
                source_id = clean_text(row.get("source_id"), 160)
                source_key = self._backfill_source_key(row)
                if source_key and source_key in set(snapshot.get("processed_source_ids", [])):
                    snapshot["skipped"]["duplicate_source"] = snapshot["skipped"].get("duplicate_source", 0) + 1
                    snapshot["next_offset"] = row_next_offset
                    continue
                if source_key:
                    snapshot.setdefault("processed_source_ids", []).append(source_key)
                content = clean_text(row.get("content"), 4000)
                if invocation_characters + len(content) > character_limit:
                    snapshot["skipped"]["character_limit"] = snapshot["skipped"].get("character_limit", 0) + 1
                    if invocation_characters == 0:
                        # A single oversized source cannot ever fit this
                        # bounded invocation; skip it explicitly so resume
                        # cannot spin forever on the same row.
                        if source_key:
                            processed = snapshot.get("processed_source_ids", [])
                            if isinstance(processed, list) and source_key in processed:
                                processed.remove(source_key)
                        snapshot["scanned"] = max(0, int(snapshot.get("scanned", 0) or 0) - 1)
                        snapshot["next_offset"] = row_next_offset
                        continue
                    if source_key:
                        processed = snapshot.get("processed_source_ids", [])
                        if isinstance(processed, list) and source_key in processed:
                            processed.remove(source_key)
                    snapshot["scanned"] = max(0, int(snapshot.get("scanned", 0) or 0) - 1)
                    snapshot["next_offset"] = page_offset + row_index
                    snapshot["paused_reason"] = "character_limit"
                    break
                invocation_characters += len(content)
                snapshot["characters_read"] = int(snapshot.get("characters_read", 0) or 0) + len(content)
                reason = self._backfill_skip_reason(row, req.target_identity)
                if clean_text(row.get("scope"), 80) not in req.source_scopes:
                    reason = "scope_not_allowed"
                if reason:
                    snapshot["skipped"][reason] = snapshot["skipped"].get(reason, 0) + 1
                    snapshot["next_offset"] = row_next_offset
                    continue
                snapshot["eligible_sources"] = int(snapshot.get("eligible_sources", 0) or 0) + 1
                message_id = clean_text(row.get("message_id"), 160) or source_id
                candidates = extract_explicit_candidates(row.get("content"))
                if not candidates:
                    snapshot["skipped"]["no_candidate"] = snapshot["skipped"].get("no_candidate", 0) + 1
                    snapshot["next_offset"] = row_next_offset
                    continue
                evidence = build_evidence(
                    person_ref=target_ref,
                    scope=clean_text(row.get("scope"), 80),
                    session_id=clean_text(row.get("session_id"), 200),
                    message_id=message_id,
                    source_identity_key=req.target_identity,
                    text=row.get("content"),
                    context_refs=[source_id] if source_id else [],
                )
                evidence["operation_id"] = req.operation_id
                evidence_result = await self.store.add_portrait_evidence(evidence)
                if not evidence_result.get("ok"):
                    if evidence_result.get("code") == "operation_not_active":
                        snapshot["cancelled"] = True
                        return snapshot
                    if evidence_result.get("code") == "portrait_learning_disabled":
                        snapshot["paused_reason"] = "capability_disabled"
                        return snapshot
                    snapshot["skipped"]["evidence_error"] = snapshot["skipped"].get("evidence_error", 0) + 1
                    snapshot["next_offset"] = row_next_offset
                    continue
                if not evidence_result.get("created"):
                    snapshot["skipped"]["duplicate_evidence"] = snapshot["skipped"].get("duplicate_evidence", 0) + 1
                elif evidence["evidence_hash"] not in snapshot["created_evidence_hashes"]:
                    snapshot["created_evidence_hashes"].append(evidence["evidence_hash"])
                for candidate in candidates:
                    if candidate.get("quality_gate_passed") is False:
                        snapshot["skipped"]["quality_gate"] = snapshot["skipped"].get("quality_gate", 0) + 1
                        continue
                    if clean_text(candidate.get("sensitivity"), 24) == "high":
                        snapshot["skipped"]["sensitivity_gate"] = snapshot["skipped"].get("sensitivity_gate", 0) + 1
                        continue
                    snapshot["candidate_count"] = int(snapshot.get("candidate_count", 0) or 0) + 1
                    dimension = clean_text(candidate.get("dimension"), 80)
                    if dimension not in snapshot["dimensions"] and len(snapshot["dimensions"]) >= dimension_limit:
                        snapshot["skipped"]["dimension_limit"] = snapshot["skipped"].get("dimension_limit", 0) + 1
                        continue
                    snapshot["dimensions"][dimension] = snapshot["dimensions"].get(dimension, 0) + 1
                    source_scope = clean_text(row.get("scope"), 80)
                    existing = await self.store.get_portrait_backfill_fact(
                        person_id=req.target_person_id, dimension=dimension,
                        normalized_claim_hash=clean_text(candidate.get("normalized_claim_hash"), 80),
                        source_scope=source_scope, portrait_tier="base",
                    )
                    if existing is not None:
                        # A historical operation may extend its own candidate,
                        # but must never mutate an external official fact.
                        if clean_text(existing.get("operation_id"), 120) != req.operation_id:
                            snapshot["skipped"]["external_fact_protected"] = snapshot["skipped"].get("external_fact_protected", 0) + 1
                            snapshot["next_offset"] = row_next_offset
                            continue
                        append = await self.store.append_portrait_fact_evidence(
                            person_id=req.target_person_id,
                            fact_id=clean_text(existing.get("id"), 120),
                            evidence_hash=evidence["evidence_hash"],
                            context_refs=evidence["context_refs"],
                            operation_id=req.operation_id,
                        )
                        if append.get("ok"):
                            fact_key = clean_text(existing.get("id"), 120)
                            is_created_by_operation = fact_key in snapshot.get("created_fact_ids", [])
                            if not is_created_by_operation and fact_key not in snapshot["touched_fact_ids"]:
                                snapshot["touched_fact_ids"].append(fact_key)
                            previous = append.get("previous")
                            if isinstance(previous, dict) and append.get("created") and not is_created_by_operation:
                                snapshot["touched_fact_snapshots"].setdefault(fact_key, previous)
                                entry = snapshot["touched_fact_snapshots"][fact_key]
                                if isinstance(entry, dict):
                                    entry.setdefault("added_evidence_hashes", []).append(evidence["evidence_hash"])
                            created_snapshot = snapshot["created_fact_snapshots"].get(clean_text(existing.get("id"), 120))
                            if append.get("created") and isinstance(created_snapshot, dict):
                                created_snapshot.setdefault("evidence_hashes", []).append(evidence["evidence_hash"])
                                created_snapshot["evidence_hashes"] = list(dict.fromkeys(created_snapshot["evidence_hashes"]))[:16]
                                created_snapshot["revision"] = int(created_snapshot.get("revision") or 1) + 1
                            result_key = "existing_fact_evidence_appended" if append.get("created") else "existing_fact_evidence_duplicate"
                            snapshot["skipped"][result_key] = snapshot["skipped"].get(result_key, 0) + 1
                        else:
                            if append.get("code") == "operation_not_active":
                                snapshot["cancelled"] = True
                                return snapshot
                            if append.get("code") == "portrait_learning_disabled":
                                snapshot["paused_reason"] = "capability_disabled"
                                return snapshot
                            snapshot["skipped"][clean_text(append.get("code"), 80) or "existing_fact_rejected"] = snapshot["skipped"].get(clean_text(append.get("code"), 80) or "existing_fact_rejected", 0) + 1
                        snapshot["next_offset"] = row_next_offset
                        continue
                    fact = {
                        **candidate,
                        "person_id": req.target_person_id,
                        "portrait_tier": "base",
                        "source_scope": source_scope,
                        "usable_scope": "self_low_global"
                        if cross_scene_whitelisted_fact(
                            dimension=dimension,
                            claim_summary=candidate.get("claim_summary"),
                            sensitivity=candidate.get("sensitivity"),
                            source_scope=source_scope,
                        ) else "source_only",
                        "confidence": float(candidate.get("extraction_quality_score") or 0.0),
                        "status": clean_text(candidate.get("profile_state"), 40) or "candidate",
                        "evidence_hashes": [evidence["evidence_hash"]],
                        "context_refs": evidence["context_refs"],
                        "operation_id": req.operation_id,
                    }
                    result = await self.store.upsert_portrait_fact(fact)
                    if not result.get("ok"):
                        if result.get("code") == "operation_not_active":
                            snapshot["cancelled"] = True
                            return snapshot
                        if result.get("code") == "portrait_learning_disabled":
                            snapshot["paused_reason"] = "capability_disabled"
                            return snapshot
                        code = clean_text(result.get("code"), 80) or "fact_rejected"
                        snapshot["skipped"][code] = snapshot["skipped"].get(code, 0) + 1
                        snapshot["next_offset"] = row_next_offset
                        continue
                    queued = {"created": False}
                    if result.get("created"):
                        snapshot["created_fact_ids"].append(result["fact_id"])
                        snapshot["touched_fact_ids"].append(result["fact_id"])
                        snapshot["created_fact_snapshots"][result["fact_id"]] = {
                            "revision": int(result.get("revision") or 1),
                            "evidence_hashes": [evidence["evidence_hash"]],
                            "operation_id": req.operation_id,
                        }
                        snapshot["accepted_fact_count"] = int(snapshot.get("accepted_fact_count", 0) or 0) + 1
                        queued = await self.store.enqueue_portrait_learning(
                            person_id=req.target_person_id,
                            fact_id=result["fact_id"],
                            evidence_hash=evidence["evidence_hash"],
                            operation_id=req.operation_id,
                        )
                        if not queued.get("ok") and queued.get("code") == "operation_not_active":
                            snapshot["cancelled"] = True
                            return snapshot
                        if not queued.get("ok") and queued.get("code") == "portrait_learning_disabled":
                            snapshot["paused_reason"] = "capability_disabled"
                            return snapshot
                    if queued.get("created"):
                        snapshot["created_queue_ids"].append(queued.get("queue_id"))
                snapshot["next_offset"] = row_next_offset
                if time.monotonic() - started_at >= runtime_limit:
                    snapshot["paused_reason"] = "runtime_limit"
                    break
            offset = int(snapshot.get("next_offset", page_offset) or page_offset)
            if snapshot.get("paused_reason") in {"runtime_limit", "character_limit"}:
                await self.store.update_portrait_backfill_operation(req.operation_id, snapshot, state="paused")
                return snapshot
            if snapshot.get("scanned", 0) >= max_records or len(page) < page_size:
                snapshot["exhausted"] = True
            await self.store.update_portrait_backfill_operation(req.operation_id, snapshot, state="running")
        return snapshot

    async def _backfill_aggregate(self, req: PortraitBackfillRequest, snapshot: dict[str, Any]) -> dict[str, Any]:
        runner = getattr(self.store, "run_portrait_backfill_aggregation", None)
        if not callable(runner):
            return {"ok": True, "accepted": 0, "insufficient": int(snapshot.get("accepted_fact_count", 0) or 0)}
        result = await runner(
            operation_id=req.operation_id,
            person_id=req.target_person_id,
            min_independent_evidence=max(1, min(16, self.config.int("portrait.min_independent_evidence", 3))),
            fact_ids=list(dict.fromkeys(clean_text(item, 120) for item in snapshot.get("touched_fact_ids", []) if clean_text(item, 120))),
            queue_ids=list(dict.fromkeys(clean_text(item, 120) for item in snapshot.get("created_queue_ids", []) if clean_text(item, 120))),
        )
        if not result.get("ok"):
            if result.get("code") == "operation_not_active":
                snapshot["cancelled"] = True
            return result
        snapshot["inferred_fact_count"] = int(result.get("created", 0) or 0)
        snapshot["insufficient_evidence_count"] = int(result.get("insufficient", 0) or 0)
        aggregate_snapshots = result.get("created_fact_snapshots")
        if isinstance(aggregate_snapshots, dict):
            for fact_id, metadata in aggregate_snapshots.items():
                fact_key = clean_text(fact_id, 120)
                if fact_key and isinstance(metadata, dict):
                    snapshot.setdefault("created_fact_snapshots", {})[fact_key] = metadata
        for fact_id in result.get("created_fact_ids", []) if isinstance(result.get("created_fact_ids"), list) else []:
            if fact_id not in snapshot["created_fact_ids"]:
                snapshot["created_fact_ids"].append(fact_id)
        return result

    async def preview_history_backfill(self, request: Any) -> dict[str, Any]:
        req = PortraitBackfillRequest.from_value(request)
        validation, person = await self._backfill_validate(req)
        if not validation.get("ok"):
            return {**validation, "operation_id": req.operation_id, "dry_run": True}
        max_records = max(1, min(50000, self.config.int("portrait.backfill_max_records", 5000)))
        page_size = max(1, min(500, self.config.int("portrait.backfill_page_size", 100)))
        counts = await self._backfill_scan(req, person=person, max_records=max_records, page_size=page_size)
        return {
            "ok": True, "code": "dry_run_ready", "operation_id": req.operation_id, "dry_run": True,
            "target_person_id": req.target_person_id, "source_scopes": list(req.source_scopes),
            "from_time": req.from_time, "to_time": req.to_time,
            "counts": counts, "audit": self._backfill_public_counts(counts),
        }

    async def start_history_backfill(self, request: Any, *, actor: str = "administrator") -> dict[str, Any]:
        req = PortraitBackfillRequest.from_value(request)
        if req.dry_run:
            return await self.preview_history_backfill(req)
        validation, person = await self._backfill_validate(req)
        if not validation.get("ok"):
            return {**validation, "operation_id": req.operation_id, "dry_run": False}
        actor_value = clean_text(actor, 120) or "administrator"
        payload_hash = hashlib.sha256(
            json.dumps(
                {**req.payload(), "actor": actor_value},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        initial = {
            "actor": actor_value,
            "target_person_id": req.target_person_id, "target_identity_hash": hashlib.sha256(req.target_identity.encode("utf-8")).hexdigest(),
            "source_scopes": list(req.source_scopes), "from_time": req.from_time, "to_time": req.to_time,
            "next_offset": 0, "exhausted": False, "scanned": 0, "eligible_sources": 0, "candidate_count": 0,
            "accepted_fact_count": 0, "inferred_fact_count": 0, "characters_read": 0, "skipped": {}, "dimensions": {},
            "created_fact_ids": [], "created_evidence_hashes": [], "created_queue_ids": [], "processed_source_ids": [],
            "created_fact_snapshots": {},
            "touched_fact_ids": [],
            "touched_fact_snapshots": {},
        }
        operation = await self.store.create_portrait_backfill_operation(operation_id=req.operation_id, payload_hash=payload_hash, snapshot=initial)
        if not operation.get("ok"):
            return operation
        state = clean_text(operation.get("state"), 40)
        snapshot = operation.get("snapshot") if isinstance(operation.get("snapshot"), dict) else initial
        if state in {"complete", "rolled_back"}:
            return {"ok": True, "code": "backfill_idempotent_replay", "operation_id": req.operation_id, "state": state, "counts": self._backfill_public_counts(snapshot)}
        if state == "cancelled":
            return {"ok": False, "code": "backfill_cancelled", "operation_id": req.operation_id, "state": state, "counts": self._backfill_public_counts(snapshot)}
        try:
            snapshot = await self._backfill_process(req, person, snapshot)
        except Exception:
            # Persist a bounded diagnostic marker without storing source text or
            # exception details in the operation audit record.
            snapshot["last_error"] = "backfill_processing_failed"
            await self.store.update_portrait_backfill_operation(req.operation_id, snapshot, state="failed")
            return {
                "ok": False,
                "code": "backfill_failed",
                "operation_id": req.operation_id,
                "state": "failed",
                "counts": self._backfill_public_counts(snapshot),
            }
        # Cancellation may arrive while the current page is being committed.
        # Re-read the authoritative operation state before deciding whether to
        # aggregate or publish completion; a stale local snapshot must not
        # resurrect a cancelled operation.
        latest = await self.store.portrait_backfill_operation(req.operation_id)
        if latest and clean_text(latest.get("state"), 40) in {"cancelled", "rolled_back"}:
            snapshot["cancelled"] = True
        if bool(snapshot.get("cancelled")):
            final_state = "cancelled"
            code = "backfill_cancelled"
        elif bool(snapshot.get("exhausted")):
            try:
                aggregation = await self._backfill_aggregate(req, snapshot)
                if not aggregation.get("ok"):
                    if aggregation.get("code") == "operation_not_active":
                        snapshot["cancelled"] = True
                    else:
                        snapshot["last_error"] = "backfill_aggregation_failed"
                        await self.store.update_portrait_backfill_operation(req.operation_id, snapshot, state="failed")
                        return {
                            "ok": False,
                            "code": "backfill_failed",
                            "operation_id": req.operation_id,
                            "state": "failed",
                            "counts": self._backfill_public_counts(snapshot),
                        }
            except Exception:
                snapshot["last_error"] = "backfill_aggregation_failed"
                await self.store.update_portrait_backfill_operation(req.operation_id, snapshot, state="failed")
                return {
                    "ok": False,
                    "code": "backfill_failed",
                    "operation_id": req.operation_id,
                    "state": "failed",
                    "counts": self._backfill_public_counts(snapshot),
                }
            if snapshot.get("cancelled"):
                final_state = "cancelled"
                code = "backfill_cancelled"
            else:
                final_state = "complete"
                code = "backfill_complete"
        else:
            final_state = "paused"
            code = "backfill_paused"
        await self.store.update_portrait_backfill_operation(req.operation_id, snapshot, state=final_state)
        return {
            "ok": final_state != "cancelled", "code": code, "operation_id": req.operation_id, "state": final_state,
            "checkpoint": {"next_offset": int(snapshot.get("next_offset", 0) or 0), "exhausted": bool(snapshot.get("exhausted"))},
            "counts": self._backfill_public_counts(snapshot),
        }

    async def status_history_backfill(self, operation_id: str) -> dict[str, Any]:
        operation = await self.store.portrait_backfill_operation(clean_text(operation_id, 120))
        if operation is None:
            return {"ok": False, "code": "operation_not_found", "operation_id": clean_text(operation_id, 120)}
        if clean_text(operation.get("operation_kind"), 80) != "historical_portrait_backfill":
            return {"ok": False, "code": "operation_conflict", "operation_id": clean_text(operation_id, 120)}
        snapshot = operation.get("snapshot") if isinstance(operation.get("snapshot"), dict) else {}
        return {
            "ok": True, "code": "backfill_status", "operation_id": operation["operation_id"], "state": operation["state"],
            "checkpoint": {"next_offset": int(snapshot.get("next_offset", 0) or 0), "exhausted": bool(snapshot.get("exhausted"))},
            "counts": self._backfill_public_counts(snapshot),
            "last_error": clean_text(snapshot.get("last_error"), 120),
            "created_at": operation.get("created_at", ""), "updated_at": operation.get("updated_at", ""),
        }

    async def cancel_history_backfill(self, operation_id: str) -> dict[str, Any]:
        return await self.store.cancel_portrait_backfill_operation(clean_text(operation_id, 120))

    async def rollback_history_backfill(self, operation_id: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "code": "rollback_requires_confirmation", "operation_id": clean_text(operation_id, 120)}
        return await self.store.rollback_portrait_backfill_operation(clean_text(operation_id, 120))

    async def render_history_portrait(self, request: Any, *, limit: int = 32) -> dict[str, Any]:
        req = PortraitBackfillRequest.from_value(request)
        errors = req.validate()
        if errors:
            return {"ok": False, "code": "invalid_request", "errors": errors, "items": [], "groups": {}, "text": ""}
        person = await self.store.portrait_backfill_person(req.target_person_id, req.target_identity)
        if not person.get("ok"):
            return {"ok": False, "code": person.get("code", "identity_mismatch"), "items": [], "groups": {}, "text": ""}
        for scope in req.source_scopes:
            capability = await self.store.portrait_backfill_scope_capability(req.target_person_id, scope)
            if scope.startswith("group:") and not bool(capability.get("configured")):
                return {"ok": False, "code": "scope_not_allowed", "scope": scope, "items": [], "groups": {}, "text": ""}
            if not bool(capability.get("portrait_usage_enabled")):
                return {"ok": False, "code": "portrait_usage_disabled", "scope": scope, "items": [], "groups": {}, "text": ""}
        summary_reader = getattr(self.store, "portrait_summary", None)
        legacy_renderer = getattr(self.store, "render_portrait_facts", None)
        if not callable(summary_reader) and not callable(legacy_renderer):
            return {"ok": False, "code": "portrait_renderer_unavailable", "items": [], "groups": {}, "text": ""}
        if callable(summary_reader):
            # Reuse the established read policy (identity assurance,
            # capability, confidence, freshness, scope and suppression) for
            # the backfill renderer instead of maintaining a second filter.
            merged_items: list[dict[str, Any]] = []
            portrait_revision = 0
            last_synced_at = ""
            for scope in req.source_scopes:
                summary = await summary_reader(
                    req.target_person_id,
                    scope=scope,
                    limit=max(1, min(32, int(limit))),
                    low_only=True,
                    usage_min_confidence=self.config.float("portrait.usage_min_confidence", 0.75),
                    inferred_freshness_days=self.config.int("portrait.inferred_freshness_days", 90),
                    include_provenance=True,
                )
                if not isinstance(summary, dict) or not summary.get("ok"):
                    result = summary if isinstance(summary, dict) else {
                        "ok": False, "code": "portrait_renderer_unavailable", "items": []
                    }
                    break
                merged_items.extend(summary.get("items") if isinstance(summary.get("items"), list) else [])
                portrait_revision = max(portrait_revision, int(summary.get("portrait_revision") or 0))
                last_synced_at = clean_text(summary.get("last_synced_at"), 80) or last_synced_at
            else:
                seen_fact_ids: set[str] = set()
                unique_items: list[dict[str, Any]] = []
                for item in merged_items:
                    fact_id = clean_text((item.get("provenance") or {}).get("fact_id"), 120) if isinstance(item, dict) else ""
                    if fact_id and fact_id in seen_fact_ids:
                        continue
                    if fact_id:
                        seen_fact_ids.add(fact_id)
                    unique_items.append(item)
                result = {
                    "ok": True,
                    "code": "profile_exact",
                    "items": unique_items,
                    "portrait_revision": portrait_revision,
                    "last_synced_at": last_synced_at,
                }
        else:
            result = await legacy_renderer(
                person_id=req.target_person_id,
                source_scopes=list(req.source_scopes),
                limit=max(1, min(64, int(limit))),
                usage_min_confidence=self.config.float("portrait.usage_min_confidence", 0.75),
                inferred_freshness_days=self.config.int("portrait.inferred_freshness_days", 90),
            )
        result = result if isinstance(result, dict) else {}
        rendered = render_portrait_items(
            result.get("items"),
            portrait_revision=result.get("portrait_revision", 0),
            last_synced_at=result.get("last_synced_at", ""),
            person_id=req.target_person_id if result.get("ok") else "",
            code=clean_text(result.get("code"), 80) or "bridge_degraded",
            ok=bool(result.get("ok")),
        )
        return {
            **rendered,
            "target_person_id": req.target_person_id,
            "items": rendered.get("facts", []),
            # Compatibility aliases used by the first backfill API draft.
            "groups": rendered["dimensions"],
            "text": rendered["natural_language"],
        }

    # Short aliases make the six-phase contract convenient for callers while
    # retaining descriptive methods for existing plugin integrations.
    backfill_preview = preview_history_backfill
    backfill_start = start_history_backfill
    backfill_status = status_history_backfill
    backfill_cancel = cancel_history_backfill
    backfill_rollback = rollback_history_backfill
    backfill_render = render_history_portrait


class PortraitService(_PortraitServiceCore, _PortraitBackfillMixin):
    """Existing portrait runtime plus the opt-in historical backfill contract."""
