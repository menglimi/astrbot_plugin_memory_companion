from __future__ import annotations

import ast
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.astrbot_compat import sanitize_request_history
from astrbot_plugin_memory_companion.core.injection import InjectionComposer
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SearchResult, SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.time_intent import parse_time_intent


class CurrentIssueRegressionTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        service = MemoryCompanionService(
            context=None,
            config={"retrieval": {"mode": "basic", "embedding_enabled": False}},
            plugin_root=ROOT,
            data_dir=Path(directory.name),
        )
        self.addCleanup(service.close)
        return service

    def test_remember_tool_docstring_uses_valid_individual_parameter_names(self) -> None:
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "memory_companion_remember_tool"
        )
        docstring = ast.get_docstring(function, clean=False) or ""
        args_section = docstring.split("Args:", 1)[1]
        names = re.findall(r"^\s{12}([A-Za-z_][A-Za-z0-9_]*)\(", args_section, re.MULTILINE)

        self.assertIn("confidence", names)
        self.assertIn("importance", names)
        self.assertIn("valid_from", names)
        self.assertIn("valid_to", names)
        self.assertFalse(any("/" in name for name in names))

    def test_history_cleaner_preserves_tool_errors_and_cron_summaries(self) -> None:
        contexts = [
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": "Tool astrbot_read_image not found. Available tools include send_message_to_user.",
            },
            {
                "role": "assistant",
                "content": "[CronJob] watered plants: used `send_message_to_user` to send the reminder.",
            },
        ]
        request = SimpleNamespace(contexts=contexts)

        result = sanitize_request_history(request, clean_proactive_guidance=True)

        self.assertEqual({"before": 2, "after": 2, "removed": 0, "cleaned": 0}, result)
        self.assertEqual(contexts, request.contexts)

    async def test_same_session_private_memory_survives_platform_prefilter(self) -> None:
        service = self.make_service()
        memory = MemoryRecord(
            id="legacy-qq-memory",
            memory_type="explicit_memory",
            subject=EntityRef(kind="user", id="u1"),
            scope="private",
            session_id="lark:FriendMessage:u1",
            platform="qq",
            visibility="private_pair",
            lifecycle="stable_memory",
            content="用户喜欢蓝色。",
            confidence=0.9,
            importance=0.9,
        )
        context = SessionContext(
            session_id="lark:FriendMessage:u1",
            scope="private",
            platform="lark",
            user_id="u1",
            message_text="我喜欢什么颜色？",
        )
        engine = service._retrieval_validation_engine()

        visible, blocked = await engine.filter_visible_candidates([memory], context)
        self.assertEqual([memory.id], [item.memory.id for item in visible])
        self.assertEqual([], blocked)

        other_session = SessionContext(
            session_id="lark:FriendMessage:u2",
            scope="private",
            platform="lark",
            user_id="u2",
            message_text="我喜欢什么颜色？",
        )
        visible, blocked = await engine.filter_visible_candidates([memory], other_session)
        self.assertEqual([], visible)
        self.assertEqual("other_platform", blocked[0]["reason"])

    def test_accepted_confidence_floor_is_not_marked_uncertain(self) -> None:
        service = self.make_service()
        now = datetime.now(timezone.utc).isoformat()
        context = SessionContext(
            session_id="qq:FriendMessage:u1",
            scope="private",
            platform="qq",
            user_id="u1",
            message_text="我之前提过喜欢蓝色。",
        )
        memory = MemoryRecord(
            id="confidence-floor",
            memory_type="explicit_memory",
            subject=EntityRef(kind="user", id="u1"),
            scope="private",
            session_id=context.session_id,
            platform="qq",
            visibility="private_pair",
            lifecycle="stable_memory",
            content="用户喜欢蓝色。",
            confidence=0.55,
            importance=0.8,
            created_at=now,
            updated_at=now,
            metadata={"owner_bot_id": "bot-1"},
        )
        context.bot_id = "bot-1"
        expression, _reason = service._memory_expression_decision(
            context,
            memory,
            SearchResult(memory=memory, score=2.0),
            "stable_memory",
            SimpleNamespace(layer="memory_recall"),
            parse_time_intent(""),
            query_text=context.message_text,
        )

        self.assertNotEqual("uncertain", expression)

    def test_uncertain_omission_diagnostic_keeps_confidence_and_threshold(self) -> None:
        memory = MemoryRecord(
            id="low-confidence",
            memory_type="explicit_memory",
            content="用户可能喜欢蓝色。",
            confidence=0.54,
        )
        result = SearchResult(
            memory=memory,
            score=0.4,
            reason="expression=uncertain;low_confidence:confidence=0.54:threshold=0.55",
        )
        composer = InjectionComposer()

        composer.compose(SessionContext(scope="private", user_id="u1"), [result], max_chars=1200)

        self.assertTrue(any(
            diagnostic["reason"].startswith("injection_omitted:uncertain")
            and "confidence=0.54:threshold=0.55" in diagnostic["reason"]
            for diagnostic in composer.last_omission_diagnostics
        ))

    async def test_injection_log_persists_slot_diagnostics(self) -> None:
        service = self.make_service()
        diagnostics = {
            "slot_counts": {"conversation_summary": 2},
            "slot_limits": {"conversation_summary": 2},
            "capped_slots": ["open_loop", "self_timeline"],
        }
        await service.store.add_injection_log(
            session_id="qq:FriendMessage:u1",
            scope="private",
            query="昨天聊了什么",
            selected_memory_ids=["memory-1"],
            blocked_reasons=[{
                "id": "memory-2",
                "reason": "slot_capped:conversation_summary",
                "score": 2.9159,
                "content": "",
            }],
            injection_chars=120,
            retrieval_info=diagnostics,
        )

        [row] = await service.store.recent_injection_logs(limit=1)
        self.assertEqual(diagnostics, row["retrieval_info"])
        self.assertEqual("slot_capped:conversation_summary", row["blocked_reasons"][0]["reason"])

    async def test_old_injection_log_table_upgrades_with_owner_and_diagnostics(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = MemoryStore(Path(directory.name) / "old-memory.db")
        self.addCleanup(store.close)
        store._conn.execute(
            "CREATE TABLE injection_logs (id TEXT PRIMARY KEY, session_id TEXT, scope TEXT, "
            "query TEXT, selected_memory_ids TEXT, blocked_reasons TEXT, "
            "injection_chars INTEGER, created_at TEXT)"
        )
        store._conn.commit()
        store.initialize()

        await store.add_injection_log(
            session_id="qq:FriendMessage:u1", scope="private", query="回顾",
            selected_memory_ids=[], blocked_reasons=[], injection_chars=0,
            user_id="u1", bot_id="b1", retrieval_info={"slot_counts": {}},
        )
        [row] = await store.recent_injection_logs(limit=1)
        self.assertEqual(("u1", "b1"), (row["user_id"], row["bot_id"]))
        self.assertEqual({"slot_counts": {}}, row["retrieval_info"])


if __name__ == "__main__":
    unittest.main()
