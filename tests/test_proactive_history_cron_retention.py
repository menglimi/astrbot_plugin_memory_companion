"""定时任务的 `[CronJob]` 历史记录不能被主动消息清理误删。

`clean_private_companion_history_text` 原来按行匹配 `send_message_to_user`：
只要一行里出现这个工具名就删掉。AstrBot core 的定时任务（`active_agent` cron）
收尾时会写一条 `[CronJob]` 执行汇报，内容是模型自述，常含「使用
`send_message_to_user` 工具发送了……」，于是整条汇报连同它复述的提醒原文一起
被当成主动消息残留删掉；而这一轮结束会覆写会话历史，等于永久丢失。

这里钉住两条边界：

1. `[CronJob]` / `【CronJob】` 开头的记录整条保留；
2. 只有同一行还带主动消息框架标记时，才按 `send_message_to_user` 删行。
"""
from __future__ import annotations

from types import SimpleNamespace

from core.astrbot_compat import clean_private_companion_history_text, sanitize_request_history


def test_cron_job_record_is_preserved_verbatim():
    record = "[CronJob] 提醒：8 点吃早饭。我使用了 send_message_to_user 工具发送。"

    cleaned, changed, dropped = clean_private_companion_history_text(record)

    assert dropped is False
    assert cleaned == record
    assert changed is False


def test_cron_job_record_keeps_text_when_tts_tags_removed():
    record = "[CronJob] 提醒：8 点吃早饭。[[PCTTS:1]]"

    cleaned, changed, dropped = clean_private_companion_history_text(record)

    assert dropped is False
    assert "8 点吃早饭" in cleaned
    assert "PCTTS" not in cleaned
    assert changed is True


def test_bracketed_cron_prefix_is_preserved_too():
    record = "【CronJob】提醒：明天交报告。send_message_to_user 已投递。"

    cleaned, changed, dropped = clean_private_companion_history_text(record)

    assert dropped is False
    assert cleaned == record
    assert changed is False


def test_tool_name_without_proactive_marker_keeps_the_line():
    text = "用户回了消息，我又用 send_message_to_user 补了一句。"

    cleaned, _, dropped = clean_private_companion_history_text(text)

    assert dropped is False
    assert cleaned == text


def test_tool_name_with_proactive_marker_still_drops_the_line():
    # 整段文本过不了「内部文本」判定（不含强标记组合），只有这一行同时命中
    # 工具名与框架标记，按行删除；其余行保留。
    text = "Private Companion 框架说要用 send_message_to_user 发。\n正常的一句"

    cleaned, changed, dropped = clean_private_companion_history_text(text)

    assert dropped is False
    assert changed is True
    assert "正常的一句" in cleaned
    assert "send_message_to_user" not in cleaned


def test_proactive_block_heading_text_is_still_dropped_whole():
    # 以主动消息标题开头的整段文本仍然整段丢弃（既有行为，本次不改）。
    text = "【主动消息回复上下文】\n（内部内容）\n正常的一句话"

    cleaned, _, dropped = clean_private_companion_history_text(text)

    assert dropped is True
    assert cleaned == ""


def test_tool_call_pair_is_preserved_during_history_cleanup():
    assistant = {
        "role": "assistant",
        "content": "【主动消息回复上下文】",
        "tool_calls": [{"id": "call_1"}],
        "metadata": {"source": "private_companion"},
    }
    tool = {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "send_message_to_user: 主动消息发送失败",
        "metadata": {"source": "private_companion"},
    }
    guidance = {"role": "system", "content": "【主动消息回复上下文】", "metadata": {"source": "private_companion"}}
    request = SimpleNamespace(contexts=[assistant, tool, guidance])

    result = sanitize_request_history(request, clean_proactive_guidance=True)

    assert request.contexts == [assistant, tool]
    assert result == {"before": 3, "after": 2, "removed": 1, "cleaned": 0}
