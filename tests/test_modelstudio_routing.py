from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent import routing
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from mcp import Tool
from test_deep_agent import Gateway, ScriptedModel, call, final

EDIT = "ModelStudio___edit_wan3_video"
EXTEND = "ModelStudio___extend_wan3_video"
POLL = "ModelStudio___get_task"
SOURCE = {"video_url": "https://example.invalid/source.mp4", "source_duration_seconds": 5,
          "source_fps": 24, "prompt": "Make the scene clay", "duration": 7}


class ModelStudioRoutingTests(unittest.TestCase):
    def test_defaults_and_explicit_requests_select_real_tools(self):
        for capability, alias, tool in [("v2v_edit", "wan3_edit", EDIT), ("extend", "wan3_extend", EXTEND)]:
            for tier in (None, "draft", "standard", "premium"):
                with self.subTest(capability=capability, tier=tier):
                    route = routing.select_provider(capability, tier=tier)
                    self.assertEqual((route.status, route.alias, route.tool, route.provider),
                                     ("ready", alias, tool, "alibaba_modelstudio"))
                    self.assertIsNone(routing.POLICY["capability_map"][capability]["interim"])
                    self.assertEqual(routing.POLICY["capability_map"][capability]["exceptions"], [])
                    self.assertNotIn("interim", route.disclosure)
        for prompt, tool in [("restyle this footage", EDIT), ("extend this clip by 10 seconds", EXTEND),
                             ("use Wan 3 to edit this video", EDIT),
                             ("Model Studio edit this video", EDIT), ("DashScope extend this clip", EXTEND)]:
            self.assertEqual(routing.route_intent(prompt).tool, tool, prompt)

    def test_named_demoted_tools_and_confidential_field_are_preserved(self):
        for prompt, tool in [("use Runway Aleph to relight this clip", "Runway___video_to_video"),
                             ("Luma modify this video", "Luma___modify_video"),
                             ("Luma extend this clip", "Luma___extend_video"),
                             ("edit this with Wan VACE", "Fal___video_to_video")]:
            self.assertEqual(routing.route_intent(prompt).tool, tool)
        for prompt in ("restyle this footage", "extend this clip"):
            self.assertEqual(routing.route_intent(prompt, confidential=True).public(),
                             routing.route_intent(prompt, confidential=False).public())

    def test_all_paid_video_pauses_and_missing_default_never_falls_back(self):
        for tool in (EDIT, EXTEND):
            self.assertTrue(tool_needs_approval(tool, True))
            self.assertTrue(tool_needs_approval(tool, False))
        self.assertTrue(routing.is_free_tool(POLL))
        self.assertFalse(tool_needs_approval(POLL, True))
        self.assertEqual(routing.select_provider("v2v_edit", available_tools={"Luma___modify_video"}).status,
                         "blocked")

    def test_list_cost_counts_source_and_total_output_seconds(self):
        from server.billing_rates import _with_fee

        with patch.dict(os.environ, {"MODELSTUDIO_DRY_RUN": "true", "DASHSCOPE_REGION": "us-east-1"}):
            quote = routing.estimate_cost(EXTEND, SOURCE, list_price=True)
            self.assertEqual(quote.total_cents, _with_fee(round(12 * 16.5025)).total_cents)
            for arguments in ({**SOURCE, "duration": -1}, {"duration": 7},
                              {**SOURCE, "source_duration_seconds": float("nan")}):
                self.assertIsNone(routing.estimate_cost(EDIT, arguments, list_price=True).total_cents)
            route = routing.select_provider("v2v_edit", arguments={**SOURCE, "duration": -1})
            self.assertEqual(route.status, "ready")
            self.assertIsNone(route.estimated_cost["total_cents"])

    def test_extend_by_seconds_uses_total_output_requirement(self):
        route = routing.route_intent("extend this clip by 2 seconds", arguments=SOURCE)
        self.assertEqual((route.status, route.tool), ("ready", EXTEND))
        self.assertEqual(route.required["duration_seconds"], 7)
        self.assertEqual(route.required["extension_seconds"], 2)

    def test_training_and_unsupported_model_are_blocked(self):
        self.assertFalse(routing.training_eligible({"provider": "alibaba_modelstudio", "model": "wan3.0-video",
            "training_eligible": True, "weights_license": "Apache-2.0", "status": "succeeded"}))
        self.assertIsNotNone(routing.policy_blocker(EDIT, {"model": "other-model"}))
        with patch.dict(os.environ, {"MODELSTUDIO_DRY_RUN": "false", "DASHSCOPE_BASE_URL": "https://dashscope-us.aliyuncs.com"}):
            self.assertIn("UNVERIFIED", routing.policy_blocker(EDIT, SOURCE))


class ModelStudioGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_autonomous_interrupt_approve_reject_and_recovery(self):
        from server.billing_rates import _with_fee

        tools = [Tool(name=name, inputSchema={"type": "object"}) for name in (EDIT, EXTEND, POLL)]
        for tool, prompt in [(EDIT, "restyle this footage"), (EXTEND, "extend this clip")]:
            for decision in ("approve", "reject"):
                with self.subTest(tool=tool, decision=decision), tempfile.TemporaryDirectory() as directory, patch.dict(
                    os.environ, {"MODELSTUDIO_DRY_RUN": "true", "DASHSCOPE_REGION": "us-east-1",
                                 "RENDERHAUS_OUTCOME_DIR": directory},
                ):
                    request = StudioAgentRequest(prompt=prompt, autonomous=True, workspace_id="workspace",
                        project_id="project", job_id=tool + decision)
                    studio = _context_from_request(request)
                    gateway = Gateway(tools, {"status": "queued", "job_id": "task-saved"})
                    with self.assertRaises(StudioAgentApprovalRequired) as paused:
                        from agent.deep_agent.runner import run_with_servers

                        await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                            call("read_file", {"file_path": "/skills/edit-v2v/SKILL.md"}, "skill"),
                            call("call_media_tool", {"tool_name": tool, "arguments": SOURCE}, "video"),
                        ]))
                    approval = paused.exception.approvals[0]
                    self.assertIn("wan3.0-video", approval.description)
                    self.assertIn(f"${_with_fee(round(12 * 16.5025)).total_cents / 100:.2f}", approval.description)
                    gateway.call_tool.assert_not_awaited()
                    resumed = request.model_copy(update={"session_items": studio.session_items,
                        "resume_state": paused.exception.state,
                        "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=decision)]})
                    await run_with_servers(resumed, _context_from_request(resumed), [gateway],
                                           model=ScriptedModel([final()]))
                    if decision == "approve":
                        gateway.call_tool.assert_awaited_once()
                    else:
                        gateway.call_tool.assert_not_awaited()
                        rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
                        self.assertEqual((rows[-1]["provider"], rows[-1]["model"], rows[-1]["stage"]),
                                         ("alibaba_modelstudio", "wan3.0-video", "approval"))
                        self.assertFalse(rows[-1]["training_eligible"])

    async def test_real_likeness_and_extension_target_cannot_be_weakened(self):
        tools = [Tool(name=name, inputSchema={"type": "object"}) for name in (EDIT, EXTEND)]
        for prompt, tool, arguments, reason in [
            ("edit video of my CEO", EDIT, SOURCE, "consent"),
            ("extend this clip by 2 seconds", EXTEND, {**SOURCE, "duration": 2}, "duration"),
        ]:
            request = StudioAgentRequest(prompt=prompt, autonomous=True, job_id="guard")
            gateway = Gateway(tools)
            result = await GatewayExecutor(_context_from_request(request), [gateway]).execute(
                {"tool_name": tool, "arguments": arguments, "call_id": "guard"}, approved=True)
            self.assertEqual(result["status"], "not_run")
            self.assertIn(reason, result["reason"].lower())
            gateway.call_tool.assert_not_awaited()
