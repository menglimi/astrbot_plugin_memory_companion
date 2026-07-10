from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core.models import MemoryRecord, SessionContext
from astrbot_plugin_remember_you.core.retrieval import RetrievalEngine
from astrbot_plugin_remember_you.core.store import MemoryStore
from astrbot_plugin_remember_you.core.visibility import VisibilityPolicy


def _memory(memory_id: str, content: str = "anchor token") -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        content=content,
        lifecycle="stable_memory",
        visibility="shareable",
        importance=0.8,
    )


class _CandidateStore:
    def __init__(
        self,
        *,
        fts: list[MemoryRecord] | None = None,
        current: list[MemoryRecord] | None = None,
    ):
        self.fts = fts or []
        self.current = current or []
        self.keyword_calls = 0

    async def related_knowledge_terms(self, *_args, **_kwargs):
        return []

    async def list_candidate_memories(self, **_kwargs):
        return []

    async def list_current_window_candidate_memories(self, **_kwargs):
        return self.current

    async def list_time_window_candidate_memories(self, *_args, **_kwargs):
        return []

    async def list_fts_candidate_memories(self, *_args, **_kwargs):
        return self.fts

    async def list_keyword_candidate_memories(self, *_args, **_kwargs):
        self.keyword_calls += 1
        return []

    async def get_memories_by_ids(self, _memory_ids):
        return {}

    async def mark_accessed(self, _memory_ids):
        return None


class RetrievalPerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_window_candidates_are_merged_even_without_global_hits(self) -> None:
        current = _memory("current-1", "current window anchor")
        store = _CandidateStore(current=[current])
        engine = RetrievalEngine(
            store,
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
        )
        ctx = SessionContext(session_id="qq:FriendMessage:u1", scope="private", user_id="u1")

        results, _blocked = await engine._rank_candidates("current window anchor", ctx)
        self.assertIn("current-1", {item.memory.id for item in results})
        self.assertEqual(1, engine._rank_path_info["current_window_candidates"])

    async def test_wide_keyword_fallback_is_skipped_when_fts_is_sufficient(self) -> None:
        fts = [_memory(f"fts-{index}") for index in range(80)]
        store = _CandidateStore(fts=fts)
        engine = RetrievalEngine(
            store,
            VisibilityPolicy(enable_acl_rules=False),
            retrieval_mode="basic",
            embedding_enabled=False,
            knowledge_graph_enabled=False,
            keyword_fallback_min_fts_candidates=80,
        )
        ctx = SessionContext(session_id="s1", scope="private", user_id="u1")

        await engine._rank_candidates("anchor token", ctx)
        self.assertEqual(0, store.keyword_calls)
        self.assertFalse(engine._rank_path_info["keyword_fallback_used"])

    async def test_vector_candidate_cache_is_copy_safe_and_revisioned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            store.initialize()
            try:
                record = _memory("vector-1", "vector content v1")
                await store.insert_memory(record)
                await store.upsert_memory_embedding(
                    memory_id=record.id,
                    provider_id="embedder",
                    text_hash="hash-1",
                    vector=[1.0, 0.0],
                )

                first = await store.list_embedding_candidate_rows(provider_id="embedder")
                first[0][1][0] = 99.0
                second = await store.list_embedding_candidate_rows(provider_id="embedder")
                self.assertEqual([1.0, 0.0], second[0][1])

                await store.update_memory_payload(record.id, content="vector content v2")
                third = await store.list_embedding_candidate_rows(provider_id="embedder")
                self.assertEqual("vector content v2", third[0][0].content)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
