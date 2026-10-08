from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from mcp import Tool
from agent.deep_agent.runner import run_with_servers
from agent.studio_agent_next import (
    StudioAgentRequest,
    StudioAgentApprovalRequired,
    StudioApprovalDecision,
    _context_from_request,
)
from server.billing_rates import cost_for
from test_deep_agent import ScriptedModel, Gateway, call, final

PREMIUM = Tool(
    name="Kling___text_to_video",
    inputSchema={
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
        "required": ["prompt"],
    },
)


def read_t2v():
    return call("read_file", {"file_path": "/skills/t2v/SKILL.md"}, "skill")


def generate(name=PREMIUM.name, call_id="video"):
    return call("call_media_tool", {"tool_name": name, "arguments": {"prompt": "forest"}}, call_id)


class IntentGraphTests(unittest.IsolatedAsyncioTestCase):
    def request(self, **kwargs):
        return StudioAgentRequest(
            prompt="make a 5 second cinematic drone shot",
            autonomous=True,
            workspace_id="workspace",
            project_id="project",
            conversation_id="conversation",
            job_id="job",
            **kwargs,
        )

    async def pause(self, request, gateway):
        studio = _context_from_request(request)
        with self.assertRaises(StudioAgentApprovalRequired) as raised:
            await run_with_servers(
                request, studio, [gateway], model=ScriptedModel([read_t2v(), generate()])
            )
        gateway.call_tool.assert_not_awaited()
        return studio, raised.exception

    async def test_autonomous_premium_pauses_with_real_billing_estimate_and_route(self):
        with patch.dict(
            os.environ, {"KLING_DRY_RUN": "false", "RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": ""}
        ):
            studio, paused = await self.pause(self.request(), Gateway([PREMIUM]))
            approval = paused.approvals[0]
            cents = cost_for("kling", "text_to_video", {"prompt": "forest"}).total_cents
            self.assertEqual(approval.estimated_cost["total_cents"], cents)
            self.assertIn(f"${cents / 100:.2f}", approval.label)
            self.assertIn("platform fee", approval.description)
            self.assertIn("Estimated cost", studio.tool_events[-1].label)

    async def test_autonomous_premium_approved_resume_dispatches_once(self):
        gateway = Gateway([PREMIUM])
        studio, paused = await self.pause(self.request(), gateway)
        resumed = self.request(
            session_items=json.loads(json.dumps(studio.session_items)),
            resume_state=paused.state,
            approval_decisions=[
                StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="approve")
            ],
        )
        restored = _context_from_request(resumed)
        await run_with_servers(resumed, restored, [gateway], model=ScriptedModel([final()]))
        gateway.call_tool.assert_awaited_once_with(PREMIUM.name, {"prompt": "forest"})

    async def test_autonomous_premium_rejected_resume_never_dispatches(self):
        gateway = Gateway([PREMIUM])
        studio, paused = await self.pause(self.request(), gateway)
        resumed = self.request(
            session_items=studio.session_items,
            resume_state=paused.state,
            approval_decisions=[
                StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="reject")
            ],
        )
        restored = _context_from_request(resumed)
        await run_with_servers(resumed, restored, [gateway], model=ScriptedModel([final()]))
        gateway.call_tool.assert_not_awaited()
        self.assertEqual(restored.tool_events[-1].status, "rejected")

    async def test_disabled_step_up_preserves_autonomous_dispatch(self):
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            request = self.request()
            gateway = Gateway([PREMIUM])
            studio = _context_from_request(request)
            await run_with_servers(
                request, studio, [gateway], model=ScriptedModel([read_t2v(), generate(), final()])
            )
            gateway.call_tool.assert_awaited_once()

    async def test_live_runner_exposes_policy_proposal_to_the_model(self):
        request = self.request().model_copy(update={"prompt": "cheapest text to video preview"})

        def check_route(messages, tools):
            self.assertIn('"skill": "t2v"', messages[-1].text)
            self.assertIn("Fal___text_to_video", messages[-1].text)
            return final()

        await run_with_servers(
            request, _context_from_request(request), [Gateway()], model=ScriptedModel([check_route])
        )

    async def test_cap_failure_is_visible_in_graph_without_second_dispatch(self):
        name = "Seedance___text_to_video"
        tool = Tool(name=name, inputSchema=PREMIUM.input_schema)
        cents = cost_for("seedance", "text_to_video", {"prompt": "forest"}).total_cents
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": str(cents)}):
            request = self.request()
            studio = _context_from_request(request)
            gateway = Gateway([tool])

            def check_cap(messages, tools):
                self.assertIn("spending cap", messages[-1].text)
                return final()

            await run_with_servers(
                request,
                studio,
                [gateway],
                model=ScriptedModel(
                    [read_t2v(), generate(name, "first"), generate(name, "second"), check_cap]
                ),
            )
            gateway.call_tool.assert_awaited_once()
            self.assertTrue(studio.session_items[0]["spending"]["stopped"])
