"""Offline behavioral checks for the fal provider; no real provider traffic."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from providers.contracts import validate_tool_arguments
from providers.fal import api, queue, wan
from providers.registry import dispatch, generate_schemas, schema_from_callable
from providers.catalog import get_provider
from lambdas.handler import handler as lambda_handler


HTTPX_CLIENT = httpx.Client
MODEL_21, MODEL_22 = wan.MODELS
SOURCE_URL = "https://media.example.test/private-source.mp4?signature=test-only"
IMAGE_URL = "https://media.example.test/reference.png?signature=test-only"
RESULT_URL = "https://cdn.example.test/video.mp4"


class BrokenDownload(httpx.SyncByteStream):
    def __iter__(self):
        yield b"partial-video"
        raise httpx.ReadError("interrupted download")


class FalProviderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="fal-offline-")
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(
            os.environ,
            {
                "FAL_DRY_RUN": "false",
                "FAL_KEY": "offline-test-key",
                "RENDERHAUS_MEDIA_DIR": self.directory.name,
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.requests = []
        self.routes = []
        self.transport = httpx.MockTransport(self.handle_request)
        client_patch = patch.object(queue.httpx, "Client", self.mock_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        stream_patch = patch.object(api.httpx, "stream", self.mock_stream)
        stream_patch.start()
        self.addCleanup(stream_patch.stop)

    def mock_client(self, *args, **kwargs):
        return HTTPX_CLIENT(*args, transport=self.transport, **kwargs)

    @contextmanager
    def mock_stream(self, method, url, **kwargs):
        with HTTPX_CLIENT(transport=self.transport) as client:
            with client.stream(method, url, **kwargs) as response:
                yield response

    def handle_request(self, request):
        self.requests.append(request)
        self.assertTrue(self.routes, f"Unexpected HTTP request: {request.method} {request.url}")
        method, url, response = self.routes.pop(0)
        self.assertEqual((request.method, str(request.url)), (method, url))
        return response

    def route(self, method, url, payload, status=200):
        self.routes.append((method, url, httpx.Response(status, json=payload)))

    def job(self, model=MODEL_21, mode="depth", request_id="request_1"):
        endpoint = model if mode == "freeform" else f"{model}/{mode}"
        return f"{endpoint}:{request_id}"

    def result_routes(self, payload, status=200, model=MODEL_21):
        base = f"https://queue.fal.run/{model}/requests/request_1"
        self.route("GET", base + "/status", {"status": "COMPLETED"})
        self.route("GET", base, payload, status)

    def assert_licensed(self, output):
        self.assertIs(output["training_eligible"], True)
        self.assertEqual(output["weights_license"], "Apache-2.0")

    def test_invalid_argument_types_fail_before_http(self):
        cases = [
            {"prompt": 42},
            {"prompt": "p", "num_frames": True},
            {"prompt": "p", "frames_per_second": 16.5},
            {"prompt": "p", "resolution": 720},
            {"prompt": "p", "seed": "1"},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                api._submit("text_to_video", arguments)
        for references in ("https://example.test/image.png", [3], [True]):
            with self.subTest(references=references), self.assertRaises(ValueError):
                api.reference_to_video(references, "p")
        with self.assertRaises(ValueError):
            api.video_to_video(SOURCE_URL, "p", preprocess="true")
        self.assertEqual(self.requests, [])

    def test_bounds_and_choices_fail_before_http(self):
        for field, values in {
            "num_frames": (80, 242),
            "frames_per_second": (4, 31),
            "resolution": ("1080p",),
            "aspect_ratio": ("2:1",),
            "model": ("unknown", MODEL_21 + "/../../evil"),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    api.text_to_video("p", **{field: value})
        for ratio in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                api.video_to_video(
                    SOURCE_URL, "p", edit_mode="outpainting", expand_left=True, expand_ratio=ratio
                )
        self.assertEqual(self.requests, [])

    def test_valid_frame_and_fps_boundaries_work_in_dry_run(self):
        os.environ["FAL_DRY_RUN"] = "true"
        for frames in (81, 241):
            for fps in (5, 30):
                with self.subTest(frames=frames, fps=fps):
                    self.assertEqual(
                        api.text_to_video("p", num_frames=frames, frames_per_second=fps)["status"],
                        "dry_run",
                    )
        self.assertEqual(self.requests, [])

    def test_schema_rejects_unknown_and_missing_fields_before_http(self):
        for arguments in ({"prompt": "p", "duration": 5}, {}, {"prompt": ""}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                api._submit("text_to_video", arguments)
        with self.assertRaises(ValueError):
            api._submit("image_to_video", {"prompt": "p"})
        with self.assertRaises(ValueError):
            api.get_video_task(self.job(), download="true")
        self.assertEqual(self.requests, [])

    def test_blank_prompt_and_missing_references_are_rejected(self):
        for call in (
            lambda: api.text_to_video("  \n"),
            lambda: api.reference_to_video([], "p"),
            lambda: api.image_to_video("", "p"),
            lambda: api.video_to_video("file:///tmp/video.mp4", "p"),
        ):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.requests, [])

    def test_inpainting_requires_exactly_one_mask(self):
        for fields in ({}, {"mask_video_url": SOURCE_URL, "mask_image_url": IMAGE_URL}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                api.video_to_video(SOURCE_URL, "p", edit_mode="inpainting", **fields)
        os.environ["FAL_DRY_RUN"] = "true"
        for mask in ("mask_video_url", "mask_image_url"):
            self.assertEqual(
                api.video_to_video(SOURCE_URL, "p", edit_mode="inpainting", **{mask: IMAGE_URL})[
                    "status"
                ],
                "dry_run",
            )
        self.assertEqual(self.requests, [])

    def test_mode_specific_fields_are_rejected(self):
        cases = [
            ("depth", {"mask_image_url": IMAGE_URL}),
            ("pose", {"expand_left": True}),
            ("reframe", {"ref_image_urls": [IMAGE_URL]}),
            ("outpainting", {"expand_left": True, "preprocess": True}),
            ("freeform", {"trim_borders": True}),
            ("inpainting", {"mask_image_url": IMAGE_URL, "zoom_factor": 1.2}),
        ]
        for mode, fields in cases:
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                api.video_to_video(SOURCE_URL, "p", edit_mode=mode, **fields)
        self.assertEqual(self.requests, [])

    def test_outpainting_requires_an_expansion_side(self):
        for fields in ({}, {"expand_left": False}, {"expand_ratio": 0.5}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                api.video_to_video(SOURCE_URL, "p", edit_mode="outpainting", **fields)
        self.assertEqual(self.requests, [])

    def test_native_submission_body_and_authorization(self):
        endpoint = MODEL_21 + "/outpainting"
        self.route(
            "POST",
            "https://queue.fal.run/" + endpoint,
            {"request_id": "request_1", "status": "IN_QUEUE"},
        )
        output = api.video_to_video(
            SOURCE_URL,
            "expand the scene",
            edit_mode="outpainting",
            expand_left=True,
            expand_ratio=0.4,
            frames_per_second=24,
            seed=10,
        )
        request = self.requests[0]
        body = json.loads(request.content)
        self.assertEqual(
            body,
            {
                "video_url": SOURCE_URL,
                "prompt": "expand the scene",
                "num_frames": 81,
                "frames_per_second": 24,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "expand_left": True,
                "expand_ratio": 0.4,
                "seed": 10,
                "match_input_num_frames": False,
                "match_input_frames_per_second": False,
            },
        )
        self.assertEqual(request.headers["Authorization"], "Key offline-test-key")
        self.assertEqual(request.headers["Content-Type"], "application/json")
        self.assertEqual(output["job_id"], endpoint + ":request_1")
        self.assertEqual(output["status"], "queued")
        self.assertEqual(output["estimated_cost_usd"], 0.405)
        self.assert_licensed(output)
        self.assertNotIn(SOURCE_URL, json.dumps(output))

    def test_reference_and_frame_urls_use_native_fields(self):
        self.route(
            "POST",
            "https://queue.fal.run/" + MODEL_21,
            {"request_id": "request_1", "status": "IN_PROGRESS"},
        )
        output = api.reference_to_video(
            [IMAGE_URL],
            "p",
            first_frame_url=IMAGE_URL,
            last_frame_url="data:image/png;base64,AA",
            negative_prompt="blur",
        )
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["ref_image_urls"], [IMAGE_URL])
        self.assertEqual(body["first_frame_url"], IMAGE_URL)
        self.assertEqual(body["last_frame_url"], "data:image/png;base64,AA")
        self.assertEqual(body["negative_prompt"], "blur")
        self.assertNotIn("model", body)
        self.assertNotIn(IMAGE_URL, json.dumps(output))

    def test_dry_run_default_and_arbitrary_truthy_values_never_call_http(self):
        del os.environ["FAL_DRY_RUN"]
        del os.environ["FAL_KEY"]
        self.assertEqual(api.text_to_video("p")["status"], "dry_run")
        for value in ("", "true", "1", "yes", "FALSE-ish"):
            with self.subTest(value=value):
                os.environ["FAL_DRY_RUN"] = value
                output = api.image_to_video(IMAGE_URL, "p")
                self.assertEqual(output["status"], "dry_run")
                self.assertNotIn(IMAGE_URL, json.dumps(output))
                self.assert_licensed(output)
        self.assertEqual(self.requests, [])

    def test_false_case_insensitive_enables_live_and_missing_key_fails(self):
        os.environ["FAL_DRY_RUN"] = "FALSE"
        del os.environ["FAL_KEY"]
        self.assertFalse(queue.dry_run())
        with self.assertRaisesRegex(RuntimeError, "FAL_KEY"):
            api.text_to_video("p")
        self.assertEqual(self.requests, [])

    def test_state_mapping_and_error_precedence(self):
        for state, expected in (
            ("IN_QUEUE", "queued"),
            ("IN_PROGRESS", "running"),
            ("COMPLETED", "succeeded"),
        ):
            self.assertEqual(queue.mapped_status({"status": state}), expected)
        for error in ({"error": "generation failed"}, {"error_type": "validation"}):
            self.assertEqual(queue.mapped_status({"status": "COMPLETED", **error}), "failed")
        for state in (None, "UNKNOWN", "FAILED"):
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                queue.mapped_status({"status": state})

    def test_cold_start_poll_uses_handle_and_app_root_without_metadata(self):
        self.route(
            "GET",
            f"https://queue.fal.run/{MODEL_22}/requests/request_1/status",
            {"status": "IN_PROGRESS", "queue_position": 3},
        )
        output = api.get_video_task(self.job(model=MODEL_22, mode="outpainting"))
        self.assertEqual(output["status"], "running")
        self.assertEqual(output["queue_position"], 3)
        self.assertEqual(output["endpoint_id"], MODEL_22 + "/outpainting")
        self.assertEqual(list(Path(self.directory.name).rglob("*")), [])
        self.assert_licensed(output)

    def test_queue_poll_does_not_fetch_result_before_completion(self):
        self.route(
            "GET",
            f"https://queue.fal.run/{MODEL_21}/requests/request_1/status",
            {"status": "IN_QUEUE", "queue_position": 7},
        )
        output = api.get_video_task(self.job())
        self.assertEqual(output["status"], "queued")
        self.assertEqual(len(self.requests), 1)

    def test_completed_result_fetch_and_download(self):
        self.result_routes({"video": {"url": RESULT_URL}, "seed": 9})
        self.routes.append(("GET", RESULT_URL, httpx.Response(200, content=b"test-mp4-bytes")))
        output = api.get_video_task(self.job(), download=True)
        self.assertEqual(output["status"], "succeeded")
        self.assertTrue(output["downloaded"])
        self.assertEqual(Path(output["output_path"]).read_bytes(), b"test-mp4-bytes")
        self.assertEqual(output["seed"], 9)
        self.assert_licensed(output)
        self.assertNotIn("authorization", self.requests[-1].headers)
        metadata = list(Path(self.directory.name).rglob("*.json"))
        self.assertEqual(len(metadata), 1)
        self.assertEqual(json.loads(metadata[0].read_text())["job_id"], self.job())
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])

    def test_completed_without_download_returns_url_and_no_output_file(self):
        self.result_routes({"video": {"url": RESULT_URL}})
        output = api.get_video_task(self.job())
        self.assertEqual(output["video_url"], RESULT_URL)
        self.assertIsNone(output["output_path"])
        self.assertFalse(output["downloaded"])
        self.assertEqual(len(self.requests), 2)

    def test_existing_download_is_reused(self):
        self.result_routes({"video": {"url": RESULT_URL}})
        self.routes.append(("GET", RESULT_URL, httpx.Response(200, content=b"test-mp4")))
        first = api.get_video_task(self.job(), download=True)
        self.result_routes({"video": {"url": RESULT_URL}})
        second = api.get_video_task(self.job(), download=True)
        self.assertEqual(first["output_path"], second["output_path"])
        self.assertEqual(len(self.requests), 5)

    def test_partial_download_failure_cleans_temporary_artifact(self):
        self.result_routes({"video": {"url": RESULT_URL}})
        self.routes.append(("GET", RESULT_URL, httpx.Response(200, stream=BrokenDownload())))
        with self.assertRaises(httpx.ReadError):
            api.get_video_task(self.job(), download=True)
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])

    def test_concurrent_downloads_of_same_job_keep_complete_artifact(self):
        barrier = threading.Barrier(2)

        class OverlappingStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"video-head"
                barrier.wait(timeout=5)
                yield b"video-tail"

        @contextmanager
        def stream(*args, **kwargs):
            yield httpx.Response(
                200, request=httpx.Request("GET", RESULT_URL), stream=OverlappingStream()
            )

        output = Path(self.directory.name) / "same-job.mp4"
        with (
            patch.object(api.httpx, "stream", stream),
            ThreadPoolExecutor(max_workers=2) as workers,
        ):
            futures = [workers.submit(api._download, RESULT_URL, output) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(output.read_bytes(), b"video-headvideo-tail")
        self.assertEqual(list(Path(self.directory.name).glob("*.part")), [])

    def test_empty_download_is_rejected_and_cleaned(self):
        self.result_routes({"video": {"url": RESULT_URL}})
        self.routes.append(("GET", RESULT_URL, httpx.Response(200, content=b"")))
        with self.assertRaisesRegex(RuntimeError, "empty video"):
            api.get_video_task(self.job(), download=True)
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])

    def test_http_errors_are_distinct_from_failed_jobs(self):
        self.route(
            "GET",
            f"https://queue.fal.run/{MODEL_21}/requests/request_1/status",
            {"detail": "bad key"},
            401,
        )
        with self.assertRaises(queue.FalAPIError) as error:
            api.get_video_task(self.job())
        self.assertEqual(error.exception.status_code, 401)
        self.route(
            "GET",
            f"https://queue.fal.run/{MODEL_21}/requests/request_1/status",
            {"status": "COMPLETED", "error": "model failure", "error_type": "inference"},
        )
        output = api.get_video_task(self.job())
        self.assertEqual(output["status"], "failed")
        self.assertEqual(output["error"], "model failure")
        self.assertEqual(output["error_type"], "inference")

    def test_result_validation_http_errors_become_failed_job(self):
        for code in (400, 422):
            with self.subTest(code=code):
                self.result_routes({"detail": "invalid input"}, status=code)
                self.assertEqual(api.get_video_task(self.job())["status"], "failed")

    def test_result_auth_notfound_and_rate_limit_remain_tool_errors(self):
        for code in (401, 403, 404, 429, 500):
            with self.subTest(code=code):
                self.result_routes({"detail": "provider request failed"}, status=code)
                with self.assertRaises(queue.FalAPIError) as error:
                    api.get_video_task(self.job())
                self.assertEqual(error.exception.status_code, code)

    def test_result_error_payload_becomes_failed_job(self):
        self.result_routes({"error": "unsafe request", "error_type": "content_policy"})
        output = api.get_video_task(self.job())
        self.assertEqual(output["status"], "failed")
        self.assertEqual(output["error_type"], "content_policy")

    def test_malformed_completed_results_are_rejected(self):
        for payload in (
            {},
            {"video": None},
            {"video": "url"},
            {"video": {}},
            {"video": {"url": 3}},
            {"video": {"url": "file:///tmp/video"}},
            {"video": {"url": "https:///missing-host"}},
            [],
        ):
            with self.subTest(payload=payload):
                self.result_routes(payload)
                with self.assertRaises(RuntimeError):
                    api.get_video_task(self.job())
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])

    def test_non_json_provider_response_is_rejected(self):
        url = "https://queue.fal.run/" + MODEL_21
        self.routes.append(("POST", url, httpx.Response(502, text="upstream failed")))
        with self.assertRaises(queue.FalAPIError) as error:
            api.text_to_video("p")
        self.assertEqual(error.exception.status_code, 502)

    def test_submission_requires_safe_nonempty_request_id(self):
        for request_id in (None, "", 3, "../elsewhere", "a/b", "a?key=value", "a\\b"):
            with self.subTest(request_id=request_id):
                self.route(
                    "POST",
                    "https://queue.fal.run/" + MODEL_21,
                    {"request_id": request_id, "status": "IN_QUEUE"},
                )
                with self.assertRaises((ValueError, RuntimeError)):
                    api.text_to_video("p")
        self.assertEqual(list(Path(self.directory.name).rglob("*.json")), [])

    def test_invalid_job_ids_and_unknown_endpoints_fail_before_http(self):
        for handle in (
            "request_1",
            "unknown:request_1",
            MODEL_21 + "/unknown:request_1",
            self.job(request_id="../escape"),
            self.job(request_id="a/b"),
            self.job(request_id="a?query"),
            self.job(request_id=""),
        ):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                api.get_video_task(handle)
        self.assertEqual(self.requests, [])

    def test_invalid_handles_are_rejected_even_during_dry_run(self):
        os.environ["FAL_DRY_RUN"] = "true"
        for handle in ("request_1", "unknown:request_1", self.job(request_id="../escape")):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                api.get_video_task(handle)
        output = api.get_video_task(self.job())
        self.assertEqual(output["status"], "dry_run")
        self.assert_licensed(output)
        self.assertEqual(self.requests, [])

    def test_reframe_can_omit_prompt_and_keeps_requested_length_and_fps(self):
        self.route(
            "POST",
            f"https://queue.fal.run/{MODEL_21}/reframe",
            {"request_id": "request_1", "status": "IN_QUEUE"},
        )
        output = api.video_to_video(
            SOURCE_URL, edit_mode="reframe", zoom_factor=1.2, trim_borders=True
        )
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["prompt"], "")
        self.assertEqual(body["zoom_factor"], 1.2)
        self.assertTrue(body["trim_borders"])
        self.assertFalse(body["match_input_num_frames"])
        self.assertFalse(body["match_input_frames_per_second"])
        self.assertEqual(output["status"], "queued")
        with self.assertRaisesRegex(ValueError, "prompt"):
            api.video_to_video(SOURCE_URL)

    def test_immediately_completed_submission_still_requires_result_poll(self):
        self.route(
            "POST",
            "https://queue.fal.run/" + MODEL_21,
            {"request_id": "request_1", "status": "COMPLETED"},
        )
        output = api.text_to_video("p")
        self.assertEqual(output["status"], "queued")
        self.assertNotIn("video_url", output)
        self.assertNotIn("output_path", output)
        self.assertEqual(len(self.requests), 1)

    def test_documented_submit_response_can_omit_status(self):
        self.route("POST", "https://queue.fal.run/" + MODEL_21, {"request_id": "request_1"})
        output = api.text_to_video("p")
        self.assertEqual(output["status"], "queued")
        self.assertEqual(output["job_id"], MODEL_21 + ":request_1")

    def test_freeform_edit_passes_explicit_task_and_mask_to_native_endpoint(self):
        with self.assertRaisesRegex(ValueError, "explicit task"):
            api.video_to_video(SOURCE_URL, "p", edit_mode="freeform", mask_image_url=IMAGE_URL)
        with self.assertRaisesRegex(ValueError, "task=inpainting"):
            api.video_to_video(
                SOURCE_URL, "p", edit_mode="freeform", task="depth", mask_image_url=IMAGE_URL
            )
        self.assertEqual(self.requests, [])
        self.route("POST", "https://queue.fal.run/" + MODEL_21, {"request_id": "request_1"})
        api.video_to_video(
            SOURCE_URL, "p", edit_mode="freeform", task="inpainting", mask_image_url=IMAGE_URL
        )
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["task"], "inpainting")
        self.assertEqual(body["mask_image_url"], IMAGE_URL)
        self.assertNotIn("edit_mode", body)

    def test_specialized_edit_rejects_freeform_task_before_http(self):
        with self.assertRaisesRegex(ValueError, "task is not supported"):
            api.video_to_video(SOURCE_URL, "p", edit_mode="pose", task="depth")
        self.assertEqual(self.requests, [])

    def test_authenticated_queue_request_cannot_target_another_host(self):
        for url in (
            "https://attacker.test/requests/id",
            "http://queue.fal.run/model",
            "https://queue.fal.run.attacker.test/model",
            "https://queue.fal.run@attacker.test/model",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                queue.request("GET", url)
        self.assertEqual(self.requests, [])

    def test_unconfirmed_pricing_blocks_live_submission_but_allows_dry_run(self):
        for mode in ("freeform", "pose"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "pricing"):
                    api.video_to_video(
                        SOURCE_URL,
                        "p",
                        model=MODEL_22,
                        edit_mode=mode,
                        task="depth" if mode == "freeform" else None,
                    )
                with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
                    self.assertEqual(
                        api.video_to_video(
                            SOURCE_URL,
                            "p",
                            model=MODEL_22,
                            edit_mode=mode,
                            task="depth" if mode == "freeform" else None,
                        )["status"],
                        "dry_run",
                    )
        for resolution in ("auto", "240p", "360p"):
            with self.subTest(resolution=resolution), self.assertRaisesRegex(ValueError, "pricing"):
                api.text_to_video("p", resolution=resolution)
        self.assertEqual(self.requests, [])

    def test_static_catalog_has_no_network_and_exposes_licensing_and_unknown_rates(self):
        del os.environ["FAL_KEY"]
        catalog = api.list_fal_models()
        self.assertEqual(catalog["status"], "ok")
        self.assertEqual(len(catalog["models"]), 9)
        self.assertEqual(len(catalog["endpoints"]), 19)
        self.assertEqual(catalog["selected_model"], "alibaba/wan-3.0/text-to-video")
        for item in catalog["models"] + catalog["endpoints"]:
            if item["id"].startswith(("fal-ai/vidu/q4/", "alibaba/wan-3.0/", "fal-ai/kling-video/v3/", "mirelo-ai/")):
                self.assertIs(item["training_eligible"], False)
                self.assertNotEqual(item["weights_license"], "Apache-2.0")
            else:
                self.assert_licensed(item)
        endpoints = {item["id"]: item for item in catalog["endpoints"]}
        self.assertEqual(endpoints["fal-ai/kling-video/v3/pro/motion-control"]["usd_per_unit"], "0.168")
        self.assertFalse(endpoints[MODEL_22]["pricing_confirmed"])
        self.assertFalse(endpoints[MODEL_22 + "/pose"]["pricing_confirmed"])
        self.assertEqual(
            endpoints[MODEL_21]["usd_per_unit_by_resolution"],
            {"480p": "0.04", "580p": "0.06", "720p": "0.08"},
        )
        self.assertEqual(self.requests, [])

    def test_provider_spec_and_gateway_contract(self):
        spec = get_provider("fal")
        self.assertEqual(spec.module_path, "providers.fal.api")
        self.assertIn("FAL_KEY", spec.env_keys)
        self.assertEqual(spec.default_env["FAL_DRY_RUN"], "true")
        schemas = {tool["name"]: tool for tool in generate_schemas(spec)}
        self.assertEqual(set(schemas), set(api.TOOL_HANDLERS))
        self.assertEqual(
            schemas["reference_to_video"]["inputSchema"]["properties"]["ref_image_urls"]["items"][
                "type"
            ],
            "string",
        )
        self.assertIn(
            "81 to 241",
            schemas["text_to_video"]["inputSchema"]["properties"]["num_frames"]["description"],
        )
        with self.assertRaises(ValueError):
            dispatch("fal", "text_to_video", {"prompt": "p", "num_frames": 80})
        self.assertEqual(self.requests, [])

    def test_committed_gateway_schema_matches_generated_contract(self):
        root = Path(api.__file__).resolve().parents[2]
        committed = json.loads((root / "configs/gateway/fal.tools.json").read_text())
        self.assertEqual(committed, generate_schemas(get_provider("fal")))

    def test_lambda_gateway_invocation_uses_fal_provider_and_context_tool(self):
        os.environ.update(FAL_DRY_RUN="true", RENDERHAUS_PROVIDER="fal")
        context = SimpleNamespace(
            client_context=SimpleNamespace(
                custom={
                    "bedrockAgentCoreToolName": "Fal___reference_to_video",
                }
            )
        )
        output = lambda_handler({"prompt": "p", "ref_image_urls": [IMAGE_URL]}, context)
        self.assertEqual(output["provider"], "fal")
        self.assertEqual(output["status"], "dry_run")
        self.assertEqual(output["mode"], "reference_to_video")
        self.assert_licensed(output)
        invalid = lambda_handler({"prompt": "p", "ref_image_urls": []}, context)
        self.assertEqual(invalid["error_type"], "ValueError")
        self.assertIn("reference image", invalid["error"])
        self.assertEqual(self.requests, [])

    def test_cross_field_validation_through_shared_contract(self):
        schema = schema_from_callable("video_to_video", api.video_to_video)["inputSchema"]
        with self.assertRaisesRegex(ValueError, "mask"):
            validate_tool_arguments(
                "fal",
                "video_to_video",
                {"prompt": "p", "video_url": SOURCE_URL, "edit_mode": "inpainting"},
                schema,
            )
        cleaned = validate_tool_arguments(
            "fal",
            "video_to_video",
            {
                "prompt": "",
                "video_url": SOURCE_URL,
                "edit_mode": "reframe",
                "zoom_factor": 1.3,
                "mask_image_url": None,
            },
            schema,
        )
        self.assertNotIn("mask_image_url", cleaned)


if __name__ == "__main__":
    unittest.main()
