from __future__ import annotations

import asyncio
import contextvars
import math
from contextlib import asynccontextmanager
from typing import Any


MAX_MEMORY_HOOK_BUDGET_SECONDS = 1.0
MAX_MODEL_CALL_TIMEOUT_MS = 2000


class _ActiveTimeBudget:
    def __init__(self, timeout_seconds: float):
        self._loop = asyncio.get_running_loop()
        self._timeout = max(0.0, float(timeout_seconds))
        self._started_at = self._loop.time()
        self._excluded_seconds = 0.0
        self._paused_at: float | None = None
        self._pause_depth = 0
        self._changed = asyncio.Event()

    @property
    def remaining(self) -> float:
        now = self._loop.time()
        paused = now - self._paused_at if self._paused_at is not None else 0.0
        elapsed = now - self._started_at - self._excluded_seconds - paused
        return max(0.0, self._timeout - elapsed)

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
                self._excluded_seconds += now - self._paused_at
            self._paused_at = None
            self._changed.set()

    async def wait_until_spent(self) -> None:
        while self.remaining > 0:
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


async def await_with_timeout(awaitable: Any, timeout_seconds: float) -> Any:
    """Return at the deadline without waiting for provider cancellation cleanup."""
    task = asyncio.ensure_future(awaitable)
    try:
        done, _pending = await asyncio.wait(
            {task}, timeout=max(0.0, float(timeout_seconds))
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


@asynccontextmanager
async def exclude_model_call_wait() -> Any:
    """Exclude an awaited provider call from the active memory-hook budget."""
    budget = _ACTIVE_MEMORY_HOOK_BUDGET.get()
    if budget is None:
        yield
        return
    budget.pause()
    try:
        yield
    finally:
        budget.resume()


async def await_with_memory_hook_budget(awaitable: Any, timeout_seconds: float) -> Any:
    """Bound plugin work while allowing explicitly marked model calls to wait."""
    budget = _ActiveTimeBudget(timeout_seconds)
    token = _ACTIVE_MEMORY_HOOK_BUDGET.set(budget)
    task = asyncio.ensure_future(awaitable)
    deadline_task = asyncio.create_task(budget.wait_until_spent())
    try:
        done, _pending = await asyncio.wait(
            {task, deadline_task}, return_when=asyncio.FIRST_COMPLETED
        )
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_consume_task_result)
        raise
    finally:
        _ACTIVE_MEMORY_HOOK_BUDGET.reset(token)
        if not deadline_task.done():
            deadline_task.cancel()
        deadline_task.add_done_callback(_consume_task_result)

    if task in done:
        return task.result()
    task.cancel()
    task.add_done_callback(_consume_task_result)
    raise asyncio.TimeoutError


def bounded_memory_hook_budget_seconds(value: Any) -> float:
    try:
        configured = float(value)
    except (TypeError, ValueError, OverflowError):
        return MAX_MEMORY_HOOK_BUDGET_SECONDS
    if not math.isfinite(configured) or configured <= 0:
        return MAX_MEMORY_HOOK_BUDGET_SECONDS
    return min(configured, MAX_MEMORY_HOOK_BUDGET_SECONDS)


def bounded_model_call_timeout_ms(value: Any) -> int:
    try:
        configured = int(value)
    except (TypeError, ValueError, OverflowError):
        return MAX_MODEL_CALL_TIMEOUT_MS
    if configured <= 0:
        return MAX_MODEL_CALL_TIMEOUT_MS
    return min(configured, MAX_MODEL_CALL_TIMEOUT_MS)
