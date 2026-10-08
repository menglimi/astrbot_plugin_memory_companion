"""Compare original source queries and progress in a temporary SQLite database.

No provider calls, production data, plugin reload or platform delivery.
Run with AstrBot's Python and app/repository on PYTHONPATH.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def stats(values):
    values = sorted(values)
    return {"samples": len(values), "median": round(statistics.median(values), 3),
            "p95": round(values[min(len(values)-1, int(len(values)*0.95))], 3), "max": round(max(values), 3)}


async def measure(samples):
    report = {"schema_version": "query-progress-performance.v1", "observed_at": datetime.now().astimezone().isoformat(),
              "evidence_level": "R", "source_kind": "synthetic_temporary_sqlite", "live_model_calls": 0,
              "production_writes": 0, "host_reloads": 0, "platform_sends": 0,
              "boundary": "Local source search and JSON serialization only; no provider, injection, TTS or delivery latency."}
    with tempfile.TemporaryDirectory(prefix="query-progress-perf-") as folder:
        os.environ["ASTRBOT_ROOT"] = folder
        from core.models import SessionContext, json_dumps
        from core.service import MemoryCompanionService
        logging.disable(logging.CRITICAL)
        service = MemoryCompanionService(context=None, plugin_root=ROOT, data_dir=Path(folder), config={
            "retrieval": {"mode": "basic", "embedding_enabled": False},
            "memory_tools": {"enable_query_progress": False},
        })
        ctx = SessionContext(session_id="qq:FriendMessage:perf-owner", scope="private", platform="qq",
                             user_id="perf-owner", bot_id="perf-bot", persona_id="perf-persona", message_id="warmup")
        service.identity.resolve_event_context = AsyncMock(return_value=ctx)
        service._p5_gate = AsyncMock(return_value={"ok": True})
        try:
            for i in range(240):
                await service.store.add_timeline_event(event_type="bot_response", session_id=ctx.session_id, scope=ctx.scope,
                    subject_id=ctx.bot_id, object_id=ctx.user_id,
                    content=(f"第 {i} 次回答，浅紫色带蕾丝边。" + "这条记录用于临时性能对照。" * 32) if i % 3 == 0 else f"第 {i} 条无关天气闲聊。",
                    occurred_at="2026-09-08T03:41:00+08:00", metadata={"owner_bot_id": ctx.bot_id, "platform": ctx.platform, "persona_id": ctx.persona_id})
            await service.tool_sources(SimpleNamespace(), terms=["浅紫色"])
            times = {"legacy": [], "progress": [], "status": []}
            sizes = {"legacy": [], "progress": [], "compact_progress": []}
            observations = []
            changes = service.store._conn.total_changes
            for i in range(samples):
                order = ("legacy", "progress") if i % 2 == 0 else ("progress", "legacy")
                pair = {}
                for mode in order:
                    service.config.raw["memory_tools"]["enable_query_progress"] = mode == "progress"
                    service.identity.resolve_event_context.return_value = replace(ctx, message_id=f"{mode}-{i}")
                    event = SimpleNamespace()
                    started = time.perf_counter_ns()
                    value = await (service.tool_query(event, "sources", {"terms": ["浅紫色"]}) if mode == "progress"
                                   else service.tool_sources(event, terms=["浅紫色"]))
                    encoded = json_dumps(value)
                    elapsed = (time.perf_counter_ns() - started) / 1e6
                    times[mode].append(elapsed)
                    sizes[mode].append(len(encoded))
                    result = value["result"] if mode == "progress" else value
                    assert value["ok"] and len(result["sources"]) == 6
                    pair[mode] = [s["source_ref"] for s in result["sources"]]
                    if mode == "progress":
                        sizes["compact_progress"].append(len(json_dumps(value["progress"])))
                        started = time.perf_counter_ns()
                        detail = await service.tool_query(event)
                        json_dumps(detail)
                        times["status"].append((time.perf_counter_ns() - started) / 1e6)
                assert pair["legacy"] == pair["progress"]
                observations.append({"sample": i+1, "legacy_ms": round(times["legacy"][-1], 4),
                                     "progress_ms": round(times["progress"][-1], 4)})
            report.update(local_ms={k: stats(v) for k, v in times.items()}, output_chars={k: stats(v) for k,v in sizes.items()},
                          paired_extra_ms=stats([b-a for a,b in zip(times["legacy"], times["progress"])]),
                          source_rows=240, result_rows=6, observations=observations,
                          database_changes_during_queries=service.store._conn.total_changes-changes,
                          p5_gate_calls=service._p5_gate.await_count)
            # Compare native tool definitions, not invented descriptions.
            import evaluate_recall_model as evaluation
            plugin = evaluation.load_plugin()
            from astrbot.core.provider.register import llm_tools
            from astrbot.core.agent.tool import ToolSet
            from core.query_session import bind_query_tool_schema
            names = ["memory_companion_" + op for op in ("recall", "sources", "navigate", "events")]
            for name in [*names, "memory_companion_query"]:
                llm_tools.get_func(name).handler_module_path = plugin.__name__
            assert plugin.bind_event_tool_schema(llm_tools, plugin.__name__)
            assert bind_query_tool_schema(llm_tools, plugin.__name__)
            native = ToolSet(tools=[deepcopy(llm_tools.get_func(name)) for name in [*names, "memory_companion_query"]])
            old = ToolSet(tools=native.tools[:-1])
            service.config.raw["memory_tools"]["enable_query_progress"] = True
            service.config.raw["memory_tools"]["enable_query_notes"] = False
            req = SimpleNamespace(func_tool=native, system_prompt="")
            service._apply_reconstruction_contract(req, ctx, event=SimpleNamespace())
            schema_text = lambda tools: json_dumps([{"name": t.name, "description": t.description, "parameters": t.parameters}
                                                  for t in tools.tools if t.active])
            old_text, new_text = schema_text(old), schema_text(req.func_tool)
            report["tool_definitions"] = {"legacy_tools": old.names(), "progress_tools": req.func_tool.names(),
                                          "legacy_chars": len(old_text), "progress_chars": len(new_text)}
            try:
                import tiktoken
                encoding = tiktoken.get_encoding("cl100k_base")
                report["tool_definitions"].update(tokenizer="cl100k_base_proxy_not_provider_billing",
                    legacy_tokens=len(encoding.encode(old_text)), progress_tokens=len(encoding.encode(new_text)))
            except ImportError:
                report["tool_definitions"]["tokenizer"] = "unavailable_characters_only"
        finally:
            await service.aclose()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("samples must be positive")
    report = asyncio.run(measure(args.samples))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "observations"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
