"""Process-local Memory acceptance fixtures for the isolated AstrBot Test Lab.

Fixture records never enter either Memory database.  They are materialized as
synthetic candidates only for an exact run UMO/actor, then passed through the
normal visibility and ACL validator by :mod:`core.service`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import hashlib
import importlib
import json
import re
from threading import RLock
from typing import Any

from .core.models import EntityRef, MemoryRecord, SessionContext, clean_text


PLUGIN_ID = "astrbot_plugin_memory_companion"
SCHEMA = "memory.acceptance_state.v1"
MAX_ACTIVE_RUNS = 32
MAX_PAYLOAD_BYTES = 8 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SYNTHETIC_MARKER = re.compile(
    r"^LAB[_:-][A-Za-z0-9_:\-\u4e00-\u9fff]{1,75}$",
    re.IGNORECASE,
)
_RECORD_KINDS = frozenset(
    {"private_memory", "foreign_private_memory", "group_memory", "profile"}
)
_ROOT_KEYS = frozenset({"records"})
_RECORD_KEYS = frozenset({"record_key", "record_kind", "marker", "match_terms"})
_SERIALIZABLE_CAPABILITY_TYPES = (
    str,
    bytes,
    bytearray,
    bool,
    int,
    float,
    list,
    tuple,
    dict,
    set,
    frozenset,
)


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:limit]


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _require_process_capability(capability: object) -> None:
    if capability is None or isinstance(capability, _SERIALIZABLE_CAPABILITY_TYPES):
        raise PermissionError("process-local fixture capability required")


def _normalized_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if set(payload) - _ROOT_KEYS:
        raise ValueError("unsupported Memory fixture field")
    try:
        encoded = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("fixture payload must be JSON-compatible") from exc
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValueError("fixture payload exceeds 8 KiB")

    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not 1 <= len(raw_records) <= 8:
        raise ValueError("records must contain 1..8 synthetic records")
    records: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw in raw_records:
        if not isinstance(raw, Mapping) or set(raw) - _RECORD_KEYS:
            raise ValueError("Memory fixture record has unsupported fields")
        raw_record_key = raw.get("record_key")
        raw_record_kind = raw.get("record_kind")
        raw_marker = raw.get("marker")
        if not all(
            isinstance(value, str)
            for value in (raw_record_key, raw_record_kind, raw_marker)
        ):
            raise ValueError("record_key, record_kind and marker must be strings")
        record_key = _text(raw_record_key, 64)
        if not _IDENTIFIER.fullmatch(record_key) or record_key in seen_keys:
            raise ValueError("record_key is invalid or duplicated")
        seen_keys.add(record_key)
        record_kind = _text(raw_record_kind, 32).lower()
        if record_kind not in _RECORD_KINDS:
            raise ValueError("record_kind is invalid")
        marker = _text(raw_marker, 80)
        if not _SYNTHETIC_MARKER.fullmatch(marker):
            raise ValueError("marker must use the LAB_ synthetic namespace")
        raw_terms = raw.get("match_terms")
        if not isinstance(raw_terms, list) or not 1 <= len(raw_terms) <= 4:
            raise ValueError("match_terms must contain 1..4 synthetic terms")
        terms: list[str] = []
        for raw_term in raw_terms:
            if not isinstance(raw_term, str):
                raise ValueError("match terms must be strings")
            term = _text(raw_term, 80)
            if not _SYNTHETIC_MARKER.fullmatch(term):
                raise ValueError("match terms must use the LAB_ synthetic namespace")
            if term.casefold() not in {item.casefold() for item in terms}:
                terms.append(term)
        records.append(
            {
                "record_key": record_key,
                "record_kind": record_kind,
                "marker": marker,
                "match_terms": tuple(terms),
            }
        )
    return {"records": tuple(records)}


class MemoryLabFixtureAdapter:
    """Own run-scoped specifications and materialize no persistent state."""

    fixture_schemas = (SCHEMA,)
    fixture_capabilities = ("final_projection", "residual_projection")

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._overlays: dict[str, dict[str, Any]] = {}
        self._closed = False
        self._lock = RLock()

    def prepare_fixture(
        self,
        run_id: str,
        schema: str,
        scope: Mapping[str, Any],
        payload: Mapping[str, Any],
        capability: object,
    ) -> None:
        _require_process_capability(capability)
        if not isinstance(run_id, str) or not isinstance(schema, str):
            raise ValueError("run_id and schema must be strings")
        clean_run_id = _text(run_id, 128)
        if not _IDENTIFIER.fullmatch(clean_run_id):
            raise ValueError("run_id is invalid")
        if schema != SCHEMA:
            raise ValueError("unsupported Memory fixture schema")
        if not isinstance(scope, Mapping) or not isinstance(payload, Mapping):
            raise ValueError("fixture scope and payload must be objects")
        raw_umo = scope.get("effective_umo")
        raw_actor_id = scope.get("effective_actor_id")
        if not isinstance(raw_umo, str) or not isinstance(raw_actor_id, str):
            raise ValueError("effective_umo and effective_actor_id must be strings")
        effective_umo = _text(raw_umo, 240)
        effective_actor_id = _text(raw_actor_id, 160)
        if not effective_umo or not effective_actor_id:
            raise ValueError("effective_umo and effective_actor_id are required")
        normalized = _normalized_payload(payload)

        stats = self._cache_stats()
        with self._lock:
            if self._closed:
                raise RuntimeError("Memory fixture adapter is closed")
            if clean_run_id in self._overlays:
                raise ValueError("one Memory fixture is allowed per run")
            if len(self._overlays) >= MAX_ACTIVE_RUNS:
                raise RuntimeError("too many active Memory fixtures")
            if any(
                item["effective_umo"] == effective_umo
                and item["effective_actor_id"] == effective_actor_id
                for item in self._overlays.values()
            ):
                raise RuntimeError("Memory fixture scope is already active")

            overlay = {
                "schema": SCHEMA,
                "effective_umo": effective_umo,
                "effective_actor_id": effective_actor_id,
                "payload": normalized,
                "cache_baseline": stats,
                "candidate_read_count": 0,
                "term_match_count": 0,
                "visible_count": 0,
                "blocked_count": 0,
                "last_block_families": (),
                "last_cache_state": "unknown",
            }
            self._overlays = {**self._overlays, clean_run_id: overlay}

    def describe_applied_fixture(self, run_id: str) -> Mapping[str, Any]:
        clean_run_id = _text(run_id, 128)
        with self._lock:
            overlay = self._overlays.get(clean_run_id)
            overlay = dict(overlay) if overlay is not None else None
        if overlay is None:
            raise KeyError("Memory fixture is not active")
        kind_counts = Counter(
            item["record_kind"] for item in overlay["payload"]["records"]
        )
        current_stats = self._cache_stats()
        baseline = overlay["cache_baseline"]
        cache_delta = {
            key: max(0, int(current_stats.get(key, 0)) - int(baseline.get(key, 0)))
            for key in ("hits", "misses", "evictions")
        }
        return {
            "active": True,
            "schema": SCHEMA,
            "run_digest": _digest(clean_run_id),
            "scope_digest": _digest(overlay["effective_umo"]),
            "actor_digest": _digest(overlay["effective_actor_id"]),
            "records": {
                "count": len(overlay["payload"]["records"]),
                "private_memory": int(kind_counts.get("private_memory", 0)),
                "foreign_private_memory": int(
                    kind_counts.get("foreign_private_memory", 0)
                ),
                "group_memory": int(kind_counts.get("group_memory", 0)),
                "profile": int(kind_counts.get("profile", 0)),
            },
            "observations": {
                "candidate_read_count": int(overlay["candidate_read_count"]),
                "term_match_count": int(overlay["term_match_count"]),
                "visible_count": int(overlay["visible_count"]),
                "blocked_count": int(overlay["blocked_count"]),
                "last_block_families": list(overlay["last_block_families"]),
                "last_cache_state": overlay["last_cache_state"],
            },
            "cache": cache_delta,
        }

    def release_fixture(self, run_id: str) -> None:
        clean_run_id = _text(run_id, 128)
        with self._lock:
            if clean_run_id not in self._overlays:
                return
            self._overlays = {
                key: value for key, value in self._overlays.items() if key != clean_run_id
            }

    def describe_released_fixture(self, run_id: str) -> Mapping[str, Any]:
        clean_run_id = _text(run_id, 128)
        with self._lock:
            active = clean_run_id in self._overlays
        return {
            "active": active,
            "residual_count": int(active),
            "residual_status": "present" if active else "clear",
        }

    def close(self) -> None:
        with self._lock:
            self._overlays = {}
            self._closed = True
            self._service = None

    def active_for_context(self, ctx: SessionContext | Any) -> bool:
        return self._matching_overlay(ctx) is not None

    def candidates_for_context(
        self,
        ctx: SessionContext,
        retrieval_text: str,
    ) -> list[MemoryRecord]:
        matched = self._matching_overlay(ctx)
        if matched is None:
            return []
        run_id, overlay = matched
        source = clean_text(retrieval_text, 1400).casefold()
        selected_specs = [
            spec
            for spec in overlay["payload"]["records"]
            if any(term.casefold() in source for term in spec["match_terms"])
        ]
        if not self._update(
            run_id,
            candidate_read_count=int(overlay["candidate_read_count"]) + 1,
            term_match_count=int(overlay["term_match_count"]) + len(selected_specs),
        ):
            return []
        return [self._record_for_context(run_id, spec, ctx) for spec in selected_specs]

    def record_selection(
        self,
        ctx: SessionContext,
        visible: list[Any],
        blocked: list[Mapping[str, Any]],
        *,
        cache_state: Any = "unknown",
    ) -> None:
        matched = self._matching_overlay(ctx)
        if matched is None:
            return
        run_id, overlay = matched
        visible_count = sum(
            1
            for item in visible or []
            if self.is_fixture_memory_id(getattr(getattr(item, "memory", None), "id", ""))
        )
        fixture_blocked = [
            item
            for item in blocked or []
            if isinstance(item, Mapping) and self.is_fixture_memory_id(item.get("id"))
        ]
        families = tuple(
            dict.fromkeys(
                _text(item.get("reason"), 180).split(";", 1)[0].split(":", 1)[0]
                for item in fixture_blocked
                if _text(item.get("reason"), 180)
            )
        )[:8]
        normalized_cache = _text(cache_state, 24).lower()
        if normalized_cache not in {"hit", "miss", "disabled", "unknown"}:
            normalized_cache = "unknown"
        self._update(
            run_id,
            visible_count=int(overlay["visible_count"]) + visible_count,
            blocked_count=int(overlay["blocked_count"]) + len(fixture_blocked),
            last_block_families=families,
            last_cache_state=normalized_cache,
        )

    @staticmethod
    def is_fixture_memory_id(memory_id: Any) -> bool:
        return _text(memory_id, 120).startswith("labfx_")

    def _matching_overlay(
        self,
        ctx: SessionContext | Any,
    ) -> tuple[str, dict[str, Any]] | None:
        if ctx is None:
            return None
        umo = _text(getattr(ctx, "session_id", ""), 240)
        actor_id = _text(getattr(ctx, "user_id", ""), 160)
        if not umo or not actor_id:
            return None
        with self._lock:
            if self._closed:
                return None
            for run_id, overlay in self._overlays.items():
                if (
                    overlay["effective_umo"] == umo
                    and overlay["effective_actor_id"] == actor_id
                ):
                    return run_id, dict(overlay)
        return None

    def _record_for_context(
        self,
        run_id: str,
        spec: Mapping[str, Any],
        ctx: SessionContext,
    ) -> MemoryRecord:
        record_kind = spec["record_kind"]
        marker = spec["marker"]
        record_digest = _digest(f"{run_id}:{spec['record_key']}")
        actor_id = clean_text(ctx.user_id, 120)
        other_actor_id = f"lab-other-{_digest(run_id)}"
        bot = EntityRef.bot_self(clean_text(ctx.bot_id, 120))
        metadata: dict[str, Any] = {
            "lab_fixture": True,
            "owner_bot_id": clean_text(ctx.bot_id, 120),
        }

        if record_kind == "group_memory":
            group_id = clean_text(ctx.group_id, 120) or f"lab-group-{_digest(run_id)}"
            record = MemoryRecord(
                id=f"labfx_{record_digest}",
                memory_type="manual_memory",
                subject=EntityRef(kind="user", id=actor_id),
                object=EntityRef(kind="group", id=group_id),
                scope="group",
                session_id=ctx.session_id,
                platform=ctx.platform,
                group_id=group_id,
                visibility="group_public",
                sayability="direct",
                reality_level="synthetic_test_fixture",
                lifecycle="stable_memory",
                content=f"LAB synthetic group memory marker {marker}",
                evidence=f"LAB synthetic evidence marker {marker}",
                confidence=0.99,
                importance=0.9,
                owner_bot_id=ctx.bot_id,
                review_status="auto",
                tags=["lab_fixture", record_kind],
                metadata=metadata,
                source_plugin="memory_companion_lab_fixture",
            )
            return record.ensure_defaults()

        owner_actor_id = other_actor_id if record_kind == "foreign_private_memory" else actor_id
        private_session = (
            ctx.session_id
            if ctx.scope == "private" and owner_actor_id == actor_id
            else f"lab:FriendMessage:{owner_actor_id}"
        )
        memory_type = "user_profile" if record_kind == "profile" else "manual_memory"
        content = (
            f"LAB synthetic user profile marker {marker}"
            if record_kind == "profile"
            else f"LAB synthetic private memory marker {marker}"
        )
        if record_kind == "profile":
            metadata.update(
                {
                    "extractor": "rule_v2",
                    "profile_dimension": "lab_fixture_marker",
                    "profile_value": marker,
                    "normalized_value": marker,
                    "extraction_quality": "explicit",
                    "extraction_quality_score": 0.99,
                    "evidence_strength": "direct_statement",
                    "profile_state": "active",
                    "quality_gate_passed": True,
                }
            )
        record = MemoryRecord(
            id=f"labfx_{record_digest}",
            memory_type=memory_type,
            subject=EntityRef(kind="user", id=owner_actor_id),
            object=bot,
            scope="private",
            session_id=private_session,
            platform=ctx.platform,
            visibility="private_pair",
            sayability="direct",
            reality_level="synthetic_test_fixture",
            lifecycle="stable_memory",
            content=content,
            evidence=f"LAB synthetic evidence marker {marker}",
            confidence=0.99,
            importance=0.9,
            owner_bot_id=ctx.bot_id,
            review_status="auto",
            tags=["lab_fixture", record_kind],
            metadata=metadata,
            source_plugin="memory_companion_lab_fixture",
        )
        return record.ensure_defaults()

    def _cache_stats(self) -> dict[str, int]:
        raw = getattr(self._service, "_retrieval_result_cache_stats", None)
        if not isinstance(raw, Mapping):
            return {"hits": 0, "misses": 0, "evictions": 0}
        return {
            key: max(0, int(raw.get(key) or 0))
            for key in ("hits", "misses", "evictions")
        }

    def _update(self, run_id: str, **changes: Any) -> bool:
        with self._lock:
            current = self._overlays.get(run_id)
            if current is None:
                return False
            updated = {**current, **changes}
            self._overlays = {**self._overlays, run_id: updated}
            return True


def register_memory_lab_fixture_adapter(service: Any = None) -> MemoryLabFixtureAdapter | None:
    """Register only when the Lab's in-process capability module is present."""

    module_name = "astrbot_test_lab_fixture"
    try:
        fixture_module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return None
        raise
    establish = getattr(fixture_module, "establish_fixture_capability", None)
    capability_is_valid = getattr(fixture_module, "fixture_capability_is_valid", None)
    register = getattr(fixture_module, "register_fixture_adapter", None)
    if not all(callable(item) for item in (establish, capability_is_valid, register)):
        raise RuntimeError("Test Lab fixture registration is unavailable")
    capability = establish()
    if not capability_is_valid(capability):
        raise PermissionError("invalid Test Lab fixture capability")
    _require_process_capability(capability)
    adapter = MemoryLabFixtureAdapter(service)
    try:
        register(PLUGIN_ID, adapter, capability)
    except Exception:
        adapter.close()
        raise
    return adapter


__all__ = [
    "MemoryLabFixtureAdapter",
    "PLUGIN_ID",
    "SCHEMA",
    "register_memory_lab_fixture_adapter",
]
