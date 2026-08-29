from __future__ import annotations

from typing import Any

from .namespace_capability import namespace_capability_descriptor
from .scoped_store import ScopedStoreError


class ScopedNamespaceBridgeFamily:
    """Concrete bridge capability family backed by one façade owner."""

    __slots__ = ("_owner",)

    def __init__(self, owner: Any):
        self._owner = owner

    def probe_namespace_context_capabilities(self) -> dict[str, Any]:
        """Advertise ready only after the store and active epoch are bound."""
        store = self._owner._scoped_store
        status = store.epoch_status() if store is not None else {"bound": False}
        ready = self._owner._active and status.get("bound") is True
        error_code = ""
        if not ready:
            error_code = "bridge_inactive" if not self._owner._active else "namespace_scoped_api_not_bound"
            if self._owner._active and store is None:
                error_code = self._owner._scoped_store_initialization_error_code() or error_code
        return namespace_capability_descriptor(
            available=ready,
            methods=(
                "list_scoped_records",
                "read_scoped_record",
                "erase_scoped_group_scopes",
                "erase_scoped_persona_scopes",
                "tombstone_scoped_identity_scopes",
                "tombstone_scoped_namespace",
                "tombstone_scoped_record",
                "upsert_scoped_record",
            ) if ready else (),
            error_code=error_code,
        )

    def bind_namespace_migration_epoch(
        self,
        capability: Any,
        *,
        operation_id: str,
        expected_previous_epoch: str,
        migration_epoch: str,
        policy_version: str,
    ) -> dict[str, Any]:
        if not self._owner._active:
            return {"ok": False, "state": "degraded", "code": "bridge_inactive"}
        if not self._owner._is_valid_private_companion_capability(capability):
            return {"ok": False, "state": "forbidden", "code": "producer_capability_required"}
        if self._owner._scoped_store is None:
            return {
                "ok": False,
                "state": "degraded",
                "code": self._owner._scoped_store_initialization_error_code()
                or "namespace_scoped_store_unavailable",
            }
        denied = self._owner._scoped_mutation_denied()
        if denied is not None:
            return denied
        try:
            result = self._owner._scoped_store.bind_epoch(
                operation_id=operation_id,
                expected_previous_epoch=expected_previous_epoch,
                migration_epoch=migration_epoch,
                policy_version=policy_version,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {
            "ok": True,
            "state": "ready",
            "code": result,
            "epoch": self._owner._scoped_store.epoch_status(),
        }

    def upsert_scoped_record(
        self,
        capability: Any,
        namespace: Any,
        *,
        record_kind: str,
        record_id: str,
        revision: int,
        payload: dict[str, Any],
        event_id: str,
    ) -> dict[str, Any]:
        context, denied = self._owner._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        denied = self._owner._scoped_mutation_denied()
        if denied is not None:
            return denied
        try:
            result = self._owner._scoped_store.upsert(
                context, record_kind=record_kind, record_id=record_id, revision=revision,
                payload=payload, event_id=event_id,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", "code": result}

    def read_scoped_record(
        self, capability: Any, namespace: Any, *, record_kind: str, record_id: str
    ) -> dict[str, Any]:
        context, denied = self._owner._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            record = self._owner._scoped_store.read(context, record_kind=record_kind, record_id=record_id)
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", "code": "found" if record is not None else "not_found", "record": record}

    def list_scoped_records(
        self, capability: Any, namespace: Any, *, record_kind: str, limit: int = 100
    ) -> dict[str, Any]:
        context, denied = self._owner._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        try:
            records = self._owner._scoped_store.list_records(context, record_kind=record_kind, limit=limit)
        except (ScopedStoreError, TypeError, ValueError, OverflowError) as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", "code": "listed", "records": records}

    def tombstone_scoped_record(
        self,
        capability: Any,
        namespace: Any,
        *,
        record_kind: str,
        record_id: str,
        revision: int,
        event_id: str,
    ) -> dict[str, Any]:
        context, denied = self._owner._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        denied = self._owner._scoped_mutation_denied()
        if denied is not None:
            return denied
        try:
            result = self._owner._scoped_store.tombstone(
                context, record_kind=record_kind, record_id=record_id, revision=revision, event_id=event_id,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", "code": result}

    def tombstone_scoped_namespace(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        context, denied = self._owner._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        denied = self._owner._scoped_mutation_denied()
        if denied is not None:
            return denied
        try:
            result = self._owner._scoped_store.tombstone_namespace(
                context, operation_id=operation_id, reason_code=reason_code,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", **result}
    def tombstone_scoped_identity_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        context, denied = self._owner._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        denied = self._owner._scoped_mutation_denied()
        if denied is not None:
            return denied
        try:
            result = self._owner._scoped_store.tombstone_identity_scopes(
                context, operation_id=operation_id, reason_code=reason_code,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", **result}

    def erase_scoped_group_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str = "group_reset",
    ) -> dict[str, Any]:
        context, denied = self._owner._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        denied = self._owner._scoped_mutation_denied()
        if denied is not None:
            return denied
        try:
            result = self._owner._scoped_store.erase_group_scopes(
                context, operation_id=operation_id, reason_code=reason_code,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", **result}

    def erase_scoped_persona_scopes(
        self,
        capability: Any,
        namespace: Any,
        *,
        operation_id: str,
        reason_code: str = "persona_reset",
    ) -> dict[str, Any]:
        context, denied = self._owner._authorized_scoped_context(capability, namespace)
        if denied is not None:
            return denied
        denied = self._owner._scoped_mutation_denied()
        if denied is not None:
            return denied
        try:
            result = self._owner._scoped_store.erase_persona_scopes(
                context, operation_id=operation_id, reason_code=reason_code,
            )
        except ScopedStoreError as exc:
            return {"ok": False, "state": "rejected", "code": str(exc)[:120]}
        return {"ok": True, "state": "ready", **result}
