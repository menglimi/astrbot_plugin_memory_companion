"""2.6.0：REPORT.md 复核出的真问题回归。

覆盖 Lead 自己改的那几处：分层不再按单字误判（S9）、自动档可以改回来（S10）、
去重不把高分项挪到队尾（R4）、注入行不再是字段 dump（R9）、空召回不写「没检索到」
（R11）、跨窗记忆带披露语境（P14）、分量不能被群里一句话抬高（H6）、
群里不主动写记忆（P3）、清理历史默认关且只碰自家片段（A4）、
插件卸载后页面接口快速失败（A6）。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.memory_tier import (
    TIER_IMPRINT,
    TIER_NORMAL,
    apply_tier_to_record,
    classify_tier,
)
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SearchResult,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine


def _iso_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _memory(content: str, *, memory_id: str = "m1", visibility: str = "private_pair",
            scope: str = "private", group_id: str = "", session_id: str = "s1") -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        memory_type="conversation_summary",
        subject=EntityRef(kind="user", id="u1"),
        scope=scope,
        session_id=session_id,
        group_id=group_id,
        visibility=visibility,
        content=content,
        confidence=0.9,
        importance=0.5,
    )


def _ctx(scope: str = "private", *, group_id: str = "") -> SessionContext:
    return SessionContext(
        session_id="qq:GroupMessage:g1" if scope == "group" else "qq:FriendMessage:u1",
        scope=scope,
        platform="qq",
        user_id="u1",
        user_name="阿哲",
        bot_id="b1",
        group_id=group_id,
        message_text="还记得上次说的事吗",
    )


def _composer(**humanize) -> InjectionComposer:
    composer = InjectionComposer()
    config = {"enabled": True, "no_recall_hint_enabled": True, **humanize}
    composer.set_humanize_config_provider(
        lambda dotted, default: config.get(
            dotted.replace("memory_humanization.", "").replace("memory_injection.", ""), default
        )
    )
    return composer


class TierRuleTests(unittest.TestCase):
    """S9：单字不再算「刻骨」；S10：自动定的档可以随规则改回来。"""

    def test_single_character_body_word_is_not_imprint(self) -> None:
        for text in ("今天胸闷得厉害", "胸牌落在会议室了", "最近有点脱发", "家里只有一张硬床"):
            with self.subTest(text=text):
                self.assertEqual(TIER_NORMAL, classify_tier(text, memory_type="conversation_summary"))

    def test_two_intimate_phrases_are_still_imprint(self) -> None:
        self.assertEqual(
            TIER_IMPRINT,
            classify_tier("那天她抱着我说想和我上床。", memory_type="conversation_summary"),
        )

    def test_automatic_tier_can_be_lowered_when_rules_change(self) -> None:
        record = _memory("今天胸闷得厉害，早早就睡了")
        record.durability = "pinned"
        record.metadata = {"memory_tier": "imprint"}

        apply_tier_to_record(record)

        self.assertNotEqual("pinned", record.durability)

    def test_manually_pinned_tier_survives_a_recompute(self) -> None:
        record = _memory("随便一句普通的话")
        record.durability = "pinned"
        record.tags = ["manual"]
        record.metadata = {"memory_tier": "imprint", "memory_tier_manual": True}

        apply_tier_to_record(record)

        self.assertEqual("pinned", record.durability)


class DedupeOrderTests(unittest.TestCase):
    """R4：同内容的两条，保留高分那条在原位，而不是挪到队尾被 top_k 截掉。"""

    def test_better_duplicate_keeps_its_slot(self) -> None:
        engine = RetrievalEngine.__new__(RetrievalEngine)
        low = SearchResult(memory=_memory("我们一起在河边跑步", memory_id="low"), score=0.4, reason="x")
        other = SearchResult(memory=_memory("她喜欢猫", memory_id="other"), score=0.9, reason="x")
        high = SearchResult(memory=_memory("我们一起在河边跑步。", memory_id="high"), score=0.8, reason="x")

        kept = RetrievalEngine._dedupe_by_content(engine, [low, other, high], 0.8)

        self.assertEqual(["high", "other"], [item.memory.id for item in kept])


class InjectionHonestyTests(unittest.TestCase):
    """R9 注入行是人话；R11 空召回不再自报「没检索到」；P14 跨窗披露。"""

    def test_injected_line_reads_like_a_recollection(self) -> None:
        injected = _composer().compose(
            _ctx(), [SearchResult(memory=_memory("她说她怕一个人睡，喜欢开着灯"), score=1.0, reason="x")],
            max_chars=4000,
        )
        self.assertIn("想起", injected)
        for leak in ("importance=", "confidence=", "记忆印象", "lifecycle="):
            self.assertNotIn(leak, injected)

    def test_empty_recall_writes_nothing_by_default(self) -> None:
        self.assertEqual("", _composer().compose(_ctx(), [], max_chars=4000))

    def test_empty_recall_notice_only_when_debug_switch_is_on(self) -> None:
        # 拟人模式默认会先说「真想不起来」，旧回执只在关掉拟人提示、且诊断开关打开时出现。
        injected = _composer(no_recall_hint_enabled=False, empty_recall_notice=True).compose(
            _ctx(), [], max_chars=4000
        )
        self.assertIn("没有检索到足够相关的长期记忆", injected)

    def test_private_memory_used_in_group_carries_a_disclosure_hint(self) -> None:
        injected = _composer().compose(
            _ctx("group", group_id="g1"),
            [SearchResult(memory=_memory("她说她其实怕一个人睡"), score=1.0, reason="x")],
            max_chars=4000,
        )
        self.assertIn("私聊", injected)

    def test_memory_from_another_group_carries_a_disclosure_hint(self) -> None:
        memory = _memory("那天在另一个群里说起搬家的事", visibility="group_public", scope="group", group_id="g2")
        injected = _composer().compose(
            _ctx("group", group_id="g1"),
            [SearchResult(memory=memory, score=1.0, reason="x")],
            max_chars=4000,
        )
        self.assertIn("别的群", injected)


class GroupWriteGuardTests(unittest.IsolatedAsyncioTestCase):
    """H6：群里不能把自己抬成刻骨的人；P3：群里默认不写记忆。"""

    def make_service(self, config: dict | None = None):
        import tempfile
        from pathlib import Path
        from astrbot_plugin_memory_companion.core.service import MemoryCompanionService

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        merged = {"retrieval": {"embedding_enabled": False}}
        for key, value in (config or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        service = MemoryCompanionService(
            context=None, config=merged, plugin_root=ROOT, data_dir=Path(temp_dir.name)
        )
        self.addCleanup(service.close)
        return service

    async def test_group_member_cannot_raise_their_own_weight(self) -> None:
        service = self.make_service()
        ctx = _ctx("group", group_id="g1")
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))

        result = await service.tool_person_weight(ctx, action="set", weight=100)

        self.assertFalse(result.get("ok"))
        self.assertEqual("person_weight_raise_requires_private", result.get("code"))
        self.assertEqual(0, result.get("weight"))

    async def test_group_member_can_lower_their_own_weight(self) -> None:
        service = self.make_service()
        ctx = _ctx("group", group_id="g1")
        # H6：往回收也必须是用户本人这句话在说关系要收一收。
        ctx.message_text = "我们没那么熟，别叫这么亲"
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        await service.initialize_database()
        await service.store.set_person_weight(user_id="u1", weight=80, platform="qq", bot_id="b1")

        result = await service.tool_person_weight(ctx, action="set", weight=20)

        self.assertTrue(result.get("ok"))
        self.assertEqual(20, result.get("weight"))

    async def test_group_reset_requires_private(self) -> None:
        service = self.make_service()
        ctx = _ctx("group", group_id="g1")
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))

        result = await service.tool_person_weight(ctx, action="reset")

        self.assertEqual("person_weight_reset_requires_private", result.get("code"))

    async def test_remember_in_group_is_refused_by_default(self) -> None:
        service = self.make_service()
        ctx = _ctx("group", group_id="g1")
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        await service.initialize_database()

        result = await service.tool_remember(ctx, "群里有人说要记住这件事")

        self.assertFalse(result.get("ok"))
        self.assertEqual("group_remember_disabled", result.get("code"))

    async def test_remember_in_group_when_explicitly_enabled_is_never_pinned(self) -> None:
        service = self.make_service({"memory_tools": {"allow_group_remember": True}})
        ctx = _ctx("group", group_id="g1")
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        await service.initialize_database()
        admin_event = SimpleNamespace(is_admin=lambda: True)

        result = await service.tool_remember(
            admin_event, "群里说好下周六一起去爬山", proposal={"durability": "pinned"}
        )

        self.assertTrue(result.get("ok"))
        self.assertNotEqual("pinned", result.get("durability"))

    async def test_group_member_cannot_make_bot_remember_even_when_enabled(self) -> None:
        service = self.make_service({"memory_tools": {"allow_group_remember": True}})
        ctx = _ctx("group", group_id="g1")
        service.identity = SimpleNamespace(resolve_event_context=AsyncMock(return_value=ctx))
        await service.initialize_database()
        member_event = SimpleNamespace(is_admin=lambda: False)

        result = await service.tool_remember(member_event, "普通群成员想让她记住这句话")

        self.assertFalse(result.get("ok"))
        self.assertEqual("group_remember_requires_admin", result.get("code"))


class RequestHistoryCleanupTests(unittest.TestCase):
    """A4：清理历史默认不碰宿主内容。"""

    def test_sanitize_keeps_host_history_by_default(self) -> None:
        from astrbot_plugin_memory_companion.core.astrbot_compat import sanitize_request_history

        req = SimpleNamespace(
            contexts=[
                {"role": "user", "content": "普通用户消息"},
                {"role": "assistant", "content": "普通回复"},
            ],
            system_prompt="原有系统提示",
        )

        result = sanitize_request_history(req)

        self.assertEqual(0, result.get("removed", 0))
        self.assertEqual(2, len(req.contexts))
        self.assertEqual("原有系统提示", req.system_prompt)

    def test_clean_proactive_history_is_off_in_schema(self) -> None:
        import json
        from pathlib import Path

        schema = json.loads((Path(ROOT) / "_conf_schema.json").read_text(encoding="utf-8"))
        item = schema["private_companion_bridge"]["items"]["clean_proactive_history"]
        self.assertFalse(item["default"])


class TerminatedPanelTests(unittest.IsolatedAsyncioTestCase):
    """A6：宿主不能反注册 web api，所以 handler 自己要快速失败。"""

    async def test_page_route_returns_503_after_terminate(self) -> None:
        from unittest.mock import patch

        from astrbot_plugin_memory_companion import page_api

        api = page_api.PluginPageApi.__new__(page_api.PluginPageApi)
        api.plugin = SimpleNamespace(terminated=True)

        async def handler():
            raise AssertionError("terminated 之后不应该再执行 handler")

        class _FakeResponse:
            status_code = 503

        def _fake_jsonify(payload):
            return _FakeResponse()

        wrapped = page_api.PluginPageApi._wrap_route(api, "/stats", handler)
        with patch.object(page_api, "jsonify", _fake_jsonify):
            response = await wrapped()

        self.assertEqual(503, response.status_code)


if __name__ == "__main__":
    unittest.main()
