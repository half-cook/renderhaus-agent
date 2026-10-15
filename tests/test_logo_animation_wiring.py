from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class LogoRoutingTests(unittest.TestCase):
    def test_supplied_logo_routes_vector_then_render_sequentially(self):
        from agent.deep_agent.routing import route_intent

        prompts = [
            "Here's our logo PNG, give me a 2-second logo reveal sting for the start of our YouTube videos",
            "Animate our attached logo JPG as a splash screen",
            "Turn this PNG logo into an animated SVG loader",
            "Make a two-second reveal from our supplied logo screenshot",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "logo-animation")
                self.assertEqual([step.alias for step in route.steps], ["logo_vectorize", "remotion_render"])
                self.assertEqual(route.execution_groups, (("logo_vectorize",), ("remotion_render",)))
                self.assertEqual(route.required["template_name"], "logo-animation")
                self.assertTrue(route.required["approved_vector_required"])
                self.assertFalse({"wan3_t2v", "seedance25_t2v", "gpt_image25_edit"} & {step.alias for step in route.steps})

    def test_other_briefs_keep_their_existing_routes(self):
        from agent.deep_agent.routing import route_intent

        cases = [
            ("Make animated lower thirds for this interview", "motion-graphics"),
            ("Make a channel intro sting without a supplied logo", "motion-graphics"),
            ("Design me a new logo as an editable SVG", "image-gen"),
            ("Make an audiogram from this podcast clip with a waveform", "podcast-audiogram"),
        ]
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt).skill, expected)

    def test_logo_intent_forbids_image_and_video_generation(self):
        from agent.deep_agent.routing import request_tool_blocker

        prompt = "Animate our attached logo PNG as a reveal"
        for tool in ("OpenAI___edit_image", "Fal___generate_wan3_t2v", "Seedance___text_to_video"):
            self.assertIn("logo", request_tool_blocker(prompt, tool).lower())
        self.assertIsNone(request_tool_blocker(prompt, "Logo___logo_vectorize"))
        self.assertIsNone(request_tool_blocker(prompt, "Remotion___render_timeline"))


class LogoApprovalTests(unittest.TestCase):
    def test_only_vector_approval_interrupts_including_autonomous(self):
        from agent.deep_agent.routing import is_free_tool
        from agent.gateway_executor import APPROVAL_EXEMPT_TOOLS, tool_needs_approval
        from server.billing_rates import cost_for

        self.assertEqual(APPROVAL_EXEMPT_TOOLS, frozenset({"Remotion___export_nle_timeline"}))
        self.assertTrue(is_free_tool("Logo___logo_vectorize"))
        self.assertEqual(cost_for("logo_animation", "logo_vectorize", {}).total_cents, 0)
        for autonomous in (False, True):
            for op in ("vectorize", "audit", "choreograph", "final_frame", "easing", "continuity"):
                self.assertFalse(tool_needs_approval("Logo___logo_vectorize", autonomous, {"op": op}))
            self.assertTrue(tool_needs_approval("Logo___logo_vectorize", autonomous, {"op": "approve"}))

    def test_lambda_refuses_private_logo_processing(self):
        from lambdas.handler import handler

        with patch.dict(os.environ, {"RENDERHAUS_PROVIDER": "logo_animation"}):
            result = handler({"_tool_name": "logo_vectorize", "job_id": "private"}, None)
        self.assertIn("local", result["error"].lower())

    def test_local_discovery_uses_neutral_labels(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request

        request = StudioAgentRequest(prompt="Animate our logo PNG", job_id="logo-job")
        executor = GatewayExecutor(_context_from_request(request), [])
        registry = asyncio.run(executor.available())
        server, _ = registry["Logo___logo_vectorize"]
        self.assertIsNone(server)
        disclosure = executor.dispatch_disclosure("Logo___logo_vectorize", {"op": "approve"}, None)
        for forbidden in ("provider", "model", "fee", "$", "remotion", "pixel2motion"):
            self.assertNotIn(forbidden, disclosure.lower())

    def test_logo_calls_refuse_another_job_before_discovery(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request

        request = StudioAgentRequest(prompt="Animate our attached logo PNG", job_id="logo-job", autonomous=True)
        executor = GatewayExecutor(_context_from_request(request), [])
        result = asyncio.run(executor.execute({"tool_name": "Logo___logo_vectorize", "call_id": "scope",
            "arguments": {"op": "vectorize", "job_id": "another-job", "input_path": "logo.png", "params": {"rights_confirmed": True}}}))
        self.assertEqual(result["status"], "not_run")
        self.assertIn("trusted current Studio job", result["reason"])

    def test_logo_template_cannot_read_another_job_or_use_lambda(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request

        request = StudioAgentRequest(prompt="Animate our supplied logo PNG", job_id="logo-job")
        executor = GatewayExecutor(_context_from_request(request), [])
        template = {"name": "logo-animation", "logo_job_id": "other-job"}
        with patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "local"}):
            self.assertIn("trusted current Studio job", executor.selection_blocker(
                "Remotion___render_timeline", {"template": template}, None))
        template["logo_job_id"] = "logo-job"
        with patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "lambda"}):
            self.assertIn("local rendering", executor.selection_blocker(
                "Remotion___render_timeline", {"template": template}, None))


class LogoNativeApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_approve_resume_and_rejection_keep_authorization_out_of_arguments(self):
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import (StudioAgentApprovalRequired, StudioAgentRequest,
                                             StudioApprovalDecision, _context_from_request)
        from providers.logo_animation.api import _AUTHORIZATION
        from test_deep_agent import ScriptedModel, call, final

        digest = "a" * 64
        args = {"op": "approve", "job_id": "logo-job", "input_path": "logo-one/logo.svg",
                "params": {"sha256": digest, "rights_confirmed": True}}
        for decision in ("approve", "reject"):
            request = StudioAgentRequest(prompt="Approve this prepared logo vector", job_id="logo-job",
                workspace_id="w", project_id="p", conversation_id="logo-" + decision, autonomous=True)
            context = _context_from_request(request)
            authorizations = []

            def dispatch(provider, verb, arguments):
                authorizations.append(_AUTHORIZATION.get())
                self.assertEqual((provider, verb, arguments), ("logo_animation", "logo_vectorize", args))
                return {"status": "approved", "svg_sha256": digest}

            with patch("providers.registry.dispatch", side_effect=dispatch):
                with self.assertRaises(StudioAgentApprovalRequired) as caught:
                    await run_with_servers(request, context, [], model=ScriptedModel([
                        call("call_editor_tool", {"tool_name": "Logo___logo_vectorize", "arguments": args}, "logo-approve"), final()]))
                self.assertEqual(authorizations, [])
                approval = caught.exception.approvals[0]
                self.assertIn("exact SVG", approval.description)
                resumed = request.model_copy(update={"session_items": context.session_items,
                    "resume_state": caught.exception.state, "approval_decisions": [StudioApprovalDecision(
                        call_id=approval.call_id, decision=decision, message="Reviewed geometry")]})
                await run_with_servers(resumed, context, [], model=ScriptedModel([final()]))
                self.assertEqual(len(authorizations), int(decision == "approve"))
                if authorizations:
                    self.assertEqual(authorizations[0][0], digest)
                    self.assertTrue(authorizations[0][1].startswith("human:"))
                self.assertIsNone(_AUTHORIZATION.get())


class LogoCompletionTests(unittest.TestCase):
    def test_missing_and_failed_logo_qa_prevent_finished_claims(self):
        from agent.studio_agent_next import (StudioAgentOutput, StudioAgentRequest, StudioToolEvent,
                                             _context_from_request, _validate_video_delivery)

        for failures in ([], ["Final frame changed approved letterforms.", "Opacity jumps at 0.520s."]):
            request = StudioAgentRequest(prompt="Animate our attached logo PNG", job_id="logo-job")
            context = _context_from_request(request)
            if failures:
                context.record_event(StudioToolEvent(id="probe", name="Logo___logo_vectorize", label="Check logo",
                    status="failed", summary="Logo QA failed", arguments={"op": "final_frame", "job_id": "logo-job"},
                    result={"passed": False, "failures": failures}))
            output = StudioAgentOutput(title="Finished", summary="Ready", markdown="Done", filename="logo.md")
            self.assertFalse(_validate_video_delivery(request, context, output))
            for failure in failures:
                self.assertIn(failure, output.markdown)

    def test_saved_report_binds_output_vector_and_motion_spec_and_requires_delivery_qc(self):
        from agent.deep_agent.logo_gate import gate_logo_delivery
        from agent.studio_agent_next import (StudioAgentOutput, StudioAgentRequest, StudioToolEvent,
                                             _context_from_request, _validate_video_delivery)
        from providers.ffmpeg.sandbox import sha256_file
        from providers.logo_animation.api import authorize, logo_vectorize
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": root}):
            directory = Path(root) / "logo-job"
            directory.mkdir()
            image = Image.new("RGB", (96, 96), "white")
            ImageDraw.Draw(image).ellipse((16, 16, 80, 80), fill="black")
            image.save(directory / "source.png")
            vector = logo_vectorize("vectorize", "logo-job", "source.png")
            svg_path = vector["svg_path"]
            with authorize(vector["svg_sha256"], "human:review"):
                logo_vectorize("approve", "logo-job", svg_path,
                               {"sha256": vector["svg_sha256"], "rights_confirmed": True})
            motion = logo_vectorize("choreograph", "logo-job", svg_path)
            spec_hash = hashlib.sha256(json.dumps(motion["motion_spec"], sort_keys=True).encode()).hexdigest()
            output = directory / "sting.mp4"
            output.write_bytes(b"Synthetic artifact for checksum boundary validation")
            report = {"passed": True, "failures": [], "output_sha256": sha256_file(output),
                      "svg_sha256": vector["svg_sha256"], "motion_spec_sha256": spec_hash,
                      **{key: {"passed": True} for key in ("final_frame", "actual_motion", "continuity", "declared_easing")}}
            report_path = directory / "logo-qc.json"
            report_path.write_text(json.dumps(report))
            result = {**report, "report_path": "logo-qc.json", "outputs": [{"path": str(report_path), "sha256": sha256_file(report_path)}]}
            request = StudioAgentRequest(prompt="Animate our supplied logo PNG", job_id="logo-job")
            context = _context_from_request(request)
            context.record_event(StudioToolEvent(id="qa", name="Logo___logo_vectorize", label="Logo QA",
                status="succeeded", summary="Saved report", arguments={"op": "final_frame", "job_id": "logo-job",
                    "input_path": "sting.mp4", "params": {"svg_path": svg_path}}, result=result))
            self.assertTrue(gate_logo_delivery(request, context))
            final = StudioAgentOutput(title="Finished", summary="Ready", markdown="Done", filename="logo.md")
            self.assertFalse(_validate_video_delivery(request, context, final))
            self.assertIn("Delivery QC", final.title)
            output.write_bytes(b"Changed")
            self.assertFalse(gate_logo_delivery(request, context))
            output.write_bytes(b"Synthetic artifact for checksum boundary validation")
            spec_path = Path(root) / "logo-job" / Path(motion["motion_spec_path"]).with_suffix(".json")
            spec_path.write_text("{}")
            self.assertFalse(gate_logo_delivery(request, context))
