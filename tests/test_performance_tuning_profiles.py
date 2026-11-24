from __future__ import annotations

import asyncio
import importlib
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

from astrbot_plugin_memory_companion.core.config import ConfigView
from astrbot_plugin_memory_companion.core.latency import (
    DEFAULT_MEMORY_HOOK_BUDGET_SECONDS,
    MAX_MEMORY_HOOK_BUDGET_SECONDS,
    bounded_memory_hook_budget_seconds,
)
from astrbot_plugin_memory_companion.core.operations import PRESETS, apply_preset
from astrbot_plugin_memory_companion.core.performance_tuning import (
    PERFORMANCE_PARAMS,
    PERFORMANCE_TIER_SPECS,
    SQLITE_SENTINELS,
    _detect_cgroup_cpu_limit,
    _detect_cgroup_memory_mb,
    build_performance_config_updates,
    detect_host_hardware,
    resolve_performance_plan,
)
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore

if "quart" not in sys.modules:
    _quart_stub = types.ModuleType("quart")
    _quart_stub.jsonify = lambda payload=None, **kwargs: payload if payload is not None else kwargs
    _quart_stub.request = SimpleNamespace(args={}, method="GET")
    _quart_stub.send_file = AsyncMock()
    sys.modules["quart"] = _quart_stub

page_api_module = importlib.import_module("astrbot_plugin_memory_companion.page_api")
PluginPageApi = page_api_module.PluginPageApi
main_module = importlib.import_module("astrbot_plugin_memory_companion.main")


class _SaveableConfig(dict):
    """Minimal AstrBotConfig stand-in supporting save_config() and config_path."""

    def __init__(self, initial: dict | None = None, config_path: str = ""):
        super().__init__(initial or {})
        self.config_path = config_path
        self.save_calls = 0

    def save_config(self) -> None:
        self.save_calls += 1


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.json = payload
        self.status_code = status_code


def _fake_jsonify(payload=None, **kwargs):
    return _FakeResponse(payload if payload is not None else kwargs)


class PerformanceTierAndHardwareTests(unittest.TestCase):
    def test_five_tiers_resolve_expected_matrix(self) -> None:
        self.assertEqual(5, len(PERFORMANCE_TIER_SPECS))
        self.assertEqual(12, len(PERFORMANCE_PARAMS))

        hw_low = detect_host_hardware(host_memory_mb=1536, cpu_count=2, is_32bit=False)
        plan_auto_low = resolve_performance_plan({}, hardware=hw_low)
        self.assertEqual("auto", plan_auto_low.requested_profile)
        self.assertEqual("eco", plan_auto_low.effective_tier)
        self.assertEqual(8, plan_auto_low.sqlite_cache_size_mb)
        self.assertEqual(0, plan_auto_low.sqlite_mmap_size_mb)
        self.assertEqual(2, plan_auto_low.sqlite_read_pool_size)
        self.assertEqual("NORMAL", plan_auto_low.sqlite_synchronous)
        self.assertEqual("float16", plan_auto_low.vector_precision)
        self.assertEqual(64, plan_auto_low.vector_snapshot_cache_mb)
        self.assertFalse(plan_auto_low.startup_vector_warmup_enabled)
        self.assertEqual(1, plan_auto_low.embedding_background_concurrency)
        self.assertEqual(2.0, plan_auto_low.hook_request_budget_seconds)
        self.assertEqual(1200, plan_auto_low.recall_latency_budget_ms)
        self.assertEqual(4 * 1024 * 1024, plan_auto_low.wal_checkpoint_min_bytes)
        self.assertEqual(90, plan_auto_low.background_grace_seconds)

        hw_mid = detect_host_hardware(host_memory_mb=8192, cpu_count=4, is_32bit=False)
        plan_auto_mid = resolve_performance_plan({}, hardware=hw_mid)
        self.assertEqual("balanced", plan_auto_mid.effective_tier)
        self.assertEqual(32, plan_auto_mid.sqlite_cache_size_mb)
        self.assertEqual(256, plan_auto_mid.sqlite_mmap_size_mb)
        self.assertEqual(4, plan_auto_mid.sqlite_read_pool_size)
        self.assertEqual("float32", plan_auto_mid.vector_precision)
        self.assertEqual(256, plan_auto_mid.vector_snapshot_cache_mb)
        self.assertTrue(plan_auto_mid.startup_vector_warmup_enabled)
        self.assertEqual(2, plan_auto_mid.embedding_background_concurrency)
        self.assertEqual(3.0, plan_auto_mid.hook_request_budget_seconds)
        self.assertEqual(1800, plan_auto_mid.recall_latency_budget_ms)
        self.assertEqual(8 * 1024 * 1024, plan_auto_mid.wal_checkpoint_min_bytes)
        self.assertEqual(60, plan_auto_mid.background_grace_seconds)

        hw_high = detect_host_hardware(host_memory_mb=16384, cpu_count=8, is_32bit=False)
        plan_auto_high = resolve_performance_plan({}, hardware=hw_high)
        self.assertEqual("turbo", plan_auto_high.effective_tier)
        self.assertEqual(64, plan_auto_high.sqlite_cache_size_mb)
        self.assertEqual(512, plan_auto_high.sqlite_mmap_size_mb)
        self.assertEqual(8, plan_auto_high.sqlite_read_pool_size)
        self.assertEqual(512, plan_auto_high.vector_snapshot_cache_mb)
        self.assertEqual(4, plan_auto_high.embedding_background_concurrency)
        self.assertEqual(2200, plan_auto_high.recall_latency_budget_ms)
        self.assertEqual(16 * 1024 * 1024, plan_auto_high.wal_checkpoint_min_bytes)
        self.assertEqual(30, plan_auto_high.background_grace_seconds)

        hw_32g = detect_host_hardware(host_memory_mb=32768, cpu_count=16, is_32bit=False)
        plan_32g = resolve_performance_plan({"performance": {"profile": "turbo"}}, hardware=hw_32g)
        self.assertEqual(1024, plan_32g.sqlite_mmap_size_mb)
        self.assertEqual(12, plan_32g.sqlite_read_pool_size)

        plan_compat = resolve_performance_plan({"performance": {"profile": "compat"}}, hardware=hw_32g)
        self.assertEqual("compat", plan_compat.effective_tier)
        self.assertEqual(16, plan_compat.sqlite_cache_size_mb)
        self.assertEqual(0, plan_compat.sqlite_mmap_size_mb)
        self.assertEqual(2, plan_compat.sqlite_read_pool_size)
        self.assertEqual("FULL", plan_compat.sqlite_synchronous)
        self.assertEqual("float32", plan_compat.vector_precision)
        self.assertEqual(128, plan_compat.vector_snapshot_cache_mb)
        self.assertFalse(plan_compat.startup_vector_warmup_enabled)
        self.assertEqual(1, plan_compat.embedding_background_concurrency)
        self.assertEqual(5.0, plan_compat.hook_request_budget_seconds)
        self.assertEqual(3000, plan_compat.recall_latency_budget_ms)
        self.assertEqual(4 * 1024 * 1024, plan_compat.wal_checkpoint_min_bytes)
        self.assertEqual(120, plan_compat.background_grace_seconds)

    def test_cgroup_v2_and_v1_memory_and_cpu_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            v2_mem = root / "memory.max"
            v1_mem = root / "memory.limit_in_bytes"
            v2_cpu = root / "cpu.max"
            v1_quota = root / "cpu.cfs_quota_us"
            v1_period = root / "cpu.cfs_period_us"

            # cgroup v2 finite limit takes priority
            v2_mem.write_text("2147483648\n", encoding="utf-8")
            v1_mem.write_text("4294967296\n", encoding="utf-8")
            mb, src = _detect_cgroup_memory_mb(v2_path=v2_mem, v1_path=v1_mem)
            self.assertEqual(2048, mb)
            self.assertEqual("cgroup_v2", src)

            # cgroup v2 "max" falls back to v1 finite limit
            v2_mem.write_text("max\n", encoding="utf-8")
            v1_mem.write_text("1073741824\n", encoding="utf-8")
            mb, src = _detect_cgroup_memory_mb(v2_path=v2_mem, v1_path=v1_mem)
            self.assertEqual(1024, mb)
            self.assertEqual("cgroup_v1", src)

            # cgroup v1 huge kernel sentinel means unlimited
            v1_mem.write_text("9223372036854771712\n", encoding="utf-8")
            mb, src = _detect_cgroup_memory_mb(v2_path=v2_mem, v1_path=v1_mem)
            self.assertIsNone(mb)
            self.assertEqual("", src)

            # cgroup CPU quota v2 and v1
            v2_cpu.write_text("200000 100000\n", encoding="utf-8")
            self.assertEqual(2, _detect_cgroup_cpu_limit(v2_path=v2_cpu, v1_quota_path=v1_quota, v1_period_path=v1_period))
            v2_cpu.write_text("max 100000\n", encoding="utf-8")
            v1_quota.write_text("150000\n", encoding="utf-8")
            v1_period.write_text("100000\n", encoding="utf-8")
            self.assertEqual(2, _detect_cgroup_cpu_limit(v2_path=v2_cpu, v1_quota_path=v1_quota, v1_period_path=v1_period))

        # Container cgroup limit tighter than host RAM drives eco recommendation
        hw = detect_host_hardware(host_memory_mb=32768, cgroup_memory_mb=2048, cpu_count=2, is_32bit=False)
        self.assertEqual(2048, hw.effective_memory_mb)
        self.assertEqual("cgroup_v2", hw.memory_source)
        self.assertEqual("eco", hw.recommended_tier)
        self.assertIn("cgroup", hw.recommendation_reason)

    def test_anti_oom_clamping_and_32bit_mmap_guard(self) -> None:
        hw_1g = detect_host_hardware(host_memory_mb=1024, cpu_count=2, is_32bit=False)
        _updated, plan = build_performance_config_updates(
            {},
            profile="turbo",
            overrides={
                "performance.sqlite_cache_size_mb": 256,
                "performance.sqlite_mmap_size_mb": 1024,
                "retrieval_advanced.vector_snapshot_cache_mb": 1024,
            },
            hardware=hw_1g,
        )
        # 10% of 1024 = 102 MB; 25% of 1024 = 256 MB; 30% of 1024 = 307 MB
        self.assertEqual(102, plan.sqlite_cache_size_mb)
        self.assertEqual(256, plan.sqlite_mmap_size_mb)
        self.assertEqual(307, plan.vector_snapshot_cache_mb)
        clamped_keys = {item["key"] for item in plan.clamped_fields}
        self.assertEqual(
            {
                "performance.sqlite_cache_size_mb",
                "performance.sqlite_mmap_size_mb",
                "retrieval_advanced.vector_snapshot_cache_mb",
            },
            clamped_keys,
        )
        for item in plan.clamped_fields:
            self.assertIn("防爆内存保护", item["reason"])

        # 32-bit environment forces mmap_size_mb = 0 even when overridden
        hw_32bit = detect_host_hardware(host_memory_mb=8192, cpu_count=4, is_32bit=True)
        _u32, plan_32 = build_performance_config_updates(
            {},
            profile="balanced",
            overrides={"performance.sqlite_mmap_size_mb": 512},
            hardware=hw_32bit,
        )
        self.assertEqual(0, plan_32.sqlite_mmap_size_mb)
        self.assertTrue(any(c["key"] == "performance.sqlite_mmap_size_mb" and "32 位" in c["reason"] for c in plan_32.clamped_fields))

    def test_sparse_overrides_preserve_reset_and_functional_preset_orthogonality(self) -> None:
        hw = detect_host_hardware(host_memory_mb=16384, cpu_count=8, is_32bit=False)
        raw: dict = {}

        # Apply eco + 2 sparse overrides
        raw, plan1 = build_performance_config_updates(
            raw,
            profile="eco",
            overrides={
                "memory_injection.hook_request_budget_seconds": 6.0,
                "performance.sqlite_cache_size_mb": 24,
            },
            hardware=hw,
        )
        self.assertEqual(2, len(plan1.overrides))
        self.assertEqual(6.0, plan1.hook_request_budget_seconds)
        self.assertEqual(24, plan1.sqlite_cache_size_mb)
        self.assertEqual(SQLITE_SENTINELS["performance.sqlite_mmap_size_mb"], raw["performance"]["sqlite_mmap_size_mb"])

        # Switch eco -> turbo keeping sparse overrides
        raw, plan2 = build_performance_config_updates(
            raw,
            profile="turbo",
            preserve_overrides=True,
            hardware=hw,
        )
        self.assertEqual("turbo", plan2.effective_tier)
        self.assertEqual(6.0, plan2.hook_request_budget_seconds)
        self.assertEqual(24, plan2.sqlite_cache_size_mb)
        self.assertEqual(512, plan2.sqlite_mmap_size_mb)  # adopted turbo default
        self.assertEqual("float32", plan2.vector_precision)  # adopted turbo default

        # Restore single override to follow tier via None
        raw, plan3 = build_performance_config_updates(
            raw,
            overrides={"memory_injection.hook_request_budget_seconds": None},
            preserve_overrides=True,
            hardware=hw,
        )
        self.assertEqual(3.0, plan3.hook_request_budget_seconds)
        self.assertNotIn("memory_injection.hook_request_budget_seconds", plan3.overrides)
        self.assertIn("performance.sqlite_cache_size_mb", plan3.overrides)

        # Reset all overrides
        raw, plan4 = build_performance_config_updates(
            raw,
            profile="turbo",
            reset_overrides=True,
            hardware=hw,
        )
        self.assertEqual({}, plan4.overrides)
        self.assertEqual(64, plan4.sqlite_cache_size_mb)
        self.assertEqual(0, raw["performance"]["sqlite_cache_size_mb"])

        # Reject unknown or protected security keys
        with self.assertRaises(ValueError):
            build_performance_config_updates(
                raw,
                overrides={"visibility.enable_acl_rules": False},
                hardware=hw,
            )

        # Functional presets (light / standard / companion) have ZERO overlap with performance params
        perf_keys = {spec.key for spec in PERFORMANCE_PARAMS}
        for preset_name, preset_values in PRESETS.items():
            self.assertEqual(set(), perf_keys & set(preset_values), f"{preset_name} overlaps performance params")
        apply_preset(raw, "companion")
        plan_after_func = resolve_performance_plan(raw, hardware=hw)
        self.assertEqual("turbo", plan_after_func.effective_tier)
        self.assertEqual(64, plan_after_func.sqlite_cache_size_mb)

    def test_hook_budget_ceiling_8s_and_plugin_profile_fallback(self) -> None:
        self.assertEqual(8.0, MAX_MEMORY_HOOK_BUDGET_SECONDS)
        self.assertEqual(1.0, DEFAULT_MEMORY_HOOK_BUDGET_SECONDS)
        self.assertEqual(5.0, bounded_memory_hook_budget_seconds(5.0))
        self.assertEqual(8.0, bounded_memory_hook_budget_seconds(8.0))
        self.assertEqual(8.0, bounded_memory_hook_budget_seconds(15.0))

        shell_empty = main_module.MemoryCompanionPlugin.__new__(main_module.MemoryCompanionPlugin)
        shell_empty.service = SimpleNamespace(config=ConfigView({}))
        self.assertEqual(0.0, shell_empty._hook_request_budget_seconds())

        shell_compat = main_module.MemoryCompanionPlugin.__new__(main_module.MemoryCompanionPlugin)
        shell_compat.service = SimpleNamespace(config=ConfigView({"performance": {"profile": "compat"}}))
        self.assertEqual(5.0, shell_compat._hook_request_budget_seconds())


class StoreHotReloadDiskGuardAndApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_store_hot_reload_updates_pragmas_and_rolls_read_pool_safely(self) -> None:
        hw = detect_host_hardware(host_memory_mb=16384, cpu_count=8, is_32bit=False)
        plan_balanced = resolve_performance_plan({"performance": {"profile": "balanced"}}, hardware=hw)
        plan_compat = resolve_performance_plan({"performance": {"profile": "compat"}}, hardware=hw)

        store = MemoryStore(self.tmp_dir / "hot_reload.db", performance_plan=plan_balanced)
        store.initialize()
        try:
            self.assertEqual(-32768, store._conn.execute("PRAGMA cache_size").fetchone()[0])
            self.assertEqual(256 * 1024 * 1024, store._conn.execute("PRAGMA mmap_size").fetchone()[0])
            self.assertEqual(1, store._conn.execute("PRAGMA synchronous").fetchone()[0])  # NORMAL = 1
            self.assertEqual(6, store._read_pool_max)

            # Open dedicated read connections AND have 1 idle + 1 in-flight pooled connection simultaneously
            rconn, _ = store._read_connection_for_bundle()
            tconn, _ = store._timeline_read_connection()
            vconn, _ = store._vector_read_connection()
            pooled_idle = store._acquire_pooled_read_conn_sync()
            pooled_inflight = store._acquire_pooled_read_conn_sync()
            store._release_pooled_read_conn_sync(pooled_idle)
            try:
                gen_before = store._read_pool_generation
                report = store.apply_performance_plan(plan_compat)
                self.assertEqual(gen_before + 1, report["read_pool_generation"])
                self.assertEqual(2, report["read_pool_max"])
                self.assertEqual(2, store._read_pool_max)
                self.assertEqual(1, report["idle_connections_recycled"])

                # Main and dedicated read connections updated live
                self.assertEqual(-16384, store._conn.execute("PRAGMA cache_size").fetchone()[0])
                self.assertEqual(0, store._conn.execute("PRAGMA mmap_size").fetchone()[0])
                self.assertEqual(2, store._conn.execute("PRAGMA synchronous").fetchone()[0])  # FULL = 2
                for conn in (rconn, tconn, vconn):
                    self.assertEqual(-16384, conn.execute("PRAGMA cache_size").fetchone()[0])
                    self.assertEqual(0, conn.execute("PRAGMA mmap_size").fetchone()[0])

                # In-flight pooled connection still completes its query and closes cleanly on release
                self.assertEqual(1, pooled_inflight.execute("SELECT 1").fetchone()[0])
            finally:
                store._release_pooled_read_conn_sync(pooled_inflight)
            self.assertNotIn(pooled_inflight, store._read_pool_all)
            self.assertEqual(0, len(store._read_pool_idle))

            # Next pooled checkout picks up new generation & new PRAGMAs
            fresh = store._acquire_pooled_read_conn_sync()
            try:
                self.assertEqual(-16384, fresh.execute("PRAGMA cache_size").fetchone()[0])
                self.assertEqual(0, fresh.execute("PRAGMA mmap_size").fetchone()[0])
                self.assertEqual(store._read_pool_generation, store._read_pool_conn_gen[fresh])
            finally:
                store._release_pooled_read_conn_sync(fresh)
        finally:
            store.close()

    async def test_full_vacuum_22x_disk_preflight_and_exclusive_lock(self) -> None:
        service = MemoryCompanionService(
            context=SimpleNamespace(),
            config=_SaveableConfig({"startup": {"background_grace_seconds": 0}}),
            plugin_root=ROOT,
            data_dir=self.tmp_dir,
        )
        try:
            # 1) Disk space too low -> full VACUUM blocked cleanly, regular slimming still works
            with patch.object(service.store, "_available_disk_bytes", return_value=10 * 1024 * 1024):
                health = await service.database_health_snapshot()
                self.assertFalse(health["primary"]["disk_preflight"]["ok"])
                self.assertIn("2.2", health["primary"]["disk_preflight"]["message"])

                blocked = await service.optimize_and_shrink_database(
                    transcode_limit=0,
                    run_full_vacuum=True,
                )
                self.assertFalse(blocked["ok"])
                self.assertEqual("insufficient_disk_space", blocked["error_code"])
                self.assertIn("2.2", blocked["error"])

                regular = await service.optimize_and_shrink_database(
                    transcode_limit=0,
                    run_full_vacuum=False,
                )
                self.assertTrue(regular["ok"])

            # 2) Concurrent optimize_and_shrink_database rejected cleanly via exclusive asyncio.Lock
            started = asyncio.Event()
            release = asyncio.Event()
            orig_opt = service.store.optimize_and_shrink

            async def _slow_opt(*args, **kwargs):
                started.set()
                await release.wait()
                return await orig_opt(*args, **kwargs)

            with patch.object(service.store, "optimize_and_shrink", side_effect=_slow_opt):
                first_task = asyncio.create_task(
                    service.optimize_and_shrink_database(transcode_limit=0, run_full_vacuum=False)
                )
                await asyncio.wait_for(started.wait(), timeout=2.0)
                second = await service.optimize_and_shrink_database(transcode_limit=0, run_full_vacuum=False)
                self.assertFalse(second["ok"])
                self.assertEqual("db_optimize_in_progress", second["error_code"])
                release.set()
                first = await first_task
                self.assertTrue(first["ok"])
        finally:
            service.close()

    async def test_performance_tuning_and_db_optimize_api_auth_csrf_and_persistence(self) -> None:
        cfg = _SaveableConfig({"startup": {"background_grace_seconds": 0}}, config_path=str(self.tmp_dir / "cfg.json"))
        service = MemoryCompanionService(
            context=SimpleNamespace(),
            config=cfg,
            plugin_root=ROOT,
            data_dir=self.tmp_dir,
        )
        try:
            plugin = SimpleNamespace(service=service, context=SimpleNamespace(), terminated=False)
            api = PluginPageApi(plugin)
            wrapped_tuning = api._wrap_route("/performance/tuning", api.performance_tuning)
            wrapped_csrf = api._wrap_route("/ui/csrf", api.ui_csrf)
            wrapped_optimize = api._wrap_route("/maintenance/db_optimize", api.db_optimize)

            async def _call(fn, *, method="GET", payload=None, headers=None):
                req = SimpleNamespace(
                    args={},
                    method=method,
                    get_json=AsyncMock(return_value=payload if payload is not None else {}),
                )
                if headers is not None:
                    req.headers = headers
                with patch.object(page_api_module, "request", req), patch.object(
                    page_api_module, "jsonify", side_effect=_fake_jsonify
                ):
                    return await fn()

            # 1) GET /performance/tuning succeeds and returns complete metadata
            get_resp = await _call(wrapped_tuning, method="GET")
            self.assertEqual(200, get_resp.status_code)
            tuning = get_resp.payload["tuning"]
            self.assertEqual(5, len(tuning["tiers"]))
            self.assertEqual(4, len(tuning["groups"]))
            self.assertEqual(12, len(tuning["params"]))
            self.assertIn("hardware", tuning)
            self.assertIn("db_summary", tuning)

            # 2) POST /performance/tuning enforces CSRF for browser requests
            browser_headers = {"Origin": "http://127.0.0.1:6185"}
            no_csrf = await _call(
                wrapped_tuning,
                method="POST",
                payload={"profile": "eco"},
                headers=browser_headers,
            )
            self.assertEqual(403, no_csrf.status_code)
            self.assertEqual("csrf_required", no_csrf.payload["error"])

            csrf_resp = await _call(wrapped_csrf, method="GET")
            token = csrf_resp.payload["token"]

            # 3) POST /performance/tuning enforces dashboard admin check
            with patch.object(api, "_dashboard_admin_state", return_value="denied"):
                denied = await _call(
                    wrapped_tuning,
                    method="POST",
                    payload={"profile": "eco", "csrf_token": token},
                    headers=browser_headers,
                )
            self.assertEqual(403, denied.status_code)
            self.assertEqual("admin_required", denied.payload["error"])

            # 4) Valid admin + CSRF persists config & hot-reloads store PRAGMAs + semaphore
            with patch.object(api, "_dashboard_admin_state", return_value="allowed"):
                ok_resp = await _call(
                    wrapped_tuning,
                    method="POST",
                    payload={
                        "profile": "compat",
                        "overrides": {"memory_injection.hook_request_budget_seconds": 6.5},
                        "preserve_overrides": False,
                        "csrf_token": token,
                    },
                    headers=browser_headers,
                )
            self.assertEqual(200, ok_resp.status_code)
            self.assertGreaterEqual(cfg.save_calls, 1)
            saved_tuning = ok_resp.payload["tuning"]
            self.assertEqual("compat", saved_tuning["profile"])
            self.assertEqual(6.5, saved_tuning["effective_values"]["memory_injection.hook_request_budget_seconds"])
            self.assertEqual(1, saved_tuning["override_count"])
            self.assertEqual(2, service.store._conn.execute("PRAGMA synchronous").fetchone()[0])
            self.assertEqual(0, service.store._conn.execute("PRAGMA mmap_size").fetchone()[0])
            self.assertEqual(1, service._embedding_background_concurrency)

            # 5) POST /maintenance/db_optimize returns 400 when 2.2x disk preflight fails
            with (
                patch.object(api, "_dashboard_admin_state", return_value="allowed"),
                patch.object(service.store, "_available_disk_bytes", return_value=1024),
            ):
                low_disk = await _call(
                    wrapped_optimize,
                    method="POST",
                    payload={"run_full_vacuum": True, "transcode_limit": 0, "csrf_token": token},
                    headers=browser_headers,
                )
            self.assertEqual(400, low_disk.status_code)
            self.assertEqual("insufficient_disk_space", low_disk.payload["error_code"])

            # 6) /ui/capabilities marks tuning and db health/optimize routes visible
            cap_resp = await _call(api.ui_capabilities, method="GET")
            by_path = {row["path"]: row for row in cap_resp.payload["endpoints"]}
            for path in ("/performance/tuning", "/maintenance/db_health", "/maintenance/db_optimize"):
                self.assertEqual("visible", by_path[path]["exposure"])
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
