from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import Tool

from agent.deep_agent import routing
from agent.gateway_executor import tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from providers.fal import api as fal
from providers.registry import dispatch
from server.billing_rates import cost_for
from test_deep_agent import Gateway, ScriptedModel, call, final


ENDPOINT = "mirelo-ai/sfx1.6/video-to-video"
TOOL = "Fal___mirelo_v2a"
ARGS = {"video_url": "https://example.com/silent.mp4", "duration": 12.5, "num_samples": 1}


class MireloProviderTests(unittest.TestCase):
    def test_gateway_tool_is_available(self):
        self.assertIn("mirelo_v2a", fal.GATEWAY_TOOLS)

    def test_invalid_controls_never_submit(self):
        cases = [{"video_url": "/etc/passwd"}, {"video_url": "http://example.com/a.mp4"},
                 {"video_url": "https://user:password@example.com/a.mp4"}, {"duration": 0},
                 {"duration": 60.01}, {"duration": True}, {"duration": float("nan")},
                 {"duration": None}, {"num_samples": 0}, {"num_samples": 5},
                 {"num_samples": True}, {"num_samples": 1.5}, {"num_samples": None},
                 {"seed": -2}, {"seed": True}, {"text_prompt": 123}, {"extra": "bad"}]
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
            for invalid in cases:
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    dispatch("fal", "mirelo_v2a", {**ARGS, **invalid})
            client.assert_not_called()

    def test_default_dry_run_and_saved_dry_handle_never_touch_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(httpx, "Client") as client:
            result = dispatch("fal", "mirelo_v2a", {"video_url": ARGS["video_url"]})
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["request_preview"], {"video_url": ARGS["video_url"], "duration": 10.0, "num_samples": 1})
            self.assertEqual(result["estimated_cost_usd"], 0.10)
            self.assertFalse(result["training_eligible"])
            self.assertNotIn("output_path", result)
            with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
                polled = dispatch("fal", "get_video_task", {"job_id": result["job_id"], "download": True})
                self.assertEqual(polled["status"], "dry_run")
            client.assert_not_called()

    def test_submit_posts_verified_payload_over_mock_http(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"request_id": "fake-mirelo", "status": "IN_QUEUE"})
        client = httpx.Client(transport=httpx.MockTransport(respond))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
            {"FAL_DRY_RUN": "false", "FAL_KEY": "fake", "RENDERHAUS_MEDIA_DIR": directory}), patch.object(httpx, "Client", return_value=client):
            result = dispatch("fal", "mirelo_v2a", {**ARGS, "text_prompt": "Footsteps on gravel, no music.", "seed": 42})
        self.assertEqual(str(requests[0].url), "https://queue.fal.run/" + ENDPOINT)
        self.assertEqual(json.loads(requests[0].content), {**ARGS, "text_prompt": "Footsteps on gravel, no music.", "seed": 42})
        self.assertEqual(result["job_id"], ENDPOINT + ":fake-mirelo")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["estimated_cost_usd"], 0.125)

    def test_extra_samples_preview_has_unknown_cost_and_blocks_paid_submit(self):
        for samples in (2, 3, 4):
            args = {**ARGS, "num_samples": samples}
            with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
                preview = dispatch("fal", "mirelo_v2a", args)
                self.assertEqual(preview["request_preview"]["num_samples"], samples)
                self.assertIsNone(preview["estimated_cost_usd"])
                self.assertIsNone(routing.estimate_cost(TOOL, args).total_cents)
            with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
                with self.assertRaisesRegex(ValueError, "unknown"):
                    dispatch("fal", "mirelo_v2a", args)
                client.assert_not_called()

    def test_poll_normalizes_all_variants_and_downloads_primary_once(self):
        videos = [{"url": "https://example.com/one.mp4", "content_type": "video/mp4"},
                  {"url": "https://example.com/two.mp4", "content_type": "video/mp4"}]
        def download(url, path):
            path.write_bytes(b"fake mp4")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
            {"FAL_DRY_RUN": "false", "RENDERHAUS_MEDIA_DIR": directory}), patch.object(fal.queue, "status", return_value={"status": "COMPLETED"}), patch.object(fal.queue, "result", return_value={"model": "sfx-1.6", "video": videos}), patch.object(fal, "_download", side_effect=download) as save:
            args = {"job_id": ENDPOINT + ":fake-mirelo", "download": True}
            result = dispatch("fal", "get_video_task", args)
            self.assertEqual(result["video_url"], "https://example.com/one.mp4")
            self.assertEqual(result["videos"], videos)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(Path(result["output_path"]).read_bytes(), b"fake mp4")
            self.assertFalse(result["training_eligible"])
            dispatch("fal", "get_video_task", args)
            self.assertEqual(save.call_count, 1)

    def test_poll_rejects_malformed_outputs_before_download(self):
        for videos in ([], {"url": "https://example.com/a.mp4"}, [{"url": "file:///etc/passwd"}],
                       [{"url": "https://example.com/a.mp4"}, {}]):
            with self.subTest(videos=videos), patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(fal.queue, "status", return_value={"status": "COMPLETED"}), patch.object(fal.queue, "result", return_value={"model": "sfx-1.6", "video": videos}), patch.object(fal, "_download") as save:
                with self.assertRaises(RuntimeError):
                    dispatch("fal", "get_video_task", {"job_id": ENDPOINT + ":fake-mirelo", "download": True})
                save.assert_not_called()

    def test_poll_queued_failed_and_provider_validation_error(self):
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(fal.queue, "status", return_value={"status": "IN_PROGRESS"}), patch.object(fal.queue, "result") as fetch:
            self.assertEqual(dispatch("fal", "get_video_task", {"job_id": ENDPOINT + ":fake"})["status"], "running")
            fetch.assert_not_called()
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(fal.queue, "status", return_value={"status": "COMPLETED"}), patch.object(fal.queue, "result", side_effect=fal.queue.FalAPIError(422, "Invalid video")):
            self.assertEqual(dispatch("fal", "get_video_task", {"job_id": ENDPOINT + ":fake"})["status"], "failed")


class MireloRoutingTests(unittest.TestCase):
    def test_default_exception_explicit_and_video_arguments(self):
        cases = [("add foley from the video", {}, TOOL, "default"),
                 ("a whoosh sound effect", {}, "ElevenLabs___text_to_sound_effects_convert", "exception:"),
                 ("add SFX", {"video_url": ARGS["video_url"]}, TOOL, "default"),
                 ("text-only SFX", {"video_url": ARGS["video_url"]}, TOOL, "default"),
                 ("use ElevenLabs for foley from video", {}, "ElevenLabs___text_to_sound_effects_convert", "explicit request"),
                 ("use Mirelo for a whoosh sound effect", {}, TOOL, "explicit request")]
        for prompt, args, tool, basis in cases:
            with self.subTest(prompt=prompt):
                route = routing.route_intent(prompt, arguments=args)
                self.assertEqual((route.status, route.tool), ("ready", tool))
                self.assertIn(basis, route.disclosure)
                self.assertEqual(route.public(), routing.route_intent(prompt, arguments=args, confidential=True).public())

    def test_price_disclosure_does_not_become_free_in_dry_run(self):
        with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
            self.assertEqual(cost_for("fal", "mirelo_v2a", ARGS).total_cents, 0)
            self.assertGreaterEqual(routing.estimate_cost(TOOL, ARGS).total_cents, 13)
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
            self.assertEqual(cost_for("fal", "mirelo_v2a", ARGS).provider_cents, 13)
        for autonomous in (True, False):
            self.assertTrue(tool_needs_approval(TOOL, autonomous))
        self.assertFalse(tool_needs_approval("Fal___get_video_task", True))


class MireloApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_autonomous_costed_interrupt_and_rejection_never_submit(self):
        from agent.deep_agent.runner import run_with_servers
        schemas = json.loads(Path("configs/gateway/fal.tools.json").read_text())
        gateway = Gateway([Tool(name="Fal___" + t["name"], description=t["description"], inputSchema=t["inputSchema"]) for t in schemas])
        request = StudioAgentRequest(prompt="add foley from the video", autonomous=True, job_id="mirelo-test", project_id="project", workspace_id="workspace")
        studio = _context_from_request(request)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory, "FAL_DRY_RUN": "true"}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/audio-bed/SKILL.md"}, "skill"),
                    call("call_media_tool", {"tool_name": TOOL, "arguments": ARGS}, "sfx")]))
            approval = paused.exception.approvals[0]
            self.assertIn("Estimated cost $", approval.description)
            self.assertIn(ENDPOINT, approval.description)
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={"session_items": studio.session_items, "resume_state": paused.exception.state,
                "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision="reject")]})
            await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_not_awaited()
            rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
            self.assertEqual((rows[-1]["provider"], rows[-1]["outcome"], rows[-1]["stage"]), ("fal", "rejected", "approval"))
