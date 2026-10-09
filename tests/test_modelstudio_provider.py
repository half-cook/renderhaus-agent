from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx

from providers.catalog import get_provider
from providers.registry import dispatch, generate_schemas


VIDEO = "https://media.example.test/source.mp4"
IMAGE = "https://media.example.test/image.png"
AUDIO = "https://media.example.test/voice.mp3"
TASK_ID = "d290f1ee-6c54-4b01-90e6-d701748f0851"
WORKSPACE_HOST = "https://exampleworkspace.us-east-1.maas.aliyuncs.com"
BASE_ARGUMENTS = {
    "video_url": VIDEO,
    "prompt": "Keep the subject and change the lighting",
    "source_duration_seconds": 5,
    "source_fps": 24,
}
TOOLS = ("edit_wan3_video", "extend_wan3_video", "get_task")


class ModelStudioTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"MODELSTUDIO_DRY_RUN": "true"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def api(self):
        return importlib.import_module("providers.alibaba_modelstudio.api")

    def config(self):
        return importlib.import_module("providers.alibaba_modelstudio.config")

    @contextmanager
    def mock_http(self, respond):
        api = self.api()
        client = httpx.Client
        transport = httpx.MockTransport(respond)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "MODELSTUDIO_DRY_RUN": "false", "DASHSCOPE_API_KEY": "dummy-test-key",
            "DASHSCOPE_BASE_URL": WORKSPACE_HOST, "RENDERHAUS_MEDIA_DIR": directory,
        }), patch.object(api.httpx, "Client", side_effect=lambda **kwargs: client(transport=transport, **kwargs)):
            yield Path(directory)

    def test_catalog_and_discovered_schemas_use_named_argument_contracts(self):
        spec = get_provider("alibaba_modelstudio")
        self.assertEqual(spec.target_name, "ModelStudio")
        self.assertIn("MODELSTUDIO_DRY_RUN", spec.env_keys)
        self.assertIn("DASHSCOPE_WORKSPACE_ID", spec.env_keys)
        schemas = {row["name"]: row["inputSchema"] for row in generate_schemas(spec)}
        self.assertEqual(set(schemas), set(TOOLS))
        for tool in TOOLS[:2]:
            self.assertEqual(set(schemas[tool]["required"]), set(BASE_ARGUMENTS))
            self.assertEqual(schemas[tool]["properties"]["duration"]["type"], "integer")
            self.assertIn("unknown", schemas[tool]["properties"]["duration"]["description"])
            self.assertNotIn("kwargs", schemas[tool]["properties"])
        self.assertEqual(schemas["get_task"]["required"], ["job_id"])

    def test_default_preview_never_uses_http_and_reports_unverified_host(self):
        os.environ.pop("MODELSTUDIO_DRY_RUN")
        with patch.object(self.api().httpx, "Client", side_effect=AssertionError("HTTP called")):
            result = dispatch("alibaba_modelstudio", "edit_wan3_video", BASE_ARGUMENTS)
            self.assertEqual(self.api().get_task(result["job_id"])["status"], "dry_run")
        self.assertEqual(result["status"], "dry_run")
        self.assertIsNone(result["estimated_cost_usd"])
        self.assertIn("UNVERIFIED", result["endpoint_verification"])
        self.assertFalse(result["training_eligible"])
        self.assertEqual(result["weights_license"], "closed-weights")
        self.assertNotIn("video_url", result)
        self.assertEqual(result["request_preview"]["model"], "wan3.0-video")
        parameters = result["request_preview"]["parameters"]
        self.assertEqual(parameters["duration"], -1)
        self.assertEqual(parameters["resolution"], "1080P")
        self.assertEqual(parameters["ratio"], "adaptive")
        self.assertTrue(parameters["audio"])
        self.assertEqual(parameters["seed"], -1)

    def test_edit_and_extension_intent_are_guaranteed_in_prompt_only(self):
        for tool, prefix in (("edit_wan3_video", "Edit Video 1"),
                             ("extend_wan3_video", "Extend Video 1 backward")):
            args = {**BASE_ARGUMENTS, "duration": 7}
            if tool.startswith("extend"):
                args["direction"] = "backward"
            result = dispatch("alibaba_modelstudio", tool, args)
            body = result["request_preview"]
            self.assertTrue(body["input"]["prompt"].startswith(prefix))
            self.assertIn(BASE_ARGUMENTS["prompt"], body["input"]["prompt"])
            self.assertEqual(body["input"]["media"], [{"type": "reference_video", "url": VIDEO}])
            self.assertEqual(set(body), {"model", "input", "parameters"})
            self.assertNotIn("direction", body["parameters"])
            self.assertNotIn("source_fps", body["parameters"])
            self.assertAlmostEqual(result["estimated_cost_usd"], 1.9803)

    def test_reference_metadata_and_consent_stay_local(self):
        result = dispatch("alibaba_modelstudio", "edit_wan3_video", {
            **BASE_ARGUMENTS, "reference_image_urls": [IMAGE] * 10,
            "reference_audio_urls": [AUDIO] * 5, "reference_audio_durations": [3] * 5,
            "real_face_refs": True, "likeness_consent": True, "seed": 0,
        })
        body = result["request_preview"]
        self.assertEqual(len(body["input"]["media"]), 16)
        self.assertEqual(body["parameters"]["seed"], 0)
        for field in ("source_duration_seconds", "source_fps", "real_face_refs",
                      "likeness_consent", "reference_audio_durations"):
            self.assertNotIn(field, json.dumps(body))

    def test_invalid_arguments_fail_for_registry_and_direct_call_before_http(self):
        cases = [
            {"video_url": "file:///tmp/a.mp4"}, {"video_url": "https://user:password@example.test/a.mp4"},
            {"video_url": "ftp://example.test/a.mp4"}, {"video_url": "https://example.test/a.mp4#fragment"},
            {"prompt": ""}, {"prompt": "x" * 20001}, {"duration": 1}, {"duration": 31},
            {"duration": 5.0}, {"duration": True}, {"resolution": "4k"}, {"audio": "true"},
            {"seed": -2}, {"seed": 2147483648}, {"watermark": 0}, {"prompt_extend": 1},
            {"reference_image_urls": [IMAGE] * 11}, {"reference_audio_urls": [AUDIO] * 6},
            {"reference_audio_urls": [AUDIO]}, {"reference_audio_durations": [3]},
            {"reference_audio_urls": [AUDIO], "reference_audio_durations": [16], "likeness_consent": True},
            {"real_face_refs": True},
            {"reference_audio_urls": [AUDIO], "reference_audio_durations": [3]},
        ]
        for field in ("source_duration_seconds", "source_fps"):
            for value in (True, 0, -1, float("nan"), float("inf"), "5"):
                cases.append({field: value})
        cases.extend([{"source_duration_seconds": 0.5}, {"source_duration_seconds": 15.1}, {"source_fps": 15},
                      {"source_duration_seconds": 15, "duration": 16}])
        for value in (True, 0, float("nan"), float("inf")):
            cases.append({"reference_audio_urls": [AUDIO], "reference_audio_durations": [value],
                          "likeness_consent": True})
        with patch.object(self.api().httpx, "Client", side_effect=AssertionError("HTTP called")):
            for extra in cases:
                args = {**BASE_ARGUMENTS, **extra}
                for direct in (False, True):
                    with self.subTest(extra=extra, direct=direct), self.assertRaises(ValueError):
                        if direct:
                            self.api().edit_wan3_video(**args)
                        else:
                            dispatch("alibaba_modelstudio", "edit_wan3_video", args)
            with self.assertRaisesRegex(ValueError, "unsupported"):
                dispatch("alibaba_modelstudio", "edit_wan3_video", {**BASE_ARGUMENTS, "edit_type": "other"})

    def test_extension_total_output_duration_and_adaptive_ratio(self):
        for extra in ({"duration": 5}, {"duration": 4}, {"aspect_ratio": "16:9"}, {"direction": "sideways"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                dispatch("alibaba_modelstudio", "extend_wan3_video", {**BASE_ARGUMENTS, **extra})
        result = self.api().extend_wan3_video(**BASE_ARGUMENTS)
        self.assertEqual(result["request_preview"]["parameters"]["duration"], -1)
        self.assertIsNone(result["estimated_cost_usd"])
        result = self.api().extend_wan3_video(**BASE_ARGUMENTS, duration=7)
        self.assertEqual(result["request_preview"]["parameters"]["duration"], 7)

    def test_edit_supports_documented_wide_ratio_and_one_second_source(self):
        result = self.api().edit_wan3_video(**{**BASE_ARGUMENTS, "source_duration_seconds": 1},
                                          duration=2, aspect_ratio="21:9")
        self.assertEqual(result["request_preview"]["parameters"]["ratio"], "21:9")

    def test_payload_builder_never_serializes_null_seed(self):
        contract = importlib.import_module("providers.alibaba_modelstudio.contracts")
        body = contract.request_body("edit_wan3_video", {**BASE_ARGUMENTS, "seed": None}, "wan3.0-video")
        self.assertEqual(body["parameters"]["seed"], -1)

    def test_settings_precedence_and_region_consistency(self):
        config = self.config()
        self.assertEqual(config.settings().base_url, "https://dashscope-us.aliyuncs.com")
        self.assertEqual(config.settings().region, "us-east-1")
        with patch.dict(os.environ, {"DASHSCOPE_WORKSPACE_ID": "workspace123"}):
            self.assertEqual(config.settings().base_url, "https://workspace123.us-east-1.maas.aliyuncs.com")
            with patch.dict(os.environ, {"DASHSCOPE_BASE_URL": WORKSPACE_HOST + "/api/v1/"}):
                self.assertEqual(config.settings().base_url, WORKSPACE_HOST)
        with patch.dict(os.environ, {"DASHSCOPE_REGION": "ap-southeast-1", "DASHSCOPE_WORKSPACE_ID": "workspace123"}):
            self.assertEqual(config.settings().base_url, "https://workspace123.ap-southeast-1.maas.aliyuncs.com")
        for base in ("https://attacker.example.test", "http://exampleworkspace.us-east-1.maas.aliyuncs.com",
                     WORKSPACE_HOST + "?token=bad", "https://user:pass@exampleworkspace.us-east-1.maas.aliyuncs.com",
                     "https://workspace.ap-southeast-1.maas.aliyuncs.com"):
            with self.subTest(base=base), patch.dict(os.environ, {
                "DASHSCOPE_REGION": "us-east-1", "DASHSCOPE_BASE_URL": base,
            }), self.assertRaises(ValueError):
                config.settings()

    def test_legacy_us_unverified_model_and_smart_duration_block_live(self):
        with patch.object(self.api().httpx, "Client", side_effect=AssertionError("HTTP called")):
            for extra, duration, message in (({}, 7, "UNVERIFIED"),
                ({"DASHSCOPE_BASE_URL": WORKSPACE_HOST}, -1, "smart duration"),
                ({"DASHSCOPE_BASE_URL": WORKSPACE_HOST, "DASHSCOPE_MODEL": "wan-unverified"}, 7, "UNVERIFIED")):
                with self.subTest(extra=extra), patch.dict(os.environ, {"MODELSTUDIO_DRY_RUN": "false", **extra}):
                    with self.assertRaisesRegex(ValueError, message):
                        self.api().edit_wan3_video(**BASE_ARGUMENTS, duration=duration)
        with patch.dict(os.environ, {"DASHSCOPE_MODEL": "wan-unverified"}):
            output = self.api().edit_wan3_video(**BASE_ARGUMENTS, duration=7)
            self.assertEqual(output["model"], "wan-unverified")
            self.assertIsNone(output["estimated_cost_usd"])

    def test_dry_handle_never_becomes_a_live_task(self):
        job_id = self.api().edit_wan3_video(**BASE_ARGUMENTS)["job_id"]
        with patch.dict(os.environ, {"MODELSTUDIO_DRY_RUN": "false"}), patch.object(
            self.api().httpx, "Client", side_effect=AssertionError("HTTP called")
        ):
            self.assertEqual(self.api().get_task(job_id)["status"], "dry_run")

    def test_preview_licence_blocks_workspace_live_use_before_http(self):
        with patch.dict(os.environ, {"MODELSTUDIO_DRY_RUN": "false", "DASHSCOPE_BASE_URL": WORKSPACE_HOST}), patch.object(
            self.api().httpx, "Client", side_effect=AssertionError("HTTP called")
        ):
            for tool in TOOLS[:2]:
                with self.subTest(tool=tool), self.assertRaisesRegex(ValueError, "licence.*preview"):
                    dispatch("alibaba_modelstudio", tool, {**BASE_ARGUMENTS, "duration": 7})
            with self.assertRaisesRegex(ValueError, "licence.*preview"):
                self.api().get_task(TASK_ID)

    def test_malformed_task_ids_fail_before_http(self):
        with patch.object(self.api().httpx, "Client", side_effect=AssertionError("HTTP called")):
            for job_id in ("", "../task", "https://example.test/task", TASK_ID + "/", "not-a-task", True):
                with self.subTest(job_id=job_id), self.assertRaises(ValueError):
                    self.api().get_task(job_id)

    def test_mock_submit_poll_download_and_cached_provenance(self):
        requests = []
        signed_video = VIDEO + "?signature=do-not-persist"
        def respond(request):
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"output": {"task_id": TASK_ID, "task_status": "PENDING"}})
            if request.url.host == "media.example.test":
                return httpx.Response(200, content=b"mock-mp4")
            return httpx.Response(200, json={
                "output": {"task_id": TASK_ID, "task_status": "SUCCEEDED", "video_url": signed_video},
                "usage": {"duration": 12, "input_video_duration": 5, "output_video_duration": 7, "fps": 24},
            })
        with self.mock_http(respond) as directory:
            result = dispatch("alibaba_modelstudio", "extend_wan3_video", {**BASE_ARGUMENTS, "duration": 7})
            self.assertEqual(result["job_id"], TASK_ID)
            self.assertEqual(result["status"], "queued")
            submitted = json.loads(requests[0].content)
            self.assertEqual(requests[0].url.path, "/api/v1/services/aigc/video-generation/video-synthesis")
            self.assertEqual(requests[0].headers["X-DashScope-Async"], "enable")
            self.assertEqual(requests[0].headers["Authorization"], "Bearer dummy-test-key")
            self.assertEqual(submitted["parameters"]["duration"], 7)
            with patch.dict(os.environ, {"DASHSCOPE_WORKSPACE_ID": "changed", "DASHSCOPE_BASE_URL": ""}):
                polled = self.api().get_task(TASK_ID)
            self.assertEqual(polled["status"], "succeeded")
            self.assertEqual(polled["usage"]["duration"], 12)
            self.assertAlmostEqual(polled["actual_cost_usd"], 1.9803)
            self.assertEqual(Path(polled["output_path"]).read_bytes(), b"mock-mp4")
            self.assertEqual(requests[1].url.host, "exampleworkspace.us-east-1.maas.aliyuncs.com")
            self.assertNotIn("Authorization", requests[-1].headers)
            count = len(requests)
            self.assertEqual(self.api().get_task(TASK_ID)["output_path"], polled["output_path"])
            self.assertEqual(len(requests), count)
            metadata = list(directory.glob("video/.tasks/alibaba_modelstudio/*.json"))
            self.assertEqual(len(metadata), 1)
            saved = metadata[0].read_text()
            self.assertNotIn("signature=", saved)
            self.assertNotIn("dummy-test-key", saved)
            self.assertFalse(json.loads(saved)["training_eligible"])

    def test_async_statuses_and_errors_are_preserved(self):
        states = (("PENDING", "queued"), ("RUNNING", "running"), ("FAILED", "failed"),
                  ("CANCELED", "cancelled"), ("UNKNOWN", "unknown"))
        for vendor, expected in states:
            def respond(request):
                return httpx.Response(200, json={"output": {"task_id": TASK_ID, "task_status": vendor,
                    "code": "VendorCode", "message": "Task cannot complete"}})
            with self.subTest(state=vendor), self.mock_http(respond):
                result = self.api().get_task(TASK_ID)
                self.assertEqual(result["status"], expected)
                if expected in {"failed", "cancelled", "unknown"}:
                    self.assertEqual(result["error_code"], "VendorCode")

    def test_actual_usage_missing_or_invalid_remains_unknown(self):
        for usage in ({}, {"duration": -1}, {"duration": True}, {"duration": 999},
                      {"duration": "12"}):
            def respond(request):
                if request.method == "POST":
                    return httpx.Response(200, json={"output": {"task_id": TASK_ID, "task_status": "PENDING"}})
                return httpx.Response(200, json={"output": {
                    "task_id": TASK_ID, "task_status": "SUCCEEDED", "video_url": VIDEO,
                }, "usage": usage})
            with self.subTest(usage=usage), self.mock_http(respond):
                self.api().edit_wan3_video(**BASE_ARGUMENTS, duration=7)
                self.assertIsNone(self.api().get_task(TASK_ID, download=False)["actual_cost_usd"])

    def test_metadata_failure_retains_paid_task_and_submission_is_not_retried(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"output": {"task_id": TASK_ID, "task_status": "PENDING"}})
        with self.mock_http(respond), patch.object(self.api(), "_write_metadata", side_effect=OSError("disk full")):
            result = self.api().edit_wan3_video(**BASE_ARGUMENTS, duration=7)
            self.assertEqual(result["job_id"], TASK_ID)
            self.assertIn("metadata", result["warning"])
        self.assertEqual(len(requests), 1)

    def test_post_http_failure_never_retries(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(503, json={"code": "Unavailable", "message": "Try later"})
        with self.mock_http(respond), self.assertRaises(RuntimeError):
            self.api().edit_wan3_video(**BASE_ARGUMENTS, duration=7)
        self.assertEqual(len(requests), 1)

    def test_download_rejects_empty_content_and_unsafe_url(self):
        for url in (VIDEO, "file:///tmp/video.mp4", "https://user:pass@media.example.test/v.mp4"):
            def respond(request):
                if request.url.host == "media.example.test":
                    return httpx.Response(200, content=b"")
                return httpx.Response(200, json={"output": {
                    "task_id": TASK_ID, "task_status": "SUCCEEDED", "video_url": url,
                }})
            with self.subTest(url=url), self.mock_http(respond) as directory:
                with self.assertRaises((ValueError, RuntimeError)):
                    self.api().get_task(TASK_ID)
                self.assertEqual(list(directory.glob("video/*.mp4")), [])
                self.assertEqual(list(directory.glob("video/*.part")), [])

    def test_missing_task_id_and_unrecognized_state_do_not_claim_success(self):
        for payload in ({"output": {}}, {"output": {"task_id": "bad", "task_status": "PENDING"}},
                        {"output": {"task_id": TASK_ID, "task_status": "NEW_UNDOCUMENTED"}}):
            with self.subTest(payload=payload), self.mock_http(lambda request: httpx.Response(200, json=payload)):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.api().edit_wan3_video(**BASE_ARGUMENTS, duration=7)
