from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.bridge import MemoryCompanionBridge, serialize_memory
from core.injection import InjectionComposer
from core.memory_revision import MemoryRevisionError, current_memory, memory_ref
from core.models import EntityRef, MemoryRecord, SearchResult, SessionContext
from core.profile_quality import profile_quality_decision
from core.service import MemoryCompanionService
from core.store import MemoryStore
from core.visibility import VisibilityPolicy


@pytest.fixture
def store(tmp_path):
    value = MemoryStore(tmp_path / "memory.db")
    value.initialize()
    yield value
    value.close()


def context(**changes):
    return replace(SessionContext(
        scope="private", platform="qq", session_id="qq:FriendMessage:user", user_id="user",
        bot_id="bot", persona_id="persona", message_id="message-2", message_text="我之前说错了，我喜欢的是清淡口味。",
    ), **changes)


def record(**changes):
    return replace(MemoryRecord(
        id="old", memory_type="memory", subject=EntityRef(kind="user", id="user"),
        object=EntityRef(kind="bot", id="bot"), owner_bot_id="bot", scope="private", platform="qq",
        session_id="qq:FriendMessage:user", visibility="private_pair", lifecycle="stable_memory",
        content="用户喜欢辣味。", evidence="我喜欢吃辣。", metadata={"persona_id": "persona", "owner_bot_id": "bot"},
    ), **changes).ensure_defaults()


async def seeded(store, **changes):
    item = record(**changes)
    await store.insert_memory(item)
    return await store.get_memory(item.id)


async def correct(store, item, **changes):
    kwargs = dict(memory_id=item.id, expected_version=memory_ref(item)["version"],
                  correction_id="change-1", content="用户喜欢清淡口味。", trace_id="trace-1")
    kwargs.update(changes)
    return await store.correct_user_memory(context(), **kwargs)


@pytest.mark.asyncio
async def test_correction_preserves_history_receipt_and_survives_reopen(store, tmp_path):
    old = await seeded(store)
    receipt = await correct(store, old)
    archived = await store.get_memory(old.id)
    replacement = await store.get_memory(receipt["new_ref"]["id"])
    assert archived.content == old.content and not current_memory(archived)
    assert replacement.supersedes_id == old.id and current_memory(replacement)
    assert replacement.evidence == context().message_text
    assert receipt["new_ref"] == memory_ref(replacement)
    assert (await correct(store, old))["deduplicated"]
    reopened = MemoryStore(tmp_path / "memory.db")
    reopened.initialize()
    try:
        replay = await reopened.correct_user_memory(context(message_id="later"), action="lookup", correction_id="change-1")
        assert replay["new_ref"] == receipt["new_ref"] and replay["trace_id"] == "trace-1"
        assert reopened._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2
        assert reopened._conn.execute("SELECT COUNT(*) FROM memory_correction_receipts").fetchone()[0] == 1
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_concurrent_corrections_compare_the_version_in_the_transaction(store):
    old = await seeded(store)
    results = await asyncio.gather(correct(store, old), correct(store, old, correction_id="change-2", content="新说法"),
                                   return_exceptions=True)
    assert sum(isinstance(item, dict) and item.get("ok") for item in results) == 1
    assert any(isinstance(item, MemoryRevisionError) and str(item) == "memory_revision_conflict" for item in results)
    assert store._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_failed_replacement_rolls_back_old_state_and_receipt(store, monkeypatch):
    old = await seeded(store)
    original = store._write_memory_record_sync
    def failing(item):
        if item.id != old.id:
            raise RuntimeError("simulated disk failure")
        return original(item)
    monkeypatch.setattr(store, "_write_memory_record_sync", failing)
    with pytest.raises(RuntimeError, match="disk failure"):
        await correct(store, old)
    assert memory_ref(await store.get_memory(old.id)) == memory_ref(old)
    assert store._conn.execute("SELECT COUNT(*) FROM memory_correction_receipts").fetchone()[0] == 0


@pytest.mark.parametrize("changes", [
    {"user_id": "other"}, {"bot_id": "other"}, {"persona_id": "other"},
    {"session_id": "qq:FriendMessage:other"}, {"scope": "group", "group_id": "group"},
])
@pytest.mark.asyncio
async def test_correction_cannot_cross_ownership(store, changes):
    old = await seeded(store)
    with pytest.raises(MemoryRevisionError, match="memory_not_owned"):
        await store.correct_user_memory(context(**changes), memory_id=old.id, expected_version=memory_ref(old)["version"],
                                        correction_id="change", content="替换内容")
    assert memory_ref(await store.get_memory(old.id)) == memory_ref(old)


@pytest.mark.asyncio
async def test_profile_revision_replaces_structured_value_and_stale_summary(store):
    old = await seeded(store, memory_type="user_preference", metadata={
        "persona_id": "persona", "owner_bot_id": "bot", "profile_dimension": "food_preference",
        "profile_value": "辣味", "normalized_value": "辣味", "profile_polarity": "positive",
        "profile_cardinality": "multi", "profile_state": "active", "quality_gate_passed": True,
        "extraction_quality": "explicit", "evidence_strength": "direct_statement", "extractor": "rule_v2",
        "canonical_summary": "旧口味", "key_facts": ["用户喜欢辣味"], "source_memory_id": "old-evidence",
    })
    with pytest.raises(MemoryRevisionError, match="structured_profile_value_required"):
        await correct(store, old)
    with pytest.raises(MemoryRevisionError, match="structured_profile_polarity_required"):
        await correct(store, old, profile_value="清淡")
    receipt = await correct(store, old, profile_value="清淡", profile_polarity="prefer")
    new = await store.get_memory(receipt["new_ref"]["id"])
    assert new.metadata["profile_value"] == new.metadata["normalized_value"] == "清淡"
    assert "辣味" not in repr(new.metadata)
    assert new.metadata["profile_polarity"] == "prefer"
    assert "canonical_summary" not in new.metadata and "source_memory_id" not in new.metadata
    assert profile_quality_decision({"memory_type": new.memory_type, "metadata": new.metadata}, require_active=True)[0]


@pytest.mark.asyncio
async def test_idempotency_rejects_changed_payload_and_unsupported_structure(store):
    old = await seeded(store)
    await correct(store, old)
    with pytest.raises(MemoryRevisionError, match="idempotency_conflict"):
        await correct(store, old, content="另一个事实")
    summary = await seeded(store, id="summary", memory_type="conversation_summary", content="一段旧摘要")
    with pytest.raises(MemoryRevisionError, match="memory_type_requires_domain_revision"):
        await correct(store, summary, correction_id="summary-change")
    assert current_memory(await store.get_memory(summary.id))


def test_versions_ignore_usage_bookkeeping_but_detect_evidence_and_validity_changes():
    old = record()
    before = memory_ref(old)
    old.injection_count = 10
    old.last_injected_at = "2026-09-12T12:00:00Z"
    old.updated_at = old.last_accessed_at = old.last_injected_at
    old.metadata.update(injection_count=10, last_injected_at=old.last_injected_at)
    assert memory_ref(old) == before
    assert memory_ref(replace(old, content="新的内容")) != before
    assert memory_ref(replace(old, validity_status="expired")) != before


@pytest.mark.asyncio
async def test_legacy_private_user_memory_retains_shared_persona_scope(store):
    old = await seeded(store, metadata={"owner_bot_id": "bot"})
    result = await correct(store, old)
    replacement = await store.get_memory(result["new_ref"]["id"])
    assert replacement.metadata["persona_id"] == ""


@pytest.mark.asyncio
async def test_rendered_cache_always_returns_to_current_retrieval_gate(store):
    from core.memory_revision import MemoryContext
    old = await seeded(store)
    service = MemoryCompanionService.__new__(MemoryCompanionService)
    service.store = store
    service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=context()))
    service.visibility_policy = lambda: VisibilityPolicy()
    service.config = SimpleNamespace(bool=lambda key, default: default, float=lambda key, default: 60.0)
    service._scope_feature_enabled = lambda *_: True
    service._mark_injected_memories = AsyncMock()
    text = MemoryContext("已缓存的有效参考", [memory_ref(old)])
    service._injection_cache = {context().session_id: (time.monotonic(), text, "private")}
    e, req = SimpleNamespace(), SimpleNamespace(prompt="用户消息", extra_user_content_parts=[])
    service._p5_gate = AsyncMock(return_value={"ok": False})
    await service.inject_memories(context(), req, event=e)
    assert not e.memory_companion_injection_state["injected"]
    assert e.memory_companion_continuity_snapshot is None
    assert "已缓存的有效参考" not in req.prompt
    service._p5_gate.assert_awaited_once()
    await correct(store, old)
    service._p5_gate = AsyncMock(side_effect=RuntimeError("fresh retrieval reached"))
    with pytest.raises(RuntimeError, match="fresh retrieval reached"):
        await service.inject_memories(context(), SimpleNamespace(prompt="新消息", extra_user_content_parts=[]), event=SimpleNamespace())
    service._p5_gate.assert_awaited_once()


def test_injection_refs_match_rendered_rows_and_do_not_follow_shared_diagnostics():
    item = record()
    composer = InjectionComposer()
    ids = []
    text = composer.compose(context(), [SearchResult(memory=item, score=0.95, reason="mention")],
                            max_chars=5000, included_memory_ids=ids)
    assert isinstance(text, str) and ids == [item.id] and text.memory_refs == [memory_ref(item)]
    tiny = composer.compose(context(), [SearchResult(memory=item, score=0.95, reason="mention")], max_chars=300)
    assert tiny.memory_refs == []
    assert text.memory_refs == [memory_ref(item)]


@pytest.mark.asyncio
async def test_bridge_uses_current_event_and_dependency_reads_only_return_scoped_states(store):
    old = await seeded(store)
    unrelated = await seeded(store, id="unrelated", content="用户喜欢安静")
    service = MemoryCompanionService.__new__(MemoryCompanionService)
    service.store = store
    service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=context()))
    service._scope_feature_enabled = lambda *_args: True
    service._p5_gate = AsyncMock(return_value={"ok": True})
    service.visibility_policy = lambda: VisibilityPolicy()
    service._schedule_memory_embedding = lambda *_args: None
    service._injection_cache = {context().session_id: "cached"}
    bridge = MemoryCompanionBridge(service)
    event = SimpleNamespace()
    inspected = await bridge.correct_user_memory(event=event, action="inspect", memory_id=old.id)
    assert inspected["memory_ref"] == serialize_memory(old)["memory_ref"]
    receipt = await bridge.correct_user_memory(event=event, action="correct", memory_id=old.id,
                                               expected_version=memory_ref(old)["version"], correction_id="change",
                                               content="用户喜欢清淡口味。")
    assert receipt["ok"] and not service._injection_cache
    checked = await bridge.check_memory_dependencies(event=event, refs=[memory_ref(old), memory_ref(unrelated), receipt["new_ref"]])
    assert [item["state"] for item in checked["items"]] == ["changed", "current", "current"]
    assert old.content not in repr(checked)
    assert receipt["new_ref"] in event.memory_companion_observed_refs
    service.identity.resolve_event_context.return_value = context(user_id="other", session_id="qq:FriendMessage:other")
    hidden = await bridge.check_memory_dependencies(event=event, refs=[receipt["new_ref"]])
    assert hidden["items"][0]["state"] == "unavailable"
    service.identity.resolve_event_context.return_value = context()
    denied = await bridge.correct_user_memory(event=SimpleNamespace(private_companion_proactive_framework=True),
                                              action="inspect", memory_id=receipt["new_ref"]["id"])
    assert denied["reason_code"] == "correction_scope_disabled"
