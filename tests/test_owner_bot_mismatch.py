from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.memory_lifecycle import evaluate_memory_lifecycle
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


def make_engine() -> RetrievalEngine:
    """Build a RetrievalEngine backed by a throwaway store."""
    temp_dir = tempfile.TemporaryDirectory()
    store = MemoryStore(Path(temp_dir.name) / "test.db")
    store.close()
    return RetrievalEngine(
        store,
        VisibilityPolicy(
            allow_self_timeline_everywhere=True,
            allow_group_public_in_private=False,
            hide_pending_review=True,
            include_raw_events=False,
            enable_acl_rules=True,
        ),
        retrieval_mode="basic",
        embedding_enabled=False,
        knowledge_graph_enabled=False,
    )


class OwnerBotLifecycleTests(unittest.TestCase):
    def ctx(self, bot_id: str = "unknown_selfid") -> SessionContext:
        return SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id=bot_id,
            message_text="hi",
        )

    def summary(self, owner_bot_id: str = "") -> MemoryRecord:
        return MemoryRecord(
            id="summary",
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="user"),
            object=EntityRef.bot_self("unknown_selfid"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            visibility="private_pair",
            reality_level="llm_summary",
            lifecycle="stable_memory",
            owner_bot_id=owner_bot_id,
            content="2026-08-27 凌晨，用户和 Bot 聊了特调配方。",
            confidence=0.72,
            importance=0.9,
        )

    def test_owner_bot_self_is_released_from_mismatch(self) -> None:
        """owner_bot_id='self' 视为无特定 bot owner，不再被 owner_bot_mismatch 误杀。

        背景：写入侧经 bridge 记录时 bot_id 缺失回退为 'self'，检索侧
        ctx.bot_id 是具体值（如 'unknown_selfid'），旧逻辑会把这类记忆永久剔除。
        """
        lifecycle = evaluate_memory_lifecycle(self.summary(owner_bot_id="self"), self.ctx())
        self.assertTrue(lifecycle.eligible)
        self.assertNotIn("owner_bot_mismatch", lifecycle.reason)

    def test_empty_owner_bot_is_released(self) -> None:
        """owner_bot_id='' 同样放行。"""
        lifecycle = evaluate_memory_lifecycle(self.summary(owner_bot_id=""), self.ctx())
        self.assertTrue(lifecycle.eligible)

    def test_other_bot_owner_still_mismatched(self) -> None:
        """明确的其他 bot owner 仍被隔离（owner_bot_mismatch 保持生效）。"""
        lifecycle = evaluate_memory_lifecycle(self.summary(owner_bot_id="other_bot"), self.ctx())
        self.assertFalse(lifecycle.eligible)
        self.assertIn("owner_bot_mismatch", lifecycle.reason)

    def test_matching_owner_bot_id_still_eligible(self) -> None:
        """owner_bot_id 与 ctx.bot_id 一致时正常放行（不破坏原有匹配逻辑）。"""
        lifecycle = evaluate_memory_lifecycle(
            self.summary(owner_bot_id="unknown_selfid"), self.ctx(bot_id="unknown_selfid")
        )
        self.assertTrue(lifecycle.eligible)

    def test_platform_name_is_not_a_specific_bot_owner(self) -> None:
        memory = self.summary(owner_bot_id="QQ")
        memory.platform = "qq"
        lifecycle = evaluate_memory_lifecycle(memory, self.ctx(bot_id="another-self-id"))
        self.assertTrue(lifecycle.eligible)

    def test_platform_name_owner_does_not_block_group_visibility(self) -> None:
        policy = VisibilityPolicy()
        context = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            group_id="g1",
            bot_id="bot-1",
        )
        memory = MemoryRecord(
            id="group-memory",
            scope="group",
            group_id="g1",
            platform="QQ",
            visibility="group_public",
            metadata={"owner_bot_id": "qq"},
        )

        self.assertEqual(policy.is_visible(memory, context), (True, "same_group"))
        memory.metadata["owner_bot_id"] = "bot-2"
        self.assertEqual(policy.is_visible(memory, context), (False, "other_bot_owner"))

    def test_platform_name_keeps_legacy_summary_ambiguity_guard(self) -> None:
        policy = VisibilityPolicy()
        context = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            group_id="g1",
            bot_id="bot-1",
        )
        memory = MemoryRecord(
            id="legacy-group-summary",
            memory_type="conversation_summary",
            scope="group",
            group_id="g1",
            platform="qq",
            visibility="group_public",
            metadata={
                "owner_bot_id": "qq",
                "summarizer": "companion_memory_schema_v1",
            },
        )

        self.assertEqual(policy.is_visible(memory, context), (False, "ambiguous_bot_owner"))


class SummarySlotRoutingTests(unittest.TestCase):
    def ctx(self) -> SessionContext:
        return SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="unknown_selfid",
            message_text="hi",
        )

    def test_private_summary_routes_to_summary_slot(self) -> None:
        """私聊 conversation_summary 优先归 summary 槽，即使 promise 权重很高。

        旧逻辑会被 _memory_is_open_loop（promise_weight >= 0.35）吸进 open_loop 槽
        （limit=1），导致 summary 槽长期空置。
        """
        engine = make_engine()
        memory = MemoryRecord(
            id="summary",
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="user"),
            object=EntityRef.bot_self("unknown_selfid"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            visibility="private_pair",
            reality_level="llm_summary",
            lifecycle="stable_memory",
            content="用户和 Bot 聊了后续安排。",
            confidence=0.72,
            importance=0.9,
            metadata={
                "promise_weight": 0.85,
                "open_loop_weight": 0.62,
                "relationship_phase": "repair",
            },
        )
        self.assertEqual("conversation_summary", engine._slot_for_memory(memory, self.ctx()))

    def test_group_summary_routes_to_self_timeline(self) -> None:
        """群聊总结 subject=bot，走 self_timeline 槽（原版行为，本修复不改变）。"""
        engine = make_engine()
        memory = MemoryRecord(
            id="group-summary",
            memory_type="conversation_summary",
            subject=EntityRef.bot_self("b1", "bot"),
            object=EntityRef(kind="group", id="g1", name="group"),
            scope="group",
            session_id="qq:GroupMessage:g1",
            group_id="g1",
            visibility="group_public",
            reality_level="llm_summary",
            lifecycle="stable_memory",
            content="群成员讨论了计划。",
            confidence=0.72,
            importance=0.9,
            metadata={"promise_weight": 0.8},
        )
        ctx = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id="u1",
            group_id="g1",
            bot_id="b1",
            message_text="hi",
        )
        self.assertEqual("self_timeline", engine._slot_for_memory(memory, ctx))

    def test_promise_memory_still_routes_to_open_loop(self) -> None:
        """非总结类的高 promise 权重记忆仍归 open_loop 槽（open_loop 判定未被破坏）。"""
        engine = make_engine()
        memory = MemoryRecord(
            id="promise",
            memory_type="observation",
            subject=EntityRef(kind="user", id="u1", name="user"),
            object=EntityRef.bot_self("unknown_selfid"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            visibility="private_pair",
            reality_level="real_user_fact",
            lifecycle="stable_memory",
            content="用户承诺明天一起去买琴弦。",
            confidence=0.7,
            importance=0.6,
            metadata={"promise_weight": 0.9},
        )
        self.assertEqual("open_loop", engine._slot_for_memory(memory, self.ctx()))


if __name__ == "__main__":
    unittest.main()
