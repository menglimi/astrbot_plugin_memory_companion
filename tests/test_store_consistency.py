from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core.models import EntityRef, MemoryRecord
from astrbot_plugin_remember_you.core.store import MemoryStore


class StoreConsistencyTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    async def test_connection_uses_conservative_wal_and_busy_settings(self) -> None:
        store = self.make_store()

        self.assertEqual(1, store._conn.execute("PRAGMA foreign_keys").fetchone()[0])
        self.assertEqual(3000, store._conn.execute("PRAGMA busy_timeout").fetchone()[0])
        self.assertEqual(500, store._conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0])

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
        expected = store._database_file_snapshot()["wal_bytes"]

        self.assertEqual(expected, stats["wal"]["wal_bytes"])
        self.assertEqual(expected, stats["wal"]["current_files"]["wal_bytes"])
        self.assertEqual(999999999, stats["wal"]["last_health_check"]["wal_bytes"])

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


if __name__ == "__main__":
    unittest.main()
