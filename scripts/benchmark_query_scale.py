"""C1 structural baseline on temporary synthetic data; no live model or transport.

Scripted query routes demonstrate available/missing evidence, not autonomous
semantic accuracy. Fixture gold IDs are used only by the scorer. Oracle controls
are explicitly labeled and are not counted as model retrieval improvements.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import statistics
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def stats(values):
    ordered = sorted(values)
    return {"samples": len(values), "median": round(statistics.median(values), 3),
            "p95_nearest_rank": round(ordered[math.ceil(.95 * len(ordered)) - 1], 3),
            "max": round(ordered[-1], 3)}


def seed_sources(store, ctx, fixture, size):
    """Fixture-only bulk load; actual SQLite indexes and revision triggers run."""
    rng = random.Random(fixture["seed"])
    start = datetime.fromisoformat("2026-06-01T00:00:00+08:00")
    week = datetime.fromisoformat("2026-09-07T00:00:00+08:00")
    texts = ["楼下的树叶开始发黄了。", "今天看完了一章书，明天接着看。",
             "午后出门散步，路上车很多。", "桌面收拾过了，文件按月份放好。",
             "风有点大，晚上早点休息。", "下班路上看见一家新开的便利店。"]
    rows = []
    key_by_ref = {}
    for index in range(size - len(fixture["sources"])):
        # Half of the noise lies in the queried week; one fifth belongs elsewhere.
        at = (week + timedelta(seconds=rng.randrange(7 * 86400)) if index % 2 == 0
              else start + timedelta(seconds=rng.randrange(90 * 86400)))
        # Keep the known question/answer control consecutive, even at 50k rows.
        if at.strftime("%m-%d %H:%M") in {"09-08 03:40", "09-08 03:41"}:
            at += timedelta(minutes=4)
        rows.append({"key": f"noise-{index}", "at": at.isoformat(), "role": "user",
                     "text": f"{texts[index % len(texts)]} 随手记录 {index}。",
                     "other_owner": index % 5 == 0})
    rows.extend(fixture["sources"])
    inserts = []
    current_count = week_count = 0
    for row in rows:
        identifier = "tl_scale_" + row["key"]
        other = row.get("other_owner", False)
        owner = "scale-other" if other else ctx.user_id
        session = "qq:FriendMessage:" + owner
        metadata = {"owner_bot_id": ctx.bot_id, "platform": ctx.platform, "persona_id": ctx.persona_id}
        inserts.append((identifier, "user_message" if row["role"] == "user" else "bot_response",
                        session, ctx.scope, owner if row["role"] == "user" else ctx.bot_id,
                        owner, row["text"], json.dumps(metadata), row["at"], row["at"]))
        key_by_ref["timeline:" + identifier] = row["key"]
        current_count += not other
        week_count += not other and "2026-09-07" <= row["at"] < "2026-09-14"
    with store._lock, store._conn:
        store._conn.executemany(
            "INSERT INTO timeline(id,event_type,session_id,scope,subject_id,object_id,content,metadata,occurred_at,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)", inserts)
    return key_by_ref, {"total_rows": len(rows), "authorized_rows": current_count,
                        "authorized_week_rows": week_count,
                        "fixture_sha256": hashlib.sha256(json.dumps(fixture, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}


async def run_route(service, ctx, case, route, key_by_ref, repetition, size):
    from core.models import json_dumps
    event = SimpleNamespace()
    service.identity.resolve_event_context.return_value = replace(
        ctx, message_id=f"scale-{size}-{case['id']}-{route['id']}-{repetition}")
    original_fts = service.store._source_fts_enabled
    service.store._source_fts_enabled = original_fts and route.get("fts", True)
    results, calls = [], []
    started = time.perf_counter()
    try:
        for step in route["steps"]:
            params = dict(step.get("parameters", {}))
            if "source_from" in step:
                sources = (results[step["source_from"]].get("result") or {}).get("sources", [])
                if not sources:
                    calls.append({"not_called": "prior_source_missing"})
                    break
                params["source_ref"] = sources[0]["source_ref"]
            if "cursor_from" in step:
                cursor = (results[step["cursor_from"]].get("result") or {}).get("next_cursor")
                if not cursor:
                    calls.append({"not_called": "prior_cursor_missing"})
                    break
                params = {"cursor": cursor}
            tick = time.perf_counter()
            value = await service.tool_query_v2(event, "sources", params)
            encoded = json_dumps(value)
            elapsed = (time.perf_counter() - tick) * 1000
            results.append(value)
            raw = value.get("result") or {}
            calls.append({"parameters": params, "elapsed_ms": round(elapsed, 3), "output_chars": len(encoded),
                          "ok": value["ok"], "error": value.get("error") or raw.get("error"),
                          "coverage": raw.get("coverage", {}), "usage": raw.get("usage", {}),
                          "steps": value.get("progress", {}).get("steps"),
                          "sources": raw.get("sources", [])})
    finally:
        service.store._source_fts_enabled = original_fts
    elapsed = (time.perf_counter() - started) * 1000
    seen = {key_by_ref[s["source_ref"]] for c in calls for s in c.get("sources", [])}
    required = set(case["required_sources"])
    forbidden = set(case.get("forbidden_sources", []))
    final = (results[-1].get("result") or {}) if results else {}
    return {"case": case["id"], "route": route["id"], "repetition": repetition,
            "scripted": True, "oracle_control": bool(route.get("oracle_window") or route.get("oracle_terms")),
            "elapsed_ms": round(elapsed, 3), "required_sources": sorted(required),
            "required_returned": sorted(required & seen), "required_missing": sorted(required - seen),
            "required_source_recall": len(required & seen) / len(required),
            "forbidden_returned": sorted(forbidden & seen), "unique_source_count": len(seen),
            "query_calls": len(results), "errors": [c["error"] for c in calls if c.get("error")],
            "more_available_at_end": final.get("coverage", {}).get("more_available"),
            "event_coverage": final.get("coverage", {}).get("event_coverage"),
            "calls": calls}


async def perturbation_probe(service, ctx):
    """A different owner writes one row; existing global revisions expire a cursor."""
    event = SimpleNamespace()
    service.identity.resolve_event_context.return_value = replace(ctx, message_id="scale-mutation")
    first = await service.tool_query_v2(event, "sources", {"action": "range",
        "start_at": "2026-09-07T00:00:00+08:00", "end_at": "2026-09-14T00:00:00+08:00"})
    raw = first["result"]
    assert first["ok"] and raw["next_cursor"]
    source = raw["sources"][0]
    note = {"text": "已读到这一页，较早的资料还没读完。",
            "evidence": [{k: source[k] for k in ("source_ref", "source_version")}]}
    accepted = await service.tool_query_v2(event, "sources", {"terms": ["赤陶杯"]}, query_note=note)
    before = service.store._conn.total_changes
    await service.store.add_timeline_event(event_type="user_message", session_id="qq:FriendMessage:scale-other",
        scope="private", subject_id="scale-other", object_id="scale-other", content="另一个窗口的新消息。",
        occurred_at="2026-09-14T12:00:00+08:00", metadata={"owner_bot_id": ctx.bot_id,
        "platform": ctx.platform, "persona_id": ctx.persona_id})
    changes = service.store._conn.total_changes - before
    resumed = await service.tool_query_v2(event, "sources", {"cursor": raw["next_cursor"]})
    status = await service.tool_query_v2(event, "status")
    return {"isolated_synthetic_mutation": "one timeline row in another owner session",
            "sqlite_total_changes_including_triggers": changes, "note_before": accepted["note_receipt"],
            "cursor_error_after": resumed["result"]["error"], "progress_after": status["progress"],
            "notes_after": status["notes"], "policy": "current_global_revision; no production mutation"}


async def source_scale(size, repetitions, fixture, root):
    from core.models import SessionContext
    from core.service import MemoryCompanionService
    ctx = SessionContext(scope="private", platform="qq", user_id="scale-owner", bot_id="scale-bot",
        persona_id="scale-persona", session_id="qq:FriendMessage:scale-owner", message_id="seed")
    service = MemoryCompanionService(context=None, plugin_root=ROOT, data_dir=root,
        config={"retrieval": {"mode": "basic", "embedding_enabled": False},
                "memory_reconstruction": {"max_steps": 3, "per_step_limit": 6},
                "memory_tools": {"enable_query_progress": True, "enable_query_notes": True}})
    service.identity.resolve_event_context = AsyncMock(return_value=ctx)
    service._p5_gate = AsyncMock(return_value={"ok": True})
    try:
        tick = time.perf_counter()
        mapping, corpus = await asyncio.to_thread(seed_sources, service.store, ctx, fixture, size)
        corpus["build_ms"] = round((time.perf_counter() - tick) * 1000, 3)
        corpus["fts5_trigram_available"] = service.store._source_fts_enabled
        # One separate warmup is disclosed and excluded from route distributions.
        await service.tool_query_v2(SimpleNamespace(), "sources", {"terms": ["赤陶杯"]})
        before = service.store._conn.total_changes
        observations = []
        for repeat in range(1, repetitions + 1):
            pairs = [(case, route) for case in fixture["cases"] for route in case["routes"]]
            if repeat % 2 == 0:
                pairs.reverse()
            for case, route in pairs:
                observations.append(await run_route(service, ctx, case, route, mapping, repeat, size))
        summaries = []
        for case in fixture["cases"]:
            for route in case["routes"]:
                group = [x for x in observations if x["case"] == case["id"] and x["route"] == route["id"]]
                summaries.append({"case": case["id"], "route": route["id"],
                    "oracle_control": group[0]["oracle_control"], "local_ms": stats([x["elapsed_ms"] for x in group]),
                    "required_source_recall": sorted({x["required_source_recall"] for x in group}),
                    "unique_source_count": sorted({x["unique_source_count"] for x in group}),
                    "query_calls": sum(x["query_calls"] for x in group),
                    "output_chars_median": statistics.median(sum(c.get("output_chars", 0) for c in x["calls"]) for x in group),
                    "errors": sorted({e for x in group for e in x["errors"]}),
                    "forbidden_returned": sorted({e for x in group for e in x["forbidden_returned"]}),
                    "first_observation": group[0]})
        static_changes = service.store._conn.total_changes - before
        mutation = await perturbation_probe(service, ctx)
        return {"corpus": corpus, "repetitions": repetitions, "routes": summaries,
                "route_runs": len(observations), "query_calls": sum(x["query_calls"] for x in observations),
                "static_query_database_changes": static_changes, "warmup_query_calls": 1,
                "mutation_probe": mutation,
                "timings": [{k: v for k, v in x.items() if k != "calls"} for x in observations]}
    finally:
        await service.aclose()


def seed_vectors(store, ctx, count, other_scope):
    """Known orthogonal 2D vectors diagnose candidate admission, not NLP quality."""
    from core.models import MemoryRecord, EntityRef, memory_embedding_text_hash
    from core.store import _pack_embedding_vector
    records, vectors = [], []
    for index in range(count):
        target = index == 0
        other = other_scope and not target
        user = "vector-other" if other else ctx.user_id
        record = MemoryRecord(id="scale-vector-target" if target else f"scale-vector-noise-{index}",
            memory_type="conversation_summary", subject=EntityRef(kind="user", id=user),
            object=EntityRef.bot_self(ctx.bot_id, "基准助手"), scope="private", platform="qq",
            session_id="qq:FriendMessage:" + user, owner_bot_id=ctx.bot_id,
            visibility="private_pair", lifecycle="stable_memory", confidence=.9,
            importance=.1 if target else .8, occurred_at="2026-06-01T12:00:00+08:00" if target else "2026-09-13T12:00:00+08:00",
            content="换乘城际列车，等抵达时已是深夜。" if target else f"日常散步随记 {index}。",
            metadata={"persona_id": ctx.persona_id})
        records.append(record)
    with store._lock, store._conn:
        for record in records:
            assert store._insert_memory_sync(record, _commit=False) == record.id
            vectors.append((record.id, "scale-synthetic-2d", memory_embedding_text_hash(record), 2,
                            _pack_embedding_vector([1., 0.] if record.id == "scale-vector-target" else [0., 1.]),
                            record.created_at, record.created_at))
        store._conn.executemany("INSERT INTO memory_embeddings(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", vectors)


async def legacy_embedding_candidates(engine, query):
    """Freeze C1's pre-C2a admission algorithm for historical reproduction."""
    vector = engine._normalize_vector(await engine._call_embedding_provider(query))
    rows = await engine.store.list_embedding_candidate_rows(
        provider_id=engine.embedding_provider_id, limit=engine.embedding_candidate_limit, include_pending=False)
    scored, stale, mismatch = [], 0, 0
    for memory, values, text_hash in rows:
        current = engine._embedding_text_hash(memory)
        if current and text_hash and current != text_hash:
            stale += 1
            continue
        if len(values) != len(vector):
            mismatch += 1
            continue
        score = engine._cosine_similarity(vector, values)
        if score >= engine.embedding_score_threshold:
            scored.append((score, memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:engine.embedding_top_k]
    return [memory for _, memory in selected], {memory.id: score for score, memory in selected}, {
        "embedding_enabled": True, "embedding_provider_id": engine.embedding_provider_id,
        "embedding_reason": "applied", "embedding_candidates": len(rows), "embedding_hits": len(selected),
        "embedding_stale": stale, "embedding_dim_mismatch": mismatch, "embedding_threshold": engine.embedding_score_threshold}


async def vector_scale(count, other_scope, root):
    from core.models import SessionContext
    from core.service import MemoryCompanionService
    from core.retrieval import RetrievalEngine
    from core.visibility import VisibilityPolicy
    ctx = SessionContext(scope="private", platform="qq", user_id="vector-owner", bot_id="vector-bot",
        persona_id="vector-persona", session_id="qq:FriendMessage:vector-owner", message_id="vector-probe")
    service = MemoryCompanionService(context=None, plugin_root=ROOT, data_dir=root, config={})
    provider = SimpleNamespace(get_embedding=AsyncMock(return_value=[1., 0.]))
    engine = RetrievalEngine(service.store, VisibilityPolicy(), embedding_enabled=True,
        embedding_provider=provider, embedding_provider_id="scale-synthetic-2d", knowledge_graph_enabled=False)
    try:
        await asyncio.to_thread(seed_vectors, service.store, ctx, count, other_scope)
        before = service.store._conn.total_changes
        tick = time.perf_counter()
        admitted, _, info = await legacy_embedding_candidates(engine, "那次临时改变交通方式为什么晚到")
        stock_ms = (time.perf_counter() - tick) * 1000
        visible, _ = await engine.filter_visible_candidates(admitted, ctx)
        # Exhaustive reference deliberately reads more than the production cap.
        # It is an upper-bound control, never described as an equal-cost improvement.
        tick = time.perf_counter()
        all_rows = await service.store.list_embedding_candidate_rows(provider_id="scale-synthetic-2d", limit=count + 1)
        allowed, _ = await engine.filter_visible_candidates([r[0] for r in all_rows], ctx)
        allowed_ids = {r.memory.id for r in allowed}
        ranked = sorted(((engine._cosine_similarity([1., 0.], vector), row.id) for row, vector, _ in all_rows
                         if row.id in allowed_ids), reverse=True)
        exhaustive_ms = (time.perf_counter() - tick) * 1000
        engine.embedding_enabled = False
        literal, _ = await engine._rank_candidates("城际列车", ctx)
        return {"memory_rows": count, "noise_scope": "other_private_session" if other_scope else "same_private_session",
                "vector_type": "synthetic_orthogonal_2d_not_real_embeddings", "provider_stub_calls": provider.get_embedding.await_count,
                "real_model_calls": 0, "stock_limit": engine.embedding_candidate_limit,
                "stock_info": info, "stock_local_ms": round(stock_ms, 3),
                "stock_visible_target_hit": any(x.memory.id == "scale-vector-target" for x in visible),
                "exhaustive_reference": {"rows_read": len(all_rows), "visible_rows": len(allowed_ids),
                    "target_top1": bool(ranked and ranked[0][1] == "scale-vector-target"),
                    "local_ms": round(exhaustive_ms, 3), "equal_resource_budget": False},
                "memory_literal_pre_rerank_top6_target_hit": any(x.memory.id == "scale-vector-target" for x in literal[:6]),
                "static_query_database_changes": service.store._conn.total_changes - before}
    finally:
        await service.aclose()


async def run(args, fixture, root):
    report = {"schema_version": "query-scale-baseline.v1", "observed_at": datetime.now().astimezone().isoformat(),
        "evidence_level": "R", "source_kind": "temporary_synthetic_sqlite", "production_writes": 0,
        "host_reloads": 0, "platform_sends": 0, "real_model_calls": 0, "mrq_formal_runs": 0,
        "fixture": str(args.fixture.relative_to(ROOT)), "budget": {"max_steps": 3, "per_step_limit": 6},
        "boundaries": ["scripted routes are not autonomous model decisions", "gold source IDs used only for scoring",
            "known-minute and paraphrase routes are oracle controls", "two-dimensional vectors diagnose admission only",
            "exhaustive vector reference has a larger resource budget", "not production latency, first token or full MRQ",
            "one disclosed warmup per raw corpus; alternating route order; local threaded store methods unchanged"],
        "source_scales": [], "vector_probes": []}
    for size in args.sizes:
        value = await source_scale(size, args.repeats, fixture, root / f"sources-{size}")
        report["source_scales"].append(value)
        print(json.dumps({"source_rows": size, "route_runs": value["route_runs"], "query_calls": value["query_calls"]}), flush=True)
    for count in args.vector_sizes:
        for other in (False, True):
            value = await vector_scale(count, other, root / f"vectors-{count}-{other}")
            report["vector_probes"].append(value)
            print(json.dumps({k: value[k] for k in ("memory_rows", "noise_scope", "stock_visible_target_hit")}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 50000])
    parser.add_argument("--vector-sizes", nargs="+", type=int, default=[300, 1201, 2401])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--fixture", type=Path, default=ROOT / "docs/evaluations/query-scale-cases.v1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(n < 100 for n in args.sizes) or any(n < 2 for n in args.vector_sizes) or not 1 <= args.repeats <= 20:
        parser.error("sizes >= 100, vector sizes >= 2 and repeats 1..20 required")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    args.fixture = args.fixture.resolve()
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="query-scale-") as tmp:
        os.environ["ASTRBOT_ROOT"] = tmp
        report = asyncio.run(run(args, fixture, Path(tmp)))
    from evaluate_recall_model import write_report
    write_report(args.output, report)
    print(json.dumps({"report": str(args.output), "real_model_calls": 0, "production_writes": 0}), flush=True)


if __name__ == "__main__":
    main()
