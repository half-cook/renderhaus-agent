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

    def test_pending_refund_apply_is_all_or_nothing_across_both_legs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.adjust_balance("user:1", 1000, "purchase")
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_1",
                plan_id="basic",
                status="active",
                monthly_budget_cents=1500,  # -> 50 cents/day
                current_period_end=None,
            )
            # A mixed charge: 50 cents from the daily allowance, 30 from
            # the wallet.
            charge = repository.charge_usage("user:1", 80, "generation")
            self.assertEqual((charge.daily_cents, charge.wallet_cents), (50, 30))
            self.assertEqual(repository.get_balance("user:1"), 970)

            def wallet_write_then_fail(connection, user_id, charge, reason, now):
                # Simulates the wallet leg succeeding and *then* the daily
                # leg raising, writing through the exact connection
                # _claim_and_apply_pending_refund opened -- if the two legs
                # weren't in one transaction, this wallet write would
                # survive the subsequent exception.
                connection.execute(
                    "UPDATE accounts SET balance_cents = balance_cents + ? WHERE user_id = ?",
                    (charge.wallet_cents, user_id),
                )
                raise RuntimeError("simulated failure on the daily leg")

            with patch.object(repository, "_apply_refund", side_effect=wallet_write_then_fail):
                repository.refund_usage("user:1", charge, "refund: dispatch failed")
                # Still inside the patch so this get_balance's own
                # opportunistic flush can't cleanly resolve it either --
                # the wallet write from the failed attempt must not have
                # survived the rollback (970, not 1000).
                self.assertEqual(repository.get_balance("user:1"), 970)

            # A clean retry (no simulated failure) applies both legs
            # together, exactly once.
            repository.charge_usage("user:1", 0, "generation")
            self.assertEqual(repository.get_balance("user:1"), 1000)
            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["daily_allowance_remaining_cents"], 50)

    def test_sync_subscription_ignores_stale_event_for_superseded_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_new",
                plan_id="basic",
                status="active",
                monthly_budget_cents=3000,
                current_period_end=None,
            )

            # A delayed event for the *old*, already-superseded subscription
            # arrives after the new one is already active -- must not
            # clobber it.
            applied = repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_old",
                plan_id="basic",
                status="canceled",
                monthly_budget_cents=0,
                current_period_end=None,
            )

            self.assertFalse(applied)
            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["status"], "active")

    def test_sync_subscription_allows_new_subscription_after_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_old",
                plan_id="basic",
                status="canceled",
                monthly_budget_cents=0,
                current_period_end=None,
            )

            applied = repository.sync_subscription(
                "user:1",
                stripe_subscription_id="sub_new",
                plan_id="pro",
                status="active",
                monthly_budget_cents=5000,
                current_period_end=None,
            )

            self.assertTrue(applied)
            state = repository.get_subscription_state("user:1")
            assert state is not None
            self.assertEqual(state["status"], "active")
            self.assertEqual(state["plan_id"], "pro")

    def test_claim_pending_subscription_checkout_blocks_concurrent_second_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)

            self.assertTrue(repository.claim_pending_subscription_checkout("user:1"))
            self.assertFalse(repository.claim_pending_subscription_checkout("user:1"))

    def test_claim_pending_subscription_checkout_stealable_after_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)

            self.assertTrue(repository.claim_pending_subscription_checkout("user:1"))
            # A negative ttl treats the existing claim as already expired --
            # standing in for real wall-clock time passing (this repository
            # only has 1-second timestamp resolution, so a ttl_seconds=0
            # claim made in the same second wouldn't reliably read as
            # stale). A genuinely abandoned checkout can be reclaimed
            # rather than blocking the user forever.
            self.assertTrue(repository.claim_pending_subscription_checkout("user:1", ttl_seconds=-1))

    def test_release_pending_subscription_checkout_unblocks_a_fresh_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            self.assertTrue(repository.claim_pending_subscription_checkout("user:1"))

            # Simulates the checkout attempt itself failing (e.g. Stripe's
            # Session.create call raised) after the claim was already
            # taken -- releasing it should let an immediate retry through,
            # rather than locking the user out for the full TTL over an
            # error that left no actual pending checkout.
            repository.release_pending_subscription_checkout("user:1")

            self.assertTrue(repository.claim_pending_subscription_checkout("user:1"))

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

    def test_separate_repositories_charge_shared_buckets_and_refuse_excess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repositories = [self._repository(directory) for _ in range(8)]
            repository = repositories[0]
            repository.adjust_balance("user:1", 100, "purchase")
            repository.sync_subscription(
                "user:1", stripe_subscription_id="sub_1", plan_id="basic", status="active",
                monthly_budget_cents=3000, current_period_end=None,
            )
            for worker in repositories:
                worker.init()

            def charge_one(index: int) -> UsageCharge | None:
                try:
                    return repositories[index % len(repositories)].charge_usage(
                        "user:1", 10, "generation",
                    )
                except InsufficientBalanceError:
                    return None

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(charge_one, range(32)))
            charges = [charge for charge in results if charge is not None]
            self.assertEqual(len(charges), 20)
            self.assertEqual(sum(charge.daily_cents for charge in charges), 100)
            self.assertEqual(sum(charge.wallet_cents for charge in charges), 100)
            self.assertEqual(repository.get_balance("user:1"), 0)
            self.assertEqual(repository.get_subscription_state("user:1")["daily_allowance_remaining_cents"], 0)
            with repository._connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0], 20)


if __name__ == "__main__":
    unittest.main()
