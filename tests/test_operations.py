from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.operations import (
    PORTABLE_FORMAT,
    PRESETS,
    PortableMemoryArchive,
    apply_preset,
    detect_preset,
    persist_runtime_config,
    scan_plugin_conflicts,
)
from astrbot_plugin_memory_companion.core.store import MemoryStore


class OperationPresetTests(unittest.TestCase):
    def test_preset_preserves_provider_selection(self) -> None:
        raw = {
            "retrieval": {
                "mode": "rerank",
                "embedding_provider_id": "embed-1",
                "rerank_provider_id": "rerank-1",
            },
            "memory_summary": {"provider_id": "summary-1"},
        }

        result = apply_preset(raw, "light")

        self.assertEqual("light", result["preset"])
        self.assertEqual("basic", raw["retrieval"]["mode"])
        self.assertFalse(raw["retrieval"]["embedding_enabled"])
        self.assertEqual("embed-1", raw["retrieval"]["embedding_provider_id"])
        self.assertEqual("rerank-1", raw["retrieval"]["rerank_provider_id"])
        self.assertEqual("summary-1", raw["memory_summary"]["provider_id"])
        self.assertEqual("light", detect_preset(ConfigView(raw)))

    def test_standard_preset_defaults_to_fewer_complete_memories(self) -> None:
        schema = json.loads((Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text(encoding="utf-8"))
        injection = schema["memory_injection"]["items"]
        self.assertEqual(8, injection["top_k"]["default"])
        self.assertEqual(4000, injection["max_chars"]["default"])
        self.assertEqual(240, injection["max_item_chars"]["default"])
        self.assertEqual(4, PRESETS["standard"]["memory_injection.top_k"])
        self.assertEqual(1800, PRESETS["standard"]["memory_injection.max_chars"])
        self.assertEqual(240, PRESETS["standard"]["memory_injection.max_item_chars"])
        self.assertEqual(5, schema["memory_summary"]["items"]["max_retries"]["default"])
        self.assertEqual(24, schema["memory_summary"]["items"]["max_calls_per_session_hour"]["default"])
        self.assertEqual(0, schema["memory_summary"]["items"]["max_calls_per_session_hour"]["min"])
        self.assertEqual(300, schema["memory_summary"]["items"]["provider_timeout_seconds"]["default"])

    def test_summary_recovery_controls_have_expected_schema_types_and_defaults(self) -> None:
        schema = json.loads((Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text(encoding="utf-8"))
        items = schema["memory_summary"]["items"]
        expected = {
            "recovery_enabled": ("bool", True),
            "recovery_startup_delay_seconds": ("int", 60),
            "recovery_poll_interval_seconds": ("int", 60),
            "recovery_sessions_per_round": ("int", 1),
            "recovery_identity_retry_seconds": ("int", 3600),
            "recovery_disabled_retry_seconds": ("int", 3600),
        }

        expected_bounds = {
            "recovery_startup_delay_seconds": (0, 3600, 10),
            "recovery_poll_interval_seconds": (5, 3600, 5),
            "recovery_sessions_per_round": (1, 32, 1),
            "recovery_identity_retry_seconds": (60, 604800, 60),
            "recovery_disabled_retry_seconds": (60, 604800, 60),
        }

        for key, (expected_type, expected_default) in expected.items():
            with self.subTest(key=key):
                self.assertEqual(expected_type, items[key]["type"])
                self.assertEqual(expected_default, items[key]["default"])
                self.assertTrue(items[key]["description"])
                self.assertTrue(items[key]["hint"])
                if key in expected_bounds:
                    lo, hi, step = expected_bounds[key]
                    self.assertEqual(lo, items[key]["min"])
                    self.assertEqual(hi, items[key]["max"])
                    self.assertEqual({"min": lo, "max": hi, "step": step}, items[key]["slider"])

    def test_persist_runtime_config_is_utf8_and_atomic_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp) / "plugin_data" / "astrbot_plugin_memory_companion"
            data_dir.mkdir(parents=True)
            path = persist_runtime_config({"备注": "中文配置"}, data_dir)

            self.assertEqual("astrbot_plugin_memory_companion_config.json", path.name)
            self.assertIn("中文配置", path.read_text(encoding="utf-8"))


class PluginConflictTests(unittest.TestCase):
    def test_scan_distinguishes_conflict_and_coordinated_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plugins = Path(temp) / "plugins"
            root = plugins / "astrbot_plugin_memory_companion"
            root.mkdir(parents=True)
            (plugins / "astrbot_plugin_livingmemory").mkdir()
            (plugins / "astrbot_plugin_private_companion").mkdir()

            result = scan_plugin_conflicts(root)

            levels = {item["plugin_dir"]: item["level"] for item in result}
            self.assertEqual("high", levels["astrbot_plugin_livingmemory"])
            self.assertEqual("coordinated", levels["astrbot_plugin_private_companion"])


class PortableArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_utf8_round_trip_preserves_boundaries_and_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = MemoryStore(base / "source.db")
            target = MemoryStore(base / "target.db")
            source.initialize()
            target.initialize()
            try:
                memory = MemoryRecord(
                    id="mem_utf8",
                    memory_type="user_preference",
                    subject=EntityRef(kind="user", id="u1", name="小明"),
                    object=EntityRef(kind="bot", id="b1", name="助手"),
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    platform="qq",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    content="用户喜欢蓝风铃，并要求仅限私聊使用。",
                    tags=["偏好", "隐私"],
                    metadata={"language": "中文"},
                )
                await source.insert_memory(memory)
                await source.upsert_identity(
                    platform="qq",
                    entity=memory.subject,
                    aliases=["明明"],
                    profile={"timezone": "Asia/Shanghai"},
                )
                await source.upsert_relationship(
                    subject=memory.subject,
                    object=memory.object,
                    relation_type="trusts",
                    scope="private",
                    session_id=memory.session_id,
                    visibility="private_pair",
                    evidence="用户明确授权私聊记忆。",
                    source_memory_id=memory.id,
                )
                timeline_id = await source.add_timeline_event(
                    event_type="user_message",
                    session_id=memory.session_id,
                    scope="private",
                    subject_id="u1",
                    object_id="b1",
                    content="请记住蓝风铃。",
                    metadata={"message_id": "msg-1"},
                )
                await source.mark_timeline_summarized([timeline_id])
                await source.upsert_acl_rule(
                    owner_scope="private",
                    owner_id="u1",
                    reader_scope="private",
                    reader_id="u1",
                    effect="allow",
                )
                await source.upsert_acl_policy(
                    window_scope="private",
                    window_id="u1",
                    read_mode="whitelist",
                    share_mode="whitelist",
                )

                exported = await PortableMemoryArchive(source, base / "source-data").export()
                self.assertEqual(PORTABLE_FORMAT, exported["format"])
                self.assertIn("蓝风铃", Path(exported["path"]).read_text(encoding="utf-8"))

                archive = PortableMemoryArchive(target, base / "target-data")
                preview = archive.preview(exported["path"])
                self.assertTrue(preview["valid"])
                self.assertEqual(1, preview["counts"]["memory"])

                result = await archive.import_data(exported["path"])
                self.assertEqual(1, result["imported"]["memory"])
                restored = await target.get_memory("mem_utf8")
                self.assertIsNotNone(restored)
                self.assertEqual("private_pair", restored.visibility)
                self.assertEqual("用户喜欢蓝风铃，并要求仅限私聊使用。", restored.content)
                self.assertEqual(["偏好", "隐私"], restored.tags)
                self.assertEqual(1, len(await target.list_relationships(limit=10)))
                self.assertEqual(1, len(await target.list_acl_rules()))
                self.assertEqual(1, len(await target.list_acl_policies()))
                restored_timeline = await target.recent_timeline(limit=10)
                self.assertEqual(1, len(restored_timeline))
                self.assertTrue(restored_timeline[0]["summarized_at"])
                self.assertTrue(Path(result["backup"]).exists())
            finally:
                source.close()
                target.close()

    async def test_invalid_archive_is_rejected_before_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            store = MemoryStore(base / "memory.db")
            store.initialize()
            try:
                invalid = base / "invalid.jsonl"
                invalid.write_text('{"record_type":"header","format":"other","version":1}\n', encoding="utf-8")

                archive = PortableMemoryArchive(store, base / "data")
                with self.assertRaises(ValueError):
                    await archive.import_data(str(invalid))
            finally:
                store.close()

    async def test_qq_chat_exporter_json_is_directed_to_historical_chat_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            store = MemoryStore(base / "memory.db")
            store.initialize()
            try:
                exported_chat = base / "qq-export.json"
                exported_chat.write_text('{"metadata":{"name":"QQChatExporter"},"messages":[]}', encoding="utf-8")

                archive = PortableMemoryArchive(store, base / "data")
                with self.assertRaisesRegex(ValueError, "历史聊天导入"):
                    archive.preview(str(exported_chat))
            finally:
                store.close()

    async def test_portable_jsonl_keeps_working_when_file_uses_json_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            archive_path = base / "renamed.json"
            archive_path.write_text(
                '{"record_type":"header","format":"astrbot-memory-jsonl","version":1}\n',
                encoding="utf-8",
            )

            header, records = PortableMemoryArchive._read(str(archive_path))

        self.assertEqual(PORTABLE_FORMAT, header["format"])
        self.assertEqual([], records)

    async def test_truncated_portable_archive_is_rejected_by_declared_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "truncated.jsonl"
            archive_path.write_text(
                '{"record_type":"header","format":"astrbot-memory-jsonl","version":1,'
                '"counts":{"memory":2,"timeline":1}}\n',
                encoding="utf-8",
            )

            archive = PortableMemoryArchive(object(), Path(temp) / "data")
            with self.assertRaisesRegex(ValueError, "record count mismatch"):
                archive.preview(str(archive_path))


if __name__ == "__main__":
    unittest.main()
