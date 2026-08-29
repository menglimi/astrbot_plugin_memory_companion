from __future__ import annotations

import sys
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bridge import MemoryCompanionBridge, sanitize_companion_expression_decision
from core.models import MemoryRecord, SearchResult, SessionContext
from core.service import MemoryCompanionService, MemoryRouteDecision
from core.time_intent import TimeIntent


def valid_expression_decision(**updates) -> dict:
    decision = {
        "contract": "companion_interaction_expression.v1",
        "expression_band": "warm",
        "tone": "gentle",
        "warmth": 76,
        "distance": 28,
        "address_style": "warm",
        "response_length": "balanced",
        "followup": True,
        "initiative": "passive_only",
        "proactive_budget": 0,
        "tts_style": "warm",
        "allowed_behaviors": ["reply", "support", "followup"],
        "safety_mode": "normal",
        "blocker": None,
        "reason_codes": ["interaction_band_applied"],
    }
    decision.update(updates)
    return decision


def memory_item() -> tuple[MemoryRecord, SearchResult]:
    memory = MemoryRecord(
        id="mem-1",
        memory_type="user_profile",
        scope="private",
        session_id="qq:FriendMessage:u1",
        visibility="private",
        sayability="direct",
        reality_level="real_user_fact",
        content="用户的生日是八月一日",
        confidence=0.95,
        importance=0.8,
        metadata={},
    )
    return memory, SearchResult(memory=memory, score=1.2, reason="")


class Req028ExpressionSyncTests(unittest.TestCase):
    @staticmethod
    def attested_decision() -> dict:
        companion = object()
        plugin = SimpleNamespace(
            context=SimpleNamespace(
                get_all_stars=lambda: [
                    SimpleNamespace(
                        star_cls=companion,
                        root_dir_name="astrbot_plugin_private_companion",
                        name="PrivateCompanion",
                        activated=True,
                    )
                ]
            )
        )
        bridge = MemoryCompanionBridge(plugin)
        capability = bridge.register_emotion_producer(companion)
        result = bridge.consume_expression_decision(
            valid_expression_decision(),
            producer_capability=capability,
            bot_id="bot-1",
            platform="qq",
            user_id="u1",
            scope="private",
            session_id="qq:FriendMessage:u1",
        )
        assert result["status"] == "accepted"
        return result["decision"]

    def test_expression_contract_is_strict_and_redacted(self) -> None:
        accepted = sanitize_companion_expression_decision(valid_expression_decision(owner_id="secret"))
        self.assertEqual("accepted", accepted["status"])
        self.assertEqual("warm", accepted["decision"]["expression_band"])
        self.assertNotIn("owner_id", accepted["decision"])

        hostile_values = (
            valid_expression_decision(contract="companion_interaction_expression.v2"),
            valid_expression_decision(expression_band="forged"),
            valid_expression_decision(followup="true"),
            valid_expression_decision(allowed_behaviors=["reply", "memory_override"]),
            valid_expression_decision(safety_mode="bypass"),
            valid_expression_decision(blocker="owner_override"),
            valid_expression_decision(reason_codes=["unknown_reason"]),
        )
        for value in hostile_values:
            with self.subTest(value=value):
                self.assertEqual("invalid", sanitize_companion_expression_decision(value)["status"])

    def test_private_context_consumes_request_scoped_decision_and_group_ignores_it(self) -> None:
        req = SimpleNamespace(_private_companion_expression_decision=self.attested_decision())
        private = SessionContext(
            scope="private",
            session_id="qq:FriendMessage:u1",
            platform="qq",
            bot_id="bot-1",
            user_id="u1",
        )
        MemoryCompanionService._apply_companion_expression_decision(private, req=req)
        self.assertEqual("companion_interaction_expression.v1", private.companion_expression_contract)
        self.assertEqual("warm", private.companion_expression_band)
        self.assertEqual(("reply", "support", "followup"), private.companion_expression_allowed_behaviors)

        group = SessionContext(scope="group", session_id="qq:GroupMessage:g1", group_id="g1", user_id="u1")
        MemoryCompanionService._apply_companion_expression_decision(group, req=req)
        self.assertEqual("", group.companion_expression_contract)
        self.assertEqual("", group.companion_expression_band)

    def test_unattested_expression_decision_is_ignored(self) -> None:
        req = SimpleNamespace(
            _private_companion_expression_decision=valid_expression_decision()
        )
        ctx = SessionContext(
            scope="private",
            session_id="qq:FriendMessage:u1",
            platform="qq",
            bot_id="bot-1",
            user_id="u1",
        )
        MemoryCompanionService._apply_companion_expression_decision(ctx, req=req)
        self.assertEqual("", ctx.companion_expression_contract)

    def test_companion_caps_unsolicited_mentions_but_explicit_recall_still_reads_fact(self) -> None:
        service = MemoryCompanionService.__new__(MemoryCompanionService)
        memory, item = memory_item()
        route = MemoryRouteDecision()
        restricted = SessionContext(
            scope="private",
            message_text="今天过得怎么样",
            companion_expression_contract="companion_interaction_expression.v1",
            companion_expression_band="hurt",
            companion_expression_allowed_behaviors=("acknowledge", "brief_reply", "give_space"),
            companion_expression_safety_mode="normal",
        )
        expression, reason = service._memory_expression_decision(
            restricted, memory, item, "user_profile", route, TimeIntent(), query_text=restricted.message_text
        )
        self.assertEqual("tone", expression)
        self.assertEqual("companion_expression:band_hurt", reason)

        restricted.message_text = "你还记得我的生日吗"
        expression, reason = service._memory_expression_decision(
            restricted, memory, item, "user_profile", route, TimeIntent(), query_text=restricted.message_text
        )
        self.assertEqual("mention", expression)
        self.assertEqual("stable_user_fact", reason)

    def test_allowed_behaviors_are_a_maximum_not_a_memory_override(self) -> None:
        service = MemoryCompanionService.__new__(MemoryCompanionService)
        memory, item = memory_item()
        route = MemoryRouteDecision()
        relaxed = SessionContext(
            scope="private",
            message_text="随便聊聊",
            companion_expression_contract="companion_interaction_expression.v1",
            companion_expression_band="relaxed",
            companion_expression_allowed_behaviors=("reply", "clarify"),
            companion_expression_safety_mode="normal",
        )
        self.assertEqual(
            ("tone", "companion_expression:behavior_cap"),
            service._memory_expression_decision(relaxed, memory, item, "user_profile", route, TimeIntent()),
        )
        relaxed.companion_expression_band = "warm"
        relaxed.companion_expression_allowed_behaviors = ("reply", "support")
        self.assertEqual(
            ("mention", "stable_user_fact"),
            service._memory_expression_decision(relaxed, memory, item, "user_profile", route, TimeIntent()),
        )

    def test_tone_abstraction_can_be_disabled_without_changing_the_default(self) -> None:
        service = MemoryCompanionService.__new__(MemoryCompanionService)
        memory, item = memory_item()
        route = MemoryRouteDecision()
        ctx = SessionContext(scope="private", message_text="随便聊聊")

        self.assertEqual(
            ("mention", "stable_user_fact"),
            service._memory_expression_decision(ctx, memory, item, "user_profile", route, TimeIntent()),
        )

        service.config = SimpleNamespace(bool=lambda _key, _default: False)
        self.assertEqual(
            ("candidate", "tone_abstraction_disabled"),
            service._memory_expression_decision(ctx, memory, item, "user_profile", route, TimeIntent()),
        )

    def test_paired_mode_does_not_inject_second_tone_or_write_legacy_state(self) -> None:
        service = MemoryCompanionService.__new__(MemoryCompanionService)
        ctx = SessionContext(
            scope="private",
            session_id="qq:FriendMessage:u1",
            user_id="u1",
            message_id="m1",
            relationship_authority_source="private_companion.relationship_score",
            companion_expression_contract="companion_interaction_expression.v1",
            companion_expression_band="warm",
            companion_expression_allowed_behaviors=("reply", "support"),
            companion_expression_safety_mode="normal",
        )
        calls = {"get": 0, "save": 0}
        service._get_relationship_phase = MethodType(
            lambda _self, _ctx: calls.__setitem__("get", calls["get"] + 1) or {}, service
        )
        service._save_relationship_phase_state = MethodType(
            lambda _self: calls.__setitem__("save", calls["save"] + 1), service
        )
        self.assertEqual("", service._address_hint_for_injection(ctx))
        service._update_address_evolution(ctx, "宝贝")
        self.assertFalse(service._update_relationship_phase_momentum(ctx, touch_type="warm"))
        self.assertEqual({"get": 0, "save": 0}, calls)

    def test_standalone_fallback_remains_available(self) -> None:
        service = MemoryCompanionService.__new__(MemoryCompanionService)
        service._BOT_ADDRESS_SUGGESTIONS = {"acquaintance": {"hint": "standalone address hint"}}
        service._get_relationship_phase = MethodType(
            lambda _self, _ctx: {"phase": "acquaintance", "current_address_phase": ""}, service
        )
        ctx = SessionContext(scope="private", session_id="qq:FriendMessage:u1", user_id="u1")
        self.assertEqual("standalone address hint", service._address_hint_for_injection(ctx))

    def test_page_source_exposes_coordination_without_second_relationship_authority(self) -> None:
        source = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        for retired in ("关系阶段演进", "情绪事件队列", "称呼演变记录", "Bot 称呼建议"):
            self.assertNotIn(retired, source)
        for required in ("陪伴表达协同状态", "记忆触动趋势", "记忆触动事件", "当时关系情境"):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
