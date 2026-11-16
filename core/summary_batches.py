"""Durable summary work: event ownership, bounded calls and per-batch recovery."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
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
            f"(({prefix}next_retry_at IS NULL OR {prefix}next_retry_at <= ?"
            f" OR ({prefix}retry_reason='{cls.BUDGET_RETRY_REASON}' AND NOT EXISTS("
            f"SELECT 1 FROM summary_batch_calls budget_call"
            f" WHERE budget_call.session_id={prefix}session_id"
            f" AND budget_call.automatic=1 AND budget_call.attempted_at>?)))"
            f" AND (COALESCE({prefix}lease_token,'')='' OR {prefix}lease_expires_at IS NULL"
            f" OR {prefix}lease_expires_at<=?))"
        )

    @staticmethod
    def _due_params() -> list[str]:
        """Parameters matching ``_due_clause`` in order."""
        now = datetime.now(timezone.utc)
        return [
            utc_now(),
            (now - timedelta(hours=1)).isoformat(timespec='seconds'),
            utc_now(),
        ]

    def _initialize_summary_batches(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS summary_batches (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, scope TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', automatic_calls INTEGER NOT NULL DEFAULT 0,
                repair_used INTEGER NOT NULL DEFAULT 0, next_retry_at TEXT DEFAULT NULL,
                retry_reason TEXT NOT NULL DEFAULT '',
                lease_token TEXT NOT NULL DEFAULT '', lease_expires_at TEXT DEFAULT NULL,
                last_error TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}',
                memory_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_summary_batches_queue
                ON summary_batches(session_id, state, next_retry_at);
            CREATE INDEX IF NOT EXISTS idx_summary_batches_global_queue
                ON summary_batches(state, next_retry_at, created_at, id, session_id);
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

    def _ensure_summary_batch_indexes_sync(self) -> None:
        """Idempotently create indexes needed by both local and global queues."""
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_batches_queue "
            "ON summary_batches(session_id, state, next_retry_at)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_batches_global_queue "
            "ON summary_batches(state, next_retry_at, created_at, id, session_id)"
        )

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
            # The rebuild recreates the table with ``retry_reason`` already in
            # place, so the snapshot taken before it is stale: re-read the
            # columns or the follow-up ALTER would fail with "duplicate column
            # name" on exactly the legacy shape this method exists to fix.
            columns = [
                row
                for row in self._conn.execute("PRAGMA table_info(summary_batches)").fetchall()
            ]
        if not any(clean_text(row["name"], 40) == "retry_reason" for row in columns):
            self._conn.execute(
                "ALTER TABLE summary_batches ADD COLUMN retry_reason TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()
            columns = self._conn.execute("PRAGMA table_info(summary_batches)").fetchall()
        existing_names = {clean_text(row["name"], 40) for row in columns}
        if "lease_token" not in existing_names:
            self._conn.execute(
                "ALTER TABLE summary_batches ADD COLUMN lease_token TEXT NOT NULL DEFAULT ''"
            )
        if "lease_expires_at" not in existing_names:
            self._conn.execute(
                "ALTER TABLE summary_batches ADD COLUMN lease_expires_at TEXT DEFAULT NULL"
            )
        if self._conn.execute(
            "SELECT COUNT(*) FROM summary_batches WHERE next_retry_at=''"
        ).fetchone()[0]:
            self._conn.execute(
                "UPDATE summary_batches SET next_retry_at=NULL WHERE next_retry_at=''"
            )
            self._conn.commit()
        # The table may have been rebuilt above, or created by an older
        # release without the global recovery index.
        self._ensure_summary_batch_indexes_sync()
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
        for optional_column in ("lease_token", "lease_expires_at"):
            if any(clean_text(row["name"], 40) == optional_column for row in columns):
                copy_columns.append(optional_column)
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
                        lease_token TEXT NOT NULL DEFAULT '', lease_expires_at TEXT DEFAULT NULL,
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
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_summary_batches_global_queue "
                    "ON summary_batches(state, next_retry_at, created_at, id, session_id)"
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

    async def create_summary_batch(self, session_id, scope, rows, metadata=None):
        def create():
            with self._lock, self._transaction_sync():
                for row in rows:
                    source = self._conn.execute('SELECT session_id,scope,summarized_at FROM timeline WHERE id=?', (row['id'],)).fetchone()
                    if not source or source['session_id'] != session_id or source['scope'] != scope or source['summarized_at']:
                        raise ValueError('summary event is outside the pending session')
                return self._create_summary_batch_sync(session_id, scope, rows, metadata=metadata)
        return await asyncio.to_thread(create)

    async def migrate_summary_failure(self, session_id: str, max_calls: int, cooldown: int = 0) -> None:
        """Import the old session blocker once; preserve its candidate and raw events."""
        def migrate():
            with self._lock, self._transaction_sync():
                failure = self._conn.execute('SELECT * FROM summary_failures WHERE session_id=?', (session_id,)).fetchone()
                if not failure:
                    return
                bounds = [self._conn.execute('''SELECT occurred_at,created_at,id,
                          COALESCE(julianday(NULLIF(occurred_at,'')),julianday(NULLIF(created_at,'')),0) AS event_time
                          FROM timeline WHERE id=? AND session_id=?''',
                          (failure[key], session_id)).fetchone() for key in ('start_timeline_id', 'end_timeline_id')]
                if all(bounds):
                    bounds.sort(key=lambda bound: (float(bound['event_time']), bound['created_at'], bound['id']))
                    rows = self._conn.execute('''SELECT * FROM timeline t WHERE session_id=? AND scope=? AND summarized_at=''
                        AND (COALESCE(julianday(NULLIF(t.occurred_at,'')),julianday(NULLIF(t.created_at,'')),0),t.created_at,t.id) >= (?,?,?)
                        AND (COALESCE(julianday(NULLIF(t.occurred_at,'')),julianday(NULLIF(t.created_at,'')),0),t.created_at,t.id) <= (?,?,?)
                        AND NOT EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.event_id=t.id)
                        ORDER BY COALESCE(julianday(NULLIF(t.occurred_at,'')),julianday(NULLIF(t.created_at,'')),0),t.created_at,t.id''',
                        (session_id, failure['scope'], bounds[0]['event_time'], bounds[0]['created_at'], bounds[0]['id'],
                         bounds[1]['event_time'], bounds[1]['created_at'], bounds[1]['id'])).fetchall()
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

    async def get_due_summary_batch(
        self,
        batch_id: str,
        *,
        session_id: str,
        scope: str,
    ) -> dict[str, Any] | None:
        """Read one named batch only when it still belongs to the due queue."""
        normalized_id = clean_text(batch_id, 160)
        normalized_session = clean_text(session_id, 200)
        normalized_scope = clean_text(scope, 40).lower()
        if not normalized_id or not normalized_session or normalized_scope not in {"private", "group"}:
            return None

        def read():
            with self._lock:
                row = self._conn.execute(
                    f"""SELECT b.* FROM summary_batches b
                        WHERE b.id=? AND b.session_id=? AND b.scope=?
                          AND b.state IN ('pending','retry_pending')
                          AND EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.batch_id=b.id)
                          AND {self._due_clause('b')}""",
                    [normalized_id, normalized_session, normalized_scope, *self._due_params()],
                ).fetchone()
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

    async def next_due_summary_batches(
        self,
        *,
        limit: int = 8,
        exclude_session_ids: set[str] | list[str] | tuple[str, ...] | None = None,
        after_session_id: str = "",
    ) -> list[dict[str, Any]]:
        """Return one due batch per session, ordered by the oldest work first.

        The normal message path asks for a batch for one known session.  A
        silent session has no message to wake it, so the recovery dispatcher
        needs a global queue view.  This query deliberately returns at most
        one eligible batch for each session; a slow or repeatedly failing
        session therefore cannot consume the whole recovery round.

        ``exclude_session_ids`` is used by the service while a worker already
        owns a session.  The filtering happens in SQL so a completed query
        cannot race a worker into scheduling a second recovery task for the
        same session during the same round.  ``after_session_id`` is a
        best-effort ring cursor: when supplied, candidates are rotated after
        that session before applying ``limit``.  This keeps a bounded recovery
        loop fair when one old session keeps producing new work or fails
        quickly.
        """
        batch_limit = max(1, min(int(limit or 1), 1000))
        excluded = sorted({clean_text(item, 200) for item in (exclude_session_ids or ()) if clean_text(item, 200)})
        cursor = clean_text(after_session_id, 200)

        def read() -> list[dict[str, Any]]:
            with self._lock:
                exclusion_sql = ""
                params: list[Any] = []
                if excluded:
                    placeholders = ",".join("?" for _ in excluded)
                    exclusion_sql = f"AND b.session_id NOT IN ({placeholders})"
                    params.extend(excluded)

                # Keep the inner candidate predicate identical to the outer
                # one.  A deferred older batch must not hide a newer due batch
                # for the same session, while a non-due older batch is ignored.
                outer_due_params = self._due_params()
                inner_due_params = self._due_params()
                order_sql = (
                    "ORDER BY b.created_at, b.id LIMIT ?"
                    if not cursor
                    else "ORDER BY CASE WHEN b.session_id>? THEN 0 ELSE 1 END, "
                         "b.session_id, b.created_at, b.id LIMIT ?"
                )
                query = f"""
                    SELECT b.*
                    FROM summary_batches b
                    WHERE b.state IN ('pending','retry_pending')
                      {exclusion_sql}
                      AND EXISTS(
                          SELECT 1 FROM summary_batch_events e
                          WHERE e.batch_id=b.id
                      )
                      AND {self._due_clause('b')}
                      AND NOT EXISTS(
                          SELECT 1
                          FROM summary_batches earlier
                          WHERE earlier.session_id=b.session_id
                            AND earlier.state IN ('pending','retry_pending')
                            AND EXISTS(
                                SELECT 1 FROM summary_batch_events earlier_event
                                WHERE earlier_event.batch_id=earlier.id
                            )
                            AND {self._due_clause('earlier')}
                            AND (
                                earlier.created_at < b.created_at
                                OR (earlier.created_at = b.created_at AND earlier.id < b.id)
                            )
                      )
                    {order_sql}
                """
                params.extend(outer_due_params)
                params.extend(inner_due_params)
                if cursor:
                    params.extend([cursor, batch_limit])
                else:
                    params.append(batch_limit)
                rows = self._conn.execute(query, params).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(read)

    async def summary_recovery_sessions(self, *, limit=1, after_session_id="", exclude_session_ids=()):
        """Discover quiet sessions with due batches or unassigned originals."""
        def read():
            with self._lock:
                excluded = sorted(set(exclude_session_ids))
                exclusion = ""
                if excluded:
                    exclusion = "WHERE session_id NOT IN (" + ",".join("?" for _ in excluded) + ")"
                rows = self._conn.execute(
                    f"""SELECT session_id, scope, MIN(created_at) AS created_at FROM (
                        SELECT b.session_id,b.scope,b.created_at FROM summary_batches b
                        WHERE b.state IN ('pending','retry_pending')
                          AND EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.batch_id=b.id)
                          AND {self._due_clause('b')}
                        UNION ALL
                        SELECT t.session_id,t.scope,t.created_at FROM timeline t
                        WHERE t.summarized_at='' AND t.scope IN ('private','group')
                          AND NOT EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.event_id=t.id)
                    ) {exclusion} GROUP BY session_id,scope
                    ORDER BY CASE WHEN session_id>? THEN 0 ELSE 1 END,session_id,created_at LIMIT ?""",
                    [*self._due_params(), *excluded, clean_text(after_session_id, 200), max(1, int(limit))],
                ).fetchall()
                return [dict(row) for row in rows]
        return await asyncio.to_thread(read)

    async def summary_budget_available(self, session_id: str, hourly_limit: int) -> bool:
        """Cheap admission hint; reserve_summary_call remains the final authority."""
        def read():
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec='seconds')
            with self._lock:
                calls = self._conn.execute(
                    'SELECT COUNT(*) FROM summary_batch_calls WHERE session_id=? AND automatic=1 AND attempted_at>?',
                    (session_id, cutoff),
                ).fetchone()[0]
                return calls < max(1, hourly_limit)
        return await asyncio.to_thread(read)

    async def summary_batch_context(self, batch_id: str) -> dict[str, Any] | None:
        """Return the batch snapshot and every owned event's persisted context.

        Keep the sources separate so a caller can reject contradictory values
        instead of letting batch metadata silently overwrite event metadata.
        """
        normalized_id = clean_text(batch_id, 160)

        def read() -> dict[str, Any] | None:
            if not normalized_id:
                return None
            with self._lock:
                batch = self._conn.execute(
                    """
                    SELECT session_id, scope, metadata
                    FROM summary_batches WHERE id=?
                    """,
                    (normalized_id,),
                ).fetchone()
                if not batch:
                    return None
                batch_metadata = json_loads(batch["metadata"], {})
                if not isinstance(batch_metadata, dict):
                    batch_metadata = {}
                event_rows = self._conn.execute(
                    """
                    SELECT t.id, t.event_type, t.session_id, t.scope, t.subject_id, t.object_id,
                           t.metadata
                    FROM summary_batch_events e
                    JOIN timeline t ON t.id=e.event_id
                    WHERE e.batch_id=?
                    ORDER BY COALESCE(julianday(NULLIF(t.occurred_at,'')),
                                      julianday(NULLIF(t.created_at,'')),0),
                             t.created_at, t.id
                    """,
                    (normalized_id,),
                ).fetchall()
                return {
                    "session_id": clean_text(batch["session_id"], 200),
                    "scope": clean_text(batch["scope"], 40),
                    "batch_metadata": batch_metadata,
                    "events": [
                        {
                            "id": clean_text(row["id"], 160),
                            "event_type": clean_text(row["event_type"], 40),
                            "session_id": clean_text(row["session_id"], 200),
                            "scope": clean_text(row["scope"], 40),
                            "subject_id": clean_text(row["subject_id"], 120),
                            "object_id": clean_text(row["object_id"], 120),
                            "metadata": (
                                json_loads(row["metadata"], {})
                                if isinstance(json_loads(row["metadata"], {}), dict)
                                else {}
                            ),
                        }
                        for row in event_rows
                    ],
                }

        return await asyncio.to_thread(read)

    async def summary_batch_rows(self, batch_id: str):
        def read():
            with self._lock:
                return [dict(r) for r in self._conn.execute('''SELECT t.* FROM timeline t
                    JOIN summary_batch_events e ON t.id=e.event_id WHERE e.batch_id=? AND t.summarized_at=''
                    ORDER BY COALESCE(julianday(NULLIF(t.occurred_at,'')),julianday(NULLIF(t.created_at,'')),0),
                             t.created_at,t.id''', (batch_id,)).fetchall()]
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

    async def reserve_summary_call(
        self,
        batch_id,
        *,
        max_calls,
        hourly_limit,
        repair=False,
        force=False,
        lease_seconds=240,
        lease_token="",
    ):
        """Commit the reservation before the request, including repairs and fallbacks.

        Every refusal writes its batch state inside the same transaction that
        made the decision.  A temporary budget shortage defers the batch to the
        moment the budget frees up, while an exhausted lifetime call count is
        final and quarantines it; treating both as one bare ``return False``
        left deferred batches selectable on every following message.
        """
        owner_token = clean_text(lease_token, 160)
        if not owner_token:
            # Keep older direct callers (and administrative repair scripts)
            # compatible while the service uses an explicit per-worker token.
            # The token is scoped to this store instance, so two independent
            # processes cannot accidentally share the compatibility lease.
            owner_token = getattr(self, "_legacy_summary_lease_token", "")
            if not owner_token:
                owner_token = "legacy:" + secrets.token_hex(16)
                self._legacy_summary_lease_token = owner_token

        def reserve():
            now = datetime.now(timezone.utc)
            now_text = now.isoformat(timespec="seconds")
            lease_deadline = (
                now + timedelta(seconds=max(1, int(lease_seconds or 1)))
            ).isoformat(timespec="seconds")
            with self._lock, self._transaction_sync():
                row = self._conn.execute('SELECT * FROM summary_batches WHERE id=?', (batch_id,)).fetchone()
                if not row or row['state'] in {'completed', 'no_memory'}:
                    return False
                row_owner = clean_text(row['lease_token'], 160)
                row_lease_expires = clean_text(row['lease_expires_at'], 40)
                active_owner = bool(row_owner and row_lease_expires and row_lease_expires > now_text)
                same_owner = bool(owner_token and active_owner and owner_token == row_owner)
                if active_owner and not same_owner:
                    return False
                if not force:
                    if row['state'] not in {'pending', 'retry_pending'}:
                        return False
                    if not same_owner:
                        due = self._conn.execute(
                            f"SELECT 1 FROM summary_batches b WHERE b.id=? AND {self._due_clause('b')}",
                            [batch_id, *self._due_params()],
                        ).fetchone()
                        if not due:
                            return False
                    if row['automatic_calls'] >= max_calls:
                        self._conn.execute(
                            "UPDATE summary_batches SET state='quarantined',lease_token='',lease_expires_at=NULL,updated_at=? WHERE id=?",
                            (utc_now(), batch_id),
                        )
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
                            "UPDATE summary_batches SET next_retry_at=?,retry_reason=?,lease_token='',lease_expires_at=NULL,updated_at=? WHERE id=?",
                            (self._budget_release_at(window[1], now), self.BUDGET_RETRY_REASON, utc_now(), batch_id),
                        )
                        return False
                self._conn.execute('''UPDATE summary_batches SET automatic_calls=automatic_calls+?,repair_used=MAX(repair_used,?),
                    state='retry_pending',next_retry_at=?,retry_reason='',lease_token=?,lease_expires_at=?,updated_at=? WHERE id=?''',
                    (int(not force), int(repair and not force), lease_deadline if not force else None,
                     owner_token if not force else '', lease_deadline if not force else None,
                     utc_now(), batch_id))
                self._conn.execute('INSERT INTO summary_batch_calls(batch_id,session_id,attempted_at,automatic) VALUES(?,?,?,?)',
                                   (batch_id, row['session_id'], utc_now(), int(not force)))
                # The hourly budget needs only recent reservations; lifetime counts live on the batch.
                self._conn.execute('DELETE FROM summary_batch_calls WHERE attempted_at<?', ((now - timedelta(days=2)).isoformat(timespec='seconds'),))
                return True
        return await asyncio.to_thread(reserve)

    async def defer_summary_batch(
        self,
        batch_id,
        error,
        *,
        quarantine=False,
        delay=60,
        only_if_due=False,
        lease_token="",
        preserve_lease=None,
    ) -> bool:
        """Defer a batch, optionally preserving a newer lease or completion.

        Recovery validates a persisted batch outside the store lock.  The batch
        can therefore be reserved or completed by the normal message path
        before recovery reports its validation result.  ``only_if_due`` makes
        that report conditional on the batch still being dispatchable at the
        moment of the update.
        """
        owner_token = clean_text(lease_token, 160)

        def update():
            with self._lock, self._transaction_sync():
                row = self._conn.execute(
                    "SELECT lease_token,lease_expires_at FROM summary_batches WHERE id=?",
                    (batch_id,),
                ).fetchone()
                current_owner = clean_text(row["lease_token"], 160) if row else ""
                if owner_token:
                    if current_owner != owner_token:
                        return False
                    expires_at = clean_text(row["lease_expires_at"], 40) if row else ""
                    if not expires_at or expires_at <= utc_now():
                        return False
                where = "id=?"
                where_params: list[Any] = [batch_id]
                if only_if_due:
                    where = (
                        "id=? AND state IN ('pending','retry_pending') "
                        f"AND {self._due_clause()}"
                    )
                    where_params.extend(self._due_params())
                keep_lease = bool(owner_token and current_owner == owner_token and not quarantine)
                if preserve_lease is not None:
                    keep_lease = bool(
                        preserve_lease
                        and owner_token
                        and current_owner == owner_token
                        and not quarantine
                    )
                cursor = self._conn.execute(
                    f"UPDATE summary_batches SET state=?,last_error=?,next_retry_at=?,retry_reason='',lease_token=?,lease_expires_at=?,updated_at=? WHERE {where}",
                    ('quarantined' if quarantine else 'retry_pending', clean_text(redact_sensitive_text(error), 1800),
                     (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec='seconds'),
                     current_owner if keep_lease else '',
                     clean_text(row["lease_expires_at"], 40) if keep_lease and row else None,
                     utc_now(), *where_params),
                )
                return bool(cursor.rowcount)
        return await asyncio.to_thread(update)

    async def release_summary_batch(self, batch_id: str, *, mode: str = "retry") -> dict[str, Any]:
        """Release a quarantined batch's events after explicit human review.

        Quarantine keeps failing content away from the automatic path, but it
        also keeps owning its timeline events: the pending window excludes
        assigned events, so those messages could never reach a later batch and
        the raw history would never become long-term memory.  This is the
        review step that ends the freeze, and it only ever runs on request.

        - ``retry``: drop the ownership rows and re-open the batch, so the
          events become eligible for a new batch.
        - ``discard``: delete the owned timeline rows and close the batch,
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
                if row['state'] != 'quarantined':
                    return {
                        "ok": False,
                        "error": "batch_not_quarantined",
                        "batch_id": batch_id,
                        "state": clean_text(row['state'], 40),
                    }
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
                        f"DELETE FROM timeline WHERE id IN ({placeholders})",
                        event_ids,
                    )
                self._conn.execute('DELETE FROM summary_batch_events WHERE batch_id=?', (batch_id,))
                if normalized_mode == 'retry':
                    state = 'retry_pending'
                    self._conn.execute(
                        "UPDATE summary_batches SET state=?,automatic_calls=0,repair_used=0,"
                        "next_retry_at=NULL,retry_reason='',last_error='',memory_id='',lease_token='',lease_expires_at=NULL,updated_at=? WHERE id=?",
                        (state, utc_now(), batch_id),
                    )
                else:
                    state = 'completed'
                    self._conn.execute(
                        "UPDATE summary_batches SET state=?,next_retry_at=NULL,retry_reason='',lease_token='',lease_expires_at=NULL,updated_at=? WHERE id=?",
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

    async def list_quarantined_batches(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Read the quarantined queue for the panel, most recently touched first.

        A quarantined batch owns its events and is never selected by the
        automatic pass again, so the only way to end the freeze is this listing
        plus ``release_quarantined_batches``.  Without it the panel could show a
        count but never the batch ids a human is asked to review.
        """
        def read():
            with self._lock:
                total = self._conn.execute(
                    "SELECT COUNT(*) FROM summary_batches WHERE state='quarantined'"
                ).fetchone()[0]
                legacy = self._conn.execute("SELECT COUNT(*) FROM summary_failures").fetchone()[0]
                rows = self._conn.execute('''
                    SELECT b.id, b.session_id, b.scope, b.automatic_calls, b.repair_used,
                           b.last_error, b.created_at, b.updated_at,
                           (SELECT COUNT(*) FROM summary_batch_events e WHERE e.batch_id=b.id) AS event_count
                    FROM summary_batches b WHERE b.state='quarantined'
                    ORDER BY b.updated_at DESC, b.id LIMIT ? OFFSET ?''',
                    (max(1, int(limit)), max(0, int(offset)))).fetchall()
                return {
                    "total": int(total or 0),
                    "legacy_failures": int(legacy or 0),
                    "batches": [dict(row) for row in rows],
                }
        return await asyncio.to_thread(read)

    async def close_orphan_retry_batches(self) -> int:
        """Retire queued batches whose raw events are gone; they can never run."""

        def update():
            with self._lock:
                with self._transaction_sync():
                    cursor = self._conn.execute(
                        """UPDATE summary_batches
                           SET state='completed', next_retry_at=NULL, retry_reason='',
                               last_error='', updated_at=?
                           WHERE state IN ('pending','retry_pending')
                             AND NOT EXISTS(
                                 SELECT 1 FROM summary_batch_events e
                                 WHERE e.batch_id=summary_batches.id)""",
                        (utc_now(),),
                    )
                    return int(cursor.rowcount or 0)

        return await asyncio.to_thread(update)

    async def list_pending_batches(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Read the batches still waiting for a normal summary pass.

        This is the read-only counterpart of the overview ``待处理批次`` count:
        it is a queue, not an error list, so the panel only shows it and never
        offers release actions for these rows.
        """
        def read():
            with self._lock:
                total = self._conn.execute(
                    "SELECT COUNT(*) FROM summary_batches b "
                    "WHERE b.state IN ('pending','retry_pending') "
                    "AND EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.batch_id=b.id)"
                ).fetchone()[0]
                rows = self._conn.execute(
                    "SELECT b.id, b.session_id, b.scope, b.automatic_calls, b.repair_used, "
                    "b.last_error, b.created_at, b.updated_at, "
                    "(SELECT COUNT(*) FROM summary_batch_events e WHERE e.batch_id=b.id) AS event_count "
                    "FROM summary_batches b "
                    "WHERE b.state IN ('pending','retry_pending') "
                    "AND EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.batch_id=b.id) "
                    "ORDER BY b.updated_at DESC, b.id LIMIT ? OFFSET ?",
                    (max(1, int(limit)), max(0, int(offset)))).fetchall()
                return {
                    "total": int(total or 0),
                    "legacy_failures": 0,
                    "batches": [dict(row) for row in rows],
                }
        return await asyncio.to_thread(read)

    async def list_processed_batches(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Read batches that already finished, most recently touched first.

        ``completed`` batches produced memories, ``no_memory`` batches finished
        without anything worth keeping.  Both are history, so the panel shows
        them read-only and never offers release actions.
        """
        def read():
            with self._lock:
                total = self._conn.execute(
                    "SELECT COUNT(*) FROM summary_batches WHERE state IN ('completed','no_memory')"
                ).fetchone()[0]
                rows = self._conn.execute('''
                    SELECT b.id, b.session_id, b.scope, b.automatic_calls, b.repair_used,
                           b.last_error, b.created_at, b.updated_at, b.state,
                           (SELECT COUNT(*) FROM summary_batch_events e WHERE e.batch_id=b.id) AS event_count
                    FROM summary_batches b WHERE b.state IN ('completed','no_memory')
                    ORDER BY b.updated_at DESC, b.id LIMIT ? OFFSET ?''',
                    (max(1, int(limit)), max(0, int(offset)))).fetchall()
                return {
                    "total": int(total or 0),
                    "legacy_failures": 0,
                    "batches": [dict(row) for row in rows],
                }
        return await asyncio.to_thread(read)

    async def release_quarantined_batches(
        self, *, mode: str = "retry", batch_ids=None, all_quarantined: bool = False, limit=None
    ) -> dict[str, Any]:
        """Release many quarantined batches in one transaction.

        ``release_summary_batch`` handles a single human-chosen batch; the panel
        also needs to clear a backlog of hundreds, which would otherwise mean one
        round-trip per id.  ``mode='retry'`` hands the events back for a later
        batch, ``mode='discard'`` deletes them and accepts the loss.
        """
        normalized_mode = clean_text(mode, 20).lower()
        if normalized_mode not in {"retry", "discard"}:
            return {"ok": False, "error": "unsupported_release_mode", "mode": normalized_mode}

        def release():
            with self._lock, self._transaction_sync():
                if all_quarantined:
                    selected = self._conn.execute(
                        "SELECT id FROM summary_batches WHERE state='quarantined' ORDER BY updated_at, id"
                    ).fetchall()
                    ids = [clean_text(row[0], 160) for row in selected]
                else:
                    ids = [clean_text(item, 160) for item in (batch_ids or [])]
                ids = [item for item in ids if item]
                if limit is not None:
                    ids = ids[: max(0, int(limit))]
                released = 0
                skipped = 0
                for batch_id in ids:
                    row = self._conn.execute(
                        "SELECT state FROM summary_batches WHERE id=?", (batch_id,)
                    ).fetchone()
                    if not row or row["state"] != "quarantined":
                        skipped += 1
                        continue
                    event_ids = [
                        clean_text(item[0], 160)
                        for item in self._conn.execute(
                            "SELECT event_id FROM summary_batch_events WHERE batch_id=?", (batch_id,)
                        )
                    ]
                    event_ids = [event_id for event_id in event_ids if event_id]
                    if normalized_mode == "discard" and event_ids:
                        placeholders = ",".join("?" for _ in event_ids)
                        self._conn.execute(
                            f"DELETE FROM timeline WHERE id IN ({placeholders})",
                            event_ids,
                        )
                    self._conn.execute("DELETE FROM summary_batch_events WHERE batch_id=?", (batch_id,))
                    if normalized_mode == "retry":
                        self._conn.execute(
                            "UPDATE summary_batches SET state='retry_pending',automatic_calls=0,repair_used=0,"
                            "next_retry_at=NULL,retry_reason='',last_error='',memory_id='',lease_token='',lease_expires_at=NULL,updated_at=? WHERE id=?",
                            (utc_now(), batch_id),
                        )
                    else:
                        self._conn.execute(
                            "UPDATE summary_batches SET state='completed',next_retry_at=NULL,retry_reason='',lease_token='',lease_expires_at=NULL,updated_at=? WHERE id=?",
                            (utc_now(), batch_id),
                        )
                    released += 1
                return {
                    "ok": True,
                    "mode": normalized_mode,
                    "released": released,
                    "skipped": skipped,
                    "candidates": len(ids),
                }
        return await asyncio.to_thread(release)

    async def reap_stale_quarantined_batches(
        self, *, older_than_days: int, limit: int = 50, mode: str = "retry"
    ) -> dict[str, Any]:
        """Re-queue quarantined batches that have been frozen longer than a window.

        Quarantine is meant to be a review pause, not a permanent sink: without
        this the queue only ever grows.  Releasing a batch refreshes
        ``updated_at``, so a batch that fails again is not re-reaped until the
        window has passed once more.
        """
        days = int(older_than_days or 0)
        if days <= 0:
            return {"ok": True, "released": 0, "mode": mode, "disabled": True}
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")

        def select():
            with self._lock:
                rows = self._conn.execute(
                    "SELECT id FROM summary_batches WHERE state='quarantined' AND updated_at<=? "
                    "ORDER BY updated_at, id LIMIT ?",
                    (cutoff, max(1, int(limit))),
                ).fetchall()
                return [clean_text(row[0], 160) for row in rows if clean_text(row[0], 160)]

        ids = await asyncio.to_thread(select)
        if not ids:
            return {"ok": True, "released": 0, "mode": mode, "cutoff": cutoff}
        result = await self.release_quarantined_batches(mode=mode, batch_ids=ids)
        result["cutoff"] = cutoff
        return result

    async def finish_summary_batch(
        self,
        batch_id,
        event_ids,
        *,
        memory_id='',
        no_memory=False,
        reason='',
        record=None,
        mark_timeline=True,
        lease_token='',
    ):
        def finish():
            result_memory_id = memory_id
            with self._lock, self._transaction_sync():
                if lease_token:
                    row = self._conn.execute(
                        "SELECT state,lease_token,lease_expires_at FROM summary_batches WHERE id=?",
                        (batch_id,),
                    ).fetchone()
                    if (
                        not row
                        or row["state"] not in {"pending", "retry_pending"}
                        or clean_text(row["lease_token"], 160) != clean_text(lease_token, 160)
                        or not clean_text(row["lease_expires_at"], 40)
                        or clean_text(row["lease_expires_at"], 40) <= utc_now()
                    ):
                        raise RuntimeError("summary batch lease ownership changed before completion")
                owned = {r[0] for r in self._conn.execute('SELECT event_id FROM summary_batch_events WHERE batch_id=?', (batch_id,))}
                consumed = set(event_ids)
                if not consumed or not consumed <= owned:
                    raise ValueError('summary completion has invalid event ownership')
                # A reduced prompt budget must release the unconsumed tail for later work.
                for event_id in owned - consumed:
                    self._conn.execute('DELETE FROM summary_batch_events WHERE event_id=?', (event_id,))
                if record is not None:
                    result_memory_id = self._insert_memory_sync(record, _commit=False)
                if not no_memory and mark_timeline:
                    self._mark_timeline_summarized_sync(list(consumed), _commit=False)
                self._conn.execute('UPDATE summary_batches SET state=?,memory_id=?,last_error=?,lease_token=\'\',lease_expires_at=NULL,updated_at=? WHERE id=?',
                    ('no_memory' if no_memory else 'completed', result_memory_id, clean_text(redact_sensitive_text(reason), 500), utc_now(), batch_id))
                return result_memory_id
        return await asyncio.to_thread(finish)

    async def summary_progress(self) -> dict[str, Any]:
        def read():
            with self._lock:
                counts = dict(self._conn.execute('SELECT state,COUNT(*) FROM summary_batches GROUP BY state').fetchall())
                pending = self._conn.execute('''SELECT COUNT(*) FROM summary_batches b
                    WHERE b.state IN ('pending','retry_pending')
                    AND EXISTS(SELECT 1 FROM summary_batch_events e WHERE e.batch_id=b.id)''').fetchone()[0]
                timeline = self._conn.execute('SELECT COUNT(*),MAX(created_at) FROM timeline').fetchone()
                memories = self._conn.execute("SELECT COUNT(*),MAX(created_at) FROM memories WHERE memory_type='conversation_summary' AND review_status!='pending'").fetchone()
                legacy = self._conn.execute('SELECT COUNT(*) FROM summary_failures').fetchone()[0]
                # Quarantined batches own their events permanently, so report
                # how many raw events are frozen behind human review.
                frozen = self._conn.execute('''SELECT COUNT(*) FROM summary_batch_events e
                    JOIN summary_batches b ON b.id=e.batch_id WHERE b.state='quarantined' ''').fetchone()[0]
                return {'raw_events': timeline[0], 'last_recorded_at': timeline[1] or '',
                        'conversation_memories': memories[0], 'last_summary_at': memories[1] or '',
                        'pending_batches': int(pending or 0),
                        'quarantined_batches': int(counts.get('quarantined', 0) or 0),
                        'legacy_failures': int(legacy or 0),
                        'frozen_events': int(frozen or 0),
                        'no_memory_batches': counts.get('no_memory', 0)}
        return await asyncio.to_thread(read)
