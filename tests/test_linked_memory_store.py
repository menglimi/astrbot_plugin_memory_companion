"""Synthetic SQLite records exercise native ownership, history and summary scope."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .package_bootstrap import bootstrap_package
bootstrap_package()
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore

BEFORE = "2026-11-14T00:00:00+00:00"
CUTOFF = "2026-11-15T00:00:00+00:00"
AFTER = "2026-11-16T00:00:00+00:00"


def member(name, since=None):
    return {"subject_id": "subject-" + name, "platform": "adapter-" + name,
        "bot_id": "internal-bot-" + name, "account_id": "native-bot-" + name,
        "native_account_id": name, "role_id": "role", "session_id": "adapter-" + name + ":FriendMessage:" + name,
        "since": since}


def record(name, *, identifier=None, at=AFTER, persona="persona", **kwargs):
    return MemoryRecord(id=identifier or "memory-" + name, memory_type="manual_memory",
        subject=EntityRef(kind="user", id=name), object=EntityRef.bot_self("native-bot-" + name),
        scope="private", session_id=member(name)["session_id"], platform="adapter-type",
        visibility="private_pair", lifecycle="stable_memory", content="synthetic fact " + (identifier or name),
        owner_bot_id="native-bot-" + name, metadata={"persona_id": persona},
        created_at=at, occurred_at=at, **kwargs)


class LinkedMemoryStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory.db")
        self.store.initialize(); self.addCleanup(self.store.close)
        self.scope = {"schema": "companion.linked-memory-read.v1", "persona_id": "persona",
                      "reader_user_id": "a", "members": [member("a"), member("b", CUTOFF)]}
        for item in [record("a"), record("b"), record("b", identifier="old-b", at=BEFORE), record("c"),
                     record("b", identifier="other-persona", persona="someone-else")]:
            await self.store.insert_memory(item)

    async def read(self, **kwargs):
        return await self.store.read_authorized_linked_memories(self.scope, **kwargs)

    async def test_scope_filters_unlinked_accounts_other_personas_and_old_history(self):
        result = await self.read()
        self.assertEqual({"memory-a", "memory-b"}, {r.id for r in result["records"]})
        self.assertEqual(sum(result["type_counts"].values()), 2)

    async def test_separately_authorized_history_is_included(self):
        self.scope["members"][1]["since"] = None
        result = await self.read()
        self.assertEqual({"memory-a", "memory-b", "old-b"}, {r.id for r in result["records"]})

    async def test_missing_bot_or_persona_provenance_fails_closed(self):
        missing_persona = record("b", identifier="legacy", persona="")
        missing_bot = record("b", identifier="missing-bot"); missing_bot.owner_bot_id = ""
        missing_bot.object = EntityRef(kind="user", id="b")
        for item in [missing_persona, missing_bot]:
            await self.store.insert_memory(item)
        self.assertEqual(sum((await self.read())["type_counts"].values()), 2)

    async def test_same_user_id_in_other_window_or_bot_is_not_visible(self):
        item = record("b", identifier="wrong-window"); item.session_id = "other:FriendMessage:b"
        await self.store.insert_memory(item)
        item = record("b", identifier="wrong-bot"); item.owner_bot_id = "different-bot"
        await self.store.insert_memory(item)
        self.assertEqual(sum((await self.read())["type_counts"].values()), 2)

    async def test_group_internal_pending_archived_and_expired_are_excluded(self):
        for field, value in [("scope", "group"), ("visibility", "internal"), ("review_status", "pending"),
                             ("lifecycle", "archived"), ("lifecycle", "raw_event"), ("valid_to", BEFORE)]:
            item = record("b", identifier="excluded-" + field)
            setattr(item, field, value); await self.store.insert_memory(item)
        self.assertEqual(sum((await self.read())["type_counts"].values()), 2)

    async def test_importing_old_history_now_does_not_bypass_cutoff(self):
        item = record("b", identifier="imported-old"); item.occurred_at = BEFORE
        await self.store.insert_memory(item)
        self.assertEqual(sum((await self.read())["type_counts"].values()), 2)

    async def test_explicit_memory_deny_is_not_overridden_by_host_grant(self):
        with self.store._lock:
            self.store._conn.execute("INSERT INTO memory_acl_rules(id,owner_scope,owner_id,reader_scope,reader_id,effect) "
                "VALUES('deny','private','b','private','a','deny')")
            self.store._conn.commit()
        self.assertEqual({"memory-a"}, {r.id for r in (await self.read())["records"]})
        self.assertEqual(sum((await self.read())["type_counts"].values()), 1)

    async def test_summary_uses_same_predicate_even_when_no_contents_requested(self):
        full = await self.read(limit=20)
        summary = await self.read(limit=0)
        self.assertEqual(summary["records"], [])
        self.assertEqual(summary["type_counts"], full["type_counts"])
        self.assertEqual(sum(summary["type_counts"].values()), len(full["records"]))

    async def test_reads_do_not_change_original_ownership_or_row_count(self):
        before = [dict(row) for row in self.store._conn.execute("SELECT * FROM memories ORDER BY id")]
        await self.read()
        after = [dict(row) for row in self.store._conn.execute("SELECT * FROM memories ORDER BY id")]
        self.assertEqual(before, after)

    async def test_native_bot_uses_login_not_companions_internal_bot_identifier(self):
        self.assertNotEqual(self.scope["members"][0]["bot_id"], self.scope["members"][0]["account_id"])
        self.assertIn("memory-a", {r.id for r in (await self.read())["records"]})

    async def test_summary_spanning_before_consent_is_not_shared(self):
        item = record("b", identifier="mixed-summary")
        item.metadata["start_at"] = BEFORE
        await self.store.insert_memory(item)
        self.assertEqual(sum((await self.read())["type_counts"].values()), 2)

    async def test_adapter_session_suffix_can_differ_from_native_user(self):
        item = record("b", identifier="qualified-session")
        item.session_id = "adapter-b:FriendMessage:native-bot-b!b"
        await self.store.insert_memory(item)
        self.scope["members"][1]["session_id"] = item.session_id
        self.assertEqual({"memory-a", "qualified-session"}, {r.id for r in (await self.read())["records"]})
