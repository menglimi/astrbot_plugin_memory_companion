from __future__ import annotations

import re
from typing import Any

from .identity import entity_for_current_target, entity_for_user, looks_like_command
from .models import EntityRef, MemoryRecord, SessionContext, clean_text


class MemoryClassifier:
    def __init__(self, capture_min_chars: int = 2):
        self.capture_min_chars = max(1, int(capture_min_chars or 1))

    def from_user_message(self, ctx: SessionContext) -> MemoryRecord | None:
        text = clean_text(ctx.message_text, 1800)
        if len(text) < self.capture_min_chars or looks_like_command(text):
            return None

        visibility = "group_public" if ctx.scope == "group" else "private_pair"
        content = self._format_user_content(ctx, text)
        importance = self._importance_for_text(text)
        return MemoryRecord(
            memory_type="conversation_event",
            subject=entity_for_user(ctx),
            object=entity_for_current_target(ctx),
            scope=ctx.scope,
            session_id=ctx.session_id,
            platform=ctx.platform,
            message_id=ctx.message_id,
            group_id=ctx.group_id,
            visibility=visibility,
            sayability="indirect",
            reality_level="observed_utterance",
            lifecycle="raw_event",
            content=content,
            evidence=text,
            confidence=0.72,
            importance=importance,
            review_status="auto",
            tags=["user_message", ctx.scope],
            metadata={"raw_text": text, "sender_name": ctx.user_name, "sender_id": ctx.user_id},
        )

    def from_bot_response(self, ctx: SessionContext, response_text: str) -> MemoryRecord | None:
        text = clean_text(response_text, 2000)
        if len(text) < self.capture_min_chars or looks_like_command(text):
            return None
        visibility = "group_public" if ctx.scope == "group" else "private_pair"
        target = entity_for_current_target(ctx)
        content = self._format_bot_content(ctx, text)
        return MemoryRecord(
            memory_type="self_action",
            subject=EntityRef.bot_self(bot_id=ctx.bot_id),
            object=target,
            scope=ctx.scope,
            session_id=ctx.session_id,
            platform=ctx.platform,
            message_id=ctx.message_id,
            group_id=ctx.group_id,
            visibility=visibility,
            sayability="direct",
            reality_level="bot_action",
            lifecycle="raw_event",
            content=content,
            evidence=text,
            confidence=0.9,
            importance=self._importance_for_text(text),
            review_status="auto",
            tags=["bot_response", ctx.scope],
            metadata={"response_text": text, "owner_bot_id": clean_text(ctx.bot_id, 120) or "self"},
        )

    def derived_user_memories(self, ctx: SessionContext, source_memory_id: str = "") -> list[MemoryRecord]:
        text = clean_text(ctx.message_text, 1800)
        if len(text) < self.capture_min_chars or looks_like_command(text):
            return []

        records: list[MemoryRecord] = []
        visibility = "group_public" if ctx.scope == "group" else "private_pair"
        base = {
            "subject": entity_for_user(ctx),
            "object": entity_for_current_target(ctx),
            "scope": ctx.scope,
            "session_id": ctx.session_id,
            "platform": ctx.platform,
            "message_id": ctx.message_id,
            "group_id": ctx.group_id,
            "visibility": visibility,
            "sayability": "direct",
            "reality_level": "real_user_fact",
            "lifecycle": "stable_memory",
            "confidence": 0.82,
            "importance": 0.68,
            "review_status": "auto",
            "source_plugin": "memory_companion",
        }

        fact = self._extract_preference_or_profile(ctx, text)
        if fact:
            records.append(
                MemoryRecord(
                    memory_type=fact["memory_type"],
                    content=fact["content"],
                    evidence=text,
                    tags=fact["tags"],
                    metadata={"source_memory_id": source_memory_id, "extractor": "rule_v1"},
                    **base,
                )
            )

        return records

    def external_record(
        self,
        *,
        content: str,
        memory_type: str = "external_event",
        subject: EntityRef | None = None,
        object: EntityRef | None = None,
        scope: str = "unknown",
        session_id: str = "",
        platform: str = "",
        message_id: str = "",
        group_id: str = "",
        visibility: str = "bot_self",
        sayability: str = "direct",
        reality_level: str = "bot_action",
        lifecycle: str = "stable_memory",
        confidence: float = 0.85,
        importance: float = 0.5,
        review_status: str = "auto",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        source_plugin: str = "external",
        occurred_at: str = "",
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_type=memory_type,
            subject=subject or EntityRef.bot_self(),
            object=object or EntityRef(kind="session", id=session_id, role="target_session"),
            scope=scope,
            session_id=session_id,
            platform=platform,
            message_id=message_id,
            group_id=group_id,
            visibility=visibility,
            sayability=sayability,
            reality_level=reality_level,
            lifecycle=lifecycle,
            content=clean_text(content, 4000),
            evidence=clean_text(content, 4000),
            confidence=confidence,
            importance=importance,
            review_status=review_status,
            tags=tags or ["external"],
            metadata=metadata or {},
            occurred_at=clean_text(occurred_at, 80),
            source_plugin=source_plugin,
        )

    def _format_user_content(self, ctx: SessionContext, text: str) -> str:
        if ctx.scope == "group":
            name = ctx.user_name or ctx.user_id or "某个群成员"
            return f"群 {ctx.group_id or 'unknown'} 中，{name} 说过：{text}"
        name = ctx.user_name or ctx.user_id or "当前私聊用户"
        return f"私聊中，{name} 说过：{text}"

    def _format_bot_content(self, ctx: SessionContext, text: str) -> str:
        if ctx.scope == "group":
            return f"Bot 在群 {ctx.group_id or 'unknown'} 回复过：{text}"
        name = ctx.user_name or ctx.user_id or "当前私聊用户"
        return f"Bot 在与 {name} 的私聊中回复过：{text}"

    def _importance_for_text(self, text: str) -> float:
        score = 0.25
        if len(text) >= 30:
            score += 0.1
        if len(text) >= 80:
            score += 0.1
        important_markers = (
            "记住", "别忘", "喜欢", "讨厌", "生日", "名字", "主人", "朋友", "约定", "以后", "密码", "作品", "写了",
            "承诺", "答应", "保证", "发誓", "过敏", "不能吃", "习惯", "信任", "在意", "害怕", "担心", "难过",
            "叫我", "我是", "职业", "从事", "专业", "别问我", "不喜欢别人", "底线",
            "很重要", "最重要", "特别在意", "舍不得", "不能接受", "雷区", "星座", "血型",
            "在乎", "珍惜", "依赖", "孤独", "焦虑", "压力大",
        )
        if any(marker in text for marker in important_markers):
            score += 0.25
        return min(0.85, score)

    def _extract_preference_or_profile(self, ctx: SessionContext, text: str) -> dict[str, Any] | None:
        name = ctx.user_name or ctx.user_id or "当前用户"
        patterns = [
            # 偏好 - 基础
            (r"(?:我|咱|俺)(?:很|最|超|特别|有点|真的|真的好|超级)?喜欢(.{1,40})", "user_preference", "喜欢"),
            (r"(?:我|咱|俺)(?:很|最|超|特别|真的)?讨厌(.{1,40})", "user_preference", "讨厌"),
            (r"(?:我|咱|俺)(?:不喜欢|不爱|不太喜欢)(.{1,40})", "user_preference", "不喜欢"),
            (r"(?:我|咱|俺)(?:最爱|超爱|最喜欢|特别喜欢|真的好爱)(.{1,40})", "user_preference", "最爱"),
            (r"(?:我|咱|俺)(?:对|对于)(.{2,30})(?:过敏|不能吃|不能碰|受不了)", "user_preference", "过敏/禁忌"),
            # 身份/画像
            (r"(?:我|咱|俺)(?:的)?生日(?:是|在)?(.{2,20})", "user_profile", "生日"),
            (r"(?:以后|之后)?(?:叫我|喊我)(.{1,20})", "user_profile", "称呼"),
            (r"(?:我|咱|俺)(?:是|在)(?:做|干|从事)(.{2,40})", "user_profile", "职业"),
            (r"(?:我|咱|俺)(?:是|在)(?:学|读)(?:的是?)?(.{2,40})", "user_profile", "专业/学业"),
            (r"(?:我|咱|俺)(?:是|属于)(.{2,12})(?:座|型)", "user_profile", "星座/血型"),
            (r"(?:我|咱|俺)(?:的)?(?:星座|血型)(?:是)?(.{2,12})", "user_profile", "星座/血型"),
            # 明确要求记住
            (r"(?:记住|别忘了?|你要记得|务必记得|一定记得)(.{2,80})", "explicit_memory", "明确要求"),
            # 承诺/约定
            (r"(?:我|咱|俺)(?:保证|发誓|答应你|跟你约定|说好了)(.{2,60})", "explicit_memory", "承诺/约定"),
            (r"(?:下次|以后|明天|回头|之后)(?:一定|肯定会|一定会|保证)(.{2,40})", "explicit_memory", "承诺"),
            # 关系表达
            (r"(?:你|你呀)(?:是我|是咱)(?:最|特别|很)?(.{2,20})(?:朋友|伙伴|重要的人|信任的人)", "relationship_claim", "关系定位"),
            (r"(?:我|咱|俺)(?:很|特别|真的|最)?(?:信任|依赖|在意|在乎|珍惜)(.{2,30})", "relationship_claim", "关系表达"),
            # 情绪状态
            (r"(?:我|咱|俺)(?:最近|今天|现在|这阵子|这会儿)?(?:很|有点|真的|好|特别)?(?:累|压力大|焦虑|低落|开心|难过|孤独|害怕|不安)(.{0,40})", "user_preference", "情绪状态"),
            # 习惯
            (r"(?:我|咱|俺)(?:一般|通常|习惯|每次|总是|经常)(.{2,40})", "user_habit", "习惯"),
            # 边界/雷区
            (r"(?:我|咱|俺)(?:不喜欢别人|讨厌别人|不希望)(.{2,40})", "user_preference", "边界"),
            (r"(?:别问我|不要问我|不想聊)(.{0,30})", "user_preference", "雷区"),
        ]
        for pattern, memory_type, label in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = clean_text(match.group(1).strip(" ，。！？!?.：:"), 80)
            if not value:
                continue
            return {
                "memory_type": memory_type,
                "content": f"{name}明确表达过：{label} {value}",
                "tags": ["stable_fact", memory_type, label],
            }
        return None
