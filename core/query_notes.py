"""Optional, source-bound model statements in the existing query turn state.

Receipt validation never certifies meaning and never calls a semantic model.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import secrets
import time
from typing import Any

from .models import json_dumps


PROFILE = "memory.local-query-session.v2"
CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "docs/contracts/query-session/v2"
MAX_NOTE_BYTES = 6144
MAX_LOG_BYTES = 16384
MAX_RECORDS = 24


def enabled(service: Any) -> bool:
    return (service.config.bool("memory_tools.enable_query_progress", True)
            and service.config.bool("memory_tools.enable_query_notes", True))


@lru_cache(maxsize=2)
def schema(name: str) -> dict[str, Any]:
    return json.loads((CONTRACT_ROOT / "schemas" / (name + ".schema.json")).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def note_validator():
    from jsonschema import Draft202012Validator
    return Draft202012Validator(schema("request")["properties"]["query_note"])


def status_parameters() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": {
        "note_ids": {"type": "array", "maxItems": MAX_RECORDS, "uniqueItems": True,
                     "items": {"type": "string", "pattern": "^qn_[a-f0-9]{16}$"}},
    }}


def unavailable_view() -> dict[str, Any]:
    return {"state": "unavailable", "available": 0, "withheld": 0, "omitted": 0, "items": []}


def _valid(record: dict[str, Any], versions: tuple[str, str], now: float) -> bool:
    return (record["status"] == "active" and record["expires_at"] > now
            and (record["source_revision"], record["policy_revision"]) == versions)


def _retire(record: dict[str, Any], status: str) -> None:
    record["status"] = status
    # Keep opaque receipt metadata for retries, not the statement or citations.
    for name in ("text", "evidence", "replaces"):
        record.pop(name, None)


def prune(state: dict[str, Any], versions: tuple[str, str], now: float) -> None:
    for record in state.get("query_notes", {}).get("items", []):
        if record["status"] == "active" and not _valid(record, versions, now):
            _retire(record, "unavailable")


def trim_history(state: dict[str, Any]) -> None:
    """Called under the query lock; statements and completed calls share 16 KiB."""
    ledger = state.get("query_progress", {})
    notes = state.get("query_notes", {})
    operations, items = ledger.get("operations", []), notes.get("items", [])
    while (len(operations) > MAX_RECORDS or len(items) > MAX_RECORDS
           or len(json_dumps([operations, items]).encode("utf-8")) > MAX_LOG_BYTES):
        retired = next((i for i, row in enumerate(items) if row["status"] != "active"), None)
        if len(items) > MAX_RECORDS or (retired is not None and len(operations) <= MAX_RECORDS):
            items.pop(retired if retired is not None else 0)
            notes["omitted"] = notes.get("omitted", 0) + 1
        elif operations:
            operations.pop(0)
            ledger["omitted_operations"] = ledger.get("omitted_operations", 0) + 1
        elif items:
            items.pop(0)
            notes["omitted"] = notes.get("omitted", 0) + 1
        else:
            break


async def accept(service: Any, event: Any, ctx: Any, value: Any) -> dict[str, Any]:
    """Accept before the next query, using only sources already returned."""
    if value is None:
        return {"status": "not_submitted"}
    rejected = lambda error: {"status": "rejected", "error": error}
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_NOTE_BYTES or not note_validator().is_valid(value):
            return rejected("invalid_query_note")
        if not value["text"].strip() or "\x00" in value["text"]:
            return rejected("invalid_query_note")
    except (TypeError, ValueError, RecursionError):
        return rejected("invalid_query_note")
    if not enabled(service):
        return rejected("query_notes_disabled")
    key = service._reconstruction_budget_key(event, ctx)
    async with service._reconstruction_lock:
        state = service._reconstruction_states.get(key)
        if not state or not state.get("query_progress"):
            return rejected("source_not_read")
        issued = state.get("issued_sources", {})
        evidence = []
        for citation in value["evidence"]:
            receipt = issued.get(citation["source_ref"])
            if not receipt or receipt["source_version"] != citation["source_version"]:
                return rejected("source_unavailable")
            evidence.append({**deepcopy(receipt), "source_ref": citation["source_ref"]})
    # One metadata read after taking the receipts; never read message text again.
    versions = await service.store.query_progress_revisions()
    async with service._reconstruction_lock:
        now = time.monotonic()
        if (service._reconstruction_states.get(key) is not state or service._closing or service._closed
                or not enabled(service) or not service._scope_feature_enabled(ctx, "recall")
                or now - state.get("last_seen", 0) > service._RECONSTRUCTION_STATE_TTL):
            return rejected("query_notes_unavailable")
        for receipt in evidence:
            current = state.get("issued_sources", {}).get(receipt["source_ref"], {})
            if (receipt["expires_at"] <= now
                    or (receipt["source_revision"], receipt["policy_revision"]) != versions
                    or any(current.get(k) != receipt[k] for k in
                           ("source_version", "source_revision", "policy_revision", "expires_at"))):
                return rejected("source_unavailable")
        prune(state, versions, now)
        ledger = state.setdefault("query_notes", {"revision": 0, "items": [], "omitted": 0})
        # Include the original grant expiry so re-reading cannot revive an old note.
        fingerprint = hashlib.sha256(json_dumps({
            "text": value["text"], "replaces": sorted(value.get("replaces", [])),
            "evidence": sorted([{k: r[k] for k in ("source_ref", "source_version", "source_revision",
                                                   "policy_revision", "expires_at")} for r in evidence],
                               key=lambda r: r["source_ref"]),
        }).encode("utf-8")).hexdigest()
        previous = next((r for r in ledger["items"] if r["fingerprint"] == fingerprint), None)
        if previous:
            return ({"status": "reused", "id": previous["id"], "revision": previous["revision"]}
                    if _valid(previous, versions, now) else rejected("note_no_longer_current"))
        targets = []
        for identifier in value.get("replaces", []):
            target = next((r for r in ledger["items"] if r["id"] == identifier), None)
            if target is None or target["status"] != "active":
                return rejected("note_replacement_conflict")
            targets.append(target)
        ledger["revision"] += 1
        record = {"id": "qn_" + secrets.token_hex(8), "revision": ledger["revision"], "status": "active",
                  "text": value["text"], "fingerprint": fingerprint,
                  "source_revision": versions[0], "policy_revision": versions[1],
                  "expires_at": min(r["expires_at"] for r in evidence),
                  "replaces": list(value.get("replaces", [])),
                  "evidence": [{"source_ref": r["source_ref"], "source_version": r["source_version"],
                                "spans": [list(span) for span in r["spans"]]} for r in evidence]}
        # A single record must fit without truncating text or its dependencies.
        if len(json_dumps([[], [record]]).encode("utf-8")) > MAX_LOG_BYTES:
            return rejected("query_note_capacity_exceeded")
        for target in targets:
            _retire(target, "superseded")
        ledger["items"].append(record)
        trim_history(state)
        return {"status": "accepted", "id": record["id"], "revision": record["revision"]}


def view(state: dict[str, Any], versions: tuple[str, str], *, detail: bool,
         note_ids: list[str] | None = None, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    """Under the original query lock; no I/O, renewal or text inference."""
    now = time.monotonic()
    prune(state, versions, now)
    ledger = state.get("query_notes", {})
    records = ledger.get("items", [])
    active = [r for r in records if _valid(r, versions, now)]
    if receipt and receipt.get("id") and not any(r["id"] == receipt["id"] for r in active):
        receipt.update(status="unavailable", error="note_no_longer_current")
    chosen = [r for r in active if note_ids is None or r["id"] in note_ids] if detail else []
    return {"state": "ready" if ledger else "empty", "available": len(active),
            "withheld": len(records) - len(active), "omitted": ledger.get("omitted", 0),
            "items": [{"id": r["id"], "revision": r["revision"], "text": r["text"],
                       "semantic_status": "model_interpretation", "source_status": "receipts_valid",
                       "evidence": deepcopy(r["evidence"]), "replaces": list(r["replaces"]),
                       "expires_in_seconds": max(0, round(r["expires_at"] - now, 1))} for r in chosen]}


def bound_display(result: dict[str, Any], *, detail: bool) -> None:
    """Share A's display cap. The original owner result is never shortened."""
    fields = {k: result[k] for k in ("progress", "note_receipt", "notes")}
    cap = 12000 if detail else 900
    for owner, field in ((result["progress"], "sources"), (result["progress"], "cursors"),
                         (result["progress"], "recent"), (result["notes"], "items")):
        while owner.get(field) and len(json_dumps(fields)) > cap:
            owner[field].pop(0)
            if owner is result["notes"]:
                owner["omitted"] += 1
            else:
                owner["display_omitted"] = owner.get("display_omitted", 0) + 1
