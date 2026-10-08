"""Bounded original-message transactions. Only trusted adapters call this port.

The full compatibility projection and chunks belong to the same Memory database
and commit together. Existing readers therefore search the entire allowed body.
Receipts describe submission separately from the source's current validity.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import time

from .models import utc_now
from .sensitive_data import redact_sensitive_text
from .message_sources import suppressed
from .source_evidence import message_source_version


PROFILE = 'memory.source-capture.v1'
MAX_BODY_BYTES = 256 * 1024
MAX_PENDING_BYTES = 16 * 1024 * 1024
CHUNK_CHARS = 4096
IDENTITY_FIELDS = ('installation', 'platform', 'bot', 'persona', 'scope', 'session',
                   'speaker', 'audience', 'direction', 'message')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def instant(value):
    if value in ('', None):
        return ''
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('source_time_requires_timezone')
    return result.astimezone(timezone.utc).isoformat()


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS capture_runtime (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS capture_sources (
            source_key TEXT PRIMARY KEY, identity TEXT NOT NULL, timeline_id TEXT UNIQUE NOT NULL,
            revision INTEGER NOT NULL, manifest TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS capture_chunks (
            source_key TEXT NOT NULL, seq INTEGER NOT NULL, char_offset INTEGER NOT NULL,
            byte_offset INTEGER NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL,
            PRIMARY KEY(source_key,seq));
        CREATE TABLE IF NOT EXISTS capture_operations (
            operation TEXT PRIMARY KEY, source_key TEXT NOT NULL, payload_digest TEXT NOT NULL,
            envelope TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT NOT NULL DEFAULT '{}',
            created REAL NOT NULL, due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            generation TEXT NOT NULL DEFAULT '', expires REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS capture_due ON capture_operations(state,due,operation);
        CREATE INDEX IF NOT EXISTS capture_by_source ON capture_operations(source_key);
        CREATE TABLE IF NOT EXISTS capture_suppression (
            source_key TEXT PRIMARY KEY, reason TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS capture_changes (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT NOT NULL,
            revision INTEGER NOT NULL, kind TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS capture_source_deleted AFTER DELETE ON timeline
        WHEN EXISTS (SELECT 1 FROM capture_sources WHERE timeline_id=OLD.id) BEGIN
            INSERT OR IGNORE INTO capture_suppression
                SELECT source_key,'source_deleted',strftime('%s','now') FROM capture_sources WHERE timeline_id=OLD.id;
            DELETE FROM capture_chunks WHERE source_key IN (SELECT source_key FROM capture_sources WHERE timeline_id=OLD.id);
            UPDATE capture_operations SET envelope='{}',state=CASE WHEN state='committed' THEN state ELSE 'excluded' END
                WHERE source_key IN (SELECT source_key FROM capture_sources WHERE timeline_id=OLD.id);
            UPDATE capture_sources SET manifest='{}',identity='{}',state='revoked' WHERE timeline_id=OLD.id;
        END;
        CREATE TRIGGER IF NOT EXISTS capture_projection_changed AFTER UPDATE OF content ON timeline
        WHEN OLD.content!=NEW.content AND EXISTS (SELECT 1 FROM capture_sources WHERE timeline_id=NEW.id) BEGIN
            DELETE FROM capture_chunks WHERE source_key IN (SELECT source_key FROM capture_sources WHERE timeline_id=NEW.id);
            UPDATE capture_sources SET state='changed',manifest='{}' WHERE timeline_id=NEW.id;
        END;
    ''')
    db.execute("INSERT OR IGNORE INTO capture_runtime VALUES ('installation',?)", (secrets.token_hex(24),))
    db.execute("INSERT OR IGNORE INTO capture_runtime VALUES ('digest_key',?)", (secrets.token_hex(32),))
    db.commit()


class SourceCapture:
    def __init__(self, store):
        self.store = store
        self.db = store._conn
        with store._lock:
            self.installation = self.db.execute("SELECT value FROM capture_runtime WHERE key='installation'").fetchone()[0]
            self._digest_key = bytes.fromhex(self.db.execute("SELECT value FROM capture_runtime WHERE key='digest_key'").fetchone()[0])

    def activate(self, generation):
        with self.store._lock, self.store._transaction_sync():
            self.db.execute("INSERT OR REPLACE INTO capture_runtime VALUES ('generation',?)", (generation,))
            self.db.execute("UPDATE capture_operations SET state='uncertain',due=0 WHERE state='submitting'")

    def fence(self, generation, authorize):
        current = self.db.execute("SELECT value FROM capture_runtime WHERE key='generation'").fetchone()
        if not current or current[0] != generation or not authorize():
            raise ValueError('capture_authority_changed')

    def prepare(self, identity, *, body, revision=1, expected_revision=0,
                source_message_at='', observed_at='', evidence='observed', media=None, raw_body_digest=''):
        if set(identity) != set(IDENTITY_FIELDS):
            raise ValueError('capture_identity_incomplete')
        if any(not isinstance(v, str) or '\x00' in v or len(v) > 4096 for v in identity.values()):
            raise ValueError('capture_identity_invalid')
        if any(not identity[k] for k in IDENTITY_FIELDS if k != 'persona'):
            raise ValueError('capture_identity_incomplete')
        if identity['installation'] != self.installation or identity['scope'] not in {'private', 'group'}:
            raise ValueError('capture_identity_mismatch')
        if identity['direction'] not in {'incoming', 'outgoing'}:
            raise ValueError('capture_direction_invalid')
        if identity['direction'] == 'outgoing' and evidence not in {'platform_accepted', 'adapter_completed'}:
            raise ValueError('capture_delivery_unproven')
        if identity['direction'] == 'incoming' and evidence != 'observed':
            raise ValueError('capture_observation_unproven')
        if type(revision) is not int or type(expected_revision) is not int or revision < 1 or expected_revision != revision - 1:
            raise ValueError('capture_revision_invalid')
        if not isinstance(body, str) or len(body) > MAX_BODY_BYTES or len(body.encode('utf-8')) > MAX_BODY_BYTES:
            raise ValueError('capture_body_capacity')
        media = media or []
        if not isinstance(media, list) or len(media) > 32 or any(not isinstance(m, dict) or set(m) - {'kind', 'ref'} for m in media):
            raise ValueError('capture_media_invalid')
        if len(encoded(media)) > 8192:
            raise ValueError('capture_media_capacity')
        # Hash the immutable input before redaction; no raw credential is retained
        # in metadata or in an ordinary reversible dictionary of short messages.
        payload = dict(identity=identity, body=body, revision=revision, expected_revision=expected_revision,
                       source_message_at=instant(source_message_at), observed_at=instant(observed_at), evidence=evidence, media=media)
        if not payload['observed_at']:
            raise ValueError('capture_observation_time_required')
        if raw_body_digest and (len(raw_body_digest)!=64 or any(c not in '0123456789abcdef' for c in raw_body_digest)):
            raise ValueError('capture_body_digest_invalid')
        immutable = {k: v for k, v in payload.items() if k not in {'observed_at','body'}}
        # A live registered producer may have already scrubbed its durable copy.
        # Its exact observed input digest is pulled from that owner, never from
        # a model argument or arbitrary metadata.
        immutable['raw_body_digest'] = raw_body_digest or hashlib.sha256(body.encode('utf-8')).hexdigest()
        payload_hash = hmac.new(self._digest_key, encoded(immutable).encode('utf-8'), hashlib.sha256).hexdigest()
        safe = redact_sensitive_text(body)
        payload.update(body=safe, media=json.loads(redact_sensitive_text(encoded(media))),
                       redaction='changed' if safe != body else 'unchanged', processing='utf8-exact/redaction-v1')
        key = digest(identity)
        return dict(operation=digest([PROFILE, key, revision]), source_key=key, payload_digest=payload_hash, payload=payload)

    def _revoked(self, key):
        return self.db.execute('SELECT 1 FROM capture_suppression WHERE source_key=?', (key,)).fetchone() is not None

    def lookup(self, operation, *, payload_digest='', authorize=lambda: True):
        with self.store._lock:
            if not authorize():
                return {'status': 'unavailable'}
            row = self.db.execute('SELECT * FROM capture_operations WHERE operation=?', (operation,)).fetchone()
            if not row:
                return {'status': 'missing', 'operation': operation, 'retry': 'same_operation_only'}
            if payload_digest and payload_digest != row['payload_digest']:
                return {'status': 'conflict', 'operation': operation}
            receipt = json.loads(row['receipt'])
            current = self.db.execute('SELECT state,timeline_id FROM capture_sources WHERE source_key=?', (row['source_key'],)).fetchone()
            current_state=current['state'] if current else 'pending'
            if current and current_state=='current' and receipt.get('source_version'):
                projection=self.db.execute('SELECT * FROM timeline WHERE id=?',(current['timeline_id'],)).fetchone()
                if not projection: current_state='unavailable'
                elif message_source_version(dict(projection))!=receipt['source_version']: current_state='changed'
            return {**receipt, 'operation': operation, 'status': row['state'], 'payload_digest': row['payload_digest'],
                    'source_state': 'revoked' if self._revoked(row['source_key']) else current_state}

    def stage(self, prepared, *, generation, authorize=lambda: True, expires=None):
        operation, key, ph = (prepared[k] for k in ('operation', 'source_key', 'payload_digest'))
        payload = prepared['payload']
        if key != digest(payload['identity']) or operation != digest([PROFILE, key, payload['revision']]):
            raise ValueError('capture_prepared_identity_changed')
        now = time.time()
        with self.store._lock, self.store._transaction_sync():
            self.fence(generation, authorize)
            old = self.lookup(operation, payload_digest=ph)
            if old['status'] != 'missing':
                return old
            if self._revoked(key):
                return {'status': 'excluded', 'source_state': 'revoked', 'operation': operation}
            size = len(encoded(payload).encode('utf-8'))
            pending = self.db.execute("SELECT COALESCE(sum(length(CAST(envelope AS BLOB))),0) FROM capture_operations WHERE envelope!='{}'").fetchone()[0]
            if pending + size > MAX_PENDING_BYTES:
                return {'status': 'held', 'reason': 'capture_capacity', 'durably_staged': False}
            deadline = min(expires if expires is not None else now + 86400, now + 86400)
            if deadline <= now:
                return {'status': 'expired', 'durably_staged': False}
            self.db.execute('''INSERT INTO capture_operations
                (operation,source_key,payload_digest,envelope,state,created,due,expires)
                VALUES (?,?,?,?,'staged',?,?,?)''', (operation,key,ph,encoded(payload),now,now,deadline))
        return {**self.lookup(operation), 'durably_staged': True}

    def commit(self, operation, *, generation, authorize=lambda: True):
        with self.store._lock, self.store._transaction_sync():
            self.fence(generation, authorize)
            row = self.db.execute('SELECT * FROM capture_operations WHERE operation=?', (operation,)).fetchone()
            if not row or row['state'] in {'committed', 'excluded', 'expired', 'held'}:
                return self.lookup(operation)
            if row['expires'] <= time.time() or self._revoked(row['source_key']):
                self.db.execute("UPDATE capture_operations SET state=?,envelope='{}' WHERE operation=?",
                                ('excluded' if self._revoked(row['source_key']) else 'expired', operation))
                return self.lookup(operation)
            payload = json.loads(row['envelope'])
            identity = payload['identity']; key = row['source_key']
            existing = self.db.execute('SELECT * FROM capture_sources WHERE source_key=?', (key,)).fetchone()
            if (existing['revision'] if existing else 0) != payload['expected_revision']:
                self.db.execute("UPDATE capture_operations SET state='held' WHERE operation=?", (operation,))
                return {'status': 'conflict', 'operation': operation, 'reason': 'source_revision_changed'}
            timeline_id = existing['timeline_id'] if existing else 'tl_' + key
            metadata = dict(platform=identity['platform'],owner_bot_id=identity['bot'],bot_id=identity['bot'],
                            persona_id=identity['persona'],message_id=identity['message'],capture_profile=PROFILE,
                            capture_truncated=False, source_key=key, capture_revision=payload['revision'],
                            source_message_at=payload['source_message_at'], observed_at=payload['observed_at'],
                            delivery_evidence=payload['evidence'], media=payload['media'],
                            redaction=payload['redaction'], capture_processing=payload['processing'])
            kind = 'user_message' if identity['direction']=='incoming' else 'bot_response'
            params = dict(source_id=timeline_id,event_type=kind,scope=identity['scope'],session_id=identity['session'],
                          subject_id=identity['speaker'],object_id=identity['audience'],message_id=identity['message'],metadata=metadata)
            if suppressed(self.db, **params):
                self.withdraw(key, reason='legacy_source_deleted')
                return self.lookup(operation)
            when = payload['source_message_at'] or payload['observed_at']
            if existing:
                self.db.execute('UPDATE timeline SET content=?,metadata=?,occurred_at=?,summarized_at=? WHERE id=?',
                                (payload['body'],encoded(metadata),when,'',timeline_id))
            else:
                self.db.execute('''INSERT INTO timeline(id,event_type,session_id,scope,subject_id,object_id,content,
                    metadata,message_id,dedupe_key,occurred_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (timeline_id,kind,identity['session'],identity['scope'],identity['speaker'],identity['audience'],
                     payload['body'],encoded(metadata),identity['message'],'cap:'+key,when,utc_now()))
            actual = self.db.execute('SELECT * FROM timeline WHERE id=?', (timeline_id,)).fetchone()
            if not actual:
                raise ValueError('capture_timeline_not_committed')
            self.db.execute('DELETE FROM capture_chunks WHERE source_key=?', (key,))
            chunks=[]; byte_offset=0
            for seq, offset in enumerate(range(0,len(payload['body']),CHUNK_CHARS)):
                chunk=payload['body'][offset:offset+CHUNK_CHARS]; blob=chunk.encode('utf-8')
                sha=hashlib.sha256(blob).hexdigest()
                self.db.execute('INSERT INTO capture_chunks VALUES (?,?,?,?,?,?)', (key,seq,offset,byte_offset,chunk,sha))
                chunks.append(dict(seq=seq,char_offset=offset,byte_offset=byte_offset,chars=len(chunk),bytes=len(blob),digest=sha))
                byte_offset+=len(blob)
            manifest=dict(chunks=chunks,chars=len(payload['body']),bytes=byte_offset,
                          body_digest=hashlib.sha256(payload['body'].encode('utf-8')).hexdigest(),processing=payload['processing'])
            self.db.execute('INSERT OR REPLACE INTO capture_sources VALUES (?,?,?,?,?,?)',
                            (key,encoded(identity),timeline_id,payload['revision'],encoded(manifest),'current'))
            receipt=dict(profile=PROFILE,operation=operation,source_key=key,source_ref='timeline:'+timeline_id,
                         source_version=message_source_version(dict(actual)),payload_digest=row['payload_digest'],
                         committed_at=utc_now(),revision=payload['revision'],
                         completeness=dict(stored_body='full',source_observation='submitted_observation',
                                           redaction=payload['redaction'],legacy_projection='full',media='references_only'),
                         index_state='ready' if getattr(self.store,'_source_fts_enabled',False) else 'scan_only', delivery_evidence=payload['evidence'],user_seen='unknown')
            self.db.execute("UPDATE capture_operations SET state='committed',receipt=?,envelope='{}',generation=? WHERE operation=?",
                            (encoded(receipt),generation,operation))
            self.db.execute("INSERT INTO capture_changes(source_key,revision,kind) VALUES (?,?,'committed')", (key,payload['revision']))
            self.fence(generation, authorize)
        return self.lookup(operation)

    def withdraw(self, key, *, reason='withdrawn'):
        with self.store._lock, self.store._transaction_sync():
            self.db.execute('INSERT OR IGNORE INTO capture_suppression VALUES (?,?,?)', (key,reason,time.time()))
            rows = self.db.execute('SELECT timeline_id FROM capture_sources WHERE source_key=?', (key,)).fetchall()
            self.store._delete_memories_referencing_timeline_ids_sync([row['timeline_id'] for row in rows])
            self.db.execute('DELETE FROM timeline WHERE id IN (SELECT timeline_id FROM capture_sources WHERE source_key=?)', (key,))
            self.db.execute('DELETE FROM capture_chunks WHERE source_key=?', (key,))
            self.db.execute("UPDATE capture_operations SET envelope='{}',state=CASE WHEN state='committed' THEN state ELSE 'excluded' END WHERE source_key=?", (key,))
            return {'status': 'excluded', 'source_state': 'revoked', 'source_key': key}

    def exclude_pending(self, operation):
        with self.store._lock, self.store._transaction_sync():
            self.db.execute("UPDATE capture_operations SET state='excluded',envelope='{}' WHERE operation=? AND state!='committed'",(operation,))

    def due(self, limit=8):
        with self.store._lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM capture_operations WHERE state IN ('staged','uncertain','retry_due') AND due<=? ORDER BY due,operation LIMIT ?", (time.time(), min(limit,32)))]

    def retry(self, operation, generation):
        with self.store._lock, self.store._transaction_sync():
            self.fence(generation, lambda: True)
            row=self.db.execute('SELECT attempts FROM capture_operations WHERE operation=?', (operation,)).fetchone()
            if row:
                attempts=row[0]+1
                self.db.execute("UPDATE capture_operations SET state=?,attempts=?,due=? WHERE operation=? AND state!='committed'",
                                ('held' if attempts>=12 else 'retry_due',attempts,time.time()+min(3600,5*2**min(attempts,10)),operation))

    def status(self):
        with self.store._lock:
            return dict(profile=PROFILE,operations=dict(self.db.execute('SELECT state,count(*) FROM capture_operations GROUP BY state').fetchall()),
                        journal_mode=self.db.execute('PRAGMA journal_mode').fetchone()[0],
                        synchronous=self.db.execute('PRAGMA synchronous').fetchone()[0],
                        body_byte_limit=MAX_BODY_BYTES, pending_byte_limit=MAX_PENDING_BYTES,
                        inventory_coverage='observed_hooks_only')
