from __future__ import annotations

import importlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from server.studio_state import StudioRepository

app_module = importlib.import_module("server.app")
studio_module = importlib.import_module("server.studio")
MB = 1024 * 1024
PNG = b"\x89PNG\r\n\x1a\n"


class ServerUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.repository = StudioRepository(root / "studio.sqlite3", root / "media")
        self.repository.create_project("user:local", "local", "Uploads", project_id="uploads")
        self.enterContext(patch.object(studio_module, "repository", self.repository))
        self.enterContext(patch.object(app_module, "register_upload", return_value=SimpleNamespace(id="asset", filename="frame.png")))
        self.enterContext(patch.dict(os.environ, {
            "STUDIO_MAX_UPLOAD_MB": "1",
            "STUDIO_MAX_IMAGE_UPLOAD_MB": "1",
            "STUDIO_MAX_VIDEO_UPLOAD_MB": "2",
            "STUDIO_MAX_AUDIO_UPLOAD_MB": "3",
            "RENDERHAUS_DISABLE_AUTH": "true",
        }))
        self.client = TestClient(app_module.app)
        self.addCleanup(self.client.close)

    def upload(self, filename: str, content: bytes, mime: str = "application/octet-stream"):
        return self.client.post(
            "/api/studio/upload?project_id=uploads", files={"file": (filename, content, mime)}
        )

    def test_each_kind_rejects_limit_plus_one_without_saving_an_asset(self) -> None:
        for filename, limit in (("frame.png", 1), ("clip.mp4", 2), ("sound.wav", 3)):
            with self.subTest(filename=filename):
                response = self.upload(filename, b"x" * (limit * MB + 1))
                self.assertEqual(response.status_code, 413)
                self.assertEqual(response.json(), {"detail": f"File is larger than {limit} MB."})
        with sqlite3.connect(self.repository.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM asset_versions").fetchone()[0], 0)
        self.assertEqual(list(self.repository.media_root.rglob("*.mp4")), [])

    def test_each_kind_accepts_exact_limit_and_preserves_the_bytes(self) -> None:
        for filename, kind, limit in (("frame.png", "image", 1), ("clip.mp4", "video", 2), ("sound.wav", "audio", 3)):
            with self.subTest(kind=kind):
                content = b"x" * (limit * MB)
                response = self.upload(filename, content)
                self.assertEqual(response.status_code, 200, response.text)
                asset = response.json()
                self.assertEqual(asset["kind"], kind)
                self.assertEqual(asset["size_bytes"], limit * MB)
                path = self.repository.version_path("user:local", asset["version_id"])
                self.assertEqual(path.read_bytes(), content)

    def test_upload_reads_bounded_chunks_and_registers_from_a_file(self) -> None:
        original = UploadFile.read
        sizes = []

        async def bounded_read(file, size=-1):
            sizes.append(size)
            self.assertGreater(size, 0, "Upload must not read the whole body")
            self.assertLessEqual(size, MB, "Upload chunks must remain bounded")
            return await original(file, size)

        with patch.object(UploadFile, "read", bounded_read), patch.object(
            self.repository, "register_bytes", side_effect=AssertionError("Use a file path")
        ):
            response = self.upload("clip.mp4", b"x" * (MB + 100))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreater(len(sizes), 1)

    def test_unsupported_type_and_empty_file_have_readable_errors(self) -> None:
        response = self.upload("notes.txt", b"hello")
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["detail"], "Use an image, video, or audio file.")
        response = self.upload("empty.mp4", b"")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "The file was empty.")

    def test_health_and_legacy_config_expose_the_effective_limits(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["max_upload_mb"], 3)
        self.assertEqual(response.json()["max_upload_mb_by_kind"], {"image": 1, "video": 2, "audio": 3})
        self.assertEqual(self.client.get("/api/config").json()["max_upload_mb"], 1)

    def test_legacy_image_limit_is_authoritative(self) -> None:
        response = self.client.post("/api/uploads", files={"file": ("frame.png", PNG + b"x" * (MB + 1 - len(PNG)), "image/png")})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": "File is larger than 1 MB."})

    def test_legacy_route_still_rejects_video_and_spoofed_images(self) -> None:
        for filename in ("clip.mp4", "fake.png"):
            response = self.client.post("/api/uploads", files={"file": (filename, b"not an image", "image/png")})
            self.assertEqual(response.status_code, 415)

    def test_legacy_exact_limit_uses_bounded_reads(self) -> None:
        original = UploadFile.read

        async def bounded_read(file, size=-1):
            self.assertGreater(size, 0)
            self.assertLessEqual(size, MB)
            return await original(file, size)

        with patch.object(UploadFile, "read", bounded_read), patch.object(
            app_module, "register_upload", return_value=SimpleNamespace(id="asset", filename="frame.png")
        ):
            response = self.client.post("/api/uploads", files={"file": ("frame.png", PNG + b"x" * (MB - len(PNG)), "image/png")})
        self.assertEqual(response.status_code, 201, response.text)

    def test_upload_still_requires_authentication_when_clerk_is_enabled(self) -> None:
        with patch("server.auth.clerk_enabled", return_value=True), patch("server.auth.authenticate_request") as authenticate:
            authenticate.return_value.is_signed_in = False
            authenticate.return_value.reason = None
            response = self.upload("frame.png", PNG)
        self.assertEqual(response.status_code, 401)


class UploadLimitConfigurationTests(unittest.TestCase):
    def test_defaults_and_overrides(self) -> None:
        from server.uploads import upload_limits_mb

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(upload_limits_mb(), {"image": 15, "video": 100, "audio": 50})
        with patch.dict(os.environ, {"STUDIO_MAX_UPLOAD_MB": "8", "STUDIO_MAX_VIDEO_UPLOAD_MB": "20"}, clear=True):
            self.assertEqual(upload_limits_mb(), {"image": 8, "video": 20, "audio": 8})

    def test_invalid_limits_fail_instead_of_removing_the_bound(self) -> None:
        from server.uploads import upload_limits_mb

        for value in ("0", "-1", "NaN", "1.5", "unlimited"):
            with self.subTest(value=value), patch.dict(os.environ, {"STUDIO_MAX_UPLOAD_MB": value}, clear=True):
                with self.assertRaises(ValueError):
                    upload_limits_mb()
