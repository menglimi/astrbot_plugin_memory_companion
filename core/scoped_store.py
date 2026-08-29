"""REQ-041 revisioned namespace-scoped record store.

This is the new-path storage primitive.  It never guesses a namespace and it
does not fall back to legacy tables.  Callers must pass a validated context and
an assurance-authorized purpose on every read and write.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterator

from .namespace import AssurancePolicy, NamespaceContext
from .scoped_domain_contract import (
    SCHEMA_VERSION,
    ScopedDomainContractError,
    build_scoped_domain_payload,
    validate_scoped_domain_payload,
)


MAX_RECORD_BYTES = 262144
_ERASED_PAYLOAD_JSON = "{}"
_ERASED_PAYLOAD_HASH = hashlib.sha256(_ERASED_PAYLOAD_JSON.encode("utf-8")).hexdigest()
RECORD_KINDS = frozenset({"profile_fact", "memory", "rule", "evidence", "summary"})
_PURPOSE_BY_KIND = {
    "profile_fact": ("profile_read", "profile_write"),
    "memory": ("memory_read", "memory_write"),
    "summary": ("memory_read", "memory_write"),
    "rule": ("rule_read", "rule_write"),
    "evidence": ("rule_read", "rule_write"),
}


class ScopedStoreError(RuntimeError):
    pass


class ScopedRecordConflict(ScopedStoreError):
    pass


class ScopedRevisionGap(ScopedStoreError):
    pass


def _token(value: Any, limit: int = 128) -> str:
    if not isinstance(value, str):
        return ""
    result = value.strip()
    if not result or len(result) > limit or any(ord(ch) < 32 for ch in result):
        return ""
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _payload(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ScopedStoreError("scoped_payload_invalid")
    try:
        encoded = _canonical(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ScopedStoreError("scoped_payload_invalid") from exc
    if len(encoded.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ScopedStoreError("scoped_payload_too_large")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ScopedStore:
    IDENTITY_SCHEMA_VERSION = "req041-scoped-store-v1"
    IDENTITY_MARKER_NAME = ".req041-scoped-identity.json"

    def __init__(
        self,
        path: str | Path,
        *,
        installation_id: str = "",
        clock: Any = None,
    ) -> None:
        self.path = Path(path)
        self.installation_id = _token(installation_id, 80).lower()
        if self.installation_id and not re.fullmatch(r"[0-9a-f]{32}", self.installation_id):
            raise ScopedStoreError("scoped_installation_identity_invalid")
        self.identity_marker_path = self.path.with_name(self.IDENTITY_MARKER_NAME)
        self._clock = clock if callable(clock) else time.time
        self._lock = threading.RLock()
        self._writes_admitted = True
        self._write_generation = 0
        self._active_epoch = ""
        self._active_policy_version = ""
        self._epoch_revision = 0
        self.last_identity_backup_path = ""
        startup = self._identity_startup_state() if self.installation_id else {
            "mode": "compat",
            "marker": None,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._initialize()
            if self.installation_id:
                self._bind_installation_identity(startup)
        except BaseException:
            if self.installation_id:
                try:
                    self._rollback_identity_initialization(startup)
                except Exception as rollback_error:
                    raise ScopedStoreError(
                        "scoped_identity_binding_rollback_failed"
                    ) from rollback_error
            raise

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA secure_delete=ON")
        return conn

    def _truncate_wal(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(
        self, *, allow_fenced_maintenance: bool = False
    ) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not allow_fenced_maintenance and not self._writes_admitted:
                raise ScopedStoreError("scoped_write_fenced")
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                if conn.in_transaction:
                    conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def begin_write_fence(self) -> int:
        """Atomically reject new business mutations before maintenance runs."""

        with self._lock:
            self._write_generation += 1
            self._writes_admitted = False
            return self._write_generation

    def resume_writes(self, expected_generation: int) -> bool:
        with self._lock:
            if expected_generation != self._write_generation:
                return False
            self._writes_admitted = True
            return True

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS scoped_records (
                    namespace_scope TEXT NOT NULL,
                    record_kind TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    migration_epoch TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(namespace_scope, record_kind, record_id)
                );
                CREATE INDEX IF NOT EXISTS idx_scoped_records_list
                    ON scoped_records(namespace_scope, record_kind, deleted, revision, record_id);
                CREATE TABLE IF NOT EXISTS scoped_operations (
                    event_id TEXT NOT NULL,
                    migration_epoch TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_code TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(event_id, migration_epoch)
                );
                CREATE TABLE IF NOT EXISTS scoped_epoch_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    migration_epoch TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scoped_epoch_operations (
                    operation_id TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    result_code TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scoped_namespace_operations (
                    operation_id TEXT NOT NULL,
                    migration_epoch TEXT NOT NULL,
                    namespace_scope TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(operation_id,migration_epoch)
                );
                CREATE TABLE IF NOT EXISTS scoped_store_identity (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    installation_id TEXT NOT NULL,
                    database_name TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            state = conn.execute(
                "SELECT migration_epoch,policy_version,revision FROM scoped_epoch_state WHERE singleton=1"
            ).fetchone()
            if state is not None:
                self._active_epoch = state["migration_epoch"]
                self._active_policy_version = state["policy_version"]
                self._epoch_revision = int(state["revision"])

    def _identity_startup_state(self) -> dict[str, Any]:
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ScopedStoreError("scoped_database_path_invalid")
        marker_exists = self.identity_marker_path.exists() or self.identity_marker_path.is_symlink()
        if marker_exists and (
            self.identity_marker_path.is_symlink() or not self.identity_marker_path.is_file()
        ):
            raise ScopedStoreError("scoped_identity_marker_invalid")
        marker: dict[str, Any] | None = None
        if marker_exists:
            try:
                value = json.loads(self.identity_marker_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ScopedStoreError("scoped_identity_marker_corrupt") from exc
            if not isinstance(value, dict):
                raise ScopedStoreError("scoped_identity_marker_invalid")
            marker = value
            if (
                value.get("version") != 1
                or value.get("database") != self.path.name
                or value.get("schema_version") != self.IDENTITY_SCHEMA_VERSION
                or not re.fullmatch(r"[0-9a-f]{32}", str(value.get("installation_id") or ""))
            ):
                raise ScopedStoreError("scoped_identity_marker_invalid")
            if value["installation_id"] != self.installation_id:
                raise ScopedStoreError("scoped_installation_identity_mismatch")

        database_exists = self.path.is_file()
        if marker is not None and not database_exists:
            raise ScopedStoreError("scoped_database_missing_after_identity_established")
        if not database_exists:
            return {"mode": "new", "marker": None}

        self._validate_existing_database_schema(require_identity=marker is not None)
        if marker is not None:
            return {"mode": "established", "marker": marker}
        self.last_identity_backup_path = str(self._backup_existing_database(".before_identity_adoption"))
        return {"mode": "adopt", "marker": None}

    def _validate_existing_database_schema(self, *, require_identity: bool) -> None:
        try:
            conn = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=3.0,
            )
        except sqlite3.Error as exc:
            raise ScopedStoreError("scoped_database_unreadable") from exc
        try:
            conn.row_factory = sqlite3.Row
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            required = {
                "scoped_records",
                "scoped_operations",
                "scoped_epoch_state",
                "scoped_epoch_operations",
                "scoped_namespace_operations",
            }
            if not required.issubset(tables):
                raise ScopedStoreError("scoped_legacy_schema_unrecognized")
            record_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(scoped_records)").fetchall()
            }
            if not {
                "namespace_scope", "record_kind", "record_id", "revision",
                "payload_json", "payload_hash", "deleted",
            }.issubset(record_columns):
                raise ScopedStoreError("scoped_legacy_schema_unrecognized")
            identity_row = None
            if "scoped_store_identity" in tables:
                identity_row = conn.execute(
                    "SELECT installation_id,database_name,schema_version "
                    "FROM scoped_store_identity WHERE singleton=1"
                ).fetchone()
            if require_identity:
                if identity_row is None:
                    raise ScopedStoreError("scoped_database_identity_missing")
                if (
                    identity_row["installation_id"] != self.installation_id
                    or identity_row["database_name"] != self.path.name
                    or identity_row["schema_version"] != self.IDENTITY_SCHEMA_VERSION
                ):
                    raise ScopedStoreError("scoped_database_identity_mismatch")
            if not require_identity and identity_row is not None:
                # A bound database without its marker is a torn identity pair,
                # not a legacy database that may be silently adopted.
                raise ScopedStoreError("scoped_identity_marker_missing")
            if not require_identity:
                populated = any(
                    conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
                    for table in required
                )
                if not populated:
                    raise ScopedStoreError("scoped_legacy_database_empty")
        except sqlite3.DatabaseError as exc:
            if isinstance(exc, ScopedStoreError):
                raise
            raise ScopedStoreError("scoped_database_unreadable") from exc
        finally:
            conn.close()

    def _backup_existing_database(self, suffix: str) -> Path:
        stamp = str(int(float(self._clock()) * 1000))
        target = self.path.with_name(
            f"{self.path.stem}.backup.{stamp}.{uuid.uuid4().hex}{suffix}.db"
        )
        try:
            source_uri = f"{self.path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(
                str(target)
            ) as destination:
                source.backup(destination)
            target.chmod(0o600)
        except (sqlite3.Error, OSError) as exc:
            target.unlink(missing_ok=True)
            raise ScopedStoreError("scoped_backup_failed") from exc
        return target

    def backup(self, suffix: str = "") -> Path:
        with self._lock:
            self._truncate_wal()
            return self._backup_existing_database(suffix)

    def _bind_installation_identity(self, startup: dict[str, Any]) -> None:
        mode = str(startup.get("mode") or "")
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT installation_id,database_name,schema_version FROM scoped_store_identity WHERE singleton=1"
            ).fetchone()
            if mode == "established":
                if row is None:
                    raise ScopedStoreError("scoped_database_identity_missing")
                if (
                    row["installation_id"] != self.installation_id
                    or row["database_name"] != self.path.name
                    or row["schema_version"] != self.IDENTITY_SCHEMA_VERSION
                ):
                    raise ScopedStoreError("scoped_database_identity_mismatch")
                return
            if row is not None and (
                row["installation_id"] != self.installation_id
                or row["database_name"] != self.path.name
                or row["schema_version"] != self.IDENTITY_SCHEMA_VERSION
            ):
                raise ScopedStoreError("scoped_database_identity_mismatch")
            if row is None:
                conn.execute(
                    "INSERT INTO scoped_store_identity(singleton,installation_id,database_name,schema_version,created_at) "
                    "VALUES(1,?,?,?,?)",
                    (
                        self.installation_id,
                        self.path.name,
                        self.IDENTITY_SCHEMA_VERSION,
                        float(self._clock()),
                    ),
                )
        if not self.identity_marker_path.exists():
            self._write_identity_marker()

    def _rollback_identity_initialization(self, startup: dict[str, Any]) -> None:
        """Restore the exact pre-construction DB/marker pairing on failure."""

        mode = str(startup.get("mode") or "")
        if mode == "established":
            return
        try:
            self.identity_marker_path.unlink(missing_ok=True)
        except OSError as exc:
            raise ScopedStoreError("scoped_identity_marker_rollback_failed") from exc
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            except OSError as exc:
                raise ScopedStoreError("scoped_identity_sidecar_rollback_failed") from exc
        if mode == "new":
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                raise ScopedStoreError("scoped_identity_database_rollback_failed") from exc
            return
        if mode != "adopt":
            return
        backup = Path(self.last_identity_backup_path)
        if not backup.is_file():
            raise ScopedStoreError("scoped_identity_adoption_backup_missing")
        temp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.rollback.tmp")
        try:
            shutil.copy2(backup, temp)
            with temp.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            directory_fd = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise ScopedStoreError("scoped_identity_adoption_restore_failed") from exc
        finally:
            temp.unlink(missing_ok=True)

    def _write_identity_marker(self) -> None:
        payload = {
            "version": 1,
            "database": self.path.name,
            "schema_version": self.IDENTITY_SCHEMA_VERSION,
            "installation_id": self.installation_id,
        }
        temp = self.identity_marker_path.with_name(
            f".{self.identity_marker_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temp.open("x", encoding="utf-8") as handle:
                os.chmod(temp, 0o600)
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.identity_marker_path)
            directory_fd = os.open(str(self.identity_marker_path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp.exists():
                temp.unlink()

    def _authorize(self, context: NamespaceContext | None, record_kind: str, *, write: bool) -> None:
        if record_kind not in RECORD_KINDS:
            raise ScopedStoreError("scoped_record_kind_invalid")
        purpose = _PURPOSE_BY_KIND[record_kind][1 if write else 0]
        decision = AssurancePolicy.authorize(context, purpose)
        if not decision.allowed:
            raise ScopedStoreError(decision.code)
        if self._active_epoch:
            assert context is not None
            if context.migration_epoch != self._active_epoch:
                raise ScopedStoreError("scoped_migration_epoch_stale")
            if context.policy_version != self._active_policy_version:
                raise ScopedStoreError("scoped_policy_version_stale")

    def epoch_status(self) -> dict[str, Any]:
        return {
            "bound": bool(self._active_epoch),
            "migration_epoch": self._active_epoch,
            "policy_version": self._active_policy_version,
            "revision": self._epoch_revision,
        }

    def bind_epoch(
        self,
        *,
        operation_id: str,
        expected_previous_epoch: str,
        migration_epoch: str,
        policy_version: str,
    ) -> str:
        operation = _token(operation_id)
        expected = _token(expected_previous_epoch) if expected_previous_epoch else ""
        epoch = _token(migration_epoch)
        policy = _token(policy_version, 64)
        if not operation or not epoch or not policy or epoch == expected:
            raise ScopedStoreError("scoped_epoch_binding_invalid")
        request_hash = hashlib.sha256(
            _canonical({"expected": expected, "epoch": epoch, "policy": policy}).encode("utf-8")
        ).hexdigest()
        now = float(self._clock())
        with self._transaction() as conn:
            prior = conn.execute(
                "SELECT request_hash,result_code FROM scoped_epoch_operations WHERE operation_id=?",
                (operation,),
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise ScopedRecordConflict("scoped_epoch_operation_conflict")
                return "duplicate"
            state = conn.execute(
                "SELECT migration_epoch,policy_version,revision FROM scoped_epoch_state WHERE singleton=1"
            ).fetchone()
            current = state["migration_epoch"] if state is not None else ""
            current_policy = state["policy_version"] if state is not None else ""
            current_revision = int(state["revision"]) if state is not None else 0
            if current == epoch and current_policy == policy:
                result = "current"
                revision = current_revision
            else:
                if current != expected:
                    raise ScopedRecordConflict("scoped_epoch_compare_and_swap_failed")
                revision = current_revision + 1
                conn.execute(
                    """INSERT INTO scoped_epoch_state(singleton,migration_epoch,policy_version,revision,updated_at)
                       VALUES(1,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET
                       migration_epoch=excluded.migration_epoch,policy_version=excluded.policy_version,
                       revision=excluded.revision,updated_at=excluded.updated_at""",
                    (epoch, policy, revision, now),
                )
                result = "bound" if current_revision == 0 else "rotated"
            conn.execute(
                "INSERT INTO scoped_epoch_operations(operation_id,request_hash,result_code,revision,created_at) VALUES(?,?,?,?,?)",
                (operation, request_hash, result, revision, now),
            )
        self._active_epoch = epoch
        self._active_policy_version = policy
        self._epoch_revision = revision
        return result

    @staticmethod
    def _scope(context: NamespaceContext) -> str:
        # Durable ownership is stable across policy revisions and migration
        # epochs.  Assurance/status/policy still gate each operation, but must
        # not silently create a second physical namespace for the same owner.
        # This local key is never emitted to logs; cache_scope() remains the
        # redacted, revision-aware cache key.
        return _canonical({
            "kind": context.kind,
            "persona_id": context.persona_id,
            "identity_id": context.identity_id,
            "group_id": context.group_id,
        })

    def upsert(
        self,
        context: NamespaceContext,
        *,
        record_kind: str,
        record_id: str,
        revision: int,
        payload: dict[str, Any],
        event_id: str,
    ) -> str:
        self._authorize(context, record_kind, write=True)
        identifier = _token(record_id)
        event = _token(event_id)
        if not identifier or not event or revision < 1:
            raise ScopedStoreError("scoped_envelope_invalid")
        if str(record_id or "").startswith("req041-") or (
            isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION
        ):
            try:
                validate_scoped_domain_payload(context, record_kind, payload)
            except ScopedDomainContractError as exc:
                raise ScopedStoreError(str(exc)) from exc
        encoded, digest = _payload(payload)
        scope = self._scope(context)
        request_hash = hashlib.sha256(
            _canonical({
                "scope": scope, "kind": record_kind, "id": identifier, "revision": revision,
                "payload_hash": digest, "policy_version": context.policy_version,
            }).encode("utf-8")
        ).hexdigest()
        now = float(self._clock())
        with self._transaction() as conn:
            prior_operation = conn.execute(
                "SELECT request_hash,result_code FROM scoped_operations WHERE event_id=? AND migration_epoch=?",
                (event, context.migration_epoch),
            ).fetchone()
            if prior_operation is not None:
                if prior_operation["request_hash"] != request_hash:
                    raise ScopedRecordConflict("scoped_event_conflict")
                return "duplicate"
            row = conn.execute(
                "SELECT revision,payload_hash,deleted FROM scoped_records WHERE namespace_scope=? AND record_kind=? AND record_id=?",
                (scope, record_kind, identifier),
            ).fetchone()
            if row is None:
                if revision != 1:
                    raise ScopedRevisionGap(f"scoped_revision_gap:0:{revision}")
                result = "created"
            else:
                current = int(row["revision"])
                if int(row["deleted"]) == 1:
                    raise ScopedRecordConflict("scoped_record_tombstoned")
                if revision == current and row["payload_hash"] == digest:
                    result = "duplicate"
                elif revision != current + 1:
                    raise ScopedRevisionGap(f"scoped_revision_gap:{current}:{revision}")
                else:
                    result = "updated"
            if result != "duplicate":
                conn.execute(
                    """INSERT INTO scoped_records(
                        namespace_scope,record_kind,record_id,revision,payload_json,payload_hash,
                        policy_version,migration_epoch,deleted,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,0,?)
                    ON CONFLICT(namespace_scope,record_kind,record_id) DO UPDATE SET
                        revision=excluded.revision,payload_json=excluded.payload_json,payload_hash=excluded.payload_hash,
                        policy_version=excluded.policy_version,migration_epoch=excluded.migration_epoch,
                        deleted=0,updated_at=excluded.updated_at""",
                    (
                        scope, record_kind, identifier, revision, encoded, digest,
                        context.policy_version, context.migration_epoch, now,
                    ),
                )
            conn.execute(
                "INSERT INTO scoped_operations(event_id,migration_epoch,request_hash,result_code,created_at) VALUES(?,?,?,?,?)",
                (event, context.migration_epoch, request_hash, result, now),
            )
        return result

    def read(self, context: NamespaceContext, *, record_kind: str, record_id: str) -> dict[str, Any] | None:
        self._authorize(context, record_kind, write=False)
        identifier = _token(record_id)
        if not identifier:
            raise ScopedStoreError("scoped_record_id_invalid")
        with self._connection() as conn:
            row = conn.execute(
                """SELECT revision,payload_json,payload_hash,policy_version,migration_epoch,updated_at
                FROM scoped_records WHERE namespace_scope=? AND record_kind=? AND record_id=? AND deleted=0""",
                (self._scope(context), record_kind, identifier),
            ).fetchone()
        if row is None:
            return None
        return {
            "record_id": identifier,
            "record_kind": record_kind,
            "revision": int(row["revision"]),
            "payload": json.loads(row["payload_json"]),
            "payload_hash": row["payload_hash"],
            "policy_version": row["policy_version"],
            "migration_epoch": row["migration_epoch"],
            "updated_at": row["updated_at"],
        }

    def list_records(self, context: NamespaceContext, *, record_kind: str, limit: int = 100) -> list[dict[str, Any]]:
        self._authorize(context, record_kind, write=False)
        safe_limit = max(1, min(1000, int(limit)))
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT record_id,revision,payload_json,payload_hash,policy_version,migration_epoch,updated_at
                FROM scoped_records WHERE namespace_scope=? AND record_kind=? AND deleted=0
                ORDER BY revision,record_id LIMIT ?""",
                (self._scope(context), record_kind, safe_limit),
            ).fetchall()
        return [
            {
                "record_id": row["record_id"], "record_kind": record_kind, "revision": int(row["revision"]),
                "payload": json.loads(row["payload_json"]), "payload_hash": row["payload_hash"],
                "policy_version": row["policy_version"], "migration_epoch": row["migration_epoch"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def tombstone(
        self,
        context: NamespaceContext,
        *,
        record_kind: str,
        record_id: str,
        revision: int,
        event_id: str,
    ) -> str:
        self._authorize(context, record_kind, write=True)
        identifier = _token(record_id)
        event = _token(event_id)
        if not identifier or not event or revision < 1:
            raise ScopedStoreError("scoped_envelope_invalid")
        scope = self._scope(context)
        request_hash = hashlib.sha256(
            _canonical({"scope": scope, "kind": record_kind, "id": identifier, "revision": revision, "delete": True}).encode("utf-8")
        ).hexdigest()
        now = float(self._clock())
        with self._transaction() as conn:
            prior = conn.execute(
                "SELECT request_hash FROM scoped_operations WHERE event_id=? AND migration_epoch=?",
                (event, context.migration_epoch),
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise ScopedRecordConflict("scoped_event_conflict")
                return "duplicate"
            row = conn.execute(
                "SELECT revision,deleted FROM scoped_records WHERE namespace_scope=? AND record_kind=? AND record_id=?",
                (scope, record_kind, identifier),
            ).fetchone()
            if row is None or revision != int(row["revision"]) + 1:
                current = int(row["revision"]) if row is not None else 0
                raise ScopedRevisionGap(f"scoped_revision_gap:{current}:{revision}")
            if int(row["deleted"]) == 1:
                raise ScopedRecordConflict("scoped_record_tombstoned")
            conn.execute(
                """UPDATE scoped_records SET revision=?,payload_json=?,payload_hash=?,deleted=1,updated_at=?
                   WHERE namespace_scope=? AND record_kind=? AND record_id=?""",
                (revision, _ERASED_PAYLOAD_JSON, _ERASED_PAYLOAD_HASH, now, scope, record_kind, identifier),
            )
            conn.execute(
                "INSERT INTO scoped_operations(event_id,migration_epoch,request_hash,result_code,created_at) VALUES(?,?,?,?,?)",
                (event, context.migration_epoch, request_hash, "tombstoned", now),
            )
        self._truncate_wal()
        return "tombstoned"

    def tombstone_namespace(
        self,
        context: NamespaceContext,
        *,
        operation_id: str,
        reason_code: str,
        record_prefix: str = "req041-",
    ) -> dict[str, Any]:
        purpose = "rule_write" if context.kind == "persona_global" else "memory_write"
        decision = AssurancePolicy.authorize(context, purpose)
        if not decision.allowed:
            raise ScopedStoreError(decision.code)
        if self._active_epoch and (
            context.migration_epoch != self._active_epoch
            or context.policy_version != self._active_policy_version
        ):
            raise ScopedStoreError("scoped_migration_epoch_stale")
        operation = _token(operation_id)
        reason = _token(reason_code, 80)
        prefix = _token(record_prefix, 40)
        if not operation or not reason or not prefix:
            raise ScopedStoreError("scoped_namespace_tombstone_invalid")
        scope = self._scope(context)
        request_hash = hashlib.sha256(
            _canonical({"scope": scope, "reason": reason, "prefix": prefix}).encode("utf-8")
        ).hexdigest()
        now = float(self._clock())
        with self._transaction() as conn:
            prior = conn.execute(
                "SELECT request_hash,result_json FROM scoped_namespace_operations WHERE operation_id=? AND migration_epoch=?",
                (operation, context.migration_epoch),
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise ScopedRecordConflict("scoped_namespace_operation_conflict")
                return json.loads(prior["result_json"])
            rows = conn.execute(
                """SELECT record_kind,record_id,revision FROM scoped_records
                   WHERE namespace_scope=? AND deleted=0 AND record_id LIKE ? ORDER BY record_kind,record_id""",
                (scope, f"{prefix}%"),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE scoped_records SET revision=?,payload_json=?,payload_hash=?,deleted=1,updated_at=?
                       WHERE namespace_scope=? AND record_kind=? AND record_id=? AND deleted=0""",
                    (
                        int(row["revision"]) + 1, _ERASED_PAYLOAD_JSON, _ERASED_PAYLOAD_HASH,
                        now, scope, row["record_kind"], row["record_id"],
                    ),
                )
            result = {
                "code": "namespace_tombstoned" if rows else "namespace_already_empty",
                "count": len(rows),
                "reason_code": reason,
            }
            conn.execute(
                """INSERT INTO scoped_namespace_operations(
                       operation_id,migration_epoch,namespace_scope,request_hash,result_json,created_at
                   ) VALUES(?,?,?,?,?,?)""",
                (operation, context.migration_epoch, scope, request_hash, _canonical(result), now),
            )
        self._truncate_wal()
        return result

    def tombstone_identity_scopes(
        self,
        context: NamespaceContext,
        *,
        operation_id: str,
        reason_code: str,
        record_prefix: str = "req041-",
    ) -> dict[str, Any]:
        """Permanently tombstone one person's private/member projections atomically.

        The caller must authorize with the person's formal private context.  We
        intentionally discover every historical group-member scope inside the
        same transaction so stale groups cannot be orphaned by a caller's
        incomplete context list.  Group-shared and persona-global ownership is
        never part of an individual archive.
        """
        decision = AssurancePolicy.authorize(context, "memory_write")
        if not decision.allowed:
            raise ScopedStoreError(decision.code)
        if context.kind != "private" or context.group_id or not context.identity_id:
            raise ScopedStoreError("scoped_identity_archive_context_invalid")
        if self._active_epoch:
            if context.migration_epoch != self._active_epoch:
                raise ScopedStoreError("scoped_migration_epoch_stale")
            if context.policy_version != self._active_policy_version:
                raise ScopedStoreError("scoped_policy_version_stale")
        operation = _token(operation_id)
        reason = _token(reason_code, 80)
        prefix = _token(record_prefix, 40)
        if not operation or not reason or not prefix:
            raise ScopedStoreError("scoped_identity_archive_invalid")
        target = _canonical({
            "kind": "identity_scopes",
            "persona_id": context.persona_id,
            "identity_id": context.identity_id,
        })
        request_hash = hashlib.sha256(
            _canonical({"target": target, "reason": reason, "prefix": prefix}).encode("utf-8")
        ).hexdigest()
        now = float(self._clock())
        with self._transaction() as conn:
            prior = conn.execute(
                "SELECT request_hash,result_json FROM scoped_namespace_operations WHERE operation_id=? AND migration_epoch=?",
                (operation, context.migration_epoch),
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise ScopedRecordConflict("scoped_namespace_operation_conflict")
                return json.loads(prior["result_json"])
            candidates = conn.execute(
                """SELECT namespace_scope,record_kind,record_id,revision FROM scoped_records
                   WHERE deleted=0 AND record_id LIKE ? ORDER BY namespace_scope,record_kind,record_id""",
                (f"{prefix}%",),
            ).fetchall()
            rows: list[sqlite3.Row] = []
            scopes: set[str] = set()
            for row in candidates:
                try:
                    owner = json.loads(row["namespace_scope"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(owner, dict):
                    continue
                if (
                    owner.get("kind") in {"private", "group_member"}
                    and owner.get("persona_id") == context.persona_id
                    and owner.get("identity_id") == context.identity_id
                ):
                    rows.append(row)
                    scopes.add(str(row["namespace_scope"]))
            for row in rows:
                conn.execute(
                    """UPDATE scoped_records SET revision=?,payload_json=?,payload_hash=?,deleted=1,updated_at=?
                       WHERE namespace_scope=? AND record_kind=? AND record_id=? AND deleted=0""",
                    (
                        int(row["revision"]) + 1, _ERASED_PAYLOAD_JSON, _ERASED_PAYLOAD_HASH,
                        now, row["namespace_scope"],
                        row["record_kind"], row["record_id"],
                    ),
                )
            result = {
                "code": "identity_scopes_tombstoned" if rows else "identity_scopes_already_empty",
                "count": len(rows),
                "namespace_count": len(scopes),
                "reason_code": reason,
            }
            conn.execute(
                """INSERT INTO scoped_namespace_operations(
                       operation_id,migration_epoch,namespace_scope,request_hash,result_json,created_at
                   ) VALUES(?,?,?,?,?,?)""",
                (operation, context.migration_epoch, target, request_hash, _canonical(result), now),
            )
        self._truncate_wal()
        return result

    def erase_group_scopes(
        self,
        context: NamespaceContext,
        *,
        operation_id: str,
        reason_code: str = "group_reset",
        record_prefix: str = "req041-",
    ) -> dict[str, Any]:
        """Atomically empty one group's shared/member projections without banning reuse."""
        decision = AssurancePolicy.authorize(context, "memory_write")
        if not decision.allowed:
            raise ScopedStoreError(decision.code)
        if context.kind != "group_shared" or context.identity_id or not context.group_id:
            raise ScopedStoreError("scoped_group_erase_context_invalid")
        if self._active_epoch:
            if context.migration_epoch != self._active_epoch:
                raise ScopedStoreError("scoped_migration_epoch_stale")
            if context.policy_version != self._active_policy_version:
                raise ScopedStoreError("scoped_policy_version_stale")
        operation = _token(operation_id)
        reason = _token(reason_code, 80)
        prefix = _token(record_prefix, 40)
        if not operation or not reason or not prefix:
            raise ScopedStoreError("scoped_group_erase_invalid")
        target = _canonical({
            "kind": "group_scopes", "persona_id": context.persona_id, "group_id": context.group_id,
        })
        request_hash = hashlib.sha256(
            _canonical({"target": target, "reason": reason, "prefix": prefix}).encode("utf-8")
        ).hexdigest()
        now = float(self._clock())
        with self._transaction() as conn:
            prior = conn.execute(
                "SELECT request_hash,result_json FROM scoped_namespace_operations WHERE operation_id=? AND migration_epoch=?",
                (operation, context.migration_epoch),
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise ScopedRecordConflict("scoped_namespace_operation_conflict")
                return json.loads(prior["result_json"])
            candidates = conn.execute(
                """SELECT namespace_scope,record_kind,record_id,revision,payload_json FROM scoped_records
                   WHERE deleted=0 AND record_id LIKE ? ORDER BY namespace_scope,record_kind,record_id""",
                (f"{prefix}%",),
            ).fetchall()
            rows: list[tuple[sqlite3.Row, str, str]] = []
            scopes: set[str] = set()
            for row in candidates:
                try:
                    owner = json.loads(row["namespace_scope"])
                    payload = json.loads(row["payload_json"])
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ScopedStoreError("scoped_group_erase_record_invalid") from exc
                if not isinstance(owner, dict) or not isinstance(payload, dict):
                    raise ScopedStoreError("scoped_group_erase_record_invalid")
                if not (
                    owner.get("kind") in {"group_shared", "group_member"}
                    and owner.get("persona_id") == context.persona_id
                    and owner.get("group_id") == context.group_id
                ):
                    continue
                try:
                    cleared = build_scoped_domain_payload(
                        domain=str(payload.get("domain") or ""),
                        source_kind=str(payload.get("source_kind") or owner.get("kind") or ""),
                        content={}, source_revision=int(payload.get("source_revision") or 0) + 1,
                        approval_state=str(payload.get("approval_state") or "not_applicable"),
                        approved_by=str(payload.get("approved_by") or ""),
                    )
                    validate_scoped_domain_payload(
                        NamespaceContext(
                            kind=str(owner.get("kind") or ""), persona_id=str(owner.get("persona_id") or ""),
                            identity_id=str(owner.get("identity_id") or ""), group_id=str(owner.get("group_id") or ""),
                            assurance=context.assurance, profile_status=context.profile_status,
                            policy_version=context.policy_version, migration_epoch=context.migration_epoch,
                        ),
                        str(row["record_kind"]), cleared,
                    )
                    encoded, digest = _payload(cleared)
                except (TypeError, ValueError, ScopedDomainContractError, ScopedStoreError) as exc:
                    raise ScopedStoreError("scoped_group_erase_record_invalid") from exc
                rows.append((row, encoded, digest))
                scopes.add(str(row["namespace_scope"]))
            for row, encoded, digest in rows:
                conn.execute(
                    """UPDATE scoped_records SET revision=?,payload_json=?,payload_hash=?,updated_at=?
                       WHERE namespace_scope=? AND record_kind=? AND record_id=? AND deleted=0""",
                    (
                        int(row["revision"]) + 1, encoded, digest, now, row["namespace_scope"],
                        row["record_kind"], row["record_id"],
                    ),
                )
            result = {
                "code": "group_scopes_erased" if rows else "group_scopes_already_empty",
                "count": len(rows), "namespace_count": len(scopes), "reason_code": reason,
            }
            conn.execute(
                """INSERT INTO scoped_namespace_operations(
                       operation_id,migration_epoch,namespace_scope,request_hash,result_json,created_at
                   ) VALUES(?,?,?,?,?,?)""",
                (operation, context.migration_epoch, target, request_hash, _canonical(result), now),
            )
        self._truncate_wal()
        return result

    def erase_persona_scopes(
        self,
        context: NamespaceContext,
        *,
        operation_id: str,
        reason_code: str = "persona_reset",
        record_prefix: str = "req041-",
    ) -> dict[str, Any]:
        """Atomically empty every managed projection owned by one persona."""
        decision = AssurancePolicy.authorize(context, "rule_write")
        if not decision.allowed:
            raise ScopedStoreError(decision.code)
        if context.kind != "persona_global" or context.identity_id or context.group_id:
            raise ScopedStoreError("scoped_persona_erase_context_invalid")
        if self._active_epoch:
            if context.migration_epoch != self._active_epoch:
                raise ScopedStoreError("scoped_migration_epoch_stale")
            if context.policy_version != self._active_policy_version:
                raise ScopedStoreError("scoped_policy_version_stale")
        operation = _token(operation_id)
        reason = _token(reason_code, 80)
        prefix = _token(record_prefix, 40)
        if not operation or not reason or not prefix:
            raise ScopedStoreError("scoped_persona_erase_invalid")
        target = _canonical({"kind": "persona_scopes", "persona_id": context.persona_id})
        request_hash = hashlib.sha256(
            _canonical({"target": target, "reason": reason, "prefix": prefix}).encode("utf-8")
        ).hexdigest()
        now = float(self._clock())
        with self._transaction() as conn:
            prior = conn.execute(
                "SELECT request_hash,result_json FROM scoped_namespace_operations WHERE operation_id=? AND migration_epoch=?",
                (operation, context.migration_epoch),
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise ScopedRecordConflict("scoped_namespace_operation_conflict")
                return json.loads(prior["result_json"])
            candidates = conn.execute(
                """SELECT namespace_scope,record_kind,record_id,revision,payload_json FROM scoped_records
                   WHERE deleted=0 AND record_id LIKE ? ORDER BY namespace_scope,record_kind,record_id""",
                (f"{prefix}%",),
            ).fetchall()
            rows: list[tuple[sqlite3.Row, str, str]] = []
            scopes: set[str] = set()
            kinds: set[str] = set()
            for row in candidates:
                try:
                    owner = json.loads(row["namespace_scope"])
                    payload = json.loads(row["payload_json"])
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ScopedStoreError("scoped_persona_erase_record_invalid") from exc
                if not isinstance(owner, dict) or not isinstance(payload, dict):
                    raise ScopedStoreError("scoped_persona_erase_record_invalid")
                if owner.get("persona_id") != context.persona_id:
                    continue
                try:
                    cleared = build_scoped_domain_payload(
                        domain=str(payload.get("domain") or ""),
                        source_kind=str(payload.get("source_kind") or owner.get("kind") or ""),
                        content={}, source_revision=int(payload.get("source_revision") or 0) + 1,
                        approval_state=str(payload.get("approval_state") or "not_applicable"),
                        approved_by=str(payload.get("approved_by") or ""),
                    )
                    validate_scoped_domain_payload(
                        NamespaceContext(
                            kind=str(owner.get("kind") or ""), persona_id=str(owner.get("persona_id") or ""),
                            identity_id=str(owner.get("identity_id") or ""), group_id=str(owner.get("group_id") or ""),
                            assurance=context.assurance, profile_status=context.profile_status,
                            policy_version=context.policy_version, migration_epoch=context.migration_epoch,
                        ),
                        str(row["record_kind"]), cleared,
                    )
                    encoded, digest = _payload(cleared)
                except (TypeError, ValueError, ScopedDomainContractError, ScopedStoreError) as exc:
                    raise ScopedStoreError("scoped_persona_erase_record_invalid") from exc
                rows.append((row, encoded, digest))
                scopes.add(str(row["namespace_scope"]))
                kinds.add(str(owner.get("kind") or ""))
            for row, encoded, digest in rows:
                conn.execute(
                    """UPDATE scoped_records SET revision=?,payload_json=?,payload_hash=?,updated_at=?
                       WHERE namespace_scope=? AND record_kind=? AND record_id=? AND deleted=0""",
                    (
                        int(row["revision"]) + 1, encoded, digest, now, row["namespace_scope"],
                        row["record_kind"], row["record_id"],
                    ),
                )
            result = {
                "code": "persona_scopes_erased" if rows else "persona_scopes_already_empty",
                "count": len(rows), "namespace_count": len(scopes),
                "namespace_kinds": sorted(kinds), "reason_code": reason,
            }
            conn.execute(
                """INSERT INTO scoped_namespace_operations(
                       operation_id,migration_epoch,namespace_scope,request_hash,result_json,created_at
                   ) VALUES(?,?,?,?,?,?)""",
                (operation, context.migration_epoch, target, request_hash, _canonical(result), now),
            )
        self._truncate_wal()
        return result

    @staticmethod
    def _maintenance_scope_matches(
        owner: dict[str, Any],
        *,
        target_type: str,
        identity_id: str,
        group_id: str,
        persona_id: str,
    ) -> bool:
        kind = _token(owner.get("kind"), 40)
        owner_identity = _token(owner.get("identity_id"))
        owner_group = _token(owner.get("group_id"))
        owner_persona = _token(owner.get("persona_id"))
        if target_type == "private":
            return kind == "private" and owner_identity == identity_id
        if target_type == "group":
            return kind in {"group_shared", "group_member"} and owner_group == group_id
        if target_type == "group_member":
            return (
                kind == "group_member"
                and owner_group == group_id
                and owner_identity == identity_id
            )
        return bool(owner_persona) and owner_persona == persona_id

    def clear_all_records(self) -> dict[str, Any]:
        """Tombstone every business record while retaining control/audit ledgers."""

        with self._lock:
            backup = self.backup(".before_clear_all")
            now = float(self._clock())
            with self._transaction(allow_fenced_maintenance=True) as conn:
                rows = conn.execute(
                    "SELECT record_kind,COUNT(*) AS count FROM scoped_records "
                    "WHERE deleted=0 GROUP BY record_kind"
                ).fetchall()
                counts = {
                    str(row["record_kind"]): int(row["count"] or 0)
                    for row in rows
                }
                cursor = conn.execute(
                    "UPDATE scoped_records SET revision=revision+1,payload_json=?,payload_hash=?,deleted=1,updated_at=? "
                    "WHERE deleted=0",
                    (_ERASED_PAYLOAD_JSON, _ERASED_PAYLOAD_HASH, now),
                )
            self._truncate_wal()
        return {
            "backup": str(backup),
            "counts": {**counts, "total": sum(counts.values())},
            "deleted": int(cursor.rowcount or 0),
            "control_data_retained": True,
        }

    def clear_scoped_records(
        self,
        *,
        target_type: str,
        identity_id: str = "",
        group_id: str = "",
        persona_id: str = "",
    ) -> dict[str, Any]:
        target = _token(target_type, 40).lower()
        identity = _token(identity_id)
        group = _token(group_id)
        persona = _token(persona_id)
        if target not in {"private", "group", "group_member", "persona"}:
            raise ScopedStoreError("scoped_clear_target_invalid")
        if target == "private" and not identity:
            raise ScopedStoreError("scoped_clear_identity_required")
        if target == "group" and not group:
            raise ScopedStoreError("scoped_clear_group_required")
        if target == "group_member" and (not identity or not group):
            raise ScopedStoreError("scoped_clear_group_member_required")
        if target == "persona" and not persona:
            raise ScopedStoreError("scoped_clear_persona_required")

        matched: list[tuple[str, str, str]] = []
        counts: dict[str, int] = {}
        with self._lock:
            backup = self.backup(f".before_clear_{target}")
            now = float(self._clock())
            with self._transaction(allow_fenced_maintenance=True) as conn:
                rows = conn.execute(
                    "SELECT namespace_scope,record_kind,record_id FROM scoped_records WHERE deleted=0"
                ).fetchall()
                for row in rows:
                    try:
                        owner = json.loads(str(row["namespace_scope"]))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if not isinstance(owner, dict) or not self._maintenance_scope_matches(
                        owner,
                        target_type=target,
                        identity_id=identity,
                        group_id=group,
                        persona_id=persona,
                    ):
                        continue
                    key = (
                        str(row["namespace_scope"]),
                        str(row["record_kind"]),
                        str(row["record_id"]),
                    )
                    matched.append(key)
                    counts[key[1]] = counts.get(key[1], 0) + 1
                for namespace_scope, record_kind, record_id in matched:
                    conn.execute(
                        "UPDATE scoped_records SET revision=revision+1,payload_json=?,payload_hash=?,deleted=1,updated_at=? "
                        "WHERE namespace_scope=? AND record_kind=? AND record_id=? AND deleted=0",
                        (
                            _ERASED_PAYLOAD_JSON,
                            _ERASED_PAYLOAD_HASH,
                            now,
                            namespace_scope,
                            record_kind,
                            record_id,
                        ),
                    )
            self._truncate_wal()
        return {
            "target_type": target,
            "identity_id": identity,
            "group_id": group,
            "persona_id": persona,
            "backup": str(backup),
            "counts": {**counts, "total": len(matched)},
            "deleted": len(matched),
            "control_data_retained": True,
        }

    def preview_scoped_records(
        self,
        *,
        target_type: str,
        identity_id: str = "",
        group_id: str = "",
        persona_id: str = "",
    ) -> dict[str, Any]:
        """Count one maintenance scope without backup or record mutation."""

        target = _token(target_type, 40).lower()
        identity = _token(identity_id)
        group = _token(group_id)
        persona = _token(persona_id)
        if target not in {"private", "group", "group_member", "persona"}:
            raise ScopedStoreError("scoped_clear_target_invalid")
        if target == "private" and not identity:
            raise ScopedStoreError("scoped_clear_identity_required")
        if target == "group" and not group:
            raise ScopedStoreError("scoped_clear_group_required")
        if target == "group_member" and (not identity or not group):
            raise ScopedStoreError("scoped_clear_group_member_required")
        if target == "persona" and not persona:
            raise ScopedStoreError("scoped_clear_persona_required")

        counts: dict[str, int] = {}
        total = 0
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT namespace_scope,record_kind FROM scoped_records WHERE deleted=0"
            ).fetchall()
            for row in rows:
                try:
                    owner = json.loads(str(row["namespace_scope"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(owner, dict) or not self._maintenance_scope_matches(
                    owner,
                    target_type=target,
                    identity_id=identity,
                    group_id=group,
                    persona_id=persona,
                ):
                    continue
                kind = str(row["record_kind"])
                counts[kind] = counts.get(kind, 0) + 1
                total += 1
        return {
            "target_type": target,
            "identity_id": identity,
            "group_id": group,
            "persona_id": persona,
            "preview": True,
            "counts": {**counts, "total": total},
        }


__all__ = [
    "MAX_RECORD_BYTES", "RECORD_KINDS", "ScopedRecordConflict", "ScopedRevisionGap", "ScopedStore",
    "ScopedStoreError",
]
