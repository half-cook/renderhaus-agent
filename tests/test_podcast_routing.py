from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.deep_agent.routing import effective_model, estimate_cost, request_tool_blocker, resolve_alias, route_intent
from agent.gateway_executor import APPROVAL_EXEMPT_TOOLS, GatewayExecutor, _local_remotion_arguments, tool_needs_approval


class PodcastRoutingTests(unittest.TestCase):
    def test_workbook_clip_routes_to_existing_transcription_then_render(self):
        route = route_intent(
            "Make an audiogram from this 60-second podcast clip with captions, sized for Reels and square"
        )
        self.assertEqual(route.skill, "podcast-audiogram")
        self.assertEqual(route.status, "ready")
        self.assertEqual([step.alias for step in route.steps], ["elevenlabs_stt", "remotion_render"])
        self.assertEqual(route.steps[0].tool, "ElevenLabs___speech_to_text_convert")
        self.assertEqual(route.steps[0].required["timestamps_granularity"], "word")
        self.assertFalse(route.steps[0].required["no_verbatim"])
        self.assertEqual(route.required["aspects"], ["9:16", "1:1"])
        self.assertEqual(route.expected_output, "assembled MP4")

    def test_source_timing_reuse_skips_transcription(self):
        for source in [
            {"words": [{"text": "Hello", "start": 0, "end": 0.5}]},
            {"transcript": {"words": [{"text": "Hello", "start": 0, "end": 0.5}]}},
            {"index_words": [{"text": "Hello", "start": 0, "end": 0.5}]},
            {"captions_srt": "1\n00:00:00,000 --> 00:00:00,500\nHello"},
            {"transcription_id": "existing-transcript"},
        ]:
            with self.subTest(source=source):
                route = route_intent("Turn this quote into a captioned waveform video", arguments=source)
                self.assertEqual(route.skill, "podcast-audiogram")
                self.assertEqual(route.alias, "remotion_render")
                self.assertFalse(any(step.alias == "elevenlabs_stt" for step in route.steps))
                self.assertTrue(route.required["reuse_transcript"])

    def test_long_episode_selects_start_with_footage_memory(self):
        for prompt in ["Find the best 60-second moment from this 90-minute podcast episode for an audiogram",
                       "From this 90-minute podcast episode, pick the best 60-second moment for an audiogram"]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "footage-memory")
                self.assertEqual(route.alias, "footage_memory_status")
                self.assertEqual(route.required["duration_s"], 5400)

    def test_channel_templates_remain_motion_graphics(self):
        for prompt, name in [
            ("Make a 4-second channel intro sting", "youtube-intro-sting"),
            ("Make a YouTube end screen", "youtube-end-screen"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "motion-graphics")
                self.assertEqual(route.alias, "remotion_render")
                self.assertEqual(route.required["template_name"], name)

    def test_existing_editing_routes_keep_ownership(self):
        for prompt, skill in [
            ("Add captions to this talking-head video and show the speaker", "conversational-edit"),
            ("Add captions and a moving waveform to this talking-head video, keeping the speaker visible", "conversational-edit"),
            ("Make an audiogram and keep the interview video visible", "conversational-edit"),
            ("Make a lower third for this speaker", "motion-graphics"),
            ("Create ad variants from this approved master video", "remotion-ad-variant-matrix"),
        ]:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt).skill, skill)

    def test_missing_transcription_cannot_fall_back_to_generation(self):
        route = route_intent("Make an audiogram from this podcast clip", available_tools={"Remotion___render_timeline"})
        self.assertEqual(route.status, "blocked")
        self.assertIsNone(route.tool)
        self.assertIn("transcription", route.reason)
        self.assertEqual(resolve_alias("elevenlabs_stt"), "ElevenLabs___speech_to_text_convert")

    def test_transcription_and_alignment_always_require_approval(self):
        for name in ["ElevenLabs___speech_to_text_convert", "ElevenLabs___forced_alignment_create"]:
            for autonomous in [False, True]:
                self.assertTrue(tool_needs_approval(name, autonomous), (name, autonomous))
        self.assertFalse(tool_needs_approval("ElevenLabs___speech_to_text_transcripts_get", True))
        self.assertEqual(APPROVAL_EXEMPT_TOOLS, frozenset({"Remotion___export_nle_timeline"}))

    def test_unconfigured_transcription_quote_remains_unknown(self):
        with patch.dict(os.environ, {"ELEVENLABS_TOOL_COST_CENTS_JSON": "{}", "STRIPE_SECRET_KEY": ""}):
            quote = estimate_cost("ElevenLabs___speech_to_text_convert", {"model_id": "scribe_v2"})
            message = GatewayExecutor.dispatch_disclosure(SimpleNamespace(),
                "ElevenLabs___speech_to_text_convert", {"model_id": "scribe_v2"}, None)
        self.assertIsNone(quote.total_cents)
        self.assertIn("unknown", quote.description.lower())
        self.assertIn("scribe_v2", message)
        self.assertIn("unknown", message.lower())

    def test_audiogram_excludes_replacement_speech_and_keeps_transcription(self):
        for tool in ["ElevenLabs___text_to_speech_convert", "ElevenLabs___speech_to_speech_convert",
                     "ElevenLabs___voices_ivc_create", "FishAudio___generate_speech", "HeyGen___voice_tts",
                     "Sync___lipsync_video", "Sync___create_dialogue_video"]:
            with self.subTest(tool=tool):
                reason = request_tool_blocker("Make an audiogram from this podcast clip", tool)
                self.assertIsNotNone(reason)
                self.assertIn("source recording", reason)
        for tool in ["ElevenLabs___speech_to_text_convert", "ElevenLabs___forced_alignment_create",
                     "Remotion___render_timeline", "Ffmpeg___ffmpeg_tool"]:
            self.assertIsNone(request_tool_blocker("Make an audiogram from this podcast clip", tool))
        self.assertIsNone(request_tool_blocker('Make a trailer; the supplied title is "audiogram"',
                                               "ElevenLabs___text_to_speech_convert"))

    def test_template_art_uses_same_owned_source_resolver_as_audio(self):
        resolved = []
        def resolver(version):
            resolved.append(version)
            return "/owned/" + version
        studio = SimpleNamespace(source_versions={"cover-source": "cover-v1"}, source_resolver=resolver, job_id="job")
        arguments = {"audio_tracks": [{"url": "renderhaus-asset://audio-v1"}],
                     "template": {"name": "podcast-audiogram", "cover_url": "cover-source"}}
        prepared = _local_remotion_arguments(studio, arguments)
        self.assertEqual(prepared["template"]["cover_url"], "/owned/cover-v1")
        self.assertEqual(prepared["audio_tracks"][0]["url"], "/owned/audio-v1")
        self.assertCountEqual(resolved, ["cover-v1", "audio-v1"])
        self.assertEqual(arguments["template"]["cover_url"], "cover-source")
        arguments = {"template": {"name": "youtube-intro-sting", "logo_url": "renderhaus-asset://logo-v1"}}
        self.assertEqual(_local_remotion_arguments(studio, arguments)["template"]["logo_url"], "/owned/logo-v1")

    def test_template_art_local_paths_are_job_confined(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": directory}):
            job = Path(directory) / "job"
            job.mkdir()
            (job / "cover.png").write_bytes(b"owned cover")
            studio = SimpleNamespace(source_versions={}, source_resolver=None, job_id="job")
            prepared = _local_remotion_arguments(studio, {"template": {"cover_url": "cover.png"}})
            self.assertEqual(prepared["template"]["cover_url"], str(job / "cover.png"))
            with self.assertRaisesRegex(ValueError, "traversal"):
                _local_remotion_arguments(studio, {"template": {"cover_url": "../cover.png"}})
            with self.assertRaisesRegex(ValueError, "resolver"):
                _local_remotion_arguments(studio, {"template": {"logo_url": "renderhaus-asset://logo-v1"}})


    def test_transcription_effective_model_and_operator_quote(self):
        self.assertEqual(effective_model("elevenlabs", "speech_to_text_convert", {"model_id": "scribe_v2"}), "scribe_v2")
        self.assertEqual(effective_model("elevenlabs", "speech_to_text_convert", {"model_id": "scribe_v1"}), "scribe_v1")
        self.assertIsNone(effective_model("elevenlabs", "speech_to_text_transcripts_get", {"transcription_id": "saved"}))
        with patch.dict(os.environ, {"ELEVENLABS_TOOL_COST_CENTS_JSON": '{"speech_to_text_convert": 10}', "STRIPE_SECRET_KEY": ""}):
            quote = estimate_cost("ElevenLabs___speech_to_text_convert", {"model_id": "scribe_v2"})
        self.assertIsNotNone(quote.total_cents)
