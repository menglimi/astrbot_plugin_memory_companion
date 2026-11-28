"""H10 接线：情绪状态参与检索排序（倍率 + 未了债务跟进）。"""

from __future__ import annotations

import asyncio
import types
import unittest
from datetime import datetime, timedelta, timezone

from core.retrieval import RetrievalEngine


def _memory(**metadata: object) -> types.SimpleNamespace:
    return types.SimpleNamespace(metadata=dict(metadata))


class PersonaDynamicsMoodTests(unittest.TestCase):
    """_persona_dynamics_bonus 在基线情绪下必须与历史完全一致。"""

    def _bonus(self, memory: types.SimpleNamespace, profile: dict[str, object]) -> float:
        return RetrievalEngine._persona_dynamics_bonus(memory, profile)

    def test_baseline_mood_keeps_historical_bonus(self) -> None:
        memory = _memory(freshness_weight=0.8, open_loop_weight=0.6)
        plain = self._bonus(memory, {"contextual_recall": True, "open_loop_followup": True})
        neutral = self._bonus(
            memory,
            {
                "contextual_recall": True,
                "open_loop_followup": True,
                "emotion_mood": {"emotional_weight_multiplier": 1.0, "debt_followup_boost": 0.0},
            },
        )
        self.assertAlmostEqual(plain, neutral, places=6)

    def test_positive_mood_lifts_the_same_memory(self) -> None:
        memory = _memory(open_loop_weight=0.6, promise_weight=0.5)
        profile = {"contextual_recall": True, "open_loop_followup": True}
        plain = self._bonus(memory, profile)
        lifted = self._bonus(
            memory,
            {
                **profile,
                "emotion_mood": {"emotional_weight_multiplier": 1.4, "debt_followup_boost": 0.2},
            },
        )
        self.assertGreater(lifted, plain)

    def test_low_mood_pulls_the_same_memory_down(self) -> None:
        memory = _memory(open_loop_weight=0.6)
        profile = {"contextual_recall": True, "open_loop_followup": True}
        plain = self._bonus(memory, profile)
        lowered = self._bonus(
            memory,
            {**profile, "emotion_mood": {"emotional_weight_multiplier": 0.75, "debt_followup_boost": 0.0}},
        )
        self.assertLess(lowered, plain)

    def test_bonus_stays_bounded(self) -> None:
        memory = _memory(freshness_weight=1.0, open_loop_weight=1.0, promise_weight=1.0, emotional_debt_weight=1.0, scar_weight=1.0)
        bonus = self._bonus(
            memory,
            {
                "contextual_recall": True,
                "open_loop_followup": True,
                "emotion_mood": {"emotional_weight_multiplier": 1.6, "debt_followup_boost": 0.35},
            },
        )
        self.assertLessEqual(bonus, 0.24 + 1e-9)

    def test_garbage_mood_is_ignored(self) -> None:
        memory = _memory(open_loop_weight=0.6)
        profile = {"contextual_recall": True, "open_loop_followup": True}
        plain = self._bonus(memory, profile)
        self.assertAlmostEqual(
            plain,
            self._bonus(memory, {**profile, "emotion_mood": {"emotional_weight_multiplier": "x"}}),
            places=6,
        )


class EmotionRetrievalMoodTests(unittest.IsolatedAsyncioTestCase):
    """_emotion_retrieval_mood：基线不注入，有债务才注入。"""

    def _engine(self, store: object) -> RetrievalEngine:
        engine = object.__new__(RetrievalEngine)
        engine.store = store
        return engine

    def test_baseline_state_returns_none(self) -> None:
        class _Store:
            async def list_emotion_events(self, **_kwargs: object) -> list[dict[str, object]]:
                return []

        engine = self._engine(_Store())
        ctx = types.SimpleNamespace(bot_id="bot", session_id="s1")
        self.assertIsNone(asyncio.run(engine._emotion_retrieval_mood(ctx)))

    def test_debt_events_produce_a_multiplier(self) -> None:
        class _Store:
            async def list_emotion_events(self, **_kwargs: object) -> list[dict[str, object]]:
                return [
                    {
                        "event_type": "hurt",
                        "valence_hint": -0.8,
                        "arousal_hint": 0.7,
                        "occurred_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                    }
                ]

        engine = self._engine(_Store())
        ctx = types.SimpleNamespace(bot_id="bot", session_id="s1")
        mood = asyncio.run(engine._emotion_retrieval_mood(ctx))
        self.assertIsNotNone(mood)
        self.assertGreater(mood["emotional_weight_multiplier"], 1.0)
        self.assertGreater(mood["debt_followup_boost"], 0.0)

    def test_store_without_emotion_reader_returns_none(self) -> None:
        engine = self._engine(object())
        ctx = types.SimpleNamespace(bot_id="bot", session_id="s1")
        self.assertIsNone(asyncio.run(engine._emotion_retrieval_mood(ctx)))


if __name__ == "__main__":
    unittest.main()
