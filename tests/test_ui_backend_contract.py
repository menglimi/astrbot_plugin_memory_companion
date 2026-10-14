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

    def test_recent_injection_trace_is_wired_to_both_panel_modes(self) -> None:
        views = literal(assignment(self.tree, "UI_VIEW_ENDPOINTS"))
        self.assertIn("/logs", views["overview"])
        modern = (ROOT / "pages" / "记忆面板" / "modern.html").read_text(encoding="utf-8")
        injection_script = (ROOT / "pages" / "记忆面板" / "injection-status.js").read_text(encoding="utf-8")
        self.assertIn("./injection-status.js?v=", modern)
        self.assertIn('bridge.apiGet("page/logs"', injection_script)
        self.assertIn("/logs?limit=", injection_script)
        self.assertIn("最近注入", injection_script)


if __name__ == "__main__":
    unittest.main()
