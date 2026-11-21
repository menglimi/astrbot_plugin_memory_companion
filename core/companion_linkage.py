"""private_companion v2 联动：向宿主注册外部记忆 provider。

private_companion 7.x（内部领域标识 ``private_companion.v2``）在宿主 Context 上挂
``_private_companion_memory_providers`` 注册表，第三方记忆插件通过
``companion.external-memory.v1`` 协议声明 read / write / summary 能力：

- 私聊回复前，V2 会调用 ``read`` 召回本插件记忆，注入「【外部记忆参考】」段；
- 记忆面板的 summary 统计优先走 ``summary`` 回调。

这里只声明 ``handles_model_memory=False``：V2 继续自己管模型记忆，本插件作为
「外部记忆源」参与。让 V2 完全让位需要完整的 owner 契约句柄（见
``companion_v2/adapters/astrbot/memory_owner.py`` 的 ``RENDER_EXTERNAL`` 分支），
不属于本模块职责。v1 的 ``get_memory_companion_bridge()`` 兼容探测保持不变，
两条路互不冲突。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

REGISTRY_ATTRIBUTE = "_private_companion_memory_providers"
PROVIDER_API_VERSION = "companion.external-memory.v1"
PROVIDER_ID = "memory_companion"
DISPLAY_NAME = "我会牢牢记住你"
SUMMARY_CATEGORIES = ("profile", "preference", "relationship", "private_conversation", "other")


def _clean(value: Any, limit: int = 200) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, number))


def _request_context(request: Any) -> Mapping[str, Any]:
    if not isinstance(request, Mapping):
        return {}
    context = request.get("context")
    return context if isinstance(context, Mapping) else {}


def _request_identity(request: Any) -> tuple[str, str, str]:
    """从 V2 的 ``memory_context_document`` 里取出私聊身份。

    身份只认序列化文档里的原生标识，绝不从 query 字符串推断。
    """

    context = _request_context(request)
    scope = context.get("scope")
    scope = scope if isinstance(scope, Mapping) else {}
    user_id = _clean(
        scope.get("native_scope_id") or scope.get("target_id") or scope.get("scope_id"),
        120,
    )
    if not user_id:
        user = context.get("user")
        if isinstance(user, Mapping):
            user_id = _clean(user.get("id"), 120)
    platform = _clean(scope.get("platform"), 40)
    bot_id = _clean(scope.get("bot_id"), 120)
    return user_id, platform, bot_id


class CompanionMemoryLinkage:
    """向 private_companion 注册 read / summary provider，并在卸载时注销。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self._registration_id = ""
        self._registry: Any = None
        self._task: asyncio.Task | None = None
        self._last_reason = ""

    # -- 状态 ---------------------------------------------------------------

    @property
    def registered(self) -> bool:
        return bool(self._registration_id)

    @property
    def _service(self) -> Any:
        return getattr(self.plugin, "service", None)

    def status(self) -> dict[str, Any]:
        return {
            "registered": bool(self._registration_id),
            "provider_id": PROVIDER_ID if self._registration_id else "",
            "registry_present": self._registry is not None,
            "last_reason": getattr(self, "_last_reason", ""),
        }

    # -- 注册 / 注销 --------------------------------------------------------

    def register(self) -> bool:
        """尝试注册。注册表不存在（private_companion 未加载）时返回 False。"""

        if self._registration_id:
            return True
        context = getattr(self.plugin, "context", None)
        if context is None:
            self._last_reason = "no_context"
            return False
        registry = getattr(context, REGISTRY_ATTRIBUTE, None)
        register = getattr(registry, "register", None)
        if not callable(register):
            self._last_reason = "no_registry"
            return False
        try:
            registration_id = register(
                PROVIDER_ID,
                plugin=self.plugin,
                read=self._read,
                summary=self._summary,
                display_name=DISPLAY_NAME,
                priority=10,
                handles_model_memory=False,
                timeout_seconds=5.0,
                linked_memory_read=True,
            )
        except Exception as exc:  # 旧宿主不支持范围授权时不注册，禁止降级为按裸用户 ID 召回
            self._last_reason = "register_exc: %s" % (exc,)
            logger.info("[MemoryCompanion] private_companion provider 注册失败: %s", exc)
            return False
        if not isinstance(registration_id, str) or not registration_id:
            self._last_reason = "invalid_registration_id"
            return False
        self._last_reason = ""
        self._registration_id = registration_id
        self._registry = registry
        logger.info(
            "[MemoryCompanion] 已向 private_companion 注册外部记忆 provider id=%s",
            PROVIDER_ID,
        )
        return True

    def unregister(self) -> None:
        registry, registration_id = self._registry, self._registration_id
        self._registry = None
        self._registration_id = ""
        if registry is None or not registration_id:
            return
        try:
            unregister = getattr(registry, "unregister", None)
            if callable(unregister):
                unregister(registration_id)
        except Exception as exc:
            logger.debug("[MemoryCompanion] private_companion provider 注销失败: %s", exc)

    def start(self) -> None:
        """先同步注册一次，失败再挂后台重试（private_companion 可能晚加载）。"""

        if self._task is not None and not self._task.done():
            return
        try:
            first_ok = self.register()
        except Exception as exc:  # 注册失败不阻断插件
            first_ok = False
            logger.info("[MemoryCompanion] companion linkage 首次注册异常: %s", exc)
        if first_ok:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            logger.info("[MemoryCompanion] companion linkage 无事件循环，跳过重试: %s", exc)
            return
        self._task = loop.create_task(self._register_with_retry())
        logger.info("[MemoryCompanion] companion linkage 已排队后台重试注册")

    async def _register_with_retry(self) -> None:
        logger.info("[MemoryCompanion] companion linkage 重试任务启动")
        for attempt in range(30):
            if self.register():
                return
            if attempt in (0, 29):
                logger.info(
                    "[MemoryCompanion] private_companion provider 注册重试 %s/30 未成功: %s",
                    attempt + 1,
                    getattr(self, "_last_reason", "") or "unknown",
                )
            await asyncio.sleep(10.0)

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self.unregister()

    # -- provider 回调 ------------------------------------------------------

    async def _authorized_records(self, request, *, limit):
        """Resolve opaque host authority; never trust member IDs supplied in JSON."""
        if not isinstance(request, Mapping):
            raise ValueError("memory_read_authorization_required")
        registry = self._registry
        if registry is None or registry is not getattr(self.plugin.context, REGISTRY_ATTRIBUTE, None):
            raise ValueError("memory_registry_changed")
        authorize = getattr(registry, "authorize_memory_read", None)
        if not callable(authorize):
            raise ValueError("scoped_memory_authorization_required")
        scope = authorize(request)
        config = getattr(self._service, "config", None)
        if config is None or not config.bool("private_companion_bridge.enabled", True):
            raise ValueError("bridge_disabled")
        reader = getattr(getattr(self._service, "store", None), "read_authorized_linked_memories", None)
        if not callable(reader):
            raise ValueError("scoped_memory_reader_unavailable")
        raw = await reader(scope, limit=limit)
        revision = await self._service.store.memory_revision()
        source_revision = await self._service.store.source_revision()
        if (str(raw.get("memory_revision")) != revision
                or raw.get("source_revision") != source_revision):
            raise ValueError("memory_read_snapshot_changed")
        if not config.bool("private_companion_bridge.enabled", True):
            raise ValueError("bridge_disabled")
        if authorize(request) != scope:
            raise ValueError("memory_read_authorization_changed")
        return raw

    async def _read(self, request: Any) -> dict[str, Any]:
        payload = request if isinstance(request, Mapping) else {}
        limit = _int(payload.get("limit"), 8, 1, 20)
        max_chars = _int(payload.get("max_chars"), 2400, 0, 20000)
        try:
            raw = await self._authorized_records(request, limit=limit)
        except Exception as exc:
            logger.debug("[MemoryCompanion] scoped recall unavailable: %s", type(exc).__name__)
            return {"items": [], "reason": "memory_read_authorization_unavailable"}
        records = raw.get("records") if isinstance(raw, Mapping) else None
        if not isinstance(records, (list, tuple)):
            return {"items": []}
        items, used = [], 0
        for record in records:
            content = _clean(getattr(record, "content", ""), 1200)
            if not content or used + len(content) > max_chars:
                continue
            used += len(content)
            provenance = raw.get("provenance", {}).get(record.id, {})
            items.append({"id": _clean(record.id, 120), "content": content,
                "occurred_at": _clean(record.occurred_at or record.created_at, 40),
                "source": "memory_companion", "source_session_id": record.session_id,
                "source_user_id": provenance.get("user_id") or (
                    record.subject.id if record.subject.kind == "user" else record.object.id),
                "source_bot_id": provenance.get("owner_bot_id", record.owner_bot_id),
                "source_original_bot_id": record.owner_bot_id})
        return {"items": items}

    async def _summary(self, request: Any) -> dict[str, Any]:
        try:
            raw = await self._authorized_records(request, limit=0)
            category = self._service._user_memory_category
            counts = {key: 0 for key in (*SUMMARY_CATEGORIES, "total")}
            for memory_type, count in raw["type_counts"].items():
                counts[category(memory_type)] += count
                counts["total"] += count
            return {"state": "ready", "ok": True, "counts": counts}
        except Exception as exc:
            logger.debug("[MemoryCompanion] scoped summary unavailable: %s", type(exc).__name__)
            return {"state": "unavailable", "ok": False, "reason": "memory_read_authorization_unavailable"}


__all__ = ["CompanionMemoryLinkage", "PROVIDER_ID", "PROVIDER_API_VERSION", "REGISTRY_ATTRIBUTE"]
