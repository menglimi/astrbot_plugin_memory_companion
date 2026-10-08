from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from benchmarks import run_hindsight_shadow_evaluation as evaluator
from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord
from astrbot_plugin_memory_companion.core.store import MemoryStore


class HindsightShadowEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_eval_uploads_only_visible_records_and_maps_source_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "memory.db"
            store = MemoryStore(db_path)
            store.initialize()
            user = EntityRef(kind="user", id="u1", name="User")
            bot = EntityRef.bot_self("b1", "Bot")
            await store.insert_memory(
                MemoryRecord(
                    id="visible",
                    memory_type="explicit_memory",
                    subject=user,
                    object=bot,
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    platform="qq",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    content="用户最喜欢的花是蓝风铃。",
                )
            )
            await store.insert_memory(
                MemoryRecord(
                    id="other-user",
                    memory_type="explicit_memory",
                    subject=EntityRef(kind="user", id="u2", name="Other"),
                    object=bot,
                    scope="private",
                    session_id="qq:FriendMessage:u2",
                    platform="qq",
                    visibility="private_pair",
                    lifecycle="stable_memory",
                    content="这是另一个用户的秘密。",
                )
            )
            await store.insert_memory(
                MemoryRecord(
                    id="other-group",
                    memory_type="explicit_memory",
                    subject=user,
                    object=bot,
                    scope="group",
                    session_id="qq:GroupMessage:g1",
                    platform="qq",
                    group_id="g1",
                    visibility="group_public",
                    lifecycle="stable_memory",
                    content="这是另一个群的内容。",
                )
            )
            await store.insert_memory(
                MemoryRecord(
                    id="raw-event",
                    memory_type="raw_event",
                    subject=user,
                    object=bot,
                    scope="private",
                    session_id="qq:FriendMessage:u1",
                    platform="qq",
                    visibility="private_pair",
                    lifecycle="raw_event",
                    content="近期原始消息默认不进入长期记忆召回。",
                )
            )
            store.close()

            cases_path = root / "cases.jsonl"
            cases_path.write_text(
                json.dumps(
                    {
                        "id": "case-1",
                        "query": "蓝风铃",
                        "scope": "private",
                        "session_id": "qq:FriendMessage:u1",
                        "bot_id": "b1",
                        "relevant_ids": ["visible"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            args = Namespace(
                db=db_path,
                cases=cases_path,
                base_url="http://127.0.0.1:8888",
                api_key_env="",
                bank_prefix="shadow-test",
                timeout=1.0,
                top_k=3,
                mode="basic",
                budget="low",
                allow_self_timeline_everywhere=True,
                allow_group_public_in_private=False,
                include_raw_events=False,
                keep_banks=False,
            )
            retain_payloads: list[dict] = []
            request_paths: list[tuple[str, str]] = []

            async def fake_request(_base, _key, method, path, payload, _timeout):
                request_paths.append((method, path))
                if method == "POST" and path.endswith("/memories"):
                    retain_payloads.append(payload)
                if path.endswith("/memories/recall"):
                    return {
                        "results": [
                            {"document_id": "visible"},
                            {"document_id": "other-user"},
                        ]
                    }
                return {}

            with patch.object(evaluator, "_request", new=AsyncMock(side_effect=fake_request)):
                report = await evaluator.run_evaluation(args)

            uploaded_ids = [
                item["document_id"]
                for batch in retain_payloads
                for item in batch["items"]
            ]
            self.assertEqual(["visible"], uploaded_ids)
            self.assertEqual(1.0, report["hindsight"]["recall@3"])
            self.assertEqual(["visible"], report["per_query"][0]["returned_ids"])
            self.assertEqual(1, report["per_query"][0]["unmapped_results"])
            self.assertTrue(report["hindsight_sync"]["temporary_banks_deleted"])
            self.assertTrue(any(method == "DELETE" for method, _path in request_paths))


if __name__ == "__main__":
    unittest.main()
