from __future__ import annotations

from typing import Any

from .models import clean_text
from .service import MemoryCompanionService


class MemoryCompanionCommandHandler:
    def __init__(self, service: MemoryCompanionService, version: str):
        self.service = service
        self.version = version

    async def status(self) -> str:
        stats = await self.service.store.stats()
        sleep = self.service.sleep_status()
        by_scope = ", ".join(f"{key or 'unknown'}={value}" for key, value in stats["by_scope"].items()) or "none"
        return (
            "我会牢牢记住你：运行中\n"
            f"版本：{self.version}\n"
            f"记忆：{stats['total_memories']} 条，稳定 {stats['stable_memories']} 条\n"
            f"身份：{stats['identities']} 个；关系边：{stats['relationships']} 条；自我时间线：{stats['timeline_events']} 条\n"
            f"跨窗口线程：{stats['open_threads']} 条；注入日志：{stats['injection_logs']} 条\n"
            f"睡眠维护：{sleep.get('ran_at') or sleep.get('message') or '-'}\n"
            f"范围：{by_scope}\n"
            f"数据库：{stats['db_path']}"
        )

    async def search(self, event: Any, query: str = "", k: int = 6) -> str:
        if not query.strip():
            return "用法：/mcomp search 关键词"
        results = await self.service.search_for_event(event, query, k)
        if not results:
            return "没有检索到当前会话可见的记忆。"
        lines = [f"检索结果：{len(results)} 条"]
        for item in results:
            memory = item.memory
            lines.append(
                f"- {memory.id}｜{memory.memory_type}｜{memory.visibility}｜{memory.reality_level}｜{memory.content[:180]}｜score={item.score:.2f}｜{item.reason}"
            )
        return "\n".join(lines)

    async def explain(self, event: Any, query: str = "", k: int = 6) -> str:
        if not query.strip():
            return "用法：/mcomp explain 关键词"
        intent, selected, blocked, slot_map = await self.service.explain_context_for_event(event, query, k)
        lines = [
            f"召回解释：选中 {len(selected)} 条，过滤 {len(blocked)} 条",
            f"检索来源：{intent.source}｜检索词：{clean_text(intent.query, 180)}",
        ]
        intent_hint = intent.format_for_injection(320)
        if intent_hint:
            lines.append("【检索意图】")
            lines.append(intent_hint)
        if selected:
            lines.append("【选中】")
            for slot, items in slot_map.items():
                lines.append(f"[{slot}]")
                for item in items:
                    lines.append(
                        f"- {item.memory.id}｜{item.memory.visibility}｜score={item.score:.2f}｜{item.reason}｜{item.memory.content[:120]}"
                    )
        if blocked:
            lines.append("【过滤示例】")
            for item in blocked[:10]:
                lines.append(f"- {item.get('id')}｜{item.get('reason')}｜{item.get('content')}")
        return "\n".join(lines)

    async def recent(self, limit: int = 10) -> str:
        memories = await self.service.store.recent_memories(limit=limit, include_pending=False)
        if not memories:
            return "还没有记忆。"
        lines = [f"最近记忆：{len(memories)} 条"]
        for memory in memories:
            lines.append(
                f"- {memory.id}｜{memory.scope}｜{memory.visibility}｜{memory.content[:180]}"
            )
        return "\n".join(lines)

    async def add(self, event: Any, content: str = "") -> str:
        content = clean_text(content, 3000)
        if not content:
            return "用法：/mcomp add 要记住的内容"
        memory_id = await self.service.add_manual_memory(event, content)
        return f"记住了：{memory_id}"

    async def summarize(self, event: Any) -> str:
        ctx = await self.service.identity.resolve_event_context(event)
        memory_id = await self.service.maybe_summarize_session(ctx, force=True)
        if not memory_id:
            return "当前会话没有可总结的未处理时间线，或暂时没有可用模型。"
        return f"已生成阶段性长期记忆：{memory_id}"

    async def delete(self, memory_id: str = "") -> str:
        if not memory_id:
            return "用法：/mcomp delete <memory_id>"
        ok = await self.service.store.delete_memory(memory_id)
        return "已删除。" if ok else "没有找到这条记忆。"

    async def visibility(self, memory_id: str = "", visibility: str = "") -> str:
        if not memory_id or not visibility:
            return "用法：/mcomp visibility <memory_id> private_pair|group_public|bot_self|shareable|internal"
        ok = await self.service.store.update_memory_visibility(memory_id, visibility)
        return f"已改为 {visibility}。" if ok else "没有找到这条记忆。"

    async def promote(self, memory_id: str = "") -> str:
        if not memory_id:
            return "用法：/mcomp promote <memory_id>"
        ok_review = await self.service.store.update_review_status(memory_id, "auto")
        ok_lifecycle = await self.service.store.update_memory_lifecycle(memory_id, "stable_memory")
        return "已提升为稳定记忆。" if ok_review or ok_lifecycle else "没有找到这条记忆。"

    async def archive(self, memory_id: str = "") -> str:
        if not memory_id:
            return "用法：/mcomp archive <memory_id>"
        ok = await self.service.store.update_memory_lifecycle(memory_id, "archived")
        return "已归档。" if ok else "没有找到这条记忆。"

    async def timeline(self, limit: int = 10) -> str:
        rows = await self.service.store.recent_timeline(limit)
        if not rows:
            return "还没有自我时间线事件。"
        lines = [f"最近自我时间线：{len(rows)} 条"]
        for row in rows:
            lines.append(
                f"- {row.get('occurred_at')}｜{row.get('event_type')}｜{row.get('scope')}｜{clean_text(row.get('content'), 160)}"
            )
        return "\n".join(lines)

    async def relations(self, limit: int = 20, entity_id: str = "") -> str:
        rows = await self.service.store.list_relationships(limit=limit, entity_id=entity_id)
        if not rows:
            return "还没有关系边。"
        lines = [f"关系边：{len(rows)} 条"]
        for row in rows:
            lines.append(
                f"- {row.get('subject_name') or row.get('subject_id')} --{row.get('relation_type')}--> "
                f"{row.get('object_name') or row.get('object_id')}｜{row.get('scope')}｜{clean_text(row.get('evidence'), 80)}"
            )
        return "\n".join(lines)

    async def threads(self, action: str = "list", thread_id: str = "") -> str:
        action = (action or "list").lower()
        if action in {"list", "ls"}:
            rows = await self.service.store.list_cross_window_threads(status="open", limit=20)
            if not rows:
                return "没有打开的跨窗口线程。"
            lines = [f"跨窗口线程：{len(rows)} 条"]
            for row in rows:
                lines.append(
                    f"- {row.get('id')}｜{row.get('from_session')} -> {row.get('to_session')}｜{row.get('topic')}｜{clean_text(row.get('content'), 120)}"
                )
            return "\n".join(lines)
        if action in {"close", "done"}:
            if not thread_id:
                return "用法：/mcomp threads close <thread_id>"
            ok = await self.service.store.update_cross_window_thread_status(thread_id, "closed")
            return "已关闭线程。" if ok else "没有找到这个线程。"
        return "用法：/mcomp threads list|close <thread_id>"

    async def logs(self, limit: int = 5) -> str:
        rows = await self.service.store.recent_injection_logs(limit)
        if not rows:
            return "还没有注入日志。"
        lines = [f"最近注入日志：{len(rows)} 条"]
        for row in rows:
            selected = row.get("selected_memory_ids") or []
            blocked = row.get("blocked_reasons") or []
            lines.append(
                f"- {row.get('created_at')}｜{row.get('scope')}｜选中 {len(selected)}｜过滤 {len(blocked)}｜chars={row.get('injection_chars')}｜{clean_text(row.get('query'), 100)}"
            )
        return "\n".join(lines)

    async def maintenance(self) -> str:
        state = await self.service.sleep_maintenance(reason="command_maintenance")
        result = state.get("repair", {})
        raw = state.get("raw_retention", {})
        decay = state.get("decay", {})
        return (
            "维护完成："
            f"可见性修正 {result.get('manual_visibility_fixed', 0)}，"
            f"原始话语修正 {result.get('utterance_reality_fixed', 0)}，"
            f"指纹补齐 {result.get('fingerprint_fixed', 0)}，"
            f"重复归档 {result.get('duplicates_archived', 0)}；"
            f"原始事件归档 {raw.get('archived', 0)}；"
            f"衰减总结 {decay.get('summaries', 0)}，衰减归档 {decay.get('archived', 0)}；"
            f"睡眠维护时间 {state.get('ran_at', '-')}"
        )

    async def sleep(self, action: str = "status") -> str:
        action = (action or "status").lower()
        if action in {"run", "maintenance", "now"}:
            state = await self.service.sleep_maintenance(reason="command_sleep")
            repair = state.get("repair", {})
            raw = state.get("raw_retention", {})
            decay = state.get("decay", {})
            return (
                "睡眠维护完成："
                f"{state.get('ran_at', '-')}｜"
                f"指纹补齐 {repair.get('fingerprint_fixed', 0)}｜"
                f"重复归档 {repair.get('duplicates_archived', 0)}｜"
                f"原始事件归档 {raw.get('archived', 0)}｜"
                f"衰减总结 {decay.get('summaries', 0)}｜"
                f"衰减归档 {decay.get('archived', 0)}"
            )
        if action in {"status", "state", "last"}:
            state = self.service.sleep_status()
            return (
                "睡眠维护状态："
                f"{state.get('ran_at') or state.get('message') or '-'}"
            )
        return "用法：/mcomp sleep status|run"

    async def import_livingmemory(self, mode: str = "preview", path: str = "") -> str:
        configured = path or str(self.service.config.get("livingmemory_migration.livingmemory_db_path", "") or "")
        raw_mode = mode or "preview"
        mode = raw_mode.lower()
        known_modes = {
            "preview",
            "dry",
            "check",
            "detail",
            "details",
            "scan",
            "run",
            "import",
            "exec",
            "start",
            "help",
            "?",
            "usage",
        }
        if not path and mode not in known_modes:
            if raw_mode.endswith(".db") or "\\" in raw_mode or "/" in raw_mode:
                configured = raw_mode
                mode = "preview"
        if mode in {"help", "?", "usage"}:
            return self._livingmemory_usage()
        if mode in {"preview", "dry", "check"}:
            return self._format_livingmemory_preview(self.service.migrator.preview(configured))
        if mode in {"detail", "details", "scan"}:
            return self._format_livingmemory_preview(self.service.migrator.preview(configured), verbose=True)
        if mode in {"run", "import", "exec", "start"}:
            result = await self.service.import_livingmemory(configured_path=configured)
            return self._format_livingmemory_import_result(result)
        return self._livingmemory_usage()

    def help(self) -> str:
        return (
            "我会牢牢记住你命令：\n"
            "主入口 /mcomp。\n"
            "/mcomp status\n"
            "/mcomp search 关键词\n"
            "/mcomp explain 关键词\n"
            "/mcomp recent 10\n"
            "/mcomp add 要记住的内容\n"
            "/mcomp summarize\n"
            "/mcomp visibility <memory_id> <visibility>\n"
            "/mcomp promote <memory_id>\n"
            "/mcomp archive <memory_id>\n"
            "/mcomp timeline 10\n"
            "/mcomp relations [数量] [用户或群ID]\n"
            "/mcomp threads list|close <thread_id>\n"
            "/mcomp logs 5\n"
            "/mcomp maintenance\n"
            "/mcomp sleep status|run\n"
            "/mcomp delete <memory_id>\n"
            "/mcomp import_livingmemory preview|run|detail [db_path]"
        )

    def _format_livingmemory_preview(self, report: dict[str, Any], *, verbose: bool = False) -> str:
        if not report["candidates"]:
            return (
                "没找到 LivingMemory 数据库。\n"
                "可在配置页填写 livingmemory_db_path，或执行：\n"
                "/mcomp import_livingmemory preview <livingmemory.db>"
            )

        first = report["candidates"][0]
        if first.get("error"):
            return f"LivingMemory 读取失败：{first.get('error')}"

        importable_rows = sum(int(table.get("count") or 0) for table in first.get("tables", []) if table.get("importable"))
        skipped_rows = sum(int(table.get("count") or 0) for table in first.get("tables", []) if not table.get("importable"))
        lines = [
            "LivingMemory 预览：",
            f"将导入 {importable_rows} 条完整记忆，跳过 {skipped_rows} 条碎片。",
            f"来源：{first.get('path')}",
            "执行：/mcomp import_livingmemory run",
        ]
        if verbose:
            lines.insert(1, "策略：只导入 documents，跳过派生碎片。")
            lines.append("表：")
            for table in first.get("tables", [])[:10]:
                lines.append(f"- {self._format_livingmemory_table(table)}")
            if len(report["candidates"]) > 1:
                lines.append("其他候选：")
                for item in report["candidates"][1:5]:
                    summary = self._candidate_summary(item)
                    lines.append(f"- {item.get('path')}｜{summary}")
        else:
            lines.append("详情：/mcomp import_livingmemory detail")
        return "\n".join(lines)

    def _format_livingmemory_import_result(self, result: dict[str, Any]) -> str:
        if result.get("reason") and not result.get("source_path"):
            return (
                f"导入未执行：{result.get('reason')}\n"
                "先试：/mcomp import_livingmemory preview"
            )
        imported = int(result.get("imported") or 0)
        skipped = int(result.get("skipped") or 0)
        lines = [
            f"LivingMemory 导入完成：{imported} 条。",
            f"来源：{result.get('source_path') or '-'}",
        ]
        if skipped:
            lines.append(f"跳过异常行：{skipped} 条")
        if imported == 0:
            lines.append("没有新增内容，可能是旧库没有 documents 完整摘要。")
        lines.append("可在记忆面板或 /mcomp search 中查看。")
        return "\n".join(lines)

    def _format_livingmemory_table(self, table: dict[str, Any]) -> str:
        name = table.get("name")
        count = table.get("count", 0)
        if table.get("importable"):
            return f"{name}｜{count} 行｜将导入完整记忆"
        return f"{name}｜{count} 行｜跳过：{self._livingmemory_note(table.get('note'))}"

    def _candidate_summary(self, item: dict[str, Any]) -> str:
        if item.get("error"):
            return f"读取失败：{item.get('error')}"
        importable_rows = sum(int(table.get("count") or 0) for table in item.get("tables", []) if table.get("importable"))
        skipped_rows = sum(int(table.get("count") or 0) for table in item.get("tables", []) if not table.get("importable"))
        return f"可导入 {importable_rows}，跳过 {skipped_rows}"

    def _livingmemory_note(self, note: Any) -> str:
        text = clean_text(note, 80)
        mapping = {
            "derived_fragment_not_imported": "派生事实碎片",
            "not_importable": "没有可导入正文",
        }
        return mapping.get(text, text or "不是完整记忆")

    def _livingmemory_usage(self) -> str:
        return (
            "LivingMemory 迁移：\n"
            "/mcomp import_livingmemory preview  预览\n"
            "/mcomp import_livingmemory run      导入\n"
            "/mcomp import_livingmemory detail   详情"
        )
