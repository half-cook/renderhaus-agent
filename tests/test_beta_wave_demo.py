from __future__ import annotations

import json
import time
import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import require_auth
from test_beta_credits import BetaFixture


class WaveCounterAndHoldTests(BetaFixture, unittest.TestCase):
    def test_wave_counter_exposes_only_counters(self):
        self.configure(wave_size=50, global_cap_cents=500_000)
        wave = self.beta.get_wave()
        self.assertEqual({k for k in wave}, {"capacity", "claimed", "remaining", "held", "status", "wave", "hold_seconds", "updated_at"})
        self.assertEqual((wave["capacity"], wave["claimed"], wave["remaining"], wave["status"]), (50, 0, 50, "open"))
        self.assertEqual(wave["hold_seconds"], 900)
        self.assertNotIn("hash", json.dumps(wave))

    def test_disabled_is_closed(self):
        self.configure(enabled=False)
        self.assertEqual(self.beta.get_wave()["status"], "closed")

    def test_hold_reserves_for_fifteen_minutes_and_blocks_the_last_spot(self):
        self.configure(wave_size=1, global_cap_cents=100_000)
        held = self.beta.hold("one")
        self.assertTrue(held["held"])
        self.assertAlmostEqual(held["expires_at"], int(time.time()) + 900, delta=3)
        self.assertEqual(self.beta.get_wave()["status"], "full")
        self.assert_denied(lambda: self.beta.hold("two"), "This wave is full. Join the waitlist for the next one.")
        self.verify("two", "two@example.com", "+14165550102")
        self.assert_denied(lambda: self.beta.claim("two"), "This wave is full. Join the waitlist for the next one.")
        self.beta.hold("one")  # refreshing your own hold is allowed
        self.verify("one")
        self.assertEqual(self.beta.claim("one")["balance_cents"], 1000)
        self.assertEqual(self.rows("SELECT * FROM beta_holds"), [])

    def test_abandoned_hold_frees_the_spot(self):
        self.configure(wave_size=1, global_cap_cents=100_000)
        self.beta.hold("one")
        with self.repo._connect() as connection:
            connection.execute("UPDATE beta_holds SET expires_at = ?", (int(time.time()) - 1,))
        self.assertEqual(self.beta.get_wave()["status"], "open")
        self.assertTrue(self.beta.hold("two")["held"])
        self.verify("two", "two@example.com", "+14165550102")
        self.assertEqual(self.beta.claim("two")["balance_cents"], 1000)

    def test_hold_after_grant_is_idempotent_and_disabled_refuses(self):
        self.verify()
        self.beta.claim("one")
        self.assertFalse(self.beta.hold("one")["held"])
        self.configure(enabled=False)
        self.assert_denied(lambda: self.beta.hold("one"), "Free beta credits are disabled.")

    def test_routes(self):
        from server import beta as api
        app = FastAPI()
        app.include_router(api.router)
        app.dependency_overrides[api.get_beta_credits] = lambda: self.beta
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "one"})
        client = TestClient(app)
        self.addCleanup(client.close)
        self.assertEqual(client.get("/api/beta/wave").json()["status"], "open")
        self.assertTrue(client.post("/api/beta/hold").json()["held"])
        app.dependency_overrides[require_auth] = lambda: None
        self.assertEqual(client.post("/api/beta/hold").status_code, 401)
        self.assertEqual(client.get("/api/beta/wave").status_code, 200)


class DemoProjectTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from server.studio_state import StudioRepository
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.repo = StudioRepository(root / "state.sqlite3", root / "media")
        self.repo.init()

    def test_copy_is_per_user_idempotent_and_free(self):
        from server.demo_project import copy_demo_project, demo_template
        first = copy_demo_project(self.repo, "ws-a", "user-a")
        again = copy_demo_project(self.repo, "ws-a", "user-a")
        other = copy_demo_project(self.repo, "ws-b", "user-b")
        self.assertTrue(first["copied"])
        self.assertFalse(again["copied"])
        self.assertEqual(first["project_id"], again["project_id"])
        self.assertNotEqual(first["project_id"], other["project_id"])
        doc = self.repo.get_canvas("ws-a", first["project_id"])["document"]
        self.assertEqual(doc["projectName"], "Matte travel mug")
        self.assertEqual(len(doc["nodes"]), len(demo_template()["nodes"]))
        # editing one copy never touches the other or the shared template
        doc["nodes"][0]["data"]["config"]["text"] = "mine"
        self.repo.save_canvas("ws-a", first["project_id"], "user-a", doc)
        theirs = self.repo.get_canvas("ws-b", other["project_id"])["document"]
        self.assertNotEqual(theirs["nodes"][0]["data"]["config"]["text"], "mine")
        self.assertNotEqual(demo_template()["nodes"][0]["data"]["config"]["text"], "mine")
        # no node references a provider or carries a paid tool
        text = json.dumps(demo_template()).lower()
        for banned in ("seedance", "kling", "runway", "providerid", "toolid"):
            self.assertNotIn(banned, text)

    def test_route_mounted(self):
        from server.app import app
        paths = {(p, m.upper()) for p, ops in app.openapi()["paths"].items() for m in ops}
        self.assertIn(("/api/studio/demo-project", "POST"), paths)
        self.assertIn(("/api/beta/wave", "GET"), paths)
        self.assertIn(("/api/beta/hold", "POST"), paths)

    def test_demo_has_three_approved_static_shots_with_editable_trims(self):
        from server.demo_project import demo_template
        shots = [node for node in demo_template()["nodes"] if node["data"]["kind"] == "video"]
        self.assertEqual(len(shots), 3)
        for index, shot in enumerate(shots):
            data = shot["data"]
            self.assertTrue(data["approved"])
            self.assertEqual(data["storyOrder"], index)
            self.assertEqual(data["config"]["duration_seconds"], 5)
            self.assertEqual(data["config"]["trim_in_seconds"], 0)
            self.assertEqual(data["config"]["trim_out_seconds"], 5)
            self.assertRegex(data["config"]["thumbnail_url"], r"^/beta/shot-[a-z]+\.jpg$")
            self.assertNotIn("toolId", data)
            self.assertNotIn("providerId", data)


if __name__ == "__main__":
    unittest.main()
