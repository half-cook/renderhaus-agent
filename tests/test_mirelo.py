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
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, StudioToolEvent, StudioNode,
    _context_from_request, _validate_video_delivery,
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

    def test_attached_asset_handle_quotes_before_resolution_and_never_submits_unresolved(self):
        args = {**ARGS, "video_url": "renderhaus-asset://version_123"}
        with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
            self.assertEqual(dispatch("fal", "mirelo_v2a", args)["status"], "dry_run")
            self.assertIsNotNone(routing.estimate_cost(TOOL, args).total_cents)
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
            with self.assertRaisesRegex(ValueError, "resolve"):
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
                 ("add SFX to this video", {}, TOOL, "default"),
                 ("sound effects for the attached clip", {}, TOOL, "default"),
                 ("text-only SFX", {"video_url": ARGS["video_url"]}, TOOL, "default"),
                 ("use ElevenLabs for foley from video", {}, "ElevenLabs___text_to_sound_effects_convert", "explicit request"),
                 ("use Mirelo for a whoosh sound effect", {}, TOOL, "explicit request")]
        for prompt, args, tool, basis in cases:
            with self.subTest(prompt=prompt):
                route = routing.route_intent(prompt, arguments=args)
                self.assertEqual((route.status, route.tool), ("ready", tool))
                self.assertIn(basis, route.disclosure)
                self.assertEqual(route.public(), routing.route_intent(prompt, arguments=args, confidential=True).public())

    def test_attached_video_and_worker_saved_artifact_are_required_for_delivery(self):
        request = StudioAgentRequest(prompt="add SFX", nodes=[StudioNode(
            id="video", title="Silent clip", kind="video", version_id="version_123")])
        studio = _context_from_request(request)
        self.assertFalse(_validate_video_delivery(request, studio))
        event = StudioToolEvent(id="poll", name="Fal___get_video_task", label="Mirelo poll",
            summary="Worker saved result", status="succeeded", result={
                "model": ENDPOINT, "status": "succeeded", "downloaded": True,
                "video_url": "https://example.com/foley.mp4", "output_path": "/tmp/worker-only.mp4"})
        studio.tool_events.append(event)
        self.assertFalse(_validate_video_delivery(request, studio))
        event.assets = [{"kind": "video", "asset_id": "asset", "version_id": "saved_version"}]
        self.assertTrue(_validate_video_delivery(request, studio))
        unattached = StudioAgentRequest(prompt="add SFX")
        recovered = _context_from_request(unattached)
        recovered.tool_events.append(event)
        self.assertTrue(_validate_video_delivery(unattached, recovered))
        event.result["status"] = "queued"
        self.assertFalse(_validate_video_delivery(unattached, recovered))

    def test_historical_mirelo_work_does_not_override_text_only_or_new_jobs(self):
        old = StudioToolEvent(id="old", name="Fal___get_video_task", label="Old Mirelo",
            summary="Previous run", status="succeeded", provider_job_id=ENDPOINT + ":old",
            arguments={"job_id": ENDPOINT + ":old"}, assets=[{"kind": "video", "version_id": "old_version"}],
            result={"model": ENDPOINT, "status": "succeeded", "downloaded": True})
        text = StudioAgentRequest(prompt="use ElevenLabs for a whoosh sound effect", prior_tool_events=[old.public()])
        self.assertTrue(_validate_video_delivery(text, _context_from_request(text)))
        preview = {**old.public(), "status": "dry_run", "result": {"model": ENDPOINT, "status": "dry_run"}}
        text.prior_tool_events = [preview]
        self.assertTrue(_validate_video_delivery(text, _context_from_request(text)))
        request = StudioAgentRequest(prompt="add foley from the video", prior_tool_events=[old.public()])
        studio = _context_from_request(request)
        studio.tool_events.append(StudioToolEvent(id="new", name=TOOL, label="New Mirelo",
            summary="Queued", status="queued", result={"model": ENDPOINT, "job_id": ENDPOINT + ":new"}))
        self.assertFalse(_validate_video_delivery(request, studio))
        poll = StudioToolEvent(id="poll", name="Fal___get_video_task", label="Poll Mirelo",
            summary="Saved", status="succeeded", arguments={"job_id": ENDPOINT + ":old"},
            assets=[{"kind": "video", "version_id": "new_version"}],
            result={"model": ENDPOINT, "status": "succeeded", "downloaded": True})
        studio.tool_events.append(poll)
        self.assertFalse(_validate_video_delivery(request, studio))
        poll.arguments["job_id"] = ENDPOINT + ":new"
        self.assertTrue(_validate_video_delivery(request, studio))
        continuation = StudioAgentRequest(prompt="finish Mirelo SFX", prior_tool_events=[old.public()])
        resumed = _context_from_request(continuation)
        resumed.tool_events.append(poll)
        self.assertTrue(_validate_video_delivery(continuation, resumed))

    def test_historical_assembly_cannot_satisfy_or_block_new_mirelo_delivery(self):
        render = StudioToolEvent(id="render", name="Remotion___render_timeline", label="Old assembly",
            summary="Previous run", status="queued", result={"job_id": "old_render"})
        finished = StudioToolEvent(id="finished", name="Remotion___get_render_progress", label="Old render",
            summary="Saved", status="succeeded", result={"status": "succeeded", "url": "https://example.com/old.mp4"})
        request = StudioAgentRequest(prompt="add foley from the video", prior_tool_events=[render.public(), finished.public()])
        studio = _context_from_request(request)
        studio.tool_events.append(StudioToolEvent(id="new", name=TOOL, label="New Mirelo",
            summary="Queued", status="queued", result={"job_id": ENDPOINT + ":new"}))
        self.assertFalse(_validate_video_delivery(request, studio))
        studio.tool_events.append(StudioToolEvent(id="poll", name="Fal___get_video_task", label="New result",
            summary="Saved", status="succeeded", arguments={"job_id": ENDPOINT + ":new"},
            assets=[{"kind": "video", "version_id": "new_version"}],
            result={"model": ENDPOINT, "status": "succeeded", "downloaded": True}))
        self.assertTrue(_validate_video_delivery(request, studio))

    def test_dry_run_or_failed_mirelo_cannot_be_reported_as_completed_media(self):
        from types import SimpleNamespace
        from server.studio import _media_generation_failed

        for status in ("dry_run", "failed"):
            outcome = SimpleNamespace(tool_events=[SimpleNamespace(name=TOOL, status=status)])
            self.assertTrue(_media_generation_failed(outcome, {"assets": []}))

    def test_price_disclosure_does_not_become_free_in_dry_run(self):
        with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
            self.assertEqual(cost_for("fal", "mirelo_v2a", ARGS).total_cents, 0)
            self.assertGreaterEqual(routing.estimate_cost(TOOL, ARGS).total_cents, 13)
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
            self.assertEqual(cost_for("fal", "mirelo_v2a", ARGS).provider_cents, 13)
        for autonomous in (True, False):
            self.assertTrue(tool_needs_approval(TOOL, autonomous))
        self.assertFalse(tool_needs_approval("Fal___get_video_task", True))

    def test_delivery_requires_saved_mirelo_result_and_preserves_assembly_requirement(self):
        for prompt in ("add foley from the video", "add SFX with Mirelo"):
            for model, status, downloaded, expected in [(ENDPOINT, "succeeded", True, True),
                ("fal-ai/wan-vace-14b", "succeeded", True, False),
                (ENDPOINT, "dry_run", False, False), (ENDPOINT, "succeeded", False, False)]:
                with self.subTest(prompt=prompt, model=model, status=status):
                    request = StudioAgentRequest(prompt=prompt)
                    studio = _context_from_request(request)
                    studio.tool_events.append(StudioToolEvent(id="poll", name="Fal___get_video_task",
                        label="Mirelo poll", summary="Saved result", status=status,
                        result={"model": model, "status": status, "downloaded": downloaded,
                                "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4")}))
                    self.assertEqual(_validate_video_delivery(request, studio), expected)
        request = StudioAgentRequest(prompt="add foley from the video and add captions")
        studio = _context_from_request(request)
        self.assertFalse(_validate_video_delivery(request, studio))


class MireloApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_studio_invoke_cannot_bypass_cost_approval(self):
        from fastapi import HTTPException
        from server import studio

        body = studio.InvokeBody(provider="fal", tool="mirelo_v2a", arguments=ARGS, project_id="untitled")
        with patch.object(studio.repository, "require_project"), patch.object(studio, "dispatch") as submit, patch.object(studio, "cost_for") as quote:
            with self.assertRaises(HTTPException) as denied:
                await studio.invoke_tool(body, None)
            self.assertEqual(denied.exception.status_code, 409)
            self.assertIn("approval", denied.exception.detail)
            submit.assert_not_called()
            quote.assert_not_called()

    async def test_manager_proposals_and_context_route_attached_video_to_mirelo(self):
        from agent.deep_agent.runner import run_with_servers
        from langchain_core.messages import HumanMessage, ToolMessage

        request = StudioAgentRequest(prompt="add SFX", nodes=[StudioNode(
            id="video", title="Silent clip", kind="video", version_id="version_123")])

        def observe(messages, tools):
            proposal = next(message.content for message in messages if isinstance(message, HumanMessage))
            self.assertIn(TOOL, proposal)
            context = next(json.loads(message.content) for message in messages
                           if isinstance(message, ToolMessage) and message.name == "read_studio_context")
            self.assertEqual(context["intent_route"]["tool"], TOOL)
            return final()

        model = ScriptedModel([call("read_studio_context", {}, "context"), observe])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
            await run_with_servers(request, _context_from_request(request), [Gateway()], model=model)

    async def test_approved_native_interrupt_dispatches_exact_quote_once(self):
        from agent.deep_agent.runner import run_with_servers

        schemas = json.loads(Path("configs/gateway/fal.tools.json").read_text())
        gateway = Gateway([Tool(name="Fal___" + t["name"], description=t["description"],
                               inputSchema=t["inputSchema"]) for t in schemas],
                          result={"status": "dry_run", "provider": "fal", "model": ENDPOINT})
        request = StudioAgentRequest(prompt="add foley from the video", autonomous=True, job_id="mirelo-approved")
        studio = _context_from_request(request)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory, "FAL_DRY_RUN": "true"}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/audio-bed/SKILL.md"}, "skill"),
                    call("call_media_tool", {"tool_name": TOOL, "arguments": ARGS}, "sfx")]))
            approval = paused.exception.approvals[0]
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=approval.call_id, decision="approve")]})
            await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_awaited_once_with(TOOL, ARGS)
            rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
            self.assertEqual((rows[-1]["provider"], rows[-1]["stage"], rows[-1]["outcome"]),
                             ("fal", "approval", "accepted"))

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
