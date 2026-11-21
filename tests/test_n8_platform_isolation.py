"""跨平台记忆放行边界回归测试。

旧实现的平台门存在放行过宽的豁免：

* ``RetrievalEngine.filter_visible_candidates`` 里的 ``linked_private_user``
  直接调用 ``is_visible()``，而 ``is_visible`` 对 ``shareable`` 无条件放行，
  于是其他平台的 shareable 记录也能穿过平台门；同处的 ``same_session``
  只比较 ``session_id`` 字符串，而该字符串由宿主适配器原样拷贝。
* ``VisibilityPolicy.is_visible`` 里同样的 ``session_id`` 相等提前返回，
  会跳过平台一致性与身份绑定校验。

这些用例同时守住两侧：跨平台必须被拦，同平台与显式身份绑定必须照旧放行。
"""

from __future__ import annotations

import json
import tempfile
from types import SimpleNamespace
import unittest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import identity as identity_module
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy

PERSON_ID = "person_" + "a" * 24
OTHER_PERSON_ID = "person_" + "b" * 24
LARK_ID = "ou_lark_user_1"
MAIN_ID = "qq_user_1"


def _ctx(**changes) -> SessionContext:
    fields = dict(
        session_id="qq:FriendMessage:u1",
        scope="private",
        platform="qq",
        user_id="u1",
        bot_id="b1",
        message_text="你还记得我喜欢什么吗？",
    )
    fields.update(changes)
    return SessionContext(**fields)


def _record(**changes) -> MemoryRecord:
    fields = dict(
        id="memory-1",
        memory_type="manual_memory",
        subject=EntityRef(kind="user", id="u1"),
        object=EntityRef.bot_self("b1"),
        scope="private",
        session_id="qq:FriendMessage:u1",
        platform="qq",
        visibility="private_pair",
        lifecycle="stable_memory",
        content="用户喜欢无糖拿铁。",
        confidence=0.95,
        importance=0.9,
        metadata={"owner_bot_id": "b1"},
    )
    fields.update(changes)
    return MemoryRecord(**fields).ensure_defaults()


class PlatformGateBlocksForeignPlatformTests(unittest.IsolatedAsyncioTestCase):
    """两个缺陷的直接回归：跨平台记录不得经豁免穿过平台门。"""

    def setUp(self) -> None:
        self.policy = VisibilityPolicy(enable_acl_rules=False)
        self.engine = RetrievalEngine(object(), self.policy)

    async def _visible_ids(self, memory: MemoryRecord, ctx: SessionContext) -> list[str]:
        visible, _blocked = await self.engine.filter_visible_candidates([memory], ctx)
        return [item.memory.id for item in visible]

    async def test_shareable_row_from_another_platform_is_blocked(self) -> None:
        # 缺陷 1 的原始形态：shareable + 同 session_id + 不同 platform。
        memory = _record(platform="other", visibility="shareable")
        visible, blocked = await self.engine.filter_visible_candidates([memory], _ctx())

        self.assertEqual([], [item.memory.id for item in visible])
        self.assertEqual(["other_platform"], [item["reason"] for item in blocked])

    async def test_private_pair_row_from_another_platform_is_blocked(self) -> None:
        # 缺陷 2 的原始形态：private_pair + 同 session_id + 不同 platform。
        # 该行带 bot 归属，所以不是「无归属的历史迁移行」，平台矛盾成立。
        memory = _record(platform="slack")
        self.assertEqual([], await self._visible_ids(memory, _ctx()))

    async def test_visibility_policy_does_not_let_session_string_grant_platform(self) -> None:
        # 策略层自己也不得凭 session_id 字符串跨平台放行。
        memory = _record(platform="slack")
        self.assertEqual((False, "other_platform"), self.policy.is_visible(memory, _ctx()))

    async def test_attributed_row_cannot_reuse_another_bots_window_text(self) -> None:
        # 归属其它 bot 的记录，即便 session_id 与本轮完全相同也要拦。
        memory = _record(
            platform="lark",
            object=EntityRef.bot_self("b2"),
            metadata={"owner_bot_id": "b2"},
        )
        self.assertEqual([], await self._visible_ids(memory, _ctx()))

    def test_group_public_from_another_platform_is_blocked_even_when_allowed_in_private(self) -> None:
        policy = VisibilityPolicy(allow_group_public_in_private=True, enable_acl_rules=False)
        onebot_qq_group_public_mem = _record(
            id="qq-group-public-mem",
            scope="group",
            group_id="group-99",
            session_id="onebot_qq:GroupMessage:group-99",
            platform="onebot_qq",
            visibility="group_public",
            owner_bot_id="b1",
        )
        webchat_private_ctx = _ctx(
            session_id="webchat:FriendMessage:web-u1",
            scope="private",
            platform="webchat",
            user_id="web-u1",
        )
        self.assertEqual(
            (False, "other_platform"),
            policy.is_visible(onebot_qq_group_public_mem, webchat_private_ctx),
        )

    def test_shareable_from_another_platform_is_blocked_by_policy(self) -> None:
        other_platform_shareable_mem = _record(
            platform="other",
            visibility="shareable",
            session_id="other:FriendMessage:u1",
        )
        self.assertEqual(
            (False, "other_platform"),
            self.policy.is_visible(other_platform_shareable_mem, _ctx()),
        )


class PlatformGateStillAllowsGenuineCasesTests(unittest.IsolatedAsyncioTestCase):
    """防止过度收紧：真实同平台 / 显式绑定的场景必须照旧放行。"""

    def setUp(self) -> None:
        self.policy = VisibilityPolicy(enable_acl_rules=False)
        self.engine = RetrievalEngine(object(), self.policy)

    async def _visible_ids(self, memory: MemoryRecord, ctx: SessionContext) -> list[str]:
        visible, _blocked = await self.engine.filter_visible_candidates([memory], ctx)
        return [item.memory.id for item in visible]

    async def test_same_platform_same_session_is_visible(self) -> None:
        self.assertEqual(["memory-1"], await self._visible_ids(_record(), _ctx()))

    async def test_same_platform_same_session_preserves_session_reason(self) -> None:
        self.assertEqual(
            (True, "same_private_session"),
            self.policy.is_visible(_record(), _ctx(user_id="")),
        )

    async def test_same_platform_other_session_of_same_user_is_visible(self) -> None:
        # 既有语义：同一个人的记忆跟着人走，跨窗口仍可见。
        memory = _record(session_id="qq:FriendMessage:u1-other-window")
        self.assertEqual(["memory-1"], await self._visible_ids(memory, _ctx()))

    async def test_qq_adapter_aliases_are_the_same_platform(self) -> None:
        # 同一 QQ 传输的不同适配器名（含 qq 前缀被改名的 onebot_qq）。
        for platform in ("qq", "aiocqhttp", "onebot_qq", "napcat"):
            with self.subTest(platform=platform):
                self.assertEqual(
                    ["memory-1"], await self._visible_ids(_record(platform=platform), _ctx())
                )

    async def test_legacy_placeholder_platform_still_matches_its_window(self) -> None:
        for platform in ("default", ""):
            with self.subTest(platform=platform):
                memory = _record(platform=platform)
                self.assertEqual(["memory-1"], await self._visible_ids(memory, _ctx()))

    async def test_explicit_person_link_crosses_platform(self) -> None:
        # 显式身份绑定（explicit_linked）是唯一允许跨平台的证据。
        memory = _record(
            platform="lark",
            session_id="lark:FriendMessage:u1",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
        )
        context = _ctx(
            platform="qq",
            session_id="qq:FriendMessage:u1",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
        )
        self.assertEqual((True, "explicit_linked_person"), self.policy.is_visible(memory, context))
        self.assertEqual(["memory-1"], await self._visible_ids(memory, context))

    async def test_unattributed_legacy_import_keeps_its_window(self) -> None:
        # 历史导入行没有 bot 归属，platform 列是旧值；同一窗口仍然可见。
        memory = _record(
            platform="qq",
            session_id="lark:FriendMessage:u1",
            subject=EntityRef(kind="user", id="u1"),
            object=EntityRef(kind="user", id="u1"),
            metadata={},
        )
        context = _ctx(session_id="lark:FriendMessage:u1", platform="lark")
        self.assertEqual(["memory-1"], await self._visible_ids(memory, context))

    async def test_different_person_is_still_refused_on_same_platform(self) -> None:
        memory = _record(
            subject_person_id=OTHER_PERSON_ID,
            identity_assurance="explicit_linked",
        )
        context = _ctx(subject_person_id=PERSON_ID, identity_assurance="explicit_linked")
        self.assertEqual((False, "other_person"), self.policy.is_visible(memory, context))


class PlatformIdentityAllowsContractTests(unittest.TestCase):
    """单一判定点：两层平台门共用 ``platform_identity_allows``。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.alias_path = f"{self.tmp.name}/identity_alias.json"
        self.config_path = f"{self.tmp.name}/config.json"
        with open(self.alias_path, "w", encoding="utf-8") as fh:
            json.dump({LARK_ID: MAIN_ID}, fh)
        self._write_config(False)
        originals = (identity_module._identity_alias_path, identity_module._identity_config_path)
        identity_module._identity_alias_path = lambda: self.alias_path
        identity_module._identity_config_path = lambda: self.config_path

        def restore() -> None:
            identity_module._identity_alias_path, identity_module._identity_config_path = originals
            identity_module._ALIAS_CACHE.update({"mtime": None, "map": {}})
            identity_module._CONFIG_CACHE.update({"mtime": None, "enabled": False})

        self.addCleanup(restore)
        self.policy = VisibilityPolicy()

    def _write_config(self, enabled: bool) -> None:
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump({"identity": {"merge_platform_accounts": enabled}}, fh)
        identity_module._ALIAS_CACHE.update({"mtime": None, "map": {}})
        identity_module._CONFIG_CACHE.update({"mtime": None, "enabled": False})

    def test_same_platform_is_always_allowed(self) -> None:
        self.assertTrue(self.policy.platform_identity_allows(_record(), _ctx()))

    def test_placeholder_platform_is_always_allowed(self) -> None:
        self.assertTrue(self.policy.platform_identity_allows(_record(platform="default"), _ctx()))

    def test_account_merge_needs_two_distinct_targets(self) -> None:
        # 两个完全相同的 id 只证明「窗口字符串相同」，不是身份合并。
        same_target = _record(
            platform="lark",
            session_id="qq:FriendMessage:u1",
            metadata={"owner_bot_id": "b1"},
        )
        self.assertFalse(self.policy.platform_identity_allows(same_target, _ctx()))

    def test_account_merge_allows_distinct_aliased_targets(self) -> None:
        self._write_config(True)
        memory = _record(
            platform="lark",
            session_id=f"lark:FriendMessage:{LARK_ID}",
            subject=EntityRef(kind="user", id=LARK_ID),
            metadata={"owner_bot_id": "b1"},
        )
        context = _ctx(session_id=f"qq:FriendMessage:{MAIN_ID}", user_id=MAIN_ID)
        self.assertTrue(self.policy.platform_identity_allows(memory, context))

    def test_account_merge_is_ignored_when_disabled(self) -> None:
        self._write_config(False)
        memory = _record(
            platform="lark",
            session_id=f"lark:FriendMessage:{LARK_ID}",
            subject=EntityRef(kind="user", id=LARK_ID),
            metadata={"owner_bot_id": "b1"},
        )
        context = _ctx(session_id=f"qq:FriendMessage:{MAIN_ID}", user_id=MAIN_ID)
        self.assertFalse(self.policy.platform_identity_allows(memory, context))


class SharedPlatformGateTests(unittest.IsolatedAsyncioTestCase):
    """两侧共用同一个平台门：多种外来平台必须一律被拦。"""

    async def test_foreign_platforms_are_blocked_through_the_shared_gate(self) -> None:
        from astrbot_plugin_memory_companion.core.service import MemoryCompanionService

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        service = MemoryCompanionService(
            context=None,
            plugin_root=ROOT,
            data_dir=directory.name,
            config={
                "retrieval": {"mode": "basic", "embedding_enabled": False},
                "visibility": {"enable_acl_rules": False},
                "memory_injection": {"enable_injection_logs": False},
            },
        )
        self.addCleanup(service.close)
        # 走 service 的引擎，确认生产装配出来的策略也带同样行为。
        engine = service._retrieval_validation_engine()
        context = _ctx()
        blocked_ids = set()
        for platform in ("other", "slack", "lark"):
            memory = _record(id=f"foreign-{platform}", platform=platform, visibility="shareable")
            visible, blocked = await engine.filter_visible_candidates([memory], context)
            self.assertEqual([], [item.memory.id for item in visible], platform)
            blocked_ids.update(item["id"] for item in blocked)

        self.assertEqual({"foreign-other", "foreign-slack", "foreign-lark"}, blocked_ids)

    async def test_search_context_slots_and_reply_validation_keep_valid_webchat_bot_self_memory(self) -> None:
        from astrbot_plugin_memory_companion.core.service import MemoryCompanionService

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        service = MemoryCompanionService(
            context=None,
            plugin_root=ROOT,
            data_dir=directory.name,
            config={
                "retrieval": {"mode": "basic", "embedding_enabled": False},
                "visibility": {
                    "enable_acl_rules": False,
                    "allow_group_public_in_private": True,
                    "allow_self_timeline_everywhere": True,
                },
                "memory_injection": {"max_chars": 3000, "enable_injection_logs": False},
            },
        )
        self.addCleanup(service.close)

        qq_group_public_mem = _record(
            id="qq-group-public-mem",
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="qq-u1"),
            object=EntityRef.bot_self("b1"),
            owner_bot_id="b1",
            scope="group",
            group_id="group-99",
            session_id="onebot_qq:GroupMessage:group-99",
            platform="onebot_qq",
            visibility="group_public",
            content="QQ群里聊到周末去喝无糖抹茶拿铁。",
            confidence=0.98,
            importance=0.95,
            metadata={"owner_bot_id": "b1"},
        )
        webchat_bot_self_mem = _record(
            id="webchat-bot-self-mem",
            memory_type="manual_memory",
            subject=EntityRef.bot_self("b1"),
            object=EntityRef.bot_self("b1"),
            owner_bot_id="b1",
            scope="private",
            session_id="webchat:FriendMessage:web-u1",
            platform="webchat",
            visibility="bot_self",
            content="我在网页端记下自己喜欢无糖抹茶拿铁。",
            confidence=0.92,
            importance=0.90,
            metadata={"owner_bot_id": "b1"},
        )
        await service.store.insert_memory(qq_group_public_mem)
        await service.store.insert_memory(webchat_bot_self_mem)

        webchat_ctx = _ctx(
            session_id="webchat:FriendMessage:web-u1",
            scope="private",
            platform="webchat",
            user_id="web-u1",
            bot_id="b1",
            message_id="turn-webchat-1",
            message_text="无糖抹茶拿铁",
        )
        results, blocked, slot_map = await service.search_context_slots("无糖抹茶拿铁", webchat_ctx, top_k=6)
        selected_ids = [item.memory.id for item in results]
        self.assertNotIn("qq-group-public-mem", selected_ids)
        self.assertIn("webchat-bot-self-mem", selected_ids)
        self.assertTrue(
            any("other_platform" in str(item.get("reason", "")) for item in blocked)
        )

        injection = service.injection.compose(
            webchat_ctx,
            results,
            max_chars=3000,
            slot_sections=service._slot_sections(slot_map),
        )
        self.assertTrue(injection)
        ref_ids = [ref["id"] for ref in injection.memory_refs]
        self.assertEqual(["webchat-bot-self-mem"], ref_ids)

        current, _revision = await service._validate_reply_memory_refs(
            webchat_ctx, injection.memory_refs, slot_map
        )
        self.assertTrue(current)

        req = SimpleNamespace(prompt="用户提问", contexts=[], extra_user_content_parts=[])
        event = SimpleNamespace()
        published = await service._publish_reply_memory_context(
            webchat_ctx,
            req,
            event=event,
            injection=injection,
            slot_map=slot_map,
            strategy_id="existing.search_context_slots",
        )
        self.assertTrue(published)
        self.assertEqual(
            ["webchat-bot-self-mem"],
            event.memory_companion_injection_state["injected_memory_ids"],
        )


if __name__ == "__main__":
    unittest.main()
