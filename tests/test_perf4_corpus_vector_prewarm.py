"""Perf4 regression tests: startup vector corpus prewarm, incremental delta sync,
dedicated SQLite read connections, single-hop incoming capture, canonical history digest,
deferred hook persistence flush, rerank circuit breaker, and single ACL load per turn."""

from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import service as service_mod, vector_search
from astrbot_plugin_memory_companion.core.capture_runtime import CaptureRuntime
from astrbot_plugin_memory_companion.core.memory_revision import memory_ref
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SearchResult,
    SessionContext,
    memory_embedding_text_hash,
)
from astrbot_plugin_memory_companion.core.retrieval import (
    RerankCircuitBreaker,
    RetrievalEngine,
)
from astrbot_plugin_memory_companion.core.service import (
    MemoryCompanionService,
    _canonical_history_digest,
)
from astrbot_plugin_memory_companion.core.source_capture import SourceCapture
from astrbot_plugin_memory_companion.core.store import (
    MemoryStore,
    _pack_embedding_vector,
)
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def _make_record(
    memory_id: str,
    *,
    content: str = "",
    scope: str = "group",
    platform: str = "qq",
    bot_id: str = "b1",
    user_id: str = "u1",
    session_id: str = "onebot_qq:GroupMessage:g1",
    group_id: str = "g1",
    visibility: str = "group_public",
    memory_type: str = "conversation_summary",
    occurred_at: str = "2026-11-18T02:00:00+00:00",
    created_at: str = "2026-11-18T02:00:00+00:00",
    updated_at: str = "2026-11-18T02:00:00+00:00",
    valid_from: str = "",
    valid_to: str = "",
    metadata: dict | None = None,
) -> MemoryRecord:
    meta = {"persona_id": "p1"}
    if metadata:
        meta.update(metadata)
    return MemoryRecord(
        id=memory_id,
        memory_type=memory_type,
        subject=EntityRef(kind="user", id=user_id),
        object=EntityRef.bot_self(bot_id),
        owner_bot_id=bot_id,
        scope=scope,
        platform=platform,
        session_id=session_id,
        group_id=group_id,
        visibility=visibility,
        lifecycle="stable_memory",
        content=content or f"群聊记录内容 {memory_id}",
        metadata=meta,
        tags=["perf4"],
        importance=0.5,
        occurred_at=occurred_at,
        created_at=created_at,
        updated_at=updated_at,
        valid_from=valid_from,
        valid_to=valid_to,
    ).ensure_defaults()


def _seed_vectors(
    store: MemoryStore,
    items: list[tuple[MemoryRecord, list[float]]],
    *,
    provider_id: str = "test",
) -> None:
    with store._lock, store._conn:
        for record, vec in items:
            store._insert_memory_sync(record, _commit=False)
            store._conn.execute(
                "INSERT OR REPLACE INTO memory_embeddings"
                "(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    record.id,
                    provider_id,
                    memory_embedding_text_hash(record),
                    len(vec),
                    _pack_embedding_vector(vec),
                    record.created_at,
                    record.updated_at,
                ),
            )


class _StrictQueryOnlyEmbeddingProvider:
    """Fails if warmup calls any network embedding API, serves query vector on search."""

    def __init__(self, query_vec: list[float] | None = None) -> None:
        self.query_vec = list(query_vec or [1.0, 0.0])
        self.calls: list[str] = []

    async def get_embedding(self, text: str) -> list[float]:
        self.calls.append(text)
        return list(self.query_vec)


class StartupVectorCorpusPrewarmTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self.db_path = self.data_dir / "memory.db"
        self.ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id="u1",
            user_name="阿瓜",
            group_id="g1",
            bot_id="b1",
            persona_id="p1",
            message_id="msg-1",
            message_text="你还记得蓝风铃吗",
        )

    async def test_startup_warmup_populates_light_cache_and_serves_warm_search(self) -> None:
        service = MemoryCompanionService(
            context=None,
            config={
                "retrieval": {
                    "embedding_enabled": True,
                    "embedding_provider_id": "test",
                    "embedding_candidate_limit": 1200,
                    "embedding_top_k": 4,
                    "embedding_score_threshold": 0.0,
                },
                "retrieval_advanced": {
                    "startup_vector_warmup_enabled": True,
                },
            },
            plugin_root=Path(ROOT),
            data_dir=self.data_dir,
        )
        self.addAsyncCleanup(service.aclose)

        r1 = _make_record("m1", content="蓝风铃的约会")
        r2 = _make_record("m2", content="咖啡店聊天")
        _seed_vectors(service.store, [(r1, [1.0, 0.0]), (r2, [0.6, 0.8])])

        # Clear any light cache entries populated during _insert_memory_sync to simulate cold start.
        light_cache = service.store.__dict__.get("_record_light_cache")
        if isinstance(light_cache, dict):
            light_cache.clear()
        service.store._vector_corpus_cache.clear()

        provider = _StrictQueryOnlyEmbeddingProvider([1.0, 0.0])
        with patch.object(service, "_resolve_embedding_provider", return_value=provider):
            scheduled = service.schedule_startup_vector_warmup(settle_seconds=0.0)
            self.assertTrue(scheduled)
            with service.store._vector_warmup_lock:
                warmup_tasks = [t for t, _ in service.store._vector_warmup_tasks.values()]
            if warmup_tasks:
                await asyncio.gather(*warmup_tasks, return_exceptions=True)

        # Warmup must never touch network embedding providers.
        self.assertEqual([], provider.calls)
        self.assertIn("m1", service.store._record_light_cache)
        self.assertIn("m2", service.store._record_light_cache)
        self.assertTrue(service.store._vector_corpus_cache)
        corpus = next(iter(service.store._vector_corpus_cache.values()))
        self.assertTrue(corpus.eager_vectors)
        self.assertEqual(2, len(corpus.entries))

        engine = RetrievalEngine(
            service.store,
            VisibilityPolicy(),
            embedding_enabled=True,
            embedding_provider=provider,
            embedding_provider_id="test",
            embedding_candidate_limit=1200,
            embedding_top_k=4,
            embedding_score_threshold=0.0,
        )
        memories, scores, info = await engine._embedding_candidate_memories(
            "蓝风铃", self.ctx, include_pending=False,
        )
        self.assertEqual({"m1", "m2"}, {m.id for m in memories})
        self.assertAlmostEqual(1.0, scores["m1"], places=6)
        self.assertFalse(info["embedding_cache_hit"])
        self.assertTrue(info["embedding_corpus_hit"])
        self.assertEqual(0, info["embedding_corpus_delta_rows"])
        self.assertEqual(0, info["embedding_scanned_rows"])
        self.assertEqual(2, info["embedding_reused_rows"])

    async def test_startup_warmup_single_flight_dedupe_disabled_and_aclose_cancel(self) -> None:
        store = MemoryStore(self.db_path)
        store.initialize()
        _seed_vectors(store, [(_make_record("m1"), [1.0, 0.0])])

        gate = threading.Event()
        entered = threading.Event()
        orig = vector_search.prewarm_vector_corpus_sync

        def slow_prewarm(*args, **kwargs):
            entered.set()
            gate.wait(timeout=5.0)
            return orig(*args, **kwargs)

        try:
            with patch("astrbot_plugin_memory_companion.core.vector_search.prewarm_vector_corpus_sync", side_effect=slow_prewarm):
                first = store.schedule_startup_vector_corpus_warmup(provider_id="test", settle_seconds=0.0)
                second = store.schedule_startup_vector_corpus_warmup(provider_id="test", settle_seconds=0.0)
                self.assertTrue(first)
                self.assertFalse(second)
                await asyncio.to_thread(entered.wait, 2.0)
                # Closing store sets cancel event, cancels warmup tasks, and waits cleanly.
                gate.set()
                await store.aclose()
        finally:
            gate.set()
            if not store._closed:
                await store.aclose()

        # Config toggle off disables startup scheduling.
        service_off = MemoryCompanionService(
            context=None,
            config={
                "retrieval": {"embedding_enabled": True, "embedding_provider_id": "test"},
                "retrieval_advanced": {"startup_vector_warmup_enabled": False},
            },
            plugin_root=Path(ROOT),
            data_dir=self.data_dir / "off",
        )
        self.addAsyncCleanup(service_off.aclose)
        self.assertFalse(service_off.schedule_startup_vector_warmup(settle_seconds=0.0))

    async def test_prewarm_on_legacy_readonly_db_without_perf4_tables_and_main_init_wiring(self) -> None:
        legacy_db = self.data_dir / "legacy_ro.db"
        setup_store = MemoryStore(legacy_db)
        setup_store.initialize()
        _seed_vectors(setup_store, [(_make_record("m1"), [1.0, 0.0])])
        setup_store.close()

        # Drop Perf4 delta/revision tables & triggers to emulate a pre-Perf4 legacy database.
        with closing(sqlite3.connect(str(legacy_db))) as conn:
            for trig in (
                "trg_memories_vector_corpus_insert",
                "trg_memories_vector_corpus_update",
                "trg_memories_vector_corpus_delete",
            ):
                conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
            for tbl in ("vector_corpus_revision", "acl_revision", "vector_corpus_changes"):
                conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            conn.commit()

        ro_store = MemoryStore(legacy_db, read_only=True)
        ro_store.initialize()
        try:
            result = await ro_store.prewarm_vector_corpus(provider_id="test")
            self.assertTrue(result["warmed"])
            self.assertEqual(1, result["rows"])
            corpus = next(iter(ro_store._vector_corpus_cache.values()))
            self.assertIsNone(corpus.corpus_revision)
        finally:
            ro_store.close()

        # Verify MemoryCompanionPlugin.initialize() calls schedule_startup_vector_warmup()
        # in an isolated module load so sys.modules stays untouched for other test modules.
        def _fake_astrbot_modules() -> dict[str, types.ModuleType]:
            astrbot_mod = types.ModuleType("astrbot")
            api_mod = types.ModuleType("astrbot.api")
            api_mod.logger = logging.getLogger("test_perf4_plugin")
            event_mod = types.ModuleType("astrbot.api.event")
            event_mod.AstrMessageEvent = type("AstrMessageEvent", (), {})
            event_mod.MessageEventResult = type("MessageEventResult", (), {})
            filter_mod = types.ModuleType("astrbot.api.event.filter")
            filter_mod.PermissionType = SimpleNamespace(ADMIN="ADMIN", MEMBER="MEMBER")
            filter_mod.EventMessageType = SimpleNamespace(GROUP_MESSAGE="GROUP", PRIVATE_MESSAGE="PRIVATE")
            filter_mod.permission_type = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.command_group = lambda *_a, **_k: (
                lambda _fn: SimpleNamespace(command=lambda *_ca, **_ck: (lambda sub: sub))
            )
            filter_mod.command = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.on_llm_request = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.on_llm_response = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.event_message_type = lambda *_a, **_k: (lambda fn: fn)
            filter_mod.llm_tool = lambda *_a, **_k: (lambda fn: fn)
            event_mod.filter = filter_mod
            provider_mod = types.ModuleType("astrbot.api.provider")
            provider_mod.LLMResponse = type("LLMResponse", (), {})
            provider_mod.ProviderRequest = type("ProviderRequest", (), {})
            star_mod = types.ModuleType("astrbot.api.star")
            star_mod.Context = type("Context", (), {})
            star_mod.Star = type("Star", (), {"__init__": lambda self, *_a, **_k: None})
            star_mod.StarTools = SimpleNamespace(get_data_dir=lambda _name: str(self.data_dir))
            star_mod.register = lambda *_a, **_k: (lambda cls: cls)
            return {
                "astrbot": astrbot_mod,
                "astrbot.api": api_mod,
                "astrbot.api.event": event_mod,
                "astrbot.api.event.filter": filter_mod,
                "astrbot.api.provider": provider_mod,
                "astrbot.api.star": star_mod,
            }

        with patch.dict(sys.modules, _fake_astrbot_modules()):
            spec = importlib.util.spec_from_file_location(
                "astrbot_plugin_memory_companion._isolated_main_perf4",
                Path(ROOT) / "main.py",
            )
            self.assertIsNotNone(spec)
            assert spec is not None and spec.loader is not None
            isolated_main = importlib.util.module_from_spec(spec)
            isolated_main.__package__ = "astrbot_plugin_memory_companion"
            spec.loader.exec_module(isolated_main)
            plugin = object.__new__(isolated_main.MemoryCompanionPlugin)
            plugin.context = SimpleNamespace(get_llm_tool_manager=lambda: SimpleNamespace())
            plugin.companion_linkage = SimpleNamespace(start=lambda: None)
            plugin._disabled_tool_names = lambda: []
            plugin._log_disabled_tools = lambda: None
            calls: list[str] = []
            plugin.service = SimpleNamespace(
                initialize_database=AsyncMock(return_value=True),
                _ensure_lifecycle_maintenance_dispatcher=lambda: calls.append("lifecycle"),
                _ensure_portrait_daily_dispatcher=lambda: calls.append("portrait"),
                _ensure_summary_drain_dispatcher=lambda: calls.append("summary"),
                capture=SimpleNamespace(start=lambda: calls.append("capture")),
                schedule_startup_vector_warmup=lambda: calls.append("warmup") or True,
            )
            with (
                patch.object(isolated_main, "bind_event_tool_schema", return_value=True),
                patch.object(isolated_main, "bind_query_tool_schema", return_value=True),
                patch.object(isolated_main, "bind_query_tool_v3_schema", return_value=True),
                patch.object(isolated_main, "bind_source_query_v2_schema", return_value=True),
            ):
                await plugin.initialize()
            self.assertIn("warmup", calls)


class VectorCorpusDeltaAndCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.provider = _StrictQueryOnlyEmbeddingProvider([1.0, 0.0])
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
        self.ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id="u1",
            user_name="阿瓜",
            group_id="g1",
            bot_id="b1",
            persona_id="p1",
            message_text="搜索",
        )

    async def test_incremental_delta_sync_insert_update_delete_and_embedding_update(self) -> None:
        r1 = _make_record("m1", content="第一条")
        r2 = _make_record("m2", content="第二条")
        r3 = _make_record("m3", content="第三条")
        _seed_vectors(self.store, [(r1, [1.0, 0.0]), (r2, [0.5, 0.5]), (r3, [0.2, 0.9])])

        await self.store.prewarm_vector_corpus(provider_id="test")

        # Update m1 embedding, update m2 content + vector, insert m4, delete m3.
        r1_v2 = _make_record("m1", content="第一条", updated_at="2026-11-18T03:00:00+00:00")
        r2_v2 = _make_record("m2", content="第二条-已更新", updated_at="2026-11-18T03:00:00+00:00")
        r4 = _make_record("m4", content="第四条新增")
        with self.store._lock, self.store._conn:
            for rec, vec in ((r1_v2, [0.0, 1.0]), (r2_v2, [0.9, 0.1]), (r4, [0.8, 0.6])):
                self.store._conn.execute(
                    "UPDATE memories SET content=?, updated_at=? WHERE id=?",
                    (rec.content, rec.updated_at, rec.id),
                )
                if rec.id == "m4":
                    self.store._insert_memory_sync(rec, _commit=False)
                self.store._conn.execute(
                    "INSERT OR REPLACE INTO memory_embeddings"
                    "(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        rec.id,
                        "test",
                        memory_embedding_text_hash(rec),
                        2,
                        _pack_embedding_vector(vec),
                        rec.created_at,
                        rec.updated_at,
                    ),
                )
            self.store._conn.execute("DELETE FROM memories WHERE id='m3'")

        memories, scores, info = await self.engine._embedding_candidate_memories(
            "查询", self.ctx, include_pending=False,
        )
        self.assertTrue(info["embedding_corpus_hit"])
        self.assertFalse(info["embedding_corpus_full_scan"])
        self.assertGreaterEqual(info["embedding_corpus_delta_rows"], 3)
        self.assertEqual(info["embedding_corpus_delta_rows"], info["embedding_scanned_rows"])
        self.assertEqual({"m1", "m2", "m4"}, {m.id for m in memories})
        self.assertNotIn("m3", scores)
        self.assertAlmostEqual(0.0, scores["m1"], places=6)
        self.assertEqual("第二条-已更新", next(m.content for m in memories if m.id == "m2"))

    async def test_pruned_delta_log_gap_triggers_full_scan_and_prune_caps_at_8192(self) -> None:
        rows = [(_make_record(f"m{i}"), [1.0, 0.0] if i == 0 else [0.1, 0.9]) for i in range(6)]
        _seed_vectors(self.store, rows)
        await self.store.prewarm_vector_corpus(provider_id="test")

        # Insert > 8220 delta rows, verify _prune_retained_rows_sync trims table to <= 8192 rows.
        with self.store._lock, self.store._conn:
            for k in range(8220):
                self.store._conn.execute(
                    "INSERT INTO vector_corpus_changes(memory_id) VALUES(?)",
                    (f"synthetic-{k}",),
                )
            self.store._prune_retained_rows_sync(
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:00:00+00:00",
                1000,
            )
            count = self.store._conn.execute("SELECT COUNT(*) FROM vector_corpus_changes").fetchone()[0]
        self.assertEqual(8192, count)

        # Now corpus.last_change_seq < min(seq) - 1, plus bump corpus revision via real insert.
        _seed_vectors(self.store, [(_make_record("m_tail"), [0.99, 0.01])])
        memories, scores, info = await self.engine._embedding_candidate_memories(
            "查询", self.ctx, include_pending=False,
        )
        self.assertFalse(info["embedding_corpus_hit"])
        self.assertTrue(info["embedding_corpus_full_scan"])
        self.assertIn("m_tail", scores)
        self.assertEqual(7, len(memories) + (7 - len(memories)))  # top_k=4, 7 candidates exist
        self.assertEqual(4, len(memories))

    async def test_tight_budget_partial_eviction_preserves_top_recall(self) -> None:
        # 128 dims * 8 bytes = 1024 bytes per row + VectorRef overhead (~1.3KB per row).
        # With candidate_limit=2 (2 rows per block -> 4 blocks), budget=2048 evicts blocks 0..2.
        dim = 128
        self.store.vector_snapshot_cache_bytes = 2048
        self.engine.embedding_candidate_limit = 2
        self.engine.embedding_provider = _StrictQueryOnlyEmbeddingProvider([1.0] + [0.0] * (dim - 1))
        self.engine.embedding_top_k = 1
        batch = []
        for idx in range(8):
            vec = [0.95 if idx == 0 else 0.2] + [0.3] * (dim - 1)
            batch.append((_make_record(f"evict-{idx}"), vec))
        _seed_vectors(self.store, batch)
        # First query under tight budget must still surface evict-0 even though early block gets evicted.
        memories, _, info = await self.engine._embedding_candidate_memories(
            "查询", self.ctx, include_pending=False,
        )
        self.assertEqual(["evict-0"], [m.id for m in memories])
        self.assertTrue(info["embedding_snapshot_partial"])

        # Clear search cache and ensure cold rebuild under tight budget also preserves evict-0.
        self.store._vector_search_cache.clear()
        memories2, _, info2 = await self.engine._embedding_candidate_memories(
            "查询", self.ctx, include_pending=False,
        )
        self.assertEqual(["evict-0"], [m.id for m in memories2])
        self.assertTrue(info2["embedding_snapshot_partial"])

    async def test_selection_cache_reused_until_acl_or_valid_until_boundary(self) -> None:
        now = datetime.now(timezone.utc)
        future_to = (now + timedelta(seconds=30)).isoformat()
        p_rec = _make_record(
            "priv-acl",
            scope="private",
            session_id="qq:FriendMessage:u1",
            group_id="",
            visibility="private_pair",
            valid_to=future_to,
        )
        g_rec = _make_record("grp-1", content="普通群记")
        _seed_vectors(self.store, [(p_rec, [1.0, 0.0]), (g_rec, [0.5, 0.5])])
        await self.store.prewarm_vector_corpus(provider_id="test")

        # Seed a second auth entry in _vector_search_cache so removing self.ctx's snapshot
        # leaves _vector_search_cache non-empty (doesn't trigger external .clear() wipe).
        other_ctx = SessionContext(
            session_id="onebot_qq:GroupMessage:g2",
            scope="group",
            platform="qq",
            user_id="u2",
            group_id="g2",
            bot_id="b1",
            persona_id="p1",
            message_text="other",
        )
        await self.engine._embedding_candidate_memories("other", other_ctx, include_pending=False)

        # Turn 1 builds SelectionCacheEntry for self.ctx.
        m1, _, info1 = await self.engine._embedding_candidate_memories("q1", self.ctx, include_pending=False)
        self.assertTrue(info1["embedding_corpus_hit"])
        self.assertEqual(["grp-1"], [m.id for m in m1])
        corpus = next(iter(self.store._vector_corpus_cache.values()))
        self.assertEqual(2, len(corpus.selection_cache))
        # OrderedDict: last inserted entry corresponds to self.ctx.
        sel_key_ctx = list(corpus.selection_cache.keys())[-1]
        sel_obj_1 = corpus.selection_cache[sel_key_ctx]

        # Evict only self.ctx's snapshot from _vector_search_cache; corpus remains valid
        # and next search misses snapshot cache yet reuses SelectionCacheEntry without re-evaluating eligible().
        ctx_snap_keys = [k for k in self.store._vector_search_cache if k[4] == sel_key_ctx[0]]
        for k in ctx_snap_keys:
            self.store._vector_search_cache.pop(k)
        with patch.object(
            self.engine.policy, "is_visible", wraps=self.engine.policy.is_visible
        ) as visible_spy:
            m2, _, info2 = await self.engine._embedding_candidate_memories("q2", self.ctx, include_pending=False)
        self.assertFalse(info2["embedding_cache_hit"])
        self.assertTrue(info2["embedding_corpus_hit"])
        self.assertEqual(["grp-1"], [m.id for m in m2])
        self.assertIs(sel_obj_1, corpus.selection_cache[sel_key_ctx])
        # Selection itself did NOT re-scan all corpus entries (0 selection checks);
        # only post-validation of the 1 selected result ran (len(m2) == 1 < 2 corpus rows).
        self.assertEqual(len(m2), visible_spy.call_count)

        # Now grant ACL for private u1 -> group g1: bumps acl_revision (NOT vector_corpus_revision).
        await self.store.upsert_acl_rule(
            owner_scope="private",
            owner_id="u1",
            reader_scope="group",
            reader_id="g1",
            effect="allow",
        )
        m3, _, info3 = await self.engine._embedding_candidate_memories("q3", self.ctx, include_pending=False)
        self.assertEqual({"priv-acl", "grp-1"}, {m.id for m in m3})
        self.assertTrue(info3["embedding_corpus_hit"])

        # Advance both selection_time and wall clock past valid_to -> SelectionCache invalidates cleanly.
        future_dt = now + timedelta(seconds=60)
        future_ts = future_dt.timestamp()

        class _FutureDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return future_dt if tz is not None else future_dt.replace(tzinfo=None)

        with (
            patch("astrbot_plugin_memory_companion.core.retrieval.datetime", _FutureDatetime),
            patch("astrbot_plugin_memory_companion.core.retrieval.time.time", return_value=future_ts),
            patch("astrbot_plugin_memory_companion.core.vector_search.time.time", return_value=future_ts),
        ):
            m4, _, info4 = await self.engine._embedding_candidate_memories("q4", self.ctx, include_pending=False)
        self.assertEqual(["grp-1"], [m.id for m in m4])
        self.assertTrue(info4["embedding_corpus_hit"])

    async def test_external_vector_search_cache_clear_resyncs_corpus(self) -> None:
        _seed_vectors(self.store, [(_make_record("m1"), [1.0, 0.0])])
        # Populate both _vector_search_cache and _vector_corpus_cache first.
        await self.engine._embedding_candidate_memories("q0", self.ctx, include_pending=False)
        self.assertTrue(self.store._vector_search_cache)
        # Externally wipe _vector_search_cache and mutate DB.
        self.store._vector_search_cache.clear()
        _seed_vectors(self.store, [(_make_record("m2"), [0.9, 0.1])])
        memories, _, info = await self.engine._embedding_candidate_memories("q", self.ctx, include_pending=False)
        self.assertEqual({"m1", "m2"}, {m.id for m in memories})
        self.assertFalse(info["embedding_corpus_hit"])
        self.assertTrue(info["embedding_corpus_full_scan"])


class ConcurrentReadPathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def test_read_methods_and_next_summary_batch_do_not_block_on_write_lock(self) -> None:
        rec = _make_record("mem-r1")
        await self.store.insert_memory(rec)
        await self.store.upsert_acl_rule(
            owner_scope="private",
            owner_id="u1",
            reader_scope="group",
            reader_id="g1",
            effect="allow",
        )
        tl_id = await self.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:GroupMessage:g1",
            scope="group",
            subject_id="u1",
            object_id="b1",
            content="群里发言",
            metadata={"group_id": "g1", "user_name": "阿瓜"},
            occurred_at="2026-11-18T02:00:00+00:00",
        )
        await self.store.upsert_emotion_event(
            {
                "event_id": "emo-1",
                "bot_id": "b1",
                "scope": "private",
                "platform": "qq",
                "session_id": "qq:FriendMessage:u1",
                "user_id": "u1",
                "emotion_label": "warm",
                "intensity": 0.7,
                "polarity": "positive",
                "source_type": "turn",
                "evidence_text": "很开心",
                "occurred_at": "2026-11-18T02:00:00+00:00",
                "expires_at": "2026-11-25T02:00:00+00:00",
            }
        )

        held = threading.Event()
        release = threading.Event()

        def hold_write() -> None:
            with self.store._lock:
                held.set()
                release.wait(timeout=5.0)

        t = threading.Thread(target=hold_write, daemon=True)
        t.start()
        try:
            self.assertTrue(await asyncio.to_thread(held.wait, 2.0))
            mems = await asyncio.wait_for(self.store.get_memories_by_ids(["mem-r1"]), timeout=1.5)
            acls = await asyncio.wait_for(self.store.list_acl_rules(), timeout=1.5)
            tl = await asyncio.wait_for(self.store.get_timeline_by_ids([tl_id]), timeout=1.5)
            emos = await asyncio.wait_for(
                self.store.list_emotion_events(session_id="qq:FriendMessage:u1"),
                timeout=1.5,
            )
            backlog = await asyncio.wait_for(self.store.list_summary_backlog_sessions(limit=5), timeout=1.5)
            batch = await asyncio.wait_for(
                self.store.next_summary_batch("qq:GroupMessage:g1", force=True),
                timeout=1.5,
            )
            self.assertEqual(["mem-r1"], list(mems))
            self.assertEqual(1, len(acls))
            self.assertIn(tl_id, tl)
            self.assertEqual(1, len(emos))
            self.assertIsInstance(backlog, list)
            self.assertIsNone(batch)
        finally:
            release.set()
            t.join(timeout=2.0)

    async def test_next_summary_batch_sees_uncommitted_write_via_main_conn_fallback_and_mock_store(self) -> None:
        tl_id = await self.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:u1",
            scope="private",
            subject_id="u1",
            object_id="b1",
            content="hi",
            metadata={"user_name": "U"},
            occurred_at="2026-11-18T00:00:00+00:00",
        )
        # Seed uncommitted batch in main conn transaction -> _read_conn_sync must read self._conn.
        self.store._conn.execute("BEGIN IMMEDIATE")
        try:
            batch_id = self.store._create_summary_batch_sync(
                "qq:FriendMessage:u1", "private", [{"id": tl_id}], {}
            )
            batch = await self.store.next_summary_batch("qq:FriendMessage:u1", force=True)
            self.assertIsNotNone(batch)
            self.assertEqual(batch_id, batch["id"])
        finally:
            self.store._conn.rollback()

        # Verify fallback on a mock store without _read_conn_sync.
        mock_store = SimpleNamespace(
            _lock=self.store._lock,
            _conn=self.store._conn,
            _due_clause=self.store._due_clause,
            _due_params=self.store._due_params,
        )
        res = await MemoryStore.next_summary_batch(mock_store, "qq:FriendMessage:u1", force=True)
        self.assertIsNone(res)

    def test_closed_store_rejects_read_connection_helpers_without_reopening_handles(self) -> None:
        # Open all dedicated readers first, then close and verify none can be reopened.
        self.assertIsNotNone(self.store._ensure_read_connection())
        self.assertIsNotNone(self.store._ensure_timeline_read_connection())
        self.assertIsNotNone(self.store._ensure_vector_read_connection())

        self.store.close()
        self.assertTrue(self.store._closed)
        self.assertIsNone(self.store._read_conn)
        self.assertIsNone(self.store._timeline_read_conn)
        self.assertIsNone(self.store._vector_read_conn)

        with patch.object(
            self.store,
            "_open_dedicated_read_connection",
            wraps=self.store._open_dedicated_read_connection,
        ) as open_spy:
            for helper in (
                self.store._ensure_read_connection,
                self.store._ensure_timeline_read_connection,
                self.store._ensure_vector_read_connection,
            ):
                with self.assertRaises(sqlite3.ProgrammingError):
                    helper()
            with self.assertRaises(sqlite3.ProgrammingError):
                with self.store._read_conn_sync():
                    pass

        self.assertEqual(0, open_spy.call_count)
        self.assertIsNone(self.store._read_conn)
        self.assertIsNone(self.store._timeline_read_conn)
        self.assertIsNone(self.store._vector_read_conn)

        # Verify read-only stores also reject read connection access after close().
        ro_store = MemoryStore(self.store.db_path, read_only=True)
        ro_store.close()
        for helper in (
            ro_store._ensure_read_connection,
            ro_store._ensure_timeline_read_connection,
            ro_store._ensure_vector_read_connection,
        ):
            with self.assertRaises(sqlite3.ProgrammingError):
                helper()
        with self.assertRaises(sqlite3.ProgrammingError):
            with ro_store._read_conn_sync():
                pass


class SingleHopSourceCaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(Path(self._tmp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.capture = SourceCapture(self.store)
        self.generation = "gen-1"
        self.capture.activate(self.generation)
        self.identity = {
            "installation": self.capture.installation,
            "platform": "qq",
            "bot": "b1",
            "persona": "p1",
            "scope": "private",
            "session": "qq:FriendMessage:u1",
            "speaker": "u1",
            "audience": "b1",
            "direction": "incoming",
            "message": "msg-capture-1",
        }

    def test_stage_and_commit_incoming_lifecycle_idempotency_conflict_revoked_and_capacity(self) -> None:
        first = self.capture.stage_and_commit_incoming(
            self.identity,
            body="今天买了新耳机",
            source_message_at="2026-11-18T02:00:00+00:00",
            observed_at="2026-11-18T02:00:01+00:00",
            generation=self.generation,
        )
        self.assertEqual("committed", first["status"])

        # Same payload retries cleanly as idempotent committed without duplicating source rows.
        retry = self.capture.stage_and_commit_incoming(
            self.identity,
            body="今天买了新耳机",
            source_message_at="2026-11-18T02:00:00+00:00",
            observed_at="2026-11-18T02:00:01+00:00",
            generation=self.generation,
        )
        self.assertEqual("committed", retry["status"])
        self.assertEqual(first["operation"], retry["operation"])

        # Different body on same identity rejects with conflict.
        conflict = self.capture.stage_and_commit_incoming(
            self.identity,
            body="被篡改的另一句话",
            source_message_at="2026-11-18T02:00:00+00:00",
            observed_at="2026-11-18T02:00:01+00:00",
            generation=self.generation,
        )
        self.assertEqual("conflict", conflict["status"])

        # Expired deadline before write rejects without inserting committed row.
        expired = self.capture.stage_and_commit_incoming(
            {**self.identity, "message": "msg-exp"},
            body="已过期输入",
            observed_at="2026-11-18T02:00:01+00:00",
            generation=self.generation,
            expires=1.0,
        )
        self.assertEqual("expired", expired["status"])

        # Revoked source key rejects cleanly.
        revoked_id = {**self.identity, "message": "msg-rev"}
        revoked_key = self.capture.prepare(
            revoked_id, body="已撤回", observed_at="2026-11-18T02:00:01+00:00"
        )["source_key"]
        self.capture.withdraw(revoked_key)
        revoked = self.capture.stage_and_commit_incoming(
            revoked_id,
            body="已撤回",
            observed_at="2026-11-18T02:00:01+00:00",
            generation=self.generation,
        )
        self.assertEqual("excluded", revoked["status"])
        self.assertEqual("revoked", revoked["source_state"])

        # Capacity overflow returns held.
        with patch("astrbot_plugin_memory_companion.core.source_capture.MAX_PENDING_BYTES", 8):
            held = self.capture.stage_and_commit_incoming(
                {**self.identity, "message": "msg-big"},
                body="超容量的大段文本内容",
                observed_at="2026-11-18T02:00:01+00:00",
                generation=self.generation,
            )
            self.assertEqual("held", held["status"])
            self.assertEqual("capture_capacity", held["reason"])

    async def test_capture_runtime_single_hop_and_c1_monkeypatch_fallback(self) -> None:
        service = MemoryCompanionService(
            context=None,
            config={},
            plugin_root=Path(ROOT),
            data_dir=Path(self._tmp.name) / "svc",
        )
        self.addAsyncCleanup(service.aclose)
        runtime = CaptureRuntime(service)
        runtime.set_source_capture_enabled(True)
        runtime.start()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="阿瓜",
            bot_id="b1",
            persona_id="p1",
            message_id="msg-rt-1",
            message_text="今天下雨了",
        )
        ev1 = SimpleNamespace(message_str="今天下雨了", get_self_id=lambda: "b1")

        with patch.object(
            runtime.store, "stage_and_commit_incoming", wraps=runtime.store.stage_and_commit_incoming
        ) as one_hop_spy:
            res = await runtime.incoming(ev1, ctx=ctx)
        self.assertEqual("committed", res["status"])
        self.assertEqual(1, one_hop_spy.call_count)

        # Monkeypatching commit directly in runtime.store.__dict__ triggers legacy multi-hop path.
        calls: list[str] = []
        orig_commit = runtime.store.commit

        def patched_commit(*args, **kwargs):
            calls.append("patched_commit")
            return orig_commit(*args, **kwargs)

        runtime.store.commit = patched_commit  # type: ignore[method-assign]
        ctx2 = replace(ctx, message_id="msg-rt-2", message_text="明天见")
        ev2 = SimpleNamespace(message_str="明天见", get_self_id=lambda: "b1")
        res2 = await runtime.incoming(ev2, ctx=ctx2)
        self.assertEqual("committed", res2["status"])
        self.assertEqual(["patched_commit"], calls)


class CanonicalHistoryDigestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        with service_mod._LARGE_STR_DIGEST_LOCK:
            service_mod._LARGE_STR_DIGEST_CACHE.clear()
            service_mod._LARGE_STR_DIGEST_CACHE_BYTES = 0

    def test_canonical_history_digest_caches_large_base64_and_detects_edits(self) -> None:
        img_a = "data:image/png;base64," + ("A" * 2048)
        img_b = "data:image/png;base64," + ("A" * 2047) + "B"

        class _Dumpable:
            def __init__(self, role: str, img: str) -> None:
                self._role = role
                self._img = img

            def model_dump(self, mode: str = "json", exclude_none: bool = True):
                return {"role": self._role, "content": [{"type": "image_url", "url": self._img}]}

        hist_a = [_Dumpable("user", img_a), {"role": "assistant", "content": "收到"}]
        hist_b = [_Dumpable("user", img_b), {"role": "assistant", "content": "收到"}]

        with patch.object(
            service_mod, "_cached_large_str_sha256", wraps=service_mod._cached_large_str_sha256
        ):
            digest1, count1 = _canonical_history_digest(hist_a)
            digest2, count2 = _canonical_history_digest(hist_a)
            digest3, count3 = _canonical_history_digest(hist_b)

        self.assertEqual(2, count1)
        self.assertEqual(count1, count2)
        self.assertEqual(digest1, digest2)
        self.assertNotEqual(digest1, digest3)
        self.assertEqual(2, count3)

        # Verify large entry cache bounds: entries > _LARGE_DIGEST_ENTRY_MAX_BYTES are not cached.
        huge = "X" * (service_mod._LARGE_DIGEST_ENTRY_MAX_BYTES + 10)
        _ = service_mod._cached_large_str_sha256(huge)
        with service_mod._LARGE_STR_DIGEST_LOCK:
            self.assertNotIn(huge, service_mod._LARGE_STR_DIGEST_CACHE)
            self.assertLessEqual(len(service_mod._LARGE_STR_DIGEST_CACHE), service_mod._LARGE_DIGEST_CACHE_MAX_ENTRIES)
            self.assertLessEqual(service_mod._LARGE_STR_DIGEST_CACHE_BYTES, service_mod._LARGE_DIGEST_CACHE_MAX_BYTES)

    async def test_large_str_digest_cache_uses_utf8_byte_budget_and_clears_on_service_close(self) -> None:
        # CJK characters are 3 UTF-8 bytes each: verify byte accounting & cap enforcement.
        cjk_sample = "记" * 1000
        expected_bytes = len(cjk_sample.encode("utf-8"))
        self.assertEqual(3000, expected_bytes)

        digest = service_mod._cached_large_str_sha256(cjk_sample)
        self.assertEqual(hashlib.sha256(cjk_sample.encode("utf-8")).hexdigest(), digest)
        with service_mod._LARGE_STR_DIGEST_LOCK:
            self.assertIn(cjk_sample, service_mod._LARGE_STR_DIGEST_CACHE)
            self.assertEqual(expected_bytes, service_mod._LARGE_STR_DIGEST_CACHE_BYTES)

        # With a small UTF-8 byte cap, CJK strings whose char length fits but UTF-8 bytes exceed
        # the entry or cache budget must be rejected / evicted accurately.
        with (
            patch.object(service_mod, "_LARGE_DIGEST_ENTRY_MAX_BYTES", 2400),
            patch.object(service_mod, "_LARGE_DIGEST_CACHE_MAX_BYTES", 3600),
        ):
            service_mod._clear_large_str_digest_cache()
            over_entry_cjk = "忆" * 900  # 900 chars < 2400, but 2700 UTF-8 bytes > 2400
            _ = service_mod._cached_large_str_sha256(over_entry_cjk)
            with service_mod._LARGE_STR_DIGEST_LOCK:
                self.assertNotIn(over_entry_cjk, service_mod._LARGE_STR_DIGEST_CACHE)
                self.assertEqual(0, service_mod._LARGE_STR_DIGEST_CACHE_BYTES)

            cjk_a = "甲" * 700  # 2100 UTF-8 bytes
            cjk_b = "乙" * 700  # 2100 UTF-8 bytes -> must evict cjk_a under 3600-byte cap
            _ = service_mod._cached_large_str_sha256(cjk_a)
            _ = service_mod._cached_large_str_sha256(cjk_b)
            with service_mod._LARGE_STR_DIGEST_LOCK:
                self.assertNotIn(cjk_a, service_mod._LARGE_STR_DIGEST_CACHE)
                self.assertIn(cjk_b, service_mod._LARGE_STR_DIGEST_CACHE)
                self.assertEqual(2100, service_mod._LARGE_STR_DIGEST_CACHE_BYTES)

        # Deterministic cleanup on both close() and aclose().
        with tempfile.TemporaryDirectory() as tmp:
            service_sync = MemoryCompanionService(
                context=None,
                config={},
                plugin_root=Path(ROOT),
                data_dir=Path(tmp) / "sync",
            )
            _ = service_mod._cached_large_str_sha256("丙" * 600)
            with service_mod._LARGE_STR_DIGEST_LOCK:
                self.assertGreater(len(service_mod._LARGE_STR_DIGEST_CACHE), 0)
                self.assertGreater(service_mod._LARGE_STR_DIGEST_CACHE_BYTES, 0)
            service_sync.close()
            with service_mod._LARGE_STR_DIGEST_LOCK:
                self.assertEqual(0, len(service_mod._LARGE_STR_DIGEST_CACHE))
                self.assertEqual(0, service_mod._LARGE_STR_DIGEST_CACHE_BYTES)

            service_async = MemoryCompanionService(
                context=None,
                config={},
                plugin_root=Path(ROOT),
                data_dir=Path(tmp) / "async",
            )
            _ = service_mod._cached_large_str_sha256("丁" * 600)
            with service_mod._LARGE_STR_DIGEST_LOCK:
                self.assertGreater(len(service_mod._LARGE_STR_DIGEST_CACHE), 0)
            await service_async.aclose()
            with service_mod._LARGE_STR_DIGEST_LOCK:
                self.assertEqual(0, len(service_mod._LARGE_STR_DIGEST_CACHE))
                self.assertEqual(0, service_mod._LARGE_STR_DIGEST_CACHE_BYTES)

    async def test_publish_reply_memory_context_records_canonical_digest_in_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryCompanionService(
                context=None,
                config={},
                plugin_root=Path(ROOT),
                data_dir=Path(tmp),
            )
            try:
                ctx = SessionContext(
                    session_id="qq:FriendMessage:u1",
                    scope="private",
                    platform="qq",
                    user_id="u1",
                    bot_id="b1",
                    persona_id="p1",
                    message_id="m-digest-1",
                    message_text="hi",
                )
                mem = _make_record(
                    "mem-pub-1",
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    group_id="",
                    visibility="private_pair",
                )
                await service.store.insert_memory(mem)

                class _Rendered(str):
                    continuity_snapshot: dict
                    memory_refs: list

                injection = _Rendered("<memory_companion_context>...</memory_companion_context>")
                ref = memory_ref(mem)
                injection.continuity_snapshot = {
                    "continuity_refs": [{"ref_id": ref["id"], "version": ref["version"]}]
                }
                injection.memory_refs = [ref]
                img = "data:image/jpeg;base64," + ("Z" * 1024)
                req = SimpleNamespace(
                    contexts=[{"role": "user", "content": [{"type": "image_url", "url": img}]}],
                    prompt="",
                    extra_user_content_parts=[],
                )
                event = SimpleNamespace()
                expected_digest, expected_count = _canonical_history_digest(req.contexts)

                ok = await service._publish_reply_memory_context(
                    ctx, req, event=event, injection=injection, slot_map={}, strategy_id="test",
                )
                self.assertTrue(ok)
                snap = getattr(event, "memory_companion_continuity_snapshot")
                self.assertIn(f"history:{expected_digest}", snap["immediate_refs"])
                self.assertEqual(expected_count, snap["coverage"]["available_history_items"])
            finally:
                await service.aclose()


class DeferredHookPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_deferred_hook_persistence_flushes_on_aclose_and_respects_mock_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryCompanionService(
                context=None,
                config={},
                plugin_root=Path(ROOT),
                data_dir=Path(tmp) / "svc1",
            )
            try:
                completed: list[str] = []
                gate = asyncio.Event()

                async def slow_write() -> None:
                    await gate.wait()
                    completed.append("persisted")

                task = service._enqueue_hook_persistence(slow_write(), label="test-deferred")
                self.assertIsNotNone(task)
                self.assertEqual(1, len(service._hook_persistence_tasks))
                self.assertEqual([], completed)
                gate.set()
                await service.aclose()
                self.assertEqual(["persisted"], completed)
                self.assertEqual(0, len(service._hook_persistence_tasks))
            finally:
                if not service._closed:
                    await service.aclose()

            # Verify mocked _mark_injected_memories directly in service.__dict__ is awaited eagerly.
            service2 = MemoryCompanionService(
                context=None,
                config={},
                plugin_root=Path(ROOT),
                data_dir=Path(tmp) / "svc2",
            )
            try:
                mem = _make_record(
                    "mem-mock-1",
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    group_id="",
                    visibility="private_pair",
                )
                await service2.store.insert_memory(mem)
                service2._mark_injected_memories = AsyncMock()  # type: ignore[method-assign]

                class _Rendered(str):
                    continuity_snapshot: dict
                    memory_refs: list

                ref = memory_ref(mem)
                inj = _Rendered("ctx")
                inj.continuity_snapshot = {"continuity_refs": [{"ref_id": ref["id"], "version": ref["version"]}]}
                inj.memory_refs = [ref]
                ctx = SessionContext(
                    session_id="qq:FriendMessage:u1",
                    scope="private",
                    platform="qq",
                    user_id="u1",
                    bot_id="b1",
                    persona_id="p1",
                    message_id="m-eag",
                    message_text="hi",
                )
                req = SimpleNamespace(contexts=[], prompt="", extra_user_content_parts=[])
                ok = await service2._publish_reply_memory_context(
                    ctx, req, event=SimpleNamespace(), injection=inj, slot_map={}, strategy_id="test",
                )
                self.assertTrue(ok)
                service2._mark_injected_memories.assert_awaited_once_with([mem.id])
            finally:
                await service2.aclose()

            # Emotion event persistence error does not prevent injection log from persisting.
            service3 = MemoryCompanionService(
                context=None,
                config={},
                plugin_root=Path(ROOT),
                data_dir=Path(tmp) / "svc3",
            )
            try:
                with (
                    patch.object(service3.store, "upsert_emotion_event", AsyncMock(side_effect=RuntimeError("boom"))),
                    patch.object(service3.store, "add_injection_log", AsyncMock(return_value="inj-1")) as log_mock,
                ):
                    await service3._persist_post_injection_bookkeeping(
                        [{"event_id": "e1"}],
                        {
                            "session_id": "s1",
                            "scope": "private",
                            "query": "q",
                            "selected_memory_ids": [],
                            "blocked_reasons": [],
                            "injection_chars": 0,
                        },
                    )
                log_mock.assert_awaited_once()
            finally:
                await service3.aclose()


class RerankBreakerAndAclReuseTests(unittest.IsolatedAsyncioTestCase):
    def test_circuit_breaker_trips_cooldown_half_open_probe_and_cancel_release(self) -> None:
        breaker = RerankCircuitBreaker(failure_threshold=2, cooldown_seconds=30.0)
        self.assertEqual((True, False), breaker.allow_request("p1", now=100.0))
        breaker.record_failure("p1", now=101.0)
        self.assertEqual((True, False), breaker.allow_request("p1", now=102.0))
        breaker.record_failure("p1", now=103.0)

        # Open cooldown blocks callers until 133.0.
        self.assertEqual((False, False), breaker.allow_request("p1", now=120.0))
        # At expiry, only one probe is admitted.
        self.assertEqual((True, True), breaker.allow_request("p1", now=133.0))
        self.assertEqual((False, False), breaker.allow_request("p1", now=133.1))

        # Cancellation releases probe slot without re-tripping.
        breaker.release_probe("p1")
        self.assertEqual((True, True), breaker.allow_request("p1", now=133.2))

        # Probe failure re-trips cooldown immediately.
        breaker.record_failure("p1", is_probe=True, now=134.0)
        self.assertEqual((False, False), breaker.allow_request("p1", now=140.0))

        # Probe success after expiry closes circuit completely.
        self.assertEqual((True, True), breaker.allow_request("p1", now=165.0))
        breaker.record_success("p1")
        self.assertEqual((True, False), breaker.allow_request("p1", now=166.0))

    async def test_rerank_provider_circuit_short_circuits_and_truncates_error(self) -> None:
        class FailingRerankProvider:
            def __init__(self) -> None:
                self.calls = 0

            async def rerank(self, *, query: str, documents: list[str], top_n: int | None = None):
                self.calls += 1
                raise RuntimeError("X" * 350)

        provider = FailingRerankProvider()
        breaker = RerankCircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
        ctx = SessionContext(session_id="s1", scope="private", platform="qq", user_id="u1", bot_id="b1")
        candidates = [
            SearchResult(memory=_make_record(f"r{i}", content=f"item {i}"), score=1.0 - i * 0.1)
            for i in range(3)
        ]

        # Two consecutive failures across distinct per-turn RetrievalEngine instances trip breaker.
        for _ in range(2):
            engine = RetrievalEngine(
                None,
                None,
                retrieval_mode="rerank",
                rerank_provider=provider,
                rerank_provider_id="r-prov",
                rerank_circuit_breaker=breaker,
                knowledge_graph_enabled=False,
            )
            await engine._maybe_rerank_results("问题", candidates, 2)
            info = engine.last_path_info
            self.assertTrue(str(info["reason"]).startswith("rerank_error:"))
            self.assertLessEqual(len(info["reason"]), 240)
        self.assertEqual(2, provider.calls)

        # Third request skips network call with rerank_circuit_open.
        engine3 = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=provider,
            rerank_provider_id="r-prov",
            rerank_circuit_breaker=breaker,
            knowledge_graph_enabled=False,
        )
        await engine3._maybe_rerank_results("问题", candidates, 2)
        info3 = engine3.last_path_info
        self.assertEqual("rerank_circuit_open", info3["reason"])
        self.assertEqual(2, provider.calls)

        # Cancelled half-open probe must release probe slot via try/finally so a follow-up probe runs.
        with breaker._lock:
            breaker._states["r-prov"].open_until = 1.0
        probe_calls = 0
        saw_in_flight = False

        class CancellingThenRecoveringProvider:
            async def rerank(self, *, query: str, documents: list[str], top_n: int | None = None):
                nonlocal probe_calls, saw_in_flight
                probe_calls += 1
                if probe_calls == 1:
                    saw_in_flight = breaker._states["r-prov"].half_open_in_flight
                    raise asyncio.CancelledError()
                return SimpleNamespace(results=[SimpleNamespace(index=0, relevance_score=0.9)])

        recovering = CancellingThenRecoveringProvider()
        engine4 = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=recovering,
            rerank_provider_id="r-prov",
            rerank_circuit_breaker=breaker,
            knowledge_graph_enabled=False,
        )
        with self.assertRaises(asyncio.CancelledError):
            await engine4._maybe_rerank_results("问题", candidates, 2)
        self.assertTrue(saw_in_flight)
        self.assertFalse(breaker._states["r-prov"].half_open_in_flight)

        engine5 = RetrievalEngine(
            None,
            None,
            retrieval_mode="rerank",
            rerank_provider=recovering,
            rerank_provider_id="r-prov",
            rerank_circuit_breaker=breaker,
            knowledge_graph_enabled=False,
        )
        reranked = await engine5._maybe_rerank_results("问题", candidates, 2)
        self.assertEqual(2, probe_calls)
        self.assertEqual("rerank_applied", engine5.last_path_info["reason"])
        self.assertEqual(candidates[0].memory.id, reranked[0].memory.id)
        self.assertNotIn("r-prov", breaker._states)

    async def test_rank_candidates_loads_acl_state_once_and_refreshes_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                r1 = _make_record("m-acl-1", content="蓝风铃记忆")
                _seed_vectors(store, [(r1, [1.0, 0.0])])
                provider = _StrictQueryOnlyEmbeddingProvider([1.0, 0.0])
                engine = RetrievalEngine(
                    store,
                    VisibilityPolicy(),
                    embedding_enabled=True,
                    embedding_provider=provider,
                    embedding_provider_id="test",
                    embedding_candidate_limit=64,
                    embedding_top_k=4,
                    embedding_score_threshold=0.0,
                    knowledge_graph_enabled=False,
                )
                ctx = SessionContext(
                    session_id="onebot_qq:GroupMessage:g1",
                    scope="group",
                    platform="qq",
                    user_id="u1",
                    group_id="g1",
                    bot_id="b1",
                    persona_id="p1",
                    message_text="蓝风铃",
                )
                with patch.object(engine, "_acl_state", wraps=engine._acl_state) as acl_spy:
                    await engine._rank_candidates("蓝风铃", ctx)
                self.assertEqual(1, acl_spy.call_count)

                # Force one VectorSnapshotChanged retry inside _embedding_candidate_memories:
                # _acl_state() must run once in _rank_candidates and once more on attempt > 0.
                orig_search = vector_search.search_embeddings_sync
                attempt_seen = {"n": 0}

                def flaky_once(*args, **kwargs):
                    attempt_seen["n"] += 1
                    if attempt_seen["n"] == 1:
                        raise vector_search.VectorSnapshotChanged("simulated_race")
                    return orig_search(*args, **kwargs)

                with patch.object(vector_search, "search_embeddings_sync", side_effect=flaky_once):
                    with patch.object(engine, "_acl_state", wraps=engine._acl_state) as acl_retry_spy:
                        await engine._rank_candidates("蓝风铃", ctx)
                self.assertEqual(2, acl_retry_spy.call_count)
            finally:
                store.close()

    async def test_acl_revoked_during_embedding_http_call_refreshes_acl_and_never_poisons_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                priv_secret = _make_record(
                    "priv-secret",
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    group_id="",
                    visibility="private_pair",
                    content="绝对保密的蓝风铃暗语",
                )
                grp_pub = _make_record("grp-pub", content="群里公开的普通聊天")
                _seed_vectors(store, [(priv_secret, [1.0, 0.0]), (grp_pub, [0.5, 0.5])])
                await store.upsert_acl_rule(
                    owner_scope="private",
                    owner_id="u1",
                    reader_scope="group",
                    reader_id="g1",
                    effect="allow",
                )
                await store.prewarm_vector_corpus(provider_id="test")

                revoked_midflight = {"done": False}

                class _AclRevokingEmbeddingProvider:
                    async def get_embedding(self, text: str) -> list[float]:
                        if not revoked_midflight["done"]:
                            revoked_midflight["done"] = True
                            await store.upsert_acl_rule(
                                owner_scope="private",
                                owner_id="u1",
                                reader_scope="group",
                                reader_id="g1",
                                effect="deny",
                            )
                        return [1.0, 0.0]

                engine = RetrievalEngine(
                    store,
                    VisibilityPolicy(),
                    embedding_enabled=True,
                    embedding_provider=_AclRevokingEmbeddingProvider(),
                    embedding_provider_id="test",
                    embedding_candidate_limit=64,
                    embedding_top_k=4,
                    embedding_score_threshold=0.0,
                    knowledge_graph_enabled=False,
                )
                ctx = SessionContext(
                    session_id="onebot_qq:GroupMessage:g1",
                    scope="group",
                    platform="qq",
                    user_id="u1",
                    group_id="g1",
                    bot_id="b1",
                    persona_id="p1",
                    message_text="蓝风铃暗语",
                )

                # Mid-flight ACL deny must take effect immediately and never leak or poison caches.
                with patch.object(engine, "_acl_state", wraps=engine._acl_state) as acl_spy:
                    results_1, _ = await engine._rank_candidates("蓝风铃暗语", ctx)
                self.assertEqual(2, acl_spy.call_count)
                self.assertNotIn("priv-secret", [r.memory.id for r in results_1])
                self.assertIn("grp-pub", [r.memory.id for r in results_1])

                # Subsequent cached turn must also exclude priv-secret (no selection_cache / snapshot poisoning).
                results_2, _ = await engine._rank_candidates("蓝风铃暗语", ctx)
                self.assertNotIn("priv-secret", [r.memory.id for r in results_2])
                self.assertIn("grp-pub", [r.memory.id for r in results_2])
            finally:
                store.close()

    async def test_evicted_search_cache_slices_reused_when_corpus_cache_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                _seed_vectors(
                    store,
                    [
                        (_make_record("ev-1", content="第一条向量"), [1.0, 0.0]),
                        (_make_record("ev-2", content="第二条向量"), [0.6, 0.8]),
                    ],
                )
                provider = _StrictQueryOnlyEmbeddingProvider([1.0, 0.0])
                engine = RetrievalEngine(
                    store,
                    VisibilityPolicy(),
                    embedding_enabled=True,
                    embedding_provider=provider,
                    embedding_provider_id="test",
                    embedding_candidate_limit=64,
                    embedding_top_k=4,
                    embedding_score_threshold=0.0,
                    knowledge_graph_enabled=False,
                )
                ctx = SessionContext(
                    session_id="onebot_qq:GroupMessage:g1",
                    scope="group",
                    platform="qq",
                    user_id="u1",
                    group_id="g1",
                    bot_id="b1",
                    persona_id="p1",
                    message_text="向量",
                )
                await engine._embedding_candidate_memories("向量", ctx, include_pending=False)
                self.assertTrue(store._vector_search_cache)

                # Drop corpus cache while leaving the previous-revision snapshot in _vector_search_cache.
                store._vector_corpus_cache.clear()
                _seed_vectors(store, [(_make_record("ev-3", content="第三条向量"), [0.0, 1.0])])

                memories, _, info = await engine._embedding_candidate_memories(
                    "向量", ctx, include_pending=False,
                )
                self.assertEqual({"ev-1", "ev-2", "ev-3"}, {m.id for m in memories})
                self.assertTrue(info["embedding_corpus_full_scan"])
                self.assertEqual(2, info["embedding_reused_rows"])
            finally:
                store.close()

    async def test_breaker_non_finite_guards_and_pr96_rerank_timeout_synergy(self) -> None:
        nan_breaker = RerankCircuitBreaker(failure_threshold=2, cooldown_seconds=float("nan"))
        self.assertEqual(0.0, nan_breaker.cooldown_seconds)
        inf_breaker = RerankCircuitBreaker(failure_threshold=True, cooldown_seconds=float("inf"))  # type: ignore[arg-type]
        self.assertEqual(0, inf_breaker.failure_threshold)
        self.assertEqual(0.0, inf_breaker.cooldown_seconds)

        with tempfile.TemporaryDirectory() as tmp:
            service = MemoryCompanionService(
                context=None,
                config={
                    "retrieval": {
                        "mode": "rerank",
                        "rerank_timeout_ms": 6000,
                    },
                    "retrieval_advanced": {
                        "rerank_failure_cooldown_threshold": 2,
                        "rerank_failure_cooldown_seconds": 30.0,
                    },
                },
                plugin_root=Path(ROOT),
                data_dir=Path(tmp),
            )
            try:
                ctx = SessionContext(
                    session_id="qq:FriendMessage:u1",
                    scope="private",
                    platform="qq",
                    user_id="u1",
                    bot_id="b1",
                )
                fake_provider = SimpleNamespace(rerank=AsyncMock(side_effect=asyncio.TimeoutError()))
                with patch.object(
                    service,
                    "_resolve_rerank_provider",
                    AsyncMock(return_value=(fake_provider, "slow-rerank")),
                ):
                    engine = await service._retrieval_engine(ctx)
                # PR #96 timeout up to 10s cap is honored while PR #90 breaker is wired.
                self.assertEqual(6000, engine.rerank_timeout_ms)
                self.assertIs(engine.rerank_circuit_breaker, service._rerank_circuit_breaker)
                candidates = [
                    SearchResult(memory=_make_record(f"t{i}", content=f"cand {i}"), score=1.0 - i * 0.1)
                    for i in range(2)
                ]
                await engine._maybe_rerank_results("问题", candidates, 2)
                await engine._maybe_rerank_results("问题", candidates, 2)
                await engine._maybe_rerank_results("问题", candidates, 2)
                self.assertEqual(2, fake_provider.rerank.await_count)
                self.assertEqual("rerank_circuit_open", engine.last_path_info["reason"])
            finally:
                await service.aclose()

    def test_memory_revision_uncommitted_tx_and_surrogate_history_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                before = int(store._memory_revision_sync())
                store._conn.execute("BEGIN IMMEDIATE")
                try:
                    store._insert_memory_sync(_make_record("uncommitted-rev"), _commit=False)
                    during = int(store._memory_revision_sync())
                    self.assertGreater(during, before)
                finally:
                    store._conn.rollback()
                self.assertEqual(before, int(store._memory_revision_sync()))
            finally:
                store.close()

        # Short string with lone UTF-16 surrogate must hash cleanly without UnicodeEncodeError.
        digest_surr, count_surr = _canonical_history_digest([{"role": "user", "content": "hi \ud800 there"}])
        self.assertEqual(64, len(digest_surr))
        self.assertEqual(1, count_surr)

        # Cache byte cap smaller than entry cap must still prevent oversized cache entries.
        with (
            patch.object(service_mod, "_LARGE_DIGEST_ENTRY_MAX_BYTES", 4096),
            patch.object(service_mod, "_LARGE_DIGEST_CACHE_MAX_BYTES", 1024),
        ):
            service_mod._clear_large_str_digest_cache()
            _ = service_mod._cached_large_str_sha256("A" * 2048)
            with service_mod._LARGE_STR_DIGEST_LOCK:
                self.assertEqual(0, len(service_mod._LARGE_STR_DIGEST_CACHE))
                self.assertEqual(0, service_mod._LARGE_STR_DIGEST_CACHE_BYTES)


if __name__ == "__main__":
    unittest.main()
