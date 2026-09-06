from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class RememberToolContractTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config=config or {"retrieval": {"embedding_enabled": False}},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def private_context() -> SessionContext:
        return SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="测试用户",
            bot_id="b1",
            message_id="m1",
            message_text="请记住我喜欢街角那家面馆",
        )

    async def test_success_is_reported_only_after_memory_is_persisted(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))

        result = await service.tool_remember(ctx, "用户喜欢街角那家面馆", note_type="preference")

        self.assertIs(result.get("ok"), True)
        memory = await service.store.get_memory(result["memory_id"])
        self.assertIsNotNone(memory)
        self.assertEqual("用户喜欢街角那家面馆", memory.content)
        self.assertEqual("private_pair", memory.visibility)

    async def test_storage_error_returns_structured_failure_instead_of_success(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        service.store.insert_memory = AsyncMock(side_effect=RuntimeError("database unavailable"))

        result = await service.tool_remember(ctx, "用户喜欢街角那家面馆")

        self.assertEqual({"ok": False, "error": "memory write failed"}, result)

    async def test_embedding_schedule_error_does_not_hide_a_committed_write(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        service._schedule_memory_embedding = Mock(side_effect=RuntimeError("scheduler unavailable"))

        result = await service.tool_remember(ctx, "用户喜欢街角那家面馆")

        self.assertIs(result.get("ok"), True)
        self.assertIsNotNone(await service.store.get_memory(result["memory_id"]))

    async def test_empty_content_is_not_reported_as_saved(self) -> None:
        service = self.make_service()
        resolver = AsyncMock()
        service.identity = SimpleNamespace(resolve_event_context=resolver)

        result = await service.tool_remember(SimpleNamespace(), "  ")

        self.assertEqual({"ok": False, "error": "empty content"}, result)
        resolver.assert_not_awaited()

    async def test_non_persistent_proposal_is_skipped_without_storage(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        service.store.insert_memory = AsyncMock()

        result = await service.tool_remember(
            ctx,
            "这只是当前会话的想法",
            proposal={"requested_persistence": False},
        )

        self.assertEqual({
            "ok": False,
            "state": "skipped",
            "reason": "persistence not requested",
            "review_status": "none",
        }, result)
        service.store.insert_memory.assert_not_awaited()

    def test_confirmation_contract_is_system_level_and_idempotent(self) -> None:
        service = self.make_service()
        req = SimpleNamespace(system_prompt="原始系统提示")

        service._apply_remember_tool_contract(req)
        service._apply_remember_tool_contract(req)

        self.assertTrue(req.system_prompt.startswith("原始系统提示"))
        self.assertEqual(1, req.system_prompt.count("<MemoryCompanion-Remember-Tool-Contract>"))
        self.assertIn("ok=true", req.system_prompt)
        self.assertIn("没有调用、返回 ok=false 或调用异常", req.system_prompt)

    async def test_request_entry_keeps_the_contract_when_memory_features_are_disabled(self) -> None:
        service = self.make_service(
            {
                "memory_capture": {"enabled": False},
                "memory_injection": {"enabled": False},
                "memory_tools": {"enable_remember_tool": False},
                "retrieval": {"embedding_enabled": False},
            }
        )
        ctx = self.private_context()
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        service.note_identity = AsyncMock()
        service._reply_chain_for_event = AsyncMock(return_value=None)
        service._apply_user_reaction_feedback = AsyncMock()
        service._update_address_evolution = Mock()
        service.inject_memories = AsyncMock()
        req = SimpleNamespace(system_prompt="原始系统提示", prompt="", contexts=[], extra_user_content_parts=[])

        await service.handle_llm_request(SimpleNamespace(), req)

        self.assertIn("<MemoryCompanion-Remember-Tool-Contract>", req.system_prompt)
        self.assertIn("只有该工具本轮返回的 JSON 明确包含 ok=true", req.system_prompt)

    def test_llm_tool_description_exposes_the_same_success_contract(self) -> None:
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("只有返回 JSON 中 ok=true 才能确认写入成功", main_source)
        self.assertIn("未调用、ok=false 或调用异常时", main_source)


if __name__ == "__main__":
    unittest.main()
