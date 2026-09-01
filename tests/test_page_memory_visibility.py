# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")
    quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = quart_stub

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi


class PageMemoryVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_regular_memory_list_excludes_bot_personal_bridge_placeholders(self) -> None:
        records = [
            SimpleNamespace(source_plugin="bot_personal_bridge", id="placeholder"),
            SimpleNamespace(source_plugin="memory_companion", id="real"),
        ]
        store = SimpleNamespace(list_memories=AsyncMock(return_value=records))
        plugin = SimpleNamespace(service=SimpleNamespace(store=store))
        api = PluginPageApi(plugin)
        request = SimpleNamespace(args={"limit": "50"})

        with (
            patch.object(page_api_module, "request", request),
            patch.object(page_api_module, "serialize_memory", side_effect=lambda record: {"id": record.id}),
            patch.object(page_api_module, "jsonify", side_effect=lambda body: body),
        ):
            response = await api.memories()

        self.assertEqual([{"id": "real"}], response["memories"])
        self.assertEqual("bot_personal_bridge", store.list_memories.await_args.kwargs["source_plugin_exclude"])

    async def test_personal_page_projects_bot_personal_schedule_payloads(self) -> None:
        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=SimpleNamespace())))
        date = "2026-09-01"
        detail = SimpleNamespace(
            id="detail-1",
            visibility="bot_self",
            memory_type="bot_detail_fragment",
            tags=["bot_personal"],
            content="Bot Personal archive reference [bot_detail_fragment]",
            metadata={
                "payload": {
                    "date": date,
                    "start": "09:00",
                    "end": "10:00",
                    "summary": "在图书馆整理笔记",
                    "events": ["整理课程笔记"],
                    "proactive_events": ["提醒朋友带资料"],
                }
            },
            occurred_at=f"{date}T09:00:00+08:00",
            created_at="",
        )
        plan = SimpleNamespace(
            id="plan-1",
            visibility="bot_self",
            memory_type="bot_schedule_plan",
            tags=["bot_personal"],
            content="Bot Personal archive reference [bot_schedule_plan]",
            metadata={
                "payload": {
                    "date": date,
                    "items": [{"time": "09:00", "activity": "整理笔记", "mood": "专注"}],
                }
            },
            occurred_at=f"{date}T08:00:00+08:00",
            created_at="",
        )

        details = api._schedule_memory_details([detail], date, {"items": []})
        projected_plan = api._schedule_memory_plan_for_date([plan], date)

        self.assertEqual("在图书馆整理笔记", details[0]["summary"])
        self.assertEqual(["整理课程笔记"], details[0]["today_events"])
        self.assertEqual(["提醒朋友带资料"], details[0]["proactive_events"])
        self.assertEqual("整理笔记", projected_plan["items"][0]["activity"])

    async def test_personal_page_projects_bot_media_payload_photo(self) -> None:
        api = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=SimpleNamespace())))
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "photo.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
            record = SimpleNamespace(
                id="media-1",
                visibility="bot_self",
                memory_type="bot_media_memory",
                tags=["bot_personal"],
                source_plugin="bot_personal_bridge",
                content="Bot Personal archive reference [bot_media_memory]",
                metadata={
                    "payload": {
                        "date": "2026-09-01",
                        "image_path": str(image_path),
                        "prompt": "图书馆窗边自拍",
                    }
                },
                occurred_at="2026-09-01T09:00:00+08:00",
                created_at="",
            )
            producer = SimpleNamespace(data_dir=directory, plugin_data_dir=directory, data_file="")

            album = api._private_companion_album({}, "2026-09-01", [record], plugin=producer)

        self.assertEqual(1, len(album))
        self.assertTrue(album[0]["exists"])
        self.assertEqual("图书馆窗边自拍", album[0]["prompt"])
