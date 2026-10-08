from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from jsonschema import Draft202012Validator
import pytest

from core.models import json_dumps
from core.query_session import (
    CONTRACT_ROOT,
    CONTRACT_ROOT_V3,
    PROFILE,
    PROFILE_V3,
    SOURCE_DISCOVERY_PROFILE,
    bind_query_tool_schema,
    bind_query_tool_v3_schema,
    request_schema,
    request_schema_v3,
)
from .test_source_query import service, ctx, add_row, RESULT_VALIDATOR
from .test_event_query import event_row, plan_for


RESULT = Draft202012Validator(json.loads((CONTRACT_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8")))
RESULT_V3 = Draft202012Validator(json.loads(
    (CONTRACT_ROOT_V3 / "schemas/result.schema.json").read_text(encoding="utf-8")
))


async def query(service, operation="status", parameters=None, event=None):
    value = await service.tool_query(event or SimpleNamespace(), operation, parameters)
    RESULT.validate(value)
    return value


def test_paired_schemas_and_examples():
    for schema in (request_schema(), RESULT.schema):
        Draft202012Validator.check_schema(schema)
    for value in json.loads((CONTRACT_ROOT / "examples/requests.json").read_text(encoding="utf-8")):
        Draft202012Validator(request_schema()).validate(value)
    RESULT.validate(json.loads((CONTRACT_ROOT / "examples/result-empty.json").read_text(encoding="utf-8")))


def test_v3_schema_and_examples_are_self_consistent():
    request = request_schema_v3()
    result = RESULT_V3.schema
    Draft202012Validator.check_schema(request)
    Draft202012Validator.check_schema(result)
    request_validator = Draft202012Validator(request)
    for value in json.loads((CONTRACT_ROOT_V3 / "examples/requests.json").read_text(encoding="utf-8")):
        request_validator.validate(value)
    RESULT_V3.validate(json.loads((CONTRACT_ROOT_V3 / "examples/result-empty.json").read_text(encoding="utf-8")))


@pytest.mark.asyncio
async def test_empty_status_does_not_create_state_query_or_call_model(service, ctx):
    with patch.object(service.store, "query_progress_revisions", new_callable=AsyncMock) as versions:
        value = await query(service)
    assert value["progress"] == {"state": "empty"}
    versions.assert_not_awaited()
    service._p5_gate.assert_not_awaited()
    assert service._reconstruction_states == {}


@pytest.mark.asyncio
async def test_legacy_and_new_calls_share_one_ledger_without_changing_raw_result(service, ctx):
    key = await add_row(service, ctx, "浅紫色的那条")
    before = service.store._conn.total_changes
    first = await service.tool_sources(SimpleNamespace(), terms=["浅紫色"])
    RESULT_VALIDATOR.validate(first)
    with patch.object(service.store, "query_source_page", wraps=service.store.query_source_page) as pages:
        value = await query(service, "sources", {"action": "read", "source_ref": "timeline:" + key})
    pages.assert_awaited_once()
    RESULT_VALIDATOR.validate(value["result"])
    assert value["result"]["sources"] == first["sources"]
    progress = value["progress"]
    assert progress["completed"] == 2 and progress["steps"] == {"used": 2, "limit": 3, "remaining": 1}
    assert value["operation_id"] == progress["recent"][-1]["id"]
    assert progress["read_sources"] == 1 and progress["valid_sources"] == 1
    assert [r["reserved_steps"] for r in progress["recent"]] == [1, 1]
    assert "浅紫色的那条" not in json_dumps(progress)
    assert len(json_dumps(progress)) <= 900
    detail = (await query(service))["progress"]
    assert detail["sources"][0]["ref"] == "timeline:" + key
    assert detail["sources"][0]["spans"] == [[0, len("浅紫色的那条")]]
    assert service.store._conn.total_changes == before


@pytest.mark.asyncio
async def test_duplicate_and_failure_keep_real_reserved_budget(service, ctx):
    await add_row(service, ctx)
    await query(service, "sources", {"terms": ["拿铁"]})
    dup = await query(service, "sources", {"terms": ["拿铁"]})
    assert not dup["ok"] and "duplicate" in dup["result"]["error"]
    assert dup["progress"]["recent"][-1]["reserved_steps"] == 0
    with patch.object(service.store, "query_source_page", side_effect=RuntimeError("read failed")):
        failed = await query(service, "sources", {"terms": ["另一个词"]})
    assert not failed["ok"] and failed["result"]["usage"] == {}
    assert failed["progress"]["steps"]["used"] == 2
    detail = (await query(service))["progress"]
    assert detail["recent"][-1]["reserved_steps"] == 1
    assert detail["recent"][-1]["usage_known"] is False


@pytest.mark.asyncio
async def test_invalid_query_rejected_before_owner_work(service, ctx):
    with patch.object(service.store, "query_source_page", new_callable=AsyncMock) as pages:
        for op, params in [("sql", {}), ("sources", {"terms": ["拿铁"], "user_id": "other"}),
                           ("sources", {"cursor": "src_fake", "terms": ["拿铁"]}),
                           ("recall", {"query": "hello", "top_k": True}),
                           ("events", {"plan": {"sql": "SELECT *"}}), ("status", {"start": True})]:
            value = await query(service, op, params)
            assert not value["ok"] and value["error"] == "invalid_query_arguments"
    pages.assert_not_awaited()
    assert not service._reconstruction_states


@pytest.mark.asyncio
async def test_concurrent_calls_and_cancel_record_in_flight_without_refund(service, ctx):
    await add_row(service, ctx)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.store.query_source_page

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    with patch.object(service.store, "query_source_page", side_effect=delayed):
        first = asyncio.create_task(query(service, "sources", {"terms": ["拿铁"]}))
        await entered.wait()
        status = (await query(service))["progress"]
        assert status["in_flight"] == 1 and status["steps"]["used"] == 1
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
    status = (await query(service))["progress"]
    assert status["in_flight"] == 0 and status["steps"]["used"] == 1
    assert status["recent"][-1]["state"] == "cancelled"
    results = await asyncio.gather(query(service, "sources", {"terms": ["拿"]}), query(service, "sources", {"terms": ["铁"]}))
    status = (await query(service))["progress"]
    assert status["completed"] == 3 and status["steps"]["used"] == 3
    assert len({r["id"] for r in status["recent"]}) == 3


@pytest.mark.asyncio
async def test_status_does_not_refresh_cursor_or_fragment_ttl(service, ctx):
    for i in range(3):
        await add_row(service, ctx, f"回答 {i}")
    value = await query(service, "sources", {"terms": ["回答"], "limit": 1})
    cursor = value["result"]["next_cursor"]
    state = service._reconstruction_states[service._reconstruction_budget_key(SimpleNamespace(), ctx)]
    deadline = state["source_cursors"][cursor]["expires_at"]
    last_seen = state["last_seen"]
    await query(service)
    assert state["source_cursors"][cursor]["expires_at"] == deadline and state["last_seen"] == last_seen
    with patch("core.query_session.time.monotonic", return_value=deadline + 1):
        expired = (await query(service))["progress"]
    assert expired["valid_sources"] == expired["continuations"] == 0
    assert expired["sources"] == expired["cursors"] == []
    assert expired["read_sources"] == 1


@pytest.mark.asyncio
async def test_revision_change_withdraws_old_progress_details(service, ctx):
    key = await add_row(service, ctx, "待撤回的资料")
    await query(service, "sources", {"terms": ["待撤回"]})
    await add_row(service, ctx, "新的版本变化")
    status = (await query(service))["progress"]
    assert status["valid_sources"] == status["continuations"] == 0
    assert "待撤回" not in json_dumps(status) and key not in json_dumps(status)


@pytest.mark.asyncio
async def test_consumed_page_is_not_offered_again_and_status_is_independent(service, ctx):
    for i in range(3):
        await add_row(service, ctx, f"回答 {i}")
    first = await query(service, "sources", {"terms": ["回答"], "limit": 1})
    consumed = first["result"]["next_cursor"]
    second = await query(service, "sources", {"cursor": consumed})
    status = (await query(service))["progress"]
    assert consumed not in [row["cursor"] for row in status["cursors"]]
    assert second["result"]["next_cursor"] in [row["cursor"] for row in status["cursors"]]
    status["sources"][0]["spans"].clear()
    assert (await query(service))["progress"]["sources"][0]["spans"]
    service.search_context_slots = AsyncMock(return_value=([], [], {}))
    for _ in range(25):
        await query(service, "recall", {"query": "回想"})
    assert consumed not in [row["cursor"] for row in (await query(service))["progress"]["cursors"]]


@pytest.mark.asyncio
async def test_authorization_revoked_while_query_in_flight_hides_progress(service, ctx):
    await add_row(service, ctx)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.store.query_source_page
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    with patch.object(service.store, "query_source_page", side_effect=delayed):
        running = asyncio.create_task(query(service, "sources", {"terms": ["拿铁"]}))
        await entered.wait()
        with patch.object(service, "_scope_feature_enabled", return_value=False):
            release.set()
            value = await running
    assert not value["ok"] and not value["result"]["sources"]
    assert value["progress"] == {"state": "unavailable"}


@pytest.mark.parametrize("change", ["turn", "persona", "scope", "generation", "ttl"])
@pytest.mark.asyncio
async def test_changed_binding_cannot_restore_previous_progress(service, ctx, change):
    await add_row(service, ctx)
    await query(service, "sources", {"terms": ["拿铁"]})
    if change == "generation":
        service._query_generation = "new-generation"
    elif change == "ttl":
        for state in service._reconstruction_states.values():
            state["last_seen"] -= 601
    else:
        updates = {"turn": {"message_id": "new-turn"}, "persona": {"persona_id": ctx.persona_id.upper()},
                   "scope": {"strict_session_only": True}}[change]
        service.identity.resolve_event_context.return_value = replace(ctx, **updates)
    assert (await query(service))["progress"] == {"state": "empty"}


@pytest.mark.asyncio
async def test_events_and_navigation_use_same_actual_receipts(service, ctx):
    key = await add_row(service, ctx)
    value = await query(service, "sources", {"action": "read", "source_ref": "timeline:" + key})
    computed = await query(service, "events", {"plan": plan_for([event_row(value["result"]["sources"][0])])})
    assert computed["ok"] and computed["progress"]["steps"]["used"] == 2
    await service.tool_navigate(SimpleNamespace(), "search", query="无糖拿铁")
    status = (await query(service))["progress"]
    assert status["completed"] == status["steps"]["used"] == 3
    assert [r["operation"] for r in status["recent"]] == ["sources", "events", "navigate"]
    assert "quote" not in json_dumps(status)


@pytest.mark.asyncio
async def test_recall_count_is_not_navigation_step_budget(service, ctx):
    service.search_context_slots = AsyncMock(return_value=([], [], {}))
    for _ in range(4):
        value = await query(service, "recall", {"query": "自然回想一下"})
    assert value["ok"] and value["progress"]["recall_calls"] == 4
    assert value["progress"]["steps"]["used"] == 0 and value["progress"]["recall_item_limit"] == 10
    assert "自然回想一下" not in json_dumps((await query(service))["progress"])
    assert service._p5_gate.await_count == 4


@pytest.mark.asyncio
async def test_progress_failure_preserves_successful_owner_result(service, ctx):
    await add_row(service, ctx)
    with patch("core.query_session.progress", side_effect=RuntimeError("optional view unavailable")):
        value = await query(service, "sources", {"terms": ["拿铁"]})
    assert value["ok"] and value["result"]["sources"]
    assert value["progress"] == {"state": "unavailable"}


def toolset():
    from astrbot.core.agent.tool import FunctionTool, ToolSet
    path = "memory.test.main"
    legacy = [FunctionTool(name="memory_companion_" + op, description="tool", parameters={}, handler_module_path=path) for op in ("recall", "sources", "navigate", "events")]
    wrapper = FunctionTool(name="memory_companion_query", description="progress", parameters={}, handler_module_path=path)
    manager = SimpleNamespace(get_func=lambda name: wrapper if name == wrapper.name else None)
    assert bind_query_tool_schema(manager, path)
    return ToolSet(tools=[*legacy, wrapper]), legacy, wrapper


class _V3Tool:
    def __init__(self, name, handler, path="memory.test.main"):
        self.name = name
        self.handler = handler
        self.handler_module_path = path
        self.parameters = {}
        self.description = "tool"
        self.active = True


class _V3ToolSet:
    def __init__(self, tools):
        self.tools = list(tools)

    def names(self):
        return [tool.name for tool in self.tools]

    def get_tool(self, name):
        return next((tool for tool in self.tools if tool.name == name), None)


def _v3_toolset():
    async def wrapper(event, operation="status", parameters=None):
        return ""

    async def discover(event, query, terms=None, start_at="", end_at="", limit=0):
        return ""

    tools = [_V3Tool("memory_companion_query", wrapper),
             _V3Tool("memory_companion_discover_sources", discover)]
    for operation in ("recall", "sources", "navigate", "events"):
        async def legacy(event, **kwargs):
            return ""
        tools.append(_V3Tool("memory_companion_" + operation, legacy))
    manager = SimpleNamespace(get_func=lambda name: next(
        (tool for tool in tools if tool.name == name), None
    ))
    assert bind_query_tool_v3_schema(manager, "memory.test.main")
    return _V3ToolSet(tools), manager


def _enable_v3(service):
    service.config.raw["source_semantic"] = {
        "enabled": True,
        "provider_id": "test-provider",
        "model_revision": "test-model",
        "dimensions": 3,
        "processing_version": "test-processing",
    }


def _offer_v3(service, ctx):
    tools, _manager = _v3_toolset()
    event = SimpleNamespace()
    request = SimpleNamespace(func_tool=tools, system_prompt="")
    service._apply_reconstruction_contract(request, ctx, event=event)
    return request, event


def _valid_discovery_result():
    return {
        "profile": SOURCE_DISCOVERY_PROFILE,
        "ok": True,
        "status": "ready",
        "error": "",
        "matches": [],
        "sources": [],
        "coverage": {},
        "usage": {},
    }


@pytest.mark.asyncio
async def test_v3_projection_exposes_discover_only_when_capabilities_are_ready(service, ctx):
    _enable_v3(service)
    request, event = _offer_v3(service, ctx)
    projected = request.func_tool.get_tool("memory_companion_query")
    assert projected.parameters["properties"]["operation"]["enum"] == ["status", "discover"]
    assert event._memory_query_v3 is True
    assert event._memory_query_v3_key == service._reconstruction_budget_key(event, ctx)

    service.config.raw["source_semantic"]["enabled"] = False
    request, event = _offer_v3(service, ctx)
    projected = request.func_tool.get_tool("memory_companion_query")
    assert projected.parameters["properties"]["operation"]["enum"] == ["status"]
    assert event._memory_query_v3 is False
    assert event._memory_query_v3_key is None


@pytest.mark.asyncio
async def test_unbound_v3_keeps_legacy_projection_even_when_semantic_config_is_ready(service, ctx):
    _enable_v3(service)
    tools, manager = _v3_toolset()
    wrapper = tools.get_tool("memory_companion_query")
    discover = tools.get_tool("memory_companion_discover_sources")
    for function in (wrapper.handler, discover.handler):
        for marker in ("_memory_query_session_profile", "_memory_query_result_profile"):
            if hasattr(function, marker):
                delattr(function, marker)
    assert bind_query_tool_schema(manager, "memory.test.main")
    request = SimpleNamespace(func_tool=tools, system_prompt="")
    event = SimpleNamespace()
    service._apply_reconstruction_contract(request, ctx, event=event)
    projected = request.func_tool.get_tool("memory_companion_query")
    assert projected.parameters["properties"]["operation"]["enum"] == ["status"]
    assert event._memory_query_v3 is False
    assert event._memory_query_v3_key is None


@pytest.mark.asyncio
async def test_v3_discover_wraps_owner_profile_and_reserves_one_step(service, ctx):
    _enable_v3(service)
    _request, event = _offer_v3(service, ctx)
    value = await service.tool_query_v3(event, "discover", {"query": "苹果", "limit": 2})
    RESULT_V3.validate(value)
    assert value["profile"] == PROFILE_V3
    assert value["result"]["profile"] == SOURCE_DISCOVERY_PROFILE
    assert value["operation"] == "discover"
    assert value["result"]["usage"]["step"] == 1
    assert value["progress"]["steps"]["used"] == 1
    assert value["progress"]["recent"][-1]["operation"] == "discover"


@pytest.mark.asyncio
async def test_v3_discover_rejects_owner_profile_without_retrying(service, ctx):
    _enable_v3(service)
    _request, event = _offer_v3(service, ctx)
    malformed = {**_valid_discovery_result(), "profile": "memory.local-source-query.v1"}
    async def return_malformed(*_args, **_kwargs):
        await service._reserve_reconstruction_step(event, ctx, "v3-owner-profile-test")
        return malformed

    with patch("core.service.run_source_discovery", new=AsyncMock(side_effect=return_malformed)) as discover:
        value = await service.tool_query_v3(event, "discover", {"query": "苹果"})
    RESULT_V3.validate(value)
    assert value["profile"] == PROFILE_V3
    assert value["ok"] is False
    assert value["error"] == "owner_profile_mismatch"
    assert value["result"] is None
    assert discover.await_count == 1
    assert value["progress"]["steps"]["used"] == 1


@pytest.mark.asyncio
async def test_discover_without_v3_binding_returns_explicit_unavailable(service, ctx):
    event = SimpleNamespace()
    value = await service.query_for_model(event, "discover", query="苹果")
    RESULT_V3.validate(value)
    assert value == {
        "profile": PROFILE_V3,
        "ok": False,
        "operation": "discover",
        "operation_id": None,
        "error": "query_v3_unavailable",
        "result": None,
        "progress": {"state": "unavailable"},
    }


@pytest.mark.asyncio
async def test_request_projection_is_local_idempotent_and_keeps_host_availability(service, ctx):
    tools, legacy, wrapper = toolset()
    legacy[0].active = False
    before = deepcopy(wrapper.parameters)
    event = SimpleNamespace()
    req = SimpleNamespace(func_tool=tools, system_prompt="原提示")
    service._apply_reconstruction_contract(req, ctx, event=event)
    service._apply_reconstruction_contract(req, ctx, event=event)
    assert req.func_tool.names() == tools.names()
    assert len(tools.tools) == 5 and wrapper.parameters == before
    projected = req.func_tool.get_tool("memory_companion_query")
    assert projected.parameters["properties"]["operation"]["enum"] == ["status"]
    assert "oneOf" not in projected.parameters
    assert len(json_dumps(projected.parameters)) < 300
    assert not (await query(service, "recall", {"query": "hello"}, event))["ok"]
    assert not service._reconstruction_states
    service.config.raw.setdefault("memory_tools", {})["enable_query_progress"] = False
    service._apply_reconstruction_contract(req, ctx, event=event)
    assert req.func_tool.names() == [item.name for item in legacy]


@pytest.mark.asyncio
async def test_disabled_progress_uses_legacy_without_tracking(service, ctx):
    await add_row(service, ctx)
    service.config.raw.setdefault("memory_tools", {})["enable_query_progress"] = False
    assert not (await query(service))["ok"]
    value = await service.tool_sources(SimpleNamespace(), terms=["拿铁"])
    assert value["ok"]
    assert all("query_progress" not in s for s in service._reconstruction_states.values())


@pytest.mark.asyncio
async def test_model_facing_original_tools_return_progress_without_new_query_calls(service, ctx):
    import inspect
    from scripts.evaluate_recall_model import load_plugin
    plugin = load_plugin()
    await add_row(service, ctx)
    obj, event = SimpleNamespace(service=service), SimpleNamespace()
    handler = inspect.unwrap(plugin.MemoryCompanionPlugin.memory_companion_sources_tool)
    with patch.object(service.store, "query_source_page", wraps=service.store.query_source_page) as pages:
        value = json.loads(await handler(obj, event, terms=["拿铁"]))
    RESULT.validate(value)
    RESULT_VALIDATOR.validate(value["result"])
    pages.assert_awaited_once()
    assert value["progress"]["completed"] == 1
    service.config.raw.setdefault("memory_tools", {})["enable_query_progress"] = False
    value = json.loads(await handler(obj, event, terms=["无糖"]))
    RESULT_VALIDATOR.validate(value)
    assert "progress" not in value


@pytest.mark.asyncio
async def test_partial_source_progress_points_at_actual_unread_gap(service, ctx):
    key = await add_row(service, ctx, "前" * 900 + "目标说法" + "后" * 900)
    value = await query(service, "sources", {"terms": ["目标说法"]})
    assert value["result"]["sources"][0]["excerpt_offset"] > 0
    assert value["progress"]["partial_sources"] == 1
    row = (await query(service))["progress"]["sources"][0]
    assert row["next_excerpt_offset"] == 0
    await query(service, "sources", {"action": "read", "source_ref": "timeline:" + key})
    row = (await query(service))["progress"]["sources"][0]
    assert row["next_excerpt_offset"] > 800


@pytest.mark.asyncio
async def test_bounded_output_and_history_without_limiting_query_count(service, ctx):
    service.search_context_slots = AsyncMock(return_value=([], [], {}))
    for i in range(30):
        value = await query(service, "recall", {"query": "回想" * 300 + str(i)})
        assert len(json_dumps(value["progress"])) <= 900
    status = (await query(service))["progress"]
    assert status["completed"] == 30 and status["omitted_operations"] >= 6
    assert len(json_dumps(status)) <= 12000
    assert "回想" not in json_dumps(status)
