from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.auth import require_auth
from server.studio_state import StudioRepository


class LogoArtifactDownloadTests(unittest.TestCase):
    def setUp(self):
        from server import studio

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.media = self.root / "media"
        self.job = self.media / "job-a"
        self.job.mkdir(parents=True)
        self.repository = StudioRepository(self.root / "studio.sqlite3", self.media)
        self.repository.create_execution(
            workspace_id="user:user-a", project_id=None, user_id="user-a",
            prompt="Vectorize this logo", execution_id="job-a",
        )
        self.enterContext(patch.object(studio, "repository", self.repository))
        self.enterContext(patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": str(self.media)}))
        self.app = FastAPI()
        self.app.include_router(studio.router)
        self.app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "user-a"})
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def record(self, outputs, *, call_id="vector-call", name="Logo___logo_vectorize"):
        self.repository.append_tool_call(
            workspace_id="user:user-a", execution_id="job-a",
            event={"id": call_id, "name": name, "status": "completed", "result": {"outputs": outputs}},
        )

    def artifact(self, filename="logo.svg", *, directory=None, key="path"):
        path = (directory or self.job) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"<svg>saved logo</svg>")
        return path, {key: str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def download(self, filename="logo.svg", *, execution="job-a", call="vector-call"):
        return self.client.get(f"/api/studio/executions/{execution}/logo-artifacts/{call}/{filename}")

    def test_saved_artifacts_download_with_exact_bytes_as_private_attachments(self):
        for filename in ("logo.svg", "overlay.png", "storyboard.html", "notes.md", "vector.json"):
            with self.subTest(filename=filename):
                _, output = self.artifact(filename, directory=self.job / "bundle")
                self.record([output])
                response = self.download(filename)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.content, b"<svg>saved logo</svg>")
                self.assertEqual(response.headers["content-disposition"], f'attachment; filename="{filename}"')
                self.assertIn("private", response.headers["cache-control"])
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_output_path_record_is_supported(self):
        _, output = self.artifact(key="output_path")
        self.record([output])
        self.assertEqual(self.download().content, b"<svg>saved logo</svg>")

    def test_other_workspaces_and_missing_executions_cannot_download(self):
        _, output = self.artifact()
        self.record([output])
        self.assertEqual(self.download(execution="missing").status_code, 404)
        self.app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "user-b"})
        self.assertEqual(self.download().status_code, 404)

    def test_signed_out_requests_require_authentication(self):
        _, output = self.artifact()
        self.record([output])

        def signed_out():
            raise HTTPException(status_code=401, detail="unauthorized")

        self.app.dependency_overrides[require_auth] = signed_out
        self.assertEqual(self.download().status_code, 401)

    def test_exact_tool_call_and_logo_tool_name_are_required(self):
        _, output = self.artifact()
        self.record([output], name="Other___tool")
        self.assertEqual(self.download().status_code, 404)
        self.record([output])
        self.assertEqual(self.download(call="different-call").status_code, 404)

    def test_unrecorded_filename_is_not_downloadable(self):
        _, output = self.artifact()
        self.artifact("unrecorded.svg")
        self.record([output])
        self.assertEqual(self.download("unrecorded.svg").status_code, 404)

    def test_recorded_path_cannot_read_another_job_or_outside_media(self):
        for directory in (self.media / "job-b", self.root / "private"):
            with self.subTest(directory=directory):
                _, output = self.artifact(directory=directory)
                self.record([output])
                self.assertEqual(self.download().status_code, 404)

    def test_recorded_paths_cannot_traverse_or_follow_foreign_symlinks(self):
        foreign, output = self.artifact(directory=self.media / "job-b")
        (self.job / "logo.svg").symlink_to(foreign)
        for path in ("../job-b/logo.svg", str(self.job / "logo.svg")):
            with self.subTest(path=path):
                self.record([{**output, "path": path}])
                self.assertEqual(self.download().status_code, 404)

    def test_filename_must_be_a_safe_single_filename(self):
        _, output = self.artifact()
        self.record([output])
        for filename in ("..%2Flogo.svg", "%2Flogo.svg", "..%5Clogo.svg", "%00logo.svg"):
            with self.subTest(filename=filename):
                self.assertEqual(self.download(filename).status_code, 404)

    def test_unsupported_recorded_extension_is_not_downloadable(self):
        _, output = self.artifact("private.txt")
        self.record([output])
        self.assertEqual(self.download("private.txt").status_code, 404)

    def test_missing_file_and_changed_or_missing_checksum_are_not_downloadable(self):
        path, output = self.artifact()
        self.record([output])
        path.write_bytes(b"changed")
        self.assertEqual(self.download().status_code, 404)
        self.record([{"path": str(path)}])
        self.assertEqual(self.download().status_code, 404)
        path.unlink()
        self.assertEqual(self.download().status_code, 404)

    def test_malformed_output_records_are_not_downloadable(self):
        for outputs in (None, {}, [None, "logo.svg", {}, {"path": 123}], [{"path": "https://example.test/logo.svg?token=private"}]):
            with self.subTest(outputs=outputs):
                self.record(outputs)
                response = self.download()
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("private", response.text)
