from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Tool
from fastapi import HTTPException

from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request
from test_deep_agent import Gateway, ScriptedModel, call, final
from test_performance_transfer import MOTION, MOTION_ARGS


class PerformanceApproval(unittest.IsolatedAsyncioTestCase):
    async def test_direct_studio_invoke_cannot_bypass_consent_and_approval(self):
        from server import studio

        for provider, tool, args in [ ("fal", "kling_motion_control", MOTION_ARGS)]:
            body = studio.InvokeBody(provider=provider, tool=tool, arguments=args, project_id="untitled")
            with patch.object(studio.repository, "require_project"), patch.object(studio, "dispatch") as dispatch, \
                    patch.object(studio, "cost_for") as quote, patch.object(studio.repository, "charge_usage") as charge:
                with self.assertRaises(HTTPException) as denied:
                    await studio.invoke_tool(body, None)
                self.assertEqual(denied.exception.status_code, 409)
                self.assertIn("consent", denied.exception.detail)
                self.assertIn("approval", denied.exception.detail)
                dispatch.assert_not_called()
                quote.assert_not_called()
                charge.assert_not_called()

    async def test_native_approval_includes_consent_and_price_then_resumes_once_or_rejects(self):
        for name, args, prompt, expected_price in [
            (MOTION, MOTION_ARGS, "copy my whole-body dance", "$1.09")]:
            for decision in ("approve", "reject"):
                with self.subTest(name=name, decision=decision), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                    {"RENDERHAUS_OUTCOME_DIR": directory, "RUNWAY_DRY_RUN": "true", "FAL_DRY_RUN": "true"}):
                    provider = "fal"
                    schemas = json.loads(Path(f"configs/gateway/{provider}.tools.json").read_text())
                    gateway = Gateway([Tool(name=name.split("___")[0] + "___" + row["name"],
                        description=row["description"], inputSchema=row["inputSchema"]) for row in schemas],
                        result={"status": "dry_run", "provider": provider, "model": "fal-ai/kling-video/v3/pro/motion-control"})
                    request = StudioAgentRequest(prompt=prompt, autonomous=True, job_id=f"performance-{provider}-{decision}")
                    studio = _context_from_request(request)
                    with self.assertRaises(StudioAgentApprovalRequired) as paused:
                        await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                            call("read_file", {"file_path": "/skills/named-provider/SKILL.md"}, "skill"),
                            call("call_media_tool", {"tool_name": name, "arguments": args}, "performance")]))
                    approval = paused.exception.approvals[0]
                    self.assertIn(expected_price, approval.description)
                    self.assertIn("Consent confirmed", approval.description)
                    self.assertIn(args["subjects"], approval.description)
                    gateway.call_tool.assert_not_awaited()
                    resumed = request.model_copy(update={"session_items": studio.session_items,
                        "resume_state": paused.exception.state, "approval_decisions": [
                            StudioApprovalDecision(call_id=approval.call_id, decision=decision)]})
                    await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
                    if decision == "approve":
                        gateway.call_tool.assert_awaited_once_with(name, args)
                    else:
                        gateway.call_tool.assert_not_awaited()

    async def test_missing_consent_is_blocked_even_if_approved(self):
        for name, args, prompt in [ (MOTION, MOTION_ARGS, "copy whole-body dance")]:
            gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
            request = StudioAgentRequest(prompt=prompt, autonomous=True)
            executor = GatewayExecutor(_context_from_request(request), [gateway])
            result = await executor.execute({"tool_name": name, "arguments": {**args, "consent_confirmed": False}, "call_id": "no-consent"}, approved=True)
            self.assertEqual(result["status"], "not_run")
            gateway.call_tool.assert_not_awaited()
