# -*- coding: utf-8 -*-
"""2.5：她记得的人——人物面板（store 目录/单人详情/改称呼与分量）。"""
from __future__ import annotations

import ast
import importlib
import json
import re
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

    async def test_ui_preferences_defaults_to_people_panel(self) -> None:
        for value, expected in (("人物", "people"), ("控制台", "legacy"), ("三维终端", "modern")):
            plugin = SimpleNamespace(
                service=SimpleNamespace(config=ConfigView({"appearance": {"ui_style": value}}))
            )
            api = PluginPageApi(plugin)
            with patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
                response = await api.ui_preferences()
            self.assertEqual(expected, response.payload["ui_style"], value)


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


if __name__ == "__main__":
    unittest.main()
