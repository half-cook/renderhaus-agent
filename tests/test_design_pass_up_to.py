"""Design pass v5: an up-to step shows one amount everywhere and can be lowered to fit the credit."""
from __future__ import annotations

from unittest.mock import patch

from server import run_billing
from test_run_billing_flow import FlowFixture
from test_deep_agent import image, read_skill


class UpToOneNumberTests(FlowFixture):
    async def pause(self):
        price_patch = patch.object(run_billing, "_step_price", return_value=None)
        price_patch.start()
        self.addCleanup(price_patch.stop)
        self.steps = [read_skill(), image()]
        await self.run_job()
        return self.execution()["approvals"][0]

    async def test_up_to_cap_equals_the_up_to_total(self):
        card = await self.pause()
        self.assertTrue(card["up_to"])
        self.assertEqual(card["cap_cents"], card["estimate_cents"])

    async def test_cap_may_be_lowered_below_the_up_to_total_but_not_below_fixed_work(self):
        await self.pause()
        raw = self.repo.execution_checkpoint("user:local", self.job)["approvals"]
        plan = run_billing.plan_for_pending(self.repo, self.job, raw)
        floor = run_billing.up_to_floor_cents(self.repo, self.job, raw)
        self.assertIsNotNone(floor)
        self.assertLess(floor, plan.estimate_cents)
        hold = run_billing.approval_gate(self.repo, run_id=self.job, user_id=self.user, conversation_id=None,
                                         raw_approvals=raw, requested_cap_cents=floor)
        self.assertGreaterEqual(hold["held_cents"], floor)
        with self.assertRaises(ValueError):
            run_billing.approval_gate(self.repo, run_id=self.job, user_id=self.user, conversation_id=None,
                                      raw_approvals=raw, requested_cap_cents=floor - 1)

    def test_insufficient_payload_offers_lower_cap_for_up_to(self):
        from server import run_budget as rb

        payload = rb.insufficient_credit_payload(estimate_cents=432, cap_cents=432, available_cents=240, floor_cents=33)
        self.assertEqual(payload["lower_cap_option_cents"], 240)
        payload = rb.insufficient_credit_payload(estimate_cents=432, cap_cents=432, available_cents=240)
        self.assertIsNone(payload["lower_cap_option_cents"])
