"""V-3 回归契约测试：针对「解决方案输出.md」第九章列出的目标契约。

这些用例覆盖问题 0 / 1 / 2 / 3 / 6 的验收断言。每条用例都先写明它锁定的是
哪一条契约，再断言行为；契约被打破时用例必须变红，而不是被放宽。
"""
from __future__ import annotations

import ast
import inspect
import re
import tempfile
import threading
import unittest
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import coordination_status as coordination_status_module
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext, clean_text
from astrbot_plugin_memory_companion.core.store import MemoryStore

try:  # 字段归属契约的公开常量；未建立时用例必须变红，而不是跳过。
    from astrbot_plugin_memory_companion.core.capability_probe import CAPABILITY_SNAPSHOT_FIELDS
except ImportError:  # pragma: no cover - 契约缺失时由用例断言报错
    CAPABILITY_SNAPSHOT_FIELDS = None


PAGE_API = ROOT / "page_api.py"
PANEL_SCRIPT = ROOT / "pages" / "记忆面板" / "app.js"


def declared_endpoint_fields() -> dict[str, tuple[str, ...]]:
    """读取 page_api.py 的端点字段归属契约（不导入模块，避免依赖宿主 astrbot）。"""
    snapshot_fields = tuple(CAPABILITY_SNAPSHOT_FIELDS or ())
    tree = ast.parse(PAGE_API.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "ENDPOINT_FIELD_CONTRACT":
            continue
        contract: dict[str, tuple[str, ...]] = {}
        for key, value in zip(node.value.keys, node.value.values):
            route = getattr(key, "value", None)
            if not isinstance(route, str):
                continue
            if isinstance(value, ast.Tuple):
                contract[route] = tuple(item.value for item in value.elts)
            elif isinstance(value, ast.Name) and value.id == "CAPABILITY_SNAPSHOT_FIELDS":
                contract[route] = snapshot_fields
        return contract
    return {}


def payload_bindings(source: str) -> dict[str, set[str]]:
    """把 `const [a, b] = await Promise.all([apiGet("/x"), ...])` 解析成变量→端点。

    只有名字数量与端点数量一致的分块才会被采纳，数量不一致时整块跳过，
    并由调用方断言关键端点一定被解析到过。
    """
    bindings: dict[str, set[str]] = {}
    pattern = re.compile(r"const\s*\[([^\]]+)\]\s*=\s*await\s+Promise\.all\(\s*\[(.*?)\]\s*\)", re.S)
    for match in pattern.finditer(source):
        names = [item.strip() for item in match.group(1).split(",") if item.strip()]
        routes = [
            item.rstrip("/")
            for item in re.findall(r"apiGet\(\s*[\"'`](/[^\"'`?${}]*)", match.group(2))
        ]
        if len(names) != len(routes):
            continue
        for name, route in zip(names, routes):
            bindings.setdefault(name, set()).add(route)
    return bindings


class V3RegressionContractTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    def make_service(self):
        from astrbot_plugin_memory_companion.core.service import MemoryCompanionService

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config = {
            "startup": {"background_grace_seconds": 60},
            "memory_summary": {
                "min_events": 1,
                "trigger_event_count": 1,
                "max_events_per_summary": 1,
                "max_retries": 3,
                "retry_backoff_seconds": 0,
                "max_calls_per_session_hour": 6,
            },
        }
        service = MemoryCompanionService(
            context=None,
            config=config,
            plugin_root=ROOT,
            data_dir=Path(temp_dir.name),
        )
        self.addCleanup(service.close)
        service._schedule_memory_embedding = lambda *args: None
        return service

    async def make_batch(self, service, session_id="qq:FriendMessage:v3"):
        event_id = await service.store.add_timeline_event(
            event_type="user_message",
            session_id=session_id,
            scope="private",
            subject_id="v3",
            object_id="bot",
            content="V3 契约测试用的原始消息。",
            metadata={"sender_name": "V3"},
            occurred_at="2026-09-15T01:00:00+00:00",
        )
        rows = list((await service.store.get_timeline_by_ids([event_id])).values())
        batch_id = await service.store.create_summary_batch(session_id, "private", rows)
        return event_id, batch_id

    # ------------------------------------------------------------------
    # 问题 1：buckets 只聚合可召回记忆
    # ------------------------------------------------------------------
    async def test_buckets_exclude_bot_personal_bridge_archive_rows(self) -> None:
        """契约：`list_memory_buckets()` 不得返回 `source_plugin='bot_personal_bridge'` 的行。

        原缺陷：过滤条件是裸 SQL 字符串拼接（`_recallable_memory_sql`），buckets 手写
        SQL 时漏拼，于是 Bot 自身归档行以「私聊」出现在「最近活跃范围」里。治根后过滤
        下沉为 `recallable_memories` 视图，buckets 默认读视图，因此这里直接断言行为。
        """
        store = self.make_store()
        await store.insert_memory(
            MemoryRecord(
                id="v3-bot-personal-archive",
                memory_type="companion_note",
                subject=EntityRef(kind="user", id="archived-window"),
                object=EntityRef.bot_self(bot_id="bot"),
                scope="private",
                session_id="qq:FriendMessage:archived-window",
                visibility="private_pair",
                lifecycle="stable_memory",
                source_plugin="bot_personal_bridge",
                content="bot personal archive reference [v3-contract]",
                occurred_at="2026-09-15T02:00:00+00:00",
                metadata={"owner_bot_id": "bot"},
            )
        )
        await store.insert_memory(
            MemoryRecord(
                id="v3-real-private-memory",
                memory_type="user_preference",
                subject=EntityRef(kind="user", id="v3-user"),
                object=EntityRef.bot_self(bot_id="bot"),
                scope="private",
                session_id="qq:FriendMessage:v3-user",
                visibility="private_pair",
                lifecycle="stable_memory",
                content="V3 真实私聊记忆。",
                occurred_at="2026-09-15T03:00:00+00:00",
                metadata={"owner_bot_id": "bot"},
            )
        )

        buckets = {item["target_id"]: item for item in await store.list_memory_buckets()}
        self.assertNotIn("archived-window", buckets, "Bot 自身归档行不得出现在记忆导航里")
        self.assertIn("v3-user", buckets)

        # 权限拓扑必须能看到归档窗口，否则窗口消失后用户无法再对它授权。
        archived = {
            item["target_id"]: item
            for item in await store.list_memory_buckets(include_archive=True)
        }
        self.assertIn("archived-window", archived, "include_archive=True 必须保留归档窗口")

    # ------------------------------------------------------------------
    # 问题 2：接口字段归属契约
    # ------------------------------------------------------------------
    def test_panel_field_references_are_declared_by_the_backend_contract(self) -> None:
        """契约：面板读取的 `caps.*` / `coord.*` 字段必须由对应端点声明归属。

        原缺陷：`app.js` 从 `/capabilities/bot-personal` 的结果里读 `daily_plan_enabled`
        / `detail_enabled` / `plugin_name` / `reason`，这些都是 `_SNAPSHOT_KEYS` 白名单
        之外的字段，永远不存在 → 联动页两行恒显示「未启用」。治根后 `page_api.py` 用
        `ENDPOINT_FIELD_CONTRACT` 声明每个端点提供的业务字段，本用例据此校验前端引用。
        """
        source = PANEL_SCRIPT.read_text(encoding="utf-8")
        self.assertIsNotNone(CAPABILITY_SNAPSHOT_FIELDS, "后端未声明能力快照字段契约")
        contract = declared_endpoint_fields()
        self.assertTrue(contract.get("/capabilities/bot-personal"), "缺少 /capabilities/bot-personal 字段契约")
        self.assertTrue(
            getattr(coordination_status_module, "COORDINATION_STATUS_FIELDS", None),
            "缺少 /coordination/status 字段契约",
        )

        sample = coordination_status_module.build_coordination_status(
            config=None,
            runtime=None,
            bridge={"health": "unverifiable", "reason_code": "bridge_status_unavailable"},
            p6_raw=None,
        )
        coord_fields = set(sample)
        coord_subfields = {
            key: set(value) for key, value in sample.items() if isinstance(value, dict)
        }

        field_sets: dict[str, set[str]] = {
            "caps": set(contract["/capabilities/bot-personal"])
            | set(contract["/conversation-import/qq/capabilities"]),
            # `coord.status` 不是协调状态字段，而是视图 load() 解包响应信封时读取的键
            # （`return { coord: coord.status || {} }`），与端点契约无关。
            "coord": coord_fields | {"status"},
            "personal": set(contract["/companion/personal-memory"])
            | set(contract["/capabilities/bot-personal"]),
        }

        # 先确认解析真的把关键端点绑到了变量上，避免"解析器失灵 → 断言空转"。
        bindings = payload_bindings(source)
        bound_routes = {route for routes in bindings.values() for route in routes}
        for route in ("/capabilities/bot-personal", "/coordination/status", "/companion/personal-memory"):
            self.assertIn(route, bound_routes, f"未能从 app.js 解析出 {route} 的取数变量")

        undeclared: list[str] = []
        for name, allowed in field_sets.items():
            for field in sorted(set(re.findall(rf"\b{name}\.([A-Za-z_][A-Za-z0-9_]*)", source))):
                if field not in allowed:
                    undeclared.append(f"{name}.{field}")
        self.assertEqual([], undeclared, "面板读取了后端未声明的字段")

        for name in ("coord.runtime", "coord.bridge", "coord.p6"):
            head, tail = name.split(".")
            nested_allowed = coord_subfields.get(tail, set())
            for field in sorted(set(re.findall(rf"\b{re.escape(name)}\.([A-Za-z_][A-Za-z0-9_]*)", source))):
                self.assertIn(field, nested_allowed, f"{name}.{field} 不在后端投影的键集里")

    # ------------------------------------------------------------------
    # 问题 3：阶段总结批次状态机
    # ------------------------------------------------------------------
    async def test_summary_batch_refusal_always_writes_state_before_returning_false(self) -> None:
        """契约：`reserve_summary_call` 返回 False 时，同一事务内必须写入批次状态。

        原缺陷：额度不足分支直接 `return False`（裸返回），批次仍是 `retry_pending`
        且 `next_retry_at` 为空 → 每条新消息都重新选中同一批、重复打 WARN、总结停摆。
        治根后额度不足写「额度释放时刻」，调用次数耗尽进入终态 quarantine。
        """
        service = self.make_service()
        session = "qq:FriendMessage:v3-budget"
        _event_id, batch_id = await self.make_batch(service, session)
        store = service.store

        reserved = await store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=6)
        self.assertTrue(reserved)
        refused = await store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=1)
        self.assertFalse(refused)

        batch = await store.get_summary_batch(batch_id)
        self.assertEqual("retry_pending", batch["state"], "额度不足是暂时状态，不得 quarantine")
        self.assertIsNotNone(batch["next_retry_at"], "拒绝必须写入统一的 next_retry_at")
        self.assertIsNone(
            await store.next_summary_batch(session),
            "被拒绝的批次在退避期内不得再次被选中",
        )

        # 调用次数耗尽属于终态：必须 quarantine 并停止参与自动调度。
        store._conn.execute(
            "UPDATE summary_batches SET automatic_calls=3, next_retry_at=NULL WHERE id=?",
            (batch_id,),
        )
        store._conn.commit()
        self.assertFalse(await store.reserve_summary_call(batch_id, max_calls=3, hourly_limit=6))
        exhausted = await store.get_summary_batch(batch_id)
        self.assertEqual("quarantined", exhausted["state"])

    async def test_quarantined_batch_events_can_be_released_through_explicit_api(self) -> None:
        """契约：quarantined 批次的事件必须能通过显式人工路由释放，不许永久冻结。

        原缺陷：quarantine 后事件归属仍在 `summary_batch_events`，而待总结窗口用
        `exclude_assigned` 排除已归属事件 → 这些原始消息**永远不会**进入任何后续批次，
        且没有任何 API 能解冻。本用例锁定 `release_summary_batch` 的 retry / discard 两条语义。
        """
        service = self.make_service()
        session = "qq:FriendMessage:v3-quarantine"
        event_id, batch_id = await self.make_batch(service, session)
        store = service.store
        self.assertTrue(hasattr(store, "release_summary_batch"), "缺少显式释放 API")

        await store.defer_summary_batch(batch_id, "evidence_gate_rejected", quarantine=True)
        self.assertEqual("quarantined", (await store.get_summary_batch(batch_id))["state"])

        result = await store.release_summary_batch(batch_id)
        self.assertTrue(result["ok"])
        self.assertEqual(1, result["released_events"])
        self.assertEqual("retry_pending", result["state"])
        self.assertEqual(
            0,
            store._conn.execute(
                "SELECT COUNT(*) FROM summary_batch_events WHERE batch_id=?", (batch_id,)
            ).fetchone()[0],
            "retry 释放必须交还事件归属",
        )
        pending = await store.unsummarized_timeline_window(session_id=session, exclude_assigned=True)
        self.assertIn(event_id, [row["id"] for row in pending["rows"]])

        # discard 语义：承认丢失但不再悬空（必须用仍有事件归属的批次验证）。
        discard_session = "qq:FriendMessage:v3-discard"
        discard_event, discard_batch = await self.make_batch(service, discard_session)
        await store.defer_summary_batch(discard_batch, "evidence_gate_rejected", quarantine=True)
        discarded = await store.release_summary_batch(discard_batch, mode="discard")
        self.assertTrue(discarded["ok"])
        self.assertEqual(1, discarded["released_events"])
        self.assertEqual("completed", discarded["state"])
        self.assertTrue(
            (await store.get_timeline_by_ids([discard_event]))[discard_event]["summarized_at"],
            "discard 必须把事件标记为已总结，避免悬空",
        )
        self.assertEqual(
            {"ok": False, "error": "unsupported_release_mode", "mode": "unknown"},
            await store.release_summary_batch(batch_id, mode="unknown"),
        )

    async def test_next_retry_at_null_is_the_only_immediately_due_marker(self) -> None:
        """契约：`next_retry_at` 可空；NULL 才表示「立即可执行」，非空表示该时刻前不得调度。

        原缺陷：列是 `NOT NULL DEFAULT ''`，空串参与 `<=` 比较后退化成「恒真」，
        「从未调度」与「无冷却」两种语义被同一个值表达，队列每轮都重新选中它。
        治根后语义唯一，且由一个 `_due_clause` 收敛全部查询。
        """
        service = self.make_service()
        session = "qq:FriendMessage:v3-due"
        _event_id, batch_id = await self.make_batch(service, session)
        store = service.store

        columns = {
            row["name"]: row for row in store._conn.execute("PRAGMA table_info(summary_batches)")
        }
        self.assertEqual(0, int(columns["next_retry_at"]["notnull"]), "next_retry_at 必须可空")

        fresh = await store.get_summary_batch(batch_id)
        self.assertIsNone(fresh["next_retry_at"], "新批次必须是 NULL 而不是空串")
        self.assertIsNotNone(await store.next_summary_batch(session), "NULL 表示立即可执行")

        await store.defer_summary_batch(batch_id, "transient", delay=3600)
        deferred = await store.get_summary_batch(batch_id)
        self.assertIsNotNone(deferred["next_retry_at"])
        self.assertIsNone(await store.next_summary_batch(session), "未到期批次不得被调度")
        self.assertIsNotNone(
            await store.next_summary_batch(session, force=True),
            "force 路径是显式人工入口，必须能拿到未到期批次",
        )

    # ------------------------------------------------------------------
    # 问题 6：ACL 缓存失效
    # ------------------------------------------------------------------
    async def test_acl_policy_change_invalidates_registered_caches(self) -> None:
        """契约：ACL 策略变更后，开关读取必须立即看到新值，且注册过的缓存被广播失效。

        原缺陷：`_acl_feature_override_cache` 是写穿透副本，只依赖「每个写路径都记得
        更新它」，既没有清库通知也没有失效广播（全仓零 clear/pop/revision 比对）。
        治根后：热路径读进程内投影，写路径提交后发布，其余缓存注册失效回调。
        """
        store = self.make_store()
        window = ("private", "v3-acl-window")
        self.assertEqual(
            {"capture_enabled": None, "recall_enabled": None},
            store.get_scope_feature_override_sync(*window),
        )

        cleared: list[str] = []
        store.register_invalidation("v3_probe_cache", lambda: cleared.append("v3_probe_cache"))
        await store.upsert_acl_policy(
            window_scope=window[0],
            window_id=window[1],
            read_mode="whitelist",
            share_mode="whitelist",
            capture_enabled=False,
            recall_enabled=False,
        )
        self.assertEqual(
            {"capture_enabled": False, "recall_enabled": False},
            store.get_scope_feature_override_sync(*window),
            "策略写入后热路径必须立即返回新值",
        )

        await store.upsert_acl_policy(
            window_scope=window[0],
            window_id=window[1],
            capture_enabled=True,
            recall_enabled=True,
        )
        self.assertEqual(
            {"capture_enabled": True, "recall_enabled": True},
            store.get_scope_feature_override_sync(*window),
        )
        cleared_by_reconcile = store.invalidate_registered_caches(reason="v3-contract")
        self.assertIn("v3_probe_cache", cleared_by_reconcile)
        self.assertEqual(["v3_probe_cache"], cleared)
        self.assertGreaterEqual(
            store.rebuild_acl_projection_sync(),
            1,
            "投影必须能从数据库整体重建（后台对账路径）",
        )

    async def test_batch_import_rollback_does_not_leak_acl_projection_values(self) -> None:
        """契约：批量导入中未提交的 ACL 策略不得进入进程内投影（SAVEPOINT/外层回滚同理）。

        原缺陷：`_upsert_acl_policy_sync` 在写库之后**无条件**写缓存；批量导入以
        `_commit=False` 调用它，一旦该单元回滚，数据库回滚而缓存保留未提交值 →
        「库已关闭、缓存仍开启」的隐私风险方向。治根后提交前只暂存、提交后才发布。
        """
        store = self.make_store()
        window = ("private", "v3-rollback-window")

        with self.assertRaises(RuntimeError):
            with store._lock:
                with store._transaction_sync():
                    store._upsert_acl_policy_sync(
                        window[0],
                        window[1],
                        "whitelist",
                        "whitelist",
                        capture_enabled=False,
                        recall_enabled=False,
                        _commit=False,
                    )
                    raise RuntimeError("v3 injected rollback")

        self.assertEqual(
            {"capture_enabled": None, "recall_enabled": None},
            store.get_scope_feature_override_sync(*window),
            "回滚后投影不得保留脏值",
        )
        self.assertEqual(
            0,
            store._conn.execute(
                "SELECT COUNT(*) FROM memory_acl_policies WHERE window_id=?", (window[1],)
            ).fetchone()[0],
        )

        # 正向对照：同批中成功提交的策略必须可见，单项失败不得连带丢失。
        ok_window = ("private", "v3-committed-window")
        results = await store.import_batch_ops(
            [
                {
                    "kind": "acl_policy",
                    "params": {
                        "window_scope": ok_window[0],
                        "window_id": ok_window[1],
                        "read_mode": "whitelist",
                        "share_mode": "whitelist",
                        "capture_enabled": True,
                        "recall_enabled": True,
                    },
                },
                {"kind": "memory", "record": object()},
            ]
        )
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertEqual(
            {"capture_enabled": True, "recall_enabled": True},
            store.get_scope_feature_override_sync(*ok_window),
        )

    async def test_clear_all_memory_data_empties_acl_projection(self) -> None:
        """契约：清库之后 ACL 投影必须为空，窗口开关不得再回答已删除的策略。

        原缺陷：`_clear_all_memory_data_sync` 删 `memory_acl_policies` 却不碰缓存，
        service 层的清库也只清自己的 7 个缓存、不通知 store → 清库后开关仍是旧值。
        """
        store = self.make_store()
        window = ("group", "v3-clear-window")
        await store.upsert_acl_policy(
            window_scope=window[0],
            window_id=window[1],
            read_mode="blacklist",
            share_mode="blacklist",
            capture_enabled=False,
            recall_enabled=False,
        )
        self.assertEqual(
            {"capture_enabled": False, "recall_enabled": False},
            store.get_scope_feature_override_sync(*window),
        )

        deleted = await store.clear_all_memory_data()
        self.assertIn("memory_acl_policies", deleted["deleted"])
        self.assertEqual(
            {"capture_enabled": None, "recall_enabled": None},
            store.get_scope_feature_override_sync(*window),
            "清库后投影必须为空",
        )
        self.assertEqual([], await store.list_acl_policies())

    # ------------------------------------------------------------------
    # 问题 0：backup 不得阻塞事件循环
    # ------------------------------------------------------------------
    async def test_backup_async_runs_outside_the_event_loop_thread(self) -> None:
        """契约：`backup_async()` 必须把整库拷贝放到工作线程，不得在事件循环线程执行。

        原缺陷：`backup()` 是同步方法却在 6 处 async 函数里被直接调用，而
        `sqlite3.Connection.backup` 要重写全部页并全程持主写锁；生产库 890MB 时
        直接堵死 AstrBot 事件循环。治根后新增 `backup_async()`（内部 to_thread），
        同步版本保留给已在工作线程内的调用方。
        """
        store = self.make_store()
        self.assertTrue(hasattr(store, "backup_async"), "缺少 backup_async")
        loop_thread = threading.get_ident()
        seen: list[int] = []
        original = store.backup

        def probe(suffix: str = "") -> Path:
            seen.append(threading.get_ident())
            return original(suffix)

        store.backup = probe  # type: ignore[method-assign]
        try:
            target = await store.backup_async(".v3")
        finally:
            store.backup = original  # type: ignore[method-assign]

        self.assertTrue(seen, "backup_async 必须真正调用备份")
        self.assertNotEqual(loop_thread, seen[0], "整库拷贝不得在事件循环线程执行")
        self.assertTrue(target.exists())
        self.assertTrue(inspect.iscoroutinefunction(store.backup_async))


if __name__ == "__main__":
    unittest.main()
