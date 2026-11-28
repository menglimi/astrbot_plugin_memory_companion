"""A1（假并行）+ A2（快照永不缓存）回归测试。

两个缺陷都在同一条检索路径上，而且都只能靠「可观测的结构事实」而不是耗时来
断言——用 sleep 卡时间的测试在 CI 上会抖，所以这里验证的是机制本身：

A1：向量扫描必须拿到**独立于候选包的只读连接与锁**。
    修复前 ``vector_search`` 调的是 ``store._read_connection_for_bundle()``，
    与候选包共用 ``_read_conn`` + ``_read_lock``；``asyncio.gather`` 里的两段
    因此首尾相接、零重叠。这里用两种方式钉死：
      1. 结构断言：两个获取器返回不同的连接对象与不同的锁对象；
      2. 行为断言：候选包持有 ``_read_lock`` 期间，向量扫描仍然能跑完
         （共享锁时会一直阻塞到超时）。
    另外补 ``_read_connection_for_bundle``/``_vector_read_connection`` 在
    ``read_only`` 库上仍复用主连接的既有语义，以及 close() 的清理。

A2：快照必须在超过旧 64MB 阈值时仍被缓存并命中。
    修复前累计 ``retained_bytes > CACHE_BYTES`` 就 ``blocks.clear()`` 且
    ``cacheable=False``，于是快照永远不发布。这里用 16384 维 × 512 行
    （≈66MB，实测 1.5s 可建好）复现「超过 64MB」的真实规模，断言：
      1. 快照被发布、``embedding_cache_retained=True``、``complete=True``；
      2. 第二轮 ``embedding_cache_hit=True`` 且 ``embedding_scanned_rows==0``；
      3. 命中结果与首次一致。
        配额耗尽时改成**按块淘汰最旧**而不是整份清空：
      4. 预算调小后 ``complete=False``、保留最新的块、``retained_ids`` 是
         candidate_ids 的子集且非空；
      5. 命中时对淘汰行做补读，结果与「不许淘汰」时逐条相同。
    配置项的默认值/上下界/非法值：
      6. ``bounded_cache_bytes`` 对 0/负数/NaN/字符串/超大值全部钳制；
      7. schema 里默认 512、范围 [64, 8192]，且 service 真的把它读进 store。
"""

from __future__ import annotations

import asyncio
import math
import sqlite3
import tempfile
import threading
import unittest
import warnings
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import vector_search
from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
    memory_embedding_text_hash,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore, _pack_embedding_vector
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


MB = 1024 * 1024


def _record(memory_id: str, *, content: str = "", session_id: str = "qq:FriendMessage:u1") -> MemoryRecord:
    return replace(
        MemoryRecord(
            id=memory_id,
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1"),
            object=EntityRef.bot_self("b1"),
            owner_bot_id="b1",
            scope="private",
            platform="qq",
            session_id=session_id,
            visibility="private_pair",
            lifecycle="stable_memory",
            content=content or f"换乘城际列车，到站时已经深夜。{memory_id}",
            metadata={"persona_id": "p1"},
            importance=0.1,
            occurred_at="2025-01-01T00:00:00+00:00",
        )
    ).ensure_defaults()


class _StoreCase(unittest.IsolatedAsyncioTestCase):
    """共享的临时库脚手架：一个可写 store + 一个只读 store。"""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.db_path = Path(self._temp.name) / "memory.db"
        self.store = MemoryStore(self.db_path)
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.ctx = SessionContext(
            scope="private", platform="qq", user_id="u1", bot_id="b1",
            persona_id="p1", session_id="qq:FriendMessage:u1",
        )

    def seed(self, records: list[tuple[MemoryRecord, list[float]]], *, provider_id: str = "test") -> None:
        with self.store._lock, self.store._conn:
            for record, vector in records:
                self.assertEqual(record.id, self.store._insert_memory_sync(record, _commit=False))
                self.store._conn.execute(
                    "INSERT INTO memory_embeddings(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (record.id, provider_id, memory_embedding_text_hash(record), len(vector),
                     _pack_embedding_vector(vector), record.created_at, record.created_at),
                )


# --------------------------------------------------------------------------- A1


class VectorScanUsesItsOwnReadPathTests(_StoreCase):
    """A1：向量扫描必须有自己的只读连接与锁，否则 gather 是假并行。"""

    def test_vector_scan_opens_a_dedicated_connection_and_lock(self) -> None:
        bundle_conn, bundle_lock = self.store._read_connection_for_bundle()
        vector_conn, vector_lock = self.store._vector_read_connection()

        # 两个获取器必须给出不同的连接与不同的锁：共用任何一项都会让
        # asyncio.gather 的两段重新变成串行（这是 A1 的根因）。
        self.assertIsNot(bundle_conn, vector_conn)
        self.assertIsNot(bundle_lock, vector_lock)
        self.assertIsNot(bundle_conn, self.store._conn)
        self.assertIsNot(vector_conn, self.store._conn)
        # 两条都是独立的 mode=ro 句柄，各自能读、都不能写。
        self.assertGreater(vector_conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0], 0)
        with self.assertRaises(sqlite3.OperationalError):
            vector_conn.execute("INSERT INTO memories(id) VALUES('x')")

    async def test_vector_scan_runs_while_the_candidate_bundle_lock_is_held(self) -> None:
        """候选包占着读锁时向量扫描仍能完成——共享锁时会阻塞到超时。"""
        self.seed([(_record("only"), [1.0, 0.0])])
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=64, embedding_top_k=4, knowledge_graph_enabled=False,
        )
        holding = threading.Event()
        release = threading.Event()

        def hold_bundle_lock() -> None:
            conn, lock = self.store._read_connection_for_bundle()
            with lock:
                holding.set()
                release.wait(5)

        holder = threading.Thread(target=hold_bundle_lock, daemon=True)
        holder.start()
        try:
            self.assertTrue(await asyncio.to_thread(holding.wait, 5))
            # 2 秒超时：旧实现等的是同一把 _read_lock，必然超时。
            memories, _scores, info = await asyncio.wait_for(engine._embedding_candidate_memories(
                "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
            ), timeout=2.0)
        finally:
            release.set()
            holder.join(5)
        self.assertEqual(["only"], [m.id for m in memories])
        self.assertEqual("applied", info["embedding_reason"])

    async def test_rank_candidates_overlaps_bundle_and_vector_scan(self) -> None:
        """候选包**持有**读锁时，向量扫描仍必须推进到打分阶段。

        这是 A1 的精确形状：仅仅「两侧都进了函数」不代表并行——旧实现里
        候选包先拿到 ``_read_lock``，向量扫描随后撞同一把锁，于是 gather 仍然
        是串行。这里让候选包在持锁期间等待向量侧真正开始打分（``block_scores``
        只在拿到锁、进事务之后才会被调用）；共用一把锁时等到超时即失败。
        """
        self.seed([(_record("only"), [1.0, 0.0])])
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), retrieval_mode="basic",
            embedding_enabled=True, embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=64, embedding_top_k=4, knowledge_graph_enabled=False,
        )
        scoring_started = threading.Event()
        overlap = False
        original_bundle = self.store._list_retrieval_candidate_bundle_sync
        original_scores = vector_search.block_scores

        def bundle_side(*args, **kwargs):
            nonlocal overlap
            conn, lock = self.store._read_connection_for_bundle()
            with lock:
                conn.execute("SELECT 1 FROM memories LIMIT 1").fetchall()
                # 只在持锁期间等：共用一把锁时这里必然等不到。
                overlap = scoring_started.wait(3)
            return original_bundle(*args, **kwargs)

        def scoring_side(block, query):
            scoring_started.set()
            return original_scores(block, query)

        with patch.object(self.store, "_list_retrieval_candidate_bundle_sync", side_effect=bundle_side), \
                patch.object(vector_search, "block_scores", side_effect=scoring_side):
            ranked, _blocked = await asyncio.wait_for(
                engine._rank_candidates("那次临时换了交通方式为什么晚到", self.ctx), timeout=30.0,
            )
        self.assertTrue(overlap, "候选包持锁期间向量扫描没能开始打分：两条读路径仍在串行")
        # 不能靠「候选包失败退回旧路径」蒙混过关。
        self.assertTrue(engine._rank_path_info["candidate_bundle"])
        self.assertIn("only", [item.memory.id for item in ranked])

    def test_read_only_store_still_reuses_the_main_connection(self) -> None:
        """A1 不得破坏 read_only 分支的既有行为。"""
        self.seed([(_record("only"), [1.0, 0.0])])
        reader = MemoryStore(self.db_path, read_only=True)
        self.addCleanup(reader.close)
        for getter in (
            reader._read_connection_for_bundle,
            reader._timeline_read_connection,
            reader._vector_read_connection,
        ):
            conn, lock = getter()
            self.assertIs(conn, reader._conn, getter.__name__)
            self.assertIs(lock, reader._lock, getter.__name__)

    def test_close_releases_the_vector_read_connection(self) -> None:
        self.store._vector_read_connection()
        self.assertIsNotNone(self.store._vector_read_conn)
        self.assertFalse(self.store.shutdown_state()["vector_read_conn_closed"])
        self.store.close()
        self.assertIsNone(self.store._vector_read_conn)
        self.assertTrue(self.store.shutdown_state()["vector_read_conn_closed"])

    def test_dedicated_read_connections_apply_read_pragmas(self) -> None:
        from astrbot_plugin_memory_companion.core.store import _sqlite_connection_pragmas

        expected = _sqlite_connection_pragmas(role="read")
        for getter in (
            self.store._read_connection_for_bundle,
            self.store._timeline_read_connection,
            self.store._vector_read_connection,
        ):
            conn, _lock = getter()
            self.assertEqual(expected["cache_size"], conn.execute("PRAGMA cache_size").fetchone()[0], getter.__name__)
            self.assertEqual(2, conn.execute("PRAGMA temp_store").fetchone()[0], getter.__name__)
            self.assertEqual(expected["mmap_size"], conn.execute("PRAGMA mmap_size").fetchone()[0], getter.__name__)

    def test_dedicated_read_connection_ignores_unsupported_read_pragma(self) -> None:
        from astrbot_plugin_memory_companion.core.store import _sqlite_connection_pragmas

        expected = _sqlite_connection_pragmas(role="read")
        real_connect = sqlite3.connect

        class _RejectMmapConn:
            def __init__(self, inner: sqlite3.Connection) -> None:
                self._inner = inner

            def execute(self, sql: str, *args, **kwargs):
                if "mmap_size" in sql:
                    raise sqlite3.OperationalError("mmap unsupported")
                return self._inner.execute(sql, *args, **kwargs)

            def __getattr__(self, name: str):
                return getattr(self._inner, name)

            def __setattr__(self, name: str, value) -> None:
                if name == "_inner":
                    super().__setattr__(name, value)
                else:
                    setattr(self._inner, name, value)

        with patch(
            "astrbot_plugin_memory_companion.core.store.sqlite3.connect",
            side_effect=lambda *a, **kw: _RejectMmapConn(real_connect(*a, **kw)),
        ):
            conn = self.store._open_dedicated_read_connection()
        try:
            self.assertEqual(expected["cache_size"], conn.execute("PRAGMA cache_size").fetchone()[0])
            self.assertEqual(2, conn.execute("PRAGMA temp_store").fetchone()[0])
        finally:
            conn.close()


# --------------------------------------------------------------------------- A2


class _LargeSnapshotCase(_StoreCase):
    """A2 的合成夹具：16384 维 × 1024 行 ≈ 66MB（float32 精度），正好越过旧的 64MB 阈值。"""

    DIMENSION = 16384
    ROWS = 1024

    def setUp(self) -> None:
        super().setUp()
        # 余弦相似度只由方向决定，稀疏基向量让 top-1 可预测且不需要随机数。
        base = [0.0] * self.DIMENSION
        base[0] = 1.0
        records = []
        for index in range(self.ROWS):
            vector = list(base)
            vector[1 + index % (self.DIMENSION - 1)] = 0.001
            records.append((_record(f"m-{index:04}"), vector))
        self.seed(records)
        self.provider = SimpleNamespace(get_embedding=AsyncMock(return_value=list(base)))
        self.engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=self.provider, embedding_provider_id="test",
            embedding_candidate_limit=64, embedding_top_k=1, knowledge_graph_enabled=False,
        )

    async def search(self):
        return await self.engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
        )


class VectorSnapshotIsActuallyCachedTests(_LargeSnapshotCase):
    async def test_snapshot_above_the_old_64mb_ceiling_is_published_and_hits(self) -> None:
        memories, _scores, info = await self.search()

        # 前提校验：这份快照真的超过了旧硬编码阈值，否则测不到 A2。
        snapshot = list(self.store._vector_search_cache.values())[0]
        self.assertGreater(snapshot.byte_size, 64 * MB,
                           "夹具没超过旧的 64MB 阈值，这条测试就测不到 A2")
        self.assertTrue(info["embedding_cache_retained"])
        self.assertFalse(info["embedding_cache_hit"])
        self.assertTrue(snapshot.complete)
        self.assertEqual(self.ROWS, info["embedding_candidates"])
        first_ids = [m.id for m in memories]
        self.assertEqual(1, len(first_ids))

        warm_memories, _scores, warm_info = await self.search()
        self.assertTrue(warm_info["embedding_cache_hit"])
        # 命中不该再扫全库：这是 A2 真正省下来的那 ~1.17 秒。
        self.assertEqual(0, warm_info["embedding_scanned_rows"])
        self.assertEqual(self.ROWS, warm_info["embedding_snapshot_rows"])
        self.assertEqual(first_ids, [m.id for m in warm_memories])
        self.assertFalse(warm_info["embedding_snapshot_partial"])


class VectorSnapshotEvictsOldestBlocksTests(_LargeSnapshotCase):
    async def test_budget_pressure_evicts_oldest_blocks_instead_of_clearing(self) -> None:
        # 预算压到「大约一块半」：一定触发淘汰，但不会退化成整份丢弃。
        one_block = 4 * MB
        with patch.object(vector_search, "CACHE_BYTES", one_block + 256 * 1024):
            _memories, _scores, info = await self.search()
            snapshot = list(self.store._vector_search_cache.values())[0]

            self.assertFalse(snapshot.complete, "超预算的快照必须标记为不完整")
            self.assertTrue(info["embedding_snapshot_partial"])
            self.assertTrue(snapshot.blocks, "至少保留一块，不能整份清空")
            self.assertLessEqual(snapshot.byte_size, one_block + 256 * 1024)
            # 保留的必须是**最新**的块：最旧的被淘汰，且淘汰是部分的。
            self.assertIsNotNone(snapshot.candidate_ids)
            self.assertEqual(self.ROWS, len(snapshot.candidate_ids))
            self.assertTrue(snapshot.retained_ids)
            self.assertLess(len(snapshot.retained_ids), len(snapshot.candidate_ids))
            # 块按写入顺序保留，因此留下的应该是尾部（最新的行）。
            kept = {ref.memory_id for block in snapshot.blocks for ref in block.refs}
            self.assertIn(f"m-{self.ROWS - 1:04}", kept, "最新的块被淘汰了，方向反了")

            # 命中时补读被淘汰的行，答案必须与「完全不淘汰」时一致。
            _m2, _s2, warm_info = await self.search()
            self.assertTrue(warm_info["embedding_cache_hit"])
            self.assertGreater(warm_info["embedding_reread_rows"], 0)

    async def test_reread_after_eviction_keeps_the_full_corpus_visible(self) -> None:
        """淘汰后命中的排名必须与一次性全扫逐条相同（语义不变）。"""
        query = self.provider.get_embedding.return_value
        reference = await self.search()
        self.store._vector_search_cache.clear()

        # 淘汰路径：小预算下先建快照，再用同一查询命中。
        with patch.object(vector_search, "CACHE_BYTES", 4 * MB + 256 * 1024):
            await self.search()
            self.store._vector_search_cache.clear()
        # 用「刚好装得下一块多一点」的预算跑两轮：第一轮淘汰+发布，第二轮命中+补读。
        with patch.object(vector_search, "CACHE_BYTES", 4 * MB + 256 * 1024):
            _first, _fs, _fi = await self.search()
            second, _ss, second_info = await self.search()
            self.assertTrue(second_info["embedding_cache_hit"])
            self.assertTrue(second_info["embedding_snapshot_partial"])
            self.assertGreater(second_info["embedding_reread_rows"], 0)
        self.assertEqual(
            ([m.id for m in reference[0]], reference[1]),
            ([m.id for m in second], _ss),
        )
        self.assertIs(query, self.provider.get_embedding.return_value)

    async def test_shrinking_budget_on_cache_hit_trims_memory_and_keeps_recall(self) -> None:
        """命中缓存后把预算调小，即使没有新写入也要立即缩容并保持召回一致。"""
        self.store.vector_snapshot_cache_bytes = vector_search.bounded_cache_bytes(512)
        ref_memories, ref_scores, ref_info = await self.search()
        self.assertFalse(ref_info["embedding_snapshot_partial"])
        full_snapshot = list(self.store._vector_search_cache.values())[0]
        self.assertTrue(full_snapshot.complete)
        self.assertIsNone(full_snapshot.candidate_ids)
        self.assertGreater(full_snapshot.byte_size, 64 * MB)
        full_blocks = len(full_snapshot.blocks)

        # 第一步缩容：512MB -> 64MB（真实面板下限），由完整快照立即裁为部分快照。
        self.store.vector_snapshot_cache_bytes = vector_search.bounded_cache_bytes(64)
        shrunk_memories, shrunk_scores, shrunk_info = await self.search()
        shrunk_snapshot = list(self.store._vector_search_cache.values())[0]
        self.assertTrue(shrunk_info["embedding_cache_hit"])
        self.assertEqual(0, shrunk_info["embedding_scanned_rows"])
        self.assertTrue(shrunk_info["embedding_snapshot_partial"])
        self.assertGreater(shrunk_info["embedding_reread_rows"], 0)
        self.assertEqual(64 * MB, shrunk_info["embedding_snapshot_budget_bytes"])
        self.assertFalse(shrunk_snapshot.complete)
        self.assertLessEqual(shrunk_snapshot.byte_size, 64 * MB)
        self.assertLess(len(shrunk_snapshot.blocks), full_blocks)
        self.assertEqual(
            ([m.id for m in ref_memories], ref_scores),
            ([m.id for m in shrunk_memories], shrunk_scores),
        )

        # 第二步缩容：64MB -> 8MB，已部分快照继续裁剪到 8MB 内，最旧块里的 top-1 仍精确召回。
        self.store.vector_snapshot_cache_bytes = 8 * MB
        tight_memories, tight_scores, tight_info = await self.search()
        tight_snapshot = list(self.store._vector_search_cache.values())[0]
        self.assertTrue(tight_info["embedding_cache_hit"])
        self.assertEqual(0, tight_info["embedding_scanned_rows"])
        self.assertTrue(tight_info["embedding_snapshot_partial"])
        self.assertEqual(
            self.ROWS - len(tight_snapshot.retained_ids),
            tight_info["embedding_reread_rows"],
        )
        self.assertEqual(8 * MB, tight_info["embedding_snapshot_budget_bytes"])
        self.assertFalse(tight_snapshot.complete)
        self.assertLessEqual(tight_snapshot.byte_size, 8 * MB)
        self.assertLess(len(tight_snapshot.blocks), len(shrunk_snapshot.blocks))
        self.assertEqual(
            ([m.id for m in ref_memories], ref_scores),
            ([m.id for m in tight_memories], tight_scores),
        )


class VectorSnapshotExcludesInvalidVectorsTests(_StoreCase):
    """坏向量（NaN / 零范数 / 损坏字节）不得进入 candidate_ids 导致部分快照反复补读。"""

    async def test_corrupted_vectors_are_not_reread_on_partial_snapshot_hits(self) -> None:
        self.seed([
            (_record("valid-0"), [1.0, 0.0]),
            (_record("bad-nan"), [math.nan, 0.0]),
            (_record("bad-zero"), [0.0, 0.0]),
            (_record("valid-1"), [0.0, 1.0]),
            (_record("bad-short"), [0.5, 0.5]),
            (_record("valid-2"), [0.6, 0.8]),
            (_record("valid-3"), [0.0, 1.0]),
        ])
        with self.store._lock, self.store._conn:
            self.store._conn.execute(
                "UPDATE memory_embeddings SET vector=? WHERE memory_id='bad-short'",
                (b"short",),
            )
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=2, embedding_top_k=1, knowledge_graph_enabled=False,
        )

        with patch.object(vector_search, "CACHE_BYTES", 100):
            cold_memories, _, cold_info = await engine._embedding_candidate_memories(
                "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
            )
            self.assertEqual(["valid-0"], [m.id for m in cold_memories])
            self.assertEqual(3, cold_info["embedding_invalid"])
            self.assertTrue(cold_info["embedding_snapshot_partial"])

            snapshot = list(self.store._vector_search_cache.values())[0]
            expected_valid = frozenset({"valid-0", "valid-1", "valid-2", "valid-3"})
            self.assertEqual(expected_valid, snapshot.candidate_ids)
            missing_valid = expected_valid - snapshot.retained_ids
            self.assertEqual(3, len(missing_valid))

            with patch.object(
                vector_search, "_normalized_bytes", wraps=vector_search._normalized_bytes
            ) as norm_spy:
                warm_memories, _, warm_info = await engine._embedding_candidate_memories(
                    "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
                )
            self.assertEqual(["valid-0"], [m.id for m in warm_memories])
            self.assertTrue(warm_info["embedding_cache_hit"])
            self.assertEqual(len(missing_valid), warm_info["embedding_reread_rows"])
            self.assertEqual(3, warm_info["embedding_invalid"])
            self.assertEqual(len(missing_valid), norm_spy.call_count)


class VectorSnapshotBudgetIsConfigurableTests(unittest.TestCase):
    """配置项的默认值 / 上下界 / 非法值钳制。"""

    def test_default_matches_the_module_constant_and_is_512mb(self) -> None:
        self.assertEqual(512 * MB, vector_search.CACHE_BYTES)
        self.assertEqual(512 * MB, vector_search.bounded_cache_bytes(512))

    def test_values_are_clamped_to_the_documented_range(self) -> None:
        cases = {
            64: 64 * MB,          # 下界本身
            1: 64 * MB,           # 低于下界 → 抬到下界
            0: 512 * MB,          # 0 = 未配置 → 默认值（不是「关掉缓存」）
            -5: 512 * MB,         # 负数 → 默认值
            8192: 8192 * MB,      # 上界本身
            999999: 8192 * MB,    # 超过上界 → 压到上界
        }
        for configured, expected in cases.items():
            with self.subTest(configured=configured):
                self.assertEqual(expected, vector_search.bounded_cache_bytes(configured))
        # 防「函数其实是个恒等映射」：钳制必须真的改变过值。
        self.assertNotEqual(vector_search.bounded_cache_bytes(999999),
                            int(999999 * MB))
        self.assertNotEqual(vector_search.bounded_cache_bytes(1), 1 * MB)

    def test_bool_values_fall_back_to_the_default(self) -> None:
        # Python 中 bool 是 int 子类，True==1 若不拦截会被转成 64MB 下界。
        for configured in (True, False):
            with self.subTest(configured=configured):
                self.assertEqual(512 * MB, vector_search.bounded_cache_bytes(configured))

    def test_non_numeric_and_non_finite_values_fall_back_to_the_default(self) -> None:
        for configured in (None, "", "not a number", math.nan, math.inf, -math.inf, object()):
            with self.subTest(configured=configured):
                self.assertEqual(512 * MB, vector_search.bounded_cache_bytes(configured))
        # 反向对照：合法数字不得被当成非法值吃掉。
        self.assertEqual(256 * MB, vector_search.bounded_cache_bytes(256))
        self.assertEqual(256 * MB, vector_search.bounded_cache_bytes("256"))

    def test_store_override_wins_over_the_module_default(self) -> None:
        store = SimpleNamespace(vector_snapshot_cache_bytes=123 * MB)
        self.assertEqual(123 * MB, vector_search.cache_budget_bytes(store))
        for value in (None, 0, -1, True, "512"):
            with self.subTest(value=value):
                self.assertEqual(vector_search.CACHE_BYTES,
                                 vector_search.cache_budget_bytes(
                                     SimpleNamespace(vector_snapshot_cache_bytes=value)))

    def test_schema_declares_the_key_with_matching_bounds(self) -> None:
        import json

        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        item = schema["retrieval_advanced"]["items"]["vector_snapshot_cache_mb"]
        self.assertEqual("int", item["type"])
        self.assertEqual(512, item["default"])
        self.assertEqual(vector_search.MIN_CACHE_BYTES // MB, item["min"])
        self.assertEqual(vector_search.MAX_CACHE_BYTES // MB, item["max"])
        self.assertEqual("向量快照缓存上限（MB）", item["description"])
        self.assertEqual(item["min"], item["slider"]["min"])
        self.assertEqual(item["max"], item["slider"]["max"])

    def test_service_reads_the_key_through_the_existing_config_path(self) -> None:
        """service 必须把 retrieval_advanced 的值注入 store，而不是只声明键。"""
        import inspect

        from astrbot_plugin_memory_companion.core import service as service_module

        source = inspect.getsource(service_module.MemoryCompanionService._retrieval_engine)
        self.assertIn("retrieval_advanced.vector_snapshot_cache_mb", source)
        self.assertIn("vector_snapshot_cache_bytes", source)
        self.assertIn("bounded_cache_bytes", source)
        # 走的是既有 ConfigView 读取路径（同一个 config.int），没有新造一套。
        self.assertIn("self.config.int(", source)
        self.assertEqual(1024, ConfigView({"retrieval_advanced": {"vector_snapshot_cache_mb": 1024}})
                         .int("retrieval_advanced.vector_snapshot_cache_mb", 512))
        # 缺键时落回调用点给的默认值，与其它 retrieval_advanced 项一致。
        self.assertEqual(512, ConfigView({}).int("retrieval_advanced.vector_snapshot_cache_mb", 512))


class CrossSessionSharedVectorReuseTests(_StoreCase):
    """跨会话复用已归一化向量，且不破坏会话隔离、版本校验与单预算约束。"""

    async def test_second_session_reuses_normalized_vectors_without_weakening_eligibility(self) -> None:
        only_a = replace(
            _record("only-a", session_id="qq:FriendMessage:u1"),
            subject=EntityRef(kind="user", id="u1"),
        ).ensure_defaults()
        only_b = replace(
            _record("only-b", session_id="qq:FriendMessage:u2"),
            subject=EntityRef(kind="user", id="u2"),
        ).ensure_defaults()
        shared_1 = replace(
            _record("shared-1", session_id="qq:GroupMessage:g_common"),
            scope="group",
            group_id="g_common",
            visibility="group_public",
            subject=EntityRef(kind="user", id="u_common"),
        ).ensure_defaults()
        shared_2 = replace(
            _record("shared-2", session_id="qq:GroupMessage:g_common"),
            scope="group",
            group_id="g_common",
            visibility="group_public",
            subject=EntityRef(kind="user", id="u_common"),
        ).ensure_defaults()
        secret_c = replace(
            _record("secret-c", session_id="qq:FriendMessage:u3"),
            subject=EntityRef(kind="user", id="u3"),
        ).ensure_defaults()

        # shared-1 故意存入未归一化向量 [3.0, 4.0]，验证复用后的余弦分数仍为精确 0.6。
        self.seed([
            (only_a, [1.0, 0.0]),
            (only_b, [1.0, 0.0]),
            (shared_1, [3.0, 4.0]),
            (shared_2, [0.0, 1.0]),
            (secret_c, [1.0, 0.0]),
        ])
        await self.store.upsert_acl_rule(
            owner_scope="private", owner_id="u1", reader_scope="group", reader_id="g1", effect="allow",
        )
        await self.store.upsert_acl_rule(
            owner_scope="private", owner_id="u2", reader_scope="group", reader_id="g2", effect="allow",
        )

        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=64, embedding_top_k=8,
            embedding_score_threshold=0.0, knowledge_graph_enabled=False,
        )
        ctx_a = SessionContext(
            scope="group", platform="qq", user_id="u1", group_id="g1",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g1",
        )
        ctx_b = SessionContext(
            scope="group", platform="qq", user_id="u2", group_id="g2",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g2",
        )
        ctx_c = SessionContext(
            scope="group", platform="qq", user_id="u3", group_id="g3",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g3",
        )

        # 会话 A 冷启动：建好快照并归一化 only-a / shared-1 / shared-2。
        m_a, scores_a, info_a = await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", ctx_a, include_pending=False,
        )
        self.assertEqual(["only-a", "shared-1", "shared-2"], [m.id for m in m_a])
        self.assertAlmostEqual(0.6, scores_a["shared-1"], places=6)
        self.assertFalse(info_a["embedding_cache_hit"])
        self.assertEqual(0, info_a["embedding_reused_rows"])

        # 会话 B（不同 session_id）：必须复用 shared-1/shared-2，仅补读并归一化 only-b，且绝对看不到 only-a/secret-c。
        vector_conn, _ = self.store._vector_read_connection()
        traced_sql: list[str] = []
        vector_conn.set_trace_callback(traced_sql.append)
        try:
            with patch.object(
                vector_search, "_normalized_bytes", wraps=vector_search._normalized_bytes
            ) as norm_spy:
                m_b, scores_b, info_b = await engine._embedding_candidate_memories(
                    "那次临时换了交通方式为什么晚到", ctx_b, include_pending=False,
                )
        finally:
            vector_conn.set_trace_callback(None)

        self.assertEqual(["only-b", "shared-1", "shared-2"], [m.id for m in m_b])
        self.assertNotIn("only-a", [m.id for m in m_b])
        self.assertNotIn("secret-c", [m.id for m in m_b])
        self.assertAlmostEqual(0.6, scores_b["shared-1"], places=6)
        self.assertAlmostEqual(0.0, scores_b["shared-2"], places=6)
        self.assertFalse(info_b["embedding_cache_hit"])
        self.assertEqual(2, info_b["embedding_reused_rows"])
        self.assertEqual(1, norm_spy.call_count)
        blob_queries = [sql for sql in traced_sql if "SELECT memory_id, vector" in sql]
        self.assertEqual(1, len(blob_queries))
        self.assertIn("only-b", blob_queries[0])
        self.assertNotIn("shared-1", blob_queries[0])
        self.assertNotIn("shared-2", blob_queries[0])

        # 会话 C（仅能看到 shared-1/shared-2）：全量命中跨会话复用，零 BLOB 读盘、零归一化。
        traced_sql.clear()
        vector_conn.set_trace_callback(traced_sql.append)
        try:
            with patch.object(
                vector_search, "_normalized_bytes", wraps=vector_search._normalized_bytes
            ) as norm_spy_c:
                m_c, scores_c, info_c = await engine._embedding_candidate_memories(
                    "那次临时换了交通方式为什么晚到", ctx_c, include_pending=False,
                )
        finally:
            vector_conn.set_trace_callback(None)

        self.assertEqual(["shared-1", "shared-2"], [m.id for m in m_c])
        self.assertAlmostEqual(0.6, scores_c["shared-1"], places=6)
        self.assertEqual(2, info_c["embedding_reused_rows"])
        self.assertEqual(0, norm_spy_c.call_count)
        self.assertEqual([], [sql for sql in traced_sql if "SELECT memory_id, vector" in sql])

        # 再次命中会话 C 自身快照时，走 cache_hit，不计入跨会话复用行数。
        m_c2, _s_c2, info_c2 = await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", ctx_c, include_pending=False,
        )
        self.assertEqual(["shared-1", "shared-2"], [m.id for m in m_c2])
        self.assertTrue(info_c2["embedding_cache_hit"])
        self.assertEqual(0, info_c2["embedding_reused_rows"])

    async def test_different_max_text_chars_or_version_mismatch_does_not_reuse_snapshot_bytes(self) -> None:
        shared = replace(
            _record("shared-short", session_id="qq:GroupMessage:g_common", content="短文本"),
            scope="group",
            group_id="g_common",
            visibility="group_public",
            subject=EntityRef(kind="user", id="u_common"),
        ).ensure_defaults()
        self.seed([(shared, [1.0, 0.0])])
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=64, embedding_top_k=4,
            embedding_max_text_chars=1200, knowledge_graph_enabled=False,
        )
        ctx_a = SessionContext(
            scope="group", platform="qq", user_id="u1", group_id="g1",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g1",
        )
        ctx_b = SessionContext(
            scope="group", platform="qq", user_id="u2", group_id="g2",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g2",
        )
        await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", ctx_a, include_pending=False,
        )
        # 即使文本未超 300 字使 text_hash 相同，max_text_chars 不同时仍不跨配置复用。
        engine.embedding_max_text_chars = 300
        m_b, _, info_b = await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", ctx_b, include_pending=False,
        )
        self.assertEqual(["shared-short"], [m.id for m in m_b])
        self.assertEqual(0, info_b["embedding_reused_rows"])

        # 同 max_text_chars 下若缓存 ref 的 updated_at 与当前记录不一致，也绝不复用旧向量。
        engine.embedding_max_text_chars = 1200
        key_a = next(iter(self.store._vector_search_cache))
        snap_a = self.store._vector_search_cache[key_a]
        stale_block = vector_search.VectorBlock(
            refs=tuple(replace(ref, updated_at="1999-01-01T00:00:00+00:00") for ref in snap_a.blocks[0].refs),
            values=snap_a.blocks[0].values,
            dimension=snap_a.blocks[0].dimension,
        )
        self.store._vector_search_cache = {
            key_a: replace(snap_a, blocks=(stale_block,)),
        }
        m_b2, _, info_b2 = await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", ctx_b, include_pending=False,
        )
        self.assertEqual(["shared-short"], [m.id for m in m_b2])
        self.assertEqual(0, info_b2["embedding_reused_rows"])

    async def test_single_budget_evicts_older_session_snapshot_after_reuse(self) -> None:
        shared_records = [
            (
                replace(
                    _record(f"shared-{i:02d}", session_id="qq:GroupMessage:g_common"),
                    scope="group",
                    group_id="g_common",
                    visibility="group_public",
                    subject=EntityRef(kind="user", id="u_common"),
                ).ensure_defaults(),
                [1.0 if i == 0 else 0.0, 0.0 if i == 0 else 1.0],
            )
            for i in range(6)
        ]
        self.seed(shared_records)
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=2, embedding_top_k=2,
            embedding_score_threshold=0.0, knowledge_graph_enabled=False,
        )
        ctx_a = SessionContext(
            scope="group", platform="qq", user_id="u1", group_id="g1",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g1",
        )
        ctx_b = SessionContext(
            scope="group", platform="qq", user_id="u2", group_id="g2",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g2",
        )

        # 预算仅够容纳单份快照：会话 B 复用会话 A 的全部块后，单预算淘汰会话 A，总缓存不超限。
        m_a, _, info_a = await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", ctx_a, include_pending=False,
        )
        self.assertEqual(6, info_a["embedding_candidates"])
        snap_a_bytes = sum(s.byte_size for s in self.store._vector_search_cache.values())

        self.store.vector_snapshot_cache_bytes = snap_a_bytes + 16
        m_b, _, info_b = await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", ctx_b, include_pending=False,
        )
        self.assertEqual([m.id for m in m_a], [m.id for m in m_b])
        self.assertEqual(6, info_b["embedding_reused_rows"])
        self.assertEqual(1, len(self.store._vector_search_cache))
        self.assertLessEqual(
            sum(s.byte_size for s in self.store._vector_search_cache.values()),
            self.store.vector_snapshot_cache_bytes,
        )


class VectorSnapshotWarmupOnCancelTests(_StoreCase):
    """冷未命中被钩子超时取消后，后台单飞预热并安全关闭。"""

    def _seed_sample(self, count: int = 6) -> RetrievalEngine:
        records = [
            (_record(f"w-{i:02d}"), [1.0 if i == 0 else 0.0, 0.0 if i == 0 else 1.0])
            for i in range(count)
        ]
        self.seed(records)
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        return RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=2, embedding_top_k=2,
            embedding_score_threshold=0.0, knowledge_graph_enabled=False,
        )

    async def test_cold_miss_timeout_cancellation_warms_snapshot_for_next_turn(self) -> None:
        engine = self._seed_sample()
        first_entered = threading.Event()
        release_first = threading.Event()
        original_search = vector_search.search_embeddings_sync
        call_count = 0

        def gated_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_entered.set()
                release_first.wait(5.0)
            return original_search(*args, **kwargs)

        with patch.object(vector_search, "search_embeddings_sync", side_effect=gated_search):
            async def run_first() -> None:
                await engine._embedding_candidate_memories(
                    "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
                )

            task = asyncio.create_task(run_first())
            self.assertTrue(await asyncio.to_thread(first_entered.wait, 5.0))
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(task, timeout=0.05)

            # 第 1 轮被取消后缓存仍为空，但单飞后台预热已挂上。
            self.assertEqual({}, self.store._vector_search_cache)
            self.assertEqual(1, len(self.store._vector_warmup_tasks))
            warmup_task, _cancel_event = next(iter(self.store._vector_warmup_tasks.values()))

            # 放行第 1 轮被取消线程，让其感知 cancelled 并释放锁，由后台预热建好快照。
            release_first.set()
            await asyncio.wait_for(warmup_task, timeout=5.0)
            await asyncio.sleep(0)

        self.assertEqual(2, call_count)
        self.assertEqual({}, self.store._vector_warmup_tasks)
        self.assertEqual(1, len(self.store._vector_search_cache))

        # 第 2 轮直接命中缓存且零全库扫描。
        memories, _scores, info = await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
        )
        self.assertEqual(["w-00"], [m.id for m in memories][:1])
        self.assertTrue(info["embedding_cache_hit"])
        self.assertEqual(0, info["embedding_scanned_rows"])

    async def test_concurrent_cold_miss_cancellations_launch_single_flight_warmup(self) -> None:
        engine = self._seed_sample()
        both_entered = threading.Event()
        release_cancelled = threading.Event()
        warmup_entered = threading.Event()
        release_warmup = threading.Event()
        original_search = vector_search.search_embeddings_sync
        lock = threading.Lock()
        call_count = 0

        def gated_search(*args, **kwargs):
            nonlocal call_count
            with lock:
                call_count += 1
                idx = call_count
                if idx == 2:
                    both_entered.set()
            if idx in (1, 2):
                release_cancelled.wait(5.0)
            elif idx == 3:
                # 只有单飞预热（第 3 次调用）会进入这里；若并发堆叠则会多出第 4 次。
                warmup_entered.set()
                release_warmup.wait(5.0)
            return original_search(*args, **kwargs)

        schedule_results: list[bool] = []
        original_schedule = self.store.schedule_vector_snapshot_warmup

        def spy_schedule(**kwargs):
            res = original_schedule(**kwargs)
            schedule_results.append(res)
            return res

        with patch.object(vector_search, "search_embeddings_sync", side_effect=gated_search), \
                patch.object(self.store, "schedule_vector_snapshot_warmup", side_effect=spy_schedule):
            t1 = asyncio.create_task(engine._embedding_candidate_memories(
                "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
            ))
            t2 = asyncio.create_task(engine._embedding_candidate_memories(
                "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
            ))
            self.assertTrue(await asyncio.to_thread(both_entered.wait, 5.0))
            t1.cancel()
            t2.cancel()
            results = await asyncio.gather(t1, t2, return_exceptions=True)
            self.assertTrue(all(isinstance(r, asyncio.CancelledError) for r in results))

            # 两次并发取消只允许调度 1 个单飞 warmup 任务。
            self.assertEqual([True, False], schedule_results)
            self.assertEqual(1, len(self.store._vector_warmup_tasks))
            warmup_task, _cancel_event = next(iter(self.store._vector_warmup_tasks.values()))

            release_cancelled.set()
            self.assertTrue(await asyncio.to_thread(warmup_entered.wait, 5.0))
            # 预热还在飞时，再按同一 key 调度仍必须去重拒绝。
            self.assertFalse(self.store.schedule_vector_snapshot_warmup(
                warmup_key=next(iter(self.store._vector_warmup_tasks)),
                provider_id="test",
                query=[1.0, 0.0],
                expected_revision=await self.store.memory_revision(),
                authorization_key=(),
                eligible=lambda _m: True,
                include_pending=False,
                top_k=2,
                threshold=0.0,
                batch_size=2,
                max_text_chars=1200,
                selection_time=0.0,
            ))
            release_warmup.set()
            await asyncio.wait_for(warmup_task, timeout=5.0)
            await asyncio.sleep(0)

        # 总调用数：t1 + t2 + 1 次单飞预热（共 3 次），绝无两次预热堆叠。
        self.assertEqual(3, call_count)
        self.assertEqual({}, self.store._vector_warmup_tasks)
        memories, _scores, info = await engine._embedding_candidate_memories(
            "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
        )
        self.assertEqual(["w-00"], [m.id for m in memories][:1])
        self.assertTrue(info["embedding_cache_hit"])
        self.assertEqual(0, info["embedding_scanned_rows"])

        # 缓存里已有有效快照时，直接返回 False 不再重复调度预热。
        cache_key = next(iter(self.store._vector_search_cache))
        snap = self.store._vector_search_cache[cache_key]
        self.assertFalse(self.store.schedule_vector_snapshot_warmup(
            warmup_key=cache_key,
            provider_id=cache_key[0],
            query=[1.0, 0.0],
            expected_revision=snap.revision,
            authorization_key=cache_key[4],
            eligible=lambda _m: True,
            include_pending=cache_key[2],
            top_k=2,
            threshold=0.0,
            batch_size=2,
            max_text_chars=cache_key[3],
            selection_time=0.0,
        ))
        self.assertEqual({}, self.store._vector_warmup_tasks)

    async def test_aclose_and_close_cancel_pending_warmup_without_warnings(self) -> None:
        self._seed_sample(count=2)
        revision = await self.store.memory_revision()

        async def run_scenario(use_aclose: bool) -> None:
            temp_dir = tempfile.TemporaryDirectory()
            self.addCleanup(temp_dir.cleanup)
            store = MemoryStore(Path(temp_dir.name) / "warmup_close.db")
            store.initialize()
            self.addCleanup(store.close)
            with store._lock, store._conn:
                rec = _record("close-1")
                store._insert_memory_sync(rec, _commit=False)
                store._conn.execute(
                    "INSERT INTO memory_embeddings(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (rec.id, "test", memory_embedding_text_hash(rec), 2,
                     _pack_embedding_vector([1.0, 0.0]), rec.created_at, rec.created_at),
                )
            rev = await store.memory_revision()
            entered = threading.Event()
            observed_cancel_set = False

            def hanging_search(*_args, **kwargs):
                nonlocal observed_cancel_set
                entered.set()
                cancel_evt = kwargs["cancelled"]
                observed_cancel_set = cancel_evt.wait(5.0)
                raise RuntimeError("embedding_search_cancelled")

            with patch.object(vector_search, "search_embeddings_sync", side_effect=hanging_search):
                scheduled = store.schedule_vector_snapshot_warmup(
                    warmup_key=("test", 2, False, 1200, ("k",)),
                    provider_id="test",
                    query=[1.0, 0.0],
                    expected_revision=rev,
                    authorization_key=("k",),
                    eligible=lambda _m: True,
                    include_pending=False,
                    top_k=2,
                    threshold=0.0,
                    batch_size=2,
                    max_text_chars=1200,
                    selection_time=0.0,
                )
                self.assertTrue(scheduled)
                self.assertTrue(await asyncio.to_thread(entered.wait, 5.0))
                warmup_task, _ = next(iter(store._vector_warmup_tasks.values()))

                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    if use_aclose:
                        await store.aclose()
                    else:
                        store.close()
                        await asyncio.sleep(0)

                self.assertTrue(observed_cancel_set)
                self.assertTrue(warmup_task.done())
                self.assertEqual({}, store._vector_warmup_tasks)
                self.assertTrue(store._closed)
                self.assertEqual([], [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)])
                # 关闭后再次调度必须被拒绝。
                self.assertFalse(store.schedule_vector_snapshot_warmup(
                    warmup_key=("test", 2, False, 1200, ("after",)),
                    provider_id="test",
                    query=[1.0, 0.0],
                    expected_revision=rev,
                    authorization_key=("after",),
                    eligible=lambda _m: True,
                    include_pending=False,
                    top_k=2,
                    threshold=0.0,
                    batch_size=2,
                    max_text_chars=1200,
                    selection_time=0.0,
                ))

        await run_scenario(use_aclose=True)
        await run_scenario(use_aclose=False)
        # 无运行中事件循环或空查询向量时直接返回 False。
        self.assertFalse(await asyncio.to_thread(
            self.store.schedule_vector_snapshot_warmup,
            warmup_key=("no-loop",),
            provider_id="test",
            query=[1.0, 0.0],
            expected_revision=revision,
            authorization_key=(),
            eligible=lambda _m: True,
            include_pending=False,
            top_k=2,
            threshold=0.0,
            batch_size=2,
            max_text_chars=1200,
            selection_time=0.0,
        ))
        self.assertFalse(self.store.schedule_vector_snapshot_warmup(
            warmup_key=("empty-query",),
            provider_id="test",
            query=[],
            expected_revision="0",
            authorization_key=(),
            eligible=lambda _m: True,
            include_pending=False,
            top_k=2,
            threshold=0.0,
            batch_size=2,
            max_text_chars=1200,
            selection_time=0.0,
        ))


class BlockProfileDecouplingAndCachedRowTests(_StoreCase):
    """block_profile 与快照构建正交解耦，且 _build_blocks 优先使用缓存轻量解析器。"""

    def _profile_record(
        self,
        memory_id: str,
        *,
        memory_type: str = "user_profile",
        content: str = "",
        scope: str = "private",
        visibility: str = "private_pair",
        group_id: str = "",
        session_id: str = "qq:FriendMessage:u1",
    ) -> MemoryRecord:
        return replace(
            _record(memory_id, content=content, session_id=session_id),
            memory_type=memory_type,
            scope=scope,
            group_id=group_id,
            visibility=visibility,
        ).ensure_defaults()

    async def test_greeting_warmup_and_recall_share_snapshot_across_block_profile_switches(self) -> None:
        profile = self._profile_record("profile-1", memory_type="user_profile", content="喜欢冰美式")
        pref = self._profile_record("pref-1", memory_type="user_preference", content="周末喜欢看电影")
        summary = _record("summary-1", content="昨天在地铁站口一起聊天")
        self.seed([
            (profile, [1.0, 0.0]),
            (pref, [0.8, 0.6]),
            (summary, [0.6, 0.8]),
        ])
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=64, embedding_top_k=2,
            embedding_score_threshold=0.0, knowledge_graph_enabled=False,
        )

        # 第 1 轮：问候语触发 block_profile=True，冷建完整快照，同时过滤掉 profile 记忆。
        self.assertTrue(engine._query_blocks_profile_retrieval("你好"))
        m1, _s1, info1 = await engine._embedding_candidate_memories(
            "你好", self.ctx, include_pending=False,
        )
        self.assertFalse(info1["embedding_cache_hit"])
        self.assertTrue(info1["embedding_cache_retained"])
        self.assertEqual(3, info1["embedding_candidates"])
        self.assertEqual(["summary-1"], [m.id for m in m1])

        self.assertEqual(1, len(self.store._vector_search_cache))
        snapshot = next(iter(self.store._vector_search_cache.values()))
        ref_types = {ref.memory_id: ref.memory_type for block in snapshot.blocks for ref in block.refs}
        self.assertEqual(
            {
                "profile-1": "user_profile",
                "pref-1": "user_preference",
                "summary-1": "conversation_summary",
            },
            ref_types,
        )

        # 第 2 轮：回忆问句触发 block_profile=False，命中同一快照（零扫描）并正确召回 profile 记忆。
        recall_query = "你还记得我平时喜欢喝什么吗"
        self.assertFalse(engine._query_blocks_profile_retrieval(recall_query))
        m2, scores2, info2 = await engine._embedding_candidate_memories(
            recall_query, self.ctx, include_pending=False,
        )
        self.assertTrue(info2["embedding_cache_hit"])
        self.assertEqual(0, info2["embedding_scanned_rows"])
        self.assertEqual(["profile-1", "pref-1"], [m.id for m in m2])
        self.assertAlmostEqual(1.0, scores2["profile-1"], places=6)

        # 第 3 轮：切回 block_profile=True，再次命中同一快照（零扫描）且不返回任何 profile 记忆。
        self.assertTrue(engine._query_blocks_profile_retrieval("早安"))
        m3, _s3, info3 = await engine._embedding_candidate_memories(
            "早安", self.ctx, include_pending=False,
        )
        self.assertTrue(info3["embedding_cache_hit"])
        self.assertEqual(0, info3["embedding_scanned_rows"])
        self.assertEqual(["summary-1"], [m.id for m in m3])
        self.assertEqual(1, len(self.store._vector_search_cache))

    async def test_partial_snapshot_reread_and_cross_session_reuse_preserve_memory_type_filtering(self) -> None:
        self.seed([
            (self._profile_record("profile-old", memory_type="user_profile"), [1.0, 0.0]),
            (_record("summary-mid-1"), [0.0, 1.0]),
            (_record("summary-mid-2"), [0.0, 1.0]),
            (_record("summary-mid-3"), [0.6, 0.8]),
            (self._profile_record("profile-new", memory_type="user_habit"), [0.8, 0.6]),
            (_record("summary-new"), [0.0, 1.0]),
        ])
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=2, embedding_top_k=3,
            embedding_score_threshold=0.0, knowledge_graph_enabled=False,
        )

        with patch.object(vector_search, "CACHE_BYTES", 100):
            m1, _s1, info1 = await engine._embedding_candidate_memories(
                "你好", self.ctx, include_pending=False,
            )
            self.assertFalse(info1["embedding_cache_hit"])
            self.assertTrue(info1["embedding_snapshot_partial"])
            self.assertEqual(6, info1["embedding_candidates"])
            self.assertNotIn("profile-old", [m.id for m in m1])
            self.assertNotIn("profile-new", [m.id for m in m1])
            self.assertEqual("summary-mid-3", m1[0].id)

            # 第 2 轮放开 profile：部分快照既从保留块召回 profile-new，也通过补读召回被淘汰的 profile-old。
            m2, _s2, info2 = await engine._embedding_candidate_memories(
                "我还记得哪些生活习惯", self.ctx, include_pending=False,
            )
            self.assertTrue(info2["embedding_cache_hit"])
            self.assertEqual(0, info2["embedding_scanned_rows"])
            self.assertGreater(info2["embedding_reread_rows"], 0)
            self.assertEqual(["profile-old", "profile-new", "summary-mid-3"], [m.id for m in m2])

            # 第 3 轮切回 block_profile=True：补读同样遵循 excluded_memory_types 过滤。
            m3, _s3, info3 = await engine._embedding_candidate_memories(
                "你好呀", self.ctx, include_pending=False,
            )
            self.assertTrue(info3["embedding_cache_hit"])
            self.assertEqual(0, info3["embedding_scanned_rows"])
            self.assertNotIn("profile-old", [m.id for m in m3])
            self.assertNotIn("profile-new", [m.id for m in m3])

        # 跨会话复用：群 g1 在 block_profile=True 下建快照，群 g2 在 block_profile=False 下复用向量仍能召回画像。
        self.store._vector_search_cache.clear()
        shared_profile = self._profile_record(
            "shared-profile",
            memory_type="user_profile",
            scope="group",
            visibility="group_public",
            group_id="g_common",
            session_id="qq:GroupMessage:g_common",
        )
        self.seed([(shared_profile, [1.0, 0.0])])
        ctx_g1 = SessionContext(
            scope="group", platform="qq", user_id="u1", group_id="g1",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g1",
        )
        ctx_g2 = SessionContext(
            scope="group", platform="qq", user_id="u2", group_id="g2",
            bot_id="b1", persona_id="p1", session_id="qq:GroupMessage:g2",
        )
        m_g1, _s_g1, _i_g1 = await engine._embedding_candidate_memories("你好", ctx_g1, include_pending=False)
        self.assertNotIn("shared-profile", [m.id for m in m_g1])

        m_g2, _s_g2, info_g2 = await engine._embedding_candidate_memories(
            "群里还记得他喜欢什么吗", ctx_g2, include_pending=False,
        )
        self.assertGreater(info_g2["embedding_reused_rows"], 0)
        self.assertIn("shared-profile", [m.id for m in m_g2])

        m_g2_blocked, _s_g2b, info_g2b = await engine._embedding_candidate_memories(
            "早安", ctx_g2, include_pending=False,
        )
        self.assertTrue(info_g2b["embedding_cache_hit"])
        self.assertEqual(0, info_g2b["embedding_scanned_rows"])
        self.assertNotIn("shared-profile", [m.id for m in m_g2_blocked])

    async def test_cancelled_greeting_warmup_feeds_subsequent_recall_turn(self) -> None:
        self.seed([
            (self._profile_record("profile-warm", memory_type="user_profile"), [1.0, 0.0]),
            (_record("summary-warm"), [0.6, 0.8]),
        ])
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=2, embedding_top_k=2,
            embedding_score_threshold=0.0, knowledge_graph_enabled=False,
        )
        first_entered = threading.Event()
        release_first = threading.Event()
        original_search = vector_search.search_embeddings_sync
        call_count = 0

        def gated_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_entered.set()
                release_first.wait(5.0)
            return original_search(*args, **kwargs)

        with patch.object(vector_search, "search_embeddings_sync", side_effect=gated_search):
            task = asyncio.create_task(engine._embedding_candidate_memories(
                "你好", self.ctx, include_pending=False,
            ))
            self.assertTrue(await asyncio.to_thread(first_entered.wait, 5.0))
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(task, timeout=0.05)

            self.assertEqual(1, len(self.store._vector_warmup_tasks))
            warmup_task, _ = next(iter(self.store._vector_warmup_tasks.values()))
            release_first.set()
            await asyncio.wait_for(warmup_task, timeout=5.0)
            await asyncio.sleep(0)

        self.assertEqual(2, call_count)
        m2, _s2, info2 = await engine._embedding_candidate_memories(
            "你还记得我平时喜欢什么吗", self.ctx, include_pending=False,
        )
        self.assertTrue(info2["embedding_cache_hit"])
        self.assertEqual(0, info2["embedding_scanned_rows"])
        self.assertEqual(["profile-warm", "summary-warm"], [m.id for m in m2])

    async def test_build_blocks_prefers_cached_row_light_parser_with_expected_revision(self) -> None:
        self.seed([
            (_record("row-1"), [1.0, 0.0]),
            (_record("row-2"), [0.0, 1.0]),
        ])
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1.0, 0.0]))
        engine = RetrievalEngine(
            self.store, VisibilityPolicy(), embedding_enabled=True,
            embedding_provider=provider, embedding_provider_id="test",
            embedding_candidate_limit=16, embedding_top_k=2,
            embedding_score_threshold=0.0, knowledge_graph_enabled=False,
        )
        expected_rev = await self.store.memory_revision()
        orig_from_row_light = MemoryRecord.from_row_light
        cached_calls: list[tuple[str, str, str]] = []

        def cached_parser(row, *, revision: str = "") -> MemoryRecord:
            cached_calls.append((row["id"], revision, type(row).__name__))
            return orig_from_row_light(row)

        self.store._cached_from_row_light = cached_parser
        try:
            with patch.object(MemoryRecord, "from_row_light", side_effect=orig_from_row_light) as fallback_spy:
                memories, _scores, info = await engine._embedding_candidate_memories(
                    "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
                )
        finally:
            delattr(self.store, "_cached_from_row_light")

        self.assertEqual(["row-1", "row-2"], [m.id for m in memories])
        self.assertEqual(2, info["embedding_candidates"])
        self.assertEqual(0, fallback_spy.call_count)
        self.assertEqual(
            {("row-1", expected_rev, "Row"), ("row-2", expected_rev, "Row")},
            set(cached_calls),
        )

        # 未暴露 _cached_from_row_light 时直接将 sqlite3.Row 传给 MemoryRecord.from_row_light，不做 dict 拷贝。
        self.store._vector_search_cache.clear()
        with patch.object(MemoryRecord, "from_row_light", side_effect=orig_from_row_light) as fallback_spy:
            memories2, _scores2, _info2 = await engine._embedding_candidate_memories(
                "那次临时换了交通方式为什么晚到", self.ctx, include_pending=False,
            )
        self.assertEqual(["row-1", "row-2"], [m.id for m in memories2])
        self.assertEqual(2, fallback_spy.call_count)
        self.assertTrue(all(isinstance(call.args[0], sqlite3.Row) for call in fallback_spy.call_args_list))


if __name__ == "__main__":
    unittest.main()
