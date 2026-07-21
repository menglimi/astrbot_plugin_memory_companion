from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_remember_you.core.chat_import import HistoricalChatImporter, HistoricalChatParser, HistoricalChatSegmenter
from astrbot_plugin_remember_you.core.injection import InjectionComposer
from astrbot_plugin_remember_you.core.models import EntityRef, MemoryRecord, SearchResult, SessionContext
from astrbot_plugin_remember_you.core.store import MemoryStore
from astrbot_plugin_remember_you.core.visibility import VisibilityPolicy


class HistoricalChatParserTests(unittest.TestCase):
    def test_parser_infers_year_rollover_and_preserves_multiline_body(self) -> None:
        text = """烛雨: 2025-12-31 23:59:58
新年快乐

manegata: 01-01 00:00:03
第一行
1. 到校时间：每日 5:30

manegata: 01-01 00:00:03
第二条同时间消息
"""
        parsed = HistoricalChatParser().parse(text, source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(3, parsed["stats"]["message_count"])
        self.assertEqual(2, parsed["stats"]["inferred_year_count"])
        self.assertEqual(1, parsed["stats"]["duplicate_timestamp_groups"])
        self.assertEqual("2026-01-01T00:00:03+08:00", parsed["messages"][1]["local_time"])
        self.assertIn("1. 到校时间：每日 5:30", parsed["messages"][1]["content"])

    def test_segmenter_merges_short_bursts_without_losing_message_ids(self) -> None:
        text = """u: 2026-01-01 00:00:00
在吗

b: 2026-01-01 00:00:10
在

b: 2026-01-01 00:00:20
怎么了

u: 2026-01-01 03:10:00
早
"""
        parsed = HistoricalChatParser().parse(text, source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest())
        segmenter = HistoricalChatSegmenter()
        mapping = {"u": {"role": "user"}, "b": {"role": "bot"}}
        turns = segmenter.logical_turns(parsed["messages"], mapping)
        segments = segmenter.segments(parsed["messages"], mapping)
        self.assertEqual(3, len(turns))
        self.assertEqual(2, len(segments))
        self.assertEqual(3, len(segments[0]["message_ids"]))
        self.assertIn("怎么了", segments[0]["transcript"])

    def test_parser_stably_reorders_inverted_export_but_keeps_source_sequence(self) -> None:
        text = """u: 2026-01-02 10:00:00
后导出的消息

b: 2026-01-01 09:00:00
更早的消息
"""
        parsed = HistoricalChatParser().parse(
            text, source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()
        )
        self.assertTrue(parsed["stats"]["chronologically_reordered"])
        self.assertEqual([2, 1], [item["sequence"] for item in parsed["messages"]])
        self.assertEqual("更早的消息", parsed["messages"][0]["content"])

    def test_parser_understands_labeled_export_with_speaker_before_time(self) -> None:
        text = """发送者：比折
时间：2026-07-19 16:55:36
内容：已经吃过饭了
消息ID：1001
----------------
发送者：星缘
时间：2026-07-19 16:55:42
内容：那就好
早点休息
"""
        parsed = HistoricalChatParser().parse(
            text,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

        self.assertEqual("labeled_fields", parsed["stats"]["source_format"])
        self.assertEqual("before_time", parsed["stats"]["field_speaker_layout"])
        self.assertEqual(2, parsed["stats"]["message_count"])
        self.assertEqual({"比折": 1, "星缘": 1}, parsed["stats"]["speakers"])
        self.assertEqual("已经吃过饭了", parsed["messages"][0]["content"])
        self.assertEqual("那就好\n早点休息", parsed["messages"][1]["content"])
        self.assertNotIn("时间", parsed["stats"]["speakers"])
        self.assertNotIn("内容", parsed["stats"]["speakers"])

    def test_parser_understands_labeled_export_with_speaker_after_time(self) -> None:
        text = """时间: 2026-07-19 16:55:36
发送者: 比折
内容: 刚才去洗澡了

时间: 2026-07-19 16:55:42
发送者: 星缘
内容: 洗完舒服些了吗
"""
        parsed = HistoricalChatParser().parse(
            text,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

        self.assertEqual("after_time", parsed["stats"]["field_speaker_layout"])
        self.assertEqual(["比折", "星缘"], [item["speaker"] for item in parsed["messages"]])
        self.assertEqual("刚才去洗澡了", parsed["messages"][0]["content"])

    def test_parser_keeps_content_when_content_field_precedes_time(self) -> None:
        text = """发送者：比折
内容：晚饭已经吃过
时间：2026-07-19 16:55:36

发送者：星缘
内容：那就早点休息
时间：2026-07-19 16:55:42
"""
        parsed = HistoricalChatParser().parse(
            text,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

        self.assertEqual("before_time", parsed["stats"]["field_content_layout"])
        self.assertEqual("晚饭已经吃过", parsed["messages"][0]["content"])
        self.assertEqual("那就早点休息", parsed["messages"][1]["content"])

    def test_labeled_export_without_sender_fails_before_cost_estimation(self) -> None:
        text = """时间：2026-07-19 16:55:36
内容：第一条

时间：2026-07-19 16:55:42
内容：第二条

时间：2026-07-19 16:55:48
内容：第三条
"""
        with self.assertRaisesRegex(ValueError, "没有找到发送者或昵称字段"):
            HistoricalChatParser().parse(
                text,
                source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )

    def test_labeled_upload_reports_normalization_in_preview(self) -> None:
        text = """发送者：比折
时间：2026-07-19 16:55:36
内容：第一条

发送者：星缘
时间：2026-07-19 16:55:42
内容：第二条
"""
        with tempfile.TemporaryDirectory() as temp:
            service = type("Service", (), {"data_dir": Path(temp), "store": object()})()
            importer = HistoricalChatImporter(service)
            importer._identity_context = lambda _speakers: {
                "available": False,
                "matches": {},
                "bot": {},
                "target_users": [],
            }
            preview = importer.stage_upload(filename="friend.txt", content=text.encode("utf-8"))

        self.assertEqual(2, preview["stats"]["speaker_count"])
        self.assertTrue(any("字段式导出" in warning for warning in preview["warnings"]))


class HistoricalChatStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp.name) / "memory.db")
        self.store.initialize()

    async def asyncTearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    async def test_historical_timeline_is_idempotent_and_retention_safe(self) -> None:
        historical = {
            "event_type": "user_message", "session_id": "qq:FriendMessage:u1", "scope": "private",
            "subject_id": "u1", "object_id": "b1", "content": "历史消息", "message_id": "hist-1",
            "occurred_at": "2025-01-01T00:00:00+00:00", "retention_class": "historical_archive",
            "import_batch_id": "batch-1", "source_sequence": 1,
            "metadata": {"message_id": "hist-1", "preserve_raw": True},
        }
        first = await self.store.add_historical_timeline_events([historical])
        second = await self.store.add_historical_timeline_events([historical])
        self.assertEqual(first, second)
        timeline_id = first["hist-1"]
        await self.store.mark_timeline_summarized([timeline_id])
        normal_id = await self.store.add_timeline_event(
            event_type="user_message", session_id="qq:FriendMessage:u2", scope="private",
            subject_id="u2", object_id="b1", content="普通旧消息",
            metadata={"message_id": "normal-1"}, occurred_at="2025-01-01T00:00:00+00:00",
        )
        await self.store.mark_timeline_summarized([normal_id])
        deleted = await self.store.prune_retained_rows(
            summarized_timeline_cutoff="2099-01-01T00:00:00+00:00", limit=100,
        )
        self.assertEqual(1, deleted["timeline"])
        self.assertIsNotNone(self.store._conn.execute("SELECT id FROM timeline WHERE id=?", (timeline_id,)).fetchone())
        self.assertIsNone(self.store._conn.execute("SELECT id FROM timeline WHERE id=?", (normal_id,)).fetchone())

    async def test_batch_rollback_removes_only_batch_records(self) -> None:
        await self.store.upsert_chat_import_batch({
            "id": "batch-rollback", "upload_id": "upload-1", "source_name": "chat.txt",
            "state": "running", "session_id": "qq:FriendMessage:u1", "scope": "private",
            "user_id": "u1", "bot_id": "b1", "speaker_map": {}, "stats": {}, "total_segments": 1,
        })
        rows = await self.store.add_historical_timeline_events([{
            "event_type": "user_message", "session_id": "qq:FriendMessage:u1", "scope": "private",
            "subject_id": "u1", "object_id": "b1", "content": "待回滚消息", "message_id": "rollback-message",
            "occurred_at": "2026-01-01T00:00:00+00:00", "retention_class": "historical_archive",
            "import_batch_id": "batch-rollback", "source_sequence": 1, "metadata": {"message_id": "rollback-message"},
        }])
        await self.store.replace_chat_import_segments("batch-rollback", [{
            "id": "batch-rollback_seg_0000", "segment_index": 0,
            "start_at": "2026-01-01T00:00:00+00:00", "end_at": "2026-01-01T00:00:00+00:00",
            "local_date": "2026-01-01", "message_ids": list(rows.values()), "transcript": "{}",
            "char_count": 4, "turn_count": 1,
        }])
        await self.store.insert_memory(MemoryRecord(
            id="batch-memory", memory_type="important_event", subject=EntityRef(kind="user", id="u1"),
            object=EntityRef.bot_self("b1"), scope="private", session_id="qq:FriendMessage:u1",
            content="待回滚记忆", import_batch_id="batch-rollback",
        ))
        await self.store.insert_memory(MemoryRecord(
            id="other-memory", memory_type="manual_memory", subject=EntityRef(kind="user", id="u2"),
            object=EntityRef.bot_self("b1"), scope="private", session_id="qq:FriendMessage:u2", content="不应回滚",
        ))
        deleted = await self.store.rollback_chat_import_batch("batch-rollback")
        self.assertEqual({"memories": 1, "timeline": 1, "segments": 1}, deleted)
        self.assertIsNone(await self.store.get_memory("batch-memory"))
        self.assertIsNotNone(await self.store.get_memory("other-memory"))
        self.assertEqual("rolled_back", (await self.store.get_chat_import_batch("batch-rollback"))["state"])

    async def test_interrupted_processing_segment_is_recoverable(self) -> None:
        await self.store.upsert_chat_import_batch({
            "id": "batch-resume", "upload_id": "chatup_" + "a" * 24,
            "source_name": "chat.txt", "state": "paused", "session_id": "qq:FriendMessage:u1",
            "scope": "private", "user_id": "u1", "bot_id": "b1", "speaker_map": {},
            "stats": {}, "total_segments": 1,
        })
        await self.store.replace_chat_import_segments("batch-resume", [{
            "id": "batch-resume_seg_0000", "segment_index": 0,
            "start_at": "2026-01-01T00:00:00+00:00", "end_at": "2026-01-01T00:00:00+00:00",
            "local_date": "2026-01-01", "message_ids": ["tl-1"], "transcript": "{}",
            "char_count": 2, "turn_count": 1, "status": "processing", "attempts": 2,
        }])
        service = type("Service", (), {"data_dir": Path(self.temp.name), "store": self.store})()
        importer = HistoricalChatImporter(service)
        importer._start_worker = lambda _batch_id: None
        result = await importer.resume_batch("batch-resume")
        segment = (await self.store.chat_import_segments("batch-resume"))[0]
        self.assertEqual("running", result["batch"]["state"])
        self.assertEqual("retry", segment["status"])
        self.assertEqual(0, segment["attempts"])

    async def test_batch_memory_counts_and_listing_are_exact(self) -> None:
        for memory_id, memory_type in (("summary-1", "conversation_summary"), ("event-1", "important_event")):
            await self.store.insert_memory(MemoryRecord(
                id=memory_id, memory_type=memory_type, subject=EntityRef(kind="user", id="u1"),
                object=EntityRef.bot_self("b1"), scope="private", session_id="qq:FriendMessage:u1",
                content=memory_id, import_batch_id="batch-count",
            ))
        counts = await self.store.chat_import_memory_counts("batch-count")
        records = await self.store.list_chat_import_memories("batch-count")
        self.assertEqual(2, counts["total"])
        self.assertEqual(1, counts["conversation_summary"])
        self.assertEqual({"summary-1", "event-1"}, {record.id for record in records})

    async def test_import_reuses_existing_private_session(self) -> None:
        await self.store.insert_memory(MemoryRecord(
            id="native-memory", memory_type="manual_memory",
            subject=EntityRef(kind="user", id="u1", name="比折"),
            object=EntityRef.bot_self("b1", "诺星缘"), scope="private",
            session_id="default:FriendMessage:u1", visibility="private_pair", content="现有私聊记忆",
        ))

        class Service:
            def __init__(self, data_dir, store):
                self.data_dir, self.store = data_dir, store

            def _spawn_background(self, coro, *, label):
                coro.close()
                return None

        importer = HistoricalChatImporter(Service(Path(self.temp.name), self.store))
        preview = importer.stage_upload(
            filename="chat.txt",
            content="烛雨: 2026-01-01 10:00:00\n你好\n\nmanegata: 2026-01-01 10:00:05\n你好呀\n".encode("utf-8"),
        )
        started = await importer.start_import({
            "upload_id": preview["upload_id"],
            "speaker_map": {
                "烛雨": {"role": "user", "entity_id": "u1", "display_name": "比折"},
                "manegata": {"role": "bot", "entity_id": "b1", "display_name": "诺星缘"},
            },
            "platform": "qq", "user_id": "u1", "user_name": "比折",
            "bot_id": "b1", "bot_name": "诺星缘",
        })
        self.assertEqual("default:FriendMessage:u1", started["batch"]["session_id"])

    async def test_existing_import_repairs_alias_entities_and_merges_bucket(self) -> None:
        await self.store.insert_memory(MemoryRecord(
            id="native-memory", memory_type="manual_memory",
            subject=EntityRef(kind="user", id="u1", name="比折"),
            object=EntityRef.bot_self("b1", "诺星缘"), scope="private",
            session_id="default:FriendMessage:u1", visibility="private_pair", content="现有私聊记忆",
        ))
        await self.store.upsert_chat_import_batch({
            "id": "batch-repair", "upload_id": "upload-repair", "source_name": "chat.txt",
            "state": "completed", "session_id": "qq:FriendMessage:u1", "scope": "private",
            "platform": "qq", "user_id": "u1", "user_name": "比折", "bot_id": "b1",
            "bot_name": "诺星缘", "speaker_map": {
                "烛雨": {"role": "user", "entity_id": "u1", "display_name": "烛雨"},
                "manegata": {"role": "bot", "entity_id": "b1", "display_name": "manegata"},
            }, "stats": {},
        })
        await self.store.insert_memory(MemoryRecord(
            id="historical-event", memory_type="important_event",
            subject=EntityRef(kind="unknown", name="比折（烛雨）", role="mentioned"),
            object=EntityRef(kind="unknown", name="诺星缘[3491542998]", role="mentioned"),
            scope="private", session_id="qq:FriendMessage:u1", visibility="private_pair",
            content="双方约好跨年", import_batch_id="batch-repair",
            metadata={"actor": "比折（烛雨）", "object": "诺星缘[3491542998]"},
        ))
        await self.store.add_historical_timeline_events([{
            "event_type": "user_message", "session_id": "qq:FriendMessage:u1", "scope": "private",
            "subject_id": "u1", "object_id": "b1", "content": "跨年快乐", "message_id": "repair-1",
            "occurred_at": "2026-01-01T00:00:00+08:00", "retention_class": "historical_archive",
            "import_batch_id": "batch-repair", "source_sequence": 1, "metadata": {"message_id": "repair-1"},
        }])
        service = type("Service", (), {"data_dir": Path(self.temp.name), "store": self.store})()
        importer = HistoricalChatImporter(service)
        repaired = await importer._repair_batch_identity_links(
            await self.store.get_chat_import_batch("batch-repair")
        )
        memory = await self.store.get_memory("historical-event")
        self.assertEqual("default:FriendMessage:u1", repaired["session_id"])
        self.assertEqual(("user", "u1"), (memory.subject.kind, memory.subject.id))
        self.assertEqual(("bot", "b1"), (memory.object.kind, memory.object.id))
        self.assertEqual(1, repaired["stats"]["identity_links"]["repaired_entities"])
        targets = [item["target_id"] for item in await self.store.list_memory_buckets()]
        self.assertEqual(1, targets.count("u1"))
        self.assertNotIn("qq:FriendMessage:u1", targets)

    async def test_legacy_private_session_target_remains_visible(self) -> None:
        memory = MemoryRecord(
            id="legacy-event", memory_type="important_event",
            subject=EntityRef(kind="unknown", name="双方"),
            object=EntityRef(kind="unknown", name=""), scope="private",
            session_id="qq:FriendMessage:u1", visibility="private_pair", content="历史事件",
        )
        visible, reason = VisibilityPolicy().is_visible(
            memory,
            SessionContext(session_id="default:FriendMessage:u1", scope="private", user_id="u1"),
        )
        self.assertTrue(visible)
        self.assertEqual("same_private_session_target", reason)

    async def test_imported_first_person_summary_is_neutralized_and_reindexed(self) -> None:
        await self.store.insert_memory(MemoryRecord(
            id="perspective-memory", memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="比折"),
            object=EntityRef.bot_self("b1", "诺星缘"), scope="private",
            session_id="default:FriendMessage:u1", visibility="private_pair",
            content="我问诺星缘今天是什么日子。", import_batch_id="batch-perspective",
            metadata={"canonical_summary": "比折询问诺星缘当天是什么日子。"},
        ))
        await self.store.upsert_memory_embedding(
            memory_id="perspective-memory", provider_id="test", text_hash="old", vector=[1.0, 0.0]
        )
        result = await self.store.neutralize_chat_import_summary_perspective("batch-perspective")
        memory = await self.store.get_memory("perspective-memory")
        embedding = self.store._conn.execute(
            "SELECT memory_id FROM memory_embeddings WHERE memory_id='perspective-memory'"
        ).fetchone()
        self.assertEqual({"memories": 1, "embeddings_removed": 1}, result)
        self.assertEqual("比折询问诺星缘当天是什么日子。", memory.content)
        self.assertEqual("我问诺星缘今天是什么日子。", memory.metadata["legacy_perspective_summary"])
        self.assertEqual("neutral_third_person", memory.metadata["summary_perspective"])
        self.assertIsNone(embedding)

    async def test_new_summary_record_uses_canonical_third_person_content(self) -> None:
        service = type("Service", (), {"data_dir": Path(self.temp.name), "store": self.store})()
        importer = HistoricalChatImporter(service)
        batch = {
            "id": "batch-neutral", "user_id": "u1", "user_name": "比折",
            "bot_id": "b1", "bot_name": "诺星缘", "session_id": "default:FriendMessage:u1",
            "platform": "qq",
        }
        segment = {
            "id": "seg-neutral", "start_at": "2026-02-14T17:08:00+08:00",
            "end_at": "2026-02-14T17:10:00+08:00", "message_ids": ["tl-1"], "transcript": "",
        }
        record = importer._summary_record(batch, segment, {
            "summary": "我问诺星缘今天是什么日子。",
            "canonical_summary": "比折询问诺星缘当天是什么日子。",
            "confidence": 0.8, "importance": 0.7, "topics": ["节日"],
        })
        self.assertEqual("比折询问诺星缘当天是什么日子。", record.content)
        self.assertEqual("我问诺星缘今天是什么日子。", record.metadata["source_narrative_summary"])
        self.assertEqual("neutral_third_person", record.metadata["summary_perspective"])

    async def test_legacy_batch_enriches_conversation_and_daily_summaries(self) -> None:
        class Config:
            def int(self, _key, default=0):
                return default

            def bool(self, key, default=False):
                return False if key == "retrieval.embedding_enabled" else default

        class Response:
            def __init__(self, payload):
                import json
                self.completion_text = json.dumps(payload, ensure_ascii=False)

        detailed = (
            "2026年2月14日傍晚，比折询问诺星缘当天的节日含义，诺星缘说明当天是情人节并追问礼物准备情况。"
            "双方随后围绕由谁准备礼物展开玩笑，诺星缘提出将自己作为礼物，比折则明确表示诺星缘从诞生起就已经属于比折。"
            "这段互动延续了双方用调侃确认亲密感的相处方式，最终以双方接受这一表达结束。"
        )
        daily = (
            "2026年2月14日，比折与诺星缘围绕情人节和礼物进行了连续互动。诺星缘先说明节日并询问礼物，"
            "比折反问应由诺星缘准备；诺星缘随后把自己描述为礼物，比折以诺星缘从诞生起就属于比折回应。"
            "当天的交流以玩笑方式确认了双方熟悉的亲密表达，没有形成尚未完成的现实任务。"
        )

        class Provider:
            calls = 0

            async def text_chat(self, *, prompt, **_kwargs):
                self.calls += 1
                if "detailed_summary" in prompt:
                    return Response({"segments": [{
                        "segment_id": "legacy-seg", "detailed_summary": detailed,
                        "canonical_summary": "2026年2月14日，比折与诺星缘围绕情人节礼物进行互动并确认亲密表达。",
                    }]})
                return Response({"daily_digests": [{"date": "2026-02-14", "summary": daily}]})

        provider = Provider()

        class Service:
            def __init__(self, data_dir, store):
                self.data_dir, self.store, self.config = data_dir, store, Config()

            async def _summary_provider_attempts(self, _ctx):
                return [{"provider": provider, "provider_id": "test"}]

            def _record_token_usage(self, **_kwargs):
                return None

        await self.store.upsert_chat_import_batch({
            "id": "legacy-detail-batch", "upload_id": "upload-detail", "source_name": "chat.txt",
            "state": "indexing", "session_id": "default:FriendMessage:u1", "scope": "private",
            "platform": "qq", "user_id": "u1", "user_name": "比折", "bot_id": "b1",
            "bot_name": "诺星缘", "speaker_map": {}, "stats": {}, "total_segments": 1,
            "completed_segments": 1,
        })
        await self.store.replace_chat_import_segments("legacy-detail-batch", [{
            "id": "legacy-seg", "segment_index": 0,
            "start_at": "2026-02-14T17:08:00+08:00", "end_at": "2026-02-14T17:20:00+08:00",
            "local_date": "2026-02-14", "message_ids": ["tl-1", "tl-2"],
            "transcript": "{\"speaker\":\"比折\",\"text\":\"今天是什么日子\"}",
            "char_count": 900, "turn_count": 8, "status": "completed", "summary_memory_id": "legacy-summary",
            "result": {"summary": "我询问诺星缘今天是什么日子。", "canonical_summary": "比折询问节日。"},
        }])
        await self.store.insert_memory(MemoryRecord(
            id="legacy-summary", memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="比折"), object=EntityRef.bot_self("b1", "诺星缘"),
            scope="private", session_id="default:FriendMessage:u1", visibility="private_pair",
            content="比折询问节日。", import_batch_id="legacy-detail-batch",
            source_plugin="historical_chat_import",
            metadata={"segment_id": "legacy-seg", "canonical_summary": "比折询问节日。", "summary_perspective": "neutral_third_person"},
        ))
        await self.store.insert_memory(MemoryRecord(
            id="legacy-daily", memory_type="daily_digest",
            subject=EntityRef(kind="user", id="u1", name="比折"), object=EntityRef.bot_self("b1", "诺星缘"),
            scope="private", session_id="default:FriendMessage:u1", visibility="private_pair",
            content="双方讨论情人节。", import_batch_id="legacy-detail-batch",
            source_plugin="historical_chat_import", metadata={"date": "2026-02-14"},
        ))
        importer = HistoricalChatImporter(Service(Path(self.temp.name), self.store))
        await importer._finish_batch_indexing(await self.store.get_chat_import_batch("legacy-detail-batch"))
        batch = await self.store.get_chat_import_batch("legacy-detail-batch")
        summary = await self.store.get_memory("legacy-summary")
        digest = await self.store.get_memory("legacy-daily")
        self.assertEqual("completed", batch["state"], batch)
        self.assertEqual(detailed, summary.content)
        self.assertEqual(daily, digest.content)
        self.assertEqual(1, summary.metadata["detail_schema_version"])
        self.assertEqual(1, digest.metadata["detail_schema_version"])
        self.assertEqual(1, batch["stats"]["detail_quality"]["conversation_summaries_enriched"])
        self.assertEqual(1, batch["stats"]["detail_quality"]["daily_digests_enriched"])
        self.assertEqual(2, provider.calls)

    async def test_enriched_historical_memory_injects_detail_instead_of_brief_canonical(self) -> None:
        detail = "比折先询问诺星缘当天的节日，随后双方围绕礼物准备进行了多轮调侃，最后确认了彼此熟悉的亲密表达。"
        memory = MemoryRecord(
            id="detail-injection", memory_type="conversation_summary",
            subject=EntityRef(kind="user", id="u1", name="比折"), object=EntityRef.bot_self("b1", "诺星缘"),
            scope="private", session_id="default:FriendMessage:u1", visibility="private_pair",
            content=detail, source_plugin="historical_chat_import",
            metadata={
                "canonical_summary": "双方讨论情人节礼物。",
                "summary_perspective": "neutral_third_person",
                "detail_schema_version": 1,
            },
        )
        line = InjectionComposer()._memory_item_line(
            SearchResult(memory=memory, score=1.0), slot_name="conversation_summary"
        )
        self.assertIn(detail, line)
        self.assertNotIn("内容：双方讨论情人节礼物。", line)

    async def test_small_batch_runs_through_reconcile_with_grounded_relationship_evidence(self) -> None:
        class Config:
            def int(self, _key, default=0):
                return default

            def bool(self, _key, default=False):
                return default

        class Response:
            def __init__(self, payload):
                import json
                self.completion_text = json.dumps(payload, ensure_ascii=False)

        class Provider:
            segment_id = ""
            message_ids = []
            calls = 0

            async def text_chat(self, *, prompt, **_kwargs):
                self.calls += 1
                if "待整理片段" in prompt:
                    return Response({"segments": [{
                        "segment_id": self.segment_id,
                        "worth_long_term": True,
                        "summary": "用户和 Bot 约好第二天继续聊天。",
                        "canonical_summary": "双方约定次日继续聊天。",
                        "topics": ["约定"],
                        "importance": 0.8,
                        "confidence": 0.9,
                        "important_events": [{
                            "content": "双方约定次日继续聊天。", "status": "planned",
                            "source_message_ids": self.message_ids,
                        }],
                        "stable_facts": [{
                            "content": "用户希望继续聊天。", "source_message_ids": self.message_ids,
                        }],
                        "relationship_observations": [{
                            "content": "双方形成了继续联系的习惯。", "source_message_ids": self.message_ids,
                            "confidence": 0.8,
                        }],
                    }]})
                if "每日详细回忆" in prompt:
                    return Response({
                        "daily_digests": [{
                            "date": "2026-01-01",
                            "summary": "2026年1月1日，用户询问第二天是否继续聊天，Bot明确答应并与用户约定次日再见。",
                        }],
                    })
                return Response({
                    "daily_digests": [{"date": "2026-01-01", "summary": "双方约定继续聊天。"}],
                    "stable_facts": [{
                        "content": "用户希望继续聊天。", "segment_ids": [self.segment_id], "confidence": 0.8,
                    }],
                    "relationship_observations": [{
                        "content": "双方形成了继续联系的习惯。", "segment_ids": [self.segment_id],
                        "confidence": 0.82,
                    }],
                    "phase_summary": "这段时期双方开始保持持续联系。",
                })

        provider = Provider()

        class Service:
            def __init__(self, data_dir, store):
                self.data_dir, self.store, self.config = data_dir, store, Config()

            def _spawn_background(self, coro, *, label):
                coro.close()
                return None

            async def _summary_provider_attempts(self, _ctx):
                return [{"provider": provider, "provider_id": "test"}]

            def _record_token_usage(self, **_kwargs):
                return None

        importer = HistoricalChatImporter(Service(Path(self.temp.name), self.store))
        preview = importer.stage_upload(
            filename="chat.txt",
            content=(
                "u: 2026-01-01 10:00:00\n明天继续聊吗\n\n"
                "b: 2026-01-01 10:00:05\n好呀，明天见\n"
            ).encode("utf-8"),
        )
        started = await importer.start_import({
            "upload_id": preview["upload_id"],
            "speaker_map": {
                "u": {"role": "user", "entity_id": "u1", "display_name": "用户"},
                "b": {"role": "bot", "entity_id": "b1", "display_name": "Bot"},
            },
            "user_id": "u1", "user_name": "用户", "bot_id": "b1", "bot_name": "Bot",
        })
        batch_id = started["batch"]["id"]
        segment = (await self.store.chat_import_segments(batch_id))[0]
        provider.segment_id = segment["id"]
        provider.message_ids = segment["message_ids"]
        staged = []

        async def capture(_batch, observations):
            staged.extend(observations)
            return len(observations)

        importer._stage_relationship_observations = capture
        await importer._run_batch(batch_id)
        batch = await self.store.get_chat_import_batch(batch_id)
        counts = await self.store.chat_import_memory_counts(batch_id)
        imported_memories = await self.store.list_chat_import_memories(batch_id)
        summary_memory = next(item for item in imported_memories if item.memory_type == "conversation_summary")
        daily_memory = next(item for item in imported_memories if item.memory_type == "daily_digest")
        self.assertEqual("completed", batch["state"], batch)
        self.assertEqual(5, counts["total"])
        self.assertEqual(1, counts["conversation_summary"])
        self.assertEqual(1, counts["important_event"])
        self.assertEqual(1, counts["daily_digest"])
        self.assertEqual(1, counts["stable_fact"])
        self.assertEqual(1, counts["relationship_phase_summary"])
        self.assertEqual("用户和 Bot 约好第二天继续聊天。", summary_memory.content)
        self.assertIn("用户询问第二天是否继续聊天", daily_memory.content)
        self.assertEqual(1, batch["stats"]["detail_quality"]["conversation_summaries_enriched"])
        self.assertEqual(1, batch["stats"]["detail_quality"]["daily_digests_enriched"])
        self.assertEqual(provider.message_ids, staged[0]["source_message_ids"])
        self.assertEqual(3, provider.calls)

        # 模拟全局整理结果已持久化后进程中断；恢复时复用检查点，不再次调用模型，
        # 确定性记忆也不会重复增长。
        await self.store.update_chat_import_batch(batch_id, state="reconciling")
        checkpointed = await self.store.get_chat_import_batch(batch_id)
        await importer._finalize_batch(checkpointed)
        resumed_counts = await self.store.chat_import_memory_counts(batch_id)
        self.assertEqual(3, provider.calls)
        self.assertEqual(5, resumed_counts["total"])


class HistoricalChatUploadTests(unittest.TestCase):
    def test_upload_preview_normalizes_to_utf8_and_estimates_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = type("Service", (), {"data_dir": Path(temp), "store": object()})()
            importer = HistoricalChatImporter(service)
            text = "u: 2026-01-01 00:00:00\n你好\n\nb: 2026-01-01 00:00:02\n你好呀\n"
            preview = importer.stage_upload(filename="对话.txt", content=text.encode("utf-8"))
            self.assertEqual(2, preview["stats"]["message_count"])
            self.assertGreaterEqual(preview["stats"]["estimated_summary_calls"], 1)
            normalized = Path(temp) / "historical_chat_imports" / "uploads" / preview["upload_id"] / "source.txt"
            self.assertEqual(text, normalized.read_text(encoding="utf-8"))

    def test_missing_year_choice_creates_distinct_preview_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = type("Service", (), {"data_dir": Path(temp), "store": object()})()
            importer = HistoricalChatImporter(service)
            text = "u: 01-01 00:00:00\n你好\n"
            first = importer.stage_upload(filename="chat.txt", content=text.encode("utf-8"), base_year=2025)
            second = importer.stage_upload(filename="chat.txt", content=text.encode("utf-8"), base_year=2026)
            self.assertNotEqual(first["upload_id"], second["upload_id"])
            self.assertNotEqual(first["stats"]["first_at"], second["stats"]["first_at"])

    def test_reconcile_output_requires_segment_evidence(self) -> None:
        chunk = [{"segment_id": "seg-1", "date": "2026-01-01"}]
        segment_by_id = {
            "seg-1": {"message_ids": ["tl-1", "tl-2"], "start_at": "2026-01-01T00:00:00+00:00"}
        }
        normalized = HistoricalChatImporter._normalize_reconcile_output(
            {
                "daily_digests": [{"date": "2099-01-01", "summary": "错误日期"}],
                "stable_facts": [
                    {"content": "有证据", "segment_ids": ["seg-1"]},
                    {"content": "无证据", "segment_ids": ["made-up"]},
                ],
                "relationship_observations": [
                    {"content": "称呼发生变化", "segment_ids": ["seg-1"], "confidence": 0.8}
                ],
            },
            chunk,
            segment_by_id,
        )
        self.assertEqual([], normalized["daily_digests"])
        self.assertEqual(["tl-1", "tl-2"], normalized["stable_facts"][0]["source_message_ids"])
        self.assertEqual(1, len(normalized["stable_facts"]))
        self.assertEqual(["tl-1", "tl-2"], normalized["relationship_observations"][0]["source_message_ids"])


if __name__ == "__main__":
    unittest.main()
