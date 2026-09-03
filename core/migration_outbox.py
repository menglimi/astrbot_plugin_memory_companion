"""REQ-041 durable outbox, revision, epoch and tombstone primitives."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterator

from .namespace import NamespaceContext, validate_namespace_context


MIGRATION_STATES = frozenset({"active", "degraded", "paused", "replaying", "verified"})
OUTBOX_STATES = frozenset({"pending", "applied", "failed", "discarded"})
MAX_PAYLOAD_BYTES = 32768
FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "chat_text", "content", "conversation", "evidence_body", "message_text", "messages", "prompt", "raw_text",
})


class OutboxError(RuntimeError):
    pass


class OutboxConflict(OutboxError):
    pass


class RevisionGap(OutboxError):
    pass


class StaleMigrationEpoch(OutboxError):
    pass


@dataclass(frozen=True, slots=True)
class OutboxItem:
    event_id: str
    migration_epoch: str
    source_revision: int
    namespace: dict[str, str]
    policy_version: str
    payload: dict[str, Any]
    payload_hash: str
    state: str
    retry_count: int
    error_code: str
    target_revision: int


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _contains_forbidden(value: Any, depth: int = 0) -> bool:
    if depth > 5:
        return True
    if isinstance(value, dict):
        return any(
            not isinstance(key, str)
            or key.strip().lower() in FORBIDDEN_PAYLOAD_KEYS
            or _contains_forbidden(item, depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden(item, depth + 1) for item in value)
    return not (value is None or isinstance(value, (str, int, float, bool)))


def _payload(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict) or _contains_forbidden(value):
        raise OutboxError("outbox_payload_invalid")
    try:
        encoded = _canonical(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OutboxError("outbox_payload_invalid") from exc
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise OutboxError("outbox_payload_too_large")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _token(value: Any, *, limit: int = 128) -> str:
    if not isinstance(value, str):
        return ""
    result = value.strip()
    if not result or len(result) > limit or any(ord(ch) < 32 for ch in result):
        return ""
    return result


class MigrationOutbox:
    """SQLite-backed single-process outbox with transactional idempotency."""

    def __init__(self, path: str | Path, *, clock: Any = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock if callable(clock) else time.time
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _connection_locked(self) -> sqlite3.Connection:
        # 复用单连接，避免每次操作新建/销毁连接并重复执行 PRAGMA。
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # 复用单连接后读路径也需持锁，防止多线程并发使用同一连接。
        with self._lock:
            yield self._connection_locked()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connection_locked()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                if conn.in_transaction:
                    conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def close(self) -> None:
        """释放底层 SQLite 连接（实例不再使用时调用）。"""
        with self._lock:
            conn, self._conn = self._conn, None
            if conn is not None:
                conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS migration_epochs (
                    migration_epoch TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    checkpoint TEXT NOT NULL DEFAULT '',
                    policy_version TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    event_id TEXT NOT NULL,
                    migration_epoch TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    namespace_json TEXT NOT NULL,
                    namespace_scope TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    target_revision INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (event_id, migration_epoch),
                    FOREIGN KEY (migration_epoch) REFERENCES migration_epochs(migration_epoch)
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(migration_epoch, state, source_revision, created_at);
                CREATE TABLE IF NOT EXISTS revisions (
                    stream_key TEXT NOT NULL,
                    migration_epoch TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (stream_key, migration_epoch),
                    FOREIGN KEY (migration_epoch) REFERENCES migration_epochs(migration_epoch)
                );
                CREATE TABLE IF NOT EXISTS tombstones (
                    object_key TEXT NOT NULL,
                    migration_epoch TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    reason_code TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (object_key, migration_epoch),
                    FOREIGN KEY (migration_epoch) REFERENCES migration_epochs(migration_epoch)
                );
                """
            )

    def begin_epoch(self, migration_epoch: str, *, policy_version: str, state: str = "active") -> dict[str, Any]:
        epoch = _token(migration_epoch)
        policy = _token(policy_version, limit=64)
        if not epoch or not policy or state not in MIGRATION_STATES:
            raise OutboxError("migration_epoch_invalid")
        now = float(self._clock())
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state, checkpoint, policy_version FROM migration_epochs WHERE migration_epoch=?", (epoch,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO migration_epochs(migration_epoch,state,checkpoint,policy_version,updated_at) VALUES(?,?,?,?,?)",
                    (epoch, state, "", policy, now),
                )
            elif row["policy_version"] != policy:
                raise OutboxConflict("migration_epoch_policy_conflict")
        return self.epoch_status(epoch)

    def epoch_status(self, migration_epoch: str) -> dict[str, Any]:
        epoch = _token(migration_epoch)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT migration_epoch,state,checkpoint,policy_version,updated_at FROM migration_epochs WHERE migration_epoch=?",
                (epoch,),
            ).fetchone()
        return dict(row) if row is not None else {}

    def set_epoch_state(self, migration_epoch: str, state: str, *, checkpoint: str | None = None) -> dict[str, Any]:
        epoch = _token(migration_epoch)
        if state not in MIGRATION_STATES:
            raise OutboxError("migration_state_invalid")
        with self._transaction() as conn:
            row = conn.execute("SELECT checkpoint FROM migration_epochs WHERE migration_epoch=?", (epoch,)).fetchone()
            if row is None:
                raise StaleMigrationEpoch("migration_epoch_missing")
            value = row["checkpoint"] if checkpoint is None else _token(checkpoint, limit=256)
            conn.execute(
                "UPDATE migration_epochs SET state=?,checkpoint=?,updated_at=? WHERE migration_epoch=?",
                (state, value, float(self._clock()), epoch),
            )
        return self.epoch_status(epoch)

    def _require_epoch(self, conn: sqlite3.Connection, epoch: str, policy: str) -> None:
        row = conn.execute(
            "SELECT state,policy_version FROM migration_epochs WHERE migration_epoch=?", (epoch,)
        ).fetchone()
        if row is None:
            raise StaleMigrationEpoch("migration_epoch_missing")
        if row["policy_version"] != policy:
            raise StaleMigrationEpoch("migration_policy_stale")
        if row["state"] == "verified":
            raise StaleMigrationEpoch("migration_epoch_closed")

    def enqueue(
        self,
        *,
        event_id: str,
        source_revision: int,
        namespace: NamespaceContext,
        migration_epoch: str,
        policy_version: str,
        payload: dict[str, Any],
    ) -> str:
        event = _token(event_id)
        epoch = _token(migration_epoch)
        policy = _token(policy_version, limit=64)
        if not event or source_revision < 1 or not epoch or not policy:
            raise OutboxError("outbox_envelope_invalid")
        namespace_payload = namespace.to_dict() if isinstance(namespace, NamespaceContext) else {}
        if validate_namespace_context(namespace_payload):
            raise OutboxError("outbox_namespace_invalid")
        if namespace.migration_epoch != epoch or namespace.policy_version != policy:
            raise StaleMigrationEpoch("outbox_namespace_epoch_mismatch")
        encoded, digest = _payload(payload)
        namespace_json = _canonical(namespace_payload)
        now = float(self._clock())
        with self._transaction() as conn:
            self._require_epoch(conn, epoch, policy)
            existing = conn.execute(
                "SELECT source_revision,namespace_json,policy_version,payload_hash FROM outbox WHERE event_id=? AND migration_epoch=?",
                (event, epoch),
            ).fetchone()
            if existing is not None:
                same = (
                    existing["source_revision"] == source_revision
                    and existing["namespace_json"] == namespace_json
                    and existing["policy_version"] == policy
                    and existing["payload_hash"] == digest
                )
                if same:
                    return "duplicate"
                raise OutboxConflict("outbox_event_conflict")
            conn.execute(
                """INSERT INTO outbox(
                    event_id,migration_epoch,source_revision,namespace_json,namespace_scope,policy_version,
                    payload_json,payload_hash,state,retry_count,error_code,target_revision,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event, epoch, source_revision, namespace_json, namespace.cache_scope(), policy,
                    encoded, digest, "pending", 0, "", 0, now, now,
                ),
            )
        return "enqueued"

    @staticmethod
    def _item(row: sqlite3.Row) -> OutboxItem:
        return OutboxItem(
            event_id=row["event_id"], migration_epoch=row["migration_epoch"], source_revision=row["source_revision"],
            namespace=json.loads(row["namespace_json"]), policy_version=row["policy_version"],
            payload=json.loads(row["payload_json"]), payload_hash=row["payload_hash"], state=row["state"],
            retry_count=row["retry_count"], error_code=row["error_code"], target_revision=row["target_revision"],
        )

    def pending(self, migration_epoch: str, *, limit: int = 100) -> list[OutboxItem]:
        epoch = _token(migration_epoch)
        safe_limit = max(1, min(1000, int(limit)))
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM outbox WHERE migration_epoch=? AND state IN ('pending','failed') ORDER BY source_revision,created_at LIMIT ?",
                (epoch, safe_limit),
            ).fetchall()
        return [self._item(row) for row in rows]

    def mark_applied(self, event_id: str, migration_epoch: str, *, target_revision: int) -> None:
        if target_revision < 1:
            raise OutboxError("target_revision_invalid")
        with self._transaction() as conn:
            changed = conn.execute(
                "UPDATE outbox SET state='applied',target_revision=?,error_code='',updated_at=? WHERE event_id=? AND migration_epoch=?",
                (target_revision, float(self._clock()), _token(event_id), _token(migration_epoch)),
            ).rowcount
            if changed != 1:
                raise OutboxError("outbox_event_missing")

    def mark_failed(self, event_id: str, migration_epoch: str, *, error_code: str) -> None:
        error = _token(error_code, limit=80) or "target_write_failed"
        with self._transaction() as conn:
            changed = conn.execute(
                "UPDATE outbox SET state='failed',retry_count=retry_count+1,error_code=?,updated_at=? WHERE event_id=? AND migration_epoch=?",
                (error, float(self._clock()), _token(event_id), _token(migration_epoch)),
            ).rowcount
            if changed != 1:
                raise OutboxError("outbox_event_missing")

    def advance_revision(self, stream_key: str, migration_epoch: str, *, expected: int, target: int) -> str:
        stream = _token(stream_key)
        epoch = _token(migration_epoch)
        if not stream or expected < 0 or target != expected + 1:
            raise OutboxError("revision_request_invalid")
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM migration_epochs WHERE migration_epoch=?", (epoch,)).fetchone() is None:
                raise StaleMigrationEpoch("migration_epoch_missing")
            row = conn.execute(
                "SELECT revision FROM revisions WHERE stream_key=? AND migration_epoch=?", (stream, epoch)
            ).fetchone()
            current = int(row["revision"]) if row is not None else 0
            if current == target:
                return "duplicate"
            if current != expected:
                raise RevisionGap(f"revision_gap:{current}:{expected}:{target}")
            conn.execute(
                """INSERT INTO revisions(stream_key,migration_epoch,revision,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(stream_key,migration_epoch) DO UPDATE SET revision=excluded.revision,updated_at=excluded.updated_at""",
                (stream, epoch, target, float(self._clock())),
            )
        return "advanced"

    def add_tombstone(self, object_key: str, migration_epoch: str, *, revision: int, reason_code: str) -> str:
        key = _token(object_key)
        epoch = _token(migration_epoch)
        reason = _token(reason_code, limit=80)
        if not key or revision < 1 or not reason:
            raise OutboxError("tombstone_invalid")
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM migration_epochs WHERE migration_epoch=?", (epoch,)).fetchone() is None:
                raise StaleMigrationEpoch("migration_epoch_missing")
            row = conn.execute(
                "SELECT revision,reason_code FROM tombstones WHERE object_key=? AND migration_epoch=?", (key, epoch)
            ).fetchone()
            if row is not None:
                if row["revision"] == revision and row["reason_code"] == reason:
                    return "duplicate"
                raise OutboxConflict("tombstone_conflict")
            conn.execute(
                "INSERT INTO tombstones(object_key,migration_epoch,revision,reason_code,created_at) VALUES(?,?,?,?,?)",
                (key, epoch, revision, reason, float(self._clock())),
            )
        return "created"

    def tombstone(self, object_key: str, migration_epoch: str) -> dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT object_key,migration_epoch,revision,reason_code,created_at FROM tombstones WHERE object_key=? AND migration_epoch=?",
                (_token(object_key), _token(migration_epoch)),
            ).fetchone()
        return dict(row) if row is not None else {}


__all__ = [
    "MAX_PAYLOAD_BYTES", "MIGRATION_STATES", "OUTBOX_STATES", "MigrationOutbox", "OutboxConflict",
    "OutboxError", "OutboxItem", "RevisionGap", "StaleMigrationEpoch",
]
