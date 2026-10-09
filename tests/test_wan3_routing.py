from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Tool

from agent.deep_agent import routing
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final

T2V = "Fal___generate_wan3_t2v"
I2V = "Fal___generate_wan3_i2v"
R2V = "Fal___generate_wan3_r2v"
TOOLS = [Tool(name=name, description="Generate Wan 3.0 video", inputSchema={"type": "object"})
         for name in (T2V, I2V, R2V)]


class Wan3RoutingTests(unittest.TestCase):
    def test_defaults_are_ready_without_seedance_interim(self):
        for capability, alias, tool in [("t2v", "wan3_t2v", T2V), ("i2v", "wan3_i2v", I2V),
                                        ("reference_video", "wan3_r2v", R2V)]:
            with self.subTest(capability=capability):
                route = routing.select_provider(capability)
                self.assertEqual((route.alias, route.tool, route.provider, route.status),
                                 (alias, tool, "fal", "ready"))
                self.assertNotIn("interim", route.disclosure)
                self.assertIsNone(routing.POLICY["capability_map"][capability]["interim"])

    def test_dialogue_exception_and_real_faces(self):
        self.assertEqual(routing.route_intent('robot says "hello"').alias, "seedance25_t2v")
        self.assertEqual(routing.route_intent('use Wan 3.0 for a robot that says "hello"').tool, T2V)
        route = routing.route_intent('use Seedance with my CEO photo saying "hello"')
        self.assertEqual(route.tool, I2V)
        self.assertIn("consent", route.disclosure.lower())

    def test_reference_controls_and_first_last_frames(self):
        route = routing.select_provider("reference_video", arguments={
            "reference_video_urls": ["https://example.invalid/ref.mp4"],
            "reference_video_durations": [10], "reference_video_fps": [24],
            "reference_audio_urls": ["https://example.invalid/ref.wav"],
            "reference_audio_durations": [5], "audio": True,
            "duration": 30, "resolution": "1080p",
        })
        self.assertEqual((route.status, route.tool), ("ready", R2V))
        self.assertEqual(routing.route_intent("Wan first last frame morph").tool, I2V)

    def test_paid_approval_and_no_fallback(self):
        for tool in (T2V, I2V, R2V):
            self.assertTrue(tool_needs_approval(tool, autonomous=True))
            self.assertTrue(tool_needs_approval(tool, autonomous=False))
        route = routing.select_provider("t2v", available_tools={"Seedance___text_to_video"})
        self.assertEqual(route.status, "blocked")
        self.assertIsNone(route.tool)

    def test_list_price_survives_dry_run_and_counts_input_seconds(self):
        from server.billing_rates import _with_fee
        with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
            for resolution, rate in [("480p", 5), ("720p", 10), ("1080p", 20)]:
                route = routing.select_provider("t2v", arguments={"duration": 5, "resolution": resolution})
                self.assertEqual(route.estimated_cost["total_cents"], _with_fee(5 * rate).total_cents)
            quote = routing.estimate_cost(R2V, {"duration": 5, "resolution": "720p",
                "reference_video_urls": ["https://example.invalid/ref.mp4"],
                "reference_video_durations": [10], "reference_video_fps": [24]}, list_price=True)
            self.assertEqual(quote.total_cents, _with_fee(150).total_cents)

    def test_smart_duration_and_missing_reference_lengths_are_unknown(self):
        for arguments in [{"duration": None}, {"reference_video_urls": ["https://example.invalid/a.mp4"]}]:
            self.assertIsNone(routing.estimate_cost(R2V, arguments, list_price=True).total_cents)

    def test_fixed_models_and_training_policy(self):
        for tool, model in [(T2V, "text-to-video"), (I2V, "image-to-video"), (R2V, "reference-to-video")]:
            endpoint = "alibaba/wan-3.0/" + model
            self.assertEqual(routing.effective_model("fal", tool.split("___")[1], {}), endpoint)
            self.assertIsNone(routing.policy_blocker(tool, {}))
            self.assertIsNotNone(routing.policy_blocker(tool, {"model": "fal-ai/wan-vace-14b"}))
            self.assertFalse(routing.training_eligible({"provider": "fal", "model": endpoint,
                "training_eligible": True, "weights_license": "Apache-2.0", "status": "succeeded"}))


class Wan3GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_real_face_requires_consent_even_if_flag_omitted(self):
        request = StudioAgentRequest(prompt="animate my CEO photo", autonomous=True, job_id="consent")
        gateway = Gateway(TOOLS)
        executor = GatewayExecutor(_context_from_request(request), [gateway])
        for arguments in [{"prompt": "CEO", "start_image_url": "https://example.invalid/ceo.png"},
                          {"prompt": "CEO", "start_image_url": "https://example.invalid/ceo.png",
                           "real_face_refs": True, "likeness_consent": False}]:
            result = await executor.execute({"tool_name": I2V, "arguments": arguments, "call_id": "face"}, approved=True)
            self.assertEqual(result["status"], "not_run")
            self.assertIn("consent", result["reason"].lower())
        gateway.call_tool.assert_not_awaited()

    async def test_reference_video_and_default_audio_are_valid(self):
        request = StudioAgentRequest(prompt="reference video with native audio", autonomous=True, job_id="references")
        gateway = Gateway(TOOLS, {"status": "queued", "job_id": "wan3-job"})
        arguments = {"prompt": "A scene", "reference_video_urls": ["https://example.invalid/ref.mp4"],
                     "reference_video_durations": [5], "reference_video_fps": [24]}
        executor = GatewayExecutor(_context_from_request(request), [gateway])
        result = await executor.execute({"tool_name": R2V, "arguments": arguments, "call_id": "ref"}, approved=True)
        self.assertEqual(result["status"], "queued")
        gateway.call_tool.assert_awaited_once()

    async def test_explicitly_disabled_native_audio_cannot_dispatch(self):
        request = StudioAgentRequest(prompt="generate a video with native audio", autonomous=True, job_id="silent")
        gateway = Gateway(TOOLS)
        result = await GatewayExecutor(_context_from_request(request), [gateway]).execute({
            "tool_name": T2V, "arguments": {"prompt": "A scene", "audio": False}, "call_id": "silent"}, approved=True)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("native_audio", result["reason"])
        gateway.call_tool.assert_not_awaited()

    async def test_consent_acknowledgement_and_end_frame_dispatch(self):
        request = StudioAgentRequest(prompt="animate my CEO photo with first and last frame", autonomous=True, job_id="face")
        gateway = Gateway(TOOLS, {"status": "queued", "job_id": "wan3-job"})
        arguments = {"prompt": "CEO", "start_image_url": "https://example.invalid/start.png",
                     "end_image_url": "https://example.invalid/end.png", "likeness_consent": True}
        executor = GatewayExecutor(_context_from_request(request), [gateway])
        result = await executor.execute({"tool_name": I2V, "arguments": arguments, "call_id": "face"}, approved=True)
        self.assertEqual(result["status"], "queued")
        self.assertIn("acknowledged", executor.media_selection(I2V, arguments).disclosure)
        gateway.call_tool.assert_awaited_once()

    async def test_native_deep_agent_autonomous_approval_resume_and_rejection(self):
        from server.billing_rates import _with_fee
        for decision in ("approve", "reject"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"FAL_DRY_RUN": "true", "RENDERHAUS_OUTCOME_DIR": directory},
            ):
                request = StudioAgentRequest(prompt="generate a 5 second cinematic shot", autonomous=True,
                    workspace_id="workspace", project_id="project", job_id="wan3-" + decision)
                studio = _context_from_request(request)
                gateway = Gateway(TOOLS, {"status": "queued", "job_id": "wan3-job"})
                with self.assertRaises(StudioAgentApprovalRequired) as paused:
                    await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                        call("read_file", {"file_path": "/skills/t2v/SKILL.md"}, "skill"),
                        call("call_media_tool", {"tool_name": T2V, "arguments": {"prompt": "A scene", "duration": 5}}, "video"),
                    ]))
                approval = paused.exception.approvals[0]
                self.assertIn(f"${_with_fee(100).total_cents / 100:.2f}", approval.description)
                self.assertIn("alibaba/wan-3.0/text-to-video", approval.description)
                gateway.call_tool.assert_not_awaited()
                resumed = request.model_copy(update={"session_items": studio.session_items,
                    "resume_state": paused.exception.state,
                    "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=decision)]})
                await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
                if decision == "approve":
                    gateway.call_tool.assert_awaited_once()
                else:
                    gateway.call_tool.assert_not_awaited()
                    rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
                    self.assertEqual((rows[-1]["provider"], rows[-1]["model"], rows[-1]["stage"]),
                                     ("fal", "alibaba/wan-3.0/text-to-video", "approval"))
                    self.assertFalse(rows[-1]["training_eligible"])
