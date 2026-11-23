"""Helpers that keep large JSON writes off the event loop.

Plugin bookkeeping lives in a few JSON documents that grow over time (token
statistics, relationship state). Serialising and writing them on the loop thread
stalls every other session, so the work is handed to a worker thread.

Three small pieces make that safe:

:func:`plain_json_copy` freezes a live mapping into plain data on the loop
thread, so a worker thread can serialise a stable snapshot while the loop keeps
mutating the original document.
:func:`write_json_atomically` swaps the file in one step using a unique staging
file, so readers never observe a half written document.
:class:`BackgroundJsonWriter` serialises writers of a single document using
monotonically increasing request generations, coalescing bursts on the loop and
discarding any stale snapshot before it can touch disk.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .astrbot_compat import logger

JSON_SCALARS = (str, int, float, bool)


def running_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the loop of the calling thread, or ``None`` outside a coroutine."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def plain_json_copy(value: Any) -> Any:
    """Detach ``value`` into JSON-only types so another thread may read it.

    Containers are rebuilt rather than referenced, so the caller can keep
    mutating the live document while a worker serialises the returned snapshot.
    Values that ``json`` cannot encode raise ``TypeError``, matching the failure
    a direct ``json.dumps`` of the live document would produce.
    """
    if value is None or isinstance(value, JSON_SCALARS):
        return value
    if isinstance(value, dict):
        return {key: plain_json_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_json_copy(item) for item in value]
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def write_json_atomically(path: Path | str, payload: str) -> None:
    """Replace ``path`` with ``payload`` in one step; safe from any thread.

    The staging file name is unique per write, so concurrent writers never share
    a temporary path: the last completed write always publishes a whole
    document. On Windows a concurrent replace of the same target can fail with
    ``PermissionError`` while another thread holds the file open, so the swap is
    retried a few times; a write that never wins still leaves the previous
    document intact.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        _replace_with_retry(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _replace_with_retry(source: str, target: Path, attempts: int = 60) -> None:
    """Swap ``source`` onto ``target``, tolerating transient sharing violations.

    Windows refuses ``os.replace`` while any reader holds the destination open, so
    a swap can fail with ``PermissionError`` even though the write itself is fine.
    Retrying for roughly a second rides out an ordinary read; a genuinely stuck
    file still surfaces so the caller can keep the dirty generation pending.
    """
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.001 if attempt < 10 else 0.005 + 0.002 * (attempt % 8))


class BackgroundJsonWriter:
    """Persist one JSON document from a worker thread without touching live data there.

    ``snapshot`` ALWAYS runs on the event loop thread (or calling thread for
    synchronous :meth:`flush` / :meth:`close`) and must return detached plain JSON
    data (:func:`plain_json_copy`). ``serialise`` and :func:`write_json_atomically`
    run inside a worker thread via ``asyncio.to_thread``.

    Monotonic generations (``_requested_gen`` / ``_written_gen``) give all three
    safety properties without holding any lock across ``snapshot()`` or I/O:

    * no torn file: :func:`write_json_atomically` swaps whole documents;
    * no lost dirty state: even if ``spawn`` refuses a task or a write fails,
      ``_requested_gen > _written_gen`` stays intact for the next flush or close;
    * no stale overwrite: :meth:`_write_if_newest` skips any payload whose
      generation is ``<= _written_gen``.
    """

    def __init__(
        self,
        *,
        path: Callable[[], Path],
        snapshot: Callable[[], Any],
        serialise: Callable[[Any], str],
        spawn: Callable[[Any], Any],
        label: str = "json-writer",
    ) -> None:
        self._path = path
        self._snapshot = snapshot
        self._serialise = serialise
        self._spawn = spawn
        self._label = label
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._requested_gen: int = 0
        self._written_gen: int = 0
        self._task: Any = None
        self._closed: bool = False

    @property
    def dirty(self) -> bool:
        """True while a requested or recorded update has not yet been written."""
        return self._requested_gen > self._written_gen

    def _next_requested_gen(self) -> int:
        with self._state_lock:
            self._requested_gen = max(self._requested_gen, self._written_gen) + 1
            return self._requested_gen

    def mark_dirty(self) -> None:
        """Record that the document changed without launching a background task."""
        if self._closed:
            return
        self._next_requested_gen()

    def request(self) -> None:
        """Ask for an asynchronous flush; returns immediately."""
        if self._closed:
            return
        self._next_requested_gen()
        if self._task is not None and not self._task.done():
            return
        task = self._spawn(self._drain())
        if task is not None:
            self._task = task

    async def _drain(self) -> None:
        try:
            while self._requested_gen > self._written_gen and not self._closed:
                target_gen = self._requested_gen
                try:
                    payload = self._snapshot()
                except Exception as exc:
                    logger.warning("[MemoryCompanion] %s 快照失败: %s", self._label, exc)
                    return
                try:
                    await asyncio.to_thread(
                        self._write_if_newest, target_gen, payload
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Keep _requested_gen > _written_gen intact so a later write
                    # or shutdown flush retries without spinning in a tight loop.
                    logger.warning("[MemoryCompanion] %s 保存失败: %s", self._label, exc)
                    return
        finally:
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if current is not None and self._task is current:
                self._task = None

    def _write_if_newest(
        self,
        target_gen: int,
        payload: Any,
        *,
        allow_closed: bool = False,
    ) -> bool:
        with self._write_lock:
            if (self._closed and not allow_closed) or target_gen <= self._written_gen:
                return False
        text = self._serialise(payload)
        with self._write_lock:
            if (self._closed and not allow_closed) or target_gen <= self._written_gen:
                return False
            write_json_atomically(self._path(), text)
            self._written_gen = target_gen
            return True

    def _flush_sync_for_gen(self, target_gen: int, *, allow_closed: bool) -> bool:
        try:
            payload = self._snapshot()
        except Exception as exc:
            logger.warning("[MemoryCompanion] %s 快照失败: %s", self._label, exc)
            return False
        try:
            wrote = self._write_if_newest(
                target_gen, payload, allow_closed=allow_closed
            )
            return wrote or self._written_gen >= target_gen
        except Exception as exc:
            logger.warning("[MemoryCompanion] %s 保存失败: %s", self._label, exc)
            return False

    async def _flush_async_for_gen(
        self, target_gen: int, *, allow_closed: bool
    ) -> bool:
        try:
            payload = self._snapshot()
        except Exception as exc:
            logger.warning("[MemoryCompanion] %s 快照失败: %s", self._label, exc)
            return False
        try:
            wrote = await asyncio.to_thread(
                self._write_if_newest, target_gen, payload, allow_closed=allow_closed
            )
            return wrote or self._written_gen >= target_gen
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[MemoryCompanion] %s 保存失败: %s", self._label, exc)
            return False

    def flush(self) -> bool:
        """Snapshot and publish the newest state synchronously on the calling thread."""
        if self._closed:
            return False
        target_gen = self._next_requested_gen()
        return self._flush_sync_for_gen(target_gen, allow_closed=False)

    async def flush_async(self) -> bool:
        """Snapshot on the event loop thread, then write on a worker thread."""
        if self._closed:
            return False
        target_gen = self._next_requested_gen()
        return await self._flush_async_for_gen(target_gen, allow_closed=False)

    async def flush_if_dirty(self) -> bool:
        """Flush only when an unpersisted generation exists; zero-cost when clean."""
        if self._closed or self._requested_gen <= self._written_gen:
            return False
        target_gen = self._next_requested_gen()
        return await self._flush_async_for_gen(target_gen, allow_closed=False)

    def close(self) -> None:
        """Seal the writer and synchronously flush only if dirty."""
        self._closed = True
        if self._requested_gen <= self._written_gen:
            return
        target_gen = self._next_requested_gen()
        self._flush_sync_for_gen(target_gen, allow_closed=True)

    async def aclose(self) -> None:
        """Seal the writer and asynchronously flush on a worker thread only if dirty."""
        self._closed = True
        if self._requested_gen <= self._written_gen:
            return
        target_gen = self._next_requested_gen()
        await self._flush_async_for_gen(target_gen, allow_closed=True)
