from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.person_weight import decay_factor
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


RELATION_BLOCK = (
    "<relation>我在阿哲面前就是恋人：说话会软下来。"
    "他补的一句：只准叫他名字。以本条为准。</relation>"
)


class PersonMemoryWiringTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, config: dict | None = None) -> MemoryCompanionService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        merged = {"retrieval": {"embedding_enabled": False}}
        for key, value in (config or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        service = MemoryCompanionService(
            context=None,
            config=merged,
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def private_context(**overrides) -> SessionContext:
        values = dict(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            user_name="阿哲",
            bot_id="b1",
            message_id="m1",
            message_text="今天好累",
        )
        values.update(overrides)
        return SessionContext(**values)

    @staticmethod
    def group_context() -> SessionContext:
        return SessionContext(
            session_id="qq:GroupMessage:g1",
            scope="group",
            platform="qq",
            user_id="u1",
            user_name="阿哲",
            group_id="g1",
            group_name="测试群",
            bot_id="b1",
            message_text="群里说话",
        )

    @staticmethod
    def memory(
        content: str,
        *,
        scope: str = "private",
        visibility: str = "private_pair",
        group_id: str = "",
        owner_bot_id: str = "b1",
        durability: str = "normal",
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_type="explicit_memory",
            subject=EntityRef(kind="user", id="u1", name="阿哲"),
            object=EntityRef.bot_self("b1"),
            scope=scope,
            session_id="qq:GroupMessage:g1" if scope == "group" else "qq:FriendMessage:u1",
            platform="qq",
            group_id=group_id,
            visibility=visibility,
            sayability="direct",
            reality_level="real_user_fact",
            lifecycle="stable_memory",
            content=content,
            evidence="用户说过。",
            confidence=0.9,
            importance=0.8,
            owner_bot_id=owner_bot_id,
            durability=durability,
            tags=["stable_fact"],
        )

    # ---- 吸收：关系插件说的关系只进档案 ----

    async def test_relation_hint_is_written_into_identity_profile(self) -> None:
        service = self.make_service()
        await service.initialize_database()
        ctx = self.private_context()
        req = SimpleNamespace(
            system_prompt="系统提示",
            extra_user_content_parts=[SimpleNamespace(text=RELATION_BLOCK)],
        )

        await service._absorb_relation_hints(ctx, req=req)

        profile = await service.store.identity_profile(
            platform="qq", entity=EntityRef(kind="user", id="u1", name="阿哲")
        )
        self.assertEqual("恋人", profile.get("relation_label"))
        self.assertEqual("阿哲", profile.get("relation_address"))
        self.assertEqual("只准叫他名字", profile.get("relation_note"))
        self.assertEqual("context", profile.get("relation_source"))

    async def test_relation_hint_never_overrides_what_the_user_said(self) -> None:
        service = self.make_service()
        await service.initialize_database()
        entity = EntityRef(kind="user", id="u1", name="阿哲")
        await service.store.upsert_identity(
            platform="qq",
            entity=entity,
            aliases=[],
            profile={"relation_label": "老同学", "relation_source": "user"},
            confidence=0.9,
        )
        ctx = self.private_context()

        await service._absorb_relation_hints(
            ctx,
            req=SimpleNamespace(system_prompt=RELATION_BLOCK),
        )

        profile = await service.store.identity_profile(platform="qq", entity=entity)
        self.assertEqual("老同学", profile.get("relation_label"))
        self.assertEqual("user", profile.get("relation_source"))

    async def test_absorb_can_be_switched_off(self) -> None:
        service = self.make_service({"persona_memory": {"absorb_enabled": False}})
        await service.initialize_database()
        ctx = self.private_context()

        await service._absorb_relation_hints(
            ctx,
            req=SimpleNamespace(system_prompt=RELATION_BLOCK),
        )

        profile = await service.store.identity_profile(
            platform="qq", entity=EntityRef(kind="user", id="u1")
        )
        self.assertEqual({}, profile)

    async def test_plain_request_writes_nothing(self) -> None:
        service = self.make_service()
        await service.initialize_database()
        ctx = self.private_context()

        await service._absorb_relation_hints(
            ctx,
            req=SimpleNamespace(
                system_prompt="普通系统提示",
                extra_user_content_parts=[SimpleNamespace(text="普通用户内容")],
            ),
        )

        profile = await service.store.identity_profile(
            platform="qq", entity=EntityRef(kind="user", id="u1")
        )
        self.assertEqual({}, profile)

    # ---- 分量：能查、能改、能抹 ----

    async def test_get_weight_reports_a_band_not_a_log_line(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        service.identity = SimpleNamespace(
            resolve_event_context=AsyncMock(return_value=ctx)
        )

        result = await service.tool_person_weight(ctx, action="get")

        self.assertTrue(result.get("ok"))
        self.assertEqual(0, result.get("weight"))
        self.assertEqual("路过的人", result.get("band_label"))

    async def test_user_can_lower_the_weight_and_it_sticks(self) -> None:
        service = self.make_service()
        # H6：改分量要有用户本人的原话作凭据，模型不能自己动手。
        ctx = self.private_context(message_text="我们没那么熟，别对我这么好")
        service.identity = SimpleNamespace(
            resolve_event_context=AsyncMock(return_value=ctx)
        )
        await service.initialize_database()
        await service.store.insert_memory(self.memory("一起熬夜看完了那部片子"))

        result = await service.tool_person_weight(ctx, action="set", weight=6)

        self.assertTrue(result.get("ok"))
        self.assertEqual(6, result.get("weight"))
        self.assertEqual("user", result.get("source"))
        self.assertLess(decay_factor(6), 1.0)

    async def test_setting_a_relationship_writes_it_as_the_user_voice(self) -> None:
        service = self.make_service()
        ctx = self.private_context(message_text="把分量调高一点，我们是恋人了，叫我阿哲")
        service.identity = SimpleNamespace(
            resolve_event_context=AsyncMock(return_value=ctx)
        )
        await service.initialize_database()

        result = await service.tool_person_weight(
            ctx,
            action="set",
            weight=80,
            label="恋人",
            address="阿哲",
        )

        self.assertTrue(result.get("profile_updated"))
        profile = await service.store.identity_profile(
            platform="qq", entity=EntityRef(kind="user", id="u1")
        )
        self.assertEqual("恋人", profile.get("relation_label"))
        self.assertEqual("user", profile.get("relation_source"))

    async def test_reset_gives_the_scale_back_to_memory(self) -> None:
        service = self.make_service()
        ctx = self.private_context()
        service.identity = SimpleNamespace(
            resolve_event_context=AsyncMock(return_value=ctx)
        )
        await service.initialize_database()
        await service.store.insert_memory(self.memory("一起熬夜看完了那部片子"))
        ctx.message_text = "把分量调到 90"
        await service.tool_person_weight(ctx, action="set", weight=90)

        ctx.message_text = "把分量重置一下，按你记得的来"
        result = await service.tool_person_weight(ctx, action="reset")

        self.assertTrue(result.get("ok"))
        self.assertEqual(0, result.get("correction"))
        self.assertEqual("auto", result.get("source"))

    async def test_weight_tool_respects_the_switch(self) -> None:
        service = self.make_service({"persona_memory": {"weight_enabled": False}})
        ctx = self.private_context()
        service.identity = SimpleNamespace(
            resolve_event_context=AsyncMock(return_value=ctx)
        )

        result = await service.tool_person_weight(ctx, action="get")

        self.assertEqual({"ok": False, "code": "person_weight_disabled"}, result)

    # ---- 人卡：场合不同、说法不同 ----

    async def test_private_card_keeps_the_whisper_out_of_the_group(self) -> None:
        service = self.make_service()
        await service.initialize_database()
        await service.store.insert_memory(self.memory("偷偷说过：其实很喜欢你"))
        await service.store.insert_memory(
            self.memory(
                "当着全群说过：最近在准备考试",
                scope="group",
                visibility="group_public",
                group_id="g1",
            )
        )
        private_card = await service._compose_person_card_block(self.private_context())
        service._person_card_cache = {}
        group_card = await service._compose_person_card_block(self.group_context())

        self.assertIn("偷偷说过", private_card)
        self.assertIn("准备考试", group_card)
        self.assertNotIn("偷偷说过", group_card)

    async def test_group_card_still_knows_how_much_this_person_matters(self) -> None:
        service = self.make_service()
        await service.initialize_database()
        await service.store.insert_memory(
            self.memory(
                "当着全群说过：最近在准备考试",
                scope="group",
                visibility="group_public",
                group_id="g1",
            )
        )
        await service.store.set_person_weight(
            user_id="u1", weight=70, platform="qq", bot_id="b1"
        )

        card = await service._compose_person_card_block(self.group_context())

        self.assertIn("很重要的人", card)
        # 自己掂量的分量只说「什么人」，不把数字念出来。
        self.assertNotIn("好感", card)

    # ---- 遗忘：按人算 ----

    async def test_decay_factors_follow_the_person_not_the_clock(self) -> None:
        service = self.make_service()
        await service.initialize_database()
        record = self.memory("一起熬夜看完了那部片子")
        await service.store.insert_memory(record)

        low = await service._decay_person_factors([record])
        await service.store.set_person_weight(
            user_id="u1", weight=95, platform="qq", bot_id="b1"
        )
        high = await service._decay_person_factors([record])

        self.assertIn(("b1", "qq", "u1"), low)
        self.assertGreater(
            high[("b1", "qq", "u1")],
            low[("b1", "qq", "u1")],
        )

    async def test_decay_factors_are_skipped_when_the_scale_is_off(self) -> None:
        service = self.make_service({"persona_memory": {"weight_enabled": False}})
        await service.initialize_database()
        record = self.memory("一起熬夜看完了那部片子")

        self.assertEqual({}, await service._decay_person_factors([record]))


if __name__ == "__main__":
    unittest.main()
