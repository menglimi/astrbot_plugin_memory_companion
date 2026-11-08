from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.portrait_service import PortraitService
from astrbot_plugin_memory_companion.core.store import MemoryStore


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


class PortraitSelfBuiltH7Tests(unittest.IsolatedAsyncioTestCase):
    """H7: the portrait subsystem must run on real plugin-owned data.

    Production bridges never set private_companion_unified_profile_context, so
    these tests exercise the fallback that builds the profile DTO from
    identities.profile plus existing memories.
    """

    def make_store(self) -> MemoryStore:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = MemoryStore(Path(temp.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    @staticmethod
    def context(**overrides) -> SessionContext:
        values = dict(
            session_id="onebot:FriendMessage:10001",
            scope="private",
            platform="onebot",
            user_id="10001",
            user_name="阿哲",
            bot_id="bot-1",
            message_id="m-1",
            message_text="今天有点累",
        )
        values.update(overrides)
        return SessionContext(**values)

    @staticmethod
    def memory(content: str) -> MemoryRecord:
        return MemoryRecord(
            memory_type="explicit_memory",
            subject=EntityRef(kind="user", id="10001", name="阿哲"),
            object=EntityRef.bot_self("bot-1"),
            scope="private",
            session_id="onebot:FriendMessage:10001",
            platform="onebot",
            visibility="private_pair",
            sayability="direct",
            reality_level="real_user_fact",
            lifecycle="stable_memory",
            content=content,
            evidence="用户说过。",
            confidence=0.9,
            importance=0.8,
            owner_bot_id="bot-1",
            durability="normal",
            tags=["stable_fact"],
        )

    async def seed_identity(self, store: MemoryStore) -> None:
        await store.upsert_identity(
            platform="onebot",
            entity=EntityRef(kind="user", id="10001", name="阿哲"),
            aliases=[],
            profile={"relation_label": "朋友", "relation_address": "阿哲", "relation_source": "user"},
            confidence=0.9,
        )

    async def test_self_built_profile_projects_and_uses_memories(self) -> None:
        store = self.make_store()
        await self.seed_identity(store)
        await store.insert_memory(self.memory("我喜欢烤肉"))
        await store.insert_memory(self.memory("我最喜欢的人是周杰伦"))
        service = PortraitService(store, _Config())

        result = await service.capture_user_message(self.context())

        self.assertTrue(result["ok"], result)
        self.assertEqual("portrait_evidence_recorded", result["code"])
        self.assertGreaterEqual(result["facts"], 2)
        person_id = result["person_id"]
        self.assertRegex(person_id, r"^person_[0-9a-f]{24}$")
        people = store._conn.execute(
            "SELECT person_id, identity_assurance, profile_status FROM portrait_people WHERE person_id=?",
            (person_id,),
        ).fetchall()
        self.assertEqual(1, len(people))
        self.assertEqual("observed", people[0]["identity_assurance"])
        self.assertEqual("active", people[0]["profile_status"])
        fact_count = store._conn.execute(
            "SELECT COUNT(*) AS n FROM portrait_facts WHERE person_id=?",
            (person_id,),
        ).fetchone()["n"]
        # two facts: one preference from the first memory, one like from the second
        self.assertGreaterEqual(fact_count, 2)
        summary = await store.portrait_summary(
            person_id,
            scope="private",
            legacy_scope="private",
            limit=8,
            usage_min_confidence=0.75,
            inferred_freshness_days=90,
        )
        self.assertTrue(summary["ok"], summary)
        text = str(summary["items"])
        self.assertIn("烤肉", text)
        self.assertIn("周杰伦", text)

    async def test_without_identity_profile_capture_skips_gracefully(self) -> None:
        store = self.make_store()
        await store.insert_memory(self.memory("我喜欢烤肉"))
        service = PortraitService(store, _Config())

        result = await service.capture_user_message(self.context())

        self.assertFalse(result["ok"])
        self.assertEqual("portrait_profile_unavailable", result["code"])
        count = store._conn.execute("SELECT COUNT(*) AS n FROM portrait_people").fetchone()["n"]
        self.assertEqual(0, count)

    async def test_group_scope_never_self_builds_private_portrait(self) -> None:
        store = self.make_store()
        await self.seed_identity(store)
        service = PortraitService(store, _Config())
        ctx = self.context(scope="group", group_id="g-1", message_text="我喜欢烤肉")

        result = await service.capture_user_message(ctx)

        self.assertFalse(result["ok"])
        self.assertEqual("portrait_profile_unavailable", result["code"])
        count = store._conn.execute("SELECT COUNT(*) AS n FROM portrait_people").fetchone()["n"]
        self.assertEqual(0, count)

    async def test_bridge_dto_still_takes_precedence(self) -> None:
        from astrbot_plugin_memory_companion.unified_profile_contract import build_profile_dto

        store = self.make_store()
        await self.seed_identity(store)
        service = PortraitService(store, _Config())
        person_ref = {
            "person_id": "person_" + "1" * 24,
            "resolved_identity_key": "chat-origin-v1:" + "2" * 64,
            "projection_revision": 1,
            "identity_assurance": "observed",
            "profile_status": "active",
        }
        dto = build_profile_dto(
            person_ref=person_ref,
            capability_summary={
                "private_companion_enabled": True,
                "proactive_private_enabled": False,
                "portrait_mode": "learn_and_use",
                "grant_source": "administrator",
            },
        )
        event = type("Event", (), {"private_companion_unified_profile_context": dto})()

        result = await service.capture_user_message(self.context(message_text="我喜欢烤肉"), event=event)

        self.assertTrue(result["ok"], result)
        self.assertEqual(person_ref["person_id"], result["person_id"])
