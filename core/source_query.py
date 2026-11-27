"""Bounded, read-only source queries used by the current response model.

This local profile does not implement the public MemoryAtom query protocol.
Identity comes from the host event; cursors live in the shared turn budget.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import secrets
import time
from typing import Any

from .models import clean_text, stable_fingerprint
from .source_evidence import record_source_read
from .query_session import query_context


PROFILE = "memory.local-source-query.v1"
_EMPTY_SEARCH_HINT = "未命中，可换2-4字短词/同义词，或改用 range/range_batch 按时间段重试。"
_EMPTY_RANGE_HINT = "该时间段无消息，可扩大起止时间或换关键词 search 重试。"
_ALLOWED_QUERY_FIELDS = frozenset({"action", "terms", "start_at", "end_at", "source_ref", "direction", "excerpt_offset", "cursor", "limit"})
_LEGACY_TOGETHER_SESSION_PREFIX = "together_companion:"
_LEGACY_TOGETHER_SHARED_EVENTS = frozenset({"shared_call", "shared_watch", "shared_activity"})


class SourceQueryError(ValueError):
    pass


def _is_valid_tz_iso8601(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > 80 or "\x00" in value:
        return False
    try:
        instant = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return instant.utcoffset() is not None
    except ValueError:
        return False


def explain_source_query_error(
    error_code: str,
    parameters: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return concise self-correcting (detail, hint) for source query rejections."""
    params = parameters if isinstance(parameters, dict) else {}
    action = str(params.get("action") or "search").strip() or "search"
    code = str(error_code or "").strip()

    if code == "range_requires_start_end_without_terms":
        if params.get("terms"):
            return (
                f"action='{action}' 不能与 terms 同时使用",
                f"按时间段读取请移除 terms 并提供带时区的 start_at（省略 end_at 默认查至当前）；按关键词搜索请用 action='search'。",
            )
        return (
            f"action='{action}' 缺少必填的 start_at（带时区 ISO 8601 时间）",
            "请传入带时区的 start_at（如 '2026-11-25T00:00:00+08:00'），省略 end_at 默认查至当前；若按关键词查找，请改用 action='search' 并传 terms。",
        )
    if code == "time_requires_iso8601_with_timezone":
        return (
            "start_at 或 end_at 不是带时区的 ISO 8601 时间格式",
            "请使用带时区偏移的 ISO 8601 字符串，例如 '2026-11-25T00:00:00+08:00' 或 '2026-11-25T00:00:00Z'。",
        )
    if code == "time_range_reversed_or_empty":
        return (
            "时间区间无效：start_at 必须早于 end_at",
            "请确保 start_at < end_at（区间为左闭右开 [start_at, end_at)），或省略 end_at 默认查至当前。",
        )
    if code == "search_requires_terms":
        return (
            "action='search' 缺少必填的非空关键词数组 terms",
            "请传入 1-6 个短关键词数组，例如 terms=['无糖拿铁']；若按时间段浏览，请改用 action='range' 并提供 start_at。",
        )
    if code in {"terms_must_be_array_up_to_6", "empty_term"}:
        return (
            "terms 必须是包含 1-6 个非空字符串的数组",
            "请传入 1-6 个非空短词数组，例如 terms=['关键词1', '关键词2']。",
        )
    if code == "context_requires_source_ref_only":
        return (
            f"action='{action}' 必须提供有效的 timeline:tl_... source_ref，且不能混用 terms/start_at/end_at",
            "请先通过 search/range 获取证据中的 source_ref（格式 timeline:tl_...），再单独传给 context 或 read。",
        )
    if code == "read_requires_source_ref_and_offset":
        return (
            "action='read' 只接受 source_ref 与 excerpt_offset，不能设置 direction",
            "请移除 direction（或保持默认 around），仅传 source_ref 和 excerpt_offset。",
        )
    if code == "excerpt_offset_requires_read":
        return (
            "excerpt_offset 仅支持与 action='read' 搭配使用",
            "续读长消息请设 action='read' 并传 source_ref 与 excerpt_offset；其他动作请省略 excerpt_offset。",
        )
    if code == "source_ref_direction_require_context":
        return (
            "source_ref 与 direction 仅适用于 action='context' 或 action='read'",
            "查看上下文请设 action='context'；按关键词或时间查询请移除 source_ref 与 direction。",
        )
    if code == "cursor_requires_no_query_parameters":
        return (
            "使用 cursor 翻页时不能同时传入其他查询参数",
            "翻页时请只传 cursor 字段，不要同时传 action、terms、start_at、end_at、source_ref 或 limit。",
        )
    if code == "cursor_invalid":
        return (
            "翻页 cursor 无效、已过期或数据源已变化",
            "请去掉 cursor，重新发起一次 search/range/range_batch 查询。",
        )
    if code == "unsupported_action":
        return (
            f"不支持的 action='{action}'",
            "action 仅支持 'search'、'range'、'range_batch'、'context' 或 'read'。",
        )
    if code == "unsupported_direction":
        return (
            "不支持的 direction 参数值",
            "direction 仅支持 'around'、'before' 或 'after'。",
        )
    if code == "unknown_parameter":
        unknown = sorted(k for k in params if k not in _ALLOWED_QUERY_FIELDS)
        extra = f"（{', '.join(unknown[:4])}）" if unknown else ""
        return (
            f"包含未定义的参数字段{extra}",
            "仅支持 action、terms、start_at、end_at、source_ref、direction、cursor、limit、excerpt_offset。",
        )
    if code == "invalid_limit":
        return (
            "limit 必须为非负整数（0 表示使用默认值）",
            "请传入非负整数 limit（如 10），或省略使用默认值。",
        )
    if code == "invalid_excerpt_offset":
        return (
            "excerpt_offset 必须为非负整数",
            "请传入来自上一条结果的 next_excerpt_offset 非负整数。",
        )
    if code == "range_batch_requires_time_range_only":
        return (
            "action='range_batch' 仅接受时间区间参数 start_at 与可选 end_at",
            "请移除 terms、source_ref、direction 和 excerpt_offset，并传入带时区的 start_at。",
        )
    if code == "range_batch_uses_server_budget":
        return (
            "action='range_batch' 由服务端控制批量预算，limit 须省略或为 0",
            "请移除 limit（或设为 0），仅传 action='range_batch' 与带时区的 start_at。",
        )
    return ("", "")


def diagnose_source_query_parameters(parameters: Any) -> tuple[str, str]:
    """Inspect invalid raw sources parameters and return a clear (detail, hint)."""
    if not isinstance(parameters, dict):
        return (
            "sources 参数必须是 JSON 对象",
            "请传入对象参数，例如 {'action': 'search', 'terms': ['关键词']} 或 {'action': 'range', 'start_at': '2026-11-25T00:00:00+08:00'}。",
        )
    unknown = sorted(k for k in parameters if k not in _ALLOWED_QUERY_FIELDS)
    if unknown:
        return explain_source_query_error("unknown_parameter", parameters)
    cursor = parameters.get("cursor")
    if isinstance(cursor, str) and cursor.strip():
        has_extra = (
            any(parameters.get(name) for name in ("terms", "start_at", "end_at", "source_ref", "excerpt_offset", "limit"))
            or parameters.get("action", "search") != "search"
            or parameters.get("direction", "around") != "around"
        )
        if has_extra:
            return explain_source_query_error("cursor_requires_no_query_parameters", parameters)
    raw_action = parameters.get("action", "search")
    if not isinstance(raw_action, str) or raw_action.strip() not in {"search", "range", "range_batch", "context", "read"}:
        return explain_source_query_error("unsupported_action", parameters)
    action = raw_action.strip()
    limit = parameters.get("limit", 0)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        return explain_source_query_error("invalid_limit", parameters)
    offset = parameters.get("excerpt_offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return explain_source_query_error("invalid_excerpt_offset", parameters)
    direction = parameters.get("direction", "around")
    if not isinstance(direction, str) or direction not in {"around", "before", "after"}:
        return explain_source_query_error("unsupported_direction", parameters)

    terms = parameters.get("terms")
    if terms is not None and (
        not isinstance(terms, list)
        or len(terms) > 6
        or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in terms)
    ):
        return explain_source_query_error("terms_must_be_array_up_to_6", parameters)

    start_at = parameters.get("start_at", "")
    end_at = parameters.get("end_at", "")
    source_ref = parameters.get("source_ref", "")
    if start_at not in ("", None) and not _is_valid_tz_iso8601(start_at):
        return explain_source_query_error("time_requires_iso8601_with_timezone", parameters)
    if end_at not in ("", None) and not _is_valid_tz_iso8601(end_at):
        return explain_source_query_error("time_requires_iso8601_with_timezone", parameters)

    if action in {"range", "range_batch"}:
        if action == "range_batch" and limit:
            return explain_source_query_error("range_batch_uses_server_budget", parameters)
        if terms:
            return explain_source_query_error("range_requires_start_end_without_terms", parameters)
        if source_ref or direction != "around" or offset:
            code = "range_batch_requires_time_range_only" if action == "range_batch" else "source_ref_direction_require_context"
            return explain_source_query_error(code, parameters)
        if not isinstance(start_at, str) or not start_at.strip():
            return explain_source_query_error("range_requires_start_end_without_terms", parameters)
        if isinstance(end_at, str) and end_at.strip():
            start_dt = datetime.fromisoformat(start_at.strip().replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_at.strip().replace("Z", "+00:00"))
            if start_dt >= end_dt:
                return explain_source_query_error("time_range_reversed_or_empty", parameters)
    elif action == "search":
        if source_ref or direction != "around":
            return explain_source_query_error("source_ref_direction_require_context", parameters)
        if offset:
            return explain_source_query_error("excerpt_offset_requires_read", parameters)
        if not terms:
            return explain_source_query_error("search_requires_terms", parameters)
    elif action in {"context", "read"}:
        if not isinstance(source_ref, str) or not source_ref.startswith("timeline:tl_") or terms or start_at or end_at:
            return explain_source_query_error("context_requires_source_ref_only", parameters)
        if action == "read" and direction != "around":
            return explain_source_query_error("read_requires_source_ref_and_offset", parameters)
        if action == "context" and offset:
            return explain_source_query_error("excerpt_offset_requires_read", parameters)
    return (
        f"sources 参数组合不符合 action='{action}' 的要求",
        "search 传 terms；range/range_batch 传带时区 start_at（end_at 可省）；context/read 传 timeline:tl_... source_ref；翻页只传 cursor。",
    )


def default_range_end_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_source_query_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Normalize ergonomic range defaults before strict request validation."""
    if not isinstance(parameters, dict):
        return parameters
    cursor = parameters.get("cursor")
    if isinstance(cursor, str) and cursor.strip():
        return parameters
    action = parameters.get("action")
    if action not in {"range", "range_batch"}:
        return parameters
    normalized = dict(parameters)
    start_at = normalized.get("start_at")
    end_at = normalized.get("end_at")
    if (
        isinstance(start_at, str)
        and start_at.strip()
        and (end_at is None or (isinstance(end_at, str) and not end_at.strip()))
    ):
        normalized["end_at"] = default_range_end_at()
    if action == "range_batch" and "limit" in normalized:
        raw_limit = normalized["limit"]
        if type(raw_limit) is int and raw_limit > 0:
            normalized["limit"] = 0
    return normalized


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise SourceQueryError("invalid_parameter")
    return value.strip()


def _instant(value: str) -> str:
    value = _text(value, 80)
    if not value:
        return ""
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.utcoffset() is None:
            raise ValueError("timezone required")
        return instant.astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise SourceQueryError("time_requires_iso8601_with_timezone") from exc


@dataclass(frozen=True)
class SourceQuery:
    action: str = "search"
    terms: tuple[str, ...] = ()
    start_at: str = ""
    end_at: str = ""
    source_ref: str = ""
    direction: str = "around"
    excerpt_offset: int = 0

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "SourceQuery":
        if set(value) - {"action", "terms", "start_at", "end_at", "source_ref", "direction", "excerpt_offset"}:
            raise SourceQueryError("unknown_parameter")
        action = _text(value.get("action", "search"), 20)
        if action not in {"search", "range", "context", "read"}:
            raise SourceQueryError("unsupported_action")
        terms = value.get("terms")
        if terms is None:
            terms = []
        if not isinstance(terms, list) or len(terms) > 6:
            raise SourceQueryError("terms_must_be_array_up_to_6")
        terms = tuple(dict.fromkeys(_text(term, 80) for term in terms))
        if any(not term for term in terms):
            raise SourceQueryError("empty_term")
        raw_end = value.get("end_at", "")
        if action == "range" and raw_end is None:
            raw_end = ""
        start, end = _instant(value.get("start_at", "")), _instant(raw_end)
        if action == "range" and start and not end:
            end = default_range_end_at()
        if start and end and datetime.fromisoformat(start) >= datetime.fromisoformat(end):
            raise SourceQueryError("time_range_reversed_or_empty")
        source_ref = _text(value.get("source_ref", ""), 180)
        direction = _text(value.get("direction", "around"), 16)
        offset = value.get("excerpt_offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise SourceQueryError("invalid_excerpt_offset")
        if direction not in {"around", "before", "after"}:
            raise SourceQueryError("unsupported_direction")
        if action in {"context", "read"}:
            if not source_ref.startswith("timeline:tl_") or terms or start or end:
                raise SourceQueryError("context_requires_source_ref_only")
            if action == "read" and direction != "around":
                raise SourceQueryError("read_requires_source_ref_and_offset")
            if action != "read" and offset:
                raise SourceQueryError("excerpt_offset_requires_read")
        elif source_ref or direction != "around":
            raise SourceQueryError("source_ref_direction_require_context")
        elif offset:
            raise SourceQueryError("excerpt_offset_requires_read")
        elif action == "search" and not terms:
            raise SourceQueryError("search_requires_terms")
        elif action == "range" and (terms or not start or not end):
            raise SourceQueryError("range_requires_start_end_without_terms")
        return cls(action, terms, start, end, source_ref, direction, offset)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["terms"] = list(self.terms)
        return value


def _authorized_group_read_policy(
    ctx: Any,
    group_policy: dict[str, Any] | None,
) -> tuple[bool, frozenset[str], frozenset[str]] | None:
    if (
        not isinstance(group_policy, dict)
        or not group_policy.get("enabled")
        or getattr(ctx, "scope", "") != "private"
        or getattr(ctx, "strict_session_only", False)
    ):
        return None
    allow_all = bool(group_policy.get("allow_all_groups"))
    allowed = frozenset(
        clean_text(item, 120)
        for item in (group_policy.get("allowed_groups") or ())
        if clean_text(item, 120)
    )
    denied = frozenset(
        clean_text(item, 120)
        for item in (group_policy.get("denied_groups") or ())
        if clean_text(item, 120)
    )
    effective_allowed = allowed - denied
    if not allow_all and not effective_allowed:
        return None
    return allow_all, effective_allowed, denied


def _legacy_together_session_id(ctx: Any) -> str:
    """Return the exact legacy together_companion:<user_id> read alias for private chats."""
    if getattr(ctx, "scope", "") != "private" or getattr(ctx, "strict_session_only", False):
        return ""
    user_id = clean_text(getattr(ctx, "user_id", ""), 120)
    bot_id = clean_text(getattr(ctx, "bot_id", ""), 120)
    if not user_id or not bot_id or bot_id == "self":
        return ""
    return f"{_LEGACY_TOGETHER_SESSION_PREFIX}{user_id}"


def _legacy_together_source_visible(
    ctx: Any,
    row: dict[str, Any],
    metadata: dict[str, Any],
) -> bool:
    """Strictly verify a legacy together_companion:<user_id> private timeline row."""
    alias_session = _legacy_together_session_id(ctx)
    if not alias_session:
        return False
    if row.get("scope") != "private" or row.get("session_id") != alias_session:
        return False
    raw_meta = row.get("metadata")
    if isinstance(raw_meta, str) and raw_meta.strip():
        try:
            if not isinstance(json.loads(raw_meta), dict):
                return False
        except ValueError:
            return False
    event_type = clean_text(row.get("event_type"), 40)
    if event_type not in {"user_message", "bot_response", *_LEGACY_TOGETHER_SHARED_EVENTS}:
        return False
    user_id = clean_text(ctx.user_id, 120)
    bot_id = clean_text(ctx.bot_id, 120)
    if row.get("object_id") != user_id:
        return False
    if clean_text(metadata.get("participant_user_id"), 120) not in {"", user_id}:
        return False
    owner = clean_text(metadata.get("owner_bot_id"), 120)
    meta_bot = clean_text(metadata.get("bot_id"), 120)
    if owner == "self" or (owner and owner != bot_id):
        return False
    if meta_bot not in {"", bot_id}:
        return False
    platform = clean_text(metadata.get("platform"), 80)
    if platform not in {"", "together_companion", clean_text(ctx.platform, 80)}:
        return False
    persona_id = clean_text(metadata.get("persona_id"), 96)
    if persona_id not in {"", "legacy", clean_text(ctx.persona_id, 96)}:
        return False
    if event_type == "user_message":
        return bool(owner == bot_id and row.get("subject_id") == user_id)
    return row.get("subject_id") == bot_id


def _legacy_together_source_sql(ctx: Any, field: Any) -> tuple[str, list[str]] | None:
    """SQL equivalent of _legacy_together_source_visible."""
    alias_session = _legacy_together_session_id(ctx)
    if not alias_session:
        return None
    user_id = clean_text(ctx.user_id, 120)
    bot_id = clean_text(ctx.bot_id, 120)
    platform = clean_text(ctx.platform, 80)
    persona_id = clean_text(ctx.persona_id, 96)
    clause = (
        "(t.scope='private' AND t.session_id=? AND t.object_id=? "
        "AND (t.metadata IS NULL OR t.metadata='' OR json_valid(t.metadata)) "
        f"AND {field('participant_user_id')} IN ('',?) "
        f"AND {field('owner_bot_id')} IN ('',?) "
        f"AND {field('bot_id')} IN ('',?) "
        f"AND {field('platform')} IN ('','together_companion',?) "
        f"AND {field('persona_id')} IN ('','legacy',?) "
        "AND ("
        f"(t.event_type='user_message' AND t.subject_id=? AND {field('owner_bot_id')}=?) "
        "OR (t.event_type IN ('bot_response','shared_call','shared_watch','shared_activity') AND t.subject_id=?)"
        "))"
    )
    params = [
        alias_session, user_id, user_id, bot_id, bot_id, platform, persona_id,
        user_id, bot_id, bot_id,
    ]
    return clause, params


def source_visible(
    ctx: Any,
    row: dict[str, Any],
    metadata: dict[str, Any],
    *,
    group_policy: dict[str, Any] | None = None,
) -> bool:
    """Never derive raw-source authority from a parent summary or supplied ID."""
    if ctx.scope not in {"private", "group"} or not ctx.session_id:
        return False
    if _legacy_together_source_visible(ctx, row, metadata):
        return True
    if row.get("event_type") not in {"user_message", "bot_response"}:
        return False
    owner = clean_text(metadata.get("owner_bot_id"), 120)
    if not owner or owner == "self" or owner != clean_text(ctx.bot_id, 120):
        return False
    if clean_text(metadata.get("bot_id"), 120) not in {"", owner}:
        return False
    if clean_text(metadata.get("platform"), 80) != clean_text(ctx.platform, 80):
        return False
    # Rows captured before the runtime persona was resolved carry no persona;
    # treat them as legacy so upgrading does not hide the captured history.
    persona_id = clean_text(metadata.get("persona_id"), 96)
    if persona_id not in {"", "legacy"} and persona_id != clean_text(ctx.persona_id, 96):
        return False
    if row.get("scope") == ctx.scope and row.get("session_id") == ctx.session_id:
        if row.get("event_type") == "bot_response" and row.get("subject_id") != owner:
            return False
        if ctx.scope == "private":
            if not ctx.user_id or row.get("object_id") != ctx.user_id:
                return False
            if row.get("event_type") == "user_message" and row.get("subject_id") != ctx.user_id:
                return False
            if clean_text(metadata.get("participant_user_id"), 120) not in {"", ctx.user_id}:
                return False
        elif not ctx.group_id or row.get("object_id") != ctx.group_id:
            return False
        return True
    # Private chat with explicit group visibility / ACL authorization may read
    # ONLY the current speaker's own messages from authorized groups; never
    # expose another group member's messages or bot replies.
    policy = _authorized_group_read_policy(ctx, group_policy)
    if policy is None:
        return False
    allow_all, allowed_groups, denied_groups = policy
    if row.get("scope") != "group" or row.get("event_type") != "user_message":
        return False
    if not ctx.user_id or row.get("subject_id") != ctx.user_id:
        return False
    if clean_text(metadata.get("participant_user_id"), 120) not in {"", ctx.user_id}:
        return False
    row_group_id = clean_text(row.get("object_id"), 120)
    if not row_group_id or row_group_id in denied_groups:
        return False
    return allow_all or row_group_id in allowed_groups


def source_partition(
    ctx: Any,
    *,
    group_policy: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """SQL equivalent of source_visible, applied before page/candidate limits."""
    if ctx.scope not in {"private", "group"} or not all((ctx.session_id, ctx.bot_id, ctx.platform)) or ctx.bot_id == "self":
        raise SourceQueryError("source_scope_unavailable")
    target = ctx.user_id if ctx.scope == "private" else ctx.group_id
    if not target:
        raise SourceQueryError("source_scope_unavailable")
    # Invalid legacy metadata is unavailable, never re-attributed to the caller.
    meta = "CASE WHEN json_valid(t.metadata) THEN t.metadata ELSE '{}' END"
    def field(name: str) -> str:
        return f"COALESCE(json_extract({meta}, '$.{name}'), '')"
    policy = _authorized_group_read_policy(ctx, group_policy)
    legacy_together = _legacy_together_source_sql(ctx, field)
    if policy is None:
        clauses = [
            "t.scope=?", "t.session_id=?", "t.object_id=?",
            "t.event_type IN ('user_message','bot_response')",
            f"{field('owner_bot_id')}=?", f"{field('platform')}=?",
            # Empty and ``legacy`` personas predate runtime persona resolution.
            f"{field('persona_id')} IN ('', 'legacy', ?)",
            f"{field('bot_id')} IN ('',?)",
            "(t.event_type!='bot_response' OR t.subject_id=?)",
        ]
        params = [ctx.scope, ctx.session_id, target, ctx.bot_id, ctx.platform, ctx.persona_id, ctx.bot_id, ctx.bot_id]
        if ctx.scope == "private":
            clauses.extend(["(t.event_type!='user_message' OR t.subject_id=?)", f"{field('participant_user_id')} IN ('',?)"])
            params.extend([ctx.user_id, ctx.user_id])
        standard = " AND ".join(clauses)
        if legacy_together is not None:
            legacy_clause, legacy_params = legacy_together
            return f"(({standard}) OR {legacy_clause})", [*params, *legacy_params]
        return standard, params
    allow_all, allowed_groups, denied_groups = policy
    common_clauses = [
        f"{field('owner_bot_id')}=?",
        f"{field('platform')}=?",
        f"{field('persona_id')} IN ('', 'legacy', ?)",
        f"{field('bot_id')} IN ('',?)",
    ]
    params = [ctx.bot_id, ctx.platform, ctx.persona_id, ctx.bot_id]
    private_branch = (
        "(t.scope='private' AND t.session_id=? AND t.object_id=? "
        "AND t.event_type IN ('user_message','bot_response') "
        "AND (t.event_type!='bot_response' OR t.subject_id=?) "
        "AND (t.event_type!='user_message' OR t.subject_id=?) "
        f"AND {field('participant_user_id')} IN ('',?))"
    )
    params.extend([ctx.session_id, ctx.user_id, ctx.bot_id, ctx.user_id, ctx.user_id])
    group_conditions = [
        "t.scope='group'",
        "t.event_type='user_message'",
        "t.subject_id=?",
        f"{field('participant_user_id')} IN ('',?)",
        "t.object_id!=''",
    ]
    params.extend([ctx.user_id, ctx.user_id])
    if allow_all:
        if denied_groups:
            ordered_denied = sorted(denied_groups)
            marks = ",".join("?" for _ in ordered_denied)
            group_conditions.append(f"t.object_id NOT IN ({marks})")
            params.extend(ordered_denied)
    else:
        ordered_allowed = sorted(allowed_groups)
        marks = ",".join("?" for _ in ordered_allowed)
        group_conditions.append(f"t.object_id IN ({marks})")
        params.extend(ordered_allowed)
    group_branch = "(" + " AND ".join(group_conditions) + ")"
    standard = " AND ".join([*common_clauses, f"({private_branch} OR {group_branch})"])
    if legacy_together is not None:
        legacy_clause, legacy_params = legacy_together
        return f"(({standard}) OR {legacy_clause})", [*params, *legacy_params]
    return standard, params


async def query_sources(service: Any, event: Any, *, cursor: str = "", limit: int = 0, **parameters: Any) -> dict[str, Any]:
    """Execute one source page; no model call and no source/fact mutation."""
    if parameters.get("action") == "range_batch" or (isinstance(cursor, str) and cursor.startswith("srcb_")):
        from .source_query_v2 import query_range_batch
        return await query_range_batch(service, event, cursor=cursor, limit=limit, **parameters)
    started = time.monotonic()
    empty = {"profile": PROFILE, "ok": False, "status": "rejected", "error": "",
             "sources": [], "next_cursor": None, "context_cursors": {}, "coverage": {}, "usage": {}}
    try:
        if not service.config.bool("memory_reconstruction.enabled", True) or not service.config.bool("memory_tools.enable_reconstruction_tool", True):
            raise SourceQueryError("source_query_disabled")
        ctx = service._normalized_session_context(await query_context(service, event))
        if not service._scope_feature_enabled(ctx, "recall"):
            raise SourceQueryError("scope_recall_disabled")
        group_policy = (
            await service._authorized_private_group_read_policy(ctx)
            if ctx.scope == "private" and hasattr(service, "_authorized_private_group_read_policy")
            else None
        )
        source_partition(ctx, group_policy=group_policy)  # Reject unknown authority before querying.
        cursor = _text(cursor, 160)
        turn_key = service._reconstruction_budget_key(event, ctx)
        previous = None
        if cursor:
            # All filter parameters belong to the server-issued cursor.
            if set(parameters) - {"action", "terms", "start_at", "end_at", "source_ref", "direction", "excerpt_offset"} or any(parameters.get(name) for name in ("terms", "start_at", "end_at", "source_ref", "excerpt_offset")) or parameters.get("action", "search") != "search" or parameters.get("direction", "around") != "around" or limit:
                raise SourceQueryError("cursor_requires_no_query_parameters")
            async with service._reconstruction_lock:
                state = service._reconstruction_states.get(turn_key, {})
                previous = state.get("source_cursors", {}).get(cursor)
            if not previous or time.monotonic() > previous["expires_at"]:
                raise SourceQueryError("cursor_invalid")
            query = SourceQuery.parse(previous["query"])
            page_limit = previous["limit"]
        else:
            query = SourceQuery.parse(parameters)
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise SourceQueryError("invalid_limit")
            page_limit = service._reconstruction_per_step_limit(limit)
        signature = stable_fingerprint("source_query", cursor or json.dumps(query.as_dict(), sort_keys=True), page_limit)
        budget = await service._reserve_reconstruction_step(
            event, ctx, signature, allow_source_fallback=True,
        )
        if not budget["accepted"]:
            raise SourceQueryError(budget["error"])
        # Cursor pages cannot refresh this deadline. Different queries still
        # consume the shared per-turn navigation step/row/character ceilings.
        expires_at = previous["expires_at"] if previous else started + 120.0
        policy = await service.store.memory_revision()
        if previous and policy != previous["policy_revision"]:
            raise SourceQueryError("cursor_invalid")
        page = await service.store.query_source_page(
            ctx, query, limit=page_limit,
            boundary=previous["boundary"] if previous else None,
            expected_revision=previous["source_revision"] if previous else None,
            group_policy=group_policy,
        )
        if time.monotonic() > expires_at or not service._scope_feature_enabled(ctx, "recall"):
            raise SourceQueryError("source_query_expired_or_disabled")
        if policy != await service.store.memory_revision() or page["revision"] != await service.store.source_revision():
            raise SourceQueryError("source_changed_retry")
        sources = [value for row in page["rows"] if (value := service._serialize_navigation_source(
            ctx, row, excerpt_offset=query.excerpt_offset, terms=query.terms,
            group_policy=group_policy,
        ))]
        cursors: dict[str, str] = {}
        async with service._reconstruction_lock:
            state = service._reconstruction_states.get(turn_key)
            if state is None:
                raise SourceQueryError("cursor_invalid")
            for direction, boundary in page["continuations"].items():
                token = "src_" + secrets.token_urlsafe(24)
                next_query = replace(query, direction=direction) if query.action == "context" else query
                state.setdefault("source_cursors", {})[token] = {
                    "query": next_query.as_dict(), "boundary": boundary, "limit": page_limit,
                    "source_revision": page["revision"], "policy_revision": policy, "expires_at": expires_at,
                }
                cursors[direction] = token
        coverage = {
            "scope": "current_session_only", "time_basis": "message_observation",
            "start_at": query.start_at, "end_at": query.end_at, "interval": "[start,end)",
            "order": "message_time_asc" if query.action == "context" else ("single_message" if query.action == "read" else "message_time_desc"),
            "selection": "literal_terms_any" if query.action == "search" else query.action,
            "more_available": bool(cursors), "source_revision": page["revision"],
            "read_count": page["read_count"], "returned_count": len(sources),
            "suppressed_count": len(page["rows"]) - len(sources),
            "excerpt_truncated_count": sum(value["excerpt_truncated"] for value in sources),
            "event_coverage": "not_established", "path": page["path"],
            "unknown_message_time": "excluded_from_time_order",
        }
        usage = {"step": budget["step"], "remaining_steps": budget["remaining_steps"],
                 "model_calls": 0, "returned_chars": sum(len(value["excerpt"]) for value in sources),
                 "elapsed_ms": round((time.monotonic() - started) * 1000)}
        async with service._reconstruction_lock:
            state = service._reconstruction_states.get(turn_key)
            if state is None:
                raise SourceQueryError("cursor_invalid")
            record_source_read(state, sources, source_revision=page["revision"], policy_revision=policy,
                               expires_at=expires_at, coverage=coverage, event=event, ctx=ctx)
        result = {
            **empty,
            "ok": True,
            "error": "",
            "status": "page" if sources else "empty",
            "sources": sources,
            "coverage": coverage,
            "usage": usage,
            "query": query.as_dict(),
            "next_cursor": cursors.get("next"),
            "context_cursors": {key: value for key, value in cursors.items() if key != "next"},
        }
        if not sources and budget["remaining_steps"] > 0:
            result["hint"] = _EMPTY_SEARCH_HINT if query.action == "search" else _EMPTY_RANGE_HINT
        return result
    except SourceQueryError as exc:
        error_code = str(exc)
        rejected_payload = {**empty, "error": error_code}
        detail, hint = explain_source_query_error(error_code, parameters)
        if detail:
            rejected_payload["detail"] = clean_text(detail, 240)
        if hint:
            rejected_payload["hint"] = clean_text(hint, 240)
        return rejected_payload
