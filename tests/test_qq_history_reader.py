from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core.chat_import import HistoricalChatImporter
from astrbot_plugin_remember_you.core.qq_history import QQHistoryReader
from astrbot_plugin_remember_you.core.store import MemoryStore


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=LOCAL_TZ).timestamp())


class FakeConfig:
    VALUES = {
        "historical_chat_import.qq_page_size": 2,
        "historical_chat_import.qq_max_pages": 10,
        "historical_chat_import.qq_request_timeout_seconds": 5,
    }

    def int(self, key: str, default: int) -> int:
        return int(self.VALUES.get(key, default))


class FakeMeta:
    id = "default"
    name = "aiocqhttp"


class FakeBot:
    def __init__(self, *, without_sequences: bool = False) -> None:
        self.without_sequences = without_sequences

    async def call_action(self, action: str, **kwargs):
        if action == "get_login_info":
            return {"status": "ok", "retcode": 0, "data": {"user_id": 12345, "nickname": "星缘"}}
        if action == "get_version_info":
            return {"app_name": "NapCat.Onebot", "app_version": "4.8.0"}
        if action == "get_stranger_info":
            return {"user_id": 23456, "nickname": "珝环"}
        if action != "get_friend_msg_history":
            raise RuntimeError(f"unexpected action: {action}")
        if self.without_sequences:
            rows = [
                self._message("m2", 0, "2026-07-15T10:20:00", 23456, "第二条"),
                self._message("m1", 0, "2026-07-15T10:10:00", 12345, "第一条"),
            ]
            return {"messages": rows}
        cursor = int(kwargs.get("message_seq") or 0)
        pages = {
            0: [
                self._message("m4", 4, "2026-07-15T12:00:00", 12345, "范围外"),
                self._message("m3", 3, "2026-07-15T11:00:00", 23456, "吃过饭了"),
            ],
            3: [
                self._message("m3", 3, "2026-07-15T11:00:00", 23456, "吃过饭了"),
                self._message(
                    "m2",
                    2,
                    "2026-07-15T10:30:00",
                    12345,
                    [{"type": "text", "data": {"text": "看这个"}}, {"type": "image", "data": {"file": "a.jpg"}}],
                ),
            ],
            2: [self._message("m1", 1, "2026-07-15T09:30:00", 23456, "更早消息")],
        }
        return {"status": "ok", "retcode": 0, "data": {"messages": pages.get(cursor, [])}}

    @staticmethod
    def _message(message_id, sequence, local_time, sender_id, message):
        return {
            "message_id": message_id,
            "message_seq": sequence,
            "time": timestamp(local_time),
            "self_id": 12345,
            "user_id": 23456,
            "sender": {"user_id": sender_id, "nickname": "星缘" if sender_id == 12345 else "珝环"},
            "message": message if isinstance(message, list) else [{"type": "text", "data": {"text": message}}],
        }


class FakePlatform:
    def __init__(self, bot: FakeBot) -> None:
        self.bot = bot

    def meta(self):
        return FakeMeta()


def service_for(bot: FakeBot):
    manager = SimpleNamespace(platform_insts=[FakePlatform(bot)])
    return SimpleNamespace(context=SimpleNamespace(platform_manager=manager), config=FakeConfig())


class QQHistoryReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_capabilities_reports_connected_bot_and_limits(self) -> None:
        result = await QQHistoryReader(service_for(FakeBot())).capabilities()

        self.assertTrue(result["available"])
        self.assertEqual("12345", result["adapters"][0]["bot_id"])
        self.assertEqual("NapCat.Onebot", result["adapters"][0]["implementation"])
        self.assertEqual(2, result["limits"]["page_size"])

    async def test_read_paginates_deduplicates_filters_and_normalizes(self) -> None:
        result = await QQHistoryReader(service_for(FakeBot())).read(
            platform_id="default",
            user_id="23456",
            start_at="2026-07-15T10:00",
            end_at="2026-07-15T11:30",
        )

        self.assertEqual(2, result["stats"]["message_count"])
        self.assertEqual(["m2", "m3"], [item["source_message_id"] for item in result["messages"]])
        self.assertIn("[图片]", result["messages"][0]["content"])
        self.assertEqual(3, result["read_stats"]["pages"])
        self.assertEqual(1, result["read_stats"]["duplicates_removed"])
        self.assertTrue(result["read_stats"]["complete"])
        self.assertFalse(result["truncated"])
        roles = {item["speaker"]: item["suggested_role"] for item in result["speaker_suggestions"]}
        self.assertEqual("user", roles["珝环"])
        self.assertEqual("bot", roles["星缘"])

    async def test_missing_page_sequence_is_reported_as_truncated(self) -> None:
        result = await QQHistoryReader(service_for(FakeBot(without_sequences=True))).read(
            platform_id="default",
            user_id="23456",
            start_at="2026-07-15T10:00",
            end_at="2026-07-15T11:30",
        )

        self.assertTrue(result["truncated"])
        self.assertFalse(result["read_stats"]["complete"])
        self.assertTrue(any("消息序号" in warning for warning in result["warnings"]))

    async def test_range_and_qq_are_strictly_bounded(self) -> None:
        reader = QQHistoryReader(service_for(FakeBot()))
        with self.assertRaisesRegex(ValueError, "纯数字"):
            await reader.read(
                platform_id="default",
                user_id="abc",
                start_at="2026-07-15T10:00",
                end_at="2026-07-15T11:30",
            )
        with self.assertRaisesRegex(ValueError, "31 天"):
            await reader.read(
                platform_id="default",
                user_id="23456",
                start_at="2026-05-01T10:00",
                end_at="2026-07-15T11:30",
            )


class StructuredQQStagingTests(unittest.TestCase):
    def test_structured_staging_preserves_onebot_source_fields(self) -> None:
        read_result = {
            "source_name": "QQ 23456",
            "source_hash": "a" * 64,
            "source_kind": "qq_history",
            "messages": [
                {
                    "sequence": 1,
                    "speaker": "珝环",
                    "raw_time": "2026-07-15 10:00:00",
                    "local_time": "2026-07-15T10:00:00+08:00",
                    "occurred_at": "2026-07-15T02:00:00+00:00",
                    "inferred_year": False,
                    "source_line": 1,
                    "content": "你好",
                    "message_id": "qqhist_internal",
                    "source_message_id": "onebot-1",
                    "source_message_seq": 88,
                    "source_platform_id": "default",
                    "source_kind": "qq_history",
                    "source_sender_id": "23456",
                }
            ],
            "stats": {
                "speakers": {"珝环": 1},
                "message_count": 1,
                "speaker_count": 1,
                "first_at": "2026-07-15T10:00:00+08:00",
                "last_at": "2026-07-15T10:00:00+08:00",
                "dialogue_chars": 2,
            },
            "source_metadata": {"platform_id": "default", "user_id": "23456"},
            "identity_context": {"available": True, "target_users": [{"user_id": "23456", "name": "珝环"}]},
            "speaker_suggestions": [
                {
                    "speaker": "珝环",
                    "message_count": 1,
                    "suggested_role": "user",
                    "confidence": "high",
                    "reasons": ["账号对应"],
                    "relationship_candidates": [{"user_id": "23456", "name": "珝环"}],
                }
            ],
            "read_stats": {"pages": 1, "selected_messages": 1, "complete": True},
            "truncated": False,
            "warnings": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            importer = HistoricalChatImporter(SimpleNamespace(data_dir=Path(temp), store=object()))
            manifest = importer.stage_structured_messages(**read_result)
            parsed_path = Path(temp) / "historical_chat_imports" / "uploads" / manifest["upload_id"] / "parsed.jsonl"
            parsed = json.loads(parsed_path.read_text(encoding="utf-8").strip())

        self.assertEqual("qq_history", manifest["source_kind"])
        self.assertEqual("onebot-1", parsed["source_message_id"])
        self.assertEqual(88, parsed["source_message_seq"])
        self.assertEqual("default", parsed["source_platform_id"])


class StructuredQQImportMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeline_keeps_original_onebot_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            store.initialize()

            class Service:
                def __init__(self):
                    self.data_dir = Path(temp)
                    self.store = store

                @staticmethod
                def _spawn_background(coro, *, label):
                    coro.close()
                    return None

            importer = HistoricalChatImporter(Service())
            messages = [
                {
                    "sequence": 1,
                    "speaker": "珝环",
                    "raw_time": "2026-07-15 10:00:00",
                    "local_time": "2026-07-15T10:00:00+08:00",
                    "occurred_at": "2026-07-15T02:00:00+00:00",
                    "inferred_year": False,
                    "source_line": 1,
                    "content": "你好",
                    "message_id": "qqhist_user",
                    "source_message_id": "onebot-user",
                    "source_message_seq": 88,
                    "source_platform_id": "default",
                    "source_kind": "qq_history",
                    "source_sender_id": "23456",
                },
                {
                    "sequence": 2,
                    "speaker": "星缘",
                    "raw_time": "2026-07-15 10:00:05",
                    "local_time": "2026-07-15T10:00:05+08:00",
                    "occurred_at": "2026-07-15T02:00:05+00:00",
                    "inferred_year": False,
                    "source_line": 2,
                    "content": "你好呀",
                    "message_id": "qqhist_bot",
                    "source_message_id": "onebot-bot",
                    "source_message_seq": 89,
                    "source_platform_id": "default",
                    "source_kind": "qq_history",
                    "source_sender_id": "12345",
                },
            ]
            preview = importer.stage_structured_messages(
                source_name="QQ 23456",
                source_hash="b" * 64,
                source_kind="qq_history",
                messages=messages,
                stats={
                    "speakers": {"珝环": 1, "星缘": 1},
                    "message_count": 2,
                    "speaker_count": 2,
                    "first_at": messages[0]["local_time"],
                    "last_at": messages[1]["local_time"],
                    "dialogue_chars": 5,
                },
                source_metadata={"platform_id": "default", "user_id": "23456", "bot_id": "12345"},
                identity_context={"available": True},
                speaker_suggestions=[
                    {"speaker": "珝环", "message_count": 1, "suggested_role": "user", "confidence": "high"},
                    {"speaker": "星缘", "message_count": 1, "suggested_role": "bot", "confidence": "high"},
                ],
            )
            started = await importer.start_import(
                {
                    "upload_id": preview["upload_id"],
                    "speaker_map": {
                        "珝环": {"role": "user", "entity_id": "23456", "display_name": "珝环"},
                        "星缘": {"role": "bot", "entity_id": "12345", "display_name": "星缘"},
                    },
                    "platform": "qq",
                    "user_id": "23456",
                    "user_name": "珝环",
                    "bot_id": "12345",
                    "bot_name": "星缘",
                }
            )
            rows = store._conn.execute(
                "SELECT metadata FROM timeline WHERE import_batch_id=? ORDER BY source_sequence",
                (started["batch"]["id"],),
            ).fetchall()
            metadata = [json.loads(row["metadata"]) for row in rows]
            store.close()

        self.assertEqual(["onebot-user", "onebot-bot"], [item["source_message_id"] for item in metadata])
        self.assertEqual([88, 89], [item["source_message_seq"] for item in metadata])
        self.assertTrue(all(item["source_kind"] == "qq_history" for item in metadata))
        self.assertTrue(all(item["source_platform_id"] == "default" for item in metadata))


if __name__ == "__main__":
    unittest.main()
