from __future__ import annotations

import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from mcp import Tool

from agent.deep_agent import routing
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision,
    StudioToolEvent, _context_from_request, _validate_video_delivery,
)
from server import billing_rates
from test_deep_agent import Gateway, ScriptedModel, call, final


SONG = "Mureka___generate_song"
INSTRUMENTAL = "Mureka___generate_instrumental"
VIDEO = "Mureka___generate_lyrics_video"


class MurekaWiringTests(unittest.TestCase):
    def test_music_default_has_no_elevenlabs_interim(self):
        for confidential in (False, True):
            for tier in (None, "draft", "premium"):
                route = routing.route_intent("write a song about summer", confidential=confidential, tier=tier)
                self.assertEqual((route.status, route.alias, route.tool), ("ready", "mureka_v95", SONG))
                self.assertEqual(route.dispatch_tool, "call_audio_tool")
                self.assertEqual(route.model, "mureka-9.5")
        self.assertIsNone(routing.POLICY["capability_map"]["music"]["interim"])

    def test_music_bed_and_instrumentals_select_instrumental_variant(self):
        for prompt in ("generate a music bed", "Mureka instrumental chillhop", "music with no vocals"):
            route = routing.route_intent(prompt)
            self.assertEqual((route.alias, route.tool), ("mureka_v95", INSTRUMENTAL))
        self.assertEqual(routing.route_intent("lofi track with lyrics").tool, SONG)

    def test_explicit_elevenlabs_music_still_wins_with_disclosure(self):
        route = routing.route_intent("use ElevenLabs music for an instrumental bed")
        self.assertEqual(route.tool, "ElevenLabs___music_compose")
        self.assertIn("explicit", route.basis)
        self.assertTrue(routing.TOOL_MAP["elevenlabs_music"]["explicit_only"])

    def test_supplied_song_lyrics_video_is_ready_and_enforced_by_capability(self):
        route = routing.route_intent("Mureka lyrics video vertical 9:16 from my track")
        self.assertEqual((route.skill, route.alias, route.tool), ("lyrics-video", "mureka_lyrics_video", VIDEO))
        self.assertEqual(routing.job_type(VIDEO), "lyrics_video")
        self.assertEqual(route.dispatch_tool, "call_audio_tool")
        self.assertEqual(route.required.get("aspect_ratio"), "9:16")

    def test_new_song_then_video_preserves_both_steps(self):
        route = routing.route_intent("lyrics video for a song you write about summer")
        self.assertEqual([(s.skill, s.alias, s.tool) for s in route.steps], [
            ("lyrics-video", "mureka_v95", SONG), ("lyrics-video", "mureka_lyrics_video", VIDEO),
        ])

    def test_supplied_song_does_not_trigger_paid_music_generation(self):
        for prompt in ("Create a lyrics video for my song", "Generate a lyrics video from this song",
                       "Generate a karaoke video using the song I uploaded"):
            route = routing.route_intent(prompt)
            self.assertEqual(route.tool, VIDEO)
            self.assertEqual(route.steps, ())

    def test_video_aspect_and_instrumental_intent_cannot_be_overridden_by_arguments(self):
        request = StudioAgentRequest(prompt="make a horizontal lyrics video from my song")
        executor = GatewayExecutor(_context_from_request(request), [])
        route = executor.media_selection(VIDEO, {"song_id": "song_1", "aspect_ratio": "9:16"})
        self.assertIn("aspect_ratio", executor.selection_blocker(VIDEO, {"song_id": "song_1"}, route))
        request = StudioAgentRequest(prompt="generate an instrumental music bed")
        executor = GatewayExecutor(_context_from_request(request), [])
        route = executor.media_selection(SONG, {"prompt": "Music"})
        self.assertEqual(route.tool, INSTRUMENTAL)
        self.assertIn("selected", executor.selection_blocker(SONG, {"prompt": "Music"}, route))

    def test_requested_video_duration_uses_the_native_millisecond_range(self):
        for seconds in (5, 10):
            request = StudioAgentRequest(prompt=f"Make a {seconds} second lyrics video from my song")
            self.assertEqual(routing.route_intent(request.prompt).required["duration_seconds"], seconds)
            executor = GatewayExecutor(_context_from_request(request), [])
            args = {"song_id": "song_1", "selection_start": 2000, "selection_end": 2000 + seconds * 1000}
            route = executor.media_selection(VIDEO, args)
            self.assertIsNone(executor.selection_blocker(VIDEO, args, route))
            self.assertEqual(route.estimated_cost["total_cents"], 19)
            for invalid in ({"song_id": "song_1"}, {**args, "selection_end": args["selection_end"] + 1000}):
                self.assertIn("duration", executor.selection_blocker(VIDEO, invalid, route))

    def test_multi_step_provider_names_are_scoped_without_substituting_unsupported_requests(self):
        prompt = "Mureka lyrics video with TTS narration track first"
        route = routing.route_intent(prompt)
        self.assertEqual([step.alias for step in route.steps], ["eleven_v4_turbo", "mureka_lyrics_video"])
        executor = GatewayExecutor(_context_from_request(StudioAgentRequest(prompt=prompt)), [])
        self.assertEqual(executor.media_selection("ElevenLabs___text_to_speech_convert", {}).status, "ready")
        self.assertEqual(routing.route_intent("use Kling for a lyrics video from my song").status, "blocked")

    def test_tts_first_then_lyrics_video_retains_speech_default(self):
        route = routing.route_intent("lyrics video with TTS narration track first")
        self.assertEqual([(s.skill, s.alias) for s in route.steps], [
            ("audio-bed", "eleven_v4_turbo"), ("lyrics-video", "mureka_lyrics_video"),
        ])

    def test_audio_and_video_approval_rules_remain_distinct(self):
        for autonomous in (False, True):
            self.assertEqual(tool_needs_approval(SONG, autonomous), not autonomous)
            self.assertEqual(tool_needs_approval(INSTRUMENTAL, autonomous), not autonomous)
            self.assertTrue(tool_needs_approval(VIDEO, autonomous))
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            self.assertTrue(tool_needs_approval(VIDEO, True))
            self.assertTrue(tool_needs_approval("mureka_lyrics_video", True))

    def test_catalog_and_poll_tools_are_free_with_no_generation_quote(self):
        for tool in ("get_music_task", "get_video_task", "list_mureka_models"):
            name = "Mureka___" + tool
            self.assertTrue(routing.is_free_tool(name))
            self.assertFalse(tool_needs_approval(name, True))
            self.assertEqual(billing_rates.cost_for("mureka", tool, {}).total_cents, 0)

    def test_exact_fal_prices_and_platform_fee_survive_dry_run(self):
        cases = [("generate_song", {"lyrics": "[Verse]\nSummer sun"}, Decimal("22.5"), 23, 30),
                 ("generate_song", {"prompt": "An original song about summer"}, Decimal("75"), 75, 97),
                 ("generate_instrumental", {"prompt": "Gentle piano"}, Decimal("22.5"), 23, 30),
                 ("generate_lyrics_video", {"song_id": "song_1"}, Decimal("15"), 15, 19)]
        for tool, args, exact, cents, total in cases:
            with self.subTest(tool=tool, args=args):
                self.assertEqual(billing_rates.mureka_price_cents(tool, args), exact)
                with patch.dict(os.environ, {"MUREKA_DRY_RUN": "true", "FAL_DRY_RUN": "true"}):
                    self.assertEqual(routing.estimate_cost("Mureka___" + tool, args).total_cents, total)
                    self.assertEqual(billing_rates.cost_for("mureka", tool, args).total_cents, 0)
                with patch.dict(os.environ, {"MUREKA_DRY_RUN": "false", "FAL_DRY_RUN": "false"}):
                    self.assertEqual(billing_rates.cost_for("mureka", tool, args).provider_cents, cents)

    def test_missing_inputs_and_unverified_models_have_unknown_quotes(self):
        for tool, args in [("generate_song", {}), ("generate_instrumental", {}),
                           ("generate_lyrics_video", {}),
                           ("generate_song", {"prompt": "Summer", "model": "mureka-future"})]:
            self.assertIsNone(routing.estimate_cost("Mureka___" + tool, args).total_cents)

    def test_unverified_model_configuration_is_preview_only(self):
        with patch.dict(os.environ, {"MUREKA_MODEL": "mureka-future", "MUREKA_DRY_RUN": "true", "FAL_DRY_RUN": "true"}):
            self.assertEqual(routing.route_intent("write a song about summer").model, "mureka-future")
            self.assertIsNone(routing.policy_blocker(SONG, {"prompt": "Summer"}))
            self.assertIsNone(routing.estimate_cost(SONG, {"prompt": "Summer"}).total_cents)
            os.environ.update(MUREKA_DRY_RUN="false", FAL_DRY_RUN="false")
            self.assertIn("UNVERIFIED", routing.policy_blocker(SONG, {"prompt": "Summer"}))

    def test_mureka_outputs_never_enter_training(self):
        self.assertFalse(routing.training_eligible({"provider": "mureka", "model": "mureka-9.5",
            "status": "succeeded", "weights_license": "Apache-2.0", "training_eligible": True}))
        for alias in ("mureka_v95", "mureka_lyrics_video"):
            self.assertFalse(routing.POLICY["model_policies"][alias]["training_eligible"])

    def test_manual_studio_options_expose_only_verified_controls(self):
        from server.studio_options import static_field_options

        options = static_field_options()["mureka"]
        self.assertEqual(options["model"], ["mureka-9.5"])
        self.assertIn("9:16", options["aspect_ratio"])
        self.assertIn("layout_7", options["layout"])

    def test_standalone_delivery_requires_saved_finished_video(self):
        for status, downloaded, expected in [("succeeded", True, True), ("queued", False, False),
                                              ("dry_run", False, False), ("succeeded", False, False)]:
            request = StudioAgentRequest(prompt="make a lyrics video from this song MP4")
            studio = _context_from_request(request)
            studio.tool_events.append(StudioToolEvent(id="lyrics-poll", name="Mureka___get_video_task",
                label="Lyrics video", summary="Poll", status=status, result={"status": status,
                "downloaded": downloaded, "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4")}))
            self.assertEqual(_validate_video_delivery(request, studio), expected)


class MurekaApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_studio_invoke_cannot_bypass_lyrics_video_approval(self):
        from fastapi import HTTPException
        from server import studio as studio_api

        body = studio_api.InvokeBody(provider="mureka", tool="generate_lyrics_video",
                                     arguments={"song_id": "song_1"}, project_id="untitled")
        with patch.object(studio_api.repository, "require_project"), patch.object(studio_api, "dispatch") as dispatch:
            with self.assertRaises(HTTPException) as denied:
                await studio_api.invoke_tool(body, None)
            self.assertEqual(denied.exception.status_code, 409)
            self.assertIn("approval", denied.exception.detail)
            dispatch.assert_not_called()

    async def test_native_video_approval_quotes_and_resumes_exactly_once_or_rejects(self):
        for decision in ("approve", "reject"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"RENDERHAUS_OUTCOME_DIR": directory, "MUREKA_DRY_RUN": "true", "FAL_DRY_RUN": "true"}
            ):
                args = {"song_id": "song_1", "layout": "layout_2", "aspect_ratio": "9:16"}
                request = StudioAgentRequest(prompt="make a lyrics video from this song", autonomous=True,
                                             job_id="mureka-" + decision)
                studio = _context_from_request(request)
                schemas = json.loads(Path("configs/gateway/mureka.tools.json").read_text())
                gateway = Gateway([Tool(name="Mureka___" + t["name"], description=t["description"],
                                       inputSchema=t["inputSchema"]) for t in schemas],
                                  result={"status": "dry_run", "provider": "mureka", "model": "mureka-9.5"})
                with self.assertRaises(StudioAgentApprovalRequired) as paused:
                    await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                        call("read_file", {"file_path": "/skills/lyrics-video/SKILL.md"}, "skill"),
                        call("call_audio_tool", {"tool_name": VIDEO, "arguments": args}, "lyrics-video")]))
                approval = paused.exception.approvals[0]
                self.assertIn("$0.19", approval.description)
                self.assertIn("default", approval.description)
                gateway.call_tool.assert_not_awaited()
                resumed = request.model_copy(update={"session_items": studio.session_items,
                    "resume_state": paused.exception.state, "approval_decisions": [
                        StudioApprovalDecision(call_id=approval.call_id, decision=decision)]})
                await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
                if decision == "approve":
                    gateway.call_tool.assert_awaited_once_with(VIDEO, args)
                else:
                    gateway.call_tool.assert_not_awaited()
                rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
                self.assertEqual((rows[-1]["provider"], rows[-1]["stage"], rows[-1]["outcome"]),
                                 ("mureka", "approval", "accepted" if decision == "approve" else "rejected"))

    async def test_default_music_blocks_unrequested_elevenlabs_dispatch(self):
        request = StudioAgentRequest(prompt="generate a music bed", autonomous=True)
        studio = _context_from_request(request)
        gateway = Gateway([Tool(name="ElevenLabs___music_compose", inputSchema={"type": "object"})])
        executor = GatewayExecutor(studio, [gateway])
        result = await executor.execute({"tool_name": "ElevenLabs___music_compose", "arguments": {"prompt": "Piano"},
                                         "call_id": "wrong-provider"}, approved=True)
        self.assertEqual(result["status"], "not_run")
        gateway.call_tool.assert_not_awaited()
