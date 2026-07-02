from __future__ import annotations

from .models import MemoryRecord, SessionContext


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
                return True, "same_group"
            if ctx.scope == "private" and self.allow_group_public_in_private:
                return True, "group_public_allowed_in_private"
            return False, "other_group_public"
        return False, f"unknown_visibility:{memory.visibility}"
