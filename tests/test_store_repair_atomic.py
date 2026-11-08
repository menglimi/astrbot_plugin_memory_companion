"""S2：_repair_internal_control_tables_sync 重建控制表时必须不丢 marker。

修复前是裸 DROP TABLE schema_metadata / retrieval_revision，没有事务也没有
commit：进程在 DROP 和 CREATE 之间挂掉，schema_version 和一整排 backfill
marker 就没了，下次启动会重做全库备份 + 全表回填。

这里用 sqlite3 直接造「旧 schema + 有 marker 行的库」，再走 initialize 里真实
的 repair 路径，断言：
1. 重建后所有旧 key 都还在（不只是 schema_version）；
2. 重建中途抛错时整段事务回滚，旧表和 marker 原样保留；
3. 极端情况下旧表被弄丢，内存快照也能把 marker 写回去。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.store import MemoryStore


LEGACY_SCRIPT = """
CREATE TABLE schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    legacy_required TEXT NOT NULL DEFAULT ''
);
INSERT INTO schema_metadata(key,value,legacy_required)
VALUES('schema_version','foreign-v1','required');
INSERT INTO schema_metadata(key,value,legacy_required)
VALUES('legacy_backfill_marker','keep-me','required');
INSERT INTO schema_metadata(key,value,legacy_required)
VALUES('sensitive_redaction_version','0','required');

CREATE TABLE retrieval_revision (
    singleton INTEGER PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0,
    legacy_required TEXT NOT NULL DEFAULT ''
);
INSERT INTO retrieval_revision(singleton,revision,legacy_required)
VALUES(1,7,'required');
"""


class RepairControlTablesAtomicTests(unittest.IsolatedAsyncioTestCase):
    def make_legacy_db(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "memory.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(LEGACY_SCRIPT)
        finally:
            conn.close()
        return db_path

    def read_schema_markers(self, db_path: Path) -> dict[str, str]:
        # store 仍持有连接时也能从另一个连接读到已提交状态。
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(schema_metadata)")
            }
            self.assertIn("key", columns)
            rows = conn.execute("SELECT key, value FROM schema_metadata").fetchall()
            return {row["key"]: row["value"] for row in rows}

    def read_table_columns(self, db_path: Path, table: str) -> set[str]:
        with closing(sqlite3.connect(db_path)) as conn:
            return {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }

    def read_revision(self, db_path: Path) -> int:
        with closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute(
                "SELECT revision FROM retrieval_revision WHERE singleton=1"
            ).fetchone()
            return int(row[0]) if row is not None else -1

    async def test_repair_keeps_every_legacy_marker_and_revision(self) -> None:
        db_path = self.make_legacy_db()
        store = MemoryStore(db_path)
        self.addCleanup(store.close)
        store.initialize()

        markers = self.read_schema_markers(db_path)
        # 自定义 marker 不会被 initialize 里别的步骤覆盖，必须原样保留。
        self.assertEqual("keep-me", markers.get("legacy_backfill_marker"))
        self.assertIn("schema_version", markers)
        # 旧 schema 里的额外列必须已被换掉（新旧表都要真换，而不是只补列）。
        self.assertEqual(
            {"key", "value", "updated_at"},
            self.read_table_columns(db_path, "schema_metadata"),
        )
        self.assertEqual(
            {"singleton", "revision"},
            self.read_table_columns(db_path, "retrieval_revision"),
        )
        # 旧 revision 不能被清零（后续 trigger 只会往上加）。
        self.assertGreaterEqual(self.read_revision(db_path), 7)

    async def test_failure_midway_rolls_back_and_keeps_markers(self) -> None:
        db_path = self.make_legacy_db()
        store = MemoryStore(db_path)
        self.addCleanup(store.close)

        # 第一张表已经重建完、第二张表开始抛错：整段事务必须回滚。
        with patch.object(
            store,
            "_rebuild_retrieval_revision_sync",
            side_effect=RuntimeError("simulated crash during repair"),
        ):
            with self.assertRaises(RuntimeError):
                store.initialize()

        markers = self.read_schema_markers(db_path)
        self.assertEqual("keep-me", markers.get("legacy_backfill_marker"))
        self.assertIn("schema_version", markers)
        # 回滚后旧表结构也还在，说明不是「先删了再说」。
        self.assertIn(
            "legacy_required", self.read_table_columns(db_path, "schema_metadata")
        )

    async def test_restore_snapshot_writes_markers_back_after_table_loss(self) -> None:
        db_path = self.make_legacy_db()
        store = MemoryStore(db_path)
        self.addCleanup(store.close)

        with store._lock:
            old_columns = store._table_column_names_sync("schema_metadata")
            snapshot = [
                dict(row)
                for row in store._conn.execute(
                    "SELECT * FROM schema_metadata"
                ).fetchall()
            ]
            # 模拟最坏情况：旧表已经没了（裸 DROP 之后崩溃）。
            store._conn.execute("DROP TABLE schema_metadata")
            store._restore_schema_metadata_snapshot_sync(snapshot, old_columns)
            store._conn.commit()

        markers = self.read_schema_markers(db_path)
        self.assertEqual("keep-me", markers.get("legacy_backfill_marker"))
        self.assertEqual("foreign-v1", markers.get("schema_version"))
