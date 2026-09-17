from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore


class _PoisonedConnection:
    """Any SQL access through the main connection fails the test loudly."""

    def __getattr__(self, name: str):
        raise AssertionError(f"ACL hot path touched SQL through the main connection: {name}")


class _PoisonedLock:
    """Any acquisition of the store write lock fails the test loudly."""

    def __enter__(self):
        raise AssertionError("ACL hot path took the store write lock")

    def __exit__(self, *_exc):
        return False

    def acquire(self, *_args, **_kwargs):
        raise AssertionError("ACL hot path took the store write lock")

    def release(self):
        return None


class AclProjectionContractTests(unittest.IsolatedAsyncioTestCase):
    """Guards the ACL projection contract of 解决方案输出.md §3.4.3 方案 A / §9.3.

    Two properties must not regress silently:

    1. ``get_scope_feature_override_sync`` keeps its name and ``(scope,
       window_id)`` signature.  ``core/service.py`` resolves it through
       ``getattr(..., None)`` inside a bare ``except`` that falls back to the
       global config, so a rename or a signature change degrades every window
       override to "只读 config" *without raising anything*.
    2. The hot path is a pure in-process dict read.  Callers are synchronous
       functions running on the event loop thread, so any SQL I/O or lock
       acquisition there reintroduces Issue #32.
    """

    def make_service(self, scope_control: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={
                "retrieval": {"mode": "basic"},
                "scope_control": scope_control or {},
            },
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def group_context(group_id: str) -> SessionContext:
        return SessionContext(
            session_id=f"qq:GroupMessage:{group_id}",
            scope="group",
            platform="qq",
            user_id="u1",
            group_id=group_id,
            bot_id="b1",
            message_text="remember this",
        )

    def test_override_getter_keeps_its_documented_name_and_signature(self) -> None:
        """A rename here would silently disable every per-window override."""
        getter = getattr(MemoryStore, "get_scope_feature_override_sync", None)
        self.assertTrue(callable(getter), "get_scope_feature_override_sync must stay callable")

        parameters = list(inspect.signature(getter).parameters)
        self.assertEqual(["self", "scope", "window_id"], parameters)

    async def test_service_resolves_the_override_getter_by_name(self) -> None:
        """The dynamic lookup must still reach the real method through the store."""
        service = self.make_service({"group_capture_enabled": True})
        seen: list[tuple[str, str]] = []
        original = service.store.get_scope_feature_override_sync

        def _recording_getter(scope: str, window_id: str) -> dict[str, bool | None]:
            seen.append((scope, window_id))
            return {"capture_enabled": False, "recall_enabled": False}

        service.store.get_scope_feature_override_sync = _recording_getter
        try:
            self.assertFalse(service._scope_feature_enabled(self.group_context("g1"), "capture"))
        finally:
            service.store.get_scope_feature_override_sync = original
        self.assertEqual([("group", "g1")], seen)

    async def test_hot_path_reads_the_projection_without_io_or_write_lock(self) -> None:
        """The projection must already hold the committed policy, with no fallback I/O."""
        service = self.make_service({"group_capture_enabled": True})
        await service.store.upsert_acl_policy(
            window_scope="group",
            window_id="g1",
            capture_enabled=False,
            recall_enabled=True,
        )

        real_conn = service.store._conn
        real_lock = service.store._lock
        service.store._conn = _PoisonedConnection()
        service.store._lock = _PoisonedLock()
        try:
            override = service.store.get_scope_feature_override_sync("group", "g1")
        finally:
            service.store._conn = real_conn
            service.store._lock = real_lock

        self.assertEqual({"capture_enabled": False, "recall_enabled": True}, override)

    async def test_unknown_window_reports_no_override_rather_than_failing(self) -> None:
        """A window without a stored policy must read as "no override" without I/O."""
        service = self.make_service({"group_capture_enabled": True})

        real_conn = service.store._conn
        service.store._conn = _PoisonedConnection()
        try:
            override = service.store.get_scope_feature_override_sync("group", "g-unknown")
        finally:
            service.store._conn = real_conn

        self.assertEqual({"capture_enabled": None, "recall_enabled": None}, override)


if __name__ == "__main__":
    unittest.main()
