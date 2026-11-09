"""H2：分量要按真实证据算，不再用 content LIKE 猜。

覆盖三层：
  1) 纯函数 compute_person_weight：没有证据包时行为与 2.6.0 完全一致；
     有证据包时按净证据强度算 bond，负面证据压、修复证据补、坏证据包退回老口径。
  2) store._person_weight_stats_sync：冲突改由 emotion_events 真实事件计数，
     记忆正文里出现「吵架」不再算冲突。
  3) store.person_weight：真实 hurt 事件让分数下降，道歉/和好事件让分数回升，
     同输入重复计算稳定。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    utc_now,
)
from astrbot_plugin_memory_companion.core.person_weight import compute_person_weight
from astrbot_plugin_memory_companion.core.store import MemoryStore

BOT_ID = "bot-a"
USER_ID = "u1"


class PersonWeightEvidenceMathTests(unittest.TestCase):
    """纯函数层：证据包有没有，决定 bond 走哪条路。"""

    def _base(self, **extra):
        kwargs = dict(
            memory_count=40,
            imprint_count=1,
            important_count=3,
            active_days=12,
            days_since_first=120,
            days_since_last=2,
        )
        kwargs.update(extra)
        return compute_person_weight(**kwargs)

    def test_without_evidence_pack_the_old_count_formula_is_unchanged(self) -> None:
        legacy = self._base(conflict_count=3, commitment_count=1)
        # 老口径：bond = min(20, 3*4 + 1*2.5) = 14.5
        self.assertEqual(legacy["components"]["bond"], 14.5)
        self.assertNotIn("evidence", legacy["components"])

    def test_evidence_pack_replaces_the_count_based_bond(self) -> None:
        evidence = {"score": 0.0}
        result = self._base(conflict_count=3, commitment_count=1, evidence=evidence)
        # 有证据包时不再看 conflict_count：bond 只剩承诺的 2.5
        self.assertEqual(result["components"]["bond"], 2.5)
        self.assertEqual(result["components"]["evidence"], 0.0)

    def test_strong_evidence_scores_higher_than_weak_evidence(self) -> None:
        weak = self._base(evidence={"score": 0.1})
        strong = self._base(evidence={"score": 0.8})
        self.assertLess(weak["weight"], strong["weight"])
        self.assertLess(weak["components"]["bond"], strong["components"]["bond"])

    def test_broken_evidence_pack_falls_back_to_legacy_math(self) -> None:
        legacy = self._base(conflict_count=3, commitment_count=1)
        broken = self._base(
            conflict_count=3, commitment_count=1, evidence={"score": "not-a-number"}
        )
        self.assertEqual(broken["weight"], legacy["weight"])
        self.assertEqual(broken["components"]["bond"], legacy["components"]["bond"])

    def test_evidence_is_clamped_into_zero_one(self) -> None:
        over = self._base(evidence={"score": 9.0})
        self.assertEqual(over["components"]["evidence"], 1.0)
        under = self._base(evidence={"score": -3.0})
        self.assertEqual(under["components"]["evidence"], 0.0)


class PersonWeightEvidenceStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory_companion.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def _insert(
        self,
        memory_id: str,
        *,
        content: str,
        durability: str = "normal",
        importance: float = 0.6,
        metadata: dict | None = None,
    ) -> None:
        await self.store.insert_memory(
            MemoryRecord(
                id=memory_id,
                memory_type="conversation_summary",
                subject=EntityRef(kind="user", id=USER_ID, name="小王"),
                object=EntityRef(kind="bot", id=BOT_ID),
                scope="private",
                visibility="private_pair",
                lifecycle="stable_memory",
                owner_bot_id=BOT_ID,
                platform="qq",
                durability=durability,
                importance=importance,
                content=content,
                metadata=dict(metadata or {}),
            )
        )

    async def _emotion(
        self,
        event_id: str,
        event_type: str,
        *,
        valence: float = 0.0,
        intensity: float = 60.0,
    ) -> None:
        await self.store.upsert_emotion_event(
            {
                "event_id": event_id,
                "producer_plugin": "memory_companion",
                "origin_kind": "interaction",
                "platform": "qq",
                "bot_id": BOT_ID,
                "scope": "private",
                "session_id": "qq:FriendMessage:u1",
                "actor_ref": {"kind": "user", "id": USER_ID, "role": "speaker"},
                "target_ref": {"kind": "bot", "id": BOT_ID, "role": "listener"},
                "event_type": event_type,
                "intensity": intensity,
                "valence_hint": valence,
                "occurred_at": utc_now(),
                "dedupe_key": event_id,
            }
        )

    async def _weight(self) -> int:
        info = await self.store.person_weight(
            user_id=USER_ID, platform="qq", bot_id=BOT_ID, max_age_seconds=0
        )
        return int(info["weight"])

    async def _seed_memories(self) -> None:
        for index in range(6):
            await self._insert(
                f"m{index}",
                content=f"第{index}次聊天，聊了些日常。",
                metadata={"emotional_weight": 0.5},
            )

    async def test_keyword_in_content_is_no_longer_a_conflict(self) -> None:
        await self._insert("m1", content="我们吵架了，后来冷战了一整天。")
        stats = self.store._person_weight_stats_sync(USER_ID, "qq", BOT_ID)
        self.assertEqual(stats["conflict_count"], 0)
        self.assertEqual(stats["evidence"]["negative_events"], 0)
        self.assertEqual(stats["evidence"]["sampled_memories"], 1)

    async def test_real_negative_events_lower_the_weight(self) -> None:
        await self._seed_memories()
        before = await self._weight()
        for index in range(3):
            await self._emotion(f"ev-hurt-{index}", "hurt", valence=-0.7)
        stats = self.store._person_weight_stats_sync(USER_ID, "qq", BOT_ID)
        self.assertEqual(stats["evidence"]["negative_events"], 3)
        after = await self._weight()
        self.assertLess(after, before)
        # 吵过会变轻，但不会归零：留下过记忆就不会消失。
        self.assertGreaterEqual(after, 1)

    async def test_apology_and_reconciliation_lift_the_weight_back(self) -> None:
        await self._seed_memories()
        for index in range(3):
            await self._emotion(f"ev-hurt-{index}", "hurt", valence=-0.7)
        conflicted = await self._weight()
        await self._emotion("ev-apology", "apology", valence=0.6)
        await self._emotion("ev-warm", "warm_memory", valence=0.7)
        await self._emotion("ev-comfort", "comfort", valence=0.5)
        repaired = await self._weight()
        self.assertGreater(repaired, conflicted)

    async def test_weight_is_stable_for_the_same_evidence(self) -> None:
        await self._seed_memories()
        await self._emotion("ev-hurt-0", "hurt", valence=-0.7)
        first = await self._weight()
        second = await self._weight()
        self.assertEqual(first, second)
        components = (
            await self.store.person_weight(
                user_id=USER_ID, platform="qq", bot_id=BOT_ID, max_age_seconds=0
            )
        )["components"]
        self.assertIn("evidence", components)
        self.assertGreaterEqual(components["evidence"], 0.0)

    async def test_events_of_other_people_do_not_move_this_weight(self) -> None:
        await self._seed_memories()
        before = await self._weight()
        await self.store.upsert_emotion_event(
            {
                "event_id": "ev-other",
                "producer_plugin": "memory_companion",
                "origin_kind": "interaction",
                "platform": "qq",
                "bot_id": BOT_ID,
                "scope": "private",
                "session_id": "qq:FriendMessage:u2",
                "actor_ref": {"kind": "user", "id": "u2", "role": "speaker"},
                "target_ref": {"kind": "bot", "id": BOT_ID, "role": "listener"},
                "event_type": "hurt",
                "intensity": 80.0,
                "valence_hint": -0.9,
                "occurred_at": utc_now(),
                "dedupe_key": "ev-other",
            }
        )
        stats = self.store._person_weight_stats_sync(USER_ID, "qq", BOT_ID)
        self.assertEqual(stats["evidence"]["negative_events"], 0)
        self.assertEqual(await self._weight(), before)


if __name__ == "__main__":
    unittest.main()
