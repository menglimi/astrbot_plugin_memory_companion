from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core.models import SessionContext
from astrbot_plugin_remember_you.core.service import MemoryCompanionService


class CrossWindowContinuityTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config=config
            or {
                "memory_injection": {"enable_injection_logs": False, "max_chars": 1800},
                "conversation_memory_advanced": {
                    "cross_window_recent_continuity_enabled": True,
                    "cross_window_recent_minutes": 30,
                    "cross_window_recent_event_limit": 6,
                    "cross_window_group_to_private_enabled": True,
                    "cross_window_private_to_group_enabled": True,
                    "low_information_guard_enabled": False,
                    "topic_shift_guard_enabled": False,
                },
            },
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def metadata(*, bot_id: str, user_id: str, platform: str = "qq") -> dict[str, str]:
        return {
            "owner_bot_id": bot_id,
            "platform": platform,
            "participant_user_id": user_id,
            "participant_user_name": user_id,
        }

    async def test_group_to_private_keeps_only_same_user_and_same_bot(self) -> None:
        service = self.make_service()
        now = datetime.now(timezone.utc)
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:GroupMessage:g1",
            scope="group",
            subject_id="u1",
            object_id="g1",
            content="部署方案先用蓝绿发布。",
            metadata=self.metadata(bot_id="b1", user_id="u1"),
            occurred_at=(now - timedelta(minutes=4)).isoformat(timespec="seconds"),
        )
        await service.store.add_timeline_event(
            event_type="bot_response",
            session_id="qq:GroupMessage:g1",
            scope="group",
            subject_id="b1",
            object_id="g1",
            content="可以，先切少量流量观察。",
            metadata=self.metadata(bot_id="b1", user_id="u1"),
            occurred_at=(now - timedelta(minutes=3)).isoformat(timespec="seconds"),
        )
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:GroupMessage:g1",
            scope="group",
            subject_id="u2",
            object_id="g1",
            content="这是其他群成员的话。",
            metadata=self.metadata(bot_id="b1", user_id="u2"),
            occurred_at=(now - timedelta(minutes=2)).isoformat(timespec="seconds"),
        )
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:GroupMessage:g2",
            scope="group",
            subject_id="u1",
            object_id="g2",
            content="这是另一个 Bot 看到的内容。",
            metadata=self.metadata(bot_id="b2", user_id="u1"),
            occurred_at=(now - timedelta(minutes=1)).isoformat(timespec="seconds"),
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_text="我们接着刚才群里的部署方案说。",
        )

        context = await service._recent_cross_window_context(ctx)

        self.assertIn("部署方案先用蓝绿发布", context)
        self.assertIn("先切少量流量观察", context)
        self.assertNotIn("其他群成员", context)
        self.assertNotIn("另一个 Bot", context)

    async def test_expired_group_context_is_not_returned(self) -> None:
        service = self.make_service()
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:GroupMessage:g1",
            scope="group",
            subject_id="u1",
            object_id="g1",
            content="四十分钟前的旧话题。",
            metadata=self.metadata(bot_id="b1", user_id="u1"),
            occurred_at=(datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat(timespec="seconds"),
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_text="继续",
        )

        self.assertEqual("", await service._recent_cross_window_context(ctx))

    async def test_private_to_group_requires_explicit_current_turn_authorization(self) -> None:
        service = self.make_service()
        self.assertFalse(service._message_explicitly_shares_private_context("告诉我群里谁知道我的私聊内容？"))
        self.assertTrue(service._message_explicitly_shares_private_context("可以在群里继续说我们刚才私聊的话题。"))
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:u1",
            scope="private",
            subject_id="u1",
            object_id="u1",
            content="私聊里约定先确认预算。",
            metadata=self.metadata(bot_id="b1", user_id="u1"),
        )
        blocked_ctx = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id="u1",
            group_id="g1",
            bot_id="b1",
            message_text="预算怎么安排？",
        )
        allowed_ctx = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id="u1",
            group_id="g1",
            bot_id="b1",
            message_text="把刚才私聊的预算约定带到群里继续说吧。",
        )
        denied_ctx = SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id="u1",
            group_id="g1",
            bot_id="b1",
            message_text="不要把刚才私聊的内容带到群里。",
        )

        self.assertEqual("", await service._recent_cross_window_context(blocked_ctx))
        self.assertEqual("", await service._recent_cross_window_context(denied_ctx))
        allowed = await service._recent_cross_window_context(allowed_ctx)
        self.assertIn("本轮明确授权", allowed)
        self.assertIn("私聊里约定先确认预算", allowed)

    async def test_main_injection_receives_semantic_cross_window_capsule(self) -> None:
        service = self.make_service()
        await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:GroupMessage:g1",
            scope="group",
            subject_id="u1",
            object_id="g1",
            content="刚才讨论的关键是先做灰度验证。",
            metadata=self.metadata(bot_id="b1", user_id="u1"),
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_text="那就接着刚才的方案说。",
        )

        async def fake_search(*_args, **_kwargs):
            return [], [], {}

        service.search_context_slots = fake_search
        captured: dict[str, str] = {}
        original_compose = service.injection.compose

        def capture_compose(*args, **kwargs):
            captured["capsule"] = str(kwargs.get("recent_cross_window_context") or "")
            result = original_compose(*args, **kwargs)
            captured["injection"] = result
            return result

        service.injection.compose = capture_compose
        req = SimpleNamespace(prompt="", system_prompt="", contexts=[], extra_user_content_parts=[])

        await service.inject_memories(ctx, req)

        self.assertIn("灰度验证", captured.get("capsule", ""))
        self.assertIn("<recent_cross_window_context>", captured.get("injection", ""))
        self.assertIn("语义上自然延续", captured.get("injection", ""))
        self.assertIn("若当前消息已换题", captured.get("injection", ""))


if __name__ == "__main__":
    unittest.main()
