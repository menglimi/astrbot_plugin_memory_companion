from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.memory_revision import memory_ref
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SearchResult,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.service import (
    MemoryCompanionService,
    analyze_turn_signal,
    parse_time_intent,
)


class N9InjectionIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={
                "retrieval": {"mode": "basic", "embedding_enabled": False},
                "visibility": {"enable_acl_rules": True},
                "memory_injection": {"max_chars": 3200, "enable_injection_logs": False},
            },
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def private_context(message_text: str = "还记得之前那次约定吗？") -> SessionContext:
        return SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="小王",
            bot_id="bot-1",
            message_id="msg-n9-1",
            message_text=message_text,
        )

    @staticmethod
    def scar_memory(memory_id: str, metadata: dict) -> MemoryRecord:
        return MemoryRecord(
            id=memory_id,
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="小王"),
            object=EntityRef.bot_self("bot-1"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            platform="qq",
            owner_bot_id="bot-1",
            visibility="private_pair",
            lifecycle="stable_memory",
            content="之前那场深夜争吵让双方都很在意，约定以后要轻声沟通。",
            evidence="用户：那晚真的很受伤。",
            confidence=0.92,
            importance=0.88,
            message_id="src-scar-1",
            metadata=metadata,
        )

    async def test_scar_scene_gate_preserves_memory_ref_for_existing_policy_and_publishes(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        record = self.scar_memory(
            "scar-with-policy",
            {"scar_weight": 0.78, "mention_policy": "soft_echo"},
        )
        await service.store.insert_memory(record)
        db_record = await service.store.get_memory(record.id)
        self.assertIsNotNone(db_record)
        assert db_record is not None

        slot_map = {"stable_memory": [SearchResult(memory=deepcopy(db_record), score=0.95, reason="mention")]}
        gated_slots = service._apply_scar_scene_gate(
            ctx,
            slot_map,
            companion_bot_energy=25,
            time_of_day="dawn",
        )
        # Re-applying the gate must remain idempotent and keep the original persisted policy.
        gated_slots = service._apply_scar_scene_gate(
            ctx,
            gated_slots,
            companion_bot_energy=25,
            time_of_day="late_night",
        )
        gated_record = gated_slots["stable_memory"][0].memory
        self.assertEqual("tone_only", gated_record.metadata["mention_policy"])
        self.assertTrue(gated_record.metadata["_scene_gated"])
        self.assertEqual("soft_echo", gated_record.metadata["_persisted_mention_policy"])
        self.assertEqual(memory_ref(db_record), memory_ref(gated_record))

        injection = service.injection.compose(
            ctx,
            [gated_slots["stable_memory"][0]],
            max_chars=3200,
            slot_sections=[("stable_memory", gated_slots["stable_memory"])],
        )
        valid, _revision = await service._validate_reply_memory_refs(ctx, injection.memory_refs, gated_slots)
        self.assertTrue(valid)

        req = SimpleNamespace(prompt="用户消息", contexts=[], extra_user_content_parts=[])
        event = SimpleNamespace()
        published = await service._publish_reply_memory_context(
            ctx,
            req,
            event=event,
            injection=injection,
            slot_map=gated_slots,
            strategy_id="existing.search_context_slots",
        )
        self.assertTrue(published)
        self.assertTrue(req.memory_companion_injection_state["injected"])
        self.assertEqual([record.id], req.memory_companion_injection_state["injected_memory_ids"])
        self.assertEqual("", req.memory_companion_injection_state["reason_code"])

    async def test_scar_scene_gate_preserves_memory_ref_when_mention_policy_was_absent(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        record = self.scar_memory("scar-without-policy", {"scar_weight": 0.85})
        await service.store.insert_memory(record)
        db_record = await service.store.get_memory(record.id)
        self.assertIsNotNone(db_record)
        assert db_record is not None
        self.assertNotIn("mention_policy", db_record.metadata)

        slot_map = {"stable_memory": [SearchResult(memory=deepcopy(db_record), score=0.95, reason="mention")]}
        gated_slots = service._apply_scar_scene_gate(
            ctx,
            slot_map,
            companion_bot_energy=80,
            time_of_day="late_night",
        )
        gated_record = gated_slots["stable_memory"][0].memory
        self.assertEqual("tone_only", gated_record.metadata["mention_policy"])
        self.assertTrue(gated_record.metadata["_scene_gated"])
        self.assertTrue(gated_record.metadata["_persisted_mention_policy_missing"])
        self.assertEqual(memory_ref(db_record), memory_ref(gated_record))

        injection = service.injection.compose(
            ctx,
            [gated_slots["stable_memory"][0]],
            max_chars=3200,
            slot_sections=[("stable_memory", gated_slots["stable_memory"])],
        )
        valid, _revision = await service._validate_reply_memory_refs(ctx, injection.memory_refs, gated_slots)
        self.assertTrue(valid)

        req = SimpleNamespace(prompt="用户消息", contexts=[], extra_user_content_parts=[])
        event = SimpleNamespace()
        published = await service._publish_reply_memory_context(
            ctx,
            req,
            event=event,
            injection=injection,
            slot_map=gated_slots,
            strategy_id="existing.search_context_slots",
        )
        self.assertTrue(published)
        self.assertTrue(req.memory_companion_injection_state["injected"])
        self.assertEqual([record.id], req.memory_companion_injection_state["injected_memory_ids"])
        self.assertNotIn("_scene_gated", (await service.store.get_memory(record.id)).metadata)

    async def test_concurrent_mention_policy_db_change_still_invalidates_reply_refs(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        record = self.scar_memory(
            "scar-concurrent-edit",
            {"scar_weight": 0.78, "mention_policy": "soft_echo"},
        )
        await service.store.insert_memory(record)
        db_record = await service.store.get_memory(record.id)
        assert db_record is not None

        gated_slots = service._apply_scar_scene_gate(
            ctx,
            {"stable_memory": [SearchResult(memory=deepcopy(db_record), score=0.95, reason="mention")]},
            companion_bot_energy=20,
            time_of_day="dawn",
        )
        injection = service.injection.compose(
            ctx,
            [gated_slots["stable_memory"][0]],
            max_chars=3200,
            slot_sections=[("stable_memory", gated_slots["stable_memory"])],
        )
        valid_before, _ = await service._validate_reply_memory_refs(ctx, injection.memory_refs, gated_slots)
        self.assertTrue(valid_before)

        # Simulate a concurrent persistent write changing mention_policy in the store.
        updated_metadata = dict(db_record.metadata)
        updated_metadata["mention_policy"] = "avoid_unless_asked"
        self.assertTrue(await service.store.update_memory_payload(record.id, metadata=updated_metadata))

        valid, _revision = await service._validate_reply_memory_refs(ctx, injection.memory_refs, gated_slots)
        self.assertFalse(valid)

        req = SimpleNamespace(prompt="用户消息", contexts=[], extra_user_content_parts=[])
        event = SimpleNamespace()
        published = await service._publish_reply_memory_context(
            ctx,
            req,
            event=event,
            injection=injection,
            slot_map=gated_slots,
            strategy_id="existing.search_context_slots",
        )
        self.assertFalse(published)
        self.assertFalse(req.memory_companion_injection_state["injected"])
        self.assertEqual("memory_changed_or_unavailable", req.memory_companion_injection_state["reason_code"])

    async def test_route_does_not_suppress_explicit_long_term_recall_with_recent_prefix(self) -> None:
        service = self.make_service()
        recall_queries = (
            "我刚才突然想起之前私聊里聊过的事，还记得吗",
            "我刚才突然想起之前在私聊里说过的猫猫咖啡馆",
            "刚刚突然想到以前那次旅行的约定，记不记得？",
            "刚才想起当年一起听过的那首歌",
            "刚刚聊着聊着想起当时你说过的话",
            "刚才突然想起来往事，还记得吗",
        )
        for query in recall_queries:
            ctx = self.private_context(message_text=query)
            decision = service._memory_route_decision(
                ctx,
                analyze_turn_signal(query),
                parse_time_intent(query),
            )
            self.assertEqual("memory_retrieval", decision.layer, query)
            self.assertFalse(decision.suppress_long_memory, query)
            self.assertNotEqual("recent_context_request", decision.suppress_reason, query)

        seeded = self.scar_memory("long-term-private-chat", {"scar_weight": 0.2})
        seeded.content = "之前在私聊里聊过猫猫咖啡馆和周末计划。"
        await service.store.insert_memory(seeded)

        ctx = self.private_context(message_text="我刚才突然想起之前私聊里聊过的事，还记得吗")
        req = SimpleNamespace(prompt=ctx.message_text, contexts=[], extra_user_content_parts=[])
        event = SimpleNamespace()
        with patch.object(service, "search_context_slots", wraps=service.search_context_slots) as search_mock:
            await service.inject_memories(ctx, req, event=event)
        search_mock.assert_called_once()
        self.assertTrue(req.memory_companion_injection_state["injected"])
        self.assertIn(seeded.id, req.memory_companion_injection_state["injected_memory_ids"])

    async def test_pure_recent_context_followups_still_suppress_long_term_retrieval(self) -> None:
        service = self.make_service()
        seeded = self.scar_memory("long-term-should-skip", {"scar_weight": 0.2})
        seeded.content = "之前在私聊里聊过猫猫咖啡馆。"
        await service.store.insert_memory(seeded)

        recent_queries = (
            "刚才我们聊了什么",
            "刚刚上一轮说了啥",
            "刚才我说了什么",
            "刚刚聊到哪了",
        )
        for query in recent_queries:
            ctx = self.private_context(message_text=query)
            decision = service._memory_route_decision(
                ctx,
                analyze_turn_signal(query),
                parse_time_intent(query),
            )
            self.assertEqual("recent_context", decision.layer, query)
            self.assertTrue(decision.suppress_long_memory, query)
            self.assertEqual("recent_context_request", decision.suppress_reason, query)

            req = SimpleNamespace(prompt=query, contexts=[], extra_user_content_parts=[])
            event = SimpleNamespace()
            with patch.object(service, "search_context_slots", wraps=service.search_context_slots) as search_mock:
                await service.inject_memories(ctx, req, event=event)
            search_mock.assert_not_called()
            self.assertEqual([], req.memory_companion_injection_state["injected_memory_ids"], query)
            self.assertEqual([], req.memory_companion_injection_state["slots"], query)
            rendered = req.prompt + "\n" + "\n".join(part.text for part in req.extra_user_content_parts)
            self.assertNotIn("猫猫咖啡馆", rendered, query)


if __name__ == "__main__":
    unittest.main()
