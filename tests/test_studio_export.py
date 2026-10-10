from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.auth import require_auth
from server.studio_state import StudioRepository


class StudioExportTests(unittest.TestCase):
    def setUp(self):
        from server import studio
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        repo = StudioRepository(root / "state.sqlite3", root / "media")
        repo.init()
        repo.ensure_workspace("user:user-a", "user-a")
        repo.create_project("user:user-a", "user-a", "Test project", project_id="export-test")
        self.patch = patch.object(studio, "repository", repo)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        app = FastAPI()
        app.include_router(studio.router)
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "user-a"})
        self.app = app
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_disconnected_export_does_not_invent_a_render_price(self):
        response = self.client.get("/api/studio/projects/export-test/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"state": "disconnected", "format": "project_json",
                                           "resolution": None, "size_bytes": None})
        self.assertNotIn("estimate", response.json())

    def test_export_checks_project_ownership_and_authentication(self):
        self.app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "user-b"})
        self.assertEqual(self.client.get("/api/studio/projects/export-test/export").status_code, 404)
        def signed_out():
            raise HTTPException(status_code=401, detail="unauthorized")
        self.app.dependency_overrides[require_auth] = signed_out
        self.assertEqual(self.client.get("/api/studio/projects/export-test/export").status_code, 401)
