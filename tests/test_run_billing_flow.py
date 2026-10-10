from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from langchain_core.messages import AIMessage

import server.studio as studio
import server.studio_state as studio_state
from server import run_billing, run_budget as rb
from server.studio_state import StudioRepository
from test_deep_agent import Gateway, ScriptedModel, final, image, read_skill

VENDOR_RE = re.compile(
    r"wan|seedance|seedream|kling|runway|luma|vidu|openai|gpt|eleven|fish|\bfal\b|anthropic|claude|sonnet|opus|"
    r"remotion|heygen|mureka|mirelo|topaz|\bsync\b|gemini|ideogram|recraft|byteplus|dashscope|30%|\bfees?\b|markup|"
    r"platform|provider|upstream",
    re.IGNORECASE,
)


def with_usage(message: AIMessage, input_tokens: int, output_tokens: int) -> AIMessage:
    message.usage_metadata = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                              "total_tokens": input_tokens + output_tokens}
    message.response_metadata = {"model_name": "claude-sonnet-5-5"}
    return message


class FlowFixture(unittest.IsolatedAsyncioTestCase):
    user = "local"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = StudioRepository(Path(directory.name) / "state.sqlite3", Path(directory.name) / "media")
        self.repo.adjust_balance(self.user, 1000, "test_credit")
        self.repo.create_project("user:local", "local", "Deep Agent", project_id="project")
        self.conversation = self.repo.create_conversation("user:local", "project", "local")["id"]
        self.job = self._job("Make a product still with Seedream")
        self.gateway = Gateway()
        self.steps = [final()]

        @asynccontextmanager
        async def gateway(**kwargs):
            yield self.gateway

        for p in [
            patch.object(studio, "repository", self.repo),
            patch.object(studio_state, "repository", self.repo),
            patch.object(run_billing, "billing_applies", return_value=True),
            patch("agent.studio_agent_next.gateway_mcp_server", gateway),
            patch("agent.deep_agent.runner.configured_deep_agent_model", side_effect=lambda role=None: ScriptedModel(self.steps)),
            patch.dict(os.environ, {"RENDERHAUS_AGENT_BACKEND": "deepagents", "AGENTCORE_DEV_URL": "",
                                    "ORCHESTRATION_BILLING_ENABLED": "true", "ORCHESTRATION_ESTIMATE_CENTS": "75"}),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def _job(self, prompt):
        return self.repo.create_execution(
            workspace_id="user:local", project_id="project", user_id="local", prompt=prompt,
            conversation_id=self.conversation,
            request={"prompt": prompt, "conversation_id": self.conversation, "workspace_id": "user:local",
                     "project_id": "project", "user_id": "local"},
        )["job_id"]

    async def run_job(self, job=None):
        await studio._run_studio_agent_job(
            job or self.job, "Make a product still with Seedream", [], self.conversation,
            workspace_id="user:local", project_id="project", user_id="local",
        )

    def execution(self, job=None):
        return self.repo.get_execution("user:local", job or self.job)

    def orchestration_rows(self):
        with self.repo._connect() as connection:
            return connection.execute("SELECT wallet_cents, run_id FROM usage_events WHERE reason = 'orchestration'").fetchall()


class MeteringFlowTests(FlowFixture):
    async def test_planner_turns_are_billed_and_the_receipt_shows_orchestration(self):
        # 100k in + 10k out on the default planner = $0.30 model cost per turn.
        self.steps = [with_usage(read_skill(), 100_000, 10_000), with_usage(final(), 100_000, 10_000)]
        await self.run_job()
        execution = self.execution()
        self.assertEqual(execution["status"], "completed")
        receipt = execution["receipt"]
        self.assertEqual(receipt["lines"], [{"label": "Agent orchestration", "price_cents": 78, "kind": "orchestration",
                                             "basis": "fixed"}])
        self.assertEqual(receipt["actual_cents"], 78)  # $0.60 x 1.3
        self.assertEqual((receipt["balance_before_cents"], receipt["balance_after_cents"]), (1000, 922))
        self.assertEqual(self.repo.get_balance(self.user), 922)
        self.assertEqual(self.repo.available_credit(self.user), 922)  # hold released
        self.assertEqual(sum(row["wallet_cents"] for row in self.orchestration_rows()), 78)
        self.assertEqual(await asyncio.to_thread(self.repo.get_run_receipt, self.job, self.user), receipt)
        self.assertIsNone(VENDOR_RE.search(json.dumps(receipt)))

    async def test_flag_off_bills_no_orchestration(self):
        self.steps = [with_usage(final(), 100_000, 10_000)]
        with patch.dict(os.environ, {"ORCHESTRATION_BILLING_ENABLED": "false"}):
            await self.run_job()
        self.assertEqual(self.execution()["receipt"]["actual_cents"], 0)
        self.assertEqual(self.repo.get_balance(self.user), 1000)

    async def test_hard_stop_at_the_cap_pauses_and_never_overcharges(self):
        with patch.dict(os.environ, {"ORCHESTRATION_ESTIMATE_CENTS": "20"}):  # cap = 50
            self.steps = [with_usage(read_skill(), 100_000, 10_000), with_usage(final(), 100_000, 10_000)]
            await self.run_job()
        execution = self.execution()
        self.assertEqual(execution["status"], "error")
        self.assertEqual(execution["error_type"], "PausedAtCap")
        self.assertEqual(execution["message"], rb.PAUSED_MESSAGE)
        paused = execution["paused_cap"]
        self.assertEqual((paused["type"], paused["cap_cents"], paused["charged_cents"]), ("paused_cap", 50, 50))
        self.assertEqual(paused["raise_options_cents"], [100, 150])
        self.assertEqual(self.repo.get_balance(self.user), 950)  # exactly the cap, never more
        self.assertIsNone(execution["receipt"])
        self.assertEqual(self.repo.get_run_hold(self.job)["state"], "held")
        self.assertIsNone(VENDOR_RE.search(json.dumps(paused)))

    async def test_cap_stop_releases_and_returns_the_receipt(self):
        with patch.dict(os.environ, {"ORCHESTRATION_ESTIMATE_CENTS": "20"}):
            self.steps = [with_usage(read_skill(), 100_000, 10_000), with_usage(final(), 100_000, 10_000)]
            await self.run_job()
        result = await studio.studio_agent_cap(self.job, studio.AgentCapBody(action="stop"), None)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["receipt"]["actual_cents"], 50)
        self.assertEqual(result["receipt"]["status"], "failed")
        self.assertEqual(self.repo.available_credit(self.user), 950)
        with self.assertRaises(HTTPException) as caught:
            await studio.studio_agent_cap(self.job, studio.AgentCapBody(action="stop"), None)
        self.assertEqual(caught.exception.status_code, 409)
        receipt = await studio.studio_agent_receipt(self.job, None)
        self.assertEqual(receipt["actual_cents"], 50)

    async def test_raising_the_cap_checks_credit_and_resumes(self):
        with patch.dict(os.environ, {"ORCHESTRATION_ESTIMATE_CENTS": "20"}):
            self.steps = [with_usage(read_skill(), 100_000, 10_000), with_usage(final(), 100_000, 10_000)]
            await self.run_job()
        self.repo.adjust_balance(self.user, -900, "test_spend")  # 50 left
        with patch.object(self.repo, "get_execution", wraps=self.repo.get_execution) as wrapped:
            wrapped.side_effect = lambda *a, **k: {**self.repo.__class__.get_execution(self.repo, *a, **k), "can_resume": True}
            with self.assertRaises(HTTPException) as caught:
                await studio.studio_agent_cap(self.job, studio.AgentCapBody(action="raise", cap_cents=150), None)
        self.assertEqual(caught.exception.status_code, 402)
        self.assertEqual(caught.exception.detail["type"], "insufficient_credit")
        self.assertEqual(self.repo.get_run_hold(self.job)["held_cents"], 50)
        self.repo.adjust_balance(self.user, 900, "test_credit")
        resumed = {"job_id": "next"}
        with patch.object(self.repo, "get_execution", wraps=self.repo.get_execution) as wrapped, \
                patch.object(studio, "resume_studio_agent_job", return_value=resumed) as resume:
            wrapped.side_effect = lambda *a, **k: {**self.repo.__class__.get_execution(self.repo, *a, **k), "can_resume": True}
            result = await studio.studio_agent_cap(self.job, studio.AgentCapBody(action="raise", cap_cents=150), None)
        self.assertEqual(result, resumed)
        resume.assert_awaited_once()
        hold = self.repo.get_run_hold(self.job)
        self.assertEqual((hold["held_cents"], hold["status"]), (150, "running"))

    async def test_raise_needs_a_new_cap_and_a_paused_run(self):
        with self.assertRaises(HTTPException) as caught:
            await studio.studio_agent_cap(self.job, studio.AgentCapBody(action="raise", cap_cents=150), None)
        self.assertEqual(caught.exception.status_code, 404)

    async def test_run_cannot_start_without_credit_for_its_cap(self):
        self.repo.adjust_balance(self.user, -950, "test_spend")
        await self.run_job()
        execution = self.execution()
        self.assertEqual(execution["status"], "error")
        self.assertEqual(execution["error_type"], "InsufficientCredit")
        self.assertIsNone(VENDOR_RE.search(execution["message"]))
        self.assertEqual(self.repo.get_balance(self.user), 50)

    async def test_vendor_wording_in_run_messages_is_neutralised(self):
        self.repo.update_execution("user:local", self.job, status="running", message="Seedance render 40 s elapsed")
        self.assertEqual(self.execution()["message"], "Working on it.")
        self.repo.update_execution("user:local", self.job, status="error", message="fal queue returned 500")
        self.assertEqual(self.execution()["message"], rb.NEUTRAL_ERROR)


class ApprovalFlowTests(FlowFixture):
    def setUp(self):
        super().setUp()
        price = patch.object(run_billing, "_step_price", return_value=26)
        price.start()
        self.addCleanup(price.stop)

    async def pause_for_approval(self):
        self.steps = [read_skill(), image()]
        await self.run_job()
        return self.execution()

    async def test_approval_card_is_priced_with_estimate_cap_and_no_vendor_data(self):
        execution = await self.pause_for_approval()
        self.assertEqual(execution["status"], "awaiting_approval")
        card = execution["approvals"][0]
        self.assertEqual(card["status"], "pending")
        self.assertEqual(card["label"], "Image")
        self.assertEqual(card["lines"][-1]["kind"], "orchestration")
        self.assertEqual(card["estimate_cents"], sum(line["price_cents"] for line in card["lines"]))
        self.assertEqual(card["cap_cents"], rb.default_cap_cents(card["estimate_cents"]))
        self.assertTrue(card["approve_enabled"])
        self.assertIsNone(VENDOR_RE.search(json.dumps(execution["approvals"])), json.dumps(execution["approvals"]))
        self.assertEqual(card["estimate_cents"], 26 + 75)
        self.assertEqual(card["cap_cents"], 150)
        self.assertEqual(self.repo.get_run_hold(self.job)["held_cents"], 125)  # default cap held at run start

    async def test_approving_holds_the_cap_and_low_credit_blocks_it_without_recording(self):
        execution = await self.pause_for_approval()
        card = execution["approvals"][0]
        self.repo.adjust_balance(self.user, -(1000 - 130), "test_spend")  # 130 left; hold already has 125
        with self.assertRaises(HTTPException) as caught:
            await studio.decide_studio_agent_tool(self.job, card["call_id"], studio.AgentApprovalBody(decision="approve"), None)
        self.assertEqual(caught.exception.status_code, 402)
        detail = caught.exception.detail
        self.assertEqual((detail["type"], detail["approve_enabled"]), ("insufficient_credit", False))
        self.assertIsNone(VENDOR_RE.search(json.dumps(detail)))
        self.assertEqual(self.execution()["status"], "awaiting_approval")  # decision was not recorded
        self.assertFalse(self.execution()["approvals"][0]["approve_enabled"])
        self.assertEqual(self.repo.get_balance(self.user), 130)

    async def test_lowered_cap_must_cover_the_estimate(self):
        execution = await self.pause_for_approval()
        card = execution["approvals"][0]
        self.assertTrue(card["estimate_cents"] > 1)
        with self.assertRaises(HTTPException) as caught:
            await studio.decide_studio_agent_tool(
                self.job, card["call_id"], studio.AgentApprovalBody(decision="approve", cap_cents=1), None)
        self.assertEqual(caught.exception.status_code, 400)

    async def test_approval_resumes_with_the_chosen_cap_and_receipt_follows(self):
        execution = await self.pause_for_approval()
        card = execution["approvals"][0]
        self.steps = [final()]
        await studio.decide_studio_agent_tool(
            self.job, card["call_id"], studio.AgentApprovalBody(decision="approve", cap_cents=card["cap_cents"]), None)
        self.assertEqual(self.repo.get_run_hold(self.job)["held_cents"], card["cap_cents"])
        await asyncio.gather(*list(studio._AGENT_TASKS))
        final_state = self.execution()
        self.assertEqual(final_state["status"], "completed")
        self.assertEqual(final_state["receipt"]["cap_cents"], card["cap_cents"])
        self.assertEqual(self.repo.available_credit(self.user), self.repo.get_balance(self.user))

    async def test_rejecting_everything_still_ends_cleanly(self):
        execution = await self.pause_for_approval()
        self.steps = [final()]
        await studio.decide_studio_agent_tool(
            self.job, execution["approvals"][0]["call_id"], studio.AgentApprovalBody(decision="reject"), None)
        await asyncio.gather(*list(studio._AGENT_TASKS))
        self.assertEqual(self.execution()["status"], "completed")
        self.assertEqual(self.execution()["receipt"]["actual_cents"], 0)
        self.assertEqual(self.repo.get_balance(self.user), 1000)


if __name__ == "__main__":
    unittest.main()
