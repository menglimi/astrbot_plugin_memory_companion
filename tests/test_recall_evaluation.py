from __future__ import annotations

import unittest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SearchResult
from benchmarks.run_recall_evaluation import _metrics


class _Store:
    async def stats(self):
        return {"total_memories": 2}


class _Engine:
    def __init__(self, results_by_query):
        self.results_by_query = results_by_query

    async def search_with_diagnostics(self, query, _ctx, _top_k):
        return self.results_by_query.get(query, []), []


class RecallEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_scores_candidates_injection_evidence_and_unsupported_claims(self):
        user = EntityRef(kind="user", id="u1", name="小王")
        bot = EntityRef.bot_self("b1", "助手")

        def memory(memory_id, content, memory_type="explicit_memory", metadata=None):
            return MemoryRecord(
                id=memory_id,
                memory_type=memory_type,
                subject=user,
                object=bot,
                scope="private",
                session_id="qq:FriendMessage:u1",
                platform="qq",
                visibility="private_pair",
                sayability="direct",
                lifecycle="stable_memory",
                owner_bot_id="b1",
                content=content,
                confidence=0.9,
                metadata=metadata or {},
            )

        flower = memory("flower", "小王最喜欢的花是蓝风铃。")
        raw = memory("raw", "不可注入的原始消息细节。", metadata={"profile_state": "candidate"})
        engine = _Engine(
            {
                "favorite flower": [SearchResult(flower, 1.0, "synthetic")],
                "raw detail": [SearchResult(raw, 1.0, "synthetic")],
            }
        )
        report = await _metrics(
            [
                {
                    "query": "favorite flower",
                    "scope": "private",
                    "session_id": "qq:FriendMessage:u1",
                    "bot_id": "b1",
                    "relevant_ids": ["flower"],
                    "expected_evidence": ["蓝风铃"],
                    "answer_text": "小王最喜欢蓝风铃。",
                    "answer_claims": [{"text": "蓝风铃", "evidence_ids": ["flower"]}],
                },
                {
                    "query": "raw detail",
                    "scope": "private",
                    "session_id": "qq:FriendMessage:u1",
                    "bot_id": "b1",
                    "relevant_ids": ["raw"],
                    "expected_evidence": ["不可注入的原始消息细节"],
                    "answer_text": "原始细节已确认。",
                    "answer_claims": [{"text": "原始细节已确认", "evidence_ids": ["raw"]}],
                },
                {
                    "query": "unanswerable",
                    "scope": "private",
                    "session_id": "qq:FriendMessage:u1",
                    "bot_id": "b1",
                    "relevant_ids": ["__none__"],
                    "unanswerable": True,
                    "answer_text": "我已经完成了。",
                    "answer_claims": [{"text": "我已经完成了", "evidence_ids": []}],
                },
            ],
            engine,
            _Store(),
            3,
        )

        self.assertEqual(1.0, report["recall@3"])
        self.assertEqual(0.5, report["injected_recall"])
        self.assertEqual(0.5, report["injection_evidence_coverage"])
        self.assertEqual(0.0, report["unanswerable_injection_rate"])
        self.assertEqual(3, report["answer_claims_scored"])
        self.assertEqual(0.6667, report["unsupported_answer_claim_rate"])
        self.assertEqual(1, report["unanswerable_answer_claims"])


if __name__ == "__main__":
    unittest.main()
