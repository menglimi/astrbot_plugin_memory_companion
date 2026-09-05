from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore


def _memory(memory_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        memory_type="observation",
        subject=EntityRef(kind="user", id="u1"),
        object=EntityRef(kind="bot", id="b1"),
        scope="private",
        session_id="qq:FriendMessage:u1",
        platform="qq",
        visibility="private_pair",
        lifecycle="stable_memory",
        content=f"批量事务测试 {memory_id}",
    )


class OptimizedBatchWriteTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    async def test_capture_batch_rolls_back_one_item_and_skips_its_dependency(self) -> None:
        store = self.make_store()
        original_insert = store._insert_memory_sync

        def insert_then_fail(
            record: MemoryRecord,
            review_reason: str = "",
            _commit: bool = True,
        ) -> str:
            memory_id = original_insert(record, review_reason, _commit=False)
            if record.id == "batch-fail":
                raise RuntimeError("injected item failure")
            return memory_id

        store._insert_memory_sync = insert_then_fail
        statements: list[str] = []
        store._conn.set_trace_callback(statements.append)
        try:
            results = await store.capture_write_batch(
                [
                    {"kind": "memory", "record": _memory("batch-first")},
                    {"kind": "memory", "record": _memory("batch-fail")},
                    {
                        "kind": "relationship",
                        "requires_ok": [1],
                        "source_memory_id_from": 1,
                        "params": {
                            "subject": EntityRef(kind="user", id="u1"),
                            "object": EntityRef(kind="bot", id="b1"),
                            "relation_type": "trusts",
                            "scope": "private",
                            "session_id": "qq:FriendMessage:u1",
                            "group_id": "",
                            "visibility": "private_pair",
                            "evidence": "依赖失败项，不应写入",
                            "confidence": 0.8,
                            "review_status": "auto",
                            "metadata": {},
                        },
                    },
                    {},
                    {"kind": "memory", "record": _memory("batch-last")},
                ]
            )
        finally:
            store._conn.set_trace_callback(None)

        self.assertEqual([True, False, False, False, True], [item["ok"] for item in results])
        self.assertEqual("skip_required_op_failed", results[2]["code"])
        self.assertEqual("unknown_batch_op:unknown", results[3]["code"])
        self.assertIsNotNone(await store.get_memory("batch-first"))
        self.assertIsNone(await store.get_memory("batch-fail"))
        self.assertIsNotNone(await store.get_memory("batch-last"))
        self.assertEqual([], await store.list_relationships(limit=10))
        self.assertEqual(
            1,
            sum(statement.strip().upper() == "COMMIT" for statement in statements),
        )

    async def test_import_batch_keeps_timeline_summary_in_outer_transaction(self) -> None:
        store = self.make_store()
        statements: list[str] = []
        store._conn.set_trace_callback(statements.append)
        try:
            results = await store.import_batch_ops(
                [
                    {
                        "kind": "timeline",
                        "params": {
                            "event_type": "user_message",
                            "session_id": "qq:FriendMessage:u1",
                            "scope": "private",
                            "subject_id": "u1",
                            "object_id": "b1",
                            "content": "同事务导入并标记总结",
                            "metadata": {"message_id": "batch-timeline-1"},
                            "occurred_at": "2026-09-06T00:00:00+00:00",
                        },
                        "summarize": True,
                    },
                    {"kind": "memory", "record": _memory("import-memory")},
                    {},
                ]
            )
        finally:
            store._conn.set_trace_callback(None)

        self.assertEqual([True, True, False], [item["ok"] for item in results])
        timeline = await store.recent_timeline(limit=10)
        self.assertEqual(1, len(timeline))
        self.assertTrue(timeline[0]["summarized_at"])
        self.assertIsNotNone(await store.get_memory("import-memory"))
        self.assertEqual(
            1,
            sum(statement.strip().upper() == "COMMIT" for statement in statements),
        )

    async def test_identity_batch_accepts_omitted_optional_fields(self) -> None:
        store = self.make_store()

        row_ids = await store.upsert_identities(
            [
                {
                    "platform": "qq",
                    "entity": EntityRef(kind="group", id="g1", name="测试群"),
                    "profile": {"last_session": "qq:GroupMessage:g1"},
                    "confidence": 0.7,
                }
            ]
        )

        self.assertEqual(["qq:group:g1"], row_ids)
        identities = await store.list_identities(limit=10)
        self.assertEqual(["测试群"], identities[0]["aliases"])


class OptimizedEmbeddingCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_binary_and_legacy_json_embeddings_are_both_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            store.initialize()
            try:
                binary_memory = _memory("embedding-binary")
                legacy_memory = _memory("embedding-legacy")
                await store.insert_memory(binary_memory)
                await store.insert_memory(legacy_memory)
                await store.upsert_memory_embedding(
                    memory_id=binary_memory.id,
                    provider_id="embedder",
                    text_hash="binary-hash",
                    vector=[0.0, 5.0],
                )
                await store.upsert_memory_embedding(
                    memory_id=legacy_memory.id,
                    provider_id="embedder",
                    text_hash="legacy-hash",
                    vector=[3.0, 4.0],
                )

                raw_binary = store._conn.execute(
                    "SELECT vector FROM memory_embeddings WHERE memory_id=?",
                    (binary_memory.id,),
                ).fetchone()[0]
                self.assertIsInstance(raw_binary, bytes)
                store._conn.execute(
                    "UPDATE memory_embeddings SET vector=? WHERE memory_id=?",
                    (json.dumps([3.0, 4.0]), legacy_memory.id),
                )
                store._conn.commit()

                rows = await store.list_embedding_candidate_rows(provider_id="embedder")
                vectors = {record.id: vector for record, vector, _ in rows}
                self.assertEqual([0.0, 1.0], vectors[binary_memory.id])
                self.assertAlmostEqual(0.6, vectors[legacy_memory.id][0])
                self.assertAlmostEqual(0.8, vectors[legacy_memory.id][1])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
