from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.injection import MEMORY_COMPANION_INJECTION_HEADER
from core.memory_revision import MemoryContext, memory_ref
from core.service import MemoryCompanionService
from core.models import SearchResult
from .test_memory_correction import context, record


@pytest.fixture
def service(tmp_path):
    value = MemoryCompanionService(
        context=None, plugin_root=Path(__file__).parents[1], data_dir=tmp_path,
        config={
            "injection_cache_ttl_seconds": 60,
            "memory_injection": {"max_chars": 3000, "enable_injection_logs": False},
            "retrieval": {"mode": "basic", "embedding_enabled": False},
            "conversation_memory_advanced": {
                "low_information_guard_enabled": False, "topic_shift_guard_enabled": False,
            },
        },
    )
    value._p5_gate = AsyncMock(return_value={"ok": True})
    yield value
    value.close()


def request():
    return SimpleNamespace(prompt="用户原始请求", contexts=[{"role": "user", "content": "前面谈到口味"}],
                           extra_user_content_parts=[])


def body(req):
    return req.prompt + "\n" + "\n".join(part.text for part in req.extra_user_content_parts)


async def seed(service):
    await service.store.insert_memory(record(message_id="source-message", confidence=0.95, importance=0.8))
    return await service.store.get_memory("old")


def compose(service, item, ctx=None, *, max_chars=3000):
    result = SearchResult(memory=item, score=0.95, reason="mention")
    return service.injection.compose(ctx or context(), [result], max_chars=max_chars), {"stable_memory": [result]}


async def publish(service, item, *, ctx=None, req=None, event=None, max_chars=3000):
    req, event = req or request(), event or SimpleNamespace()
    injection, slots = compose(service, item, ctx, max_chars=max_chars)
    ok = await service._publish_reply_memory_context(
        ctx or context(), req, event=event, injection=injection, slot_map=slots,
        strategy_id="existing.search_context_slots",
    )
    return ok, req, event


@pytest.mark.asyncio
async def test_changed_turn_recompiles_even_with_ttl_and_retry_does_not_duplicate(service):
    item = await seed(service)
    first_ctx = context(message_id="turn-a", message_text="你还记得我喜欢辣味吗？")
    second_ctx = replace(first_ctx, message_id="turn-b", message_text="聊聊我喜欢辣味的事情吧。")
    service._injection_cache[first_ctx.session_id] = (0, MemoryContext("上一轮的缓存内容", [memory_ref(item)]), "private")
    req, event = request(), SimpleNamespace()
    await service.inject_memories(first_ctx, req, event=event)
    first = deepcopy(req.memory_companion_continuity_snapshot)
    assert first is not None and item.content in body(req), req.memory_companion_injection_state
    await service.inject_memories(second_ctx, req, event=event)
    second = deepcopy(req.memory_companion_continuity_snapshot)
    assert first["snapshot_id"] != second["snapshot_id"]
    assert first_ctx.message_text not in body(req) and second_ctx.message_text in body(req)
    await service.inject_memories(second_ctx, req, event=event)
    assert body(req).count(MEMORY_COMPANION_INJECTION_HEADER) == 1
    assert req.memory_companion_continuity_snapshot["snapshot_id"] == second["snapshot_id"]
    assert service._p5_gate.await_count == 3


@pytest.mark.asyncio
async def test_history_compression_changes_snapshot_and_records_available_history(service):
    item = await seed(service)
    ok, req, event = await publish(service, item)
    assert ok
    before = deepcopy(req.memory_companion_continuity_snapshot)
    req.contexts = [{"role": "assistant", "content": [{"type": "text", "text": "压缩后的摘要"}]}]
    ok, req, event = await publish(service, item, req=req, event=event)
    after = req.memory_companion_continuity_snapshot
    assert ok and before["context_revision"] != after["context_revision"]
    assert after["coverage"]["available_history_items"] == 1
    assert after["coverage"]["history_recovery"] == "not_performed"
    assert "压缩后的摘要" not in json.dumps(after, ensure_ascii=False)


@pytest.mark.asyncio
async def test_receipt_has_real_revision_and_isolated_copies_of_rendered_refs(service):
    item = await seed(service)
    ok, req, event = await publish(service, item)
    assert ok
    snapshot = req.memory_companion_continuity_snapshot
    assert snapshot["memory_revision"] == await service.store.memory_revision()
    assert snapshot["state"] == "ready" and snapshot["continuity_refs"][0]["purpose"] == "reply"
    assert event.memory_companion_injection_state["injected_memory_ids"] == [item.id]
    snapshot["continuity_refs"].clear()
    req.memory_companion_injection_state["memory_refs"].clear()
    assert event.memory_companion_continuity_snapshot["continuity_refs"]
    assert event.memory_companion_injection_state["memory_refs"] == [memory_ref(item)]


@pytest.mark.parametrize("change", ["corrected", "expired", "acl", "persona", "missing"])
@pytest.mark.asyncio
async def test_final_validation_rejects_stale_or_invisible_evidence(service, change):
    item = await seed(service)
    if change == "acl":
        item = replace(item, id="group-memory", scope="group", group_id="group-x", session_id="qq:GroupMessage:group-x",
                       visibility="group_public")
        await service.store.insert_memory(item)
        item = await service.store.get_memory(item.id)
        rule = await service.store.upsert_acl_rule(owner_scope="group", owner_id="group-x",
            reader_scope="private", reader_id="user", effect="allow")
    injection, slots = compose(service, item)
    if change == "corrected":
        await service.store.correct_user_memory(context(), memory_id=item.id,
            expected_version=memory_ref(item)["version"], correction_id="correction", content="用户喜欢清淡口味。")
    elif change == "expired":
        await service.store.update_memory_payload(item.id, valid_to="2000-01-01T00:00:00Z")
        item = await service.store.get_memory(item.id)
        injection, slots = compose(service, item)
    elif change == "acl":
        await service.store.delete_acl_rule(rule["id"])
    elif change == "persona":
        item.metadata["persona_id"] = "different-persona"
        await service.store.update_memory_payload(item.id, metadata=item.metadata)
        item = await service.store.get_memory(item.id)
        injection, slots = compose(service, item)
    else:
        injection.memory_refs[0]["id"] = "missing"
        injection.continuity_snapshot["continuity_refs"][0]["ref_id"] = "missing"
    req, event = request(), SimpleNamespace(memory_companion_continuity_snapshot={"old": True})
    ok = await service._publish_reply_memory_context(context(), req, event=event, injection=injection,
        slot_map=slots, strategy_id="existing.search_context_slots")
    assert not ok and MEMORY_COMPANION_INJECTION_HEADER not in body(req)
    assert event.memory_companion_continuity_snapshot is None
    assert not event.memory_companion_injection_state["injected"]


@pytest.mark.asyncio
async def test_correction_then_fresh_read_can_inject_replacement(service):
    item = await seed(service)
    receipt = await service.store.correct_user_memory(context(), memory_id=item.id,
        expected_version=memory_ref(item)["version"], correction_id="correction", content="用户喜欢清淡口味。")
    new = await service.store.get_memory(receipt["new_ref"]["id"])
    ok, req, event = await publish(service, new)
    assert ok and new.content in body(req) and item.content not in body(req)
    assert event.memory_companion_injection_state["memory_refs"] == [receipt["new_ref"]]


@pytest.mark.asyncio
async def test_budget_omission_is_not_reported_as_injected_memory(service):
    ok, req, event = await publish(service, await seed(service), max_chars=300)
    assert ok
    state = event.memory_companion_injection_state
    assert state["selected_memory_ids"] == ["old"]
    assert state["memory_refs"] == state["injected_memory_ids"] == state["feedback_target_memory_ids"] == []
    assert req.memory_companion_continuity_snapshot["usage"]["rendered_items"] == 0


@pytest.mark.parametrize("failure", ["append", "missing_refs", "disabled", "gate"])
@pytest.mark.asyncio
async def test_unpublished_or_skipped_context_never_retains_success_receipt(service, monkeypatch, failure):
    item = await seed(service)
    req, event = request(), SimpleNamespace()
    await publish(service, item, req=req, event=event)
    if failure == "append":
        monkeypatch.setattr("core.service.append_temp_text", lambda *_: (_ for _ in ()).throw(RuntimeError("append failed")))
        with pytest.raises(RuntimeError, match="append failed"):
            await publish(service, item, req=req, event=event)
    elif failure == "missing_refs":
        await service._publish_reply_memory_context(context(), req, event=event, injection="untracked text",
            slot_map={}, strategy_id="test")
    else:
        if failure == "disabled":
            original = service.config.bool
            monkeypatch.setattr(service.config, "bool", lambda key, default=True: False if key == "memory_injection.enabled" else original(key, default))
        else:
            service._p5_gate.return_value = {"ok": False}
        await service.inject_memories(context(), req, event=event)
    assert event.memory_companion_continuity_snapshot is None
    assert req.memory_companion_continuity_snapshot is None
    assert not event.memory_companion_injection_state["injected"]


def test_source_metadata_does_not_invent_or_stringify_evidence(service):
    item = record(message_id="", metadata={"evidence_refs": [{"unknown": "not a source"}, {"message_id": "source-2"}]})
    injection, _ = compose(service, item)
    assert injection.continuity_snapshot["continuity_refs"][0]["source_ref"] == "source-2"
    item.metadata = {}
    injection, _ = compose(service, item)
    assert injection.continuity_snapshot["continuity_refs"][0]["source_ref"] == ""
    assert injection.continuity_snapshot["coverage"]["missing_source_refs"] == 1


def test_current_message_alone_changes_snapshot_identity():
    from core.continuity import build_context_snapshot
    ctx = context()
    first = build_context_snapshot(ctx)
    second = build_context_snapshot(replace(ctx, message_text="另一条当前消息"))
    assert first.snapshot_id != second.snapshot_id
    assert second.current_turn_digest == hashlib.sha256("另一条当前消息".encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_followup_retrieval_uses_request_history_before_delayed_timeline(service):
    from core.turn_signal import analyze_turn_signal
    ctx = context(message_text="还有呢？")
    req = request()
    req.contexts = [
        {"role": "user", "content": "你还记得我们讨论的蓝绿发布方案吗？"},
        {"role": "assistant", "content": [{"type": "text", "text": "蓝绿发布可以先从灰度验证开始。"}]},
    ]
    service.store.recent_timeline = AsyncMock(side_effect=AssertionError("request history is already available"))
    intent = service.intent_builder.build(ctx, req=req)
    expanded = await service._expand_contextual_retrieval_intent(ctx, intent, analyze_turn_signal(ctx.message_text), req=req)
    assert expanded.query != ctx.message_text
    assert "蓝绿" in expanded.query or "灰度" in expanded.query
    service.store.recent_timeline.assert_not_awaited()


@pytest.mark.parametrize("query", ["上次穿蕾丝胖次是什么时候", "上次借的雨伞是哪天还的"])
@pytest.mark.parametrize("entry", ["reply", "compose"])
@pytest.mark.asyncio
async def test_complete_recall_reaches_search_without_unrelated_recent_anchors(service, query, entry):
    req = request()
    weather = "气象台刚更新了，橙色暴雨预警还没解除，尽量别出门，窗关好。"
    req.contexts = [{"role": "assistant", "content": weather}, {"role": "assistant", "content": weather}]
    for index in range(2):
        await service.store.add_timeline_event(
            event_type="bot_response", session_id=context().session_id, scope="private",
            subject_id=context().bot_id, object_id=context().user_id,
            content=weather, occurred_at=f"2026-09-13T12:0{index}:00+08:00", metadata={},
        )
    original = deepcopy(req.contexts)
    service.search_context_slots = AsyncMock(wraps=service.search_context_slots)
    ctx = context(message_text=query)
    if entry == "reply":
        await service.inject_memories(ctx, req, event=SimpleNamespace())
    else:
        await service._compose_memory_injection(ctx, req=req, event=SimpleNamespace())
    service.search_context_slots.assert_awaited_once()
    assert service.search_context_slots.call_args.args[0] == query
    assert req.contexts == original


@pytest.mark.asyncio
async def test_compose_followup_uses_request_history_in_actual_search(service):
    req = request()
    req.contexts = [
        {"role": "user", "content": "你还记得我们讨论的蓝绿发布方案吗？"},
        {"role": "assistant", "content": "蓝绿发布可以先从灰度验证开始。"},
    ]
    service.search_context_slots = AsyncMock(wraps=service.search_context_slots)
    await service._compose_memory_injection(context(message_text="你还记得那个方案吗？"), req=req, event=SimpleNamespace())
    query = service.search_context_slots.call_args.args[0]
    assert "蓝绿" in query or "灰度" in query


@pytest.mark.parametrize("availability", ["available", "empty", "uninspected"])
def test_reconstruction_diagnostic_observes_request_tools_without_dialogue(service, caplog, availability):
    from astrbot.core.agent.tool import FunctionTool, ToolSet
    req = request()
    if availability != "uninspected":
        req.func_tool = ToolSet(tools=[
            FunctionTool(name="memory_companion_sources", description="source lookup", parameters={}),
            FunctionTool(name="memory_companion_events", description="inactive calculation", parameters={}, active=False),
        ] if availability == "available" else [])
    with caplog.at_level("INFO", logger="astrbot"):
        service._apply_reconstruction_contract(req, context(message_text="上次借的雨伞是哪天还的"))
    diagnostic = next(item.message for item in caplog.records if "reconstruction offered:" in item.message)
    expected = {"available": "memory_companion_sources", "empty": "none", "uninspected": "uninspected"}[availability]
    assert f"request_tools_at_memory_hook={expected}" in diagnostic
    assert "memory_companion_events" not in diagnostic and "雨伞" not in diagnostic
    if availability == "available":
        assert len(req.func_tool.tools) == 2 and not req.func_tool.tools[1].active


@pytest.mark.parametrize("format", ["plain", "parts", "objects"])
@pytest.mark.asyncio
async def test_followup_query_excludes_host_reminders_and_part_metadata(service, format):
    from core.turn_signal import analyze_turn_signal
    text = "你还记得我们讨论的蓝绿发布方案吗？"
    reminder = "<system_reminder>User ID: 987654321, Nickname: metadata_alias</system_reminder>"
    content = text + reminder
    if format == "parts":
        content = [
            {"type": "text", "text": text, "metadata": {"text": "private_part_metadata"}, "source": "internal_source"},
            {"type": "text", "text": reminder},
            {"type": "image_url", "image_url": {"url": "https://example.invalid/not-dialogue"}, "metadata": {"text": "media_metadata"}},
        ]
    elif format == "objects":
        content = [SimpleNamespace(text=text), SimpleNamespace(text=reminder)]
    req = request()
    req.contexts = [{"role": "user", "content": content}]
    original = deepcopy(req.contexts)
    ctx = context(message_text="还有呢？")
    service.store.recent_timeline = AsyncMock(side_effect=AssertionError("visible request history exists"))
    intent = service.intent_builder.build(ctx, req=req)
    expanded = await service._expand_contextual_retrieval_intent(ctx, intent, analyze_turn_signal(ctx.message_text), req=req)
    assert "蓝绿" in expanded.query
    for noise in ("system_reminder", "987654321", "nickname", "metadata_alias", "private_part_metadata", "internal_source", "media_metadata"):
        assert noise not in expanded.query.lower()
    assert req.contexts == original
    service.store.recent_timeline.assert_not_awaited()


@pytest.mark.asyncio
async def test_reminder_only_history_uses_visible_timeline_for_followup(service):
    from core.turn_signal import analyze_turn_signal
    req = request()
    req.contexts = [{"role": "user", "content": "<system_reminder>metadata_alias</system_reminder>"}]
    service.store.recent_timeline = AsyncMock(return_value=[{
        "event_type": "user_message",
        "content": "你还记得我们讨论的蓝绿发布方案吗？<system_reminder>other_metadata</system_reminder>",
    }])
    ctx = context(message_text="还有呢？")
    expanded = await service._expand_contextual_retrieval_intent(
        ctx, service.intent_builder.build(ctx, req=req), analyze_turn_signal(ctx.message_text), req=req,
    )
    assert "蓝绿" in expanded.query and "metadata" not in expanded.query
    service.store.recent_timeline.assert_awaited_once()


def test_history_projection_preserves_literal_dialogue_and_only_removes_protocol_blocks():
    from core.astrbot_compat import retrieval_history_text
    dialogue = "User ID 是接口字段。a < b；<code>metadata_alias</code>；&lt;system_reminder&gt;"
    text = dialogue + '<SYSTEM_REMINDER source="host">hidden<system_reminder>nested</system_reminder>also_hidden</SYSTEM_REMINDER>后续正文'
    cleaned = retrieval_history_text(text)
    assert dialogue in cleaned and "后续正文" in cleaned
    assert "hidden" not in cleaned
    assert retrieval_history_text("正文<system_reminder>incomplete_metadata") == "正文"


@pytest.mark.asyncio
async def test_concurrent_revision_change_is_not_published_as_a_coherent_snapshot(service):
    item = await seed(service)
    service.store.memory_revision = AsyncMock(side_effect=["revision-before", "revision-after"])
    ok, req, event = await publish(service, item)
    assert not ok and MEMORY_COMPANION_INJECTION_HEADER not in body(req)
    assert event.memory_companion_injection_state["reason_code"] == "memory_changed_or_unavailable"


@pytest.mark.asyncio
async def test_core_memory_remains_injected_and_disabled_core_is_rejected(service):
    item = record(memory_type="core_memory", confidence=1.0, metadata={
        "core_memory": True, "core_enabled": True, "core_scope": "private", "target_id": "user",
        "core_kind": "rule", "core_label": "口味", "persona_id": "persona", "owner_bot_id": "bot",
    })
    await service.store.save_core_memory(item, expected_revision=0)
    item = await service.store.get_memory(item.id)
    injection = service.injection.compose(context(), [], max_chars=3000, core_memories=[item])
    req, event = request(), SimpleNamespace()
    assert await service._publish_reply_memory_context(context(), req, event=event, injection=injection,
        slot_map={}, strategy_id="existing.core_and_recent_context")
    assert "<core_memory>" in body(req) and event.memory_companion_injection_state["memory_refs"]
    await service.store.update_memory_payload(item.id, metadata={**item.metadata, "core_enabled": False})
    assert not await service._publish_reply_memory_context(context(), req, event=event, injection=injection,
        slot_map={}, strategy_id="existing.core_and_recent_context")
    assert MEMORY_COMPANION_INJECTION_HEADER not in body(req)


@pytest.mark.asyncio
async def test_timeline_sources_are_reloaded_from_their_own_store(service):
    ctx = context()
    key = await service.store.add_timeline_event(event_type="user_message", session_id=ctx.session_id,
        scope=ctx.scope, subject_id=ctx.user_id, object_id=ctx.bot_id, content="当时讨论过灰度验证。")
    rows = await service.store.get_timeline_by_ids([key])
    item = service._timeline_row_as_memory(ctx, rows[key])
    ok, req, event = await publish(service, item)
    assert ok
    ref = event.memory_companion_continuity_snapshot["continuity_refs"][0]
    assert ref["ref_kind"] == "source" and ref["source_ref"] == f"timeline:{key}"
    assert "当时讨论过灰度验证" in body(req)


@pytest.mark.parametrize("platform,allowed", [("default", True), ("aiocqhttp", True), ("slack", False)])
@pytest.mark.asyncio
async def test_final_validation_preserves_platform_alias_policy(service, platform, allowed):
    item = record(platform=platform, confidence=0.95)
    await service.store.insert_memory(item)
    item = await service.store.get_memory(item.id)
    ok, req, event = await publish(service, item)
    assert ok is allowed
    assert (event.memory_companion_continuity_snapshot is not None) is allowed
