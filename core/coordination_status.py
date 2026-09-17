"""Allowlist-only coordination status for the Memory page.

This projection is observational. It never returns memory text, identity
values, session identifiers, audit bodies, provider details, or handles.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

try:
    from .p5c_guard import P5C_SINK_FLAGS
except ImportError:
    P5C_SINK_FLAGS = {}
try:
    from .p5d_security_events import P5D_OPERATION_FLAGS
except ImportError:
    P5D_OPERATION_FLAGS = {}

from .p6_four_package_manifest import FOUR_PACKAGE_IDS, manifest_contract
from .p6_readonly_projection import P6_READONLY_STATUS_FINGERPRINT, P6_READONLY_STATUS_SCHEMA


COORDINATION_STATUS_SCHEMA = "ops.memory.coordination_status.v1"
# Closed field contract for the coordination projection.  ``build_coordination_status``
# returns exactly these keys, so page consumers can rely on the declaration instead of
# guessing (``contract`` / ``compatibility_level`` were never part of it).
COORDINATION_STATUS_FIELDS = (
    "schema_version",
    "contract_fingerprint",
    "health",
    "reason_code",
    "page_api",
    "runtime",
    "bridge",
    "p5",
    "p6",
    "four_package",
)
_HEALTH = frozenset({"ready", "degraded", "unverifiable"})
_P5_B_FLAGS = (
    "enable_p5_b1_recall_gate",
    "enable_p5_b1_bridge_gate",
    "enable_p5_b1_tool_recall_gate",
    "enable_p5_b2_archive_read_gate",
    "enable_p5_b2_cross_user_read_gate",
)
_P6_FIELDS = ("profiles", "identity_links", "audit_events", "operations")
_P6_REASON_CODES = frozenset({"", "registry_status_unavailable", "invalid_reason_code"})
_BRIDGE_REASON_CODES = frozenset({
    "bridge_status_unavailable",
    "bridge_config_unavailable",
    "bridge_config_unreadable",
    "bridge_config_invalid",
    "bridge_disabled",
    "companion_api_unavailable",
    "companion_p6_producer_unavailable",
    "companion_p6_producer_unreadable",
    "companion_p6_unverifiable",
    "companion_bridge_available",
})


def _has_exact_str_fields(value: dict[Any, Any], fields: frozenset[str]) -> bool:
    if len(value) != len(fields):
        return False
    for key in value:
        if type(key) is not str or key not in fields:
            return False
    return True


def _fingerprint() -> str:
    payload = {"schema_version": COORDINATION_STATUS_SCHEMA, "sections": ("page_api", "runtime", "bridge", "p5", "p6", "four_package")}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


COORDINATION_STATUS_FINGERPRINT = _fingerprint()


def _status(health: str, reason_code: str) -> dict[str, str]:
    return {
        "health": health if type(health) is str and health in _HEALTH else "unverifiable",
        "reason_code": reason_code if type(reason_code) is str and len(reason_code) <= 80 else "status_unavailable",
    }


def _project_bridge_status(raw: Any) -> dict[str, str]:
    if type(raw) is not dict or not _has_exact_str_fields(raw, frozenset({"health", "reason_code"})):
        return _status("unverifiable", "bridge_status_unavailable")
    health = raw.get("health")
    reason_code = raw.get("reason_code")
    if type(health) is not str or health not in _HEALTH:
        return _status("unverifiable", "bridge_status_unavailable")
    if type(reason_code) is not str or reason_code not in _BRIDGE_REASON_CODES:
        return _status("unverifiable", "bridge_status_unavailable")
    return _status(health, reason_code)


def _unavailable_group(total_count: int) -> dict[str, Any]:
    return {"health": "unverifiable", "mode": "unavailable", "enabled_count": 0, "total_count": total_count, "reason_code": "contract_not_available"}


def _config_group(config: Any, flags: tuple[str, ...], *, fallback_flags: tuple[str, ...] = ()) -> dict[str, Any]:
    if not flags:
        return _unavailable_group(0)
    getter = getattr(config, "bool", None)
    if not callable(getter):
        return {"health": "unverifiable", "mode": "unverifiable", "enabled_count": 0, "total_count": len(flags), "reason_code": "config_unavailable"}
    values: list[bool] = []
    for index, flag in enumerate(flags):
        try:
            value = getter(flag, False)
            if type(value) is not bool:
                return {"health": "unverifiable", "mode": "unverifiable", "enabled_count": 0, "total_count": len(flags), "reason_code": "config_value_invalid"}
            if value is False and fallback_flags:
                fallback = getter(fallback_flags[index], False)
                if type(fallback) is not bool:
                    return {"health": "unverifiable", "mode": "unverifiable", "enabled_count": 0, "total_count": len(flags), "reason_code": "config_value_invalid"}
                value = fallback
        except Exception:
            return {"health": "unverifiable", "mode": "unverifiable", "enabled_count": 0, "total_count": len(flags), "reason_code": "config_unreadable"}
        values.append(value)
    enabled_count = sum(values)
    if enabled_count == 0:
        return {"health": "ready", "mode": "default_off", "enabled_count": 0, "total_count": len(flags), "reason_code": "default_off"}
    if enabled_count == len(flags):
        return {"health": "ready", "mode": "enabled", "enabled_count": enabled_count, "total_count": len(flags), "reason_code": "configured"}
    return {"health": "degraded", "mode": "partial", "enabled_count": enabled_count, "total_count": len(flags), "reason_code": "partial_coverage"}


def build_p5_status(config: Any) -> dict[str, dict[str, Any]]:
    return {
        "attestation_read": _config_group(config, _P5_B_FLAGS),
        "sink_boundary": _config_group(config, tuple(f"p5c_safety.{flag}" for flag in P5C_SINK_FLAGS.values()), fallback_flags=tuple(P5C_SINK_FLAGS.values())),
        "security_recovery": _config_group(config, tuple(f"p5d_safety.{flag}" for flag in P5D_OPERATION_FLAGS.values()), fallback_flags=tuple(P5D_OPERATION_FLAGS.values())),
    }


def project_runtime_health(runtime: Any) -> dict[str, str]:
    try:
        if type(runtime) is dict:
            for key in runtime:
                if type(key) is not str:
                    return _status("unverifiable", "runtime_unsupported")
            if len(runtime) != 1 or "compatibility_level" not in runtime:
                return _status("unverifiable", "runtime_unsupported")
            level = runtime.get("compatibility_level")
        else:
            level = getattr(runtime, "compatibility_level", None)
    except Exception:
        return _status("unverifiable", "runtime_status_unavailable")
    if type(level) is not str:
        return _status("unverifiable", "runtime_unsupported")
    if level == "full":
        return _status("ready", "runtime_compatible")
    if level == "degraded":
        return _status("degraded", "runtime_degraded")
    return _status("unverifiable", "runtime_unsupported")


def project_p6_status(raw: Any) -> dict[str, Any]:
    fallback = {
        "schema_version": P6_READONLY_STATUS_SCHEMA,
        "contract_fingerprint": P6_READONLY_STATUS_FINGERPRINT,
        "health": "unverifiable",
        "reason_code": "p6_status_unavailable",
        "counts": {field: 0 for field in _P6_FIELDS},
    }
    if type(raw) is not dict or not _has_exact_str_fields(raw, frozenset({"schema_version", "source_plugin", "contract_fingerprint", "health", "reason_code", "counts"})):
        return fallback
    schema_version = raw.get("schema_version")
    source_plugin = raw.get("source_plugin")
    contract_fingerprint = raw.get("contract_fingerprint")
    if (
        type(schema_version) is not str
        or type(source_plugin) is not str
        or type(contract_fingerprint) is not str
        or schema_version != P6_READONLY_STATUS_SCHEMA
        or source_plugin != "private_companion"
        or contract_fingerprint != P6_READONLY_STATUS_FINGERPRINT
    ):
        return fallback
    health, reason_code, counts = raw.get("health"), raw.get("reason_code"), raw.get("counts")
    if type(health) is not str or health not in _HEALTH:
        return fallback
    if type(reason_code) is not str or reason_code not in _P6_REASON_CODES:
        return fallback
    if type(counts) is not dict or not _has_exact_str_fields(counts, frozenset(_P6_FIELDS)):
        return fallback
    if any(type(counts[field]) is not int or not 0 <= counts[field] <= 10_000_000 for field in _P6_FIELDS):
        return fallback
    return {
        "schema_version": P6_READONLY_STATUS_SCHEMA,
        "contract_fingerprint": P6_READONLY_STATUS_FINGERPRINT,
        "health": health,
        "reason_code": reason_code,
        "counts": {field: counts[field] for field in _P6_FIELDS},
    }


def build_coordination_status(*, config: Any, runtime: Any, bridge: dict[str, str], p6_raw: Any) -> dict[str, Any]:
    p5 = build_p5_status(config)
    p6 = project_p6_status(p6_raw)
    manifest = manifest_contract()
    bridge_status = _project_bridge_status(bridge)
    components = [project_runtime_health(runtime), bridge_status, {"health": p6["health"], "reason_code": p6["reason_code"]}]
    if any(item["health"] == "unverifiable" for item in components):
        health, reason_code = "unverifiable", "coordination_input_unverifiable"
    elif any(item["health"] == "degraded" for item in components):
        health, reason_code = "degraded", "coordination_degraded"
    else:
        health, reason_code = "ready", "coordination_ready"
    result = {
        "schema_version": COORDINATION_STATUS_SCHEMA,
        "contract_fingerprint": COORDINATION_STATUS_FINGERPRINT,
        "health": health,
        "reason_code": reason_code,
        "page_api": _status("ready", "page_api_registered"),
        "runtime": project_runtime_health(runtime),
        "bridge": bridge_status,
        "p5": p5,
        "p6": p6,
        "four_package": {
            "schema_version": manifest["schema"],
            "contract_fingerprint": manifest["contract_fingerprint"],
            "health": "unverifiable",
            "reason_code": "manifest_registry_unavailable",
            "expected_package_count": len(FOUR_PACKAGE_IDS),
        },
    }
    return {key: result[key] for key in COORDINATION_STATUS_FIELDS}


__all__ = ["COORDINATION_STATUS_FIELDS", "COORDINATION_STATUS_FINGERPRINT", "COORDINATION_STATUS_SCHEMA", "build_coordination_status", "build_p5_status", "project_p6_status", "project_runtime_health"]
