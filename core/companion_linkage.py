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
            )
        except Exception as exc:  # 注册失败不阻断插件，V2 会回落到 v1 探测
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

    async def _read(self, request: Any) -> dict[str, Any]:
        """返回该用户最近一段私聊记忆，供 V2 注入「外部记忆参考」。"""

        user_id, _platform, _bot_id = _request_identity(request)
        if not user_id:
            return {"items": []}
        store = getattr(self._service, "store", None)
        reader = getattr(store, "read_user_memory_summary_records", None)
        if not callable(reader):
            return {"items": []}
        payload = request if isinstance(request, Mapping) else {}
        limit = _int(payload.get("limit"), 8, 1, 20)
        max_chars = _int(payload.get("max_chars"), 2400, 0, 20000)
        try:
            raw = await reader(user_id, session_id="", limit=limit)
        except Exception as exc:
            logger.debug("[MemoryCompanion] 外部记忆 read 失败: %s", exc)
            return {"items": []}
        records = raw.get("records") if isinstance(raw, Mapping) else None
        if not isinstance(records, (list, tuple)):
            return {"items": []}
        items: list[dict[str, str]] = []
        used = 0
        for record in records:
            content = _clean(getattr(record, "content", ""), 1200)
            if not content:
                continue
            size = len(content)
            if max_chars and used + size > max_chars:
                continue
            used += size
            items.append(
                {
                    "id": _clean(getattr(record, "id", ""), 120),
                    "content": content,
                    "occurred_at": _clean(
                        getattr(record, "occurred_at", "") or getattr(record, "created_at", ""),
                        40,
                    ),
                    "source": "memory_companion",
                }
            )
        return {"items": items}

    async def _summary(self, request: Any) -> dict[str, Any]:
        """返回按类别聚合的记忆条数，供 V2 记忆面板展示。"""

        user_id, _platform, _bot_id = _request_identity(request)
        if not user_id:
            return {"state": "unavailable", "ok": False, "reason": "missing_user_id"}
        reader = getattr(self._service, "read_user_memory_summary", None)
        if not callable(reader):
            return {"state": "unavailable", "ok": False, "reason": "service_unavailable"}
        try:
            raw = await reader(user_id, session_id="", limit=8)
        except Exception as exc:
            logger.debug("[MemoryCompanion] 外部记忆 summary 失败: %s", exc)
            return {"state": "unavailable", "ok": False, "reason": "summary_read_failed"}
        if not isinstance(raw, Mapping):
            return {"state": "unavailable", "ok": False, "reason": "invalid_summary_response"}
        raw_counts = raw.get("counts") if isinstance(raw.get("counts"), Mapping) else {}
        counts = {
            key: _int(raw_counts.get(key), 0, 0, 1000000000)
            for key in (*SUMMARY_CATEGORIES, "total")
        }
        return {"state": "ready", "ok": True, "counts": counts}


__all__ = ["CompanionMemoryLinkage", "PROVIDER_ID", "PROVIDER_API_VERSION", "REGISTRY_ATTRIBUTE"]
