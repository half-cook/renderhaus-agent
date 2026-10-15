from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import boto3
import requests
from fastapi.testclient import TestClient
from moto import mock_aws

from server import assets
from server import direct_uploads
from server.studio_state import StudioRepository

MIB = 1024 * 1024
ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_REGION": "us-east-1",
    "STUDIO_INGEST_BUCKET": "rh-ingest-test",
    "ASSET_SIGNING_SECRET": "test-secret",
    "RENDERHAUS_DISABLE_AUTH": "true",
    "STUDIO_MAX_DIRECT_UPLOAD_MB": "64",
}


class DirectUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, ENV))
        self.enterContext(mock_aws())
        assets._session.cache_clear()
        self.addCleanup(assets._session.cache_clear)
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="rh-ingest-test")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.repository = StudioRepository(root / "studio.sqlite3", root / "media")
        self.repository.create_project("user:local", "local", "Uploads", project_id="uploads")
        self.enterContext(patch("server.studio_state.repository", self.repository))
        app_module = importlib.import_module("server.app")
        self.client = TestClient(app_module.app)
        self.addCleanup(self.client.close)

    def create(self, size: int, filename: str = "take.mov"):
        return self.client.post(
            "/api/studio/uploads/direct/create",
            json={"project_id": "uploads", "filename": filename, "size_bytes": size, "content_type": "video/quicktime"},
        )

    def put_parts(self, token: str, data: bytes, part_size: int, numbers: list[int]) -> dict[int, str]:
        urls = self.client.post("/api/studio/uploads/direct/sign-parts", json={"token": token, "part_numbers": numbers}).json()["urls"]
        etags = {}
        for number in numbers:
            chunk = data[(number - 1) * part_size: number * part_size]
            response = requests.put(urls[str(number)], data=chunk)
            self.assertEqual(response.status_code, 200)
            etags[number] = response.headers["ETag"]
        return etags

    def test_health_reports_direct_upload(self) -> None:
        body = self.client.get("/api/health").json()
        self.assertEqual(body["direct_upload"], {"enabled": True, "max_upload_mb": 64, "min_part_bytes": 8 * MIB})

    def test_disabled_without_bucket_or_by_flag(self) -> None:
        with patch.dict(os.environ, {"STUDIO_DIRECT_UPLOAD": "false"}):
            self.assertFalse(direct_uploads.direct_upload_enabled())
            self.assertEqual(self.create(10 * MIB).status_code, 404)
        with patch.dict(os.environ, {"STUDIO_INGEST_BUCKET": "", "AWS_S3_BUCKET": ""}):
            self.assertFalse(direct_uploads.direct_upload_enabled())

    def test_drop_then_resume_from_last_completed_part(self) -> None:
        data = os.urandom(20 * MIB + 123)
        created = self.create(len(data))
        self.assertEqual(created.status_code, 201)
        token, part_size = created.json()["token"], created.json()["part_size"]
        self.assertEqual(part_size, 8 * MIB)
        self.assertEqual(created.json()["part_count"], 3)
        # First attempt stores part 1 only, then the connection "drops".
        self.put_parts(token, data, part_size, [1])
        status = self.client.post("/api/studio/uploads/direct/status", json={"token": token}).json()
        self.assertEqual([p["part_number"] for p in status["completed_parts"]], [1])
        self.assertEqual(status["uploaded_bytes"], 8 * MIB)
        # Completing early names the missing parts instead of failing silently.
        early = self.client.post("/api/studio/uploads/direct/complete", json={"token": token})
        self.assertEqual(early.status_code, 409)
        self.assertEqual(early.json()["detail"]["missing_parts"], [2, 3])
        # Resume uploads only what is missing.
        self.put_parts(token, data, part_size, [2, 3])
        done = self.client.post("/api/studio/uploads/direct/complete", json={"token": token})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["kind"], "video")
        self.assertEqual(done.json()["filename"], "take.mov")
        self.assertEqual(done.json()["size_bytes"], len(data))
        stored = list(self.repository.media_root.rglob("*.mov"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].read_bytes(), data)

    def test_size_and_type_limits(self) -> None:
        self.assertEqual(self.create(64 * MIB + 1).status_code, 413)
        self.assertEqual(self.create(64 * MIB).status_code, 201)
        self.assertEqual(self.create(10, "notes.txt").status_code, 415)
        missing = self.client.post(
            "/api/studio/uploads/direct/create",
            json={"project_id": "nope", "filename": "a.mp4", "size_bytes": 10},
        )
        self.assertEqual(missing.status_code, 404)

    def test_tampered_or_foreign_token_is_rejected(self) -> None:
        token = self.create(9 * MIB).json()["token"]
        body, mac = token.rsplit(".", 1)
        bad = self.client.post("/api/studio/uploads/direct/status", json={"token": body + "." + "0" * len(mac)})
        self.assertEqual(bad.status_code, 400)
        import base64, json
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        forged = direct_uploads._sign({**payload, "uid": "someone-else"})
        self.assertEqual(self.client.post("/api/studio/uploads/direct/status", json={"token": forged}).status_code, 404)
        out_of_range = self.client.post("/api/studio/uploads/direct/sign-parts", json={"token": token, "part_numbers": [3]})
        self.assertEqual(out_of_range.status_code, 400)

    def test_truncated_part_is_not_counted_as_done(self) -> None:
        data = os.urandom(17 * MIB)
        created = self.create(len(data)).json()
        url = self.client.post("/api/studio/uploads/direct/sign-parts", json={"token": created["token"], "part_numbers": [1]}).json()["urls"]["1"]
        requests.put(url, data=data[: 6 * MIB])
        status = self.client.post("/api/studio/uploads/direct/status", json={"token": created["token"]}).json()
        self.assertEqual(status["completed_parts"], [])

    def test_abort(self) -> None:
        token = self.create(9 * MIB).json()["token"]
        self.assertEqual(self.client.post("/api/studio/uploads/direct/abort", json={"token": token}).json(), {"aborted": True})
        self.assertEqual(self.client.post("/api/studio/uploads/direct/status", json={"token": token}).status_code, 410)

    def test_part_size_respects_part_cap(self) -> None:
        self.assertEqual(direct_uploads.part_size_for(1), 8 * MIB)
        big = 200 * 1024 * MIB
        size = direct_uploads.part_size_for(big)
        self.assertLessEqual(-(-big // size), 10_000)
        self.assertEqual(size % MIB, 0)


if __name__ == "__main__":
    unittest.main()
