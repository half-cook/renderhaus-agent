from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mcp import Tool

from agent.deep_agent import routing
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision,
    StudioToolEvent, _context_from_request, _validate_video_delivery,
)
from server.billing_rates import cost_for
from test_deep_agent import Gateway, ScriptedModel, call, final


ARGS = {"video_url": "https://example.test/source.mp4", "source_duration_seconds": 10.0,
        "source_fps": 30.0, "source_width": 960, "source_height": 540}
UPSCALE = "Topaz___upscale_video"
INTERPOLATE = "Topaz___interpolate_video"


class TopazWiringTests(unittest.TestCase):
    def test_defaults_are_ready_for_all_projects_and_price_tiers(self):
        for confidential in (False, True):
            for tier in (None, "draft", "premium"):
                for prompt, name, model in [("upscale to 1080p deliverable", UPSCALE, "Starlight Precise 2.6"),
                                           ("smooth this blurry fast-motion clip to 60fps", INTERPOLATE, "Apollo")]:
                    route = routing.route_intent(prompt, confidential=confidential, tier=tier)
                    self.assertEqual((route.status, route.tool, route.model), ("ready", name, model))
                    self.assertEqual(route.dispatch_tool, "call_media_tool")

    def test_chronos_exception_changes_actual_model_and_explicit_apollo_wins(self):
        for prompt, model in [("convert 24fps to 60fps simple pan", "Chronos"),
                              ("use Topaz to interpolate simple linear motion", "Chronos"),
                              ("use Apollo to interpolate simple linear motion", "Apollo"),
                              ("use Chronos to interpolate blurry motion", "Chronos")]:
            route = routing.route_intent(prompt)
            self.assertEqual((route.tool, route.model), (INTERPOLATE, model))
        route = routing.route_intent("interpolate simple linear motion", arguments={**ARGS, "model": "Apollo"})
        self.assertEqual(route.model, "Apollo")
        self.assertIn("explicit", route.basis)
        self.assertIn("exception", routing.route_intent("interpolate simple linear motion").basis)

    def test_retired_models_and_unavailable_tools_do_not_fall_back(self):
        for model in ("SeedVR2", "RIFE"):
            self.assertEqual(routing.route_intent(f"use {model} to upscale").status, "retired")
        self.assertEqual(routing.route_intent("upscale this clip", available_tools=set()).status, "blocked")

    def test_finishing_always_pauses_even_when_autonomous_and_switch_is_off(self):
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            for name in (UPSCALE, INTERPOLATE, "topaz_upscale", "topaz_interpolate"):
                for autonomous in (False, True):
                    self.assertTrue(tool_needs_approval(name, autonomous))
        self.assertFalse(tool_needs_approval("Topaz___get_video_task", True))
        self.assertEqual(cost_for("topaz", "get_video_task", {}).total_cents, 0)

    def test_published_estimates_survive_dry_run_zero_billing(self):
        with patch.dict(os.environ, {"TOPAZ_DRY_RUN": "true", "FAL_DRY_RUN": "true"}):
            for list_price in (False, True):
                self.assertEqual(routing.estimate_cost(UPSCALE, ARGS, list_price=list_price).total_cents, 156)
            self.assertEqual(cost_for("topaz", "upscale_video", ARGS).total_cents, 0)
        with patch.dict(os.environ, {"TOPAZ_DRY_RUN": "false", "FAL_DRY_RUN": "false"}):
            self.assertEqual(cost_for("topaz", "upscale_video", ARGS).provider_cents, 120)
            four_k = {**ARGS, "source_width": 1920, "source_height": 1080}
            self.assertEqual(cost_for("topaz", "upscale_video", four_k).provider_cents, 260)
            self.assertEqual(cost_for("topaz", "upscale_video", {**four_k, "target_fps": 60}).provider_cents, 510)
            self.assertEqual(cost_for("topaz", "interpolate_video", {**ARGS, "source_width": 1920,
                             "source_height": 1080}).provider_cents, 30)
            self.assertEqual(cost_for("topaz", "interpolate_video", {**ARGS, "source_width": 3840,
                             "source_height": 2160, "model": "Chronos"}).provider_cents, 60)

    def test_unknown_quotes_remain_unknown_and_no_metadata_is_invented(self):
        for args in ({}, {**ARGS, "source_fps": 24.0}, {**ARGS, "source_width": 1280, "source_height": 720}):
            self.assertIsNone(routing.estimate_cost(UPSCALE, args).total_cents)
        self.assertIsNone(routing.estimate_cost(INTERPOLATE, {**ARGS, "slowdown_factor": 2}).total_cents)

    def test_native_scale_and_fps_controls_cannot_weaken_selected_route(self):
        executor = object.__new__(GatewayExecutor)
        executor.studio = SimpleNamespace(prompt="upscale to 4K deliverable")
        route = routing.route_intent(executor.studio.prompt, arguments=ARGS)
        self.assertIsNotNone(executor.selection_blocker(UPSCALE, ARGS, route))
        self.assertIsNone(executor.selection_blocker(UPSCALE, {**ARGS, "target_resolution": "4K"}, route))
        executor.studio.prompt = "convert 30fps to 60fps simple pan"
        route = routing.route_intent(executor.studio.prompt, arguments=ARGS)
        self.assertIsNotNone(executor.selection_blocker(INTERPOLATE, ARGS, route))
        self.assertIsNone(executor.selection_blocker(INTERPOLATE, {**ARGS, "model": "Chronos"}, route))
        self.assertIsNotNone(executor.selection_blocker(INTERPOLATE, {**ARGS, "model": "Chronos", "target_fps": 45}, route))

    def test_training_is_blocked_for_every_finishing_model(self):
        for model in ("Starlight Precise 2.6", "Apollo", "Chronos"):
            self.assertFalse(routing.training_eligible({"provider": "topaz", "model": model,
                "status": "succeeded", "weights_license": "Apache-2.0", "training_eligible": True}))

    def test_policy_and_static_studio_choices_use_verified_models(self):
        from server.studio_options import static_field_options

        for alias, name in [("topaz_upscale", UPSCALE), ("topaz_interpolate", INTERPOLATE)]:
            self.assertEqual(routing.resolve_alias(alias), name)
            self.assertFalse(routing.POLICY["tools"][alias]["training_eligible"])
        options = static_field_options()["topaz"]
        self.assertIn("Apollo", options["model"])
        self.assertIn("Chronos", options["model"])

    def test_only_saved_finished_mp4_satisfies_standalone_delivery(self):
        for status, downloaded, assembly, expected in [("succeeded", True, False, True),
                ("queued", False, False, False), ("dry_run", False, False, False),
                ("succeeded", True, True, False)]:
            request = StudioAgentRequest(prompt="upscale this video MP4" + (" with captions" if assembly else ""))
            studio = _context_from_request(request)
            studio.tool_events.append(StudioToolEvent(id="topaz-poll", name="Topaz___get_video_task",
                label="Topaz poll", summary="Finish", status=status, result={"status": status,
                "downloaded": downloaded, "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4")}))
            self.assertEqual(_validate_video_delivery(request, studio), expected)


class TopazApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_interrupt_has_cost_and_rejection_never_submits(self):
        request = StudioAgentRequest(prompt="upscale this clip", autonomous=True, job_id="topaz-approval")
        studio = _context_from_request(request)
        tools = json.loads(Path("configs/gateway/topaz.tools.json").read_text())
        gateway = Gateway([Tool(name="Topaz___" + t["name"], description=t["description"],
                           inputSchema=t["inputSchema"]) for t in tools])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/upscale/SKILL.md"}, "skill"),
                    call("call_media_tool", {"tool_name": UPSCALE, "arguments": ARGS}, "finish-video")]))
            approval = paused.exception.approvals[0]
            self.assertIn("$1.56", approval.description)
            self.assertTrue(any("Starlight Precise 2.6" in e.message and "default" in e.message
                                for e in studio.progress_events))
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state, "approval_decisions": [
                StudioApprovalDecision(call_id=approval.call_id, decision="reject")]})
            await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_not_awaited()
            rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
            self.assertEqual((rows[-1]["provider"], rows[-1]["stage"], rows[-1]["outcome"]),
                             ("topaz", "approval", "rejected"))


if __name__ == "__main__":
    unittest.main()
