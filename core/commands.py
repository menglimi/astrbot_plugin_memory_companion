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

    async def clear_scope(
        self,
        target_type: str = "",
        first_id: str = "",
        second_id: str = "",
        confirm: str = "",
    ) -> str:
        target_type = clean_text(target_type, 40).lower()
        first_id = clean_text(first_id, 120)
        second_id = clean_text(second_id, 120)
        confirm = clean_text(confirm, 20)
        if target_type in {"group", "private"} and second_id == "清空" and not confirm:
            confirm = second_id
            second_id = ""
        if target_type not in {"group", "private", "group_member"}:
            return (
                "用法：\n"
                "/mcomp clear_scope group <群号> [清空]\n"
                "/mcomp clear_scope private <QQ> [清空]\n"
                "/mcomp clear_scope group_member <群号> <QQ> [清空]\n"
                "不带“清空”只预览数量，带“清空”才执行。"
            )
        group_id = first_id if target_type in {"group", "group_member"} else ""
        user_id = first_id if target_type == "private" else second_id
        try:
            if confirm == "清空":
                result = await self.service.clear_scoped_memory(
                    target_type=target_type,
                    group_id=group_id,
                    user_id=user_id,
                )
                action = "已清空"
            else:
                result = await self.service.store.preview_scoped_memory_clear(
                    target_type=target_type,
                    group_id=group_id,
                    user_id=user_id,
                )
                action = "预览"
        except ValueError as exc:
            return f"参数错误：{exc}"
        counts = result.get("deleted") if confirm == "清空" else result.get("counts")
        counts = counts or {}
        lines = [
            f"{action}范围：{self._clear_scope_label(target_type, group_id, user_id)}",
            "影响数量："
        ]
        for key in ["memories", "timeline", "relationship_edges", "knowledge_nodes", "knowledge_edges", "injection_logs", "summary_failures", "cross_window_threads"]:
            lines.append(f"- {key}: {counts.get(key, 0)}")
        if confirm != "清空":
            lines.append("确认执行请在命令末尾加：清空")
        elif result.get("backup"):
            lines.append(f"备份：{result.get('backup')}")
        return "\n".join(lines)

    @staticmethod
    def _clear_scope_label(target_type: str, group_id: str, user_id: str) -> str:
        if target_type == "group":
            return f"群聊 {group_id}"
        if target_type == "private":
            return f"私聊 {user_id}"
        return f"群聊 {group_id} 中的用户 {user_id}"

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
            f"重复归档 {result.get('duplicates_archived', 0)}，"
            f"全文索引 {result.get('fts_rebuilt', 0)}；"
            f"原始事件归档 {raw.get('archived', 0)}；"
            f"衰减总结 {decay.get('summaries', 0)}，衰减归档 {decay.get('archived', 0)}；"
            f"睡眠维护时间 {state.get('ran_at', '-')}"
        )

    async def diagnostics(self) -> str:
        report = await self.service.operational_report()
        cache = report.get("cache") or {}
        usage = report.get("model_usage") or {}
        retrieval = report.get("retrieval") or {}
        conflicts = report.get("conflicts") or []
        hit_rate = cache.get("hit_rate")
        hit_label = f"{float(hit_rate) * 100:.1f}%" if hit_rate is not None else "暂无样本"
        avg_ms = usage.get("average_elapsed_ms")
        avg_label = f"{float(avg_ms):.1f}ms" if avg_ms is not None else "暂无样本"
        lines = [
            "记忆运维诊断：",
            f"配置预设：{report.get('preset_label')} ({report.get('preset')})",
            f"检索：mode={retrieval.get('mode')}｜Embedding={retrieval.get('embedding_enabled')}｜零外部检索调用={retrieval.get('zero_external_retrieval_calls')}",
            f"缓存：命中 {cache.get('hits', 0)}｜未命中 {cache.get('misses', 0)}｜命中率 {hit_label}｜当前 {cache.get('entries', 0)} 项",
            f"模型消耗：调用 {usage.get('calls', 0)}｜Token {usage.get('total_tokens', 0)}｜估算 Token {usage.get('estimated_tokens', 0)}｜平均耗时 {avg_label}",
        ]
        if conflicts:
            lines.append("插件共存：")
            for item in conflicts:
                lines.append(
                    f"- {item.get('label')}｜{item.get('level')}｜{item.get('reason')}"
                )
        else:
            lines.append("插件共存：未检测到已知记忆插件目录。")
        warnings = report.get("warnings") or []
        if warnings:
            lines.append("注意：")
            lines.extend(f"- {warning}" for warning in warnings)
        lines.append(str(report.get("benchmark_note") or ""))
        return "\n".join(line for line in lines if line)

    def preset(self, action: str = "status", name: str = "") -> str:
        action = clean_text(action, 40).lower() or "status"
        name = clean_text(name, 40).lower()
        if action in {"light", "standard", "companion"} and not name:
            name = action
            action = "apply"
        if action in {"status", "show", "current"}:
            status = self.service.operation_preset_status()
            return (
                f"当前配置预设：{status.get('label')} ({status.get('preset')})\n"
                "可用：light（轻量）、standard（标准）、companion（陪伴）\n"
                "应用：/mcomp preset apply <名称>"
            )
        if action in {"apply", "use", "set"} and name in {"light", "standard", "companion"}:
            result = self.service.apply_operation_preset(name)
            return (
                f"已应用{result.get('label')}预设。\n"
                f"修改 {len(result.get('changed') or {})} 项；模型 Provider 选择保持不变。\n"
                f"配置：{result.get('config_path')}"
            )
        return "用法：/mcomp preset status|apply light|standard|companion"

    async def portable_data(self, action: str = "help", path: str = "") -> str:
        action = clean_text(action, 40).lower() or "help"
        path = str(path or "").strip()
        try:
            if action in {"export", "backup"}:
                result = await self.service.export_portable_data()
                counts = result.get("counts") or {}
                return (
                    "UTF-8 JSONL 导出完成：\n"
                    f"路径：{result.get('path')}\n"
                    f"记忆 {counts.get('memory', 0)}｜身份 {counts.get('identity', 0)}｜关系 {counts.get('relationship', 0)}｜"
                    f"时间线 {counts.get('timeline', 0)}｜ACL {counts.get('acl_rule', 0) + counts.get('acl_policy', 0)}"
                )
            if action in {"preview", "check"}:
                if not path:
                    return "用法：/mcomp data preview <jsonl_path>"
                result = self.service.preview_portable_data(path)
                return (
                    "可移植档案预览：\n"
                    f"路径：{result.get('path')}\n"
                    f"格式：{result.get('format')} v{result.get('version')}｜记录 {result.get('total_records', 0)}\n"
                    f"分类：{result.get('counts')}"
                )
            if action in {"import", "restore"}:
                if not path:
                    return "用法：/mcomp data import <jsonl_path>"
                result = await self.service.import_portable_data(path)
                return (
                    "可移植档案导入完成：\n"
                    f"导入：{result.get('imported')}\n"
                    f"跳过：{result.get('skipped')}\n"
                    f"导入前备份：{result.get('backup')}\n"
                    f"错误示例：{result.get('errors') or '无'}"
                )
        except (OSError, ValueError, RuntimeError) as exc:
            return f"数据操作失败：{exc}"
        return (
            "可移植数据命令：\n"
            "/mcomp data export\n"
            "/mcomp data preview <jsonl_path>\n"
            "/mcomp data import <jsonl_path>"
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
                f"全文索引 {repair.get('fts_rebuilt', 0)}｜"
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
            "/mcomp diagnostics\n"
            "/mcomp preset status|apply light|standard|companion\n"
            "/mcomp data export|preview|import [jsonl_path]\n"
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
