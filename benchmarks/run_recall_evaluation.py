"""Offline recall-quality evaluation for the memory retrieval pipeline.

Latency benchmarks cannot catch ranking regressions such as "schedules crowd
out real matches". This harness turns stored injection logs into a labeled
dataset and scores the retrieval engine against it.

Workflow:

1. Export recent real queries from a production database (read-only)::

     python benchmarks/run_recall_evaluation.py export --db <path> \
         --out eval_cases.jsonl --limit 200

2. Label the file: for each line fill ``relevant_ids`` with the memory ids a
   perfect assistant should recall (comma-free strings). Mark queries that
   should return nothing with ``["__none__"]``. Optional ``expected_evidence``
   lists source phrases that should survive injection; ``answer_text`` plus
   ``answer_claims`` scores whether annotated claims had their evidence in the
   final context. Delete uninteresting lines.

3. Score the current engine and compare across code/weight changes::

     python benchmarks/run_recall_evaluation.py evaluate --db <path> \
         --cases eval_cases.jsonl --top-k 6

A ``synthetic`` mode plants known targets among decoys in a temporary store so
the harness itself can be smoke tested without production data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.identity import session_target_id
from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy

NONE_MARKER = "__none__"

SYNTHETIC_TARGETS = [
    ("蓝风铃", "用户最喜欢的花是蓝风铃。", "花"),
    ("周三牙医", "用户预约了周三下午三点看牙医。", "日程"),
    ("无糖拿铁", "用户喝拿铁时不要加糖。", "偏好"),
    ("海边计划", "共同计划是十月去海边看日出。", "约定"),
]


class _NoWriteStore(MemoryStore):
    """Read-only evaluation must not bump access counters or anything else."""

    async def mark_accessed(self, memory_ids: list[str]) -> None:
        return None


def _session_context(scope: str, session_id: str, bot_id: str = "") -> SessionContext:
    scope = (scope or "").strip() or "private"
    target_id = session_target_id(session_id, scope)
    ctx = SessionContext(scope=scope, session_id=session_id, bot_id=bot_id)
    if scope == "group":
        ctx.group_id = target_id
    else:
        ctx.user_id = target_id
    return ctx


def _load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item.get("query") and item.get("relevant_ids"):
                cases.append(item)
    return cases


async def _metrics(
    cases: list[dict],
    engine: RetrievalEngine,
    store: MemoryStore,
    top_k: int,
) -> dict:
    recall_values: list[float] = []
    reciprocal_ranks: list[float] = []
    injected_recall_values: list[float] = []
    injection_distractors = 0
    injection_items = 0
    expected_evidence_count = 0
    included_evidence_count = 0
    answer_claims_scored = 0
    answer_claims_grounded = 0
    unanswerable_count = 0
    unanswerable_injected = 0
    unanswerable_claims = 0
    hit1 = 0
    scored_queries = 0
    empty_expected = 0
    empty_expected_returned = 0
    per_query: list[dict] = []
    composer = InjectionComposer()

    for item in cases:
        relevant = {str(value) for value in item.get("relevant_ids", [])}
        expects_none = relevant == {NONE_MARKER}
        ctx = _session_context(
            item.get("scope", ""), item.get("session_id", ""), str(item.get("bot_id", ""))
        )
        results, blocked = await engine.search_with_diagnostics(
            str(item["query"]), ctx, top_k
        )
        returned_ids = [result.memory.id for result in results]
        ctx.message_text = str(item["query"])
        included_ids: list[str] = []
        injected_text = composer.compose(
            ctx,
            results,
            max_chars=max(300, int(item.get("max_injection_chars") or 1800)),
            included_memory_ids=included_ids,
        )
        expected_evidence_values = item.get("expected_evidence", [])
        if isinstance(expected_evidence_values, str):
            expected_evidence_values = [expected_evidence_values]
        expected_evidence = [
            str(value) for value in expected_evidence_values if str(value)
        ] if isinstance(expected_evidence_values, list) else []
        expected_evidence_count += len(expected_evidence)
        present_evidence = [
            phrase for phrase in expected_evidence if _contains_text(injected_text, phrase)
        ]
        included_evidence_count += len(present_evidence)
        unsupported_claims = 0
        answer_text = str(item.get("answer_text") or "")
        for claim in item.get("answer_claims", []) if isinstance(item.get("answer_claims"), list) else []:
            if isinstance(claim, str):
                claim = {"text": claim}
            if not isinstance(claim, dict):
                continue
            claim_text = str(claim.get("text") or "").strip()
            if not claim_text:
                continue
            if answer_text and claim_text and not _contains_text(answer_text, claim_text):
                continue
            evidence_ids = claim.get("evidence_ids") or claim.get("supported_by_ids") or []
            if isinstance(evidence_ids, str):
                evidence_ids = [evidence_ids]
            if not isinstance(evidence_ids, (list, tuple, set)):
                evidence_ids = []
            evidence_ids = {str(value) for value in evidence_ids}
            answer_claims_scored += 1
            if evidence_ids.intersection(included_ids):
                answer_claims_grounded += 1
            else:
                unsupported_claims += 1

        is_unanswerable = bool(item.get("unanswerable")) or expects_none
        if is_unanswerable:
            unanswerable_count += 1
            unanswerable_injected += int(bool(included_ids))
            unanswerable_claims += unsupported_claims

        if expects_none:
            empty_expected += 1
            if returned_ids:
                empty_expected_returned += 1
            per_query.append(
                {
                    "query": item["query"],
                    "status": "expected_empty",
                    "returned": len(returned_ids),
                    "injected_ids": included_ids,
                    "expected_evidence": len(expected_evidence),
                    "included_evidence": len(present_evidence),
                    "unsupported_answer_claims": unsupported_claims,
                }
            )
            continue

        relevant -= {NONE_MARKER}
        if not relevant:
            continue
        scored_queries += 1
        hits = [index for index, value in enumerate(returned_ids) if value in relevant]
        recall = len(hits) / len(relevant)
        recall_values.append(recall)
        injected_hits = len(relevant.intersection(included_ids))
        injected_recall_values.append(injected_hits / len(relevant))
        injection_items += len(included_ids)
        injection_distractors += sum(memory_id not in relevant for memory_id in included_ids)
        rank = min(hits) + 1 if hits else 0
        # A complete miss contributes zero to MRR and stays in the denominator.
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        if rank:
            if rank == 1:
                hit1 += 1
        per_query.append(
            {
                "query": item["query"],
                "relevant": sorted(relevant),
                "returned": returned_ids,
                "recall": recall,
                "injected_recall": injected_hits / len(relevant),
                "injected_ids": included_ids,
                "expected_evidence": len(expected_evidence),
                "included_evidence": len(present_evidence),
                "unsupported_answer_claims": unsupported_claims,
                "first_rank": rank,
                "top_blocked": [
                    str(entry.get("reason", ""))[:80] for entry in blocked[:2]
                ],
            }
        )

    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    stats = await store.stats()
    return {
        "queries_scored": scored_queries,
        "expected_empty": empty_expected,
        "expected_empty_returned": empty_expected_returned,
        f"recall@{top_k}": round(mean(recall_values), 4),
        "mrr": round(mean(reciprocal_ranks), 4),
        "hit@1": round(hit1 / scored_queries, 4) if scored_queries else 0.0,
        "injected_recall": round(mean(injected_recall_values), 4),
        "injection_distractor_rate": round(injection_distractors / injection_items, 4) if injection_items else 0.0,
        "expected_evidence": expected_evidence_count,
        "injection_evidence_coverage": round(included_evidence_count / expected_evidence_count, 4) if expected_evidence_count else 0.0,
        "unanswerable_cases": unanswerable_count,
        "unanswerable_injection_rate": round(unanswerable_injected / unanswerable_count, 4) if unanswerable_count else 0.0,
        "answer_claims_scored": answer_claims_scored,
        "answer_claim_grounding_rate": round(answer_claims_grounded / answer_claims_scored, 4) if answer_claims_scored else 0.0,
        "unsupported_answer_claim_rate": round((answer_claims_scored - answer_claims_grounded) / answer_claims_scored, 4) if answer_claims_scored else 0.0,
        "unanswerable_answer_claims": unanswerable_claims,
        "store_memories": int(stats.get("total_memories", 0) or 0),
        "per_query": per_query,
    }


def _contains_text(text: str, phrase: str) -> bool:
    compact_text = "".join(str(text or "").split()).casefold()
    compact_phrase = "".join(str(phrase or "").split()).casefold()
    return bool(compact_phrase and compact_phrase in compact_text)


def _build_engine(store: MemoryStore, mode: str) -> RetrievalEngine:
    return RetrievalEngine(
        store,
        VisibilityPolicy(enable_acl_rules=False),
        retrieval_mode=mode,
    )


async def run_export(db_path: Path, out_path: Path, limit: int) -> None:
    store = _NoWriteStore(db_path, read_only=True)
    try:
        logs = await store.recent_injection_logs(limit=limit)
    finally:
        store.close()
    seen: set[str] = set()
    written = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for entry in logs:
            query = (entry.get("query") or "").strip()
            if not query or query in seen:
                continue
            seen.add(query)
            handle.write(
                json.dumps(
                    {
                        "id": entry.get("id", ""),
                        "query": query,
                        "scope": entry.get("scope", ""),
                        "session_id": entry.get("session_id", ""),
                        "selected_ids": entry.get("selected_memory_ids", []),
                        "relevant_ids": [],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            written += 1
    print(f"exported {written} unique queries to {out_path}; fill relevant_ids to label")


async def run_evaluate(db_path: Path, cases_path: Path, top_k: int, mode: str) -> None:
    cases = _load_cases(cases_path)
    if not cases:
        print("no labeled cases found; every line needs a non-empty relevant_ids")
        return
    store = _NoWriteStore(db_path, read_only=True)
    engine = _build_engine(store, mode)
    try:
        report = await _metrics(cases, engine, store, top_k)
    finally:
        store.close()
    summary = {key: value for key, value in report.items() if key != "per_query"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    misses = [entry for entry in report["per_query"] if entry.get("recall", 1.0) == 0.0]
    if misses:
        print(f"\n{len(misses)} queries with zero recall:")
        for entry in misses[:10]:
            blocked = "; ".join(entry.get("top_blocked", []))
            print(f"  - {entry['query'][:60]} | blocked: {blocked}")


async def run_synthetic(decoys: int, top_k: int) -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = MemoryStore(Path(temp) / "eval.db")
        try:
            store.initialize()
            user = EntityRef(kind="user", id="eval-user", name="评估用户")
            bot = EntityRef.bot_self("eval-bot", "评估助手")
            session = "qq:FriendMessage:eval-user"
            for index in range(decoys):
                await store.insert_memory(
                    MemoryRecord(
                        id=f"decoy_{index}",
                        memory_type="conversation_summary",
                        subject=user,
                        object=bot,
                        scope="private",
                        session_id=session,
                        visibility="private_pair",
                        lifecycle="stable_memory",
                        content=f"普通对话片段 {index}，主题编号 {index % 97}。",
                        importance=0.4,
                    )
                )
            cases: list[dict] = []
            for index, (query, content, tag) in enumerate(SYNTHETIC_TARGETS):
                memory_id = f"target_{index}"
                await store.insert_memory(
                    MemoryRecord(
                        id=memory_id,
                        memory_type="explicit_memory",
                        subject=user,
                        object=bot,
                        scope="private",
                        session_id=session,
                        visibility="private_pair",
                        lifecycle="stable_memory",
                        content=content,
                        tags=[tag],
                        importance=0.7,
                    )
                )
                cases.append(
                    {
                        "query": f"你还记得{query}吗",
                        "scope": "private",
                        "session_id": session,
                        "bot_id": "eval-bot",
                        "relevant_ids": [memory_id],
                        "expected_evidence": [content],
                        "answer_text": content,
                        "answer_claims": [
                            {"text": content, "evidence_ids": [memory_id]}
                        ],
                    }
                )
            cases.append(
                {
                    "query": "量子退相干时间是多少？",
                    "scope": "private",
                    "session_id": session,
                    "bot_id": "eval-bot",
                    "relevant_ids": [NONE_MARKER],
                    "unanswerable": True,
                    "answer_text": "我还没有这方面的记录。",
                    "answer_claims": [],
                }
            )
            engine = _build_engine(store, "basic")
            report = await _metrics(cases, engine, store, top_k)
            summary = {key: value for key, value in report.items() if key != "per_query"}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        finally:
            store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="sample queries from injection logs")
    export.add_argument("--db", required=True, type=Path, help="path to memory SQLite db")
    export.add_argument("--out", required=True, type=Path, help="output JSONL template")
    export.add_argument("--limit", type=int, default=200)

    evaluate = sub.add_parser("evaluate", help="score labeled cases against the engine")
    evaluate.add_argument("--db", required=True, type=Path)
    evaluate.add_argument("--cases", required=True, type=Path)
    evaluate.add_argument("--top-k", type=int, default=6)
    evaluate.add_argument("--mode", default="basic", choices=["basic", "auto", "rerank"])

    synthetic = sub.add_parser("synthetic", help="smoke test the harness on planted targets")
    synthetic.add_argument("--decoys", type=int, default=200)
    synthetic.add_argument("--top-k", type=int, default=6)

    args = parser.parse_args()
    if args.command == "export":
        asyncio.run(run_export(args.db, args.out, args.limit))
    elif args.command == "evaluate":
        asyncio.run(run_evaluate(args.db, args.cases, args.top_k, args.mode))
    else:
        asyncio.run(run_synthetic(args.decoys, args.top_k))


if __name__ == "__main__":
    main()
