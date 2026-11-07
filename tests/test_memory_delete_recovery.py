# -*- coding: utf-8 -*-
"""Deleting a memory must recover, or explain itself — never fail silently.

Production report: pressing "确认删除" in the panel answered
``500 Internal server error`` while everything else kept working.  The store
only retried database-path errors for inserts, so a transient
``unable to open database file`` on the delete path escaped as a raw 500 and
the memory stayed in place.  These tests pin the contract:

* a delete retries once after a genuine reconnect;
* a delete that cannot reconnect keeps the row and raises a diagnosable error
  instead of the opaque SQLite message;
* the reconnect never adopts an empty database in place of the real one;
* the page API and the chat command both tell the user what happened.
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")
    quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = quart_stub

from astrbot_plugin_memory_companion.core.commands import MemoryCompanionCommandHandler
from astrbot_plugin_memory_companion.core.models import MemoryRecord
from astrbot_plugin_memory_companion.core.store import (
    MemoryStore,
    MemoryStoreUnavailableError,
)

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi


class _Response(dict):
    """Minimal stand-in for a quart response used by ``jsonify`` in tests."""

    status_code = 200


def _jsonify(payload=None, **kwargs):
    return _Response(payload or kwargs)


class MemoryDeleteRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    async def _insert(self, store: MemoryStore, content: str) -> str:
        return await store.insert_memory(
            MemoryRecord(content=content, lifecycle="stable_memory", visibility="shareable")
        )

    async def test_delete_memory_recovers_once_from_database_path_error(self) -> None:
        store = self.make_store()
        memory_id = await self._insert(store, "删除也要能重连")
        original = store._delete_memory_sync
        attempts = 0

        def fail_once(value: str) -> bool:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise sqlite3.OperationalError("unable to open database file")
            return original(value)

        store._delete_memory_sync = fail_once
        self.assertTrue(await store.delete_memory(memory_id))

        self.assertEqual(2, attempts)
        self.assertIsNone(await store.get_memory(memory_id))
        stats = await store.stats()
        self.assertEqual(1, stats["wal"]["database_recovery_attempts"])
        self.assertEqual(1, stats["wal"]["database_recovery_successes"])

    async def test_delete_memory_reports_reason_and_keeps_row_when_reopen_fails(self) -> None:
        store = self.make_store()
        memory_id = await self._insert(store, "重连失败时原记忆必须保留")

        def always_unopenable(value: str) -> bool:
            raise sqlite3.OperationalError("unable to open database file")

        store._delete_memory_sync = always_unopenable
        with patch.object(
            store,
            "_open_connection",
            side_effect=sqlite3.OperationalError("unable to open database file"),
        ):
            with self.assertRaises(MemoryStoreUnavailableError) as raised:
                await store.delete_memory(memory_id)

        error = raised.exception
        self.assertEqual("database_open_failed", error.reason)
        self.assertIn("记忆库暂时无法写入", str(error))
        self.assertIn("unable to open database file", str(error))
        self.assertEqual(str(store.db_path), error.diagnostics["db_path"])
        self.assertTrue(error.diagnostics["db_path_exists"])
        self.assertEqual(
            store.DATABASE_RECOVERY_OPEN_ATTEMPTS,
            error.diagnostics["recovery_attempts"],
        )
        self.assertEqual("database_open_failed", store._last_recovery_failure["reason"])
        # The failed delete must not lose the row: the panel can retry later.
        self.assertIsNotNone(await store.get_memory(memory_id))

    async def test_recovery_refuses_to_adopt_an_empty_database(self) -> None:
        store = self.make_store()
        memory_id = await self._insert(store, "不能被空库覆盖")
        store.close()

        # Simulate the real accident: the file was replaced by an empty one
        # (restore, sync client, "clean up the big file" tool).
        store.db_path.write_bytes(b"")
        reopened = MemoryStore(store.db_path)
        self.addCleanup(reopened.close)
        replaced_connection = reopened._conn
        reopened._schema_ready = True

        with self.assertRaises(MemoryStoreUnavailableError) as raised:
            reopened._recover_connection_sync()

        self.assertEqual("database_schema_missing", raised.exception.reason)
        self.assertIs(replaced_connection, reopened._conn)
        self.assertIsNotNone(memory_id)

    async def test_recovery_reports_a_missing_database_instead_of_creating_one(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        missing_path = Path(temp_dir.name) / "missing.db"
        store = MemoryStore(missing_path)
        store.close()
        missing_path.unlink()
        store._closed = False
        try:
            with self.assertRaises(MemoryStoreUnavailableError) as raised:
                store._recover_connection_sync()

            self.assertEqual("database_file_missing", raised.exception.reason)
            self.assertFalse(missing_path.exists())
        finally:
            # The connection is already closed; only the flag kept close() from
            # short-circuiting, so restore it instead of closing twice.
            store._closed = True

    async def test_memory_delete_endpoint_returns_actionable_503(self) -> None:
        error = MemoryStoreUnavailableError(
            "记忆库暂时无法写入（unable to open database file）。"
            "记忆库目录不可写：C:/data/plugin_data/memory；"
            "常见原因是目录权限被改或被同步盘/杀毒软件的文件夹保护接管。",
            reason="database_directory_not_writable",
            diagnostics={
                "db_path": "C:/data/plugin_data/memory/memory_companion.db",
                "directory": "C:/data/plugin_data/memory",
                "directory_writable": False,
            },
        )

        class _Store:
            async def delete_memory(self, memory_id: str) -> bool:
                raise error

        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=_Store())))
        with patch.object(page_api_module, "jsonify", _jsonify):
            with patch.object(api, "_json", AsyncMock(return_value={"id": "mem-404"})):
                response = await api.memory_delete()

        self.assertEqual(503, response.status_code)
        self.assertFalse(response["success"])
        self.assertEqual("database_unavailable", response["code"])
        self.assertEqual("database_directory_not_writable", response["reason"])
        self.assertIn("记忆库目录不可写", response["error"])
        self.assertIn("文件夹保护", response["error"])
        self.assertEqual(
            "C:/data/plugin_data/memory",
            response["detail"]["directory"],
        )

    async def test_memory_delete_endpoint_rejects_missing_id(self) -> None:
        deleted: list[str] = []

        class _Store:
            async def delete_memory(self, memory_id: str) -> bool:
                deleted.append(memory_id)
                return True

        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=_Store())))
        with patch.object(page_api_module, "jsonify", _jsonify):
            with patch.object(api, "_json", AsyncMock(return_value={})):
                response = await api.memory_delete()

        self.assertEqual(400, response.status_code)
        self.assertFalse(response["success"])
        self.assertEqual([], deleted)

    async def test_chat_delete_command_explains_database_failure(self) -> None:
        class _Store:
            async def delete_memory(self, memory_id: str) -> bool:
                raise MemoryStoreUnavailableError(
                    "记忆库暂时无法写入（unable to open database file）"
                )

        handler = MemoryCompanionCommandHandler(SimpleNamespace(store=_Store()), "test")
        message = await handler.delete("mem-1")

        self.assertIn("删除失败", message)
        self.assertIn("仍然保留", message)
        self.assertIn("unable to open database file", message)

    async def test_chat_delete_command_still_reports_a_missing_memory(self) -> None:
        class _Store:
            async def delete_memory(self, memory_id: str) -> bool:
                return False

        handler = MemoryCompanionCommandHandler(SimpleNamespace(store=_Store()), "test")

        self.assertEqual("没有找到这条记忆。", await handler.delete("mem-404"))


if __name__ == "__main__":
    unittest.main()
