"""Perf3 regression tests: incremental row cache, cross-revision vector reuse,
time-intent snapshot sharing, hot-path helpers, lock-free revision reads, and
ReplyChain RPC budget exemption."""

from __future__ import annotations

import asyncio
from collections import UserDict
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sqlite3
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import (
    memory_lifecycle,
    profile_quality,
    retrieval as retrieval_mod,
    vector_search,
)
from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.latency import await_with_memory_hook_budget
from astrbot_plugin_memory_companion.core.memory_atom import row_value
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
    clean_text,
    memory_embedding_text_hash,
)
from astrbot_plugin_memory_companion.core.reply_chain import ReplyChainResolver
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.source_capture import SourceCapture
from astrbot_plugin_memory_companion.core.store import MemoryStore, _pack_embedding_vector
from astrbot_plugin_memory_companion.core.time_intent import TimeIntent
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def _make_record(
    memory_id: str,
    *,
    content: str = "",
    scope: str = "group",
    session_id: str = "onebot_qq:GroupMessage:g1",
    group_id: str = "g1",
    visibility: str = "group_public",
    occurred_at: str = "2026-11-18T02:00:00+00:00",
    updated_at: str = "2026-11-18T02:00:00+00:00",
    created_at: str = "2026-11-18T02:00:00+00:00",
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> MemoryRecord:
    meta = {"persona_id": "p1"}
    if metadata:
        meta.update(metadata)
    return MemoryRecord(
        id=memory_id,
        memory_type="conversation_summary",
        subject=EntityRef(kind="user", id="u1"),
        object=EntityRef.bot_self("b1"),
        owner_bot_id="b1",
        scope=scope,
        platform="qq",
        session_id=session_id,
        group_id=group_id,
        visibility=visibility,
        lifecycle="stable_memory",
        content=content or f"群聊记录内容 {memory_id}",
        metadata=meta,
        tags=tags or ["group_tag"],
        importance=0.4,
        occurred_at=occurred_at,
        created_at=created_at,
        updated_at=updated_at,
    ).ensure_defaults()


class IncrementalRowCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    def test_row_value_handles_dict_sqlite_row_mapping_and_none(self) -> None:
        self.assertEqual("fallback", row_value(None, "id", "fallback"))
        self.assertEqual("v1", row_value({"id": "v1"}, "id", "fallback"))
        self.assertEqual("fallback", row_value({"id": "v1"}, "missing", "fallback"))
        self.assertEqual("mv", row_value(UserDict({"id": "mv"}), "id", "fallback"))
        self.assertEqual("fallback", row_value(UserDict({"id": "mv"}), "missing", "fallback"))

        rec = _make_record("rv-1")
        self.store._insert_memory_sync(rec)
        row = self.store._conn.execute("SELECT * FROM memories WHERE id='rv-1'").fetchone()
        self.assertEqual("rv-1", row_value(row, "id", ""))
        self.assertEqual("fallback", row_value(row, "nonexistent_col", "fallback"))

    def test_incremental_cache_survives_revision_bump_and_copy_false_isolates_callers(self) -> None:
        rec1 = _make_record("inc-1", content="第一条群聊记录", metadata={"k": "v1"}, tags=["t1"])
        rec2 = _make_record("inc-2", content="第二条群聊记录", metadata={"k": "v2"}, tags=["t2"])
        self.store._insert_memory_sync(rec1)
        self.store._insert_memory_sync(rec2)

        rev1 = self.store._memory_revision_sync()
        rows1 = {
            r["id"]: r
            for r in self.store._conn.execute("SELECT * FROM memories").fetchall()
        }

        with patch.object(
            MemoryRecord, "from_row_light", wraps=MemoryRecord.from_row_light
        ) as spy_parse:
            ro_1 = self.store._cached_from_row_light(rows1["inc-1"], revision=rev1, copy=False)
            ro_2 = self.store._cached_from_row_light(rows1["inc-2"], revision=rev1, copy=False)
            self.assertEqual(2, spy_parse.call_count)
            self.assertIs(
                ro_1,
                self.store._cached_from_row_light(rows1["inc-1"], revision=rev1, copy=False),
            )
            self.assertEqual(2, spy_parse.call_count)

            # Mutating a copy=True result must never pollute the cached template or copy=False views.
            rw_1 = self.store._cached_from_row_light(rows1["inc-1"], revision=rev1, copy=True)
            rw_1.metadata["mutated"] = True
            rw_1.tags.append("bad_tag")
            self.assertNotIn("mutated", ro_1.metadata)
            self.assertEqual(["t1"], ro_1.tags)

            # Update ONLY inc-2 in SQLite (without changing updated_at) -> bumps revision.
            self.store._conn.execute(
                "UPDATE memories SET content='第二条已更新' WHERE id='inc-2'"
            )
            self.store._conn.commit()
            rev2 = self.store._memory_revision_sync()
            self.assertNotEqual(rev1, rev2)

            rows2 = {
                r["id"]: r
                for r in self.store._conn.execute("SELECT * FROM memories").fetchall()
            }
            ro_1_after = self.store._cached_from_row_light(rows2["inc-1"], revision=rev2, copy=False)
            ro_2_after = self.store._cached_from_row_light(rows2["inc-2"], revision=rev2, copy=False)

            # inc-1 must reuse its cached template without re-parsing; inc-2 must detect content change and re-parse.
            self.assertIs(ro_1, ro_1_after)
            self.assertEqual("第二条已更新", ro_2_after.content)
            self.assertEqual(3, spy_parse.call_count)

    def test_cached_embedding_text_hash_memoizes_per_max_chars_and_invalidates_on_update(self) -> None:
        rec = _make_record("hash-1", content="甲" * 400, metadata={"canonical_summary": "乙" * 400})
        self.store._insert_memory_sync(rec)
        rev1 = self.store._memory_revision_sync()
        row1 = self.store._conn.execute("SELECT * FROM memories WHERE id='hash-1'").fetchone()

        mem1 = self.store._cached_from_row_light(row1, revision=rev1, copy=False)
        expected_1200 = memory_embedding_text_hash(mem1, max_chars=1200)
        expected_300 = memory_embedding_text_hash(mem1, max_chars=300)
        self.assertNotEqual(expected_1200, expected_300)

        with patch(
            "astrbot_plugin_memory_companion.core.store.memory_embedding_text_hash",
            wraps=memory_embedding_text_hash,
        ) as spy_hash:
            h1 = self.store._cached_embedding_text_hash(mem1, max_chars=1200, revision=rev1)
            h2 = self.store._cached_embedding_text_hash(mem1, max_chars=1200, revision=rev1)
            h3 = self.store._cached_embedding_text_hash(mem1, max_chars=300, revision=rev1)
            h4 = self.store._cached_embedding_text_hash(mem1, max_chars=300, revision=rev1)
            self.assertEqual(expected_1200, h1)
            self.assertEqual(expected_1200, h2)
            self.assertEqual(expected_300, h3)
            self.assertEqual(expected_300, h4)
            self.assertEqual(2, spy_hash.call_count)

        # Updating content creates a fresh cache entry without stale hashes.
        self.store._conn.execute("UPDATE memories SET content='丙' WHERE id='hash-1'")
        self.store._conn.commit()
        rev2 = self.store._memory_revision_sync()
        row2 = self.store._conn.execute("SELECT * FROM memories WHERE id='hash-1'").fetchone()
        mem2 = self.store._cached_from_row_light(row2, revision=rev2, copy=False)
        h_new = self.store._cached_embedding_text_hash(mem2, max_chars=1200, revision=rev2)
        self.assertEqual(memory_embedding_text_hash(mem2, max_chars=1200), h_new)
        self.assertNotEqual(expected_1200, h_new)


class VectorCrossRevisionAndTimeIntentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.ctx = SessionContext(
            scope="group",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            persona_id="p1",
            group_id="g1",
            session_id="onebot_qq:GroupMessage:g1",
        )
        self.provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        self.engine = RetrievalEngine(
            self.store,
            VisibilityPolicy(),
            embedding_enabled=True,
            embedding_provider=self.provider,
            embedding_provider_id="test",
            embedding_candidate_limit=64,
            embedding_top_k=4,
            embedding_score_threshold=0.0,
            knowledge_graph_enabled=False,
        )

    def seed(self, items: list[tuple[MemoryRecord, list[float]]], *, provider_id: str = "test") -> None:
        with self.store._lock, self.store._conn:
            for record, vec in items:
                self.store._insert_memory_sync(record, _commit=False)
                self.store._conn.execute(
                    "INSERT INTO memory_embeddings(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        record.id,
                        provider_id,
                        memory_embedding_text_hash(record),
                        len(vec),
                        _pack_embedding_vector(vec),
                        record.created_at,
                        record.created_at,
                    ),
                )

    async def test_cross_revision_reuses_unchanged_normalized_slices_and_clears_old_snapshots(self) -> None:
        self.seed([
            (_make_record("m1"), [1.0, 0.0]),
            (_make_record("m2"), [0.6, 0.8]),
            (_make_record("m3"), [0.0, 1.0]),
        ])
        m_a, _, info_a = await self.engine._embedding_candidate_memories(
            "群里最近讨论了什么", self.ctx, include_pending=False,
        )
        self.assertEqual(3, len(m_a))
        self.assertFalse(info_a["embedding_cache_hit"])
        rev1 = info_a["embedding_revision"]

        # Insert 1 new record -> bumps retrieval_revision.
        self.seed([(_make_record("m4"), [0.8, 0.6])])

        with patch.object(
            vector_search, "_normalized_bytes", wraps=vector_search._normalized_bytes
        ) as norm_spy:
            m_b, scores_b, info_b = await self.engine._embedding_candidate_memories(
                "群里最近讨论了什么", self.ctx, include_pending=False,
            )

        self.assertFalse(info_b["embedding_cache_hit"])
        self.assertEqual(3, info_b["embedding_reused_rows"])
        self.assertEqual(1, norm_spy.call_count)
        self.assertEqual({"m1", "m2", "m3", "m4"}, {m.id for m in m_b})
        self.assertAlmostEqual(0.8, scores_b["m4"], places=6)
        rev2 = info_b["embedding_revision"]
        self.assertNotEqual(rev1, rev2)
        # Old revision snapshot must be evicted after publishing the new revision snapshot.
        self.assertEqual(1, len(self.store._vector_search_cache))
        for snap in self.store._vector_search_cache.values():
            self.assertEqual(rev2, snap.revision)

    async def test_time_intent_shares_snapshot_in_both_orders_and_filters_before_topk(self) -> None:
        # top_k=1: out-of-window row has score 1.0, in-window rows have 0.8 and 0.6.
        self.engine.embedding_top_k = 1
        self.seed([
            (
                _make_record(
                    "old-exact",
                    occurred_at="2025-01-01T00:00:00+00:00",
                    created_at="2025-01-01T00:00:00+00:00",
                    updated_at="2025-01-01T00:00:00+00:00",
                ),
                [1.0, 0.0],
            ),
            (
                _make_record(
                    "meta-range",
                    occurred_at="2025-02-01T00:00:00+00:00",
                    created_at="2025-02-01T00:00:00+00:00",
                    updated_at="2025-02-01T00:00:00+00:00",
                    metadata={
                        "start_at": "2026-11-17T20:00:00+00:00",
                        "end_at": "2026-11-18T12:00:00+00:00",
                    },
                ),
                [0.8, 0.6],
            ),
            (
                _make_record(
                    "today-direct",
                    occurred_at="2026-11-18T08:00:00+00:00",
                    created_at="2026-11-18T08:00:00+00:00",
                    updated_at="2026-11-18T08:00:00+00:00",
                ),
                [0.6, 0.8],
            ),
        ])
        window = TimeIntent(
            active=True,
            start_at="2026-11-18T00:00:00+00:00",
            end_at="2026-11-19T00:00:00+00:00",
        )

        # Order A: time_intent first builds FULL snapshot, then non-time query hits same snapshot!
        m_ti, _, info_ti = await self.engine._embedding_candidate_memories(
            "今天群里聊过什么", self.ctx, include_pending=False, time_intent=window,
        )
        self.assertEqual(["meta-range"], [m.id for m in m_ti])
        self.assertFalse(info_ti["embedding_cache_hit"])

        m_plain, _, info_plain = await self.engine._embedding_candidate_memories(
            "群里聊过什么", self.ctx, include_pending=False,
        )
        self.assertEqual(["old-exact"], [m.id for m in m_plain])
        self.assertTrue(info_plain["embedding_cache_hit"])
        self.assertEqual(0, info_plain["embedding_scanned_rows"])
        self.assertEqual(1, len(self.store._vector_search_cache))

        # Order B: non-time query first, then time_intent query hits same snapshot!
        self.store._vector_search_cache.clear()
        m_plain_2, _, info_plain_2 = await self.engine._embedding_candidate_memories(
            "群里聊过什么", self.ctx, include_pending=False,
        )
        self.assertEqual(["old-exact"], [m.id for m in m_plain_2])
        self.assertFalse(info_plain_2["embedding_cache_hit"])

        m_ti_2, _, info_ti_2 = await self.engine._embedding_candidate_memories(
            "今天群里聊过什么", self.ctx, include_pending=False, time_intent=window,
        )
        self.assertEqual(["meta-range"], [m.id for m in m_ti_2])
        self.assertTrue(info_ti_2["embedding_cache_hit"])
        self.assertEqual(0, info_ti_2["embedding_scanned_rows"])
        self.assertEqual(1, len(self.store._vector_search_cache))

    async def test_batch_numpy_normalization_matches_python_reference(self) -> None:
        rng = random.Random(20261118)
        dim = 64
        query = [rng.uniform(-1.0, 1.0) for _ in range(dim)]
        vectors = [[rng.uniform(-1.0, 1.0) for _ in range(dim)] for _ in range(20)]
        self.seed([(_make_record(f"b-{i:02d}"), vec) for i, vec in enumerate(vectors)] + [
            (_make_record("bad-nan"), [math.nan] + [0.0] * (dim - 1)),
            (_make_record("bad-zero"), [0.0] * dim),
        ])
        self.provider.get_embedding.return_value = query
        self.engine.embedding_top_k = 5

        expected = sorted(
            (
                (
                    math.fsum(a * b for a, b in zip(query, v))
                    / (math.hypot(*query) * math.hypot(*v)),
                    f"b-{i:02d}",
                )
                for i, v in enumerate(vectors)
            ),
            key=lambda item: (-item[0], item[1]),
        )[:5]

        memories, scores, info = await self.engine._embedding_candidate_memories(
            "批归一化测试", self.ctx, include_pending=False,
        )
        self.assertEqual(2, info["embedding_invalid"])
        self.assertEqual([mid for _, mid in expected], [m.id for m in memories])
        for exp_score, mid in expected:
            self.assertAlmostEqual(exp_score, scores[mid], places=12)


class HotPathScoringAndSharedCacheTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_text_fast_path_matches_regex_reference(self) -> None:
        samples = [
            None,
            "",
            "   ",
            "hello world",
            "  hello\u3000\n\tworld\r\n  测试  ",
            "中文连续文本无需正则",
            "a" * 300,
        ]
        for sample in samples:
            expected = (
                ""
                if sample is None
                else " ".join(str(sample).replace("\u3000", " ").split())
            )
            self.assertEqual(
                expected[:19] + "…" if len(expected) > 20 else expected,
                clean_text(sample, 20),
            )
            self.assertEqual(expected[:20], profile_quality._clean_text(sample, 20))

    async def test_rank_candidates_evaluates_lifecycle_once_per_searchable_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                for idx in range(5):
                    store._insert_memory_sync(
                        _make_record(f"lc-{idx}", content=f"周末一起去公园散步 {idx}")
                    )
                engine = RetrievalEngine(
                    store,
                    VisibilityPolicy(enable_acl_rules=False),
                    retrieval_mode="basic",
                    embedding_enabled=False,
                    knowledge_graph_enabled=False,
                )
                ctx = SessionContext(
                    scope="group",
                    platform="qq",
                    user_id="u1",
                    bot_id="b1",
                    persona_id="p1",
                    group_id="g1",
                    session_id="onebot_qq:GroupMessage:g1",
                )
                with patch.object(
                    retrieval_mod,
                    "evaluate_memory_lifecycle",
                    wraps=memory_lifecycle.evaluate_memory_lifecycle,
                ) as spy_lc:
                    results, _ = await engine._rank_candidates("公园散步", ctx)
                self.assertEqual(5, len(results))
                self.assertEqual(5, spy_lc.call_count)
            finally:
                store.close()

    async def test_service_shares_query_vector_cache_across_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryCompanionService(
                context=None,
                plugin_root=ROOT,
                data_dir=Path(tmp),
                config={
                    "retrieval": {
                        "mode": "basic",
                        "embedding_enabled": True,
                        "embedding_provider_id": "test-emb",
                    },
                    "retrieval_advanced": {
                        "query_vector_cache_ttl_seconds": 60.0,
                    },
                },
            )
            try:
                provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
                ctx = SessionContext(
                    scope="private",
                    platform="qq",
                    user_id="u1",
                    bot_id="b1",
                    persona_id="p1",
                    session_id="qq:FriendMessage:u1",
                )
                with patch.object(
                    service, "_resolve_embedding_provider", AsyncMock(return_value=(provider, "test-emb"))
                ), patch.object(service, "_schedule_embedding_backfill"):
                    engine_1 = await service._retrieval_engine(ctx)
                    engine_2 = await service._retrieval_engine(ctx)
                self.assertIs(engine_1._query_vector_cache, service._query_vector_cache)
                self.assertIs(engine_2._query_vector_cache, service._query_vector_cache)

                v1 = await engine_1._call_embedding_provider("周末计划")
                v2 = await engine_2._call_embedding_provider("周末计划")
                self.assertEqual(v1, v2)
                self.assertEqual(1, provider.get_embedding.await_count)
            finally:
                await service.aclose()


class LockContentionCaptureAndReplyChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_revision_does_not_block_on_write_lock_or_bundle_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                store._insert_memory_sync(_make_record("rev-1"))
                expected = store._memory_revision_sync()

                # Hold write lock + transaction on main connection.
                held = threading.Event()
                release = threading.Event()

                def hold_write_tx() -> None:
                    with store._lock, store._transaction_sync():
                        held.set()
                        release.wait(5.0)

                t = threading.Thread(target=hold_write_tx, daemon=True)
                t.start()
                try:
                    self.assertTrue(await asyncio.to_thread(held.wait, 5.0))
                    rev = await asyncio.wait_for(store.memory_revision(), timeout=1.5)
                    self.assertEqual(expected, rev)
                finally:
                    release.set()
                    t.join(5.0)

                # Hold bundle read lock too: memory_revision must fall back to timeline reader without blocking.
                held2 = threading.Event()
                release2 = threading.Event()

                def hold_bundle_lock() -> None:
                    _conn, lock = store._read_connection_for_bundle()
                    with lock:
                        held2.set()
                        release2.wait(5.0)

                t2 = threading.Thread(target=hold_bundle_lock, daemon=True)
                t2.start()
                try:
                    self.assertTrue(await asyncio.to_thread(held2.wait, 5.0))
                    rev2 = await asyncio.wait_for(store.memory_revision(), timeout=1.5)
                    self.assertEqual(expected, rev2)
                finally:
                    release2.set()
                    t2.join(5.0)
            finally:
                store.close()

    def test_source_capture_enabled_uses_in_process_cache_without_store_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                cap = SourceCapture(store, default_enabled=True)
                self.assertTrue(cap.source_capture_enabled())

                cap.set_source_capture_enabled(False, actor="tester")
                self.assertFalse(cap.source_capture_enabled())

                # Even if store._lock is held by another thread, source_capture_enabled() stays non-blocking.
                held = threading.Event()
                release = threading.Event()

                def hold() -> None:
                    with store._lock:
                        held.set()
                        release.wait(5.0)

                t = threading.Thread(target=hold, daemon=True)
                t.start()
                try:
                    self.assertTrue(held.wait(5.0))
                    self.assertFalse(cap.source_capture_enabled())
                finally:
                    release.set()
                    t.join(5.0)

                reopened = SourceCapture(store, default_enabled=True)
                self.assertFalse(reopened.source_capture_enabled())
            finally:
                store.close()

    async def test_reply_chain_get_msg_is_excluded_from_hook_budget_and_bounded_by_timeout(self) -> None:
        resolver = ReplyChainResolver(get_msg_timeout_seconds=0.5)

        async def slow_call_action(action: str, **_kwargs):
            self.assertEqual("get_msg", action)
            await asyncio.sleep(0.18)
            return {"message": "被引用消息"}

        event = SimpleNamespace(
            message_obj=SimpleNamespace(message=[{"type": "reply", "data": {"id": "123"}}]),
            bot=SimpleNamespace(api=SimpleNamespace(call_action=slow_call_action)),
        )
        # Hook budget is 0.08s, shorter than the 0.18s OneBot RPC wait: must succeed because wait is excluded.
        chain = await await_with_memory_hook_budget(resolver.resolve(event, max_depth=1), 0.08)
        self.assertEqual(1, len(chain))
        self.assertEqual("被引用消息", chain[0]["text"])

        # Hanging RPC must time out at get_msg_timeout_seconds and return empty chain without hanging.
        bounded_resolver = ReplyChainResolver(get_msg_timeout_seconds=0.12)

        async def hanging_call_action(_action: str, **_kwargs):
            await asyncio.sleep(5.0)
            return {"message": "never"}

        hanging_event = SimpleNamespace(
            message_obj=SimpleNamespace(message=[{"type": "reply", "data": {"id": "456"}}]),
            bot=SimpleNamespace(api=SimpleNamespace(call_action=hanging_call_action)),
        )
        chain_timeout = await asyncio.wait_for(bounded_resolver.resolve(hanging_event, max_depth=1), timeout=1.0)
        self.assertEqual([], chain_timeout)

    def test_keyword_and_fts_candidate_rows_match_content_and_metadata_with_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                r1 = _make_record("kw-content", content="今天讨论了黑神话悟空攻略", session_id="onebot_qq:GroupMessage:g1")
                r2 = _make_record("kw-meta", content="普通对话记录", metadata={"canonical_summary": "包含只狼隐藏结局"}, session_id="")
                r3 = _make_record("kw-other", content="无关内容")
                for rec in (r1, r2, r3):
                    store._insert_memory_sync(rec)
                conn, lock = store._read_connection_for_bundle()
                with lock:
                    kw_meta = store._keyword_candidate_rows(conn, ["黑神话", "只狼"], 10, False)
                    self.assertEqual(["kw-content", "kw-meta"], [r["id"] for r in kw_meta])
                    kw_limited = store._keyword_candidate_rows(conn, ["黑神话", "只狼"], 1, False)
                    self.assertEqual(["kw-content"], [r["id"] for r in kw_limited])
                    fts_rows = store._fts_candidate_rows(conn, ["黑神话"], 10, False)
                    self.assertEqual(["kw-content"], [r["id"] for r in fts_rows])
            finally:
                store.close()


class VectorBudgetAndMutationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_revision_reuse_respects_snapshot_budget_and_post_filter_catches_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                records = [
                    _make_record(
                        f"bg-{i:02d}",
                        occurred_at="2026-11-18T05:00:00+00:00",
                        created_at="2026-11-18T05:00:00+00:00",
                        updated_at="2026-11-18T05:00:00+00:00",
                    )
                    for i in range(8)
                ]
                with store._lock, store._conn:
                    for idx, rec in enumerate(records):
                        store._insert_memory_sync(rec, _commit=False)
                        vec = [1.0, 0.0] if idx == 0 else [0.0, 1.0]
                        store._conn.execute(
                            "INSERT INTO memory_embeddings(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (
                                rec.id,
                                "test",
                                memory_embedding_text_hash(rec),
                                2,
                                _pack_embedding_vector(vec),
                                rec.created_at,
                                rec.created_at,
                            ),
                        )
                provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
                engine = RetrievalEngine(
                    store,
                    VisibilityPolicy(),
                    embedding_enabled=True,
                    embedding_provider=provider,
                    embedding_provider_id="test",
                    embedding_candidate_limit=2,
                    embedding_top_k=2,
                    embedding_score_threshold=0.0,
                    knowledge_graph_enabled=False,
                )
                ctx = SessionContext(
                    scope="group",
                    platform="qq",
                    user_id="u1",
                    bot_id="b1",
                    persona_id="p1",
                    group_id="g1",
                    session_id="onebot_qq:GroupMessage:g1",
                )
                with patch.object(vector_search, "CACHE_BYTES", 100):
                    m1, _, info1 = await engine._embedding_candidate_memories(
                        "测试", ctx, include_pending=False,
                    )
                    self.assertTrue(info1["embedding_snapshot_partial"])
                    self.assertIn("bg-00", [m.id for m in m1])

                    # Bump revision with 1 more record; retained blocks still respect tight budget.
                    extra = _make_record("bg-08")
                    with store._lock, store._conn:
                        store._insert_memory_sync(extra, _commit=False)
                        store._conn.execute(
                            "INSERT INTO memory_embeddings(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (
                                extra.id,
                                "test",
                                memory_embedding_text_hash(extra),
                                2,
                                _pack_embedding_vector([0.0, 1.0]),
                                extra.created_at,
                                extra.created_at,
                            ),
                        )
                    m2, _, info2 = await engine._embedding_candidate_memories(
                        "测试", ctx, include_pending=False,
                    )
                    self.assertTrue(info2["embedding_snapshot_partial"])
                    self.assertGreater(info2["embedding_reused_rows"], 0)
                    self.assertIn("bg-00", [m.id for m in m2])
                    self.assertEqual(1, len(store._vector_search_cache))
                    snap = next(iter(store._vector_search_cache.values()))
                    self.assertEqual(1, len(snap.blocks))
                    self.assertEqual(info2["embedding_revision"], snap.revision)

                # Post-filter catches concurrent metadata time-window mutation before materializing final result.
                window = TimeIntent(
                    active=True,
                    start_at="2026-11-18T00:00:00+00:00",
                    end_at="2026-11-19T00:00:00+00:00",
                )
                original_scores = vector_search.block_scores
                mutated_once = False

                def mutate_time_meta(block, query):
                    nonlocal mutated_once
                    if not mutated_once:
                        mutated_once = True
                        with store._lock, store._conn:
                            store._conn.execute(
                                "UPDATE memories SET occurred_at=?, created_at=?, updated_at=? WHERE id='bg-00'",
                                ("2020-01-01T00:00:00+00:00",) * 3,
                            )
                    return original_scores(block, query)

                with patch.object(vector_search, "block_scores", side_effect=mutate_time_meta):
                    m3, _, _info3 = await engine._embedding_candidate_memories(
                        "今天", ctx, include_pending=False, time_intent=window,
                    )
                self.assertNotIn("bg-00", [m.id for m in m3])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
