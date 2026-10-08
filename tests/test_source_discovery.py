from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from .test_reply_continuity import service
from .test_source_query import ctx
from .test_source_query import add_row
from .test_source_semantic import add_row_with_id


pytestmark = pytest.mark.asyncio


class _DiscoveryProvider:
    def __init__(self, *, fail: bool = False, prefer_windows: bool = False):
        self.fail = fail
        self.prefer_windows = prefer_windows
        self.inputs: list[str] = []

    def meta(self):
        return {"id": "semantic-test-provider"}

    async def get_embedding(self, text: str):
        self.inputs.append(text)
        if self.fail:
            raise RuntimeError("provider unavailable")
        if self.prefer_windows:
            if "\n" in text or text == "苹果":
                return [1.0, 0.0, 0.0]
            if "苹果" in text:
                return [0.0, 0.0, 1.0]
        if "苹果" in text:
            return [1.0, 0.0, 0.0]
        if "旅行" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def enable_discovery(service, provider: _DiscoveryProvider, *, history: bool = False) -> None:
    service.config.raw["memory_reconstruction"] = {
        **dict(service.config.raw.get("memory_reconstruction") or {}),
        "enabled": True,
        "per_step_limit": 6,
        "max_steps": 8,
    }
    service.config.raw["source_semantic"] = {
        "enabled": True,
        "provider_id": "semantic-test-provider",
        "model_revision": "semantic-discovery-r1",
        "dimensions": 3,
        "history_backfill_enabled": history,
        "sources_per_run": 8,
        "provider_calls_per_run": 16,
        "fragment_target_chars": 600,
        "fragment_overlap_chars": 80,
        "window_max_chars": 1800,
        "processing_version": "source-redaction-v1",
        "query_max_chars": 1000,
        "documents_per_query": 5000,
    }
    service.context = SimpleNamespace(
        get_embedding_provider_by_id=lambda _provider_id: provider,
    )


async def build_index(service, ctx, provider, rows, *, history: bool = False):
    enable_discovery(service, provider, history=history)
    for source_id, content, occurred_at in rows:
        await add_row_with_id(service, ctx, source_id, content, occurred_at)
        await service._run_source_semantic_maintenance(ctx, source_id, "discovery-test")


async def call_discovery(service, ctx, **params):
    counter = int(getattr(service, "_discovery_test_counter", 0)) + 1
    service._discovery_test_counter = counter
    service.identity.resolve_event_context.return_value = replace(
        ctx, message_id=f"discovery-turn-{counter}"
    )
    return await service.tool_discover_sources(SimpleNamespace(), **params)


async def test_semantic_discovery_returns_source_level_matches_and_receipt(service, ctx):
    provider = _DiscoveryProvider()
    await build_index(service, ctx, provider, [
        ("tl_discovery-apple", "苹果是我最近喜欢的水果。", "2026-09-08T00:00:00+08:00"),
        ("tl_discovery-trip", "旅行计划安排在下个月。", "2026-09-08T00:01:00+08:00"),
    ])

    result = await call_discovery(service, ctx, query="苹果")

    assert result["ok"] and result["status"] in {"candidates", "partial"}
    assert result["sources"][0]["source_ref"] == "timeline:tl_discovery-apple"
    assert result["matches"][0]["source_ref"] == "timeline:tl_discovery-apple"
    assert result["matches"][0]["branches"] == ["semantic"]
    assert result["coverage"]["event_coverage"] == "not_established"
    assert result["coverage"]["semantic_status"] == "available"
    assert result["coverage"]["index_coverage"] == "partial"
    assert result["usage"]["query_embedding_calls"] == 1
    state = next(iter(service._reconstruction_states.values()))
    receipt = state["issued_sources"]
    assert receipt
    assert "timeline:tl_discovery-apple" in receipt
    assert receipt["timeline:tl_discovery-apple"]["spans"]


async def test_semantic_fragments_are_collapsed_and_terms_are_fused(service, ctx):
    provider = _DiscoveryProvider()
    long_text = "苹果" + ("细节" * 400)
    await build_index(service, ctx, provider, [
        ("tl_discovery-long", long_text, "2026-09-08T00:00:00+08:00"),
        ("tl_discovery-term", "旅行也提到了苹果。", "2026-09-08T00:01:00+08:00"),
    ])

    result = await call_discovery(service, ctx, query="苹果", terms=["旅行"])

    refs = [item["source_ref"] for item in result["sources"]]
    assert refs.count("timeline:tl_discovery-long") == 1
    assert refs.count("timeline:tl_discovery-term") == 1
    assert next(item for item in result["matches"]
                if item["source_ref"] == "timeline:tl_discovery-long")["branches"] == ["semantic"]
    assert any(match["branches"] == ["semantic", "literal"] for match in result["matches"])
    assert result["coverage"]["literal_status"] == "available"


async def test_literal_terms_can_return_partial_when_provider_fails(service, ctx):
    provider = _DiscoveryProvider(fail=True)
    enable_discovery(service, provider)
    await add_row(service, ctx, "旅行记录", at="2026-09-08T00:00:00+08:00")

    result = await call_discovery(service, ctx, query="相关内容", terms=["旅行"])

    assert result["ok"] and result["status"] == "partial"
    assert result["coverage"]["semantic_status"] == "unavailable"
    assert result["coverage"]["literal_status"] == "available"
    assert result["sources"][0]["excerpt"] == "旅行记录"


async def test_unavailable_without_provider_or_explicit_terms(service, ctx):
    enable_discovery(service, _DiscoveryProvider(fail=True))
    result = await call_discovery(service, ctx, query="没有索引")
    assert not result["ok"] and result["status"] == "unavailable"
    assert result["error"] == "semantic_provider_or_index_unavailable"


async def test_time_range_and_unauthorized_sources_are_enforced(service, ctx):
    provider = _DiscoveryProvider()
    await build_index(service, ctx, provider, [
        ("tl_discovery-old", "苹果旧记录", "2026-09-07T23:00:00+08:00"),
        ("tl_discovery-in", "苹果范围内记录", "2026-09-08T01:00:00+08:00"),
    ])
    hidden = await add_row_with_id(
        service, ctx, "tl_discovery-hidden", "苹果隐藏记录", "2026-09-08T01:30:00+08:00",
        metadata={"owner_bot_id": "other-bot", "bot_id": "other-bot"},
    )

    result = await call_discovery(
        service, ctx, query="苹果", start_at="2026-09-08T00:00:00+08:00",
        end_at="2026-09-08T02:00:00+08:00",
    )

    refs = [item["source_ref"] for item in result["sources"]]
    assert "timeline:tl_discovery-in" in refs
    assert "timeline:tl_discovery-old" not in refs
    assert f"timeline:{hidden}" not in refs


async def test_time_range_keeps_in_range_anchor_when_window_neighbor_is_outside(service, ctx):
    provider = _DiscoveryProvider(prefer_windows=True)
    await build_index(service, ctx, provider, [
        ("tl_discovery-window-old", "苹果旧邻居", "2026-09-08T00:00:00+08:00"),
        ("tl_discovery-window-in", "苹果范围内锚点", "2026-09-08T01:00:00+08:00"),
    ])

    result = await call_discovery(
        service, ctx, query="苹果", start_at="2026-09-08T00:30:00+08:00",
        end_at="2026-09-08T02:00:00+08:00",
    )

    refs = [item["source_ref"] for item in result["sources"]]
    assert result["ok"]
    assert refs == ["timeline:tl_discovery-window-in"]
    match = next(item for item in result["matches"]
                 if item["source_ref"] == "timeline:tl_discovery-window-in")
    assert match["context"] == []
    assert match["context_status"] == "outside_time_range"


async def test_context_budget_counts_only_new_sources(service, ctx):
    provider = _DiscoveryProvider(prefer_windows=True)
    await build_index(service, ctx, provider, [
        ("tl_discovery-budget-a", "苹果甲", "2026-09-08T00:00:00+08:00"),
        ("tl_discovery-budget-b", "苹果乙", "2026-09-08T00:01:00+08:00"),
        ("tl_discovery-budget-c", "苹果丙", "2026-09-08T00:02:00+08:00"),
    ])

    result = await call_discovery(service, ctx, query="苹果", limit=2)

    assert result["ok"]
    assert len(result["sources"]) == 2
    second = next(item for item in result["matches"]
                  if item["source_ref"] == "timeline:tl_discovery-budget-b")
    assert {item["source_ref"] for item in second["context"]} >= {
        "timeline:tl_discovery-budget-a",
    }
    assert second["context_status"] == "not_returned_budget"


async def test_zero_limit_uses_configured_default(service, ctx):
    provider = _DiscoveryProvider()
    enable_discovery(service, provider)
    service.config.raw["memory_reconstruction"]["per_step_limit"] = 1
    await add_row_with_id(service, ctx, "tl_discovery-default-a", "苹果甲", "2026-09-08T00:00:00+08:00")
    await add_row_with_id(service, ctx, "tl_discovery-default-b", "苹果乙", "2026-09-08T00:01:00+08:00")
    await service._run_source_semantic_maintenance(ctx, "tl_discovery-default-a", "discovery-test")
    await service._run_source_semantic_maintenance(ctx, "tl_discovery-default-b", "discovery-test")

    result = await call_discovery(service, ctx, query="苹果", limit=0)

    assert result["ok"]
    assert len(result["sources"]) == 1


async def test_history_generation_reports_complete_coverage(service, ctx):
    provider = _DiscoveryProvider()
    await build_index(service, ctx, provider, [
        ("tl_discovery-complete", "苹果历史记录", "2026-09-08T00:00:00+08:00"),
    ], history=True)

    result = await call_discovery(service, ctx, query="苹果")

    assert result["ok"]
    assert result["coverage"]["index_coverage"] == "complete"


async def test_source_revision_change_rejects_stale_result(service, ctx):
    provider = _DiscoveryProvider()
    await build_index(service, ctx, provider, [
        ("tl_discovery-revision", "苹果原始记录", "2026-09-08T00:00:00+08:00"),
    ])
    original = service.store.get_timeline_by_ids

    async def revised(ids):
        rows = await original(ids)
        with service.store._lock, service.store._transaction_sync():
            service.store._conn.execute(
                "UPDATE timeline SET content='苹果修订记录' WHERE id=?", ("tl_discovery-revision",)
            )
        return rows

    service.store.get_timeline_by_ids = revised
    result = await call_discovery(service, ctx, query="苹果")
    assert not result["ok"] and result["error"] == "source_changed_retry"
    assert not result["sources"]
