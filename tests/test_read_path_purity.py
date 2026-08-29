"""读取/召回路径的结构纯净性与候选预算回归守卫。"""

from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import store as store_module
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SessionContext,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


_SCHEMA_ACTION_NAMES = (
    "SQLITE_CREATE_INDEX",
    "SQLITE_CREATE_TABLE",
    "SQLITE_CREATE_TEMP_INDEX",
    "SQLITE_CREATE_TEMP_TABLE",
    "SQLITE_CREATE_TEMP_TRIGGER",
    "SQLITE_CREATE_TEMP_VIEW",
    "SQLITE_CREATE_TRIGGER",
    "SQLITE_CREATE_VIEW",
    "SQLITE_DROP_INDEX",
    "SQLITE_DROP_TABLE",
    "SQLITE_DROP_TEMP_INDEX",
    "SQLITE_DROP_TEMP_TABLE",
    "SQLITE_DROP_TEMP_TRIGGER",
    "SQLITE_DROP_TEMP_VIEW",
    "SQLITE_DROP_TRIGGER",
    "SQLITE_DROP_VIEW",
    "SQLITE_ALTER_TABLE",
    "SQLITE_REINDEX",
    "SQLITE_ANALYZE",
    "SQLITE_CREATE_VTABLE",
    "SQLITE_DROP_VTABLE",
    "SQLITE_ATTACH",
    "SQLITE_DETACH",
)
_SCHEMA_ACTIONS = {
    getattr(sqlite3, name): name
    for name in _SCHEMA_ACTION_NAMES
    if hasattr(sqlite3, name)
}
_READ_ONLY_PRAGMAS = frozenset(
    {
        "table_info",
        "table_xinfo",
        "index_info",
        "index_xinfo",
        "index_list",
        "foreign_key_list",
        "data_version",
    }
)
_STRUCTURAL_SQL = re.compile(
    r"\b(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX|TRIGGER|VIEW|VIRTUAL\s+TABLE)\b"
    r"|\b(?:REINDEX|VACUUM|ATTACH|DETACH|ANALYZE)\b",
    re.IGNORECASE,
)


class _SqlAudit:
    """Reject structural SQL while retaining trace evidence for assertions."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.violations: list[str] = []
        self.connections: list[sqlite3.Connection] = []

    def install(self, connection: sqlite3.Connection) -> sqlite3.Connection:
        connection.set_authorizer(self._authorize)
        connection.set_trace_callback(self.statements.append)
        self.connections.append(connection)
        return connection

    def _authorize(
        self,
        action: int,
        arg1: str | None,
        arg2: str | None,
        _database: str | None,
        _trigger: str | None,
    ) -> int:
        action_name = _SCHEMA_ACTIONS.get(action)
        if action_name:
            self.violations.append(f"{action_name}:{arg1 or ''}:{arg2 or ''}")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA:
            pragma = str(arg1 or "").strip().casefold()
            if pragma not in _READ_ONLY_PRAGMAS:
                self.violations.append(f"SQLITE_PRAGMA:{pragma}:{arg2 or ''}")
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def detach(self) -> None:
        for connection in self.connections:
            try:
                connection.set_authorizer(None)
                connection.set_trace_callback(None)
            except sqlite3.ProgrammingError:
                pass

    def assert_clean(self, case: unittest.TestCase) -> None:
        case.assertEqual([], self.violations)
        for statement in self.statements:
            case.assertIsNone(_STRUCTURAL_SQL.search(statement), statement)
            normalized = " ".join(statement.split())
            if normalized.upper().startswith("PRAGMA "):
                pragma = normalized.split(None, 1)[1].split("(", 1)[0]
                pragma = pragma.rsplit(".", 1)[-1].strip("'\"[]`").casefold()
                case.assertIn(pragma, _READ_ONLY_PRAGMAS, statement)


@contextmanager
def _audit_new_store_connections(audit: _SqlAudit):
    real_connect = sqlite3.connect

    def connect(*args, **kwargs):
        return audit.install(real_connect(*args, **kwargs))

    with patch.object(store_module.sqlite3, "connect", side_effect=connect):
        yield


def _memory(index: int) -> MemoryRecord:
    return MemoryRecord(
        id=f"read-{index}",
        memory_type="user_preference" if index == 0 else "observation",
        subject=EntityRef("user", "u1", "用户", "unknown"),
        object=EntityRef("bot", "bot1", "机器人", "unknown"),
        scope="private",
        session_id="s1",
        visibility="shareable",
        lifecycle="stable_memory",
        review_status="auto",
        content=f"orchid meadow memory {index}",
        importance=1.0 - (index * 0.03),
        occurred_at=f"2026-08-25T07:{index:02d}:00+00:00",
        created_at=f"2026-08-25T07:{index:02d}:00+00:00",
        updated_at=f"2026-08-25T07:{index:02d}:00+00:00",
    )


class ReadPathPurityTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self, count: int = 8) -> MemoryStore:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = MemoryStore(Path(temp_dir.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        for index in range(count):
            store._insert_memory_sync(_memory(index))
        self.db_path = Path(temp_dir.name) / "memory.db"
        return store

    def test_read_only_initialize_executes_inspection_only(self) -> None:
        writer = self.make_store(count=1)
        writer.close()
        before_hash = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        audit = _SqlAudit()

        with _audit_new_store_connections(audit):
            read_only = MemoryStore(self.db_path, read_only=True)
            try:
                read_only.initialize()
                row = read_only._conn.execute("SELECT 1").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(1, row[0])
            finally:
                read_only.close()

        audit.assert_clean(self)
        self.assertEqual(before_hash, hashlib.sha256(self.db_path.read_bytes()).hexdigest())

    async def test_representative_reads_and_recall_do_not_mutate_schema(self) -> None:
        store = self.make_store()
        before_schema = store._schema_fingerprint_sync()
        before_changes = store._conn.total_changes
        audit = _SqlAudit()
        audit.install(store._conn)

        try:
            with _audit_new_store_connections(audit):
                self.assertEqual("read-0", (await store.get_memory("read-0")).id)
                self.assertEqual(3, len(await store.list_memories(limit=3)))
                self.assertEqual(3, len(await store.list_candidate_memories(limit=3)))
                self.assertLessEqual(
                    len(
                        await store.list_current_window_candidate_memories(
                            scope="private",
                            session_id="s1",
                            user_id="u1",
                            limit=3,
                        )
                    ),
                    3,
                )
                self.assertLessEqual(len(await store.list_fts_candidate_memories(["orchid"], limit=3)), 3)
                self.assertLessEqual(len(await store.list_keyword_candidate_memories(["orchid"], limit=3)), 3)
                self.assertLessEqual(
                    len(
                        await store.list_time_window_candidate_memories(
                            "2026-08-25T00:00:00+00:00",
                            "2026-08-26T00:00:00+00:00",
                            limit=3,
                        )
                    ),
                    3,
                )
                self.assertLessEqual(
                    len(
                        await store.list_schedule_context_memories(
                            session_id="s1",
                            user_id="u1",
                            bot_id="bot1",
                            limit=4,
                        )
                    ),
                    4,
                )

                engine = RetrievalEngine(
                    store,
                    VisibilityPolicy(enable_acl_rules=False),
                    retrieval_mode="basic",
                    embedding_enabled=False,
                    knowledge_graph_enabled=False,
                    current_window_candidate_limit=3,
                    keyword_fallback_min_fts_candidates=0,
                )
                engine.DEFAULT_MATERIALIZE_LIMIT = 4
                results = await engine.search(
                    "orchid meadow",
                    SessionContext(scope="private", session_id="s1", user_id="u1"),
                    top_k=2,
                )
                self.assertEqual(2, len(results))
                self.assertTrue(engine.last_path_info["candidate_bundle"])
                self.assertTrue(engine.last_path_info["ranking_offloaded"])
                self.assertTrue(engine.last_path_info["mmr_offloaded"])
        finally:
            audit.detach()

        audit.assert_clean(self)
        self.assertEqual(before_changes, store._conn.total_changes)
        self.assertEqual(before_schema, store._schema_fingerprint_sync())

    async def test_candidate_bundle_is_bounded_and_uses_light_hydration(self) -> None:
        store = self.make_store(count=12)
        audit = _SqlAudit()
        limits = {
            "ranked_candidates": 3,
            "current_window_candidates": 2,
            "fts_candidates": 2,
            "keyword_candidates": 2,
            "time_window_candidates": 2,
        }
        original_light = MemoryRecord.from_row_light

        with (
            _audit_new_store_connections(audit),
            patch.object(
                MemoryRecord,
                "from_row",
                side_effect=AssertionError("candidate bundle used full hydration"),
            ) as full_hydration,
            patch.object(MemoryRecord, "from_row_light", wraps=original_light) as light_hydration,
        ):
            bundle = await store.list_retrieval_candidate_bundle(
                materialize_limit=limits["ranked_candidates"],
                current_window={
                    "scope": "private",
                    "session_id": "s1",
                    "user_id": "u1",
                    "group_id": "",
                    "limit": limits["current_window_candidates"],
                },
                fts_terms=["orchid"],
                fts_limit=limits["fts_candidates"],
                keyword_terms=["orchid"],
                keyword_limit=limits["keyword_candidates"],
                keyword_fallback_min_fts=100,
                time_window=(
                    "2026-08-25T00:00:00+00:00",
                    "2026-08-26T00:00:00+00:00",
                    limits["time_window_candidates"],
                ),
                include_pending=False,
            )

        self.assertTrue(bundle["keyword_fallback_used"])
        for key, limit in limits.items():
            self.assertLessEqual(len(bundle[key]), limit, key)
        hydrated = sum(len(bundle[key]) for key in limits)
        self.assertEqual(hydrated, light_hydration.call_count)
        self.assertLessEqual(hydrated, sum(limits.values()))
        full_hydration.assert_not_called()

        candidate_selects = [
            " ".join(statement.split())
            for statement in audit.statements
            if statement.lstrip().upper().startswith("SELECT")
            and ("FROM memories" in statement or "FROM memory_fts" in statement)
        ]
        self.assertGreaterEqual(len(candidate_selects), 5)
        for statement in candidate_selects:
            self.assertIn(" LIMIT ", statement.upper(), statement)
        audit.assert_clean(self)


class ReadPathStaticGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tree = ast.parse((ROOT / "core" / "store.py").read_text(encoding="utf-8"))
        store_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MemoryStore"
        )
        cls.methods = {
            node.name: node
            for node in store_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def test_public_read_call_graph_cannot_reach_schema_ddl(self) -> None:
        calls = {
            name: {
                node.attr
                for node in ast.walk(method)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr in self.methods
            }
            for name, method in self.methods.items()
        }
        ddl_methods: set[str] = set()
        for name, method in self.methods.items():
            literals = "\n".join(
                str(node.value)
                for node in ast.walk(method)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            )
            if _STRUCTURAL_SQL.search(literals):
                ddl_methods.add(name)

        read_prefixes = ("get_", "list_", "recent_", "read_", "query_", "related_", "search_")
        roots = {
            name
            for name in self.methods
            if not name.startswith("_")
            and (name.startswith(read_prefixes) or name in {"stats", "memory_revision"})
        }
        reachable = set(roots)
        pending = list(roots)
        while pending:
            name = pending.pop()
            for called in calls.get(name, set()):
                if called not in reachable:
                    reachable.add(called)
                    pending.append(called)

        self.assertEqual(set(), reachable & ddl_methods)

    def test_candidate_fetchall_helpers_have_sql_limits(self) -> None:
        helpers = {
            "_materialized_candidate_rows",
            "_current_window_candidate_rows",
            "_fts_candidate_rows",
            "_keyword_candidate_rows",
            "_time_window_candidate_rows",
        }
        for name in helpers:
            method = self.methods[name]
            literals = "\n".join(
                str(node.value)
                for node in ast.walk(method)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            )
            self.assertRegex(literals, r"\bLIMIT\s+\?", name)
            self.assertTrue(
                any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "fetchall"
                    for node in ast.walk(method)
                ),
                name,
            )

        bundle = self.methods["_list_retrieval_candidate_bundle_sync"]
        constructors = [
            node.func.attr
            for node in ast.walk(bundle)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "MemoryRecord"
        ]
        self.assertIn("from_row_light", constructors)
        self.assertNotIn("from_row", constructors)


if __name__ == "__main__":
    unittest.main()
