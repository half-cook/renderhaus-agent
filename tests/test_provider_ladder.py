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


class LadderTests(unittest.TestCase):
    def select(self, job="t2v", **kwargs):
        return routing.select_provider(job, **kwargs)

    def test_finished_shots_default_to_standard_cheapest_known(self):
        route = self.select(arguments={"duration_seconds": 5, "resolution": "720p"})
        self.assertEqual((route.tier, route.tool), ("standard", "Seedance___text_to_video"))

    def test_capabilities_filter_before_tier_and_cost(self):
        self.assertEqual(self.select(required={"native_audio": True}).tool, "Seedance___text_to_video")
        self.assertEqual(self.select(required={"multi_shot": True}).tool, "Kling___text_to_video")
        self.assertEqual(self.select("i2v", required={"start_end_frame": True}).tool, "Kling___image_to_video")
        self.assertEqual(self.select(required={"max_resolution": 2160}).tool, "Kling___text_to_video")
        blocked = self.select(tier="draft", required={"native_audio": True})
        self.assertEqual(blocked.status, "blocked")
        self.assertIsNone(blocked.tool)
        self.assertEqual(self.select(provider="luma", arguments={"duration_seconds": 7}).status, "blocked")
        self.assertEqual(self.select(tier="draft", required={"duration_seconds": 60}).status, "blocked")

    def test_tiers_and_pending_premium(self):
        self.assertEqual(self.select(tier="draft").tool, "Fal___text_to_video")
        self.assertEqual(self.select(tier="premium").tool, "Kling___text_to_video")
        self.assertEqual(self.select(provider="veo").status, "blocked")

    def test_explicit_provider_wins_only_when_capable_and_allowed(self):
        self.assertEqual(self.select(provider="runway").tool, "Runway___text_to_video")
        self.assertEqual(self.select(provider="seedance", required={"start_end_frame": True}).status, "blocked")
        self.assertEqual(self.select(provider="runway", required={"max_resolution": 1080}).status, "blocked")
        with patch.dict(routing.POLICY["providers"]["kling"], {"allowed_regions": ["CA"]}):
            self.assertEqual(self.select(provider="kling", region="US").status, "blocked")

    def test_unknown_sorts_after_known_without_changing_dry_run_flags(self):
        with patch.dict(os.environ, {"KLING_DRY_RUN": "true"}):
            route = self.select(provider="kling")
            self.assertEqual(route.model, "kling-3.0")
            self.assertEqual(os.environ["KLING_DRY_RUN"], "true")
        route = self.select(provider="kling", model="kling-3.0-turbo")
        self.assertIsNone(route.estimated_cost["total_cents"])
        self.assertIn("unknown", route.disclosure.lower())

    def test_list_quotes_keep_billing_validation(self):
        for name, args in [
            ("Runway___video_to_video", {}),
            ("Luma___modify_video", {}),
            ("Kling___text_to_video", {"duration_seconds": 2}),
            ("Runway___text_to_video", {"duration_seconds": 99}),
        ]:
            with self.subTest(name=name, args=args):
                self.assertIsNone(routing.estimate_cost(name, args).total_cents)
                self.assertIsNone(routing.estimate_cost(name, args, list_price=True).total_cents)

    def test_resolution_domain_and_minimum_are_priced_at_supported_presets(self):
        self.assertEqual(self.select(provider="seedance", arguments={"resolution": "580p"}).status, "blocked")
        route = self.select(provider="seedance", required={"max_resolution": 580})
        self.assertEqual(route.estimated_cost["total_cents"],
                         routing.estimate_cost(route.tool, {"resolution": "720p"}, list_price=True).total_cents)
        image = self.select("image", provider="runway", required={"max_resolution": 1024})
        self.assertEqual(image.provider, "runway")
        self.assertEqual(image.estimated_cost["total_cents"],
                         routing.estimate_cost(image.tool, {"ratio": "1920:1080"}, list_price=True).total_cents)
        self.assertIsNone(self.select("image", provider="seedream", required={"max_resolution": 720}).estimated_cost["total_cents"])

    def test_published_quotes_match_pure_billing_calculations(self):
        from server.billing_rates import cost_for
        examples = [
            ("Kling___text_to_video", {"duration_seconds": 5, "generate_audio": True, "resolution": "1080p"}),
            ("Runway___text_to_video", {"duration_seconds": 5}),
            ("Runway___video_to_video", {"video_duration_seconds": 5}),
            ("Runway___text_to_image", {"ratio": "1920:1080"}),
            ("Luma___modify_video", {"source_duration_seconds": 5}),
            ("Fal___text_to_video", {"prompt": "Forest", "num_frames": 81}),
            ("Seedance___text_to_video", {"duration_seconds": 5}),
            ("Seedream___text_to_image", {"size": "1K"}),
        ]
        with patch.dict(os.environ, {key: "false" for key in ["KLING_DRY_RUN", "RUNWAY_DRY_RUN", "LUMA_DRY_RUN", "FAL_DRY_RUN"]}):
            for name, args in examples:
                with self.subTest(name=name):
                    provider, tool = routing.tool_parts(name)
                    args = {**args, "model": routing.effective_model(provider, tool, args)}
                    self.assertEqual(routing.estimate_cost(name, args, list_price=True).total_cents,
                                     cost_for(provider, tool, args).total_cents)

    def test_v2v_ladder_and_plate_preference(self):
        for tier, tool in [("draft", "Fal___video_to_video"), ("standard", "Luma___modify_video"),
                           ("premium", "Runway___video_to_video")]:
            self.assertEqual(self.select("v2v_edit", tier=tier).tool, tool)
        self.assertEqual(self.select("v2v_edit", faithful=True).tool, "Runway___video_to_video")
        self.assertEqual(routing.route_intent("edit multi-shot footage faithfully").tool, "Runway___video_to_video")

    def test_confidential_is_wan_only_and_never_escalates(self):
        for tier in ["draft", "standard", "premium"]:
            self.assertEqual(self.select(tier=tier, confidential=True).tool, "Fal___text_to_video")
        self.assertEqual(self.select(confidential=True, provider="runway").status, "blocked")
        self.assertEqual(self.select(confidential=True, required={"max_resolution": 1080}).status, "blocked")
        self.assertEqual(self.select(confidential=True, retry=True).tool, "Fal___text_to_video")
        self.assertEqual(self.select("image", confidential=True).status, "blocked")

    def test_reject_retry_keeps_features_and_uses_wan(self):
        self.assertEqual(self.select(tier="premium", retry=True).tool, "Fal___text_to_video")
        self.assertEqual(self.select(retry=True, required={"native_audio": True}).status, "blocked")

    def test_prompt_constraints_and_preview_tier(self):
        self.assertEqual(routing.route_intent("generate a video of a forest").tier, "standard")
        self.assertEqual(routing.route_intent("draft video of a forest").tool, "Fal___text_to_video")
        self.assertEqual(routing.route_intent("animate image with end frame at 1080p").tool, "Kling___image_to_video")
        self.assertEqual(routing.route_intent("Seedance video needs end frame").status, "blocked")
        self.assertEqual(routing.route_intent("confidential video with native audio").status, "blocked")

    def test_disclosure_contains_choice_tier_filters_cost_and_typical_speed(self):
        route = self.select(required={"multi_shot": True})
        for part in ["Kling", "kling-3.0", "standard", "multi_shot", "Estimated cost", "typical"]:
            self.assertIn(part, route.disclosure)

    def test_unpublished_settings_remain_unknown(self):
        for job, kwargs in [
            ("image", {"provider": "seedream", "arguments": {"size": "2K"}}),
            ("v2v_edit", {"provider": "runway", "arguments": {"video_duration_seconds": 5.5}}),
            ("t2v", {"provider": "fal", "arguments": {"resolution": "360p"}}),
            ("t2v", {"provider": "fal", "model": "fal-ai/wan-22-vace-fun-a14b"}),
            ("v2v_edit", {"provider": "luma", "arguments": {"source_duration_seconds": 7}}),
        ]:
            with self.subTest(kwargs=kwargs):
                route = self.select(job, **kwargs)
                self.assertIn("unknown", route.disclosure)
                self.assertIsNone(route.estimated_cost["total_cents"])

    def test_table_is_built_schema_and_inherits_restrictive_policy(self):
        from test_skill_routing import gateway_names
        rows = routing.capability_table()
        known = gateway_names()
        schemas = {path.stem.removesuffix(".tools"): {tool["name"]: tool["inputSchema"] for tool in json.loads(path.read_text())}
                   for path in Path("configs/gateway").glob("*.tools.json")}
        for row in rows:
            policy = routing.POLICY["providers"][row["provider"]]
            self.assertEqual(row["license"], policy.get("model_policies", {}).get(row["model"], {}).get("license", policy["license"]))
            self.assertEqual(row["allowed_regions"], policy["allowed_regions"])
            self.assertEqual(row["blocked_regions"], policy.get("blocked_regions", []))
            self.assertEqual(row["training_eligible"], policy["training_eligible"] and policy.get("model_policies", {}).get(row["model"], {}).get("training_eligible", False))
            self.assertTrue(set(row["tools"].values()) <= known)
            for variant, name in row["tools"].items():
                provider, tool = routing.tool_parts(name)
                self.assertTrue(set(row["controls"][variant]) <= set(schemas[provider][tool]["properties"]))
            self.assertFalse(row["jobs"]["lipsync"])
            self.assertFalse(row["jobs"]["upscale"])
        self.assertEqual(len(rows), 17)
        self.assertFalse(next(r for r in rows if r["provider"] == "seedance")["jobs"]["start_end_frame"])


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
            await executor.execute({"tool_name": "Seedance___text_to_video", "arguments": {"prompt": "Shot"}, "call_id": "generate"})
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

    async def test_confidential_cannot_send_new_media_to_audio_provider(self):
        from agent.gateway_executor import GatewayExecutor
        from mcp import Tool
        studio = _context_from_request(StudioAgentRequest(prompt="voiceover", confidential=True, autonomous=True))
        gateway = Gateway([Tool(name="ElevenLabs___text_to_speech_convert", inputSchema={"type": "object"})])
        result = await GatewayExecutor(studio, [gateway]).execute({"tool_name": "ElevenLabs___text_to_speech_convert",
            "arguments": {}, "call_id": "voice"}, approved=True)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("Wan", result["reason"])
        gateway.call_tool.assert_not_awaited()

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
            self.assertTrue(any("kling-3.0" in event.message and "standard" in event.message
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

    async def test_confidential_context_cannot_be_bypassed_by_approved_tool(self):
        from agent.gateway_executor import GatewayExecutor
        from mcp import Tool
        request = StudioAgentRequest(prompt="video", confidential=True, autonomous=True, job_id="private")
        studio = _context_from_request(request)
        gateway = Gateway([Tool(name="Runway___text_to_video", description="Video", inputSchema={"type": "object"})])
        result = await GatewayExecutor(studio, [gateway]).execute({"tool_name": "Runway___text_to_video",
            "arguments": {"prompt": "Hero"}, "call_id": "bypass"}, approved=True)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("confidential", result["reason"].lower())
        gateway.call_tool.assert_not_awaited()


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
                self.assertEqual(routing.route_intent(request.prompt + " video", confidential=request.confidential).status, "blocked")
            restored = StudioRepository(repo.database_path, repo.media_root)
            self.assertTrue(restored.project_provider_policy("workspace", "private")["confidential"])

    def test_invalid_tier_is_rejected_at_request_boundary(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            StudioAgentRequest(prompt="video", quality_tier="free")
