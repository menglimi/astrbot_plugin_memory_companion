from __future__ import annotations

import ast
import importlib
from pathlib import Path

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


PLUGIN_ROOT = bootstrap_package()

from astrbot_plugin_memory_companion import bridge_lifecycle
from astrbot_plugin_memory_companion.core.bridge import MemoryCompanionBridge


class _FakeBridge:
    def __init__(self, generation: int, *, fail_activate: bool = False) -> None:
        self._instance_generation = generation
        self.active = False
        self.activate_calls = 0
        self.deactivate_calls = 0
        self.fail_activate = fail_activate

    def activate(self) -> None:
        self.activate_calls += 1
        if self.fail_activate:
            raise RuntimeError("activation-failed")
        self.active = True

    def deactivate(self) -> None:
        self.deactivate_calls += 1
        self.active = False


def _reset_registry() -> None:
    registry = bridge_lifecycle._runtime_registry
    with registry.lock:
        current = registry.active_bridge
        if current is not None:
            current.deactivate()
        registry.active_bridge = None
        registry.active_generation = None


def test_bridge_begins_inactive_until_explicit_activation() -> None:
    bridge = MemoryCompanionBridge(
        object(),
        active=False,
        instance_generation=7,
    )

    assert bridge.bridge_lifecycle_status() == {
        "active": False,
        "state": "inactive",
        "instance_generation": 7,
    }

    bridge_lifecycle.publish_bridge(bridge, enabled=True)
    assert bridge.bridge_lifecycle_status()["active"] is True
    bridge_lifecycle.revoke_bridge(bridge)


def test_publication_atomically_revokes_superseded_generation() -> None:
    _reset_registry()
    first = _FakeBridge(1)
    second = _FakeBridge(2)

    assert bridge_lifecycle.publish_bridge(first, enabled=True) is first
    assert bridge_lifecycle.get_published_bridge() is first

    assert bridge_lifecycle.publish_bridge(second, enabled=True) is second
    assert first.active is False
    assert first.deactivate_calls == 1
    assert second.active is True
    assert bridge_lifecycle.get_published_bridge() is second
    assert bridge_lifecycle._runtime_registry.active_generation == 2

    bridge_lifecycle.revoke_bridge(first)
    assert bridge_lifecycle.get_published_bridge() is second

    bridge_lifecycle.revoke_bridge(second)
    assert bridge_lifecycle.get_published_bridge() is None


def test_disabled_generation_revokes_existing_publication() -> None:
    _reset_registry()
    previous = _FakeBridge(3)
    disabled = _FakeBridge(4)
    bridge_lifecycle.publish_bridge(previous, enabled=True)

    assert bridge_lifecycle.publish_bridge(disabled, enabled=False) is None
    assert previous.active is False
    assert disabled.active is False
    assert bridge_lifecycle.get_published_bridge() is None


def test_activation_failure_restores_previous_publication() -> None:
    _reset_registry()
    previous = _FakeBridge(6)
    failed = _FakeBridge(7, fail_activate=True)
    bridge_lifecycle.publish_bridge(previous, enabled=True)

    try:
        bridge_lifecycle.publish_bridge(failed, enabled=True)
    except RuntimeError as exc:
        assert str(exc) == "activation-failed"
    else:
        raise AssertionError("activation failure must escape")

    assert previous.active is True
    assert failed.active is False
    assert bridge_lifecycle.get_published_bridge() is previous
    bridge_lifecycle.revoke_bridge(previous)


def test_runtime_registry_survives_module_reload() -> None:
    _reset_registry()
    bridge = _FakeBridge(5)
    bridge_lifecycle.publish_bridge(bridge, enabled=True)
    registry = bridge_lifecycle._runtime_registry

    reloaded = importlib.reload(bridge_lifecycle)

    assert reloaded._runtime_registry is registry
    assert reloaded.get_published_bridge() is bridge
    reloaded.revoke_bridge(bridge)


def test_plugin_constructor_cannot_publish_cross_plugin_bridge() -> None:
    tree = ast.parse((Path(PLUGIN_ROOT) / "main.py").read_text(encoding="utf-8"))
    plugin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MemoryCompanionPlugin"
    )
    methods = {
        node.name: node
        for node in plugin.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    constructor_calls = {
        node.func.id
        for node in ast.walk(methods["__init__"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    initialize_calls = {
        node.func.id
        for node in ast.walk(methods["initialize"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "publish_bridge" not in constructor_calls
    assert "publish_bridge" in initialize_calls
