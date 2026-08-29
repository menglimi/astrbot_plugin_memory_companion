from __future__ import annotations

import json
import sqlite3
import os
import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.bridge import serialize_memory
from astrbot_plugin_memory_companion.core.audit import MemoryAuditManager


ATOM_COLUMNS = {
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
}


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


class MemoryAtomV2Tests(unittest.TestCase):
    def make_store(self) -> MemoryStore:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = MemoryStore(Path(directory.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    @staticmethod
    def record(memory_id: str, **changes) -> MemoryRecord:
        values = {
            "id": memory_id,
            "memory_type": "stable_fact",
            "subject": EntityRef(kind="user", id="user-1"),
            "object": EntityRef(kind="bot", id="bot-1"),
            "scope": "private",
            "session_id": "qq:FriendMessage:user-1",
            "platform": "qq",
            "visibility": "private_pair",
            "reality_level": "real_user_fact",
            "lifecycle": "stable_memory",
            "content": "用户喜欢蓝风铃。",
            "owner_bot_id": "bot-1",
        }
        values.update(changes)
        return MemoryRecord(**values)

    def test_new_database_has_atom_columns_and_indexes_and_reinitialize_is_safe(self) -> None:
        store = self.make_store()
        store._insert_memory_sync(self.record("kept"))

        store.initialize()

        columns = {row["name"] for row in store._conn.execute("PRAGMA table_info(memories)")}
        indexes = {row["name"] for row in store._conn.execute("PRAGMA index_list(memories)")}
        self.assertTrue(ATOM_COLUMNS.issubset(columns))
        self.assertTrue(
            {
                "idx_memories_atom_domain",
                "idx_memories_validity_time",
                "idx_memories_canonical_key",
            }.issubset(indexes)
        )
        self.assertEqual(1, store._conn.execute("SELECT COUNT(*) FROM memories WHERE id='kept'").fetchone()[0])

    def test_clear_all_covers_bridge_portrait_emotion_and_namespace_tables(self) -> None:
        store = self.make_store()
        result = store._clear_all_memory_data_sync()
        expected = {
            "emotion_event_deliveries",
            "emotion_events",
            "portrait_learning_queue",
            "portrait_daily_runs",
            "portrait_suppressions",
            "portrait_facts",
            "portrait_evidence",
            "portrait_operations",
            "portrait_people",
        }
        self.assertTrue(expected.issubset(result["deleted"]))

    def test_serialization_round_trip_preserves_atom_fields(self) -> None:
        original = self.record(
            "round-trip",
            validity_status="superseded",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2026-08-01T00:00:00+00:00",
            salience=0.82,
            durability="durable",
            sensitivity="restricted",
            reinforcement_score=0.35,
            injection_count=4,
            last_injected_at="2026-07-01T00:00:00+00:00",
            canonical_key="preference:flower",
        )

        restored = MemoryRecord.from_row(original.to_db())

        for field in ATOM_COLUMNS:
            self.assertEqual(getattr(original, field), getattr(restored, field), field)
        self.assertEqual(original.content_fingerprint, restored.content_fingerprint)
        self.assertEqual(original.importance, restored.importance)

    def test_page_serialization_exposes_atom_fields_without_raw_secret_metadata(self) -> None:
        record = self.record(
            "page-atom",
            metadata={"persona_id": "persona-main", "access_token": "must-not-leak"},
            validity_status="superseded",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2026-08-01T00:00:00+00:00",
            salience=0.82,
            durability="durable",
            sensitivity="restricted",
            reinforcement_score=0.35,
            injection_count=4,
            last_injected_at="2026-07-01T00:00:00+00:00",
            canonical_key="preference:flower",
        ).ensure_defaults()

        payload = serialize_memory(record)

        for field in ATOM_COLUMNS:
            self.assertIn(field, payload)
            self.assertEqual(getattr(record, field), payload[field])
        self.assertEqual("persona-main", payload["persona_id"])
        self.assertNotIn("metadata", payload)
        self.assertNotIn("must-not-leak", json.dumps(payload, ensure_ascii=False))

    def test_audit_snapshot_includes_every_mutable_atom_field_for_rollback(self) -> None:
        record = self.record(
            "audit-atom",
            validity_status="expired",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2026-07-01T00:00:00+00:00",
            salience=0.61,
            durability="short",
            sensitivity="restricted",
        ).ensure_defaults()

        snapshot = MemoryAuditManager._snapshot(record)

        for field in (
            "validity_status",
            "valid_from",
            "valid_to",
            "salience",
            "durability",
            "sensitivity",
        ):
            self.assertEqual(getattr(record, field), snapshot[field])

    def test_memory_types_receive_safe_default_durability(self) -> None:
        self.assertEqual("pinned", self.record("explicit", memory_type="explicit_memory").ensure_defaults().durability)
        self.assertEqual("durable", self.record("preference", memory_type="user_preference").ensure_defaults().durability)
        self.assertEqual("short", self.record("state", memory_type="current_state").ensure_defaults().durability)

    def test_legacy_sqlite_row_and_upgrade_backfill_metadata_without_guessing_owner(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "legacy.db"
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute(LEGACY_MEMORIES_DDL)
        metadata = {
            "owner_bot_id": "legacy-bot",
            "validity_status": "superseded",
            "valid_from": "2025-01-01T00:00:00+00:00",
            "valid_to": "2026-01-01T00:00:00+00:00",
            "salience": 0.77,
            "durability": "durable",
            "sensitivity": "restricted",
            "reinforcement_score": 0.25,
            "injection_count": 3,
            "last_injected_at": "2025-06-01T00:00:00+00:00",
            "canonical_key": "legacy:preference",
        }
        conn.execute(
            """
            INSERT INTO memories(
                id,memory_type,subject_kind,subject_id,object_kind,object_id,scope,session_id,
                platform,visibility,sayability,reality_level,lifecycle,content,evidence,
                confidence,importance,metadata,created_at,updated_at,occurred_at,source_plugin
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "legacy",
                "stable_fact",
                "user",
                "user-1",
                "bot",
                "legacy-bot",
                "private",
                "qq:FriendMessage:user-1",
                "qq",
                "private_pair",
                "direct",
                "real_user_fact",
                "stable_memory",
                "旧记忆内容",
                "旧证据",
                0.8,
                0.73,
                json.dumps(metadata, ensure_ascii=False),
                "2025-01-01T00:00:00+00:00",
                "2025-01-01T00:00:00+00:00",
                "2025-01-01T00:00:00+00:00",
                "legacy",
            ),
        )
        conn.execute(
            """
            INSERT INTO memories(
                id,memory_type,subject_kind,subject_id,object_kind,object_id,scope,session_id,
                platform,visibility,sayability,reality_level,lifecycle,content,metadata
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "owner-unknown",
                "stable_fact",
                "user",
                "user-2",
                "bot",
                "actual-looking-bot",
                "private",
                "qq:FriendMessage:user-2",
                "qq",
                "private_pair",
                "direct",
                "real_user_fact",
                "stable_memory",
                "没有 owner metadata",
                "{}",
            ),
        )
        conn.commit()
        legacy_row = conn.execute("SELECT * FROM memories WHERE id='legacy'").fetchone()
        legacy_record = MemoryRecord.from_row(legacy_row)
        self.assertEqual("legacy-bot", legacy_record.owner_bot_id)
        self.assertEqual("superseded", legacy_record.validity_status)
        conn.close()

        store = MemoryStore(path)
        self.addCleanup(store.close)
        store.initialize()
        first_backup = Path(store.last_schema_backup_path)
        self.assertTrue(first_backup.is_file())
        if os.name == "nt":
            # Windows exposes ACL-backed files through a reduced mode model;
            # the implementation still applies the private-file ACL request.
            self.assertNotEqual(0o222, first_backup.stat().st_mode & 0o777)
        else:
            self.assertEqual(0o600, first_backup.stat().st_mode & 0o777)
        with sqlite3.connect(first_backup) as backup_conn:
            backup_columns = {
                row[1] for row in backup_conn.execute("PRAGMA table_info(memories)").fetchall()
            }
            self.assertFalse(ATOM_COLUMNS.intersection(backup_columns))
            self.assertEqual(
                "旧记忆内容",
                backup_conn.execute("SELECT content FROM memories WHERE id='legacy'").fetchone()[0],
            )
        # sqlite3.Connection.__exit__ commits/rolls back but does not close
        # the handle.  Close it explicitly so TemporaryDirectory cleanup is
        # reliable on Windows, where an open handle prevents unlinking.
        backup_conn.close()
        store.initialize()
        self.assertEqual("", store.last_schema_backup_path)

        upgraded = store._get_memory_sync("legacy")
        unknown = store._get_memory_sync("owner-unknown")
        self.assertIsNotNone(upgraded)
        self.assertEqual("legacy-bot", upgraded.owner_bot_id)
        self.assertEqual("superseded", upgraded.validity_status)
        self.assertEqual(0.77, upgraded.salience)
        self.assertEqual("durable", upgraded.durability)
        self.assertEqual("restricted", upgraded.sensitivity)
        self.assertEqual(3, upgraded.injection_count)
        self.assertTrue(upgraded.canonical_key.startswith("mav2:"))
        self.assertTrue(upgraded.content_fingerprint.startswith("mav2:"))
        self.assertEqual("", unknown.owner_bot_id)
        salience_column = store._conn.execute(
            "PRAGMA table_info(memories)"
        ).fetchall()
        salience_definition = next(
            row for row in salience_column if row[1] == "salience"
        )
        self.assertEqual("0", salience_definition[4])
        self.assertEqual(2, store._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def test_fingerprint_and_canonical_key_are_scoped_by_bot_and_platform(self) -> None:
        base = {
            "id": "base",
            "memory_type": "stable_fact",
            "subject": EntityRef(kind="user", id="same-user"),
            "object": EntityRef(kind="bot", id="same-bot-entity"),
            "scope": "private",
            "session_id": "shared-session",
            "visibility": "private_pair",
            "content": "完全相同的内容",
            "canonical_key": "same-fact",
        }
        first = MemoryRecord(**base, platform="qq", owner_bot_id="bot-a").ensure_defaults()
        other_bot = MemoryRecord(**{**base, "id": "other-bot"}, platform="qq", owner_bot_id="bot-b").ensure_defaults()
        other_platform = MemoryRecord(
            **{**base, "id": "other-platform"}, platform="telegram", owner_bot_id="bot-a"
        ).ensure_defaults()

        self.assertNotEqual(first.canonical_key, other_bot.canonical_key)
        self.assertNotEqual(first.content_fingerprint, other_bot.content_fingerprint)
        self.assertNotEqual(first.canonical_key, other_platform.canonical_key)
        self.assertNotEqual(first.content_fingerprint, other_platform.content_fingerprint)

    def test_storage_boundaries_redact_credentials_before_persistence(self) -> None:
        store = self.make_store()
        store._insert_memory_sync(
            self.record(
                "secret",
                content="调试值 api_key=super-se" "cret-value",
                evidence="Authorization: Bearer abcdefghijklmnop",
                metadata={
                    "access_token": "raw-token",
                    "weather_api_key": "raw-weather-key",
                    "note": "password=hunter2",
                },
            )
        )
        row = store._conn.execute(
            "SELECT content, evidence, metadata FROM memories WHERE id='secret'"
        ).fetchone()
        serialized = " ".join(str(row[key]) for key in ("content", "evidence", "metadata"))
        self.assertNotIn("super-secret-value", serialized)
        self.assertNotIn("abcdefghijklmnop", serialized)
        self.assertNotIn("raw-token", serialized)
        self.assertNotIn("raw-weather-key", serialized)
        self.assertNotIn("hunter2", serialized)
        self.assertIn("[REDACTED]", serialized)

        timeline_id = store._add_timeline_event_sync(
            "",
            "",
            "user_message",
            "qq:FriendMessage:user-1",
            "private",
            "user-1",
            "bot-1",
            "access_token=timeline-secret",
            {"authorization": "Bearer raw-timeline-token"},
            "2026-08-16T00:00:00+00:00",
        )
        timeline = store._conn.execute(
            "SELECT content, metadata FROM timeline WHERE id=?",
            (timeline_id,),
        ).fetchone()
        self.assertNotIn("timeline-secret", timeline["content"])
        self.assertNotIn("raw-timeline-token", timeline["metadata"])

        store._add_historical_timeline_events_sync([
            {
                "event_type": "user_message",
                "session_id": "qq:FriendMessage:user-1",
                "scope": "private",
                "subject_id": "user-1",
                "object_id": "bot-1",
                "message_id": "historical-secret",
                "content": "api_key=historic" "al-raw-key",
                "metadata": {"weather_api_key": "historical-metadata-key"},
            }
        ])
        historical = store._conn.execute(
            "SELECT content, metadata FROM timeline WHERE message_id='historical-secret'"
        ).fetchone()
        self.assertNotIn("historical-raw-key", historical["content"])
        self.assertNotIn("historical-metadata-key", historical["metadata"])

    def test_startup_scrub_rekeys_legacy_secret_and_drops_stale_vector(self) -> None:
        store = self.make_store()
        store._insert_memory_sync(self.record("legacy-secret", content="safe placeholder"))
        store._conn.execute(
            """UPDATE memories
               SET content='api_key=legacy-p""" + """lain-secret',
                   metadata='{"weather_api_key":"legacy-meta-secret"}'
               WHERE id='legacy-secret'"""
        )
        raw = store._conn.execute(
            "SELECT * FROM memories WHERE id='legacy-secret'"
        ).fetchone()
        store._upsert_memory_fts_row(raw)
        store._conn.execute(
            """INSERT INTO memory_embeddings(
                   memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at
               ) VALUES('legacy-secret','provider','hash',1,'[0.1]','now','now')"""
        )
        store._conn.commit()
        old_keys = store._conn.execute(
            "SELECT canonical_key,content_fingerprint FROM memories WHERE id='legacy-secret'"
        ).fetchone()

        store.initialize()

        row = store._conn.execute(
            "SELECT content,metadata,canonical_key,content_fingerprint FROM memories WHERE id='legacy-secret'"
        ).fetchone()
        fts = store._conn.execute(
            "SELECT search_text FROM memory_fts WHERE memory_id='legacy-secret'"
        ).fetchone()
        self.assertNotIn("legacy-plain-secret", row["content"])
        self.assertNotIn("legacy-meta-secret", row["metadata"])
        self.assertNotIn("legacy-plain-secret", fts["search_text"])
        self.assertNotEqual(old_keys["canonical_key"], row["canonical_key"])
        self.assertNotEqual(old_keys["content_fingerprint"], row["content_fingerprint"])
        self.assertEqual(
            0,
            store._conn.execute(
                "SELECT COUNT(*) FROM memory_embeddings WHERE memory_id='legacy-secret'"
            ).fetchone()[0],
        )

    def test_archive_transitions_lifecycle_and_atom_validity_together(self) -> None:
        store = self.make_store()
        store._insert_memory_sync(self.record("archive-me"))

        archived = store._archive_memories_sync(
            ["archive-me"],
            reason="test_natural_decay",
            supersedes_id="summary-1",
        )

        row = store._conn.execute(
            "SELECT lifecycle, validity_status FROM memories WHERE id='archive-me'"
        ).fetchone()
        self.assertEqual(1, archived)
        self.assertEqual("archived", row["lifecycle"])
        self.assertEqual("archived", row["validity_status"])

    def test_ordinary_admin_edit_preserves_non_active_validity(self) -> None:
        store = self.make_store()
        store._insert_memory_sync(
            self.record(
                "edit-superseded",
                validity_status="superseded",
                salience=0.42,
                durability="durable",
                sensitivity="restricted",
            )
        )

        updated = store._update_memory_payload_sync(
            "edit-superseded",
            None,
            "管理员修正后的内容",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            0.73,
            None,
            None,
        )

        record = store._get_memory_sync("edit-superseded")
        self.assertTrue(updated)
        self.assertEqual("管理员修正后的内容", record.content)
        self.assertEqual("superseded", record.validity_status)
        self.assertEqual("durable", record.durability)
        self.assertEqual("restricted", record.sensitivity)
        self.assertAlmostEqual(0.73, record.salience)

    def test_admin_archive_and_restore_keep_lifecycle_and_validity_consistent(self) -> None:
        store = self.make_store()
        store._insert_memory_sync(self.record("admin-lifecycle"))

        base_args = [None] * 15
        base_args[6] = "archived"
        self.assertTrue(store._update_memory_payload_sync("admin-lifecycle", *base_args))
        archived = store._get_memory_sync("admin-lifecycle")
        self.assertEqual("archived", archived.lifecycle)
        self.assertEqual("archived", archived.validity_status)

        restore_args = [None] * 15
        restore_args[6] = "stable_memory"
        self.assertTrue(store._update_memory_payload_sync("admin-lifecycle", *restore_args))
        restored = store._get_memory_sync("admin-lifecycle")
        self.assertEqual("stable_memory", restored.lifecycle)
        self.assertEqual("active", restored.validity_status)

    def test_validity_time_read_and_mark_injected_only_touch_existing_ids(self) -> None:
        store = self.make_store()
        store._insert_memory_sync(
            self.record(
                "current",
                valid_from="2026-08-01T00:00:00+00:00",
                valid_to="2026-09-01T00:00:00+00:00",
            )
        )
        store._insert_memory_sync(
            self.record(
                "future",
                content="未来才生效的记忆",
                valid_from="2026-09-02T00:00:00+00:00",
            )
        )
        store._insert_memory_sync(
            self.record(
                "ended",
                content="已经结束的记忆",
                valid_to="2026-08-10T00:00:00+00:00",
            )
        )
        store._insert_memory_sync(
            self.record(
                "superseded",
                content="已经被替代的记忆",
                validity_status="superseded",
            )
        )

        rows = store._list_memories_by_validity_sync(
            ["active"],
            "2026-08-16T00:00:00+00:00",
            "bot-1",
            "qq",
            "private",
            20,
            0,
        )
        self.assertEqual(["current"], [row.id for row in rows])

        updated = store._mark_injected_sync(
            ["current", "missing", "current"],
            "2026-08-16T01:02:03+00:00",
        )
        self.assertEqual(1, updated)
        self.assertEqual(1, store._get_memory_sync("current").injection_count)
        self.assertAlmostEqual(0.025, store._get_memory_sync("current").reinforcement_score)
        self.assertEqual("2026-08-16T01:02:03+00:00", store._get_memory_sync("current").last_injected_at)
        self.assertEqual(0, store._get_memory_sync("future").injection_count)


if __name__ == "__main__":
    unittest.main()
