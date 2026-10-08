"""Authorized exact retrieval, version races and bounded snapshot regression."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
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

from astrbot_plugin_memory_companion.core import vector_search
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext, memory_embedding_text_hash
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore, _pack_embedding_vector
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy
from astrbot_plugin_memory_companion.core.time_intent import TimeIntent


class VectorSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = MemoryStore(Path(tmp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.ctx = SessionContext(scope="private", platform="qq", user_id="u1", bot_id="b1",
                                  persona_id="p1", session_id="qq:FriendMessage:u1")
        self.provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1., 0.]))
        self.engine = RetrievalEngine(self.store, VisibilityPolicy(), embedding_enabled=True,
                                     embedding_provider=self.provider, embedding_provider_id="test",
                                     embedding_candidate_limit=64, embedding_top_k=1,
                                     knowledge_graph_enabled=False)

    def record(self, mid, **changes):
        return replace(MemoryRecord(
            id=mid, memory_type="conversation_summary", subject=EntityRef(kind="user", id="u1"),
            object=EntityRef.bot_self("b1"), owner_bot_id="b1", scope="private", platform="qq",
            session_id=self.ctx.session_id, visibility="private_pair", lifecycle="stable_memory",
            content=f"换乘城际列车，到站时已经深夜。{mid}", metadata={"persona_id": "p1"},
            importance=.1, occurred_at="2025-01-01T00:00:00+00:00"), **changes)

    def seed(self, records):
        with self.store._lock, self.store._conn:
            for record, vector in records:
                self.assertEqual(record.id, self.store._insert_memory_sync(record, _commit=False))
                self.store._conn.execute(
                    "INSERT INTO memory_embeddings(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)", (record.id, "test", memory_embedding_text_hash(record), len(vector),
                                              _pack_embedding_vector(vector), record.created_at, record.created_at))

    async def search(self, ctx=None):
        return await self.engine._embedding_candidate_memories("那次临时换了交通方式为什么晚到", ctx or self.ctx,
                                                               include_pending=False)

    async def test_old_target_and_other_sessions_do_not_lose_admission(self):
        self.seed([(self.record("old"), [1., 0.])] + [
            (self.record(f"noise-{i:04}", importance=.9,
                         subject=EntityRef(kind="user", id="u2" if i % 2 else "u1"),
                         session_id="qq:FriendMessage:u2" if i % 2 else self.ctx.session_id), [0., 1.])
            for i in range(1250)])
        legacy = await self.store.list_embedding_candidate_rows(provider_id="test", limit=1200)
        self.assertNotIn("old", [r.id for r, _, _ in legacy])
        memories, scores, info = await self.search()
        self.assertEqual(["old"], [m.id for m in memories])
        self.assertAlmostEqual(1., scores["old"])
        self.assertEqual(626, info["embedding_candidates"])
        self.assertEqual(1, info["embedding_rows_materialized"])
        ranked, _ = await self.engine._rank_candidates("那次临时换了交通方式为什么晚到", self.ctx)
        self.assertIn("old", [r.memory.id for r in ranked])

    async def test_hidden_best_score_cannot_crowd_out_authorized_top1(self):
        self.seed([(self.record("hidden", subject=EntityRef(kind="user", id="u2"),
                                session_id="qq:FriendMessage:u2"), [1., 0.]),
                   (self.record("visible"), [.8, .6])])
        memories, _, _ = await self.search()
        self.assertEqual(["visible"], [m.id for m in memories])

    async def test_shared_acl_grant_revoke_and_policy_changes_invalidate(self):
        self.seed([(self.record("shared"), [1., 0.])])
        group = replace(self.ctx, scope="group", group_id="g1", session_id="qq:GroupMessage:g1")
        self.assertFalse((await self.search(group))[0])
        rule = await self.store.upsert_acl_rule(owner_scope="private", owner_id="u1",
                                              reader_scope="group", reader_id="g1", effect="allow")
        self.assertEqual(["shared"], [m.id for m in (await self.search(group))[0]])
        self.assertFalse((await self.search(replace(group, strict_session_only=True)))[0])
        await self.store.delete_acl_rule(rule["id"])
        self.assertFalse((await self.search(group))[0])

    async def test_group_default_topology_sharing_is_preserved(self):
        self.seed([(self.record("group", scope="group", group_id="g2", visibility="group_public",
                                session_id="qq:GroupMessage:g2"), [1., 0.])])
        group = replace(self.ctx, scope="group", group_id="g1", session_id="qq:GroupMessage:g1")
        self.assertEqual(["group"], [m.id for m in (await self.search(group))[0]])
        self.engine.group_topology_enabled = False
        self.assertFalse((await self.search(group))[0])

    async def test_lifecycle_owner_persona_and_internal_rows_filtered_before_topk(self):
        now = datetime.now(timezone.utc)
        variants = [{"validity_status": "superseded"}, {"valid_to": (now - timedelta(days=1)).isoformat()},
                    {"valid_from": (now + timedelta(days=1)).isoformat()}, {"sensitivity": "restricted"},
                    {"owner_bot_id": "b2"}, {"metadata": {"persona_id": "p2"}},
                    {"lifecycle": "archived"}, {"review_status": "pending"}, {"visibility": "internal"}]
        self.seed([(self.record(f"excluded-{i}", **variant), [1., 0.]) for i, variant in enumerate(variants)]
                  + [(self.record("allowed"), [.8, .6])])
        self.assertEqual(["allowed"], [m.id for m in (await self.search())[0]])

    async def test_stale_text_embedding_update_and_delete_refresh_cache(self):
        self.seed([(self.record("item"), [1., 0.])])
        first = await self.search()
        first[0][0].content = "cannot mutate snapshot"
        warm = await self.search()
        self.assertTrue(warm[2]["embedding_cache_hit"])
        self.assertNotEqual("cannot mutate snapshot", warm[0][0].content)
        with self.store._lock, self.store._conn:
            self.store._conn.execute("UPDATE memories SET content=? WHERE id='item'", ("后来更正了记录。",))
        stale = await self.search()
        self.assertFalse(stale[0])
        self.assertEqual(1, stale[2]["embedding_stale"])
        record = (await self.store.get_memories_by_ids(["item"]))["item"]
        await self.store.upsert_memory_embedding(memory_id="item", provider_id="test",
                                                text_hash=memory_embedding_text_hash(record), vector=[1., 0.])
        self.assertEqual("后来更正了记录。", (await self.search())[0][0].content)
        await self.store.delete_memory("item")
        self.assertFalse((await self.search())[0])

    async def test_validity_clock_boundary_invalidates_without_write(self):
        now = datetime.now(timezone.utc)
        self.seed([(self.record("future", valid_from=(now + timedelta(minutes=1)).isoformat()), [1., 0.]),
                   (self.record("present", valid_to=(now + timedelta(minutes=1)).isoformat()), [.8, .6])])
        with patch("astrbot_plugin_memory_companion.core.retrieval.datetime") as clock:
            clock.now.return_value = now
            self.assertEqual(["present"], [m.id for m in (await self.search())[0]])
            clock.now.return_value = now + timedelta(minutes=2)
            self.assertEqual(["future"], [m.id for m in (await self.search())[0]])

    async def test_legacy_json_invalid_vectors_and_dimension_do_not_hide_valid_result(self):
        self.seed([(self.record("legacy"), [3., 4.]), (self.record("nan"), [math.nan, 0.]),
                   (self.record("zero"), [0., 0.]), (self.record("dimension"), [1., 0., 0.]),
                   (self.record("malformed"), [1., 0.])])
        with self.store._lock, self.store._conn:
            self.store._conn.execute("UPDATE memory_embeddings SET vector=? WHERE memory_id='legacy'", (json.dumps([3., 4.]),))
            self.store._conn.execute("UPDATE memory_embeddings SET vector=? WHERE memory_id='malformed'", (b"short",))
        memories, scores, info = await self.search()
        self.assertEqual(["legacy"], [m.id for m in memories])
        self.assertAlmostEqual(.6, scores["legacy"])
        self.assertEqual(3, info["embedding_invalid"])
        self.assertEqual(1, info["embedding_dim_mismatch"])
        self.provider.get_embedding.return_value = [math.nan, 0.]
        self.assertEqual("empty_query_vector", (await self.search())[2]["embedding_reason"])

    async def test_numpy_and_python_match_independent_exact_cosine_in_multiple_blocks(self):
        rng = random.Random(91403)
        query = [rng.uniform(-1, 1) for _ in range(37)]
        vectors = [[rng.uniform(-1, 1) for _ in query] for _ in range(91)]
        self.seed([(self.record(f"m-{i:03}"), vec) for i, vec in enumerate(vectors)])
        self.engine.embedding_candidate_limit = 7
        self.engine.embedding_top_k = 8
        self.engine.embedding_score_threshold = 0.
        self.provider.get_embedding.return_value = query
        expected = sorted(((math.fsum(a*b for a,b in zip(query, vec)) / (math.hypot(*query)*math.hypot(*vec)), f"m-{i:03}")
                           for i, vec in enumerate(vectors)), key=lambda item: (-item[0], item[1]))[:8]
        for python_only in (False, True):
            with patch.object(vector_search, "_numpy", return_value=None) if python_only else nullcontext():
                memories, scores, _ = await self.search()
            self.assertEqual([mid for _, mid in expected], [m.id for m in memories])
            for score, mid in expected:
                self.assertAlmostEqual(score, scores[mid], places=12)

    async def test_cache_budget_overflow_keeps_search_complete(self):
        self.seed([(self.record(f"item-{i}"), [0., 1.]) for i in range(15)] + [(self.record("z-target"), [1., 0.])])
        self.engine.embedding_candidate_limit = 2
        with patch.object(vector_search, "CACHE_BYTES", 100):
            memories, _, info = await self.search()
        self.assertEqual(["z-target"], [m.id for m in memories])
        self.assertFalse(info["embedding_cache_retained"])
        self.assertFalse(self.store._vector_search_cache)

    async def test_explicit_time_window_enters_cache_key_and_filters_before_topk(self):
        self.seed([(self.record("outside", occurred_at="2025-01-01T00:00:00+00:00"), [1., 0.]),
                   (self.record("inside", occurred_at="2025-06-01T00:00:00+00:00",
                                created_at="2025-06-01T00:00:00+00:00", updated_at="2025-06-01T00:00:00+00:00"), [.8, .6])])
        self.assertEqual(["outside"], [m.id for m in (await self.search())[0]])
        window = TimeIntent(active=True, start_at="2025-06-01T00:00:00+00:00", end_at="2025-06-02T00:00:00+00:00")
        result = await self.engine._embedding_candidate_memories("那次临时换了交通方式为什么晚到", self.ctx,
                                                                 include_pending=False, time_intent=window)
        self.assertEqual(["inside"], [m.id for m in result[0]])
        self.assertFalse(result[2]["embedding_cache_hit"])

    async def test_provider_dimension_changes_and_read_only_store(self):
        self.seed([(self.record("item"), [1., 0.])])
        self.assertTrue((await self.search())[0])
        self.engine.embedding_provider_id = "different"
        self.assertFalse((await self.search())[0])
        self.engine.embedding_provider_id = "test"
        self.provider.get_embedding.return_value = [1., 0., 0.]
        self.assertEqual(1, (await self.search())[2]["embedding_dim_mismatch"])
        self.provider.get_embedding.return_value = [1., 0.]
        reader = MemoryStore(self.store.db_path, read_only=True)
        try:
            self.engine.store = reader
            before = reader._conn.total_changes
            self.assertEqual(["item"], [m.id for m in (await self.search())[0]])
            self.assertEqual(before, reader._conn.total_changes)
        finally:
            self.engine.store = self.store
            reader.close()

    async def test_continuous_revision_race_returns_diagnostic_without_partial_answer(self):
        self.seed([(self.record("item"), [1., 0.])])
        with patch.object(self.store, "search_memory_embeddings", new=AsyncMock(
            side_effect=vector_search.VectorSnapshotChanged("changed"))) as search:
            memories, scores, info = await self.search()
        self.assertFalse(memories)
        self.assertFalse(scores)
        self.assertEqual("embedding_snapshot_changed", info["embedding_reason"])
        self.assertEqual(2, search.await_count)
        self.provider.get_embedding.assert_awaited_once()

    async def test_parallel_queries_share_numeric_snapshot_not_ranked_answer(self):
        self.seed([(self.record("a"), [1., 0.]), (self.record("b"), [0., 1.])])
        self.provider.get_embedding.side_effect = [[1., 0.], [0., 1.]]
        first, second = await asyncio.gather(self.search(), self.search())
        self.assertEqual(["a"], [m.id for m in first[0]])
        self.assertEqual(["b"], [m.id for m in second[0]])
        self.assertEqual(1, sum(r[2]["embedding_cache_hit"] for r in (first, second)))

    async def test_mutation_during_search_retries_current_snapshot_without_second_embedding(self):
        self.seed([(self.record("item"), [1., 0.])])
        original = vector_search.block_scores
        changed = False
        def mutate(block, query):
            nonlocal changed
            if not changed:
                changed = True
                with self.store._lock, self.store._conn:
                    self.store._conn.execute("UPDATE memories SET visibility='internal' WHERE id='item'")
            return original(block, query)
        with patch.object(vector_search, "block_scores", side_effect=mutate):
            self.assertFalse((await self.search())[0])
        self.provider.get_embedding.assert_awaited_once()

    async def test_cancel_and_close_wait_for_worker_without_publishing_snapshot(self):
        self.seed([(self.record("item"), [1., 0.])])
        entered, release = threading.Event(), threading.Event()
        original = vector_search.block_scores
        def pause(block, query):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test worker timed out")
            return original(block, query)
        with patch.object(vector_search, "block_scores", side_effect=pause):
            task = asyncio.create_task(self.search())
            closer = None
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                closer = asyncio.create_task(asyncio.to_thread(self.store.close))
                await asyncio.sleep(0)
            finally:
                release.set()
                if closer:
                    await asyncio.wait_for(closer, 5)
        self.assertTrue(self.store._closed)
        self.assertFalse(self.store._vector_search_cache)
