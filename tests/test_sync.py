from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx


HTTPX_CLIENT = httpx.Client
FAL_ENDPOINT = "fal-ai/sync-lipsync/v3"
FAL_SUBMIT = f"https://queue.fal.run/{FAL_ENDPOINT}"
FAL_REQUESTS = "https://queue.fal.run/fal-ai/sync-lipsync/requests"
DIRECT_GENERATE = "https://api.sync.so/v2/generate"
VIDEO_URL = "https://media.example.test/source.mp4"
AUDIO_URL = "https://media.example.test/voice.wav"
OUTPUT_URL = "https://cdn.example.test/lipsync.mp4"
MP4_BYTES = (Path(__file__).parent / "fixtures" / "sync-video.mp4").read_bytes()
ARGUMENTS = {
    "video_url": VIDEO_URL,
    "audio_url": AUDIO_URL,
    "source_duration_seconds": 12.0,
    "audio_duration_seconds": 12.0,
    "source_fps": 25.0,
    "subjects": "Synthetic presenter and synthetic voice",
    "consent_confirmed": True,
}


def marked_mp4(label: bytes) -> bytes:
    return MP4_BYTES + (8 + len(label)).to_bytes(4, "big") + b"free" + label


class MemoryS3:
    def __init__(self, *, fail_puts=()):
        self.objects = {}
        self.put_count = 0
        self.fail_puts = set(fail_puts)
        self.uploaded = []
        self.sign_count = 0

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.put_count += 1
        if self.put_count in self.fail_puts:
            raise OSError("Synthetic store interruption")
        self.objects[Key] = Body.encode() if isinstance(Body, str) else Body

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def upload_file(self, *, Filename, Bucket, Key, ExtraArgs):
        self.objects[Key] = Path(Filename).read_bytes()
        self.uploaded.append(Key)

    def download_file(self, *, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[Key])

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.sign_count += 1
        return f"https://objects.example.test/{Params['Key']}?X-Amz-Signature=offline-{self.sign_count}"


class SyncProviderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("providers.sync"), "The Sync provider is not implemented."
        )
        self.assertIsNotNone(
            importlib.util.find_spec("providers.sync.api"), "The Sync provider API is not implemented."
        )
        self.api = importlib.import_module("providers.sync.api")
        self.contracts = importlib.import_module("providers.sync.contracts")
        self.chunks = importlib.import_module("providers.sync.chunks")
        self.directory = tempfile.TemporaryDirectory(prefix="sync-offline-")
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(
            os.environ,
            {
                "SYNC_DRY_RUN": "false",
                "SYNC_TRANSPORT": "fal",
                "SYNC_MODEL": "sync-3",
                "SYNC_API_KEY": "offline-sync-key",
                "SYNC_DIRECT_AUTHORIZED": "true",
                "SYNC_BILLING_PLAN": "legacy_base",
                "FAL_DRY_RUN": "false",
                "FAL_KEY": "offline-fal-key",
                "RENDERHAUS_MEDIA_DIR": self.directory.name,
            },
            clear=True,
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.requests: list[httpx.Request] = []
        self.routes = []
        self.transport = httpx.MockTransport(self.handle_request)
        client_patch = patch.object(self.api.httpx, "Client", self.mock_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        stream_patch = patch.object(self.api.httpx, "stream", self.mock_stream)
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
        self.assertTrue(self.routes, f"Unexpected HTTP request to {request.url.host}")
        method, url, response = self.routes.pop(0)
        self.assertEqual((request.method, str(request.url)), (method, url))
        return response

    def route(self, method, url, payload, status=200):
        self.routes.append((method, url, httpx.Response(status, json=payload)))

    def download_route(self, url=OUTPUT_URL, content=MP4_BYTES):
        self.routes.append(("GET", url, httpx.Response(200, content=content)))

    def submit(self, **overrides):
        return self.api.lipsync_video(**{**ARGUMENTS, **overrides})

    def fal_submit_route(self, request_id="request_1"):
        self.route("POST", FAL_SUBMIT, {"request_id": request_id, "status": "IN_QUEUE"})

    def fal_completed_routes(self, request_id="request_1", output_url=OUTPUT_URL):
        self.route("GET", f"{FAL_REQUESTS}/{request_id}/status", {"status": "COMPLETED"})
        self.route("GET", f"{FAL_REQUESTS}/{request_id}", {"video": {"url": output_url}})

    def direct_submit(self):
        os.environ["SYNC_TRANSPORT"] = "direct"
        self.route("POST", DIRECT_GENERATE, {"id": "direct_1", "status": "PENDING"})
        return self.submit()

    def sync_metadata(self):
        return list(Path(self.directory.name).glob("video/.tasks/sync/*.json"))

    def test_contract_is_strict_and_rejects_unknown_fields(self):
        request = self.contracts.request_for(ARGUMENTS)
        self.assertEqual(request.model, "sync-3")
        self.assertEqual(request.output_duration, 12.0)
        for field, value in (
            ("consent_confirmed", "true"),
            ("source_duration_seconds", "12"),
            ("audio_duration_seconds", True),
            ("source_fps", "25"),
            ("subjects", ["Synthetic"]),
            ("options", {"sync_mode": "loop"}),
            ("ignored_field", "anything"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.contracts.request_for({**ARGUMENTS, field: value})
        self.assertEqual(self.requests, [])

    def test_invalid_inputs_refuse_before_http_or_file_writes(self):
        cases = [
            {"consent_confirmed": value} for value in (False, "true", 1, None)
        ] + [{"subjects": value} for value in ("", "  ", [], ["Synthetic"], [3], None)]
        cases += [
            {field: value}
            for field in ("source_duration_seconds", "audio_duration_seconds", "source_fps")
            for value in (0, -1, float("nan"), float("inf"), True, "12", None)
        ]
        cases += [
            {field: value}
            for field in ("video_url", "audio_url")
            for value in (
                "http://media.example.test/file",
                "https:///missing-host",
                "https://user:password@media.example.test/file",
                "file:///tmp/secret",
                "data:video/mp4;base64,AA==",
                "/tmp/source.mp4",
                "renderhaus-asset://../escape",
                "renderhaus-asset://asset?signature=secret",
            )
        ]
        cases += [{"sync_mode": value} for value in ("unknown", "", None, {})]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises((ValueError, TypeError)):
                self.submit(**arguments)
        self.assertEqual(self.requests, [])
        self.assertEqual(list(Path(self.directory.name).rglob("*")), [])

    def test_output_duration_matches_documented_sync_modes(self):
        for mode, expected in (
            ("cut_off", 8.0), ("loop", 8.0), ("bounce", 8.0),
            ("silence", 10.0), ("remap", 8.0),
        ):
            with self.subTest(mode=mode):
                request = self.contracts.request_for({
                    **ARGUMENTS, "source_duration_seconds": 10.0,
                    "audio_duration_seconds": 8.0, "sync_mode": mode,
                })
                self.assertEqual(request.output_duration, expected)

    def test_optional_measured_dimensions_are_paired_positive_and_local_only(self):
        try:
            request = self.contracts.request_for({**ARGUMENTS, "source_width": 1920, "source_height": 1080})
        except ValueError:
            self.fail("Valid measured dimensions must be accepted.")
        self.assertEqual((request.source_width, request.source_height), (1920, 1080))
        for values in (
            {"source_width": 1920}, {"source_height": 1080},
            {"source_width": 0, "source_height": 1080},
            {"source_width": True, "source_height": 1080},
            {"source_width": "1920", "source_height": 1080},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.contracts.request_for({**ARGUMENTS, **values})
        self.fal_submit_route()
        self.submit(source_width=1920, source_height=1080)
        body = json.loads(self.requests[0].content)
        self.assertNotIn("source_width", body)
        self.assertNotIn("source_height", body)

    def test_dry_run_defaults_to_true_and_needs_no_keys_or_files(self):
        os.environ.pop("SYNC_DRY_RUN")
        os.environ.pop("FAL_KEY")
        os.environ.pop("SYNC_API_KEY")
        output = self.submit()
        self.assertTrue(self.api.dry_run())
        self.assertEqual(output["status"], "dry_run")
        self.assertEqual(output["request_preview"], {
            "video_url": VIDEO_URL, "audio_url": AUDIO_URL, "sync_mode": "cut_off",
        })
        self.assertIs(output["training_eligible"], False)
        self.assertNotIn("output_path", output)
        self.assertNotIn("video_url", output)
        polled = self.api.get_video_task(output["job_id"], download=True)
        self.assertEqual(polled["status"], "dry_run")
        self.assertEqual(self.requests, [])
        self.assertEqual(list(Path(self.directory.name).rglob("*")), [])

    def test_fal_dry_run_is_an_additional_submission_gate(self):
        os.environ["FAL_DRY_RUN"] = "true"
        self.assertEqual(self.submit()["status"], "dry_run")
        self.assertEqual(self.requests, [])

    def test_unverified_model_is_preview_only(self):
        with self.assertRaisesRegex(ValueError, "UNVERIFIED"):
            self.submit(model="future-sync-model")
        with patch.dict(os.environ, {"SYNC_DRY_RUN": "true"}):
            output = self.submit(model="future-sync-model")
        self.assertEqual(output["verification_status"], "UNVERIFIED")
        self.assertEqual(output["status"], "dry_run")
        self.assertEqual(self.requests, [])

    def test_direct_live_requires_written_authorization_and_known_plan(self):
        os.environ["SYNC_TRANSPORT"] = "direct"
        os.environ.pop("SYNC_DIRECT_AUTHORIZED")
        self.assertIn("permission", self.contracts.live_blocker({}))
        with self.assertRaisesRegex(ValueError, "permission"):
            self.submit()
        os.environ["SYNC_DIRECT_AUTHORIZED"] = "true"
        os.environ["SYNC_BILLING_PLAN"] = "credits"
        with self.assertRaisesRegex(ValueError, "billing"):
            self.submit()
        os.environ["SYNC_DRY_RUN"] = "true"
        self.assertEqual(self.submit()["status"], "dry_run")
        self.assertEqual(self.requests, [])

    def test_renderhaus_handles_are_accepted_for_preview_and_require_live_resolution(self):
        os.environ["SYNC_DRY_RUN"] = "true"
        output = self.submit(video_url="renderhaus-asset://version_123")
        self.assertEqual(output["status"], "dry_run")
        os.environ["SYNC_DRY_RUN"] = "false"
        with self.assertRaisesRegex(ValueError, "resolve"):
            self.submit(video_url="renderhaus-asset://version_123")
        self.assertEqual(self.requests, [])

    def test_fal_submission_sends_only_verified_fields_and_persists_consent(self):
        self.fal_submit_route()
        output = self.submit()
        self.assertEqual(output["status"], "queued")
        self.assertEqual(output["transport"], "fal")
        self.assertEqual(output["endpoint_id"], FAL_ENDPOINT)
        self.assertIs(output["training_eligible"], False)
        self.assertEqual(output["license"], "service-terms")
        self.assertEqual(json.loads(self.requests[0].content), {
            "video_url": VIDEO_URL, "audio_url": AUDIO_URL, "sync_mode": "cut_off",
        })
        saved = json.loads(self.sync_metadata()[0].read_text())
        self.assertTrue(saved["consent_confirmed"])
        self.assertEqual(saved["subjects"], ARGUMENTS["subjects"])
        self.assertEqual(saved["endpoint_handle"], f"{FAL_ENDPOINT}:request_1")

    def test_fal_poll_and_download_produces_atomic_artifact_with_provenance(self):
        self.fal_submit_route()
        job = self.submit(video_url=VIDEO_URL + "?X-Amz-Signature=input-secret")
        self.route("GET", f"{FAL_REQUESTS}/request_1/status", {"status": "IN_PROGRESS"})
        self.assertEqual(self.api.get_video_task(job["job_id"])["status"], "running")
        self.fal_completed_routes()
        self.download_route()
        output = self.api.get_video_task(job["job_id"], download=True)
        self.assertEqual(output["status"], "succeeded")
        self.assertEqual(Path(output["output_path"]).read_bytes(), MP4_BYTES)
        self.assertTrue(output["downloaded"])
        metadata = "\n".join(path.read_text() for path in self.sync_metadata())
        self.assertNotIn("input-secret", metadata)
        self.assertNotIn("X-Amz-Signature", metadata)
        self.assertIn('"training_eligible": false', metadata)
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])
        count = len(self.requests)
        self.assertEqual(self.api.get_video_task(job["job_id"], download=True)["status"], "succeeded")
        self.assertEqual(len(self.requests), count)

    def test_direct_submission_matches_official_body_and_header(self):
        output = self.direct_submit()
        request = self.requests[0]
        self.assertEqual(request.headers["x-api-key"], "offline-sync-key")
        self.assertEqual(json.loads(request.content), {
            "model": "sync-3", "input": [
                {"type": "video", "url": VIDEO_URL},
                {"type": "audio", "url": AUDIO_URL},
            ], "options": {"sync_mode": "cut_off"},
        })
        self.assertEqual(output["status"], "queued")
        self.assertEqual(output["transport"], "direct")

    def test_direct_poll_maps_all_official_states_and_never_resubmits(self):
        for state, expected in (
            ("PENDING", "queued"), ("PROCESSING", "running"),
            ("FAILED", "failed"), ("REJECTED", "failed"),
        ):
            with self.subTest(state=state):
                job = self.direct_submit()
                self.route("GET", DIRECT_GENERATE + "/direct_1", {
                    "id": "direct_1", "status": state,
                    "error": "contains https://private.test/token?signature=secret",
                })
                output = self.api.get_video_task(job["job_id"])
                self.assertEqual(output["status"], expected)
                self.assertNotIn("signature=secret", json.dumps(output))
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 4)
        self.assertEqual(sum(request.method == "GET" for request in self.requests), 4)

    def test_direct_completed_artifact_downloads(self):
        job = self.direct_submit()
        self.route("GET", DIRECT_GENERATE + "/direct_1", {
            "id": "direct_1", "status": "COMPLETED", "outputUrl": OUTPUT_URL,
        })
        self.download_route()
        output = self.api.get_video_task(job["job_id"], download=True)
        self.assertEqual(output["status"], "succeeded")
        self.assertEqual(Path(output["output_path"]).read_bytes(), MP4_BYTES)

    def test_provider_http_errors_never_echo_urls_keys_or_response_text(self):
        for transport, submit_url in (("fal", FAL_SUBMIT), ("direct", DIRECT_GENERATE)):
            with self.subTest(transport=transport):
                os.environ["SYNC_TRANSPORT"] = transport
                self.route("POST", submit_url, {
                    "error": f"{VIDEO_URL}?secret=credential offline-sync-key offline-fal-key",
                }, 422)
                with self.assertRaises(RuntimeError) as failure:
                    self.submit()
                message = str(failure.exception)
                self.assertIn("422", message)
                self.assertNotIn(VIDEO_URL, message)
                self.assertNotIn("credential", message)
                self.assertNotIn("offline-", message)

    def test_fal_failure_is_sanitized(self):
        self.fal_submit_route()
        job = self.submit()
        self.route("GET", f"{FAL_REQUESTS}/request_1/status", {
            "status": "COMPLETED", "error": VIDEO_URL + "?secret=provider-error",
            "error_type": "unsafe-secret",
        })
        output = self.api.get_video_task(job["job_id"])
        self.assertEqual(output["status"], "failed")
        self.assertNotIn("provider-error", json.dumps(output))
        self.assertNotIn("unsafe-secret", json.dumps(output))

    def test_invalid_completed_output_is_refused_before_download(self):
        for transport in ("fal", "direct"):
            for url in (None, 3, "file:///tmp/private", "http://cdn.test/file", "https:///file"):
                with self.subTest(transport=transport, url=url):
                    os.environ["SYNC_TRANSPORT"] = transport
                    if transport == "fal":
                        self.fal_submit_route()
                        job = self.submit()
                        self.fal_completed_routes(output_url=url)
                    else:
                        job = self.direct_submit()
                        self.route("GET", DIRECT_GENERATE + "/direct_1", {
                            "status": "COMPLETED", "outputUrl": url,
                        })
                    with self.assertRaises(RuntimeError):
                        self.api.get_video_task(job["job_id"], download=True)
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])

    def test_empty_download_never_leaves_an_artifact(self):
        self.fal_submit_route()
        job = self.submit()
        self.fal_completed_routes()
        self.download_route(content=b"")
        with self.assertRaisesRegex(RuntimeError, "empty"):
            self.api.get_video_task(job["job_id"], download=True)
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])

    def test_nonvideo_and_truncated_downloads_never_report_success_without_ffprobe(self):
        for content in (b"<html>not a video</html>", b"%PDF-1.7", MP4_BYTES[:16], MP4_BYTES[:-10]):
            with self.subTest(content_length=len(content)):
                self.fal_submit_route()
                job = self.submit()
                self.fal_completed_routes()
                self.download_route(content=content)
                with patch.object(self.chunks.shutil, "which", return_value=None):
                    with self.assertRaisesRegex(RuntimeError, "MP4|container|video"):
                        self.api.get_video_task(job["job_id"], download=True)
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])

    def test_original_mp4_fixture_can_download_without_ffprobe(self):
        self.fal_submit_route()
        job = self.submit()
        self.fal_completed_routes()
        self.download_route()
        with patch.object(self.chunks.shutil, "which", return_value=None):
            output = self.api.get_video_task(job["job_id"], download=True)
        self.assertEqual(Path(output["output_path"]).read_bytes(), MP4_BYTES)

    def test_signed_output_url_is_never_saved_in_sync_or_fal_metadata(self):
        signed = OUTPUT_URL + "?X-Amz-Signature=synthetic-private-marker"
        self.fal_submit_route()
        job = self.submit()
        self.fal_completed_routes(output_url=signed)
        self.download_route(signed)
        self.api.get_video_task(job["job_id"], download=True)
        saved = "\n".join(path.read_text() for path in Path(self.directory.name).glob("video/.tasks/**/*.json"))
        self.assertNotIn("synthetic-private-marker", saved)
        self.assertNotIn("X-Amz-Signature", saved)

    def test_local_manifest_failure_after_acceptance_returns_handle_even_if_fallback_fails(self):
        original = self.api._write_local
        calls = 0

        def fail_after_initial(manifest):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise OSError("Synthetic local failure https://private.test/?token=secret")
            original(manifest)

        self.fal_submit_route()
        with patch.object(self.api, "_write_local", side_effect=fail_after_initial):
            try:
                output = self.submit()
            except OSError:
                self.fail("Accepted Sync work must return its handle when local persistence fails.")
        self.assertEqual(output["accepted_provider_handle"], f"{FAL_ENDPOINT}:request_1")
        self.assertTrue(output["persistence_error"])
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("private.test", json.dumps(output))

    def test_accepted_handle_can_persist_remotely_when_local_cache_write_fails(self):
        os.environ["AWS_S3_BUCKET"] = "offline-sync-store"
        store = MemoryS3()
        original = self.api._write_local
        calls = 0

        def fail_after_initial(manifest):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise OSError("Synthetic local cache interruption")
            original(manifest)

        self.fal_submit_route()
        with (
            patch.object(self.chunks.boto3, "client", return_value=store),
            patch.object(self.api, "_write_local", side_effect=fail_after_initial),
        ):
            try:
                output = self.submit()
            except OSError:
                self.fail("Remote acceptance must survive a local cache error.")
        saved = json.loads(next(iter(store.objects.values())))
        self.assertEqual(saved["request_id"], "request_1")
        self.assertEqual(output["accepted_provider_handle"], f"{FAL_ENDPOINT}:request_1")

    def test_stale_remote_initial_manifest_does_not_hide_newer_local_accepted_handle(self):
        os.environ["AWS_S3_BUCKET"] = "offline-sync-store"
        store = MemoryS3(fail_puts={2})
        self.fal_submit_route()
        with patch.object(self.chunks.boto3, "client", return_value=store):
            output = self.submit()
            self.assertTrue(output["persistence_error"])
            self.assertIsNone(json.loads(next(iter(store.objects.values())))["request_id"])
            self.route("GET", f"{FAL_REQUESTS}/request_1/status", {"status": "IN_PROGRESS"})
            try:
                polled = self.api.get_video_task(output["job_id"])
            except ValueError:
                self.fail("Polling must retain the newer validated local accepted handle.")
        self.assertEqual(polled["status"], "running")
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_hosted_completed_artifact_has_fresh_url_after_cache_and_cold_worker(self):
        os.environ.update(AWS_S3_BUCKET="offline-sync-store", AWS_LAMBDA_FUNCTION_NAME="offline-sync-lambda")
        store = MemoryS3()
        self.fal_submit_route()
        with patch.object(self.chunks.boto3, "client", return_value=store):
            job = self.submit()
            self.fal_completed_routes()
            self.download_route()
            first = self.api.get_video_task(job["job_id"], download=True)
            self.assertTrue(first["video_url"].startswith("https://objects.example.test/"))
            second = self.api.get_video_task(job["job_id"], download=True)
            self.assertIn("video_url", second)
            self.assertNotEqual(first["video_url"], second["video_url"])
            shutil.rmtree(Path(self.directory.name) / "video")
            cold = self.api.get_video_task(job["job_id"], download=True)
        self.assertEqual(cold["status"], "succeeded")
        self.assertTrue(cold["video_url"].startswith("https://objects.example.test/"))
        self.assertNotIn("output_path", cold)
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)
        self.assertEqual(len(store.uploaded), 1)
        saved = "\n".join(body.decode() for key, body in store.objects.items() if key.endswith(".json"))
        self.assertNotIn("X-Amz-Signature", saved)

    def test_saved_jobs_respect_sync_and_transport_dry_run_flags(self):
        from providers.fal import api as fal_api

        self.fal_submit_route()
        job = self.submit()
        count = len(self.requests)
        os.environ["SYNC_DRY_RUN"] = "true"
        self.assertEqual(self.api.get_video_task(job["job_id"])["status"], "dry_run")
        raw = fal_api.get_video_task(f"{FAL_ENDPOINT}:request_1", download=True)
        self.assertEqual(raw["status"], "dry_run")
        os.environ["SYNC_DRY_RUN"] = "false"
        os.environ["FAL_DRY_RUN"] = "true"
        self.assertEqual(self.api.get_video_task(job["job_id"])["status"], "dry_run")
        self.assertEqual(len(self.requests), count)

    def test_saved_dry_run_poll_never_reads_the_remote_store(self):
        self.fal_submit_route()
        job = self.submit()
        os.environ["AWS_S3_BUCKET"] = "offline-sync-store"
        for flags in (
            {"SYNC_DRY_RUN": "true", "FAL_DRY_RUN": "false"},
            {"SYNC_DRY_RUN": "false", "FAL_DRY_RUN": "true"},
        ):
            with (
                self.subTest(flags=flags), patch.dict(os.environ, flags),
                patch.object(self.chunks.boto3, "client", side_effect=AssertionError("Remote store accessed during dry-run")),
            ):
                try:
                    output = self.api.get_video_task(job["job_id"], download=True)
                except RuntimeError:
                    self.fail("Dry-run polling must not access the remote store.")
                self.assertEqual(output["status"], "dry_run")
        self.assertEqual(len(self.requests), 1)

    def test_unknown_and_tampered_saved_handles_refuse_before_http(self):
        for handle in ("request_1", "sync:direct:../escape", "sync:fal:missing", "sync:chunks:missing"):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                self.api.get_video_task(handle)
        self.fal_submit_route()
        job = self.submit()
        path = self.sync_metadata()[0]
        saved = json.loads(path.read_text())
        saved["transport"] = "direct"
        path.write_text(json.dumps(saved))
        count = len(self.requests)
        with self.assertRaises(ValueError):
            self.api.get_video_task(job["job_id"])
        self.assertEqual(len(self.requests), count)

    def test_long_dry_run_returns_ordered_plan_without_dependencies_or_sources(self):
        os.environ["SYNC_DRY_RUN"] = "true"
        output = self.submit(
            source_duration_seconds=125.0, audio_duration_seconds=125.0,
            chunk_boundaries_seconds=[45.0, 90.0],
        )
        self.assertEqual(output["status"], "dry_run")
        self.assertEqual(
            [(part["start_seconds"], part["end_seconds"]) for part in output["chunk_plan"]],
            [(0.0, 45.0), (45.0, 90.0), (90.0, 125.0)],
        )
        self.assertEqual(output["chunk_limit_verification"], "UNVERIFIED")
        self.assertEqual(self.requests, [])
        self.assertEqual(list(Path(self.directory.name).rglob("*")), [])

    def test_long_boundaries_and_modes_refuse_unsafe_spans(self):
        for boundaries in (None, [], [80.0], [40.0, 40.0], [80.0, 40.0], [0.0, 60.0], [60.0, 125.0], [float("nan")], ["60"]):
            with self.subTest(boundaries=boundaries), self.assertRaises(ValueError):
                self.submit(
                    source_duration_seconds=125.0, audio_duration_seconds=125.0,
                    chunk_boundaries_seconds=boundaries,
                )
        for override in (
            {"sync_mode": "loop"}, {"sync_mode": "bounce"}, {"sync_mode": "remap"},
            {"sync_mode": "silence"}, {"audio_duration_seconds": 126.0},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.submit(**{
                    "source_duration_seconds": 125.0, "audio_duration_seconds": 125.0,
                    "chunk_boundaries_seconds": [45.0, 90.0], **override,
                })
        self.assertEqual(self.requests, [])

    def test_long_inputs_cannot_bypass_cap_by_cutting_off_to_short_audio(self):
        with self.assertRaisesRegex(ValueError, "equal-length|long input"):
            self.contracts.request_for({
                **ARGUMENTS, "source_duration_seconds": 500.0,
                "audio_duration_seconds": 10.0,
            })
        self.assertEqual(self.requests, [])

    def test_hosted_live_requires_a_durable_job_store(self):
        os.environ["AWS_LAMBDA_FUNCTION_NAME"] = "offline-sync-lambda"
        with self.assertRaisesRegex(ValueError, "AWS_S3_BUCKET"):
            self.submit()
        self.assertEqual(self.requests, [])

    def test_saved_manifest_survives_another_worker_without_local_metadata(self):
        os.environ["AWS_S3_BUCKET"] = "offline-sync-store"
        objects = {}

        class S3:
            def put_object(s3, *, Bucket, Key, Body, ContentType):
                objects[Key] = Body.encode() if isinstance(Body, str) else Body

            def get_object(s3, *, Bucket, Key):
                return {"Body": io.BytesIO(objects[Key])}

        with patch.object(self.chunks.boto3, "client", return_value=S3()):
            self.fal_submit_route()
            output = self.submit()
            self.assertTrue(objects)
            shutil.rmtree(Path(self.directory.name) / "video" / ".tasks" / "sync")
            self.route("GET", f"{FAL_REQUESTS}/request_1/status", {"status": "IN_PROGRESS"})
            self.assertEqual(self.api.get_video_task(output["job_id"])["status"], "running")
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_unavailable_durable_job_store_refuses_before_paid_submission(self):
        os.environ["AWS_S3_BUCKET"] = "offline-sync-store"

        class S3:
            def put_object(s3, **kwargs):
                raise RuntimeError("store failure https://private.test/?token=secret")

        with patch.object(self.chunks.boto3, "client", return_value=S3()):
            with self.assertRaisesRegex(RuntimeError, "store") as failure:
                self.submit()
        self.assertNotIn("private.test", str(failure.exception))
        self.assertNotIn("token=secret", str(failure.exception))
        self.assertEqual(self.requests, [])

    def test_invalid_operational_cap_refuses_before_submission(self):
        for value in ("0", "-1", "nan", "inf", "1801", "not-a-number"):
            with self.subTest(value=value), patch.dict(os.environ, {"SYNC_MAX_CHUNK_SECONDS": value}):
                with self.assertRaises(ValueError):
                    self.submit()
        self.assertEqual(self.requests, [])

    def test_long_prerequisites_refuse_before_paid_requests(self):
        arguments = {
            "source_duration_seconds": 125.0, "audio_duration_seconds": 125.0,
            "chunk_boundaries_seconds": [45.0, 90.0],
        }
        with patch.object(self.chunks.shutil, "which", return_value="/usr/bin/tool"):
            with self.assertRaisesRegex(ValueError, "AWS_S3_BUCKET"):
                self.submit(**arguments)
            os.environ["AWS_S3_BUCKET"] = "offline-chunks"
            with self.assertRaisesRegex(ValueError, "REMOTION_LOCAL_MEDIA_HOSTS"):
                self.submit(**arguments)
            os.environ["REMOTION_LOCAL_MEDIA_HOSTS"] = "attacker.example.test"
            with self.assertRaisesRegex(ValueError, "REMOTION_LOCAL_MEDIA_HOSTS"):
                self.submit(**arguments)
            os.environ["REMOTION_LOCAL_MEDIA_HOSTS"] = "media.example.test"
        with patch.object(self.chunks.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "ffmpeg"):
                self.submit(**arguments)
        self.assertEqual(self.requests, [])

    def test_missing_concat_dependency_refuses_before_sources_or_paid_submission(self):
        import builtins
        from providers.remotion import local

        original_import = builtins.__import__
        os.environ.update(AWS_S3_BUCKET="offline-chunks", REMOTION_LOCAL_MEDIA_HOSTS="media.example.test")

        def missing_concat(name, *args, **kwargs):
            if name == "server.projects":
                raise ImportError("Not packaged in this Lambda")
            return original_import(name, *args, **kwargs)

        with (
            patch.object(self.chunks.shutil, "which", return_value="/usr/bin/tool"),
            patch.object(builtins, "__import__", side_effect=missing_concat),
            patch.object(local, "_source", side_effect=AssertionError("Source fetched before dependency check")),
        ):
            with self.assertRaisesRegex(ValueError, "concat|merge"):
                self.submit_aggregate_without_patch()
        self.assertEqual(self.requests, [])

    def prepared_parts(self, *args, **kwargs):
        return [
            self.chunks.PreparedChunk(
                index=index, start_seconds=start, end_seconds=end,
                video_url=f"https://chunks.example.test/{index}.mp4?X-Amz-Signature=transient",
                audio_url=f"https://chunks.example.test/{index}.wav?X-Amz-Signature=transient",
            )
            for index, (start, end) in enumerate(((0.0, 45.0), (45.0, 90.0), (90.0, 125.0)))
        ]

    def submit_aggregate(self):
        with patch.object(self.chunks, "prepare", self.prepared_parts):
            return self.submit(
                source_duration_seconds=125.0, audio_duration_seconds=125.0,
                chunk_boundaries_seconds=[45.0, 90.0],
            )

    def test_chunk_submission_retains_order_and_keeps_signed_urls_transient(self):
        for index in range(3):
            self.fal_submit_route(f"part_{index}")
        output = self.submit_aggregate()
        self.assertEqual(output["status"], "queued")
        self.assertEqual(len(output["accepted_job_ids"]), 3)
        self.assertEqual(
            [json.loads(request.content)["video_url"] for request in self.requests],
            [f"https://chunks.example.test/{i}.mp4?X-Amz-Signature=transient" for i in range(3)],
        )
        saved = "\n".join(path.read_text() for path in self.sync_metadata())
        self.assertNotIn("X-Amz-Signature", saved)
        self.assertNotIn("transient", saved)

    def test_preprocessing_failure_submits_no_chunks(self):
        with patch.object(self.chunks, "prepare", side_effect=ValueError("preprocessing failed")):
            with self.assertRaisesRegex(ValueError, "preprocessing"):
                self.submit_aggregate_without_patch()
        self.assertEqual(self.requests, [])

    def submit_aggregate_without_patch(self):
        return self.submit(
            source_duration_seconds=125.0, audio_duration_seconds=125.0,
            chunk_boundaries_seconds=[45.0, 90.0],
        )

    def test_partial_submission_returns_accepted_handles_and_never_retries(self):
        self.fal_submit_route("part_0")
        self.route("POST", FAL_SUBMIT, {"error": "do not echo me"}, 503)
        output = self.submit_aggregate()
        self.assertEqual(output["status"], "failed")
        self.assertEqual(len(output["accepted_job_ids"]), 1)
        self.assertIn("partial", output["error"].lower())
        self.route("GET", f"{FAL_REQUESTS}/part_0/status", {"status": "IN_PROGRESS"})
        polled = self.api.get_video_task(output["job_id"], download=True)
        self.assertEqual(polled["status"], "failed")
        self.assertEqual(polled["accepted_job_ids"], output["accepted_job_ids"])
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 2)
        self.assertEqual(sum(request.method == "GET" for request in self.requests), 1)
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])

    def test_aggregate_polls_once_per_child_then_concats_in_order_and_reuses_artifact(self):
        for index in range(3):
            self.fal_submit_route(f"part_{index}")
        job = self.submit_aggregate()
        for index in range(3):
            url = f"https://cdn.example.test/part-{index}.mp4"
            self.fal_completed_routes(f"part_{index}", output_url=url)
            self.download_route(url, content=marked_mp4(f"part-{index}".encode()))
        merged_inputs = []

        def merge(paths, *, output_path):
            merged_inputs.extend(path.read_bytes() for path in paths)
            output_path.write_bytes(marked_mp4(b"assembled"))
            return output_path

        with patch("server.projects.merge_video_paths", side_effect=merge) as concat:
            output = self.api.get_video_task(job["job_id"], download=True)
            self.assertEqual(output["status"], "succeeded")
            self.assertEqual(merged_inputs, [marked_mp4(f"part-{i}".encode()) for i in range(3)])
            self.assertEqual(Path(output["output_path"]).read_bytes(), marked_mp4(b"assembled"))
            request_count = len(self.requests)
            self.assertEqual(self.api.get_video_task(job["job_id"], download=True)["status"], "succeeded")
            self.assertEqual(concat.call_count, 1)
            self.assertEqual(len(self.requests), request_count)
        self.assertEqual(sum(request.url.path.endswith("/status") for request in self.requests), 3)

    def test_empty_concat_does_not_report_success(self):
        for index in range(3):
            self.fal_submit_route(f"part_{index}")
        job = self.submit_aggregate()
        for index in range(3):
            url = f"https://cdn.example.test/part-{index}.mp4"
            self.fal_completed_routes(f"part_{index}", output_url=url)
            self.download_route(url, content=MP4_BYTES)

        def empty_merge(paths, *, output_path):
            output_path.write_bytes(b"")
            return output_path

        with patch("server.projects.merge_video_paths", side_effect=empty_merge):
            with self.assertRaisesRegex(RuntimeError, "empty"):
                self.api.get_video_task(job["job_id"], download=True)
        self.assertNotEqual(
            json.loads(next(path for path in self.sync_metadata() if json.loads(path.read_text())["job_id"] == job["job_id"]).read_text())["status"],
            "succeeded",
        )

    def test_aggregate_publishes_final_mp4_and_returns_fresh_url_after_cold_worker(self):
        os.environ.update(AWS_S3_BUCKET="offline-sync-store", AWS_LAMBDA_FUNCTION_NAME="offline-sync-lambda")
        store = MemoryS3()
        for index in range(3):
            self.fal_submit_route(f"part_{index}")

        def merge(paths, *, output_path):
            self.assertEqual(len(paths), 3)
            output_path.write_bytes(marked_mp4(b"assembled"))
            return output_path

        with (
            patch.object(self.chunks.boto3, "client", return_value=store),
            patch("server.projects.merge_video_paths", side_effect=merge) as concat,
        ):
            job = self.submit_aggregate()
            for index in range(3):
                url = f"https://cdn.example.test/part-{index}.mp4"
                self.fal_completed_routes(f"part_{index}", output_url=url)
                self.download_route(url)
            first = self.api.get_video_task(job["job_id"], download=True)
            self.assertIn("video_url", first)
            second = self.api.get_video_task(job["job_id"], download=True)
            self.assertNotEqual(first["video_url"], second["video_url"])
            shutil.rmtree(Path(self.directory.name) / "video")
            cold = self.api.get_video_task(job["job_id"], download=True)
            self.assertEqual(concat.call_count, 1)
        self.assertEqual(cold["status"], "succeeded")
        self.assertTrue(cold["video_url"].startswith("https://objects.example.test/"))
        self.assertEqual(len(store.uploaded), 4)
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 3)
        saved = "\n".join(body.decode() for key, body in store.objects.items() if key.endswith(".json"))
        self.assertNotIn("X-Amz-Signature", saved)

    def test_aggregate_can_restore_completed_children_after_worker_restart(self):
        os.environ.update(AWS_S3_BUCKET="offline-sync-store", AWS_LAMBDA_FUNCTION_NAME="offline-sync-lambda")
        store = MemoryS3()
        for index in range(3):
            self.fal_submit_route(f"part_{index}")

        def merge(paths, *, output_path):
            self.assertEqual([path.read_bytes() for path in paths], [marked_mp4(f"part-{i}".encode()) for i in range(3)])
            output_path.write_bytes(marked_mp4(b"assembled"))
            return output_path

        with (
            patch.object(self.chunks.boto3, "client", return_value=store),
            patch("server.projects.merge_video_paths", side_effect=merge),
        ):
            job = self.submit_aggregate()
            for index in range(2):
                url = f"https://cdn.example.test/part-{index}.mp4"
                self.fal_completed_routes(f"part_{index}", output_url=url)
                self.download_route(url, marked_mp4(f"part-{index}".encode()))
            self.route("GET", f"{FAL_REQUESTS}/part_2/status", {"status": "IN_PROGRESS"})
            self.assertEqual(self.api.get_video_task(job["job_id"], download=True)["status"], "running")
            shutil.rmtree(Path(self.directory.name) / "video")
            final_url = "https://cdn.example.test/part-2.mp4"
            self.fal_completed_routes("part_2", output_url=final_url)
            self.download_route(final_url, marked_mp4(b"part-2"))
            output = self.api.get_video_task(job["job_id"], download=True)
        self.assertEqual(output["status"], "succeeded")
        self.assertIn("video_url", output)
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 3)
        self.assertEqual(sum(request.url.path.endswith("/status") for request in self.requests), 4)

    def test_source_probe_mismatch_refuses_before_split_upload_or_paid_requests(self):
        from providers.remotion import local

        os.environ.update(AWS_S3_BUCKET="offline-chunks", REMOTION_LOCAL_MEDIA_HOSTS="media.example.test")
        source = Path(self.directory.name) / "source.mp4"
        source.write_bytes(b"source")
        for duration, fps in ((120.0, "25/1"), (125.0, "30/1")):
            probe = {"format": {"duration": str(duration)}, "streams": [
                {"codec_type": "video", "avg_frame_rate": fps, "duration": str(duration)},
                {"codec_type": "audio", "duration": str(duration)},
            ]}
            with (
                self.subTest(duration=duration, fps=fps),
                patch.object(self.chunks.shutil, "which", return_value="/usr/bin/tool"),
                patch.object(local, "_source", return_value=source),
                patch.object(local, "_probe", return_value=probe),
                patch.object(self.chunks.subprocess, "run") as split,
                patch.object(self.chunks.boto3, "client") as upload,
            ):
                with self.assertRaisesRegex(ValueError, "measured"):
                    self.submit_aggregate_without_patch()
                split.assert_not_called()
                upload.assert_not_called()
        self.assertEqual(self.requests, [])

    def test_preprocessing_splits_paired_media_and_uploads_all_before_submission(self):
        from providers.remotion import local

        os.environ.update(AWS_S3_BUCKET="offline-chunks", REMOTION_LOCAL_MEDIA_HOSTS="media.example.test")
        source_video = Path(self.directory.name) / "source.mp4"
        source_audio = Path(self.directory.name) / "source.wav"
        source_video.write_bytes(b"video")
        source_audio.write_bytes(b"audio")
        commands, uploaded = [], []

        def source(value, **kwargs):
            return source_video if value == VIDEO_URL else source_audio

        def probe(path):
            duration = 125.0
            if path.name.startswith("chunk-"):
                duration = (45.0, 45.0, 35.0)[int(path.stem.split("-")[1])]
            stream = {"codec_type": "video" if path.suffix == ".mp4" else "audio", "duration": str(duration)}
            if stream["codec_type"] == "video":
                stream["avg_frame_rate"] = "25/1"
            return {"format": {"duration": str(duration)}, "streams": [stream]}

        def split(command, **kwargs):
            self.assertEqual(self.requests, [])
            commands.append(command)
            Path(command[-1]).write_bytes(b"clipped")
            return SimpleNamespace(returncode=0)

        class S3:
            def put_object(s3, **kwargs):
                pass

            def upload_file(s3, *, Filename, Bucket, Key, ExtraArgs):
                self.assertEqual(self.requests, [])
                self.assertEqual(Bucket, "offline-chunks")
                self.assertTrue(Path(Filename).is_file())
                uploaded.append((Key, ExtraArgs["ContentType"]))

            def generate_presigned_url(s3, operation, *, Params, ExpiresIn):
                self.assertEqual(len(commands), 6)
                return "https://chunks.example.test/" + Params["Key"] + "?X-Amz-Signature=temporary"

        for index in range(3):
            self.fal_submit_route(f"part_{index}")
        with (
            patch.object(self.chunks.shutil, "which", return_value="/usr/bin/tool"),
            patch.object(local, "_source", side_effect=source),
            patch.object(local, "_probe", side_effect=probe),
            patch.object(self.chunks.subprocess, "run", side_effect=split),
            patch.object(self.chunks.boto3, "client", return_value=S3()),
        ):
            output = self.submit_aggregate_without_patch()
        self.assertEqual(output["status"], "queued")
        self.assertEqual(len(commands), 6)
        self.assertEqual([command[command.index("-t") + 1] for command in commands], ["45", "45", "45", "45", "35", "35"])
        self.assertEqual([mime for _, mime in uploaded], ["video/mp4", "audio/wav"] * 3)
        self.assertEqual(len(self.requests), 3)


if __name__ == "__main__":
    unittest.main()
