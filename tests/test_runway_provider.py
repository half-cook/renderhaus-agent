from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx

from providers.runway import api
from providers.runway.contracts import (
    IMAGE_1080_RATIOS,
    IMAGE_720_RATIOS,
    I2V_RATIOS,
    MAX_DATA_URI_BYTES,
    T2V_RATIOS,
    validate_runway_arguments,
)


CLIENT = httpx.Client
JOB_ID = "8bfc9b2a-8a4f-4ed8-a2e7-f7cf786faa9b"
IMAGE_URL = "https://assets.example.com/input.png"
VIDEO_URL = "https://assets.example.com/input.mp4"
OUTPUT_VIDEO = "https://cdn.example.com/output.mp4?signature=private"
OUTPUT_IMAGE = "https://cdn.example.com/output.png?signature=private"


class RunwayProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.media_dir = Path(temporary.name)
        self.env = patch.dict(
            os.environ,
            {
                "RENDERHAUS_MEDIA_DIR": str(self.media_dir),
                "RUNWAY_DRY_RUN": "true",
                "RUNWAYML_API_SECRET": "mock-secret",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        blocker = patch(
            "providers.runway.api.httpx.Client", side_effect=AssertionError("Unexpected HTTP")
        )
        self.blocker = blocker.start()
        self.addCleanup(blocker.stop)

    @contextmanager
    def http(self, handler):
        requests = []

        def route(request):
            requests.append(request)
            return handler(request)

        def client(*args, **kwargs):
            return CLIENT(*args, **kwargs, transport=httpx.MockTransport(route))

        with patch("providers.runway.api.httpx.Client", side_effect=client):
            yield requests

    def live(self) -> None:
        os.environ["RUNWAY_DRY_RUN"] = "false"

    def created(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": JOB_ID, "estimatedCost": {"credits": 60}})

    def task(self, status: str, **fields) -> httpx.Response:
        return httpx.Response(200, json={"id": JOB_ID, "status": status, **fields})

    def test_gateway_tools_are_explicit_synchronous_queued_operations(self) -> None:
        self.assertEqual(
            set(api.GATEWAY_TOOLS),
            {
                "text_to_video",
                "image_to_video",
                "video_to_video",
                "text_to_image",
                "image_to_image",
                "get_runway_task",
                "list_runway_models",
            },
        )
        self.assertEqual(set(api.GATEWAY_TOOLS), set(api.TOOL_HANDLERS))
        self.assertTrue(
            all(not inspect.iscoroutinefunction(fn) for fn in api.TOOL_HANDLERS.values())
        )

    def test_dry_run_default_requires_explicit_false_to_submit(self) -> None:
        os.environ.pop("RUNWAY_DRY_RUN")
        os.environ.pop("RUNWAYML_API_SECRET")
        self.assertTrue(api.dry_run())
        result = api.text_to_video("A camera moves over a mountain")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["provider"], "runway")
        self.assertNotIn("output_path", result)
        self.assertNotIn("video_url", result)
        self.assertNotIn("image_url", result)
        self.blocker.assert_not_called()
        for value in ("", "0", "yes", "false "):
            os.environ["RUNWAY_DRY_RUN"] = value
            self.assertTrue(api.dry_run())
        self.live()
        self.assertFalse(api.dry_run())

    def test_every_submission_mode_validates_and_runs_without_http_in_dry_mode(self) -> None:
        calls = [
            lambda: api.text_to_video("A mountain"),
            lambda: api.image_to_video(IMAGE_URL, "Move the camera"),
            lambda: api.video_to_video(VIDEO_URL, "Make the sky blue", 4.5),
            lambda: api.text_to_image("A mountain"),
            lambda: api.image_to_image(IMAGE_URL, "Make the sky blue", model="gen4_image_turbo"),
        ]
        for call in calls:
            result = call()
            self.assertEqual(result["status"], "dry_run")
            self.assertNotIn("output_path", result)
        self.blocker.assert_not_called()

    def test_dry_id_stays_dry_after_env_change_without_metadata(self) -> None:
        result = api.text_to_image("A mountain")
        for path in self.media_dir.rglob("*.json"):
            path.unlink()
        self.live()
        polled = api.get_runway_task(result["job_id"], download=True)
        self.assertEqual(polled["status"], "dry_run")
        self.assertNotIn("output_path", polled)
        self.blocker.assert_not_called()

    def test_dry_mode_does_not_query_an_existing_live_job(self) -> None:
        result = api.get_runway_task(JOB_ID)
        self.assertEqual(result["status"], "dry_run")
        self.blocker.assert_not_called()

    def test_text_to_video_uses_fixed_api_auth_version_and_camelcase_body(self) -> None:
        self.live()
        os.environ["RUNWAY_BASE_URL"] = "https://untrusted.example.com"
        with self.http(self.created) as requests:
            result = api.text_to_video("A mountain", duration_seconds=10, ratio="720:1280", seed=42)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(str(request.url), api.API_BASE + "/text_to_video")
        self.assertEqual(request.headers["authorization"], "Bearer mock-secret")
        self.assertEqual(request.headers["x-runway-version"], "2024-11-06")
        self.assertEqual(
            json.loads(request.content),
            {
                "model": "gen4.5",
                "promptText": "A mountain",
                "duration": 10,
                "ratio": "720:1280",
                "seed": 42,
            },
        )
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["poll_interval_seconds"], 5)
        self.assertEqual(result["estimated_cost"], {"credits": 60})
        self.assertNotIn("output_path", result)
        metadata = list((self.media_dir / "runway" / ".tasks").glob("*.json"))
        self.assertEqual(len(metadata), 1)
        self.assertNotIn("prompt", metadata[0].read_text())

    def test_image_to_video_sends_a_prompt_image_uri(self) -> None:
        self.live()
        with self.http(self.created) as requests:
            api.image_to_video(IMAGE_URL, "Pan right", ratio="960:960")
        self.assertEqual(str(requests[0].url), api.API_BASE + "/image_to_video")
        self.assertEqual(
            json.loads(requests[0].content),
            {
                "model": "gen4.5",
                "promptText": "Pan right",
                "promptImage": IMAGE_URL,
                "duration": 5,
                "ratio": "960:960",
            },
        )

    def test_aleph_uses_video_uri_and_keyframe_without_duration_or_ratio(self) -> None:
        self.live()
        with self.http(self.created) as requests:
            result = api.video_to_video(
                VIDEO_URL,
                "Make the sky blue",
                4.5,
                reference_image_path_or_url=IMAGE_URL,
                reference_seconds=2,
                seed=0,
            )
        self.assertEqual(str(requests[0].url), api.API_BASE + "/video_to_video")
        self.assertEqual(
            json.loads(requests[0].content),
            {
                "model": "aleph2",
                "promptText": "Make the sky blue",
                "videoUri": VIDEO_URL,
                "keyframes": [{"uri": IMAGE_URL, "seconds": 2}],
                "seed": 0,
            },
        )
        self.assertEqual(result["video_duration_seconds"], 4.5)

    def test_aleph_optional_guidance_is_omitted(self) -> None:
        self.live()
        with self.http(self.created) as requests:
            api.video_to_video(VIDEO_URL, "Make the sky blue", 2)
        self.assertNotIn("keyframes", json.loads(requests[0].content))

    def test_image_tools_share_text_to_image_endpoint_with_reference_images(self) -> None:
        self.live()
        with self.http(self.created) as requests:
            api.text_to_image("A mountain", ratio="1920:1080", seed=4294967295)
            api.image_to_image(
                IMAGE_URL,
                "Use @style",
                model="gen4_image_turbo",
                reference_images=[{"uri": "runway://uploaded-token", "tag": "style"}],
            )
        for request in requests:
            self.assertEqual(str(request.url), api.API_BASE + "/text_to_image")
        self.assertNotIn("referenceImages", json.loads(requests[0].content))
        self.assertEqual(
            json.loads(requests[1].content)["referenceImages"],
            [{"uri": IMAGE_URL}, {"uri": "runway://uploaded-token", "tag": "style"}],
        )

    def test_model_listing_is_a_local_documented_catalog(self) -> None:
        self.live()
        result = api.list_runway_models()
        self.assertEqual(result["catalog_kind"], "documented")
        self.assertFalse(result["account_availability_verified"])
        self.assertEqual(result["verified_on"], "2026-10-08")
        self.assertEqual(
            {item["id"] for item in result["models"]},
            {"gen4.5", "aleph2", "gen4_image", "gen4_image_turbo"},
        )
        self.blocker.assert_not_called()

    def test_missing_secret_fails_before_client_creation(self) -> None:
        self.live()
        os.environ.pop("RUNWAYML_API_SECRET")
        with self.assertRaisesRegex(RuntimeError, "RUNWAYML_API_SECRET"):
            api.text_to_image("A mountain")
        self.blocker.assert_not_called()

    def test_invalid_input_is_rejected_before_even_dry_submission(self) -> None:
        cases = [
            {"prompt": ""},
            {"prompt": "\t "},
            {"prompt": 12},
            {"prompt": "a" * 1001},
            {"prompt": "😀" * 501},
            {"prompt": "a", "duration_seconds": True},
            {"prompt": "a", "duration_seconds": 5.0},
            {"prompt": "a", "duration_seconds": "5"},
            {"prompt": "a", "duration_seconds": 1},
            {"prompt": "a", "duration_seconds": 11},
            {"prompt": "a", "duration_seconds": float("nan")},
            {"prompt": "a", "duration_seconds": None},
            {"prompt": "a", "ratio": "16:9"},
            {"prompt": "a", "model": "gen4_turbo"},
            {"prompt": "a", "seed": True},
            {"prompt": "a", "seed": -1},
            {"prompt": "a", "seed": 4294967296},
            {"prompt": "a", "seed": 1.5},
            {"prompt": "a", "seed": float("inf")},
            {"prompt": "a", "seed": 10**1000},
        ]
        for arguments in cases:
            with self.subTest(
                arguments={key: type(value).__name__ for key, value in arguments.items()}
            ):
                with self.assertRaises(ValueError):
                    api.text_to_video(**arguments)
        self.blocker.assert_not_called()
        self.assertFalse((self.media_dir / "runway").exists())

    def test_prompt_length_is_measured_in_utf16_units(self) -> None:
        self.assertEqual(api.text_to_image("😀" * 500)["status"], "dry_run")
        with self.assertRaisesRegex(ValueError, "UTF-16"):
            api.text_to_image("😀" * 500 + "a")

    def test_ratios_and_models_follow_each_operations_contract(self) -> None:
        for ratio in T2V_RATIOS:
            api.text_to_video("A mountain", ratio=ratio)
        for ratio in I2V_RATIOS:
            api.image_to_video(IMAGE_URL, "Move", ratio=ratio)
        for ratio in IMAGE_720_RATIOS + IMAGE_1080_RATIOS:
            api.text_to_image("A mountain", ratio=ratio)
        with self.assertRaises(ValueError):
            api.text_to_video("A mountain", ratio="960:960")
        with self.assertRaises(ValueError):
            api.text_to_image("A mountain", ratio="1024:1024")
        with self.assertRaises(ValueError):
            api.text_to_image("A mountain", model="gen4_image_turbo")

    def test_bad_uris_do_not_trigger_network_or_host_file_reads(self) -> None:
        uris = [
            "http://assets.example.com/image.png",
            "https://127.0.0.1/image.png",
            "https://[::1]/image.png",
            "https://localhost/image.png",
            "https://assets.local/image.png",
            "https://assets.example.com:8443/image.png",
            "https://user:secret@assets.example.com/image.png",
            "https://assets.example.com/image.png#frame",
            "https://assets.example.com/image.png#",
            "https://assets.example.com/\nimage.png",
            "https://assets.example.com/\\image.png",
            "https://assets.example.com/" + "a" * 2048,
            "/etc/passwd",
            "file:///etc/passwd",
            "missing.png",
            "runway://uploaded-token#fragment",
            "runway://user@token",
            "data:image/png,abc",
            "data:image/gif;base64,YWJj",
            "data:video/mp4;base64,YWJj",
            "data:image/png;base64,",
            "data:image/png;base64,%%%%",
        ]
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("Unexpected local read")):
            for uri in uris:
                with self.subTest(uri=uri[:80]):
                    with self.assertRaises(ValueError):
                        api.image_to_image(uri, "Edit")
        self.blocker.assert_not_called()

    def test_supported_uri_forms_and_encoded_size_limit(self) -> None:
        api.image_to_image("data:image/png;base64,YWJj", "Edit")
        api.image_to_image("runway://uploaded-token", "Edit")
        api.video_to_video("data:video/mp4;base64,YWJj", "Edit", 2)
        for kind, call in (
            ("image/png", lambda uri: api.image_to_image(uri, "Edit")),
            ("video/mp4", lambda uri: api.video_to_video(uri, "Edit", 2)),
        ):
            uri = f"data:{kind};base64," + "A" * MAX_DATA_URI_BYTES
            with self.assertRaisesRegex(ValueError, "5 MiB"):
                call(uri)

    def test_aleph_duration_and_reference_bounds_are_strict(self) -> None:
        for duration in (1.99, 30.01, True, "2", float("nan"), float("inf")):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                api.video_to_video(VIDEO_URL, "Edit", duration)
        for seconds in (-0.1, 4.1, True, "1", float("nan"), float("inf")):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                api.video_to_video(
                    VIDEO_URL,
                    "Edit",
                    4,
                    reference_image_path_or_url=IMAGE_URL,
                    reference_seconds=seconds,
                )
        with self.assertRaisesRegex(ValueError, "requires reference_image"):
            api.video_to_video(VIDEO_URL, "Edit", 4, reference_seconds=1)
        api.video_to_video(
            VIDEO_URL, "Edit", 30, reference_image_path_or_url=IMAGE_URL, reference_seconds=30
        )
        self.blocker.assert_not_called()

    def test_image_reference_bounds_and_tags_are_validated(self) -> None:
        good = [{"uri": IMAGE_URL, "tag": "ref_one"}, {"uri": IMAGE_URL, "tag": "ref_two"}]
        api.image_to_image(IMAGE_URL, "Edit", reference_images=good)
        cases = [
            good + [{"uri": IMAGE_URL}],
            "bad",
            [IMAGE_URL],
            [{}],
            [{"uri": IMAGE_URL, "other": 1}],
            [{"uri": IMAGE_URL, "tag": "ab"}],
            [{"uri": IMAGE_URL, "tag": "Tag"}],
            [{"uri": IMAGE_URL, "tag": "bad-tag"}],
            [{"uri": IMAGE_URL, "tag": "a" * 17}],
            [{"uri": IMAGE_URL, "tag": "same"}, {"uri": IMAGE_URL, "tag": "same"}],
        ]
        for references in cases:
            with self.subTest(references=references), self.assertRaises(ValueError):
                api.image_to_image(IMAGE_URL, "Edit", reference_images=references)

    def test_shared_validator_rejects_unknown_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            validate_runway_arguments("text_to_video", {"prompt": "a", "outputFormat": "prores"})

    def test_paid_post_is_never_retried_and_upstream_text_is_not_reflected(self) -> None:
        self.live()
        for status in (400, 401, 429, 503):

            def failed(request):
                return httpx.Response(
                    status,
                    json={
                        "error": "mock-secret https://private.example.com/?token=secret",
                        "reason": "INPUT_PREPROCESSING.VALIDATION",
                    },
                    headers={"x-request-id": "request-123"},
                )

            with self.subTest(status=status), self.http(failed) as requests:
                with self.assertRaises(RuntimeError) as caught:
                    api.text_to_video("A mountain")
                self.assertEqual(len(requests), 1)
                self.assertIn(str(status), str(caught.exception))
                self.assertIn("INPUT_PREPROCESSING.VALIDATION", str(caught.exception))
                self.assertIn("request-123", str(caught.exception))
                self.assertNotIn("mock-secret", str(caught.exception))
                self.assertNotIn("private.example", str(caught.exception))

    def test_connection_failure_warns_before_resubmitting_without_retry(self) -> None:
        self.live()

        def failed(request):
            raise httpx.ConnectError("mock-secret", request=request)

        with self.http(failed) as requests:
            with self.assertRaisesRegex(RuntimeError, "before resubmitting"):
                api.text_to_video("A mountain")
        self.assertEqual(len(requests), 1)

    def test_invalid_provider_json_or_task_id_cannot_report_a_created_job(self) -> None:
        self.live()
        responses = [
            httpx.Response(200, content=b"invalid"),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={}),
            httpx.Response(200, json={"id": "../escape"}),
        ]
        for response in responses:
            with (
                self.subTest(response=response.content[:50]),
                self.http(lambda request: response) as requests,
            ):
                with self.assertRaises(RuntimeError):
                    api.text_to_image("A mountain")
                self.assertEqual(len(requests), 1)
        self.assertFalse((self.media_dir / "runway").exists())

    def test_missing_local_metadata_does_not_block_a_successful_submission(self) -> None:
        self.live()
        with (
            self.http(self.created),
            patch(
                "providers.runway.api.tempfile.NamedTemporaryFile", side_effect=OSError("read only")
            ),
        ):
            result = api.text_to_image("A mountain")
        self.assertEqual(result["job_id"], JOB_ID)
        self.assertEqual(result["status"], "queued")

    def test_polls_once_and_normalizes_all_documented_statuses(self) -> None:
        self.live()
        for provider_status, status in api.STATE_MAP.items():
            fields = {"progress": 0.25} if provider_status == "RUNNING" else {}
            if provider_status == "FAILED":
                fields = {
                    "failureCode": "INPUT_PREPROCESSING.VALIDATION",
                    "failure": "private reflected prompt",
                }
            if provider_status == "SUCCEEDED":
                fields = {"output": [OUTPUT_VIDEO]}
            with (
                self.subTest(provider_status=provider_status),
                self.http(lambda request: self.task(provider_status, **fields)) as requests,
            ):
                result = api.get_runway_task(JOB_ID)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].method, "GET")
            self.assertEqual(str(requests[0].url), api.API_BASE + "/tasks/" + JOB_ID)
            self.assertEqual(result["status"], status)
            if status in {"queued", "running"}:
                self.assertEqual(result["poll_interval_seconds"], 5)
            else:
                self.assertNotIn("poll_interval_seconds", result)
            if status == "failed":
                self.assertEqual(result["failure_code"], "INPUT_PREPROCESSING.VALIDATION")
                self.assertNotIn("private reflected prompt", json.dumps(result))

    def test_stateless_poll_infers_images_and_videos_from_urls(self) -> None:
        self.live()
        for kind, url in (("image", OUTPUT_IMAGE), ("video", OUTPUT_VIDEO)):
            with (
                self.subTest(kind=kind),
                self.http(lambda request: self.task("SUCCEEDED", output=[url])),
                patch("providers.runway.api._read_task_meta", return_value={}),
            ):
                result = api.get_runway_task(JOB_ID)
            self.assertEqual(result["media_kind"], kind)
            self.assertEqual(result[f"{kind}_url"], url)
            self.assertEqual(result["assets"], [{"kind": kind, "url": url}])
            self.assertIsNone(result["model"])
            self.assertNotIn("output_path", result)

    def test_stateless_poll_uses_unauthenticated_content_type_for_extensionless_output(
        self,
    ) -> None:
        self.live()
        url = "https://cdn.example.com/opaque"

        def handler(request):
            if request.url.host == "api.dev.runwayml.com":
                return self.task("SUCCEEDED", output=[url])
            self.assertEqual(request.method, "HEAD")
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("x-runway-version", request.headers)
            return httpx.Response(200, headers={"content-type": "image/jpeg; charset=binary"})

        with self.http(handler) as requests:
            result = api.get_runway_task(JOB_ID)
        self.assertEqual(len(requests), 2)
        self.assertEqual(result["media_kind"], "image")
        self.assertEqual(result["image_url"], url)

    def test_unknown_task_status_or_missing_output_does_not_report_success(self) -> None:
        self.live()
        responses = [
            self.task("UNKNOWN"),
            self.task(["RUNNING"]),
            self.task("SUCCEEDED"),
            self.task("SUCCEEDED", output=[]),
            self.task("SUCCEEDED", output=[12]),
            self.task("SUCCEEDED", output=["https://127.0.0.1/output.mp4"]),
            httpx.Response(
                200, json={"id": "4a0fb983-5510-45e8-bf02-7aecb3c2edb2", "status": "RUNNING"}
            ),
        ]
        for response in responses:
            with self.subTest(response=response.content[:100]), self.http(lambda request: response):
                with self.assertRaises(RuntimeError):
                    api.get_runway_task(JOB_ID)

    def test_invalid_job_ids_and_download_flags_cannot_traverse_or_poll(self) -> None:
        self.live()
        for job_id in (
            "../escape",
            "/absolute",
            JOB_ID + "/../escape",
            "ci-smoke",
            "runway_dry_bad",
            None,
        ):
            with self.subTest(job_id=job_id), self.assertRaises(ValueError):
                api.get_runway_task(job_id)
        for download in ("true", 1, None):
            with self.subTest(download=download), self.assertRaises(ValueError):
                api.get_runway_task(JOB_ID, download=download)
        self.blocker.assert_not_called()
        self.assertFalse((self.media_dir / "runway").exists())

    def test_downloads_each_output_atomically_and_reuses_nonempty_files(self) -> None:
        self.live()
        second = "https://cdn.example.com/second.png"

        def handler(request):
            if request.url.host == "api.dev.runwayml.com":
                return self.task("SUCCEEDED", output=[OUTPUT_IMAGE, second])
            self.assertEqual(request.method, "GET")
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("x-runway-version", request.headers)
            return httpx.Response(
                200, content=b"generated-image", headers={"content-type": "image/png"}
            )

        with self.http(handler) as requests:
            result = api.get_runway_task(JOB_ID, download=True)
            again = api.get_runway_task(JOB_ID, download=True)
        self.assertEqual(len(requests), 4)
        self.assertTrue(result["downloaded"])
        paths = [Path(asset["output_path"]) for asset in result["assets"]]
        self.assertEqual(
            paths,
            [
                self.media_dir / "image" / f"{JOB_ID}.png",
                self.media_dir / "image" / f"{JOB_ID}_2.png",
            ],
        )
        self.assertTrue(all(path.read_bytes() == b"generated-image" for path in paths))
        self.assertEqual(result["output_path"], again["output_path"])
        self.assertFalse(list(self.media_dir.rglob("*.tmp")))

    def test_video_download_is_stored_in_the_video_directory(self) -> None:
        self.live()

        def handler(request):
            if request.url.host == "api.dev.runwayml.com":
                return self.task("SUCCEEDED", output=[OUTPUT_VIDEO])
            return httpx.Response(
                200, content=b"generated-video", headers={"content-type": "video/mp4"}
            )

        with self.http(handler):
            result = api.get_runway_task(JOB_ID, download=True)
        self.assertEqual(Path(result["output_path"]), self.media_dir / "video" / f"{JOB_ID}.mp4")
        self.assertEqual(Path(result["output_path"]).read_bytes(), b"generated-video")

    def test_failed_or_zero_byte_download_never_returns_an_output_path(self) -> None:
        self.live()
        for response in (
            httpx.Response(200, content=b"", headers={"content-type": "video/mp4"}),
            httpx.Response(403, content=b"signature=private"),
            httpx.Response(
                200, content=b"<html>error</html>", headers={"content-type": "text/html"}
            ),
        ):

            def handler(request):
                return (
                    self.task("SUCCEEDED", output=[OUTPUT_VIDEO])
                    if request.url.host == "api.dev.runwayml.com"
                    else response
                )

            with self.subTest(response=response.status_code), self.http(handler):
                with self.assertRaises(RuntimeError) as caught:
                    api.get_runway_task(JOB_ID, download=True)
                self.assertNotIn("signature", str(caught.exception))
            self.assertFalse((self.media_dir / "video" / f"{JOB_ID}.mp4").exists())
            self.assertFalse(list(self.media_dir.rglob("*.tmp")))

    def test_stream_failure_discards_partial_download(self) -> None:
        self.live()

        class BrokenStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"partial"
                raise httpx.ReadError("signature=private")

        def handler(request):
            if request.url.host == "api.dev.runwayml.com":
                return self.task("SUCCEEDED", output=[OUTPUT_VIDEO])
            return httpx.Response(200, stream=BrokenStream(), headers={"content-type": "video/mp4"})

        with self.http(handler):
            with self.assertRaisesRegex(RuntimeError, "download failed"):
                api.get_runway_task(JOB_ID, download=True)
        self.assertFalse((self.media_dir / "video" / f"{JOB_ID}.mp4").exists())
        self.assertFalse(list(self.media_dir.rglob("*.tmp")))

    def test_download_redirect_cannot_reach_an_ip_host(self) -> None:
        self.live()

        def handler(request):
            if request.url.host == "api.dev.runwayml.com":
                return self.task("SUCCEEDED", output=[OUTPUT_VIDEO])
            return httpx.Response(302, headers={"location": "https://127.0.0.1/private.mp4"})

        with self.http(handler) as requests:
            with self.assertRaisesRegex(RuntimeError, "download failed"):
                api.get_runway_task(JOB_ID, download=True)
        self.assertEqual(len(requests), 2)
        self.assertFalse((self.media_dir / "video" / f"{JOB_ID}.mp4").exists())


if __name__ == "__main__":
    unittest.main()
