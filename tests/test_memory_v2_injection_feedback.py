from __future__ import annotations

import unittest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.bot_personal_contract import (
    BOT_PERSONAL_MEMORY_DOMAIN,
    BOT_PERSONAL_SUBJECT,
)
from astrbot_plugin_memory_companion.core.bot_personal_dto import build_bot_personal_archive
from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.memory_lifecycle import evaluate_memory_lifecycle
from astrbot_plugin_memory_companion.core.models import MemoryRecord, SearchResult, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class _DecayConfig:
    @staticmethod
    def int(_path, default=0):
        return default

    @staticmethod
    def bool(_path, default=False):
        return default


class MemoryV2InjectionFeedbackTests(unittest.TestCase):
    def test_important_memory_forgets_slowly_but_not_never(self) -> None:
        service = object.__new__(MemoryCompanionService)
        service.config = _DecayConfig()
        record = MemoryRecord(
            id="old-important",
            memory_type="stable_fact",
            content="一条非常久远但重要的普通事实",
            visibility="private_pair",
            scope="private",
            importance=0.95,
            confidence=0.8,
            occurred_at="2000-01-01T00:00:00+00:00",
            created_at="2000-01-01T00:00:00+00:00",
            last_injected_at="2000-01-01T00:00:00+00:00",
            durability="normal",
        )

        candidate = service._decay_candidate(record)

        self.assertIsNotNone(candidate)
        self.assertGreater(candidate["score"], 0.75)

    def test_pinned_memory_is_never_an_automatic_decay_candidate(self) -> None:
        service = object.__new__(MemoryCompanionService)
        service.config = _DecayConfig()
        record = MemoryRecord(
            id="pinned",
            memory_type="explicit_memory",
            content="用户明确要求永久保留",
            visibility="private_pair",
            scope="private",
            occurred_at="2000-01-01T00:00:00+00:00",
            durability="pinned",
        )

        self.assertIsNone(service._decay_candidate(record))

    def test_decay_consolidation_never_mixes_persona_namespaces(self) -> None:
        service = object.__new__(MemoryCompanionService)
        common = {
            "memory_type": "bot_detail_fragment",
            "content": "过期细节",
            "visibility": "bot_self",
            "scope": "private",
            "session_id": "bot-personal",
            "owner_bot_id": "bot-a",
        }
        persona_a = MemoryRecord(id="a", metadata={"persona_id": "persona-a"}, **common)
        persona_b = MemoryRecord(id="b", metadata={"persona_id": "persona-b"}, **common)

        groups = service._decay_groups([
            {"record": persona_a, "score": 1.0},
            {"record": persona_b, "score": 1.0},
        ])

        self.assertEqual(2, len(groups))
        self.assertNotEqual(groups[0]["bucket"], groups[1]["bucket"])

    def test_expired_and_cross_bot_memories_fail_before_scoring(self) -> None:
        ctx = SessionContext(scope="private", user_id="u1", bot_id="bot-a")
        expired = MemoryRecord(id="expired", content="old", metadata={"valid_to": "2020-01-01T00:00:00+00:00"})
        foreign = MemoryRecord(id="foreign", content="other", metadata={"owner_bot_id": "bot-b"})
        self.assertFalse(evaluate_memory_lifecycle(expired, ctx).eligible)
        self.assertFalse(evaluate_memory_lifecycle(foreign, ctx).eligible)

    def test_bot_personal_memory_requires_matching_persona_context(self) -> None:
        memory = MemoryRecord(
            id="persona-a-memory",
            content="人格 A 的个人时间线",
            owner_bot_id="bot-a",
            metadata={"persona_id": "persona-a"},
        )
        missing = evaluate_memory_lifecycle(
            memory,
            SessionContext(scope="private", user_id="u1", bot_id="bot-a"),
        )
        wrong = evaluate_memory_lifecycle(
            memory,
            SessionContext(scope="private", user_id="u1", bot_id="bot-a", persona_id="persona-b"),
        )
        matching = evaluate_memory_lifecycle(
            memory,
            SessionContext(scope="private", user_id="u1", bot_id="bot-a", persona_id="persona-a"),
        )

        self.assertEqual("persona_context_missing", missing.reason)
        self.assertEqual("persona_mismatch", wrong.reason)
        self.assertTrue(matching.eligible)

    def test_admin_read_all_bypasses_namespace_but_not_safety_lifecycle(self) -> None:
        ctx = SessionContext(
            scope="unknown",
            bot_id="admin-bot",
            persona_id="admin-persona",
        )
        foreign = MemoryRecord(
            id="foreign",
            content="other bot",
            owner_bot_id="bot-b",
            metadata={"persona_id": "persona-b"},
        )
        restricted = MemoryRecord(
            id="restricted",
            content="secret",
            owner_bot_id="bot-b",
            sensitivity="restricted",
        )
        expired = MemoryRecord(
            id="expired",
            content="old",
            owner_bot_id="bot-b",
            valid_to="2020-01-01T00:00:00+00:00",
        )

        self.assertTrue(
            evaluate_memory_lifecycle(
                foreign,
                ctx,
                admin_read_all=True,
            ).eligible
        )
        self.assertEqual(
            "sensitivity=restricted",
            evaluate_memory_lifecycle(
                restricted,
                ctx,
                admin_read_all=True,
            ).reason,
        )
        self.assertEqual(
            "validity=expired",
            evaluate_memory_lifecycle(
                expired,
                ctx,
                admin_read_all=True,
            ).reason,
        )

    def test_rrf_rewards_candidates_found_by_multiple_routes(self) -> None:
        shared = MemoryRecord(id="shared", content="same")
        single = MemoryRecord(id="single", content="one route")
        scores = RetrievalEngine._reciprocal_rank_scores(
            (("fts", [shared, single]), ("vector", [shared])),
        )
        self.assertGreater(scores["shared"], scores["single"])

    def test_composer_reports_only_memory_ids_rendered_inside_budget(self) -> None:
        results = [
            SearchResult(MemoryRecord(id="mem_a", content="ALPHA_UNIQUE_FACT", evidence="source a"), 0.9),
            SearchResult(MemoryRecord(id="mem_b", content="BETA_UNIQUE_FACT", evidence="source b"), 0.8),
        ]
        included: list[str] = []
        text = InjectionComposer().compose(
            SessionContext(scope="private", user_id="u1", session_id="qq:private:u1", message_text="你还记得吗"),
            results,
            max_chars=1800,
            included_memory_ids=included,
        )

        rendered = {
            "mem_a": "ALPHA_UNIQUE_FACT" in text,
            "mem_b": "BETA_UNIQUE_FACT" in text,
        }
        self.assertEqual({memory_id for memory_id, present in rendered.items() if present}, set(included))
        self.assertEqual(len(included), len(set(included)))

    def test_minimal_budget_does_not_reinforce_omitted_memories(self) -> None:
        included: list[str] = []
        text = InjectionComposer().compose(
            SessionContext(scope="private", user_id="u1", session_id="qq:private:u1", message_text="嗯"),
            [SearchResult(MemoryRecord(id="mem_hidden", content="SHOULD_NOT_RENDER"), 0.9)],
            max_chars=300,
            included_memory_ids=included,
        )
        self.assertNotIn("SHOULD_NOT_RENDER", text)
        self.assertEqual([], included)

    def test_bot_personal_rev3_namespace_and_canonical_fields_survive_memory_boundary(self) -> None:
        envelope = {
            "memory_type": "bot_detail_fragment",
            "memory_domain": BOT_PERSONAL_MEMORY_DOMAIN,
            "subject": BOT_PERSONAL_SUBJECT,
            "date": "2026-08-16",
            "window": "afternoon",
            "window_date": "2026-08-16",
            "occurred_at": "2026-08-16T15:00:00+08:00",
            "created_at": "2026-08-16T15:00:00+08:00",
            "updated_at": "2026-08-16T15:00:00+08:00",
            "source_kind": "detail",
            "source_refs": ["archive:detail:one"],
            "certainty": 0.7,
            "evidence_level": "L0",
            "status": "planned",
            "version": 1,
            "idempotency_key": "detail:2026-08-16:15:00:16:00",
            "payload_schema_version": "1.0",
            "payload": {"summary": "short plan", "legacy_flags": ["short_ttl_candidate"]},
            "evidence_kind": "none",
            "canonical_evidence_level": "L0",
            "archive_evidence_level": "L0",
            "evidence_level_mapping": {},
            "authority_kind": "llm",
            "commitment_level": "tentative",
            "epistemic_status": "inferred",
            "content_granularity": "scene",
            "materialization_state": "candidate",
            "fact_eligibility": "none",
            "actor_type": "bot",
            "subject_actor_id": BOT_PERSONAL_SUBJECT,
            "object_actor_id": "",
            "source_actor_id": "system",
            "target_user_id": "",
            "participant_roles": [],
            "runtime_origin_refs": [],
            "expires_at": "2026-08-16T17:00:00+08:00",
            "decision_trace": [],
            "owner_bot_id": "bot-a",
            "persona_id": "persona-a",
            "canonical_schema_version": 3,
        }
        dto = build_bot_personal_archive(envelope)
        serialized = dto.envelope()

        self.assertEqual(3, serialized["canonical_schema_version"])
        self.assertEqual("bot-a", serialized["owner_bot_id"])
        self.assertEqual("persona-a", serialized["persona_id"])
        self.assertEqual("planned", serialized["status"])
        self.assertEqual("none", serialized["fact_eligibility"])
        self.assertEqual(envelope["expires_at"], serialized["expires_at"])


if __name__ == "__main__":
    unittest.main()
