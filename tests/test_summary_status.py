"""Recovery status stays faithful to queue state without performing work."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from . import test_summary_admission as admission_tests
from .test_panel_guard import PluginPageApi, page_api_module, make_request, _fake_jsonify


class SummaryStatusTests(unittest.IsolatedAsyncioTestCase):
    setUp = admission_tests.SummaryAdmissionTests.setUp
    batch = admission_tests.SummaryAdmissionTests.batch
    ctx = admission_tests.SummaryAdmissionTests.ctx

    def change(self, batch_id, **values):
        columns = ",".join(key + "=?" for key in values)
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute(
                "UPDATE summary_batches SET " + columns + " WHERE id=?",
                [*values.values(), batch_id],
            )

    async def test_waits_read_actual_queue_and_do_not_mutate_or_call_provider(self):
        batches = [await self.batch(i) for i in range(6)]
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.change(batches[1][0], next_retry_at=future, retry_reason="transient")
        self.change(batches[2][0], lease_token="fake-owner", lease_expires_at=future, next_retry_at=future)
        self.change(batches[3][0], automatic_calls=3)
        self.change(batches[4][0], retry_reason="budget", next_retry_at=future)
        _, invalid_event = batches[5]
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute("UPDATE timeline SET metadata='{}' WHERE id=?", (invalid_event,))
            self.service.store._conn.execute("UPDATE summary_batches SET metadata='{}' WHERE id=?", (batches[5][0],))
            # One recent automatic call preserves the real budget defer predicate.
            self.service.store._conn.execute(
                "INSERT INTO summary_batch_calls(batch_id,session_id,attempted_at,automatic) VALUES(?,?,?,1)",
                (batches[0][0], self.ctx().session_id, datetime.now(timezone.utc).isoformat()),
            )
        self.service._summary_provider_attempts = AsyncMock(side_effect=AssertionError("status selected a provider"))
        before = "\n".join(self.service.store._conn.iterdump())
        status = await self.service.summary_recovery_status()
        self.assertEqual({"runnable": 1, "retry": 1, "running": 1, "call_limit": 1,
                          "hourly_budget": 1, "identity": 1},
                         {key: value for key, value in status["waits"].items() if value})
        self.assertEqual(6, status["pending_batches"])
        self.assertEqual(6, sum(status["waits"].values()))
        self.assertGreater(status["oldest_wait_seconds"], 86400)
        self.assertEqual(before, "\n".join(self.service.store._conn.iterdump()))
        self.service._summary_provider_attempts.assert_not_awaited()
        self.assertNotIn("u1", json.dumps(status))
        self.assertNotIn("fake-owner", json.dumps(status))

    async def test_hourly_budget_pause_disabled_scope_and_live_capacity(self):
        batch_id, _ = await self.batch()
        async def reason():
            return (await self.service.summary_recovery_status())["waits"]
        self.assertEqual(1, (await reason())["runnable"])
        self.service._summary_admission.save(mode="paused")
        self.assertEqual(1, (await reason())["paused"])
        self.service._summary_admission.save(mode="normal")
        self.config["memory_summary"]["enabled"] = False
        self.assertEqual(1, (await reason())["disabled"])
        self.config["memory_summary"]["enabled"] = True
        with patch.object(self.service, "_scope_feature_enabled", return_value=False):
            self.assertEqual(1, (await reason())["capture_disabled"])
        await self.service._summary_call_semaphore.acquire()
        try:
            self.assertEqual(1, (await reason())["global_slot"])
        finally:
            self.service._summary_call_semaphore.release()
        lock = self.service._summary_locks.setdefault(self.ctx().session_id, asyncio.Lock())
        await lock.acquire()
        try:
            self.assertEqual(1, (await reason())["session_busy"])
        finally:
            lock.release()
        with self.service.store._lock, self.service.store._transaction_sync():
            for _ in range(6):
                self.service.store._conn.execute(
                    "INSERT INTO summary_batch_calls(batch_id,session_id,attempted_at,automatic) VALUES(?,?,?,1)",
                    (batch_id, self.ctx().session_id, datetime.now(timezone.utc).isoformat()),
                )
        self.assertEqual(1, (await reason())["hourly_budget"])

    async def test_originals_candidates_and_blank_history_stay_separate(self):
        identity = {"platform": "qq", "owner_bot_id": "b1", "persona_id": "persona-1", "user_id": "u1"}
        for content in ("有效未分批记录一", "有效未分批记录二", "   \t\n"):
            await self.service.store.add_timeline_event(
                event_type="user_message", session_id=self.ctx().session_id, scope="private",
                subject_id="u1", object_id="u1", content=content, metadata=identity,
            )
        from .test_panel_guard import make_record
        for index, review in enumerate(("auto", "pending", "rejected", "expired", "manual", "auto")):
            record = make_record("mem-" + str(index))
            record.review_status = review
            if index == 5:
                record.lifecycle = "archived"
            await self.service.store.insert_memory(record)
        status = await self.service.summary_recovery_status()
        self.assertEqual(0, status["pending_batches"])
        self.assertEqual(2, status["unbatched"]["events"])
        self.assertEqual(1, status["unbatched"]["eligible_events"])
        self.assertEqual(1, status["unbatched"]["eligible_windows"])
        self.assertEqual(2, status["progress"]["raw_events"])
        self.assertEqual(2, status["progress"]["adopted_memories"])
        self.assertEqual(1, status["progress"]["review_candidates"])
        self.config["memory_summary"]["min_events"] = 3
        status = await self.service.summary_recovery_status()
        self.assertEqual(2, status["unbatched"]["below_threshold_events"])
        self.assertEqual(0, status["unbatched"]["eligible_events"])
        self.config["memory_summary"]["min_events"] = 1
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute("UPDATE timeline SET metadata='{}'")
        status = await self.service.summary_recovery_status()
        self.assertEqual(1, status["unbatched"]["identity_blocked_events"])
        self.assertEqual(0, status["unbatched"]["eligible_events"])

    async def test_empty_history_batches_are_not_valid_backlog_or_progress(self):
        batch_id, event_id = await self.batch()
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute("UPDATE timeline SET content='   ' WHERE id=?", (event_id,))
        status = await self.service.summary_recovery_status()
        self.assertEqual(0, status["pending_batches"])
        self.assertEqual(0, (await self.service.store.list_pending_batches())["total"])
        self.change(batch_id, state="quarantined")
        status = await self.service.summary_recovery_status()
        self.assertEqual(0, status["progress"]["quarantined_batches"])

    async def test_conflicting_source_identity_is_not_runnable(self):
        batch_id, _ = await self.batch()
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute(
                "UPDATE summary_batches SET metadata=? WHERE id=?",
                (json.dumps({"owner_bot_id": "other-bot"}), batch_id),
            )
        status = await self.service.summary_recovery_status()
        self.assertEqual(1, status["waits"]["identity"])
        self.assertEqual(0, status["waits"]["runnable"])

    async def test_panel_renders_real_backend_counts_and_waits(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is needed only for the panel rendering check")
        await self.batch()
        empty_batch, empty_event = await self.batch(1)
        with self.service.store._lock, self.service.store._transaction_sync():
            self.service.store._conn.execute("UPDATE timeline SET content='   ' WHERE id=?", (empty_event,))
        self.change(empty_batch, state="quarantined")
        self.service._summary_admission.save(mode="paused")
        status = await self.service.summary_recovery_status()
        from pathlib import Path
        script = Path(__file__).resolve().parents[1] / "pages" / "记忆面板" / "app.js"
        code = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({
  document: {documentElement: {dataset: {}}, readyState: 'loading', addEventListener() {}},
  window: {addEventListener() {}},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.snapshot = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(vm.runInContext(`({
  card: summaryRecoveryCard(snapshot),
  unlimitedCard: summaryRecoveryCard({...snapshot, limits: {...snapshot.limits, calls_per_session_hour: 0}}),
  overview: VIEWS.overview.render({recovery: snapshot, stats: {
    summary_progress: {quarantined_batches: 987654, no_memory_batches: 987653, frozen_events: 987652}
  }})
})`, context)));
"""
        rendered = subprocess.run(
            [node, "-e", code, str(script), json.dumps(status)],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        output = json.loads(rendered)
        rendered = output["card"]
        self.assertIn('class="card ', rendered)
        self.assertIn("待处理 1 批", rendered)
        self.assertIn("每会话每小时 6 次", rendered)
        self.assertIn("每会话每小时 不限", output["unlimitedCard"])
        self.assertIn(status["wait_labels"]["paused"], rendered)
        self.assertIn("待审候选 0 条", rendered)
        self.assertNotIn("qq:FriendMessage:u1", rendered)
        self.assertNotIn("987", output["overview"])
        self.assertIn("待修复批次", output["overview"])
        self.assertIn("已处理，无新增记忆", output["overview"])
        self.assertNotIn("冻结原文", output["overview"])

    async def test_panel_recovery_guards_styles_and_people_banner(self):
        from pathlib import Path
        pages = Path(__file__).resolve().parents[1] / "pages" / "记忆面板"
        app_css = (pages / "app.css").read_text(encoding="utf-8")
        legacy_html = (pages / "legacy.html").read_text(encoding="utf-8")
        people_html = (pages / "people.html").read_text(encoding="utf-8")
        people_css = (pages / "people.css").read_text(encoding="utf-8")
        people_js = (pages / "people.js").read_text(encoding="utf-8")

        self.assertIn("./app.css?v=2.6.6-summary-status", legacy_html)
        self.assertIn("./people.css?v=2.6.6-summary-status", people_html)
        self.assertIn('<details id="recovery" class="recovery" hidden></details>', people_html)
        self.assertIn(".recovery-card .pill-row", app_css)
        self.assertIn(".section-note {", app_css)
        self.assertIn('html[data-ui-mode="cinema"] .terminal-stage + .recovery-card', app_css)
        self.assertIn(".recovery summary {", people_css)
        self.assertIn("recoveryTicket", people_js)
        self.assertIn("loadRecoveryStatus()", people_js)

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is needed only for the panel rendering check")
        code = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const appCtx = vm.createContext({
  document: {documentElement: {dataset: {}}, readyState: 'loading', addEventListener() {}},
  window: {addEventListener() {}},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), appCtx);
const appRes = vm.runInContext(`({
  zero: summaryWaitDuration(0),
  short: summaryWaitDuration(30),
  degraded: summaryRecoveryCard({
    summary_enabled: true, admission: "normal", recovery_enabled: true,
    dispatcher_state: "degraded", pending_batches: 2, oldest_wait_seconds: 30,
    waits: {identity: 1, call_limit: 1, running: 1},
    wait_labels: {identity: "来源身份缺失或冲突", call_limit: "本批调用次数已用完", running: "正在整理"},
    unbatched: {events: 0, eligible_events: 0, eligible_windows: 0, waits: {}},
    progress: {adopted_memories: 0, review_candidates: 0, completed_batches: 0, no_memory_batches: 0, quarantined_batches: 0},
    limits: {calls_per_session_hour: 24, global_concurrency: 1},
  }),
  partialOverview: VIEWS.overview.render({
    recovery: {pending_batches: 2},
    stats: {summary_progress: {raw_events: 9999, quarantined_batches: 8888}},
  }),
})`, appCtx);

const nodes = {};
const makeNode = () => ({hidden: true, innerHTML: '', textContent: '', value: '', addEventListener() {}, focus() {}});
const peopleCtx = vm.createContext({
  document: {
    getElementById(id) { return nodes[id] || (nodes[id] = makeNode()); },
    addEventListener() {},
  },
  window: {addEventListener() {}, confirm: () => false},
  location: {search: '?asset_token=tok123'},
  fetch: () => Promise.resolve({ok: true, json: () => Promise.resolve({ok: true, data: {items: [], bots: []}})}),
  setTimeout, clearTimeout, URLSearchParams,
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), peopleCtx);
const peopleRes = vm.runInContext(`(() => {
  renderRecoveryStatus(null);
  const hiddenOnNull = document.getElementById('recovery').hidden;
  renderRecoveryStatus({});
  const partialHtml = document.getElementById('recovery').innerHTML;
  renderRecoveryStatus({
    pending_batches: 3, oldest_wait_seconds: 45,
    waits: {retry: 2}, wait_labels: {retry: '等待错误重试'},
    unbatched: {events: 5, eligible_events: 2},
    progress: {adopted_memories: 4, review_candidates: 1, quarantined_batches: 0},
  });
  return {hiddenOnNull, partialHtml, fullHtml: document.getElementById('recovery').innerHTML};
})()`, peopleCtx);
process.stdout.write(JSON.stringify({appRes, peopleRes}));
"""
        raw = subprocess.run(
            [node, "-e", code, str(pages / "app.js"), str(pages / "people.js")],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        data = json.loads(raw)
        self.assertEqual("无", data["appRes"]["zero"])
        self.assertEqual("不足 1 分钟", data["appRes"]["short"])
        self.assertIn("card recovery-card", data["appRes"]["degraded"])
        self.assertIn("后台恢复已开启（调度器异常）", data["appRes"]["degraded"])
        self.assertIn('data-tone="warn"', data["appRes"]["degraded"])
        self.assertIn('data-tone="danger"', data["appRes"]["degraded"])
        self.assertIn('data-tone="ok"', data["appRes"]["degraded"])
        self.assertNotIn('data-tone="gold"', data["appRes"]["degraded"])
        self.assertIn("待处理批次", data["appRes"]["partialOverview"])
        self.assertNotIn("9,999", data["appRes"]["partialOverview"])
        self.assertNotIn("8,888", data["appRes"]["partialOverview"])

        self.assertTrue(data["peopleRes"]["hiddenOnNull"])
        self.assertNotIn("NaN", data["peopleRes"]["partialHtml"])
        self.assertIn("最老等待 无", data["peopleRes"]["partialHtml"])
        self.assertIn("最老等待 不足 1 分钟", data["peopleRes"]["fullHtml"])
        self.assertIn('./legacy.html?asset_token=tok123', data["peopleRes"]["fullHtml"])
        self.assertNotIn("NaN", data["peopleRes"]["fullHtml"])


class SummaryStatusApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_requires_bound_admin_and_has_no_write_path(self):
        service = SimpleNamespace(summary_recovery_status=AsyncMock(return_value={"pending_batches": 2}))
        api = PluginPageApi(SimpleNamespace(service=service))
        api._audit_page_access = Mock()
        for allowed in (False, True):
            with (
                patch.object(page_api_module, "request", make_request(method="GET")),
                patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify),
                patch.object(api, "_is_bound_dashboard_admin", return_value=allowed),
            ):
                response = await api._wrap_route("/maintenance/summary_status", api.summary_status)()
            if not allowed:
                self.assertEqual(403, response.status_code)
                service.summary_recovery_status.assert_not_awaited()
            else:
                self.assertEqual({"pending_batches": 2}, response.payload["status"])
        self.assertEqual("read", api._endpoint_policy("/maintenance/summary_status", "GET")["policy"])
        service.summary_recovery_status.assert_awaited_once_with()
