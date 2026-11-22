from __future__ import annotations

import asyncio
import json
import math
import random
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import store as store_mod
from astrbot_plugin_memory_companion.core import vector_search
from astrbot_plugin_memory_companion.core.bridge import MemoryCompanionBridge
from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
    memory_embedding_text_hash,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.scoped_store import ScopedStore
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import (
    MemoryStore,
    _pack_embedding_vector,
    _unpack_embedding_vector,
    detect_embedding_blob_precision,
)
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy
if "quart" not in sys.modules:
    _quart_stub = types.ModuleType("quart")
    _quart_stub.jsonify = lambda payload=None, **kwargs: payload if payload is not None else kwargs
    _quart_stub.request = SimpleNamespace(args={}, method="GET")
    _quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = _quart_stub

from astrbot_plugin_memory_companion.page_api import PluginPageApi


def _make_record(
    memory_id: str,
    *,
    content: str = "测试记忆内容",
    scope: str = "group",
    session_id: str = "qq:GroupMessage:g1",
    group_id: str = "g1",
    user_id: str = "u1",
    bot_id: str = "b1",
    persona_id: str = "p1",
    visibility: str = "group_public",
    memory_type: str = "fact",
    metadata: dict | None = None,
    evidence: list | None = None,
) -> MemoryRecord:
    meta = {"owner_bot_id": bot_id, "persona_id": persona_id}
    if metadata:
        meta.update(metadata)
    return MemoryRecord(
        id=memory_id,
        memory_type=memory_type,
        scope=scope,
        platform="qq",
        session_id=session_id,
        group_id=group_id,
        subject=EntityRef(kind="user", id=user_id, name=f"用户{user_id}"),
        object=EntityRef(kind="group" if scope == "group" else "user", id=group_id or user_id, name="目标"),
        content=content,
        visibility=visibility,
        importance=0.8,
        confidence=0.9,
        metadata=meta,
        evidence=list(evidence or []),
    ).ensure_defaults()


class VectorPrecisionAndZeroCopyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.store = MemoryStore(self.tmp_dir / "memory.db")
        self.store.initialize()
        self.ctx = SessionContext(
            scope="group",
            platform="qq",
            user_id="u1",
            group_id="g1",
            bot_id="b1",
            persona_id="p1",
            session_id="qq:GroupMessage:g1",
        )

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_schema_and_config_aliases_expose_vector_precision(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        adv = schema["retrieval_advanced"]["items"]
        self.assertIn("vector_precision", adv)
        spec = adv["vector_precision"]
        self.assertEqual("float32", spec["default"])
        self.assertEqual(["float32", "float16"], spec["options"])
        self.assertIn("向量存储精度", spec["description"])
        self.assertIn("float16", spec["hint"])

        cfg = ConfigView({"retrieval_advanced": {"vector_storage_precision": "float16"}})
        self.assertEqual("float16", cfg.get("retrieval_advanced.vector_precision", "float32"))
        cfg2 = ConfigView({"retrieval": {"vector_precision": "float16"}})
        self.assertEqual("float16", cfg2.get("retrieval_advanced.vector_precision", "float32"))

    async def test_mixed_f64_f32_f16_json_cross_read_recall_and_runtime_switch(self) -> None:
        rng = random.Random(20261123)
        dim = 64
        query = [rng.uniform(-1.0, 1.0) for _ in range(dim)]
        vectors = [[rng.uniform(-1.0, 1.0) for _ in range(dim)] for _ in range(24)]

        # Seed mixed storage formats: f64, f32, f16, and legacy JSON strings.
        formats = ("float64", "float32", "float16", "json")
        for idx, vec in enumerate(vectors):
            rec = _make_record(f"mix-{idx:02d}", content=f"混合精度记录 {idx}")
            self.store._insert_memory_sync(rec)
            text_hash = memory_embedding_text_hash(rec, max_chars=1200)
            fmt = formats[idx % len(formats)]
            if fmt == "float64":
                blob: bytes | str = struct.pack(f"<{dim}d", *vec)
            elif fmt == "float32":
                blob = _pack_embedding_vector(vec, precision="float32")
            elif fmt == "float16":
                blob = _pack_embedding_vector(vec, precision="float16")
            else:
                blob = json.dumps(vec)
            now = datetime.now(timezone.utc).isoformat()
            with self.store._lock, self.store._conn:
                self.store._conn.execute(
                    """INSERT INTO memory_embeddings(
                           memory_id, provider_id, text_hash, dimension, vector, created_at, updated_at
                       ) VALUES (?, 'test', ?, ?, ?, ?, ?)""",
                    (rec.id, text_hash, dim, blob, now, now),
                )

        # Verify precision auto-detection & unpack roundtrip for every format.
        self.assertEqual("float64", detect_embedding_blob_precision(dim * 8, dim))
        self.assertEqual("float32", detect_embedding_blob_precision(dim * 4, dim))
        self.assertEqual("float16", detect_embedding_blob_precision(dim * 2, dim))
        for fmt in ("float32", "float16"):
            packed = _pack_embedding_vector(vectors[0], precision=fmt)
            unpacked = _unpack_embedding_vector(packed, dimension=dim)
            self.assertEqual(dim, len(unpacked))
            tol = 1e-5 if fmt == "float32" else 5e-3
            for a, b in zip(vectors[0], unpacked):
                self.assertAlmostEqual(a, b, delta=tol)

        expected = sorted(
            (
                (
                    math.fsum(a * b for a, b in zip(query, vec))
                    / (math.hypot(*query) * math.hypot(*vec)),
                    f"mix-{idx:02d}",
                )
                for idx, vec in enumerate(vectors)
            ),
            key=lambda item: (-item[0], item[1]),
        )[:6]

        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=query))
        engine = RetrievalEngine(
            self.store,
            VisibilityPolicy(),
            embedding_enabled=True,
            embedding_provider=provider,
            embedding_provider_id="test",
            embedding_candidate_limit=10,
            embedding_top_k=6,
            embedding_score_threshold=-1.0,
            knowledge_graph_enabled=False,
        )

        # Default float32 corpus
        self.store.vector_storage_precision = "float32"
        m32, s32, info32 = await engine._embedding_candidate_memories("查询", self.ctx, include_pending=False)
        self.assertEqual("float32", info32["embedding_vector_precision"])
        self.assertEqual([mid for _, mid in expected], [m.id for m in m32])
        for exp_score, mid in expected:
            self.assertAlmostEqual(exp_score, s32[mid], delta=5e-3)
        corpus_f32 = next(iter(self.store._vector_corpus_cache.values()))
        f32_vec_bytes = sum(b.matrix.nbytes for b in corpus_f32.vector_blocks)

        # Runtime switch to float16 invalidates old precision snapshot and halves vector RAM
        self.store.vector_storage_precision = "float16"
        m16, s16, info16 = await engine._embedding_candidate_memories("查询", self.ctx, include_pending=False)
        self.assertEqual("float16", info16["embedding_vector_precision"])
        self.assertFalse(info16["embedding_cache_hit"])
        self.assertEqual([mid for _, mid in expected], [m.id for m in m16])
        for exp_score, mid in expected:
            self.assertAlmostEqual(exp_score, s16[mid], delta=1e-2)
        corpus_f16 = self.store._vector_corpus_cache[
            ("test", dim, False, 1200, "float16")
        ]
        f16_vec_bytes = sum(b.matrix.nbytes for b in corpus_f16.vector_blocks)
        self.assertEqual(f32_vec_bytes // 2, f16_vec_bytes)

        # Verify pure-Python fallback also matches for float16 blocks
        with patch.object(vector_search, "_numpy", return_value=None):
            m16_py, _s16_py, info16_py = await engine._embedding_candidate_memories(
                "查询", self.ctx, include_pending=False
            )
        self.assertEqual("python_exact", info16_py["embedding_backend"])
        self.assertEqual([mid for _, mid in expected], [m.id for m in m16_py])

        # Transcode legacy f64/f32/json embeddings to float16 and purge orphans
        with self.store._lock, self.store._conn:
            self.store._conn.execute(
                """INSERT INTO memory_embeddings(
                       memory_id, provider_id, text_hash, dimension, vector, created_at, updated_at
                   ) VALUES ('orphan-id', 'test', 'h', ?, ?, 'now', 'now')""",
                (dim, struct.pack(f"<{dim}d", *vectors[0])),
            )
        report = await self.store.transcode_memory_embeddings(target_precision="float16", max_rows=100)
        self.assertEqual("float16", report["target_precision"])
        self.assertEqual(1, report["purged_orphans"])
        self.assertGreaterEqual(report["transcoded"], 18)  # 6 f64 + 6 f32 + 6 json
        self.assertGreater(report["bytes_saved"], 0)
        lengths = {
            row[0]
            for row in self.store._conn.execute("SELECT LENGTH(vector) FROM memory_embeddings").fetchall()
        }
        self.assertEqual({dim * 2}, lengths)

    async def test_zero_copy_snapshot_views_slim_corpus_and_kg_revision_isolation(self) -> None:
        dim = 128
        for idx in range(20):
            is_g1 = idx % 2 == 0
            rec = _make_record(
                f"zc-{idx:02d}",
                content="很长的普通对话正文 " * 20,
                scope="group" if is_g1 else "private",
                group_id="g1" if is_g1 else "",
                user_id="u1" if is_g1 else "u_other",
                session_id="qq:GroupMessage:g1" if is_g1 else "qq:FriendMessage:u_other",
                visibility="group_public" if is_g1 else "private_pair",
                metadata={"bulky_debug_payload": "X" * 4096, "extra_blob": [1, 2, 3]},
                evidence=[{"quote": "长证据" * 100}],
            )
            self.store._insert_memory_sync(rec)
            vec = [1.0 if i == (idx % dim) else 0.0 for i in range(dim)]
            await self.store.upsert_memory_embedding(
                memory_id=rec.id,
                provider_id="test",
                text_hash=memory_embedding_text_hash(rec, max_chars=1200),
                vector=vec,
            )

        # Prewarm full corpus across both groups
        warm = await self.store.prewarm_vector_corpus(provider_id="test")
        self.assertTrue(warm["warmed"])
        corpus = next(iter(self.store._vector_corpus_cache.values()))
        # Slim CorpusEntry: bulky metadata, non-profile content, and evidence stripped
        sample_entry = corpus.entries["zc-00"]
        self.assertEqual("", sample_entry.memory.content)
        self.assertEqual([], sample_entry.memory.evidence)
        self.assertNotIn("bulky_debug_payload", sample_entry.memory.metadata)
        self.assertEqual("b1", sample_entry.memory.metadata.get("owner_bot_id"))

        # Query only group g1 (non-contiguous subset of corpus block -> zero-copy view block!)
        query = [1.0] + [0.0] * (dim - 1)
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=query))
        engine = RetrievalEngine(
            self.store,
            VisibilityPolicy(),
            embedding_enabled=True,
            embedding_provider=provider,
            embedding_provider_id="test",
            embedding_candidate_limit=64,
            embedding_top_k=5,
            embedding_score_threshold=-1.0,
            knowledge_graph_enabled=False,
        )
        memories, _scores, info = await engine._embedding_candidate_memories("查询", self.ctx, include_pending=False)
        self.assertTrue(info["embedding_corpus_hit"])
        self.assertEqual("zc-00", memories[0].id)
        snap = next(iter(self.store._vector_search_cache.values()))
        self.assertTrue(any(block.is_view for block in snap.blocks))
        # View block owns only int32 indices + ref overhead, NOT the duplicated vector bytes!
        self.assertLess(snap.owned_bytes, snap.byte_size)
        self.assertEqual(snap.owned_bytes, info["embedding_snapshot_owned_bytes"])

        # Writing to knowledge graph bumps knowledge_revision ONLY, NOT retrieval_revision!
        rev_before = await self.store.memory_revision()
        kg_before = await self.store.knowledge_revision()
        await self.store.upsert_knowledge_node(node_type="topic", label="黑神话", metadata={"aliases": ["悟空"]})
        rev_after = await self.store.memory_revision()
        kg_after = await self.store.knowledge_revision()
        self.assertEqual(rev_before, rev_after)
        self.assertNotEqual(kg_before, kg_after)

        # Subsequent vector search must still hit the cached snapshot with 0 rows scanned!
        _m2, _s2, info2 = await engine._embedding_candidate_memories("查询", self.ctx, include_pending=False)
        self.assertTrue(info2["embedding_cache_hit"])
        self.assertEqual(0, info2["embedding_scanned_rows"])

    def test_shared_query_embedding_cache_shares_same_provider_and_isolates_others(self) -> None:
        vector_search.clear_shared_query_embedding_cache()
        shared_provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[0.6, 0.8]))
        other_provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[0.0, 1.0]))

        eng1 = RetrievalEngine(
            self.store,
            VisibilityPolicy(),
            embedding_enabled=True,
            embedding_provider=shared_provider,
            embedding_provider_id="shared-p",
            query_vector_cache_ttl_seconds=120.0,
        )
        eng2 = RetrievalEngine(
            self.store,
            VisibilityPolicy(),
            embedding_enabled=True,
            embedding_provider=shared_provider,
            embedding_provider_id="shared-p",
            query_vector_cache_ttl_seconds=120.0,
        )
        eng_other = RetrievalEngine(
            self.store,
            VisibilityPolicy(),
            embedding_enabled=True,
            embedding_provider=other_provider,
            embedding_provider_id="shared-p",
            query_vector_cache_ttl_seconds=120.0,
        )

        v1 = asyncio.run(eng1._call_embedding_provider("周末去吃拉面吗"))
        v2 = asyncio.run(eng2._call_embedding_provider("周末去吃拉面吗"))
        v3 = asyncio.run(eng_other._call_embedding_provider("周末去吃拉面吗"))
        self.assertEqual(v1, v2)
        self.assertEqual(1, shared_provider.get_embedding.await_count)
        self.assertEqual([0.0, 1.0], v3)
        self.assertEqual(1, other_provider.get_embedding.await_count)


class FtsMigrationIndexEqpAndLockFreeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_legacy_fts_migrates_to_contentless_rowid_and_supports_update_delete(self) -> None:
        db_path = self.tmp_dir / "legacy_fts.db"
        store = MemoryStore(db_path)
        store.initialize()
        rec1 = _make_record("fts-1", content="量子计算与超导芯片实验")
        rec2 = _make_record("fts-2", content="周末去杭州西湖骑行")
        store._insert_memory_sync(rec1)
        store._insert_memory_sync(rec2)

        # Simulate a legacy database with old memory_id UNINDEXED FTS schema and idx_memories_content
        with store._lock, store._conn:
            raw1 = store._conn.execute("SELECT * FROM memories WHERE id=?", (rec1.id,)).fetchone()
            raw2 = store._conn.execute("SELECT * FROM memories WHERE id=?", (rec2.id,)).fetchone()
            fts_text1 = store._memory_fts_text(raw1)
            fts_text2 = store._memory_fts_text(raw2)
            store._conn.execute("DROP TABLE memory_fts")
            store._conn.execute(
                "CREATE VIRTUAL TABLE memory_fts USING fts5(memory_id UNINDEXED, search_text, tokenize='unicode61')"
            )
            store._conn.execute(
                "INSERT INTO memory_fts(memory_id, search_text) VALUES (?, ?), (?, ?)",
                (rec1.id, fts_text1, rec2.id, fts_text2),
            )
            store._conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_content ON memories(content)")
            store._conn.execute("DELETE FROM schema_metadata WHERE key='memory_fts_schema_version'")
        store.close()

        # Verify read_only=True can still read legacy memory_id FTS without mutating schema
        ro_store = MemoryStore(db_path, read_only=True)
        ro_store.initialize()
        try:
            self.assertFalse(ro_store._fts_uses_rowid)
            conn, lock = ro_store._read_connection_for_bundle()
            with lock:
                hits = ro_store._fts_candidate_rows(conn, ["量子计算"], 10, False)
            self.assertEqual(["fts-1"], [r["id"] for r in hits])
        finally:
            ro_store.close()

        # Normal writable open migrates to contentless rowid FTS5 and drops idx_memories_content
        migrated = MemoryStore(db_path)
        migrated.initialize()
        try:
            self.assertTrue(migrated._fts_uses_rowid)
            tables = {
                r[0]
                for r in migrated._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertNotIn("memory_fts_content", tables)
            indexes = {
                r[0]
                for r in migrated._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            self.assertNotIn("idx_memories_content", indexes)
            self.assertIn("idx_emotion_events_session_only", indexes)
            self.assertIn("idx_emotion_events_session", indexes)

            conn, lock = migrated._read_connection_for_bundle()
            with lock:
                self.assertEqual(["fts-1"], [r["id"] for r in migrated._fts_candidate_rows(conn, ["量子计算"], 10, False)])
                self.assertEqual(["fts-2"], [r["id"] for r in migrated._fts_candidate_rows(conn, ["西湖"], 10, False)])

            # Update record via rowid: old term gone, new term searchable
            rec1.content = "神经网络编译优化器"
            migrated._insert_memory_sync(rec1)
            with lock:
                self.assertEqual([], migrated._fts_candidate_rows(conn, ["量子计算"], 10, False))
                self.assertEqual(["fts-1"], [r["id"] for r in migrated._fts_candidate_rows(conn, ["神经网络"], 10, False)])

            # Delete record via rowid: gone from FTS
            migrated._delete_memory_sync(rec1.id)
            with lock:
                self.assertEqual([], migrated._fts_candidate_rows(conn, ["神经网络"], 10, False))
        finally:
            migrated.close()

    async def test_explain_query_plan_hits_timeline_indexes_without_temp_btree_and_trgm_union(self) -> None:
        store = MemoryStore(self.tmp_dir / "eqp.db")
        store.initialize()
        try:
            for idx in range(25):
                await store.add_timeline_event(
                    event_type="user_message",
                    session_id="qq:GroupMessage:g1",
                    scope="group",
                    subject_id="u1",
                    object_id="g1",
                    content=f"消息 {idx}",
                    metadata={"owner_bot_id": "b1"},
                )
            event_time_sql = store_mod._timeline_time_sql()
            for col, expected_idx in (
                ("subject_id", "idx_timeline_subject_event_time"),
                ("object_id", "idx_timeline_object_event_time"),
            ):
                plan = " | ".join(
                    str(row[3])
                    for row in store._conn.execute(
                        f"""EXPLAIN QUERY PLAN
                            SELECT * FROM timeline
                            WHERE scope='group' AND session_id='qq:GroupMessage:g1' AND {col}='g1'
                            ORDER BY {event_time_sql} DESC, created_at DESC, id DESC
                            LIMIT 20"""
                    ).fetchall()
                )
                self.assertIn(expected_idx, plan)
                self.assertNotIn("TEMP B-TREE", plan.upper())

            indexes = {
                r[0]
                for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            }
            for required_idx in (
                "idx_timeline_subject_event_time",
                "idx_timeline_object_event_time",
                "idx_timeline_cross_window_subject",
                "idx_timeline_unsummarized",
                "idx_memories_type_lifecycle",
                "idx_knowledge_nodes_updated",
                "idx_emotion_events_session_only",
            ):
                self.assertIn(required_idx, indexes)

            # Mixed 2-char CJK + 3-char terms in related_knowledge_terms UNION query
            n_cat = await store.upsert_knowledge_node(node_type="topic", label="猫猫")
            n_fish = await store.upsert_knowledge_node(node_type="topic", label="小鱼干")
            n_wukong = await store.upsert_knowledge_node(node_type="topic", label="黑神话悟空")
            n_staff = await store.upsert_knowledge_node(node_type="topic", label="金箍棒")
            await store.upsert_knowledge_edge(
                source_node_id=n_cat,
                target_node_id=n_fish,
                relation_type="related_to",
            )
            await store.upsert_knowledge_edge(
                source_node_id=n_wukong,
                target_node_id=n_staff,
                relation_type="related_to",
            )
            related = await store.related_knowledge_terms(["猫猫", "黑神话"], limit=10)
            self.assertIn("小鱼干", related)
            self.assertIn("金箍棒", related)
        finally:
            store.close()

    def test_memory_adaptive_pragmas_on_main_and_read_connections(self) -> None:
        with patch.object(store_mod, "_detect_total_memory_mb", return_value=1024):
            low_store = MemoryStore(self.tmp_dir / "low_ram.db")
            low_store.initialize()
            try:
                self.assertEqual(-8192, low_store._conn.execute("PRAGMA cache_size").fetchone()[0])
                self.assertEqual(2, low_store._conn.execute("PRAGMA temp_store").fetchone()[0])
                self.assertEqual(0, low_store._conn.execute("PRAGMA mmap_size").fetchone()[0])
                rconn, _ = low_store._timeline_read_connection()
                self.assertEqual(-8192, rconn.execute("PRAGMA cache_size").fetchone()[0])
                self.assertEqual(0, rconn.execute("PRAGMA mmap_size").fetchone()[0])
            finally:
                low_store.close()

        with patch.object(store_mod, "_detect_total_memory_mb", return_value=16384):
            hi_store = MemoryStore(self.tmp_dir / "hi_ram.db")
            hi_store.initialize()
            try:
                self.assertEqual(-16384, hi_store._conn.execute("PRAGMA cache_size").fetchone()[0])
                self.assertEqual(2, hi_store._conn.execute("PRAGMA temp_store").fetchone()[0])
                self.assertEqual(67108864, hi_store._conn.execute("PRAGMA mmap_size").fetchone()[0])
            finally:
                hi_store.close()

    async def test_read_pool_endpoints_do_not_block_on_main_write_lock(self) -> None:
        store = MemoryStore(self.tmp_dir / "lockfree.db")
        store.initialize()
        try:
            rec = _make_record(
                "lf-1",
                content="无锁并发读验证",
                memory_type="schedule_fragment",
                scope="bot_self",
                visibility="bot_self",
            )
            rec_grp = _make_record("lf-grp", content="群聊桶测试")
            await store.insert_memory(rec)
            await store.insert_memory(rec_grp)
            await store.upsert_identity(
                platform="qq",
                entity=EntityRef(kind="user", id="u1", name="阿明"),
            )

            lock_acquired = threading.Event()
            release_lock = threading.Event()

            def _hold_write_lock() -> None:
                with store._lock:
                    lock_acquired.set()
                    release_lock.wait(timeout=5.0)

            holder = threading.Thread(target=_hold_write_lock, daemon=True)
            holder.start()
            self.assertTrue(lock_acquired.wait(timeout=2.0))
            try:
                # Every read endpoint below must finish promptly while store._lock is held!
                results = await asyncio.wait_for(
                    asyncio.gather(
                        store.stats(),
                        store.owner_bot_counts(),
                        store.list_memory_buckets(),
                        store.list_person_cards(),
                        store.summary_recovery_sessions(),
                        store.summary_progress(),
                        store.summary_status_snapshot(max_events=10),
                        store.list_schedule_context_memories(bot_id="b1", limit=5),
                        store.scan_memories_missing_embeddings(provider_id="test", limit=10),
                        store.database_health_snapshot(),
                    ),
                    timeout=3.0,
                )
                stats, owners, buckets, _people, _rec_sess, _prog, _snap, sched, _missing, health = results
                self.assertEqual(2, stats["total_memories"])
                self.assertEqual(2, owners.get("b1"))
                self.assertTrue(buckets)
                self.assertEqual(["lf-1"], [m.id for m in sched])
                self.assertEqual("contentless-rowid-v2", health["fts_schema_version"])
                self.assertEqual(2, health["auto_vacuum"])
            finally:
                release_lock.set()
                holder.join(timeout=2.0)
        finally:
            store.close()

    async def test_injection_log_blocked_reasons_compact_and_drop_full_content(self) -> None:
        store = MemoryStore(self.tmp_dir / "logs.db")
        store.initialize()
        try:
            huge_blocked = [
                {
                    "id": f"m-{i}",
                    "reason": "visibility_denied",
                    "content": "超大完整正文内容不应该落盘" * 50,
                    "memory_type": "fact",
                    "scope": "group",
                    "slot": "relevant",
                }
                for i in range(40)
            ]
            await store.add_injection_log(
                session_id="s1",
                scope="group",
                query="测试查询",
                selected_memory_ids=["m-0"],
                blocked_reasons=huge_blocked,
                injection_chars=120,
            )
            raw = store._conn.execute("SELECT blocked_reasons FROM injection_logs LIMIT 1").fetchone()[0]
            parsed = json.loads(raw)
            self.assertLessEqual(len(parsed), 30)
            self.assertNotIn("超大完整正文内容", raw)
            self.assertEqual("m-0", parsed[0]["id"])
            self.assertEqual("visibility_denied", parsed[0]["reason"])
            self.assertNotIn("content", parsed[0])
        finally:
            store.close()


class ServiceScopedAndApiPerfTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_scoped_store_wal_normal_prune_and_async_off_loop_bridge(self) -> None:
        db_path = self.tmp_dir / "req041_scoped.db"
        scoped = ScopedStore(db_path)
        try:
            with scoped._connection() as sconn:
                self.assertEqual("wal", sconn.execute("PRAGMA journal_mode").fetchone()[0].lower())
                self.assertEqual(1, sconn.execute("PRAGMA synchronous").fetchone()[0])
                self.assertEqual(2, sconn.execute("PRAGMA auto_vacuum").fetchone()[0])
                indexes = {
                    r[0]
                    for r in sconn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
                }
                self.assertIn("idx_scoped_operations_created", indexes)

                # Insert old and recent scoped_operations and verify TTL pruning
                old_ts = time.time() - 45 * 86400.0
                new_ts = time.time()
                with scoped._lock, sconn:
                    sconn.execute(
                        """INSERT INTO scoped_operations(
                               event_id, migration_epoch, request_hash, result_code, created_at
                           ) VALUES
                           ('ev-old', 'ep1', 'h1', 'ok', ?),
                           ('ev-new', 'ep1', 'h2', 'ok', ?)""",
                        (old_ts, new_ts),
                    )
            pruned = scoped.prune_expired_operations(older_than_seconds=30 * 86400.0, limit=100)
            self.assertEqual(1, pruned["deleted_operations"])
            with scoped._connection() as sconn:
                remaining = [
                    r[0]
                    for r in sconn.execute("SELECT event_id FROM scoped_operations").fetchall()
                ]
            self.assertEqual(["ev-new"], remaining)
            health = scoped.health_snapshot()
            self.assertEqual("wal", health["journal_mode"])
            self.assertEqual(1, health["scoped_operations"])

            # Verify async bridge methods run off the event loop thread
            loop_tid = threading.get_ident()
            worker_tids: list[int] = []
            fake_service = SimpleNamespace(scoped_store=scoped, config=ConfigView({}))
            bridge = MemoryCompanionBridge(fake_service)
            orig_sync = bridge.list_scoped_records

            def _tracked_sync(*args, **kwargs):
                worker_tids.append(threading.get_ident())
                return orig_sync(*args, **kwargs)

            bridge.list_scoped_records = _tracked_sync
            await bridge.list_scoped_records_async(
                capability=None,
                namespace=None,
                record_kind="note",
                limit=10,
            )
            self.assertEqual(1, len(worker_tids))
            self.assertNotEqual(loop_tid, worker_tids[0])
        finally:
            scoped.close()

    async def test_turn_timeline_cache_warmup_grace_token_usage_cap_and_db_api(self) -> None:
        cfg = {
            "startup": {"background_grace_seconds": 45},
            "retrieval": {"embedding_enabled": True, "embedding_provider_id": "test"},
            "retrieval_advanced": {
                "vector_precision": "float16",
                "startup_vector_warmup_enabled": True,
            },
            "memory_injection": {"enabled": True},
        }
        service = MemoryCompanionService(
            context=SimpleNamespace(),
            config=cfg,
            plugin_root=ROOT,
            data_dir=self.tmp_dir,
        )
        try:
            # 1. vector_precision synced to store on init
            self.assertEqual("float16", service.store.vector_storage_precision)

            # 2. schedule_startup_vector_warmup respects startup.background_grace_seconds when unset
            recorded_settle: list[float] = []
            with patch.object(
                service.store,
                "schedule_startup_vector_corpus_warmup",
                side_effect=lambda **kw: recorded_settle.append(kw["settle_seconds"]) or True,
            ):
                self.assertTrue(service.schedule_startup_vector_warmup())
                self.assertTrue(service.schedule_startup_vector_warmup(settle_seconds=0.0))
            self.assertGreater(recorded_settle[0], 30.0)
            self.assertEqual(0.0, recorded_settle[1])

            # 3. Single-turn recent_timeline sharing inside inject_memories / handle_llm_request
            ctx = SessionContext(
                scope="private",
                platform="qq",
                user_id="u1",
                bot_id="b1",
                persona_id="p1",
                session_id="qq:FriendMessage:u1",
                message_text="对了，刚才那件事继续聊",
            )
            await service.store.add_timeline_event(
                event_type="user_message",
                session_id=ctx.session_id,
                scope=ctx.scope,
                subject_id=ctx.user_id,
                object_id=ctx.user_id,
                content="上次我们聊到了东京旅行计划",
                metadata={"owner_bot_id": ctx.bot_id},
            )
            orig_recent = service.store.recent_timeline
            calls: list[tuple] = []

            async def _spy_recent(*args, **kwargs):
                calls.append((args, kwargs))
                return await orig_recent(*args, **kwargs)

            with patch.object(service.store, "recent_timeline", side_effect=_spy_recent):
                req = SimpleNamespace(contexts=[], system_prompt="", prompt="")
                await service.inject_memories(ctx, req)
            # Multiple consumers (_recent_fact_guard_context + topic_shift_guard + followup) share 1-2 reads max,
            # and calling _recent_timeline_cached twice in the same turn executes only 1 DB call.
            calls.clear()
            from astrbot_plugin_memory_companion.core.service import _TURN_TIMELINE_CACHE

            tok = _TURN_TIMELINE_CACHE.set({})
            try:
                with patch.object(service.store, "recent_timeline", side_effect=_spy_recent):
                    r1 = await service._recent_timeline_cached(
                        limit=6, scope=ctx.scope, session_id=ctx.session_id, entity_id=ctx.user_id,
                    )
                    r2 = await service._recent_timeline_cached(
                        limit=1, scope=ctx.scope, session_id=ctx.session_id, entity_id=ctx.user_id,
                    )
                    r3 = await service._recent_timeline_cached(
                        limit=12, scope=ctx.scope, session_id=ctx.session_id, entity_id=ctx.user_id,
                        bot_id=ctx.bot_id,
                    )
                self.assertEqual(1, len(calls))
                self.assertEqual(1, len(r1))
                self.assertEqual(1, len(r2))
                self.assertEqual(1, len(r3))
            finally:
                _TURN_TIMELINE_CACHE.reset(tok)

            # 4. Bounded token_usage by_hour (<= 336) and compact JSON
            big_by_hour = {
                f"2026-01-{(i // 24) + 1:02d}T{i % 24:02d}:00": {"calls": 1, "total_tokens": 10}
                for i in range(500)
            }
            normalized = service._normalize_token_usage({"by_hour": dict(big_by_hour)})
            self.assertEqual(336, len(normalized["by_hour"]))
            self.assertIn(sorted(big_by_hour.keys())[-1], normalized["by_hour"])
            self.assertNotIn(sorted(big_by_hour.keys())[0], normalized["by_hour"])

            # 5. One-click db_health & db_optimize API endpoints + admin guard
            fake_plugin = SimpleNamespace(
                service=service,
                context=SimpleNamespace(),
            )
            api = PluginPageApi(fake_plugin)
            api._ok = lambda payload=None, status=200: (status, {"status": "ok", **(payload or {})})
            api._err = lambda msg, status=400: (status, {"status": "error", "message": msg})
            api._admin_required_response = lambda: (403, {"status": "error", "code": "admin_required"})

            api._is_bound_dashboard_admin = lambda: False
            api._dashboard_admin_state = lambda: "denied"
            self.assertEqual(403, (await api.db_health())[0])
            self.assertEqual(403, (await api.db_optimize())[0])

            api._is_bound_dashboard_admin = lambda: True
            api._dashboard_admin_state = lambda: "allowed"
            api._json = AsyncMock(return_value={"target_precision": "float16", "transcode_limit": 100})
            h_status, h_body = await api.db_health()
            self.assertEqual(200, h_status)
            self.assertEqual("float16", h_body["health"]["configured_vector_precision"])
            self.assertEqual("contentless-rowid-v2", h_body["health"]["primary"]["fts_schema_version"])

            o_status, o_body = await api.db_optimize()
            self.assertEqual(200, o_status)
            self.assertTrue(o_body["data"]["ok"])
            self.assertEqual("float16", o_body["data"]["target_precision"])
            self.assertNotIn("error", o_body["data"]["scoped_prune"])
            self.assertNotIn("error", o_body["data"]["capture_prune"])
        finally:
            service.close()

    async def test_transcode_limit_zero_skips_transcoding_and_sleep_maintenance_is_bounded(self) -> None:
        dim = 16
        service = MemoryCompanionService(
            context=SimpleNamespace(),
            config={"retrieval_advanced": {"vector_precision": "float16"}},
            plugin_root=ROOT,
            data_dir=self.tmp_dir,
        )
        try:
            now = datetime.now(timezone.utc).isoformat()
            vec = [0.25] * dim
            raw_f64 = struct.pack(f"<{dim}d", *vec)
            for idx in range(8):
                rec = _make_record(f"tc-{idx}", content=f"转码边界记录 {idx}")
                service.store._insert_memory_sync(rec)
                with service.store._lock, service.store._conn:
                    service.store._conn.execute(
                        """INSERT INTO memory_embeddings(
                               memory_id, provider_id, text_hash, dimension, vector, created_at, updated_at
                           ) VALUES (?, 'test', ?, ?, ?, ?, ?)""",
                        (rec.id, memory_embedding_text_hash(rec, max_chars=1200), dim, raw_f64, now, now),
                    )

            # max_rows=0 must transcode 0 rows (not unlimited).
            zero_res = await service.store.transcode_memory_embeddings(
                target_precision="float16", max_rows=0, purge_archived_orphans=False
            )
            self.assertEqual(0, zero_res["transcoded"])
            f64_count = service.store._conn.execute(
                "SELECT COUNT(*) FROM memory_embeddings WHERE length(vector)=?", (dim * 8,)
            ).fetchone()[0]
            self.assertEqual(8, f64_count)

            # max_rows=3 must transcode strictly 3 rows.
            bounded_res = await service.store.transcode_memory_embeddings(
                target_precision="float16", max_rows=3, purge_archived_orphans=False
            )
            self.assertEqual(3, bounded_res["transcoded"])
            f64_after_3 = service.store._conn.execute(
                "SELECT COUNT(*) FROM memory_embeddings WHERE length(vector)=?", (dim * 8,)
            ).fetchone()[0]
            self.assertEqual(5, f64_after_3)

            # optimize_and_shrink(transcode_limit=0) must skip transcoding completely.
            skip_opt = await service.store.optimize_and_shrink(
                target_precision="float16", transcode_limit=0, run_full_vacuum=False
            )
            self.assertTrue(skip_opt["transcode"]["skipped"])
            self.assertEqual(0, skip_opt["transcode"]["transcoded"])
            self.assertEqual(
                5,
                service.store._conn.execute(
                    "SELECT COUNT(*) FROM memory_embeddings WHERE length(vector)=?", (dim * 8,)
                ).fetchone()[0],
            )

            # POST /maintenance/db_optimize with transcode_limit=0 must also skip transcoding.
            api = PluginPageApi(SimpleNamespace(service=service, context=SimpleNamespace()))
            api._ok = lambda payload=None, status=200: (status, {"status": "ok", **(payload or {})})
            api._err = lambda msg, status=400: (status, {"status": "error", "message": msg})
            api._dashboard_admin_state = lambda: "allowed"
            api._json = AsyncMock(return_value={"target_precision": "float16", "transcode_limit": 0})
            status, body = await api.db_optimize()
            self.assertEqual(200, status)
            self.assertTrue(body["data"]["primary"]["transcode"]["skipped"])
            self.assertEqual(0, body["data"]["primary"]["transcode"]["transcoded"])
            self.assertEqual(
                5,
                service.store._conn.execute(
                    "SELECT COUNT(*) FROM memory_embeddings WHERE length(vector)=?", (dim * 8,)
                ).fetchone()[0],
            )

            # sleep_maintenance must NOT perform a second unbounded transcode via optimize_and_shrink(transcode_limit=0).
            orig_transcode = service.store.transcode_memory_embeddings
            transcode_calls: list[int | None] = []

            async def _capped_transcode(*args, **kwargs):
                transcode_calls.append(kwargs.get("max_rows"))
                kwargs["max_rows"] = 2
                return await orig_transcode(*args, **kwargs)

            with patch.object(service.store, "transcode_memory_embeddings", side_effect=_capped_transcode):
                sleep_state = await service.sleep_maintenance(reason="scheduled_natural_forgetting")
            self.assertEqual([5000], transcode_calls)
            self.assertEqual(2, sleep_state["embedding_transcode"]["transcoded"])
            self.assertTrue(sleep_state["db_optimize"]["transcode"]["skipped"])
            # 5 - 2 = 3 legacy float64 rows remain untouched (proving optimize_and_shrink didn't transcode them).
            self.assertEqual(
                3,
                service.store._conn.execute(
                    "SELECT COUNT(*) FROM memory_embeddings WHERE length(vector)=?", (dim * 8,)
                ).fetchone()[0],
            )
        finally:
            service.close()

    async def test_concurrent_initialize_database_single_flight_capture_runtime(self) -> None:
        from astrbot_plugin_memory_companion.core import capture_runtime as cr_mod

        service = MemoryCompanionService(
            context=SimpleNamespace(),
            config={},
            plugin_root=ROOT,
            data_dir=self.tmp_dir,
            defer_database_initialization=True,
        )
        orig_init = cr_mod.CaptureRuntime.__init__
        init_count = 0
        init_lock = threading.Lock()

        def _slow_capture_init(cap_self, svc):
            nonlocal init_count
            with init_lock:
                init_count += 1
            time.sleep(0.05)
            orig_init(cap_self, svc)

        try:
            with patch.object(cr_mod.CaptureRuntime, "__init__", _slow_capture_init):
                results = await asyncio.gather(*(service.initialize_database() for _ in range(6)))
            self.assertEqual([True] * 6, results)
            self.assertEqual(1, init_count)
            self.assertIsNotNone(service.capture)
            # Active generation in DB must match service.capture.generation (fence must not raise).
            service.capture.store.fence(service.capture.generation, lambda: True)
        finally:
            service.close()

    async def test_knowledge_revision_invalidates_retrieval_result_cache_without_invalidating_vector_cache(self) -> None:
        service = MemoryCompanionService(
            context=SimpleNamespace(),
            config={
                "knowledge_graph": {"retrieval_expansion_enabled": True},
                "retrieval": {"embedding_enabled": True, "embedding_provider_id": "test"},
            },
            plugin_root=ROOT,
            data_dir=self.tmp_dir,
        )
        try:
            rec = _make_record("kg-vec-1", content="京都抹茶甜品店攻略")
            await service.store.insert_memory(rec)
            await service.store.upsert_memory_embedding(
                memory_id=rec.id,
                provider_id="test",
                text_hash=memory_embedding_text_hash(rec, max_chars=1200),
                vector=[1.0, 0.0, 0.0, 0.0],
            )
            ctx = SessionContext(
                scope="group",
                platform="qq",
                user_id="u1",
                group_id="g1",
                bot_id="b1",
                persona_id="p1",
                session_id="qq:GroupMessage:g1",
            )
            provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0, 0.0, 0.0]))
            engine = RetrievalEngine(
                service.store,
                VisibilityPolicy(),
                embedding_enabled=True,
                embedding_provider=provider,
                embedding_provider_id="test",
                embedding_top_k=4,
                embedding_score_threshold=-1.0,
                knowledge_graph_enabled=True,
            )
            _m1, _s1, info1 = await engine._embedding_candidate_memories("甜品", ctx, include_pending=False)
            self.assertFalse(info1["embedding_cache_hit"])

            key_kg_on_before = await service._retrieval_cache_key("search", "甜品", ctx, 6)
            service.config.raw["knowledge_graph"]["retrieval_expansion_enabled"] = False
            key_kg_off_before = await service._retrieval_cache_key("search", "甜品", ctx, 6)
            service.config.raw["knowledge_graph"]["retrieval_expansion_enabled"] = True

            # Write to knowledge graph -> invalidates retrieval result cache when KG is on, NOT vector cache!
            await service.store.upsert_knowledge_node(node_type="topic", label="宇治抹茶")

            key_kg_on_after = await service._retrieval_cache_key("search", "甜品", ctx, 6)
            service.config.raw["knowledge_graph"]["retrieval_expansion_enabled"] = False
            key_kg_off_after = await service._retrieval_cache_key("search", "甜品", ctx, 6)

            self.assertNotEqual(key_kg_on_before, key_kg_on_after)
            self.assertEqual(key_kg_off_before, key_kg_off_after)

            _m2, _s2, info2 = await engine._embedding_candidate_memories("甜品", ctx, include_pending=False)
            self.assertTrue(info2["embedding_cache_hit"])
            self.assertEqual(0, info2["embedding_scanned_rows"])
        finally:
            service.close()

    async def test_db_optimize_precision_override_does_not_mutate_store_precision_and_reports_notice(self) -> None:
        dim = 16
        service = MemoryCompanionService(
            context=SimpleNamespace(),
            config={"retrieval_advanced": {"vector_precision": "float32"}},
            plugin_root=ROOT,
            data_dir=self.tmp_dir,
        )
        try:
            rec = _make_record("ov-1", content="精度覆写边界测试")
            service.store._insert_memory_sync(rec)
            now = datetime.now(timezone.utc).isoformat()
            with service.store._lock, service.store._conn:
                service.store._conn.execute(
                    """INSERT INTO memory_embeddings(
                           memory_id, provider_id, text_hash, dimension, vector, created_at, updated_at
                       ) VALUES (?, 'test', ?, ?, ?, ?, ?)""",
                    (
                        rec.id,
                        memory_embedding_text_hash(rec, max_chars=1200),
                        dim,
                        struct.pack(f"<{dim}d", *([0.5] * dim)),
                        now,
                        now,
                    ),
                )
            self.assertEqual("float32", service.store.vector_storage_precision)

            result = await service.optimize_and_shrink_database(
                target_precision="float16",
                transcode_limit=10,
                run_full_vacuum=False,
            )
            self.assertEqual("float32", service.store.vector_storage_precision)
            self.assertEqual("float16", result["target_precision"])
            self.assertEqual("float32", result["configured_vector_precision"])
            self.assertTrue(result["precision_override_temporary"])
            self.assertIn("float16", result["notice"])
            self.assertIn("float32", result["notice"])
            self.assertEqual("float32", result["health"]["primary"]["vector_precision"])
            self.assertEqual(1, result["primary"]["transcode"]["transcoded"])
            blob_len = service.store._conn.execute(
                "SELECT length(vector) FROM memory_embeddings WHERE memory_id='ov-1'"
            ).fetchone()[0]
            self.assertEqual(dim * 2, blob_len)
        finally:
            service.close()

    async def test_full_vacuum_checks_rowid_bounds_and_rebuilds_fts_if_shifted(self) -> None:
        store = MemoryStore(self.tmp_dir / "vacuum_fts.db")
        store.initialize()
        try:
            rec = _make_record("vac-1", content="海风与咖啡香的下午")
            await store.insert_memory(rec)
            await store.add_timeline_event(
                event_type="user_message",
                session_id="qq:GroupMessage:g1",
                scope="group",
                subject_id="u1",
                object_id="g1",
                content="下午茶讨论海风咖啡馆",
                metadata={"owner_bot_id": "b1"},
            )
            # Normal VACUUM when implicit rowids don't shift: fts_rebuilt is empty and FTS still works.
            res_normal = await store.optimize_and_shrink(transcode_limit=0, run_full_vacuum=True)
            self.assertEqual("full_vacuum_incremental_enabled", res_normal["vacuum_mode"])
            self.assertEqual([], res_normal["fts_rebuilt"])
            conn, lock = store._read_connection_for_bundle()
            with lock:
                self.assertEqual(["vac-1"], [r["id"] for r in store._fts_candidate_rows(conn, ["咖啡香"], 10, False)])

            # Simulate a SQLite build where VACUUM shifts implicit rowids -> both FTS tables rebuild automatically.
            orig_bounds = store._table_rowid_bounds_sync
            call_counts: dict[str, int] = {}

            def _shifted_bounds(table: str):
                call_counts[table] = call_counts.get(table, 0) + 1
                cnt, lo, hi = orig_bounds(table)
                if call_counts[table] >= 2 and lo is not None and hi is not None:
                    return (cnt, lo + 100, hi + 100)
                return (cnt, lo, hi)

            with patch.object(store, "_table_rowid_bounds_sync", side_effect=_shifted_bounds):
                res_shifted = await store.optimize_and_shrink(transcode_limit=0, run_full_vacuum=True)
            self.assertIn("memory_fts", res_shifted["fts_rebuilt"])
            if store._source_fts_enabled:
                self.assertIn("timeline_source_fts", res_shifted["fts_rebuilt"])
            with lock:
                self.assertEqual(["vac-1"], [r["id"] for r in store._fts_candidate_rows(conn, ["咖啡香"], 10, False)])
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
