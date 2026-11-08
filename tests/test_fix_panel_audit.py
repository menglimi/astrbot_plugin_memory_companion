# -*- coding: utf-8 -*-
"""P10：审计预览只把「截断 + 去标识」的片段送给模型。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.audit import MemoryAuditManager
from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.store import MemoryStore


LONG_TAIL = "尾部标记TAILMARK-9F3"
EMAIL = "user.real@example.com"
PHONE = "13800138000"
LONG_BODY = "小王说他最近换了工作，喜欢无糖拿铁。" * 60


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


class PromptProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = MemoryAuditManager.__new__(MemoryAuditManager)

    def test_redaction_removes_identifiers(self) -> None:
        text = self.manager._redacted_fragment(
            f"联系 {EMAIL} 或致电 {PHONE}，主页 https://example.com/u/1 @某人", 400
        )
        self.assertNotIn(EMAIL, text)
        self.assertNotIn(PHONE, text)
        self.assertNotIn("https://example.com/u/1", text)
        self.assertIn("<email>", text)
        self.assertIn("<number>", text)
        self.assertIn("<url>", text)

    def test_redaction_truncates_to_the_limit(self) -> None:
        text = self.manager._redacted_fragment("字" * 5000, 480)
        self.assertLessEqual(len(text), 481)
        self.assertTrue(text.endswith("…"))

    def test_projection_drops_trace_quotes_and_speaker_ids(self) -> None:
        record = MemoryRecord(
            id="summary-1",
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1"),
            object=EntityRef.bot_self(),
            content="正文" * 500,
            evidence="阶段摘要",
        )
        item = {
            "record": record,
            "traces": [
                {
                    "fact": "小王喜欢无糖拿铁",
                    "refs": ["event-1"],
                    "evidence": [{"ref": "event-1", "quote": "原始引文QUOTE-1"}],
                }
            ],
            "evidence": [
                {
                    "event_id": "event-1",
                    "event_type": "user_message",
                    "speaker_id": "u1-secret-speaker",
                    "occurred_at": "2026-01-01T00:00:00+00:00",
                    "content": "原文" * 500,
                }
            ],
        }
        projection = self.manager._prompt_projection(item)
        dumped = json.dumps(projection, ensure_ascii=False)
        self.assertNotIn("QUOTE-1", dumped)
        self.assertNotIn("u1-secret-speaker", dumped)
        self.assertEqual("truncated_and_deidentified", projection["redaction"])
        self.assertTrue(projection["content_truncated"])
        self.assertLessEqual(len(projection["content"]), 481)
        self.assertLessEqual(len(projection["evidence"][0]["content"]), 241)


class PreviewPromptPayloadTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, proposal: dict) -> tuple[_Service, Path]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        service = _Service(root, _Provider(proposal))
        self.addCleanup(service.store.close)
        return service, root

    async def seed(self, service: _Service) -> tuple[str, str]:
        event_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id="qq:FriendMessage:u1",
            scope="private",
            subject_id="u1",
            object_id="u1",
            content=f"联系人 {EMAIL} 电话 {PHONE}。{LONG_BODY} 事件尾部EVENTTAIL",
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
                content=f"联系人 {EMAIL} 电话 {PHONE}。{LONG_BODY} {LONG_TAIL}",
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

    async def test_model_payload_is_truncated_and_deidentified(self) -> None:
        service, _root = self.make_service({"items": []})
        await self.seed(service)
        await service.audit.preview(SessionContext(session_id="qq:FriendMessage:u1"))

        self.assertEqual(1, len(service.provider.prompts))
        prompt = service.provider.prompts[0]
        self.assertIn("summary-1", prompt)
        self.assertNotIn(LONG_TAIL, prompt)
        self.assertNotIn("事件尾部EVENTTAIL", prompt)
        self.assertNotIn(EMAIL, prompt)
        self.assertNotIn(PHONE, prompt)
        self.assertIn("<email>", prompt)
        self.assertIn("truncated_and_deidentified", prompt)

    async def test_full_text_stays_local_for_validation_and_apply(self) -> None:
        proposal = {
            "items": [
                {
                    "memory_id": "summary-1",
                    "action": "replace",
                    "content": "小王换了工作，仍然喜欢无糖拿铁。",
                    "reason": "旧摘要遗漏了新工作",
                    "refs": [],
                }
            ]
        }
        service, _root = self.make_service(proposal)
        memory_id, event_id = await self.seed(service)
        service.provider.payload["items"][0]["refs"] = [event_id]
        batch = await service.audit.preview(SessionContext())

        before = batch["items"][0]["before"]["content"]
        self.assertIn(LONG_TAIL, before)
        self.assertIn(EMAIL, before)
        applied = await service.audit.apply(batch["batch_id"], "确认")
        self.assertEqual("applied", applied["status"])
        changed = await service.store.get_memory(memory_id)
        self.assertEqual("小王换了工作，仍然喜欢无糖拿铁。", changed.content)


if __name__ == "__main__":
    unittest.main()
