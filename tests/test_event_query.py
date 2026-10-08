from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from jsonschema import Draft202012Validator
import pytest

from core.event_query import CONTRACT_ROOT
from core.models import EntityRef, MemoryRecord
from .test_source_query import service, ctx, add_row, sources


pytestmark = pytest.mark.asyncio
RESULT = Draft202012Validator(json.loads((CONTRACT_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8")))
REQUEST = Draft202012Validator(json.loads((CONTRACT_ROOT / "schemas/request.schema.json").read_text(encoding="utf-8")))


def event_row(source, key="event-1", row_id="row-1", **changes):
    value = {"row_id": row_id, "event_key": key, "description": source["excerpt"],
             "subject": "current_user", "world": "real", "occurrence": "occurred",
             "relevance": "match", "identity": "clear", "resolution": "resolved",
             "time": {"kind": "relative_day", "source_ref": source["source_ref"], "days": 0, "timezone": "Asia/Shanghai"},
             "evidence": [{"source_ref": source["source_ref"], "source_version": source["source_version"], "quote": source["excerpt"]}]}
    value.update(changes)
    return value


def plan_for(rows, **changes):
    value = {"goal": "列出本人实际早餐", "unit": "同一顿早餐", "operation": "list", "timezone": "Asia/Shanghai",
             "select": {"subject": "current_user", "world": "real", "occurrences": ["occurred"]}, "rows": rows}
    value.update(changes)
    return value


async def events(service, plan):
    result = await service.tool_events(SimpleNamespace(), plan)
    RESULT.validate(result)
    return result


async def observed(service, ctx, text="今天早上喝了豆浆", **kwargs):
    key = await add_row(service, ctx, text, **kwargs)
    result = await sources(service, action="read", source_ref=f"timeline:{key}")
    assert result["ok"], result
    return result["sources"][0]


def relative(source, days):
    return {"kind": "relative_day", "source_ref": source["source_ref"], "days": days, "timezone": "Asia/Shanghai"}


async def test_week_from_design_deduplicates_corrects_and_reports_missing_days(service, ctx):
    fixture = [
        ("2026-09-07T12:10:00+08:00", "昨天早上吃了包子。"),
        ("2026-09-07T12:12:00+08:00", "就是刚说的昨天那顿包子，挺顶饱。"),
        ("2026-09-08T20:00:00+08:00", "明天早上打算吃吐司。"),
        ("2026-09-09T08:10:00+08:00", "今早出门前只喝了牛奶。"),
        ("2026-09-10T10:00:00+08:00", "小陈昨天早上也喝了牛奶。"),
        ("2026-09-10T12:00:00+08:00", "昨天早上那杯，我说牛奶是记错了，其实是豆浆。"),
        ("2026-09-12T08:00:00+08:00", "今天没吃早饭，只喝了水。"),
    ]
    keys = [await add_row(service, ctx, text, at=at) for at, text in fixture]
    page = await sources(service, action="range", start_at="2026-09-06T00:00:00+08:00", end_at="2026-09-13T00:00:00+08:00")
    found = page["sources"]
    page = await sources(service, cursor=page["next_cursor"])
    found += page["sources"]
    by_ref = {item["source_ref"].removeprefix("timeline:"): item for item in found}
    raw = [by_ref[key] for key in keys]
    rows = [
        event_row(raw[0], "meal-06", "r1", time=relative(raw[0], -1)),
        event_row(raw[1], "meal-06", "r2", time=relative(raw[1], -1)),
        event_row(raw[2], "plan-09", "r3", time=relative(raw[2], 1), occurrence="planned"),
        event_row(raw[3], "meal-09", "r4"),
        event_row(raw[4], "other-09", "r5", subject="other", time=relative(raw[4], -1)),
        event_row(raw[5], "meal-09", "r6", description="早上那杯是豆浆", time=relative(raw[5], -1), supersedes=["r4"]),
        event_row(raw[6], "no-meal-12", "r7", occurrence="not_occurred"),
    ]
    plan = plan_for(rows, operation="by_day", window={"start_at": "2026-09-06T00:00:00+08:00", "end_at": "2026-09-13T00:00:00+08:00"},
                    select={"subject": "current_user", "world": "real", "occurrences": ["occurred", "not_occurred"]})
    REQUEST.validate({"plan": plan})
    before = service.store._conn.total_changes
    result = await events(service, plan)
    assert result["ok"], result
    assert result["aggregate"]["count"] == 3
    assert result["aggregate"]["by_occurrence"] == {"occurred": 2, "not_occurred": 1}
    assert result["aggregate"]["days_without_resolved_events"] == ["2026-09-07", "2026-09-08", "2026-09-10", "2026-09-11"]
    assert result["aggregate"]["latest_candidates"] == ["no-meal-12"]
    assert len(result["excluded"]) == 2 and not result["unresolved"]
    corrected = next(item for item in result["events"] if item["event_key"] == "meal-09")
    assert corrected["descriptions"] == ["早上那杯是豆浆"] and corrected["superseded_row_ids"] == ["r4"]
    assert len(corrected["evidence"]) == 2
    assert result["coverage"]["event_coverage"] == "not_established"
    assert result["usage"]["remaining_steps"] == 0 and result["usage"]["model_calls"] == 0
    assert result["usage"]["memory_writes"] == 0 and service.store._conn.total_changes == before


async def test_latest_uses_event_date_not_newest_message(service, ctx):
    a = await add_row(service, ctx, "上周二喝了豆浆", at="2026-09-13T12:00:00+08:00")
    b = await add_row(service, ctx, "今天喝了咖啡", at="2026-09-12T08:00:00+08:00")
    found = (await sources(service, terms=["喝了"]))["sources"]
    first, second = {item["source_ref"]: item for item in found}[f"timeline:{a}"], {item["source_ref"]: item for item in found}[f"timeline:{b}"]
    result = await events(service, plan_for([
        event_row(first, "older", "r1", time={"kind": "date", "date": "2026-09-08", "timezone": "Asia/Shanghai", "source_ref": first["source_ref"]}),
        event_row(second, "latest", "r2"),
    ], operation="latest"))
    assert result["aggregate"]["latest_candidates"] == ["latest"]
    assert result["aggregate"]["earliest_candidates"] == ["older"]


async def test_overlapping_dates_return_multiple_latest_candidates(service, ctx):
    source = await observed(service, ctx, "今天吃过两顿，具体几点忘了")
    result = await events(service, plan_for([event_row(source, "first", "r1"), event_row(source, "second", "r2")], operation="latest"))
    assert result["aggregate"]["count"] == 2
    assert set(result["aggregate"]["latest_candidates"]) == {"first", "second"}


async def test_unknown_time_cannot_fill_range_but_can_count_scoped_supplied_events(service, ctx):
    source = await observed(service, ctx, "什么时候吃的忘了")
    row = event_row(source, time={"kind": "unknown"})
    window = {"start_at": "2026-09-08T00:00:00+08:00", "end_at": "2026-09-09T00:00:00+08:00"}
    result = await events(service, plan_for([row], window=window))
    assert result["aggregate"]["count"] == 0 and len(result["unresolved"]) == 1
    result = await events(service, plan_for([row], operation="count"))
    assert result["aggregate"]["count"] == 1 and result["aggregate"]["ordering"] == "unresolved"


@pytest.mark.parametrize("change", [
    {"occurrence": "planned"}, {"occurrence": "cancelled"}, {"subject": "other"}, {"world": "fictional"}, {"relevance": "not_match"},
])
async def test_semantic_selection_keeps_excluded_evidence_without_counting(service, ctx, change):
    source = await observed(service, ctx)
    result = await events(service, plan_for([event_row(source, **change)]))
    assert result["aggregate"]["count"] == 0 and len(result["excluded"]) == 1
    assert result["excluded"][0]["evidence"]


@pytest.mark.parametrize("change", [{"resolution": "conflicting"}, {"identity": "uncertain"}, {"subject": "unknown"}, {"occurrence": "unknown"}])
async def test_unresolved_semantics_are_not_silently_counted(service, ctx, change):
    source = await observed(service, ctx)
    result = await events(service, plan_for([event_row(source, **change)]))
    assert result["aggregate"]["count"] == 0 and len(result["unresolved"]) == 1


async def test_same_key_with_different_dates_is_conflict_not_one_precise_event(service, ctx):
    source = await observed(service, ctx, "我说的是两天中的某一天")
    result = await events(service, plan_for([event_row(source), event_row(source, row_id="row-2", time=relative(source, -1))]))
    assert result["aggregate"]["count"] == 0
    assert "event_time_conflict" in result["unresolved"][0]["reasons"]


@pytest.mark.parametrize("field", ["message_id", "user_id", "persona_id", "session_id", "platform", "bot_id"])
async def test_event_plan_cannot_reuse_another_turn_or_identity_receipts(service, ctx, field):
    source = await observed(service, ctx)
    service.identity.resolve_event_context.return_value = replace(ctx, **{field: "another"})
    result = await events(service, plan_for([event_row(source)]))
    assert result["error"] == "source_not_observed_this_turn_or_expired"


@pytest.mark.parametrize("change", ["insert", "update", "delete", "acl"])
async def test_changed_sources_or_policy_invalidate_calculation(service, ctx, change):
    source = await observed(service, ctx)
    if change == "insert":
        await add_row(service, ctx, "有新的资料")
    elif change == "acl":
        await service.store.upsert_acl_rule(owner_scope="private", owner_id=ctx.user_id, reader_scope="group", reader_id="g1", effect="deny")
    else:
        with service.store._lock:
            service.store._conn.execute("DELETE FROM timeline WHERE id=?" if change == "delete" else "UPDATE timeline SET content='改口了' WHERE id=?", (source["source_ref"][9:],))
            service.store._conn.commit()
    result = await events(service, plan_for([event_row(source)]))
    assert result["error"] == "source_changed_retry" and not result["events"]


async def test_unread_source_and_forged_quote_are_rejected(service, ctx):
    source = await observed(service, ctx)
    row = event_row(source)
    row["evidence"][0]["quote"] = "原文没有这句话"
    assert (await events(service, plan_for([row])))["error"] == "quote_not_in_observed_fragment"
    row["evidence"][0]["source_ref"] = "timeline:tl_unread"
    row["time"] = {"kind": "unknown"}
    assert (await events(service, plan_for([row])))["error"] == "source_not_observed_this_turn_or_expired"


async def test_quote_outside_observed_long_fragment_is_rejected(service, ctx):
    source = await observed(service, ctx, "开头" * 600 + "后半段未读证据")
    row = event_row(source, description="片段外引用")
    row["evidence"][0]["quote"] = "后半段未读证据"
    assert (await events(service, plan_for([row])))["error"] == "quote_not_in_observed_fragment"


async def test_source_hash_covers_tail_and_case(service, ctx):
    source = await observed(service, ctx, "前缀" * 600 + "CaseA")
    rows = await service.store.get_timeline_by_ids([source["source_ref"][9:]])
    row = rows[source["source_ref"][9:]]
    row["content"] = row["content"].replace("CaseA", "caseA")
    new = service._serialize_navigation_source(ctx, row)
    assert new["source_version"] != source["source_version"]


async def test_stale_during_validation_returns_no_calculation(service, ctx):
    source = await observed(service, ctx)
    read = service.store.get_timeline_by_ids
    async def changed(ids):
        rows = await read(ids)
        await add_row(service, ctx, "查询期间的新记录")
        return rows
    service.store.get_timeline_by_ids = changed
    result = await events(service, plan_for([event_row(source)]))
    assert result["error"] == "source_changed_retry" and not result["aggregate"]


async def test_budget_and_duplicate_calculation_are_shared_with_reads(service, ctx):
    source = await observed(service, ctx)
    plan = plan_for([event_row(source)])
    assert (await events(service, plan))["ok"]
    assert (await events(service, plan))["error"] == "duplicate navigation call"
    assert (await events(service, {**plan, "operation": "count"}))["ok"]
    assert (await events(service, {**plan, "operation": "latest"}))["error"] == "navigation step budget exhausted"


async def test_expired_disabled_and_cancelled_calculations_return_no_facts(service, ctx):
    source = await observed(service, ctx)
    plan = plan_for([event_row(source)])
    with patch.object(service, "_scope_feature_enabled", return_value=False):
        assert (await events(service, plan))["error"] == "scope_recall_disabled"
    service.store.get_timeline_by_ids = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await events(service, plan)
    for state in service._reconstruction_states.values():
        for receipt in state["issued_sources"].values():
            receipt["expires_at"] = 0
    assert (await events(service, plan))["error"] == "source_not_observed_this_turn_or_expired"


async def test_navigation_sources_can_feed_event_calculation(service, ctx):
    key = await add_row(service, ctx)
    summary = MemoryRecord(
        id="summary", memory_type="conversation_summary",
        subject=EntityRef(kind="user", id=ctx.user_id), object=EntityRef.bot_self(ctx.bot_id),
        scope=ctx.scope, session_id=ctx.session_id, platform=ctx.platform,
        visibility="private_pair", sayability="direct", reality_level="llm_summary",
        lifecycle="stable_memory", content="早餐喝了无糖拿铁。", evidence="早餐记录。",
        confidence=0.9, importance=0.8, occurred_at="2026-09-13T00:00:00+08:00",
        metadata={"owner_bot_id": ctx.bot_id, "persona_id": ctx.persona_id, "source_event_ids": [key]},
    )
    await service.store.insert_memory(summary)
    revision = await service.store.memory_revision()
    result = await service.tool_navigate(SimpleNamespace(), "event_time", memory_ids=[summary.id])
    assert result["ok"] and result["evidence"][0]["sources"][0]["source_ref"] == f"timeline:{key}"
    assert (await service.store.get_memory(summary.id)).access_count == 1
    assert await service.store.memory_revision() == revision
    result = await events(service, plan_for([event_row(result["evidence"][0]["sources"][0])]))
    assert result["ok"] and result["aggregate"]["count"] == 1
    assert result["events"][0]["time"]["start_at"] == "2026-09-07T16:00:00+00:00"
    assert result["events"][0]["time"]["end_at"] == "2026-09-08T16:00:00+00:00"
    assert result["coverage"]["source_reads"][0]["selection"] == "navigation_references"


async def test_relative_day_uses_historical_local_anchor_and_dst(service, ctx):
    source = await observed(service, ctx, "昨天的那顿", at="2026-03-09T04:30:00Z")
    row = event_row(source, time={"kind": "relative_day", "source_ref": source["source_ref"], "days": -1, "timezone": "America/New_York"})
    result = await events(service, plan_for([row], timezone="America/New_York"))
    assert result["events"][0]["time"]["start_at"] == "2026-03-08T05:00:00+00:00"
    assert result["events"][0]["time"]["end_at"] == "2026-03-09T04:00:00+00:00"


async def test_window_overlap_stays_unresolved_and_upper_boundary_excluded(service, ctx):
    source = await observed(service, ctx)
    window = {"start_at": "2026-09-08T08:00:00+08:00", "end_at": "2026-09-08T09:00:00+08:00"}
    row1 = event_row(source, "day", "r1")
    row2 = event_row(source, "edge", "r2", time={"kind": "instant", "at": window["end_at"], "source_ref": source["source_ref"]})
    result = await events(service, plan_for([row1, row2], window=window))
    assert result["aggregate"]["count"] == 0
    assert len(result["unresolved"]) == len(result["excluded"]) == 1


async def test_plan_correction_references_reject_cycle_and_cross_event(service, ctx):
    source = await observed(service, ctx)
    a, b = event_row(source, row_id="a"), event_row(source, row_id="b")
    a["supersedes"], b["supersedes"] = ["b"], ["a"]
    assert (await events(service, plan_for([a, b])))["error"] == "cyclic_correction"
    b["supersedes"], b["event_key"] = [], "other-event"
    assert (await events(service, plan_for([a, b])))["error"] == "correction_requires_same_event"


async def test_plan_size_and_invalid_calendar_are_explicit(service, ctx):
    source = await observed(service, ctx)
    row = event_row(source)
    assert (await events(service, {**plan_for([row]), "owner_id": "forged"}))["error"] == "invalid_plan_shape"
    assert (await events(service, {**plan_for([row]), "goal": "大" * 48001}))["error"] == "event_plan_too_large"
    row["time"] = {"kind": "date", "date": "2026-02-30", "source_ref": source["source_ref"], "timezone": "Asia/Shanghai"}
    assert (await events(service, plan_for([row])))["error"] == "invalid_event_date"


async def test_receipt_expiry_is_not_extended_by_reading_another_fragment(service, ctx):
    source = await observed(service, ctx, "开头" * 700 + "末尾")
    receipt = next(iter(service._reconstruction_states.values()))["issued_sources"][source["source_ref"]]
    first_expiry = receipt["expires_at"]
    await sources(service, action="read", source_ref=source["source_ref"], excerpt_offset=800)
    assert receipt["expires_at"] == first_expiry
    assert len(receipt["spans"]) == 2


async def test_other_authorized_but_unread_record_cannot_be_cited(service, ctx):
    key = await add_row(service, ctx)
    raw = (await service.store.get_timeline_by_ids([key]))[key]
    source = service._serialize_navigation_source(ctx, raw)
    result = await events(service, plan_for([event_row(source)]))
    assert result["error"] == "source_not_observed_this_turn_or_expired"


async def test_runtime_reset_while_revalidating_invalidates_result(service, ctx):
    source = await observed(service, ctx)
    read = service.store.get_timeline_by_ids
    async def cleared(ids):
        rows = await read(ids)
        service._reconstruction_states.clear()
        return rows
    service.store.get_timeline_by_ids = cleared
    result = await events(service, plan_for([event_row(source)]))
    assert result["error"] == "source_not_observed_this_turn_or_expired"


async def test_large_daily_window_returns_explicit_grid_gap(service, ctx):
    source = await observed(service, ctx)
    result = await events(service, plan_for([event_row(source)], operation="by_day", window={
        "start_at": "2026-01-01T00:00:00+08:00", "end_at": "2027-01-01T00:00:00+08:00",
    }))
    assert result["aggregate"]["day_grid"] == "omitted_over_31_days"
    assert not result["aggregate"]["days_without_resolved_events"]
    assert result["aggregate"]["count"] == 1


async def test_unknown_message_time_is_not_replaced_with_query_time(service, ctx):
    source = await observed(service, ctx, at="unknown")
    result = await events(service, plan_for([event_row(source)], operation="latest"))
    assert result["events"][0]["time"] is None
    assert not result["aggregate"]["latest_candidates"]
    assert result["aggregate"]["ordering"] == "unresolved"
