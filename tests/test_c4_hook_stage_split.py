"""C4：钩子阶段计时要能拆出 capture.incoming 与注入内部各阶段。

排障时原先只能看到 ``decorate`` 把采集写入一并吞掉、``inject`` 把整段注入吞掉，
无法判断时间花在身份解析、采集落库、检索还是编排上。这些用例钉住拆分后的
可观测事实，并保证既有输出格式（``name=Nms`` 以空格分隔）不变。
"""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import service as service_module
from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import (
    MemoryCompanionService,
    _HookStageTimer,
)


class StageTimerFormatTests(unittest.TestCase):
    def test_summary_format_is_unchanged(self) -> None:
        timer = _HookStageTimer(True)
        timer.record_duration("identity", 2_000_000)
        timer.record_duration("capture_incoming", 5_000_000)

        self.assertEqual("identity=2ms capture_incoming=5ms", timer.summary())

    def test_disabled_timer_records_nothing_new(self) -> None:
        timer = _HookStageTimer(False)
        timer.mark("capture_incoming")
        timer.record_duration("capture_incoming", 9_000_000)

        self.assertEqual("no_stages", timer.summary())
        self.assertEqual(0, timer.total_ms())

    def test_timer_can_record_many_stages_without_collision(self) -> None:
        timer = _HookStageTimer(True)
        for name in ("identity", "capture_incoming", "decorate", "inject"):
            timer.mark(name)

        recorded = [name for name, _ms in timer._marks]
        self.assertEqual(["identity", "capture_incoming", "decorate", "inject"], recorded)


class HookStageSplitTests(unittest.IsolatedAsyncioTestCase):
    def make_service(
        self, config: dict, *, capture: bool, mock_emit: bool = True
    ) -> MemoryCompanionService:
        service = object.__new__(MemoryCompanionService)
        service.config = _ConfigView(config)
        service._hook_stage_timer = None
        service._last_retrieval_path_info = {}
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_id="m1",
            message_text="你还记得我上次说的口味吗",
        )
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        service.capture = None
        service._ensure_lifecycle_maintenance_dispatcher = Mock()
        service._ensure_wal_checkpoint_loop = Mock()
        service._ensure_acl_projection_reconcile_loop = Mock()
        service._mark_memory_companion_injection_state = Mock()
        service._sanitize_session_context_message_text = Mock()
        service._apply_companion_relationship_projection = Mock()
        service._apply_companion_expression_decision = Mock()
        service._absorb_relation_hints = AsyncMock()
        service._ensure_reconstruction_turn_token = Mock()
        service._apply_private_companion_preferred_address = Mock()
        service._private_companion_internal_generation_event = Mock(return_value=False)
        service._apply_remember_tool_contract = Mock()
        service._apply_core_memory_tool_contract = Mock()
        service._scope_feature_enabled = Mock(return_value=False)
        service._reply_chain_for_event = AsyncMock(return_value=None)
        service._apply_user_reaction_feedback = AsyncMock()
        service._update_address_evolution = Mock()
        service.inject_memories = AsyncMock()
        service._apply_reconstruction_contract = Mock()
        if mock_emit:
            service._emit_hook_stage_timing = Mock()

        if capture:
            service.capture = SimpleNamespace(
                incoming=AsyncMock(
                    return_value={
                        "status": "committed",
                        "source_state": "current",
                        "source_ref": "timeline:tl_c4",
                        "source_version": "v1",
                    }
                )
            )
        return service

    @staticmethod
    def request() -> SimpleNamespace:
        return SimpleNamespace(
            system_prompt="原始系统提示", prompt="", contexts=[], extra_user_content_parts=[]
        )

    async def test_capture_incoming_is_measured_separately_from_decorate(self) -> None:
        service = self.make_service(
            {"memory_injection": {"debug_stage_timing_enabled": True}}, capture=True
        )

        await service.handle_llm_request(SimpleNamespace(), self.request())

        service._emit_hook_stage_timing.assert_called_once()
        timer = service._emit_hook_stage_timing.call_args.args[0]
        names = [name for name, _ms in timer._marks]

        self.assertIn("capture_incoming", names)
        # Ordering: capture runs after identity and before decorate.
        self.assertLess(names.index("identity"), names.index("capture_incoming"))
        self.assertLess(names.index("capture_incoming"), names.index("decorate"))
        self.assertIn("reply_chain", names)
        self.assertIn("feedback", names)
        self.assertIn("inject", names)

    async def test_capture_stage_is_skipped_when_no_capture_runtime(self) -> None:
        """Without a capture runtime nothing ran, so nothing may be reported."""
        service = self.make_service(
            {"memory_injection": {"debug_stage_timing_enabled": True}}, capture=False
        )

        await service.handle_llm_request(SimpleNamespace(), self.request())

        timer = service._emit_hook_stage_timing.call_args.args[0]
        names = [name for name, _ms in timer._marks]
        self.assertNotIn("capture_incoming", names)
        self.assertIn("identity", names)

    async def test_timing_is_not_emitted_when_the_flag_is_off(self) -> None:
        service = self.make_service(
            {"memory_injection": {"debug_stage_timing_enabled": False}}, capture=True
        )

        await service.handle_llm_request(SimpleNamespace(), self.request())

        # _emit_hook_stage_timing stays callable but the timer recorded nothing.
        timer = service._emit_hook_stage_timing.call_args.args[0]
        self.assertFalse(timer.enabled)
        self.assertEqual("no_stages", timer.summary())

    @staticmethod
    def _format_timing_log(call) -> str:
        fmt, *args = call.args
        return fmt % tuple(args)

    async def test_second_turn_skipping_retrieval_does_not_leak_previous_retrieval_info(self) -> None:
        service = self.make_service(
            {"memory_injection": {"debug_stage_timing_enabled": True}},
            capture=False,
            mock_emit=False,
        )
        turn = 0

        async def inject_side_effect(*_args, **_kwargs) -> None:
            nonlocal turn
            turn += 1
            if turn == 1:
                service._last_retrieval_path_info = {
                    "path": "fts_vector",
                    "mode": "auto",
                    "candidate_count": 12,
                }
            # Turn 2 skips retrieval and leaves _last_retrieval_path_info untouched.

        service.inject_memories = AsyncMock(side_effect=inject_side_effect)

        with patch.object(service_module.logger, "info") as info_mock:
            await service.handle_llm_request(SimpleNamespace(), self.request())
            await service.handle_llm_request(SimpleNamespace(), self.request())

        self.assertEqual(2, info_mock.call_count)
        first_log = self._format_timing_log(info_mock.call_args_list[0])
        second_log = self._format_timing_log(info_mock.call_args_list[1])

        self.assertIn('"path":"fts_vector"', first_log)
        self.assertIsNone(service._last_retrieval_path_info)
        self.assertTrue(second_log.endswith(" | retrieval={}"))
        self.assertNotIn("fts_vector", second_log)
        self.assertNotIn("candidate_count", second_log)

    async def test_second_turn_command_skip_does_not_leak_previous_retrieval_info(self) -> None:
        service = self.make_service(
            {"memory_injection": {"debug_stage_timing_enabled": True}},
            capture=False,
            mock_emit=False,
        )
        command_ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_id="m2",
            message_text="/help",
        )
        normal_ctx = await service.identity.resolve_event_context(SimpleNamespace())
        service.identity.resolve_event_context = AsyncMock(side_effect=[normal_ctx, command_ctx])

        async def inject_round_one(*_args, **_kwargs) -> None:
            service._last_retrieval_path_info = {
                "path": "fts_vector",
                "mode": "auto",
                "candidate_count": 9,
            }

        service.inject_memories = AsyncMock(side_effect=inject_round_one)

        with patch.object(service_module.logger, "info") as info_mock:
            await service.handle_llm_request(SimpleNamespace(), self.request())
            await service.handle_llm_request(SimpleNamespace(), self.request())

        self.assertEqual(2, info_mock.call_count)
        second_log = self._format_timing_log(info_mock.call_args_list[1])
        self.assertIn("note=command_skip", second_log)
        self.assertTrue(second_log.endswith(" | retrieval={}"))
        self.assertNotIn("fts_vector", second_log)

    async def test_second_turn_cancelled_by_budget_does_not_leak_previous_retrieval_info(self) -> None:
        service = self.make_service(
            {"memory_injection": {"debug_stage_timing_enabled": True}},
            capture=False,
            mock_emit=False,
        )
        turn = 0

        async def inject_side_effect(*_args, **_kwargs) -> None:
            nonlocal turn
            turn += 1
            if turn == 1:
                service._last_retrieval_path_info = {
                    "path": "fts_vector",
                    "mode": "auto",
                    "candidate_count": 7,
                }
                return
            raise asyncio.CancelledError

        service.inject_memories = AsyncMock(side_effect=inject_side_effect)

        with patch.object(service_module.logger, "info") as info_mock:
            await service.handle_llm_request(SimpleNamespace(), self.request())
            with self.assertRaises(asyncio.CancelledError):
                await service.handle_llm_request(SimpleNamespace(), self.request())

        self.assertEqual(2, info_mock.call_count)
        second_log = self._format_timing_log(info_mock.call_args_list[1])
        self.assertIn("note=cancelled:memory_injection", second_log)
        self.assertTrue(second_log.endswith(" | retrieval={}"))
        self.assertNotIn("fts_vector", second_log)
        self.assertNotIn("candidate_count", second_log)


class _ConfigView:
    """Minimal config surface used by ``handle_llm_request``."""

    def __init__(self, raw: dict) -> None:
        self._raw = raw

    def _get(self, key: str, default=None):
        current = self._raw
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def bool(self, key: str, default: bool = False) -> bool:
        value = self._get(key, default)
        return bool(value)

    def int(self, key: str, default: int = 0) -> int:
        try:
            return int(self._get(key, default))
        except (TypeError, ValueError):
            return default

    def float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self._get(key, default))
        except (TypeError, ValueError):
            return default

    def get(self, key: str, default=None):
        return self._get(key, default)


if __name__ == "__main__":
    unittest.main()
