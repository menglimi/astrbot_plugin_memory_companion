from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "req036_history_backfill"
if PACKAGE not in sys.modules:
    module = types.ModuleType(PACKAGE)
    module.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = module

from req036_history_backfill.core.models import EntityRef, MemoryRecord, json_loads
from req036_history_backfill.core.portrait import normalized_claim_hash
from req036_history_backfill.core.portrait_service import PortraitBackfillRequest, PortraitService
from req036_history_backfill.core.store import MemoryStore
from req036_history_backfill.unified_profile_contract import build_capability_summary


PERSON_ID = "person_" + "1" * 24
IDENTITY = "chat-origin-v1:" + "2" * 64
OTHER_IDENTITY = "chat-origin-v1:" + "3" * 64
PERSON_REF = {
    "person_id": PERSON_ID,
    "resolved_identity_key": IDENTITY,
    "projection_revision": 1,
    "identity_assurance": "observed",
    "profile_status": "active",
}


class Config:
    @staticmethod
    def int(key: str, default: int) -> int:
        return {
            "portrait.min_independent_evidence": 3,
            "portrait.backfill_max_records": 5000,
            "portrait.backfill_page_size": 2,
        }.get(key, default)

    @staticmethod
    def float(key: str, default: float) -> float:
        return default


class PortraitHistoryBackfillTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = MemoryStore(Path(temp.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    async def project_person(self, store: MemoryStore, *, group: bool = False) -> None:
        capabilities = build_capability_summary(
            {
                "private_companion_enabled": True,
                "portrait_mode": "learn_and_use",
                "grant_source": "test",
            }
        )
        await store.upsert_portrait_person_projection(
            PERSON_REF,
            capabilities,
            source_scope="private",
        )
        if group:
            await store.upsert_portrait_person_projection(
                PERSON_REF,
                capabilities,
                source_scope="group:onebot:g-1",
            )

    async def add_source(
        self,
        store: MemoryStore,
        message_id: str,
        content: str,
        *,
        identity: str = IDENTITY,
        event_type: str = "user_message",
        metadata: dict[str, object] | None = None,
        scope: str = "private",
    ) -> None:
        payload = {"message_id": message_id, "source_identity_key": identity}
        if metadata:
            payload.update(metadata)
        await store.add_timeline_event(
            event_type=event_type,
            session_id=f"onebot:FriendMessage:{identity[-8:]}",
            scope=scope,
            subject_id=identity,
            object_id="self",
            content=content,
            metadata=payload,
            occurred_at=f"2026-08-01T00:00:0{message_id[-1]}+00:00",
        )

    async def test_preview_is_read_only_and_exact_identity_excludes_other_subjects(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        await self.add_source(store, "m1", "我喜欢烤肉")
        await self.add_source(store, "m2", "我喜欢烤肉", identity=OTHER_IDENTITY)
        before = {
            table: int(store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("portrait_operations", "portrait_evidence", "portrait_facts", "portrait_learning_queue")
        }
        service = PortraitService(store, Config())
        result = await service.preview_history_backfill(
            {
                "target_person_id": PERSON_ID,
                "target_identity": IDENTITY,
                "source_scopes": ["private"],
                "operation_id": "preview-only",
                "dry_run": True,
            }
        )
        self.assertEqual("dry_run_ready", result["code"])
        self.assertGreaterEqual(result["counts"]["eligible_sources"], 1)
        self.assertEqual(1, result["counts"]["skipped"].get("identity_mismatch"))
        after = {
            table: int(store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in before
        }
        self.assertEqual(before, after)

    async def test_start_aggregates_independent_statements_and_is_idempotent(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        for index, content in enumerate(("我喜欢烤肉", "我真的喜欢烤肉", "我最喜欢烤肉"), 1):
            await self.add_source(store, f"m{index}", content)
        await self.add_source(store, "bot-1", "我喜欢烤肉", event_type="bot_response", metadata={"bot_generated": True})
        await self.add_source(store, "quote-1", "我喜欢烤肉", metadata={"quoted": True})
        service = PortraitService(store, Config())
        request = {
            "target_person_id": PERSON_ID,
            "target_identity": IDENTITY,
            "source_scopes": ["private"],
            "operation_id": "backfill-1",
        }
        first = await service.start_history_backfill(request)
        self.assertEqual("backfill_complete", first["code"])
        self.assertGreaterEqual(first["counts"]["scanned"], 4)
        self.assertGreaterEqual(first["counts"]["skipped"].get("excluded_context", 0), 1)
        self.assertGreaterEqual(first["counts"]["accepted_fact_count"], 1)
        self.assertGreaterEqual(first["counts"]["inferred_fact_count"], 1)
        counts = {
            table: int(store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("portrait_evidence", "portrait_facts", "portrait_learning_queue")
        }
        replay = await service.start_history_backfill(request)
        self.assertEqual("backfill_idempotent_replay", replay["code"])
        self.assertEqual(counts, {
            table: int(store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in counts
        })
        rendered = await service.render_history_portrait(request)
        self.assertTrue(rendered.get("ok"), rendered)
        self.assertTrue(rendered.get("items"), rendered)
        self.assertNotIn("我喜欢烤肉", json_loads(store._conn.execute("SELECT snapshot FROM portrait_operations WHERE operation_id='backfill-1'").fetchone()[0], {}).__str__())
        self.assertNotIn("我喜欢烤肉", str(await service.status_history_backfill("backfill-1")))

    async def test_rollback_requires_confirmation_and_preserves_other_operation_fact(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        await self.add_source(store, "m1", "我喜欢烤肉")
        service = PortraitService(store, Config())
        request = {
            "target_person_id": PERSON_ID,
            "target_identity": IDENTITY,
            "source_scopes": ["private"],
            "operation_id": "backfill-rollback",
        }
        await service.start_history_backfill(request)
        unrelated = await store.upsert_portrait_fact(
            {
                "person_id": PERSON_ID,
                "dimension": "preference",
                "normalized_claim_hash": "a" * 64,
                "claim_summary": "独立事实",
                "portrait_tier": "base",
                "producer_kind": "test",
                "producer_version": "test",
                "derivation_kind": "explicit_statement",
                "epistemic_status": "explicit",
                "source_scope": "private",
                "sensitivity": "low",
                "confidence": 0.9,
                "operation_id": "unrelated-operation",
            }
        )
        self.assertTrue(unrelated["ok"])
        self.assertEqual("rollback_requires_confirmation", (await service.rollback_history_backfill("backfill-rollback"))["code"])
        rolled = await service.rollback_history_backfill("backfill-rollback", confirm=True)
        self.assertEqual("backfill_rolled_back", rolled["code"])
        replayed_rollback = await service.rollback_history_backfill("backfill-rollback", confirm=True)
        self.assertEqual("backfill_already_rolled_back", replayed_rollback["code"])
        self.assertIsNotNone(
            await store.get_portrait_backfill_fact(
                person_id=PERSON_ID,
                dimension="preference",
                normalized_claim_hash="a" * 64,
                source_scope="private",
            )
        )
        self.assertEqual("rolled_back", (await service.status_history_backfill("backfill-rollback"))["state"])

    async def test_backfill_does_not_mutate_existing_official_fact(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        existing = await store.upsert_portrait_fact(
            {
                "person_id": PERSON_ID,
                "dimension": "preference",
                "normalized_claim_hash": normalized_claim_hash("preference", "like:烤肉"),
                "claim_summary": "喜欢 烤肉",
                "portrait_tier": "base",
                "producer_kind": "official",
                "producer_version": "fixture",
                "derivation_kind": "explicit_statement",
                "epistemic_status": "explicit",
                "source_scope": "private",
                "sensitivity": "low",
                "confidence": 0.95,
                "evidence_hashes": ["a" * 64],
                "operation_id": "official-operation",
            }
        )
        await self.add_source(store, "append-1", "我喜欢烤肉")
        service = PortraitService(store, Config())
        request = {
            "target_person_id": PERSON_ID,
            "target_identity": IDENTITY,
            "source_scopes": ["private"],
            "operation_id": "backfill-append-existing",
        }
        result = await service.start_history_backfill(request)
        self.assertEqual(1, result["counts"]["skipped"].get("external_fact_protected"))
        after_backfill = await store.get_portrait_backfill_fact(
            person_id=PERSON_ID,
            dimension="preference",
            normalized_claim_hash=normalized_claim_hash("preference", "like:烤肉"),
            source_scope="private",
        )
        self.assertEqual(existing["fact_id"], after_backfill["id"])
        self.assertEqual(["a" * 64], after_backfill["evidence_hashes"])

    async def test_legacy_operation_id_cannot_be_reused_by_history_backfill(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        legacy = await store.portrait_migration(operation_id="legacy-operation", dry_run=False)
        self.assertEqual("migration_applied", legacy["code"])
        result = await PortraitService(store, Config()).start_history_backfill(
            {
                "target_person_id": PERSON_ID,
                "target_identity": IDENTITY,
                "source_scopes": ["private"],
                "operation_id": "legacy-operation",
            }
        )
        self.assertEqual("operation_conflict", result["code"])

    async def test_rollback_keeps_operation_fact_when_external_evidence_was_appended(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        await self.add_source(store, "created-1", "我喜欢茶")
        service = PortraitService(store, Config())
        request = {
            "target_person_id": PERSON_ID,
            "target_identity": IDENTITY,
            "source_scopes": ["private"],
            "operation_id": "backfill-stale-created",
        }
        await service.start_history_backfill(request)
        created = await store.get_portrait_backfill_fact(
            person_id=PERSON_ID,
            dimension="preference",
            normalized_claim_hash=normalized_claim_hash("preference", "like:茶"),
            source_scope="private",
        )
        self.assertIsNotNone(created)
        await store.append_portrait_fact_evidence(
            person_id=PERSON_ID,
            fact_id=created["id"],
            evidence_hash="f" * 64,
        )
        rolled = await service.rollback_history_backfill("backfill-stale-created", confirm=True)
        self.assertEqual(1, rolled["deleted"]["rollback_stale"])
        self.assertIsNotNone(
            await store.get_portrait_backfill_fact(
                person_id=PERSON_ID,
                dimension="preference",
                normalized_claim_hash=normalized_claim_hash("preference", "like:茶"),
                source_scope="private",
            )
        )

    async def test_identity_mismatch_and_unconfigured_group_scope_are_rejected(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        service = PortraitService(store, Config())
        wrong = await service.start_history_backfill(
            {
                "target_person_id": PERSON_ID,
                "target_identity": OTHER_IDENTITY,
                "source_scopes": ["private"],
                "operation_id": "wrong-identity",
            }
        )
        self.assertEqual("identity_mismatch", wrong["code"])
        group = await service.start_history_backfill(
            {
                "target_person_id": PERSON_ID,
                "target_identity": IDENTITY,
                "source_scopes": ["group:onebot:g-1"],
                "operation_id": "group-not-allowed",
            }
        )
        self.assertEqual("scope_not_allowed", group["code"])

    async def test_memory_sources_use_authenticated_subject_not_owner_bot_and_exclude_bot_subjects(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        await store.insert_memory(
            MemoryRecord(
                id="memory-user-source",
                memory_type="manual_memory",
                subject=EntityRef(kind="user", id=IDENTITY),
                scope="private",
                session_id="memory-session",
                visibility="private_pair",
                content="我喜欢咖啡",
                metadata={"source_identity_key": IDENTITY, "owner_bot_id": "fixture-bot"},
                owner_bot_id="fixture-bot",
                occurred_at="2026-08-01T00:00:01+00:00",
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="memory-bot-source",
                memory_type="manual_memory",
                subject=EntityRef(kind="bot", id="fixture-bot"),
                scope="private",
                session_id="memory-bot-session",
                visibility="private_pair",
                content="我喜欢咖啡",
                metadata={"source_identity_key": IDENTITY, "bot_generated": True},
                owner_bot_id="fixture-bot",
                occurred_at="2026-08-01T00:00:02+00:00",
            )
        )
        result = await PortraitService(store, Config()).preview_history_backfill(
            {
                "target_person_id": PERSON_ID,
                "target_identity": IDENTITY,
                "source_scopes": ["private"],
                "operation_id": "memory-source-preview",
                "dry_run": True,
            }
        )
        self.assertEqual("dry_run_ready", result["code"])
        self.assertGreaterEqual(result["counts"]["eligible_sources"], 1)
        self.assertGreaterEqual(result["counts"]["skipped"].get("bot_subject", 0), 1)

    async def test_sources_without_message_id_are_deduplicated_by_content_time_and_scope(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        for source_id in ("no-message-a", "no-message-b"):
            await store.add_timeline_event(
                event_type="user_message",
                session_id="same-session",
                scope="private",
                subject_id=IDENTITY,
                object_id="self",
                content="我喜欢茶",
                metadata={"source_identity_key": IDENTITY},
                occurred_at="2026-08-01T00:00:03+00:00",
            )
        result = await PortraitService(store, Config()).preview_history_backfill(
            {
                "target_person_id": PERSON_ID,
                "target_identity": IDENTITY,
                "source_scopes": ["private"],
                "operation_id": "content-dedupe-preview",
                "dry_run": True,
            }
        )
        self.assertEqual("dry_run_ready", result["code"])
        self.assertEqual(1, result["counts"]["eligible_sources"])
        self.assertEqual(1, result["counts"]["skipped"].get("duplicate_source"))

    async def test_history_sources_apply_memory_governance_and_timeline_metadata_filters(self) -> None:
        store = self.make_store()
        await self.project_person(store)
        await store.insert_memory(
            MemoryRecord(
                id="memory-visible",
                memory_type="manual_memory",
                subject=EntityRef(kind="user", id=IDENTITY),
                scope="private",
                session_id="memory-visible-session",
                visibility="private_pair",
                content="我喜欢咖啡",
                metadata={"source_identity_key": IDENTITY},
                occurred_at="2026-08-01T00:00:01+00:00",
            )
        )
        for memory_id, visibility, lifecycle, validity_status, review_status in (
            ("memory-internal", "internal", "raw_event", "active", "auto"),
            ("memory-bot-self", "bot_self", "raw_event", "active", "auto"),
            ("memory-archived", "private_pair", "archived", "active", "auto"),
            ("memory-deleted", "private_pair", "raw_event", "deleted", "auto"),
            ("memory-pending", "private_pair", "raw_event", "active", "pending"),
            ("memory-rejected", "private_pair", "raw_event", "active", "rejected"),
        ):
            await store.insert_memory(
                MemoryRecord(
                    id=memory_id,
                    memory_type="manual_memory",
                    subject=EntityRef(kind="user", id=IDENTITY),
                    scope="private",
                    session_id=f"{memory_id}-session",
                    visibility=visibility,
                    lifecycle=lifecycle,
                    validity_status=validity_status,
                    review_status=review_status,
                    content="我喜欢咖啡",
                    metadata={"source_identity_key": IDENTITY},
                    occurred_at="2026-08-01T00:00:02+00:00",
                )
            )
        timeline_visible = await store.add_timeline_event(
            event_type="user_message",
            session_id="timeline-visible",
            scope="private",
            subject_id=IDENTITY,
            object_id="self",
            content="我喜欢茶",
            metadata={"source_identity_key": IDENTITY},
            occurred_at="2026-08-01T00:00:03+00:00",
        )
        for metadata in (
            {"source_identity_key": IDENTITY, "lifecycle": "archived"},
            {"source_identity_key": IDENTITY, "review_status": "pending"},
            {"source_identity_key": IDENTITY, "visibility": "internal"},
            {"source_identity_key": IDENTITY, "bot_generated": True},
        ):
            await store.add_timeline_event(
                event_type="user_message",
                session_id="timeline-filtered",
                scope="private",
                subject_id=IDENTITY,
                object_id="self",
                content="我喜欢茶",
                metadata=metadata,
                occurred_at="2026-08-01T00:00:04+00:00",
            )
        rows = await store.list_portrait_history_sources(
            source_scopes=["private"],
            from_time="2026-08-01T00:00:00+00:00",
            to_time="2026-08-01T00:00:59+00:00",
            offset=0,
            limit=100,
        )
        source_ids = {row["source_id"] for row in rows}
        self.assertIn("memory-visible", source_ids)
        self.assertIn(timeline_visible, source_ids)
        self.assertEqual(2, len(rows))

    def test_request_normalizes_scope_order_and_utc_time_bounds(self) -> None:
        request = PortraitBackfillRequest.from_value(
            {
                "target_person_id": PERSON_ID,
                "target_identity": IDENTITY,
                "source_scopes": ["group:z", "private", "group:z", "private@persona"],
                "from_time": "2026-08-01T08:00:00+08:00",
                "to_time": "2026-08-02T00:00:00Z",
                "operation_id": "canonical-request",
            }
        )
        self.assertEqual(("group:z", "private", "private@persona"), request.source_scopes)
        self.assertEqual("2026-08-01T00:00:00+00:00", request.from_time)
        self.assertEqual("2026-08-02T00:00:00+00:00", request.to_time)
        self.assertEqual(list(request.source_scopes), request.payload()["source_scopes"])

    def test_source_key_keeps_message_ids_separate_by_kind_and_scope(self) -> None:
        key_timeline_private = PortraitService._backfill_source_key(
            {"source_kind": "timeline", "scope": "private", "message_id": "same-message"}
        )
        key_memory_private = PortraitService._backfill_source_key(
            {"source_kind": "memory", "scope": "private", "message_id": "same-message"}
        )
        key_timeline_group = PortraitService._backfill_source_key(
            {"source_kind": "timeline", "scope": "group:onebot:g-1", "message_id": "same-message"}
        )
        self.assertEqual(len({key_timeline_private, key_memory_private, key_timeline_group}), 3)


if __name__ == "__main__":
    unittest.main()
