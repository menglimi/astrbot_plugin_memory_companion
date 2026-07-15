from __future__ import annotations

import asyncio
import base64
import json
import hashlib
import inspect
import logging
import mimetypes
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from quart import jsonify, request, send_file

from .core.bridge import serialize_memory
from .core.identity import normalize_session_context_fields
from .core.models import SessionContext, clean_text

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


class PluginPageApi:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def register_routes(self) -> None:
        register = self.plugin.context.register_web_api
        routes = [
            ("/stats", self.stats, ["GET"], "MemoryCompanion Page stats"),
            ("/buckets", self.buckets, ["GET"], "MemoryCompanion Page buckets"),
            ("/memories", self.memories, ["GET"], "MemoryCompanion Page memories"),
            ("/memory", self.memory_detail, ["GET"], "MemoryCompanion Page memory detail"),
            ("/memory/update", self.memory_update, ["POST"], "MemoryCompanion Page memory update"),
            ("/memory/delete", self.memory_delete, ["POST"], "MemoryCompanion Page memory delete"),
            ("/memory/visibility", self.memory_visibility, ["POST"], "MemoryCompanion Page memory visibility"),
            ("/memory/lifecycle", self.memory_lifecycle, ["POST"], "MemoryCompanion Page memory lifecycle"),
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
            ("/operations/preset", self.operations_preset, ["GET", "POST"], "MemoryCompanion operations preset"),
            ("/data/export", self.data_export, ["POST"], "MemoryCompanion portable data export"),
            ("/data/import/preview", self.data_import_preview, ["GET"], "MemoryCompanion portable data preview"),
            ("/data/import/run", self.data_import_run, ["POST"], "MemoryCompanion portable data import"),
            ("/conversation-import/upload", self.conversation_import_upload, ["POST"], "MemoryCompanion historical chat upload"),
            ("/conversation-import/start", self.conversation_import_start, ["POST"], "MemoryCompanion historical chat start"),
            ("/conversation-import/status", self.conversation_import_status, ["GET"], "MemoryCompanion historical chat status"),
            ("/conversation-import/pause", self.conversation_import_pause, ["POST"], "MemoryCompanion historical chat pause"),
            ("/conversation-import/resume", self.conversation_import_resume, ["POST"], "MemoryCompanion historical chat resume"),
            ("/conversation-import/rollback", self.conversation_import_rollback, ["POST"], "MemoryCompanion historical chat rollback"),
            ("/companion/personal-memory", self.companion_personal_memory, ["GET"], "MemoryCompanion Page companion personal memory"),
            ("/companion/personal-photo", self.companion_personal_photo, ["GET"], "MemoryCompanion Page companion personal photo"),
            ("/companion/personal-photo-data", self.companion_personal_photo_data, ["GET"], "MemoryCompanion Page companion personal photo data"),
            ("/maintenance", self.maintenance, ["POST"], "MemoryCompanion Page maintenance"),
            ("/maintenance/sleep", self.sleep_maintenance, ["GET", "POST"], "MemoryCompanion Page sleep maintenance"),
            ("/maintenance/repair_livingmemory_content", self.repair_livingmemory_content, ["POST"], "MemoryCompanion Page repair LivingMemory content"),
            ("/maintenance/clear_all", self.clear_all, ["POST"], "MemoryCompanion Page clear all memory data"),
            ("/maintenance/clear_scope", self.clear_scope, ["POST"], "MemoryCompanion Page clear scoped memory data"),
            ("/import/livingmemory/preview", self.import_preview, ["GET"], "MemoryCompanion Page import preview"),
            ("/import/livingmemory/run", self.import_run, ["POST"], "MemoryCompanion Page import run"),
            ("/persona-state", self.persona_state, ["GET"], "MemoryCompanion Page persona state"),
            ("/acl/matrix", self.acl_matrix, ["GET"], "MemoryCompanion Page ACL matrix"),
        ]
        for prefix in PAGE_API_PREFIXES:
            for route, handler, methods, desc in routes:
                register(f"{prefix}{route}", handler, methods, desc)

    async def stats(self):
        stats = await self.plugin.service.store.stats()
        stats.pop("pending_review", None)
        return self._ok({"stats": stats})

    async def operations_diagnostics(self):
        try:
            return self._ok({"diagnostics": await self.plugin.service.operational_report()})
        except Exception as exc:
            return self._err(f"运维诊断失败: {exc}", 500)

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
        try:
            result = await self.plugin.service.historical_chat_import_status(batch_id)
            return self._ok({"result": result})
        except ValueError as exc:
            return self._err(str(exc), 404)
        except Exception as exc:
            return self._err(f"读取历史对话导入状态失败: {exc}", 500)

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
        """Return persona state: relationship phases, emotional events, address evolution, cross-window state."""
        try:
            service = self.plugin.service
            phases: list[dict[str, Any]] = []
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
                    phases.append({
                        "session_key": key,
                        "session_label": " / ".join(part for part in identity_parts if part) or key,
                        "phase": state.get("phase", "acquaintance"),
                        "momentum": round(state.get("momentum", 0.0), 3),
                        "touch_count": state.get("touch_count", 0),
                        "last_transition_at": state.get("last_transition_at", ""),
                        "updated_at": state.get("updated_at", ""),
                        "current_address_phase": state.get("current_address_phase", ""),
                        "address_log": (state.get("address_log") or [])[-5:],
                    })
            phases.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
            pending_emotional_events: list[dict[str, Any]] = []
            event_queue = getattr(service, "_emotional_event_queue", None)
            if isinstance(event_queue, dict):
                for session_id, queue in event_queue.items():
                    if not isinstance(queue, list):
                        continue
                    for event in queue[-3:]:
                        if not isinstance(event, dict):
                            continue
                        pending_emotional_events.append({
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
            phases_list = getattr(service, "_PHASES", ["acquaintance", "familiar", "close", "intimate", "deeply_bonded"])
            thresholds = getattr(service, "_PHASE_THRESHOLDS", [0.0, 0.20, 0.45, 0.65, 0.85])
            bot_suggestions = getattr(service, "_BOT_ADDRESS_SUGGESTIONS", {})
            return self._ok({
                "phases": phases[:20],
                "pending_emotional_events": pending_emotional_events[:15],
                "time_of_day": time_of_day,
                "phase_definitions": {
                    "phases": phases_list,
                    "thresholds": thresholds,
                },
                "cross_window_emotional_state": cross_window_state,
                "address_phase_labels": {
                    "formal": "正式",
                    "casual": "随意",
                    "intimate": "亲密",
                    "playful": "玩笑",
                },
                "time_of_day_labels": {
                    "late_night": "深夜",
                    "dawn": "凌晨",
                    "early_morning": "清晨",
                    "afternoon": "下午",
                    "evening": "傍晚",
                    "night": "夜间",
                },
                "bot_address_suggestions": bot_suggestions,
                "phase_labels": {
                    "acquaintance": "初识",
                    "familiar": "熟悉",
                    "close": "亲近",
                    "intimate": "亲密",
                    "deeply_bonded": "深伴",
                },
            })
        except Exception as exc:
            return self._err(f"拟人维度数据读取失败: {exc}", 500)

    async def acl_matrix(self):
        """Return all windows, ACL rules and policies in one shot for topology visualization."""
        try:
            store = self.plugin.service.store
            buckets = await store.list_memory_buckets(limit=200)
            windows: list[dict[str, Any]] = []
            for b in buckets:
                scope = clean_text(b.get("scope"), 40)
                tid = clean_text(b.get("target_id"), 160)
                if scope in ("group", "private") and tid:
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
                ],
                "policies": [
                    {
                        "window_scope": clean_text(p.get("window_scope"), 40),
                        "window_id": clean_text(p.get("window_id"), 160),
                        "read_mode": p.get("read_mode") or ("blacklist" if clean_text(p.get("window_scope"), 40) == "group" else "whitelist"),
                        "share_mode": p.get("share_mode") or ("blacklist" if clean_text(p.get("window_scope"), 40) == "group" else "whitelist"),
                    }
                    for p in policies
                ],
            })
        except Exception as exc:
            return self._err(f"权限矩阵读取失败: {exc}", 500)

    async def buckets(self):
        buckets = await self.plugin.service.store.list_memory_buckets(limit=self._query_int("limit", 160))
        for bucket in buckets:
            bucket.pop("pending_count", None)
        return self._ok({"buckets": buckets})

    async def memories(self):
        limit = self._query_int("limit", 50)
        query = clean_text(request.args.get("q", ""), 200)
        scope = clean_text(request.args.get("scope", ""), 40)
        visibility = clean_text(request.args.get("visibility", ""), 40)
        lifecycle = clean_text(request.args.get("lifecycle", ""), 40)
        records = await self.plugin.service.store.list_memories(
            limit=limit,
            include_pending=False,
            query=query,
            memory_type=clean_text(request.args.get("memory_type", ""), 80),
            scope=scope,
            visibility=visibility,
            review_status="",
            lifecycle=lifecycle,
            session_id=clean_text(request.args.get("session_id", ""), 200),
            group_id=clean_text(request.args.get("group_id", ""), 120),
            entity_id=clean_text(request.args.get("entity_id", ""), 120),
        )
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
        ok = await self.plugin.service.store.update_memory_payload(
            memory_id,
            memory_type=payload.get("memory_type"),
            content=payload.get("content"),
            evidence=payload.get("evidence"),
            importance=payload.get("importance"),
            confidence=payload.get("confidence"),
            visibility=payload.get("visibility"),
            lifecycle=payload.get("lifecycle"),
        )
        if not ok:
            return self._err("memory not found", 404)
        return self._ok({"updated": ok})

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
        policy = await self.plugin.service.store.upsert_acl_policy(
            window_scope=window_scope,
            window_id=window_id,
            read_mode=self._acl_mode(payload.get("read_mode")),
            share_mode=self._acl_mode(payload.get("share_mode")),
        )
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
        normalized = normalize_session_context_fields(
            session_id=clean_text(payload.get("session_id"), 200),
            scope=clean_text(payload.get("scope"), 40) or "unknown",
            platform=clean_text(payload.get("platform"), 80),
            user_id=clean_text(payload.get("user_id"), 120),
            group_id=clean_text(payload.get("group_id"), 120),
        )
        ctx = SessionContext(
            session_id=normalized["session_id"],
            scope=normalized["scope"],
            platform=normalized["platform"],
            user_id=normalized["user_id"],
            user_name=clean_text(payload.get("user_name"), 80),
            group_id=normalized["group_id"],
            group_name=clean_text(payload.get("group_name"), 80),
            message_text=query,
        )
        results, blocked = await self.plugin.service.search_with_diagnostics(
            query,
            ctx,
            self._int(payload.get("top_k"), 8),
            admin_read_all=False,
        )
        return self._ok(
            {
                "results": [
                    serialize_memory(item.memory, item.score, item.reason)
                    for item in results
                ],
                "blocked": blocked[:30],
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
            return self._ok({"items": []})

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
            return self._ok({"items": []})

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
            return self._ok({"items": []})

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
            return self._ok({"items": []})

    async def thread_status(self):
        payload = await self._json()
        ok = await self.plugin.service.store.update_cross_window_thread_status(
            clean_text(payload.get("id"), 120),
            clean_text(payload.get("status"), 40),
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
            return self._ok({"items": []})

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
                    "min_events": config.int("memory_summary.min_events", 8),
                    "trigger_event_count": config.int("memory_summary.trigger_event_count", 12),
                    "trigger_interval_minutes": config.int("memory_summary.trigger_interval_minutes", 60),
                    "max_events_per_summary": config.int("memory_summary.max_events_per_summary", 40),
                    "max_retries": config.int("memory_summary.max_retries", 3),
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
        status = self._private_companion_status()
        if not status["available"]:
            return self._ok(status)

        limit = self._query_int("limit", 80)
        selected_date = clean_text(request.args.get("date", ""), 16)
        query = clean_text(request.args.get("q", ""), 200)
        payload = dict(status)
        records = await self.plugin.service.store.list_memories(
            limit=max(limit * 12, 1200),
            include_pending=False,
            query=query,
            visibility="bot_self",
        )
        dates = self._private_companion_dates(status.get("plugin"), records)
        if not selected_date:
            selected_date = dates[0] if dates else ""
        if selected_date and selected_date not in dates:
            dates.insert(0, selected_date)
        if selected_date:
            date_records = await self.plugin.service.store.list_memories(
                limit=240,
                include_pending=False,
                query=selected_date,
                visibility="bot_self",
            )
            records = self._merge_records_by_id(records, date_records)

        payload["selected_date"] = selected_date
        payload["dates"] = dates
        payload["snapshot"] = self._private_companion_snapshot(status.get("plugin"), selected_date, records)
        payload.pop("plugin", None)
        filtered = [record for record in records if self._memory_date_key(record) == selected_date] if selected_date else records
        payload["actions"] = [serialize_memory(record) for record in filtered if self._is_personal_action(record)][:limit]
        return self._ok(payload)

    async def companion_personal_photo(self):
        resolved = await self._resolve_companion_personal_photo_path_from_request()
        if isinstance(resolved, dict):
            return self._err(str(resolved.get("error") or "photo_not_found"), int(resolved.get("status") or 404))
        return await send_file(resolved)

    async def companion_personal_photo_data(self):
        resolved = await self._resolve_companion_personal_photo_path_from_request()
        if isinstance(resolved, dict):
            return self._err(str(resolved.get("error") or "photo_not_found"), int(resolved.get("status") or 404))
        try:
            mime = mimetypes.guess_type(str(resolved))[0] or "image/jpeg"
            raw = await asyncio.to_thread(resolved.read_bytes)
            return self._ok(
                {
                    "mime": mime,
                    "size": len(raw),
                    "data_url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
                }
            )
        except Exception:
            return self._err("photo_read_failed", 500)

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
            return {
                "available": True,
                "plugin_name": "astrbot_plugin_private_companion",
                "daily_plan_enabled": bool(getattr(plugin, "enable_daily_plan", False)) if plugin else False,
                "detail_enabled": bool(getattr(plugin, "enable_detail_enhancement", False)) if plugin else False,
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
            path = clean_text(metadata.get("image_path") or metadata.get("path"), 500)
            if not path:
                continue
            date = clean_text(metadata.get("date"), 16) or self._memory_date_key(record)
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
                    "backend": clean_text(metadata.get("backend"), 80),
                    "prompt": clean_text(metadata.get("prompt_preview") or metadata.get("prompt"), 360),
                    "note": clean_text(metadata.get("note") or getattr(record, "content", ""), 220),
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
        return (
            getattr(record, "visibility", "") == "bot_self"
            and (
                getattr(record, "memory_type", "") == "schedule_fragment"
                or "schedule" in tag_set
                or "daily_plan" in tag_set
                or "daily_detail" in tag_set
                or bool(clean_text(metadata.get("start"), 20) or clean_text(metadata.get("end"), 20))
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
        if not clean_text(metadata.get("image_path") or metadata.get("path"), 500):
            return False
        tags = {clean_text(tag, 80) for tag in (getattr(record, "tags", []) or []) if clean_text(tag, 80)}
        return (
            getattr(record, "memory_type", "") in {"image_action", "persona_life"}
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
            date = clean_text(metadata.get("date"), 16) or self._memory_date_key(record)
            if date != selected_date:
                continue
            start = clean_text(metadata.get("start"), 20)
            end = clean_text(metadata.get("end"), 20)
            summary = clean_text(metadata.get("summary"), 180)
            content = str(getattr(record, "content", "") or "")[:1600]
            if not summary:
                summary = self._schedule_detail_summary_from_content(content)
            today_events = self._schedule_detail_lines_from_content(content, "生活片段：")
            proactive_events = self._schedule_detail_lines_from_content(content, "可能主动念头：")
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
            date = clean_text(metadata.get("date"), 16) or self._memory_date_key(record)
            if date != selected_date:
                continue
            content = str(getattr(record, "content", "") or "")
            if "当日生活日程" not in content and clean_text(getattr(record, "memory_type", ""), 80) != "schedule_fragment":
                continue
            items = self._schedule_plan_items_from_content(content)
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
