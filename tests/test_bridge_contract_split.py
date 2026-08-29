from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest

from core import bridge, bridge_contract
from core.models import EntityRef, MemoryRecord


ROOT = Path(__file__).resolve().parents[1]


def relationship_projection(**updates) -> dict:
    value = {
        "schema_version": "chat.relationship_projection.v1",
        "authority": "private_companion.relationship_score",
        "read_only": True,
        "score": 620,
        "phase_key": "close",
        "phase_label": "亲近",
        "tone": "温暖、自然",
        "address_level": "使用已确认昵称",
        "proactive_care_limit": 2,
        "soft_behaviors": {
            "allow_playful_jokes": True,
            "allow_followup": True,
            "allow_memory_mention": True,
            "allow_daily_care": True,
        },
    }
    value.update(updates)
    return value


def expression_decision(**updates) -> dict:
    value = {
        "contract": "companion_interaction_expression.v2",
        "expression_band": "warm",
        "allowed_behaviors": ["reply", "support", "followup"],
        "safety_mode": "normal",
        "blocker": None,
        "reason_codes": ["interaction_band_applied"],
        "followup": True,
        "pacing": "steady",
        "directness": "natural",
        "validation_style": "support_first",
        "self_disclosure": "light",
        "humor_mode": "light",
        "topic_initiative": "followup",
    }
    value.update(updates)
    return value


def real_bridge() -> tuple[bridge.MemoryCompanionBridge, object]:
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
    instance = bridge.MemoryCompanionBridge(plugin)
    capability = instance.register_emotion_producer(companion)
    assert capability is not None
    return instance, capability


class BridgeContractCompatibilityTests(unittest.TestCase):
    def test_bridge_reexports_preserve_objects_and_signature_snapshot(self) -> None:
        reexports = (
            "_AuthenticatedCompanionProjection",
            "sanitize_companion_relationship_projection",
            "sanitize_companion_expression_decision",
            "_local_time_label",
            "serialize_memory",
        )
        for name in reexports:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bridge_contract, name),
                    getattr(bridge, name),
                )

        expected_signatures = {
            "_AuthenticatedCompanionProjection": (
                "(payload: 'dict[str, Any]', *, kind: 'str', bot_id: 'str', "
                "platform: 'str', person_id: 'str', scope: 'str', "
                "session_id: 'str', signature: 'str') -> 'None'"
            ),
            "sanitize_companion_relationship_projection": (
                "(value: 'Any') -> 'dict[str, Any]'"
            ),
            "sanitize_companion_expression_decision": (
                "(value: 'Any') -> 'dict[str, Any]'"
            ),
            "consume_authenticated_companion_projection": (
                "(value: 'Any', *, kind: 'str', expected_person_id: 'str' = '', "
                "expected_scope: 'str' = '', expected_session_id: 'str' = '', "
                "expected_platform: 'str' = '', expected_bot_id: 'str' = '') "
                "-> 'dict[str, Any]'"
            ),
            "_local_time_label": "(value: 'Any') -> 'str'",
            "serialize_memory": (
                "(record: 'MemoryRecord', score: 'float | None' = None, "
                "reason: 'str' = '') -> 'dict[str, Any]'"
            ),
        }
        for name, expected in expected_signatures.items():
            with self.subTest(name=name):
                self.assertEqual(expected, str(inspect.signature(getattr(bridge, name))))

    def test_sanitizers_keep_accepted_and_invalid_semantics(self) -> None:
        relationship = bridge.sanitize_companion_relationship_projection(
            relationship_projection(owner_secret="must-not-escape")
        )
        self.assertEqual("accepted", relationship["status"])
        self.assertEqual("close", relationship["projection"]["phase_key"])
        self.assertNotIn("owner_secret", relationship["projection"])
        self.assertEqual(
            "invalid",
            bridge.sanitize_companion_relationship_projection(
                relationship_projection(score=1201)
            )["status"],
        )

        expression = bridge.sanitize_companion_expression_decision(
            expression_decision(owner_secret="must-not-escape")
        )
        self.assertEqual("accepted", expression["status"])
        self.assertEqual("light", expression["decision"]["humor_mode"])
        self.assertNotIn("owner_secret", expression["decision"])
        self.assertEqual(
            "invalid",
            bridge.sanitize_companion_expression_decision(
                expression_decision(humor_mode="disable_safety")
            )["status"],
        )

    def test_real_bridge_seal_consumes_and_rejects_tamper_or_wrong_domain(self) -> None:
        instance, capability = real_bridge()
        issued = instance.consume_relationship_projection(
            relationship_projection(),
            producer_capability=capability,
            bot_id="bot-1",
            platform="qq",
            user_id="u1",
            scope="private",
            session_id="qq:FriendMessage:u1",
        )
        self.assertEqual("accepted", issued["status"])
        sealed = issued["projection"]
        self.assertIs(type(sealed), bridge._AuthenticatedCompanionProjection)

        accepted = bridge.consume_authenticated_companion_projection(
            sealed,
            kind="relationship",
            expected_person_id="u1",
            expected_scope="private",
            expected_session_id="qq:FriendMessage:u1",
            expected_platform="qq",
            expected_bot_id="bot-1",
        )
        self.assertEqual("accepted", accepted["status"])
        wrong_domain = bridge.consume_authenticated_companion_projection(
            sealed,
            kind="relationship",
            expected_person_id="other-user",
        )
        self.assertEqual("invalid", wrong_domain["status"])
        self.assertEqual("projection_person_id_mismatch", wrong_domain["error_code"])

        dict.__setitem__(sealed, "score", 621)
        tampered = bridge.consume_authenticated_companion_projection(
            sealed,
            kind="relationship",
        )
        self.assertEqual("invalid", tampered["status"])
        self.assertEqual("projection_signature_invalid", tampered["error_code"])

    def test_explicit_secret_helpers_cannot_forge_runtime_attestation(self) -> None:
        payload = relationship_projection()
        test_secret = b"contract-test-only-secret"
        signature = bridge_contract._canonical_companion_projection_signature(
            payload,
            secret=test_secret,
            kind="relationship",
            bot_id="bot-1",
            platform="qq",
            person_id="u1",
            scope="private",
            session_id="qq:FriendMessage:u1",
        )
        self.assertTrue(
            bridge_contract._verify_companion_projection_signature(
                payload,
                signature,
                secret=test_secret,
                kind="relationship",
                bot_id="bot-1",
                platform="qq",
                person_id="u1",
                scope="private",
                session_id="qq:FriendMessage:u1",
            )
        )
        self.assertFalse(
            bridge_contract._verify_companion_projection_signature(
                payload,
                signature,
                secret=b"different-secret",
                kind="relationship",
                bot_id="bot-1",
                platform="qq",
                person_id="u1",
                scope="private",
                session_id="qq:FriendMessage:u1",
            )
        )
        forged = bridge_contract._AuthenticatedCompanionProjection(
            payload,
            kind="relationship",
            bot_id="bot-1",
            platform="qq",
            person_id="u1",
            scope="private",
            session_id="qq:FriendMessage:u1",
            signature=signature,
        )
        rejected = bridge.consume_authenticated_companion_projection(
            forged,
            kind="relationship",
        )
        self.assertEqual("projection_signature_invalid", rejected["error_code"])

        malformed_signature = bridge_contract._AuthenticatedCompanionProjection(
            payload,
            kind="relationship",
            bot_id="bot-1",
            platform="qq",
            person_id="u1",
            scope="private",
            session_id="qq:FriendMessage:u1",
            signature=b"not-a-text-signature",
        )
        with self.assertRaises(TypeError):
            bridge.consume_authenticated_companion_projection(
                malformed_signature,
                kind="relationship",
            )

        for helper_name in (
            "_canonical_companion_projection_signature",
            "_verify_companion_projection_signature",
        ):
            helper_signature = inspect.signature(getattr(bridge_contract, helper_name))
            secret = helper_signature.parameters["secret"]
            self.assertIs(secret.default, inspect.Parameter.empty)
            self.assertIs(secret.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_serialize_memory_output_remains_compatible(self) -> None:
        record = MemoryRecord(
            id="memory-1",
            memory_type="user_profile",
            subject=EntityRef(kind="user", id="u1", name="小雪", role="user"),
            object=EntityRef(kind="topic", id="flower", name="蓝风铃"),
            scope="private",
            session_id="qq:FriendMessage:u1",
            visibility="private",
            sayability="direct",
            reality_level="real_user_fact",
            content="用户喜欢蓝风铃",
            evidence="用户亲口说明",
            confidence=0.95,
            importance=0.8,
            metadata={
                "persona_id": "persona-main",
                "key_facts": ["喜欢蓝风铃"],
                "access_token": "must-not-escape",
            },
            created_at="2026-08-26T00:00:00+00:00",
            updated_at="2026-08-26T01:00:00+00:00",
            occurred_at="2026-08-26T02:00:00+00:00",
        )
        payload = bridge.serialize_memory(record, 1.25, "semantic_match")
        self.assertEqual("memory-1", payload["id"])
        self.assertEqual("persona-main", payload["persona_id"])
        self.assertEqual(["喜欢蓝风铃"], payload["key_facts"])
        self.assertEqual("2026-08-26 08:00:00", payload["created_at_local"])
        self.assertEqual(1.25, payload["score"])
        self.assertEqual("semantic_match", payload["reason"])
        self.assertNotIn("metadata", payload)
        self.assertNotIn("must-not-escape", str(payload))


class BridgeContractStaticBoundaryTests(unittest.TestCase):
    def test_neutral_module_has_no_runtime_authority_or_live_references(self) -> None:
        source_path = ROOT / "core" / "bridge_contract.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported_modules = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertFalse(
            imported_modules
            & {
                "core.bridge",
                "bridge",
                "core.scoped_store",
                "scoped_store",
                "core.service",
                "service",
            }
        )
        self.assertNotIn("secrets", imported_modules)
        self.assertFalse(hasattr(bridge_contract, "_COMPANION_PROJECTION_SECRET"))
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "secrets"
                and node.func.attr == "token_bytes"
                for node in ast.walk(tree)
            )
        )
        forbidden_live_names = {
            "plugin",
            "store",
            "_bridge",
            "MemoryCompanionBridge",
            "ScopedStore",
        }
        self.assertFalse(
            {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            & forbidden_live_names
        )

    def test_bridge_keeps_secret_and_has_one_canonical_signing_callsite(self) -> None:
        source = (ROOT / "core" / "bridge.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        seal = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_seal_companion_projection"
        )
        all_signing_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_canonical_companion_projection_signature"
        ]
        seal_signing_calls = [
            node
            for node in ast.walk(seal)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_canonical_companion_projection_signature"
        ]
        self.assertEqual(1, len(all_signing_calls))
        self.assertEqual(all_signing_calls, seal_signing_calls)
        self.assertIn("_COMPANION_PROJECTION_SECRET = secrets.token_bytes(32)", source)


if __name__ == "__main__":
    unittest.main()
