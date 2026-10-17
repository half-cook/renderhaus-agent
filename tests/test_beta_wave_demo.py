from __future__ import annotations

import json
import unittest


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
        doc["nodes"][0]["data"]["config"]["prompt"] = "mine"
        self.repo.save_canvas("ws-a", first["project_id"], "user-a", doc)
        theirs = self.repo.get_canvas("ws-b", other["project_id"])["document"]
        self.assertNotEqual(theirs["nodes"][0]["data"]["config"]["prompt"], "mine")
        self.assertNotEqual(demo_template()["nodes"][0]["data"]["config"]["prompt"], "mine")
        # no node references a provider or carries a paid tool
        text = json.dumps(demo_template()).lower()
        for banned in ("seedance", "kling", "runway", "providerid", "toolid"):
            self.assertNotIn(banned, text)

    def test_route_mounted(self):
        from server.app import app
        paths = {(p, m.upper()) for p, ops in app.openapi()["paths"].items() for m in ops}
        self.assertIn(("/api/studio/demo-project", "POST"), paths)
        self.assertNotIn(("/api/beta/wave", "GET"), paths)
        self.assertNotIn(("/api/beta/hold", "POST"), paths)

    def test_demo_has_three_approved_static_shots_with_editable_trims(self):
        from server.demo_project import demo_template
        self.assertTrue(demo_template()["nodes"][0]["data"]["config"]["prompt"])
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
