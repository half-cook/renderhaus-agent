from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Tool

from agent.deep_agent import routing
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final


I2V = "Fal___vidu_q4_i2v"
R2V = "Fal___vidu_q4_r2v"
I2V_MODEL = "fal-ai/vidu/q4/image-to-video"
R2V_MODEL = "fal-ai/vidu/q4/reference-to-video"
IMAGE = "https://example.test/product.png"
VOICE = "https://example.test/voice.mp3"


class ViduRoutingTests(unittest.TestCase):
    def test_named_requests_select_exact_model_and_variant(self):
        for prompt, tool, model in [
            ("animate this product still with Vidu Q4 native audio", I2V, I2V_MODEL),
            ("character locked multi-ref Vidu Q4 with voice clips", R2V, R2V_MODEL),
            ("cheapest Vidu Q4 preview 540p", I2V, I2V_MODEL),
            ("Vidu Q4 reference to video", R2V, R2V_MODEL),
        ]:
            with self.subTest(prompt=prompt):
                route = routing.route_intent(prompt)
                self.assertEqual((route.skill, route.tool, route.model, route.status),
                                 ("named-provider", tool, model, "ready"))
                self.assertIn("Estimated cost $", route.disclosure)
                self.assertIn("explicit request; not the default", route.disclosure)
        self.assertEqual(routing.route_intent("Wan 2.2 VACE first last frame morph").tool, "Fal___image_to_video")
        self.assertEqual(routing.route_intent("animate an image").tool, "Fal___generate_wan3_i2v")

    def test_paid_video_approval_and_fixed_identity(self):
        for name, model in [(I2V, I2V_MODEL), (R2V, R2V_MODEL)]:
            self.assertEqual(routing.job_type(name), "i2v" if name == I2V else "reference_video")
            self.assertFalse(routing.is_free_tool(name))
            self.assertTrue(routing.premium_video(name))
            self.assertTrue(tool_needs_approval(name, autonomous=False))
            self.assertTrue(tool_needs_approval(name, autonomous=True))
            self.assertEqual(routing.effective_model("fal", name.split("___")[1], {}), model)
            self.assertIsNone(routing.policy_blocker(name, {}, region="US"))
            self.assertIsNone(routing.policy_blocker(name, {}, region="CA"))
        self.assertNotIn("premium_targets", routing.POLICY)

    def test_capabilities_and_billing_derived_prices(self):
        rows = [r for r in routing.capability_table() if r["model"] in {I2V_MODEL, R2V_MODEL}]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertNotIn("tiers", row)
            self.assertTrue(row["explicit_only"])
            self.assertEqual(row["jobs"]["max_resolution"], 2160)
            self.assertTrue(row["jobs"]["i2v"])
            self.assertTrue(row["jobs"]["native_audio"])
            self.assertFalse(row["training_eligible"])
            self.assertEqual(row["license"], "service-terms")
            for feature in ("t2v", "v2v_edit", "start_end_frame", "multi_shot", "lipsync", "upscale", "image"):
                self.assertFalse(row["jobs"][feature], feature)
            self.assertTrue(row["price"]["rates"])
        ref = next(r for r in rows if r["model"] == R2V_MODEL)
        self.assertTrue(ref["jobs"]["voice_references"])
        self.assertTrue(ref["jobs"]["reference_elements"])
        image = next(r for r in rows if r["model"] == I2V_MODEL)
        self.assertFalse(image["jobs"]["voice_references"])
        self.assertFalse(image["jobs"]["reference_elements"])

    def test_native_duration_resolution_and_voice_filters(self):
        route = routing.select_provider("i2v", model=R2V_MODEL, provider="fal",
            arguments={"duration": 16, "resolution": "4K", "audio": True,
                       "reference_image_urls": [IMAGE], "reference_audio_urls": [VOICE]})
        self.assertEqual(route.tool, R2V)
        self.assertIsNotNone(route.estimated_cost["total_cents"])
        for args in [{"duration": 17}, {"duration": 2}, {"resolution": "580p"}]:
            self.assertEqual(routing.select_provider("i2v", provider="fal", model=I2V_MODEL,
                                                    arguments=args).status, "blocked")
        route = routing.select_provider("i2v", required={"voice_references": True})
        self.assertEqual(route.status, "blocked")
        self.assertIsNone(route.tool)

    def test_confidential_metadata_does_not_change_explicit_q4_selection(self):
        for confidential in (False, True):
            route = routing.select_provider("i2v", provider="fal", model=I2V_MODEL,
                                            confidential=confidential)
            self.assertEqual(route.tool, I2V)
            self.assertEqual(route.model, I2V_MODEL)
        self.assertEqual(routing.route_intent("confidential Vidu Q4 video").tool, I2V)

    def test_training_retry_stays_on_wan_and_preserves_required_features(self):
        route = routing.select_provider("i2v", provider="fal", model=I2V_MODEL, retry=True)
        self.assertEqual(route.tool, "Fal___image_to_video")
        self.assertNotIn("vidu", route.model)
        self.assertEqual(routing.select_provider("i2v", required={"native_audio": True},
                                                retry=True).status, "blocked")

    def test_q4_provenance_never_enters_training(self):
        from agent.deep_agent.outcomes import OutcomeStore
        from agent.deep_agent.continuity_qc import training_loop_hook

        for model in (I2V_MODEL, R2V_MODEL):
            asset = {"provider": "fal", "model": model, "status": "succeeded",
                     "training_eligible": True, "weights_license": "Apache-2.0", "version_id": "owned"}
            self.assertFalse(routing.training_eligible(asset))
            with self.assertRaises(ValueError):
                training_loop_hook([asset], lambda _: self.fail("Training consumer called"))
            with tempfile.TemporaryDirectory() as directory:
                row = OutcomeStore(Path(directory)).record(event_id="q4", provider="fal", model=model,
                    job_type="i2v", outcome="accepted", stage="review", asset=asset)
                self.assertFalse(row["training_eligible"])


class ViduGraphTests(unittest.IsolatedAsyncioTestCase):
    def gateway(self):
        return Gateway([Tool(name="Fal___" + t["name"], description=t["description"],
                             inputSchema=t["inputSchema"])
                        for t in json.loads(Path("configs/gateway/fal.tools.json").read_text())],
                       {"status": "dry_run", "provider": "fal", "model": I2V_MODEL,
                        "training_eligible": False, "job_id": I2V_MODEL + ":dry_fake"})

    async def test_native_interrupt_quote_approve_and_reject_in_fresh_worker(self):
        from agent.deep_agent.runner import run_with_servers

        for verdict in ("approve", "reject"):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"RENDERHAUS_OUTCOME_DIR": directory, "FAL_DRY_RUN": "true"}
            ):
                request = StudioAgentRequest(prompt="animate product still with Vidu Q4 native audio",
                    workspace_id="w", project_id="p", conversation_id=verdict, job_id=verdict)
                studio, gateway = _context_from_request(request), self.gateway()
                args = {"image_url": IMAGE, "prompt": "A talking product", "duration": 5}
                with self.assertRaises(StudioAgentApprovalRequired) as paused:
                    await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                        call("read_file", {"file_path": "/skills/named-provider/SKILL.md"}, "skill"),
                        call("call_media_tool", {"tool_name": I2V, "arguments": args}, "q4")]))
                approval = paused.exception.approvals[0]
                self.assertEqual(approval.tool_name, I2V)
                self.assertIn("Estimated cost $", approval.description)
                self.assertIn("platform fee", approval.description)
                self.assertTrue(any(I2V_MODEL in event.message for event in studio.progress_events))
                gateway.call_tool.assert_not_awaited()
                resumed = request.model_copy(update={"session_items": studio.session_items,
                    "resume_state": paused.exception.state,
                    "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=verdict)]})
                await run_with_servers(resumed, _context_from_request(resumed), [gateway],
                                       model=ScriptedModel([final()]))
                if verdict == "approve":
                    gateway.call_tool.assert_awaited_once_with(I2V, args)
                else:
                    gateway.call_tool.assert_not_awaited()
                rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
                self.assertEqual(rows[-1]["model"], I2V_MODEL)
                self.assertFalse(rows[-1]["training_eligible"])

    async def test_native_audio_references_and_duration_cannot_be_weakened(self):
        request = StudioAgentRequest(prompt="Vidu Q4 multi-ref with voice clips native audio 16 seconds at 4K",
                                     autonomous=True, job_id="native")
        executor = GatewayExecutor(_context_from_request(request), [self.gateway()])
        args = {"prompt": "[@reference_image_1] speaks in [reference_audio_1]",
                "reference_image_urls": [IMAGE], "reference_audio_urls": [VOICE],
                "duration": 16, "resolution": "4K", "audio": True}
        route = executor.media_selection(R2V, args)
        self.assertEqual(route.tool, R2V)
        self.assertIsNone(executor.selection_blocker(R2V, args, route))
        for changed in ({"audio": False}, {"duration": 5}, {"reference_image_urls": []},
                        {"reference_audio_urls": []}, {"resolution": "720p"}):
            self.assertIsNotNone(executor.selection_blocker(R2V, {**args, **changed}, route))

    async def test_preapproved_unnamed_q4_cannot_bypass_capability_default(self):
        for confidential in (False, True):
            with self.subTest(confidential=confidential):
                gateway = self.gateway()
                studio = _context_from_request(StudioAgentRequest(
                    prompt="animate image", confidential=confidential,
                    autonomous=True, job_id="project",
                ))
                result = await GatewayExecutor(studio, [gateway]).execute({"tool_name": I2V,
                    "arguments": {"image_url": IMAGE}, "call_id": "bypass"}, approved=True)
                self.assertEqual(result["status"], "not_run")
                self.assertIn("Capability map selected", result["reason"])
                gateway.call_tool.assert_not_awaited()
