from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core.models import MemoryRecord
from astrbot_plugin_remember_you.core.store import MemoryStore


class StoreConsistencyTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

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


if __name__ == "__main__":
    unittest.main()
