from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.companion_linkage import CompanionMemoryLinkage, REGISTRY_ATTRIBUTE
from core.config import ConfigView
from core.injection import InjectionComposer
from core.migration_livingmemory import LivingMemoryMigrator
from core.models import EntityRef, MemoryRecord, SearchResult, SessionContext, json_dumps
from core.operations import PortableMemoryArchive
from core.service import _RECALL_STATIC_GUIDANCE
from core.source_query import source_visible
from core.store import MemoryStore
from core.visibility import VisibilityPolicy
from .package_bootstrap import bootstrap_package
from .test_source_query import RESULT_VALIDATOR as SOURCE_V1_VALIDATOR, add_row, ctx, service  # noqa: F401
from .test_source_query_v2 import RESULT as SOURCE_V2_VALIDATOR, event as v2_event  # noqa: F401

bootstrap_package()
if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload if payload is not None else kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")
    quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = quart_stub
PluginPageApi = importlib.import_module("astrbot_plugin_memory_companion.page_api").PluginPageApi


def _private_ctx(text: str = "还记得我们上次去海边是什么时候吗") -> SessionContext:
    return SessionContext(
        session_id="qq:FriendMessage:u1",
        scope="private",
        platform="qq",
        user_id="u1",
        user_name="用户甲",
        bot_id="b1",
        persona_id="p1",
        message_text=text,
    )


def _make_memory(
    memory_id: str,
    content: str,
    *,
    session_id: str = "qq:FriendMessage:u1",
    user_id: str = "u1",
    bot_id: str = "b1",
    persona_id: str = "p1",
    memory_type: str = "conversation_summary",
    occurred_at: str = "2026-09-08T10:00:00+00:00",
    scope: str = "private",
    visibility: str = "private_pair",
    metadata: dict | None = None,
) -> MemoryRecord:
    meta = {"persona_id": persona_id, "owner_bot_id": bot_id, **(metadata or {})}
    return MemoryRecord(
        id=memory_id,
        memory_type=memory_type,
        subject=EntityRef(kind="user", id=user_id, name="用户甲", role="user"),
        object=EntityRef.bot_self(bot_id),
        scope=scope,
        session_id=session_id,
        platform="qq",
        visibility=visibility,
        lifecycle="stable_memory",
        review_status="auto",
        content=content,
        evidence=content,
        confidence=0.9,
        importance=0.8,
        owner_bot_id=bot_id,
        occurred_at=occurred_at,
        created_at=occurred_at,
        updated_at=occurred_at,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# 1. Recall guidance, humanized injection & tool-availability gating
# ---------------------------------------------------------------------------


def test_humanized_no_recall_hint_is_suppressed_when_recall_tools_available():
    composer = InjectionComposer()
    cfg = {"enabled": True, "no_recall_hint_enabled": True}
    composer.set_humanize_config_provider(
        lambda dotted, default: cfg.get(dotted.replace("memory_humanization.", ""), default)
    )
    core_mem = _make_memory("core_1", "用户偏好清淡饮食", memory_type="core_memory")

    without_tools = composer.compose(
        _private_ctx(),
        [],
        max_chars=3000,
        core_memories=[core_mem],
        recall_tools_available=False,
    )
    assert "确实想不起来了" in without_tools

    with_tools = composer.compose(
        _private_ctx(),
        [],
        max_chars=3000,
        core_memories=[core_mem],
        recall_tools_available=True,
    )
    assert "确实想不起来了" not in with_tools
    assert "先调工具核查原文后再判断" in with_tools


def test_static_recall_guidance_is_compact_and_covers_routing_rules():
    assert len(_RECALL_STATIC_GUIDANCE) < 340
    for token in ("先查后认忘", "recall", "sources", "range_batch", "events", "0命中"):
        assert token in _RECALL_STATIC_GUIDANCE


def test_recall_tools_available_for_request_tracks_mounted_tools(service, ctx):
    req_with_recall = SimpleNamespace(func_tool=SimpleNamespace(tools=[SimpleNamespace(name="memory_companion_recall")]))
    req_with_sources = SimpleNamespace(func_tool=SimpleNamespace(tools=[SimpleNamespace(name="memory_companion_sources")]))
    req_empty = SimpleNamespace(func_tool=SimpleNamespace(tools=[]))

    assert service._recall_tools_available_for_request(ctx, req_with_recall) is True
    assert service._recall_tools_available_for_request(ctx, req_with_sources) is True
    assert service._recall_tools_available_for_request(ctx, req_empty) is False

    # Disabling recall tool alone must not let recall-only request count as available via reconstruction tools.
    service.config.raw.setdefault("memory_tools", {})["enable_recall_tool"] = False
    assert service._recall_tools_available_for_request(ctx, req_with_recall) is False
    assert service._recall_tools_available_for_request(ctx, req_with_sources) is True

    service.config.raw.setdefault("memory_reconstruction", {})["enabled"] = False
    assert service._recall_tools_available_for_request(ctx, req_with_recall) is False
    assert service._recall_tools_available_for_request(ctx, req_with_sources) is False


@pytest.mark.asyncio
async def test_inject_memories_suppresses_defeatist_hint_when_tools_mounted(service, ctx):
    service.config.raw["memory_humanization"] = {"enabled": True, "no_recall_hint_enabled": True}
    core_mem = _make_memory(
        "core_u1",
        "用户喜欢喝黑咖啡",
        session_id=ctx.session_id,
        user_id=ctx.user_id,
        bot_id=ctx.bot_id,
        persona_id=ctx.persona_id,
        memory_type="core_memory",
        metadata={"core_memory": True, "core_enabled": True, "core_scope": "private", "target_id": ctx.user_id},
    )
    await service.store.insert_memory(core_mem)
    req = SimpleNamespace(
        system_prompt="",
        prompt="我们上次去图书馆是什么时候",
        contexts=[],
        func_tool=SimpleNamespace(tools=[SimpleNamespace(name="memory_companion_recall")]),
    )
    event = SimpleNamespace()
    with patch.object(service, "search_context_slots", new=AsyncMock(return_value=([], [], {}))):
        await service.inject_memories(ctx, req, event=event)
    assert "确实想不起来了" not in str(req.prompt)


# ---------------------------------------------------------------------------
# 2. Zero-hit retry hint & source query ergonomics (end_at default, limit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_recall_attaches_hint_only_on_empty_with_remaining_steps(service, ctx):
    event = SimpleNamespace()
    with patch.object(service, "search_context_slots", new=AsyncMock(return_value=([], [], {}))):
        empty_res = await service.tool_recall(event, "不存在的冷门词")
    assert empty_res["ok"] is True
    assert empty_res["memories"] == []
    assert "hint" in empty_res and "sources" in empty_res["hint"]

    hit_mem = _make_memory("m_hit", "用户喜欢抹茶蛋糕", session_id=ctx.session_id, user_id=ctx.user_id, bot_id=ctx.bot_id)
    with patch.object(
        service,
        "search_context_slots",
        new=AsyncMock(return_value=([SearchResult(memory=hit_mem, score=0.95, reason="exact")], [], {})),
    ):
        hit_res = await service.tool_recall(event, "抹茶蛋糕")
    assert hit_res["ok"] is True
    assert len(hit_res["memories"]) == 1
    assert "hint" not in hit_res

    # Exhaust reconstruction step budget: hint must disappear.
    budget_key = service._reconstruction_budget_key(event, ctx)
    service._reconstruction_states[budget_key] = {"steps": service._reconstruction_max_steps(), "last_seen": 9e12}
    with patch.object(service, "search_context_slots", new=AsyncMock(return_value=([], [], {}))):
        exhausted_res = await service.tool_recall(event, "另一个词")
    assert exhausted_res["ok"] is True
    assert "hint" not in exhausted_res


@pytest.mark.asyncio
async def test_tool_sources_v1_empty_hint_and_range_default_end_at(service, ctx):
    event = SimpleNamespace()
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    row_id = await add_row(service, ctx, "刚才一起去喝了桂花乌龙茶", at=past)

    # Empty search with remaining steps includes schema-valid hint.
    empty = await service.tool_sources(event, action="search", terms=["完全不存在的词"])
    SOURCE_V1_VALIDATOR.validate(empty)
    assert empty["status"] == "empty"
    assert empty["usage"]["remaining_steps"] > 0
    assert "hint" in empty and len(empty["hint"]) <= 60

    # Range without end_at defaults to now and finds the recent message (no hint on hit).
    start_at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
    ranged = await service.tool_query(event, "sources", {"action": "range", "start_at": start_at})
    assert ranged["ok"] is True
    SOURCE_V1_VALIDATOR.validate(ranged["result"])
    assert [s["source_ref"] for s in ranged["result"]["sources"]] == [f"timeline:{row_id}"]
    assert "hint" not in ranged["result"]

    # Last step (remaining_steps == 0) empty search omits hint.
    last_empty = await service.tool_sources(event, action="search", terms=["又一个不存在的词"])
    SOURCE_V1_VALIDATOR.validate(last_empty)
    assert last_empty["status"] == "empty"
    assert last_empty["usage"]["remaining_steps"] == 0
    assert "hint" not in last_empty


@pytest.mark.asyncio
async def test_tool_sources_v1_range_rejects_future_start_when_end_omitted(service, ctx):
    event = SimpleNamespace()
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec="seconds")
    res = await service.tool_sources(event, action="range", start_at=future)
    SOURCE_V1_VALIDATOR.validate(res)
    assert res["ok"] is False
    assert res["error"] == "time_range_reversed_or_empty"


@pytest.mark.asyncio
async def test_tool_sources_v1_range_direct_end_at_none_and_invalid_type(service, ctx):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    row_id = await add_row(service, ctx, "直调 range 省略 end_at=None 测试", at=past)
    start_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")

    res_none = await service.tool_sources(SimpleNamespace(), action="range", start_at=start_at, end_at=None)
    SOURCE_V1_VALIDATOR.validate(res_none)
    assert res_none["ok"] is True
    assert [s["source_ref"] for s in res_none["sources"]] == [f"timeline:{row_id}"]

    res_bad = await service.tool_sources(SimpleNamespace(), action="range", start_at=start_at, end_at=123)
    SOURCE_V1_VALIDATOR.validate(res_bad)
    assert res_bad["ok"] is False and res_bad["error"] == "invalid_parameter"


@pytest.mark.asyncio
async def test_tool_sources_v2_range_batch_defaults_end_at_tolerates_limit_and_empty_hint(service, ctx, v2_event):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    row_id = await add_row(service, ctx, "约定周五去美术馆看画展", at=past)
    start_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")

    # Omit end_at AND pass redundant positive limit through v3 query_for_model.
    wrapped = await service.query_for_model(
        v2_event,
        "sources",
        action="range_batch",
        start_at=start_at,
        limit=20,
    )
    assert wrapped["ok"] is True
    result = wrapped["result"]
    SOURCE_V2_VALIDATOR.validate(result)
    assert result["status"] == "batch"
    assert [s["source_ref"] for s in result["sources"]] == [f"timeline:{row_id}"]
    assert "hint" not in result
    assert result["usage"]["returned_bytes"] == len(json_dumps(result).encode("utf-8"))

    # Empty range_batch with remaining steps includes hint and exact byte count.
    empty_res = await service.tool_sources(
        v2_event,
        action="range_batch",
        start_at="2025-01-01T00:00:00+00:00",
        end_at="2025-01-02T00:00:00+00:00",
        limit=10,
    )
    SOURCE_V2_VALIDATOR.validate(empty_res)
    assert empty_res["status"] == "empty"
    assert empty_res["usage"]["remaining_steps"] > 0
    assert "hint" in empty_res
    assert empty_res["usage"]["returned_bytes"] == len(json_dumps(empty_res).encode("utf-8"))

    # Direct tool_sources(range_batch, end_at=None) also defaults end_at to now, while invalid type rejects.
    direct_none = await service.tool_sources(
        v2_event,
        action="range_batch",
        start_at=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds"),
        end_at=None,
    )
    SOURCE_V2_VALIDATOR.validate(direct_none)
    assert direct_none["ok"] is True
    assert [s["source_ref"] for s in direct_none["sources"]] == [f"timeline:{row_id}"]

    bad_end = await service.tool_sources(
        v2_event,
        action="range_batch",
        start_at="2025-01-01T00:00:00+00:00",
        end_at=123,
    )
    assert bad_end["ok"] is False and bad_end["error"] == "invalid_parameter"

    # Invalid boolean/negative limits are still rejected.
    bad = await service.tool_sources(
        v2_event,
        action="range_batch",
        start_at="2025-01-01T00:00:00+00:00",
        end_at="2025-01-02T00:00:00+00:00",
        limit=True,
    )
    assert bad["ok"] is False and bad["error"] == "range_batch_uses_server_budget"


# ---------------------------------------------------------------------------
# 3. CompanionMemoryLinkage query-aware recall & strict isolation
# ---------------------------------------------------------------------------


class _FakeRegistry:
    def __init__(self, scope: dict | None):
        self.scope = scope
        self.registered = {}

    def register(self, provider_id, **kwargs):
        self.registered[provider_id] = kwargs
        return "reg-1"

    def authorize_memory_read(self, request):
        if self.scope is None:
            raise PermissionError("revoked")
        return self.scope


@pytest.mark.asyncio
async def test_companion_linkage_query_recalls_core_topic_and_continuity_with_isolation(tmp_path):
    store = MemoryStore(tmp_path / "memory_companion.db")
    store.initialize()
    try:
        session_id = "qq:FriendMessage:u1"
        scope = {
            "schema": "companion.linked-memory-read.v1",
            "persona_id": "p1",
            "reader_user_id": "u1",
            "members": [
                {
                    "session_id": session_id,
                    "platform": "qq",
                    "native_account_id": "u1",
                    "bot_id": "b1",
                    "account_id": "b1",
                    "memory_identity": {"owner_bot_id": "b1", "platform_name": "qq"},
                    "since": "2026-04-01T00:00:00+00:00",
                }
            ],
        }
        disabled_core = _make_memory(
            "mem_core_disabled",
            "已停用的高优先级核心记忆",
            memory_type="core_memory",
            occurred_at="2026-04-02T01:00:00+00:00",
            metadata={"core_memory": True, "core_priority": 99, "core_enabled": False},
        )
        core_mem = _make_memory(
            "mem_core",
            "核心记忆：用户偏好清淡饮食",
            memory_type="core_memory",
            occurred_at="2026-04-02T00:00:00+00:00",
            metadata={"core_memory": True, "core_priority": 90, "core_enabled": True},
        )
        old_topic = _make_memory(
            "mem_library",
            "四月五号一起去图书馆借阅设计画册",
            occurred_at="2026-04-05T12:00:00+00:00",
        )
        pre_since = _make_memory(
            "mem_pre_since",
            "三月二十日图书馆旧记录（早于授权起始时间）",
            occurred_at="2026-03-20T12:00:00+00:00",
        )
        wrong_persona = _make_memory(
            "mem_other_persona",
            "另一个人格的图书馆借阅记录",
            persona_id="p_other",
            occurred_at="2026-04-10T12:00:00+00:00",
        )
        other_user = _make_memory(
            "mem_other_user",
            "用户乙的图书馆借阅记录",
            session_id="qq:FriendMessage:u2",
            user_id="u2",
            occurred_at="2026-04-11T12:00:00+00:00",
        )
        recent_records = [
            _make_memory(
                f"mem_recent_{i}",
                f"最近闲聊记忆 #{i}",
                occurred_at=f"2026-05-{10 + i:02d}T10:00:00+00:00",
            )
            for i in range(6)
        ]
        for record in [disabled_core, core_mem, old_topic, pre_since, wrong_persona, other_user, *recent_records]:
            await store.insert_memory(record)

        # Simulate search_context_slots returning both authorized topic match AND unauthorized/disabled candidates.
        search_calls: list[SessionContext] = []

        async def fake_search_context_slots(query_text, search_ctx, top_k=6):
            search_calls.append(search_ctx)
            return (
                [
                    SearchResult(memory=disabled_core, score=0.995, reason="disabled_core_attempt"),
                    SearchResult(memory=wrong_persona, score=0.99, reason="leak_attempt"),
                    SearchResult(memory=other_user, score=0.98, reason="leak_attempt"),
                    SearchResult(memory=pre_since, score=0.97, reason="pre_since_attempt"),
                    SearchResult(memory=old_topic, score=0.92, reason="topic_hit"),
                ],
                [],
                {},
            )

        cfg = ConfigView({"private_companion_bridge": {"enabled": True}})
        fake_service = SimpleNamespace(
            store=store,
            config=cfg,
            search_context_slots=fake_search_context_slots,
            _user_memory_category=lambda t: "private_conversation",
        )
        registry = _FakeRegistry(scope)
        context = SimpleNamespace(**{REGISTRY_ATTRIBUTE: registry})
        plugin = SimpleNamespace(context=context, service=fake_service)
        linkage = CompanionMemoryLinkage(plugin)
        assert linkage.register() is True

        # 1) Query-aware read: gets core + topic match + recent continuity, and strips unauthorized rows!
        result = await linkage._read({"query": "上次去图书馆是什么时候", "limit": 4, "max_chars": 4000})
        ids = [item["id"] for item in result["items"]]
        assert len(search_calls) == 1
        assert search_calls[0].strict_session_only is True
        assert "mem_core" in ids
        assert "mem_core_disabled" not in ids
        assert "mem_library" in ids
        assert "mem_recent_5" in ids
        assert "mem_pre_since" not in ids
        assert "mem_other_persona" not in ids
        assert "mem_other_user" not in ids

        # 2) Empty query: skips search_context_slots and falls back to occurred_at DESC.
        search_calls.clear()
        no_query = await linkage._read({"query": "", "limit": 3, "max_chars": 4000})
        assert search_calls == []
        assert [item["id"] for item in no_query["items"]] == ["mem_recent_5", "mem_recent_4", "mem_recent_3"]

        # 3) Timeout in search_context_slots gracefully falls back to recent authorized memories.
        async def slow_search(*_args, **_kwargs):
            await asyncio.sleep(5.0)
            return [], [], {}

        fake_service.search_context_slots = slow_search
        with patch("core.companion_linkage._QUERY_SEARCH_TIMEOUT_SECONDS", 0.12):
            timed_out = await linkage._read({"query": "图书馆", "limit": 3, "max_chars": 4000})
        assert [item["id"] for item in timed_out["items"]][:2] == ["mem_core", "mem_recent_5"]

        # 4) Lease revocation mid-flight fails closed.
        async def revoking_search(*_args, **_kwargs):
            registry.scope = None
            return [SearchResult(memory=old_topic, score=0.9, reason="hit")], [], {}

        registry.scope = scope
        fake_service.search_context_slots = revoking_search
        revoked = await linkage._read({"query": "图书馆", "limit": 4, "max_chars": 4000})
        assert revoked["items"] == []
        assert revoked["reason"] == "memory_read_authorization_unavailable"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 4. Import path localization, quote stripping & LivingMemory directory scan
# ---------------------------------------------------------------------------


def _create_livingmemory_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE documents (id TEXT, content TEXT, created_at TEXT)")
        conn.execute("INSERT INTO documents VALUES ('doc1', '这是一条有效的历史总结记忆，长度足够通过导入检测。', '2026-05-01T10:00:00Z')")
        conn.commit()
    finally:
        conn.close()


def test_page_path_strips_quotes_and_returns_chinese_error_with_real_allowed_dir():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data_dir = root / "plugin_data" / "astrbot_plugin_memory_companion"
        data_dir.mkdir(parents=True, exist_ok=True)
        allowed_file = data_dir.parent / "astrbot_plugin_livingmemory" / "livingmemory.db"
        allowed_file.parent.mkdir(parents=True, exist_ok=True)
        allowed_file.write_bytes(b"")

        plugin = SimpleNamespace(
            service=SimpleNamespace(data_dir=data_dir, config=ConfigView({})),
        )
        api = PluginPageApi(plugin)

        resolved, err = api._resolve_page_path(f'"{allowed_file}"')
        assert err == ""
        assert resolved == allowed_file.resolve()

        resolved_single, err_single = api._resolve_page_path(f"'{allowed_file}'")
        assert err_single == ""
        assert resolved_single == allowed_file.resolve()

        outside = root / "outside" / "secret.db"
        res_out, err_out = api._resolve_page_path(str(outside))
        assert res_out is None
        assert "path" in err_out
        assert "超出允许的插件数据目录范围" in err_out
        assert str(data_dir.resolve()) in err_out

        res_dot, err_dot = api._resolve_page_path("../outside/secret.db")
        assert res_dot is None
        assert "path" in err_dot
        assert "上级目录跳转" in err_dot
        assert "相对路径" not in err_dot

        roots_payload = api._allowed_import_roots_payload()
        assert roots_payload["memory_data_dir"] == str(data_dir.resolve())
        assert roots_payload["plugin_data_dir"] == str(data_dir.parent.resolve())
        assert roots_payload["portable_export_dir"] == str((data_dir / "exports").resolve())


def test_portable_archive_strips_quotes_and_shows_chinese_allowed_dir():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data_dir = root / "plugin_data" / "astrbot_plugin_memory_companion"
        archive_file = data_dir / "exports" / "backup.jsonl"
        archive_file.parent.mkdir(parents=True, exist_ok=True)
        archive_file.write_text("", encoding="utf-8")

        archive = PortableMemoryArchive(MagicMock(), data_dir)
        assert archive._resolve_source_path(f'"{archive_file}"') == archive_file.resolve()

        outside = root / "outside" / "other.jsonl"
        with pytest.raises(ValueError) as exc_info:
            archive._resolve_source_path(str(outside))
        msg = str(exc_info.value)
        assert "outside the plugin data directory" in msg
        assert "超出允许的插件数据目录范围" in msg
        assert str(data_dir.resolve()) in msg


def test_livingmemory_migrator_auto_scans_directory_and_skips_own_db(tmp_path):
    root = tmp_path
    plugin_root = root / "plugins" / "astrbot_plugin_memory_companion"
    data_dir = root / "plugin_data" / "astrbot_plugin_memory_companion"
    plugin_root.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Put memory_companion.db and a nested LivingMemory db inside the same folder.
    own_db = root / "plugin_data" / "memory_companion.db"
    _create_livingmemory_db(own_db)
    nested_lm = root / "plugin_data" / "exported_folder" / "sub" / "custom_lm.db"
    _create_livingmemory_db(nested_lm)

    migrator = LivingMemoryMigrator(MagicMock(), plugin_root, data_dir)
    candidates = migrator.candidate_paths(f'"{root / "plugin_data"}"')
    resolved_candidates = [p.resolve() for p in candidates]
    assert nested_lm.resolve() in resolved_candidates
    assert own_db.resolve() not in resolved_candidates

    report = migrator.preview(str(root / "plugin_data" / "exported_folder"))
    assert report["count"] >= 1
    assert Path(report["candidates"][0]["path"]).resolve() == nested_lm.resolve()


# ---------------------------------------------------------------------------
# 5. Legacy together_companion:<user_id> private read alias & strict isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_together_companion_sources_range_search_and_isolation(service, ctx, v2_event):
    # Synthetic legacy together_companion:<user_id> timeline rows.
    legacy_call_id = await service.store.add_timeline_event(
        event_type="shared_call",
        session_id=f"together_companion:{ctx.user_id}",
        scope="private",
        subject_id=ctx.bot_id,
        object_id=ctx.user_id,
        content="周末通话约定去植物园散步并拍风景照。",
        metadata={"source_plugin": "astrbot_plugin_together_companion"},
        occurred_at="2026-05-01T10:05:00+00:00",
    )
    legacy_msg_id = await service.store.add_timeline_event(
        event_type="user_message",
        session_id=f"together_companion:{ctx.user_id}",
        scope="private",
        subject_id=ctx.user_id,
        object_id=ctx.user_id,
        content="周末天气不错，去哪散步比较好？",
        metadata={
            "owner_bot_id": ctx.bot_id,
            "platform": "together_companion",
            "source_plugin": "astrbot_plugin_together_companion",
        },
        occurred_at="2026-05-01T10:00:00+00:00",
    )
    # Rows belonging to another user, another bot, another persona, or corrupt JSON metadata must stay invisible.
    other_user_id = await service.store.add_timeline_event(
        event_type="shared_call",
        session_id="together_companion:u_other",
        scope="private",
        subject_id=ctx.bot_id,
        object_id="u_other",
        content="用户乙的植物园散步通话记录",
        metadata={"source_plugin": "astrbot_plugin_together_companion"},
        occurred_at="2026-05-01T10:06:00+00:00",
    )
    other_bot_id = await service.store.add_timeline_event(
        event_type="shared_call",
        session_id=f"together_companion:{ctx.user_id}",
        scope="private",
        subject_id="other_bot",
        object_id=ctx.user_id,
        content="角色B的植物园散步通话记录",
        metadata={"source_plugin": "astrbot_plugin_together_companion"},
        occurred_at="2026-05-01T10:07:00+00:00",
    )
    other_persona_id = await service.store.add_timeline_event(
        event_type="shared_call",
        session_id=f"together_companion:{ctx.user_id}",
        scope="private",
        subject_id=ctx.bot_id,
        object_id=ctx.user_id,
        content="其他人格的植物园散步通话记录",
        metadata={"persona_id": "other_persona", "source_plugin": "astrbot_plugin_together_companion"},
        occurred_at="2026-05-01T10:08:00+00:00",
    )
    corrupt_meta_id = await service.store.add_timeline_event(
        event_type="shared_call",
        session_id=f"together_companion:{ctx.user_id}",
        scope="private",
        subject_id=ctx.bot_id,
        object_id=ctx.user_id,
        content="损坏元数据的植物园散步记录",
        metadata={"persona_id": "other_persona"},
        occurred_at="2026-05-01T10:09:00+00:00",
    )
    with service.store._lock:
        service.store._conn.execute("UPDATE timeline SET metadata='{corrupt' WHERE id=?", (corrupt_meta_id,))
        service.store._conn.commit()

    # Python-side source_visible guard also rejects corrupt JSON string metadata.
    assert (
        source_visible(
            ctx,
            {
                "scope": "private",
                "session_id": f"together_companion:{ctx.user_id}",
                "event_type": "shared_call",
                "subject_id": ctx.bot_id,
                "object_id": ctx.user_id,
                "metadata": "{corrupt",
            },
            {},
        )
        is False
    )

    # 1) Same private user + same bot: sources(range) finds only valid legacy together_companion rows.
    ranged = await service.tool_sources(
        SimpleNamespace(),
        action="range",
        start_at="2026-05-01T00:00:00+00:00",
        end_at="2026-05-02T00:00:00+00:00",
    )
    SOURCE_V1_VALIDATOR.validate(ranged)
    assert ranged["ok"] is True
    returned_refs = [item["source_ref"] for item in ranged["sources"]]
    assert f"timeline:{legacy_call_id}" in returned_refs
    assert f"timeline:{legacy_msg_id}" in returned_refs
    assert f"timeline:{other_user_id}" not in returned_refs
    assert f"timeline:{other_bot_id}" not in returned_refs
    assert f"timeline:{other_persona_id}" not in returned_refs
    assert f"timeline:{corrupt_meta_id}" not in returned_refs
    call_item = next(item for item in ranged["sources"] if item["source_ref"] == f"timeline:{legacy_call_id}")
    assert call_item["speaker_role"] == "assistant"

    # 2) sources(search) and sources(range_batch) also find valid legacy rows and exclude corrupt rows.
    searched = await service.tool_sources(SimpleNamespace(), action="search", terms=["植物园散步"])
    SOURCE_V1_VALIDATOR.validate(searched)
    assert [item["source_ref"] for item in searched["sources"]] == [f"timeline:{legacy_call_id}"]

    batched = await service.tool_sources(
        v2_event,
        action="range_batch",
        start_at="2026-05-01T00:00:00+00:00",
        end_at="2026-05-02T00:00:00+00:00",
    )
    SOURCE_V2_VALIDATOR.validate(batched)
    assert [item["source_ref"] for item in batched["sources"]] == [
        f"timeline:{legacy_msg_id}",
        f"timeline:{legacy_call_id}",
    ]

    # 3) Group chat (even with the same user_id and bot_id) MUST NOT see private legacy rows.
    group_ctx = SessionContext(
        session_id="qq:GroupMessage:g1",
        scope="group",
        platform=ctx.platform,
        user_id=ctx.user_id,
        group_id="g1",
        bot_id=ctx.bot_id,
        persona_id=ctx.persona_id,
    )
    service.identity.resolve_event_context.return_value = group_ctx
    group_range = await service.tool_sources(
        SimpleNamespace(),
        action="range",
        start_at="2026-05-01T00:00:00+00:00",
        end_at="2026-05-02T00:00:00+00:00",
    )
    SOURCE_V1_VALIDATOR.validate(group_range)
    assert group_range["ok"] is True
    assert group_range["sources"] == []

    # 4) Different private user MUST NOT see u1's legacy rows.
    other_user_ctx = SessionContext(
        session_id="qq:FriendMessage:u_third",
        scope="private",
        platform=ctx.platform,
        user_id="u_third",
        bot_id=ctx.bot_id,
        persona_id=ctx.persona_id,
    )
    service.identity.resolve_event_context.return_value = other_user_ctx
    third_range = await service.tool_sources(
        SimpleNamespace(),
        action="range",
        start_at="2026-05-01T00:00:00+00:00",
        end_at="2026-05-02T00:00:00+00:00",
    )
    SOURCE_V1_VALIDATOR.validate(third_range)
    assert third_range["ok"] is True
    assert third_range["sources"] == []

    # 5) Different bot (same user_id) MUST NOT see ctx.bot_id's legacy rows.
    other_bot_ctx = SessionContext(
        session_id=ctx.session_id,
        scope="private",
        platform=ctx.platform,
        user_id=ctx.user_id,
        bot_id="b_third",
        persona_id=ctx.persona_id,
    )
    service.identity.resolve_event_context.return_value = other_bot_ctx
    other_bot_range = await service.tool_sources(
        SimpleNamespace(),
        action="range",
        start_at="2026-05-01T00:00:00+00:00",
        end_at="2026-05-02T00:00:00+00:00",
    )
    SOURCE_V1_VALIDATOR.validate(other_bot_range)
    assert other_bot_range["ok"] is True
    assert other_bot_range["sources"] == []


@pytest.mark.asyncio
async def test_legacy_together_companion_recall_and_navigate_with_strict_isolation(service, ctx):
    legacy_tl_id = await service.store.add_timeline_event(
        event_type="shared_call",
        session_id=f"together_companion:{ctx.user_id}",
        scope="private",
        subject_id=ctx.bot_id,
        object_id=ctx.user_id,
        content="周末通话约定去植物园散步并顺路看温室。",
        metadata={"source_plugin": "astrbot_plugin_together_companion"},
        occurred_at="2026-05-01T10:05:00+00:00",
    )
    legacy_mem = MemoryRecord(
        id="together-shared-test-0",
        memory_type="shared_call",
        subject=EntityRef(kind="bot", id=ctx.bot_id, name="角色A", role="assistant"),
        object=EntityRef(kind="user", id=ctx.user_id, name="用户甲", role="user"),
        scope="private",
        session_id=f"together_companion:{ctx.user_id}",
        platform="together_companion",
        visibility="bot_self",
        lifecycle="stable_memory",
        review_status="auto",
        content="周末通话约定去植物园散步并顺路看温室。",
        evidence="周末通话约定去植物园散步",
        confidence=0.9,
        importance=0.85,
        owner_bot_id="",
        source_plugin="astrbot_plugin_together_companion",
        occurred_at="2026-05-01T10:05:00+00:00",
        created_at="2026-05-01T10:05:00+00:00",
        updated_at="2026-05-01T10:05:00+00:00",
        metadata={"source_event_ids": [legacy_tl_id]},
    )
    other_user_legacy_mem = MemoryRecord(
        id="together-shared-other-user",
        memory_type="shared_call",
        subject=EntityRef(kind="bot", id=ctx.bot_id, name="角色A", role="assistant"),
        object=EntityRef(kind="user", id="u_other", name="用户乙", role="user"),
        scope="private",
        session_id="together_companion:u_other",
        platform="together_companion",
        visibility="bot_self",
        lifecycle="stable_memory",
        review_status="auto",
        content="用户乙也计划去植物园散步。",
        evidence="用户乙去植物园散步",
        confidence=0.9,
        importance=0.85,
        owner_bot_id="",
        source_plugin="astrbot_plugin_together_companion",
        occurred_at="2026-05-01T10:06:00+00:00",
        created_at="2026-05-01T10:06:00+00:00",
        updated_at="2026-05-01T10:06:00+00:00",
        metadata={},
    )
    other_bot_legacy_mem = MemoryRecord(
        id="together-shared-other-bot",
        memory_type="shared_call",
        subject=EntityRef(kind="bot", id="other_bot", name="角色B", role="assistant"),
        object=EntityRef(kind="user", id=ctx.user_id, name="用户甲", role="user"),
        scope="private",
        session_id=f"together_companion:{ctx.user_id}",
        platform="together_companion",
        visibility="bot_self",
        lifecycle="stable_memory",
        review_status="auto",
        content="角色B也提到去植物园散步。",
        evidence="角色B去植物园散步",
        confidence=0.9,
        importance=0.85,
        owner_bot_id="",
        source_plugin="astrbot_plugin_together_companion",
        occurred_at="2026-05-01T10:07:00+00:00",
        created_at="2026-05-01T10:07:00+00:00",
        updated_at="2026-05-01T10:07:00+00:00",
        metadata={},
    )
    # Conflicting multi-bot attribution (subject=ctx.bot_id vs owner_bot_id/meta bot_id=other_bot) & mismatched participant.
    conflicting_owner_mem = MemoryRecord(
        id="together-shared-conflict-owner",
        memory_type="shared_call",
        subject=EntityRef(kind="bot", id=ctx.bot_id, name="角色A", role="assistant"),
        object=EntityRef(kind="user", id=ctx.user_id, name="用户甲", role="user"),
        scope="private",
        session_id=f"together_companion:{ctx.user_id}",
        platform="together_companion",
        visibility="bot_self",
        lifecycle="stable_memory",
        review_status="auto",
        content="归属冲突的植物园散步记录。",
        evidence="归属冲突记录",
        confidence=0.9,
        importance=0.85,
        owner_bot_id="other_bot",
        source_plugin="astrbot_plugin_together_companion",
        occurred_at="2026-05-01T10:08:00+00:00",
        created_at="2026-05-01T10:08:00+00:00",
        updated_at="2026-05-01T10:08:00+00:00",
        metadata={},
    )
    conflicting_meta_bot_mem = MemoryRecord(
        id="together-shared-conflict-meta-bot",
        memory_type="shared_call",
        subject=EntityRef(kind="bot", id=ctx.bot_id, name="角色A", role="assistant"),
        object=EntityRef(kind="user", id=ctx.user_id, name="用户甲", role="user"),
        scope="private",
        session_id=f"together_companion:{ctx.user_id}",
        platform="together_companion",
        visibility="bot_self",
        lifecycle="stable_memory",
        review_status="auto",
        content="元数据 Bot 冲突的植物园散步记录。",
        evidence="元数据 Bot 冲突记录",
        confidence=0.9,
        importance=0.85,
        owner_bot_id="",
        source_plugin="astrbot_plugin_together_companion",
        occurred_at="2026-05-01T10:09:00+00:00",
        created_at="2026-05-01T10:09:00+00:00",
        updated_at="2026-05-01T10:09:00+00:00",
        metadata={"bot_id": "other_bot"},
    )
    mismatched_participant_mem = MemoryRecord(
        id="together-shared-bad-participant",
        memory_type="shared_call",
        subject=EntityRef(kind="bot", id=ctx.bot_id, name="角色A", role="assistant"),
        object=EntityRef(kind="user", id=ctx.user_id, name="用户甲", role="user"),
        scope="private",
        session_id=f"together_companion:{ctx.user_id}",
        platform="together_companion",
        visibility="bot_self",
        lifecycle="stable_memory",
        review_status="auto",
        content="参与者不匹配的植物园散步记录。",
        evidence="参与者不匹配记录",
        confidence=0.9,
        importance=0.85,
        owner_bot_id="",
        source_plugin="astrbot_plugin_together_companion",
        occurred_at="2026-05-01T10:10:00+00:00",
        created_at="2026-05-01T10:10:00+00:00",
        updated_at="2026-05-01T10:10:00+00:00",
        metadata={"participant_user_id": "u_other"},
    )
    for rec in (
        legacy_mem,
        other_user_legacy_mem,
        other_bot_legacy_mem,
        conflicting_owner_mem,
        conflicting_meta_bot_mem,
        mismatched_participant_mem,
    ):
        await service.store.insert_memory(rec)

    # Policy boundary checks: allow_self_timeline_everywhere=False, conflicting bots, mismatched participant.
    assert VisibilityPolicy(allow_self_timeline_everywhere=False).is_visible(legacy_mem, ctx) == (False, "bot_self")
    assert VisibilityPolicy().is_visible(conflicting_owner_mem, ctx)[0] is False
    assert VisibilityPolicy().is_visible(conflicting_meta_bot_mem, ctx)[0] is False
    assert VisibilityPolicy().is_visible(mismatched_participant_mem, ctx)[0] is False

    # 1) Private recall for same user + same bot finds ONLY their clean legacy together_companion memory.
    recalled = await service.tool_recall(SimpleNamespace(), "植物园散步", top_k=5)
    assert recalled["ok"] is True
    recalled_ids = [item["id"] for item in recalled["memories"]]
    assert "together-shared-test-0" in recalled_ids
    assert "together-shared-other-user" not in recalled_ids
    assert "together-shared-other-bot" not in recalled_ids
    assert "together-shared-conflict-owner" not in recalled_ids
    assert "together-shared-conflict-meta-bot" not in recalled_ids
    assert "together-shared-bad-participant" not in recalled_ids

    # 2) Navigate event_time expands the legacy together_companion timeline source too.
    nav = await service.tool_navigate(
        SimpleNamespace(),
        action="event_time",
        memory_ids=["together-shared-test-0"],
    )
    assert nav["ok"] is True
    assert len(nav["evidence"]) == 1
    assert [s["source_ref"] for s in nav["evidence"][0]["sources"]] == [f"timeline:{legacy_tl_id}"]

    # 3) Group chat (even with bot_self visible everywhere) MUST NOT see private legacy together_companion memories.
    group_ctx = SessionContext(
        session_id="qq:GroupMessage:g1",
        scope="group",
        platform=ctx.platform,
        user_id=ctx.user_id,
        group_id="g1",
        bot_id=ctx.bot_id,
        persona_id=ctx.persona_id,
    )
    service.identity.resolve_event_context.return_value = group_ctx
    group_recalled = await service.tool_recall(SimpleNamespace(), "植物园散步", top_k=5)
    assert group_recalled["ok"] is True
    assert group_recalled["memories"] == []

    # 4) Another private user MUST NOT see u1's bot_self legacy together_companion memory.
    third_ctx = SessionContext(
        session_id="qq:FriendMessage:u_third",
        scope="private",
        platform=ctx.platform,
        user_id="u_third",
        bot_id=ctx.bot_id,
        persona_id=ctx.persona_id,
    )
    service.identity.resolve_event_context.return_value = third_ctx
    third_recalled = await service.tool_recall(SimpleNamespace(), "植物园散步", top_k=5)
    assert third_recalled["ok"] is True
    assert third_recalled["memories"] == []

    # 5) Another bot MUST NOT see ctx.bot_id's legacy together_companion memory.
    other_bot_ctx = SessionContext(
        session_id=ctx.session_id,
        scope="private",
        platform=ctx.platform,
        user_id=ctx.user_id,
        bot_id="b_third",
        persona_id=ctx.persona_id,
    )
    service.identity.resolve_event_context.return_value = other_bot_ctx
    other_bot_recalled = await service.tool_recall(SimpleNamespace(), "植物园散步", top_k=5)
    assert other_bot_recalled["ok"] is True
    assert other_bot_recalled["memories"] == []
