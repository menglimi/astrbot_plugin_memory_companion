from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from core.source_capture import SourceCapture, MAX_BODY_BYTES
from core.store import MemoryStore
from core.models import EntityRef, MemoryRecord
from .test_source_query import service, ctx

pytestmark = pytest.mark.asyncio


def owner(service, ctx):
    cap=SourceCapture(service.store); cap.activate('test')
    identity=dict(installation=cap.installation,platform=ctx.platform,bot=ctx.bot_id,persona=ctx.persona_id,
                  scope=ctx.scope,session=ctx.session_id,speaker=ctx.user_id,audience=ctx.user_id,
                  direction='incoming',message='native-1')
    return cap,identity


def prepared(cap, identity, body=' 原文\r\n  最后一行  ', **changes):
    return cap.prepare(identity,body=body,source_message_at='2026-09-14T12:00:00+08:00',
                       observed_at='2026-09-16T01:00:00+08:00',**changes)


def commit(cap, value):
    staged=cap.stage(value,generation='test')
    return cap.commit(value['operation'],generation='test') if staged['status'] in {'staged','uncertain','retry_due'} else staged


async def test_full_original_tail_search_read_and_chunks(service,ctx):
    cap,identity=owner(service,ctx)
    body='  原文\r\n'+('长句🙂e\u0301\t'*2400)+'\n工具调用只是一段技术讨论。最末端的橘猫  '
    receipt=commit(cap,prepared(cap,identity,body))
    assert receipt['status']=='committed'
    found=await service.tool_sources(SimpleNamespace(),terms=['最末端的橘猫'])
    assert found['ok'] and len(found['sources'])==1, found
    assert '最末端的橘猫' in found['sources'][0]['excerpt']
    read=await service.tool_sources(SimpleNamespace(),action='read',source_ref=receipt['source_ref'],excerpt_offset=len(body)-30)
    assert read['sources'][0]['excerpt']==body[-30:]
    chunks=cap.db.execute('SELECT * FROM capture_chunks ORDER BY seq').fetchall()
    assert ''.join(row['body'] for row in chunks)==body
    assert all(chunks[i]['byte_offset']==len(''.join(r['body'] for r in chunks[:i]).encode('utf-8')) for i in range(len(chunks)))


async def test_same_operation_retry_and_payload_conflict(service,ctx):
    cap,identity=owner(service,ctx); p=prepared(cap,identity)
    receipt=commit(cap,p)
    assert commit(cap,p)==receipt
    assert commit(cap,prepared(cap,identity,'不同的原文'))['status']=='conflict'
    assert cap.db.execute('SELECT count(*) FROM timeline').fetchone()[0]==1


async def test_receipt_commits_atomically_with_body_and_recovers_after_reopen(service,ctx):
    cap,identity=owner(service,ctx); p=prepared(cap,identity)
    cap.stage(p,generation='test')
    cap.db.executescript("CREATE TRIGGER fail_cap BEFORE UPDATE OF receipt ON capture_operations BEGIN SELECT RAISE(ABORT,'fault'); END;")
    with pytest.raises(sqlite3.IntegrityError): cap.commit(p['operation'],generation='test')
    assert cap.db.execute('SELECT count(*) FROM timeline').fetchone()[0]==0
    assert cap.lookup(p['operation'])['status']=='staged'
    cap.db.execute('DROP TRIGGER fail_cap')
    receipt=cap.commit(p['operation'],generation='test')
    path=cap.db.execute('PRAGMA database_list').fetchone()[2]
    service.store.close(); service.store=MemoryStore(path); service.store.initialize()
    reopened=SourceCapture(service.store); reopened.activate('next')
    assert reopened.lookup(p['operation'])==receipt
    assert reopened.commit(p['operation'],generation='next')==receipt


async def test_delete_scrubs_chunks_pending_and_preserves_receipt(service,ctx):
    cap,identity=owner(service,ctx); p=prepared(cap,identity)
    receipt=commit(cap,p)
    next_p=prepared(cap,identity,'修订',revision=2,expected_revision=1)
    cap.stage(next_p,generation='test')
    with service.store._lock,service.store._transaction_sync():
        cap.db.execute('DELETE FROM timeline WHERE id=?',(receipt['source_ref'].removeprefix('timeline:'),))
    assert cap.lookup(p['operation'])['status']=='committed'
    assert cap.lookup(p['operation'])['source_state']=='revoked'
    assert cap.lookup(next_p['operation'])['status']=='excluded'
    assert cap.db.execute('SELECT count(*) FROM capture_chunks').fetchone()[0]==0
    assert cap.db.execute("SELECT count(*) FROM capture_operations WHERE envelope!='{}'").fetchone()[0]==0
    assert commit(cap,next_p)['status']=='excluded'


async def test_withdrawal_removes_memories_derived_from_the_source(service,ctx):
    cap,identity=owner(service,ctx); receipt=commit(cap,prepared(cap,identity))
    source_id=receipt['source_ref'].removeprefix('timeline:')
    record=MemoryRecord(id='derived-summary',memory_type='conversation_summary',
        subject=EntityRef(kind='user',id=ctx.user_id),object=EntityRef.bot_self(ctx.bot_id),
        scope=ctx.scope,session_id=ctx.session_id,visibility='private_pair',lifecycle='stable_memory',
        content='摘要中的派生事实。',metadata={'source_event_ids':[source_id],
            'key_facts_with_refs':[{'fact':'派生事实','refs':[source_id],
                'evidence':[{'ref':source_id,'quote':'原文'}]}]})
    await service.store.insert_memory(record)
    source_key=cap.db.execute('SELECT source_key FROM capture_sources WHERE timeline_id=?',(source_id,)).fetchone()[0]

    cap.withdraw(source_key)

    assert await service.store.get_memory(record.id) is None


async def test_explicit_revision_changes_full_body_and_version(service,ctx):
    cap,identity=owner(service,ctx); first=commit(cap,prepared(cap,identity))
    second=commit(cap,prepared(cap,identity,'另一份完整原文',revision=2,expected_revision=1))
    assert second['source_ref']==first['source_ref'] and second['source_version']!=first['source_version']
    assert cap.lookup(first['operation'])['source_version']==first['source_version']
    assert ''.join(r[0] for r in cap.db.execute('SELECT body FROM capture_chunks ORDER BY seq'))=='另一份完整原文'


@pytest.mark.parametrize('field',['platform','bot','persona','session','speaker','audience','message'])
async def test_complete_identity_prevents_cross_owner_dedupe(service,ctx,field):
    cap,identity=owner(service,ctx)
    first=commit(cap,prepared(cap,identity))
    other=commit(cap,prepared(cap,{**identity,field:identity[field]+'-other'}))
    assert first['source_ref']!=other['source_ref']


async def test_redaction_across_chunk_boundary_preserves_original_whitespace(service,ctx):
    cap,identity=owner(service,ctx)
    body='  '+('a'*4084)+'\napi_key=only-a-test-value\n  尾部\r\n'
    receipt=commit(cap,prepared(cap,identity,body))
    stored=cap.db.execute('SELECT content FROM timeline').fetchone()[0]
    assert stored.startswith('  ') and stored.endswith('  尾部\r\n')
    assert 'only-a-test-value' not in stored and '[REDACTED]' in stored
    assert receipt['completeness']['redaction']=='changed'
    assert 'only-a-test-value' not in repr([tuple(row) for row in cap.db.execute('SELECT * FROM capture_operations')])


async def test_capacity_fence_and_delivery_evidence(service,ctx):
    cap,identity=owner(service,ctx)
    with pytest.raises(ValueError,match='capacity'): prepared(cap,identity,'中'*MAX_BODY_BYTES)
    with pytest.raises(ValueError,match='delivery_unproven'): prepared(cap,{**identity,'direction':'outgoing'})
    p=prepared(cap,identity)
    with pytest.raises(ValueError,match='authority_changed'): cap.stage(p,generation='old')
    with pytest.raises(ValueError,match='authority_changed'): cap.stage(p,generation='test',authorize=lambda:False)
    assert cap.lookup(p['operation'])['status']=='missing'


async def test_metadata_revision_lookup_and_disabled_pending_do_not_rewrite_committed(service,ctx):
    cap,identity=owner(service,ctx); first=commit(cap,prepared(cap,identity))
    with service.store._lock,service.store._transaction_sync():
        cap.db.execute("UPDATE timeline SET metadata=json_set(metadata,'$.annotation','changed')")
    receipt=cap.lookup(first['operation'])
    assert receipt['status']=='committed' and receipt['source_state']=='changed'
    second=prepared(cap,identity,'修订中',revision=2,expected_revision=1)
    cap.stage(second,generation='test'); cap.exclude_pending(second['operation'])
    assert cap.db.execute('SELECT content FROM timeline').fetchone()[0]==' 原文\r\n  最后一行  '
    assert cap.lookup(second['operation'])['status']=='excluded'


async def test_complete_source_chinese_secret_redaction(service,ctx):
    cap,identity=owner(service,ctx)
    receipt=commit(cap,prepared(cap,identity,'原文\n密码是example-test-value。\n尾部  '))
    stored=cap.db.execute('SELECT content FROM timeline').fetchone()[0]
    assert stored=='原文\n密码是[REDACTED]。\n尾部  '
    assert receipt['completeness']['redaction']=='changed'
