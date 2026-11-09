from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .identity import canonical_user_id, session_target_id
from .models import MemoryRecord, SessionContext, normalize_explicit_person_binding


def _clean_id(value: str | None) -> str:
    return (value or "").strip()


def _platform_family(value: str | None) -> str:
    """Normalize adapter/product names without merging unrelated platforms."""
    platform = _clean_id(value).casefold()
    if platform in {"", "unknown", "default"}:
        return ""
    if platform in {"qq", "qqbot", "aiocqhttp", "onebot", "napcat", "go-cqhttp"}:
        return "qq"
    return platform


def visibility_prefilter_sql(
    scope: str | None,
    group_id: str | None,
    *,
    allow_group_public_in_private: bool = False,
    person_id: str | None = "",
) -> tuple[str, list[Any]]:
    # SQL prefilter for the visibility branch of VisibilityPolicy.is_visible.
    # Only the visibility column is covered here: callers keep their own
    # guards for archived / pending / raw-event columns, because those
    # columns differ between the memories table and the API surfaces.
    # The rule is the same one is_visible applies: group_public reaches a
    # private reader only when allow_group_public_in_private is on.  Keeping
    # the predicate here stops the person card and the recall path from
    # drifting apart again (L14).
    current_scope = _clean_id(scope).casefold()
    current_group = _clean_id(group_id)
    if current_scope == "private":
        allowed = ["private_pair", "shareable"]
        if allow_group_public_in_private:
            allowed.append("group_public")
        marks = ", ".join(f"'{value}'" for value in allowed)
        return f"COALESCE(visibility, '') IN ({marks})", []
    if current_scope == "group" and current_group:
        person = _clean_id(person_id)
        if person:
            # 同一个人：他在别的群公开说过的事，在这个群也能想起来。
            return (
                "("
                "COALESCE(visibility, '') = 'shareable' OR ("
                "COALESCE(visibility, '') = 'group_public' AND ("
                "group_id=? OR subject_id=? OR object_id=?"
                ")))",
                [current_group, person, person],
            )
        return (
            "("
            "COALESCE(visibility, '') = 'shareable' OR ("
            "COALESCE(visibility, '') = 'group_public' AND group_id=?"
            "))",
            [current_group],
        )
    # Group scope without a group id (or an unknown scope): shareable only.
    return "COALESCE(visibility, '') = 'shareable'", []


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
            owner_ok, owner_reason = self._bot_owner_visible(memory, ctx)
            if not owner_ok:
                return False, owner_reason
            return (self.allow_self_timeline_everywhere, "bot_self")
        if memory.visibility == "shareable":
            return True, "shareable"
        if memory.visibility == "private_pair":
            if self.explicit_person_link_matches(memory, ctx):
                return True, "explicit_linked_person"
            owner_ok, owner_reason = self._bot_owner_visible(memory, ctx)
            if not owner_ok:
                return False, owner_reason
            # A session id is the strongest ownership signal.  Imported rows
            # may carry a legacy platform prefix (usually ``default``), so
            # do not let that placeholder hide an otherwise identical window.
            if memory.session_id and memory.session_id == ctx.session_id:
                return True, "same_private_session"
            memory_person_id, _memory_assurance = normalize_explicit_person_binding(
                memory.subject_person_id,
                memory.identity_assurance,
            )
            context_person_id, _context_assurance = normalize_explicit_person_binding(
                ctx.subject_person_id,
                ctx.identity_assurance,
            )
            if memory_person_id and context_person_id and memory_person_id != context_person_id:
                return False, "other_person"
            memory_platform = _platform_family(memory.platform)
            current_platform = _platform_family(ctx.platform)
            if ctx.scope != "private":
                if memory_platform and current_platform and memory_platform != current_platform:
                    return False, "other_platform"
                return False, "private_pair_not_current_private"
            # 同一个人优先于平台判断：QQ 与飞书归一后，
            # 记忆不该因为 platform 字段不同而互相不可见。
            ids = {memory.subject.id, memory.object.id}
            if ctx.user_id and ctx.user_id in ids:
                if memory_platform and current_platform and memory_platform != current_platform:
                    memory_user = session_target_id(memory.session_id, "private")
                    current_user = session_target_id(ctx.session_id, "private")
                    if not (
                        memory_user and current_user and memory_user != current_user
                        and canonical_user_id(memory_user) == ctx.user_id
                        and canonical_user_id(current_user) == ctx.user_id
                    ):
                        return False, "other_platform"
                if memory_platform and current_platform:
                    return True, "same_private_user"
                return True, "same_private_user_legacy_platform"
            if memory_platform and current_platform and memory_platform != current_platform:
                return False, "other_platform"
            if ctx.user_id and session_target_id(memory.session_id, "private") == ctx.user_id:
                return True, "same_private_session_target"
            return False, "other_private_pair"
        if memory.visibility == "group_public":
            if ctx.scope == "group" and memory.group_id and memory.group_id == ctx.group_id:
                owner_ok, owner_reason = self._bot_owner_visible(memory, ctx)
                if not owner_ok:
                    return False, owner_reason
                return True, "same_group"
            if ctx.scope == "group" and _clean_id(ctx.user_id):
                # 一个人的记忆跟着人走：记忆主体就是当前发言人时，跨群也可见。
                ids = {_clean_id(memory.subject.id), _clean_id(memory.object.id)}
                if _clean_id(ctx.user_id) in ids:
                    owner_ok, owner_reason = self._bot_owner_visible(memory, ctx)
                    if not owner_ok:
                        return False, owner_reason
                    return True, "same_person_other_group"
            if ctx.scope == "private" and self.allow_group_public_in_private:
                owner_ok, owner_reason = self._bot_owner_visible(memory, ctx)
                if not owner_ok:
                    return False, owner_reason
                return True, "group_public_allowed_in_private"
            return False, "other_group_public"
        return False, f"unknown_visibility:{memory.visibility}"

    @staticmethod
    def explicit_person_link_matches(memory: MemoryRecord, ctx: SessionContext) -> bool:
        if memory.visibility != "private_pair" or memory.scope != "private" or ctx.scope != "private":
            return False
        memory_person_id, memory_assurance = normalize_explicit_person_binding(
            memory.subject_person_id,
            memory.identity_assurance,
        )
        context_person_id, context_assurance = normalize_explicit_person_binding(
            ctx.subject_person_id,
            ctx.identity_assurance,
        )
        return bool(
            memory_person_id
            and memory_person_id == context_person_id
            and memory_assurance == context_assurance == "explicit_linked"
        )

    def _bot_owner_visible(self, memory: MemoryRecord, ctx: SessionContext) -> tuple[bool, str]:
        """Keep bot-perspective group memories tied to the bot that produced them."""
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        owner_bot_id = _clean_id(metadata.get("owner_bot_id"))
        platform_id = _clean_id(memory.platform)
        if owner_bot_id and platform_id and owner_bot_id.casefold() == platform_id.casefold():
            owner_bot_id = ""
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
        if not current_bot_id:
            return False, "owner_bot_context_missing"
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
        owner_bot_id = _clean_id(metadata.get("owner_bot_id"))
        platform_id = _clean_id(memory.platform)
        if owner_bot_id and not (
            platform_id and owner_bot_id.casefold() == platform_id.casefold()
        ):
            return False
        return _clean_id(metadata.get("summarizer")) == "companion_memory_schema_v1" or _clean_id(
            metadata.get("summary_schema_version")
        ) == "companion_memory_v1"

# ---------------------------------------------------------------------------
# H6 / P3：写入范围的统一判定
#
# 这两个判定函数只做「能不能写」这一件事，不碰存储、不碰消息、不碰事件对象：
#   * can_remember_in_scope：显式 remember 这条记忆能不能落在当前会话范围；
#   * can_change_person_weight：当前这句话有没有资格改「这个人有多重」。
# 调用方（service.py / main.py）把结果翻成自己的错误码即可；判定本身可单测。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeWriteDecision:
    """A reusable allow/deny verdict for a scoped write.

    visibility is the exact value the caller should persist when allowed;
    durability is the ceiling the caller must not exceed (normal or pinned).
    Denied decisions keep the safe internal default.
    """

    allowed: bool
    code: str
    reason: str
    visibility: str = "internal"
    durability: str = "normal"

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "visibility": self.visibility,
            "durability": self.durability,
        }


def _config_bool(config: Any, dotted_key: str, default: bool = False) -> bool:
    """Read config.bool without importing the caller's config class."""
    if config is None:
        return default
    reader = getattr(config, "bool", None)
    if callable(reader):
        try:
            return bool(reader(dotted_key, default))
        except TypeError:
            try:
                return bool(reader(dotted_key))
            except Exception:
                return default
        except Exception:
            return default
    if isinstance(config, Mapping):
        current: Any = config
        for part in dotted_key.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return default
            current = current[part]
        return bool(current)
    return default


def resolve_group_admin(event: Any) -> bool:
    """Best-effort admin check for an AstrBot event (never trusts message text).

    AstrBot exposes AstrMessageEvent.is_admin() (implemented as
    role == "admin"), while tests and future adapters may expose a boolean
    attribute or role.  Anything else is treated as a normal member.
    """
    if event is None:
        return False
    admin = getattr(event, "is_admin", None)
    if callable(admin):
        try:
            if bool(admin()):
                return True
        except Exception:
            pass
    elif isinstance(admin, bool) and admin:
        return True
    for attr in ("is_group_admin", "group_admin", "admin"):
        value = getattr(event, attr, None)
        if isinstance(value, bool) and value:
            return True
    role = str(getattr(event, "role", "") or "").strip().casefold()
    return role in {"admin", "administrator", "owner", "群主", "管理员"}


def can_remember_in_scope(
    ctx: SessionContext,
    config: Any = None,
    *,
    event: Any = None,
    is_group_admin: bool | None = None,
) -> ScopeWriteDecision:
    """P3: decide whether this sender may persist an explicit memory here.

    Rules:
      * private chat: the speaker may remember their own private memory;
      * group chat: disabled unless memory_tools.allow_group_remember is on,
        and even then only a group admin may write group_public memories;
      * every other scope: refuse rather than guess.

    is_group_admin overrides event inspection.  Callers should pass the
    current AstrBot event so the decision uses the platform's own admin bit.
    """
    scope = _clean_id(getattr(ctx, "scope", "")).casefold()
    user_id = _clean_id(getattr(ctx, "user_id", ""))
    if scope == "private":
        if not user_id:
            return ScopeWriteDecision(False, "user_required", "私聊也缺发言人身份，先不写。")
        return ScopeWriteDecision(
            True,
            "private_remember_allowed",
            "私聊里可以记，默认只给这一对一关系看。",
            visibility="private_pair",
            durability="normal",
        )
    if scope != "group":
        return ScopeWriteDecision(
            False,
            "remember_scope_unsupported",
            "只支持私聊或群聊会话；不认识的场景宁可不写。",
        )
    if not _config_bool(config, "memory_tools.allow_group_remember", False):
        return ScopeWriteDecision(
            False,
            "group_remember_disabled",
            "群聊里默认不主动记；要记请私聊，或由管理员显式开启。",
        )
    admin = is_group_admin
    if admin is None:
        admin = resolve_group_admin(event)
    if not admin:
        return ScopeWriteDecision(
            False,
            "group_remember_requires_admin",
            "群聊里只有管理员能让 Bot 写群可见记忆；普通成员请私聊。",
        )
    if not _clean_id(getattr(ctx, "group_id", "")):
        return ScopeWriteDecision(False, "group_id_required", "群聊缺群标识，先不写。")
    return ScopeWriteDecision(
        True,
        "group_admin_remember_allowed",
        "管理员显式开启后，允许写群可见记忆；仍不许 pinned。",
        visibility="group_public",
        durability="normal",
    )


_WEIGHT_RELATION_TOPIC = re.compile(
    r"关系|分量|好感|印象|称呼|亲密度|权重|weight|relationship", re.IGNORECASE
)
_WEIGHT_ADJUST_ACTION = re.compile(
    r"改|调|设|重置|纠正|降|低|别|不要|不用|没那么|没到|不是|只是|普通|忘|不重要|"
    r"lower|reset|set|adjust|stop|forget|treat me",
    re.IGNORECASE,
)
_DIRECT_WEIGHT_CORRECTION_PHRASES = (
    "没那么熟",
    "不熟",
    "别叫这么亲",
    "别叫得这么亲",
    "别这么亲",
    "不要这么亲",
    "只是朋友",
    "只是普通朋友",
    "普通朋友",
    "把我当",
    "别把我当",
    "忘了我",
    "不用记得我",
    "不重要",
    "别对我这么",
    "没到那个份上",
    "关系降",
    "分量调低",
    "好感度调低",
    "not that close",
    "just friends",
    "lower my weight",
    "reset my weight",
    "treat me as",
    "forget me",
    "stop calling me",
    "don't call me",
    "do not call me",
)


def message_requests_weight_change(text: str) -> bool:
    """Whether the current user utterance is an explicit relationship correction.

    H6 的根因是模型可以凭自己的判断调 tool；判定只认「用户这话本身在说关系
    要收一收」，不认模型传上来的 rationale。 文案里既认中文口语，也认英文。
    """
    normalized = str(text or "").strip().casefold()
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _DIRECT_WEIGHT_CORRECTION_PHRASES):
        return True
    return bool(
        _WEIGHT_RELATION_TOPIC.search(normalized)
        and _WEIGHT_ADJUST_ACTION.search(normalized)
    )


def can_change_person_weight(
    ctx: SessionContext,
    config: Any = None,
    *,
    action: str = "set",
    target_weight: int | float | None = None,
    current_weight: int | float | None = None,
    user_request_confirmed: bool | None = None,
) -> ScopeWriteDecision:
    """H6: decide whether this tool call may change the speaker's weight.

    Rules:
      * reads are always allowed when the feature is enabled;
      * every mutation needs explicit evidence from the user (the current
        message, or a caller-verified user_request_confirmed), so the model
        cannot rewrite the weight on its own;
      * in groups, weight may never be raised or reset; only a lowering that
        the user explicitly asked for is accepted.
    """
    if not _config_bool(config, "persona_memory.weight_enabled", True):
        return ScopeWriteDecision(False, "person_weight_disabled", "分量功能没开，先不动。")
    normalized = _clean_id(action).casefold() or "get"
    if normalized in {"get", "check", "read", "查看"}:
        return ScopeWriteDecision(
            True,
            "person_weight_read_allowed",
            "只读查看，不涉及改写。",
        )
    if normalized not in {"set", "reset", "correct", "改", "纠正", "重置"}:
        return ScopeWriteDecision(False, "unknown_action", "不认识的分量动作，拒绝。")

    requested = user_request_confirmed
    if requested is None:
        requested = message_requests_weight_change(getattr(ctx, "message_text", ""))
    in_group = _clean_id(getattr(ctx, "scope", "")).casefold() == "group"

    if normalized in {"reset", "重置"}:
        if in_group:
            return ScopeWriteDecision(
                False,
                "person_weight_reset_requires_private",
                "群里不能重置分量；要重置请回私聊说。",
            )
        if not requested:
            return ScopeWriteDecision(
                False,
                "person_weight_requires_user_request",
                "分量只有用户本人明确纠正才能动，模型不能自己改。",
            )
        return ScopeWriteDecision(True, "person_weight_reset_allowed", "用户明确要求重置，允许。")

    if target_weight is None:
        return ScopeWriteDecision(False, "weight_required", "要改分量就得给目标值。")
    try:
        target = int(round(float(target_weight)))
    except (TypeError, ValueError):
        return ScopeWriteDecision(False, "invalid_weight", "分量必须是数字。")
    if target < 0 or target > 100:
        return ScopeWriteDecision(False, "invalid_weight", "分量必须在 0 到 100 之间。")

    if in_group:
        try:
            current = int(round(float(current_weight or 0)))
        except (TypeError, ValueError):
            current = 0
        if target >= current:
            return ScopeWriteDecision(
                False,
                "person_weight_raise_requires_private",
                "群里不能把自己抬重；抬升请回私聊说。",
            )
        if not requested:
            return ScopeWriteDecision(
                False,
                "person_weight_requires_user_request",
                "群里也只能按用户本人的原话往回收，模型不能自己改。",
            )
        return ScopeWriteDecision(
            True,
            "person_weight_group_lower_allowed",
            "用户明确要求收一收，群里允许把分量降下来。",
        )

    if not requested:
        return ScopeWriteDecision(
            False,
            "person_weight_requires_user_request",
            "分量只有用户本人明确纠正才能动，模型不能自己改。",
        )
    return ScopeWriteDecision(True, "person_weight_set_allowed", "用户明确纠正，允许改分量。")
