"""记忆来源标记（source_surface）的单元测试。

覆盖 core/source_surface.py 的判定顺序与 metadata 合并语义：

* Minecraft 轮次的 message id 前缀 mc- 必须压过平台判定，因为 MC 聊天是
  经 QQ 适配器（napcat/aiocqhttp）注入的，平台列看起来和真实 QQ 私聊一样；
* 平台只认 OneBot/QQ 家族，其它平台落 unknown 但仍记 platform 依据；
* 标签只进 metadata，绝不产出 tags（tags 会进 FTS 文本，污染关键词召回）。
"""

from __future__ import annotations

import pytest

from core import source_surface as ss


def test_mc_prefix_wins_over_qq_platform():
    surface, basis = ss.detect_source_surface("mc-1fd3b3d3ccd076dc", "napcat")
    assert surface == ss.SURFACE_MINECRAFT
    assert basis == ss.BASIS_MESSAGE_ID_PREFIX


def test_mc_prefix_wins_even_without_platform():
    surface, basis = ss.detect_source_surface("mc-abcdef0123456789", "")
    assert (surface, basis) == (ss.SURFACE_MINECRAFT, ss.BASIS_MESSAGE_ID_PREFIX)


def test_qq_platform_without_prefix_is_qq():
    for platform in sorted(ss.QQ_PLATFORMS):
        surface, basis = ss.detect_source_surface("1234567890001", platform)
        assert (surface, basis) == (ss.SURFACE_QQ, ss.BASIS_PLATFORM)


def test_non_qq_platform_is_unknown_but_records_platform():
    surface, basis = ss.detect_source_surface("webchat-42", "webchat")
    assert surface == ss.SURFACE_UNKNOWN
    assert basis == ss.BASIS_PLATFORM


def test_empty_message_and_platform_is_unknown():
    assert ss.detect_source_surface("", "") == (ss.SURFACE_UNKNOWN, ss.BASIS_UNKNOWN)


def test_none_values_do_not_crash():
    assert ss.detect_source_surface(None, None) == (ss.SURFACE_UNKNOWN, ss.BASIS_UNKNOWN)


def test_case_and_whitespace_are_normalised():
    assert ss.detect_source_surface("  MC-AbCdEf  ", "NapCat") == (
        ss.SURFACE_MINECRAFT,
        ss.BASIS_MESSAGE_ID_PREFIX,
    )
    assert ss.detect_source_surface(" 12345 ", " NAPCAT ") == (ss.SURFACE_QQ, ss.BASIS_PLATFORM)


def test_known_prefixes_extend_without_breaking_mc():
    extra = {"bili-": "bilibili"}
    assert ss.detect_source_surface("bili-watch-1", "napcat", known_prefixes=extra) == (
        "bilibili",
        ss.BASIS_MESSAGE_ID_PREFIX,
    )
    assert ss.detect_source_surface("mc-1", "napcat", known_prefixes=extra) == (
        ss.SURFACE_MINECRAFT,
        ss.BASIS_MESSAGE_ID_PREFIX,
    )


def test_metadata_fragment_shape_has_no_tags():
    fragment = ss.source_surface_metadata("mc-1", "napcat")
    assert fragment == {
        ss.SOURCE_SURFACE_KEY: ss.SURFACE_MINECRAFT,
        ss.SOURCE_SURFACE_BY_KEY: ss.BASIS_MESSAGE_ID_PREFIX,
    }
    assert "tags" not in fragment


def test_merge_keeps_existing_keys_and_is_in_place():
    metadata = {ss.SOURCE_SURFACE_KEY: "preset", "source": "group_conversation_observer"}
    returned = ss.merge_source_surface(metadata, "mc-77", "aiocqhttp")
    assert returned is metadata
    assert metadata[ss.SOURCE_SURFACE_KEY] == "preset"
    assert metadata[ss.SOURCE_SURFACE_BY_KEY] == ss.BASIS_MESSAGE_ID_PREFIX
    assert metadata["source"] == "group_conversation_observer"


def test_merge_adds_keys_to_empty_dict():
    metadata: dict = {}
    ss.merge_source_surface(metadata, "123456", "aiocqhttp")
    assert metadata == {
        ss.SOURCE_SURFACE_KEY: ss.SURFACE_QQ,
        ss.SOURCE_SURFACE_BY_KEY: ss.BASIS_PLATFORM,
    }


@pytest.mark.parametrize("message_id", ["mc-", "MC-0", "mc-0000abcd"])
def test_all_mc_shaped_ids_are_minecraft(message_id):
    surface, _ = ss.detect_source_surface(message_id, "napcat")
    assert surface == ss.SURFACE_MINECRAFT

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


def _row(rid, message_id="", metadata=None, platform="napcat"):
    return {"id": rid, "message_id": message_id, "platform": platform, "metadata": metadata}


def test_aggregate_minecraft_only():
    rows = [_row("tl_a", "mc-aaa", {ss.SOURCE_SURFACE_KEY: "minecraft"})]
    assert ss.aggregate_source_surface(rows) == {
        ss.SOURCE_SURFACE_KEY: ss.SURFACE_MINECRAFT,
        ss.SOURCE_SURFACE_REFS_KEY: ["tl_a"],
    }


def test_aggregate_qq_only():
    rows = [_row("tl_b", "1234567890001", {ss.SOURCE_SURFACE_KEY: "qq"})]
    assert ss.aggregate_source_surface(rows) == {
        ss.SOURCE_SURFACE_KEY: ss.SURFACE_QQ,
        ss.SOURCE_SURFACE_REFS_KEY: ["tl_b"],
    }


def test_aggregate_mixed_batch_is_mixed():
    rows = [
        _row("tl_c", "mc-ccc", {ss.SOURCE_SURFACE_KEY: "minecraft"}),
        _row("tl_d", "12345", {ss.SOURCE_SURFACE_KEY: "qq"}),
    ]
    fragment = ss.aggregate_source_surface(rows)
    assert fragment[ss.SOURCE_SURFACE_KEY] == ss.SURFACE_MIXED
    assert fragment[ss.SOURCE_SURFACE_REFS_KEY] == ["tl_c", "tl_d"]


def test_aggregate_ignores_platform_column():
    # 没有元数据、没有 mc- 前缀：即使 platform 是 napcat 也不能算 qq，
    # 否则 QQ 与 MC 共用一个平台时会把 MC 窗口误标成 qq。
    rows = [_row("tl_e", "", None), _row("tl_f", "1234567890001", "{}")]
    assert ss.aggregate_source_surface(rows) == {}


def test_aggregate_legacy_row_falls_back_to_mc_prefix():
    # 打补丁前的 history 行没有 source_surface，但 message id 前缀仍在。
    rows = [
        _row("tl_g", "mc-test-0001", "{\"source\": \"group_conversation_observer\"}"),
        _row("tl_legacy", metadata='{"message_id": "mc-test-0002"}'),
    ]
    assert ss.aggregate_source_surface(rows) == {
        ss.SOURCE_SURFACE_KEY: ss.SURFACE_MINECRAFT,
        ss.SOURCE_SURFACE_REFS_KEY: ["tl_g", "tl_legacy"],
    }


def test_aggregate_mixed_upstream_row_counts_as_both():
    rows = [_row("tl_h", "", {ss.SOURCE_SURFACE_KEY: "mixed"})]
    assert ss.aggregate_source_surface(rows) == {
        ss.SOURCE_SURFACE_KEY: ss.SURFACE_MIXED,
        ss.SOURCE_SURFACE_REFS_KEY: ["tl_h"],
    }


def test_aggregate_refs_dedupe_and_truncate():
    rows = [_row("tl_dup", "mc-dup", {ss.SOURCE_SURFACE_KEY: "minecraft"}) for _ in range(3)]
    rows += [
        _row("tl_%02d" % index, "mc-%02d" % index, {ss.SOURCE_SURFACE_KEY: "minecraft"})
        for index in range(ss.MAX_AGGREGATED_REFS + 5)
    ]
    fragment = ss.aggregate_source_surface(rows)
    assert len(fragment[ss.SOURCE_SURFACE_REFS_KEY]) == ss.MAX_AGGREGATED_REFS
    assert fragment[ss.SOURCE_SURFACE_TRUNCATED_KEY] is True
    assert fragment[ss.SOURCE_SURFACE_REFS_KEY][0] == "tl_dup"


def test_row_source_surface_can_use_platform_when_asked():
    row = _row("tl_i", "1234567890001", None)
    assert ss.row_source_surface(row) == ""
    assert ss.row_source_surface(row, use_platform=True) == ss.SURFACE_QQ


class SourceSurfaceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """真实 store（临时目录 sqlite）上的接线测试，不只测纯函数。"""

    def make_service(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={"conversation_memory": {"idle_gap_minutes": 20}},
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    async def test_conversation_metadata_marks_mc_and_qq(self):
        service = self.make_service()
        ctx = SessionContext(
            session_id="napcat:FriendMessage:10001",
            scope="private",
            platform="napcat",
            user_id="10001",
            user_name="测试用户",
            bot_id="30001",
            message_id="mc-test-0001",
            message_text="测试消息一",
        )
        metadata = await service._conversation_memory_metadata(ctx, source="group_conversation_observer")
        assert metadata[ss.SOURCE_SURFACE_KEY] == "minecraft"
        assert metadata["source"] == "group_conversation_observer"
        ctx.message_id = "1234567890001"
        qq_metadata = await service._conversation_memory_metadata(ctx, source="group_conversation_observer")
        assert qq_metadata[ss.SOURCE_SURFACE_KEY] == "qq"

    async def test_timeline_window_aggregates_like_the_summary_writer(self):
        service = self.make_service()
        session_id = "napcat:FriendMessage:10001"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        mc_metadata = dict(ss.source_surface_metadata("mc-aaa", "napcat"))
        mc_metadata.update({"message_id": "mc-aaa", "sender_name": "测试用户"})
        mc_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id=session_id,
            scope="private",
            subject_id="10001",
            object_id="10001",
            content="测试消息一",
            metadata=mc_metadata,
            occurred_at=now,
        )
        qq_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id=session_id,
            scope="private",
            subject_id="10001",
            object_id="10001",
            content="你好",
            metadata={
                **ss.source_surface_metadata("1234567890001", "napcat"),
                "message_id": "1234567890001",
                "sender_name": "测试用户",
            },
            occurred_at=now,
        )
        self.assertTrue(mc_id and qq_id)
        window = await service.store.unsummarized_timeline_window(
            session_id=session_id, scope="private", limit=10
        )
        rows = window["rows"]
        self.assertEqual(len(rows), 2)
        # 摘要构造处拿到的正是这一份 rows，所以这里等价于摘要写入路径。
        fragment = ss.aggregate_source_surface(rows)
        self.assertEqual(fragment[ss.SOURCE_SURFACE_KEY], "mixed")
        self.assertEqual(set(fragment[ss.SOURCE_SURFACE_REFS_KEY]), {mc_id, qq_id})
        only_mc = ss.aggregate_source_surface([row for row in rows if row["id"] == mc_id])
        self.assertEqual(
            only_mc,
            {ss.SOURCE_SURFACE_KEY: "minecraft", ss.SOURCE_SURFACE_REFS_KEY: [mc_id]},
        )

    async def test_core_memory_inherits_surface_from_its_sources(self):
        service = self.make_service()
        mc_memory = MemoryRecord(
            id="mem_mc_summary",
            memory_type="conversation_summary",
            scope="private",
            content="一条游戏内摘要",
            metadata={"summary_refs": [], ss.SOURCE_SURFACE_KEY: "minecraft"},
        )
        qq_memory = MemoryRecord(
            id="mem_qq_summary",
            memory_type="conversation_summary",
            scope="private",
            content="一条私聊摘要",
            metadata={"summary_refs": [], ss.SOURCE_SURFACE_KEY: "qq"},
        )
        await service.store.insert_memory(mc_memory)
        await service.store.insert_memory(qq_memory)
        only_mc = await service._core_source_surface_metadata([{"id": "mem_mc_summary"}])
        self.assertEqual(
            only_mc,
            {ss.SOURCE_SURFACE_KEY: "minecraft", ss.SOURCE_SURFACE_REFS_KEY: ["mem_mc_summary"]},
        )
        both = await service._core_source_surface_metadata(
            [{"id": "mem_mc_summary"}, {"id": "mem_qq_summary"}]
        )
        self.assertEqual(both[ss.SOURCE_SURFACE_KEY], "mixed")
        # 只含 mixed 摘要的上游记录，核心记忆仍是 mixed
        mixed_memory = MemoryRecord(
            id="mem_mixed_summary",
            memory_type="conversation_summary",
            scope="private",
            content="一天里两类消息都有",
            metadata={ss.SOURCE_SURFACE_KEY: "mixed"},
        )
        await service.store.insert_memory(mixed_memory)
        chain = await service._core_source_surface_metadata([{"id": "mem_mixed_summary"}])
        self.assertEqual(chain[ss.SOURCE_SURFACE_KEY], "mixed")
        self.assertEqual(await service._core_source_surface_metadata([]), {})
        self.assertEqual(await service._core_source_surface_metadata(None), {})
