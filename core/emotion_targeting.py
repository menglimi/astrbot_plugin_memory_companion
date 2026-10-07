"""Validate memory-event attribution against the active visibility domain."""

from __future__ import annotations

from typing import Any

from .models import clean_text


def memory_emotion_refs(memory: Any, ctx: Any) -> dict[str, dict[str, str]] | None:
    memory_session = clean_text(getattr(memory, "session_id", ""), 220)
    current_session = clean_text(getattr(ctx, "session_id", ""), 220)
    memory_scope = clean_text(getattr(memory, "scope", ""), 24).lower()
    current_scope = clean_text(getattr(ctx, "scope", ""), 24).lower()
    memory_platform = clean_text(getattr(memory, "platform", ""), 80)
    current_platform = clean_text(getattr(ctx, "platform", ""), 80)
    user_id = clean_text(getattr(ctx, "user_id", ""), 160)
    bot_id = clean_text(getattr(ctx, "bot_id", ""), 160)
    if (
        not all((memory_session, current_session, memory_platform, current_platform, user_id))
        or memory_session != current_session
        or memory_scope != "private"
        or current_scope != "private"
        or memory_platform != current_platform
    ):
        return None
    subject = getattr(memory, "subject", None)
    subject_kind = clean_text(getattr(subject, "kind", ""), 24)
    subject_id = clean_text(getattr(subject, "id", ""), 160)
    if subject_kind != "user" or subject_id != user_id:
        return None
    metadata = getattr(memory, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    owner_bot_id = clean_text(metadata.get("owner_bot_id"), 160)
    target = getattr(memory, "object", None)
    target_kind = clean_text(getattr(target, "kind", ""), 24)
    target_id = clean_text(getattr(target, "id", ""), 160)
    if bot_id:
        if owner_bot_id:
            if owner_bot_id not in {"self", bot_id}:
                return None
        elif target_kind != "bot" or target_id != bot_id:
            return None
        expected_bot_id = bot_id
    else:
        # Without a runtime ID, only the context-bound self sentinel is verifiable.
        if owner_bot_id not in {"", "self"} or target_kind != "bot" or target_id != "self":
            return None
        expected_bot_id = "self"
    if target_id and (
        (target_kind == "bot" and target_id not in {expected_bot_id, "self" if owner_bot_id == "self" else expected_bot_id})
        or (target_kind == "user" and target_id != user_id)
        or target_kind not in {"bot", "user"}
    ):
        return None
    return {
        "actor_ref": {"kind": "user", "id": subject_id, "role": clean_text(getattr(subject, "role", ""), 40)},
        "target_ref": {"kind": "bot", "id": expected_bot_id, "role": "bot_self"},
        "quoted_target_ref": {"kind": "unknown", "id": "", "role": ""},
    }


__all__ = ["memory_emotion_refs"]
