from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agent.studio_agent_next import (StudioAgentOutput, StudioAgentRequest, StudioToolEvent,
                                    _context_from_request, _validate_video_delivery)


class MotionHostTests(unittest.TestCase):
    def request(self):
        return StudioAgentRequest(prompt="QC the motion graphics video before I review it",
                                  workspace_id="w", project_id="p", conversation_id="c", job_id="job")

    def event(self, context, result):
        context.record_event(StudioToolEvent(id="qc", name="Remotion___motion_carry_probe", label="Motion carry",
            status=result["status"], summary="Motion report", arguments={"job_id": "job", "input_path": "film.mp4"}, result=result))

    def final(self):
        return StudioAgentOutput(title="Finished film", summary="Ready for review", markdown="# Final", filename="film.md")

    def test_failing_report_is_surfaced_verbatim_before_final_with_rerender(self):
        request = self.request()
        context = _context_from_request(request)
        failures = ["carry at 1.000s: Nothing carries.", "no_rests: Add a hold at 2.000s."]
        self.event(context, {"status": "failed", "passed": False, "failures": failures})
        output = self.final()
        self.assertFalse(_validate_video_delivery(request, context, output))
        for failure in failures:
            self.assertIn(failure, output.markdown)
        self.assertIn("remotion_render", output.markdown)
        self.assertIn("re-render", output.markdown)
        self.assertEqual(output.title, "Motion carry QC failed")

    def test_missing_dry_run_skipped_and_forged_pass_are_incomplete(self):
        for status in (None, "dry_run", "skipped", "passed"):
            request = self.request()
            context = _context_from_request(request)
            if status:
                self.event(context, {"status": status, "passed": status == "passed", "reason": "Local dependency unavailable."})
            output = self.final()
            self.assertFalse(_validate_video_delivery(request, context, output))
            self.assertIn("incomplete", output.summary.lower())

    def test_generated_continuity_does_not_require_motion_report(self):
        request = self.request().model_copy(update={"prompt": "Check this AI-generated drone clip for continuity errors between shots"})
        context = _context_from_request(request)
        output = self.final()
        _validate_video_delivery(request, context, output)
        self.assertNotIn("Motion carry", output.title)

    def test_prior_motion_report_does_not_gate_a_new_continuity_request(self):
        request = self.request().model_copy(update={"prompt": "Check this AI-generated drone clip for continuity errors between shots"})
        context = _context_from_request(request)
        self.event(context, {"status": "failed", "passed": False, "failures": ["Prior film failed."]})
        request.prior_tool_events = [event.public() for event in context.tool_events]
        output = self.final()
        _validate_video_delivery(request, context, output)
        self.assertNotIn("Motion carry", output.title)

    def test_followup_export_preserves_motion_qc_requirement(self):
        request = self.request().model_copy(update={"prompt": "Export this as an MP4"})
        context = _context_from_request(request)
        context.record_event(StudioToolEvent(id="render", name="Remotion___render_timeline", label="Motion render",
            status="queued", summary="Rendered motion graphics", result={"motion_carry_required": True}))
        request.prior_tool_events = [event.public() for event in context.tool_events]
        output = self.final()
        self.assertFalse(_validate_video_delivery(request, context, output))
        self.assertIn("Motion carry QC incomplete", output.title)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
    def test_only_current_saved_pass_for_owned_delivered_artifact_can_clear_gate(self):
        from providers.remotion.motion_carry import motion_carry_probe

        fixtures = Path(__file__).parent / "fixtures" / "motion_carry"
        with tempfile.TemporaryDirectory() as root:
            job = Path(root) / "job"
            job.mkdir()
            shutil.copyfile(fixtures / "carrying.mp4", job / "film.mp4")
            timeline = json.loads((fixtures / "manifest.json").read_text())["films"][0]["timeline"]
            with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": root, "MOTION_CARRY_QC_DRY_RUN": "false"}):
                report = motion_carry_probe("job", "film.mp4", timeline)
                request = self.request()
                context = _context_from_request(request)
                context.record_event(StudioToolEvent(id="poll", name="Remotion___get_render_progress", label="Render",
                    status="succeeded", summary="MP4 exists", arguments={},
                    result={"status": "succeeded", "output_path": str(job / "film.mp4")}))
                self.event(context, report)
                self.assertTrue(_validate_video_delivery(request, context, self.final()))
                (job / "other.mp4").write_bytes(b"different output")
                context.tool_events[0].result["output_path"] = str(job / "other.mp4")
                self.assertFalse(_validate_video_delivery(request, context, self.final()))
                context.tool_events[0].result["output_path"] = str(job / "film.mp4")
                context.record_event(StudioToolEvent(id="new", name="Remotion___render_timeline", label="Render",
                    status="queued", summary="New render", arguments={}, result={"status": "queued"}))
                self.assertFalse(_validate_video_delivery(request, context, self.final()))
                context.tool_events.pop()
                for name, arguments in (("Remotion___render_ad_variants", {"stage": "render"}),
                                        ("Remotion___deliver_render", {}),
                                        ("Ffmpeg___ffmpeg_tool", {"op": "mux_aac"})):
                    with self.subTest(tool=name):
                        context.record_event(StudioToolEvent(id="new", name=name, label="Finishing",
                            status="succeeded", summary="New output", arguments=arguments, result={"status": "succeeded"}))
                        self.assertFalse(_validate_video_delivery(request, context, self.final()))
                        context.tool_events.pop()
                # Probing the old file after a finishing operation cannot certify the new file.
                context.tool_events.insert(1, StudioToolEvent(id="matrix", name="Remotion___render_ad_variants",
                    label="Matrix", status="succeeded", summary="New deliverable", arguments={"stage": "render_batch"},
                    result={"status": "succeeded", "rendered": [{"file": str(job / "other.mp4")}]}))
                self.assertFalse(_validate_video_delivery(request, context, self.final()))
                shutil.copyfile(fixtures / "carrying.mp4", job / "other.mp4")
                context.tool_events[-1].result = motion_carry_probe("job", "other.mp4", timeline)
                from agent.deep_agent.motion_carry_gate import gate_motion_delivery

                self.assertTrue(gate_motion_delivery(request, context, self.final()))
                # Motion metrics do not waive the matrix's separate delivery checks.
                self.assertFalse(_validate_video_delivery(request, context, self.final()))


class MotionDeepAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_failed_probe_survives_deepagents_and_prevents_final_delivery(self):
        from agent.deep_agent.runner import run_with_servers
        from test_deep_agent import ScriptedModel, call, final

        fixtures = Path(__file__).parent / "fixtures" / "motion_carry"
        timeline = json.loads((fixtures / "manifest.json").read_text())["films"][1]["timeline"]
        request = StudioAgentRequest(prompt="Check why my motion video feels like PowerPoint", job_id="job")
        context = _context_from_request(request)
        with tempfile.TemporaryDirectory() as root:
            job = Path(root)/"job"
            job.mkdir()
            shutil.copyfile(fixtures / "slideshow.mp4", job / "film.mp4")
            with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": root, "MOTION_CARRY_QC_DRY_RUN": "false"}):
                output = await run_with_servers(request, context, [], model=ScriptedModel([
                    call("call_editor_tool", {"tool_name": "Remotion___motion_carry_probe", "arguments": {
                        "job_id": "job", "input_path": "film.mp4", "timeline": timeline}}, "probe"), final()]))
                self.assertEqual(output.title, "Motion carry QC failed")
                report = context.tool_events[-1].result
                self.assertEqual(json.loads(Path(report["report_path"]).read_text()), report)
                self.assertTrue(all(failure in output.markdown for failure in report["failures"]))
                self.assertIn("remotion_render", output.markdown)

    async def test_owned_local_render_poll_stages_mp4_and_exact_timing_for_probe(self):
        from agent.gateway_executor import GatewayExecutor
        from test_deep_agent import Gateway
        from mcp import Tool

        render_id = "local-" + "a"*32
        request = StudioAgentRequest(prompt="Make motion graphics", job_id="job", autonomous=True)
        context = _context_from_request(request)
        context.record_event(StudioToolEvent(id="render", name="Remotion___render_timeline", label="Render",
            status="queued", summary="Owned render", result={"status": "queued", "render_id": render_id,
                                                             "bucket_name": "local", "output_key": ""}))
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/"remotion"/"local"/render_id/"film.mp4"
            source.parent.mkdir(parents=True)
            shutil.copyfile(Path(__file__).parent/"fixtures"/"motion_carry"/"carrying.mp4", source)
            gateway = Gateway([Tool(name="Remotion___get_render_progress", inputSchema={"type": "object"})])
            timeline = {"beats_s": [0, .9, 2.3, 3.4, 6]}
            gateway.call_tool.return_value = {"status": "succeeded", "backend": "local", "render_id": render_id,
                                              "output_path": str(source), "motion_carry_timeline": timeline}
            with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": root, "MOTION_CARRY_QC_DRY_RUN": "false"}):
                with patch('providers.registry.dispatch', return_value=gateway.call_tool.return_value):
                    result = await GatewayExecutor(context, [gateway]).execute({
                        "tool_name": "Remotion___get_render_progress", "arguments": {
                            "render_id": render_id, 'bucket_name': 'local'}, "call_id": "poll"})
                gateway.call_tool.assert_not_called()
                self.assertEqual(Path(result["output_path"]).parent, Path(root)/"job")
                self.assertEqual(Path(result["output_path"]).read_bytes(), source.read_bytes())
                self.assertEqual(result["motion_carry_timeline"], timeline)

    async def test_probe_is_discovered_and_runs_without_approval_in_real_deepagents(self):
        from agent.deep_agent.runner import run_with_servers
        from test_deep_agent import ScriptedModel, call, final

        request = StudioAgentRequest(prompt="Check why my render feels like PowerPoint", job_id="job",
                                    workspace_id="w", project_id="p", conversation_id="motion-dry")
        context = _context_from_request(request)
        with patch.dict(os.environ, {"MOTION_CARRY_QC_DRY_RUN": "true"}):
            output = await run_with_servers(request, context, [], model=ScriptedModel([
                call("call_editor_tool", {"tool_name": "Remotion___motion_carry_probe",
                                         "arguments": {"job_id": "job", "input_path": "film.mp4"}}, "probe"), final()]))
        self.assertEqual(context.tool_events[-1].result["status"], "dry_run")
        self.assertIn("incomplete", output.summary.lower())

    async def test_another_studio_job_cannot_be_probed(self):
        from agent.gateway_executor import GatewayExecutor

        request = StudioAgentRequest(prompt="motion carry QC", job_id="job", autonomous=True)
        executor = GatewayExecutor(_context_from_request(request), [])
        report = await executor.execute({"tool_name": "Remotion___motion_carry_probe", "call_id": "other",
                                         "arguments": {"job_id": "other", "input_path": "film.mp4"}})
        self.assertEqual(report["status"], "not_run")
        self.assertIn("Studio job", report["reason"])
