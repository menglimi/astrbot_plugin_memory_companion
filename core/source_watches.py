# -*- coding: utf-8 -*-
"""Durable, reference-only watches issued from an actual authorized interaction."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4
import json

from .memory_revision import current_memory, memory_ref
from .models import MemoryRecord, SessionContext, json_dumps


def initialize(connection):
    from .message_sources import initialize as initialize_message_sources
    initialize_message_sources(connection)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS life_source_watches (
            ticket TEXT PRIMARY KEY, binding TEXT NOT NULL, memory_id TEXT NOT NULL,
            version TEXT NOT NULL, context TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active',
            UNIQUE(binding,memory_id,version));
        CREATE INDEX IF NOT EXISTS life_source_memory ON life_source_watches(memory_id);
        CREATE TRIGGER IF NOT EXISTS life_source_deleted AFTER DELETE ON memories BEGIN
            UPDATE life_source_watches SET state='revoked',context='{}' WHERE memory_id=OLD.id;
        END;
    """)


async def bind(service, event, refs, binding):
    if not isinstance(binding, str) or not binding.startswith('user:') or len(binding) > 240:
        return {'status': 'unavailable', 'items': []}
    if not isinstance(refs, list) or len(refs) > 128 or any(
            not isinstance(ref, dict) or not isinstance(ref.get('id'), str)
            or not isinstance(ref.get('version'), str) or not ref['id'] or len(ref['id']) > 120
            or len(ref['version']) != 64 for ref in refs):
        return {'status': 'unavailable', 'reason_code': 'invalid_memory_refs', 'items': []}
    reads = getattr(event, 'memory_companion_reply_sources', {})
    seen = {(item['id'], item['version']) for item in reads.get('refs', [])}
    reply_refs = [ref for ref in refs if (ref['id'], ref['version']) in seen]
    memory_refs = [ref for ref in refs if (ref['id'], ref['version']) not in seen]
    check = await service.check_memory_dependencies(event=event, refs=memory_refs)
    if (check.get('status') not in {'current', 'needs_revalidation'}
            or len(check.get('items', [])) != len(memory_refs)
            or any(item['state'] not in {'current', 'changed'} for item in check['items'])):
        return {'status': 'unavailable', 'reason_code': 'memory_dependencies_unavailable', 'items': []}
    ctx = await service.identity.resolve_event_context(event)
    if ctx.scope != 'private' or not (await service._p5_gate(event=event, sink='memory_recall')).get('ok'):
        return {'status': 'unavailable', 'items': []}
    # No message text or user names are retained. Background checks cannot recall
    # content or invent a platform message; they can only inspect these watches.
    context = {key: getattr(ctx, key) for key in
               ('session_id', 'scope', 'platform', 'user_id', 'group_id', 'bot_id', 'persona_id', 'strict_session_only')}
    items = []
    if reply_refs:
        from .message_sources import bind_reply
        reply = await bind_reply(service, event, reply_refs, binding)
        if reply.get('status') != 'current':
            return reply
        items.extend(reply['items'])
    store = service.store
    with store._lock, store._transaction_sync():
        for ref in memory_refs:
            row = store._conn.execute('SELECT * FROM memories WHERE id=?', (ref['id'],)).fetchone()
            if not row:
                return {'status': 'unavailable', 'items': []}
            record = MemoryRecord.from_row(row)
            visible = deepcopy(record)
            visible.lifecycle = 'stable_memory'
            if (not service._scope_feature_enabled(ctx, 'recall')
                    or record.metadata.get('persona_id') not in {None, '', 'legacy', ctx.persona_id}
                    or not service.visibility_policy().is_visible(visible, ctx)[0]):
                return {'status': 'unavailable', 'items': []}
            store._conn.execute('INSERT OR IGNORE INTO life_source_watches(ticket,binding,memory_id,version,context) VALUES (?,?,?,?,?)',
                                (uuid4().hex, binding, ref['id'], ref['version'], json_dumps(context)))
            watch = store._conn.execute('SELECT ticket,state FROM life_source_watches WHERE binding=? AND memory_id=? AND version=?',
                                        (binding, ref['id'], ref['version'])).fetchone()
            if watch['state'] == 'revoked':
                return {'status': 'unavailable', 'items': []}
            items.append({'kind': 'memory', **ref, 'binding': binding, 'ticket': watch['ticket']})
    return {'status': 'current', 'items': items}


def check(service, binding, tickets):
    if (not isinstance(tickets, list) or len(tickets) > 128
            or any(not isinstance(t, str) or len(t) != 32 for t in tickets)):
        return {'status': 'unavailable', 'items': []}
    items = []
    store = service.store
    with store._lock:
        for ticket in tickets:
            watch = store._conn.execute('SELECT * FROM life_source_watches WHERE ticket=? AND binding=?', (ticket, binding)).fetchone()
            item = {'ticket': ticket, 'state': 'unavailable'}
            if watch and watch['state'] == 'revoked':
                item.update(state='revoked', receipt='memory-withdrawal:' + ticket)
            elif watch:
                ctx = SessionContext(**json.loads(watch['context']))
                row = store._conn.execute('SELECT * FROM memories WHERE id=?', (watch['memory_id'],)).fetchone()
                if row and service._scope_feature_enabled(ctx, 'recall'):
                    record = MemoryRecord.from_row(row)
                    visible = deepcopy(record)
                    visible.lifecycle = 'stable_memory'
                    if ((record.metadata.get('persona_id') in {None, '', 'legacy', ctx.persona_id})
                            and service.visibility_policy().is_visible(visible, ctx)[0]):
                        item['state'] = 'current' if current_memory(record) and memory_ref(record)['version'] == watch['version'] else 'changed'
            items.append(item)
    return {'status': 'current' if all(i['state'] == 'current' for i in items) else 'needs_revalidation', 'items': items}
