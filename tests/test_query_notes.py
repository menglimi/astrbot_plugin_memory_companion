from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from functools import partial
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from jsonschema import Draft202012Validator
import pytest

from core.models import json_dumps
from core import query_notes
from .test_source_query import service, ctx, add_row, RESULT_VALIDATOR
from .test_query_session import RESULT as V1_RESULT


RESULT = Draft202012Validator(query_notes.schema("result"))


async def query(service, operation="status", parameters=None, note=None, event=None):
    result = await service.tool_query_v2(event or SimpleNamespace(), operation, parameters, query_note=note)
    RESULT.validate(result)
    if operation == "sources" and result.get("result") is not None:
        RESULT_VALIDATOR.validate(result["result"])
    return result


def note_for(result, text="暂按同一次问答理解，后续改口还需看原文。", **extra):
    original = result.get("result", result)
    return {"text": text, "evidence": [{k: s[k] for k in ("source_ref", "source_version")}
                                       for s in original["sources"]], **extra}


def state_for(service, ctx):
    return service._reconstruction_states[service._reconstruction_budget_key(SimpleNamespace(), ctx)]


def native_request(service, ctx, event):
    from scripts.evaluate_recall_model import load_plugin
    from astrbot.core.agent.tool import ToolSet
    from astrbot.core.provider.register import llm_tools
    plugin = load_plugin()
    names = ["memory_companion_" + op for op in ("recall", "sources", "navigate", "events", "query")]
    for name in names:
        llm_tools.get_func(name).handler_module_path = plugin.__name__
    assert plugin.bind_query_tool_schema(llm_tools, plugin.__name__)
    tools = ToolSet(tools=[deepcopy(llm_tools.get_func(n)) for n in names])
    request = SimpleNamespace(func_tool=tools, system_prompt="")
    service._apply_reconstruction_contract(request, ctx, event=event)
    return plugin, request, tools


def test_v2_is_paired_and_cannot_be_mistaken_for_v1():
    for name in ("request", "result"):
        Draft202012Validator.check_schema(query_notes.schema(name))
    for value in json.loads((query_notes.CONTRACT_ROOT / "examples/requests.json").read_text(encoding="utf-8")):
        Draft202012Validator(query_notes.schema("request")).validate(value)
    empty = json.loads((query_notes.CONTRACT_ROOT / "examples/result-empty.json").read_text(encoding="utf-8"))
    RESULT.validate(empty)
    assert not V1_RESULT.is_valid(empty)


@pytest.mark.asyncio
async def test_empty_read_is_local_and_no_note_does_not_create_extra_work(service, ctx):
    with patch.object(service.store, "query_progress_revisions", new_callable=AsyncMock) as metadata:
        empty = await query(service)
    assert empty["notes"]["state"] == "empty" and not service._reconstruction_states
    metadata.assert_not_awaited()
    await add_row(service, ctx)
    with patch.object(service.store, "query_source_page", wraps=service.store.query_source_page) as pages:
        result = await query(service, "sources", {"terms": ["拿铁"]})
    pages.assert_awaited_once()
    assert result["note_receipt"]["status"] == "not_submitted"
    assert not state_for(service, ctx).get("query_notes")
    service._p5_gate.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_sources_and_status_round_trip_preserves_owner_result(service, ctx):
    await add_row(service, ctx)
    event = SimpleNamespace()
    plugin, req, original_tools = native_request(service, ctx, event)
    assert "query_note" not in original_tools.get_tool("memory_companion_sources").parameters["properties"]
    original_schema = deepcopy(req.func_tool.get_tool("memory_companion_sources").parameters)
    service._apply_reconstruction_contract(req, ctx, event=event)
    assert req.func_tool.get_tool("memory_companion_sources").parameters == original_schema
    assert req.func_tool.get_tool("memory_companion_query").parameters["properties"]["operation"]["enum"] == ["status"]
    source_handler = inspect.unwrap(plugin.MemoryCompanionPlugin.memory_companion_sources_tool)
    status_handler = inspect.unwrap(plugin.MemoryCompanionPlugin.memory_companion_query_tool)
    bound = SimpleNamespace(service=service)
    # AstrBot binds the registered handler with functools.partial at loading.
    req.func_tool.get_tool("memory_companion_sources").handler = partial(source_handler, bound)
    service._apply_reconstruction_contract(req, ctx, event=event)
    assert "query_note" in req.func_tool.get_tool("memory_companion_sources").parameters["properties"]
    first = json.loads(await source_handler(bound, event, terms=["拿铁"]))
    RESULT.validate(first)
    note = note_for(first)
    before = service.store._conn.total_changes
    with patch.object(service.store, "query_source_page", wraps=service.store.query_source_page) as pages:
        second = json.loads(await source_handler(bound, event, terms=["后续"], query_note=note))
    RESULT.validate(second)
    pages.assert_awaited_once()
    assert second["note_receipt"]["status"] == "accepted" and second["notes"]["items"] == []
    identifier = second["note_receipt"]["id"]
    view = json.loads(await status_handler(bound, event, parameters={"note_ids": [identifier]}))
    RESULT.validate(view)
    assert view["notes"]["items"][0]["text"] == note["text"]
    assert view["notes"]["items"][0]["semantic_status"] == "model_interpretation"
    assert view["progress"]["steps"]["used"] == 2
    assert view["progress"]["current_context"] == "unknown"
    assert before == service.store._conn.total_changes


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_note", ["not an object", {"text": "没有引用"},
    {"text": "x" * 900, "evidence": []},
    {"text": "尚未读到", "evidence": [{"source_ref": "timeline:tl_unread", "source_version": "version"}]}])
async def test_bad_note_does_not_erase_or_repeat_valid_source_query(service, ctx, bad_note):
    await add_row(service, ctx)
    with patch.object(service.store, "query_source_page", wraps=service.store.query_source_page) as pages:
        result = await query(service, "sources", {"terms": ["拿铁"]}, bad_note)
    assert result["ok"] and result["result"]["sources"]
    assert result["note_receipt"]["status"] == "rejected"
    pages.assert_awaited_once()


@pytest.mark.asyncio
async def test_note_cannot_cite_the_query_that_has_not_returned_yet(service, ctx):
    identifier = await add_row(service, ctx)
    raw = await service.store.get_timeline_by_ids([identifier])
    assert raw
    result = await query(service, "sources", {"terms": ["拿铁"]},
                         {"text": "猜一个引用", "evidence": [{"source_ref": "timeline:" + identifier, "source_version": "made-up"}]})
    assert result["ok"] and result["note_receipt"]["error"] == "source_not_read"


@pytest.mark.asyncio
async def test_duplicate_or_budget_rejection_keeps_independent_note_receipt(service, ctx):
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    note = note_for(first)
    duplicate = await query(service, "sources", {"terms": ["拿铁"]}, note)
    assert not duplicate["ok"] and duplicate["note_receipt"]["status"] == "accepted"
    retry = await query(service, "sources", {"terms": ["拿铁"]}, note)
    assert retry["note_receipt"]["status"] == "reused"
    assert retry["note_receipt"]["id"] == duplicate["note_receipt"]["id"]
    assert retry["progress"]["steps"]["used"] == 1
    await query(service, "sources", {"terms": ["a"]})
    await query(service, "sources", {"terms": ["b"]})
    budget = await query(service, "sources", {"terms": ["c"]}, note_for(first, "另外的理解"))
    assert not budget["ok"] and budget["note_receipt"]["status"] == "accepted"
    assert budget["progress"]["steps"]["used"] == 3


@pytest.mark.asyncio
async def test_note_exception_and_source_exception_have_separate_results(service, ctx):
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    with patch("core.query_notes.accept", side_effect=RuntimeError("note unavailable")):
        value = await query(service, "sources", {"terms": ["无糖"]}, note_for(first))
    assert value["ok"] and value["note_receipt"]["status"] == "unavailable"
    with patch.object(service.store, "query_source_page", side_effect=RuntimeError("store unavailable")):
        value = await query(service, "sources", {"terms": ["后续"]}, note_for(first))
    assert not value["ok"] and value["note_receipt"]["status"] == "accepted"
    assert (await query(service))["notes"]["items"]


@pytest.mark.asyncio
async def test_replacement_uses_immutable_note_id_and_concurrent_conflict(service, ctx):
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    accepted = await query(service, "sources", {"terms": ["拿铁"]}, note_for(first, "最初理解"))
    old_id = accepted["note_receipt"]["id"]
    # Unrelated query progress changes do not create note conflicts.
    await query(service, "sources", {"terms": ["无糖"]})
    outputs = await asyncio.gather(*[query(service, "sources", {"terms": ["拿铁"]},
        note_for(first, text, replaces=[old_id])) for text in ("更正后的理解", "另一种替换")])
    assert sorted(v["note_receipt"]["status"] for v in outputs) == ["accepted", "rejected"]
    assert next(v for v in outputs if v["note_receipt"]["status"] == "rejected")["note_receipt"]["error"] == "note_replacement_conflict"
    visible = (await query(service))["notes"]
    assert visible["available"] == 1 and visible["withheld"] == 1
    assert visible["items"][0]["id"] != old_id
    assert visible["items"][0]["replaces"] == [old_id]


@pytest.mark.asyncio
async def test_cancelled_query_keeps_committed_note_and_real_reservation(service, ctx):
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set()
        await release.wait()
    with patch.object(service.store, "query_source_page", side_effect=blocked):
        task = asyncio.create_task(query(service, "sources", {"terms": ["后续"]}, note_for(first)))
        await entered.wait()
        current = await query(service)
        assert current["notes"]["available"] == 1 and current["progress"]["in_flight"] == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    view = await query(service)
    assert view["progress"]["steps"]["used"] == 2 and view["notes"]["available"] == 1


@pytest.mark.asyncio
async def test_expired_notes_do_not_revive_when_sources_are_read_again(service, ctx):
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    accepted = await query(service, "sources", {"terms": ["拿铁"]}, note_for(first))
    state = state_for(service, ctx)
    deadline = state["query_notes"]["items"][0]["expires_at"]
    with patch("core.query_notes.time.monotonic", return_value=deadline + 1):
        await query(service, "sources", {"terms": ["无糖"]})
        expired = await query(service)
        assert not expired["notes"]["items"]
        assert "暂按" not in json_dumps(expired)
        renewed = await query(service, "sources", {"terms": ["餐"]}, note_for(first))
        assert renewed["note_receipt"]["status"] == "accepted"
        assert renewed["note_receipt"]["id"] != accepted["note_receipt"]["id"]


@pytest.mark.asyncio
async def test_multi_source_note_is_withheld_whole_and_status_does_not_renew(service, ctx):
    await add_row(service, ctx, "问题颜色")
    await add_row(service, ctx, "回答颜色")
    first = await query(service, "sources", {"terms": ["颜色"]})
    await query(service, "sources", {"terms": ["颜色"]}, note_for(first))
    state = state_for(service, ctx)
    deadline, last_seen = state["query_notes"]["items"][0]["expires_at"], state["last_seen"]
    with patch.object(service.store, "query_source_page", new_callable=AsyncMock) as pages:
        detail = await query(service)
    pages.assert_not_awaited()
    assert state["query_notes"]["items"][0]["expires_at"] == deadline and state["last_seen"] == last_seen
    detail["notes"]["items"][0]["evidence"].clear()
    assert len((await query(service))["notes"]["items"][0]["evidence"]) == 2
    await add_row(service, ctx, "修订元数据变化")
    changed = await query(service)
    assert changed["notes"]["available"] == 0 and not changed["notes"]["items"]
    assert "暂按" not in json_dumps(state["query_notes"])


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["turn", "persona", "generation", "permission"])
async def test_notes_obey_current_binding_and_authorization(service, ctx, binding):
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    await query(service, "sources", {"terms": ["拿铁"]}, note_for(first))
    if binding == "turn":
        service.identity.resolve_event_context.return_value = replace(ctx, message_id="another-turn")
    elif binding == "persona":
        service.identity.resolve_event_context.return_value = replace(ctx, persona_id="another-persona")
    elif binding == "generation":
        service._query_generation = "another-generation"
    else:
        service._scope_feature_enabled = lambda *args: False
    result = await query(service)
    assert result["notes"]["available"] == 0 and "暂按" not in json_dumps(result)


@pytest.mark.asyncio
async def test_disabled_and_missing_binding_do_not_silently_accept_notes(service, ctx):
    await add_row(service, ctx)
    event = SimpleNamespace()
    plugin, req, original = native_request(service, ctx, event)
    assert "query_note" in req.func_tool.get_tool("memory_companion_sources").parameters["properties"]
    service.config.raw.setdefault("memory_tools", {})["enable_query_notes"] = False
    service._apply_reconstruction_contract(req, ctx, event=event)
    assert "query_note" not in req.func_tool.get_tool("memory_companion_sources").parameters["properties"]
    assert not event._memory_query_notes
    handler = inspect.unwrap(plugin.MemoryCompanionPlugin.memory_companion_sources_tool)
    result = json.loads(await handler(SimpleNamespace(service=service), event, terms=["拿铁"]))
    V1_RESULT.validate(result)
    bad = json.loads(await handler(SimpleNamespace(service=service), event, terms=["餐"], query_note=note_for(result)))
    assert bad["error"] == "query_notes_not_offered"
    assert (await query(service))["error"] == "query_notes_disabled"
    service.config.raw["memory_tools"]["enable_query_progress"] = False
    service._apply_reconstruction_contract(req, ctx, event=event)
    status_handler = inspect.unwrap(plugin.MemoryCompanionPlugin.memory_companion_query_tool)
    unavailable = json.loads(await status_handler(SimpleNamespace(service=service), event))
    V1_RESULT.validate(unavailable)
    assert unavailable["error"] == "query_progress_unavailable"


@pytest.mark.asyncio
async def test_compacted_context_can_read_notes_but_does_not_claim_original_present(service, ctx):
    from astrbot.core.agent.context.compressor import TruncateByTurnsCompressor
    from astrbot.core.agent.message import Message
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    saved = await query(service, "sources", {"terms": ["拿铁"]}, note_for(first))
    # Exercise the real local compressor in an isolated fixture. This is not
    # a final-input hook in the running Host or a cross-turn resume token.
    previous_context = [Message(role="system", content="引用是材料，理解可有歧义。"),
        Message(role="user", content="查那次问答"),
        Message(role="assistant", content=None, tool_calls=[{"id": "call_fixture", "type": "function",
            "function": {"name": "memory_companion_sources", "arguments": "{}"}}]),
        Message(role="tool", tool_call_id="call_fixture", content=json_dumps(first)),
        Message(role="assistant", content="还有后文待核对。"),
        Message(role="user", content="继续核对那段原话。")]
    compressed = await TruncateByTurnsCompressor(truncate_turns=1)(previous_context)
    current_context = [m.model_dump() for m in compressed]
    assert len(current_context) < len(previous_context)
    detail = await query(service, parameters={"note_ids": [saved["note_receipt"]["id"]]})
    assert detail["notes"]["items"] and detail["progress"]["current_context"] == "unknown"
    assert "无糖拿铁" not in json_dumps(current_context + [detail])
    original = await query(service, "sources", {"action": "read", "source_ref": first["result"]["sources"][0]["source_ref"]})
    assert "无糖拿铁" in json_dumps(original["result"])


@pytest.mark.asyncio
async def test_authorization_changes_during_note_acceptance_do_not_commit(service, ctx):
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    original = service.store.query_progress_revisions
    async def revoke():
        versions = await original()
        service._scope_feature_enabled = lambda *args: False
        return versions
    with patch.object(service.store, "query_progress_revisions", side_effect=revoke):
        result = await query(service, "sources", {"terms": ["无糖"]}, note_for(first))
    assert result["note_receipt"]["status"] == "rejected"
    assert not state_for(service, ctx).get("query_notes")


@pytest.mark.asyncio
async def test_missing_or_inactive_wrapper_never_enables_source_note_arguments(service, ctx):
    event = SimpleNamespace()
    plugin, req, _ = native_request(service, ctx, event)
    req.func_tool.tools = [t for t in req.func_tool.tools if t.name != "memory_companion_query"]
    service._apply_reconstruction_contract(req, ctx, event=event)
    assert event._memory_query_notes is None
    assert "query_note" not in req.func_tool.get_tool("memory_companion_sources").parameters["properties"]


@pytest.mark.asyncio
async def test_bounded_notes_share_operation_memory_and_never_truncate_statement(service, ctx):
    await add_row(service, ctx)
    first = await query(service, "sources", {"terms": ["拿铁"]})
    for i in range(30):
        value = await query(service, "sources", {"terms": ["拿铁"]}, note_for(first, "不是同一件事。" * 90 + str(i)))
        assert value["note_receipt"]["status"] == "accepted"
        assert len(json_dumps({k: value[k] for k in ("progress", "note_receipt", "notes")})) <= 900
    state = state_for(service, ctx)
    assert len(json_dumps([state["query_progress"]["operations"], state["query_notes"]["items"]]).encode("utf-8")) <= 16384
    detail = await query(service)
    assert detail["notes"]["omitted"] > 0
    assert len(json_dumps({k: detail[k] for k in ("progress", "note_receipt", "notes")})) <= 12000
    assert all(item["text"].startswith("不是同一件事。") and item["evidence"] for item in detail["notes"]["items"])
