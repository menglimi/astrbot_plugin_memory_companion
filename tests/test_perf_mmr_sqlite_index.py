from __future__ import annotations

import json
import math
import random
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import retrieval as retrieval_mod
from astrbot_plugin_memory_companion.core.models import (
    EntityRef,
    MemoryRecord,
    SearchResult,
    clean_text,
)
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.store import (
    MemoryStore,
    _memory_time_sql,
    _timeline_time_sql,
)
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


class _NullStore:
    pass


def _make_engine(*, mmr_redundancy_weight: float = 0.35) -> RetrievalEngine:
    return RetrievalEngine(
        _NullStore(),
        VisibilityPolicy(enable_acl_rules=False),
        retrieval_mode="basic",
        embedding_enabled=False,
        knowledge_graph_enabled=False,
        mmr_redundancy_weight=mmr_redundancy_weight,
    )


def _reference_mmr(
    engine: RetrievalEngine,
    ranked: list[SearchResult],
    selection_limit: int,
) -> list[SearchResult]:
    """Unoptimized reference MMR implementation for strict equivalence checks."""
    if len(ranked) < 2 or selection_limit <= 1:
        return ranked
    head_size = min(len(ranked), max(int(selection_limit or 1) * 4, 16))
    pool = list(ranked[:head_size])
    scores = [float(item.score) for item in pool]
    minimum = min(scores)
    maximum = max(scores)

    def relevance(item: SearchResult) -> float:
        if maximum <= minimum:
            return 1.0
        return (float(item.score) - minimum) / (maximum - minimum)

    def features(item: SearchResult) -> set[str]:
        memory = item.memory
        text = re.sub(r"\s+", "", engine._haystack(memory))
        cjk = {
            text[index : index + 2]
            for index in range(max(0, len(text) - 1))
            if text[index : index + 2]
        }
        latin = set(re.findall(r"[a-z0-9_]{2,}", text))
        tags = {
            f"tag:{clean_text(tag, 40).lower()}"
            for tag in (memory.tags or [])
            if clean_text(tag, 40)
        }
        source = clean_text(memory.source_plugin, 60).lower()
        return set(sorted(cjk)[:180]) | latin | tags | ({f"source:{source}"} if source else set())

    feature_map = {id(item): features(item) for item in pool}

    def similarity(left: SearchResult, right: SearchResult) -> float:
        left_features = feature_map[id(left)]
        right_features = feature_map[id(right)]
        union = left_features | right_features
        return (len(left_features & right_features) / len(union)) if union else 0.0

    selected: list[SearchResult] = [pool.pop(0)]
    target = min(len(ranked), max(1, int(selection_limit or 1)))
    while pool and len(selected) < target:
        best_index = 0
        best_value = -math.inf
        for index, item in enumerate(pool):
            redundancy = max(similarity(item, chosen) for chosen in selected)
            value = (0.84 * relevance(item)) - (engine.mmr_redundancy_weight * redundancy)
            if value > best_value:
                best_value = value
                best_index = index
        selected.append(pool.pop(best_index))
    selected_ids = {id(item) for item in selected}
    tail = [item for item in ranked if id(item) not in selected_ids]
    return [*selected, *tail]


def _make_memory(
    memory_id: str,
    content: str,
    *,
    scope: str = "private",
    session_id: str = "s1",
    subject_id: str = "u1",
    object_id: str = "bot",
    group_id: str = "",
    visibility: str = "private_pair",
    lifecycle: str = "stable_memory",
    review_status: str = "auto",
    importance: float = 0.5,
    occurred_at: str = "",
    updated_at: str = "",
    created_at: str = "2026-11-18T00:00:00+00:00",
    subject_person_id: str = "",
    identity_assurance: str = "",
    tags: list[str] | None = None,
    source_plugin: str = "memory_companion",
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        memory_type="memory",
        subject=EntityRef(kind="user", id=subject_id),
        object=EntityRef(kind="bot", id=object_id),
        owner_bot_id="bot",
        scope=scope,
        session_id=session_id,
        group_id=group_id,
        visibility=visibility,
        lifecycle=lifecycle,
        review_status=review_status,
        importance=importance,
        occurred_at=occurred_at,
        updated_at=updated_at,
        created_at=created_at,
        subject_person_id=subject_person_id,
        identity_assurance=identity_assurance,
        content=content,
        tags=tags or [],
        source_plugin=source_plugin,
    ).ensure_defaults()


def _explain_details(store: MemoryStore, sql: str, params: tuple = ()) -> list[str]:
    rows = store._conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return [str(row["detail"]) for row in rows]


class PerfMmrAndSqliteIndexTests(unittest.TestCase):
    def test_module_level_mmr_regexes_are_precompiled(self) -> None:
        self.assertIsInstance(retrieval_mod._MMR_WHITESPACE_RE, re.Pattern)
        self.assertIsInstance(retrieval_mod._MMR_LATIN_TOKEN_RE, re.Pattern)

    def test_mmr_memoized_matches_reference_across_random_ties_and_mixed_texts(self) -> None:
        rng = random.Random(20261118)
        fragments_cjk = ["蓝风铃", "午夜盛开", "冰美式不加糖", "周末加班", "樱花树下", "数据库索引", "回忆整理", "轻声细语"]
        fragments_latin = ["alpha_01", "beta_2", "coffee_latte", "sql_index", "mmr_cache", "x", "z9"]

        for weight in (0.0, 0.16, 0.35, 0.8):
            engine = _make_engine(mmr_redundancy_weight=weight)
            for trial in range(8):
                candidates: list[SearchResult] = []
                for idx in range(70):
                    if idx % 7 == 0:
                        # Long CJK + Latin mixed text exceeding the 180-bigram cap
                        long_cjk = "".join(rng.choice(fragments_cjk) for _ in range(95))
                        long_lat = " ".join(rng.choice(fragments_latin) for _ in range(12))
                        content = f"{long_cjk} \n\t {long_lat}"
                    else:
                        content = " ".join(
                            rng.choice(fragments_cjk + fragments_latin)
                            for _ in range(rng.randint(2, 6))
                        )
                    if trial % 3 == 0:
                        score = 0.85  # All tied scores
                    elif trial % 3 == 1:
                        score = round(rng.choice([0.95, 0.90, 0.85, 0.80, 0.70, 0.55]), 2)  # Frequent ties
                    else:
                        score = rng.uniform(0.1, 1.0)
                    rec = _make_memory(
                        f"mem-{trial}-{idx}",
                        content,
                        tags=[rng.choice(["flower", "drink", "work", "  "])] if idx % 2 == 0 else [],
                        source_plugin="memory_companion" if idx % 3 else "chat_summary",
                    )
                    candidates.append(SearchResult(memory=rec, score=score))

                for top_k in (1, 2, 5, 12, 24):
                    expected = _reference_mmr(engine, list(candidates), top_k)
                    actual = engine._mmr_diversify(list(candidates), top_k)
                    self.assertEqual(
                        [item.memory.id for item in expected],
                        [item.memory.id for item in actual],
                        f"MMR order mismatch: weight={weight}, trial={trial}, top_k={top_k}",
                    )

    def test_mmr_caches_features_once_per_evaluated_item(self) -> None:
        engine = _make_engine(mmr_redundancy_weight=0.35)
        call_counts: dict[str, int] = {}
        original_haystack = engine._haystack

        def counted_haystack(memory: MemoryRecord) -> str:
            call_counts[memory.id] = call_counts.get(memory.id, 0) + 1
            return original_haystack(memory)

        engine._haystack = counted_haystack  # type: ignore[method-assign]
        candidates = [
            SearchResult(memory=_make_memory(f"c-{i}", f"第{i}条 记忆内容 token_{i}"), score=1.0 - i * 0.01)
            for i in range(40)
        ]
        result = engine._mmr_diversify(list(candidates), 12)
        self.assertEqual(len(candidates), len(result))
        self.assertTrue(all(count <= 1 for count in call_counts.values()))

    def test_sqlite_indexes_created_and_explain_uses_index_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.db"
            store = MemoryStore(db_path)
            store.initialize()
            try:
                for idx in range(30):
                    store._insert_memory_sync(
                        _make_memory(
                            f"m-{idx}",
                            f"索引测试记忆 {idx}",
                            scope="group" if idx % 2 == 0 else "private",
                            session_id=f"sess-{idx % 3}",
                            group_id=f"grp-{idx % 3}" if idx % 2 == 0 else "",
                            subject_id=f"user-{idx % 4}",
                            object_id=f"obj-{idx % 4}",
                            importance=0.1 * ((idx % 9) + 1),
                            occurred_at=f"2026-11-{(idx % 20) + 1:02d}T10:00:00+00:00",
                        )
                    )
                store.close()

                # Re-open so ANALYZE populates sqlite_stat1 on non-empty memories
                store = MemoryStore(db_path)
                store.initialize()

                indexes = {
                    row["name"]
                    for row in store._conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memories'"
                    ).fetchall()
                }
                self.assertIn("idx_memories_session_id", indexes)
                self.assertIn("idx_memories_time_order", indexes)
                self.assertIn("idx_memories_time_order_nullif", indexes)
                self.assertIn("idx_memories_time_order_updated_nullif", indexes)
                self.assertIn("idx_memories_archive_time_order_nullif", indexes)
                self.assertIn("idx_memories_archive_importance_time_nullif", indexes)

                stat_indexes = {
                    row["idx"]
                    for row in store._conn.execute(
                        "SELECT idx FROM sqlite_stat1 WHERE tbl='memories'"
                    ).fetchall()
                }
                self.assertIn("idx_memories_session_id", stat_indexes)
                self.assertIn("idx_memories_time_order_nullif", stat_indexes)

                session_plan = _explain_details(
                    store,
                    "SELECT * FROM memories WHERE session_id=?",
                    ("sess-0",),
                )
                self.assertTrue(any("SEARCH memories USING INDEX" in d for d in session_plan), session_plan)

                base_cw = f"lifecycle != 'archived' AND {store._recallable_memory_sql()} AND review_status != 'pending'"
                time_upd = _memory_time_sql(include_updated=True)
                for branch_where, param in [
                    ("session_id=?", "sess-0"),
                    ("scope='group' AND group_id=?", "grp-0"),
                    ("scope='private' AND subject_id=?", "user-1"),
                    ("scope='private' AND object_id=?", "obj-1"),
                    (
                        "scope='private' AND visibility='private_pair' "
                        "AND subject_person_id=? AND identity_assurance='explicit_linked'",
                        "person_abc",
                    ),
                ]:
                    plan = _explain_details(
                        store,
                        f"SELECT * FROM memories WHERE {base_cw} AND {branch_where} "
                        f"ORDER BY importance DESC, {time_upd} DESC LIMIT 50",
                        (param,),
                    )
                    self.assertTrue(
                        any("SEARCH memories USING INDEX" in d for d in plan),
                        f"Branch {branch_where} did not use index search: {plan}",
                    )
                    self.assertFalse(
                        any("USE TEMP B-TREE FOR ORDER BY" in d for d in plan),
                        f"Branch {branch_where} still used TEMP B-TREE: {plan}",
                    )

                where_mat = (
                    f"lifecycle != 'archived' AND {store._recallable_memory_sql()} "
                    "AND COALESCE(validity_status, 'active') NOT IN "
                    "('archived', 'deleted', 'superseded', 'expired', 'quarantined') "
                    "AND review_status != 'pending'"
                )
                time_no_upd = _memory_time_sql(include_updated=False)
                mat_plan = _explain_details(
                    store,
                    f"""
                    SELECT * FROM (
                        SELECT * FROM memories WHERE {where_mat}
                        ORDER BY importance DESC, {time_no_upd} DESC
                        LIMIT 20
                    )
                    UNION ALL
                    SELECT * FROM (
                        SELECT * FROM memories WHERE {where_mat}
                        ORDER BY {time_no_upd} DESC
                        LIMIT 20
                    )
                    """,
                )
                self.assertFalse(
                    any("USE TEMP B-TREE FOR ORDER BY" in d for d in mat_plan),
                    f"Materialized query used TEMP B-TREE: {mat_plan}",
                )
            finally:
                store.close()

    def test_current_window_candidate_rows_matches_legacy_full_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                person_id = "person_" + "a" * 24
                seed_records = [
                    # Matches session_id only
                    _make_memory(
                        "cw-sess-1",
                        "当前会话记忆一",
                        scope="private",
                        session_id="qq:FriendMessage:u_main",
                        subject_id="other_u",
                        object_id="bot",
                        importance=0.7,
                        occurred_at="2026-11-18T01:00:00+00:00",
                    ),
                    # Matches subject_id (different session)
                    _make_memory(
                        "cw-subj-1",
                        "私聊主体记忆",
                        scope="private",
                        session_id="qq:FriendMessage:old_sess",
                        subject_id="u_main",
                        object_id="bot",
                        importance=0.9,
                        occurred_at="",
                        updated_at="2026-11-18T02:00:00+00:00",
                        created_at="2026-11-17T00:00:00+00:00",
                    ),
                    # Matches object_id with importance tie -> sorted by time DESC
                    _make_memory(
                        "cw-obj-1",
                        "私聊客体记忆旧",
                        scope="private",
                        session_id="qq:FriendMessage:another",
                        subject_id="other_u2",
                        object_id="u_main",
                        importance=0.9,
                        occurred_at="",
                        updated_at="",
                        created_at="2026-11-18T01:30:00+00:00",
                    ),
                    # Matches explicit linked subject_person_id -> prioritized first even with lower importance
                    _make_memory(
                        "cw-person-1",
                        "跨平台绑定人物记忆",
                        scope="private",
                        session_id="web:FriendMessage:linked_u",
                        subject_id="linked_u",
                        object_id="bot",
                        visibility="private_pair",
                        subject_person_id=person_id,
                        identity_assurance="explicit_linked",
                        importance=0.2,
                        occurred_at="2026-11-18T00:10:00+00:00",
                    ),
                    # Pending memory (included only when include_pending=True)
                    _make_memory(
                        "cw-pending",
                        "待审核记忆",
                        scope="private",
                        session_id="qq:FriendMessage:u_main",
                        subject_id="u_main",
                        review_status="pending",
                        importance=0.95,
                        occurred_at="2026-11-18T03:00:00+00:00",
                    ),
                    # Archived memory (always excluded)
                    _make_memory(
                        "cw-archived",
                        "已归档记忆",
                        scope="private",
                        session_id="qq:FriendMessage:u_main",
                        subject_id="u_main",
                        lifecycle="archived",
                        importance=1.0,
                    ),
                    # Archive ref memory (always excluded)
                    _make_memory(
                        "cw-archive-ref",
                        "Bot Personal archive reference [test_ref]",
                        scope="private",
                        session_id="qq:FriendMessage:u_main",
                        subject_id="u_main",
                        importance=1.0,
                    ),
                    # Group scope memories
                    _make_memory(
                        "cw-grp-1",
                        "群聊记忆高重要度",
                        scope="group",
                        session_id="qq:GroupMessage:g1",
                        group_id="g1",
                        importance=0.85,
                        occurred_at="2026-11-18T04:00:00+00:00",
                    ),
                    _make_memory(
                        "cw-grp-2",
                        "群聊记忆同群不同会话",
                        scope="group",
                        session_id="qq:GroupMessage:g1_thread",
                        group_id="g1",
                        importance=0.85,
                        occurred_at="2026-11-18T05:00:00+00:00",
                    ),
                ]
                for rec in seed_records:
                    store._insert_memory_sync(rec)

                def reference_current_window(
                    scope: str,
                    session_id: str,
                    user_id: str,
                    group_id: str,
                    limit: int,
                    include_pending: bool,
                    subject_person_id: str = "",
                    identity_assurance: str = "",
                ) -> list[str]:
                    clauses = []
                    params = []
                    if session_id:
                        clauses.append("session_id=?")
                        params.append(session_id)
                    if scope == "group" and group_id:
                        clauses.append("(scope='group' AND group_id=?)")
                        params.append(group_id)
                    elif scope == "private" and user_id:
                        sub = "subject_id=? OR object_id=?"
                        params.extend([user_id, user_id])
                        if subject_person_id and identity_assurance == "explicit_linked":
                            sub += " OR (visibility='private_pair' AND subject_person_id=? AND identity_assurance='explicit_linked')"
                            params.append(subject_person_id)
                        clauses.append(f"(scope='private' AND ({sub}))")
                    where = f"lifecycle != 'archived' AND {store._recallable_memory_sql()} AND (" + " OR ".join(clauses) + ")"
                    if not include_pending:
                        where += " AND review_status != 'pending'"
                    order_by = "importance DESC, " + _memory_time_sql(include_updated=True) + " DESC"
                    if subject_person_id and identity_assurance == "explicit_linked":
                        order_by = (
                            "CASE WHEN subject_person_id=? AND identity_assurance='explicit_linked' "
                            "THEN 0 ELSE 1 END, " + order_by
                        )
                        params.append(subject_person_id)
                    rows = store._conn.execute(
                        f"SELECT id FROM memories WHERE {where} ORDER BY {order_by} LIMIT ?",
                        params + [limit],
                    ).fetchall()
                    return [str(r["id"]) for r in rows]

                cases = [
                    ("private", "qq:FriendMessage:u_main", "u_main", "", 10, False, "", ""),
                    ("private", "qq:FriendMessage:u_main", "u_main", "", 10, True, "", ""),
                    ("private", "qq:FriendMessage:u_main", "u_main", "", 10, False, person_id, "explicit_linked"),
                    ("private", "qq:FriendMessage:u_main", "u_main", "", 2, False, person_id, "explicit_linked"),
                    ("group", "qq:GroupMessage:g1", "", "g1", 10, False, "", ""),
                    ("group", "qq:GroupMessage:g1", "", "g1", 1, False, "", ""),
                    ("private", "nonexistent_sess", "nonexistent_user", "", 10, False, "", ""),
                ]
                for args in cases:
                    expected_ids = reference_current_window(*args)
                    actual_rows = store._current_window_candidate_rows(store._conn, *args)
                    actual_ids = [str(r["id"]) for r in actual_rows]
                    self.assertEqual(expected_ids, actual_ids, f"Mismatch for args={args}")
            finally:
                store.close()

    def test_timeline_cross_window_index_created_and_explain_uses_index_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.db"
            store = MemoryStore(db_path)
            store.initialize()
            try:
                for idx in range(30):
                    scope = "group" if idx % 2 == 0 else "private"
                    event_type = (
                        "user_message"
                        if idx % 3 == 0
                        else ("bot_response" if idx % 3 == 1 else "system_note")
                    )
                    store._add_timeline_event_sync(
                        event_type,
                        f"sess-{idx % 4}",
                        scope,
                        f"user-{idx % 5}",
                        "bot",
                        f"时间线跨窗口测试消息 {idx}",
                        {"owner_bot_id": "bot-a" if idx % 2 == 0 else ""},
                        f"2026-11-{(idx % 20) + 1:02d}T10:00:00+00:00",
                    )
                store.close()

                # Re-open so ANALYZE timeline populates sqlite_stat1 on non-empty timeline
                store = MemoryStore(db_path)
                store.initialize()

                timeline_indexes = {
                    row["name"]
                    for row in store._conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='timeline'"
                    ).fetchall()
                }
                self.assertIn("idx_timeline_scope_event_time", timeline_indexes)

                stat_indexes = {
                    row["idx"]
                    for row in store._conn.execute(
                        "SELECT idx FROM sqlite_stat1 WHERE tbl='timeline'"
                    ).fetchall()
                }
                self.assertIn("idx_timeline_scope_event_time", stat_indexes)

                event_time_sql = _timeline_time_sql()
                for scope, bot_clause, params in [
                    ("private", "", ("private", "sess-0", "2026-11-01T00:00:00+00:00", 24)),
                    (
                        "group",
                        " AND (bot_id=? OR bot_id='')",
                        ("group", "sess-1", "2026-11-01T00:00:00+00:00", "bot-a", 24),
                    ),
                ]:
                    plan = _explain_details(
                        store,
                        f"""
                        SELECT * FROM timeline
                        WHERE scope=?
                          AND session_id!=?
                          AND {event_time_sql} >= julianday(?)
                          AND event_type IN ('user_message', 'bot_response'){bot_clause}
                        ORDER BY {event_time_sql} DESC, created_at DESC, id DESC
                        LIMIT ?
                        """,
                        params,
                    )
                    self.assertTrue(
                        any("SEARCH timeline USING INDEX idx_timeline_scope_event_time" in d for d in plan),
                        f"Cross-window query for scope={scope} did not use idx_timeline_scope_event_time: {plan}",
                    )
                    self.assertFalse(
                        any("USE TEMP B-TREE FOR ORDER BY" in d for d in plan),
                        f"Cross-window query for scope={scope} still used TEMP B-TREE: {plan}",
                    )
            finally:
                store.close()

    def test_recent_cross_window_timeline_matches_full_scan_and_uses_timeline_read_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.db"
            store = MemoryStore(db_path)
            store.initialize()
            try:
                rows_to_insert = [
                    ("tl-1", "user_message", "qq:FriendMessage:u_curr", "private", "u_curr", "bot", "当前会话消息", "", "2026-11-18T05:00:00+00:00", "2026-11-18T05:00:00+00:00"),
                    ("tl-2", "user_message", "qq:FriendMessage:u_other1", "private", "u_other1", "bot", "其他私聊消息1", "bot-a", "2026-11-18T04:00:00+00:00", "2026-11-18T04:00:00+00:00"),
                    ("tl-3", "bot_response", "qq:FriendMessage:u_other2", "private", "bot", "u_other2", "其他私聊回复空occurred", "", "", "2026-11-18T04:30:00+00:00"),
                    ("tl-4", "system_note", "qq:FriendMessage:u_other2", "private", "u_other2", "bot", "非对话事件应排除", "bot-a", "2026-11-18T06:00:00+00:00", "2026-11-18T06:00:00+00:00"),
                    ("tl-5", "user_message", "qq:FriendMessage:u_other3", "private", "u_other3", "bot", "其他bot消息应隔离", "bot-b", "2026-11-18T05:30:00+00:00", "2026-11-18T05:30:00+00:00"),
                    ("tl-6", "user_message", "qq:FriendMessage:u_old", "private", "u_old", "bot", "过期窗口外消息", "", "2026-11-10T00:00:00+00:00", "2026-11-10T00:00:00+00:00"),
                    ("tl-7", "user_message", "qq:GroupMessage:g_other1", "group", "u1", "bot", "群聊跨窗口1", "bot-a", "2026-11-18T03:00:00+00:00", "2026-11-18T03:00:00+00:00"),
                    ("tl-8", "bot_response", "qq:GroupMessage:g_other2", "group", "bot", "g_other2", "群聊跨窗口2", "", "2026-11-18T03:00:00+00:00", "2026-11-18T03:01:00+00:00"),
                    ("tl-9", "user_message", "qq:GroupMessage:g_curr", "group", "u2", "bot", "当前群会话消息", "bot-a", "2026-11-18T05:00:00+00:00", "2026-11-18T05:00:00+00:00"),
                ]
                store._conn.executemany(
                    """
                    INSERT INTO timeline(
                        id, event_type, session_id, scope, subject_id, object_id,
                        content, metadata, message_id, dedupe_key,
                        occurred_at, created_at, summarized_at,
                        retention_class, import_batch_id, source_sequence, bot_id
                    )
                    VALUES(?,?,?,?,?,?,?,'{}','','',?,?,'','normal','',0,?)
                    """,
                    [
                        (rid, etype, sess, sc, subj, obj, content, occ, cre, bid)
                        for rid, etype, sess, sc, subj, obj, content, bid, occ, cre in rows_to_insert
                    ],
                )
                store._conn.commit()

                event_time_sql = _timeline_time_sql()

                def full_scan_reference(
                    scope: str,
                    current_session_id: str,
                    since_at: str,
                    limit: int,
                    bot_id: str = "",
                ) -> list[dict]:
                    # `+scope` suppresses idx_timeline_scope_event_time to force a baseline scan
                    bot_clause, bot_params = store._bot_scope_clause("bot_id", bot_id)
                    rows = store._conn.execute(
                        f"""
                        SELECT * FROM timeline
                        WHERE +scope=?
                          AND session_id!=?
                          AND {event_time_sql} >= julianday(?)
                          AND event_type IN ('user_message', 'bot_response'){bot_clause}
                        ORDER BY {event_time_sql} DESC, created_at DESC, id DESC
                        LIMIT ?
                        """,
                        (scope, current_session_id, since_at, *bot_params, limit),
                    ).fetchall()
                    return [dict(r) for r in rows]

                cases = [
                    ("private", "qq:FriendMessage:u_curr", "2026-11-17T00:00:00+00:00", 10, ""),
                    ("private", "qq:FriendMessage:u_curr", "2026-11-17T00:00:00+00:00", 10, "bot-a"),
                    ("private", "qq:FriendMessage:u_curr", "2026-11-17T00:00:00+00:00", 1, "bot-a"),
                    ("group", "qq:GroupMessage:g_curr", "2026-11-17T00:00:00+00:00", 10, "bot-a"),
                    ("group", "qq:GroupMessage:g_curr", "2026-11-19T00:00:00+00:00", 10, "bot-a"),
                ]
                for args in cases:
                    expected = full_scan_reference(*args)
                    actual = store._recent_cross_window_timeline_sync(*args)
                    self.assertEqual(expected, actual, f"Cross-window mismatch for args={args}")

                self.assertIsNotNone(store._timeline_read_conn)

                # Must NOT block on main write lock self._lock
                worker_result: list[dict] = []
                worker_done = threading.Event()

                def run_query() -> None:
                    try:
                        worker_result.extend(
                            store._recent_cross_window_timeline_sync(
                                "private", "qq:FriendMessage:u_curr", "2026-11-17T00:00:00+00:00", 10, "bot-a"
                            )
                        )
                    finally:
                        worker_done.set()

                with store._lock:
                    t = threading.Thread(target=run_query, daemon=True)
                    t.start()
                    self.assertTrue(
                        worker_done.wait(timeout=2.0),
                        "_recent_cross_window_timeline_sync blocked on self._lock instead of _timeline_read_lock",
                    )
                t.join(timeout=1.0)
                self.assertEqual([r["id"] for r in worker_result], ["tl-3", "tl-2"])

                # Must synchronize on _timeline_read_lock
                lock_done = threading.Event()
                with store._timeline_read_lock:
                    t2 = threading.Thread(
                        target=lambda: (
                            store._recent_cross_window_timeline_sync(
                                "private", "qq:FriendMessage:u_curr", "2026-11-17T00:00:00+00:00", 10, "bot-a"
                            ),
                            lock_done.set(),
                        ),
                        daemon=True,
                    )
                    t2.start()
                    self.assertFalse(
                        lock_done.wait(timeout=0.1),
                        "_recent_cross_window_timeline_sync did not acquire _timeline_read_lock",
                    )
                self.assertTrue(lock_done.wait(timeout=2.0))
                t2.join(timeout=1.0)

                # Read-only store must continue reusing main _conn/_lock
                ro_store = MemoryStore(db_path, read_only=True)
                ro_store.initialize()
                try:
                    ro_actual = ro_store._recent_cross_window_timeline_sync(
                        "private", "qq:FriendMessage:u_curr", "2026-11-17T00:00:00+00:00", 10, "bot-a"
                    )
                    self.assertEqual([r["id"] for r in ro_actual], ["tl-3", "tl-2"])
                    self.assertIsNone(ro_store._timeline_read_conn)
                    self.assertEqual(ro_store._timeline_read_connection(), (ro_store._conn, ro_store._lock))
                finally:
                    ro_store.close()
            finally:
                store.close()

    def test_cached_from_row_light_strict_equivalence_and_non_trigger_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                rec = _make_memory(
                    "cache-eq-1",
                    "缓存等价性测试记忆",
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    subject_id="u1",
                    tags=["  alpha  ", "beta", ""],
                    importance=0.82,
                    occurred_at="2026-11-18T02:00:00+00:00",
                )
                rec.metadata = {
                    "nested": {"k": "v", "nums": [1, 2, 3]},
                    "source_turn": 42,
                    "notes": "x" * 256,
                }
                rec.ensure_defaults()
                store._insert_memory_sync(rec)

                rev = store._memory_revision_sync()
                row = store._conn.execute("SELECT * FROM memories WHERE id=?", ("cache-eq-1",)).fetchone()
                expected_cold = MemoryRecord.from_row_light(row)
                actual_cold = store._cached_from_row_light(row, revision=rev)
                self.assertEqual(expected_cold, actual_cold)

                actual_warm = store._cached_from_row_light(row, revision=rev)
                self.assertEqual(expected_cold, actual_warm)

                # mark_injected and mark_accessed update counters WITHOUT bumping retrieval_revision
                store._mark_injected_sync(["cache-eq-1"], when="2026-11-18T03:00:00+00:00")
                store._mark_accessed_sync(["cache-eq-1"])
                self.assertEqual(rev, store._memory_revision_sync())

                updated_row = store._conn.execute("SELECT * FROM memories WHERE id=?", ("cache-eq-1",)).fetchone()
                expected_after = MemoryRecord.from_row_light(updated_row)
                actual_after = store._cached_from_row_light(updated_row, revision=rev)
                self.assertEqual(expected_after, actual_after)
                self.assertEqual(actual_after.injection_count, 1)
                self.assertEqual(actual_after.last_injected_at, "2026-11-18T03:00:00+00:00")
                self.assertEqual(actual_after.access_count, 2)
                self.assertAlmostEqual(actual_after.reinforcement_score, 0.035, places=6)
            finally:
                store.close()

    def test_cached_from_row_light_invalidation_and_mutation_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                rec = _make_memory(
                    "cache-inv-1",
                    "缓存失效与隔离测试",
                    tags=["tag_a"],
                )
                rec.metadata = {"key": "initial"}
                rec.ensure_defaults()
                store._insert_memory_sync(rec)

                rev1 = store._memory_revision_sync()
                row1 = store._conn.execute("SELECT * FROM memories WHERE id=?", ("cache-inv-1",)).fetchone()

                # Mutating returned cold & warm records must never pollute cached template
                cold_res = store._cached_from_row_light(row1, revision=rev1)
                cold_res.metadata["polluted"] = True
                cold_res.tags.append("polluted_tag")

                warm_res = store._cached_from_row_light(row1, revision=rev1)
                self.assertNotIn("polluted", warm_res.metadata)
                self.assertEqual(warm_res.tags, ["tag_a"])
                warm_res.metadata["polluted_2"] = True
                warm_res.tags.append("polluted_tag_2")

                warm_res_2 = store._cached_from_row_light(row1, revision=rev1)
                self.assertEqual(warm_res_2.metadata.get("key"), "initial")
                self.assertNotIn("polluted", warm_res_2.metadata)
                self.assertNotIn("polluted_2", warm_res_2.metadata)
                self.assertEqual(warm_res_2.tags, ["tag_a"])

                # Changing metadata/tags/updated_at without bumping revision must still re-parse
                row_meta_changed = dict(row1)
                row_meta_changed["metadata"] = json.dumps({"key": "meta_changed"})
                parsed_meta = store._cached_from_row_light(row_meta_changed, revision=rev1)
                self.assertEqual(parsed_meta.metadata["key"], "meta_changed")

                row_tags_changed = dict(row_meta_changed)
                row_tags_changed["tags"] = json.dumps(["tag_b", "tag_c"])
                parsed_tags = store._cached_from_row_light(row_tags_changed, revision=rev1)
                self.assertEqual(parsed_tags.tags, ["tag_b", "tag_c"])

                row_upd_changed = dict(row_tags_changed)
                row_upd_changed["updated_at"] = "2026-11-18T09:99:99+00:00"
                row_upd_changed["content"] = "新内容不改meta"
                parsed_upd = store._cached_from_row_light(row_upd_changed, revision=rev1)
                self.assertEqual(parsed_upd.content, "新内容不改meta")

                # Real DB update bumps retrieval_revision and clears whole cache
                store._conn.execute(
                    "UPDATE memories SET content=? WHERE id=?",
                    ("数据库更新后内容", "cache-inv-1"),
                )
                store._conn.commit()
                rev2 = store._memory_revision_sync()
                self.assertNotEqual(rev1, rev2)
                row2 = store._conn.execute("SELECT * FROM memories WHERE id=?", ("cache-inv-1",)).fetchone()
                parsed_rev2 = store._cached_from_row_light(row2, revision=rev2)
                self.assertEqual(parsed_rev2.content, "数据库更新后内容")
                self.assertEqual(parsed_rev2.metadata["key"], "initial")
            finally:
                store.close()

    def test_cached_from_row_light_bounded_capacity_and_candidate_bundle_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            try:
                # 1. Verify bounded eviction at 16384 entries
                for i in range(16385):
                    fake_row = {
                        "id": f"fake-{i}",
                        "memory_type": "observation",
                        "content": f"c-{i}",
                        "metadata": "{}",
                        "tags": "[]",
                        "updated_at": "2026-11-18T00:00:00+00:00",
                    }
                    store._cached_from_row_light(fake_row, revision="bound-test")
                self.assertEqual(len(store._record_light_cache), 16384)
                self.assertNotIn("fake-0", store._record_light_cache)
                self.assertIn("fake-16384", store._record_light_cache)

                # 2. Verify candidate bundle uses cache on round 2+, drops parse work,
                # and matches MemoryRecord.from_row_light exactly.
                large_meta = {"payload": "x" * 2048, "items": list(range(30))}
                for idx in range(120):
                    rec = _make_memory(
                        f"bundle-{idx:03d}",
                        f"候选缓存测试 关键词alpha {idx}",
                        scope="private",
                        session_id="qq:FriendMessage:u_bundle",
                        subject_id="u_bundle",
                        tags=["bundle_tag", f"t_{idx % 5}"],
                        importance=0.4 + (idx % 5) * 0.1,
                        occurred_at=f"2026-11-18T01:{idx % 60:02d}:00+00:00",
                    )
                    rec.metadata = dict(large_meta, idx=idx)
                    rec.ensure_defaults()
                    store._insert_memory_sync(rec)

                bundle_kwargs = dict(
                    materialize_limit=200,
                    current_window={
                        "scope": "private",
                        "session_id": "qq:FriendMessage:u_bundle",
                        "user_id": "u_bundle",
                        "group_id": "",
                        "limit": 100,
                    },
                    fts_terms=["关键词alpha"],
                    fts_limit=100,
                    keyword_terms=["关键词alpha"],
                    keyword_limit=100,
                    keyword_fallback_min_fts=10,
                    time_window=None,
                    include_pending=False,
                )

                with patch.object(
                    MemoryRecord,
                    "from_row_light",
                    wraps=MemoryRecord.from_row_light,
                ) as spy_from_row:
                    round1 = store._list_retrieval_candidate_bundle_sync(**bundle_kwargs)
                    calls_round1 = spy_from_row.call_count
                    unique_round1 = {
                        rec.id
                        for key in (
                            "ranked_candidates",
                            "current_window_candidates",
                            "fts_candidates",
                            "keyword_candidates",
                            "time_window_candidates",
                        )
                        for rec in round1[key]
                    }
                    total_round1 = sum(
                        len(round1[key])
                        for key in (
                            "ranked_candidates",
                            "current_window_candidates",
                            "fts_candidates",
                            "keyword_candidates",
                            "time_window_candidates",
                        )
                    )
                    self.assertEqual(calls_round1, len(unique_round1))
                    self.assertGreater(total_round1, calls_round1)

                    round2 = store._list_retrieval_candidate_bundle_sync(**bundle_kwargs)
                    calls_round2 = spy_from_row.call_count - calls_round1
                    self.assertEqual(calls_round2, 0)

                self.assertLessEqual(round2["_timing"]["parse_ms"], round1["_timing"]["parse_ms"])

                # Exact equivalence against direct MemoryRecord.from_row_light
                conn, _ = store._read_connection_for_bundle()
                direct_ranked = [
                    MemoryRecord.from_row_light(r)
                    for r in store._materialized_candidate_rows(conn, 200, False)
                ]
                direct_cw = [
                    MemoryRecord.from_row_light(r)
                    for r in store._current_window_candidate_rows(
                        conn, "private", "qq:FriendMessage:u_bundle", "u_bundle", "", 100, False, "", ""
                    )
                ]
                direct_fts = [
                    MemoryRecord.from_row_light(r)
                    for r in store._fts_candidate_rows(conn, ["关键词alpha"], 100, False)
                ]
                self.assertEqual(round2["ranked_candidates"], direct_ranked)
                self.assertEqual(round2["current_window_candidates"], direct_cw)
                self.assertEqual(round2["fts_candidates"], direct_fts)

                # Missing retrieval_revision table must degrade cleanly without raising
                store._conn.execute("DROP TABLE IF EXISTS retrieval_revision")
                store._conn.commit()
                round3 = store._list_retrieval_candidate_bundle_sync(**bundle_kwargs)
                self.assertEqual(round3["ranked_candidates"], direct_ranked)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
