from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.classifier import MemoryClassifier  # noqa: E402
from core.emotion_targeting import memory_emotion_refs  # noqa: E402
from core.models import EntityRef, MemoryRecord, SessionContext  # noqa: E402


class EmotionE7ActorTargetMemoryTests(unittest.TestCase):
    def test_matching_subject_and_session_are_preserved(self) -> None:
        memory = MemoryRecord(
            id="m1",
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            subject=EntityRef(kind="user", id="u1", role="speaker"),
            object=EntityRef(kind="bot", id="b1", role="bot_self"),
            metadata={"owner_bot_id": "b1"},
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )
        refs = memory_emotion_refs(memory, ctx)
        self.assertEqual("u1", refs["actor_ref"]["id"])
        self.assertEqual("b1", refs["target_ref"]["id"])

    def test_cross_session_or_different_user_is_rejected(self) -> None:
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )
        for memory in (
            MemoryRecord(id="m1", session_id="qq:FriendMessage:u2", scope="private", platform="qq", subject=EntityRef(kind="user", id="u1"), metadata={"owner_bot_id": "b1"}),
            MemoryRecord(id="m2", session_id="qq:FriendMessage:u1", scope="private", platform="qq", subject=EntityRef(kind="user", id="u2"), metadata={"owner_bot_id": "b1"}),
            MemoryRecord(id="m3", session_id="qq:FriendMessage:u1", scope="private", platform="qq", subject=EntityRef(kind="other", id="nickname"), metadata={"owner_bot_id": "b1"}),
        ):
            with self.subTest(memory=memory.id):
                self.assertIsNone(memory_emotion_refs(memory, ctx))

    def test_current_user_target_from_classifier_keeps_verified_bot_owner(self) -> None:
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小明",
            bot_id="b1",
            message_text="今天心情很好",
        )
        record = MemoryClassifier().from_user_message(ctx)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("user", record.object.kind)
        self.assertEqual("u1", record.object.id)
        self.assertEqual("b1", record.metadata["owner_bot_id"])
        refs = memory_emotion_refs(record, ctx)
        self.assertIsNotNone(refs)
        assert refs is not None
        self.assertEqual("u1", refs["actor_ref"]["id"])
        self.assertEqual("b1", refs["target_ref"]["id"])

    def test_self_owner_is_a_shared_bot_sentinel(self) -> None:
        memory = MemoryRecord(
            id="m-self",
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            subject=EntityRef(kind="user", id="u1", role="speaker"),
            object=EntityRef(kind="bot", id="b1", role="bot_self"),
            metadata={"owner_bot_id": "self"},
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )

        refs = memory_emotion_refs(memory, ctx)

        self.assertIsNotNone(refs)
        self.assertEqual("b1", refs["target_ref"]["id"])

    def test_missing_bot_id_allows_only_a_matching_self_sentinel(self) -> None:
        base = {
            "session_id": "qq:FriendMessage:u1",
            "scope": "private",
            "platform": "qq",
            "subject": EntityRef(kind="user", id="u1", role="speaker"),
        }
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="",
        )
        sentinel = MemoryRecord(
            id="m-self-missing-bot",
            **base,
            object=EntityRef(kind="bot", id="self", role="bot_self"),
            metadata={"owner_bot_id": "self"},
        )
        explicit_owner = MemoryRecord(
            id="m-explicit-missing-bot",
            **base,
            object=EntityRef(kind="bot", id="b1", role="bot_self"),
            metadata={"owner_bot_id": "b1"},
        )

        refs = memory_emotion_refs(sentinel, ctx)

        self.assertIsNotNone(refs)
        self.assertEqual("self", refs["target_ref"]["id"])
        self.assertIsNone(memory_emotion_refs(explicit_owner, ctx))

    def test_nickname_text_is_not_used_as_identity(self) -> None:
        memory = SimpleNamespace(
            session_id="session-a",
            content="小明说你是垃圾",
            subject=SimpleNamespace(kind="user", id="", role="speaker", name="小明"),
        )
        ctx = SessionContext(session_id="session-a", scope="private", platform="qq", user_id="u1", bot_id="b1")
        self.assertIsNone(memory_emotion_refs(memory, ctx))

    def test_recalled_memory_owner_domain_mismatches_are_rejected(self) -> None:
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )
        base = {
            "session_id": "qq:FriendMessage:u1",
            "scope": "private",
            "platform": "qq",
            "subject": EntityRef(kind="user", id="u1", role="speaker"),
        }
        for suffix, overrides in (
            ("owner", {"metadata": {"owner_bot_id": "b2"}}),
            ("target", {"object": EntityRef(kind="bot", id="b2", role="bot_self")}),
            ("unowned_user_target", {"object": EntityRef(kind="user", id="u1", role="current_private_user")}),
            ("platform", {"platform": "wechat", "metadata": {"owner_bot_id": "b1"}}),
            ("scope", {"scope": "group", "metadata": {"owner_bot_id": "b1"}}),
        ):
            with self.subTest(domain=suffix):
                memory = MemoryRecord(id=f"m-{suffix}", **(base | overrides))
                self.assertIsNone(memory_emotion_refs(memory, ctx))

    def test_self_owner_is_a_shared_bot_sentinel(self) -> None:
        memory = MemoryRecord(
            id="m-self",
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            subject=EntityRef(kind="user", id="u1", role="speaker"),
            object=EntityRef(kind="bot", id="b1", role="bot_self"),
            metadata={"owner_bot_id": "self"},
        )
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
        )

        refs = memory_emotion_refs(memory, ctx)

        self.assertIsNotNone(refs)
        self.assertEqual("b1", refs["target_ref"]["id"])

    def test_missing_bot_id_allows_only_a_matching_self_sentinel(self) -> None:
        base = {
            "session_id": "qq:FriendMessage:u1",
            "scope": "private",
            "platform": "qq",
            "subject": EntityRef(kind="user", id="u1", role="speaker"),
        }
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="",
        )
        sentinel = MemoryRecord(
            id="m-self-missing-bot",
            **base,
            object=EntityRef(kind="bot", id="self", role="bot_self"),
            metadata={"owner_bot_id": "self"},
        )
        explicit_owner = MemoryRecord(
            id="m-explicit-missing-bot",
            **base,
            object=EntityRef(kind="bot", id="b1", role="bot_self"),
            metadata={"owner_bot_id": "b1"},
        )

        refs = memory_emotion_refs(sentinel, ctx)

        self.assertIsNotNone(refs)
        self.assertEqual("self", refs["target_ref"]["id"])
        self.assertIsNone(memory_emotion_refs(explicit_owner, ctx))


if __name__ == "__main__":
    unittest.main()
