from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from providers.remotion import api
from providers.remotion import local
from providers.registry import dispatch


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class RemotionQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        cls.sources = {}
        for fps in (24, 30, "30000/1001"):
            source = cls.root / f"source-{str(fps).replace('/', '-')}.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                f"testsrc2=size=320x180:rate={fps}:duration=3", "-c:v", "libx264",
                "-crf", "10", "-pix_fmt", "yuv420p", str(source),
            ], check=True, timeout=30)
            cls.sources[fps] = source
        cls.sources["mkv30"] = cls.root / "source-30.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(cls.sources[30]), "-c", "copy",
                        str(cls.sources["mkv30"])], check=True, timeout=30)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    @staticmethod
    def probe(path: Path) -> dict:
        result = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path),
        ], timeout=30)
        return json.loads(result)["streams"][0]

    def test_local_export_preserves_source_quality_and_unset_source_fps(self) -> None:
        with patch.dict(os.environ, {
            "REMOTION_RENDER_BACKEND": "local", "REMOTION_DRY_RUN": "false",
            "RENDERHAUS_MEDIA_DIR": str(self.root),
        }), patch.dict(api.ASPECT_SIZES, {"16:9": (320, 180)}):
            for source_fps, requested_fps, expected_rate in (
                (30, None, "30/1"), (24, None, "24/1"), (30, 24, "24/1"),
                ("30000/1001", None, "30000/1001"),
                ("mkv30", None, "30/1"),
            ):
                with self.subTest(source_fps=source_fps, requested_fps=requested_fps):
                    arguments = {
                        "title": "Source quality", "visuals": [{"kind": "video",
                            "output_path": str(self.sources[source_fps]), "duration_seconds": 3}],
                        "aspect_ratio": "16:9",
                    }
                    if requested_fps is not None:
                        arguments["fps"] = requested_fps
                    props = api.build_timeline_props(**arguments)
                    result = api.render_timeline_and_wait(props, output_filename="quality.mp4",
                                                         poll_interval_seconds=.25, timeout_seconds=30)
                    self.assertEqual(result["status"], "succeeded")
                    source = self.probe(self.sources[source_fps])
                    output = self.probe(Path(result["output_path"]))
                    self.assertEqual(output["r_frame_rate"], expected_rate)
                    source_rate = source.get("bit_rate") or local._probe(self.sources[source_fps])["format"]["bit_rate"]
                    self.assertGreaterEqual(int(output["bit_rate"]), int(source_rate) * .8)

    def test_lambda_receives_resolved_frame_rate_and_source_bitrate_floor(self) -> None:
        source = self.sources[24]
        client = Mock()
        client.render_media_on_lambda.return_value = Mock(render_id="render", bucket_name="bucket")
        with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": str(self.root),
                                    "REMOTION_RENDER_BACKEND": "lambda", "REMOTION_DRY_RUN": "false"}), \
                patch.object(api, "load_remotion_settings", return_value=api.RemotionSettings(
                    region="us-east-1", function_name="function", serve_url="https://example/site",
                    bucket_name="bucket")), \
                patch.object(api.boto3, "Session"), \
                patch.object(api, "_prepare_input_props", side_effect=lambda props, **_: props), \
                patch.object(api, "RemotionClient", return_value=client):
            result = dispatch("remotion", "render_timeline", {
                "title": "Lambda source quality", "visuals": [{"kind": "video",
                    "output_path": str(source), "duration_seconds": 3}],
            })
        self.assertEqual(result["status"], "queued")
        params = client.render_media_on_lambda.call_args.args[0]
        self.assertEqual(params.input_props["renderConfig"]["fps"], 24)
        self.assertEqual(params.input_props["renderConfig"]["durationInFrames"], 72)
        self.assertEqual(params.force_fps, 24)
        self.assertGreaterEqual(params.video_bitrate, int(self.probe(source)["bit_rate"]))
        self.assertIsNone(params.crf)

    def test_remote_video_metadata_and_bitrate_are_validated_before_submission(self) -> None:
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "false"}), \
                patch.object(api, "_start_render", side_effect=AssertionError("render started")):
            for metadata in ({}, {"source_fps": 0}, {"source_fps": float("nan")},
                             {"source_fps": 24, "source_bitrate": -1},
                             {"source_fps": 24, "source_bitrate": 1.5}):
                with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                    dispatch("remotion", "render_timeline", {
                        "title": "Remote metadata", "visuals": [{"kind": "video",
                            "url": "https://example.test/video.mp4", "duration_seconds": 3,
                            **metadata}],
                    })
            with self.assertRaises(ValueError):
                dispatch("remotion", "render_timeline", {
                    "title": "Invalid bitrate", "visuals": [{"kind": "image",
                        "url": "https://example.test/still.png", "duration_seconds": 3}],
                    "video_bitrate": 0,
                })
        props = api.build_timeline_props("Measured remote", [{"kind": "video",
            "url": "https://example.test/video.mp4", "duration_seconds": 3,
            "source_fps": 24, "source_bitrate": 1_000_000}], video_bitrate=100_000)
        self.assertEqual(props["renderConfig"]["fps"], 24)
        self.assertEqual(props["renderConfig"]["videoBitrate"], 1_250_000)

    def test_gateway_lambda_measures_remote_video_without_ffprobe(self) -> None:
        source = self.sources["mkv30"]
        client = Mock()
        client.render_media_on_lambda.return_value = Mock(render_id="render", bucket_name="bucket")
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=source.read_bytes()))
        http_client = httpx.Client
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "false", "REMOTION_RENDER_BACKEND": "lambda",
                                    "AWS_LAMBDA_FUNCTION_NAME": "remotion", "REMOTION_LOCAL_MEDIA_HOSTS": ""}), \
                patch.object(local.shutil, "which", return_value=None), \
                patch.object(local.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]), \
                patch.object(local.httpx, "Client", side_effect=lambda **kwargs: http_client(
                    transport=transport, **kwargs)), \
                patch.object(api, "load_remotion_settings", return_value=api.RemotionSettings(
                    region="us-east-1", function_name="function", serve_url="https://example/site",
                    bucket_name="bucket")), \
                patch.object(api.boto3, "Session"), \
                patch.object(api, "_prepare_input_props", side_effect=lambda props, **_: props), \
                patch.object(api, "RemotionClient", return_value=client):
            result = dispatch("remotion", "render_timeline", {
                "title": "Remote source", "visuals": [{"kind": "video",
                    "url": "https://v3b.fal.media/files/test/source.mp4", "duration_seconds": 3}],
            })
        self.assertEqual(result["status"], "queued")
        params = client.render_media_on_lambda.call_args.args[0]
        self.assertEqual(params.force_fps, 30)
        self.assertEqual(params.input_props["renderConfig"]["durationInFrames"], 90)
        self.assertGreaterEqual(params.video_bitrate, int(local._probe(source)["format"]["bit_rate"]))

    def test_remote_probe_failures_never_submit_a_render(self) -> None:
        http_client = httpx.Client
        for status, body, address, url, limit in (
            (302, b"redirect", "8.8.8.8", "https://v3.fal.media/source.mp4", 128 * 1024 * 1024),
            (200, b"invalid media", "8.8.8.8", "https://v3.fal.media/source.mp4", 128 * 1024 * 1024),
            (200, self.sources[30].read_bytes(), "8.8.8.8", "https://v3.fal.media/source.mp4", 32),
            (200, self.sources[30].read_bytes(), "127.0.0.1", "https://v3.fal.media/source.mp4", 128 * 1024 * 1024),
            (200, self.sources[30].read_bytes(), "8.8.8.8", "https://fal.media.attacker.example/source.mp4", 128 * 1024 * 1024),
        ):
            with self.subTest(status=status, address=address, url=url, limit=limit):
                transport = httpx.MockTransport(lambda request: httpx.Response(status, content=body))
                with patch.dict(os.environ, {"REMOTION_DRY_RUN": "false", "REMOTION_LOCAL_MEDIA_HOSTS": ""}), \
                        patch.object(local.shutil, "which", return_value=None), \
                        patch.object(local.socket, "getaddrinfo", return_value=[(2, 1, 6, "", (address, 443))]), \
                        patch.object(local, "MAX_MEDIA_BYTES", limit), \
                        patch.object(local.httpx, "Client", side_effect=lambda **kwargs: http_client(
                            transport=transport, **kwargs)), \
                        patch.object(api, "_start_render", side_effect=AssertionError("paid render started")):
                    with self.assertRaises(ValueError):
                        api.render_timeline("Blocked probe", [{"kind": "video", "url": url,
                                                               "duration_seconds": 3}])


if __name__ == "__main__":
    unittest.main()
