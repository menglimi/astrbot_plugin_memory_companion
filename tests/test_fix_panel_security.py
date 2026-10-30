# -*- coding: utf-8 -*-
"""2.6.0 页面安全基线回归：P8 / P7 / P9 / P10 / P13 / P4 / A6。

这些测试不启动 Web 服务，直接调用 _wrap_route 产出的包装函数，用假的
plugin/service/store 与假的 request/jsonify 校验真实行为。
"""
from __future__ import annotations

import ast
import importlib
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi

PAGE_API_PATH = ROOT / "page_api.py"
BROWSER_HEADERS = {"Origin": "http://127.0.0.1:6185"}

# 一个必然成功的写路由（/acl/upsert）及其合法载荷，用来验证写档校验。
WRITE_ROUTE = "/acl/upsert"
WRITE_PAYLOAD = {
    "owner_scope": "private",
    "owner_id": "u1",
    "reader_scope": "group",
    "reader_id": "g1",
    "effect": "allow",
}


class _FakeResponse:
    status_code = 200

    def __init__(self, payload) -> None:
        self.payload = payload


def _fake_jsonify(payload=None, **kwargs):
    return _FakeResponse(payload if payload is not None else kwargs)


def route_specs() -> dict[str, tuple[list[str], str]]:
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


def fake_store(**overrides):
    store = SimpleNamespace(
        list_memories=AsyncMock(return_value=[]),
        get_memory=AsyncMock(return_value=None),
        delete_memory=AsyncMock(return_value=True),
        update_memory_visibility=AsyncMock(return_value=True),
        erase_person_data=AsyncMock(
            return_value={"ok": True, "user_id": "u1", "deleted": {"memories": 3}}
        ),
        stats=AsyncMock(return_value={"memories": 5, "people": 2}),
        summary_progress=AsyncMock(return_value={}),
        set_person_weight=AsyncMock(return_value=None),
        identity_profile=AsyncMock(return_value={}),
        upsert_identity=AsyncMock(return_value=None),
        person_panel_detail=AsyncMock(return_value={"display_name": "u1"}),
        preview_scoped_memory_clear=AsyncMock(return_value={"counts": {"memories": 4}}),
        upsert_acl_rule=AsyncMock(return_value={"id": "rule-1"}),
    )
    for key, value in overrides.items():
        setattr(store, key, value)
    return store


def make_api(data_dir="", store=None, service_overrides=None, plugin_overrides=None):
    service = SimpleNamespace(
        store=store or fake_store(),
        data_dir=str(data_dir),
        config=SimpleNamespace(
            raw={"retrieval": {"mode": "auto"}, "visibility": {"enable_acl_rules": True}},
            bool=lambda key, default=True: default,
            int=lambda key, default=0: default,
            float=lambda key, default=0.0: default,
            get=lambda key, default=None: default,
        ),
        migrator=SimpleNamespace(
            preview=Mock(return_value={"ok": True}),
            repair_imported_content=Mock(return_value={"ok": True}),
        ),
        import_livingmemory=AsyncMock(return_value={"ok": True}),
        clear_all_memory_data=AsyncMock(return_value={"ok": True}),
        clear_scoped_memory=AsyncMock(return_value={"deleted": {"memories": 4}}),
    )
    for key, value in (service_overrides or {}).items():
        setattr(service, key, value)
    plugin = SimpleNamespace(service=service)
    for key, value in (plugin_overrides or {}).items():
        setattr(plugin, key, value)
    return PluginPageApi(plugin)


def make_request(args=None, method="GET", payload=None, headers=None):
    stub = SimpleNamespace(
        args=args or {},
        method=method,
        get_json=AsyncMock(return_value=payload if payload is not None else {}),
    )
    if headers is not None:
        stub.headers = headers
    return stub


async def call_route(api, route, *, args=None, method=None, payload=None, headers=None):
    specs = route_specs()
    methods, handler_name = specs[route]
    handler = getattr(api, handler_name)
    guarded = api._wrap_route(route, handler)
    fake_request = make_request(
        args=args,
        method=method or (methods[0] if methods else "GET"),
        payload=payload,
        headers=headers,
    )
    with patch.object(page_api_module, "request", fake_request), patch.object(
        page_api_module, "jsonify", side_effect=_fake_jsonify
    ):
        return await guarded()


async def csrf_token(api, headers=None):
    response = await call_route(api, "/ui/csrf", method="GET", headers=headers)
    return response.payload["token"]


class PanelConfigWriteGuardTests(unittest.IsolatedAsyncioTestCase):
    """P8：/config/module/update 不能再改安全键。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.api = make_api(self.temp_dir.name)
        self.written: list[dict] = []
        patcher = patch.object(self.api, "_write_plugin_config", side_effect=self.written.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        schema_patcher = patch.object(self.api, "_schema_config_values", return_value={})
        schema_patcher.start()
        self.addCleanup(schema_patcher.stop)

    def test_config_write_is_a_dangerous_route(self) -> None:
        self.assertIn("/config/module/update", page_api_module.UI_DANGEROUS_ENDPOINTS)
        self.assertEqual(
            "dangerous", self.api._endpoint_policy("/config/module/update", "POST")["policy"]
        )
        self.assertTrue(page_api_module.UI_DANGEROUS_REASONS.get("/config/module/update"))

    async def test_security_keys_cannot_be_written_from_the_panel(self) -> None:
        for module, key in (
            ("visibility", "allow_group_public_in_private"),
            ("visibility", "enable_acl_rules"),
            ("visibility", "allow_self_timeline_everywhere"),
            ("private_companion_bridge", "enable_p5_b1_bridge_gate"),
            ("private_companion_bridge", "accept_external_records"),
        ):
            with self.subTest(module=module, key=key):
                payload = {"module": module, "values": {key: False}}
                payload["confirm"] = self.api._expected_confirmation("/config/module/update", payload)[0]
                response = await call_route(
                    self.api, "/config/module/update", method="POST", payload=payload
                )
                self.assertEqual(403, response.status_code)
                self.assertIn("protected_config_key", response.payload["error"])
        self.assertEqual([], self.written)

    async def test_credential_like_keys_are_rejected_by_name(self) -> None:
        payload = {"module": "retrieval", "values": {"rerank_api_key": "sk-live"}}
        payload["confirm"] = self.api._expected_confirmation("/config/module/update", payload)[0]
        response = await call_route(
            self.api, "/config/module/update", method="POST", payload=payload
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual([], self.written)

    async def test_safe_keys_still_save_normally(self) -> None:
        payload = {"module": "retrieval", "values": {"mode": "basic"}}
        payload["confirm"] = self.api._expected_confirmation("/config/module/update", payload)[0]
        response = await call_route(
            self.api, "/config/module/update", method="POST", payload=payload
        )
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.payload["success"])
        self.assertEqual("basic", self.api.plugin.service.config.raw["retrieval"]["mode"])
        self.assertEqual(1, len(self.written))

    async def test_config_schema_advertises_protected_keys(self) -> None:
        with patch.object(self.api, "_provider_options", return_value=[]), patch.object(
            self.api, "_rerank_provider_options", new=AsyncMock(return_value=[])
        ), patch.object(self.api, "_embedding_provider_options", new=AsyncMock(return_value=[])):
            response = await call_route(self.api, "/config/schema", method="GET")
        self.assertEqual(200, response.status_code)
        self.assertIn(
            "visibility.allow_group_public_in_private", response.payload["protected_keys"]
        )
        self.assertIn("visibility", response.payload["protected_modules"])


class PanelCsrfTests(unittest.IsolatedAsyncioTestCase):
    """P13：写操作要带 CSRF 令牌。"""

    def setUp(self) -> None:
        self.api = make_api()

    async def test_csrf_endpoint_issues_a_token(self) -> None:
        response = await call_route(self.api, "/ui/csrf", method="GET")
        self.assertEqual(200, response.status_code)
        token = response.payload["token"]
        self.assertGreaterEqual(len(token), 16)
        self.assertEqual("X-CSRF-Token", response.payload["header"])
        self.assertEqual(900, response.payload["expires_in"])

    async def test_browser_write_without_token_is_rejected(self) -> None:
        response = await call_route(
            self.api,
            WRITE_ROUTE,
            method="POST",
            payload=dict(WRITE_PAYLOAD),
            headers=BROWSER_HEADERS,
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("csrf_required", response.payload["error"])
        self.api.plugin.service.store.upsert_acl_rule.assert_not_called()

    async def test_browser_write_with_bad_token_is_rejected(self) -> None:
        payload = dict(WRITE_PAYLOAD, csrf_token="not-a-token")
        response = await call_route(
            self.api, WRITE_ROUTE, method="POST", payload=payload, headers=BROWSER_HEADERS
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("csrf_required", response.payload["error"])

    async def test_browser_write_with_header_token_passes_the_gate(self) -> None:
        token = await csrf_token(self.api)
        response = await call_route(
            self.api,
            WRITE_ROUTE,
            method="POST",
            payload=dict(WRITE_PAYLOAD),
            headers={**BROWSER_HEADERS, "X-CSRF-Token": token},
        )
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.payload["success"])
        self.api.plugin.service.store.upsert_acl_rule.assert_awaited_once()

    async def test_body_token_works_for_the_bridge_transport(self) -> None:
        token = await csrf_token(self.api)
        payload = dict(WRITE_PAYLOAD, csrf_token=token)
        response = await call_route(
            self.api, WRITE_ROUTE, method="POST", payload=payload, headers=BROWSER_HEADERS
        )
        self.assertEqual(200, response.status_code)

    async def test_expired_token_is_rejected(self) -> None:
        token = await csrf_token(self.api)
        self.api._csrf_tokens[token] = time.monotonic() - 1
        payload = dict(WRITE_PAYLOAD, csrf_token=token)
        response = await call_route(
            self.api, WRITE_ROUTE, method="POST", payload=payload, headers=BROWSER_HEADERS
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("csrf_required", response.payload["error"])


class PanelAdminTests(unittest.IsolatedAsyncioTestCase):
    """P7：所有写档路由统一走面板管理员校验。"""

    def setUp(self) -> None:
        self.api = make_api()

    async def test_denied_admin_cannot_write(self) -> None:
        token = await csrf_token(self.api)
        payload = dict(WRITE_PAYLOAD, csrf_token=token)
        with patch.object(self.api, "_dashboard_admin_state", return_value="denied"):
            response = await call_route(
                self.api, WRITE_ROUTE, method="POST", payload=payload, headers=BROWSER_HEADERS
            )
        self.assertEqual(403, response.status_code)
        self.assertEqual("admin_required", response.payload["error"])
        self.api.plugin.service.store.upsert_acl_rule.assert_not_called()

    async def test_allowed_admin_can_write(self) -> None:
        token = await csrf_token(self.api)
        payload = dict(WRITE_PAYLOAD, csrf_token=token)
        with patch.object(self.api, "_dashboard_admin_state", return_value="allowed"):
            response = await call_route(
                self.api, WRITE_ROUTE, method="POST", payload=payload, headers=BROWSER_HEADERS
            )
        self.assertEqual(200, response.status_code)

    async def test_read_routes_do_not_need_admin(self) -> None:
        with patch.object(self.api, "_dashboard_admin_state", return_value="denied"):
            response = await call_route(self.api, "/stats", method="GET")
        self.assertEqual(200, response.status_code)

    async def test_unbound_dashboard_stays_compatible(self) -> None:
        # 测试环境没有 astrbot.api.web.request，宿主也没配 dashboard.username，
        # 此时必须放行（否则未启用面板鉴权的部署整个写面会瘫掉）。
        token = await csrf_token(self.api)
        payload = dict(WRITE_PAYLOAD, csrf_token=token)
        response = await call_route(
            self.api, WRITE_ROUTE, method="POST", payload=payload, headers=BROWSER_HEADERS
        )
        self.assertEqual(200, response.status_code)

    def test_acl_upsert_and_visibility_are_write_routes(self) -> None:
        for route in (
            "/acl/upsert",
            "/acl/policy",
            "/acl/delete",
            "/memory/visibility",
            "/memory/lifecycle",
            "/person/weight",
        ):
            with self.subTest(route=route):
                policy = self.api._endpoint_policy(route, "POST")["policy"]
                self.assertIn(policy, {"write", "dangerous"})


class PanelConfirmationNonceTests(unittest.IsolatedAsyncioTestCase):
    """P9：确认语从固定串改成一次性 nonce。"""

    def setUp(self) -> None:
        self.api = make_api()

    async def test_nonce_route_issues_a_route_bound_confirmation(self) -> None:
        token = await csrf_token(self.api)
        response = await call_route(
            self.api,
            "/ui/confirm-nonce",
            method="POST",
            payload={"route": "/person/erase", "payload": {"user_id": "u1"}, "csrf_token": token},
            headers=BROWSER_HEADERS,
        )
        self.assertEqual(200, response.status_code)
        confirm = response.payload["confirm"]
        prefix, _, nonce = confirm.rpartition(":")
        self.assertEqual("ERASE:u1", prefix)
        self.assertRegex(nonce, r"^[0-9a-f]{24}$")

    async def test_nonce_route_rejects_routes_that_need_no_confirmation(self) -> None:
        token = await csrf_token(self.api)
        response = await call_route(
            self.api,
            "/ui/confirm-nonce",
            method="POST",
            payload={"route": "/stats", "csrf_token": token},
            headers=BROWSER_HEADERS,
        )
        self.assertEqual(400, response.status_code)

    async def test_nonce_is_single_use(self) -> None:
        token = await csrf_token(self.api)
        issued = await call_route(
            self.api,
            "/ui/confirm-nonce",
            method="POST",
            payload={"route": "/person/erase", "payload": {"user_id": "u1"}, "csrf_token": token},
            headers=BROWSER_HEADERS,
        )
        confirm = issued.payload["confirm"]
        payload = {"user_id": "u1", "confirm": confirm, "csrf_token": token}
        first = await call_route(
            self.api, "/person/erase", method="POST", payload=payload, headers=BROWSER_HEADERS
        )
        self.assertEqual(200, first.status_code)
        second = await call_route(
            self.api, "/person/erase", method="POST", payload=payload, headers=BROWSER_HEADERS
        )
        self.assertEqual(400, second.status_code)
        self.assertEqual("confirm_required", second.payload["error"])
        self.assertEqual(1, self.api.plugin.service.store.erase_person_data.await_count)

    async def test_expired_nonce_is_rejected(self) -> None:
        token = await csrf_token(self.api)
        issued = await call_route(
            self.api,
            "/ui/confirm-nonce",
            method="POST",
            payload={"route": "/person/erase", "payload": {"user_id": "u1"}, "csrf_token": token},
            headers=BROWSER_HEADERS,
        )
        confirm = issued.payload["confirm"]
        nonce = confirm.rpartition(":")[2]
        route, expected, _expiry = self.api._confirm_nonces[nonce]
        self.api._confirm_nonces[nonce] = (route, expected, time.monotonic() - 1)
        response = await call_route(
            self.api,
            "/person/erase",
            method="POST",
            payload={"user_id": "u1", "confirm": confirm, "csrf_token": token},
            headers=BROWSER_HEADERS,
        )
        self.assertEqual(400, response.status_code)

    async def test_canonical_confirm_is_refused_in_a_browser(self) -> None:
        token = await csrf_token(self.api)
        response = await call_route(
            self.api,
            "/person/erase",
            method="POST",
            payload={"user_id": "u1", "confirm": "ERASE:u1", "csrf_token": token},
            headers=BROWSER_HEADERS,
        )
        self.assertEqual(400, response.status_code)
        self.assertEqual(0, self.api.plugin.service.store.erase_person_data.await_count)

    async def test_clear_scope_accepts_a_nonce_and_keeps_its_own_check(self) -> None:
        token = await csrf_token(self.api)
        issued = await call_route(
            self.api,
            "/ui/confirm-nonce",
            method="POST",
            payload={
                "route": "/maintenance/clear_scope",
                "payload": {"target_type": "group", "group_id": "g1"},
                "csrf_token": token,
            },
            headers=BROWSER_HEADERS,
        )
        confirm = issued.payload["confirm"]
        self.assertTrue(confirm.startswith("CLEAR:group:"))
        response = await call_route(
            self.api,
            "/maintenance/clear_scope",
            method="POST",
            payload={"target_type": "group", "group_id": "g1", "confirm": confirm, "csrf_token": token},
            headers=BROWSER_HEADERS,
        )
        self.assertEqual(200, response.status_code)
        self.api.plugin.service.clear_scoped_memory.assert_awaited_once()

    def test_confirmation_text_strips_only_nonce_suffixes(self) -> None:
        self.assertEqual("CLEAR:all", self.api._confirmation_text({"confirm": "CLEAR:all:" + "a" * 24}))
        self.assertEqual("CLEAR:all", self.api._confirmation_text({"confirm": "CLEAR:all"}))
        self.assertEqual("DELETE:m1", self.api._confirmation_text({"confirm": "DELETE:m1:" + "b" * 24}))
        self.assertEqual("", self.api._confirmation_text({}))


class PanelPathGuardTests(unittest.IsolatedAsyncioTestCase):
    """P4：livingmemory 相关 ?path= 只能在插件数据目录内。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name) / "plugin_data" / "astrbot_plugin_memory_companion"
        self.data_dir.mkdir(parents=True)
        self.api = make_api(self.data_dir)

    async def test_traversal_and_absolute_escapes_are_rejected(self) -> None:
        attacks = [
            "../../../../etc/passwd",
            "..\\..\\windows\\win.ini",
            r"C:\Windows\win.ini",
            "/etc/passwd",
        ]
        for attack in attacks:
            with self.subTest(path=attack):
                response = await call_route(
                    self.api, "/import/livingmemory/preview", method="GET", args={"path": attack}
                )
                self.assertEqual(400, response.status_code)
                self.assertIn("path", response.payload["error"])
                self.api.plugin.service.migrator.preview.assert_not_called()

    async def test_path_inside_the_data_dir_is_allowed(self) -> None:
        inside = self.data_dir / "livingmemory.db"
        inside.write_text("", encoding="utf-8")
        response = await call_route(
            self.api, "/import/livingmemory/preview", method="GET", args={"path": str(inside)}
        )
        self.assertEqual(200, response.status_code)
        called_with = self.api.plugin.service.migrator.preview.call_args[0][0]
        self.assertEqual(str(inside.resolve()), called_with)

    async def test_empty_path_keeps_the_configured_default(self) -> None:
        response = await call_route(self.api, "/import/livingmemory/preview", method="GET")
        self.assertEqual(200, response.status_code)
        self.assertEqual("", self.api.plugin.service.migrator.preview.call_args[0][0])

    async def test_import_run_and_repair_share_the_same_guard(self) -> None:
        confirm = "CONFIRM:/import/livingmemory/run"
        response = await call_route(
            self.api,
            "/import/livingmemory/run",
            method="POST",
            payload={"path": r"C:\Windows\win.ini", "confirm": confirm},
        )
        self.assertEqual(400, response.status_code)
        self.api.plugin.service.import_livingmemory.assert_not_called()

        repair_confirm = "CONFIRM:/maintenance/repair_livingmemory_content"
        response = await call_route(
            self.api,
            "/maintenance/repair_livingmemory_content",
            method="POST",
            payload={"path": "../../secrets.db", "confirm": repair_confirm},
        )
        self.assertEqual(400, response.status_code)
        self.api.plugin.service.migrator.repair_imported_content.assert_not_called()


class PanelUnloadTests(unittest.IsolatedAsyncioTestCase):
    """A6：卸载/终止时尽力摘掉页面路由并让入口快速失败。"""

    def setUp(self) -> None:
        self.api = make_api()

    async def test_unregister_routes_makes_every_endpoint_fail_closed(self) -> None:
        self.api._registered_routes = ["/astrbot_plugin_memory_companion/page/stats"]
        self.api.unregister_routes()
        self.assertTrue(self.api._unregistered)
        self.assertEqual({}, self.api._csrf_tokens)
        response = await call_route(self.api, "/stats", method="GET")
        self.assertEqual(503, response.status_code)
        self.assertEqual("plugin_terminated", response.payload["error"])

    async def test_unregister_routes_is_idempotent(self) -> None:
        self.api.unregister_routes()
        self.api.unregister_routes()
        self.assertTrue(self.api._unregistered)

    async def test_terminate_hook_runs_cleanup_before_the_original_terminate(self) -> None:
        order: list[str] = []

        async def terminate() -> None:
            order.append("terminate")

        self.api.plugin.terminate = terminate
        self.api._install_terminate_hook()
        self.assertTrue(self.api._terminate_hook_installed)
        await self.api.plugin.terminate()
        self.assertTrue(self.api._unregistered)
        self.assertEqual(["terminate"], order)

    async def test_terminate_hook_is_installed_only_once(self) -> None:
        async def terminate() -> None:
            return None

        self.api.plugin.terminate = terminate
        self.api._install_terminate_hook()
        wrapped = self.api.plugin.terminate
        self.api._install_terminate_hook()
        self.assertIs(wrapped, self.api.plugin.terminate)


class PanelFrontendSecurityTests(unittest.TestCase):
    def test_panel_fetches_csrf_and_nonce_before_writing(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/ui/csrf", script)
        self.assertIn("/ui/confirm-nonce", script)
        self.assertIn("csrf_token", script)
        self.assertIn("withCsrfToken", script)
        people = (ROOT / "pages" / "记忆面板" / "people.js").read_text(encoding="utf-8")
        self.assertIn("ui/csrf", people)
        self.assertIn("ui/confirm-nonce", people)
        self.assertIn("secureWriteBody", people)

    def test_panel_renders_protected_config_keys_read_only(self) -> None:
        script = (ROOT / "pages" / "记忆面板" / "app.js").read_text(encoding="utf-8")
        self.assertIn("protectedConfigSets", script)
        self.assertIn("protected_keys", script)
        self.assertIn("isProtectedConfigKey", script)


if __name__ == "__main__":
    unittest.main()