from __future__ import annotations

import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from providers.footage_memory.backends import BACKENDS, MediaWindow, get_backend
from providers.footage_memory.decisions import recommendation


def offline_environment(values=None):
    settings = {"FOOTAGE_MEMORY_DRY_RUN": "true", **(values or {})}

    def read(name, default=None):
        if name.endswith("_KEY") or "TOKEN" in name:
            raise AssertionError("Credential access is forbidden in offline tests.")
        return settings.get(name, default)

    return patch("os.getenv", side_effect=read)


class FootageBackendTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaWindow(Path("fictional.mp4"), 30.0, 60.0, "a" * 64)

    def test_default_is_offline_candidate_using_existing_model_config(self):
        with (
            offline_environment({"GEMINI_VLM_MODEL": "configured-candidate"}),
            patch("socket.socket", side_effect=AssertionError("No network")),
        ):
            backend = get_backend()
            self.assertEqual(backend.name, "gemini")
            self.assertEqual(backend.backend_ref, "gemini:configured-candidate:synthetic-v1")
            self.assertTrue(backend.dry_run)
            events = backend.describe_window(self.media, "Describe this window.")
            answer = backend.answer("What is on the whiteboard?", self.media)
        self.assertEqual(
            {event["kind"] for event in events},
            {"person", "object", "location", "dialogue", "sound", "on_screen_text", "moment"},
        )
        self.assertTrue(answer["simulated"])
        self.assertIn(answer["verdict"], {"verified", "refuted", "ambiguous"})

    def test_unset_flags_default_to_dry_run(self):
        with (
            patch("os.getenv", side_effect=lambda _name, default=None: default),
            patch("socket.socket", side_effect=AssertionError("No network")),
        ):
            result = get_backend().answer("Whiteboard?", self.media)
        self.assertTrue(result["simulated"])

    def test_invalid_shared_model_configuration_has_a_neutral_error(self):
        with offline_environment({"GEMINI_VLM_MODEL": "invalid model identifier"}):
            with self.assertRaises(ValueError) as raised:
                get_backend()
        self.assertEqual(str(raised.exception), "Footage analysis configuration is invalid.")

    def test_mock_events_are_repeatable_absolute_and_speaker_attributed(self):
        with (
            offline_environment(),
            patch("socket.socket", side_effect=AssertionError("No network")),
        ):
            backend = get_backend("mock")
            first = backend.describe_window(self.media, "Describe.")
            second = backend.describe_window(self.media, "Describe.")
        self.assertEqual(first, second)
        dialogue = next(event for event in first if event["kind"] == "dialogue")
        person = next(event for event in first if event["kind"] == "person")
        self.assertEqual(dialogue["speaker_id"], person["speaker_id"])
        self.assertIn("childhood", dialogue["text"].lower())
        for event in first:
            self.assertGreaterEqual(event["t0_ms"], 30_000)
            self.assertLessEqual(event["t1_ms"], 60_000)
            self.assertLess(event["t0_ms"], event["t1_ms"])
            self.assertGreaterEqual(event["confidence"], 0)
            self.assertLessEqual(event["confidence"], 1)

    def test_submillisecond_window_is_rejected_before_backend(self):
        with self.assertRaises(ValueError):
            MediaWindow(Path("fictional.mp4"), 1, 1.00001, "hash")

    def test_registry_contains_only_the_requested_candidates(self):
        self.assertEqual(set(BACKENDS), {"mock", "gemini", "qwen_omni"})

    def test_disabled_backend_never_reads_credentials_even_in_dry_run(self):
        with (
            offline_environment(),
            patch("socket.socket", side_effect=AssertionError("No network")),
        ):
            with self.assertRaisesRegex(ValueError, "disabled"):
                get_backend("qwen_omni", allow_third_party_vlm=True)

    def test_live_candidate_requires_project_opt_in_and_remains_unimplemented(self):
        with (
            offline_environment({"FOOTAGE_MEMORY_DRY_RUN": "false"}),
            patch("socket.socket", side_effect=AssertionError("No network")),
        ):
            with self.assertRaisesRegex(ValueError, "not enabled for this project"):
                get_backend("gemini")
            with self.assertRaisesRegex(ValueError, "not implemented"):
                get_backend("gemini", allow_third_party_vlm=True)
            self.assertTrue(get_backend("mock").answer("What happened?", self.media)["simulated"])

    def test_unknown_selection_does_not_echo_untrusted_name(self):
        with offline_environment():
            with self.assertRaises(ValueError) as raised:
                get_backend("unsafe-untrusted-value")
        self.assertNotIn("unsafe-untrusted-value", str(raised.exception))

    def test_invalid_dry_run_setting_cannot_enable_live_calls(self):
        with offline_environment({"FOOTAGE_MEMORY_DRY_RUN": "off"}):
            with self.assertRaisesRegex(ValueError, "true or false"):
                get_backend("gemini", allow_third_party_vlm=True)

    def test_fixture_answer_refines_timestamp_and_marks_simulation(self):
        media = MediaWindow(Path("fictional.mp4"), 0, 60, "hash", "m01")
        with offline_environment():
            answer = get_backend("mock").answer("Find the moment the red cup falls.", media)
        self.assertEqual(answer["t0_s"], 12.0)
        self.assertEqual(answer["t1_s"], 13.0)
        self.assertTrue(answer["simulated"])
        self.assertEqual(answer["verdict"], "verified")

    def test_answers_are_bounded_to_the_requested_window(self):
        media = MediaWindow(Path("fictional.mp4"), 25, 29, "hash", "m01")
        with offline_environment():
            answer = get_backend("mock").answer("Find the moment the red cup falls.", media)
        self.assertEqual(answer["verdict"], "ambiguous")
        self.assertGreaterEqual(answer["t0_s"], 25)
        self.assertLessEqual(answer["t1_s"], 29)

    def test_neutral_output_does_not_disclose_provider_model_or_fee(self):
        with offline_environment({"GEMINI_VLM_MODEL": "configured-candidate"}):
            backend = get_backend()
            output = json.dumps(
                {
                    "events": backend.describe_window(self.media, "Describe."),
                    "answer": backend.answer("Whiteboard?", self.media),
                }
            ).lower()
        for prohibited in ("gemini", "qwen", "alibaba", "google", "configured-candidate", "fee"):
            self.assertNotIn(prohibited, output)

    def test_invalid_media_window_times_rejected(self):
        for t0, t1 in ((-1, 30), (30, 30), (math.nan, 30), (0, math.inf), (True, 30)):
            with self.subTest(t0=t0, t1=t1), self.assertRaises(ValueError):
                MediaWindow(Path("fictional.mp4"), t0, t1, "hash")


class FootageDecisionTests(unittest.TestCase):
    def test_duration_thresholds(self):
        for seconds, expected in (
            (0, "watch"),
            (240, "watch"),
            (599.999, "watch"),
            (600, "build"),
            (1799.999, "build"),
            (1800, "build"),
            (10_800, "build"),
        ):
            with self.subTest(seconds=seconds):
                self.assertEqual(recommendation(seconds), expected)

    def test_folder_and_multiple_questions_build(self):
        self.assertEqual(recommendation(60, is_folder=True), "build")
        self.assertEqual(recommendation(60, question_count=3), "build")

    def test_existing_memory_wins(self):
        self.assertEqual(recommendation(60, memory_exists=True), "query")
        self.assertEqual(recommendation(10_800, is_folder=True, memory_exists=True), "query")

    def test_invalid_routing_inputs_rejected(self):
        for duration in (-1, math.inf, math.nan, "60", True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                recommendation(duration)
        for count in (0, -1, True, 1.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                recommendation(60, question_count=count)


if __name__ == "__main__":
    unittest.main()
