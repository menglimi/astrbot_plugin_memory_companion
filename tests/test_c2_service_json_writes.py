"""C2（服务层）：Token 统计与关系阶段状态的落盘契约。

``test_c2_json_persistence_off_loop.py`` 验证写入原语本身；这里钉住 service 的真实
接线，并且刻意只依赖修复前后都存在的公开行为（是否在调用线程上同步落盘、
落盘结果是否完整、破坏性操作是否已持久化），这样同一份用例放回未修复代码
也会失败，而不是因为缺少新模块而收集失败。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core import service as service_module
from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


def big_usage_document(entries: int = 1800) -> dict:
    return {
        "totals": {"calls": entries},
        "by_hour": {
            f"2026-09-{index % 28 + 1:02d}T{index % 24:02d}:00": {
                "calls": index,
                "total_tokens": index * 3,
                "reported_tokens": index * 3,
                "estimated_tokens": 0,
                "elapsed_ms": index,
            }
            for index in range(entries)
        },
        "recent": [{"ts": index, "task": "memory_summary"} for index in range(240)],
        "updated_at": "2026-11-18 00:00:00",
    }


def relationship_document(entries: int = 188) -> dict:
    return {
        f"key-{index}": {
            "phase": "close",
            "momentum": 0.1,
            "touch_count": index,
            "updated_at": "2026-11-18T00:00:00+00:00",
        }
        for index in range(entries)
    }


def relationship_context(index: int = 0) -> SessionContext:
    return SessionContext(
        session_id=f"qq:FriendMessage:u{index}",
        scope="private",
        platform="qq",
        user_id=f"u{index}",
        bot_id="b1",
        message_id=f"turn-{index}",
    )


@pytest.fixture
def service(tmp_path: Path):
    value = MemoryCompanionService(
        context=None,
        plugin_root=ROOT,
        data_dir=tmp_path,
        config={"retrieval": {"mode": "basic", "embedding_enabled": False}},
    )
    yield value
    value.close()


def test_relationship_state_save_still_writes_a_complete_document(service) -> None:
    """Durability is preserved: the full document must land as valid JSON."""
    service._relationship_phase_state = relationship_document()
    service._save_relationship_phase_state()
    service._relationship_phase_writer.flush()

    saved = json.loads(service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8"))
    assert len(saved) == 188
    assert saved["key-7"] == {
        "phase": "close",
        "momentum": 0.1,
        "touch_count": 7,
        "updated_at": "2026-11-18T00:00:00+00:00",
    }


def test_token_usage_save_still_writes_a_complete_document(service) -> None:
    service._token_usage = big_usage_document(120)
    service._save_token_usage(force=True)

    saved = json.loads(service.token_usage_path.read_text(encoding="utf-8"))
    assert saved["totals"] == {"calls": 120}
    assert len(saved["by_hour"]) == 120


async def test_relationship_state_save_does_not_write_on_the_calling_thread(service) -> None:
    """The 188-key document must not be serialised inside the event loop turn."""
    service._relationship_phase_state = relationship_document()

    service._save_relationship_phase_state()

    assert not service._RELATIONSHIP_PHASE_FILE.exists(), (
        "关系阶段状态在调用线程上同步落盘了"
    )
    await service.flush_relationship_phase_state()
    assert len(json.loads(service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8"))) == 188


async def test_token_usage_save_does_not_write_on_the_calling_thread(service) -> None:
    """Recording a provider call happens in a retrieval ``finally`` on the loop."""
    service._token_usage = big_usage_document()
    service._token_usage_last_save_at = 0.0

    service._record_token_usage(
        task="memory_summary", provider_id="p", prompt="hi", completion="ok"
    )

    assert not service.token_usage_path.exists(), "Token 统计在调用线程上同步落盘了"
    assert service._token_usage["totals"]["calls"] == 1801
    await service._token_usage_writer.flush_async()
    assert json.loads(service.token_usage_path.read_text(encoding="utf-8"))["totals"]["calls"] == 1801


async def test_token_usage_serialisation_runs_off_the_event_loop(service) -> None:
    """``json.dumps`` of a 1.4 MiB document must not run on the loop thread."""
    service._token_usage = big_usage_document()
    service._token_usage_last_save_at = 0.0

    loop_thread = threading.get_ident()
    serialise_threads: list[int] = []
    real_dumps = service_module.json.dumps

    def recording_dumps(*args, **kwargs):
        serialise_threads.append(threading.get_ident())
        return real_dumps(*args, **kwargs)

    service_module.json.dumps = recording_dumps
    try:
        service._record_token_usage(
            task="memory_summary", provider_id="p", prompt="hi", completion="ok"
        )
        await service._token_usage_writer.flush_async()
    finally:
        service_module.json.dumps = real_dumps

    assert serialise_threads, "没有任何序列化发生"
    assert all(ident != loop_thread for ident in serialise_threads), (
        "Token 统计仍在事件循环线程上序列化"
    )


async def test_off_loop_save_keeps_the_event_loop_schedulable(service) -> None:
    """A large document must not stall other sessions (the C2 defect)."""
    service._token_usage = big_usage_document(2400)
    service._token_usage_last_save_at = 0.0
    ticks: list[float] = []

    async def heartbeat() -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            ticks.append(now - last)
            last = now

    pulse = asyncio.create_task(heartbeat())
    try:
        for _ in range(6):
            service._token_usage_last_save_at = 0.0
            service._record_token_usage(task="memory_summary", provider_id="p", prompt="x")
            await asyncio.sleep(0.01)
        await service._token_usage_writer.flush_async()
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)

    assert ticks, "写入期间事件循环一次都没有被调度"
    assert max(ticks) < 0.10, f"事件循环被序列化拖慢到 {max(ticks):.3f}s"


async def test_clear_all_memory_data_is_durable_before_it_returns(service, monkeypatch) -> None:
    """A destructive reset must not leave an older snapshot queued behind it."""
    service._cancel_background_tasks_for_clear = AsyncMock()
    service.store.clear_all_memory_data = AsyncMock(return_value={})
    service.store.clear_acl_projection_sync = lambda: None
    service.chat_importer.clear_relationship_observations = AsyncMock(return_value={})
    service.chat_importer.clear_archives = lambda: {}
    service.store.invalidate_registered_caches = lambda **kwargs: {}

    service._relationship_phase_state = {"stale": {"phase": "close"}}
    await service.clear_all_memory_data()

    assert json.loads(service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8")) == {}


async def test_scoped_clear_publishes_inline(service) -> None:
    ctx = relationship_context(3)
    service._get_relationship_phase(ctx)["phase"] = "close"
    await service.flush_relationship_phase_state()
    assert service._phase_key(ctx) in json.loads(
        service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8")
    )

    await service.store.clear_scoped_memory(target_type="private", user_id="u3")
    service._clear_scoped_runtime_state(target_type="private", group_id="", user_id="u3")

    saved = json.loads(service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8"))
    assert service._phase_key(ctx) not in saved


def test_close_flushes_pending_documents(service) -> None:
    service._token_usage = {"totals": {"calls": 7}}
    # Inside 30s throttle interval: mark dirty without immediate write; close() flushes it.
    service._token_usage_last_save_at = time.time()
    service._save_token_usage()
    service._relationship_phase_state = {"k": {"phase": "close"}}
    service._save_relationship_phase_state()

    assert not service.token_usage_path.exists()
    service.close()

    assert json.loads(service.token_usage_path.read_text(encoding="utf-8"))["totals"]["calls"] == 7
    assert json.loads(service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8")) == {
        "k": {"phase": "close"}
    }


def test_close_does_not_instantiate_or_write_clean_writers(tmp_path: Path) -> None:
    svc = MemoryCompanionService(
        context=None,
        plugin_root=ROOT,
        data_dir=tmp_path,
        config={"retrieval": {"mode": "basic", "embedding_enabled": False}},
    )
    svc.close()

    assert "_token_usage_writer_instance" not in svc.__dict__
    assert "_relationship_phase_writer_instance" not in svc.__dict__
    assert not svc.token_usage_path.exists()
    assert not svc._RELATIONSHIP_PHASE_FILE.exists()
