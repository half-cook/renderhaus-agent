from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.browser_e2e_hook import fingerprint, handle_event, read_state, record


class BrowserE2EHookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text(".renderhaus/\n.env*\n")
        (self.root / "server").mkdir()
        self.source = self.root / "server" / "app.py"
        self.source.write_text("original app")
        self.event("UserPromptSubmit")

    def event(self, name, **kwargs):
        return handle_event(self.root, {
            "session_id": "test-session", "turn_id": "turn-1",
            "hook_event_name": name, **kwargs,
        })

    def report(self, status="passed"):
        return {
            "status": status,
            "scenario": "Approval flow in Comet",
            "url": "http://localhost:5174/canvas",
            "steps": ["Opened the app", "Submitted a prompt", "Observed approval"],
            "expected": "A successful artifact after approval",
            "observed": "The artifact opened" if status == "passed" else "Login required",
            "evidence": ["Browser accessibility snapshot observed in tool output"],
        }

    def test_existing_dirty_code_and_docs_do_not_trigger_unrelated_e2e(self):
        (self.root / "README.md").write_text("documentation")
        self.assertEqual(self.event("Stop"), {})

    def test_changed_app_requires_browser_evidence(self):
        self.source.write_text("fixed app")
        result = self.event("Stop")
        self.assertEqual(result["decision"], "block")
        self.assertIn("Comet", result["reason"])

    def test_pass_is_invalidated_by_further_edits(self):
        self.source.write_text("fixed app")
        record(self.root, "test-session", self.report())
        self.assertEqual(self.event("Stop"), {})
        self.source.write_text("another fix")
        self.assertEqual(self.event("Stop")["decision"], "block")

    def test_login_handoff_stays_pending_and_rechecks_next_turn(self):
        self.source.write_text("fixed app")
        record(self.root, "test-session", self.report("waiting_login"))
        self.assertIn("pending", self.event("Stop")["systemMessage"])
        self.assertTrue(read_state(self.root, "test-session")["pending"])
        self.event("UserPromptSubmit", turn_id="turn-2")
        self.assertEqual(self.event("Stop", turn_id="turn-2")["decision"], "block")

    def test_blocker_cannot_cover_later_source_changes(self):
        record(self.root, "test-session", self.report("blocked"))
        self.source.write_text("changed after blocker")
        self.assertEqual(self.event("Stop")["decision"], "block")

    def test_continuation_is_bounded_without_claiming_success(self):
        self.source.write_text("fixed app")
        result = self.event("Stop", stop_hook_active=True)
        self.assertNotIn("decision", result)
        self.assertIn("incomplete", result["systemMessage"])
        self.assertTrue(read_state(self.root, "test-session")["pending"])

    def test_report_requires_observations_and_avoids_signed_urls(self):
        for changed in ({"evidence": []}, {"steps": []}, {"observed": ""},
                        {"url": "http://localhost/asset?ticket=private"},
                        {"url": "http://secret@example.test/"}, {"status": "skipped"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                record(self.root, "test-session", {**self.report(), **changed})

    def test_source_hash_ignores_receipts_and_secrets(self):
        before = fingerprint(self.root)
        (self.root / "server" / ".env.local").write_text("secret")
        record(self.root, "test-session", self.report())
        self.assertEqual(fingerprint(self.root), before)

    def test_other_session_cannot_reuse_a_pass(self):
        handle_event(self.root, {"session_id": "other", "hook_event_name": "UserPromptSubmit"})
        self.source.write_text("new app")
        record(self.root, "test-session", self.report())
        result = handle_event(self.root, {"session_id": "other", "hook_event_name": "Stop"})
        self.assertEqual(result["decision"], "block")

    def test_plan_mode_does_not_force_browser_execution(self):
        self.source.write_text("new app")
        self.assertEqual(self.event("Stop", permission_mode="plan"), {})
