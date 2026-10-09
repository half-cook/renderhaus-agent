from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


HTTPX_CLIENT = httpx.Client
BASE = "https://api.heygen.com/v3"
OUTPUT_URL = "https://files.heygen.ai/video/presenter.mp4?signature=offline-signed-url"
SCRIPT = "An authorized presenter reads this private script."
MP4_BYTES = (Path(__file__).parent / "fixtures" / "sync-video.mp4").read_bytes()
ARGUMENTS = {
    "avatar_id": "look_authorized",
    "duration_seconds": 45.0,
    "subjects": "Presenter Alice and voice actor Alice",
    "consent_confirmed": True,
    "consent_record_id": "consent_record_123",
    "script": SCRIPT,
    "voice_id": "voice_authorized",
}


class MemoryS3:
    def __init__(self, *, fail_puts=()):
        self.objects = {}
        self.put_count = 0
        self.fail_puts = set(fail_puts)

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.put_count += 1
        if self.put_count in self.fail_puts:
            raise OSError("Offline storage interruption")
        self.objects[Key] = Body

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def upload_file(self, *, Filename, Bucket, Key, ExtraArgs):
        self.objects[Key] = Path(Filename).read_bytes()

    def download_file(self, *, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[Key])


class HeyGenProviderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("providers.heygen"), "HeyGen provider is missing.")
        self.api = importlib.import_module("providers.heygen.api")
        self.contracts = importlib.import_module("providers.heygen.contracts")
        self.directory = tempfile.TemporaryDirectory(prefix="heygen-offline-")
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {
            "HEYGEN_DRY_RUN": "false",
            "HEYGEN_MODEL": "avatar_v",
            "HEYGEN_API_PLAN": "paid_self_serve",
            "HEYGEN_API_KEY": "offline-heygen-key",
            "RENDERHAUS_MEDIA_DIR": self.directory.name,
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.requests = []
        self.routes = []
        self.transport = httpx.MockTransport(self.handle_request)
        client_patch = patch.object(self.api.httpx, "Client", self.mock_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        dns_patch = patch.object(self.api.socket, "getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ])
        dns_patch.start()
        self.addCleanup(dns_patch.stop)

    def mock_client(self, *args, **kwargs):
        return HTTPX_CLIENT(*args, transport=self.transport, **kwargs)

    def handle_request(self, request):
        self.requests.append(request)
        self.assertTrue(self.routes, "Unexpected HTTP request.")
        method, url, response = self.routes.pop(0)
        self.assertEqual((request.method, str(request.url)), (method, url))
        if isinstance(response, Exception):
            raise response
        return response

    def route(self, method, url, payload, *, status=200):
        self.routes.append((method, url, httpx.Response(status, json=payload)))

    def preflight(self, *, look=None, group=None):
        self.route("GET", f"{BASE}/avatars/looks/look_authorized", {"data": {
            "id": "look_authorized", "group_id": "group_authorized",
            "avatar_type": "digital_twin", "supported_api_engines": ["avatar_v"],
            "status": "completed", **(look or {}),
        }})
        if group is not False:
            self.route("GET", f"{BASE}/avatars/group_authorized", {"data": {
                "id": "group_authorized", "consent_status": "accepted", "status": "completed",
                **(group or {}),
            }})

    def submitted(self):
        self.preflight()
        self.route("POST", f"{BASE}/videos", {"data": {"video_id": "video_123", "status": "waiting"}})
        return self.api.create_avatar_video(**ARGUMENTS)

    def poll_route(self, *, status="completed", **overrides):
        self.route("GET", f"{BASE}/videos/video_123", {"data": {
            "id": "video_123", "status": status, "video_url": OUTPUT_URL,
            "duration": 45.0, **overrides,
        }})

    def metadata(self):
        paths = list(Path(self.directory.name).rglob("*.json"))
        self.assertEqual(len(paths), 1)
        return json.loads(paths[0].read_text())

    def test_default_dry_run_requires_no_key_or_http(self):
        os.environ.pop("HEYGEN_DRY_RUN")
        os.environ.pop("HEYGEN_API_KEY")
        result = self.api.create_avatar_video(**ARGUMENTS)
        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(result["job_id"].startswith("heygen:dry:"))
        self.assertEqual(result["request_preview"]["engine"], {"type": "avatar_v"})
        self.assertFalse(result["training_eligible"])
        self.assertIsNone(result["estimated_cost_usd"])
        self.assertEqual(self.requests, [])

    def test_dry_handle_never_polls_live_after_configuration_changes(self):
        os.environ["HEYGEN_DRY_RUN"] = "true"
        created = self.api.create_avatar_video(**ARGUMENTS)
        os.environ["HEYGEN_DRY_RUN"] = "false"
        result = self.api.get_video_status(created["job_id"], download=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["downloaded"])
        self.assertNotIn("video_url", result)
        self.assertEqual(self.requests, [])

    def test_unverified_engine_forces_preview_even_when_live_configured(self):
        for model in ("avatar_iv", "avatar5", "unknown_engine"):
            with self.subTest(model=model):
                result = self.api.create_avatar_video(**{**ARGUMENTS, "model": model})
                self.assertEqual(result["status"], "dry_run")
                self.assertEqual(result["model"], model)
                self.assertIn("UNVERIFIED", result["note"])
        os.environ["HEYGEN_MODEL"] = "avatar5"
        self.assertTrue(self.api.dry_run())
        self.assertEqual(self.requests, [])

    def test_consent_subjects_and_record_are_required_before_any_http(self):
        for fields in (
            {"consent_confirmed": False}, {"consent_confirmed": "true"},
            {"subjects": " "}, {"consent_record_id": ""},
            {"consent_record_id": "https://credentials.example.test/consent?token=private"},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.api.create_avatar_video(**{**ARGUMENTS, **fields})
        self.assertEqual(self.requests, [])

    def test_invalid_source_and_limits_reject_before_any_http(self):
        invalid = (
            {"script": None}, {"audio_url": "https://media.example.test/audio.wav"},
            {"voice_id": None}, {"script": " "}, {"script": "x" * 5001},
            {"duration_seconds": float("nan")}, {"duration_seconds": True},
            {"duration_seconds": 1801}, {"resolution": "4k"},
            {"aspect_ratio": "2:1"}, {"avatar_id": "../another/avatar"},
        )
        for fields in invalid:
            with self.subTest(fields=list(fields)), self.assertRaises(ValueError):
                self.api.create_avatar_video(**{**ARGUMENTS, **fields})
        with self.assertRaises(ValueError):
            self.api.create_avatar_video(**{**ARGUMENTS, "script": None, "voice_id": None,
                                          "audio_url": "https://example.test/audio.wav", "duration_seconds": 601})
        self.assertEqual(self.requests, [])

    def test_script_payload_preserves_v3_names_and_omits_local_consent_fields(self):
        result = self.submitted()
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["provider_video_id"], "video_123")
        request = self.requests[-1]
        self.assertEqual(json.loads(request.content), {
            "type": "avatar", "avatar_id": "look_authorized", "script": SCRIPT,
            "voice_id": "voice_authorized", "engine": {"type": "avatar_v"},
            "resolution": "720p", "aspect_ratio": "16:9", "output_format": "mp4",
        })
        self.assertEqual(request.headers["x-api-key"], "offline-heygen-key")
        self.assertEqual(request.headers["Idempotency-Key"], result["job_id"])
        self.assertFalse(result["training_eligible"])

    def test_audio_payload_and_script_locale_motion_controls(self):
        os.environ["HEYGEN_DRY_RUN"] = "true"
        audio = self.api.create_avatar_video(**{**ARGUMENTS, "script": None, "voice_id": None,
            "audio_url": "https://media.example.test/speech.wav?token=private-signature"})
        self.assertEqual(audio["request_preview"]["audio_url"], "https://media.example.test/speech.wav?token=private-signature")
        self.assertNotIn("script", audio["request_preview"])
        self.assertNotIn("duration_seconds", audio["request_preview"])
        scripted = self.api.create_avatar_video(**{**ARGUMENTS, "language": "fr-CA",
            "motion_prompt": "Use restrained hand gestures", "aspect_ratio": "4:5", "resolution": "1080p"})
        self.assertEqual(scripted["request_preview"]["voice_settings"], {"locale": "fr-CA"})
        self.assertEqual(scripted["request_preview"]["motion_prompt"], "Use restrained hand gestures")

    def test_unknown_or_free_plan_cannot_start_live_generation(self):
        for plan in ("unknown", "free", "unverified_plan"):
            with self.subTest(plan=plan):
                os.environ["HEYGEN_API_PLAN"] = plan
                with self.assertRaisesRegex(ValueError, "paid.*plan|plan.*paid"):
                    self.api.create_avatar_video(**ARGUMENTS)
        self.assertEqual(self.requests, [])

    def test_live_audio_asset_handle_requires_authorized_host_resolution(self):
        with self.assertRaisesRegex(ValueError, "resolv"):
            self.api.create_avatar_video(**{**ARGUMENTS, "script": None, "voice_id": None,
                                           "audio_url": "renderhaus-asset://authorized_audio"})
        self.assertEqual(self.requests, [])

    def test_ineligible_look_cannot_start_generation(self):
        for look in ({"avatar_type": "photo_avatar"}, {"supported_api_engines": ["avatar_iv"]},
                     {"status": "pending"}, {"id": "different_look"}, {"group_id": "../group"}):
            with self.subTest(look=look):
                self.preflight(look=look, group=False)
                with self.assertRaises(ValueError):
                    self.api.create_avatar_video(**ARGUMENTS)
        self.assertFalse(any(request.method == "POST" for request in self.requests))
        self.assertEqual(self.routes, [])

    def test_provider_consent_must_be_accepted_on_matching_completed_group(self):
        for group in ({"consent_status": value} for value in (None, "pending", "rejected", "approved", "verified")):
            with self.subTest(group=group):
                self.preflight(group=group)
                with self.assertRaises(ValueError):
                    self.api.create_avatar_video(**ARGUMENTS)
        for group in ({"id": "other_group"}, {"status": "pending"}):
            self.preflight(group=group)
            with self.assertRaises(ValueError):
                self.api.create_avatar_video(**ARGUMENTS)
        self.assertFalse(any(request.method == "POST" for request in self.requests))

    def test_saved_metadata_retains_consent_but_no_script_key_or_signed_urls(self):
        created = self.submitted()
        self.poll_route()
        self.api.get_video_status(created["job_id"])
        metadata = self.metadata()
        encoded = json.dumps(metadata)
        self.assertEqual(metadata["subjects"], "Presenter Alice and voice actor Alice")
        self.assertEqual(metadata["consent_record_id"], "consent_record_123")
        self.assertEqual(metadata["provider_video_id"], "video_123")
        self.assertEqual(metadata["model"], "avatar_v")
        self.assertTrue(metadata["consent_confirmed"])
        self.assertFalse(metadata["training_eligible"])
        for private in (SCRIPT, "offline-heygen-key", "offline-signed-url", "signature="):
            self.assertNotIn(private, encoded)

    def test_poll_maps_documented_statuses_without_resubmitting(self):
        created = self.submitted()
        for provider_status, expected in (("pending", "queued"), ("waiting", "queued"),
                                          ("processing", "running"), ("failed", "failed")):
            self.poll_route(status=provider_status, failure_message="secret_key must never be echoed")
            result = self.api.get_video_status(created["job_id"])
            self.assertEqual(result["status"], expected)
            self.assertNotIn("secret_key", json.dumps(result))
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_poll_rejects_unknown_status_and_mismatched_identity(self):
        created = self.submitted()
        for fields in ({"id": "other_video"}, {"status": "ready"}, {"video_url": None}):
            self.poll_route(**fields)
            with self.assertRaises(RuntimeError):
                self.api.get_video_status(created["job_id"], download=True)
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)
        self.assertFalse(list(Path(self.directory.name).rglob("*.mp4")))

    def test_completed_download_is_validated_atomic_and_reused(self):
        created = self.submitted()
        self.poll_route()
        self.routes.append(("GET", OUTPUT_URL, httpx.Response(200, content=MP4_BYTES)))
        result = self.api.get_video_status(created["job_id"], download=True)
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["downloaded"])
        self.assertEqual(Path(result["output_path"]).read_bytes(), MP4_BYTES)
        self.assertFalse(result["training_eligible"])
        before = len(self.requests)
        repeated = self.api.get_video_status(created["job_id"], download=True)
        self.assertEqual(repeated["output_path"], result["output_path"])
        self.assertEqual(len(self.requests), before)
        download_headers = self.requests[-1].headers
        self.assertNotIn("x-api-key", download_headers)

    def test_invalid_video_content_never_becomes_a_saved_artifact(self):
        created = self.submitted()
        self.poll_route()
        self.routes.append(("GET", OUTPUT_URL, httpx.Response(200, content=b"<html>error</html>")))
        with self.assertRaisesRegex(RuntimeError, "MP4"):
            self.api.get_video_status(created["job_id"], download=True)
        self.assertFalse(list(Path(self.directory.name).rglob("*.mp4")))
        self.assertFalse(list(Path(self.directory.name).rglob("*.part")))

    def test_download_rejects_private_addresses_and_redirects(self):
        created = self.submitted()
        self.poll_route(video_url="https://127.0.0.1/private.mp4")
        with self.assertRaises((ValueError, RuntimeError)):
            self.api.get_video_status(created["job_id"], download=True)
        self.poll_route()
        self.routes.append(("GET", OUTPUT_URL, httpx.Response(302, headers={"location": "http://localhost/secret"})))
        with self.assertRaises(RuntimeError):
            self.api.get_video_status(created["job_id"], download=True)
        self.assertFalse(list(Path(self.directory.name).rglob("*.mp4")))

    def test_live_lambda_requires_durable_storage_before_any_http(self):
        os.environ["AWS_LAMBDA_FUNCTION_NAME"] = "offline-lambda"
        with self.assertRaisesRegex(ValueError, "durable|AWS_S3_BUCKET"):
            self.api.create_avatar_video(**ARGUMENTS)
        self.assertEqual(self.requests, [])

    def test_store_failure_before_submission_cannot_start_paid_work(self):
        os.environ["AWS_S3_BUCKET"] = "offline-bucket"
        storage = MemoryS3(fail_puts={1})
        with patch.object(self.api.boto3, "client", return_value=storage):
            self.preflight()
            with self.assertRaises(RuntimeError):
                self.api.create_avatar_video(**ARGUMENTS)
        self.assertFalse(any(request.method == "POST" for request in self.requests))

    def test_post_acceptance_storage_failure_preserves_ids_and_no_resubmit(self):
        os.environ["AWS_S3_BUCKET"] = "offline-bucket"
        storage = MemoryS3(fail_puts={2})
        with patch.object(self.api.boto3, "client", return_value=storage):
            result = self.submitted()
            self.assertEqual(result["provider_video_id"], "video_123")
            self.assertEqual(result["status"], "queued")
            self.assertTrue(result["persistence_error"])
            self.assertNotIn("error", result)
            self.assertEqual(self.metadata()["provider_video_id"], "video_123")
            self.poll_route(status="processing")
            polled = self.api.get_video_status(result["job_id"])
            self.assertEqual(polled["status"], "running")
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_s3_manifest_and_artifact_resume_on_a_cold_worker(self):
        os.environ["AWS_S3_BUCKET"] = "offline-bucket"
        storage = MemoryS3()
        with patch.object(self.api.boto3, "client", return_value=storage):
            result = self.submitted()
            self.poll_route()
            self.routes.append(("GET", OUTPUT_URL, httpx.Response(200, content=MP4_BYTES)))
            completed = self.api.get_video_status(result["job_id"], download=True)
            with tempfile.TemporaryDirectory(prefix="heygen-cold-") as cold:
                os.environ["RENDERHAUS_MEDIA_DIR"] = cold
                restored = self.api.get_video_status(result["job_id"], download=True)
                self.assertTrue(restored["downloaded"])
                self.assertEqual(Path(restored["output_path"]).read_bytes(), MP4_BYTES)
                self.assertNotEqual(completed["output_path"], restored["output_path"])
                self.assertEqual(restored["consent_record_id"], "consent_record_123")
                self.assertFalse(restored["training_eligible"])
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)
        self.assertFalse(self.routes)

    def test_ambiguous_post_never_retries_and_preserves_reconciliation_handle(self):
        self.preflight()
        self.routes.append(("POST", f"{BASE}/videos", httpx.ReadTimeout("private response secret")))
        result = self.api.create_avatar_video(**ARGUMENTS)
        self.assertEqual(result["status"], "submission_unknown")
        self.assertTrue(result["submission_unknown"])
        self.assertIn("Do not resubmit", result["note"])
        self.assertNotIn("private response secret", json.dumps(result))
        polled = self.api.get_video_status(result["job_id"])
        self.assertEqual(polled["status"], "submission_unknown")
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_http_error_never_echoes_vendor_body_or_api_key(self):
        self.route("GET", f"{BASE}/avatars/looks/look_authorized", {"error": {
            "message": "offline-heygen-key private_script " + SCRIPT,
        }}, status=401)
        with self.assertRaises(RuntimeError) as failure:
            self.api.create_avatar_video(**ARGUMENTS)
        self.assertIn("401", str(failure.exception))
        self.assertNotIn("offline-heygen-key", str(failure.exception))
        self.assertNotIn(SCRIPT, str(failure.exception))

    def test_list_tools_page_once_with_official_query_and_response_shapes(self):
        self.route("GET", f"{BASE}/avatars/looks?avatar_type=digital_twin&limit=20&token=next-cursor", {
            "data": [{"id": "look_authorized", "group_id": "group_authorized", "name": "Alice",
                      "avatar_type": "digital_twin", "supported_api_engines": ["avatar_v"], "status": "completed"}],
            "has_more": True, "next_token": "cursor_2",
        })
        avatars = self.api.list_avatars(next_token="next-cursor")
        self.assertEqual(avatars["data"][0]["id"], "look_authorized")
        self.assertEqual(avatars["next_token"], "cursor_2")
        self.route("GET", f"{BASE}/voices?limit=20", {
            "data": [{"voice_id": "voice_authorized", "name": "Alice", "language": "English", "type": "private"}],
            "has_more": False, "next_token": None,
        })
        voices = self.api.list_voices()
        self.assertEqual(voices["data"][0]["voice_id"], "voice_authorized")
        self.assertFalse(voices["has_more"])
        for fields in ({"limit": 0}, {"limit": True}, {"limit": 51}):
            with self.assertRaises(ValueError):
                self.api.list_avatars(**fields)
        with self.assertRaises(ValueError):
            self.api.list_voices(limit=101)
        self.assertEqual(len(self.requests), 2)

    def test_dry_list_tools_never_invent_account_resources(self):
        os.environ["HEYGEN_DRY_RUN"] = "true"
        for tool in (self.api.list_avatars, self.api.list_voices):
            result = tool()
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["data"], [])
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
