from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.commands import MemoryCompanionCommandHandler
from core.models import EntityRef, MemoryRecord
from core.profile_quality import profile_quality_decision
from core.retrieval import RetrievalEngine
from core.service import MemoryCompanionService
from core.store import MemoryStore
from scripts.repair_profile_noise import (
    APPLY_CONFIRMATION,
    ROLLBACK_CONFIRMATION,
    apply_plan,
    build_repair_plan,
    preview,
    rollback,
)


def profile_record(
    *,
    record_id: str,
    value: str,
    source_id: str,
    dimension: str = "preferred_address",
    polarity: str = "address",
    cardinality: str = "single",
    state: str = "active",
    scope: str = "private",
    group_id: str = "",
    visibility: str = "",
    owner_bot_id: str = "bot-1",
    evidence: str = "",
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        memory_type="user_profile"
        if dimension == "preferred_address"
        else "user_preference",
        subject=EntityRef(kind="user", id="user-1", name="用户一"),
        object=EntityRef(kind="user", id="user-1"),
        scope=scope,
        session_id=f"qq:{scope}:user-1:{source_id}",
        platform="qq",
        message_id=f"message-{source_id}",
        group_id=group_id,
        visibility=visibility
        or ("private_pair" if scope == "private" else "group_public"),
        sayability="direct",
        reality_level="real_user_fact",
        lifecycle="stable_memory" if state == "active" else "raw_event",
        content=f"用户一明确表达过：{dimension} {value}",
        evidence=evidence or f"用户直接声明 {value}",
        confidence=0.95,
        importance=0.68,
        review_status="auto" if state == "active" else "pending",
        tags=["stable_fact", dimension],
        metadata={
            "extractor": "rule_v2",
            "profile_dimension": dimension,
            "profile_value": value,
            "normalized_value": value,
            "profile_polarity": polarity,
            "profile_cardinality": cardinality,
            "extraction_quality": "explicit" if state == "active" else "inferred",
            "extraction_quality_score": 0.95,
            "evidence_strength": "direct_statement"
            if state == "active"
            else "independent_evidence",
            "profile_state": state,
            "quality_gate_passed": True,
            "source_memory_id": source_id,
            "owner_bot_id": owner_bot_id,
            "required_evidence_count": 1 if state == "active" else 2,
        },
    )


class ProfileStorageGovernanceTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> tuple[MemoryStore, Path]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "memory.db"
        store = MemoryStore(path)
        store.initialize()
        self.addCleanup(store.close)
        return store, path

    async def test_legacy_profile_state_backfill_requires_strong_direct_evidence(self) -> None:
        store, _path = self.make_store()
        strong = profile_record(
            record_id="legacy-strong",
            value="无糖拿铁",
            source_id="legacy-strong-source",
            dimension="drink_preference",
            cardinality="multi",
        )
        weak = profile_record(
            record_id="legacy-weak",
            value="燕麦奶",
            source_id="legacy-weak-source",
            dimension="drink_preference",
            cardinality="multi",
        )
        strong.metadata.pop("profile_state", None)
        weak.metadata.pop("profile_state", None)
        weak.metadata["extraction_quality"] = "inferred"
        weak.metadata["evidence_strength"] = "independent_evidence"
        await store.insert_memory(strong)
        await store.insert_memory(weak)

        normalized = store.normalize_legacy_rule_profile_states()

        self.assertEqual(normalized, 1)
        strong_after = await store.get_memory("legacy-strong")
        weak_after = await store.get_memory("legacy-weak")
        self.assertEqual(strong_after.metadata["profile_state"], "active")
        self.assertEqual(strong_after.metadata["profile_status"], "active")
        self.assertEqual(
            strong_after.metadata["profile_state_backfill_rule"],
            "legacy_rule_strong_evidence_v1",
        )
        self.assertEqual(
            profile_quality_decision(strong_after, require_active=True),
            (True, "profile_quality_passed"),
        )
        self.assertNotIn("profile_state", weak_after.metadata)
        self.assertEqual(
            profile_quality_decision(weak_after, require_active=True),
            (False, "profile_state_missing"),
        )

    async def add_rule_portrait_fact(
        self,
        store: MemoryStore,
        *,
        person_id: str,
        dimension: str,
        summary: str,
        version: str = "req036.rule.v1",
        suffix: str = "a",
    ) -> str:
        result = await store.upsert_portrait_fact(
            {
                "person_id": person_id,
                "dimension": dimension,
                "normalized_claim_hash": suffix * 64,
                "claim_summary": summary,
                "portrait_tier": "base",
                "producer_kind": "rule_explicit",
                "producer_version": version,
                "derivation_kind": "explicit_statement",
                "epistemic_status": "explicit",
                "source_scope": "private",
                "usable_scope": "source_only",
                "confidence": 0.92,
                "sensitivity": "low",
                "status": "active",
                "evidence_hashes": [suffix * 64],
                "operation_id": f"portrait-source-{suffix}",
            }
        )
        self.assertTrue(result["ok"])
        fact_id = result["fact_id"]
        queued = await store.enqueue_portrait_learning(
            person_id=person_id,
            fact_id=fact_id,
            evidence_hash=suffix * 64,
        )
        self.assertTrue(queued["ok"])
        return fact_id

    async def test_candidate_evidence_is_distinct_and_promotes_atomically(self) -> None:
        store, _path = self.make_store()
        first = profile_record(
            record_id="candidate-1",
            value="无糖拿铁",
            source_id="timeline-1",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
        )
        result = await store.upsert_profile_candidate(first)
        self.assertEqual("candidate", result["profile_status"])
        self.assertEqual(1, result["evidence_count"])

        replay = await store.upsert_profile_candidate(first)
        self.assertFalse(replay["evidence_added"])
        self.assertEqual(1, replay["evidence_count"])

        second = profile_record(
            record_id="candidate-2",
            value="无糖拿铁",
            source_id="timeline-2",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
            evidence="用户补充说每次都点无糖拿铁",
        )
        promoted = await store.upsert_profile_candidate(second)
        self.assertEqual("active", promoted["profile_status"])
        self.assertEqual(2, promoted["evidence_count"])
        canonical = await store.get_memory(promoted["memory_id"])
        self.assertEqual("stable_memory", canonical.lifecycle)
        self.assertEqual("auto", canonical.review_status)
        self.assertEqual(2, canonical.metadata["independent_evidence_count"])

    async def test_low_quality_independent_evidence_remains_candidate(self) -> None:
        store, _path = self.make_store()
        first = profile_record(
            record_id="low-quality-1",
            value="无糖拿铁",
            source_id="timeline-low-quality-1",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
            evidence="用户说最近会点无糖拿铁",
        )
        second = profile_record(
            record_id="low-quality-2",
            value="无糖拿铁",
            source_id="timeline-low-quality-2",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
            evidence="用户另一次说有时选择无糖拿铁",
        )
        first.metadata["extraction_quality_score"] = 0.4
        second.metadata["extraction_quality_score"] = 0.4

        initial = await store.upsert_profile_candidate(first)
        accumulated = await store.upsert_profile_candidate(second)

        self.assertEqual("candidate", initial["profile_status"])
        self.assertEqual("candidate", accumulated["profile_status"])
        self.assertEqual(2, accumulated["evidence_count"])
        self.assertEqual(0, accumulated["independent_evidence_count"])
        canonical = await store.get_memory(accumulated["memory_id"])
        self.assertEqual("candidate", canonical.metadata["profile_state"])
        self.assertEqual(0.4, canonical.metadata["extraction_quality_score"])
        self.assertEqual("raw_event", canonical.lifecycle)
        self.assertEqual("pending", canonical.review_status)

    async def test_low_quality_evidence_cannot_corroborate_high_quality_candidate(
        self,
    ) -> None:
        store, _path = self.make_store()
        high_quality = profile_record(
            record_id="mixed-quality-high",
            value="无糖拿铁",
            source_id="timeline-mixed-quality-high",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
            evidence="用户说自己经常点无糖拿铁",
        )
        low_quality = profile_record(
            record_id="mixed-quality-low",
            value="无糖拿铁",
            source_id="timeline-mixed-quality-low",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
            evidence="低可信来源猜测用户或许选择无糖拿铁",
        )
        high_quality.metadata["extraction_quality_score"] = 0.9
        low_quality.metadata["extraction_quality_score"] = 0.1

        await store.upsert_profile_candidate(high_quality)
        accumulated = await store.upsert_profile_candidate(low_quality)

        self.assertEqual("candidate", accumulated["profile_status"])
        self.assertEqual(2, accumulated["evidence_count"])
        self.assertEqual(1, accumulated["independent_evidence_count"])
        canonical = await store.get_memory(accumulated["memory_id"])
        self.assertEqual("candidate", canonical.metadata["profile_state"])
        self.assertEqual("raw_event", canonical.lifecycle)
        self.assertEqual("pending", canonical.review_status)

    async def test_single_upsert_cannot_forge_aggregate_evidence(self) -> None:
        store, _path = self.make_store()
        forged = profile_record(
            record_id="forged-aggregate-evidence",
            value="无糖拿铁",
            source_id="timeline-forged-aggregate-evidence",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
            evidence="用户说自己经常点无糖拿铁",
        )
        forged.metadata["extraction_quality_score"] = 0.9
        forged.metadata["profile_evidence_refs"] = ["forged-a", "forged-b"]
        forged.metadata["profile_statement_fingerprints"] = [
            "forged-statement-a",
            "forged-statement-b",
        ]

        result = await store.upsert_profile_candidate(forged)

        self.assertEqual("candidate", result["profile_status"])
        self.assertEqual(1, result["evidence_count"])
        self.assertEqual(1, result["independent_evidence_count"])
        canonical = await store.get_memory(result["memory_id"])
        self.assertEqual(
            ["timeline-forged-aggregate-evidence"],
            canonical.metadata["profile_evidence_refs"],
        )
        self.assertNotIn(
            "forged-statement-a",
            canonical.metadata["profile_statement_fingerprints"],
        )

    async def test_non_finite_profile_quality_score_is_rejected(self) -> None:
        store, _path = self.make_store()
        record = profile_record(
            record_id="non-finite-score",
            value="宝宝",
            source_id="timeline-non-finite",
        )
        record.metadata["extraction_quality_score"] = float("nan")

        result = await store.upsert_profile_candidate(record)

        self.assertFalse(result["ok"])
        self.assertEqual("profile_candidate_invalid", result["code"])
        self.assertIsNone(await store.get_memory(record.id))

    async def test_upsert_rejects_incomplete_or_inconsistent_profile_values(
        self,
    ) -> None:
        cases = {
            "missing_profile_value": lambda metadata: metadata.pop("profile_value"),
            "missing_normalized_value": lambda metadata: metadata.pop(
                "normalized_value"
            ),
            "normalized_value_mismatch": lambda metadata: metadata.__setitem__(
                "normalized_value", "另一个称呼"
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                store, _path = self.make_store()
                record = profile_record(
                    record_id=f"invalid-{label}",
                    value="宝宝",
                    source_id=f"timeline-invalid-{label}",
                )
                mutate(record.metadata)

                result = await store.upsert_profile_candidate(record)

                self.assertFalse(result["ok"])
                self.assertEqual("profile_candidate_invalid", result["code"])
                self.assertEqual("", result["memory_id"])
                self.assertEqual(
                    [], await store.list_rule_profile_memories(include_archived=True)
                )
                queue_count = store._conn.execute(
                    "SELECT COUNT(*) AS count FROM review_queue"
                ).fetchone()["count"]
                self.assertEqual(0, queue_count)

    async def test_same_statement_from_distinct_sources_does_not_promote(self) -> None:
        store, _path = self.make_store()
        first = profile_record(
            record_id="candidate-same-1",
            value="无糖拿铁",
            source_id="timeline-same-1",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
        )
        second = profile_record(
            record_id="candidate-same-2",
            value="无糖拿铁",
            source_id="timeline-same-2",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
        )

        await store.upsert_profile_candidate(first)
        result = await store.upsert_profile_candidate(second)

        self.assertEqual("candidate", result["profile_status"])
        self.assertEqual(2, result["evidence_count"])
        self.assertEqual(1, result["independent_evidence_count"])
        canonical = await store.get_memory(result["memory_id"])
        self.assertEqual("raw_event", canonical.lifecycle)
        self.assertEqual("pending", canonical.review_status)

    async def test_distinct_statements_from_one_source_do_not_promote(self) -> None:
        store, _path = self.make_store()
        first = profile_record(
            record_id="candidate-one-source-1",
            value="无糖拿铁",
            source_id="timeline-one-source",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
        )
        second = profile_record(
            record_id="candidate-one-source-2",
            value="无糖拿铁",
            source_id="timeline-one-source",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="candidate",
            evidence="同一条时间线里的另一种表述",
        )

        await store.upsert_profile_candidate(first)
        result = await store.upsert_profile_candidate(second)

        self.assertEqual("candidate", result["profile_status"])
        self.assertEqual(1, result["evidence_count"])
        self.assertEqual(1, result["independent_evidence_count"])

    async def test_inferred_candidate_cannot_force_single_evidence_activation(
        self,
    ) -> None:
        store, _path = self.make_store()
        inferred = profile_record(
            record_id="forced-active",
            value="无糖拿铁",
            source_id="timeline-forced",
            dimension="drink_preference",
            polarity="like",
            cardinality="multi",
            state="active",
        )
        inferred.metadata.update(
            {
                "extraction_quality": "inferred",
                "evidence_strength": "independent_evidence",
                "required_evidence_count": 1,
            }
        )

        result = await store.upsert_profile_candidate(inferred)

        self.assertEqual("candidate", result["profile_status"])
        canonical = await store.get_memory(result["memory_id"])
        self.assertEqual(2, canonical.metadata["required_evidence_count"])
        self.assertEqual("raw_event", canonical.lifecycle)

    async def test_polarity_and_acl_domain_are_part_of_the_merge_key(self) -> None:
        store, _path = self.make_store()
        like = profile_record(
            record_id="like",
            value="烤肉",
            source_id="timeline-like",
            dimension="food_preference",
            polarity="like",
            cardinality="multi",
        )
        dislike = profile_record(
            record_id="dislike",
            value="烤肉",
            source_id="timeline-dislike",
            dimension="food_preference",
            polarity="dislike",
            cardinality="multi",
        )
        group_like = profile_record(
            record_id="group-like",
            value="烤肉",
            source_id="timeline-group",
            dimension="food_preference",
            polarity="like",
            cardinality="multi",
            scope="group",
            group_id="group-1",
        )
        ids = {
            (await store.upsert_profile_candidate(like))["memory_id"],
            (await store.upsert_profile_candidate(dislike))["memory_id"],
            (await store.upsert_profile_candidate(group_like))["memory_id"],
        }
        self.assertEqual(3, len(ids))
        rows = await store.list_rule_profile_memories(include_archived=False)
        self.assertEqual(3, len(rows))

    async def test_new_single_value_supersedes_only_inside_same_acl_domain(
        self,
    ) -> None:
        store, _path = self.make_store()
        old = await store.upsert_profile_candidate(
            profile_record(record_id="old", value="宝宝", source_id="timeline-old")
        )
        group = await store.upsert_profile_candidate(
            profile_record(
                record_id="group",
                value="宝宝",
                source_id="timeline-group",
                scope="group",
                group_id="group-1",
            )
        )
        new = await store.upsert_profile_candidate(
            profile_record(record_id="new", value="主人", source_id="timeline-new")
        )
        previous = await store.get_memory(old["memory_id"])
        group_record = await store.get_memory(group["memory_id"])
        self.assertEqual("superseded", previous.metadata["profile_state"])
        self.assertEqual(new["memory_id"], previous.supersedes_id)
        self.assertEqual("active", group_record.metadata["profile_state"])

    async def test_single_value_dimension_ignores_declared_multi_cardinality(
        self,
    ) -> None:
        store, _path = self.make_store()
        previous = await store.upsert_profile_candidate(
            profile_record(
                record_id="declared-multi-old",
                value="宝宝",
                source_id="timeline-declared-multi-old",
                cardinality="multi",
            )
        )
        current = await store.upsert_profile_candidate(
            profile_record(
                record_id="declared-multi-new",
                value="主人",
                source_id="timeline-declared-multi-new",
                cardinality="multi",
            )
        )

        previous_record = await store.get_memory(previous["memory_id"])
        current_record = await store.get_memory(current["memory_id"])
        self.assertEqual("superseded", previous_record.metadata["profile_state"])
        self.assertEqual(current["memory_id"], previous_record.supersedes_id)
        self.assertEqual("single", current_record.metadata["profile_cardinality"])
        rows = await store.list_rule_profile_memories(include_archived=True)
        active = [
            row
            for row in rows
            if row.metadata.get("profile_dimension") == "preferred_address"
            and row.metadata.get("profile_state") == "active"
        ]
        self.assertEqual([current["memory_id"]], [row.id for row in active])

    async def test_single_value_round_trip_preserves_superseded_history(
        self,
    ) -> None:
        store, _path = self.make_store()
        first = await store.upsert_profile_candidate(
            profile_record(
                record_id="address-a-1",
                value="宝宝",
                source_id="timeline-a-1",
                evidence="evidence-a-1",
            )
        )
        second = await store.upsert_profile_candidate(
            profile_record(
                record_id="address-b",
                value="主人",
                source_id="timeline-b",
                evidence="evidence-b",
            )
        )
        third = await store.upsert_profile_candidate(
            profile_record(
                record_id="address-a-2",
                value="宝宝",
                source_id="timeline-a-2",
                evidence="evidence-a-2",
            )
        )

        self.assertNotEqual(first["memory_id"], third["memory_id"])
        first_record = await store.get_memory(first["memory_id"])
        second_record = await store.get_memory(second["memory_id"])
        third_record = await store.get_memory(third["memory_id"])
        self.assertEqual("evidence-a-1", first_record.evidence)
        self.assertEqual("archived", first_record.lifecycle)
        self.assertEqual("superseded", first_record.metadata["profile_state"])
        self.assertEqual(second["memory_id"], first_record.supersedes_id)
        self.assertEqual("archived", second_record.lifecycle)
        self.assertEqual(third["memory_id"], second_record.supersedes_id)
        self.assertEqual("evidence-a-2", third_record.evidence)

        rows = await store.list_rule_profile_memories(include_archived=True)
        active = [
            row
            for row in rows
            if row.metadata.get("profile_dimension") == "preferred_address"
            and row.metadata.get("profile_state") == "active"
        ]
        self.assertEqual([third["memory_id"]], [row.id for row in active])
        self.assertEqual(3, len(rows))

    async def test_command_promote_confirms_profile_candidate_atomically(
        self,
    ) -> None:
        store, _path = self.make_store()
        previous = await store.upsert_profile_candidate(
            profile_record(
                record_id="address-old",
                value="宝宝",
                source_id="timeline-old",
            )
        )
        candidate = await store.upsert_profile_candidate(
            profile_record(
                record_id="address-candidate",
                value="主人",
                source_id="timeline-candidate",
                state="candidate",
            )
        )
        handler = MemoryCompanionCommandHandler(
            type("ServiceStub", (), {"store": store})(),
            "test",
        )

        await handler.promote(candidate["memory_id"])

        confirmed = await store.get_memory(candidate["memory_id"])
        superseded = await store.get_memory(previous["memory_id"])
        self.assertEqual("active", confirmed.metadata["profile_state"])
        self.assertEqual("active", confirmed.metadata["profile_status"])
        self.assertEqual("confirmed", confirmed.metadata["extraction_quality"])
        self.assertEqual("user_confirmed", confirmed.metadata["evidence_strength"])
        self.assertEqual("stable_memory", confirmed.lifecycle)
        self.assertEqual("auto", confirmed.review_status)
        self.assertEqual(
            (True, "profile_quality_passed"),
            profile_quality_decision(confirmed),
        )
        self.assertEqual(
            (True, "profile_quality_compatible"),
            RetrievalEngine._profile_retrieval_decision(confirmed),
        )
        self.assertEqual("superseded", superseded.metadata["profile_state"])
        self.assertEqual(candidate["memory_id"], superseded.supersedes_id)

        rows = await store.list_rule_profile_memories(include_archived=True)
        active = [
            row
            for row in rows
            if row.metadata.get("profile_dimension") == "preferred_address"
            and row.metadata.get("profile_state") == "active"
        ]
        self.assertEqual([candidate["memory_id"]], [row.id for row in active])

    async def test_manual_approval_cannot_override_single_dimension_with_multi(
        self,
    ) -> None:
        store, _path = self.make_store()
        previous = await store.upsert_profile_candidate(
            profile_record(
                record_id="manual-multi-old",
                value="宝宝",
                source_id="timeline-manual-multi-old",
            )
        )
        candidate = profile_record(
            record_id="manual-multi-candidate",
            value="主人",
            source_id="timeline-manual-multi-candidate",
            cardinality="multi",
            state="candidate",
        )
        await store.insert_memory(candidate, "profile_candidate_requires_review")

        changed = await store.update_review_status(candidate.id, "auto")

        self.assertTrue(changed)
        previous_record = await store.get_memory(previous["memory_id"])
        approved = await store.get_memory(candidate.id)
        self.assertEqual("superseded", previous_record.metadata["profile_state"])
        self.assertEqual(candidate.id, previous_record.supersedes_id)
        self.assertEqual("active", approved.metadata["profile_state"])
        self.assertEqual("single", approved.metadata["profile_cardinality"])
        self.assertEqual("stable_memory", approved.lifecycle)
        rows = await store.list_rule_profile_memories(include_archived=True)
        active = [
            row
            for row in rows
            if row.metadata.get("profile_dimension") == "preferred_address"
            and row.metadata.get("profile_state") == "active"
        ]
        self.assertEqual([candidate.id], [row.id for row in active])

    async def test_manual_approval_rejects_rule_profile_without_dimension(
        self,
    ) -> None:
        store, _path = self.make_store()
        candidate = profile_record(
            record_id="manual-missing-dimension",
            value="主人",
            source_id="timeline-manual-missing-dimension",
            state="candidate",
        )
        candidate.metadata.pop("profile_dimension")
        await store.insert_memory(candidate, "profile_candidate_requires_review")

        changed = await store.update_review_status(candidate.id, "auto")

        self.assertFalse(changed)
        unchanged = await store.get_memory(candidate.id)
        self.assertEqual("candidate", unchanged.metadata["profile_state"])
        self.assertEqual("raw_event", unchanged.lifecycle)
        self.assertEqual("pending", unchanged.review_status)

    async def test_manual_approval_rejects_incomplete_profile_without_superseding(
        self,
    ) -> None:
        store, _path = self.make_store()
        current = await store.upsert_profile_candidate(
            profile_record(
                record_id="address-current",
                value="宝宝",
                source_id="timeline-current",
            )
        )
        incomplete = profile_record(
            record_id="address-incomplete",
            value="主人",
            source_id="timeline-incomplete",
            state="candidate",
        )
        incomplete.metadata.pop("normalized_value")
        await store.insert_memory(incomplete, "profile_candidate_requires_review")

        changed = await store.update_review_status(incomplete.id, "auto")

        self.assertFalse(changed)
        current_record = await store.get_memory(current["memory_id"])
        incomplete_record = await store.get_memory(incomplete.id)
        self.assertEqual("active", current_record.metadata["profile_state"])
        self.assertEqual("candidate", incomplete_record.metadata["profile_state"])
        self.assertEqual("pending", incomplete_record.review_status)

    async def test_manual_approval_requires_consistent_profile_values(self) -> None:
        cases = {
            "missing_value": lambda metadata: metadata.pop("profile_value"),
            "missing_normalized": lambda metadata: metadata.pop("normalized_value"),
            "mismatched": lambda metadata: metadata.__setitem__(
                "normalized_value", "另一个称呼"
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                store, _path = self.make_store()
                current = await store.upsert_profile_candidate(
                    profile_record(
                        record_id=f"current-{label}",
                        value="宝宝",
                        source_id=f"current-{label}",
                    )
                )
                candidate = profile_record(
                    record_id=f"candidate-{label}",
                    value="主人",
                    source_id=f"candidate-{label}",
                    state="candidate",
                )
                mutate(candidate.metadata)
                await store.insert_memory(
                    candidate, "profile_candidate_requires_review"
                )

                changed = await store.update_review_status(candidate.id, "auto")

                self.assertFalse(changed)
                self.assertEqual(
                    "active",
                    (await store.get_memory(current["memory_id"])).metadata[
                        "profile_state"
                    ],
                )
                rejected = await store.get_memory(candidate.id)
                self.assertEqual("candidate", rejected.metadata["profile_state"])
                self.assertEqual("raw_event", rejected.lifecycle)
                self.assertEqual("pending", rejected.review_status)

    async def test_command_promote_does_not_bypass_profile_validation(
        self,
    ) -> None:
        store, _path = self.make_store()
        candidate = profile_record(
            record_id="command-invalid-candidate",
            value="主人",
            source_id="command-invalid-candidate",
            state="candidate",
        )
        candidate.metadata.pop("normalized_value")
        await store.insert_memory(candidate, "profile_candidate_requires_review")
        handler = MemoryCompanionCommandHandler(
            type("ServiceStub", (), {"store": store})(), "test"
        )

        response = await handler.promote(candidate.id)

        current = await store.get_memory(candidate.id)
        self.assertEqual("没有找到这条记忆。", response)
        self.assertEqual("candidate", current.metadata["profile_state"])
        self.assertEqual("raw_event", current.lifecycle)
        self.assertEqual("pending", current.review_status)

    async def test_visibility_move_preserves_single_value_domain_invariant(
        self,
    ) -> None:
        store, _path = self.make_store()
        private = await store.upsert_profile_candidate(
            profile_record(
                record_id="private-address",
                value="宝宝",
                source_id="timeline-private",
            )
        )
        shareable = await store.upsert_profile_candidate(
            profile_record(
                record_id="shareable-address",
                value="主人",
                source_id="timeline-shareable",
                visibility="shareable",
            )
        )

        self.assertFalse(
            await store.update_memory_visibility(
                shareable["memory_id"],
                "private_pair",
            )
        )

        rows = await store.list_rule_profile_memories(include_archived=True)
        active = [
            row
            for row in rows
            if row.metadata.get("profile_dimension") == "preferred_address"
            and row.metadata.get("profile_state") == "active"
            and row.visibility == "private_pair"
        ]
        self.assertEqual([private["memory_id"]], [row.id for row in active])
        private_record = await store.get_memory(private["memory_id"])
        shareable_record = await store.get_memory(shareable["memory_id"])
        self.assertEqual("active", private_record.metadata["profile_state"])
        self.assertEqual("private_pair", private_record.visibility)
        self.assertEqual("active", shareable_record.metadata["profile_state"])
        self.assertEqual("shareable", shareable_record.visibility)
        self.assertEqual("", private_record.supersedes_id)
        self.assertEqual("", shareable_record.supersedes_id)

    async def test_payload_update_cannot_bypass_visibility_domain_guard(
        self,
    ) -> None:
        store, _path = self.make_store()
        private = await store.upsert_profile_candidate(
            profile_record(
                record_id="payload-private-address",
                value="宝宝",
                source_id="payload-private",
            )
        )
        shareable = await store.upsert_profile_candidate(
            profile_record(
                record_id="payload-shareable-address",
                value="主人",
                source_id="payload-shareable",
                visibility="shareable",
            )
        )

        changed = await store.update_memory_payload(
            shareable["memory_id"], visibility="private_pair"
        )

        self.assertFalse(changed)
        self.assertEqual(
            "private_pair", (await store.get_memory(private["memory_id"])).visibility
        )
        self.assertEqual(
            "shareable",
            (await store.get_memory(shareable["memory_id"])).visibility,
        )

    async def test_reject_profile_candidate_archives_and_removes_embedding(
        self,
    ) -> None:
        store, _path = self.make_store()
        candidate = await store.upsert_profile_candidate(
            profile_record(
                record_id="address-rejected",
                value="主人",
                source_id="timeline-rejected",
                state="candidate",
            )
        )
        await store.upsert_memory_embedding(
            memory_id=candidate["memory_id"],
            provider_id="test-provider",
            text_hash="test-hash",
            vector=[0.1, 0.2],
        )

        changed = await store.update_review_status(candidate["memory_id"], "rejected")

        self.assertTrue(changed)
        rejected = await store.get_memory(candidate["memory_id"])
        self.assertEqual("rejected", rejected.metadata["profile_state"])
        self.assertEqual("rejected", rejected.metadata["profile_status"])
        self.assertFalse(rejected.metadata["quality_gate_passed"])
        self.assertEqual("archived", rejected.lifecycle)
        self.assertEqual("rejected", rejected.review_status)
        embedding = store._conn.execute(
            "SELECT 1 FROM memory_embeddings WHERE memory_id=?",
            (candidate["memory_id"],),
        ).fetchone()
        review = store._conn.execute(
            "SELECT status FROM review_queue WHERE memory_id=?",
            (candidate["memory_id"],),
        ).fetchone()
        self.assertIsNone(embedding)
        self.assertEqual("rejected", review["status"])

    async def test_repair_apply_is_cas_and_rollback_restores_snapshots(self) -> None:
        store, path = self.make_store()
        first = profile_record(
            record_id="duplicate-a", value="宝宝", source_id="timeline-a"
        )
        second = profile_record(
            record_id="duplicate-b", value="宝宝", source_id="timeline-b"
        )
        await store.insert_memory(first)
        await store.insert_memory(second)
        plan = build_repair_plan([first, second])
        self.assertEqual(1, plan["counts"]["merge"])
        backup = store.backup(".test_profile_repair")
        result = await store.apply_profile_repairs(
            operation_id="profile_repair_test",
            rule_version="test-v1",
            actions=plan["records"],
            backup_path=str(backup),
        )
        self.assertEqual(2, result["changed"])
        merged = next(item for item in plan["records"] if item["action"] == "merge")
        source = await store.get_memory(merged["memory_id"])
        self.assertEqual("archived", source.lifecycle)

        replay = await store.apply_profile_repairs(
            operation_id="profile_repair_test",
            rule_version="test-v1",
            actions=plan["records"],
            backup_path=str(backup),
        )
        self.assertEqual("profile_repair_idempotent_replay", replay["code"])

        conflicting_plan = [dict(item) for item in plan["records"]]
        conflicting_plan[0]["action"] = "pending"
        with self.assertRaisesRegex(ValueError, "different plan"):
            await store.apply_profile_repairs(
                operation_id="profile_repair_test",
                rule_version="test-v1",
                actions=conflicting_plan,
                backup_path=str(backup),
            )

        rolled_back = await store.rollback_profile_repairs(
            operation_id="profile_repair_test",
            rollback_backup_path=str(path.with_suffix(".rollback.db")),
        )
        self.assertEqual(2, rolled_back["rolled_back"])
        self.assertEqual("stable_memory", (await store.get_memory(first.id)).lifecycle)
        self.assertEqual("stable_memory", (await store.get_memory(second.id)).lifecycle)

        with self.assertRaisesRegex(ValueError, "already been rolled back"):
            await store.apply_profile_repairs(
                operation_id="profile_repair_test",
                rule_version="test-v1",
                actions=plan["records"],
                backup_path=str(backup),
            )

    async def test_repair_skips_stale_record_without_overwrite(self) -> None:
        store, _path = self.make_store()
        record = profile_record(
            record_id="stale", value="宝宝", source_id="timeline-stale"
        )
        await store.insert_memory(record)
        plan = build_repair_plan([record])
        action = plan["records"][0]
        action["action"] = "archive"
        action["proposed_action"] = "archive"
        await store.update_memory_payload(record.id, content="用户刚刚修正的新内容")
        backup = store.backup(".stale")
        result = await store.apply_profile_repairs(
            operation_id="profile_repair_stale",
            rule_version="test-v1",
            actions=[action],
            backup_path=str(backup),
        )
        self.assertEqual(1, result["stale"])
        current = await store.get_memory(record.id)
        self.assertEqual("用户刚刚修正的新内容", current.content)
        self.assertEqual("stable_memory", current.lifecycle)

    async def test_rollback_skips_entire_merge_when_canonical_is_stale(self) -> None:
        store, path = self.make_store()
        first = profile_record(
            record_id="rollback-source",
            value="宝宝",
            source_id="timeline-rollback-source",
        )
        second = profile_record(
            record_id="rollback-canonical",
            value="宝宝",
            source_id="timeline-rollback-canonical",
        )
        await store.insert_memory(first)
        await store.insert_memory(second)
        plan = build_repair_plan([first, second])
        merge = next(item for item in plan["records"] if item["action"] == "merge")
        backup = store.backup(".rollback-dependent-stale")
        await store.apply_profile_repairs(
            operation_id="profile_repair_rollback_dependent_stale",
            rule_version="test-v1",
            actions=plan["records"],
            backup_path=str(backup),
        )
        await store.update_memory_payload(
            merge["canonical_id"],
            content="用户在修复后更新了 canonical",
        )

        result = await store.rollback_profile_repairs(
            operation_id="profile_repair_rollback_dependent_stale",
            rollback_backup_path=str(path.with_suffix(".rollback.db")),
        )

        source = await store.get_memory(merge["memory_id"])
        canonical = await store.get_memory(merge["canonical_id"])
        self.assertEqual("archived", source.lifecycle)
        self.assertEqual("active", canonical.metadata["profile_state"])
        self.assertGreaterEqual(result["rollback_stale"], 1)

    async def test_supersede_skips_when_canonical_record_is_stale(self) -> None:
        store, _path = self.make_store()
        older = profile_record(
            record_id="supersede-old",
            value="宝宝",
            source_id="timeline-supersede-old",
        )
        newer = profile_record(
            record_id="supersede-new",
            value="主人",
            source_id="timeline-supersede-new",
        )
        older.occurred_at = "2026-01-01T00:00:00+00:00"
        newer.occurred_at = "2026-02-01T00:00:00+00:00"
        await store.insert_memory(older)
        await store.insert_memory(newer)
        plan = build_repair_plan([older, newer])
        action = next(
            item for item in plan["records"] if item["target_state"] == "superseded"
        )
        await store.update_memory_payload(
            action["canonical_id"],
            content="用户刚刚修正的 canonical 内容",
        )
        backup = store.backup(".canonical-stale")

        result = await store.apply_profile_repairs(
            operation_id="profile_repair_canonical_stale",
            rule_version="test-v1",
            actions=[action],
            backup_path=str(backup),
        )

        self.assertEqual(1, result["stale"])
        source = await store.get_memory(action["memory_id"])
        self.assertEqual("stable_memory", source.lifecycle)
        self.assertEqual("", source.supersedes_id)

    async def test_preview_is_read_only_and_apply_requires_confirmation(self) -> None:
        store, path = self.make_store()
        await store.insert_memory(
            profile_record(
                record_id="preview", value="宝宝", source_id="timeline-preview"
            )
        )
        store.close()
        before = path.read_bytes()
        plan = await preview(path)
        after = path.read_bytes()
        self.assertTrue(plan["read_only"])
        self.assertEqual(before, after)
        self.assertEqual([], list(path.parent.glob("*.backup.*")))

        with self.assertRaisesRegex(ValueError, APPLY_CONFIRMATION):
            await apply_plan(path, plan, confirmation="")
        self.assertEqual([], list(path.parent.glob("*.backup.*")))

        with self.assertRaisesRegex(ValueError, "invalid profile repair operation id"):
            await apply_plan(
                path,
                plan,
                confirmation=APPLY_CONFIRMATION,
                operation_id="../invalid",
            )
        self.assertEqual([], list(path.parent.glob("*.before_.*")))

        with self.assertRaisesRegex(ValueError, "memory type filter"):
            await preview(path, memory_types=["observation"])
        with self.assertRaisesRegex(ValueError, "extractor filter"):
            await preview(path, extractors=["manual"])

    async def test_portrait_v1_preview_apply_and_rollback_govern_queue(self) -> None:
        store, path = self.make_store()
        person_id = "person_repair_v1"
        pending_id = await self.add_rule_portrait_fact(
            store,
            person_id=person_id,
            dimension="preferred_address",
            summary="希望被称为 宝宝",
            suffix="a",
        )
        rejected_id = await self.add_rule_portrait_fact(
            store,
            person_id=person_id,
            dimension="preference",
            summary="喜欢 今天的午饭",
            suffix="b",
        )

        plan = await preview(path, person_id=person_id)
        portrait = {
            item["record_id"]: item
            for item in plan["records"]
            if item["record_kind"] == "portrait_fact"
        }
        self.assertEqual("pending", portrait[pending_id]["action"])
        self.assertEqual("archive", portrait[rejected_id]["action"])
        self.assertEqual("rejected", portrait[rejected_id]["target_state"])
        before = store._conn.execute(
            "SELECT id, status FROM portrait_facts ORDER BY id"
        ).fetchall()
        self.assertEqual(["active", "active"], [row["status"] for row in before])

        applied = await apply_plan(
            path,
            plan,
            confirmation=APPLY_CONFIRMATION,
            operation_id="portrait_repair_apply",
        )
        self.assertEqual(2, applied["changed"])
        states = {
            row["id"]: row["status"]
            for row in store._conn.execute(
                "SELECT id, status FROM portrait_facts"
            ).fetchall()
        }
        queue_states = {
            row["fact_id"]: row["state"]
            for row in store._conn.execute(
                "SELECT fact_id, state FROM portrait_learning_queue"
            ).fetchall()
        }
        self.assertEqual("pending", states[pending_id])
        self.assertEqual("rejected", states[rejected_id])
        self.assertEqual("pending_review", queue_states[pending_id])
        self.assertEqual("rejected", queue_states[rejected_id])

        rolled_back = await rollback(
            path,
            operation_id="portrait_repair_apply",
            confirmation=ROLLBACK_CONFIRMATION,
        )
        self.assertEqual(2, rolled_back["rolled_back"])
        self.assertEqual(
            ["active", "active"],
            [
                row["status"]
                for row in store._conn.execute(
                    "SELECT status FROM portrait_facts ORDER BY id"
                ).fetchall()
            ],
        )
        self.assertEqual(
            ["pending", "pending"],
            [
                row["state"]
                for row in store._conn.execute(
                    "SELECT state FROM portrait_learning_queue ORDER BY fact_id"
                ).fetchall()
            ],
        )

    async def test_portrait_rollback_skips_fact_when_queue_is_stale(self) -> None:
        store, path = self.make_store()
        fact_id = await self.add_rule_portrait_fact(
            store,
            person_id="person_queue_stale",
            dimension="preferred_address",
            summary="希望被称为 宝宝",
            suffix="c",
        )
        plan = await preview(path, person_id="person_queue_stale")
        await apply_plan(
            path,
            plan,
            confirmation=APPLY_CONFIRMATION,
            operation_id="portrait_repair_queue_stale",
        )
        store._conn.execute(
            "UPDATE portrait_learning_queue SET state='manual_change' WHERE fact_id=?",
            (fact_id,),
        )
        store._conn.commit()

        result = await rollback(
            path,
            operation_id="portrait_repair_queue_stale",
            confirmation=ROLLBACK_CONFIRMATION,
        )

        fact = store._conn.execute(
            "SELECT status FROM portrait_facts WHERE id=?", (fact_id,)
        ).fetchone()
        queue = store._conn.execute(
            "SELECT state FROM portrait_learning_queue WHERE fact_id=?",
            (fact_id,),
        ).fetchone()
        self.assertEqual("pending", fact["status"])
        self.assertEqual("manual_change", queue["state"])
        self.assertGreaterEqual(result["rollback_stale"], 1)

    async def test_portrait_preview_archives_one_off_profile_summaries(self) -> None:
        store, path = self.make_store()
        person_id = "person_one_off_portrait"
        fact_ids = []
        for suffix, summary in (
            ("d", "喜欢 今晚的晚饭"),
            ("e", "喜欢 刚刚的回复"),
        ):
            fact_ids.append(
                await self.add_rule_portrait_fact(
                    store,
                    person_id=person_id,
                    dimension="preference",
                    summary=summary,
                    suffix=suffix,
                )
            )

        plan = await preview(path, person_id=person_id)
        records = {
            item["record_id"]: item
            for item in plan["records"]
            if item["record_kind"] == "portrait_fact"
        }

        for fact_id in fact_ids:
            with self.subTest(fact_id=fact_id):
                self.assertEqual("archive", records[fact_id]["action"])
                self.assertEqual("rejected", records[fact_id]["target_state"])

    def test_repair_plan_never_reactivates_inactive_records(self) -> None:
        rejected = profile_record(
            record_id="already-rejected",
            value="错误称呼",
            source_id="timeline-rejected",
        )
        rejected.metadata["profile_state"] = "rejected"
        rejected.lifecycle = "archived"
        rejected.review_status = "auto"

        plan = build_repair_plan([rejected])

        self.assertEqual("keep", plan["records"][0]["action"])
        self.assertEqual("already_inactive", plan["records"][0]["reason"])

    def test_repair_plan_keeps_valid_boundary_mentions_of_other_people(self) -> None:
        boundary = profile_record(
            record_id="valid-boundary",
            value="别人问我的工资",
            source_id="timeline-boundary",
            dimension="boundary",
            polarity="avoid",
            cardinality="multi",
            evidence="我不喜欢别人问我的工资",
        )

        plan = build_repair_plan([boundary])

        self.assertEqual("keep", plan["records"][0]["action"])
        self.assertNotEqual(
            "third_party_statement",
            plan["records"][0]["reason"],
        )

    def test_repair_plan_archives_temporary_rule_v2_preferences(self) -> None:
        for suffix, statement, value in (
            ("lunch", "我喜欢今天的午饭", "今天的午饭"),
            ("dinner", "我喜欢今晚的晚饭", "今晚的晚饭"),
            ("reply", "我喜欢刚刚的回复", "刚刚的回复"),
        ):
            with self.subTest(statement=statement):
                temporary = profile_record(
                    record_id=f"temporary-preference-{suffix}",
                    value=value,
                    source_id=f"timeline-temporary-{suffix}",
                    dimension="food_preference",
                    polarity="like",
                    cardinality="multi",
                )
                temporary.evidence = ""
                temporary.content = statement

                plan = build_repair_plan([temporary])

                self.assertEqual("archive", plan["records"][0]["action"])
                self.assertEqual("rejected", plan["records"][0]["target_state"])

    def test_repair_plan_prefers_newer_single_value_correction_over_score(self) -> None:
        older = profile_record(
            record_id="older-high-score",
            value="宝宝",
            source_id="timeline-older-high-score",
        )
        newer = profile_record(
            record_id="newer-correction",
            value="主人",
            source_id="timeline-newer-correction",
        )
        older.occurred_at = "2026-01-01T00:00:00+00:00"
        newer.occurred_at = "2026-02-01T00:00:00+00:00"
        older.metadata["extraction_quality_score"] = 0.99
        newer.metadata["extraction_quality_score"] = 0.95

        plan = build_repair_plan([older, newer])

        archived = next(
            item for item in plan["records"] if item["target_state"] == "superseded"
        )
        self.assertEqual(older.id, archived["memory_id"])
        self.assertEqual(newer.id, archived["canonical_id"])

    async def test_script_apply_and_rollback_are_backed_up_and_cas_guarded(
        self,
    ) -> None:
        store, path = self.make_store()
        first = profile_record(
            record_id="script-a", value="宝宝", source_id="timeline-a"
        )
        second = profile_record(
            record_id="script-b", value="宝宝", source_id="timeline-b"
        )
        await store.insert_memory(first)
        await store.insert_memory(second)
        store.close()

        plan = await preview(path)
        self.assertEqual(
            MemoryStore.profile_repair_plan_fingerprint(plan["records"]),
            plan["plan_fingerprint"],
        )
        tampered = {**plan, "records": [dict(item) for item in plan["records"]]}
        tampered["records"][0]["action"] = "pending"
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            await apply_plan(
                path,
                tampered,
                confirmation=APPLY_CONFIRMATION,
                operation_id="script_tampered",
            )
        self.assertEqual([], list(path.parent.glob("*.before_script_tampered*")))

        applied = await apply_plan(
            path,
            plan,
            confirmation=APPLY_CONFIRMATION,
            operation_id="script_roundtrip",
        )
        self.assertEqual(2, applied["changed"])
        self.assertTrue(Path(applied["backup_path"]).is_file())

        rolled_back = await rollback(
            path,
            operation_id="script_roundtrip",
            confirmation=ROLLBACK_CONFIRMATION,
        )
        self.assertEqual(2, rolled_back["rolled_back"])
        self.assertTrue(Path(rolled_back["rollback_backup_path"]).is_file())

        restored = MemoryStore(path)
        restored.initialize()
        self.addCleanup(restored.close)
        self.assertEqual(
            "stable_memory", (await restored.get_memory(first.id)).lifecycle
        )
        self.assertEqual(
            "stable_memory", (await restored.get_memory(second.id)).lifecycle
        )

    def test_service_gate_requires_complete_rule_metadata(self) -> None:
        valid = profile_record(
            record_id="valid", value="宝宝", source_id="timeline-valid"
        )
        mode, state = MemoryCompanionService._prepare_rule_profile_write(valid)
        self.assertEqual(("profile", "active"), (mode, state))

        invalid = profile_record(
            record_id="invalid", value="宝宝", source_id="timeline-invalid"
        )
        invalid.metadata.pop("normalized_value")
        mode, reason = MemoryCompanionService._prepare_rule_profile_write(invalid)
        self.assertEqual("reject", mode)
        self.assertEqual("profile_candidate_metadata_missing", reason)


if __name__ == "__main__":
    unittest.main()
