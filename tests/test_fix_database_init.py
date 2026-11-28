"""H12：数据库初始化只保留一份实现，失败时不留半开连接。

历史上 service.py 里有两份 _initialize_database_sync / initialize_database：前面那份
（失败时直接 close store）是死码，后面那份才是生效版本。死码留着会让人误读行为，
所以这里用 AST 断言每个名字只定义一次。
"""

from __future__ import annotations

import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:  # pragma: no cover - 直接 pytest 单文件时
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


SERVICE_PATH = Path(ROOT) / "core" / "service.py"


def class_level_definitions(name: str) -> list[int]:
    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines.append(node.lineno)
    return sorted(lines)


class DatabaseInitializationDefinitionTests(unittest.TestCase):
    def test_initialize_database_sync_is_defined_once(self) -> None:
        self.assertEqual(1, len(class_level_definitions("_initialize_database_sync")))

    def test_initialize_database_is_defined_once(self) -> None:
        self.assertEqual(1, len(class_level_definitions("initialize_database")))


class DatabaseInitializationFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_closes_the_half_open_connection_and_stays_retryable(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
            defer_database_initialization=True,
        )
        self.addCleanup(service.close)
        store = service.store
        initialize = store.initialize
        fail_once = True

        def fail_once_then_initialize() -> None:
            nonlocal fail_once
            if fail_once:
                fail_once = False
                raise sqlite3.OperationalError("temporary initialization failure")
            initialize()

        store.initialize = fail_once_then_initialize
        with self.assertRaisesRegex(RuntimeError, "temporary initialization failure"):
            await service.initialize_database()

        # 失败后连接被换掉（旧的半开句柄不会留在 store 上），但 store 没有进入 closed 状态。
        self.assertFalse(store._closed)
        self.assertIsNotNone(store._conn)
        self.assertIsNotNone(store._conn.execute("PRAGMA schema_version").fetchone())

        self.assertTrue(await service.initialize_database())
        self.assertIsNotNone(
            store._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
        )
        memory_id = await store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:user",
            scope="private",
            subject_id="user",
            object_id="bot",
            content="重试之后库是好的。",
        )
        self.assertTrue(memory_id)

    async def test_initialize_database_returns_false_once_the_service_is_closed(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
            defer_database_initialization=True,
        )
        service.close()
        self.assertFalse(await service.initialize_database())
