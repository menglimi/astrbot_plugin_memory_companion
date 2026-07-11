from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.event.filter import PermissionType, permission_type
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register

from .core.bridge import MemoryCompanionBridge
from .core.commands import MemoryCompanionCommandHandler
from .core.models import json_dumps
from .core.service import MemoryCompanionService

PLUGIN_NAME = "astrbot_plugin_memory_companion"
PLUGIN_VERSION = "1.5.0"

_ACTIVE_BRIDGE: MemoryCompanionBridge | None = None


def get_memory_companion_bridge() -> MemoryCompanionBridge | None:
    return _ACTIVE_BRIDGE


def get_active_bridge() -> MemoryCompanionBridge | None:
    return get_memory_companion_bridge()


def _prepare_data_dir() -> Path:
    data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@register(
    "MemoryCompanion",
    "menglimi",
    "我会牢牢记住你：结构化长期记忆、共同自我时间线和关系隔离。",
    PLUGIN_VERSION,
    "https://github.com/menglimi/astrbot_plugin_memory_companion",
)
class MemoryCompanionPlugin(Star):
    def __init__(self, context: Context, config: dict[str, Any]):
        super().__init__(context)
        self.context = context
        data_dir = _prepare_data_dir()
        self.service = MemoryCompanionService(
            context=context,
            config=config or {},
            plugin_root=Path(__file__).resolve().parent,
            data_dir=data_dir,
        )
        self.memory_companion = MemoryCompanionBridge(self.service)
        self.commands = MemoryCompanionCommandHandler(self.service, PLUGIN_VERSION)
        self.page_api = None

        global _ACTIVE_BRIDGE
        _ACTIVE_BRIDGE = self.memory_companion if self.service.config.bool("private_companion_bridge.enabled", True) else None
        self._register_page_api_if_available()

        logger.info("[MemoryCompanion] 我会牢牢记住你 已启动，数据目录=%s", self.service.data_dir)

    def _register_page_api_if_available(self) -> None:
        if not hasattr(self.context, "register_web_api"):
            return
        try:
            from .page_api import PluginPageApi

            self.page_api = PluginPageApi(self)
            self.page_api.register_routes()
        except Exception as exc:
            self.page_api = None
            logger.warning("[MemoryCompanion] 拓展页 API 注册失败: %s", exc, exc_info=True)

    @filter.on_llm_request(priority=-20)
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        await self.service.handle_llm_request(event, req)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=1000)
    async def on_group_message(self, event: AstrMessageEvent):
        await self.service.handle_group_message(event)

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        await self.service.handle_llm_response(event, resp)

    @filter.llm_tool(name="memory_companion_recall")
    async def memory_companion_recall_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """从 MemoryCompanion 中主动回忆当前会话可见的长期记忆。

        Args:
            query(string): 要回忆的关键词或自然语言问题。
            top_k(number): 最多返回几条，默认 5，最多 10。
        """
        if not self.service.config.bool("memory_tools.enable_recall_tool", True):
            return json_dumps({"ok": False, "error": "recall tool disabled"})
        result = await self.service.tool_recall(
            event,
            str(kwargs.get("query") or ""),
            int(kwargs.get("top_k") or 5),
        )
        return json_dumps(result)

    @filter.llm_tool(name="memory_companion_remember")
    async def memory_companion_remember_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """主动写入一条需要长期保存的记忆。

        只在用户明确要求记住、或对陪伴关系有长期价值时使用。写入前应确认这不是玩笑、注入话术或临时情绪。

        Args:
            content(string): 要保存的记忆内容。
            note_type(string): memory/preference/relationship/promise 等简短类别。
        """
        if not self.service.config.bool("memory_tools.enable_remember_tool", True):
            return json_dumps({"ok": False, "error": "remember tool disabled"})
        result = await self.service.tool_remember(
            event,
            str(kwargs.get("content") or ""),
            note_type=str(kwargs.get("note_type") or "memory"),
        )
        return json_dumps(result)

    @filter.llm_tool(name="memory_companion_note_create")
    async def memory_companion_note_create_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """创建一条 Bot 自己可见的陪伴笔记，用于日程、状态、创作草稿、关系线索的自我整理。

        Args:
            title(string): 笔记标题或分类。
            content(string): 笔记正文。
        """
        if not self.service.config.bool("memory_tools.enable_note_tools", True):
            return json_dumps({"ok": False, "error": "note tools disabled"})
        result = await self.service.tool_note_create(
            event,
            str(kwargs.get("title") or ""),
            str(kwargs.get("content") or ""),
        )
        return json_dumps(result)

    @filter.llm_tool(name="memory_companion_note_read")
    async def memory_companion_note_read_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """读取 Bot 自己可见的陪伴笔记。

        Args:
            query(string): 可选关键词。
            limit(number): 最多读取几条，默认 5，最多 20。
        """
        if not self.service.config.bool("memory_tools.enable_note_tools", True):
            return json_dumps({"ok": False, "error": "note tools disabled"})
        result = await self.service.tool_note_read(
            event,
            str(kwargs.get("query") or ""),
            int(kwargs.get("limit") or 5),
        )
        return json_dumps(result)

    @filter.command_group("mcomp")
    def mcomp(self):
        """MemoryCompanion memory management command group."""
        pass

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("status", priority=10)
    async def cmd_mcomp_status(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.status())

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("search", priority=10)
    async def cmd_mcomp_search(
        self, event: AstrMessageEvent, query: str = "", k: int = 6
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.search(event, query, k))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("explain", priority=10)
    async def cmd_mcomp_explain(
        self, event: AstrMessageEvent, query: str = "", k: int = 6
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.explain(event, query, k))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("recent", priority=10)
    async def cmd_mcomp_recent(
        self, event: AstrMessageEvent, limit: int = 10
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.recent(limit))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("add", priority=10)
    async def cmd_mcomp_add(
        self, event: AstrMessageEvent, content: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.add(event, content))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("summarize", priority=10)
    async def cmd_mcomp_summarize(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.summarize(event))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("delete", priority=10)
    async def cmd_mcomp_delete(
        self, event: AstrMessageEvent, memory_id: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.delete(memory_id))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("clear_scope", priority=10)
    async def cmd_mcomp_clear_scope(
        self,
        event: AstrMessageEvent,
        target_type: str = "",
        first_id: str = "",
        second_id: str = "",
        confirm: str = "",
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.clear_scope(target_type, first_id, second_id, confirm))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("visibility", priority=10)
    async def cmd_mcomp_visibility(
        self, event: AstrMessageEvent, memory_id: str = "", visibility: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.visibility(memory_id, visibility))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("promote", priority=10)
    async def cmd_mcomp_promote(
        self, event: AstrMessageEvent, memory_id: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.promote(memory_id))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("archive", priority=10)
    async def cmd_mcomp_archive(
        self, event: AstrMessageEvent, memory_id: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.archive(memory_id))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("timeline", priority=10)
    async def cmd_mcomp_timeline(
        self, event: AstrMessageEvent, limit: int = 10
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.timeline(limit))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("relations", priority=10)
    async def cmd_mcomp_relations(
        self, event: AstrMessageEvent, limit: int = 20, entity_id: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.relations(limit, entity_id))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("threads", priority=10)
    async def cmd_mcomp_threads(
        self, event: AstrMessageEvent, action: str = "list", thread_id: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.threads(action, thread_id))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("logs", priority=10)
    async def cmd_mcomp_logs(
        self, event: AstrMessageEvent, limit: int = 5
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.logs(limit))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("maintenance", priority=10)
    async def cmd_mcomp_maintenance(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.maintenance())

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("diagnostics", priority=10)
    async def cmd_mcomp_diagnostics(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.diagnostics())

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("preset", priority=10)
    async def cmd_mcomp_preset(
        self, event: AstrMessageEvent, action: str = "status", name: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(self.commands.preset(action, name))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("data", priority=10)
    async def cmd_mcomp_data(
        self, event: AstrMessageEvent, action: str = "help", path: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.portable_data(action, path))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("sleep", priority=10)
    async def cmd_mcomp_sleep(
        self, event: AstrMessageEvent, action: str = "status"
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.sleep(action))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("import_livingmemory", priority=10)
    async def cmd_mcomp_import_livingmemory(
        self, event: AstrMessageEvent, mode: str = "preview", path: str = ""
    ) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(await self.commands.import_livingmemory(mode, path))

    @permission_type(PermissionType.ADMIN)
    @mcomp.command("help", priority=10)
    async def cmd_mcomp_help(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        yield event.plain_result(self.commands.help())

    async def terminate(self):
        global _ACTIVE_BRIDGE
        if _ACTIVE_BRIDGE is self.memory_companion:
            _ACTIVE_BRIDGE = None
        self.service.close()
        logger.info("[MemoryCompanion] 我会牢牢记住你 已停止")
