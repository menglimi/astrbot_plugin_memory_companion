# -*- coding: utf-8 -*-
"""P5：可移植档案的导入/导出入口必须有路径约束与大小上限。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core import operations
from astrbot_plugin_memory_companion.core.operations import PortableMemoryArchive


def write_archive(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "record_type": "header",
                "format": "astrbot-memory-jsonl",
                "version": 1,
                "plugin": "astrbot_plugin_memory_companion",
                "counts": {"memory": len(records)},
            },
            ensure_ascii=False,
        )
    ]
    for record in records:
        lines.append(json.dumps({"record_type": "memory", "data": record}, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_store() -> SimpleNamespace:
    return SimpleNamespace(
        backup_async=AsyncMock(return_value="backup-before-import.db"),
        add_import_batch=AsyncMock(return_value="batch-1"),
        import_batch_ops=AsyncMock(side_effect=lambda chunk: [{"ok": True} for _ in chunk]),
    )


class ArchivePathGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data_dir = self.root / "plugin_data" / "astrbot_plugin_memory_companion"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = make_store()
        self.archive = PortableMemoryArchive(self.store, self.data_dir)
        self.inside = write_archive(
            self.data_dir / "exports" / "memory-companion-20260101-000000.jsonl",
            [{"content": "一条记忆", "memory_type": "conversation_summary"}],
        )
        self.outside = write_archive(
            self.root / "outside" / "stolen.jsonl",
            [{"content": "外部档案", "memory_type": "conversation_summary"}],
        )

    def test_empty_path_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "required"):
            self.archive._resolve_source_path("")

    def test_parent_traversal_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "two dots"):
            self.archive._resolve_source_path("../outside/stolen.jsonl")
        with self.assertRaisesRegex(ValueError, "two dots"):
            self.archive._resolve_source_path(str(self.inside) + "/../../outside/stolen.jsonl")

    def test_absolute_path_outside_the_data_dir_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the plugin data directory"):
            self.archive._resolve_source_path(str(self.outside))

    def test_path_inside_the_data_dir_is_allowed(self) -> None:
        resolved = self.archive._resolve_source_path(str(self.inside))
        self.assertEqual(self.inside.resolve(), resolved)

    def test_relative_path_inside_the_data_dir_is_allowed(self) -> None:
        resolved = self.archive._resolve_source_path("exports/memory-companion-20260101-000000.jsonl")
        self.assertEqual(self.inside.resolve(), resolved)

    def test_symlink_escape_is_refused(self) -> None:
        link = self.data_dir / "escape.jsonl"
        try:
            link.symlink_to(self.outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is not permitted on this host")
        with self.assertRaisesRegex(ValueError, "outside the plugin data directory"):
            self.archive._resolve_source_path(str(link))

    def test_preview_reads_only_inside_the_data_dir(self) -> None:
        preview = self.archive.preview(str(self.inside))
        self.assertTrue(preview["valid"])
        self.assertEqual(1, preview["total_records"])
        with self.assertRaisesRegex(ValueError, "outside the plugin data directory"):
            self.archive.preview(str(self.outside))

    async def test_import_refuses_outside_paths_before_touching_the_store(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the plugin data directory"):
            await self.archive.import_data(str(self.outside))
        self.store.backup_async.assert_not_called()
        self.store.import_batch_ops.assert_not_called()

    async def test_import_accepts_an_archive_inside_the_data_dir(self) -> None:
        result = await self.archive.import_data(str(self.inside))
        self.assertEqual(str(self.inside.resolve()), result["path"])
        self.assertEqual("batch-1", result["batch_id"])
        self.store.backup_async.assert_awaited_once()

    async def test_callers_can_widen_the_allowed_roots_explicitly(self) -> None:
        archive = PortableMemoryArchive(
            self.store, self.data_dir, allowed_roots=(self.data_dir, self.root / "outside")
        )
        self.assertEqual(self.outside.resolve(), archive._resolve_source_path(str(self.outside)))

    def test_read_stays_a_staticmethod_without_path_constraints(self) -> None:
        # tests/test_operations.py:222 直接调用 PortableMemoryArchive._read(path)。
        header, records = PortableMemoryArchive._read(str(self.outside))
        self.assertEqual("astrbot-memory-jsonl", header["format"])
        self.assertEqual(1, len(records))

    def test_record_count_cap_is_enforced(self) -> None:
        original = operations.MAX_PORTABLE_RECORDS
        operations.MAX_PORTABLE_RECORDS = 1
        try:
            big = write_archive(
                self.data_dir / "exports" / "big.jsonl",
                [
                    {"content": "a", "memory_type": "conversation_summary"},
                    {"content": "b", "memory_type": "conversation_summary"},
                ],
            )
            with self.assertRaisesRegex(ValueError, "more than 1 records"):
                self.archive.preview(str(big))
        finally:
            operations.MAX_PORTABLE_RECORDS = original


if __name__ == "__main__":
    unittest.main()
