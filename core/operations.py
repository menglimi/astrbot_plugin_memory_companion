from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigView
from .models import EntityRef, MemoryRecord, clean_text, json_loads


PORTABLE_FORMAT = "astrbot-memory-jsonl"
PORTABLE_VERSION = 1
MAX_PORTABLE_BYTES = 64 * 1024 * 1024


PRESETS: dict[str, dict[str, Any]] = {
    "light": {
        "retrieval.mode": "basic",
        "retrieval.embedding_enabled": False,
        "retrieval_advanced.embedding_backfill_enabled": False,
        "knowledge_graph.enabled": False,
        "knowledge_graph.retrieval_expansion_enabled": False,
        "memory_injection.top_k": 4,
        "memory_injection.max_chars": 1400,
        "context_orchestration.query_mode": "current_message",
        "memory_summary.min_events": 12,
        "memory_summary.trigger_event_count": 24,
    },
    "standard": {
        "retrieval.mode": "auto",
        "retrieval.embedding_enabled": False,
        "retrieval_advanced.embedding_backfill_enabled": True,
        "knowledge_graph.enabled": True,
        "knowledge_graph.retrieval_expansion_enabled": True,
        "memory_injection.top_k": 6,
        "memory_injection.max_chars": 1800,
        "context_orchestration.query_mode": "current_message",
        "memory_summary.min_events": 8,
        "memory_summary.trigger_event_count": 12,
        "maintenance.memory_decay_enabled": True,
    },
    "companion": {
        "retrieval.mode": "auto",
        "retrieval.embedding_enabled": False,
        "retrieval_advanced.embedding_backfill_enabled": True,
        "knowledge_graph.enabled": True,
        "knowledge_graph.retrieval_expansion_enabled": True,
        "memory_injection.top_k": 8,
        "memory_injection.max_chars": 2400,
        "context_orchestration.query_mode": "current_message",
        "context_orchestration_advanced.self_timeline_limit": 2,
        "context_orchestration_advanced.user_profile_limit": 2,
        "context_orchestration_advanced.current_window_limit": 3,
        "context_orchestration_advanced.conversation_summary_limit": 2,
        "context_orchestration_advanced.stable_memory_limit": 4,
        "memory_summary.min_events": 8,
        "memory_summary.trigger_event_count": 12,
        "private_companion_bridge.enabled": True,
        "private_companion_bridge.schedule_fast_context_enabled": True,
        "private_companion_bridge.outfit_fast_context_enabled": True,
        "private_companion_bridge.dedupe_prompt_context": True,
        "private_companion_bridge.prefer_memory_companion_memory": True,
        "private_companion_bridge.suppress_self_timeline_when_companion_seen": True,
        "private_companion_bridge.suppress_user_context_when_companion_seen": True,
        "maintenance.memory_decay_enabled": True,
    },
}


PRESET_LABELS = {
    "light": "轻量",
    "standard": "标准",
    "companion": "陪伴",
    "custom": "自定义",
}


CONFLICT_PLUGINS: dict[str, dict[str, str]] = {
    "astrbot_plugin_private_companion": {
        "level": "coordinated",
        "label": "PrivateCompanion",
        "reason": "已提供专用桥接和重复上下文抑制。",
    },
    "astrbot_plugin_livingmemory": {
        "level": "high",
        "label": "LivingMemory",
        "reason": "可能重复捕获、检索并注入长期记忆。",
    },
    "astrbot_plugin_memorix": {
        "level": "high",
        "label": "Memorix",
        "reason": "可能重复维护图谱、向量记忆和提示词注入。",
    },
    "astrbot_plugin_iris_memory": {
        "level": "high",
        "label": "Iris Memory",
        "reason": "可能重复生成画像、图谱和长期记忆注入。",
    },
    "astrbot_plugin_iris_chat_memory": {
        "level": "high",
        "label": "Iris 聊天记忆",
        "reason": "可能重复生成群聊画像和陪伴记忆。",
    },
    "astrbot_plugin_simple_memory": {
        "level": "high",
        "label": "LLM 简单记忆",
        "reason": "可能重复总结并注入长、中、短期记忆。",
    },
    "astrbot_plugin_simple_long_memory": {
        "level": "high",
        "label": "简单长期记忆",
        "reason": "可能重复写入和召回 AstrBot 知识库记忆。",
    },
    "astrbot_plugin_mnemosyne": {
        "level": "high",
        "label": "Mnemosyne",
        "reason": "可能重复执行向量召回和长期记忆注入。",
    },
    "astrbot_plugin_memos_integrator": {
        "level": "high",
        "label": "MemOS 集成",
        "reason": "可能重复捕获和注入持久化对话记忆。",
    },
    "astrbot_plugin_openviking_memory": {
        "level": "high",
        "label": "OpenViking Memory",
        "reason": "可能重复自动捕获、语义召回和跨空间注入。",
    },
    "astrbot_plugin_memory": {
        "level": "high",
        "label": "astrbot_plugin_memory",
        "reason": "可能重复维护画像、历史、备忘录和持久记忆。",
    },
    "astrbot_plugin_engram": {
        "level": "high",
        "label": "Engram",
        "reason": "可能重复运行长期记忆捕获和注入链。",
    },
    "astrbot_plugin_livelystate": {
        "level": "medium",
        "label": "角色状态记忆",
        "reason": "角色状态可能与 Bot 自我时间线或当前状态提示重复。",
    },
    "emotionai-pro": {
        "level": "medium",
        "label": "EmotionAI-Pro",
        "reason": "情绪和关系阶段可能被两个插件同时注入。",
    },
    "astrbot_plugin_angel_memory": {
        "level": "medium",
        "label": "天使之魂",
        "reason": "人格演化与自主记忆可能和陪伴记忆重复。",
    },
    "astrbot_plugin_self_evolution": {
        "level": "medium",
        "label": "自我进化",
        "reason": "人格演化和记忆沉淀可能重复进入提示词。",
    },
    "astrbot_plugin_xnbot": {
        "level": "medium",
        "label": "XNBot",
        "reason": "自带聊天流、记忆和状态系统，可能接管同一回复链。",
    },
}


def apply_preset(raw: dict[str, Any], name: str) -> dict[str, Any]:
    preset = clean_text(name, 40).lower()
    values = PRESETS.get(preset)
    if values is None:
        raise ValueError("preset must be light, standard or companion")
    for dotted, value in values.items():
        _set_dotted(raw, dotted, value)
    return {
        "preset": preset,
        "label": PRESET_LABELS[preset],
        "changed": dict(values),
        "preserved": [
            "memory_summary.provider_id",
            "memory_summary.fallback_provider_id",
            "retrieval.embedding_provider_id",
            "retrieval.rerank_provider_id",
        ],
    }


def detect_preset(config: ConfigView) -> str:
    for name, values in PRESETS.items():
        if all(config.get(dotted, object()) == expected for dotted, expected in values.items()):
            return name
    return "custom"


def persist_runtime_config(raw: dict[str, Any], data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    root = data_dir.parent.parent if data_dir.parent.name == "plugin_data" else data_dir.parent
    path = root / "config" / "astrbot_plugin_memory_companion_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".tmp", prefix=path.stem, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return path


def scan_plugin_conflicts(plugin_root: Path) -> list[dict[str, Any]]:
    plugins_dir = Path(plugin_root).resolve().parent
    if not plugins_dir.exists():
        return []
    found: list[dict[str, Any]] = []
    for path in plugins_dir.iterdir():
        if not path.is_dir():
            continue
        key = path.name.lower()
        definition = CONFLICT_PLUGINS.get(key)
        if definition is None:
            continue
        found.append(
            {
                "plugin_dir": path.name,
                "label": definition["label"],
                "level": definition["level"],
                "reason": definition["reason"],
                "enabled": None,
                "note": "检测到插件目录，未确认 AstrBot 运行时是否已启用。",
            }
        )
    rank = {"high": 0, "medium": 1, "coordinated": 2}
    found.sort(key=lambda item: (rank.get(str(item.get("level")), 9), str(item.get("label"))))
    return found


async def build_operational_report(service: Any) -> dict[str, Any]:
    stats = await service.store.stats()
    token = service.token_usage_summary()
    totals = token.get("totals") if isinstance(token.get("totals"), dict) else {}
    cache = dict(getattr(service, "_retrieval_result_cache_stats", {}) or {})
    hits = _int(cache.get("hits"))
    misses = _int(cache.get("misses"))
    requests = hits + misses
    calls = _int(totals.get("calls"))
    elapsed_ms = _int(totals.get("elapsed_ms"))
    conflicts = scan_plugin_conflicts(service.plugin_root)
    high_conflicts = [item for item in conflicts if item.get("level") == "high"]
    mode = clean_text(service.config.get("retrieval.mode", "auto"), 40) or "auto"
    embedding_enabled = service.config.bool("retrieval.embedding_enabled", False)
    warnings: list[str] = []
    if high_conflicts:
        warnings.append(f"检测到 {len(high_conflicts)} 个高风险记忆插件目录，请确认未重复启用注入。")
    if mode == "rerank" and not clean_text(service.config.get("retrieval.rerank_provider_id", ""), 160):
        warnings.append("当前强制 rerank 但未指定 Provider；失败时会回退 basic。")
    if embedding_enabled and not clean_text(service.config.get("retrieval.embedding_provider_id", ""), 160):
        warnings.append("Embedding 已启用但未指定 Provider，将依赖自动发现。")
    if calls <= 0:
        warnings.append("还没有模型调用统计，Token 与耗时结论暂无样本。")
    return {
        "preset": detect_preset(service.config),
        "preset_label": PRESET_LABELS[detect_preset(service.config)],
        "retrieval": {
            "mode": mode,
            "embedding_enabled": embedding_enabled,
            "zero_external_retrieval_calls": mode == "basic" and not embedding_enabled,
            "last_path": dict(getattr(service, "_last_retrieval_path_info", {}) or {}),
        },
        "cache": {
            **cache,
            "requests": requests,
            "hit_rate": round(hits / requests, 4) if requests else None,
            "entries": len(getattr(service, "_retrieval_result_cache", {}) or {}),
        },
        "model_usage": {
            "calls": calls,
            "success": _int(totals.get("success")),
            "errors": _int(totals.get("errors")),
            "total_tokens": _int(totals.get("total_tokens")),
            "estimated_tokens": _int(totals.get("estimated_tokens")),
            "average_elapsed_ms": round(elapsed_ms / calls, 2) if calls else None,
            "by_task": token.get("by_task") if isinstance(token.get("by_task"), dict) else {},
        },
        "memory": stats,
        "conflicts": conflicts,
        "warnings": warnings,
        "benchmark_note": "不同插件尚未在同一模型、数据集和硬件下比较。",
    }


class PortableMemoryArchive:
    def __init__(self, store: Any, data_dir: Path):
        self.store = store
        self.data_dir = Path(data_dir)
        self.export_dir = self.data_dir / "exports"

    async def export(self) -> dict[str, Any]:
        memories = await self.store.list_memories(limit=1_000_000)
        identities = await self.store.list_identities(limit=1_000_000)
        relationships = await self.store.list_relationships(limit=1_000_000)
        timeline = await self.store.recent_timeline(limit=1_000_000)
        acl_rules = await self.store.list_acl_rules()
        acl_policies = await self.store.list_acl_policies()
        counts = {
            "memory": len(memories),
            "identity": len(identities),
            "relationship": len(relationships),
            "timeline": len(timeline),
            "acl_rule": len(acl_rules),
            "acl_policy": len(acl_policies),
        }
        now = datetime.now(timezone.utc)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        path = self.export_dir / f"memory-companion-{now.strftime('%Y%m%d-%H%M%S')}.jsonl"
        header = {
            "record_type": "header",
            "format": PORTABLE_FORMAT,
            "version": PORTABLE_VERSION,
            "plugin": "astrbot_plugin_memory_companion",
            "exported_at": now.isoformat(timespec="seconds"),
            "encoding": "utf-8",
            "counts": counts,
            "excluded": ["memory_embeddings", "injection_logs", "provider_credentials"],
        }
        fd, temp_name = tempfile.mkstemp(suffix=".tmp", prefix=path.stem, dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                self._write_line(handle, header)
                for memory in memories:
                    self._write_line(handle, {"record_type": "memory", "data": self._memory_payload(memory)})
                for kind, rows in (
                    ("identity", identities),
                    ("relationship", relationships),
                    ("timeline", timeline),
                    ("acl_rule", acl_rules),
                    ("acl_policy", acl_policies),
                ):
                    for row in rows:
                        self._write_line(handle, {"record_type": kind, "data": self._normalized_row(row)})
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return {"path": str(path), "counts": counts, "format": PORTABLE_FORMAT, "version": PORTABLE_VERSION}

    def preview(self, path: str) -> dict[str, Any]:
        header, records = self._read(path)
        counts = Counter(str(item.get("record_type") or "unknown") for item in records)
        return {
            "path": str(Path(path).expanduser().resolve()),
            "format": header.get("format"),
            "version": header.get("version"),
            "exported_at": header.get("exported_at"),
            "counts": dict(counts),
            "total_records": len(records),
            "valid": True,
        }

    async def import_data(self, path: str) -> dict[str, Any]:
        header, records = self._read(path)
        preview_counts = Counter(str(item.get("record_type") or "unknown") for item in records)
        backup = self.store.backup(".before_portable_import")
        batch_id = await self.store.add_import_batch(
            source_plugin=clean_text(header.get("plugin"), 120) or "portable_jsonl",
            source_path=str(Path(path).expanduser().resolve()),
            mode=f"portable_v{PORTABLE_VERSION}",
            stats={"preview_counts": dict(preview_counts)},
        )
        imported: Counter[str] = Counter()
        skipped: Counter[str] = Counter()
        errors: list[str] = []
        for index, item in enumerate(records, start=2):
            kind = clean_text(item.get("record_type"), 40)
            data = item.get("data")
            if not isinstance(data, dict):
                skipped[kind or "unknown"] += 1
                continue
            try:
                if kind == "memory":
                    record = self._memory_record(data, batch_id)
                    if not record.content:
                        skipped[kind] += 1
                        continue
                    await self.store.insert_memory(record)
                elif kind == "identity":
                    await self.store.upsert_identity(
                        platform=clean_text(data.get("platform"), 80),
                        entity=EntityRef(
                            kind=clean_text(data.get("entity_kind"), 40) or "user",
                            id=clean_text(data.get("entity_id"), 120),
                            name=clean_text(data.get("display_name"), 80),
                            role=clean_text(data.get("role"), 80) or "unknown",
                        ),
                        aliases=self._list(data.get("aliases")),
                        profile=self._dict(data.get("profile")),
                        confidence=self._float(data.get("confidence"), 0.6),
                    )
                elif kind == "relationship":
                    await self.store.upsert_relationship(
                        subject=EntityRef(
                            kind=clean_text(data.get("subject_kind"), 40),
                            id=clean_text(data.get("subject_id"), 120),
                            name=clean_text(data.get("subject_name"), 80),
                        ),
                        object=EntityRef(
                            kind=clean_text(data.get("object_kind"), 40),
                            id=clean_text(data.get("object_id"), 120),
                            name=clean_text(data.get("object_name"), 80),
                        ),
                        relation_type=clean_text(data.get("relation_type"), 80),
                        scope=clean_text(data.get("scope"), 40),
                        session_id=clean_text(data.get("session_id"), 200),
                        group_id=clean_text(data.get("group_id"), 120),
                        visibility=clean_text(data.get("visibility"), 40) or "internal",
                        evidence=clean_text(data.get("evidence"), 1000),
                        confidence=self._float(data.get("confidence"), 0.6),
                        review_status=clean_text(data.get("review_status"), 40) or "auto",
                        source_memory_id=clean_text(data.get("source_memory_id"), 120),
                        metadata=self._dict(data.get("metadata")),
                    )
                elif kind == "timeline":
                    metadata = self._dict(data.get("metadata"))
                    metadata.setdefault("message_id", clean_text(data.get("message_id") or data.get("id"), 120))
                    metadata["portable_import_batch_id"] = batch_id
                    timeline_id = await self.store.add_timeline_event(
                        event_type=clean_text(data.get("event_type"), 80),
                        session_id=clean_text(data.get("session_id"), 200),
                        scope=clean_text(data.get("scope"), 40),
                        subject_id=clean_text(data.get("subject_id"), 120),
                        object_id=clean_text(data.get("object_id"), 120),
                        content=clean_text(data.get("content"), 4000),
                        metadata=metadata,
                        occurred_at=clean_text(data.get("occurred_at"), 80),
                    )
                    if clean_text(data.get("summarized_at"), 80):
                        await self.store.mark_timeline_summarized([timeline_id])
                elif kind == "acl_rule":
                    await self.store.upsert_acl_rule(
                        owner_scope=clean_text(data.get("owner_scope"), 40),
                        owner_id=clean_text(data.get("owner_id"), 160),
                        reader_scope=clean_text(data.get("reader_scope"), 40),
                        reader_id=clean_text(data.get("reader_id"), 160),
                        effect=clean_text(data.get("effect"), 20) or "allow",
                        enabled=bool(data.get("enabled", True)),
                        note=clean_text(data.get("note"), 300),
                    )
                elif kind == "acl_policy":
                    await self.store.upsert_acl_policy(
                        window_scope=clean_text(data.get("window_scope"), 40),
                        window_id=clean_text(data.get("window_id"), 160),
                        read_mode=clean_text(data.get("read_mode"), 20),
                        share_mode=clean_text(data.get("share_mode"), 20),
                    )
                else:
                    skipped[kind or "unknown"] += 1
                    continue
                imported[kind] += 1
            except Exception as exc:
                skipped[kind or "unknown"] += 1
                if len(errors) < 20:
                    errors.append(f"line {index}: {type(exc).__name__}: {clean_text(exc, 180)}")
        return {
            "path": str(Path(path).expanduser().resolve()),
            "backup": str(backup),
            "batch_id": batch_id,
            "imported": dict(imported),
            "skipped": dict(skipped),
            "errors": errors,
        }

    @staticmethod
    def _write_line(handle: Any, payload: dict[str, Any]) -> None:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    @staticmethod
    def _normalized_row(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for key in ("metadata", "aliases", "profile"):
            if key in result:
                fallback: Any = [] if key == "aliases" else {}
                result[key] = json_loads(result[key], fallback) if isinstance(result[key], str) else result[key]
        return result

    @staticmethod
    def _memory_payload(memory: MemoryRecord) -> dict[str, Any]:
        return {
            "id": memory.id,
            "memory_type": memory.memory_type,
            "subject": {"kind": memory.subject.kind, "id": memory.subject.id, "name": memory.subject.name, "role": memory.subject.role},
            "object": {"kind": memory.object.kind, "id": memory.object.id, "name": memory.object.name, "role": memory.object.role},
            "scope": memory.scope,
            "session_id": memory.session_id,
            "platform": memory.platform,
            "message_id": memory.message_id,
            "group_id": memory.group_id,
            "visibility": memory.visibility,
            "sayability": memory.sayability,
            "reality_level": memory.reality_level,
            "lifecycle": memory.lifecycle,
            "content": memory.content,
            "evidence": memory.evidence,
            "confidence": memory.confidence,
            "importance": memory.importance,
            "review_status": memory.review_status,
            "tags": memory.tags,
            "metadata": memory.metadata,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
            "occurred_at": memory.occurred_at,
            "last_accessed_at": memory.last_accessed_at,
            "access_count": memory.access_count,
            "source_plugin": memory.source_plugin,
            "content_fingerprint": memory.content_fingerprint,
            "merged_count": memory.merged_count,
            "supersedes_id": memory.supersedes_id,
        }

    @classmethod
    def _memory_record(cls, data: dict[str, Any], batch_id: str) -> MemoryRecord:
        subject = cls._dict(data.get("subject"))
        object_ = cls._dict(data.get("object"))
        return MemoryRecord(
            id=clean_text(data.get("id"), 120),
            memory_type=clean_text(data.get("memory_type"), 80) or "imported_memory",
            subject=EntityRef(
                kind=clean_text(subject.get("kind"), 40) or "user",
                id=clean_text(subject.get("id"), 120),
                name=clean_text(subject.get("name"), 80),
                role=clean_text(subject.get("role"), 80) or "unknown",
            ),
            object=EntityRef(
                kind=clean_text(object_.get("kind"), 40) or "session",
                id=clean_text(object_.get("id"), 120),
                name=clean_text(object_.get("name"), 80),
                role=clean_text(object_.get("role"), 80) or "unknown",
            ),
            scope=clean_text(data.get("scope"), 40),
            session_id=clean_text(data.get("session_id"), 200),
            platform=clean_text(data.get("platform"), 80),
            message_id=clean_text(data.get("message_id"), 120),
            group_id=clean_text(data.get("group_id"), 120),
            visibility=clean_text(data.get("visibility"), 40) or "internal",
            sayability=clean_text(data.get("sayability"), 40) or "indirect",
            reality_level=clean_text(data.get("reality_level"), 60) or "imported_summary",
            lifecycle=clean_text(data.get("lifecycle"), 60) or "stable_memory",
            content=clean_text(data.get("content"), 4000),
            evidence=clean_text(data.get("evidence"), 4000),
            confidence=cls._float(data.get("confidence"), 0.5),
            importance=cls._float(data.get("importance"), 0.3),
            review_status=clean_text(data.get("review_status"), 40) or "auto",
            tags=cls._list(data.get("tags")),
            metadata=cls._dict(data.get("metadata")),
            created_at=clean_text(data.get("created_at"), 80),
            updated_at=clean_text(data.get("updated_at"), 80),
            occurred_at=clean_text(data.get("occurred_at"), 80),
            last_accessed_at=clean_text(data.get("last_accessed_at"), 80),
            access_count=_int(data.get("access_count")),
            source_plugin=clean_text(data.get("source_plugin"), 120) or "portable_import",
            import_batch_id=batch_id,
            content_fingerprint=clean_text(data.get("content_fingerprint"), 80),
            merged_count=max(1, _int(data.get("merged_count"), 1)),
            supersedes_id=clean_text(data.get("supersedes_id"), 120),
        )

    @staticmethod
    def _list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        parsed = json_loads(value, []) if isinstance(value, str) else []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        parsed = json_loads(value, {}) if isinstance(value, str) else {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _float(value: Any, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _read(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise ValueError("portable archive not found")
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_PORTABLE_BYTES:
            raise ValueError("portable archive must be between 1 byte and 64 MiB")
        records: list[dict[str, Any]] = []
        header: dict[str, Any] = {}
        with resolved.open("r", encoding="utf-8-sig") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON on line {line_number}: {exc.msg}") from exc
                if not isinstance(item, dict):
                    raise ValueError(f"line {line_number} must be an object")
                if not header:
                    header = item
                    if item.get("record_type") != "header" or item.get("format") != PORTABLE_FORMAT:
                        raise ValueError("unsupported portable archive header")
                    if int(item.get("version") or 0) != PORTABLE_VERSION:
                        raise ValueError("unsupported portable archive version")
                    continue
                records.append(item)
        if not header:
            raise ValueError("portable archive header is missing")
        return header, records


def _set_dotted(raw: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    target = raw
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child
    target[parts[-1]] = value


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
