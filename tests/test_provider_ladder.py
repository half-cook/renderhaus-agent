from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent import routing
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final


class CapabilityMapTests(unittest.TestCase):
    def test_defaults_are_opinionated_and_tiers_do_not_select(self):
        expected = {"t2v": "wan3_t2v", "i2v": "wan3_i2v", "reference_video": "wan3_r2v",
                    "v2v_edit": "seedance25_edit", "extend": "seedance25_extend", "still_image": "gpt_image25_t2i",
                    "image_edit": "gpt_image25_edit", "lipsync": "sync3_lipsync",
                    "performance_transfer": "runway_act_two", "tts": "eleven_v4_turbo",
                    "voice_clone": "voices_ivc_create", "cloned_tts": "eleven_v4_turbo",
                    "music": "mureka_v95", "sfx": "mirelo_v2a",
                    "upscale": "topaz_upscale", "interpolate": "topaz_interpolate",
                    "motion_graphics": "remotion_render", "nle_handoff": "Remotion___export_nle_timeline",
                    "nle_import": "nle_import",
                    "continuity_qc": "local_qc", "motion_carry_qc": "motion_carry_probe", "lyrics_video": "mureka_lyrics_video",
                    "ad_variant_matrix": "ad_variant_matrix", "media_inspection": "ffmpeg_tool",
                    "delivery_render": "delivery_render", "deliverable_qc": "deliverable_qc",
                    "loudness_qc": "ffmpeg_tool"}
        self.assertEqual({k: v["default"] for k, v in routing.POLICY["capability_map"].items()}, expected)
        self.assertNotIn("ladder", routing.POLICY)
        for capability in ["v2v_edit", "extend"]:
            self.assertNotIn("interim", routing.POLICY["capability_map"][capability])
        for tier in [None, "draft", "standard", "premium"]:
            route = routing.select_provider("t2v", tier=tier)
            self.assertEqual(route.tool, "Fal___generate_wan3_t2v")
            self.assertEqual(route.alias, "wan3_t2v")
            self.assertNotIn("interim default until", route.disclosure)

    def test_wan_edit_and_extend_are_explicit_only_and_absent_from_automatic_choices(self):
        wan_aliases = {"wan3_edit", "wan3_extend"}
        for choice in routing.POLICY["capability_map"].values():
            automatic = {choice["default"], choice.get("interim"), *choice["ab_candidates"],
                         *(exception["tool"] for exception in choice["exceptions"])}
            self.assertFalse(wan_aliases & automatic)
        for alias in wan_aliases:
            self.assertTrue(routing.TOOL_MAP[alias]["explicit_only"])
            self.assertEqual(routing.TOOL_MAP[alias]["status"], "ready")
        policy = routing.POLICY["providers"]["alibaba_modelstudio"]
        self.assertTrue(policy["enabled"])
        self.assertTrue(policy["explicit_only"])
        self.assertTrue(policy["model_policies"]["wan3.0-video"]["explicit_only"])
        capability = next(row for row in routing.capability_table() if row["provider"] == "alibaba_modelstudio")
        self.assertTrue(capability["enabled"])
        self.assertTrue(capability["explicit_only"])

    def test_plain_video_never_automatically_chooses_demoted_providers(self):
        for prompt in ["generate a video", "cheapest video preview", "highest quality video", "draft video"]:
            route = routing.route_intent(prompt)
            self.assertEqual(route.provider, "fal")
        for required in [{"max_resolution": 2160}]:
            route = routing.select_provider("i2v", required=required)
            self.assertEqual(route.status, "blocked")
            self.assertIsNone(route.tool)

    def test_explicit_request_precedes_exception_and_discloses_demotion(self):
        for provider, target in [("Kling", "Kling"), ("Runway", "Runway"), ("Luma", "Luma")]:
            route = routing.route_intent(f'use {provider} for a robot that says "hello"')
            self.assertEqual(route.tool, f"{target}___text_to_video")
            self.assertIn("explicit request; not the default for t2v", route.disclosure)
        self.assertEqual(routing.route_intent("use Runway Aleph to relight this clip").tool, "Runway___video_to_video")

    def test_predicates_are_deterministic_and_negation_is_respected(self):
        cases = [('robot says "hello"', "dialogue"), ("cartoons talking", "dialogue"),
                 ("my CEO photo attached with consent", "real_face_refs"), ("editable SVG logo", "vector_output"),
                 ("fix the typo in this banner", "text_only_edit"), ("whole-body dance", "full_body_motion"),
                 ("transfer facial acting", "facial_performance"), ("2 minute presenter", "duration_over_30s")]
        for prompt, key in cases:
            with self.subTest(prompt=prompt):
                self.assertTrue(routing.intent_constraints(prompt)["predicates"][key])
        self.assertFalse(routing.intent_constraints("synthetic character refs, no dialogue")["predicates"]["dialogue"])
        self.assertFalse(routing.intent_constraints("cartoon mascot image speaking")["predicates"]["real_face_refs"])

    def test_exception_routes_and_pending_specialists(self):
        cases = [('robot says "hello"', "seedance25_t2v"),
                 ('animate a mascot image speaking "hi"', "seedance25_i2v"),
                 ("synthetic characters from refs talking", "seedance25_r2v"),
                 ("editable SVG logo", "recraft_v41_vector"), ("fix the typo in this banner", "ideogram45_edit"),
                 ("90 second multilingual avatar presenter", "heygen_avatar_v"),
                 ("copy whole-body dance", "kling_motion_control"), ("whoosh sound effect", "elevenlabs_sfx_v2")]
        for prompt, alias in cases:
            with self.subTest(prompt=prompt):
                route = routing.route_intent(prompt)
                self.assertEqual(route.alias, alias)
                self.assertIn("exception:", route.disclosure)
        self.assertEqual(routing.route_intent("generate an Ideogram poster").alias, "gpt_image25_t2i")
        self.assertEqual(routing.route_intent("convert 24fps to 60fps simple pan").alias, "topaz_interpolate")

    def test_real_face_refs_never_fall_back_to_seedance_or_omni(self):
        for prompt in ['my CEO photo attached says "hello"', 'use Seedance with my CEO photo saying "hi"']:
            route = routing.route_intent(prompt)
            self.assertEqual(route.alias, "wan3_i2v")
            self.assertEqual(route.status, "ready")
            self.assertEqual(route.tool, "Fal___generate_wan3_i2v")
        self.assertEqual(routing.select_provider("i2v", provider="seedance", arguments={"real_face_refs": True}).tool, "Fal___generate_wan3_i2v")

    def test_pending_default_only_uses_declared_interim(self):
        self.assertEqual(routing.select_provider("image").status, "ready")
        self.assertEqual(routing.select_provider("image").tool, "OpenAI___generate_image")
        self.assertEqual(routing.select_provider("v2v_edit").tool, "Seedance___edit_video")
        self.assertEqual(routing.select_provider("reference_video").tool, "Fal___generate_wan3_r2v")
        self.assertEqual(routing.select_provider("lipsync").status, "ready")
        self.assertEqual(routing.select_provider("t2v", available_tools={"Kling___text_to_video"}).status, "blocked")
        self.assertEqual(routing.select_provider("t2v").tool, "Fal___generate_wan3_t2v")

    def test_pending_seedance_default_has_no_interim_and_generic_interims_still_work(self):
        with patch.dict(routing.TOOL_MAP["seedance25_edit"], {
            "status": "pending", "reason": "provider pending: unavailable Seedance adapter",
        }):
            route = routing.select_provider("v2v_edit")
            self.assertEqual((route.status, route.alias, route.tool), ("pending", "seedance25_edit", None))
            self.assertIsNone(routing.resolve_alias("seedance25_edit"))
        self.assertIsNone(routing.job_type("Unknown___future_generation"))
        with patch.dict(routing.POLICY["capability_map"]["t2v"], {"interim": "wan_t2v"}), patch.dict(
            routing.TOOL_MAP["wan3_t2v"], {"status": "pending"},
        ):
            route = routing.select_provider("t2v")
            self.assertEqual((route.status, route.alias, route.tool),
                             ("ready", "wan3_t2v", "Fal___text_to_video"))
            self.assertIn("interim default until wan3_t2v", route.disclosure)
            self.assertEqual(routing.resolve_alias("wan3_t2v"), "Fal___text_to_video")

    def test_long_generation_refuses_with_split_reason(self):
        route = routing.route_intent("generate a 45 second single shot")
        self.assertEqual(route.status, "blocked")
        self.assertIn("split", route.reason)


    def test_project_confidential_flag_has_no_routing_effect(self):
        for prompt in ["make a video", "use Runway for a video", 'mascot says "hi"',
                       "generate a still image", "edit this image", "lipsync this footage",
                       "narrate", "generate music", "add sound effects", "upscale clip",
                       "interpolate frames", "transfer facial acting", "clone my voice"]:
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.route_intent(prompt, confidential=True).public(),
                                 routing.route_intent(prompt, confidential=False).public())
        self.assertNotIn("project_policy", routing.POLICY)
        self.assertNotIn("flux2_klein4b_t2i", routing.TOOL_MAP)
        self.assertNotIn("confidential-route", routing.POLICY["pending_skills"])

    def test_every_paid_video_pauses_in_autonomous_runs(self):
        from agent.gateway_executor import tool_needs_approval
        for name in routing.POLICY["paid_video_tools"]:
            self.assertTrue(tool_needs_approval(name, autonomous=True), name)
        self.assertFalse(tool_needs_approval("Remotion___export_nle_timeline", autonomous=True))
        self.assertFalse(tool_needs_approval("ElevenLabs___text_to_sound_effects_convert", autonomous=True))

    def test_retired_aliases_cannot_dispatch(self):
        for alias in ["veo_t2v", "hedra_character3", "liveportrait_lipsync", "mmaudio_sfx", "ace_step_music"]:
            self.assertEqual(routing.TOOL_MAP[alias]["status"], "retired")
            self.assertIsNone(routing.resolve_alias(alias))


class OutcomeTests(unittest.TestCase):
    def test_studio_preserves_wan_eligibility_and_restricted_source_lineage(self):
        import server.studio as studio
        from server.studio_state import StudioRepository
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "clip.mp4"
            media.write_bytes(b"offline fixture")
            repo = StudioRepository(root / "state.sqlite3", root / "media")
            repo.create_project("workspace", "local", "Review", project_id="project")
            restricted = repo.register_file(workspace_id="workspace", project_id="project", user_id="local",
                                            path=media, training_eligible=False)
            payload = {"provider": "fal", "model": "fal-ai/wan-vace-14b", "status": "succeeded",
                       "training_eligible": True, "weights_license": "Apache-2.0", "output_path": str(media)}
            with patch.object(studio, "repository", repo), patch.object(studio, "_resolved_media_file", return_value=media):
                owned = studio._register_payload_assets(payload=payload, workspace_id="workspace", project_id="project", user_id="local")
                derived = studio._register_payload_assets(payload=payload, workspace_id="workspace", project_id="project", user_id="local",
                                                         source_version_ids=[restricted.version_id])
            self.assertTrue(owned[0]["training_eligible"])
            self.assertFalse(derived[0]["training_eligible"])
            self.assertFalse(studio._payload_training_eligibility({**payload, "provider": "kling"}))
            with patch.object(studio, "repository", repo), patch.object(studio, "_resolved_media_file", return_value=media):
                for provider, result in [("seedance", {"provider": "byteplus-seedance"}), ("seedream", {})]:
                    owned = studio._register_payload_assets(payload={"output_path": str(media), **result}, provider=provider,
                        workspace_id="workspace", project_id="project", user_id="local")
                    self.assertFalse(owned[0]["training_eligible"])

    def test_duplicate_receipt_is_idempotent(self):
        from agent.deep_agent.outcomes import OutcomeStore
        with tempfile.TemporaryDirectory() as directory:
            store = OutcomeStore(Path(directory))
            args = dict(event_id="review-1", provider="fal", model="fal-ai/wan-vace-14b",
                        job_type="t2v", outcome="accepted", stage="review")
            self.assertEqual(store.record(**args), store.record(**args))
            self.assertEqual(len(store.path.read_text().splitlines()), 1)

    def test_append_only_review_rows_and_wan_only_training(self):
        from agent.deep_agent.outcomes import OutcomeStore
        with tempfile.TemporaryDirectory() as directory:
            store = OutcomeStore(Path(directory))
            for provider in ["fal", "kling", "runway", "seedance", "seedream", "luma"]:
                asset = {"provider": provider, "model": "fal-ai/wan-vace-14b", "weights_license": "Apache-2.0",
                         "training_eligible": True, "status": "succeeded", "version_id": "owned-version",
                         "url": "https://secret/?token=private"}
                store.record(event_id=provider, provider=provider, model=asset["model"], job_type="t2v",
                             provider_job_id="job-" + provider, outcome="accepted", stage="review", asset=asset)
            before = store.path.read_text()
            store.record(event_id="new", provider="fal", model="fal-ai/wan-vace-14b", job_type="i2v",
                         provider_job_id="second", outcome="rejected", stage="review")
            self.assertTrue(store.path.read_text().startswith(before))
            rows = [json.loads(line) for line in store.path.read_text().splitlines()]
            self.assertEqual(len(rows), 7)
            self.assertEqual({r["provider"] for r in rows if r["training_eligible"]}, {"fal"})
            self.assertNotIn("private", store.path.read_text())
            self.assertNotIn("url", store.path.read_text())
            self.assertEqual(rows[-1]["job_type"], "i2v")

    def test_dry_run_and_approval_are_never_training(self):
        from agent.deep_agent.outcomes import OutcomeStore
        asset = {"provider": "fal", "model": "fal-ai/wan-vace-14b", "weights_license": "Apache-2.0",
                 "training_eligible": True, "status": "succeeded", "dry_run": True}
        with tempfile.TemporaryDirectory() as directory:
            store = OutcomeStore(Path(directory))
            row = store.record(event_id="dry", provider="fal", model=asset["model"], job_type="t2v",
                               outcome="accepted", stage="review", asset=asset)
            self.assertFalse(row["training_eligible"])
            row = store.record(event_id="approval", provider="fal", model=asset["model"], job_type="t2v",
                               outcome="accepted", stage="approval", asset={**asset, "dry_run": False})
            self.assertFalse(row["training_eligible"])


class LadderGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_registers_original_generation_source_lineage(self):
        from agent.gateway_executor import GatewayExecutor
        from mcp import Tool
        from unittest.mock import Mock
        request = StudioAgentRequest(prompt="Wan video", autonomous=True, job_id="lineage")
        studio = _context_from_request(request)
        studio.asset_registrar = Mock(return_value=[])
        saved = {"media_jobs": {"generate": {"provider": "fal", "model": "fal-ai/wan-vace-14b", "job_type": "v2v_edit",
            "provider_job_id": "saved", "status": "queued", "required": {}, "asset": {},
            "arguments": {"video_url": "renderhaus-asset://restricted-version"}}}}
        gateway = Gateway([Tool(name="Fal___get_video_task", inputSchema={"type": "object"})],
                          {"status": "succeeded", "job_id": "saved", "video_url": "https://example.invalid/offline"})
        executor = GatewayExecutor(studio, [gateway], saved)
        await executor.execute({"tool_name": "Fal___get_video_task", "arguments": {"job_id": "saved"}, "call_id": "poll"})
        self.assertEqual(studio.asset_registrar.call_args.kwargs["source_version_ids"], ["restricted-version"])

    async def test_local_studio_runner_keeps_host_provider_context(self):
        import server.studio as studio
        from server.studio_state import StudioRepository
        from agent.studio_agent_next import StudioAgentOutput
        from test_deep_agent import FINAL
        from unittest.mock import AsyncMock

        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / "state.sqlite3", Path(directory) / "media")
            repo.create_project("workspace", "local", "Private", project_id="private",
                                provider_policy={"confidential": True, "quality_tier": "premium"})
            runtime = AsyncMock(return_value=StudioAgentOutput.model_validate(FINAL))
            with patch.object(studio, "repository", repo), patch.object(studio, "run_studio_agent_runtime", runtime), patch.dict(os.environ, {"AGENTCORE_DEV_URL": ""}):
                await studio.run_studio_agent("Runway video", workspace_id="workspace", project_id="private")
            context = runtime.await_args.kwargs["studio"]
            self.assertTrue(context.confidential)
            self.assertEqual((context.quality_tier, context.prompt), ("premium", "Runway video"))

    async def test_required_audio_cannot_be_silently_disabled(self):
        from agent.gateway_executor import GatewayExecutor
        from mcp import Tool
        request = StudioAgentRequest(prompt="Seedance video with native audio", autonomous=True, job_id="audio")
        studio = _context_from_request(request)
        gateway = Gateway([Tool(name="Seedance___text_to_video", inputSchema={"type": "object"})])
        result = await GatewayExecutor(studio, [gateway]).execute({"tool_name": "Seedance___text_to_video",
            "arguments": {"prompt": "Dialogue", "generate_audio": False}, "call_id": "silent"}, approved=True)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("native_audio", result["reason"])
        gateway.call_tool.assert_not_awaited()

    async def test_review_attribution_polling_and_retry_survive_restart(self):
        from agent.gateway_executor import GatewayExecutor
        from mcp import Tool
        request = StudioAgentRequest(prompt="Seedance video", autonomous=True, job_id="review", workspace_id="local")
        studio = _context_from_request(request)
        gateway = Gateway([Tool(name="Seedance___text_to_video", inputSchema={"type": "object"}),
                           Tool(name="Seedance___get_video_task", inputSchema={"type": "object"})],
                          {"status": "queued", "job_id": "saved"})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
            executor = GatewayExecutor(studio, [gateway])
            await executor.execute({"tool_name": "Seedance___text_to_video", "arguments": {"prompt": "Shot"}, "call_id": "generate"}, approved=True)
            self.assertEqual(executor.record_outcome("generate", "accepted")["status"], "not_run")
            gateway.call_tool.return_value = {"status": "succeeded", "job_id": "saved", "training_eligible": True,
                                              "weights_license": "Apache-2.0"}
            await executor.execute({"tool_name": "Seedance___get_video_task", "arguments": {"job_id": "saved"}, "call_id": "poll"})
            studio.prompt = "reject the Seedance video"
            result = executor.record_outcome("generate", "rejected")
            self.assertEqual(result["retry_route"]["tool"], "Fal___text_to_video")
            restarted = GatewayExecutor(_context_from_request(request.model_copy(update={"prompt": "retry the rejected shot"})), [gateway], executor.snapshot())
            self.assertEqual(restarted.media_selection("Seedance___text_to_video", {"prompt": "Retry"}).tool, "Fal___text_to_video")
            self.assertFalse(result["outcome"]["training_eligible"])
            rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
            self.assertEqual(rows[-1]["provider_job_id"], "saved")
            self.assertEqual(rows[-1]["provider"], "seedance")
            self.assertNotIn("weights_license", rows[-1])

    async def test_retry_keeps_rejected_job_requirements_and_does_not_rearm(self):
        from agent.gateway_executor import GatewayExecutor
        request = StudioAgentRequest(prompt="retry the rejected shot", autonomous=True, job_id="retry")
        studio = _context_from_request(request)
        saved = {"media_jobs": {"old": {"provider": "seedance", "model": "seedance-1-5-pro-251215",
            "job_type": "t2v", "status": "succeeded", "arguments": {}, "asset": {},
            "required": {"native_audio": True}}}, "rejected_reviews": {"t2v": "old"}}
        executor = GatewayExecutor(studio, [Gateway()], saved)
        route = executor.media_selection("Fal___text_to_video", {"prompt": "Speaking person"})
        self.assertEqual(route.status, "blocked")
        self.assertTrue(route.required["native_audio"])

    async def test_review_without_customer_verdict_cannot_emit_training(self):
        from agent.gateway_executor import GatewayExecutor
        request = StudioAgentRequest(prompt="make a video", job_id="review")
        saved = {"media_jobs": {"old": {"provider": "fal", "model": "fal-ai/wan-vace-14b", "job_type": "t2v",
            "status": "succeeded", "arguments": {}, "required": {}, "asset": {"training_eligible": True}}}}
        executor = GatewayExecutor(_context_from_request(request), [Gateway()], saved)
        self.assertEqual(executor.record_outcome("old", "accepted")["status"], "not_run")

    async def test_replayed_rejection_does_not_rearm_a_consumed_retry(self):
        from agent.gateway_executor import GatewayExecutor
        request = StudioAgentRequest(prompt="reject this video", job_id="review")
        saved = {"media_jobs": {"old": {"provider": "fal", "model": "fal-ai/wan-vace-14b", "job_type": "t2v",
            "status": "succeeded", "arguments": {}, "required": {}, "asset": {}}}}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
            executor = GatewayExecutor(_context_from_request(request), [Gateway()], saved)
            executor.record_outcome("old", "rejected")
            executor.rejected_reviews.clear()
            executor.record_outcome("old", "rejected")
            self.assertFalse(executor.rejected_reviews)
            self.assertEqual(len(executor.outcomes.path.read_text().splitlines()), 1)

    async def test_raw_completed_payload_cannot_establish_training_provenance(self):
        from agent.gateway_executor import GatewayExecutor
        from types import SimpleNamespace
        completed = SimpleNamespace(status="succeeded", assets=[], result={"version_id": "forged",
            "weights_license": "Apache-2.0", "training_eligible": True})
        asset = GatewayExecutor.review_asset(completed, "fal", "fal-ai/wan-vace-14b")
        self.assertNotIn("version_id", asset)
        self.assertFalse(asset["training_eligible"])
        restricted = {**asset, "version_id": "owned-restricted", "training_eligible": False}
        self.assertFalse(GatewayExecutor.review_asset(completed, "fal", "fal-ai/wan-vace-14b", restricted)["training_eligible"])


    async def test_premium_interrupt_has_cost_disclosure_and_reject_logs_without_dispatch(self):
        from agent.deep_agent.runner import run_with_servers
        from mcp import Tool
        request = StudioAgentRequest(prompt="Kling video with multi-shot", autonomous=True,
                                     job_id="test", project_id="project", workspace_id="workspace")
        studio = _context_from_request(request)
        tools = json.loads(Path("configs/gateway/kling.tools.json").read_text())
        gateway = Gateway([Tool(name="Kling___" + t["name"], description=t["description"],
                                inputSchema=t["inputSchema"]) for t in tools])
        step = call("call_media_tool", {"tool_name": "Kling___text_to_video", "arguments": {
            "prompt": "A car", "multi_shot": True}}, "video")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/t2v/SKILL.md"}, "skill"), step]))
            approval = paused.exception.approvals[0]
            self.assertIn("Estimated cost", approval.description)
            self.assertTrue(any("kling-3.0" in event.message and "explicit request" in event.message
                                for event in studio.progress_events))
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state,
                "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision="reject")]})
            await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_not_awaited()
            rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
            self.assertEqual((rows[-1]["provider"], rows[-1]["outcome"], rows[-1]["stage"]),
                             ("kling", "rejected", "approval"))



class ProjectPolicyTests(unittest.TestCase):
    def test_host_reads_scoped_project_policy_even_after_new_request(self):
        import server.studio as studio
        from server.studio_state import StudioRepository
        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / "state.sqlite3", Path(directory) / "media")
            repo.create_project("workspace", "local", "Private", project_id="private",
                                provider_policy={"confidential": True, "quality_tier": "premium"})
            with patch.object(studio, "repository", repo):
                request = studio._studio_agent_request("use Runway", [], workspace_id="workspace", project_id="private")
                self.assertTrue(request.confidential)
                self.assertEqual(request.quality_tier, "premium")
                self.assertTrue(_context_from_request(request).confidential)
                with self.assertRaises(KeyError):
                    studio._studio_agent_request("video", [], workspace_id="other", project_id="private")
                self.assertEqual(routing.route_intent(request.prompt + " video", confidential=request.confidential).provider, "runway")
            restored = StudioRepository(repo.database_path, repo.media_root)
            self.assertTrue(restored.project_provider_policy("workspace", "private")["confidential"])

    def test_invalid_tier_is_rejected_at_request_boundary(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            StudioAgentRequest(prompt="video", quality_tier="free")
