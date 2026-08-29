from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore


class PrimaryStoreStartupSafetyTests(unittest.TestCase):
    def make_dir(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Path(temp.name)

    @staticmethod
    def make_service(data_dir: Path, config: dict | None = None) -> MemoryCompanionService:
        return MemoryCompanionService(
            context=None,
            config=config or {},
            plugin_root=ROOT,
            data_dir=data_dir,
        )

    def test_first_install_creates_database_and_identity_marker(self) -> None:
        data_dir = self.make_dir()

        service = self.make_service(data_dir)
        service.close()

        marker_path = data_dir / ".memory-store-identity.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertTrue((data_dir / "memory_companion.db").is_file())
        self.assertRegex(marker["installation_id"], r"^[0-9a-f]{32}$")
        with sqlite3.connect(data_dir / "memory_companion.db") as connection:
            stored = connection.execute(
                "SELECT value FROM schema_metadata WHERE key='installation_id'"
            ).fetchone()[0]
        self.assertEqual(marker["installation_id"], stored)

    def test_missing_database_with_existing_marker_fails_closed(self) -> None:
        data_dir = self.make_dir()
        service = self.make_service(data_dir)
        service.close()
        db_path = data_dir / "memory_companion.db"
        db_path.unlink()

        with self.assertRaisesRegex(RuntimeError, "主库缺失"):
            self.make_service(data_dir)

        self.assertFalse(db_path.exists())

    def test_existing_empty_sqlite_file_is_not_adopted(self) -> None:
        data_dir = self.make_dir()
        db_path = data_dir / "memory_companion.db"
        db_path.touch()

        with self.assertRaisesRegex(RuntimeError, "no application schema"):
            self.make_service(data_dir)

        with sqlite3.connect(db_path) as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        self.assertEqual(tables, [])

    def test_unrelated_sqlite_schema_is_not_adopted_as_memory_store(self) -> None:
        data_dir = self.make_dir()
        db_path = data_dir / "memory_companion.db"
        with sqlite3.connect(db_path) as connection:
            connection.execute("CREATE TABLE unrelated_state(id INTEGER PRIMARY KEY)")

        with self.assertRaisesRegex(RuntimeError, "no recognized application schema"):
            self.make_service(data_dir)

        with sqlite3.connect(db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertEqual(tables, {"unrelated_state"})

    def test_missing_database_with_other_plugin_state_fails_closed(self) -> None:
        data_dir = self.make_dir()
        (data_dir / "req041_scoped.db").touch()

        with self.assertRaisesRegex(RuntimeError, "既有记忆数据痕迹"):
            self.make_service(data_dir)

        self.assertFalse((data_dir / "memory_companion.db").exists())

    def test_legacy_database_without_marker_is_adopted_once(self) -> None:
        data_dir = self.make_dir()
        store = MemoryStore(data_dir / "memory_companion.db")
        store.initialize()
        store.close()

        service = self.make_service(data_dir)
        self.assertTrue(service.primary_store_status["adopted_legacy_store"])
        service.close()

        self.assertTrue((data_dir / ".memory-store-identity.json").is_file())

    def test_marker_database_identity_mismatch_fails_closed(self) -> None:
        data_dir = self.make_dir()
        service = self.make_service(data_dir)
        service.close()
        marker_path = data_dir / ".memory-store-identity.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["installation_id"] = "0" * 32
        marker_path.write_text(json.dumps(marker), encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.make_service(data_dir)

    def test_corrupt_identity_marker_fails_closed_without_touching_database(self) -> None:
        data_dir = self.make_dir()
        service = self.make_service(data_dir)
        service.close()
        db_path = data_dir / "memory_companion.db"
        before = db_path.read_bytes()
        (data_dir / ".memory-store-identity.json").write_text(
            "{broken",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RuntimeError, "身份标记损坏"):
            self.make_service(data_dir)

        self.assertEqual(db_path.read_bytes(), before)

    def test_memory_store_can_explicitly_refuse_creation(self) -> None:
        data_dir = self.make_dir()
        with self.assertRaises(FileNotFoundError):
            MemoryStore(data_dir / "missing.db", allow_create=False)


class SummaryTimeoutDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def make_dir(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Path(temp.name)

    async def test_default_timeout_is_recommended_value(self) -> None:
        service = PrimaryStoreStartupSafetyTests.make_service(self.make_dir())
        self.addCleanup(service.close)

        status = service.summary_timeout_status()

        self.assertEqual(status["configured_seconds"], 180)
        self.assertFalse(status["below_recommendation"])

    async def test_explicit_short_timeout_is_respected_and_reported(self) -> None:
        with patch(
            "astrbot_plugin_memory_companion.core.service.logger.warning"
        ) as warning:
            service = PrimaryStoreStartupSafetyTests.make_service(
                self.make_dir(),
                {"memory_summary": {"provider_timeout_seconds": 60}},
            )
        self.addCleanup(service.close)

        status = service.summary_timeout_status()
        report = await service.operational_report()

        self.assertEqual(service.summarizer.provider_timeout_seconds, 60)
        self.assertEqual(status["configured_seconds"], 60)
        self.assertTrue(status["below_recommendation"])
        self.assertTrue(status["timeout_preserves_pending_timeline"])
        self.assertEqual(report["summary_timeout"], status)
        self.assertTrue(any("180 秒" in item for item in report["warnings"]))
        self.assertTrue(
            any("低于建议值 180 秒" in str(call.args[0]) for call in warning.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
