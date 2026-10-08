# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.message_sources import bind, check, manage
from core.source_evidence import message_source_version
from core.store import MemoryStore
from core.models import EntityRef, MemoryRecord
from .test_source_query import service, ctx, add_row

pytestmark = pytest.mark.asyncio
BINDING = 'user:message-source-test'


async def read(service, ctx, *, source_id=None, event=None, **changes):
    source_id = source_id or await add_row(service, ctx, metadata={'message_id': 'native-message', **changes.pop('metadata', {})}, **changes)
    event = event or SimpleNamespace()
    result = await service.tool_sources(event, action='read', source_ref='timeline:' + source_id)
    assert result['ok'] and result['sources'], result
    return event, result['sources'][0]


async def watch(service, event):
    result = await bind(service, event, BINDING)
    assert result['status'] == 'current', result
    return result['items'][0]['ticket']


def state(service, ticket):
    return check(service, BINDING, [ticket])['items'][0]


def delete(service, source):
    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute('DELETE FROM timeline WHERE id=?', (source['source_ref'].removeprefix('timeline:'),))


async def test_actual_source_query_read_is_reference_only_and_preserves_v1_version(service, ctx):
    source_id = await add_row(service, ctx)
    before = service.store._conn.total_changes
    event, source = await read(service, ctx, source_id=source_id)
    assert service.store._conn.total_changes == before
    assert event.memory_companion_message_sources['refs'] == [{'id': source_id, 'version': source['source_version']}]
    ticket = await watch(service, event)
    assert state(service, ticket)['state'] == 'current'
    row = (await service.store.get_timeline_by_ids([source_id]))[source_id]
    assert message_source_version(row) == source['source_version']
    persisted = service.store._conn.execute('SELECT * FROM life_message_source_watches').fetchone()
    assert source['excerpt'] not in repr(dict(persisted))
    assert (await bind(service, SimpleNamespace(), BINDING))['status'] == 'unavailable'


@pytest.mark.parametrize('changes', [
    {'user_id': 'other'}, {'bot_id': 'other'}, {'persona_id': 'other'}, {'platform': 'other'},
    {'session_id': 'qq:FriendMessage:other'}, {'scope': 'group', 'group_id': 'group'},
])
async def test_read_does_not_authorize_a_changed_identity(service, ctx, changes):
    event, source = await read(service, ctx)
    service.identity.resolve_event_context = AsyncMock(return_value=replace(ctx, **changes))
    assert (await bind(service, event, BINDING))['status'] == 'unavailable'
    result = await manage(service, event, action='withdraw', operation_id='delete',
                          source_ref=source['source_ref'], expected_version=source['source_version'])
    assert not result['ok']
    assert await service.store.get_timeline_by_ids([source['source_ref'].removeprefix('timeline:')])


async def test_revision_and_temporary_unavailability_are_not_deletion(service, ctx):
    event, source = await read(service, ctx)
    ticket = await watch(service, event)
    source_id = source['source_ref'].removeprefix('timeline:')
    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute('UPDATE timeline SET content=? WHERE id=?', ('现在换成了豆浆', source_id))
    assert state(service, ticket) == {'ticket': ticket, 'state': 'changed'}
    gate = service._scope_feature_enabled
    service._scope_feature_enabled = lambda *_: False
    assert state(service, ticket) == {'ticket': ticket, 'state': 'unavailable'}
    service._scope_feature_enabled = gate
    assert state(service, ticket)['state'] == 'changed'
    service.store._conn.execute("UPDATE timeline SET metadata='[]' WHERE id=?", (source_id,))
    service.store._conn.commit()
    assert state(service, ticket)['state'] == 'unavailable'


async def test_missing_without_tombstone_is_unavailable(service, ctx):
    event, source = await read(service, ctx)
    ticket = await watch(service, event)
    service.store._conn.execute('DROP TRIGGER life_message_source_deleted')
    delete(service, source)
    assert state(service, ticket) == {'ticket': ticket, 'state': 'unavailable'}


async def test_delete_between_read_and_binding_preserves_revocation_proof(service, ctx):
    event, source = await read(service, ctx)
    delete(service, source)
    ticket = await watch(service, event)
    assert state(service, ticket)['state'] == 'revoked'
    assert state(service, ticket)['receipt'].startswith('message-withdrawal:')
    assert service.store._conn.execute('SELECT context FROM life_message_source_watches').fetchone()[0] == '{}'


async def test_withdrawal_receipt_replays_after_reopen_without_restoring_source(service, ctx):
    event, source = await read(service, ctx)
    ticket = await watch(service, event)
    request = dict(action='withdraw', operation_id='delete-original', source_ref=source['source_ref'],
                   expected_version=source['source_version'])
    receipt = await manage(service, event, **request)
    assert receipt['ok'] and receipt['status'] == 'committed' and receipt['source_state'] == 'revoked'
    path = service.store._conn.execute('PRAGMA database_list').fetchone()[2]
    service.store.close()
    service.store = MemoryStore(path)
    service.store.initialize()
    assert await manage(service, SimpleNamespace(), action='lookup', operation_id='delete-original') == receipt
    assert await manage(service, SimpleNamespace(), **request) == receipt
    assert (await manage(service, event, **{**request, 'expected_version': '0' * 64}))['status'] == 'conflict'
    assert state(service, ticket)['state'] == 'revoked'
    assert await add_row(service, ctx, metadata={'message_id': 'native-message'}) == ''
    assert source['excerpt'] not in repr([dict(row) for row in service.store._conn.execute('SELECT * FROM message_source_tombstones')])


async def test_existing_database_installs_other_timeline_deletion_governance_on_reopen(service, ctx):
    key = await add_row(service, ctx, event_type='proactive_message')
    service.store._conn.execute('DROP TRIGGER life_reply_timeline_deleted')
    service.store._conn.commit()
    path = service.store._conn.execute('PRAGMA database_list').fetchone()[2]
    service.store.close()
    service.store = MemoryStore(path)
    service.store.initialize()
    with service.store._lock, service.store._transaction_sync():
        service.store._conn.execute('DELETE FROM timeline WHERE id=?', (key,))
    row = service.store._conn.execute('SELECT event_type FROM message_source_tombstones WHERE source_id=?', (key,)).fetchone()
    assert row['event_type'] == 'proactive_message'


async def test_withdrawal_failure_rolls_back_source_tombstone_watch_and_receipt(service, ctx):
    event, source = await read(service, ctx)
    ticket = await watch(service, event)
    service.store._conn.executescript("""CREATE TRIGGER fail_receipt BEFORE INSERT ON life_message_withdrawals
        BEGIN SELECT RAISE(ABORT,'injected receipt failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match='receipt failure'):
        await manage(service, event, action='withdraw', operation_id='rollback', source_ref=source['source_ref'],
                     expected_version=source['source_version'])
    assert state(service, ticket)['state'] == 'current'
    assert service.store._conn.execute('SELECT count(*) FROM message_source_tombstones').fetchone()[0] == 0
    assert (await manage(service, event, action='lookup', operation_id='rollback'))['status'] == 'missing'


async def test_owner_fence_and_expected_revision_are_checked_before_delete(service, ctx):
    event, source = await read(service, ctx)
    request = dict(action='withdraw', operation_id='fenced', source_ref=source['source_ref'], expected_version=source['source_version'])
    assert not (await manage(service, event, authorize=lambda: False, **request))['ok']
    service.store._conn.execute('UPDATE timeline SET content=? WHERE id=?', ('修订后', source['source_ref'].removeprefix('timeline:')))
    service.store._conn.commit()
    assert (await manage(service, event, **request))['error'] == 'source_version_changed'
    assert service.store._conn.execute('SELECT count(*) FROM timeline').fetchone()[0] == 1


@pytest.mark.parametrize('port', ['private_clear', 'all_clear', 'prune', 'import_rollback'])
async def test_existing_owner_delete_ports_revoke_watches_and_suppress_history_replay(service, ctx, port):
    event, source = await read(service, ctx, metadata={'import_batch_id': 'test-batch'})
    source_id = source['source_ref'].removeprefix('timeline:')
    ticket = await watch(service, event)
    old = (await service.store.get_timeline_by_ids([source_id]))[source_id]
    old['metadata'] = json.loads(old['metadata'])
    if port == 'private_clear':
        await service.store.clear_scoped_memory(target_type='private', user_id=ctx.user_id)
    elif port == 'all_clear':
        await service.store.clear_all_memory_data()
    elif port == 'prune':
        await service.store.mark_timeline_summarized([source_id])
        await service.store.prune_retained_rows(summarized_timeline_cutoff='2027-01-01T00:00:00Z')
    else:
        await service.store.rollback_chat_import_batch('test-batch')
    assert state(service, ticket)['state'] == 'revoked'
    old['id'] = 'tl_replayed_with_new_row_id'
    assert await service.store.add_historical_timeline_events_with_status([old]) == ({}, set())
    assert await add_row(service, ctx, metadata={'message_id': 'native-message'}) == ''


@pytest.mark.parametrize('change', ['bot', 'persona', 'platform', 'session', 'user', 'native_id'])
async def test_suppression_uses_native_identity_and_full_known_ownership(service, ctx, change):
    event, source = await read(service, ctx)
    delete(service, source)
    ctx_changes = {'bot': {'bot_id': 'different-bot'}, 'persona': {'persona_id': 'different-persona'},
                   'platform': {'platform': 'different-platform'}, 'session': {'session_id': 'qq:FriendMessage:elsewhere'},
                   'user': {'user_id': 'different-user'}, 'native_id': {}}[change]
    changed = await add_row(service, replace(ctx, **ctx_changes), metadata={
        'message_id': 'another-message' if change == 'native_id' else 'native-message'})
    assert changed.startswith('tl_')
    assert (await service.store.get_timeline_by_ids([changed]))[changed]['content'] == source['excerpt']


async def test_rebind_cannot_move_a_live_row_into_a_deleted_native_identity(service, ctx):
    event, source = await read(service, ctx)
    delete(service, source)
    other = await add_row(service, ctx, metadata={'message_id': 'different'})
    with pytest.raises(sqlite3.IntegrityError, match='message_source_revoked'):
        with service.store._lock, service.store._transaction_sync():
            service.store._conn.execute('UPDATE timeline SET message_id=? WHERE id=?', ('native-message', other))
    assert (await service.store.get_timeline_by_ids([other]))[other]['message_id'] == 'different'


async def test_suppressed_inbound_capture_stops_before_derived_writes(service, ctx):
    current = replace(ctx, message_id='native-message', message_text='这一餐是无糖拿铁')
    event, source = await read(service, current)
    delete(service, source)
    service.note_identity = AsyncMock()
    assert service.classifier.from_user_message(current) is not None
    service.portraits.capture_user_message = AsyncMock()
    service.store.capture_write_batch = AsyncMock()
    await service._capture_async(current, event, SimpleNamespace(), [])
    assert service.store._conn.execute('SELECT count(*) FROM timeline').fetchone()[0] == 0
    service.portraits.capture_user_message.assert_not_awaited()
    service.store.capture_write_batch.assert_not_awaited()


async def test_navigation_raw_fragments_bind_the_versions_actually_returned(service, ctx):
    source_id = await add_row(service, ctx)
    record = MemoryRecord(id='navigation-summary', memory_type='conversation_summary', scope=ctx.scope,
        session_id=ctx.session_id, platform=ctx.platform, owner_bot_id=ctx.bot_id,
        subject=EntityRef(kind='user', id=ctx.user_id), object=EntityRef(kind='bot', id=ctx.bot_id),
        lifecycle='stable_memory', visibility='private_pair', content='谈过早餐。',
        metadata={'source_event_ids': [source_id], 'persona_id': ctx.persona_id, 'owner_bot_id': ctx.bot_id})
    await service.store.insert_memory(record)
    event = SimpleNamespace()
    result = await service.tool_navigate(event, action='event_time', memory_ids=[record.id])
    assert result['ok'] and result['evidence'][0]['sources'], result
    source = result['evidence'][0]['sources'][0]
    assert event.memory_companion_message_sources['refs'] == [{'id': source_id, 'version': source['source_version']}]
    assert state(service, await watch(service, event))['state'] == 'current'


async def test_visible_delivery_record_replay_cannot_reinsert_withdrawn_source(service, ctx):
    service._schedule_session_summary = Mock()
    params = dict(role='assistant', content='桌上的菜谱已经整理好了。', scope=ctx.scope, session_id=ctx.session_id,
        platform=ctx.platform, user_id=ctx.user_id, message_id='delivery-part-original',
        source='private_companion_confirmed_reply', metadata={'bot_id': ctx.bot_id, 'persona_id': ctx.persona_id,
                                                            'delivery_confirmed': True})
    source_id = await service.record_visible_turn(**params)
    assert source_id.startswith('tl_')
    event, source = await read(service, ctx, source_id=source_id)
    await watch(service, event)
    delete(service, source)
    service._schedule_session_summary.reset_mock()
    assert await service.record_visible_turn(**params) == ''
    service._schedule_session_summary.assert_not_called()


async def test_multiple_read_versions_remain_distinct_from_query_cursor_expiry(service, ctx):
    event, first = await read(service, ctx)
    source_id = first['source_ref'].removeprefix('timeline:')
    service.store._conn.execute('UPDATE timeline SET content=? WHERE id=?', ('后来改成豆浆。', source_id))
    service.store._conn.commit()
    # A different query can re-read the same source within this real turn.
    later = await service.tool_sources(event, terms=['豆浆'])
    assert later['ok'] and len(event.memory_companion_message_sources['refs']) == 2
    for value in service._reconstruction_states.values():
        for receipt in value.get('issued_sources', {}).values():
            receipt['expires_at'] = 0
    watches = await bind(service, event, BINDING)
    states = [state(service, item['ticket'])['state'] for item in watches['items']]
    assert states == ['changed', 'current']


async def test_deleted_source_cannot_receive_another_owners_legacy_dedupe_receipt(service, ctx):
    event, source = await read(service, ctx)
    source_id = source['source_ref'].removeprefix('timeline:')
    original = (await service.store.get_timeline_by_ids([source_id]))[source_id]
    original['metadata'] = json.loads(original['metadata'])
    delete(service, source)
    other = await add_row(service, replace(ctx, bot_id='another-bot'), metadata={'message_id': 'native-message'})
    assert other.startswith('tl_')
    assert await add_row(service, ctx, metadata={'message_id': 'native-message'}) == ''
    original['id'] = 'tl_replay'
    assert await service.store.add_historical_timeline_events_with_status([original]) == ({}, set())
    assert (await service.store.get_timeline_by_ids([other]))[other]['id'] == other
