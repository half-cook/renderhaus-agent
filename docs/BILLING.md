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
`pending_refunds` insert, its own committed transaction) *before* attempting the actual reversal via
`_claim_and_apply_pending_refund`. That method claims the row (`UPDATE pending_refunds SET resolved_at = ?
WHERE id = ? AND resolved_at IS NULL`) and calls `_apply_refund` — the wallet credit, the daily-allowance
credit, and their ledger/`usage_events` rows — **all on the same connection, one transaction**: either
everything commits together or an exception rolls back the claim along with both reversal legs, so a
crash or error partway through can never leave the claim resolved with only one leg applied, and a retry
of a genuinely-failed attempt can never double-credit a leg that already landed. `flush_pending_refunds
(user_id)` retries every still-unresolved obligation for that user and is called opportunistically from
both `get_balance` and `charge_usage`, so a refund that failed to apply immediately gets a real chance to
complete on the user's very next balance read or charge — no separate reconciliation job needed. The same
claim also protects against two processes flushing the same user concurrently (this app runs as two
separate OS processes — the FastAPI server and the AgentCore agent — sharing one SQLite file): only
whichever caller flips `resolved_at` from `NULL` first gets to apply that refund. Both
`server/studio.py::invoke_tool` (the manual `/invoke` path) and
`agent/studio_agent_next.py::GatewayMCPServer.call_tool` (the agent-dispatched path) debit *before*
dispatching to the provider and call `refund_usage` on any dispatch/registration failure; neither needed
to change to get any of this, since it all lives inside `refund_usage` itself.

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

## Orchestration billing, run holds and caps

The agent's own planning work is billed to the user's credit, on the same ledger and with the same markup as media.
Nothing in this section is shown to clients except the integer-cent, fee-inclusive amounts described under
"Client payloads".

### What is billed

- **Media steps** are charged at approval-time prices through `charge_usage` (`reason = 'generation'`), unchanged.
- **Agent orchestration** is metered per planner turn. `agent/deep_agent/usage.py::ModelUsage.record` returns each
  model call's USD cost (the same accounting `scripts/e2e_lighthouse.py` reports as `model_cost_usd`). The run keeps the
  cumulative model cost (`run_holds.model_usd`, backend-only) and bills `ceil(cumulative_usd * 100 * (1 + PLATFORM_FEE_RATE))`
  cents minus what was already billed, so rounding never compounds per turn. The fee rate is the single backend
  constant `server/billing_rates.py::PLATFORM_FEE_RATE`; there is no second orchestration rate. Each billed turn is one
  `usage_events` row with `reason = 'orchestration'` (and a `credit_ledger` row for the wallet leg) via the normal
  `charge_usage` path: daily allowance first, then wallet, never negative.
- Calls whose model has no price in `MODEL_RATES` (unknown model) are not billed (logged as `unknown_cost_calls`); add
  the model's official rates before enabling it.
- A planner turn that would exceed the cap is **clipped**: only the part up to the cap is charged and the run pauses.
  After the user raises the cap the unbilled part is caught up from the cumulative cost.

### Config (env; defaults in `server/config.py::DEFAULT_ENV`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `ORCHESTRATION_BILLING_ENABLED` | `true` | Master flag. `false`: planner turns are not charged and no orchestration line appears on cards/receipts (media billing, holds and caps still apply). |
| `ORCHESTRATION_ESTIMATE_CENTS` | `75` | Fee-inclusive orchestration estimate per run. Basis: observed planner model cost was $0.41-$0.69 on clean lighthouse runs (11-22 calls, `/workspace/rh-e2e/out-sonnet*`) and $0.98 on the retry-heavy P1 film; with markup that is about $0.55-$0.90, so 75 covers a typical clean run. Re-measure after prompt/model changes. |
| `ORCHESTRATION_CAP_FACTOR` | `1.4` | Default hard cap = estimate x factor ... |
| `ORCHESTRATION_CAP_ROUND_CENTS` | `25` | ... rounded **up** to the next multiple of this ($1.05 -> $1.47 -> $1.50). |
| `ORCHESTRATION_HARD_CAP_CENTS` | unset | Optional fixed cap override (never below the estimate). |
| `ORCHESTRATION_RAISE_STEP_CENTS` | `50` | Spacing of `raise_options_cents` (two options above the current cap). |
| `ORCHESTRATION_AUTONOMOUS_MEDIA_CENTS` | `300` | Media allowance added to an autonomous run's hold (no approval card sets its cap). `RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS`, when set, is used instead. Autonomous runs hard-stop at the resulting cap like any other. |
| `ORCHESTRATION_HOLD_TTL_SECONDS` | `21600` | A hold untouched for this long is released by the sweep (crashed runs). |

Invalid values raise `ValueError` loudly; nothing silently defaults to unlimited. Billing only applies to accounts
that media billing applies to (Stripe enabled, or a beta-credit account).

### Wallet holds (`run_holds`)

One row per agent run (the execution/job id): `held_cents` is the run's **hard cap**, `charged_cents` what has been debited.

- **Hold at start and at approval.** `run_billing.start_run` holds the default orchestration cap when the job starts
  (a run that cannot afford it is refused with `insufficient_credit`, HTTP 402 on `POST /api/studio/agent`). Approving a
  card holds the card's cap (`hold_run`, idempotent; raising a hold needs the extra to fit in available credit).
- **Available credit** = daily allowance remaining + wallet minus the unspent part (`held - charged`) of every other
  active hold. `charge_usage` honours holds: a charge without the run id cannot spend credit reserved by a run, and a
  charge with `run_id` can never take the run past its cap (`RunCapExceededError`). Two runs cannot hold the same credit
  and the wallet cannot go negative (tested with racing threads).
- **Release at run end** (`completed`, failed, stopped, cancelled): the unused part is released and the receipt is stored.
  A run paused for approval or paused at its cap keeps its hold. Stale holds are swept after the TTL.
- A refunded step is removed from the run (its line disappears, its cap is freed).
- A resumed job (new job id, same conversation) adopts the conversation's held run, so the cap and spend carry over.

### Hard stop

Before every paid step (gateway executor, plus `charge_media` as the transactional backstop) the run's spend plus the
step price must fit the cap; before and after every agent turn the remaining cap is checked. If not, nothing is
dispatched, the hold's status becomes `paused_cap`, the run ends with `error_type = "PausedAtCap"` and the client
receives a `paused_cap` payload. The user answers with `POST /api/studio/agent/{job_id}/cap`:
`{"action": "raise", "cap_cents": 200}` (new **total** cap, bounded by available credit, then the run resumes) or
`{"action": "stop"}` (releases the hold, returns the receipt, charges nothing more). Insufficient credit is reported
as an `insufficient_credit` payload (HTTP 402) and never charges.

### Client payloads

All amounts are integer cents and already fee-inclusive. Clients render them and never recompute. Not present anywhere
in a client payload: fee amounts or percentages, `fee`/`markup`/`platform` wording, provider, vendor or model names,
`approval.provider`, upstream model ids, the tool's machine name on approval cards. Error and status text is passed
through `run_budget.neutral_error` (replaced by a neutral sentence when it names a vendor/model or a fee).
`tests/test_run_billing.py` scans every payload and every gateway tool id's label for a deny-list.

**Approval card** (each item of `execution.approvals`; run-level numbers repeat on every card of the pause):

```json
{
  "call_id": "call_1", "label": "Video clip", "detail": "5 s · 720p", "status": "pending", "decision": null,
  "arguments": {"prompt": "...", "duration_seconds": 5, "resolution": "720p"},
  "step_price_cents": 65, "step_index": 2, "step_count": 4,
  "estimate_cents": 233, "cap_cents": 350, "held_cents": 125, "spent_so_far_cents": 0,
  "lines": [
    {"label": "Image", "price_cents": 26, "kind": "media", "basis": "fixed"},
    {"label": "Video clip", "detail": "5 s · 720p", "price_cents": 65, "kind": "media", "basis": "fixed"},
    {"label": "Voiceover", "price_cents": 2, "kind": "media", "basis": "fixed"},
    {"label": "Agent orchestration", "price_cents": 75, "kind": "orchestration", "basis": "estimate"}
  ],
  "balance_cents": 875, "balance_after_estimate_cents": 767, "balance_after_cap_cents": 650,
  "approve_enabled": true, "insufficient_credit": null, "raise_options_cents": [], "estimate_incomplete": false
}
```

`status`: `pending | approved | running | done | failed | paused_cap | rejected` (`rejected` is an addition for a card the
user rejected; rejected cards carry no cost fields). `estimate_cents` is the sum of `lines[].price_cents` (completed
steps of the same run are included as `fixed` lines; the orchestration line combines what was billed and what is still
expected). `balance_cents` is credit available beyond holds. `estimate_incomplete` is true when a step could not be
priced (it is shown at 0 and must not be treated as free). Approve with
`POST /api/studio/agent/{job_id}/approvals/{call_id}` body `{"decision": "approve", "cap_cents": 350}`; `cap_cents` is
optional (default = the card's cap), must be >= `estimate_cents`, and is held from the credit (a lower cap than the
default is how the user "lowers the cap").

**`insufficient_credit`** (nested in the card as `insufficient_credit`, and the HTTP 402 `detail` of approvals, raises and
run starts):

```json
{"type": "insufficient_credit", "reason": "insufficient_credit", "approve_enabled": false,
 "message": "Not enough credit for this cap.", "balance_cents": 150, "estimate_cents": 233, "cap_cents": 350,
 "lower_cap_option_cents": null, "add_credit": true, "shortfall_cents": 200, "minimum_needed_cents": 108}
```

`lower_cap_option_cents` is the cap the user can lower to (available credit) when it still covers the estimate, else
`null` (only "add credit").

**`paused_cap`** (`execution.paused_cap`; the execution is `status: "error"`, `error_type: "PausedAtCap"`):

```json
{"type": "paused_cap", "status": "paused_cap", "run_id": "job_1",
 "message": "Stopped at your cap. Nothing more has been charged, and the run is paused so you decide.",
 "charged_cents": 350, "cap_cents": 350, "held_cents": 350,
 "lines": [{"label": "Video clip", "detail": "5 s", "price_cents": 65, "kind": "media", "basis": "fixed"},
           {"label": "Agent orchestration", "price_cents": 285, "kind": "orchestration", "basis": "fixed"}],
 "raise_options_cents": [400, 450], "balance_cents": 650, "choices": ["raise_cap", "stop"], "add_credit": false}
```

`raise_options_cents` are new **totals** the user can afford (empty with `add_credit: true` when none).

**Receipt** (`execution.receipt` once the run has ended, `GET /api/studio/agent/{job_id}/receipt`, and the body of the
`stop` response; idempotent per run id; 404 until the run ends):

```json
{"type": "receipt", "run_id": "job_1", "status": "done",
 "lines": [{"label": "Image", "price_cents": 26, "kind": "media", "basis": "fixed"},
           {"label": "Video clip", "detail": "5 s", "price_cents": 65, "kind": "media", "basis": "fixed"},
           {"label": "Agent orchestration", "price_cents": 71, "kind": "orchestration", "basis": "fixed"}],
 "actual_cents": 162, "estimate_cents": 233, "cap_cents": 325, "under_estimate": true,
 "balance_before_cents": 1000, "balance_after_cents": 838}
```

`status` is `done` or `failed` (failed/stopped runs list only what was charged). Line prices are actuals; the total is
`actual_cents`.

### Also scrubbed for clients

`GET /api/studio/agent*`, the SSE snapshots and the approval/stop responses go through `run_billing.public_execution`:
tool-call `label` becomes the work label, `provider` is `null`, `summary`, run `message`, event text and result
`error/reason/message/note` strings are replaced by neutral text when they name a vendor/model or fee. The tool-call
`name` (machine id used by Studio canvas logic) is still present; clients must not display it.

### Not done / decisions

See `docs/orchestration-billing-decisions.tsv`.

### Studio export metadata

`GET /api/studio/projects/{project_id}/export` checks project ownership and currently returns
`{"state":"disconnected","format":"project_json","resolution":null,"size_bytes":null}`.
Rendering is not connected. The Studio can download the current editable canvas as JSON without
starting paid work. It does not describe that download as a rendered film.

The UI adapter accepts optional future `configure` metadata with `format`, `resolution`,
`size_bytes` and an `estimate` containing integer `estimate_cents`, `cap_cents` and `lines`.
It displays a render ledger only when both totals are present. A `done` response needs a
same-origin `download_path`. These future shapes are adapter fixtures; no render submission
endpoint or paid export approval is implemented.
