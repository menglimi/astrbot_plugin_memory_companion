"""Opt-in recall evaluation: real model/tools, synthetic sources, temporary storage.

Run with AstrBot's Python and --astrbot-app. No platform transport is installed.
The report contains synthetic dialogue and tool evidence; never provider secrets.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import importlib
import importlib.machinery
import inspect
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/evaluations/recall-model-cases.v1.json"
TOOL_METHODS = {
    "memory_companion_recall": "memory_companion_recall_tool",
    "memory_companion_navigate": "memory_companion_navigate_tool",
    "memory_companion_sources": "memory_companion_sources_tool",
    "memory_companion_events": "memory_companion_events_tool",
    "memory_companion_query": "memory_companion_query_tool",
}


def public_report(value):
    if isinstance(value, dict):
        return {key: public_report(item) for key, item in value.items() if key != "reasoning_content"}
    if isinstance(value, list):
        return [public_report(item) for item in value]
    return value


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(public_report(report), ensure_ascii=False, indent=2) + "\n"
    # Readers always see a complete checkpoint. A transient Windows file lock
    # must not truncate evidence or discard already billed model responses.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.stem + "-", suffix=".tmp", delete=False) as output:
        output.write(text)
        temporary = Path(output.name)
    for attempt in range(4):
        try:
            os.replace(temporary, path)
            return
        except OSError:
            if attempt == 3:
                raise RuntimeError("report_replace_failed; complete_checkpoint=" + str(temporary)) from None
            time.sleep(0.05 * (attempt + 1))


def load_plugin():
    name = "isolated_recall_evaluation"
    package = ModuleType(name)
    package.__path__ = [str(ROOT)]
    package.__package__ = name
    package.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    sys.modules[name] = package
    return importlib.import_module(name + ".main")


def live_provider(config_path):
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial

    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    provider_id = config["provider_settings"]["default_provider_id"]
    model = next(item for item in config["provider"] if item["id"] == provider_id)
    source = next(item for item in config["provider_sources"] if item["id"] == model["provider_source_id"])
    if (not model.get("enable") or not source.get("enable")
            or source.get("type") != "openai_chat_completion"
            or "tool_use" not in model.get("modalities", ["tool_use"])):
        raise RuntimeError("enabled tool-capable Chat Completions provider required")
    return ProviderOpenAIOfficial({**source, **model, "timeout": 60}, config["provider_settings"]), provider_id


async def run_case(plugin, provider, case, fixture, data_dir, request_limit, report, checkpoint, *,
                   query_progress=False, query_notes=False, repetition=1):
    from astrbot.core.agent.tool import ToolSet
    from astrbot.core.provider.entities import ProviderRequest
    from astrbot.core.provider.register import llm_tools

    module = importlib.import_module(plugin.__package__ + ".core.models")
    ctx = module.SessionContext(
        scope="private", platform="qq", session_id="qq:FriendMessage:recall-eval-owner",
        user_id="recall-eval-owner", bot_id="recall-eval-bot", persona_id="recall-eval-persona",
        message_id="recall-eval-" + case["id"], message_text=case["question"],
    )
    service = plugin.MemoryCompanionService(
        context=None, plugin_root=ROOT, data_dir=data_dir,
        config={
            "memory_injection": {"max_chars": 3000, "enable_injection_logs": False},
            "retrieval": {"mode": "basic", "embedding_enabled": False},
            "memory_reconstruction": {"max_steps": 3, "per_step_limit": 6},
            "memory_tools": {"enable_query_progress": query_progress, "enable_query_notes": query_notes},
        },
    )
    service._p5_gate = AsyncMock(return_value={"ok": True})
    service.identity.resolve_event_context = AsyncMock(return_value=ctx)
    event = SimpleNamespace(message_id=ctx.message_id, message_str=case["question"])
    names = [name for name in TOOL_METHODS if query_progress or name != "memory_companion_query"]
    tools = ToolSet(tools=[deepcopy(llm_tools.get_func(name)) for name in names])
    assert all(tools.tools), "native memory tool registration missing"
    bound_plugin = SimpleNamespace(service=service)
    case_report = {
        "id": case["id"], "question": case["question"], "expected": case["expected"],
        "source_fixture": deepcopy(case["sources"]),
        "execution_status": "running", "semantic_status": "needs_review",
        "tools_offered": tools.names(), "source_ids": {}, "requests": [], "tool_calls": [],
        "query_notes_enabled": query_notes, "repetition": repetition,
    }
    report["cases"].append(case_report)
    started = time.monotonic()
    try:
        for row in case["sources"]:
            source_id = await service.store.add_timeline_event(
                event_type="user_message" if row["role"] == "user" else "bot_response",
                session_id=ctx.session_id, scope=ctx.scope,
                subject_id=ctx.user_id if row["role"] == "user" else ctx.bot_id,
                object_id=ctx.user_id, content=row["text"], occurred_at=row["at"],
                metadata={"owner_bot_id": ctx.bot_id, "platform": ctx.platform,
                          "persona_id": ctx.persona_id, "fixture_key": row["key"]},
            )
            case_report["source_ids"][row["key"]] = "timeline:" + source_id
        # Ordinary search and injection run against this temporary store only.
        req = ProviderRequest(prompt=case["question"], contexts=deepcopy(fixture["recent_context"]), func_tool=tools)
        await service.inject_memories(ctx, req, event=event)
        req.system_prompt = (
            "你是陪伴角色，正在和当前用户私聊。请自然简短回答。\n"
            f"当前时间 {fixture['now']}，时区 Asia/Shanghai。\n"
        ) + (req.system_prompt or "")
        service._apply_reconstruction_contract(req, ctx, event=event)
        tools = req.func_tool
        case_report["tools_offered"] = tools.names()
        case_report["tool_definition_chars"] = len(json.dumps([
            {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
            for tool in tools.tools if tool.active], ensure_ascii=False))
        case_report["reconstruction_prompt_offered"] = "<MemoryCompanion-Reconstruction-Contract>" in req.system_prompt
        case_report["general_guidance_offered"] = "<MemoryCompanion-Recall-Guidance>" in req.system_prompt
        case_report["initial_injection"] = getattr(req, "memory_companion_injection_state", {})
        messages = [{"role": "system", "content": req.system_prompt}, *req.contexts,
                    {"role": "user", "content": req.prompt + "\n" + "\n".join(
                        getattr(part, "text", "") for part in req.extra_user_content_parts)}]
        case_report["input_messages"] = deepcopy(messages)
        changes_before = service.store._conn.total_changes
        model_started = time.monotonic()
        for index in range(request_limit):
            request_record = {"index": index + 1, "status": "started"}
            case_report["requests"].append(request_record)
            checkpoint()
            call_started = time.monotonic()
            try:
                response = await asyncio.wait_for(provider.text_chat(
                    contexts=messages, func_tool=tools, tool_choice="auto",
                    request_max_retries=1, max_tokens=3200,
                ), timeout=75)
            except Exception as exc:
                request_record.update(status="failed", error_type=type(exc).__name__,
                                      duration_seconds=round(time.monotonic() - call_started, 3))
                raise RuntimeError("model_request_failed:" + type(exc).__name__) from None
            request_record.update(status="returned", duration_seconds=round(time.monotonic() - call_started, 3),
                                  usage=asdict(response.usage) if response.usage else {},
                                  tools=response.tools_call_name)
            raw = response.raw_completion.choices[0].message.model_dump(exclude_none=True)
            messages.append(raw)
            print(json.dumps({"case": case["id"], "step": index + 1,
                              "tools": response.tools_call_name, "seconds": request_record["duration_seconds"]}, ensure_ascii=False), flush=True)
            if not response.tools_call_name:
                case_report["answer"] = response.completion_text
                case_report["model_to_answer_seconds"] = round(time.monotonic() - model_started, 3)
                case_report["execution_status"] = "answered"
                break
            for call_id, name, arguments in zip(response.tools_call_ids, response.tools_call_name,
                                                response.tools_call_args, strict=True):
                tool_started = time.perf_counter()
                if name not in tools.names():
                    result = {"ok": False, "error": "unavailable_evaluation_tool"}
                else:
                    method = inspect.unwrap(getattr(plugin.MemoryCompanionPlugin, TOOL_METHODS[name]))
                    try:
                        result = json.loads(await method(bound_plugin, event, **arguments))
                    except (TypeError, ValueError) as exc:
                        result = {"ok": False, "error": "invalid_tool_arguments", "error_type": type(exc).__name__}
                case_report["tool_calls"].append({"name": name, "arguments": arguments, "result": result,
                                                 "seconds": round(time.perf_counter() - tool_started, 6)})
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": json.dumps(result, ensure_ascii=False)})
            checkpoint()
        else:
            case_report["execution_status"] = "request_budget_exhausted"
        case_report["store_changes_during_model_loop"] = service.store._conn.total_changes - changes_before
        case_report["transcript"] = messages
    except Exception as exc:
        case_report["execution_status"] = "error"
        case_report["error_type"] = type(exc).__name__
    finally:
        case_report["case_seconds"] = round(time.monotonic() - started, 3)
        await service.aclose()
        checkpoint()


async def evaluate(args, fixture, temporary_root):
    plugin = load_plugin()
    from astrbot.core.provider.register import llm_tools
    # StarManager assigns ownership after import in the running host.
    for name, method in TOOL_METHODS.items():
        tool = llm_tools.get_func(name)
        assert tool is not None and tool.handler is getattr(plugin.MemoryCompanionPlugin, method)
        tool.handler_module_path = plugin.__name__
    assert plugin.bind_event_tool_schema(llm_tools, plugin.__name__)
    assert plugin.bind_query_tool_schema(llm_tools, plugin.__name__)
    report = {
        "schema_version": "recall-model-eval.v1", "observed_at": datetime.now().astimezone().isoformat(),
        "evidence_level": "R", "live_model": True, "production_memory_writes": 0,
        "platform_sends": 0, "host_reloads": 0, "semantic_status": "needs_review",
        "query_progress_enabled": args.query_progress,
        "query_notes_enabled": args.query_notes, "compare_notes": args.compare_notes, "repeats": args.repeats,
        "boundaries": ["synthetic dialogue and identity", "P5 authorization fixture", "temporary SQLite",
                       "real current tool descriptions/handlers and reconstruction prompt",
                       "Memory tools only; request-local progress projection when enabled; no full production persona or other plugins",
                       "no production embedding/reranker/TTS or delivery", "non-streaming final-answer timing"],
        "fixture": str(args.fixture), "cases": [],
    }
    if args.resume:
        previous = json.loads(args.report.read_text(encoding="utf-8"))
        for key in ("fixture", "compare_notes", "repeats", "query_notes_enabled", "query_progress_enabled"):
            if previous.get(key) != report[key]:
                raise ValueError("resume_configuration_mismatch:" + key)
        report = previous
        report.setdefault("resume_events", []).append(datetime.now().astimezone().isoformat())
    provider = None
    try:
        provider, report["provider_id"] = live_provider(args.config)
        report["model"] = provider.get_model()
        for repetition in range(1, args.repeats + 1):
            modes = ([False, True] if repetition % 2 else [True, False]) if args.compare_notes else [args.query_notes]
            for case in fixture["cases"]:
                if args.case and case["id"] not in args.case:
                    continue
                for notes_mode in modes:
                    if any(c["id"] == case["id"] and c.get("repetition", 1) == repetition
                           and c.get("query_notes_enabled", False) == notes_mode for c in report["cases"]):
                        continue
                    case_dir = temporary_root / str(repetition) / ("B" if notes_mode else "A") / case["id"]
                    await run_case(plugin, provider, case, fixture, case_dir,
                        args.max_requests, report, lambda: write_report(args.report, report),
                        query_progress=args.query_progress, query_notes=notes_mode, repetition=repetition)
    finally:
        if provider is not None:
            await provider.terminate()
        write_report(args.report, report)
    return 0 if all(case["execution_status"] == "answered" for case in report["cases"]) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="explicitly enable billable model requests")
    parser.add_argument("--astrbot-app", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--case", action="append")
    parser.add_argument("--query-progress", action="store_true", help="enable A's compact progress on the original tools")
    parser.add_argument("--query-notes", action="store_true", help="enable B's optional source-bound notes")
    parser.add_argument("--compare-notes", action="store_true", help="compare A and B, alternating order on repetitions")
    parser.add_argument("--repeats", type=int, default=1, choices=range(1, 6))
    parser.add_argument("--resume", action="store_true", help="continue missing cases from a complete checkpoint without rerunning recorded samples")
    parser.add_argument("--max-requests", type=int, default=6, choices=range(1, 9))
    args = parser.parse_args()
    if not args.run_live:
        parser.error("live evaluation requires --run-live")
    if args.query_notes or args.compare_notes:
        args.query_progress = True
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    ids = {case["id"] for case in fixture["cases"]}
    if args.case and not set(args.case).issubset(ids):
        parser.error("unknown fixture case")
    # Set the host root before importing AstrBot; constructors cannot reach production data.
    with tempfile.TemporaryDirectory(prefix="memory-recall-model-") as tmp:
        os.environ["ASTRBOT_ROOT"] = tmp
        sys.path.insert(0, str(args.astrbot_app))
        logging.disable(logging.CRITICAL)
        return asyncio.run(evaluate(args, fixture, Path(tmp)))


if __name__ == "__main__":
    raise SystemExit(main())
