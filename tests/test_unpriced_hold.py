"""Unpriced paid steps with a hard beta credit: never approvable without a price or a worst-case hold,
held at a documented ceiling otherwise, and cut off at that hold by the runner."""
from __future__ import annotations

import json
from unittest.mock import patch

from fastapi import HTTPException

import server.studio as studio
from server import run_billing, run_budget as rb
from test_run_billing_flow import FlowFixture, VENDOR_RE
from test_deep_agent import image, read_skill


class WorstCaseHoldTable(FlowFixture):
    def test_constants_cover_video_image_and_audio_and_are_conservative(self):
        self.assertEqual(run_billing.WORST_CASE_HOLD_CENTS, {"video": 400, "image": 50, "audio": 50})
        self.assertEqual(run_billing.worst_case_hold_cents("Kling___image_to_video"), 400)
        self.assertEqual(run_billing.worst_case_hold_cents("Seedream___text_to_image"), 50)
        self.assertEqual(run_billing.worst_case_hold_cents("ElevenLabs___text_to_speech_v3"), 50)
        self.assertIsNone(run_billing.worst_case_hold_cents("Mystery___do_something"))


class UnpricedApprovalTests(FlowFixture):
    async def pause(self, price=None):
        price_patch = patch.object(run_billing, "_step_price", return_value=price)
        price_patch.start()
        self.addCleanup(price_patch.stop)
        self.steps = [read_skill(), image()]
        await self.run_job()
        return self.execution()

    async def test_unpriced_step_gets_worst_case_hold_as_its_cap(self):
        execution = await self.pause()
        card = execution["approvals"][0]
        self.assertEqual(card["status"], "pending")
        self.assertEqual(card["price_basis"], "up_to")
        self.assertTrue(card["up_to"])
        self.assertEqual(card["step_price_cents"], 50)
        media = [line for line in card["lines"] if line["kind"] == "media"]
        self.assertEqual(media[0]["price_cents"], 50)
        self.assertGreaterEqual(card["cap_cents"], card["estimate_cents"])
        self.assertTrue(card["approve_enabled"])
        self.assertIsNone(VENDOR_RE.search(json.dumps(execution["approvals"])))

    async def test_approve_is_rejected_when_a_step_has_neither_price_nor_hold(self):
        await self.pause()
        raw = self.repo.execution_checkpoint("user:local", self.job)["approvals"]
        for item in raw:
            item["tool_name"] = "Mystery___do_something"
        with self.repo._connect() as connection:
            connection.execute("UPDATE executions SET approvals_json = ? WHERE id = ?", (json.dumps(raw), self.job))
        card = self.execution()["approvals"][0]
        self.assertFalse(card["approve_enabled"])
        self.assertTrue(card["unpriceable"])
        before = self.repo.get_balance(self.user)
        with self.assertRaises(HTTPException) as caught:
            await studio.decide_studio_agent_tool(self.job, card["call_id"], studio.AgentApprovalBody(decision="approve"), None)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("can’t be priced", caught.exception.detail)
        self.assertEqual(self.execution()["status"], "awaiting_approval")
        self.assertEqual(self.repo.get_balance(self.user), before)  # no charge
        with self.assertRaises(ValueError):
            run_billing.approval_gate(self.repo, run_id=self.job, user_id=self.user, conversation_id=None,
                                      raw_approvals=raw, requested_cap_cents=None)

    async def test_over_credit_hold_routes_to_the_over_credit_state(self):
        # The up-to total is the cap, so make the worst case outgrow the run's opening hold plus the credit left.
        table = patch.dict(run_billing.WORST_CASE_HOLD_CENTS, {"image": 400})
        table.start()
        self.addCleanup(table.stop)
        await self.pause()
        self.repo.adjust_balance(self.user, -(1000 - 130), "test_spend")  # 130 left, the up-to total needs more
        card = self.execution()["approvals"][0]
        self.assertEqual(card["price_basis"], "up_to")
        self.assertFalse(card["approve_enabled"])
        self.assertEqual(card["insufficient_credit"]["type"], "insufficient_credit")
        with self.assertRaises(HTTPException) as caught:
            await studio.decide_studio_agent_tool(self.job, card["call_id"], studio.AgentApprovalBody(decision="approve"), None)
        self.assertEqual(caught.exception.status_code, 402)


class RunnerCutoffTests(FlowFixture):
    def held_meter(self, cap):
        self.repo.hold_run(self.user, self.job, cap, estimate_cents=cap, conversation_id=None)
        return run_billing.RunMeter.for_run(self.repo, self.user, self.job)

    def test_unpriced_dispatch_reserves_the_worst_case_hold(self):
        meter = self.held_meter(500)
        meter.reserve_media("call-1", None, "Seedream___text_to_image")
        row = next(r for r in self.repo.run_work(self.job) if r["work_id"] == "media:call-1")
        self.assertEqual(row["reserved_cents"], 50)

    def test_charge_never_exceeds_the_hold(self):
        meter = self.held_meter(500)
        with meter.media_dispatch("call-2", None, "Seedream___text_to_image"):
            run_billing.charge_media(self.repo, self.user, self.job, 900, "Seedream___text_to_image", {}, call_id="call-2")
        charged = self.repo.get_run_hold(self.job)["charged_cents"]
        self.assertEqual(charged, 50)
        self.assertEqual(self.repo.get_balance(self.user), 1000 - 50)

    def test_runner_stops_when_the_hold_does_not_fit_the_cap(self):
        meter = self.held_meter(30)  # cap below the 50 c image hold
        with self.assertRaises(rb.RunPausedAtCap):
            meter.reserve_media("call-3", None, "Seedream___text_to_image")
        self.assertEqual(self.repo.get_run_hold(self.job)["charged_cents"], 0)

    def test_runner_cuts_off_a_step_with_no_hold(self):
        meter = self.held_meter(500)
        with self.assertRaises(rb.RunPausedAtCap):
            meter.reserve_media("call-4", None, "Mystery___do_something")
