from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from providers.ffmpeg import api, ops


class FinishingFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = self.root / "finishing"
        self.job.mkdir()
        self.source = self.job / "source.mp4"
        self.source.write_bytes(b"invalid media")
        self.env = patch.dict("os.environ", {"RENDERHAUS_MEDIA_DIR": str(self.root),
                                             "FFMPEG_DRY_RUN": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cues = [{"start": .125, "end": 1.875, "text": "Café 世界"}]
        self.subtitle = self.job / "captions.srt"
        self.subtitle.write_text("1\n00:00:00,800 --> 00:00:02,200\nHELLO café\n", encoding="utf-8")

    def call(self, op, params=None, input_path="source.mp4"):
        return api.ffmpeg_tool(op, "finishing", input_path, params)

    def exported(self, result):
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["estimated_cost_usd"], 0)
        paths = []
        for output in result["outputs"]:
            path = Path(output["path"])
            self.assertTrue(path.is_relative_to(self.job))
            self.assertRegex(path.name, r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
            self.assertEqual(output["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(output["bytes"], path.stat().st_size)
            paths.append(path)
        return paths


class FinishingContractTests(FinishingFixture, unittest.TestCase):
    def test_export_srt_has_exact_milliseconds_unicode_and_no_media_dependency(self):
        with patch("providers.ffmpeg.api._bounded_run", side_effect=AssertionError("No binary")):
            result = self.call("export_srt", {"cues": self.cues}, input_path="unused.mp4")
        output = self.exported(result)[0]
        self.assertEqual(output.read_text(), "1\n00:00:00,125 --> 00:00:01,875\nCafé 世界\n\n")
        self.assertIsNone(result["ffmpeg_version"])

    def test_export_batch_writes_two_independent_srt_files(self):
        result = self.call("export_srt", {"cues": self.cues,
            "export_batch": [{"cues": [{"start": 2, "end": 3, "text": "Second"}]}]})
        outputs = self.exported(result)
        self.assertEqual(len(outputs), 2)
        self.assertIn("00:00:02,000 --> 00:00:03,000\nSecond", outputs[1].read_text())

    def test_export_refuses_invalid_cues_before_writing_any_batch_output(self):
        invalid = [[], [{"start": 1, "end": 1, "text": "zero"}],
                   [{"start": 0, "end": .0001, "text": "tiny"}],
                   [{"start": float("nan"), "end": 1, "text": "nan"}],
                   [{"start": 0, "end": float("inf"), "text": "inf"}],
                   [{"start": False, "end": 1, "text": "bool"}],
                   [{"start": 0, "end": 601, "text": "long"}],
                   [{"start": 0, "end": 1, "text": "empty\n\ncue"}],
                   [{"start": 0, "end": 1, "text": "nul\x00"}],
                   [{"start": 0, "end": 1, "text": "x" * 2001}],
                   [{"start": 0, "end": 2, "text": "first"},
                    {"start": 1, "end": 3, "text": "overlap"}],
                   [{"start": 2, "end": 3, "text": "first"},
                    {"start": 0, "end": 1, "text": "unsorted"}]]
        for cues in invalid:
            with self.subTest(cues=cues):
                result = self.call("export_srt", {"cues": self.cues,
                                                   "export_batch": [{"cues": cues}]})
                self.assertFalse(result["ok"], result)
                self.assertEqual(list(self.job.glob("*.srt")), [self.subtitle])

    def test_export_batch_limit_counts_the_primary_item(self):
        result = self.call("export_srt", {"cues": self.cues,
            "export_batch": [{"cues": self.cues}] * 5})
        self.assertFalse(result["ok"], result)
        self.assertEqual(list(self.job.glob("*.srt")), [self.subtitle])

    def test_export_refuses_whitespace_blank_lines(self):
        for whitespace in (" ", "\t", "\u00a0"):
            with self.subTest(whitespace=repr(whitespace)):
                result = self.call("export_srt", {"cues": [
                    {"start": 0, "end": 1, "text": "first\n" + whitespace + "\nsecond"}]})
                self.assertFalse(result["ok"], result)

    def test_dry_run_validates_new_operations_without_reading_files_or_running_binaries(self):
        cases = [("burn_subtitles", {"subtitle_path": "missing.srt"}),
                 ("export_srt", {"cues": self.cues}),
                 ("color_match_lut", {"lut_path": "missing.cube"}),
                 ("audio_cleanup", {}), ("make_proxy", {})]
        with patch.dict("os.environ", {"FFMPEG_DRY_RUN": "true"}), \
                patch("providers.ffmpeg.api.input_file", side_effect=AssertionError("No reads")), \
                patch("providers.ffmpeg.api._bounded_run", side_effect=AssertionError("No binary")):
            for op, params in cases:
                with self.subTest(op=op):
                    result = self.call(op, params, input_path="missing.mp4")
                    self.assertTrue(result["ok"], result)
                    self.assertEqual(result["status"], "dry_run")
                    self.assertEqual(result["outputs"], [])

    def test_dry_run_refuses_every_secondary_path_escape(self):
        outside = self.root / "outside.srt"
        outside.write_text("outside")
        (self.job / "escape.srt").symlink_to(outside)
        bad = ["../outside.srt", str(outside), "https://example.com/a.srt", "-captions.srt",
               "captions.srt\n", "capti\u043ens.srt", "escape.srt"]
        with patch.dict("os.environ", {"FFMPEG_DRY_RUN": "true"}):
            for value in bad:
                for op, params in [("burn_subtitles", {"subtitle_path": value}),
                                   ("burn_subtitles", {"subtitle_path": "captions.srt",
                                    "subtitle_batch": [{"input_path": value,
                                                         "subtitle_path": "captions.srt"}]}),
                                   ("color_match_lut", {"lut_path": value})]:
                    with self.subTest(op=op, value=value):
                        self.assertFalse(self.call(op, params)["ok"])

    def test_fixed_finishing_parameters_refuse_commands_style_injection_and_nonfinite_values(self):
        cases = [("burn_subtitles", {"subtitle_path": "captions.srt", "font_id": "DejaVu Sans,/etc/passwd"}),
                 ("burn_subtitles", {"subtitle_path": "captions.srt", "colour": "#FFFFFF,Fontname=x"}),
                 ("burn_subtitles", {"subtitle_path": "captions.srt", "font_size": 999999}),
                 ("burn_subtitles", {"subtitle_path": "captions.srt", "outline": float("nan")}),
                 ("color_match_lut", {"intensity": float("inf")}),
                 ("color_match_lut", {"intensity": True}),
                 ("color_match_lut", {"contrast": 1e99}),
                 ("audio_cleanup", {"highpass_hz": 1e99}),
                 ("audio_cleanup", {"denoise_db": 0}),
                 ("audio_cleanup", {"compressor_ratio": float("nan")}),
                 ("make_proxy", {"height": 481}),
                 ("make_proxy", {"crf": True}),
                 ("make_proxy", {"proxy_preset": "veryfast;touch /tmp/x"})]
        with patch.dict("os.environ", {"FFMPEG_DRY_RUN": "true"}):
            for op, params in cases:
                with self.subTest(op=op, params=params):
                    self.assertFalse(self.call(op, params)["ok"])
            for op in ("burn_subtitles", "export_srt", "color_match_lut", "audio_cleanup", "make_proxy"):
                result = self.call(op, {"filtergraph": "movie=https://example.com/x"})
                self.assertFalse(result["ok"], result)

    def test_gateway_schema_and_runtime_accept_the_same_finishing_arguments(self):
        from jsonschema import ValidationError, validate

        schema = ops.tool_schema()["inputSchema"]
        base = {"job_id": "finishing", "input_path": "source.mp4"}
        cases = [("burn_subtitles", {"subtitle_path": "captions.srt"}),
                 ("export_srt", {"cues": self.cues}),
                 ("color_match_lut", {"grade_preset": "warm", "intensity": .5}),
                 ("audio_cleanup", {"compressor": True}),
                 ("make_proxy", {"height": 480, "proxy_preset": "fast"})]
        for op, params in cases:
            with self.subTest(op=op):
                self.assertTrue(op in ops.OPS, f"Missing finishing operation {op}")
                validate({**base, "op": op, "params": params}, schema)
                api.validate_arguments({**base, "op": op, "params": params})
        with self.assertRaises(ValidationError):
            validate({**base, "op": "make_proxy", "params": {"height": 481}}, schema)

    def test_proxy_height_contract_keeps_existing_contact_sheet_schema_valid(self):
        from jsonschema import validate

        validate({"op": "contact_sheet", "job_id": "finishing", "input_path": "source.mp4",
                  "params": {"width": 320, "height": 180}}, ops.tool_schema()["inputSchema"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
class FinishingRealBinaryTests(FinishingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.run_ffmpeg(["-f", "lavfi", "-i", "color=c=0x204060:size=320x180:rate=24:duration=4",
                         "-f", "lavfi", "-i", "aevalsrc=0.25*sin(2*PI*50*t)+0.15*sin(2*PI*1000*t):s=48000:d=4",
                         "-c:v", "libx264", "-threads", "1", "-crf", "18", "-c:a", "aac",
                         "-shortest", "-movflags", "+faststart", str(self.source)])

    def run_ffmpeg(self, args):
        return subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", *args],
                              check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)

    def frame(self, path, time=1):
        from PIL import Image

        raw = self.run_ffmpeg(["-i", str(path), "-ss", str(time), "-frames:v", "1", "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "-threads", "1", "-"]).stdout
        size = self.call("probe", input_path=path.name)["metrics"]["streams"][0]
        return Image.frombytes("RGB", (size["width"], size["height"]), raw)

    def cube(self, name="identity.cube", invert=False):
        lines = ["TITLE \"generated test LUT\"", "LUT_3D_SIZE 2", "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
        for blue in (0, 1):
            for green in (0, 1):
                for red in (0, 1):
                    values = (red, green, blue)
                    lines.append(" ".join(str(1 - value if invert else value) for value in values))
        path = self.job / name
        path.write_text("\n".join(lines) + "\n")
        return path

    def test_subtitles_change_pixels_only_during_the_cue(self):
        from PIL import ImageChops, ImageStat

        result = self.call("burn_subtitles", {"subtitle_path": self.subtitle.name})
        output = self.exported(result)[0]
        differences = []
        for time in (.4, 1.4):
            delta = ImageChops.difference(self.frame(self.source, time), self.frame(output, time))
            differences.append(sum(ImageStat.Stat(delta.crop((0, 100, 320, 180))).mean) / 3)
        self.assertLess(differences[0], 2)
        self.assertGreater(differences[1], 5)
        self.assertEqual(result["metrics"]["source_resolution"], {"width": 320, "height": 180})

    def test_restricted_ass_preserves_dialogue_and_uses_selected_font(self):
        self.subtitle = self.job / "captions.ass"
        self.subtitle.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,DejaVu Sans,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.80,0:00:02.20,Default,,0,0,0,,ASS caption\n")
        result = self.call("burn_subtitles", {"subtitle_path": self.subtitle.name, "font_id": "dejavu_serif"})
        self.assertEqual(len(self.exported(result)), 1)

    def test_subtitle_batch_is_atomic_when_second_render_fails(self):
        second = self.job / "second.mp4"
        shutil.copyfile(self.source, second)
        run = api._bounded_run

        def fail_second(argv, directory, timeout, **kwargs):
            if "./second.mp4" in argv and "-vf" in argv:
                return api.ProcessResult(1, b"", b"test render failure")
            return run(argv, directory, timeout, **kwargs)

        before = set(self.job.iterdir())
        with patch("providers.ffmpeg.api._bounded_run", side_effect=fail_second):
            result = self.call("burn_subtitles", {"subtitle_path": self.subtitle.name,
                "subtitle_batch": [{"input_path": second.name, "subtitle_path": self.subtitle.name}]})
        self.assertFalse(result["ok"], result)
        self.assertEqual(set(self.job.iterdir()), before)

    def test_subtitle_batch_produces_two_videos_without_sidecar_leaks(self):
        second = self.job / "second.mp4"
        shutil.copyfile(self.source, second)
        before = set(self.job.iterdir())
        result = self.call("burn_subtitles", {"subtitle_path": self.subtitle.name,
            "subtitle_batch": [{"input_path": second.name, "subtitle_path": self.subtitle.name}]})
        outputs = self.exported(result)
        self.assertEqual(len(outputs), 2)
        self.assertEqual(set(self.job.iterdir()) - before, set(outputs))

    def test_subtitle_font_overrides_attachments_and_drawing_are_refused(self):
        texts = ["{\\fn/etc/passwd}caption", "{\\p1}m 0 0 l 100 100", "<font face='/etc/passwd'>caption</font>"]
        for text in texts:
            with self.subTest(text=text):
                self.subtitle.write_text("1\n00:00:00,800 --> 00:00:02,200\n" + text + "\n")
                result = self.call("burn_subtitles", {"subtitle_path": self.subtitle.name})
                self.assertFalse(result["ok"], result)
        self.subtitle = self.job / "font.ass"
        self.subtitle.write_text("[Script Info]\nScriptType: v4.00+\n[Fonts]\nfontname: evil.ttf\nAAAA\n")
        self.assertFalse(self.call("burn_subtitles", {"subtitle_path": self.subtitle.name})["ok"])
        self.assertEqual(list(self.job.glob("subtitled-*.mp4")), [])

    def test_requested_font_size_and_colour_override_ass_styles(self):
        ass = self.job / "styled.ass"
        ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,DejaVu Sans,12,&H000000FF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,10,10,10,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.80,0:00:02.20,Default,,0,0,0,,HELLO\n")
        counts = []
        for size in (12, 48):
            output = self.exported(self.call("burn_subtitles", {"subtitle_path": ass.name,
                "font_size": size, "colour": "#00FF00", "outline": 0}))[0]
            counts.append(sum(green > 180 and red < 80 and blue < 80
                              for red, green, blue in self.frame(output).get_flattened_data()))
        self.assertGreater(counts[0], 10)
        self.assertGreater(counts[1], counts[0] * 4)

    def test_lut_identity_inversion_and_half_intensity_obey_numeric_relation(self):
        self.cube()
        self.cube("invert.cube", invert=True)
        outputs = []
        for lut, intensity in [("identity.cube", 1), ("invert.cube", 1), ("invert.cube", .5)]:
            outputs.append(self.exported(self.call("color_match_lut", {"lut_path": lut,
                                                                        "intensity": intensity}))[0])
        original = self.frame(self.source).getpixel((100, 50))
        identity, inverted, half = [self.frame(output).getpixel((100, 50)) for output in outputs]
        for before, same, inverse, midpoint in zip(original, identity, inverted, half):
            self.assertLessEqual(abs(before - same), 5)
            self.assertLessEqual(abs(inverse - (255 - before)), 7)
            self.assertLessEqual(abs(midpoint - (same + inverse) / 2), 6)

    def test_grade_preset_changes_pixels_without_a_lut(self):
        result = self.call("color_match_lut", {"grade_preset": "warm"})
        output = self.exported(result)[0]
        before, after = self.frame(self.source).getpixel((100, 50)), self.frame(output).getpixel((100, 50))
        self.assertGreater(after[0] - after[2], before[0] - before[2] + 5)

    def test_malformed_luts_are_refused_without_artifacts(self):
        malformed = ["LUT_3D_SIZE 999999\n", "LUT_3D_SIZE 2\n0 0 0\n", "LUT_3D_SIZE 2\n" + "nan 0 0\n" * 8,
                     "LUT_3D_SIZE 2\n" + "inf 0 0\n" * 8,
                     "LUT_3D_SIZE 2\nDOMAIN_MIN 1 0 0\nDOMAIN_MAX 0 1 1\n" + "0 0 0\n" * 8,
                     "LUT_3D_SIZE 2\nLUT_1D_SIZE 2\n" + "0 0 0\n" * 8,
                     "LUT_3D_SIZE 2\nINCLUDE /etc/passwd\n" + "0 0 0\n" * 8]
        lut = self.job / "bad.cube"
        for text in malformed:
            with self.subTest(text=text[:80]):
                lut.write_text(text)
                before = set(self.job.iterdir())
                self.assertFalse(self.call("color_match_lut", {"lut_path": lut.name})["ok"])
                self.assertEqual(set(self.job.iterdir()), before)

    def test_cleanup_wav_attenuates_low_hum_and_preserves_duration_channels(self):
        wav = self.job / "hum.wav"
        self.run_ffmpeg(["-f", "lavfi", "-i", "aevalsrc=0.25*sin(2*PI*50*t)+0.15*sin(2*PI*1000*t):s=48000:d=4",
                         "-c:a", "pcm_s16le", str(wav)])
        result = self.call("audio_cleanup", {"highpass_hz": 200, "denoise_db": 1,
                                              "eq_preset": "neutral"}, input_path=wav.name)
        output = self.exported(result)[0]
        self.assertEqual(output.suffix, ".wav")

        def amplitudes(path):
            with wave.open(str(path)) as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getframerate(), 48000)
                self.assertEqual(handle.getnframes(), 192000)
                samples = struct.unpack("<" + "h" * handle.getnframes(), handle.readframes(handle.getnframes()))
            middle = samples[48000:96000]
            return [abs(sum(sample * math.sin(2 * math.pi * hz * index / 48000)
                            for index, sample in enumerate(middle))) / len(middle) for hz in (50, 1000)]

        before, after = amplitudes(wav), amplitudes(output)
        self.assertLess(after[0] / before[0], .15)
        self.assertGreater(after[1] / before[1], .5)

    def test_cleanup_video_can_be_measured_then_normalized_from_the_cleaned_artifact(self):
        cleaned = self.exported(self.call("audio_cleanup", {"compressor": True}))[0]
        target = {"I": -16, "TP": -1.5, "LRA": 11}
        measured = self.call("measure_loudness", target, input_path=cleaned.name)
        self.assertTrue(measured["ok"], measured)
        names = {"measured_I": "input_i", "measured_TP": "input_tp", "measured_LRA": "input_lra",
                 "measured_thresh": "input_thresh", "offset": "target_offset"}
        params = {**target, **{name: measured["metrics"][field] for name, field in names.items()}}
        normalized = self.call("loudnorm_mux_aac", params, input_path=cleaned.name)
        self.exported(normalized)
        self.assertLessEqual(abs(normalized["metrics"]["after"]["integrated_lufs"] + 16), .5)

    def test_cleanup_refuses_video_without_audio(self):
        silent = self.job / "silent.mp4"
        self.run_ffmpeg(["-i", str(self.source), "-an", "-c:v", "copy", str(silent)])
        result = self.call("audio_cleanup", input_path=silent.name)
        self.assertFalse(result["ok"], result)
        self.assertIn("audio", result["error"])

    def test_proxy_reports_actual_dimensions_cadence_source_hash_and_faststart(self):
        result = self.call("make_proxy", {"height": 480, "crf": 30})
        output = self.exported(result)[0]
        metadata = result["metrics"]
        self.assertEqual((metadata["width"], metadata["height"]), (320, 180))
        self.assertEqual(metadata["source_resolution"], {"width": 320, "height": 180})
        self.assertEqual(metadata["source_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(metadata["source_fps"], "24/1")
        self.assertTrue(metadata["faststart"])
        self.assertFalse(metadata["upscaled"])
        probe = metadata.get("output_probe")
        self.assertIsInstance(probe, dict, "The actual structured proxy probe must be reported")
        video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (320, 180))
        self.assertEqual(video["avg_frame_rate"], "24/1")
        self.assertTrue(output.name.startswith("source-proxy-"), output.name)
        self.assertTrue(metadata["is_proxy"])

    def test_proxy_downsizes_to_selected_height_and_never_overwrites(self):
        large = self.job / "large.mp4"
        self.run_ffmpeg(["-f", "lavfi", "-i", "color=size=1280x720:rate=24:duration=1",
                         "-c:v", "libx264", "-threads", "1", str(large)])
        results = [self.call("make_proxy", {"height": height}, input_path=large.name) for height in (480, 540)]
        paths = [self.exported(result)[0] for result in results]
        self.assertNotEqual(paths[0], paths[1])
        self.assertEqual([(result["metrics"]["width"], result["metrics"]["height"]) for result in results],
                         [(852, 480), (960, 540)])
        self.assertTrue(all(path.exists() for path in paths))

    def test_missing_binary_filter_or_font_fails_soft_and_removes_owned_files(self):
        with patch("providers.ffmpeg.api.shutil.which", return_value=None):
            result = self.call("make_proxy")
        self.assertFalse(result["ok"])
        self.assertIn("local", result["error"])
        self.assertTrue("burn_subtitles" in ops.OPS, "Missing subtitle operation")
        from providers.ffmpeg import finishing

        with patch.dict(finishing.FONTS, {"dejavu_sans": ("DejaVu Sans", self.job / "missing.ttf")}):
            result = self.call("burn_subtitles", {"subtitle_path": self.subtitle.name})
        self.assertFalse(result["ok"])
        self.assertIn("font", result["error"].lower())
        run = api._bounded_run

        def missing_filter(argv, directory, timeout, **kwargs):
            if "-filters" in argv:
                return api.ProcessResult(0, b"Filters:\n", b"")
            return run(argv, directory, timeout, **kwargs)

        with patch("providers.ffmpeg.api._bounded_run", side_effect=missing_filter):
            result = self.call("burn_subtitles", {"subtitle_path": self.subtitle.name})
        self.assertFalse(result["ok"])
        self.assertIn("filter", result["error"].lower())
        self.assertEqual(list(self.job.glob("subtitled-*.mp4")), [])

    def test_size_cap_truncation_fails_instead_of_claiming_a_complete_artifact(self):
        self.assertTrue("make_proxy" in ops.OPS, "Missing proxy operation")
        from providers.ffmpeg import finishing

        before = set(self.job.iterdir())
        with patch.object(finishing, "MAX_OUTPUT_BYTES", 1024):
            result = self.call("make_proxy")
        self.assertFalse(result["ok"], result)
        self.assertEqual(set(self.job.iterdir()), before)

    def test_concurrent_subtitle_runs_have_distinct_outputs_and_no_sidecars(self):
        before = set(self.job.iterdir())
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.call("burn_subtitles", {"subtitle_path": self.subtitle.name}), range(3)))
        paths = [self.exported(result)[0] for result in results]
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual(set(self.job.iterdir()) - before, set(paths))

    def test_sidecar_creation_race_preserves_the_preexisting_collision(self):
        self.assertTrue("burn_subtitles" in ops.OPS, "Missing subtitle operation")
        from providers.ffmpeg import finishing

        original = finishing.output_file
        collisions = []

        def create_collision(directory, prefix, suffix):
            path = original(directory, prefix, suffix)
            if suffix == ".ass":
                path.write_bytes(b"preexisting collision")
                collisions.append(path)
            return path

        with patch.object(finishing, "output_file", side_effect=create_collision):
            result = self.call("burn_subtitles", {"subtitle_path": self.subtitle.name})
        self.assertFalse(result["ok"], result)
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].read_bytes(), b"preexisting collision")
        self.assertEqual(list(self.job.glob("subtitled-*.mp4")), [])


if __name__ == "__main__":
    unittest.main()
