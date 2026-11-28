"""来源集合开放后的注册、聚合与权重约定测试。

三条老标签（minecraft / qq / mixed）必须逐字沿用旧行为；这里新增的
注册表、通用聚合与权重解析都是**叠加**的：

* 第三方来源（注册过的或只是合法的 token）不得再被聚合折叠成 qq；
* 注册只能用合法名字，unknown / mixed 是保留状态；
* 权重解析在默认配置下恒为 1.0，mixed / unknown 永远不降权。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core import source_surface as ss
from core.models import SessionContext
from core.service import MemoryCompanionService


def _row(rid, message_id="", metadata=None, platform="napcat"):
    return {"id": rid, "message_id": message_id, "platform": platform, "metadata": metadata}


DISCORD = json.dumps(
    [{"name": "discord", "message_id_prefixes": ["dc-"], "platforms": ["discord", "discord_bot"]}]
)


class BuiltinSetUnchangedTests(unittest.TestCase):
    """默认配置下，判定、片段形状与聚合结果与开放集合之前完全一致。"""

    def test_detection_order_is_unchanged(self):
        self.assertEqual(
            (ss.SURFACE_MINECRAFT, ss.BASIS_MESSAGE_ID_PREFIX),
            ss.detect_source_surface("mc-1fd3b3d3ccd076dc", "napcat"),
        )
        self.assertEqual(
            (ss.SURFACE_QQ, ss.BASIS_PLATFORM),
            ss.detect_source_surface("123456", "napcat"),
        )
        self.assertEqual(
            (ss.SURFACE_UNKNOWN, ss.BASIS_PLATFORM),
            ss.detect_source_surface("123456", "telegram"),
        )
        self.assertEqual(
            (ss.SURFACE_UNKNOWN, ss.BASIS_UNKNOWN),
            ss.detect_source_surface("", ""),
        )

    def test_default_rules_are_exactly_the_builtin_specs(self):
        prefixes, platforms = ss.source_surface_rules("")
        self.assertEqual({ss.MINECRAFT_MESSAGE_PREFIX: ss.SURFACE_MINECRAFT}, prefixes)
        self.assertEqual({platform: ss.SURFACE_QQ for platform in ss.QQ_PLATFORMS}, platforms)
        self.assertEqual(ss.BUILTIN_SPECS, ss.surface_specs(""))

    def test_metadata_fragment_shape_is_unchanged(self):
        fragment = ss.source_surface_metadata("mc-abc", "napcat")
        self.assertEqual(
            {ss.SOURCE_SURFACE_KEY: ss.SURFACE_MINECRAFT, ss.SOURCE_SURFACE_BY_KEY: ss.BASIS_MESSAGE_ID_PREFIX},
            fragment,
        )


class RegisteredSourceTests(unittest.TestCase):
    """注册生效：前缀、平台都可以接新来源，且不改变老来源的判定。"""

    def test_registered_prefix_is_detected(self):
        rules = dict(zip(("known_prefixes", "known_platforms"), ss.source_surface_rules(DISCORD)))
        self.assertEqual(
            ("discord", ss.BASIS_MESSAGE_ID_PREFIX),
            ss.detect_source_surface("dc-9999", "telegram", **rules),
        )

    def test_registered_platform_is_detected(self):
        rules = dict(zip(("known_prefixes", "known_platforms"), ss.source_surface_rules(DISCORD)))
        self.assertEqual(
            ("discord", ss.BASIS_PLATFORM),
            ss.detect_source_surface("9999", "discord", **rules),
        )

    def test_prefix_wins_over_platform(self):
        rules = dict(zip(("known_prefixes", "known_platforms"), ss.source_surface_rules(DISCORD)))
        self.assertEqual(
            ("discord", ss.BASIS_MESSAGE_ID_PREFIX),
            ss.detect_source_surface("dc-1", "napcat", **rules),
        )

    def test_longest_prefix_wins(self):
        raw = json.dumps(
            [
                {"name": "minecraft", "message_id_prefixes": ["mc-raid-"]},
                {"name": "discord", "message_id_prefixes": ["dc-"]},
            ]
        )
        rules = dict(zip(("known_prefixes", "known_platforms"), ss.source_surface_rules(raw)))
        self.assertEqual(
            ("minecraft", ss.BASIS_MESSAGE_ID_PREFIX),
            ss.detect_source_surface("mc-raid-7", "napcat", **rules),
        )
        self.assertEqual(
            ("minecraft", ss.BASIS_MESSAGE_ID_PREFIX),
            ss.detect_source_surface("mc-plain-7", "napcat", **rules),
        )
        self.assertEqual(
            ("discord", ss.BASIS_MESSAGE_ID_PREFIX),
            ss.detect_source_surface("dc-7", "napcat", **rules),
        )

    def test_reserved_and_illegal_names_are_ignored(self):
        raw = json.dumps(
            [
                {"name": "unknown", "message_id_prefixes": ["un-"]},
                {"name": "mixed", "message_id_prefixes": ["mx-"]},
                {"name": "Not A Name", "message_id_prefixes": ["na-"]},
                {"name": "1abc", "message_id_prefixes": ["1a-"]},
                {"name": "discord", "message_id_prefixes": ["dc-"]},
            ]
        )
        prefixes, _platforms = ss.source_surface_rules(raw)
        self.assertEqual({ss.MINECRAFT_MESSAGE_PREFIX: "minecraft", "dc-": "discord"}, prefixes)

    def test_malformed_registry_payload_falls_back_to_builtins(self):
        for raw in ("{not json", "null", "[]", 42, None, ""):
            with self.subTest(raw=raw):
                self.assertEqual(ss.BUILTIN_SPECS, ss.surface_specs(raw))

    def test_entry_without_ids_does_not_change_detection(self):
        # 只有名字、没有前缀/平台：注册本身合法，但它既不抢 mc- 也不加平台。
        rules = dict(zip(("known_prefixes", "known_platforms"), ss.source_surface_rules('{"name": "discord"}')))
        self.assertEqual({ss.MINECRAFT_MESSAGE_PREFIX: "minecraft"}, rules["known_prefixes"])
        self.assertEqual((ss.SURFACE_UNKNOWN, ss.BASIS_PLATFORM), ss.detect_source_surface("1", "discord", **rules))


class AggregationTests(unittest.TestCase):
    """聚合从「mc+qq 二值」改成「集合」，第三方来源不再被错标成 qq。"""

    def test_third_party_surface_is_not_folded_into_qq(self):
        # 这是开放值域的那条回归：旧实现里任何非 mc 集合都落到 qq。
        self.assertEqual(
            {ss.SOURCE_SURFACE_KEY: "discord", ss.SOURCE_SURFACE_REFS_KEY: ["tl_a"]},
            ss.aggregate_source_surface([_row("tl_a", metadata={ss.SOURCE_SURFACE_KEY: "discord"})]),
        )
        # 没注册也照样认：注册只是「怎么判」，不是「认不认」的白名单。
        self.assertEqual(
            "mastodon",
            ss.aggregate_source_surface(
                [_row("tl_b", metadata={ss.SOURCE_SURFACE_KEY: "mastodon"})]
            )[ss.SOURCE_SURFACE_KEY],
        )
        # 老的三值一个不变。
        self.assertEqual(
            "minecraft",
            ss.aggregate_source_surface(
                [_row("tl_c", metadata={ss.SOURCE_SURFACE_KEY: "minecraft"})]
            )[ss.SOURCE_SURFACE_KEY],
        )
        self.assertEqual(
            "qq",
            ss.aggregate_source_surface([_row("tl_d", metadata={ss.SOURCE_SURFACE_KEY: "qq"})])[
                ss.SOURCE_SURFACE_KEY
            ],
        )

    def test_mixed_aggregation_is_generalised(self):
        both = ss.aggregate_source_surface(
            [
                _row("tl_a", metadata={ss.SOURCE_SURFACE_KEY: "discord"}),
                _row("tl_b", metadata={ss.SOURCE_SURFACE_KEY: "qq"}),
            ]
        )
        self.assertEqual(ss.SURFACE_MIXED, both[ss.SOURCE_SURFACE_KEY])
        legacy_mixed = ss.aggregate_source_surface(
            [_row("tl_a", metadata={ss.SOURCE_SURFACE_KEY: ss.SURFACE_MIXED})]
        )
        self.assertEqual(ss.SURFACE_MIXED, legacy_mixed[ss.SOURCE_SURFACE_KEY])
        mc_and_qq = ss.aggregate_source_surface(
            [
                _row("tl_a", message_id="mc-1"),
                _row("tl_b", metadata={ss.SOURCE_SURFACE_KEY: "qq"}),
            ]
        )
        self.assertEqual(ss.SURFACE_MIXED, mc_and_qq[ss.SOURCE_SURFACE_KEY])

    def test_nothing_recognised_writes_no_keys(self):
        self.assertEqual({}, ss.aggregate_source_surface([_row("tl_a", message_id="123")]))
        self.assertEqual({}, ss.aggregate_source_surface([]))

    def test_refs_and_truncation_survive_new_surfaces(self):
        rows = [
            _row(f"tl_{index}", metadata={ss.SOURCE_SURFACE_KEY: "discord"}) for index in range(40)
        ]
        fragment = ss.aggregate_source_surface(rows)
        self.assertEqual("discord", fragment[ss.SOURCE_SURFACE_KEY])
        self.assertEqual(ss.MAX_AGGREGATED_REFS, len(fragment[ss.SOURCE_SURFACE_REFS_KEY]))
        self.assertTrue(fragment[ss.SOURCE_SURFACE_TRUNCATED_KEY])


class WeightContractTests(unittest.TestCase):
    """权重解析：默认中性、显式映射优先、保留状态恒 1.0。"""

    def test_default_is_neutral(self):
        for surface in ("minecraft", "qq", ss.SURFACE_MIXED, ss.SURFACE_UNKNOWN, "", None):
            with self.subTest(surface=surface):
                self.assertEqual(1.0, ss.resolve_surface_weight(surface))

    def test_priority_discounts_only_the_other_surface(self):
        self.assertEqual(1.0, ss.resolve_surface_weight("qq", priority="qq", weight=0.5))
        self.assertEqual(0.5, ss.resolve_surface_weight("minecraft", priority="qq", weight=0.5))
        self.assertEqual(1.0, ss.resolve_surface_weight("minecraft", priority="equal", weight=0.5))

    def test_explicit_weights_override_priority(self):
        weights = {"minecraft": 0.2}
        self.assertEqual(0.2, ss.resolve_surface_weight("minecraft", priority="qq", weight=0.5, weights=weights))
        self.assertEqual(1.0, ss.resolve_surface_weight("qq", priority="qq", weight=0.5, weights=weights))
        self.assertEqual(
            0.2,
            ss.resolve_surface_weight("minecraft", priority="qq", weight=0.5, weights=json.dumps(weights)),
        )

    def test_reserved_surfaces_are_never_discounted(self):
        for surface in (ss.SURFACE_MIXED, ss.SURFACE_UNKNOWN, "", "not a name"):
            with self.subTest(surface=surface):
                self.assertEqual(
                    1.0,
                    ss.resolve_surface_weight(surface, priority="qq", weight=0.0, weights={"minecraft": 0.0}),
                )

    def test_undeclared_surface_stays_neutral(self):
        # 未声明的合法 token 不被 priority 规则降权：它没选过这套规则，只记 warning。
        declared = ("minecraft", "qq")
        self.assertEqual(
            1.0,
            ss.resolve_surface_weight("discord", priority="qq", weight=0.5, registered=declared),
        )
        self.assertEqual(
            0.5,
            ss.resolve_surface_weight("minecraft", priority="qq", weight=0.5, registered=declared),
        )
        self.assertEqual(
            1.0,
            ss.resolve_surface_weight("qq", priority="qq", weight=0.5, registered=declared),
        )

    def test_unusable_weights_fall_back_instead_of_raising(self):
        self.assertEqual(1.0, ss.resolve_surface_weight("minecraft", priority="qq", weight="abc"))
        # 坏 JSON 只会丢掉「显式映射」，不会连 priority/weight 一起失效。
        self.assertEqual(0.5, ss.resolve_surface_weight("minecraft", priority="qq", weight=0.5, weights="{not json"))
        self.assertEqual(1.0, ss.resolve_surface_weight("minecraft", priority="mixed", weight=0.5))
        self.assertEqual({"minecraft": 0.4}, ss.parse_surface_weights('{"minecraft": 0.4, "nope": "x"}'))


class ServiceWiringTests(unittest.IsolatedAsyncioTestCase):
    """服务层把配置读成规则与权重映射；默认配置保持空规则 = 内置集合。"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self._services: list[MemoryCompanionService] = []
        self.addCleanup(self._close_services)

    def _close_services(self) -> None:
        for service in self._services:
            try:
                service.close()
            except Exception:
                pass

    def _service(self, config: dict) -> MemoryCompanionService:
        data_dir = Path(self._temp_dir.name) / ("svc%d" % len(self._services))
        data_dir.mkdir()
        service = MemoryCompanionService(context=None, config=config, plugin_root=Path("."), data_dir=data_dir)
        self._services.append(service)
        return service

    def test_default_config_yields_builtin_rules(self):
        service = self._service({})
        rules = service._source_surface_rules()
        self.assertEqual({ss.MINECRAFT_MESSAGE_PREFIX: "minecraft"}, rules["known_prefixes"])
        self.assertEqual({}, service._source_surface_weights())

    def test_registry_and_weights_come_from_config(self):
        service = self._service(
            {
                "memory_capture": {"source_surfaces": DISCORD},
                "retrieval_advanced": {"source_surface_weights": '{"discord": 0.4}'},
            }
        )
        rules = service._source_surface_rules()
        self.assertEqual("discord", rules["known_prefixes"]["dc-"])
        self.assertEqual("minecraft", rules["known_prefixes"][ss.MINECRAFT_MESSAGE_PREFIX])
        self.assertEqual({"discord": 0.4}, service._source_surface_weights())
        self.assertEqual(
            ("discord", ss.BASIS_MESSAGE_ID_PREFIX),
            ss.detect_source_surface("dc-1", "telegram", **rules),
        )


if __name__ == "__main__":
    unittest.main()
