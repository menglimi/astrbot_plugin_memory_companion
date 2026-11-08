# -*- coding: utf-8 -*-
"""A10：只读命令降权声明 + delete 命令二次确认。"""
from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.commands import (
    COMMAND_PERMISSION_ADMIN,
    COMMAND_PERMISSION_MEMBER,
    READ_ONLY_COMMANDS,
    MemoryCompanionCommandHandler,
    command_permission,
    read_only_commands,
)


def make_handler(delete_ok: bool = True):
    store = SimpleNamespace(delete_memory=AsyncMock(return_value=delete_ok))
    handler = MemoryCompanionCommandHandler(SimpleNamespace(store=store), "2.6.0")
    return handler, store


class CommandPermissionTests(unittest.TestCase):
    def test_read_only_commands_are_member_level(self) -> None:
        for name in ("status", "search", "explain", "recent", "timeline", "relations", "logs", "diagnostics", "help"):
            with self.subTest(command=name):
                self.assertEqual(COMMAND_PERMISSION_MEMBER, command_permission(name))

    def test_mutating_commands_stay_admin_level(self) -> None:
        for name in ("delete", "clear_scope", "add", "visibility", "promote", "archive", "summarize", "maintenance", "audit", "import_livingmemory", "data", "preset"):
            with self.subTest(command=name):
                self.assertEqual(COMMAND_PERMISSION_ADMIN, command_permission(name))

    def test_unknown_commands_fail_closed(self) -> None:
        self.assertEqual(COMMAND_PERMISSION_ADMIN, command_permission("brand-new-command"))
        self.assertEqual(COMMAND_PERMISSION_ADMIN, command_permission(""))

    def test_command_names_are_normalized(self) -> None:
        self.assertEqual(COMMAND_PERMISSION_MEMBER, command_permission("  STATUS  "))

    def test_read_only_set_is_immutable_and_has_no_write_commands(self) -> None:
        self.assertIsInstance(READ_ONLY_COMMANDS, frozenset)
        self.assertIs(read_only_commands(), READ_ONLY_COMMANDS)
        for name in ("delete", "clear_scope", "add", "visibility", "import_livingmemory"):
            self.assertNotIn(name, READ_ONLY_COMMANDS)


class DeleteConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_delete_only_arms_a_confirmation(self) -> None:
        handler, store = make_handler()
        first = await handler.delete("m-1")
        self.assertIn("m-1", first)
        self.assertIn(str(handler.DELETE_CONFIRM_TTL_SECONDS), first)
        store.delete_memory.assert_not_called()

    async def test_second_delete_within_ttl_really_deletes(self) -> None:
        handler, store = make_handler()
        await handler.delete("m-1")
        second = await handler.delete("m-1")
        self.assertEqual("已删除。", second)
        store.delete_memory.assert_awaited_once_with("m-1")

    async def test_explicit_confirm_word_deletes_immediately(self) -> None:
        handler, store = make_handler()
        self.assertEqual("已删除。", await handler.delete("m-1", confirm="确认"))
        store.delete_memory.assert_awaited_once_with("m-1")

    async def test_expired_confirmation_does_not_delete(self) -> None:
        handler, store = make_handler()
        await handler.delete("m-1")
        handler._pending_deletes["m-1"] = time.monotonic() - 1
        result = await handler.delete("m-1")
        self.assertIn("m-1", result)
        store.delete_memory.assert_not_called()

    async def test_pending_confirmation_is_bound_to_one_memory(self) -> None:
        handler, store = make_handler()
        await handler.delete("m-1")
        await handler.delete("m-2")
        store.delete_memory.assert_not_called()
        await handler.delete("m-1")
        store.delete_memory.assert_awaited_once_with("m-1")

    async def test_missing_id_still_returns_usage(self) -> None:
        handler, store = make_handler()
        self.assertIn("用法", await handler.delete(""))
        store.delete_memory.assert_not_called()

    async def test_missing_memory_reports_not_found(self) -> None:
        handler, store = make_handler(delete_ok=False)
        self.assertEqual("没有找到这条记忆。", await handler.delete("m-9", confirm="确认"))
        store.delete_memory.assert_awaited_once_with("m-9")


if __name__ == "__main__":
    unittest.main()
