from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from server.studio_state import StudioRepository, UsageCharge


class ChargeUsageTests(unittest.TestCase):
    def _repository(self, directory: str) -> StudioRepository:
        return StudioRepository(Path(directory) / "studio.sqlite3", Path(directory) / "media")

    def test_no_subscription_degenerates_to_wallet_only_charge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 1000, "purchase")

            charge = repository.charge_usage("user:1", 300, "generation")

            self.assertEqual(charge, UsageCharge(daily_cents=0, wallet_cents=300, charge_date=charge.charge_date))
            self.assertEqual(repository.get_balance("user:1"), 700)
            ledger = repository.list_ledger("user:1")
            spend_entries = [row for row in ledger if row["reason"] == "generation"]
            self.assertEqual(len(spend_entries), 1)
            self.assertEqual(spend_entries[0]["delta"], -300)

    def test_no_subscription_insufficient_balance_raises_plain_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 100, "purchase")

            with self.assertRaises(ValueError):
                repository.charge_usage("user:1", 300, "generation")
            self.assertEqual(repository.get_balance("user:1"), 100)


    def test_refund_left_pending_when_apply_fails_is_flushed_by_a_later_charge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 1000, "purchase")
            charge = repository.charge_usage("user:1", 300, "generation")
            self.assertEqual(repository.get_balance("user:1"), 700)

            with patch.object(repository, "_apply_refund", side_effect=RuntimeError("db is busy")):
                repository.refund_usage("user:1", charge, "refund: dispatch failed")
                # The apply failed, but the obligation was recorded first --
                # the balance doesn't reflect the refund yet (and this
                # get_balance's own opportunistic flush can't resolve it
                # either, since _apply_refund is still mocked to fail here),
                # rather than the refund being silently lost.
                self.assertEqual(repository.get_balance("user:1"), 700)

            # Outside the patch, _apply_refund works again -- the next call
            # that flushes (get_balance here) completes the still-pending
            # refund with no separate reconciliation job needed.
            self.assertEqual(repository.get_balance("user:1"), 1000)

    def test_concurrent_flush_applies_one_pending_refund_at_most_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 1000, "purchase")
            charge = repository.charge_usage("user:1", 300, "generation")
            with patch.object(repository, "_apply_refund", side_effect=RuntimeError("db is busy")):
                repository.refund_usage("user:1", charge, "refund: dispatch failed")
            # Exactly one unresolved pending_refunds row exists for user:1 now.

            # This app runs as two separate OS processes (the FastAPI server
            # and the AgentCore agent) sharing one SQLite file, so two
            # flushes for the same user can genuinely race -- without the
            # atomic claim in _claim_and_apply_pending_refund, each of these
            # would independently apply the same $3.00 refund.
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: repository.flush_pending_refunds("user:1"), range(8)))

            # 700 + one 300-cent refund = 1000, not 700 + 8*300.
            self.assertEqual(repository.get_balance("user:1"), 1000)


if __name__ == "__main__":
    unittest.main()
