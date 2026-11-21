"""Opt-in two-checkout contract test, using real owners and temporary SQLite only.

Set PRIVATE_COMPANION_CHECKOUT to the companion checkout before running this
module. No installed plugin, SDK, model provider or production data is used.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

from .package_bootstrap import bootstrap_package
bootstrap_package()
from .test_linked_memory_store import member, record, AFTER, BEFORE
from astrbot_plugin_memory_companion.core.companion_linkage import CompanionMemoryLinkage
from astrbot_plugin_memory_companion.core.store import MemoryStore

COMPANION = os.environ.get("PRIVATE_COMPANION_CHECKOUT")
if COMPANION:
    sys.path.insert(0, str(Path(COMPANION).resolve()))
    from companion_v2.adapters.astrbot.memory_providers import ExternalMemoryProviderRegistry
    from companion_v2.execution.models import TaskError
    from companion_v2.foundation.outcome import Outcome
    from companion_v2.foundation.refs import ScopeKind, SubjectKind
    from companion_v2.relationships.account_links import PrivateAccountLinks, member_for
    from companion_v2.relationships.account_link_memory import read_scope, CONFIRMATION, HISTORY_CONFIRMATION
    from companion_v2.storage.runtime import StorageRuntime


@unittest.skipUnless(COMPANION, "set PRIVATE_COMPANION_CHECKOUT for the two-plugin integration test")
class LinkedMemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.runtime = StorageRuntime.open(data_root=Path(self.temp.name) / "companion", installation_id="integration")
        self.addCleanup(self.runtime.close)
        self.store = MemoryStore(Path(self.temp.name) / "memory.db")
        self.store.initialize(); self.addCleanup(self.store.close)
        self.now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        self.personas = {name: "persona" for name in ("a", "b", "c")}
        self.blocked = set()
        self.contexts = {}
        for name in ("a", "b", "c"):
            m = member(name)
            subject = NS(subject_id=m["subject_id"], kind=SubjectKind.HUMAN)
            self.contexts[name] = NS(scope=NS(installation_id="integration", platform=m["platform"],
                bot_id=m["bot_id"], account_id=m["account_id"], native_scope_id=name,
                session_id=name, kind=ScopeKind.PRIVATE), actor=NS(subject=subject),
                audience=NS(recipients=(subject,)), role_binding=NS(role=NS(subject_id="role")))
        def access(context):
            if context.scope.native_scope_id in self.blocked:
                raise TaskError("permission_revoked", "synthetic access revoked")
        self.app = NS(runtime=self.runtime, now=lambda: self.now,
            tasks=NS(check_context_access=lambda *args, **kwargs: Outcome.success(True)),
            memory=NS(writer=NS(access=NS(check=access, policy_for=lambda _: NS(automatic_context=True)))),
            private_account_link_persona=lambda m: self.personas[m["native_account_id"]],
            private_account_link_resolve=lambda m: self.contexts[m["native_account_id"]])
        self.links = PrivateAccountLinks(self.runtime)
        self.plugin = NS(service=NS(store=self.store, config=NS(bool=lambda *args: True),
            _user_memory_category=lambda _: "other"))
        self.star = NS(star_cls=self.plugin, activated=True)
        self.native = NS(get_all_stars=lambda: [self.star]); self.plugin.context = self.native
        self.registry = ExternalMemoryProviderRegistry(self.native); self.addCleanup(self.registry.close)
        self.linkage = CompanionMemoryLinkage(self.plugin)
        self.assertTrue(self.linkage.register()); self.addCleanup(self.linkage.unregister)
        self.entry = self.registry.select("read")
        for item in [record("a"), record("b"), record("c"), record("b", identifier="old-b", at=BEFORE),
                     record("b", identifier="other-persona", persona="not-persona")]:
            await self.store.insert_memory(item)

    def configure(self, enabled=True, history="since_enabled"):
        return self.links.configure(self.contexts["a"], [self.contexts["a"], self.contexts["b"]],
            persona_id="persona", expected_revision=self.links.read()["revision"], share_context=False,
            operation_key="save-" + str(self.links.read()["revision"]), operator_id="admin", at=self.now,
            memory={"enabled": enabled, "history": history,
                    "confirmation": HISTORY_CONFIRMATION if history == "all" else CONFIRMATION})

    def issue(self, name="a", purpose="recall"):
        context = self.contexts[name]
        request = {"schema": "companion.external-memory.v1", "source_plugin": "astrbot_plugin_private_companion",
            "purpose": purpose, "context": {"scope": member_for(context)}, "limit": 20, "max_chars": 20000}
        return self.registry.issue_memory_read(self.entry, request, lambda: read_scope(self.app, context, purpose))

    async def read(self, name="a"):
        return await self.registry.invoke(self.entry, "read", self.issue(name))

    async def test_default_off_keeps_native_user_memory_separate(self):
        result = await self.read()
        self.assertEqual({"memory-a"}, {i["id"] for i in result["items"]})

    async def test_bidirectional_recall_excludes_unlinked_and_different_persona(self):
        self.configure()
        a = await self.read("a"); b = await self.read("b")
        self.assertEqual({"memory-a", "memory-b"}, {i["id"] for i in a["items"]})
        self.assertEqual({"memory-a", "memory-b", "old-b"}, {i["id"] for i in b["items"]})
        self.assertEqual({"memory-c"}, {i["id"] for i in (await self.read("c"))["items"]})

    async def test_history_requires_explicit_scope_and_preserves_provenance(self):
        self.configure(history="all")
        result = await self.read()
        self.assertEqual({"memory-a", "memory-b", "old-b"}, {i["id"] for i in result["items"]})
        peer = next(i for i in result["items"] if i["id"] == "memory-b")
        self.assertEqual(("b", "native-bot-b", "adapter-b:FriendMessage:b"),
            (peer["source_user_id"], peer["source_bot_id"], peer["source_session_id"]))

    async def test_summary_and_recall_have_identical_authorized_set(self):
        self.configure()
        for who in ("a", "b", "c"):
            recall = await self.read(who)
            summary = await self.registry.invoke(self.entry, "summary", self.issue(who, "summary"))
            self.assertTrue(summary["ok"])
            self.assertEqual(len(recall["items"]), summary["counts"]["total"])

    async def test_unlink_invalidates_old_lease_and_new_reads_are_local_only(self):
        self.configure(); old = self.issue()
        self.links.unlink(self.contexts["a"], expected_revision=self.links.read()["revision"],
            operation_key="unlink", operator_id="admin", at=self.now)
        self.assertEqual([], (await self.registry.invoke(self.entry, "read", old))["items"])
        self.assertEqual({"memory-a"}, {i["id"] for i in (await self.read())["items"]})

    async def test_disable_revokes_previously_prepared_reads(self):
        self.configure(); old = self.issue()
        self.configure(enabled=False)
        self.assertEqual([], (await self.registry.invoke(self.entry, "read", old))["items"])
        self.assertEqual({"memory-a"}, {i["id"] for i in (await self.read())["items"]})

    async def test_persona_or_permissions_change_fails_closed(self):
        self.configure(); old = self.issue()
        self.personas["b"] = "other"
        self.assertEqual([], (await self.registry.invoke(self.entry, "read", old))["items"])
        with self.assertRaises(TaskError): self.issue()
        self.personas["b"] = "persona"; self.blocked.add("b")
        with self.assertRaises(TaskError): self.issue()

    async def test_revoke_during_store_await_discards_result(self):
        self.configure(); request = self.issue()
        original = self.store.read_authorized_linked_memories
        async def raced(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.configure(enabled=False)
            return result
        self.store.read_authorized_linked_memories = raced
        self.assertEqual([], (await self.registry.invoke(self.entry, "read", request))["items"])

    async def test_forged_members_and_serialized_token_cannot_expand_scope(self):
        self.configure()
        forged = {"context": {"scope": member("c")}, "members": [member("a"), member("b"), member("c")],
                  "_memory_read_lease": "copied-from-json"}
        self.assertEqual([], (await self.linkage._read(forged))["items"])
        request = self.issue(); request["context"] = {"scope": member("c")}
        self.assertEqual([], (await self.linkage._read(request))["items"])

    async def test_read_and_summary_do_not_merge_reassign_or_copy_any_memory(self):
        self.configure(history="all")
        before = [dict(row) for row in self.store._conn.execute("SELECT * FROM memories ORDER BY id")]
        await self.read("a"); await self.read("b")
        await self.registry.invoke(self.entry, "summary", self.issue("a", "summary"))
        after = [dict(row) for row in self.store._conn.execute("SELECT * FROM memories ORDER BY id")]
        self.assertEqual(before, after)

    async def test_memory_acl_change_during_await_discards_stale_records(self):
        self.configure(); request = self.issue()
        original = self.store.read_authorized_linked_memories
        async def raced(*args, **kwargs):
            result = await original(*args, **kwargs)
            with self.store._lock:
                self.store._conn.execute("INSERT INTO memory_acl_rules(id,owner_scope,owner_id,reader_scope,reader_id,effect) "
                    "VALUES('deny-race','private','b','private','a','deny')")
                self.store._conn.commit()
            return result
        self.store.read_authorized_linked_memories = raced
        self.assertEqual([], (await self.registry.invoke(self.entry, "read", request))["items"])

    async def test_bridge_disabled_and_zero_budget_do_not_return_contents(self):
        self.configure(); request = self.issue(); request["max_chars"] = 0
        self.assertEqual([], (await self.registry.invoke(self.entry, "read", request))["items"])
        self.plugin.service.config.bool = lambda *args: False
        self.assertEqual([], (await self.registry.invoke(self.entry, "read", self.issue()))["items"])


    async def native_legacy_fixture(self):
        self.configure(history="all")
        self.app.private_account_link_memory_identity = lambda context: {
            "owner_bot_id": "wechat-login" if context.scope.native_scope_id == "b" else "native-bot-a",
            "platform_name": "wechat_native" if context.scope.native_scope_id == "b" else "aiocqhttp"}
        source = await self.store.add_timeline_event(event_type="user_message", scope="private",
            session_id=member("b")["session_id"], subject_id="b", object_id="b", content="SYNTHETIC_SOURCE",
            metadata={"owner_bot_id":"wechat-login", "persona_id":"persona", "platform":"wechat_native"},
            occurred_at=AFTER)
        item = record("b", identifier="native-legacy", persona="")
        item.memory_type="conversation_summary";item.owner_bot_id="self";item.subject.id=""
        item.metadata["source_event_ids"]=[source]
        await self.store.insert_memory(item)
        return source

    async def test_native_legacy_recall_has_verified_and_original_provenance(self):
        await self.native_legacy_fixture()
        result = await self.read("a")
        item = next(i for i in result["items"] if i["id"] == "native-legacy")
        self.assertEqual((item["source_user_id"],item["source_bot_id"],item["source_original_bot_id"]),
            ("b","wechat-login","self"))
        summary = await self.registry.invoke(self.entry,"summary",self.issue("a","summary"))
        self.assertEqual(len(result["items"]),summary["counts"]["total"])
        old=self.issue("a")
        self.app.private_account_link_memory_identity=lambda context: {
            "owner_bot_id":"new-login", "platform_name":"wechat_native"}
        self.assertEqual([], (await self.registry.invoke(self.entry,"read",old))["items"])

    async def test_source_persona_change_during_await_discards_result(self):
        source=await self.native_legacy_fixture()
        original=self.store.read_authorized_linked_memories
        async def raced(*args,**kwargs):
            result=await original(*args,**kwargs)
            self.store._conn.execute("UPDATE timeline SET metadata=json_set(metadata,'$.persona_id','other') WHERE id=?",(source,))
            self.store._conn.commit()
            return result
        self.store.read_authorized_linked_memories=raced
        self.assertEqual([], (await self.read("a"))["items"])
