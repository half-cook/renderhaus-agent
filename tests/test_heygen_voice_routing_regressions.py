from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent.deep_agent import routing


class HeyGenVoiceRoutingRegressions(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "HEYGEN_VOICE_AB_GATE": "internal", "HEYGEN_VOICE_AB_USERS": "alice",
            "HEYGEN_VOICE_DRY_RUN": "true", "HEYGEN_DRY_RUN": "true",
            "ELEVENLABS_DRY_RUN": "true", "SEEDANCE_DRY_RUN": "true",
            "FAL_DRY_RUN": "true", "REMOTION_DRY_RUN": "true",
            "RENDERHAUS_SECRETS_NAME": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def route(self, prompt: str, **kwargs):
        return routing.route_intent(prompt, user_id="alice", **kwargs)

    def test_apostrophes_do_not_hide_shorthand_after_script_label(self):
        route = self.route("Read this script in my cloned voice: It's sunny and he'll call Dr. Lee ASAP.")
        self.assertEqual(route.alias, "eleven_v4_turbo")
        self.assertIn("normalisation", route.basis)

    def test_unquoted_cloned_speech_uses_elevenlabs_for_spoken_shorthand(self):
        for script in ("Call 1-800-555-0199 tomorrow, ASAP.", "Meet on 2026-10-31.",
                       "Download 3.5 GB.", "Ask Dr. Lee."):
            with self.subTest(script=script):
                route = self.route("Read in my cloned voice. " + script)
                self.assertEqual(route.alias, "eleven_v4_turbo")
                self.assertIn("normalisation", route.basis)

    def test_single_quoted_script_keeps_contractions_and_shorthand(self):
        route = self.route("Read in my cloned voice: 'It's sunny and he'll call Dr. Lee ASAP.'")
        self.assertEqual(route.alias, "eleven_v4_turbo")

    def test_quoted_name_does_not_hide_shorthand_in_labelled_script(self):
        route = self.route("Read this script in my cloned voice: Call 'Alice' by Oct 31, ASAP.")
        self.assertEqual(route.alias, "eleven_v4_turbo")
        self.assertIn("normalisation", route.basis)

    def test_plain_unquoted_prose_uses_gated_candidate(self):
        route = self.route("Read in my cloned voice. It's sunny and he'll call tomorrow.")
        self.assertEqual(route.alias, "heygen_voice_tts")

    def test_language_prefixed_script_checks_the_spoken_text(self):
        route = self.route("Read the script with my cloned voice in French: Call Dr. Lee ASAP.")
        self.assertEqual(route.alias, "eleven_v4_turbo")
        self.assertIn("normalisation", route.basis)

    def test_video_clone_and_read_script_keeps_picture_and_assembly(self):
        route = self.route("Make a video, clone my voice and read a script in it.")
        self.assertEqual([step.alias for step in route.steps],
                         ["wan3_t2v", "heygen_voice_clone", "heygen_voice_tts", "remotion_render"])
        self.assertEqual(route.execution_groups,
                         (("wan3_t2v", "heygen_voice_clone"), ("heygen_voice_tts",), ("remotion_render",)))

    def test_video_clone_and_speak_script_keeps_picture_and_assembly(self):
        route = self.route("Make a video, clone my voice and speak this script in it.")
        self.assertEqual([step.alias for step in route.steps],
                         ["wan3_t2v", "heygen_voice_clone", "heygen_voice_tts", "remotion_render"])

    def test_negated_read_or_speak_does_not_add_narration(self):
        for prompt in ("Make a silent video; do not read the script.",
                       "Make a video without narration; never speak this script."):
            with self.subTest(prompt=prompt):
                route = self.route(prompt)
                self.assertEqual(route.alias, "wan3_t2v")
                self.assertFalse(route.steps)

    def test_reference_duration_is_not_part_of_spoken_script(self):
        route = self.route("Clone my voice from this 2-minute recording and read this script in it")
        self.assertEqual([step.alias for step in route.steps], ["heygen_voice_clone", "heygen_voice_tts"])

    def test_reference_duration_does_not_override_plain_script(self):
        route = self.route("Clone my voice from this 2-minute recording and read this script in it: "
                           "It's sunny and he'll call tomorrow.")
        self.assertEqual([step.alias for step in route.steps], ["heygen_voice_clone", "heygen_voice_tts"])

    def test_noun_voice_clone_creates_before_speaking(self):
        route = self.route("Create an instant voice clone and read this script")
        self.assertEqual([step.alias for step in route.steps], ["heygen_voice_clone", "heygen_voice_tts"])
        self.assertEqual(route.execution_groups, (("heygen_voice_clone",), ("heygen_voice_tts",)))

    def test_video_noun_voice_clone_creates_before_narration_and_assembly(self):
        route = self.route("Generate a 5-second clip using Seedance. Create an instant voice clone "
                           "and add narration, then assemble an MP4.")
        self.assertEqual(route.status, "ready", route.reason)
        self.assertEqual([step.alias for step in route.steps],
                         ["seedance25_t2v", "heygen_voice_clone", "heygen_voice_tts", "remotion_render"])
        self.assertEqual(route.execution_groups,
                         (("seedance25_t2v", "heygen_voice_clone"), ("heygen_voice_tts",), ("remotion_render",)))

    def test_video_clone_narration_and_assembly_preserve_dependencies(self):
        route = self.route("Generate a 5-second clip using Seedance. Clone my voice from this "
                           "2-minute recording and add narration, then assemble an MP4.")
        self.assertEqual(route.status, "ready", route.reason)
        self.assertEqual([step.alias for step in route.steps],
                         ["seedance25_t2v", "heygen_voice_clone", "heygen_voice_tts", "remotion_render"])
        self.assertEqual(route.execution_groups,
                         (("seedance25_t2v", "heygen_voice_clone"), ("heygen_voice_tts",), ("remotion_render",)))
        self.assertEqual(route.expected_output, "assembled MP4")
        self.assertTrue(all(step.dispatch_tool == "call_audio_tool" for step in route.steps[1:3]))

    def test_video_cloned_speech_gate_off_keeps_elevenlabs_and_assembly(self):
        with patch.dict(os.environ, {"HEYGEN_VOICE_AB_GATE": "off"}):
            route = self.route("Generate a 5-second clip using Seedance. Clone my voice and add narration, "
                               "then assemble an MP4.")
        self.assertEqual(route.status, "ready", route.reason)
        self.assertEqual([step.alias for step in route.steps],
                         ["seedance25_t2v", "voices_ivc_create", "eleven_v4_turbo", "remotion_render"])
        self.assertEqual(route.execution_groups,
                         (("seedance25_t2v", "voices_ivc_create"), ("eleven_v4_turbo",), ("remotion_render",)))

    def test_existing_project_clone_skips_creation_and_still_assembles(self):
        route = self.route("Generate a 5-second clip using Seedance with narration in my cloned voice, "
                           "then assemble an MP4.")
        self.assertEqual(route.status, "ready", route.reason)
        self.assertEqual([step.alias for step in route.steps],
                         ["seedance25_t2v", "heygen_voice_tts", "remotion_render"])
        self.assertEqual(route.execution_groups,
                         (("seedance25_t2v", "heygen_voice_tts"), ("remotion_render",)))

    def test_video_named_elevenlabs_request_overrides_candidate(self):
        route = self.route("Generate a 5-second clip using Seedance. Use ElevenLabs to clone my voice "
                           "and add narration, then assemble an MP4.")
        self.assertEqual(route.status, "ready", route.reason)
        self.assertEqual([step.alias for step in route.steps],
                         ["seedance25_t2v", "voices_ivc_create", "eleven_v4_turbo", "remotion_render"])

    def test_video_stock_voice_retains_tts_default(self):
        route = self.route("Generate a 5-second clip using Seedance with narration in a stock voice, "
                           "then assemble an MP4.")
        self.assertEqual(route.status, "ready", route.reason)
        self.assertEqual([step.alias for step in route.steps],
                         ["seedance25_t2v", "eleven_v4_turbo", "remotion_render"])
        self.assertEqual(route.execution_groups,
                         (("seedance25_t2v", "eleven_v4_turbo"), ("remotion_render",)))


if __name__ == "__main__":
    unittest.main()
