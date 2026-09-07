from __future__ import annotations

import unittest

from server.billing import SubscriptionPlan, _monthly_budget_cents


class MonthlyBudgetCentsTests(unittest.TestCase):
    def test_uses_snapshotted_price_when_present(self) -> None:
        plan = SubscriptionPlan(id="basic", label="Basic", price_usd_cents=2000)

        # The plan's *current* price (9999) must not win over the snapshot
        # -- that's the whole point of snapshotting it at checkout time.
        stale_plan = SubscriptionPlan(id="basic", label="Basic", price_usd_cents=9999)
        self.assertEqual(_monthly_budget_cents({"price_usd_cents": "2000"}, stale_plan), 2000)
        self.assertEqual(_monthly_budget_cents({"price_usd_cents": "2000"}, plan), 2000)

    def test_falls_back_to_plan_price_when_snapshot_missing(self) -> None:
        plan = SubscriptionPlan(id="basic", label="Basic", price_usd_cents=2000)
        self.assertEqual(_monthly_budget_cents({}, plan), 2000)

    def test_falls_back_to_plan_price_when_snapshot_malformed(self) -> None:
        plan = SubscriptionPlan(id="basic", label="Basic", price_usd_cents=2000)
        self.assertEqual(_monthly_budget_cents({"price_usd_cents": "not-a-number"}, plan), 2000)
        self.assertEqual(_monthly_budget_cents({"price_usd_cents": None}, plan), 2000)

    def test_falls_back_to_zero_when_snapshot_missing_and_plan_unknown(self) -> None:
        # An unknown/removed plan_id with no snapshot -- degrades to 0
        # budget rather than raising and 500ing the whole webhook delivery.
        self.assertEqual(_monthly_budget_cents({}, None), 0)


if __name__ == "__main__":
    unittest.main()
