from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_remember_you.core.service import MemoryCompanionService


TARGETS = [
    ("蓝风铃", "用户最喜欢的花是蓝风铃。"),
    ("周三牙医", "用户预约了周三下午三点看牙医。"),
    ("无糖拿铁", "用户喝拿铁时不要加糖。"),
    ("海边计划", "共同计划是十月去海边看日出。"),
]


async def run(size: int, repeats: int) -> dict:
    with tempfile.TemporaryDirectory() as temp:
        service = MemoryCompanionService(
            context=None,
            config={
                "retrieval": {"mode": "basic", "embedding_enabled": False},
                "knowledge_graph": {"enabled": False, "retrieval_expansion_enabled": False},
                "visibility": {"enable_acl_rules": True, "allow_group_public_in_private": False},
            },
            plugin_root=ROOT,
            data_dir=Path(temp),
        )
        try:
            session = "qq:FriendMessage:benchmark-user"
            user = EntityRef(kind="user", id="benchmark-user", name="基准用户")
            bot = EntityRef.bot_self("benchmark-bot", "基准助手")
            started = time.perf_counter()
            for index in range(max(0, size - len(TARGETS))):
                await service.store.insert_memory(
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
            target_ids: dict[str, str] = {}
            for index, (query, content) in enumerate(TARGETS):
                memory_id = f"target_{index}"
                target_ids[query] = memory_id
                await service.store.insert_memory(
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
                        importance=0.9,
                    )
                )
            group_secret_id = await service.store.insert_memory(
                MemoryRecord(
                    id="group_secret",
                    memory_type="conversation_summary",
                    subject=EntityRef(kind="user", id="other-user"),
                    object=EntityRef(kind="group", id="private-group"),
                    scope="group",
                    session_id="qq:GroupMessage:private-group",
                    group_id="private-group",
                    visibility="group_public",
                    lifecycle="stable_memory",
                    content="群聊机密口令是银色月桂，禁止流入私聊。",
                    importance=1.0,
                )
            )
            load_ms = (time.perf_counter() - started) * 1000
            ctx = SessionContext(
                session_id=session,
                scope="private",
                platform="qq",
                user_id="benchmark-user",
                bot_id="benchmark-bot",
            )
            latencies: list[float] = []
            hits = 0
            total = 0
            privacy_leaks = 0
            per_query: dict[str, dict[str, int]] = {
                query: {"hits": 0, "runs": 0} for query, _content in TARGETS
            }
            for _ in range(max(1, repeats)):
                for query, _content in TARGETS:
                    tick = time.perf_counter()
                    results = await service.search(query, ctx, top_k=5)
                    latencies.append((time.perf_counter() - tick) * 1000)
                    ids = {item.memory.id for item in results}
                    matched = int(target_ids[query] in ids)
                    hits += matched
                    per_query[query]["hits"] += matched
                    per_query[query]["runs"] += 1
                    privacy_leaks += int(group_secret_id in ids)
                    total += 1
                secret_results = await service.search("银色月桂", ctx, top_k=5)
                privacy_leaks += int(group_secret_id in {item.memory.id for item in secret_results})
            ordered = sorted(latencies)
            p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
            return {
                "dataset_size": size + 1,
                "mode": "basic",
                "embedding_enabled": False,
                "external_retrieval_model_calls": 0,
                "load_ms": round(load_ms, 2),
                "queries": total,
                "hit_at_5": round(hits / total, 4) if total else 0.0,
                "per_query": {
                    query: {
                        **values,
                        "hit_rate": round(values["hits"] / values["runs"], 4) if values["runs"] else 0.0,
                    }
                    for query, values in per_query.items()
                },
                "privacy_leaks": privacy_leaks,
                "latency_ms": {
                    "median": round(statistics.median(latencies), 3),
                    "p95": round(ordered[p95_index], 3),
                    "max": round(max(latencies), 3),
                },
                "notes": [
                    "该脚本只测本地 basic 检索，不代表 Embedding、Rerank 或阶段总结成本。",
                    "跨插件比较必须使用相同数据、模型、硬件和配置。",
                ],
            }
        finally:
            service.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="MemoryCompanion deterministic retrieval benchmark")
    parser.add_argument("--size", type=int, default=1000, help="number of private memories before adding one group secret")
    parser.add_argument("--repeats", type=int, default=5, help="query repetitions")
    parser.add_argument("--output", type=Path, default=None, help="optional UTF-8 JSON result path")
    args = parser.parse_args()
    result = await run(max(10, args.size), max(1, args.repeats))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    asyncio.run(main())
