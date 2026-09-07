# Payment infrastructure

Two pricing models sit side by side on one ledger: pay-as-you-go top-ups (a wallet, `accounts.balance_cents`)
and a recurring subscription (a daily allowance, `subscriptions`). Every generation call is priced in real
dollar cents by `server/billing_rates.py::cost_for` and debited by `server/studio_state.py::charge_usage`,
which draws from the subscriber's daily allowance first and only touches the wallet for the remainder —
there is no separate "credits" unit to reconcile against real cost.

```text
                                cost_for(provider, tool, args)
                                            |
                                            v
                                    charge_usage(user_id, cost_cents)
                                            |
                       +--------------------+--------------------+
                       |                                         |
              active subscription?                        no / past_due
                       |                                         |
                       v                                         v
        drain today's daily_allowance first          cost_cents comes entirely
        (CAS against subscriptions row),              from the wallet -- byte-for-
        remainder (if any) falls through               byte today's pre-subscription
        to the wallet leg below                         behavior
                       |                                         |
                       +--------------------+--------------------+
                                            |
                                            v
                          UPDATE accounts.balance_cents (atomic,
                          never lets balance go negative)
                                            |
                                            v
              credit_ledger row (wallet spend) + usage_events row (full split)
```

## Data model

- **`accounts`** — one row per user. `balance_cents` is the top-up wallet; `stripe_customer_id` links
  to Stripe (populated from whichever billing event reaches it first, top-up or subscription).
- **`credit_ledger`** — every change to `balance_cents`: top-up purchases (positive), generation spend
  (negative), refunds (positive). `reference_id` carries a unique index (`credit_ledger_reference_unique`,
  NULL-safe) so a redelivered Stripe webhook event can't double-credit a purchase.
- **`subscriptions`** — one row per user with a plan. `monthly_budget_cents` is the price paid, stored
  redundantly so re-pricing a plan later doesn't change what an existing subscriber already committed to.
  `daily_allowance_cents = monthly_budget_cents // 30`. `daily_allowance_used_cents` and
  `daily_allowance_reset_date` track today's spend; there is **no rollover** — an unused allowance is
  forfeited at the UTC day boundary, not carried forward (same shape as a rate-limit window, not a wallet).
- **`usage_events`** — an append-only log of every `charge_usage`/`refund_usage` call, recording the full
  daily/wallet split. Kept separate from `credit_ledger` because `credit_ledger.delta` is defined as "an
  actual `balance_cents` change" (that invariant backs its uniqueness index), and daily-allowance spend
  never touches `balance_cents`.
- **`pending_refunds`** — a refund obligation recorded *before* it's applied (see `refund_usage` below),
  so a failure partway through leaves a row `flush_pending_refunds` can find and finish later instead of
  the debit being silently lost.
- **`pending_subscription_checkouts`** — one in-flight claim per user, so two concurrent `/subscribe`
  calls can't both create a Stripe subscription before either one's webhook lands (see "Stripe
  integration" below).

## `charge_usage` / `refund_usage`

`repository.charge_usage(user_id, cost_cents, reason) -> UsageCharge(daily_cents, wallet_cents, charge_date)`
is the only way a generation gets billed. With no active subscription it degenerates to exactly the old
`adjust_balance(-cost_cents)` behavior — same `ValueError`, same ledger row — which is what makes this
change safe for every pre-existing top-up-only account.

With an active subscription, the daily leg is **not** a plain read-then-write: `server/studio.py`
(the FastAPI process) and `agent/studio_agent_next.py` (the separate AWS Bedrock AgentCore process) both
debit against the same SQLite file, so a concurrent charge from either process could otherwise double-spend
the same slice of allowance. `charge_usage` guards the daily update with a compare-and-swap —

```sql
UPDATE subscriptions SET daily_allowance_used_cents = ?, daily_allowance_reset_date = ?
WHERE user_id = ? AND daily_allowance_used_cents = ? AND daily_allowance_reset_date = ?
```

— and retries (bounded) on a lost race, the same pattern `save_canvas` already uses for its `revision`
column. The wallet leg reuses `adjust_balance`'s own atomic `UPDATE ... WHERE balance_cents + ? >= 0`, so
insufficient balance is a single-statement check, not a separate read.

If neither bucket can cover the cost, `InsufficientBalanceError` (a `ValueError` subclass, so existing
`except ValueError` call sites keep working unmodified) carries `daily_remaining_cents`/`wallet_cents` for
a richer 402 message. Nothing is written when this is raised.

`refund_usage` reverses a `UsageCharge` — the wallet portion via a plain `adjust_balance(+wallet_cents)`,
and the daily portion **only** if `daily_allowance_reset_date` still matches the charge's `charge_date`.
If the day has since rolled over, that bucket was already reset to zero; crediting into today's fresh
allowance would inflate it, so a stale refund is a deliberate silent no-op — the user already has a full
new day's allowance and isn't harmed by not also getting yesterday's leftover credited back.

**Refunds are durable, not best-effort.** `refund_usage` first calls `record_pending_refund` (a plain
`pending_refunds` insert) *before* attempting the actual reversal (`_apply_refund`). If `_apply_refund`
raises, the obligation stays in `pending_refunds` unresolved rather than being lost after a logged
exception. `flush_pending_refunds(user_id)` retries every unresolved obligation for that user and is
called opportunistically from both `get_balance` and `charge_usage`, so a refund that failed to apply
immediately gets a real chance to complete on the user's very next balance read or charge — no separate
reconciliation job needed. Both `server/studio.py::invoke_tool` (the manual `/invoke` path) and
`agent/studio_agent_next.py::GatewayMCPServer.call_tool` (the agent-dispatched path) debit *before*
dispatching to the provider and call `refund_usage` on any dispatch/registration failure; neither needed
to change to get this durability, since it lives inside `refund_usage` itself.

## Stripe integration (`server/billing.py`)

Both top-up packs (`TOP_UP_PACKS`) and subscription plans (`SUBSCRIPTION_PLANS`) are defined as code, not
Stripe dashboard objects — a Checkout Session is created with inline `price_data` (and, for subscriptions,
`recurring: {interval: "month"}`), so there's nothing to keep in sync between this file and Stripe's UI.

| Endpoint | Purpose |
|---|---|
| `GET /api/studio/billing/packs` | List top-up packs |
| `GET /api/studio/billing/plans` | List subscription plans |
| `POST /api/studio/billing/checkout` | Create a one-off Checkout Session (`mode="payment"`) |
| `POST /api/studio/billing/subscribe` | Create a subscription Checkout Session (`mode="subscription"`) |
| `POST /api/studio/billing/portal` | Create a Stripe Billing Portal session (self-serve cancel / payment method) |
| `POST /api/studio/billing/webhook` | Stripe webhook receiver |

Subscription metadata (`user_id`, `plan_id`, **`price_usd_cents`**) is set on `subscription_data.metadata`
at checkout time, not just the Checkout Session — so the `Subscription` object itself carries it, and
every later webhook event for that subscription is self-contained without a session lookup.
`price_usd_cents` is the actual snapshot backing `monthly_budget_cents`'s "stored redundantly" guarantee
above: the webhook reads the budget from this metadata, not by re-looking-up `plan_id` in the current
`SUBSCRIPTION_PLANS`, so repricing or removing a plan later can't retroactively change what an existing
subscriber's allowance is (a fallback to today's `SUBSCRIPTION_PLANS` value only covers subscriptions
created before this field existed).

**Duplicate-checkout guards.** `POST /subscribe` refuses to create a second subscription for a user who
already has one: `get_subscription_state(user_id)` blocks it outright if a subscription is already
active/past_due (409 — the Billing Portal is the way to change plans), and
`claim_pending_subscription_checkout(user_id)` closes the narrower race where two requests (double-click,
two tabs) both reach this endpoint before either one's webhook has landed (409, "checkout already in
progress"). The claim is released once a definitive webhook event lands for that user (inside
`sync_subscription`) or after 24h (a Checkout Session's own expiry), whichever comes first.

The webhook handles:

- `checkout.session.completed` / `checkout.session.async_payment_succeeded` (top-ups only —
  subscription-mode sessions carry no `amount_cents` and are skipped here) — credits the wallet once
  `payment_status == "paid"`, keyed on the Checkout Session id so both events for one payment collapse
  to a single credit.
- `customer.subscription.created` / `.updated` / `.deleted` — re-fetches the subscription live from
  Stripe (`stripe.Subscription.retrieve`) rather than trusting the event's own embedded payload, since
  Stripe does not guarantee webhook delivery order (and explicitly warns against inferring order from
  event timestamps); fetching live means two events for the *same* subscription arriving out of order
  both converge on Stripe's actual current state. `repository.sync_subscription` additionally refuses to
  apply an update whose subscription id doesn't match the user's current, still-live one — protecting
  against a delayed event for an already-superseded subscription (e.g. an old subscription's late
  `.deleted` arriving after a new one's `.created` already went active) from clobbering it. A plan change
  takes effect for future days only; there is no proration of the current day's already-spent allowance
  (an explicit v1 simplification). `.deleted` specifically marks the subscription `canceled` and zeroes
  `daily_allowance_cents`; `charge_usage` then falls back to wallet-only billing on the next call, with
  no special-casing needed.

All three flows populate `accounts.stripe_customer_id` opportunistically (from whichever event's
`customer` field arrives first), so top-ups and a subscription consolidate onto one Stripe Customer —
required for the Billing Portal to show a coherent history at all.

Every webhook branch that can fail (crediting a purchase, syncing a subscription) raises `HTTPException(500)`
rather than swallowing the error, so Stripe retries delivery instead of marking a lost credit "delivered."

## Where this shows up in the product

- `AccountBalance.tsx` (the header chip on `/canvas`) and the Credits card on `/home` both read
  `GET /api/studio/account`'s `subscription` field (`null` when there's no active plan) to show either
  "$X left today of $Y" + a link into the Billing Portal, or a plan picker.
- Checkout/portal redirects land back on `/canvas` (`?checkout=success|cancelled`) and `/home`
  respectively — see `_frontend_url()` in `server/billing.py`.
