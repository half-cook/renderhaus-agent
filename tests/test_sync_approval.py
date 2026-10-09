from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from mcp import Tool

from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final
from test_sync_wiring import ARGS


class SyncNativeApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_native_pause_and_fresh_worker_approve_or_reject(self):
        for decision in ("approve", "reject"):
            with self.subTest(decision=decision):
                name = "Sync___lipsync_video"
                request = StudioAgentRequest(
                    prompt="lipsync this interview footage", autonomous=True,
                    workspace_id="sync-workspace", project_id="sync-project",
                    conversation_id=f"sync-{decision}", job_id=f"sync-{decision}",
                )
                gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
                studio = _context_from_request(request)
                with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                    "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false",
                    "SYNC_DRY_RUN": "true", "SYNC_TRANSPORT": "fal",
                }):
                    with self.assertRaises(StudioAgentApprovalRequired) as paused:
                        await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                            call("read_file", {"file_path": "/skills/lipsync/SKILL.md"}, "skill"),
                            call("call_media_tool", {"tool_name": name, "arguments": ARGS}, "sync"),
                        ]))
                    gateway.call_tool.assert_not_awaited()
                    approval = paused.exception.approvals[0]
                    self.assertIn("Alice", approval.description)
                    self.assertIn("consent", approval.description.lower())
                    self.assertIn("fal", approval.description.lower())
                    self.assertIn("$1.39", approval.description)
                    resumed = request.model_copy(update={
                        "session_items": json.loads(json.dumps(studio.session_items)),
                        "resume_state": paused.exception.state,
                        "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=decision)],
                    })
                    restored = _context_from_request(resumed)
                    await run_with_servers(
                        resumed, restored, [gateway], model=ScriptedModel([final()]),
                    )
                    if decision == "approve":
                        gateway.call_tool.assert_awaited_once_with(name, ARGS)
                    else:
                        gateway.call_tool.assert_not_awaited()
                        self.assertEqual(restored.tool_events[0].status, "rejected")

    async def test_real_face_uses_sync_consent_contract_without_wan_fields(self):
        request = StudioAgentRequest(prompt="lip-sync my face in this footage", autonomous=True)
        studio = _context_from_request(request)
        name = "Sync___lipsync_video"
        gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
        executor = GatewayExecutor(studio, [gateway])
        with patch.dict(os.environ, {"SYNC_DRY_RUN": "true"}):
            result = await executor.execute({"tool_name": name, "arguments": ARGS, "call_id": "sync"}, approved=True)
        self.assertNotEqual(result.get("status"), "not_run")
        gateway.call_tool.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
