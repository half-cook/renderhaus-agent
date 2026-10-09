"""Offline Wan 3 contracts and queue lifecycle checks."""

from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from providers.catalog import get_provider
from providers.fal import api, queue
from providers.registry import dispatch, generate_schemas


IMAGE = "https://media.example.test/image.png"
VIDEO = "https://media.example.test/video.mp4"
AUDIO = "https://media.example.test/audio.mp3"
TOOLS = {
    "generate_wan3_t2v": "alibaba/wan-3.0/text-to-video",
    "generate_wan3_i2v": "alibaba/wan-3.0/image-to-video",
    "generate_wan3_r2v": "alibaba/wan-3.0/reference-to-video",
}


class Wan3ContractTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"FAL_DRY_RUN": "true"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        guard = patch.object(queue, "request", side_effect=AssertionError("Provider HTTP called"))
        guard.start()
        self.addCleanup(guard.stop)

    def contract(self):
        return importlib.import_module("providers.fal.wan3")

    def test_fixed_endpoints_schema_and_no_negative_prompt(self):
        self.assertEqual(self.contract().TOOL_ENDPOINTS, TOOLS)
        schemas = {row["name"]: row for row in generate_schemas(get_provider("fal"))}
        for tool in TOOLS:
            schema = schemas[tool]["inputSchema"]
            self.assertNotIn("negative_prompt", schema["properties"])
            self.assertNotIn("model", schema["properties"])
            self.assertEqual(schema["properties"]["duration"]["type"], "integer")
            self.assertEqual(schema["required"], {"generate_wan3_t2v": ["prompt"],
                             "generate_wan3_i2v": ["start_image_url"],
                             "generate_wan3_r2v": []}[tool])

    def test_default_dry_run_never_submits_or_claims_an_artifact(self):
        os.environ.pop("FAL_DRY_RUN")
        for tool, args in (("generate_wan3_t2v", {"prompt": "A scene"}),
                           ("generate_wan3_i2v", {"start_image_url": IMAGE}),
                           ("generate_wan3_r2v", {})):
            output = dispatch("fal", tool, args)
            self.assertEqual(output["status"], "dry_run")
            self.assertEqual(output["endpoint_id"], TOOLS[tool])
            self.assertFalse(output["training_eligible"])
            self.assertEqual(output["weights_license"], "closed-weights")
            self.assertNotIn("video_url", output)
            self.assertEqual(output["request_preview"]["resolution"], "1080p")
            self.assertEqual(output["request_preview"]["duration"], 5)
            self.assertTrue(output["request_preview"]["audio"])
            self.assertEqual(api.get_video_task(output["job_id"])["status"], "dry_run")

    def test_smart_duration_survives_dry_run_as_null(self):
        result = dispatch("fal", "generate_wan3_t2v", {"prompt": "A scene", "duration": None})
        self.assertIsNone(result["request_preview"]["duration"])
        self.assertIsNone(result["estimated_cost_usd"])
        self.assertIn("unknown", result["cost_estimate"])

    def test_smart_duration_blocks_live_before_network(self):
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
            with self.assertRaisesRegex(ValueError, "smart duration|Smart duration"):
                dispatch("fal", "generate_wan3_t2v", {"prompt": "A scene", "duration": None})

    def test_i2v_native_start_end_and_optional_prompt(self):
        body = dispatch("fal", "generate_wan3_i2v", {
            "start_image_url": IMAGE, "end_image_url": "data:image/png;base64,AA",
            "seed": 2147483647, "duration": 30, "audio": False,
        })["request_preview"]
        self.assertEqual(body["start_image_url"], IMAGE)
        self.assertEqual(body["end_image_url"], "data:image/png;base64,AA")
        self.assertFalse(body["audio"])
        self.assertNotIn("real_face_refs", body)
        self.assertNotIn("likeness_consent", body)

    def test_reference_limits_and_measurements_stay_local(self):
        body = dispatch("fal", "generate_wan3_r2v", {
            "reference_image_urls": [IMAGE] * 10,
            "reference_video_urls": [VIDEO] * 5,
            "reference_video_durations": [3.0] * 5,
            "reference_video_fps": [16.0] * 5,
            "reference_audio_urls": [AUDIO] * 5,
            "reference_audio_durations": [3.0] * 5,
        })["request_preview"]
        for field in ("reference_video_durations", "reference_video_fps", "reference_audio_durations"):
            self.assertNotIn(field, body)
        self.assertEqual(len(body["reference_video_urls"]), 5)

    def test_consent_is_required_for_real_face_references(self):
        for tool, base in (("generate_wan3_i2v", {"start_image_url": IMAGE}),
                           ("generate_wan3_r2v", {"reference_image_urls": [IMAGE]})):
            with self.subTest(tool=tool), self.assertRaisesRegex(ValueError, "likeness_consent"):
                dispatch("fal", tool, {**base, "real_face_refs": True})
            result = dispatch("fal", tool, {**base, "real_face_refs": True, "likeness_consent": True})
            self.assertEqual(result["status"], "dry_run")

    def test_invalid_arguments_fail_before_http(self):
        cases = [
            ("generate_wan3_t2v", {"prompt": "p", "negative_prompt": "bad"}, "negative_prompt"),
            ("generate_wan3_t2v", {"prompt": "p", "model": "other"}, "model"),
            ("generate_wan3_t2v", {"prompt": "p" * 20001}, "prompt"),
            ("generate_wan3_t2v", {}, "prompt"),
            ("generate_wan3_i2v", {"start_image_url": "file:///tmp/a"}, "start_image_url"),
            ("generate_wan3_i2v", {"start_image_url": IMAGE, "end_image_url": "bad"}, "end_image_url"),
            ("generate_wan3_r2v", {"reference_image_urls": [IMAGE] * 11}, "reference_image_urls"),
            ("generate_wan3_r2v", {"reference_video_urls": [VIDEO] * 6}, "reference_video_urls"),
            ("generate_wan3_r2v", {"reference_audio_urls": [AUDIO] * 6}, "reference_audio_urls"),
            ("generate_wan3_r2v", {"reference_video_urls": [VIDEO]}, "reference_video_durations"),
            ("generate_wan3_r2v", {"reference_video_urls": [VIDEO], "reference_video_durations": [16]}, "15"),
            ("generate_wan3_r2v", {"reference_video_urls": [VIDEO], "reference_video_durations": [3], "reference_video_fps": [15]}, "reference_video_fps"),
            ("generate_wan3_r2v", {"reference_audio_urls": [AUDIO], "reference_audio_durations": [16]}, "15"),
            ("generate_wan3_r2v", {"reference_audio_urls": [AUDIO]}, "reference_audio_durations"),
            ("generate_wan3_r2v", {"reference_audio_durations": [3]}, "reference_audio_durations"),
            ("generate_wan3_r2v", {"file_url": IMAGE}, "enable_thinking"),
            ("generate_wan3_r2v", {"web_url": "data:text/html,hi", "enable_thinking": True}, "web_url"),
            ("generate_wan3_r2v", {"reference_video_urls": [12]}, "reference_video_urls"),
            ("generate_wan3_t2v", {"prompt": "p", "audio": "true"}, "audio"),
        ]
        for kind, url in (("video", VIDEO), ("audio", AUDIO)):
            for duration in (0, -1, True, float("nan"), float("inf")):
                cases.append(("generate_wan3_r2v", {
                    f"reference_{kind}_urls": [url],
                    f"reference_{kind}_durations": [duration],
                    **({"reference_video_fps": [24]} if kind == "video" else {}),
                }, f"reference_{kind}_durations"))
        for fps in (True, float("nan"), float("inf")):
            cases.append(("generate_wan3_r2v", {
                "reference_video_urls": [VIDEO], "reference_video_durations": [3],
                "reference_video_fps": [fps],
            }, "reference_video_fps"))
        for duration in (True, 1, 31, 5.0, "5"):
            cases.append(("generate_wan3_t2v", {"prompt": "p", "duration": duration}, "duration"))
        for seed in (-1, 2147483648, True, "1"):
            cases.append(("generate_wan3_t2v", {"prompt": "p", "seed": seed}, "seed"))
        for field, value in (("resolution", "4K"), ("aspect_ratio", "21:9")):
            cases.append(("generate_wan3_t2v", {"prompt": "p", field: value}, field))
        for tool, args, message in cases:
            with self.subTest(tool=tool, args=args), self.assertRaisesRegex(ValueError, message):
                dispatch("fal", tool, args)

    def test_documented_boundaries(self):
        for duration in (2, 30):
            for resolution in ("480p", "720p", "1080p"):
                for seed in (0, 2147483647):
                    result = dispatch("fal", "generate_wan3_t2v", {
                        "prompt": "p" * 20000, "duration": duration,
                        "resolution": resolution, "seed": seed,
                    })
                    self.assertEqual(result["status"], "dry_run")
        result = dispatch("fal", "generate_wan3_r2v", {
            "file_url": IMAGE, "web_url": "https://example.test", "enable_thinking": True,
        })
        self.assertEqual(result["request_preview"]["web_url"], "https://example.test")

    def test_queue_root_and_handle_validation(self):
        for endpoint in TOOLS.values():
            self.assertEqual(queue.request_url(endpoint, "request_1"),
                             "https://queue.fal.run/alibaba/wan-3.0/requests/request_1")
            self.assertEqual(api._parse_job(endpoint + ":request_1"), (endpoint, "request_1"))
        with self.assertRaises(ValueError):
            api.get_video_task("alibaba/wan-3.0/unknown:request_1")

    def test_catalog_sources_and_training_policy(self):
        rows = {row["id"]: row for row in api.list_fal_models()["endpoints"]}
        for endpoint in TOOLS.values():
            row = rows[endpoint]
            self.assertEqual(row["api_url"], "https://fal.ai/models/" + endpoint + "/api")
            self.assertEqual(row["pricing_checked_at"], "2026-10-09")
            self.assertEqual(row["hosted_terms_url"], "https://fal.ai/legal/terms-of-service")
            self.assertFalse(row["training_eligible"])
            self.assertEqual(row["usd_per_unit_by_resolution"], {"480p": "0.05", "720p": "0.1", "1080p": "0.2"})


class Wan3QueueTests(unittest.TestCase):
    def test_mock_http_submit_poll_and_download(self):
        endpoint = TOOLS["generate_wan3_r2v"]
        requests = []
        def respond(request):
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"request_id": "request_1", "status": "IN_QUEUE"})
            if request.url.path.endswith("/status"):
                return httpx.Response(200, json={"status": "COMPLETED"})
            if request.url.host == "media.example.test":
                return httpx.Response(200, content=b"mock-video")
            return httpx.Response(200, json={"video": {"url": VIDEO}, "seed": 7, "duration": 5,
                                            "actual_prompt": "Expanded scene"})
        transport = httpx.MockTransport(respond)
        real_client = httpx.Client
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "FAL_DRY_RUN": "false", "FAL_KEY": "dummy-test-key", "RENDERHAUS_MEDIA_DIR": directory,
        }), patch.object(queue.httpx, "Client", side_effect=lambda **kwargs: real_client(transport=transport, **kwargs)), patch.object(api.httpx, "stream", side_effect=lambda method, url, **kwargs: real_client(transport=transport).stream(method, url, **kwargs)):
            output = dispatch("fal", "generate_wan3_r2v", {
                "reference_video_urls": [VIDEO], "reference_video_durations": [3],
                "reference_video_fps": [24], "duration": 5, "resolution": "720p",
            })
            self.assertEqual(output["status"], "queued")
            self.assertEqual(output["estimated_cost_usd"], .8)
            body = json.loads(requests[0].content)
            self.assertEqual(requests[0].url.path, "/" + endpoint)
            self.assertNotIn("reference_video_durations", body)
            self.assertNotIn("reference_video_fps", body)
            polled = api.get_video_task(output["job_id"], download=True)
            self.assertEqual(polled["status"], "succeeded")
            self.assertEqual(polled["duration"], 5)
            self.assertEqual(polled["actual_prompt"], "Expanded scene")
            self.assertFalse(polled["training_eligible"])
            self.assertEqual(Path(polled["output_path"]).read_bytes(), b"mock-video")

    def test_queue_and_result_failures_keep_metadata(self):
        endpoint = TOOLS["generate_wan3_i2v"]
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false", "FAL_KEY": "dummy-test-key"}):
            for status in ({"status": "FAILED", "error": "blocked"},
                           {"status": "COMPLETED", "error_type": "content_policy"}):
                with patch.object(queue, "status", return_value=status):
                    result = api.get_video_task(endpoint + ":request_1")
                    self.assertEqual(result["status"], "failed")
                    self.assertFalse(result["training_eligible"])
            with patch.object(queue, "status", return_value={"status": "COMPLETED"}), patch.object(queue, "result", side_effect=queue.FalAPIError(422, "bad input")):
                self.assertEqual(api.get_video_task(endpoint + ":request_1")["status"], "failed")
            with patch.object(queue, "status", return_value={"status": "COMPLETED"}), patch.object(queue, "result", side_effect=queue.FalAPIError(429, "retry later")):
                with self.assertRaises(queue.FalAPIError):
                    api.get_video_task(endpoint + ":request_1")
