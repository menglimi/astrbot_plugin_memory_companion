"""V-3 regressions for the store projection, batch queue and cache work."""
from __future__ import annotations

import inspect
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    utc_now,
)
from astrbot_plugin_memory_companion.core.store import MemoryStore

SESSION_ID = "qq:FriendMessage:u1"


class StoreProjectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory_companion.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def _timeline(self, content: str = "小王和我聊了今天喝的无糖拿铁。") -> str:
        return await self.store.add_timeline_event(
            event_type="user_message",
            session_id=SESSION_ID,
            scope="private",
            subject_id="u1",
            object_id="b1",
            content=content,
        )

    async def _batch_with_event(self, content: str = "小王和我聊了今天喝的无糖拿铁。") -> tuple[str, str]:
        event_id = await self._timeline(content)
        rows = list((await self.store.get_timeline_by_ids([event_id])).values())
        batch_id = await self.store.create_summary_batch(SESSION_ID, "private", rows)
        return batch_id, event_id

    async def _insert_archive_memory(self) -> None:
        await self.store.insert_memory(
            MemoryRecord(
                id="archive-row",
                memory_type="bot_personal_reference",
                subject=EntityRef(kind="unknown"),
                object=EntityRef(kind="unknown"),
                scope="private",
                session_id="bot_personal_archive",
                visibility="private_pair",
                lifecycle="stable_memory",
                source_plugin="bot_personal_bridge",
                content="bot personal archive reference [dream]",
            )
        )

    async def _insert_native_memory(self) -> None:
        await self.store.insert_memory(
            MemoryRecord(
                id="native-private",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self(bot_id="b1"),
                scope="private",
                session_id=SESSION_ID,
                visibility="private_pair",
                lifecycle="stable_memory",
                content="正常私聊记忆",
            )
        )

    # P0-2：backup_async 必须离开事件循环线程，同步版本保持不变。
    async def test_backup_async_runs_off_the_event_loop_thread(self) -> None:
        threads: list[int] = []
        original = self.store.backup

        def spy(suffix: str = "") -> Path:
            threads.append(threading.get_ident())
            return original(suffix)

        self.store.backup = spy
        target = await self.store.backup_async(".v3_test")
        self.assertEqual(1, len(threads))
        self.assertNotEqual(threading.get_ident(), threads[0])
        self.assertTrue(Path(target).is_file())

        sync_target = self.store.backup(".v3_sync")
        self.assertEqual(threading.get_ident(), threads[-1])
        self.assertTrue(Path(sync_target).is_file())

    # P1-1：热路径读投影，直写数据库的旁路会被后台对账修复。
    async def test_hot_acl_read_uses_projection_and_reconcile_heals_direct_writes(self) -> None:
        self.assertEqual(
            {"capture_enabled": None, "recall_enabled": None},
            self.store.get_scope_feature_override_sync("private", SESSION_ID),
        )
        await self.store.upsert_acl_policy(
            window_scope="private",
            window_id=SESSION_ID,
            read_mode="whitelist",
            share_mode="whitelist",
            capture_enabled=False,
            recall_enabled=True,
        )
        self.assertEqual(
            {"capture_enabled": False, "recall_enabled": True},
            self.store.get_scope_feature_override_sync("private", SESSION_ID),
        )

        # 绕过写路径的直写：投影保持权威，直到后台对账发现 revision 变化。
        self.store._conn.execute(
            "INSERT INTO memory_acl_policies(id, window_scope, window_id, read_mode, share_mode,"
            " capture_enabled, recall_enabled, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            ("acl_direct", "private", "qq:FriendMessage:u2", "whitelist", "whitelist", 0, 1, "", ""),
        )
        self.store._conn.commit()
        self.assertEqual(
            {"capture_enabled": None, "recall_enabled": None},
            self.store.get_scope_feature_override_sync("private", "qq:FriendMessage:u2"),
        )
        result = self.store.reconcile_caches_sync()
        self.assertTrue(result["changed"])
        self.assertEqual(
            {"capture_enabled": False, "recall_enabled": True},
            self.store.get_scope_feature_override_sync("private", "qq:FriendMessage:u2"),
        )
        self.assertFalse(self.store.reconcile_caches_sync()["changed"])

    # P0-3：SAVEPOINT 回滚不得把未提交的覆盖写进投影。
    async def test_savepoint_rollback_leaves_no_dirty_projection(self) -> None:
        with self.store._lock:
            with self.store._transaction_sync():
                try:
                    with self.store._transaction_sync():
                        self.store._upsert_acl_policy_sync(
                            "private",
                            SESSION_ID,
                            "whitelist",
                            "whitelist",
                            True,
                            True,
                            _commit=False,
                        )
                        raise RuntimeError("injected savepoint failure")
                except RuntimeError:
                    pass
                self.assertEqual(
                    {"capture_enabled": None, "recall_enabled": None},
                    self.store.get_scope_feature_override_sync("private", SESSION_ID),
                )
        self.assertEqual(
            {"capture_enabled": None, "recall_enabled": None},
            self.store.get_scope_feature_override_sync("private", SESSION_ID),
        )
        row = self.store._conn.execute(
            "SELECT COUNT(*) FROM memory_acl_policies WHERE window_id=?", (SESSION_ID,)
        ).fetchone()
        self.assertEqual(0, int(row[0] or 0))

    async def test_transactional_acl_write_publishes_after_commit(self) -> None:
        with self.store._lock:
            with self.store._transaction_sync():
                self.store._upsert_acl_policy_sync(
                    "private",
                    SESSION_ID,
                    "whitelist",
                    "whitelist",
                    False,
                    True,
                    _commit=False,
                )
                self.assertEqual(
                    {"capture_enabled": None, "recall_enabled": None},
                    self.store.get_scope_feature_override_sync("private", SESSION_ID),
                )
        self.assertEqual(
            {"capture_enabled": False, "recall_enabled": True},
            self.store.get_scope_feature_override_sync("private", SESSION_ID),
        )

    # P0-3：清库必须同时清掉投影与已注册缓存。
    async def test_clear_all_memory_data_empties_acl_projection(self) -> None:
        await self.store.upsert_acl_policy(
            window_scope="private",
            window_id=SESSION_ID,
            read_mode="whitelist",
            share_mode="whitelist",
            capture_enabled=True,
            recall_enabled=True,
        )
        cleared: list[str] = []
        self.store.register_invalidation("v3_probe", lambda: cleared.append("hit"))
        await self.store.clear_all_memory_data()
        self.assertEqual({}, self.store._acl_feature_override_cache)
        self.assertEqual(
            {"capture_enabled": None, "recall_enabled": None},
            self.store.get_scope_feature_override_sync("private", SESSION_ID),
        )
        self.assertEqual(["v3_probe"], self.store.invalidate_registered_caches(reason="clear_all_memory_data"))
        self.assertEqual(["hit"], cleared)

    def test_scope_feature_override_contract_is_intact(self) -> None:
        signature = inspect.signature(MemoryStore.get_scope_feature_override_sync)
        self.assertEqual(["self", "scope", "window_id"], list(signature.parameters))
        self.assertEqual(
            {"capture_enabled", "recall_enabled"},
            set(self.store.get_scope_feature_override_sync("private", SESSION_ID)),
        )

    # P2-2：缓存向 store 注册失效回调，revision 变化时广播。
    async def test_registered_caches_are_invalidated_on_revision_change(self) -> None:
        cleared: list[str] = []
        self.store.register_invalidation("v3_probe", lambda: cleared.append("hit"))
        self.assertEqual(["v3_probe"], self.store.invalidate_registered_caches(reason="explicit"))
        self.assertEqual(["v3_probe"], self.store.invalidate_registered_caches(reason="explicit"))
        self.assertEqual(["hit", "hit"], cleared)

        await self._insert_native_memory()
        result = self.store.reconcile_caches_sync()
        self.assertTrue(result["changed"])
        self.assertIn("v3_probe", result["caches"])
        self.assertEqual(["hit", "hit", "hit"], cleared)

    # P1-2：额度拒绝必须写状态，且不得 quarantine。
    async def test_budget_refusal_records_release_time_without_quarantine(self) -> None:
        batch_id, _ = await self._batch_with_event()
        self.store._conn.execute(
            "INSERT INTO summary_batch_calls(batch_id, session_id, attempted_at, automatic) VALUES(?,?,?,1)",
            (batch_id, SESSION_ID, utc_now()),
        )
        self.store._conn.commit()

        self.assertFalse(
            await self.store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=1)
        )
        batch = await self.store.get_summary_batch(batch_id)
        self.assertNotEqual("quarantined", batch["state"])
        self.assertTrue(batch["next_retry_at"])
        self.assertEqual("budget", batch["retry_reason"])

        # 额度窗口清空后，退避不得再拦调度。
        self.store._conn.execute(
            "UPDATE summary_batch_calls SET attempted_at='2000-01-01T00:00:00+00:00'"
        )
        self.store._conn.commit()
        due = await self.store.next_summary_batch(SESSION_ID)
        self.assertIsNotNone(due)
        self.assertEqual(batch_id, due["id"])

    async def test_exhausted_call_count_is_final_and_quarantines(self) -> None:
        batch_id, _ = await self._batch_with_event()
        self.assertFalse(
            await self.store.reserve_summary_call(batch_id, max_calls=0, hourly_limit=6)
        )
        batch = await self.store.get_summary_batch(batch_id)
        self.assertEqual("quarantined", batch["state"])

    # P1-2：NULL 表示立即可执行，未来时刻表示不可调度。
    async def test_null_retry_at_is_due_now(self) -> None:
        ready_batch, _ = await self._batch_with_event("准备好的一批")
        later_batch, _ = await self._batch_with_event("需要等待的一批")
        self.store._conn.execute(
            "UPDATE summary_batches SET next_retry_at=? WHERE id=?",
            (
                (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds"),
                later_batch,
            ),
        )
        self.store._conn.commit()

        due = await self.store.next_summary_batch(SESSION_ID)
        self.assertIsNotNone(due)
        self.assertEqual(ready_batch, due["id"])

        self.store._conn.execute(
            "UPDATE summary_batches SET state='completed' WHERE id=?", (ready_batch,)
        )
        self.store._conn.commit()
        self.assertIsNone(await self.store.next_summary_batch(SESSION_ID))

    # P0-1：人工复核可以释放被冻结的事件。
    async def test_quarantined_events_are_frozen_until_released(self) -> None:
        batch_id, event_id = await self._batch_with_event()
        self.store._conn.execute(
            "UPDATE summary_batches SET state='quarantined',automatic_calls=3,repair_used=1 "
            "WHERE id=?", (batch_id,)
        )
        self.store._conn.commit()

        window = await self.store.unsummarized_timeline_window(
            session_id=SESSION_ID, exclude_assigned=True
        )
        self.assertEqual([], [row["id"] for row in window["rows"]])
        progress = await self.store.summary_progress()
        self.assertEqual(1, progress["frozen_events"])

        result = await self.store.release_summary_batch(batch_id, mode="retry")
        self.assertTrue(result["ok"])
        self.assertEqual(1, result["released_events"])
        window = await self.store.unsummarized_timeline_window(
            session_id=SESSION_ID, exclude_assigned=True
        )
        self.assertEqual([event_id], [row["id"] for row in window["rows"]])
        released = await self.store.get_summary_batch(batch_id)
        self.assertEqual(0, released["automatic_calls"])
        self.assertEqual(0, released["repair_used"])
        self.assertEqual(0, (await self.store.summary_progress())["pending_batches"])

        rows = list((await self.store.get_timeline_by_ids([event_id])).values())
        recreated = await self.store.create_summary_batch(SESSION_ID, "private", rows)
        self.assertEqual(batch_id, recreated)
        self.assertTrue(
            await self.store.reserve_summary_call(
                recreated, max_calls=3, hourly_limit=6,
            )
        )

    async def test_release_discard_marks_events_summarized(self) -> None:
        batch_id, event_id = await self._batch_with_event()
        self.store._conn.execute(
            "UPDATE summary_batches SET state='quarantined' WHERE id=?", (batch_id,)
        )
        self.store._conn.commit()
        result = await self.store.release_summary_batch(batch_id, mode="discard")
        self.assertEqual(1, result["released_events"])
        self.assertEqual("completed", result["state"])
        record = (await self.store.get_timeline_by_ids([event_id]))[event_id]
        self.assertTrue(record["summarized_at"])
        window = await self.store.unsummarized_timeline_window(
            session_id=SESSION_ID, exclude_assigned=True
        )
        self.assertEqual([], [row["id"] for row in window["rows"]])

    async def test_release_rejects_unknown_mode_and_batch(self) -> None:
        batch_id, _ = await self._batch_with_event()
        active = await self.store.release_summary_batch(batch_id, mode="retry")
        self.assertFalse(active["ok"])
        self.assertEqual("batch_not_quarantined", active["error"])
        self.assertFalse(
            (await self.store.release_summary_batch("sb_missing", mode="retry"))["ok"]
        )
        self.assertFalse(
            (await self.store.release_summary_batch("sb_missing", mode="explode"))["ok"]
        )

    # 文档 6.8-5：重复归属不得回滚整批。
    async def test_duplicate_event_assignment_is_ignored(self) -> None:
        event_id = await self._timeline()
        rows = list((await self.store.get_timeline_by_ids([event_id])).values())
        batch_id = await self.store.create_summary_batch(SESSION_ID, "private", rows)
        self.assertTrue(batch_id)
        self.store._conn.execute(
            "UPDATE timeline SET summarized_at='' WHERE id=?", (event_id,)
        )
        self.store._conn.commit()
        again = await self.store.create_summary_batch(SESSION_ID, "private", rows)
        self.assertEqual(batch_id, again)
        owned = self.store._conn.execute(
            "SELECT COUNT(*) FROM summary_batch_events WHERE event_id=?", (event_id,)
        ).fetchone()
        self.assertEqual(1, int(owned[0] or 0))

    # P2-1：导航 buckets 默认走召回视图。
    async def test_buckets_exclude_archive_rows_unless_requested(self) -> None:
        await self._insert_native_memory()
        await self._insert_archive_memory()

        default_targets = {item["target_id"] for item in await self.store.list_memory_buckets()}
        self.assertIn("u1", default_targets)
        self.assertNotIn("bot_personal_archive", default_targets)

        with_archive = {
            item["target_id"]: item
            for item in await self.store.list_memory_buckets(include_archive=True)
        }
        self.assertIn("bot_personal_archive", with_archive)
        self.assertEqual(1, with_archive["u1"]["memory_count"])

    async def test_recallable_view_matches_the_recall_predicate(self) -> None:
        await self._insert_native_memory()
        await self._insert_archive_memory()
        rows = self.store._conn.execute(
            "SELECT id FROM recallable_memories ORDER BY id"
        ).fetchall()
        self.assertEqual(["native-private"], [row["id"] for row in rows])
