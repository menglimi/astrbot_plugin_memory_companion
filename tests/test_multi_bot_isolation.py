"""S13：timeline / memories 的多 bot 隔离（旧库兼容）。

修复前：
- timeline 表没有 bot_id 列，两个 bot 共用同一个 session_id 时
  recent_timeline / timeline_window 会把对方的事件读出来；
- memories 只有 person_snapshot 之类用了 `owner_bot_id=? OR owner_bot_id=''`，
  list_memories 根本没有 bot 过滤，多账号数据直接串。

修复后：
- timeline 建表带 bot_id，旧库在 initialize() 里幂等 ALTER 补列，并用
  metadata 里的 owner_bot_id 回填历史行（旧行默认 ''，按「公共」处理）；
- 写入从 metadata["owner_bot_id"] 落到 bot_id；
- recent_timeline / recent_cross_window_timeline / timeline_window / list_memories
  接受可选 bot 参数，过滤条件为 `bot_id=? OR bot_id=''`：
  有归属的行只归该 bot，'' 的历史行继续可读，旧数据一条不丢。
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore


# S13 之前 timeline 的真实建表语句（没有 bot_id），用来验证旧库迁移。
LEGACY_TIMELINE_SCRIPT = """
CREATE TABLE timeline (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL DEFAULT '',
    object_id TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    message_id TEXT NOT NULL DEFAULT '',
    dedupe_key TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    summarized_at TEXT NOT NULL DEFAULT '',
    retention_class TEXT NOT NULL DEFAULT 'normal',
    import_batch_id TEXT NOT NULL DEFAULT '',
    source_sequence INTEGER NOT NULL DEFAULT 0
);
INSERT INTO timeline(id,event_type,session_id,scope,subject_id,object_id,content,metadata,occurred_at,created_at)
VALUES('legacy-a','user_message','private:u1','private','u1','','legacy bot-a line',
       '{"owner_bot_id":"bot-a"}','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00');
INSERT INTO timeline(id,event_type,session_id,scope,subject_id,object_id,content,metadata,occurred_at,created_at)
VALUES('legacy-b','user_message','private:u1','private','u1','','legacy bot-b line',
       '{"owner_bot_id":"bot-b"}','2026-01-01T00:00:01+00:00','2026-01-01T00:00:01+00:00');
INSERT INTO timeline(id,event_type,session_id,scope,subject_id,object_id,content,metadata,occurred_at,created_at)
VALUES('legacy-public','user_message','private:u1','private','u1','','legacy shared line',
       '{}','2026-01-01T00:00:02+00:00','2026-01-01T00:00:02+00:00');
"""


def run(coro):
    return asyncio.run(coro)


class TimelineBotIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = MemoryStore(Path(self.tmp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    def _add(self, content: str, bot_id: str, subject_id: str = "u1") -> str:
        metadata = {"owner_bot_id": bot_id} if bot_id else {}
        return run(
            self.store.add_timeline_event(
                event_type="user_message",
                session_id="private:u1",
                scope="private",
                subject_id=subject_id,
                object_id="",
                content=content,
                metadata=metadata,
            )
        )

    def _stored_bot_ids(self) -> dict[str, str]:
        with self.store._lock:
            rows = self.store._conn.execute(
                "SELECT content, bot_id FROM timeline"
            ).fetchall()
        return {str(row["content"]): str(row["bot_id"]) for row in rows}

    def test_recent_timeline_only_returns_own_bot_and_legacy_public_rows(self):
        self._add("bot-a secret", "bot-a")
        self._add("bot-b secret", "bot-b")
        self._add("legacy shared", "")

        stored = self._stored_bot_ids()
        self.assertEqual(stored["bot-a secret"], "bot-a")
        self.assertEqual(stored["bot-b secret"], "bot-b")
        self.assertEqual(stored["legacy shared"], "")

        rows_a = run(
            self.store.recent_timeline(
                limit=20, scope="private", session_id="private:u1", bot_id="bot-a"
            )
        )
        contents_a = {str(row["content"]) for row in rows_a}
        self.assertEqual(contents_a, {"bot-a secret", "legacy shared"})

        rows_b = run(
            self.store.recent_timeline(
                limit=20, scope="private", session_id="private:u1", bot_id="bot-b"
            )
        )
        self.assertEqual({str(row["content"]) for row in rows_b}, {"bot-b secret", "legacy shared"})

        # 不传 bot_id 时保持旧读法：全部可见，旧代码行为不变。
        rows_all = run(self.store.recent_timeline(limit=20, scope="private", session_id="private:u1"))
        self.assertEqual({str(row["content"]) for row in rows_all}, {"bot-a secret", "bot-b secret", "legacy shared"})

    def test_recent_timeline_entity_split_branch_filters_by_bot(self):
        # scope+session+entity 齐全时走 _recent_timeline_entity_split_sync 双索引分支，
        # 这条分支也必须带上 bot 过滤，否则换个调用方式又串了。
        self._add("bot-a entity line", "bot-a", subject_id="u1")
        self._add("bot-b entity line", "bot-b", subject_id="u1")
        self._add("legacy entity line", "", subject_id="u1")

        rows = run(
            self.store.recent_timeline(
                limit=20,
                scope="private",
                session_id="private:u1",
                entity_id="u1",
                bot_id="bot-a",
            )
        )
        self.assertEqual({str(row["content"]) for row in rows}, {"bot-a entity line", "legacy entity line"})

    def test_timeline_window_filters_by_bot(self):
        self._add("bot-a window line", "bot-a")
        self._add("bot-b window line", "bot-b")
        self._add("legacy window line", "")

        rows_a = run(
            self.store.timeline_window(
                start_at="2000-01-01T00:00:00+00:00",
                end_at="2100-01-01T00:00:00+00:00",
                limit=20,
                scope="private",
                session_id="private:u1",
                bot_id="bot-a",
            )
        )
        self.assertEqual({str(row["content"]) for row in rows_a}, {"bot-a window line", "legacy window line"})

        rows_b = run(
            self.store.timeline_window(
                start_at="2000-01-01T00:00:00+00:00",
                end_at="2100-01-01T00:00:00+00:00",
                limit=20,
                scope="private",
                session_id="private:u1",
                bot_id="bot-b",
            )
        )
        self.assertEqual({str(row["content"]) for row in rows_b}, {"bot-b window line", "legacy window line"})

    def test_unsummarized_timeline_window_filters_by_bot(self):
        # 摘要任务同样按 session 取事件；不按 bot 过滤会把别人的会话总结进自己的记忆。
        self._add("bot-a raw line", "bot-a")
        self._add("bot-b raw line", "bot-b")
        self._add("legacy raw line", "")

        window_a = run(
            self.store.unsummarized_timeline_window(
                session_id="private:u1", scope="private", limit=20, bot_id="bot-a"
            )
        )
        # '' 的历史行按公共数据处理，两个 bot 都还能摘要到；对方 bot 的行不可见。
        self.assertEqual(2, window_a["total"])
        self.assertEqual(
            {str(row["content"]) for row in window_a["rows"]}, {"bot-a raw line", "legacy raw line"}
        )

        window_b = run(
            self.store.unsummarized_timeline_window(
                session_id="private:u1", scope="private", limit=20, bot_id="bot-b"
            )
        )
        self.assertEqual(2, window_b["total"])
        self.assertEqual(
            {str(row["content"]) for row in window_b["rows"]}, {"bot-b raw line", "legacy raw line"}
        )


class MemoriesBotIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = MemoryStore(Path(self.tmp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    def _write_memory(self, record_id: str, bot_id: str, content: str) -> None:
        record = MemoryRecord(
            id=record_id,
            memory_type="user_fact",
            scope="private",
            session_id="private:u1",
            platform="test",
            visibility="private_pair",
            lifecycle="stable_memory",
            content=content,
            owner_bot_id=bot_id,
            subject=EntityRef(kind="user", id="u1"),
            confidence=0.9,
            importance=0.5,
        )
        # 直接走底层写入，避开跨会话去重（本测试只关心 bot 归属过滤）。
        with self.store._lock:
            with self.store._transaction_sync():
                self.store._write_memory_record_sync(record)

    def _ids(self, bot_id: str) -> set[str]:
        rows = run(self.store.list_memories(limit=100, owner_bot_id=bot_id))
        return {str(row.id) for row in rows}

    def test_list_memories_does_not_leak_across_bots_and_keeps_legacy_empty_owner(self):
        self._write_memory("mem-a", "bot-a", "bot-a 的私房记忆")
        self._write_memory("mem-b", "bot-b", "bot-b 的私房记忆")
        self._write_memory("mem-legacy", "", "旧版本没有 bot 归属的记忆")

        self.assertEqual(self._ids("bot-a"), {"mem-a", "mem-legacy"})
        self.assertEqual(self._ids("bot-b"), {"mem-b", "mem-legacy"})
        self.assertNotIn("mem-b", self._ids("bot-a"))
        self.assertNotIn("mem-a", self._ids("bot-b"))
        # 不传 owner_bot_id 时维持旧行为：全都能读到（旧调用点不用改就还能用）。
        self.assertTrue({"mem-a", "mem-b", "mem-legacy"} <= self._ids(""))


class LegacyTimelineMigrationTests(unittest.TestCase):
    def test_initialize_adds_bot_id_and_backfills_owner_bot_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(LEGACY_TIMELINE_SCRIPT)
                conn.commit()

            store = MemoryStore(db_path)
            store.initialize()
            try:
                with store._lock:
                    columns = store._table_column_names_sync("timeline")
                self.assertIn("bot_id", columns)

                rows_a = run(
                    store.recent_timeline(
                        limit=20, scope="private", session_id="private:u1", bot_id="bot-a"
                    )
                )
                self.assertEqual({str(row["content"]) for row in rows_a}, {"legacy bot-a line", "legacy shared line"})

                rows_b = run(
                    store.recent_timeline(
                        limit=20, scope="private", session_id="private:u1", bot_id="bot-b"
                    )
                )
                self.assertEqual({str(row["content"]) for row in rows_b}, {"legacy bot-b line", "legacy shared line"})

                with store._lock:
                    stored = store._conn.execute(
                        "SELECT id, bot_id FROM timeline ORDER BY id"
                    ).fetchall()
                self.assertEqual(
                    {str(row["id"]): str(row["bot_id"]) for row in stored},
                    {"legacy-a": "bot-a", "legacy-b": "bot-b", "legacy-public": ""},
                )
            finally:
                store.close()

            # 再次 initialize 必须幂等：不重复加列、不丢旧行。
            reopened = MemoryStore(db_path)
            reopened.initialize()
            try:
                with reopened._lock:
                    columns = reopened._table_column_names_sync("timeline")
                    count = reopened._conn.execute("SELECT COUNT(*) FROM timeline").fetchone()[0]
                self.assertIn("bot_id", columns)
                self.assertEqual(int(count), 3)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
