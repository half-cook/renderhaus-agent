from __future__ import annotations

import importlib
import io
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from server.studio_state import StudioRepository
from server.uploads import validate_uploaded_media


class UploadedMediaValidationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "upload"

    def test_real_supported_raster_images_decode_and_keep_original_bytes(self):
        for suffix, image_format in (("png", "PNG"), ("jpg", "JPEG"), ("webp", "WEBP"), ("gif", "GIF")):
            with self.subTest(suffix=suffix):
                Image.new("RGB", (20, 30), "red").save(self.path, format=image_format)
                original = self.path.read_bytes()
                validate_uploaded_media(self.path, filename=f"portrait.{suffix}", kind="image")
                self.assertEqual(self.path.read_bytes(), original)

    def test_text_truncated_and_mismatched_raster_uploads_are_rejected(self):
        image = io.BytesIO()
        Image.new("RGB", (20, 30), "red").save(image, format="PNG")
        for data, filename in ((b"not an image", "fake.png"), (image.getvalue()[:40], "broken.png"),
                               (image.getvalue(), "wrong.jpg")):
            with self.subTest(filename=filename):
                self.path.write_bytes(data)
                with self.assertRaises(HTTPException) as raised:
                    validate_uploaded_media(self.path, filename=filename, kind="image")
                self.assertEqual(raised.exception.status_code, 415)

    def test_image_bomb_is_rejected_before_decode(self):
        Image.new("RGB", (20, 30), "red").save(self.path, format="PNG")
        with patch.object(Image, "MAX_IMAGE_PIXELS", 200), self.assertRaises(HTTPException) as raised:
            validate_uploaded_media(self.path, filename="large.png", kind="image")
        self.assertEqual(raised.exception.status_code, 415)

    def test_svg_reuses_existing_sanitizer_and_rejects_non_svg_xml(self):
        for data, valid in ((b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="30"><rect width="20" height="30"/></svg>', True),
                            (b"<html>not an SVG</html>", False), (b"text", False)):
            self.path.write_bytes(data)
            if valid:
                validate_uploaded_media(self.path, filename="drawing.svg", kind="image")
            else:
                with self.assertRaises(HTTPException) as raised:
                    validate_uploaded_media(self.path, filename="drawing.svg", kind="image")
                self.assertEqual(raised.exception.status_code, 415)

    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required for real media validation")
    def test_real_audio_and_wrong_stream_or_container(self):
        with wave.open(str(self.path), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x01\x00" * 800)
        validate_uploaded_media(self.path, filename="voice.wav", kind="audio")
        for filename, kind in (("wrong.mp4", "video"), ("wrong.mp3", "audio")):
            with self.subTest(filename=filename), self.assertRaises(HTTPException) as raised:
                validate_uploaded_media(self.path, filename=filename, kind=kind)
            self.assertEqual(raised.exception.status_code, 415)
        self.path.write_bytes(b"not real audio")
        with self.assertRaises(HTTPException) as raised:
            validate_uploaded_media(self.path, filename="fake.wav", kind="audio")
        self.assertEqual(raised.exception.status_code, 415)

    @unittest.skipUnless(shutil.which("ffprobe") and shutil.which("ffmpeg"), "FFmpeg is required for real video validation")
    def test_real_video_and_missing_video_stream(self):
        video = self.root / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=32x48:d=0.2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                       check=True, capture_output=True, timeout=30)
        validate_uploaded_media(video, filename="clip.mp4", kind="video")
        with self.assertRaises(HTTPException) as raised:
            validate_uploaded_media(video, filename="voice.m4a", kind="audio")
        self.assertEqual(raised.exception.status_code, 415)

    def test_unavailable_probe_returns_retryable_error_without_accepting_bytes(self):
        self.path.write_bytes(b"not media")
        with patch("server.uploads.shutil.which", return_value=None), self.assertRaises(HTTPException) as raised:
            validate_uploaded_media(self.path, filename="clip.mp4", kind="video")
        self.assertEqual(raised.exception.status_code, 503)


class UploadBoundaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.repository = StudioRepository(root / "studio.sqlite3", root / "media")
        self.repository.create_project("user:local", "local", "Uploads", project_id="uploads")
        self.studio = importlib.import_module("server.studio")
        self.app = importlib.import_module("server.app")
        self.enterContext(patch.object(self.studio, "repository", self.repository))
        self.enterContext(patch.dict(os.environ, {"RENDERHAUS_DISABLE_AUTH": "true"}))
        self.client = TestClient(self.app.app)
        self.addCleanup(self.client.close)

    def test_invalid_studio_upload_creates_no_asset_and_real_png_still_works(self):
        for filename in ("not-media.png", "not-media.mp4", "not-media.wav"):
            with self.subTest(filename=filename):
                response = self.client.post("/api/studio/upload?project_id=uploads",
                                            files={"file": (filename, b"plain ASCII pretending to be media")})
                self.assertEqual(response.status_code, 415, response.text)
        with sqlite3.connect(self.repository.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM asset_versions").fetchone()[0], 0)
        image = io.BytesIO()
        Image.new("RGB", (20, 30), "red").save(image, format="PNG")
        response = self.client.post("/api/studio/upload?project_id=uploads",
                                    files={"file": ("portrait.png", image.getvalue(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.repository.version_path("user:local", response.json()["version_id"]).read_bytes(), image.getvalue())

    def test_legacy_magic_header_without_decodable_image_is_rejected(self):
        with patch.object(self.app, "register_upload") as register:
            response = self.client.post("/api/uploads", files={"file": ("broken.png", b"\x89PNG\r\n\x1a\nnot an image", "image/png")})
        self.assertEqual(response.status_code, 415, response.text)
        register.assert_not_called()
