from __future__ import annotations

import asyncio
import base64
import copy
import json
import hashlib
import inspect
import logging
import mimetypes
import re
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from quart import jsonify, request, send_file

try:
    from astrbot.api.web import request as astrbot_web_request
except Exception:  # pragma: no cover - optional in isolated page tests.
    astrbot_web_request = None

from .core.bridge import serialize_memory
from .core.coordination_status import build_coordination_status, project_p6_status
from .core.identity import normalize_session_context_fields, parse_scope_from_session
from .core.memory_atom import DURABILITY_LEVELS, SENSITIVITY_LEVELS, VALIDITY_STATUSES
from .core.models import SessionContext, clean_text
from .companion_page_bridge import (
    COMPANION_PLUGIN_ID,
    CompanionPageBridge,
    CompanionPageBridgeError,
    CompanionPagePhoto,
    CompanionPageSnapshot,
)

PLUGIN_NAME = "astrbot_plugin_memory_companion"
PAGE_API_PREFIXES = (f"/{PLUGIN_NAME}/page",)

logger = logging.getLogger("MemoryCompanion.PageAPI")

THEME_NAME_TO_KEY = {
    "黄白游": "huangbaiyou",
    "天缥": "tianpiao",
    "海天霞": "haitianxia",
    "盈盈": "yingying",
    "欧碧": "oubi",
    "青冥": "qingming",
    "紫蒲": "zipu",
    "山岚": "shanlan",
    "窃蓝": "qielan",
    "退红": "tuihong",
    "葱倩": "congqing",
    "月白": "yuebai",
    "墨黪": "mocan",
    "骨缥": "gupiao",
}
THEME_KEYS = set(THEME_NAME_TO_KEY.values())
DEFAULT_THEME_NAME = "月白"
DEFAULT_THEME_KEY = THEME_NAME_TO_KEY[DEFAULT_THEME_NAME]

UI_CONTRACT_VERSION = "memory.page.ui.v2"
UI_MODES = (
    {"id": "standard", "label": "简洁管理"},
    {"id": "cinema", "label": "放映馆界面"},
)
UI_VIEW_ENDPOINTS = {
    "overview": ("/stats", "/buckets"),
    "users": (
        "/memories",
        "/memory",
        "/memory/update",
        "/memory/rebind-owner",
        "/memory/delete",
        "/portrait/profiles",
        "/portrait/profile",
        "/portrait/govern",
        "/maintenance/clear_scope",
    ),
    "groups": (
        "/memories",
        "/memory",
        "/memory/update",
        "/memory/delete",
        "/maintenance/clear_scope",
    ),
    "personal": ("/companion/personal-memory", "/companion/personal-photo-data"),
    "knowledge": (
        "/graph",
        "/relations",
        "/threads",
        "/thread/status",
        "/timeline",
        "/logs",
        "/persona-state",
        "/emotion/traces",
        "/emotion/trace",
    ),
    "microscope": ("/search",),
    "archive": (
        "/core-memory",
        "/core-memory/upsert",
        "/core-memory/delete",
        "/context/config",
        "/config/schema",
        "/config/module/update",
        "/retrieval/config/update",
        "/operations/diagnostics",
        "/operations/preset",
        "/maintenance",
        "/maintenance/audit/preview",
        "/maintenance/audit/status",
        "/maintenance/audit/apply",
        "/maintenance/audit/rollback",
        "/data/export",
        "/data/import/preview",
        "/data/import/run",
        "/conversation-import/targets",
        "/conversation-import/qq/capabilities",
        "/conversation-import/qq/preview",
        "/conversation-import/upload",
        "/conversation-import/start",
        "/conversation-import/status",
        "/conversation-import/pause",
        "/conversation-import/resume",
        "/conversation-import/rebind",
        "/conversation-import/rollback",
        "/maintenance/repair_livingmemory_content",
        "/maintenance/clear_all",
        "/import/livingmemory/preview",
        "/import/livingmemory/run",
        "/acl/matrix",
        "/acl/upsert",
        "/acl/delete",
    ),
}

# The panel uses stable, user-facing categories while the store keeps the
# more specific memory types written by each producer. Keep this mapping at
# the API boundary so filtering a category does not accidentally query a
# literal type that is never persisted.
MEMORY_TYPE_FILTERS = {
    "profile": ("profile", "user_profile", "user_habit"),
    "preference": ("preference", "user_preference"),
    "relationship": ("relationship", "relationship_claim", "relationship_phase_summary"),
    "fact": ("fact", "stable_fact", "user_fact", "manual_memory", "explicit_memory"),
    "event": ("event", "conversation_event", "important_event", "timeline_event"),
    "state": ("state", "current_state", "stable_state", "stable_fact"),
    "promise": ("promise", "promise_memory"),
    "schedule": ("schedule", "schedule_fragment", "daily_digest"),
    "thought": ("thought", "companion_note", "internal_note"),
}

MEMORY_LIFECYCLE_FILTERS = {
    "active": ("active", "current_window", "recent", "open_loop", "planned_projection", "stable_memory"),
    "stable": ("stable", "stable_memory"),
    "fading": ("fading", "recent"),
    "archived": ("archived",),
    "expired": ("expired",),
}

MEMORY_VISIBILITY_FILTERS = {
    "public": ("public", "group_public"),
    "private": ("private", "private_pair"),
    "group_shared": ("group_shared", "group_public"),
    "bot_self": ("bot_self",),
    "restricted": ("restricted", "internal"),
}
UI_ENDPOINT_EXPOSURE = {
    "/ui/capabilities": {"exposure": "internal", "reason": "前端启动时用于自校验，不作为业务按钮"},
    "/memory/visibility": {"exposure": "compat", "reason": "由统一 memory/update 表单覆盖"},
    "/memory/lifecycle": {"exposure": "compat", "reason": "由统一 memory/update 表单覆盖"},
    "/acl": {"exposure": "compat", "reason": "当前权限拓扑使用聚合 matrix 端点"},
    "/acl/policy": {"exposure": "advanced", "reason": "保留给高级策略调用，普通拓扑按规则管理"},
    "/coordination/status": {"exposure": "internal", "reason": "由个人记忆和统计投影聚合展示"},
    "/profiles": {"exposure": "compat", "reason": "旧 Bot profile 查询兼容入口"},
    "/user-memory-summary": {"exposure": "compat", "reason": "旧用户摘要工作区兼容入口"},
    "/portrait/migration": {"exposure": "internal", "reason": "画像迁移控制，不向普通面板暴露"},
    "/capabilities/bot-personal": {"exposure": "internal", "reason": "跨插件能力探测"},
    "/companion/personal-photo": {"exposure": "internal", "reason": "图片代理兼容入口"},
    "/companion/personal-photo-data": {"exposure": "visible", "reason": "个人相册按需加载的数据端点"},
    "/maintenance/sleep": {"exposure": "compat", "reason": "页面使用统一 maintenance 操作，保留状态/命令兼容"},
}
UI_DANGEROUS_ENDPOINTS = frozenset(
    {
        "/memory/delete",
        "/core-memory/delete",
        "/portrait/govern",
        "/maintenance/audit/apply",
        "/maintenance/audit/rollback",
        "/data/import/run",
        "/conversation-import/rollback",
        "/maintenance/clear_all",
        "/maintenance/clear_scope",
        "/import/livingmemory/run",
    }
)


class PluginPageApi:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self._companion_page_bridge = CompanionPageBridge(plugin)
        self._emotion_page_admin_capability = None
        bridge = getattr(plugin, "memory_companion", None)
        binder = getattr(bridge, "bind_emotion_page_api", None)
        if callable(binder):
            try:
                self._emotion_page_admin_capability = binder(self)
            except Exception:
                self._emotion_page_admin_capability = None

    def _route_specs(self) -> list[tuple[str, Any, list[str], str]]:
        return [
            ("/ui/capabilities", self.ui_capabilities, ["GET"], "MemoryCompanion UI capability contract"),
            ("/stats", self.stats, ["GET"], "MemoryCompanion Page stats"),
            ("/buckets", self.buckets, ["GET"], "MemoryCompanion Page buckets"),
            ("/memories", self.memories, ["GET"], "MemoryCompanion Page memories"),
            ("/memory", self.memory_detail, ["GET"], "MemoryCompanion Page memory detail"),
            ("/memory/update", self.memory_update, ["POST"], "MemoryCompanion Page memory update"),
            ("/memory/rebind-owner", self.memory_rebind_owner, ["POST"], "MemoryCompanion Page memory owner rebind"),
            ("/memory/delete", self.memory_delete, ["POST"], "MemoryCompanion Page memory delete"),
            ("/memory/visibility", self.memory_visibility, ["POST"], "MemoryCompanion Page memory visibility"),
            ("/memory/lifecycle", self.memory_lifecycle, ["POST"], "MemoryCompanion Page memory lifecycle"),
            ("/core-memory", self.core_memory_list, ["GET"], "MemoryCompanion core memory blocks"),
            ("/core-memory/upsert", self.core_memory_upsert, ["POST"], "MemoryCompanion core memory upsert"),
            ("/core-memory/delete", self.core_memory_delete, ["POST"], "MemoryCompanion core memory delete"),
            ("/acl", self.acl, ["GET"], "MemoryCompanion Page memory ACL rules"),
            ("/acl/upsert", self.acl_upsert, ["POST"], "MemoryCompanion Page memory ACL upsert"),
            ("/acl/policy", self.acl_policy, ["POST"], "MemoryCompanion Page memory ACL policy"),
            ("/acl/delete", self.acl_delete, ["POST"], "MemoryCompanion Page memory ACL delete"),
            ("/search", self.search, ["POST"], "MemoryCompanion Page search"),
            ("/timeline", self.timeline, ["GET"], "MemoryCompanion Page timeline"),
            ("/relations", self.relations, ["GET"], "MemoryCompanion Page relations"),
            ("/graph", self.graph, ["GET"], "MemoryCompanion Page knowledge graph"),
            ("/threads", self.threads, ["GET"], "MemoryCompanion Page threads"),
            ("/thread/status", self.thread_status, ["POST"], "MemoryCompanion Page thread status"),
            ("/logs", self.logs, ["GET"], "MemoryCompanion Page injection logs"),
            ("/context/config", self.context_config, ["GET"], "MemoryCompanion Page context config"),
            ("/config/schema", self.config_schema, ["GET"], "MemoryCompanion Page config schema"),
            ("/config/module/update", self.config_module_update, ["POST"], "MemoryCompanion Page config module update"),
            ("/retrieval/config/update", self.retrieval_config_update, ["POST"], "MemoryCompanion Page retrieval config update"),
            ("/operations/diagnostics", self.operations_diagnostics, ["GET"], "MemoryCompanion operations diagnostics"),
            ("/emotion/trace", self.emotion_trace, ["GET"], "MemoryCompanion redacted emotion trace"),
            ("/emotion/traces", self.emotion_traces, ["GET"], "MemoryCompanion redacted emotion trace list"),
            ("/coordination/status", self.coordination_status, ["GET"], "MemoryCompanion safe coordination status"),
            ("/operations/preset", self.operations_preset, ["GET", "POST"], "MemoryCompanion operations preset"),
            ("/data/export", self.data_export, ["POST"], "MemoryCompanion portable data export"),
            ("/data/import/preview", self.data_import_preview, ["GET"], "MemoryCompanion portable data preview"),
            ("/data/import/run", self.data_import_run, ["POST"], "MemoryCompanion portable data import"),
            ("/conversation-import/qq/capabilities", self.conversation_import_qq_capabilities, ["GET"], "MemoryCompanion QQ history capabilities"),
            ("/conversation-import/qq/preview", self.conversation_import_qq_preview, ["POST"], "MemoryCompanion QQ history preview"),
            ("/conversation-import/upload", self.conversation_import_upload, ["POST"], "MemoryCompanion historical chat upload"),
            ("/conversation-import/start", self.conversation_import_start, ["POST"], "MemoryCompanion historical chat start"),
            ("/conversation-import/status", self.conversation_import_status, ["GET"], "MemoryCompanion historical chat status"),
            ("/conversation-import/targets", self.conversation_import_targets, ["GET"], "MemoryCompanion historical chat private targets"),
            ("/conversation-import/pause", self.conversation_import_pause, ["POST"], "MemoryCompanion historical chat pause"),
            ("/conversation-import/resume", self.conversation_import_resume, ["POST"], "MemoryCompanion historical chat resume"),
            ("/conversation-import/rebind", self.conversation_import_rebind, ["POST"], "MemoryCompanion historical chat rebind"),
            ("/conversation-import/rollback", self.conversation_import_rollback, ["POST"], "MemoryCompanion historical chat rollback"),
            ("/profiles", self.profiles, ["GET"], "MemoryCompanion Bot Profiles"),
            ("/user-memory-summary", self.user_memory_summary, ["GET"], "MemoryCompanion User Memory workspace summary"),
            ("/portrait/profiles", self.portrait_profiles, ["GET"], "MemoryCompanion unified portrait profiles"),
            ("/portrait/profile", self.portrait_profile, ["GET"], "MemoryCompanion unified portrait governance detail"),
            ("/portrait/govern", self.portrait_govern, ["POST"], "MemoryCompanion unified portrait governance"),
            ("/portrait/migration", self.portrait_migration, ["POST"], "MemoryCompanion portrait migration control"),
            ("/capabilities/bot-personal", self.bot_personal_capabilities, ["GET"], "MemoryCompanion Bot Personal capability"),
            ("/companion/personal-memory", self.companion_personal_memory, ["GET"], "MemoryCompanion Page companion personal memory"),
            ("/companion/personal-photo", self.companion_personal_photo, ["GET"], "MemoryCompanion Page companion personal photo"),
            ("/companion/personal-photo-data", self.companion_personal_photo_data, ["GET"], "MemoryCompanion Page companion personal photo data"),
            ("/maintenance", self.maintenance, ["POST"], "MemoryCompanion Page maintenance"),
            ("/maintenance/sleep", self.sleep_maintenance, ["GET", "POST"], "MemoryCompanion Page sleep maintenance"),
            ("/maintenance/audit/preview", self.audit_preview, ["POST"], "MemoryCompanion memory audit preview"),
            ("/maintenance/audit/status", self.audit_status, ["GET"], "MemoryCompanion memory audit status"),
            ("/maintenance/audit/apply", self.audit_apply, ["POST"], "MemoryCompanion memory audit apply"),
            ("/maintenance/audit/rollback", self.audit_rollback, ["POST"], "MemoryCompanion memory audit rollback"),
            ("/maintenance/repair_livingmemory_content", self.repair_livingmemory_content, ["POST"], "MemoryCompanion Page repair LivingMemory content"),
            ("/maintenance/clear_all", self.clear_all, ["POST"], "MemoryCompanion Page clear all memory data"),
            ("/maintenance/clear_scope", self.clear_scope, ["POST"], "MemoryCompanion Page clear scoped memory data"),
            ("/import/livingmemory/preview", self.import_preview, ["GET"], "MemoryCompanion Page import preview"),
            ("/import/livingmemory/run", self.import_run, ["POST"], "MemoryCompanion Page import run"),
            ("/persona-state", self.persona_state, ["GET"], "MemoryCompanion Page persona state"),
            ("/acl/matrix", self.acl_matrix, ["GET"], "MemoryCompanion Page ACL matrix"),
        ]

    def register_routes(self) -> None:
        register = self.plugin.context.register_web_api
        for prefix in PAGE_API_PREFIXES:
            for route, handler, methods, desc in self._route_specs():
                register(f"{prefix}{route}", handler, methods, desc)

    async def ui_capabilities(self):
        routes = self._route_specs()
        endpoint_views: dict[str, list[str]] = {}
        for view, endpoints in UI_VIEW_ENDPOINTS.items():
            for endpoint in endpoints:
                endpoint_views.setdefault(endpoint, []).append(view)
        return self._ok(
            {
                "contract_version": UI_CONTRACT_VERSION,
                "modes": list(UI_MODES),
                "views": [
                    {"id": view, "endpoints": list(endpoints)}
                    for view, endpoints in UI_VIEW_ENDPOINTS.items()
                ],
                "endpoints": [
                    {
                        "path": path,
                        "methods": list(methods),
                        "description": description,
                        "exposure": UI_ENDPOINT_EXPOSURE.get(path, {}).get("exposure", "visible"),
                        "reason": UI_ENDPOINT_EXPOSURE.get(path, {}).get("reason", "面板直接功能"),
                        "views": endpoint_views.get(path, []),
                        "dangerous": path in UI_DANGEROUS_ENDPOINTS,
                    }
                    for path, _handler, methods, description in routes
                ],
            }
        )

    async def stats(self):
        stats = await self.plugin.service.store.stats()
        stats.pop("pending_review", None)
        return self._ok({"stats": stats})

    async def profiles(self):
        profile = clean_text(request.args.get("profile", ""), 80)
        query = clean_text(request.args.get("query", ""), 240)
        current_date = clean_text(request.args.get("date", ""), 20)
        current_window = clean_text(request.args.get("window", ""), 40)
        try:
            limit = max(1, min(100, int(request.args.get("limit", "10"))))
        except (TypeError, ValueError):
            limit = 10
        result = await self.plugin.service.read_bot_profile(
            profile,
            query=query,
            limit=limit,
            current_date=current_date,
            current_window=current_window,
            authorized=False,
        )
        return self._ok({"result": result})

    async def user_memory_summary(self):
        user_id = clean_text(request.args.get("user_id", ""), 120)
        session_id = clean_text(request.args.get("session_id", ""), 200)
        try:
            limit = max(1, min(8, int(request.args.get("limit", "6"))))
        except (TypeError, ValueError):
            limit = 6
        reader = getattr(getattr(self.plugin, "service", None), "read_user_memory_summary", None)
        if not callable(reader):
            result = {
                "contract": "memory.user_memory_summary.v1",
                "ok": False,
                "read_only": True,
                "state": "degraded",
                "degraded": True,
                "pending": True,
                "user_id": user_id,
                "session_id": session_id,
                "counts": {"profile": 0, "preference": 0, "relationship": 0, "private_conversation": 0, "other": 0, "total": 0},
                "summaries": [],
                "workspace": {"kind": "memory_user_workspace", "route_hint": "user_memory", "user_id": user_id},
                "error_code": "bridge_method_unavailable",
            }
        else:
            try:
                result = await reader(user_id, session_id=session_id, limit=limit)
            except Exception:
                result = {
                    "contract": "memory.user_memory_summary.v1",
                    "ok": False,
                    "read_only": True,
                    "state": "degraded",
                    "degraded": True,
                    "pending": True,
                    "user_id": user_id,
                    "session_id": session_id,
                    "counts": {"profile": 0, "preference": 0, "relationship": 0, "private_conversation": 0, "other": 0, "total": 0},
                    "summaries": [],
                    "workspace": {"kind": "memory_user_workspace", "route_hint": "user_memory", "user_id": user_id},
                    "error_code": "summary_unavailable",
                }
        return self._ok({"result": result})

    async def portrait_profiles(self):
        try:
            limit = max(1, min(500, int(request.args.get("limit", "100"))))
        except (TypeError, ValueError):
            limit = 100
        portraits = getattr(getattr(self.plugin, "service", None), "portraits", None)
        if portraits is None:
            return self._ok({"items": [], "state": "bridge_unavailable"})
        try:
            items = await portraits.list_governance_profiles(limit=limit)
        except Exception:
            logger.exception("统一画像列表读取失败")
            return self._err("统一画像列表读取失败", 500)
        return self._ok({"items": items, "state": "ready"})

    async def portrait_profile(self):
        person_id = clean_text(request.args.get("person_id", ""), 80)
        if not person_id:
            return self._err("缺少 person_id", 400)
        portraits = getattr(getattr(self.plugin, "service", None), "portraits", None)
        if portraits is None:
            return self._ok({"result": {"ok": False, "code": "bridge_unavailable", "person": {}, "facts": [], "suppressions": []}})
        try:
            result = await portraits.governance_detail(person_id)
        except Exception:
            logger.exception("统一画像详情读取失败")
            return self._err("统一画像详情读取失败", 500)
        return self._ok({"result": result})

    async def portrait_govern(self):
        payload = await self._json()
        portraits = getattr(getattr(self.plugin, "service", None), "portraits", None)
        if portraits is None:
            return self._err("统一画像服务不可用", 503)
        try:
            result = await portraits.govern_fact(
                person_id=clean_text(payload.get("person_id"), 80),
                fact_id=clean_text(payload.get("fact_id"), 120),
                action=clean_text(payload.get("action"), 40),
                actor="page_administrator",
                operation_id=clean_text(payload.get("operation_id"), 120),
                expires_at=clean_text(payload.get("expires_at"), 80),
            )
        except Exception:
            logger.exception("统一画像治理失败")
            return self._err("统一画像治理失败", 500)
        return self._ok({"result": result})

    async def portrait_migration(self):
        payload = await self._json()
        mode = clean_text(payload.get("mode"), 40) or "dry_run"
        operation_id = clean_text(payload.get("operation_id"), 120)
        portraits = getattr(getattr(self.plugin, "service", None), "portraits", None)
        if portraits is None:
            return self._err("统一画像服务不可用", 503)
        if not operation_id:
            return self._err("缺少 operation_id", 400)
        try:
            if mode == "dry_run":
                result = await portraits.migrate_legacy(operation_id=operation_id, dry_run=True)
            elif mode == "apply":
                result = await portraits.migrate_legacy(operation_id=operation_id, dry_run=False)
            elif mode == "rollback":
                result = await portraits.rollback_legacy_migration(operation_id=operation_id)
            else:
                return self._err("无效的迁移模式", 400)
        except Exception:
            logger.exception("统一画像迁移操作失败")
            return self._err("统一画像迁移操作失败", 500)
        return self._ok({"result": result})

    async def bot_personal_capabilities(self):
        getter = getattr(self.plugin, "bot_personal_capability_status", None)
        result = getter() if callable(getter) else {
            "available": False,
            "state": "degraded",
            "degraded": True,
            "warnings": ["capability_status_unavailable"],
        }
        return self._ok({"result": result if isinstance(result, dict) else {}})

    async def operations_diagnostics(self):
        try:
            return self._ok({"diagnostics": await self.plugin.service.operational_report()})
        except Exception as exc:
            return self._err(f"运维诊断失败: {exc}", 500)

    async def emotion_trace(self):
        context = self._trusted_emotion_admin_context()
        if context is None:
            return self._err("admin_required", 403)
        trace_id = clean_text(request.args.get("trace_id", ""), 96)
        if not trace_id:
            return self._err("缺少 trace_id", 400)
        bridge = getattr(self.plugin, "memory_companion", None)
        getter = getattr(bridge, "get_emotion_trace_diagnostic", None)
        if not callable(getter):
            return self._ok({"result": {"state": "degraded", "read_only": True, "items": [], "error_code": "bridge_method_unavailable"}})
        return self._ok({"result": await getter(trace_id, context, limit=100)})

    async def emotion_traces(self):
        context = self._trusted_emotion_admin_context()
        if context is None:
            return self._err("admin_required", 403)
        bridge = getattr(self.plugin, "memory_companion", None)
        getter = getattr(bridge, "get_emotion_trace_summary", None)
        if not callable(getter):
            return self._ok({"result": {"state": "degraded", "read_only": True, "items": [], "error_code": "bridge_method_unavailable"}})
        return self._ok({"result": await getter(
            context,
            cursor=clean_text(request.args.get("cursor", ""), 20),
            limit=max(1, min(100, self._int(request.args.get("limit", "20"), 20))),
        )})

    def _trusted_emotion_admin_context(self) -> Any | None:
        """Construct diagnostic authority only from AstrBot's bound dashboard user."""

        if not self._is_bound_dashboard_admin():
            return None
        bridge = getattr(self.plugin, "memory_companion", None)
        creator = getattr(bridge, "create_emotion_admin_context", None)
        if not callable(creator) or self._emotion_page_admin_capability is None:
            return None
        try:
            return creator(
                self._emotion_page_admin_capability,
                bot_id=clean_text(request.args.get("bot_id", ""), 160),
                scope=clean_text(request.args.get("scope", ""), 24),
                session_id=clean_text(request.args.get("session_id", ""), 220),
            )
        except Exception:
            return None

    def _is_bound_dashboard_admin(self) -> bool:
        """Accept only the framework-injected dashboard user, never request claims."""

        bound_request = astrbot_web_request
        if bound_request is None:
            return False
        try:
            username = clean_text(bound_request.username, 160)
        except Exception:
            return False
        context = getattr(self.plugin, "context", None)
        config_getter = getattr(context, "get_config", None)
        if not callable(config_getter):
            return False
        try:
            config = config_getter()
        except Exception:
            return False
        dashboard = config.get("dashboard") if isinstance(config, dict) else None
        expected_username = clean_text(
            dashboard.get("username") if isinstance(dashboard, dict) else "",
            160,
        )
        return bool(username and expected_username and username == expected_username)

    async def coordination_status(self):
        """Expose a fixed, read-only coordination projection."""
        try:
            service = getattr(self.plugin, "service", None)
            p6_raw, bridge = self._companion_p6_status(service)
            status = build_coordination_status(
                config=getattr(service, "config", None),
                runtime={"compatibility_level": "full"},
                bridge=bridge,
                p6_raw=p6_raw,
            )
        except Exception:
            status = build_coordination_status(
                config=None,
                runtime=None,
                bridge={"health": "unverifiable", "reason_code": "bridge_status_unavailable"},
                p6_raw=None,
            )
        return self._ok({"status": status})

    def _companion_p6_status(self, service: Any) -> tuple[Any, dict[str, str]]:
        config = getattr(service, "config", None)
        getter = getattr(config, "bool", None)
        if not callable(getter):
            return None, {"health": "unverifiable", "reason_code": "bridge_config_unavailable"}
        try:
            enabled = getter("private_companion_bridge.enabled", True)
        except Exception:
            return None, {"health": "unverifiable", "reason_code": "bridge_config_unreadable"}
        if type(enabled) is not bool:
            return None, {"health": "unverifiable", "reason_code": "bridge_config_invalid"}
        if not enabled:
            return None, {"health": "degraded", "reason_code": "bridge_disabled"}
        try:
            p6_raw = self._companion_page_bridge.read_p6_status()
        except CompanionPageBridgeError as exc:
            reason = exc.code
            if reason == "companion_p6_producer_stale":
                reason = "companion_p6_producer_unreadable"
            elif not reason.startswith("companion_p6_"):
                reason = "companion_api_unavailable"
            return None, {"health": "unverifiable", "reason_code": reason}
        p6 = project_p6_status(p6_raw)
        if p6["health"] == "ready":
            return p6_raw, {"health": "ready", "reason_code": "companion_bridge_available"}
        return p6_raw, {"health": "degraded", "reason_code": "companion_p6_unverifiable"}

    async def operations_preset(self):
        if request.method == "GET":
            return self._ok({"preset": self.plugin.service.operation_preset_status()})
        payload = await self._json()
        try:
            result = self.plugin.service.apply_operation_preset(clean_text(payload.get("preset"), 40))
            return self._ok({"preset": result})
        except ValueError as exc:
            return self._err(str(exc), 400)
        except Exception as exc:
            return self._err(f"应用预设失败: {exc}", 500)

    async def data_export(self):
        try:
            return self._ok({"result": await self.plugin.service.export_portable_data()})
        except Exception as exc:
            return self._err(f"导出失败: {exc}", 500)

    async def data_import_preview(self):
        path = clean_text(request.args.get("path", ""), 2000)
        if not path:
            return self._err("path is required", 400)
        try:
            return self._ok({"result": self.plugin.service.preview_portable_data(path)})
        except (OSError, ValueError) as exc:
            return self._err(str(exc), 400)

    async def data_import_run(self):
        payload = await self._json()
        path = clean_text(payload.get("path"), 2000)
        if not path:
            return self._err("path is required", 400)
        try:
            return self._ok({"result": await self.plugin.service.import_portable_data(path)})
        except (OSError, ValueError) as exc:
            return self._err(str(exc), 400)
        except Exception as exc:
            return self._err(f"导入失败: {exc}", 500)

    async def conversation_import_upload(self):
        payload = await self._json()
        filename = clean_text(payload.get("filename"), 240) or "conversation.txt"
        encoded = str(payload.get("content_base64") or "").strip()
        if not encoded:
            return self._err("content_base64 is required", 400)
        if "," in encoded and encoded.lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            content = base64.b64decode(encoded, validate=True)
            result = await asyncio.to_thread(
                self.plugin.service.preview_historical_chat_upload,
                filename=filename,
                content=content,
                base_year=int(payload.get("base_year") or 0),
            )
            return self._ok({"result": result})
        except (ValueError, OSError) as exc:
            return self._err(str(exc), 400)
        except Exception as exc:
            logger.exception("历史对话预览失败")
            return self._err(f"历史对话预览失败: {exc}", 500)

    async def conversation_import_qq_capabilities(self):
        try:
            result = await self.plugin.service.qq_history_capabilities()
            return self._ok({"result": result})
        except Exception as exc:
            logger.exception("QQ 历史读取能力检测失败")
            return self._err(f"QQ 历史读取能力检测失败: {exc}", 500)

    async def conversation_import_qq_preview(self):
        payload = await self._json()
        try:
            result = await self.plugin.service.preview_qq_historical_chat(payload)
            return self._ok({"result": result})
        except ValueError as exc:
            return self._err(str(exc), 400)
        except (RuntimeError, asyncio.TimeoutError) as exc:
            return self._err(str(exc), 502)
        except Exception as exc:
            logger.exception("QQ 历史读取预览失败")
            return self._err(f"QQ 历史读取预览失败: {exc}", 500)

    async def conversation_import_start(self):
        payload = await self._json()
        try:
            result = await self.plugin.service.start_historical_chat_import(payload)
            return self._ok({"result": result})
        except (ValueError, OSError) as exc:
            return self._err(str(exc), 400)
        except Exception as exc:
            logger.exception("历史对话导入启动失败")
            return self._err(f"历史对话导入启动失败: {exc}", 500)

    async def conversation_import_status(self):
        batch_id = clean_text(request.args.get("batch_id", ""), 120)
        upgrade_legacy = self._bool(request.args.get("upgrade_legacy"), True)
        try:
            result = await self.plugin.service.historical_chat_import_status(
                batch_id,
                upgrade_legacy=upgrade_legacy,
            )
            return self._ok({"result": result})
        except ValueError as exc:
            return self._err(str(exc), 404)
        except Exception as exc:
            return self._err(f"读取历史对话导入状态失败: {exc}", 500)

    async def conversation_import_targets(self):
        try:
            buckets = await self.plugin.service.store.list_memory_buckets(
                limit=None,
                include_raw_events=self.plugin.service.config.bool(
                    "memory_injection.include_raw_events",
                    False,
                ),
            )
            private_buckets = []
            for bucket in buckets:
                if clean_text(bucket.get("scope"), 40) != "private":
                    continue
                item = dict(bucket)
                item.pop("pending_count", None)
                private_buckets.append(item)
            return self._ok({"buckets": private_buckets})
        except Exception as exc:
            return self._err(f"读取历史导入目标私聊失败: {exc}", 500)

    async def conversation_import_pause(self):
        payload = await self._json()
        batch_id = clean_text(payload.get("batch_id"), 120)
        if not batch_id:
            return self._err("batch_id is required", 400)
        try:
            return self._ok({"result": await self.plugin.service.pause_historical_chat_import(batch_id)})
        except ValueError as exc:
            return self._err(str(exc), 404)

    async def conversation_import_resume(self):
        payload = await self._json()
        batch_id = clean_text(payload.get("batch_id"), 120)
        if not batch_id:
            return self._err("batch_id is required", 400)
        try:
            return self._ok({"result": await self.plugin.service.resume_historical_chat_import(batch_id)})
        except ValueError as exc:
            return self._err(str(exc), 404)

    async def conversation_import_rebind(self):
        payload = await self._json()
        try:
            result = await self.plugin.service.rebind_historical_chat_import(payload)
            return self._ok({"result": result})
        except ValueError as exc:
            message = str(exc)
            return self._err(message, 404 if message == "导入批次不存在" else 400)
        except Exception as exc:
            logger.exception("历史对话导入归属修正失败")
            return self._err(f"历史对话导入归属修正失败: {exc}", 500)

    async def conversation_import_rollback(self):
        payload = await self._json()
        batch_id = clean_text(payload.get("batch_id"), 120)
        if not batch_id:
            return self._err("batch_id is required", 400)
        try:
            return self._ok({"result": await self.plugin.service.rollback_historical_chat_import(batch_id)})
        except ValueError as exc:
            return self._err(str(exc), 404)
        except Exception as exc:
            logger.exception("历史对话导入回滚失败")
            return self._err(f"历史对话导入回滚失败: {exc}", 500)

    async def persona_state(self):
        """Return read-only expression coordination and memory-touch diagnostics."""
        try:
            service = self.plugin.service
            touch_trends: list[dict[str, Any]] = []
            phase_state = getattr(service, "_relationship_phase_state", None)
            if isinstance(phase_state, dict):
                for key, state in phase_state.items():
                    if not isinstance(state, dict):
                        continue
                    identity = state.get("_identity") if isinstance(state.get("_identity"), dict) else {}
                    identity_parts = [
                        clean_text(identity.get("platform"), 80),
                        clean_text(identity.get("bot_id"), 120),
                        clean_text(identity.get("scope"), 40),
                        clean_text(identity.get("target_id"), 200),
                    ]
                    member_id = clean_text(identity.get("member_id"), 120)
                    if member_id:
                        identity_parts.append(f"member={member_id}")
                    raw_momentum = state.get("momentum", 0.0)
                    momentum = float(raw_momentum) if type(raw_momentum) in {int, float} else 0.0
                    trend_band = "rising" if momentum >= 0.08 else "cooling" if momentum <= -0.08 else "steady"
                    touch_trends.append({
                        "session_key": key,
                        "session_label": " / ".join(part for part in identity_parts if part) or key,
                        "trend_band": trend_band,
                        "touch_count": state.get("touch_count", 0),
                        "legacy_context": clean_text(state.get("phase"), 40),
                        "updated_at": state.get("updated_at", ""),
                    })
            touch_trends.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
            memory_touch_events: list[dict[str, Any]] = []
            event_queue = getattr(service, "_emotional_event_queue", None)
            if isinstance(event_queue, dict):
                for session_id, queue in event_queue.items():
                    if not isinstance(queue, list):
                        continue
                    for event in queue[-3:]:
                        if not isinstance(event, dict):
                            continue
                        memory_touch_events.append({
                            "session_id": session_id,
                            "event_type": event.get("event_type"),
                            "energy_delta": event.get("energy_delta"),
                            "mood_hint": event.get("mood_hint"),
                            "content_preview": str(event.get("content_preview", ""))[:80],
                            "ts": event.get("ts"),
                        })
            time_of_day = ""
            if hasattr(service, "_compute_time_of_day"):
                time_of_day = service._compute_time_of_day()
            cross_window_state: dict[str, Any] = {"total": 0, "scar_count": 0, "warm_count": 0, "vulnerable_count": 0}
            if hasattr(service, "_get_cross_window_emotional_state"):
                cross_window_state = service._get_cross_window_emotional_state()
            return self._ok({
                "expression_coordination": {
                    "contract": "companion_interaction_expression.v1",
                    "mode": "request_scoped_read_only",
                    "expression_authority": "private_companion",
                    "memory_role": "recall_visibility_and_mention_cap",
                    "persistent": False,
                },
                "memory_touch_trends": touch_trends[:20],
                "memory_touch_events": memory_touch_events[:15],
                "time_of_day": time_of_day,
                "cross_window_emotional_state": cross_window_state,
                "time_of_day_labels": {
                    "late_night": "深夜",
                    "dawn": "凌晨",
                    "early_morning": "清晨",
                    "afternoon": "下午",
                    "evening": "傍晚",
                    "night": "夜间",
                },
                "legacy_context_labels": {
                    "acquaintance": "初识",
                    "familiar": "熟悉",
                    "close": "亲近",
                    "intimate": "亲密",
                    "deeply_bonded": "深伴",
                },
            })
        except Exception as exc:
            return self._err(f"互动协同数据读取失败: {exc}", 500)

    async def acl_matrix(self):
        """Return all windows, ACL rules and policies in one shot for topology visualization."""
        try:
            store = self.plugin.service.store
            scope_control = {
                "private_capture_enabled": self.plugin.service.config.bool("scope_control.private_capture_enabled", True),
                "group_capture_enabled": self.plugin.service.config.bool("scope_control.group_capture_enabled", True),
                "private_recall_enabled": self.plugin.service.config.bool("scope_control.private_recall_enabled", True),
                "group_recall_enabled": self.plugin.service.config.bool("scope_control.group_recall_enabled", True),
                "private_topology_enabled": self.plugin.service.config.bool("scope_control.private_topology_enabled", True),
                "group_topology_enabled": self.plugin.service.config.bool("scope_control.group_topology_enabled", True),
            }
            topology_scopes = {
                scope for scope in ("private", "group")
                if scope_control[f"{scope}_topology_enabled"]
            }
            buckets = await store.list_memory_buckets(
                limit=200,
                include_raw_events=self.plugin.service.config.bool(
                    "memory_injection.include_raw_events",
                    False,
                ),
            )
            windows: list[dict[str, Any]] = []
            for b in buckets:
                scope = clean_text(b.get("scope"), 40)
                tid = clean_text(b.get("target_id"), 160)
                if scope in topology_scopes and tid:
                    windows.append({
                        "scope": scope,
                        "id": tid,
                        "label": clean_text(b.get("label"), 120),
                        "target_name": clean_text(b.get("target_name"), 120),
                        "target_kind": clean_text(b.get("target_kind"), 40),
                        "sample_session_id": clean_text(b.get("sample_session_id"), 200),
                        "sample_group_id": clean_text(b.get("sample_group_id"), 120),
                        "memory_count": b.get("memory_count", 0),
                    })
            rules = await store.list_acl_rules(enabled_only=False)
            policies = await store.list_acl_policies()
            return self._ok({
                "scope_control": scope_control,
                "windows": windows,
                "rules": [
                    {
                        "id": clean_text(r.get("id"), 120),
                        "owner_scope": clean_text(r.get("owner_scope"), 40),
                        "owner_id": clean_text(r.get("owner_id"), 160),
                        "reader_scope": clean_text(r.get("reader_scope"), 40),
                        "reader_id": clean_text(r.get("reader_id"), 160),
                        "effect": r.get("effect") or "allow",
                        "enabled": bool(r.get("enabled", True)),
                    }
                    for r in rules
                    if clean_text(r.get("owner_scope"), 40) in topology_scopes
                    and clean_text(r.get("reader_scope"), 40) in topology_scopes
                ],
                "policies": [
                    {
                        "window_scope": clean_text(p.get("window_scope"), 40),
                        "window_id": clean_text(p.get("window_id"), 160),
                        "read_mode": p.get("read_mode") or ("blacklist" if clean_text(p.get("window_scope"), 40) == "group" else "whitelist"),
                        "share_mode": p.get("share_mode") or ("blacklist" if clean_text(p.get("window_scope"), 40) == "group" else "whitelist"),
                        "capture_enabled": p.get("capture_enabled"),
                        "recall_enabled": p.get("recall_enabled"),
                    }
                    for p in policies
                    if clean_text(p.get("window_scope"), 40) in topology_scopes
                ],
            })
        except Exception as exc:
            return self._err(f"权限矩阵读取失败: {exc}", 500)

    async def buckets(self):
        buckets = await self.plugin.service.store.list_memory_buckets(
            limit=self._query_int("limit", 160),
            include_raw_events=self.plugin.service.config.bool(
                "memory_injection.include_raw_events",
                False,
            ),
        )
        for bucket in buckets:
            bucket.pop("pending_count", None)
        return self._ok({"buckets": buckets})

    async def memories(self):
        limit = self._query_int("limit", 50)
        query = clean_text(request.args.get("q", ""), 200)
        scope = clean_text(request.args.get("scope", ""), 40)
        visibility = clean_text(request.args.get("visibility", ""), 40)
        lifecycle = clean_text(request.args.get("lifecycle", ""), 40)
        lifecycle_values = MEMORY_LIFECYCLE_FILTERS.get(lifecycle)
        visibility_values = MEMORY_VISIBILITY_FILTERS.get(visibility)
        requested_type = clean_text(request.args.get("memory_type", ""), 80)
        memory_types = MEMORY_TYPE_FILTERS.get(requested_type)
        if scope == "profile" and not memory_types:
            memory_types = MEMORY_TYPE_FILTERS["profile"] + MEMORY_TYPE_FILTERS["preference"] + MEMORY_TYPE_FILTERS["relationship"]
        records = await self.plugin.service.store.list_memories(
            limit=max(limit * 2, 50),
            include_pending=False,
            query=query,
            memory_type="" if memory_types else requested_type,
            memory_types=memory_types,
            scope="" if scope in {"profile", "external"} else scope,
            visibility="" if visibility_values else visibility,
            visibility_values=visibility_values,
            source_plugin_exclude="bot_personal_bridge",
            review_status="",
            lifecycle="" if lifecycle_values else lifecycle,
            lifecycle_values=lifecycle_values,
            session_id=clean_text(request.args.get("session_id", ""), 200),
            group_id=clean_text(request.args.get("group_id", ""), 120),
            entity_id=clean_text(request.args.get("entity_id", ""), 120),
        )
        if scope == "external":
            records = [record for record in records if clean_text(getattr(record, "source_plugin", ""), 120) != PLUGIN_NAME]
        records = [
            record
            for record in records
            if clean_text(getattr(record, "source_plugin", ""), 120) != "bot_personal_bridge"
        ][:limit]
        return self._ok({"memories": [serialize_memory(record) for record in records]})

    async def memory_detail(self):
        memory_id = clean_text(request.args.get("id", ""), 120)
        if not memory_id:
            return self._err("missing id", 400)
        record = await self.plugin.service.store.get_memory(memory_id)
        if not record:
            return self._err("memory not found", 404)
        payload = serialize_memory(record)
        payload["evidence"] = record.evidence
        payload["metadata"] = record.metadata
        payload["merged_count"] = record.merged_count
        payload["content_fingerprint"] = record.content_fingerprint
        return self._ok({"memory": payload})

    async def memory_update(self):
        payload = await self._json()
        memory_id = clean_text(payload.get("id"), 120)
        if not memory_id:
            return self._err("missing id", 400)
        current = await self.plugin.service.store.get_memory(memory_id)
        if current is None:
            return self._err("memory not found", 404)
        validity_status = self._optional_choice(payload, "validity_status", VALIDITY_STATUSES)
        durability = self._optional_choice(payload, "durability", DURABILITY_LEVELS)
        sensitivity = self._optional_choice(payload, "sensitivity", SENSITIVITY_LEVELS)
        try:
            valid_from = self._optional_iso_timestamp(payload, "valid_from")
            valid_to = self._optional_iso_timestamp(payload, "valid_to")
            salience = self._optional_unit_score(payload, "salience")
        except ValueError as exc:
            return self._err(clean_text(exc, 240), 400)
        if validity_status is False:
            return self._err("invalid validity_status", 400)
        if durability is False:
            return self._err("invalid durability", 400)
        if sensitivity is False:
            return self._err("invalid sensitivity", 400)
        effective_valid_from = valid_from if valid_from is not None else current.valid_from
        effective_valid_to = valid_to if valid_to is not None else current.valid_to
        if (
            effective_valid_from
            and effective_valid_to
            and self._iso_timestamp_number(effective_valid_from)
            > self._iso_timestamp_number(effective_valid_to)
        ):
            return self._err("valid_from must not be later than valid_to", 400)
        ok = await self.plugin.service.store.update_memory_payload(
            memory_id,
            memory_type=payload.get("memory_type"),
            content=payload.get("content"),
            evidence=payload.get("evidence"),
            importance=payload.get("importance"),
            confidence=payload.get("confidence"),
            visibility=payload.get("visibility"),
            lifecycle=payload.get("lifecycle"),
            validity_status=validity_status,
            valid_from=valid_from,
            valid_to=valid_to,
            salience=salience,
            durability=durability,
            sensitivity=sensitivity,
        )
        if not ok:
            return self._err("memory not found", 404)
        return self._ok({"updated": ok})

    async def memory_rebind_owner(self):
        payload = await self._json()
        try:
            result = await self.plugin.service.rebind_memory_owners(payload)
            return self._ok({"result": result})
        except ValueError as exc:
            return self._err(str(exc), 400)
        except Exception as exc:
            logger.exception("记忆 Bot 归属修正失败")
            return self._err(f"记忆 Bot 归属修正失败: {exc}", 500)

    async def memory_delete(self):
        payload = await self._json()
        ok = await self.plugin.service.store.delete_memory(clean_text(payload.get("id"), 120))
        return self._ok({"deleted": ok})

    async def memory_visibility(self):
        payload = await self._json()
        ok = await self.plugin.service.store.update_memory_visibility(
            clean_text(payload.get("id"), 120),
            clean_text(payload.get("visibility"), 40),
        )
        return self._ok({"updated": ok})

    async def memory_lifecycle(self):
        payload = await self._json()
        ok = await self.plugin.service.store.update_memory_lifecycle(
            clean_text(payload.get("id"), 120),
            clean_text(payload.get("lifecycle"), 40),
        )
        return self._ok({"updated": ok})

    @staticmethod
    def _core_memory_payload(record: Any) -> dict[str, Any]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        owner_bot_id = clean_text(metadata.get("owner_bot_id") or record.owner_bot_id, 120)
        try:
            priority = max(0, min(100, int(metadata.get("core_priority", 50))))
        except (TypeError, ValueError):
            priority = 50
        try:
            revision = max(0, int(metadata.get("core_revision") or 0))
        except (TypeError, ValueError):
            revision = 0
        return {
            "id": clean_text(record.id, 120),
            "label": clean_text(metadata.get("core_label"), 80),
            "content": record.content,
            "kind": clean_text(metadata.get("core_kind"), 32) or "fact",
            "scope": clean_text(metadata.get("core_scope"), 24) or "global",
            "target_id": clean_text(metadata.get("target_id"), 160),
            "target_name": clean_text(getattr(record.subject, "name", ""), 80),
            "bot_id": "" if owner_bot_id == "self" else owner_bot_id,
            "persona_id": clean_text(metadata.get("persona_id"), 120),
            "platform": clean_text(record.platform, 80),
            "session_id": clean_text(record.session_id, 220),
            "priority": priority,
            "enabled": metadata.get("core_enabled", True) is True,
            "revision": revision,
            "updated_at": clean_text(record.updated_at, 80),
        }

    async def core_memory_list(self):
        records = await self.plugin.service.list_core_memory_blocks()
        scope = clean_text(request.args.get("scope", ""), 24).lower()
        target_id = clean_text(request.args.get("target_id", ""), 160)
        blocks = [self._core_memory_payload(record) for record in records]
        if scope:
            blocks = [block for block in blocks if block["scope"] == scope]
        if target_id:
            blocks = [block for block in blocks if block["target_id"] == target_id]
        return self._ok({"blocks": blocks})

    async def core_memory_upsert(self):
        payload = await self._json()
        result = await self.plugin.service.save_core_memory_block(payload)
        if result.get("ok"):
            return self._ok(result)
        code = clean_text(result.get("code"), 80) or "core_memory_save_failed"
        status = 409 if code in {"revision_conflict", "memory_type_conflict", "label_conflict"} else 400
        return self._err(code, status)

    async def core_memory_delete(self):
        payload = await self._json()
        memory_id = clean_text(payload.get("id"), 120)
        if not memory_id:
            return self._err("missing id", 400)
        result = await self.plugin.service.delete_core_memory_block(memory_id)
        if result.get("ok"):
            return self._ok({"deleted": True})
        code = clean_text(result.get("code"), 80) or "core_memory_delete_failed"
        status = 404 if code == "not_found" else 409
        return self._err(code, status)

    async def acl(self):
        owner_scope = clean_text(request.args.get("scope", ""), 40)
        owner_id = clean_text(request.args.get("id", ""), 160)
        error = self._acl_window_error(owner_scope, owner_id)
        if error:
            return self._err(error, 400)
        can_read = await self.plugin.service.store.list_acl_rules(
            reader_scope=owner_scope,
            reader_id=owner_id,
            enabled_only=True,
        )
        can_be_read_by = await self.plugin.service.store.list_acl_rules(
            owner_scope=owner_scope,
            owner_id=owner_id,
            enabled_only=True,
        )
        policy = await self.plugin.service.store.get_acl_policy(owner_scope, owner_id)
        return self._ok(
            {
                "owner": {"scope": owner_scope, "id": owner_id},
                "policy": policy,
                "can_read": can_read,
                "can_be_read_by": can_be_read_by,
            }
        )

    async def acl_upsert(self):
        payload = await self._json()
        owner_scope = clean_text(payload.get("owner_scope"), 40)
        owner_id = clean_text(payload.get("owner_id"), 160)
        reader_scope = clean_text(payload.get("reader_scope"), 40)
        reader_id = clean_text(payload.get("reader_id"), 160)
        error = self._acl_window_error(owner_scope, owner_id) or self._acl_window_error(reader_scope, reader_id)
        if error:
            return self._err(error, 400)
        if owner_scope == reader_scope and owner_id == reader_id:
            return self._err("same window does not need ACL", 400)
        rule = await self.plugin.service.store.upsert_acl_rule(
            owner_scope=owner_scope,
            owner_id=owner_id,
            reader_scope=reader_scope,
            reader_id=reader_id,
            effect=self._acl_effect(payload.get("effect")),
            enabled=self._bool(payload.get("enabled"), True),
            note=clean_text(payload.get("note"), 300),
        )
        return self._ok({"rule": rule})

    async def acl_policy(self):
        payload = await self._json()
        window_scope = clean_text(payload.get("scope") or payload.get("window_scope"), 40)
        window_id = clean_text(payload.get("id") or payload.get("window_id"), 160)
        error = self._acl_window_error(window_scope, window_id)
        if error:
            return self._err(error, 400)
        policy_values: dict[str, Any] = {
            "window_scope": window_scope,
            "window_id": window_id,
            "read_mode": self._acl_mode(payload.get("read_mode")),
            "share_mode": self._acl_mode(payload.get("share_mode")),
        }
        for key in ("capture_enabled", "recall_enabled"):
            if key in payload:
                value = payload.get(key)
                if value is not None and not isinstance(value, (bool, int, str)):
                    return self._err(f"{key} must be a boolean or null", 400)
                policy_values[key] = value
        policy = await self.plugin.service.store.upsert_acl_policy(**policy_values)
        return self._ok({"policy": policy})

    async def acl_delete(self):
        payload = await self._json()
        ok = await self.plugin.service.store.delete_acl_rule(clean_text(payload.get("id"), 120))
        return self._ok({"deleted": ok})

    async def search(self):
        payload = await self._json()
        query = clean_text(payload.get("query"), 500)
        if not query:
            return self._err("missing query", 400)
        raw_context = {
            "session_id": clean_text(payload.get("session_id"), 200),
            "scope": clean_text(payload.get("scope"), 40).lower() or "unknown",
            "platform": clean_text(payload.get("platform"), 80),
            "user_id": clean_text(payload.get("user_id"), 120),
            "group_id": clean_text(payload.get("group_id"), 120),
        }
        requested_bot_id = clean_text(payload.get("bot_id"), 120)
        context_mode = clean_text(
            payload.get("context_mode") or payload.get("search_mode"),
            20,
        ).lower() or "auto"
        context_mode = {"context": "session", "window": "session"}.get(context_mode, context_mode)
        if context_mode not in {"auto", "all", "session"}:
            return self._err("invalid context_mode", 400)
        parsed_scope, parsed_target = parse_scope_from_session(raw_context["session_id"])
        has_context_intent = (
            raw_context["scope"] in {"private", "group"}
            or any(raw_context[key] for key in ("session_id", "user_id", "group_id"))
            or bool(requested_bot_id)
        )
        if context_mode != "all":
            if raw_context["scope"] not in {"unknown", "private", "group"}:
                return self._err("invalid search scope", 400)
            if (
                parsed_scope in {"private", "group"}
                and raw_context["scope"] in {"private", "group"}
                and raw_context["scope"] != parsed_scope
            ):
                return self._err("search scope conflicts with session_id", 400)
            if (
                parsed_scope == "private"
                and parsed_target
                and raw_context["user_id"]
                and raw_context["user_id"] != parsed_target
            ):
                return self._err("private search target conflicts with session_id", 400)
            if (
                parsed_scope == "group"
                and parsed_target
                and raw_context["group_id"]
                and raw_context["group_id"] != parsed_target
            ):
                return self._err("group search target conflicts with session_id", 400)
            if raw_context["user_id"] and raw_context["group_id"]:
                return self._err("search context cannot contain both user_id and group_id", 400)
            if raw_context["scope"] == "private" and raw_context["group_id"]:
                return self._err("private search context cannot contain group_id", 400)
            if raw_context["scope"] == "group" and raw_context["user_id"]:
                return self._err("group search context cannot contain user_id", 400)
        normalized = normalize_session_context_fields(**raw_context)
        if context_mode != "all":
            if normalized["scope"] == "private" and normalized["group_id"]:
                return self._err("private search context cannot contain group_id", 400)
            if normalized["scope"] == "group" and normalized["user_id"]:
                return self._err("group search context cannot contain user_id", 400)
        has_session_context = bool(normalized["session_id"]) or (
            normalized["scope"] == "private" and bool(normalized["user_id"])
        ) or (
            normalized["scope"] == "group" and bool(normalized["group_id"])
        )
        if context_mode == "session" and not has_session_context:
            return self._err("missing valid private or group search context", 400)
        if context_mode == "auto" and has_context_intent and not has_session_context:
            return self._err("incomplete private or group search context", 400)
        admin_read_all = context_mode == "all" or (
            context_mode == "auto" and not has_context_intent
        )
        if admin_read_all:
            normalized = {
                "session_id": "",
                "scope": "unknown",
                "platform": "",
                "user_id": "",
                "group_id": "",
            }
            requested_bot_id = ""
        ctx = SessionContext(
            session_id=normalized["session_id"],
            scope=normalized["scope"],
            platform=normalized["platform"],
            user_id=normalized["user_id"],
            user_name=clean_text(payload.get("user_name"), 80),
            group_id=normalized["group_id"],
            group_name=clean_text(payload.get("group_name"), 80),
            bot_id=requested_bot_id,
            message_text=query,
        )
        top_k = max(1, min(50, self._int(payload.get("top_k"), 8)))
        slot_map: dict[str, list[Any]] = {}
        search_context_slots = getattr(self.plugin.service, "search_context_slots", None)
        if callable(search_context_slots):
            results, blocked, slot_map = await search_context_slots(
                query,
                ctx,
                top_k,
                admin_read_all=admin_read_all,
            )
        else:
            results, blocked = await self.plugin.service.search_with_diagnostics(
                query,
                ctx,
                top_k,
                admin_read_all=admin_read_all,
            )
            slot_map = {"stable_memory": results} if results else {}
        slot_limits: dict[str, int] = {}
        slot_limit_builder = getattr(self.plugin.service, "_slot_limits", None)
        if callable(slot_limit_builder):
            slot_limits = slot_limit_builder(top_k, query=query)
        capped_slots: set[str] = set()
        cap_builder = getattr(self.plugin.service, "_slot_capped_slots", None)
        if callable(cap_builder):
            capped_slots = set(cap_builder(query, bot_id=requested_bot_id) or set())
        orchestration_enabled = callable(search_context_slots)
        config = getattr(self.plugin.service, "config", None)
        config_bool = getattr(config, "bool", None)
        if callable(config_bool):
            orchestration_enabled = orchestration_enabled and bool(
                config_bool("context_orchestration.enabled", True)
            )
        return self._ok(
            {
                "results": [
                    serialize_memory(item.memory, item.score, item.reason)
                    for item in results
                ],
                "blocked": blocked[:30],
                "retrieval": {
                    "top_k": top_k,
                    "orchestration_enabled": orchestration_enabled,
                    "slot_counts": {
                        clean_text(slot, 60): len(items)
                        for slot, items in slot_map.items()
                        if isinstance(items, list) and items
                    },
                    "slot_limits": slot_limits if orchestration_enabled else {},
                    "capped_slots": sorted(capped_slots) if orchestration_enabled else [],
                },
                "search_context": {
                    "mode": "all" if admin_read_all else "session",
                    "scope": normalized["scope"],
                    "session_id": normalized["session_id"],
                    "user_id": normalized["user_id"],
                    "group_id": normalized["group_id"],
                    "bot_id": requested_bot_id,
                },
            }
        )

    async def timeline(self):
        try:
            rows = await self.plugin.service.store.recent_timeline(
                limit=self._query_int("limit", 30),
                scope=clean_text(request.args.get("scope", ""), 40),
                session_id=clean_text(request.args.get("session_id", ""), 200),
                entity_id=clean_text(request.args.get("entity_id", ""), 120),
            )
            return self._ok({"items": rows})
        except Exception as exc:
            logger.warning("[MemoryCompanion] timeline 端点异常: %s", exc, exc_info=True)
            return self._err("timeline_unavailable", 500)

    async def relations(self):
        try:
            rows = await self.plugin.service.store.list_relationships(
                limit=self._query_int("limit", 50),
                entity_id=clean_text(request.args.get("entity_id", ""), 120),
                scope=clean_text(request.args.get("scope", ""), 40),
                session_id=clean_text(request.args.get("session_id", ""), 200),
                group_id=clean_text(request.args.get("group_id", ""), 120),
            )
            return self._ok({"items": rows})
        except Exception as exc:
            logger.warning("[MemoryCompanion] relations 端点异常: %s", exc, exc_info=True)
            return self._err("relations_unavailable", 500)

    async def graph(self):
        try:
            rows = await self.plugin.service.store.list_knowledge_edges(
                limit=self._query_int("limit", 50),
                scope=clean_text(request.args.get("scope", ""), 40),
                session_id=clean_text(request.args.get("session_id", ""), 200),
                group_id=clean_text(request.args.get("group_id", ""), 120),
                node=clean_text(request.args.get("node") or request.args.get("q"), 160),
            )
            return self._ok({"items": rows})
        except Exception as exc:
            logger.warning("[MemoryCompanion] graph 端点异常: %s", exc, exc_info=True)
            return self._err("graph_unavailable", 500)

    async def threads(self):
        try:
            rows = await self.plugin.service.store.list_cross_window_threads(
                status=clean_text(request.args.get("status", "open"), 40) or "open",
                limit=self._query_int("limit", 30),
                session_id=clean_text(request.args.get("session_id", ""), 200),
            )
            return self._ok({"items": rows})
        except Exception as exc:
            logger.warning("[MemoryCompanion] threads 端点异常: %s", exc, exc_info=True)
            return self._err("threads_unavailable", 500)

    async def thread_status(self):
        payload = await self._json()
        thread_id = clean_text(payload.get("id"), 120)
        status = clean_text(payload.get("status"), 40).lower()
        if not thread_id:
            return self._err("missing thread id", 400)
        if status not in {"open", "closed"}:
            return self._err("thread status must be open or closed", 400)
        ok = await self.plugin.service.store.update_cross_window_thread_status(
            thread_id,
            status,
        )
        return self._ok({"updated": ok})

    async def logs(self):
        try:
            rows = await self.plugin.service.store.recent_injection_logs(
                limit=self._query_int("limit", 20),
                scope=clean_text(request.args.get("scope", ""), 40),
                session_id=clean_text(request.args.get("session_id", ""), 200),
            )
            all_ids: list[str] = []
            for row in rows:
                all_ids.extend(clean_text(mid, 120) for mid in (row.get("selected_memory_ids") or [])[:12])
            records_map = await self.plugin.service.store.get_memories_by_ids(all_ids) if all_ids else {}
            for row in rows:
                selected = []
                for memory_id in (row.get("selected_memory_ids") or [])[:12]:
                    record = records_map.get(clean_text(memory_id, 120))
                    if record:
                        selected.append(serialize_memory(record))
                row["selected_memories"] = selected
            return self._ok({"items": rows})
        except Exception as exc:
            logger.warning("[MemoryCompanion] logs 端点异常: %s", exc, exc_info=True)
            return self._err("logs_unavailable", 500)

    async def context_config(self):
        config = self.plugin.service.config
        theme_name = str(config.get("appearance.theme", DEFAULT_THEME_NAME))
        return self._ok(
            {
                "appearance": {
                    "theme": theme_name,
                    "theme_key": self._theme_key(theme_name),
                    "available_themes": list(THEME_NAME_TO_KEY.keys()),
                },
                "conversation_memory": {
                    "enabled": config.bool("conversation_memory.enabled", True),
                    "capture_group_messages": config.bool("conversation_memory.capture_group_messages", True),
                    "idle_gap_minutes": config.int("conversation_memory.idle_gap_minutes", 20),
                    "recent_events_for_followup": config.int("conversation_memory.recent_events_for_followup", 12),
                    "time_window_timeline_limit": config.int("conversation_memory.time_window_timeline_limit", 12),
                    "recent_fact_guard_enabled": config.bool(
                        "conversation_memory.recent_fact_guard_enabled", True
                    ),
                    "recent_fact_guard_hours": config.int("conversation_memory.recent_fact_guard_hours", 3),
                    "recent_fact_guard_event_limit": config.int(
                        "conversation_memory.recent_fact_guard_event_limit", 24
                    ),
                    "recent_fact_guard_max_items": config.int(
                        "conversation_memory.recent_fact_guard_max_items", 4
                    ),
                    "low_information_guard_enabled": config.bool("conversation_memory.low_information_guard_enabled", True),
                    "low_information_gap_minutes": config.int("conversation_memory.low_information_gap_minutes", 20),
                    "suppress_memory_on_low_information": config.bool(
                        "conversation_memory.suppress_memory_on_low_information", True
                    ),
                    "topic_shift_guard_enabled": config.bool("conversation_memory.topic_shift_guard_enabled", True),
                    "suppress_memory_on_topic_shift": config.bool(
                        "conversation_memory.suppress_memory_on_topic_shift", True
                    ),
                    "topic_shift_guard_recent_events": config.int(
                        "conversation_memory.topic_shift_guard_recent_events", 6
                    ),
                    "group_actor_relevance_guard_enabled": config.bool(
                        "conversation_memory.group_actor_relevance_guard_enabled", True
                    ),
                },
                "scope_control": {
                    "private_capture_enabled": config.bool("scope_control.private_capture_enabled", True),
                    "group_capture_enabled": config.bool("scope_control.group_capture_enabled", True),
                    "private_recall_enabled": config.bool("scope_control.private_recall_enabled", True),
                    "group_recall_enabled": config.bool("scope_control.group_recall_enabled", True),
                    "private_topology_enabled": config.bool("scope_control.private_topology_enabled", True),
                    "group_topology_enabled": config.bool("scope_control.group_topology_enabled", True),
                },
                "provider_options": self._provider_options(),
                "rerank_provider_options": await self._rerank_provider_options(),
                "embedding_provider_options": await self._embedding_provider_options(),
                "retrieval": {
                    "mode": str(config.get("retrieval.mode", "auto") or "auto"),
                    "rerank_provider_id": str(config.get("retrieval.rerank_provider_id", "") or ""),
                    "rerank_candidate_multiplier": config.int("retrieval.rerank_candidate_multiplier", 5),
                    "rerank_candidate_limit": config.int("retrieval.rerank_candidate_limit", 32),
                    "rerank_timeout_ms": config.int("retrieval.rerank_timeout_ms", 1200),
                    "embedding_enabled": config.bool("retrieval.embedding_enabled", False),
                    "embedding_provider_id": str(config.get("retrieval.embedding_provider_id", "") or ""),
                    "embedding_candidate_limit": config.int("retrieval.embedding_candidate_limit", 1200),
                    "embedding_top_k": config.int("retrieval.embedding_top_k", 32),
                    "embedding_score_threshold": config.float("retrieval.embedding_score_threshold", 0.34),
                    "embedding_weight": config.float("retrieval.embedding_weight", 0.55),
                    "embedding_timeout_ms": config.int("retrieval.embedding_timeout_ms", 5000),
                    "embedding_max_text_chars": config.int("retrieval.embedding_max_text_chars", 1200),
                    "embedding_backfill_enabled": config.bool("retrieval.embedding_backfill_enabled", True),
                    "embedding_backfill_batch_size": config.int("retrieval.embedding_backfill_batch_size", 50),
                    "embedding_backfill_interval_seconds": config.int(
                        "retrieval.embedding_backfill_interval_seconds", 300
                    ),
                    "embedding_background_concurrency": config.int(
                        "retrieval.embedding_background_concurrency", 2
                    ),
                    "current_window_candidate_limit": config.int(
                        "retrieval.current_window_candidate_limit", 600
                    ),
                    "keyword_fallback_min_fts_candidates": config.int(
                        "retrieval.keyword_fallback_min_fts_candidates", 80
                    ),
                },
                "knowledge_graph": {
                    "enabled": config.bool("knowledge_graph.enabled", True),
                    "retrieval_expansion_enabled": config.bool(
                        "knowledge_graph.retrieval_expansion_enabled",
                        True,
                    ),
                    "expansion_limit": config.int("knowledge_graph.expansion_limit", 12),
                    "backfill_limit": config.int("knowledge_graph.backfill_limit", 300),
                },
                "memory_injection": {
                    "enabled": config.bool("memory_injection.enabled", True),
                    "features_removed": False,
                    "top_k": config.int("memory_injection.top_k", 6),
                    "max_chars": config.int("memory_injection.max_chars", 1800),
                    "temporal_aggregate_max_chars": config.int(
                        "memory_injection.temporal_aggregate_max_chars",
                        3600,
                    ),
                    "include_raw_events": config.bool("memory_injection.include_raw_events", False),
                    "enable_injection_logs": config.bool("memory_injection.enable_injection_logs", True),
                    "debug_log_injection_enabled": config.bool(
                        "memory_injection.debug_log_injection_enabled",
                        False,
                    ),
                    "debug_log_max_chars": config.int("memory_injection.debug_log_max_chars", 12000),
                },
                "context_orchestration": {
                    "enabled": config.bool("context_orchestration.enabled", True),
                    "features_removed": False,
                    "query_mode": str(config.get("context_orchestration.query_mode", "current_message") or "current_message"),
                    "include_intent_context": config.bool("context_orchestration.include_intent_context", True),
                    "intent_max_chars": config.int("context_orchestration.intent_max_chars", 520),
                    "self_timeline_limit": config.int("context_orchestration.self_timeline_limit", 2),
                    "user_profile_limit": config.int("context_orchestration.user_profile_limit", 2),
                    "current_window_limit": config.int("context_orchestration.current_window_limit", 3),
                    "conversation_summary_limit": config.int("context_orchestration.conversation_summary_limit", 2),
                    "stable_memory_limit": config.int("context_orchestration.stable_memory_limit", 3),
                },
                "memory_summary": {
                    "enabled": config.bool("memory_summary.enabled", True),
                    "provider_id": str(config.get("memory_summary.provider_id", "") or ""),
                    "fallback_provider_id": str(config.get("memory_summary.fallback_provider_id", "") or ""),
                    "private_provider_id": str(config.get("memory_summary.private_provider_id", "") or ""),
                    "private_fallback_provider_id": str(
                        config.get("memory_summary.private_fallback_provider_id", "") or ""
                    ),
                    "group_provider_id": str(config.get("memory_summary.group_provider_id", "") or ""),
                    "group_fallback_provider_id": str(
                        config.get("memory_summary.group_fallback_provider_id", "") or ""
                    ),
                    "min_events": config.int("memory_summary.min_events", 8),
                    "trigger_event_count": config.int("memory_summary.trigger_event_count", 12),
                    "trigger_interval_minutes": config.int("memory_summary.trigger_interval_minutes", 60),
                    "max_events_per_summary": config.int("memory_summary.max_events_per_summary", 40),
                    "max_retries": config.int("memory_summary.max_retries", 3),
                    "retry_backoff_seconds": config.int("memory_summary.retry_backoff_seconds", 60),
                    "transient_retry_cooldown_minutes": config.int(
                        "memory_summary.transient_retry_cooldown_minutes", 10
                    ),
                },
                "memory_tools": {
                    "enable_recall_tool": config.bool("memory_tools.enable_recall_tool", True),
                    "enable_remember_tool": config.bool("memory_tools.enable_remember_tool", True),
                    "enable_note_tools": config.bool("memory_tools.enable_note_tools", True),
                },
                "private_companion_bridge": {
                    "enabled": config.bool("private_companion_bridge.enabled", True),
                    "accept_external_records": config.bool("private_companion_bridge.accept_external_records", True),
                    "cross_window_emotional_continuity_enabled": config.bool(
                        "private_companion_bridge.cross_window_emotional_continuity_enabled",
                        False,
                    ),
                    "dedupe_prompt_context": config.bool("private_companion_bridge.dedupe_prompt_context", True),
                    "prefer_memory_companion_memory": config.bool(
                        "private_companion_bridge.prefer_memory_companion_memory",
                        True,
                    ),
                    "preserve_external_prompt_context": config.bool(
                        "private_companion_bridge.preserve_external_prompt_context",
                        True,
                    ),
                    "clean_proactive_history": config.bool("private_companion_bridge.clean_proactive_history", True),
                    "suppress_self_timeline_when_companion_seen": config.bool(
                        "private_companion_bridge.suppress_self_timeline_when_companion_seen",
                        True,
                    ),
                    "suppress_user_context_when_companion_seen": config.bool(
                        "private_companion_bridge.suppress_user_context_when_companion_seen",
                        True,
                    ),
                    "context_features_removed": False,
                },
                "visibility": {
                    "allow_self_timeline_everywhere": config.bool("visibility.allow_self_timeline_everywhere", True),
                    "allow_group_public_in_private": config.bool("visibility.allow_group_public_in_private", False),
                    "enable_acl_rules": config.bool("visibility.enable_acl_rules", True),
                },
                "maintenance": {
                    "retention_raw_event_days": config.int("maintenance.retention_raw_event_days", 7),
                    "retention_raw_event_limit": config.int("maintenance.retention_raw_event_limit", 1000),
                    "retention_summarized_timeline_days": config.int(
                        "maintenance.retention_summarized_timeline_days", 30
                    ),
                    "retention_injection_log_days": config.int(
                        "maintenance.retention_injection_log_days", 14
                    ),
                    "retention_cleanup_limit": config.int("maintenance.retention_cleanup_limit", 2000),
                    "memory_decay_enabled": config.bool("maintenance.memory_decay_enabled", True),
                    "memory_decay_after_days": config.int("maintenance.memory_decay_after_days", 180),
                    "memory_decay_idle_days": config.int("maintenance.memory_decay_idle_days", 90),
                    "memory_decay_max_importance_percent": config.int(
                        "maintenance.memory_decay_max_importance_percent",
                        74,
                    ),
                    "memory_decay_max_access_count": config.int("maintenance.memory_decay_max_access_count", 2),
                    "memory_decay_score_threshold_percent": config.int(
                        "maintenance.memory_decay_score_threshold_percent",
                        75,
                    ),
                    "memory_decay_max_candidates": config.int("maintenance.memory_decay_max_candidates", 120),
                    "memory_decay_max_groups": config.int("maintenance.memory_decay_max_groups", 8),
                    "memory_decay_min_items_per_summary": config.int(
                        "maintenance.memory_decay_min_items_per_summary",
                        4,
                    ),
                    "memory_decay_max_items_per_summary": config.int(
                        "maintenance.memory_decay_max_items_per_summary",
                        24,
                    ),
                },
                "sleep_maintenance": self.plugin.service.sleep_status(),
            }
        )

    async def retrieval_config_update(self):
        payload = await self._json()
        raw = self.plugin.service.config.raw
        if not isinstance(raw, dict):
            return self._err("runtime config is not writable", 500)
        mode = clean_text(payload.get("mode"), 40).lower()
        if mode not in {"auto", "basic", "rerank"}:
            mode = "auto"
        core_values = {
            "mode": mode,
            "rerank_provider_id": clean_text(payload.get("rerank_provider_id"), 160),
            "rerank_candidate_multiplier": max(1, self._int(payload.get("rerank_candidate_multiplier"), 5)),
            "rerank_candidate_limit": max(1, self._int(payload.get("rerank_candidate_limit"), 32)),
            "embedding_enabled": bool(payload.get("embedding_enabled")),
            "embedding_provider_id": clean_text(payload.get("embedding_provider_id"), 160),
        }
        advanced_values = {
            "rerank_timeout_ms": max(0, self._int(payload.get("rerank_timeout_ms"), 1200)),
            "embedding_candidate_limit": max(1, self._int(payload.get("embedding_candidate_limit"), 1200)),
            "embedding_top_k": max(1, self._int(payload.get("embedding_top_k"), 32)),
            "embedding_score_threshold": max(0.0, min(1.0, self._float(payload.get("embedding_score_threshold"), 0.34))),
            "embedding_weight": max(0.0, min(2.0, self._float(payload.get("embedding_weight"), 0.55))),
            "embedding_timeout_ms": max(0, self._int(payload.get("embedding_timeout_ms"), 5000)),
            "embedding_max_text_chars": max(200, self._int(payload.get("embedding_max_text_chars"), 1200)),
            "embedding_backfill_enabled": bool(payload.get("embedding_backfill_enabled", True)),
            "embedding_backfill_batch_size": max(1, self._int(payload.get("embedding_backfill_batch_size"), 50)),
        }
        raw.setdefault("retrieval", {})
        if not isinstance(raw["retrieval"], dict):
            raw["retrieval"] = {}
        raw["retrieval"].update(core_values)
        raw.setdefault("retrieval_advanced", {})
        if not isinstance(raw["retrieval_advanced"], dict):
            raw["retrieval_advanced"] = {}
        raw["retrieval_advanced"].update(advanced_values)
        self._write_plugin_config(raw)
        return self._ok(
            {
                "retrieval": {
                    "mode": str(self.plugin.service.config.get("retrieval.mode", core_values["mode"]) or core_values["mode"]),
                    "rerank_provider_id": str(
                        self.plugin.service.config.get("retrieval.rerank_provider_id", core_values["rerank_provider_id"])
                        or core_values["rerank_provider_id"]
                    ),
                    "rerank_candidate_multiplier": self.plugin.service.config.int(
                        "retrieval.rerank_candidate_multiplier",
                        core_values["rerank_candidate_multiplier"],
                    ),
                    "rerank_candidate_limit": self.plugin.service.config.int(
                        "retrieval.rerank_candidate_limit",
                        core_values["rerank_candidate_limit"],
                    ),
                    "rerank_timeout_ms": self.plugin.service.config.int(
                        "retrieval.rerank_timeout_ms",
                        advanced_values["rerank_timeout_ms"],
                    ),
                    "embedding_enabled": self.plugin.service.config.bool(
                        "retrieval.embedding_enabled",
                        core_values["embedding_enabled"],
                    ),
                    "embedding_provider_id": str(
                        self.plugin.service.config.get("retrieval.embedding_provider_id", core_values["embedding_provider_id"])
                        or core_values["embedding_provider_id"]
                    ),
                    "embedding_candidate_limit": self.plugin.service.config.int(
                        "retrieval.embedding_candidate_limit",
                        advanced_values["embedding_candidate_limit"],
                    ),
                    "embedding_top_k": self.plugin.service.config.int(
                        "retrieval.embedding_top_k",
                        advanced_values["embedding_top_k"],
                    ),
                    "embedding_score_threshold": self.plugin.service.config.float(
                        "retrieval.embedding_score_threshold",
                        advanced_values["embedding_score_threshold"],
                    ),
                    "embedding_weight": self.plugin.service.config.float(
                        "retrieval.embedding_weight",
                        advanced_values["embedding_weight"],
                    ),
                    "embedding_timeout_ms": self.plugin.service.config.int(
                        "retrieval.embedding_timeout_ms",
                        advanced_values["embedding_timeout_ms"],
                    ),
                    "embedding_max_text_chars": self.plugin.service.config.int(
                        "retrieval.embedding_max_text_chars",
                        advanced_values["embedding_max_text_chars"],
                    ),
                    "embedding_backfill_enabled": self.plugin.service.config.bool(
                        "retrieval.embedding_backfill_enabled",
                        advanced_values["embedding_backfill_enabled"],
                    ),
                    "embedding_backfill_batch_size": self.plugin.service.config.int(
                        "retrieval.embedding_backfill_batch_size",
                        advanced_values["embedding_backfill_batch_size"],
                    ),
                },
                "rerank_provider_options": await self._rerank_provider_options(),
                "embedding_provider_options": await self._embedding_provider_options(),
            }
        )

    async def config_schema(self):
        try:
            schema = self._load_config_schema()
            return self._ok(
                {
                    "schema": schema,
                    "values": self._schema_config_values(schema),
                    "provider_options": self._provider_options(),
                    "rerank_provider_options": await self._rerank_provider_options(),
                    "embedding_provider_options": await self._embedding_provider_options(),
                }
            )
        except Exception as exc:
            return self._err(f"配置 schema 读取失败: {exc}", 500)

    async def config_module_update(self):
        payload = await self._json()
        module = clean_text(payload.get("module"), 80)
        values = payload.get("values")
        if not isinstance(values, dict):
            return self._err("values must be an object", 400)
        raw = self.plugin.service.config.raw
        if not isinstance(raw, dict):
            return self._err("runtime config is not writable", 500)
        schema = self._load_config_schema()
        module_schema = schema.get(module)
        if not isinstance(module_schema, dict):
            return self._err("unknown config module", 400)
        items = module_schema.get("items")
        if not isinstance(items, dict):
            return self._err("invalid config module", 400)

        target = raw.setdefault(module, {})
        if not isinstance(target, dict):
            target = {}
            raw[module] = target
        for key, item_schema in items.items():
            if key not in values or not isinstance(item_schema, dict):
                continue
            target[key] = self._coerce_config_value(values.get(key), item_schema)
        self._write_plugin_config(raw)
        return self._ok(
            {
                "module": module,
                "values": self._schema_config_values(schema).get(module, {}),
            }
        )

    def _theme_key(self, theme: str) -> str:
        value = clean_text(theme, 40)
        if value in THEME_NAME_TO_KEY:
            return THEME_NAME_TO_KEY[value]
        if value in THEME_KEYS:
            return value
        return DEFAULT_THEME_KEY

    async def companion_personal_memory(self):
        limit = max(1, min(300, self._query_int("limit", 80)))
        selected_date = clean_text(request.args.get("date", ""), 16)
        query = clean_text(request.args.get("q", ""), 200)
        try:
            companion = await self._companion_page_bridge.export_snapshot(selected_date)
        except CompanionPageBridgeError as exc:
            if exc.code == "memory_page_companion_unavailable":
                return self._no_store(self._ok(self._companion_page_unavailable(exc.code)))
            return self._no_store(self._err(exc.code, self._companion_page_error_status(exc.code)))
        records = await self._personal_memory_records(
            limit=limit,
            query=query,
            selected_date=companion.payload["selected_date"],
        )
        payload = self._project_companion_page(companion, records)
        selected = payload["selected_date"]
        filtered = [record for record in records if self._memory_date_key(record) == selected] if selected else records
        payload["actions"] = [
            self._personal_action_projection(record)
            for record in filtered
            if self._is_personal_action(record)
        ][:limit]
        return self._no_store(self._ok(payload))

    async def companion_personal_photo(self):
        resolved = await self._read_companion_photo_from_request()
        if isinstance(resolved, dict):
            return self._no_store(self._err(str(resolved.get("error") or "memory_page_photo_unavailable"), int(resolved.get("status") or 404)))
        return self._no_store(await send_file(BytesIO(resolved.content), mimetype=resolved.mime_type))

    async def companion_personal_photo_data(self):
        resolved = await self._read_companion_photo_from_request()
        if isinstance(resolved, dict):
            return self._no_store(self._err(str(resolved.get("error") or "memory_page_photo_unavailable"), int(resolved.get("status") or 404)))
        return self._no_store(self._ok({
            "mime": resolved.mime_type,
            "size": resolved.size,
            "data_url": f"data:{resolved.mime_type};base64,{resolved.content_base64}",
        }))

    async def _read_companion_photo_from_request(self) -> CompanionPagePhoto | dict[str, Any]:
        photo_ref = clean_text(request.args.get("ref", ""), 64)
        selected_date = clean_text(request.args.get("date", ""), 16)
        photo_id = clean_text(request.args.get("id"), 120)
        expected_mode = clean_text(request.args.get("mode", ""), 16)
        if expected_mode not in {"", "formal", "legacy"}:
            return {"error": "memory_page_photo_ref_invalid", "status": 400}

        async def refresh_photo_ref() -> str | dict[str, Any]:
            dates = [selected_date]
            if photo_id and selected_date:
                dates.append("")
            last_error = "memory_page_photo_unavailable"
            for lookup_date in dates:
                try:
                    snapshot = await self._companion_page_bridge.export_snapshot(
                        lookup_date,
                        expected_mode=expected_mode or None,
                    )
                except CompanionPageBridgeError as exc:
                    last_error = exc.code
                    continue
                for item in snapshot.payload["day"]["photos"]:
                    if item["id"] == photo_id and item["available"] is True:
                        return item["photo_ref"]
            if last_error != "memory_page_photo_unavailable":
                return self._companion_photo_error(last_error)
            return {"error": "memory_page_photo_unavailable", "status": 404}

        if not photo_ref and photo_id:
            refreshed = await refresh_photo_ref()
            if isinstance(refreshed, dict):
                return refreshed
            photo_ref = refreshed
        if not photo_ref:
            return {"error": "memory_page_photo_ref_invalid", "status": 400}
        try:
            return await self._companion_page_bridge.read_photo(photo_ref, expected_mode=expected_mode or None)
        except CompanionPageBridgeError as exc:
            if photo_id and exc.code in {"memory_page_photo_ref_stale", "memory_page_photo_ref_expired", "memory_page_photo_changed"}:
                refreshed = await refresh_photo_ref()
                if isinstance(refreshed, dict):
                    return refreshed
                try:
                    return await self._companion_page_bridge.read_photo(refreshed, expected_mode=expected_mode or None)
                except CompanionPageBridgeError as refreshed_exc:
                    return self._companion_photo_error(refreshed_exc.code)
            return self._companion_photo_error(exc.code)

    @staticmethod
    def _companion_page_unavailable(code: str) -> dict[str, Any]:
        return {"available": False, "plugin_name": COMPANION_PLUGIN_ID, "reason": clean_text(code, 120) or "memory_page_companion_unavailable"}

    @staticmethod
    def _companion_photo_error(code: str) -> dict[str, Any]:
        if code in {"memory_page_photo_ref_stale", "memory_page_photo_ref_expired", "memory_page_contract_downgrade"}:
            status = 410
        elif code in {"memory_page_photo_ref_invalid", "memory_page_snapshot_invalid_date"}:
            status = 400
        elif code == "memory_page_photo_unavailable":
            status = 404
        elif code in {"memory_page_photo_too_large", "memory_page_snapshot_too_large"}:
            status = 413
        elif code == "memory_page_photo_unsupported":
            status = 415
        elif code.startswith("memory_page_"):
            status = 503
        else:
            status = 409
        return {"error": clean_text(code, 120), "status": status}

    @staticmethod
    def _companion_page_error_status(code: str) -> int:
        if code == "memory_page_snapshot_invalid_date":
            return 400
        if code == "memory_page_snapshot_too_large":
            return 413
        return 503

    @staticmethod
    def _no_store(response: Any) -> Any:
        headers = getattr(response, "headers", None)
        if headers is not None:
            headers["Cache-Control"] = "private, no-store"
            headers["Pragma"] = "no-cache"
            headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def _personal_memory_records(self, *, limit: int, query: str, selected_date: str) -> list[Any]:
        try:
            records = await self.plugin.service.store.list_memories(
                limit=max(limit * 12, 1200), include_pending=False, query=query, visibility="bot_self"
            )
            if selected_date:
                date_records = await self.plugin.service.store.list_memories(
                    limit=240, include_pending=False, query=selected_date, visibility="bot_self"
                )
                records = self._merge_records_by_id(records, date_records)
            return records
        except Exception:
            return []

    def _project_companion_page(self, snapshot: CompanionPageSnapshot, records: list[Any]) -> dict[str, Any]:
        value = snapshot.payload
        dates = self._personal_dates(value["available_dates"], records)
        selected_date = value["selected_date"] or (dates[0] if dates else "")
        if selected_date and selected_date not in dates:
            dates.insert(0, selected_date)
        day = value["day"]
        plan = copy.deepcopy(day["plan"])
        current_item = copy.deepcopy(day["current_item"])
        memory_plan = self._schedule_memory_plan_for_date(records, selected_date)
        if memory_plan and (plan.get("source") == "none" or not plan.get("items")):
            plan = memory_plan
            current_item = {"index": None, "time": "", "activity": "", "mood": "", "message_seed": ""}
        formal_details = [
            {"key": item["id"], "index": "" if item["index"] is None else item["index"], "status": item["status"], "time": item["time"], "summary": item["summary"], "today_events": list(item["today_events"]), "proactive_events": list(item["proactive_events"]), "state_variables": list(item["state_variables"])}
            for item in day["details"]
        ]
        details = self._merge_companion_details(formal_details, self._schedule_memory_details(records, selected_date, plan))
        album = [self._project_companion_photo(item, snapshot.mode) for item in day["photos"]]
        subjective = self._merge_personal_subjective_memories(day["diaries"], selected_date, records)
        return {
            "available": True,
            "plugin_name": COMPANION_PLUGIN_ID,
            "daily_plan_enabled": value["features"]["daily_plan_enabled"],
            "detail_enabled": value["features"]["detail_enhancement_enabled"],
            "bridge_available": value["coordination"]["available"],
            "bridge_state": value["coordination"]["state"],
            "bridge_reason": value["coordination"]["reason_code"],
            "selected_date": selected_date,
            "dates": dates,
            "snapshot": {"bot_name": day["bot_name"], "plan": plan, "current_item": current_item, "daily_state": copy.deepcopy(day["daily_state"]), "details": details, "album": album, "subjective_memories": subjective},
        }

    def _project_companion_photo(self, item: dict[str, Any], mode: str) -> dict[str, Any]:
        title = {"daily_outfit": "每日穿搭图", "recent_photo": "近期自拍", "life_photo": "生活分享图"}.get(item["kind"], "近期照片")
        query_parts = [
            f"ref={quote(item['photo_ref'], safe='')}",
            f"date={quote(item['date'], safe='')}",
            f"id={quote(item['id'], safe='')}",
        ] if item.get("photo_ref") else []
        if query_parts:
            query_parts.append(f"mode={quote(mode, safe='')}")
        query = "&".join(query_parts)
        return {"id": item["id"], "date": item["date"], "kind": item["kind"], "title": title, "url": f"{PAGE_API_PREFIXES[0]}/companion/personal-photo?{query}" if query else "", "image_data_url": f"/companion/personal-photo-data?{query}" if query else "", "exists": item["available"], "backend": "", "prompt": "", "note": "", "error": item["error_code"], "generated_at": self._timestamp_label(item["generated_at"])}

    def _personal_dates(self, companion_dates: list[str], records: list[Any]) -> list[str]:
        dates = set(companion_dates)
        for record in records:
            if self._is_personal_action(record) or self._is_personal_schedule_memory(record) or self._is_personal_subjective_memory(record):
                value = self._memory_date_key(record)
                if value:
                    dates.add(value)
        return sorted(dates, reverse=True)[:180]

    @staticmethod
    def _personal_action_projection(record: Any) -> dict[str, Any]:
        metadata = getattr(record, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        try:
            image_count = max(0, min(8, int(metadata.get("image_count") or 0)))
        except (TypeError, ValueError):
            image_count = 0
        return {"id": clean_text(getattr(record, "id", ""), 160), "memory_type": clean_text(getattr(record, "memory_type", ""), 80), "visibility": "bot_self", "reality_level": clean_text(getattr(record, "reality_level", ""), 40), "content": clean_text(getattr(record, "content", ""), 520), "tags": [clean_text(tag, 80) for tag in (getattr(record, "tags", []) or []) if clean_text(tag, 80)][:8], "created_at": clean_text(getattr(record, "created_at", ""), 80), "occurred_at": clean_text(getattr(record, "occurred_at", ""), 80), "metadata": {"action_label": clean_text(metadata.get("action_label"), 80), "image_count": image_count, "text": clean_text(metadata.get("text"), 220)}}

    def _merge_personal_subjective_memories(self, companion_diaries: list[dict[str, Any]], selected_date: str, records: list[Any]) -> list[dict[str, Any]]:
        rows = [copy.deepcopy(item) for item in companion_diaries]
        seen = {(clean_text(item.get("date"), 16), clean_text(item.get("summary"), 220), clean_text(item.get("body"), 520)) for item in rows}
        for record in records:
            if not self._is_personal_subjective_memory(record):
                continue
            record_date = self._memory_date_key(record)
            if selected_date and record_date != selected_date:
                continue
            metadata = getattr(record, "metadata", {}) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            body = clean_text(getattr(record, "content", ""), 520)
            key = (record_date, "梦境碎片", body)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"date": record_date, "summary": "梦境碎片", "body": body, "share_seed": "", "tags": [value for value in ("梦境碎片", clean_text(metadata.get("dream_type"), 40), clean_text(metadata.get("dream_mood"), 40)) if value][:8], "today_events": [], "proactive_events": [], "long_term_events": []})
            if len(rows) >= 6:
                break
        return rows[:6]

    async def _resolve_companion_personal_photo_path_from_request(self) -> Path | dict[str, Any]:
        status = self._private_companion_status()
        if not status["available"]:
            return {"error": status.get("reason") or "private companion unavailable", "status": 404}
        plugin = status.get("plugin")
        data = getattr(plugin, "data", {}) if plugin is not None else {}
        if not isinstance(data, dict):
            data = {}
        selected_date = clean_text(request.args.get("date", ""), 16)
        photo_id = clean_text(request.args.get("id"), 120)
        # When looking up by photo_id, skip date filtering so photos from any date can be served
        lookup_date = "" if photo_id else selected_date
        records: list[Any] = []
        try:
            records = await self.plugin.service.store.list_memories(
                limit=1200,
                include_pending=False,
                query=selected_date if selected_date and not photo_id else "",
                visibility="bot_self",
            )
        except Exception:
            records = []
        for item in self._private_companion_album(
            data,
            lookup_date,
            records,
            limit=1200 if photo_id else 80,
            plugin=plugin,
            include_local_path=True,
        ):
            if photo_id and clean_text(item.get("id"), 120) != photo_id:
                continue
            raw_path = clean_text(item.get("_local_path"), 500)
            if not raw_path:
                continue
            resolved = self._safe_companion_photo_path(raw_path, plugin)
            if resolved is not None:
                return resolved
        return {"error": "photo_not_found", "status": 404}

    def _private_companion_status(self) -> dict[str, Any]:
        for module_name in (
            "data.plugins.astrbot_plugin_private_companion.main",
            "astrbot_plugin_private_companion.main",
        ):
            module = sys.modules.get(module_name)
            if module is None:
                continue
            getter = getattr(module, "get_private_companion_api", None)
            if not callable(getter):
                continue
            try:
                api = getter()
            except Exception:
                api = None
            if api is None:
                continue
            plugin = getattr(api, "_plugin", None)
            bridge_status: dict[str, Any] = {}
            status_getter = getattr(plugin, "_memory_companion_coordination_status", None) if plugin else None
            if callable(status_getter):
                try:
                    candidate = status_getter()
                    if isinstance(candidate, dict):
                        bridge_status = candidate
                except Exception:
                    bridge_status = {"available": False, "state": "degraded", "reason": "bridge_status_failed"}
            bridge_available = bool(
                bridge_status.get("available")
                and bridge_status.get("state") not in {"degraded", "local_only", "disabled", "inactive"}
                and not bridge_status.get("degraded")
            )
            return {
                "available": True,
                "plugin_name": "astrbot_plugin_private_companion",
                "daily_plan_enabled": bool(getattr(plugin, "enable_daily_plan", False)) if plugin else False,
                "detail_enabled": bool(getattr(plugin, "enable_detail_enhancement", False)) if plugin else False,
                "bridge_available": bridge_available,
                "bridge_state": clean_text(bridge_status.get("state") or "degraded", 40),
                "bridge_reason": clean_text(
                    bridge_status.get("reason") or bridge_status.get("error_code") or "bridge_status_unavailable",
                    120,
                ),
                "plugin": plugin,
            }
        return {
            "available": False,
            "plugin_name": "astrbot_plugin_private_companion",
            "reason": "未检测到已加载的主动陪伴插件",
        }

    @staticmethod
    def _merge_records_by_id(primary: list[Any], extra: list[Any]) -> list[Any]:
        rows: list[Any] = []
        seen: set[str] = set()
        for record in [*(primary or []), *(extra or [])]:
            record_id = clean_text(getattr(record, "id", ""), 160)
            key = record_id or f"{getattr(record, 'memory_type', '')}:{getattr(record, 'content', '')}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(record)
        return rows

    def _private_companion_snapshot(
        self,
        plugin: Any,
        selected_date: str = "",
        records: list[Any] | None = None,
    ) -> dict[str, Any]:
        if plugin is None:
            return {}
        data = getattr(plugin, "data", {})
        if not isinstance(data, dict):
            data = {}
        plan = self._private_companion_plan_for_date(data, selected_date)
        if not isinstance(plan, dict):
            plan = {}
        memory_plan = self._schedule_memory_plan_for_date(records or [], selected_date)
        if memory_plan and len(memory_plan.get("items", []) or []) > len(plan.get("items", []) or []):
            plan = memory_plan
        state = data.get("daily_state", {})
        if not isinstance(state, dict):
            state = {}
        enhanced = self._private_companion_detail_segments_for_date(data, selected_date)
        current_item = None
        getter = getattr(plugin, "_get_current_plan_item", None)
        if callable(getter) and (not selected_date or selected_date == clean_text(plan.get("date"), 16)):
            try:
                current_item = getter(plan)
            except Exception:
                current_item = None
        if not isinstance(current_item, dict):
            current_item = {}
        details = self._merge_companion_details(
            self._compact_details(enhanced),
            self._story_plan_details_for_date(data, selected_date, plan),
            self._schedule_memory_details(records or [], selected_date, plan),
        )
        return {
            "bot_name": str(getattr(plugin, "bot_name", "") or ""),
            "plan": self._compact_plan(plan),
            "current_item": self._compact_plan_item(current_item),
            "daily_state": {
                "date": clean_text(state.get("date"), 40),
                "energy": state.get("energy", ""),
                "mood_bias": clean_text(state.get("mood_bias"), 80),
                "sleep": clean_text(state.get("sleep"), 120),
                "weather": clean_text(state.get("weather"), 160),
                "note": clean_text(state.get("note"), 240),
            },
            "details": details,
            "album": self._private_companion_album(data, selected_date, records or [], plugin=plugin),
            "subjective_memories": self._private_companion_subjective_memories(data, selected_date, records or []),
        }

    def _private_companion_album(
        self,
        data: dict[str, Any],
        selected_date: str,
        records: list[Any] | None = None,
        limit: int = 8,
        *,
        plugin: Any = None,
        include_local_path: bool = False,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(raw: Any, source: str) -> None:
            if not isinstance(raw, dict):
                return
            date = clean_text(raw.get("date"), 16)
            generated_at = raw.get("generated_at") or raw.get("ts")
            if not date and generated_at:
                date = self._timestamp_date_key(generated_at)
            if selected_date and date and date != selected_date:
                return
            path = clean_text(raw.get("path"), 500)
            error = clean_text(raw.get("error"), 240)
            if not path and not error:
                return
            item_id = clean_text(raw.get("trace"), 80)
            if not item_id:
                item_id = hashlib.sha1(f"{source}:{date}:{path or error}".encode("utf-8", errors="ignore")).hexdigest()[:16]
            if item_id in seen:
                return
            seen.add(item_id)
            safe_path = self._safe_companion_photo_path(path, plugin) if path else None
            exists = safe_path is not None
            query = f"date={quote(date, safe='')}&id={quote(item_id, safe='')}"
            row = {
                    "id": item_id,
                    "date": date,
                    "kind": clean_text(raw.get("kind"), 40) or ("daily_outfit" if source == "daily_outfit_photo" else source),
                    "title": {
                        "daily_outfit_photo": "每日穿搭图",
                        "recent_photo": "近期自拍",
                        "life_photo": "生活分享图",
                    }.get(source, "近期照片"),
                    "url": f"{PAGE_API_PREFIXES[0]}/companion/personal-photo?{query}",
                    "image_data_url": f"/companion/personal-photo-data?{query}",
                    "exists": exists,
                    "backend": clean_text(raw.get("backend"), 80),
                    "prompt": clean_text(raw.get("prompt"), 360),
                    "note": clean_text(raw.get("note"), 220),
                    "error": error if not exists else "",
                    "generated_at": self._timestamp_label(generated_at),
                }
            if include_local_path and safe_path is not None:
                row["_local_path"] = str(safe_path)
            rows.append(row)

        add(data.get("daily_outfit_photo"), "daily_outfit_photo")
        recent = data.get("recent_photo_generations", [])
        if isinstance(recent, list):
            for item in recent[:12]:
                if not isinstance(item, dict):
                    continue
                ok = bool(item.get("ok"))
                path = clean_text(item.get("path"), 500)
                if not ok or not path:
                    continue
                session = clean_text(item.get("session"), 100)
                kind = clean_text(item.get("kind"), 30)
                if session == "daily_outfit" or kind == "selfie":
                    add(item, "recent_photo")
                elif session.startswith("natural_photo") or kind == "text2img":
                    add(item, "life_photo")

        for record in records or []:
            if not self._is_personal_album_memory(record):
                continue
            metadata = getattr(record, "metadata", {}) or {}
            if not isinstance(metadata, dict):
                continue
            tags = {clean_text(tag, 80) for tag in (getattr(record, "tags", []) or []) if clean_text(tag, 80)}
            memory_type = clean_text(getattr(record, "memory_type", ""), 80)
            payload = metadata.get("payload") if isinstance(metadata.get("payload"), dict) else {}
            path = clean_text(
                metadata.get("image_path") or metadata.get("path")
                or payload.get("image_path") or payload.get("path"),
                500,
            )
            if not path:
                continue
            date = clean_text(metadata.get("date"), 16) or clean_text(payload.get("date"), 16) or self._memory_date_key(record)
            if selected_date and date and date != selected_date:
                continue
            source = "memory_photo"
            if "daily_outfit" in tags or "outfit" in tags:
                source = "daily_outfit_photo"
            elif memory_type == "image_action" or "life_photo" in tags:
                source = "life_photo"
            item_id = clean_text(getattr(record, "id", ""), 120)
            if not item_id:
                item_id = hashlib.sha1(f"memory:{date}:{path}".encode("utf-8", errors="ignore")).hexdigest()[:16]
            if item_id in seen:
                continue
            seen.add(item_id)
            safe_path = self._safe_companion_photo_path(path, plugin) if path else None
            exists = safe_path is not None
            query = f"date={quote(date, safe='')}&id={quote(item_id, safe='')}"
            row = {
                    "id": item_id,
                    "date": date,
                    "kind": "daily_outfit" if source == "daily_outfit_photo" else source,
                    "title": {
                        "daily_outfit_photo": "每日穿搭图",
                        "life_photo": "生活分享图",
                    }.get(source, "记忆照片"),
                    "url": f"{PAGE_API_PREFIXES[0]}/companion/personal-photo?{query}",
                    "image_data_url": f"/companion/personal-photo-data?{query}",
                    "exists": exists,
                    "backend": clean_text(metadata.get("backend") or payload.get("backend"), 80),
                    "prompt": clean_text(metadata.get("prompt_preview") or metadata.get("prompt") or payload.get("prompt"), 360),
                    "note": clean_text(metadata.get("note") or payload.get("note") or getattr(record, "content", ""), 220),
                    "error": "" if exists else "图片文件不可用",
                    "generated_at": self._timestamp_label(getattr(record, "occurred_at", "") or getattr(record, "created_at", "")),
                }
            if include_local_path and safe_path is not None:
                row["_local_path"] = str(safe_path)
            rows.append(row)
        safe_limit = max(1, min(2000, int(limit or 8)))
        return rows[:safe_limit]

    def _safe_companion_photo_path(self, raw_path: Any, plugin: Any = None) -> Path | None:
        text = clean_text(raw_path, 1000)
        if not text:
            return None
        roots: list[Path] = []
        candidates = [
            getattr(plugin, "data_dir", "") if plugin is not None else "",
            getattr(plugin, "plugin_data_dir", "") if plugin is not None else "",
            getattr(getattr(self.plugin, "service", None), "data_dir", ""),
        ]
        data_file = getattr(plugin, "data_file", "") if plugin is not None else ""
        if data_file:
            candidates.append(Path(str(data_file)).parent)
        for candidate in candidates:
            if not candidate:
                continue
            try:
                root = Path(str(candidate)).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if root not in roots:
                roots.append(root)
        if not roots:
            return None
        source = Path(text).expanduser()
        paths = [source] if source.is_absolute() else [root / source for root in roots]
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
        max_bytes = 20 * 1024 * 1024
        for candidate in paths:
            try:
                resolved = candidate.resolve()
                if not any(resolved.is_relative_to(root) for root in roots):
                    continue
                mime = mimetypes.guess_type(str(resolved))[0] or ""
                if resolved.suffix.lower() not in allowed_extensions or not mime.startswith("image/"):
                    continue
                stat = resolved.stat()
                if not resolved.is_file() or stat.st_size <= 0 or stat.st_size > max_bytes:
                    continue
            except (OSError, RuntimeError, ValueError):
                continue
            return resolved
        return None

    def _private_companion_subjective_memories(
        self,
        data: dict[str, Any],
        selected_date: str,
        records: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        diaries = data.get("bot_diaries", [])
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        if isinstance(diaries, list):
            for diary in reversed(diaries):
                if not isinstance(diary, dict):
                    continue
                date = clean_text(diary.get("date"), 16)
                if selected_date and date != selected_date:
                    continue
                story_plan = diary.get("story_plan") if isinstance(diary.get("story_plan"), dict) else {}
                row_key = f"diary:{date}:{clean_text(diary.get('summary'), 120)}"
                seen.add(row_key)
                rows.append(
                    {
                        "date": date,
                        "summary": clean_text(diary.get("summary"), 220),
                        "body": clean_text(diary.get("body"), 520),
                        "share_seed": clean_text(diary.get("share_seed"), 180),
                        "tags": [clean_text(tag, 40) for tag in (diary.get("tags") or []) if clean_text(tag, 40)][:8]
                        if isinstance(diary.get("tags"), list)
                        else [],
                        "today_events": self._compact_detail_events(story_plan.get("today_events")) if story_plan else [],
                        "proactive_events": self._compact_detail_events(story_plan.get("proactive_events")) if story_plan else [],
                        "long_term_events": self._compact_detail_events(story_plan.get("long_term_events")) if story_plan else [],
                    }
                )
                if len(rows) >= 4:
                    break
        for record in records or []:
            if not self._is_personal_subjective_memory(record):
                continue
            date = self._memory_date_key(record)
            if selected_date and date != selected_date:
                continue
            record_id = clean_text(getattr(record, "id", ""), 120)
            if record_id in seen:
                continue
            seen.add(record_id)
            metadata = getattr(record, "metadata", {}) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            rows.append(
                {
                    "date": date,
                    "summary": "梦境碎片",
                    "body": clean_text(getattr(record, "content", ""), 520),
                    "share_seed": "",
                    "tags": [
                        tag
                        for tag in ["梦境碎片", clean_text(metadata.get("dream_type"), 40), clean_text(metadata.get("dream_mood"), 40)]
                        if tag
                    ],
                    "today_events": [],
                    "proactive_events": [],
                    "long_term_events": [],
                }
            )
            if len(rows) >= 6:
                break
        return rows

    def _private_companion_plan_for_date(self, data: dict[str, Any], selected_date: str) -> dict[str, Any]:
        plan = data.get("daily_plan", {})
        if isinstance(plan, dict) and (not selected_date or clean_text(plan.get("date"), 16) == selected_date):
            return plan
        history = data.get("daily_plan_history", [])
        if isinstance(history, list):
            for entry in reversed(history):
                if not isinstance(entry, dict):
                    continue
                if clean_text(entry.get("date"), 16) != selected_date:
                    continue
                items = entry.get("items")
                if isinstance(items, list) and items:
                    return {
                        "date": selected_date,
                        "source": entry.get("source") or "history",
                        "items": [
                            self._compact_plan_item(item, index=index)
                            for index, item in enumerate(items)
                            if isinstance(item, dict)
                        ][:18],
                    }
                return {
                    "date": selected_date,
                    "source": entry.get("source") or "history",
                    "items": self._history_samples_to_plan_items(entry.get("sample")),
                }
        return plan if isinstance(plan, dict) else {}

    def _private_companion_detail_segments_for_date(self, data: dict[str, Any], selected_date: str) -> dict[str, Any]:
        current_day = clean_text(data.get("detail_enhanced_day"), 16)
        current = data.get("detail_enhanced_segments", {})
        if isinstance(current, dict) and (not selected_date or current_day == selected_date):
            return current
        history = data.get("detail_enhanced_history", [])
        if isinstance(history, list):
            for entry in reversed(history):
                if not isinstance(entry, dict):
                    continue
                if clean_text(entry.get("date"), 16) != selected_date:
                    continue
                segments = entry.get("segments")
                return segments if isinstance(segments, dict) else {}
        return {}

    def _history_samples_to_plan_items(self, samples: Any) -> list[dict[str, Any]]:
        if not isinstance(samples, list):
            return []
        rows = []
        for sample in samples:
            text = clean_text(sample, 180)
            if not text:
                continue
            parts = text.split(maxsplit=1)
            if parts and ":" in parts[0]:
                rows.append({"index": len(rows), "time": parts[0], "activity": parts[1] if len(parts) > 1 else ""})
            else:
                rows.append({"index": len(rows), "time": "", "activity": text})
        return rows

    def _private_companion_dates(self, plugin: Any, records: list[Any]) -> list[str]:
        dates: set[str] = set()
        if plugin is not None:
            data = getattr(plugin, "data", {})
            if isinstance(data, dict):
                plan = data.get("daily_plan", {})
                if isinstance(plan, dict) and clean_text(plan.get("date"), 16):
                    dates.add(clean_text(plan.get("date"), 16))
                history = data.get("daily_plan_history", [])
                if isinstance(history, list):
                    for entry in history:
                        if isinstance(entry, dict) and clean_text(entry.get("date"), 16):
                            dates.add(clean_text(entry.get("date"), 16))
                detail_history = data.get("detail_enhanced_history", [])
                if isinstance(detail_history, list):
                    for entry in detail_history:
                        if isinstance(entry, dict) and clean_text(entry.get("date"), 16):
                            dates.add(clean_text(entry.get("date"), 16))
                story_history = data.get("daily_story_plan_history", [])
                if isinstance(story_history, list):
                    for entry in story_history:
                        if isinstance(entry, dict) and clean_text(entry.get("date"), 16):
                            dates.add(clean_text(entry.get("date"), 16))
                if clean_text(data.get("detail_enhanced_day"), 16):
                    dates.add(clean_text(data.get("detail_enhanced_day"), 16))
                diaries = data.get("bot_diaries", [])
                if isinstance(diaries, list):
                    for diary in diaries:
                        if isinstance(diary, dict) and clean_text(diary.get("date"), 16):
                            dates.add(clean_text(diary.get("date"), 16))
        for record in records:
            metadata = getattr(record, "metadata", {}) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            key = clean_text(metadata.get("date"), 16) if self._is_personal_schedule_memory(record) else ""
            key = key or self._memory_date_key(record)
            if key and (
                self._is_personal_action(record)
                or self._is_personal_schedule_memory(record)
                or self._is_personal_album_memory(record)
                or self._is_personal_subjective_memory(record)
            ):
                dates.add(key)
        return sorted(dates, reverse=True)

    def _memory_date_key(self, record: Any) -> str:
        metadata = getattr(record, "metadata", {}) or {}
        date = clean_text(metadata.get("date"), 16) if isinstance(metadata, dict) else ""
        return date or self._date_key(getattr(record, "occurred_at", "") or getattr(record, "created_at", ""))

    def _date_key(self, value: Any) -> str:
        text = clean_text(value, 80)
        if not text:
            return ""
        try:
            normalized = text.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is not None:
                dt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
            return dt.date().isoformat()
        except Exception:
            return text[:10] if len(text) >= 10 else ""

    def _timestamp_date_key(self, value: Any) -> str:
        try:
            ts = float(value or 0)
        except Exception:
            return self._date_key(value)
        if ts <= 0:
            return ""
        return datetime.fromtimestamp(ts, ZoneInfo("Asia/Shanghai")).date().isoformat()

    def _timestamp_label(self, value: Any) -> str:
        try:
            ts = float(value or 0)
        except Exception:
            return clean_text(value, 40)
        if ts <= 0:
            return ""
        return datetime.fromtimestamp(ts, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")

    def _is_personal_action(self, record: Any) -> bool:
        tags = getattr(record, "tags", []) or []
        tag_set = {clean_text(tag, 80) for tag in tags if clean_text(tag, 80)}
        action_types = {
            "self_action",
            "proactive_message",
            "search_action",
            "creative_work",
            "image_action",
            "qzone_action",
            "reading_memory",
        }
        non_action_tags = {
            "schedule",
            "daily_plan",
            "daily_detail",
            "daily_outfit",
            "outfit",
            "dream",
            "dream_fragment",
        }
        positive_action_tags = {
            "bot_action",
            "qzone",
            "qzone_publish",
            "proactive",
            "proactive_message",
            "search",
            "creative_work",
            "image_action",
            "reading",
            "self_meal",
        }
        memory_type = getattr(record, "memory_type", "")
        return (
            getattr(record, "visibility", "") == "bot_self"
            and (
                memory_type in action_types
                or bool(tag_set & positive_action_tags)
                or (
                    getattr(record, "source_plugin", "") == "private_companion"
                    and memory_type != "schedule_fragment"
                    and not bool(tag_set & non_action_tags)
                )
            )
        )

    def _is_personal_schedule_memory(self, record: Any) -> bool:
        tags = getattr(record, "tags", []) or []
        tag_set = {clean_text(tag, 80) for tag in tags if clean_text(tag, 80)}
        metadata = getattr(record, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        content = clean_text(getattr(record, "content", ""), 360)
        payload = metadata.get("payload") if isinstance(metadata.get("payload"), dict) else {}
        memory_type = clean_text(getattr(record, "memory_type", ""), 80)
        return (
            getattr(record, "visibility", "") == "bot_self"
            and (
                memory_type in {"schedule_fragment", "bot_schedule_plan", "bot_detail_fragment", "bot_calendar_event"}
                or "schedule" in tag_set
                or "daily_plan" in tag_set
                or "daily_detail" in tag_set
                or bool(clean_text(metadata.get("start"), 20) or clean_text(metadata.get("end"), 20))
                or bool(
                    clean_text(payload.get("date"), 16)
                    and (
                        clean_text(payload.get("summary"), 180)
                        or isinstance(payload.get("items"), list)
                        or isinstance(payload.get("events"), list)
                        or isinstance(payload.get("today_events"), list)
                    )
                )
                or "当日生活日程" in content
                or "日程细化" in content
            )
        )

    def _is_personal_album_memory(self, record: Any) -> bool:
        if getattr(record, "visibility", "") != "bot_self":
            return False
        metadata = getattr(record, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            return False
        payload = metadata.get("payload") if isinstance(metadata.get("payload"), dict) else {}
        if not clean_text(metadata.get("image_path") or metadata.get("path") or payload.get("image_path") or payload.get("path"), 500):
            return False
        tags = {clean_text(tag, 80) for tag in (getattr(record, "tags", []) or []) if clean_text(tag, 80)}
        return (
            getattr(record, "memory_type", "") in {"image_action", "persona_life", "bot_media_memory"}
            or bool(tags & {"daily_outfit", "outfit", "life_photo", "image", "current_state"})
            or getattr(record, "source_plugin", "") == "private_companion"
        )

    def _is_personal_subjective_memory(self, record: Any) -> bool:
        if getattr(record, "visibility", "") != "bot_self":
            return False
        tags = {clean_text(tag, 80) for tag in (getattr(record, "tags", []) or []) if clean_text(tag, 80)}
        return bool(tags & {"dream", "dream_fragment", "subjective_memory", "bot_diary"})

    def _compact_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        items = plan.get("items", [])
        if not isinstance(items, list):
            items = []
        return {
            "date": clean_text(plan.get("date"), 40),
            "source": clean_text(plan.get("source"), 40),
            "items": [
                self._compact_plan_item(item, index=index)
                for index, item in enumerate(items)
                if isinstance(item, dict)
            ][:18],
        }

    def _compact_plan_item(self, item: dict[str, Any], index: int | None = None) -> dict[str, Any]:
        return {
            "index": index if index is not None else "",
            "time": clean_text(item.get("time"), 20),
            "activity": clean_text(item.get("activity") or item.get("title"), 180),
            "mood": clean_text(item.get("mood"), 80),
            "message_seed": clean_text(item.get("message_seed"), 220),
        }

    def _compact_details(self, enhanced: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for key, item in enhanced.items():
            if not isinstance(item, dict):
                continue
            key_text = clean_text(key, 80)
            rows.append(
                {
                    "key": key_text,
                    "index": self._detail_index_from_key(key_text),
                    "status": clean_text(item.get("status"), 40),
                    "time": clean_text(item.get("time") or self._detail_time_from_key(key_text) or item.get("started_at"), 40),
                    "summary": clean_text(item.get("summary"), 180),
                    "today_events": self._compact_detail_events(item.get("today_events")),
                    "proactive_events": self._compact_detail_events(item.get("proactive_events")),
                    "state_variables": self._compact_detail_events(item.get("state_variables")),
                }
            )
        return rows[-12:]

    def _merge_companion_details(self, *sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in sources:
            if not isinstance(source, list):
                continue
            for item in source:
                if not isinstance(item, dict):
                    continue
                key = clean_text(item.get("key"), 120) or f"{item.get('index')}:{item.get('time')}"
                if key in seen:
                    continue
                seen.add(key)
                rows.append(item)
        return rows[-18:]

    def _story_plan_details_for_date(
        self,
        data: dict[str, Any],
        selected_date: str,
        plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        story = self._story_plan_for_date(data, selected_date)
        if not story:
            return []
        grouped: dict[str, dict[str, Any]] = {}

        def ensure(window: str) -> dict[str, Any]:
            key = clean_text(window, 40) or "story"
            row = grouped.setdefault(
                key,
                {
                    "key": f"story:{selected_date}:{key}",
                    "index": self._schedule_detail_index_for_time(plan, key.split("-", 1)[0].strip()),
                    "status": "story_plan",
                    "time": key,
                    "summary": "",
                    "today_events": [],
                    "proactive_events": [],
                    "state_variables": [],
                },
            )
            return row

        for item in story.get("today_events") if isinstance(story.get("today_events"), list) else []:
            if not isinstance(item, dict):
                continue
            window = clean_text(item.get("window") or item.get("time") or item.get("range"), 40)
            row = ensure(window)
            text = clean_text(item.get("event") or item.get("content") or item.get("text"), 180)
            if text and text not in row["today_events"]:
                row["today_events"].append(text)
            if not row["summary"]:
                row["summary"] = text

        for item in story.get("proactive_events") if isinstance(story.get("proactive_events"), list) else []:
            if not isinstance(item, dict):
                continue
            window = clean_text(item.get("window") or item.get("time") or item.get("range"), 40)
            row = ensure(window)
            text = clean_text(
                item.get("topic") or item.get("why") or item.get("motive") or item.get("reason") or item.get("action"),
                180,
            )
            if text and text not in row["proactive_events"]:
                row["proactive_events"].append(text)

        rows = [row for row in grouped.values() if row["summary"] or row["today_events"] or row["proactive_events"]]
        rows.sort(key=lambda item: clean_text(item.get("time"), 40))
        return rows[-18:]

    def _story_plan_for_date(self, data: dict[str, Any], selected_date: str) -> dict[str, Any]:
        current = data.get("daily_story_plan", {})
        if isinstance(current, dict) and (not selected_date or clean_text(current.get("date"), 16) == selected_date):
            return current
        history = data.get("daily_story_plan_history", [])
        if isinstance(history, list):
            for entry in reversed(history):
                if isinstance(entry, dict) and clean_text(entry.get("date"), 16) == selected_date:
                    return entry
        return {}

    def _schedule_memory_details(
        self,
        records: list[Any],
        selected_date: str,
        plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not selected_date:
            return []
        rows: list[dict[str, Any]] = []
        for record in records:
            if not self._is_personal_schedule_memory(record):
                continue
            metadata = getattr(record, "metadata", {}) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            payload = metadata.get("payload") if isinstance(metadata.get("payload"), dict) else {}
            date = clean_text(metadata.get("date"), 16) or clean_text(payload.get("date"), 16) or self._memory_date_key(record)
            if date != selected_date:
                continue
            start = clean_text(metadata.get("start"), 20) or clean_text(payload.get("start"), 20)
            end = clean_text(metadata.get("end"), 20) or clean_text(payload.get("end"), 20)
            summary = clean_text(metadata.get("summary"), 180) or clean_text(payload.get("summary"), 180)
            content = str(getattr(record, "content", "") or "")[:1600]
            if not summary:
                summary = self._schedule_detail_summary_from_content(content)
            today_events = self._schedule_detail_lines_from_content(content, "生活片段：")
            proactive_events = self._schedule_detail_lines_from_content(content, "可能主动念头：")
            if not today_events:
                today_events = self._schedule_detail_payload_lines(payload.get("events") or payload.get("today_events"))
            if not proactive_events:
                proactive_events = self._schedule_detail_payload_lines(payload.get("proactive_events"))
            if not summary and not today_events and not proactive_events:
                continue
            index = self._schedule_detail_index_for_time(plan, start)
            rows.append(
                {
                    "key": clean_text(getattr(record, "id", ""), 120) or f"memory:{selected_date}:{start}:{end}",
                    "index": index,
                    "status": "memory",
                    "time": f"{start}-{end}" if start and end else start,
                    "summary": summary,
                    "today_events": today_events,
                    "proactive_events": proactive_events,
                    "state_variables": [],
                }
            )
        rows.sort(key=lambda item: clean_text(item.get("time"), 40))
        return rows[-18:]

    @staticmethod
    def _schedule_detail_payload_lines(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        rows: list[str] = []
        for item in value[:8]:
            if isinstance(item, dict):
                text = clean_text(item.get("event") or item.get("topic") or item.get("text") or item.get("summary"), 180)
            else:
                text = clean_text(item, 180)
            if text and text not in rows:
                rows.append(text)
        return rows[:6]

    def _schedule_memory_plan_for_date(self, records: list[Any], selected_date: str) -> dict[str, Any]:
        if not selected_date:
            return {}
        best_items: list[dict[str, Any]] = []
        for record in records:
            if not self._is_personal_schedule_memory(record):
                continue
            metadata = getattr(record, "metadata", {}) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            payload = metadata.get("payload") if isinstance(metadata.get("payload"), dict) else {}
            date = clean_text(metadata.get("date"), 16) or clean_text(payload.get("date"), 16) or self._memory_date_key(record)
            if date != selected_date:
                continue
            content = str(getattr(record, "content", "") or "")
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            if "当日生活日程" not in content and not items and clean_text(getattr(record, "memory_type", ""), 80) not in {"schedule_fragment", "bot_schedule_plan"}:
                continue
            if not items:
                items = self._schedule_plan_items_from_content(content)
            else:
                items = [
                    self._compact_plan_item(item, index=index)
                    for index, item in enumerate(items)
                    if isinstance(item, dict)
                ]
            if len(items) > len(best_items):
                best_items = items
        if not best_items:
            return {}
        return {"date": selected_date, "source": "memory_companion", "items": best_items[:18]}

    def _schedule_plan_items_from_content(self, content: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line in str(content or "").splitlines():
            text = clean_text(line.strip("- "), 260)
            if not text:
                continue
            if "日程细化" in text or text.startswith("生活片段：") or text.startswith("可能主动念头："):
                continue
            match = re.match(r"^(\d{1,2}:\d{2})(?:\s*[-~—至]\s*(\d{1,2}:\d{2}))?\s*(.+)$", text)
            if not match:
                continue
            activity = clean_text(match.group(3), 220)
            mood = ""
            seed = ""
            mood_match = re.search(r"情绪[:：]([^可]+)", activity)
            if mood_match:
                mood = clean_text(mood_match.group(1), 80)
                activity = clean_text(activity[: mood_match.start()], 180)
            seed_match = re.search(r"可分享[:：](.+)$", text)
            if seed_match:
                seed = clean_text(seed_match.group(1), 220)
            rows.append(
                {
                    "index": len(rows),
                    "time": clean_text(match.group(1), 20),
                    "activity": activity,
                    "mood": mood,
                    "message_seed": seed,
                }
            )
        return rows

    def _schedule_detail_index_for_time(self, plan: dict[str, Any], start: str) -> Any:
        if not start or not isinstance(plan, dict):
            return ""
        items = plan.get("items", [])
        if not isinstance(items, list):
            return ""
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            time_text = clean_text(item.get("time"), 40)
            if time_text and (time_text.startswith(start) or start in time_text):
                return index
        return ""

    def _schedule_detail_summary_from_content(self, content: str) -> str:
        for line in content.splitlines()[1:]:
            text = clean_text(line, 180)
            if text and not text.startswith("生活片段：") and not text.startswith("可能主动念头："):
                return text
        return ""

    def _schedule_detail_lines_from_content(self, content: str, prefix: str) -> list[str]:
        for line in content.splitlines():
            text = clean_text(line, 500)
            if not text.startswith(prefix):
                continue
            payload = text[len(prefix):].strip()
            return [clean_text(part, 180) for part in payload.split("；") if clean_text(part, 180)][:5]
        return []

    def _detail_time_from_key(self, key: Any) -> str:
        parts = clean_text(key, 80).split(":")
        if len(parts) >= 4:
            return f"{parts[2]}:{parts[3]}"
        if len(parts) >= 3:
            return parts[2]
        return ""

    def _detail_index_from_key(self, key: Any) -> Any:
        parts = clean_text(key, 80).split(":")
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except Exception:
                return ""
        return ""

    def _compact_detail_events(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        rows = []
        for item in value[:5]:
            if isinstance(item, dict):
                window = clean_text(
                    item.get("window")
                    or item.get("time")
                    or item.get("range")
                    or item.get("when"),
                    40,
                )
                text = (
                    item.get("event")
                    or item.get("content")
                    or item.get("detail")
                    or item.get("description")
                    or item.get("text")
                    or item.get("topic")
                    or item.get("why")
                    or item.get("motive")
                    or item.get("reason")
                    or item.get("action")
                    or item.get("label")
                    or item.get("title")
                )
            else:
                window = ""
                text = item
            cleaned = clean_text(text, 180)
            if cleaned:
                rows.append(f"{window} {cleaned}".strip() if window else cleaned)
        return rows

    async def maintenance(self):
        result = await self.plugin.service.sleep_maintenance(reason="page_maintenance")
        return self._ok({"result": result})

    async def sleep_maintenance(self):
        if request.method == "POST":
            result = await self.plugin.service.sleep_maintenance(reason="page_sleep")
        else:
            result = self.plugin.service.sleep_status()
        return self._ok({"result": result})

    async def audit_preview(self):
        payload = await self._json()
        try:
            result = await self.plugin.service.preview_memory_audit(
                limit=max(0, min(100, self._int(payload.get("limit"), 0)))
            )
        except (ValueError, RuntimeError) as exc:
            return self._err(clean_text(exc, 300), 400)
        return self._ok({"result": result})

    async def audit_status(self):
        try:
            result = await self.plugin.service.memory_audit_status(
                clean_text(request.args.get("batch_id"), 80)
            )
        except ValueError as exc:
            return self._err(clean_text(exc, 300), 400)
        return self._ok({"result": result})

    async def audit_apply(self):
        payload = await self._json()
        try:
            result = await self.plugin.service.apply_memory_audit(
                clean_text(payload.get("batch_id"), 80),
                clean_text(payload.get("confirm"), 20),
            )
        except ValueError as exc:
            return self._err(clean_text(exc, 300), 400)
        return self._ok({"result": result})

    async def audit_rollback(self):
        payload = await self._json()
        try:
            result = await self.plugin.service.rollback_memory_audit(
                clean_text(payload.get("batch_id"), 80),
                clean_text(payload.get("confirm"), 20),
            )
        except ValueError as exc:
            return self._err(clean_text(exc, 300), 400)
        return self._ok({"result": result})

    async def repair_livingmemory_content(self):
        payload = await self._json()
        result = await self.plugin.service.migrator.repair_imported_content(
            configured_path=clean_text(payload.get("path"), 1000)
        )
        return self._ok({"result": result})

    async def clear_all(self):
        payload = await self._json()
        if clean_text(payload.get("confirm"), 20) != "清空":
            return self._err("confirmation mismatch", 400)
        result = await self.plugin.service.clear_all_memory_data()
        return self._ok({"result": result})

    async def clear_scope(self):
        payload = await self._json()
        target_type = clean_text(payload.get("target_type") or payload.get("type"), 40)
        group_id = clean_text(payload.get("group_id"), 120)
        user_id = clean_text(payload.get("user_id"), 120)
        preview = self._bool(payload.get("preview"), False)
        try:
            if preview:
                result = await self.plugin.service.store.preview_scoped_memory_clear(
                    target_type=target_type,
                    group_id=group_id,
                    user_id=user_id,
                )
            else:
                if clean_text(payload.get("confirm"), 20) != "清空":
                    return self._err("confirmation mismatch", 400)
                result = await self.plugin.service.clear_scoped_memory(
                    target_type=target_type,
                    group_id=group_id,
                    user_id=user_id,
                )
        except ValueError as exc:
            return self._err(str(exc), 400)
        return self._ok({"result": result})

    async def import_preview(self):
        configured = clean_text(request.args.get("path", ""), 1000)
        report = self.plugin.service.migrator.preview(configured)
        return self._ok({"report": report})

    async def import_run(self):
        payload = await self._json()
        result = await self.plugin.service.import_livingmemory(
            configured_path=clean_text(payload.get("path"), 1000)
        )
        return self._ok({"result": result})

    @staticmethod
    def _ok(data: dict[str, Any] | None = None):
        body = {"success": True}
        if data:
            body.update(data)
        return jsonify(body)

    @staticmethod
    def _err(message: str, status: int = 500):
        response = jsonify({"success": False, "error": message})
        response.status_code = status
        return response

    async def _json(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True)
        return payload if isinstance(payload, dict) else {}

    def _write_plugin_config(self, raw: dict[str, Any]) -> None:
        path = self._plugin_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import os
        import tempfile
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=path.stem,
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _plugin_config_path(self) -> Path:
        data_dir = Path(getattr(self.plugin.service, "data_dir", ""))
        root = data_dir.parent.parent if data_dir.parent.name == "plugin_data" else data_dir.parent
        return root / "config" / f"{PLUGIN_NAME}_config.json"

    def _load_config_schema(self) -> dict[str, Any]:
        path = Path(__file__).with_name("_conf_schema.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def _schema_config_values(self, schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for module, module_schema in schema.items():
            if not isinstance(module_schema, dict):
                continue
            items = module_schema.get("items")
            if not isinstance(items, dict):
                continue
            result[module] = {}
            for key, item_schema in items.items():
                if not isinstance(item_schema, dict):
                    continue
                dotted = f"{module}.{key}"
                default = item_schema.get("default")
                value = self._config_value_with_reverse_alias(dotted, default)
                result[module][key] = value
        return result

    def _config_value_with_reverse_alias(self, dotted: str, default: Any = None) -> Any:
        config = self.plugin.service.config
        marker = object()
        exact = getattr(config, "_get_exact", None)
        aliases = getattr(config, "ALIASES", {}) or {}
        if callable(exact):
            value = exact(dotted, marker)
            if value is not marker:
                return value
            for canonical, alias_list in aliases.items():
                if dotted in alias_list:
                    value = exact(canonical, marker)
                    if value is not marker:
                        return value
        return config.get(dotted, default)

    def _coerce_config_value(self, value: Any, item_schema: dict[str, Any]) -> Any:
        value_type = clean_text(item_schema.get("type"), 40)
        if value_type == "bool":
            return self._bool(value, bool(item_schema.get("default", False)))
        if value_type == "int":
            return self._int(value, int(item_schema.get("default", 0) or 0))
        if value_type == "float":
            return self._float(value, float(item_schema.get("default", 0.0) or 0.0))
        text = clean_text(value, 2000)
        options = item_schema.get("options")
        if isinstance(options, list) and options and text not in {str(option) for option in options}:
            default = item_schema.get("default", "")
            return clean_text(default, 2000)
        return text

    def _provider_options(self) -> list[dict[str, str]]:
        options = [{"id": "", "label": "不使用 LLM 压缩"}]
        context = getattr(self.plugin, "context", None)
        getter = getattr(context, "get_all_providers", None)
        if not callable(getter):
            return options
        try:
            providers = getter()
        except Exception:
            return options
        for provider in providers or []:
            try:
                meta = provider.meta()
            except Exception:
                meta = None
            provider_id = str(getattr(meta, "id", "") or "")
            if not provider_id:
                continue
            provider_type = str(getattr(meta, "type", "") or "").strip()
            model_name = str(getattr(meta, "model", "") or getattr(provider, "model_name", "") or "").strip()
            label = provider_id
            if provider_type:
                label = f"{provider_type} ({provider_id})"
            if model_name and model_name not in label:
                label = f"{label} - {model_name}"
            options.append({"id": provider_id, "label": label})
        return options

    async def _rerank_provider_options(self) -> list[dict[str, str]]:
        options = [{"id": "", "label": "自动探测 / 不指定"}]
        seen = {""}
        context = getattr(self.plugin, "context", None)
        manager = getattr(context, "provider_manager", None)
        for provider_config in self._configured_rerank_providers(manager):
            provider_id = clean_text(provider_config.get("id"), 160)
            if not provider_id or provider_id in seen:
                continue
            seen.add(provider_id)
            provider_type = clean_text(provider_config.get("type"), 80)
            model_name = clean_text(
                provider_config.get("rerank_model")
                or provider_config.get("model")
                or provider_config.get("model_name"),
                160,
            )
            enabled = provider_config.get("enable", True)
            label = provider_id
            if provider_type:
                label = f"{provider_type} ({provider_id})"
            if model_name and model_name not in label:
                label = f"{label} - {model_name}"
            if not enabled:
                label = f"{label} - 未启用"
            options.append({"id": provider_id, "label": label})
        providers: list[Any] = []
        for getter_name in ("get_all_rerank_providers", "get_all_providers"):
            getter = getattr(context, getter_name, None)
            if not callable(getter):
                continue
            try:
                result = getter()
                if inspect.isawaitable(result):
                    result = await result
            except Exception:
                continue
            for provider in result or []:
                if hasattr(provider, "rerank"):
                    providers.append(provider)
        for provider in getattr(manager, "rerank_provider_insts", []) or []:
            if hasattr(provider, "rerank"):
                providers.append(provider)
        for provider in getattr(manager, "inst_map", {}).values() if manager is not None else []:
            if hasattr(provider, "rerank"):
                providers.append(provider)
        for provider in providers:
            try:
                meta = provider.meta()
            except Exception:
                meta = None
            provider_id = clean_text(getattr(meta, "id", ""), 160)
            if not provider_id:
                provider_id = clean_text(getattr(provider, "id", "") or getattr(provider, "provider_id", ""), 160)
            if not provider_id or provider_id in seen:
                continue
            seen.add(provider_id)
            provider_type = clean_text(getattr(meta, "type", ""), 80)
            model_name = clean_text(getattr(meta, "model", "") or getattr(provider, "model", ""), 160)
            label = provider_id
            if provider_type:
                label = f"{provider_type} ({provider_id})"
            if model_name and model_name not in label:
                label = f"{label} - {model_name}"
            options.append({"id": provider_id, "label": label})
        return options

    async def _embedding_provider_options(self) -> list[dict[str, str]]:
        options = [{"id": "", "label": "自动探测 / 不指定"}]
        seen = {""}
        context = getattr(self.plugin, "context", None)
        manager = getattr(context, "provider_manager", None)
        for provider_config in self._configured_embedding_providers(manager):
            provider_id = clean_text(provider_config.get("id"), 160)
            if not provider_id or provider_id in seen:
                continue
            seen.add(provider_id)
            provider_type = clean_text(provider_config.get("type"), 80)
            model_name = clean_text(
                provider_config.get("embedding_model")
                or provider_config.get("model")
                or provider_config.get("model_name"),
                160,
            )
            enabled = provider_config.get("enable", True)
            label = provider_id
            if provider_type:
                label = f"{provider_type} ({provider_id})"
            if model_name and model_name not in label:
                label = f"{label} - {model_name}"
            if not enabled:
                label = f"{label} - 未启用"
            options.append({"id": provider_id, "label": label})

        providers: list[Any] = []
        for getter_name in ("get_all_embedding_providers", "get_all_providers"):
            getter = getattr(context, getter_name, None)
            if not callable(getter):
                continue
            try:
                result = getter()
                if inspect.isawaitable(result):
                    result = await result
            except Exception:
                continue
            for provider in result or []:
                if self._is_embedding_provider(provider):
                    providers.append(provider)
        for provider in getattr(manager, "embedding_provider_insts", []) or []:
            if self._is_embedding_provider(provider):
                providers.append(provider)
        for provider in getattr(manager, "inst_map", {}).values() if manager is not None else []:
            if self._is_embedding_provider(provider):
                providers.append(provider)

        for provider in providers:
            provider_id, label = self._provider_option_identity(provider)
            if not provider_id or provider_id in seen:
                continue
            seen.add(provider_id)
            options.append({"id": provider_id, "label": label or provider_id})
        return options

    def _configured_rerank_providers(self, manager: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(provider_config: Any) -> None:
            if not isinstance(provider_config, dict):
                return
            provider_id = clean_text(provider_config.get("id"), 160)
            if not provider_id or provider_id in seen:
                return
            provider_type = clean_text(provider_config.get("type"), 80).lower()
            provider_task = clean_text(provider_config.get("provider_type"), 80).lower()
            if provider_task != "rerank" and not provider_type.endswith("_rerank"):
                return
            seen.add(provider_id)
            rows.append(dict(provider_config))

        for provider_config in getattr(manager, "providers_config", []) or []:
            merged = None
            getter = getattr(manager, "get_merged_provider_config", None)
            if callable(getter):
                try:
                    merged = getter(provider_config)
                except Exception:
                    merged = None
            add(merged or provider_config)

        config_path = self._astrbot_cmd_config_path()
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            for provider_config in data.get("provider", []) if isinstance(data, dict) else []:
                add(provider_config)
        return rows

    def _configured_embedding_providers(self, manager: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(provider_config: Any) -> None:
            if not isinstance(provider_config, dict):
                return
            provider_id = clean_text(provider_config.get("id"), 160)
            if not provider_id or provider_id in seen:
                return
            provider_type = clean_text(provider_config.get("type"), 80).lower()
            provider_task = clean_text(provider_config.get("provider_type"), 80).lower()
            if (
                provider_task != "embedding"
                and "embedding" not in provider_type
                and "embed" not in provider_type
            ):
                return
            seen.add(provider_id)
            rows.append(dict(provider_config))

        for provider_config in getattr(manager, "providers_config", []) or []:
            merged = None
            getter = getattr(manager, "get_merged_provider_config", None)
            if callable(getter):
                try:
                    merged = getter(provider_config)
                except Exception:
                    merged = None
            add(merged or provider_config)

        config_path = self._astrbot_cmd_config_path()
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            for provider_config in data.get("provider", []) if isinstance(data, dict) else []:
                add(provider_config)
        return rows

    @staticmethod
    def _is_embedding_provider(provider: Any) -> bool:
        return any(
            callable(getattr(provider, name, None))
            for name in ("get_embedding", "get_embeddings", "get_embeddings_batch")
        )

    @staticmethod
    def _provider_option_identity(provider: Any) -> tuple[str, str]:
        try:
            meta = provider.meta()
        except Exception:
            meta = None
        provider_id = clean_text(getattr(meta, "id", ""), 160)
        provider_type = clean_text(getattr(meta, "type", ""), 80)
        model_name = clean_text(getattr(meta, "model", "") or getattr(provider, "model", ""), 160)
        provider_config = getattr(provider, "provider_config", None)
        if not provider_id and isinstance(provider_config, dict):
            provider_id = clean_text(provider_config.get("id"), 160)
            provider_type = provider_type or clean_text(provider_config.get("type"), 80)
            model_name = model_name or clean_text(
                provider_config.get("embedding_model")
                or provider_config.get("rerank_model")
                or provider_config.get("model")
                or provider_config.get("model_name"),
                160,
            )
        if not provider_id and provider_config is not None:
            provider_id = clean_text(getattr(provider_config, "id", ""), 160)
        if not provider_id:
            provider_id = clean_text(getattr(provider, "id", "") or getattr(provider, "provider_id", ""), 160)
        label = provider_id
        if provider_type:
            label = f"{provider_type} ({provider_id})"
        if model_name and model_name not in label:
            label = f"{label} - {model_name}"
        return provider_id, label

    def _astrbot_cmd_config_path(self) -> Path:
        data_dir = Path(getattr(self.plugin.service, "data_dir", ""))
        root = data_dir.parent.parent if data_dir.parent.name == "plugin_data" else data_dir.parent
        return root / "cmd_config.json"

    def _query_int(self, key: str, default: int) -> int:
        return self._int(request.args.get(key), default)

    @staticmethod
    def _optional_choice(payload: dict[str, Any], key: str, allowed: set[str] | frozenset[str]) -> Any:
        if key not in payload:
            return None
        value = clean_text(payload.get(key), 40).lower()
        return value if value in allowed else False

    @staticmethod
    def _optional_iso_timestamp(payload: dict[str, Any], key: str) -> str | None:
        if key not in payload:
            return None
        value = clean_text(payload.get(key), 80)
        if not value:
            return ""
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{key} must be an ISO-8601 timestamp") from exc
        return value

    @staticmethod
    def _optional_unit_score(payload: dict[str, Any], key: str) -> float | None:
        if key not in payload:
            return None
        try:
            value = float(payload.get(key))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number between 0 and 1") from exc
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{key} must be a number between 0 and 1")
        return value

    @staticmethod
    def _iso_timestamp_number(value: str) -> float:
        parsed = datetime.fromisoformat(clean_text(value, 80).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return parsed.timestamp()

    @staticmethod
    def _acl_window_error(scope: str, window_id: str) -> str:
        if scope not in {"private", "group"}:
            return "ACL scope must be private or group"
        if not window_id:
            return "ACL window id is required"
        return ""

    @staticmethod
    def _acl_effect(value: Any) -> str:
        return "deny" if clean_text(value, 20).lower() in {"deny", "block", "blacklist"} else "allow"

    @staticmethod
    def _acl_mode(value: Any) -> str:
        text = clean_text(value, 20).lower()
        if not text:
            return ""
        return "blacklist" if text in {"blacklist", "deny", "block"} else "whitelist"

    @staticmethod
    def _int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _float(value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "off", "no", "否", "关"}
        return bool(value)
