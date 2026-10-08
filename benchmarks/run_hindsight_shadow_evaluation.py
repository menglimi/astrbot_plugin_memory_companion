"""Compare the local memory retriever with Hindsight on labeled queries.

The Hindsight server receives only records visible to each evaluated session.
Temporary banks are deleted after the run unless --keep-banks is supplied.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

try:
    from . import run_recall_evaluation as local
except ImportError:
    import run_recall_evaluation as local

from astrbot_plugin_memory_companion.core.models import clean_text


def _bank_id(prefix: str, run_id: str, ctx: Any) -> str:
    context_key = "|".join(
        clean_text(value, 240)
        for value in (
            ctx.scope,
            ctx.platform,
            ctx.session_id,
            ctx.user_id,
            ctx.group_id,
            ctx.bot_id,
            ctx.persona_id,
        )
    )
    digest = hashlib.sha256(context_key.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{run_id}-{digest}"


def _request_sync(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Hindsight HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Hindsight request failed: {type(exc).__name__}: {exc}") from exc
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Hindsight returned a non-JSON response") from exc
    return value if isinstance(value, dict) else {}


async def _request(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _request_sync, base_url, api_key, method, path, payload, timeout
    )


async def _all_memories(store: Any) -> list[Any]:
    result: list[Any] = []
    offset = 0
    page_size = 500
    while True:
        page = await store.list_memories(
            limit=page_size, offset=offset, include_pending=False
        )
        result.extend(page)
        if len(page) < page_size:
            return result
        offset += len(page)


def _memory_item(record: Any) -> dict[str, Any]:
    content = clean_text(record.content, 4000)
    evidence = clean_text(record.evidence, 1200)
    if evidence:
        content = f"{content}\nEvidence: {evidence}" if content else evidence
    item: dict[str, Any] = {
        "content": content,
        "context": clean_text(record.memory_type, 100),
        "document_id": clean_text(record.id, 120),
        "metadata": {"source_memory_id": clean_text(record.id, 120)},
        "update_mode": "replace",
    }
    timestamp = clean_text(record.occurred_at or record.created_at, 80)
    if timestamp:
        item["timestamp"] = timestamp
    return item


def _ids_from_recall(response: dict[str, Any], allowed_ids: set[str]) -> tuple[list[str], int]:
    ids: list[str] = []
    unmapped = 0
    for result in response.get("results", []) or []:
        if not isinstance(result, dict):
            continue
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        memory_id = clean_text(
            result.get("document_id") or metadata.get("source_memory_id"), 120
        )
        if not memory_id or memory_id not in allowed_ids:
            unmapped += 1
            continue
        if memory_id not in ids:
            ids.append(memory_id)
    return ids, unmapped


def _score_predictions(
    cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    recall_values: list[float] = []
    reciprocal_ranks: list[float] = []
    hit1 = 0
    scored = 0
    expected_empty = 0
    expected_empty_returned = 0
    latency_values: list[float] = []
    per_query: list[dict[str, Any]] = []
    for index, (case, prediction) in enumerate(zip(cases, predictions)):
        latency_values.append(float(prediction["latency_ms"]))
        relevant = {str(value) for value in case.get("relevant_ids", [])}
        returned = prediction.get("ids", [])[:top_k]
        expects_none = relevant == {local.NONE_MARKER}
        if expects_none:
            expected_empty += 1
            expected_empty_returned += int(bool(returned))
            per_query.append(
                {
                    "case": case.get("id") or index,
                    "status": "expected_empty",
                    "returned_ids": returned,
                    "latency_ms": prediction["latency_ms"],
                }
            )
            continue
        relevant.discard(local.NONE_MARKER)
        if not relevant:
            continue
        scored += 1
        hits = [rank for rank, memory_id in enumerate(returned) if memory_id in relevant]
        rank = min(hits) + 1 if hits else 0
        recall_values.append(len(hits) / len(relevant))
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        hit1 += int(rank == 1)
        per_query.append(
            {
                "case": case.get("id") or index,
                "relevant_ids": sorted(relevant),
                "returned_ids": returned,
                "recall": round(len(hits) / len(relevant), 4),
                "first_rank": rank,
                "unmapped_results": int(prediction.get("unmapped_results", 0) or 0),
                "latency_ms": prediction["latency_ms"],
            }
        )
    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return {
        "queries_scored": scored,
        "expected_empty": expected_empty,
        "expected_empty_returned": expected_empty_returned,
        f"recall@{top_k}": round(mean(recall_values), 4),
        "mrr": round(mean(reciprocal_ranks), 4),
        "hit@1": round(hit1 / scored, 4) if scored else 0.0,
        "mean_recall_latency_ms": round(mean(latency_values), 2),
        "per_query": per_query,
    }


def _context_from_case(case: dict[str, Any]) -> Any:
    ctx = local._session_context(
        case.get("scope", ""), case.get("session_id", ""),
        str(case.get("bot_id", "")),
    )
    session_id = clean_text(case.get("session_id", ""), 240)
    ctx.platform = clean_text(case.get("platform", ""), 80)
    if not ctx.platform and ":" in session_id:
        ctx.platform = session_id.split(":", 1)[0]
    return ctx


def _retrieval_engine(store: Any, args: argparse.Namespace) -> Any:
    policy = local.VisibilityPolicy(
        allow_self_timeline_everywhere=args.allow_self_timeline_everywhere,
        allow_group_public_in_private=args.allow_group_public_in_private,
        hide_pending_review=True,
        include_raw_events=args.include_raw_events,
        enable_acl_rules=True,
    )
    return local.RetrievalEngine(store, policy, retrieval_mode=args.mode)


async def _measure_local(
    cases: list[dict[str, Any]], engine: Any, top_k: int
) -> dict[str, Any]:
    predictions: list[dict[str, Any]] = []
    for case in cases:
        ctx = _context_from_case(case)
        started = time.perf_counter()
        results, _blocked = await engine.search_with_diagnostics(
            str(case["query"]), ctx, top_k
        )
        predictions.append(
            {
                "ids": [result.memory.id for result in results],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
    return _score_predictions(cases, predictions, top_k)


async def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    cases = local._load_cases(args.cases)
    if not cases:
        raise RuntimeError("no labeled cases found; fill relevant_ids in the JSONL file")
    store = local._NoWriteStore(args.db, read_only=True)
    engine = _retrieval_engine(store, args)
    base_url = args.base_url.rstrip("/")
    api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    run_id = uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.bank_prefix):
        store.close()
        raise ValueError("bank prefix may contain only letters, digits, '_' or '-' (max 40)")

    banks: set[str] = set()
    predictions: list[dict[str, Any]] = []
    bank_cache: dict[str, tuple[str, set[str]]] = {}
    sync_counts: dict[str, int] = {}
    sync_latencies: dict[str, float] = {}
    try:
        baseline = await _measure_local(cases, engine, args.top_k)
        all_records = await _all_memories(store)
        for case in cases:
            ctx = _context_from_case(case)
            context_key = "|".join(
                clean_text(value, 240)
                for value in (
                    ctx.scope, ctx.platform, ctx.session_id, ctx.user_id,
                    ctx.group_id, ctx.bot_id, ctx.persona_id,
                )
            )
            if context_key not in bank_cache:
                visible, _blocked = await engine.filter_visible_candidates(
                    all_records, ctx, reason="hindsight_shadow_evaluation"
                )
                allowed = {item.memory.id for item in visible}
                bank_id = _bank_id(args.bank_prefix, run_id, ctx)
                encoded_bank = urllib.parse.quote(bank_id, safe="")
                banks.add(encoded_bank)
                sync_started = time.perf_counter()
                await _request(
                    base_url,
                    api_key,
                    "PUT",
                    f"/v1/default/banks/{encoded_bank}",
                    {
                        "name": f"Memory Companion shadow {run_id}",
                        "retain_extraction_mode": "verbatim",
                        "enable_observations": False,
                    },
                    args.timeout,
                )
                items = [
                    _memory_item(item.memory)
                    for item in visible
                    if clean_text(item.memory.content, 4000)
                ]
                for start in range(0, len(items), 50):
                    await _request(
                        base_url,
                        api_key,
                        "POST",
                        f"/v1/default/banks/{encoded_bank}/memories",
                        {"items": items[start : start + 50], "async": False},
                        args.timeout,
                    )
                sync_latencies[encoded_bank] = round(
                    (time.perf_counter() - sync_started) * 1000, 2
                )
                bank_cache[context_key] = (encoded_bank, allowed)
                sync_counts[encoded_bank] = len(items)

            encoded_bank, allowed_ids = bank_cache[context_key]
            started = time.perf_counter()
            response = await _request(
                base_url,
                api_key,
                "POST",
                f"/v1/default/banks/{encoded_bank}/memories/recall",
                {
                    "query": clean_text(case["query"], 1400),
                    "budget": args.budget,
                    "max_tokens": max(512, args.top_k * 160),
                },
                args.timeout,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            ids, unmapped = _ids_from_recall(response, allowed_ids)
            predictions.append(
                {"ids": ids, "unmapped_results": unmapped, "latency_ms": latency_ms}
            )
    finally:
        if not args.keep_banks:
            for encoded_bank in banks:
                try:
                    await _request(
                        base_url,
                        api_key,
                        "DELETE",
                        f"/v1/default/banks/{encoded_bank}",
                        None,
                        args.timeout,
                    )
                except Exception as exc:
                    print(f"warning: failed to delete temporary Hindsight bank: {exc}")
        store.close()

    hindsight = _score_predictions(cases, predictions, args.top_k)
    return {
        "top_k": args.top_k,
        "baseline": {key: value for key, value in baseline.items() if key != "per_query"},
        "hindsight": {key: value for key, value in hindsight.items() if key != "per_query"},
        "hindsight_sync": {
            "banks": len(sync_counts),
            "visible_records": sum(sync_counts.values()),
            "records_per_bank": list(sync_counts.values()),
            "seed_latency_ms": round(sum(sync_latencies.values()), 2),
            "seed_latency_per_bank_ms": list(sync_latencies.values()),
            "temporary_banks_deleted": not args.keep_banks,
            "bank_ids": list(sync_counts) if args.keep_banks else [],
        },
        "per_query": hindsight["per_query"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, type=Path, help="path to memory SQLite db")
    parser.add_argument("--cases", required=True, type=Path, help="labeled recall JSONL")
    parser.add_argument("--base-url", default="http://127.0.0.1:8888")
    parser.add_argument(
        "--api-key-env", default="HINDSIGHT_API_KEY",
        help="environment variable containing the optional Hindsight API key",
    )
    parser.add_argument("--bank-prefix", default="astrbot-mcomp-shadow")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--mode", default="basic", choices=["basic", "auto", "rerank"])
    parser.add_argument("--budget", default="low", choices=["low", "mid", "high"])
    parser.add_argument(
        "--allow-self-timeline-everywhere",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--allow-group-public-in-private", action="store_true")
    parser.add_argument("--include-raw-events", action="store_true")
    parser.add_argument("--out", type=Path, help="optional UTF-8 JSON report path")
    parser.add_argument(
        "--keep-banks", action="store_true",
        help="keep temporary banks and their uploaded memory data after evaluation",
    )
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    report = asyncio.run(run_evaluation(args))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
