"""Offline precision probes using synthetic facts and a temporary database.

Run with: python -m benchmarks.audit_memory_precision
Each row reports an expected property and the observed result, not a production
failure rate. The script never connects to a model or a user's memory database.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

from .package_bootstrap import bootstrap_package

bootstrap_package()

from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.models import (
    EntityRef, MemoryRecord, SearchResult, SessionContext, memory_embedding_text_hash,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.summarizer import MemorySummarizer
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy
from .run_recall_evaluation import _metrics


def memory(record_id: str, content: str, *, user: str = "u1", **fields) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        content=content,
        subject=EntityRef(kind="user", id=user),
        object=EntityRef.bot_self("bot1"),
        scope="private",
        session_id=f"qq:FriendMessage:{user}",
        platform="qq",
        visibility="private_pair",
        lifecycle="stable_memory",
        sayability="direct",
        owner_bot_id="bot1",
        confidence=0.8,
        **fields,
    )


def finding(probe: str, expected, observed, **details) -> dict:
    return {
        "probe": probe,
        "expected": expected,
        "observed": observed,
        "matches_expectation": expected == observed,
        **details,
    }


class SyntheticEmbedding:
    async def get_embedding(self, _text: str) -> list[float]:
        return [1.0, 0.0]


async def run() -> list[dict]:
    findings = []
    ctx = SessionContext(
        scope="private", session_id="qq:FriendMessage:u1",
        platform="qq", user_id="u1", bot_id="bot1",
    )
    policy = VisibilityPolicy(enable_acl_rules=False)
    engine = RetrievalEngine(None, policy)

    # Two distinct properties belonging to one user must coexist.
    old = memory("home", "小林的家庭地址是青松路。", occurred_at="2026-08-01T00:00:00+00:00")
    new = memory("office", "小林的公司地址是星河路。", occurred_at="2026-08-02T00:00:00+00:00")
    selected, blocked = engine._collapse_mutable_fact_results(
        "我的家庭地址和公司地址分别是什么？", ctx,
        [SearchResult(old, 2.0, "hits=3"), SearchResult(new, 1.0, "hits=2")],
    )
    findings.append(finding(
        "M-01 distinct_address_facts", ["home", "office"],
        [item.memory.id for item in selected], blocked=blocked,
    ))

    for probe, source, claim in [
        ("M-02 negation", "小林不喜欢香菜。", "小林喜欢香菜。"),
        ("M-02 appointment_time", "小林预约周三下午三点看牙医。", "小林预约周五下午五点看牙医。"),
    ]:
        accepted = MemorySummarizer.fact_supported_by_rows(claim, [{"content": source}])
        findings.append(finding(probe, False, accepted, source=source, claim=claim))

    # The answer is stored in the selected record, beyond its leading facts.
    answer = "蓝色文件夹放在书架第二层"
    facts = [
        "小林在周末整理工作材料，先清点旧项目，再按用途分类记录文档和进度。" * 3,
        "小林整理了近期课程资料，并讨论学习过程中的问题和后续阅读安排。" * 3,
        "小林检查了家庭办公区的物品，并计划继续整理常用工具和备份资料。" * 3,
        f"小林说明{answer}。",
    ]
    selected_memory = memory(
        "detailed-summary", "小林整理资料并交代物品存放位置。",
        metadata={"key_facts": facts},
    )
    item = SearchResult(selected_memory, 3.0, "hits=4;exact=1;expression=mention")
    ctx.message_text = "蓝色文件夹放在哪里？"
    composer = InjectionComposer()
    included: list[str] = []
    text = composer.compose(ctx, [item], max_chars=6000, included_memory_ids=included)
    findings.append(finding(
        "M-03 answer_in_final_context", True, answer in text,
        selected_record_contains_answer=answer in " ".join(facts),
        included_memory_ids=included,
    ))

    with tempfile.TemporaryDirectory(prefix="memory-precision-audit-") as folder:
        store = MemoryStore(Path(folder) / "audit.db")
        store.initialize()
        try:
            target = memory("vector-target", "窗台上的白色花朵。", importance=0.2)
            records = [target] + [
                memory(f"other-{i}", f"另一个人的记录 {i}", user="u2", importance=0.9)
                for i in range(33)
            ]
            for record in records:
                await store.insert_memory(record)
                vector = [0.99, 0.1] if record.id == target.id else [1.0, 0.0]
                await store.upsert_memory_embedding(
                    memory_id=record.id, provider_id="synthetic",
                    text_hash=memory_embedding_text_hash(record), vector=vector,
                )
            vector_engine = RetrievalEngine(
                store, policy, embedding_enabled=True,
                embedding_provider=SyntheticEmbedding(), embedding_provider_id="synthetic",
            )
            candidates, _scores, info = await vector_engine._embedding_candidate_memories(
                "以前养的植物", ctx, include_pending=False,
            )
            visible, _blocked = await vector_engine.filter_visible_candidates(candidates, ctx)
            target_visible, _ = await vector_engine.filter_visible_candidates([target], ctx)
            findings.append(finding(
                "M-04 vector_top_k_before_visibility", [target.id],
                [item.memory.id for item in visible],
                target_visible_in_isolation=bool(target_visible), route_info=info,
            ))
            rows = await store.list_embedding_candidate_rows(provider_id="synthetic", limit=2)
            findings.append(finding(
                "M-04 importance_cap_before_similarity", True,
                any(record.id == target.id for record, _vector, _hash in rows),
                reduced_limit=2, total_rows=len(records),
            ))

            event_id = await store.add_timeline_event(
                event_type="user_message", session_id=ctx.session_id, scope="private",
                subject_id="u1", object_id="bot1", content="小林不喜欢香菜。",
                occurred_at="2026-01-01T00:00:00+00:00",
            )
            summary = memory(
                "referencing-summary", "小林说明了自己的饮食偏好。",
                memory_type="conversation_summary",
                metadata={
                    "summary_refs": [event_id],
                    "source_event_ids": [event_id],
                    "key_facts": ["小林不喜欢香菜。"],
                    "key_facts_with_refs": [{
                        "fact": "小林不喜欢香菜。",
                        "refs": [event_id],
                        "evidence": [{"ref": event_id, "quote": "小林不喜欢香菜。"}],
                    }],
                },
            )
            await store.insert_memory(summary)
            await store.mark_timeline_summarized([event_id])
            cleanup = await store.prune_retained_rows(
                summarized_timeline_cutoff="2026-02-01T00:00:00+00:00",
                injection_log_cutoff="", limit=10,
            )
            surviving = await store.get_timeline_by_ids([event_id])
            retained_summary = await store.get_memory(summary.id)
            retained_trace = retained_summary.metadata["key_facts_with_refs"][0]
            findings.append(finding(
                "M-05 retention_keeps_minimal_evidence", {
                    "source_deleted": True, "source_marked_expired": True,
                    "quote_retained": True,
                }, {
                    "source_deleted": event_id not in surviving,
                    "source_marked_expired": event_id in retained_summary.metadata.get("source_expired_event_ids", []),
                    "quote_retained": retained_trace.get("evidence") == [
                        {"ref": event_id, "quote": "小林不喜欢香菜。"}
                    ],
                },
                cleanup=cleanup,
                summary_still_present=bool(retained_summary),
            ))

            await store.mark_injected([target.id])
            refreshed = await store.get_memory(target.id)
            findings.append({
                "probe": "M-06 exposure_changes_reinforcement",
                "classification": "design_tradeoff",
                "observed_reinforcement": refreshed.reinforcement_score,
                "explicit_user_confirmation": False,
                "note": "Exposure-based rehearsal is intentional, not proof of factual validation.",
            })

            fake_engine = AsyncMock()
            fake_engine.search_with_diagnostics.side_effect = [
                ([SearchResult(target, 1.0, "synthetic")], []), ([], []), ([], []),
            ]
            metrics = await _metrics([
                {
                    "query": "hit", "relevant_ids": [target.id], "scope": "private",
                    "session_id": ctx.session_id, "bot_id": "bot1",
                    "expected_evidence": ["白色花朵"],
                    "answer_text": "窗台上的白色花朵。",
                    "answer_claims": [{"text": "白色花朵", "evidence_ids": [target.id]}],
                },
                {
                    "query": "miss", "relevant_ids": ["absent"], "scope": "private",
                    "session_id": ctx.session_id, "bot_id": "bot1", "unanswerable": True,
                },
                {
                    "query": "unanswerable", "relevant_ids": ["__none__"], "scope": "private",
                    "session_id": ctx.session_id, "bot_id": "bot1", "unanswerable": True,
                    "answer_text": "我处理好了。", "answer_claims": [
                        {"text": "我处理好了", "evidence_ids": []}
                    ],
                },
            ], fake_engine, store, 6)
            findings.append(finding(
                "M-07 mrr_counts_misses", 0.5, metrics["mrr"],
                scored_queries=metrics["queries_scored"], recall=metrics["recall@6"],
            ))
            findings.append(finding(
                "M-08 injection_and_answer_grounding",
                {"injected_recall": 0.5, "injection_evidence_coverage": 1.0, "answer_claims_scored": 2},
                {"injected_recall": metrics["injected_recall"],
                 "injection_evidence_coverage": metrics["injection_evidence_coverage"],
                 "answer_claims_scored": metrics["answer_claims_scored"]},
                unsupported_answer_claim_rate=metrics["unsupported_answer_claim_rate"],
                unanswerable_answer_claims=metrics["unanswerable_answer_claims"],
            ))
        finally:
            store.close()
    return findings


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
