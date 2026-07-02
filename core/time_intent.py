from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import clean_text


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class TimeIntent:
    active: bool = False
    label: str = ""
    start_at: str = ""
    end_at: str = ""
    display_start: str = ""
    display_end: str = ""
    summary_like: bool = False
    source: str = ""

    @property
    def display_range(self) -> str:
        if not self.active:
            return ""
        if self.display_start == self.display_end:
            return self.display_start
        return f"{self.display_start} 至 {self.display_end}"


def parse_time_intent(text: str, *, now: datetime | None = None) -> TimeIntent:
    compact = re.sub(r"\s+", "", clean_text(text, 1000)).lower()
    if not compact:
        return TimeIntent()

    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    current = current.astimezone(LOCAL_TZ)
    today = current.replace(hour=0, minute=0, second=0, microsecond=0)
    summary_like = _summary_like(compact)

    start: datetime | None = None
    end: datetime | None = None
    source = ""

    if "前天" in compact:
        start, end, source = today - timedelta(days=2), today - timedelta(days=1), "day_before_yesterday"
    elif "昨天" in compact or "昨日" in compact:
        start, end, source = today - timedelta(days=1), today, "yesterday"
    elif "今天" in compact or "今日" in compact:
        start, end, source = today, today + timedelta(days=1), "today"
    elif any(marker in compact for marker in ("上个月", "上月")):
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        start = last_prev_month.replace(day=1)
        end = first_this_month
        source = "previous_month"
    elif any(marker in compact for marker in ("这个月", "本月", "这月")):
        start, end, source = today.replace(day=1), today + timedelta(days=1), "current_month"
    elif any(marker in compact for marker in ("最近一个月", "近一个月", "过去一个月")):
        start, end, source = today - timedelta(days=30), today + timedelta(days=1), "recent_month"
    elif "上周" in compact or "上一周" in compact:
        this_monday = today - timedelta(days=today.weekday())
        start, end, source = this_monday - timedelta(days=7), this_monday, "previous_week"
    elif any(marker in compact for marker in ("本周", "这周", "这一周")):
        start, end, source = today - timedelta(days=today.weekday()), today + timedelta(days=1), "current_week"
    elif any(marker in compact for marker in ("最近一周", "近一周", "过去一周", "最近7天", "最近七天", "过去7天", "过去七天")):
        start, end, source = today - timedelta(days=7), today + timedelta(days=1), "recent_week"
    else:
        days = _relative_days(compact)
        if days:
            start, end, source = today - timedelta(days=days), today + timedelta(days=1), f"recent_{days}_days"
        elif any(marker in compact for marker in ("这几天", "最近几天", "近几天")):
            start, end, source = today - timedelta(days=3), today + timedelta(days=1), "recent_few_days"
        elif "最近" in compact and summary_like:
            start, end, source = today - timedelta(days=7), today + timedelta(days=1), "recent_default_summary"

    if start is None or end is None:
        return TimeIntent(summary_like=summary_like)

    display_end = (end - timedelta(days=1)).date().isoformat()
    return TimeIntent(
        active=True,
        label=_label_for_source(source),
        start_at=start.astimezone(timezone.utc).isoformat(timespec="seconds"),
        end_at=end.astimezone(timezone.utc).isoformat(timespec="seconds"),
        display_start=start.date().isoformat(),
        display_end=display_end,
        summary_like=summary_like,
        source=source,
    )


def _relative_days(compact: str) -> int:
    match = re.search(r"(最近|过去|近)(\d{1,2})天", compact)
    if match:
        return max(1, min(60, int(match.group(2))))
    chinese_numbers = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    match = re.search(r"(最近|过去|近)([一二两三四五六七八九十])天", compact)
    if match:
        return chinese_numbers.get(match.group(2), 0)
    return 0


def _summary_like(compact: str) -> bool:
    markers = (
        "怎么样",
        "如何",
        "总结",
        "概括",
        "回顾",
        "发生了什么",
        "聊了什么",
        "说了什么",
        "讲了什么",
        "问了什么",
        "做了什么",
        "有什么",
        "有哪些",
        "过得",
        "状态",
        "近况",
        "我最近",
        "最近我",
    )
    return any(marker in compact for marker in markers)


def _label_for_source(source: str) -> str:
    labels = {
        "today": "今天",
        "yesterday": "昨天",
        "day_before_yesterday": "前天",
        "recent_week": "最近一周",
        "current_week": "本周",
        "previous_week": "上周",
        "recent_month": "最近一个月",
        "current_month": "本月",
        "previous_month": "上个月",
        "recent_few_days": "最近几天",
        "recent_default_summary": "最近",
    }
    if source.startswith("recent_") and source.endswith("_days"):
        days = source.removeprefix("recent_").removesuffix("_days")
        return f"最近 {days} 天"
    return labels.get(source, source or "时间窗口")
