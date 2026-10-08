from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore


class StoreConsistencyTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    async def test_initialize_repairs_incompatible_internal_control_tables(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "memory.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    legacy_required TEXT NOT NULL
                );
                INSERT INTO schema_metadata(key,value,updated_at,legacy_required)
                VALUES('schema_version','foreign-v1','','required');
                CREATE TABLE retrieval_revision (
                    singleton INTEGER PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 0,
                    legacy_required TEXT NOT NULL
                );
                INSERT INTO retrieval_revision(singleton,revision,legacy_required)
                VALUES(1,7,'required');
                """
            )
        finally:
            conn.close()

        store = MemoryStore(db_path)
        self.addCleanup(store.close)
        store.initialize()

        schema_columns = {
            row["name"] for row in store._conn.execute("PRAGMA table_info(schema_metadata)")
        }
        revision_columns = {
            row["name"] for row in store._conn.execute("PRAGMA table_info(retrieval_revision)")
        }
        self.assertEqual({"key", "value", "updated_at"}, schema_columns)
        self.assertEqual({"singleton", "revision"}, revision_columns)
        self.assertEqual(
            MemoryStore.SCHEMA_VERSION,
            store._conn.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()[0],
        )
        self.assertGreaterEqual(
            store._conn.execute(
                "SELECT revision FROM retrieval_revision WHERE singleton=1"
            ).fetchone()[0],
            7,
        )

    async def test_connection_uses_conservative_wal_and_busy_settings(self) -> None:
        store = self.make_store()

        self.assertEqual(1, store._conn.execute("PRAGMA foreign_keys").fetchone()[0])
        self.assertEqual(3000, store._conn.execute("PRAGMA busy_timeout").fetchone()[0])
        self.assertEqual(500, store._conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0])

    async def test_memory_ordering_uses_absolute_time_for_mixed_offsets(self) -> None:
        store = self.make_store()
        records = [
            MemoryRecord(
                id="mixed-offset-older",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="older event",
                importance=0.5,
                owner_bot_id="b1",
                metadata={"owner_bot_id": "b1"},
                occurred_at="2026-08-01T22:00:00+08:00",
            ),
            MemoryRecord(
                id="mixed-offset-newer",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="newer event",
                importance=0.5,
                owner_bot_id="b1",
                metadata={"owner_bot_id": "b1"},
                occurred_at="2026-08-01T20:00:00+00:00",
            ),
        ]
        for record in records:
            await store.insert_memory(record)

        listed = await store.list_memories(
            limit=10,
            include_pending=False,
            scope="private",
            lifecycle="stable_memory",
            session_id="qq:FriendMessage:u1",
        )
        candidates = await store.list_candidate_memories(limit=10)
        buckets = await store.list_memory_buckets(limit=10)

        self.assertEqual(
            ["mixed-offset-newer", "mixed-offset-older"],
            [record.id for record in listed],
        )
        self.assertEqual(
            ["mixed-offset-newer", "mixed-offset-older"],
            [record.id for record in candidates],
        )
        self.assertEqual("2026-08-01T20:00:00+00:00", buckets[0]["latest_at"])

    async def test_maintenance_repair_commits_fingerprint_work_in_batches(self) -> None:
        store = self.make_store()
        store.MAINTENANCE_REPAIR_BATCH_SIZE = 2
        for index in range(5):
            await store.insert_memory(
                MemoryRecord(
                    id=f"repair-batch-{index}",
                    memory_type="observation",
                    subject=EntityRef(kind="user", id="u1"),
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    content=f"repair batch row {index}",
                )
            )
        with store._lock:
            store._conn.execute(
                "UPDATE memories SET content_fingerprint='', merged_count=0 WHERE id LIKE 'repair-batch-%'"
            )
            store._conn.commit()

        original_transaction = store._transaction_sync
        transaction_entries = 0

        @contextmanager
        def counted_transaction():
            nonlocal transaction_entries
            transaction_entries += 1
            with original_transaction():
                yield

        with patch.object(store, "_transaction_sync", counted_transaction):
            result = await store.maintenance_repair()

        self.assertEqual(5, result["fingerprint_fixed"])
        self.assertGreaterEqual(transaction_entries, 5)
        rows = store._conn.execute(
            "SELECT content_fingerprint, merged_count FROM memories WHERE id LIKE 'repair-batch-%'"
        ).fetchall()
        self.assertTrue(all(row["content_fingerprint"] and row["merged_count"] >= 1 for row in rows))

    async def test_maintenance_repair_does_not_rebuild_fts_for_archived_rows(self) -> None:
        store = self.make_store()
        if not store._fts_enabled:
            self.skipTest("SQLite FTS5 is unavailable")
        await store.insert_memory(
            MemoryRecord(
                id="fts-visible",
                memory_type="observation",
                subject=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="visible row",
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="fts-archived",
                memory_type="observation",
                subject=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                visibility="private_pair",
                lifecycle="archived",
                content="archived row",
            )
        )

        result = await store.maintenance_repair()

        self.assertEqual(0, result["fts_rebuilt"])

    async def test_timeline_filters_order_and_cursor_normalize_timezone_offsets(self) -> None:
        store = self.make_store()
        earlier = await store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:u1",
            scope="private",
            subject_id="u1",
            object_id="b1",
            content="较早消息",
            metadata={"message_id": "timezone-earlier"},
            occurred_at="2026-08-01T00:30:00+08:00",
        )
        later = await store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:u1",
            scope="private",
            subject_id="u1",
            object_id="b1",
            content="较晚消息",
            metadata={"message_id": "timezone-later"},
            occurred_at="2026-07-31T16:45:00+00:00",
        )

        window = await store.timeline_window(
            start_at="2026-07-31T16:00:00+00:00",
            end_at="2026-07-31T17:00:00+00:00",
            scope="private",
            session_id="qq:FriendMessage:u1",
        )
        recent = await store.recent_timeline(
            limit=2,
            scope="private",
            session_id="qq:FriendMessage:u1",
            entity_id="u1",
        )
        cross_window = await store.recent_cross_window_timeline(
            source_scope="private",
            current_session_id="qq:FriendMessage:u2",
            since_at="2026-07-31T16:00:00+00:00",
            limit=2,
        )
        first_page = await store.unsummarized_timeline_window(
            session_id="qq:FriendMessage:u1", scope="private", limit=1
        )
        second_page = await store.unsummarized_timeline_window(
            session_id="qq:FriendMessage:u1",
            scope="private",
            limit=1,
            after_timeline_id=first_page["rows"][0]["id"],
        )
        batch_id = await store.create_summary_batch(
            "qq:FriendMessage:u1",
            "private",
            [{"id": later}, {"id": earlier}],
        )
        batch_rows = await store.summary_batch_rows(batch_id)

        self.assertEqual([later, earlier], [row["id"] for row in window])
        self.assertEqual([later, earlier], [row["id"] for row in recent])
        self.assertEqual([later, earlier], [row["id"] for row in cross_window])
        self.assertEqual(earlier, first_page["rows"][0]["id"])
        self.assertEqual(later, second_page["rows"][0]["id"])
        self.assertEqual([earlier, later], [row["id"] for row in batch_rows])

    async def test_wal_checkpoint_truncate_skips_below_threshold(self) -> None:
        store = self.make_store()
        # A fresh empty DB has a tiny (or absent) WAL, so a high threshold skips.
        result = await store.wal_checkpoint_truncate(min_wal_bytes=10 * 1024 * 1024)
        self.assertEqual("below_threshold", result.get("skipped"))
        self.assertFalse(result.get("checkpoint_attempted"))

    async def test_wal_checkpoint_truncate_attempts_above_threshold(self) -> None:
        store = self.make_store()
        for index in range(200):
            await store.insert_memory(
                MemoryRecord(
                    id=f"wal-{index}",
                    memory_type="observation",
                    subject=EntityRef(kind="user", id="u1"),
                    object=EntityRef(kind="group", id="g1"),
                    scope="group",
                    session_id="qq:GroupMessage:g1",
                    group_id="g1",
                    visibility="group_public",
                    lifecycle="stable_memory",
                    content=f"WAL checkpoint 写入 {index}",
                )
            )
        result = await store.wal_checkpoint_truncate(min_wal_bytes=1)
        # TRUNCATE is best-effort: it must report an attempt, not a skip, and
        # must not raise. busy==0 means it succeeded; busy==1 is a legal no-op.
        self.assertTrue(result.get("checkpoint_attempted"))
        self.assertIn(result.get("checkpoint_busy"), (0, 1))

    async def test_bucket_limit_applies_after_multi_bot_contexts_are_merged(self) -> None:
        store = self.make_store()
        for index in range(9):
            await store.insert_memory(
                MemoryRecord(
                    id=f"g1-bot-{index}",
                    memory_type="conversation_summary",
                    subject=EntityRef(kind="user", id="u1"),
                    object=EntityRef(kind="group", id="g1"),
                    scope="group",
                    session_id="qq:GroupMessage:g1",
                    group_id="g1",
                    visibility="group_public",
                    lifecycle="stable_memory",
                    content=f"群一 Bot {index} 的记忆",
                    metadata={"owner_bot_id": f"bot-{index}"},
                )
            )
        await store.insert_memory(
            MemoryRecord(
                id="g2-bot-old-name",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u2"),
                object=EntityRef(kind="group", id="g2", name="Zeta Old"),
                scope="group",
                session_id="qq:GroupMessage:g2",
                group_id="g2",
                visibility="group_public",
                lifecycle="stable_memory",
                content="群二的记忆",
                occurred_at="2026-07-20T10:00:00+00:00",
                metadata={"owner_bot_id": "bot-g2"},
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="g2-bot-new-name",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u2"),
                object=EntityRef(kind="group", id="g2", name="Alpha New"),
                scope="group",
                session_id="qq:GroupMessage:g2",
                group_id="g2",
                visibility="group_public",
                lifecycle="stable_memory",
                content="群二更新后的记忆",
                occurred_at="2026-07-21T10:00:00+00:00",
                metadata={"owner_bot_id": "bot-g2"},
            )
        )

        buckets = await store.list_memory_buckets(limit=2)
        by_target = {item["target_id"]: item for item in buckets}
        self.assertEqual({"g1", "g2"}, set(by_target))
        self.assertEqual(9, by_target["g1"]["memory_count"])
        self.assertEqual(9, len(by_target["g1"]["sample_contexts"]))
        self.assertEqual("Alpha New", by_target["g2"]["target_name"])

        await store.insert_memory(
            MemoryRecord(
                id="newer-private-bucket",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="private-user", name="私聊用户"),
                object=EntityRef.bot_self(bot_id="private-bot"),
                scope="private",
                session_id="qq:FriendMessage:private-user",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="比群聊更新的私聊记忆",
                occurred_at="2027-01-01T10:00:00+00:00",
                metadata={"owner_bot_id": "private-bot"},
            )
        )
        newest = await store.list_memory_buckets(limit=1)
        self.assertEqual(["private-user"], [item["target_id"] for item in newest])

    async def test_bucket_listing_can_return_the_complete_target_set(self) -> None:
        store = self.make_store()
        for index in range(3):
            await store.insert_memory(
                MemoryRecord(
                    id=f"private-target-{index}",
                    memory_type="conversation_summary",
                    subject=EntityRef(kind="user", id=f"user-{index}"),
                    object=EntityRef.bot_self(bot_id="bot"),
                    scope="private",
                    session_id=f"qq:FriendMessage:user-{index}",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    content=f"私聊目标 {index}",
                    metadata={"owner_bot_id": "bot"},
                )
            )

        limited = await store.list_memory_buckets(limit=2)
        complete = await store.list_memory_buckets(limit=None)

        self.assertEqual(2, len(limited))
        self.assertEqual(3, len(complete))

    async def test_internal_dreams_leave_private_buckets_and_legacy_sessions_are_typed(self) -> None:
        store = self.make_store()
        legacy_session_id = "7e6a17fd-d9c9-4753-95cc-5e93922fa72f"
        await store.insert_memory(
            MemoryRecord(
                id="private_companion_dream_test",
                memory_type="persona_life",
                subject=EntityRef.bot_self(),
                object=EntityRef(kind="session", id="private_companion:dream"),
                scope="private",
                session_id="private_companion:dream",
                visibility="bot_self",
                reality_level="persona_life",
                lifecycle="stable_memory",
                source_plugin="private_companion",
                content="Bot 梦境碎片：测试梦境。",
                tags=["dream", "dream_fragment", "persona_life"],
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="legacy-live2d-summary",
                memory_type="conversation_summary",
                subject=EntityRef(kind="unknown"),
                object=EntityRef(kind="user", id=legacy_session_id),
                scope="private",
                session_id=f"live2d_default:FriendMessage:{legacy_session_id}",
                visibility="private_pair",
                reality_level="imported_summary",
                lifecycle="stable_memory",
                source_plugin="livingmemory",
                content="旧 Live2D 会话摘要。",
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="native-private-memory",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="995051631", name="比折"),
                object=EntityRef.bot_self(),
                scope="private",
                session_id="default:FriendMessage:995051631",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="正常 QQ 私聊记忆。",
            )
        )

        fingerprint_before = (await store.get_memory("private_companion_dream_test")).content_fingerprint
        self.assertEqual(1, store.normalize_internal_bot_self_scopes())
        dream = await store.get_memory("private_companion_dream_test")
        self.assertIsNotNone(dream)
        self.assertEqual("unknown", dream.scope)
        self.assertEqual("bot_self", dream.visibility)
        self.assertNotEqual(fingerprint_before, dream.content_fingerprint)

        buckets = {item["target_id"]: item for item in await store.list_memory_buckets()}
        self.assertNotIn("private_companion:dream", buckets)
        self.assertEqual("legacy_live2d", buckets[legacy_session_id]["target_kind"])
        self.assertEqual("qq", buckets["995051631"]["target_kind"])
        legacy = await store.get_memory("legacy-live2d-summary")
        self.assertEqual("private", legacy.scope)
        self.assertEqual("private_pair", legacy.visibility)

    async def test_schedule_context_read_is_scoped_and_checkpoint_is_observable(self) -> None:
        store = self.make_store()
        current_session = "qq:FriendMessage:u1"
        await store.insert_memory(
            MemoryRecord(
                id="schedule-current",
                memory_type="schedule_fragment",
                subject=EntityRef.bot_self(),
                object=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id=current_session,
                visibility="bot_self",
                reality_level="persona_life",
                lifecycle="stable_memory",
                content="今天傍晚继续剪视频。",
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="profile-current",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="u1"),
                object=EntityRef.bot_self(),
                scope="private",
                session_id=current_session,
                visibility="private_pair",
                lifecycle="stable_memory",
                content="当前用户不喜欢被连续催问。",
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="other-private-action",
                memory_type="proactive_message",
                subject=EntityRef.bot_self(),
                object=EntityRef(kind="user", id="u2"),
                scope="private",
                session_id="qq:FriendMessage:u2",
                visibility="bot_self",
                reality_level="bot_action",
                lifecycle="stable_memory",
                content="只属于另一个私聊对象的主动消息。",
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="same-bot-group-action",
                memory_type="self_action",
                subject=EntityRef.bot_self(bot_id="b1"),
                scope="group",
                session_id="qq:GroupMessage:g1",
                visibility="bot_self",
                reality_level="bot_action",
                lifecycle="stable_memory",
                content="当前 Bot 在群里的公开动作。",
                metadata={"owner_bot_id": "b1"},
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="other-bot-group-action",
                memory_type="self_action",
                subject=EntityRef.bot_self(bot_id="b2"),
                scope="group",
                session_id="qq:GroupMessage:g2",
                visibility="bot_self",
                reality_level="bot_action",
                lifecycle="stable_memory",
                content="另一个 Bot 的群聊动作。",
                metadata={"owner_bot_id": "b2"},
            )
        )

        records = await store.list_schedule_context_memories(
            session_id=current_session,
            user_id="u1",
            bot_id="b1",
            limit=12,
        )
        ids = {record.id for record in records}
        self.assertIn("schedule-current", ids)
        self.assertIn("profile-current", ids)
        self.assertIn("same-bot-group-action", ids)
        self.assertNotIn("other-private-action", ids)
        self.assertNotIn("other-bot-group-action", ids)

        wal = await store.wal_health(checkpoint=True)
        self.assertTrue(wal["checkpoint_attempted"])
        self.assertIn("checkpoint_busy", wal)
        self.assertIn("checkpoint_log_frames", wal)
        self.assertIn("checkpointed_frames", wal)

    async def test_delete_memory_cascades_graph_and_relationship_edges(self) -> None:
        store = self.make_store()
        memory_id = await store.insert_memory(
            MemoryRecord(content="级联删除", lifecycle="stable_memory", visibility="shareable")
        )
        store._conn.execute(
            "INSERT INTO relationship_edges(id, source_memory_id) VALUES(?, ?)",
            ("rel-1", memory_id),
        )
        store._conn.execute(
            "INSERT INTO knowledge_edges(id, source_memory_id) VALUES(?, ?)",
            ("kg-1", memory_id),
        )
        store._conn.commit()

        self.assertTrue(await store.delete_memory(memory_id))
        self.assertEqual(0, store._conn.execute("SELECT COUNT(*) FROM relationship_edges").fetchone()[0])
        self.assertEqual(0, store._conn.execute("SELECT COUNT(*) FROM knowledge_edges").fetchone()[0])

    async def test_delete_memory_rolls_back_all_tables_on_failure(self) -> None:
        store = self.make_store()
        memory_id = await store.insert_memory(
            MemoryRecord(content="事务回滚", lifecycle="stable_memory", visibility="shareable")
        )
        store._conn.execute(
            "INSERT INTO relationship_edges(id, source_memory_id) VALUES(?, ?)",
            ("rel-rollback", memory_id),
        )
        store._conn.commit()
        original = store._delete_memory_fts_row

        def fail(_memory_id: str) -> None:
            raise RuntimeError("forced failure")

        store._delete_memory_fts_row = fail
        try:
            with self.assertRaisesRegex(RuntimeError, "forced failure"):
                await store.delete_memory(memory_id)
        finally:
            store._delete_memory_fts_row = original

        self.assertIsNotNone(await store.get_memory(memory_id))
        self.assertEqual(1, store._conn.execute("SELECT COUNT(*) FROM relationship_edges").fetchone()[0])

    async def test_retention_deletes_only_summarized_timeline_and_old_logs(self) -> None:
        store = self.make_store()
        old = "2020-01-01T00:00:00+00:00"
        summarized_id = await store.add_timeline_event(
            event_type="user_message",
            session_id="s1",
            scope="private",
            subject_id="u1",
            object_id="u1",
            content="已总结",
            occurred_at=old,
        )
        pending_id = await store.add_timeline_event(
            event_type="user_message",
            session_id="s1",
            scope="private",
            subject_id="u1",
            object_id="u1",
            content="未总结",
            occurred_at=old,
        )
        summary_id = await store.insert_memory(
            MemoryRecord(
                id="summary-source-retention",
                memory_type="conversation_summary",
                content="小王提到一个已总结的事实。",
                metadata={
                    "summary_refs": [summarized_id],
                    "source_event_ids": [summarized_id],
                    "key_facts_with_refs": [
                        {
                            "fact": "已总结",
                            "refs": [summarized_id],
                            "evidence": [{"ref": summarized_id, "quote": "已总结"}],
                        }
                    ],
                },
            )
        )
        store._conn.execute(
            "UPDATE timeline SET summarized_at=? WHERE id=?",
            ("2020-01-02T00:00:00+00:00", summarized_id),
        )
        log_id = await store.add_injection_log(
            session_id="s1",
            scope="private",
            query="旧日志",
            selected_memory_ids=[],
            blocked_reasons=[],
            injection_chars=0,
        )
        store._conn.execute("UPDATE injection_logs SET created_at=? WHERE id=?", (old, log_id))
        store._conn.commit()

        deleted = await store.prune_retained_rows(
            summarized_timeline_cutoff="2021-01-01T00:00:00+00:00",
            injection_log_cutoff="2021-01-01T00:00:00+00:00",
        )
        self.assertEqual({"timeline": 1, "injection_logs": 1}, deleted)
        self.assertIsNone(store._conn.execute("SELECT id FROM timeline WHERE id=?", (summarized_id,)).fetchone())
        self.assertIsNotNone(store._conn.execute("SELECT id FROM timeline WHERE id=?", (pending_id,)).fetchone())
        summary = await store.get_memory(summary_id)
        self.assertEqual([summarized_id], summary.metadata["source_expired_event_ids"])

    async def test_memory_management_update_is_atomic(self) -> None:
        store = self.make_store()
        memory_id = await store.insert_memory(
            MemoryRecord(
                content="原内容",
                evidence="原证据",
                visibility="private_pair",
                lifecycle="stable_memory",
            )
        )
        original = store._upsert_memory_fts_row

        def fail(_row) -> None:
            raise RuntimeError("forced fts failure")

        store._upsert_memory_fts_row = fail
        try:
            with self.assertRaisesRegex(RuntimeError, "forced fts failure"):
                await store.update_memory_payload(
                    memory_id,
                    content="新内容",
                    evidence="新证据",
                    visibility="shareable",
                    lifecycle="archived",
                )
        finally:
            store._upsert_memory_fts_row = original

        restored = await store.get_memory(memory_id)
        self.assertEqual("原内容", restored.content)
        self.assertEqual("原证据", restored.evidence)
        self.assertEqual("private_pair", restored.visibility)
        self.assertEqual("stable_memory", restored.lifecycle)

        self.assertTrue(
            await store.update_memory_payload(
                memory_id,
                content="新内容",
                evidence="新证据",
                visibility="shareable",
                lifecycle="archived",
            )
        )
        updated = await store.get_memory(memory_id)
        self.assertEqual("新内容", updated.content)
        self.assertEqual("新证据", updated.evidence)
        self.assertEqual("shareable", updated.visibility)
        self.assertEqual("archived", updated.lifecycle)

    async def test_concurrent_timeline_ingest_is_idempotent_by_message_id(self) -> None:
        store = self.make_store()
        kwargs = {
            "event_type": "user_message",
            "session_id": "qq:GroupMessage:g1",
            "scope": "group",
            "subject_id": "u1",
            "object_id": "g1",
            "content": "并发的同一条消息",
            "metadata": {"message_id": "message-42"},
        }
        ids = await asyncio.gather(*(store.add_timeline_event(**kwargs) for _ in range(12)))
        self.assertEqual(1, len(set(ids)))
        self.assertEqual(1, store._conn.execute("SELECT COUNT(*) FROM timeline").fetchone()[0])

    async def test_insert_recovers_once_from_database_path_error(self) -> None:
        store = self.make_store()
        original = store._insert_memory_sync
        attempts = 0

        def fail_once(record: MemoryRecord, review_reason: str = "") -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise sqlite3.OperationalError("unable to open database file")
            return original(record, review_reason)

        store._insert_memory_sync = fail_once
        memory_id = await store.insert_memory(
            MemoryRecord(content="数据库路径恢复", lifecycle="stable_memory", visibility="private_pair")
        )

        self.assertEqual(2, attempts)
        self.assertIsNotNone(await store.get_memory(memory_id))
        stats = await store.stats()
        self.assertEqual(1, stats["wal"]["database_recovery_attempts"])
        self.assertEqual(1, stats["wal"]["database_recovery_successes"])
        self.assertIn("unable to open", stats["wal"]["last_database_error"]["message"])

    async def test_stats_prefers_current_wal_file_snapshot(self) -> None:
        store = self.make_store()
        store._last_wal_health = {"wal_bytes": 999999999, "checkpoint_attempted": True}

        stats = await store.stats()
        snapshot = store._database_file_snapshot()
        expected = snapshot["wal_bytes"]
        expected_storage = sum(
            max(0, int(snapshot[key] or 0))
            for key in ("db_bytes", "wal_bytes", "shm_bytes")
        )

        self.assertEqual(expected, stats["wal"]["wal_bytes"])
        self.assertEqual(expected, stats["wal"]["current_files"]["wal_bytes"])
        self.assertEqual(999999999, stats["wal"]["last_health_check"]["wal_bytes"])
        self.assertEqual(expected_storage, stats["memory_storage_bytes"])
        self.assertEqual(max(0, snapshot["db_bytes"]), stats["memory_storage"]["database_bytes"])
        self.assertEqual(expected, stats["memory_storage"]["wal_bytes"])

    async def test_recent_timeline_entity_split_matches_baseline(self) -> None:
        store = self.make_store()
        scope = "group"
        session_id = "qq:GroupMessage:g1"
        entity = "u1"
        seed = [
            ("m1", entity, "bot", "2026-08-01T10:00:00+00:00"),
            ("m2", "u2", entity, "2026-08-01T11:00:00+00:00"),
            ("m3", entity, entity, "2026-08-01T12:00:00+00:00"),
            ("m4", entity, "u3", "2026-08-01T13:00:00+00:00"),
            ("m5", "u4", entity, "2026-08-01T14:00:00+00:00"),
            ("noise-entity", "u2", "u3", "2026-08-01T15:00:00+00:00"),
            ("noise-session", entity, "bot", "2026-08-01T16:00:00+00:00"),
        ]
        for event_id, subject_id, object_id, occurred_at in seed:
            other_session = "qq:GroupMessage:g2" if event_id == "noise-session" else session_id
            await store.add_timeline_event(
                event_type="user_message",
                session_id=other_session,
                scope=scope,
                subject_id=subject_id,
                object_id=object_id,
                content=f"content-{event_id}",
                occurred_at=occurred_at,
            )

        def baseline(limit: int, offset: int) -> list[str]:
            with store._lock:
                rows = store._conn.execute(
                    """
                    SELECT * FROM timeline
                    WHERE scope=? AND session_id=? AND (subject_id=? OR object_id=?)
                    ORDER BY occurred_at DESC, created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (scope, session_id, entity, entity, limit, offset),
                ).fetchall()
            return [str(row["content"]) for row in rows]

        for limit, offset in ((10, 0), (2, 0), (2, 1), (1, 4)):
            actual = await store.recent_timeline(
                limit=limit,
                scope=scope,
                session_id=session_id,
                entity_id=entity,
                offset=offset,
            )
            self.assertEqual(
                baseline(limit, offset),
                [str(row["content"]) for row in actual],
                f"limit={limit} offset={offset}",
            )

        # Rows visible to both branches must appear exactly once.
        all_rows = await store.recent_timeline(
            limit=10, scope=scope, session_id=session_id, entity_id=entity
        )
        self.assertEqual(5, len(all_rows))
        self.assertEqual(
            ["content-m5", "content-m4", "content-m3", "content-m2", "content-m1"],
            [row["content"] for row in all_rows],
        )

    async def test_recovery_never_replaces_a_missing_database_with_empty_file(self) -> None:
        store = self.make_store()
        store.close()
        store.db_path.unlink()
        store._closed = False

        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "database file is missing"):
                store._recover_connection_sync()
        finally:
            store._closed = True
        self.assertFalse(store.db_path.exists())

    async def test_memory_ordering_uses_absolute_time_for_mixed_offsets(self) -> None:
        store = self.make_store()
        records = [
            MemoryRecord(
                id="mixed-offset-older",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="older event",
                importance=0.5,
                owner_bot_id="b1",
                metadata={"owner_bot_id": "b1"},
                occurred_at="2026-08-01T22:00:00+08:00",
            ),
            MemoryRecord(
                id="mixed-offset-newer",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="newer event",
                importance=0.5,
                owner_bot_id="b1",
                metadata={"owner_bot_id": "b1"},
                occurred_at="2026-08-01T20:00:00+00:00",
            ),
        ]
        for record in records:
            await store.insert_memory(record)

        listed = await store.list_memories(
            limit=10,
            include_pending=False,
            scope="private",
            lifecycle="stable_memory",
            session_id="qq:FriendMessage:u1",
        )
        candidates = await store.list_candidate_memories(limit=10)
        buckets = await store.list_memory_buckets(limit=10)

        self.assertEqual(
            ["mixed-offset-newer", "mixed-offset-older"],
            [record.id for record in listed],
        )
        self.assertEqual(
            ["mixed-offset-newer", "mixed-offset-older"],
            [record.id for record in candidates],
        )
        self.assertEqual("2026-08-01T20:00:00+00:00", buckets[0]["latest_at"])

    async def test_maintenance_repair_commits_fingerprint_work_in_batches(self) -> None:
        store = self.make_store()
        store.MAINTENANCE_REPAIR_BATCH_SIZE = 2
        for index in range(5):
            await store.insert_memory(
                MemoryRecord(
                    id=f"repair-batch-{index}",
                    memory_type="observation",
                    subject=EntityRef(kind="user", id="u1"),
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    content=f"repair batch row {index}",
                )
            )
        with store._lock:
            store._conn.execute(
                "UPDATE memories SET content_fingerprint='', merged_count=0 WHERE id LIKE 'repair-batch-%'"
            )
            store._conn.commit()

        original_transaction = store._transaction_sync
        transaction_entries = 0

        @contextmanager
        def counted_transaction():
            nonlocal transaction_entries
            transaction_entries += 1
            with original_transaction():
                yield

        with patch.object(store, "_transaction_sync", counted_transaction):
            result = await store.maintenance_repair()

        self.assertEqual(5, result["fingerprint_fixed"])
        self.assertGreaterEqual(transaction_entries, 5)
        rows = store._conn.execute(
            "SELECT content_fingerprint, merged_count FROM memories WHERE id LIKE 'repair-batch-%'"
        ).fetchall()
        self.assertTrue(all(row["content_fingerprint"] and row["merged_count"] >= 1 for row in rows))

    async def test_maintenance_repair_does_not_rebuild_fts_for_archived_rows(self) -> None:
        store = self.make_store()
        if not store._fts_enabled:
            self.skipTest("SQLite FTS5 is unavailable")
        await store.insert_memory(
            MemoryRecord(
                id="fts-visible",
                memory_type="observation",
                subject=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="visible row",
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="fts-archived",
                memory_type="observation",
                subject=EntityRef(kind="user", id="u1"),
                scope="private",
                session_id="qq:FriendMessage:u1",
                visibility="private_pair",
                lifecycle="archived",
                content="archived row",
            )
        )

        result = await store.maintenance_repair()

        self.assertEqual(0, result["fts_rebuilt"])


if __name__ == "__main__":
    unittest.main()
