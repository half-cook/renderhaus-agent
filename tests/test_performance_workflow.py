from __future__ import annotations

import json
import os
import shutil
import subprocess
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
from test_performance_transfer import ACT, ACT_ARGS, MOTION, MOTION_ARGS


class PerformanceApproval(unittest.IsolatedAsyncioTestCase):
    async def test_direct_studio_invoke_cannot_bypass_consent_and_approval(self):
        from server import studio

        for provider, tool, args in [("runway", "act_two", ACT_ARGS), ("fal", "kling_motion_control", MOTION_ARGS)]:
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
        for name, args, prompt, expected_price in [(ACT, ACT_ARGS, "transfer my facial acting", "$0.33"),
            (MOTION, MOTION_ARGS, "copy my whole-body dance", "$1.09")]:
            for decision in ("approve", "reject"):
                with self.subTest(name=name, decision=decision), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                    {"RENDERHAUS_OUTCOME_DIR": directory, "RUNWAY_DRY_RUN": "true", "FAL_DRY_RUN": "true"}):
                    provider = "runway" if name == ACT else "fal"
                    schemas = json.loads(Path(f"configs/gateway/{provider}.tools.json").read_text())
                    gateway = Gateway([Tool(name=name.split("___")[0] + "___" + row["name"],
                        description=row["description"], inputSchema=row["inputSchema"]) for row in schemas],
                        result={"status": "dry_run", "provider": provider, "model": "act_two" if name == ACT else "fal-ai/kling-video/v3/pro/motion-control"})
                    request = StudioAgentRequest(prompt=prompt, autonomous=True, job_id=f"performance-{provider}-{decision}")
                    studio = _context_from_request(request)
                    with self.assertRaises(StudioAgentApprovalRequired) as paused:
                        await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                            call("read_file", {"file_path": "/skills/act-two/SKILL.md"}, "skill"),
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
        for name, args, prompt in [(ACT, ACT_ARGS, "transfer facial acting"), (MOTION, MOTION_ARGS, "copy whole-body dance")]:
            gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
            request = StudioAgentRequest(prompt=prompt, autonomous=True)
            executor = GatewayExecutor(_context_from_request(request), [gateway])
            result = await executor.execute({"tool_name": name, "arguments": {**args, "consent_confirmed": False}, "call_id": "no-consent"}, approved=True)
            self.assertEqual(result["status"], "not_run")
            gateway.call_tool.assert_not_awaited()

    async def test_long_take_permits_only_explicit_supported_source_segments(self):
        request = StudioAgentRequest(prompt="transfer facial acting from this 60 second video", autonomous=True)
        gateway = Gateway([Tool(name=ACT, inputSchema={"type": "object"})])
        executor = GatewayExecutor(_context_from_request(request), [gateway])
        segment = {**ACT_ARGS, "source_duration_seconds": 60, "performance_duration_seconds": 30,
                   "performance_start_seconds": 0, "boundary_kind": "shot"}
        route = executor.media_selection(ACT, segment)
        self.assertEqual(route.status, "ready")
        self.assertIsNone(executor.selection_blocker(ACT, segment, route))
        self.assertIn("Sequential", executor.dispatch_disclosure(ACT, segment, route))

    async def test_next_chunk_waits_for_previous_act_two_job(self):
        request = StudioAgentRequest(prompt="transfer facial acting", autonomous=True)
        studio = _context_from_request(request)
        gateway = Gateway([Tool(name=ACT, inputSchema={"type": "object"})])
        executor = GatewayExecutor(studio, [gateway])
        segment = {**ACT_ARGS, "source_duration_seconds": 60, "performance_duration_seconds": 30,
                   "performance_start_seconds": 30, "boundary_kind": "shot"}
        executor.media_jobs["previous"] = {"provider": "runway", "model": "act_two", "status": "running", "job_id": "previous"}
        result = await executor.execute({"tool_name": ACT, "arguments": segment, "call_id": "next"}, approved=True)
        self.assertEqual(result["status"], "not_run")
        gateway.call_tool.assert_not_awaited()
        executor.media_jobs["previous"]["status"] = "succeeded"
        self.assertIsNone(executor.selection_blocker(ACT, segment, executor.media_selection(ACT, segment)))


class PerformanceSegments(unittest.TestCase):
    def test_missing_chunk_dependencies_refuse_before_paid_submit(self):
        from providers.runway import api
        with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "false"}), patch("providers.runway.segments.shutil.which", return_value=None), patch.object(api, "_request") as paid:
            with self.assertRaisesRegex(ValueError, "ffmpeg"):
                api.act_two(**ACT_ARGS, source_duration_seconds=60, boundary_kind="silence")
            paid.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
    def test_real_source_is_split_and_existing_concat_preserves_order(self):
        from providers.runway import segments
        from providers.runway.performance import request_for
        from providers.sync.chunks import _measurement
        from server.projects import merge_video_paths
        from providers.remotion.api import build_timeline_props

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for color in ("red", "blue"):
                source = root / f"{color}.mp4"
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=96x64:r=24:d=20", "-c:v", "libx264", str(source)],
                    capture_output=True, check=True, timeout=30)
                sources.append(source)
            merge_video_paths(sources, output_path=root / "source.mp4")
            whole_seconds, _ = _measurement(root / "source.mp4", "video")
            self.assertGreater(whole_seconds, 30)
            request = request_for({**ACT_ARGS, "source_duration_seconds": whole_seconds,
                "performance_duration_seconds": 20, "boundary_kind": "shot"})
            first = segments.split_file(request, root / "source.mp4", root / "first.mp4")
            request = request.model_copy(update={"performance_start_seconds": 20})
            second = segments.split_file(request, root / "source.mp4", root / "second.mp4")
            self.assertAlmostEqual(_measurement(first, "video")[0], request.performance_duration_seconds, delta=0.1)
            merge_video_paths([first, second], output_path=root / "joined.mp4")
            self.assertAlmostEqual(_measurement(root / "joined.mp4", "video")[0], 2 * request.performance_duration_seconds, delta=0.15)
            for offset, expected_channel in [(1, 0), (21, 2)]:
                frame = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(offset),
                    "-i", str(root / "joined.mp4"), "-frames:v", "1", "-vf", "scale=1:1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                    capture_output=True, check=True, timeout=30).stdout
                self.assertGreater(frame[expected_channel], 200)
                self.assertLess(frame[2 if expected_channel == 0 else 0], 30)
            props = build_timeline_props("Performance", [
                {"output_path": str(path), "kind": "video", "duration_seconds": 20,
                 "start_seconds": index * 20, "source_in_seconds": 0, "transition": "cut"}
                for index, path in enumerate((first, second))], aspect_ratio="16:9", fps=24)
            self.assertEqual(props["renderConfig"]["durationInFrames"], 960)

    def test_prepared_segment_uses_runway_input_publisher_before_generation(self):
        from providers.runway import api, segments

        job = "12345678-1234-4234-8234-123456789abc"
        fixture = Path(__file__).parent / "fixtures/sync-video.mp4"
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {"RUNWAY_DRY_RUN": "false", "RENDERHAUS_MEDIA_DIR": directory}), \
                patch.object(segments.local, "_source", return_value=fixture), \
                patch.object(segments, "split_file", return_value=fixture), \
                patch("providers.runway.inputs.publish_file", return_value="runway://prepared-clip") as publish, \
                patch.object(api, "_request", return_value={"id": job}) as paid:
            result = api.act_two(**ACT_ARGS, source_duration_seconds=60, boundary_kind="shot")
            self.assertEqual(result["job_id"], job)
            publish.assert_called_once_with(fixture, "performance.mp4", "video/mp4")
            self.assertEqual(paid.call_args.args[2]["reference"]["uri"], "runway://prepared-clip")
            self.assertEqual(paid.call_count, 1)
