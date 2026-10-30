# -*- coding: utf-8 -*-
"""2.6.0：面板路由授权分档、危险操作确认、访问审计与人物擦除。

这些测试不启动 Web 服务：直接把 _wrap_route 产出的包装函数当端点调用，
用假的 plugin/store 与假的 request/jsonify 检查行为是否合规。
"""
from __future__ import annotations

import ast
import importlib
import json
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

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi

PAGE_API_PATH = ROOT / "page_api.py"
PAGES = ROOT / "pages" / "记忆面板"

# 这两个端点一条路由两种语义：GET 只看状态，POST 才真的动数据。
DUAL_METHOD_ROUTES = {"/maintenance/sleep", "/operations/preset"}
POLICIES = {"read", "write", "dangerous"}


class _FakeResponse:
    """jsonify 的替身：有 status_code，也能取回 payload。"""

    status_code = 200

    def __init__(self, payload) -> None:
        self.payload = payload


def _fake_jsonify(payload=None, **kwargs):
    return _FakeResponse(payload if payload is not None else kwargs)


def route_specs() -> dict[str, tuple[list[str], str]]:
    """用 AST 读 _route_specs：路由 -> (方法列表, handler 名)，不执行插件入口。"""
    tree = ast.parse(PAGE_API_PATH.read_text(encoding="utf-8"))
    specs: dict[str, tuple[list[str], str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "_route_specs"):
            continue
        for item in ast.walk(node):
            if not (isinstance(item, ast.Tuple) and item.elts):
                continue
            first = item.elts[0]
            if not (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value.startswith("/")
            ):
                continue
            handler = item.elts[1]
            name = handler.attr if isinstance(handler, ast.Attribute) else str(getattr(handler, "id", ""))
            methods = [
                element.value
                for element in item.elts[2].elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
            specs[first.value] = (methods, name)
    return specs


def make_record(memory_id: str, user_id: str = "u1") -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        memory_type="conversation_summary",
        subject=EntityRef(kind="user", id=user_id),
        object=EntityRef(kind="bot", id="bot-a"),
        platform="qq",
        scope="private",
        visibility="private_pair",
        lifecycle="stable_memory",
        owner_bot_id="bot-a",
        content=f"和她说过的第 {memory_id} 件事。",
    )


def fake_store(**overrides):
    store = SimpleNamespace(
        list_memories=AsyncMock(return_value=[]),
        get_memory=AsyncMock(return_value=None),
        delete_memory=AsyncMock(return_value=True),
        erase_person_data=AsyncMock(
            return_value={"ok": True, "user_id": "u1", "deleted": {"memories": 3}}
        ),
        stats=AsyncMock(return_value={"memories": 5, "people": 2}),
        summary_progress=AsyncMock(return_value={}),
        set_person_weight=AsyncMock(return_value=None),
        identity_profile=AsyncMock(return_value={}),
        upsert_identity=AsyncMock(return_value=None),
        person_panel_detail=AsyncMock(
            return_value={
                "display_name": "u1",
                "weight": {"weight": 7},
                "profile": {"relation_address": "阿哲"},
            }
        ),
    )
    for key, value in overrides.items():
        setattr(store, key, value)
    return store


def make_api(data_dir="", store=None):
    plugin = SimpleNamespace(
        service=SimpleNamespace(store=store or fake_store(), data_dir=str(data_dir))
    )
    return PluginPageApi(plugin)


def make_request(args=None, method="GET", payload=None):
    return SimpleNamespace(
        args=args or {},
        method=method,
        get_json=AsyncMock(return_value=payload if payload is not None else {}),
    )


async def call_route(api, route, *, args=None, method=None, payload=None):
    """经统一包装层调用一条路由，模拟真实 Web 请求。"""
    specs = route_specs()
    methods, handler_name = specs[route]
    handler = getattr(api, handler_name)
    guarded = api._wrap_route(route, handler)
    fake_request = make_request(
        args=args,
        method=method or (methods[0] if methods else "GET"),
        payload=payload,
    )
    with patch.object(page_api_module, "request", fake_request), patch.object(
        page_api_module, "jsonify", side_effect=_fake_jsonify
    ):
        return await guarded()


class PanelPolicyTests(unittest.IsolatedAsyncioTestCase):
    def test_every_registered_route_has_an_explicit_policy(self) -> None:
        specs = route_specs()
        self.assertGreater(len(specs), 60)
        api = make_api()
        read = page_api_module.UI_READ_ENDPOINTS
        write = page_api_module.UI_WRITE_ENDPOINTS
        dangerous = page_api_module.UI_DANGEROUS_ENDPOINTS
        for route, (methods, _handler) in specs.items():
            with self.subTest(route=route):
                self.assertIn(route, read | write | dangerous)
                for method in methods or ["GET"]:
                    policy = api._endpoint_policy(route, method)["policy"]
                    self.assertIn(policy, POLICIES)
                    self.assertTrue(api._endpoint_policy(route, method)["reason"])

    def test_unknown_route_fails_closed_as_dangerous(self) -> None:
        api = make_api()
        policy = api._endpoint_policy("/definitely-not-registered", "POST")
        self.assertEqual("dangerous", policy["policy"])
        self.assertTrue(policy["reason"])

    def test_write_and_dangerous_routes_are_not_reachable_by_get(self) -> None:
        specs = route_specs()
        api = make_api()
        for route, (methods, _handler) in specs.items():
            with self.subTest(route=route):
                if "GET" not in methods:
                    continue
                if route in DUAL_METHOD_ROUTES:
                    # 双语义路由：GET 只读，POST 才写。
                    self.assertEqual("read", api._endpoint_policy(route, "GET")["policy"])
                    self.assertEqual("write", api._endpoint_policy(route, "POST")["policy"])
                else:
                    self.assertEqual("read", api._endpoint_policy(route, "GET")["policy"])
                    self.assertNotIn(
                        api._endpoint_policy(route, "GET")["policy"],
                        {"write", "dangerous"},
                    )
        for route in page_api_module.UI_DANGEROUS_ENDPOINTS:
            self.assertIn(route, specs, route)
            self.assertNotIn("GET", specs[route][0], route)

    async def test_ui_capabilities_exposes_policy_for_every_endpoint(self) -> None:
        api = make_api()
        with patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify):
            response = await api.ui_capabilities()
        endpoints = response.payload["endpoints"]
        self.assertTrue(endpoints)
        for endpoint in endpoints:
            self.assertIn(endpoint["policy"], POLICIES)

    async def test_every_dangerous_route_rejects_without_confirm(self) -> None:
        api = make_api()
        for route in sorted(page_api_module.UI_DANGEROUS_ENDPOINTS):
            with self.subTest(route=route):
                response = await call_route(api, route, method="POST", payload={})
                self.assertEqual(400, response.status_code)
                self.assertEqual("confirm_required", response.payload["error"])
                self.assertFalse(response.payload["success"])

    async def test_wrong_confirm_is_rejected(self) -> None:
        api = make_api()
        response = await call_route(
            api,
            "/person/erase",
            method="POST",
            payload={"user_id": "u1", "confirm": "ERASE:someone-else"},
        )
        self.assertEqual(400, response.status_code)
        self.assertEqual("confirm_required", response.payload["error"])


class PanelDataGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_memories_requires_scope_or_entity_id(self) -> None:
        api = make_api()
        response = await call_route(api, "/memories", args={"limit": "50"}, method="GET")
        self.assertEqual(400, response.status_code)
        self.assertIn("scope", response.payload["error"])
        self.assertIn("entity_id", response.payload["error"])

    async def test_memories_limit_is_capped_and_offset_is_forwarded(self) -> None:
        records = [make_record(f"m{index}") for index in range(300)]
        store = fake_store(list_memories=AsyncMock(return_value=records))
        api = make_api(store=store)
        response = await call_route(
            api,
            "/memories",
            args={"scope": "private", "limit": "999", "offset": "20"},
            method="GET",
        )
        self.assertTrue(response.payload["success"])
        self.assertLessEqual(len(response.payload["memories"]), 200)
        kwargs = store.list_memories.await_args.kwargs
        self.assertLessEqual(kwargs["limit"], 400)  # 取 2×上限做来源过滤，最终切片 ≤200
        self.assertEqual(20, kwargs["offset"])

    async def test_memories_accepts_entity_id_without_scope(self) -> None:
        store = fake_store()
        api = make_api(store=store)
        response = await call_route(api, "/memories", args={"entity_id": "u1"}, method="GET")
        self.assertTrue(response.payload["success"])
        kwargs = store.list_memories.await_args.kwargs
        self.assertEqual("u1", kwargs["entity_id"])

    async def test_memory_detail_hides_evidence_by_default(self) -> None:
        record = make_record("m1")
        record.evidence = "她原话的原文"
        store = fake_store(get_memory=AsyncMock(return_value=record))
        api = make_api(store=store)
        response = await call_route(api, "/memory", args={"id": "m1"}, method="GET")
        memory = response.payload["memory"]
        self.assertNotIn("evidence", memory)
        response = await call_route(
            api, "/memory", args={"id": "m1", "include_evidence": "1"}, method="GET"
        )
        self.assertEqual("她原话的原文", response.payload["memory"]["evidence"])

    async def test_memory_delete_reports_missing_memory(self) -> None:
        store = fake_store(delete_memory=AsyncMock(return_value=False))
        api = make_api(store=store)
        response = await call_route(
            api,
            "/memory/delete",
            method="POST",
            payload={"id": "m404", "confirm": "DELETE:m404"},
        )
        self.assertEqual(404, response.status_code)
        self.assertFalse(response.payload["success"])

    async def test_person_weight_rejects_invalid_input(self) -> None:
        api = make_api()
        confirm = "CONFIRM:/person/weight"
        for weight in (101, -1, 7.5, "7.5", "abc", True):
            with self.subTest(weight=weight):
                response = await call_route(
                    api,
                    "/person/weight",
                    method="POST",
                    payload={"user_id": "u1", "weight": weight, "confirm": confirm},
                )
                self.assertEqual(400, response.status_code)
        too_long = {
            "address": "阿" * 41,
            "label": "恋" * 41,
            "note": "注" * 81,
        }
        for field, value in too_long.items():
            with self.subTest(field=field):
                payload = {"user_id": "u1", "weight": 7, "confirm": confirm, field: value}
                response = await call_route(api, "/person/weight", method="POST", payload=payload)
                self.assertEqual(400, response.status_code)

    async def test_person_erase_requires_confirm_and_calls_store(self) -> None:
        store = fake_store()
        api = make_api(store=store)
        response = await call_route(
            api, "/person/erase", method="POST", payload={"user_id": "u1"}
        )
        self.assertEqual(400, response.status_code)
        self.assertEqual("confirm_required", response.payload["error"])
        self.assertEqual(0, store.erase_person_data.await_count)

        response = await call_route(
            api,
            "/person/erase",
            method="POST",
            payload={"user_id": "u1", "confirm": "ERASE:u1"},
        )
        self.assertTrue(response.payload["success"])
        store.erase_person_data.assert_awaited_once_with(
            user_id="u1", platform="", bot_id=""
        )
        self.assertEqual(3, response.payload["data"]["deleted"]["memories"])

    async def test_person_erase_reports_store_failure(self) -> None:
        store = fake_store(
            erase_person_data=AsyncMock(return_value={"ok": False, "code": "not_found"})
        )
        api = make_api(store=store)
        response = await call_route(
            api,
            "/person/erase",
            method="POST",
            payload={"user_id": "u1", "confirm": "ERASE:u1"},
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("not_found", response.payload["error"])


class PanelAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_access_log_records_every_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            api = make_api(data_dir=temp)
            await call_route(api, "/stats", method="GET")
            await call_route(
                api, "/person/erase", method="POST", payload={"user_id": "u1"}
            )
            log_path = Path(temp) / "page_access.log"
            self.assertTrue(log_path.exists())
            lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(lines))
            self.assertEqual("/stats", lines[0]["route"])
            self.assertEqual("read", lines[0]["policy"])
            self.assertEqual("ok", lines[0]["outcome"])
            self.assertEqual("/person/erase", lines[1]["route"])
            self.assertEqual("dangerous", lines[1]["policy"])
            self.assertEqual("confirm_required", lines[1]["outcome"])
            self.assertEqual("u1", lines[1]["target"])
            for line in lines:
                self.assertIn("ts", line)
                self.assertIn("method", line)

    async def test_page_access_log_rotates_when_too_big(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            api = make_api(data_dir=temp)
            await call_route(api, "/stats", method="GET")
            with patch.object(page_api_module, "PAGE_ACCESS_LOG_ROTATE_BYTES", 1):
                await call_route(api, "/stats", method="GET")
            data_dir = Path(temp)
            self.assertTrue((data_dir / "page_access.log").exists())
            self.assertTrue((data_dir / "page_access.log.1").exists())

    async def test_audit_failure_never_breaks_the_request(self) -> None:
        api = make_api(data_dir="")
        response = await call_route(api, "/stats", method="GET")
        self.assertTrue(response.payload["success"])


class PanelFrontendTests(unittest.TestCase):
    def test_people_panel_offers_erase_with_confirmation(self) -> None:
        script = (PAGES / "people.js").read_text(encoding="utf-8")
        self.assertIn("person/erase", script)
        self.assertIn("ERASE:", script)
        self.assertIn("eraseConfirmInput", script)
        self.assertIn("擦掉这个人的一切", script)

    def test_app_sends_canonical_confirmation_tokens(self) -> None:
        script = (PAGES / "app.js").read_text(encoding="utf-8")
        self.assertIn("withConfirmation", script)
        self.assertIn('"DELETE:"', script)
        self.assertIn('"CLEAR:all"', script)
        self.assertIn('"CONFIRM:" + route', script)
        self.assertIn("scope=all", script)


if __name__ == "__main__":
    unittest.main()
