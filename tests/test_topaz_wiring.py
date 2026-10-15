from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mcp import Tool

from agent.deep_agent import routing
from agent.deep_agent.runner import SESSION_TYPE, run_with_servers
from agent.deep_agent.finishing_preview import FinishingPreviewGate
from agent.session_scope import conversation_scope
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

    def test_route_quote_preserves_valid_fps_multiplier(self):
        args = {**ARGS, "source_width": 1920, "source_height": 1080, "fps_multiplier": 2.0}
        route = routing.route_intent("interpolate this clip to 60fps", arguments=args)
        self.assertEqual(route.status, "ready")
        self.assertEqual(route.estimated_cost["total_cents"], routing.estimate_cost(INTERPOLATE, args).total_cents)
        self.assertEqual(route.estimated_cost["total_cents"], 39)

    def test_route_quote_uses_actual_output_instead_of_rewriting_intent(self):
        args = {**ARGS, "source_width": 1920, "source_height": 1080}
        route = routing.route_intent("upscale this clip to 1080p", arguments=args)
        self.assertEqual(route.estimated_cost["total_cents"], routing.estimate_cost(UPSCALE, args).total_cents)
        self.assertEqual(route.estimated_cost["total_cents"], 338)
        route = routing.route_intent("interpolate this clip to 120fps", arguments=args)
        self.assertEqual(route.estimated_cost["total_cents"], routing.estimate_cost(INTERPOLATE, args).total_cents)

    def test_native_scale_and_fps_controls_cannot_weaken_selected_route(self):
        executor = object.__new__(GatewayExecutor)
        executor.studio = SimpleNamespace(prompt="upscale to 4K deliverable")
        executor.finishing_previews = SimpleNamespace(blocker=lambda *_: None)
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


def approved_finishing_fixture(request, args, directory, *, approve=True):
    root = Path(directory)
    paths = {"original": root / "original.mp4"}
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c=red:s={args['source_width']}x{args['source_height']}:r=30:d=10",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    str(paths["original"])], check=True)

    def register(**kwargs):
        version = f"version-{len(paths)}"
        target = root / f"{version}.mp4"
        shutil.copyfile(kwargs["result"]["output_path"], target)
        paths[version] = target
        return [{"version_id": version, "kind": "video"}]

    studio = _context_from_request(request, source_resolver=lambda version: str(paths[version]),
                                   asset_registrar=register)
    studio.add_assets([{"version_id": "original", "kind": "video"}])
    gate = FinishingPreviewGate(studio, scope=conversation_scope(request))
    prepared = gate.prepare(UPSCALE, {**args, "video_url": "renderhaus-asset://original"})
    if not prepared["ok"]:
        raise AssertionError(prepared)
    gate.claim_submission(UPSCALE, prepared["preview_arguments"], "preview")
    gate.record_submission(UPSCALE, prepared["preview_arguments"], "preview",
                           {"status": "queued", "job_id": "topaz:upscale:fixture"})
    clip = paths[prepared["source_clip_version_id"]]
    processed = root / "processed.mp4"
    from providers.topaz.contracts import request_for

    output = request_for("upscale_video", prepared["preview_arguments"])
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip), "-vf",
                    f"scale={output.output_width}:{output.output_height}", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(processed)], check=True)
    result = {"status": "succeeded", "downloaded": True, "job_id": "topaz:upscale:fixture",
              "output_path": str(processed)}
    assets = register(result=result)
    studio.add_assets(assets)
    event = StudioToolEvent(id="fixture-poll", name="Topaz___get_video_task", label="Status",
        summary="Saved", status="succeeded", provider_job_id=result["job_id"],
        arguments={"job_id": result["job_id"], "download": True}, result=result, assets=assets)
    studio.tool_events.append(event)
    gate.observe(event)
    if approve and gate.approve(prepared["preview_id"])["status"] != "approved":
        raise AssertionError(gate.snapshot())
    session = {"type": SESSION_TYPE, "version": 1, "scope": conversation_scope(request),
               "finishing_previews": gate.snapshot(), "working_assets": studio.working_assets}
    request.session_items.append(session)
    studio.session_items = list(request.session_items)
    return studio, prepared["full_arguments"]


class TopazApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_dispatch_cannot_bypass_preview_review(self):
        request = StudioAgentRequest(prompt="upscale this clip", job_id="topaz-bypass")
        studio = _context_from_request(request)
        tools = json.loads(Path("configs/gateway/topaz.tools.json").read_text())
        gateway = Gateway([Tool(name="Topaz___" + t["name"], description=t["description"],
                               inputSchema=t["inputSchema"]) for t in tools],
                          result={"status": "dry_run"})
        executor = GatewayExecutor(studio, [gateway])
        result = await executor.execute({"tool_name": UPSCALE, "arguments": ARGS,
                                         "call_id": "bypass"}, approved=True)
        self.assertEqual(result["status"], "not_run")
        gateway.call_tool.assert_not_awaited()

    async def test_native_preparation_uses_measured_clip_and_preserves_preview_cost_interrupt(self):
        request = StudioAgentRequest(prompt="upscale this 10 second clip", autonomous=True,
                                     job_id="native-preview")
        tools = json.loads(Path("configs/gateway/topaz.tools.json").read_text())
        gateway = Gateway([Tool(name="Topaz___" + t["name"], description=t["description"],
                               inputSchema=t["inputSchema"]) for t in tools],
                          result={"status": "queued", "job_id": "topaz:upscale:native-preview"})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_MEDIA_DIR": directory + "/media",
                "RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            studio, args = approved_finishing_fixture(request, ARGS, directory)
            request.session_items.clear()
            studio.session_items.clear()
            studio.tool_events.clear()
            prepared = {}

            def submit_preview(messages, available):
                self.assertIn("prepare_finishing_preview", available)
                prepared.update(json.loads(messages[-1].content))
                self.assertTrue(prepared["ok"], prepared)
                return call("call_media_tool", {"tool_name": UPSCALE,
                    "arguments": prepared["preview_arguments"]}, "preview-submit")

            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/upscale/SKILL.md"}, "skill"),
                    call("prepare_finishing_preview", {"tool_name": UPSCALE, "arguments": args}, "prepare"),
                    submit_preview]))
            approval = paused.exception.approvals[0]
            self.assertEqual(approval.tool_name, UPSCALE)
            self.assertLessEqual(approval.arguments["source_duration_seconds"], 3)
            self.assertNotEqual(approval.arguments["video_url"], args["video_url"])
            self.assertGreater(approval.estimated_cost["total_cents"], 0)
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=approval.call_id, decision="approve")]})
            resumed_studio = _context_from_request(resumed, source_resolver=studio.source_resolver,
                                                   asset_registrar=studio.asset_registrar)
            await run_with_servers(resumed, resumed_studio, [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_awaited_once_with(UPSCALE, prepared["preview_arguments"])

    async def test_native_review_has_host_comparison_and_rejection_blocks_full_job(self):
        request = StudioAgentRequest(prompt="upscale this clip", autonomous=True, job_id="native-reject")
        gateway = Gateway()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_MEDIA_DIR": directory + "/media"}):
            studio, args = approved_finishing_fixture(request, ARGS, directory, approve=False)
            record = next(iter(request.session_items[0]["finishing_previews"]["previews"].values()))
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("review_finishing_preview", {"preview_id": record["preview_id"],
                        "comparison": {"before_version_id": "invented"}}, "review")]))
            approval = paused.exception.approvals[0]
            self.assertEqual(approval.tool_name, "review_finishing_preview")
            self.assertEqual(approval.estimated_cost["total_cents"], 0)
            self.assertIsNone(approval.provider)
            self.assertEqual(approval.arguments["comparison"]["before_version_id"], record["source_clip_version_id"])
            self.assertEqual(approval.arguments["comparison"]["after_version_id"], record["output_version_id"])
            self.assertFalse(approval.arguments["comparison"]["covers_full_source"])
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=approval.call_id, decision="reject")]})
            resumed_studio = _context_from_request(resumed, source_resolver=studio.source_resolver,
                                                   asset_registrar=studio.asset_registrar)
            await run_with_servers(resumed, resumed_studio, [gateway], model=ScriptedModel([
                call("call_media_tool", {"tool_name": UPSCALE, "arguments": args}, "blocked-full"), final()]))
            gate = resumed_studio.session_items[0]["finishing_previews"]["previews"][record["preview_id"]]
            self.assertEqual(gate["status"], "rejected")
            gateway.call_tool.assert_not_awaited()

    async def test_native_review_approval_requires_a_separate_full_cost_approval(self):
        request = StudioAgentRequest(prompt="upscale this clip", autonomous=True, job_id="native-accept")
        tools = json.loads(Path("configs/gateway/topaz.tools.json").read_text())
        gateway = Gateway([Tool(name="Topaz___" + t["name"], description=t["description"],
                               inputSchema=t["inputSchema"]) for t in tools], result={"status": "dry_run"})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_MEDIA_DIR": directory + "/media"}):
            studio, args = approved_finishing_fixture(request, ARGS, directory, approve=False)
            preview_id = next(iter(request.session_items[0]["finishing_previews"]["previews"]))
            with self.assertRaises(StudioAgentApprovalRequired) as reviewed:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("review_finishing_preview", {"preview_id": preview_id}, "review")]))
            review = reviewed.exception.approvals[0]
            resume_review = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": reviewed.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=review.call_id, decision="approve")]})
            approved_studio = _context_from_request(resume_review, source_resolver=studio.source_resolver,
                                                    asset_registrar=studio.asset_registrar)
            with self.assertRaises(StudioAgentApprovalRequired) as full:
                await run_with_servers(resume_review, approved_studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/upscale/SKILL.md"}, "skill"),
                    call("call_media_tool", {"tool_name": UPSCALE, "arguments": args}, "full")]))
            full_approval = full.exception.approvals[0]
            self.assertEqual(full_approval.tool_name, UPSCALE)
            self.assertEqual(full_approval.arguments, args)
            self.assertGreater(full_approval.estimated_cost["total_cents"], 0)
            gateway.call_tool.assert_not_awaited()
            resume_full = resume_review.model_copy(update={"session_items": approved_studio.session_items,
                "resume_state": full.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=full_approval.call_id, decision="approve")]})
            await run_with_servers(resume_full, _context_from_request(resume_full,
                source_resolver=studio.source_resolver, asset_registrar=studio.asset_registrar),
                [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_awaited_once_with(UPSCALE, args)

    async def test_review_resume_rechecks_the_actual_saved_result(self):
        request = StudioAgentRequest(prompt="upscale this clip", autonomous=True, job_id="native-changed")
        gateway = Gateway()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_MEDIA_DIR": directory + "/media"}):
            studio, _ = approved_finishing_fixture(request, ARGS, directory, approve=False)
            record = next(iter(request.session_items[0]["finishing_previews"]["previews"].values()))
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("review_finishing_preview", {"preview_id": record["preview_id"]}, "review")]))
            path = Path(studio.source_resolver(record["output_version_id"]))
            path.write_bytes(path.read_bytes() + b"changed")
            approval = paused.exception.approvals[0]
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=approval.call_id, decision="approve")]})
            with self.assertRaisesRegex(ValueError, "changed"):
                await run_with_servers(resumed, _context_from_request(resumed,
                    source_resolver=studio.source_resolver, asset_registrar=studio.asset_registrar),
                    [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_not_awaited()

    async def test_concurrent_full_replays_leave_one_paid_request_and_one_reservation(self):
        request = StudioAgentRequest(prompt="upscale this clip", autonomous=True, job_id="concurrent-finish")
        tools = json.loads(Path("configs/gateway/topaz.tools.json").read_text())
        gateway = Gateway([Tool(name="Topaz___" + t["name"], description=t["description"],
                               inputSchema=t["inputSchema"]) for t in tools],
                          result={"status": "queued", "job_id": "topaz:upscale:concurrent-full"})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_MEDIA_DIR": directory + "/media",
                "RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "160"}):
            studio, args = approved_finishing_fixture(request, ARGS, directory)
            studio.run_meter = SimpleNamespace(check_step=lambda cents: None)
            executor = GatewayExecutor(studio, [gateway], request.session_items[0],
                                       finishing_scope=conversation_scope(request))
            await asyncio.gather(*(executor.execute({"tool_name": UPSCALE, "arguments": args,
                "call_id": call_id}, approved=True) for call_id in ("full-a", "full-b")))
            gateway.call_tool.assert_awaited_once_with(UPSCALE, args)
            self.assertEqual(len(executor.reservations), 1)
            self.assertEqual(sum(executor.reservations.values()), 156)
            self.assertFalse(executor.cap_stopped)

    async def test_manual_studio_invoke_cannot_bypass_finishing_approval(self):
        from fastapi import HTTPException
        from server import studio as studio_api

        for verb in ("upscale_video", "interpolate_video"):
            body = studio_api.InvokeBody(provider="topaz", tool=verb, arguments=ARGS, project_id="untitled")
            with patch.object(studio_api.repository, "require_project"), \
                    patch.object(studio_api, "dispatch") as dispatch, patch.object(studio_api, "cost_for") as quote:
                with self.assertRaises(HTTPException) as denied:
                    await studio_api.invoke_tool(body, None)
                self.assertEqual(denied.exception.status_code, 409)
                self.assertIn("approval", denied.exception.detail)
                dispatch.assert_not_called()
                quote.assert_not_called()

    async def test_approved_native_interrupt_dispatches_exact_quoted_request_once(self):
        args = {**ARGS, "source_width": 1920, "source_height": 1080}
        request = StudioAgentRequest(prompt="upscale this clip to 1080p", autonomous=True, job_id="topaz-approved")
        tools = json.loads(Path("configs/gateway/topaz.tools.json").read_text())
        gateway = Gateway([Tool(name="Topaz___" + t["name"], description=t["description"],
                               inputSchema=t["inputSchema"]) for t in tools], result={
                                   "status": "dry_run", "provider": "topaz", "model": "Starlight Precise 2.6"})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_MEDIA_DIR": directory + "/media"}):
            studio, args = approved_finishing_fixture(request, args, directory)
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/upscale/SKILL.md"}, "skill"),
                    call("call_media_tool", {"tool_name": UPSCALE, "arguments": args}, "finish-video")]))
            approval = paused.exception.approvals[0]
            self.assertIn("$3.38", approval.description)
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=approval.call_id, decision="approve")]})
            await run_with_servers(resumed, _context_from_request(resumed, source_resolver=studio.source_resolver,
                asset_registrar=studio.asset_registrar), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_awaited_once_with(UPSCALE, args)
            rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
            self.assertEqual((rows[-1]["provider"], rows[-1]["stage"], rows[-1]["outcome"]),
                             ("topaz", "approval", "accepted"))

    async def test_native_interrupt_has_cost_and_rejection_never_submits(self):
        request = StudioAgentRequest(prompt="upscale this clip", autonomous=True, job_id="topaz-approval")
        tools = json.loads(Path("configs/gateway/topaz.tools.json").read_text())
        gateway = Gateway([Tool(name="Topaz___" + t["name"], description=t["description"],
                           inputSchema=t["inputSchema"]) for t in tools])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "RENDERHAUS_MEDIA_DIR": directory + "/media"}):
            studio, args = approved_finishing_fixture(request, ARGS, directory)
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/upscale/SKILL.md"}, "skill"),
                    call("call_media_tool", {"tool_name": UPSCALE, "arguments": args}, "finish-video")]))
            approval = paused.exception.approvals[0]
            self.assertIn("$1.56", approval.description)
            self.assertTrue(any("Starlight Precise 2.6" in e.message and "default" in e.message
                                for e in studio.progress_events))
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state, "approval_decisions": [
                StudioApprovalDecision(call_id=approval.call_id, decision="reject")]})
            await run_with_servers(resumed, _context_from_request(resumed, source_resolver=studio.source_resolver,
                asset_registrar=studio.asset_registrar), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_not_awaited()
            rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
            self.assertEqual((rows[-1]["provider"], rows[-1]["stage"], rows[-1]["outcome"]),
                             ("topaz", "approval", "rejected"))


if __name__ == "__main__":
    unittest.main()
