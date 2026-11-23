from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.astrbot_compat import (
    clean_private_companion_history_text,
    retrieval_history_text,
)
from core.classifier import MemoryClassifier
from core.forward_extractor import (
    FORWARD_FALLBACK_PLACEHOLDER,
    SHARED_EXTRA_KEY,
    TIMELINE_FORWARD_MAX_CHARS,
    extract_forwards,
    format_forward_timeline_text,
)
from core.models import SessionContext, json_loads
from core.service import MemoryCompanionService
from core.summarizer import MemorySummarizer

pytestmark = pytest.mark.asyncio


class Plain:
    type = "Plain"

    def __init__(self, text: str) -> None:
        self.text = text


class Forward:
    type = "Forward"

    def __init__(self, id: str = "", nodes: list | None = None) -> None:
        self.id = id
        if nodes is not None:
            self.nodes = nodes


class Node:
    type = "Node"

    def __init__(self, name: str = "", uin: str = "", content: list | None = None) -> None:
        self.name = name
        self.uin = uin
        self.content = content if content is not None else []


class Nodes:
    type = "Nodes"

    def __init__(self, nodes: list[Node]) -> None:
        self.nodes = nodes


class At:
    type = "At"

    def __init__(self, qq: str = "", name: str = "") -> None:
        self.qq = qq
        self.name = name


class Face:
    type = "Face"

    def __init__(self, id: int = 1) -> None:
        self.id = id


class Image:
    type = "Image"

    def __init__(self, url: str = "") -> None:
        self.url = url


class File:
    type = "File"

    def __init__(self, name: str = "") -> None:
        self.name = name


class Reply:
    type = "Reply"

    def __init__(self, id: str = "", sender_id: str = "") -> None:
        self.id = id
        self.sender_id = sender_id


class _FakeEvent:
    def __init__(
        self,
        *,
        message_str: str = "",
        components: list | None = None,
        message_id: str = "msg_001",
        timestamp: float | None = None,
        user_id: str = "u_alice",
        user_name: str = "Alice",
        group_id: str = "",
        group_name: str = "",
        bot_id: str = "bot_main",
        platform: str = "aiocqhttp",
        persona_id: str = "persona_default",
        call_action=None,
        extras: dict | None = None,
    ) -> None:
        self.message_str = message_str
        self._user_id = user_id
        self._user_name = user_name
        self._group_id = group_id
        self._group_name = group_name
        self._bot_id = bot_id
        self._platform = platform
        self.persona_id = persona_id
        self.unified_msg_origin = (
            f"{platform}:GroupMessage:{group_id}"
            if group_id
            else f"{platform}:FriendMessage:{user_id}"
        )
        ts = timestamp if timestamp is not None else datetime(2026, 11, 23, 3, 53, 25, tzinfo=timezone.utc).timestamp()
        self.message_obj = SimpleNamespace(
            message_id=message_id,
            message=list(components or []),
            timestamp=ts,
            raw_message={},
        )
        self._extras: dict = dict(extras or {})
        self.bot = SimpleNamespace(api=SimpleNamespace(call_action=call_action)) if call_action is not None else None

    def get_message_str(self) -> str:
        return self.message_str

    def get_messages(self) -> list:
        return list(self.message_obj.message)

    def get_sender_id(self) -> str:
        return self._user_id

    def get_sender_name(self) -> str:
        return self._user_name

    def get_group_id(self) -> str:
        return self._group_id

    def get_group_name(self) -> str:
        return self._group_name

    def get_self_id(self) -> str:
        return self._bot_id

    def get_platform_name(self) -> str:
        return self._platform

    def get_extra(self, key: str, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key: str, value) -> None:
        self._extras[key] = value


@pytest.fixture
async def svc(tmp_path: Path):
    service = MemoryCompanionService(
        context=SimpleNamespace(),
        config={
            "memory_capture": {
                "enabled": True,
                "reliable_sources_enabled": True,
                "source_capture_enabled": True,
                "capture_user_messages": True,
                "extract_stable_facts": True,
                "proposal_mode": "hybrid",
            },
            "conversation_memory": {
                "enabled": True,
                "capture_private_messages": True,
                "capture_group_messages": True,
                "group_capture_engagement_only": True,
            },
            "memory_reconstruction": {"enabled": True},
            "memory_tools": {"enable_reconstruction_tool": True},
            "memory_summary": {"enabled": False},
            "source_semantic": {"enabled": False},
            "retrieval": {"embedding_enabled": False},
        },
        plugin_root=Path(__file__).resolve().parents[1],
        data_dir=tmp_path,
    )
    await service.initialize_database()
    yield service
    service.close()


async def _collect_all_range_sources(
    svc: MemoryCompanionService,
    event: _FakeEvent,
    *,
    start_at: str,
    end_at: str,
) -> list[dict]:
    collected: list[dict] = []
    res = await svc.tool_sources(
        event,
        action="range",
        start_at=start_at,
        end_at=end_at,
    )
    assert res["ok"] is True
    collected.extend(res["sources"])
    while res.get("next_cursor"):
        res = await svc.tool_sources(event, cursor=res["next_cursor"])
        assert res["ok"] is True
        collected.extend(res["sources"])
    return collected


async def test_extract_forwards_reuses_shared_cache_with_zero_rpc():
    rpc = AsyncMock(side_effect=AssertionError("get_forward_msg must not be called on cache hit"))
    cached_payload = {
        "version": 1,
        "source": "private_companion",
        "cards": [
            {
                "forward_id": "fwd_cached_1",
                "message_id": "msg_c1",
                "node_count": 2,
                "truncated": False,
                "summary_text": "林川: 周末去爬山\n苏晴: 记得带外套",
            }
        ],
        "combined_text": "林川: 周末去爬山\n苏晴: 记得带外套",
        "total_nodes": 2,
        "truncated": False,
    }
    event = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_cached_1")],
        call_action=rpc,
        extras={SHARED_EXTRA_KEY: cached_payload},
    )

    parsed = await extract_forwards(event)
    assert parsed is not None
    assert parsed.source == "private_companion"
    assert len(parsed.cards) == 1
    assert parsed.cards[0].forward_id == "fwd_cached_1"
    assert parsed.cards[0].message_id == "msg_c1"
    assert parsed.total_nodes == 2
    assert "周末去爬山" in parsed.combined_text
    assert rpc.await_count == 0


async def test_extract_forwards_standalone_rpc_degrades_segments_nests_and_caches():
    calls: list[tuple[str, dict]] = []

    async def fake_call_action(action: str, **kwargs):
        calls.append((action, kwargs))
        fid = str(kwargs.get("id") or kwargs.get("message_id") or "")
        if fid == "fwd_root":
            return {
                "messages": [
                    {
                        "type": "node",
                        "data": {
                            "nickname": "甲同学",
                            "user_id": "1001",
                            "content": [
                                {"type": "text", "data": {"text": "看下附件"}},
                                {"type": "face", "data": {"id": 14}},
                                {"type": "at", "data": {"qq": "1002", "name": "乙同学"}},
                                {"type": "file", "data": {"name": "行程表.pdf"}},
                                {"type": "reply", "data": {"id": "999"}},
                                {"type": "image", "data": {"url": "https://example.invalid/pic.png"}},
                                {"type": "unknown_widget", "data": {}},
                            ],
                        },
                    },
                    {
                        "type": "node",
                        "data": {
                            "nickname": "乙同学",
                            "user_id": "1002",
                            "content": [{"type": "forward", "data": {"id": "fwd_nested"}}],
                        },
                    },
                ]
            }
        if fid == "fwd_nested":
            return {
                "data": {
                    "messages": [
                        {
                            "sender": {"nickname": "丙同学", "user_id": "1003"},
                            "message": [
                                {"type": "text", "data": {"text": "嵌套记录：明天九点集合"}},
                                # Cycle back to root must not loop infinitely.
                                {"type": "forward", "data": {"id": "fwd_root"}},
                            ],
                        }
                    ]
                }
            }
        return {}

    event = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_root")],
        message_id="msg_standalone",
        call_action=fake_call_action,
    )

    first = await extract_forwards(event)
    assert first is not None
    assert first.source == "memory_companion"
    assert first.total_nodes == 3
    assert len(calls) == 2
    text = first.combined_text
    assert "甲同学: 看下附件" in text
    assert "[表情]" in text
    assert "[@乙同学]" in text
    assert "[文件:行程表.pdf]" in text
    assert "[回复]" in text
    assert "[图片]" in text
    assert "丙同学: 嵌套记录：明天九点集合" in text
    assert "[嵌套转发消息]" in text
    assert first.image_urls == ("https://example.invalid/pic.png",)

    # Cached back onto event: second extraction makes 0 additional RPC calls.
    assert isinstance(event.get_extra(SHARED_EXTRA_KEY), dict)
    second = await extract_forwards(event)
    assert second is not None
    assert len(calls) == 2


async def test_extract_forwards_timeout_and_failure_degrade_to_safe_placeholder():
    async def slow_call_action(action: str, **kwargs):
        await asyncio.sleep(0.4)
        return {"messages": []}

    timeout_event = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_slow")],
        message_id="msg_timeout",
        call_action=slow_call_action,
    )
    parsed_timeout = await extract_forwards(timeout_event, timeout_seconds=0.06)
    assert parsed_timeout is not None
    assert len(parsed_timeout.cards) == 1
    assert parsed_timeout.cards[0].fallback is True
    assert parsed_timeout.cards[0].summary_text == FORWARD_FALLBACK_PLACEHOLDER
    assert format_forward_timeline_text(parsed_timeout) == FORWARD_FALLBACK_PLACEHOLDER

    async def broken_call_action(action: str, **kwargs):
        raise RuntimeError("onebot disconnected")

    broken_event = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_err")],
        message_id="msg_err",
        call_action=broken_call_action,
    )
    parsed_broken = await extract_forwards(broken_event)
    assert parsed_broken is not None
    assert parsed_broken.cards[0].fallback is True
    assert parsed_broken.cards[0].summary_text == FORWARD_FALLBACK_PLACEHOLDER


async def test_extract_forwards_handles_inline_nodes_without_rpc():
    rpc = AsyncMock(side_effect=AssertionError("inline Nodes should not call RPC"))
    inline = Nodes(
        [
            Node(name="阿哲", uin="201", content=[Plain("周五晚上看电影"), Face(2)]),
            Node(name="小雨", uin="202", content=[Plain("好，买八点场的票")]),
        ]
    )
    event = _FakeEvent(message_str="", components=[inline], message_id="msg_inline", call_action=rpc)
    parsed = await extract_forwards(event)
    assert parsed is not None
    assert parsed.total_nodes == 2
    assert "阿哲: 周五晚上看电影 [表情]" in parsed.combined_text
    assert "小雨: 好，买八点场的票" in parsed.combined_text
    assert rpc.await_count == 0


async def test_pure_forward_captured_by_capture_runtime_and_found_by_sources_range(svc: MemoryCompanionService):
    ts = datetime(2026, 11, 23, 3, 53, 25, tzinfo=timezone.utc).timestamp()

    async def fake_rpc(action: str, **kwargs):
        return {
            "messages": [
                {"sender": {"nickname": "路人甲"}, "message": [{"type": "text", "data": {"text": "下周四发布新版本"}}]},
                {"sender": {"nickname": "路人乙"}, "message": [{"type": "text", "data": {"text": "收到，我先写变更清单"}}]},
            ]
        }

    event = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_solo_01")],
        message_id="msg_solo_01",
        timestamp=ts,
        call_action=fake_rpc,
    )

    receipt = await svc.capture.incoming(event)
    assert receipt is not None
    assert receipt["status"] == "committed"
    assert receipt["source_state"] == "current"

    # Stored in capture_sources & full original body readable.
    stored = svc.capture.read_original(receipt["source_key"])
    assert stored["ok"] is True
    assert "下周四发布新版本" in stored["body"]
    assert "收到，我先写变更清单" in stored["body"]

    # Idempotent replay on a fresh event with empty message_id deduplicates by forward_id.
    event_no_mid_1 = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_dedupe_99")],
        message_id="",
        timestamp=ts + 1,
        call_action=fake_rpc,
    )
    event_no_mid_2 = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_dedupe_99")],
        message_id="",
        timestamp=ts + 1,
        call_action=fake_rpc,
    )
    event_no_mid_3 = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_dedupe_99")],
        message_id="",
        timestamp=ts + 5,
        call_action=fake_rpc,
    )
    r1 = await svc.capture.incoming(event_no_mid_1)
    r2 = await svc.capture.incoming(event_no_mid_2)
    r3 = await svc.capture.incoming(event_no_mid_3)
    assert r1 is not None and r2 is not None and r3 is not None
    assert r2["status"] == "committed" and r1["source_key"] == r2["source_key"]
    assert r3["status"] == "conflict" and r3["operation"] == r1["operation"]
    assert svc.store._conn.execute("SELECT COUNT(*) FROM capture_sources").fetchone()[0] == 2

    # memory_companion_sources(action="range") finds the pure-forward capture cleanly.
    query_event = _FakeEvent(message_str="你看到刚才那条转发了吗", message_id="msg_query", timestamp=ts + 30)
    res = await svc.tool_sources(
        query_event,
        action="range",
        start_at="2026-11-23T11:40:00+08:00",
        end_at="2026-11-23T12:00:00+08:00",
    )
    assert res["ok"] is True
    excerpts = "\n".join(item.get("excerpt", "") for item in res["sources"])
    assert "下周四发布新版本" in excerpts
    assert len(res["sources"]) == 2  # msg_solo_01 + deduped fwd_dedupe_99


async def test_eight_consecutive_forwards_observer_and_debounced_aggregation_all_recalled(svc: MemoryCompanionService):
    base_ts = datetime(2026, 11, 23, 3, 53, 21, tzinfo=timezone.utc).timestamp()

    # Scenario A: 8 debounced cards aggregated onto the follow-up user turn via _astrbot_parsed_forwards.
    cards = [
        {
            "forward_id": f"fwd_burst_{i}",
            "message_id": f"msg_burst_{i}",
            "node_count": 2,
            "truncated": False,
            "timestamp": datetime.fromtimestamp(base_ts + i, timezone.utc).isoformat(),
            "summary_text": f"同学A: 第{i}份聊天记录主题-{i * 11}\n同学B: 第{i}份补充细节",
        }
        for i in range(1, 9)
    ]
    shared_payload = {
        "version": 1,
        "source": "private_companion",
        "cards": cards,
        "combined_text": "\n".join(c["summary_text"] for c in cards),
        "total_nodes": 16,
        "truncated": False,
    }
    rpc_guard = AsyncMock(side_effect=AssertionError("must reuse shared cache without RPC"))
    aggregated_event = _FakeEvent(
        message_str="你看到我刚发的那 8 条聊天记录了吗",
        components=[Plain("你看到我刚发的那 8 条聊天记录了吗")],
        message_id="msg_followup_9",
        timestamp=base_ts + 60,
        call_action=rpc_guard,
        extras={SHARED_EXTRA_KEY: shared_payload},
    )

    receipt = await svc.capture.incoming(aggregated_event)
    assert receipt is not None
    assert receipt["status"] == "committed"
    assert len(getattr(aggregated_event, "_memory_capture_receipts", [])) == 9  # 8 cards + 1 user question
    assert rpc_guard.await_count == 0

    # Replaying the exact same aggregated payload on a fresh event commits 0 duplicate capture_sources rows.
    replay_event = _FakeEvent(
        message_str="你看到我刚发的那 8 条聊天记录了吗",
        components=[Plain("你看到我刚发的那 8 条聊天记录了吗")],
        message_id="msg_followup_9",
        timestamp=base_ts + 60,
        call_action=rpc_guard,
        extras={SHARED_EXTRA_KEY: shared_payload},
    )
    await svc.capture.incoming(replay_event)
    capture_count = svc.store._conn.execute("SELECT COUNT(*) FROM capture_sources").fetchone()[0]
    assert capture_count == 9

    # memory_companion_sources(action="range") retrieves ALL 8 forwarded records + follow-up question across pages.
    all_sources = await _collect_all_range_sources(
        svc,
        aggregated_event,
        start_at="2026-11-23T11:40:00+08:00",
        end_at="2026-11-23T12:00:00+08:00",
    )
    assert len(all_sources) == 9
    joined = "\n".join(item["excerpt"] for item in all_sources)
    for i in range(1, 9):
        assert f"第{i}份聊天记录主题-{i * 11}" in joined


async def test_observer_captures_eight_separate_pure_forwards_with_bounds_and_dedupe(svc: MemoryCompanionService):
    base_ts = datetime(2026, 11, 23, 3, 53, 21, tzinfo=timezone.utc).timestamp()

    for i in range(1, 9):
        long_body = f"路人{i}: " + (f"关于活动安排{i}的详细说明，" * 90)
        ev = _FakeEvent(
            message_str="",
            components=[Forward(id=f"fwd_obs_{i}")],
            message_id=f"msg_obs_{i}",
            timestamp=base_ts + i,
            extras={
                SHARED_EXTRA_KEY: {
                    "version": 1,
                    "source": "astrbot_core",
                    "cards": [
                        {
                            "forward_id": f"fwd_obs_{i}",
                            "message_id": f"msg_obs_{i}",
                            "node_count": 3,
                            "truncated": False,
                            "summary_text": long_body,
                        }
                    ],
                    "combined_text": long_body,
                    "total_nodes": 3,
                    "truncated": False,
                }
            },
        )
        await svc.handle_group_message(ev)
        # Re-observing the same message_id must deduplicate cleanly.
        await svc.handle_group_message(ev)

    rows = await svc.store.recent_timeline(
        limit=20,
        scope="private",
        session_id="aiocqhttp:FriendMessage:u_alice",
        entity_id="u_alice",
    )
    assert len(rows) == 8
    for row in rows:
        assert row["content"].startswith("[合并转发聊天记录(3条)]")
        assert len(row["content"]) <= TIMELINE_FORWARD_MAX_CHARS
        meta = json_loads(row["metadata"], {})
        assert meta["has_forward"] is True
        assert meta["forward_count"] == 1
        assert meta["forward_only"] is True

    # Also queryable via memory_companion_sources(action="range") even without on_llm_request!
    query_ev = _FakeEvent(message_str="查一下", message_id="msg_q_obs")
    all_obs_sources = await _collect_all_range_sources(
        svc,
        query_ev,
        start_at="2026-11-23T00:00:00+00:00",
        end_at="2026-11-24T00:00:00+00:00",
    )
    assert len(all_obs_sources) == 8


async def test_third_party_speech_in_forward_never_contaminates_user_profile_or_facts(svc: MemoryCompanionService):
    third_party_claims = (
        "陌生人甲: 我住在火星基地，我叫王铁柱，我对花生严重过敏，我最喜欢吃榴莲披萨，我是航天工程师\n"
        "陌生人乙: 我今年35岁，我养了一只叫大黄的金毛"
    )
    cached = {
        "version": 1,
        "source": "private_companion",
        "cards": [
            {
                "forward_id": "fwd_attr_1",
                "message_id": "msg_attr_1",
                "node_count": 2,
                "truncated": False,
                "summary_text": third_party_claims,
            }
        ],
        "combined_text": third_party_claims,
        "total_nodes": 2,
        "truncated": False,
    }

    portrait_spy = AsyncMock(return_value={"ok": True, "facts": 0})
    svc.portraits.capture_user_message = portrait_spy

    # 1) Pure forward through observer AND _capture_async must produce ZERO derived user profile memories.
    pure_event = _FakeEvent(
        message_str="",
        components=[Forward(id="fwd_attr_1")],
        message_id="msg_attr_1",
        extras={SHARED_EXTRA_KEY: cached},
    )
    await svc.handle_group_message(pure_event)
    assert portrait_spy.await_count == 0

    ctx_pure = await svc.identity.resolve_event_context(pure_event)
    assert ctx_pure.message_text == ""
    await svc.capture.incoming(pure_event, ctx_pure)
    await svc._capture_async(ctx_pure, pure_event, SimpleNamespace(), [])
    assert portrait_spy.await_count == 0

    all_memories = svc.store._conn.execute("SELECT content, memory_type FROM memories").fetchall()
    assert all_memories == []

    # 2) Mixed message: only user's own Plain utterance is evaluated by classifier, NEVER forwarded third-party claims.
    mixed_event = _FakeEvent(
        message_str="我喜欢喝无糖乌龙茶，你看群里这段聊天",
        components=[Plain("我喜欢喝无糖乌龙茶，你看群里这段聊天"), Forward(id="fwd_attr_2")],
        message_id="msg_attr_2",
        extras={
            SHARED_EXTRA_KEY: {
                **cached,
                "cards": [{**cached["cards"][0], "forward_id": "fwd_attr_2", "message_id": "msg_attr_2"}],
            }
        },
    )
    ctx_mixed = await svc.identity.resolve_event_context(mixed_event)
    assert ctx_mixed.message_text == "我喜欢喝无糖乌龙茶，你看群里这段聊天"
    await svc.capture.incoming(mixed_event, ctx_mixed)
    await svc._capture_async(ctx_mixed, mixed_event, SimpleNamespace(), [])

    mixed_memories = [
        row["content"]
        for row in svc.store._conn.execute("SELECT content FROM memories").fetchall()
    ]
    joined_mem = "\n".join(mixed_memories)
    for forbidden in ("火星基地", "王铁柱", "花生", "榴莲披萨", "航天工程师", "大黄"):
        assert forbidden not in joined_mem

    # 3) Direct defense-in-depth on MemoryClassifier even if a caller passes combined text.
    classifier = MemoryClassifier()
    direct_ctx = SessionContext(
        session_id="aiocqhttp:FriendMessage:u_alice",
        scope="private",
        platform="aiocqhttp",
        user_id="u_alice",
        user_name="Alice",
        bot_id="bot_main",
        message_text=f"我喜欢喝乌龙茶\n[合并转发聊天记录(2条)] {third_party_claims}",
    )
    derived = classifier.derived_user_memories(direct_ctx)
    derived_text = "\n".join(item.content for item in derived)
    for forbidden in ("火星基地", "王铁柱", "花生", "榴莲披萨", "航天工程师", "大黄"):
        assert forbidden not in derived_text

    pure_digest_ctx = SessionContext(
        session_id="aiocqhttp:FriendMessage:u_alice",
        scope="private",
        platform="aiocqhttp",
        user_id="u_alice",
        user_name="Alice",
        bot_id="bot_main",
        message_text=f"[合并转发聊天记录(2条)] {third_party_claims}",
    )
    assert classifier.from_user_message(pure_digest_ctx) is None
    assert classifier.derived_user_memories(pure_digest_ctx) == []


async def test_summarizer_marks_forward_timeline_rows_with_forwarded_chat_log_hint():
    summarizer = MemorySummarizer()
    observer_row = {
        "id": "tl_fwd_obs",
        "event_type": "user_message",
        "scope": "private",
        "subject_id": "u_alice",
        "occurred_at": "2026-11-23T03:53:25+00:00",
        # Contains "不对" inside third-party forwarded speech: must NOT be mislabeled as user_correction!
        "content": "[合并转发聊天记录(2条)] 路人甲: 不对，我是说我住在东京 | 路人乙: 收到",
        "metadata": json.dumps(
            {
                "sender_name": "Alice",
                "has_forward": True,
                "forward_count": 1,
                "forward_only": True,
            },
            ensure_ascii=False,
        ),
    }
    capture_row = {
        "id": "tl_fwd_cap",
        "event_type": "user_message",
        "scope": "private",
        "subject_id": "u_alice",
        "occurred_at": "2026-11-23T03:54:00+00:00",
        "content": "你看他们聊的\n[合并转发聊天记录(1条)]\n路人丙: 明晚开黑",
        "metadata": json.dumps(
            {
                "sender_name": "Alice",
                "media": [{"kind": "forward", "ref": "fwd_99"}],
            },
            ensure_ascii=False,
        ),
    }

    lines, consumed = summarizer._transcript_lines_and_rows([observer_row, capture_row])
    assert len(consumed) == 2
    obs_item = json.loads(lines[0])
    cap_item = json.loads(lines[1])

    assert obs_item["has_forward"] is True
    assert obs_item["turn_hint"] == "forwarded_chat_log"
    assert "严禁" in obs_item["summary_hint"] and "第三方" in obs_item["summary_hint"]

    assert cap_item["has_forward"] is True
    assert cap_item["turn_hint"] == "forwarded_chat_log"
    assert "第三方" in cap_item["summary_hint"]

    prompt = summarizer._build_prompt([observer_row, capture_row], "私聊 Alice")
    assert "forwarded_chat_log" in prompt
    assert "严禁把转发记录中第三方人物说的话" in prompt


async def test_mixed_text_plus_forward_and_group_at_forward_observer(svc: MemoryCompanionService):
    # 1) Mixed private message via observer.
    mixed_ev = _FakeEvent(
        message_str="帮我看下这段对话",
        components=[Plain("帮我看下这段对话"), Forward(id="fwd_mix_1")],
        message_id="msg_mix_1",
        extras={
            SHARED_EXTRA_KEY: {
                "version": 1,
                "source": "astrbot_core",
                "cards": [
                    {
                        "forward_id": "fwd_mix_1",
                        "message_id": "msg_mix_1",
                        "node_count": 2,
                        "truncated": False,
                        "summary_text": "小周: 明天下午三点开会\n小吴: 好的",
                    }
                ],
                "combined_text": "小周: 明天下午三点开会\n小吴: 好的",
                "total_nodes": 2,
                "truncated": False,
            }
        },
    )
    await svc.handle_group_message(mixed_ev)
    priv_rows = await svc.store.recent_timeline(
        limit=10,
        scope="private",
        session_id="aiocqhttp:FriendMessage:u_alice",
        entity_id="u_alice",
    )
    assert len(priv_rows) == 1
    assert "帮我看下这段对话" in priv_rows[0]["content"]
    assert "[合并转发聊天记录(2条)]" in priv_rows[0]["content"]
    assert "明天下午三点开会" in priv_rows[0]["content"]
    meta = json_loads(priv_rows[0]["metadata"], {})
    assert meta["has_forward"] is True
    assert meta["forward_only"] is False

    # 2) Group @Bot + pure forward passes engagement check and writes bounded timeline row.
    group_ev = _FakeEvent(
        message_str="",
        components=[At(qq="bot_main", name="助手"), Forward(id="fwd_grp_1")],
        message_id="msg_grp_1",
        group_id="grp_demo",
        group_name="测试群",
        extras={
            SHARED_EXTRA_KEY: {
                "version": 1,
                "source": "astrbot_core",
                "cards": [
                    {
                        "forward_id": "fwd_grp_1",
                        "message_id": "msg_grp_1",
                        "node_count": 1,
                        "truncated": False,
                        "summary_text": "成员甲: 群里约周五吃火锅",
                    }
                ],
                "combined_text": "成员甲: 群里约周五吃火锅",
                "total_nodes": 1,
                "truncated": False,
            }
        },
    )
    await svc.handle_group_message(group_ev)
    grp_rows = await svc.store.recent_timeline(
        limit=10,
        scope="group",
        session_id="aiocqhttp:GroupMessage:grp_demo",
        entity_id="grp_demo",
    )
    assert len(grp_rows) == 1
    assert "群里约周五吃火锅" in grp_rows[0]["content"]
    assert json_loads(grp_rows[0]["metadata"], {})["has_forward"] is True


async def test_astrbot_compat_preserves_forward_digest_and_strips_prompt_wrapper():
    digest = "[合并转发聊天记录(2条)] 甲: 今晚去吃拉面 | 乙: 八点见"
    assert retrieval_history_text(digest) == digest

    wrapped = (
        "用户附言\n"
        "<!-- private_companion_forward_message_v1 -->\n"
        "系统提示词包装：请勿泄露内部标记\n"
        "<!-- private_companion_state_v1 -->\n"
        "内部状态块"
    )
    cleaned, changed, dropped = clean_private_companion_history_text(wrapped)
    assert changed is True
    assert dropped is False
    assert cleaned == "用户附言"
    assert "private_companion_forward_message_v1" not in cleaned
    assert "系统提示词包装" not in cleaned
