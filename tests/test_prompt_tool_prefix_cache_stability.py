from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
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

from astrbot_plugin_memory_companion.core.classifier import MemoryClassifier
from astrbot_plugin_memory_companion.core.identity import looks_like_command
from astrbot_plugin_memory_companion.core.models import SessionContext, json_dumps
from astrbot_plugin_memory_companion.core.query_session import (
    bind_query_tool_schema,
    bind_source_query_v2_schema,
    offer_query_tool,
)
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class _FakeTool:
    def __init__(
        self,
        name: str,
        *,
        description: str = "tool",
        parameters: dict | None = None,
        handler: object | None = None,
        handler_module_path: str = "memory.test.main",
        active: bool = True,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = deepcopy(parameters) if parameters is not None else {}
        self.handler = handler
        self.handler_module_path = handler_module_path
        self.active = active


class _FakeToolSet:
    def __init__(self, tools: list[_FakeTool]) -> None:
        self.tools = list(tools)

    def names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    def get_tool(self, name: str) -> _FakeTool | None:
        return next((tool for tool in self.tools if tool.name == name), None)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tools_schema_hash(toolset: _FakeToolSet) -> str:
    payload = [
        {
            "name": tool.name,
            "active": bool(getattr(tool, "active", True)),
            "description": getattr(tool, "description", ""),
            "parameters": getattr(tool, "parameters", {}),
        }
        for tool in toolset.tools
    ]
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _build_full_toolset(*, include_remember: bool = True, include_core: bool = True) -> _FakeToolSet:
    path = "memory.test.main"
    tools: list[_FakeTool] = [
        _FakeTool(name="memory_companion_" + op, description=f"{op} tool", handler_module_path=path)
        for op in ("recall", "sources", "navigate", "events")
    ]
    wrapper = _FakeTool(
        name="memory_companion_query",
        description="raw bloated query wrapper",
        handler_module_path=path,
    )
    manager = SimpleNamespace(get_func=lambda name: wrapper if name == wrapper.name else None)
    assert bind_query_tool_schema(manager, path)
    # Confirm raw schema is the large multi-operation schema before projection.
    raw_ops = wrapper.parameters["properties"]["operation"]["enum"]
    assert len(raw_ops) > 1 and "status" in raw_ops
    assert len(json_dumps(wrapper.parameters)) > 1000
    tools.append(wrapper)
    if include_remember:
        tools.append(_FakeTool(name="memory_companion_remember", description="remember tool", handler_module_path=path))
    if include_core:
        tools.append(_FakeTool(name="memory_companion_core_memory", description="core memory tool", handler_module_path=path))
    return _FakeToolSet(tools)


class PromptAndToolPrefixCacheStabilityTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        merged = {
            "retrieval": {"embedding_enabled": False},
            "memory_injection": {"hook_request_budget_seconds": 0.15},
            "memory_capture": {"enabled": False},
        }
        if config:
            merged.update(config)
        service = MemoryCompanionService(
            context=None,
            config=merged,
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def make_event(
        text: str,
        *,
        scope: str = "group",
        group_id: str = "g100",
        user_id: str = "u200",
        bot_id: str = "b1",
        message_id: str = "msg-1",
    ) -> SimpleNamespace:
        session_id = f"qq:GroupMessage:{group_id}" if scope == "group" else f"qq:FriendMessage:{user_id}"
        return SimpleNamespace(
            unified_msg_origin=session_id,
            message_str=text,
            get_platform_name=lambda: "qq",
            get_group_id=lambda: group_id if scope == "group" else "",
            get_sender_id=lambda: user_id,
            get_sender_name=lambda: "测试群友",
            get_self_id=lambda: bot_id,
            get_message_str=lambda: text,
            message_obj=SimpleNamespace(message_id=message_id, message_str=text),
        )

    @staticmethod
    def make_request() -> SimpleNamespace:
        return SimpleNamespace(
            system_prompt="你是测试助手，请保持自然对话。",
            prompt="hello",
            contexts=[],
            extra_user_content_parts=[],
            func_tool=_build_full_toolset(),
        )

    def test_looks_like_command_does_not_misclassify_empty_or_whitespace_text(self) -> None:
        for non_command in (
            "",
            "   ",
            "\t\n  ",
            "[CQ:at,qq=12345]",
            "[At:12345]",
            "你好呀",
            "@机器人 今天吃什么",
        ):
            with self.subTest(non_command=non_command):
                self.assertFalse(looks_like_command(non_command))

        for real_command in (
            "/help",
            "/mem status",
            "／help",
            "!status",
            "！status",
            "#tag",
            "＃tag",
            "[CQ:at,qq=12345] /help",
            "@机器人 /mem status",
            "[Reply:99] /status",
        ):
            with self.subTest(real_command=real_command):
                self.assertTrue(looks_like_command(real_command))

    async def test_empty_text_still_skipped_by_classifier_and_group_observer(self) -> None:
        classifier = MemoryClassifier(capture_min_chars=2)
        empty_ctx = SessionContext(
            session_id="qq:GroupMessage:g100",
            scope="group",
            platform="qq",
            user_id="u200",
            user_name="测试群友",
            group_id="g100",
            bot_id="b1",
            message_id="m-empty",
            message_text="   ",
        )
        self.assertIsNone(classifier.from_user_message(empty_ctx))
        self.assertIsNone(classifier.from_bot_response(empty_ctx, "   "))
        self.assertEqual([], classifier.derived_user_memories(empty_ctx))

        service = self.make_service(
            {
                "memory_capture": {"enabled": True},
                "conversation_memory": {
                    "enabled": True,
                    "capture_group_messages": True,
                    "group_capture_engagement_only": False,
                },
            }
        )
        service.identity.resolve_event_context = AsyncMock(return_value=empty_ctx)
        service.note_identity = AsyncMock()
        await service.handle_group_message(self.make_event("   "))
        service.note_identity.assert_not_awaited()

    async def test_empty_bare_mention_turn_is_not_aborted_as_command(self) -> None:
        service = self.make_service()
        service.capture = None
        service._reply_chain_for_event = AsyncMock(return_value=None)
        service.inject_memories = AsyncMock()

        event = self.make_event("", message_id="bare-at-1")
        req = self.make_request()
        await service.handle_llm_request(event, req)

        # Bare @ / quoted media turn must enter normal memory injection path
        # rather than aborting at the slash-command short-circuit.
        service.inject_memories.assert_awaited_once()
        self.assertIn("<MemoryCompanion-Remember-Tool-Contract>", req.system_prompt)
        self.assertIn("<MemoryCompanion-Core-Memory-Tool-Contract>", req.system_prompt)
        self.assertIn("<MemoryCompanion-Recall-Guidance>", req.system_prompt)
        projected = req.func_tool.get_tool("memory_companion_query")
        self.assertIsNotNone(projected)
        self.assertEqual(["status"], projected.parameters["properties"]["operation"]["enum"])

    async def test_prefix_and_tool_hashes_stay_identical_across_all_turn_types_and_timeouts(self) -> None:
        import astrbot_plugin_memory_companion.main as plugin_main

        service = self.make_service()
        plugin = object.__new__(plugin_main.MemoryCompanionPlugin)
        plugin.service = service
        plugin._terminated = False
        plugin._init_failed = False

        # Stub out irrelevant background/external probes while exercising real
        # identity resolution, contract application, offer_query_tool, and budget timeout.
        service.capture = None
        service._reply_chain_for_event = AsyncMock(return_value=None)
        service._p5_gate = AsyncMock(return_value={"ok": True})

        async def run_turn(
            text: str,
            *,
            message_id: str,
            hang_in_inject: bool = False,
            hang_in_db_init: bool = False,
            raise_in_handle: bool = False,
        ) -> SimpleNamespace:
            event = self.make_event(text, message_id=message_id)
            req = self.make_request()
            orig_inject = service.inject_memories
            orig_init_db = service.initialize_database
            orig_handle = service.handle_llm_request

            async def slow_inject(ctx, req_obj, *, event=None):
                await asyncio.sleep(5.0)

            async def slow_init_db():
                await asyncio.sleep(5.0)
                return True

            async def failing_handle(ev, req_obj):
                raise RuntimeError("simulated early hook failure")

            if hang_in_inject:
                service.inject_memories = slow_inject
            if hang_in_db_init:
                service.initialize_database = slow_init_db
            if raise_in_handle:
                service.handle_llm_request = failing_handle
            try:
                await plugin.on_llm_request(event, req)
            finally:
                service.inject_memories = orig_inject
                service.initialize_database = orig_init_db
                service.handle_llm_request = orig_handle
            return req

        normal_req = await run_turn("你好呀，拉面好吃吗", message_id="m1")
        time_word_req = await run_turn("今天天气真不错，中午去吃什么呀", message_id="m1b")
        recall_req = await run_turn("你还记得我上次说周末几点起床吗？", message_id="m2")
        empty_req = await run_turn("", message_id="m3")
        whitespace_req = await run_turn("   ", message_id="m4")
        command_req = await run_turn("/unknown_cmd", message_id="m5")
        punct_req = await run_turn("？？？", message_id="m6")
        inject_timeout_req = await run_turn(
            "帮我回忆一下上个月去哪家面馆了",
            message_id="m7",
            hang_in_inject=True,
        )
        db_timeout_req = await run_turn(
            "你好呀",
            message_id="m8",
            hang_in_db_init=True,
        )
        early_error_req = await run_turn(
            "你好呀",
            message_id="m9",
            raise_in_handle=True,
        )

        baseline_sys_hash = _sha256_text(normal_req.system_prompt)
        baseline_tools_hash = _tools_schema_hash(normal_req.func_tool)

        # Verify static contracts are present and reconstruction contract never toggles in system_prompt.
        self.assertIn("<MemoryCompanion-Remember-Tool-Contract>", normal_req.system_prompt)
        self.assertIn("<MemoryCompanion-Core-Memory-Tool-Contract>", normal_req.system_prompt)
        self.assertIn("<MemoryCompanion-Recall-Guidance>", normal_req.system_prompt)
        self.assertNotIn("<MemoryCompanion-Reconstruction-Contract>", normal_req.system_prompt)

        # Verify memory_companion_query was projected to its compact status schema.
        projected_query = normal_req.func_tool.get_tool("memory_companion_query")
        self.assertIsNotNone(projected_query)
        self.assertEqual(["status"], projected_query.parameters["properties"]["operation"]["enum"])
        self.assertNotIn("oneOf", projected_query.parameters)
        self.assertLess(len(json_dumps(projected_query.parameters)), 400)

        for label, req in (
            ("time_word_chat", time_word_req),
            ("recall", recall_req),
            ("empty_bare_at", empty_req),
            ("whitespace_bare_at", whitespace_req),
            ("command_fallback_llm", command_req),
            ("punctuation_only", punct_req),
            ("inject_budget_timeout", inject_timeout_req),
            ("db_init_budget_timeout", db_timeout_req),
            ("early_hook_exception", early_error_req),
        ):
            with self.subTest(case=label):
                self.assertEqual(
                    baseline_sys_hash,
                    _sha256_text(req.system_prompt),
                    f"system_prompt drifted on {label}",
                )
                self.assertEqual(
                    baseline_tools_hash,
                    _tools_schema_hash(req.func_tool),
                    f"func_tool schema drifted on {label}",
                )

        # Dynamic recall/reconstruction guidance must sit strictly in tail temp parts on recall turns only.
        recall_tail = "\n".join(getattr(p, "text", "") for p in recall_req.extra_user_content_parts)
        self.assertIn("<MemoryCompanion-Reconstruction-Turn-State>", recall_tail)
        self.assertIn("本轮正常检索已选出", recall_tail)
        self.assertNotIn("本轮正常检索已选出", recall_req.system_prompt)

        for label, req in (
            ("normal", normal_req),
            ("empty_bare_at", empty_req),
            ("command_fallback_llm", command_req),
            ("inject_budget_timeout", inject_timeout_req),
            ("db_init_budget_timeout", db_timeout_req),
        ):
            with self.subTest(no_turn_state=label):
                tail = "\n".join(getattr(p, "text", "") for p in req.extra_user_content_parts)
                self.assertNotIn("<MemoryCompanion-Reconstruction-Turn-State>", tail)

    def test_tool_contracts_check_tool_availability_and_omit_dangling_contracts(self) -> None:
        service = self.make_service()
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_id="m1",
            message_text="请记住我喜欢热拿铁",
        )

        # Case 1: Empty inspected toolset -> zero dangling contracts in system_prompt.
        empty_tools_req = SimpleNamespace(
            system_prompt="基础提示",
            func_tool=_FakeToolSet([]),
        )
        service._apply_remember_tool_contract(empty_tools_req)
        service._apply_core_memory_tool_contract(empty_tools_req)
        service._apply_static_recall_contract(empty_tools_req, ctx, event=SimpleNamespace())
        self.assertEqual("基础提示", empty_tools_req.system_prompt)

        # Case 2: Tools present but active=False -> zero dangling contracts.
        inactive_tools = _build_full_toolset()
        for tool in inactive_tools.tools:
            tool.active = False
        inactive_req = SimpleNamespace(system_prompt="基础提示", func_tool=inactive_tools)
        service._apply_remember_tool_contract(inactive_req)
        service._apply_core_memory_tool_contract(inactive_req)
        service._apply_static_recall_contract(inactive_req, ctx, event=SimpleNamespace())
        self.assertEqual("基础提示", inactive_req.system_prompt)

        # Case 3: Only remember active -> only remember contract injected.
        only_remember = _FakeToolSet([_FakeTool(name="memory_companion_remember", active=True)])
        partial_req = SimpleNamespace(system_prompt="基础提示", func_tool=only_remember)
        service._apply_remember_tool_contract(partial_req)
        service._apply_core_memory_tool_contract(partial_req)
        service._apply_static_recall_contract(partial_req, ctx, event=SimpleNamespace())
        self.assertIn("<MemoryCompanion-Remember-Tool-Contract>", partial_req.system_prompt)
        self.assertNotIn("<MemoryCompanion-Core-Memory-Tool-Contract>", partial_req.system_prompt)
        self.assertNotIn("<MemoryCompanion-Recall-Guidance>", partial_req.system_prompt)

        # Case 4: Uninspected request (no func_tool) preserves backward-compatible contract injection.
        uninspected_req = SimpleNamespace(system_prompt="基础提示")
        service._apply_remember_tool_contract(uninspected_req)
        service._apply_core_memory_tool_contract(uninspected_req)
        service._apply_static_recall_contract(uninspected_req, ctx, event=SimpleNamespace())
        self.assertIn("<MemoryCompanion-Remember-Tool-Contract>", uninspected_req.system_prompt)
        self.assertIn("<MemoryCompanion-Core-Memory-Tool-Contract>", uninspected_req.system_prompt)
        self.assertIn("<MemoryCompanion-Recall-Guidance>", uninspected_req.system_prompt)

    def test_fallback_prefix_helper_respects_req036_denied_and_internal_generation(self) -> None:
        service = self.make_service()

        denied_event = SimpleNamespace(private_companion_req036_denied=True)
        # Must not inspect or mutate sentinel req object when denied.
        service.ensure_request_prefix_contracts_on_fallback(denied_event, object())

        internal_event = SimpleNamespace(private_companion_proactive_framework=True)
        internal_req = self.make_request()
        before_prompt = internal_req.system_prompt
        before_hash = _tools_schema_hash(internal_req.func_tool)
        service.ensure_request_prefix_contracts_on_fallback(internal_event, internal_req)
        self.assertEqual(before_prompt, internal_req.system_prompt)
        self.assertEqual(before_hash, _tools_schema_hash(internal_req.func_tool))

    async def test_fallback_prefix_budget_key_matches_resolved_context_and_allows_query_status(self) -> None:
        import astrbot_plugin_memory_companion.main as plugin_main

        service = self.make_service()
        service.context = SimpleNamespace(bot_self_id="b-fallback")
        service._p5_gate = AsyncMock(return_value={"ok": True})
        plugin = object.__new__(plugin_main.MemoryCompanionPlugin)
        plugin.service = service
        plugin._terminated = False
        plugin._init_failed = False

        # Event with real message_id but empty get_self_id(), relying on
        # _resolve_default_bot_id() just like IdentityResolver.resolve_event_context().
        event = SimpleNamespace(
            unified_msg_origin="",
            message_str="帮我查一下",
            get_platform_name=lambda: "qq",
            get_group_id=lambda: "",
            get_sender_id=lambda: "u200",
            get_sender_name=lambda: "测试用户",
            get_self_id=lambda: "",
            get_message_str=lambda: "帮我查一下",
            message_obj=SimpleNamespace(message_id="msg-fallback-42", message_str="帮我查一下"),
        )
        req = self.make_request()

        orig_init_db = service.initialize_database

        async def slow_init_db() -> bool:
            await asyncio.sleep(5.0)
            return True

        service.initialize_database = slow_init_db
        try:
            await plugin.on_llm_request(event, req)
        finally:
            service.initialize_database = orig_init_db

        resolved_ctx = await service.identity.resolve_event_context(event)
        expected_key = service._reconstruction_budget_key(event, resolved_ctx)
        offered_key, offered_ops = getattr(event, "_memory_query_operations", (None, set()))
        self.assertEqual(expected_key, offered_key)
        self.assertIn("status", offered_ops)

        # Subsequent query_for_model(event, "status") must succeed without operation_not_offered.
        status_result = await service.query_for_model(event, "status")
        self.assertIs(True, status_result.get("ok"), status_result)
        self.assertNotEqual("operation_not_offered", status_result.get("error"))

    async def test_fallback_prefix_respects_private_scope_control_on_bare_user_id_event(self) -> None:
        service = self.make_service({"scope_control": {"private_recall_enabled": False}})
        for origin in ("", "qq:custom:u999"):
            with self.subTest(unified_msg_origin=origin):
                event = SimpleNamespace(
                    unified_msg_origin=origin,
                    message_str="你好",
                    get_platform_name=lambda: "qq",
                    get_group_id=lambda: "",
                    get_sender_id=lambda: "u999",
                    get_sender_name=lambda: "私聊用户",
                    get_self_id=lambda: "b1",
                    get_message_str=lambda: "你好",
                    message_obj=SimpleNamespace(message_id="m-priv-1", message_str="你好"),
                )
                fallback_ctx = service._fallback_session_context_sync(event)
                resolved_ctx = await service.identity.resolve_event_context(event)
                self.assertEqual("private", fallback_ctx.scope)
                self.assertEqual(resolved_ctx.scope, fallback_ctx.scope)
                self.assertEqual(resolved_ctx.session_id, fallback_ctx.session_id)
                self.assertEqual(resolved_ctx.user_id, fallback_ctx.user_id)
                self.assertEqual(resolved_ctx.message_id, fallback_ctx.message_id)

                req = self.make_request()
                service.ensure_request_prefix_contracts_on_fallback(event, req)
                self.assertIsNone(req.func_tool.get_tool("memory_companion_query"))
                self.assertNotIn("<MemoryCompanion-Recall-Guidance>", req.system_prompt)

    def test_offer_query_tool_source_v2_description_is_idempotent(self) -> None:
        service = self.make_service({"memory_tools": {"enable_source_query_v2": True}})
        ctx = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            bot_id="b1",
            message_id="m1",
            message_text="你好",
        )

        async def source_handler(
            event,
            action="",
            terms=None,
            start_at="",
            end_at="",
            source_ref="",
            direction="",
            cursor="",
            limit=0,
            excerpt_offset=0,
        ):
            return ""

        path = "memory.test.main"
        source_tool = _FakeTool(
            name="memory_companion_sources",
            description="基础原文查询。",
            handler=source_handler,
            handler_module_path=path,
        )
        manager = SimpleNamespace(get_func=lambda name: source_tool if name == source_tool.name else None)
        assert bind_source_query_v2_schema(manager, path)

        req = SimpleNamespace(func_tool=_FakeToolSet([source_tool]))
        event = SimpleNamespace()
        offer_query_tool(service, req, ctx, event)
        first_desc = req.func_tool.get_tool("memory_companion_sources").description
        first_params = deepcopy(req.func_tool.get_tool("memory_companion_sources").parameters)
        offer_query_tool(service, req, ctx, event)
        second_desc = req.func_tool.get_tool("memory_companion_sources").description
        second_params = req.func_tool.get_tool("memory_companion_sources").parameters

        self.assertEqual(1, first_desc.count("range_batch"))
        self.assertEqual(first_desc, second_desc)
        self.assertEqual(first_params, second_params)


if __name__ == "__main__":
    unittest.main()
