from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.chat_import import HistoricalChatImporter
from astrbot_plugin_memory_companion.core.identity import IdentityResolver
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy
from astrbot_plugin_memory_companion.unified_profile_contract import build_profile_dto


PERSON_ID = "person_" + "a" * 24


def profile_dto(*, assurance: str = "explicit_linked", status: str = "active") -> dict:
    return build_profile_dto(
        person_ref={
            "person_id": PERSON_ID,
            "resolved_identity_key": "chat-origin-v1:" + "b" * 64,
            "projection_revision": 1,
            "identity_assurance": assurance,
            "profile_status": status,
        }
    )


class IdentityLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_identity_resolver_accepts_only_active_explicit_link(self) -> None:
        class Event:
            unified_msg_origin = "qq:FriendMessage:old-user"

            def __init__(self, dto):
                self.private_companion_unified_profile_context = dto

            async def get_platform_name(self):
                return "qq"

            async def get_sender_id(self):
                return "old-user"

            async def get_sender_name(self):
                return "用户"

            async def get_self_id(self):
                return "old-bot"

        resolver = IdentityResolver()
        context = await resolver.resolve_event_context(Event(profile_dto()))
        observed = await resolver.resolve_event_context(Event(profile_dto(assurance="observed")))
        suspended = await resolver.resolve_event_context(Event(profile_dto(status="suspended")))

        self.assertEqual((PERSON_ID, "explicit_linked"), (context.subject_person_id, context.identity_assurance))
        self.assertEqual(("", ""), (observed.subject_person_id, observed.identity_assurance))
        self.assertEqual(("", ""), (suspended.subject_person_id, suspended.identity_assurance))

    async def test_normalized_context_keeps_verified_person_binding(self) -> None:
        service = object.__new__(MemoryCompanionService)
        context = SessionContext(
            session_id="qq:FriendMessage:old-user",
            scope="private",
            user_id="old-user",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
        )

        normalized = service._normalized_session_context(context)

        self.assertEqual(PERSON_ID, normalized.subject_person_id)
        self.assertEqual("explicit_linked", normalized.identity_assurance)

    def test_explicit_person_link_allows_cross_platform_and_bot_private_memory(self) -> None:
        policy = VisibilityPolicy()
        context = SessionContext(
            session_id="web:FriendMessage:new-user",
            scope="private",
            platform="web",
            user_id="new-user",
            bot_id="new-bot",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
        )
        memory = MemoryRecord(
            id="linked-memory",
            subject=EntityRef(kind="user", id="old-user"),
            object=EntityRef.bot_self("old-bot"),
            scope="private",
            session_id="qq:FriendMessage:old-user",
            platform="qq",
            visibility="private_pair",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
            metadata={"owner_bot_id": "old-bot"},
        )

        self.assertEqual((True, "explicit_linked_person"), policy.is_visible(memory, context))

    def test_unverified_mismatched_and_strict_contexts_remain_isolated(self) -> None:
        policy = VisibilityPolicy()
        memory = MemoryRecord(
            id="linked-memory",
            subject=EntityRef(kind="user", id="old-user"),
            object=EntityRef.bot_self("old-bot"),
            scope="private",
            session_id="qq:FriendMessage:old-user",
            platform="qq",
            visibility="private_pair",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
            metadata={"owner_bot_id": "old-bot"},
        )
        unverified_context = SessionContext(
            session_id="web:FriendMessage:new-user",
            scope="private",
            platform="web",
            user_id="new-user",
            bot_id="old-bot",
            subject_person_id=PERSON_ID,
            identity_assurance="verified",
        )
        mismatch_context = SessionContext(
            session_id="web:FriendMessage:new-user",
            scope="private",
            platform="web",
            user_id="new-user",
            bot_id="old-bot",
            subject_person_id="person_" + "c" * 24,
            identity_assurance="explicit_linked",
        )
        relinked_context = SessionContext(
            session_id="qq:private:old-user",
            scope="private",
            platform="qq",
            user_id="old-user",
            bot_id="old-bot",
            subject_person_id="person_" + "c" * 24,
            identity_assurance="explicit_linked",
        )
        strict_context = SessionContext(
            session_id="web:FriendMessage:new-user",
            scope="private",
            platform="web",
            user_id="new-user",
            bot_id="old-bot",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
            strict_session_only=True,
        )

        self.assertFalse(policy.is_visible(memory, unverified_context)[0])
        self.assertFalse(policy.is_visible(memory, mismatch_context)[0])
        self.assertEqual((False, "other_person"), policy.is_visible(memory, relinked_context))
        self.assertEqual((False, "strict_session_mismatch"), policy.is_visible(memory, strict_context))

    async def test_candidate_sql_loads_only_matching_explicit_person_records(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        linked = MemoryRecord(
                id="linked-memory",
                memory_type="manual_memory",
                subject=EntityRef(kind="user", id="old-user"),
                object=EntityRef.bot_self("old-bot"),
                scope="private",
                session_id="qq:FriendMessage:old-user",
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="cross-platform fact",
                subject_person_id=PERSON_ID,
                identity_assurance="explicit_linked",
                metadata={"owner_bot_id": "old-bot"},
        )
        unlinked = MemoryRecord(
                id="unlinked-memory",
                memory_type="manual_memory",
                subject=EntityRef(kind="user", id="other-user"),
                object=EntityRef.bot_self("old-bot"),
                scope="private",
                session_id="qq:FriendMessage:other-user",
                platform="qq",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="unlinked fact",
                metadata={"owner_bot_id": "old-bot"},
        )
        await store.insert_memory(linked)
        await store.insert_memory(unlinked)

        candidates = await store.list_current_window_candidate_memories(
            scope="private",
            session_id="web:FriendMessage:new-user",
            user_id="new-user",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
        )
        restored = await store.get_memory("linked-memory")

        self.assertEqual(["linked-memory"], [item.id for item in candidates])
        self.assertEqual((PERSON_ID, "explicit_linked"), (restored.subject_person_id, restored.identity_assurance))

    async def test_duplicate_write_attaches_identity_without_merging_other_people(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)

        base = {
            "memory_type": "manual_memory",
            "subject": EntityRef(kind="user", id="old-user"),
            "object": EntityRef.bot_self("old-bot"),
            "scope": "private",
            "session_id": "qq:FriendMessage:old-user",
            "platform": "qq",
            "visibility": "private_pair",
            "lifecycle": "stable_memory",
            "content": "same private fact",
            "metadata": {"owner_bot_id": "old-bot"},
        }
        await store.insert_memory(MemoryRecord(id="legacy-memory", **base))
        linked_id = await store.insert_memory(
            MemoryRecord(
                id="linked-import",
                **base,
                subject_person_id=PERSON_ID,
                identity_assurance="explicit_linked",
            )
        )
        separate_id = await store.insert_memory(
            MemoryRecord(
                id="other-person-import",
                **base,
                subject_person_id="person_" + "c" * 24,
                identity_assurance="explicit_linked",
            )
        )

        legacy = await store.get_memory("legacy-memory")
        separate = await store.get_memory("other-person-import")

        self.assertEqual("legacy-memory", linked_id)
        self.assertEqual((PERSON_ID, "explicit_linked"), (legacy.subject_person_id, legacy.identity_assurance))
        self.assertEqual("other-person-import", separate_id)
        self.assertEqual("person_" + "c" * 24, separate.subject_person_id)

    async def test_direct_retrieval_candidates_keep_explicit_link_and_acl_path(self) -> None:
        policy = VisibilityPolicy(enable_acl_rules=False)
        engine = RetrievalEngine(object(), policy)
        context = SessionContext(
            session_id="web:FriendMessage:new-user",
            scope="private",
            platform="web",
            user_id="new-user",
            bot_id="new-bot",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
        )
        memory = MemoryRecord(
            id="linked-memory",
            subject=EntityRef(kind="user", id="old-user"),
            object=EntityRef.bot_self("old-bot"),
            scope="private",
            session_id="qq:FriendMessage:old-user",
            platform="qq",
            visibility="private_pair",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
            metadata={"owner_bot_id": "old-bot"},
        )

        visible, blocked = await engine.filter_visible_candidates([memory], context)

        self.assertEqual(["linked-memory"], [item.memory.id for item in visible])
        self.assertEqual([], blocked)

    def test_acl_deny_still_overrides_explicit_person_link(self) -> None:
        engine = RetrievalEngine(object(), VisibilityPolicy())
        context = SessionContext(
            session_id="web:FriendMessage:new-user",
            scope="private",
            platform="web",
            user_id="new-user",
            bot_id="new-bot",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
        )
        memory = MemoryRecord(
            id="linked-memory",
            subject=EntityRef(kind="user", id="old-user"),
            object=EntityRef.bot_self("old-bot"),
            scope="private",
            session_id="qq:FriendMessage:old-user",
            platform="qq",
            visibility="private_pair",
            subject_person_id=PERSON_ID,
            identity_assurance="explicit_linked",
            metadata={"owner_bot_id": "old-bot"},
        )
        acl_state = engine._empty_acl_state()
        acl_state["deny"] = {("private", "old-user", "private", "new-user")}

        visible_reason, blocked_reason = engine._search_visibility_reason(memory, context, acl_state)

        self.assertEqual("", visible_reason)
        self.assertTrue(blocked_reason.startswith("acl_denied:"))


class HistoricalImportIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_person_id_is_validated_fingerprinted_and_persisted(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)

        class Service:
            data_dir = Path(temp_dir.name)

            def __init__(self) -> None:
                self.store = store

            @staticmethod
            def _spawn_background(coro, *, label):
                coro.close()
                return None

        importer = HistoricalChatImporter(Service())
        preview = importer.stage_upload(
            filename="chat.txt",
            content=(
                "u: 2026-01-01 10:00:00\n你好\n\n"
                "b: 2026-01-01 10:00:05\n你好呀\n"
            ).encode("utf-8"),
        )
        payload = {
            "upload_id": preview["upload_id"],
            "speaker_map": {
                "u": {"role": "user", "entity_id": "u1", "display_name": "用户"},
                "b": {"role": "bot", "entity_id": "b1", "display_name": "Bot"},
            },
            "user_id": "u1",
            "bot_id": "b1",
            "subject_person_id": PERSON_ID,
        }

        with self.assertRaisesRegex(ValueError, "关联人物 ID"):
            await importer.start_import({**payload, "subject_person_id": "not-a-person"})
        first = await importer.start_import(payload)
        second = await importer.start_import(
            {**payload, "subject_person_id": "person_" + "c" * 24}
        )

        self.assertEqual(PERSON_ID, first["batch"]["stats"]["subject_person_id"])
        self.assertNotEqual(first["batch"]["id"], second["batch"]["id"])

        record = importer._summary_record(
            {
                "id": first["batch"]["id"],
                "session_id": "qq:FriendMessage:u1",
                "platform": "qq",
                "user_id": "u1",
                "bot_id": "b1",
                "stats": first["batch"]["stats"],
            },
            {
                "id": "segment-1",
                "start_at": "2026-01-01T10:00:00+08:00",
                "end_at": "2026-01-01T10:05:00+08:00",
                "message_ids": [],
            },
            {"summary": "用户询问天气。", "canonical_summary": "用户询问天气。", "confidence": 0.8, "importance": 0.6, "topics": []},
        )
        await store.insert_memory(record)
        persisted = await store.get_memory(record.id)

        self.assertEqual((PERSON_ID, "explicit_linked"), (persisted.subject_person_id, persisted.identity_assurance))


if __name__ == "__main__":
    unittest.main()
