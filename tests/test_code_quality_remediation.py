from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import threading
import types
from unittest.mock import patch

import pytest

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")
    quart_stub.send_file = lambda *_args, **_kwargs: None
    sys.modules["quart"] = quart_stub

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

bootstrap_package()

from core.bridge import MemoryCompanionBridge
from core.chat_import import HistoricalChatImporter
from core.models import EntityRef, MemoryRecord, SessionContext
from core.namespace import NamespaceContext
from core.scoped_store import ScopedStore, ScopedStoreError
from core.service import MemoryCompanionService
from core.store import MemoryStore
from astrbot_plugin_memory_companion.page_api import PluginPageApi


def _service(tmp_path: Path, config: dict | None = None) -> MemoryCompanionService:
    return MemoryCompanionService(
        context=SimpleNamespace(),
        config=config or {},
        plugin_root=tmp_path,
        data_dir=tmp_path / "data",
    )


def _scope(
    kind: str = "private",
    *,
    identity: str = "person-a",
    group: str = "",
    persona: str = "default",
) -> NamespaceContext:
    return NamespaceContext(
        kind=kind,
        identity_id=identity,
        group_id=group,
        assurance="verified",
        profile_status="active",
        policy_version="req041-v1",
        migration_epoch="req041-test-epoch",
        persona_id=persona,
    )


def test_timeline_owner_persona_isolation_covers_dedupe_summary_and_failures(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.initialize()
        try:
            common = {
                "event_type": "user_message",
                "session_id": "shared-session",
                "scope": "private",
                "subject_id": "person-a",
                "object_id": "bot",
                "content": "same content",
                "metadata": {"message_id": "same-message"},
            }
            first = await store.add_timeline_event(
                owner_bot_id="bot-a", persona_id="persona-a", **common
            )
            second = await store.add_timeline_event(
                owner_bot_id="bot-a", persona_id="persona-b", **common
            )
            third = await store.add_timeline_event(
                owner_bot_id="bot-b", persona_id="persona-a", **common
            )
            legacy = await store.add_timeline_event(**common)
            assert len({first, second, third, legacy}) == 4

            rows = await store.recent_timeline(
                session_id="shared-session",
                owner_bot_id="bot-a",
                persona_id="persona-a",
                limit=10,
            )
            assert [row["id"] for row in rows] == [first]
            window = await store.unsummarized_timeline_window(
                session_id="shared-session",
                owner_bot_id="bot-a",
                persona_id="persona-b",
                limit=10,
            )
            assert [row["id"] for row in window["rows"]] == [second]

            marked = await store.mark_timeline_summarized(
                [first, second, third, legacy],
                owner_bot_id="bot-a",
                persona_id="persona-a",
            )
            assert marked == 1
            states = {
                row["id"]: row["summarized_at"]
                for row in store._conn.execute(
                    "SELECT id,summarized_at FROM timeline"
                ).fetchall()
            }
            assert states[first]
            assert not states[second] and not states[third] and not states[legacy]

            for owner, persona, marker in (
                ("bot-a", "persona-a", "a"),
                ("bot-a", "persona-b", "b"),
                ("", "", "legacy"),
            ):
                await store.record_summary_failure(
                    owner_bot_id=owner,
                    persona_id=persona,
                    session_id="shared-session",
                    scope="private",
                    start_timeline_id=first,
                    end_timeline_id=first,
                    error=marker,
                )
            assert (await store.get_summary_failure(
                "shared-session", owner_bot_id="bot-a", persona_id="persona-a"
            ))["last_error"] == "a"
            assert (await store.get_summary_failure(
                "shared-session", owner_bot_id="bot-a", persona_id="persona-b"
            ))["last_error"] == "b"
            assert (await store.get_summary_failure("shared-session"))["last_error"] == "legacy"
        finally:
            store.close()

    asyncio.run(scenario())


def test_fence_invalidates_embedding_and_knowledge_writes_already_queued(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.initialize()
        await store.insert_memory(
            MemoryRecord(id="memory-1", memory_type="manual_memory", content="seed")
        )
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        gate = threading.Event()
        started = threading.Event()

        def occupy_executor() -> None:
            started.set()
            gate.wait(timeout=5)

        blocker = loop.run_in_executor(None, occupy_executor)
        while not started.is_set():
            await asyncio.sleep(0)
        embedding = asyncio.create_task(
            store.upsert_memory_embedding(
                memory_id="memory-1",
                provider_id="provider",
                text_hash="hash",
                vector=[0.1, 0.2],
            )
        )
        knowledge = asyncio.create_task(
            store.upsert_knowledge_node(node_type="topic", label="queued-node")
        )
        for _ in range(100):
            if store._active_tracked_operations == 2:
                break
            await asyncio.sleep(0.001)
        assert store._active_tracked_operations == 2

        generation = store.begin_write_fence()
        gate.set()
        await blocker
        await asyncio.gather(embedding, knowledge)
        await asyncio.to_thread(store.wait_for_writes)

        assert store._conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0] == 0
        assert store._active_tracked_operations == 0
        assert store.resume_writes(generation)
        store.close()

    asyncio.run(scenario())


def test_aclose_fences_before_close_worker_can_queue_behind_writers(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        gate = threading.Event()
        started = threading.Event()

        def occupy_executor() -> None:
            started.set()
            gate.wait(timeout=5)

        blocker = loop.run_in_executor(None, occupy_executor)
        while not started.is_set():
            await asyncio.sleep(0)
        queued = asyncio.create_task(
            service.store.upsert_knowledge_node(node_type="topic", label="late-node")
        )
        for _ in range(100):
            if service.store._active_tracked_operations == 1:
                break
            await asyncio.sleep(0.001)
        closing = asyncio.create_task(service.aclose())
        await asyncio.sleep(0)
        assert service.store._writes_admitted is False
        assert service.store._closing is True
        gate.set()
        await blocker
        assert await queued == ""
        await closing
        assert service.store._closed is True
        assert service.store._active_tracked_operations == 0
        assert not service._background_tasks

    asyncio.run(scenario())


def test_aclose_waits_for_request_path_relationship_writer(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        entered = asyncio.Event()
        release = asyncio.Event()
        context = SessionContext(
            session_id="qq:FriendMessage:person-a",
            scope="private",
            platform="qq",
            user_id="person-a",
            bot_id="bot-a",
        )

        async def late_request_state(_event, _request) -> None:
            entered.set()
            await release.wait()
            service._update_address_evolution(context, "宝贝，晚安")

        service._handle_llm_request_unfenced = late_request_state
        request_task = asyncio.create_task(service.handle_llm_request(object(), object()))
        await entered.wait()
        close_task = asyncio.create_task(service.aclose())
        await asyncio.sleep(0)

        assert service.store._writes_admitted is False
        assert not close_task.done()

        release.set()
        await request_task
        await close_task

        assert service._closed is True
        persisted = service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8")
        await asyncio.sleep(0)
        assert service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8") == persisted

    asyncio.run(scenario())


def test_clear_waits_for_request_path_relationship_state_then_removes_it(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        entered = asyncio.Event()
        release = asyncio.Event()
        context = SessionContext(
            session_id="qq:FriendMessage:person-a",
            scope="private",
            platform="qq",
            user_id="person-a",
            bot_id="bot-a",
        )

        async def late_request_state(_event, _request) -> None:
            entered.set()
            await release.wait()
            service._update_address_evolution(context, "宝贝，晚安")

        service._handle_llm_request_unfenced = late_request_state
        request_task = asyncio.create_task(service.handle_llm_request(object(), object()))
        await entered.wait()
        clear_task = asyncio.create_task(service.clear_all_memory_data())
        await asyncio.sleep(0)
        assert not clear_task.done()
        release.set()
        await request_task
        result = await clear_task

        assert "backup" in result and "deleted" in result
        assert "historical_relationship_observations" in result
        assert "historical_chat_archives" in result
        assert Path(result["backup"]).is_file()
        assert service._relationship_phase_state == {}
        assert json.loads(
            service._RELATIONSHIP_PHASE_FILE.read_text(encoding="utf-8")
        ) == {}
        await service.aclose()

    asyncio.run(scenario())


def test_clear_scoped_memory_preserves_public_validation_errors(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        try:
            with pytest.raises(ValueError, match="user_id is required"):
                await service.clear_scoped_memory(target_type="private")
            assert service.store._writes_admitted is True

            with pytest.raises(ValueError, match="target_type must be"):
                await service.clear_scoped_memory(target_type="unknown")
            assert service.store._writes_admitted is True
        finally:
            await service.aclose()

    asyncio.run(scenario())


def test_scoped_clear_removes_primary_and_scoped_sentinels_from_public_reads(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        companion = object()
        service.context = SimpleNamespace(
            get_all_stars=lambda: [
                SimpleNamespace(
                    star_cls=companion,
                    root_dir_name="astrbot_plugin_private_companion",
                    name="PrivateCompanion",
                    activated=True,
                )
            ]
        )
        bridge = MemoryCompanionBridge(service)
        capability = bridge.register_private_companion(companion)
        assert capability is not None
        assert bridge.bind_namespace_migration_epoch(
            capability,
            operation_id="bind-dual-clear",
            expected_previous_epoch="",
            migration_epoch="req041-test-epoch",
            policy_version="req041-v1",
        )["ok"]
        namespace = _scope().to_dict()

        await service.store.insert_memory(
            MemoryRecord(
                id="primary-private-sentinel",
                memory_type="manual_memory",
                subject=EntityRef(kind="user", id="person-a"),
                object=EntityRef.bot_self(bot_id="bot-a", bot_name="Bot"),
                scope="private",
                session_id="qq:FriendMessage:person-a",
                content="primary sentinel",
                owner_bot_id="bot-a",
            )
        )
        assert bridge.upsert_scoped_record(
            capability,
            namespace,
            record_kind="memory",
            record_id="scoped-private-sentinel",
            revision=1,
            payload={"value": "scoped sentinel"},
            event_id="write-dual-clear",
        )["ok"]

        result = await service.clear_scoped_memory(
            target_type="private", user_id="person-a"
        )
        assert result["state"] == "ready"
        assert result["databases"]["primary"]["ok"] is True
        assert result["databases"]["scoped"]["ok"] is True
        primary_records = await service.store.list_memories(limit=100)
        assert "primary-private-sentinel" not in {item.id for item in primary_records}
        scoped_read = bridge.read_scoped_record(
            capability,
            namespace,
            record_kind="memory",
            record_id="scoped-private-sentinel",
        )
        assert scoped_read["code"] == "not_found"
        await service.aclose()

    asyncio.run(scenario())


def test_bridge_scoped_write_is_fenced_while_clear_is_running(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        companion = object()
        service.context = SimpleNamespace(
            get_all_stars=lambda: [
                SimpleNamespace(
                    star_cls=companion,
                    root_dir_name="astrbot_plugin_private_companion",
                    name="PrivateCompanion",
                    activated=True,
                )
            ]
        )
        bridge = MemoryCompanionBridge(service)
        capability = bridge.register_private_companion(companion)
        assert capability is not None
        assert bridge.bind_namespace_migration_epoch(
            capability,
            operation_id="bind-race-clear",
            expected_previous_epoch="",
            migration_epoch="req041-test-epoch",
            policy_version="req041-v1",
        )["ok"]
        namespace = _scope().to_dict()
        entered = threading.Event()
        release = threading.Event()
        original_clear = service.scoped_store.clear_scoped_records

        def blocked_clear(**kwargs):
            entered.set()
            assert release.wait(timeout=5)
            return original_clear(**kwargs)

        with patch.object(
            service.scoped_store,
            "clear_scoped_records",
            side_effect=blocked_clear,
        ):
            clear_task = asyncio.create_task(
                service.clear_scoped_memory(
                    target_type="private", user_id="person-a"
                )
            )
            assert await asyncio.to_thread(entered.wait, 5)
            denied = bridge.upsert_scoped_record(
                capability,
                namespace,
                record_kind="memory",
                record_id="late-scoped-write",
                revision=1,
                payload={"value": "must not survive"},
                event_id="late-scoped-write",
            )
            assert denied == {
                "ok": False,
                "state": "degraded",
                "code": "scoped_write_fenced",
            }
            release.set()
            assert (await clear_task)["state"] == "ready"

        read = bridge.read_scoped_record(
            capability,
            namespace,
            record_kind="memory",
            record_id="late-scoped-write",
        )
        assert read["code"] == "not_found"
        await service.aclose()

    asyncio.run(scenario())


def test_scoped_only_preview_and_partial_clear_report_each_database(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        assert service.scoped_store is not None
        context = _scope()
        service.scoped_store.upsert(
            context,
            record_kind="memory",
            record_id="scoped-only",
            revision=1,
            payload={"value": "only scoped"},
            event_id="write-scoped-only",
        )
        preview = await service.preview_scoped_memory_clear(
            target_type="private", user_id="person-a"
        )
        assert preview["counts"]["total"] == 1
        assert preview["databases"]["primary"]["counts"]["memories"] == 0
        assert preview["databases"]["scoped"]["counts"]["memory"] == 1

        page = PluginPageApi(SimpleNamespace(service=service))
        page._ok = lambda data=None: {"success": True, **(data or {})}

        async def preview_payload() -> dict:
            return {
                "target_type": "private",
                "user_id": "person-a",
                "preview": True,
            }

        page._json = preview_payload
        page_preview = await page.clear_scope()
        assert page_preview["result"]["counts"]["total"] == 1
        assert page_preview["result"]["databases"]["scoped"]["counts"]["memory"] == 1

        with patch.object(
            service.scoped_store,
            "clear_all_records",
            side_effect=RuntimeError("scoped unavailable"),
        ):
            result = await service.clear_all_memory_data()
        assert result["state"] == "partial"
        assert result["databases"]["primary"]["ok"] is True
        assert result["databases"]["scoped"]["ok"] is False
        assert Path(result["backup"]).is_file()
        assert isinstance(result["deleted"], dict)

        async def fail_primary_clear(**_kwargs):
            raise RuntimeError("primary unavailable")

        with patch.object(
            service.store,
            "clear_scoped_memory",
            side_effect=fail_primary_clear,
        ):
            reverse = await service.clear_scoped_memory(
                target_type="private", user_id="person-a"
            )
        assert reverse["state"] == "partial"
        assert reverse["databases"]["primary"]["ok"] is False
        assert reverse["databases"]["scoped"]["ok"] is True
        assert reverse["backup"] == ""
        assert reverse["deleted"] == {}
        await service.aclose()

    asyncio.run(scenario())


def test_scoped_clear_all_kinds_is_visible_through_bridge_and_private_is_exact(tmp_path: Path) -> None:
    store = ScopedStore(tmp_path / "scoped.db")
    companion = object()
    context_registry = SimpleNamespace(
        get_all_stars=lambda: [
            SimpleNamespace(
                star_cls=companion,
                root_dir_name="astrbot_plugin_private_companion",
                name="PrivateCompanion",
                activated=True,
            )
        ]
    )
    bridge = MemoryCompanionBridge(
        SimpleNamespace(scoped_store=store, context=context_registry)
    )
    capability = bridge.register_private_companion(companion)
    assert capability is not None
    bound = bridge.bind_namespace_migration_epoch(
        capability,
        operation_id="bind",
        expected_previous_epoch="",
        migration_epoch="req041-test-epoch",
        policy_version="req041-v1",
    )
    assert bound["ok"]
    private = _scope().to_dict()
    member = _scope("group_member", group="group-a").to_dict()
    for index, kind in enumerate(("profile_fact", "memory", "rule", "evidence", "summary")):
        result = bridge.upsert_scoped_record(
            capability,
            private,
            record_kind=kind,
            record_id=f"private-{kind}",
            revision=1,
            payload={"value": kind},
            event_id=f"private-write-{index}",
        )
        assert result["ok"], result
    assert bridge.upsert_scoped_record(
        capability,
        member,
        record_kind="memory",
        record_id="member-memory",
        revision=1,
        payload={"value": "keep"},
        event_id="member-write",
    )["ok"]
    with sqlite3.connect(store.path) as connection:
        operation_count = connection.execute(
            "SELECT COUNT(*) FROM scoped_operations"
        ).fetchone()[0]

    result = store.clear_scoped_records(target_type="private", identity_id="person-a")
    assert result["counts"]["total"] == 5
    for kind in ("profile_fact", "memory", "rule", "evidence", "summary"):
        read = bridge.read_scoped_record(
            capability,
            private,
            record_kind=kind,
            record_id=f"private-{kind}",
        )
        assert read["code"] == "not_found"
    member_read = bridge.read_scoped_record(
        capability,
        member,
        record_kind="memory",
        record_id="member-memory",
    )
    assert member_read["record"]["payload"]["value"] == "keep"
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM scoped_operations"
        ).fetchone()[0] == operation_count


@pytest.mark.parametrize(
    ("target", "kwargs", "expected_deleted"),
    (
        (
            "private",
            {"identity_id": "person-a"},
            {"private-a-pa", "private-a-pb"},
        ),
        (
            "group",
            {"group_id": "group-a"},
            {"group-a-shared-pa", "group-a-a-pa", "group-a-b-pa"},
        ),
        (
            "group_member",
            {"group_id": "group-a", "identity_id": "person-a"},
            {"group-a-a-pa"},
        ),
        (
            "persona",
            {"persona_id": "persona-a"},
            {
                "private-a-pa",
                "private-b-pa",
                "group-a-shared-pa",
                "group-a-a-pa",
                "group-a-b-pa",
                "group-b-a-pa",
                "persona-pa",
            },
        ),
    ),
)
def test_scoped_clear_target_matrix(
    tmp_path: Path,
    target: str,
    kwargs: dict[str, str],
    expected_deleted: set[str],
) -> None:
    store = ScopedStore(tmp_path / target / "scoped.db")
    seeds = {
        "private-a-pa": _scope(identity="person-a", persona="persona-a"),
        "private-b-pa": _scope(identity="person-b", persona="persona-a"),
        "private-a-pb": _scope(identity="person-a", persona="persona-b"),
        "group-a-shared-pa": _scope(
            "group_shared", identity="", group="group-a", persona="persona-a"
        ),
        "group-a-a-pa": _scope(
            "group_member", identity="person-a", group="group-a", persona="persona-a"
        ),
        "group-a-b-pa": _scope(
            "group_member", identity="person-b", group="group-a", persona="persona-a"
        ),
        "group-b-a-pa": _scope(
            "group_member", identity="person-a", group="group-b", persona="persona-a"
        ),
        "persona-pa": _scope("persona_global", identity="", persona="persona-a"),
        "persona-pb": _scope("persona_global", identity="", persona="persona-b"),
    }
    for index, (record_id, context) in enumerate(seeds.items()):
        record_kind = "rule" if context.kind == "persona_global" else "memory"
        store.upsert(
            context,
            record_kind=record_kind,
            record_id=record_id,
            revision=1,
            payload={"value": record_id},
            event_id=f"seed-{index}",
        )

    result = store.clear_scoped_records(target_type=target, **kwargs)
    assert result["counts"]["total"] == len(expected_deleted)
    for record_id, context in seeds.items():
        record_kind = "rule" if context.kind == "persona_global" else "memory"
        record = store.read(context, record_kind=record_kind, record_id=record_id)
        assert (record is None) is (record_id in expected_deleted)


def test_runtime_config_api_applies_scalars_and_reports_semaphore_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        raw = {
            "memory_capture": {"capture_min_chars": 2},
            "memory_summary": {
                "max_input_chars": 6000,
                "max_summary_chars": 1200,
                "provider_timeout_seconds": 180,
                "max_concurrent_calls": 1,
            },
        }
        service = _service(tmp_path, raw)
        plugin = SimpleNamespace(service=service)
        page = PluginPageApi(plugin)
        schema = {
            "memory_capture": {
                "items": {"capture_min_chars": {"type": "int", "default": 2}}
            },
            "memory_summary": {
                "items": {
                    "max_input_chars": {"type": "int", "default": 6000},
                    "max_summary_chars": {"type": "int", "default": 1200},
                    "provider_timeout_seconds": {"type": "int", "default": 180},
                    "max_concurrent_calls": {"type": "int", "default": 1},
                }
            },
        }
        page._load_config_schema = lambda: schema
        page._write_plugin_config = lambda _raw: None
        page._ok = lambda data=None: {"success": True, **(data or {})}

        async def capture_payload() -> dict:
            return {
                "module": "memory_capture",
                "values": {"capture_min_chars": 7},
            }

        page._json = capture_payload
        capture_result = await page.config_module_update()
        assert capture_result["applied_now"] == ["memory_capture.capture_min_chars"]
        assert capture_result["restart_required"] == []
        assert service.classifier.capture_min_chars == 7

        old_semaphore = service._summary_call_semaphore

        async def summary_payload() -> dict:
            return {
                "module": "memory_summary",
                "values": {
                    "max_input_chars": 7200,
                    "max_summary_chars": 1500,
                    "provider_timeout_seconds": 75,
                    "max_concurrent_calls": 3,
                },
            }

        page._json = summary_payload
        summary_result = await page.config_module_update()
        assert summary_result["applied_now"] == [
            "memory_summary.max_input_chars",
            "memory_summary.max_summary_chars",
            "memory_summary.provider_timeout_seconds",
        ]
        assert summary_result["restart_required"] == [
            "memory_summary.max_concurrent_calls"
        ]
        assert service.summarizer.max_input_chars == 7200
        assert service.summarizer.max_summary_chars == 1500
        assert service.summarizer.provider_timeout_seconds == 75.0
        assert service.summary_provider_timeout_seconds == 75
        assert service.summary_timeout_warning is True
        assert service._summary_call_semaphore is old_semaphore
        await service.aclose()

    asyncio.run(scenario())


def test_capability_activation_page_rebind_and_deactivation_are_immediate() -> None:
    service = SimpleNamespace()
    plugin = SimpleNamespace(service=service)
    bridge = MemoryCompanionBridge(service, active=False, instance_generation=1)
    plugin.memory_companion = bridge
    page = PluginPageApi(plugin)

    assert bridge.probe_capability_snapshot()["error_code"] == "bridge_inactive"
    assert page._emotion_page_admin_capability is None
    bridge._activate()
    assert bridge.probe_capability_snapshot()["state"] == "available"
    assert page.rebind_runtime_capabilities() is True
    issued = page._emotion_page_admin_capability
    assert issued is not None

    bridge.deactivate()
    inactive = bridge.probe_capability_snapshot()
    assert inactive["available"] is False
    assert inactive["error_code"] == "bridge_inactive"
    assert bridge._is_valid_emotion_page_admin_capability(issued) is False
    assert page.rebind_runtime_capabilities() is False


def test_historical_import_uses_service_namespace_and_cannot_mark_foreign_row(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.initialize()

        class ImportService:
            _timeline_namespace = MemoryCompanionService._timeline_namespace
            _timeline_namespace_kwargs = MemoryCompanionService._timeline_namespace_kwargs

            def __init__(self) -> None:
                self.data_dir = tmp_path / "data"
                self.store = store

            @staticmethod
            def _spawn_background(coro, *, label):
                coro.close()
                return None

        importer = HistoricalChatImporter(ImportService())
        preview = importer.stage_upload(
            filename="chat.txt",
            content=(
                "用户: 2026-01-01 10:00:00\n你好\n\n"
                "Bot: 2026-01-01 10:00:05\n你好呀\n"
            ).encode("utf-8"),
        )
        started = await importer.start_import(
            {
                "upload_id": preview["upload_id"],
                "speaker_map": {
                    "用户": {
                        "role": "user",
                        "entity_id": "person-a",
                        "display_name": "用户",
                    },
                    "Bot": {
                        "role": "bot",
                        "entity_id": "bot-a",
                        "display_name": "Bot",
                    },
                },
                "platform": "qq",
                "user_id": "person-a",
                "user_name": "用户",
                "bot_id": "bot-a",
                "bot_name": "Bot",
                "persona_id": "persona-import",
            }
        )
        batch = await store.get_chat_import_batch(started["batch"]["id"])
        assert batch is not None
        assert batch["options"]["_timeline_namespace"] == {
            "owner_bot_id": "bot-a",
            "persona_id": "persona-import",
        }
        legacy_batch = dict(batch)
        legacy_batch["options"] = {
            key: value
            for key, value in batch["options"].items()
            if key != "_timeline_namespace"
        }
        assert importer._timeline_namespace_kwargs(legacy_batch) == {
            "owner_bot_id": "",
            "persona_id": "",
        }
        rows = store._conn.execute(
            "SELECT id,owner_bot_id,persona_id,summarized_at FROM timeline "
            "WHERE import_batch_id=? ORDER BY source_sequence",
            (batch["id"],),
        ).fetchall()
        assert len(rows) == 2
        assert {(row["owner_bot_id"], row["persona_id"]) for row in rows} == {
            ("bot-a", "persona-import")
        }
        foreign_id = await store.add_timeline_event(
            owner_bot_id="bot-a",
            persona_id="persona-other",
            event_type="user_message",
            session_id=batch["session_id"],
            scope="private",
            subject_id="person-a",
            object_id="bot-a",
            content="foreign",
            metadata={"message_id": "foreign-message"},
        )
        segment = (await store.chat_import_segments(batch["id"]))[0]
        segment["message_ids"] = [*segment["message_ids"], foreign_id]

        async def provider_result(*_args, **_kwargs):
            return {
                "segments": [
                    {
                        "segment_id": segment["id"],
                        "worth_long_term": False,
                        "summary": "",
                        "canonical_summary": "",
                        "archive_note": "archived",
                        "topics": [],
                        "important_events": [],
                        "stable_facts": [],
                        "relationship_observations": [],
                    }
                ]
            }

        importer._call_json_provider = provider_result
        await importer._process_package(batch, [segment])
        summarized = {
            row["id"]: row["summarized_at"]
            for row in store._conn.execute(
                "SELECT id,summarized_at FROM timeline"
            ).fetchall()
        }
        assert all(summarized[row["id"]] for row in rows)
        assert summarized[foreign_id] == ""
        store.close()

    asyncio.run(scenario())


def test_scoped_identity_rejects_empty_legacy_and_wrong_installation(tmp_path: Path) -> None:
    empty_path = tmp_path / "empty" / "scoped.db"
    ScopedStore(empty_path)
    with patch.object(ScopedStore, "_write_identity_marker") as marker_writer:
        try:
            ScopedStore(empty_path, installation_id="a" * 32)
        except ScopedStoreError as exc:
            assert str(exc) == "scoped_legacy_database_empty"
        else:
            raise AssertionError("an empty legacy scoped database must not be adopted")
    marker_writer.assert_not_called()

    bound_path = tmp_path / "bound" / "scoped.db"
    first = ScopedStore(bound_path, installation_id="b" * 32)
    assert first.identity_marker_path.is_file()
    with sqlite3.connect(bound_path) as connection:
        row = connection.execute(
            "SELECT installation_id,database_name,schema_version "
            "FROM scoped_store_identity WHERE singleton=1"
        ).fetchone()
    assert row == ("b" * 32, "scoped.db", ScopedStore.IDENTITY_SCHEMA_VERSION)
    try:
        ScopedStore(bound_path, installation_id="c" * 32)
    except ScopedStoreError as exc:
        assert str(exc) == "scoped_installation_identity_mismatch"
    else:
        raise AssertionError("a different installation identity must fail closed")


def test_scoped_identity_adopts_valid_legacy_and_rejects_torn_or_corrupt_pairs(
    tmp_path: Path,
) -> None:
    adoption_path = tmp_path / "adoption" / "scoped.db"
    legacy = ScopedStore(adoption_path)
    legacy.upsert(
        _scope(),
        record_kind="memory",
        record_id="adopted-record",
        revision=1,
        payload={"value": "preserved"},
        event_id="legacy-adoption-write",
    )
    adopted = ScopedStore(adoption_path, installation_id="1" * 32)
    assert adopted.identity_marker_path.is_file()
    assert Path(adopted.last_identity_backup_path).is_file()
    assert adopted.read(
        _scope(), record_kind="memory", record_id="adopted-record"
    )["payload"]["value"] == "preserved"

    missing_path = tmp_path / "missing" / "scoped.db"
    established = ScopedStore(missing_path, installation_id="2" * 32)
    marker = established.identity_marker_path
    missing_path.unlink()
    with pytest.raises(
        ScopedStoreError,
        match="scoped_database_missing_after_identity_established",
    ):
        ScopedStore(missing_path, installation_id="2" * 32)
    assert not missing_path.exists()
    assert marker.is_file()

    corrupt_path = tmp_path / "corrupt" / "scoped.db"
    corrupt = ScopedStore(corrupt_path, installation_id="3" * 32)
    corrupt.identity_marker_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ScopedStoreError, match="scoped_identity_marker_corrupt"):
        ScopedStore(corrupt_path, installation_id="3" * 32)
    assert corrupt_path.is_file()

    unrelated_path = tmp_path / "unrelated" / "scoped.db"
    unrelated_path.parent.mkdir(parents=True)
    with sqlite3.connect(unrelated_path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    with pytest.raises(ScopedStoreError, match="scoped_legacy_schema_unrecognized"):
        ScopedStore(unrelated_path, installation_id="4" * 32)
    assert unrelated_path.is_file()
    assert not unrelated_path.with_name(ScopedStore.IDENTITY_MARKER_NAME).exists()


def test_scoped_identity_marker_fsync_failure_restores_legacy_pair(tmp_path: Path) -> None:
    path = tmp_path / "scoped.db"
    legacy = ScopedStore(path)
    legacy.upsert(
        _scope(),
        record_kind="memory",
        record_id="legacy-record",
        revision=1,
        payload={"value": "preserve"},
        event_id="legacy-write",
    )
    real_fsync = __import__("os").fsync
    calls = 0

    def fail_marker_parent_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected parent fsync failure")
        real_fsync(fd)

    with patch("core.scoped_store.os.fsync", side_effect=fail_marker_parent_fsync):
        try:
            ScopedStore(path, installation_id="d" * 32)
        except OSError as exc:
            assert "injected parent fsync failure" in str(exc)
        else:
            raise AssertionError("marker fsync failure must escape construction")

    marker = path.with_name(ScopedStore.IDENTITY_MARKER_NAME)
    assert not marker.exists()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM scoped_store_identity"
        ).fetchone()[0] == 0
    reopened = ScopedStore(path)
    assert reopened.read(
        _scope(), record_kind="memory", record_id="legacy-record"
    )["payload"]["value"] == "preserve"
    assert list(tmp_path.glob("scoped.backup.*.before_identity_adoption.db"))


def test_scoped_identity_new_database_marker_failure_removes_all_pair_artifacts(tmp_path: Path) -> None:
    path = tmp_path / "new" / "scoped.db"
    with patch.object(
        ScopedStore,
        "_write_identity_marker",
        side_effect=OSError("injected marker failure"),
    ):
        try:
            ScopedStore(path, installation_id="e" * 32)
        except OSError as exc:
            assert "injected marker failure" in str(exc)
        else:
            raise AssertionError("marker failure must escape construction")
    assert not path.exists()
    assert not path.with_name(ScopedStore.IDENTITY_MARKER_NAME).exists()
    assert not Path(str(path) + "-wal").exists()
    assert not Path(str(path) + "-shm").exists()
