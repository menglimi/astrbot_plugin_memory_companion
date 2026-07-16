from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .astrbot_compat import logger
from .models import clean_text, stable_fingerprint


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
QQ_ID = re.compile(r"^[0-9]{5,20}$")


class QQHistoryReader:
    """Read bounded private-message history through an aiocqhttp/OneBot adapter."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def _config_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        config = getattr(self.service, "config", None)
        getter = getattr(config, "int", None)
        value = default
        if callable(getter):
            try:
                value = int(getter(f"historical_chat_import.{key}", default))
            except Exception:
                value = default
        return max(minimum, min(maximum, int(value)))

    def limits(self) -> dict[str, int]:
        return {
            "max_range_days": self._config_int("qq_max_range_days", 31, 1, 31),
            "max_messages": self._config_int("qq_max_messages", 5000, 10, 5000),
            "page_size": self._config_int("qq_page_size", 100, 1, 100),
            "max_pages": self._config_int("qq_max_pages", 100, 1, 200),
            "request_timeout_seconds": self._config_int(
                "qq_request_timeout_seconds", 15, 3, 60
            ),
        }

    @staticmethod
    def _meta_value(meta: Any, key: str) -> str:
        if isinstance(meta, dict):
            return clean_text(meta.get(key), 160)
        return clean_text(getattr(meta, key, ""), 160)

    @staticmethod
    def _call_action(candidate: Any) -> Callable[..., Any] | None:
        if candidate is None:
            return None
        direct = getattr(candidate, "call_action", None)
        if callable(direct):
            return direct
        api = getattr(candidate, "api", None)
        nested = getattr(api, "call_action", None)
        return nested if callable(nested) else None

    def _adapters(self) -> list[dict[str, Any]]:
        context = getattr(self.service, "context", None)
        manager = getattr(context, "platform_manager", None)
        platforms: list[Any] = []
        if manager is not None:
            getter = getattr(manager, "get_insts", None)
            if callable(getter):
                try:
                    platforms = list(getter() or [])
                except Exception:
                    platforms = []
            if not platforms:
                raw = getattr(manager, "platform_insts", []) or []
                platforms = list(raw.values() if isinstance(raw, dict) else raw)

        adapters: list[dict[str, Any]] = []
        seen: set[int] = set()
        used_platform_ids: set[str] = set()
        for index, platform in enumerate(platforms):
            if platform is None or id(platform) in seen:
                continue
            seen.add(id(platform))
            try:
                meta = platform.meta()
            except Exception:
                meta = {}
            platform_name = self._meta_value(meta, "name")
            platform_id = self._meta_value(meta, "id") or clean_text(
                getattr(platform, "id", ""), 160
            )
            description = (
                f"{platform_name} {platform_id} "
                f"{platform.__class__.__module__}.{platform.__class__.__name__}"
            ).lower()
            if not any(token in description for token in ("aiocqhttp", "onebot", "napcat")):
                continue

            caller = None
            for candidate in (
                getattr(platform, "bot", None),
                getattr(platform, "client", None),
                platform,
            ):
                caller = self._call_action(candidate)
                if caller is not None:
                    break
            if caller is None:
                continue
            resolved_platform_id = platform_id or f"aiocqhttp-{index + 1}"
            if resolved_platform_id in used_platform_ids:
                resolved_platform_id = f"{resolved_platform_id}-{index + 1}"
            used_platform_ids.add(resolved_platform_id)
            adapters.append(
                {
                    "platform": platform,
                    "call_action": caller,
                    "platform_id": resolved_platform_id,
                    "platform_name": platform_name or "aiocqhttp",
                }
            )
        return adapters

    async def _call(self, adapter: dict[str, Any], action: str, **kwargs: Any) -> Any:
        caller = adapter["call_action"]
        timeout = self.limits()["request_timeout_seconds"]
        result = caller(action, **kwargs)
        if hasattr(result, "__await__"):
            result = await asyncio.wait_for(result, timeout=timeout)
        return self._result_data(result)

    @staticmethod
    def _result_data(result: Any) -> Any:
        if not isinstance(result, dict):
            return result
        status = clean_text(result.get("status"), 40).lower()
        retcode = result.get("retcode", result.get("code"))
        failed = status in {"failed", "fail", "error", "nok"}
        if retcode not in (None, ""):
            try:
                failed = failed or int(retcode) != 0
            except Exception:
                pass
        if failed:
            message = clean_text(
                result.get("message") or result.get("msg") or result.get("wording"), 240
            )
            raise RuntimeError(message or "OneBot 接口返回失败")
        if "data" in result and (
            status or retcode not in (None, "") or set(result).issubset({"status", "retcode", "code", "message", "msg", "wording", "data"})
        ):
            return result.get("data")
        return result

    async def capabilities(self) -> dict[str, Any]:
        public: list[dict[str, Any]] = []
        for adapter in self._adapters():
            item = {
                "platform_id": adapter["platform_id"],
                "platform_name": adapter["platform_name"],
                "connected": False,
                "history_status": "unavailable",
                "bot_id": "",
                "bot_name": "",
                "implementation": "",
                "implementation_version": "",
                "error": "",
            }
            try:
                login = await self._call(adapter, "get_login_info")
                login = login if isinstance(login, dict) else {}
                version: dict[str, Any] = {}
                try:
                    raw_version = await self._call(adapter, "get_version_info")
                    version = raw_version if isinstance(raw_version, dict) else {}
                except Exception:
                    version = {}
                item["bot_id"] = clean_text(login.get("user_id"), 40)
                item["bot_name"] = clean_text(login.get("nickname"), 80)
                item["implementation"] = clean_text(
                    version.get("app_name")
                    or version.get("app_full_name")
                    or version.get("implementation"),
                    100,
                )
                item["implementation_version"] = clean_text(
                    version.get("app_version") or version.get("version"), 80
                )
                item["connected"] = bool(item["bot_id"])
                item["history_status"] = "ready" if item["connected"] else "unavailable"
            except Exception as exc:
                item["error"] = clean_text(exc, 240)
            public.append(item)
        return {
            "available": any(item["connected"] for item in public),
            "adapters": public,
            "limits": self.limits(),
            "source": "onebot_get_friend_msg_history",
        }

    def _select_adapter(self, platform_id: str) -> dict[str, Any]:
        adapters = self._adapters()
        if not adapters:
            raise ValueError("没有找到已连接的 aiocqhttp/OneBot QQ 适配器")
        selected_id = clean_text(platform_id, 160)
        if selected_id:
            for adapter in adapters:
                if adapter["platform_id"] == selected_id:
                    return adapter
            raise ValueError("选择的 QQ 适配器已离线，请重新检测")
        if len(adapters) > 1:
            raise ValueError("检测到多个 QQ 适配器，请先选择当前 Bot 连接")
        return adapters[0]

    @staticmethod
    def _parse_local(value: Any, label: str) -> datetime:
        text = clean_text(value, 80)
        if not text:
            raise ValueError(f"{label}不能为空")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label}格式无效") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TZ)
        return parsed.astimezone(LOCAL_TZ)

    def _validated_range(self, start_at: Any, end_at: Any) -> tuple[datetime, datetime]:
        start = self._parse_local(start_at, "开始时间")
        end = self._parse_local(end_at, "结束时间")
        if end <= start:
            raise ValueError("结束时间必须晚于开始时间")
        max_days = self.limits()["max_range_days"]
        if end - start > timedelta(days=max_days):
            raise ValueError(f"单次读取时间范围不能超过 {max_days} 天")
        if end > datetime.now(LOCAL_TZ) + timedelta(minutes=5):
            raise ValueError("结束时间不能晚于当前时间")
        return start, end

    async def _friend_name(self, adapter: dict[str, Any], user_id: int) -> str:
        for kwargs in ({"user_id": user_id, "no_cache": True}, {"user_id": user_id}):
            try:
                result = await self._call(adapter, "get_stranger_info", **kwargs)
                if isinstance(result, dict):
                    name = clean_text(result.get("remark") or result.get("nickname"), 80)
                    if name:
                        return name
            except Exception:
                continue
        return ""

    async def _history_page(
        self,
        adapter: dict[str, Any],
        *,
        user_id: int,
        cursor: int,
        count: int,
    ) -> list[dict[str, Any]]:
        variants = (
            {
                "user_id": user_id,
                "message_seq": cursor,
                "count": count,
                "reverse_order": False,
            },
            {"user_id": user_id, "message_seq": cursor, "count": count},
            {
                "user_id": str(user_id),
                "message_seq": cursor,
                "count": count,
                "reverse_order": False,
            },
        )
        last_error: Exception | None = None
        for params in variants:
            try:
                payload = await self._call(adapter, "get_friend_msg_history", **params)
                return self._extract_history_messages(payload)
            except Exception as exc:
                last_error = exc
        message = clean_text(last_error, 240) if last_error is not None else "未知错误"
        raise RuntimeError(f"QQ 历史接口不可用：{message}")

    @classmethod
    def _extract_history_messages(cls, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("messages", "message_list", "list"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        nested = payload.get("data")
        if nested is not payload:
            return cls._extract_history_messages(nested)
        return []

    @staticmethod
    def _timestamp(raw: dict[str, Any]) -> float:
        value = raw.get("time", raw.get("timestamp", raw.get("send_time")))
        try:
            number = float(value)
            if number > 10_000_000_000:
                number /= 1000.0
            return number if number > 0 else 0.0
        except Exception:
            pass
        text = clean_text(value, 80)
        if not text:
            return 0.0
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=LOCAL_TZ)
            return parsed.timestamp()
        except ValueError:
            return 0.0

    @staticmethod
    def _segment_text(segment: dict[str, Any]) -> str:
        kind = clean_text(segment.get("type"), 40).lower()
        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
        if kind == "text":
            return str(data.get("text") or "")
        if kind == "at":
            target = clean_text(data.get("qq") or data.get("user_id"), 40)
            return "@全体成员" if target == "all" else (f"@{target}" if target else "[提及]")
        labels = {
            "image": "[图片]",
            "record": "[语音]",
            "video": "[视频]",
            "file": "[文件]",
            "face": "[表情]",
            "mface": "[动画表情]",
            "reply": "[回复消息]",
            "forward": "[转发消息]",
            "json": "[卡片消息]",
            "xml": "[卡片消息]",
            "location": "[位置]",
            "music": "[音乐]",
            "dice": "[骰子]",
            "rps": "[猜拳]",
            "poke": "[戳一戳]",
        }
        return labels.get(kind, f"[{kind or '消息'}]")

    @classmethod
    def _content(cls, raw: dict[str, Any]) -> str:
        message = raw.get("message")
        if isinstance(message, list):
            parts = [cls._segment_text(item) for item in message if isinstance(item, dict)]
            text = "".join(part for part in parts if part)
        elif isinstance(message, str):
            text = message
        else:
            text = str(raw.get("raw_message") or "")
        replacements = {
            "image": "[图片]",
            "record": "[语音]",
            "video": "[视频]",
            "file": "[文件]",
            "face": "[表情]",
            "reply": "[回复消息]",
            "forward": "[转发消息]",
            "json": "[卡片消息]",
            "xml": "[卡片消息]",
        }

        def cq_label(match: re.Match[str]) -> str:
            return replacements.get(match.group(1).lower(), f"[{match.group(1)}]")

        text = re.sub(r"\[CQ:([a-zA-Z0-9_]+)(?:,[^\]]*)?\]", cq_label, text)
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            text = "[消息]"
        return text[:15999].rstrip() + ("…" if len(text) > 15999 else "")

    @staticmethod
    def _sequence(raw: dict[str, Any]) -> int:
        for key in ("message_seq", "msg_seq", "sequence", "seq"):
            try:
                value = int(raw.get(key) or 0)
            except Exception:
                value = 0
            if value > 0:
                return value
        return 0

    @staticmethod
    def _source_message_id(raw: dict[str, Any]) -> str:
        for key in ("message_id", "real_id", "msg_id"):
            value = clean_text(raw.get(key), 120)
            if value:
                return value
        return ""

    @classmethod
    def _dedupe_key(cls, raw: dict[str, Any]) -> str:
        message_id = cls._source_message_id(raw)
        if message_id:
            return f"id:{message_id}"
        sender = raw.get("sender") if isinstance(raw.get("sender"), dict) else {}
        return "fallback:" + stable_fingerprint(
            cls._timestamp(raw),
            sender.get("user_id") or raw.get("user_id"),
            cls._content(raw),
        )

    async def read(
        self,
        *,
        platform_id: str,
        user_id: str,
        start_at: Any,
        end_at: Any,
    ) -> dict[str, Any]:
        target_id = clean_text(user_id, 40)
        if not QQ_ID.fullmatch(target_id):
            raise ValueError("目标 QQ 必须是 5 到 20 位纯数字")
        start, end = self._validated_range(start_at, end_at)
        adapter = self._select_adapter(platform_id)
        limits = self.limits()

        login = await self._call(adapter, "get_login_info")
        login = login if isinstance(login, dict) else {}
        bot_id = clean_text(login.get("user_id"), 40)
        if not QQ_ID.fullmatch(bot_id):
            raise ValueError("当前 QQ 适配器没有返回有效的 Bot QQ")
        if bot_id == target_id:
            raise ValueError("目标 QQ 不能与当前 Bot QQ 相同")
        bot_name = clean_text(login.get("nickname"), 80) or f"Bot {bot_id}"
        user_name = await self._friend_name(adapter, int(target_id)) or f"QQ {target_id}"

        cursor = 0
        pages = 0
        scanned = 0
        duplicate_count = 0
        invalid_time_count = 0
        selected_raw: list[dict[str, Any]] = []
        seen: set[str] = set()
        reached_start = False
        exhausted = False
        cursor_stalled = False
        message_limit_hit = False
        previous_cursor: int | None = None
        start_ts = start.timestamp()
        end_ts = end.timestamp()

        while pages < limits["max_pages"]:
            page = await self._history_page(
                adapter,
                user_id=int(target_id),
                cursor=cursor,
                count=limits["page_size"],
            )
            pages += 1
            if not page:
                exhausted = True
                break
            scanned += len(page)
            page_times: list[float] = []
            for raw in page:
                key = self._dedupe_key(raw)
                if key in seen:
                    duplicate_count += 1
                    continue
                seen.add(key)
                timestamp = self._timestamp(raw)
                if timestamp <= 0:
                    invalid_time_count += 1
                    continue
                page_times.append(timestamp)
                if start_ts <= timestamp <= end_ts:
                    selected_raw.append(raw)
                    if len(selected_raw) > limits["max_messages"]:
                        message_limit_hit = True
                        break
            if message_limit_hit:
                break
            if page_times and min(page_times) <= start_ts:
                reached_start = True
                break
            if len(page) < limits["page_size"]:
                exhausted = True
                break
            sequences = [self._sequence(item) for item in page]
            sequences = [value for value in sequences if value > 0]
            if not sequences:
                cursor_stalled = True
                break
            next_cursor = min(sequences)
            if next_cursor == cursor or next_cursor == previous_cursor:
                cursor_stalled = True
                break
            previous_cursor, cursor = cursor, next_cursor

        max_pages_hit = pages >= limits["max_pages"] and not (reached_start or exhausted)
        truncated = message_limit_hit or max_pages_hit or cursor_stalled
        warnings: list[str] = []
        if message_limit_hit:
            warnings.append(f"该时段超过 {limits['max_messages']} 条，只保留最近的上限数量")
        if max_pages_hit:
            warnings.append("已达到分页扫描上限，所选时段可能没有读取完整")
        if cursor_stalled:
            warnings.append("接口未返回可继续分页的消息序号，预览可能只包含最近一页")
        if invalid_time_count:
            warnings.append(f"跳过 {invalid_time_count} 条没有有效时间的消息")

        selected_raw.sort(
            key=lambda item: (
                self._timestamp(item),
                self._sequence(item),
                self._source_message_id(item),
            )
        )
        selected_raw = selected_raw[-limits["max_messages"] :]
        if not selected_raw:
            suffix = "；接口分页未能覆盖到该时段" if truncated else ""
            raise ValueError(f"所选时段没有读取到可导入的私聊消息{suffix}")

        user_speaker = user_name
        bot_speaker = bot_name
        if user_speaker == bot_speaker:
            user_speaker = f"{user_name}（用户）"
            bot_speaker = f"{bot_name}（Bot）"
        messages: list[dict[str, Any]] = []
        speakers = {user_speaker: 0, bot_speaker: 0}
        timestamp_counts: dict[str, int] = {}
        for sequence, raw in enumerate(selected_raw, start=1):
            timestamp = self._timestamp(raw)
            local = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(LOCAL_TZ)
            sender = raw.get("sender") if isinstance(raw.get("sender"), dict) else {}
            sender_id = clean_text(
                sender.get("user_id") or raw.get("sender_id") or raw.get("user_id"), 40
            )
            is_bot = sender_id == bot_id
            speaker = bot_speaker if is_bot else user_speaker
            speakers[speaker] += 1
            content = self._content(raw)
            source_message_id = self._source_message_id(raw)
            source_sequence = self._sequence(raw)
            internal_id = "qqhist_" + stable_fingerprint(
                adapter["platform_id"],
                bot_id,
                target_id,
                source_message_id or source_sequence,
                timestamp,
                sender_id,
                content,
            )[:32]
            local_time = local.isoformat(timespec="seconds")
            timestamp_counts[local_time] = timestamp_counts.get(local_time, 0) + 1
            messages.append(
                {
                    "sequence": sequence,
                    "speaker": speaker,
                    "raw_time": local.strftime("%Y-%m-%d %H:%M:%S"),
                    "local_time": local_time,
                    "occurred_at": local.astimezone(timezone.utc).isoformat(timespec="seconds"),
                    "inferred_year": False,
                    "source_line": sequence,
                    "content": content,
                    "message_id": internal_id,
                    "source_message_id": source_message_id,
                    "source_message_seq": source_sequence,
                    "source_platform_id": adapter["platform_id"],
                    "source_kind": "qq_history",
                    "source_sender_id": sender_id,
                }
            )

        source_basis = [
            {
                "id": item["source_message_id"] or item["message_id"],
                "seq": item["source_message_seq"],
                "time": item["occurred_at"],
                "sender": item["source_sender_id"],
                "content": item["content"],
            }
            for item in messages
        ]
        source_hash = hashlib.sha256(
            json.dumps(source_basis, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        dialogue_chars = sum(len(re.sub(r"\s+", "", item["content"])) for item in messages)
        stats = {
            "line_count": len(messages),
            "message_count": len(messages),
            "speaker_count": len(speakers),
            "speakers": dict(speakers),
            "first_at": messages[0]["local_time"],
            "last_at": messages[-1]["local_time"],
            "inferred_year_count": 0,
            "time_inversion_count": 0,
            "chronologically_reordered": False,
            "duplicate_timestamp_groups": sum(1 for count in timestamp_counts.values() if count > 1),
            "empty_message_count": 0,
            "header_like_body_count": 0,
            "header_like_body_samples": [],
            "unicode_chars": sum(len(item["content"]) for item in messages),
            "non_whitespace_chars": dialogue_chars,
            "dialogue_chars": dialogue_chars,
        }
        source_metadata = {
            "platform_id": adapter["platform_id"],
            "platform_name": adapter["platform_name"],
            "bot_id": bot_id,
            "bot_name": bot_name,
            "user_id": target_id,
            "user_name": user_name,
            "start_at": start.isoformat(timespec="minutes"),
            "end_at": end.isoformat(timespec="minutes"),
        }
        read_stats = {
            "pages": pages,
            "scanned_messages": scanned,
            "selected_messages": len(messages),
            "duplicates_removed": duplicate_count,
            "invalid_time_messages": invalid_time_count,
            "reached_start": reached_start,
            "history_exhausted": exhausted,
            "complete": not truncated,
        }
        identity_context = {
            "available": True,
            "source": "qq_history",
            "matches": {
                user_speaker: [{"user_id": target_id, "name": user_name}],
                bot_speaker: [],
            },
            "bot": {
                "self_ids": [bot_id],
                "name": bot_name,
                "aliases": [bot_name],
            },
            "target_users": [{"user_id": target_id, "name": user_name}],
        }
        speaker_suggestions = [
            {
                "speaker": user_speaker,
                "message_count": speakers[user_speaker],
                "suggested_role": "user",
                "confidence": "high",
                "reasons": [f"OneBot 发送者 QQ 与目标账号 {target_id} 对应"],
                "relationship_candidates": [{"user_id": target_id, "name": user_name}],
            },
            {
                "speaker": bot_speaker,
                "message_count": speakers[bot_speaker],
                "suggested_role": "bot",
                "confidence": "high",
                "reasons": [f"OneBot 登录账号 {bot_id} 明确标记为 Bot"],
                "relationship_candidates": [],
            },
        ]
        if any(item["message_count"] == 0 for item in speaker_suggestions):
            warnings.append("所选时段只有一方发言；另一方身份已按 OneBot 登录账号补齐")
        logger.info(
            "[MemoryCompanion] QQ 历史读取完成: adapter=%s user=%s range=%s..%s pages=%s scanned=%s selected=%s truncated=%s",
            adapter["platform_id"],
            target_id,
            start.isoformat(timespec="minutes"),
            end.isoformat(timespec="minutes"),
            pages,
            scanned,
            len(messages),
            truncated,
        )
        return {
            "source_name": f"QQ {target_id} · {start:%Y-%m-%d} 至 {end:%Y-%m-%d}",
            "source_hash": source_hash,
            "source_kind": "qq_history",
            "messages": messages,
            "stats": stats,
            "identity_context": identity_context,
            "speaker_suggestions": speaker_suggestions,
            "source_metadata": source_metadata,
            "read_stats": read_stats,
            "truncated": truncated,
            "warnings": warnings,
        }
