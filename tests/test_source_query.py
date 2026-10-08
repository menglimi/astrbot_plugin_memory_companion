from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from .test_reply_continuity import service
from core.models import SessionContext
pytestmark = pytest.mark.asyncio
CONTRACT_ROOT = Path(__file__).parents[1] / "docs/contracts/source-query/v1"
RESULT_VALIDATOR = Draft202012Validator(json.loads(
    (CONTRACT_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8")
))


@pytest.fixture
def ctx(service):
    value = SessionContext(session_id="qq:FriendMessage:source-user", scope="private", platform="qq",
                           user_id="source-user", bot_id="source-bot", persona_id="source-persona", message_id="source-turn")
    service.identity.resolve_event_context = AsyncMock(return_value=value)
    return value


async def add_row(service, ctx, text="这一餐是无糖拿铁", *, at="2026-09-08T00:00:00+08:00", **overrides):
    metadata = {"owner_bot_id": ctx.bot_id, "platform": ctx.platform, "persona_id": ctx.persona_id}
    metadata.update(overrides.pop("metadata", {}))
    params = dict(event_type="user_message", session_id=ctx.session_id, scope=ctx.scope,
                  subject_id=ctx.user_id, object_id=ctx.current_target_id,
                  content=text, occurred_at=at, metadata=metadata)
    params.update(overrides)
    return await service.store.add_timeline_event(**params)


async def sources(service, **kwargs):
    result = await service.tool_sources(SimpleNamespace(), **kwargs)
    RESULT_VALIDATOR.validate(result)
    return result


def refs(result):
    return [item["source_ref"].removeprefix("timeline:") for item in result["sources"]]


async def test_search_finds_raw_message_without_summary_and_has_no_write(service, ctx):
    target = await add_row(service, ctx)
    before = service.store._conn.total_changes
    result = await sources(service, terms=["无糖拿铁"])
    assert result["ok"] and refs(result) == [target]
    assert result["coverage"]["path"] == "fts5_trigram"
    assert result["coverage"]["event_coverage"] == "not_established"
    assert result["sources"][0]["message_at_local"] == "2026-09-08 00:00:00"
    assert result["usage"]["model_calls"] == 0
    assert service.store._conn.total_changes == before


async def test_short_terms_and_literal_fts_operators_work(service, ctx):
    short = await add_row(service, ctx, "早餐是粥")
    quoted = await add_row(service, ctx, '标签是 "OR" * (x)')
    result = await sources(service, terms=["早餐"])
    assert refs(result) == [short]
    assert result["coverage"]["path"] == "partition_substring"
    result = await sources(service, terms=['"OR" *'])
    assert refs(result) == [quoted]


async def test_term_list_uses_any_match_and_no_sql_execution(service, ctx):
    a = await add_row(service, ctx, "青苹果")
    b = await add_row(service, ctx, "红草莓")
    result = await sources(service, terms=["青苹果", "红草莓"])
    assert set(refs(result)) == {a, b}
    result = await sources(service, terms=["'; DROP TABLE timeline; --"])
    assert result["ok"] and not result["sources"]
    assert (await service.store.get_timeline_by_ids([a]))[a]["content"] == "青苹果"


async def test_hidden_matches_do_not_starve_authorized_candidate(service, ctx):
    target = await add_row(service, ctx)
    for index in range(18):
        await add_row(service, replace(ctx, user_id=f"other-{index}", session_id=f"qq:FriendMessage:other-{index}"))
    result = await sources(service, terms=["无糖拿铁"], limit=1)
    assert refs(result) == [target]
    assert result["next_cursor"] is None
    assert "other-" not in str(result)


@pytest.mark.parametrize("changes", [
    {"metadata": {"owner_bot_id": "another-bot"}}, {"metadata": {"platform": "other"}},
    {"metadata": {"persona_id": ""}}, {"metadata": {"persona_id": "other-persona"}},
    {"metadata": {"participant_user_id": "other"}}, {"object_id": "other"},
    {"subject_id": "other"}, {"scope": "group"}, {"session_id": "qq:FriendMessage:other"},
    {"event_type": "summary"},
])
async def test_search_excludes_wrong_source_ownership(service, ctx, changes):
    hidden = await add_row(service, ctx, **changes)
    result = await sources(service, terms=["无糖拿铁"])
    assert result["ok"] and not result["sources"]
    assert hidden not in str(result)


async def test_range_pages_use_absolute_time_and_stable_ties_without_duplicates(service, ctx):
    before = await add_row(service, ctx, "窗外", at="2026-09-07T15:59:59Z")
    end = await add_row(service, ctx, "上界", at="2026-09-09T00:00:00+08:00")
    expected = [await add_row(service, ctx, f"窗内 {i}", at="2026-09-07T16:00:00Z") for i in range(5)]
    result = await sources(service, action="range", start_at="2026-09-08T00:00:00+08:00",
                           end_at="2026-09-09T00:00:00+08:00", limit=2)
    found = refs(result)
    assert result["coverage"]["more_available"]
    while result["next_cursor"]:
        result = await sources(service, cursor=result["next_cursor"])
        assert result["ok"]
        found.extend(refs(result))
    assert len(found) == 5 and set(found) == set(expected)
    assert before not in found and end not in found
    assert result["usage"]["remaining_steps"] == 0


async def test_context_recovers_answer_without_search_terms(service, ctx):
    await add_row(service, ctx, "前一条", at="2026-09-08T01:00:00+08:00")
    question = await add_row(service, ctx, "那次吃的什么？", at="2026-09-08T01:01:00+08:00")
    answer = await add_row(service, ctx, "是豆浆和面包。", at="2026-09-08T01:02:00+08:00",
                           event_type="bot_response", subject_id=ctx.bot_id)
    await add_row(service, ctx, "后面的讨论", at="2026-09-08T01:03:00+08:00")
    result = await sources(service, action="context", source_ref=f"timeline:{question}", limit=3)
    assert answer in refs(result)
    assert [item["speaker_role"] for item in result["sources"]] == ["user", "user", "assistant"]
    cursor = result["context_cursors"]["after"]
    following = await sources(service, cursor=cursor)
    assert following["ok"] and not set(refs(following)) & set(refs(result))


async def test_context_never_substitutes_a_hidden_anchor(service, ctx):
    target = await add_row(service, replace(ctx, user_id="other", session_id="qq:FriendMessage:other"))
    result = await sources(service, action="context", source_ref=f"timeline:{target}")
    missing = await sources(service, action="context", source_ref="timeline:tl_missing")
    assert result["error"] == missing["error"] == "source_unavailable"
    assert not result["sources"] and target not in str(result)


async def page_with_cursor(service, ctx):
    keys = [await add_row(service, ctx, f"无糖拿铁 {i}") for i in range(3)]
    result = await sources(service, terms=["无糖拿铁"], limit=1)
    assert result["next_cursor"]
    return result["next_cursor"], keys


@pytest.mark.parametrize("change", ["insert", "update", "delete", "acl"])
async def test_cursor_invalidates_after_source_or_policy_change(service, ctx, change):
    cursor, keys = await page_with_cursor(service, ctx)
    if change == "insert":
        await add_row(service, ctx)
    elif change == "acl":
        await service.store.upsert_acl_rule(owner_scope="private", owner_id=ctx.user_id,
                                           reader_scope="group", reader_id="g1", effect="deny")
    else:
        with service.store._lock:
            service.store._conn.execute("DELETE FROM timeline WHERE id=?" if change == "delete" else "UPDATE timeline SET content='已修订' WHERE id=?", (keys[0],))
            service.store._conn.commit()
    result = await sources(service, cursor=cursor)
    assert not result["ok"] and result["error"] == "cursor_invalid"
    assert not result["sources"]


@pytest.mark.parametrize("change", ["message_id", "persona_id", "user_id", "platform", "bot_id"])
async def test_cursor_bound_to_host_turn_and_identity(service, ctx, change):
    cursor, _ = await page_with_cursor(service, ctx)
    service.identity.resolve_event_context.return_value = replace(ctx, **{change: "another"})
    result = await sources(service, cursor=cursor)
    assert result["error"] == "cursor_invalid"


async def test_pages_share_budget_with_regular_navigation(service, ctx):
    cursor, _ = await page_with_cursor(service, ctx)
    await service.tool_navigate(SimpleNamespace(), "search", query="一条线索")
    second = await sources(service, cursor=cursor)
    assert second["usage"]["remaining_steps"] == 0
    final = await sources(service, cursor=second["next_cursor"])
    assert final["error"] == "navigation step budget exhausted"


async def test_disabled_recall_and_cursor_expiry_return_no_sources(service, ctx):
    cursor, _ = await page_with_cursor(service, ctx)
    with patch.object(service, "_scope_feature_enabled", return_value=False):
        assert (await sources(service, cursor=cursor))["error"] == "scope_recall_disabled"
    for state in service._reconstruction_states.values():
        for entry in state.get("source_cursors", {}).values():
            entry["expires_at"] = 0
    assert (await sources(service, cursor=cursor))["error"] == "cursor_invalid"


async def test_source_change_during_read_does_not_return_stale_page(service, ctx):
    await add_row(service, ctx)
    real = service.store.query_source_page
    async def changed(*args, **kwargs):
        result = await real(*args, **kwargs)
        await add_row(service, ctx, "稍后补充")
        return result
    service.store.query_source_page = changed
    result = await sources(service, terms=["无糖拿铁"])
    assert result["error"] == "source_changed_retry" and not result["sources"]


async def test_cancellation_does_not_issue_cursor(service, ctx):
    service.store.query_source_page = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await sources(service, terms=["无糖拿铁"])
    assert not any(state.get("source_cursors") for state in service._reconstruction_states.values())


async def test_invalid_dates_and_filters_have_explicit_feedback(service, ctx):
    for params, error in [
        ({"terms": "早餐"}, "terms_must_be_array_up_to_6"),
        ({"action": "range", "start_at": "2026-09-08", "end_at": "2026-09-09"}, "time_requires_iso8601_with_timezone"),
        ({"terms": ["早餐"], "bot_id": "forged"}, "unknown_parameter"),
        ({"action": "aggregate"}, "unsupported_action"),
        ({"terms": ["早餐"], "limit": True}, "invalid_limit"),
    ]:
        result = await sources(service, **params)
        assert result["error"] == error and not result["sources"]


async def test_fts_tracks_edits_and_deletion(service, ctx):
    key = await add_row(service, ctx)
    with service.store._lock:
        service.store._conn.execute("UPDATE timeline SET content='早餐红草莓' WHERE id=?", (key,))
        service.store._conn.commit()
    assert not refs(await sources(service, terms=["无糖拿铁"]))
    assert refs(await sources(service, terms=["红草莓"])) == [key]
    with service.store._lock:
        service.store._conn.execute("DELETE FROM timeline WHERE id=?", (key,))
        service.store._conn.commit()
    assert not refs(await sources(service, terms=["早餐红草莓"]))


async def test_plain_fallback_remains_bounded_and_reports_truncation(service, ctx):
    key = await add_row(service, ctx, "无糖拿铁。" + "细节" * 600)
    service.store._source_fts_enabled = False
    result = await sources(service, terms=["无糖拿铁"])
    assert refs(result) == [key] and result["coverage"]["path"] == "partition_substring"
    assert len(result["sources"][0]["excerpt"]) <= 800
    assert result["coverage"]["excerpt_truncated_count"] == 1


async def test_search_shows_match_in_long_message_and_can_read_remaining_text(service, ctx):
    key = await add_row(service, ctx, "开头细节" * 300 + "唯一的银杏树线索" + "结尾内容" * 300)
    result = await sources(service, terms=["银杏树"])
    found = result["sources"][0]
    assert "银杏树" in found["excerpt"] and found["excerpt_offset"] > 0
    result = await sources(service, action="read", source_ref=f"timeline:{key}", excerpt_offset=found["next_excerpt_offset"])
    assert result["ok"] and result["sources"][0]["excerpt"].endswith("结尾内容")
    assert result["sources"][0]["excerpt_offset"] == found["next_excerpt_offset"]
    assert result["coverage"]["order"] == "single_message"


async def test_context_before_pages_keep_chronological_order(service, ctx):
    keys = [await add_row(service, ctx, f"第{i}条", at=f"2026-09-08T0{i}:00:00+08:00") for i in range(7)]
    result = await sources(service, action="context", source_ref=f"timeline:{keys[-1]}", direction="before", limit=2)
    assert refs(result) == keys[4:6]
    result = await sources(service, cursor=result["context_cursors"]["before"])
    assert refs(result) == keys[2:4]


async def test_context_index_range_keeps_equal_time_rows_and_tuple_paging(service, ctx):
    keys = [await add_row(service, ctx, f"并列消息 {i}") for i in range(7)]
    tied_created_at = "2026-09-08T00:00:00.000000+00:00"
    with service.store._lock:
        for key in keys:
            service.store._conn.execute("UPDATE timeline SET created_at=? WHERE id=?", (tied_created_at, key))
        service.store._conn.commit()
        ordered = [row[0] for row in service.store._conn.execute(
            "SELECT id FROM timeline WHERE session_id=? ORDER BY julianday(occurred_at),created_at,id",
            (ctx.session_id,),
        ).fetchall()]

    conn, lock = service.store._read_connection_for_bundle()
    statements = []
    with lock:
        conn.set_trace_callback(statements.append)
    try:
        result = await sources(service, action="context", source_ref=f"timeline:{ordered[3]}", limit=3)
    finally:
        with lock:
            conn.set_trace_callback(None)

    assert refs(result) == ordered[2:5]
    context_selects = [
        statement for statement in statements
        if "SELECT t.*,julianday(t.occurred_at) AS source_sort_time FROM timeline t WHERE" in statement
        and "ORDER BY julianday(t.occurred_at)" in statement
    ]
    assert any("julianday(t.occurred_at) <= " in statement for statement in context_selects)
    assert any("julianday(t.occurred_at) >= " in statement for statement in context_selects)
    with lock:
        plans = [
            [str(row[3]) for row in conn.execute("EXPLAIN QUERY PLAN " + statement).fetchall()]
            for statement in context_selects
        ]
    assert len(plans) == 2
    assert all(any("idx_timeline_source_page" in detail and "<expr>" in detail for detail in plan) for plan in plans)

    before = await sources(service, cursor=result["context_cursors"]["before"])
    after = await sources(service, cursor=result["context_cursors"]["after"])
    assert refs(before) == ordered[:2]
    assert refs(after) == ordered[5:]


async def test_cursor_does_not_accept_changed_query_and_cannot_repeat_page(service, ctx):
    cursor, _ = await page_with_cursor(service, ctx)
    result = await sources(service, cursor=cursor, terms=["另一条件"])
    assert result["error"] == "cursor_requires_no_query_parameters"
    assert (await sources(service, cursor=cursor))["ok"]
    assert (await sources(service, cursor=cursor))["error"] == "duplicate navigation call"


async def test_unknown_times_are_explicitly_excluded_but_direct_ref_read_works(service, ctx):
    key = await add_row(service, ctx, at="unknown")
    result = await sources(service, terms=["无糖拿铁"])
    assert not result["sources"] and result["coverage"]["unknown_message_time"] == "excluded_from_time_order"
    result = await sources(service, action="read", source_ref=f"timeline:{key}")
    assert result["ok"] and refs(result) == [key]


async def test_query_timeout_is_explicit_and_releases_read_transaction(service, ctx):
    from core.source_query import SourceQuery, SourceQueryError
    for index in range(40):
        await add_row(service, ctx, f"无糖拿铁 {index}")
    service.store._source_fts_enabled = False
    with patch("core.store.time.monotonic", side_effect=[0, 3, 3, 3, 3, 3]):
        with pytest.raises(SourceQueryError, match="source_query_timeout"):
            service.store._query_source_page_sync(ctx, SourceQuery.parse({"terms": ["不存在"]}), 6, None, None)
    assert not service.store._read_conn.in_transaction
    assert (await sources(service, terms=["无糖拿铁"]))["ok"]


async def test_group_context_is_scoped_before_candidate_limit(service, ctx):
    group = replace(ctx, scope="group", session_id="qq:GroupMessage:g1", group_id="g1")
    service.identity.resolve_event_context.return_value = group
    expected = await add_row(service, group)
    await add_row(service, replace(group, session_id="qq:GroupMessage:g2", group_id="g2"))
    result = await sources(service, terms=["无糖拿铁"], limit=1)
    assert refs(result) == [expected] and not result["next_cursor"]


@pytest.mark.parametrize("lost_table", [False, True])
async def test_new_index_rebuild_covers_existing_rows(service, ctx, lost_table):
    key = await add_row(service, ctx)
    with service.store._lock:
        if lost_table:
            service.store._conn.execute("DROP TABLE timeline_source_fts")
        else:
            service.store._conn.execute("INSERT INTO timeline_source_fts(timeline_source_fts) VALUES('delete-all')")
            service.store._conn.execute("DELETE FROM schema_metadata WHERE key='timeline_source_fts_version'")
        service.store._conn.commit()
        service.store._ensure_source_query_indexes_sync()
        service.store._conn.commit()
    assert refs(await sources(service, terms=["无糖拿铁"])) == [key]
