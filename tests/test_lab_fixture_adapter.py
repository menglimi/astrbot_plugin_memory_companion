from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()
LAB_FIXTURE_CONTRACT = (
    ROOT.parent.parent / "astrbot-test-lab" / "src" / "astrbot_test_lab" / "fixture_contract.py"
)


def _load_current_lab_fixture_contract():
    if not LAB_FIXTURE_CONTRACT.is_file():
        raise unittest.SkipTest("adjacent astrbot-test-lab fixture contract is unavailable")
    spec = importlib.util.spec_from_file_location(
        "memory_lab_fixture_contract_v2",
        LAB_FIXTURE_CONTRACT,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load the adjacent fixture contract")
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    return contract

from astrbot_plugin_memory_companion import lab_fixture_adapter as fixture_module
from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.lab_fixture_adapter import (
    MemoryLabFixtureAdapter,
    PLUGIN_ID,
    SCHEMA,
    register_memory_lab_fixture_adapter,
)


def _scope(
    umo: str = "lab:FriendMessage:actor-a",
    actor_id: str = "actor-a",
) -> dict[str, str]:
    return {"effective_umo": umo, "effective_actor_id": actor_id}


def _record(
    record_key: str,
    record_kind: str,
    marker: str,
    *terms: str,
) -> dict[str, object]:
    return {
        "record_key": record_key,
        "record_kind": record_kind,
        "marker": marker,
        "match_terms": list(terms or ("LAB_TRIGGER_ALL",)),
    }


def _payload(*records: dict[str, object]) -> dict[str, object]:
    return {"records": list(records)}


def _private_context(
    *,
    actor_id: str = "actor-a",
    umo: str = "lab:FriendMessage:actor-a",
    message_text: str = "请回忆 LAB_TRIGGER_ALL 对应的内容",
) -> SessionContext:
    return SessionContext(
        session_id=umo,
        scope="private",
        platform="qq",
        user_id=actor_id,
        user_name="LAB 用户",
        bot_id="bot-a",
        message_id="lab-message-a",
        message_text=message_text,
    )


def _group_context(
    *,
    actor_id: str = "actor-a",
    umo: str = "lab:GroupMessage:group-a",
    message_text: str = "请回忆 LAB_TRIGGER_GROUP 对应的内容",
) -> SessionContext:
    return SessionContext(
        session_id=umo,
        scope="group",
        platform="qq",
        user_id=actor_id,
        user_name="LAB 群成员",
        group_id="group-a",
        group_name="LAB 测试群",
        bot_id="bot-a",
        message_id="lab-group-message-a",
        message_text=message_text,
    )


class MemoryFixtureAdapterUnitTests(unittest.TestCase):
    def test_fixture_is_exactly_scoped_sanitized_and_released(self) -> None:
        adapter = MemoryLabFixtureAdapter()
        self.assertEqual((SCHEMA,), adapter.fixture_schemas)
        self.assertEqual(
            ("final_projection", "residual_projection"),
            adapter.fixture_capabilities,
        )
        adapter.prepare_fixture(
            "run-a",
            SCHEMA,
            _scope(),
            _payload(
                _record(
                    "private-a",
                    "private_memory",
                    "LAB_PRIVATE_ALPHA",
                    "LAB_TRIGGER_ALL",
                )
            ),
            object(),
        )

        candidates = adapter.candidates_for_context(
            _private_context(), "请回忆 LAB_TRIGGER_ALL"
        )
        self.assertEqual(1, len(candidates))
        self.assertIs(candidates[0].metadata.get("lab_fixture"), True)
        self.assertIn("LAB_PRIVATE_ALPHA", candidates[0].content)
        self.assertEqual(
            [],
            adapter.candidates_for_context(
                _private_context(actor_id="actor-b"), "LAB_TRIGGER_ALL"
            ),
        )

        projection = adapter.describe_applied_fixture("run-a")
        projection_text = json.dumps(projection, ensure_ascii=False, sort_keys=True)
        self.assertLess(len(projection_text.encode("utf-8")), 4096)
        self.assertNotIn("actor-a", projection_text)
        self.assertNotIn("lab:FriendMessage", projection_text)
        self.assertNotIn("LAB_PRIVATE_ALPHA", projection_text)
        self.assertEqual(
            {
                "active": True,
                "residual_count": 1,
                "residual_status": "present",
            },
            adapter.describe_released_fixture("run-a"),
        )

        adapter.release_fixture("run-a")
        adapter.release_fixture("run-a")
        self.assertEqual(
            {
                "active": False,
                "residual_count": 0,
                "residual_status": "clear",
            },
            adapter.describe_released_fixture("run-a"),
        )
        self.assertEqual(
            [], adapter.candidates_for_context(_private_context(), "LAB_TRIGGER_ALL")
        )
        with self.assertRaises(KeyError):
            adapter.describe_applied_fixture("run-a")

    def test_invalid_inputs_and_serialized_capability_fail_before_mutation(self) -> None:
        adapter = MemoryLabFixtureAdapter()
        valid_payload = _payload(
            _record("private-a", "private_memory", "LAB_PRIVATE_ALPHA")
        )
        with self.assertRaises(PermissionError):
            adapter.prepare_fixture("run-a", SCHEMA, _scope(), valid_payload, {"fake": True})
        with self.assertRaisesRegex(ValueError, "LAB_"):
            adapter.prepare_fixture(
                "run-a",
                SCHEMA,
                _scope(),
                _payload(_record("private-a", "private_memory", "production-data")),
                object(),
            )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            adapter.prepare_fixture(
                "run-a",
                SCHEMA,
                _scope(),
                {**valid_payload, "database": "not-allowed"},
                object(),
            )
        with self.assertRaisesRegex(ValueError, "8 KiB"):
            adapter.prepare_fixture(
                "run-a",
                SCHEMA,
                _scope(),
                _payload(
                    _record(
                        "private-a",
                        "private_memory",
                        f"LAB_{'A' * 9000}",
                    )
                ),
                object(),
            )
        with self.assertRaisesRegex(ValueError, "must be strings"):
            adapter.prepare_fixture(
                "run-a",
                SCHEMA,
                {"effective_umo": 123, "effective_actor_id": "actor-a"},
                valid_payload,
                object(),
            )
        with self.assertRaises(KeyError):
            adapter.describe_applied_fixture("run-a")

    def test_runs_are_isolated_and_same_scope_is_rejected(self) -> None:
        adapter = MemoryLabFixtureAdapter()
        payload = _payload(
            _record("private-a", "private_memory", "LAB_PRIVATE_ALPHA")
        )
        adapter.prepare_fixture("run-a", SCHEMA, _scope(), payload, object())
        adapter.prepare_fixture(
            "run-b",
            SCHEMA,
            _scope("lab:FriendMessage:actor-b", "actor-b"),
            _payload(_record("private-b", "private_memory", "LAB_PRIVATE_BETA")),
            object(),
        )
        with self.assertRaisesRegex(RuntimeError, "already active"):
            adapter.prepare_fixture("run-c", SCHEMA, _scope(), payload, object())
        self.assertIn(
            "LAB_PRIVATE_BETA",
            adapter.candidates_for_context(
                _private_context(actor_id="actor-b", umo="lab:FriendMessage:actor-b"),
                "LAB_TRIGGER_ALL",
            )[0].content,
        )

    def test_registration_is_optional_and_capability_is_not_retained(self) -> None:
        capability = object()
        registrations: dict[str, tuple[object, object]] = {}

        def register(plugin_id, adapter, registered_capability):
            self.assertIs(capability, registered_capability)
            registrations[plugin_id] = (adapter, registered_capability)

        fake_module = SimpleNamespace(
            establish_fixture_capability=lambda: capability,
            fixture_capability_is_valid=lambda candidate: candidate is capability,
            register_fixture_adapter=register,
        )
        with patch.object(fixture_module.importlib, "import_module", return_value=fake_module):
            adapter = register_memory_lab_fixture_adapter(object())

        self.assertIs(adapter, registrations[PLUGIN_ID][0])
        self.assertTrue(
            all(value is not capability for value in adapter.__dict__.values())
        )

        missing = ModuleNotFoundError("missing Lab fixture gate")
        missing.name = "astrbot_test_lab_fixture"
        with patch.object(fixture_module.importlib, "import_module", side_effect=missing):
            self.assertIsNone(register_memory_lab_fixture_adapter(object()))

    def test_registration_rejects_invalid_or_legacy_gate_and_closes_on_failure(
        self,
    ) -> None:
        capability = object()
        register_called = False

        def should_not_register(*_args):
            nonlocal register_called
            register_called = True

        invalid_gate = SimpleNamespace(
            establish_fixture_capability=lambda: capability,
            fixture_capability_is_valid=lambda _candidate: False,
            register_fixture_adapter=should_not_register,
        )
        with patch.object(
            fixture_module.importlib,
            "import_module",
            return_value=invalid_gate,
        ):
            with self.assertRaisesRegex(
                PermissionError,
                "invalid Test Lab fixture capability",
            ):
                register_memory_lab_fixture_adapter(object())
        self.assertFalse(register_called)

        legacy_gate = SimpleNamespace(
            establish_fixture_capability=lambda: capability,
            fixture_capability_is_valid=lambda candidate: candidate is capability,
            register_fixture_adapter=lambda _plugin_id, _adapter: None,
        )
        with patch.object(
            fixture_module.importlib,
            "import_module",
            return_value=legacy_gate,
        ):
            with self.assertRaises(TypeError):
                register_memory_lab_fixture_adapter(object())

        captured: dict[str, MemoryLabFixtureAdapter] = {}

        def failing_register(_plugin_id, adapter, _capability):
            captured["adapter"] = adapter
            raise RuntimeError("synthetic registration failure")

        failing_gate = SimpleNamespace(
            establish_fixture_capability=lambda: capability,
            fixture_capability_is_valid=lambda candidate: candidate is capability,
            register_fixture_adapter=failing_register,
        )
        with patch.object(
            fixture_module.importlib,
            "import_module",
            return_value=failing_gate,
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic registration failure"):
                register_memory_lab_fixture_adapter(object())
        self.assertTrue(captured["adapter"]._closed)
        self.assertEqual(
            {
                "active": False,
                "residual_count": 0,
                "residual_status": "clear",
            },
            captured["adapter"].describe_released_fixture("run-never-applied"),
        )

    def test_current_lab_fixture_v2_contract_is_compatible(self) -> None:
        contract = _load_current_lab_fixture_contract()
        self.assertEqual(2, contract.FIXTURE_CONTRACT_VERSION)
        with patch.object(
            fixture_module.importlib,
            "import_module",
            side_effect=lambda name: (
                contract if name == "astrbot_test_lab_fixture" else None
            ),
        ):
            adapter = register_memory_lab_fixture_adapter()

        self.assertIsNotNone(adapter)
        capability = contract.establish_fixture_capability()
        self.assertTrue(contract.fixture_capability_is_valid(capability))
        self.assertTrue(
            all(value is not capability for value in adapter.__dict__.values())
        )
        self.assertEqual(
            (
                {
                    "plugin_id": PLUGIN_ID,
                    "contract_version": 2,
                    "schemas": [SCHEMA],
                    "capabilities": ["final_projection", "residual_projection"],
                    "final_projection": True,
                    "residual_projection": True,
                    "release_idempotent": True,
                },
            ),
            contract.registered_fixture_adapters(capability),
        )
        with self.assertRaisesRegex(
            PermissionError,
            "invalid Test Lab fixture capability",
        ):
            contract.register_fixture_adapter("memory-forged", adapter, object())

        applied = contract.prepare_registered_fixture(
            PLUGIN_ID,
            "run-contract-v2",
            SCHEMA,
            _scope(),
            _payload(_record("private-a", "private_memory", "LAB_PRIVATE_ALPHA")),
            capability,
        )
        self.assertIs(applied["active"], True)
        self.assertEqual(SCHEMA, applied["schema"])
        final = contract.describe_registered_fixture(
            PLUGIN_ID,
            "run-contract-v2",
            capability,
            phase="final",
        )
        self.assertEqual(1, final["records"]["count"])
        self.assertIs(
            contract.release_registered_fixture(
                PLUGIN_ID,
                "run-contract-v2",
                capability,
            ),
            True,
        )
        self.assertEqual(
            {
                "active": False,
                "residual_count": 0,
                "residual_status": "clear",
            },
            contract.describe_registered_fixture(
                PLUGIN_ID,
                "run-contract-v2",
                capability,
                phase="residual",
            ),
        )


class MemoryFixtureProductionPathTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={
                "retrieval": {"mode": "basic", "embedding_enabled": False},
                "visibility": {"enable_acl_rules": True},
                "memory_injection": {
                    "enable_injection_logs": True,
                    "max_chars": 3200,
                },
                "injection_cache_ttl_seconds": 120,
            },
            plugin_root=Path(ROOT),
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    async def test_private_recall_profile_isolation_cache_and_release(self) -> None:
        service = self.make_service()
        adapter = MemoryLabFixtureAdapter(service)
        service.lab_fixture_adapter = adapter
        adapter.prepare_fixture(
            "run-private",
            SCHEMA,
            _scope(),
            _payload(
                _record("private", "private_memory", "LAB_PRIVATE_ALPHA"),
                _record("foreign", "foreign_private_memory", "LAB_FOREIGN_ALPHA"),
                _record("group", "group_memory", "LAB_GROUP_ALPHA"),
                _record("profile", "profile", "LAB_PROFILE_ALPHA"),
            ),
            object(),
        )
        ctx = _private_context()

        results, blocked, slots = await service.search_context_slots(
            "LAB_TRIGGER_ALL", ctx, top_k=8
        )
        visible_kinds = {
            item.memory.tags[-1]
            for item in results
            if item.memory.tags and adapter.is_fixture_memory_id(item.memory.id)
        }
        self.assertEqual({"private_memory", "profile"}, visible_kinds)
        self.assertEqual({"stable_memory", "user_profile"}, set(slots))
        self.assertEqual(2, len(blocked))
        self.assertTrue(all(not item.get("content") for item in blocked))
        for item in results:
            self.assertIsNone(await service.store.get_memory(item.memory.id))

        cached_results, _, _ = await service.search_context_slots(
            "LAB_TRIGGER_ALL", ctx, top_k=8
        )
        self.assertEqual(
            [item.memory.id for item in results],
            [item.memory.id for item in cached_results],
        )
        projection = adapter.describe_applied_fixture("run-private")
        self.assertGreaterEqual(projection["cache"]["hits"], 1)
        self.assertGreaterEqual(projection["observations"]["blocked_count"], 4)

        logs_before = await service.store.recent_injection_logs(
            limit=20, scope=ctx.scope, session_id=ctx.session_id
        )
        self.assertEqual([], logs_before)
        service._injection_cache[ctx.session_id] = (
            time.monotonic(),
            "CACHED_PRODUCTION_MARKER",
            ctx.scope,
        )
        service.store.mark_injected = AsyncMock()
        req = SimpleNamespace(
            prompt="",
            system_prompt="",
            contexts=[],
            extra_user_content_parts=[],
        )

        await service.inject_memories(ctx, req)

        rendered_request = "\n".join(
            [
                str(req.prompt),
                str(req.system_prompt),
                str(req.extra_user_content_parts),
            ]
        )
        self.assertIn("LAB_PRIVATE_ALPHA", rendered_request)
        self.assertNotIn("CACHED_PRODUCTION_MARKER", rendered_request)
        service.store.mark_injected.assert_not_awaited()
        self.assertEqual(
            "CACHED_PRODUCTION_MARKER",
            service._injection_cache[ctx.session_id][1],
        )
        self.assertEqual(
            [],
            await service.store.recent_injection_logs(
                limit=20, scope=ctx.scope, session_id=ctx.session_id
            ),
        )

        adapter.release_fixture("run-private")
        after_release, after_blocked, after_slots = await service.search_context_slots(
            "LAB_TRIGGER_ALL", ctx, top_k=8
        )
        self.assertEqual(([], [], {}), (after_release, after_blocked, after_slots))

    async def test_group_fixture_uses_production_acl_rules(self) -> None:
        service = self.make_service()
        adapter = MemoryLabFixtureAdapter(service)
        service.lab_fixture_adapter = adapter
        adapter.prepare_fixture(
            "run-group",
            SCHEMA,
            _scope("lab:GroupMessage:group-a", "actor-a"),
            _payload(
                _record(
                    "group",
                    "group_memory",
                    "LAB_GROUP_ALPHA",
                    "LAB_TRIGGER_GROUP",
                ),
                _record(
                    "private",
                    "private_memory",
                    "LAB_PRIVATE_ALPHA",
                    "LAB_TRIGGER_GROUP",
                ),
            ),
            object(),
        )
        ctx = _group_context()

        default_results, default_blocked, _ = await service.search_context_slots(
            "LAB_TRIGGER_GROUP", ctx, top_k=8
        )
        self.assertEqual(
            ["group_memory"],
            [item.memory.tags[-1] for item in default_results],
        )
        self.assertEqual(1, len(default_blocked))
        self.assertIn("private", default_blocked[0]["reason"])

        await service.store.upsert_acl_rule(
            owner_scope="private",
            owner_id="actor-a",
            reader_scope="group",
            reader_id="group-a",
            effect="allow",
        )
        service._retrieval_result_cache.clear()
        allowed_results, allowed_blocked, _ = await service.search_context_slots(
            "LAB_TRIGGER_GROUP", ctx, top_k=8
        )
        self.assertEqual(
            {"group_memory", "private_memory"},
            {item.memory.tags[-1] for item in allowed_results},
        )
        self.assertEqual([], allowed_blocked)

        other_actor_results, _, _ = await service.search_context_slots(
            "LAB_TRIGGER_GROUP",
            _group_context(actor_id="actor-b"),
            top_k=8,
        )
        self.assertEqual([], other_actor_results)


if __name__ == "__main__":
    unittest.main()
