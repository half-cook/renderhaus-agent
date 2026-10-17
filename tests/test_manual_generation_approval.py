from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from server import studio
from server.billing_rates import GenerationCost
from server.studio_state import StudioRepository


class ManualGenerationApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.auth = SimpleNamespace(payload={"sub": "one"})
        self.body = studio.InvokeBody(provider="seedream", tool="text_to_image", project_id="project", arguments={"prompt": "A square"})
        self.repo = Mock()
        self.repo.available_credit.return_value = 1000
        self.enterContext(patch.object(studio, "repository", self.repo))
        self.enterContext(patch.object(studio, "beta_billing_enabled", return_value=True))
        self.enterContext(patch.object(studio, "cost_for", return_value=GenerationCost(40, 10)))
        self.dispatch = self.enterContext(patch.object(studio, "dispatch", return_value={"status": "queued", "job_id": "job"}))
        self.enterContext(patch.object(studio, "_register_payload_assets", return_value=[]))

    async def approved(self):
        quote = await studio.quote_tool(self.body, self.auth)
        return self.body.model_copy(update={"approval_token": quote["approval_token"]})

    async def rejected(self, body, auth=None):
        with self.assertRaises(HTTPException) as caught:
            await studio.invoke_tool(body, auth or self.auth)
        self.assertEqual(caught.exception.status_code, 409)
        self.dispatch.assert_not_called()
        self.repo.charge_usage.assert_not_called()

    async def test_quote_is_read_only_and_contains_exact_hard_cap(self):
        quote = await studio.quote_tool(self.body, self.auth)
        self.assertEqual(quote["estimate_cents"], 50)
        self.assertEqual(quote["cap_cents"], 50)
        self.assertEqual(quote["balance_cents"], 1000)
        self.dispatch.assert_not_called()
        self.repo.charge_usage.assert_not_called()

    async def test_quote_counts_wallet_and_subtracts_other_run_holds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = StudioRepository(root / "studio.sqlite3", root / "media")
            repository.create_project("user:one", "one", "Quote credit", project_id="project")
            repository.adjust_balance("one", 500, "test credit")
            with patch.object(studio, "repository", repository):
                self.assertEqual(repository.get_balance("one"), 500)
                quote = await studio.quote_tool(self.body, self.auth)
                self.assertEqual(quote["balance_cents"], 500)
                repository.hold_run("one", "other-run", 480)
                quote = await studio.quote_tool(self.body, self.auth)
                self.assertEqual(quote["balance_cents"], 20)
                self.assertLess(quote["balance_cents"], quote["cap_cents"])
                self.assertEqual(repository.get_balance("one"), 500)
        self.dispatch.assert_not_called()

    async def test_paid_call_without_approval_never_charges_or_dispatches(self):
        await self.rejected(self.body)

    async def test_approved_call_dispatches_and_charges_exact_amount(self):
        body = await self.approved()
        result = await studio.invoke_tool(body, self.auth)
        self.assertEqual(result["result"]["job_id"], "job")
        self.repo.charge_usage.assert_called_once_with("one", 50, "generation")
        self.dispatch.assert_called_once_with("seedream", "text_to_image", {"prompt": "A square"})


    async def test_changed_inputs_identity_price_and_expiry_fail_closed(self):
        approved = await self.approved()
        for update in ({"arguments": {"prompt": "Different"}}, {"project_id": "other"}, {"source_version_ids": ["other"]}, {"asset_id": "other"}):
            with self.subTest(update=update):
                await self.rejected(approved.model_copy(update=update))
        await self.rejected(approved, SimpleNamespace(payload={"sub": "two"}))
        with patch.object(studio, "cost_for", return_value=GenerationCost(41, 10)):
            await self.rejected(approved)
        with patch.object(studio.time, "time", return_value=10**12):
            await self.rejected(approved)

    async def test_free_poll_needs_no_approval(self):
        with patch.object(studio, "cost_for", return_value=GenerationCost(0, 0)):
            await studio.invoke_tool(self.body.model_copy(update={"tool": "get_task"}), self.auth)
        self.dispatch.assert_called_once()
        self.repo.charge_usage.assert_not_called()

    async def test_restricted_manual_tools_cannot_quote_or_dispatch(self):
        for provider, tool in (("sync", "lipsync_video"), ("heygen", "voice_clone"), ("remotion", "deliver_render"), ("fal", "kling_motion_control")):
            body = self.body.model_copy(update={"provider": provider, "tool": tool})
            for action in (studio.quote_tool, studio.invoke_tool):
                with self.subTest(provider=provider, tool=tool, action=action.__name__), self.assertRaises(HTTPException) as caught:
                    await action(body, self.auth)
                self.assertEqual(caught.exception.status_code, 409)
        self.dispatch.assert_not_called()
        self.repo.charge_usage.assert_not_called()

    async def test_unpriceable_input_and_other_project_do_not_dispatch(self):
        with patch.object(studio, "cost_for", side_effect=ValueError("Unknown price")):
            with self.assertRaises(HTTPException) as caught:
                await studio.quote_tool(self.body, self.auth)
            self.assertEqual(caught.exception.status_code, 400)
        self.repo.require_project.side_effect = KeyError("missing")
        with self.assertRaises(HTTPException) as caught:
            await studio.quote_tool(self.body, self.auth)
        self.assertEqual(caught.exception.status_code, 404)
        self.dispatch.assert_not_called()
        self.repo.charge_usage.assert_not_called()

    async def test_no_work_including_dry_run_refunds_without_saving_artifact(self):
        for status in ("dry_run", "blocked", "not_run", "error", "failed"):
            with self.subTest(status=status):
                self.dispatch.return_value = {"status": status}
                body = await self.approved()
                result = await studio.invoke_tool(body, self.auth)
                self.assertEqual(result["assets"], [])
        self.assertEqual(self.repo.refund_usage.call_count, 5)


if __name__ == "__main__":
    unittest.main()
