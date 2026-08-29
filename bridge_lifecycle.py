# -*- coding: utf-8 -*-
"""Process-stable publication for the optional cross-plugin Memory bridge."""
from __future__ import annotations

import itertools
import sys
import threading
from types import ModuleType
from typing import Any


_RUNTIME_KEY = "_astrbot_memory_companion_bridge_runtime_v1"


def _new_runtime_registry() -> ModuleType:
    registry = ModuleType(_RUNTIME_KEY)
    registry.lock = threading.RLock()
    registry.active_bridge = None
    registry.active_generation = None
    registry.instance_generations = itertools.count(1)
    return registry


_runtime_registry = sys.modules.setdefault(_RUNTIME_KEY, _new_runtime_registry())


def _activate_bridge(bridge: Any) -> None:
    activator = getattr(bridge, "_activate", None)
    if not callable(activator):
        activator = getattr(bridge, "activate", None)
    if not callable(activator):
        raise RuntimeError("memory_bridge_activation_unavailable")
    activator()


def next_bridge_generation() -> int:
    with _runtime_registry.lock:
        return next(_runtime_registry.instance_generations)


def get_published_bridge() -> Any | None:
    with _runtime_registry.lock:
        return _runtime_registry.active_bridge


def publish_bridge(bridge: Any, *, enabled: bool) -> Any | None:
    """Publish only a ready bridge and revoke the superseded generation."""
    with _runtime_registry.lock:
        previous = _runtime_registry.active_bridge
        if enabled:
            if previous is not None and previous is not bridge:
                previous.deactivate()
            try:
                _activate_bridge(bridge)
            except BaseException:
                if previous is not None and previous is not bridge:
                    _activate_bridge(previous)
                raise
            _runtime_registry.active_bridge = bridge
            _runtime_registry.active_generation = getattr(
                bridge,
                "_instance_generation",
                None,
            )
            return bridge

        bridge.deactivate()
        if previous is not None and previous is not bridge:
            previous.deactivate()
        _runtime_registry.active_bridge = None
        _runtime_registry.active_generation = None
        return None


def revoke_bridge(bridge: Any) -> None:
    """Revoke one instance without allowing an old terminate to clear a new one."""
    with _runtime_registry.lock:
        bridge.deactivate()
        if _runtime_registry.active_bridge is bridge:
            _runtime_registry.active_bridge = None
            _runtime_registry.active_generation = None
