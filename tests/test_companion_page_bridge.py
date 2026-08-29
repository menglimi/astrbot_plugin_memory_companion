# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


ROOT = bootstrap_package()

if "quart" not in sys.modules:
    quart_stub = types.ModuleType("quart")
    quart_stub.jsonify = lambda payload=None, **kwargs: payload or kwargs
    quart_stub.request = SimpleNamespace(args={}, method="GET")

    async def _send_file(value: Any, **_kwargs: Any) -> Any:
        return value

    quart_stub.send_file = _send_file
    sys.modules["quart"] = quart_stub

import astrbot_plugin_memory_companion.companion_page_bridge as bridge_module
import astrbot_plugin_memory_companion.page_api as page_api_module
from astrbot_plugin_memory_companion.companion_page_bridge import (
    COMPANION_MODULE_NAMES,
    COMPANION_PLUGIN_ID,
    CompanionPageBridge,
    CompanionPageBridgeError,
    CompanionPagePhoto,
    CompanionPageSnapshot,
    MEMORY_PAGE_API_FAMILY,
    MEMORY_PAGE_API_VERSION,
    MEMORY_PAGE_PHOTO_VERSION,
    MEMORY_PAGE_REQUIRED_CAPABILITIES,
    MEMORY_PAGE_SNAPSHOT_VERSION,
    MEMORY_PAGE_SUPPORTED_TASK_VERSIONS,
    MEMORY_PLUGIN_ID,
    seal_memory_page_snapshot,
    validate_memory_page_descriptor,
    validate_memory_page_photo,
    validate_memory_page_snapshot,
)
from astrbot_plugin_memory_companion.page_api import PluginPageApi


PNG = b"\x89PNG\r\n\x1a\ncompanion-page-photo"


@pytest.fixture(autouse=True)
def _reset_process_formal_seen() -> Any:
    runtime = bridge_module._COMPANION_PAGE_RUNTIME
    with runtime.lock:
        runtime.formal_seen = False
    yield
    with runtime.lock:
        runtime.formal_seen = False


def _descriptor(generation: str, **changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "plugin_id": COMPANION_PLUGIN_ID,
        "instance_generation": generation,
        "api_family": MEMORY_PAGE_API_FAMILY,
        "api_version": MEMORY_PAGE_API_VERSION,
        "supported_task_versions": list(MEMORY_PAGE_SUPPORTED_TASK_VERSIONS),
        "capabilities": sorted(MEMORY_PAGE_REQUIRED_CAPABILITIES),
        "lifecycle_state": "ready",
        "degraded_reasons": [],
    }
    value.update(changes)
    return value


def _snapshot(
    generation: str,
    *,
    selected_date: str = "2026-08-26",
    photos: list[dict[str, Any]] | None = None,
    plan_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "version": MEMORY_PAGE_SNAPSHOT_VERSION,
        "source_plugin_id": COMPANION_PLUGIN_ID,
        "instance_generation": generation,
        "selected_date": selected_date,
        "available_dates": ["2026-08-26", "2026-08-25"],
        "features": {
            "daily_plan_enabled": True,
            "detail_enhancement_enabled": True,
        },
        "coordination": {
            "available": True,
            "state": "ready",
            "reason_code": "",
        },
        "day": {
            "date": selected_date,
            "bot_name": "小雪",
            "plan": {
                "date": selected_date,
                "source": "live",
                "items": plan_items
                if plan_items is not None
                else [
                    {
                        "index": 0,
                        "time": "08:00",
                        "activity": "早餐",
                        "mood": "平静",
                        "message_seed": "早安",
                    }
                ],
            },
            "current_item": {
                "index": 0,
                "time": "08:00",
                "activity": "早餐",
                "mood": "平静",
                "message_seed": "早安",
            },
            "daily_state": {
                "date": selected_date,
                "energy": 80,
                "mood_bias": "平静",
                "sleep": "充足",
                "weather": "晴",
                "note": "",
            },
            "details": [
                {
                    "id": f"detail_{'D' * 22}",
                    "index": 0,
                    "status": "ready",
                    "time": "08:00",
                    "summary": "做了早餐",
                    "today_events": ["烤面包"],
                    "proactive_events": [],
                    "state_variables": [],
                }
            ],
            "photos": photos or [],
            "diaries": [
                {
                    "date": selected_date,
                    "summary": "安静的一天",
                    "body": "今天过得很安静。",
                    "share_seed": "晚安",
                    "tags": ["日常"],
                    "today_events": ["吃早餐"],
                    "proactive_events": [],
                    "long_term_events": [],
                }
            ],
        },
    }
    return seal_memory_page_snapshot(payload)


def _reseal_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    unsigned = copy.deepcopy(value)
    unsigned.pop("snapshot_id", None)
    unsigned.pop("snapshot_sha256", None)
    return seal_memory_page_snapshot(unsigned)


def _photo_result(generation: str, photo_ref: str, content: bytes = PNG) -> dict[str, Any]:
    return {
        "version": MEMORY_PAGE_PHOTO_VERSION,
        "source_plugin_id": COMPANION_PLUGIN_ID,
        "instance_generation": generation,
        "photo_ref": photo_ref,
        "mime_type": "image/png",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


class _FormalAPI:
    def __init__(
        self,
        generation: str,
        *,
        snapshot: dict[str, Any] | None = None,
        photo: dict[str, Any] | None = None,
    ) -> None:
        self.generation = generation
        self.snapshot = snapshot or _snapshot(generation)
        self.photo = photo
        self.capability_calls = 0
        self.snapshot_calls = 0
        self.photo_calls = 0
        self.on_export = None
        self.on_photo = None

    def memory_page_capabilities(self) -> dict[str, Any]:
        self.capability_calls += 1
        return _descriptor(self.generation)

    async def export_memory_page_snapshot(
        self,
        *,
        target_plugin_id: str,
        selected_date: str = "",
    ) -> dict[str, Any]:
        assert target_plugin_id == MEMORY_PLUGIN_ID
        self.snapshot_calls += 1
        if callable(self.on_export):
            self.on_export()
        return copy.deepcopy(self.snapshot)

    async def read_memory_page_photo(
        self,
        *,
        target_plugin_id: str,
        photo_ref: str,
    ) -> dict[str, Any]:
        assert target_plugin_id == MEMORY_PLUGIN_ID
        self.photo_calls += 1
        if callable(self.on_photo):
            self.on_photo()
        if self.photo is None:
            raise AssertionError("unexpected photo read")
        return copy.deepcopy(self.photo)


def _install_api(monkeypatch: pytest.MonkeyPatch, holder: dict[str, Any]) -> None:
    for name in COMPANION_MODULE_NAMES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = types.ModuleType(COMPANION_MODULE_NAMES[-1])
    module.get_private_companion_api = lambda: holder.get("api")
    monkeypatch.setitem(sys.modules, COMPANION_MODULE_NAMES[-1], module)


def _legacy_api(data_dir: Path, data: dict[str, Any]) -> Any:
    module_name = COMPANION_MODULE_NAMES[-1]
    plugin_type = type(
        "PrivateCompanionPlugin",
        (),
        {"__module__": module_name},
    )
    api_type = type(
        "PrivateCompanionExtensionAPI",
        (),
        {"__module__": module_name},
    )
    plugin = plugin_type()
    plugin.data = data
    plugin._data_lock = asyncio.Lock()
    plugin.plugin_identity = {
        "plugin_id": COMPANION_PLUGIN_ID,
        "version": "6.4.1",
    }
    plugin.data_dir = data_dir
    plugin.data_file = data_dir / "companions.json"
    plugin.bot_name = "旧版小雪"
    plugin.enable_daily_plan = True
    plugin.enable_detail_enhancement = True
    plugin._get_current_plan_item = lambda plan: (plan.get("items") or [{}])[0]
    plugin._memory_companion_coordination_status = lambda: {
        "available": True,
        "state": "ready",
    }
    api = api_type()
    api._plugin = plugin
    api._story_migration_generation = "f" * 32
    api._story_migration_state = "ready"
    api.get_p6_readonly_status = lambda: {}
    api.story_migration_capabilities = lambda: {}

    async def export_story_migration_snapshot(
        *,
        lease_token: str = "",
    ) -> dict[str, Any]:
        assert lease_token == ""
        return {}

    api.export_story_migration_snapshot = export_story_migration_snapshot
    api.get_bot_identity = lambda: {}
    return api


def _assert_no_forbidden_keys(value: Any) -> None:
    forbidden = {
        "path",
        "image_path",
        "_local_path",
        "data_dir",
        "data_file",
        "plugin",
        "api",
        "cmd_config",
    }
    if isinstance(value, dict):
        assert not forbidden.intersection(value)
        for item in value.values():
            _assert_no_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_keys(item)


def test_formal_snapshot_is_exact_fresh_and_detached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "1" * 32
        api = _FormalAPI(generation)
        holder = {"api": api}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()

        result = await bridge.export_snapshot("2026-08-26")

        assert result.mode == "formal"
        assert result.payload == _snapshot(generation)
        assert api.capability_calls == 2
        assert api.snapshot_calls == 1
        assert bridge.formal_seen is True
        _assert_no_forbidden_keys(result.payload)
        result.payload["day"]["bot_name"] = "caller mutation"
        second = await bridge.export_snapshot("2026-08-26")
        assert second.payload["day"]["bot_name"] == "小雪"

    asyncio.run(run())


def test_current_registry_instance_wins_over_stale_module_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "9" * 32
        current_api = _FormalAPI(generation)
        stale_api = _FormalAPI("8" * 32)
        _install_api(monkeypatch, {"api": stale_api})
        plugin = SimpleNamespace(
            context=SimpleNamespace(
                get_all_stars=lambda: [],
                get_registered_star=lambda _name: SimpleNamespace(
                    extension_api=current_api,
                    activated=True,
                ),
            )
        )

        result = await CompanionPageBridge(plugin).export_snapshot("2026-08-26")

        assert result.payload["instance_generation"] == generation
        assert current_api.snapshot_calls == 1
        assert stale_api.snapshot_calls == 0

    asyncio.run(run())


def test_registry_absence_is_authoritative_over_stale_module_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        _install_api(monkeypatch, {"api": _FormalAPI("7" * 32)})
        plugin = SimpleNamespace(
            context=SimpleNamespace(
                get_all_stars=lambda: [],
                get_registered_star=lambda _name: None,
            )
        )

        with pytest.raises(CompanionPageBridgeError) as error:
            await CompanionPageBridge(plugin).export_snapshot("2026-08-26")

        assert error.value.code == "memory_page_companion_unavailable"

    asyncio.run(run())


def test_snapshot_generation_change_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        first = _FormalAPI("1" * 32)
        second = _FormalAPI("2" * 32)
        holder = {"api": first}
        _install_api(monkeypatch, holder)
        first.on_export = lambda: holder.update(api=second)

        result = await CompanionPageBridge().export_snapshot("2026-08-26")

        assert result.payload["instance_generation"] == "2" * 32
        assert first.snapshot_calls == 1
        assert second.snapshot_calls == 1

        third = _FormalAPI("3" * 32)
        fourth = _FormalAPI("4" * 32)
        holder["api"] = second
        second.on_export = lambda: holder.update(api=third)
        third.on_export = lambda: holder.update(api=fourth)
        with pytest.raises(CompanionPageBridgeError) as changed:
            await CompanionPageBridge().export_snapshot("2026-08-26")
        assert changed.value.code == "memory_page_generation_changed"

    asyncio.run(run())


def test_formal_marker_is_sticky_and_never_downgrades(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        partial = SimpleNamespace(memory_page_capabilities=lambda: {})
        holder = {"api": partial}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()

        with pytest.raises(CompanionPageBridgeError) as malformed:
            await bridge.export_snapshot()
        assert malformed.value.code == "memory_page_contract_malformed"
        assert bridge.formal_seen is True

        holder["api"] = _legacy_api(tmp_path, {})
        with pytest.raises(CompanionPageBridgeError) as downgrade:
            await bridge.export_snapshot()
        assert downgrade.value.code == "memory_page_contract_downgrade"

        with pytest.raises(CompanionPageBridgeError) as process_downgrade:
            await CompanionPageBridge().export_snapshot()
        assert process_downgrade.value.code == "memory_page_contract_downgrade"

    asyncio.run(run())


def test_ambiguous_aliases_latch_formal_and_block_later_legacy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        formal = _FormalAPI("1" * 32)
        legacy = _legacy_api(tmp_path, {})
        for module_name, api in zip(
            COMPANION_MODULE_NAMES,
            (formal, legacy),
            strict=True,
        ):
            module = types.ModuleType(module_name)
            module.get_private_companion_api = lambda api=api: api
            monkeypatch.setitem(sys.modules, module_name, module)

        bridge = CompanionPageBridge()
        with pytest.raises(CompanionPageBridgeError) as ambiguous:
            await bridge.export_snapshot()
        assert ambiguous.value.code == "memory_page_companion_ambiguous"
        assert bridge.formal_seen is True

        monkeypatch.delitem(sys.modules, COMPANION_MODULE_NAMES[0])
        with pytest.raises(CompanionPageBridgeError) as downgrade:
            await bridge.export_snapshot()
        assert downgrade.value.code == "memory_page_contract_downgrade"

    asyncio.run(run())


def test_unreadable_alias_blocks_other_alias_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        broken = types.ModuleType(COMPANION_MODULE_NAMES[0])

        def fail_getter() -> Any:
            raise RuntimeError("private failure must not escape")

        broken.get_private_companion_api = fail_getter
        legacy = types.ModuleType(COMPANION_MODULE_NAMES[1])
        legacy_api = _legacy_api(tmp_path, {})
        legacy.get_private_companion_api = lambda: legacy_api
        monkeypatch.setitem(sys.modules, COMPANION_MODULE_NAMES[0], broken)
        monkeypatch.setitem(sys.modules, COMPANION_MODULE_NAMES[1], legacy)
        bridge = CompanionPageBridge()

        with pytest.raises(CompanionPageBridgeError) as unreadable:
            await bridge.export_snapshot()

        assert unreadable.value.code == "memory_page_companion_unreadable"
        assert bridge._legacy_adapter is None

    asyncio.run(run())


def test_empty_alias_blocks_other_alias_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        empty = types.ModuleType(COMPANION_MODULE_NAMES[0])
        empty.get_private_companion_api = lambda: None
        legacy = types.ModuleType(COMPANION_MODULE_NAMES[1])
        legacy_api = _legacy_api(tmp_path, {})
        legacy.get_private_companion_api = lambda: legacy_api
        monkeypatch.setitem(sys.modules, COMPANION_MODULE_NAMES[0], empty)
        monkeypatch.setitem(sys.modules, COMPANION_MODULE_NAMES[1], legacy)
        bridge = CompanionPageBridge()

        with pytest.raises(CompanionPageBridgeError) as unreadable:
            await bridge.export_snapshot()

        assert unreadable.value.code == "memory_page_companion_unreadable"
        assert bridge._legacy_adapter is None

    asyncio.run(run())


def test_formal_latch_between_surface_selection_and_legacy_creation_blocks_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        holder = {"api": _legacy_api(tmp_path, {})}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()
        original_select = bridge._select_surface

        def latch_after_selection(resolved: Any) -> str:
            surface = original_select(resolved)
            assert surface == "legacy"
            with bridge_module._COMPANION_PAGE_RUNTIME.lock:
                bridge_module._COMPANION_PAGE_RUNTIME.formal_seen = True
            return surface

        monkeypatch.setattr(bridge, "_select_surface", latch_after_selection)

        with pytest.raises(CompanionPageBridgeError) as downgrade:
            await bridge.export_snapshot()

        assert downgrade.value.code == "memory_page_contract_downgrade"
        assert bridge._legacy_adapter is None

    asyncio.run(run())


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value.update(extra=True), "memory_page_contract_malformed"),
        (
            lambda value: value.update(api_version="companion.memory-page-api.v999"),
            "memory_page_contract_unsupported",
        ),
        (
            lambda value: value.update(instance_generation="not-a-generation"),
            "memory_page_contract_malformed",
        ),
    ],
)
def test_descriptor_is_exact(
    mutation: Any,
    code: str,
) -> None:
    value = _descriptor("1" * 32)
    mutation(value)
    with pytest.raises(CompanionPageBridgeError) as refused:
        validate_memory_page_descriptor(value)
    assert refused.value.code == code


def test_snapshot_hash_limits_and_nested_fields_are_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = "1" * 32
    extra = _snapshot(generation)
    extra["day"]["photos"].append(
        {
            "id": f"photo_{'P' * 22}",
            "date": "2026-08-26",
            "kind": "life_photo",
            "generated_at": 1,
            "available": False,
            "error_code": "memory_page_photo_unavailable",
            "photo_ref": "",
            "path": "/private/photo.png",
        }
    )
    with pytest.raises(CompanionPageBridgeError) as nested:
        validate_memory_page_snapshot(extra, expected_generation=generation)
    assert nested.value.code == "memory_page_snapshot_malformed"

    wrong_hash = _snapshot(generation)
    wrong_hash["day"]["bot_name"] = "changed after seal"
    with pytest.raises(CompanionPageBridgeError) as digest:
        validate_memory_page_snapshot(wrong_hash, expected_generation=generation)
    assert digest.value.code == "memory_page_snapshot_malformed"

    wrong_id = _snapshot(generation)
    wrong_id["snapshot_id"] = f"memorypagesnap_{'0' * 64}"
    with pytest.raises(CompanionPageBridgeError) as identity:
        validate_memory_page_snapshot(wrong_id, expected_generation=generation)
    assert identity.value.code == "memory_page_snapshot_malformed"

    cross_day = _snapshot(generation)
    cross_day["day"]["date"] = "2026-08-25"
    with pytest.raises(CompanionPageBridgeError) as day:
        validate_memory_page_snapshot(
            _reseal_snapshot(cross_day),
            expected_generation=generation,
        )
    assert day.value.code == "memory_page_snapshot_malformed"

    with pytest.raises(CompanionPageBridgeError) as requested:
        validate_memory_page_snapshot(
            _snapshot(generation),
            expected_generation=generation,
            expected_selected_date="2026-08-25",
        )
    assert requested.value.code == "memory_page_snapshot_malformed"

    unreachable_default = _snapshot(generation)
    unreachable_default["selected_date"] = "2026-08-25"
    unreachable_default["day"]["date"] = "2026-08-25"
    unreachable_default["day"]["plan"] = {
        "date": "",
        "source": "none",
        "items": [],
    }
    unreachable_default["day"]["current_item"] = {
        "index": None,
        "time": "",
        "activity": "",
        "mood": "",
        "message_seed": "",
    }
    unreachable_default["day"]["daily_state"] = {
        "date": "",
        "energy": None,
        "mood_bias": "",
        "sleep": "",
        "weather": "",
        "note": "",
    }
    unreachable_default["day"]["details"] = []
    unreachable_default["day"]["diaries"] = []
    with pytest.raises(CompanionPageBridgeError) as unreachable:
        validate_memory_page_snapshot(
            _reseal_snapshot(unreachable_default),
            expected_generation=generation,
        )
    assert unreachable.value.code == "memory_page_snapshot_malformed"

    cross_photo = _snapshot(
        generation,
        photos=[
            {
                "id": f"photo_{'P' * 22}",
                "date": "2026-08-25",
                "kind": "life_photo",
                "generated_at": 1,
                "available": False,
                "error_code": "memory_page_photo_unavailable",
                "photo_ref": "",
            }
        ],
    )
    with pytest.raises(CompanionPageBridgeError) as photo_date:
        validate_memory_page_snapshot(
            cross_photo,
            expected_generation=generation,
        )
    assert photo_date.value.code == "memory_page_snapshot_malformed"

    controlled = _snapshot(generation)
    controlled["day"]["bot_name"] = "line\nbreak"
    with pytest.raises(CompanionPageBridgeError) as control:
        validate_memory_page_snapshot(
            _reseal_snapshot(controlled),
            expected_generation=generation,
        )
    assert control.value.code == "memory_page_snapshot_malformed"

    gap = _snapshot(generation)
    gap["day"]["plan"]["items"] = [
        {
            "index": 1,
            "time": "09:00",
            "activity": "散步",
            "mood": "",
            "message_seed": "",
        },
        {
            "index": 3,
            "time": "10:00",
            "activity": "读书",
            "mood": "",
            "message_seed": "",
        },
    ]
    gap["day"]["current_item"] = copy.deepcopy(
        gap["day"]["plan"]["items"][1]
    )
    validated_gap = validate_memory_page_snapshot(
        _reseal_snapshot(gap),
        expected_generation=generation,
    )
    assert [item["index"] for item in validated_gap["day"]["plan"]["items"]] == [
        1,
        3,
    ]

    monkeypatch.setattr(bridge_module, "MEMORY_PAGE_SNAPSHOT_MAX_BYTES", 128)
    with pytest.raises(CompanionPageBridgeError) as too_large:
        validate_memory_page_snapshot(
            _snapshot(generation),
            expected_generation=generation,
        )
    assert too_large.value.code == "memory_page_snapshot_too_large"


def test_snapshot_allows_distinct_photo_rows_to_share_one_capability_ref() -> None:
    generation = "1" * 32
    shared_ref = f"mphoto_{generation[:12]}_{'A' * 22}"
    value = _snapshot(
        generation,
        photos=[
            {
                "id": f"photo_{'P' * 22}",
                "date": "2026-08-26",
                "kind": "daily_outfit",
                "generated_at": 2,
                "available": True,
                "error_code": "",
                "photo_ref": shared_ref,
            },
            {
                "id": f"photo_{'Q' * 22}",
                "date": "2026-08-26",
                "kind": "recent_photo",
                "generated_at": 1,
                "available": True,
                "error_code": "",
                "photo_ref": shared_ref,
            },
        ],
    )

    result = validate_memory_page_snapshot(
        value,
        expected_generation=generation,
    )

    assert [item["photo_ref"] for item in result["day"]["photos"]] == [
        shared_ref,
        shared_ref,
    ]


@pytest.mark.parametrize(
    "mutation",
    ["opaque_id", "plan_time", "daily_sleep", "reason", "diary_date"],
)
def test_snapshot_exact_field_bounds(mutation: str) -> None:
    generation = "1" * 32
    value = _snapshot(generation)
    if mutation == "opaque_id":
        value["day"]["details"][0]["id"] = "detail_too_short"
    elif mutation == "plan_time":
        value["day"]["plan"]["items"][0]["time"] = "1" * 21
        value["day"]["current_item"]["time"] = "1" * 21
    elif mutation == "daily_sleep":
        value["day"]["daily_state"]["sleep"] = "睡" * 81
    elif mutation == "reason":
        value["coordination"] = {
            "available": False,
            "state": "degraded",
            "reason_code": "1invalid",
        }
    else:
        value["day"]["diaries"][0]["date"] = "2026-08-25"

    with pytest.raises(CompanionPageBridgeError) as refused:
        validate_memory_page_snapshot(
            _reseal_snapshot(value),
            expected_generation=generation,
        )
    assert refused.value.code == "memory_page_snapshot_malformed"


def test_formal_photo_is_generation_bound_and_revalidated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "a" * 32
        photo_ref = f"mphoto_{generation[:12]}_{'A' * 22}"
        api = _FormalAPI(
            generation,
            photo=_photo_result(generation, photo_ref),
        )
        holder = {"api": api}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()

        result = await bridge.read_photo(photo_ref)

        assert result.content == PNG
        assert result.mime_type == "image/png"
        assert result.mode == "formal"
        assert api.photo_calls == 1
        assert api.capability_calls == 2

        stale = f"mphoto_{'b' * 12}_{'B' * 22}"
        with pytest.raises(CompanionPageBridgeError) as refused:
            await bridge.read_photo(stale)
        assert refused.value.code == "memory_page_photo_ref_stale"
        assert api.photo_calls == 1

    asyncio.run(run())


def test_formal_photo_hot_reload_is_stale_without_retry_or_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "a" * 32
        photo_ref = f"mphoto_{generation[:12]}_{'A' * 22}"
        first = _FormalAPI(
            generation,
            photo=_photo_result(generation, photo_ref),
        )
        second = _FormalAPI("b" * 32)
        holder = {"api": first}
        _install_api(monkeypatch, holder)
        first.on_photo = lambda: holder.update(api=second)

        with pytest.raises(CompanionPageBridgeError) as stale:
            await CompanionPageBridge().read_photo(photo_ref)

        assert stale.value.code == "memory_page_photo_ref_stale"
        assert first.photo_calls == 1
        assert second.photo_calls == 0

    asyncio.run(run())


def test_expected_formal_photo_mode_never_enters_legacy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        holder = {"api": _legacy_api(tmp_path, {})}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()
        reference = f"mphoto_{'a' * 12}_{'A' * 22}"

        with pytest.raises(CompanionPageBridgeError) as snapshot_stale:
            await bridge.export_snapshot(
                "2026-08-26",
                expected_mode="formal",
            )
        assert snapshot_stale.value.code == "memory_page_photo_ref_stale"

        with pytest.raises(CompanionPageBridgeError) as photo_stale:
            await bridge.read_photo(reference, expected_mode="formal")
        assert photo_stale.value.code == "memory_page_photo_ref_stale"
        assert bridge._legacy_adapter is None

    asyncio.run(run())


def test_p6_status_rechecks_fresh_facade_and_detaches_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: dict[str, Any] = {}

    def swapping_status() -> dict[str, Any]:
        holder["api"] = SimpleNamespace(get_p6_readonly_status=lambda: {"count": 2})
        return {"count": 1}

    holder["api"] = SimpleNamespace(get_p6_readonly_status=swapping_status)
    _install_api(monkeypatch, holder)
    bridge = CompanionPageBridge()

    with pytest.raises(CompanionPageBridgeError) as stale:
        bridge.read_p6_status()
    assert stale.value.code == "companion_p6_producer_stale"

    stable = {"nested": {"count": 3}}
    holder["api"] = SimpleNamespace(get_p6_readonly_status=lambda: stable)
    result = bridge.read_p6_status()
    result["nested"]["count"] = 9
    assert stable["nested"]["count"] == 3


def test_p6_observation_latches_formal_page_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        formal = _FormalAPI("1" * 32)
        formal.get_p6_readonly_status = lambda: {"available": True}
        holder = {"api": formal}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()

        assert bridge.read_p6_status() == {"available": True}
        assert bridge.formal_seen is True
        legacy = _legacy_api(tmp_path, {})
        legacy_calls = 0

        def legacy_p6() -> dict[str, Any]:
            nonlocal legacy_calls
            legacy_calls += 1
            return {"available": True}

        legacy.get_p6_readonly_status = legacy_p6
        holder["api"] = legacy

        with pytest.raises(CompanionPageBridgeError) as p6_downgrade:
            bridge.read_p6_status()
        assert p6_downgrade.value.code == "companion_p6_producer_stale"
        assert legacy_calls == 0

        with pytest.raises(CompanionPageBridgeError) as downgrade:
            await bridge.export_snapshot()
        assert downgrade.value.code == "memory_page_contract_downgrade"

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["base64", "digest", "mime", "extra"])
def test_photo_wire_magic_hash_and_base64_are_strict(mutation: str) -> None:
    generation = "a" * 32
    photo_ref = f"mphoto_{generation[:12]}_{'A' * 22}"
    value = _photo_result(generation, photo_ref)
    if mutation == "base64":
        value["content_base64"] = value["content_base64"][:-1] + "!"
    elif mutation == "digest":
        value["sha256"] = "0" * 64
    elif mutation == "mime":
        value["mime_type"] = "image/jpeg"
    else:
        value["path"] = "/private/photo.png"
    with pytest.raises(CompanionPageBridgeError):
        validate_memory_page_photo(
            value,
            expected_generation=generation,
            expected_photo_ref=photo_ref,
        )


def test_known_n_minus_one_legacy_is_path_free_and_symlink_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        inside = tmp_path / "inside.png"
        inside.write_bytes(PNG)
        outside = tmp_path.parent / "outside.png"
        outside.write_bytes(PNG)
        symlink = tmp_path / "linked.png"
        symlink.symlink_to(outside)
        data = {
            "daily_plan": {
                "date": "2026-08-26",
                "items": [{"time": "08:00", "activity": "早餐"}],
            },
            "daily_plan_history": [
                {
                    "date": "2026-08-25",
                    "items": [
                        {"time": "09:00", "activity": "散步"},
                        {"time": "10:00", "activity": "读书"},
                    ],
                }
            ],
            "detail_enhanced_history": [
                {
                    "date": "2026-08-25",
                    "segments": {
                        "2026-08-25:0:09:00": {
                            "index": 0,
                            "status": "ready",
                            "summary": "沿河散步",
                        }
                    },
                }
            ],
            "detail_enhanced_day": "2026-08-26",
            "detail_enhanced_segments": {
                "2026-08-26:0:08:00": {
                    "status": "completed",
                    "summary": "早餐完成",
                }
            },
            "daily_state": {"date": "2026-08-26", "energy": 70},
            "daily_outfit_photo": {
                "date": "2026-08-26",
                "path": str(inside),
                "generated_at": 1,
            },
            "daily_outfit_history": [
                {
                    "date": "2026-08-25",
                    "path": str(inside),
                    "generated_at": 3,
                }
            ],
            "recent_photo_generations": [
                {
                    "ok": True,
                    "date": "2026-08-26",
                    "path": str(symlink),
                    "kind": "text2img",
                    "generated_at": 2,
                }
            ],
        }
        api = _legacy_api(tmp_path, data)
        holder = {"api": api}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()

        snapshot = await bridge.export_snapshot("2026-08-26")

        assert snapshot.mode == "legacy"
        _assert_no_forbidden_keys(snapshot.payload)
        photos = snapshot.payload["day"]["photos"]
        available_photo = next(item for item in photos if item["available"] is True)
        unavailable_photo = next(item for item in photos if item["available"] is False)
        assert unavailable_photo["photo_ref"] == ""
        assert snapshot.payload["day"]["current_item"]["index"] == 0
        assert snapshot.payload["day"]["details"][0]["status"] == "ready"
        assert snapshot.payload["day"]["details"][0]["index"] == 0
        assert snapshot.payload["day"]["details"][0]["time"] == "08:00"
        result = await bridge.read_photo(available_photo["photo_ref"])
        assert result.content == PNG
        assert result.mode == "legacy"
        assert str(tmp_path) not in json.dumps(snapshot.payload)

        repeated = await bridge.export_snapshot("2026-08-26")
        repeated_photo = next(
            item
            for item in repeated.payload["day"]["photos"]
            if item["available"] is True
        )
        assert repeated_photo["photo_ref"] == available_photo["photo_ref"]

        history = await bridge.export_snapshot("2026-08-25")
        assert len(history.payload["day"]["plan"]["items"]) == 2
        assert history.payload["day"]["details"][0]["summary"] == "沿河散步"
        assert history.payload["day"]["photos"][0]["available"] is True

        api._story_migration_state = "closed"
        with pytest.raises(CompanionPageBridgeError) as closed:
            await bridge.read_photo(available_photo["photo_ref"])
        assert closed.value.code == "memory_page_photo_ref_stale"

    asyncio.run(run())


def test_legacy_hot_reload_retries_with_fresh_facade_and_retires_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        first = _legacy_api(
            tmp_path,
            {
                "daily_plan": {
                    "date": "2026-08-26",
                    "items": [{"time": "08:00", "activity": "旧实例"}],
                }
            },
        )
        second = _legacy_api(
            tmp_path,
            {
                "daily_plan": {
                    "date": "2026-08-26",
                    "items": [{"time": "09:00", "activity": "新实例"}],
                }
            },
        )
        second._plugin.bot_name = "新版小雪"
        holder = {"api": first}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()
        retired: dict[str, Any] = {}

        def swap_facade(plan: dict[str, Any]) -> dict[str, Any]:
            retired["adapter"] = bridge._legacy_adapter
            first._story_migration_state = "superseded"
            holder["api"] = second
            return plan["items"][0]

        first._plugin._get_current_plan_item = swap_facade

        result = await bridge.export_snapshot("2026-08-26")

        assert result.mode == "legacy"
        assert result.payload["day"]["bot_name"] == "新版小雪"
        assert result.payload["day"]["plan"]["items"][0]["activity"] == "新实例"
        assert retired["adapter"]._closed is True
        assert not retired["adapter"]._photos
        assert bridge._legacy_api is second

    asyncio.run(run())


def test_legacy_date_without_plan_uses_exact_empty_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        api = _legacy_api(
            tmp_path,
            {"daily_state": {"date": "2026-08-26", "energy": 60}},
        )
        holder = {"api": api}
        _install_api(monkeypatch, holder)

        result = await CompanionPageBridge().export_snapshot("2026-08-26")

        assert result.payload["day"]["plan"] == {
            "date": "",
            "source": "none",
            "items": [],
        }
        assert result.payload["day"]["current_item"] == {
            "index": None,
            "time": "",
            "activity": "",
            "mood": "",
            "message_seed": "",
        }

    asyncio.run(run())


def test_legacy_empty_date_clears_state_and_ignores_unrelated_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        class DeepcopyBomb:
            def __deepcopy__(self, memo: dict[int, Any]) -> Any:
                raise AssertionError("unrelated state must not be copied")

        api = _legacy_api(
            tmp_path,
            {
                "daily_state": {"energy": 90, "note": "must stay hidden"},
                "unrelated": DeepcopyBomb(),
            },
        )
        holder = {"api": api}
        _install_api(monkeypatch, holder)

        result = await CompanionPageBridge().export_snapshot()

        assert result.payload["selected_date"] == ""
        assert result.payload["day"]["daily_state"] == {
            "date": "",
            "energy": None,
            "mood_bias": "",
            "sleep": "",
            "weather": "",
            "note": "",
        }

    asyncio.run(run())


def test_legacy_story_details_do_not_displace_enhanced_segments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        segments = {
            f"2026-08-26:{index}:{index:02d}:00": {
                "status": "ready",
                "summary": f"segment-{index}",
            }
            for index in range(17)
        }
        api = _legacy_api(
            tmp_path,
            {
                "detail_enhanced_day": "2026-08-26",
                "detail_enhanced_segments": segments,
                "daily_story_plan": {
                    "date": "2026-08-26",
                    "today_events": [
                        {"window": "上午", "event": "story-morning"},
                        {"window": "下午", "event": "story-afternoon"},
                    ],
                },
            },
        )
        holder = {"api": api}
        _install_api(monkeypatch, holder)

        result = await CompanionPageBridge().export_snapshot("2026-08-26")
        details = result.payload["day"]["details"]

        assert len(details) == 18
        assert [item["summary"] for item in details[:17]] == [
            f"segment-{index}" for index in range(17)
        ]
        assert details[17]["status"] == "story_plan"

    asyncio.run(run())


def test_legacy_refresh_keeps_new_registration_during_old_photo_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        image = tmp_path / "inside.png"
        image.write_bytes(PNG)
        api = _legacy_api(
            tmp_path,
            {
                "daily_outfit_photo": {
                    "date": "2026-08-26",
                    "path": str(image),
                    "generated_at": 1,
                }
            },
        )
        holder = {"api": api}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()
        first = await bridge.export_snapshot("2026-08-26")
        photo_ref = first.payload["day"]["photos"][0]["photo_ref"]
        adapter = bridge._legacy_adapter
        original_read = adapter._read_photo_sync
        entered = threading.Event()
        release = threading.Event()

        def blocked_read(reference: str, record: Any) -> bytes:
            entered.set()
            assert release.wait(timeout=5)
            return original_read(reference, record)

        monkeypatch.setattr(adapter, "_read_photo_sync", blocked_read)
        old_read = asyncio.create_task(bridge.read_photo(photo_ref))
        assert await asyncio.to_thread(entered.wait, 5)

        refreshed = await bridge.export_snapshot("2026-08-26")
        assert refreshed.payload["day"]["photos"][0]["photo_ref"] == photo_ref
        release.set()

        with pytest.raises(CompanionPageBridgeError) as superseded:
            await old_read
        assert superseded.value.code == "memory_page_photo_ref_expired"
        assert (await bridge.read_photo(photo_ref)).content == PNG

    asyncio.run(run())


def test_unknown_legacy_surface_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        holder = {"api": SimpleNamespace(get_p6_readonly_status=lambda: {})}
        _install_api(monkeypatch, holder)
        with pytest.raises(CompanionPageBridgeError) as refused:
            await CompanionPageBridge().export_snapshot()
        assert refused.value.code == "memory_page_legacy_unsupported"

    asyncio.run(run())


def test_legacy_snapshot_waits_for_data_lock_and_rechecks_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        api = _legacy_api(
            tmp_path,
            {"daily_plan": {"date": "2026-08-26", "items": []}},
        )
        holder = {"api": api}
        _install_api(monkeypatch, holder)
        bridge = CompanionPageBridge()
        await api._plugin._data_lock.acquire()
        pending = asyncio.create_task(
            bridge.export_snapshot("2026-08-26")
        )
        await asyncio.sleep(0)
        assert pending.done() is False

        api._story_migration_state = "closed"
        api._plugin._data_lock.release()
        with pytest.raises(CompanionPageBridgeError) as closed:
            await pending
        assert closed.value.code == "memory_page_service_closed"
        assert bridge._legacy_adapter is None

    asyncio.run(run())


def test_legacy_fingerprint_rejects_wrong_async_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def run() -> None:
        api = _legacy_api(tmp_path, {})
        api.export_story_migration_snapshot = lambda: {}
        holder = {"api": api}
        _install_api(monkeypatch, holder)

        with pytest.raises(CompanionPageBridgeError) as refused:
            await CompanionPageBridge().export_snapshot()
        assert refused.value.code == "memory_page_legacy_unsupported"

    asyncio.run(run())


@pytest.mark.parametrize("version", ["", "6.4.0", "6.4.2"])
def test_legacy_fingerprint_rejects_missing_or_unknown_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: str,
) -> None:
    async def run() -> None:
        api = _legacy_api(tmp_path, {})
        if version:
            api._plugin.plugin_identity["version"] = version
        else:
            api._plugin.plugin_identity.pop("version")
        holder = {"api": api}
        _install_api(monkeypatch, holder)

        with pytest.raises(CompanionPageBridgeError) as refused:
            await CompanionPageBridge().export_snapshot()
        assert refused.value.code == "memory_page_legacy_unsupported"

    asyncio.run(run())


class _JsonResponse(dict):
    def __init__(self, value: dict[str, Any]) -> None:
        super().__init__(value)
        self.status_code = 200
        self.headers: dict[str, str] = {}


def _memory_record(**changes: Any) -> Any:
    value = {
        "id": "memory-1",
        "memory_type": "self_action",
        "visibility": "bot_self",
        "reality_level": "bot_action",
        "content": "完成了一件事",
        "tags": ["bot_action"],
        "source_plugin": "private_companion",
        "metadata": {"date": "2026-08-26"},
        "occurred_at": "2026-08-26T10:00:00+08:00",
        "created_at": "2026-08-26T10:00:00+08:00",
    }
    value.update(changes)
    return SimpleNamespace(**value)


def test_page_projects_formal_snapshot_then_merges_only_safe_local_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "1" * 32
        photo_ref = f"mphoto_{generation[:12]}_{'A' * 22}"
        value = _snapshot(
            generation,
            photos=[
                {
                    "id": f"photo_{'P' * 22}",
                    "date": "2026-08-26",
                    "kind": "life_photo",
                    "generated_at": 1,
                    "available": True,
                    "error_code": "",
                    "photo_ref": photo_ref,
                }
            ],
        )
        events: list[str] = []

        class StubBridge:
            async def export_snapshot(self, selected_date: str) -> CompanionPageSnapshot:
                events.append("snapshot")
                return CompanionPageSnapshot(copy.deepcopy(value), "formal")

        schedule = _memory_record(
            id="schedule-1",
            memory_type="schedule_fragment",
            tags=["schedule"],
            content="当日生活日程\n08:00 早餐\n10:00 散步\n生活片段：晒太阳",
            metadata={
                "date": "2026-08-26",
                "start": "08:00",
                "end": "10:00",
                "summary": "上午安排",
            },
        )
        dream = _memory_record(
            id="dream-1",
            memory_type="persona_life",
            tags=["dream"],
            content="梦见了海",
        )
        action = _memory_record(
            id="action-1",
            memory_type="image_action",
            tags=["image_action"],
            metadata={
                "date": "2026-08-26",
                "path": "/private/secret.png",
                "provider": "secret-provider",
                "action_label": "生图",
                "image_count": 1,
            },
        )
        invalid_date_action = _memory_record(
            id="action-invalid-date",
            content="不应进入所选日期",
            metadata={"date": "2026-99-99"},
            occurred_at="not-a-timestamp",
            created_at="also-not-a-timestamp",
        )

        async def list_memories(**_kwargs: Any) -> list[Any]:
            events.append("records")
            return [schedule, dream, action, invalid_date_action]

        store = SimpleNamespace(list_memories=AsyncMock(side_effect=list_memories))
        page = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=store)))
        page._companion_page_bridge = StubBridge()
        fake_request = SimpleNamespace(
            args={"date": "2026-08-26", "q": "", "limit": "80"},
            method="GET",
        )
        monkeypatch.setattr(page_api_module, "request", fake_request)
        monkeypatch.setattr(
            page_api_module,
            "jsonify",
            lambda body: _JsonResponse(body),
        )

        response = await page.companion_personal_memory()

        assert events[0] == "snapshot"
        assert response["available"] is True
        assert response.headers["Cache-Control"] == "private, no-store"
        assert len(response["snapshot"]["plan"]["items"]) == 1
        assert response["snapshot"]["current_item"] == response["snapshot"]["plan"]["items"][0]
        assert any(item["status"] == "memory" for item in response["snapshot"]["details"])
        assert len(response["snapshot"]["subjective_memories"]) == 2
        album_url = response["snapshot"]["album"][0]["image_data_url"]
        assert f"ref={photo_ref}" in album_url
        assert "date=2026-08-26" in album_url
        assert f"id=photo_{'P' * 22}" in album_url
        assert "mode=formal" in album_url
        encoded = json.dumps(response, ensure_ascii=False)
        assert "/private/secret.png" not in encoded
        assert "secret-provider" not in encoded
        assert "session_id" not in encoded
        assert "2026-99-99" not in response["dates"]
        assert "不应进入所选日期" not in encoded
        assert response["actions"][0]["metadata"] == {
            "action_label": "生图",
            "image_count": 1,
            "text": "",
        }

        fallback_value = copy.deepcopy(value)
        fallback_value["day"]["plan"] = {
            "date": "",
            "source": "none",
            "items": [],
        }
        fallback_value["day"]["current_item"] = {
            "index": None,
            "time": "",
            "activity": "",
            "mood": "",
            "message_seed": "",
        }
        fallback = page._project_companion_page(
            CompanionPageSnapshot(_reseal_snapshot(fallback_value), "formal"),
            [schedule],
        )
        assert len(fallback["snapshot"]["plan"]["items"]) == 2
        assert fallback["snapshot"]["current_item"]["index"] is None

        gap_plan = {
            "date": "2026-08-26",
            "source": "live",
            "items": [
                {"index": 1, "time": "08:00", "activity": "早餐"},
                {"index": 3, "time": "10:00", "activity": "散步"},
            ],
        }
        gap_details = page._schedule_memory_details(
            [schedule],
            "2026-08-26",
            gap_plan,
        )
        assert gap_details[0]["index"] == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    ("code", "success", "status"),
    [
        ("memory_page_companion_unavailable", True, 200),
        ("memory_page_contract_malformed", False, 503),
        ("memory_page_snapshot_too_large", False, 413),
    ],
)
def test_page_snapshot_failures_are_classified_and_never_cached(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    success: bool,
    status: int,
) -> None:
    async def run() -> None:
        class StubBridge:
            async def export_snapshot(self, selected_date: str) -> CompanionPageSnapshot:
                raise CompanionPageBridgeError(code)

        page = PluginPageApi(SimpleNamespace(service=SimpleNamespace()))
        page._companion_page_bridge = StubBridge()
        monkeypatch.setattr(
            page_api_module,
            "request",
            SimpleNamespace(args={"date": "", "q": "", "limit": "80"}, method="GET"),
        )
        monkeypatch.setattr(
            page_api_module,
            "jsonify",
            lambda body: _JsonResponse(body),
        )

        response = await page.companion_personal_memory()

        assert response["success"] is success
        assert response.status_code == status
        assert response.headers["Cache-Control"] == "private, no-store"
        if success:
            assert response["available"] is False
        else:
            assert response["error"] == code

    asyncio.run(run())


def test_page_uses_latest_local_date_when_formal_snapshot_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "1" * 32
        empty = _snapshot(generation)
        empty["selected_date"] = ""
        empty["available_dates"] = []
        empty["day"] = {
            "date": "",
            "bot_name": "小雪",
            "plan": {"date": "", "source": "none", "items": []},
            "current_item": {
                "index": None,
                "time": "",
                "activity": "",
                "mood": "",
                "message_seed": "",
            },
            "daily_state": {
                "date": "",
                "energy": None,
                "mood_bias": "",
                "sleep": "",
                "weather": "",
                "note": "",
            },
            "details": [],
            "photos": [],
            "diaries": [],
        }
        empty = _reseal_snapshot(empty)

        class StubBridge:
            async def export_snapshot(self, selected_date: str) -> CompanionPageSnapshot:
                assert selected_date == ""
                return CompanionPageSnapshot(copy.deepcopy(empty), "formal")

        schedule = _memory_record(
            id="schedule-latest",
            memory_type="schedule_fragment",
            tags=["schedule"],
            content="当日生活日程\n08:00 早餐",
            metadata={"date": "2026-08-26", "start": "08:00"},
        )
        latest_action = _memory_record(
            id="action-latest",
            content="今天的动作",
            metadata={"date": "2026-08-26"},
        )
        older_action = _memory_record(
            id="action-older",
            content="昨天的动作",
            metadata={"date": "2026-08-25"},
            occurred_at="2026-08-25T10:00:00+08:00",
            created_at="2026-08-25T10:00:00+08:00",
        )
        store = SimpleNamespace(
            list_memories=AsyncMock(
                return_value=[schedule, latest_action, older_action]
            )
        )
        page = PluginPageApi(SimpleNamespace(service=SimpleNamespace(store=store)))
        page._companion_page_bridge = StubBridge()
        monkeypatch.setattr(
            page_api_module,
            "request",
            SimpleNamespace(args={"date": "", "q": "", "limit": "80"}, method="GET"),
        )
        monkeypatch.setattr(
            page_api_module,
            "jsonify",
            lambda body: _JsonResponse(body),
        )

        response = await page.companion_personal_memory()

        assert response["selected_date"] == "2026-08-26"
        assert response["dates"] == ["2026-08-26", "2026-08-25"]
        assert response["snapshot"]["plan"]["items"][0]["activity"] == "早餐"
        assert [item["id"] for item in response["actions"]] == ["action-latest"]

    asyncio.run(run())


def test_page_refreshes_expired_photo_ref_once_by_date_and_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "1" * 32
        photo_id = f"photo_{'P' * 22}"
        old_ref = f"mphoto_{generation[:12]}_{'A' * 22}"
        fresh_ref = f"mphoto_{generation[:12]}_{'B' * 22}"
        fresh_photo = CompanionPagePhoto(
            photo_ref=fresh_ref,
            mime_type="image/png",
            size=len(PNG),
            sha256=hashlib.sha256(PNG).hexdigest(),
            content_base64=base64.b64encode(PNG).decode("ascii"),
            content=PNG,
            mode="formal",
        )
        refreshed = _snapshot(
            generation,
            photos=[
                {
                    "id": photo_id,
                    "date": "2026-08-26",
                    "kind": "life_photo",
                    "generated_at": 1,
                    "available": True,
                    "error_code": "",
                    "photo_ref": fresh_ref,
                }
            ],
        )

        class StubBridge:
            def __init__(self) -> None:
                self.read_refs: list[str] = []
                self.snapshot_dates: list[str] = []

            async def read_photo(
                self,
                value: str,
                *,
                expected_mode: str | None = None,
            ) -> CompanionPagePhoto:
                assert expected_mode == "formal"
                self.read_refs.append(value)
                if value == old_ref:
                    raise CompanionPageBridgeError("memory_page_photo_ref_expired")
                assert value == fresh_ref
                return fresh_photo

            async def export_snapshot(
                self,
                selected_date: str,
                *,
                expected_mode: str | None = None,
            ) -> CompanionPageSnapshot:
                assert expected_mode == "formal"
                self.snapshot_dates.append(selected_date)
                return CompanionPageSnapshot(copy.deepcopy(refreshed), "formal")

        bridge = StubBridge()
        page = PluginPageApi(SimpleNamespace(service=SimpleNamespace()))
        page._companion_page_bridge = bridge
        monkeypatch.setattr(
            page_api_module,
            "request",
            SimpleNamespace(
                args={
                    "ref": old_ref,
                    "date": "2026-08-26",
                    "id": photo_id,
                    "mode": "formal",
                },
                method="GET",
            ),
        )

        result = await page._read_companion_photo_from_request()

        assert result is fresh_photo
        assert bridge.read_refs == [old_ref, fresh_ref]
        assert bridge.snapshot_dates == ["2026-08-26"]

    asyncio.run(run())


def test_page_does_not_repeat_photo_refresh_after_second_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "1" * 32
        photo_id = f"photo_{'P' * 22}"
        old_ref = f"mphoto_{generation[:12]}_{'A' * 22}"
        fresh_ref = f"mphoto_{generation[:12]}_{'B' * 22}"
        refreshed = _snapshot(
            generation,
            photos=[
                {
                    "id": photo_id,
                    "date": "2026-08-26",
                    "kind": "life_photo",
                    "generated_at": 1,
                    "available": True,
                    "error_code": "",
                    "photo_ref": fresh_ref,
                }
            ],
        )

        class StubBridge:
            def __init__(self) -> None:
                self.read_refs: list[str] = []
                self.export_count = 0

            async def read_photo(
                self,
                value: str,
                *,
                expected_mode: str | None = None,
            ) -> CompanionPagePhoto:
                assert expected_mode == "formal"
                self.read_refs.append(value)
                raise CompanionPageBridgeError("memory_page_photo_ref_stale")

            async def export_snapshot(
                self,
                selected_date: str,
                *,
                expected_mode: str | None = None,
            ) -> CompanionPageSnapshot:
                assert selected_date == "2026-08-26"
                assert expected_mode == "formal"
                self.export_count += 1
                return CompanionPageSnapshot(copy.deepcopy(refreshed), "formal")

        bridge = StubBridge()
        page = PluginPageApi(SimpleNamespace(service=SimpleNamespace()))
        page._companion_page_bridge = bridge
        monkeypatch.setattr(
            page_api_module,
            "request",
            SimpleNamespace(
                args={
                    "ref": old_ref,
                    "date": "2026-08-26",
                    "id": photo_id,
                    "mode": "formal",
                },
                method="GET",
            ),
        )

        result = await page._read_companion_photo_from_request()

        assert result == {"error": "memory_page_photo_ref_stale", "status": 410}
        assert bridge.read_refs == [old_ref, fresh_ref]
        assert bridge.export_count == 1

    asyncio.run(run())


def test_page_photo_responses_are_private_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        generation = "1" * 32
        photo_ref = f"mphoto_{generation[:12]}_{'A' * 22}"
        photo = CompanionPagePhoto(
            photo_ref=photo_ref,
            mime_type="image/png",
            size=len(PNG),
            sha256=hashlib.sha256(PNG).hexdigest(),
            content_base64=base64.b64encode(PNG).decode("ascii"),
            content=PNG,
            mode="formal",
        )

        class StubBridge:
            async def read_photo(
                self,
                value: str,
                *,
                expected_mode: str | None = None,
            ) -> CompanionPagePhoto:
                assert value == photo_ref
                assert expected_mode is None
                return photo

        class RawResponse:
            def __init__(self) -> None:
                self.headers: dict[str, str] = {}

        async def fake_send_file(stream: Any, *, mimetype: str) -> RawResponse:
            assert stream.read() == PNG
            assert mimetype == "image/png"
            return RawResponse()

        page = PluginPageApi(SimpleNamespace(service=SimpleNamespace()))
        page._companion_page_bridge = StubBridge()
        monkeypatch.setattr(
            page_api_module,
            "request",
            SimpleNamespace(args={"ref": photo_ref}, method="GET"),
        )
        monkeypatch.setattr(page_api_module, "send_file", fake_send_file)
        monkeypatch.setattr(
            page_api_module,
            "jsonify",
            lambda body: _JsonResponse(body),
        )

        raw = await page.companion_personal_photo()
        data = await page.companion_personal_photo_data()

        assert raw.headers["Cache-Control"] == "private, no-store"
        assert data.headers["Cache-Control"] == "private, no-store"
        assert data["data_url"] == (
            f"data:image/png;base64,{base64.b64encode(PNG).decode('ascii')}"
        )

    asyncio.run(run())
