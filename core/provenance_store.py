"""Small append-only provenance ledger for the chat-side memory plugin.

The ledger stores only validated provenance records and migration audit
metadata.  It never accepts prompt text, conversation content, media,
credentials, or arbitrary source prose.  Writes are atomic and every mutation
creates a backup before the current projection changes.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Mapping

from .provenance import (
    apply_planned_operation,
    plan_legacy_migration,
    provenance_record_digest,
    rollback_planned_operation,
    validate_operation,
    validate_provenance_record,
)


LEDGER_SCHEMA_VERSION = "ops.p5.provenance.ledger.v1"


class ProvenanceLedger:
    """Persist validated provenance projections with CAS-protected writes."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        # mtime/size 缓存：避免每次 mutation 前全量 read_text + json.loads + 逐条校验。
        # 所有读写均在 self._lock 内进行，缓存无需额外同步。
        self._cache_document: dict[str, Any] | None = None
        self._cache_mtime_ns: int | None = None
        self._cache_size: int | None = None

    def _empty(self) -> dict[str, Any]:
        return {"schema_version": LEDGER_SCHEMA_VERSION, "records": {}, "operations": [], "observations": []}

    def _load_locked(self) -> dict[str, Any]:
        try:
            stat_result = self.path.stat()
        except OSError:
            # 文件缺失或不可访问：清空缓存并返回空文档。
            self._cache_document = None
            self._cache_mtime_ns = None
            self._cache_size = None
            return self._empty()
        mtime_ns = stat_result.st_mtime_ns
        size = stat_result.st_size
        if (
            self._cache_document is not None
            and self._cache_mtime_ns == mtime_ns
            and self._cache_size == size
        ):
            # mtime+size 未变化：跳过全量读与逐条校验，直接深拷贝缓存返回。
            return deepcopy(self._cache_document)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self._cache_document = None
            self._cache_mtime_ns = None
            self._cache_size = None
            return self._empty()
        if not isinstance(raw, dict) or raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
            self._cache_document = None
            self._cache_mtime_ns = None
            self._cache_size = None
            return self._empty()
        records: dict[str, dict[str, Any]] = {}
        raw_records = raw.get("records")
        if isinstance(raw_records, dict):
            for memory_id, value in raw_records.items():
                checked = validate_provenance_record(value if isinstance(value, Mapping) else None)
                if checked.get("ok") and checked.get("record", {}).get("memory_id") == memory_id:
                    records[memory_id] = deepcopy(checked["record"])
        operations: list[dict[str, Any]] = []
        raw_operations = raw.get("operations")
        if isinstance(raw_operations, list):
            for value in raw_operations:
                checked = validate_operation(value if isinstance(value, Mapping) else None)
                if checked.get("ok"):
                    operations.append(deepcopy(checked["operation"]))
                elif isinstance(value, dict) and value.get("kind") == "rollback":
                    safe = self._safe_rollback_audit(value)
                    if safe is not None:
                        operations.append(safe)
        observations: list[dict[str, Any]] = []
        raw_observations = raw.get("observations")
        if isinstance(raw_observations, list):
            for value in raw_observations:
                safe = self._safe_observation(value)
                if safe is not None:
                    observations.append(safe)
        document = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "records": records,
            "operations": operations,
            "observations": observations,
        }
        # 记录加载时文件的 mtime/size，并缓存文档（存深拷贝副本，
        # 避免调用方对返回值的修改污染缓存）。
        self._cache_mtime_ns = mtime_ns
        self._cache_size = size
        self._cache_document = deepcopy(document)
        return document

    @staticmethod
    def _safe_observation(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, Mapping) or set(value) != {
            "memory_id", "record_digest", "record_revision", "source_event_ref_hash",
            "authority_attestation_ref_hash", "provenance_state",
        }:
            return None
        if (
            not isinstance(value.get("memory_id"), str)
            or not value["memory_id"]
            or not isinstance(value.get("record_digest"), str)
            or len(value["record_digest"]) != 64
            or not isinstance(value.get("source_event_ref_hash"), str)
            or len(value["source_event_ref_hash"]) != 64
            or not isinstance(value.get("authority_attestation_ref_hash"), str)
            or len(value["authority_attestation_ref_hash"]) != 64
            or not isinstance(value.get("record_revision"), int)
            or value["record_revision"] < 1
            or value.get("provenance_state") not in {"observed", "owner_recovered"}
        ):
            return None
        return {
            "memory_id": value["memory_id"][:120],
            "record_digest": value["record_digest"].lower(),
            "record_revision": value["record_revision"],
            "source_event_ref_hash": value["source_event_ref_hash"].lower(),
            "authority_attestation_ref_hash": value["authority_attestation_ref_hash"].lower(),
            "provenance_state": value["provenance_state"],
        }

    @staticmethod
    def _safe_rollback_audit(value: Mapping[str, Any]) -> dict[str, Any] | None:
        memory_id = value.get("memory_id")
        before_digest = value.get("before_digest")
        after_digest = value.get("after_digest")
        from_revision = value.get("from_revision")
        to_revision = value.get("to_revision")
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or not isinstance(before_digest, str)
            or len(before_digest) != 64
            or not isinstance(after_digest, str)
            or len(after_digest) != 64
            or not isinstance(from_revision, int)
            or from_revision < 0
            or not isinstance(to_revision, int)
            or to_revision < 0
        ):
            return None
        return {
            "kind": "rollback",
            "memory_id": memory_id[:120],
            "before_digest": before_digest.lower(),
            "after_digest": after_digest.lower(),
            "from_revision": from_revision,
            "to_revision": to_revision,
        }

    def _write_locked(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{threading.get_ident()}.tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        # 写入成功后刷新缓存，避免下一次 mutation 再全量重读。
        self._cache_document = dict(document)
        try:
            stat_result = self.path.stat()
        except OSError:
            self._cache_mtime_ns = None
            self._cache_size = None
        else:
            self._cache_mtime_ns = stat_result.st_mtime_ns
            self._cache_size = stat_result.st_size

    def _backup_locked(self) -> bool:
        if not self.path.is_file():
            return False
        backup = self.path.with_name(f"{self.path.name}.backup.{time.time_ns()}")
        try:
            shutil.copy2(self.path, backup)
            return True
        except OSError:
            return False

    @staticmethod
    def _minimal_current(memory_id: str, record: Mapping[str, Any] | None) -> dict[str, Any]:
        if isinstance(record, Mapping):
            return deepcopy(dict(record))
        return {"memory_id": memory_id, "record_revision": 0}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            document = self._load_locked()
            return {
                "schema_version": LEDGER_SCHEMA_VERSION,
                "records": deepcopy(document["records"]),
                "operation_count": len(document["operations"]),
                "observation_count": len(document["observations"]),
                "path_present": self.path.is_file(),
            }

    def preview_legacy(self, candidates: list[Mapping[str, Any]], *, operation_ref_hash: str) -> dict[str, Any]:
        return plan_legacy_migration(candidates, operation_ref_hash=operation_ref_hash)

    def backup(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.is_file():
                return {"ok": True, "state": "nothing_to_backup", "created": False}
            created = self._backup_locked()
            return {"ok": created, "state": "backed_up" if created else "degraded", "created": created}

    def apply(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        checked = validate_operation(operation)
        if not checked.get("ok"):
            return {"ok": False, "state": "invalid", "error_codes": checked.get("error_codes", [])}
        op = checked["operation"]
        with self._lock:
            document = self._load_locked()
            current = self._minimal_current(op["memory_id"], document["records"].get(op["memory_id"]))
            result = apply_planned_operation(current, op)
            if not result.get("ok") or not result.get("changed"):
                return {**result, "backup_created": False}
            backup_created = self._backup_locked()
            document["records"][op["memory_id"]] = deepcopy(result["record"])
            document["operations"].append(deepcopy(op))
            self._write_locked(document)
            return {**result, "backup_created": backup_created, "operation_count": len(document["operations"])}

    def rollback(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        checked = validate_operation(operation)
        if not checked.get("ok"):
            return {"ok": False, "state": "invalid", "error_codes": checked.get("error_codes", [])}
        op = checked["operation"]
        with self._lock:
            document = self._load_locked()
            current = document["records"].get(op["memory_id"])
            result = rollback_planned_operation(current, op)
            if not result.get("ok"):
                return {**result, "backup_created": False}
            backup_created = self._backup_locked()
            if result.get("removed"):
                document["records"].pop(op["memory_id"], None)
            else:
                document["records"][op["memory_id"]] = deepcopy(result["record"])
            document["operations"].append(
                {
                    "kind": "rollback",
                    "memory_id": op["memory_id"],
                    "before_digest": op["after_record_digest"],
                    "after_digest": provenance_record_digest(result.get("record")) if result.get("record") else "0" * 64,
                    "from_revision": op["after_record"]["record_revision"],
                    "to_revision": result.get("record", {}).get("record_revision", 0) if result.get("record") else 0,
                }
            )
            self._write_locked(document)
            return {**result, "backup_created": backup_created, "operation_count": len(document["operations"])}

    def record_observed(self, memory_ids: list[str], snapshot: Any) -> dict[str, Any]:
        """Append observed metadata for selected memories without raw payloads."""

        from .provenance import observed_from_companion_snapshot

        safe_ids = [item for item in memory_ids if isinstance(item, str) and item][:64]
        if not safe_ids:
            return {"ok": False, "state": "invalid", "error_code": "memory_ids_empty", "written": 0}
        with self._lock:
            document = self._load_locked()
            updates: dict[str, dict[str, Any]] = {}
            for memory_id in safe_ids:
                current = document["records"].get(memory_id)
                revision = int(current.get("record_revision", 0)) if isinstance(current, dict) else 0
                record = observed_from_companion_snapshot(memory_id, snapshot, record_revision=revision + 1)
                checked = validate_provenance_record(record)
                if not checked.get("ok"):
                    continue
                if isinstance(current, dict) and current == checked["record"]:
                    continue
                updates[memory_id] = deepcopy(checked["record"])
            if not updates:
                return {"ok": True, "state": "deduplicated", "written": 0, "backup_created": False}
            backup_created = self._backup_locked()
            document["records"].update(updates)
            for record in updates.values():
                document["observations"].append(
                    {
                        "memory_id": record["memory_id"],
                        "record_digest": provenance_record_digest(record),
                        "record_revision": record["record_revision"],
                        "source_event_ref_hash": record["source_event_ref_hash"],
                        "authority_attestation_ref_hash": record["authority_attestation_ref_hash"],
                        "provenance_state": record["provenance_state"],
                    }
                )
            self._write_locked(document)
            return {
                "ok": True,
                "state": "written",
                "written": len(updates),
                "memory_ids": list(updates),
                "backup_created": backup_created,
            }


__all__ = ["LEDGER_SCHEMA_VERSION", "ProvenanceLedger"]
