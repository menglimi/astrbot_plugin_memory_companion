"""Small, turn-local receipts for source fragments actually returned to a model."""
from __future__ import annotations

from typing import Any
import time
import hashlib
import json

from .models import clean_text


def record_source_read(
    state: dict[str, Any], sources: list[dict[str, Any]], *, source_revision: str,
    policy_revision: str, expires_at: float, coverage: dict[str, Any],
    event: Any = None, ctx: Any = None,
) -> None:
    issued = state.setdefault("issued_sources", {})
    for source in sources:
        ref = source["source_ref"]
        receipt = issued.get(ref)
        if (not receipt or receipt["source_version"] != source["source_version"]
                or receipt["source_revision"] != source_revision or receipt["policy_revision"] != policy_revision
                or receipt["expires_at"] < time.monotonic()):
            receipt = {"source_version": source["source_version"], "spans": [], "expires_at": expires_at}
            issued[ref] = receipt
        span = (source["excerpt_offset"], source["excerpt_end"])
        if span not in receipt["spans"]:
            receipt["spans"].append(span)
        if source.get("next_excerpt_offset") is None:
            receipt["text_length"] = source["excerpt_end"]
        receipt.update(source_revision=source_revision, policy_revision=policy_revision,
                       expires_at=min(receipt["expires_at"], expires_at))
    state.setdefault("source_reads", []).append({
        **coverage, "source_revision": source_revision,
        "policy_revision": policy_revision, "expires_at": expires_at,
        "source_refs": [source["source_ref"] for source in sources],
    })

    if event is not None and ctx is not None:
        remember_source_reads(event, ctx, sources)


def message_source_version(row: dict[str, Any]) -> str:
    """Keep the existing source-query v1 version encoding exactly unchanged."""
    return hashlib.sha256(json.dumps(
        [row.get("content"), row.get("metadata"), clean_text(row.get("occurred_at"), 80), row.get("created_at")],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def read_context(ctx: Any) -> dict[str, Any]:
    return {key: getattr(ctx, key) for key in
            ('session_id', 'scope', 'platform', 'user_id', 'group_id', 'bot_id', 'persona_id', 'strict_session_only')}


def read_context_key(ctx: Any) -> str:
    return hashlib.sha256(json.dumps(read_context(ctx), sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def remember_source_reads(event: Any, ctx: Any, sources: list[dict[str, Any]]) -> None:
    """Exact returned versions for subsequent life writes; no database mutation.

    This event-local provenance is independent of expiring query-page cursors.
    Re-reading a changed source retains both versions that reached this model.
    """
    if not sources:
        return
    key = read_context_key(ctx)
    previous = getattr(event, 'memory_companion_message_sources', {})
    refs = previous.get('refs', []) if previous.get('context') == key else []
    by_ref = {(item['id'], item['version']): item for item in refs}
    for source in sources:
        ref = {'id': source['source_ref'].removeprefix('timeline:'), 'version': source['source_version']}
        by_ref[(ref['id'], ref['version'])] = ref
    setattr(event, 'memory_companion_message_sources', {'context': key, 'refs': list(by_ref.values())})


def remember_reply_sources(event: Any, ctx: Any, sources: list[dict[str, str]]) -> None:
    """Record validated timeline projections, without granting raw-query access."""
    if event is None or not sources:
        return
    key = read_context_key(ctx)
    previous = getattr(event, 'memory_companion_reply_sources', {})
    refs = previous.get('refs', []) if previous.get('context') == key else []
    by_ref = {(item['id'], item['version']): item for item in refs}
    by_ref.update({(item['id'], item['version']): dict(item) for item in sources})
    setattr(event, 'memory_companion_reply_sources', {'context': key, 'refs': list(by_ref.values())})
