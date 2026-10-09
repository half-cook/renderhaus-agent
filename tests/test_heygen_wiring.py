from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from mcp import Tool

from agent.deep_agent import routing
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision,
    StudioToolEvent, _context_from_request, _validate_video_delivery,
)
from server.billing_rates import cost_for
import server.studio as studio_api
from test_deep_agent import Gateway, ScriptedModel, call, final


NAME = "HeyGen___create_avatar_video"
ARGS = {
    "avatar_id": "lk_alice", "voice_id": "voice_alice", "script": "Bonjour tout le monde.",
    "duration_seconds": 90.0, "subjects": "Presenter Alice and her authorized voice",
    "consent_confirmed": True, "consent_record_id": "consent-alice-2026",
    "language": "fr-FR", "resolution": "1080p",
}


class HeyGenWiringTests(unittest.TestCase):
    def test_long_presenters_use_exception_with_explicit_request_first(self):
        for prompt in ("2 minute multilingual presenter video of my digital twin",
                       "90 second training video with an avatar presenter in French and German"):
            for confidential in (False, True):
                route = routing.route_intent(prompt, confidential=confidential)
                self.assertEqual(route.status, "ready")
                self.assertEqual(route.alias, "heygen_avatar_v")
                self.assertEqual(route.tool, NAME)
                self.assertEqual(route.dispatch_tool, "call_media_tool")
                self.assertIn("exception", route.basis)
        self.assertEqual(routing.route_intent("use sync-3 for a 90 second presenter").alias, "sync3_lipsync")
        for prompt in ("use HeyGen for this 20 second presenter", "HeyGen Avatar V 20 second video"):
            route = routing.route_intent(prompt)
            self.assertEqual(route.tool, NAME)
            self.assertIn("explicit", route.basis)
        self.assertEqual(routing.route_intent("30 second presenter video").alias, "sync3_lipsync")
        self.assertEqual(routing.route_intent("dub a 90 second interview clip").alias, "sync3_lipsync")
        self.assertEqual(routing.route_intent("make a HeyGen generative video clip").status, "retired")

    def test_approval_is_mandatory_even_with_global_switch_off(self):
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            for autonomous in (False, True):
                self.assertTrue(tool_needs_approval(NAME, autonomous))
                self.assertTrue(tool_needs_approval("heygen_avatar_v", autonomous))
        for name in ("get_video_status", "list_avatars", "list_voices"):
            self.assertTrue(routing.is_free_tool(f"HeyGen___{name}"))
            self.assertEqual(cost_for("heygen", name, {}).total_cents, 0)

    def test_unknown_price_is_never_zero_list_quote(self):
        with patch.dict(os.environ, {"HEYGEN_DRY_RUN": "true"}):
            for list_price in (False, True):
                quote = routing.estimate_cost(NAME, ARGS, list_price=list_price)
                self.assertIsNone(quote.total_cents)
                self.assertIn("unknown", quote.description.lower())
            self.assertEqual(cost_for("heygen", "create_avatar_video", ARGS).total_cents, 0)
        with patch.dict(os.environ, {"HEYGEN_DRY_RUN": "false", "HEYGEN_API_PLAN": "paid_self_serve"}):
            with self.assertRaisesRegex(ValueError, "unknown"):
                cost_for("heygen", "create_avatar_video", ARGS)

    def test_consent_record_required_at_host_boundary(self):
        executor = object.__new__(GatewayExecutor)
        executor.studio = SimpleNamespace(prompt="90 second presenter of my digital twin")
        route = routing.route_intent(executor.studio.prompt, arguments=ARGS)
        self.assertIsNone(executor.selection_blocker(NAME, ARGS, route))
        for change in ({"consent_confirmed": False}, {"consent_confirmed": "true"},
                       {"subjects": " "}, {"consent_record_id": ""}):
            self.assertIsNotNone(executor.selection_blocker(NAME, {**ARGS, **change}, route))
        disclosure = executor.dispatch_disclosure(NAME, ARGS, route)
        for text in ("Alice", "consent", "unknown", "training", "API"):
            self.assertIn(text.lower(), disclosure.lower())
        self.assertFalse(routing.training_eligible({"provider": "heygen", "model": "avatar_v",
            "status": "succeeded", "training_eligible": True, "weights_license": "Apache-2.0"}))

    def test_saved_mp4_finishes_standalone_presenter_but_assembly_needs_remotion(self):
        for suffix, expected in (("", True), (" without captions", True), (" with captions", False)):
            request = StudioAgentRequest(prompt=f"make a 90 second presenter MP4{suffix}")
            studio = _context_from_request(request)
            studio.tool_events.append(StudioToolEvent(
                id="heygen-poll", name="HeyGen___get_video_status", label="HeyGen poll",
                summary="Saved output", status="succeeded", result={
                    "status": "succeeded", "downloaded": True,
                    "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4"),
                },
            ))
            self.assertEqual(_validate_video_delivery(request, studio), expected)
        for status, downloaded in (("dry_run", False), ("queued", False), ("succeeded", False)):
            request = StudioAgentRequest(prompt="make a 90 second presenter MP4")
            studio = _context_from_request(request)
            studio.tool_events.append(StudioToolEvent(
                id="heygen-poll", name="HeyGen___get_video_status", label="HeyGen poll",
                summary="Incomplete", status=status, result={"status": status, "downloaded": downloaded},
            ))
            self.assertFalse(_validate_video_delivery(request, studio))


class HeyGenNativeApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_pause_then_fresh_worker_approve_or_reject(self):
        for decision in ("approve", "reject"):
            request = StudioAgentRequest(
                prompt="use HeyGen for a 90 second multilingual presenter of my digital twin",
                autonomous=True, workspace_id="heygen-workspace", project_id="heygen-project",
                conversation_id=f"heygen-{decision}", job_id=f"heygen-{decision}",
            )
            gateway = Gateway([Tool(name=NAME, inputSchema={"type": "object"})])
            studio = _context_from_request(request)
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false",
                "HEYGEN_DRY_RUN": "true",
            }):
                with self.assertRaises(StudioAgentApprovalRequired) as paused:
                    await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                        call("read_file", {"file_path": "/skills/lipsync/SKILL.md"}, "skill"),
                        call("call_media_tool", {"tool_name": NAME, "arguments": ARGS}, "heygen"),
                    ]))
                gateway.call_tool.assert_not_awaited()
                approval = paused.exception.approvals[0]
                for text in ("Alice", "consent", "unknown", "avatar_v"):
                    self.assertIn(text.lower(), approval.description.lower())
                resumed = request.model_copy(update={
                    "session_items": json.loads(json.dumps(studio.session_items)),
                    "resume_state": paused.exception.state,
                    "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=decision)],
                })
                restored = _context_from_request(resumed)
                await run_with_servers(resumed, restored, [gateway], model=ScriptedModel([final()]))
                if decision == "approve":
                    gateway.call_tool.assert_awaited_once_with(NAME, ARGS)
                else:
                    gateway.call_tool.assert_not_awaited()
                    self.assertEqual(restored.tool_events[0].status, "rejected")

    async def test_direct_studio_invoke_cannot_bypass_agent_approval(self):
        body = studio_api.InvokeBody(provider="heygen", tool="create_avatar_video", arguments=ARGS, project_id="untitled")
        with patch.object(studio_api.repository, "require_project"), \
                patch.object(studio_api, "dispatch") as dispatch, patch.object(studio_api, "cost_for") as quote:
            with self.assertRaises(HTTPException) as denied:
                await studio_api.invoke_tool(body, None)
            self.assertEqual(denied.exception.status_code, 409)
            self.assertIn("approval", denied.exception.detail.lower())
            dispatch.assert_not_called()
            quote.assert_not_called()

    async def test_studio_reports_default_dry_run(self):
        with patch.dict(os.environ, {"HEYGEN_DRY_RUN": "true"}), \
                patch.object(studio_api, "agent_configured", return_value=False):
            result = await studio_api.studio_status()
        self.assertTrue(result["dry_run"]["heygen"])
