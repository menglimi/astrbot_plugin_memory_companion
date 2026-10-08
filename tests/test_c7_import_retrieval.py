from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.chat_import import HistoricalChatImporter
from astrbot_plugin_memory_companion.core.models import MemoryRecord
from astrbot_plugin_memory_companion.core.operations import PORTABLE_EXPORT_PAGE_SIZE, PortableMemoryArchive
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore


class _Config:
    def int(self, _key: str, default: int) -> int:
        return default


class _ResumeStore:
    def __init__(self) -> None:
        self.batch = {"id": "batch-1", "state": "running", "checkpoint_segment": 7}
        self.segments = [{"id": "seg-1", "segment_index": 1, "status": "processing", "attempts": 2}]
        self.updates: list[tuple[str, dict]] = []

    async def get_chat_import_batch(self, _batch_id: str):
        return dict(self.batch)

    async def chat_import_segments(self, _batch_id: str, *, statuses=None):
        if statuses is None:
            return list(self.segments)
        return [item for item in self.segments if item["status"] in statuses]

    async def update_chat_import_segment(self, segment_id: str, **changes):
        self.updates.append((segment_id, changes))
        for item in self.segments:
            if item["id"] == segment_id:
                item.update(changes)
        return dict(self.segments[0])

    async def update_chat_import_batch(self, _batch_id: str, **changes):
        self.batch.update(changes)
        return dict(self.batch)


class C7ImportRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_corrupt_manifest_has_stable_redacted_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            importer = HistoricalChatImporter(SimpleNamespace(data_dir=Path(temp), store=object()))
            upload_id = "chatup_" + "a" * 24
            upload_dir = importer._upload_dir(upload_id)
            upload_dir.mkdir(parents=True)
            (upload_dir / "manifest.json").write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "历史导入暂存数据损坏") as raised:
                importer.preview_upload(upload_id)
            self.assertNotIn(str(upload_dir), str(raised.exception))

    def test_corrupt_parsed_jsonl_does_not_become_empty_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            importer = HistoricalChatImporter(SimpleNamespace(data_dir=Path(temp), store=object()))
            upload_id = "chatup_" + "b" * 24
            upload_dir = importer._upload_dir(upload_id)
            upload_dir.mkdir(parents=True)
            (upload_dir / "manifest.json").write_text(
                json.dumps({"upload_id": upload_id}), encoding="utf-8"
            )
            (upload_dir / "parsed.jsonl").write_text('{"message_id":"ok"}\n{broken\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "历史导入暂存数据损坏"):
                importer._load_upload_messages(upload_id)

    async def test_processing_segment_is_retried_only_without_active_worker(self) -> None:
        store = _ResumeStore()
        service = SimpleNamespace(data_dir=Path(tempfile.gettempdir()), store=store, config=_Config())
        importer = HistoricalChatImporter(service)
        importer._start_worker = lambda _batch_id: None
        result = await importer.resume_batch("batch-1")
        self.assertEqual("retry", store.segments[0]["status"])
        self.assertEqual("running", result["batch"]["state"])
        self.assertEqual(0, store.segments[0]["attempts"])


class C7RetrievalBoundaryTests(unittest.TestCase):
    def test_materialize_limit_is_explicit_and_bounded(self) -> None:
        self.assertGreater(RetrievalEngine.DEFAULT_MATERIALIZE_LIMIT, 0)
        self.assertLessEqual(RetrievalEngine.DEFAULT_MATERIALIZE_LIMIT, 2000)

    def test_panel_polling_has_attempt_and_time_bounds(self) -> None:
        """历史导入任务状态轮询必须有上限。

        2.0.0 重写移除了历史导入页的自动轮询（`historicalChatPollAttempts`、
        `elapsed > 10 * 60 * 1000` 与「历史导入轮询已达到上限」提示随之消失），
        状态改为进入视图时读取一次、之后由「刷新状态」按钮按需触发。因此
        「轮询必须有次数与时间上限」的等价契约收紧为「面板不得存在定时轮询器」：
        轮询器不存在时次数与时间上限自动满足，一旦有人加回 setInterval 轮询即失败。
        """
        panel = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("setInterval", panel)
        self.assertIn(
            'apiGet("/conversation-import/status?batch_id=" + encodeURIComponent(importState.batchId)',
            panel,
        )
        self.assertIn('const result = await apiTry(() => apiGet("/conversation-import/status"), null);', panel)

    def test_panel_fetches_import_status_on_navigation_and_manual_refresh(self) -> None:
        panel = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        self.assertIn('apiGet("/conversation-import/status?batch_id="', panel)
        self.assertIn('apiGet("/conversation-import/status")', panel)
        self.assertIn('const recentRefresh = $("#recentRefreshBtn", node);', panel)
        self.assertIn('recentRefresh.addEventListener("click"', panel)


class C7PerformanceBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_embedding_candidate_cache_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            store.initialize()
            try:
                for index in range(store.EMBEDDING_CANDIDATE_CACHE_MAX + 1):
                    await store.list_embedding_candidate_rows(
                        provider_id=f"provider-{index}",
                        limit=1,
                    )
                self.assertLessEqual(
                    len(store._embedding_candidate_cache),
                    store.EMBEDDING_CANDIDATE_CACHE_MAX,
                )
            finally:
                store.close()

    async def test_portable_export_pages_large_memory_sets_without_materializing_all_rows(self) -> None:
        records = [
            MemoryRecord(
                id=f"memory-{index}",
                memory_type="user_fact",
                scope="private",
                visibility="private_pair",
                content=f"content-{index}",
            )
            for index in range(PORTABLE_EXPORT_PAGE_SIZE + 1)
        ]

        class PagedStore:
            def __init__(self) -> None:
                self.memory_calls: list[tuple[int, int]] = []

            async def stats(self):
                return {
                    "total_memories": len(records),
                    "identities": 0,
                    "relationships": 0,
                    "timeline_events": 0,
                }

            async def list_memories(self, *, limit, offset=0):
                self.memory_calls.append((limit, offset))
                return records[offset : offset + limit]

            async def list_identities(self, *, limit, offset=0):
                return []

            async def list_relationships(self, *, limit, offset=0):
                return []

            async def recent_timeline(self, *, limit, offset=0):
                return []

            async def list_acl_rules(self):
                return []

            async def list_acl_policies(self):
                return []

        with tempfile.TemporaryDirectory() as temp:
            store = PagedStore()
            result = await PortableMemoryArchive(store, Path(temp)).export()
            self.assertEqual(
                [
                    (PORTABLE_EXPORT_PAGE_SIZE, 0),
                    (PORTABLE_EXPORT_PAGE_SIZE, PORTABLE_EXPORT_PAGE_SIZE),
                ],
                store.memory_calls,
            )
            self.assertEqual(len(records), result["counts"]["memory"])
            self.assertEqual(
                len(records) + 1,
                len(Path(result["path"]).read_text(encoding="utf-8").splitlines()),
            )


if __name__ == "__main__":
    unittest.main()
