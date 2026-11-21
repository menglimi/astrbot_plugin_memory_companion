"""The bounded trial operates only through the live admin-protected service."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import unittest

from .test_panel_guard import PluginPageApi, page_api_module, make_request, _fake_jsonify


class SummaryAdmissionApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = {"mode": "paused", "batches": [{"id": "private-id"}], "results": [], "stop_reason": ""}
        self.service = SimpleNamespace(
            pause_summary_admission=AsyncMock(return_value=self.state),
            run_summary_recovery_trial=AsyncMock(return_value=self.state),
            resume_summary_admission=AsyncMock(),
            _summary_admission=SimpleNamespace(state=self.state),
        )
        self.api = PluginPageApi(SimpleNamespace(service=self.service))
        self.api._audit_page_access = Mock()

    async def call(self, payload, *, csrf=None, admin=None):
        with (
            patch.object(page_api_module, "request", make_request(method="POST", payload=payload)),
            patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify),
            patch.object(self.api, "_require_csrf", return_value=csrf),
            patch.object(self.api, "_require_dashboard_admin", return_value=admin),
            patch.object(self.api, "_dashboard_admin_state", return_value="allowed"),
        ):
            return await self.api._wrap_route("/maintenance/summary_admission", self.api.summary_admission)()

    async def test_csrf_and_admin_reject_before_live_operation(self):
        for protections in ({"csrf": object()}, {"admin": object()}):
            await self.call({"action": "trial"}, **protections)
        self.service.run_summary_recovery_trial.assert_not_awaited()
        self.service.pause_summary_admission.assert_not_awaited()

    async def test_exact_live_operation_and_safe_response(self):
        response = await self.call({"action": "trial", "limit": 999, "force": True, "batch_ids": ["other"]})
        self.service.run_summary_recovery_trial.assert_awaited_once_with(limit=5)
        self.assertEqual("paused", response.payload["data"]["mode"])
        self.assertEqual(1, response.payload["data"]["selected_batches"])
        self.assertNotIn("private-id", repr(response.payload))
        await self.call({"action": "pause"})
        self.service.pause_summary_admission.assert_awaited_once_with()
        await self.call({"action": "resume"})
        self.service.resume_summary_admission.assert_awaited_once_with()

    async def test_invalid_action_never_dispatches(self):
        response = await self.call({"action": "force"})
        self.assertEqual(400, response.status_code)
        self.service.run_summary_recovery_trial.assert_not_awaited()

    async def test_unavailable_bound_identity_is_rejected(self):
        with (
            patch.object(self.api, "_dashboard_admin_state", return_value="unavailable"),
            patch.object(page_api_module, "jsonify", side_effect=_fake_jsonify),
        ):
            response = await self.api.summary_admission()
        self.assertEqual(403, response.status_code)
        self.service.run_summary_recovery_trial.assert_not_awaited()
