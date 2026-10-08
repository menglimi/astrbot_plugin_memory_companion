"""C2a numeric retrieval comparison in temporary databases; no real embeddings."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark_query_scale import stats


def seed(store, ctx, count, dimension, other_scope):
    from core.models import EntityRef, MemoryRecord, memory_embedding_text_hash
    from core.store import _pack_embedding_vector
    rng = random.Random(91403)
    query = [rng.uniform(-1, 1) for _ in range(dimension)]
    norm = math.hypot(*query)
    query = [v / norm for v in query]
    reference = []
    # Fixture-only bulk load under real revision/redaction triggers.
    with store._lock, store._conn:
        for index in range(count):
            target = index == 0
            other = other_scope and not target
            user = "vector-other" if other else ctx.user_id
            vector = list(query) if target else [rng.uniform(-1, 1) for _ in query]
            norm = math.hypot(*vector)
            vector = [v / norm for v in vector]
            record = MemoryRecord(id="target-old" if target else f"noise-{index:06}",
                memory_type="conversation_summary", subject=EntityRef(kind="user", id=user),
                object=EntityRef.bot_self(ctx.bot_id), owner_bot_id=ctx.bot_id, scope="private", platform="qq",
                session_id="qq:FriendMessage:" + user, visibility="private_pair", lifecycle="stable_memory",
                content=f"换乘城际列车，到站已是深夜。{index}" if target else f"日常散步记录 {index}。",
                importance=.1 if target else .9, occurred_at="2025-01-01T00:00:00+00:00" if target else "2026-09-13T00:00:00+00:00",
                metadata={"persona_id": ctx.persona_id})
            assert store._insert_memory_sync(record, _commit=False) == record.id
            store._conn.execute("INSERT INTO memory_embeddings(memory_id,provider_id,text_hash,dimension,vector,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)", (record.id, "numeric", memory_embedding_text_hash(record), dimension,
                                        _pack_embedding_vector(vector), record.created_at, record.created_at))
            if not other:
                reference.append((math.fsum(a*b for a,b in zip(query, vector)), record.id))
    reference.sort(key=lambda item: (-item[0], item[1]))
    return query, reference[:32]


async def legacy(engine, query, ctx):
    """Explicit C1 algorithm, not the now-changed production entry point."""
    rows = await engine.store.list_embedding_candidate_rows(provider_id="numeric", limit=1200)
    scored = sorted(((engine._cosine_similarity(query, vec), mem) for mem, vec, text_hash in rows
                     if text_hash == engine._embedding_text_hash(mem)), key=lambda item: -item[0])[:32]
    visible, _ = await engine.filter_visible_candidates([mem for _, mem in scored], ctx)
    return [r.memory.id for r in visible], len(rows)


async def probe(count, dimension, other_scope, repeats, path):
    from core.models import SessionContext
    from core.store import MemoryStore
    from core.visibility import VisibilityPolicy
    from core.retrieval import RetrievalEngine
    ctx = SessionContext(scope="private", platform="qq", user_id="vector-owner", bot_id="vector-bot",
                         persona_id="vector-persona", session_id="qq:FriendMessage:vector-owner")
    store = MemoryStore(path)
    store.initialize()
    try:
        started = time.perf_counter()
        query, reference = await asyncio.to_thread(seed, store, ctx, count, dimension, other_scope)
        build_ms = (time.perf_counter()-started)*1000
        provider = SimpleNamespace(get_embedding=AsyncMock(return_value=query))
        engine = RetrievalEngine(store, VisibilityPolicy(), embedding_enabled=True, embedding_provider=provider,
                                 embedding_provider_id="numeric", embedding_score_threshold=0,
                                 knowledge_graph_enabled=False)
        before = store._conn.total_changes
        observations = []
        for repetition in range(repeats + 1):
            for route in (["legacy", "authorized"] if repetition % 2 == 0 else ["authorized", "legacy"]):
                tick = time.perf_counter()
                if route == "legacy":
                    ids, rows = await legacy(engine, query, ctx)
                    info = {"candidate_rows": rows}
                    scores = {}
                else:
                    records, scores, info = await engine._embedding_candidate_memories(
                        "那次临时改变交通方式为什么晚到", ctx, include_pending=False)
                    ids = [r.id for r in records]
                elapsed = (time.perf_counter()-tick)*1000
                if route == "authorized":
                    assert ids == [mid for _, mid in reference], (count, dimension, ids)
                    assert max((abs(score-scores[mid]) for score, mid in reference), default=0) < 1e-12
                    assert info["embedding_candidates"] == (1 if other_scope else count)
                observations.append({"route": route, "repetition": repetition,
                    "phase": "cold" if repetition == 0 else "warm", "local_ms": round(elapsed,3),
                    "target_hit": "target-old" in ids, "ids": ids, "diagnostics": info})
        return {"memory_rows": count, "dimension": dimension, "noise_scope": "other_private" if other_scope else "same_private",
            "seed_ms": round(build_ms,3), "authorized_exact_top32": [mid for _, mid in reference],
            "observations": observations, "warm_ms": {route: stats([x["local_ms"] for x in observations if x["route"]==route and x["phase"]=="warm"])
                                                        for route in ("legacy", "authorized")},
            "stub_embedding_calls": provider.get_embedding.await_count, "real_embedding_calls": 0,
            "static_query_database_changes": store._conn.total_changes-before}
    finally:
        store.close()


async def run(args, root):
    probes=[]
    for count, dimension in [(300, 2), (1201, 2), (2401, 2), (1000, 768), (10000, 768)]:
        for other in (False, True):
            value = await probe(count, dimension, other, args.repeats, root/f"{count}-{dimension}-{other}.db")
            probes.append(value)
            print(json.dumps({k: value[k] for k in ("memory_rows", "dimension", "noise_scope", "warm_ms")}), flush=True)
    return {"schema_version": "vector-search-c2a.v1", "observed_at": datetime.now().astimezone().isoformat(),
        "evidence_level": "R", "numeric_fixture_seed": 91403, "repeats": args.repeats,
        "probes": probes, "production_writes": 0, "host_reloads": 0, "platform_sends": 0,
        "real_model_calls": 0, "real_embedding_calls": 0, "mrq_formal_runs": 0,
        "implementation_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in [ROOT/'core/vector_search.py', ROOT/'core/retrieval.py', ROOT/'core/store.py']},
        "boundaries": ["seeded random numeric vectors; 768 dimensions is not a real embedding accuracy test",
            "target exact query vector deliberately diagnoses admission; not autonomous recall",
            "legacy explicitly reproduces prior importance/time pre-truncation; unequal rows compared",
            "first cold snapshot includes optional numpy import; warm runs exclude first",
            "same local machine with active Bot; not end-to-end or stable production tails",
            "cache hit avoids corpus decoding, but materializes selected rows for validation"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error('repeats must be 1..20')
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix='vector-search-c2a-') as tmp:
        os.environ['ASTRBOT_ROOT']=tmp
        report=asyncio.run(run(args,Path(tmp)))
    from evaluate_recall_model import write_report
    write_report(args.output,report)
    print(json.dumps({'report':str(args.output),'probes':len(report['probes'])}),flush=True)


if __name__=='__main__':
    main()
