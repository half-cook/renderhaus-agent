"""A waiting run (approval card / cap pause) parks its hold; Approve re-holds atomically."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from server import run_billing, run_budget as rb
from server.studio_state import StudioRepository

USER = "user:parked"


class ParkedHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name)
        self.repo = StudioRepository(path / "state.sqlite3", path / "media")
        self.repo.adjust_balance(USER, 500, "test_credit")

    def test_waiting_card_releases_its_cap_until_approve(self):
        self.repo.hold_run(USER, "run-a", 300)
        self.assertEqual(self.repo.available_credit(USER), 200)
        self.assertIsNone(run_billing.end_run(self.repo, "run-a", execution_status="awaiting_approval"))
        hold = self.repo.get_run_hold("run-a")
        self.assertEqual(hold["state"], "held")
        self.assertEqual(hold["held_cents"], hold["charged_cents"])
        self.assertEqual(self.repo.available_credit(USER), 500)
        self.repo.hold_run(USER, "run-a", 300)  # Approve re-holds
        self.assertEqual(self.repo.available_credit(USER), 200)

    def test_two_concurrent_approvals_cannot_hold_past_available_credit(self):
        for run in ("run-a", "run-b"):
            self.repo.hold_run(USER, run, 300)
            run_billing.end_run(self.repo, run, execution_status="awaiting_approval")
        self.assertEqual(self.repo.available_credit(USER), 500)
        barrier = threading.Barrier(2)
        results: dict[str, str] = {}

        def approve(run: str) -> None:
            barrier.wait()
            try:
                self.repo.hold_run(USER, run, 300)
                results[run] = "held"
            except rb.InsufficientCreditError:
                results[run] = "insufficient"

        for _ in range(5):
            threads = [threading.Thread(target=approve, args=(run,)) for run in ("run-a", "run-b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(sorted(results.values()), ["held", "insufficient"])
            held = sum(self.repo.get_run_hold(r)["held_cents"] - self.repo.get_run_hold(r)["charged_cents"]
                       for r in ("run-a", "run-b"))
            self.assertLessEqual(held, 500)
            self.assertGreaterEqual(self.repo.available_credit(USER), 0)
            for run in ("run-a", "run-b"):
                run_billing.end_run(self.repo, run, execution_status="awaiting_approval")
            barrier.reset()
            results.clear()
