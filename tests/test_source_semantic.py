from __future__ import annotations

import hashlib
import json

import pytest

from core.source_semantic import (
    FRAGMENT_OVERLAP_CHARS,
    FRAGMENT_TARGET_CHARS,
    acknowledge_dirty,
    build_semantic_window,
    capture_semantic_fence,
    expand_semantic_order_changes,
    list_semantic_dirty,
    read_semantic_source,
    register_generation,
    scan_generation_sources,
    split_source_fragments,
    store_semantic_document,
    validate_semantic_snapshot,
)
from core.source_evidence import message_source_version
from core.source_query import source_visible
from .test_source_query import add_row, ctx, service


pytestmark = pytest.mark.asyncio


def configuration(model_revision: str = "model-r1", build_scope=None) -> dict[str, object]:
    return {
        "provider_id": "local-test",
        "model_revision": model_revision,
        "dimensions": 3,
        "distance_metric": "cosine",
        "query_encoding": "query-v1",
        "document_encoding": "document-v1",
        "processing_version": "redaction-v1",
        "fragment_profile": "unicode-codepoint-overlap-v1",
        "window_profile": "adjacent-one-v1",
        "build_scope": build_scope or {"kind": "all"},
    }


def start_generation(service, name: str, model_revision: str = "model-r1", build_scope=None) -> int:
    with service.store._lock, service.store._transaction_sync():
        return register_generation(
            service.store._conn,
            name,
            configuration(model_revision, build_scope),
            created_at="2026-10-08T00:00:00+00:00",
        )


def authorization(context):
    return lambda row, metadata: source_visible(context, row, metadata)


def current_source(service, source_id: str) -> dict[str, object]:
    with service.store._lock:
        row = dict(service.store._conn.execute(
            "SELECT * FROM timeline WHERE id=?", (source_id,),
        ).fetchone())
    return row


def source_version(service, source_id: str) -> str:
    return message_source_version(current_source(service, source_id))


def generation_config_hash(service, generation: str) -> str:
    with service.store._lock:
        return service.store._conn.execute(
            "SELECT config_hash FROM source_semantic_generations WHERE generation=?",
            (generation,),
        ).fetchone()[0]


async def add_row_with_id(service, context, source_id: str, text: str, at: str, *, metadata=None):
    source_metadata = {
        "owner_bot_id": context.bot_id,
        "bot_id": context.bot_id,
        "platform": context.platform,
        "persona_id": context.persona_id,
    }
    source_metadata.update(metadata or {})
    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute(
            """INSERT INTO timeline(
                id,event_type,session_id,scope,subject_id,object_id,content,metadata,
                occurred_at,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (source_id, "user_message", context.session_id, context.scope,
             context.user_id, context.current_target_id, text,
             json.dumps(source_metadata, ensure_ascii=False, sort_keys=True), at, at),
        )
    return source_id


async def test_unicode_fragments_preserve_offsets_overlap_and_tail():
    text = "🙂e\u0301中" * 330
    fragments = split_source_fragments(text)

    assert fragments[0]["char_start"] == 0
    assert fragments[0]["char_end"] == FRAGMENT_TARGET_CHARS
    assert fragments[1]["char_start"] == FRAGMENT_TARGET_CHARS - FRAGMENT_OVERLAP_CHARS
    assert fragments[-1]["char_end"] == len(text)
    rebuilt = fragments[0]["text"] + "".join(
        fragment["text"][FRAGMENT_OVERLAP_CHARS:] for fragment in fragments[1:]
    )
    assert rebuilt == text
    assert all(fragment["char_end"] - fragment["char_start"] == len(fragment["text"])
               for fragment in fragments)


async def test_generation_scan_uses_stable_id_checkpoint_and_keeps_late_old_time_dirty(service, ctx):
    first_id = await add_row_with_id(
        service, ctx, "b-semantic-source", "第一条", "2026-09-08T00:00:00+08:00",
    )
    await add_row_with_id(
        service, ctx, "bb-hidden-source", "不属于当前 owner", "2026-09-08T00:00:30+08:00",
        metadata={"owner_bot_id": "another-bot", "bot_id": "another-bot"},
    )
    last_id = await add_row_with_id(
        service, ctx, "c-semantic-source", "最后一条", "2026-09-08T00:01:00+08:00",
    )
    base = start_generation(service, "semantic-scan")
    authorize = authorization(ctx)
    with service.store._lock, service.store._transaction_sync():
        first = scan_generation_sources(
            service.store._conn, "semantic-scan", limit=2,
            authorize_source=authorize, updated_at="2026-10-08T00:00:00+00:00",
        )
    assert [item["source_id"] for item in first["sources"]] == [first_id]
    assert first["has_more"] and first["checkpoint_sequence"] == base
    late_id = await add_row_with_id(
        service, ctx, "a-late-semantic-source", "游标之前插入的旧时间来源",
        "2026-09-07T00:00:00+08:00",
    )
    with service.store._lock, service.store._transaction_sync():
        second = scan_generation_sources(
            service.store._conn, "semantic-scan", limit=2,
            authorize_source=authorize, updated_at="2026-10-08T00:01:00+00:00",
        )
        terminal = scan_generation_sources(
            service.store._conn, "semantic-scan", limit=2,
            authorize_source=authorize, updated_at="2026-10-08T00:02:00+00:00",
        )
        dirty_ids = {item["source_id"] for item in list_semantic_dirty(
            service.store._conn, "semantic-scan",
        )}
    assert [item["source_id"] for item in second["sources"]] == [last_id]
    assert second["done"] and terminal["done"] and not terminal["sources"]
    assert late_id in dirty_ids
    with service.store._lock:
        expected = source_version(service, first_id)
        source = read_semantic_source(
            service.store._conn, "semantic-scan", first_id, expected,
            authorize_source=authorize,
        )
        assert source["text"] == "第一条"
        with pytest.raises(ValueError, match="semantic_source_version_changed"):
            read_semantic_source(
                service.store._conn, "semantic-scan", first_id, "wrong-version",
                authorize_source=authorize,
            )


async def test_partition_generation_filters_scan_and_marks_out_of_scope_dirty(service, ctx):
    build_scope = {
        "kind": "partition", "scope": ctx.scope, "session_id": ctx.session_id,
        "object_id": ctx.current_target_id, "owner_bot_id": ctx.bot_id,
        "platform": ctx.platform, "persona_id": ctx.persona_id,
    }
    start_generation(service, "semantic-partition", build_scope=build_scope)
    inside_id = await add_row_with_id(
        service, ctx, "partition-inside", "授权范围内", "2026-09-08T00:00:00+08:00",
    )
    outside_id = await add_row_with_id(
        service, ctx, "partition-outside", "其它 owner", "2026-09-08T00:00:30+08:00",
        metadata={"owner_bot_id": "another-bot", "bot_id": "another-bot"},
    )
    with service.store._lock, service.store._transaction_sync():
        page = scan_generation_sources(
            service.store._conn, "semantic-partition", limit=4,
            authorize_source=authorization(ctx), updated_at="2026-10-08T00:00:00+00:00",
        )
        dirty = list_semantic_dirty(service.store._conn, "semantic-partition")
    assert [item["source_id"] for item in page["sources"]] == [inside_id]
    assert page["done"]
    dirty_scope = {item["source_id"]: item["build_scope_matches"] for item in dirty}
    assert dirty_scope == {inside_id: True, outside_id: False}


async def test_semantic_dirty_is_generation_scoped_and_coalesces_old_new_positions(service, ctx):
    start_generation(service, "semantic-test-a")
    start_generation(service, "semantic-test-b", "model-r2")
    source_id = await add_row(service, ctx, "原始来源")

    with service.store._lock:
        rows = service.store._conn.execute(
            "SELECT * FROM source_semantic_dirty WHERE source_id=? ORDER BY generation",
            (source_id,),
        ).fetchall()
    assert len(rows) == 2
    first = dict(rows[0])
    assert first["old_present"] == 0 and first["new_present"] == 1
    assert first["new_session_id"] == ctx.session_id
    assert first["new_owner_bot_id"] == ctx.bot_id
    actual_version = source_version(service, source_id)

    with service.store._lock, service.store._transaction_sync():
        document_id = store_semantic_document(
            service.store._conn,
            generation="semantic-test-a",
            view_kind="window",
            anchor_source_id=source_id,
            anchor_source_version=actual_version,
            char_start=0,
            char_end=4,
            input_text="原始来源",
            source_change_sequence=first["change_sequence"],
            dependencies=[{
                "source_id": source_id, "source_version": actual_version,
                "char_start": 0, "char_end": 4, "role": "anchor",
            }],
            expected_config_hash=generation_config_hash(service, "semantic-test-a"),
            authorize_source=authorization(ctx),
            updated_at="2026-10-08T00:00:00+00:00",
        )

    with service.store._lock, service.store._transaction_sync():
        expanded = expand_semantic_order_changes(
            service.store._conn, "semantic-test-a",
        )
        assert source_id in expanded["changed_source_ids"]

    assert acknowledge_dirty(service.store._conn, "semantic-test-a", source_id, first["change_sequence"])
    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute(
            """UPDATE timeline
               SET session_id=?,occurred_at=?,metadata=json_set(metadata,'$.persona_id','persona-next')
               WHERE id=?""",
            ("qq:FriendMessage:semantic-moved", "2026-10-07T16:00:00Z", source_id),
        )
    with service.store._lock:
        changed = dict(service.store._conn.execute(
            "SELECT * FROM source_semantic_dirty WHERE generation=? AND source_id=?",
            ("semantic-test-a", source_id),
        ).fetchone())
        document_state = service.store._conn.execute(
            "SELECT state FROM source_semantic_documents WHERE document_id=?", (document_id,),
        ).fetchone()[0]
        other_generation = service.store._conn.execute(
            "SELECT 1 FROM source_semantic_dirty WHERE generation=? AND source_id=?",
            ("semantic-test-b", source_id),
        ).fetchone()
    assert other_generation is not None
    assert changed["old_session_id"] == ctx.session_id
    assert changed["new_session_id"] == "qq:FriendMessage:semantic-moved"
    assert changed["old_persona_id"] == ctx.persona_id
    assert changed["new_persona_id"] == "persona-next"
    assert document_state == "stale"

    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute(
            "UPDATE timeline SET session_id=? WHERE id=?",
            ("qq:FriendMessage:semantic-latest", source_id),
        )
    with service.store._lock:
        latest = dict(service.store._conn.execute(
            "SELECT * FROM source_semantic_dirty WHERE generation=? AND source_id=?",
            ("semantic-test-a", source_id),
        ).fetchone())
    assert latest["change_sequence"] > changed["change_sequence"]
    assert latest["old_session_id"] == ctx.session_id
    assert latest["new_session_id"] == "qq:FriendMessage:semantic-latest"
    assert not acknowledge_dirty(service.store._conn, "semantic-test-a", source_id, changed["change_sequence"])
    with service.store._lock, service.store._transaction_sync():
        expand_semantic_order_changes(service.store._conn, "semantic-test-a")
        assert acknowledge_dirty(service.store._conn, "semantic-test-a", source_id, latest["change_sequence"])

    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute("DELETE FROM timeline WHERE id=?", (source_id,))
    with service.store._lock:
        deleted = dict(service.store._conn.execute(
            "SELECT * FROM source_semantic_dirty WHERE generation=? AND source_id=?",
            ("semantic-test-a", source_id),
        ).fetchone())
    assert deleted["operation"] == "delete"
    assert deleted["old_present"] == 1 and deleted["new_present"] == 0
    assert deleted["old_session_id"] == "qq:FriendMessage:semantic-latest"


async def test_semantic_dirty_is_not_written_without_an_active_generation(service, ctx):
    source_id = await add_row(service, ctx, "语义索引未启用时的普通原文")
    with service.store._lock:
        before = service.store._conn.execute(
            "SELECT revision FROM source_semantic_revision WHERE singleton=1"
        ).fetchone()[0]
        pending = service.store._conn.execute(
            "SELECT count(*) FROM source_semantic_dirty"
        ).fetchone()[0]
    assert before == pending == 0

    start_generation(service, "semantic-paused", "model-paused")
    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute(
            "UPDATE source_semantic_generations SET state='retired' WHERE generation='semantic-paused'"
        )
        service.store._conn.execute("UPDATE timeline SET content='已变化' WHERE id=?", (source_id,))
    with service.store._lock:
        after = service.store._conn.execute(
            "SELECT revision FROM source_semantic_revision WHERE singleton=1"
        ).fetchone()[0]
        pending = service.store._conn.execute(
            "SELECT count(*) FROM source_semantic_dirty"
        ).fetchone()[0]
    assert after == 0 and pending == 0


async def test_retired_generation_rejects_late_document_and_dirty_ack(service, ctx):
    start_generation(service, "semantic-retired")
    source_id = await add_row(service, ctx, "稍后撤销的来源")
    with service.store._lock, service.store._transaction_sync():
        dirty = dict(service.store._conn.execute(
            "SELECT * FROM source_semantic_dirty WHERE generation=? AND source_id=?",
            ("semantic-retired", source_id),
        ).fetchone())
        service.store._conn.execute(
            "UPDATE source_semantic_generations SET state='retired' WHERE generation='semantic-retired'"
        )

    with service.store._lock, service.store._transaction_sync():
        assert not acknowledge_dirty(
            service.store._conn, "semantic-retired", source_id, dirty["change_sequence"],
        )
        with pytest.raises(ValueError, match="semantic_generation_not_writable"):
            store_semantic_document(
                service.store._conn,
                generation="semantic-retired",
                view_kind="fragment",
                anchor_source_id=source_id,
                anchor_source_version="source-version-1",
                char_start=0,
                char_end=4,
                input_text="稍后撤销的来源",
                source_change_sequence=dirty["change_sequence"],
                dependencies=[{
                    "source_id": source_id, "source_version": "source-version-1",
                    "char_start": 0, "char_end": 4, "role": "anchor",
                }],
                expected_config_hash=generation_config_hash(service, "semantic-retired"),
                authorize_source=authorization(ctx),
                updated_at="2026-10-08T00:00:00+00:00",
            )


async def test_semantic_documents_store_hashes_and_every_source_dependency(service, ctx):
    previous_id = await add_row_with_id(
        service, ctx, "semantic-prev", "前一条来源记录", "2026-09-08T00:00:00+08:00",
    )
    anchor_id = await add_row_with_id(
        service, ctx, "semantic-anchor", "锚点片段与前一条来源的组合文本",
        "2026-09-08T00:01:00+08:00",
    )
    start_generation(service, "semantic-doc-test")
    input_text = "来源\n锚点片段"
    dependencies = [
        {"source_id": previous_id, "source_version": source_version(service, previous_id),
         "char_start": 3, "char_end": 5, "role": "context"},
        {"source_id": anchor_id, "source_version": source_version(service, anchor_id),
         "char_start": 0, "char_end": 4, "role": "anchor"},
    ]
    anchor_version = dependencies[1]["source_version"]
    with service.store._lock, service.store._transaction_sync():
        source_sequence = service.store._conn.execute(
            "SELECT revision FROM source_semantic_revision WHERE singleton=1",
        ).fetchone()[0]
        document_id = store_semantic_document(
            service.store._conn,
            generation="semantic-doc-test",
            view_kind="window",
            anchor_source_id=anchor_id,
            anchor_source_version=anchor_version,
            char_start=0,
            char_end=4,
            input_text=input_text,
            source_change_sequence=source_sequence,
            dependencies=dependencies,
            expected_config_hash=generation_config_hash(service, "semantic-doc-test"),
            authorize_source=authorization(ctx),
            updated_at="2026-10-08T00:00:00+00:00",
        )
        document = dict(service.store._conn.execute(
            "SELECT * FROM source_semantic_documents WHERE document_id=?", (document_id,),
        ).fetchone())
        refs = [dict(row) for row in service.store._conn.execute(
            "SELECT * FROM source_semantic_dependencies WHERE document_id=? ORDER BY dependency_order",
            (document_id,),
        ).fetchall()]

    assert document["state"] == "pending" and document["vector_blob"] is None
    assert document["input_hash"] == hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    assert input_text not in repr(document)
    assert [(row["source_id"], row["role"]) for row in refs] == [
        (previous_id, "context"), (anchor_id, "anchor"),
    ]
    with pytest.raises(ValueError, match="semantic_anchor_dependency_mismatch"):
        store_semantic_document(
            service.store._conn,
            generation="semantic-doc-test",
            view_kind="fragment",
            anchor_source_id=anchor_id,
            anchor_source_version=anchor_version,
            char_start=0,
            char_end=4,
            input_text=input_text,
            source_change_sequence=source_sequence,
            dependencies=[dependencies[0]],
            expected_config_hash=generation_config_hash(service, "semantic-doc-test"),
            authorize_source=authorization(ctx),
            updated_at="2026-10-08T00:00:00+00:00",
        )


async def test_bounded_window_spans_and_order_changes_invalidate_neighbors(service, ctx):
    previous_id = await add_row_with_id(
        service, ctx, "window-previous", "前一段内容", "2026-09-08T00:00:00+08:00",
    )
    anchor_id = await add_row_with_id(
        service, ctx, "window-anchor", "说改坐了高铁。", "2026-09-08T00:01:00+08:00",
    )
    following_id = await add_row_with_id(
        service, ctx, "window-following", "后来到达。", "2026-09-08T00:02:00+08:00",
    )
    start_generation(service, "semantic-window")
    authorize = authorization(ctx)
    with service.store._lock, service.store._transaction_sync():
        expand_semantic_order_changes(service.store._conn, "semantic-window")
        previous = read_semantic_source(
            service.store._conn, "semantic-window", previous_id,
            source_version(service, previous_id), authorize_source=authorize,
        )
        anchor = read_semantic_source(
            service.store._conn, "semantic-window", anchor_id,
            source_version(service, anchor_id), authorize_source=authorize,
        )
        following = read_semantic_source(
            service.store._conn, "semantic-window", following_id,
            source_version(service, following_id), authorize_source=authorize,
        )
        window = build_semantic_window(
            anchor, char_start=0, char_end=7, previous=previous, following=following, max_chars=13,
        )
        fence = capture_semantic_fence(service.store._conn, "semantic-window")
        document_id = store_semantic_document(
            service.store._conn,
            generation="semantic-window",
            view_kind="window",
            anchor_source_id=window["anchor_source_id"],
            anchor_source_version=window["anchor_source_version"],
            char_start=window["char_start"],
            char_end=window["char_end"],
            input_text=window["input_text"],
            source_change_sequence=fence["source_revision"],
            dependencies=window["dependencies"],
            expected_config_hash=fence["config_hash"],
            authorize_source=authorize,
            updated_at="2026-10-08T00:00:00+00:00",
        )
    assert len(window["input_text"]) <= 13
    assert [item["source_id"] for item in window["dependencies"]] == [
        previous_id, anchor_id, following_id,
    ]
    assert window["dependencies"][0]["char_start"] > 0
    assert window["dependencies"][2]["char_start"] == 0
    with service.store._lock, service.store._transaction_sync():
        validate_semantic_snapshot(
            service.store._conn,
            generation="semantic-window",
            expected_config_hash=fence["config_hash"],
            source_change_sequence=fence["source_revision"],
            view_kind="window",
            anchor_source_id=window["anchor_source_id"],
            anchor_source_version=window["anchor_source_version"],
            char_start=window["char_start"],
            char_end=window["char_end"],
            input_text=window["input_text"],
            dependencies=window["dependencies"],
            authorize_source=authorize,
        )
    inserted_id = await add_row_with_id(
        service, ctx, "window-inserted", "插进相邻位置", "2026-09-08T00:00:30+08:00",
    )
    with service.store._lock, service.store._transaction_sync():
        current_sequence = service.store._conn.execute(
            "SELECT revision FROM source_semantic_revision WHERE singleton=1",
        ).fetchone()[0]
        with pytest.raises(ValueError, match="semantic_window_adjacency_changed"):
            validate_semantic_snapshot(
                service.store._conn,
                generation="semantic-window",
                expected_config_hash=fence["config_hash"],
                source_change_sequence=current_sequence,
                view_kind="window",
                anchor_source_id=window["anchor_source_id"],
                anchor_source_version=window["anchor_source_version"],
                char_start=window["char_start"],
                char_end=window["char_end"],
                input_text=window["input_text"],
                dependencies=window["dependencies"],
                authorize_source=authorize,
            )
        expanded = expand_semantic_order_changes(service.store._conn, "semantic-window")
        dirty_ids = {item["source_id"] for item in list_semantic_dirty(
            service.store._conn, "semantic-window",
        )}
        document_state = service.store._conn.execute(
            "SELECT state FROM source_semantic_documents WHERE document_id=?", (document_id,),
        ).fetchone()[0]
    assert {previous_id, anchor_id}.issubset(set(expanded["affected_source_ids"]))
    assert {previous_id, anchor_id}.issubset(dirty_ids)
    assert document_state == "stale"
    assert inserted_id in {item["source_id"] for item in list_semantic_dirty(
        service.store._conn, "semantic-window",
    )}
    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute("DELETE FROM timeline WHERE id=?", (inserted_id,))
        deleted = expand_semantic_order_changes(service.store._conn, "semantic-window")
        service.store._conn.execute(
            "UPDATE timeline SET occurred_at=? WHERE id=?",
            ("2026-09-08T00:03:00+08:00", anchor_id),
        )
        moved = expand_semantic_order_changes(service.store._conn, "semantic-window")
    assert {previous_id, anchor_id}.issubset(set(deleted["affected_source_ids"]))
    assert {previous_id, following_id}.issubset(set(moved["affected_source_ids"]))
