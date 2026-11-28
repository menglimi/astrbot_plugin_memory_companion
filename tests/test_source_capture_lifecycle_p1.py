from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.source_capture import DEFAULT_RETENTION_SECONDS, SourceCapture
from core.store import MemoryStore

from .test_source_query import ctx, service  # noqa: F401  (pytest fixtures)

pytestmark = pytest.mark.asyncio


class Plain:
    def __init__(self, text: str):
        self.text = text


def event(text: str, message_id: str = "p1-native-1") -> SimpleNamespace:
    return SimpleNamespace(
        message_obj=SimpleNamespace(message_id=message_id, message=[Plain(text)], timestamp=0),
        message_str=text,
    )


async def test_switch_roundtrip_gates_real_incoming_write(service, ctx):
    capture = service.capture
    assert capture.source_capture_enabled() is True
    assert capture.store.retention_seconds == DEFAULT_RETENTION_SECONDS

    written = capture.set_source_capture_enabled(False, actor="test-owner")
    assert written == {"enabled": False, "actor": "test-owner", "updated_at": written["updated_at"]}
    assert capture.source_capture_enabled() is False
    assert capture.store.source_capture_switch()["explicit"] is True

    assert await capture.incoming(event("开关关闭时不应该落库"), ctx) is None
    assert service.store._conn.execute("SELECT count(*) FROM capture_chunks").fetchone()[0] == 0
    assert service.store._conn.execute("SELECT count(*) FROM capture_sources").fetchone()[0] == 0

    capture.set_source_capture_enabled(True, actor="test-owner")
    receipt = await capture.incoming(event("开关打开后的完整原文"), ctx)
    assert receipt["status"] == "committed", receipt
    assert service.store._conn.execute("SELECT count(*) FROM capture_chunks").fetchone()[0] == 1


async def test_retained_body_reads_back_then_expires_but_timeline_survives(service, ctx):
    capture = service.capture
    capture.set_source_capture_enabled(True, actor="test-owner")
    receipt = await capture.incoming(event("可以被读回来的原文", message_id="p1-native-2"), ctx)
    assert receipt["status"] == "committed", receipt

    read = capture.read_original(receipt["source_key"])
    assert read["ok"] is True and read["status"] == "available"
    assert read["body"] == "可以被读回来的原文"
    assert read["chunks"] == 1
    assert read["created_at"] > 0 and read["expires_at"] > read["created_at"]
    assert read["expires_at"] - read["created_at"] == DEFAULT_RETENTION_SECONDS

    timeline_id = receipt["source_ref"].removeprefix("timeline:")
    before = service.store._conn.execute("SELECT count(*) FROM timeline WHERE id=?", (timeline_id,)).fetchone()[0]
    assert before == 1

    purged = capture.purge_expired(now=read["expires_at"] + 1)
    assert purged["deleted_chunks"] == 1 and purged["sources"] == 1

    expired = capture.read_original(receipt["source_key"])
    assert expired["ok"] is False and expired["status"] == "expired"
    # Retention only drops the retained body; the timeline projection is untouched.
    assert service.store._conn.execute("SELECT count(*) FROM timeline WHERE id=?", (timeline_id,)).fetchone()[0] == 1
    assert capture.purge_expired(now=read["expires_at"] + 2)["deleted_chunks"] == 0


async def test_status_reports_switch_and_retention(service):
    capture = service.capture
    capture.set_source_capture_enabled(False, actor="status-check")
    status = capture.status()
    assert status["source_capture"]["enabled"] is False
    assert status["source_capture"]["explicit"] is True
    assert status["retention_seconds"] == DEFAULT_RETENTION_SECONDS
    assert status["retained_chunks"] == 0


async def test_legacy_capture_chunks_gain_retention_columns_without_losing_rows(tmp_path):
    path = Path(tmp_path) / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE capture_chunks (source_key TEXT NOT NULL, seq INTEGER NOT NULL, char_offset INTEGER NOT NULL,"
        " byte_offset INTEGER NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(source_key,seq))"
    )
    legacy.execute(
        "INSERT INTO capture_chunks VALUES ('legacy-key',0,0,0,'旧原文','deadbeef')"
    )
    legacy.commit()
    legacy.close()

    store = MemoryStore(path)
    try:
        store.initialize()
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(capture_chunks)").fetchall()}
        assert {"created_at", "expires_at"} <= columns
        row = store._conn.execute(
            "SELECT body,created_at,expires_at FROM capture_chunks WHERE source_key='legacy-key'"
        ).fetchone()
        assert row["body"] == "旧原文"
        assert row["created_at"] == 0 and row["expires_at"] == 0
        capture = SourceCapture(store)
        assert capture.read_body("legacy-key")["status"] == "missing"  # no source row, old chunks are untouched
        assert capture.purge_expired(now=time.time() + 10**9)["deleted_chunks"] == 0
    finally:
        store.close()
