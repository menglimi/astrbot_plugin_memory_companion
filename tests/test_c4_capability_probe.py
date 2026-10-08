from __future__ import annotations

from types import ModuleType, SimpleNamespace

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


def _api(active=True):
    return SimpleNamespace(bridge_lifecycle_status=lambda: {"active": active})


def _star(name, display="", activated=True, ext=_api(), module=None):
    return SimpleNamespace(
        name=name,
        display_name=display,
        activated=activated,
        star_cls=SimpleNamespace(extension_api=ext) if ext is not None else None,
        module=module,
    )


def _ctx(stars, registered=None):
    def reg(name):
        return registered if name == "astrbot_plugin_private_companion" else None

    return SimpleNamespace(get_all_stars=lambda: list(stars), get_registered_star=reg)


COMPANION = "astrbot_plugin_private_companion"
OURS = "astrbot_plugin_memory_companion"


def test_detect_finds_a_live_companion_in_the_host_registry():
    """装了且启用 -> 报已装。这是 2.2.1 之前判错的方向。

    之前只用 ``importlib.import_module("data.plugins.…")`` 去 import，而 AstrBot
    并不保证插件模块以这个别名留在 ``sys.modules`` 里，于是真装了也报未装。
    正确做法是问宿主注册表要**当前活着的实例**。
    """
    for label, context in (
        ("get_all_stars", _ctx([_star(COMPANION, "我会永远陪着你")])),
        ("root_dir_name", _ctx([SimpleNamespace(root_dir_name=COMPANION, activated=True,
                                               star_cls=SimpleNamespace(extension_api=_api()),
                                               module=None)])),
        ("get_registered_star", _ctx([_star(OURS, "我会牢牢记住你")],
                                     registered=_star(COMPANION))),
        ("only get_all_stars", SimpleNamespace(get_all_stars=lambda: [_star(COMPANION)])),
    ):
        found = detect_companion_plugin(context)
        assert found["companion_installed"] is True, label
        assert found["companion_plugin_name"] == COMPANION, label


def test_detect_uses_the_companions_own_module_entry_point():
    module = ModuleType("data.plugins.astrbot_plugin_private_companion.main")
    module.get_private_companion_api = lambda: _api(True)
    found = detect_companion_plugin(_ctx([_star(COMPANION, "x", module=module)]))
    assert found["companion_installed"] is True


def test_detect_reports_absent_when_the_registry_has_no_companion():
    """注册表可用却没找到 = 真的没装。"""
    found = detect_companion_plugin(_ctx([_star(OURS, "我会牢牢记住你")]))
    assert found == {"companion_installed": False, "companion_plugin_name": ""}


def test_detect_ignores_a_disabled_or_inactive_companion():
    disabled = detect_companion_plugin(_ctx([_star(COMPANION, "w", activated=False)]))
    assert disabled["companion_installed"] is False, "装了但没启用不算可用"
    inactive = detect_companion_plugin(_ctx([_star(COMPANION, "w", ext=_api(active=False))]))
    assert inactive["companion_installed"] is False, "桥接没 active 不算可用"


def test_registry_verdict_beats_a_stale_sys_modules_alias(monkeypatch):
    """插件重载后旧模块会留在 sys.modules 里冒充还在——不能让它翻盘。

    这条是刻意反向设计的：宿主注册表说没有，就是没有。
    """
    stale = ModuleType("data.plugins.astrbot_plugin_private_companion.main")
    stale.get_private_companion_api = lambda: _api(True)
    monkeypatch.setitem(
        __import__("sys").modules, "data.plugins.astrbot_plugin_private_companion.main", stale
    )
    found = detect_companion_plugin(_ctx([_star(OURS, "我会牢牢记住你")]))
    assert found["companion_installed"] is False


def test_modules_are_only_consulted_without_a_registry(monkeypatch):
    """宿主没有注册表 API 时才允许退回模块别名（老版本 AstrBot、单测环境）。

    两种「没有注册表」的形态——压根没有 context，或者 context 上没有那两个方法——
    行为必须一致，否则换个调用点结论就变了。
    """
    stale = ModuleType("astrbot_plugin_private_companion.main")
    stale.get_private_companion_api = lambda: _api(True)
    monkeypatch.setitem(__import__("sys").modules, "astrbot_plugin_private_companion.main", stale)
    for context in (None, object(), SimpleNamespace()):
        assert detect_companion_plugin(context)["companion_installed"] is True, context

    # 一旦宿主给出了注册表 API，模块别名就完全不参与判定
    registry = SimpleNamespace(get_all_stars=lambda: [], get_registered_star=lambda name: None)
    assert detect_companion_plugin(registry)["companion_installed"] is False


def test_public_state_constants_are_closed():
    assert set(CAPABILITY_STATES) == {"unprobed", "available", "degraded", "negative"}
    assert len(PROFILE_NAMES) == 5
    assert len(set(PROFILE_NAMES)) == 5
