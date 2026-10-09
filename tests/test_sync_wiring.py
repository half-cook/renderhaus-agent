from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.deep_agent import routing
from agent.gateway_executor import GatewayExecutor, tool_needs_approval


ARGS = {
    "video_url": "https://example.test/interview.mp4",
    "audio_url": "https://example.test/voice.wav",
    "source_duration_seconds": 10.0,
    "audio_duration_seconds": 8.0,
    "source_fps": 25.0,
    "subjects": "Presenter Alice and narrator Bob; both authorized this replacement",
    "consent_confirmed": True,
}


class SyncWiringTests(unittest.TestCase):
    def test_existing_footage_routes_to_sync_without_confidential_or_price_tiers(self):
        for prompt in ["lipsync this footage", "revoice this interview clip",
                       "dub this interview clip into Spanish",
                       "lip-sync existing footage with a new narration voiceover",
                       "revoice this interview clip with ElevenLabs audio",
                       "lipsync this clip with ElevenLabs TTS",
                       "dub this uploaded footage into French",
                       "dub this existing video into French",
                       "replace the voice in this video"]:
            for confidential in (False, True):
                route = routing.route_intent(prompt, confidential=confidential, arguments=ARGS)
                self.assertEqual(route.tool, "Sync___lipsync_video")
                self.assertEqual(route.alias, "sync3_lipsync")
                self.assertEqual(route.dispatch_tool, "call_media_tool")
                self.assertEqual(route.status, "ready")

    def test_generated_talking_shots_keep_seedance_and_long_presenters_stay_pending(self):
        self.assertEqual(routing.route_intent("generate a cartoon talking shot").alias, "seedance25_t2v")
        self.assertEqual(routing.route_intent("talking avatar from a cartoon image and audio").alias, "seedance25_i2v")
        long = routing.route_intent("90 second multilingual avatar presenter")
        self.assertEqual(long.alias, "heygen_avatar_v")
        self.assertEqual(long.status, "pending")
        self.assertEqual(routing.route_intent("use sync-3 to dub a 90 second presenter video").alias,
                         "sync3_lipsync")

    def test_paid_sync_always_requires_approval_and_polling_is_free(self):
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            for autonomous in (False, True):
                self.assertTrue(tool_needs_approval("Sync___lipsync_video", autonomous))
                self.assertTrue(tool_needs_approval("sync3_lipsync", autonomous))
        self.assertFalse(tool_needs_approval("Sync___get_video_task", True))
        self.assertEqual(routing.estimate_cost("Sync___get_video_task", {}).total_cents, 0)

    def test_retired_noncommercial_face_dependencies_cannot_route_to_sync(self):
        for provider in ("LatentSync", "Latent Sync", "LivePortrait", "Live Portrait"):
            with self.subTest(provider=provider):
                route = routing.route_intent(f"use {provider} to lipsync this existing video")
                self.assertEqual(route.status, "retired")
                self.assertIsNone(route.tool)
                self.assertIn("non-commercial InsightFace", route.reason)

    def test_quotes_use_host_rate_duration_mode_and_fps(self):
        from server.billing_rates import cost_for

        with patch.dict(os.environ, {"SYNC_TRANSPORT": "fal"}):
            cost = cost_for("sync", "lipsync_video", ARGS)
            self.assertEqual(cost.provider_cents, 107)
            self.assertEqual(routing.estimate_cost("Sync___lipsync_video", ARGS).total_cents, cost.total_cents)
            self.assertEqual(cost_for("sync", "lipsync_video", {**ARGS, "sync_mode": "silence"}).provider_cents, 134)
        with patch.dict(os.environ, {"SYNC_TRANSPORT": "direct", "SYNC_BILLING_PLAN": "legacy_base"}):
            self.assertEqual(cost_for("sync", "lipsync_video", {**ARGS, "source_fps": 50.0}).provider_cents, 213)
        with patch.dict(os.environ, {"SYNC_TRANSPORT": "direct", "SYNC_BILLING_PLAN": "credits"}):
            self.assertIsNone(routing.estimate_cost("Sync___lipsync_video", ARGS).total_cents)
        self.assertIsNone(routing.estimate_cost("Sync___lipsync_video", {}).total_cents)

    def test_consent_cannot_be_inferred_from_spending_approval(self):
        executor = object.__new__(GatewayExecutor)
        executor.studio = SimpleNamespace(prompt="lipsync this footage")
        route = routing.route_intent(executor.studio.prompt, arguments=ARGS)
        self.assertIsNone(executor.selection_blocker("Sync___lipsync_video", ARGS, route))
        for changed in ({"consent_confirmed": False}, {"consent_confirmed": "true"}, {"subjects": " "}):
            self.assertIn("consent", executor.selection_blocker("Sync___lipsync_video", {**ARGS, **changed}, route).lower())
        disclosure = executor.dispatch_disclosure("Sync___lipsync_video", ARGS, route)
        self.assertIn("Alice", disclosure)
        self.assertIn("consent", disclosure.lower())
        self.assertIn("fal", disclosure.lower())
        self.assertIn("$", disclosure)

    def test_sync_provenance_never_enters_training(self):
        self.assertFalse(routing.training_eligible({"provider": "sync", "model": "sync-3",
            "status": "succeeded", "weights_license": "Apache-2.0", "training_eligible": True}))

    def test_mode_output_duration_and_measured_resolution_are_enforced(self):
        executor = object.__new__(GatewayExecutor)
        executor.studio = SimpleNamespace(prompt="lipsync this 8 second 1080p interview clip")
        measured = {**ARGS, "source_width": 1920, "source_height": 1080}
        route = routing.route_intent(executor.studio.prompt, arguments=measured)
        self.assertEqual(route.status, "ready")
        self.assertIsNone(executor.selection_blocker("Sync___lipsync_video", measured, route))
        self.assertIn("measured", executor.selection_blocker("Sync___lipsync_video", ARGS, route))
        wrong_duration = {**measured, "audio_duration_seconds": 7.0}
        self.assertIn("duration", executor.selection_blocker("Sync___lipsync_video", wrong_duration, route).lower())
        executor.studio.prompt = "use Sync to revoice a 120 second 1080p presenter video"
        chunked = {**measured, "source_duration_seconds": 120.0, "audio_duration_seconds": 120.0,
                   "chunk_boundaries_seconds": [60.0]}
        route = routing.route_intent(executor.studio.prompt, arguments=chunked)
        self.assertIn("720p", executor.selection_blocker("Sync___lipsync_video", chunked, route))


if __name__ == "__main__":
    unittest.main()
