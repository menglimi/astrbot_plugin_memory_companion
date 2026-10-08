from __future__ import annotations

from dataclasses import replace
import json

import pytest

from core.continuity import (
    ContinuityContractError,
    QueryBudget,
    QueryOperation,
    QueryPlan,
    TimeWindow,
    build_context_snapshot,
)
from core.injection import InjectionComposer
from core.models import EntityRef, MemoryRecord, SearchResult, SessionContext


def context(**changes) -> SessionContext:
    value = SessionContext(
        scope="private",
        platform="qq",
        session_id="session-a",
        user_id="user-a",
        bot_id="bot-a",
        persona_id="persona-a",
        message_id="message-a",
        message_text="今天也来一杯。",
    )
    return replace(value, **changes)


def memory(**changes) -> MemoryRecord:
    value = MemoryRecord(
        id="memory-a",
        memory_type="user_preference",
        subject=EntityRef(kind="user", id="user-a"),
        object=EntityRef(kind="bot", id="bot-a"),
        scope="private",
        session_id="session-a",
        platform="qq",
        message_id="message-old",
        visibility="private_pair",
        lifecycle="stable_memory",
        content="用户最近喜欢喝咖啡。",
        evidence="我最近喜欢喝咖啡。",
        confidence=0.9,
        metadata={"persona_id": "persona-a", "owner_bot_id": "bot-a"},
    )
    return replace(value, **changes).ensure_defaults()


def test_relevant_plan_is_read_only_and_bounded() -> None:
    plan = QueryPlan(
        profile="continuity.relevant.v1",
        purpose="reply",
        scope_key="scope:abc",
        query_intent="承接用户刚才提到的饮品偏好",
        operations=(
            QueryOperation("search", "search_candidates", arguments={"query": "饮品偏好"}),
            QueryOperation("expand", "expand_source", depends_on=("search",)),
            QueryOperation("verify", "revalidate", depends_on=("expand",)),
        ),
    )
    payload = plan.to_dict()
    assert payload["schema"] == "memory.query-plan.v1"
    assert payload["budget"]["max_model_calls"] == 1
    assert all(item["operation"] != "write_memory" for item in payload["operations"])


def test_range_plan_requires_dependencies_to_be_declared_before_use() -> None:
    with pytest.raises(ContinuityContractError, match="operation_dependency_invalid"):
        QueryPlan(
            profile="continuity.range.v1",
            purpose="reply",
            scope_key="scope:abc",
            query_intent="列举一段时间内的早餐",
            operations=(
                QueryOperation("aggregate", "aggregate", depends_on=("rows",)),
                QueryOperation("rows", "range_read"),
            ),
        )


def test_pending_query_requires_current_session() -> None:
    with pytest.raises(ContinuityContractError, match="pending_requires_session"):
        QueryPlan(
            profile="continuity.relevant.v1",
            purpose="reply",
            scope_key="scope:abc",
            query_intent="查找本轮尚未确认的说法",
            include_pending=True,
            operations=(QueryOperation("search", "search_candidates"),),
        )


def test_snapshot_keeps_current_text_out_and_changes_revision_on_correction() -> None:
    first = build_context_snapshot(
        context(),
        memory_refs=[
            {
                "id": "memory-a",
                "version": "a" * 64,
                "source_ref": "message-old",
                "status": "active",
                "confidence": 0.9,
            }
        ],
        current_message="今天也来一杯。",
        session_revision=2,
        memory_revision="17",
        open_loops=["继续讨论饮品选择"],
    )
    corrected = build_context_snapshot(
        context(message_text="我最近戒咖啡了。", message_id="message-new"),
        memory_refs=[
            {
                "id": "memory-b",
                "version": "b" * 64,
                "source_ref": "message-new",
                "status": "active",
                "confidence": 1.0,
            }
        ],
        current_message="我最近戒咖啡了。",
        session_revision=3,
        memory_revision="18",
    )
    payload_text = json.dumps(first.to_dict(), ensure_ascii=False)
    assert "今天也来一杯" not in payload_text
    assert first.scope_key == corrected.scope_key
    assert first.context_revision != corrected.context_revision
    assert first.continuity_refs[0].source_ref == "message-old"


def test_cross_session_rebuild_keeps_owner_scope_but_not_session_state() -> None:
    first = build_context_snapshot(context(session_id="session-a"), memory_revision="17")
    second = build_context_snapshot(context(session_id="session-b"), memory_revision="17")
    assert first.scope_key == second.scope_key
    assert first.session_id != second.session_id
    assert first.context_revision != second.context_revision


def test_injection_attaches_snapshot_without_changing_legacy_text() -> None:
    item = memory()
    rendered = InjectionComposer().compose(
        context(),
        [SearchResult(memory=item, score=0.9, reason="relevant")],
        max_chars=1800,
    )
    assert isinstance(rendered, str)
    assert rendered.memory_refs and rendered.memory_refs[0]["id"] == item.id
    snapshot = rendered.continuity_snapshot
    assert snapshot["schema"] == "memory.context-snapshot.v1"
    assert snapshot["continuity_refs"][0]["ref_id"] == item.id
    assert "用户最近喜欢喝咖啡" not in json.dumps(snapshot, ensure_ascii=False)
