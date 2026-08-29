from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from core.bridge import MemoryCompanionBridge
from core.models import MemoryRecord
from core.service import MemoryCompanionService
from core.store import MemoryStore


def run(coro):
    return asyncio.run(coro)


def make_service(tmp_path: Path):
    service = object.__new__(MemoryCompanionService)
    service.store = MemoryStore(tmp_path / "memory.db")
    service.store.initialize()
    service._schedule_memory_embedding = lambda *args, **kwargs: None
    return service


def envelope(memory_type: str, key: str, *, date: str = "2026-07-30", window: str = "afternoon"):
    return {
        "memory_type": memory_type,
        "date": date,
        "window": window,
        "occurred_at": f"{date}T15:00:00+08:00",
        "source_refs": [f"companion:c4:{key}"],
        "idempotency_key": f"c4:{key}",
        "payload": {"summary": "private raw payload must stay hidden", "topic": key},
    }


def test_service_profiles_partition_domains_and_hide_raw_fields(tmp_path):
    service = make_service(tmp_path)
    try:
        current = run(service.record_bot_personal_archive(envelope("bot_schedule_plan", "current")))
        old_window = run(service.record_bot_personal_archive(envelope("bot_schedule_plan", "old-window", window="morning")))
        old_date = run(service.record_bot_personal_archive(envelope("bot_schedule_plan", "old-date", date="2026-07-29")))
        creative = run(service.record_bot_personal_archive(envelope("bot_creative_work", "creative")))
        subjective = run(service.record_bot_personal_archive(envelope("bot_subjective_memory", "subjective")))

        run(service.store.insert_memory(MemoryRecord(
            id="user-leak",
            memory_type="bot_creative_work",
            scope="private",
            session_id="bot_personal",
            visibility="bot_self",
            content="raw user content",
            metadata={"memory_domain": "user_memory", "bot_personal": True},
        )))
        run(service.store.insert_memory(MemoryRecord(
            id="group-leak",
            memory_type="bot_creative_work",
            scope="group",
            session_id="bot_personal",
            visibility="group",
            content="raw group content",
            metadata={"memory_domain": "bot_self_schedule", "bot_personal": True},
        )))

        current_profile = run(service.read_bot_profile(
            "bot_schedule_current",
            current_date="2026-07-30",
            current_window="afternoon",
        ))
        history_profile = run(service.read_bot_profile(
            "bot_schedule_history",
            current_date="2026-07-30",
            current_window="afternoon",
        ))
        creative_profile = run(service.read_bot_profile("bot_creative", query="creative"))
        subjective_profile = run(service.read_bot_profile("bot_subjective"))
        locked_denied = run(service.read_bot_profile("locked_frame_personal"))
        locked_allowed = run(service.read_bot_profile("locked_frame_personal", authorized=True))
        unsafe_query = run(service.read_bot_profile("bot_creative", query="C:\\private\\secret.txt"))

        assert [item["record_id"] for item in current_profile["items"]] == [current["record_id"]]
        assert {item["record_id"] for item in history_profile["items"]} == {old_window["record_id"], old_date["record_id"]}
        assert [item["record_id"] for item in creative_profile["items"]] == [creative["record_id"]]
        assert [item["record_id"] for item in subjective_profile["items"]] == [subjective["record_id"]]
        assert locked_denied["state"] == "forbidden" and locked_denied["items"] == []
        assert {item["record_id"] for item in locked_allowed["items"]} == {
            current["record_id"], old_window["record_id"], old_date["record_id"],
            creative["record_id"], subjective["record_id"],
        }
        assert unsafe_query["items"] == []
        assert "unsafe_query_rejected" in unsafe_query["warnings"]
        for result in (current_profile, history_profile, creative_profile, subjective_profile, locked_allowed):
            for item in result["items"]:
                assert "payload" not in item and "content" not in item and "evidence" not in item
                assert "private raw payload" not in str(item)
        assert "user-leak" not in str(locked_allowed)
        assert "group-leak" not in str(locked_allowed)
    finally:
        service.store.close()


def test_bridge_profile_and_capability_compatibility(tmp_path):
    service = make_service(tmp_path)
    try:
        run(service.record_bot_personal_archive(envelope("bot_creative_work", "bridge")))
        bridge = MemoryCompanionBridge(service)
        snapshot = bridge.probe_capability_snapshot()
        legacy = bridge.probe_bot_personal_memory_capabilities()
        profile = run(bridge.read_bot_profile("bot_creative", query="bridge"))
        missing = run(MemoryCompanionBridge(object()).read_bot_profile("bot_creative"))

        assert snapshot["state"] == "available"
        assert snapshot["capability_state"] == "available"
        assert snapshot["profiles"] == [
            "bot_schedule_current", "bot_schedule_history", "bot_creative",
            "bot_subjective", "locked_frame_personal",
        ]
        assert legacy["state"] == "ready"
        assert legacy["capability_state"] == "available"
        assert profile["ok"] and profile["read_only"] is True
        assert len(profile["items"]) == 1
        assert missing["state"] == "degraded"
        assert missing["error_code"] == "bridge_method_unavailable"
    finally:
        service.store.close()


def test_bridge_locked_profile_ignores_caller_boolean_and_requires_capability(tmp_path):
    service = make_service(tmp_path)
    try:
        class CompanionProducer:
            @staticmethod
            def _memory_companion_bridge_bot_id():
                return "bot-a"

            @staticmethod
            def _memory_companion_archive_persona_id():
                return "persona-a"

        companion = CompanionProducer()
        namespaced = envelope("bot_creative_work", "locked")
        namespaced.update(
            canonical_schema_version=3,
            owner_bot_id="bot-a",
            persona_id="persona-a",
        )
        run(service.record_bot_personal_archive(namespaced))
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
        denied = run(bridge.read_bot_profile("locked_frame_personal", authorized=True))
        capability = bridge.register_bot_personal_producer(companion)
        allowed = run(
            bridge.read_bot_profile(
                "locked_frame_personal",
                authorized=False,
                producer_capability=capability,
            )
        )
        assert denied["state"] == "forbidden"
        assert denied["items"] == []
        assert allowed["ok"] is True
        assert allowed["items"]
    finally:
        service.store.close()


def test_capability_namespace_is_filtered_before_limit_and_legacy_stays_separate(tmp_path):
    service = make_service(tmp_path)
    try:
        class CompanionProducer:
            @staticmethod
            def _memory_companion_bridge_bot_id():
                return "bot-target"

            @staticmethod
            def _memory_companion_archive_persona_id():
                return "persona-target"

        def namespaced(key: str, bot: str, persona: str):
            value = envelope("bot_creative_work", key)
            value.update(
                canonical_schema_version=3,
                owner_bot_id=bot,
                persona_id=persona,
            )
            return value

        target = run(service.record_bot_personal_archive(
            namespaced("target", "bot-target", "persona-target")
        ))
        other_persona = run(service.record_bot_personal_archive(
            namespaced("other-persona", "bot-target", "persona-other")
        ))
        foreign_ids = set()
        for index in range(12):
            result = run(service.record_bot_personal_archive(
                namespaced(f"foreign-{index}", f"bot-foreign-{index}", "persona-target")
            ))
            foreign_ids.add(result["record_id"])
        legacy = run(service.record_bot_personal_archive(
            envelope("bot_creative_work", "legacy-only")
        ))

        producer = CompanionProducer()
        service.context = SimpleNamespace(
            get_all_stars=lambda: [
                SimpleNamespace(
                    star_cls=producer,
                    root_dir_name="astrbot_plugin_private_companion",
                    name="PrivateCompanion",
                    activated=True,
                )
            ]
        )
        bridge = MemoryCompanionBridge(service)
        capability = bridge.register_bot_personal_producer(producer)
        exact = run(bridge.read_bot_profile(
            "bot_creative", limit=1, producer_capability=capability
        ))
        legacy_read = run(bridge.read_bot_profile("bot_creative", limit=20))
        fake = run(bridge.read_bot_profile(
            "bot_creative",
            limit=20,
            authorized=True,
            producer_capability=object(),
        ))

        assert [item["record_id"] for item in exact["items"]] == [target["record_id"]]
        assert other_persona["record_id"] not in str(exact)
        assert foreign_ids.isdisjoint({item["record_id"] for item in exact["items"]})
        assert [item["record_id"] for item in legacy_read["items"]] == [legacy["record_id"]]
        assert fake["state"] == "forbidden"
        assert fake["items"] == []
    finally:
        service.store.close()
