from __future__ import annotations

from .models import MemoryRecord, SessionContext


def _clean_id(value: str | None) -> str:
    return (value or "").strip()


class VisibilityPolicy:
    def __init__(
        self,
        *,
        allow_self_timeline_everywhere: bool = True,
        allow_group_public_in_private: bool = False,
        hide_pending_review: bool = True,
        include_raw_events: bool = True,
        enable_acl_rules: bool = True,
        admin_read_all: bool = False,
    ):
        self.allow_self_timeline_everywhere = allow_self_timeline_everywhere
        self.allow_group_public_in_private = allow_group_public_in_private
        self.hide_pending_review = hide_pending_review
        self.include_raw_events = include_raw_events
        self.enable_acl_rules = enable_acl_rules
        self.admin_read_all = admin_read_all

    def is_visible(self, memory: MemoryRecord, ctx: SessionContext) -> tuple[bool, str]:
        if memory.lifecycle == "archived":
            return False, "archived"
        if self.hide_pending_review and memory.review_status == "pending":
            return False, "pending_review"
        if not self.include_raw_events and memory.lifecycle == "raw_event":
            return False, "raw_event_disabled"
        if memory.visibility == "internal":
            return False, "internal"
        if ctx.strict_session_only:
            if not ctx.session_id:
                return False, "strict_session_missing"
            if not memory.session_id or memory.session_id != ctx.session_id:
                return False, "strict_session_mismatch"
        if self.admin_read_all:
            return True, "admin_search"
        if memory.visibility == "bot_self":
            return (self.allow_self_timeline_everywhere, "bot_self")
        if memory.visibility == "shareable":
            return True, "shareable"
        if memory.visibility == "private_pair":
            if memory.session_id and memory.session_id == ctx.session_id:
                return True, "same_private_session"
            if ctx.scope != "private":
                return False, "private_pair_not_current_private"
            ids = {memory.subject.id, memory.object.id}
            if ctx.user_id and ctx.user_id in ids:
                return True, "same_private_user"
            return False, "other_private_pair"
        if memory.visibility == "group_public":
            if ctx.scope == "group" and memory.group_id and memory.group_id == ctx.group_id:
                owner_ok, owner_reason = self._bot_owner_visible(memory, ctx)
                if not owner_ok:
                    return False, owner_reason
                return True, "same_group"
            if ctx.scope == "private" and self.allow_group_public_in_private:
                owner_ok, owner_reason = self._bot_owner_visible(memory, ctx)
                if not owner_ok:
                    return False, owner_reason
                return True, "group_public_allowed_in_private"
            return False, "other_group_public"
        return False, f"unknown_visibility:{memory.visibility}"

    def _bot_owner_visible(self, memory: MemoryRecord, ctx: SessionContext) -> tuple[bool, str]:
        """Keep bot-perspective group memories tied to the bot that produced them."""
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        owner_bot_id = _clean_id(metadata.get("owner_bot_id"))
        bot_entity_ids = {
            _clean_id(entity.id)
            for entity in (memory.subject, memory.object)
            if getattr(entity, "kind", "") == "bot" and _clean_id(getattr(entity, "id", ""))
        }
        specific_bot_ids = {bot_id for bot_id in bot_entity_ids if bot_id != "self"}
        if owner_bot_id and owner_bot_id != "self":
            specific_bot_ids.add(owner_bot_id)
        if not specific_bot_ids:
            if self._is_legacy_group_conversation_summary(memory) and _clean_id(ctx.bot_id):
                return False, "ambiguous_bot_owner"
            return True, "no_specific_bot_owner"
        current_bot_id = _clean_id(ctx.bot_id)
        if current_bot_id and current_bot_id in specific_bot_ids:
            return True, "same_bot_owner"
        return False, "other_bot_owner"

    @staticmethod
    def _is_legacy_group_conversation_summary(memory: MemoryRecord) -> bool:
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        if memory.memory_type != "conversation_summary":
            return False
        if memory.scope != "group" and memory.visibility != "group_public":
            return False
        if _clean_id(metadata.get("owner_bot_id")):
            return False
        return _clean_id(metadata.get("summarizer")) == "companion_memory_schema_v1" or _clean_id(
            metadata.get("summary_schema_version")
        ) == "companion_memory_v1"
