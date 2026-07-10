from __future__ import annotations

import asyncio
from contextlib import closing, contextmanager
from copy import deepcopy
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .models import EntityRef, MemoryRecord, clean_text, json_dumps, json_loads, new_id, stable_fingerprint, utc_now


class MemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._closed = False
        self._fts_enabled = False
        self._savepoint_counter = 0
        self._embedding_candidate_cache_revision = ""
        self._embedding_candidate_cache: dict[
            tuple[str, bool, int],
            list[tuple[MemoryRecord, list[float], str]],
        ] = {}

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
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(
                """
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
                    summarized_at TEXT NOT NULL DEFAULT ''
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
                """
            )
            self._ensure_memory_columns_sync()
            self._ensure_timeline_columns_sync()
            self._ensure_acl_columns_sync()
            self._ensure_memory_fts_sync()
            self._ensure_retrieval_revision_sync()
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_fingerprint ON memories(content_fingerprint)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_summary ON timeline(session_id, summarized_at, occurred_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_retention ON timeline(occurred_at, created_at) WHERE summarized_at!=''"
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
            self._conn.commit()

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
            CREATE TRIGGER IF NOT EXISTS trg_memories_retrieval_revision_update
            AFTER UPDATE OF
                memory_type, subject_kind, subject_id, subject_name, subject_role,
                object_kind, object_id, object_name, object_role, scope, session_id,
                platform, message_id, group_id, visibility, sayability, reality_level,
                lifecycle, content, evidence, confidence, importance, review_status,
                tags, metadata, created_at, updated_at, occurred_at, source_plugin,
                import_batch_id, content_fingerprint, merged_count, supersedes_id
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
            memory_count = int(self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] or 0)
            fts_count = int(self._conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] or 0)
            if memory_count != fts_count:
                self._rebuild_memory_fts_sync()
        except sqlite3.Error:
            self._fts_enabled = False

    def _rebuild_memory_fts_sync(self) -> int:
        if not self._fts_enabled:
            return 0
        self._conn.execute("DELETE FROM memory_fts")
        rows = self._conn.execute("SELECT * FROM memories").fetchall()
        count = 0
        for row in rows:
            self._upsert_memory_fts_row(row)
            count += 1
        return count

    def _upsert_memory_fts_row(self, row: sqlite3.Row | None) -> None:
        if not self._fts_enabled or row is None:
            return
        memory_id = clean_text(row["id"], 120)
        if not memory_id:
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
        additions = {
            "content_fingerprint": "TEXT NOT NULL DEFAULT ''",
            "merged_count": "INTEGER NOT NULL DEFAULT 1",
            "supersedes_id": "TEXT NOT NULL DEFAULT ''",
        }
        for name, ddl in additions.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")

    def _ensure_timeline_columns_sync(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(timeline)").fetchall()
        }
        additions = {
            "summarized_at": "TEXT NOT NULL DEFAULT ''",
            "message_id": "TEXT NOT NULL DEFAULT ''",
            "dedupe_key": "TEXT NOT NULL DEFAULT ''",
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

    def normalize_legacy_manual_visibility(self) -> int:
        """收回早期版本中过宽的手动记忆默认可见性。"""
        with self._lock:
            with self._transaction_sync():
                return self._normalize_legacy_manual_visibility_sync()

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

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.commit()
            self._conn.close()
            self._closed = True

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
            "review_queue",
            "injection_logs",
            "summary_failures",
            "relationship_edges",
            "knowledge_nodes",
            "knowledge_edges",
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

    async def insert_memory(self, record: MemoryRecord, review_reason: str = "") -> str:
        return await asyncio.to_thread(self._insert_memory_sync, record, review_reason)

    def _insert_memory_sync(self, record: MemoryRecord, review_reason: str = "") -> str:
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

    def _upsert_identity_sync(
        self,
        platform: str,
        entity: EntityRef,
        aliases: list[str],
        profile: dict[str, Any],
        confidence: float,
    ) -> str:
        now = utc_now()
        entity_id = clean_text(entity.id, 120)
        if not entity_id:
            entity_id = "unknown"
        row_id = f"{platform or 'unknown'}:{entity.kind}:{entity_id}"
        aliases = [clean_text(alias, 80) for alias in aliases if clean_text(alias, 80)]
        if entity.name and entity.name not in aliases:
            aliases.append(entity.name)
        with self._lock:
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
            self._conn.commit()
        return row_id

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
        return await asyncio.to_thread(
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
    ) -> str:
        now = utc_now()
        row_id = new_id("rel")
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
            self._conn.commit()
        return row_id

    async def list_relationships(
        self,
        limit: int = 20,
        entity_id: str = "",
        scope: str = "",
        session_id: str = "",
        group_id: str = "",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_relationships_sync,
            limit,
            entity_id,
            scope,
            session_id,
            group_id,
        )

    def _list_relationships_sync(
        self,
        limit: int,
        entity_id: str,
        scope: str,
        session_id: str,
        group_id: str,
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
                LIMIT ?
                """,
                params + [max(1, int(limit))],
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
        label = clean_text(label, 160)
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
            where += " AND (s.label LIKE ? OR t.label LIKE ?)"
            like = f"%{node}%"
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
        like_sql = " OR ".join(["lower(n.label) LIKE ?" for _ in cleaned_terms])
        like_params = [f"%{term}%" for term in cleaned_terms]
        with self._lock:
            matched = self._conn.execute(
                f"""
                SELECT n.id, n.label
                FROM knowledge_nodes n
                WHERE ({like_sql}) {scope_filter}
                ORDER BY n.updated_at DESC
                LIMIT ?
                """,
                like_params + params + [max(1, int(limit))],
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
                        occurred_at, created_at, summarized_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?, '')
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

    async def recent_timeline(
        self,
        limit: int = 10,
        scope: str = "",
        session_id: str = "",
        entity_id: str = "",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._recent_timeline_sync, limit, scope, session_id, entity_id)

    def _recent_timeline_sync(
        self,
        limit: int,
        scope: str,
        session_id: str,
        entity_id: str,
    ) -> list[dict[str, Any]]:
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
                LIMIT ?
                """,
                params + [max(1, int(limit))],
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

    async def unsummarized_timeline_window(
        self,
        *,
        session_id: str,
        scope: str = "",
        limit: int = 40,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._unsummarized_timeline_window_sync, session_id, scope, limit)

    def _unsummarized_timeline_window_sync(self, session_id: str, scope: str, limit: int) -> dict[str, Any]:
        params: list[Any] = [clean_text(session_id, 200)]
        where = "session_id=? AND summarized_at=''"
        if scope:
            where += " AND scope=?"
            params.append(clean_text(scope, 40))
        with self._lock:
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

    def _mark_timeline_summarized_sync(self, event_ids: list[str]) -> int:
        ids = [clean_text(event_id, 120) for event_id in event_ids if clean_text(event_id, 120)]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE timeline SET summarized_at=? WHERE id IN ({placeholders})",
                [utc_now()] + ids,
            )
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
                    clean_text(error, 1000),
                    json_dumps(metadata),
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

    def _mark_summary_failure_dead_letter_sync(self, session_id: str, max_retries: int) -> bool:
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
                metadata.update(
                    {
                        "state": "dead_letter",
                        "max_retries": max(1, int(max_retries or 1)),
                        "dead_letter_at": utc_now(),
                    }
                )
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
                    clean_text(query, 1000),
                    json_dumps(selected_memory_ids),
                    json_dumps(blocked_reasons[:30]),
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
        return await asyncio.to_thread(self._list_candidate_memories_sync, limit, include_pending)

    def _list_candidate_memories_sync(self, limit: int, include_pending: bool) -> list[MemoryRecord]:
        where = "lifecycle != 'archived'"
        params: list[Any] = []
        if not include_pending:
            where += " AND review_status != 'pending'"
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM memories
                WHERE {where}
                ORDER BY importance DESC, occurred_at DESC
                LIMIT ?
                """,
                params + [max(1, int(limit))],
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

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
        return await asyncio.to_thread(
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
        where = "lifecycle != 'archived' AND (" + " OR ".join(clauses) + ")"
        if not include_pending:
            where += " AND review_status != 'pending'"
        with self._lock:
            rows = self._conn.execute(
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
        return [MemoryRecord.from_row(row) for row in rows]

    async def list_time_window_candidate_memories(
        self,
        start_at: str,
        end_at: str,
        limit: int = 1200,
        include_pending: bool = False,
    ) -> list[MemoryRecord]:
        return await asyncio.to_thread(
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
        start = clean_text(start_at, 80)
        end = clean_text(end_at, 80)
        if not start or not end:
            return []
        where = "lifecycle != 'archived'"
        params: list[Any] = [start, end, start, end, start, end]
        if not include_pending:
            where += " AND review_status != 'pending'"
        with self._lock:
            rows = self._conn.execute(
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
        return [MemoryRecord.from_row(row) for row in rows]

    async def list_fts_candidate_memories(
        self,
        terms: list[str],
        limit: int = 800,
        include_pending: bool = False,
    ) -> list[MemoryRecord]:
        return await asyncio.to_thread(
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
        if not self._fts_enabled:
            return []
        query = self._fts_match_query(terms)
        if not query:
            return []
        where = "m.lifecycle != 'archived'"
        params: list[Any] = [query]
        if not include_pending:
            where += " AND m.review_status != 'pending'"
        try:
            with self._lock:
                rows = self._conn.execute(
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
        return [MemoryRecord.from_row(row) for row in rows]

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
        return await asyncio.to_thread(
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
        cleaned_terms = []
        for term in terms or []:
            text = clean_text(term, 80).lower()
            if text and text not in cleaned_terms:
                cleaned_terms.append(text)
            if len(cleaned_terms) >= 24:
                break
        if not cleaned_terms:
            return []

        where = "lifecycle != 'archived'"
        params: list[Any] = []
        if not include_pending:
            where += " AND review_status != 'pending'"

        columns = [
            "content",
            "evidence",
            "tags",
            "metadata",
            "subject_id",
            "subject_name",
            "object_id",
            "object_name",
            "session_id",
            "group_id",
        ]
        term_clauses: list[str] = []
        for term in cleaned_terms:
            like = self._like_pattern(term)
            term_clauses.append(
                "(" + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in columns) + ")"
            )
            params.extend([like] * len(columns))
        where += " AND (" + " OR ".join(term_clauses) + ")"

        with self._lock:
            rows = self._conn.execute(
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
        return [MemoryRecord.from_row(row) for row in rows]

    @staticmethod
    def _like_pattern(term: str) -> str:
        escaped = clean_text(term, 120).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    async def recent_memories(self, limit: int = 10, include_pending: bool = True) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._recent_memories_sync, limit, include_pending)

    def _recent_memories_sync(self, limit: int, include_pending: bool) -> list[MemoryRecord]:
        where = "1=1"
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
    ) -> list[MemoryRecord]:
        return await asyncio.to_thread(
            self._list_memories_sync,
            limit,
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
        )

    def _list_memories_sync(
        self,
        limit: int,
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
    ) -> list[MemoryRecord]:
        params: list[Any] = []
        where = "1=1"
        if not include_pending:
            where += " AND review_status != 'pending'"
        if query:
            like = f"%{clean_text(query, 500)}%"
            where += (
                " AND (id LIKE ? OR content LIKE ? OR evidence LIKE ? OR subject_id LIKE ?"
                " OR subject_name LIKE ? OR object_id LIKE ? OR object_name LIKE ?"
                " OR session_id LIKE ? OR group_id LIKE ?)"
            )
            params.extend([like] * 9)
        if memory_type:
            where += " AND memory_type=?"
            params.append(clean_text(memory_type, 80))
        if scope:
            where += " AND scope=?"
            params.append(clean_text(scope, 40))
        if visibility:
            where += " AND visibility=?"
            params.append(clean_text(visibility, 40))
        if review_status:
            where += " AND review_status=?"
            params.append(clean_text(review_status, 40))
        if lifecycle:
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
            where += " AND (subject_id=? OR object_id=? OR group_id=? OR session_id LIKE ?)"
            params.extend([entity, entity, entity, f"%{entity}%"])
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM memories
                WHERE {where}
                ORDER BY occurred_at DESC, created_at DESC
                LIMIT ?
                """,
                params + [max(1, int(limit))],
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

    async def list_memory_buckets(self, limit: int = 160) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_memory_buckets_sync, limit)

    def _list_memory_buckets_sync(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    scope,
                    target_id,
                    target_name,
                    sample_session_id,
                    sample_group_id,
                    COUNT(*) AS memory_count,
                    SUM(CASE WHEN lifecycle='archived' THEN 1 ELSE 0 END) AS archived_count,
                    MAX(occurred_at) AS latest_at
                FROM (
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
                        review_status,
                        lifecycle,
                        occurred_at
                    FROM memories
                    WHERE scope IN ('private', 'group')
                      AND review_status!='pending'
                )
                WHERE target_id!=''
                GROUP BY scope, target_id
                ORDER BY scope ASC, latest_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            buckets = [dict(row) for row in rows]
            for bucket in buckets:
                bucket["target_name"] = self._resolve_bucket_target_name_sync(
                    clean_text(bucket.get("scope"), 40),
                    clean_text(bucket.get("target_id"), 160),
                    clean_text(bucket.get("target_name"), 120),
                )
        return buckets

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
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._upsert_acl_policy_sync,
            window_scope,
            window_id,
            read_mode,
            share_mode,
        )

    def _upsert_acl_policy_sync(
        self,
        window_scope: str,
        window_id: str,
        read_mode: str,
        share_mode: str,
    ) -> dict[str, Any]:
        window_scope = clean_text(window_scope, 40)
        window_id = clean_text(window_id, 160)
        current = self._get_acl_policy_sync(window_scope, window_id)
        read_mode = self._normalize_acl_mode(read_mode or current.get("read_mode"))
        share_mode = self._normalize_acl_mode(share_mode or current.get("share_mode"))
        now = utc_now()
        data = {
            "id": current.get("id") or new_id("acl_policy"),
            "window_scope": window_scope,
            "window_id": window_id,
            "read_mode": read_mode,
            "share_mode": share_mode,
            "created_at": current.get("created_at") or now,
            "updated_at": now,
        }
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_acl_policies(
                    id, window_scope, window_id, read_mode, share_mode, created_at, updated_at
                )
                VALUES(:id, :window_scope, :window_id, :read_mode, :share_mode, :created_at, :updated_at)
                ON CONFLICT(window_scope, window_id) DO UPDATE SET
                    read_mode=excluded.read_mode,
                    share_mode=excluded.share_mode,
                    updated_at=excluded.updated_at
                """,
                data,
            )
            row = self._conn.execute(
                "SELECT * FROM memory_acl_policies WHERE window_scope=? AND window_id=?",
                (window_scope, window_id),
            ).fetchone()
            self._conn.commit()
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
            "created_at": "",
            "updated_at": "",
        }

    @classmethod
    def _acl_policy_from_row(cls, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["read_mode"] = cls._normalize_acl_mode(item.get("read_mode"))
        item["share_mode"] = cls._normalize_acl_mode(item.get("share_mode"))
        return item

    @staticmethod
    def _normalize_acl_effect(effect: Any) -> str:
        return "deny" if clean_text(effect, 20).lower() in {"deny", "block", "blacklist"} else "allow"

    @staticmethod
    def _normalize_acl_mode(mode: Any) -> str:
        return "blacklist" if clean_text(mode, 20).lower() in {"blacklist", "deny", "block"} else "whitelist"

    async def get_memory(self, memory_id: str) -> MemoryRecord | None:
        return await asyncio.to_thread(self._get_memory_sync, memory_id)

    def _get_memory_sync(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return MemoryRecord.from_row(row) if row else None

    async def get_memories_by_ids(self, memory_ids: list[str]) -> dict[str, MemoryRecord]:
        return await asyncio.to_thread(self._get_memories_by_ids_sync, memory_ids)

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

    async def update_memory_payload(
        self,
        memory_id: str,
        *,
        memory_type: str | None = None,
        content: str | None = None,
        evidence: str | None = None,
        importance: Any | None = None,
        confidence: Any | None = None,
    ) -> bool:
        return await asyncio.to_thread(
            self._update_memory_payload_sync,
            memory_id,
            memory_type,
            content,
            evidence,
            importance,
            confidence,
        )

    def _update_memory_payload_sync(
        self,
        memory_id: str,
        memory_type: str | None,
        content: str | None,
        evidence: str | None,
        importance: Any | None,
        confidence: Any | None,
    ) -> bool:
        memory_id = clean_text(memory_id, 120)
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                return False
            next_type = clean_text(memory_type if memory_type is not None else row["memory_type"], 80) or row["memory_type"]
            next_content = clean_text(content if content is not None else row["content"], 4000)
            next_evidence = clean_text(evidence if evidence is not None else row["evidence"], 4000)
            try:
                next_importance = max(0.0, min(1.0, float(importance if importance is not None else row["importance"])))
            except Exception:
                next_importance = float(row["importance"] or 0.3)
            try:
                next_confidence = max(0.0, min(1.0, float(confidence if confidence is not None else row["confidence"])))
            except Exception:
                next_confidence = float(row["confidence"] or 0.5)
            fingerprint = stable_fingerprint(
                next_type,
                row["scope"],
                row["session_id"],
                row["group_id"],
                row["subject_kind"],
                row["subject_id"],
                row["object_kind"],
                row["object_id"],
                row["visibility"],
                row["reality_level"],
                next_content,
            )
            cur = self._conn.execute(
                """
                UPDATE memories
                SET memory_type=?,
                    content=?,
                    evidence=?,
                    importance=?,
                    confidence=?,
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
                    fingerprint,
                    utc_now(),
                    memory_id,
                ),
            )
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            self._upsert_memory_fts_row(row)
            self._conn.commit()
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
        evidence = clean_text(evidence, 500)
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
        now = utc_now()
        status = "auto" if status in {"approve", "approved", "auto"} else "rejected"
        lifecycle = "archived" if status == "rejected" else "stable_memory"
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET review_status=?, lifecycle=?, updated_at=? WHERE id=?",
                (status, lifecycle, now, memory_id),
            )
            self._conn.execute(
                "UPDATE review_queue SET status=?, updated_at=? WHERE memory_id=?",
                (status, now, memory_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

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
                    clean_text(payload.get("content"), 4000),
                    clean_text(payload.get("evidence"), 4000),
                    json_dumps(payload.get("metadata") or {}),
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
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET visibility=?, updated_at=? WHERE id=?",
                (clean_text(visibility, 40), utc_now(), clean_text(memory_id, 120)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    async def update_memory_lifecycle(self, memory_id: str, lifecycle: str) -> bool:
        return await asyncio.to_thread(self._update_memory_lifecycle_sync, memory_id, lifecycle)

    def _update_memory_lifecycle_sync(self, memory_id: str, lifecycle: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET lifecycle=?, updated_at=? WHERE id=?",
                (clean_text(lifecycle, 40), utc_now(), clean_text(memory_id, 120)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    async def maintenance_repair(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._maintenance_repair_sync)

    def _maintenance_repair_sync(self) -> dict[str, Any]:
        with self._lock:
            with self._transaction_sync():
                manual_fixed = self._normalize_legacy_manual_visibility_sync()
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
                            SET lifecycle='archived', supersedes_id=?, updated_at=?
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
                fts_rebuilt = self._rebuild_memory_fts_sync() if self._fts_enabled else 0
        return {
            "manual_visibility_fixed": manual_fixed,
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
        await asyncio.to_thread(
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
                    json_dumps(values),
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
        return await asyncio.to_thread(
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
        where = "m.lifecycle != 'archived' AND e.provider_id=?"
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
            payload = json_loads(row["embedding_vector"], [])
            if not isinstance(payload, list):
                continue
            vector: list[float] = []
            for item in payload:
                try:
                    vector.append(float(item))
                except Exception:
                    vector = []
                    break
            if not vector:
                continue
            result.append((MemoryRecord.from_row(row), vector, clean_text(row["embedding_text_hash"], 80)))
        with self._lock:
            self._embedding_candidate_cache[cache_key] = result
        return deepcopy(result)

    async def list_memories_missing_embeddings(
        self,
        *,
        provider_id: str,
        limit: int = 80,
        include_pending: bool = False,
    ) -> list[MemoryRecord]:
        return await asyncio.to_thread(
            self._list_memories_missing_embeddings_sync,
            provider_id,
            limit,
            include_pending,
        )

    def _list_memories_missing_embeddings_sync(
        self,
        provider_id: str,
        limit: int,
        include_pending: bool,
    ) -> list[MemoryRecord]:
        provider_id = clean_text(provider_id, 160)
        if not provider_id:
            return []
        where = "m.lifecycle != 'archived'"
        params: list[Any] = [provider_id]
        if not include_pending:
            where += " AND m.review_status != 'pending'"
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT m.*
                FROM memories m
                LEFT JOIN memory_embeddings e
                  ON e.memory_id=m.id AND e.provider_id=?
                WHERE {where}
                  AND (e.memory_id IS NULL OR e.text_hash='')
                ORDER BY m.importance DESC, COALESCE(NULLIF(m.occurred_at, ''), m.created_at) DESC
                LIMIT ?
                """,
                params + [max(1, int(limit or 1))],
            ).fetchall()
        return [MemoryRecord.from_row(row) for row in rows]

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

    async def stats(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._stats_sync)

    async def memory_revision(self) -> str:
        return await asyncio.to_thread(self._memory_revision_sync)

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
        return {
            "db_path": str(self.db_path),
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
