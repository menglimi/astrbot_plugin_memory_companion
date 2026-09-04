from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "req036_memory"
if PACKAGE not in sys.modules:
    module = types.ModuleType(PACKAGE)
    module.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = module

from req036_memory.core.models import EntityRef, MemoryRecord, SearchResult, SessionContext
from req036_memory.core.bridge import MemoryCompanionBridge
from req036_memory.core.portrait import build_evidence, normalized_claim_hash
from req036_memory.core.portrait_service import PortraitService
from req036_memory.core.service import MemoryCompanionService
from req036_memory.core.store import MemoryStore
from req036_memory.unified_profile_contract import build_capability_summary, build_profile_dto, build_portrait_request


PERSON_REF = {
    "person_id": "person_" + "1" * 24,
    "resolved_identity_key": "chat-origin-v1:" + "2" * 64,
    "projection_revision": 1,
    "identity_assurance": "observed",
    "profile_status": "active",
}


class _Config:
    @staticmethod
    def int(key: str, default: int) -> int:
        return {
            "portrait.min_independent_evidence": 3,
            "portrait.daily_success_limit_per_person": 1,
            "portrait.daily_attempt_limit_per_person": 2,
            "portrait.inferred_freshness_days": 90,
        }.get(key, default)

    @staticmethod
    def float(key: str, default: float) -> float:
        return {"portrait.usage_min_confidence": 0.75}.get(key, default)


class Req036PortraitTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = MemoryStore(Path(temp.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    @staticmethod
    def dto(mode: str = "learn_and_use") -> dict[str, object]:
        return build_profile_dto(
            person_ref=PERSON_REF,
            capability_summary={
                "private_companion_enabled": True,
                "proactive_private_enabled": False,
                "portrait_mode": mode,
                "grant_source": "administrator",
            },
        )

    @staticmethod
    def request(scope: str = "private", requester: str | None = None) -> dict[str, object]:
        return build_portrait_request(
            person_ref=PERSON_REF,
            requester_person_id=requester if requester is not None else PERSON_REF["person_id"],
            target_person_id=PERSON_REF["person_id"],
            scope=scope,
            purpose="summarize_to_subject",
        )

    async def test_explicit_evidence_daily_limit_and_scope_filtered_summary(self) -> None:
        store = self.make_store()
        service = PortraitService(store, _Config())
        for index, text in enumerate(("我喜欢烤肉", "我真的喜欢烤肉", "我最喜欢烤肉")):
            event = types.SimpleNamespace(private_companion_unified_profile_context=self.dto())
            ctx = SessionContext(
                session_id="onebot:FriendMessage:10001",
                scope="private",
                platform="onebot",
                user_id="10001",
                message_id=f"m-{index}",
                message_text=text,
            )
            result = await service.capture_user_message(ctx, event=event)
            self.assertTrue(result["ok"])

        batch = await service.run_daily_batch(PERSON_REF["person_id"], run_day="2026-08-05")
        self.assertTrue(batch["ok"])
        self.assertEqual(1, batch["successes"])
        self.assertEqual("portrait_daily_limit", (await service.run_daily_batch(PERSON_REF["person_id"], run_day="2026-08-05"))["code"])
        summary = await service.read_summary(self.request())
        self.assertTrue(summary["ok"])
        self.assertTrue(any("烤肉" in item["summary"] for item in summary["items"]))

    async def test_new_single_value_portrait_fact_supersedes_previous_value(
        self,
    ) -> None:
        store = self.make_store()
        service = PortraitService(store, _Config())
        event = types.SimpleNamespace(
            private_companion_unified_profile_context=self.dto()
        )
        for message_id, text in (
            ("address-old", "以后叫我宝宝"),
            ("address-new", "以后叫我主人"),
        ):
            result = await service.capture_user_message(
                SessionContext(
                    session_id="onebot:FriendMessage:10001",
                    scope="private",
                    platform="onebot",
                    user_id="10001",
                    message_id=message_id,
                    message_text=text,
                ),
                event=event,
            )
            self.assertTrue(result["ok"])

        summary = await service.read_summary(self.request())
        addresses = [
            item["summary"]
            for item in summary["items"]
            if item["dimension"] == "preferred_address"
        ]
        self.assertEqual(["希望被称为 主人"], addresses)
        rows = store._conn.execute(
            "SELECT status, supersedes_id FROM portrait_facts "
            "WHERE person_id=? AND dimension='preferred_address' "
            "ORDER BY created_at",
            (PERSON_REF["person_id"],),
        ).fetchall()
        self.assertEqual(["superseded", "active"], [row["status"] for row in rows])
        self.assertTrue(rows[0]["supersedes_id"])

    async def test_single_value_portrait_supersedes_across_tiers_and_queue(
        self,
    ) -> None:
        store = self.make_store()
        first = await store.upsert_portrait_fact(
            {
                "person_id": PERSON_REF["person_id"],
                "dimension": "preferred_address",
                "profile_cardinality": "single",
                "normalized_claim_hash": "a" * 64,
                "claim_summary": "希望被称为 宝宝",
                "portrait_tier": "base",
                "producer_kind": "rule_explicit",
                "producer_version": "req036.rule.v2",
                "derivation_kind": "explicit_statement",
                "epistemic_status": "explicit",
                "source_scope": "private",
                "usable_scope": "self_low_global",
                "confidence": 0.95,
                "sensitivity": "low",
                "status": "active",
                "evidence_hashes": ["c" * 64],
                "operation_id": "cross-tier-base",
            }
        )
        await store.enqueue_portrait_learning(
            person_id=PERSON_REF["person_id"],
            fact_id=first["fact_id"],
            evidence_hash="c" * 64,
        )
        second = await store.upsert_portrait_fact(
            {
                "person_id": PERSON_REF["person_id"],
                "dimension": "preferred_address",
                "profile_cardinality": "single",
                "normalized_claim_hash": "b" * 64,
                "claim_summary": "希望被称为 主人",
                "portrait_tier": "intelligent",
                "producer_kind": "daily_evidence_batch",
                "producer_version": "req036.batch.v1",
                "derivation_kind": "independent_evidence_aggregate",
                "epistemic_status": "inferred",
                "source_scope": "private",
                "usable_scope": "self_low_global",
                "confidence": 0.96,
                "sensitivity": "low",
                "status": "active",
                "evidence_hashes": ["d" * 64],
                "operation_id": "cross-tier-intelligent",
            }
        )

        old = store._conn.execute(
            "SELECT status, supersedes_id FROM portrait_facts WHERE id=?",
            (first["fact_id"],),
        ).fetchone()
        new = store._conn.execute(
            "SELECT status FROM portrait_facts WHERE id=?", (second["fact_id"],)
        ).fetchone()
        queue = store._conn.execute(
            "SELECT state FROM portrait_learning_queue WHERE fact_id=?",
            (first["fact_id"],),
        ).fetchone()
        self.assertEqual("superseded", old["status"])
        self.assertEqual(second["fact_id"], old["supersedes_id"])
        self.assertEqual("active", new["status"])
        self.assertEqual("superseded", queue["state"])

    async def test_mechanical_repeats_do_not_satisfy_independent_evidence_threshold(self) -> None:
        store = self.make_store()
        service = PortraitService(store, _Config())
        for index in range(3):
            event = types.SimpleNamespace(private_companion_unified_profile_context=self.dto())
            ctx = SessionContext(
                session_id="onebot:FriendMessage:10001",
                scope="private",
                platform="onebot",
                user_id="10001",
                message_id=f"repeat-{index}",
                message_text="我喜欢烤肉",
            )
            self.assertTrue((await service.capture_user_message(ctx, event=event))["ok"])
        result = await service.run_daily_batch(PERSON_REF["person_id"], run_day="2026-08-05")
        self.assertFalse(result["ok"])
        self.assertEqual("portrait_insufficient_evidence", result["code"])

    async def test_third_party_rejection_happens_before_store_query(self) -> None:
        store = self.make_store()
        portraits = PortraitService(store, _Config())
        service = object.__new__(MemoryCompanionService)
        service.portraits = portraits
        calls = 0

        async def should_not_query(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return {"ok": True, "items": []}

        store.portrait_summary = should_not_query  # type: ignore[method-assign]
        result = await service.read_unified_profile_portrait(
            self.request(requester="person_" + "9" * 24)
        )
        self.assertFalse(result["ok"])
        self.assertEqual("portrait_third_party_forbidden", result["code"])
        self.assertEqual(0, calls)

    async def test_unverified_or_stale_projection_is_rejected_before_fact_query(self) -> None:
        store = self.make_store()
        portraits = PortraitService(store, _Config())
        service = object.__new__(MemoryCompanionService)
        service.portraits = portraits
        current_ref = {**PERSON_REF, "projection_revision": 2}
        await store.upsert_portrait_person_projection(
            current_ref,
            build_capability_summary({
                "private_companion_enabled": True,
                "proactive_private_enabled": False,
                "portrait_mode": "use_existing",
            }),
        )
        calls = 0

        async def should_not_query(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return {"ok": True, "items": []}

        store.portrait_summary = should_not_query  # type: ignore[method-assign]
        self.assertEqual(
            "bridge_stale_revision",
            (await service.read_unified_profile_portrait(self.request()))["code"],
        )
        unverified_ref = {**PERSON_REF, "identity_assurance": "unverified"}
        unverified_request = build_portrait_request(
            person_ref=unverified_ref,
            requester_person_id=unverified_ref["person_id"],
            target_person_id=unverified_ref["person_id"],
            scope="private",
            purpose="summarize_to_subject",
        )
        self.assertEqual(
            "bridge_person_mismatch",
            (await service.read_unified_profile_portrait(unverified_request))["code"],
        )
        self.assertEqual(0, calls)

    async def test_group_source_only_fact_cannot_cross_into_private_scope(self) -> None:
        store = self.make_store()
        await store.upsert_portrait_person_projection(
            PERSON_REF,
            build_capability_summary({
                "private_companion_enabled": True,
                "proactive_private_enabled": False,
                "portrait_mode": "use_existing",
            }),
        )
        claim_hash = normalized_claim_hash("preference", "like:桌游")
        evidence = build_evidence(
            person_ref=PERSON_REF,
            scope="group:onebot:group-a",
            session_id="onebot:GroupMessage:group-a",
            message_id="g-1",
            source_identity_key=PERSON_REF["resolved_identity_key"],
            text="我喜欢桌游",
        )
        await store.add_portrait_evidence(evidence)
        await store.upsert_portrait_fact(
            {
                "person_id": PERSON_REF["person_id"],
                "dimension": "preference",
                "normalized_claim_hash": claim_hash,
                "claim_summary": "喜欢 桌游",
                "portrait_tier": "base",
                "producer_kind": "rule_explicit",
                "producer_version": "test",
                "derivation_kind": "explicit_statement",
                "epistemic_status": "explicit",
                "source_scope": "group:onebot:group-a",
                "usable_scope": "source_only",
                "confidence": 0.9,
                "sensitivity": "low",
                "evidence_hashes": [evidence["evidence_hash"]],
                "operation_id": "group-fact",
            }
        )
        private = await store.portrait_summary(PERSON_REF["person_id"], scope="private")
        group_a = await store.portrait_summary(PERSON_REF["person_id"], scope="group:onebot:group-a")
        group_b = await store.portrait_summary(PERSON_REF["person_id"], scope="group:onebot:group-b")
        self.assertEqual([], private["items"])
        self.assertEqual(1, len(group_a["items"]))
        self.assertEqual([], group_b["items"])

    async def test_legacy_rule_v1_fact_is_not_returned_before_governance(
        self,
    ) -> None:
        store = self.make_store()
        await store.upsert_portrait_person_projection(
            PERSON_REF,
            build_capability_summary(
                {
                    "private_companion_enabled": True,
                    "proactive_private_enabled": False,
                    "portrait_mode": "use_existing",
                }
            ),
        )
        inserted = await store.upsert_portrait_fact(
            {
                "person_id": PERSON_REF["person_id"],
                "dimension": "preferred_address",
                "profile_cardinality": "single",
                "normalized_claim_hash": "d" * 64,
                "claim_summary": "希望被称为 错误旧称呼",
                "portrait_tier": "base",
                "producer_kind": "rule_explicit",
                "producer_version": "req036.rule.v1",
                "derivation_kind": "explicit_statement",
                "epistemic_status": "explicit",
                "source_scope": "private",
                "usable_scope": "self_low_global",
                "confidence": 0.99,
                "sensitivity": "low",
                "status": "active",
                "evidence_hashes": ["e" * 64],
                "operation_id": "legacy-v1-fact",
            }
        )
        self.assertTrue(inserted["ok"])

        summary = await store.portrait_summary(
            PERSON_REF["person_id"], scope="private"
        )

        self.assertEqual([], summary["items"])

    async def test_cross_scene_allowlist_keeps_schedule_like_habits_in_source_scope(self) -> None:
        store = self.make_store()
        service = PortraitService(store, _Config())
        event = types.SimpleNamespace(private_companion_unified_profile_context=self.dto("learn_and_use"))
        for message_id, text in (("food", "我喜欢烤肉"), ("schedule", "我通常凌晨工作")):
            result = await service.capture_user_message(
                SessionContext(
                    session_id="onebot:FriendMessage:10001",
                    scope="private",
                    platform="onebot",
                    user_id="10001",
                    message_id=message_id,
                    message_text=text,
                ),
                event=event,
            )
            self.assertTrue(result["ok"])

        group_summary = await service.read_summary(self.request(scope="group:onebot:group-a"))
        summaries = [item["summary"] for item in group_summary["items"]]
        self.assertTrue(any("烤肉" in item for item in summaries))
        self.assertFalse(any("凌晨" in item for item in summaries))

    async def test_use_existing_mode_syncs_without_collecting_new_evidence(self) -> None:
        store = self.make_store()
        service = PortraitService(store, _Config())
        event = types.SimpleNamespace(private_companion_unified_profile_context=self.dto("use_existing"))

        result = await service.capture_user_message(
            SessionContext(
                session_id="onebot:FriendMessage:10001",
                scope="private",
                platform="onebot",
                user_id="10001",
                message_id="use-existing-1",
                message_text="我喜欢烤肉",
            ),
            event=event,
        )

        self.assertFalse(result["ok"])
        self.assertEqual("portrait_learning_disabled", result["code"])
        self.assertEqual([], await store.list_portrait_evidence(PERSON_REF["person_id"]))
        self.assertTrue((await store.portrait_status(PERSON_REF["person_id"]))["ok"])

    async def test_daily_batch_consumes_all_queue_rows_for_the_aggregated_fact(self) -> None:
        store = self.make_store()
        service = PortraitService(store, _Config())
        event = types.SimpleNamespace(private_companion_unified_profile_context=self.dto())
        for index, text in enumerate(("我喜欢烤肉", "我真的喜欢烤肉", "我最喜欢烤肉")):
            await service.capture_user_message(
                SessionContext(
                    session_id="onebot:FriendMessage:10001",
                    scope="private",
                    platform="onebot",
                    user_id="10001",
                    message_id=f"queue-{index}",
                    message_text=text,
                ),
                event=event,
            )

        self.assertTrue((await service.run_daily_batch(PERSON_REF["person_id"], run_day="2026-08-05"))["ok"])
        self.assertEqual([], await store.list_pending_portrait_people())

    async def test_suspended_projection_invalidates_the_previous_active_revision(self) -> None:
        store = self.make_store()
        service = PortraitService(store, _Config())
        active_event = types.SimpleNamespace(private_companion_unified_profile_context=self.dto())
        await service.capture_user_message(
            SessionContext(
                session_id="onebot:FriendMessage:10001",
                scope="private",
                platform="onebot",
                user_id="10001",
                message_id="active-1",
                message_text="我喜欢烤肉",
            ),
            event=active_event,
        )

        suspended_ref = {**PERSON_REF, "projection_revision": 2, "profile_status": "suspended"}
        suspended_dto = build_profile_dto(
            person_ref=suspended_ref,
            capability_summary={
                "private_companion_enabled": True,
                "proactive_private_enabled": False,
                "portrait_mode": "disabled",
                "grant_source": "administrator",
            },
        )
        synced = await service.sync_profile_context(
            event=types.SimpleNamespace(private_companion_unified_profile_context=suspended_dto)
        )

        self.assertFalse(synced["ok"])
        self.assertEqual("bridge_person_mismatch", synced["code"])
        self.assertFalse((await store.portrait_status(PERSON_REF["person_id"]))["ok"])
        self.assertEqual("bridge_stale_revision", (await service.read_summary(self.request()))["code"])

    async def test_suppression_blocks_write_and_read_and_is_idempotent(self) -> None:
        store = self.make_store()
        await store.upsert_portrait_person_projection(
            PERSON_REF,
            build_capability_summary({
                "private_companion_enabled": True,
                "proactive_private_enabled": False,
                "portrait_mode": "use_existing",
            }),
        )
        claim_hash = normalized_claim_hash("preference", "like:烤肉")
        evidence = build_evidence(
            person_ref=PERSON_REF,
            scope="private",
            session_id="onebot:FriendMessage:10001",
            message_id="m-1",
            source_identity_key=PERSON_REF["resolved_identity_key"],
            text="我喜欢烤肉",
        )
        await store.add_portrait_evidence(evidence)
        inserted = await store.upsert_portrait_fact(
            {
                "person_id": PERSON_REF["person_id"], "dimension": "preference", "normalized_claim_hash": claim_hash,
                "claim_summary": "喜欢 烤肉", "portrait_tier": "base", "producer_kind": "rule_explicit",
                "producer_version": "test", "derivation_kind": "explicit_statement", "epistemic_status": "explicit",
                "source_scope": "private", "usable_scope": "self_low_global", "confidence": 0.9, "sensitivity": "low",
                "evidence_hashes": [evidence["evidence_hash"]], "operation_id": "fact-1",
            }
        )
        governed = await store.govern_portrait_fact(
            person_id=PERSON_REF["person_id"], fact_id=inserted["fact_id"], action="suppress",
            actor="administrator", operation_id="suppress-1",
        )
        self.assertTrue(governed["ok"])
        replay = await store.govern_portrait_fact(
            person_id=PERSON_REF["person_id"], fact_id=inserted["fact_id"], action="suppress",
            actor="administrator", operation_id="suppress-1",
        )
        self.assertEqual("suppression_idempotent_replay", replay["code"])
        self.assertEqual([], (await store.portrait_summary(PERSON_REF["person_id"], scope="private"))["items"])
        blocked = await store.upsert_portrait_fact(
            {
                "person_id": PERSON_REF["person_id"], "dimension": "preference", "normalized_claim_hash": claim_hash,
                "claim_summary": "喜欢 烤肉", "portrait_tier": "intelligent", "producer_kind": "daily_evidence_batch",
                "producer_version": "test", "derivation_kind": "aggregate", "epistemic_status": "inferred",
                "source_scope": "private", "usable_scope": "self_low_global", "confidence": 0.9, "sensitivity": "low",
                "evidence_hashes": [evidence["evidence_hash"]], "operation_id": "replay-evidence",
            }
        )
        self.assertEqual("portrait_suppressed", blocked["code"])

    async def test_migration_dry_run_apply_idempotence_and_rollback(self) -> None:
        store = self.make_store()
        dry = await store.portrait_migration(operation_id="migration-1", dry_run=True)
        self.assertEqual("migration_dry_run", dry["code"])
        applied = await store.portrait_migration(operation_id="migration-1", dry_run=False)
        self.assertEqual("migration_applied", applied["code"])
        self.assertEqual("migration_idempotent_replay", (await store.portrait_migration(operation_id="migration-1", dry_run=False))["code"])
        self.assertEqual("migration_rolled_back", (await store.rollback_portrait_migration(operation_id="migration-1"))["code"])

    async def test_denied_private_gate_bypasses_memory_service_before_identity_resolution(self) -> None:
        service = object.__new__(MemoryCompanionService)
        service.identity = types.SimpleNamespace(resolve_event_context=AsyncMock())
        event = types.SimpleNamespace(private_companion_req036_denied=True)

        await service.handle_llm_request(event, object())

        service.identity.resolve_event_context.assert_not_awaited()

    async def test_bridge_never_returns_high_sensitivity_portrait_items(self) -> None:
        class PortraitPlugin:
            async def read_unified_profile_portrait(self, _request, *, limit: int):
                self.assert_limit = limit
                return {
                    "ok": True,
                    "code": "profile_exact",
                    "portrait_revision": 7,
                    "items": [
                        {
                            "dimension": "preference",
                            "summary": "喜欢 烤肉",
                            "sensitivity": "low",
                            "portrait_tier": "base",
                            "epistemic_status": "explicit",
                            "confidence": 0.9,
                            "updated_at": "2026-08-05T00:00:00+00:00",
                        },
                        {
                            "dimension": "health",
                            "summary": "敏感健康信息",
                            "sensitivity": "high",
                            "portrait_tier": "base",
                            "epistemic_status": "explicit",
                            "confidence": 0.9,
                            "updated_at": "2026-08-05T00:00:00+00:00",
                        },
                    ],
                }

        plugin = PortraitPlugin()
        result = await MemoryCompanionBridge(plugin).read_unified_profile_portrait(
            self.request(),
            limit=99,
        )

        self.assertEqual(16, plugin.assert_limit)
        self.assertEqual(["喜欢 烤肉"], [item["summary"] for item in result["items"]])
        self.assertNotIn("敏感健康信息", str(result))

    async def test_unified_portrait_does_not_override_legacy_group_guard_toggle(self) -> None:
        service = object.__new__(MemoryCompanionService)
        service._context_bool = lambda *_args, **_kwargs: False
        ctx = SessionContext(
            session_id="onebot:GroupMessage:group-a",
            scope="group",
            platform="onebot",
            group_id="group-a",
            user_id="10001",
            user_name="测试用户",
        )
        profile = MemoryRecord(
            id="profile",
            memory_type="user_profile",
            subject=EntityRef(kind="user", id="10001", name="测试用户"),
            scope="group",
            group_id="group-a",
            visibility="group_public",
            content="不应进入群聊模型的旧画像。",
        )
        private = MemoryRecord(
            id="private",
            memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="10001", name="测试用户"),
            scope="private",
            visibility="private_pair",
            content="不应进入群聊模型的私聊记忆。",
        )

        filtered, blocked = service._filter_group_actor_memory_slots(
            ctx,
            {
                "user_profile": [SearchResult(memory=profile, score=1.0)],
                "conversation_summary": [SearchResult(memory=private, score=1.0)],
            },
        )

        self.assertEqual(
            {"profile", "private"},
            {item.memory.id for items in filtered.values() for item in items},
        )
        self.assertEqual([], blocked)

    async def test_group_moment_portrait_sinks_only_interaction_dimensions(self) -> None:
        store = self.make_store()
        service = PortraitService(store, _Config())
        candidates = [
            {
                "dimension": "communication_preference",
                "claim": "惯用玩梗风格：名场面语境中常用“笑死”这类表达带动气氛。",
                "claim_summary": "惯用玩梗风格：常用“笑死”带动气氛",
                "evidence_text": "哈哈笑死我了",
                "sender": "u1",
                "score": 3.0,
            },
            {
                "dimension": "boundary",
                "claim": "玩笑/接梗边界：在群里对\"u2\"开类似玩笑需谨慎。",
                "claim_summary": "玩笑/接梗边界",
                "evidence_text": "别拿我开玩笑",
                "sender": "u2",
                "score": 2.0,
            },
            {
                "dimension": "occupation",
                "claim": "职业（不应由名场面推断）",
                "claim_summary": "职业",
                "evidence_text": "我是医生",
                "sender": "u3",
                "score": 4.0,
            },
        ]
        result = await service.record_group_moment_portrait(
            PERSON_REF,
            candidates,
            scope="group:onebot:group-a",
            session_id="onebot:GroupMessage:group-a",
            group_id="group-a",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(2, result["facts"])  # occupation 被拒
        rows = store._conn.execute(
            "SELECT dimension, producer_kind, epistemic_status, sensitivity FROM portrait_facts ORDER BY dimension"
        ).fetchall()
        dims = {row["dimension"] for row in rows}
        self.assertEqual({"communication_preference", "boundary"}, dims)
        for row in rows:
            self.assertEqual("group_moment", row["producer_kind"])
            self.assertEqual("observed", row["epistemic_status"])
        boundary = [row for row in rows if row["dimension"] == "boundary"][0]
        self.assertEqual("sensitive", boundary["sensitivity"])
        evidence_count = store._conn.execute("SELECT COUNT(*) FROM portrait_evidence").fetchone()[0]
        queue_count = store._conn.execute("SELECT COUNT(*) FROM portrait_learning_queue").fetchone()[0]
        self.assertEqual(2, evidence_count)
        self.assertEqual(2, queue_count)


if __name__ == "__main__":
    unittest.main()
