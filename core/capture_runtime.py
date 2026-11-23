"""AstrBot adapters for the original-message store; never sends messages."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import secrets

from .models import SessionContext, utc_now
from .source_capture import SourceCapture, digest
from .forward_extractor import (
    DEFAULT_CARD_MAX_CHARS,
    ParsedForwards,
    build_forward_media_refs,
    extract_forwards,
    format_forward_capture_body,
    format_single_card_text,
    group_separate_card_entries,
    split_distinct_card_entries,
)

logger = logging.getLogger("astrbot_plugin_memory_companion.capture_runtime")


async def _in_thread(function, *args, **kwargs):
    """Run one synchronous store write unit outside the event loop.

    Every capture write path takes the store's threading lock and opens its own
    ``BEGIN IMMEDIATE`` transaction, so the work is pure blocking I/O: running it
    on the loop thread would stall every other session for as long as SQLite
    needs to commit. Only plain values cross the thread boundary — the callables
    passed in are closed over service state and never touch the event loop.
    """
    return await asyncio.to_thread(function, *args, **kwargs)


class CaptureRuntime:
    def __init__(self, service):
        self.service = service
        config = getattr(service, 'config', None)
        default_enabled = config.bool('memory_capture.source_capture_enabled', True) if config is not None else True
        retention_days = config.int('memory_capture.source_retention_days', 7) if config is not None else 7
        self.store = SourceCapture(service.store, default_enabled=default_enabled,
                                   retention_seconds=max(0, retention_days) * 86400)
        self.generation = secrets.token_hex(16)
        self.store.activate(self.generation)
        self.wake = asyncio.Event()
        self.task = None
        self.last_error = ''

    def start(self):
        if self.task is None or self.task.done():
            self.task = self.service._spawn_background(self.loop(), label='source-capture', defer_during_grace=True)

    def source_capture_enabled(self):
        return self.store.source_capture_enabled()

    def set_source_capture_enabled(self, enabled, *, actor=''):
        return self.store.set_source_capture_enabled(enabled, actor=actor)

    def read_original(self, source_key, *, authorize=lambda: True):
        return self.store.read_body(source_key, authorize=authorize)

    def purge_expired(self, now=None):
        return self.store.purge_expired(now)

    def allowed(self, identity):
        s = self.service
        ctx = SessionContext(scope=identity['scope'],session_id=identity['session'],platform=identity['platform'],
                             bot_id=identity['bot'],persona_id=identity['persona'],
                             user_id=identity['audience'] if identity['scope']=='private' else identity['speaker'],
                             group_id=identity['audience'] if identity['scope']=='group' else '')
        return (not getattr(s,'_closing',False) and not getattr(s,'_closed',False)
                and s.config.bool('memory_capture.enabled',True)
                and s.config.bool('memory_capture.reliable_sources_enabled',True)
                and s.config.bool('memory_capture.capture_user_messages' if identity['direction']=='incoming' else 'memory_capture.capture_bot_responses',True)
                and s._scope_feature_enabled(ctx,'capture'))

    def identity(self, ctx, *, direction, message):
        return dict(installation=self.store.installation,platform=ctx.platform,bot=ctx.bot_id,persona=ctx.persona_id,
                    scope=ctx.scope,session=ctx.session_id,speaker=ctx.user_id if direction=='incoming' else ctx.bot_id,
                    audience=ctx.user_id if ctx.scope=='private' else ctx.group_id,direction=direction,message=message)

    async def incoming(self, event, ctx=None):
        old=getattr(event,'_memory_capture_receipt',None)
        if old is not None:
            return old
        s=self.service
        if not await _in_thread(self.source_capture_enabled):
            return None
        if (not s.config.bool('memory_capture.reliable_sources_enabled',True)
                or getattr(event,'private_companion_req036_denied',False)
                or s._private_companion_internal_generation_event(event)):
            return None
        ctx=ctx or s._normalized_session_context(await s.identity.resolve_event_context(event))
        obj=getattr(event,'message_obj',None)
        explicit_id=str(getattr(obj,'message_id','') or ctx.message_id or '')
        raw_id=explicit_id or ('observed:'+secrets.token_hex(24))
        identity=self.identity(ctx,direction='incoming',message=raw_id)
        if not self.allowed(identity):
            return None
        # Keep exact visible Plain components. message_str is a trusted adapter
        # fallback with explicitly weaker observation completeness.
        parts=getattr(obj,'message',None)
        body=''.join(str(p.text) for p in parts if type(p).__name__=='Plain') if isinstance(parts,list) else str(getattr(event,'message_str','') or '')
        parsed_forwards=await extract_forwards(event)
        if not body and parsed_forwards is None:
            return None
        stamp=getattr(obj,'timestamp',None)
        try:
            message_at=datetime.fromtimestamp(float(stamp),timezone.utc).isoformat() if stamp else ''
        except (TypeError,ValueError,OverflowError,OSError):
            message_at=''
        if parsed_forwards is not None:
            return await self._incoming_forwards(event,ctx,explicit_id,body,message_at,parsed_forwards)
        fast_commit=getattr(self.store,'stage_and_commit_incoming',None)
        if callable(fast_commit):
            return await self._incoming_single_hop(event,identity,body,message_at,fast_commit)
        try:
            prepared=await _in_thread(self.store.prepare,identity,body=body,source_message_at=message_at,observed_at=utc_now())
            authorize=lambda: self.allowed(identity)
            result=await _in_thread(self.store.stage,prepared,generation=self.generation,authorize=authorize)
            if result['status'] in {'staged','uncertain','retry_due'}:
                result=await _in_thread(self.store.commit,prepared['operation'],generation=self.generation,authorize=authorize)
            setattr(event,'_memory_capture_receipt',result)
            self.wake.set()
            return result
        except (ValueError,UnicodeError) as exc:
            result={'status':'held','reason':str(exc),'durably_staged':False}
        except Exception as exc:
            result={'status':'uncertain','reason':type(exc).__name__}
        setattr(event,'_memory_capture_receipt',result)
        self.last_error=result['reason']
        self.wake.set()
        return result

    async def submit(self, identity, request, *, authorize=lambda: True):
        if not self.allowed(identity) or not authorize():
            return {'status':'excluded','reason':'capture_disabled'}
        prepared=await _in_thread(self.store.prepare,identity,**request)
        check=lambda: self.allowed(identity) and authorize()
        result=await _in_thread(self.store.stage,prepared,generation=self.generation,authorize=check)
        if result['status'] in {'staged','uncertain','retry_due'}:
            result=await _in_thread(self.store.commit,prepared['operation'],generation=self.generation,authorize=check)
        if result.get('status')=='committed' and identity['direction']=='outgoing' and hasattr(self.service,'_summary_workers'):
            ctx=SessionContext(scope=identity['scope'],session_id=identity['session'],platform=identity['platform'],
                               bot_id=identity['bot'],persona_id=identity['persona'],
                               user_id=identity['audience'] if identity['scope']=='private' else '',
                               group_id=identity['audience'] if identity['scope']=='group' else '')
            try:
                self.service._schedule_session_summary(ctx,reason='confirmed_source')
            except Exception as exc:
                # Submission already committed; an optional summary must not
                # turn its receipt into an uncertain source-write result.
                self.last_error=type(exc).__name__
        self.wake.set()
        return result

    async def loop(self):
        while not getattr(self.service,'_closing',False):
            self.wake.clear()
            try:
                await _in_thread(self.store.purge_expired)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error=type(exc).__name__
            try:
                rows=await _in_thread(self.store.due)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error=type(exc).__name__
                logger.debug('[MemoryCompanion] 读取待重试采集队列失败: error=%s', exc)
                rows=[]
            for row in rows:
                try:
                    payload=json.loads(row['envelope']); identity=payload['identity']
                    if not self.allowed(identity):
                        await _in_thread(self.store.exclude_pending,row['operation'])
                    else:
                        await _in_thread(self.store.commit,row['operation'],generation=self.generation,
                                         authorize=lambda: self.allowed(identity))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error=type(exc).__name__
                    try:
                        await _in_thread(self.store.retry,row['operation'],self.generation)
                    except asyncio.CancelledError:
                        raise
                    except Exception as retry_exc:
                        self.last_error=type(retry_exc).__name__
                        logger.warning(
                            '[MemoryCompanion] 采集重试记账失败: operation=%s error=%s',
                            row.get('operation', '') if isinstance(row, dict) else '',
                            retry_exc,
                        )
            if len(rows)>=8:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self.wake.wait(),timeout=60)
            except asyncio.TimeoutError:
                pass

    def status(self):
        return {**self.store.status(),'last_error':self.last_error,
                'worker_running':bool(self.task and not self.task.done())}

    async def _incoming_single_hop(self,event,identity,body,message_at,fast_commit):
        """Execute incoming capture in one worker-thread hop and one SQLite commit."""
        def run_sync():
            store_dict=getattr(self.store,'__dict__',{})
            if any(name in store_dict for name in ('prepare','stage','commit')):
                prepared=self.store.prepare(identity,body=body,source_message_at=message_at,observed_at=utc_now())
                authorize=lambda: self.allowed(identity)
                result=self.store.stage(prepared,generation=self.generation,authorize=authorize)
                if result['status'] in {'staged','uncertain','retry_due'}:
                    result=self.store.commit(prepared['operation'],generation=self.generation,authorize=authorize)
                return result
            return fast_commit(
                identity,
                body=body,
                source_message_at=message_at,
                observed_at=utc_now(),
                generation=self.generation,
                authorize=lambda: self.allowed(identity),
            )

        try:
            result=await asyncio.to_thread(run_sync)
            setattr(event,'_memory_capture_receipt',result)
            self.wake.set()
            return result
        except (ValueError,UnicodeError) as exc:
            result={'status':'held','reason':str(exc),'durably_staged':False}
        except Exception as exc:
            result={'status':'uncertain','reason':type(exc).__name__}
        setattr(event,'_memory_capture_receipt',result)
        self.last_error=result['reason']
        self.wake.set()
        return result

    async def _incoming_forwards(self,event,ctx,explicit_id,plain_body,message_at,parsed_forwards):
        """Capture forward cards (single, mixed, or multi-card aggregated) with dedupe."""
        has_own_text = bool(str(plain_body or "").strip())
        separate_cards, attached_cards = split_distinct_card_entries(
            parsed_forwards,
            outer_message_id=explicit_id,
            has_own_text=has_own_text,
        )
        units: list[tuple[dict, str, str, list[dict[str, str]]]] = []
        seen_unit_ids: set[str] = set()

        for group_id, group_cards in group_separate_card_entries(separate_cards):
            if group_id in seen_unit_ids:
                continue
            seen_unit_ids.add(group_id)
            if len(group_cards) == 1:
                card = group_cards[0]
                group_body = format_single_card_text(card, max_chars=DEFAULT_CARD_MAX_CHARS, single_line=False)
                group_ts = card.timestamp or message_at
            else:
                group_parsed = ParsedForwards(
                    version=parsed_forwards.version,
                    source=parsed_forwards.source,
                    cards=tuple(group_cards),
                    total_nodes=sum(c.node_count for c in group_cards),
                    truncated=any(c.truncated for c in group_cards),
                )
                group_body = format_forward_capture_body("", group_parsed)
                group_ts = next((c.timestamp for c in group_cards if c.timestamp), "") or message_at
            group_media = build_forward_media_refs(group_cards)
            units.append((self.identity(ctx, direction='incoming', message=group_id), group_body, group_ts, group_media))

        if attached_cards:
            outer_id = explicit_id
            if not outer_id:
                fwd_ids = [card.forward_id for card in attached_cards if card.forward_id]
                if len(fwd_ids) == 1:
                    outer_id = f"forward:{fwd_ids[0]}"
                elif fwd_ids:
                    outer_id = f"forward:{digest(fwd_ids)[:24]}"
                else:
                    outer_id = 'observed:' + secrets.token_hex(24)
            if outer_id not in seen_unit_ids:
                seen_unit_ids.add(outer_id)
                attached_parsed = ParsedForwards(
                    version=parsed_forwards.version,
                    source=parsed_forwards.source,
                    cards=tuple(attached_cards),
                    total_nodes=sum(card.node_count for card in attached_cards),
                    truncated=any(card.truncated for card in attached_cards),
                )
                outer_body = format_forward_capture_body(plain_body, attached_parsed)
                outer_media = build_forward_media_refs(attached_cards)
                units.append((self.identity(ctx, direction='incoming', message=outer_id), outer_body, message_at, outer_media))
        elif has_own_text:
            outer_id = explicit_id or ('observed:' + secrets.token_hex(24))
            if outer_id not in seen_unit_ids:
                seen_unit_ids.add(outer_id)
                units.append((self.identity(ctx, direction='incoming', message=outer_id), plain_body, message_at, []))

        if not units:
            return None

        receipts: list[dict] = []
        for unit_identity, unit_body, unit_ts, unit_media in units:
            receipt = await self._commit_incoming_unit(unit_identity, unit_body, unit_ts, media=unit_media)
            receipts.append(receipt)

        primary = next(
            (r for r in reversed(receipts) if isinstance(r, dict) and r.get('status') == 'committed'),
            receipts[-1],
        )
        setattr(event, '_memory_capture_receipts', receipts)
        setattr(event, '_memory_capture_receipt', primary)
        if any(not isinstance(r, dict) or r.get('status') not in {'committed', 'excluded'} for r in receipts):
            self.wake.set()
        return primary

    async def _commit_incoming_unit(self, identity, body, message_at, *, media=None):
        """Commit one incoming unit via single-hop fast path or prepare/stage/commit."""
        media_list = list(media or [])
        fast_commit = getattr(self.store, 'stage_and_commit_incoming', None)

        def run_sync():
            store_dict = getattr(self.store, '__dict__', {})
            use_staged = (not callable(fast_commit)) or any(
                name in store_dict for name in ('prepare', 'stage', 'commit')
            )
            kwargs = {'media': media_list} if media_list else {}
            if use_staged:
                prepared = self.store.prepare(
                    identity,
                    body=body,
                    source_message_at=message_at,
                    observed_at=utc_now(),
                    **kwargs,
                )
                authorize = lambda: self.allowed(identity)
                result = self.store.stage(prepared, generation=self.generation, authorize=authorize)
                if result['status'] in {'staged', 'uncertain', 'retry_due'}:
                    result = self.store.commit(prepared['operation'], generation=self.generation, authorize=authorize)
                return result
            return fast_commit(
                identity,
                body=body,
                source_message_at=message_at,
                observed_at=utc_now(),
                generation=self.generation,
                authorize=lambda: self.allowed(identity),
                **kwargs,
            )

        try:
            return await asyncio.to_thread(run_sync)
        except (ValueError, UnicodeError) as exc:
            result = {'status': 'held', 'reason': str(exc), 'durably_staged': False}
            self.last_error = result['reason']
            return result
        except Exception as exc:
            result = {'status': 'uncertain', 'reason': type(exc).__name__}
            self.last_error = result['reason']
            return result
