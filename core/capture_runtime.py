"""AstrBot adapters for the original-message store; never sends messages."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import secrets

from .models import SessionContext, utc_now
from .source_capture import SourceCapture, digest


class CaptureRuntime:
    def __init__(self, service):
        self.service = service
        self.store = SourceCapture(service.store)
        self.generation = secrets.token_hex(16)
        self.store.activate(self.generation)
        self.wake = asyncio.Event()
        self.task = None
        self.last_error = ''

    def start(self):
        if self.task is None or self.task.done():
            self.task = self.service._spawn_background(self.loop(), label='source-capture', defer_during_grace=True)

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
        if not getattr(event,'_s4_source_capture_enabled',False):
            return None
        if (not s.config.bool('memory_capture.reliable_sources_enabled',True)
                or getattr(event,'private_companion_req036_denied',False)
                or s._private_companion_internal_generation_event(event)):
            return None
        ctx=ctx or s._normalized_session_context(await s.identity.resolve_event_context(event))
        obj=getattr(event,'message_obj',None)
        raw_id=str(getattr(obj,'message_id','') or ctx.message_id or '')
        if not raw_id:
            raw_id='observed:'+secrets.token_hex(24)
        identity=self.identity(ctx,direction='incoming',message=raw_id)
        if not self.allowed(identity):
            return None
        # Keep exact visible Plain components. message_str is a trusted adapter
        # fallback with explicitly weaker observation completeness.
        parts=getattr(obj,'message',None)
        body=''.join(str(p.text) for p in parts if type(p).__name__=='Plain') if isinstance(parts,list) else str(getattr(event,'message_str','') or '')
        if not body:
            return None
        stamp=getattr(obj,'timestamp',None)
        try:
            message_at=datetime.fromtimestamp(float(stamp),timezone.utc).isoformat() if stamp else ''
        except (TypeError,ValueError,OverflowError,OSError):
            message_at=''
        try:
            prepared=self.store.prepare(identity,body=body,source_message_at=message_at,observed_at=utc_now())
            authorize=lambda: self.allowed(identity)
            result=self.store.stage(prepared,generation=self.generation,authorize=authorize)
            if result['status'] in {'staged','uncertain','retry_due'}:
                result=self.store.commit(prepared['operation'],generation=self.generation,authorize=authorize)
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

    def submit(self, identity, request, *, authorize=lambda: True):
        if not self.allowed(identity) or not authorize():
            return {'status':'excluded','reason':'capture_disabled'}
        prepared=self.store.prepare(identity,**request)
        check=lambda: self.allowed(identity) and authorize()
        result=self.store.stage(prepared,generation=self.generation,authorize=check)
        if result['status'] in {'staged','uncertain','retry_due'}:
            result=self.store.commit(prepared['operation'],generation=self.generation,authorize=check)
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
            rows=self.store.due()
            for row in rows:
                try:
                    payload=json.loads(row['envelope']); identity=payload['identity']
                    if not self.allowed(identity):
                        self.store.exclude_pending(row['operation'])
                    else:
                        self.store.commit(row['operation'],generation=self.generation,authorize=lambda: self.allowed(identity))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error=type(exc).__name__
                    self.store.retry(row['operation'],self.generation)
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
