"""Native login and legacy source validation with synthetic events only."""
import json
import unittest
from . import test_linked_memory_store as fixtures
from .test_linked_memory_store import record, member, BEFORE, AFTER


class NativeWechatMemoryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.LinkedMemoryStoreTests.asyncSetUp
    read = fixtures.LinkedMemoryStoreTests.read

    async def legacy(self, *, owner="self", persona="", refs=None, **changes):
        self.scope["members"][1]["memory_identity"] = {"owner_bot_id":"wechat-login","platform_name":"wechat_native"}
        source = dict(event_type="user_message", session_id=member("b")["session_id"], scope="private",
            subject_id="b", object_id="b", content="SYNTHETIC_SOURCE", occurred_at=AFTER,
            metadata={"owner_bot_id":"wechat-login","persona_id":"persona","platform":"wechat_native"})
        source.update(changes)
        self.source_id = await self.store.add_timeline_event(**source)
        item = record("b", identifier="legacy", persona=persona)
        item.memory_type="conversation_summary";item.owner_bot_id=owner;item.subject.id=""
        item.metadata["source_event_ids"] = refs if refs is not None else [self.source_id]
        await self.store.insert_memory(item)

    async def ids(self):
        return {r.id for r in (await self.read(limit=20))["records"]}

    async def test_complete_sources_restore_legacy_without_mutation(self):
        await self.legacy()
        before=[tuple(r) for r in self.store._conn.execute("SELECT * FROM memories ORDER BY id")]
        result=await self.read(limit=20)
        self.assertIn("legacy",{r.id for r in result["records"]})
        self.assertEqual(result["provenance"]["legacy"],{"user_id":"b","owner_bot_id":"wechat-login","original_owner_bot_id":"self"})
        self.assertEqual(sum(result["type_counts"].values()),len(result["records"]))
        self.assertEqual(before,[tuple(r) for r in self.store._conn.execute("SELECT * FROM memories ORDER BY id")])

    async def test_native_login_mapping_does_not_use_adapter_alias(self):
        await self.legacy(owner="wechat-login",persona="persona")
        self.assertIn("legacy",await self.ids());self.assertNotIn("memory-b",await self.ids())

    async def test_requires_host_native_mapping(self):
        await self.legacy();del self.scope["members"][1]["memory_identity"]
        self.assertNotIn("legacy",await self.ids())

    async def test_missing_reference_is_rejected(self):
        await self.legacy(refs=["missing"]);self.assertNotIn("legacy",await self.ids())

    async def test_partial_sources_are_rejected(self):
        await self.legacy()
        self.store._conn.execute("UPDATE memories SET metadata=json_set(metadata,'$.source_event_ids',json(?)) WHERE id='legacy'",(json.dumps([self.source_id,"missing"]),));self.store._conn.commit()
        self.assertNotIn("legacy",await self.ids())

    async def test_wrong_source_persona_is_rejected(self):
        await self.legacy(metadata={"owner_bot_id":"wechat-login","persona_id":"other","platform":"wechat_native"})
        self.assertNotIn("legacy",await self.ids())

    async def test_explicit_record_persona_is_never_overridden(self):
        await self.legacy(persona="other");self.assertNotIn("legacy",await self.ids())

    async def test_wrong_source_login_is_rejected(self):
        await self.legacy(metadata={"owner_bot_id":"other","persona_id":"persona","platform":"wechat_native"})
        self.assertNotIn("legacy",await self.ids())

    async def test_wrong_source_peer_is_rejected(self):
        await self.legacy(subject_id="other");self.assertNotIn("legacy",await self.ids())

    async def test_wrong_source_session_is_rejected(self):
        await self.legacy(session_id="other:FriendMessage:b");self.assertNotIn("legacy",await self.ids())

    async def test_group_source_is_rejected(self):
        await self.legacy(scope="group");self.assertNotIn("legacy",await self.ids())

    async def test_explicit_other_owner_is_not_overridden(self):
        await self.legacy(owner="other");self.assertNotIn("legacy",await self.ids())

    async def test_acl_handles_empty_legacy_subject(self):
        await self.legacy()
        self.store._conn.execute("INSERT INTO memory_acl_rules(id,owner_scope,owner_id,reader_scope,reader_id,effect) VALUES('deny-legacy','private','b','private','a','deny')");self.store._conn.commit()
        self.assertNotIn("legacy",await self.ids())

    async def test_preconsent_source_is_rejected(self):
        await self.legacy(occurred_at=BEFORE);self.assertNotIn("legacy",await self.ids())

    async def test_source_deletion_revokes_legacy(self):
        await self.legacy();self.assertIn("legacy",await self.ids())
        self.store._conn.execute("DELETE FROM timeline WHERE id=?",(self.source_id,));self.store._conn.commit()
        self.assertNotIn("legacy",await self.ids())
