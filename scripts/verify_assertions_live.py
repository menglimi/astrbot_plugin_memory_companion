"""Real-model check for the assertion layer. Run this on a live AstrBot host.

This container has no LLM credential, so the numbers that matter most -- how
well the model actually distils assertions -- cannot be produced here. This
script is that measurement, and it runs against whatever provider the host is
already configured with.

    python -X utf8 scripts/verify_assertions_live.py --provider openai --model gpt-4o-mini

It writes a realistic multi-session conversation into a throwaway store, drives
the real summary provider, and then reports:

* how many assertions the model produced, kept, and refused (with reasons)
* how many of the deliberately planted facts survived
* whether fabricated and non-promotable claims were stopped
* whether a repeated fact merged instead of duplicating

Requires: ``OPENAI_API_KEY`` or ``DEEPSEEK_API_KEY`` in the environment, or
``--base-url`` plus ``--api-key``. Never touches a real memory database.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.assertions import (  # noqa: E402
    ASSERTION_MEMORY_TYPE,
    claim_is_personal_fact,
    normalize_assertion,
)
from core.models import SessionContext  # noqa: E402
from core.service import MemoryCompanionService  # noqa: E402

CTX = SessionContext(
    session_id="qq:FriendMessage:naliling", scope="private", platform="qq",
    user_id="naliling", user_name="naliling", bot_id="b1",
)

# Planted facts: each is something the old regex extractor could not represent.
PLANTED = {
    "t5": "累的时候会咬后槽牙",
    "t8": "母亲的忌日是每年十一月三号",
    "t9": "睡觉必须开着白噪音",
    "t10": "同一件事只说一次，不喜欢重复",
    "t11": "生气时会先沉默三秒再说话",
}

# Must never become a long-term fact, though each is literally present.
FORBIDDEN = {
    "t12": "转述他人",
    "t13": "角色扮演台词",
    "t14": "临时状态",
    "t15": "未来计划",
}

CHAT = [
    ("t1", "我今天真的好累啊 加班到现在才吃上饭", "2026-10-01T20:01:00+08:00"),
    ("t2", "昨晚我一共才睡了六个小时 一直在想事情", "2026-10-01T20:02:00+08:00"),
    ("t3", "我不是不开心 就是有点累", "2026-10-01T20:03:00+08:00"),
    ("t4", "明天还要早起 真的不想去上班", "2026-10-01T20:04:00+08:00"),
    ("t5", "我一累就咬后槽牙 小时候就这样", "2026-10-01T20:05:00+08:00"),
    ("t6", "我最喜欢喝冰美式 不加糖", "2026-10-01T20:06:00+08:00"),
    ("t7", "我不吃香菜 一点点都不行", "2026-10-01T20:07:00+08:00"),
    ("t8", "我妈忌日是每年十一月三号", "2026-10-01T20:08:00+08:00"),
    ("t9", "我睡觉必须开着白噪音 不开就睡不着", "2026-10-01T20:09:00+08:00"),
    ("t10", "我跟他说过一次就够了 不喜欢重复", "2026-10-01T20:10:00+08:00"),
    ("t11", "他生气的时候会先沉默三秒 然后才说话", "2026-10-01T20:11:00+08:00"),
    ("t12", "他说他最讨厌香菜 我觉得可能是瞎说", "2026-10-01T20:12:00+08:00"),
    ("t13", "（角色扮演）我是刺客代号十七 今晚行动", "2026-10-01T20:13:00+08:00"),
    ("t14", "今天有点累 明天就好了", "2026-10-01T20:14:00+08:00"),
    ("t15", "我打算下周开始每天跑五公里", "2026-10-01T20:15:00+08:00"),
    ("t16", "先这样 我去洗澡了", "2026-10-01T20:16:00+08:00"),
]

SECOND_SESSION = [
    ("u1", "我一累还是咬后槽牙", "2026-10-03T21:01:00+08:00"),
    ("u2", "我妈忌日还是每年十一月三号", "2026-10-03T21:02:00+08:00"),
]


class OpenAICompatibleProvider:
    """Minimal chat provider over the OpenAI-compatible HTTP API."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.calls = 0
        self.prompts: list[str] = []

    async def text_chat(self, *, prompt: str = "", system_prompt: str = "",
                        request_max_retries: int = 0, **kwargs):
        import aiohttp

        self.calls += 1
        self.prompts.append(prompt)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt or "你是一个 JSON 输出助手。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as response:
                body = await response.json()
        if response.status >= 400:
            raise RuntimeError(f"provider HTTP {response.status}: {body}")
        text = body["choices"][0]["message"]["content"]

        class _Result:
            completion_text = text

        return _Result()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="deepseek",
                        choices=("deepseek", "openai", "moonshot"))
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    return parser.parse_args()


DEFAULTS = {
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    "moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-32k", "MOONSHOT_API_KEY"),
}


async def main() -> int:
    args = parse_args()
    base_url, default_model, key_name = DEFAULTS[args.provider]
    api_key = args.api_key or os.environ.get(key_name, "")
    model = args.model or default_model
    if not api_key:
        print(f"缺少 API key：请设置环境变量 {key_name}，或用 --api-key 传入。", file=sys.stderr)
        return 2
    base_url = args.base_url or base_url
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print("需要 aiohttp：pip install aiohttp", file=sys.stderr)
        return 2

    provider = OpenAICompatibleProvider(base_url, api_key, model)
    with tempfile.TemporaryDirectory() as tmp:
        config = {
            "startup": {"background_grace_seconds": 60},
            "memory_summary": {
                "min_events": 1, "trigger_event_count": 1,
                "max_events_per_summary": 20, "max_retries": 3,
                "retry_backoff_seconds": 0, "max_calls_per_session_hour": 60,
                "provider_timeout_seconds": 180,
            },
        }
        service = MemoryCompanionService(
            context=None, config=config, plugin_root=ROOT, data_dir=Path(tmp))
        service._schedule_memory_embedding = lambda *args: None

        async def attempts(*args, **kwargs):
            return [{"provider": provider, "provider_id": "live", "source": "primary"}]

        service._summary_provider_attempts = attempts

        async def feed(rows):
            for event_id, text, when in rows:
                await service.store.add_timeline_event(
                    event_type="user_message", session_id=CTX.session_id, scope=CTX.scope,
                    subject_id=CTX.user_id, object_id=CTX.bot_id, content=text,
                    metadata={"sender_name": "naliling"}, occurred_at=when)

        await feed(CHAT)
        summary_id = await service.maybe_summarize_session(CTX)
        first = _read_assertions(service)
        print(f"\n模型调用 {provider.calls} 次；摘要落库={bool(summary_id)}")
        print(f"断言写入 {len(first)} 条\n")

        await feed(SECOND_SESSION)
        await service.maybe_summarize_session(CTX)
        second = _read_assertions(service)

        _report(first, second, service)
        service.close()
    return 0


def _read_assertions(service) -> list[dict]:
    rows = service.store._conn.execute(
        "SELECT content, lifecycle, review_status, "
        "json_extract(metadata,'$.profile_dimension') AS dimension, "
        "json_extract(metadata,'$.assertion_evidence_refs') AS refs, "
        "json_extract(metadata,'$.assertion_evidence_count') AS sources "
        "FROM memories WHERE memory_type=? ORDER BY dimension", (ASSERTION_MEMORY_TYPE,)
    ).fetchall()
    return [dict(row) for row in rows]


def _report(first: list[dict], second: list[dict], service) -> None:
    by_ref: dict[str, list[dict]] = {}
    for row in second:
        for ref in json.loads(row["refs"] or "[]"):
            by_ref.setdefault(ref, []).append(row)

    print("=== 1. 埋入的长期细节是否被提炼出来 ===")
    hits = 0
    for event_id, value in PLANTED.items():
        found = by_ref.get(event_id, [])
        ok = bool(found)
        hits += ok
        print(f"  {'HIT ' if ok else 'MISS'}  {value:26s} "
              f"{('<dimension=' + found[0]['dimension'] + '>') if ok else ''}")
    print(f"  命中 {hits}/{len(PLANTED)}")

    print("\n=== 2. 不该成为长期断言的内容是否被拦下 ===")
    leaks = 0
    for event_id, label in FORBIDDEN.items():
        found = [r for r in by_ref.get(event_id, []) if r["lifecycle"] == "stable_memory"]
        leaks += bool(found)
        state = "LEAKED: " + found[0]["content"] if found else "blocked"
        print(f"  {'LEAK' if found else 'OK  '}  {label:12s} {state}")
    print(f"  泄漏 {leaks}/{len(FORBIDDEN)}")

    print("\n=== 3. 同一断言再次提及是否合并 ===")
    for value in ("累的时候会咬后槽牙", "母亲的忌日是每年十一月三号"):
        rows = [r for r in second if r["content"].strip().startswith(value[:6])]
        count = sum(1 for r in second if r["content"] == value)
        print(f"  {value:22s} 总条数={count} "
              f"来源累计={rows[0]['sources'] if rows else '-'} "
              f"（两轮后仍应为 1 条、来源 2）")
    grew = len(second) - len(first)
    print(f"  第二轮新增 {grew} 条（若全部为已存在断言的合并，应为 0）")

    print("\n=== 4. 跨窗口可见性 ===")
    rows = service.store._conn.execute(
        "SELECT DISTINCT visibility, scope FROM memories WHERE memory_type=?",
        (ASSERTION_MEMORY_TYPE,)).fetchall()
    print(f"  可见性集合={[tuple(r) for r in rows]}（私聊提炼应为 private_pair/private）")
    for row in second:
        if row["lifecycle"] == "stable_memory":
            continue
        print(f"  候选（非稳定）: {row['content']} [{row['review_status']}]")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))