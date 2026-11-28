from __future__ import annotations

import unittest
from types import SimpleNamespace

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.visibility import (
    ScopeWriteDecision,
    can_change_person_weight,
    can_remember_in_scope,
    message_requests_weight_change,
    resolve_group_admin,
)


class _Config:
    """Minimal stand-in for AstrBotConfig.bool(dotted_key, default)."""

    def __init__(self, data: dict | None = None) -> None:
        self.data = data or {}

    def bool(self, key: str, default: bool = False) -> bool:
        current = self.data
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return bool(current)


def _ctx(scope: str = "private", message_text: str = "", **overrides) -> SessionContext:
    data = {
        "scope": scope,
        "user_id": "u1",
        "user_name": "小明",
        "group_id": "g1" if scope == "group" else "",
        "message_text": message_text,
    }
    data.update(overrides)
    return SessionContext(**data)


def _group_config(enabled: bool = True) -> _Config:
    return _Config({"memory_tools": {"allow_group_remember": enabled}})


class RememberScopeGuardTests(unittest.TestCase):
    """P3：群里普通成员不能写 group_public，管理员/私聊才行。"""

    def test_private_chat_may_remember_private_memory(self) -> None:
        decision = can_remember_in_scope(_ctx("private"), _Config())

        self.assertTrue(decision.allowed)
        self.assertEqual("private_remember_allowed", decision.code)
        self.assertEqual("private_pair", decision.visibility)
        self.assertEqual("normal", decision.durability)

    def test_group_member_is_refused_even_when_group_remember_is_enabled(self) -> None:
        decision = can_remember_in_scope(
            _ctx("group"), _group_config(True), is_group_admin=False
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("group_remember_requires_admin", decision.code)
        self.assertEqual("internal", decision.visibility)

    def test_group_remember_is_disabled_by_default_for_admin_too(self) -> None:
        decision = can_remember_in_scope(
            _ctx("group"), _Config(), is_group_admin=True
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("group_remember_disabled", decision.code)

    def test_group_admin_with_setting_enabled_may_write_group_public(self) -> None:
        event = SimpleNamespace(is_admin=lambda: True)
        decision = can_remember_in_scope(_ctx("group"), _group_config(True), event=event)

        self.assertTrue(decision.allowed)
        self.assertEqual("group_admin_remember_allowed", decision.code)
        self.assertEqual("group_public", decision.visibility)
        self.assertEqual("normal", decision.durability)

    def test_group_admin_can_also_be_detected_from_role_attribute(self) -> None:
        decision = can_remember_in_scope(
            _ctx("group"), _group_config(True), event=SimpleNamespace(role="admin")
        )

        self.assertTrue(decision.allowed)

    def test_unknown_scope_is_refused_instead_of_guessed(self) -> None:
        decision = can_remember_in_scope(_ctx("unknown"), _group_config(True))

        self.assertFalse(decision.allowed)
        self.assertEqual("remember_scope_unsupported", decision.code)

    def test_private_scope_without_user_id_is_refused(self) -> None:
        decision = can_remember_in_scope(_ctx("private", user_id=""), _Config())

        self.assertFalse(decision.allowed)
        self.assertEqual("user_required", decision.code)

    def test_decision_as_dict_is_plain_and_serializable(self) -> None:
        decision = ScopeWriteDecision(True, "ok", "fine", visibility="private_pair")

        self.assertEqual(
            {
                "allowed": True,
                "code": "ok",
                "reason": "fine",
                "visibility": "private_pair",
                "durability": "normal",
            },
            decision.as_dict(),
        )


class GroupAdminResolverTests(unittest.TestCase):
    def test_none_event_is_not_admin(self) -> None:
        self.assertFalse(resolve_group_admin(None))

    def test_plain_member_is_not_admin(self) -> None:
        self.assertFalse(resolve_group_admin(SimpleNamespace(is_admin=lambda: False)))

    def test_admin_method_exception_is_treated_as_member(self) -> None:
        def boom() -> bool:
            raise RuntimeError("adapter bug")

        self.assertFalse(resolve_group_admin(SimpleNamespace(is_admin=boom)))

    def test_group_owner_role_is_admin(self) -> None:
        self.assertTrue(resolve_group_admin(SimpleNamespace(role="owner")))

    def test_owner_role_wins_even_when_adapter_reports_is_admin_false(self) -> None:
        event = SimpleNamespace(is_admin=lambda: False, role="owner")

        self.assertTrue(resolve_group_admin(event))


class PersonWeightGuardTests(unittest.TestCase):
    """H6：分量只能按用户本人的明确纠正改，模型不能单方面改写。"""

    def test_model_cannot_change_private_weight_without_user_request(self) -> None:
        decision = can_change_person_weight(
            _ctx("private"), _Config(), action="set", target_weight=90
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("person_weight_requires_user_request", decision.code)

    def test_private_user_explicit_correction_allows_set(self) -> None:
        decision = can_change_person_weight(
            _ctx("private", "我们没那么熟，别叫这么亲"),
            _Config(),
            action="set",
            target_weight=20,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual("person_weight_set_allowed", decision.code)

    def test_private_user_explicit_request_allows_reset(self) -> None:
        decision = can_change_person_weight(
            _ctx("private", "把分量重置一下吧"), _Config(), action="reset"
        )

        self.assertTrue(decision.allowed)
        self.assertEqual("person_weight_reset_allowed", decision.code)

    def test_private_reset_without_user_request_is_refused(self) -> None:
        decision = can_change_person_weight(_ctx("private"), _Config(), action="reset")

        self.assertFalse(decision.allowed)
        self.assertEqual("person_weight_requires_user_request", decision.code)

    def test_normal_chat_does_not_authorize_a_weight_change(self) -> None:
        text = "今天天气不错，我们去吃饭吧"

        self.assertFalse(message_requests_weight_change(text))
        decision = can_change_person_weight(
            _ctx("private", text), _Config(), action="set", target_weight=90
        )
        self.assertFalse(decision.allowed)

    def test_group_cannot_raise_weight_even_with_user_request(self) -> None:
        decision = can_change_person_weight(
            _ctx("group", "把我当重要的人吧"),
            _Config(),
            action="set",
            target_weight=100,
            current_weight=20,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("person_weight_raise_requires_private", decision.code)

    def test_group_cannot_reset_weight_even_with_user_request(self) -> None:
        decision = can_change_person_weight(
            _ctx("group", "把分量重置一下"), _Config(), action="reset"
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("person_weight_reset_requires_private", decision.code)

    def test_group_lower_without_user_request_is_refused(self) -> None:
        decision = can_change_person_weight(
            _ctx("group"),
            _Config(),
            action="set",
            target_weight=20,
            current_weight=80,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("person_weight_requires_user_request", decision.code)

    def test_group_lower_with_user_request_is_allowed(self) -> None:
        decision = can_change_person_weight(
            _ctx("group", "我们没那么熟，往回收一收"),
            _Config(),
            action="set",
            target_weight=20,
            current_weight=80,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual("person_weight_group_lower_allowed", decision.code)

    def test_weight_read_is_always_allowed_when_enabled(self) -> None:
        decision = can_change_person_weight(_ctx("group"), _Config(), action="get")

        self.assertTrue(decision.allowed)
        self.assertEqual("person_weight_read_allowed", decision.code)

    def test_weight_feature_can_be_disabled(self) -> None:
        config = _Config({"persona_memory": {"weight_enabled": False}})
        decision = can_change_person_weight(
            _ctx("private", "我们没那么熟"), config, action="set", target_weight=20
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("person_weight_disabled", decision.code)

    def test_missing_or_out_of_range_weight_is_refused(self) -> None:
        config = _Config()
        missing = can_change_person_weight(
            _ctx("private", "我们没那么熟"), config, action="set", target_weight=None
        )
        too_high = can_change_person_weight(
            _ctx("private", "我们没那么熟"), config, action="set", target_weight=120
        )
        not_a_number = can_change_person_weight(
            _ctx("private", "我们没那么熟"), config, action="set", target_weight="abc"
        )

        self.assertEqual("weight_required", missing.code)
        self.assertEqual("invalid_weight", too_high.code)
        self.assertEqual("invalid_weight", not_a_number.code)

    def test_caller_confirmed_request_bypasses_text_inference(self) -> None:
        decision = can_change_person_weight(
            _ctx("private"),
            _Config(),
            action="set",
            target_weight=20,
            user_request_confirmed=True,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual("person_weight_set_allowed", decision.code)

    def test_unknown_action_is_refused(self) -> None:
        decision = can_change_person_weight(
            _ctx("private", "我们没那么熟"), _Config(), action="explode"
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("unknown_action", decision.code)


if __name__ == "__main__":
    unittest.main()
