from __future__ import annotations

import asyncio
import contextvars
import inspect
import math
from contextlib import asynccontextmanager, contextmanager
from typing import Any


MIN_MEMORY_HOOK_BUDGET_SECONDS = 0.1
MAX_MEMORY_HOOK_BUDGET_SECONDS = 8.0
DEFAULT_MEMORY_HOOK_BUDGET_SECONDS = 1.0
MAX_MODEL_CALL_TIMEOUT_MS = 2000


class _ActiveTimeBudget:
    def __init__(
        self,
        timeout_seconds: float,
        *,
        model_call_budget_fraction: float | None = None,
        max_model_call_wait_seconds: float | None = None,
    ):
        self._loop = asyncio.get_running_loop()
        parsed_timeout = float(timeout_seconds)
        self._timeout = 0.0 if math.isnan(parsed_timeout) else max(0.0, parsed_timeout)
        self._started_at = self._loop.time()
        self._excluded_seconds = 0.0
        self._paused_at: float | None = None
        self._pause_depth = 0
        self._closed = False
        self._changed = asyncio.Event()
        if model_call_budget_fraction is None:
            self._model_call_budget_fraction: float | None = None
        else:
            parsed_fraction = float(model_call_budget_fraction)
            if math.isfinite(parsed_fraction):
                self._model_call_budget_fraction = min(1.0, max(0.0, parsed_fraction))
            else:
                self._model_call_budget_fraction = None
        if max_model_call_wait_seconds is None:
            self._max_model_call_wait_seconds: float | None = None
        else:
            parsed_max_wait = float(max_model_call_wait_seconds)
            if math.isfinite(parsed_max_wait):
                self._max_model_call_wait_seconds = max(0.0, parsed_max_wait)
            else:
                self._max_model_call_wait_seconds = None

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._changed.set()

    @property
    def remaining(self) -> float:
        active_now = self._paused_at if self._paused_at is not None else self._loop.time()
        elapsed = active_now - self._started_at - self._excluded_seconds
        return max(0.0, self._timeout - elapsed)

    @property
    def excluded_elapsed(self) -> float:
        paused = (
            max(0.0, self._loop.time() - self._paused_at)
            if self._paused_at is not None
            else 0.0
        )
        return max(0.0, self._excluded_seconds + paused)

    @property
    def model_call_budget_fraction(self) -> float | None:
        return self._model_call_budget_fraction

    @property
    def max_model_call_wait_seconds(self) -> float | None:
        return self._max_model_call_wait_seconds

    @property
    def model_call_wait_remaining(self) -> float | None:
        if self._max_model_call_wait_seconds is None:
            return None
        return max(0.0, self._max_model_call_wait_seconds - self.excluded_elapsed)

    def pause(self) -> None:
        self._pause_depth += 1
        if self._pause_depth == 1:
            self._paused_at = self._loop.time()
            self._changed.set()

    def resume(self) -> None:
        if self._pause_depth <= 0:
            return
        self._pause_depth -= 1
        if self._pause_depth == 0:
            now = self._loop.time()
            if self._paused_at is not None:
                self._excluded_seconds += max(0.0, now - self._paused_at)
            self._paused_at = None
            self._changed.set()

    async def wait_until_spent(self) -> None:
        while not self._closed and self.remaining > 0:
            self._changed.clear()
            if self._pause_depth:
                await self._changed.wait()
                continue
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=self.remaining)
            except asyncio.TimeoutError:
                return


_ACTIVE_MEMORY_HOOK_BUDGET: contextvars.ContextVar[_ActiveTimeBudget | None] = (
    contextvars.ContextVar("memory_hook_active_time_budget", default=None)
)


def _consume_task_result(task: asyncio.Future[Any]) -> None:
    try:
        task.exception()
    except (asyncio.CancelledError, Exception):
        pass


def _discard_awaitable(awaitable: Any) -> None:
    if not inspect.isawaitable(awaitable):
        raise TypeError("An asyncio.Future, a coroutine or an awaitable is required")
    if isinstance(awaitable, asyncio.Future):
        if not awaitable.done():
            awaitable.cancel()
        awaitable.add_done_callback(_consume_task_result)
        return
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()


MAX_HOOK_MODEL_CALL_WAIT_SECONDS = 12.0


def effective_model_call_timeout_seconds(timeout_seconds: float) -> float:
    """Bound a remote model call timeout against the active memory-hook budget.

    Outside an active ``on_llm_request`` hook (or when neither
    ``max_model_call_wait_seconds`` nor ``model_call_budget_fraction`` is set),
    returns ``max(0.0, float(timeout_seconds))`` unchanged.

    Inside a hook with remote-wait protection enabled:
    - If active local hook budget (``budget.remaining``, excluding
      ``exclude_model_call_wait()`` pauses) is already exhausted, returns
      ``0.0`` so downstream remote calls fail fast.
    - When ``max_model_call_wait_seconds`` is set, caps the call against the
      remaining shared excluded-wait ceiling ``budget.model_call_wait_remaining``
      so prior excluded external I/O (such as embedding) does not starve
      downstream rerank against the local hook budget while still enforcing a
      hard upper wall safety cap across all remote calls in the hook.
    - When ``model_call_budget_fraction`` is explicitly set, caps against
      ``budget.remaining * fraction`` (active remaining time rather than raw
      wall time) so excluded external waits do not eat into the local budget.
    """
    parsed = float(timeout_seconds)
    configured = 0.0 if math.isnan(parsed) else max(0.0, parsed)
    budget = _ACTIVE_MEMORY_HOOK_BUDGET.get()
    if budget is None or budget.closed:
        return configured
    max_wait_remaining = budget.model_call_wait_remaining
    fraction = budget.model_call_budget_fraction
    if max_wait_remaining is None and fraction is None:
        return configured
    active_remaining = budget.remaining
    if active_remaining <= 0.0:
        return 0.0
    effective = configured
    if max_wait_remaining is not None:
        effective = min(effective, max_wait_remaining)
    if fraction is not None:
        effective = min(effective, active_remaining * fraction)
    return max(0.0, effective)


async def await_with_timeout(awaitable: Any, timeout_seconds: float) -> Any:
    """Return at the deadline without waiting for provider cancellation cleanup."""
    effective_timeout = effective_model_call_timeout_seconds(timeout_seconds)
    if effective_timeout <= 0.0:
        _discard_awaitable(awaitable)
        raise asyncio.TimeoutError
    task = asyncio.ensure_future(awaitable)
    try:
        done, _pending = await asyncio.wait(
            {task}, timeout=effective_timeout
        )
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_consume_task_result)
        raise
    if task not in done:
        task.cancel()
        task.add_done_callback(_consume_task_result)
        raise asyncio.TimeoutError
    return task.result()


@contextmanager
def detach_memory_hook_budget() -> Any:
    """Temporarily clear the active hook budget when spawning detached work."""
    token = _ACTIVE_MEMORY_HOOK_BUDGET.set(None)
    try:
        yield
    finally:
        _ACTIVE_MEMORY_HOOK_BUDGET.reset(token)


@asynccontextmanager
async def exclude_model_call_wait() -> Any:
    """Exclude an awaited provider call from the active memory-hook budget."""
    budget = _ACTIVE_MEMORY_HOOK_BUDGET.get()
    if budget is None or budget.closed:
        yield
        return
    budget.pause()
    try:
        yield
    finally:
        budget.resume()


async def await_with_memory_hook_budget(
    awaitable: Any,
    timeout_seconds: float,
    *,
    model_call_budget_fraction: float | None = None,
    max_model_call_wait_seconds: float | None = None,
) -> Any:
    """Bound plugin work while allowing explicitly marked model calls to wait."""
    budget = _ActiveTimeBudget(
        timeout_seconds,
        model_call_budget_fraction=model_call_budget_fraction,
        max_model_call_wait_seconds=max_model_call_wait_seconds,
    )
    if budget._timeout <= 0.0:
        budget.close()
        _discard_awaitable(awaitable)
        raise asyncio.TimeoutError
    token = _ACTIVE_MEMORY_HOOK_BUDGET.set(budget)
    task: asyncio.Future[Any] | None = None
    deadline_task: asyncio.Task[Any] | None = None
    try:
        task = asyncio.ensure_future(awaitable)
        deadline_task = asyncio.create_task(budget.wait_until_spent())
        done, _pending = await asyncio.wait(
            {task, deadline_task}, return_when=asyncio.FIRST_COMPLETED
        )
    except BaseException:
        if task is not None:
            if not task.done():
                task.cancel()
            task.add_done_callback(_consume_task_result)
        raise
    finally:
        budget.close()
        _ACTIVE_MEMORY_HOOK_BUDGET.reset(token)
        if deadline_task is not None:
            if not deadline_task.done():
                deadline_task.cancel()
            deadline_task.add_done_callback(_consume_task_result)

    if task in done:
        return task.result()
    task.cancel()
    task.add_done_callback(_consume_task_result)
    raise asyncio.TimeoutError


def bounded_memory_hook_budget_seconds(value: Any) -> float:
    """Clamp a configured hook budget into the supported range.

    Booleans and values that are missing, non-finite or not positive fall back
    to the default, while positive values are clamped to ``[0.1, 8.0]``. The
    upper cap stops a local failure from holding a reply indefinitely while
    giving slow-disk or ``compat`` deployments enough headroom; the default
    stays at one second for fast local turns.
    """
    if isinstance(value, bool):
        return DEFAULT_MEMORY_HOOK_BUDGET_SECONDS
    try:
        configured = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_MEMORY_HOOK_BUDGET_SECONDS
    if not math.isfinite(configured) or configured <= 0:
        return DEFAULT_MEMORY_HOOK_BUDGET_SECONDS
    return max(
        MIN_MEMORY_HOOK_BUDGET_SECONDS,
        min(configured, MAX_MEMORY_HOOK_BUDGET_SECONDS),
    )


DEFAULT_MODEL_CALL_TIMEOUT_MS = MAX_MODEL_CALL_TIMEOUT_MS
MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS = 10000


def bounded_model_call_timeout_ms(
    value: Any,
    *,
    max_timeout_ms: int | None = None,
) -> int:
    """Clamp a configured remote model-call timeout into ``[1, cap]``.

    Booleans and values that are missing, invalid, or not positive fall back to
    ``DEFAULT_MODEL_CALL_TIMEOUT_MS`` (2000 ms). Explicit positive values are
    honored up to ``MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS`` (10000 ms) so
    multi-document rerank or embedding batches are not silently clamped down to
    2000 ms while still preventing unbounded remote waits.
    """
    cap = MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS
    if max_timeout_ms is not None and not isinstance(max_timeout_ms, bool):
        try:
            custom_cap = int(max_timeout_ms)
        except (TypeError, ValueError, OverflowError):
            custom_cap = cap
        if custom_cap > 0:
            cap = min(custom_cap, MAX_CONFIGURED_MODEL_CALL_TIMEOUT_MS)
    default_timeout = min(DEFAULT_MODEL_CALL_TIMEOUT_MS, cap)
    if isinstance(value, bool):
        return default_timeout
    try:
        configured = int(value)
    except (TypeError, ValueError, OverflowError):
        return default_timeout
    if configured <= 0:
        return default_timeout
    return min(configured, cap)
