from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.audit import MemoryAuditManager
from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer


class _Response:
    def __init__(self, payload: dict):
        self.completion_text = json.dumps(payload, ensure_ascii=False)


class _Provider:
    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    async def text_chat(self, **kwargs):
        self.prompts.append(str(kwargs.get("prompt") or ""))
        return _Response(self.payload)


class _Service:
    def __init__(self, root: Path, provider: _Provider):
        self.config = ConfigView(
            {
                "maintenance_audit": {
                    "enabled": True,
                    "max_candidates": 20,
                    "max_items_per_preview": 8,
                    "provider_timeout_seconds": 5,
                    "preview_expire_hours": 24,
                },
                "retrieval": {"embedding_enabled": False},
            }
        )
        self.store = MemoryStore(root / "memory.db")
        self.store.initialize()
        self.provider = provider
        self._retrieval_result_cache = {"cached": {}}
        self.embeddings: list[str] = []
        self.audit = MemoryAuditManager(self, root / "audits")

    async def _summary_provider_attempts(self, _ctx):
        return [{"provider": self.provider, "provider_id": "test-provider"}]

    @staticmethod
    def _provider_runtime_id(_provider):
        return "test-provider"

    @staticmethod
    def _record_token_usage(**_kwargs):
        return None

    def _schedule_memory_embedding(self, memory_id, _record):
        self.embeddings.append(memory_id)


class MemoryAuditTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, proposal: dict) -> tuple[_Service, Path]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        service = _Service(root, _Provider(proposal))
        self.addCleanup(service.store.close)
        return service, root

    async def seed(self, service: _Service, *, content: str = "旧摘要把饮品写错了。") -> tuple[str, str]:
        event_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:u1",
            scope="private",
            subject_id="u1",
            object_id="u1",
            content="小王明确说自己喜欢无糖拿铁。",
            metadata={"sender_name": "小王"},
        )
        memory_id = await service.store.insert_memory(
            MemoryRecord(
                id="summary-1",
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef.bot_self(),
                scope="private",
                session_id="qq:FriendMessage:u1",
                visibility="private_pair",
                lifecycle="stable_memory",
                content=content,
                evidence="阶段摘要",
                confidence=0.72,
                importance=0.7,
                metadata={
                    "key_facts": ["小王喜欢无糖拿铁"],
                    "key_facts_with_refs": [
                        {"fact": "小王喜欢无糖拿铁", "refs": [event_id]}
                    ],
                },
            )
        )
        return memory_id, event_id

    def test_structured_fact_requires_existing_supporting_reference(self) -> None:
        summarizer = MemorySummarizer()
        rows = [{"id": "event-1", "content": "小王喜欢无糖拿铁。"}]
        traced, warnings, errors = summarizer._normalize_key_facts_with_validation(
            [
                {"fact": "小王喜欢无糖拿铁", "refs": ["event-1"]},
                {"fact": "小王喜欢红茶", "refs": ["missing"]},
                {"fact": "小王住在上海", "refs": ["event-1"]},
            ],
            rows,
        )
        self.assertEqual(["小王喜欢无糖拿铁"], [item["fact"] for item in traced])
        self.assertEqual(
            [{
                "fact": "小王喜欢无糖拿铁",
                "refs": ["event-1"],
                "evidence": [{"ref": "event-1", "quote": "小王喜欢无糖拿铁"}],
            }],
            traced,
        )
        self.assertTrue(any("event_id" in error for error in errors))
        self.assertTrue(any("不受原文支持" in warning for warning in warnings))

    def test_legacy_string_fact_is_attributed_instead_of_dropped(self) -> None:
        summarizer = MemorySummarizer()
        traced, warnings, errors = summarizer._normalize_key_facts_with_validation(
            ["小王喜欢无糖拿铁"],
            [{"id": "event-1", "content": "小王喜欢无糖拿铁。"}],
        )
        self.assertEqual([{"fact": "小王喜欢无糖拿铁", "refs": ["event-1"], "evidence": [{"ref": "event-1", "quote": "小王喜欢无糖拿铁"}]}], traced)
        self.assertEqual([], errors)

    async def test_preview_does_not_mutate_memory(self) -> None:
        proposal = {
            "items": [
                {
                    "memory_id": "summary-1",
                    "action": "replace",
                    "content": "小王明确表示自己喜欢无糖拿铁。",
                    "reason": "原摘要把饮品写错了",
                    "refs": [],
                }
            ]
        }
        service, _root = self.make_service(proposal)
        memory_id, event_id = await self.seed(service)
        service.provider.payload["items"][0]["refs"] = [event_id]
        before = await service.store.get_memory(memory_id)

        batch = await service.audit.preview(SessionContext(session_id="qq:FriendMessage:u1"))
        after = await service.store.get_memory(memory_id)

        self.assertEqual("preview", batch["status"])
        self.assertEqual(1, len(batch["items"]))
        self.assertEqual(before.content, after.content)
        self.assertEqual(before.updated_at, after.updated_at)
        self.assertTrue((service.audit.root / f"{batch['batch_id']}.json").exists())

    async def test_preview_routes_private_and_group_candidates_to_separate_models(self) -> None:
        service, _root = self.make_service({"items": []})
        await self.seed(service)
        group_event_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:GroupMessage:g1",
            scope="group",
            subject_id="u2",
            object_id="g1",
            content="group fact",
        )
        await service.store.insert_memory(
            MemoryRecord(
                id="summary-group",
                memory_type="conversation_summary",
                subject=EntityRef.bot_self(),
                object=EntityRef(kind="group", id="g1"),
                scope="group",
                session_id="qq:GroupMessage:g1",
                group_id="g1",
                visibility="group_public",
                lifecycle="stable_memory",
                content="group fact",
                evidence="group fact",
                metadata={
                    "key_facts_with_refs": [
                        {"fact": "group fact", "refs": [group_event_id]}
                    ],
                },
            )
        )
        private_provider = _Provider({"items": []})
        group_provider = _Provider({"items": []})
        routed_scopes: list[str] = []

        async def scoped_attempts(ctx):
            routed_scopes.append(ctx.scope)
            provider = group_provider if ctx.scope == "group" else private_provider
            return [{"provider": provider, "provider_id": f"{ctx.scope}-provider"}]

        service._summary_provider_attempts = scoped_attempts
        batch = await service.audit.preview(SessionContext())

        self.assertEqual({"private", "group"}, set(routed_scopes))
        self.assertEqual(1, len(private_provider.prompts))
        self.assertEqual(1, len(group_provider.prompts))
        self.assertIn("summary-1", private_provider.prompts[0])
        self.assertNotIn("summary-group", private_provider.prompts[0])
        self.assertIn("summary-group", group_provider.prompts[0])
        self.assertNotIn("summary-1", group_provider.prompts[0])
        self.assertEqual(
            {("private", "private-provider"), ("group", "group-provider")},
            {(item["scope"], item["provider_id"]) for item in batch["provider_ids"]},
        )

    async def test_apply_requires_confirmation_and_rollback_restores_content(self) -> None:
        proposal = {
            "items": [
                {
                    "memory_id": "summary-1",
                    "action": "replace",
                    "content": "小王明确表示自己喜欢无糖拿铁。",
                    "reason": "修正旧摘要",
                    "refs": [],
                }
            ]
        }
        service, _root = self.make_service(proposal)
        memory_id, event_id = await self.seed(service)
        service.provider.payload["items"][0]["refs"] = [event_id]
        batch = await service.audit.preview(SessionContext())

        with self.assertRaisesRegex(ValueError, "确认"):
            await service.audit.apply(batch["batch_id"], "")
        applied = await service.audit.apply(batch["batch_id"], "确认")
        changed = await service.store.get_memory(memory_id)
        self.assertEqual("applied", applied["status"])
        self.assertEqual("小王明确表示自己喜欢无糖拿铁。", changed.content)
        self.assertTrue(Path(applied["backup_path"]).exists())

        rolled_back = await service.audit.rollback(batch["batch_id"], "确认")
        restored = await service.store.get_memory(memory_id)
        self.assertEqual("rolled_back", rolled_back["status"])
        self.assertEqual("旧摘要把饮品写错了。", restored.content)

    async def test_delete_proposal_archives_and_stale_preview_is_skipped(self) -> None:
        proposal = {
            "items": [
                {
                    "memory_id": "summary-1",
                    "action": "delete",
                    "reason": "正文与引用事件无关且无法可靠修复",
                    "refs": [],
                }
            ]
        }
        service, _root = self.make_service(proposal)
        memory_id, event_id = await self.seed(service, content="完全无关的天气摘要。")
        service.provider.payload["items"][0]["refs"] = [event_id]
        batch = await service.audit.preview(SessionContext())
        self.assertEqual("archive", batch["items"][0]["action"])

        await service.store.update_memory_payload(memory_id, content="管理员刚刚手工修改的内容")
        result = await service.audit.apply(batch["batch_id"], "确认")
        current = await service.store.get_memory(memory_id)
        self.assertEqual("partial", result["status"])
        self.assertEqual("stale", result["applied_results"][0]["status"])
        self.assertEqual("stable_memory", current.lifecycle)

    async def test_archive_never_hard_deletes(self) -> None:
        proposal = {
            "items": [
                {
                    "memory_id": "summary-1",
                    "action": "archive",
                    "reason": "正文与引用事件无关且无法可靠修复",
                    "refs": [],
                }
            ]
        }
        service, _root = self.make_service(proposal)
        memory_id, event_id = await self.seed(service, content="完全无关的天气摘要。")
        service.provider.payload["items"][0]["refs"] = [event_id]
        batch = await service.audit.preview(SessionContext())
        await service.audit.apply(batch["batch_id"], "确认")

        current = await service.store.get_memory(memory_id)
        self.assertIsNotNone(current)
        self.assertEqual("archived", current.lifecycle)

    def test_config_commands_and_routes_are_registered(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertIn("maintenance_audit", schema)
        self.assertFalse(schema["maintenance_audit"]["items"]["enabled"]["default"])
        self.assertIn('@mcomp.command("audit"', (ROOT / "main.py").read_text(encoding="utf-8"))
        page = (ROOT / "page_api.py").read_text(encoding="utf-8")
        self.assertIn('"/maintenance/audit/preview"', page)
        self.assertIn('"/maintenance/audit/rollback"', page)
    def test_legacy_string_fact_remains_untraced(self) -> None:
        summarizer = MemorySummarizer()
        facts, traced = summarizer._normalize_key_facts(
            ["小王喜欢无糖拿铁"],
            [{"id": "event-1", "content": "小王喜欢无糖拿铁。"}],
        )
        self.assertEqual(["小王喜欢无糖拿铁"], facts)
        self.assertEqual([], traced)


if __name__ == "__main__":
    unittest.main()
