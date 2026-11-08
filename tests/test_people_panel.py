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

    def test_schema_defaults_open_on_people_panel(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        style = schema["appearance"]["items"]["ui_style"]
        self.assertEqual("人物", style["default"])
        self.assertEqual(["人物", "控制台", "三维终端"], style["options"])
        self.assertTrue(schema["memory_humanization"]["items"]["enabled"]["default"])


if __name__ == "__main__":
    unittest.main()
