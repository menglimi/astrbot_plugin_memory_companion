from __future__ import annotations

import re
import unittest
from pathlib import Path

from core.commands import COMMAND_PERMISSION_ADMIN, COMMAND_PERMISSION_MEMBER, command_permission

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (REPO_ROOT / "main.py").read_text(encoding="utf-8")


def _decorated_commands() -> dict[str, str]:
    """main.py 里每个 @mcomp.command("x") 及其上一行的 permission_type。"""
    found: dict[str, str] = {}
    lines = MAIN_SOURCE.split("\n")
    for index, line in enumerate(lines):
        match = re.search(r'@mcomp\.command\("([a-z_]+)"', line)
        if not match:
            continue
        cursor = index - 1
        while cursor >= 0 and not lines[cursor].strip():
            cursor -= 1
        decorator = lines[cursor] if cursor >= 0 else ""
        if "PermissionType.ADMIN" in decorator:
            found[match.group(1)] = COMMAND_PERMISSION_ADMIN
        elif "PermissionType.MEMBER" in decorator:
            found[match.group(1)] = COMMAND_PERMISSION_MEMBER
        else:
            found[match.group(1)] = "missing"
    return found


class CommandPermissionWiringTests(unittest.TestCase):
    """A10：main.py 的命令装饰器必须与 core/commands.py 的权限表一致。"""

    def test_every_decorated_command_matches_the_permission_table(self) -> None:
        decorated = _decorated_commands()
        self.assertGreaterEqual(len(decorated), 20, decorated)
        mismatched = {
            name: (level, command_permission(name))
            for name, level in decorated.items()
            if level != command_permission(name)
        }
        self.assertEqual({}, mismatched)

    def test_read_only_commands_are_reachable_for_ordinary_members(self) -> None:
        decorated = _decorated_commands()
        for name in ("status", "search", "explain", "recent", "timeline", "relations", "logs", "diagnostics", "help"):
            self.assertEqual(COMMAND_PERMISSION_MEMBER, decorated.get(name), name)

    def test_destructive_commands_stay_admin_only(self) -> None:
        decorated = _decorated_commands()
        for name in ("delete", "clear_scope", "maintenance", "data", "preset", "import_livingmemory"):
            self.assertEqual(COMMAND_PERMISSION_ADMIN, decorated.get(name), name)


class TerminateUnregistersRoutesTests(unittest.TestCase):
    """A6：terminate 必须主动反注册 web 路由（宿主不清）。"""

    def test_terminate_calls_unregister_routes(self) -> None:
        start = MAIN_SOURCE.index("async def terminate")
        body = MAIN_SOURCE[start:]
        self.assertIn("unregister_routes", body)
        self.assertLess(body.index("unregister_routes"), body.index("await self.service.aclose()"))


if __name__ == "__main__":
    unittest.main()
