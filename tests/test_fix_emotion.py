"""H10 / H11 回归：当轮情绪状态建模 + 真正的情绪调制器。

H10：以前只有记忆条目上的静态 emotional_weight，没有「她此刻是什么情绪」。
     现在 core/emotion_state.py 从真实 emotion_events 聚合出 valence/arousal/debt，
     并按半衰期衰减；同一批事件换个时间点分数就不一样。
H11：core/affect_modulation.py 以前只是 DTO，现在输出检索权重倍率与注入语气，
     带边界夹取与衰减。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.affect_modulation import (  # noqa: E402
    DEBT_FOLLOWUP_BOOST_MAX,
    RETRIEVAL_MULTIPLIER_MAX,
    RETRIEVAL_MULTIPLIER_MIN,
    apply_emotional_weight,
    debt_followup_boost,
    emotional_weight_multiplier,
    modulate,
    mood_label,
    normalize_affect_modulation,
    tone_profile,
)
from core.emotion_event_contract import normalize_emotion_event  # noqa: E402
from core.emotion_state import (  # noqa: E402
    EmotionState,
    apply_event,
    baseline_state,
    load_state,
    save_state,
    state_for_session,
    state_from_events,
)
from core.store import MemoryStore  # noqa: E402

NOW = 1_800_000_000.0


def _event(event_type: str, *, occurred_at: float, intensity: float = 0.9, **extra: object) -> dict:
    payload = {
        "event_id": f"ev-{event_type}-{int(occurred_at)}",
        "event_type": event_type,
        "intensity": intensity,
        "confidence": 0.9,
        "occurred_at": occurred_at,
    }
    payload.update(extra)
    return payload


class EmotionStateTests(unittest.TestCase):
    def test_valence_and_debt_follow_real_events(self) -> None:
        hurt = state_from_events([_event("hurt", occurred_at=NOW)], now=NOW)
        praise = state_from_events([_event("praise", occurred_at=NOW)], now=NOW)
        self.assertLess(hurt.valence, -0.2)
        self.assertGreater(hurt.debt, 0.2)
        self.assertGreater(praise.valence, 0.2)
        self.assertEqual(0.0, praise.debt)

    def test_same_events_decay_over_time(self) -> None:
        events = [_event("hurt", occurred_at=NOW)]
        fresh = state_from_events(events, now=NOW)
        later = state_from_events(events, now=NOW + 3 * 3600)  # 正好一个半衰期
        self.assertLess(abs(later.valence), abs(fresh.valence) * 0.6)
        self.assertLess(later.debt, fresh.debt)
        # 同一输入、同一时间点必须完全一样（没有隐式随机/当前时间）。
        self.assertEqual(fresh, state_from_events(events, now=NOW))

    def test_state_is_bounded_for_extreme_events(self) -> None:
        events = [_event("hurt", occurred_at=NOW, intensity=1.0, confidence=1.0) for _ in range(30)]
        state = state_from_events(events, now=NOW)
        self.assertGreaterEqual(state.valence, -1.0)
        self.assertLessEqual(state.valence, 1.0)
        self.assertGreaterEqual(state.arousal, 0.0)
        self.assertLessEqual(state.arousal, 1.0)
        self.assertGreaterEqual(state.debt, 0.0)
        self.assertLessEqual(state.debt, 1.0)

    def test_apply_event_accumulates_then_repairs_debt(self) -> None:
        hurt = apply_event(baseline_state(), _event("hurt", occurred_at=NOW), now=NOW)
        self.assertGreater(hurt.debt, 0.0)
        self.assertLess(hurt.valence, 0.0)
        repaired = apply_event(hurt, _event("apology", occurred_at=NOW + 60), now=NOW + 60)
        self.assertLess(repaired.debt, hurt.debt)
        self.assertGreater(repaired.valence, hurt.valence)
        self.assertGreaterEqual(repaired.events, 2)

    def test_apply_event_ignores_empty_payload(self) -> None:
        state = apply_event(baseline_state(), {}, now=NOW)
        self.assertEqual(0.0, state.valence)
        self.assertEqual(0, state.events)

    def test_state_dict_roundtrip_and_garbage(self) -> None:
        state = state_from_events([_event("intimacy", occurred_at=NOW)], now=NOW)
        restored = EmotionState.from_dict(state.to_dict())
        self.assertAlmostEqual(state.valence, restored.valence, places=3)
        self.assertEqual(state.source_event_ids, restored.source_event_ids)
        self.assertEqual(baseline_state().valence, EmotionState.from_dict("not a dict").valence)
        clamped = EmotionState.from_dict({"valence": 99, "arousal": -5, "debt": 3})
        self.assertEqual(1.0, clamped.valence)
        self.assertEqual(0.0, clamped.arousal)
        self.assertEqual(1.0, clamped.debt)

    def test_state_file_roundtrip_and_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "data" / "emotion_state.json"
            state = state_from_events([_event("hurt", occurred_at=NOW)], now=NOW)
            self.assertTrue(save_state(path, state))
            loaded = load_state(path)
            self.assertAlmostEqual(state.valence, loaded.valence, places=3)
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(0.0, load_state(path).valence)
            self.assertEqual(0.0, load_state(Path(temp) / "missing.json").valence)

class StoredEmotionEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def test_state_from_stored_emotion_events(self) -> None:
        await self.store.upsert_emotion_event(
            normalize_emotion_event(
                {
                    "event_type": "hurt",
                    "session_id": "qq:FriendMessage:u1",
                    "dedupe_key": "m1",
                    "intensity": 0.9,
                    "confidence": 0.9,
                },
                producer_plugin="private_companion",
            )
        )
        rows = await self.store.list_emotion_events(session_id="qq:FriendMessage:u1", limit=10)
        self.assertEqual(1, len(rows))
        state = state_from_events(rows)
        self.assertLess(state.valence, 0.0)
        self.assertGreater(state.debt, 0.0)
        self.assertEqual(1, state.events)
        # 检索/注入的接入口：一个 await 就拿到当轮情绪，不需要新表。
        wired = await state_for_session(self.store, session_id="qq:FriendMessage:u1")
        self.assertAlmostEqual(state.valence, wired.valence, places=4)
        self.assertAlmostEqual(state.debt, wired.debt, places=4)
        # 没有这个方法的 store（老版本/替身）安静回基线，不抛。
        self.assertEqual(0.0, (await state_for_session(object())).valence)
        self.assertEqual(0.0, (await state_for_session(None)).valence)


class AffectModulatorTests(unittest.TestCase):
    def test_neutral_state_multiplier_is_exactly_one(self) -> None:
        self.assertEqual(1.0, emotional_weight_multiplier(baseline_state()))
        self.assertEqual(1.0, emotional_weight_multiplier({"valence": 0, "arousal": 0, "debt": 0}))
        self.assertEqual(0.0, debt_followup_boost(baseline_state()))

    def test_multiplier_rises_with_debt(self) -> None:
        scores = [
            emotional_weight_multiplier({"valence": 0.0, "arousal": 0.0, "debt": debt})
            for debt in (0.0, 0.3, 0.6, 1.0)
        ]
        self.assertEqual(scores, sorted(scores))
        self.assertGreater(scores[-1], scores[0])

    def test_negative_valence_lowers_positive_raises(self) -> None:
        neutral = emotional_weight_multiplier({"valence": 0.0, "arousal": 0.0, "debt": 0.0})
        low = emotional_weight_multiplier({"valence": -0.9, "arousal": 0.0, "debt": 0.0})
        warm = emotional_weight_multiplier({"valence": 0.9, "arousal": 0.0, "debt": 0.0})
        self.assertLess(low, neutral)
        self.assertGreater(warm, neutral)

    def test_multiplier_and_boost_are_clamped(self) -> None:
        for valence in (-1.0, 0.0, 1.0):
            for arousal in (0.0, 0.5, 1.0):
                for debt in (0.0, 0.5, 1.0):
                    state = {"valence": valence, "arousal": arousal, "debt": debt}
                    multiplier = emotional_weight_multiplier(state)
                    self.assertGreaterEqual(multiplier, RETRIEVAL_MULTIPLIER_MIN)
                    self.assertLessEqual(multiplier, RETRIEVAL_MULTIPLIER_MAX)
                    boost = debt_followup_boost(state)
                    self.assertGreaterEqual(boost, 0.0)
                    self.assertLessEqual(boost, DEBT_FOLLOWUP_BOOST_MAX)

    def test_tone_profile_tracks_state(self) -> None:
        tense = tone_profile({"valence": -0.2, "arousal": 0.6, "debt": 0.9})
        bright = tone_profile({"valence": 0.8, "arousal": 0.8, "debt": 0.0})
        calm = tone_profile(baseline_state())
        self.assertEqual("tense", tense["label"])
        self.assertEqual("bright", bright["label"])
        self.assertEqual("calm", calm["label"])
        self.assertNotEqual(tense["guidance"], bright["guidance"])
        for profile in (tense, bright, calm):
            self.assertGreaterEqual(profile["warmth"], 0.0)
            self.assertLessEqual(profile["warmth"], 1.0)
            self.assertGreaterEqual(profile["brevity"], 0.0)
            self.assertLessEqual(profile["brevity"], 1.0)
            self.assertTrue(profile["guidance"])
            self.assertLessEqual(len(profile["guidance"]), 60)
        self.assertGreater(tense["brevity"], calm["brevity"])
        self.assertGreater(bright["warmth"], tense["warmth"])

    def test_modulate_returns_dto_and_decays(self) -> None:
        state = state_from_events([_event("hurt", occurred_at=NOW)], now=NOW)
        fresh = modulate(state, now=NOW)
        later = modulate(state, now=NOW + 6 * 3600)
        self.assertEqual("affect_modulator.v1", fresh["schema_version"])
        self.assertEqual("affect_modulation.v1", fresh["affect"]["schema_version"])
        # affect 仍是 v1 DTO，重复归一化必须幂等（老消费者照旧能读）。
        self.assertEqual(fresh["affect"], normalize_affect_modulation(fresh["affect"]))
        self.assertIn("ev-hurt-1800000000", fresh["affect"]["source_event_ids"])
        # 读数带时间戳：注入侧能判断"这条情绪是什么时候的"。
        self.assertAlmostEqual(fresh["affect"]["computed_at"], NOW, places=3)
        # 还没开始记的状态没有时间戳，就是 0，不编一个假时间出来。
        self.assertEqual(0.0, modulate(baseline_state())["affect"]["computed_at"])
        self.assertGreater(fresh["retrieval"]["emotional_weight_multiplier"], 1.0)
        # 六小时后情绪淡了，倍率必须回到更接近 1.0 的位置。
        self.assertLess(later["retrieval"]["emotional_weight_multiplier"], fresh["retrieval"]["emotional_weight_multiplier"])
        self.assertLess(abs(later["affect"]["valence"]), abs(fresh["affect"]["valence"]))

    def test_apply_emotional_weight_clamped(self) -> None:
        hot = {"valence": 1.0, "arousal": 1.0, "debt": 1.0}
        cold = {"valence": -1.0, "arousal": 0.0, "debt": 0.0}
        self.assertEqual(1.0, apply_emotional_weight(0.9, hot))
        self.assertLess(apply_emotional_weight(0.9, cold), 0.9)
        self.assertEqual(0.0, apply_emotional_weight("nonsense", hot))
        self.assertEqual(1.0, apply_emotional_weight(5.0, baseline_state()))

    def test_mood_label_matches_state_module(self) -> None:
        self.assertEqual("tense", mood_label({"valence": 0.0, "arousal": 0.0, "debt": 0.9}))
        self.assertEqual("low", mood_label({"valence": -0.8, "arousal": 0.2, "debt": 0.1}))
        self.assertEqual("calm", mood_label({}))


if __name__ == "__main__":
    unittest.main()
