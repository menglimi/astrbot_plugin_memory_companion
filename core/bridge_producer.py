from __future__ import annotations

from typing import Any

from . import bot_personal_contract
from .capability_probe import PROFILE_NAMES as C4_PROFILE_NAMES, build_capability_snapshot
from .models import clean_text


class ProducerBridgeFamily:
    """Concrete bridge capability family backed by one façade owner."""

    __slots__ = ("_owner",)

    def __init__(self, owner: Any):
        self._owner = owner

    def probe_capability_snapshot(self) -> dict[str, Any]:
        """Return the C4 capability snapshot without touching plugin state or storage.

        The probe is intentionally based only on the shared contract module. It
        must remain safe to call from ordinary chat paths even when the contract
        is stale or the local module is otherwise malformed.
        """
        if not self._owner._active:
            return self._owner._negative_personal_capability_probe("bridge_inactive")
        if self._owner._capability_cache.snapshot().get("state") == "negative":
            return self._owner.capability_status()
        try:
            descriptor = bot_personal_contract.capability_descriptor(
                available=True,
                read_only=False,
            )
        except Exception:
            return self._owner._negative_personal_capability_probe("contract_descriptor_exception")

        if not isinstance(descriptor, dict):
            return self._owner._negative_personal_capability_probe("contract_descriptor_invalid")

        result = dict(descriptor)
        try:
            problems = bot_personal_contract.contract_self_check()
        except Exception:
            return self._owner._negative_personal_capability_probe(
                "contract_self_check_exception",
                base=result,
            )

        if not isinstance(problems, list):
            return self._owner._negative_personal_capability_probe(
                "contract_self_check_invalid",
                base=result,
            )
        if problems:
            warnings = ["contract_self_check_failed"]
            known_codes = {
                "contract_fingerprint_stale",
                "duplicate_window_slug",
                "type_contracts_out_of_sync",
                "window_coverage_gap",
                "alias_points_to_unknown_window",
            }
            for problem in problems:
                code = str(problem).split(":", 1)[0]
                if code in known_codes and code not in warnings:
                    warnings.append(code)
            return self._owner._negative_personal_capability_probe(
                "contract_self_check_failed",
                base=result,
                warnings=warnings,
            )

        result["available"] = True
        result["state"] = "available"
        result["degraded"] = False
        self._owner._add_personal_capability_contract_aliases(result)
        c4_snapshot = build_capability_snapshot(
            available=True,
            state="available",
            contract_module=bot_personal_contract,
            methods=result.get("methods", []),
            profiles=C4_PROFILE_NAMES,
            warnings=result.get("warnings", []),
        )
        result.update(c4_snapshot)
        result["memory_domain"] = bot_personal_contract.BOT_PERSONAL_MEMORY_DOMAIN
        result["domain"] = bot_personal_contract.BOT_PERSONAL_MEMORY_DOMAIN
        result["contract_revision"] = bot_personal_contract.CONTRACT_REVISION
        result["capability_schema_version"] = bot_personal_contract.BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION
        result["payload_schema_version"] = bot_personal_contract.BOT_PERSONAL_PAYLOAD_SCHEMA_VERSION
        result["capability_state"] = "available"
        # Capability discovery must remain static: callers use it before the
        # plugin service is safe to query, and C1 guarantees no storage access.
        result["p5"] = {"state": "unprobed", "error_code": "p5_status_not_probed"}
        self._owner._capability_cache.mark_available(c4_snapshot)
        result.setdefault("warnings", [])
        return result

    def probe_bot_personal_memory_capabilities(self) -> dict[str, Any]:
        """Backward-compatible C1 probe; C4 state is exposed as capability_state."""

        result = dict(self._owner.probe_capability_snapshot())
        if result.get("capability_state") == "available":
            result["state"] = "ready"
        result["legacy_state"] = result.get("state", "degraded")
        return result

    def capability_status(self) -> dict[str, Any]:
        """Return the bounded C4 cache state without probing storage."""

        snapshot = self._owner._capability_cache.snapshot()
        snapshot["read_only"] = False
        snapshot["contract_name"] = bot_personal_contract.CONTRACT_NAME
        snapshot["max_payload_bytes"] = bot_personal_contract.BOT_PERSONAL_MAX_PAYLOAD_BYTES
        snapshot["memory_domain"] = bot_personal_contract.BOT_PERSONAL_MEMORY_DOMAIN
        snapshot["domain"] = snapshot["memory_domain"]
        snapshot["contract_revision"] = bot_personal_contract.CONTRACT_REVISION
        snapshot["capability_schema_version"] = bot_personal_contract.BOT_PERSONAL_CAPABILITY_SCHEMA_VERSION
        snapshot["payload_schema_version"] = bot_personal_contract.BOT_PERSONAL_PAYLOAD_SCHEMA_VERSION
        snapshot["capability_state"] = snapshot.get("state", "unprobed")
        return snapshot

    def mark_capability_negative(self, reason: str) -> dict[str, Any]:
        """Temporarily suppress repeated capability failures at the bridge edge."""

        self._owner._capability_cache.mark_negative(clean_text(reason, 120) or "capability_negative")
        return self._owner.capability_status()
