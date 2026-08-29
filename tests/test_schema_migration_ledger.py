from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.store import MemoryStore


LEGACY_MEMORIES_DDL = """
CREATE TABLE memories (
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
)
"""


def _schema_digest(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """SELECT type,name,tbl_name,sql FROM sqlite_master
           WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
           ORDER BY type,name,tbl_name"""
    ).fetchall()
    encoded = repr([tuple(row) for row in rows]).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SchemaMigrationLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "memory.db"

    def _create_legacy_database(self) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(LEGACY_MEMORIES_DDL)
            connection.execute(
                "INSERT INTO memories(id,memory_type,content) VALUES('legacy','stable_fact','legacy row')"
            )
            connection.commit()
        finally:
            connection.close()

    def test_fresh_and_current_database_have_one_monotonic_ledger_entry(self) -> None:
        store = MemoryStore(self.path)
        self.addCleanup(store.close)
        store.initialize()

        self.assertEqual("", store.last_schema_backup_path)
        self.assertEqual([], list(self.path.parent.glob("*.before-*.db")))
        ledger = store._conn.execute(
            """SELECT from_revision,to_revision,state,backup_path,
                      schema_fingerprint,applied_at
               FROM schema_migration_ledger"""
        ).fetchall()
        self.assertEqual(1, len(ledger))
        self.assertEqual(0, ledger[0]["from_revision"])
        self.assertEqual(MemoryStore.SCHEMA_MIGRATION_REVISION, ledger[0]["to_revision"])
        self.assertEqual("applied", ledger[0]["state"])
        self.assertEqual("", ledger[0]["backup_path"])
        self.assertEqual(store._schema_fingerprint_sync(), ledger[0]["schema_fingerprint"])
        self.assertTrue(ledger[0]["applied_at"])
        self.assertEqual(
            str(MemoryStore.SCHEMA_MIGRATION_REVISION),
            store._conn.execute(
                "SELECT value FROM schema_metadata WHERE key='migration_revision'"
            ).fetchone()[0],
        )

        trigger_names = {
            row["name"]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        self.assertIn("trg_memories_retrieval_revision_insert", trigger_names)
        before_revision = store._conn.execute(
            "SELECT revision FROM retrieval_revision WHERE singleton=1"
        ).fetchone()[0]
        store._conn.execute(
            "INSERT INTO memories(id,memory_type,content) VALUES('trigger-check','stable_fact','trigger')"
        )
        store._conn.commit()
        after_revision = store._conn.execute(
            "SELECT revision FROM retrieval_revision WHERE singleton=1"
        ).fetchone()[0]
        self.assertGreater(after_revision, before_revision)

        original_ledger = [tuple(row) for row in ledger]
        original_fingerprint = store._schema_fingerprint_sync()
        store.initialize()
        current_ledger = store._conn.execute(
            """SELECT from_revision,to_revision,state,backup_path,
                      schema_fingerprint,applied_at
               FROM schema_migration_ledger"""
        ).fetchall()
        self.assertEqual(original_ledger, [tuple(row) for row in current_ledger])
        self.assertEqual(original_fingerprint, store._schema_fingerprint_sync())
        self.assertEqual("", store.last_schema_backup_path)

    def test_schema_script_parser_keeps_trigger_body_in_one_statement(self) -> None:
        store = MemoryStore(self.path)
        self.addCleanup(store.close)
        with store._transaction_sync():
            store._execute_schema_script_sync(
                """
                CREATE TABLE parser_source(value INTEGER);
                CREATE TABLE parser_sink(value INTEGER);
                CREATE TRIGGER parser_trigger AFTER INSERT ON parser_source
                BEGIN
                    INSERT INTO parser_sink(value) VALUES(new.value);
                    UPDATE parser_sink SET value=value+1;
                END;
                """
            )
            store._conn.execute("INSERT INTO parser_source(value) VALUES(1)")

        self.assertEqual(
            2,
            store._conn.execute("SELECT value FROM parser_sink").fetchone()[0],
        )

    def test_existing_current_schema_without_numeric_ledger_is_backed_up(self) -> None:
        seed = MemoryStore(self.path)
        seed.initialize()
        seed._conn.execute("DELETE FROM schema_metadata WHERE key='migration_revision'")
        seed._conn.execute("DROP TABLE schema_migration_ledger")
        seed._conn.commit()
        seed.close()

        store = MemoryStore(self.path)
        self.addCleanup(store.close)
        store.initialize()

        backup = Path(store.last_schema_backup_path)
        self.assertTrue(backup.is_file())
        if os.name == "nt":
            self.assertNotEqual(0o222, backup.stat().st_mode & 0o777)
        else:
            self.assertEqual(0o600, backup.stat().st_mode & 0o777)
        with sqlite3.connect(backup) as backup_connection:
            self.assertEqual(
                MemoryStore.SCHEMA_VERSION,
                backup_connection.execute(
                    "SELECT value FROM schema_metadata WHERE key='schema_version'"
                ).fetchone()[0],
            )
            self.assertIsNone(
                backup_connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration_ledger'"
                ).fetchone()
            )
        self.assertEqual(
            str(backup),
            store._conn.execute(
                "SELECT backup_path FROM schema_migration_ledger"
            ).fetchone()[0],
        )

    def test_future_revision_fails_before_wal_or_backup_and_preserves_bytes(self) -> None:
        seed = MemoryStore(self.path)
        seed.initialize()
        fingerprint = seed._schema_fingerprint_sync()
        now = "2030-01-01T00:00:00+00:00"
        seed._conn.execute(
            """INSERT INTO schema_migration_ledger(
                   from_revision,to_revision,state,backup_path,schema_fingerprint,applied_at
               ) VALUES(?,?,?,?,?,?)""",
            (
                MemoryStore.SCHEMA_MIGRATION_REVISION,
                MemoryStore.SCHEMA_MIGRATION_REVISION + 1,
                "applied",
                "future.backup.db",
                fingerprint,
                now,
            ),
        )
        seed._conn.execute(
            "UPDATE schema_metadata SET value=?,updated_at=? WHERE key='migration_revision'",
            (str(MemoryStore.SCHEMA_MIGRATION_REVISION + 1), now),
        )
        seed._conn.commit()
        seed.close()

        before_bytes = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with sqlite3.connect(self.path) as before_connection:
            before_schema = _schema_digest(before_connection)
            before_ledger = before_connection.execute(
                """SELECT from_revision,to_revision,state,backup_path,
                          schema_fingerprint,applied_at
                   FROM schema_migration_ledger ORDER BY to_revision"""
            ).fetchall()
        backups_before = set(self.path.parent.glob("*.before-*.db"))

        store = MemoryStore(self.path)
        try:
            with self.assertRaisesRegex(sqlite3.DatabaseError, "future schema migration revision"):
                store.initialize()
            self.assertEqual("", store.last_schema_backup_path)
            self.assertEqual(0, store._conn.total_changes)
        finally:
            store.close()

        self.assertEqual(before_bytes, hashlib.sha256(self.path.read_bytes()).hexdigest())
        with sqlite3.connect(self.path) as after_connection:
            self.assertEqual(before_schema, _schema_digest(after_connection))
            self.assertEqual(
                before_ledger,
                after_connection.execute(
                    """SELECT from_revision,to_revision,state,backup_path,
                              schema_fingerprint,applied_at
                       FROM schema_migration_ledger ORDER BY to_revision"""
                ).fetchall(),
            )
        self.assertEqual(backups_before, set(self.path.parent.glob("*.before-*.db")))

    def test_mid_migration_failure_rolls_back_schema_data_and_version(self) -> None:
        self._create_legacy_database()
        with sqlite3.connect(self.path) as before_connection:
            before_schema = _schema_digest(before_connection)
            before_columns = {
                row[1] for row in before_connection.execute("PRAGMA table_info(memories)")
            }

        store = MemoryStore(self.path)
        before_fingerprint = store._schema_fingerprint_sync()
        original = store._redact_existing_sensitive_rows_sync

        def fail_mid_migration() -> None:
            original()
            raise RuntimeError("injected migration failure")

        store._redact_existing_sensitive_rows_sync = fail_mid_migration
        with self.assertRaisesRegex(RuntimeError, "injected migration failure"):
            store.initialize()

        backup = Path(store.last_schema_backup_path)
        self.assertTrue(backup.is_file())
        self.assertEqual(before_columns, store._table_column_names_sync("memories"))
        self.assertIsNone(
            store._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration_ledger'"
            ).fetchone()
        )
        self.assertIsNone(
            store._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_metadata'"
            ).fetchone()
        )
        self.assertEqual(
            "legacy row",
            store._conn.execute("SELECT content FROM memories WHERE id='legacy'").fetchone()[0],
        )
        self.assertEqual(before_fingerprint, store._schema_fingerprint_sync())
        with sqlite3.connect(backup) as backup_connection:
            self.assertEqual(before_schema, _schema_digest(backup_connection))

        store._redact_existing_sensitive_rows_sync = original
        store.initialize()
        self.assertEqual(
            MemoryStore.SCHEMA_MIGRATION_REVISION,
            store._conn.execute(
                "SELECT to_revision FROM schema_migration_ledger"
            ).fetchone()[0],
        )
        store.close()

    def test_read_only_initialize_never_creates_ledger_backup_or_ddl(self) -> None:
        self._create_legacy_database()
        before_bytes = hashlib.sha256(self.path.read_bytes()).hexdigest()
        before_files = set(self.path.parent.iterdir())

        store = MemoryStore(self.path, read_only=True)
        store.initialize()
        self.assertEqual("", store.last_schema_backup_path)
        self.assertIsNone(
            store._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration_ledger'"
            ).fetchone()
        )
        store.close()

        self.assertEqual(before_bytes, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(before_files, set(self.path.parent.iterdir()))

    def test_revision_one_timeline_namespace_migration_backs_up_and_keeps_legacy_blank(self) -> None:
        seed = MemoryStore(self.path)
        seed.initialize()
        seed.close()
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                ALTER TABLE timeline RENAME TO timeline_revision_two;
                CREATE TABLE timeline (
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
                DROP TABLE timeline_revision_two;
                ALTER TABLE summary_failures RENAME TO summary_failures_revision_two;
                CREATE TABLE summary_failures (
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
                DROP TABLE summary_failures_revision_two;
                INSERT INTO timeline(
                    id,event_type,session_id,scope,subject_id,object_id,content,
                    metadata,message_id,dedupe_key,occurred_at,created_at
                ) VALUES(
                    'legacy-timeline','user_message','same-session','private',
                    'person-a','bot-a','legacy event','{}','legacy-message',
                    'legacy-dedupe','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00'
                );
                INSERT INTO summary_failures(
                    session_id,scope,start_timeline_id,end_timeline_id,retry_count,
                    last_error,metadata,created_at,updated_at
                ) VALUES(
                    'same-session','private','legacy-timeline','legacy-timeline',1,
                    'legacy failure','{}','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00'
                );
                UPDATE schema_metadata SET value='1' WHERE key='migration_revision';
                UPDATE schema_migration_ledger SET to_revision=1 WHERE to_revision=2;
                """
            )
            connection.commit()

        store = MemoryStore(self.path)
        self.addCleanup(store.close)
        store.initialize()

        backup = Path(store.last_schema_backup_path)
        self.assertTrue(backup.is_file())
        timeline = store._conn.execute(
            "SELECT owner_bot_id,persona_id,content FROM timeline WHERE id='legacy-timeline'"
        ).fetchone()
        failure = store._conn.execute(
            "SELECT owner_bot_id,persona_id,last_error FROM summary_failures "
            "WHERE session_id='same-session'"
        ).fetchone()
        self.assertEqual(("", "", "legacy event"), tuple(timeline))
        self.assertEqual(("", "", "legacy failure"), tuple(failure))
        self.assertEqual(
            [(0, 1), (1, 2)],
            [
                tuple(row)
                for row in store._conn.execute(
                    "SELECT from_revision,to_revision FROM schema_migration_ledger "
                    "ORDER BY to_revision"
                ).fetchall()
            ],
        )
        with sqlite3.connect(backup) as backup_connection:
            timeline_columns = {
                row[1] for row in backup_connection.execute("PRAGMA table_info(timeline)")
            }
            self.assertNotIn("owner_bot_id", timeline_columns)
            self.assertNotIn("persona_id", timeline_columns)


if __name__ == "__main__":
    unittest.main()
