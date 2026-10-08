# -*- coding: utf-8 -*-
"""Local governance for legacy timeline sources; this is not a CAP capture port.

Read authority comes from the actual event and the exact fragments Memory
returned. Watches and withdrawal receipts never contain message text.
"""
from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

from .models import SessionContext, json_dumps, json_loads, utc_now
from .source_evidence import message_source_version, read_context, read_context_key
from .source_query import source_visible
from .memory_revision import digest


def suppression_clause(alias):
    return ("""EXISTS (SELECT 1 FROM message_source_tombstones s WHERE s.source_id=NEW.id OR (
        s.message_id!='' AND s.message_id=NEW.message_id AND s.event_type=NEW.event_type
        AND s.scope=NEW.scope AND s.session_id=NEW.session_id
        AND s.subject_id=NEW.subject_id AND s.object_id=NEW.object_id
        AND s.platform=COALESCE(json_extract(CASE WHEN json_valid(NEW.metadata) THEN NEW.metadata ELSE '{}' END,'$.platform'),'')
        AND s.owner_bot_id=COALESCE(json_extract(CASE WHEN json_valid(NEW.metadata) THEN NEW.metadata ELSE '{}' END,'$.owner_bot_id'),'')
        AND s.persona_id=COALESCE(json_extract(CASE WHEN json_valid(NEW.metadata) THEN NEW.metadata ELSE '{}' END,'$.persona_id'),'')))""").replace('NEW.', alias + '.')


def suppressed(db, *, source_id, event_type, scope, session_id, subject_id, object_id, message_id, metadata):
    # Check the tombstone before looking up an old-format dedupe receipt: that
    # key omits bot/persona, so another owner's live row must not become ours.
    incoming = """SELECT ? AS id, ? AS event_type, ? AS scope, ? AS session_id,
        ? AS subject_id, ? AS object_id, ? AS message_id, ? AS metadata"""
    return db.execute(f"SELECT 1 FROM ({incoming}) AS candidate WHERE {suppression_clause('candidate')}",
        (source_id, event_type, scope, session_id, subject_id, object_id, message_id, json_dumps(metadata))).fetchone() is not None


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS life_message_source_watches (
            ticket TEXT PRIMARY KEY, binding TEXT NOT NULL, source_id TEXT NOT NULL,
            version TEXT NOT NULL, context TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active',
            UNIQUE(binding,source_id,version));
        CREATE INDEX IF NOT EXISTS life_message_source_watch_id ON life_message_source_watches(source_id);
        CREATE TABLE IF NOT EXISTS message_source_tombstones (
            source_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, scope TEXT NOT NULL,
            session_id TEXT NOT NULL, subject_id TEXT NOT NULL, object_id TEXT NOT NULL,
            message_id TEXT NOT NULL, platform TEXT NOT NULL, owner_bot_id TEXT NOT NULL,
            persona_id TEXT NOT NULL, deleted_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS message_source_suppression ON message_source_tombstones(
            session_id,event_type,subject_id,message_id);
        CREATE TABLE IF NOT EXISTS life_message_withdrawals (
            scope_key TEXT NOT NULL, operation_id TEXT NOT NULL, source_id TEXT NOT NULL,
            version TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(scope_key,operation_id));
        CREATE TRIGGER IF NOT EXISTS life_message_source_deleted AFTER DELETE ON timeline
        WHEN OLD.event_type IN ('user_message','bot_response') BEGIN
            INSERT OR IGNORE INTO message_source_tombstones VALUES (
                OLD.id, OLD.event_type, OLD.scope, OLD.session_id, OLD.subject_id, OLD.object_id,
                OLD.message_id,
                COALESCE(json_extract(CASE WHEN json_valid(OLD.metadata) THEN OLD.metadata ELSE '{}' END,'$.platform'),''),
                COALESCE(json_extract(CASE WHEN json_valid(OLD.metadata) THEN OLD.metadata ELSE '{}' END,'$.owner_bot_id'),''),
                COALESCE(json_extract(CASE WHEN json_valid(OLD.metadata) THEN OLD.metadata ELSE '{}' END,'$.persona_id'),''),
                strftime('%Y-%m-%dT%H:%M:%fZ','now'));
            UPDATE life_message_source_watches SET state='revoked',context='{}' WHERE source_id=OLD.id;
        END;
        CREATE TRIGGER IF NOT EXISTS life_reply_timeline_deleted AFTER DELETE ON timeline
        WHEN OLD.event_type NOT IN ('user_message','bot_response') BEGIN
            INSERT OR IGNORE INTO message_source_tombstones VALUES (
                OLD.id, OLD.event_type, OLD.scope, OLD.session_id, OLD.subject_id, OLD.object_id,
                OLD.message_id,
                COALESCE(json_extract(CASE WHEN json_valid(OLD.metadata) THEN OLD.metadata ELSE '{}' END,'$.platform'),''),
                COALESCE(json_extract(CASE WHEN json_valid(OLD.metadata) THEN OLD.metadata ELSE '{}' END,'$.owner_bot_id'),''),
                COALESCE(json_extract(CASE WHEN json_valid(OLD.metadata) THEN OLD.metadata ELSE '{}' END,'$.persona_id'),''),
                strftime('%Y-%m-%dT%H:%M:%fZ','now'));
            UPDATE life_message_source_watches SET state='revoked',context='{}' WHERE source_id=OLD.id;
        END;
    """)
    # Full known ownership prevents a native ID reused by another bot/persona
    # from being mistaken for this source. Text similarity never participates.
    match = suppression_clause('NEW')
    db.executescript(f"""
        CREATE TRIGGER IF NOT EXISTS life_message_source_no_reinsert BEFORE INSERT ON timeline
        WHEN {match} BEGIN SELECT RAISE(IGNORE); END;
        CREATE TRIGGER IF NOT EXISTS life_message_source_no_rebind
        BEFORE UPDATE OF id,event_type,scope,session_id,subject_id,object_id,message_id,metadata ON timeline
        WHEN {match} BEGIN SELECT RAISE(ABORT,'message_source_revoked'); END;
    """)


def visible(ctx, row):
    metadata = json_loads(row['metadata'], {})
    return isinstance(metadata, dict) and source_visible(ctx, dict(row), metadata)


def observed(event, ctx):
    reads = getattr(event, 'memory_companion_message_sources', {})
    if not isinstance(reads, dict) or reads.get('context') != read_context_key(ctx):
        return []
    return reads.get('refs', [])


async def authorized_context(service, event):
    ctx = service._normalized_session_context(await service.identity.resolve_event_context(event))
    if (ctx.scope != 'private' or not all((ctx.session_id, ctx.user_id, ctx.bot_id, ctx.platform))
            or ctx.bot_id == 'self' or not service._scope_feature_enabled(ctx, 'recall')
            or not (await service._p5_gate(event=event, sink='memory_recall')).get('ok')):
        return None
    return ctx


async def bind(service, event, binding):
    empty = {'status': 'unavailable', 'items': []}
    if not isinstance(binding, str) or not binding.startswith('user:') or len(binding) > 240:
        return empty
    ctx = await authorized_context(service, event)
    if ctx is None:
        return empty
    refs = observed(event, ctx)
    if not refs:
        return empty
    store, items = service.store, []
    with store._lock, store._transaction_sync():
        for ref in refs:
            row = store._conn.execute('SELECT * FROM timeline WHERE id=?', (ref['id'],)).fetchone()
            deleted = store._conn.execute('SELECT 1 FROM message_source_tombstones WHERE source_id=?', (ref['id'],)).fetchone()
            if not deleted and (not row or not visible(ctx, row)):
                return empty
            state = 'revoked' if deleted else 'active'
            store._conn.execute('''INSERT OR IGNORE INTO life_message_source_watches
                (ticket,binding,source_id,version,context,state) VALUES (?,?,?,?,?,?)''',
                (uuid4().hex, binding, ref['id'], ref['version'], '{}' if deleted else json_dumps(read_context(ctx)), state))
            watch = store._conn.execute('''SELECT ticket FROM life_message_source_watches
                WHERE binding=? AND source_id=? AND version=?''', (binding, ref['id'], ref['version'])).fetchone()
            items.append({'kind': 'message', **ref, 'binding': binding, 'ticket': watch['ticket']})
    return {'status': 'current', 'items': items}


def reply_projection(service, ctx, row):
    """Recheck the original reply view's policy, never expand it to raw access.

    Legacy timeline rows may lack raw-query ownership metadata. Their existing
    reply policy is session-bound; retain that distinction in the watch itself.
    """
    # Admission comes from the exact published receipt, not an event-type list.
    # Proactive messages and other timeline views follow this same owner path.
    if row['session_id'] != ctx.session_id or row['scope'] != ctx.scope:
        return None
    record = service._timeline_row_as_memory(ctx, dict(row))
    if record is None or record.metadata.get('persona_id') not in {None, '', 'legacy', ctx.persona_id}:
        return None
    policy = deepcopy(service.visibility_policy())
    policy.include_raw_events = True
    return record if policy.is_visible(record, ctx)[0] else None


async def bind_reply(service, event, refs, binding):
    """Issue ordinary message watches from exact, actually published projections."""
    def unavailable(reason):
        return {'status': 'unavailable', 'reason_code': reason, 'items': []}
    ctx = await authorized_context(service, event)
    reads = getattr(event, 'memory_companion_reply_sources', {})
    if ctx is None:
        return unavailable('reply_source_context_unavailable')
    if not isinstance(reads, dict) or reads.get('context') != read_context_key(ctx):
        return unavailable('reply_source_context_changed')
    seen = {(item['id'], item['version']): item for item in reads.get('refs', [])}
    if any((ref['id'], ref['version']) not in seen for ref in refs):
        return unavailable('reply_source_receipt_missing')
    store, items = service.store, []
    with store._lock, store._transaction_sync():
        for ref in refs:
            receipt = seen[(ref['id'], ref['version'])]
            source_id = receipt['source_id']
            row = store._conn.execute('SELECT * FROM timeline WHERE id=?', (source_id,)).fetchone()
            deleted = store._conn.execute('SELECT 1 FROM message_source_tombstones WHERE source_id=?', (source_id,)).fetchone()
            if not deleted and not row:
                return unavailable('reply_source_row_missing')
            if not deleted and reply_projection(service, ctx, row) is None:
                return unavailable('reply_source_visibility_changed')
            version = digest(['reply_timeline', receipt['source_version']])
            context = {**read_context(ctx), 'read_mode': 'reply_timeline'}
            store._conn.execute('''INSERT OR IGNORE INTO life_message_source_watches
                (ticket,binding,source_id,version,context,state) VALUES (?,?,?,?,?,?)''',
                (uuid4().hex, binding, source_id, version, '{}' if deleted else json_dumps(context),
                 'revoked' if deleted else 'active'))
            watch = store._conn.execute('''SELECT ticket FROM life_message_source_watches
                WHERE binding=? AND source_id=? AND version=?''', (binding, source_id, version)).fetchone()
            items.append({'kind': 'message', 'id': source_id, 'version': version,
                          'binding': binding, 'ticket': watch['ticket']})
    return {'status': 'current', 'items': items}


def check(service, binding, tickets):
    if (not isinstance(tickets, list) or len(tickets) > 128
            or any(not isinstance(t, str) or len(t) != 32 for t in tickets)):
        return {'status': 'unavailable', 'items': []}
    store, items = service.store, []
    with store._lock:
        for ticket in tickets:
            watch = store._conn.execute('SELECT * FROM life_message_source_watches WHERE ticket=? AND binding=?', (ticket, binding)).fetchone()
            item = {'ticket': ticket, 'state': 'unavailable'}
            if watch and watch['state'] == 'revoked':
                item.update(state='revoked', receipt='message-withdrawal:' + ticket)
            elif watch:
                context = json.loads(watch['context'])
                read_mode = context.pop('read_mode', 'raw_source')
                ctx = SessionContext(**context)
                row = store._conn.execute('SELECT * FROM timeline WHERE id=?', (watch['source_id'],)).fetchone()
                if row and service._scope_feature_enabled(ctx, 'recall') and read_mode == 'reply_timeline':
                    record = reply_projection(service, ctx, row)
                    if record is not None:
                        version = digest(['reply_timeline', message_source_version(dict(row))])
                        item['state'] = 'current' if version == watch['version'] else 'changed'
                elif (row and read_mode == 'raw_source' and service._scope_feature_enabled(ctx, 'recall')
                        and visible(ctx, row)):
                    item['state'] = 'current' if message_source_version(dict(row)) == watch['version'] else 'changed'
            items.append(item)
    return {'status': 'current' if all(i['state'] == 'current' for i in items) else 'needs_revalidation', 'items': items}


async def manage(service, event, *, action, operation_id, source_ref='', expected_version='', authorize=lambda: True):
    """Private owner port, intentionally not registered as a model query tool.

    A host/platform withdrawal adapter must supply its own trusted event. This
    local port does not interpret platform notices or prove delivery/capture.
    """
    denied = {'status': 'unavailable', 'ok': False}
    if (action not in {'withdraw', 'lookup'} or not isinstance(operation_id, str)
            or not operation_id.strip() or len(operation_id) > 160 or '\x00' in operation_id):
        return {'status': 'rejected', 'ok': False, 'error': 'invalid_operation'}
    ctx = await authorized_context(service, event)
    if ctx is None or not authorize():
        return denied
    scope_key = read_context_key(ctx)
    store = service.store
    with store._lock, store._transaction_sync():
        old = store._conn.execute('SELECT * FROM life_message_withdrawals WHERE scope_key=? AND operation_id=?',
                                 (scope_key, operation_id)).fetchone()
        if action == 'lookup':
            return json.loads(old['receipt']) if old else {'status': 'missing', 'ok': False}
        if not isinstance(source_ref, str) or not source_ref.startswith('timeline:tl_'):
            return denied
        source_id = source_ref.removeprefix('timeline:')
        if old:
            if old['source_id'] != source_id or old['version'] != expected_version:
                return {'status': 'conflict', 'ok': False, 'error': 'operation_conflict'}
            return json.loads(old['receipt'])
        if {'id': source_id, 'version': expected_version} not in observed(event, ctx):
            return denied
        row = store._conn.execute('SELECT * FROM timeline WHERE id=?', (source_id,)).fetchone()
        if not row or not visible(ctx, row):
            return denied
        if message_source_version(dict(row)) != expected_version:
            return {'status': 'conflict', 'ok': False, 'error': 'source_version_changed'}
        store._delete_memories_referencing_timeline_ids_sync([source_id])
        store._conn.execute('DELETE FROM timeline WHERE id=?', (source_id,))
        receipt = {'ok': True, 'status': 'committed', 'operation_id': operation_id,
                   'source_ref': source_ref, 'source_version': expected_version, 'source_state': 'revoked',
                   'receipt': 'message-withdrawal:' + uuid4().hex, 'committed_at': utc_now()}
        store._conn.execute('INSERT INTO life_message_withdrawals VALUES (?,?,?,?,?)',
                            (scope_key, operation_id, source_id, expected_version, json_dumps(receipt)))
    return receipt
