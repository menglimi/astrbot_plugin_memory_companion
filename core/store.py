from __future__ import annotations

import asyncio
import hashlib
import json
import math

from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import re
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Any

from .identity import parse_scope_from_session
from .astrbot_compat import logger
from .memory_atom import (
    DURABILITY_LEVELS,
    SENSITIVITY_LEVELS,
    VALIDITY_STATUSES,
    clamp_score,
    normalize_durability,
    normalize_sensitivity,
    normalize_validity_status,
    validity_where_clause,
)
from .models import (
    EntityRef,
    MemoryRecord,
    clean_text,
    is_memory_placeholder,
    json_dumps,
    json_loads,
    new_id,
    stable_fingerprint,
    utc_now,
)
from .models import memory_embedding_text_hash
from .portrait import cross_scene_whitelisted_fact
from .profile_quality import normalize_profile_value, profile_quality_decision
from .portrait_namespace import portrait_scope_kind, portrait_scope_persona
from .sensitive_data import redact_sensitive_text, redact_sensitive_value


_ACL_UNSET = object()


# 向量二进制格式常量：little-endian float64 打包，
# 相比 JSON 文本列可减少约 60% 存储体积并省去 json 解析开销。
_EMBEDDING_VECTOR_FMT = "<d"


def _pack_embedding_vector(values: list[float]) -> bytes:
    """把向量序列化为二进制 bytes（兼容旧 JSON 文本读取）。"""
    floats = [float(item) for item in values if isinstance(item, (int, float))]
    if not floats:
        return b""
    return struct.pack(f"<{len(floats)}d", *floats)


def _unpack_embedding_vector(raw: Any) -> list[float]:
    """按二进制格式解析向量；若是旧 JSON 文本则回退 json 解析。"""
    if isinstance(raw, (bytes, bytearray, memoryview)):
        payload = bytes(raw)
        count = len(payload) // 8
        if count <= 0:
            return []
        return list(struct.unpack(f"<{count}d", payload[: count * 8]))
    if isinstance(raw, str) and raw:
        payload = json_loads(raw, [])
        if isinstance(payload, list):
            vector: list[float] = []
            for item in payload:
                try:
                    vector.append(float(item))
                except Exception:
                    return []
            return vector
    return []


def _normalize_embedding_vector_values(values: list[float]) -> list[float]:
    """对向量做 L2 归一化，供候选缓存一次性归一化，避免每次召回重复计算。"""
    if not values:
        return []
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return []
    return [value / norm for value in values]


class MemoryStore:
    EMBEDDING_CANDIDATE_CACHE_MAX = 64
    SCHEMA_VERSION = "memory-atom-v2"
    # Redaction is idempotent but scanning the whole history at every startup
    # is needlessly expensive for large installations.  Bump this when the
    # storage redaction rules change so existing data gets one fresh pass.
    SENSITIVE_REDACTION_VERSION = "storage-redaction-v1"

    PROFILE_MEMORY_TYPES = frozenset({"user_profile", "user_preference", "user_habit"})

    PROFILE_RULE_EXTRACTORS = frozenset({"rule_v1", "rule_v2"})

    PROFILE_RULE_PORTRAIT_VERSIONS = frozenset(
        {"req036.rule.v1", "req036.rule.v2"}
    )

    # Keep storage-only archive references out of every recall index while
    # retaining the rows for the dedicated Bot Personal profile bridge.
    @classmethod
    def _recallable_memory_sql(cls, alias: str = "") -> str:
        normalized_alias = clean_text(alias, 40)
        prefix = f"{normalized_alias}." if normalized_alias else ""
        return (
            f"{prefix}source_plugin != 'bot_personal_bridge' AND "
            f"lower({prefix}content) NOT LIKE 'bot personal archive reference [%]'"
        )

    PROFILE_SINGLE_VALUE_DIMENSIONS = frozenset(
        {
            "preferred_address",
            "name",
            "birthday",
            "birth_date",
            "occupation",
            "profession",
            "education",
            "major",
            "zodiac",
            "zodiac_or_blood_type",
            "blood_type",
        }
    )

    def __init__(self, db_path: Path, *, read_only: bool = False):
        self.db_path = Path(db_path)
        self._read_only = bool(read_only)
        if self._read_only:
            if not self.db_path.is_file():
                raise FileNotFoundError(
                    f"memory database does not exist: {self.db_path}"
                )
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open_connection()
        self._lock = threading.RLock()
        # 专用只读连接（WAL 下与主连接写入真正并行）：候选加载等纯读操作
        # 不再排队等主连接写锁，对应 optimization_plan.md §6.1。
        self._read_conn: sqlite3.Connection | None = None
        self._read_lock = threading.RLock()
        self._operation_condition = threading.Condition()
        self._active_tracked_operations = 0
        self._closing = False
        self._closed = False
        self._fts_enabled = False
        self._knowledge_trgm_enabled = False
        self._savepoint_counter = 0
        self._embedding_candidate_cache_revision = ""
        self._embedding_candidate_cache: dict[
            tuple[str, bool, int],
            list[tuple[MemoryRecord, list[float], str]],
        ] = {}
        self._acl_feature_override_cache: dict[
            tuple[str, str], tuple[bool | None, bool | None]
        ] = {}
        self._last_wal_health: dict[str, Any] = {}
        self._last_database_error: dict[str, Any] = {}
        self._database_recovery_attempts = 0
        self._database_recovery_successes = 0
        self.last_schema_backup_path = ""

    def _open_connection(self) -> sqlite3.Connection:
        database = str(self.db_path)
        uri = False
        if self._read_only:
            database = f"{self.db_path.resolve().as_uri()}?mode=ro"
            uri = True
        connection = sqlite3.connect(
            database,
            timeout=3.0,
            check_same_thread=False,
            uri=uri,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=3000")
        if not self._read_only:
            connection.execute("PRAGMA wal_autocheckpoint=500")
        return connection

    def _ensure_read_connection(self) -> sqlite3.Connection:
        """Lazily open a dedicated read-only connection.

        Under WAL this reader runs concurrently with the main connection's
        writes, so pure-read paths (candidate loading) stop queueing behind
        the main write lock. Read-only stores simply reuse the main
        connection, which is already opened with mode=ro.
        """
        if self._read_only:
            return self._conn
        conn = self._read_conn
        if conn is None:
            with self._read_lock:
                conn = self._read_conn
                if conn is None:
                    conn = sqlite3.connect(
                        f"{self.db_path.resolve().as_uri()}?mode=ro",
                        timeout=3.0,
                        check_same_thread=False,
                        uri=True,
                    )
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA busy_timeout=3000")
                    self._read_conn = conn
        return conn

    def _read_connection_for_bundle(self) -> tuple[sqlite3.Connection, threading.RLock]:
        if self._read_only:
            return self._conn, self._lock
        return self._ensure_read_connection(), self._read_lock

    @staticmethod
    def _is_database_path_error(error: BaseException) -> bool:
        if not isinstance(error, sqlite3.OperationalError):
            return False
        message = str(error).strip().lower()
        return "unable to open database file" in message or "cannot open database" in message

    def _recover_connection_sync(self) -> None:
        """Replace a broken connection without ever creating an empty database."""
        with self._lock:
            if self._closed:
                raise sqlite3.ProgrammingError("memory database is closed")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.db_path.is_file():
                raise sqlite3.OperationalError(
                    f"memory database file is missing: {self.db_path}; restart or restore the data directory"
                )
            replacement = self._open_connection()
            try:
                replacement.execute("PRAGMA journal_mode=WAL")
                replacement.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            except BaseException:
                replacement.close()
                raise
            previous = self._conn
            self._conn = replacement
            try:
                previous.close()
            except sqlite3.Error:
                pass

    def _run_with_database_recovery_sync(self, operation: Any, *args: Any) -> Any:
        try:
            return operation(*args)
        except sqlite3.OperationalError as error:
            if not self._is_database_path_error(error):
                raise
            self._database_recovery_attempts += 1
            error_details = {
                "recorded_at": utc_now(),
                "message": clean_text(error, 500),
                "sqlite_errorcode": getattr(error, "sqlite_errorcode", None),
                "sqlite_errorname": clean_text(getattr(error, "sqlite_errorname", ""), 80),
                **self._database_file_snapshot(),
            }
            self._last_database_error = dict(error_details)
            try:
                health = self._wal_health_sync(checkpoint=False)
            except Exception as health_error:
                health = {
                    "health_error": clean_text(health_error, 500),
                    **self._database_file_snapshot(),
                }
            self._last_wal_health = {
                **health,
                "last_database_error": dict(error_details),
                "database_recovery_attempts": self._database_recovery_attempts,
                "database_recovery_successes": self._database_recovery_successes,
            }
            with self._lock:
                if self._conn.in_transaction:
                    self._conn.rollback()
            self._recover_connection_sync()
            self._database_recovery_successes += 1
            return operation(*args)

    async def _run_recoverable_database_operation(self, operation: Any, *args: Any) -> Any:
        return await asyncio.to_thread(self._run_with_database_recovery_sync, operation, *args)

    async def _run_tracked_operation(
        self,
        operation: Any,
        *args: Any,
        closed_result: Any = None,
    ) -> Any:
        """Keep a queued executor write alive until store shutdown can flush it."""

        with self._operation_condition:
            if self._closing or self._closed:
                return closed_result
            self._active_tracked_operations += 1

        def run() -> Any:
            try:
                return operation(*args)
            finally:
                with self._operation_condition:
                    self._active_tracked_operations -= 1
                    self._operation_condition.notify_all()

        try:
            future = asyncio.get_running_loop().run_in_executor(None, run)
        except BaseException:
            with self._operation_condition:
                self._active_tracked_operations -= 1
                self._operation_condition.notify_all()
            raise
        return await asyncio.shield(future)

    def _database_file_snapshot(self) -> dict[str, Any]:
        def size(path: Path) -> int:
            try:
                return int(path.stat().st_size)
            except OSError:
                return -1

        wal_path = Path(str(self.db_path) + "-wal")
        shm_path = Path(str(self.db_path) + "-shm")
        return {
            "db_exists": self.db_path.is_file(),
            "db_bytes": size(self.db_path),
            "wal_exists": wal_path.is_file(),
            "wal_bytes": size(wal_path),
            "shm_exists": shm_path.is_file(),
            "shm_bytes": size(shm_path),
        }

    async def wal_health(self, *, checkpoint: bool = False) -> dict[str, Any]:
        return await asyncio.to_thread(self._wal_health_sync, checkpoint)

    def _wal_health_sync(self, checkpoint: bool = False) -> dict[str, Any]:
        result = self._database_file_snapshot()
        result.update(
            {
                "checkpoint_attempted": False,
                "checkpoint_busy": None,
                "checkpoint_log_frames": None,
                "checkpointed_frames": None,
            }
        )
        with self._lock:
            result["in_transaction"] = bool(self._conn.in_transaction)
            result["busy_timeout_ms"] = int(self._conn.execute("PRAGMA busy_timeout").fetchone()[0] or 0)
            result["wal_autocheckpoint_pages"] = int(
                self._conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0] or 0
            )
            if checkpoint and not self._conn.in_transaction:
                row = self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                result["checkpoint_attempted"] = True
                if row is not None and len(row) >= 3:
                    result["checkpoint_busy"] = int(row[0] or 0)
                    result["checkpoint_log_frames"] = int(row[1] or 0)
                    result["checkpointed_frames"] = int(row[2] or 0)
        result.update({f"after_{key}": value for key, value in self._database_file_snapshot().items()})
        result["database_recovery_attempts"] = self._database_recovery_attempts
        result["database_recovery_successes"] = self._database_recovery_successes
        if self._last_database_error:
            result["last_database_error"] = dict(self._last_database_error)
        self._last_wal_health = dict(result)
        return result

    async def wal_checkpoint_truncate(self, *, min_wal_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
        """Best-effort TRUNCATE checkpoint to bound the WAL file size.

        A long-running WAL reader (the dedicated candidate-load connection) can
        keep the passive auto-checkpoint from ever truncating the ``-wal`` file,
        so it grows to its high-water mark and stays there — a 146MB WAL was
        observed in production, which slows every subsequent read. This runs a
        ``wal_checkpoint(TRUNCATE)`` on the main connection only when the WAL is
        above ``min_wal_bytes`` and no write transaction is active; a busy
        result is not an error.
        """
        return await asyncio.to_thread(self._wal_checkpoint_truncate_sync, min_wal_bytes)

    def _wal_checkpoint_truncate_sync(self, min_wal_bytes: int) -> dict[str, Any]:
        result = self._database_file_snapshot()
        result.update(
            {
                "checkpoint_attempted": False,
                "checkpoint_mode": "truncate",
                "checkpoint_busy": None,
                "checkpoint_log_frames": None,
                "checkpointed_frames": None,
            }
        )
        if self._read_only:
            result["skipped"] = "read_only"
            return result
        if result.get("wal_bytes", -1) < max(0, int(min_wal_bytes)):
            result["skipped"] = "below_threshold"
            return result
        with self._lock:
            if self._conn.in_transaction:
                result["skipped"] = "in_transaction"
                return result
            try:
                row = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                result["checkpoint_attempted"] = True
                if row is not None and len(row) >= 3:
                    result["checkpoint_busy"] = int(row[0] or 0)
                    result["checkpoint_log_frames"] = int(row[1] or 0)
                    result["checkpointed_frames"] = int(row[2] or 0)
            except sqlite3.Error as exc:
                result["checkpoint_error"] = clean_text(exc, 200)
        result.update({f"after_{key}": value for key, value in self._database_file_snapshot().items()})
        return result

    @contextmanager
    def _transaction_sync(self):
        """Run a write unit atomically; callers must hold ``self._lock``."""
        if self._conn.in_transaction:
            self._savepoint_counter += 1
            savepoint = f"memory_companion_{self._savepoint_counter}"
            self._conn.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            return
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def initialize(self) -> None:
        if self._read_only:
            with self._lock:
                memories = self._conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
                ).fetchone()
                if memories is None:
                    raise sqlite3.DatabaseError(
                        "memory database schema is missing the memories table"
                    )
                self._fts_enabled = bool(
                    self._conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_fts'"
                    ).fetchone()
                )
            return
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self.last_schema_backup_path = self._backup_before_schema_upgrade_sync()
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    subject_kind TEXT NOT NULL DEFAULT '',
                    subject_id TEXT NOT NULL DEFAULT '',
                    subject_name TEXT NOT NULL DEFAULT '',
                    subject_role TEXT NOT NULL DEFAULT '',
                    object_kind TEXT NOT NULL DEFAULT '',
                    object_id TEXT NOT NULL DEFAULT '',
                    object_name TEXT NOT NULL DEFAULT '',
                    object_role TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    message_id TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    visibility TEXT NOT NULL DEFAULT '',
                    sayability TEXT NOT NULL DEFAULT '',
                    reality_level TEXT NOT NULL DEFAULT '',
                    lifecycle TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    evidence TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    importance REAL NOT NULL DEFAULT 0.3,
                    owner_bot_id TEXT NOT NULL DEFAULT '',
                    validity_status TEXT NOT NULL DEFAULT 'active'
                        CHECK(validity_status IN ('active','superseded','expired','archived','deleted','quarantined')),
                    valid_from TEXT NOT NULL DEFAULT '',
                    valid_to TEXT NOT NULL DEFAULT '',
                    salience REAL NOT NULL DEFAULT 0.3 CHECK(salience >= 0 AND salience <= 1),
                    durability TEXT NOT NULL DEFAULT 'normal'
                        CHECK(durability IN ('ephemeral','short','normal','durable','pinned')),
                    sensitivity TEXT NOT NULL DEFAULT 'private'
                        CHECK(sensitivity IN ('public','internal','private','restricted')),
                    reinforcement_score REAL NOT NULL DEFAULT 0
                        CHECK(reinforcement_score >= 0 AND reinforcement_score <= 1),
                    injection_count INTEGER NOT NULL DEFAULT 0 CHECK(injection_count >= 0),
                    last_injected_at TEXT NOT NULL DEFAULT '',
                    canonical_key TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL DEFAULT 'auto',
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    occurred_at TEXT NOT NULL DEFAULT '',
                    last_accessed_at TEXT NOT NULL DEFAULT '',
                    access_count INTEGER NOT NULL DEFAULT 0,
                    source_plugin TEXT NOT NULL DEFAULT '',
                    import_batch_id TEXT NOT NULL DEFAULT '',
                    content_fingerprint TEXT NOT NULL DEFAULT '',
                    merged_count INTEGER NOT NULL DEFAULT 1,
                    supersedes_id TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_memories_scope_session
                    ON memories(scope, session_id, group_id, subject_id, object_id);
                CREATE INDEX IF NOT EXISTS idx_memories_visibility
                    ON memories(visibility, review_status, lifecycle);
                CREATE INDEX IF NOT EXISTS idx_memories_reality
                    ON memories(reality_level, memory_type, occurred_at);
                CREATE INDEX IF NOT EXISTS idx_memories_content
                    ON memories(content);

                CREATE TABLE IF NOT EXISTS identities (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL DEFAULT '',
                    entity_kind TEXT NOT NULL DEFAULT 'user',
                    entity_id TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT 'unknown',
                    aliases TEXT NOT NULL DEFAULT '[]',
                    profile TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(platform, entity_kind, entity_id)
                );

                CREATE TABLE IF NOT EXISTS timeline (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    subject_id TEXT NOT NULL DEFAULT '',
                    object_id TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    message_id TEXT NOT NULL DEFAULT '',
                    dedupe_key TEXT NOT NULL DEFAULT '',
                    occurred_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    summarized_at TEXT NOT NULL DEFAULT '',
                    retention_class TEXT NOT NULL DEFAULT 'normal',
                    import_batch_id TEXT NOT NULL DEFAULT '',
                    source_sequence INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS summary_failures (
                    session_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL DEFAULT '',
                    start_timeline_id TEXT NOT NULL DEFAULT '',
                    end_timeline_id TEXT NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS chat_import_batches (
                    id TEXT PRIMARY KEY,
                    upload_id TEXT NOT NULL DEFAULT '',
                    source_name TEXT NOT NULL DEFAULT '',
                    source_hash TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'prepared',
                    session_id TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT 'private',
                    platform TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    user_name TEXT NOT NULL DEFAULT '',
                    bot_id TEXT NOT NULL DEFAULT '',
                    bot_name TEXT NOT NULL DEFAULT '',
                    speaker_map TEXT NOT NULL DEFAULT '{}',
                    options TEXT NOT NULL DEFAULT '{}',
                    stats TEXT NOT NULL DEFAULT '{}',
                    checkpoint_segment INTEGER NOT NULL DEFAULT 0,
                    total_segments INTEGER NOT NULL DEFAULT 0,
                    completed_segments INTEGER NOT NULL DEFAULT 0,
                    summary_memory_count INTEGER NOT NULL DEFAULT 0,
                    important_event_count INTEGER NOT NULL DEFAULT 0,
                    relationship_observation_count INTEGER NOT NULL DEFAULT 0,
                    backup_path TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS chat_import_segments (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL DEFAULT '',
                    segment_index INTEGER NOT NULL DEFAULT 0,
                    start_at TEXT NOT NULL DEFAULT '',
                    end_at TEXT NOT NULL DEFAULT '',
                    local_date TEXT NOT NULL DEFAULT '',
                    message_ids TEXT NOT NULL DEFAULT '[]',
                    transcript TEXT NOT NULL DEFAULT '',
                    char_count INTEGER NOT NULL DEFAULT 0,
                    turn_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result TEXT NOT NULL DEFAULT '{}',
                    summary_memory_id TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(batch_id, segment_index)
                );

                CREATE TABLE IF NOT EXISTS relationship_edges (
                    id TEXT PRIMARY KEY,
                    subject_kind TEXT NOT NULL DEFAULT '',
                    subject_id TEXT NOT NULL DEFAULT '',
                    subject_name TEXT NOT NULL DEFAULT '',
                    object_kind TEXT NOT NULL DEFAULT '',
                    object_id TEXT NOT NULL DEFAULT '',
                    object_name TEXT NOT NULL DEFAULT '',
                    relation_type TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    visibility TEXT NOT NULL DEFAULT 'internal',
                    evidence TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    review_status TEXT NOT NULL DEFAULT 'auto',
                    source_memory_id TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(subject_kind, subject_id, object_kind, object_id, relation_type, scope, session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_relationship_edges_subject
                    ON relationship_edges(subject_kind, subject_id, relation_type);
                CREATE INDEX IF NOT EXISTS idx_relationship_edges_object
                    ON relationship_edges(object_kind, object_id, relation_type);

                CREATE TABLE IF NOT EXISTS knowledge_nodes (
                    id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL DEFAULT '',
                    node_key TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(node_type, node_key, scope, session_id)
                );

                CREATE TABLE IF NOT EXISTS knowledge_edges (
                    id TEXT PRIMARY KEY,
                    source_node_id TEXT NOT NULL DEFAULT '',
                    target_node_id TEXT NOT NULL DEFAULT '',
                    relation_type TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    source_memory_id TEXT NOT NULL DEFAULT '',
                    evidence TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    review_status TEXT NOT NULL DEFAULT 'auto',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(source_node_id, target_node_id, relation_type, source_memory_id)
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_lookup
                    ON knowledge_nodes(scope, session_id, node_type, label);
                CREATE INDEX IF NOT EXISTS idx_knowledge_edges_source
                    ON knowledge_edges(source_node_id, relation_type);
                CREATE INDEX IF NOT EXISTS idx_knowledge_edges_target
                    ON knowledge_edges(target_node_id, relation_type);

                CREATE TABLE IF NOT EXISTS cross_window_threads (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'open',
                    from_session TEXT NOT NULL DEFAULT '',
                    to_session TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    visibility TEXT NOT NULL DEFAULT 'shareable',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS review_queue (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(memory_id, reason)
                );

                CREATE TABLE IF NOT EXISTS injection_logs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    query TEXT NOT NULL DEFAULT '',
                    selected_memory_ids TEXT NOT NULL DEFAULT '[]',
                    blocked_reasons TEXT NOT NULL DEFAULT '[]',
                    injection_chars INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS import_batches (
                    id TEXT PRIMARY KEY,
                    source_plugin TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT '',
                    stats TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS memory_acl_rules (
                    id TEXT PRIMARY KEY,
                    owner_scope TEXT NOT NULL DEFAULT '',
                    owner_id TEXT NOT NULL DEFAULT '',
                    reader_scope TEXT NOT NULL DEFAULT '',
                    reader_id TEXT NOT NULL DEFAULT '',
                    effect TEXT NOT NULL DEFAULT 'allow',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(owner_scope, owner_id, reader_scope, reader_id)
                );

                CREATE TABLE IF NOT EXISTS memory_acl_policies (
                    id TEXT PRIMARY KEY,
                    window_scope TEXT NOT NULL DEFAULT '',
                    window_id TEXT NOT NULL DEFAULT '',
                    read_mode TEXT NOT NULL DEFAULT 'whitelist',
                    share_mode TEXT NOT NULL DEFAULT 'whitelist',
                    capture_enabled INTEGER CHECK(capture_enabled IS NULL OR capture_enabled IN (0, 1)),
                    recall_enabled INTEGER CHECK(recall_enabled IS NULL OR recall_enabled IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(window_scope, window_id)
                );

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL DEFAULT '',
                    text_hash TEXT NOT NULL DEFAULT '',
                    dimension INTEGER NOT NULL DEFAULT 0,
                    vector TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(memory_id, provider_id)
                );

                CREATE TABLE IF NOT EXISTS emotion_events (
                    event_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    trace_id TEXT NOT NULL DEFAULT '',
                    producer_plugin TEXT NOT NULL DEFAULT '',
                    origin_kind TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    bot_id TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    actor_ref TEXT NOT NULL DEFAULT '{}',
                    target_ref TEXT NOT NULL DEFAULT '{}',
                    quoted_target_ref TEXT NOT NULL DEFAULT '{}',
                    event_type TEXT NOT NULL DEFAULT 'neutral',
                    intensity REAL NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    valence_hint REAL NOT NULL DEFAULT 0,
                    arousal_hint REAL NOT NULL DEFAULT 0,
                    vulnerability_hint REAL NOT NULL DEFAULT 0,
                    source_rule TEXT NOT NULL DEFAULT '',
                    occurred_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    dedupe_key TEXT NOT NULL DEFAULT '',
                    payload_hash TEXT NOT NULL DEFAULT '',
                    privacy_level TEXT NOT NULL DEFAULT 'redacted',
                    applied_interaction TEXT NOT NULL DEFAULT '',
                    applied_energy_delta REAL NOT NULL DEFAULT 0,
                    correction_of TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'observed',
                    reason_codes TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(event_id, revision)
                );

                CREATE TABLE IF NOT EXISTS emotion_event_deliveries (
                    event_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    consumer_id TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    first_delivered_at TEXT NOT NULL DEFAULT '',
                    last_delivered_at TEXT NOT NULL DEFAULT '',
                    acked_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(event_id, revision, consumer_id),
                    FOREIGN KEY(event_id, revision)
                        REFERENCES emotion_events(event_id, revision)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS portrait_people (
                    person_id TEXT PRIMARY KEY,
                    resolved_identity_key TEXT NOT NULL DEFAULT '',
                    projection_revision INTEGER NOT NULL DEFAULT 0,
                    identity_assurance TEXT NOT NULL DEFAULT '',
                    profile_status TEXT NOT NULL DEFAULT '',
                    capability_summary TEXT NOT NULL DEFAULT '{}',
                    portrait_revision INTEGER NOT NULL DEFAULT 0,
                    last_synced_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS portrait_scope_capabilities (
                    person_id TEXT NOT NULL DEFAULT '',
                    source_scope TEXT NOT NULL DEFAULT '',
                    capability_summary TEXT NOT NULL DEFAULT '{}',
                    projection_revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(person_id, source_scope)
                );

                CREATE TABLE IF NOT EXISTS portrait_evidence (
                    evidence_hash TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL DEFAULT '',
                    origin_identity_key TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    message_id TEXT NOT NULL DEFAULT '',
                    statement_fingerprint TEXT NOT NULL DEFAULT '',
                    context_refs TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS portrait_facts (
                    id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL DEFAULT '',
                    dimension TEXT NOT NULL DEFAULT '',
                    normalized_claim_hash TEXT NOT NULL DEFAULT '',
                    claim_summary TEXT NOT NULL DEFAULT '',
                    portrait_tier TEXT NOT NULL DEFAULT '',
                    producer_kind TEXT NOT NULL DEFAULT '',
                    producer_version TEXT NOT NULL DEFAULT '',
                    derivation_kind TEXT NOT NULL DEFAULT '',
                    epistemic_status TEXT NOT NULL DEFAULT '',
                    source_scope TEXT NOT NULL DEFAULT '',
                    usable_scope TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0,
                    sensitivity TEXT NOT NULL DEFAULT 'high',
                    status TEXT NOT NULL DEFAULT 'active',
                    evidence_hashes TEXT NOT NULL DEFAULT '[]',
                    context_refs TEXT NOT NULL DEFAULT '[]',
                    first_evidence_at TEXT NOT NULL DEFAULT '',
                    last_evidence_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    supersedes_id TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    operation_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(person_id, dimension, normalized_claim_hash, portrait_tier, source_scope)
                );

                CREATE TABLE IF NOT EXISTS portrait_suppressions (
                    suppression_key TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL DEFAULT '',
                    dimension TEXT NOT NULL DEFAULT '',
                    normalized_claim_hash TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    origin_identity_key TEXT NOT NULL DEFAULT '',
                    operation_id TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    revoked_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS portrait_operations (
                    operation_id TEXT PRIMARY KEY,
                    operation_kind TEXT NOT NULL DEFAULT '',
                    payload_hash TEXT NOT NULL DEFAULT '',
                    snapshot TEXT NOT NULL DEFAULT '{}',
                    state TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS profile_repair_operations (
                    operation_id TEXT PRIMARY KEY,
                    rule_version TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT '',
                    backup_path TEXT NOT NULL DEFAULT '',
                    plan_fingerprint TEXT NOT NULL DEFAULT '',
                    snapshot TEXT NOT NULL DEFAULT '{}',
                    result TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS portrait_learning_queue (
                    queue_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL DEFAULT '',
                    fact_id TEXT NOT NULL DEFAULT '',
                    evidence_hash TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(person_id, fact_id, evidence_hash)
                );

                CREATE TABLE IF NOT EXISTS portrait_daily_runs (
                    person_id TEXT NOT NULL DEFAULT '',
                    run_day TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    last_code TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(person_id, run_day)
                );

                """
            )
            self._repair_internal_control_tables_sync()
            self._ensure_memory_columns_sync()
            self._ensure_timeline_columns_sync()
            self._ensure_acl_columns_sync()
            self._ensure_portrait_columns_sync()
            self._ensure_memory_fts_sync()
            self._ensure_knowledge_trgm_sync()
            self._ensure_redaction_tracking_triggers_sync()
            self._ensure_retrieval_revision_sync()
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_fingerprint ON memories(content_fingerprint)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_atom_domain "
                "ON memories(owner_bot_id, platform, scope, validity_status)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_validity_time "
                "ON memories(validity_status, valid_from, valid_to)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_canonical_key "
                "ON memories(canonical_key)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_candidate "
                "ON memories(importance DESC, occurred_at DESC, id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_summary ON timeline(session_id, summarized_at, occurred_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_scope_recent ON timeline(scope, occurred_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_subject_recent "
                "ON timeline(scope, session_id, subject_id, occurred_at DESC, created_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_object_recent "
                "ON timeline(scope, session_id, object_id, occurred_at DESC, created_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_retention ON timeline(occurred_at, created_at) WHERE summarized_at!=''"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_import_batch ON timeline(import_batch_id, source_sequence)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_injection_logs_created ON injection_logs(created_at)"
            )
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_dedupe_key ON timeline(dedupe_key) WHERE dedupe_key!=''"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_summary_failures_updated ON summary_failures(updated_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_import_batches_state ON chat_import_batches(state, updated_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_import_segments_state ON chat_import_segments(batch_id, status, segment_index)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_import_batch ON memories(import_batch_id, memory_type)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_acl_owner ON memory_acl_rules(owner_scope, owner_id, enabled)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_acl_reader ON memory_acl_rules(reader_scope, reader_id, enabled)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_acl_policy_window ON memory_acl_policies(window_scope, window_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_provider ON memory_embeddings(provider_id, updated_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotion_events_trace ON emotion_events(trace_id, revision)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotion_events_session ON emotion_events(bot_id, scope, session_id, occurred_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotion_events_delivery_domain "
                "ON emotion_events(bot_id, scope, platform, occurred_at DESC, event_id DESC, revision DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotion_events_dedupe ON emotion_events(dedupe_key, event_type)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotion_event_deliveries_pending "
                "ON emotion_event_deliveries(consumer_id, acked_at, last_delivered_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_portrait_evidence_person ON portrait_evidence(person_id, created_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_portrait_facts_person ON portrait_facts(person_id, status, sensitivity, updated_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_portrait_scope_capabilities_person "
                "ON portrait_scope_capabilities(person_id, updated_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_portrait_suppressions_person ON portrait_suppressions(person_id, status)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_portrait_learning_queue_person ON portrait_learning_queue(person_id, state, updated_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_profile_domain "
                "ON memories(platform, subject_kind, subject_id, object_kind, "
                "object_id, scope, group_id, visibility, memory_type, lifecycle)"
            )
            # c1: 画像治理/修复按 fact_id 逐条查询，原无索引导致逐 fact 全表扫描
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_portrait_learning_queue_fact "
                "ON portrait_learning_queue(fact_id, state)"
            )
            # c2: 回滚/删除按 source_memory_id 批量 IN 查询，原无索引导致全表扫描
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relationship_edges_source_memory "
                "ON relationship_edges(source_memory_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_edges_source_memory "
                "ON knowledge_edges(source_memory_id)"
            )
            # c3: 仅按 session_id 过滤 emotion 事件时现有索引（前缀 bot_id）无法命中
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotion_events_session "
                "ON emotion_events(session_id, occurred_at DESC)"
            )
            # c4: timeline 仅按 session_id（无 scope）过滤时无索引命中；
            #     memories 时间窗口查询的 created_at/updated_at 无索引
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_session_recent "
                "ON timeline(session_id, occurred_at DESC, created_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at)"
            )
            # c5: emotion 投递查询使用 LOWER(scope) 导致 scope 列索引失效，
            #     用表达式索引精确匹配 LOWER(scope) 谓词
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotion_events_delivery_scope "
                "ON emotion_events(bot_id, LOWER(scope), platform)"
            )
            self._redact_existing_sensitive_rows_sync()
            self._cleanup_placeholder_memory_indexes_sync()
            self._conn.execute(
                """INSERT INTO schema_metadata(key,value,updated_at) VALUES('schema_version',?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (self.SCHEMA_VERSION, utc_now()),
            )
            self._conn.commit()

    def _cleanup_placeholder_memory_indexes_sync(self) -> int:
        """Remove historical placeholder entries from recall-only indexes.

        The memory rows themselves are intentionally retained because the
        Bot Personal bridge reads their structured metadata.  Deleting stale
        FTS/vector entries is sufficient to keep ordinary recall clean and is
        safe to repeat during startup.
        """
        rows = self._conn.execute(
            f"SELECT id FROM memories WHERE NOT ({self._recallable_memory_sql()})"
        ).fetchall()
        memory_ids = [clean_text(row["id"], 120) for row in rows if clean_text(row["id"], 120)]
        if not memory_ids:
            return 0
        deleted = 0
        for index in range(0, len(memory_ids), 500):
            chunk = memory_ids[index : index + 500]
            marks = ",".join("?" for _ in chunk)
            deleted += int(
                self._conn.execute(
                    f"DELETE FROM memory_embeddings WHERE memory_id IN ({marks})",
                    chunk,
                ).rowcount
                or 0
            )
            if self._fts_enabled:
                self._conn.execute(
                    f"DELETE FROM memory_fts WHERE memory_id IN ({marks})",
                    chunk,
                )
        return deleted

    def _backup_before_schema_upgrade_sync(self) -> str:
        """Create a consistent, private rollback copy before mutating an existing schema."""

        tables = {
            clean_text(row["name"], 160)
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if not tables:
            return ""
        schema_columns = self._table_column_names_sync("schema_metadata")
        if schema_columns == {"key", "value", "updated_at"}:
            row = self._conn.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()
            if row is not None and clean_text(row["value"], 80) == self.SCHEMA_VERSION:
                return ""

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = self.db_path.with_name(
            f"{self.db_path.stem}.before-{self.SCHEMA_VERSION}.{timestamp}{self.db_path.suffix or '.db'}"
        )
        with closing(sqlite3.connect(str(backup_path))) as backup_conn:
            self._conn.backup(backup_conn)
        backup_path.chmod(0o600)
        return str(backup_path)

    def _table_column_names_sync(self, table: str) -> set[str]:
        return {
            clean_text(row["name"], 160)
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def _repair_internal_control_tables_sync(self) -> None:
        """Canonicalize disposable control tables left by interrupted/foreign upgrades."""

        schema_columns = self._table_column_names_sync("schema_metadata")
        if schema_columns != {"key", "value", "updated_at"}:
            remembered_version = ""
            if {"key", "value"}.issubset(schema_columns):
                row = self._conn.execute(
                    "SELECT value FROM schema_metadata WHERE key='schema_version'"
                ).fetchone()
                if row is not None:
                    remembered_version = clean_text(row["value"], 80)
            self._conn.execute("DROP TABLE schema_metadata")
            self._conn.execute(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            if remembered_version:
                self._conn.execute(
                    "INSERT INTO schema_metadata(key,value,updated_at) VALUES('schema_version',?,?)",
                    (remembered_version, utc_now()),
                )

        revision_columns = self._table_column_names_sync("retrieval_revision")
        if revision_columns and revision_columns != {"singleton", "revision"}:
            remembered_revision = 0
            if {"singleton", "revision"}.issubset(revision_columns):
                row = self._conn.execute(
                    "SELECT revision FROM retrieval_revision WHERE singleton=1"
                ).fetchone()
                if row is not None:
                    try:
                        remembered_revision = max(0, int(row["revision"] or 0))
                    except (TypeError, ValueError):
                        remembered_revision = 0
            self._conn.execute("DROP TABLE retrieval_revision")
            self._conn.execute(
                """
                CREATE TABLE retrieval_revision (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    revision INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                "INSERT INTO retrieval_revision(singleton,revision) VALUES(1,?)",
                (remembered_revision,),
            )

    def _redact_existing_sensitive_rows_sync(self) -> None:
        """Idempotently scrub legacy rows before recall, embedding, or export."""
        marker = self._conn.execute(
            "SELECT value FROM schema_metadata WHERE key='sensitive_redaction_version'"
        ).fetchone()
        if marker is not None and clean_text(marker["value"], 80) == self.SENSITIVE_REDACTION_VERSION:
            return
        rekeyed = False
        for row in self._conn.execute("SELECT id, content, evidence, metadata FROM memories").fetchall():
            content = redact_sensitive_text(row["content"])
            evidence = redact_sensitive_text(row["evidence"])
            metadata = redact_sensitive_value(json_loads(row["metadata"], {}))
            encoded_metadata = json_dumps(metadata)
            if content != row["content"] or evidence != row["evidence"] or encoded_metadata != row["metadata"]:
                content_changed = content != row["content"]
                self._conn.execute(
                    """UPDATE memories
                       SET content=?, evidence=?, metadata=?,
                           canonical_key=CASE WHEN ? THEN '' ELSE canonical_key END,
                           content_fingerprint=CASE WHEN ? THEN '' ELSE content_fingerprint END
                       WHERE id=?""",
                    (content, evidence, encoded_metadata, content_changed, content_changed, row["id"]),
                )
                if content_changed:
                    self._conn.execute(
                        "DELETE FROM memory_embeddings WHERE memory_id=?",
                        (row["id"],),
                    )
                    refreshed = self._conn.execute(
                        "SELECT * FROM memories WHERE id=?",
                        (row["id"],),
                    ).fetchone()
                    self._upsert_memory_fts_row(refreshed)
                rekeyed = rekeyed or content_changed
        for row in self._conn.execute("SELECT id, content, metadata FROM timeline").fetchall():
            content = redact_sensitive_text(row["content"])
            metadata = redact_sensitive_value(json_loads(row["metadata"], {}))
            encoded_metadata = json_dumps(metadata)
            if content != row["content"] or encoded_metadata != row["metadata"]:
                self._conn.execute(
                    "UPDATE timeline SET content=?, metadata=? WHERE id=?",
                    (content, encoded_metadata, row["id"]),
                )
        self._redact_legacy_auxiliary_tables_sync()
        if rekeyed:
            self._backfill_memory_atom_v2_sync()
        self._conn.execute(
            """INSERT INTO schema_metadata(key,value,updated_at) VALUES('sensitive_redaction_version',?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (self.SENSITIVE_REDACTION_VERSION, utc_now()),
        )

    def _ensure_redaction_tracking_triggers_sync(self) -> None:
        """Invalidate the startup redaction marker when protected text changes."""
        self._conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS trg_redaction_memories_insert
            AFTER INSERT ON memories
            WHEN EXISTS (
                SELECT 1 FROM schema_metadata
                WHERE key='sensitive_redaction_version' AND value <> ''
            )
            BEGIN
                UPDATE schema_metadata SET value='', updated_at=datetime('now')
                WHERE key='sensitive_redaction_version';
            END;
            CREATE TRIGGER IF NOT EXISTS trg_redaction_memories_update
            AFTER UPDATE OF content,evidence,metadata ON memories
            WHEN EXISTS (
                SELECT 1 FROM schema_metadata
                WHERE key='sensitive_redaction_version' AND value <> ''
            )
            BEGIN
                UPDATE schema_metadata SET value='', updated_at=datetime('now')
                WHERE key='sensitive_redaction_version';
            END;
            CREATE TRIGGER IF NOT EXISTS trg_redaction_timeline_insert
            AFTER INSERT ON timeline
            WHEN EXISTS (
                SELECT 1 FROM schema_metadata
                WHERE key='sensitive_redaction_version' AND value <> ''
            )
            BEGIN
                UPDATE schema_metadata SET value='', updated_at=datetime('now')
                WHERE key='sensitive_redaction_version';
            END;
            CREATE TRIGGER IF NOT EXISTS trg_redaction_timeline_update
            AFTER UPDATE OF content,metadata ON timeline
            WHEN EXISTS (
                SELECT 1 FROM schema_metadata
                WHERE key='sensitive_redaction_version' AND value <> ''
            )
            BEGIN
                UPDATE schema_metadata SET value='', updated_at=datetime('now')
                WHERE key='sensitive_redaction_version';
            END;
            """
        )

    def _redact_legacy_auxiliary_tables_sync(self) -> None:
        """Scrub older secondary projections that can surface memory text."""
        secret_node_ids: list[str] = []
        for row in self._conn.execute("SELECT id,label FROM knowledge_nodes").fetchall():
            if redact_sensitive_text(row["label"]) != row["label"]:
                secret_node_ids.append(row["id"])
        if secret_node_ids:
            placeholders = ",".join("?" for _ in secret_node_ids)
            self._conn.execute(
                f"DELETE FROM knowledge_edges WHERE source_node_id IN ({placeholders}) OR target_node_id IN ({placeholders})",
                [*secret_node_ids, *secret_node_ids],
            )
            self._conn.execute(
                f"DELETE FROM knowledge_nodes WHERE id IN ({placeholders})",
                secret_node_ids,
            )

        secret_fact_ids: list[str] = []
        for row in self._conn.execute("SELECT id,claim_summary FROM portrait_facts").fetchall():
            if redact_sensitive_text(row["claim_summary"]) != row["claim_summary"]:
                secret_fact_ids.append(row["id"])
        if secret_fact_ids:
            placeholders = ",".join("?" for _ in secret_fact_ids)
            self._conn.execute(
                f"DELETE FROM portrait_learning_queue WHERE fact_id IN ({placeholders})",
                secret_fact_ids,
            )
            self._conn.execute(
                f"DELETE FROM portrait_facts WHERE id IN ({placeholders})",
                secret_fact_ids,
            )

        table_columns = {
            "identities": ((), ("profile",)),
            "summary_failures": (("last_error",), ("metadata",)),
            "chat_import_batches": (("error",), ("speaker_map", "options", "stats")),
            "chat_import_segments": (("transcript", "error"), ("result",)),
            "relationship_edges": (("evidence",), ("metadata",)),
            "knowledge_nodes": (("label",), ("metadata",)),
            "knowledge_edges": (("evidence",), ("metadata",)),
            "cross_window_threads": (("topic", "content"), ("metadata",)),
            "injection_logs": (("query",), ("blocked_reasons",)),
            "portrait_people": ((), ("capability_summary",)),
            "portrait_facts": (("claim_summary",), ("context_refs",)),
            "portrait_suppressions": (("reason",), ()),
            "portrait_operations": ((), ("snapshot",)),
        }
        for table, (text_columns, json_columns) in table_columns.items():
            columns = [*text_columns, *json_columns]
            if not columns:
                continue
            selected = ",".join(columns)
            rows = self._conn.execute(
                f"SELECT rowid AS _redact_rowid,{selected} FROM {table}"
            ).fetchall()
            for row in rows:
                values: list[str] = []
                changed = False
                for column in text_columns:
                    raw = str(row[column] or "")
                    safe = redact_sensitive_text(raw)
                    values.append(safe)
                    changed = changed or safe != raw
                for column in json_columns:
                    raw = str(row[column] or "")
                    decoded = json_loads(raw, {})
                    safe = json_dumps(redact_sensitive_value(decoded))
                    values.append(safe)
                    changed = changed or safe != raw
                if changed:
                    assignments = ",".join(f"{column}=?" for column in columns)
                    self._conn.execute(
                        f"UPDATE {table} SET {assignments} WHERE rowid=?",
                        [*values, row["_redact_rowid"]],
                    )


    def _ensure_retrieval_revision_sync(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS retrieval_revision (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                revision INTEGER NOT NULL DEFAULT 0
            );
            INSERT OR IGNORE INTO retrieval_revision(singleton, revision) VALUES(1, 0);

            CREATE TRIGGER IF NOT EXISTS trg_memories_retrieval_revision_insert
            AFTER INSERT ON memories
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_memories_retrieval_revision_delete
            AFTER DELETE ON memories
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            DROP TRIGGER IF EXISTS trg_memories_retrieval_revision_update;
            CREATE TRIGGER IF NOT EXISTS trg_memories_retrieval_revision_update
            AFTER UPDATE OF
                memory_type, subject_kind, subject_id, subject_name, subject_role,
                object_kind, object_id, object_name, object_role, scope, session_id,
                platform, message_id, group_id, visibility, sayability, reality_level,
                lifecycle, content, evidence, confidence, importance, review_status,
                tags, metadata, created_at, updated_at, occurred_at, source_plugin,
                import_batch_id, content_fingerprint, merged_count, supersedes_id,
                owner_bot_id, validity_status, valid_from, valid_to, salience,
                durability, sensitivity, canonical_key
            ON memories
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_acl_rules_retrieval_revision_insert
            AFTER INSERT ON memory_acl_rules
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_acl_rules_retrieval_revision_update
            AFTER UPDATE ON memory_acl_rules
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_acl_rules_retrieval_revision_delete
            AFTER DELETE ON memory_acl_rules
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_acl_policies_retrieval_revision_insert
            AFTER INSERT ON memory_acl_policies
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_acl_policies_retrieval_revision_update
            AFTER UPDATE ON memory_acl_policies
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_acl_policies_retrieval_revision_delete
            AFTER DELETE ON memory_acl_policies
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_embeddings_retrieval_revision_insert
            AFTER INSERT ON memory_embeddings
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_embeddings_retrieval_revision_update
            AFTER UPDATE ON memory_embeddings
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_embeddings_retrieval_revision_delete
            AFTER DELETE ON memory_embeddings
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_knowledge_nodes_retrieval_revision_insert
            AFTER INSERT ON knowledge_nodes
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_nodes_retrieval_revision_update
            AFTER UPDATE ON knowledge_nodes
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_nodes_retrieval_revision_delete
            AFTER DELETE ON knowledge_nodes
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_knowledge_edges_retrieval_revision_insert
            AFTER INSERT ON knowledge_edges
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_edges_retrieval_revision_update
            AFTER UPDATE ON knowledge_edges
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_edges_retrieval_revision_delete
            AFTER DELETE ON knowledge_edges
            BEGIN
                UPDATE retrieval_revision SET revision = revision + 1 WHERE singleton = 1;
            END;
            """
        )

    def _ensure_memory_fts_sync(self) -> None:
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(search_text, memory_id UNINDEXED, tokenize='unicode61')
                """
            )
            self._fts_enabled = True
            # Placeholder rows remain available to the dedicated Bot Personal
            # bridge, but are intentionally absent from the recall index.
            memory_count = int(
                self._conn.execute(
                    f"SELECT COUNT(*) FROM memories WHERE {self._recallable_memory_sql()}"
                ).fetchone()[0]
                or 0
            )
            fts_count = int(self._conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] or 0)
            if memory_count != fts_count:
                self._rebuild_memory_fts_sync()
        except sqlite3.Error:
            self._fts_enabled = False

    def _ensure_knowledge_trgm_sync(self) -> None:
        """Maintain a trigram index over knowledge node labels via triggers.

        LIKE '%term%' cannot use a b-tree index, so substring recall over
        ~100k labels needs FTS5 trigram. Triggers keep the index in sync for
        every write path (upsert, cascade delete, clear); a count mismatch at
        startup triggers a full rebuild.
        """
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_label_trgm
                USING fts5(label, node_id UNINDEXED, tokenize='trigram')
                """
            )
            self._conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS trg_knowledge_label_trgm_ai
                AFTER INSERT ON knowledge_nodes
                BEGIN
                    INSERT INTO knowledge_label_trgm(rowid, node_id, label)
                    VALUES(new.rowid, new.id, new.label);
                END;
                CREATE TRIGGER IF NOT EXISTS trg_knowledge_label_trgm_ad
                AFTER DELETE ON knowledge_nodes
                BEGIN
                    DELETE FROM knowledge_label_trgm WHERE rowid=old.rowid;
                END;
                CREATE TRIGGER IF NOT EXISTS trg_knowledge_label_trgm_au
                AFTER UPDATE OF label ON knowledge_nodes
                BEGIN
                    DELETE FROM knowledge_label_trgm WHERE rowid=old.rowid;
                    INSERT INTO knowledge_label_trgm(rowid, node_id, label)
                    VALUES(new.rowid, new.id, new.label);
                END;
                """
            )
            node_count = int(self._conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0] or 0)
            trgm_count = int(self._conn.execute("SELECT COUNT(*) FROM knowledge_label_trgm").fetchone()[0] or 0)
            if node_count != trgm_count:
                self._conn.execute("DELETE FROM knowledge_label_trgm")
                self._conn.execute(
                    """
                    INSERT INTO knowledge_label_trgm(rowid, node_id, label)
                    SELECT rowid, id, label FROM knowledge_nodes
                    """
                )
            self._knowledge_trgm_enabled = True
        except sqlite3.Error:
            self._knowledge_trgm_enabled = False

    def _rebuild_memory_fts_sync(self) -> int:
        if not self._fts_enabled:
            return 0
        self._conn.execute("DELETE FROM memory_fts")
        rows = self._conn.execute(
            f"SELECT * FROM memories WHERE {self._recallable_memory_sql()}"
        ).fetchall()
        count = 0
        for row in rows:
            self._upsert_memory_fts_row(row)
            count += 1
        return count

    async def rebuild_memory_indexes(self) -> dict[str, Any]:
        """Ensure local lexical indexes exist after an external database import."""
        return await asyncio.to_thread(self._rebuild_memory_indexes_sync)

    def _rebuild_memory_indexes_sync(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_memory_fts_sync()
            rebuilt = self._rebuild_memory_fts_sync() if self._fts_enabled else 0
            self._conn.commit()
            return {"fts_enabled": self._fts_enabled, "fts_rebuilt": rebuilt}

    def _upsert_memory_fts_row(self, row: sqlite3.Row | None) -> None:
        if not self._fts_enabled or row is None:
            return
        memory_id = clean_text(row["id"], 120)
        if not memory_id:
            return
        # Do not index storage-only Bot Personal archive references.  This
        # also removes stale entries when an existing row changes source.
        if is_memory_placeholder(MemoryRecord.from_row_light(row)):
            self._conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
            return
        search_text = self._memory_fts_text(row)
        self._conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
        if search_text:
            self._conn.execute(
                "INSERT INTO memory_fts(memory_id, search_text) VALUES(?, ?)",
                (memory_id, search_text),
            )

    def _delete_memory_fts_row(self, memory_id: str) -> None:
        if not self._fts_enabled:
            return
        memory_id = clean_text(memory_id, 120)
        if memory_id:
            self._conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))

    def _memory_fts_text(self, row: sqlite3.Row) -> str:
        if is_memory_placeholder(MemoryRecord.from_row_light(row)):
            return ""
        metadata = json_loads(row["metadata"], {})
        if not isinstance(metadata, dict):
            metadata = {}
        tags = json_loads(row["tags"], [])
        if not isinstance(tags, list):
            tags = []
        metadata_parts: list[str] = []
        for key in (
            "canonical_summary",
            "persona_summary",
            "memory_reason",
            "title",
            "topic",
            "fact_key",
        ):
            value = metadata.get(key)
            if isinstance(value, dict):
                value = json_dumps(value)
            if value:
                metadata_parts.append(clean_text(value, 800))
        for key in ("key_facts", "routine_check_notes", "topics", "participants", "aliases", "query_anchors"):
            value = metadata.get(key)
            if isinstance(value, list):
                metadata_parts.extend(clean_text(item, 160) for item in value if clean_text(item, 160))
        parts = [
            row["memory_type"],
            row["subject_id"],
            row["subject_name"],
            row["object_id"],
            row["object_name"],
            row["session_id"],
            row["group_id"],
            row["content"],
            row["evidence"],
            " ".join(clean_text(tag, 80) for tag in tags if clean_text(tag, 80)),
            " ".join(metadata_parts),
        ]
        text = clean_text(" ".join(part for part in parts if part), 8000)
        bigrams = self._cjk_bigrams(text)
        return clean_text(f"{text} {' '.join(bigrams)}", 12000)

    @staticmethod
    def _cjk_bigrams(text: str) -> list[str]:
        compact = re.sub(r"\s+", "", clean_text(text, 8000))
        chunks = re.findall(r"[\u4e00-\u9fff]{2,}", compact)
        result: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            for index in range(0, len(chunk) - 1):
                gram = chunk[index : index + 2]
                if gram not in seen:
                    seen.add(gram)
                    result.append(gram)
                if len(result) >= 512:
                    return result
        return result

    def _ensure_memory_columns_sync(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        salience_added = "salience" not in existing
        additions = {
            "content_fingerprint": "TEXT NOT NULL DEFAULT ''",
            "merged_count": "INTEGER NOT NULL DEFAULT 1",
            "supersedes_id": "TEXT NOT NULL DEFAULT ''",
            "owner_bot_id": "TEXT NOT NULL DEFAULT ''",
            "validity_status": (
                "TEXT NOT NULL DEFAULT 'active' "
                "CHECK(validity_status IN ('active','superseded','expired','archived','deleted','quarantined'))"
            ),
            "valid_from": "TEXT NOT NULL DEFAULT ''",
            "valid_to": "TEXT NOT NULL DEFAULT ''",
            # SQLite cannot reliably add a NOT NULL column with a fractional
            # default to a populated legacy table.  Use an integer default for
            # the ALTER TABLE path; _backfill_memory_atom_v2_sync restores the
            # legacy metadata/importance-derived value immediately afterwards.
            "salience": "REAL NOT NULL DEFAULT 0 CHECK(salience >= 0 AND salience <= 1)",
            "durability": (
                "TEXT NOT NULL DEFAULT 'normal' "
                "CHECK(durability IN ('ephemeral','short','normal','durable','pinned'))"
            ),
            "sensitivity": (
                "TEXT NOT NULL DEFAULT 'private' "
                "CHECK(sensitivity IN ('public','internal','private','restricted'))"
            ),
            "reinforcement_score": (
                "REAL NOT NULL DEFAULT 0 CHECK(reinforcement_score >= 0 AND reinforcement_score <= 1)"
            ),
            "injection_count": "INTEGER NOT NULL DEFAULT 0 CHECK(injection_count >= 0)",
            "last_injected_at": "TEXT NOT NULL DEFAULT ''",
            "canonical_key": "TEXT NOT NULL DEFAULT ''",
        }
        for name, ddl in additions.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")
        self._backfill_memory_atom_v2_sync(restore_legacy_salience=salience_added)

    def _backfill_memory_atom_v2_sync(self, *, restore_legacy_salience: bool = False) -> int:
        """Populate v2 atom columns without rewriting legacy content or timestamps."""

        rows = self._conn.execute("SELECT * FROM memories").fetchall()
        updated = 0
        columns = (
            "owner_bot_id",
            "validity_status",
            "valid_from",
            "valid_to",
            "salience",
            "durability",
            "sensitivity",
            "reinforcement_score",
            "injection_count",
            "last_injected_at",
            "canonical_key",
            "content_fingerprint",
        )
        for row in rows:
            record = MemoryRecord.from_row(row)
            if restore_legacy_salience and not row["salience"]:
                metadata = json_loads(row["metadata"], {})
                if isinstance(metadata, dict):
                    # The migration default is deliberately zero for SQLite
                    # compatibility; recover the legacy semantic default or
                    # explicit metadata value before writing the atom fields.
                    record.salience = metadata.get("salience", record.importance)
            values = record.to_db()
            current = tuple(row[name] for name in columns)
            desired = tuple(values[name] for name in columns)
            if current == desired:
                continue
            self._conn.execute(
                """
                UPDATE memories
                SET owner_bot_id=?, validity_status=?, valid_from=?, valid_to=?,
                    salience=?, durability=?, sensitivity=?, reinforcement_score=?,
                    injection_count=?, last_injected_at=?, canonical_key=?,
                    content_fingerprint=?
                WHERE id=?
                """,
                [*desired, record.id],
            )
            updated += 1
        return updated

    def _ensure_timeline_columns_sync(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(timeline)").fetchall()
        }
        additions = {
            "summarized_at": "TEXT NOT NULL DEFAULT ''",
            "message_id": "TEXT NOT NULL DEFAULT ''",
            "dedupe_key": "TEXT NOT NULL DEFAULT ''",
            "retention_class": "TEXT NOT NULL DEFAULT 'normal'",
            "import_batch_id": "TEXT NOT NULL DEFAULT ''",
            "source_sequence": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, ddl in additions.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE timeline ADD COLUMN {name} {ddl}")

    def _ensure_acl_columns_sync(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(memory_acl_rules)").fetchall()
        }
        if "effect" not in existing:
            self._conn.execute("ALTER TABLE memory_acl_rules ADD COLUMN effect TEXT NOT NULL DEFAULT 'allow'")
        policy_columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(memory_acl_policies)").fetchall()
        }
        if "capture_enabled" not in policy_columns:
            self._conn.execute(
                "ALTER TABLE memory_acl_policies ADD COLUMN capture_enabled INTEGER"
            )
        if "recall_enabled" not in policy_columns:
            self._conn.execute(
                "ALTER TABLE memory_acl_policies ADD COLUMN recall_enabled INTEGER"
            )

    def _ensure_portrait_columns_sync(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(portrait_evidence)").fetchall()
        }
        if "statement_fingerprint" not in existing:
            self._conn.execute("ALTER TABLE portrait_evidence ADD COLUMN statement_fingerprint TEXT NOT NULL DEFAULT ''")

    async def upsert_portrait_person_projection(
        self,
        person_ref: dict[str, Any],
        capability_summary: dict[str, Any],
        *,
        source_scope: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._upsert_portrait_person_projection_sync,
            deepcopy(person_ref),
            deepcopy(capability_summary),
            source_scope,
        )

    def _upsert_portrait_person_projection_sync(
        self,
        person_ref: dict[str, Any],
        capability_summary: dict[str, Any],
        source_scope: str,
    ) -> dict[str, Any]:
        person_id = clean_text(person_ref.get("person_id"), 80)
        identity_key = clean_text(person_ref.get("resolved_identity_key"), 96)
        revision = int(person_ref.get("projection_revision") or 0)
        assurance = clean_text(person_ref.get("identity_assurance"), 40)
        status = clean_text(person_ref.get("profile_status"), 40)
        source_scope = clean_text(source_scope, 80)
        if (
            not person_id
            or not identity_key
            or revision < 1
            or assurance not in {"unverified", "observed", "verified", "explicit_linked"}
            or status not in {"active", "suspended", "quarantined", "deleted"}
        ):
            return {"ok": False, "code": "bridge_person_mismatch", "state": "invalid"}
        now = utc_now()
        with self._lock:
            previous = self._conn.execute(
                "SELECT * FROM portrait_people WHERE person_id=?", (person_id,)
            ).fetchone()
            if previous is not None:
                old_revision = int(previous["projection_revision"] or 0)
                if old_revision > revision:
                    return {"ok": False, "code": "bridge_stale_revision", "state": "stale", "projection_revision": old_revision}
                if old_revision == revision and previous["resolved_identity_key"] != identity_key:
                    return {"ok": False, "code": "bridge_person_mismatch", "state": "invalid"}
            portrait_revision = int(previous["portrait_revision"] or 0) if previous is not None else 0
            durable_capability_summary = capability_summary
            if previous is not None and source_scope and not (
                source_scope == "private" or source_scope.startswith("private@")
            ):
                durable_capability_summary = json_loads(previous["capability_summary"], {})
            self._conn.execute(
                """
                INSERT INTO portrait_people(
                    person_id, resolved_identity_key, projection_revision, identity_assurance,
                    profile_status, capability_summary, portrait_revision, last_synced_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(person_id) DO UPDATE SET
                    resolved_identity_key=excluded.resolved_identity_key,
                    projection_revision=excluded.projection_revision,
                    identity_assurance=excluded.identity_assurance,
                    profile_status=excluded.profile_status,
                    capability_summary=excluded.capability_summary,
                    last_synced_at=excluded.last_synced_at,
                    updated_at=excluded.updated_at
                """,
                (
                    person_id,
                    identity_key,
                    revision,
                    clean_text(person_ref.get("identity_assurance"), 40),
                    clean_text(person_ref.get("profile_status"), 40),
                    json_dumps(durable_capability_summary),
                    portrait_revision,
                    now,
                    now,
                ),
            )
            if source_scope:
                self._conn.execute(
                    """
                    INSERT INTO portrait_scope_capabilities(
                        person_id, source_scope, capability_summary, projection_revision, updated_at
                    ) VALUES(?,?,?,?,?)
                    ON CONFLICT(person_id, source_scope) DO UPDATE SET
                        capability_summary=excluded.capability_summary,
                        projection_revision=excluded.projection_revision,
                        updated_at=excluded.updated_at
                    """,
                    (person_id, source_scope, json_dumps(capability_summary), revision, now),
                )
            self._conn.commit()
        return {"ok": True, "code": "profile_exact", "state": "ready", "portrait_revision": portrait_revision}

    async def portrait_projection_decision(self, person_ref: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._portrait_projection_decision_sync, deepcopy(person_ref))

    def _portrait_projection_decision_sync(self, person_ref: dict[str, Any]) -> dict[str, Any]:
        person_id = clean_text(person_ref.get("person_id"), 80)
        identity_key = clean_text(person_ref.get("resolved_identity_key"), 96)
        revision = int(person_ref.get("projection_revision") or 0)
        assurance = clean_text(person_ref.get("identity_assurance"), 40)
        if not person_id or not identity_key or revision < 1 or assurance not in {"observed", "verified", "explicit_linked"}:
            return {"ok": False, "code": "bridge_person_mismatch"}
        with self._lock:
            row = self._conn.execute(
                "SELECT resolved_identity_key, projection_revision, identity_assurance, profile_status FROM portrait_people WHERE person_id=?",
                (person_id,),
            ).fetchone()
        if row is None:
            return {"ok": False, "code": "bridge_unavailable"}
        if clean_text(row["resolved_identity_key"], 96) != identity_key:
            return {"ok": False, "code": "bridge_person_mismatch"}
        if int(row["projection_revision"] or 0) != revision:
            return {"ok": False, "code": "bridge_stale_revision"}
        if clean_text(row["identity_assurance"], 40) not in {"observed", "verified", "explicit_linked"}:
            return {"ok": False, "code": "bridge_person_mismatch"}
        if clean_text(row["profile_status"], 40) != "active":
            return {"ok": False, "code": "bridge_person_mismatch"}
        return {"ok": True, "code": "profile_exact"}

    async def add_portrait_evidence(self, evidence: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._add_portrait_evidence_sync, deepcopy(evidence))

    def _add_portrait_evidence_sync(self, evidence: dict[str, Any]) -> dict[str, Any]:
        person_id = clean_text(evidence.get("person_id"), 80)
        evidence_key = clean_text(evidence.get("evidence_hash"), 80)
        if not person_id or not re.fullmatch(r"[0-9a-f]{64}", evidence_key):
            return {"ok": False, "code": "portrait_evidence_invalid", "created": False}
        statement_key = clean_text(evidence.get("statement_fingerprint"), 80)
        if not re.fullmatch(r"[0-9a-f]{64}", statement_key):
            statement_key = evidence_key
        context_refs = evidence.get("context_refs") if isinstance(evidence.get("context_refs"), list) else []
        now = utc_now()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO portrait_evidence(
                    evidence_hash, person_id, origin_identity_key, scope, session_id, message_id, statement_fingerprint, context_refs, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    evidence_key,
                    person_id,
                    clean_text(evidence.get("origin_identity_key"), 96),
                    clean_text(evidence.get("scope"), 80),
                    clean_text(evidence.get("session_id"), 200),
                    clean_text(evidence.get("message_id"), 120),
                    statement_key,
                    json_dumps([clean_text(item, 160) for item in context_refs if clean_text(item, 160)][:8]),
                    now,
                ),
            )
            self._conn.commit()
        return {"ok": True, "code": "portrait_evidence_recorded", "created": bool(cur.rowcount)}

    def _portrait_suppressed_sync(self, person_id: str, dimension: str, claim_hash: str, scope: str) -> bool:
        now = utc_now()
        row = self._conn.execute(
            """
            SELECT 1 FROM portrait_suppressions
            WHERE person_id=? AND dimension=? AND normalized_claim_hash=?
              AND status IN ('active', 'reconfirmation_pending')
              AND (scope='' OR scope=?)
              AND (expires_at='' OR expires_at>?)
            LIMIT 1
            """,
            (person_id, dimension, claim_hash, scope, now),
        ).fetchone()
        return row is not None

    @staticmethod
    def _portrait_timestamp_is_fresh(value: Any, freshness_days: int) -> bool:
        """Treat malformed or stale inferred timestamps as unusable."""
        text = clean_text(value, 80)
        if not text:
            return False
        try:
            observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            return False
        age = datetime.now(timezone.utc) - observed.astimezone(timezone.utc)
        return age.total_seconds() <= max(1, freshness_days) * 86400

    @staticmethod
    def _portrait_scope_allows_row(
        row: sqlite3.Row,
        requested_scope: str,
        legacy_scope: str = "",
    ) -> bool:
        usable_scope = clean_text(row["usable_scope"], 80)
        source_scope = clean_text(row["source_scope"], 80)
        if usable_scope == "self_low_global":
            source_persona = portrait_scope_persona(source_scope)
            requested_persona = portrait_scope_persona(requested_scope)
            return not source_persona or (
                bool(requested_persona) and source_persona == requested_persona
            )
        return usable_scope == "source_only" and bool(requested_scope) and source_scope in {
            requested_scope,
            legacy_scope,
        }

    def _portrait_scope_capability_sync(
        self,
        person_id: str,
        source_scope: str,
        *,
        legacy_scope: str = "",
    ) -> dict[str, Any]:
        source_scope = clean_text(source_scope, 80)
        row = self._conn.execute(
            "SELECT capability_summary FROM portrait_scope_capabilities WHERE person_id=? AND source_scope=?",
            (person_id, source_scope),
        ).fetchone()
        if row is not None:
            value = json_loads(row["capability_summary"], {})
            return value if isinstance(value, dict) else {}
        if (
            source_scope == "private"
            or source_scope.startswith("group:")
        ):
            person = self._conn.execute(
                "SELECT capability_summary FROM portrait_people WHERE person_id=?",
                (person_id,),
            ).fetchone()
            value = json_loads(person["capability_summary"], {}) if person is not None else {}
            return value if isinstance(value, dict) else {}
        return {}

    def _bump_portrait_revision_sync(self, person_id: str) -> int:
        self._conn.execute(
            "UPDATE portrait_people SET portrait_revision=portrait_revision+1, updated_at=? WHERE person_id=?",
            (utc_now(), person_id),
        )
        row = self._conn.execute("SELECT portrait_revision FROM portrait_people WHERE person_id=?", (person_id,)).fetchone()
        return int(row["portrait_revision"] or 0) if row is not None else 0

    async def upsert_portrait_fact(self, fact: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._upsert_portrait_fact_sync, deepcopy(fact))

    def _upsert_portrait_fact_sync(self, fact: dict[str, Any]) -> dict[str, Any]:
        fact = redact_sensitive_value(fact)
        person_id = clean_text(fact.get("person_id"), 80)
        dimension = clean_text(fact.get("dimension"), 80)
        claim_hash = clean_text(fact.get("normalized_claim_hash"), 80)
        tier = clean_text(fact.get("portrait_tier"), 24)
        source_scope = clean_text(fact.get("source_scope"), 80)
        if not person_id or not dimension or not re.fullmatch(r"[0-9a-f]{64}", claim_hash) or tier not in {"base", "intelligent"}:
            return {"ok": False, "code": "portrait_fact_invalid", "created": False}
        if not source_scope:
            source_scope = "private"
        now = utc_now()
        evidence_hashes = [
            clean_text(item, 80) for item in (fact.get("evidence_hashes") or [])
            if re.fullmatch(r"[0-9a-f]{64}", clean_text(item, 80))
        ][:16]
        status = clean_text(fact.get("status"), 40) or "active"
        cardinality = clean_text(fact.get("profile_cardinality"), 20).lower()
        single_value = (
            cardinality == "single"
            or dimension in self.PROFILE_SINGLE_VALUE_DIMENSIONS
        )
        with self._lock:
            with self._transaction_sync():
                if self._portrait_suppressed_sync(person_id, dimension, claim_hash, source_scope):
                    return {"ok": False, "code": "portrait_suppressed", "created": False}
                previous = self._conn.execute(
                    """
                    SELECT * FROM portrait_facts WHERE person_id=? AND dimension=?
                      AND normalized_claim_hash=? AND portrait_tier=? AND source_scope=?
                    """,
                    (person_id, dimension, claim_hash, tier, source_scope),
                ).fetchone()
                previous_hashes = json_loads(previous["evidence_hashes"], []) if previous is not None else []
                merged_hashes = list(dict.fromkeys([
                    clean_text(item, 80) for item in previous_hashes + evidence_hashes if clean_text(item, 80)
                ]))[:16]
                fact_id = clean_text(previous["id"], 120) if previous is not None else f"portrait_{stable_fingerprint(person_id, dimension, claim_hash, tier, source_scope)[:24]}"
                revision = int(previous["revision"] or 0) + 1 if previous is not None else 1
                first_at = clean_text(previous["first_evidence_at"], 80) if previous is not None else now
                sensitivity = clean_text(fact.get("sensitivity"), 24)
                if sensitivity not in {"low", "sensitive", "high"}:
                    sensitivity = "high"
                usable_scope = clean_text(fact.get("usable_scope"), 80)
                if usable_scope == "self_low_global" and cross_scene_whitelisted_fact(
                    dimension=dimension,
                    claim_summary=fact.get("claim_summary"),
                    sensitivity=sensitivity,
                    source_scope=source_scope,
                ):
                    usable_scope = "self_low_global"
                else:
                    usable_scope = "source_only"
                self._conn.execute(
                    """
                    INSERT INTO portrait_facts(
                        id, person_id, dimension, normalized_claim_hash, claim_summary, portrait_tier,
                        producer_kind, producer_version, derivation_kind, epistemic_status, source_scope,
                        usable_scope, confidence, sensitivity, status, evidence_hashes, context_refs,
                        first_evidence_at, last_evidence_at, expires_at, supersedes_id, revision,
                        operation_id, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(person_id, dimension, normalized_claim_hash, portrait_tier, source_scope) DO UPDATE SET
                        claim_summary=excluded.claim_summary,
                        producer_kind=excluded.producer_kind,
                        producer_version=excluded.producer_version,
                        derivation_kind=excluded.derivation_kind,
                        epistemic_status=excluded.epistemic_status,
                        usable_scope=excluded.usable_scope,
                        confidence=max(portrait_facts.confidence, excluded.confidence),
                        sensitivity=excluded.sensitivity,
                        status=excluded.status,
                        evidence_hashes=excluded.evidence_hashes,
                        context_refs=excluded.context_refs,
                        last_evidence_at=excluded.last_evidence_at,
                        expires_at=excluded.expires_at,
                        supersedes_id=excluded.supersedes_id,
                        revision=excluded.revision,
                        operation_id=excluded.operation_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        fact_id, person_id, dimension, claim_hash, clean_text(fact.get("claim_summary"), 180), tier,
                        clean_text(fact.get("producer_kind"), 80), clean_text(fact.get("producer_version"), 80),
                        clean_text(fact.get("derivation_kind"), 80), clean_text(fact.get("epistemic_status"), 80),
                        source_scope, usable_scope, max(0.0, min(1.0, float(fact.get("confidence") or 0.0))),
                        sensitivity, status, json_dumps(merged_hashes),
                        json_dumps([clean_text(item, 160) for item in (fact.get("context_refs") or []) if clean_text(item, 160)][:8]),
                        first_at, now, clean_text(fact.get("expires_at"), 80), clean_text(fact.get("supersedes_id"), 120),
                        revision, clean_text(fact.get("operation_id"), 120),
                        clean_text(previous["created_at"], 80) if previous is not None else now, now,
                    ),
                )
                superseded_ids: list[str] = []
                if status == "active" and single_value:
                    superseded_rows = self._conn.execute(
                        """
                        SELECT id FROM portrait_facts
                        WHERE person_id=? AND dimension=?
                          AND source_scope=? AND status='active' AND id!=?
                        """,
                        (person_id, dimension, source_scope, fact_id),
                    ).fetchall()
                    superseded_ids = [clean_text(row["id"], 120) for row in superseded_rows]
                    if superseded_ids:
                        placeholders = ",".join("?" for _ in superseded_ids)
                        self._conn.execute(
                            f"""
                            UPDATE portrait_facts
                            SET status='superseded', supersedes_id=?, revision=revision+1,
                                operation_id=?, updated_at=?
                            WHERE id IN ({placeholders})
                            """,
                            [fact_id, clean_text(fact.get("operation_id"), 120), now, *superseded_ids],
                        )
                        self._conn.execute(
                            f"""
                            UPDATE portrait_learning_queue
                            SET state='superseded', updated_at=?
                            WHERE fact_id IN ({placeholders}) AND state='pending'
                            """,
                            [now, *superseded_ids],
                        )
                portrait_revision = self._bump_portrait_revision_sync(person_id)
        return {
            "ok": True,
            "code": "portrait_fact_upserted",
            "created": previous is None,
            "fact_id": fact_id,
            "portrait_revision": portrait_revision,
            "superseded": len(superseded_ids),
        }

    async def list_portrait_evidence(self, person_id: str, *, limit: int = 64) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_portrait_evidence_sync, person_id, limit)

    def _list_portrait_evidence_sync(self, person_id: str, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM portrait_evidence WHERE person_id=? ORDER BY created_at DESC LIMIT ?",
                (clean_text(person_id, 80), max(1, min(512, int(limit)))),
            ).fetchall()
        return [
            {
                "evidence_hash": row["evidence_hash"], "scope": row["scope"], "session_id": row["session_id"],
                "message_id": row["message_id"], "statement_fingerprint": row["statement_fingerprint"],
                "context_refs": json_loads(row["context_refs"], []), "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def enqueue_portrait_learning(self, *, person_id: str, fact_id: str, evidence_hash: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._enqueue_portrait_learning_sync, person_id, fact_id, evidence_hash)

    async def list_pending_portrait_people(self, *, limit: int = 500) -> list[str]:
        return await asyncio.to_thread(self._list_pending_portrait_people_sync, limit)

    def _list_pending_portrait_people_sync(self, limit: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT DISTINCT q.person_id
                FROM portrait_learning_queue q
                JOIN portrait_people p ON p.person_id=q.person_id
                WHERE q.state='pending' AND p.profile_status='active'
                ORDER BY q.updated_at ASC
                LIMIT ?
                """,
                (max(1, min(2000, int(limit))),),
            ).fetchall()
        return [clean_text(row["person_id"], 80) for row in rows if clean_text(row["person_id"], 80)]

    def _enqueue_portrait_learning_sync(self, person_id: str, fact_id: str, evidence_hash: str) -> dict[str, Any]:
        person_id = clean_text(person_id, 80)
        fact_id = clean_text(fact_id, 120)
        evidence_hash = clean_text(evidence_hash, 80)
        if not person_id or not fact_id or not re.fullmatch(r"[0-9a-f]{64}", evidence_hash):
            return {"ok": False, "code": "portrait_queue_invalid"}
        queue_id = f"portrait_queue_{stable_fingerprint(person_id, fact_id, evidence_hash)[:24]}"
        now = utc_now()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO portrait_learning_queue(queue_id, person_id, fact_id, evidence_hash, state, created_at, updated_at)
                VALUES(?,?,?,?, 'pending', ?, ?)
                """,
                (queue_id, person_id, fact_id, evidence_hash, now, now),
            )
            self._conn.commit()
        return {"ok": True, "code": "portrait_queued", "created": bool(cur.rowcount), "queue_id": queue_id}

    async def run_portrait_daily_batch(
        self,
        *,
        person_id: str,
        run_day: str,
        min_independent_evidence: int = 3,
        success_limit: int = 1,
        attempt_limit: int = 2,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._run_portrait_daily_batch_sync,
            person_id,
            run_day,
            min_independent_evidence,
            success_limit,
            attempt_limit,
        )

    def _portrait_distinct_statement_count_sync(self, evidence_hashes: list[Any]) -> int:
        hashes = list(dict.fromkeys(
            clean_text(item, 80)
            for item in evidence_hashes
            if re.fullmatch(r"[0-9a-f]{64}", clean_text(item, 80))
        ))[:16]
        if not hashes:
            return 0
        placeholders = ",".join("?" for _ in hashes)
        rows = self._conn.execute(
            f"SELECT evidence_hash, statement_fingerprint FROM portrait_evidence WHERE evidence_hash IN ({placeholders})",
            hashes,
        ).fetchall()
        fingerprints = {
            clean_text(row["statement_fingerprint"], 80) or clean_text(row["evidence_hash"], 80)
            for row in rows
            if clean_text(row["statement_fingerprint"], 80) or clean_text(row["evidence_hash"], 80)
        }
        return len(fingerprints)

    def _run_portrait_daily_batch_sync(
        self,
        person_id: str,
        run_day: str,
        min_independent_evidence: int,
        success_limit: int,
        attempt_limit: int,
    ) -> dict[str, Any]:
        person_id = clean_text(person_id, 80)
        run_day = clean_text(run_day, 16)
        if not person_id or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", run_day):
            return {"ok": False, "code": "invalid_request"}
        min_independent_evidence = max(1, min(16, int(min_independent_evidence)))
        success_limit = max(1, min(4, int(success_limit)))
        attempt_limit = max(success_limit, min(8, int(attempt_limit)))
        now = utc_now()
        with self._lock:
            person = self._conn.execute("SELECT * FROM portrait_people WHERE person_id=?", (person_id,)).fetchone()
            if person is None:
                return {"ok": False, "code": "bridge_unavailable"}
            run = self._conn.execute(
                "SELECT * FROM portrait_daily_runs WHERE person_id=? AND run_day=?", (person_id, run_day)
            ).fetchone()
            attempts = int(run["attempts"] or 0) if run is not None else 0
            successes = int(run["successes"] or 0) if run is not None else 0
            if successes >= success_limit:
                return {"ok": False, "code": "portrait_daily_limit", "attempts": attempts, "successes": successes}
            if attempts >= attempt_limit:
                return {"ok": False, "code": "portrait_daily_limit", "attempts": attempts, "successes": successes}
            pending_scopes = self._conn.execute(
                """
                SELECT DISTINCT f.source_scope
                FROM portrait_learning_queue q
                JOIN portrait_facts f ON f.id=q.fact_id
                WHERE q.person_id=? AND q.state='pending' AND f.status='active'
                """,
                (person_id,),
            ).fetchall()
            if not any(
                bool(
                    self._portrait_scope_capability_sync(
                        person_id,
                        clean_text(row["source_scope"], 80),
                        legacy_scope=(
                            "private"
                            if clean_text(row["source_scope"], 80) == "private"
                            else ""
                        ),
                    ).get("portrait_learning_enabled")
                )
                for row in pending_scopes
            ):
                return {"ok": False, "code": "portrait_learning_disabled"}
            attempts += 1
            self._conn.execute(
                """
                INSERT INTO portrait_daily_runs(person_id, run_day, attempts, successes, last_code, updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(person_id, run_day) DO UPDATE SET attempts=excluded.attempts, updated_at=excluded.updated_at
                """,
                (person_id, run_day, attempts, successes, "portrait_insufficient_evidence", now),
            )
            rows = self._conn.execute(
                """
                SELECT q.queue_id, q.fact_id, f.* FROM portrait_learning_queue q
                JOIN portrait_facts f ON f.id=q.fact_id
                WHERE q.person_id=? AND q.state='pending' AND f.status='active' AND f.portrait_tier='base'
                ORDER BY q.created_at ASC
                """,
                (person_id,),
            ).fetchall()
            created = 0
            for row in rows:
                row_scope = clean_text(row["source_scope"], 80)
                row_capabilities = self._portrait_scope_capability_sync(
                    person_id,
                    row_scope,
                    legacy_scope="private" if row_scope == "private" else "",
                )
                if not bool(row_capabilities.get("portrait_learning_enabled")):
                    continue
                evidence_hashes = json_loads(row["evidence_hashes"], [])
                if self._portrait_distinct_statement_count_sync(evidence_hashes) < min_independent_evidence:
                    continue
                if self._portrait_suppressed_sync(person_id, row["dimension"], row["normalized_claim_hash"], row["source_scope"]):
                    self._conn.execute(
                        "UPDATE portrait_learning_queue SET state='suppressed', updated_at=? "
                        "WHERE person_id=? AND fact_id=? AND state='pending'",
                        (now, person_id, row["fact_id"]),
                    )
                    continue
                inferred = {
                    "person_id": person_id,
                    "dimension": row["dimension"],
                    "normalized_claim_hash": row["normalized_claim_hash"],
                    "claim_summary": clean_text(f"可能{row['claim_summary']}", 180),
                    "portrait_tier": "intelligent",
                    "producer_kind": "daily_evidence_batch",
                    "producer_version": "req036.batch.v1",
                    "derivation_kind": "independent_evidence_aggregate",
                    "epistemic_status": "inferred",
                    "source_scope": row["source_scope"],
                    "usable_scope": (
                        "self_low_global"
                        if portrait_scope_kind(row["source_scope"]) == "private"
                        else "source_only"
                    ),
                    "confidence": min(0.95, max(0.75, float(row["confidence"] or 0.0))),
                    "sensitivity": row["sensitivity"],
                    "evidence_hashes": evidence_hashes,
                    "context_refs": json_loads(row["context_refs"], []),
                    "operation_id": f"portrait.daily:{person_id[-12:]}:{run_day}",
                }
                result = self._upsert_portrait_fact_sync(inferred)
                if result.get("ok"):
                    self._conn.execute(
                        "UPDATE portrait_learning_queue SET state='processed', updated_at=? "
                        "WHERE person_id=? AND fact_id=? AND state='pending'",
                        (now, person_id, row["fact_id"]),
                    )
                    created += 1
                    break
            successes += 1 if created else 0
            code = "portrait_fact_upserted" if created else "portrait_insufficient_evidence"
            self._conn.execute(
                "UPDATE portrait_daily_runs SET successes=?, last_code=?, updated_at=? WHERE person_id=? AND run_day=?",
                (successes, code, now, person_id, run_day),
            )
            self._conn.commit()
        return {"ok": bool(created), "code": code, "attempts": attempts, "successes": successes, "created": created}

    async def portrait_summary(
        self,
        person_id: str,
        *,
        scope: str = "",
        legacy_scope: str = "",
        limit: int = 8,
        low_only: bool = True,
        usage_min_confidence: float = 0.75,
        inferred_freshness_days: int = 90,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._portrait_summary_sync,
            person_id,
            scope,
            legacy_scope,
            limit,
            low_only,
            usage_min_confidence,
            inferred_freshness_days,
        )

    def _portrait_summary_sync(
        self,
        person_id: str,
        scope: str,
        legacy_scope: str,
        limit: int,
        low_only: bool,
        usage_min_confidence: float,
        inferred_freshness_days: int,
    ) -> dict[str, Any]:
        person_id = clean_text(person_id, 80)
        scope = clean_text(scope, 80)
        legacy_scope = clean_text(legacy_scope, 80)
        confidence_floor = max(0.0, min(1.0, float(usage_min_confidence or 0.75)))
        freshness_days = max(1, min(3650, int(inferred_freshness_days or 90)))
        with self._lock:
            person = self._conn.execute("SELECT * FROM portrait_people WHERE person_id=?", (person_id,)).fetchone()
            if person is None:
                return {"ok": False, "code": "bridge_unavailable", "items": [], "portrait_revision": 0}
            if clean_text(person["profile_status"], 40) != "active" or clean_text(person["identity_assurance"], 40) not in {
                "observed", "verified", "explicit_linked"
            }:
                return {
                    "ok": False,
                    "code": "bridge_person_mismatch",
                    "items": [],
                    "portrait_revision": int(person["portrait_revision"] or 0),
                }
            capabilities = self._portrait_scope_capability_sync(
                person_id, scope, legacy_scope=legacy_scope
            )
            if not bool(capabilities.get("portrait_usage_enabled")):
                return {"ok": False, "code": "portrait_usage_disabled", "items": [], "portrait_revision": int(person["portrait_revision"] or 0)}
            query = (
                "SELECT * FROM portrait_facts "
                "WHERE person_id=? AND status='active' "
                "AND producer_version!='req036.rule.v1'"
            )
            params: list[Any] = [person_id]
            if low_only:
                query += " AND sensitivity='low'"
            # Read a bounded superset before filtering scope, suppression,
            # confidence and freshness.  The bridge never sees rejected rows.
            query += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
            params.append(max(16, min(128, int(limit) * 8)))
            rows = self._conn.execute(query, params).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                if not self._portrait_scope_allows_row(row, scope, legacy_scope):
                    continue
                if self._portrait_suppressed_sync(person_id, row["dimension"], row["normalized_claim_hash"], row["source_scope"]):
                    continue
                confidence = float(row["confidence"] or 0)
                if confidence < confidence_floor:
                    continue
                if row["portrait_tier"] == "intelligent" and not self._portrait_timestamp_is_fresh(row["updated_at"], freshness_days):
                    continue
                items.append(
                    {
                        "dimension": row["dimension"],
                        "summary": row["claim_summary"],
                        "portrait_tier": row["portrait_tier"],
                        "epistemic_status": row["epistemic_status"],
                        "confidence": confidence,
                        "sensitivity": row["sensitivity"],
                        "usable_scope": row["usable_scope"],
                        "updated_at": row["updated_at"],
                    }
                )
                if len(items) >= max(1, min(32, int(limit))):
                    break
        return {
            "ok": True,
            "code": "profile_exact",
            "items": items,
            "portrait_revision": int(person["portrait_revision"] or 0),
            "last_synced_at": clean_text(person["last_synced_at"], 80),
        }

    async def upsert_portrait_suppression(self, marker: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._upsert_portrait_suppression_sync, deepcopy(marker))

    def _upsert_portrait_suppression_sync(self, marker: dict[str, Any]) -> dict[str, Any]:
        key = clean_text(marker.get("suppression_key"), 80)
        person_id = clean_text(marker.get("person_id"), 80)
        status = clean_text(marker.get("status"), 40) or "active"
        operation_id = clean_text(marker.get("operation_id"), 120)
        if not key or not person_id or not operation_id or status not in {"active", "reconfirmation_pending", "revoked", "superseded", "expired"}:
            return {"ok": False, "code": "suppression_invalid"}
        now = utc_now()
        with self._lock:
            previous = self._conn.execute("SELECT * FROM portrait_suppressions WHERE suppression_key=?", (key,)).fetchone()
            if previous is not None and clean_text(previous["operation_id"], 120) == operation_id:
                return {"ok": True, "code": "suppression_idempotent_replay", "revision": int(previous["revision"] or 1)}
            revision = int(previous["revision"] or 0) + 1 if previous is not None else 1
            self._conn.execute(
                """
                INSERT INTO portrait_suppressions(
                    suppression_key, person_id, dimension, normalized_claim_hash, scope, reason, actor, status,
                    origin_identity_key, operation_id, revision, created_at, updated_at, expires_at, revoked_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(suppression_key) DO UPDATE SET
                    reason=excluded.reason, actor=excluded.actor, status=excluded.status,
                    operation_id=excluded.operation_id, revision=excluded.revision, updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at, revoked_at=excluded.revoked_at
                """,
                (
                    key, person_id, clean_text(marker.get("dimension"), 80), clean_text(marker.get("normalized_claim_hash"), 80),
                    clean_text(marker.get("scope"), 80), clean_text(marker.get("reason"), 80), clean_text(marker.get("actor"), 80), status,
                    clean_text(marker.get("origin_identity_key"), 96), operation_id, revision,
                    now if previous is None else clean_text(marker.get("created_at"), 80) or now, now,
                    clean_text(marker.get("expires_at"), 80), clean_text(marker.get("revoked_at"), 80),
                ),
            )
            self._bump_portrait_revision_sync(person_id)
            self._conn.commit()
        return {"ok": True, "code": "suppression_upserted", "revision": revision}

    async def list_portrait_people(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_portrait_people_sync, limit)

    async def portrait_status(self, person_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._portrait_status_sync, person_id)

    def _portrait_status_sync(self, person_id: str) -> dict[str, Any]:
        person_id = clean_text(person_id, 80)
        with self._lock:
            row = self._conn.execute(
                "SELECT portrait_revision, last_synced_at, profile_status FROM portrait_people WHERE person_id=?",
                (person_id,),
            ).fetchone()
        if row is None:
            return {"ok": False, "code": "bridge_unavailable", "person_id": person_id, "last_synced_at": "", "portrait_revision": 0}
        return {
            "ok": clean_text(row["profile_status"], 40) == "active",
            "code": "profile_exact" if clean_text(row["profile_status"], 40) == "active" else "bridge_person_mismatch",
            "person_id": person_id,
            "portrait_revision": int(row["portrait_revision"] or 0),
            "last_synced_at": clean_text(row["last_synced_at"], 80),
        }

    def _list_portrait_people_sync(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT p.*, COUNT(DISTINCT f.id) AS fact_count, COUNT(DISTINCT e.evidence_hash) AS evidence_count
                FROM portrait_people p
                LEFT JOIN portrait_facts f ON f.person_id=p.person_id
                LEFT JOIN portrait_evidence e ON e.person_id=p.person_id
                GROUP BY p.person_id
                ORDER BY p.updated_at DESC
                LIMIT ?
                """,
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [
            {
                "person_id": clean_text(row["person_id"], 80),
                "identity_assurance": clean_text(row["identity_assurance"], 40),
                "profile_status": clean_text(row["profile_status"], 40),
                "projection_revision": int(row["projection_revision"] or 0),
                "portrait_revision": int(row["portrait_revision"] or 0),
                "last_synced_at": clean_text(row["last_synced_at"], 80),
                "updated_at": clean_text(row["updated_at"], 80),
                "capability_summary": json_loads(row["capability_summary"], {}),
                "fact_count": int(row["fact_count"] or 0),
                "evidence_count": int(row["evidence_count"] or 0),
            }
            for row in rows
        ]

    async def portrait_governance_detail(self, person_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._portrait_governance_detail_sync, person_id)

    def _portrait_governance_detail_sync(self, person_id: str) -> dict[str, Any]:
        person_id = clean_text(person_id, 80)
        with self._lock:
            person = self._conn.execute("SELECT * FROM portrait_people WHERE person_id=?", (person_id,)).fetchone()
            if person is None:
                return {"ok": False, "code": "bridge_unavailable", "person": {}, "facts": [], "suppressions": []}
            facts = self._conn.execute(
                """
                SELECT id, dimension, normalized_claim_hash, claim_summary, portrait_tier, producer_kind,
                       derivation_kind, epistemic_status, source_scope, usable_scope, confidence,
                       sensitivity, status, first_evidence_at, last_evidence_at, expires_at, revision
                FROM portrait_facts WHERE person_id=? ORDER BY updated_at DESC LIMIT 200
                """,
                (person_id,),
            ).fetchall()
            suppressions = self._conn.execute(
                """
                SELECT suppression_key, dimension, normalized_claim_hash, scope, reason, actor, status,
                       operation_id, revision, created_at, updated_at, expires_at
                FROM portrait_suppressions WHERE person_id=? ORDER BY updated_at DESC LIMIT 200
                """,
                (person_id,),
            ).fetchall()
        return {
            "ok": True,
            "code": "profile_exact",
            "person": {
                "person_id": person_id,
                "identity_assurance": clean_text(person["identity_assurance"], 40),
                "profile_status": clean_text(person["profile_status"], 40),
                "portrait_revision": int(person["portrait_revision"] or 0),
                "last_synced_at": clean_text(person["last_synced_at"], 80),
                "capability_summary": json_loads(person["capability_summary"], {}),
            },
            "facts": [dict(row) for row in facts],
            "suppressions": [dict(row) for row in suppressions],
        }

    async def govern_portrait_fact(
        self,
        *,
        person_id: str,
        fact_id: str,
        action: str,
        actor: str,
        operation_id: str,
        expires_at: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._govern_portrait_fact_sync,
            person_id,
            fact_id,
            action,
            actor,
            operation_id,
            expires_at,
        )

    def _govern_portrait_fact_sync(
        self,
        person_id: str,
        fact_id: str,
        action: str,
        actor: str,
        operation_id: str,
        expires_at: str,
    ) -> dict[str, Any]:
        person_id = clean_text(person_id, 80)
        fact_id = clean_text(fact_id, 120)
        action = clean_text(action, 40)
        actor = clean_text(actor, 80) or "administrator"
        operation_id = clean_text(operation_id, 120)
        expires_at = clean_text(expires_at, 80)
        if not person_id or not fact_id or not operation_id or action not in {"suppress", "freeze", "reconfirmation_pending"}:
            return {"ok": False, "code": "invalid_request"}
        if action == "freeze" and not expires_at:
            return {"ok": False, "code": "suppression_expiry_required"}
        with self._lock:
            fact = self._conn.execute(
                "SELECT * FROM portrait_facts WHERE id=? AND person_id=?", (fact_id, person_id)
            ).fetchone()
            if fact is None:
                return {"ok": False, "code": "portrait_fact_not_found"}
        reason = {
            "suppress": "administrator_delete_or_forget",
            "freeze": "administrator_temporary_freeze",
            "reconfirmation_pending": "reconfirmation_requested",
        }[action]
        status = "reconfirmation_pending" if action == "reconfirmation_pending" else "active"
        marker = {
            "suppression_key": stable_fingerprint(
                "portrait_suppression", person_id, fact["dimension"], fact["normalized_claim_hash"], fact["source_scope"]
            ),
            "person_id": person_id,
            "dimension": clean_text(fact["dimension"], 80),
            "normalized_claim_hash": clean_text(fact["normalized_claim_hash"], 80),
            "scope": clean_text(fact["source_scope"], 80),
            "reason": reason,
            "actor": actor,
            "status": status,
            "operation_id": operation_id,
            "expires_at": expires_at if action == "freeze" else "",
        }
        result = self._upsert_portrait_suppression_sync(marker)
        return {**result, "fact_id": fact_id, "action": action}

    async def portrait_migration(self, *, operation_id: str, dry_run: bool = True) -> dict[str, Any]:
        return await asyncio.to_thread(self._portrait_migration_sync, operation_id, dry_run)

    def _portrait_migration_sync(self, operation_id: str, dry_run: bool) -> dict[str, Any]:
        operation_id = clean_text(operation_id, 120)
        if not operation_id:
            return {"ok": False, "code": "invalid_request"}
        with self._lock:
            count = int(self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE memory_type IN ('user_profile', 'user_preference', 'user_habit')"
            ).fetchone()[0] or 0)
            if dry_run:
                return {"ok": True, "code": "migration_dry_run", "write_count": 0, "legacy_candidate_count": count}
            prior = self._conn.execute("SELECT * FROM portrait_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if prior is not None:
                return {"ok": True, "code": "migration_idempotent_replay", "operation_id": operation_id}
            now = utc_now()
            self._conn.execute(
                "INSERT INTO portrait_operations(operation_id, operation_kind, payload_hash, snapshot, state, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                (operation_id, "legacy_portrait_projection", stable_fingerprint("portrait", operation_id, count), json_dumps({"fact_ids": []}), "applied", now, now),
            )
            self._conn.commit()
        return {"ok": True, "code": "migration_applied", "operation_id": operation_id, "legacy_candidate_count": count}

    async def rollback_portrait_migration(self, *, operation_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._rollback_portrait_migration_sync, operation_id)

    def _rollback_portrait_migration_sync(self, operation_id: str) -> dict[str, Any]:
        operation_id = clean_text(operation_id, 120)
        with self._lock:
            row = self._conn.execute("SELECT snapshot FROM portrait_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                return {"ok": False, "code": "migration_not_found"}
            snapshot = json_loads(row["snapshot"], {})
            fact_ids = snapshot.get("fact_ids") if isinstance(snapshot, dict) and isinstance(snapshot.get("fact_ids"), list) else []
            if fact_ids:
                self._conn.executemany("DELETE FROM portrait_facts WHERE id=?", [(clean_text(item, 120),) for item in fact_ids if clean_text(item, 120)])
            self._conn.execute("UPDATE portrait_operations SET state='rolled_back', updated_at=? WHERE operation_id=?", (utc_now(), operation_id))
            self._conn.commit()
        return {"ok": True, "code": "migration_rolled_back", "operation_id": operation_id}

    def normalize_legacy_manual_visibility(self) -> int:
        """收回早期版本中过宽的手动记忆默认可见性。"""
        with self._lock:
            with self._transaction_sync():
                return self._normalize_legacy_manual_visibility_sync()

    def normalize_internal_bot_self_scopes(self) -> int:
        """Move legacy internal Bot memories out of user-facing private scopes."""
        with self._lock:
            with self._transaction_sync():
                return self._normalize_internal_bot_self_scopes_sync()

    def _normalize_legacy_manual_visibility_sync(self) -> int:
        private_cur = self._conn.execute(
            """
            UPDATE memories
            SET visibility='private_pair', updated_at=?
            WHERE memory_type='manual_memory' AND visibility='shareable' AND scope='private'
            """,
            (utc_now(),),
        )
        group_cur = self._conn.execute(
            """
            UPDATE memories
            SET visibility='group_public', updated_at=?
            WHERE memory_type='manual_memory' AND visibility='shareable' AND scope='group'
            """,
            (utc_now(),),
        )
        unknown_cur = self._conn.execute(
            """
            UPDATE memories
            SET visibility='internal', updated_at=?
            WHERE memory_type='manual_memory' AND visibility='shareable' AND scope NOT IN ('private', 'group')
            """,
            (utc_now(),),
        )
        return int(private_cur.rowcount or 0) + int(group_cur.rowcount or 0) + int(unknown_cur.rowcount or 0)

    def _normalize_internal_bot_self_scopes_sync(self) -> int:
        rows = self._conn.execute(
            """
            SELECT * FROM memories
            WHERE scope='private'
              AND visibility='bot_self'
              AND source_plugin='private_companion'
              AND (
                    session_id='private_companion:dream'
                    OR id LIKE 'private_companion_dream_%'
                    OR tags LIKE '%"dream_fragment"%'
              )
            """,
        ).fetchall()
        now = utc_now()
        for row in rows:
            record = MemoryRecord.from_row(row)
            record.scope = "unknown"
            record.group_id = ""
            record.content_fingerprint = ""
            record.ensure_defaults()
            self._conn.execute(
                """
                UPDATE memories
                SET scope='unknown', group_id='', content_fingerprint=?, updated_at=?
                WHERE id=?
                """,
                (record.content_fingerprint, now, record.id),
            )
        return len(rows)

    def close(self) -> None:
        with self._operation_condition:
            if self._closed:
                return
            self._closing = True
            while self._active_tracked_operations:
                self._operation_condition.wait()
        with self._lock:
            if self._closed:
                return
            self._conn.commit()
            self._conn.close()
            self._closed = True
        with self._read_lock:
            if self._read_conn is not None:
                try:
                    self._read_conn.close()
                except sqlite3.Error:
                    pass
                self._read_conn = None

    def backup(self, suffix: str = "") -> Path:
        stamp = utc_now().replace(":", "").replace("-", "").replace("+", "_")
        target = self.db_path.with_name(f"{self.db_path.stem}.backup.{stamp}{suffix}.db")
        with self._lock:
            self._conn.commit()
            with closing(sqlite3.connect(str(target))) as target_conn:
                self._conn.backup(target_conn)
        return target

    async def clear_all_memory_data(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._clear_all_memory_data_sync)

    def _clear_all_memory_data_sync(self) -> dict[str, Any]:
        backup = self.backup(".before_clear_all")
        tables = [
            "memory_fts",
            "emotion_event_deliveries",
            "emotion_events",
            "portrait_learning_queue",
            "portrait_daily_runs",
            "portrait_suppressions",
            "portrait_facts",
            "portrait_evidence",
            "portrait_operations",
            "portrait_people",
            "review_queue",
            "injection_logs",
            "summary_failures",
            "chat_import_segments",
            "chat_import_batches",
            "relationship_edges",
            "knowledge_edges",
            "knowledge_nodes",
            "timeline",
            "cross_window_threads",
            "memory_acl_rules",
            "memory_acl_policies",
            "memory_embeddings",
            "identities",
            "memories",
            "import_batches",
        ]
        deleted: dict[str, int] = {}
        with self._lock:
            with self._transaction_sync():
                for table in tables:
                    try:
                        cur = self._conn.execute(f"DELETE FROM {table}")
                    except sqlite3.Error:
                        if table == "memory_fts":
                            continue
                        raise
                    deleted[table] = int(cur.rowcount or 0)
        return {"backup": str(backup), "deleted": deleted}

    async def preview_scoped_memory_clear(
        self,
        *,
        target_type: str,
        group_id: str = "",
        user_id: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._scoped_memory_clear_sync,
            target_type,
            group_id,
            user_id,
            False,
        )

    async def clear_scoped_memory(
        self,
        *,
        target_type: str,
        group_id: str = "",
        user_id: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._scoped_memory_clear_sync,
            target_type,
            group_id,
            user_id,
            True,
        )

    def _scoped_memory_clear_sync(
        self,
        target_type: str,
        group_id: str,
        user_id: str,
        execute: bool,
    ) -> dict[str, Any]:
        target_type = clean_text(target_type, 40).lower()
        group_id = clean_text(group_id, 120)
        user_id = clean_text(user_id, 120)
        if target_type not in {"group", "private", "group_member"}:
            raise ValueError("target_type must be group, private or group_member")
        if target_type == "group" and not group_id:
            raise ValueError("group_id is required")
        if target_type == "private" and not user_id:
            raise ValueError("user_id is required")
        if target_type == "group_member" and (not group_id or not user_id):
            raise ValueError("group_id and user_id are required")

        memory_where, memory_params = self._scoped_memory_where(target_type, group_id, user_id)
        timeline_where, timeline_params = self._scoped_timeline_where(target_type, group_id, user_id)
        relation_where, relation_params = self._scoped_relation_where(target_type, group_id, user_id)
        knowledge_node_where, knowledge_node_params = self._scoped_knowledge_node_where(target_type, group_id, user_id)
        knowledge_edge_where, knowledge_edge_params = self._scoped_knowledge_edge_where(target_type, group_id, user_id)
        injection_where, injection_params = self._scoped_session_log_where(target_type, group_id, user_id)
        thread_where, thread_params = self._scoped_thread_where(target_type, group_id, user_id)

        with self._lock:
            memory_ids = [
                row["id"]
                for row in self._conn.execute(
                    f"SELECT id FROM memories WHERE {memory_where}",
                    memory_params,
                ).fetchall()
            ]
            counts = {
                "memories": len(memory_ids),
                "timeline": self._count_where("timeline", timeline_where, timeline_params),
                "relationship_edges": self._count_where("relationship_edges", relation_where, relation_params),
                "knowledge_nodes": self._count_where("knowledge_nodes", knowledge_node_where, knowledge_node_params),
                "knowledge_edges": self._count_knowledge_edges_for_scope_or_memory_ids(
                    knowledge_edge_where,
                    knowledge_edge_params,
                    memory_ids,
                ),
                "injection_logs": self._count_where("injection_logs", injection_where, injection_params),
                "summary_failures": self._count_where("summary_failures", injection_where, injection_params),
                "cross_window_threads": self._count_where("cross_window_threads", thread_where, thread_params),
            }
            if not execute:
                return {
                    "target_type": target_type,
                    "group_id": group_id,
                    "user_id": user_id,
                    "preview": True,
                    "counts": counts,
                }

            backup = self.backup(f".before_clear_{target_type}")
            deleted: dict[str, int] = {}
            with self._transaction_sync():
                if memory_ids:
                    self._delete_many_by_ids("review_queue", "memory_id", memory_ids, deleted)
                    self._delete_many_by_ids("memory_embeddings", "memory_id", memory_ids, deleted)
                    self._delete_many_by_ids("knowledge_edges", "source_memory_id", memory_ids, deleted)
                    self._delete_many_by_ids("relationship_edges", "source_memory_id", memory_ids, deleted)
                    for memory_id in memory_ids:
                        self._delete_memory_fts_row(memory_id)
                deleted["memories"] = self._delete_where("memories", memory_where, memory_params)
                deleted["timeline"] = self._delete_where("timeline", timeline_where, timeline_params)
                deleted["relationship_edges"] = deleted.get("relationship_edges", 0) + self._delete_where(
                    "relationship_edges", relation_where, relation_params
                )
                deleted["knowledge_edges"] = deleted.get("knowledge_edges", 0) + self._delete_where(
                    "knowledge_edges",
                    knowledge_edge_where,
                    knowledge_edge_params,
                )
                deleted["knowledge_nodes"] = self._delete_where("knowledge_nodes", knowledge_node_where, knowledge_node_params)
                deleted["injection_logs"] = self._delete_where("injection_logs", injection_where, injection_params)
                deleted["summary_failures"] = self._delete_where("summary_failures", injection_where, injection_params)
                deleted["cross_window_threads"] = self._delete_where("cross_window_threads", thread_where, thread_params)
        return {
            "target_type": target_type,
            "group_id": group_id,
            "user_id": user_id,
            "preview": False,
            "backup": str(backup),
            "counts": counts,
            "deleted": deleted,
        }

    def _count_where(self, table: str, where: str, params: list[Any]) -> int:
        row = self._conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params).fetchone()
        return int(row["c"] if row else 0)

    def _delete_where(self, table: str, where: str, params: list[Any]) -> int:
        cur = self._conn.execute(f"DELETE FROM {table} WHERE {where}", params)
        return int(cur.rowcount or 0)

    def _delete_many_by_ids(self, table: str, column: str, ids: list[str], deleted: dict[str, int]) -> None:
        total = 0
        for index in range(0, len(ids), 500):
            chunk = ids[index:index + 500]
            placeholders = ",".join("?" for _ in chunk)
            cur = self._conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", chunk)
            total += int(cur.rowcount or 0)
        deleted[table] = deleted.get(table, 0) + total

    @staticmethod
    def _like_id(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}"

    def _session_target_where(self, column: str, scope: str, target_id: str) -> tuple[str, list[Any]]:
        target_id = clean_text(target_id, 120)
        lowered = target_id.lower()
        if scope == "group":
            tokens = (":groupmessage:", ":group:")
        else:
            tokens = (":friendmessage:", ":privatemessage:", ":friend:", ":private:")
        clauses = [f"{column}=?"]
        params: list[Any] = [target_id]
        for token in tokens:
            clauses.append(f"LOWER({column}) LIKE ? ESCAPE '\\'")
            params.append(self._like_id(f"{token}{lowered}"))
        return f"({' OR '.join(clauses)})", params

    def _count_knowledge_edges_for_scope_or_memory_ids(
        self,
        where: str,
        params: list[Any],
        memory_ids: list[str],
    ) -> int:
        edge_ids = {
            row["id"]
            for row in self._conn.execute(f"SELECT id FROM knowledge_edges WHERE {where}", params).fetchall()
        }
        for index in range(0, len(memory_ids), 500):
            chunk = memory_ids[index:index + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = self._conn.execute(
                f"SELECT id FROM knowledge_edges WHERE source_memory_id IN ({placeholders})",
                chunk,
            ).fetchall()
            edge_ids.update(row["id"] for row in rows)
        return len(edge_ids)

    def _scoped_memory_where(self, target_type: str, group_id: str, user_id: str) -> tuple[str, list[Any]]:
        if target_type == "group":
            session_where, session_params = self._session_target_where("session_id", "group", group_id)
            return (
                f"scope='group' AND (group_id=? OR object_id=? OR {session_where})",
                [group_id, group_id, *session_params],
            )
        if target_type == "private":
            session_where, session_params = self._session_target_where("session_id", "private", user_id)
            return (
                f"scope='private' AND (subject_id=? OR object_id=? OR {session_where})",
                [user_id, user_id, *session_params],
            )
        session_where, session_params = self._session_target_where("session_id", "group", group_id)
        return (
            f"scope='group' AND (group_id=? OR {session_where}) AND (subject_id=? OR object_id=?)",
            [group_id, *session_params, user_id, user_id],
        )

    def _scoped_timeline_where(self, target_type: str, group_id: str, user_id: str) -> tuple[str, list[Any]]:
        if target_type == "group":
            session_where, session_params = self._session_target_where("session_id", "group", group_id)
            return (f"scope='group' AND ({session_where} OR object_id=?)", [*session_params, group_id])
        if target_type == "private":
            session_where, session_params = self._session_target_where("session_id", "private", user_id)
            return (
                f"scope='private' AND (subject_id=? OR object_id=? OR {session_where})",
                [user_id, user_id, *session_params],
            )
        session_where, session_params = self._session_target_where("session_id", "group", group_id)
        return (
            f"scope='group' AND {session_where} AND (subject_id=? OR object_id=?)",
            [*session_params, user_id, user_id],
        )

    def _scoped_relation_where(self, target_type: str, group_id: str, user_id: str) -> tuple[str, list[Any]]:
        if target_type == "group":
            session_where, session_params = self._session_target_where("session_id", "group", group_id)
            return (f"scope='group' AND (group_id=? OR {session_where})", [group_id, *session_params])
        if target_type == "private":
            session_where, session_params = self._session_target_where("session_id", "private", user_id)
            return (
                f"scope='private' AND (subject_id=? OR object_id=? OR {session_where})",
                [user_id, user_id, *session_params],
            )
        session_where, session_params = self._session_target_where("session_id", "group", group_id)
        return (
            f"scope='group' AND (group_id=? OR {session_where}) AND (subject_id=? OR object_id=?)",
            [group_id, *session_params, user_id, user_id],
        )

    def _scoped_knowledge_node_where(self, target_type: str, group_id: str, user_id: str) -> tuple[str, list[Any]]:
        if target_type == "group":
            session_where, session_params = self._session_target_where("session_id", "group", group_id)
            return (f"scope='group' AND (group_id=? OR {session_where})", [group_id, *session_params])
        if target_type == "private":
            session_where, session_params = self._session_target_where("session_id", "private", user_id)
            return (f"scope='private' AND {session_where}", session_params)
        session_where, session_params = self._session_target_where("session_id", "group", group_id)
        return (
            f"scope='group' AND (group_id=? OR {session_where}) AND node_type='user' AND node_key=?",
            [group_id, *session_params, user_id.lower()],
        )

    def _scoped_knowledge_edge_where(self, target_type: str, group_id: str, user_id: str) -> tuple[str, list[Any]]:
        if target_type == "group":
            session_where, session_params = self._session_target_where("session_id", "group", group_id)
            return (f"scope='group' AND (group_id=? OR {session_where})", [group_id, *session_params])
        if target_type == "private":
            session_where, session_params = self._session_target_where("session_id", "private", user_id)
            return (f"scope='private' AND {session_where}", session_params)
        session_where, session_params = self._session_target_where("session_id", "group", group_id)
        return (
            f"""scope='group' AND (group_id=? OR {session_where}) AND (
                source_node_id IN (SELECT id FROM knowledge_nodes WHERE node_type='user' AND node_key=?)
                OR target_node_id IN (SELECT id FROM knowledge_nodes WHERE node_type='user' AND node_key=?)
            )""",
            [group_id, *session_params, user_id.lower(), user_id.lower()],
        )

    def _scoped_session_log_where(self, target_type: str, group_id: str, user_id: str) -> tuple[str, list[Any]]:
        if target_type == "group":
            session_where, session_params = self._session_target_where("session_id", "group", group_id)
            return (f"scope='group' AND {session_where}", session_params)
        if target_type == "private":
            session_where, session_params = self._session_target_where("session_id", "private", user_id)
            return (f"scope='private' AND {session_where}", session_params)
        return ("1=0", [])

    def _scoped_thread_where(self, target_type: str, group_id: str, user_id: str) -> tuple[str, list[Any]]:
        if target_type == "group_member":
            return ("1=0", [])
        value = group_id if target_type in {"group", "group_member"} else user_id
        scope = "group" if target_type == "group" else "private"
        from_where, from_params = self._session_target_where("from_session", scope, value)
        to_where, to_params = self._session_target_where("to_session", scope, value)
        return (f"{from_where} OR {to_where}", [*from_params, *to_params])

    @staticmethod
    def profile_memory_fingerprint(record: MemoryRecord) -> str:
        """Fingerprint fields governed by profile repair, excluding access counters."""
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        payload = {
            "id": record.id,
            "memory_type": record.memory_type,
            "subject": {
                "kind": record.subject.kind,
                "id": record.subject.id,
                "name": record.subject.name,
                "role": record.subject.role,
            },
            "object": {
                "kind": record.object.kind,
                "id": record.object.id,
                "name": record.object.name,
                "role": record.object.role,
            },
            "scope": record.scope,
            "session_id": record.session_id,
            "platform": record.platform,
            "message_id": record.message_id,
            "group_id": record.group_id,
            "visibility": record.visibility,
            "sayability": record.sayability,
            "reality_level": record.reality_level,
            "lifecycle": record.lifecycle,
            "content": record.content,
            "evidence": record.evidence,
            "confidence": record.confidence,
            "importance": record.importance,
            "review_status": record.review_status,
            "tags": list(record.tags or []),
            "metadata": metadata,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "occurred_at": record.occurred_at,
            "source_plugin": record.source_plugin,
            "import_batch_id": record.import_batch_id,
            "content_fingerprint": record.content_fingerprint,
            "merged_count": record.merged_count,
            "supersedes_id": record.supersedes_id,
        }
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def profile_repair_plan_fingerprint(actions: list[dict[str, Any]]) -> str:
        """Return a deterministic fingerprint for an ordered repair action plan."""
        raw = json.dumps(
            actions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def profile_repair_group_id(record_id: Any) -> str:
        record_id = clean_text(record_id, 120)
        return (
            "profile_group_"
            + stable_fingerprint("profile_repair_group", record_id)[:24]
            if record_id
            else ""
        )

    @staticmethod
    def profile_portrait_fact_fingerprint(fact: Any) -> str:
        data = dict(fact) if fact is not None else {}
        fields = (
            "id",
            "person_id",
            "dimension",
            "normalized_claim_hash",
            "claim_summary",
            "portrait_tier",
            "producer_kind",
            "producer_version",
            "derivation_kind",
            "epistemic_status",
            "source_scope",
            "usable_scope",
            "confidence",
            "sensitivity",
            "status",
            "evidence_hashes",
            "context_refs",
            "first_evidence_at",
            "last_evidence_at",
            "expires_at",
            "supersedes_id",
            "revision",
            "operation_id",
            "created_at",
            "updated_at",
        )
        payload = {field: data.get(field) for field in fields}
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def profile_portrait_queue_fingerprint(rows: Any) -> str:
        normalized = sorted(
            (dict(row) for row in (rows or [])),
            key=lambda item: (
                clean_text(item.get("queue_id"), 120),
                clean_text(item.get("evidence_hash"), 80),
            ),
        )
        raw = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _memory_db_snapshot(record: MemoryRecord) -> dict[str, Any]:
        return dict(record.to_db())

    @staticmethod
    def _memory_from_db_snapshot(snapshot: dict[str, Any]) -> MemoryRecord:
        return MemoryRecord.from_row(snapshot)

    def _write_memory_record_sync(self, record: MemoryRecord) -> sqlite3.Row:
        record.ensure_defaults()
        data = record.to_db()
        columns = ", ".join(data.keys())
        placeholders = ", ".join(f":{key}" for key in data)
        updates = ", ".join(f"{key}=excluded.{key}" for key in data if key != "id")
        self._conn.execute(
            f"INSERT INTO memories ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            data,
        )
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id=?", (record.id,)
        ).fetchone()
        self._upsert_memory_fts_row(row)
        return row

    @staticmethod
    def _profile_evidence_refs(record: MemoryRecord) -> list[str]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        raw_refs: list[Any] = []
        for key in ("profile_evidence_refs", "source_memory_ids", "evidence_refs"):
            value = metadata.get(key)
            if isinstance(value, list):
                raw_refs.extend(value)
        source_memory_id = clean_text(metadata.get("source_memory_id"), 160)
        if source_memory_id:
            raw_refs.append(source_memory_id)
        elif not raw_refs and record.message_id:
            raw_refs.append(record.message_id)
        refs = [clean_text(value, 160) for value in raw_refs if clean_text(value, 160)]
        if not refs:
            refs = [
                "fallback:"
                + stable_fingerprint(
                    record.scope,
                    record.session_id,
                    record.subject.id,
                    record.evidence,
                )
            ]
        return list(dict.fromkeys(refs))[:256]

    @staticmethod
    def _profile_incoming_evidence_refs(record: MemoryRecord) -> list[str]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        source_memory_id = clean_text(metadata.get("source_memory_id"), 160)
        if source_memory_id:
            return [source_memory_id]
        message_id = clean_text(record.message_id, 160)
        if message_id:
            return [message_id]
        return [
            "fallback:"
            + stable_fingerprint(
                record.scope,
                record.session_id,
                record.subject.id,
                record.evidence,
            )
        ]

    @staticmethod
    def _profile_evidence_text(records: list[MemoryRecord]) -> str:
        parts: list[str] = []
        for record in records:
            for part in clean_text(record.evidence, 4000).split("\n---\n"):
                cleaned = clean_text(part, 1200)
                if cleaned and cleaned not in parts:
                    parts.append(cleaned)
        return clean_text("\n---\n".join(parts), 4000)

    @staticmethod
    def _profile_statement_fingerprints(record: MemoryRecord) -> list[str]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        raw = metadata.get("profile_statement_fingerprints")
        values = (
            [clean_text(item, 80) for item in raw if clean_text(item, 80)]
            if isinstance(raw, list)
            else []
        )
        if not values and clean_text(record.evidence, 4000):
            values.append(
                stable_fingerprint("profile_statement", record.evidence.casefold())
            )
        return list(dict.fromkeys(values))[:256]

    @staticmethod
    def _profile_incoming_statement_fingerprints(
        record: MemoryRecord,
    ) -> list[str]:
        evidence = clean_text(record.evidence, 4000)
        if not evidence:
            return []
        return [stable_fingerprint("profile_statement", evidence.casefold())]

    @staticmethod
    def _profile_evidence_passes_quality_gate(record: MemoryRecord) -> bool:
        metadata = dict(record.metadata) if isinstance(record.metadata, dict) else {}
        metadata["profile_state"] = "active"
        metadata["profile_status"] = "active"
        metadata["independent_evidence_count"] = 2
        allowed, _reason = profile_quality_decision(
            {"memory_type": record.memory_type, "metadata": metadata},
            require_active=True,
        )
        return allowed

    @staticmethod
    def _profile_domain(record: MemoryRecord) -> tuple[str, ...]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        return (
            clean_text(record.platform, 80).lower(),
            clean_text(record.subject.kind, 40).lower(),
            clean_text(record.subject.id, 120),
            clean_text(record.object.kind, 40).lower(),
            clean_text(record.object.id, 120),
            clean_text(record.scope, 40).lower(),
            clean_text(record.group_id, 120),
            clean_text(record.visibility, 40).lower(),
            clean_text(metadata.get("owner_bot_id"), 120),
        )

    def _profile_domain_rows_sync(self, record: MemoryRecord) -> list[sqlite3.Row]:
        rows = self._conn.execute(
            """
            SELECT * FROM memories
            WHERE memory_type IN ('user_profile', 'user_preference', 'user_habit')
              AND platform=? AND subject_kind=? AND subject_id=?
              AND object_kind=? AND object_id=? AND scope=? AND group_id=? AND visibility=?
              AND lifecycle!='archived'
            """,
            (
                clean_text(record.platform, 80),
                clean_text(record.subject.kind, 40),
                clean_text(record.subject.id, 120),
                clean_text(record.object.kind, 40),
                clean_text(record.object.id, 120),
                clean_text(record.scope, 40),
                clean_text(record.group_id, 120),
                clean_text(record.visibility, 40),
            ),
        ).fetchall()
        domain = self._profile_domain(record)
        return [
            row
            for row in rows
            if self._profile_domain(MemoryRecord.from_row(row)) == domain
        ]

    def _profile_single_value_domain_conflict_sync(
        self, record: MemoryRecord
    ) -> bool:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        extractor = clean_text(metadata.get("extractor"), 40).lower()
        dimension = clean_text(metadata.get("profile_dimension"), 80).lower()
        cardinality = (
            "single"
            if dimension in self.PROFILE_SINGLE_VALUE_DIMENSIONS
            else clean_text(metadata.get("profile_cardinality"), 20).lower()
            or "multi"
        )
        if not (
            record.memory_type in self.PROFILE_MEMORY_TYPES
            and extractor in self.PROFILE_RULE_EXTRACTORS
            and dimension
            and cardinality == "single"
            and self._profile_state(record) == "active"
        ):
            return False
        for domain_row in self._profile_domain_rows_sync(record):
            other = MemoryRecord.from_row(domain_row)
            other_metadata = (
                other.metadata if isinstance(other.metadata, dict) else {}
            )
            if (
                other.id != record.id
                and self._profile_state(other) == "active"
                and clean_text(
                    other_metadata.get("profile_dimension"), 80
                ).lower()
                == dimension
            ):
                return True
        return False

    def _profile_single_value_invariant_signature(
        self, record: MemoryRecord
    ) -> tuple[Any, ...]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        dimension = clean_text(metadata.get("profile_dimension"), 80).lower()
        cardinality = (
            "single"
            if dimension in self.PROFILE_SINGLE_VALUE_DIMENSIONS
            else clean_text(metadata.get("profile_cardinality"), 20).lower()
            or "multi"
        )
        return (
            clean_text(record.memory_type, 80),
            self._profile_domain(record),
            self._profile_state(record),
            clean_text(record.lifecycle, 40),
            clean_text(record.review_status, 40),
            clean_text(metadata.get("extractor"), 40).lower(),
            dimension,
            cardinality,
            normalize_profile_value(metadata.get("normalized_value")),
        )

    @staticmethod
    def _profile_state(record: MemoryRecord) -> str:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        state = clean_text(
            metadata.get("profile_state") or metadata.get("profile_status"),
            32,
        ).lower()
        if state in {"candidate", "active", "rejected", "superseded"}:
            return state
        if record.lifecycle == "archived":
            return "superseded" if record.supersedes_id else "rejected"
        if record.review_status == "pending":
            return "candidate"
        return "active"

    async def upsert_profile_candidate(self, record: MemoryRecord) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(
            self._upsert_profile_candidate_sync,
            deepcopy(record),
        )

    def _upsert_profile_candidate_sync(self, record: MemoryRecord) -> dict[str, Any]:
        record.ensure_defaults()
        metadata = dict(record.metadata) if isinstance(record.metadata, dict) else {}
        extractor = clean_text(metadata.get("extractor"), 40).lower()
        dimension = clean_text(metadata.get("profile_dimension"), 80).lower()
        profile_value = clean_text(metadata.get("profile_value"), 240)
        normalized = normalize_profile_value(metadata.get("normalized_value"))
        polarity = clean_text(metadata.get("profile_polarity"), 40).lower()
        if (
            record.memory_type not in self.PROFILE_MEMORY_TYPES
            or extractor not in self.PROFILE_RULE_EXTRACTORS
            or not dimension
            or not profile_value
            or not normalized
            or normalize_profile_value(profile_value) != normalized
        ):
            return {"ok": False, "code": "profile_candidate_invalid", "memory_id": ""}
        try:
            raw_quality_score = float(metadata.get("extraction_quality_score"))
        except (TypeError, ValueError):
            return {"ok": False, "code": "profile_candidate_invalid", "memory_id": ""}
        if not math.isfinite(raw_quality_score):
            return {"ok": False, "code": "profile_candidate_invalid", "memory_id": ""}
        quality_score = max(0.0, min(1.0, raw_quality_score))

        requested_state = clean_text(
            metadata.get("profile_state") or metadata.get("profile_status"),
            32,
        ).lower()
        explicit_active = bool(
            requested_state == "active"
            and clean_text(metadata.get("extraction_quality"), 40).lower() == "explicit"
            and clean_text(metadata.get("evidence_strength"), 40).lower()
            == "direct_statement"
            and metadata.get("quality_gate_passed") is True
            and quality_score >= 0.8
        )
        requested_state = "active" if explicit_active else "candidate"
        try:
            required_evidence = max(
                1 if explicit_active else 2,
                min(10, int(metadata.get("required_evidence_count") or 2)),
            )
        except (TypeError, ValueError):
            required_evidence = 1 if explicit_active else 2
        incoming_refs = self._profile_incoming_evidence_refs(record)
        incoming_statement_fingerprints = (
            self._profile_incoming_statement_fingerprints(record)
        )
        now = utc_now()

        with self._lock:  # noqa: SIM117
            # T3: 画像域扫描为只读查询，前移到写事务外执行（autocommit 读），
            # 避免在 BEGIN IMMEDIATE 持有写锁期间做全表扫描而阻塞其他写者。
            domain_rows = self._profile_domain_rows_sync(record)
            with self._transaction_sync():
                exact_records: list[MemoryRecord] = []
                for row in domain_rows:
                    candidate = MemoryRecord.from_row(row)
                    candidate_metadata = (
                        candidate.metadata
                        if isinstance(candidate.metadata, dict)
                        else {}
                    )
                    if (
                        clean_text(
                            candidate_metadata.get("profile_dimension"), 80
                        ).lower()
                        != dimension
                    ):
                        continue
                    candidate_polarity = clean_text(
                        candidate_metadata.get("profile_polarity"),
                        40,
                    ).lower()
                    if (
                        normalize_profile_value(
                            candidate_metadata.get("normalized_value")
                        )
                        == normalized
                        and candidate_polarity == polarity
                    ):
                        exact_records.append(candidate)

                exact_records.sort(
                    key=lambda item: (
                        self._profile_state(item) == "active",
                        int(item.merged_count or 1),
                        item.updated_at,
                    ),
                    reverse=True,
                )
                if exact_records:
                    canonical = exact_records[0]
                    existing_metadata = (
                        dict(canonical.metadata)
                        if isinstance(canonical.metadata, dict)
                        else {}
                    )
                    existing_state = self._profile_state(canonical)
                else:
                    canonical = deepcopy(record)
                    profile_key = stable_fingerprint(
                        *self._profile_domain(record),
                        dimension,
                        polarity,
                        normalized,
                    )
                    canonical.id = f"profile_{profile_key}"
                    if self._conn.execute(
                        "SELECT 1 FROM memories WHERE id=?", (canonical.id,)
                    ).fetchone():
                        collision_seed = stable_fingerprint(
                            profile_key,
                            record.id,
                            *incoming_refs,
                            *incoming_statement_fingerprints,
                        )
                        sequence = 1
                        while True:
                            candidate_id = f"profile_{stable_fingerprint(collision_seed, str(sequence))}"
                            if self._conn.execute(
                                "SELECT 1 FROM memories WHERE id=?", (candidate_id,)
                            ).fetchone() is None:
                                canonical.id = candidate_id
                                break
                            sequence += 1
                    existing_metadata = {}
                    existing_state = "candidate"

                all_records = [*exact_records, record]
                refs: list[str] = []
                statement_fingerprints: list[str] = []
                for item in exact_records:
                    refs.extend(self._profile_evidence_refs(item))
                    statement_fingerprints.extend(
                        self._profile_statement_fingerprints(item)
                    )
                refs.extend(incoming_refs)
                statement_fingerprints.extend(incoming_statement_fingerprints)
                refs = list(dict.fromkeys(refs))[:256]
                statement_fingerprints = list(dict.fromkeys(statement_fingerprints))[
                    :256
                ]
                qualified_refs: list[str] = []
                qualified_statement_fingerprints: list[str] = []
                for item in exact_records:
                    item_metadata = (
                        item.metadata if isinstance(item.metadata, dict) else {}
                    )
                    stored_refs = item_metadata.get(
                        "profile_qualified_evidence_refs"
                    )
                    stored_statements = item_metadata.get(
                        "profile_qualified_statement_fingerprints"
                    )
                    if isinstance(stored_refs, list) and isinstance(
                        stored_statements, list
                    ):
                        qualified_refs.extend(stored_refs)
                        qualified_statement_fingerprints.extend(stored_statements)
                    elif self._profile_evidence_passes_quality_gate(item):
                        qualified_refs.extend(self._profile_evidence_refs(item))
                        qualified_statement_fingerprints.extend(
                            self._profile_statement_fingerprints(item)
                        )
                if self._profile_evidence_passes_quality_gate(record):
                    qualified_refs.extend(incoming_refs)
                    qualified_statement_fingerprints.extend(
                        incoming_statement_fingerprints
                    )
                qualified_refs = list(dict.fromkeys(qualified_refs))[:256]
                qualified_statement_fingerprints = list(
                    dict.fromkeys(qualified_statement_fingerprints)
                )[:256]
                independent_evidence_count = min(
                    len(qualified_refs),
                    len(qualified_statement_fingerprints),
                )
                existing_refs: list[str] = []
                for item in exact_records:
                    existing_refs.extend(self._profile_evidence_refs(item))
                existing_refs = list(dict.fromkeys(existing_refs))
                evidence_added = any(ref not in existing_refs for ref in incoming_refs)

                merged_metadata = dict(existing_metadata)
                merged_metadata.update(metadata)
                merged_metadata["extractor"] = extractor
                merged_metadata["profile_dimension"] = dimension
                merged_metadata["profile_polarity"] = polarity
                merged_metadata["normalized_value"] = clean_text(
                    metadata.get("normalized_value"), 240
                )
                merged_metadata["profile_value"] = profile_value
                try:
                    existing_quality_score = float(
                        existing_metadata.get("extraction_quality_score") or 0.0
                    )
                except (TypeError, ValueError):
                    existing_quality_score = 0.0
                merged_metadata["extraction_quality_score"] = round(
                    max(quality_score, existing_quality_score),
                    4,
                )
                merged_metadata["profile_evidence_refs"] = refs
                merged_metadata["profile_statement_fingerprints"] = (
                    statement_fingerprints
                )
                merged_metadata["profile_qualified_evidence_refs"] = qualified_refs
                merged_metadata["profile_qualified_statement_fingerprints"] = (
                    qualified_statement_fingerprints
                )
                merged_metadata["evidence_count"] = len(refs)
                merged_metadata["independent_evidence_count"] = (
                    independent_evidence_count
                )
                merged_metadata["required_evidence_count"] = required_evidence
                merged_metadata["profile_cardinality"] = (
                    "single"
                    if dimension in self.PROFILE_SINGLE_VALUE_DIMENSIONS
                    else clean_text(metadata.get("profile_cardinality"), 20)
                    or "multi"
                )

                activation_metadata = {
                    **merged_metadata,
                    "profile_state": "active",
                    "profile_status": "active",
                }
                activation_allowed, _activation_reason = profile_quality_decision(
                    activation_metadata,
                    require_active=True,
                )

                next_state = (
                    "active"
                    if (
                        existing_state == "active"
                        or activation_allowed
                        and (
                            requested_state == "active"
                            or independent_evidence_count >= required_evidence
                        )
                    )
                    else "candidate"
                )
                merged_metadata["profile_state"] = next_state
                merged_metadata["profile_status"] = next_state
                merged_metadata["profile_status_updated_at"] = now
                canonical.metadata = merged_metadata
                if not exact_records or requested_state == "active":
                    canonical.content = record.content
                    canonical.memory_type = record.memory_type
                    canonical.tags = list(
                        dict.fromkeys([*(canonical.tags or []), *(record.tags or [])])
                    )
                canonical.evidence = self._profile_evidence_text(all_records)
                canonical.confidence = max(
                    float(canonical.confidence or 0.0), quality_score
                )
                canonical.importance = max(
                    float(canonical.importance or 0.0), float(record.importance or 0.0)
                )
                canonical.merged_count = max(1, len(refs))
                canonical.lifecycle = (
                    "stable_memory" if next_state == "active" else "raw_event"
                )
                canonical.review_status = (
                    "auto" if next_state == "active" else "pending"
                )
                canonical.updated_at = now
                canonical.content_fingerprint = ""
                canonical.ensure_defaults()
                self._write_memory_record_sync(canonical)

                superseded_ids: list[str] = []
                duplicate_ids = [item.id for item in exact_records[1:]]
                cardinality = clean_text(
                    merged_metadata.get("profile_cardinality"), 20
                ).lower()
                if next_state == "active" and cardinality == "single":
                    for row in domain_rows:
                        other = MemoryRecord.from_row(row)
                        other_metadata = (
                            other.metadata if isinstance(other.metadata, dict) else {}
                        )
                        if other.id == canonical.id:
                            continue
                        if (
                            clean_text(
                                other_metadata.get("profile_dimension"), 80
                            ).lower()
                            != dimension
                        ):
                            continue
                        if self._profile_state(other) == "active":
                            duplicate_ids.append(other.id)
                for memory_id in list(dict.fromkeys(duplicate_ids)):
                    row = self._conn.execute(
                        "SELECT * FROM memories WHERE id=?", (memory_id,)
                    ).fetchone()
                    if row is None:
                        continue
                    other = MemoryRecord.from_row(row)
                    other_metadata = (
                        dict(other.metadata) if isinstance(other.metadata, dict) else {}
                    )
                    other_metadata["profile_state"] = "superseded"
                    other_metadata["profile_status"] = "superseded"
                    other_metadata["profile_superseded_by"] = canonical.id
                    other_metadata["profile_status_updated_at"] = now
                    other.metadata = other_metadata
                    other.lifecycle = "archived"
                    other.supersedes_id = canonical.id
                    other.updated_at = now
                    self._write_memory_record_sync(other)
                    self._conn.execute(
                        "DELETE FROM memory_embeddings WHERE memory_id=?", (other.id,)
                    )
                    self._conn.execute(
                        "UPDATE review_queue SET status='superseded', updated_at=? WHERE memory_id=?",
                        (now, other.id),
                    )
                    superseded_ids.append(other.id)

                if next_state == "candidate":
                    self._upsert_review_sync(
                        canonical.id, "profile_candidate_requires_evidence"
                    )
                    self._conn.execute(
                        "DELETE FROM memory_embeddings WHERE memory_id=?",
                        (canonical.id,),
                    )
                else:
                    self._conn.execute(
                        "UPDATE review_queue SET status='auto', updated_at=? WHERE memory_id=? AND status='pending'",
                        (now, canonical.id),
                    )
                self._embedding_candidate_cache.clear()
                self._embedding_candidate_cache_revision = ""

        return {
            "ok": True,
            "code": "profile_candidate_upserted",
            "memory_id": canonical.id,
            "profile_status": next_state,
            "evidence_count": len(refs),
            "independent_evidence_count": independent_evidence_count,
            "evidence_added": evidence_added,
            "superseded_ids": superseded_ids,
        }

    async def list_rule_profile_memories(
        self,
        *,
        user_id: str = "",
        scope: str = "",
        memory_types: list[str] | None = None,
        extractors: list[str] | None = None,
        include_archived: bool = True,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_rule_profile_memories_sync,
            user_id,
            scope,
            list(memory_types or []),
            list(extractors or []),
            include_archived,
            limit,
            offset,
        )

    def _list_rule_profile_memories_sync(
        self,
        user_id: str,
        scope: str,
        memory_types: list[str],
        extractors: list[str],
        include_archived: bool,
        limit: int,
        offset: int,
    ) -> list[MemoryRecord]:
        requested_types = [clean_text(value, 80) for value in memory_types]
        invalid_types = sorted(
            {
                value or "<empty>"
                for value in requested_types
                if value not in self.PROFILE_MEMORY_TYPES
            }
        )
        if invalid_types:
            raise ValueError(
                "unsupported profile memory type filter: " + ", ".join(invalid_types)
            )
        selected_types = list(dict.fromkeys(requested_types)) or sorted(
            self.PROFILE_MEMORY_TYPES
        )

        requested_extractors = [clean_text(value, 40).lower() for value in extractors]
        invalid_extractors = sorted(
            {
                value or "<empty>"
                for value in requested_extractors
                if value not in self.PROFILE_RULE_EXTRACTORS
            }
        )
        if invalid_extractors:
            raise ValueError(
                "unsupported profile extractor filter: " + ", ".join(invalid_extractors)
            )
        selected_extractors = list(dict.fromkeys(requested_extractors)) or sorted(
            self.PROFILE_RULE_EXTRACTORS
        )
        type_marks = ",".join("?" for _ in selected_types)
        extractor_marks = ",".join("?" for _ in selected_extractors)
        where = [
            f"memory_type IN ({type_marks})",
            "json_valid(metadata)",
            f"LOWER(COALESCE(CAST(json_extract(metadata, '$.extractor') AS TEXT), '')) IN ({extractor_marks})",
        ]
        params: list[Any] = [*selected_types, *selected_extractors]
        if user_id:
            where.append("subject_id=?")
            params.append(clean_text(user_id, 120))
        if scope:
            where.append("scope=?")
            params.append(clean_text(scope, 40))
        if not include_archived:
            where.append("lifecycle!='archived'")
        safe_limit = max(1, min(100000, int(limit or 5000)))
        safe_offset = max(0, int(offset or 0))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM memories
                WHERE {" AND ".join(where)}
                ORDER BY subject_id, scope, occurred_at, created_at, id
                LIMIT ? OFFSET ?
                """,
                [*params, safe_limit, safe_offset],
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    async def list_rule_portrait_facts(
        self,
        *,
        person_id: str = "",
        source_scope: str = "",
        include_inactive: bool = True,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_rule_portrait_facts_sync,
            person_id,
            source_scope,
            include_inactive,
            limit,
            offset,
        )

    def _list_rule_portrait_facts_sync(
        self,
        person_id: str,
        source_scope: str,
        include_inactive: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        versions = sorted(self.PROFILE_RULE_PORTRAIT_VERSIONS)
        marks = ",".join("?" for _ in versions)
        where = [
            "producer_kind='rule_explicit'",
            f"producer_version IN ({marks})",
        ]
        params: list[Any] = [*versions]
        if person_id:
            where.append("person_id=?")
            params.append(clean_text(person_id, 80))
        if source_scope:
            where.append("source_scope=?")
            params.append(clean_text(source_scope, 80))
        if not include_inactive:
            where.append("status='active'")
        safe_limit = max(1, min(100000, int(limit or 5000)))
        safe_offset = max(0, int(offset or 0))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM portrait_facts
                WHERE {" AND ".join(where)}
                ORDER BY person_id, source_scope, dimension,
                         last_evidence_at, created_at, id
                LIMIT ? OFFSET ?
                """,
                [*params, safe_limit, safe_offset],
            ).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                queue_rows = self._conn.execute(
                    """
                    SELECT * FROM portrait_learning_queue
                    WHERE fact_id=? ORDER BY queue_id
                    """,
                    (row["id"],),
                ).fetchall()
                item["queue_fingerprint"] = (
                    self.profile_portrait_queue_fingerprint(queue_rows)
                )
                results.append(item)
        return results

    @staticmethod
    def _valid_profile_operation_id(operation_id: Any) -> str:
        value = clean_text(operation_id, 120)
        return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value) else ""

    def _profile_repair_record_snapshot_sync(
        self,
        record: MemoryRecord,
        *,
        group_id: str = "",
        guard_only: bool = False,
    ) -> dict[str, Any]:
        review_rows = self._conn.execute(
            "SELECT * FROM review_queue WHERE memory_id=? ORDER BY created_at, id",
            (record.id,),
        ).fetchall()
        embedding_rows = self._conn.execute(
            "SELECT * FROM memory_embeddings WHERE memory_id=? ORDER BY provider_id",
            (record.id,),
        ).fetchall()
        embedding_snapshots: list[dict[str, Any]] = []
        for row in embedding_rows:
            snapshot = dict(row)
            raw_vector = snapshot.get("vector")
            # 二进制向量转回 JSON 文本，保证快照可 json 序列化且恢复路径兼容
            if isinstance(raw_vector, (bytes, bytearray, memoryview)):
                snapshot["vector"] = json_dumps(_unpack_embedding_vector(raw_vector))
            embedding_snapshots.append(snapshot)
        return {
            "record_kind": "memory",
            "record_id": record.id,
            "memory_id": record.id,
            "group_id": clean_text(group_id, 120),
            "guard_only": bool(guard_only),
            "before": self._memory_db_snapshot(record),
            "review_queue": [dict(row) for row in review_rows],
            "embeddings": embedding_snapshots,
            "after_fingerprint": "",
        }

    def _profile_repair_portrait_snapshot_sync(
        self,
        fact: Any,
        *,
        group_id: str = "",
        guard_only: bool = False,
    ) -> dict[str, Any]:
        fact_data = dict(fact)
        fact_id = clean_text(fact_data.get("id"), 120)
        queue_rows = self._conn.execute(
            """
            SELECT * FROM portrait_learning_queue
            WHERE fact_id=? ORDER BY queue_id
            """,
            (fact_id,),
        ).fetchall()
        return {
            "record_kind": "portrait_fact",
            "record_id": fact_id,
            "group_id": clean_text(group_id, 120),
            "guard_only": bool(guard_only),
            "person_id": clean_text(fact_data.get("person_id"), 80),
            "before": fact_data,
            "learning_queue": [dict(row) for row in queue_rows],
            "after_fingerprint": "",
            "after_queue_fingerprint": "",
        }

    def _write_portrait_fact_snapshot_sync(
        self, snapshot: dict[str, Any]
    ) -> bool:
        columns = (
            "id",
            "person_id",
            "dimension",
            "normalized_claim_hash",
            "claim_summary",
            "portrait_tier",
            "producer_kind",
            "producer_version",
            "derivation_kind",
            "epistemic_status",
            "source_scope",
            "usable_scope",
            "confidence",
            "sensitivity",
            "status",
            "evidence_hashes",
            "context_refs",
            "first_evidence_at",
            "last_evidence_at",
            "expires_at",
            "supersedes_id",
            "revision",
            "operation_id",
            "created_at",
            "updated_at",
        )
        if any(column not in snapshot for column in columns):
            return False
        names = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(
            f"{column}=excluded.{column}" for column in columns if column != "id"
        )
        self._conn.execute(
            f"""
            INSERT INTO portrait_facts ({names}) VALUES ({placeholders})
            ON CONFLICT(id) DO UPDATE SET {updates}
            """,
            [snapshot[column] for column in columns],
        )
        return True

    def _restore_portrait_queue_snapshot_sync(
        self, fact_id: str, rows: list[Any]
    ) -> bool:
        columns = (
            "queue_id",
            "person_id",
            "fact_id",
            "evidence_hash",
            "state",
            "created_at",
            "updated_at",
        )
        normalized: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, dict):
                return False
            row = dict(raw)
            if (
                any(column not in row for column in columns)
                or clean_text(row.get("fact_id"), 120) != fact_id
            ):
                return False
            normalized.append(row)
        self._conn.execute(
            "DELETE FROM portrait_learning_queue WHERE fact_id=?", (fact_id,)
        )
        for row in normalized:
            self._conn.execute(
                """
                INSERT INTO portrait_learning_queue(
                    queue_id, person_id, fact_id, evidence_hash, state,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                [row[column] for column in columns],
            )
        return True

    @staticmethod
    def _profile_repair_history(
        metadata: dict[str, Any],
        *,
        operation_id: str,
        action: str,
        reason: str,
        now: str,
    ) -> dict[str, Any]:
        updated = dict(metadata)
        history = updated.get("profile_repair_history")
        history = list(history) if isinstance(history, list) else []
        history.append(
            {
                "operation_id": operation_id,
                "action": action,
                "reason": clean_text(reason, 240),
                "applied_at": now,
            }
        )
        updated["profile_repair_history"] = history[-20:]
        return updated

    def _profile_repair_merge_sync(
        self,
        source: MemoryRecord,
        canonical: MemoryRecord,
        *,
        operation_id: str,
        reason: str,
        now: str,
    ) -> tuple[MemoryRecord, MemoryRecord] | None:
        source_metadata = source.metadata if isinstance(source.metadata, dict) else {}
        canonical_metadata = (
            canonical.metadata if isinstance(canonical.metadata, dict) else {}
        )
        if self._profile_domain(source) != self._profile_domain(canonical):
            return None
        source_dimension = clean_text(
            source_metadata.get("profile_dimension"), 80
        ).lower()
        canonical_dimension = clean_text(
            canonical_metadata.get("profile_dimension"), 80
        ).lower()
        source_value = clean_text(
            source_metadata.get("normalized_value"), 240
        ).casefold()
        canonical_value = clean_text(
            canonical_metadata.get("normalized_value"), 240
        ).casefold()
        source_polarity = clean_text(
            source_metadata.get("profile_polarity"), 40
        ).lower()
        canonical_polarity = clean_text(
            canonical_metadata.get("profile_polarity"), 40
        ).lower()
        if (
            not source_dimension
            or source_dimension != canonical_dimension
            or source_value != canonical_value
            or source_polarity != canonical_polarity
        ):
            return None

        refs = list(
            dict.fromkeys(
                [
                    *self._profile_evidence_refs(canonical),
                    *self._profile_evidence_refs(source),
                ]
            )
        )[:256]
        statement_fingerprints = list(
            dict.fromkeys(
                [
                    *self._profile_statement_fingerprints(canonical),
                    *self._profile_statement_fingerprints(source),
                ]
            )
        )[:256]
        next_state = (
            "active"
            if "active" in {self._profile_state(source), self._profile_state(canonical)}
            else "candidate"
        )
        merged_metadata = self._profile_repair_history(
            canonical_metadata,
            operation_id=operation_id,
            action="merge_target",
            reason=reason,
            now=now,
        )
        merged_metadata["profile_evidence_refs"] = refs
        merged_metadata["profile_statement_fingerprints"] = statement_fingerprints
        merged_metadata["evidence_count"] = len(refs)
        merged_metadata["independent_evidence_count"] = min(
            len(refs),
            len(statement_fingerprints),
        )
        merged_metadata["profile_state"] = next_state
        merged_metadata["profile_status"] = next_state
        canonical.metadata = merged_metadata
        canonical.evidence = self._profile_evidence_text([canonical, source])
        canonical.confidence = max(canonical.confidence, source.confidence)
        canonical.importance = max(canonical.importance, source.importance)
        canonical.merged_count = max(1, len(refs))
        canonical.lifecycle = "stable_memory" if next_state == "active" else "raw_event"
        canonical.review_status = "auto" if next_state == "active" else "pending"
        canonical.updated_at = now

        superseded_metadata = self._profile_repair_history(
            source_metadata,
            operation_id=operation_id,
            action="merge_source",
            reason=reason,
            now=now,
        )
        superseded_metadata["profile_state"] = "superseded"
        superseded_metadata["profile_status"] = "superseded"
        superseded_metadata["profile_superseded_by"] = canonical.id
        source.metadata = superseded_metadata
        source.lifecycle = "archived"
        source.review_status = "auto"
        source.supersedes_id = canonical.id
        source.updated_at = now
        return source, canonical

    async def apply_profile_repairs(
        self,
        *,
        operation_id: str,
        rule_version: str,
        actions: list[dict[str, Any]],
        backup_path: str,
    ) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(
            self._apply_profile_repairs_sync,
            operation_id,
            rule_version,
            deepcopy(actions),
            backup_path,
        )

    def _apply_profile_repairs_sync(
        self,
        operation_id: str,
        rule_version: str,
        actions: list[dict[str, Any]],
        backup_path: str,
    ) -> dict[str, Any]:
        operation_id = self._valid_profile_operation_id(operation_id)
        rule_version = clean_text(rule_version, 80)
        backup_path = clean_text(backup_path, 2000)
        if not operation_id or not rule_version or not backup_path:
            raise ValueError("profile repair operation metadata is invalid")
        if len(actions) > 100000:
            raise ValueError("profile repair action limit exceeded")
        plan_fingerprint = self.profile_repair_plan_fingerprint(actions)
        now = utc_now()

        with self._lock:  # noqa: SIM117
            with self._transaction_sync():
                prior = self._conn.execute(
                    "SELECT * FROM profile_repair_operations WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                if prior is not None:
                    if (
                        clean_text(prior["rule_version"], 80) != rule_version
                        or clean_text(prior["plan_fingerprint"], 80) != plan_fingerprint
                    ):
                        raise ValueError(
                            "profile repair operation id already used with a different plan"
                        )
                    if clean_text(prior["state"], 40) == "rolled_back":
                        raise ValueError(
                            "profile repair operation has already been rolled back"
                        )
                    result = json_loads(prior["result"], {})
                    return {
                        **(result if isinstance(result, dict) else {}),
                        "ok": True,
                        "code": "profile_repair_idempotent_replay",
                        "operation_id": operation_id,
                    }

                snapshots: dict[str, dict[str, Any]] = {}
                validated_targets: set[str] = set()
                validated_portrait_targets: set[str] = set()
                changed_ids: set[str] = set()
                affected_portrait_people: set[str] = set()
                results: list[dict[str, Any]] = []
                for raw_action in actions:
                    if not isinstance(raw_action, dict):
                        continue
                    record_kind = clean_text(
                        raw_action.get("record_kind"), 32
                    ).lower() or "memory"
                    memory_id = clean_text(
                        raw_action.get("record_id")
                        or raw_action.get("memory_id"),
                        120,
                    )
                    action = clean_text(raw_action.get("action"), 24).lower()
                    reason = clean_text(raw_action.get("reason"), 240)
                    if record_kind == "portrait_fact":
                        portrait_key = f"portrait_fact:{memory_id}"
                        fact_row = self._conn.execute(
                            "SELECT * FROM portrait_facts WHERE id=?",
                            (memory_id,),
                        ).fetchone()
                        if fact_row is None:
                            results.append(
                                {
                                    "record_kind": record_kind,
                                    "record_id": memory_id,
                                    "status": "missing",
                                }
                            )
                            continue
                        fact = dict(fact_row)
                        if (
                            clean_text(fact.get("producer_kind"), 80)
                            != "rule_explicit"
                            or clean_text(fact.get("producer_version"), 80)
                            not in self.PROFILE_RULE_PORTRAIT_VERSIONS
                        ):
                            results.append(
                                {
                                    "record_kind": record_kind,
                                    "record_id": memory_id,
                                    "status": "unsupported",
                                }
                            )
                            continue
                        expected = clean_text(
                            raw_action.get("expected_fingerprint"), 80
                        )
                        queue_rows = self._conn.execute(
                            """
                            SELECT * FROM portrait_learning_queue
                            WHERE fact_id=? ORDER BY queue_id
                            """,
                            (memory_id,),
                        ).fetchall()
                        expected_queue = clean_text(
                            raw_action.get("expected_queue_fingerprint"), 80
                        )
                        if (
                            not expected
                            or self.profile_portrait_fact_fingerprint(fact)
                            != expected
                            or (
                                expected_queue
                                and self.profile_portrait_queue_fingerprint(
                                    queue_rows
                                )
                                != expected_queue
                            )
                        ):
                            results.append(
                                {
                                    "record_kind": record_kind,
                                    "record_id": memory_id,
                                    "status": "skip-stale",
                                }
                            )
                            continue
                        if action == "keep":
                            results.append(
                                {
                                    "record_kind": record_kind,
                                    "record_id": memory_id,
                                    "status": "kept",
                                }
                            )
                            continue
                        if action not in {"pending", "archive"}:
                            results.append(
                                {
                                    "record_kind": record_kind,
                                    "record_id": memory_id,
                                    "status": "invalid-action",
                                }
                            )
                            continue
                        snapshots.setdefault(
                            portrait_key,
                            self._profile_repair_portrait_snapshot_sync(
                                fact,
                                group_id=self.profile_repair_group_id(memory_id),
                            ),
                        )
                        target_state = "pending"
                        canonical_id = ""
                        queue_state = "pending_review"
                        if action == "archive":
                            target_state = clean_text(
                                raw_action.get("target_state"), 32
                            ).lower()
                            if target_state not in {"rejected", "superseded"}:
                                target_state = "rejected"
                            queue_state = target_state
                        if target_state == "superseded":
                            canonical_id = clean_text(
                                raw_action.get("canonical_id"), 120
                            )
                            group_id = self.profile_repair_group_id(canonical_id)
                            snapshots[portrait_key]["group_id"] = group_id
                            canonical_row = self._conn.execute(
                                "SELECT * FROM portrait_facts WHERE id=?",
                                (canonical_id,),
                            ).fetchone()
                            if canonical_row is None or canonical_id == memory_id:
                                results.append(
                                    {
                                        "record_kind": record_kind,
                                        "record_id": memory_id,
                                        "status": "invalid-canonical",
                                    }
                                )
                                continue
                            canonical = dict(canonical_row)
                            canonical_queue = self._conn.execute(
                                """
                                SELECT * FROM portrait_learning_queue
                                WHERE fact_id=? ORDER BY queue_id
                                """,
                                (canonical_id,),
                            ).fetchall()
                            if canonical_id not in validated_portrait_targets:
                                canonical_expected = clean_text(
                                    raw_action.get(
                                        "canonical_expected_fingerprint"
                                    ),
                                    80,
                                )
                                canonical_queue_expected = clean_text(
                                    raw_action.get(
                                        "canonical_expected_queue_fingerprint"
                                    ),
                                    80,
                                )
                                if (
                                    not canonical_expected
                                    or self.profile_portrait_fact_fingerprint(
                                        canonical
                                    )
                                    != canonical_expected
                                    or (
                                        canonical_queue_expected
                                        and self.profile_portrait_queue_fingerprint(
                                            canonical_queue
                                        )
                                        != canonical_queue_expected
                                    )
                                ):
                                    results.append(
                                        {
                                            "record_kind": record_kind,
                                            "record_id": memory_id,
                                            "status": "skip-stale",
                                        }
                                    )
                                    continue
                                validated_portrait_targets.add(canonical_id)
                            if (
                                clean_text(fact.get("person_id"), 80)
                                != clean_text(canonical.get("person_id"), 80)
                                or clean_text(fact.get("dimension"), 80).lower()
                                != clean_text(
                                    canonical.get("dimension"), 80
                                ).lower()
                                or clean_text(fact.get("source_scope"), 80)
                                != clean_text(
                                    canonical.get("source_scope"), 80
                                )
                                or clean_text(canonical.get("status"), 40)
                                != "active"
                            ):
                                results.append(
                                    {
                                        "record_kind": record_kind,
                                        "record_id": memory_id,
                                        "status": "acl-domain-mismatch",
                                    }
                                )
                                continue
                            canonical_key = f"portrait_fact:{canonical_id}"
                            snapshots.setdefault(
                                canonical_key,
                                self._profile_repair_portrait_snapshot_sync(
                                    canonical,
                                    group_id=group_id,
                                    guard_only=True,
                                ),
                            )
                            snapshots[canonical_key]["group_id"] = group_id

                        self._conn.execute(
                            """
                            UPDATE portrait_facts
                            SET status=?, supersedes_id=?, revision=revision+1,
                                operation_id=?, updated_at=?
                            WHERE id=?
                            """,
                            (
                                target_state,
                                canonical_id,
                                operation_id,
                                now,
                                memory_id,
                            ),
                        )
                        self._conn.execute(
                            """
                            UPDATE portrait_learning_queue
                            SET state=?, updated_at=?
                            WHERE fact_id=? AND state='pending'
                            """,
                            (queue_state, now, memory_id),
                        )
                        person_id = clean_text(fact.get("person_id"), 80)
                        if person_id:
                            affected_portrait_people.add(person_id)
                        changed_ids.add(portrait_key)
                        results.append(
                            {
                                "record_kind": record_kind,
                                "record_id": memory_id,
                                "status": "applied",
                                "action": action,
                                "canonical_id": canonical_id,
                            }
                        )
                        continue
                    if record_kind != "memory":
                        results.append(
                            {
                                "record_kind": record_kind,
                                "record_id": memory_id,
                                "memory_id": memory_id,
                                "status": "unsupported",
                            }
                        )
                        continue
                    row = self._conn.execute(
                        "SELECT * FROM memories WHERE id=?", (memory_id,)
                    ).fetchone()
                    if row is None:
                        results.append({"memory_id": memory_id, "status": "missing"})
                        continue
                    current = MemoryRecord.from_row(row)
                    metadata = (
                        current.metadata if isinstance(current.metadata, dict) else {}
                    )
                    if (
                        current.memory_type not in self.PROFILE_MEMORY_TYPES
                        or clean_text(metadata.get("extractor"), 40).lower()
                        not in self.PROFILE_RULE_EXTRACTORS
                    ):
                        results.append(
                            {"memory_id": memory_id, "status": "unsupported"}
                        )
                        continue
                    expected = clean_text(raw_action.get("expected_fingerprint"), 80)
                    if (
                        not expected
                        or self.profile_memory_fingerprint(current) != expected
                    ):
                        results.append({"memory_id": memory_id, "status": "skip-stale"})
                        continue
                    if action == "keep":
                        results.append({"memory_id": memory_id, "status": "kept"})
                        continue
                    if action not in {"pending", "archive", "merge"}:
                        results.append(
                            {"memory_id": memory_id, "status": "invalid-action"}
                        )
                        continue
                    snapshots.setdefault(
                        memory_id,
                        self._profile_repair_record_snapshot_sync(
                            current,
                            group_id=self.profile_repair_group_id(memory_id),
                        ),
                    )

                    records_to_write: list[MemoryRecord] = []
                    if action == "merge":
                        canonical_id = clean_text(raw_action.get("canonical_id"), 120)
                        group_id = self.profile_repair_group_id(canonical_id)
                        snapshots[memory_id]["group_id"] = group_id
                        canonical_row = self._conn.execute(
                            "SELECT * FROM memories WHERE id=?",
                            (canonical_id,),
                        ).fetchone()
                        if canonical_row is None or canonical_id == memory_id:
                            results.append(
                                {"memory_id": memory_id, "status": "invalid-canonical"}
                            )
                            continue
                        canonical = MemoryRecord.from_row(canonical_row)
                        if canonical_id not in validated_targets:
                            canonical_expected = clean_text(
                                raw_action.get("canonical_expected_fingerprint"),
                                80,
                            )
                            if (
                                not canonical_expected
                                or self.profile_memory_fingerprint(canonical)
                                != canonical_expected
                            ):
                                results.append(
                                    {"memory_id": memory_id, "status": "skip-stale"}
                                )
                                continue
                            validated_targets.add(canonical_id)
                            snapshots.setdefault(
                                canonical_id,
                                self._profile_repair_record_snapshot_sync(
                                    canonical,
                                    group_id=group_id,
                                ),
                            )
                        snapshots[canonical_id]["group_id"] = group_id
                        merged = self._profile_repair_merge_sync(
                            current,
                            canonical,
                            operation_id=operation_id,
                            reason=reason,
                            now=now,
                        )
                        if merged is None:
                            results.append(
                                {
                                    "memory_id": memory_id,
                                    "status": "acl-domain-mismatch",
                                }
                            )
                            continue
                        records_to_write.extend(merged)
                    else:
                        metadata_patch = raw_action.get("metadata_patch")
                        if isinstance(metadata_patch, dict):
                            allowed_patch_keys = {
                                "profile_dimension",
                                "profile_value",
                                "normalized_value",
                                "profile_polarity",
                                "profile_cardinality",
                                "extraction_quality",
                                "extraction_quality_score",
                                "evidence_strength",
                                "quality_gate_passed",
                            }
                            metadata = {
                                **metadata,
                                **{
                                    key: value
                                    for key, value in metadata_patch.items()
                                    if key in allowed_patch_keys
                                },
                            }
                        next_metadata = self._profile_repair_history(
                            metadata,
                            operation_id=operation_id,
                            action=action,
                            reason=reason,
                            now=now,
                        )
                        if action == "pending":
                            next_metadata["profile_state"] = "candidate"
                            next_metadata["profile_status"] = "candidate"
                            current.lifecycle = "raw_event"
                            current.review_status = "pending"
                        else:
                            target_state = clean_text(
                                raw_action.get("target_state"),
                                32,
                            ).lower()
                            if target_state not in {"rejected", "superseded"}:
                                target_state = "rejected"
                            if target_state == "superseded":
                                canonical_id = clean_text(
                                    raw_action.get("canonical_id"),
                                    120,
                                )
                                group_id = self.profile_repair_group_id(canonical_id)
                                snapshots[memory_id]["group_id"] = group_id
                                canonical_row = self._conn.execute(
                                    "SELECT * FROM memories WHERE id=?",
                                    (canonical_id,),
                                ).fetchone()
                                if canonical_row is None or canonical_id == memory_id:
                                    results.append(
                                        {
                                            "memory_id": memory_id,
                                            "status": "invalid-canonical",
                                        }
                                    )
                                    continue
                                canonical = MemoryRecord.from_row(canonical_row)
                                if canonical_id not in validated_targets:
                                    canonical_expected = clean_text(
                                        raw_action.get(
                                            "canonical_expected_fingerprint"
                                        ),
                                        80,
                                    )
                                    if (
                                        not canonical_expected
                                        or self.profile_memory_fingerprint(canonical)
                                        != canonical_expected
                                    ):
                                        results.append(
                                            {
                                                "memory_id": memory_id,
                                                "status": "skip-stale",
                                            }
                                        )
                                        continue
                                    validated_targets.add(canonical_id)
                                snapshots.setdefault(
                                    canonical_id,
                                    self._profile_repair_record_snapshot_sync(
                                        canonical,
                                        group_id=group_id,
                                        guard_only=True,
                                    ),
                                )
                                snapshots[canonical_id]["group_id"] = group_id
                                canonical_metadata = (
                                    canonical.metadata
                                    if isinstance(canonical.metadata, dict)
                                    else {}
                                )
                                if (
                                    self._profile_domain(current)
                                    != self._profile_domain(canonical)
                                    or clean_text(
                                        metadata.get("profile_dimension"),
                                        80,
                                    ).lower()
                                    != clean_text(
                                        canonical_metadata.get("profile_dimension"),
                                        80,
                                    ).lower()
                                    or self._profile_state(canonical) != "active"
                                ):
                                    results.append(
                                        {
                                            "memory_id": memory_id,
                                            "status": "acl-domain-mismatch",
                                        }
                                    )
                                    continue
                            next_metadata["profile_state"] = target_state
                            next_metadata["profile_status"] = target_state
                            next_metadata["profile_archive_reason"] = reason
                            current.lifecycle = "archived"
                            current.review_status = "auto"
                            if target_state == "superseded":
                                current.supersedes_id = canonical_id
                                next_metadata["profile_superseded_by"] = (
                                    current.supersedes_id
                                )
                        current.metadata = next_metadata
                        current.updated_at = now
                        records_to_write.append(current)

                    for changed in records_to_write:
                        self._write_memory_record_sync(changed)
                        self._conn.execute(
                            "DELETE FROM memory_embeddings WHERE memory_id=?",
                            (changed.id,),
                        )
                        if changed.review_status == "pending":
                            self._upsert_review_sync(
                                changed.id,
                                "profile_repair_pending",
                            )
                        else:
                            self._conn.execute(
                                "UPDATE review_queue SET status=?, updated_at=? WHERE memory_id=? AND status='pending'",
                                (
                                    "superseded" if changed.supersedes_id else "auto",
                                    now,
                                    changed.id,
                                ),
                            )
                        changed_ids.add(changed.id)
                    results.append(
                        {
                            "memory_id": memory_id,
                            "status": "applied",
                            "action": action,
                            "canonical_id": clean_text(
                                raw_action.get("canonical_id"), 120
                            ),
                        }
                    )

                for person_id in sorted(affected_portrait_people):
                    self._bump_portrait_revision_sync(person_id)
                for snapshot in snapshots.values():
                    record_kind = clean_text(
                        snapshot.get("record_kind"), 32
                    ).lower() or "memory"
                    record_id = clean_text(
                        snapshot.get("record_id")
                        or snapshot.get("memory_id"),
                        120,
                    )
                    if record_kind == "portrait_fact":
                        row = self._conn.execute(
                            "SELECT * FROM portrait_facts WHERE id=?",
                            (record_id,),
                        ).fetchone()
                        if row is not None:
                            snapshot["after_fingerprint"] = (
                                self.profile_portrait_fact_fingerprint(row)
                            )
                            queue_rows = self._conn.execute(
                                """
                                SELECT * FROM portrait_learning_queue
                                WHERE fact_id=? ORDER BY queue_id
                                """,
                                (record_id,),
                            ).fetchall()
                            snapshot["after_queue_fingerprint"] = (
                                self.profile_portrait_queue_fingerprint(
                                    queue_rows
                                )
                            )
                        continue
                    row = self._conn.execute(
                        "SELECT * FROM memories WHERE id=?", (record_id,)
                    ).fetchone()
                    if row is not None:
                        snapshot["after_fingerprint"] = self.profile_memory_fingerprint(
                            MemoryRecord.from_row(row)
                        )
                snapshot_payload = {
                    "schema_version": "profile.repair.snapshot.v2",
                    "records": list(snapshots.values()),
                }
                stale_count = sum(
                    1 for item in results if item.get("status") == "skip-stale"
                )
                result = {
                    "ok": True,
                    "code": "profile_repair_applied",
                    "operation_id": operation_id,
                    "rule_version": rule_version,
                    "plan_fingerprint": plan_fingerprint,
                    "backup_path": backup_path,
                    "results": results,
                    "changed": len(changed_ids),
                    "stale": stale_count,
                }
                state = (
                    "partial"
                    if any(
                        item.get("status")
                        in {
                            "skip-stale",
                            "missing",
                            "unsupported",
                            "invalid-action",
                            "invalid-canonical",
                            "acl-domain-mismatch",
                        }
                        for item in results
                    )
                    else "applied"
                )
                self._conn.execute(
                    """
                    INSERT INTO profile_repair_operations(
                        operation_id, rule_version, state, backup_path, plan_fingerprint,
                        snapshot, result, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        operation_id,
                        rule_version,
                        state,
                        backup_path,
                        plan_fingerprint,
                        json_dumps(snapshot_payload),
                        json_dumps(result),
                        now,
                        now,
                    ),
                )
                self._embedding_candidate_cache.clear()
                self._embedding_candidate_cache_revision = ""
        return result

    async def get_profile_repair_operation(
        self, operation_id: str
    ) -> dict[str, Any] | None:
        return await self._run_recoverable_database_operation(
            self._get_profile_repair_operation_sync,
            operation_id,
        )

    def _get_profile_repair_operation_sync(
        self, operation_id: str
    ) -> dict[str, Any] | None:
        operation_id = self._valid_profile_operation_id(operation_id)
        if not operation_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM profile_repair_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["snapshot"] = json_loads(result.get("snapshot"), {})
        result["result"] = json_loads(result.get("result"), {})
        return result

    async def rollback_profile_repairs(
        self,
        *,
        operation_id: str,
        rollback_backup_path: str = "",
    ) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(
            self._rollback_profile_repairs_sync,
            operation_id,
            rollback_backup_path,
        )

    def _rollback_profile_repairs_sync(
        self,
        operation_id: str,
        rollback_backup_path: str,
    ) -> dict[str, Any]:
        operation_id = self._valid_profile_operation_id(operation_id)
        if not operation_id:
            raise ValueError("invalid profile repair operation id")
        now = utc_now()
        with self._lock:  # noqa: SIM117
            with self._transaction_sync():
                operation = self._conn.execute(
                    "SELECT * FROM profile_repair_operations WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                if operation is None:
                    raise ValueError("profile repair operation not found")
                if clean_text(operation["state"], 40) == "rolled_back":
                    previous = json_loads(operation["result"], {})
                    return {
                        **(previous if isinstance(previous, dict) else {}),
                        "ok": True,
                        "code": "profile_repair_rollback_idempotent",
                        "operation_id": operation_id,
                    }
                if clean_text(operation["state"], 40) not in {"applied", "partial"}:
                    raise ValueError("profile repair operation is not rollbackable")
                snapshot = json_loads(operation["snapshot"], {})
                records = snapshot.get("records") if isinstance(snapshot, dict) else []
                records = records if isinstance(records, list) else []
                results: list[dict[str, Any]] = []
                groups: dict[str, list[dict[str, Any]]] = {}
                for index, item in enumerate(records):
                    if not isinstance(item, dict):
                        continue
                    record_kind = clean_text(
                        item.get("record_kind"), 32
                    ).lower() or "memory"
                    record_id = clean_text(
                        item.get("record_id") or item.get("memory_id"), 120
                    )
                    group_id = clean_text(item.get("group_id"), 120)
                    if not group_id:
                        group_id = f"legacy:{record_kind}:{record_id}:{index}"
                    groups.setdefault(group_id, []).append(item)

                restored_portrait_people: set[str] = set()
                for group_id, group in groups.items():
                    prepared: list[dict[str, Any]] = []
                    failures: dict[tuple[str, str], str] = {}
                    for item in group:
                        record_kind = clean_text(
                            item.get("record_kind"), 32
                        ).lower() or "memory"
                        record_id = clean_text(
                            item.get("record_id") or item.get("memory_id"), 120
                        )
                        failure_key = (record_kind, record_id)
                        before = (
                            item.get("before")
                            if isinstance(item.get("before"), dict)
                            else {}
                        )
                        if record_kind == "portrait_fact":
                            row = self._conn.execute(
                                "SELECT * FROM portrait_facts WHERE id=?",
                                (record_id,),
                            ).fetchone()
                            if row is None:
                                failures[failure_key] = "missing"
                                continue
                            queue_rows = self._conn.execute(
                                """
                                SELECT * FROM portrait_learning_queue
                                WHERE fact_id=? ORDER BY queue_id
                                """,
                                (record_id,),
                            ).fetchall()
                            if (
                                self.profile_portrait_fact_fingerprint(row)
                                != clean_text(
                                    item.get("after_fingerprint"), 80
                                )
                                or self.profile_portrait_queue_fingerprint(
                                    queue_rows
                                )
                                != clean_text(
                                    item.get("after_queue_fingerprint"), 80
                                )
                            ):
                                failures[failure_key] = "skip-stale"
                                continue
                            queue_snapshot = item.get("learning_queue")
                            if (
                                clean_text(before.get("id"), 120) != record_id
                                or not isinstance(queue_snapshot, list)
                                or any(
                                    not isinstance(queue_item, dict)
                                    or clean_text(
                                        queue_item.get("fact_id"), 120
                                    )
                                    != record_id
                                    for queue_item in queue_snapshot
                                )
                            ):
                                failures[failure_key] = "invalid-snapshot"
                                continue
                            prepared.append(
                                {
                                    "item": item,
                                    "record_kind": record_kind,
                                    "record_id": record_id,
                                    "restored": before,
                                }
                            )
                            continue
                        if record_kind != "memory":
                            failures[failure_key] = "invalid-snapshot"
                            continue
                        row = self._conn.execute(
                            "SELECT * FROM memories WHERE id=?", (record_id,)
                        ).fetchone()
                        if row is None:
                            failures[failure_key] = "missing"
                            continue
                        current = MemoryRecord.from_row(row)
                        if self.profile_memory_fingerprint(current) != clean_text(
                            item.get("after_fingerprint"), 80
                        ):
                            failures[failure_key] = "skip-stale"
                            continue
                        try:
                            restored = self._memory_from_db_snapshot(before)
                        except (KeyError, TypeError, ValueError):
                            failures[failure_key] = "invalid-snapshot"
                            continue
                        prepared.append(
                            {
                                "item": item,
                                "record_kind": record_kind,
                                "record_id": record_id,
                                "restored": restored,
                            }
                        )

                    if failures:
                        for item in group:
                            record_kind = clean_text(
                                item.get("record_kind"), 32
                            ).lower() or "memory"
                            record_id = clean_text(
                                item.get("record_id")
                                or item.get("memory_id"),
                                120,
                            )
                            result_item = {
                                "record_kind": record_kind,
                                "record_id": record_id,
                                "group_id": group_id,
                                "status": failures.get(
                                    (record_kind, record_id),
                                    "skip-group-stale",
                                ),
                            }
                            if record_kind == "memory":
                                result_item["memory_id"] = record_id
                            results.append(result_item)
                        continue

                    for prepared_item in prepared:
                        item = prepared_item["item"]
                        record_kind = prepared_item["record_kind"]
                        record_id = prepared_item["record_id"]
                        result_item = {
                            "record_kind": record_kind,
                            "record_id": record_id,
                            "group_id": group_id,
                        }
                        if record_kind == "memory":
                            result_item["memory_id"] = record_id
                        if bool(item.get("guard_only")):
                            result_item["status"] = "guard-verified"
                            results.append(result_item)
                            continue
                        if record_kind == "portrait_fact":
                            restored_fact = prepared_item["restored"]
                            if not self._write_portrait_fact_snapshot_sync(
                                restored_fact
                            ) or not self._restore_portrait_queue_snapshot_sync(
                                record_id, item.get("learning_queue", [])
                            ):
                                raise ValueError(
                                    "invalid portrait repair snapshot"
                                )
                            person_id = clean_text(
                                restored_fact.get("person_id"), 80
                            )
                            if person_id:
                                restored_portrait_people.add(person_id)
                            result_item["status"] = "rolled-back"
                            results.append(result_item)
                            continue

                        restored = prepared_item["restored"]
                        self._write_memory_record_sync(restored)
                        self._conn.execute(
                            "DELETE FROM review_queue WHERE memory_id=?",
                            (record_id,),
                        )
                        for review in item.get("review_queue", []):
                            if not isinstance(review, dict):
                                continue
                            self._conn.execute(
                                """
                                INSERT INTO review_queue(id, memory_id, reason, status, created_at, updated_at)
                                VALUES(?,?,?,?,?,?)
                                """,
                                (
                                    clean_text(review.get("id"), 120),
                                    record_id,
                                    clean_text(review.get("reason"), 500),
                                    clean_text(review.get("status"), 40),
                                    clean_text(review.get("created_at"), 80),
                                    clean_text(review.get("updated_at"), 80),
                                ),
                            )
                        self._conn.execute(
                            "DELETE FROM memory_embeddings WHERE memory_id=?",
                            (record_id,),
                        )
                        for embedding in item.get("embeddings", []):
                            if not isinstance(embedding, dict):
                                continue
                            self._conn.execute(
                                """
                                INSERT INTO memory_embeddings(
                                    memory_id, provider_id, text_hash, dimension, vector, created_at, updated_at
                                ) VALUES(?,?,?,?,?,?,?)
                                """,
                                (
                                    record_id,
                                    clean_text(embedding.get("provider_id"), 160),
                                    clean_text(embedding.get("text_hash"), 80),
                                    max(0, int(embedding.get("dimension") or 0)),
                                    clean_text(embedding.get("vector"), 100000),
                                    clean_text(embedding.get("created_at"), 80),
                                    clean_text(embedding.get("updated_at"), 80),
                                ),
                            )
                        result_item["status"] = "rolled-back"
                        results.append(result_item)

                for person_id in sorted(restored_portrait_people):
                    self._bump_portrait_revision_sync(person_id)

                rolled_back = sum(
                    1 for item in results if item.get("status") == "rolled-back"
                )
                stale = sum(
                    1
                    for item in results
                    if item.get("status")
                    in {
                        "skip-stale",
                        "skip-group-stale",
                        "missing",
                        "invalid-snapshot",
                    }
                )
                guards = sum(
                    1 for item in results if item.get("status") == "guard-verified"
                )
                previous_result = json_loads(operation["result"], {})
                result = (
                    dict(previous_result) if isinstance(previous_result, dict) else {}
                )
                result.update(
                    {
                        "ok": True,
                        "code": "profile_repair_rolled_back",
                        "operation_id": operation_id,
                        "rollback_backup_path": clean_text(rollback_backup_path, 2000),
                        "rollback_results": results,
                        "rolled_back": rolled_back,
                        "rollback_stale": stale,
                    }
                )
                state = (
                    "rolled_back"
                    if rolled_back + guards == len(results) and stale == 0
                    else "partial"
                )
                self._conn.execute(
                    "UPDATE profile_repair_operations SET state=?, result=?, updated_at=? WHERE operation_id=?",
                    (state, json_dumps(result), now, operation_id),
                )
                self._embedding_candidate_cache.clear()
                self._embedding_candidate_cache_revision = ""
        return result

    @staticmethod
    def _memory_atom_record_for_row(
        row: sqlite3.Row,
        *,
        reset_semantic_keys: bool = False,
        **changes: Any,
    ) -> MemoryRecord:
        payload = dict(row)
        payload.update(changes)
        if reset_semantic_keys:
            payload["canonical_key"] = ""
            payload["content_fingerprint"] = ""
        return MemoryRecord.from_row(payload)

    async def insert_memory(self, record: MemoryRecord, review_reason: str = "") -> str:
        return await self._run_recoverable_database_operation(
            self._insert_memory_sync,
            record,
            review_reason,
        )

    def _insert_memory_sync(
        self,
        record: MemoryRecord,
        review_reason: str = "",
        _commit: bool = True,
    ) -> str:
        # _commit=False 用于批量写链：由外层事务统一提交，避免逐次 fsync。
        record.ensure_defaults()
        data = record.to_db()
        columns = ", ".join(data.keys())
        placeholders = ", ".join(f":{key}" for key in data.keys())
        updates = ", ".join(f"{key}=excluded.{key}" for key in data.keys() if key != "id")
        with self._lock:
            duplicate = None
            if record.content_fingerprint:
                duplicate = self._conn.execute(
                    """
                    SELECT id, importance, confidence, merged_count, evidence, metadata
                    FROM memories
                    WHERE content_fingerprint=? AND id<>? AND lifecycle!='archived'
                    ORDER BY merged_count DESC, updated_at DESC
                    LIMIT 1
                    """,
                    (record.content_fingerprint, record.id),
                ).fetchone()
            if duplicate:
                merged_metadata = json_loads(duplicate["metadata"], {})
                incoming_metadata = record.metadata if isinstance(record.metadata, dict) else {}
                merged_metadata.setdefault("merged_from", [])
                merged_from = merged_metadata.get("merged_from")
                if isinstance(merged_from, list) and record.id not in merged_from:
                    merged_from.append(record.id)
                merged_metadata["last_merge_source"] = record.source_plugin
                for key, value in incoming_metadata.items():
                    if key in {
                        "persona_importance",
                        "relationship_weight",
                        "emotional_weight",
                        "promise_weight",
                        "open_loop_weight",
                        "creative_weight",
                        "preference_weight",
                        "self_continuity_weight",
                        "freshness_weight",
                        "scar_weight",
                        "emotional_debt_weight",
                    }:
                        try:
                            merged_metadata[key] = max(float(merged_metadata.get(key) or 0.0), float(value or 0.0))
                        except Exception:
                            merged_metadata.setdefault(key, value)
                    elif key in {
                        "memory_reason",
                        "relationship_phase",
                        "decay_mode",
                        "last_emotional_touch_at",
                        "importance_evaluator",
                        "importance_source",
                    }:
                        if value:
                            merged_metadata[key] = value
                    elif key == "mention_policy":
                        incoming_policy = clean_text(value, 60)
                        existing_policy = clean_text(merged_metadata.get(key), 60)
                        policy_rank = {
                            "direct": 0,
                            "soft_echo": 1,
                            "tone_only": 2,
                            "avoid_unless_asked": 3,
                        }
                        if incoming_policy and policy_rank.get(incoming_policy, 1) > policy_rank.get(existing_policy, -1):
                            merged_metadata[key] = incoming_policy
                    elif key == "mentionability_score":
                        try:
                            incoming_score = float(value or 0.5)
                            existing_score = float(merged_metadata.get(key, 0.5) or 0.5)
                            merged_metadata[key] = round(min(incoming_score, existing_score), 3)
                        except Exception:
                            merged_metadata.setdefault(key, value)
                    elif key == "mention_policy_source":
                        merged_metadata.setdefault(key, value)
                    elif key == "persona_dimensions" and isinstance(value, list):
                        old_dimensions = merged_metadata.get("persona_dimensions")
                        if not isinstance(old_dimensions, list):
                            old_dimensions = []
                        merged_metadata[key] = list(dict.fromkeys([*old_dimensions, *value]))
                evidence = duplicate["evidence"] or record.evidence
                if record.evidence and record.evidence not in evidence:
                    evidence = clean_text(f"{evidence}\n---\n{record.evidence}", 4000)
                self._conn.execute(
                    """
                    UPDATE memories
                    SET importance=max(importance, ?),
                        confidence=max(confidence, ?),
                        evidence=?,
                        metadata=?,
                        merged_count=COALESCE(merged_count, 1) + 1,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        record.importance,
                        record.confidence,
                        evidence,
                        json_dumps(merged_metadata),
                        utc_now(),
                        duplicate["id"],
                    ),
                )
                row = self._conn.execute("SELECT * FROM memories WHERE id=?", (duplicate["id"],)).fetchone()
                self._upsert_memory_fts_row(row)
                if _commit:
                    self._conn.commit()
                return str(duplicate["id"])
            self._conn.execute(
                f"INSERT INTO memories ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                data,
            )
            if record.review_status == "pending" or review_reason:
                self._upsert_review_sync(record.id, review_reason or "待人工确认")
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (record.id,)).fetchone()
            self._upsert_memory_fts_row(row)
            if _commit:
                self._conn.commit()
        return record.id

    def _upsert_review_sync(self, memory_id: str, reason: str) -> None:
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO review_queue(id, memory_id, reason, status, created_at, updated_at)
            VALUES(:id, :memory_id, :reason, 'pending', :created_at, :updated_at)
            ON CONFLICT(memory_id, reason) DO UPDATE SET updated_at=excluded.updated_at
            """,
            {
                "id": new_id("review"),
                "memory_id": memory_id,
                "reason": clean_text(reason, 500),
                "created_at": now,
                "updated_at": now,
            },
        )

    async def upsert_identity(
        self,
        *,
        platform: str,
        entity: EntityRef,
        aliases: list[str] | None = None,
        profile: dict[str, Any] | None = None,
        confidence: float = 0.6,
    ) -> str:
        return await asyncio.to_thread(
            self._upsert_identity_sync,
            platform,
            entity,
            aliases or [],
            profile or {},
            confidence,
        )

    async def upsert_identities(
        self, identities: list[dict[str, Any]]
    ) -> list[str]:
        """批量写入多条身份记录，合并为单事务提交（减少独立 commit）。"""
        return await asyncio.to_thread(self._upsert_identities_sync, identities)

    def _upsert_identity_row_locked(
        self,
        platform: str,
        entity: EntityRef,
        aliases: list[str],
        profile: dict[str, Any],
        confidence: float,
    ) -> str:
        """写入单行身份记录；调用方须已持有 ``self._lock`` 且处于事务中。"""
        now = utc_now()
        entity_id = clean_text(entity.id, 120)
        if not entity_id:
            entity_id = "unknown"
        row_id = f"{platform or 'unknown'}:{entity.kind}:{entity_id}"
        aliases = [clean_text(alias, 80) for alias in aliases if clean_text(alias, 80)]
        if entity.name and entity.name not in aliases:
            aliases.append(entity.name)
        old = self._conn.execute(
            "SELECT aliases, profile, created_at FROM identities WHERE id=?",
            (row_id,),
        ).fetchone()
        created_at = now
        if old:
            created_at = old["created_at"] or now
            merged_aliases = list(dict.fromkeys(json_loads(old["aliases"], []) + aliases))
            merged_profile = json_loads(old["profile"], {})
            merged_profile.update(profile)
        else:
            merged_aliases = aliases
            merged_profile = profile
        self._conn.execute(
            """
            INSERT INTO identities(
                id, platform, entity_kind, entity_id, display_name, role, aliases,
                profile, confidence, created_at, updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(platform, entity_kind, entity_id) DO UPDATE SET
                display_name=excluded.display_name,
                role=excluded.role,
                aliases=excluded.aliases,
                profile=excluded.profile,
                confidence=max(identities.confidence, excluded.confidence),
                updated_at=excluded.updated_at
            """,
            (
                row_id,
                platform,
                entity.kind,
                entity_id,
                clean_text(entity.name, 80),
                clean_text(entity.role, 80),
                json_dumps(merged_aliases),
                json_dumps(merged_profile),
                confidence,
                created_at,
                now,
            ),
        )
        return row_id

    def _upsert_identity_sync(
        self,
        platform: str,
        entity: EntityRef,
        aliases: list[str],
        profile: dict[str, Any],
        confidence: float,
    ) -> str:
        with self._lock:
            row_id = self._upsert_identity_row_locked(
                platform, entity, aliases, profile, confidence
            )
            self._conn.commit()
        return row_id

    def _upsert_identities_sync(
        self, identities: list[dict[str, Any]]
    ) -> list[str]:
        """批量身份写入：单事务（BEGIN IMMEDIATE + 一次 commit）。"""
        if not identities:
            return []
        with self._lock:
            with self._transaction_sync():
                return [
                    self._upsert_identity_row_locked(**identity)
                    for identity in identities
                ]

    async def list_identities(self, limit: int = 1000, *, offset: int = 0) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_identities_sync, limit, offset)

    def _list_identities_sync(self, limit: int, offset: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM identities ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (max(1, int(limit)), max(0, int(offset))),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["aliases"] = json_loads(item.get("aliases"), [])
            item["profile"] = json_loads(item.get("profile"), {})
            result.append(item)
        return result

    async def upsert_relationship(
        self,
        *,
        subject: EntityRef,
        object: EntityRef,
        relation_type: str,
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
        visibility: str = "internal",
        evidence: str = "",
        confidence: float = 0.6,
        review_status: str = "auto",
        source_memory_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return await self._run_tracked_operation(
            self._upsert_relationship_sync,
            subject,
            object,
            relation_type,
            scope,
            session_id,
            group_id,
            visibility,
            evidence,
            confidence,
            review_status,
            source_memory_id,
            metadata or {},
            closed_result="",
        )

    def _upsert_relationship_sync(
        self,
        subject: EntityRef,
        object: EntityRef,
        relation_type: str,
        scope: str,
        session_id: str,
        group_id: str,
        visibility: str,
        evidence: str,
        confidence: float,
        review_status: str,
        source_memory_id: str,
        metadata: dict[str, Any],
        _commit: bool = True,
    ) -> str:
        now = utc_now()
        row_id = new_id("rel")
        evidence = redact_sensitive_text(evidence)
        metadata = redact_sensitive_value(metadata)
        with self._lock:
            old = self._conn.execute(
                """
                SELECT id, metadata, created_at FROM relationship_edges
                WHERE subject_kind=? AND subject_id=? AND object_kind=? AND object_id=?
                  AND relation_type=? AND scope=? AND session_id=?
                """,
                (
                    subject.kind,
                    subject.id,
                    object.kind,
                    object.id,
                    clean_text(relation_type, 80),
                    clean_text(scope, 40),
                    clean_text(session_id, 200),
                ),
            ).fetchone()
            if old:
                row_id = old["id"]
                merged_metadata = json_loads(old["metadata"], {})
                merged_metadata.update(metadata)
            else:
                merged_metadata = metadata
            self._conn.execute(
                """
                INSERT INTO relationship_edges(
                    id, subject_kind, subject_id, subject_name, object_kind, object_id,
                    object_name, relation_type, scope, session_id, group_id, visibility,
                    evidence, confidence, review_status, source_memory_id, metadata,
                    created_at, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(subject_kind, subject_id, object_kind, object_id, relation_type, scope, session_id)
                DO UPDATE SET
                    subject_name=excluded.subject_name,
                    object_name=excluded.object_name,
                    visibility=excluded.visibility,
                    evidence=excluded.evidence,
                    confidence=max(relationship_edges.confidence, excluded.confidence),
                    review_status=excluded.review_status,
                    source_memory_id=excluded.source_memory_id,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (
                    row_id,
                    clean_text(subject.kind, 40),
                    clean_text(subject.id, 120),
                    clean_text(subject.name, 80),
                    clean_text(object.kind, 40),
                    clean_text(object.id, 120),
                    clean_text(object.name, 80),
                    clean_text(relation_type, 80),
                    clean_text(scope, 40),
                    clean_text(session_id, 200),
                    clean_text(group_id, 120),
                    clean_text(visibility, 40),
                    clean_text(evidence, 1000),
                    max(0.0, min(1.0, float(confidence or 0.0))),
                    clean_text(review_status, 40),
                    clean_text(source_memory_id, 120),
                    json_dumps(merged_metadata),
                    now,
                    now,
                ),
            )
            if _commit:
                self._conn.commit()
        return row_id

    async def capture_write_batch(
        self, ops: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """批量执行采集写链，合并为单事务一次 commit。

        ops 为有序写操作描述列表，元素形如：
          - {"kind": "relationship", "source_memory_id": str,
             "params": {详见 _upsert_relationship_sync 关键字参数}}
          - {"kind": "profile", "record": MemoryRecord}
          - {"kind": "memory", "record": MemoryRecord}
        可附加字段：
          - "requires_ok": list[int] 仅当这些索引对应的 op 均成功才执行
          - "source_memory_id_from": int 从该索引 op 的结果中取 memory_id
        profile 项内部已含 SAVEPOINT（_transaction_sync），在外层事务中自动降级嵌套；
        memory 项通过 _commit=False 复用内部无 commit 变体。
        返回与 ops 等长的结果列表；单项失败被 SAVEPOINT 隔离，不拖累整批。
        """
        return await asyncio.to_thread(self._capture_write_batch_sync, ops)

    def _capture_write_batch_sync(
        self, ops: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not ops:
            return results
        with self._lock:
            with self._transaction_sync():
                for index, op in enumerate(ops):
                    required_indexes = op.get("requires_ok") or []
                    if any(
                        i >= len(results) or not results[i].get("ok")
                        for i in required_indexes
                    ):
                        results.append({"ok": False, "code": "skip_required_op_failed"})
                        continue
                    kind = op["kind"]
                    try:
                        with self._transaction_sync():  # 单项 SAVEPOINT 隔离失败
                            if kind == "relationship":
                                params = dict(op["params"])
                                if op.get("source_memory_id_from") is not None:
                                    src_index = op["source_memory_id_from"]
                                    src = (
                                        results[src_index].get("memory_id") or ""
                                        if src_index < len(results)
                                        else ""
                                    )
                                    params["source_memory_id"] = src
                                elif op.get("source_memory_id"):
                                    params["source_memory_id"] = op["source_memory_id"]
                                elif "source_memory_id" not in params:
                                    params["source_memory_id"] = ""
                                row_id = self._upsert_relationship_sync(
                                    _commit=False, **params
                                )
                                results.append({"ok": True, "row_id": row_id})
                            elif kind == "profile":
                                results.append(
                                    self._upsert_profile_candidate_sync(op["record"])
                                )
                            elif kind == "memory":
                                memory_id = self._insert_memory_sync(
                                    op["record"],
                                    op.get("review_reason") or "",
                                    _commit=False,
                                )
                                results.append({"ok": True, "memory_id": memory_id})
                            else:
                                results.append(
                                    {"ok": False, "code": f"unknown_batch_op:{kind}"}
                                )
                    except Exception as exc:
                        logger.warning(
                            "[MemoryCompanion] 批量写入单项失败 index=%s kind=%s error=%s",
                            index,
                            kind,
                            exc,
                            exc_info=True,
                        )
                        results.append(
                            {
                                "ok": False,
                                "code": "batch_op_error",
                                "error": clean_text(str(exc), 300),
                            }
                        )
        return results

    async def list_relationships(
        self,
        limit: int = 20,
        entity_id: str = "",
        memory_types: list[str] | tuple[str, ...] | None = None,
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
        *,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_relationships_sync,
            limit,
            entity_id,
            memory_types,
            scope,
            session_id,
            group_id,
            offset,
        )

    def _list_relationships_sync(
        self,
        limit: int,
        entity_id: str,
        memory_types: list[str] | tuple[str, ...] | None,
        scope: str,
        session_id: str,
        group_id: str,
        offset: int,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = "1=1"
        if entity_id:
            where += " AND (subject_id=? OR object_id=?)"
            params.extend([entity_id, entity_id])
        if scope:
            where += " AND scope=?"
            params.append(scope)
        if session_id:
            where += " AND session_id=?"
            params.append(session_id)
        if group_id:
            where += " AND group_id=?"
            params.append(group_id)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM relationship_edges
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [max(1, int(limit)), max(0, int(offset))],
            ).fetchall()
        return [dict(row) for row in rows]

    async def upsert_knowledge_node(
        self,
        *,
        node_type: str,
        label: str,
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
        confidence: float = 0.6,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._upsert_knowledge_node_sync,
            node_type,
            label,
            scope,
            session_id,
            group_id,
            confidence,
            metadata or {},
        )

    def _upsert_knowledge_node_sync(
        self,
        node_type: str,
        label: str,
        scope: str,
        session_id: str,
        group_id: str,
        confidence: float,
        metadata: dict[str, Any],
    ) -> str:
        node_type = clean_text(node_type, 40)
        label = clean_text(redact_sensitive_text(label), 160)
        metadata = redact_sensitive_value(metadata)
        scope = clean_text(scope, 40)
        session_id = clean_text(session_id, 200)
        group_id = clean_text(group_id, 120)
        if not node_type or not label:
            return ""
        node_key = stable_fingerprint(node_type, label.lower())
        node_id = "kg_node_" + stable_fingerprint(node_type, node_key, scope, session_id)[:16]
        now = utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO knowledge_nodes(
                    id, node_type, node_key, label, scope, session_id, group_id,
                    confidence, metadata, created_at, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(node_type, node_key, scope, session_id) DO UPDATE SET
                    label=excluded.label,
                    group_id=CASE WHEN excluded.group_id!='' THEN excluded.group_id ELSE knowledge_nodes.group_id END,
                    confidence=max(knowledge_nodes.confidence, excluded.confidence),
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (
                    node_id,
                    node_type,
                    node_key,
                    label,
                    scope,
                    session_id,
                    group_id,
                    max(0.0, min(1.0, float(confidence or 0.0))),
                    json_dumps(metadata),
                    now,
                    now,
                ),
            )
            row = self._conn.execute(
                """
                SELECT id FROM knowledge_nodes
                WHERE node_type=? AND node_key=? AND scope=? AND session_id=?
                """,
                (node_type, node_key, scope, session_id),
            ).fetchone()
            self._conn.commit()
        return str(row["id"] if row else node_id)

    async def upsert_knowledge_edge(
        self,
        *,
        source_node_id: str,
        target_node_id: str,
        relation_type: str,
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
        source_memory_id: str = "",
        evidence: str = "",
        confidence: float = 0.6,
        review_status: str = "auto",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._upsert_knowledge_edge_sync,
            source_node_id,
            target_node_id,
            relation_type,
            scope,
            session_id,
            group_id,
            source_memory_id,
            evidence,
            confidence,
            review_status,
            metadata or {},
        )

    def _upsert_knowledge_edge_sync(
        self,
        source_node_id: str,
        target_node_id: str,
        relation_type: str,
        scope: str,
        session_id: str,
        group_id: str,
        source_memory_id: str,
        evidence: str,
        confidence: float,
        review_status: str,
        metadata: dict[str, Any],
    ) -> str:
        source_node_id = clean_text(source_node_id, 120)
        target_node_id = clean_text(target_node_id, 120)
        relation_type = clean_text(relation_type, 60)
        source_memory_id = clean_text(source_memory_id, 120)
        evidence = redact_sensitive_text(evidence)
        metadata = redact_sensitive_value(metadata)
        if not source_node_id or not target_node_id or not relation_type:
            return ""
        edge_id = "kg_edge_" + stable_fingerprint(source_node_id, target_node_id, relation_type, source_memory_id)[:16]
        now = utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO knowledge_edges(
                    id, source_node_id, target_node_id, relation_type, scope, session_id,
                    group_id, source_memory_id, evidence, confidence, review_status,
                    metadata, created_at, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_node_id, target_node_id, relation_type, source_memory_id) DO UPDATE SET
                    evidence=excluded.evidence,
                    confidence=max(knowledge_edges.confidence, excluded.confidence),
                    review_status=excluded.review_status,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (
                    edge_id,
                    source_node_id,
                    target_node_id,
                    relation_type,
                    clean_text(scope, 40),
                    clean_text(session_id, 200),
                    clean_text(group_id, 120),
                    source_memory_id,
                    clean_text(evidence, 1000),
                    max(0.0, min(1.0, float(confidence or 0.0))),
                    clean_text(review_status, 40),
                    json_dumps(metadata),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return edge_id

    async def list_knowledge_edges(
        self,
        limit: int = 50,
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
        node: str = "",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_knowledge_edges_sync,
            limit,
            scope,
            session_id,
            group_id,
            node,
        )

    def _list_knowledge_edges_sync(
        self,
        limit: int,
        scope: str,
        session_id: str,
        group_id: str,
        node: str,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = "1=1"
        if scope:
            where += " AND e.scope=?"
            params.append(clean_text(scope, 40))
        if session_id:
            where += " AND e.session_id=?"
            params.append(clean_text(session_id, 200))
        if group_id:
            where += " AND e.group_id=?"
            params.append(clean_text(group_id, 120))
        node = clean_text(node, 160)
        if node:
            where += " AND (s.label LIKE ? ESCAPE '\\' OR t.label LIKE ? ESCAPE '\\')"
            like = self._like_pattern(node)
            params.extend([like, like])
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    e.*,
                    s.node_type AS source_type,
                    s.label AS source_label,
                    t.node_type AS target_type,
                    t.label AS target_label
                FROM knowledge_edges e
                LEFT JOIN knowledge_nodes s ON s.id=e.source_node_id
                LEFT JOIN knowledge_nodes t ON t.id=e.target_node_id
                WHERE {where}
                ORDER BY e.updated_at DESC
                LIMIT ?
                """,
                params + [max(1, int(limit))],
            ).fetchall()
        return [dict(row) for row in rows]

    async def query_knowledge_paths(
        self,
        terms: list[str],
        *,
        tag: str = "",
        node_type: str = "",
        memory_ids: list[str] | None = None,
        limit: int = 80,
        session_id: str = "",
        scope: str = "",
        group_id: str = "",
        user_id: str = "",
    ) -> list[dict[str, Any]]:
        """Return bounded one-hop graph paths for active memory reconstruction.

        This storage query intentionally does not decide visibility. Callers must
        resolve ``source_memory_id`` values to memories and apply the current ACL
        before exposing any returned evidence.
        """
        return await asyncio.to_thread(
            self._query_knowledge_paths_sync,
            terms,
            tag,
            node_type,
            memory_ids,
            limit,
            session_id,
            scope,
            group_id,
            user_id,
        )

    def _query_knowledge_paths_sync(
        self,
        terms: list[str],
        tag: str,
        node_type: str,
        memory_ids: list[str] | None,
        limit: int,
        session_id: str,
        scope: str,
        group_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        # Keep placeholder counts comfortably below SQLite's common variable
        # limit. Repeated tool calls provide traversal depth at the service layer.
        cleaned_terms: list[str] = []
        raw_terms = terms if isinstance(terms, list) else []
        for raw_term in raw_terms:
            term = clean_text(raw_term, 160).lower()
            if term and term not in cleaned_terms:
                cleaned_terms.append(term)
            if len(cleaned_terms) >= 32:
                break

        cleaned_memory_ids: list[str] = []
        raw_memory_ids = memory_ids if isinstance(memory_ids, list) else []
        for raw_memory_id in raw_memory_ids:
            memory_id = clean_text(raw_memory_id, 120)
            if memory_id and memory_id not in cleaned_memory_ids:
                cleaned_memory_ids.append(memory_id)
            if len(cleaned_memory_ids) >= 256:
                break

        tag = clean_text(tag, 80).lower()
        node_type = clean_text(node_type, 40).lower()
        session_id = clean_text(session_id, 200)
        scope = clean_text(scope, 40).lower()
        group_id = clean_text(group_id, 120)
        user_id = clean_text(user_id, 160)
        if not cleaned_terms and not tag and not node_type and not cleaned_memory_ids:
            return []

        def literal_like(value: str) -> str:
            escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            return f"%{escaped}%"

        clauses: list[str] = []
        params: list[Any] = []
        if cleaned_terms:
            term_clauses: list[str] = []
            for term in cleaned_terms:
                term_clauses.append(
                    "(lower(s.label) LIKE ? ESCAPE '\\' OR lower(t.label) LIKE ? ESCAPE '\\')"
                )
                pattern = literal_like(term)
                params.extend([pattern, pattern])
            clauses.append("(" + " OR ".join(term_clauses) + ")")
        if tag:
            tag_pattern = literal_like(tag)
            clauses.append(
                """
                (
                    lower(
                        CASE
                            WHEN json_valid(e.metadata)
                            THEN coalesce(CAST(json_extract(e.metadata, '$.associative_tag') AS TEXT), '')
                            ELSE ''
                        END
                    ) LIKE ? ESCAPE '\\'
                    OR (lower(s.node_type)='tag' AND lower(s.label) LIKE ? ESCAPE '\\')
                    OR (lower(t.node_type)='tag' AND lower(t.label) LIKE ? ESCAPE '\\')
                )
                """
            )
            params.extend([tag_pattern, tag_pattern, tag_pattern])
        if node_type:
            clauses.append("(lower(s.node_type)=? OR lower(t.node_type)=?)")
            params.extend([node_type, node_type])
        if cleaned_memory_ids:
            placeholders = ",".join("?" for _ in cleaned_memory_ids)
            clauses.append(f"e.source_memory_id IN ({placeholders})")
            params.extend(cleaned_memory_ids)

        try:
            bounded_limit = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            bounded_limit = 80

        # Prefer paths that are likely to survive the service-layer visibility
        # check. This keeps a dense, unrelated user's graph from consuming the
        # bounded scan budget before current-session evidence is considered.
        priority_cases: list[str] = []
        priority_params: list[Any] = []
        if session_id:
            priority_cases.append("WHEN e.session_id=? THEN 0")
            priority_params.append(session_id)
        if user_id:
            priority_cases.append("WHEN (m.subject_id=? OR m.object_id=?) THEN 1")
            priority_params.extend([user_id, user_id])
        if group_id:
            priority_cases.append("WHEN e.group_id=? THEN 2")
            priority_params.append(group_id)
        if scope:
            priority_cases.append("WHEN lower(e.scope)=? THEN 3")
            priority_params.append(scope)
        priority_order = (
            "CASE " + " ".join(priority_cases) + " ELSE 4 END, "
            if priority_cases
            else ""
        )
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    e.id AS edge_id,
                    e.source_memory_id,
                    e.source_node_id,
                    s.node_type AS source_type,
                    s.node_key AS source_key,
                    s.label AS source_label,
                    s.metadata AS source_metadata,
                    e.target_node_id,
                    t.node_type AS target_type,
                    t.node_key AS target_key,
                    t.label AS target_label,
                    t.metadata AS target_metadata,
                    e.relation_type,
                    e.evidence,
                    e.confidence,
                    e.review_status,
                    e.scope,
                    e.session_id,
                    e.group_id,
                    e.metadata AS edge_metadata,
                    e.created_at,
                    e.updated_at
                FROM knowledge_edges e
                JOIN knowledge_nodes s ON s.id=e.source_node_id
                JOIN knowledge_nodes t ON t.id=e.target_node_id
                LEFT JOIN memories m ON m.id=e.source_memory_id
                WHERE {' AND '.join(clauses)}
                ORDER BY {priority_order}e.confidence DESC, e.updated_at DESC, e.id ASC
                LIMIT ?
                """,
                params + priority_params + [bounded_limit],
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("source_metadata", "target_metadata", "edge_metadata"):
                parsed = json_loads(item.get(key), {})
                item[key] = parsed if isinstance(parsed, dict) else {}
            results.append(item)
        return results

    async def related_knowledge_terms(
        self,
        terms: list[str],
        *,
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
        limit: int = 12,
    ) -> list[str]:
        return await asyncio.to_thread(
            self._related_knowledge_terms_sync,
            terms,
            scope,
            session_id,
            group_id,
            limit,
        )

    def _related_knowledge_terms_sync(
        self,
        terms: list[str],
        scope: str,
        session_id: str,
        group_id: str,
        limit: int,
    ) -> list[str]:
        cleaned_terms = [clean_text(term, 80).lower() for term in terms if clean_text(term, 80)]
        if not cleaned_terms:
            return []
        params: list[Any] = []
        scope = clean_text(scope, 40)
        session_id = clean_text(session_id, 200)
        group_id = clean_text(group_id, 120)
        scope_filter = ""
        if scope:
            scope_filter += " AND (n.scope='' OR n.scope=?)"
            params.append(scope)
        if session_id:
            scope_filter += " AND (n.session_id='' OR n.session_id=?)"
            params.append(session_id)
        if group_id:
            scope_filter += " AND (n.group_id='' OR n.group_id=?)"
            params.append(group_id)
        match_clauses: list[str] = []
        match_params: list[Any] = []
        like_terms = cleaned_terms
        if self._knowledge_trgm_enabled:
            # Trigram substring match equals LIKE '%term%' for terms with
            # >=3 alphanumeric characters. Terms containing punctuation keep
            # the exact LIKE path because the trigram tokenizer splits tokens
            # on non-alphanumeric characters.
            long_terms = [term for term in cleaned_terms if len(term) >= 3 and term.isalnum()]
            like_terms = [term for term in cleaned_terms if term not in long_terms]
            if long_terms:
                trgm_query = " OR ".join(self._quote_fts_term(term) for term in long_terms)
                match_clauses.append(
                    "n.rowid IN (SELECT rowid FROM knowledge_label_trgm WHERE knowledge_label_trgm MATCH ?)"
                )
                match_params.append(trgm_query)
        if like_terms:
            like_sql = " OR ".join(["lower(n.label) LIKE ? ESCAPE '\\'" for _ in like_terms])
            match_clauses.append(f"({like_sql})")
            match_params.extend(self._like_pattern(term) for term in like_terms)
        match_where = " OR ".join(match_clauses) or "1=0"
        with self._lock:
            matched = self._conn.execute(
                f"""
                SELECT n.id, n.label
                FROM knowledge_nodes n
                WHERE ({match_where}) {scope_filter}
                ORDER BY n.updated_at DESC
                LIMIT ?
                """,
                match_params + params + [max(1, int(limit))],
            ).fetchall()
            matched_ids = [str(row["id"]) for row in matched]
            labels = [clean_text(row["label"], 80) for row in matched]
            if not matched_ids:
                return labels[:limit]
            placeholders = ",".join("?" for _ in matched_ids)
            related = self._conn.execute(
                f"""
                SELECT DISTINCT n.label
                FROM knowledge_edges e
                JOIN knowledge_nodes n
                  ON n.id = CASE
                    WHEN e.source_node_id IN ({placeholders}) THEN e.target_node_id
                    ELSE e.source_node_id
                  END
                WHERE e.source_node_id IN ({placeholders})
                   OR e.target_node_id IN ({placeholders})
                ORDER BY e.updated_at DESC
                LIMIT ?
                """,
                matched_ids + matched_ids + matched_ids + [max(1, int(limit))],
            ).fetchall()
        for row in related:
            label = clean_text(row["label"], 80)
            if label and label.lower() not in cleaned_terms and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
        return labels[:limit]

    async def add_timeline_event(
        self,
        *,
        event_type: str,
        session_id: str,
        scope: str,
        subject_id: str,
        object_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        occurred_at: str = "",
    ) -> str:
        return await asyncio.to_thread(
            self._add_timeline_event_sync,
            event_type,
            session_id,
            scope,
            subject_id,
            object_id,
            content,
            metadata or {},
            occurred_at,
        )

    def _add_timeline_event_sync(
        self,
        event_type: str,
        session_id: str,
        scope: str,
        subject_id: str,
        object_id: str,
        content: str,
        metadata: dict[str, Any],
        occurred_at: str,
    ) -> str:
        now = utc_now()
        content = redact_sensitive_text(clean_text(content, 4000))
        metadata = redact_sensitive_value(metadata)
        row_id = new_id("tl")
        event_type = clean_text(event_type, 80)
        session_id = clean_text(session_id, 200)
        subject_id = clean_text(subject_id, 120)
        message_id = clean_text(metadata.get("message_id"), 120)
        dedupe_key = (
            stable_fingerprint("timeline", event_type, session_id, subject_id, message_id)
            if message_id
            else ""
        )
        with self._lock:
            with self._transaction_sync():
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO timeline(
                        id, event_type, session_id, scope, subject_id, object_id,
                        content, metadata, message_id, dedupe_key,
                        occurred_at, created_at, summarized_at,
                        retention_class, import_batch_id, source_sequence
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?, '',?,?,?)
                    """,
                    (
                        row_id,
                        event_type,
                        session_id,
                        clean_text(scope, 40),
                        subject_id,
                        clean_text(object_id, 120),
                        clean_text(content, 4000),
                        json_dumps(metadata),
                        message_id,
                        dedupe_key,
                        occurred_at or now,
                        now,
                        clean_text(metadata.get("retention_class"), 40) or "normal",
                        clean_text(metadata.get("import_batch_id"), 120),
                        max(0, int(metadata.get("source_sequence") or 0)),
                    ),
                )
                if cur.rowcount == 0 and dedupe_key:
                    existing = self._conn.execute(
                        "SELECT id FROM timeline WHERE dedupe_key=?",
                        (dedupe_key,),
                    ).fetchone()
                    if existing:
                        return clean_text(existing["id"], 120)
        return row_id

    async def add_historical_timeline_events(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        inserted, _ = await asyncio.to_thread(self._add_historical_timeline_events_sync, rows)
        return inserted

    async def add_historical_timeline_events_with_status(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[dict[str, str], set[str]]:
        return await asyncio.to_thread(self._add_historical_timeline_events_sync, rows)

    def _add_historical_timeline_events_sync(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[dict[str, str], set[str]]:
        now = utc_now()
        inserted: dict[str, str] = {}
        newly_inserted: set[str] = set()
        with self._lock:
            with self._transaction_sync():
                for raw in rows:
                    if not isinstance(raw, dict):
                        continue
                    event_type = clean_text(raw.get("event_type"), 80)
                    session_id = clean_text(raw.get("session_id"), 200)
                    subject_id = clean_text(raw.get("subject_id"), 120)
                    message_id = clean_text(raw.get("message_id"), 120)
                    if not event_type or not session_id or not subject_id or not message_id:
                        continue
                    dedupe_key = stable_fingerprint("timeline", event_type, session_id, subject_id, message_id)
                    row_id = clean_text(raw.get("id"), 120) or new_id("tl")
                    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
                    cursor = self._conn.execute(
                        """
                        INSERT OR IGNORE INTO timeline(
                            id, event_type, session_id, scope, subject_id, object_id,
                            content, metadata, message_id, dedupe_key,
                            occurred_at, created_at, summarized_at,
                            retention_class, import_batch_id, source_sequence
                        )
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?, '',?,?,?)
                        """,
                        (
                            row_id,
                            event_type,
                            session_id,
                            clean_text(raw.get("scope"), 40),
                            subject_id,
                            clean_text(raw.get("object_id"), 120),
                            clean_text(redact_sensitive_text(raw.get("content")), 4000),
                            json_dumps(redact_sensitive_value(metadata)),
                            message_id,
                            dedupe_key,
                            clean_text(raw.get("occurred_at"), 80) or now,
                            now,
                            clean_text(raw.get("retention_class"), 40) or "historical_archive",
                            clean_text(raw.get("import_batch_id"), 120),
                            max(0, int(raw.get("source_sequence") or 0)),
                        ),
                    )
                    if cursor.rowcount > 0:
                        newly_inserted.add(message_id)
                    existing = self._conn.execute(
                        "SELECT id FROM timeline WHERE dedupe_key=?",
                        (dedupe_key,),
                    ).fetchone()
                    if existing:
                        inserted[message_id] = clean_text(existing["id"], 120)
        return inserted, newly_inserted

    async def upsert_chat_import_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._upsert_chat_import_batch_sync, payload)

    def _upsert_chat_import_batch_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        batch_id = clean_text(payload.get("id"), 120)
        if not batch_id:
            raise ValueError("chat import batch id is required")
        now = utc_now()
        json_fields = {"speaker_map", "options", "stats"}
        payload = redact_sensitive_value(payload)
        values: dict[str, Any] = {
            "id": batch_id,
            "upload_id": clean_text(payload.get("upload_id"), 120),
            "source_name": clean_text(payload.get("source_name"), 240),
            "source_hash": clean_text(payload.get("source_hash"), 120),
            "state": clean_text(payload.get("state"), 40) or "prepared",
            "session_id": clean_text(payload.get("session_id"), 200),
            "scope": clean_text(payload.get("scope"), 40) or "private",
            "platform": clean_text(payload.get("platform"), 40),
            "user_id": clean_text(payload.get("user_id"), 120),
            "user_name": clean_text(payload.get("user_name"), 120),
            "bot_id": clean_text(payload.get("bot_id"), 120),
            "bot_name": clean_text(payload.get("bot_name"), 120),
            "speaker_map": payload.get("speaker_map") if isinstance(payload.get("speaker_map"), dict) else {},
            "options": payload.get("options") if isinstance(payload.get("options"), dict) else {},
            "stats": payload.get("stats") if isinstance(payload.get("stats"), dict) else {},
            "checkpoint_segment": max(0, int(payload.get("checkpoint_segment") or 0)),
            "total_segments": max(0, int(payload.get("total_segments") or 0)),
            "completed_segments": max(0, int(payload.get("completed_segments") or 0)),
            "summary_memory_count": max(0, int(payload.get("summary_memory_count") or 0)),
            "important_event_count": max(0, int(payload.get("important_event_count") or 0)),
            "relationship_observation_count": max(0, int(payload.get("relationship_observation_count") or 0)),
            "backup_path": clean_text(payload.get("backup_path"), 2000),
            "error": clean_text(redact_sensitive_text(payload.get("error")), 1000),
            "created_at": clean_text(payload.get("created_at"), 80) or now,
            "updated_at": now,
        }
        columns = list(values)
        db_values = [json_dumps(values[name]) if name in json_fields else values[name] for name in columns]
        updates = ",".join(f"{name}=excluded.{name}" for name in columns if name not in {"id", "created_at"})
        with self._lock:
            with self._transaction_sync():
                self._conn.execute(
                    f"INSERT INTO chat_import_batches({','.join(columns)}) VALUES({','.join('?' for _ in columns)}) "
                    f"ON CONFLICT(id) DO UPDATE SET {updates}",
                    db_values,
                )
        return self._get_chat_import_batch_sync(batch_id) or {}

    async def get_chat_import_batch(self, batch_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_chat_import_batch_sync, batch_id)

    def _get_chat_import_batch_sync(self, batch_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM chat_import_batches WHERE id=?",
                (clean_text(batch_id, 120),),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ("speaker_map", "options", "stats"):
            result[key] = json_loads(result.get(key), {})
        return result

    async def list_chat_import_batches(self, limit: int | None = 20) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_chat_import_batches_sync, limit)

    def _list_chat_import_batches_sync(self, limit: int | None) -> list[dict[str, Any]]:
        with self._lock:
            if limit is None:
                rows = self._conn.execute(
                    "SELECT * FROM chat_import_batches ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM chat_import_batches ORDER BY updated_at DESC LIMIT ?",
                    (max(1, min(1000, int(limit or 20))),),
                ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("speaker_map", "options", "stats"):
                item[key] = json_loads(item.get(key), {})
            results.append(item)
        return results

    async def update_chat_import_batch(self, batch_id: str, **changes: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._update_chat_import_batch_sync, batch_id, changes)

    def _update_chat_import_batch_sync(self, batch_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "state", "checkpoint_segment", "total_segments", "completed_segments",
            "summary_memory_count", "important_event_count", "relationship_observation_count",
            "stats", "options", "speaker_map", "backup_path", "error",
        }
        json_fields = {"stats", "options", "speaker_map"}
        selected = redact_sensitive_value(
            {key: value for key, value in changes.items() if key in allowed}
        )
        if not selected:
            return self._get_chat_import_batch_sync(batch_id)
        selected["updated_at"] = utc_now()
        clauses = ",".join(f"{key}=?" for key in selected)
        params = [json_dumps(value) if key in json_fields else value for key, value in selected.items()]
        params.append(clean_text(batch_id, 120))
        with self._lock:
            with self._transaction_sync():
                self._conn.execute(f"UPDATE chat_import_batches SET {clauses} WHERE id=?", params)
        return self._get_chat_import_batch_sync(batch_id)

    async def replace_chat_import_segments(self, batch_id: str, segments: list[dict[str, Any]]) -> int:
        return await asyncio.to_thread(self._replace_chat_import_segments_sync, batch_id, segments)

    def _replace_chat_import_segments_sync(self, batch_id: str, segments: list[dict[str, Any]]) -> int:
        batch_id = clean_text(batch_id, 120)
        now = utc_now()
        with self._lock:
            with self._transaction_sync():
                self._conn.execute("DELETE FROM chat_import_segments WHERE batch_id=?", (batch_id,))
                for raw in segments:
                    self._conn.execute(
                        """
                        INSERT INTO chat_import_segments(
                            id,batch_id,segment_index,start_at,end_at,local_date,message_ids,
                            transcript,char_count,turn_count,status,attempts,result,
                            summary_memory_id,error,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            clean_text(raw.get("id"), 120), batch_id, max(0, int(raw.get("segment_index") or 0)),
                            clean_text(raw.get("start_at"), 80), clean_text(raw.get("end_at"), 80),
                            clean_text(raw.get("local_date"), 20), json_dumps(raw.get("message_ids") or []),
                            redact_sensitive_text(raw.get("transcript")), max(0, int(raw.get("char_count") or 0)),
                            max(0, int(raw.get("turn_count") or 0)), clean_text(raw.get("status"), 30) or "pending",
                            max(0, int(raw.get("attempts") or 0)), json_dumps(redact_sensitive_value(raw.get("result") or {})),
                            clean_text(raw.get("summary_memory_id"), 120),
                            clean_text(redact_sensitive_text(raw.get("error")), 1000), now, now,
                        ),
                    )
        return len(segments)

    async def chat_import_segments(self, batch_id: str, *, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._chat_import_segments_sync, batch_id, statuses)

    def _chat_import_segments_sync(self, batch_id: str, statuses: set[str] | None) -> list[dict[str, Any]]:
        params: list[Any] = [clean_text(batch_id, 120)]
        where = "batch_id=?"
        normalized = sorted({clean_text(item, 30) for item in (statuses or set()) if clean_text(item, 30)})
        if normalized:
            where += f" AND status IN ({','.join('?' for _ in normalized)})"
            params.extend(normalized)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM chat_import_segments WHERE {where} ORDER BY segment_index ASC",
                params,
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["message_ids"] = json_loads(item.get("message_ids"), [])
            item["result"] = json_loads(item.get("result"), {})
            results.append(item)
        return results

    async def update_chat_import_segment(self, segment_id: str, **changes: Any) -> bool:
        return await asyncio.to_thread(self._update_chat_import_segment_sync, segment_id, changes)

    def _update_chat_import_segment_sync(self, segment_id: str, changes: dict[str, Any]) -> bool:
        allowed = {"status", "attempts", "result", "summary_memory_id", "error"}
        selected = redact_sensitive_value(
            {key: value for key, value in changes.items() if key in allowed}
        )
        if not selected:
            return False
        selected["updated_at"] = utc_now()
        clauses = ",".join(f"{key}=?" for key in selected)
        params = [json_dumps(value) if key == "result" else value for key, value in selected.items()]
        params.append(clean_text(segment_id, 120))
        with self._lock:
            cur = self._conn.execute(f"UPDATE chat_import_segments SET {clauses} WHERE id=?", params)
            self._conn.commit()
        return cur.rowcount > 0

    async def rollback_chat_import_batch(self, batch_id: str) -> dict[str, int]:
        return await asyncio.to_thread(self._rollback_chat_import_batch_sync, batch_id)

    async def chat_import_memory_counts(self, batch_id: str) -> dict[str, int]:
        return await asyncio.to_thread(self._chat_import_memory_counts_sync, batch_id)

    def _chat_import_memory_counts_sync(self, batch_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT memory_type, COUNT(*) AS count FROM memories WHERE import_batch_id=? GROUP BY memory_type",
                (clean_text(batch_id, 120),),
            ).fetchall()
        result = {clean_text(row["memory_type"], 80): int(row["count"] or 0) for row in rows}
        result["total"] = sum(result.values())
        return result

    async def chat_import_rebind_target_exists(
        self,
        *,
        batch_id: str,
        session_id: str,
        user_id: str,
        bot_id: str,
    ) -> bool:
        return await asyncio.to_thread(
            self._private_memory_context_exists_sync,
            session_id,
            user_id,
            bot_id,
            batch_id,
        )

    async def private_memory_context_exists(
        self,
        *,
        session_id: str,
        user_id: str,
        bot_id: str,
        exclude_import_batch_id: str = "",
    ) -> bool:
        return await asyncio.to_thread(
            self._private_memory_context_exists_sync,
            session_id,
            user_id,
            bot_id,
            exclude_import_batch_id,
        )

    def _private_memory_context_exists_sync(
        self,
        session_id: str,
        user_id: str,
        bot_id: str,
        exclude_import_batch_id: str = "",
    ) -> bool:
        return self._private_memory_context_row_sync(
            session_id,
            user_id,
            bot_id,
            exclude_import_batch_id,
        ) is not None

    def _private_memory_context_row_sync(
        self,
        session_id: str,
        user_id: str,
        bot_id: str,
        exclude_import_batch_id: str = "",
    ) -> sqlite3.Row | None:
        session_id = clean_text(session_id, 200)
        user_id = clean_text(user_id, 120)
        bot_id = clean_text(bot_id, 120)
        exclude_import_batch_id = clean_text(exclude_import_batch_id, 120)
        if not session_id or not user_id or not bot_id:
            return None
        exclude_clause = ""
        params: list[Any] = [session_id]
        if exclude_import_batch_id:
            exclude_clause = "AND COALESCE(import_batch_id, '')!=?"
            params.append(exclude_import_batch_id)
        params.extend([user_id, user_id, bot_id, bot_id, bot_id])
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT *
                FROM memories
                WHERE scope='private' AND session_id=?
                  {exclude_clause}
                  AND (
                    (subject_kind='user' AND subject_id=?)
                    OR (object_kind='user' AND object_id=?)
                  )
                  AND (
                    (subject_kind='bot' AND subject_id=?)
                    OR (object_kind='bot' AND object_id=?)
                    OR CASE
                        WHEN json_valid(metadata)
                        THEN COALESCE(CAST(json_extract(metadata, '$.owner_bot_id') AS TEXT), '')
                        ELSE ''
                       END=?
                  )
                ORDER BY
                  CASE WHEN COALESCE(import_batch_id, '')='' THEN 0 ELSE 1 END,
                  COALESCE(NULLIF(occurred_at, ''), created_at) DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return row

    async def rebind_chat_import_batch(
        self,
        *,
        batch_id: str,
        session_id: str,
        platform: str,
        user_id: str,
        user_name: str = "",
        bot_id: str,
        bot_name: str = "",
        backup_path: str = "",
    ) -> dict[str, int]:
        return await asyncio.to_thread(
            self._rebind_chat_import_batch_sync,
            batch_id,
            session_id,
            platform,
            user_id,
            user_name,
            bot_id,
            bot_name,
            backup_path,
        )

    def _rebind_chat_import_batch_sync(
        self,
        batch_id: str,
        session_id: str,
        platform: str,
        user_id: str,
        user_name: str,
        bot_id: str,
        bot_name: str,
        backup_path: str,
    ) -> dict[str, int]:
        batch_id = clean_text(batch_id, 120)
        session_id = clean_text(session_id, 200)
        platform = clean_text(platform, 40)
        user_id = clean_text(user_id, 120)
        user_name = clean_text(user_name, 120)
        bot_id = clean_text(bot_id, 120)
        bot_name = clean_text(bot_name, 120)
        backup_path = clean_text(backup_path, 2000)
        if not batch_id or not session_id or not platform or not user_id or not bot_id:
            raise ValueError("批次、用户、会话、Bot 和平台均不能为空")
        if user_id == bot_id:
            raise ValueError("目标用户 ID 和 Bot ID 不能相同")
        parsed_scope, parsed_target = parse_scope_from_session(session_id)
        if parsed_scope != "private" or clean_text(parsed_target, 120) != user_id:
            raise ValueError("目标用户 ID 与私聊会话不一致")
        session_platform = clean_text(session_id.split(":", 1)[0], 40) if ":" in session_id else ""
        if session_platform and session_platform.casefold() != platform.casefold():
            raise ValueError("目标平台与私聊会话不一致")

        counts = {
            "memories": 0,
            "timeline": 0,
            "embeddings_removed": 0,
            "relationships": 0,
            "relationships_merged": 0,
            "knowledge_edges_removed": 0,
            "knowledge_nodes_removed": 0,
            "batch": 0,
        }
        now = utc_now()
        with self._lock:
            with self._transaction_sync():
                batch_row = self._conn.execute(
                    "SELECT * FROM chat_import_batches WHERE id=?",
                    (batch_id,),
                ).fetchone()
                if batch_row is None:
                    raise ValueError("导入批次不存在")
                state = clean_text(batch_row["state"], 40)
                if state not in {"completed", "completed_with_warnings"}:
                    raise ValueError("仅已完成的导入批次可以修正归属")
                if clean_text(batch_row["scope"], 40) != "private":
                    raise ValueError("仅私聊历史导入支持修正归属")
                old_session_id = clean_text(batch_row["session_id"], 200)
                old_user_id = clean_text(batch_row["user_id"], 120)
                old_bot_id = clean_text(batch_row["bot_id"], 120)
                if (old_session_id, old_user_id, old_bot_id) == (session_id, user_id, bot_id):
                    raise ValueError("当前批次已经属于所选私聊，无需重复修正")
                target_context = self._private_memory_context_row_sync(
                    session_id,
                    user_id,
                    bot_id,
                    batch_id,
                )
                if target_context is None:
                    raise ValueError("目标私聊上下文不存在，或用户、Bot 与所选会话不一致")

                old_target = {
                    "session_id": old_session_id,
                    "platform": clean_text(batch_row["platform"], 40),
                    "user_id": old_user_id,
                    "user_name": clean_text(batch_row["user_name"], 120),
                    "bot_id": old_bot_id,
                    "bot_name": clean_text(batch_row["bot_name"], 120),
                }
                matched_user_name = ""
                matched_bot_name = ""
                for prefix in ("subject", "object"):
                    kind = clean_text(target_context[f"{prefix}_kind"], 40)
                    entity_id = clean_text(target_context[f"{prefix}_id"], 120)
                    name = clean_text(target_context[f"{prefix}_name"], 120)
                    if kind == "user" and entity_id == user_id:
                        matched_user_name = name or matched_user_name
                    elif kind == "bot" and entity_id == bot_id:
                        matched_bot_name = name or matched_bot_name
                new_target = {
                    "session_id": session_id,
                    "platform": platform,
                    "user_id": user_id,
                    "user_name": user_name or matched_user_name or old_target["user_name"],
                    "bot_id": bot_id,
                    "bot_name": bot_name or matched_bot_name or old_target["bot_name"],
                }

                speaker_map = json_loads(batch_row["speaker_map"], {})
                if not isinstance(speaker_map, dict):
                    speaker_map = {}
                roles_by_id: dict[str, set[str]] = {}
                roles_by_name: dict[str, set[str]] = {}

                def identity_forms(value: Any) -> set[str]:
                    text = clean_text(value, 160).casefold()
                    if not text:
                        return set()
                    forms = {text}
                    forms.update(
                        clean_text(inner, 160).casefold()
                        for inner in re.findall(r"[（(\[【]([^）)\]】]+)[）)\]】]", text)
                    )
                    forms.add(re.sub(r"[（(\[【][^）)\]】]*[）)\]】]", "", text).strip())
                    forms.update(
                        part.strip()
                        for part in re.split(r"[\s/|,，、;；:：]+", text)
                        if part.strip()
                    )
                    return {item for item in forms if item}

                for mapped_role, mapped_id, mapped_name in (
                    ("user", old_target["user_id"], old_target["user_name"]),
                    ("bot", old_target["bot_id"], old_target["bot_name"]),
                ):
                    if mapped_id:
                        roles_by_id.setdefault(mapped_id, set()).add(mapped_role)
                    for form in identity_forms(mapped_name):
                        roles_by_name.setdefault(form, set()).add(mapped_role)

                for speaker, mapping in speaker_map.items():
                    if not isinstance(mapping, dict):
                        continue
                    mapped_role = clean_text(mapping.get("role"), 20)
                    if mapped_role not in {"user", "bot"}:
                        continue
                    for mapped_id in (
                        mapping.get("source_entity_id"),
                        mapping.get("entity_id"),
                    ):
                        normalized_id = clean_text(mapped_id, 120)
                        if normalized_id:
                            roles_by_id.setdefault(normalized_id, set()).add(mapped_role)
                    for mapped_name in (speaker, mapping.get("display_name")):
                        for form in identity_forms(mapped_name):
                            roles_by_name.setdefault(form, set()).add(mapped_role)

                def binding_metadata(raw: Any) -> dict[str, Any]:
                    metadata = json_loads(raw, {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    original = metadata.get("original_import_target")
                    if not isinstance(original, dict):
                        metadata["original_import_target"] = dict(old_target)
                    metadata["current_import_target"] = dict(new_target)
                    metadata["identity_rebound_at"] = now
                    return metadata

                memory_rows = self._conn.execute(
                    "SELECT * FROM memories WHERE import_batch_id=?",
                    (batch_id,),
                ).fetchall()
                timeline_rows = self._conn.execute(
                    "SELECT * FROM timeline WHERE import_batch_id=?",
                    (batch_id,),
                ).fetchall()
                if not memory_rows and not timeline_rows:
                    raise ValueError("该导入批次没有可修正的记忆或历史消息")
                memory_ids = [clean_text(row["id"], 120) for row in memory_rows]

                def rebound_entity(row: sqlite3.Row, prefix: str) -> tuple[str, str, str, str]:
                    kind = clean_text(row[f"{prefix}_kind"], 40)
                    entity_id = clean_text(row[f"{prefix}_id"], 120)
                    name = clean_text(row[f"{prefix}_name"], 80)
                    role_key = f"{prefix}_role"
                    role = clean_text(row[role_key], 80) if role_key in row.keys() else ""
                    if kind == "user" or (old_target["user_id"] and entity_id == old_target["user_id"]):
                        return kind or "user", user_id, new_target["user_name"] or name, role
                    if kind == "bot" or (old_target["bot_id"] and entity_id == old_target["bot_id"]):
                        return kind or "bot", bot_id, new_target["bot_name"] or name, role
                    inferred_roles = set(roles_by_id.get(entity_id, set()))
                    row_metadata = json_loads(row["metadata"], {}) if "metadata" in row.keys() else {}
                    if not isinstance(row_metadata, dict):
                        row_metadata = {}
                    fallback_name = row_metadata.get("actor" if prefix == "subject" else "object")
                    for candidate_name in (name, fallback_name):
                        for form in identity_forms(candidate_name):
                            inferred_roles.update(roles_by_name.get(form, set()))
                    if len(inferred_roles) == 1:
                        inferred_role = next(iter(inferred_roles))
                        if inferred_role == "user":
                            return "user", user_id, new_target["user_name"] or name, role
                        return "bot", bot_id, new_target["bot_name"] or name, role
                    return kind, entity_id, name, role

                for row in memory_rows:
                    subject = rebound_entity(row, "subject")
                    object_ref = rebound_entity(row, "object")
                    metadata = binding_metadata(row["metadata"])
                    metadata["owner_bot_id"] = bot_id
                    atom = self._memory_atom_record_for_row(
                        row,
                        subject_kind=subject[0],
                        subject_id=subject[1],
                        subject_name=subject[2],
                        subject_role=subject[3],
                        object_kind=object_ref[0],
                        object_id=object_ref[1],
                        object_name=object_ref[2],
                        object_role=object_ref[3],
                        scope="private",
                        session_id=session_id,
                        platform=platform,
                        group_id="",
                        metadata=json_dumps(metadata),
                        owner_bot_id=bot_id,
                    )
                    self._conn.execute(
                        """
                        UPDATE memories
                        SET subject_kind=?, subject_id=?, subject_name=?, subject_role=?,
                            object_kind=?, object_id=?, object_name=?, object_role=?,
                            scope='private', session_id=?, platform=?, group_id='',
                            metadata=?, owner_bot_id=?, canonical_key=?,
                            content_fingerprint=?, updated_at=?
                        WHERE id=? AND import_batch_id=?
                        """,
                        (
                            *subject,
                            *object_ref,
                            session_id,
                            platform,
                            json_dumps(metadata),
                            atom.owner_bot_id,
                            atom.canonical_key,
                            atom.content_fingerprint,
                            now,
                            row["id"],
                            batch_id,
                        ),
                    )
                    refreshed = self._conn.execute(
                        "SELECT * FROM memories WHERE id=?",
                        (row["id"],),
                    ).fetchone()
                    self._upsert_memory_fts_row(refreshed)
                    counts["memories"] += 1

                if memory_ids:
                    placeholders = ",".join("?" for _ in memory_ids)
                    relationship_rows = self._conn.execute(
                        f"SELECT * FROM relationship_edges WHERE source_memory_id IN ({placeholders})",
                        memory_ids,
                    ).fetchall()
                    for row in relationship_rows:
                        subject = rebound_entity(row, "subject")
                        object_ref = rebound_entity(row, "object")
                        collision = self._conn.execute(
                            """
                            SELECT id FROM relationship_edges
                            WHERE subject_kind=? AND subject_id=? AND object_kind=? AND object_id=?
                              AND relation_type=? AND scope='private' AND session_id=? AND id!=?
                            LIMIT 1
                            """,
                            (
                                subject[0], subject[1], object_ref[0], object_ref[1],
                                row["relation_type"], session_id, row["id"],
                            ),
                        ).fetchone()
                        if collision:
                            self._conn.execute("DELETE FROM relationship_edges WHERE id=?", (row["id"],))
                            counts["relationships_merged"] += 1
                            continue
                        metadata = binding_metadata(row["metadata"])
                        metadata["owner_bot_id"] = bot_id
                        metadata["participant_user_id"] = user_id
                        self._conn.execute(
                            """
                            UPDATE relationship_edges
                            SET subject_kind=?, subject_id=?, subject_name=?,
                                object_kind=?, object_id=?, object_name=?,
                                scope='private', session_id=?, group_id='', metadata=?, updated_at=?
                            WHERE id=? AND source_memory_id=?
                            """,
                            (
                                subject[0], subject[1], subject[2],
                                object_ref[0], object_ref[1], object_ref[2],
                                session_id, json_dumps(metadata), now,
                                row["id"], row["source_memory_id"],
                            ),
                        )
                        counts["relationships"] += 1

                    knowledge_rows = self._conn.execute(
                        f"""
                        SELECT id, source_node_id, target_node_id
                        FROM knowledge_edges
                        WHERE source_memory_id IN ({placeholders})
                        """,
                        memory_ids,
                    ).fetchall()
                    node_ids = {
                        clean_text(node_id, 120)
                        for row in knowledge_rows
                        for node_id in (row["source_node_id"], row["target_node_id"])
                        if clean_text(node_id, 120)
                    }
                    counts["knowledge_edges_removed"] = int(
                        self._conn.execute(
                            f"DELETE FROM knowledge_edges WHERE source_memory_id IN ({placeholders})",
                            memory_ids,
                        ).rowcount or 0
                    )
                    for node_id in node_ids:
                        used = self._conn.execute(
                            """
                            SELECT 1 FROM knowledge_edges
                            WHERE source_node_id=? OR target_node_id=?
                            LIMIT 1
                            """,
                            (node_id, node_id),
                        ).fetchone()
                        if used is None:
                            counts["knowledge_nodes_removed"] += int(
                                self._conn.execute(
                                    "DELETE FROM knowledge_nodes WHERE id=?",
                                    (node_id,),
                                ).rowcount or 0
                            )

                for row in timeline_rows:
                    subject_id = clean_text(row["subject_id"], 120)
                    object_id = clean_text(row["object_id"], 120)
                    event_type = clean_text(row["event_type"], 40)
                    if event_type == "bot_response":
                        subject_id, object_id = bot_id, user_id
                    elif event_type == "user_message":
                        subject_id, object_id = user_id, bot_id
                    else:
                        if old_target["user_id"] and subject_id == old_target["user_id"]:
                            subject_id = user_id
                        elif old_target["bot_id"] and subject_id == old_target["bot_id"]:
                            subject_id = bot_id
                        if old_target["user_id"] and object_id == old_target["user_id"]:
                            object_id = user_id
                        elif old_target["bot_id"] and object_id == old_target["bot_id"]:
                            object_id = bot_id
                    metadata = binding_metadata(row["metadata"])
                    metadata["owner_bot_id"] = bot_id
                    metadata["participant_user_id"] = user_id
                    metadata["platform"] = platform
                    self._conn.execute(
                        """
                        UPDATE timeline
                        SET session_id=?, scope='private', subject_id=?, object_id=?, metadata=?
                        WHERE id=? AND import_batch_id=?
                        """,
                        (
                            session_id,
                            subject_id,
                            object_id,
                            json_dumps(metadata),
                            row["id"],
                            batch_id,
                        ),
                    )
                    counts["timeline"] += 1

                for mapping in speaker_map.values():
                    if not isinstance(mapping, dict):
                        continue
                    mapping.setdefault("source_entity_id", clean_text(mapping.get("entity_id"), 120))
                    role = clean_text(mapping.get("role"), 20)
                    if role == "user":
                        mapping["entity_id"] = user_id
                    elif role == "bot":
                        mapping["entity_id"] = bot_id

                stats = json_loads(batch_row["stats"], {})
                if not isinstance(stats, dict):
                    stats = {}
                rebind_entry = {
                    "at": now,
                    "from": old_target,
                    "to": new_target,
                    "backup_path": backup_path,
                }
                history = stats.get("identity_rebind_history")
                if not isinstance(history, list):
                    history = []
                stats["identity_rebind_history"] = [*history, rebind_entry][-12:]
                stats["identity_rebind"] = rebind_entry
                identity_links = stats.get("identity_links")
                if not isinstance(identity_links, dict):
                    identity_links = {}
                try:
                    identity_links_version = int(identity_links.get("version") or 0)
                except (TypeError, ValueError):
                    identity_links_version = 0
                identity_links.update(
                    {
                        "version": max(2, identity_links_version),
                        "target_user_id": user_id,
                        "canonical_session_id": session_id,
                    }
                )
                stats["identity_links"] = identity_links

                batch_cur = self._conn.execute(
                    """
                    UPDATE chat_import_batches
                    SET session_id=?, scope='private', platform=?, user_id=?, user_name=?,
                        bot_id=?, bot_name=?, speaker_map=?, stats=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        session_id,
                        platform,
                        user_id,
                        new_target["user_name"],
                        bot_id,
                        new_target["bot_name"],
                        json_dumps(speaker_map),
                        json_dumps(stats),
                        now,
                        batch_id,
                    ),
                )
                counts["batch"] = int(batch_cur.rowcount or 0)
            self._embedding_candidate_cache.clear()
            self._embedding_candidate_cache_revision = ""
        return counts

    async def repair_chat_import_identity_links(
        self,
        *,
        batch_id: str,
        session_id: str,
        entity_links: dict[str, dict[str, dict[str, str]]] | None = None,
    ) -> dict[str, int]:
        return await asyncio.to_thread(
            self._repair_chat_import_identity_links_sync,
            batch_id,
            session_id,
            entity_links or {},
        )

    def _repair_chat_import_identity_links_sync(
        self,
        batch_id: str,
        session_id: str,
        entity_links: dict[str, dict[str, dict[str, str]]],
    ) -> dict[str, int]:
        batch_id = clean_text(batch_id, 120)
        session_id = clean_text(session_id, 200)
        if not batch_id or not session_id:
            return {"memories": 0, "entities": 0, "timeline": 0, "batch": 0}
        repaired_memories = 0
        repaired_entities = 0
        now = utc_now()
        with self._lock:
            with self._transaction_sync():
                rows = self._conn.execute(
                    "SELECT * FROM memories WHERE import_batch_id=?",
                    (batch_id,),
                ).fetchall()
                for row in rows:
                    link = entity_links.get(clean_text(row["id"], 120), {})

                    def resolved(prefix: str) -> tuple[str, str, str, str]:
                        current = (
                            clean_text(row[f"{prefix}_kind"], 40),
                            clean_text(row[f"{prefix}_id"], 120),
                            clean_text(row[f"{prefix}_name"], 80),
                            clean_text(row[f"{prefix}_role"], 80),
                        )
                        candidate = link.get(prefix) if isinstance(link.get(prefix), dict) else {}
                        candidate_id = clean_text(candidate.get("id"), 120)
                        if not candidate_id:
                            return current
                        return (
                            clean_text(candidate.get("kind"), 40) or current[0],
                            candidate_id,
                            clean_text(candidate.get("name"), 80) or current[2],
                            clean_text(candidate.get("role"), 80) or current[3],
                        )

                    subject = resolved("subject")
                    object_ref = resolved("object")
                    entity_changed = (
                        subject != (
                            clean_text(row["subject_kind"], 40), clean_text(row["subject_id"], 120),
                            clean_text(row["subject_name"], 80), clean_text(row["subject_role"], 80),
                        )
                        or object_ref != (
                            clean_text(row["object_kind"], 40), clean_text(row["object_id"], 120),
                            clean_text(row["object_name"], 80), clean_text(row["object_role"], 80),
                        )
                    )
                    session_changed = clean_text(row["session_id"], 200) != session_id
                    if not entity_changed and not session_changed:
                        continue
                    atom = self._memory_atom_record_for_row(
                        row,
                        subject_kind=subject[0],
                        subject_id=subject[1],
                        subject_name=subject[2],
                        subject_role=subject[3],
                        object_kind=object_ref[0],
                        object_id=object_ref[1],
                        object_name=object_ref[2],
                        object_role=object_ref[3],
                        session_id=session_id,
                    )
                    self._conn.execute(
                        """
                        UPDATE memories
                        SET subject_kind=?, subject_id=?, subject_name=?, subject_role=?,
                            object_kind=?, object_id=?, object_name=?, object_role=?,
                            session_id=?, canonical_key=?, content_fingerprint=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            *subject,
                            *object_ref,
                            session_id,
                            atom.canonical_key,
                            atom.content_fingerprint,
                            now,
                            row["id"],
                        ),
                    )
                    repaired_memories += 1
                    repaired_entities += int(entity_changed)
                timeline_cur = self._conn.execute(
                    "UPDATE timeline SET session_id=? WHERE import_batch_id=? AND session_id!=?",
                    (session_id, batch_id, session_id),
                )
                batch_cur = self._conn.execute(
                    "UPDATE chat_import_batches SET session_id=?, updated_at=? WHERE id=? AND session_id!=?",
                    (session_id, now, batch_id, session_id),
                )
        return {
            "memories": repaired_memories,
            "entities": repaired_entities,
            "timeline": int(timeline_cur.rowcount or 0),
            "batch": int(batch_cur.rowcount or 0),
        }

    async def neutralize_chat_import_summary_perspective(self, batch_id: str) -> dict[str, int]:
        return await asyncio.to_thread(self._neutralize_chat_import_summary_perspective_sync, batch_id)

    def _neutralize_chat_import_summary_perspective_sync(self, batch_id: str) -> dict[str, int]:
        batch_id = clean_text(batch_id, 120)
        if not batch_id:
            return {"memories": 0, "embeddings_removed": 0}
        updated = 0
        embeddings_removed = 0
        now = utc_now()
        with self._lock:
            with self._transaction_sync():
                rows = self._conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE import_batch_id=? AND memory_type='conversation_summary'
                    """,
                    (batch_id,),
                ).fetchall()
                for row in rows:
                    metadata = json_loads(row["metadata"], {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    try:
                        detail_version = int(metadata.get("detail_schema_version") or 0)
                    except (TypeError, ValueError):
                        detail_version = 0
                    if (
                        clean_text(metadata.get("summary_perspective"), 40) == "neutral_third_person"
                        and detail_version >= 1
                    ):
                        continue
                    canonical = clean_text(metadata.get("canonical_summary"), 1600)
                    current = clean_text(row["content"], 4000)
                    if not canonical or canonical == current:
                        continue
                    metadata.setdefault("legacy_perspective_summary", current)
                    metadata["summary_perspective"] = "neutral_third_person"
                    atom = self._memory_atom_record_for_row(
                        row,
                        reset_semantic_keys=True,
                        content=canonical,
                        metadata=json_dumps(metadata),
                    )
                    self._conn.execute(
                        """
                        UPDATE memories
                        SET content=?, metadata=?, canonical_key=?, content_fingerprint=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            canonical,
                            json_dumps(metadata),
                            atom.canonical_key,
                            atom.content_fingerprint,
                            now,
                            row["id"],
                        ),
                    )
                    embeddings_removed += int(
                        self._conn.execute(
                            "DELETE FROM memory_embeddings WHERE memory_id=?",
                            (row["id"],),
                        ).rowcount or 0
                    )
                    refreshed = self._conn.execute(
                        "SELECT * FROM memories WHERE id=?",
                        (row["id"],),
                    ).fetchone()
                    self._upsert_memory_fts_row(refreshed)
                    updated += 1
        return {"memories": updated, "embeddings_removed": embeddings_removed}

    async def update_chat_import_summary_detail(
        self,
        *,
        memory_id: str,
        detailed_summary: str,
        canonical_summary: str,
        detail_schema_version: int,
    ) -> dict[str, int]:
        return await asyncio.to_thread(
            self._update_chat_import_summary_detail_sync,
            memory_id,
            detailed_summary,
            canonical_summary,
            detail_schema_version,
        )

    def _update_chat_import_summary_detail_sync(
        self,
        memory_id: str,
        detailed_summary: str,
        canonical_summary: str,
        detail_schema_version: int,
    ) -> dict[str, int]:
        memory_id = clean_text(memory_id, 120)
        detailed_summary = clean_text(detailed_summary, 2200)
        canonical_summary = clean_text(canonical_summary, 800)
        if not memory_id or not detailed_summary:
            return {"memories": 0, "embeddings_removed": 0}
        with self._lock:
            with self._transaction_sync():
                row = self._conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE id=? AND source_plugin='historical_chat_import'
                      AND memory_type='conversation_summary'
                    """,
                    (memory_id,),
                ).fetchone()
                if not row:
                    return {"memories": 0, "embeddings_removed": 0}
                metadata = json_loads(row["metadata"], {})
                if not isinstance(metadata, dict):
                    metadata = {}
                current = clean_text(row["content"], 4000)
                canonical_summary = canonical_summary or clean_text(metadata.get("canonical_summary"), 800) or current
                if current != detailed_summary:
                    metadata.setdefault("legacy_brief_summary", current)
                metadata["canonical_summary"] = canonical_summary
                metadata["summary_perspective"] = "neutral_third_person"
                metadata["detail_schema_version"] = max(1, int(detail_schema_version or 1))
                atom = self._memory_atom_record_for_row(
                    row,
                    reset_semantic_keys=True,
                    content=detailed_summary,
                    metadata=json_dumps(metadata),
                )
                self._conn.execute(
                    """
                    UPDATE memories
                    SET content=?, metadata=?, canonical_key=?, content_fingerprint=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        detailed_summary,
                        json_dumps(metadata),
                        atom.canonical_key,
                        atom.content_fingerprint,
                        utc_now(),
                        memory_id,
                    ),
                )
                removed = int(
                    self._conn.execute(
                        "DELETE FROM memory_embeddings WHERE memory_id=?",
                        (memory_id,),
                    ).rowcount or 0
                )
                refreshed = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
                self._upsert_memory_fts_row(refreshed)
        return {"memories": 1, "embeddings_removed": removed}

    async def update_chat_import_daily_digest(
        self,
        *,
        batch_id: str,
        date: str,
        detailed_summary: str,
        segment_ids: list[str],
        source_message_ids: list[str],
        detail_schema_version: int,
    ) -> dict[str, int]:
        return await asyncio.to_thread(
            self._update_chat_import_daily_digest_sync,
            batch_id,
            date,
            detailed_summary,
            segment_ids,
            source_message_ids,
            detail_schema_version,
        )

    def _update_chat_import_daily_digest_sync(
        self,
        batch_id: str,
        date: str,
        detailed_summary: str,
        segment_ids: list[str],
        source_message_ids: list[str],
        detail_schema_version: int,
    ) -> dict[str, int]:
        batch_id = clean_text(batch_id, 120)
        date = clean_text(date, 20)
        detailed_summary = clean_text(detailed_summary, 2200)
        if not batch_id or not date or not detailed_summary:
            return {"memories": 0, "embeddings_removed": 0}
        with self._lock:
            with self._transaction_sync():
                row = self._conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE import_batch_id=? AND memory_type='daily_digest'
                      AND json_valid(metadata) AND json_extract(metadata, '$.date')=?
                    ORDER BY created_at ASC LIMIT 1
                    """,
                    (batch_id, date),
                ).fetchone()
                if not row:
                    return {"memories": 0, "embeddings_removed": 0}
                metadata = json_loads(row["metadata"], {})
                if not isinstance(metadata, dict):
                    metadata = {}
                current = clean_text(row["content"], 4000)
                if current != detailed_summary:
                    metadata.setdefault("legacy_brief_summary", current)
                metadata["segment_ids"] = [clean_text(item, 120) for item in segment_ids if clean_text(item, 120)][:32]
                metadata["source_message_ids"] = [
                    clean_text(item, 120) for item in source_message_ids if clean_text(item, 120)
                ][:64]
                metadata["summary_perspective"] = "neutral_third_person"
                metadata["detail_schema_version"] = max(1, int(detail_schema_version or 1))
                atom = self._memory_atom_record_for_row(
                    row,
                    reset_semantic_keys=True,
                    content=detailed_summary,
                    evidence="；".join(metadata["source_message_ids"]),
                    metadata=json_dumps(metadata),
                )
                evidence = "；".join(metadata["source_message_ids"])
                self._conn.execute(
                    """
                    UPDATE memories
                    SET content=?, evidence=?, metadata=?, canonical_key=?, content_fingerprint=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        detailed_summary,
                        evidence,
                        json_dumps(metadata),
                        atom.canonical_key,
                        atom.content_fingerprint,
                        utc_now(),
                        row["id"],
                    ),
                )
                removed = int(
                    self._conn.execute(
                        "DELETE FROM memory_embeddings WHERE memory_id=?",
                        (row["id"],),
                    ).rowcount or 0
                )
                refreshed = self._conn.execute("SELECT * FROM memories WHERE id=?", (row["id"],)).fetchone()
                self._upsert_memory_fts_row(refreshed)
        return {"memories": 1, "embeddings_removed": removed}

    async def list_chat_import_memories(self, batch_id: str) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_chat_import_memories_sync,
            batch_id,
        )

    def _list_chat_import_memories_sync(self, batch_id: str) -> list[MemoryRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM memories
                WHERE import_batch_id=? AND lifecycle!='archived'
                ORDER BY importance DESC, COALESCE(NULLIF(occurred_at, ''), created_at) ASC
                """,
                (clean_text(batch_id, 120),),
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    async def list_chat_import_memories_missing_embeddings(
        self,
        batch_id: str,
        provider_id: str,
        *,
        include_pending: bool = False,
    ) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_chat_import_memories_missing_embeddings_sync,
            batch_id,
            provider_id,
            include_pending,
        )

    def _list_chat_import_memories_missing_embeddings_sync(
        self,
        batch_id: str,
        provider_id: str,
        include_pending: bool,
    ) -> list[MemoryRecord]:
        where = "m.import_batch_id=? AND m.lifecycle!='archived'"
        if not include_pending:
            where += " AND m.review_status!='pending'"
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT m.* FROM memories m
                LEFT JOIN memory_embeddings e
                  ON e.memory_id=m.id AND e.provider_id=?
                WHERE {where} AND (e.memory_id IS NULL OR e.text_hash='')
                ORDER BY m.importance DESC, COALESCE(NULLIF(m.occurred_at, ''), m.created_at) ASC
                """,
                (clean_text(provider_id, 160), clean_text(batch_id, 120)),
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    def _rollback_chat_import_batch_sync(self, batch_id: str) -> dict[str, int]:
        batch_id = clean_text(batch_id, 120)
        deleted = {"memories": 0, "timeline": 0, "segments": 0}
        with self._lock:
            with self._transaction_sync():
                memory_rows = self._conn.execute(
                    "SELECT id FROM memories WHERE import_batch_id=?",
                    (batch_id,),
                ).fetchall()
                memory_ids = [clean_text(row["id"], 120) for row in memory_rows]
                for memory_id in memory_ids:
                    self._conn.execute("DELETE FROM review_queue WHERE memory_id=?", (memory_id,))
                    self._conn.execute("DELETE FROM memory_embeddings WHERE memory_id=?", (memory_id,))
                    self._conn.execute("DELETE FROM relationship_edges WHERE source_memory_id=?", (memory_id,))
                    self._conn.execute("DELETE FROM knowledge_edges WHERE source_memory_id=?", (memory_id,))
                    self._delete_memory_fts_row(memory_id)
                    deleted["memories"] += int(
                        self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,)).rowcount or 0
                    )
                deleted["timeline"] = int(
                    self._conn.execute("DELETE FROM timeline WHERE import_batch_id=?", (batch_id,)).rowcount or 0
                )
                deleted["segments"] = int(
                    self._conn.execute("DELETE FROM chat_import_segments WHERE batch_id=?", (batch_id,)).rowcount or 0
                )
                self._conn.execute(
                    """
                    UPDATE chat_import_batches
                    SET state='rolled_back', checkpoint_segment=0, completed_segments=0,
                        summary_memory_count=0, important_event_count=0,
                        relationship_observation_count=0, error='', updated_at=?
                    WHERE id=?
                    """,
                    (utc_now(), batch_id),
                )
        return deleted

    async def recent_timeline(
        self,
        limit: int = 10,
        scope: str = "",
        session_id: str = "",
        entity_id: str = "",
        *,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._recent_timeline_sync,
            limit,
            scope,
            session_id,
            entity_id,
            offset,
        )

    def _recent_timeline_sync(
        self,
        limit: int,
        scope: str,
        session_id: str,
        entity_id: str,
        offset: int,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, int(limit))
        safe_offset = max(0, int(offset))
        if scope and session_id and entity_id:
            return self._recent_timeline_entity_split_sync(
                safe_limit, scope, session_id, entity_id, safe_offset
            )
        params: list[Any] = []
        where = "1=1"
        if scope:
            where += " AND scope=?"
            params.append(scope)
        if session_id:
            where += " AND session_id=?"
            params.append(session_id)
        if entity_id:
            where += " AND (subject_id=? OR object_id=?)"
            params.extend([entity_id, entity_id])
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM timeline
                WHERE {where}
                ORDER BY occurred_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [safe_limit, safe_offset],
            ).fetchall()
        return [dict(row) for row in rows]

    def _recent_timeline_entity_split_sync(
        self,
        limit: int,
        scope: str,
        session_id: str,
        entity_id: str,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Read the subject/object branches through dedicated indexes and merge.

        ``(subject_id=? OR object_id=?)`` forces a scan plus temp B-tree on
        large sessions. Two index-driven branch reads keep the same rows and
        ordering: any row in the merged top-(offset+limit) must be in its own
        branch's top-(offset+limit), so bounded branch reads are exact.
        """
        branch_size = limit + offset
        merged: dict[str, dict[str, Any]] = {}
        with self._lock:
            for column in ("subject_id", "object_id"):
                rows = self._conn.execute(
                    f"""
                    SELECT * FROM timeline
                    WHERE scope=? AND session_id=? AND {column}=?
                    ORDER BY occurred_at DESC, created_at DESC
                    LIMIT ?
                    """,
                    (scope, session_id, entity_id, branch_size),
                ).fetchall()
                for row in rows:
                    merged.setdefault(str(row["id"]), dict(row))
        ordered = sorted(
            merged.values(),
            key=lambda row: (str(row.get("occurred_at") or ""), str(row.get("created_at") or "")),
            reverse=True,
        )
        return ordered[offset : offset + limit]

    async def recent_cross_window_timeline(
        self,
        *,
        source_scope: str,
        current_session_id: str,
        since_at: str,
        limit: int = 48,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._recent_cross_window_timeline_sync,
            source_scope,
            current_session_id,
            since_at,
            limit,
        )

    def _recent_cross_window_timeline_sync(
        self,
        source_scope: str,
        current_session_id: str,
        since_at: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        scope = clean_text(source_scope, 40)
        session_id = clean_text(current_session_id, 200)
        cutoff = clean_text(since_at, 80)
        if scope not in {"private", "group"} or not session_id or not cutoff:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM timeline
                WHERE scope=?
                  AND session_id!=?
                  AND occurred_at>=?
                  AND event_type IN ('user_message', 'bot_response')
                ORDER BY occurred_at DESC, created_at DESC
                LIMIT ?
                """,
                (scope, session_id, cutoff, max(1, min(240, int(limit or 48)))),
            ).fetchall()
        return [dict(row) for row in rows]

    async def timeline_window(
        self,
        *,
        start_at: str,
        end_at: str,
        limit: int = 30,
        scope: str = "",
        session_id: str = "",
        entity_id: str = "",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._timeline_window_sync,
            start_at,
            end_at,
            limit,
            scope,
            session_id,
            entity_id,
        )

    def _timeline_window_sync(
        self,
        start_at: str,
        end_at: str,
        limit: int,
        scope: str,
        session_id: str,
        entity_id: str,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [clean_text(start_at, 80), clean_text(end_at, 80)]
        where = "occurred_at >= ? AND occurred_at < ?"
        if scope:
            where += " AND scope=?"
            params.append(clean_text(scope, 40))
        if session_id:
            where += " AND session_id=?"
            params.append(clean_text(session_id, 200))
        if entity_id:
            where += " AND (subject_id=? OR object_id=?)"
            params.extend([clean_text(entity_id, 120), clean_text(entity_id, 120)])
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM timeline
                WHERE {where}
                ORDER BY occurred_at DESC, created_at DESC
                LIMIT ?
                """,
                params + [max(1, int(limit or 1))],
            ).fetchall()
        return [dict(row) for row in rows]

    async def get_timeline_by_ids(self, event_ids: list[str]) -> dict[str, dict[str, Any]]:
        return await self._run_recoverable_database_operation(self._get_timeline_by_ids_sync, event_ids)

    def _get_timeline_by_ids_sync(self, event_ids: list[str]) -> dict[str, dict[str, Any]]:
        ids = list(
            dict.fromkeys(
                clean_text(event_id, 160)
                for event_id in event_ids
                if clean_text(event_id, 160)
            )
        )
        if not ids:
            return {}
        rows: list[Any] = []
        with self._lock:
            for index in range(0, len(ids), 500):
                chunk = ids[index:index + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(
                    self._conn.execute(
                        f"SELECT * FROM timeline WHERE id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
        return {clean_text(row["id"], 160): dict(row) for row in rows}

    async def unsummarized_timeline_window(
        self,
        *,
        session_id: str,
        scope: str = "",
        limit: int = 40,
        after_timeline_id: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._unsummarized_timeline_window_sync,
            session_id,
            scope,
            limit,
            after_timeline_id,
        )

    def _unsummarized_timeline_window_sync(
        self,
        session_id: str,
        scope: str,
        limit: int,
        after_timeline_id: str = "",
    ) -> dict[str, Any]:
        params: list[Any] = [clean_text(session_id, 200)]
        where = "session_id=? AND summarized_at=''"
        if scope:
            where += " AND scope=?"
            params.append(clean_text(scope, 40))
        with self._lock:
            cursor = None
            if clean_text(after_timeline_id, 160):
                cursor = self._conn.execute(
                    "SELECT occurred_at, created_at FROM timeline WHERE id=? AND session_id=?",
                    (clean_text(after_timeline_id, 160), clean_text(session_id, 200)),
                ).fetchone()
            if cursor:
                where += " AND (occurred_at > ? OR (occurred_at = ? AND created_at > ?))"
                params.extend(
                    [
                        clean_text(cursor["occurred_at"], 80),
                        clean_text(cursor["occurred_at"], 80),
                        clean_text(cursor["created_at"], 80),
                    ]
                )
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM timeline WHERE {where}",
                params,
            ).fetchone()[0]
            first = self._conn.execute(
                f"""
                SELECT occurred_at
                FROM timeline
                WHERE {where}
                ORDER BY occurred_at ASC, created_at ASC
                LIMIT 1
                """,
                params,
            ).fetchone()
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM timeline
                WHERE {where}
                ORDER BY occurred_at ASC, created_at ASC
                LIMIT ?
                """,
                params + [max(1, int(limit))],
            ).fetchall()
        return {
            "total": int(total or 0),
            "first_occurred_at": first["occurred_at"] if first else "",
            "rows": [dict(row) for row in rows],
        }

    async def mark_timeline_summarized(self, event_ids: list[str]) -> int:
        return await asyncio.to_thread(self._mark_timeline_summarized_sync, event_ids)

    def _mark_timeline_summarized_sync(self, event_ids: list[str], _commit: bool = True) -> int:
        ids = [clean_text(event_id, 120) for event_id in event_ids if clean_text(event_id, 120)]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE timeline SET summarized_at=? WHERE id IN ({placeholders})",
                [utc_now()] + ids,
            )
            # _commit=False 用于批量导入：由外层事务统一提交，避免逐次 fsync。
            if _commit:
                self._conn.commit()
        return int(cur.rowcount or 0)

    async def get_summary_failure(self, session_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_summary_failure_sync, session_id)

    def _get_summary_failure_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM summary_failures WHERE session_id=?",
                (clean_text(session_id, 200),),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["metadata"] = json_loads(item.get("metadata"), {})
        return item

    async def record_summary_failure(
        self,
        *,
        session_id: str,
        scope: str,
        start_timeline_id: str,
        end_timeline_id: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._record_summary_failure_sync,
            session_id,
            scope,
            start_timeline_id,
            end_timeline_id,
            error,
            metadata or {},
        )

    def _record_summary_failure_sync(
        self,
        session_id: str,
        scope: str,
        start_timeline_id: str,
        end_timeline_id: str,
        error: str,
        metadata: dict[str, Any],
    ) -> int:
        now = utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO summary_failures(
                    session_id, scope, start_timeline_id, end_timeline_id,
                    retry_count, last_error, metadata, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    scope=excluded.scope,
                    start_timeline_id=excluded.start_timeline_id,
                    end_timeline_id=excluded.end_timeline_id,
                    retry_count=summary_failures.retry_count + 1,
                    last_error=excluded.last_error,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (
                    clean_text(session_id, 200),
                    clean_text(scope, 40),
                    clean_text(start_timeline_id, 120),
                    clean_text(end_timeline_id, 120),
                    clean_text(redact_sensitive_text(error), 1000),
                    json_dumps(redact_sensitive_value(metadata)),
                    now,
                    now,
                ),
            )
            row = self._conn.execute(
                "SELECT retry_count FROM summary_failures WHERE session_id=?",
                (clean_text(session_id, 200),),
            ).fetchone()
            self._conn.commit()
        return int(row["retry_count"] if row else 1)

    async def clear_summary_failure(self, session_id: str) -> bool:
        return await asyncio.to_thread(self._clear_summary_failure_sync, session_id)

    async def mark_summary_failure_dead_letter(self, session_id: str, max_retries: int) -> bool:
        return await asyncio.to_thread(
            self._mark_summary_failure_dead_letter_sync,
            session_id,
            max_retries,
        )

    async def mark_summary_failure_cooldown(
        self,
        session_id: str,
        max_retries: int,
        cooldown_seconds: int,
        state: str = "transient_cooldown",
    ) -> bool:
        return await asyncio.to_thread(
            self._mark_summary_failure_state_sync,
            session_id,
            clean_text(state, 40) or "transient_cooldown",
            {
                "max_retries": max(1, int(max_retries or 1)),
                "cooldown_seconds": max(0, int(cooldown_seconds or 0)),
                "cooldown_at": utc_now(),
            },
        )

    def _mark_summary_failure_dead_letter_sync(self, session_id: str, max_retries: int) -> bool:
        return self._mark_summary_failure_state_sync(
            session_id,
            "dead_letter",
            {
                "max_retries": max(1, int(max_retries or 1)),
                "dead_letter_at": utc_now(),
            },
        )

    def _mark_summary_failure_state_sync(
        self,
        session_id: str,
        state: str,
        extra_metadata: dict[str, Any],
    ) -> bool:
        session_id = clean_text(session_id, 200)
        with self._lock:
            with self._transaction_sync():
                row = self._conn.execute(
                    "SELECT metadata FROM summary_failures WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if not row:
                    return False
                metadata = json_loads(row["metadata"], {})
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata.update(extra_metadata or {})
                metadata["state"] = clean_text(state, 40)
                cur = self._conn.execute(
                    "UPDATE summary_failures SET metadata=?, updated_at=? WHERE session_id=?",
                    (json_dumps(metadata), utc_now(), session_id),
                )
                return cur.rowcount > 0

    def _clear_summary_failure_sync(self, session_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM summary_failures WHERE session_id=?",
                (clean_text(session_id, 200),),
            )
            self._conn.commit()
        return int(cur.rowcount or 0) > 0

    async def create_cross_window_thread(
        self,
        *,
        from_session: str,
        to_session: str,
        topic: str,
        content: str,
        visibility: str = "shareable",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._create_cross_window_thread_sync,
            from_session,
            to_session,
            topic,
            content,
            visibility,
            metadata or {},
        )

    def _create_cross_window_thread_sync(
        self,
        from_session: str,
        to_session: str,
        topic: str,
        content: str,
        visibility: str,
        metadata: dict[str, Any],
    ) -> str:
        now = utc_now()
        row_id = new_id("thread")
        topic = redact_sensitive_text(topic)
        content = redact_sensitive_text(content)
        metadata = redact_sensitive_value(metadata)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO cross_window_threads(
                    id, status, from_session, to_session, topic, content,
                    visibility, metadata, created_at, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row_id,
                    "open",
                    clean_text(from_session, 200),
                    clean_text(to_session, 200),
                    clean_text(topic, 200),
                    clean_text(content, 4000),
                    clean_text(visibility, 40),
                    json_dumps(metadata),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return row_id

    async def list_cross_window_threads(
        self,
        status: str = "open",
        limit: int = 20,
        session_id: str = "",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_cross_window_threads_sync, status, limit, session_id)

    def _list_cross_window_threads_sync(
        self,
        status: str,
        limit: int,
        session_id: str,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = "1=1"
        if status and status != "all":
            where += " AND status=?"
            params.append(status)
        if session_id:
            where += " AND (from_session=? OR to_session=?)"
            params.extend([session_id, session_id])
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM cross_window_threads
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params + [max(1, int(limit))],
            ).fetchall()
        return [dict(row) for row in rows]

    async def update_cross_window_thread_status(self, thread_id: str, status: str) -> bool:
        return await asyncio.to_thread(self._update_cross_window_thread_status_sync, thread_id, status)

    def _update_cross_window_thread_status_sync(self, thread_id: str, status: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE cross_window_threads SET status=?, updated_at=? WHERE id=?",
                (clean_text(status, 40), utc_now(), clean_text(thread_id, 120)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    async def add_injection_log(
        self,
        *,
        session_id: str,
        scope: str,
        query: str,
        selected_memory_ids: list[str],
        blocked_reasons: list[dict[str, Any]],
        injection_chars: int,
    ) -> str:
        return await asyncio.to_thread(
            self._add_injection_log_sync,
            session_id,
            scope,
            query,
            selected_memory_ids,
            blocked_reasons,
            injection_chars,
        )

    def _add_injection_log_sync(
        self,
        session_id: str,
        scope: str,
        query: str,
        selected_memory_ids: list[str],
        blocked_reasons: list[dict[str, Any]],
        injection_chars: int,
    ) -> str:
        row_id = new_id("inj")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO injection_logs(
                    id, session_id, scope, query, selected_memory_ids,
                    blocked_reasons, injection_chars, created_at
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    row_id,
                    clean_text(session_id, 200),
                    clean_text(scope, 40),
                    clean_text(redact_sensitive_text(query), 1000),
                    json_dumps(selected_memory_ids),
                    json_dumps(redact_sensitive_value(blocked_reasons[:30])),
                    max(0, int(injection_chars or 0)),
                    utc_now(),
                ),
            )
            self._conn.commit()
        return row_id

    async def recent_injection_logs(
        self,
        limit: int = 10,
        scope: str = "",
        session_id: str = "",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._recent_injection_logs_sync, limit, scope, session_id)

    def _recent_injection_logs_sync(self, limit: int, scope: str, session_id: str) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = "1=1"
        if scope:
            where += " AND scope=?"
            params.append(scope)
        if session_id:
            where += " AND session_id=?"
            params.append(session_id)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM injection_logs
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params + [max(1, int(limit))],
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["selected_memory_ids"] = json_loads(item.get("selected_memory_ids"), [])
            item["blocked_reasons"] = json_loads(item.get("blocked_reasons"), [])
            result.append(item)
        return result

    async def list_candidate_memories(self, limit: int = 500, include_pending: bool = False) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(self._list_candidate_memories_sync, limit, include_pending)

    def _list_candidate_memories_sync(self, limit: int, include_pending: bool) -> list[MemoryRecord]:
        with self._lock:
            rows = self._materialized_candidate_rows(self._conn, limit, include_pending)
        return [MemoryRecord.from_row(row) for row in rows]

    def _materialized_candidate_rows(
        self,
        conn: sqlite3.Connection,
        limit: int,
        include_pending: bool,
    ) -> list[Any]:
        # Bot Personal archive references (including legacy rows identified by
        # their display text) are served by a dedicated bridge and are not
        # ordinary memory documents.
        where = f"lifecycle != 'archived' AND {self._recallable_memory_sql()}"
        params: list[Any] = []
        if not include_pending:
            where += " AND review_status != 'pending'"
        return conn.execute(
            f"""
            SELECT * FROM memories
            WHERE {where}
            ORDER BY importance DESC, occurred_at DESC
            LIMIT ?
            """,
            params + [max(1, int(limit))],
        ).fetchall()

    async def list_core_memories(self, limit: int = 200) -> list[MemoryRecord]:
        """Read active core blocks without routing them through similarity search."""
        return await self._run_recoverable_database_operation(
            self._list_core_memories_sync,
            limit,
        )

    def _list_core_memories_sync(self, limit: int) -> list[MemoryRecord]:
        now = utc_now()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT *
                FROM memories
                WHERE memory_type='core_memory'
                  AND lifecycle!='archived'
                  AND review_status!='pending'
                  AND validity_status='active'
                  AND (valid_from='' OR julianday(valid_from) IS NULL OR julianday(valid_from)<=julianday(?))
                  AND (valid_to='' OR julianday(valid_to) IS NULL OR julianday(valid_to)>=julianday(?))
                ORDER BY
                    CASE
                        WHEN json_valid(metadata)
                        THEN COALESCE(CAST(json_extract(metadata, '$.core_priority') AS INTEGER), 50)
                        ELSE 50
                    END DESC,
                    updated_at DESC,
                    id ASC
                LIMIT ?
                """,
                (now, now, max(1, min(1000, int(limit or 200)))),
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    async def save_core_memory(
        self,
        record: MemoryRecord,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(
            self._save_core_memory_sync,
            record,
            expected_revision,
        )

    def _save_core_memory_sync(
        self,
        record: MemoryRecord,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        """Atomically create or replace one labeled core-memory block."""
        record.memory_type = "core_memory"
        record.ensure_defaults()
        with self._lock:
            with self._transaction_sync():
                current = self._conn.execute(
                    "SELECT * FROM memories WHERE id=?",
                    (record.id,),
                ).fetchone()
                current_revision = 0
                if current is not None:
                    if clean_text(current["memory_type"], 80) != "core_memory":
                        return {"ok": False, "code": "memory_type_conflict"}
                    current_metadata = json_loads(current["metadata"], {})
                    if isinstance(current_metadata, dict):
                        try:
                            current_revision = max(0, int(current_metadata.get("core_revision") or 0))
                        except (TypeError, ValueError):
                            current_revision = 0
                    record.created_at = clean_text(current["created_at"], 80) or record.created_at
                if expected_revision is not None and int(expected_revision) != current_revision:
                    return {
                        "ok": False,
                        "code": "revision_conflict",
                        "current_revision": current_revision,
                    }

                metadata = dict(record.metadata) if isinstance(record.metadata, dict) else {}
                next_revision = current_revision + 1
                metadata["core_revision"] = next_revision
                metadata["core_memory"] = True
                record.metadata = metadata
                record.updated_at = utc_now()
                record.canonical_key = ""
                record.content_fingerprint = ""
                data = record.to_db()
                columns = ", ".join(data.keys())
                placeholders = ", ".join(f":{key}" for key in data.keys())
                updates = ", ".join(
                    f"{key}=excluded.{key}" for key in data.keys() if key != "id"
                )
                self._conn.execute(
                    f"INSERT INTO memories ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT(id) DO UPDATE SET {updates}",
                    data,
                )
                row = self._conn.execute(
                    "SELECT * FROM memories WHERE id=?",
                    (record.id,),
                ).fetchone()
                self._upsert_memory_fts_row(row)
        return {"ok": True, "id": record.id, "revision": next_revision}

    async def list_schedule_context_memories(
        self,
        *,
        session_id: str = "",
        user_id: str = "",
        bot_id: str = "",
        limit: int = 36,
        strict_session_only: bool = False,
    ) -> list[MemoryRecord]:
        """Read a small schedule-focused snapshot without waiting on the shared writer lock."""
        return await asyncio.to_thread(
            self._list_schedule_context_memories_sync,
            session_id,
            user_id,
            bot_id,
            limit,
            strict_session_only,
        )

    def _list_schedule_context_memories_sync(
        self,
        session_id: str,
        user_id: str,
        bot_id: str,
        limit: int,
        strict_session_only: bool,
    ) -> list[MemoryRecord]:
        session_id = clean_text(session_id, 200)
        user_id = clean_text(user_id, 120)
        bot_id = clean_text(bot_id, 120)
        if not self.db_path.is_file():
            return []
        bot_types = (
            "schedule_fragment",
            "persona_life",
            "self_action",
            "proactive_message",
            "reading_memory",
            "creative_work",
            "search_action",
            "image_action",
            "qzone_action",
            "companion_note",
        )
        profile_types = (
            "user_profile",
            "user_preference",
            "relationship_claim",
        )
        bot_placeholders = ",".join("?" for _ in bot_types)
        profile_placeholders = ",".join("?" for _ in profile_types)
        clauses = [
            """
            (
                visibility='bot_self'
                AND memory_type IN (BOT_TYPE_PLACEHOLDERS)
                AND (
                    scope!='private'
                    OR session_id=''
                    OR session_id=?
                    OR (? != '' AND (subject_id=? OR object_id=?))
                )
                AND (
                    CASE
                        WHEN json_valid(metadata)
                        THEN COALESCE(CAST(json_extract(metadata, '$.owner_bot_id') AS TEXT), '')
                        ELSE ''
                    END
                ) IN ('', 'self', ?)
                AND (subject_kind!='bot' OR subject_id IN ('', 'self', ?))
                AND (object_kind!='bot' OR object_id IN ('', 'self', ?))
            )
            """.replace("BOT_TYPE_PLACEHOLDERS", bot_placeholders)
        ]
        params: list[Any] = [
            *bot_types,
            session_id,
            user_id,
            user_id,
            user_id,
            bot_id,
            bot_id,
            bot_id,
        ]
        if user_id:
            clauses.append(
                f"""
                (
                    scope='private'
                    AND visibility IN ('private_pair', 'shareable')
                    AND memory_type IN ({profile_placeholders})
                    AND (session_id=? OR subject_id=? OR object_id=?)
                    AND (
                        CASE
                            WHEN json_valid(metadata)
                            THEN COALESCE(CAST(json_extract(metadata, '$.owner_bot_id') AS TEXT), '')
                            ELSE ''
                        END
                    ) IN ('', 'self', ?)
                    AND (subject_kind!='bot' OR subject_id IN ('', 'self', ?))
                    AND (object_kind!='bot' OR object_id IN ('', 'self', ?))
                )
                """
            )
            params.extend([*profile_types, session_id, user_id, user_id, bot_id, bot_id, bot_id])
        # This is the dedicated Companion schedule context path; Bot Personal
        # records remain available here and are not part of ordinary recall.
        where = "lifecycle!='archived' AND review_status!='pending' AND (" + " OR ".join(clauses) + ")"
        if strict_session_only:
            if not session_id:
                return []
            where += " AND session_id=?"
            params.append(session_id)
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.35, check_same_thread=False)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA busy_timeout=350")
            type_count = max(1, len(bot_types) + (len(profile_types) if user_id else 0))
            # 提高 per-type 上限（默认时间倒序仅取最少 2 条），让跨天记录更容易进入候选；
            # 上限从 12 提到 20，最终仍受 120 条总量约束。
            per_type_limit = max(2, min(20, (max(1, int(limit or 36)) + type_count - 1) // type_count))
            rows = connection.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        memories.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY memory_type
                            ORDER BY
                                COALESCE(NULLIF(occurred_at, ''), NULLIF(updated_at, ''), created_at) DESC,
                                importance DESC
                        ) AS fast_type_rank
                    FROM memories
                    WHERE {where}
                )
                SELECT *
                FROM ranked
                WHERE fast_type_rank<=?
                ORDER BY
                    COALESCE(NULLIF(occurred_at, ''), NULLIF(updated_at, ''), created_at) DESC,
                    importance DESC
                """,
                [*params, per_type_limit],
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows[:120]]

    async def list_current_window_candidate_memories(
        self,
        *,
        scope: str,
        session_id: str = "",
        user_id: str = "",
        group_id: str = "",
        limit: int = 600,
        include_pending: bool = False,
    ) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_current_window_candidate_memories_sync,
            scope,
            session_id,
            user_id,
            group_id,
            limit,
            include_pending,
        )

    def _list_current_window_candidate_memories_sync(
        self,
        scope: str,
        session_id: str,
        user_id: str,
        group_id: str,
        limit: int,
        include_pending: bool,
    ) -> list[MemoryRecord]:
        with self._lock:
            rows = self._current_window_candidate_rows(
                self._conn, scope, session_id, user_id, group_id, limit, include_pending
            )
        return [MemoryRecord.from_row(row) for row in rows]

    def _current_window_candidate_rows(
        self,
        conn: sqlite3.Connection,
        scope: str,
        session_id: str,
        user_id: str,
        group_id: str,
        limit: int,
        include_pending: bool,
    ) -> list[Any]:
        scope = clean_text(scope, 40).lower()
        session_id = clean_text(session_id, 200)
        user_id = clean_text(user_id, 120)
        group_id = clean_text(group_id, 120)
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id=?")
            params.append(session_id)
        if scope == "group" and group_id:
            clauses.append("(scope='group' AND group_id=?)")
            params.append(group_id)
        elif scope == "private" and user_id:
            clauses.append("(scope='private' AND (subject_id=? OR object_id=?))")
            params.extend([user_id, user_id])
        if not clauses:
            return []
        where = f"lifecycle != 'archived' AND {self._recallable_memory_sql()} AND (" + " OR ".join(clauses) + ")"
        if not include_pending:
            where += " AND review_status != 'pending'"
        return conn.execute(
            f"""
            SELECT *
            FROM memories
            WHERE {where}
            ORDER BY importance DESC,
                     COALESCE(NULLIF(occurred_at, ''), NULLIF(updated_at, ''), created_at) DESC
            LIMIT ?
            """,
            params + [max(1, int(limit or 1))],
        ).fetchall()

    async def list_time_window_candidate_memories(
        self,
        start_at: str,
        end_at: str,
        limit: int = 1200,
        include_pending: bool = False,
    ) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_time_window_candidate_memories_sync,
            start_at,
            end_at,
            limit,
            include_pending,
        )

    def _list_time_window_candidate_memories_sync(
        self,
        start_at: str,
        end_at: str,
        limit: int,
        include_pending: bool,
    ) -> list[MemoryRecord]:
        with self._lock:
            rows = self._time_window_candidate_rows(self._conn, start_at, end_at, limit, include_pending)
        return [MemoryRecord.from_row(row) for row in rows]

    def _time_window_candidate_rows(
        self,
        conn: sqlite3.Connection,
        start_at: str,
        end_at: str,
        limit: int,
        include_pending: bool,
    ) -> list[Any]:
        start = clean_text(start_at, 80)
        end = clean_text(end_at, 80)
        if not start or not end:
            return []
        where = f"lifecycle != 'archived' AND {self._recallable_memory_sql()}"
        params: list[Any] = [start, end, start, end, start, end]
        if not include_pending:
            where += " AND review_status != 'pending'"
        return conn.execute(
            f"""
            SELECT *
            FROM memories
            WHERE {where}
              AND (
                (occurred_at >= ? AND occurred_at < ?)
                OR (created_at >= ? AND created_at < ?)
                OR (updated_at >= ? AND updated_at < ?)
              )
            ORDER BY
                COALESCE(NULLIF(occurred_at, ''), NULLIF(updated_at, ''), created_at) DESC,
                importance DESC
            LIMIT ?
            """,
            params + [max(1, int(limit or 1))],
        ).fetchall()

    async def list_retrieval_candidate_bundle(
        self,
        *,
        materialize_limit: int,
        current_window: dict[str, Any] | None,
        fts_terms: list[str],
        fts_limit: int,
        keyword_terms: list[str],
        keyword_limit: int,
        keyword_fallback_min_fts: int,
        time_window: tuple[str, str, int] | None,
        include_pending: bool = False,
    ) -> dict[str, Any]:
        """Load all retrieval candidate sources in one read-only pass.

        Replaces four separate ``asyncio.gather`` store calls (each of which
        re-acquired the single write connection lock) with a single threaded
        pass over a dedicated read-only connection. Under WAL this reader runs
        concurrently with writes, so candidate loading no longer serializes
        behind the main lock. Keyword-fallback semantics are preserved: the
        keyword scan only runs when FTS produced too few candidates.

        Corresponds to optimization_plan.md §6.1/§6.2.
        """
        return await asyncio.to_thread(
            self._list_retrieval_candidate_bundle_sync,
            materialize_limit,
            current_window or {},
            fts_terms,
            fts_limit,
            keyword_terms,
            keyword_limit,
            keyword_fallback_min_fts,
            time_window,
            include_pending,
        )

    def _list_retrieval_candidate_bundle_sync(
        self,
        materialize_limit: int,
        current_window: dict[str, Any],
        fts_terms: list[str],
        fts_limit: int,
        keyword_terms: list[str],
        keyword_limit: int,
        keyword_fallback_min_fts: int,
        time_window: tuple[str, str, int] | None,
        include_pending: bool,
    ) -> dict[str, Any]:
        bundle_started = time.perf_counter()
        conn, lock = self._read_connection_for_bundle()
        with lock:
            lock_acquired_at = time.perf_counter()
            ranked_rows = self._materialized_candidate_rows(conn, materialize_limit, include_pending)
            current_window_rows = self._current_window_candidate_rows(
                conn,
                clean_text(current_window.get("scope", ""), 40),
                clean_text(current_window.get("session_id", ""), 200),
                clean_text(current_window.get("user_id", ""), 120),
                clean_text(current_window.get("group_id", ""), 120),
                int(current_window.get("limit", 0) or 0),
                include_pending,
            )
            fts_rows = self._fts_candidate_rows(conn, fts_terms, fts_limit, include_pending)
            keyword_fallback_used = len(fts_rows) < max(0, int(keyword_fallback_min_fts or 0))
            keyword_rows = (
                self._keyword_candidate_rows(conn, keyword_terms, keyword_limit, include_pending)
                if keyword_fallback_used
                else []
            )
            time_rows: list[Any] = []
            if time_window is not None:
                start_at, end_at, tw_limit = time_window
                time_rows = self._time_window_candidate_rows(conn, start_at, end_at, tw_limit, include_pending)
            queries_done_at = time.perf_counter()
        parsed = {
            "ranked_candidates": [MemoryRecord.from_row_light(row) for row in ranked_rows],
            "current_window_candidates": [MemoryRecord.from_row_light(row) for row in current_window_rows],
            "fts_candidates": [MemoryRecord.from_row_light(row) for row in fts_rows],
            "keyword_candidates": [MemoryRecord.from_row_light(row) for row in keyword_rows],
            "keyword_fallback_used": keyword_fallback_used,
            "time_window_candidates": [MemoryRecord.from_row_light(row) for row in time_rows],
        }
        parsed["_timing"] = {
            "lock_wait_ms": int((lock_acquired_at - bundle_started) * 1000),
            "queries_ms": int((queries_done_at - lock_acquired_at) * 1000),
            "parse_ms": int((time.perf_counter() - queries_done_at) * 1000),
            "inner_total_ms": int((time.perf_counter() - bundle_started) * 1000),
        }
        return parsed

    async def list_fts_candidate_memories(
        self,
        terms: list[str],
        limit: int = 800,
        include_pending: bool = False,
    ) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_fts_candidate_memories_sync,
            terms,
            limit,
            include_pending,
        )

    def _list_fts_candidate_memories_sync(
        self,
        terms: list[str],
        limit: int,
        include_pending: bool,
    ) -> list[MemoryRecord]:
        with self._lock:
            rows = self._fts_candidate_rows(self._conn, terms, limit, include_pending)
        return [MemoryRecord.from_row(row) for row in rows]

    def _fts_candidate_rows(
        self,
        conn: sqlite3.Connection,
        terms: list[str],
        limit: int,
        include_pending: bool,
    ) -> list[Any]:
        if not self._fts_enabled:
            return []
        query = self._fts_match_query(terms)
        if not query:
            return []
        where = f"m.lifecycle != 'archived' AND {self._recallable_memory_sql('m')}"
        params: list[Any] = [query]
        if not include_pending:
            where += " AND m.review_status != 'pending'"
        try:
            return conn.execute(
                f"""
                SELECT m.*
                FROM memory_fts
                JOIN memories m ON m.id = memory_fts.memory_id
                WHERE memory_fts MATCH ?
                  AND {where}
                ORDER BY bm25(memory_fts), m.importance DESC,
                         COALESCE(NULLIF(m.occurred_at, ''), m.created_at) DESC
                LIMIT ?
                """,
                params + [max(1, int(limit or 1))],
            ).fetchall()
        except sqlite3.Error:
            return []

    def _fts_match_query(self, terms: list[str]) -> str:
        variants: list[str] = []
        for term in terms or []:
            text = clean_text(term, 80).lower()
            if not text:
                continue
            for variant in self._fts_term_variants(text):
                if variant and variant not in variants:
                    variants.append(variant)
            if len(variants) >= 48:
                break
        return " OR ".join(self._quote_fts_term(term) for term in variants[:48])

    @staticmethod
    def _fts_term_variants(term: str) -> list[str]:
        variants = [term]
        compact = re.sub(r"\s+", "", term)
        if re.fullmatch(r"[\u4e00-\u9fff]{3,}", compact):
            variants.extend(compact[index : index + 2] for index in range(0, len(compact) - 1))
        return variants

    @staticmethod
    def _quote_fts_term(term: str) -> str:
        return '"' + clean_text(term, 80).replace('"', '""') + '"'

    async def list_keyword_candidate_memories(
        self,
        terms: list[str],
        limit: int = 800,
        include_pending: bool = False,
    ) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_keyword_candidate_memories_sync,
            terms,
            limit,
            include_pending,
        )

    def _list_keyword_candidate_memories_sync(
        self,
        terms: list[str],
        limit: int,
        include_pending: bool,
    ) -> list[MemoryRecord]:
        with self._lock:
            rows = self._keyword_candidate_rows(self._conn, terms, limit, include_pending)
        return [MemoryRecord.from_row(row) for row in rows]

    def _keyword_candidate_rows(
        self,
        conn: sqlite3.Connection,
        terms: list[str],
        limit: int,
        include_pending: bool,
    ) -> list[Any]:
        cleaned_terms = []
        for term in terms or []:
            text = clean_text(term, 80).lower()
            if text and text not in cleaned_terms:
                cleaned_terms.append(text)
            if len(cleaned_terms) >= 24:
                break
        if not cleaned_terms:
            return []

        where = f"lifecycle != 'archived' AND {self._recallable_memory_sql()}"
        params: list[Any] = []
        if not include_pending:
            where += " AND review_status != 'pending'"

        columns = [
            "content",
            "evidence",
            "tags",
            "subject_name",
            "object_name",
        ]
        term_clauses: list[str] = []
        for term in cleaned_terms:
            like = self._like_pattern(term)
            term_clauses.append(
                "(" + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in columns) + ")"
            )
            params.extend([like] * len(columns))
        where += " AND (" + " OR ".join(term_clauses) + ")"

        return conn.execute(
            f"""
            SELECT *
            FROM memories
            WHERE {where}
            ORDER BY
                CASE WHEN session_id != '' THEN 0 ELSE 1 END,
                importance DESC,
                occurred_at DESC,
                created_at DESC
            LIMIT ?
            """,
            params + [max(1, int(limit or 1))],
        ).fetchall()

    @staticmethod
    def _like_pattern(term: str) -> str:
        escaped = clean_text(term, 120).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    async def recent_memories(self, limit: int = 10, include_pending: bool = True) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(self._recent_memories_sync, limit, include_pending)

    def _recent_memories_sync(self, limit: int, include_pending: bool) -> list[MemoryRecord]:
        where = self._recallable_memory_sql()
        if not include_pending:
            where += " AND review_status != 'pending'"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM memories WHERE {where} ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    async def list_memories(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        include_pending: bool = True,
        query: str = "",
        memory_type: str = "",
        scope: str = "",
        visibility: str = "",
        review_status: str = "",
        lifecycle: str = "",
        session_id: str = "",
        group_id: str = "",
        entity_id: str = "",
        memory_types: list[str] | tuple[str, ...] | None = None,
        lifecycle_values: list[str] | tuple[str, ...] | None = None,
        visibility_values: list[str] | tuple[str, ...] | None = None,
        source_plugin_exclude: str = "",
    ) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_memories_sync,
            limit,
            offset,
            include_pending,
            query,
            memory_type,
            scope,
            visibility,
            review_status,
            lifecycle,
            session_id,
            group_id,
            entity_id,
            memory_types,
            lifecycle_values,
            visibility_values,
            source_plugin_exclude,
        )

    def _list_memories_sync(
        self,
        limit: int,
        offset: int,
        include_pending: bool,
        query: str,
        memory_type: str,
        scope: str,
        visibility: str,
        review_status: str,
        lifecycle: str,
        session_id: str,
        group_id: str,
        entity_id: str,
        memory_types: list[str] | tuple[str, ...] | None,
        lifecycle_values: list[str] | tuple[str, ...] | None,
        visibility_values: list[str] | tuple[str, ...] | None,
        source_plugin_exclude: str,
    ) -> list[MemoryRecord]:
        params: list[Any] = []
        where = "1=1"
        if not include_pending:
            where += " AND review_status != 'pending'"
        if query:
            like = self._like_pattern(query)
            where += (
                " AND (id LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR evidence LIKE ? ESCAPE '\\' OR subject_id LIKE ? ESCAPE '\\'"
                " OR subject_name LIKE ? ESCAPE '\\' OR object_id LIKE ? ESCAPE '\\' OR object_name LIKE ? ESCAPE '\\'"
                " OR session_id LIKE ? ESCAPE '\\' OR group_id LIKE ? ESCAPE '\\')"
            )
            params.extend([like] * 9)
        requested_types = [clean_text(value, 80) for value in (memory_types or ()) if clean_text(value, 80)]
        if requested_types:
            marks = ",".join("?" for _ in requested_types)
            where += f" AND memory_type IN ({marks})"
            params.extend(requested_types)
        elif memory_type:
            where += " AND memory_type=?"
            params.append(clean_text(memory_type, 80))
        if scope:
            where += " AND scope=?"
            params.append(clean_text(scope, 40))
        requested_visibilities = [clean_text(value, 40) for value in (visibility_values or ()) if clean_text(value, 40)]
        if requested_visibilities:
            marks = ",".join("?" for _ in requested_visibilities)
            where += f" AND visibility IN ({marks})"
            params.extend(requested_visibilities)
        elif visibility:
            where += " AND visibility=?"
            params.append(clean_text(visibility, 40))
        if source_plugin_exclude:
            where += " AND source_plugin != ?"
            params.append(clean_text(source_plugin_exclude, 120))
        if review_status:
            where += " AND review_status=?"
            params.append(clean_text(review_status, 40))
        requested_lifecycles = [clean_text(value, 40) for value in (lifecycle_values or ()) if clean_text(value, 40)]
        if requested_lifecycles:
            marks = ",".join("?" for _ in requested_lifecycles)
            where += f" AND lifecycle IN ({marks})"
            params.extend(requested_lifecycles)
        elif lifecycle:
            where += " AND lifecycle=?"
            params.append(clean_text(lifecycle, 40))
        if session_id:
            where += " AND session_id=?"
            params.append(clean_text(session_id, 200))
        if group_id:
            where += " AND group_id=?"
            params.append(clean_text(group_id, 120))
        if entity_id:
            entity = clean_text(entity_id, 120)
            where += " AND (subject_id=? OR object_id=? OR group_id=? OR session_id LIKE ? ESCAPE '\\')"
            params.extend([entity, entity, entity, self._like_pattern(entity)])
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM memories
                WHERE {where}
                ORDER BY occurred_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [max(1, int(limit)), max(0, int(offset))],
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    async def list_memories_by_validity(
        self,
        *,
        validity_statuses: list[str] | tuple[str, ...] | None = None,
        valid_at: str = "",
        owner_bot_id: str = "",
        platform: str = "",
        scope: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """Read a bounded Memory Atom set using reusable validity-time rules."""

        return await self._run_recoverable_database_operation(
            self._list_memories_by_validity_sync,
            validity_statuses,
            valid_at,
            owner_bot_id,
            platform,
            scope,
            limit,
            offset,
        )

    def _list_memories_by_validity_sync(
        self,
        validity_statuses: list[str] | tuple[str, ...] | None,
        valid_at: str,
        owner_bot_id: str,
        platform: str,
        scope: str,
        limit: int,
        offset: int,
    ) -> list[MemoryRecord]:
        statuses = [
            clean_text(value, 24).lower()
            for value in (validity_statuses or ["active"])
            if clean_text(value, 24).lower() in VALIDITY_STATUSES
        ]
        at = clean_text(valid_at, 80) or utc_now()
        validity_where, params = validity_where_clause(statuses=statuses, valid_at=at)
        where = [validity_where]
        owner = clean_text(owner_bot_id, 120)
        platform_value = clean_text(platform, 80)
        scope_value = clean_text(scope, 40)
        if owner:
            where.append("owner_bot_id=?")
            params.append(owner)
        if platform_value:
            where.append("platform=?")
            params.append(platform_value)
        if scope_value:
            where.append("scope=?")
            params.append(scope_value)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM memories
                WHERE {' AND '.join(where)}
                ORDER BY salience DESC, importance DESC,
                         COALESCE(NULLIF(valid_from, ''), NULLIF(occurred_at, ''), created_at) DESC
                LIMIT ? OFFSET ?
                """,
                [*params, max(1, int(limit or 1)), max(0, int(offset or 0))],
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    async def read_user_memory_summary_records(
        self,
        user_id: str,
        *,
        session_id: str = "",
        limit: int = 8,
    ) -> dict[str, Any]:
        """Read a bounded exact-identity private-memory set for a bridge DTO.

        This is deliberately not a general search: it accepts no display name,
        has no cross-window expansion, and never reads group rows. A supplied
        session must itself resolve to the same private user identity.
        """

        return await self._run_recoverable_database_operation(
            self._read_user_memory_summary_records_sync,
            user_id,
            session_id,
            limit,
        )

    def _read_user_memory_summary_records_sync(
        self,
        user_id: str,
        session_id: str,
        limit: int,
    ) -> dict[str, Any]:
        identity = clean_text(user_id, 120)
        requested_session = clean_text(session_id, 200)
        empty = {"records": [], "total": 0, "type_counts": {}}
        if not identity:
            return empty
        if requested_session:
            scope, target_id = parse_scope_from_session(requested_session)
            if scope != "private" or clean_text(target_id, 120) != identity:
                return empty

        try:
            safe_limit = max(1, min(12, int(limit or 8)))
        except (TypeError, ValueError, OverflowError):
            safe_limit = 8
        session_filters = [
            "%:friendmessage:" + self._escape_like_suffix(identity),
            "%:privatemessage:" + self._escape_like_suffix(identity),
            "%:friend:" + self._escape_like_suffix(identity),
            "%:private:" + self._escape_like_suffix(identity),
        ]
        identity_clause = " OR ".join(
            ["subject_id=?", "object_id=?", *("LOWER(session_id) LIKE ? ESCAPE '\\'" for _ in session_filters)]
        )
        params: list[Any] = [identity, identity, *session_filters]
        session_clause = ""
        if requested_session:
            session_clause = " AND session_id=?"
            params.append(requested_session)
        where = (
            "scope='private' AND review_status!='pending' "
            "AND visibility IN ('private_pair', 'shareable') "
            f"AND ({identity_clause}){session_clause}"
        )
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM memories
                WHERE {where}
                ORDER BY occurred_at DESC, created_at DESC
                LIMIT ?
                """,
                [*params, safe_limit],
            ).fetchall()
            total_row = self._conn.execute(
                f"SELECT COUNT(*) AS count FROM memories WHERE {where}",
                params,
            ).fetchone()
            type_rows = self._conn.execute(
                f"SELECT memory_type, COUNT(*) AS count FROM memories WHERE {where} GROUP BY memory_type",
                params,
            ).fetchall()

        records: list[MemoryRecord] = []
        for row in rows:
            record = MemoryRecord.from_row(row)
            parsed_scope, parsed_target = parse_scope_from_session(clean_text(record.session_id, 200))
            direct_identity = identity in {clean_text(record.subject.id, 120), clean_text(record.object.id, 120)}
            session_identity = parsed_scope == "private" and clean_text(parsed_target, 120) == identity
            if requested_session and record.session_id != requested_session:
                continue
            if direct_identity or session_identity:
                records.append(record)
        type_counts = {
            clean_text(row["memory_type"], 80): max(0, int(row["count"] or 0))
            for row in type_rows
            if clean_text(row["memory_type"], 80)
        }
        return {
            "records": records,
            "total": max(0, int(total_row["count"] or 0)) if total_row else 0,
            "type_counts": type_counts,
        }

    @staticmethod
    def _escape_like_suffix(value: str) -> str:
        return clean_text(value, 120).lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    async def list_memory_buckets(
        self,
        limit: int | None = 160,
        *,
        include_raw_events: bool = False,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_memory_buckets_sync,
            limit,
            include_raw_events,
        )

    async def preferred_private_session_id(self, user_id: str, bot_id: str = "") -> str:
        return await asyncio.to_thread(self._preferred_private_session_id_sync, user_id, bot_id)

    def _preferred_private_session_id_sync(self, user_id: str, bot_id: str = "") -> str:
        user_id = clean_text(user_id, 120)
        bot_id = clean_text(bot_id, 120)
        if not user_id:
            return ""
        bot_clause = ""
        params: list[Any] = [user_id, user_id, self._like_pattern(user_id)]
        if bot_id:
            bot_clause = """
                  AND (
                    (subject_kind='bot' AND subject_id=?)
                    OR (object_kind='bot' AND object_id=?)
                    OR CASE
                        WHEN json_valid(metadata)
                        THEN COALESCE(CAST(json_extract(metadata, '$.owner_bot_id') AS TEXT), '')
                        ELSE ''
                       END=?
                  )
            """
            params.extend([bot_id, bot_id, bot_id])
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    session_id,
                    SUM(CASE WHEN COALESCE(import_batch_id, '')='' THEN 1 ELSE 0 END) AS native_count,
                    COUNT(*) AS total_count,
                    MAX(COALESCE(NULLIF(occurred_at, ''), created_at)) AS latest_at
                FROM memories
                WHERE scope='private' AND session_id!=''
                  AND (subject_id=? OR object_id=? OR session_id LIKE ? ESCAPE '\\')
                  {bot_clause}
                GROUP BY session_id
                ORDER BY native_count DESC, total_count DESC, latest_at DESC
                LIMIT 64
                """,
                params,
            ).fetchall()
        for row in rows:
            parsed_scope, parsed_target = parse_scope_from_session(clean_text(row["session_id"], 200))
            if parsed_scope == "private" and clean_text(parsed_target, 120) == user_id:
                return clean_text(row["session_id"], 200)
        return ""

    def _list_memory_buckets_sync(
        self,
        limit: int | None,
        include_raw_events: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                WITH normalized AS (
                    SELECT
                        scope,
                        CASE
                            WHEN scope='group' THEN
                                CASE
                                    WHEN group_id!='' THEN group_id
                                    WHEN object_kind='group' AND object_id!='' THEN object_id
                                    ELSE session_id
                                END
                            ELSE
                                CASE
                                    WHEN subject_kind='user' AND subject_id!='' AND subject_id!='self' THEN subject_id
                                    WHEN object_kind='user' AND object_id!='' AND object_id!='self' THEN object_id
                                    ELSE session_id
                                END
                        END AS target_id,
                        CASE
                            WHEN scope='group' THEN
                                CASE
                                    WHEN object_kind='group' AND object_name!='' THEN object_name
                                    ELSE ''
                                END
                            ELSE
                                CASE
                                    WHEN subject_kind='user' AND subject_id!='' AND subject_id!='self' THEN subject_name
                                    WHEN object_kind='user' AND object_id!='' AND object_id!='self' THEN object_name
                                    ELSE ''
                                END
                        END AS target_name,
                        session_id AS sample_session_id,
                        group_id AS sample_group_id,
                        CASE
                            WHEN json_valid(metadata)
                                 AND COALESCE(CAST(json_extract(metadata, '$.owner_bot_id') AS TEXT), '') NOT IN ('', 'self')
                            THEN CAST(json_extract(metadata, '$.owner_bot_id') AS TEXT)
                            WHEN subject_kind='bot' AND subject_id NOT IN ('', 'self') THEN subject_id
                            WHEN object_kind='bot' AND object_id NOT IN ('', 'self') THEN object_id
                            ELSE ''
                        END AS sample_bot_id,
                        review_status,
                        lifecycle,
                        visibility,
                        CASE
                            WHEN lifecycle!='archived'
                                 AND visibility!='internal'
                                 AND (?=1 OR lifecycle!='raw_event')
                            THEN 1
                            ELSE 0
                        END AS is_searchable,
                        occurred_at
                    FROM memories
                    WHERE scope IN ('private', 'group')
                      AND review_status!='pending'
                ), ranked AS (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY scope, target_id, sample_bot_id
                            ORDER BY
                                CASE
                                    WHEN is_searchable=1 THEN 0
                                    ELSE 1
                                END ASC,
                                occurred_at DESC,
                                sample_session_id DESC
                        ) AS sample_rank,
                        ROW_NUMBER() OVER (
                            PARTITION BY scope, target_id, sample_bot_id
                            ORDER BY
                                CASE WHEN target_name!='' THEN 0 ELSE 1 END ASC,
                                occurred_at DESC,
                                sample_session_id DESC
                        ) AS name_rank
                    FROM normalized
                    WHERE target_id!=''
                )
                SELECT
                    scope,
                    target_id,
                    MAX(CASE WHEN name_rank=1 THEN target_name ELSE '' END) AS target_name,
                    MAX(CASE WHEN name_rank=1 THEN occurred_at ELSE '' END) AS name_latest_at,
                    MAX(CASE WHEN sample_rank=1 THEN sample_session_id ELSE '' END) AS sample_session_id,
                    MAX(CASE WHEN sample_rank=1 THEN sample_group_id ELSE '' END) AS sample_group_id,
                    sample_bot_id,
                    COUNT(*) AS memory_count,
                    SUM(CASE WHEN lifecycle='archived' THEN 1 ELSE 0 END) AS archived_count,
                    SUM(
                        is_searchable
                    ) AS searchable_count,
                    MAX(
                        CASE
                            WHEN is_searchable=1 THEN occurred_at
                            ELSE ''
                        END
                    ) AS active_latest_at,
                    MAX(occurred_at) AS latest_at
                FROM ranked
                GROUP BY scope, target_id, sample_bot_id
                ORDER BY
                    scope ASC,
                    CASE
                        WHEN MAX(
                            CASE
                                WHEN is_searchable=1 THEN occurred_at
                                ELSE ''
                            END
                        )!='' THEN 0
                        ELSE 1
                    END ASC,
                    COALESCE(
                        NULLIF(
                            MAX(
                                CASE
                                    WHEN is_searchable=1 THEN occurred_at
                                    ELSE ''
                                END
                            ),
                            ''
                        ),
                        MAX(occurred_at)
                    ) DESC
                """,
                (1 if include_raw_events else 0,),
            ).fetchall()
            merged: dict[tuple[str, str], dict[str, Any]] = {}
            for raw in rows:
                bucket = dict(raw)
                scope = clean_text(bucket.get("scope"), 40)
                target_id = clean_text(bucket.get("target_id"), 200)
                parsed_scope, parsed_target = parse_scope_from_session(target_id)
                if parsed_scope == scope and clean_text(parsed_target, 120):
                    target_id = clean_text(parsed_target, 120)
                key = (scope, target_id)
                sample_context = {
                    "bot_id": clean_text(bucket.get("sample_bot_id"), 120),
                    "session_id": clean_text(bucket.get("sample_session_id"), 200),
                    "group_id": clean_text(bucket.get("sample_group_id"), 120),
                    "memory_count": int(bucket.get("memory_count") or 0),
                    "archived_count": int(bucket.get("archived_count") or 0),
                    "searchable_count": int(bucket.get("searchable_count") or 0),
                    "active_latest_at": clean_text(bucket.get("active_latest_at"), 80),
                    "latest_at": clean_text(bucket.get("latest_at"), 80),
                }
                candidate_priority = (
                    bool(sample_context["active_latest_at"]),
                    sample_context["active_latest_at"] or sample_context["latest_at"],
                )
                current = merged.get(key)
                if current is None:
                    bucket["target_id"] = target_id
                    bucket["sample_contexts"] = [sample_context]
                    bucket["_sample_has_active"] = candidate_priority[0]
                    bucket["_sample_latest_at"] = candidate_priority[1]
                    bucket["_name_latest_at"] = clean_text(bucket.get("name_latest_at"), 80)
                    merged[key] = bucket
                    continue
                current["memory_count"] = int(current.get("memory_count") or 0) + int(bucket.get("memory_count") or 0)
                current["archived_count"] = int(current.get("archived_count") or 0) + int(bucket.get("archived_count") or 0)
                current["searchable_count"] = int(current.get("searchable_count") or 0) + int(bucket.get("searchable_count") or 0)
                current["active_latest_at"] = max(
                    clean_text(current.get("active_latest_at"), 80),
                    clean_text(bucket.get("active_latest_at"), 80),
                )
                current["latest_at"] = max(
                    clean_text(current.get("latest_at"), 80),
                    clean_text(bucket.get("latest_at"), 80),
                )
                current_priority = (
                    bool(current.get("_sample_has_active")),
                    clean_text(current.get("_sample_latest_at"), 80),
                )
                if candidate_priority > current_priority:
                    current["sample_session_id"] = bucket.get("sample_session_id")
                    current["sample_group_id"] = bucket.get("sample_group_id")
                    current["sample_bot_id"] = bucket.get("sample_bot_id")
                    current["_sample_has_active"] = candidate_priority[0]
                    current["_sample_latest_at"] = candidate_priority[1]
                contexts = current.setdefault("sample_contexts", [])
                existing_context = next(
                    (
                        item
                        for item in contexts
                        if clean_text(item.get("bot_id"), 120) == sample_context["bot_id"]
                    ),
                    None,
                )
                if existing_context is None:
                    contexts.append(sample_context)
                else:
                    existing_priority = (
                        bool(clean_text(existing_context.get("active_latest_at"), 80)),
                        clean_text(existing_context.get("active_latest_at"), 80)
                        or clean_text(existing_context.get("latest_at"), 80),
                    )
                    existing_context["memory_count"] = int(existing_context.get("memory_count") or 0) + sample_context["memory_count"]
                    existing_context["archived_count"] = int(existing_context.get("archived_count") or 0) + sample_context["archived_count"]
                    existing_context["searchable_count"] = int(existing_context.get("searchable_count") or 0) + sample_context["searchable_count"]
                    existing_context["active_latest_at"] = max(
                        clean_text(existing_context.get("active_latest_at"), 80),
                        sample_context["active_latest_at"],
                    )
                    existing_context["latest_at"] = max(
                        clean_text(existing_context.get("latest_at"), 80),
                        sample_context["latest_at"],
                    )
                    if candidate_priority > existing_priority:
                        existing_context["session_id"] = sample_context["session_id"]
                        existing_context["group_id"] = sample_context["group_id"]
                candidate_name = clean_text(bucket.get("target_name"), 120)
                candidate_name_at = clean_text(bucket.get("name_latest_at"), 80)
                current_name = clean_text(current.get("target_name"), 120)
                current_name_at = clean_text(current.get("_name_latest_at"), 80)
                if (
                    candidate_name
                    and candidate_name not in {target_id, clean_text(bucket.get("sample_session_id"), 200)}
                    and (not current_name or candidate_name_at > current_name_at)
                ):
                    current["target_name"] = candidate_name
                    current["_name_latest_at"] = candidate_name_at
            buckets = list(merged.values())
            for bucket in buckets:
                contexts = bucket.get("sample_contexts") or []
                contexts.sort(
                    key=lambda item: (
                        bool(clean_text(item.get("active_latest_at"), 80)),
                        clean_text(item.get("active_latest_at"), 80)
                        or clean_text(item.get("latest_at"), 80),
                    ),
                    reverse=True,
                )
                bucket.pop("_sample_has_active", None)
                bucket.pop("_sample_latest_at", None)
                bucket.pop("_name_latest_at", None)
                bucket.pop("name_latest_at", None)
            buckets.sort(
                key=lambda item: (
                    bool(int(item.get("searchable_count") or 0)),
                    clean_text(item.get("active_latest_at"), 80)
                    or clean_text(item.get("latest_at"), 80),
                    clean_text(item.get("scope"), 40),
                    clean_text(item.get("target_id"), 160),
                ),
                reverse=True,
            )
            if limit is not None:
                buckets = buckets[: max(1, int(limit))]
            for bucket in buckets:
                bucket.pop("active_latest_at", None)
                for context in bucket.get("sample_contexts") or []:
                    context.pop("active_latest_at", None)
                bucket["target_name"] = self._resolve_bucket_target_name_sync(
                    clean_text(bucket.get("scope"), 40),
                    clean_text(bucket.get("target_id"), 160),
                    clean_text(bucket.get("target_name"), 120),
                )
                bucket["target_kind"] = self._bucket_target_kind(
                    clean_text(bucket.get("scope"), 40),
                    clean_text(bucket.get("target_id"), 160),
                    clean_text(bucket.get("sample_session_id"), 200),
                )
        return buckets

    @staticmethod
    def _bucket_target_kind(scope: str, target_id: str, session_id: str = "") -> str:
        if scope == "group":
            return "group"
        if scope != "private":
            return "unknown"
        target_id = clean_text(target_id, 160)
        session_id = clean_text(session_id, 200).lower()
        if target_id.isdigit():
            return "qq"
        if "live2d" in session_id:
            return "legacy_live2d"
        if target_id.startswith("private_companion:"):
            return "internal"
        if re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", target_id):
            return "legacy_session"
        return "private_session"

    def _resolve_bucket_target_name_sync(self, scope: str, target_id: str, fallback: str = "") -> str:
        fallback = self._clean_window_display_name(fallback)
        target_id = clean_text(target_id, 160)
        if fallback and fallback != target_id:
            return fallback
        if not target_id:
            return fallback

        entity_kind = "group" if scope == "group" else "user"
        row = self._conn.execute(
            """
            SELECT display_name FROM identities
            WHERE entity_kind=? AND entity_id=? AND display_name!=''
            ORDER BY confidence DESC, updated_at DESC
            LIMIT 1
            """,
            (entity_kind, target_id),
        ).fetchone()
        if row:
            name = self._clean_window_display_name(row["display_name"])
            if name:
                return name

        if scope == "group":
            row = self._conn.execute(
                """
                SELECT object_name AS name FROM relationship_edges
                WHERE object_kind='group' AND object_id=? AND object_name!=''
                ORDER BY confidence DESC, updated_at DESC
                LIMIT 1
                """,
                (target_id,),
            ).fetchone()
            if row:
                name = self._clean_window_display_name(row["name"])
                if name:
                    return name
        elif scope == "private":
            row = self._conn.execute(
                """
                SELECT name FROM (
                    SELECT subject_name AS name, confidence, updated_at FROM relationship_edges
                    WHERE subject_kind='user' AND subject_id=? AND subject_name!=''
                    UNION ALL
                    SELECT object_name AS name, confidence, updated_at FROM relationship_edges
                    WHERE object_kind='user' AND object_id=? AND object_name!=''
                )
                ORDER BY confidence DESC, updated_at DESC
                LIMIT 1
                """,
                (target_id, target_id),
            ).fetchone()
            if row:
                name = self._clean_window_display_name(row["name"])
                if name:
                    return name
        return fallback

    @staticmethod
    def _clean_window_display_name(value: Any) -> str:
        text = clean_text(value, 120)
        if not text:
            return ""
        text = re.sub(
            r"\s+(?:Avatar|Owner\s*ID|Admin\s*IDs?|Member\s*Count|Max\s*Member\s*Count|Description)\s*[:：].*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"^(?:Group\s*ID|Group\s*Name|Name|User\s*ID|User\s*Name|Nick(?:name)?|QQ)\s*[:：]\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return clean_text(text, 80)

    async def list_acl_rules(
        self,
        *,
        owner_scope: str = "",
        owner_id: str = "",
        reader_scope: str = "",
        reader_id: str = "",
        effect: str = "",
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_acl_rules_sync,
            owner_scope,
            owner_id,
            reader_scope,
            reader_id,
            effect,
            enabled_only,
        )

    def _list_acl_rules_sync(
        self,
        owner_scope: str,
        owner_id: str,
        reader_scope: str,
        reader_id: str,
        effect: str,
        enabled_only: bool,
    ) -> list[dict[str, Any]]:
        where = "1=1"
        params: list[Any] = []
        if enabled_only:
            where += " AND enabled=1"
        if owner_scope:
            where += " AND owner_scope=?"
            params.append(clean_text(owner_scope, 40))
        if owner_id:
            where += " AND owner_id=?"
            params.append(clean_text(owner_id, 160))
        if reader_scope:
            where += " AND reader_scope=?"
            params.append(clean_text(reader_scope, 40))
        if reader_id:
            where += " AND reader_id=?"
            params.append(clean_text(reader_id, 160))
        if effect:
            where += " AND effect=?"
            params.append(self._normalize_acl_effect(effect))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM memory_acl_rules
                WHERE {where}
                ORDER BY updated_at DESC, created_at DESC
                """,
                params,
            ).fetchall()
        return [self._acl_rule_from_row(row) for row in rows]

    async def upsert_acl_rule(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        reader_scope: str,
        reader_id: str,
        effect: str = "allow",
        enabled: bool = True,
        note: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._upsert_acl_rule_sync,
            owner_scope,
            owner_id,
            reader_scope,
            reader_id,
            effect,
            enabled,
            note,
        )

    def _upsert_acl_rule_sync(
        self,
        owner_scope: str,
        owner_id: str,
        reader_scope: str,
        reader_id: str,
        effect: str,
        enabled: bool,
        note: str,
        _commit: bool = True,
    ) -> dict[str, Any]:
        now = utc_now()
        owner_scope = clean_text(owner_scope, 40)
        owner_id = clean_text(owner_id, 160)
        reader_scope = clean_text(reader_scope, 40)
        reader_id = clean_text(reader_id, 160)
        effect = self._normalize_acl_effect(effect)
        data = {
            "id": new_id("acl"),
            "owner_scope": owner_scope,
            "owner_id": owner_id,
            "reader_scope": reader_scope,
            "reader_id": reader_id,
            "effect": effect,
            "enabled": 1 if enabled else 0,
            "note": clean_text(note, 300),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_acl_rules(
                    id, owner_scope, owner_id, reader_scope, reader_id, effect, enabled, note, created_at, updated_at
                )
                VALUES(:id, :owner_scope, :owner_id, :reader_scope, :reader_id, :effect, :enabled, :note, :created_at, :updated_at)
                ON CONFLICT(owner_scope, owner_id, reader_scope, reader_id) DO UPDATE SET
                    effect=excluded.effect,
                    enabled=excluded.enabled,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                data,
            )
            row = self._conn.execute(
                """
                SELECT * FROM memory_acl_rules
                WHERE owner_scope=? AND owner_id=? AND reader_scope=? AND reader_id=?
                """,
                (owner_scope, owner_id, reader_scope, reader_id),
            ).fetchone()
            if _commit:
                self._conn.commit()
        return self._acl_rule_from_row(row) if row else data

    async def delete_acl_rule(self, rule_id: str) -> bool:
        return await asyncio.to_thread(self._delete_acl_rule_sync, rule_id)

    def _delete_acl_rule_sync(self, rule_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memory_acl_rules WHERE id=?",
                (clean_text(rule_id, 120),),
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _acl_rule_from_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["effect"] = item.get("effect") or "allow"
        return item

    async def get_acl_policy(self, window_scope: str, window_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_acl_policy_sync, window_scope, window_id)

    def _get_acl_policy_sync(self, window_scope: str, window_id: str) -> dict[str, Any]:
        window_scope = clean_text(window_scope, 40)
        window_id = clean_text(window_id, 160)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory_acl_policies WHERE window_scope=? AND window_id=?",
                (window_scope, window_id),
            ).fetchone()
        if not row:
            return self._default_acl_policy(window_scope, window_id)
        return self._acl_policy_from_row(row)

    async def list_acl_policies(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_acl_policies_sync)

    def _list_acl_policies_sync(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM memory_acl_policies").fetchall()
        return [self._acl_policy_from_row(row) for row in rows]

    async def upsert_acl_policy(
        self,
        *,
        window_scope: str,
        window_id: str,
        read_mode: str = "",
        share_mode: str = "",
        capture_enabled: Any = _ACL_UNSET,
        recall_enabled: Any = _ACL_UNSET,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._upsert_acl_policy_sync,
            window_scope,
            window_id,
            read_mode,
            share_mode,
            capture_enabled,
            recall_enabled,
        )

    def _upsert_acl_policy_sync(
        self,
        window_scope: str,
        window_id: str,
        read_mode: str,
        share_mode: str,
        capture_enabled: Any = _ACL_UNSET,
        recall_enabled: Any = _ACL_UNSET,
        _commit: bool = True,
    ) -> dict[str, Any]:
        window_scope = clean_text(window_scope, 40)
        window_id = clean_text(window_id, 160)
        current = self._get_acl_policy_sync(window_scope, window_id)
        read_mode = self._normalize_acl_mode(read_mode or current.get("read_mode"))
        share_mode = self._normalize_acl_mode(share_mode or current.get("share_mode"))
        next_capture = (
            current.get("capture_enabled")
            if capture_enabled is _ACL_UNSET
            else self._normalize_acl_feature_override(capture_enabled)
        )
        next_recall = (
            current.get("recall_enabled")
            if recall_enabled is _ACL_UNSET
            else self._normalize_acl_feature_override(recall_enabled)
        )
        now = utc_now()
        data = {
            "id": current.get("id") or new_id("acl_policy"),
            "window_scope": window_scope,
            "window_id": window_id,
            "read_mode": read_mode,
            "share_mode": share_mode,
            "capture_enabled": next_capture,
            "recall_enabled": next_recall,
            "created_at": current.get("created_at") or now,
            "updated_at": now,
        }
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_acl_policies(
                    id, window_scope, window_id, read_mode, share_mode,
                    capture_enabled, recall_enabled, created_at, updated_at
                )
                VALUES(:id, :window_scope, :window_id, :read_mode, :share_mode,
                       :capture_enabled, :recall_enabled, :created_at, :updated_at)
                ON CONFLICT(window_scope, window_id) DO UPDATE SET
                    read_mode=excluded.read_mode,
                    share_mode=excluded.share_mode,
                    capture_enabled=excluded.capture_enabled,
                    recall_enabled=excluded.recall_enabled,
                    updated_at=excluded.updated_at
                """,
                data,
            )
            row = self._conn.execute(
                "SELECT * FROM memory_acl_policies WHERE window_scope=? AND window_id=?",
                (window_scope, window_id),
            ).fetchone()
            if _commit:
                self._conn.commit()
            self._acl_feature_override_cache[(window_scope, window_id)] = (
                next_capture,
                next_recall,
            )
        return self._acl_policy_from_row(row) if row else data

    @staticmethod
    def _default_acl_policy(window_scope: str, window_id: str) -> dict[str, Any]:
        default_mode = "blacklist" if clean_text(window_scope, 40) == "group" else "whitelist"
        return {
            "id": "",
            "window_scope": window_scope,
            "window_id": window_id,
            "read_mode": default_mode,
            "share_mode": default_mode,
            "capture_enabled": None,
            "recall_enabled": None,
            "created_at": "",
            "updated_at": "",
        }

    @classmethod
    def _acl_policy_from_row(cls, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["read_mode"] = cls._normalize_acl_mode(item.get("read_mode"))
        item["share_mode"] = cls._normalize_acl_mode(item.get("share_mode"))
        for key in ("capture_enabled", "recall_enabled"):
            value = item.get(key)
            item[key] = None if value is None else bool(value)
        return item

    @staticmethod
    def _normalize_acl_feature_override(value: Any) -> bool | None:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

    def get_scope_feature_override_sync(self, scope: str, window_id: str) -> dict[str, bool | None]:
        scope = clean_text(scope, 40)
        window_id = clean_text(window_id, 160)
        if scope not in {"private", "group"} or not window_id:
            return {"capture_enabled": None, "recall_enabled": None}
        cache_key = (scope, window_id)
        with self._lock:
            cached = self._acl_feature_override_cache.get(cache_key)
            if cached is not None:
                capture_enabled, recall_enabled = cached
                return {
                    "capture_enabled": capture_enabled,
                    "recall_enabled": recall_enabled,
                }
            try:
                row = self._conn.execute(
                    "SELECT capture_enabled, recall_enabled FROM memory_acl_policies "
                    "WHERE window_scope=? AND window_id=?",
                    (scope, window_id),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such column" not in str(exc).lower():
                    raise
                row = None
            values = (
                (None, None)
                if not row
                else (
                    None if row["capture_enabled"] is None else bool(row["capture_enabled"]),
                    None if row["recall_enabled"] is None else bool(row["recall_enabled"]),
                )
            )
            self._acl_feature_override_cache[cache_key] = values
        capture_enabled, recall_enabled = values
        return {
            "capture_enabled": capture_enabled,
            "recall_enabled": recall_enabled,
        }

    @staticmethod
    def _normalize_acl_effect(effect: Any) -> str:
        return "deny" if clean_text(effect, 20).lower() in {"deny", "block", "blacklist"} else "allow"

    @staticmethod
    def _normalize_acl_mode(mode: Any) -> str:
        return "blacklist" if clean_text(mode, 20).lower() in {"blacklist", "deny", "block"} else "whitelist"

    async def get_memory(self, memory_id: str) -> MemoryRecord | None:
        return await self._run_recoverable_database_operation(self._get_memory_sync, memory_id)

    def _get_memory_sync(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return MemoryRecord.from_row(row) if row else None

    async def get_memories_by_ids(self, memory_ids: list[str]) -> dict[str, MemoryRecord]:
        return await self._run_recoverable_database_operation(self._get_memories_by_ids_sync, memory_ids)

    def _get_memories_by_ids_sync(self, memory_ids: list[str]) -> dict[str, MemoryRecord]:
        ids = [clean_text(mid, 120) for mid in memory_ids if clean_text(mid, 120)]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM memories WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return {row["id"]: MemoryRecord.from_row(row) for row in rows}

    async def update_memory_owner_bot(self, memory_id: str, owner_bot_id: str) -> bool:
        """Update the Memory Atom owner and its mirrored metadata field."""
        return await self._run_recoverable_database_operation(
            self._update_memory_owner_bot_sync,
            memory_id,
            owner_bot_id,
        )

    def _update_memory_owner_bot_sync(self, memory_id: str, owner_bot_id: str) -> bool:
        memory_id = clean_text(memory_id, 120)
        owner_bot_id = clean_text(owner_bot_id, 120)
        if not memory_id or not owner_bot_id or owner_bot_id.casefold() in {"self", "bot", "bot_self"}:
            return False
        with self._lock:
            with self._transaction_sync():
                row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
                if not row:
                    return False
                metadata = json_loads(row["metadata"], {})
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["owner_bot_id"] = owner_bot_id
                atom = self._memory_atom_record_for_row(
                    row,
                    metadata=json_dumps(metadata),
                    owner_bot_id=owner_bot_id,
                )
                cur = self._conn.execute(
                    """
                    UPDATE memories
                    SET owner_bot_id=?, metadata=?, canonical_key=?, content_fingerprint=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        owner_bot_id,
                        json_dumps(metadata),
                        atom.canonical_key,
                        atom.content_fingerprint,
                        utc_now(),
                        memory_id,
                    ),
                )
                refreshed = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
                self._upsert_memory_fts_row(refreshed)
                return cur.rowcount > 0

    async def update_memory_payload(
        self,
        memory_id: str,
        *,
        memory_type: str | None = None,
        content: str | None = None,
        evidence: str | None = None,
        importance: Any | None = None,
        confidence: Any | None = None,
        visibility: str | None = None,
        lifecycle: str | None = None,
        review_status: str | None = None,
        metadata: dict[str, Any] | None = None,
        validity_status: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        salience: Any | None = None,
        durability: str | None = None,
        sensitivity: str | None = None,
    ) -> bool:
        return await self._run_recoverable_database_operation(
            self._update_memory_payload_sync,
            memory_id,
            memory_type,
            content,
            evidence,
            importance,
            confidence,
            visibility,
            lifecycle,
            review_status,
            metadata,
            validity_status,
            valid_from,
            valid_to,
            salience,
            durability,
            sensitivity,
        )

    def _update_memory_payload_sync(
        self,
        memory_id: str,
        memory_type: str | None,
        content: str | None,
        evidence: str | None,
        importance: Any | None,
        confidence: Any | None,
        visibility: str | None,
        lifecycle: str | None,
        review_status: str | None,
        metadata: dict[str, Any] | None,
        validity_status: str | None,
        valid_from: str | None,
        valid_to: str | None,
        salience: Any | None,
        durability: str | None,
        sensitivity: str | None,
    ) -> bool:
        memory_id = clean_text(memory_id, 120)
        with self._lock:
            with self._transaction_sync():
                row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
                if not row:
                    return False
                next_type = clean_text(memory_type if memory_type is not None else row["memory_type"], 80) or row["memory_type"]
                next_content = clean_text(
                    redact_sensitive_text(content if content is not None else row["content"]),
                    4000,
                )
                next_evidence = clean_text(
                    redact_sensitive_text(evidence if evidence is not None else row["evidence"]),
                    4000,
                )
                next_visibility = clean_text(visibility if visibility is not None else row["visibility"], 40) or row["visibility"]
                next_lifecycle = clean_text(lifecycle if lifecycle is not None else row["lifecycle"], 40) or row["lifecycle"]
                next_review_status = clean_text(
                    review_status if review_status is not None else row["review_status"],
                    40,
                ) or row["review_status"]
                next_metadata = metadata if isinstance(metadata, dict) else json_loads(row["metadata"], {})
                if not isinstance(next_metadata, dict):
                    next_metadata = {}
                next_metadata = redact_sensitive_value(next_metadata)
                prospective = MemoryRecord.from_row(row)
                prospective.memory_type = next_type
                prospective.visibility = next_visibility
                prospective.lifecycle = next_lifecycle
                prospective.review_status = next_review_status
                prospective.metadata = dict(next_metadata)
                current = MemoryRecord.from_row(row)
                if (
                    self._profile_single_value_invariant_signature(current)
                    != self._profile_single_value_invariant_signature(prospective)
                    and self._profile_single_value_domain_conflict_sync(prospective)
                ):
                    return False
                try:
                    next_importance = max(0.0, min(1.0, float(importance if importance is not None else row["importance"])))
                except Exception:
                    next_importance = float(row["importance"] or 0.3)
                try:
                    next_confidence = max(0.0, min(1.0, float(confidence if confidence is not None else row["confidence"])))
                except Exception:
                    next_confidence = float(row["confidence"] or 0.5)
                current_validity = normalize_validity_status(row["validity_status"])
                if validity_status is None:
                    next_validity = current_validity
                    if lifecycle is not None and next_lifecycle == "archived":
                        next_validity = "archived"
                    elif lifecycle is not None and current_validity == "archived" and next_lifecycle != "archived":
                        next_validity = "active"
                else:
                    requested_validity = clean_text(validity_status, 24).lower()
                    next_validity = normalize_validity_status(requested_validity, current_validity)
                if next_lifecycle == "archived" or next_validity == "archived":
                    next_lifecycle = "archived"
                    next_validity = "archived"
                next_valid_from = clean_text(
                    valid_from if valid_from is not None else row["valid_from"],
                    80,
                )
                next_valid_to = clean_text(
                    valid_to if valid_to is not None else row["valid_to"],
                    80,
                )
                next_salience = clamp_score(
                    salience if salience is not None else row["salience"],
                    float(row["salience"] or next_importance),
                )
                requested_durability = clean_text(
                    durability if durability is not None else row["durability"],
                    24,
                ).lower()
                next_durability = normalize_durability(
                    requested_durability,
                    clean_text(row["durability"], 24) if row["durability"] in DURABILITY_LEVELS else "normal",
                )
                requested_sensitivity = clean_text(
                    sensitivity if sensitivity is not None else row["sensitivity"],
                    24,
                ).lower()
                next_sensitivity = normalize_sensitivity(
                    requested_sensitivity,
                    clean_text(row["sensitivity"], 24) if row["sensitivity"] in SENSITIVITY_LEVELS else "private",
                )
                atom = self._memory_atom_record_for_row(
                    row,
                    reset_semantic_keys=memory_type is not None or content is not None,
                    memory_type=next_type,
                    content=next_content,
                    evidence=next_evidence,
                    visibility=next_visibility,
                    lifecycle=next_lifecycle,
                    review_status=next_review_status,
                    metadata=json_dumps(next_metadata),
                    importance=next_importance,
                    confidence=next_confidence,
                )
                cur = self._conn.execute(
                    """
                    UPDATE memories
                    SET memory_type=?,
                        content=?,
                        evidence=?,
                        importance=?,
                        confidence=?,
                        visibility=?,
                        lifecycle=?,
                        validity_status=?,
                        valid_from=?,
                        valid_to=?,
                        salience=?,
                        durability=?,
                        sensitivity=?,
                        review_status=?,
                        metadata=?,
                        canonical_key=?,
                        content_fingerprint=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        next_type,
                        next_content,
                        next_evidence,
                        next_importance,
                        next_confidence,
                        next_visibility,
                        next_lifecycle,
                        next_validity,
                        next_valid_from,
                        next_valid_to,
                        next_salience,
                        next_durability,
                        next_sensitivity,
                        next_review_status,
                        json_dumps(next_metadata),
                        atom.canonical_key,
                        atom.content_fingerprint,
                        utc_now(),
                        memory_id,
                    ),
                )
                row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
                self._upsert_memory_fts_row(row)
                return cur.rowcount > 0

    async def update_memory_reaction_feedback(
        self,
        memory_id: str,
        *,
        reaction: str,
        evidence: str,
        source_id: str = "",
        mention_delta: float = 0.0,
        confidence_delta: float = 0.0,
        emotional_delta: float = 0.0,
    ) -> bool:
        return await asyncio.to_thread(
            self._update_memory_reaction_feedback_sync,
            memory_id,
            reaction,
            evidence,
            source_id,
            mention_delta,
            confidence_delta,
            emotional_delta,
        )

    def _update_memory_reaction_feedback_sync(
        self,
        memory_id: str,
        reaction: str,
        evidence: str,
        source_id: str,
        mention_delta: float,
        confidence_delta: float,
        emotional_delta: float,
    ) -> bool:
        memory_id = clean_text(memory_id, 120)
        reaction = clean_text(reaction, 60)
        evidence = clean_text(redact_sensitive_text(evidence), 500)
        with self._lock:
            row = self._conn.execute("SELECT metadata, confidence FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                return False
            metadata = json_loads(row["metadata"], {})
            if not isinstance(metadata, dict):
                metadata = {}
            feedback = metadata.get("mention_feedback")
            if not isinstance(feedback, dict):
                feedback = {}
            source_id = clean_text(source_id, 120)
            applied_sources = feedback.get("applied_sources")
            if not isinstance(applied_sources, list):
                applied_sources = []
            if source_id and source_id in applied_sources:
                return False
            if source_id:
                applied_sources.append(source_id)
                feedback["applied_sources"] = applied_sources[-12:]
            count_key = f"{reaction}_count"
            try:
                feedback[count_key] = int(feedback.get(count_key) or 0) + 1
            except Exception:
                feedback[count_key] = 1
            now = utc_now()
            feedback["last_reaction"] = reaction
            feedback["last_reaction_at"] = now
            if evidence:
                feedback["last_evidence"] = evidence
            metadata["mention_feedback"] = feedback
            try:
                mentionability = float(metadata.get("mentionability_score", 0.5) or 0.5)
            except Exception:
                mentionability = 0.5
            mentionability = max(0.0, min(1.0, mentionability + float(mention_delta or 0.0)))
            metadata["mentionability_score"] = round(mentionability, 3)
            if reaction in {"awkward", "denied"} and mentionability <= 0.35:
                metadata["mention_policy"] = "avoid_unless_asked"
            elif reaction in {"accepted", "comforted", "touched", "nostalgic"} and mentionability >= 0.62:
                metadata["mention_policy"] = "soft_echo"
            if reaction == "corrected" and evidence:
                metadata["user_correction"] = {
                    "text": evidence,
                    "created_at": now,
                }
                metadata["mention_policy"] = "avoid_unless_asked"
            try:
                confidence = max(0.0, min(1.0, float(row["confidence"] or 0.5) + float(confidence_delta or 0.0)))
            except Exception:
                confidence = float(row["confidence"] or 0.5)
            if emotional_delta:
                try:
                    emotional = float(metadata.get("emotional_weight") or 0.0)
                except Exception:
                    emotional = 0.0
                metadata["emotional_weight"] = round(max(0.0, min(1.0, emotional + float(emotional_delta or 0.0))), 3)
            cur = self._conn.execute(
                """
                UPDATE memories
                SET metadata=?,
                    confidence=?,
                    updated_at=?
                WHERE id=?
                """,
                (json_dumps(metadata), confidence, now, memory_id),
            )
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            self._upsert_memory_fts_row(row)
            self._conn.commit()
            return cur.rowcount > 0

    async def delete_memory(self, memory_id: str) -> bool:
        return await asyncio.to_thread(self._delete_memory_sync, memory_id)

    def _delete_memory_sync(self, memory_id: str) -> bool:
        memory_id = clean_text(memory_id, 120)
        with self._lock:
            with self._transaction_sync():
                self._conn.execute("DELETE FROM review_queue WHERE memory_id=?", (memory_id,))
                self._conn.execute("DELETE FROM memory_embeddings WHERE memory_id=?", (memory_id,))
                self._conn.execute("DELETE FROM relationship_edges WHERE source_memory_id=?", (memory_id,))
                self._conn.execute("DELETE FROM knowledge_edges WHERE source_memory_id=?", (memory_id,))
                self._delete_memory_fts_row(memory_id)
                cur = self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
                return cur.rowcount > 0

    async def update_review_status(self, memory_id: str, status: str) -> bool:
        return await asyncio.to_thread(self._update_review_status_sync, memory_id, status)

    def _update_review_status_sync(self, memory_id: str, status: str) -> bool:
        memory_id = clean_text(memory_id, 120)
        now = utc_now()
        review_status = (
            "auto"
            if clean_text(status, 24).lower() in {"approve", "approved", "auto"}
            else "rejected"
        )
        lifecycle = "archived" if review_status == "rejected" else "stable_memory"
        with self._lock:  # noqa: SIM117
            with self._transaction_sync():
                row = self._conn.execute(
                    "SELECT * FROM memories WHERE id=?", (memory_id,)
                ).fetchone()
                if row is None:
                    return False

                record = MemoryRecord.from_row(row)
                metadata = (
                    dict(record.metadata) if isinstance(record.metadata, dict) else {}
                )
                extractor = clean_text(metadata.get("extractor"), 40).lower()
                dimension = clean_text(
                    metadata.get("profile_dimension"), 80
                ).lower()
                is_rule_profile = bool(
                    record.memory_type in self.PROFILE_MEMORY_TYPES
                    and extractor in self.PROFILE_RULE_EXTRACTORS
                )
                if not is_rule_profile:
                    self._conn.execute(
                        "UPDATE memories SET review_status=?, lifecycle=?, validity_status=?, updated_at=? WHERE id=?",
                        (
                            review_status,
                            lifecycle,
                            "archived" if lifecycle == "archived" else "active",
                            now,
                            memory_id,
                        ),
                    )
                    self._conn.execute(
                        "UPDATE review_queue SET status=?, updated_at=? WHERE memory_id=?",
                        (review_status, now, memory_id),
                    )
                    return True

                if review_status == "rejected":
                    metadata["profile_state"] = "rejected"
                    metadata["profile_status"] = "rejected"
                    metadata["profile_archive_reason"] = "manual_rejected"
                    metadata["profile_status_updated_at"] = now
                    metadata["quality_gate_passed"] = False
                    record.metadata = metadata
                    record.lifecycle = "archived"
                    record.validity_status = "archived"
                    record.review_status = "rejected"
                    record.updated_at = now
                    self._write_memory_record_sync(record)
                    self._conn.execute(
                        "DELETE FROM memory_embeddings WHERE memory_id=?", (record.id,)
                    )
                    self._conn.execute(
                        "UPDATE review_queue SET status='rejected', updated_at=? WHERE memory_id=?",
                        (now, record.id),
                    )
                    self._embedding_candidate_cache.clear()
                    self._embedding_candidate_cache_revision = ""
                    return True

                profile_value = clean_text(metadata.get("profile_value"), 240)
                normalized_value = normalize_profile_value(
                    metadata.get("normalized_value")
                )
                if (
                    not dimension
                    or not profile_value
                    or not normalized_value
                    or normalize_profile_value(profile_value) != normalized_value
                ):
                    return False

                domain_rows = self._profile_domain_rows_sync(record)
                try:
                    quality_score = float(
                        metadata.get("extraction_quality_score") or 0.0
                    )
                except (TypeError, ValueError):
                    quality_score = 0.0
                if not math.isfinite(quality_score):
                    quality_score = 0.0
                metadata["profile_state"] = "active"
                metadata["profile_status"] = "active"
                metadata["extraction_quality"] = "confirmed"
                metadata["extraction_quality_score"] = round(
                    max(0.95, min(1.0, quality_score)), 4
                )
                metadata["evidence_strength"] = "user_confirmed"
                metadata["quality_gate_passed"] = True
                metadata["required_evidence_count"] = 1
                metadata["profile_confirmation_source"] = "manual_review"
                metadata["profile_status_updated_at"] = now
                metadata["profile_cardinality"] = (
                    "single"
                    if dimension in self.PROFILE_SINGLE_VALUE_DIMENSIONS
                    else clean_text(metadata.get("profile_cardinality"), 20).lower()
                    or "multi"
                )
                record.metadata = metadata
                record.confidence = max(float(record.confidence or 0.0), 0.95)
                record.lifecycle = "stable_memory"
                record.validity_status = "active"
                record.review_status = "auto"
                record.updated_at = now
                self._write_memory_record_sync(record)

                cardinality = metadata["profile_cardinality"]
                if cardinality == "single":
                    for domain_row in domain_rows:
                        other = MemoryRecord.from_row(domain_row)
                        if other.id == record.id or self._profile_state(other) != "active":
                            continue
                        other_metadata = (
                            dict(other.metadata)
                            if isinstance(other.metadata, dict)
                            else {}
                        )
                        if (
                            clean_text(
                                other_metadata.get("profile_dimension"), 80
                            ).lower()
                            != dimension
                        ):
                            continue
                        other_metadata["profile_state"] = "superseded"
                        other_metadata["profile_status"] = "superseded"
                        other_metadata["profile_superseded_by"] = record.id
                        other_metadata["profile_status_updated_at"] = now
                        other.metadata = other_metadata
                        other.lifecycle = "archived"
                        other.validity_status = "superseded"
                        other.review_status = "auto"
                        other.supersedes_id = record.id
                        other.updated_at = now
                        self._write_memory_record_sync(other)
                        self._conn.execute(
                            "DELETE FROM memory_embeddings WHERE memory_id=?",
                            (other.id,),
                        )
                        self._conn.execute(
                            "UPDATE review_queue SET status='superseded', updated_at=? WHERE memory_id=?",
                            (now, other.id),
                        )

                self._conn.execute(
                    "UPDATE review_queue SET status='auto', updated_at=? WHERE memory_id=?",
                    (now, record.id),
                )
                self._embedding_candidate_cache.clear()
                self._embedding_candidate_cache_revision = ""
                return True

    async def approve_livingmemory_imports(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._approve_livingmemory_imports_sync)

    def _approve_livingmemory_imports_sync(self) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id
                FROM memories
                WHERE source_plugin='livingmemory' AND review_status='pending'
                """
            ).fetchall()
            ids = [row["id"] for row in rows]
            if not ids:
                return {"updated": 0, "review_queue_updated": 0}
            placeholders = ",".join("?" for _ in ids)
            memory_cur = self._conn.execute(
                f"""
                UPDATE memories
                SET review_status='auto',
                    lifecycle='stable_memory',
                    updated_at=?
                WHERE id IN ({placeholders})
                """,
                [now] + ids,
            )
            queue_cur = self._conn.execute(
                f"""
                UPDATE review_queue
                SET status='auto',
                    updated_at=?
                WHERE memory_id IN ({placeholders}) AND status='pending'
                """,
                [now] + ids,
            )
            self._conn.commit()
        return {
            "updated": int(memory_cur.rowcount or 0),
            "review_queue_updated": int(queue_cur.rowcount or 0),
        }

    async def list_livingmemory_content_repair_candidates(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_livingmemory_content_repair_candidates_sync)

    def _list_livingmemory_content_repair_candidates_sync(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, content, evidence, metadata
                FROM memories
                WHERE source_plugin='livingmemory'
                """
            ).fetchall()
        candidates = []
        for row in rows:
            content = clean_text(row["content"], 80)
            if content.isdigit():
                candidates.append(dict(row))
        return candidates

    async def update_livingmemory_import_payload(self, memory_id: str, payload: dict[str, Any]) -> bool:
        return await asyncio.to_thread(self._update_livingmemory_import_payload_sync, memory_id, payload)

    def _update_livingmemory_import_payload_sync(self, memory_id: str, payload: dict[str, Any]) -> bool:
        with self._lock:
            cur = self._conn.execute(
                """
                UPDATE memories
                SET content=?,
                    evidence=?,
                    metadata=?,
                    scope=?,
                    session_id=?,
                    group_id=?,
                    visibility=?,
                    object_kind=?,
                    object_id=?,
                    object_role=?,
                    occurred_at=COALESCE(NULLIF(?, ''), occurred_at),
                    content_fingerprint='',
                    updated_at=?
                WHERE id=? AND source_plugin='livingmemory'
                """,
                (
                    clean_text(redact_sensitive_text(payload.get("content")), 4000),
                    clean_text(redact_sensitive_text(payload.get("evidence")), 4000),
                    json_dumps(redact_sensitive_value(payload.get("metadata") or {})),
                    clean_text(payload.get("scope"), 40),
                    clean_text(payload.get("session_id"), 200),
                    clean_text(payload.get("group_id"), 120),
                    clean_text(payload.get("visibility"), 40),
                    clean_text(payload.get("object_kind"), 40),
                    clean_text(payload.get("object_id"), 120),
                    clean_text(payload.get("object_role"), 80),
                    clean_text(payload.get("occurred_at"), 80),
                    utc_now(),
                    clean_text(memory_id, 120),
                ),
            )
            self._conn.commit()
            return cur.rowcount > 0

    async def update_memory_visibility(self, memory_id: str, visibility: str) -> bool:
        return await asyncio.to_thread(self._update_memory_visibility_sync, memory_id, visibility)

    def _update_memory_visibility_sync(self, memory_id: str, visibility: str) -> bool:
        memory_id = clean_text(memory_id, 120)
        visibility = clean_text(visibility, 40)
        now = utc_now()
        with self._lock:  # noqa: SIM117
            with self._transaction_sync():
                row = self._conn.execute(
                    "SELECT * FROM memories WHERE id=?", (memory_id,)
                ).fetchone()
                if row is None:
                    return False
                record = MemoryRecord.from_row(row)
                target = deepcopy(record)
                target.visibility = visibility
                if self._profile_single_value_domain_conflict_sync(target):
                    return False
                cur = self._conn.execute(
                    "UPDATE memories SET visibility=?, updated_at=? WHERE id=?",
                    (visibility, now, memory_id),
                )
                if cur.rowcount:
                    self._embedding_candidate_cache.clear()
                    self._embedding_candidate_cache_revision = ""
                return cur.rowcount > 0

    async def update_memory_lifecycle(self, memory_id: str, lifecycle: str) -> bool:
        return await asyncio.to_thread(self._update_memory_lifecycle_sync, memory_id, lifecycle)

    def _update_memory_lifecycle_sync(self, memory_id: str, lifecycle: str) -> bool:
        lifecycle = clean_text(lifecycle, 40)
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET lifecycle=?, validity_status=?, updated_at=? WHERE id=?",
                (
                    lifecycle,
                    "archived" if lifecycle == "archived" else "active",
                    utc_now(),
                    clean_text(memory_id, 120),
                ),
            )
            self._conn.commit()
            return cur.rowcount > 0

    async def maintenance_repair(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._maintenance_repair_sync)

    def _maintenance_repair_sync(self) -> dict[str, Any]:
        with self._lock:
            with self._transaction_sync():
                manual_fixed = self._normalize_legacy_manual_visibility_sync()
                internal_bot_self_fixed = self._normalize_internal_bot_self_scopes_sync()
                utterance_fixed_cur = self._conn.execute(
                    """
                    UPDATE memories
                    SET reality_level='observed_utterance', updated_at=?
                    WHERE memory_type='conversation_event' AND reality_level='real_user_fact'
                    """,
                    (utc_now(),),
                )
                all_rows = self._conn.execute("SELECT * FROM memories").fetchall()
                fingerprint_fixed = 0
                for row in all_rows:
                    record = MemoryRecord.from_row(row)
                    old_fingerprint = record.content_fingerprint
                    record.content_fingerprint = ""
                    record.ensure_defaults()
                    if record.content_fingerprint != old_fingerprint or int(row["merged_count"] or 0) < 1:
                        self._conn.execute(
                            "UPDATE memories SET content_fingerprint=?, merged_count=max(merged_count, 1), updated_at=? WHERE id=?",
                            (record.content_fingerprint, utc_now(), record.id),
                        )
                        fingerprint_fixed += 1

                duplicates = self._conn.execute(
                    """
                    SELECT content_fingerprint, COUNT(*) AS count
                    FROM memories
                    WHERE content_fingerprint!='' AND lifecycle!='archived'
                    GROUP BY content_fingerprint
                    HAVING count > 1
                    """
                ).fetchall()
                merged = 0
                for dup in duplicates:
                    rows = self._conn.execute(
                        """
                        SELECT id, importance, confidence, merged_count, created_at
                        FROM memories
                        WHERE content_fingerprint=? AND lifecycle!='archived'
                        ORDER BY merged_count DESC, importance DESC, created_at ASC
                        """,
                        (dup["content_fingerprint"],),
                    ).fetchall()
                    keep = rows[0]
                    for row in rows[1:]:
                        self._conn.execute(
                            """
                            UPDATE memories
                            SET lifecycle='archived', validity_status='archived', supersedes_id=?, updated_at=?
                            WHERE id=?
                            """,
                            (keep["id"], utc_now(), row["id"]),
                        )
                        self._conn.execute(
                            """
                            UPDATE memories
                            SET importance=max(importance, ?),
                                confidence=max(confidence, ?),
                                merged_count=COALESCE(merged_count, 1) + COALESCE(?, 1),
                                updated_at=?
                            WHERE id=?
                            """,
                            (
                                row["importance"],
                                row["confidence"],
                                row["merged_count"],
                                utc_now(),
                                keep["id"],
                            ),
                        )
                        merged += 1
                # A repair pass runs automatically shortly after startup.  Rebuilding
                # the complete FTS table on every pass needlessly holds the write lock
                # and can starve the event loop while other plugins are active.  Only
                # rebuild when repair changed indexed content, or when the row counts
                # show that an index is genuinely incomplete.  Explicit index rebuilds
                # remain available through ``rebuild_memory_indexes``.
                fts_rebuild_needed = bool(fingerprint_fixed or merged)
                if self._fts_enabled and not fts_rebuild_needed:
                    memory_count = int(self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] or 0)
                    fts_count = int(self._conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] or 0)
                    fts_rebuild_needed = memory_count != fts_count
                fts_rebuilt = self._rebuild_memory_fts_sync() if self._fts_enabled and fts_rebuild_needed else 0
        return {
            "manual_visibility_fixed": manual_fixed,
            "internal_bot_self_scope_fixed": internal_bot_self_fixed,
            "utterance_reality_fixed": int(utterance_fixed_cur.rowcount or 0),
            "fingerprint_fixed": fingerprint_fixed,
            "duplicates_archived": merged,
            "fts_rebuilt": fts_rebuilt,
        }

    async def list_decay_candidate_pool(self, limit: int = 2000) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._list_decay_candidate_pool_sync, limit)

    def _list_decay_candidate_pool_sync(self, limit: int) -> list[MemoryRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT *
                FROM memories
                WHERE lifecycle='stable_memory'
                  AND review_status!='pending'
                ORDER BY
                    COALESCE(NULLIF(occurred_at, ''), created_at) ASC,
                    created_at ASC
                LIMIT ?
                """,
                (max(1, int(limit or 1)),),
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    async def archive_raw_events_older_than(self, cutoff_at: str, limit: int = 1000) -> int:
        return await asyncio.to_thread(self._archive_raw_events_older_than_sync, cutoff_at, limit)

    def _archive_raw_events_older_than_sync(self, cutoff_at: str, limit: int) -> int:
        cutoff_at = clean_text(cutoff_at, 80)
        if not cutoff_at:
            return 0
        now = utc_now()
        with self._lock:
            with self._transaction_sync():
                rows = self._conn.execute(
                    """
                    SELECT id, metadata
                    FROM memories
                    WHERE lifecycle='raw_event'
                      AND COALESCE(NULLIF(occurred_at, ''), created_at) < ?
                    ORDER BY COALESCE(NULLIF(occurred_at, ''), created_at) ASC
                    LIMIT ?
                    """,
                    (cutoff_at, max(1, int(limit or 1))),
                ).fetchall()
                archived = 0
                for row in rows:
                    metadata = json_loads(row["metadata"], {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    metadata["retention_archived"] = {
                        "reason": "raw_event_retention",
                        "cutoff_at": cutoff_at,
                        "archived_at": now,
                    }
                    cur = self._conn.execute(
                        """
                        UPDATE memories
                        SET lifecycle='archived',
                            validity_status='archived',
                            metadata=?,
                            updated_at=?
                        WHERE id=? AND lifecycle='raw_event'
                        """,
                        (json_dumps(metadata), now, row["id"]),
                    )
                    archived += int(cur.rowcount or 0)
        return archived

    async def prune_retained_rows(
        self,
        *,
        summarized_timeline_cutoff: str = "",
        injection_log_cutoff: str = "",
        limit: int = 2000,
    ) -> dict[str, int]:
        return await asyncio.to_thread(
            self._prune_retained_rows_sync,
            summarized_timeline_cutoff,
            injection_log_cutoff,
            limit,
        )

    def _prune_retained_rows_sync(
        self,
        summarized_timeline_cutoff: str,
        injection_log_cutoff: str,
        limit: int,
    ) -> dict[str, int]:
        summarized_timeline_cutoff = clean_text(summarized_timeline_cutoff, 80)
        injection_log_cutoff = clean_text(injection_log_cutoff, 80)
        safe_limit = max(1, int(limit or 1))
        deleted = {"timeline": 0, "injection_logs": 0}
        with self._lock:
            with self._transaction_sync():
                if summarized_timeline_cutoff:
                    rows = self._conn.execute(
                        """
                        SELECT id
                        FROM timeline
                        WHERE summarized_at!=''
                          AND retention_class!='historical_archive'
                          AND COALESCE(NULLIF(occurred_at, ''), created_at) < ?
                        ORDER BY COALESCE(NULLIF(occurred_at, ''), created_at) ASC
                        LIMIT ?
                        """,
                        (summarized_timeline_cutoff, safe_limit),
                    ).fetchall()
                    ids = [row["id"] for row in rows]
                    if ids:
                        result: dict[str, int] = {}
                        self._delete_many_by_ids("timeline", "id", ids, result)
                        deleted["timeline"] = result.get("timeline", 0)
                if injection_log_cutoff:
                    rows = self._conn.execute(
                        """
                        SELECT id
                        FROM injection_logs
                        WHERE created_at < ?
                        ORDER BY created_at ASC
                        LIMIT ?
                        """,
                        (injection_log_cutoff, safe_limit),
                    ).fetchall()
                    ids = [row["id"] for row in rows]
                    if ids:
                        result = {}
                        self._delete_many_by_ids("injection_logs", "id", ids, result)
                        deleted["injection_logs"] = result.get("injection_logs", 0)
        return deleted

    async def archive_memories(
        self,
        memory_ids: list[str],
        *,
        reason: str,
        supersedes_id: str = "",
    ) -> int:
        return await asyncio.to_thread(
            self._archive_memories_sync,
            memory_ids,
            reason,
            supersedes_id,
        )

    def _archive_memories_sync(self, memory_ids: list[str], reason: str, supersedes_id: str) -> int:
        ids = [clean_text(memory_id, 120) for memory_id in memory_ids if clean_text(memory_id, 120)]
        if not ids:
            return 0
        now = utc_now()
        reason = clean_text(reason, 120)
        supersedes_id = clean_text(supersedes_id, 120)
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, metadata FROM memories WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            archived = 0
            for row in rows:
                metadata = json_loads(row["metadata"], {})
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["decay_archived"] = {
                    "reason": reason,
                    "supersedes_id": supersedes_id,
                    "archived_at": now,
                }
                cur = self._conn.execute(
                    """
                    UPDATE memories
                    SET lifecycle='archived',
                        validity_status='archived',
                        supersedes_id=?,
                        metadata=?,
                        updated_at=?
                    WHERE id=? AND lifecycle!='archived'
                    """,
                    (supersedes_id, json_dumps(metadata), now, row["id"]),
                )
                archived += int(cur.rowcount or 0)
            self._conn.commit()
        return archived

    async def list_review_queue(self, limit: int = 20) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_review_queue_sync, limit)

    def _list_review_queue_sync(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    rq.id,
                    rq.memory_id,
                    rq.reason,
                    rq.status,
                    rq.created_at,
                    m.memory_type,
                    m.subject_id,
                    m.subject_name,
                    m.object_id,
                    m.object_name,
                    m.scope,
                    m.session_id,
                    m.group_id,
                    m.visibility,
                    m.sayability,
                    m.reality_level,
                    m.lifecycle,
                    m.content,
                    m.evidence,
                    m.confidence,
                    m.importance,
                    m.tags,
                    m.metadata,
                    m.source_plugin,
                    m.import_batch_id,
                    m.occurred_at
                FROM review_queue rq
                LEFT JOIN memories m ON m.id = rq.memory_id
                WHERE rq.status = 'pending'
                ORDER BY rq.created_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    async def upsert_memory_embedding(
        self,
        *,
        memory_id: str,
        provider_id: str,
        text_hash: str,
        vector: list[float],
    ) -> None:
        await self._run_recoverable_database_operation(
            self._upsert_memory_embedding_sync,
            memory_id,
            provider_id,
            text_hash,
            vector,
        )

    def _upsert_memory_embedding_sync(
        self,
        memory_id: str,
        provider_id: str,
        text_hash: str,
        vector: list[float],
    ) -> None:
        memory_id = clean_text(memory_id, 120)
        provider_id = clean_text(provider_id, 160)
        text_hash = clean_text(text_hash, 80)
        values = [float(item) for item in vector if isinstance(item, (int, float))]
        if not memory_id or not provider_id or not text_hash or not values:
            return
        now = utc_now()
        packed = _pack_embedding_vector(values)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_embeddings(
                    memory_id, provider_id, text_hash, dimension, vector, created_at, updated_at
                )
                SELECT ?,?,?,?,?,?,?
                WHERE EXISTS(SELECT 1 FROM memories WHERE id=?)
                ON CONFLICT(memory_id, provider_id) DO UPDATE SET
                    text_hash=excluded.text_hash,
                    dimension=excluded.dimension,
                    vector=excluded.vector,
                    updated_at=excluded.updated_at
                """,
                (
                    memory_id,
                    provider_id,
                    text_hash,
                    len(values),
                    packed,
                    now,
                    now,
                    memory_id,
                ),
            )
            self._conn.commit()

    async def list_embedding_candidate_rows(
        self,
        *,
        provider_id: str,
        limit: int = 3000,
        include_pending: bool = False,
    ) -> list[tuple[MemoryRecord, list[float], str]]:
        return await self._run_recoverable_database_operation(
            self._list_embedding_candidate_rows_sync,
            provider_id,
            limit,
            include_pending,
        )

    def _list_embedding_candidate_rows_sync(
        self,
        provider_id: str,
        limit: int,
        include_pending: bool,
    ) -> list[tuple[MemoryRecord, list[float], str]]:
        provider_id = clean_text(provider_id, 160)
        if not provider_id:
            return []
        safe_limit = max(1, int(limit or 1))
        with self._lock:
            revision = self._memory_revision_sync()
            if revision != self._embedding_candidate_cache_revision:
                self._embedding_candidate_cache.clear()
                self._embedding_candidate_cache_revision = revision
            cache_key = (provider_id, bool(include_pending), safe_limit)
            cached = self._embedding_candidate_cache.get(cache_key)
            if cached is not None:
                return deepcopy(cached)
        where = f"m.lifecycle != 'archived' AND {self._recallable_memory_sql('m')} AND e.provider_id=?"
        params: list[Any] = [provider_id]
        if not include_pending:
            where += " AND m.review_status != 'pending'"
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    m.*,
                    e.vector AS embedding_vector,
                    e.text_hash AS embedding_text_hash
                FROM memory_embeddings e
                JOIN memories m ON m.id=e.memory_id
                WHERE {where}
                ORDER BY m.importance DESC, COALESCE(NULLIF(m.occurred_at, ''), m.created_at) DESC
                LIMIT ?
                """,
                params + [safe_limit],
            ).fetchall()
        result: list[tuple[MemoryRecord, list[float], str]] = []
        for row in rows:
            vector = _normalize_embedding_vector_values(
                _unpack_embedding_vector(row["embedding_vector"])
            )
            if not vector:
                continue
            result.append((MemoryRecord.from_row(row), vector, clean_text(row["embedding_text_hash"], 80)))
        with self._lock:
            self._embedding_candidate_cache[cache_key] = result
            while len(self._embedding_candidate_cache) > self.EMBEDDING_CANDIDATE_CACHE_MAX:
                self._embedding_candidate_cache.pop(next(iter(self._embedding_candidate_cache)), None)
        return deepcopy(result)

    async def list_memories_missing_embeddings(
        self,
        *,
        provider_id: str,
        limit: int = 80,
        include_pending: bool = False,
        embedding_max_text_chars: int = 1200,
    ) -> list[MemoryRecord]:
        return await self._run_recoverable_database_operation(
            self._list_memories_missing_embeddings_sync,
            provider_id,
            limit,
            include_pending,
            embedding_max_text_chars,
        )

    async def scan_memories_missing_embeddings(
        self,
        *,
        provider_id: str,
        limit: int = 80,
        include_pending: bool = False,
        embedding_max_text_chars: int = 1200,
        offset: int = 0,
    ) -> tuple[list[MemoryRecord], int, bool]:
        """Scan one bounded window and return (stale records, next offset, exhausted)."""

        return await self._run_recoverable_database_operation(
            self._scan_memories_missing_embeddings_sync,
            provider_id,
            limit,
            include_pending,
            embedding_max_text_chars,
            offset,
        )

    def _list_memories_missing_embeddings_sync(
        self,
        provider_id: str,
        limit: int,
        include_pending: bool,
        embedding_max_text_chars: int,
    ) -> list[MemoryRecord]:
        result, _next_offset, _exhausted = self._scan_memories_missing_embeddings_sync(
            provider_id,
            limit,
            include_pending,
            embedding_max_text_chars,
            0,
        )
        return result

    def _scan_memories_missing_embeddings_sync(
        self,
        provider_id: str,
        limit: int,
        include_pending: bool,
        embedding_max_text_chars: int,
        offset: int,
    ) -> tuple[list[MemoryRecord], int, bool]:
        provider_id = clean_text(provider_id, 160)
        if not provider_id:
            return [], 0, True
        where = f"m.lifecycle != 'archived' AND {self._recallable_memory_sql('m')}"
        params: list[Any] = [provider_id]
        if not include_pending:
            where += " AND m.review_status != 'pending'"
        safe_limit = max(1, int(limit or 1))
        # Hash validation is intentionally done in Python because SQLite cannot
        # evaluate the canonical embedding document. Keep the scan bounded; the
        # existing importance/time ordering brings recently changed memories into
        # the next backfill pass first.
        scan_limit = max(safe_limit, min(2000, safe_limit * 8))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT m.*
                    ,e.text_hash AS embedding_text_hash
                FROM memories m
                LEFT JOIN memory_embeddings e
                  ON e.memory_id=m.id AND e.provider_id=?
                WHERE {where}
                  ORDER BY m.importance DESC, COALESCE(NULLIF(m.occurred_at, ''), m.created_at) DESC
                  LIMIT ?
                  OFFSET ?
                """,
                params + [scan_limit, max(0, int(offset or 0))],
            ).fetchall()
        result: list[MemoryRecord] = []
        processed = 0
        for processed, row in enumerate(rows, start=1):
            record = MemoryRecord.from_row(row)
            stored_hash = clean_text(row["embedding_text_hash"], 80)
            expected_hash = memory_embedding_text_hash(
                record,
                max_chars=embedding_max_text_chars,
            )
            if not stored_hash or stored_hash != expected_hash:
                result.append(record)
                if len(result) >= safe_limit:
                    break
        next_offset = max(0, int(offset or 0)) + processed
        exhausted = processed >= len(rows) and len(rows) < scan_limit
        return result, next_offset, exhausted

    async def mark_accessed(self, memory_ids: list[str]) -> None:
        await asyncio.to_thread(self._mark_accessed_sync, memory_ids)

    def _mark_accessed_sync(self, memory_ids: list[str]) -> None:
        ids = [memory_id for memory_id in memory_ids if memory_id]
        if not ids:
            return
        now = utc_now()
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            self._conn.execute(
                f"""
                UPDATE memories
                SET access_count = access_count + 1, last_accessed_at = ?
                WHERE id IN ({placeholders})
                """,
                [now] + ids,
            )
            self._conn.commit()

    async def mark_injected(self, memory_ids: list[str], when: str = "") -> int:
        """Record only memories that reached the final injected context."""

        return await asyncio.to_thread(self._mark_injected_sync, memory_ids, when)

    def _mark_injected_sync(self, memory_ids: list[str], when: str = "") -> int:
        ids = list(
            dict.fromkeys(
                clean_text(memory_id, 120)
                for memory_id in memory_ids or []
                if clean_text(memory_id, 120)
            )
        )
        if not ids:
            return 0
        timestamp = clean_text(when, 80) or utc_now()
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            cur = self._conn.execute(
                f"""
                UPDATE memories
                SET injection_count = injection_count + 1,
                    last_injected_at = ?,
                    reinforcement_score = min(1.0, reinforcement_score + 0.025)
                WHERE id IN ({placeholders})
                """,
                [timestamp, *ids],
            )
            self._conn.commit()
        return max(0, int(cur.rowcount or 0))

    async def stats(self) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(self._stats_sync)

    async def memory_revision(self) -> str:
        return await self._run_recoverable_database_operation(self._memory_revision_sync)

    def _memory_revision_sync(self) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT revision FROM retrieval_revision WHERE singleton=1"
            ).fetchone()
        if not row:
            return "0"
        return str(int(row["revision"] or 0))

    def _stats_sync(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            pending = self._conn.execute("SELECT COUNT(*) FROM memories WHERE review_status='pending'").fetchone()[0]
            stable = self._conn.execute("SELECT COUNT(*) FROM memories WHERE lifecycle='stable_memory'").fetchone()[0]
            identities = self._conn.execute("SELECT COUNT(*) FROM identities").fetchone()[0]
            timeline = self._conn.execute("SELECT COUNT(*) FROM timeline").fetchone()[0]
            relationships = self._conn.execute("SELECT COUNT(*) FROM relationship_edges").fetchone()[0]
            knowledge_nodes = self._conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0]
            knowledge_edges = self._conn.execute("SELECT COUNT(*) FROM knowledge_edges").fetchone()[0]
            open_threads = self._conn.execute(
                "SELECT COUNT(*) FROM cross_window_threads WHERE status='open'"
            ).fetchone()[0]
            injection_logs = self._conn.execute("SELECT COUNT(*) FROM injection_logs").fetchone()[0]
            acl_rules = self._conn.execute("SELECT COUNT(*) FROM memory_acl_rules WHERE enabled=1").fetchone()[0]
            by_scope = {
                row["scope"]: row["count"]
                for row in self._conn.execute("SELECT scope, COUNT(*) AS count FROM memories GROUP BY scope").fetchall()
            }
        current_wal_files = self._database_file_snapshot()
        last_wal_health = dict(self._last_wal_health)
        memory_storage = {
            "database_bytes": max(0, int(current_wal_files.get("db_bytes") or 0)),
            "wal_bytes": max(0, int(current_wal_files.get("wal_bytes") or 0)),
            "shm_bytes": max(0, int(current_wal_files.get("shm_bytes") or 0)),
        }
        memory_storage["total_bytes"] = sum(memory_storage.values())
        return {
            "db_path": str(self.db_path),
            "memory_storage_bytes": memory_storage["total_bytes"],
            "memory_storage": memory_storage,
            "total_memories": total,
            "pending_review": pending,
            "stable_memories": stable,
            "identities": identities,
            "timeline_events": timeline,
            "relationships": relationships,
            "knowledge_nodes": knowledge_nodes,
            "knowledge_edges": knowledge_edges,
            "open_threads": open_threads,
            "injection_logs": injection_logs,
            "acl_rules": acl_rules,
            "by_scope": by_scope,
            "wal": {
                **last_wal_health,
                **current_wal_files,
                "current_files": current_wal_files,
                "last_health_check": last_wal_health,
                "last_database_error": dict(self._last_database_error),
                "database_recovery_attempts": self._database_recovery_attempts,
                "database_recovery_successes": self._database_recovery_successes,
            },
        }

    async def add_import_batch(
        self,
        *,
        source_plugin: str,
        source_path: str,
        mode: str,
        stats: dict[str, Any],
    ) -> str:
        return await asyncio.to_thread(
            self._add_import_batch_sync, source_plugin, source_path, mode, stats
        )

    def _add_import_batch_sync(
        self, source_plugin: str, source_path: str, mode: str, stats: dict[str, Any]
    ) -> str:
        row_id = new_id("import")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO import_batches(id, source_plugin, source_path, mode, stats, created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (row_id, source_plugin, source_path, mode, json_dumps(stats), utc_now()),
            )
            self._conn.commit()
        return row_id

    async def import_batch_ops(self, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量导入写入（portable JSONL 导入用），合并为单事务一次 commit。

        ops 为有序写入描述列表，元素形如：
          - {"kind": "memory", "record": MemoryRecord, "review_reason": str}
          - {"kind": "identity", "params": {platform, entity, aliases, profile, confidence}}
          - {"kind": "relationship", "params": {详见 _upsert_relationship_sync 关键字参数}}
          - {"kind": "timeline", "params": {event_type, session_id, scope, subject_id,
             object_id, content, metadata, occurred_at}, "summarize": bool}
          - {"kind": "acl_rule", "params": {owner_scope, owner_id, reader_scope,
             reader_id, effect, enabled, note}}
          - {"kind": "acl_policy", "params": {window_scope, window_id, read_mode,
             share_mode, capture_enabled, recall_enabled}}
        单项失败被 SAVEPOINT 隔离，不拖累整批；全部完成后一次 commit。
        返回与 ops 等长的结果列表，每项为 {"ok": bool, ...}。
        """
        return await asyncio.to_thread(self._import_batch_ops_sync, ops)

    def _import_batch_ops_sync(
        self, ops: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not ops:
            return results
        with self._lock:
            with self._transaction_sync():
                for index, op in enumerate(ops):
                    kind = op["kind"]
                    try:
                        with self._transaction_sync():  # 单项 SAVEPOINT 隔离失败
                            if kind == "memory":
                                memory_id = self._insert_memory_sync(
                                    op["record"],
                                    op.get("review_reason") or "",
                                    _commit=False,
                                )
                                results.append({"ok": True, "memory_id": memory_id})
                            elif kind == "identity":
                                row_id = self._upsert_identity_row_locked(
                                    **op["params"]
                                )
                                results.append({"ok": True, "row_id": row_id})
                            elif kind == "relationship":
                                row_id = self._upsert_relationship_sync(
                                    _commit=False, **op["params"]
                                )
                                results.append({"ok": True, "row_id": row_id})
                            elif kind == "timeline":
                                event_id = self._add_timeline_event_sync(
                                    **op["params"]
                                )
                                if op.get("summarize"):
                                    self._mark_timeline_summarized_sync(
                                        [event_id], _commit=False
                                    )
                                results.append({"ok": True, "event_id": event_id})
                            elif kind == "acl_rule":
                                result = self._upsert_acl_rule_sync(
                                    _commit=False, **op["params"]
                                )
                                results.append({"ok": True, "result": result})
                            elif kind == "acl_policy":
                                result = self._upsert_acl_policy_sync(
                                    _commit=False, **op["params"]
                                )
                                results.append({"ok": True, "result": result})
                            else:
                                results.append(
                                    {"ok": False, "code": f"unknown_batch_op:{kind}"}
                                )
                    except Exception as exc:
                        logger.warning(
                            "[MemoryCompanion] 批量导入单项失败 index=%s kind=%s error=%s",
                            index,
                            kind,
                            exc,
                            exc_info=True,
                        )
                        results.append(
                            {
                                "ok": False,
                                "code": "batch_op_error",
                                "error": clean_text(str(exc), 300),
                            }
                        )
        return results

    async def upsert_emotion_event(self, value: Any) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(self._upsert_emotion_event_sync, value)

    def _upsert_emotion_event_sync(self, value: Any) -> dict[str, Any]:
        from .emotion_event_contract import normalize_emotion_event

        event = normalize_emotion_event(value, producer_plugin="memory_companion")
        with self._lock:
            with self._transaction_sync():
                existing_rows = self._conn.execute(
                    "SELECT * FROM emotion_events WHERE event_id=?",
                    (event["event_id"],),
                ).fetchall()
                event_domain = self._emotion_event_identity_domain(event)
                if any(
                    self._emotion_event_identity_domain(self._emotion_event_row(row)) != event_domain
                    for row in existing_rows
                ):
                    raise ValueError("emotion event_id is already bound to another identity domain")
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO emotion_events(
                        event_id, revision, trace_id, producer_plugin, origin_kind, platform,
                        bot_id, scope, session_id, actor_ref, target_ref, quoted_target_ref,
                        event_type, intensity, confidence, valence_hint, arousal_hint,
                        vulnerability_hint, source_rule, occurred_at, expires_at, dedupe_key,
                        payload_hash, privacy_level, applied_interaction, applied_energy_delta,
                        correction_of, status, reason_codes, created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event["event_id"], event["revision"], event["trace_id"], event["producer_plugin"],
                        event["origin_kind"], event["platform"], event["bot_id"], event["scope"],
                        event["session_id"], json_dumps(event["actor_ref"]), json_dumps(event["target_ref"]),
                        json_dumps(event["quoted_target_ref"]), event["event_type"], event["intensity"],
                        event["confidence"], event["valence_hint"], event["arousal_hint"],
                        event["vulnerability_hint"], event["source_rule"], event["occurred_at"],
                        event["expires_at"], event["dedupe_key"], event["payload_hash"],
                        event["privacy_level"], event["applied_interaction"], event["applied_energy_delta"],
                        event["correction_of"], event["status"], json_dumps(event["reason_codes"]), utc_now(),
                    ),
                )
        return event

    async def get_emotion_trace(self, trace_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return await self._run_recoverable_database_operation(self._get_emotion_trace_sync, trace_id, limit)

    def _get_emotion_trace_sync(self, trace_id: str, limit: int) -> list[dict[str, Any]]:
        trace = clean_text(trace_id, 96)
        if not trace:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM emotion_events WHERE trace_id=? ORDER BY revision ASC LIMIT ?",
                (trace, max(1, min(500, int(limit or 100)))),
            ).fetchall()
        return [self._emotion_event_row(row) for row in rows]

    async def get_emotion_trace_diagnostic(
        self,
        trace_id: str,
        *,
        bot_id: str = "",
        scope: str = "",
        session_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await self._run_recoverable_database_operation(
            self._get_emotion_trace_diagnostic_sync, trace_id, bot_id, scope, session_id, limit
        )

    def _get_emotion_trace_diagnostic_sync(
        self,
        trace_id: str,
        bot_id: str,
        scope: str,
        session_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        trace = clean_text(trace_id, 96)
        if not trace:
            return []
        clauses = ["e.trace_id=?"]
        params: list[Any] = [trace]
        for column, value, size in (("bot_id", bot_id, 160), ("scope", scope, 24), ("session_id", session_id, 220)):
            cleaned = clean_text(value, size)
            if cleaned:
                clauses.append(f"e.{column}=?")
                params.append(cleaned)
        params.append(max(1, min(100, int(limit or 100))))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT e.* FROM emotion_events e WHERE {' AND '.join(clauses)} ORDER BY e.revision ASC LIMIT ?",
                params,
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                event = self._emotion_event_row(row)
                delivery_rows = self._conn.execute(
                    """
                    SELECT consumer_id, attempts, first_delivered_at, last_delivered_at, acked_at
                    FROM emotion_event_deliveries
                    WHERE event_id=? AND revision=?
                    ORDER BY consumer_id ASC LIMIT 20
                    """,
                    (event["event_id"], event["revision"]),
                ).fetchall()
                deliveries = []
                for delivery in delivery_rows:
                    values = dict(delivery)
                    values["consumer_id"] = clean_text(
                        values.get("consumer_id"), 120
                    ).split("@", 1)[0]
                    deliveries.append(values)
                result.append(self._emotion_diagnostic_projection(event, deliveries))
        return result

    async def get_emotion_trace_summary(
        self,
        *,
        bot_id: str = "",
        scope: str = "",
        session_id: str = "",
        cursor: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(
            self._get_emotion_trace_summary_sync, bot_id, scope, session_id, cursor, limit
        )

    def _get_emotion_trace_summary_sync(
        self,
        bot_id: str,
        scope: str,
        session_id: str,
        cursor: str,
        limit: int,
    ) -> dict[str, Any]:
        clauses = ["1=1"]
        params: list[Any] = []
        for column, value, size in (("bot_id", bot_id, 160), ("scope", scope, 24), ("session_id", session_id, 220)):
            cleaned = clean_text(value, size)
            if cleaned:
                clauses.append(f"e.{column}=?")
                params.append(cleaned)
        try:
            offset = max(0, min(100000, int(cursor or 0)))
        except (TypeError, ValueError):
            offset = 0
        bounded = max(1, min(100, int(limit or 20)))
        params.extend((bounded + 1, offset))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT e.*
                FROM emotion_events e
                WHERE {' AND '.join(clauses)}
                  AND {self._emotion_latest_revision_clause('e', 'newer')}
                ORDER BY e.occurred_at DESC, e.event_id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        page = [self._emotion_event_row(row) for row in rows[:bounded]]
        return {
            "items": [{
                "trace_id": clean_text(item.get("trace_id"), 96),
                "event_id": clean_text(item.get("event_id"), 96),
                "revision": int(item.get("revision") or 1),
                "event_type": clean_text(item.get("event_type"), 48),
                "status": clean_text(item.get("status"), 24),
                "occurred_at": clean_text(item.get("occurred_at"), 48),
                "session_hash": self._diagnostic_hash(item.get("session_id")),
            } for item in page],
            "next_cursor": str(offset + bounded) if len(rows) > bounded else "",
            "has_more": len(rows) > bounded,
        }

    @classmethod
    def _emotion_diagnostic_projection(cls, event: dict[str, Any], deliveries: list[sqlite3.Row]) -> dict[str, Any]:
        return {
            "schema_version": "emotion_trace_diagnostic.v1",
            "event_id": clean_text(event.get("event_id"), 96),
            "trace_id": clean_text(event.get("trace_id"), 96),
            "revision": int(event.get("revision") or 1),
            "producer_plugin": clean_text(event.get("producer_plugin"), 80),
            "origin_kind": clean_text(event.get("origin_kind"), 40),
            "event_type": clean_text(event.get("event_type"), 48),
            "intensity": float(event.get("intensity") or 0.0),
            "confidence": float(event.get("confidence") or 0.0),
            "status": clean_text(event.get("status"), 24),
            "source_rule": clean_text(event.get("source_rule"), 80),
            "occurred_at": clean_text(event.get("occurred_at"), 48),
            "applied_interaction": clean_text(event.get("applied_interaction"), 32),
            "applied_energy_delta": float(event.get("applied_energy_delta") or 0.0),
            "correction_of": clean_text(event.get("correction_of"), 96),
            "actor": cls._diagnostic_ref(event.get("actor_ref")),
            "target": cls._diagnostic_ref(event.get("target_ref")),
            "quoted_target": cls._diagnostic_ref(event.get("quoted_target_ref")),
            "scope": clean_text(event.get("scope"), 24),
            "session_hash": cls._diagnostic_hash(event.get("session_id")),
            "deliveries": [{
                "consumer_id": clean_text(row["consumer_id"], 80),
                "attempts": max(0, int(row["attempts"] or 0)),
                "first_delivered_at": clean_text(row["first_delivered_at"], 48),
                "last_delivered_at": clean_text(row["last_delivered_at"], 48),
                "acked": bool(row["acked_at"]),
                "acked_at": clean_text(row["acked_at"], 48),
            } for row in deliveries],
        }

    @classmethod
    def _diagnostic_ref(cls, value: Any) -> dict[str, str]:
        source = value if isinstance(value, dict) else {}
        return {
            "kind": clean_text(source.get("kind"), 24),
            "role": clean_text(source.get("role"), 40),
            "id_hash": cls._diagnostic_hash(source.get("id")),
        }

    @staticmethod
    def _diagnostic_hash(value: Any) -> str:
        cleaned = clean_text(value, 220)
        return hashlib.sha256(cleaned.encode("utf-8", errors="ignore")).hexdigest()[:12] if cleaned else ""

    async def list_emotion_events(
        self,
        *,
        bot_id: str = "",
        session_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return await self._run_recoverable_database_operation(
            self._list_emotion_events_sync, bot_id, session_id, limit
        )

    def _list_emotion_events_sync(self, bot_id: str, session_id: str, limit: int) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if clean_text(bot_id, 160):
            clauses.append("bot_id=?")
            params.append(clean_text(bot_id, 160))
        if clean_text(session_id, 220):
            clauses.append("session_id=?")
            params.append(clean_text(session_id, 220))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(500, int(limit or 50))))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM emotion_events{where} ORDER BY occurred_at DESC, revision DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._emotion_event_row(row) for row in rows]

    async def list_emotion_event_deliveries(
        self,
        *,
        consumer_id: str,
        bot_id: str,
        scope: str,
        platform: str,
        user_id: str,
        session_id: str,
        allow_cross_window: bool = False,
        cursor: str = "",
        limit: int = 10,
    ) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(
            self._list_emotion_event_deliveries_sync,
            consumer_id,
            bot_id,
            scope,
            platform,
            user_id,
            session_id,
            allow_cross_window,
            cursor,
            limit,
        )

    def _list_emotion_event_deliveries_sync(
        self,
        consumer_id: str,
        bot_id: str,
        scope: str,
        platform: str,
        user_id: str,
        session_id: str,
        allow_cross_window: bool,
        cursor: str,
        limit: int,
    ) -> dict[str, Any]:
        domain = self._emotion_delivery_domain(
            consumer_id=consumer_id,
            bot_id=bot_id,
            scope=scope,
            platform=platform,
            user_id=user_id,
            session_id=session_id,
            allow_cross_window=allow_cross_window,
        )
        if domain is None:
            return self._empty_emotion_delivery("delivery_domain_required")
        try:
            bounded_limit = max(1, min(20, int(limit or 10)))
        except (TypeError, ValueError):
            bounded_limit = 10
        cursor_value = clean_text(cursor, 400)
        cursor_position = self._parse_emotion_delivery_cursor(cursor_value)
        if cursor_value and cursor_position is None:
            return self._empty_emotion_delivery()
        delivery_consumer_id = self._emotion_delivery_consumer_key(
            domain["consumer_id"], domain
        )
        clauses = [
            "e.origin_kind='memory_recall'",
            "e.status NOT IN ('ignored','expired')",
            "COALESCE(d.acked_at, '')=''",
            "e.bot_id=?",
            "LOWER(e.scope)=?",
            "e.platform=?",
            "json_valid(e.actor_ref)",
            "json_extract(e.actor_ref, '$.kind')='user'",
            "CAST(json_extract(e.actor_ref, '$.id') AS TEXT)=?",
            "json_valid(e.target_ref)",
            "json_extract(e.target_ref, '$.kind')='bot'",
            "CAST(json_extract(e.target_ref, '$.id') AS TEXT)=?",
            """(
                e.expires_at=''
                OR (
                    (instr(e.expires_at, 'Z') > 0 OR substr(e.expires_at, -6, 1) IN ('+', '-'))
                    AND julianday(e.expires_at) IS NOT NULL
                    AND julianday(e.expires_at) > julianday('now')
                )
            )""",
        ]
        params: list[Any] = [
            delivery_consumer_id,
            domain["bot_id"],
            domain["scope"],
            domain["platform"],
            domain["user_id"],
            domain["bot_id"],
        ]
        if not domain["allow_cross_window"]:
            clauses.append("e.session_id=?")
            params.append(domain["session_id"])
        if cursor_position is not None:
            occurred_at, event_id, revision = cursor_position
            clauses.append(
                """(
                    e.occurred_at < ?
                    OR (e.occurred_at=? AND e.event_id < ?)
                    OR (e.occurred_at=? AND e.event_id=? AND e.revision < ?)
                )"""
            )
            params.extend((
                occurred_at,
                occurred_at,
                event_id,
                occurred_at,
                event_id,
                revision,
            ))
        params.append(bounded_limit + 1)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT e.*
                FROM emotion_events e
                LEFT JOIN emotion_event_deliveries d
                  ON d.event_id=e.event_id AND d.revision=e.revision AND d.consumer_id=?
                WHERE {' AND '.join(clauses)}
                  AND {self._emotion_latest_revision_clause('e', 'newer')}
                ORDER BY e.occurred_at DESC, e.event_id DESC, e.revision DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            events = [
                event
                for event in (self._emotion_event_row(row) for row in rows)
                if (
                    self._emotion_event_in_delivery_domain(event, domain)
                    and not self._emotion_event_is_expired(event)
                )
            ]
            page = events[:bounded_limit]
            has_more = len(events) > bounded_limit
            delivered_at = utc_now()
            for event in page:
                self._conn.execute(
                    """
                    INSERT INTO emotion_event_deliveries(
                        event_id, revision, consumer_id, attempts,
                        first_delivered_at, last_delivered_at, acked_at
                    ) VALUES(?,?,?,1,?,?,'')
                    ON CONFLICT(event_id, revision, consumer_id) DO UPDATE SET
                        attempts=emotion_event_deliveries.attempts+1,
                        last_delivered_at=excluded.last_delivered_at
                    """,
                    (
                        event["event_id"],
                        event["revision"],
                        delivery_consumer_id,
                        delivered_at,
                        delivered_at,
                    ),
                )
            self._conn.commit()
        projection = [self._emotion_delivery_projection(event) for event in page]
        return {
            "schema_version": "emotion_afterglow_delivery.v1",
            "events": projection,
            "next_cursor": self._emotion_delivery_cursor(page[-1]) if page and has_more else "",
            "has_more": has_more,
        }

    async def ack_emotion_event_deliveries(
        self,
        *,
        consumer_id: str,
        event_refs: list[dict[str, Any]],
        bot_id: str,
        scope: str,
        platform: str,
        user_id: str,
        session_id: str,
        allow_cross_window: bool = False,
    ) -> dict[str, Any]:
        return await self._run_recoverable_database_operation(
            self._ack_emotion_event_deliveries_sync,
            consumer_id,
            event_refs,
            bot_id,
            scope,
            platform,
            user_id,
            session_id,
            allow_cross_window,
        )

    def _ack_emotion_event_deliveries_sync(
        self,
        consumer_id: str,
        event_refs: list[dict[str, Any]],
        bot_id: str,
        scope: str,
        platform: str,
        user_id: str,
        session_id: str,
        allow_cross_window: bool,
    ) -> dict[str, Any]:
        domain = self._emotion_delivery_domain(
            consumer_id=consumer_id,
            bot_id=bot_id,
            scope=scope,
            platform=platform,
            user_id=user_id,
            session_id=session_id,
            allow_cross_window=allow_cross_window,
        )
        if domain is None or not isinstance(event_refs, list):
            return {"acked": 0, "consumer_id": clean_text(consumer_id, 80), "error_code": "delivery_domain_required"}
        unique_refs: set[tuple[str, int]] = set()
        for item in event_refs[:100]:
            if not isinstance(item, dict):
                continue
            event_id = clean_text(item.get("event_id"), 96)
            try:
                revision = max(1, min(1000000, int(item.get("revision") or 1)))
            except (TypeError, ValueError):
                continue
            if event_id:
                unique_refs.add((event_id, revision))
        acked_at = utc_now()
        acked = 0
        delivery_consumer_id = self._emotion_delivery_consumer_key(
            domain["consumer_id"], domain
        )
        with self._lock:
            for event_id, revision in unique_refs:
                row = self._conn.execute(
                    "SELECT * FROM emotion_events WHERE event_id=? AND revision=?",
                    (event_id, revision),
                ).fetchone()
                if row is None:
                    continue
                event = self._emotion_event_row(row)
                if (
                    not self._emotion_event_in_delivery_domain(event, domain)
                    or self._emotion_event_is_expired(event)
                ):
                    continue
                result = self._conn.execute(
                    """
                    UPDATE emotion_event_deliveries
                    SET acked_at=?
                    WHERE event_id=? AND revision=? AND consumer_id=? AND acked_at=''
                    """,
                    (acked_at, event_id, revision, delivery_consumer_id),
                )
                acked += max(0, int(result.rowcount or 0))
            self._conn.commit()
        return {"acked": acked, "consumer_id": domain["consumer_id"], "acked_at": acked_at}

    @staticmethod
    def _empty_emotion_delivery(error_code: str = "") -> dict[str, Any]:
        result = {
            "schema_version": "emotion_afterglow_delivery.v1",
            "events": [],
            "next_cursor": "",
            "has_more": False,
        }
        if error_code:
            result["error_code"] = error_code
        return result

    @staticmethod
    def _emotion_delivery_domain(
        *,
        consumer_id: Any,
        bot_id: Any,
        scope: Any,
        platform: Any,
        user_id: Any,
        session_id: Any,
        allow_cross_window: Any,
    ) -> dict[str, Any] | None:
        domain = {
            "consumer_id": clean_text(consumer_id, 80),
            "bot_id": clean_text(bot_id, 160),
            "scope": clean_text(scope, 24).lower(),
            "platform": clean_text(platform, 80),
            "user_id": clean_text(user_id, 160),
            "session_id": clean_text(session_id, 220),
            "allow_cross_window": allow_cross_window,
        }
        if (
            not all(domain[key] for key in ("consumer_id", "bot_id", "platform", "user_id", "session_id"))
            or domain["scope"] != "private"
            or type(domain["allow_cross_window"]) is not bool
        ):
            return None
        return domain

    @staticmethod
    def _emotion_event_in_delivery_domain(event: dict[str, Any], domain: dict[str, Any]) -> bool:
        actor = event.get("actor_ref") if isinstance(event.get("actor_ref"), dict) else {}
        target = event.get("target_ref") if isinstance(event.get("target_ref"), dict) else {}
        return (
            clean_text(event.get("origin_kind"), 40) == "memory_recall"
            and clean_text(event.get("bot_id"), 160) == domain["bot_id"]
            and clean_text(event.get("scope"), 24).lower() == domain["scope"]
            and clean_text(event.get("platform"), 80) == domain["platform"]
            and clean_text(actor.get("kind"), 24) == "user"
            and clean_text(actor.get("id"), 160) == domain["user_id"]
            and clean_text(target.get("kind"), 24) == "bot"
            and clean_text(target.get("id"), 160) == domain["bot_id"]
            and (
                domain["allow_cross_window"]
                or clean_text(event.get("session_id"), 220) == domain["session_id"]
            )
        )

    @staticmethod
    def _emotion_event_identity_domain(event: dict[str, Any]) -> tuple[str, ...]:
        actor = event.get("actor_ref") if isinstance(event.get("actor_ref"), dict) else {}
        target = event.get("target_ref") if isinstance(event.get("target_ref"), dict) else {}
        return (
            clean_text(event.get("producer_plugin"), 80),
            clean_text(event.get("origin_kind"), 40),
            clean_text(event.get("platform"), 80),
            clean_text(event.get("bot_id"), 160),
            clean_text(event.get("scope"), 24).lower(),
            clean_text(event.get("session_id"), 220),
            clean_text(actor.get("kind"), 24),
            clean_text(actor.get("id"), 160),
            clean_text(target.get("kind"), 24),
            clean_text(target.get("id"), 160),
        )

    @staticmethod
    def _emotion_delivery_consumer_key(consumer_id: str, domain: dict[str, Any]) -> str:
        """Namespace delivery state so legacy duplicate event IDs cannot share acks."""

        identity = json_dumps({
            "consumer_id": clean_text(consumer_id, 80),
            "bot_id": clean_text(domain.get("bot_id"), 160),
            "scope": clean_text(domain.get("scope"), 24).lower(),
            "platform": clean_text(domain.get("platform"), 80),
            "user_id": clean_text(domain.get("user_id"), 160),
            "session_id": clean_text(domain.get("session_id"), 220),
        })
        return f"{clean_text(consumer_id, 80)}@{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _emotion_latest_revision_clause(event_alias: str, newer_alias: str) -> str:
        def ref_value(alias: str, column: str, key: str) -> str:
            return (
                f"COALESCE(CASE WHEN json_valid({alias}.{column}) "
                f"THEN CAST(json_extract({alias}.{column}, '$.{key}') AS TEXT) END, '')"
            )

        return f"""NOT EXISTS (
            SELECT 1
            FROM emotion_events {newer_alias}
            WHERE {newer_alias}.event_id={event_alias}.event_id
              AND {newer_alias}.producer_plugin={event_alias}.producer_plugin
              AND {newer_alias}.origin_kind={event_alias}.origin_kind
              AND {newer_alias}.platform={event_alias}.platform
              AND {newer_alias}.bot_id={event_alias}.bot_id
              AND LOWER({newer_alias}.scope)=LOWER({event_alias}.scope)
              AND {newer_alias}.session_id={event_alias}.session_id
              AND {ref_value(newer_alias, 'actor_ref', 'kind')}={ref_value(event_alias, 'actor_ref', 'kind')}
              AND {ref_value(newer_alias, 'actor_ref', 'id')}={ref_value(event_alias, 'actor_ref', 'id')}
              AND {ref_value(newer_alias, 'target_ref', 'kind')}={ref_value(event_alias, 'target_ref', 'kind')}
              AND {ref_value(newer_alias, 'target_ref', 'id')}={ref_value(event_alias, 'target_ref', 'id')}
              AND {newer_alias}.revision>{event_alias}.revision
        )"""

    @staticmethod
    def _emotion_event_is_expired(event: dict[str, Any], *, now: datetime | None = None) -> bool:
        expires_at = clean_text(event.get("expires_at"), 48)
        if not expires_at:
            return False
        try:
            parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return True
            return parsed.astimezone(timezone.utc) <= (now or datetime.now(timezone.utc))
        except (TypeError, ValueError, OverflowError):
            return True

    @staticmethod
    def _emotion_delivery_cursor(event: dict[str, Any]) -> str:
        return json_dumps({
            "occurred_at": clean_text(event.get("occurred_at"), 48),
            "event_id": clean_text(event.get("event_id"), 96),
            "revision": max(1, int(event.get("revision") or 1)),
        })

    @staticmethod
    def _parse_emotion_delivery_cursor(value: Any) -> tuple[str, str, int] | None:
        cursor = clean_text(value, 400)
        if not cursor:
            return None
        payload = json_loads(cursor, {})
        if isinstance(payload, dict):
            occurred_at = clean_text(payload.get("occurred_at"), 48)
            event_id = clean_text(payload.get("event_id"), 96)
            revision = payload.get("revision")
            try:
                normalized_revision = max(1, min(1_000_000, int(revision)))
            except (TypeError, ValueError):
                normalized_revision = 0
            if occurred_at and event_id and normalized_revision:
                return occurred_at, event_id, normalized_revision
        legacy = cursor.rsplit("|", 2)
        if len(legacy) != 3:
            return None
        occurred_at = clean_text(legacy[0], 48)
        event_id = clean_text(legacy[1], 96)
        try:
            revision = max(1, min(1_000_000, int(legacy[2])))
        except (TypeError, ValueError):
            return None
        return (occurred_at, event_id, revision) if occurred_at and event_id else None

    @staticmethod
    def _emotion_delivery_projection(event: dict[str, Any]) -> dict[str, Any]:
        from .affect_modulation import normalize_affect_modulation

        projection = {
            "event_id": clean_text(event.get("event_id"), 96),
            "revision": max(1, int(event.get("revision") or 1)),
            "trace_id": clean_text(event.get("trace_id"), 96),
            "event_type": clean_text(event.get("event_type"), 48),
            "intensity": float(event.get("intensity") or 0.0),
            "confidence": float(event.get("confidence") or 0.0),
            "energy_delta": float(event.get("applied_energy_delta") or 0.0),
            "valence": float(event.get("valence_hint") or 0.0),
            "arousal": float(event.get("arousal_hint") or 0.0),
            "vulnerability": float(event.get("vulnerability_hint") or 0.0),
            "occurred_at": clean_text(event.get("occurred_at"), 48),
            "expires_at": clean_text(event.get("expires_at"), 48),
        }
        projection["affect_modulation"] = normalize_affect_modulation({
            "valence": projection["valence"],
            "arousal": projection["arousal"],
            "vulnerability": projection["vulnerability"],
            "confidence": projection["confidence"],
            "source_event_ids": [projection["event_id"]],
        })
        return projection

    @staticmethod
    def _emotion_event_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in ("actor_ref", "target_ref", "quoted_target_ref"):
            result[key] = json_loads(result.get(key), {})
        result["reason_codes"] = json_loads(result.get("reason_codes"), [])
        result.pop("created_at", None)
        result["schema_version"] = "companion_emotion_event.v1"
        return result
