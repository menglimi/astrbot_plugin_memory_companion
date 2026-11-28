from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package


bootstrap_package()

from astrbot_plugin_memory_companion.core.models import EntityRef, MemoryRecord, SessionContext
from astrbot_plugin_memory_companion.core.retrieval import RetrievalEngine
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.core.store import MemoryStore
from astrbot_plugin_memory_companion.core.visibility import VisibilityPolicy


class CoreDistillationIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.store = MemoryStore(Path(temp_dir.name) / "memory.db")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.max_blocks = 30
        self.service = MemoryCompanionService.__new__(MemoryCompanionService)
        self.service.store = self.store
        self.service._core_distill_lock = asyncio.Lock()
        self.service.config = SimpleNamespace(
            bool=lambda _key, default=True: default,
            int=lambda key, default: self.max_blocks if key == "core_memory.auto_distill_max_blocks" else default,
            float=lambda _key, default: default,
        )
        self.service._normalized_session_context = lambda ctx: ctx
        self.service.visibility_policy = VisibilityPolicy
        self.service._retrieval_validation_engine = lambda: RetrievalEngine(self.store, VisibilityPolicy())

    async def add_pair(
        self, *, scope: str, target: str, bot: str, platform: str,
        persona: str, marker: str, session_id: str = "",
    ) -> None:
        for index in range(2):
            if scope == "group":
                subject = EntityRef.bot_self(bot)
                object_ref = EntityRef(kind="group", id=target)
                visibility = "group_public"
            else:
                subject = EntityRef(kind="user", id=target)
                object_ref = EntityRef.bot_self(bot)
                visibility = "private_pair"
            await self.store.insert_memory(MemoryRecord(
                id=f"{marker}-{index}",
                subject=subject,
                object=object_ref,
                scope=scope,
                session_id=session_id or f"{platform}:{scope}:{target}",
                group_id=target if scope == "group" else "",
                platform=platform,
                visibility=visibility,
                lifecycle="stable_memory",
                content=f"{marker} fact {index}",
                salience=0.9,
                owner_bot_id=bot,
                metadata={"persona_id": persona, "owner_bot_id": bot},
            ))

    async def test_windows_bots_platforms_and_personas_do_not_mix(self) -> None:
        cases = [
            ("group", "g1", "bot1", "qq", "p1", "group-a"),
            ("group", "g2", "bot1", "qq", "p1", "group-b"),
            ("group", "g1", "bot2", "qq", "p1", "group-c"),
            ("group", "g1", "bot1", "telegram", "p1", "group-d"),
            ("group", "g1", "bot1", "qq", "p2", "group-e"),
            ("private", "u1", "bot1", "qq", "p1", "private-a"),
            ("private", "u2", "bot1", "qq", "p1", "private-b"),
        ]
        for scope, target, bot, platform, persona, marker in cases:
            await self.add_pair(scope=scope, target=target, bot=bot, platform=platform, persona=persona, marker=marker)

        await self.service.auto_distill_core_memory()
        blocks = await self.store.list_core_memories()
        self.assertEqual(len(cases), len(blocks))
        for scope, target, bot, platform, persona, marker in cases:
            ctx = SessionContext(
                scope=scope,
                user_id=target if scope == "private" else "speaker",
                group_id=target if scope == "group" else "",
                bot_id=bot,
                platform=platform,
                persona_id=persona,
            )
            visible = await self.service.core_memories_for_context(ctx)
            self.assertEqual(1, len(visible), msg=marker)
            self.assertEqual({f"{marker} fact 0", f"{marker} fact 1"}, set(visible[0].content.split("；")))

    async def test_existing_automatic_block_is_merged_at_limit_without_repeated_writes(self) -> None:
        self.max_blocks = 1
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="old")
        await self.service.auto_distill_core_memory()
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="new")

        await self.service.auto_distill_core_memory()
        blocks = await self.store.list_core_memories()
        self.assertEqual(1, len(blocks))
        self.assertEqual(
            {"old fact 0", "old fact 1", "new fact 0", "new fact 1"},
            set(blocks[0].content.split("；")),
        )
        revision = blocks[0].metadata["core_revision"]
        self.assertEqual(2, revision)
        await self.service.auto_distill_core_memory()
        self.assertEqual(revision, (await self.store.list_core_memories())[0].metadata["core_revision"])

    async def test_invalid_or_ambiguous_source_is_not_promoted(self) -> None:
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="safe")
        for index, changes in enumerate((
            {"visibility": "internal"},
            {"validity_status": "retracted"},
            {"scope": "unknown"},
            {"owner_bot_id": "", "metadata": {}},
            {"platform": ""},
            {"sensitivity": "restricted"},
        )):
            record = MemoryRecord(
                id=f"unsafe-{index}",
                subject=EntityRef.bot_self("bot1"),
                object=EntityRef(kind="group", id="g1"),
                scope="group", group_id="g1", platform="qq", visibility="group_public",
                lifecycle="stable_memory", content=f"unsafe fact {index}", salience=0.99,
                owner_bot_id="bot1", metadata={"persona_id": "p1", "owner_bot_id": "bot1"},
            )
            for key, value in changes.items():
                setattr(record, key, value)
            await self.store.insert_memory(record)

        await self.service.auto_distill_core_memory()
        blocks = await self.store.list_core_memories()
        self.assertEqual(1, len(blocks))
        self.assertEqual({"safe fact 0", "safe fact 1"}, set(blocks[0].content.split("；")))

    async def test_inactive_profiles_and_placeholder_do_not_hide_valid_sources(self) -> None:
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="safe")
        template = await self.store.get_memory("safe-0")
        candidate = deepcopy(template)
        candidate.id = "candidate"
        candidate.content = "candidate profile"
        candidate.metadata["profile_state"] = "candidate"
        candidate.salience = 1.0
        placeholder = deepcopy(template)
        placeholder.id = "placeholder"
        placeholder.content = "bot personal archive reference [example]"
        placeholder.salience = 1.0
        for record in (candidate, placeholder):
            await self.store.insert_memory(record)

        await self.service.auto_distill_core_memory()
        ctx = SessionContext(scope="group", group_id="g1", bot_id="bot1", platform="qq", persona_id="p1")
        visible = await self.service.core_memories_for_context(ctx)
        self.assertEqual(1, len(visible))
        self.assertEqual({"safe fact 0", "safe fact 1"}, set(visible[0].content.split("；")))

    async def test_manual_blocks_do_not_consume_the_automatic_limit(self) -> None:
        self.max_blocks = 1
        result = await self.service.save_core_memory_block({
            "label": "手工", "scope": "group", "target_id": "g1", "bot_id": "bot1",
            "platform": "qq", "persona_id": "p1", "content": "人工内容",
        })
        self.assertTrue(result["ok"])
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="auto")

        result = await self.service.auto_distill_core_memory()
        blocks = await self.store.list_core_memories()
        self.assertEqual(1, result["created"])
        self.assertEqual(2, len(blocks))
        self.assertEqual({"memory_companion_core", "memory_companion_core_auto"}, {b.source_plugin for b in blocks})

    async def test_concurrent_runs_observe_automatic_limit(self) -> None:
        self.max_blocks = 1
        for target in ("g1", "g2"):
            await self.add_pair(scope="group", target=target, bot="bot1", platform="qq", persona="p1", marker=target)
        entered = asyncio.Event()
        release = asyncio.Event()
        initial_blocks = await self.service.list_core_memory_blocks()
        list_blocks = self.service.list_core_memory_blocks
        calls = 0

        async def held_list():
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
                return initial_blocks
            return await list_blocks()

        self.service.list_core_memory_blocks = held_list
        first = asyncio.create_task(self.service.auto_distill_core_memory())
        await entered.wait()
        second = asyncio.create_task(self.service.auto_distill_core_memory())
        try:
            await asyncio.sleep(0)
            self.assertEqual(1, calls)
        finally:
            release.set()
        results = await asyncio.gather(first, second)
        self.assertEqual([1, 0], [result["created"] for result in results])
        self.assertEqual([1, 1], [result["blocks"] for result in results])
        self.assertEqual(1, len(await self.store.list_core_memories()))

    async def test_cancelled_run_finishes_before_the_next_run(self) -> None:
        self.max_blocks = 1
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="first")
        entered = asyncio.Event()
        release = asyncio.Event()
        list_blocks = self.service.list_core_memory_blocks
        calls = 0

        async def held_list():
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            return await list_blocks()

        self.service.list_core_memory_blocks = held_list
        first = asyncio.create_task(self.service.auto_distill_core_memory())
        await entered.wait()
        first.cancel()
        second = asyncio.create_task(self.service.auto_distill_core_memory())
        try:
            await asyncio.sleep(0)
            self.assertFalse(first.done())
            self.assertEqual(1, calls)
        finally:
            release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertIsInstance(results[0], asyncio.CancelledError)
        self.assertEqual(0, results[1]["created"])
        self.assertEqual(1, len(await self.store.list_core_memories()))

    async def test_repeated_cancellation_keeps_lock_until_thread_finishes(self) -> None:
        entered = asyncio.Event()
        release = threading.Event()
        worker_finished = threading.Event()
        list_blocks = self.service.list_core_memory_blocks
        loop = asyncio.get_running_loop()
        calls = 0

        def held_worker():
            loop.call_soon_threadsafe(entered.set)
            try:
                release.wait()
            finally:
                worker_finished.set()

        async def held_list():
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.to_thread(held_worker)
            return await list_blocks()

        self.service.list_core_memory_blocks = held_list
        first = asyncio.create_task(self.service.auto_distill_core_memory())
        await entered.wait()
        first.cancel()
        await asyncio.sleep(0)
        first.cancel()
        second = asyncio.create_task(self.service.auto_distill_core_memory())
        try:
            done, _ = await asyncio.wait({first, second}, timeout=0.05, return_when=asyncio.FIRST_COMPLETED)
            self.assertFalse(done)
            self.assertFalse(worker_finished.is_set())
            self.assertEqual(1, calls)
        finally:
            release.set()
            results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(worker_finished.is_set())
        self.assertIsInstance(results[0], asyncio.CancelledError)
        self.assertTrue(results[1]["ok"])
        self.assertEqual(2, calls)

    async def test_strict_session_accepts_only_the_original_session(self) -> None:
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="strict")
        await self.service.auto_distill_core_memory()
        ctx = SessionContext(
            scope="group", group_id="g1", bot_id="bot1", platform="qq", persona_id="p1",
            session_id="qq:group:g1", strict_session_only=True,
        )
        self.assertEqual(1, len(await self.service.core_memories_for_context(ctx)))
        ctx.session_id = "napcat:group:g1"
        self.assertEqual([], await self.service.core_memories_for_context(ctx))

    async def test_strict_sessions_for_the_same_target_are_isolated(self) -> None:
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="qq")
        await self.add_pair(
            scope="group", target="g1", bot="bot1", platform="qq", persona="p1",
            marker="napcat", session_id="napcat:group:g1",
        )
        await self.service.auto_distill_core_memory()
        self.assertEqual(2, len(await self.store.list_core_memories()))
        ctx = SessionContext(
            scope="group", group_id="g1", bot_id="bot1", platform="qq", persona_id="p1",
            strict_session_only=True,
        )
        for session_id, marker in (("qq:group:g1", "qq"), ("napcat:group:g1", "napcat")):
            ctx.session_id = session_id
            visible = await self.service.core_memories_for_context(ctx)
            self.assertEqual(1, len(visible))
            self.assertEqual({f"{marker} fact 0", f"{marker} fact 1"}, set(visible[0].content.split("；")))

    async def test_changed_sources_are_hidden_immediately_and_reconciled(self) -> None:
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="source")
        ctx = SessionContext(scope="group", group_id="g1", bot_id="bot1", platform="qq", persona_id="p1")
        await self.service.auto_distill_core_memory()
        self.assertEqual(1, len(await self.service.core_memories_for_context(ctx)))

        await self.store.delete_memory("source-0")
        self.assertEqual([], await self.service.core_memories_for_context(ctx))
        await self.service.auto_distill_core_memory()
        visible = await self.service.core_memories_for_context(ctx)
        self.assertEqual(["source fact 1"], [record.content for record in visible])

        await self.store.update_memory_visibility("source-1", "internal")
        self.assertEqual([], await self.service.core_memories_for_context(ctx))
        await self.service.auto_distill_core_memory()
        self.assertEqual([], await self.store.list_core_memories())

    async def test_user_edit_and_revision_conflict_are_preserved(self) -> None:
        await self.add_pair(scope="group", target="g1", bot="bot1", platform="qq", persona="p1", marker="source")
        await self.service.auto_distill_core_memory()
        block = (await self.store.list_core_memories())[0]
        metadata = block.metadata
        result = await self.service.save_core_memory_block({
            "id": block.id, "label": metadata["core_label"], "scope": "group",
            "target_id": "g1", "bot_id": "bot1", "platform": "qq", "persona_id": "p1",
            "content": "人工修改后的内容", "expected_revision": metadata["core_revision"],
        })
        self.assertTrue(result["ok"])
        stale_delete = await self.store.delete_automatic_core_memory(block.id, expected_revision=metadata["core_revision"])
        self.assertEqual("revision_conflict", stale_delete["code"])
        await self.service.auto_distill_core_memory()
        current = (await self.store.list_core_memories())[0]
        self.assertEqual("人工修改后的内容", current.content)
        self.assertEqual("memory_companion_core", current.source_plugin)

    async def test_retracted_expired_and_restricted_sources_stop_injecting(self) -> None:
        changes = (
            {"validity_status": "retracted"},
            {"valid_to": "2000-01-01T00:00:00+00:00"},
            {"sensitivity": "restricted"},
            {"review_status": "pending"},
        )
        for index, update in enumerate(changes):
            target = f"g-{index}"
            marker = f"source-{index}"
            await self.add_pair(scope="group", target=target, bot="bot1", platform="qq", persona="p1", marker=marker)
            await self.service.auto_distill_core_memory()
            ctx = SessionContext(scope="group", group_id=target, bot_id="bot1", platform="qq", persona_id="p1")
            self.assertEqual(1, len(await self.service.core_memories_for_context(ctx)))
            await self.store.update_memory_payload(f"{marker}-0", **update)
            self.assertEqual([], await self.service.core_memories_for_context(ctx), msg=str(update))
            await self.service.auto_distill_core_memory()
            visible = await self.service.core_memories_for_context(ctx)
            self.assertEqual([f"{marker} fact 1"], [record.content for record in visible], msg=str(update))

    async def test_private_owner_comes_from_the_conversation_window(self) -> None:
        await self.add_pair(scope="private", target="u1", bot="bot1", platform="qq", persona="p1", marker="private")
        record = await self.store.get_memory("private-0")
        record.subject = EntityRef(kind="user", id="someone-else")
        record.object = EntityRef(kind="user", id="u1")
        await self.store.insert_memory(record)
        await self.service.auto_distill_core_memory()
        u1 = SessionContext(scope="private", user_id="u1", bot_id="bot1", platform="qq", persona_id="p1")
        other = SessionContext(scope="private", user_id="someone-else", bot_id="bot1", platform="qq", persona_id="p1")
        self.assertEqual(1, len(await self.service.core_memories_for_context(u1)))
        self.assertEqual([], await self.service.core_memories_for_context(other))
