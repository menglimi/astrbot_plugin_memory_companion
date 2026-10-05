from __future__ import annotations

from core import bot_personal_contract
from core.capability_probe import (
    CAPABILITY_STATES,
    PROFILE_NAMES,
    CapabilityCache,
    build_capability_snapshot,
    detect_companion_plugin,
)


def test_snapshot_uses_contract_fingerprint_windows_and_types():
    snapshot = build_capability_snapshot()
    assert snapshot["contract_fingerprint"] == bot_personal_contract.CONTRACT_FINGERPRINT
    assert snapshot["windows"] == list(bot_personal_contract.WINDOW_SLUGS)
    assert snapshot["memory_types"] == list(bot_personal_contract.BOT_PERSONAL_MEMORY_TYPES)
    assert set(snapshot) == {
        "available", "state", "degraded", "pending", "contract_fingerprint",
        "contract_version", "schema_version", "windows", "memory_types", "domains",
        "profiles", "methods", "warnings", "error_code",
        "companion_installed", "companion_plugin_name",
    }


def test_snapshot_never_claims_the_companion_on_its_own():
    """快照是纯函数，自己不探测运行时，所以默认值必须是保守的「未装」。"""
    for snapshot in (build_capability_snapshot(), build_capability_snapshot(available=True)):
        assert snapshot["companion_installed"] is False
        assert snapshot["companion_plugin_name"] == ""


def test_detect_companion_plugin_reports_not_installed_when_absent(monkeypatch):
    import importlib

    import core.capability_probe as probe

    def missing(name, *args, **kwargs):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(probe.importlib, "import_module", missing)
    assert detect_companion_plugin() == {
        "companion_installed": False,
        "companion_plugin_name": "",
    }


def test_detect_companion_plugin_requires_an_active_api(monkeypatch):
    """模块能 import 不等于能用：入口返回 None 或抛异常时都必须报「未装」。

    原缺陷：面板把「记忆侧 contract 自检通过」当成「陪伴插件已安装」，
    于是在根本没装 astrbot_plugin_private_companion 的宿主上也显示「已连接」。
    """
    import types

    import core.capability_probe as probe

    module = types.ModuleType("astrbot_plugin_private_companion.main")
    for behaviour in (lambda: None, lambda: (_ for _ in ()).throw(RuntimeError("boom"))):
        module.get_private_companion_api = behaviour
        monkeypatch.setattr(
            probe.importlib,
            "import_module",
            lambda name, _m=module: _m,
        )
        assert detect_companion_plugin()["companion_installed"] is False

    module.get_private_companion_api = lambda: object()
    found = detect_companion_plugin()
    assert found["companion_installed"] is True
    assert found["companion_plugin_name"] == probe.COMPANION_PLUGIN_ID


def test_initial_cache_is_unprobed_and_pending():
    snapshot = CapabilityCache().snapshot()
    assert snapshot["state"] == "unprobed"
    assert snapshot["pending"] is True
    assert snapshot["available"] is False


def test_available_degraded_and_negative_states_are_observable():
    cache = CapabilityCache()
    available = cache.mark_available({"methods": ["search", "search"], "profiles": PROFILE_NAMES})
    assert available["state"] == "available"
    assert available["available"] is True
    assert available["degraded"] is False

    degraded = cache.mark_degraded("contract_invalid")
    assert degraded["state"] == "degraded"
    assert degraded["degraded"] is True
    assert degraded["error_code"] == "contract_invalid"

    negative = cache.mark_negative("bridge_missing")
    assert negative["state"] == "negative"
    assert negative["available"] is False
    assert negative["pending"] is False
    assert negative["degraded"] is True
    assert negative["error_code"] == "bridge_missing"


def test_negative_ttl_returns_to_unprobed_after_expiry():
    now = [10.0]
    cache = CapabilityCache(negative_ttl=5, clock=lambda: now[0])
    cache.mark_negative("not_ready")
    assert cache.snapshot()["state"] == "negative"
    now[0] = 14.99
    assert cache.snapshot()["state"] == "negative"
    now[0] = 15.0
    assert cache.snapshot()["state"] == "unprobed"


def test_snapshot_is_a_deep_copy():
    cache = CapabilityCache()
    value = cache.snapshot()
    value["windows"].append("mutated")
    value["warnings"].append("mutated")
    fresh = cache.snapshot()
    assert "mutated" not in fresh["windows"]
    assert "mutated" not in fresh["warnings"]


def test_malformed_contract_module_is_safe():
    class Broken:
        def __getattribute__(self, _name):
            raise RuntimeError("broken contract")

    snapshot = build_capability_snapshot(
        available=True,
        contract_module=Broken(),
        profiles=[*PROFILE_NAMES, "not-a-profile", "not-a-profile"],
        methods=["search", "search", object()],
    )
    assert snapshot["state"] == "available"
    assert snapshot["available"] is True
    assert snapshot["profiles"] == list(PROFILE_NAMES)
    assert all(isinstance(value, (str, int, float, bool, list, dict)) or value is None
               for value in snapshot.values())


def test_public_state_constants_are_closed():
    assert set(CAPABILITY_STATES) == {"unprobed", "available", "degraded", "negative"}
    assert len(PROFILE_NAMES) == 5
    assert len(set(PROFILE_NAMES)) == 5
