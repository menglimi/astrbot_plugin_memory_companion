from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from jsonschema import Draft202012Validator

from core.models import json_dumps
from core.query_session import bind_query_tool_schema, bind_source_query_v2_schema, offer_query_tool
from core.source_query_v2 import SOURCE_QUERY_PROFILE_V2, request_schema
from .test_query_session import _V3Tool, _V3ToolSet
from .test_source_query import add_row, ctx, refs, service


ROOT = Path(__file__).parents[1] / "docs/contracts/source-query/v2"
RESULT = Draft202012Validator(json.loads((ROOT / "schemas/result.schema.json").read_text(encoding="utf-8")))
RANGE = {"action": "range_batch", "start_at": "2026-09-08T00:00:00+08:00", "end_at": "2026-09-11T00:00:00+08:00"}


def tools_for_batch():
    from scripts.evaluate_recall_model import load_plugin
    plugin = load_plugin()
    path = plugin.__name__
    handlers = [("sources", plugin.MemoryCompanionPlugin.memory_companion_sources_tool),
                ("query", plugin.MemoryCompanionPlugin.memory_companion_query_tool)]
    tools = [_V3Tool("memory_companion_" + op, inspect.unwrap(handler), path) for op, handler in handlers]
    manager = SimpleNamespace(get_func=lambda name: next((tool for tool in tools if tool.name == name), None))
    assert bind_query_tool_schema(manager, path)
    assert bind_source_query_v2_schema(manager, path)
    return _V3ToolSet(tools), manager


@pytest.fixture
def event(service, ctx):
    service.config.raw.setdefault("memory_tools", {})["enable_source_query_v2"] = True
    tools, _ = tools_for_batch()
    value = SimpleNamespace()
    req = SimpleNamespace(func_tool=tools)
    offer_query_tool(service, req, ctx, value)
    assert value._memory_source_query_v2
    return value


async def batch(service, event, **params):
    result = await service.tool_sources(event, **params)
    RESULT.validate(result)
    if result["ok"]:
        size = len(json_dumps(result).encode("utf-8"))
        assert result["usage"]["returned_bytes"] == size <= result["usage"]["limits"]["max_bytes"]
    return result


@pytest.mark.asyncio
async def test_cross_day_batch_preserves_order_and_half_open_window(service, ctx, event):
    outside = await add_row(service, ctx, "下界外", at="2026-09-07T15:59:59Z")
    question = await add_row(service, ctx, "前夜询问", at="2026-09-08T23:59:00+08:00")
    answer = await add_row(service, ctx, "次日答复", at="2026-09-09T00:02:00+08:00", event_type="bot_response", subject_id=ctx.bot_id)
    correction = await add_row(service, ctx, "又一天的更正", at="2026-09-10T00:00:00+08:00")
    end = await add_row(service, ctx, "上界外", at=RANGE["end_at"])
    changes = service.store._conn.total_changes
    value = await batch(service, event, **RANGE)
    assert refs(value) == [question, answer, correction]
    assert outside not in str(value) and end not in str(value)
    assert value["status"] == "batch" and value["batch"]["stop_reason"] == "eof"
    assert value["coverage"]["presentation"]["status"] == "complete"
    assert value["coverage"]["interpretation"]["event_coverage"] == "not_established"
    assert service.store._conn.total_changes == changes


@pytest.mark.asyncio
async def test_more_than_twelve_short_messages_and_stable_tie_continuation(service, ctx, event):
    service.config.raw["memory_reconstruction"] = {"range_batch_max_messages": 18, "range_batch_max_bytes": 32000}
    keys = [await add_row(service, ctx, f"消息 {i}") for i in range(25)]
    with service.store._lock:
        service.store._conn.execute("UPDATE timeline SET created_at='2026-09-08T00:00:00Z'")
        service.store._conn.commit()
        ordered = [row[0] for row in service.store._conn.execute("SELECT id FROM timeline ORDER BY julianday(occurred_at),created_at,id")]
    first = await batch(service, event, **RANGE)
    assert len(first["sources"]) == 18 and first["usage"]["read_count"] == 19
    assert first["batch"]["stop_reason"] == "message_budget"
    assert first["coverage"]["traversal"]["cumulative_messages"] == 18
    second = await batch(service, event, cursor=first["batch"]["next_batch_cursor"])
    assert refs(first) + refs(second) == ordered
    assert set(ordered) == set(keys) and second["batch"]["sequence"] == 2
    assert second["batch"]["expires_at"] == first["batch"]["expires_at"]
    assert second["coverage"]["presentation"]["cumulative_completed_messages"] == 25


@pytest.mark.asyncio
async def test_utf8_byte_budget_and_long_message_resume_without_text_loss(service, ctx, event):
    service.config.raw["memory_reconstruction"] = {"range_batch_max_bytes": 4200, "max_steps": 8}
    text = "汉字🙂引号\"换行\n" * 230
    key = await add_row(service, ctx, text)
    value = await batch(service, event, **RANGE)
    chunks, offset, versions = [], 0, set()
    deadline = value["batch"]["expires_at"]
    while True:
        assert value["ok"]
        for fragment in value["sources"]:
            assert fragment["source_ref"] == "timeline:" + key
            assert fragment["excerpt_offset"] == offset
            offset = fragment["excerpt_end"]
            chunks.append(fragment["excerpt"])
            versions.add(fragment["source_version"])
        assert value["coverage"]["traversal"]["eof"]
        assert value["batch"]["expires_at"] == deadline
        cursor = value["batch"]["next_batch_cursor"]
        if not cursor:
            break
        assert value["status"] == "partial"
        assert value["coverage"]["presentation"]["status"] == "incomplete"
        value = await batch(service, event, cursor=cursor)
    stored = (await service.store.get_timeline_by_ids([key]))[key]
    assert "".join(chunks) == service._navigation_source_text(ctx, stored)
    assert len(versions) == 1 and value["coverage"]["presentation"]["cumulative_completed_messages"] == 1
    status = await service.tool_query(event)
    assert status["progress"]["partial_sources"] == status["progress"]["continuations"] == 0


@pytest.mark.asyncio
async def test_fragment_ceiling_keeps_tail_and_does_not_mark_full_presentation(service, ctx, event):
    service.config.raw["memory_reconstruction"] = {"range_batch_max_fragments": 1}
    await add_row(service, ctx, "甲" * 1800)
    first = await batch(service, event, **RANGE)
    assert first["batch"]["stop_reason"] == "fragment_budget"
    assert first["coverage"]["traversal"]["eof"] and first["coverage"]["presentation"]["pending_excerpt"]
    second = await batch(service, event, cursor=first["batch"]["next_batch_cursor"])
    third = await batch(service, event, cursor=second["batch"]["next_batch_cursor"])
    assert [x["sources"][0]["excerpt_offset"] for x in [first, second, third]] == [0, 800, 1600]
    assert third["coverage"]["presentation"]["cumulative_chars"] == 1800


@pytest.mark.asyncio
async def test_suppressed_authorized_row_is_gap_and_hidden_rows_do_not_leak(service, ctx, event):
    await add_row(service, ctx, "")
    visible = await add_row(service, ctx, "可读正文")
    hidden = await add_row(service, replace(ctx, user_id="secret", session_id="qq:FriendMessage:secret"))
    await add_row(service, ctx, "未知时间", at="unknown")
    value = await batch(service, event, **RANGE)
    assert refs(value) == [visible] and hidden not in str(value)
    assert value["coverage"]["traversal"]["cumulative_messages"] == 2
    assert value["coverage"]["presentation"]["suppressed_messages"] == 1
    assert value["coverage"]["presentation"]["status"] == "incomplete"


@pytest.mark.asyncio
async def test_tiny_budget_has_no_empty_advancing_cursor(service, ctx, event):
    service.config.raw["memory_reconstruction"] = {"range_batch_max_bytes": 128}
    await add_row(service, ctx)
    value = await batch(service, event, **RANGE)
    assert value["error"] == "range_batch_budget_too_small" and not value["batch"]
    assert not any(s.get("source_batch_cursors") for s in service._reconstruction_states.values())


@pytest.mark.parametrize("change", ["source", "policy", "expiry", "identity", "capability"])
@pytest.mark.asyncio
async def test_cursor_dependencies_and_authority_are_revalidated(service, ctx, event, change):
    service.config.raw["memory_reconstruction"] = {"range_batch_max_messages": 1}
    await add_row(service, ctx)
    await add_row(service, ctx, "第二条")
    first = await batch(service, event, **RANGE)
    cursor = first["batch"]["next_batch_cursor"]
    if change == "source":
        await add_row(service, ctx, "新增内容")
    elif change == "policy":
        await service.store.upsert_acl_rule(owner_scope="private", owner_id=ctx.user_id, reader_scope="group", reader_id="g", effect="deny")
    elif change == "expiry":
        for state in service._reconstruction_states.values():
            state["source_batch_cursors"][cursor]["expires_at"] = 0
    elif change == "identity":
        service.identity.resolve_event_context.return_value = replace(ctx, persona_id="other")
    else:
        event._memory_source_query_v2 = False
    second = await batch(service, event, cursor=cursor)
    assert second["error"] in {"cursor_invalid", "source_query_v2_not_offered"}
    assert not second["sources"]


@pytest.mark.asyncio
async def test_v1_and_v2_cursors_cannot_be_mixed_and_budgets_do_not_reset(service, ctx, event):
    service.config.raw["memory_reconstruction"] = {"range_batch_max_messages": 1}
    for i in range(4):
        await add_row(service, ctx, f"共同线索 {i}")
    first = await batch(service, event, **RANGE)
    with patch.object(service.store, "query_source_page", side_effect=AssertionError("wrong owner")):
        second = await batch(service, event, cursor=first["batch"]["next_batch_cursor"])
    duplicate = await batch(service, event, cursor=first["batch"]["next_batch_cursor"])
    assert duplicate["error"] == "duplicate navigation call"
    legacy = await service.tool_sources(event, terms=["共同线索"], limit=1)
    assert legacy["profile"].endswith(".v1")
    mixed = await batch(service, event, **{**RANGE, "cursor": legacy["next_cursor"]})
    assert mixed["error"] == "cursor_invalid"
    final = await batch(service, event, cursor=second["batch"]["next_batch_cursor"])
    assert final["error"] == "navigation step budget exhausted"


@pytest.mark.asyncio
async def test_change_during_query_and_cancellation_issue_no_batch_receipts(service, ctx, event):
    await add_row(service, ctx)
    original = service.store.query_source_range_batch
    async def changed(*args, **kwargs):
        value = await original(*args, **kwargs)
        await add_row(service, ctx, "稍后变更")
        return value
    with patch.object(service.store, "query_source_range_batch", side_effect=changed):
        value = await batch(service, event, **RANGE)
    assert value["error"] == "source_changed_retry"
    with patch.object(service.store, "query_source_range_batch", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await batch(service, event, **{**RANGE, "end_at": "2026-09-12T00:00:00+08:00"})
    assert not any(s.get("source_batch_cursors") or s.get("issued_sources") for s in service._reconstruction_states.values())


@pytest.mark.asyncio
async def test_native_handler_projection_and_v3_envelope_with_notes(service, ctx, event):
    await add_row(service, ctx)
    tools, manager = tools_for_batch()
    source = manager.get_func("memory_companion_sources")
    initial = deepcopy(source.parameters)
    req = SimpleNamespace(func_tool=tools)
    offer_query_tool(service, req, ctx, event)
    projected = req.func_tool.get_tool(source.name)
    assert "range_batch" in projected.parameters["properties"]["action"]["enum"]
    assert source.parameters == initial
    Draft202012Validator(projected.parameters).validate(RANGE)
    result = json.loads(await projected.handler(SimpleNamespace(service=service), event, **RANGE))
    assert result["ok"] and result["profile"] == "memory.local-query-session.v3"
    RESULT.validate(result["result"])
    assert result["progress"]["steps"]["used"] == 1
    evidence = [{"source_ref": x["source_ref"], "source_version": x["source_version"]} for x in result["result"]["sources"]]
    note = {"text": "已读到一条原文", "evidence": evidence}
    Draft202012Validator(projected.parameters).validate({**RANGE, "query_note": note})


@pytest.mark.asyncio
async def test_unbound_or_disabled_capability_stays_v1_and_rejects_batch(service, ctx):
    tools, manager = tools_for_batch()
    req, event = SimpleNamespace(func_tool=tools), SimpleNamespace()
    offer_query_tool(service, req, ctx, event)
    assert not event._memory_source_query_v2
    assert "range_batch" not in req.func_tool.get_tool("memory_companion_sources").parameters["properties"]["action"]["enum"]
    assert (await batch(service, event, **RANGE))["error"] == "source_query_v2_not_offered"
    service.config.raw["memory_tools"] = {"enable_source_query_v2": True}
    manager.get_func("memory_companion_sources").handler_module_path = "foreign.main"
    req = SimpleNamespace(func_tool=tools)
    offer_query_tool(service, req, ctx, event)
    assert not event._memory_source_query_v2


@pytest.mark.asyncio
async def test_disabled_progress_still_uses_shared_navigation_budget(service, ctx, event):
    service.config.raw["memory_tools"]["enable_query_progress"] = False
    await add_row(service, ctx)
    value = await service.query_for_model(event, "sources", **RANGE)
    RESULT.validate(value)
    assert value["ok"] and value["usage"]["step"] == 1


@pytest.mark.asyncio
async def test_v3_checks_batch_owner_profile_without_retry(service, ctx, event):
    service.tool_sources = AsyncMock(return_value={"profile": "memory.local-source-query.v1", "ok": True})
    value = await service.query_for_model(event, "sources", **RANGE)
    assert not value["ok"] and value["error"] == "owner_profile_mismatch" and value["result"] is None
    service.tool_sources.assert_awaited_once()


@pytest.mark.asyncio
async def test_cursor_keeps_bound_limits_and_receipts_only_count_returned_rows(service, ctx, event):
    service.config.raw["memory_reconstruction"] = {"range_batch_max_messages": 1}
    first_key = await add_row(service, ctx)
    second_key = await add_row(service, ctx, "第二条", at="2026-09-08T00:00:01+08:00")
    first = await batch(service, event, **RANGE)
    state = next(iter(service._reconstruction_states.values()))
    assert set(state["issued_sources"]) == {"timeline:" + first_key}
    service.config.raw["memory_reconstruction"]["range_batch_max_messages"] = 48
    second = await batch(service, event, cursor=first["batch"]["next_batch_cursor"])
    assert second["usage"]["limits"]["max_messages"] == 1 and refs(second) == [second_key]


@pytest.mark.asyncio
async def test_oversized_history_is_explicitly_blocked_and_read_transaction_closes(service, ctx, event):
    key = await add_row(service, ctx, "原本短正文")
    with service.store._lock:
        service.store._conn.execute("UPDATE timeline SET content=? WHERE id=?", ("长" * 262145, key))
        service.store._conn.commit()
    value = await batch(service, event, **RANGE)
    assert value["error"] == "source_processing_budget_exceeded" and not value["batch"]
    assert not service.store._read_conn.in_transaction


def test_contract_schemas_examples_and_mixed_input_rejection():
    Draft202012Validator.check_schema(request_schema())
    Draft202012Validator.check_schema(RESULT.schema)
    for example in json.loads((ROOT / "examples/requests.json").read_text(encoding="utf-8")):
        Draft202012Validator(request_schema()).validate(example)
    for path in (ROOT / "examples").glob("result-*.json"):
        example = json.loads(path.read_text(encoding="utf-8"))
        RESULT.validate(example)
        if example["ok"]:
            assert example["usage"]["returned_bytes"] == len(json_dumps(example).encode("utf-8"))
    for params in [{**RANGE, "terms": ["筛选"]}, {**RANGE, "limit": 48}, {**RANGE, "bot_id": "forged"},
                   {**RANGE, "cursor": "src_example"}, {"cursor": "srcb_example", "end_at": RANGE["end_at"]},
                   {**RANGE, "start_at": "2026-09-08"}, {**RANGE, "excerpt_offset": True}]:
        assert not Draft202012Validator(request_schema()).is_valid(params)
