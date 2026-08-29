from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

bootstrap_package()

from astrbot_plugin_memory_companion.core.bridge import MemoryCompanionBridge
from astrbot_plugin_memory_companion.core.classifier import MemoryClassifier
from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.importance import ImportanceEvaluator
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy
from astrbot_plugin_memory_companion.core.models import SessionContext


class _HealthProducer:
    pass


class _CompanionProducer:
    pass


class ExternalMemoryBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp_dir.name) / "memory.db")
        self.store.initialize()
        self.config_data = {
            "private_companion_bridge": {
                "accept_external_records": True,
                "external_memory_producer_allowlist": "health_app",
            }
        }
        self.producer = _HealthProducer()
        self.stars = [
            SimpleNamespace(
                star_cls=self.producer,
                star_cls_type=type(self.producer),
                root_dir_name="health_app",
                name="HealthApp",
                activated=True,
            )
        ]
        self.service = object.__new__(MemoryCompanionService)
        self.service.config = ConfigView(self.config_data)
        self.service.context = SimpleNamespace(get_all_stars=lambda: self.stars)
        self.service.store = self.store
        self.service.classifier = MemoryClassifier()
        self.service.importance = ImportanceEvaluator()
        self.service._schedule_memory_embedding = lambda *args, **kwargs: None
        self.bridge = MemoryCompanionBridge(self.service)
        self.capability = self.bridge.register_external_memory_producer(self.producer)
        self.assertIsNotNone(self.capability)

    def producer_context(self, user_id: str):
        context = self.bridge.create_external_memory_context(
            self.capability,
            user_id=user_id,
        )
        self.assertIsNotNone(context)
        return context

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    async def test_external_memory_is_bound_to_user_private_scope_and_recallable(self) -> None:
        result = await self.bridge.record_external_memory(
            user_id="user-42",
            producer_context=self.producer_context("user-42"),
            content="用户开始每周慢跑三次，通常在晚饭后进行。",
            source_plugin="spoofed_source",
            idempotency_key="week-2026-08-25",
            payload={"activity": "running", "frequency": 3},
            metadata={
                "source_plugin": "spoofed_source",
                "scope": "group",
                "session_id": "group:attacker",
                "server_id": "server-attacker",
                "group_id": "group-attacker",
                "visibility": "public",
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual("stored", result["state"])
        record = await self.store.get_memory(result["memory_id"])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("private", record.scope)
        self.assertEqual("private_pair", record.visibility)
        self.assertEqual("user-42", record.subject.id)
        self.assertEqual("health_app", record.source_plugin)
        self.assertEqual("external:health_app:user-42", record.session_id)
        self.assertEqual("health_app", record.metadata["producer_id"])
        self.assertEqual("health_app", record.metadata["source_plugin"])
        self.assertEqual("private", record.metadata["scope"])
        self.assertEqual("external:health_app:user-42", record.metadata["session_id"])
        self.assertEqual("private_pair", record.metadata["visibility"])
        self.assertNotIn("server_id", record.metadata)
        self.assertNotIn("group_id", record.metadata)
        visible, reason = VisibilityPolicy().is_visible(
            record,
            SessionContext(scope="private", platform="qq", user_id="user-42", session_id="qq:private:user-42"),
        )
        self.assertTrue(visible, reason)

    async def test_idempotency_key_updates_one_record_instead_of_creating_duplicates(self) -> None:
        first = await self.bridge.record_external_memory(
            user_id="user-7",
            producer_context=self.producer_context("user-7"),
            content="用户偏好无糖茶。",
            source_plugin="spoofed_profile_app",
            idempotency_key="preference:tea",
        )
        second = await self.bridge.record_external_memory(
            user_id="user-7",
            producer_context=self.producer_context("user-7"),
            content="用户偏好无糖绿茶。",
            source_plugin="another_spoof",
            idempotency_key="preference:tea",
        )

        self.assertEqual(first["memory_id"], second["memory_id"])
        self.assertTrue(second["deduplicated"])
        stored = await self.store.get_memory(first["memory_id"])
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual("用户偏好无糖绿茶。", stored.content)
        self.assertEqual("health_app", stored.source_plugin)

    async def test_legacy_unauthenticated_and_cross_user_writes_are_rejected(self) -> None:
        unauthenticated = await self.bridge.record_external_memory(
            user_id="user-1",
            content="没有生产者能力",
            source_plugin="health_app",
        )
        self.assertFalse(unauthenticated["ok"])
        self.assertEqual("producer_capability_required", unauthenticated["error_code"])
        direct_bypass = await self.service.record_external_memory(
            user_id="user-1",
            content="绕过 Bridge 也不应写入",
            source_plugin="health_app",
        )
        self.assertEqual("producer_capability_required", direct_bypass["error_code"])

        mismatch = await self.bridge.record_external_memory(
            user_id="user-2",
            producer_context=self.producer_context("user-1"),
            content="试图跨用户写入",
        )
        self.assertFalse(mismatch["ok"])
        self.assertEqual("producer_context_mismatch", mismatch["error_code"])

    async def test_capability_direct_call_requires_and_binds_explicit_user(self) -> None:
        missing_user = await self.bridge.record_external_memory(
            producer_capability=self.capability,
            content="没有显式用户",
        )
        self.assertEqual("producer_capability_required", missing_user["error_code"])

        stored = await self.bridge.record_external_memory(
            producer_capability=self.capability,
            user_id="user-direct",
            content="由能力在同一调用中绑定用户。",
        )
        self.assertTrue(stored["ok"])
        record = await self.store.get_memory(stored["memory_id"])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("user-direct", record.subject.id)
        self.assertEqual("external:health_app:user-direct", record.session_id)

    async def test_caller_memory_id_is_namespaced_by_producer_and_user(self) -> None:
        first = await self.bridge.record_external_memory(
            producer_context=self.producer_context("user-a"),
            content="A 用户记忆",
            memory_id="shared-caller-id",
        )
        second = await self.bridge.record_external_memory(
            producer_context=self.producer_context("user-b"),
            content="B 用户记忆",
            memory_id="shared-caller-id",
        )
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertNotEqual(first["memory_id"], second["memory_id"])

    async def test_disabled_write_is_structured_after_authorization(self) -> None:
        self.config_data["private_companion_bridge"]["accept_external_records"] = False
        disabled = await self.bridge.record_external_memory(
            producer_context=self.producer_context("user-1"),
            content="不应写入",
        )
        self.assertFalse(disabled["ok"])
        self.assertEqual("external_records_disabled", disabled["error_code"])

    def test_registration_requires_exact_active_instance_and_allowlist(self) -> None:
        self.config_data["private_companion_bridge"]["external_memory_producer_allowlist"] = ""
        denied_bridge = MemoryCompanionBridge(self.service)
        self.assertIsNone(denied_bridge.register_external_memory_producer(self.producer))

        self.config_data["private_companion_bridge"]["external_memory_producer_allowlist"] = "health_app"
        impostor = _HealthProducer()
        self.assertIsNone(denied_bridge.register_external_memory_producer(impostor))
        self.stars[0].activated = False
        self.assertIsNone(denied_bridge.register_external_memory_producer(self.producer))
        self.stars[0].activated = True

        capability = denied_bridge.register_external_memory_producer(self.producer)
        self.assertIsNotNone(capability)
        context = denied_bridge.create_external_memory_context(capability, user_id="user-1")
        self.assertIsNotNone(context)
        with self.assertRaises(TypeError):
            json.dumps(capability)
        with self.assertRaises(TypeError):
            json.dumps(context)

    def test_private_companion_is_implicitly_allowed_by_strict_metadata(self) -> None:
        companion = _CompanionProducer()
        self.stars[:] = [
            SimpleNamespace(
                star_cls=companion,
                star_cls_type=type(companion),
                root_dir_name="astrbot_plugin_private_companion",
                name="PrivateCompanion",
                activated=True,
            )
        ]
        self.config_data["private_companion_bridge"]["external_memory_producer_allowlist"] = ""
        bridge = MemoryCompanionBridge(self.service)
        capability = bridge.register_external_memory_producer(companion)
        self.assertIsNotNone(capability)

    async def test_deactivate_and_hot_reload_revoke_old_authority(self) -> None:
        old_context = self.producer_context("user-1")
        self.bridge.deactivate()
        revoked = await self.bridge.record_external_memory(
            producer_context=old_context,
            content="旧能力不应写入",
        )
        self.assertEqual("producer_capability_required", revoked["error_code"])

        reloaded_bridge = MemoryCompanionBridge(self.service)
        stale_bridge_context = await reloaded_bridge.record_external_memory(
            producer_context=old_context,
            content="旧 bridge 上下文不应复活",
        )
        self.assertEqual("producer_capability_required", stale_bridge_context["error_code"])

        capability = reloaded_bridge.register_external_memory_producer(self.producer)
        self.assertIsNotNone(capability)
        replacement = _HealthProducer()
        self.stars[0].star_cls = replacement
        self.stars[0].star_cls_type = type(replacement)
        stale_instance = await reloaded_bridge.record_external_memory(
            producer_capability=capability,
            user_id="user-1",
            content="热重载旧实例不应写入",
        )
        self.assertEqual("producer_capability_required", stale_instance["error_code"])
        self.assertIsNotNone(reloaded_bridge.register_external_memory_producer(replacement))

    def test_capability_contract_advertises_external_memory_method(self) -> None:
        snapshot = self.bridge.probe_capability_snapshot()
        self.assertIn("record_external_memory", snapshot["methods"])
        self.assertIn("register_external_memory_producer", snapshot["methods"])
        self.assertIn("create_external_memory_context", snapshot["methods"])
