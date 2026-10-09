from __future__ import annotations

import copy
import json
import math
import os
import unittest
from unittest.mock import patch

from providers.catalog import get_provider
from providers.contracts import validate_tool_arguments
from providers.registry import dispatch, generate_schemas, load_committed_schemas
from providers.remotion import api


def source(identifier: str = "interview") -> dict:
    return {
        "id": identifier,
        "url": f"https://example.test/{identifier}.mp4",
        "duration_seconds": 3,
        "words": [
            {"text": "um", "start": 0.1, "end": 0.4, "type": "word"},
            {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
            {"text": "Keep", "start": 0.5, "end": 0.8},
            {"text": "", "start": 0.8, "end": 1.3, "type": "silence"},
            {"text": "this", "start": 1.3, "end": 1.7, "type": "word"},
            {"text": "uh", "start": 1.8, "end": 2, "type": "word"},
            {"text": "idea", "start": 2.2, "end": 2.6, "type": "word"},
        ],
        "metadata": {"version_id": "original-v1", "training_eligible": True},
    }


def proposal() -> dict:
    return {
        "title": "Interview cut",
        "plan_summary": "Remove the fillers and long pause. Add a warm grade and subtitles.",
        "sources": [source()],
        "segments": [
            {"source_id": "interview", "first_word": 1, "last_word": 1},
            {"source_id": "interview", "first_word": 2, "last_word": 2},
            {"source_id": "interview", "first_word": 4, "last_word": 4},
        ],
        "grade": "warm",
    }


def schema_for(name: str) -> dict:
    return next(tool["inputSchema"] for tool in generate_schemas(get_provider("remotion"))
                if tool["name"] == name)


class TranscriptEditTests(unittest.TestCase):
    def prepare(self, **changes) -> dict:
        arguments = proposal()
        arguments.update(changes)
        return api.prepare_conversational_edit(**arguments)

    def test_kept_word_ranges_remove_fillers_and_silence(self) -> None:
        result = self.prepare()
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["transcript"]["text"], "Keep this idea")
        self.assertEqual([word["source_word_index"] for word in result["transcript"]["words"]],
                         [1, 2, 4])
        self.assertLess(result["qc_expectations"]["expected_duration_seconds"], 1.5)
        self.assertEqual(result["qc_expectations"]["word_count"], 3)
        self.assertEqual(result["qc_expectations"]["cut_count"], 3)

    def test_reordered_multi_source_cuts_use_output_caption_offsets(self) -> None:
        ending = {
            "id": "ending", "url": "https://example.test/ending.mp4", "duration_seconds": 2,
            "words": [{"text": "Finish", "start": 0.3, "end": 0.7},
                      {"text": "now", "start": 0.8, "end": 1}],
        }
        result = self.prepare(sources=[source(), ending], segments=[
            {"source_id": "ending", "first_word": 0, "last_word": 1},
            {"source_id": "interview", "first_word": 4, "last_word": 4},
            {"source_id": "interview", "first_word": 1, "last_word": 2},
        ])
        self.assertEqual(result["transcript"]["text"], "Finish now idea Keep this")
        self.assertEqual([cut["source_id"] for cut in result["cuts"]],
                         ["ending", "interview", "interview"])
        for cut, caption, original_word in zip(result["cuts"], result["captions"],
                                               [ending["words"][0], source()["words"][6],
                                                source()["words"][2]]):
            self.assertAlmostEqual(caption["start_seconds"], cut["output_start_seconds"]
                                   + original_word["start"] - cut["source_in_seconds"])
        words = result["transcript"]["words"]
        self.assertTrue(all(left["end"] <= right["start"] for left, right in zip(words, words[1:])))

    def test_padding_cannot_invade_discarded_words(self) -> None:
        result = self.prepare(segments=[{"source_id": "interview", "first_word": 2,
                                         "last_word": 2, "padding_seconds": 0.2}])
        cut = result["cuts"][0]
        self.assertGreaterEqual(cut["source_in_seconds"], 0.8)
        self.assertLessEqual(cut["source_out_seconds"], 1.8)
        self.assertLessEqual(cut["source_in_seconds"], 1.3)
        self.assertGreaterEqual(cut["source_out_seconds"], 1.7)
        self.assertAlmostEqual(cut["source_in_seconds"] * 30,
                               round(cut["source_in_seconds"] * 30))
        self.assertAlmostEqual(cut["source_out_seconds"] * 30,
                               round(cut["source_out_seconds"] * 30))

    def test_audio_event_is_a_padding_boundary_but_not_a_word_index(self) -> None:
        original = {
            "id": "interview", "url": "https://example.test/source.mp4", "duration_seconds": 2,
            "words": [{"text": "[cough]", "start": 0.5, "end": 0.98, "type": "audio_event"},
                      {"text": "Hello", "start": 1, "end": 1.2, "type": "word"},
                      {"text": "[music]", "start": 1.24, "end": 1.5, "type": "audio_event"}],
        }
        result = self.prepare(sources=[original], segments=[
            {"source_id": "interview", "first_word": 0, "last_word": 0,
             "padding_seconds": 0.2}])
        self.assertEqual(result["transcript"]["text"], "Hello")
        self.assertEqual(result["cuts"][0]["source_in_seconds"], 1)
        self.assertLessEqual(result["cuts"][0]["source_out_seconds"], 1.24)

    def test_unsafe_subframe_boundary_is_rejected(self) -> None:
        original = {"id": "interview", "url": "https://example.test/source.mp4", "duration_seconds": 1,
                    "words": [{"text": "discard", "start": 0, "end": 0.505},
                              {"text": "keep", "start": 0.51, "end": 0.8}]}
        with self.assertRaisesRegex(ValueError, "frame boundary"):
            self.prepare(sources=[original], segments=[
                {"source_id": "interview", "first_word": 1, "last_word": 1}])

    def test_source_inputs_and_metadata_stay_immutable(self) -> None:
        arguments = proposal()
        before = copy.deepcopy(arguments)
        result = api.prepare_conversational_edit(**arguments)
        self.assertEqual(arguments, before)
        self.assertNotIn("training_eligible", json.dumps(result))
        self.assertNotIn("version_id", json.dumps(result))

    def test_preview_never_contacts_network_or_starts_a_render(self) -> None:
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "false"}), \
             patch("providers.remotion.api.boto3.Session", side_effect=AssertionError("AWS")), \
             patch("providers.remotion.api._start_lambda_render", side_effect=AssertionError("render")), \
             patch("socket.socket.connect", side_effect=AssertionError("network")):
            result = dispatch("remotion", "prepare_conversational_edit", proposal())
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["plan_summary"], proposal()["plan_summary"])
        for key in ("url", "output_path", "render_id", "bucket_name", "output_key"):
            self.assertNotIn(key, result)

    def test_overlays_precede_captions_and_grade_affects_only_video(self) -> None:
        overlay = {"text": "Key idea", "start_seconds": 0, "duration_seconds": 0.3,
                   "position": "top"}
        result = self.prepare(overlays=[overlay])
        tracks = result["timeline"]["document"]["tracks"]
        self.assertEqual(tracks[-2]["name"], "Titles")
        self.assertEqual(tracks[-1]["name"], "Subtitles")
        self.assertEqual(tracks[-2]["items"][0]["text"], "Key idea")
        self.assertTrue(all(item["grade"] == "warm" for item in tracks[0]["items"]))
        self.assertTrue(all("grade" not in item for item in tracks[-1]["items"]))
        self.assertEqual(result["render_arguments"]["text_overlays"], [overlay])
        self.assertEqual(result["render_arguments"]["subtitles"], result["captions"])

    def test_subtitles_can_be_disabled_without_losing_transcript(self) -> None:
        result = self.prepare(subtitles=False)
        self.assertEqual(result["transcript"]["text"], "Keep this idea")
        self.assertEqual(result["captions"], [])
        self.assertEqual(result["qc_expectations"]["subtitle_count"], 0)
        self.assertEqual(len(result["timeline"]["document"]["tracks"]), 1)

    def test_short_clip_audio_fades_fit_without_opacity_fades(self) -> None:
        original = {"id": "interview", "url": "https://example.test/source.mp4", "duration_seconds": 1,
                    "words": [{"text": "Yes", "start": 0, "end": 0.015},
                              {"text": "discard", "start": 1 / 30, "end": 0.3}]}
        result = self.prepare(sources=[original], segments=[
            {"source_id": "interview", "first_word": 0, "last_word": 0}])
        clip = result["render_arguments"]["visuals"][0]
        self.assertEqual(result["timeline"]["renderConfig"]["durationInFrames"], 1)
        self.assertEqual(clip["fade_in_seconds"], 0)
        self.assertEqual(clip["fade_out_seconds"], 0)
        self.assertLessEqual(clip["audio_fade_in_seconds"] + clip["audio_fade_out_seconds"],
                             clip["duration_seconds"])
        item = result["timeline"]["document"]["tracks"][0]["items"][0]
        self.assertEqual(item["audioFadeIn"], clip["audio_fade_in_seconds"])
        self.assertEqual(item["audioFadeOut"], clip["audio_fade_out_seconds"])

    def test_repeated_cuts_keep_exact_frame_total_without_a_black_tail(self) -> None:
        original = {"id": "interview", "url": "https://example.test/source.mp4", "duration_seconds": 2,
                    "words": [{"text": "Hi", "start": 0.3, "end": 0.7}]}
        result = self.prepare(sources=[original], segments=[
            {"source_id": "interview", "first_word": 0, "last_word": 0}] * 13, fps=14)
        self.assertEqual(result["qc_expectations"]["duration_in_frames"], 78)
        self.assertEqual(result["timeline"]["renderConfig"]["durationInFrames"], 78)

    def test_invalid_word_timing_is_rejected(self) -> None:
        for field, invalid in [("start", math.nan), ("end", math.inf), ("start", True),
                               ("end", False), ("start", -1), ("end", 0.1), ("end", 4)]:
            with self.subTest(field=field, invalid=invalid):
                original = source()
                original["words"][0][field] = invalid
                with self.assertRaises(ValueError):
                    self.prepare(sources=[original])
        original = source()
        original["words"][4]["start"] = 0.6
        with self.assertRaises(ValueError):
            self.prepare(sources=[original])

    def test_invalid_source_identity_and_empty_input_is_rejected(self) -> None:
        for changes in ({"sources": []}, {"segments": []}, {"sources": [source(), source()]},
                        {"plan_summary": " "}, {"title": " "}, {"fps": True}, {"fps": 61},
                        {"grade": "cinematic"}, {"subtitles": "yes"}, {"aspect_ratio": "4:3"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.prepare(**changes)
        for field, invalid in [("id", ""), ("url", ""), ("duration_seconds", math.nan),
                               ("duration_seconds", True), ("words", [])]:
            original = source()
            original[field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.prepare(sources=[original])

    def test_invalid_ranges_and_arbitrary_time_cuts_are_rejected(self) -> None:
        for changes in ({"source_id": "missing"}, {"first_word": True}, {"last_word": False},
                        {"first_word": -1}, {"last_word": 99}, {"first_word": 2, "last_word": 1},
                        {"first_word": 1.5}, {"padding_seconds": 0.01}, {"padding_seconds": 0.3},
                        {"padding_seconds": math.nan}, {"padding_seconds": math.inf},
                        {"padding_seconds": True}, {"start_seconds": 0.5}):
            segment = {"source_id": "interview", "first_word": 1, "last_word": 1, **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.prepare(segments=[segment])

    def test_committed_schema_matches_provider_and_describes_word_indices(self) -> None:
        self.assertEqual(load_committed_schemas(get_provider("remotion")),
                         generate_schemas(get_provider("remotion")))
        schema = schema_for("prepare_conversational_edit")
        self.assertIn("plan_summary", schema["required"])
        self.assertIn("type=word", schema["properties"]["segments"]["description"])
        self.assertEqual(schema["properties"]["sources"]["items"]["required"],
                         ["id", "url", "duration_seconds", "words"])
        self.assertEqual(schema["properties"]["sources"]["items"]["properties"]["words"]
                         ["items"]["required"], ["text", "start", "end"])
        self.assertNotIn("confirmed", schema["properties"])
        self.assertNotIn("live", schema["properties"])

    def test_prepare_contract_rejects_invalid_nested_timing_before_dispatch(self) -> None:
        schema = schema_for("prepare_conversational_edit")
        arguments = proposal()
        arguments["sources"][0]["words"][2]["end"] = math.nan
        with self.assertRaises(ValueError):
            validate_tool_arguments("remotion", "prepare_conversational_edit", arguments, schema)

    def test_existing_render_contract_accepts_subtitles_grade_and_audio_fades(self) -> None:
        arguments = {"title": "Cut", "visuals": [{"kind": "video", "url": "https://example.test/a.mp4",
                     "duration_seconds": 1, "grade": "neutral", "audio_fade_in_seconds": 0.03,
                     "audio_fade_out_seconds": 0.03}],
                     "subtitles": [{"text": "Hello", "start_seconds": 0.1, "duration_seconds": 0.5}]}
        validated = validate_tool_arguments("remotion", "render_timeline", arguments,
                                            schema_for("render_timeline"))
        self.assertEqual(validated, arguments)
        props = api.build_timeline_props(**arguments)
        self.assertEqual(props["document"]["tracks"][-1]["name"], "Subtitles")
        self.assertEqual(props["document"]["tracks"][0]["items"][0]["grade"], "neutral")

    def test_legacy_title_zero_fades_use_defaults_and_subtitle_zero_fades_stay_zero(self) -> None:
        text = {"text": "Hello", "start_seconds": 0, "duration_seconds": 1,
                "fade_in_seconds": 0, "fade_out_seconds": 0}
        props = api.build_timeline_props("Cut", [{"kind": "video", "url": "https://example.test/a.mp4",
                                                   "duration_seconds": 2}],
                                         text_overlays=[text], subtitles=[text])
        titles, subtitles = props["document"]["tracks"][-2:]
        self.assertEqual(titles["items"][0]["fadeIn"], 0.2)
        self.assertEqual(titles["items"][0]["fadeOut"], 0.2)
        self.assertEqual(subtitles["items"][0]["fadeIn"], 0)
        self.assertEqual(subtitles["items"][0]["fadeOut"], 0)

    def test_render_contract_rejects_invalid_grade_fades_and_subtitles(self) -> None:
        schema = schema_for("render_timeline")
        base = {"title": "Cut", "visuals": [{"kind": "video", "url": "https://example.test/a.mp4",
                                               "duration_seconds": 1}]}
        for field, invalid in [("grade", "cinematic"), ("audio_fade_in_seconds", -0.1),
                               ("audio_fade_out_seconds", 2), ("audio_fade_in_seconds", math.nan),
                               ("audio_fade_out_seconds", math.inf), ("audio_fade_in_seconds", True)]:
            arguments = copy.deepcopy(base)
            arguments["visuals"][0][field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                validate_tool_arguments("remotion", "render_timeline", arguments, schema)
        for changes in ({"text": " "}, {"start_seconds": -1}, {"duration_seconds": 0},
                        {"start_seconds": math.nan}, {"duration_seconds": math.inf},
                        {"position": "side"}, {"font_size": True}, {"fade_in_seconds": 2},
                        {"font_size": 1}, {"font_weight": 999}):
            arguments = copy.deepcopy(base)
            arguments["subtitles"] = [{"text": "Hello", "start_seconds": 0,
                                       "duration_seconds": 0.5, **changes}]
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_tool_arguments("remotion", "render_timeline", arguments, schema)


if __name__ == "__main__":
    unittest.main()
