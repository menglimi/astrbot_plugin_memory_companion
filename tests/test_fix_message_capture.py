from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class At:
    """与宿主组件同名，A2 门槛按类名识别消息段。"""

    def __init__(self, qq: str) -> None:
        self.qq = qq


class AtAll:
    pass


class Reply:
    def __init__(self, sender_id: str) -> None:
        self.sender_id = sender_id


class Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class MessageCaptureGateTests(unittest.IsolatedAsyncioTestCase):
    """A2：群聊默认不采集、只采集指向机器人的消息；私聊只落一条 timeline。"""

    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config=config or {},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def group_context(*, message_id: str = "group-msg-1", message_text: str = "今天天气不错") -> SessionContext:
        return SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id="u1",
            user_name="小王",
            group_id="g1",
            group_name="测试群",
            bot_id="b1",
            message_id=message_id,
            message_text=message_text,
        )

    @staticmethod
    def private_context(*, message_id: str = "private-msg-1", message_text: str = "在吗") -> SessionContext:
        return SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="b1",
            message_id=message_id,
            message_text=message_text,
        )

    @staticmethod
    def fake_event(components: list[object], *, self_id: str = "b1", message_str: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            get_self_id=lambda: self_id,
            get_messages=lambda: list(components),
            message_str=message_str,
            private_companion_proactive_framework=False,
        )

    async def observe(self, service: MemoryCompanionService, ctx: SessionContext, event: object) -> None:
        service.identity.resolve_event_context = AsyncMock(return_value=ctx)
        # 与采集门槛无关的重活全部打桩，避免测试依赖桥接/画像链路。
        service.reply_chain.resolve = AsyncMock(return_value=[])
        service.portraits.capture_user_message = AsyncMock(
            return_value={"ok": False, "code": "test_stub", "facts": 0}
        )
        await service.handle_group_message(event)

    @staticmethod
    def timeline_count(service: MemoryCompanionService, session_id: str) -> int:
        row = service.store._conn.execute(
            "SELECT COUNT(*) AS total FROM timeline WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row["total"])

    async def test_group_message_without_engagement_is_not_captured(self) -> None:
        service = self.make_service(
            {"conversation_memory": {"capture_group_messages": True}}
        )
        event = self.fake_event([Plain("今天天气不错")])

        await self.observe(service, self.group_context(), event)

        self.assertEqual(0, self.timeline_count(service, "qq:GroupMessage:g1"))

    async def test_group_message_with_at_bot_is_captured(self) -> None:
        service = self.make_service(
            {"conversation_memory": {"capture_group_messages": True}}
        )
        event = self.fake_event([At("b1"), Plain(" 在吗")])

        await self.observe(service, self.group_context(message_text="在吗"), event)

        self.assertEqual(1, self.timeline_count(service, "qq:GroupMessage:g1"))

    async def test_group_message_reply_to_bot_is_captured(self) -> None:
        service = self.make_service(
            {"conversation_memory": {"capture_group_messages": True}}
        )
        event = self.fake_event([Reply("b1"), Plain("刚才那句什么意思")])

        await self.observe(
            service, self.group_context(message_text="刚才那句什么意思"), event
        )

        self.assertEqual(1, self.timeline_count(service, "qq:GroupMessage:g1"))

    async def test_group_capture_keyword_counts_as_engagement(self) -> None:
        service = self.make_service(
            {
                "conversation_memory": {
                    "capture_group_messages": True,
                    "group_capture_keywords": ["小助手"],
                }
            }
        )
        event = self.fake_event([Plain("小助手你今天话好多")])

        await self.observe(
            service, self.group_context(message_text="小助手你今天话好多"), event
        )

        self.assertEqual(1, self.timeline_count(service, "qq:GroupMessage:g1"))

    async def test_group_capture_is_off_by_default(self) -> None:
        service = self.make_service()
        event = self.fake_event([At("b1"), Plain(" 在吗")])

        await self.observe(service, self.group_context(message_text="在吗"), event)

        self.assertEqual(0, self.timeline_count(service, "qq:GroupMessage:g1"))

    async def test_group_capture_all_messages_when_engagement_gate_disabled(self) -> None:
        service = self.make_service(
            {
                "conversation_memory": {
                    "capture_group_messages": True,
                    "group_capture_engagement_only": False,
                }
            }
        )
        event = self.fake_event([Plain("今天天气不错")])

        await self.observe(service, self.group_context(), event)

        self.assertEqual(1, self.timeline_count(service, "qq:GroupMessage:g1"))

    async def test_private_message_is_captured_once_and_deduped(self) -> None:
        service = self.make_service()
        ctx = self.private_context(message_id="private-dup-1", message_text="在吗")
        event = self.fake_event([Plain("在吗")])

        await self.observe(service, ctx, event)
        await self.observe(service, ctx, event)

        self.assertEqual(1, self.timeline_count(service, "qq:FriendMessage:u1"))

    async def test_host_wake_flag_does_not_bypass_the_group_gate(self) -> None:
        """宿主 WakingCheckStage 会给 catch-all handler 置 is_at_or_wake_command，
        门槛必须只看原始消息段，不能被这个标志骗过。"""
        service = self.make_service(
            {"conversation_memory": {"capture_group_messages": True}}
        )
        event = self.fake_event([Plain("今天天气不错")])
        event.is_at_or_wake_command = True
        event.is_wake = True

        await self.observe(service, self.group_context(), event)

        self.assertEqual(0, self.timeline_count(service, "qq:GroupMessage:g1"))

    async def test_private_message_is_not_double_written_by_llm_capture(self) -> None:
        """观察入口先落库后，on_llm_request 的采集链不能再写第二条。"""
        service = self.make_service()
        ctx = self.private_context(message_id="private-cross-1", message_text="在吗")
        event = self.fake_event([Plain("在吗")])

        await self.observe(service, ctx, event)
        await service._capture_async(ctx, event, None, None)

        self.assertEqual(1, self.timeline_count(service, "qq:FriendMessage:u1"))
        row = service.store._conn.execute(
            "SELECT metadata FROM timeline WHERE session_id = ?",
            ("qq:FriendMessage:u1",),
        ).fetchone()
        self.assertIn("group_conversation_observer", str(row["metadata"]))

    async def test_private_message_is_not_double_written_by_the_observer(self) -> None:
        """反序同样成立：llm_request 采集链先落库，观察入口只做去重。"""
        service = self.make_service()
        ctx = self.private_context(message_id="private-cross-2", message_text="在吗")
        event = self.fake_event([Plain("在吗")])

        await service._capture_async(ctx, event, None, None)
        before = self.timeline_count(service, "qq:FriendMessage:u1")
        await self.observe(service, ctx, event)

        self.assertEqual(1, before)
        self.assertEqual(1, self.timeline_count(service, "qq:FriendMessage:u1"))

    async def test_private_capture_can_be_switched_off(self) -> None:
        service = self.make_service(
            {"conversation_memory": {"capture_private_messages": False}}
        )
        event = self.fake_event([Plain("在吗")])

        await self.observe(service, self.private_context(), event)

        self.assertEqual(0, self.timeline_count(service, "qq:FriendMessage:u1"))


if __name__ == "__main__":
    unittest.main()
