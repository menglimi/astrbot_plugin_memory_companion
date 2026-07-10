from __future__ import annotations

import unittest

from astrbot_plugin_remember_you.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_remember_you.core.service import MemoryCompanionService
from astrbot_plugin_remember_you.core.visibility import VisibilityPolicy


class StrictSessionVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = VisibilityPolicy(allow_self_timeline_everywhere=True)
        self.context = SessionContext(
            session_id="platform:FriendMessage:user-1",
            scope="private",
            user_id="user-1",
            strict_session_only=True,
        )

    def test_other_session_for_the_same_user_is_not_visible(self) -> None:
        memory = MemoryRecord(
            session_id="other:FriendMessage:user-1",
            scope="private",
            visibility="private_pair",
            subject=EntityRef(kind="user", id="user-1"),
        )
        self.assertEqual(self.policy.is_visible(memory, self.context), (False, "strict_session_mismatch"))

    def test_current_session_memory_remains_visible(self) -> None:
        memory = MemoryRecord(
            session_id=self.context.session_id,
            scope="private",
            visibility="private_pair",
            subject=EntityRef(kind="user", id="user-1"),
        )
        self.assertEqual(self.policy.is_visible(memory, self.context), (True, "same_private_session"))

    def test_bridge_context_preserves_strict_session_flag(self) -> None:
        service = object.__new__(MemoryCompanionService)
        context = service.session_context_from_bridge(
            {
                "session_id": "platform:FriendMessage:user-1",
                "scope": "private",
                "user_id": "user-1",
                "strict_session_only": True,
            }
        )
        self.assertTrue(context.strict_session_only)
        self.assertTrue(service._normalized_session_context(context).strict_session_only)


if __name__ == "__main__":
    unittest.main()
