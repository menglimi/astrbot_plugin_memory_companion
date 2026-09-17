"""Durable summary work: event ownership, bounded calls and per-batch recovery."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import clean_text, json_dumps, json_loads, utc_now
from .sensitive_data import redact_sensitive_text, redact_sensitive_value


class SummaryBatchStore:
    """Batch queue state; the store owns the transaction and the clock."""

    BUDGET_RETRY_REASON = "budget"

    @classmethod
    def _due_clause(cls, alias: str = "") -> str:
        """The single definition of "this batch may be dispatched now".

        ``next_retry_at`` is NULL for a batch that was never scheduled (or was
        explicitly released) and a deadline otherwise.  The predicate lives
        here so no caller can write its own comparison: the previous
        ``next_retry_at <= ?`` form compared the empty-string default as
        "always due", which made the queue re-select a batch on every message.

        A budget deferral is the one deadline that can lapse early: its
        duration is derived from the sliding hourly window, so when that window
        is empty again the batch must become dispatchable immediately instead
        of waiting out a timestamp that no longer describes reality.
        """
        prefix = f"{clean_text(alias, 40)}." if clean_text(alias, 40) else ""
        return (
            f"({prefix}next_retry_at IS NULL OR {prefix}next_retry_at <= ?"
            f" OR ({prefix}retry_reason='{cls.BUDGET_RETRY_REASON}' AND NOT EXISTS("
            f"SELECT 1 FROM summary_batch_calls budget_call"
            f" WHERE budget_call.session_id={prefix}session_id"
            f" AND budget_call.automatic=1 AND budget_call.attempted_at>?)))"
        )

    @staticmethod
    def _due_params() -> list[str]:
        """Parameters matching ``_due_clause`` in order."""
        now = datetime.now(timezone.utc)
        return [
            utc_now(),
            (now - timedelta(hours=1)).isoformat(timespec='seconds'),
        ]

    def _initialize_summary_batches(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS summary_batches (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, scope TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', automatic_calls INTEGER NOT NULL DEFAULT 0,
                repair_used INTEGER NOT NULL DEFAULT 0, next_retry_at TEXT DEFAULT NULL,
                retry_reason TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}',
                memory_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_summary_batches_queue
                ON summary_batches(session_id, state, next_retry_at);
            CREATE TABLE IF NOT EXISTS summary_batch_events (
                event_id TEXT PRIMARY KEY REFERENCES timeline(id) ON DELETE CASCADE,
                batch_id TEXT NOT NULL REFERENCES summary_batches(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_summary_batch_events_batch ON summary_batch_events(batch_id);
            CREATE TABLE IF NOT EXISTS summary_batch_calls (
                id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES summary_batches(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL, attempted_at TEXT NOT NULL, automatic INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_summary_batch_calls_budget
                ON summary_batch_calls(session_id, automatic, attempted_at);
        """)

    def _migrate_summary_batch_retry_state_sync(self) -> None:
        """Bring legacy batch rows to the nullable retry state.

        Existing databases were created with ``next_retry_at NOT NULL DEFAULT
        ''``, and SQLite cannot drop a NOT NULL constraint in place, so those
        tables are rebuilt.  ``retry_reason`` is added afterwards, and legacy
        empty strings are normalized to NULL because the empty string was the
        value that made the queue predicate compare as "always due".
        """
        columns = [
            row
            for row in self._conn.execute("PRAGMA table_info(summary_batches)").fetchall()
        ]
        if not columns:
            return
        retry_column = next(
            (row for row in columns if clean_text(row["name"], 40) == "next_retry_at"),
            None,
        )
        if retry_column is None:
            return
        if int(retry_column["notnull"] or 0) == 1:
            self._rebuild_summary_batches_nullable_retry_sync(columns)
        if not any(clean_text(row["name"], 40) == "retry_reason" for row in columns):
            self._conn.execute(
                "ALTER TABLE summary_batches ADD COLUMN retry_reason TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()
        if self._conn.execute(
            "SELECT COUNT(*) FROM summary_batches WHERE next_retry_at=''"
        ).fetchone()[0]:
            self._conn.execute(
                "UPDATE summary_batches SET next_retry_at=NULL WHERE next_retry_at=''"
            )
            self._conn.commit()

    def _rebuild_summary_batches_nullable_retry_sync(self, columns: list[Any]) -> None:
        copy_columns = [
            "id",
            "session_id",
            "scope",
            "state",
            "automatic_calls",
            "repair_used",
            "next_retry_at",
            "last_error",
            "metadata",
            "memory_id",
            "created_at",
            "updated_at",
        ]
        if any(clean_text(row["name"], 40) == "retry_reason" for row in columns):
            copy_columns.append("retry_reason")
        target_columns = ", ".join(
            "NULLIF(next_retry_at, '')" if name == "next_retry_at" else name
            for name in copy_columns
        )
        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            with self._transaction_sync():
                self._conn.execute("""
                    CREATE TABLE summary_batches_nullable_retry (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, scope TEXT NOT NULL,
                        state TEXT NOT NULL DEFAULT 'pending', automatic_calls INTEGER NOT NULL DEFAULT 0,
                        repair_used INTEGER NOT NULL DEFAULT 0, next_retry_at TEXT DEFAULT NULL,
                        retry_reason TEXT NOT NULL DEFAULT '',
                        last_error TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}',
                        memory_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    )
                """)
                self._conn.execute(
                    f"INSERT INTO summary_batches_nullable_retry({', '.join(copy_columns)}) "
                    f"SELECT {target_columns} FROM summary_batches"
                )
                self._conn.execute("DROP TABLE summary_batches")
                self._conn.execute(
                    "ALTER TABLE summary_batches_nullable_retry RENAME TO summary_batches"
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_summary_batches_queue "
                    "ON summary_batches(session_id, state, next_retry_at)"
                )
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")

    def _create_summary_batch_sync(self, session_id, scope, rows, metadata=None):
        ids = [str(row['id']) for row in rows]
        batch_id = 'sb_' + hashlib.sha256(json_dumps([session_id, ids]).encode('utf-8')).hexdigest()[:32]
        now = utc_now()
        self._conn.execute(
            'INSERT OR IGNORE INTO summary_batches(id,session_id,scope,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            (batch_id, session_id, scope, json_dumps(redact_sensitive_value(metadata or {})), now, now),
        )
        for event_id in ids:
            self._conn.execute(
                'INSERT OR IGNORE INTO summary_batch_events(event_id,batch_id) VALUES(?,?)',
                (event_id, batch_id),
            )
        return batch_id

    async def create_summary_batch(self, session_id, scope, rows):
        def create():
            with self._lock, self._transaction_sync():
                for row in rows:
                    source = self._conn.execute('SELECT session_id,scope,summarized_at FROM timeline WHERE id=?', (row['id'],)).fetchone()
                    if not source or source['session_id'] != session_id or source['scope'] != scope or source['summarized_at']:
                        raise ValueError('summary event is outside the pending session')
                return self._create_summary_batch_sync(session_id, scope, rows)
        return await asyncio.to_thread(create)

    async def migrate_summary_failure(self, session_id: str, max_calls: int, cooldown: int = 0) -> None:
        """Import the old session blocker once; preserve its candidate and raw events."""
        def migrate():
            with self._lock, self._transaction_sync():
                failure = self._conn.execute('SELECT * FROM summary_failures WHERE session_id=?', (session_id,)).fetchone()
                if not failure:
                    return
                bounds = [self._conn.execute('SELECT occurred_at,created_at,id FROM timeline WHERE id=? AND session_id=?',
                          (failure[key], session_id)).fetchone() for key in ('start_timeline_id', 'end_timeline_id')]
                if all(bounds):
                    bounds = sorted(tuple(bound) for bound in bounds)
                    rows = self._conn.execute('''SELECT * FROM timeline t WHERE session_id=? AND scope=? AND summarized_at=''
                        AND (occurred_at,created_at,id) >= (?,?,?) AND (occurred_at,created_at,id) <= (?,?,?)
                        AND NOT EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.event_id=t.id)
                        ORDER BY occurred_at,created_at,id''',
                        (session_id, failure['scope'], *tuple(bounds[0]), *tuple(bounds[1]))).fetchall()
                else:
                    # Never guess a range when a legacy boundary was deleted.
                    rows = []
                metadata = json_loads(failure['metadata'], {})
                metadata = metadata if isinstance(metadata, dict) else {}
                metadata.update(legacy_retry_count=failure['retry_count'], legacy_failure=True,
                                start_timeline_id=failure['start_timeline_id'], end_timeline_id=failure['end_timeline_id'])
                batch_id = self._create_summary_batch_sync(session_id, failure['scope'], rows, metadata)
                is_evidence = metadata.get('state') == 'evidence_quarantine'
                due = metadata.get('cooldown_at') or failure['updated_at']
                try:
                    due = (datetime.fromisoformat(due) + timedelta(seconds=int(metadata.get('cooldown_seconds', cooldown)))).isoformat(timespec='seconds')
                except (ValueError, TypeError):
                    due = utc_now()
                self._conn.execute('''UPDATE summary_batches SET state=?,automatic_calls=?,next_retry_at=?,retry_reason='',last_error=?
                    WHERE id=?''', ('retry_pending' if rows else 'quarantined', max(0, max_calls - 1), due,
                                    'repair:旧批次需要纠正引用、移除无来源的结论并同步修正正文。' if is_evidence else failure['last_error'], batch_id))
                self._conn.execute('DELETE FROM summary_failures WHERE session_id=?', (session_id,))
        await asyncio.to_thread(migrate)

    async def get_summary_batch(self, batch_id: str):
        def read():
            with self._lock:
                row = self._conn.execute('SELECT * FROM summary_batches WHERE id=?', (batch_id,)).fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(read)

    async def next_summary_batch(self, session_id: str, *, force=False):
        def read():
            with self._lock:
                states = "('pending','retry_pending','quarantined')" if force else "('pending','retry_pending')"
                due = '' if force else f'AND {self._due_clause("b")}'
                params = [session_id] if force else [session_id, *self._due_params()]
                row = self._conn.execute(f'''SELECT * FROM summary_batches b WHERE session_id=? AND state IN {states} {due}
                    AND EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.batch_id=b.id)
                    ORDER BY created_at,id LIMIT 1''', params).fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(read)

    async def summary_batch_rows(self, batch_id: str):
        def read():
            with self._lock:
                return [dict(r) for r in self._conn.execute('''SELECT t.* FROM timeline t
                    JOIN summary_batch_events e ON t.id=e.event_id WHERE e.batch_id=? AND t.summarized_at=''
                    ORDER BY t.occurred_at,t.created_at,t.id''', (batch_id,)).fetchall()]
        return await asyncio.to_thread(read)

    @staticmethod
    def _budget_release_at(oldest_attempt: Any, now: datetime) -> str:
        """Return the exact moment the sliding hourly budget frees a slot.

        The budget is temporary by construction, so the deadline is derived
        from the oldest counted call rather than from a hard-coded cooldown.
        """
        release = now + timedelta(hours=1)
        text = clean_text(oldest_attempt, 40)
        if text:
            try:
                oldest = datetime.fromisoformat(text)
            except ValueError:
                oldest = None
            if oldest is not None:
                if oldest.tzinfo is None:
                    oldest = oldest.replace(tzinfo=timezone.utc)
                release = oldest + timedelta(hours=1)
        if release <= now:
            release = now + timedelta(seconds=1)
        return release.isoformat(timespec='seconds')

    async def reserve_summary_call(self, batch_id, *, max_calls, hourly_limit, repair=False, force=False, lease_seconds=240):
        """Commit the reservation before the request, including repairs and fallbacks.

        Every refusal writes its batch state inside the same transaction that
        made the decision.  A temporary budget shortage defers the batch to the
        moment the budget frees up, while an exhausted lifetime call count is
        final and quarantines it; treating both as one bare ``return False``
        left deferred batches selectable on every following message.
        """
        def reserve():
            now = datetime.now(timezone.utc)
            with self._lock, self._transaction_sync():
                row = self._conn.execute('SELECT * FROM summary_batches WHERE id=?', (batch_id,)).fetchone()
                if not row or row['state'] in {'completed', 'no_memory'}:
                    return False
                if not force:
                    if row['state'] == 'quarantined':
                        return False
                    if row['automatic_calls'] >= max_calls or (repair and row['repair_used']):
                        self._conn.execute("UPDATE summary_batches SET state='quarantined',updated_at=? WHERE id=?", (utc_now(), batch_id))
                        return False
                    window = self._conn.execute('''SELECT COUNT(*),MIN(attempted_at) FROM summary_batch_calls
                        WHERE session_id=? AND automatic=1 AND attempted_at>?''',
                        (row['session_id'], (now - timedelta(hours=1)).isoformat(timespec='seconds'))).fetchone()
                    if int(window[0] or 0) >= hourly_limit:
                        # Temporary by construction: the slot opens when the
                        # oldest counted call ages out of the sliding window,
                        # so record that exact moment and never quarantine a
                        # batch that only ran out of hourly budget.
                        self._conn.execute(
                            "UPDATE summary_batches SET next_retry_at=?,retry_reason=?,updated_at=? WHERE id=?",
                            (self._budget_release_at(window[1], now), self.BUDGET_RETRY_REASON, utc_now(), batch_id),
                        )
                        return False
                self._conn.execute('''UPDATE summary_batches SET automatic_calls=automatic_calls+?,repair_used=MAX(repair_used,?),
                    state='retry_pending',next_retry_at=?,retry_reason='',updated_at=? WHERE id=?''',
                    (int(not force), int(repair and not force), (now + timedelta(seconds=lease_seconds)).isoformat(timespec='seconds'), utc_now(), batch_id))
                self._conn.execute('INSERT INTO summary_batch_calls(batch_id,session_id,attempted_at,automatic) VALUES(?,?,?,?)',
                                   (batch_id, row['session_id'], utc_now(), int(not force)))
                # The hourly budget needs only recent reservations; lifetime counts live on the batch.
                self._conn.execute('DELETE FROM summary_batch_calls WHERE attempted_at<?', ((now - timedelta(days=2)).isoformat(timespec='seconds'),))
                return True
        return await asyncio.to_thread(reserve)

    async def defer_summary_batch(self, batch_id, error, *, quarantine=False, delay=60):
        def update():
            with self._lock, self._transaction_sync():
                self._conn.execute("UPDATE summary_batches SET state=?,last_error=?,next_retry_at=?,retry_reason='',updated_at=? WHERE id=?",
                    ('quarantined' if quarantine else 'retry_pending', clean_text(redact_sensitive_text(error), 1800),
                     (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec='seconds'), utc_now(), batch_id))
        await asyncio.to_thread(update)

    async def release_summary_batch(self, batch_id: str, *, mode: str = "retry") -> dict[str, Any]:
        """Release a quarantined batch's events after explicit human review.

        Quarantine keeps failing content away from the automatic path, but it
        also keeps owning its timeline events: the pending window excludes
        assigned events, so those messages could never reach a later batch and
        the raw history would never become long-term memory.  This is the
        review step that ends the freeze, and it only ever runs on request.

        - ``retry``: drop the ownership rows and re-open the batch, so the
          events become eligible for a new batch.
        - ``discard``: mark the owned events summarized and close the batch,
          accepting the loss instead of leaving them dangling.
        """
        normalized_mode = clean_text(mode, 20).lower()
        if normalized_mode not in {"retry", "discard"}:
            return {"ok": False, "error": "unsupported_release_mode", "mode": normalized_mode}

        def release():
            with self._lock, self._transaction_sync():
                row = self._conn.execute(
                    'SELECT * FROM summary_batches WHERE id=?', (batch_id,)
                ).fetchone()
                if not row:
                    return {"ok": False, "error": "batch_not_found", "batch_id": batch_id}
                event_ids = [
                    clean_text(item[0], 160)
                    for item in self._conn.execute(
                        'SELECT event_id FROM summary_batch_events WHERE batch_id=?', (batch_id,)
                    )
                ]
                event_ids = [event_id for event_id in event_ids if event_id]
                if normalized_mode == 'discard' and event_ids:
                    placeholders = ','.join('?' for _ in event_ids)
                    self._conn.execute(
                        f"UPDATE timeline SET summarized_at=? WHERE id IN ({placeholders}) AND summarized_at=''",
                        [utc_now(), *event_ids],
                    )
                self._conn.execute('DELETE FROM summary_batch_events WHERE batch_id=?', (batch_id,))
                if normalized_mode == 'retry':
                    state = 'retry_pending'
                    self._conn.execute(
                        "UPDATE summary_batches SET state=?,next_retry_at=NULL,retry_reason='',repair_used=0,updated_at=? WHERE id=?",
                        (state, utc_now(), batch_id),
                    )
                else:
                    state = 'completed'
                    self._conn.execute(
                        "UPDATE summary_batches SET state=?,next_retry_at=NULL,retry_reason='',updated_at=? WHERE id=?",
                        (state, utc_now(), batch_id),
                    )
                return {
                    "ok": True,
                    "batch_id": batch_id,
                    "mode": normalized_mode,
                    "released_events": len(event_ids),
                    "state": state,
                }

        return await asyncio.to_thread(release)

    async def finish_summary_batch(self, batch_id, event_ids, *, memory_id='', no_memory=False, reason='', record=None):
        def finish():
            result_memory_id = memory_id
            with self._lock, self._transaction_sync():
                owned = {r[0] for r in self._conn.execute('SELECT event_id FROM summary_batch_events WHERE batch_id=?', (batch_id,))}
                consumed = set(event_ids)
                if not consumed or not consumed <= owned:
                    raise ValueError('summary completion has invalid event ownership')
                # A reduced prompt budget must release the unconsumed tail for later work.
                for event_id in owned - consumed:
                    self._conn.execute('DELETE FROM summary_batch_events WHERE event_id=?', (event_id,))
                if record is not None:
                    result_memory_id = self._insert_memory_sync(record, _commit=False)
                if not no_memory:
                    self._mark_timeline_summarized_sync(list(consumed), _commit=False)
                self._conn.execute('UPDATE summary_batches SET state=?,memory_id=?,last_error=?,updated_at=? WHERE id=?',
                    ('no_memory' if no_memory else 'completed', result_memory_id, clean_text(redact_sensitive_text(reason), 500), utc_now(), batch_id))
                return result_memory_id
        return await asyncio.to_thread(finish)

    async def summary_progress(self) -> dict[str, Any]:
        def read():
            with self._lock:
                counts = dict(self._conn.execute('SELECT state,COUNT(*) FROM summary_batches GROUP BY state').fetchall())
                timeline = self._conn.execute('SELECT COUNT(*),MAX(created_at) FROM timeline').fetchone()
                memories = self._conn.execute("SELECT COUNT(*),MAX(created_at) FROM memories WHERE memory_type='conversation_summary' AND review_status!='pending'").fetchone()
                legacy = self._conn.execute('SELECT COUNT(*) FROM summary_failures').fetchone()[0]
                # Quarantined batches own their events permanently, so report
                # how many raw events are frozen behind human review.
                frozen = self._conn.execute('''SELECT COUNT(*) FROM summary_batch_events e
                    JOIN summary_batches b ON b.id=e.batch_id WHERE b.state='quarantined' ''').fetchone()[0]
                return {'raw_events': timeline[0], 'last_recorded_at': timeline[1] or '',
                        'conversation_memories': memories[0], 'last_summary_at': memories[1] or '',
                        'pending_batches': counts.get('pending', 0) + counts.get('retry_pending', 0),
                        'quarantined_batches': counts.get('quarantined', 0) + legacy,
                        'frozen_events': int(frozen or 0),
                        'no_memory_batches': counts.get('no_memory', 0)}
        return await asyncio.to_thread(read)
