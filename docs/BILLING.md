# Credit balances and spending

Credit comes from beta grants and operator adjustments. The wallet is the only
spendable balance. Paid operations retain estimates, exact approvals, run holds,
spending caps, durable usage records and idempotent refunds. No checkout, subscription
or payment portal is exposed. Legacy refund records are retained for recoverability.

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
that media billing applies to (a beta account, invite-only account, or prepaid wallet).

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

All amounts are integer cents and already fee-inclusive. Clients render them and never recompute. Not present in
billing data: fee amounts or percentages, `fee`/`markup`/`platform` wording, provider, vendor or model names,
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
 "lower_cap_option_cents": null, "shortfall_cents": 200, "minimum_needed_cents": 108}
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

`raise_options_cents` are new **totals** the user can afford (empty when none fit).

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
