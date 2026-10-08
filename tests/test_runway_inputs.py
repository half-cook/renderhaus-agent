from __future__ import annotations

import base64
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from server import runway_inputs as inputs
from server.billing_rates import cost_for
from server.studio_state import StudioRepository


class RunwayInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = patch.dict(os.environ, {"RUNWAY_DRY_RUN": "false", "RUNWAYML_API_SECRET": "offline-key"})
        self.live.start()
        self.addCleanup(self.live.stop)

    def video_args(self, source):
        return {"video_path_or_url": source, "prompt": "Add snow", "video_duration_seconds": 2}

    def test_actual_duration_overrides_client_quote_before_submission(self):
        uri = "data:video/webm;base64," + base64.b64encode(b"exact source bytes").decode()
        with patch.object(inputs, "_probe_video", return_value=8.5), patch.object(inputs, "_request") as request:
            prepared = inputs.prepare_runway_arguments("video_to_video", self.video_args(uri))
        self.assertEqual(prepared["video_path_or_url"], uri)
        self.assertEqual(prepared["video_duration_seconds"], 8.5)
        self.assertEqual(cost_for("runway", "video_to_video", prepared).provider_cents, 238)
        request.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "host ffmpeg/ffprobe unavailable")
    def test_real_webm_is_measured_and_preserves_mime_and_bytes(self):
        path = self.root / "source.webm"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=24", "-t", "2", "-c:v", "libvpx-vp9", str(path)], check=True, timeout=30)
        uri = "data:video/webm;base64," + base64.b64encode(path.read_bytes()).decode()
        prepared = inputs.prepare_runway_arguments("video_to_video", self.video_args(uri))
        self.assertEqual(prepared["video_path_or_url"], uri)
        self.assertAlmostEqual(prepared["video_duration_seconds"], 2, places=1)

    def test_bad_declared_args_fail_before_any_upload_or_source_fetch(self):
        arguments = {**self.video_args("https://example.com/source.mp4"), "seed": -1}
        with patch.object(inputs, "_capture_video") as capture, patch.object(inputs, "_request") as request:
            with self.assertRaises(ValueError):
                inputs.prepare_runway_arguments("video_to_video", arguments)
        capture.assert_not_called()
        request.assert_not_called()

    def test_reference_timestamp_is_checked_against_measured_duration(self):
        arguments = {**self.video_args("data:video/mp4;base64,dmlkZW8="), "video_duration_seconds": 10, "reference_image_path_or_url": "data:image/png;base64,aW1hZ2U=", "reference_seconds": 8}
        with patch.object(inputs, "_probe_video", return_value=3), patch.object(inputs, "_publish_file") as publish:
            with self.assertRaises(ValueError):
                inputs.prepare_runway_arguments("video_to_video", arguments)
        publish.assert_not_called()

    def test_dry_run_does_not_fetch_or_probe_remote_media(self):
        with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "true"}), patch.object(inputs, "_capture_video") as capture, patch.object(inputs, "_probe_video") as probe:
            arguments = self.video_args("https://example.com/source.mp4")
            self.assertEqual(inputs.prepare_runway_arguments("video_to_video", arguments), arguments)
        capture.assert_not_called()
        probe.assert_not_called()

    def test_external_aleph_upload_handle_cannot_bypass_measurement(self):
        with self.assertRaisesRegex(ValueError, "cannot measure"):
            inputs.prepare_runway_arguments("video_to_video", self.video_args("runway://external-upload"))

    def test_extensionless_owned_image_uses_scoped_media_metadata(self):
        repo = StudioRepository(self.root / "state.sqlite3", self.root / "media")
        project = repo.create_project("owner", "user", "Inputs")
        ref = repo.register_bytes(workspace_id="owner", project_id=project["id"], user_id="user", kind="image", content=b"image fixture", filename="opaque", mime_type="image/png")
        arguments = {"image_path_or_url": "renderhaus-asset://" + ref.version_id, "prompt": "Animate"}
        with patch("server.studio.repository", repo):
            result = inputs.prepare_runway_arguments("image_to_video", arguments, workspace_id="owner", source_resolver=lambda version: str(repo.version_path("owner", version)))
            self.assertTrue(result["image_path_or_url"].startswith("data:image/png;base64,"))
            with self.assertRaises(KeyError):
                inputs.prepare_runway_arguments("image_to_video", arguments, workspace_id="intruder", source_resolver=lambda version: str(repo.version_path("intruder", version)))

    def test_large_owned_media_uses_official_upload_without_api_auth_on_storage(self):
        path = self.root / "opaque"
        path.write_bytes(b"x" * (4 * 1024 * 1024))
        calls = []

        def upload(request):
            calls.append(request)
            return httpx.Response(204)

        real_client = httpx.Client
        with patch.object(inputs, "_request", return_value={"uploadUrl": "https://storage.example.com/upload?signature=" + "a" * 2100, "fields": {"policy": "offline"}, "runwayUri": "runway://upload-id"}) as create, patch.object(inputs.httpx, "Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(upload), **kwargs)):
            result = inputs._publish_file(path, "opaque", "image/png")
        self.assertEqual(result, "runway://upload-id")
        create.assert_called_once_with("POST", "/uploads", {"type": "ephemeral", "filename": "opaque.png"})
        self.assertEqual(len(calls), 1)
        self.assertNotIn("authorization", calls[0].headers)
        self.assertNotIn("x-runway-version", calls[0].headers)
        self.assertIn(b'name="file"; filename="opaque.png"', calls[0].content)

    def test_failed_upload_does_not_retry_or_submit_a_generation(self):
        path = self.root / "large.png"
        path.write_bytes(b"x" * (4 * 1024 * 1024))
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = httpx.Response(403)
        with patch.object(inputs, "_request", return_value={"uploadUrl": "https://storage.example.com/upload", "fields": {}, "runwayUri": "runway://upload-id"}) as request, patch.object(inputs.httpx, "Client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "No generation was submitted"):
                inputs._publish_file(path)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(client.post.call_count, 1)

    def test_large_owned_media_dry_run_never_uploads(self):
        path = self.root / "large.png"
        path.write_bytes(b"x" * (4 * 1024 * 1024))
        with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "true"}), patch.object(inputs, "_request") as request:
            self.assertTrue(inputs._publish_file(path).startswith("runway://"))
        request.assert_not_called()

    def test_private_dns_answers_are_rejected_before_connecting(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "224.0.0.1"):
            with self.subTest(address=address), patch.object(inputs.socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]), patch.object(inputs.socket, "create_connection") as connect:
                with self.assertRaisesRegex(ValueError, "public addresses"):
                    inputs._PublicHTTPSConnection("attacker.example.com").connect()
                connect.assert_not_called()

    def test_connection_pins_validated_ip_but_tls_uses_original_hostname(self):
        connection = inputs._PublicHTTPSConnection("media.example.com", timeout=90)
        connection._context = MagicMock()
        with patch.object(inputs.socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]), patch.object(inputs.socket, "create_connection", return_value=MagicMock()) as connect:
            connection.connect()
        connect.assert_called_once_with(("8.8.8.8", 443), 90)
        self.assertEqual(connection._context.wrap_socket.call_args.kwargs["server_hostname"], "media.example.com")
        connection.close()

    def test_remote_capture_preserves_mime_and_never_follows_redirects(self):
        response = io.BytesIO(b"source bytes")
        response.status = 200
        response.getheader = lambda *args: "video/webm"
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch.object(inputs, "_PublicHTTPSConnection", return_value=connection):
            self.assertEqual(inputs._capture_video("https://media.example.com/clip", self.root / "captured"), "video/webm")
        self.assertEqual((self.root / "captured").read_bytes(), b"source bytes")
        response = io.BytesIO(b"")
        response.status = 302
        connection.getresponse.return_value = response
        with patch.object(inputs, "_PublicHTTPSConnection", return_value=connection), self.assertRaises(ValueError):
            inputs._capture_video("https://media.example.com/clip", self.root / "redirect")

    def test_probe_rejects_bad_media_limits_and_disables_network_protocols(self):
        for duration, fps, height in [(1, "24/1", 720), (31, "24/1", 720), (3, "60/1", 720), (3, "24/1", 2160)]:
            result = subprocess.CompletedProcess([], 0, json.dumps({"format": {"duration": duration}, "streams": [{"codec_type": "video", "width": 3840, "height": height, "r_frame_rate": fps}]}))
            with self.subTest(duration=duration, fps=fps, height=height), patch.object(inputs.subprocess, "run", return_value=result) as probe:
                with self.assertRaises(ValueError):
                    inputs._probe_video(self.root / "source")
                self.assertIn("file,pipe", probe.call_args.args[0])

    def test_remote_agent_without_scoped_assets_fails_before_paid_work(self):
        with patch.object(inputs, "_request") as request:
            with self.assertRaisesRegex(ValueError, "scoped Studio"):
                inputs.prepare_runway_arguments("text_to_video", {"prompt": "Move"}, workspace_id="owner")
        request.assert_not_called()

    def test_task_ownership_survives_repository_reload_and_blocks_cross_workspace(self):
        repo = StudioRepository(self.root / "state.sqlite3", self.root / "media")
        project = repo.create_project("owner", "user", "Runway")
        job = "00000000-0000-4000-8000-000000000001"
        repo.record_provider_task("owner", project["id"], "runway", job)
        repo = StudioRepository(self.root / "state.sqlite3", self.root / "media")
        with patch("server.studio.repository", repo):
            result = inputs.prepare_runway_arguments("get_runway_task", {"job_id": job}, workspace_id="owner")
            self.assertEqual(result["job_id"], job)
            with self.assertRaisesRegex(ValueError, "not owned"):
                inputs.prepare_runway_arguments("get_runway_task", {"job_id": job}, workspace_id="intruder")
