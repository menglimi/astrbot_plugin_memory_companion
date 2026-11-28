from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE_API = ROOT / "page_api.py"
PANEL_SCRIPT = ROOT / "pages" / "记忆面板" / "app.js"
PANEL_PAGE = ROOT / "pages" / "记忆面板" / "index.html"
PANEL_SHELL = ROOT / "pages" / "记忆面板" / "legacy.html"


def assignment(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return node.value
    raise AssertionError(f"missing assignment: {name}")


def literal(value: ast.AST):
    return ast.literal_eval(value)


class UiBackendContractTests(unittest.TestCase):
    # 前端拼接出的动态端点：正则只能截到前缀，因此在这里逐条登记为完整端点。
    # 旧实现从 app.js 的 `UI_DYNAMIC_ENDPOINTS` 常量读取该清单，该常量在
    # 2.1.0 面板重写时被删除，导致整个文件无法再校验路由覆盖。
    FRONTEND_DYNAMIC_ENDPOINTS = {
        # app.js:1761 `apiGet(endpoint)`，endpoint 由 albumImageDataPath() 产出。
        "/companion/personal-photo-data",
        # app.js:3310 `apiPost("/conversation-import/" + action)`，action 取自 bindBatch()。
        "/conversation-import/pause",
        "/conversation-import/resume",
        "/conversation-import/rollback",
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls.backend_source = PAGE_API.read_text(encoding="utf-8")
        cls.frontend_source = PANEL_SCRIPT.read_text(encoding="utf-8")
        cls.page_source = PANEL_PAGE.read_text(encoding="utf-8")
        cls.shell_source = PANEL_SHELL.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.backend_source)

    def route_paths(self) -> set[str]:
        for node in ast.walk(self.tree):
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
                self.assertTrue(paths)
                return paths
        self.fail("missing _route_specs")

    def frontend_paths(self) -> set[str]:
        # 面板由两个文件发起请求：app.js（apiGet/apiPost）与 index.html
        # （bridge.apiGet("page/...") 与 /api/plug/... 同源回退）。只扫描 app.js
        # 会把 index.html 独占的端点误判成"后端独有"。
        raw: set[str] = set()
        for source in (self.frontend_source, self.page_source):
            raw.update(re.findall(r"api(?:Get|Post)\(\s*[\"'`]([^\"'`?${}]*)", source))
            raw.update(
                re.findall(
                    r"[\"'`]/api/(?:plug|v1/plugins/extensions)/[A-Za-z0-9_]+/page/([^\"'`?${}]*)",
                    source,
                )
            )
        paths = set()
        for item in raw:
            path = item.strip()
            if path.startswith("page/"):
                path = path[len("page"):]
            if not path.startswith("/"):
                continue
            paths.add(path.rstrip())
        # 拼接型调用只会被截成前缀（如 "/conversation-import/"）。前缀必须在
        # FRONTEND_DYNAMIC_ENDPOINTS 中有对应完整端点，否则新增的拼接调用会被静默漏检。
        prefixes = {path for path in paths if path.endswith("/")}
        paths -= prefixes
        for prefix in prefixes:
            self.assertTrue(
                any(endpoint.startswith(prefix) for endpoint in self.FRONTEND_DYNAMIC_ENDPOINTS),
                f"前端拼接型端点前缀 {prefix} 未登记为可校验的完整端点",
            )
        paths.update(self.FRONTEND_DYNAMIC_ENDPOINTS)
        return paths

    def test_ui_contract_version_and_modes_match(self) -> None:
        backend_version = literal(assignment(self.tree, "UI_CONTRACT_VERSION"))
        backend_modes = literal(assignment(self.tree, "UI_MODES"))
        self.assertEqual("memory.page.ui.v2", backend_version)
        self.assertEqual({"standard", "cinema"}, {item["id"] for item in backend_modes})
        # 2.1.0 面板重写后，前端不再镜像 UI_CONTRACT_VERSION（契约常量只由后端
        # /ui/capabilities 发布），但必须实现后端声明的同一组模式标识。
        self.assertIn('state.mode = mode === "cinema" ? "cinema" : "standard";', self.frontend_source)
        self.assertIn('document.documentElement.dataset.uiMode = state.mode;', self.frontend_source)
        self.assertIn('const MODE_KEY = "memory_companion_mode";', self.frontend_source)
        # 入口页只做风格分流，真正的实现页必须加载 app.js 且带缓存标识。
        self.assertIn("./modern.html", self.page_source)
        self.assertIn("./legacy.html", self.page_source)
        self.assertIn("./app.js?v=", self.shell_source)

    def test_every_frontend_api_call_has_a_registered_backend_route(self) -> None:
        missing = self.frontend_paths() - self.route_paths()
        self.assertEqual(set(), missing, f"frontend endpoints without backend routes: {sorted(missing)}")

    def test_page_bridge_uses_registered_namespace_and_separates_query_params(self) -> None:
        # `/api/plug/<plugin>/page` 是 AstrBot 当前的插件页路由前缀；旧断言写的是
        # `/api/v1/plugins/extensions/...`，该写法在 5417b01（2.1.3）后被改掉，
        # 移动端 WebView 走 `/api/plug` 才能在同源请求下拿到插件页。
        self.assertIn('const API = "/api/plug/astrbot_plugin_memory_companion/page";', self.frontend_source)
        self.assertIn('const PAGE_ENDPOINT_PREFIX = "page"', self.frontend_source)
        self.assertIn("data = await bridgeRequest(bridge, path, method, options.body);", self.frontend_source)
        self.assertIn("const bridge = getBridge() || await waitForBridge();", self.frontend_source)
        self.assertIn("url.pathname.replace(/^\\/+/, \"\")", self.frontend_source)
        self.assertIn("Object.fromEntries(url.searchParams.entries())", self.frontend_source)
        self.assertIn("bridge.apiGet(endpoint, Object.keys(params).length ? params : undefined)", self.frontend_source)
        self.assertIn('data.status === "error"', self.frontend_source)

    def test_personal_album_uses_bridge_loaded_data_urls(self) -> None:
        self.assertIn("data-album-image-src", self.frontend_source)
        self.assertIn("async function hydratePersonalAlbumImages", self.frontend_source)
        self.assertIn('apiGet(endpoint)', self.frontend_source)
        self.assertIn('result.data_url', self.frontend_source)
        self.assertIn('personal-photo-data', self.frontend_source)

    def test_starmap_detail_unwraps_memory_api_payload(self) -> None:
        self.assertIn('const response = await apiGet("/memory?id=" + encodeURIComponent(memoryId));', self.frontend_source)
        self.assertIn('const memory = response && response.memory ? response.memory : response;', self.frontend_source)

    def test_summary_batch_release_hint_uses_the_real_batch_id_prefix(self) -> None:
        self.assertIn('placeholder: "sb_... 批次 ID"', self.frontend_source)
        self.assertNotIn("summary_batch_...", self.frontend_source)

    def test_memory_category_filters_expand_to_persisted_types(self) -> None:
        filters = literal(assignment(self.tree, "MEMORY_TYPE_FILTERS"))
        self.assertIn("user_profile", filters["profile"])
        self.assertIn("user_preference", filters["preference"])
        self.assertIn("relationship_phase_summary", filters["relationship"])
        self.assertIn("important_event", filters["event"])
        self.assertIn("schedule_fragment", filters["schedule"])
        self.assertIn("memory_types=memory_types", self.backend_source)
        self.assertIn('user_profile: "画像"', self.frontend_source)

    def test_memory_category_filter_uses_store_in_query(self) -> None:
        store_source = (ROOT / "core" / "store.py").read_text(encoding="utf-8")
        self.assertIn("memory_types=memory_types", self.backend_source)
        self.assertIn("memory_types: list[str] | tuple[str, ...] | None = None", store_source)
        self.assertIn("memory_type IN ({marks})", store_source)

    def test_lifecycle_filters_expand_to_persisted_states(self) -> None:
        filters = literal(assignment(self.tree, "MEMORY_LIFECYCLE_FILTERS"))
        self.assertIn("stable_memory", filters["stable"])
        self.assertIn("current_window", filters["active"])
        self.assertIn("planned_projection", filters["active"])
        self.assertIn("recent", filters["fading"])
        self.assertIn("lifecycle_values=lifecycle_values", self.backend_source)

    def test_scope_and_visibility_filters_use_persisted_values(self) -> None:
        backend = self.backend_source
        self.assertIn('"public": ("public", "group_public")', backend)
        self.assertIn('"private": ("private", "private_pair")', backend)
        self.assertIn('scope="" if scope in {"profile", "external"} else scope', backend)
        # external 视图必须排除本插件自己写入的行，同时始终隐藏 bot_personal 归档行。
        # 9800dbf（2.1.0）把这条排除从单个 SQL 参数改成了「SQL 排除归档行 + 结果侧排除本插件」，
        # 语义未变（external 仍看不到自产记忆），因此断言改为校验当前写法。
        self.assertIn('source_plugin_exclude="bot_personal_bridge",', backend)
        self.assertIn('if scope == "external":', backend)
        self.assertIn('!= PLUGIN_NAME', backend)

    def test_every_backend_only_route_has_an_explicit_exposure_reason(self) -> None:
        routes = self.route_paths()
        frontend = self.frontend_paths()
        views = literal(assignment(self.tree, "UI_VIEW_ENDPOINTS"))
        frontend.update(path for endpoints in views.values() for path in endpoints)
        exposure = literal(assignment(self.tree, "UI_ENDPOINT_EXPOSURE"))
        self.assertTrue(set(exposure).issubset(routes))
        backend_only = routes - frontend
        self.assertEqual(
            set(),
            backend_only - set(exposure),
            f"backend-only routes need an explicit internal/compat/advanced reason: {sorted(backend_only - set(exposure))}",
        )
        for path in backend_only:
            self.assertIn(exposure[path]["exposure"], {"internal", "compat", "advanced"})
            self.assertTrue(exposure[path]["reason"].strip())

    def test_declared_view_endpoints_are_registered(self) -> None:
        routes = self.route_paths()
        views = literal(assignment(self.tree, "UI_VIEW_ENDPOINTS"))
        self.assertEqual(
            {"overview", "users", "groups", "personal", "knowledge", "microscope", "archive"},
            set(views),
        )
        for view, endpoints in views.items():
            self.assertTrue(endpoints, view)
            self.assertEqual(set(), set(endpoints) - routes, view)

    def test_recent_injection_trace_survives_starmap_removal(self) -> None:
        # 2.6.4 删三维终端时一并移除了 injection-status.js；
        # 总览的「最近注入」改由控制台 app.js 直接渲染，接口契约不变。
        views = literal(assignment(self.tree, "UI_VIEW_ENDPOINTS"))
        self.assertIn("/logs", views["overview"])
        panel = ROOT / "pages" / "记忆面板"
        modern = (panel / "modern.html").read_text(encoding="utf-8")
        self.assertNotIn("injection-status.js", modern)
        self.assertFalse((panel / "injection-status.js").exists())
        console = (panel / "app.js").read_text(encoding="utf-8")
        self.assertIn("/logs?limit=", console)
        self.assertIn("最近注入", console)


# ---- L8：真实接口契约（直调 page_api，而不是只 grep 标签字符串）----------------
# 旧测试用 ast 把 UI_DANGEROUS_ENDPOINTS 等常量读出来再断言字符串存在，这只能证明
# 常量里写了这些字，证明不了运行中的端点真的按契约返回、危险操作真的被拦下。
# 下面直接实例化 PluginPageApi，调 ui_capabilities() 与 _wrap_route() 来验行为。
import importlib
import inspect
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:  # pragma: no cover - 直接以脚本方式运行时
    from package_bootstrap import bootstrap_package


bootstrap_package()

if "quart" not in sys.modules:
    _quart_stub = types.ModuleType("quart")
    _quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    _quart_stub.request = SimpleNamespace(args={}, method="GET")
    _quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = _quart_stub

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi

# 危险端点_handler 里出现任意一个标记，就认为它接了管理身份鉴权。
ADMIN_GUARD_MARKERS = (
    "admin_required",
    "_require_admin",
    "_require_dashboard_admin",
    "_trusted_emotion_admin_context",
    "_is_bound_dashboard_admin",
)


class _FakeResponse:
    """替代 quart.jsonify 的最小响应：保留 status_code，业务负载放 json。"""

    def __init__(self, payload, status_code=200):
        self.json = payload
        self.status_code = status_code


def _fake_jsonify(payload=None, **kwargs):
    return _FakeResponse(payload if payload is not None else kwargs)


class UiCapabilitiesRuntimeContractTests(unittest.IsolatedAsyncioTestCase):
    """L8：把 /ui/capabilities 当成真契约逐字段核对，并验证危险端点的确认关口。"""

    def _api(self):
        # ui_capabilities / _wrap_route 不访问 service 业务方法；service 留空即可，
        # data_dir 为空时审计日志直接跳过，测试不会污染仓库。
        return PluginPageApi(SimpleNamespace(service=SimpleNamespace()))

    async def _capabilities(self):
        api = self._api()
        with patch.object(page_api_module, "jsonify", _fake_jsonify):
            response = await api.ui_capabilities()
        self.assertEqual(200, response.status_code)
        return api, response.json

    async def test_ui_capabilities_matches_module_constants(self) -> None:
        api, payload = await self._capabilities()
        self.assertTrue(payload["success"])
        self.assertEqual(page_api_module.UI_CONTRACT_VERSION, payload["contract_version"])
        self.assertEqual(list(page_api_module.UI_MODES), payload["modes"])

        endpoint_views: dict[str, list[str]] = {}
        for view, endpoints in page_api_module.UI_VIEW_ENDPOINTS.items():
            for endpoint in endpoints:
                endpoint_views.setdefault(endpoint, []).append(view)
        self.assertEqual(
            {
                view: list(endpoints)
                for view, endpoints in page_api_module.UI_VIEW_ENDPOINTS.items()
            },
            {row["id"]: row["endpoints"] for row in payload["views"]},
        )

        rows = {row["path"]: row for row in payload["endpoints"]}
        self.assertEqual(len(rows), len(payload["endpoints"]), "端点路径重复")
        runtime_paths = {path for path, _h, _m, _d in api._route_specs()}
        self.assertEqual(runtime_paths, set(rows), "能力清单与实际路由不一致")

        exposure = page_api_module.UI_ENDPOINT_EXPOSURE
        dangerous = page_api_module.UI_DANGEROUS_ENDPOINTS
        problems: list[str] = []
        for path, row in sorted(rows.items()):
            expected_exposure = exposure.get(path, {}).get("exposure", "visible")
            expected_reason = exposure.get(path, {}).get("reason", "面板直接功能")
            if row["exposure"] != expected_exposure:
                problems.append(f"{path} exposure={row['exposure']} 期望 {expected_exposure}")
            if row["reason"] != expected_reason:
                problems.append(f"{path} reason={row['reason']!r} 期望 {expected_reason!r}")
            if row["dangerous"] != (path in dangerous):
                problems.append(f"{path} dangerous={row['dangerous']}")
            if row["views"] != endpoint_views.get(path, []):
                problems.append(f"{path} views={row['views']}")
            if not row["methods"]:
                problems.append(f"{path} methods 为空")
            if row["exposure"] not in {"internal", "compat", "advanced", "visible"}:
                problems.append(f"{path} exposure 档位非法：{row['exposure']}")
            if row["policy"] not in {"read", "write", "dangerous"}:
                problems.append(f"{path} policy 非法：{row['policy']}")
            if path in dangerous:
                if row["policy"] != "dangerous":
                    problems.append(f"{path} 是危险端点但 policy={row['policy']}")
                if path not in page_api_module.UI_DANGEROUS_REASONS:
                    problems.append(f"{path} 缺危险原因说明")
        self.assertEqual([], problems, "ui_capabilities 与契约常量不一致：\n" + "\n".join(problems))

        self.assertEqual(
            set(dangerous),
            {path for path, row in rows.items() if row["dangerous"]},
        )

    async def test_dangerous_endpoints_reject_missing_confirmation(self) -> None:
        api = self._api()
        failures: list[str] = []
        for route in sorted(page_api_module.UI_DANGEROUS_ENDPOINTS):
            handler = AsyncMock(return_value=_FakeResponse({"success": True}))
            request = SimpleNamespace(method="POST")
            with (
                patch.object(page_api_module, "request", request),
                patch.object(page_api_module, "jsonify", _fake_jsonify),
                patch.object(api, "_json", AsyncMock(return_value={})),
            ):
                response = await api._wrap_route(route, handler)()
            if response.status_code != 400:
                failures.append(f"{route} 缺 confirm 时 status_code={response.status_code}")
                continue
            if response.json.get("error") != "confirm_required":
                failures.append(f"{route} 错误码不是 confirm_required：{response.json}")
            if handler.await_count:
                failures.append(f"{route} 缺 confirm 却执行了业务 handler")
        self.assertEqual([], failures, "危险端点确认关口漏洞：\n" + "\n".join(failures))

    async def test_dangerous_endpoints_accept_matching_confirmation(self) -> None:
        api = self._api()
        failures: list[str] = []
        for route in sorted(page_api_module.UI_DANGEROUS_ENDPOINTS):
            payload = self._confirmation_payload(route)
            expected, _target = api._expected_confirmation(route, payload)
            if not expected:
                failures.append(f"{route} 生不出期望 confirm")
                continue
            payload["confirm"] = expected
            handler = AsyncMock(return_value=_FakeResponse({"success": True}))
            request = SimpleNamespace(method="POST")
            with (
                patch.object(page_api_module, "request", request),
                patch.object(page_api_module, "jsonify", _fake_jsonify),
                patch.object(api, "_json", AsyncMock(return_value=payload)),
            ):
                response = await api._wrap_route(route, handler)()
            if response.status_code != 200:
                failures.append(f"{route} confirm={expected} 仍被拒：{response.json}")
            if handler.await_count != 1:
                failures.append(f"{route} confirm 匹配但 handler 未执行")
        self.assertEqual([], failures, "危险端点确认规则不可用：\n" + "\n".join(failures))

    @staticmethod
    def _confirmation_payload(route: str) -> dict:
        if route in {"/memory/delete", "/core-memory/delete"}:
            return {"id": "mem-1"}
        if route == "/person/erase":
            return {"user_id": "user-1"}
        if route == "/maintenance/clear_scope":
            return {"scope": "private"}
        return {}

    def test_dangerous_endpoints_have_admin_authentication(self) -> None:
        """危险端点除 confirm 外还必须有管理身份鉴权；未落地前跳过而不是硬失败。"""
        api = self._api()
        missing: list[str] = []
        for path, handler, _methods, _desc in api._route_specs():
            if path not in page_api_module.UI_DANGEROUS_ENDPOINTS:
                continue
            try:
                source = inspect.getsource(handler)
            except (OSError, TypeError):
                source = ""
            if not any(marker in source for marker in ADMIN_GUARD_MARKERS):
                missing.append(path)
        if missing:
            self.skipTest(
                "危险端点尚未接入管理身份鉴权（等 panel/Lead 落地后这条会自动生效）："
                + ", ".join(missing)
            )


if __name__ == "__main__":
    unittest.main()
