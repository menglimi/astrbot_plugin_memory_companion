"""候选捆绑加载（只读连接 + 单线程一次读取）单元测试。

覆盖 optimization_plan.md §6.1/§6.2：
- 捆绑结果与传统四路读取逐源等价；
- 关键词回退语义保持（FTS 候选不足才跑 LIKE 扫描）；
- 只读连接拒绝写入；只读 store 复用主连接；
- 捆绑失败时 _rank_candidates 回退到传统读取路径。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def _memory(
    mid: str,
    content: str,
    *,
    scope: str = "private",
    session_id: str = "s1",
    subject_id: str = "u1",
    importance: float = 0.5,
    lifecycle: str = "summarized",
    review_status: str = "auto",
    visibility: str = "shareable",
) -> MemoryRecord:
    return MemoryRecord(
        id=mid,
        memory_type="observation",
        scope=scope,
        session_id=session_id,
        content=content,
        importance=importance,
        lifecycle=lifecycle,
        review_status=review_status,
        visibility=visibility,
        subject=EntityRef("user", subject_id, "用户", "unknown"),
        object=EntityRef("bot", "bot1", "机器人", "unknown"),
        occurred_at="2026-08-25T07:00:00+00:00",
        created_at="2026-08-25T07:00:00+00:00",
        updated_at="2026-08-25T07:00:00+00:00",
    )


def _ids(records) -> list[str]:
    return [record.id for record in records]


class CandidateBundleStoreTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        self._db_path = Path(temp_dir.name) / "memory.db"
        return store

    def seed(self, store: MemoryStore) -> None:
        records = [
            _memory("m1", "今天天气很好，适合散步", importance=0.9),
            _memory("m2", "明天要上班，记得带伞", importance=0.7),
            _memory("m3", "周末一起看电影", importance=0.5, session_id="s2"),
            _memory("m4", "已归档的旧事", lifecycle="archived"),
            _memory("m5", "待审核的天气记录", review_status="pending"),
            _memory("m6", "群里的天气讨论", scope="group", session_id="g1", subject_id="g1"),
        ]
        for record in records:
            store._insert_memory_sync(record)

    async def test_bundle_matches_legacy_sources(self) -> None:
        store = self.make_store()
        self.seed(store)

        bundle = await store.list_retrieval_candidate_bundle(
            materialize_limit=100,
            current_window={"scope": "private", "session_id": "s1", "user_id": "u1", "group_id": "", "limit": 50},
            fts_terms=["天气"],
            fts_limit=50,
            keyword_terms=["天气"],
            keyword_limit=50,
            keyword_fallback_min_fts=0,
            time_window=("2026-08-25T00:00:00+00:00", "2026-08-26T00:00:00+00:00", 50),
            include_pending=False,
        )

        legacy_materialized = await store.list_candidate_memories(limit=100, include_pending=False)
        legacy_window = await store.list_current_window_candidate_memories(
            scope="private", session_id="s1", user_id="u1", group_id="", limit=50, include_pending=False
        )
        legacy_fts = await store.list_fts_candidate_memories(["天气"], limit=50, include_pending=False)
        legacy_time = await store.list_time_window_candidate_memories(
            "2026-08-25T00:00:00+00:00", "2026-08-26T00:00:00+00:00", limit=50, include_pending=False
        )

        self.assertEqual(_ids(bundle["ranked_candidates"]), _ids(legacy_materialized))
        self.assertEqual(_ids(bundle["current_window_candidates"]), _ids(legacy_window))
        self.assertEqual(_ids(bundle["fts_candidates"]), _ids(legacy_fts))
        self.assertEqual(_ids(bundle["time_window_candidates"]), _ids(legacy_time))
        # from_row_light (bundle) must be field-for-field identical to from_row
        # (legacy) for every row written through the store — the semantic
        # equivalence contract of the light read path.
        self.assertEqual(bundle["ranked_candidates"], legacy_materialized)
        self.assertEqual(bundle["current_window_candidates"], legacy_window)
        self.assertEqual(bundle["fts_candidates"], legacy_fts)
        self.assertEqual(bundle["time_window_candidates"], legacy_time)
        self.assertNotIn("m4", _ids(bundle["ranked_candidates"]))
        self.assertNotIn("m5", _ids(bundle["ranked_candidates"]))

    async def test_bot_personal_archive_rows_are_excluded_from_regular_candidates(self) -> None:
        store = self.make_store()
        self.seed(store)
        bridge_row = _memory("bot-personal-1", "今天的天气很好，适合散步", importance=1.0)
        bridge_row.source_plugin = "bot_personal_bridge"
        bridge_row.visibility = "bot_self"
        store._insert_memory_sync(bridge_row)

        bundle = await store.list_retrieval_candidate_bundle(
            materialize_limit=100,
            current_window={"scope": "private", "session_id": "s1", "user_id": "u1", "group_id": "", "limit": 50},
            fts_terms=["天气"],
            fts_limit=50,
            keyword_terms=["天气"],
            keyword_limit=50,
            keyword_fallback_min_fts=50,
            time_window=("2026-08-25T00:00:00+00:00", "2026-08-26T00:00:00+00:00", 50),
            include_pending=False,
        )
        for key in ("ranked_candidates", "current_window_candidates", "fts_candidates", "keyword_candidates", "time_window_candidates"):
            self.assertNotIn("bot-personal-1", _ids(bundle[key]))

    async def test_legacy_placeholder_content_is_excluded_even_with_old_source(self) -> None:
        store = self.make_store()
        self.seed(store)
        legacy = _memory("legacy-placeholder", "Bot Personal archive reference [schedule_fragment]", importance=1.0)
        legacy.source_plugin = "memory_companion"
        store._insert_memory_sync(legacy)

        candidates = await store.list_keyword_candidate_memories(
            ["schedule_fragment"], limit=50, include_pending=False
        )
        self.assertNotIn("legacy-placeholder", _ids(candidates))

    def test_startup_cleans_placeholder_indexes_but_keeps_archive_row(self) -> None:
        store = self.make_store()
        bridge_row = _memory("bridge-index", "Bot Personal archive reference [schedule_fragment]")
        bridge_row.source_plugin = "bot_personal_bridge"
        store._insert_memory_sync(bridge_row)
        store._conn.execute(
            "INSERT INTO memory_fts(memory_id, search_text) VALUES(?, ?)",
            (bridge_row.id, bridge_row.content),
        )
        store._conn.execute(
            """INSERT INTO memory_embeddings(
                   memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (bridge_row.id, "provider", "hash", 1, "[0.1]", "now", "now"),
        )
        store._conn.commit()

        store.initialize()

        self.assertIsNotNone(store._conn.execute(
            "SELECT 1 FROM memories WHERE id=?", (bridge_row.id,)
        ).fetchone())
        self.assertIsNone(store._conn.execute(
            "SELECT 1 FROM memory_fts WHERE memory_id=?", (bridge_row.id,)
        ).fetchone())
        self.assertIsNone(store._conn.execute(
            "SELECT 1 FROM memory_embeddings WHERE memory_id=?", (bridge_row.id,)
        ).fetchone())

    def test_time_window_expression_indexes_support_each_date_predicate(self) -> None:
        store = self.make_store()
        expected = {
            "occurred_at": "idx_memories_jd_occurred_at",
            "created_at": "idx_memories_jd_created_at",
            "updated_at": "idx_memories_jd_updated_at",
        }

        predicates = " OR ".join(
            f"(julianday({column}) >= julianday(?) AND julianday({column}) < julianday(?))"
            for column in expected
        )
        params = ("2026-08-25T00:00:00+00:00", "2026-08-26T00:00:00+00:00") * len(expected)
        plan = store._conn.execute(
            f"EXPLAIN QUERY PLAN SELECT id FROM memories WHERE {predicates}", params
        ).fetchall()
        plan_details = "\n".join(str(row["detail"]) for row in plan)

        for index_name in expected.values():
            self.assertIn(index_name, plan_details, plan_details)

    async def test_direct_candidate_filter_blocks_placeholder_memory(self) -> None:
        store = self.make_store()
        bridge_row = _memory("bridge-direct", "Bot Personal archive reference [schedule_fragment]")
        bridge_row.source_plugin = "bot_personal_bridge"
        engine = RetrievalEngine(store, VisibilityPolicy())

        visible, blocked = await engine.filter_visible_candidates(
            [bridge_row],
            SessionContext(scope="private", session_id="s1", user_id="u1"),
        )

        self.assertEqual([], visible)
        self.assertEqual("placeholder_memory", blocked[0]["reason"])

    def test_from_row_light_matches_from_row_for_stored_rows(self) -> None:
        store = self.make_store()
        # Seed a record carrying sensitive-looking metadata to prove the light
        # path (no re-redaction) still equals the normalized stored value.
        store._insert_memory_sync(
            _memory(
                "sensitive-1",
                "我的 api_key 是 sk_live_abc123 请勿泄露",
                importance=0.95,
            )
        )
        store._insert_memory_sync(_memory("plain-1", "今天天气很好", importance=0.4))
        with store._lock:
            rows = store._conn.execute("SELECT * FROM memories ORDER BY id").fetchall()
        for row in rows:
            self.assertEqual(
                MemoryRecord.from_row_light(row),
                MemoryRecord.from_row(row),
            )

    async def test_keyword_fallback_semantics(self) -> None:
        store = self.make_store()
        self.seed(store)

        triggered = await store.list_retrieval_candidate_bundle(
            materialize_limit=100,
            current_window={},
            fts_terms=["天气"],
            fts_limit=50,
            keyword_terms=["天气"],
            keyword_limit=50,
            keyword_fallback_min_fts=10,
            time_window=None,
            include_pending=False,
        )
        self.assertTrue(triggered["keyword_fallback_used"])
        legacy_keyword = await store.list_keyword_candidate_memories(["天气"], limit=50, include_pending=False)
        self.assertEqual(_ids(triggered["keyword_candidates"]), _ids(legacy_keyword))
        self.assertGreater(len(triggered["keyword_candidates"]), 0)

        suppressed = await store.list_retrieval_candidate_bundle(
            materialize_limit=100,
            current_window={},
            fts_terms=["天气"],
            fts_limit=50,
            keyword_terms=["天气"],
            keyword_limit=50,
            keyword_fallback_min_fts=0,
            time_window=None,
            include_pending=False,
        )
        self.assertFalse(suppressed["keyword_fallback_used"])
        self.assertEqual(suppressed["keyword_candidates"], [])

    def test_read_connection_rejects_writes(self) -> None:
        store = self.make_store()
        self.seed(store)
        conn = store._ensure_read_connection()
        self.assertIsNot(conn, store._conn)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO memories(id) VALUES('x')")
        # 主连接不受影响
        with store._lock:
            count = store._conn.execute("SELECT count(*) FROM memories").fetchone()[0]
        self.assertEqual(count, 6)

    def test_read_only_store_reuses_main_connection(self) -> None:
        store = self.make_store()
        self.seed(store)
        ro_store = MemoryStore(self._db_path, read_only=True)
        self.addCleanup(ro_store.close)
        conn, lock = ro_store._read_connection_for_bundle()
        self.assertIs(conn, ro_store._conn)
        self.assertIs(lock, ro_store._lock)

    def test_close_releases_read_connection(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        store._ensure_read_connection()
        self.assertIsNotNone(store._read_conn)
        store.close()
        self.assertIsNone(store._read_conn)


class CandidateBundleFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_rank_candidates_falls_back_when_bundle_fails(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        store._insert_memory_sync(_memory("m1", "今天天气很好，适合散步", importance=0.9))

        async def broken_bundle(**_kwargs):
            raise RuntimeError("bundle unavailable")

        store.list_retrieval_candidate_bundle = broken_bundle
        engine = RetrievalEngine(
            store=store,
            policy=VisibilityPolicy(),
            retrieval_mode="basic",
            knowledge_graph_enabled=False,
        )
        ctx = SessionContext(scope="private", session_id="s1", user_id="u1")
        results, blocked = await engine._rank_candidates("天气", ctx)
        self.assertIn("m1", {item.memory.id for item in results})
        self.assertFalse(engine._rank_path_info.get("candidate_bundle"))

    async def test_rank_candidates_uses_bundle_when_available(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        store._insert_memory_sync(_memory("m1", "今天天气很好，适合散步", importance=0.9))

        engine = RetrievalEngine(
            store=store,
            policy=VisibilityPolicy(),
            retrieval_mode="basic",
            knowledge_graph_enabled=False,
        )
        ctx = SessionContext(scope="private", session_id="s1", user_id="u1")
        results, _blocked = await engine._rank_candidates("天气", ctx)
        self.assertIn("m1", {item.memory.id for item in results})
        self.assertTrue(engine._rank_path_info.get("candidate_bundle"))


if __name__ == "__main__":
    unittest.main()
