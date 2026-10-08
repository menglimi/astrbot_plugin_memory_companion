"""Explicit Role source port over Memory's actual originals and published inputs.

No model-facing read API, extra recall or capture is introduced. The owner keeps
version metadata and exact derivative registrations in its existing database.
Only an explicitly opened session enables publication receipts. Native source
versions remain opaque; they are never converted into invented revision numbers.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import json
import threading
import time
from uuid import uuid4

from .memory_revision import current_memory, digest, memory_ref
from .message_sources import authorized_context, reply_projection
from .models import MemoryRecord, SessionContext
from .source_evidence import message_source_version, read_context, read_context_key


def _instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('role_source_time_requires_timezone')
    return result.astimezone(timezone.utc)


def _bound(record):
    values = [v for v in (record.valid_to, (record.metadata or {}).get('expires_at')) if v]
    return min((_instant(v) for v in values), default=None)


def request_parts(req):
    """Read the actual placement surface, without marker/text provenance guesses."""
    result = {'prompt': getattr(req, 'prompt', None) or ''}
    for index, part in enumerate(getattr(req, 'extra_user_content_parts', None) or []):
        value = part.model_dump_for_context() if callable(getattr(part, 'model_dump_for_context', None)) else part
        result[f'extra:{index}'] = deepcopy(value)
    return result


class RoleInputSources:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.sessions = set()
        self.thread = threading.get_ident()
        with self.store._lock:
            db = self.store._conn
            if db.in_transaction:
                raise ValueError('role_owner_initialization_in_transaction')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS role_input_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS role_input_contexts (
                    key TEXT PRIMARY KEY, context_key TEXT NOT NULL, context TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS role_input_versions (
                    ref TEXT PRIMARY KEY, context_key TEXT NOT NULL, source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL, source_version TEXT NOT NULL, read_mode TEXT NOT NULL,
                    dependency TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'current');
                CREATE INDEX IF NOT EXISTS role_input_source ON role_input_versions(source_kind,source_id);
                CREATE TABLE IF NOT EXISTS role_input_registrations (
                    registration_id TEXT PRIMARY KEY, registration_digest TEXT NOT NULL,
                    dependency_digest TEXT NOT NULL, target TEXT NOT NULL, governance_revision INTEGER NOT NULL);
            ''')
            db.execute("INSERT OR IGNORE INTO role_input_meta VALUES ('owner',?)", ('memory-role:' + uuid4().hex,))
            self.owner_ref = db.execute("SELECT value FROM role_input_meta WHERE key='owner'").fetchone()[0]
            # Invalidate exact already-issued versions, including A -> B -> A.
            # Access-count/embedding bookkeeping is deliberately excluded.
            fields = {
                'memory': ('memories', 'id,memory_type,subject_id,subject_kind,object_id,object_kind,scope,session_id,platform,group_id,owner_bot_id,visibility,sayability,reality_level,lifecycle,content,evidence,validity_status,valid_from,valid_to,review_status,sensitivity,supersedes_id,message_id,confidence,occurred_at,metadata'),
                'timeline': ('timeline', 'id,event_type,scope,session_id,subject_id,object_id,message_id,content,metadata,occurred_at,created_at'),
            }
            for kind, (table, columns) in fields.items():
                actual = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
                selected = [c for c in columns.split(',') if c in actual]
                changed = ' OR '.join(f'OLD.{c} IS NOT NEW.{c}' for c in selected)
                db.executescript(f'''
                    CREATE TRIGGER IF NOT EXISTS role_input_{kind}_deleted AFTER DELETE ON {table}
                    BEGIN UPDATE role_input_versions SET state='deleted' WHERE source_kind='{kind}' AND source_id=OLD.id; END;
                    CREATE TRIGGER IF NOT EXISTS role_input_{kind}_changed AFTER UPDATE OF {','.join(selected)} ON {table}
                    WHEN {changed}
                    BEGIN UPDATE role_input_versions SET state='revoked' WHERE source_kind='{kind}' AND source_id=OLD.id AND state='current'; END;
                ''')
            db.commit()

    def published(self, ctx, req, event, injection, refs, timeline_reads, before):
        """Called by the actual publisher after successful append and validation."""
        after = request_parts(req)
        for session in tuple(self.sessions):
            if session.event is event and not session.closed:
                session._published(ctx, req, str(injection), refs, timeline_reads, before, after,
                                   complete=getattr(injection, 'role_input_complete', False))

    async def open(self, bridge, event, capability, context, identity):
        if len(self.sessions) >= 64:
            raise ValueError('role_source_session_limit')
        session = RoleSourceSession(self, bridge, event, capability, context, identity)
        await session.prepare()
        self.sessions.add(session)
        return session

    async def open_task(self, bridge, capability, manager, ticket):
        if len(self.sessions) >= 64:
            raise ValueError('role_source_session_limit')
        context, identity = manager.context(ticket)
        session = RoleTaskSourceSession(self, bridge, capability, context, identity, manager, ticket)
        await session.prepare()
        self.sessions.add(session)
        return session


class RoleSourceSession:
    def __init__(self, owner, bridge, event, capability, context, identity):
        self.owner, self.bridge, self.event, self.capability = owner, bridge, event, capability
        self.service, self.store, self.owner_ref = owner.service, owner.store, owner.owner_ref
        self.context, self.identity = context, deepcopy(identity)
        self.ctx, self.closed, self.prepared = None, False, False
        self.publications = {}
        self.until = 0.0
        self._local = threading.local()

    def _config(self):
        engine = self.service._retrieval_validation_engine()
        return digest([getattr(self.service.config, 'raw', {}), vars(engine.policy),
                       engine.private_topology_enabled, engine.group_topology_enabled])

    def _revisions(self):
        return tuple(int(v) for v in self.store._query_progress_revisions_sync())

    def _active(self):
        return (not self.closed and not getattr(self.service, '_closing', False)
                and not getattr(self.service, '_closed', False)
                and getattr(self.service, '_role_input_sources', None) is self.owner
                and self.bridge._is_valid_private_companion_capability(self.capability))

    async def _resolve_context(self):
        ctx = await authorized_context(self.service, self.event)
        producer = self.bridge._producer_capability_from(self.capability)._producer
        actual_scope = producer.extension_api.runtime_scope_for_event(self.event)
        actual_scope = ({k: v if v != '' else None for k, v in actual_scope.to_dict().items()}
                        if actual_scope is not None else None)
        return ctx, actual_scope

    def _save_context(self, ctx, scope):
        """Retain only the actual authorized scope, never message text/event IDs."""
        with self.store._lock, self.store._transaction_sync():
            self.store._conn.execute('INSERT OR REPLACE INTO role_input_contexts VALUES (?,?,?)',
                (digest([scope, self.identity]), self.context_key, json.dumps(read_context(ctx), ensure_ascii=False)))

    async def prepare(self):
        self.prepared = False
        if threading.get_ident() != self.owner.thread or not self._active():
            raise ValueError('memory_role_authority_unavailable')
        ctx, actual_scope = await self._resolve_context()
        scope = self.context.scope.to_dict()
        if (ctx is None or actual_scope is None or actual_scope != scope
                or ctx.scope != 'private' or ctx.group_id or scope.get('group_id')
                or (ctx.user_id, ctx.persona_id, ctx.platform, ctx.session_id) !=
                   (scope['user_id'], scope['persona_id'], scope['platform'], scope['conversation_ref'])
                or scope['bot_id'] not in {ctx.bot_id, f'{ctx.platform}:{ctx.bot_id}'}
                or (self.ctx is not None and read_context_key(ctx) != read_context_key(self.ctx))):
            raise ValueError('memory_role_identity_changed')
        revision, config = self._revisions(), self._config()
        engine = self.service._retrieval_validation_engine()
        acl = await engine._acl_state() if engine.policy.enable_acl_rules else engine._empty_acl_state()
        core = {record.id for record in await self.service.core_memories_for_context(ctx)}
        if revision != self._revisions() or config != self._config() or not self._active():
            raise ValueError('memory_role_policy_changed')
        self.ctx, self.engine, self.acl, self.core = ctx, engine, acl, core
        self.revision, self.config = revision, config
        self.context_key = digest([read_context(ctx), scope, self.identity])
        self._save_context(ctx, scope)
        self.until, self.prepared = time.monotonic() + 10, True

    @property
    def watermark(self):
        return digest([self.owner_ref, self._revisions(), self._config(), self.context_key])

    def verify(self):
        if (not self.prepared or not self._active() or time.monotonic() >= self.until
                or self._revisions() != self.revision or self._config() != self.config
                or not self.service._scope_feature_enabled(self.ctx, 'recall')):
            raise ValueError('memory_role_view_changed')

    @contextmanager
    def guard(self, context, identity):
        with self._task_guard(context, identity):
            with self._source_guard(context, identity):
                yield self

    def _task_guard(self, context, identity):
        return nullcontext()

    @contextmanager
    def _source_guard(self, context, identity):
        if context is not self.context or identity != self.identity:
            raise ValueError('memory_role_scope_changed')
        # Role holds other owner locks. Never wait for this lock in the opposite order.
        if not self.store._lock.acquire(blocking=False):
            raise ValueError('memory_role_owner_busy')
        depth = getattr(self._local, 'depth', 0)
        try:
            if self.store._conn.in_transaction and not depth:
                raise ValueError('memory_role_guard_requires_own_transaction')
            self._local.depth = depth + 1
            with self.store._transaction_sync():
                self.verify()
                yield self
                self.verify()
        finally:
            self._local.depth = depth
            self.store._lock.release()

    def _record(self, kind, source_id, mode):
        table = 'memories' if kind == 'memory' else 'timeline'
        row = self.store._conn.execute(f'SELECT * FROM {table} WHERE id=?', (source_id,)).fetchone()
        if not row:
            return None, None
        record = MemoryRecord.from_row(row) if kind == 'memory' else reply_projection(self.service, self.ctx, row)
        if record is None:
            return None, None
        version = memory_ref(record)['version'] if kind == 'memory' else message_source_version(dict(row))
        if kind == 'timeline':
            # The compatibility reply projection intentionally omits most raw
            # metadata. Do not lose the original's explicit expiry with it.
            original_metadata = json.loads(row['metadata'] or '{}')
            if original_metadata.get('expires_at'):
                record.metadata['expires_at'] = original_metadata['expires_at']
        return record, version

    def _visible(self, record, kind):
        if record.metadata.get('persona_id') not in {None, '', 'legacy', self.ctx.persona_id}:
            return False
        if (record.memory_type == 'core_memory' or record.metadata.get('core_memory') is True) and record.id not in self.core:
            return False
        from .visibility import _platform_family
        if (_platform_family(record.platform) and _platform_family(record.platform) != _platform_family(self.ctx.platform)):
            return False
        engine = self.engine
        if kind == 'timeline':
            engine = self.service._retrieval_validation_engine()
            engine.policy.include_raw_events = True
        return bool(engine.policy._bot_owner_visible(record, self.ctx)[0] and
                    engine._search_visibility_reason(record, self.ctx, self.acl, include_core_memory=True)[0])

    def _capture(self, kind, source_id, version, *, mode):
        record, current = self._record(kind, source_id, mode)
        if record is None or current != version or not current_memory(record) or not self._visible(record, kind):
            raise ValueError('memory_role_original_unavailable')
        bound = _bound(record)
        cutoff = bound.isoformat() if bound else None
        existing = self.store._conn.execute('''SELECT dependency FROM role_input_versions
            WHERE context_key=? AND source_kind=? AND source_id=? AND source_version=? AND read_mode=? AND state='current'
            LIMIT 1''', (self.context_key, kind, source_id, version, mode)).fetchone()
        if existing:
            return json.loads(existing['dependency'])
        # The reference identifies this issued original version, including a new
        # occurrence after correction. Native hashes are retained unchanged.
        reference = 'memory-input:' + uuid4().hex
        dep = {'input_id': 'input:' + uuid4().hex, 'owner_ref': self.owner_ref,
               'reference': {'kind': 'memory.record' if kind == 'memory' else 'message.source',
                             'ref': reference, 'revision': None}, 'version_kind': 'immutable_ref',
               'access_ref': 'memory-role-access:' + self.context_key, 'access_revision': 1,
               'binding_ref': 'memory-role-binding:' + self.context_key, 'binding_revision': 1,
               'governance_ref': self.owner_ref, 'governance_revision': sum(self._revisions()), 'retain_until': cutoff}
        self.store._conn.execute('INSERT INTO role_input_versions VALUES (?,?,?,?,?,?,?,?)',
            (reference, self.context_key, kind, source_id, version, mode, json.dumps(dep, ensure_ascii=False), 'current'))
        return dep

    async def current_message(self, *, event=None):
        """Attest one actual captured event in this session's stable identity.

        Follow-ups keep their own CAP operation/message ID. They do not replace
        the original session event or borrow its receipt by matching text.
        """
        await self.prepare()
        event = self.event if event is None else event
        ctx = self.ctx
        if event is not self.event:
            ctx = await authorized_context(self.service, event)
            producer = self.bridge._producer_capability_from(self.capability)._producer
            scope = producer.extension_api.runtime_scope_for_event(event)
            scope = ({k: v if v != '' else None for k, v in scope.to_dict().items()}
                     if scope is not None else None)
            if (ctx is None or read_context_key(ctx) != read_context_key(self.ctx)
                    or scope != self.context.scope.to_dict()):
                raise ValueError('memory_role_identity_changed')
        receipt = getattr(event, '_memory_capture_receipt', None)
        if not isinstance(receipt, dict) or not receipt.get('operation'):
            return None
        with self.guard(self.context, self.identity), self.store._transaction_sync():
            capture = self.service.capture
            actual = capture.store.lookup(receipt['operation'])
            if actual.get('status') != 'committed' or actual.get('source_state') != 'current':
                return None
            original = self.store._conn.execute('SELECT * FROM capture_sources WHERE source_key=?', (actual['source_key'],)).fetchone()
            if not original or json.loads(original['identity']) != capture.identity(ctx, direction='incoming', message=ctx.message_id):
                return None
            row = self.store._conn.execute('SELECT * FROM timeline WHERE id=?', (original['timeline_id'],)).fetchone()
            # Exact submitted observation only. Redacted/rewritten text cannot
            # attest the unredacted prompt, and a copied receipt cannot move turns.
            text = getattr(event, 'message_str', '')
            if not isinstance(text, str) or row is None or row['content'] != text:
                return None
            dep = self._capture('timeline', row['id'], actual['source_version'], mode='current_message')
        return {'sha256': digest(text), 'dependency': dep}

    def _published(self, ctx, req, text, refs, timeline_reads, before, after, *, complete=False):
        if self.ctx is None or read_context_key(ctx) != read_context_key(self.ctx):
            return
        # Publication ran the native async visibility check. Capture again under
        # the same database lock so old text cannot acquire a newer source version.
        by_ref = {(r['id'], r['version']): r for r in timeline_reads}
        try:
            with self.store._lock, self.store._transaction_sync():
                deps = []
                for ref in refs:
                    row = by_ref.get((ref['id'], ref['version']))
                    if row:
                        deps.append(self._capture('timeline', row['source_id'], row['source_version'], mode='reply_timeline'))
                    else:
                        deps.append(self._capture('memory', ref['id'], ref['version'], mode='memory'))
            changes = []
            for key, value in after.items():
                if before.get(key) != value:
                    changes.append({'slot': key, 'before': digest(before[key]) if key in before else None,
                                    'after': digest(value), 'dependencies': deps, 'complete': bool(complete and deps)})
            if len(self.publications) >= 32 and id(req) not in self.publications:
                return
            self.publications[id(req)] = (req, changes)
        except (ValueError, TypeError, KeyError):
            self.publications.pop(id(req), None)

    def publication(self, req):
        entry = self.publications.get(id(req))
        return deepcopy(entry[1]) if entry and entry[0] is req else []

    def inspect(self, dependency):
        self.verify()
        state = {'availability': 'unverifiable', 'access_revision': 1, 'binding_revision': 1,
                 'governance_revision': sum(self._revisions()), 'retain_until': None}
        row = self.store._conn.execute('SELECT * FROM role_input_versions WHERE ref=?', (dependency['reference']['ref'],)).fetchone()
        if (row is None or row['context_key'] != self.context_key or json.loads(row['dependency']) != dependency):
            return state
        state['retain_until'] = dependency['retain_until']
        if row['state'] != 'current':
            return {**state, 'availability': row['state']}
        if dependency['retain_until'] and _instant(dependency['retain_until']) <= datetime.now(timezone.utc):
            return {**state, 'availability': 'expired'}
        record, version = self._record(row['source_kind'], row['source_id'], row['read_mode'])
        if record is None:
            return state
        if version != row['source_version'] or not current_memory(record):
            return {**state, 'availability': 'revoked'}
        if self._visible(record, row['source_kind']):
            state['availability'] = 'available'
        return state

    async def register(self, context, identity, registration):
        if getattr(self._local, 'depth', 0):
            raise ValueError('memory_role_ack_requires_own_commit')
        await self.prepare()
        if registration['target']['owner_ref'] != self.identity['owner_ref']:
            raise ValueError('memory_role_target_owner_changed')
        dependency = registration['dependency']
        key, sha = registration['registration_id'], digest(registration)
        with self.guard(context, identity):
            if self.inspect(dependency)['availability'] != 'available':
                return None
            with self.store._transaction_sync():
                old = self.store._conn.execute('SELECT * FROM role_input_registrations WHERE registration_id=?', (key,)).fetchone()
                if old and old['registration_digest'] != sha:
                    raise ValueError('memory_role_registration_conflict')
                if not old:
                    self.store._conn.execute('INSERT INTO role_input_registrations VALUES (?,?,?,?,?)',
                        (key, sha, digest(dependency), json.dumps(registration['target'], ensure_ascii=False), sum(self.revision)))
                revision = old['governance_revision'] if old else sum(self.revision)
        return {'registration_id': key, 'dependency_sha256': digest(dependency), 'governance_revision': revision}

    def close(self):
        self.closed = True
        self.publications.clear()
        self.owner.sessions.discard(self)


class RoleTaskSourceSession(RoleSourceSession):
    """Verify already-issued originals under the task's current read authority.

    The context comes only from an earlier authorized owner session in this
    Memory database. A live producer ticket authorizes use, not source content.
    """
    def __init__(self, owner, bridge, capability, context, identity, manager, ticket):
        super().__init__(owner, bridge, None, capability, context, identity)
        self.manager, self.ticket = manager, ticket

    async def _resolve_context(self):
        grant = self.manager.prepare_memory(self.ticket)
        scope = self.context.scope.to_dict()
        if grant['scope'] != scope or grant['identity'] != self.identity:
            raise ValueError('memory_role_task_scope_changed')
        pin = grant['memory_context']
        if not isinstance(pin, dict) or pin.get('owner_ref') != self.owner_ref:
            raise ValueError('memory_role_task_owner_changed')
        with self.store._lock:
            row = self.store._conn.execute('SELECT context_key,context FROM role_input_contexts WHERE key=?',
                                           (digest([scope, self.identity]),)).fetchone()
        if row is None or row['context_key'] != pin.get('context_key'):
            raise ValueError('memory_role_task_original_context_missing')
        ctx = self.service._normalized_session_context(SessionContext(**json.loads(row['context'])))
        if (digest([read_context(ctx), scope, self.identity]) != row['context_key']
                or not self.service._scope_feature_enabled(ctx, 'recall')):
            raise ValueError('memory_role_task_read_denied')
        gate = await self.service._p5_gate(sink='memory_recall', attestation=grant['attestation'], consumer=grant['consumer'])
        if not gate.get('ok'):
            raise ValueError('memory_role_task_p5_denied')
        # Revalidate after any await inside gate consumption.
        self.manager.context(self.ticket)
        return ctx, scope

    def _save_context(self, ctx, scope):
        pass  # A task can never create or overwrite its own original identity.

    def _task_guard(self, context, identity):
        return self.manager.guard_memory(self.ticket, context, identity)

    async def current_message(self, *, event=None):
        raise ValueError('memory_role_task_has_no_current_message')
