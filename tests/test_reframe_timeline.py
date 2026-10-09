from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from providers.contracts import validate_remotion_timeline_arguments
from providers.remotion import api, local


class ReframeTimelineContractTests(unittest.TestCase):
    def visual(self, **fields):
        return {"kind": "video", "url": "master.mp4", "duration_seconds": 1,
                "source_fps": 24, **fields}

    def test_crop_window_survives_document_normalization(self):
        box = {"x": 0, "y": 0, "width": 144, "height": 180}
        props = api.build_timeline_props("Crop", [self.visual(crop_box=box,
            reframe_size={"width": 144, "height": 180})], aspect_ratio="4:5", measure_local=False)
        self.assertEqual(props["document"]["tracks"][0]["items"][0].get("cropBox"), box)
        self.assertEqual((props["renderConfig"]["width"], props["renderConfig"]["height"]), (144, 180))

    def test_lambda_refuses_crop_and_pad_before_aws_including_dry_run(self):
        for enabled in ("true", "false"):
            for fields in ({"crop_box": {"x": 0, "y": 0, "width": 144, "height": 180}},
                           {"fit": "pad_blur"}):
                with self.subTest(dry_run=enabled, fields=fields), patch.dict(os.environ, {
                    "REMOTION_RENDER_BACKEND": "lambda", "REMOTION_DRY_RUN": enabled}), \
                        patch.object(api, "load_remotion_settings", side_effect=AssertionError("AWS access")), \
                        self.assertRaisesRegex(ValueError, "reframing.*local"):
                    api.render_timeline("Crop", [self.visual(**fields)])

    def test_lambda_refuses_normalized_reframe_document(self):
        props = {"document": {"tracks": [{"items": [{"type": "clip", "fit": "pad_blur"}]}]}}
        with patch.object(api, "load_remotion_settings", side_effect=AssertionError("AWS access")), \
                self.assertRaisesRegex(ValueError, "reframing.*local"):
            api._start_lambda_render(props, output_filename="crop.mp4")

    def test_crop_box_parameter_boundaries(self):
        for box in ({"x": -2, "y": 0, "width": 144, "height": 180},
                    {"x": 0, "y": 0, "width": 143, "height": 180},
                    {"x": 0, "y": 0, "width": 0, "height": 180},
                    {"x": float("nan"), "y": 0, "width": 144, "height": 180},
                    {"x": 0, "y": 0, "width": 144, "height": 180, "args": "-vf"}):
            with self.subTest(box=box), self.assertRaises(ValueError):
                validate_remotion_timeline_arguments({"visuals": [self.visual(crop_box=box)]})

    def test_reframe_canvas_requires_crop_or_blur_and_consistent_primary_size(self):
        for visuals in ([self.visual(reframe_size={"width": 144, "height": 180})],
                        [self.visual(fit="pad_blur", reframe_size={"width": 144, "height": 180}),
                         self.visual(fit="pad_blur", reframe_size={"width": 288, "height": 360})]):
            with self.subTest(visuals=visuals), self.assertRaises(ValueError):
                api.build_timeline_props("Bad canvas", visuals, aspect_ratio="4:5", measure_local=False)

    def test_pad_foreground_box_survives_and_requires_blurred_padding(self):
        box = {"x": 10, "y": 60, "width": 80, "height": 44}
        props = api.build_timeline_props("Safe pad", [self.visual(fit="pad_blur", pad_box=box,
            reframe_size={"width": 100, "height": 178})], aspect_ratio="9:16", measure_local=False)
        self.assertEqual(props["document"]["tracks"][0]["items"][0].get("padBox"), box)
        with self.assertRaises(ValueError):
            validate_remotion_timeline_arguments({"visuals": [self.visual(pad_box=box)]})


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
class ReframeTimelineRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "master.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
            "color=c=red:s=320x180:r=24:d=1,drawbox=x=160:y=0:w=160:h=180:color=blue:t=fill",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
            "-threads", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(cls.source)], check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        env = patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "local", "REMOTION_DRY_RUN": "false",
                                      "RENDERHAUS_MEDIA_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def visual(self, **fields):
        return {"kind": "video", "output_path": str(self.source), "duration_seconds": 1, **fields}

    def render(self, visuals, aspect="1:1"):
        props = api.build_timeline_props("Reframe", visuals, aspect_ratio=aspect)
        result = api.render_timeline_and_wait(props, output_filename="reframe.mp4",
                                             poll_interval_seconds=.05, timeout_seconds=30)
        self.assertEqual(result["status"], "succeeded", result)
        return Path(result["output_path"]), props, result

    @staticmethod
    def pixel(path, time, x, y):
        raw = subprocess.check_output(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-ss", str(time),
            "-i", str(path), "-vf", f"format=rgb24,crop=1:1:{x}:{y}:exact=1", "-frames:v", "1",
            "-threads", "1", "-f", "rawvideo", "pipe:1"], timeout=30)
        return tuple(raw)

    def test_per_shot_static_windows_change_only_at_cut_and_preserve_audio_fps_sar(self):
        visuals = [self.visual(duration_seconds=.5, source_in_seconds=0,
                    crop_box={"x": 0, "y": 0, "width": 180, "height": 180},
                    reframe_size={"width": 180, "height": 180}),
                   self.visual(duration_seconds=.5, source_in_seconds=.5,
                    crop_box={"x": 140, "y": 0, "width": 180, "height": 180},
                    reframe_size={"width": 180, "height": 180})]
        path, props, result = self.render(visuals)
        probe = local._probe(path)
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (180, 180))
        self.assertEqual(video["sample_aspect_ratio"], "1:1")
        self.assertEqual(video["avg_frame_rate"], "24/1")
        self.assertTrue(any(s["codec_type"] == "audio" for s in probe["streams"]))
        self.assertEqual(result["source_resolution"], "320x180")
        self.assertFalse(result["upscaled"])
        for time in (.1, .4):
            red, _, blue = self.pixel(path, time, 90, 90)
            self.assertGreater(red, blue + 150)
        red, _, blue = self.pixel(path, .75, 90, 90)
        self.assertGreater(blue, red + 150)
        self.assertEqual(props["renderConfig"]["durationInFrames"], 24)

    def test_blurred_padding_keeps_the_whole_foreground(self):
        path, _, _ = self.render([self.visual(fit="pad_blur", reframe_size={"width": 100, "height": 178})], "9:16")
        video = next(s for s in local._probe(path)["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (100, 178))
        red, _, blue = self.pixel(path, .4, 10, 89)
        self.assertGreater(red, blue + 150)
        red, _, blue = self.pixel(path, .4, 90, 89)
        self.assertGreater(blue, red + 150)

    def test_safe_zone_foreground_box_keeps_both_sides_inside_the_viewport(self):
        path, _, _ = self.render([self.visual(fit="pad_blur", pad_box={"x": 10, "y": 60,
            "width": 80, "height": 44}, reframe_size={"width": 100, "height": 178})], "9:16")
        red, _, blue = self.pixel(path, .4, 14, 82)
        self.assertGreater(red, blue + 150)
        red, _, blue = self.pixel(path, .4, 86, 82)
        self.assertGreater(blue, red + 150)

    def test_crop_outside_measured_source_is_refused_before_worker(self):
        with self.assertRaisesRegex(ValueError, "crop.*source"):
            api.build_timeline_props("Bad crop", [self.visual(crop_box={"x": 200, "y": 0,
                "width": 180, "height": 180})])

    def test_upscale_requires_allowance_and_reports_no_added_detail(self):
        visual = self.visual(crop_box={"x": 0, "y": 0, "width": 180, "height": 180},
                             reframe_size={"width": 360, "height": 360})
        with self.assertRaisesRegex(ValueError, "allow_upscale"):
            api.build_timeline_props("Upscale", [visual], aspect_ratio="1:1")
        visual["allow_upscale"] = True
        _, _, result = self.render([visual])
        self.assertTrue(result["upscaled"])
        self.assertTrue(any("no added detail" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
