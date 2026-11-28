# -*- coding: utf-8 -*-
"""2.5：她记得的人——人物面板（store 目录/单人详情/改称呼与分量）。"""
from __future__ import annotations

import ast
import importlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload if payload is not None else kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")
    quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = quart_stub

from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi

BOT_A = "bot-a"
BOT_B = "bot-b"
PLATFORM = "qq"


class _FakeResponse:
    """jsonify 的替身：既有 status_code，也能取回 payload。"""

    status_code = 200

    def __init__(self, payload) -> None:
        self.payload = payload


def _fake_jsonify(payload=None, **kwargs):
    return _FakeResponse(payload if payload is not None else kwargs)


PAGES = ROOT / "pages" / "记忆面板"


def _record(
    memory_id: str,
    *,
    user_id: str,
    bot_id: str = BOT_A,
    content: str,
    durability: str = "normal",
    memory_type: str = "conversation_summary",
    occurred_at: str = "",
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        memory_type=memory_type,
        subject=EntityRef(kind="user", id=user_id),
        object=EntityRef(kind="bot", id=bot_id),
        platform=PLATFORM,
        scope="private",
        visibility="private_pair",
        lifecycle="stable_memory",
        owner_bot_id=bot_id,
        durability=durability,
        content=content,
        occurred_at=occurred_at,
    )


class PeopleStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory_companion.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def _seed(self) -> None:
        await self.store.upsert_identity(
            platform="qq",
            entity=EntityRef(kind="user", id="u1", name="小王"),
            aliases=["阿哲"],
            profile={"relation_address": "阿哲", "relation_label": "恋人"},
        )
        await self.store.upsert_identity(
            platform="qq",
            entity=EntityRef(kind="user", id="u2", name="小李"),
        )
        for index in range(4):
            await self.store.insert_memory(
                _record(f"u1-{index}", user_id="u1", content=f"和她说过的第{index}件事。")
            )
        await self.store.insert_memory(
            _record("u1-pinned", user_id="u1", content="那天她说会一直记得我。", durability="pinned")
        )
        await self.store.insert_memory(
            _record("u2-0", user_id="u2", content="只在群里见过一次。")
        )
        await self.store.person_weight(user_id="u1", platform=PLATFORM, bot_id=BOT_A)
        await self.store.person_weight(user_id="u2", platform=PLATFORM, bot_id=BOT_A)

    async def test_cards_list_people_with_weight_and_memories(self) -> None:
        await self._seed()
        data = await self.store.list_person_cards(bot_id=BOT_A, sort="weight")
        self.assertEqual("ok", data["state"])
        self.assertEqual(2, data["total"])
        first, second = data["items"]
        self.assertEqual("u1", first["user_id"])
        self.assertEqual("小王", first["display_name"])
        self.assertEqual("阿哲", first["address"])
        self.assertGreater(first["weight"], second["weight"])
        self.assertEqual(5, first["memory_count"])
        self.assertEqual(1, first["imprint_count"])
        self.assertLessEqual(len(first["top"]), 3)
        self.assertTrue(first["top"][0]["content"])
        self.assertEqual("imprint", first["top"][0]["tier"])

    async def test_cards_can_be_searched_by_name_and_address(self) -> None:
        await self._seed()
        by_name = await self.store.list_person_cards(bot_id=BOT_A, query="小李")
        self.assertEqual(["u2"], [item["user_id"] for item in by_name["items"]])
        by_address = await self.store.list_person_cards(bot_id=BOT_A, query="阿哲")
        self.assertEqual(["u1"], [item["user_id"] for item in by_address["items"]])

    async def test_cards_are_separated_per_bot(self) -> None:
        await self._seed()
        other = await self.store.list_person_cards(bot_id=BOT_B)
        self.assertEqual([], other["items"])
        self.assertEqual("empty", other["state"])

    async def test_empty_store_tells_the_panel_it_is_empty(self) -> None:
        data = await self.store.list_person_cards()
        self.assertEqual([], data["items"])
        self.assertEqual("empty", data["state"])

    async def test_person_detail_has_profile_and_memory_list(self) -> None:
        await self._seed()
        detail = await self.store.person_panel_detail(user_id="u1", bot_id=BOT_A)
        self.assertEqual("ok", detail["state"])
        self.assertEqual("小王", detail["display_name"])
        self.assertEqual("阿哲", detail["profile"]["relation_address"])
        self.assertEqual(5, detail["total"])
        self.assertEqual(5, len(detail["memories"]))
        self.assertGreaterEqual(detail["weight"]["weight"], 1)
        self.assertEqual(5, detail["type_counts"].get("conversation_summary"))

    async def test_first_upgrade_seeds_people_without_new_chat(self) -> None:
        # 旧库升级后没人再说话，也不该让面板空着。
        await self.store.insert_memory(_record("old-1", user_id="old-user", content="以前的对话。"))
        seeded = self.store._seed_person_weights_if_empty_sync(10)
        self.assertEqual(1, seeded)
        data = await self.store.list_person_cards(bot_id=BOT_A)
        self.assertEqual(["old-user"], [item["user_id"] for item in data["items"]])
        self.assertGreaterEqual(data["items"][0]["weight"], 1)
        # 第二次调用不重复算
        self.assertEqual(0, self.store._seed_person_weights_if_empty_sync(10))

    async def test_person_detail_respects_limit(self) -> None:
        await self._seed()
        detail = await self.store.person_panel_detail(user_id="u1", bot_id=BOT_A, limit=2)
        self.assertEqual(2, len(detail["memories"]))
        self.assertEqual(5, detail["total"])


class PeoplePageApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(Path(self.temp.name) / "memory_companion.db")
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def _seed(self) -> None:
        await self.store.insert_memory(_record("m1", user_id="u1", content="她记得我。"))
        await self.store.person_weight(user_id="u1", platform=PLATFORM, bot_id=BOT_A)

    async def test_people_endpoint_returns_cards(self) -> None:
        await self._seed()
        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=self.store)))
        with patch.object(page_api_module, "request", SimpleNamespace(args={"limit": "10"})), patch.object(
            page_api_module, "jsonify", side_effect=_fake_jsonify
        ):
            response = await api.people()
        body = response.payload
        self.assertTrue(body["success"])
        self.assertEqual(1, body["total"])
        self.assertEqual("u1", body["items"][0]["user_id"])

    async def test_person_endpoint_requires_user_id(self) -> None:
        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=self.store)))
        with patch.object(page_api_module, "request", SimpleNamespace(args={})), patch.object(
            page_api_module, "jsonify", side_effect=_fake_jsonify
        ):
            response = await api.person()
        self.assertEqual(400, response.status_code)
        self.assertFalse(response.payload["success"])
        self.assertIn("user_id", response.payload["error"])

    async def test_weight_update_moves_weight_and_records_address(self) -> None:
        await self._seed()
        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=self.store)))
        payload = {
            "user_id": "u1",
            "bot_id": BOT_A,
            "weight": 7,
            "address": "阿哲",
            "label": "恋人",
        }
        api._json = AsyncMock(return_value=payload)
        with patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
            response = await api.person_weight_update()
        body = response.payload
        self.assertTrue(body["success"])
        self.assertTrue(body["profile_updated"])
        self.assertEqual(7, body["weight"]["weight"])
        self.assertEqual("user", body["weight"]["source"])
        self.assertEqual("阿哲", body["person"]["profile"]["relation_address"])

    async def test_combined_card_keeps_manual_relation_after_platform_updates(self) -> None:
        await self._seed()
        await self.store.person_weight(user_id="u1", platform="lark", bot_id=BOT_A)
        person = EntityRef(kind="user", id="u1", name="小王")
        await self.store.upsert_identity(
            platform="",
            entity=EntityRef(kind="user", id="u1"),
            profile={"relation_address": "旧称呼", "relation_source": "user", "marker": "保留"},
        )
        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=self.store)))

        async def save(**fields):
            api._json = AsyncMock(return_value={"user_id": "u1", "bot_id": BOT_A, **fields})
            with patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
                return (await api.person_weight_update()).payload

        first = await save(address="新称呼", label="朋友", note="保留这条")
        self.assertTrue(first["profile_updated"])
        self.assertEqual("新称呼", first["person"]["profile"]["relation_address"])
        second = await save(label="同事")
        self.assertTrue(second["profile_updated"])
        self.assertEqual("同事", second["person"]["profile"]["relation_label"])
        self.assertEqual("保留这条", second["person"]["profile"]["relation_note"])
        self.assertFalse((await save(weight=50))["profile_updated"])
        self.assertTrue((await save(address="", note=""))["profile_updated"])
        self.assertFalse((await save(address="", note=""))["profile_updated"])

        with patch("astrbot_plugin_memory_companion.core.store.utc_now", return_value="2099-01-01T00:00:00+00:00"):
            await self.store.upsert_identity(
                platform=PLATFORM,
                entity=person,
                aliases=["王同学"],
                profile={
                    "last_session": "recent-session",
                    "relation_address": "推断称呼",
                    "relation_note": "平台备注",
                    "relation_source": "context",
                },
            )

        detail = await self.store.person_panel_detail(user_id="u1", bot_id=BOT_A)
        self.assertEqual("小王", detail["display_name"])
        self.assertIn("王同学", detail["aliases"])
        self.assertEqual("recent-session", detail["profile"]["last_session"])
        self.assertEqual("user", detail["profile"]["relation_source"])
        self.assertEqual("同事", detail["profile"]["relation_label"])
        self.assertEqual("", detail["profile"]["relation_address"])
        self.assertEqual("", detail["profile"]["relation_note"])
        listing = await self.store.list_person_cards(bot_id=BOT_A, query="同事")
        card = listing["items"][0]
        self.assertEqual("小王", card["display_name"])
        self.assertEqual("同事", card["relation_label"])
        self.assertEqual("", card["address"])
        self.assertEqual("", card["relation_note"])
        stored = await self.store.identity_profile(platform="", entity=person)
        self.assertEqual("保留", stored["marker"])

        scoped = await save(platform=PLATFORM, address="平台新称呼")
        self.assertTrue(scoped["profile_updated"])
        self.assertEqual("小王", scoped["person"]["display_name"])
        self.assertEqual("平台新称呼", scoped["person"]["profile"]["relation_address"])
        self.assertEqual("平台备注", scoped["person"]["profile"]["relation_note"])
        self.assertEqual("recent-session", scoped["person"]["profile"]["last_session"])
        scoped_detail = await self.store.person_panel_detail(user_id="u1", platform=PLATFORM)
        self.assertIn("王同学", scoped_detail["aliases"])
        combined = await self.store.person_panel_detail(user_id="u1")
        self.assertEqual("", combined["profile"]["relation_address"])

    async def test_ui_preferences_defaults_to_people_panel(self) -> None:
        for value, expected in (("人物", "people"), ("控制台", "legacy"), ("三维终端", "modern")):
            plugin = SimpleNamespace(
                service=SimpleNamespace(config=ConfigView({"appearance": {"ui_style": value}}))
            )
            api = PluginPageApi(plugin)
            with patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
                response = await api.ui_preferences()
            self.assertEqual(expected, response.payload["ui_style"], value)

    async def test_ui_preferences_reports_whether_dark_mode_was_explicitly_saved(self) -> None:
        plugin = SimpleNamespace(
            service=SimpleNamespace(
                config=ConfigView({"appearance": {"ui_style": "人物"}}),
                data_dir=self.temp.name,
            )
        )
        api = PluginPageApi(plugin)
        with patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
            initial = (await api.ui_preferences()).payload
        self.assertTrue(initial["dark_mode"])
        self.assertFalse(initial["dark_mode_saved"])

        api._json = AsyncMock(return_value={"dark_mode": False})
        with patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
            saved = (await api.ui_preferences_save()).payload
            after_light = (await api.ui_preferences()).payload
        self.assertTrue(saved["success"])
        self.assertFalse(after_light["dark_mode"])
        self.assertTrue(after_light["dark_mode_saved"])

        api._json = AsyncMock(return_value={"dark_mode": True})
        with patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
            await api.ui_preferences_save()
            after_dark = (await api.ui_preferences()).payload
        self.assertTrue(after_dark["dark_mode"])
        self.assertTrue(after_dark["dark_mode_saved"])


def _extract_css_rules(css_text: str) -> list[tuple[str, str]]:
    """提取 CSS 规则（含 @media 内的嵌套规则），返回 [(selector, body), ...]。"""
    cleaned = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    rules: list[tuple[str, str]] = []

    def _walk(source: str) -> None:
        index = 0
        length = len(source)
        while index < length:
            brace = source.find("{", index)
            if brace == -1:
                break
            header = source[index:brace].strip()
            depth = 1
            cursor = brace + 1
            while cursor < length and depth > 0:
                ch = source[cursor]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                cursor += 1
            body = source[brace + 1 : cursor - 1].strip()
            if header.startswith("@"):
                _walk(body)
            elif header:
                for selector in header.split(","):
                    trimmed = selector.strip()
                    if trimmed:
                        rules.append((trimmed, body))
            index = cursor

    _walk(cleaned)
    return rules


def _match_css_compound(
    compound: str, node: tuple[str, str, set[str]]
) -> tuple[bool, set[str]]:
    """匹配单个 CSS 复合选择器，返回 (是否命中, 伪类集合)。"""
    if "::" in compound or "[" in compound:
        return False, set()
    tag, elem_id, classes = node
    parts = compound.split(":")
    base = parts[0]
    pseudos = {part for part in parts[1:] if part}
    if not base or "root" in pseudos:
        return False, set()
    if base == "*":
        return True, pseudos
    for token in re.findall(r"[#.][^#.]+|^[^#.]+", base):
        if token.startswith("#"):
            if elem_id != token[1:]:
                return False, set()
        elif token.startswith("."):
            if token[1:] not in classes:
                return False, set()
        elif tag != token.lower():
            return False, set()
    return True, pseudos


def _css_selector_matches_chain(
    selector: str, chain: list[tuple[str, str, set[str]]]
) -> tuple[bool, set[str]]:
    """判断 CSS 选择器（支持后代与直接子代 >）是否命中目标 DOM 祖先链。"""
    normalized = re.sub(r"\s*>\s*", " > ", selector.strip())
    raw_tokens = normalized.split()
    if not raw_tokens or not chain:
        return False, set()

    steps: list[tuple[str | None, str]] = []
    combinator: str | None = None
    for token in raw_tokens:
        if token == ">":
            combinator = ">"
        elif token in {"+", "~"}:
            return False, set()
        else:
            steps.append((combinator, token))
            combinator = " "

    matched_target, target_pseudos = _match_css_compound(steps[-1][1], chain[-1])
    if not matched_target:
        return False, set()

    def _match_prev(step_idx: int, node_idx: int) -> bool:
        if step_idx < 0:
            return True
        if node_idx < 0:
            return False
        comb = steps[step_idx + 1][0]
        comp = steps[step_idx][1]
        if comb == ">":
            ok, _ = _match_css_compound(comp, chain[node_idx])
            return ok and _match_prev(step_idx - 1, node_idx - 1)
        for ancestor_idx in range(node_idx, -1, -1):
            ok, _ = _match_css_compound(comp, chain[ancestor_idx])
            if ok and _match_prev(step_idx - 1, ancestor_idx - 1):
                return True
        return False

    if _match_prev(len(steps) - 2, len(chain) - 2):
        return True, target_pseudos
    return False, set()


class _DrawerStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str, set[str]]] = []
        self.close_chain: list[tuple[str, str, set[str]]] | None = None
        self.drawer_body_chain: list[tuple[str, str, set[str]]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        elem_id = attr_map.get("id") or ""
        classes = set((attr_map.get("class") or "").split())
        tag_lower = tag.lower()
        self.stack.append((tag_lower, elem_id, classes))
        if elem_id == "close" and "close" in classes:
            self.close_chain = list(self.stack)
        if elem_id == "drawerBody":
            self.drawer_body_chain = list(self.stack)
        if tag_lower in {"meta", "link", "input", "br", "hr", "img"}:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        while self.stack:
            if self.stack.pop()[0] == tag_lower:
                break


class PeoplePanelAssetsTests(unittest.TestCase):
    def test_entry_page_routes_to_all_three_panels(self) -> None:
        source = (PAGES / "index.html").read_text(encoding="utf-8")
        self.assertIn("./people.html", source)
        self.assertIn("./modern.html", source)
        self.assertIn("./legacy.html", source)
        self.assertIn("function styleTarget", source)
        self.assertIn('return "people";', source)

    def test_people_panel_loads_bridge_and_versioned_assets(self) -> None:
        html = (PAGES / "people.html").read_text(encoding="utf-8")
        self.assertIn("/api/plugin/page/bridge-sdk.js", html)
        version = re.search(
            r'PLUGIN_VERSION\s*=\s*"([^"]+)"', (ROOT / "main.py").read_text(encoding="utf-8")
        ).group(1)
        self.assertIn(f"./people.js?v={version}", html)
        self.assertIn(f"./people.css?v={version}", html)
        script = (PAGES / "people.js").read_text(encoding="utf-8")
        self.assertIn('const API = "/api/plug/astrbot_plugin_memory_companion/page";', script)
        self.assertIn('"people"', script)
        self.assertIn('"person/weight"', script)
        self.assertIn("让她忘掉这条", script)
        # 跨 bot / 平台的人点开详情时不能只带主行的过滤条件。
        self.assertIn("spansRows", script)

    def test_people_routes_and_exposure_are_registered(self) -> None:
        tree = ast.parse((ROOT / "page_api.py").read_text(encoding="utf-8"))
        paths = set()
        exposure = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_route_specs":
                paths = {
                    item.elts[0].value
                    for item in ast.walk(node)
                    if isinstance(item, ast.Tuple)
                    and item.elts
                    and isinstance(item.elts[0], ast.Constant)
                    and isinstance(item.elts[0].value, str)
                    and item.elts[0].value.startswith("/")
                }
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "UI_ENDPOINT_EXPOSURE"
                for target in node.targets
            ):
                exposure = ast.literal_eval(node.value)
        for route in ("/people", "/person", "/person/weight"):
            self.assertIn(route, paths)
            self.assertIn(route, exposure)
            self.assertEqual("internal", exposure[route]["exposure"])

    def test_people_close_button_selector_does_not_collide_with_close_band_chip(
        self,
    ) -> None:
        html = (PAGES / "people.html").read_text(encoding="utf-8")
        css = (PAGES / "people.css").read_text(encoding="utf-8")

        parser = _DrawerStructureParser()
        parser.feed(html)
        self.assertIsNotNone(parser.close_chain)
        self.assertIsNotNone(parser.drawer_body_chain)
        assert parser.close_chain is not None
        assert parser.drawer_body_chain is not None
        # 关闭按钮与内容容器都挂在 <aside id="drawer" class="drawer"> 直接子级。
        self.assertEqual(("aside", "drawer", {"drawer"}), parser.close_chain[-2])
        self.assertEqual(("aside", "drawer", {"drawer"}), parser.drawer_body_chain[-2])

        rules = _extract_css_rules(css)

        def matched_bodies(
            chain: list[tuple[str, str, set[str]]],
        ) -> tuple[str, str]:
            base_parts: list[str] = []
            hover_parts: list[str] = []
            for selector, body in rules:
                matched, pseudos = _css_selector_matches_chain(selector, chain)
                if not matched:
                    continue
                if not pseudos:
                    base_parts.append(body)
                elif "hover" in pseudos:
                    hover_parts.append(body)
            return "\n".join(base_parts), "\n".join(hover_parts)

        # 1) 抽屉关闭按钮仍完整命中定位、圆形尺寸与 hover 高亮样式。
        close_base, close_hover = matched_bodies(parser.close_chain)
        self.assertIn("position: absolute", close_base)
        self.assertIn("border-radius: 50%", close_base)
        self.assertIn("width: 34px", close_base)
        self.assertIn("border-color: var(--accent)", close_hover)

        # 2) 「亲近的人」徽章（.chip.band.close）无论在人卡内还是抽屉详情内，
        #    都只能命中徽章样式，不能被抽屉关闭按钮规则污染。
        card_close_badge = [
            ("section", "grid", {"grid"}),
            ("button", "", {"card"}),
            ("div", "", {"chips"}),
            ("span", "", {"chip", "band", "close"}),
        ]
        drawer_close_badge = parser.drawer_body_chain + [
            ("div", "", {"chips"}),
            ("span", "", {"chip", "band", "close"}),
        ]
        for label, badge_chain in (
            ("card", card_close_badge),
            ("drawer", drawer_close_badge),
        ):
            with self.subTest(location=label):
                badge_base, badge_hover = matched_bodies(badge_chain)
                self.assertIn("#9fe1bd", badge_base)
                self.assertIn("#0e1a12", badge_base)
                self.assertIn("border-radius: 999px", badge_base)
                self.assertNotIn("position: absolute", badge_base)
                self.assertNotIn("border-radius: 50%", badge_base)
                self.assertNotIn("font-size: 20px", badge_base)
                self.assertNotIn("border-color: var(--accent)", badge_hover)

    def test_schema_defaults_open_on_people_panel(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        style = schema["appearance"]["items"]["ui_style"]
        self.assertEqual("人物", style["default"])
        self.assertEqual(["人物", "控制台", "三维终端"], style["options"])
        self.assertTrue(schema["memory_humanization"]["items"]["enabled"]["default"])

    def test_people_css_is_tokenized_for_light_theme_palettes_and_danger_zone(self) -> None:
        css = (PAGES / "people.css").read_text(encoding="utf-8")
        rules = _extract_css_rules(css)

        # 1) 必须声明完整的浅色主题变量，并与完整控制台浅色质感对齐。
        light_bodies = [body for selector, body in rules if selector == ':root[data-theme="light"]']
        self.assertTrue(light_bodies, "people.css 缺少 :root[data-theme=\"light\"] 浅色色阶")
        light_block = "\n".join(light_bodies)
        for expected_token in (
            "color-scheme: light",
            "--bg: #f6f7fa",
            "--card: #ffffff",
            "--text: #1b2430",
            "--danger: #dc2626",
        ):
            self.assertIn(expected_token, light_block)

        # 2) 非令牌组件规则里不允许残留硬编码十六进制/rgba 颜色（var() 语义兜底除外）。
        hardcoded: list[str] = []
        for selector, body in rules:
            if ":root" in selector or "[data-palette=" in selector or "[data-theme=" in selector:
                continue
            without_var_fallbacks = re.sub(r"var\([^)]*\)", "", body)
            if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", without_var_fallbacks):
                hardcoded.append(selector)
        self.assertEqual([], hardcoded, f"people.css 组件规则仍含硬编码颜色：{hardcoded}")

        # 3) 14 套传统色在深/浅两态均已定义，且浅色块完整覆盖深色块全部变量避免泄漏。
        palettes = list(page_api_module.THEME_NAME_TO_KEY.values())
        self.assertEqual(14, len(palettes))
        dark_props: dict[str, set[str]] = {}
        light_props: dict[str, set[str]] = {}
        for selector, body in rules:
            props = set(re.findall(r"(--[a-z0-9-]+)\s*:", body))
            m_light = re.fullmatch(r':root\[data-palette="([a-z]+)"\]\[data-theme="light"\]', selector)
            m_dark = re.fullmatch(r':root\[data-palette="([a-z]+)"\]', selector)
            if m_light:
                light_props[m_light.group(1)] = props
            elif m_dark:
                dark_props[m_dark.group(1)] = props
        people_js = (PAGES / "people.js").read_text(encoding="utf-8")
        for key in palettes:
            self.assertIn(key, dark_props, f"people.css 缺少深色色板 {key}")
            self.assertIn(key, light_props, f"people.css 缺少浅色色板 {key}")
            leaked = dark_props[key] - light_props[key]
            self.assertEqual(set(), leaked, f"people.css 色板 {key} 浅色块漏覆盖变量：{leaked}")
            self.assertRegex(people_js, rf'"{key}"', f"people.js 的色板白名单缺少 {key}")

        # 4) 补齐危险区（.block.danger / button.danger）与主题切换按钮样式。
        selectors = {selector for selector, _body in rules}
        self.assertIn(".block.danger", selectors)
        self.assertTrue(any("button.danger" in selector for selector in selectors))
        self.assertIn(".theme-btn", selectors)

    def test_people_panel_does_not_rely_on_sandbox_blocked_web_storage(self) -> None:
        html = (PAGES / "people.html").read_text(encoding="utf-8")
        script = (PAGES / "people.js").read_text(encoding="utf-8")
        for label, source in (("people.html", html), ("people.js", script)):
            self.assertNotIn("localStorage", source, f"{label} 不应依赖沙箱禁用的 localStorage")
            self.assertNotIn("sessionStorage", source, f"{label} 不应依赖沙箱禁用的 sessionStorage")

    def test_people_html_first_frame_theme_script_and_toggle_controls(self) -> None:
        html = (PAGES / "people.html").read_text(encoding="utf-8")
        self.assertIn('id="themeToggle"', html)
        self.assertIn('id="themeToggleLabel"', html)
        self.assertIn('data-console-link href="./legacy.html"', html)
        self.assertLess(
            html.index('URLSearchParams(location.search).get("theme")'),
            html.index('rel="stylesheet"'),
            "防闪烁主题初始化脚本必须位于样式表之前",
        )

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is needed only for the first-frame theme script check")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const m = html.match(/<head>[\s\S]*?<script>([\s\S]*?)<\/script>[\s\S]*?<\/head>/i);
if (!m) throw new Error("missing inline head script");
const script = m[1];
function run({ search = "", preset = "", preferLight = false }) {
  const root = { dataset: preset ? { theme: preset } : {} };
  let metaContent = "#0f1218";
  const ctx = vm.createContext({
    location: { search },
    URLSearchParams,
    document: {
      documentElement: root,
      querySelector(sel) {
        if (sel === 'meta[name="theme-color"]') {
          return { setAttribute(name, val) { if (name === "content") metaContent = val; } };
        }
        return null;
      },
    },
    window: {
      matchMedia: (q) => ({ matches: preferLight && String(q).includes("light") }),
      get localStorage() { throw new Error("SecurityError"); },
      get sessionStorage() { throw new Error("SecurityError"); },
    },
  });
  vm.runInContext(script, ctx);
  return { theme: root.dataset.theme, metaContent };
}
process.stdout.write(JSON.stringify({
  queryLight: run({ search: "?theme=light&asset_token=tok", preferLight: false }),
  queryDark: run({ search: "?theme=dark&asset_token=tok", preferLight: true }),
  preferLight: run({ search: "?asset_token=tok", preferLight: true }),
  fallbackDark: run({ search: "", preferLight: false }),
  presetLight: run({ search: "", preset: "light", preferLight: false }),
}));
"""
        raw = subprocess.run(
            [node, "-e", code, str(PAGES / "people.html")],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        out = json.loads(raw)
        self.assertEqual({"theme": "light", "metaContent": "#f6f7fa"}, out["queryLight"])
        self.assertEqual({"theme": "dark", "metaContent": "#0f1218"}, out["queryDark"])
        self.assertEqual({"theme": "light", "metaContent": "#f6f7fa"}, out["preferLight"])
        self.assertEqual({"theme": "dark", "metaContent": "#0f1218"}, out["fallbackDark"])
        self.assertEqual({"theme": "light", "metaContent": "#f6f7fa"}, out["presetLight"])

    def test_people_js_preferences_bridge_sync_and_search_passthrough(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is needed only for the people.js behavior check")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");

async function runScenario({ search, prefs, initialHostIsDark }) {
  const nodes = {};
  const makeNode = (id) => {
    const attrs = {};
    const listeners = {};
    return {
      id,
      hidden: false,
      innerHTML: "",
      textContent: "",
      value: "",
      attrs,
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      dispatch(type, evt) { (listeners[type] || []).forEach((fn) => fn(evt || {})); },
      setAttribute(k, v) { attrs[k] = String(v); },
      getAttribute(k) { return attrs[k]; },
      querySelectorAll() { return []; },
      focus() {},
    };
  };
  const topLink = makeNode("consoleLink");
  topLink.setAttribute("href", "./legacy.html");
  const emptyLink = makeNode("emptyConsoleLink");
  emptyLink.setAttribute("href", "./legacy.html");
  nodes.consoleLink = topLink;

  const root = { dataset: {} };
  let metaColor = "#0f1218";
  const posts = [];
  let contextCb = null;
  const bridge = {
    onContext(fn) {
      contextCb = fn;
      if (typeof initialHostIsDark === "boolean") {
        root.dataset.theme = initialHostIsDark ? "dark" : "light";
        fn({ isDark: initialHostIsDark });
      }
      return () => {};
    },
    apiGet(endpoint) {
      if (endpoint === "page/ui-preferences") return Promise.resolve({ success: true, data: prefs });
      if (endpoint === "page/ui/csrf") return Promise.resolve({ success: true, data: { token: "csrf-1", expires_in: 900 } });
      if (endpoint === "page/people") return Promise.resolve({ success: true, data: { items: [], bots: [], total: 0 } });
      if (endpoint === "page/maintenance/summary_status") return Promise.resolve({ success: true, data: { status: null } });
      return Promise.resolve({ success: true, data: {} });
    },
    apiPost(endpoint, body) {
      posts.push({ endpoint, body });
      return Promise.resolve({ success: true, data: { dark_mode: body.dark_mode } });
    },
  };

  const ctx = vm.createContext({
    location: { search, origin: "null" },
    URLSearchParams,
    setTimeout,
    clearTimeout,
    document: {
      documentElement: root,
      getElementById(id) { return nodes[id] || (nodes[id] = makeNode(id)); },
      querySelector(sel) {
        if (sel === 'meta[name="theme-color"]') {
          return { setAttribute(k, v) { if (k === "content") metaColor = v; } };
        }
        return null;
      },
      querySelectorAll(sel) {
        if (sel.includes("data-console-link")) return [topLink, emptyLink];
        return [];
      },
      addEventListener() {},
    },
    window: {
      AstrBotPluginPage: bridge,
      addEventListener() {},
      confirm: () => false,
      get localStorage() { throw new Error("SecurityError"); },
      get sessionStorage() { throw new Error("SecurityError"); },
    },
  });
  vm.runInContext(source, ctx);
  await new Promise((r) => setTimeout(r, 30));

  const afterBoot = {
    theme: root.dataset.theme,
    palette: root.dataset.palette || "",
    metaColor,
    toggleLabel: nodes.themeToggleLabel.textContent,
    topHref: topLink.attrs.href,
    emptyHref: emptyLink.attrs.href,
    emptyHtml: nodes.empty.innerHTML,
    postCount: posts.length,
  };

  // 宿主实时切换深浅模式
  if (contextCb) {
    const nextDark = !(typeof initialHostIsDark === "boolean" ? initialHostIsDark : false);
    root.dataset.theme = nextDark ? "dark" : "light";
    contextCb({ isDark: nextDark });
  }
  const afterHostToggle = {
    theme: root.dataset.theme,
    toggleLabel: nodes.themeToggleLabel.textContent,
    topHref: topLink.attrs.href,
    postCount: posts.length,
  };

  // 手动点击人物页顶部主题切换按钮 -> 调用 POST /ui-preferences/save
  nodes.themeToggle.dispatch("click");
  await new Promise((r) => setTimeout(r, 30));
  const afterManualToggle = {
    theme: root.dataset.theme,
    toggleLabel: nodes.themeToggleLabel.textContent,
    topHref: topLink.attrs.href,
    posts,
  };

  return { afterBoot, afterHostToggle, afterManualToggle };
}

(async () => {
  const hostLightUnsaved = await runScenario({
    search: "?theme=light&asset_token=tok999",
    prefs: { palette: "yuebai", dark_mode: true, dark_mode_saved: false },
    initialHostIsDark: false,
  });
  const explicitLightSaved = await runScenario({
    search: "?theme=dark&asset_token=tok888",
    prefs: { palette: "tianpiao", dark_mode: false, dark_mode_saved: true },
    initialHostIsDark: true,
  });
  process.stdout.write(JSON.stringify({ hostLightUnsaved, explicitLightSaved }));
})();
"""
        raw = subprocess.run(
            [node, "-e", code, str(PAGES / "people.js")],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        out = json.loads(raw)

        # 场景 1：宿主浅色 + 后端尚未显式保存偏好 -> 保持浅色并同步色板，透传参数。
        s1 = out["hostLightUnsaved"]
        self.assertEqual("light", s1["afterBoot"]["theme"])
        self.assertEqual("yuebai", s1["afterBoot"]["palette"])
        self.assertEqual("#f6f7fa", s1["afterBoot"]["metaColor"])
        self.assertEqual("浅色", s1["afterBoot"]["toggleLabel"])
        self.assertEqual("./legacy.html?theme=light&asset_token=tok999", s1["afterBoot"]["topHref"])
        self.assertEqual("./legacy.html?theme=light&asset_token=tok999", s1["afterBoot"]["emptyHref"])
        self.assertIn('href="./legacy.html?theme=light&amp;asset_token=tok999"', s1["afterBoot"]["emptyHtml"])
        self.assertEqual(0, s1["afterBoot"]["postCount"])

        # 宿主实时切换 -> 立即切到深色，不发无谓写请求。
        self.assertEqual("dark", s1["afterHostToggle"]["theme"])
        self.assertEqual("深色", s1["afterHostToggle"]["toggleLabel"])
        self.assertEqual("./legacy.html?theme=dark&asset_token=tok999", s1["afterHostToggle"]["topHref"])
        self.assertEqual(0, s1["afterHostToggle"]["postCount"])

        # 手动点击按钮 -> 切回浅色并持久化到 /ui-preferences/save。
        self.assertEqual("light", s1["afterManualToggle"]["theme"])
        self.assertEqual("浅色", s1["afterManualToggle"]["toggleLabel"])
        self.assertEqual("./legacy.html?theme=light&asset_token=tok999", s1["afterManualToggle"]["topHref"])
        self.assertEqual(1, len(s1["afterManualToggle"]["posts"]))
        self.assertEqual("page/ui-preferences/save", s1["afterManualToggle"]["posts"][0]["endpoint"])
        self.assertIs(False, s1["afterManualToggle"]["posts"][0]["body"]["dark_mode"])
        self.assertEqual("csrf-1", s1["afterManualToggle"]["posts"][0]["body"]["csrf_token"])

        # 场景 2：用户在控制台显式保存了浅色偏好 -> 即使宿主初始暗色，人物页也同步恢复浅色与色板。
        s2 = out["explicitLightSaved"]
        self.assertEqual("light", s2["afterBoot"]["theme"])
        self.assertEqual("tianpiao", s2["afterBoot"]["palette"])
        self.assertEqual("./legacy.html?theme=light&asset_token=tok888", s2["afterBoot"]["topHref"])

    def test_legacy_console_provides_people_entries_and_preserves_search_params(self) -> None:
        legacy_html = (PAGES / "legacy.html").read_text(encoding="utf-8")
        app_js = (PAGES / "app.js").read_text(encoding="utf-8")

        # 1) 完整控制台静态外壳在左侧 .rail-nav 与顶部 .topbar-tools 均有返回「她记得的人」入口。
        self.assertIn('id="railPeopleLink" data-people-link href="./people.html"', legacy_html)
        self.assertIn('id="topbarPeopleLink" data-people-link href="./people.html"', legacy_html)
        self.assertIn('URLSearchParams(location.search).get("theme")', legacy_html)

        # 2) 运行 app.js 验证侧栏渲染、总览「六个常用工作区」6 张卡片与 location.search 全链路透传。
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is needed only for the app.js console nav check")
        code = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const railHost = { innerHTML: "" };
const topbarLink = { attrs: { href: "./people.html" }, setAttribute(k, v) { this.attrs[k] = String(v); } };
const root = { dataset: { theme: "light" } };
const ctx = vm.createContext({
  location: { search: "?theme=light&asset_token=tok777" },
  URLSearchParams,
  CustomEvent: function CustomEvent(type, init) { this.type = type; this.detail = init && init.detail; },
  document: {
    documentElement: root,
    readyState: "loading",
    addEventListener() {},
    querySelector(sel) {
      if (sel === "#railNav") return railHost;
      if (sel === "#themeToggleLabel") return { textContent: "" };
      return null;
    },
    querySelectorAll(sel) {
      if (sel.includes("data-people-link")) return [topbarLink];
      return [];
    },
  },
  window: { addEventListener() {}, dispatchEvent() {} },
});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const inner = vm.runInContext(`(() => {
  renderRail();
  const overviewHtml = VIEWS.overview.render({ stats: {}, buckets: [], core: [], caps: {}, personal: {}, coord: {}, memories: [], injectionLogs: [], bots: [] });
  const lightHref = peopleHref();
  applyTheme("dark", { persist: false });
  const darkHref = peopleHref();
  return { overviewHtml, lightHref, darkHref };
})()`, ctx);
process.stdout.write(JSON.stringify({
  railHtml: railHost.innerHTML,
  overviewHtml: inner.overviewHtml,
  lightHref: inner.lightHref,
  darkHref: inner.darkHref,
  syncedTopbarHref: topbarLink.attrs.href,
}));
"""
        raw = subprocess.run(
            [node, "-e", code, str(PAGES / "app.js")],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        data = json.loads(raw)
        self.assertIn("她记得的人", data["railHtml"])
        self.assertIn('href="./people.html?theme=light&amp;asset_token=tok777"', data["railHtml"])
        self.assertEqual("./people.html?theme=light&asset_token=tok777", data["lightHref"])
        self.assertEqual("./people.html?theme=dark&asset_token=tok777", data["darkHref"])
        self.assertEqual("./people.html?theme=dark&asset_token=tok777", data["syncedTopbarHref"])

        # 核对总览「功能入口」副标题「六个常用工作区」与实际渲染卡片数量严格一致（6 张卡）。
        overview = data["overviewHtml"]
        self.assertIn("六个常用工作区", overview)
        m = re.search(r'<h3>功能入口</h3><div class="card-sub">六个常用工作区</div></div></div><div class="row-list">(.*?)</div></section>', overview)
        self.assertIsNotNone(m, "找不到总览「功能入口」卡片")
        entry_rows = re.findall(r'<(?:a|button)\s+class="row"', m.group(1))
        self.assertEqual(6, len(entry_rows), f"「六个常用工作区」应渲染 6 个入口，实际 {len(entry_rows)}")
        self.assertIn('href="./people.html?theme=light&amp;asset_token=tok777"', m.group(1))
        self.assertIn("她记得的人", m.group(1))
        self.assertIn("peopleHref", app_js)


if __name__ == "__main__":
    unittest.main()
