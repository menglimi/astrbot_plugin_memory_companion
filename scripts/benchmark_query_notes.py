"""A/B local query-note timing with synthetic sources and no model or transport."""
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
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from benchmark_query_progress import stats


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def measure(samples: int) -> dict:
    from core.models import SessionContext, json_dumps
    from core.service import MemoryCompanionService
    import evaluate_recall_model as evaluation
    from astrbot.core.provider.register import llm_tools
    from astrbot.core.agent.tool import ToolSet

    plugin = evaluation.load_plugin()
    names = ["memory_companion_" + op for op in ("recall", "sources", "navigate", "events", "query")]
    for name in names:
        llm_tools.get_func(name).handler_module_path = plugin.__name__
    assert plugin.bind_query_tool_schema(llm_tools, plugin.__name__)
    assert plugin.bind_event_tool_schema(llm_tools, plugin.__name__)
    report = {"schema_version": "query-note-performance.v1", "observed_at": datetime.now().astimezone().isoformat(),
              "evidence_level": "R", "source_kind": "synthetic_temporary_sqlite", "model_calls": 0,
              "host_reloads": 0, "production_writes": 0, "platform_sends": 0,
              "boundary": "Local metadata, source query, note receipt and JSON only; not first-token or provider timing."}
    with tempfile.TemporaryDirectory(prefix="query-note-performance-") as tmp:
        service = MemoryCompanionService(context=None, config={"memory_tools": {"enable_query_progress": True},
            "retrieval": {"embedding_enabled": False}, "memory_reconstruction": {"max_steps": 3, "per_step_limit": 6}},
            data_dir=Path(tmp), plugin_root=ROOT)
        ctx = SessionContext(scope="private", platform="qq", session_id="qq:FriendMessage:note-perf",
                             user_id="note-perf", bot_id="note-bot", persona_id="note-persona", message_id="warmup")
        service.identity.resolve_event_context = AsyncMock(return_value=ctx)
        service._p5_gate = AsyncMock(return_value={"ok": True})
        try:
            for index in range(240):
                await service.store.add_timeline_event(event_type="bot_response", session_id=ctx.session_id,
                    scope=ctx.scope, subject_id=ctx.bot_id, object_id=ctx.user_id,
                    content=("预约看房：" + "临时资料，待核对后来的调整。" * 30) if index % 3 == 0 else "天气闲聊。",
                    occurred_at="2026-09-08T10:00:00+08:00",
                    metadata={"owner_bot_id": ctx.bot_id, "platform": ctx.platform, "persona_id": ctx.persona_id})
            await service.tool_sources(SimpleNamespace(), terms=["预约看房"])
            measurements = {mode: [] for mode in ("A", "B_empty", "B_note", "B_status")}
            sizes = {mode: [] for mode in measurements}
            paired = []
            definitions = {}
            before = service.store._conn.total_changes
            for index in range(samples):
                order = ["A", "B_empty", "B_note"] if index % 2 == 0 else ["B_note", "B_empty", "A"]
                pair = {"sample": index + 1}
                for mode in order:
                    notes = mode != "A"
                    service.config.raw["memory_tools"]["enable_query_notes"] = notes
                    current = replace(ctx, message_id=f"{index}-{mode}")
                    service.identity.resolve_event_context.return_value = current
                    event = SimpleNamespace()
                    req = SimpleNamespace(func_tool=ToolSet(tools=[deepcopy(llm_tools.get_func(n)) for n in names]), system_prompt="")
                    service._apply_reconstruction_contract(req, current, event=event)
                    definitions[mode] = len(json_dumps([{"name": t.name, "description": t.description, "parameters": t.parameters}
                                                       for t in req.func_tool.tools if t.active]))
                    first = await service.query_for_model(event, "sources", terms=["预约看房"])
                    source = first["result"]["sources"][0]
                    note = ({"text": "已定位这一组预约记录，后来的变更还需继续查。",
                             "evidence": [{k: source[k] for k in ("source_ref", "source_version")}]} if mode == "B_note" else None)
                    start = time.perf_counter_ns()
                    result = await service.query_for_model(event, "sources", terms=["后来的调整"], query_note=note)
                    encoded = json_dumps(result)
                    elapsed = (time.perf_counter_ns() - start) / 1e6
                    assert result["ok"]
                    measurements[mode].append(elapsed)
                    sizes[mode].append(len(encoded))
                    pair[mode] = round(elapsed, 4)
                    if mode == "B_note":
                        assert result["note_receipt"]["status"] == "accepted"
                        start = time.perf_counter_ns()
                        detail = await service.query_for_model(event, "status", note_ids=[result["note_receipt"]["id"]])
                        text = json_dumps(detail)
                        measurements["B_status"].append((time.perf_counter_ns() - start) / 1e6)
                        sizes["B_status"].append(len(text))
                        assert detail["notes"]["items"][0]["text"] == note["text"]
                paired.append(pair)
            report.update(samples=samples, source_rows=240, result_rows=6,
                local_ms={k: stats(v) for k, v in measurements.items()}, output_chars={k: stats(v) for k, v in sizes.items()},
                paired_extra_ms={k: stats([b-a for a,b in zip(measurements["A"], measurements[k])]) for k in ("B_empty", "B_note")},
                tool_definition_chars=definitions, observations=paired,
                database_changes_during_queries=service.store._conn.total_changes-before)
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
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="query-note-host-") as root:
        os.environ["ASTRBOT_ROOT"] = root
        report = asyncio.run(measure(args.samples))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "observations"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
