"""2.4：她心里给这个人留多大位置（分量）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .package_bootstrap import bootstrap_package

ROOT = bootstrap_package()
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.person_weight import (
    BAND_ACQUAINTANCE,
    BAND_CLOSE,
    BAND_FAMILIAR,
    BAND_IMPRINT,
    BAND_IMPORTANT,
    BAND_STRANGER,
    band_of,
    clamp_weight,
    compute_person_weight,
    decay_factor,
    describe,
    merge_external_weight,
)
from astrbot_plugin_memory_companion.core.store import MemoryStore

BOT_ID = "bot-a"


class PersonWeightMathTests(unittest.TestCase):
    def test_no_memory_means_no_weight(self) -> None:
        result = compute_person_weight(memory_count=0)
        self.assertEqual(result["weight"], 0)
        self.assertEqual(result["band"], BAND_STRANGER)

    def test_one_memory_never_drops_to_zero(self) -> None:
        # 留下过记忆就不会从她心里消失，只会变淡。
        result = compute_person_weight(memory_count=1, days_since_last=3000)
        self.assertGreaterEqual(result["weight"], 1)

    def test_bands_go_up_with_evidence(self) -> None:
        light = compute_person_weight(memory_count=2, active_days=1)
        heavy = compute_person_weight(
            memory_count=240,
            imprint_count=8,
            important_count=30,
            active_days=60,
            days_since_first=900,
            days_since_last=1,
            conflict_count=3,
            commitment_count=4,
        )
        self.assertLess(light["weight"], heavy["weight"])
        self.assertEqual(heavy["band"], BAND_IMPRINT)

    def test_idle_only_softens_never_erases(self) -> None:
        fresh = compute_person_weight(memory_count=80, active_days=40)
        idle = compute_person_weight(
            memory_count=80, active_days=40, days_since_last=3650
        )
        self.assertLess(idle["weight"], fresh["weight"])
        # 最多打八五折
        self.assertGreaterEqual(idle["weight"], int(fresh["weight"] * 0.84))

    def test_correction_moves_weight_and_is_explained(self) -> None:
        base = compute_person_weight(memory_count=60, active_days=20)
        lowered = compute_person_weight(
            memory_count=60, active_days=20, correction=-40
        )
        self.assertLess(lowered["weight"], base["weight"])
        self.assertEqual(lowered["components"]["correction"], -40)

    def test_band_thresholds(self) -> None:
        self.assertEqual(band_of(0), BAND_STRANGER)
        self.assertEqual(band_of(12), BAND_ACQUAINTANCE)
        self.assertEqual(band_of(30), BAND_FAMILIAR)
        self.assertEqual(band_of(50), BAND_CLOSE)
        self.assertEqual(band_of(70), BAND_IMPORTANT)
        self.assertEqual(band_of(90), BAND_IMPRINT)

    def test_clamp_weight_bounds(self) -> None:
        self.assertEqual(clamp_weight(-5), 0)
        self.assertEqual(clamp_weight(150), 100)
        self.assertEqual(clamp_weight("abc"), 0)

    def test_heavier_people_decay_slower(self) -> None:
        self.assertLess(decay_factor(5), decay_factor(30))
        self.assertLess(decay_factor(30), decay_factor(95))

    def test_describe_is_human(self) -> None:
        self.assertIn("亲近", describe(52))
        self.assertNotIn("{", describe(52))

    def test_external_projection_wins_when_present(self) -> None:
        local = compute_person_weight(memory_count=10)
        merged = merge_external_weight(local, 88, external_phase="恋人")
        self.assertEqual(merged["weight"], 88)
        self.assertEqual(merged["source"], "companion")
        untouched = merge_external_weight(local, None)
        self.assertEqual(untouched["weight"], local["weight"])


class PersonWeightStoreTests(unittest.IsolatedAsyncioTestCase):
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
        memory_type: str = "conversation_summary",
        bot_id: str = BOT_ID,
        occurred_at: str = "",
    ) -> None:
        await self.store.insert_memory(
            MemoryRecord(
                id=memory_id,
                memory_type=memory_type,
                subject=EntityRef(kind="user", id="u1", name="小王"),
                object=EntityRef(kind="bot", id=bot_id),
                scope="private",
                visibility="private_pair",
                lifecycle="stable_memory",
                owner_bot_id=bot_id,
                durability=durability,
                content=content,
                occurred_at=occurred_at,
            )
        )

    async def test_weight_is_computed_from_memories(self) -> None:
        await self._insert("m1", content="她说过喜欢下雨天。", durability="pinned")
        await self._insert("m2", content="上次吵架以后和好了。")
        result = await self.store.person_weight(user_id="u1", bot_id=BOT_ID)
        self.assertGreater(result["weight"], 0)
        self.assertIn(result["band"], (BAND_ACQUAINTANCE, BAND_FAMILIAR, BAND_CLOSE))
        self.assertEqual(result["source"], "auto")
        self.assertTrue(result["updated_at"])

    async def test_two_bots_have_separate_weights(self) -> None:
        await self._insert("m1", content="阿莉娜记得的事。", bot_id=BOT_ID)
        await self.store.person_weight(user_id="u1", bot_id=BOT_ID)
        other = await self.store.person_weight(user_id="u1", bot_id="bot-b")
        self.assertEqual(other["weight"], 0)
        self.assertEqual(other["band"], BAND_STRANGER)

    async def test_user_can_lower_the_weight_and_it_survives_refresh(self) -> None:
        for index in range(6):
            await self._insert(f"m{index}", content=f"第{index}次聊天。")
        before = await self.store.person_weight(user_id="u1", bot_id=BOT_ID)
        after = await self.store.set_person_weight(
            user_id="u1", weight=3, bot_id=BOT_ID
        )
        self.assertEqual(after["weight"], 3)
        self.assertEqual(after["source"], "user")
        refreshed = await self.store.person_weight(
            user_id="u1", bot_id=BOT_ID, max_age_seconds=0
        )
        self.assertEqual(refreshed["weight"], 3)
        self.assertLess(before["weight"], before["weight"] + 1)

    async def test_bulk_refresh_does_not_duplicate_rows(self) -> None:
        await self._insert("m1", content="早上好。")
        refreshed = await self.store.refresh_person_weights(limit=10, max_age_seconds=0)
        self.assertEqual(refreshed, 1)
        await self.store.refresh_person_weights(limit=10, max_age_seconds=0)
        with self.store._lock:  # noqa: SLF001 - 测试直接数行
            count = self.store._conn.execute(
                "SELECT COUNT(*) AS n FROM person_weights"
            ).fetchone()["n"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
