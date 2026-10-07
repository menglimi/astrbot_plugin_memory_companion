"""High-fidelity regression for the assertion layer.

No LLM key exists in this container, so this cannot measure the model's own
extraction quality. It measures everything *downstream* of the model, against
real conversational material taken from the field report, and reports each
gate's precision explicitly so a weak gate cannot hide behind an aggregate.

Adversarial cases are deliberate: negation flips, reported speech, role-play,
temporary states, relative time, cross-day references, and corrections. Those
are exactly the shapes the old regex extractor could not represent.
"""
from __future__ import annotations

import sys
import asyncio
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.assertions import (  # noqa: E402
    ASSERTION_MEMORY_TYPE,
    assertion_is_promotable,
    cardinality_for,
    claim_is_personal_fact,
    normalize_assertion,
)
from core.models import SessionContext, clean_text
from core.summarizer import MemorySummarizer
from core.store import MemoryStore
from core.models import EntityRef, MemoryRecord

PRIV = SessionContext(
    session_id="qq:FriendMessage:naliling", scope="private", platform="qq",
    user_id="naliling", user_name="naliling", bot_id="b1",
)

# ---- Real conversational material, paraphrased from the field report --------
# (case_id, speaker, text, timestamp)
CHAT = [
    ("t1", "naliling", "我今天真的好累啊 加班到现在才吃上饭", "2026-10-01T20:01:00+08:00"),
    ("t2", "naliling", "昨晚我一共才睡了六个小时 一直在想事情", "2026-10-01T20:02:00+08:00"),
    ("t3", "naliling", "我不是不开心 就是有点累", "2026-10-01T20:03:00+08:00"),
    ("t4", "naliling", "明天还要早起 真的不想去上班", "2026-10-01T20:04:00+08:00"),
    ("t5", "naliling", "他一累就咬后槽牙 小时候就这样", "2026-10-01T20:05:00+08:00"),
    ("t6", "naliling", "我最喜欢喝冰美式 不加糖", "2026-10-01T20:06:00+08:00"),
    ("t7", "naliling", "我不吃香菜 一点点都不行", "2026-10-01T20:07:00+08:00"),
    ("t8", "naliling", "我妈忌日是每年十一月三号", "2026-10-01T20:08:00+08:00"),
    ("t9", "naliling", "我睡觉必须开着白噪音 不开就睡不着", "2026-10-01T20:09:00+08:00"),
    ("t10", "naliling", "我跟他说过一次就够了 不喜欢重复", "2026-10-01T20:10:00+08:00"),
    ("t11", "naliling", "他生气的时候会先沉默三秒 然后才说话", "2026-10-01T20:11:00+08:00"),
    # adversarial: reported speech, role-play, temporary state, plans vs done
    ("t12", "naliling", "他说他最讨厌香菜 我觉得可能是瞎说", "2026-10-01T20:12:00+08:00"),
    ("t13", "naliling", "（角色扮演）我是刺客代号十七 今晚行动", "2026-10-01T20:13:00+08:00"),
    ("t14", "naliling", "今天有点累 明天就好了", "2026-10-01T20:14:00+08:00"),
    ("t15", "naliling", "我打算下周开始每天跑五公里", "2026-10-01T20:15:00+08:00"),
    ("t16", "naliling", "先这样 我去洗澡了", "2026-10-01T20:16:00+08:00"),
    # a later day, same person, corrections and a changed value
    ("t17", "naliling", "我累的时候不咬后槽牙了 现在改成咬指甲", "2026-10-03T21:01:00+08:00"),
    ("t18", "naliling", "我最喜欢的咖啡改成美式了 拿铁太甜", "2026-10-03T21:02:00+08:00"),
    ("t19", "naliling", "我住在杭州 不是上海 我上次说错了", "2026-10-03T21:03:00+08:00"),
]

ROWS = [
    {"id": cid, "content": text, "event_type": "user_message", "scope": "private",
     "subject_id": "naliling", "occurred_at": ts}
    for cid, _speaker, text, ts in CHAT
]
BY_ID = {row["id"]: row for row in ROWS}


def verdict(assertion):
    cited = [BY_ID[ref] for ref in assertion.get("refs", []) if ref in BY_ID]
    return MemorySummarizer.citation_check(assertion["value"], cited)[0]


def build(subject, predicate, value, refs, *, polarity="positive", durability="stable"):
    return normalize_assertion({
        "subject": subject, "predicate": predicate, "value": value,
        "polarity": polarity, "durability": durability, "refs": list(refs),
    })


# ---- 1. details the old regex table structurally could not hold -------------
POSITIVE = [
    ("习惯", "habit", "累的时候会咬后槽牙", ["t5"]),
    ("习惯", "habit", "生气时会先沉默三秒再说话", ["t11"]),
    ("健康", "health", "母亲的忌日是每年十一月三号", ["t8"]),
    ("习惯", "habit", "睡觉必须开着白噪音", ["t9"]),
    ("约定", "commitment", "同一件事只说一次，不喜欢重复", ["t10"]),
    ("饮食", "dietary_restriction", "不能吃香菜", ["t7"]),
    ("偏好", "preference", "喜欢喝不加糖的冰美式", ["t6"]),
]

# ---- 2. must never be promoted --------------------------------------------
NEGATIVE = [
    ("转述他人（不是本人事实）", "dislike", "naliling 最讨厌香菜", ["t12"]),
    ("角色扮演台词", "commitment", "代号十七今晚要行动", ["t13"]),
    ("临时状态", "habit", "有点累", ["t14"]),
    ("未来计划不是已完成行为", "habit", "每天跑五公里", ["t15"]),
    ("无实质内容", "habit", "他去洗澡了", ["t16"]),
    ("凭空编造", "habit", "养了三只仓鼠", ["t1"]),
    ("凭空编造2", "preference", "喜欢骑马", ["t6"]),
]


def report(title, rows):
    print(f"\n{title}")
    for label, *rest in rows:
        print(f"  {label}")


def main():
    print("=" * 72)
    print("断言层高保真回归（无 LLM 凭据，测的是模型下游每一道闸门）")
    print("=" * 72)

    print("\n[1] 旧正则表结构上无法容纳的细节 — 应全部通过")
    ok = 0
    for label, dim, value, refs in POSITIVE:
        a = build("naliling", dim, value, refs)
        v = verdict(a) if a else "NORMALIZE_DROP"
        good = a and v != "unsupported"
        ok += bool(good)
        print(f"  {'PASS' if good else 'FAIL'}  [{dim:20s}] {value:26s} -> {v}")
    print(f"  小计 {ok}/{len(POSITIVE)}")

    print("\n[2] 不该被提升为长期断言的内容 — 应全部拦下")
    blocked = 0
    for label, dim, value, refs in NEGATIVE:
        a = build("naliling", dim, value, refs)
        v = verdict(a) if a else "NORMALIZE_DROP"
        ev = [BY_ID[r]["content"] for r in refs if r in BY_ID]
        ok_person, why = claim_is_personal_fact("naliling", value, ev)
        good = (not a) or (v == "unsupported" or not assertion_is_promotable(a, ev))
        blocked += bool(good)
        print(f"  {'PASS' if good else 'FAIL'}  {label:24s} {value:18s} -> 引用={v:12s} 可晋升={ok_person}({why or '-'})")
    print(f"  小计 {blocked}/{len(NEGATIVE)}")

    print("\n[3] 时态与极性保真")
    cases = [
        ("保留否定（原文: 不想去上班）", "habit", "很抗拒去上班", ["t4"], "positive", True),
        ("保留否定（原文: 不喜欢重复）", "commitment", "不喜欢被重复提醒", ["t10"], "negative", True),
    ]
    for label, dim, value, refs, pol, expect_ok in cases:
        a = build("naliling", dim, value, refs, polarity=pol)
        v = verdict(a)
        print(f"  {'PASS' if (v != 'unsupported') == expect_ok else 'FAIL'}  {label:32s} -> {v}")

    print("\n[4] 跨日与绝对时间表达（上一轮回归的修复点）")
    s = MemorySummarizer()
    long_rows = [BY_ID["t1"], BY_ID["t2"]]
    for text in [
        "naliling 说他 2026-10-01 晚上才吃上饭，睡得很晚",
        "naliling 说他前一晚只睡了六个小时",
        "naliling 说他 2027-01-01 那天只睡了六个小时",   # wrong date -> must reject
        "naliling 说他 2026-10-01 凌晨才吃上饭",          # wrong time-of-day -> must reject
    ]:
        v = s.citation_check(text, long_rows)[0]
        print(f"  {text:44s} -> {v}")

    print("\n[5] 合并语义（同一断言多次提及）")
    asyncio.run(merge_report())


async def merge_report():
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(Path(tmp) / "t.db")
        store.initialize()
        try:
            def rec(dim, value, refs, polarity="positive"):
                import re
                return MemoryRecord(
                    id=f"a_{abs(hash((dim, value, polarity))) % 10 ** 12}",
                    memory_type=ASSERTION_MEMORY_TYPE,
                    subject=EntityRef(kind="user", id="naliling"),
                    object=EntityRef.bot_self(bot_id="b1"),
                    scope="private", session_id=PRIV.session_id, platform="qq",
                    visibility="private_pair", lifecycle="stable_memory",
                    review_status="auto", content=value, evidence="原文",
                    confidence=0.8, importance=0.5, owner_bot_id="b1",
                    durability="normal", sensitivity="internal",
                    metadata={
                        "profile_dimension": dim, "profile_polarity": polarity,
                        "profile_value": value,
                        "normalized_value": re.sub(r"\s+", " ", value.casefold()).strip(),
                        "profile_cardinality": cardinality_for(dim),
                        "assertion_evidence_refs": list(refs),
                    },
                )

            r1 = await store.upsert_assertion(rec("habit", "累的时候会咬后槽牙", ["t5"]))
            r2 = await store.upsert_assertion(rec("habit", "累的时候会咬后槽牙", ["t17"]))
            print(f"  同一断言第 2 次提及 -> 同一条={r1['memory_id'] == r2['memory_id']} "
                  f"来源数={r2['merged_sources']}")
            await store.upsert_assertion(rec("habit", "生气时会先沉默三秒", ["t11"]))
            rows = store._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE memory_type='assertion' "
                "AND json_extract(metadata,'$.profile_dimension')='habit'").fetchone()[0]
            print(f"  两条不同习惯 -> habit 维度存活 {rows} 条（应为 2，不互相取代）")

            old = await store.upsert_assertion(rec("preferred_address", "住在上海", ["x"]))
            new = await store.upsert_assertion(rec("preferred_address", "现在住杭州", ["y"]))
            prev = store._conn.execute(
                "SELECT lifecycle, supersedes_id FROM memories WHERE id=?",
                (old["memory_id"],)).fetchone()
            print(f"  单值改口（上海->杭州）-> 旧行={prev['lifecycle']} "
                  f"指向新行={prev['supersedes_id'] == new['memory_id']}")

            total = store._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE memory_type='assertion'").fetchone()[0]
            print(f"  库中断言总数={total}")
        finally:
            store.close()


main()