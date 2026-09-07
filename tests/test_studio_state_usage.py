from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from server.studio_state import InsufficientBalanceError, StudioRepository, UsageCharge


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

    def test_cost_fully_covered_by_daily_allowance_leaves_wallet_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 1000, "purchase")
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_1",
                plan_id="basic",
                status="active",
                monthly_budget_cents=3000,  # -> 100 cents/day
                current_period_end=None,
            )

            charge = repository.charge_usage("user:1", 60, "generation")

            self.assertEqual(charge.daily_cents, 60)
            self.assertEqual(charge.wallet_cents, 0)
            self.assertEqual(repository.get_balance("user:1"), 1000)
            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["daily_allowance_remaining_cents"], 40)

    def test_cost_overflows_into_wallet_when_daily_allowance_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 1000, "purchase")
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_1",
                plan_id="basic",
                status="active",
                monthly_budget_cents=3000,  # -> 100 cents/day
                current_period_end=None,
            )

            charge = repository.charge_usage("user:1", 150, "generation")

            self.assertEqual(charge.daily_cents, 100)
            self.assertEqual(charge.wallet_cents, 50)
            self.assertEqual(repository.get_balance("user:1"), 950)
            ledger = repository.list_ledger("user:1")
            spend_entries = [row for row in ledger if row["reason"] == "generation"]
            self.assertEqual(len(spend_entries), 1)
            self.assertEqual(spend_entries[0]["delta"], -50)
            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["daily_allowance_remaining_cents"], 0)

    def test_both_buckets_insufficient_raises_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 20, "purchase")
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_1",
                plan_id="basic",
                status="active",
                monthly_budget_cents=3000,  # -> 100 cents/day
                current_period_end=None,
            )

            with self.assertRaises(InsufficientBalanceError) as ctx:
                repository.charge_usage("user:1", 500, "generation")
            self.assertEqual(ctx.exception.daily_remaining_cents, 100)
            self.assertEqual(ctx.exception.wallet_cents, 20)
            self.assertEqual(repository.get_balance("user:1"), 20)
            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["daily_allowance_remaining_cents"], 100)

    def test_lazy_reset_across_a_day_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_1",
                plan_id="basic",
                status="active",
                monthly_budget_cents=3000,  # -> 100 cents/day
                current_period_end=None,
            )
            repository.charge_usage("user:1", 100, "generation")
            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["daily_allowance_remaining_cents"], 0)

            with patch("server.studio_state._today_utc", return_value="2999-01-01"):
                state = repository.get_subscription_state("user:1")
                assert state is not None
                self.assertEqual(state["daily_allowance_remaining_cents"], 100)

                charge = repository.charge_usage("user:1", 40, "generation")
                self.assertEqual(charge.daily_cents, 40)
                self.assertEqual(charge.charge_date, "2999-01-01")

    def test_refund_restores_daily_bucket_when_same_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_1",
                plan_id="basic",
                status="active",
                monthly_budget_cents=3000,
                current_period_end=None,
            )
            charge = repository.charge_usage("user:1", 60, "generation")

            repository.refund_usage("user:1", charge, "refund: dispatch failed")

            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["daily_allowance_remaining_cents"], 100)

    def test_refund_is_a_no_op_on_daily_side_after_day_rolls_over(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 1000, "purchase")
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_1",
                plan_id="basic",
                status="active",
                monthly_budget_cents=3000,
                current_period_end=None,
            )
            charge = repository.charge_usage("user:1", 60, "generation")

            with patch("server.studio_state._today_utc", return_value="2999-01-01"):
                # A fresh day's charge first, so today's bucket is genuinely
                # in use before the stale refund arrives.
                repository.charge_usage("user:1", 30, "generation")
                repository.refund_usage("user:1", charge, "refund: dispatch failed")
                state = repository.get_subscription_state("user:1")
                assert state is not None
                # Unaffected by the stale refund -- still exactly today's
                # own 30-cent charge, not credited an extra 60.
                self.assertEqual(state["daily_allowance_remaining_cents"], 70)

    def test_concurrent_charges_never_overspend_the_daily_allowance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 100_000, "purchase")
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_1",
                plan_id="basic",
                status="active",
                monthly_budget_cents=3000,  # -> 100 cents/day
                current_period_end=None,
            )

            def charge_one(_: int) -> UsageCharge:
                return repository.charge_usage("user:1", 10, "generation")

            with ThreadPoolExecutor(max_workers=8) as pool:
                charges = list(pool.map(charge_one, range(20)))

            total_daily = sum(charge.daily_cents for charge in charges)
            total_wallet = sum(charge.wallet_cents for charge in charges)
            self.assertEqual(total_daily + total_wallet, 200)
            # 10-cent charges against a 100-cent daily cap divide evenly --
            # the allowance must land at exactly 100, never over or under,
            # regardless of how the 20 charges interleaved across threads.
            self.assertEqual(total_daily, 100)
            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["daily_allowance_remaining_cents"], 0)
            self.assertEqual(repository.get_balance("user:1"), 100_000 - total_wallet)


if __name__ == "__main__":
    unittest.main()
