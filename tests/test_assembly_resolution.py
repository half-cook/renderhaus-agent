from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
import httpx

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

    def test_direct_dry_run_rejects_invalid_resolution_without_probing(self) -> None:
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "true"}), \
                patch.object(api, "_visual_metadata", side_effect=AssertionError("source probed")):
            with self.assertRaises(ValueError):
                api.render_timeline("Invalid", [{"kind": "video",
                    "url": "https://example.test/source.mp4", "duration_seconds": 1,
                }], output_resolution="8K")

    def test_gateway_resolution_argument_is_optional_and_matches_signature(self) -> None:
        spec = PROVIDERS_BY_ID["remotion"]
        generated = generate_schemas(spec)
        self.assertEqual(generated, load_committed_schemas(spec))
        schema = next(tool["inputSchema"] for tool in generated if tool["name"] == "render_timeline")
        self.assertNotIn("output_resolution", schema["required"])
        resolution = schema["properties"]["output_resolution"]
        self.assertEqual(resolution["type"], "string")
        self.assertNotIn("enum", resolution)
        for choice in ("source", "720p", "1080p", "1440p", "2160p"):
            self.assertIn(choice, resolution["description"])
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

    def test_smaller_canvas_preserves_measured_container_overhead_without_inflation(self) -> None:
        with patch.object(local, "_probe", return_value={"format": {"bit_rate": "1100000"},
                "streams": [{"codec_type": "video", "avg_frame_rate": "24/1",
                    "bit_rate": "1000000", "width": 1280, "height": 720}]}):
            config = api.build_timeline_props("Container overhead", [{"kind": "video",
                "output_path": str(self.source), "duration_seconds": 1,
            }], aspect_ratio="16:9")["renderConfig"]
        self.assertEqual(config["videoBitrate"], 1_100_000)

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

    def test_clip_scale_counts_when_reporting_upscaling(self) -> None:
        with patch.object(local, "_probe", return_value={"streams": [{
            "codec_type": "video", "avg_frame_rate": "24/1", "width": 1280, "height": 720,
        }]}):
            config = api.build_timeline_props("Scale", [{"kind": "video",
                "output_path": str(self.source), "duration_seconds": 1, "scale": 1.2,
            }], aspect_ratio="16:9")["renderConfig"]
        self.assertTrue(config["resolution"]["upscaled"])

    def test_existing_zoom_and_pan_motion_count_when_reporting_upscaling(self) -> None:
        for motion in ("zoom_in", "zoom_out", "pan_left", "pan_right"):
            with self.subTest(motion=motion), patch.object(local, "_probe", return_value={"streams": [{
                "codec_type": "video", "avg_frame_rate": "24/1", "width": 1280, "height": 720,
            }]}):
                config = api.build_timeline_props("Motion", [{"kind": "video",
                    "output_path": str(self.source), "duration_seconds": 1, "motion": motion,
                }], aspect_ratio="16:9")["renderConfig"]
                self.assertTrue(config["resolution"]["upscaled"])

    def test_ffprobe_display_rotation_uses_display_dimensions(self) -> None:
        for rotation, source, upscaled in ((90, "720x1280", False), (-90, "720x1280", False),
                                          (270, "720x1280", False), (180, "1280x720", True)):
            with self.subTest(rotation=rotation), patch.object(local, "_probe", return_value={"streams": [{
                "codec_type": "video", "avg_frame_rate": "24/1", "width": 1280, "height": 720,
                "side_data_list": [{"side_data_type": "Display Matrix", "rotation": rotation}],
            }]}):
                config = api.build_timeline_props("Phone video", [{"kind": "video",
                    "output_path": str(self.source), "duration_seconds": 1,
                }], aspect_ratio="9:16")["renderConfig"]
                self.assertEqual(config["resolution"]["source_resolution"], source)
                self.assertEqual(config["resolution"]["upscaled"], upscaled)

    def test_unusual_display_rotation_keeps_source_dimensions_unknown(self) -> None:
        with patch.object(local, "_probe", return_value={"streams": [{
            "codec_type": "video", "avg_frame_rate": "24/1", "width": 1280, "height": 720,
            "side_data_list": [{"side_data_type": "Display Matrix", "rotation": 45}],
        }]}):
            config = api.build_timeline_props("Angled video", [{"kind": "video",
                "output_path": str(self.source), "duration_seconds": 1,
            }], aspect_ratio="9:16")["renderConfig"]
        self.assertIsNone(config["resolution"]["source_resolution"])
        self.assertTrue(config["resolution"]["warnings"])

    def test_trusted_remote_dimensions_are_probed_despite_prior_measurements(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"video"))
        http_client = httpx.Client
        with patch.dict(os.environ, {"REMOTION_LOCAL_MEDIA_HOSTS": ""}), \
                patch.object(local.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]), \
                patch.object(local.httpx, "Client", side_effect=lambda **kwargs: http_client(
                    transport=transport, **kwargs)), \
                patch.object(local, "_probe", return_value={"streams": [{
                    "codec_type": "video", "avg_frame_rate": "24/1", "bit_rate": 1000000,
                    "width": 1280, "height": 720,
                }]}):
            config = api.build_timeline_props("Remote", [{"kind": "video",
                "url": "https://v3.fal.media/source.mp4", "duration_seconds": 1,
                "source_fps": 24, "source_bitrate": 1000000,
            }], aspect_ratio="16:9", measure_remote=True)["renderConfig"]
        self.assertEqual((config["width"], config["height"]), (1280, 720))
        self.assertEqual(config["resolution"]["source_resolution"], "1280x720")

    def test_untrusted_remote_with_prior_measurements_keeps_no_download_fallback(self) -> None:
        with patch.object(local, "_source", side_effect=AssertionError("untrusted download")):
            config = api.build_timeline_props("Remote", [{"kind": "video",
                "url": "https://example.test/source.mp4", "duration_seconds": 1,
                "source_fps": 24, "source_bitrate": 1000000,
            }], aspect_ratio="16:9", measure_remote=True)["renderConfig"]
        self.assertEqual((config["width"], config["height"]), (1920, 1080))
        self.assertIn("could not be measured", " ".join(config["resolution"]["warnings"]))

    def test_trusted_remote_probe_errors_are_not_hidden_by_prior_measurements(self) -> None:
        with patch.object(local, "_source", side_effect=ValueError("unsafe source")), \
                patch.object(api, "_start_render", side_effect=AssertionError("paid render")), \
                patch.dict(os.environ, {"REMOTION_DRY_RUN": "false"}):
            with self.assertRaisesRegex(ValueError, "unsafe source"):
                api.render_timeline("Remote", [{"kind": "video",
                    "url": "https://v3.fal.media/source.mp4", "duration_seconds": 1,
                    "source_fps": 24, "source_bitrate": 1000000,
                }])

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


class LambdaResolutionReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        import io
        from remotion_lambda.models import RenderMediaProgress

        self.objects = {}
        self.s3 = Mock()
        self.s3.put_object.side_effect = lambda **kwargs: self.objects.update({kwargs["Key"]: kwargs["Body"]})

        def get_object(**kwargs):
            if kwargs["Key"] not in self.objects:
                raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
            return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

        self.s3.get_object.side_effect = get_object
        self.s3.generate_presigned_url.return_value = "https://example.test/final.mp4"
        session = Mock()
        session.client.return_value = self.s3
        self.client = Mock()
        self.client.render_media_on_lambda.return_value = Mock(render_id="receipt-test", bucket_name="bucket")
        self.client.get_render_progress.return_value = RenderMediaProgress(
            done=True, outKey="renders/receipt-test/final.mp4", overallProgress=1,
            renderMetadata={"dimensions": {"width": 1280, "height": 720}},
        )
        self.enterContext(patch.dict(os.environ, {"REMOTION_DRY_RUN": "false", "REMOTION_RENDER_BACKEND": "lambda"}))
        self.enterContext(patch.object(api, "load_remotion_settings", return_value=api.RemotionSettings(
            "us-east-1", "function", "https://example.test/site", "bucket")))
        self.enterContext(patch.object(api.boto3, "Session", return_value=session))
        self.enterContext(patch.object(api, "_prepare_input_props", side_effect=lambda props, **_: props))
        self.enterContext(patch.object(api, "RemotionClient", return_value=self.client))
        self.props = api.build_timeline_props('Receipt', [{'kind': 'image',
            'url': 'https://example.test/still.png', 'duration_seconds': 2}], fps=24, aspect_ratio='16:9')
        self.props['renderConfig'].update({
            "width": 1280, "height": 720, "fps": 24, "videoBitrate": None, "crf": 18,
            "resolution": {"width": 1280, "height": 720, "source_resolution": "1280x720",
                "upscaled": False, "warnings": [], "url": "https://private.test/input?credential=secret"},
        })

    def test_receipt_write_failure_preserves_accepted_render_handle(self) -> None:
        self.s3.put_object.side_effect = OSError("storage unavailable")
        result = api._start_render(self.props, output_filename="final.mp4")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["render_id"], "receipt-test")
        self.assertEqual((result["width"], result["height"]), (1280, 720))
        self.assertIn("could not be stored", " ".join(result["warnings"]))

    def test_receipt_contains_only_resolution_fields(self) -> None:
        api._start_render(self.props, output_filename="final.mp4")
        self.assertEqual(len(self.objects), 1)
        receipt = json.loads(next(iter(self.objects.values())))
        self.assertEqual(receipt, {"width": 1280, "height": 720,
            "source_resolution": "1280x720", "upscaled": False, "warnings": []})

    def test_receipt_omits_sensitive_warning_text(self) -> None:
        warning = "Video source dimensions could not be measured; the canvas may resize the source."
        self.props["renderConfig"]["resolution"]["warnings"] = [
            warning, "https://private.test/source?token=secret", "/workspace/private-secret.mp4",
        ]
        api._start_render(self.props, output_filename="final.mp4")
        receipt = json.loads(next(iter(self.objects.values())))
        self.assertEqual(receipt["warnings"], [warning])

    def test_legacy_missing_receipt_reports_unknown_source_and_actual_canvas(self) -> None:
        result = api.get_render_progress("legacy-render", "bucket", download=False)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual((result["width"], result["height"]), (1280, 720))
        self.assertIsNone(result["source_resolution"])
        self.assertFalse(result["upscaled"])
        self.assertTrue(result["warnings"])

    def test_missing_receipt_with_no_canvas_metadata_keeps_dimensions_unknown(self) -> None:
        from remotion_lambda.models import RenderMediaProgress

        self.client.get_render_progress.return_value = RenderMediaProgress(
            done=True, outKey="renders/legacy/final.mp4", overallProgress=1)
        result = api.get_render_progress("legacy-render", "bucket", download=False)
        self.assertIsNone(result["width"])
        self.assertIsNone(result["height"])
        self.assertTrue(result["warnings"])

    def test_receipt_read_failure_does_not_hide_completed_render(self) -> None:
        self.s3.get_object.side_effect = OSError("storage unavailable")
        result = api.get_render_progress("legacy-render", "bucket", download=False)
        self.assertEqual(result["status"], "succeeded")
        self.assertIsNone(result["source_resolution"])
        self.assertTrue(result["warnings"])

    def test_downloaded_output_dimensions_override_reported_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.s3.download_file.side_effect = lambda bucket, key, path: Path(path).write_bytes(b"final video")
            with patch.object(api, "OUTPUT_DIR", Path(temporary)), \
                    patch.object(api, "_on_lambda", return_value=False), \
                    patch.object(local, "_probe", return_value={"streams": [{
                        "codec_type": "video", "width": 640, "height": 360,
                    }]}):
                result = api.get_render_progress("receipt-test", "bucket", download=True)
            self.assertEqual((result["width"], result["height"]), (640, 360))
            self.assertTrue(Path(result["output_path"]).is_file())

    def test_download_measurement_failure_retains_completed_metadata_and_artifact(self) -> None:
        for error in (ValueError("source size limit"), OSError("probe unavailable"),
                      subprocess.TimeoutExpired("ffprobe", 30)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                self.s3.download_file.side_effect = lambda bucket, key, path: Path(path).write_bytes(b"video")
                with patch.object(api, "OUTPUT_DIR", Path(temporary)), \
                        patch.object(api, "_on_lambda", return_value=False), \
                        patch.object(local, "_probe", side_effect=error):
                    result = api.get_render_progress("receipt-test", "bucket", download=True)
                self.assertEqual(result["status"], "succeeded")
                self.assertEqual((result["width"], result["height"]), (1280, 720))
                self.assertTrue(Path(result["output_path"]).is_file())
                self.assertIn("could not be measured", " ".join(result["warnings"]))

    def test_failed_output_probe_does_not_treat_planned_canvas_as_delivered_dimensions(self) -> None:
        from remotion_lambda.models import RenderMediaProgress

        api._start_render(self.props, output_filename="final.mp4")
        self.client.get_render_progress.return_value = RenderMediaProgress(
            done=True, outKey="renders/receipt-test/final.mp4", overallProgress=1)
        with tempfile.TemporaryDirectory() as temporary:
            self.s3.download_file.side_effect = lambda bucket, key, path: Path(path).write_bytes(b"video")
            with patch.object(api, "OUTPUT_DIR", Path(temporary)), \
                    patch.object(api, "_on_lambda", return_value=False), \
                    patch.object(local, "_probe", side_effect=ValueError("source size limit")):
                result = api.get_render_progress("receipt-test", "bucket", download=True)
            self.assertEqual(result["status"], "succeeded")
            self.assertIsNone(result["width"])
            self.assertIsNone(result["height"])
            self.assertIn("could not be measured", " ".join(result["warnings"]))

    def test_completed_poll_without_measurement_does_not_report_planned_canvas(self) -> None:
        from remotion_lambda.models import RenderMediaProgress

        api._start_render(self.props, output_filename="final.mp4")
        self.client.get_render_progress.return_value = RenderMediaProgress(
            done=True, outKey="renders/receipt-test/final.mp4", overallProgress=1)
        result = api.get_render_progress("receipt-test", "bucket", download=False)
        self.assertEqual(result["status"], "succeeded")
        self.assertIsNone(result["width"])
        self.assertIsNone(result["height"])
        self.assertEqual(result["source_resolution"], "1280x720")
        self.assertIn("could not be measured", " ".join(result["warnings"]))


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
        cls.sources["rotated"] = cls.root / "rotated-portrait.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-display_rotation:v:0", "90", "-i",
            str(cls.sources[(1280, 720)]), "-c", "copy", str(cls.sources["rotated"]),
        ], check=True, timeout=30)

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

    def test_rotated_phone_source_delivers_native_portrait_without_upscale_warning(self) -> None:
        result, output = self.render(["rotated"], aspect="9:16")
        self.assertEqual((output["width"], output["height"]), (720, 1280))
        self.assertEqual(result["source_resolution"], "720x1280")
        self.assertFalse(result["upscaled"])
        self.assertEqual(result["warnings"], [])

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
