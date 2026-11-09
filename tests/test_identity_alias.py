from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

import astrbot_plugin_memory_companion.core.identity as identity_module
from astrbot_plugin_memory_companion.core.identity import (
    IdentityResolver,
    canonical_user_id,
    normalize_session_context_fields,
)
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy

LARK_ID = "ou_cec66"
MAIN_ID = "302578963"


class IdentityMergeSwitchTests(unittest.TestCase):
    """身份归一默认关闭；配置打开才生效。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.alias_path = os.path.join(self.tmp.name, "identity_alias.json")
        with open(self.alias_path, "w", encoding="utf-8") as fh:
            json.dump({LARK_ID: MAIN_ID}, fh)
        self.config_path = os.path.join(self.tmp.name, "config.json")
        self._orig_alias = identity_module._identity_alias_path
        self._orig_config = identity_module._identity_config_path
        identity_module._identity_alias_path = lambda: self.alias_path
        identity_module._identity_config_path = lambda: self.config_path
        self._reset_cache()

    def tearDown(self) -> None:
        identity_module._identity_alias_path = self._orig_alias
        identity_module._identity_config_path = self._orig_config
        self._reset_cache()
        self.tmp.cleanup()

    @staticmethod
    def _reset_cache() -> None:
        identity_module._ALIAS_CACHE.update({"mtime": None, "map": {}})
        identity_module._CONFIG_CACHE.update({"mtime": None, "enabled": False})

    def _write_config(self, enabled: bool) -> None:
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump({"identity": {"merge_platform_accounts": enabled}}, fh)
        self._reset_cache()

    def test_disabled_without_config(self) -> None:
        self.assertEqual(canonical_user_id(LARK_ID), LARK_ID)

    def test_disabled_when_false(self) -> None:
        self._write_config(False)
        self.assertEqual(canonical_user_id(LARK_ID), LARK_ID)

    def test_enabled_when_true(self) -> None:
        self._write_config(True)
        self.assertEqual(canonical_user_id(LARK_ID), MAIN_ID)

    def test_unknown_and_empty_are_unchanged(self) -> None:
        self._write_config(True)
        self.assertEqual(canonical_user_id("999"), "999")
        self.assertEqual(canonical_user_id(""), "")


class IdentityAliasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.alias_path = os.path.join(self.tmp.name, "identity_alias.json")
        with open(self.alias_path, "w", encoding="utf-8") as fh:
            json.dump({LARK_ID: MAIN_ID}, fh)
        self.config_path = os.path.join(self.tmp.name, "config.json")
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump({"identity": {"merge_platform_accounts": True}}, fh)
        self._orig_alias = identity_module._identity_alias_path
        self._orig_config = identity_module._identity_config_path
        identity_module._identity_alias_path = lambda: self.alias_path
        identity_module._identity_config_path = lambda: self.config_path
        identity_module._ALIAS_CACHE.update({"mtime": None, "map": {}})
        identity_module._CONFIG_CACHE.update({"mtime": None, "enabled": False})

    def tearDown(self) -> None:
        identity_module._identity_alias_path = self._orig_alias
        identity_module._identity_config_path = self._orig_config
        identity_module._ALIAS_CACHE.update({"mtime": None, "map": {}})
        identity_module._CONFIG_CACHE.update({"mtime": None, "enabled": False})
        self.tmp.cleanup()

    def test_normalize_private_session_uses_canonical_id(self) -> None:
        # 页面/桥接/工具都走这个函数；不归一的话跨平台会看不到对方的记忆
        ctx = normalize_session_context_fields(
            session_id="lark:FriendMessage:" + LARK_ID, scope="private"
        )
        self.assertEqual(ctx["user_id"], MAIN_ID)
        self.assertEqual(ctx["session_id"], "lark:FriendMessage:" + LARK_ID)

    def test_normalize_group_untouched(self) -> None:
        ctx = normalize_session_context_fields(
            session_id="qq:GroupMessage:12345", scope="group", user_id=LARK_ID,
        )
        self.assertEqual(ctx["group_id"], "12345")
        self.assertEqual(ctx["user_id"], LARK_ID)

    def test_group_event_keeps_platform_user_id(self) -> None:
        event = SimpleNamespace(
            unified_msg_origin="lark:GroupMessage:12345",
            get_platform_name=lambda: "lark",
            get_group_id=lambda: "12345",
            get_sender_id=lambda: LARK_ID,
            get_message_str=lambda: "hello",
        )
        ctx = asyncio.run(IdentityResolver().resolve_event_context(event))
        self.assertEqual(ctx.user_id, LARK_ID)


class CrossPlatformVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = VisibilityPolicy()
        self.tmp = tempfile.TemporaryDirectory()
        self.alias_path = os.path.join(self.tmp.name, "identity_alias.json")
        self.config_path = os.path.join(self.tmp.name, "config.json")
        with open(self.alias_path, "w", encoding="utf-8") as fh:
            json.dump({LARK_ID: MAIN_ID}, fh)
        self._orig_alias = identity_module._identity_alias_path
        self._orig_config = identity_module._identity_config_path
        identity_module._identity_alias_path = lambda: self.alias_path
        identity_module._identity_config_path = lambda: self.config_path
        self._set_enabled(True)

    def tearDown(self) -> None:
        identity_module._identity_alias_path = self._orig_alias
        identity_module._identity_config_path = self._orig_config
        identity_module._ALIAS_CACHE.update({"mtime": None, "map": {}})
        identity_module._CONFIG_CACHE.update({"mtime": None, "enabled": False})
        self.tmp.cleanup()

    def _set_enabled(self, enabled: bool) -> None:
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump({"identity": {"merge_platform_accounts": enabled}}, fh)
        identity_module._ALIAS_CACHE.update({"mtime": None, "map": {}})
        identity_module._CONFIG_CACHE.update({"mtime": None, "enabled": False})

    @staticmethod
    def _memory(subject: str, obj: str, platform: str, session_id: str) -> MemoryRecord:
        return MemoryRecord(
            scope="private",
            session_id=session_id,
            platform=platform,
            visibility="private_pair",
            lifecycle="stable_memory",
            subject=EntityRef(kind="user", id=subject),
            object=EntityRef(kind="user", id=obj),
        )

    def test_qq_context_can_read_lark_memory(self) -> None:
        memory = self._memory(MAIN_ID, "470488586", "lark", "lark:FriendMessage:" + LARK_ID)
        ctx = SessionContext(
            session_id="qq:FriendMessage:" + MAIN_ID, scope="private", platform="qq", user_id=MAIN_ID
        )
        visible, reason = self.policy.is_visible(memory, ctx)
        self.assertTrue(visible, reason)

    def test_lark_context_can_read_qq_memory(self) -> None:
        memory = self._memory(MAIN_ID, "470488586", "qq", "qq:FriendMessage:" + MAIN_ID)
        ctx = SessionContext(
            session_id="lark:FriendMessage:" + LARK_ID, scope="private", platform="lark", user_id=MAIN_ID
        )
        visible, reason = self.policy.is_visible(memory, ctx)
        self.assertTrue(visible, reason)

    def test_stranger_still_blocked(self) -> None:
        memory = self._memory(MAIN_ID, "470488586", "lark", "lark:FriendMessage:" + LARK_ID)
        ctx = SessionContext(
            session_id="qq:FriendMessage:999", scope="private", platform="qq", user_id="999"
        )
        visible, _ = self.policy.is_visible(memory, ctx)
        self.assertFalse(visible)

    def test_cross_platform_match_requires_explicit_alias(self) -> None:
        memory = self._memory(MAIN_ID, "470488586", "lark", "lark:FriendMessage:" + MAIN_ID)
        ctx = SessionContext(
            session_id="qq:FriendMessage:" + MAIN_ID, scope="private", platform="qq", user_id=MAIN_ID,
        )
        visible, reason = self.policy.is_visible(memory, ctx)
        self.assertFalse(visible)
        self.assertEqual(reason, "other_platform")

        self._set_enabled(False)
        memory.session_id = "lark:FriendMessage:" + LARK_ID
        visible, reason = self.policy.is_visible(memory, ctx)
        self.assertFalse(visible)
        self.assertEqual(reason, "other_platform")

    def test_group_context_cannot_read_private_pair_for_same_user(self) -> None:
        memory = self._memory(MAIN_ID, "470488586", "lark", "lark:FriendMessage:" + LARK_ID)
        ctx = SessionContext(
            session_id="qq:GroupMessage:12345", scope="group", platform="qq",
            user_id=MAIN_ID, group_id="12345",
        )
        visible, reason = self.policy.is_visible(memory, ctx)
        self.assertFalse(visible)
        self.assertEqual(reason, "other_platform")


if __name__ == "__main__":
    unittest.main()
