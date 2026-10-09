from __future__ import annotations

import unittest
import os
from unittest.mock import patch

from agent.codex_harness import ToolApprovalPending
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import (StudioAgentApprovalRequired, StudioAgentRequest,
                                    StudioApprovalDecision, _context_from_request,
                                    _validate_video_delivery)
from test_deep_agent import ScriptedModel, call, final


NAME = "Remotion___render_ad_variants"
ARGS = {"stage": "render_first", "job_id": "matrix", "master_asset": "master.mp4",
        "brief": {"campaign": "demo"}, "plan_hash": "a" * 64,
        "rows": [{"variant_key": "a", "sku": "A", "price_text": "$1", "cta_text": "Buy",
                  "logo_asset": "logo.png", "legal_text": "Terms", "locale": "en", "aspect": "1:1"}]}


class MatrixHostTests(unittest.IsolatedAsyncioTestCase):
    def request(self, autonomous=True):
        return StudioAgentRequest(prompt="make ad variants from a table", job_id="matrix", autonomous=autonomous)

    async def test_executor_pauses_both_stages_and_first_card_has_count_cost_aspects_hash(self):
        for autonomous in (False, True):
            for stage in ("render_first", "render_batch"):
                with self.subTest(autonomous=autonomous, stage=stage):
                    context = _context_from_request(self.request(autonomous))
                    executor = GatewayExecutor(context, [])
                    args = {**ARGS, "stage": stage}
                    with self.assertRaises(ToolApprovalPending):
                        await executor.execute({"tool_name": NAME, "arguments": args, "call_id": "sample"})
                    message = context.progress_events[-1].message
                    self.assertIn("Estimated cost $", message)
                    self.assertIn("1:1", message)
                    self.assertIn("a" * 64, message)
                    rejected = await executor.execute({"tool_name": NAME, "arguments": args, "call_id": "sample"}, rejection="No")
                    self.assertEqual(rejected["status"], "rejected")

    async def test_native_deep_agents_when_predicate_gates_plan_vs_first(self):
        request = self.request().model_copy(update={"conversation_id": "matrix-approval"})
        context = _context_from_request(request)
        model = ScriptedModel([call("call_editor_tool", {"tool_name": NAME, "arguments": ARGS}, "first")])
        with self.assertRaises(StudioAgentApprovalRequired) as caught:
            await run_with_servers(request, context, [], model=model)
        self.assertIn("plan hash", caught.exception.approvals[0].description)
        approval = caught.exception.approvals[0]
        resumed = request.model_copy(update={"session_items": context.session_items, "resume_state": caught.exception.state,
            "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision="reject", message="No batch")]})
        await run_with_servers(resumed, context, [], model=ScriptedModel([final()]))
        self.assertTrue(any(e.result.get("status") == "rejected" for e in context.tool_events))
        planned_args = {**ARGS, "stage": "plan"}
        planned_context = _context_from_request(request)
        await run_with_servers(request, planned_context, [], model=ScriptedModel([
            call("call_editor_tool", {"tool_name": NAME, "arguments": planned_args}, "plan"), final()]))
        self.assertFalse(any(e.status == "awaiting_approval" for e in planned_context.tool_events))

    def test_completion_accepts_only_a_whole_batch_of_real_artifacts(self):
        from agent.studio_agent_next import StudioToolEvent

        request = self.request()
        context = _context_from_request(request)
        result = {"status": "succeeded", "planned": 2, "failed": [], "blocked": [],
                  "rendered": [{"file": "first.mp4"}, {"file": "second.mp4"}]}
        context.record_event(StudioToolEvent(id="batch", name=NAME, status="succeeded", label="Matrix", summary="Rendered matrix",
                                            arguments={"stage": "render_batch"}, result=result))
        with patch("agent.studio_agent_next._completed_video_artifact", return_value=True):
            self.assertTrue(_validate_video_delivery(request, context))
        with patch("agent.studio_agent_next._completed_video_artifact", return_value=False):
            self.assertFalse(_validate_video_delivery(request, context))
        context.tool_events[-1].result["rendered"] = result["rendered"][:1]
        with patch("agent.studio_agent_next._completed_video_artifact", return_value=True):
            self.assertFalse(_validate_video_delivery(request, context))

    async def test_local_tools_cannot_read_another_trusted_studio_job(self):
        for user in ("customer-A", "customer-B"):
            request = StudioAgentRequest(prompt="inspect local media", user_id=user, workspace_id=user,
                                         project_id="project", job_id="trusted-" + user, autonomous=True)
            executor = GatewayExecutor(_context_from_request(request), [])
            result = await executor.execute({"tool_name": "Ffmpeg___ffmpeg_tool", "call_id": "inspect",
                "arguments": {"op": "probe", "job_id": "some-other-job", "input_path": "master.mp4"}})
            self.assertEqual(result["status"], "not_run")
            self.assertIn("Studio job", result["reason"])

    def test_previous_batch_cannot_certify_a_new_matrix_plan(self):
        from agent.studio_agent_next import StudioToolEvent

        request = self.request()
        context = _context_from_request(request)
        old = StudioToolEvent(id="old", name=NAME, status="succeeded", label="Matrix", summary="Old batch",
            arguments={"stage": "render_batch", "plan_hash": "a" * 64},
            result={"status": "succeeded", "planned": 1, "rendered": [{"file": "old.mp4"}]})
        request.prior_tool_events = [old.public()]
        context.record_event(old)
        context.record_event(StudioToolEvent(id="new", name=NAME, status="succeeded", label="Plan", summary="New plan",
            arguments={"stage": "plan"}, result={"status": "planned", "plan_hash": "b" * 64}))
        with patch("agent.studio_agent_next._completed_video_artifact", return_value=True):
            self.assertFalse(_validate_video_delivery(request, context))

    async def test_invalid_quote_configuration_is_refused_before_approval(self):
        executor = GatewayExecutor(_context_from_request(self.request()), [])
        with patch.dict(os.environ, {"REMOTION_LICENSE_RENDER_USD": "NaN"}):
            result = await executor.execute({"tool_name": NAME, "arguments": ARGS, "call_id": "invalid-quote"})
        self.assertEqual(result["status"], "not_run")
        self.assertIn("REMOTION_LICENSE_RENDER_USD", result["reason"])

    async def test_generic_invoke_refuses_local_workflow_tools_before_dispatch(self):
        from fastapi import HTTPException
        from server.studio import InvokeBody, invoke_tool

        for provider, tool in (("ffmpeg", "ffmpeg_tool"), ("remotion", "render_ad_variants")):
            with self.subTest(provider=provider):
                with patch("server.studio.repository.require_project"), patch("server.studio.dispatch") as dispatch:
                    with self.assertRaises(HTTPException) as caught:
                        await invoke_tool(InvokeBody(project_id="project", provider=provider, tool=tool,
                            arguments={"job_id": "another-job"}), None)
                self.assertEqual(caught.exception.status_code, 409)
                dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
