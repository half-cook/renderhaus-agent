from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from providers.remotion import api, local
from providers.catalog import PROVIDERS_BY_ID
from providers.registry import dispatch, generate_schemas, load_committed_schemas


class CanvasPolicyTests(unittest.TestCase):
    def test_native_canvas_uses_largest_video_short_edge(self) -> None:
        for aspect, sources, expected in (
            ("16:9", [(1280, 720)], (1280, 720)),
            ("16:9", [(1920, 1080)], (1920, 1080)),
            ("16:9", [(1280, 720), (1920, 1080)], (1920, 1080)),
            ("9:16", [(720, 1280)], (720, 1280)),
            ("16:9", [(3840, 2160)], (1920, 1080)),
            ("1:1", [(720, 1280)], (720, 720)),
            ("16:9", [(1281, 721)], (1280, 720)),
            ("2.39:1", [(1280, 720)], (1718, 720)),
        ):
            with self.subTest(aspect=aspect, sources=sources):
                self.assertEqual(api.choose_canvas(aspect, sources), expected)

    def test_explicit_resolution_scales_the_aspect_table(self) -> None:
        for aspect, resolution, expected in (
            ("16:9", "720p", (1280, 720)),
            ("16:9", "1080p", (1920, 1080)),
            ("16:9", "1440p", (2560, 1440)),
            ("16:9", "2160p", (3840, 2160)),
            ("9:16", "720p", (720, 1280)),
            ("9:16", "2160p", (2160, 3840)),
            ("1:1", "720p", (720, 720)),
            ("2.39:1", "1080p", (1920, 804)),
        ):
            with self.subTest(aspect=aspect, resolution=resolution):
                self.assertEqual(api.choose_canvas(aspect, [(1920, 1080)], resolution), expected)

    def test_no_measurements_use_the_aspect_table(self) -> None:
        for aspect, expected in (("16:9", (1920, 1080)), ("9:16", (1080, 1920)),
                                 ("1:1", (1080, 1080)), ("2.39:1", (1920, 804))):
            with self.subTest(aspect=aspect):
                self.assertEqual(api.choose_canvas(aspect, []), expected)

    def test_invalid_output_resolution_rejected_before_render(self) -> None:
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "false"}), \
                patch.object(api, "_start_render", side_effect=AssertionError("render started")):
            with self.assertRaises(ValueError):
                dispatch("remotion", "render_timeline", {
                    "title": "Invalid", "visuals": [{"kind": "image",
                        "url": "https://example.test/still.png", "duration_seconds": 1}],
                    "output_resolution": "8K",
                })

    def test_gateway_resolution_argument_is_optional_and_matches_signature(self) -> None:
        spec = PROVIDERS_BY_ID["remotion"]
        generated = generate_schemas(spec)
        self.assertEqual(generated, load_committed_schemas(spec))
        schema = next(tool["inputSchema"] for tool in generated if tool["name"] == "render_timeline")
        self.assertNotIn("output_resolution", schema["required"])
        self.assertEqual(schema["properties"]["output_resolution"]["enum"],
                         ["source", "720p", "1080p", "1440p", "2160p"])
        for path in ("docs/LOCAL_ASSEMBLY.md", "docs/DEEP_AGENT.md",
                     "agent/deep_agent/skills/final-assembly/SKILL.md"):
            with self.subTest(path=path):
                self.assertIn("output_resolution", Path(path).read_text())


class ResolutionMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / "video.mp4"
        self.source.write_bytes(b"mock probe source")
        env = patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def props(self, *, size=(1280, 720), fit="cover", **arguments) -> dict:
        stream = {"codec_type": "video", "avg_frame_rate": "24/1", "bit_rate": "1000000"}
        if size:
            stream.update(width=size[0], height=size[1])
        with patch.object(local, "_probe", return_value={"streams": [stream]}):
            return api.build_timeline_props("Measured source", [{
                "kind": "video", "output_path": str(self.source), "duration_seconds": 1,
                "fit": fit,
            }], aspect_ratio="16:9", **arguments)

    def test_smaller_canvas_caps_preserved_target_bitrate_at_source(self) -> None:
        config = self.props()["renderConfig"]
        self.assertEqual((config["width"], config["height"]), (1280, 720))
        self.assertEqual(config["fps"], 24)
        self.assertLessEqual(config["videoBitrate"], 1_000_000)
        self.assertIsNone(config["crf"])

    def test_full_canvas_retains_existing_bitrate_floor(self) -> None:
        self.assertEqual(self.props(size=(1920, 1080))["renderConfig"]["videoBitrate"], 1_250_000)

    def test_unmeasurable_dimensions_fall_back_with_visible_warning(self) -> None:
        config = self.props(size=None)["renderConfig"]
        self.assertEqual((config["width"], config["height"]), (1920, 1080))
        self.assertIsNone(config["resolution"]["source_resolution"])
        self.assertFalse(config["resolution"]["upscaled"])
        self.assertIn("could not be measured", " ".join(config["resolution"]["warnings"]))

    def test_unprobed_remote_source_falls_back(self) -> None:
        props = api.build_timeline_props("Remote", [{"kind": "video",
            "url": "https://example.test/source.mp4", "duration_seconds": 1, "source_fps": 24}])
        self.assertEqual(props["renderConfig"]["width"], 1080)
        self.assertIsNone(props["renderConfig"]["resolution"]["source_resolution"])
        self.assertTrue(props["renderConfig"]["resolution"]["warnings"])

    def test_images_only_use_table_canvas_and_crf(self) -> None:
        props = api.build_timeline_props("Still", [{"kind": "image",
            "url": "https://example.test/still.png", "duration_seconds": 1}], aspect_ratio="16:9")
        self.assertEqual((props["renderConfig"]["width"], props["renderConfig"]["height"]), (1920, 1080))
        self.assertEqual(props["renderConfig"]["crf"], 18)
        self.assertFalse(props["renderConfig"]["resolution"]["upscaled"])
        self.assertEqual(props["renderConfig"]["resolution"]["warnings"], [])

    def test_cover_and_contain_report_actual_scaling_for_changed_aspect(self) -> None:
        for fit, expected in (("cover", True), ("contain", False)):
            with self.subTest(fit=fit):
                config = self.props(size=(720, 720), fit=fit)["renderConfig"]
                self.assertEqual(config["resolution"]["upscaled"], expected)

    def test_lambda_submit_and_stateless_poll_retain_resolution_warning(self) -> None:
        import io
        from remotion_lambda.models import RenderMediaProgress

        objects = {}
        s3 = Mock()
        s3.put_object.side_effect = lambda **kwargs: objects.update({kwargs["Key"]: kwargs["Body"]})
        s3.get_object.side_effect = lambda **kwargs: {"Body": io.BytesIO(objects[kwargs["Key"]])}
        session = Mock()
        session.client.return_value = s3
        s3.generate_presigned_url.return_value = "https://example.test/final.mp4"
        client = Mock()
        client.render_media_on_lambda.return_value = Mock(render_id="resolution-test", bucket_name="bucket")
        client.get_render_progress.return_value = RenderMediaProgress(
            done=True, outKey="renders/resolution-test/final.mp4", overallProgress=1,
            renderMetadata={"dimensions": {"width": 1920, "height": 1080}},
        )
        props = self.props(output_resolution="1080p")
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "false", "REMOTION_RENDER_BACKEND": "lambda"}), \
                patch.object(api, "load_remotion_settings", return_value=api.RemotionSettings(
                    "us-east-1", "function", "https://example.test/site", "bucket")), \
                patch.object(api.boto3, "Session", return_value=session), \
                patch.object(api, "_prepare_input_props", side_effect=lambda props, **_: props), \
                patch.object(api, "RemotionClient", return_value=client):
            started = api._start_render(props, output_filename="final.mp4")
            finished = api.get_render_progress(started["render_id"], started["bucket_name"], download=False)
        for result in (started, finished):
            self.assertEqual((result["width"], result["height"]), (1920, 1080))
            self.assertEqual(result["source_resolution"], "1280x720")
            self.assertTrue(result["upscaled"])
            warning = " ".join(result["warnings"])
            self.assertIn("upscaled from 1280x720", warning)
            self.assertIn("no added detail", warning)
            self.assertIn("Topaz", warning)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class AssemblyResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        cls.sources = {}
        for width, height in ((1280, 720), (1920, 1080), (720, 1280)):
            path = cls.root / f"source-{width}x{height}.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                f"testsrc2=size={width}x{height}:rate=24:duration=1", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
            ], check=True, timeout=30)
            cls.sources[(width, height)] = path

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    def render(self, sizes, *, aspect="16:9", **arguments) -> tuple[dict, dict]:
        with patch.dict(os.environ, {
            "REMOTION_RENDER_BACKEND": "local", "REMOTION_DRY_RUN": "false",
            "RENDERHAUS_MEDIA_DIR": str(self.root),
        }), patch.object(api, "load_remotion_settings", side_effect=AssertionError("AWS called")):
            props = api.build_timeline_props("Native resolution", [{
                "kind": "video", "output_path": str(self.sources[size]), "duration_seconds": 1,
            } for size in sizes], aspect_ratio=aspect, **arguments)
            result = api.render_timeline_and_wait(
                props, output_filename="native.mp4", poll_interval_seconds=.25, timeout_seconds=30,
            )
            self.assertEqual(result["status"], "succeeded", result)
            output = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_streams", "-of", "json", result["output_path"],
            ], timeout=30))["streams"][0]
            self.assertEqual((result["width"], result["height"]), (output["width"], output["height"]))
            self.assertEqual(output["r_frame_rate"], "24/1")
            subprocess.run(["ffmpeg", "-v", "error", "-i", result["output_path"],
                            "-f", "null", "-"], check=True, timeout=30)
            return result, output

    def test_720p_source_delivers_native_720p_by_default(self) -> None:
        result, output = self.render([(1280, 720)])
        self.assertEqual((output["width"], output["height"]), (1280, 720))
        self.assertEqual(result["source_resolution"], "1280x720")
        self.assertFalse(result["upscaled"])

    def test_1080p_source_delivers_native_1080p(self) -> None:
        _, output = self.render([(1920, 1080)])
        self.assertEqual((output["width"], output["height"]), (1920, 1080))

    def test_mixed_sources_use_largest_canvas_and_lanczos(self) -> None:
        result, output = self.render([(1280, 720), (1920, 1080)])
        self.assertEqual((output["width"], output["height"]), (1920, 1080))
        directory = Path(result["output_path"]).parent
        command = json.loads((directory / "worker.json").read_text())["command"]
        filters = command[command.index("-filter_complex") + 1]
        self.assertEqual(filters.count("scale="), 2)
        self.assertEqual(filters.count("flags=lanczos"), 2)
        self.assertTrue(result["upscaled"])

    def test_portrait_source_delivers_native_portrait(self) -> None:
        _, output = self.render([(720, 1280)], aspect="9:16")
        self.assertEqual((output["width"], output["height"]), (720, 1280))

    def test_explicit_1080p_warns_about_upscaling(self) -> None:
        result, output = self.render([(1280, 720)], output_resolution="1080p")
        self.assertEqual((output["width"], output["height"]), (1920, 1080))
        self.assertTrue(result["upscaled"])
        warning = " ".join(result["warnings"])
        self.assertIn("upscaled from 1280x720", warning)
        self.assertIn("no added detail", warning)
        self.assertIn("Topaz", warning)

    def test_explicit_720p_downscales_with_lanczos(self) -> None:
        result, output = self.render([(1920, 1080)], output_resolution="720p")
        self.assertEqual((output["width"], output["height"]), (1280, 720))
        self.assertFalse(result["upscaled"])
        command = json.loads((Path(result["output_path"]).parent / "worker.json").read_text())["command"]
        self.assertIn("flags=lanczos", command[command.index("-filter_complex") + 1])

    def test_contain_scaling_uses_lanczos(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            props = api.build_timeline_props("Contain", [{"kind": "video",
                "output_path": str(self.sources[(1280, 720)]), "duration_seconds": 1,
                "source_fps": 24, "fit": "contain"}], fps=24, output_resolution="1080p")
            command, _ = local._command(props, Path(folder), media_roots=(self.root,),
                                        source_root=self.root, filename="contain.mp4")
        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("force_original_aspect_ratio=decrease:flags=lanczos", filters)




if __name__ == "__main__":
    unittest.main()
