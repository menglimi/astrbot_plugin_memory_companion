"""Rebuildable semantic source projections and their independent change queue.

The module stores references, spans, versions, and optional vectors. It never
stores a second copy of source text; callers must revalidate source authority.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
import json
import sqlite3
import struct
from typing import Any, Callable

from .source_evidence import message_source_version


FRAGMENT_TARGET_CHARS = 600
FRAGMENT_OVERLAP_CHARS = 80
FRAGMENT_PROFILE = "unicode-codepoint-overlap-v1"
_TRACKED_GENERATION_STATES_SQL = "('building','ready','paused')"
_SOURCE_EVENT_SQL = "('user_message','bot_response')"
_SOURCE_PARTITION_FIELDS = (
    "scope", "session_id", "object_id", "owner_bot_id", "platform",
    "persona_id", "participant_user_id",
)


def split_source_fragments(
    text: str,
    *,
    target_chars: int = FRAGMENT_TARGET_CHARS,
    overlap_chars: int = FRAGMENT_OVERLAP_CHARS,
) -> list[dict[str, Any]]:
    """Split readable text by Unicode code-point offsets, preserving the tail."""
    if not isinstance(text, str):
        raise TypeError("source_text_must_be_string")
    if isinstance(target_chars, bool) or not isinstance(target_chars, int) or target_chars < 1:
        raise ValueError("invalid_fragment_target")
    if isinstance(overlap_chars, bool) or not isinstance(overlap_chars, int) or not 0 <= overlap_chars < target_chars:
        raise ValueError("invalid_fragment_overlap")
    if not text:
        return []

    step = target_chars - overlap_chars
    fragments = []
    for start in range(0, len(text), step):
        end = min(len(text), start + target_chars)
        fragments.append({"char_start": start, "char_end": end, "text": text[start:end]})
        if end == len(text):
            break
    return fragments


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _source_snapshot(alias: str) -> str:
    return f"""json_object(
        'source_id',{alias}.id,'event_type',{alias}.event_type,'scope',{alias}.scope,
        'session_id',{alias}.session_id,'subject_id',{alias}.subject_id,'object_id',{alias}.object_id,
        'owner_bot_id',CASE WHEN json_valid({alias}.metadata) THEN COALESCE(json_extract({alias}.metadata,'$.owner_bot_id'),'') ELSE '' END,
        'bot_id',CASE WHEN json_valid({alias}.metadata) THEN COALESCE(json_extract({alias}.metadata,'$.bot_id'),'') ELSE '' END,
        'platform',CASE WHEN json_valid({alias}.metadata) THEN COALESCE(json_extract({alias}.metadata,'$.platform'),'') ELSE '' END,
        'persona_id',CASE WHEN json_valid({alias}.metadata) THEN COALESCE(json_extract({alias}.metadata,'$.persona_id'),'') ELSE '' END,
        'participant_user_id',CASE WHEN json_valid({alias}.metadata) THEN COALESCE(json_extract({alias}.metadata,'$.participant_user_id'),'') ELSE '' END,
        'occurred_at',{alias}.occurred_at,'created_at',{alias}.created_at
    )"""


def initialize(conn: sqlite3.Connection) -> None:
    """Create semantic projection tables and source-change triggers."""
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS source_semantic_revision (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            revision INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO source_semantic_revision(singleton,revision) VALUES(1,0);

        CREATE TABLE IF NOT EXISTS source_semantic_generations (
            generation TEXT PRIMARY KEY,
            config_hash TEXT NOT NULL,
            config_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('building','ready','paused','failed','retired')),
            base_sequence INTEGER NOT NULL,
            scan_cursor TEXT NOT NULL DEFAULT '',
            checkpoint_sequence INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_semantic_documents (
            document_id TEXT PRIMARY KEY,
            generation TEXT NOT NULL,
            view_kind TEXT NOT NULL CHECK(view_kind IN ('fragment','window')),
            anchor_source_id TEXT NOT NULL,
            anchor_source_version TEXT NOT NULL,
            char_start INTEGER NOT NULL CHECK(char_start>=0),
            char_end INTEGER NOT NULL CHECK(char_end>=char_start),
            input_hash TEXT NOT NULL,
            source_change_sequence INTEGER NOT NULL,
            vector_blob BLOB,
            vector_dimension INTEGER,
            state TEXT NOT NULL CHECK(state IN ('pending','ready','stale')),
            updated_at TEXT NOT NULL,
            UNIQUE(generation,anchor_source_id,view_kind,char_start,char_end),
            FOREIGN KEY(generation) REFERENCES source_semantic_generations(generation) ON DELETE CASCADE,
            CHECK((vector_blob IS NULL AND vector_dimension IS NULL) OR
                  (vector_blob IS NOT NULL AND vector_dimension>0))
        );
        CREATE INDEX IF NOT EXISTS idx_source_semantic_document_anchor
            ON source_semantic_documents(generation,anchor_source_id,view_kind);

        CREATE TABLE IF NOT EXISTS source_semantic_dependencies (
            document_id TEXT NOT NULL,
            dependency_order INTEGER NOT NULL CHECK(dependency_order>=0),
            source_id TEXT NOT NULL,
            source_version TEXT NOT NULL,
            char_start INTEGER NOT NULL CHECK(char_start>=0),
            char_end INTEGER NOT NULL CHECK(char_end>=char_start),
            role TEXT NOT NULL CHECK(role IN ('anchor','context')),
            PRIMARY KEY(document_id,dependency_order),
            FOREIGN KEY(document_id) REFERENCES source_semantic_documents(document_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_source_semantic_dependency_source
            ON source_semantic_dependencies(source_id,source_version,document_id);

        CREATE TABLE IF NOT EXISTS source_semantic_dirty (
            generation TEXT NOT NULL,
            source_id TEXT NOT NULL,
            change_sequence INTEGER NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('upsert','delete')),
            old_present INTEGER NOT NULL CHECK(old_present IN (0,1)),
            old_scope TEXT,
            old_session_id TEXT,
            old_event_type TEXT,
            old_subject_id TEXT,
            old_object_id TEXT,
            old_owner_bot_id TEXT,
            old_bot_id TEXT,
            old_platform TEXT,
            old_persona_id TEXT,
            old_participant_user_id TEXT,
            old_occurred_at TEXT,
            old_created_at TEXT,
            new_source_id TEXT,
            new_present INTEGER NOT NULL CHECK(new_present IN (0,1)),
            new_scope TEXT,
            new_session_id TEXT,
            new_event_type TEXT,
            new_subject_id TEXT,
            new_object_id TEXT,
            new_owner_bot_id TEXT,
            new_bot_id TEXT,
            new_platform TEXT,
            new_persona_id TEXT,
            new_participant_user_id TEXT,
            new_occurred_at TEXT,
            new_created_at TEXT,
            PRIMARY KEY(generation,source_id),
            FOREIGN KEY(generation) REFERENCES source_semantic_generations(generation) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_source_semantic_dirty_position
            ON source_semantic_dirty(generation,old_scope,old_session_id,old_occurred_at,old_created_at);
        CREATE INDEX IF NOT EXISTS idx_source_semantic_dirty_new_position
            ON source_semantic_dirty(generation,new_scope,new_session_id,new_occurred_at,new_created_at);

        CREATE TABLE IF NOT EXISTS source_semantic_order_changes (
            generation TEXT NOT NULL,
            change_sequence INTEGER NOT NULL,
            source_id TEXT NOT NULL,
            old_present INTEGER NOT NULL CHECK(old_present IN (0,1)),
            old_snapshot TEXT NOT NULL DEFAULT '{{}}',
            new_present INTEGER NOT NULL CHECK(new_present IN (0,1)),
            new_snapshot TEXT NOT NULL DEFAULT '{{}}',
            PRIMARY KEY(generation,change_sequence,source_id),
            FOREIGN KEY(generation) REFERENCES source_semantic_generations(generation) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_source_semantic_order_sequence
            ON source_semantic_order_changes(generation,change_sequence,source_id);

        CREATE TRIGGER IF NOT EXISTS trg_source_semantic_generation_config_immutable
        BEFORE UPDATE OF config_hash,config_json ON source_semantic_generations
        WHEN old.config_hash IS NOT new.config_hash OR old.config_json IS NOT new.config_json
        BEGIN
            SELECT RAISE(ABORT,'semantic_generation_config_immutable');
        END;

        DROP TRIGGER IF EXISTS trg_source_semantic_timeline_ai;
        CREATE TRIGGER trg_source_semantic_timeline_ai AFTER INSERT ON timeline
        WHEN new.event_type IN {_SOURCE_EVENT_SQL}
          AND EXISTS (SELECT 1 FROM source_semantic_generations WHERE state IN {_TRACKED_GENERATION_STATES_SQL})
        BEGIN
            UPDATE source_semantic_revision SET revision=revision+1 WHERE singleton=1;
            UPDATE source_semantic_generations SET state='building',updated_at=datetime('now')
            WHERE state='ready';
            UPDATE source_semantic_documents SET state='stale',updated_at=datetime('now')
            WHERE state!='stale'
              AND generation IN (SELECT generation FROM source_semantic_generations
                                 WHERE state IN {_TRACKED_GENERATION_STATES_SQL})
              AND (anchor_source_id=new.id OR document_id IN (
                    SELECT document_id FROM source_semantic_dependencies WHERE source_id=new.id));
            INSERT INTO source_semantic_dirty (
                generation,source_id,change_sequence,operation,old_present,
                new_source_id,new_present,new_scope,new_session_id,new_event_type,
                new_subject_id,new_object_id,new_owner_bot_id,new_bot_id,new_platform,
                new_persona_id,new_participant_user_id,new_occurred_at,new_created_at
            )
            SELECT g.generation,new.id,r.revision,'upsert',0,
                new.id,1,new.scope,new.session_id,new.event_type,new.subject_id,new.object_id,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.owner_bot_id'),'') ELSE '' END,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.bot_id'),'') ELSE '' END,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.platform'),'') ELSE '' END,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.persona_id'),'') ELSE '' END,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.participant_user_id'),'') ELSE '' END,
                new.occurred_at,new.created_at
            FROM source_semantic_generations g CROSS JOIN source_semantic_revision r
            WHERE g.state IN {_TRACKED_GENERATION_STATES_SQL} AND r.singleton=1
            ON CONFLICT(generation,source_id) DO UPDATE SET
                change_sequence=excluded.change_sequence,operation='upsert',new_source_id=excluded.new_source_id,
                new_present=1,new_scope=excluded.new_scope,new_session_id=excluded.new_session_id,
                new_event_type=excluded.new_event_type,new_subject_id=excluded.new_subject_id,
                new_object_id=excluded.new_object_id,new_owner_bot_id=excluded.new_owner_bot_id,
                new_bot_id=excluded.new_bot_id,new_platform=excluded.new_platform,
                new_persona_id=excluded.new_persona_id,new_participant_user_id=excluded.new_participant_user_id,
                new_occurred_at=excluded.new_occurred_at,new_created_at=excluded.new_created_at;
            INSERT INTO source_semantic_order_changes(
                generation,change_sequence,source_id,old_present,old_snapshot,new_present,new_snapshot
            )
            SELECT g.generation,r.revision,new.id,0,'{{}}',1,{_source_snapshot('new')}
            FROM source_semantic_generations g CROSS JOIN source_semantic_revision r
            WHERE g.state IN {_TRACKED_GENERATION_STATES_SQL} AND r.singleton=1;
        END;

        DROP TRIGGER IF EXISTS trg_source_semantic_timeline_ad;
        CREATE TRIGGER trg_source_semantic_timeline_ad AFTER DELETE ON timeline
        WHEN old.event_type IN {_SOURCE_EVENT_SQL}
          AND EXISTS (SELECT 1 FROM source_semantic_generations WHERE state IN {_TRACKED_GENERATION_STATES_SQL})
        BEGIN
            UPDATE source_semantic_revision SET revision=revision+1 WHERE singleton=1;
            UPDATE source_semantic_generations SET state='building',updated_at=datetime('now')
            WHERE state='ready';
            UPDATE source_semantic_documents SET state='stale',updated_at=datetime('now')
            WHERE state!='stale'
              AND generation IN (SELECT generation FROM source_semantic_generations
                                 WHERE state IN {_TRACKED_GENERATION_STATES_SQL})
              AND (anchor_source_id=old.id OR document_id IN (
                    SELECT document_id FROM source_semantic_dependencies WHERE source_id=old.id));
            INSERT INTO source_semantic_dirty (
                generation,source_id,change_sequence,operation,old_present,
                old_scope,old_session_id,old_event_type,old_subject_id,old_object_id,
                old_owner_bot_id,old_bot_id,old_platform,old_persona_id,old_participant_user_id,
                old_occurred_at,old_created_at,new_source_id,new_present
            )
            SELECT g.generation,old.id,r.revision,'delete',1,
                old.scope,old.session_id,old.event_type,old.subject_id,old.object_id,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.owner_bot_id'),'') ELSE '' END,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.bot_id'),'') ELSE '' END,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.platform'),'') ELSE '' END,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.persona_id'),'') ELSE '' END,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.participant_user_id'),'') ELSE '' END,
                old.occurred_at,old.created_at,'',0
            FROM source_semantic_generations g CROSS JOIN source_semantic_revision r
            WHERE g.state IN {_TRACKED_GENERATION_STATES_SQL} AND r.singleton=1
            ON CONFLICT(generation,source_id) DO UPDATE SET
                change_sequence=excluded.change_sequence,operation='delete',new_source_id='',new_present=0,
                new_scope=NULL,new_session_id=NULL,new_event_type=NULL,new_subject_id=NULL,new_object_id=NULL,
                new_owner_bot_id=NULL,new_bot_id=NULL,new_platform=NULL,new_persona_id=NULL,
                new_participant_user_id=NULL,new_occurred_at=NULL,new_created_at=NULL;
            INSERT INTO source_semantic_order_changes(
                generation,change_sequence,source_id,old_present,old_snapshot,new_present,new_snapshot
            )
            SELECT g.generation,r.revision,old.id,1,{_source_snapshot('old')},0,'{{}}'
            FROM source_semantic_generations g CROSS JOIN source_semantic_revision r
            WHERE g.state IN {_TRACKED_GENERATION_STATES_SQL} AND r.singleton=1;
        END;

        DROP TRIGGER IF EXISTS trg_source_semantic_timeline_au;
        CREATE TRIGGER trg_source_semantic_timeline_au
        AFTER UPDATE OF id,event_type,scope,session_id,subject_id,object_id,content,metadata,occurred_at,created_at ON timeline
        WHEN (old.event_type IN {_SOURCE_EVENT_SQL} OR new.event_type IN {_SOURCE_EVENT_SQL})
          AND (old.id IS NOT new.id OR old.event_type IS NOT new.event_type OR old.scope IS NOT new.scope
            OR old.session_id IS NOT new.session_id OR old.subject_id IS NOT new.subject_id
            OR old.object_id IS NOT new.object_id OR old.content IS NOT new.content
            OR old.metadata IS NOT new.metadata OR old.occurred_at IS NOT new.occurred_at
            OR old.created_at IS NOT new.created_at)
          AND EXISTS (SELECT 1 FROM source_semantic_generations WHERE state IN {_TRACKED_GENERATION_STATES_SQL})
        BEGIN
            UPDATE source_semantic_revision SET revision=revision+1 WHERE singleton=1;
            UPDATE source_semantic_generations SET state='building',updated_at=datetime('now')
            WHERE state='ready';
            UPDATE source_semantic_documents SET state='stale',updated_at=datetime('now')
            WHERE state!='stale'
              AND generation IN (SELECT generation FROM source_semantic_generations
                                 WHERE state IN {_TRACKED_GENERATION_STATES_SQL})
              AND (anchor_source_id IN (old.id,new.id) OR document_id IN (
                    SELECT document_id FROM source_semantic_dependencies WHERE source_id IN (old.id,new.id)));
            INSERT INTO source_semantic_dirty (
                generation,source_id,change_sequence,operation,old_present,
                old_scope,old_session_id,old_event_type,old_subject_id,old_object_id,
                old_owner_bot_id,old_bot_id,old_platform,old_persona_id,old_participant_user_id,
                old_occurred_at,old_created_at,new_source_id,new_present,new_scope,new_session_id,
                new_event_type,new_subject_id,new_object_id,new_owner_bot_id,new_bot_id,new_platform,
                new_persona_id,new_participant_user_id,new_occurred_at,new_created_at
            )
            SELECT g.generation,old.id,r.revision,
                CASE WHEN new.event_type IN {_SOURCE_EVENT_SQL} THEN 'upsert' ELSE 'delete' END,
                CASE WHEN old.event_type IN {_SOURCE_EVENT_SQL} THEN 1 ELSE 0 END,
                old.scope,old.session_id,old.event_type,old.subject_id,old.object_id,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.owner_bot_id'),'') ELSE '' END,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.bot_id'),'') ELSE '' END,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.platform'),'') ELSE '' END,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.persona_id'),'') ELSE '' END,
                CASE WHEN json_valid(old.metadata) THEN COALESCE(json_extract(old.metadata,'$.participant_user_id'),'') ELSE '' END,
                old.occurred_at,old.created_at,new.id,
                CASE WHEN new.event_type IN {_SOURCE_EVENT_SQL} THEN 1 ELSE 0 END,
                new.scope,new.session_id,new.event_type,new.subject_id,new.object_id,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.owner_bot_id'),'') ELSE '' END,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.bot_id'),'') ELSE '' END,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.platform'),'') ELSE '' END,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.persona_id'),'') ELSE '' END,
                CASE WHEN json_valid(new.metadata) THEN COALESCE(json_extract(new.metadata,'$.participant_user_id'),'') ELSE '' END,
                new.occurred_at,new.created_at
            FROM source_semantic_generations g CROSS JOIN source_semantic_revision r
            WHERE g.state IN {_TRACKED_GENERATION_STATES_SQL} AND r.singleton=1
            ON CONFLICT(generation,source_id) DO UPDATE SET
                change_sequence=excluded.change_sequence,operation=excluded.operation,
                new_source_id=excluded.new_source_id,new_present=excluded.new_present,
                new_scope=excluded.new_scope,new_session_id=excluded.new_session_id,
                new_event_type=excluded.new_event_type,new_subject_id=excluded.new_subject_id,
                new_object_id=excluded.new_object_id,new_owner_bot_id=excluded.new_owner_bot_id,
                new_bot_id=excluded.new_bot_id,new_platform=excluded.new_platform,
                new_persona_id=excluded.new_persona_id,new_participant_user_id=excluded.new_participant_user_id,
                new_occurred_at=excluded.new_occurred_at,new_created_at=excluded.new_created_at;
            INSERT INTO source_semantic_order_changes(
                generation,change_sequence,source_id,old_present,old_snapshot,new_present,new_snapshot
            )
            SELECT g.generation,r.revision,old.id,
                CASE WHEN old.event_type IN {_SOURCE_EVENT_SQL} THEN 1 ELSE 0 END,
                CASE WHEN old.event_type IN {_SOURCE_EVENT_SQL} THEN {_source_snapshot('old')} ELSE '{{}}' END,
                CASE WHEN new.event_type IN {_SOURCE_EVENT_SQL} THEN 1 ELSE 0 END,
                CASE WHEN new.event_type IN {_SOURCE_EVENT_SQL} THEN {_source_snapshot('new')} ELSE '{{}}' END
            FROM source_semantic_generations g CROSS JOIN source_semantic_revision r
            WHERE g.state IN {_TRACKED_GENERATION_STATES_SQL} AND r.singleton=1;
        END;
    """)


def register_generation(
    conn: sqlite3.Connection,
    generation: str,
    configuration: Mapping[str, Any],
    *,
    created_at: str,
) -> int:
    """Start a generation after its caller records the full-scan plan."""
    required = {
        "provider_id", "model_revision", "dimensions", "distance_metric",
        "query_encoding", "document_encoding", "processing_version",
        "fragment_profile", "window_profile", "build_scope",
    }
    if not isinstance(generation, str) or not generation or len(generation) > 160:
        raise ValueError("invalid_semantic_generation")
    if not isinstance(configuration, Mapping) or not required.issubset(configuration):
        raise ValueError("semantic_generation_config_incomplete")
    dimensions = configuration.get("dimensions")
    if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions < 1:
        raise ValueError("semantic_generation_dimensions_invalid")
    _build_scope_matches(configuration.get("build_scope"), {}, {})
    config_json = _canonical_json(dict(configuration))
    config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
    history_backfill = configuration.get("history_backfill", True) is True
    row = conn.execute("SELECT revision FROM source_semantic_revision WHERE singleton=1").fetchone()
    if row is None:
        raise RuntimeError("source_semantic_schema_missing")
    base_sequence = int(row[0])
    try:
        conn.execute(
            """INSERT INTO source_semantic_generations
                (generation,config_hash,config_json,state,base_sequence,scan_cursor,
                 checkpoint_sequence,created_at,updated_at)
                VALUES (?,?,?,'building',?,?,?, ?,?)""",
            (generation, config_hash, config_json, base_sequence,
             '{"complete":true,"id":""}' if not history_backfill else "{}",
             base_sequence, created_at, created_at),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("semantic_generation_already_exists") from exc
    return base_sequence


def find_active_generation(conn: sqlite3.Connection, config_hash: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT * FROM source_semantic_generations
           WHERE config_hash=? AND state IN ('building','ready','paused')
           ORDER BY created_at DESC,generation DESC LIMIT 1""",
        (config_hash,),
    ).fetchone()
    return dict(row) if row is not None else None


def enqueue_semantic_source(
    conn: sqlite3.Connection,
    generation: str,
    source_id: str,
    *,
    authorize_source: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> bool:
    """Durably enqueue one current source without copying its body."""
    generation_row = _writable_generation(conn, generation)
    build_scope = _json_object(generation_row["config_json"]).get("build_scope")
    raw = conn.execute(
        "SELECT * FROM timeline WHERE id=? AND event_type IN " + _SOURCE_EVENT_SQL,
        (source_id,),
    ).fetchone()
    if raw is None:
        return False
    row = dict(raw)
    metadata = _json_object(row.get("metadata"))
    if (not _build_scope_matches(build_scope, row, metadata)
            or not _authorization_result(authorize_source, row, metadata)):
        return False
    revision = conn.execute(
        "SELECT revision FROM source_semantic_revision WHERE singleton=1",
    ).fetchone()
    if revision is None:
        raise RuntimeError("source_semantic_schema_missing")
    conn.execute(
        """INSERT OR IGNORE INTO source_semantic_dirty(
             generation,source_id,change_sequence,operation,old_present,
             new_source_id,new_present,new_scope,new_session_id,new_event_type,
             new_subject_id,new_object_id,new_owner_bot_id,new_bot_id,new_platform,
             new_persona_id,new_participant_user_id,new_occurred_at,new_created_at
           ) VALUES (?,?,?,'upsert',0,?,1,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (generation, source_id, int(revision[0]), source_id, row.get("scope"),
         row.get("session_id"), row.get("event_type"), row.get("subject_id"),
         row.get("object_id"), metadata.get("owner_bot_id", ""), metadata.get("bot_id", ""),
         metadata.get("platform", ""), metadata.get("persona_id", ""),
         metadata.get("participant_user_id", ""), row.get("occurred_at"), row.get("created_at")),
    )
    return True


def list_generations(
    conn: sqlite3.Connection,
    *,
    states: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return generation metadata without exposing source text."""
    allowed = {"building", "ready", "paused", "failed", "retired"}
    if states is None:
        rows = conn.execute(
            "SELECT * FROM source_semantic_generations ORDER BY created_at,generation"
        ).fetchall()
    else:
        requested = {str(state) for state in states}
        if not requested or not requested <= allowed:
            raise ValueError("semantic_generation_state_invalid")
        placeholders = ",".join("?" for _ in requested)
        rows = conn.execute(
            f"SELECT * FROM source_semantic_generations WHERE state IN ({placeholders}) "
            "ORDER BY created_at,generation",
            sorted(requested),
        ).fetchall()
    return [dict(row) for row in rows]


def generation_status(conn: sqlite3.Connection, generation: str) -> dict[str, Any]:
    """Expose bounded maintenance counters used by the worker and diagnostics."""
    row = conn.execute(
        "SELECT * FROM source_semantic_generations WHERE generation=?", (generation,)
    ).fetchone()
    if row is None:
        raise ValueError("semantic_generation_not_found")
    try:
        cursor = json.loads(row["scan_cursor"] or "{}")
    except (TypeError, ValueError):
        cursor = {}
    current = conn.execute(
        "SELECT revision FROM source_semantic_revision WHERE singleton=1"
    ).fetchone()
    counts = conn.execute(
        """SELECT
             SUM(CASE WHEN state='ready' THEN 1 ELSE 0 END) AS ready_documents,
             SUM(CASE WHEN state='pending' THEN 1 ELSE 0 END) AS pending_documents,
             SUM(CASE WHEN state='stale' THEN 1 ELSE 0 END) AS stale_documents,
             COUNT(*) AS document_count
           FROM source_semantic_documents WHERE generation=?""",
        (generation,),
    ).fetchone()
    dirty = conn.execute(
        "SELECT COUNT(*) FROM source_semantic_dirty WHERE generation=?", (generation,)
    ).fetchone()
    order_changes = conn.execute(
        "SELECT COUNT(*) FROM source_semantic_order_changes WHERE generation=?", (generation,)
    ).fetchone()
    return {
        "generation": generation,
        "state": row["state"],
        "config_hash": row["config_hash"],
        "base_sequence": int(row["base_sequence"]),
        "checkpoint_sequence": int(row["checkpoint_sequence"]),
        "source_revision": int(current[0]) if current is not None else None,
        "scan_complete": bool(isinstance(cursor, dict) and cursor.get("complete") is True),
        "scan_cursor": cursor.get("id", "") if isinstance(cursor, dict) else "",
        "dirty_count": int(dirty[0] or 0) if dirty is not None else 0,
        "order_change_count": int(order_changes[0] or 0) if order_changes is not None else 0,
        "document_count": int(counts["document_count"] or 0) if counts is not None else 0,
        "ready_documents": int(counts["ready_documents"] or 0) if counts is not None else 0,
        "pending_documents": int(counts["pending_documents"] or 0) if counts is not None else 0,
        "stale_documents": int(counts["stale_documents"] or 0) if counts is not None else 0,
    }


def pause_generation(
    conn: sqlite3.Connection,
    generation: str,
    *,
    updated_at: str,
) -> bool:
    """Pause a generation while keeping its change queue active."""
    cursor = conn.execute(
        """UPDATE source_semantic_generations SET state='paused',updated_at=?
           WHERE generation=? AND state IN ('building','ready')""",
        (updated_at, generation),
    )
    return cursor.rowcount == 1


def resume_generation(
    conn: sqlite3.Connection,
    generation: str,
    *,
    updated_at: str,
) -> bool:
    """Resume work; the next maintenance pass decides whether it is ready."""
    cursor = conn.execute(
        """UPDATE source_semantic_generations SET state='building',updated_at=?
           WHERE generation=? AND state='paused'""",
        (updated_at, generation),
    )
    return cursor.rowcount == 1


def retire_generation(
    conn: sqlite3.Connection,
    generation: str,
    *,
    updated_at: str,
) -> bool:
    """Retire a generation so in-flight results cannot be committed."""
    cursor = conn.execute(
        """UPDATE source_semantic_generations SET state='retired',updated_at=?
           WHERE generation=? AND state!='retired'""",
        (updated_at, generation),
    )
    return cursor.rowcount == 1


def mark_generation_ready(
    conn: sqlite3.Connection,
    generation: str,
    *,
    updated_at: str,
) -> dict[str, Any]:
    """Publish ready only after scan, order changes, dirty rows and documents settle."""
    row = conn.execute(
        "SELECT * FROM source_semantic_generations WHERE generation=?", (generation,)
    ).fetchone()
    if row is None:
        raise ValueError("semantic_generation_not_found")
    if row["state"] != "building":
        raise ValueError("semantic_generation_not_building")
    try:
        cursor = json.loads(row["scan_cursor"] or "{}")
    except (TypeError, ValueError):
        cursor = {}
    current = conn.execute(
        "SELECT revision FROM source_semantic_revision WHERE singleton=1"
    ).fetchone()
    config = _json_object(row["config_json"])
    blockers = {
        "scan_complete": config.get("history_backfill", True) is True
        and not (isinstance(cursor, dict) and cursor.get("complete") is True),
        "dirty_count": int(conn.execute(
            "SELECT COUNT(*) FROM source_semantic_dirty WHERE generation=?", (generation,)
        ).fetchone()[0] or 0),
        "order_change_count": int(conn.execute(
            "SELECT COUNT(*) FROM source_semantic_order_changes WHERE generation=?", (generation,)
        ).fetchone()[0] or 0),
        "pending_documents": int(conn.execute(
            "SELECT COUNT(*) FROM source_semantic_documents WHERE generation=? AND state='pending'",
            (generation,),
        ).fetchone()[0] or 0),
        "stale_documents": int(conn.execute(
            "SELECT COUNT(*) FROM source_semantic_documents WHERE generation=? AND state='stale'",
            (generation,),
        ).fetchone()[0] or 0),
    }
    if any(blockers.values()):
        return {"ready": False, "blockers": blockers}
    revision = int(current[0]) if current is not None else int(row["checkpoint_sequence"])
    updated = conn.execute(
        """UPDATE source_semantic_generations
           SET state='ready',checkpoint_sequence=?,updated_at=?
           WHERE generation=? AND state='building'""",
        (revision, updated_at, generation),
    )
    if updated.rowcount != 1:
        raise ValueError("semantic_generation_state_changed")
    return {"ready": True, "blockers": blockers, "source_revision": revision}


def remove_semantic_documents_for_source(
    conn: sqlite3.Connection,
    generation: str,
    source_id: str,
) -> int:
    """Remove projections whose anchor or dependency disappeared."""
    _writable_generation(conn, generation)
    cursor = conn.execute(
        """DELETE FROM source_semantic_documents
           WHERE generation=? AND (
             anchor_source_id=? OR document_id IN (
               SELECT document_id FROM source_semantic_dependencies WHERE source_id=?
             )
           )""",
        (generation, source_id, source_id),
    )
    return int(cursor.rowcount or 0)


def semantic_document_is_ready(
    conn: sqlite3.Connection,
    *,
    generation: str,
    view_kind: str,
    anchor_source_id: str,
    char_start: int,
    char_end: int,
    input_text: str,
    dependencies: Sequence[Mapping[str, Any]],
) -> bool:
    """Skip provider work only when the exact source projection already exists."""
    document_id = semantic_document_id(
        generation, anchor_source_id, view_kind, char_start, char_end,
    )
    input_hash = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    row = conn.execute(
        """SELECT input_hash,state FROM source_semantic_documents
           WHERE document_id=? AND generation=?""",
        (document_id, generation),
    ).fetchone()
    if row is None or row["state"] != "ready" or row["input_hash"] != input_hash:
        return False
    stored = conn.execute(
        """SELECT source_id,source_version,char_start,char_end,role
           FROM source_semantic_dependencies WHERE document_id=? ORDER BY dependency_order""",
        (document_id,),
    ).fetchall()
    expected = [
        (item.get("source_id"), item.get("source_version"), item.get("char_start"),
         item.get("char_end"), item.get("role"))
        for item in dependencies
    ]
    return [tuple(item) for item in stored] == expected


def prune_semantic_documents(
    conn: sqlite3.Connection,
    generation: str,
    anchor_source_id: str,
    keep_document_ids: Sequence[str],
) -> int:
    """Remove old or out-of-span projections after a source was fully rebuilt."""
    _writable_generation(conn, generation)
    keep = set(keep_document_ids)
    rows = conn.execute(
        """SELECT document_id FROM source_semantic_documents
           WHERE generation=? AND anchor_source_id=?""",
        (generation, anchor_source_id),
    ).fetchall()
    remove = [str(row[0]) for row in rows if str(row[0]) not in keep]
    if remove:
        conn.executemany(
            "DELETE FROM source_semantic_documents WHERE generation=? AND document_id=?",
            [(generation, document_id) for document_id in remove],
        )
    return len(remove)


def pack_semantic_vector(values: Sequence[float]) -> bytes:
    """Serialize a finite vector using the same stable float64 format as memory embeddings."""
    checked: list[float] = []
    for value in values:
        number = float(value)
        if number != number or number in {float("inf"), float("-inf")}:
            raise ValueError("semantic_vector_invalid")
        checked.append(number)
    if not checked:
        raise ValueError("semantic_vector_invalid")
    return struct.pack(f"<{len(checked)}d", *checked)


def acknowledge_dirty(
    conn: sqlite3.Connection, generation: str, source_id: str, change_sequence: int,
) -> bool:
    """Acknowledge only the exact dirty version processed by a worker."""
    state = conn.execute(
        "SELECT state FROM source_semantic_generations WHERE generation=?", (generation,),
    ).fetchone()
    if state is None or state[0] not in {"building", "ready"}:
        return False
    pending_order_change = conn.execute(
        """SELECT 1 FROM source_semantic_order_changes
           WHERE generation=? AND source_id=? AND change_sequence<=? LIMIT 1""",
        (generation, source_id, change_sequence),
    ).fetchone()
    if pending_order_change is not None:
        return False
    cursor = conn.execute(
        "DELETE FROM source_semantic_dirty WHERE generation=? AND source_id=? AND change_sequence=?",
        (generation, source_id, change_sequence),
    )
    return cursor.rowcount == 1


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        decoded = json.loads(value) if isinstance(value, str) else {}
    except (TypeError, ValueError):
        decoded = {}
    return decoded if isinstance(decoded, dict) else {}


def _build_scope_matches(build_scope: Any, row: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    if not isinstance(build_scope, Mapping):
        raise ValueError("semantic_build_scope_invalid")
    kind = build_scope.get("kind")
    if kind == "all":
        if set(build_scope) != {"kind"}:
            raise ValueError("semantic_build_scope_invalid")
        return True
    if kind != "partition":
        raise ValueError("semantic_build_scope_invalid")
    allowed = {"kind", *_SOURCE_PARTITION_FIELDS}
    if set(build_scope) - allowed:
        raise ValueError("semantic_build_scope_invalid")
    required = {"scope", "session_id", "object_id", "owner_bot_id", "platform", "persona_id"}
    if not required.issubset(build_scope):
        raise ValueError("semantic_build_scope_invalid")
    required_nonempty = required - {"persona_id"}
    if (build_scope.get("scope") not in {"private", "group"}
            or any(not isinstance(build_scope.get(key), str) or not build_scope.get(key)
                   for key in required_nonempty - {"scope"})
            or not isinstance(build_scope.get("persona_id"), str)
            or ("participant_user_id" in build_scope
                and not isinstance(build_scope["participant_user_id"], str))):
        raise ValueError("semantic_build_scope_invalid")
    actual = {
        "scope": row.get("scope", ""),
        "session_id": row.get("session_id", ""),
        "object_id": row.get("object_id", ""),
        "owner_bot_id": metadata.get("owner_bot_id", ""),
        "platform": metadata.get("platform", ""),
        "persona_id": metadata.get("persona_id", ""),
        "participant_user_id": metadata.get("participant_user_id", ""),
    }
    return all(actual.get(key, "") == value for key, value in build_scope.items() if key != "kind")


def _build_scope_sql(build_scope: Mapping[str, Any]) -> tuple[str, list[str]]:
    _build_scope_matches(build_scope, {}, {})
    if build_scope.get("kind") == "all":
        return "1=1", []
    expressions = {
        "scope": "t.scope",
        "session_id": "t.session_id",
        "object_id": "t.object_id",
        "owner_bot_id": "COALESCE(json_extract(CASE WHEN json_valid(t.metadata) THEN t.metadata ELSE '{}' END,'$.owner_bot_id'),'')",
        "platform": "COALESCE(json_extract(CASE WHEN json_valid(t.metadata) THEN t.metadata ELSE '{}' END,'$.platform'),'')",
        "persona_id": "COALESCE(json_extract(CASE WHEN json_valid(t.metadata) THEN t.metadata ELSE '{}' END,'$.persona_id'),'')",
        "participant_user_id": "COALESCE(json_extract(CASE WHEN json_valid(t.metadata) THEN t.metadata ELSE '{}' END,'$.participant_user_id'),'')",
    }
    clauses = []
    params: list[str] = []
    for key, value in build_scope.items():
        if key == "kind":
            continue
        clauses.append(f"{expressions[key]}=?")
        params.append(value)
    return " AND ".join(clauses), params


def _authorization_result(
    authorize_source: Callable[[dict[str, Any], dict[str, Any]], bool],
    row: Mapping[str, Any],
    metadata: dict[str, Any],
) -> bool:
    if not callable(authorize_source):
        raise ValueError("semantic_source_authorizer_required")
    projection = {key: row[key] for key in row.keys() if key != "content"}
    projection["metadata"] = metadata
    try:
        return authorize_source(projection, metadata) is True
    except Exception as exc:
        raise ValueError("semantic_source_authorization_failed") from exc


def _writable_generation(conn: sqlite3.Connection, generation: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM source_semantic_generations WHERE generation=?", (generation,),
    ).fetchone()
    if row is None or row["state"] not in {"building", "ready"}:
        raise ValueError("semantic_generation_not_writable")
    return row


def scan_generation_sources(
    conn: sqlite3.Connection,
    generation: str,
    *,
    limit: int = 64,
    authorize_source: Callable[[dict[str, Any], dict[str, Any]], bool],
    updated_at: str,
) -> dict[str, Any]:
    """Advance a stable-ID historical scan; timeline changes remain in dirty queues."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 128:
        raise ValueError("semantic_scan_limit_invalid")
    generation_row = _writable_generation(conn, generation)
    if generation_row["state"] != "building":
        raise ValueError("semantic_generation_scan_closed")
    try:
        cursor_state = json.loads(generation_row["scan_cursor"] or "{}")
    except (TypeError, ValueError):
        raise ValueError("semantic_scan_cursor_invalid")
    if not isinstance(cursor_state, dict):
        raise ValueError("semantic_scan_cursor_invalid")
    after_id = cursor_state.get("id", "")
    if not isinstance(after_id, str):
        raise ValueError("semantic_scan_cursor_invalid")
    if cursor_state.get("complete") is True:
        return {
            "sources": [], "next_cursor": after_id, "has_more": False, "done": True,
            "base_sequence": int(generation_row["base_sequence"]),
            "checkpoint_sequence": int(generation_row["checkpoint_sequence"]),
        }

    build_scope = _json_object(generation_row["config_json"]).get("build_scope")
    _build_scope_matches(build_scope, {}, {})
    base_sequence = int(generation_row["base_sequence"])
    scope_where, scope_params = _build_scope_sql(build_scope)
    rows = conn.execute(
        f"""SELECT t.id,t.event_type,t.session_id,t.scope,t.subject_id,t.object_id,
                   t.content,t.metadata,t.occurred_at,t.created_at,
                   julianday(t.occurred_at) AS source_sort_time
            FROM timeline t
            WHERE t.id>? AND t.event_type IN {_SOURCE_EVENT_SQL} AND {scope_where}
            ORDER BY t.id LIMIT ?""",
        (after_id, *scope_params, limit + 1),
    )
    sources: list[dict[str, Any]] = []
    next_id = after_id
    scanned = 0
    has_more = False
    for raw in rows:
        if scanned >= limit:
            has_more = True
            break
        row = dict(raw)
        scanned += 1
        next_id = str(row["id"])
        metadata = _json_object(row.get("metadata"))
        if not _build_scope_matches(build_scope, row, metadata):
            continue
        if not _authorization_result(authorize_source, row, metadata):
            continue
        source = {
            "source_id": row["id"],
            "source_version": message_source_version(row),
            "scope": row["scope"],
            "session_id": row["session_id"],
            "event_type": row["event_type"],
            "subject_id": row["subject_id"],
            "object_id": row["object_id"],
            "occurred_at": row["occurred_at"],
            "created_at": row["created_at"],
            "source_sort_time": row["source_sort_time"],
            "metadata": metadata,
        }
        sources.append(source)
        conn.execute(
            """INSERT OR IGNORE INTO source_semantic_dirty(
                 generation,source_id,change_sequence,operation,old_present,
                 new_source_id,new_present,new_scope,new_session_id,new_event_type,
                 new_subject_id,new_object_id,new_owner_bot_id,new_bot_id,new_platform,
                 new_persona_id,new_participant_user_id,new_occurred_at,new_created_at
               ) VALUES (?,?,?,'upsert',0,?,1,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (generation, row["id"], base_sequence, row["id"], row.get("scope"),
             row.get("session_id"), row.get("event_type"), row.get("subject_id"),
             row.get("object_id"), metadata.get("owner_bot_id", ""), metadata.get("bot_id", ""),
             metadata.get("platform", ""), metadata.get("persona_id", ""),
             metadata.get("participant_user_id", ""), row.get("occurred_at"), row.get("created_at")),
        )
    done = not has_more
    next_cursor = _canonical_json({"id": next_id, "complete": done})
    checkpoint = conn.execute(
        """UPDATE source_semantic_generations
           SET scan_cursor=?,checkpoint_sequence=?,updated_at=?
           WHERE generation=? AND state='building' AND scan_cursor=?""",
        (next_cursor, base_sequence, updated_at, generation, generation_row["scan_cursor"]),
    )
    if checkpoint.rowcount != 1:
        raise ValueError("semantic_scan_checkpoint_changed")
    return {
        "sources": sources, "next_cursor": next_id, "has_more": has_more, "done": done,
        "base_sequence": base_sequence, "checkpoint_sequence": base_sequence,
    }


def read_semantic_source(
    conn: sqlite3.Connection,
    generation: str,
    source_id: str,
    expected_version: str,
    *,
    authorize_source: Callable[[dict[str, Any], dict[str, Any]], bool],
    project_text: Callable[[str, dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Read full text only after rechecking generation scope, owner, and version."""
    generation_row = _writable_generation(conn, generation)
    row = conn.execute(
        "SELECT *,julianday(occurred_at) AS source_sort_time FROM timeline WHERE id=?",
        (source_id,),
    ).fetchone()
    if row is None or row["event_type"] not in {"user_message", "bot_response"}:
        raise ValueError("semantic_source_unavailable")
    row = dict(row)
    metadata = _json_object(row.get("metadata"))
    build_scope = _json_object(generation_row["config_json"]).get("build_scope")
    if (not _build_scope_matches(build_scope, row, metadata)
            or not _authorization_result(authorize_source, row, metadata)):
        raise ValueError("semantic_source_unauthorized")
    actual_version = message_source_version(row)
    if not expected_version or actual_version != expected_version:
        raise ValueError("semantic_source_version_changed")
    if not isinstance(row.get("content"), str):
        raise ValueError("semantic_source_text_unavailable")
    text = project_text(row["content"], row) if project_text is not None else row["content"]
    if not isinstance(text, str):
        raise ValueError("semantic_source_text_unavailable")
    return {
        "source_id": row["id"], "source_version": actual_version,
        "scope": row["scope"], "session_id": row["session_id"],
        "event_type": row["event_type"], "subject_id": row["subject_id"],
        "object_id": row["object_id"], "occurred_at": row["occurred_at"],
        "created_at": row["created_at"], "source_sort_time": row["source_sort_time"],
        "metadata": metadata, "text": text,
    }


def read_semantic_neighbors(
    conn: sqlite3.Connection,
    generation: str,
    anchor: Mapping[str, Any],
    *,
    authorize_source: Callable[[dict[str, Any], dict[str, Any]], bool],
    project_text: Callable[[str, dict[str, Any]], str] | None = None,
) -> list[dict[str, Any]]:
    """Read only currently adjacent, authorized source rows in the same partition."""
    generation_row = _writable_generation(conn, generation)
    snapshot = dict(anchor)
    metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), Mapping) else {}
    snapshot.update(metadata)
    neighbors = _snapshot_neighbors(conn, snapshot)
    results = []
    for row in neighbors:
        source_id = str(row["id"])
        try:
            results.append(read_semantic_source(
                conn, generation, source_id, message_source_version(dict(row)),
                authorize_source=authorize_source, project_text=project_text,
            ))
        except ValueError as exc:
            if str(exc) in {"semantic_source_unauthorized", "semantic_source_unavailable"}:
                continue
            raise
    return results


def _trusted_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _source_position(source: Mapping[str, Any]) -> tuple[float, str, str]:
    value = source.get("occurred_at")
    if _trusted_timestamp(value) is None:
        raise ValueError("semantic_window_time_untrusted")
    try:
        sort_time = float(source.get("source_sort_time"))
    except (TypeError, ValueError):
        sort_time = float("nan")
    if sort_time != sort_time:
        # Python's ISO parser handles timezone equivalence without SQLite's Julian conversion.
        sort_time = _trusted_timestamp(value).timestamp()
    return sort_time, str(source.get("created_at") or ""), str(source.get("source_id") or source.get("id") or "")


def _source_partition(source: Mapping[str, Any]) -> tuple[str, ...]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), Mapping) else {}
    return (
        str(source.get("scope") or ""), str(source.get("session_id") or ""),
        str(source.get("object_id") or ""), str(metadata.get("owner_bot_id") or ""),
        str(metadata.get("platform") or ""), str(metadata.get("persona_id") or ""),
        str(metadata.get("participant_user_id") or ""),
    )


def build_semantic_window(
    anchor: Mapping[str, Any],
    *,
    char_start: int,
    char_end: int,
    previous: Mapping[str, Any] | None = None,
    following: Mapping[str, Any] | None = None,
    max_chars: int = 1800,
) -> dict[str, Any]:
    """Build one bounded neighbor window and exact owner-relative spans."""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("semantic_window_limit_invalid")
    anchor_text = anchor.get("text")
    if not isinstance(anchor_text, str):
        raise ValueError("semantic_source_text_unavailable")
    if (isinstance(char_start, bool) or not isinstance(char_start, int) or char_start < 0
            or isinstance(char_end, bool) or not isinstance(char_end, int)
            or char_end < char_start or char_end > len(anchor_text)):
        raise ValueError("semantic_anchor_invalid")
    anchor_piece = anchor_text[char_start:char_end]
    if len(anchor_piece) > max_chars:
        raise ValueError("semantic_anchor_exceeds_window")
    anchor_position = _source_position(anchor)
    anchor_partition = _source_partition(anchor)
    neighbors: list[tuple[str, Mapping[str, Any]]] = []
    for side, item in (("previous", previous), ("following", following)):
        if item is None:
            continue
        if not isinstance(item.get("text"), str) or _source_partition(item) != anchor_partition:
            raise ValueError("semantic_window_partition_mismatch")
        position = _source_position(item)
        if side == "previous" and not position < anchor_position:
            raise ValueError("semantic_window_order_invalid")
        if side == "following" and not position > anchor_position:
            raise ValueError("semantic_window_order_invalid")
        neighbors.append((side, item))

    context_budget = max(0, max_chars - len(anchor_piece) - len(neighbors))
    if len(neighbors) == 1:
        allocations = [context_budget]
    else:
        allocations = [context_budget // 2, context_budget - context_budget // 2]
    selected: dict[str, tuple[int, int, str, Mapping[str, Any]]] = {}
    for (side, item), budget in zip(neighbors, allocations):
        text = str(item["text"])
        size = min(len(text), budget)
        if side == "previous":
            start, end = len(text) - size, len(text)
        else:
            start, end = 0, size
        if size:
            selected[side] = (start, end, text[start:end], item)

    dependencies: list[dict[str, Any]] = []
    chunks: list[str] = []
    for side in ("previous", "anchor", "following"):
        if side == "anchor":
            source = anchor
            start, end, piece = char_start, char_end, anchor_piece
            role = "anchor"
        elif side in selected:
            start, end, piece, source = selected[side]
            role = "context"
        else:
            continue
        dependencies.append({
            "source_id": str(source.get("source_id") or source.get("id") or ""),
            "source_version": str(source.get("source_version") or ""),
            "char_start": start, "char_end": end, "role": role,
        })
        chunks.append(piece)
    if any(not dep["source_id"] or not dep["source_version"] for dep in dependencies):
        raise ValueError("semantic_dependency_invalid")
    return {
        "input_text": "\n".join(chunks),
        "dependencies": dependencies,
        "anchor_source_id": str(anchor.get("source_id") or anchor.get("id") or ""),
        "anchor_source_version": str(anchor.get("source_version") or ""),
        "char_start": char_start,
        "char_end": char_end,
    }


def _snapshot_position(snapshot: Mapping[str, Any]) -> tuple[str, str, str] | None:
    occurred_at = snapshot.get("occurred_at")
    if _trusted_timestamp(occurred_at) is None:
        return None
    return str(occurred_at), str(snapshot.get("created_at") or ""), str(snapshot.get("source_id") or "")


def _snapshot_neighbors(conn: sqlite3.Connection, snapshot: Mapping[str, Any]) -> list[sqlite3.Row]:
    position = _snapshot_position(snapshot)
    if position is None:
        return []
    owner_meta = {key: snapshot.get(key, "") for key in (
        "owner_bot_id", "platform", "persona_id", "participant_user_id",
    )}
    clauses = [
        f"t.event_type IN {_SOURCE_EVENT_SQL}",
        "t.scope=?", "t.session_id=?", "t.object_id=?", "t.id!=?",
    ]
    params: list[Any] = [
        snapshot.get("scope", ""), snapshot.get("session_id", ""),
        snapshot.get("object_id", ""), snapshot.get("source_id", ""),
    ]
    meta_expr = "CASE WHEN json_valid(t.metadata) THEN t.metadata ELSE '{}' END"
    for key, expected in owner_meta.items():
        clauses.append(f"COALESCE(json_extract({meta_expr},'$.{key}'),'')=?")
        params.append(expected or "")
    clauses.append("julianday(t.occurred_at) IS NOT NULL")
    base_where = " AND ".join(clauses)
    occurred_at, created_at, source_id = position
    neighbors: list[sqlite3.Row] = []
    for operator, direction in (("<", "DESC"), (">", "ASC")):
        row = conn.execute(
            f"""SELECT t.* FROM timeline t WHERE {base_where}
                AND (julianday(t.occurred_at),t.created_at,t.id)
                    {operator} (julianday(?),?,?)
                ORDER BY julianday(t.occurred_at) {direction},t.created_at {direction},t.id {direction}
                LIMIT 1""",
            (*params, occurred_at, created_at, source_id),
        ).fetchone()
        if row is not None and _trusted_timestamp(row["occurred_at"]) is not None:
            neighbors.append(row)
    return neighbors


def _dirty_values_from_row(
    generation: str, sequence: int, row: Mapping[str, Any],
) -> tuple[Any, ...]:
    row = dict(row)
    metadata = _json_object(row.get("metadata"))
    fields = (
        row.get("scope"), row.get("session_id"), row.get("event_type"),
        row.get("subject_id"), row.get("object_id"), metadata.get("owner_bot_id", ""),
        metadata.get("bot_id", ""), metadata.get("platform", ""), metadata.get("persona_id", ""),
        metadata.get("participant_user_id", ""), row.get("occurred_at"), row.get("created_at"),
    )
    return (
        generation, row["id"], sequence, "upsert", 1, *fields,
        row["id"], 1, *fields,
    )


def expand_semantic_order_changes(
    conn: sqlite3.Connection,
    generation: str,
    *,
    limit: int = 64,
) -> dict[str, Any]:
    """Invalidate and enqueue the nearest anchors around each old/new position."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
        raise ValueError("semantic_order_limit_invalid")
    generation_row = _writable_generation(conn, generation)
    build_scope = _json_object(generation_row["config_json"]).get("build_scope")
    changes = conn.execute(
        """SELECT * FROM source_semantic_order_changes
           WHERE generation=? ORDER BY change_sequence,source_id LIMIT ?""",
        (generation, limit),
    ).fetchall()
    affected: dict[str, sqlite3.Row] = {}
    changed_sources: set[str] = set()
    for change in changes:
        changed_sources.add(str(change["source_id"]))
        for present_key, snapshot_key in (("old_present", "old_snapshot"), ("new_present", "new_snapshot")):
            if not change[present_key]:
                continue
            snapshot = _json_object(change[snapshot_key])
            snapshot_metadata = {key: snapshot.get(key, "") for key in (
                "owner_bot_id", "platform", "persona_id", "participant_user_id",
            )}
            if not _build_scope_matches(build_scope, snapshot, snapshot_metadata):
                continue
            for neighbor in _snapshot_neighbors(conn, snapshot):
                neighbor_metadata = _json_object(neighbor["metadata"])
                if _build_scope_matches(build_scope, dict(neighbor), neighbor_metadata):
                    affected[str(neighbor["id"])] = neighbor

    revision_row = conn.execute(
        "SELECT revision FROM source_semantic_revision WHERE singleton=1",
    ).fetchone()
    if revision_row is None:
        raise RuntimeError("source_semantic_schema_missing")
    current_sequence = int(revision_row[0])
    if affected:
        source_ids = sorted(affected)
        conn.executemany(
            """INSERT INTO source_semantic_dirty(
                generation,source_id,change_sequence,operation,old_present,
                old_scope,old_session_id,old_event_type,old_subject_id,old_object_id,
                old_owner_bot_id,old_bot_id,old_platform,old_persona_id,old_participant_user_id,
                old_occurred_at,old_created_at,new_source_id,new_present,new_scope,new_session_id,
                new_event_type,new_subject_id,new_object_id,new_owner_bot_id,new_bot_id,new_platform,
                new_persona_id,new_participant_user_id,new_occurred_at,new_created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(generation,source_id) DO UPDATE SET
                change_sequence=MAX(source_semantic_dirty.change_sequence,excluded.change_sequence),
                operation='upsert',new_source_id=excluded.new_source_id,new_present=1,
                new_scope=excluded.new_scope,new_session_id=excluded.new_session_id,
                new_event_type=excluded.new_event_type,new_subject_id=excluded.new_subject_id,
                new_object_id=excluded.new_object_id,new_owner_bot_id=excluded.new_owner_bot_id,
                new_bot_id=excluded.new_bot_id,new_platform=excluded.new_platform,
                new_persona_id=excluded.new_persona_id,new_participant_user_id=excluded.new_participant_user_id,
                new_occurred_at=excluded.new_occurred_at,new_created_at=excluded.new_created_at""",
            [_dirty_values_from_row(generation, current_sequence, affected[source_id]) for source_id in source_ids],
        )
        conn.executemany(
            """UPDATE source_semantic_documents SET state='stale',updated_at=datetime('now')
               WHERE generation=? AND view_kind='window' AND anchor_source_id=? AND state!='stale'""",
            [(generation, source_id) for source_id in source_ids],
        )
    for change in changes:
        conn.execute(
            """DELETE FROM source_semantic_order_changes
               WHERE generation=? AND change_sequence=? AND source_id=?""",
            (generation, change["change_sequence"], change["source_id"]),
        )
    return {
        "processed_changes": len(changes),
        "changed_source_ids": sorted(changed_sources),
        "affected_source_ids": sorted(affected),
        "change_sequence": current_sequence,
    }


def list_semantic_dirty(
    conn: sqlite3.Connection, generation: str, *, limit: int = 64,
) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
        raise ValueError("semantic_dirty_limit_invalid")
    generation_row = _writable_generation(conn, generation)
    build_scope = _json_object(generation_row["config_json"]).get("build_scope")
    rows = [dict(row) for row in conn.execute(
        """SELECT * FROM source_semantic_dirty WHERE generation=?
           ORDER BY change_sequence,source_id LIMIT ?""",
        (generation, limit),
    ).fetchall()]
    for row in rows:
        scope_flags = {}
        for prefix in ("old", "new"):
            source = {
                "scope": row.get(f"{prefix}_scope", ""),
                "session_id": row.get(f"{prefix}_session_id", ""),
                "event_type": row.get(f"{prefix}_event_type", ""),
                "subject_id": row.get(f"{prefix}_subject_id", ""),
                "object_id": row.get(f"{prefix}_object_id", ""),
            }
            metadata = {
                "owner_bot_id": row.get(f"{prefix}_owner_bot_id", ""),
                "bot_id": row.get(f"{prefix}_bot_id", ""),
                "platform": row.get(f"{prefix}_platform", ""),
                "persona_id": row.get(f"{prefix}_persona_id", ""),
                "participant_user_id": row.get(f"{prefix}_participant_user_id", ""),
            }
            scope_flags[prefix] = bool(row[f"{prefix}_present"]) and _build_scope_matches(
                build_scope, source, metadata,
            )
        row["old_build_scope_matches"] = scope_flags["old"]
        row["new_build_scope_matches"] = scope_flags["new"]
        row["build_scope_matches"] = scope_flags["old"] or scope_flags["new"]
    return rows


def semantic_document_id(
    generation: str, source_id: str, view_kind: str, char_start: int, char_end: int,
) -> str:
    return "sd_" + _digest([generation, source_id, view_kind, char_start, char_end])


def capture_semantic_fence(conn: sqlite3.Connection, generation: str) -> dict[str, Any]:
    generation_row = _writable_generation(conn, generation)
    revision = conn.execute(
        "SELECT revision FROM source_semantic_revision WHERE singleton=1",
    ).fetchone()
    if revision is None:
        raise RuntimeError("source_semantic_schema_missing")
    return {
        "generation": generation,
        "config_hash": generation_row["config_hash"],
        "source_revision": int(revision[0]),
    }


def _current_dependency_rows(
    conn: sqlite3.Connection,
    *,
    generation_config: Mapping[str, Any],
    dependencies: Sequence[Mapping[str, Any]],
    authorize_source: Callable[[dict[str, Any], dict[str, Any]], bool],
    project_text: Callable[[str, dict[str, Any]], str] | None = None,
) -> list[tuple[int, str, str, int, int, str, dict[str, Any]]]:
    checked: list[tuple[int, str, str, int, int, str, dict[str, Any]]] = []
    seen: set[str] = set()
    partition: tuple[str, ...] | None = None
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, Mapping):
            raise ValueError("semantic_dependency_invalid")
        source_id = dependency.get("source_id")
        source_version = dependency.get("source_version")
        start, end = dependency.get("char_start"), dependency.get("char_end")
        role = dependency.get("role")
        if (not isinstance(source_id, str) or not source_id or source_id in seen
                or not isinstance(source_version, str) or not source_version
                or isinstance(start, bool) or not isinstance(start, int) or start < 0
                or isinstance(end, bool) or not isinstance(end, int) or end < start
                or role not in {"anchor", "context"}):
            raise ValueError("semantic_dependency_invalid")
        seen.add(source_id)
        raw = conn.execute(
            "SELECT *,julianday(occurred_at) AS source_sort_time FROM timeline WHERE id=?",
            (source_id,),
        ).fetchone()
        if raw is None or raw["event_type"] not in {"user_message", "bot_response"}:
            raise ValueError("semantic_dependency_unavailable")
        row = dict(raw)
        metadata = _json_object(row.get("metadata"))
        if (not _build_scope_matches(generation_config.get("build_scope"), row, metadata)
                or not _authorization_result(authorize_source, row, metadata)):
            raise ValueError("semantic_dependency_unauthorized")
        if message_source_version(row) != source_version:
            raise ValueError("semantic_dependency_version_changed")
        content = row.get("content")
        if not isinstance(content, str) or end > len(content):
            raise ValueError("semantic_dependency_span_invalid")
        text = content if project_text is None else project_text(content, row)
        if not isinstance(text, str):
            raise ValueError("semantic_source_text_unavailable")
        source = {
            "source_id": row["id"], "source_version": source_version,
            "scope": row["scope"], "session_id": row["session_id"],
            "event_type": row["event_type"], "subject_id": row["subject_id"],
            "object_id": row["object_id"], "occurred_at": row["occurred_at"],
            "created_at": row["created_at"], "source_sort_time": row["source_sort_time"],
            "metadata": metadata, "text": text,
        }
        current_partition = _source_partition(source)
        if partition is None:
            partition = current_partition
        elif current_partition != partition:
            raise ValueError("semantic_window_partition_mismatch")
        checked.append((index, source_id, source_version, start, end, role, source))
    return checked


def validate_semantic_snapshot(
    conn: sqlite3.Connection,
    *,
    generation: str,
    expected_config_hash: str,
    source_change_sequence: int,
    view_kind: str,
    anchor_source_id: str,
    anchor_source_version: str,
    char_start: int,
    char_end: int,
    input_text: str,
    dependencies: Sequence[Mapping[str, Any]],
    authorize_source: Callable[[dict[str, Any], dict[str, Any]], bool],
    project_text: Callable[[str, dict[str, Any]], str] | None = None,
) -> list[tuple[int, str, str, int, int, str, dict[str, Any]]]:
    """Recheck generation, global source revision, every owner, span, and window edge."""
    if view_kind not in {"fragment", "window"}:
        raise ValueError("semantic_view_kind_invalid")
    if (not isinstance(expected_config_hash, str) or not expected_config_hash
            or isinstance(source_change_sequence, bool) or not isinstance(source_change_sequence, int)
            or source_change_sequence < 0
            or isinstance(char_start, bool) or not isinstance(char_start, int) or char_start < 0
            or isinstance(char_end, bool) or not isinstance(char_end, int) or char_end < char_start):
        raise ValueError("semantic_snapshot_fence_invalid")
    generation_row = _writable_generation(conn, generation)
    if generation_row["config_hash"] != expected_config_hash:
        raise ValueError("semantic_generation_changed")
    revision = conn.execute(
        "SELECT revision FROM source_semantic_revision WHERE singleton=1",
    ).fetchone()
    if revision is None or int(revision[0]) != source_change_sequence:
        raise ValueError("semantic_source_revision_changed")
    if not isinstance(input_text, str) or not dependencies:
        raise ValueError("semantic_document_input_invalid")
    config = _json_object(generation_row["config_json"])
    checked = _current_dependency_rows(
        conn,
        generation_config=config,
        dependencies=dependencies,
        authorize_source=authorize_source,
        project_text=project_text,
    )
    anchors = [item for item in checked if item[5] == "anchor"]
    if len(anchors) != 1 or anchors[0][1:5] != (
        anchor_source_id, anchor_source_version, char_start, char_end,
    ):
        raise ValueError("semantic_anchor_dependency_mismatch")
    if view_kind == "fragment" and len(checked) != 1:
        raise ValueError("semantic_fragment_dependency_invalid")
    if view_kind == "window":
        anchor = anchors[0][6]
        anchor_time = _trusted_timestamp(anchor.get("occurred_at"))
        if anchor_time is None:
            raise ValueError("semantic_window_time_untrusted")
        context_rows = [item for item in checked if item[5] == "context"]
        if len(context_rows) > 2:
            raise ValueError("semantic_window_neighbor_limit")
        anchor_snapshot = {
            "source_id": anchor["source_id"], "scope": anchor["scope"],
            "session_id": anchor["session_id"], "object_id": anchor["object_id"],
            "occurred_at": anchor["occurred_at"], "created_at": anchor["created_at"],
            **{key: anchor["metadata"].get(key, "") for key in (
                "owner_bot_id", "platform", "persona_id", "participant_user_id",
            )},
        }
        neighbor_ids = {str(row["id"]) for row in _snapshot_neighbors(conn, anchor_snapshot)}
        if any(item[1] not in neighbor_ids for item in context_rows):
            raise ValueError("semantic_window_adjacency_changed")
        sorted_ids = [item[1] for item in sorted(
            checked,
            key=lambda item: _source_position(item[6]),
        )]
        if sorted_ids != [item[1] for item in checked]:
            raise ValueError("semantic_window_dependency_order_invalid")
    rendered = "\n".join(item[6]["text"][item[3]:item[4]] for item in checked)
    if input_text != rendered:
        raise ValueError("semantic_input_dependency_mismatch")
    return checked


def store_semantic_document(
    conn: sqlite3.Connection,
    *,
    generation: str,
    view_kind: str,
    anchor_source_id: str,
    anchor_source_version: str,
    char_start: int,
    char_end: int,
    input_text: str,
    source_change_sequence: int,
    dependencies: Sequence[Mapping[str, Any]],
    expected_config_hash: str,
    authorize_source: Callable[[dict[str, Any], dict[str, Any]], bool],
    project_text: Callable[[str, dict[str, Any]], str] | None = None,
    vector: bytes | None = None,
    vector_dimension: int | None = None,
    updated_at: str,
) -> str:
    """Persist only a freshly authorized, version-bound text-free projection."""
    if view_kind not in {"fragment", "window"}:
        raise ValueError("semantic_view_kind_invalid")
    if (not isinstance(anchor_source_id, str) or not anchor_source_id
            or not isinstance(anchor_source_version, str) or not anchor_source_version
            or isinstance(char_start, bool) or not isinstance(char_start, int) or char_start < 0
            or isinstance(char_end, bool) or not isinstance(char_end, int) or char_end < char_start):
        raise ValueError("semantic_anchor_invalid")
    if (not isinstance(input_text, str) or not dependencies or isinstance(source_change_sequence, bool)
            or not isinstance(source_change_sequence, int) or source_change_sequence < 0):
        raise ValueError("semantic_document_input_invalid")
    if vector is not None and (not isinstance(vector, bytes) or isinstance(vector_dimension, bool)
                               or not isinstance(vector_dimension, int) or vector_dimension < 1):
        raise ValueError("semantic_vector_invalid")
    if vector is None and vector_dimension is not None:
        raise ValueError("semantic_vector_invalid")
    generation_row = _writable_generation(conn, generation)
    generation_config = _json_object(generation_row["config_json"])
    if vector is not None and vector_dimension != generation_config.get("dimensions"):
        raise ValueError("semantic_vector_dimension_mismatch")
    checked = validate_semantic_snapshot(
        conn,
        generation=generation,
        expected_config_hash=expected_config_hash,
        source_change_sequence=source_change_sequence,
        view_kind=view_kind,
        anchor_source_id=anchor_source_id,
        anchor_source_version=anchor_source_version,
        char_start=char_start,
        char_end=char_end,
        input_text=input_text,
        dependencies=dependencies,
        authorize_source=authorize_source,
        project_text=project_text,
    )

    document_id = semantic_document_id(generation, anchor_source_id, view_kind, char_start, char_end)
    input_hash = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    conn.execute(
        """INSERT INTO source_semantic_documents
            (document_id,generation,view_kind,anchor_source_id,anchor_source_version,char_start,char_end,
             input_hash,source_change_sequence,vector_blob,vector_dimension,state,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(document_id) DO UPDATE SET
                anchor_source_version=excluded.anchor_source_version,char_start=excluded.char_start,
                char_end=excluded.char_end,input_hash=excluded.input_hash,
                source_change_sequence=excluded.source_change_sequence,vector_blob=excluded.vector_blob,
                vector_dimension=excluded.vector_dimension,state=excluded.state,updated_at=excluded.updated_at""",
        (document_id, generation, view_kind, anchor_source_id, anchor_source_version,
         char_start, char_end, input_hash, source_change_sequence, vector, vector_dimension,
         "ready" if vector is not None else "pending", updated_at),
    )
    conn.execute("DELETE FROM source_semantic_dependencies WHERE document_id=?", (document_id,))
    conn.executemany(
        """INSERT INTO source_semantic_dependencies
            (document_id,dependency_order,source_id,source_version,char_start,char_end,role)
            VALUES (?,?,?,?,?,?,?)""",
        [(document_id, *dependency[:6]) for dependency in checked],
    )
    return document_id
