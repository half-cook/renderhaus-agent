# Closed-beta free credits

The beta programme grants one verified account $10 by default. It uses the existing
Studio wallet and never sends email or SMS in this implementation. Fresh deployments
grant nothing. Both the feature flag and admission limits must be opened by an operator.

## Configuration

`server/config.py` supplies these defaults. `BetaSettings.from_env()` validates them at
app startup and at the feature boundary. Empty values, negative values, fractional cents,
unknown booleans, and integers above SQLite's signed 64-bit limit raise `ValueError`.
Boolean settings accept `true`, `false`, `1`, and `0`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BETA_CREDITS_ENABLED` | `false` | Allows verification, claims, waitlist admission, and wave advancement. A disabled programme cannot grant credit, including on a retry. |
| `BETA_GRANT_CENTS` | `1000` | Positive integer USD cents per new grant. Existing grants keep their original amount. |
| `BETA_GLOBAL_CAP_CENTS` | `0` | Lifetime commitment ceiling. Zero closes grants. Allocations remain committed after spending or refunds. |
| `BETA_WAVE_SIZE` | `0` | Maximum accounts admitted per wave. Zero closes the wave. |
| `BETA_WAVE_INDEX` | `1` | Initial wave for a new database. Once created, the database owns the current wave. Changing this variable cannot reset admission counts. |
| `BETA_DAILY_GRANT_LIMIT` | `0` | Maximum new grants per UTC day. Zero disables this additional limit. |
| `BETA_VERIFICATION_DRY_RUN` | `true` | Selects deterministic mocked verification. False refuses verification and new grants unless a real provider has been registered. |
| `BETA_IDENTITY_SALT` | unset | Secret used for HMAC-SHA256 identity hashes. Required for an enabled programme outside dry run. |
| `BETA_ADMIN_TOKEN` | unset | Secret compared against `X-Beta-Admin-Token` in constant time. Unset disables the admin action. |

There are no new provider keys. `scripts/sync_secrets.py` already syncs arbitrary nonempty
application settings and secrets without printing their values. Its documentation now
includes the beta settings. No secret is generated or synced by this branch.

Dry run without a salt uses a fixed development salt. Use an operator-managed secret
even for a persistent test programme. The database stores a salt fingerprint and refuses
identity writes after the salt changes. Rotate the salt only with a reviewed identity
migration. Never clear identities to reopen admission. Do not lower the cap below existing
commitments; doing so closes grants but cannot revoke previously allocated credit.

## Verification and claim flow

1. Sign in through Clerk. Beta routes require a real authenticated subject. The Studio's
   local-user fallback cannot claim credit.
2. Open **Credits** on `/home`. Studio shows the public counter and admission message.
3. Start email verification, then confirm with the token. In dry run, use `beta-email-ok`.
4. Start phone verification, then confirm with the code. In dry run, use `424242`.
5. Select **Claim free credit**. Both verified identities are required. Email-only and
   phone-only grants are never allowed.

Mocked start responses state that no message was sent and display the deterministic code.
These codes prove the test flow, not control of a real mailbox or phone. Keep an enabled
mock programme isolated from paid production dispatch. All provider dry-run flags remain
enabled for this task. Turning beta verification dry run off does not enable any vendor.

Pending challenges expire after ten minutes. They belong to one account and one identity
kind. Starting a replacement challenge resets verification for that kind. Confirmation
returns the salted identity hash through the provider interface, while the HTTP response
exposes only success and a message. Confirmed identities remain verified until replaced.
Claims must match the current provider's dry-run mode; mocked proofs cannot become live
proofs after a configuration change.

Email normalization trims whitespace, lowercases the address, and removes the plus-tag
from the local part on every domain. For `gmail.com` and `googlemail.com`, it also removes
local-part dots and maps the domain to `gmail.com`. Dots on other domains stay significant.
For example, `First.Last+tag@googlemail.com` and `firstlast@gmail.com` share one identity.
This policy deliberately treats case and plus variants as one account even where a mail
host may support distinct mailboxes.

Phones require an explicit country code. Spaces, parentheses, and hyphens are removed,
then the result must match E.164 syntax, a leading `+` and 7 to 15 digits with a nonzero
first digit. This validates format only; the future provider must establish reachability
and possession. The application stores only salted hashes of normalized email and phone.

## API reference

| Method and route | Body or credential | Result |
| --- | --- | --- |
| `GET /api/beta/status` | Public | `enabled`, `wave`, `wave_size`, `spots_left`, `programme_full`, `message`. No identifiers. |
| `POST /api/beta/verify/email/start` | Authenticated, `{email}` | `challenge_id`, `dry_run`, `message`. |
| `POST /api/beta/verify/email/confirm` | Authenticated, `{challenge_id, token}` | `verified`, `message`. |
| `POST /api/beta/verify/phone/start` | Authenticated, `{phone}` | `challenge_id`, `dry_run`, `message`. |
| `POST /api/beta/verify/phone/confirm` | Authenticated, `{challenge_id, code}` | `verified`, `message`. |
| `POST /api/beta/claim` | Authenticated, no body required | `balance_cents`, `grant` with `amount_cents` and `wave`, `message`. |
| `POST /api/beta/waitlist` | Authenticated, `{email}` | Generic recorded message. No email is sent. Available only while a wave is full and programme capacity remains. |
| `POST /api/admin/beta/next-wave` | `X-Beta-Admin-Token` | Updated public status. Missing configuration returns 503; a missing or wrong credential returns 403. |

Public status messages are exact:

| Admission state | Message |
| --- | --- |
| Open | `N spots left in this wave` |
| Wave full | `This wave is full. Join the waitlist for the next one.` |
| Programme full | `The free beta credit is fully allocated.` |
| Disabled | `Free beta credits are disabled.` |

`spots_left` is the smaller of remaining wave admissions and whole grants supported by
the remaining cap. Less than one grant of capacity makes the programme full. The daily
limit is an additional claim gate and returns
`Today's beta grant limit has been reached. Try again tomorrow.`

Verification starts and confirmations share SQLite counters. Each account has ten attempts
per fixed 15-minute UTC window across both kinds. Each normalized identity has five attempts
in that window across accounts. Waitlist writes use the same counters. A rate-limited
request returns HTTP 429. Counters survive app restarts and work across app processes.

Identity reuse and missing verification both return `Not eligible for free beta credit.`
The response never names which identity was used by another account. Grant and policy-denial
audit rows contain only salted account/identity hash prefixes, an outcome, a reason, and
a timestamp. Identity reuse has a separate server-side reason for investigation.

## Allocation, spending, and refunds

One `BEGIN IMMEDIATE` transaction checks the cap and current wave, checks both unique
identity constraints, inserts `beta_grants`, credits the wallet, records `beta_grant` in
`credit_ledger`, and writes the grant audit row. It commits everything or nothing. The email
and phone hashes each have their own unique constraint, independently of account id.
The account id is unique too, so a retry returns its existing grant and current balance.

Programme commitments come from `SUM(beta_grants.amount_cents)`. Wave admissions come
from the grant rows for the stored wave. These totals cannot drift from separate mutable
counters. Schema migrations also acquire a database write transaction before inspecting
or adding columns, protecting concurrent API and agent startup.

`accounts.balance_cents` remains the total wallet value. `beta_grants.remaining_cents`
identifies the free portion; purchased credit equals wallet value minus that portion.
Charges use the subscription daily allowance first, then free beta credit, then purchased
credit. `spent_cents` is net free spend, and `gross_spent_cents` includes charges later
refunded. A refunded failure restores free credit; it never reopens programme capacity.
Net free spend cannot exceed the grant. Every wallet delta has a matching ledger row.

`UsageCharge.beta_cents` is included in `wallet_cents`. Each new charge has a durable
`charge_id`, recorded date, and funding split in `usage_events`. Refunds validate that
record and atomically mark it refunded once. They restore the original free portion to
the grant and the original paid portion to purchased value. Replays cannot create extra
value. Pending refunds keep the same provenance for recovery after a database failure.
Previously recorded legacy pending refunds remain recoverable. New refunds for beta
accounts require the original charge id.

Wallet enforcement applies when Stripe is configured, beta is enabled, or the account
has an existing grant. Closing admissions cannot make already allocated credit spendable
without debiting it. Studio invoke, Gateway dispatch, and direct local ad-variant dispatch
use the wallet. Existing approval exemptions, cost disclosures, and autonomous spend caps
are unchanged. Failed, blocked, and not-run dispatch results refund their original funding
split. Structured render failures retain partial outputs and manifest details for recovery.
Actual provider dry-run costs remain zero, including Remotion ad variants; tests inject
positive costs and mocked dispatch to exercise accounting without a provider call.

The credits page and canvas billing popover show remaining free credit. An exhausted grant
with an empty wallet shows `Your free beta credit is used up. Top up to keep creating.`
An ordinary empty wallet shows `Your wallet is empty. Top up to keep creating.` An active
daily plan allowance suppresses out-of-credit guidance while credit remains available.

## Open a wave and set its cap

1. Keep `BETA_CREDITS_ENABLED=false` while configuring admission. Set a positive grant
   amount, cap, and wave size. For example, ten $10 grants require a cap of `10000` cents
   and a wave size of `10`.
2. Supply a stable `BETA_IDENTITY_SALT` and, to use the admin action, `BETA_ADMIN_TOKEN`
   through the existing environment or Secrets Manager path. Keep values out of logs and git.
3. For this mocked branch, keep `BETA_VERIFICATION_DRY_RUN=true` and all media providers
   in dry run. A production programme must register a real verifier and set verification
   dry run false before accepting real identity proofs.
4. Restart the backend with `BETA_CREDITS_ENABLED=true`. Check `GET /api/beta/status`.
5. To admit another wave, call `POST /api/admin/beta/next-wave` with the admin header using
   your approved credential tooling. Advancement increments the durable wave atomically;
   it never clears grants or resets the lifetime cap. Repeated actions open repeated waves.
6. Check status again. Increasing the wave number cannot reopen an exhausted cap. Increase
   the operator-configured cap and restart only when additional allocation is authorized.
7. To close new grants, set the feature flag false and restart. Existing balances and
   their charge/refund provenance remain available.

Useful read-only reconciliation queries for the Studio SQLite database are:

```sql
SELECT SUM(amount_cents) AS committed_cents, SUM(spent_cents) AS net_spent_cents,
       SUM(gross_spent_cents) AS gross_spent_cents FROM beta_grants;
SELECT wave, COUNT(*) AS admitted FROM beta_grants GROUP BY wave;
SELECT a.user_id FROM accounts a LEFT JOIN credit_ledger l ON l.user_id = a.user_id
GROUP BY a.user_id HAVING a.balance_cents != COALESCE(SUM(l.delta), 0);
```

The last query must return no rows. Treat programme identities and the account database
as private operational state. Do not export them into public status or UI analytics.

## Register a real verification provider

`VerificationProvider` defines `start_email(email)`, `confirm_email(token)`,
`start_phone(phone)`, and `confirm_phone(code)`, plus its `dry_run` property. Starts return
a `VerificationChallenge` with the normalized salted `identifier_hash` and an opaque
`reference`. Confirmations receive `reference:proof` and return the verified identifier
hash. The adapter must use the programme's normalization and salt, return `dry_run=False`,
and keep raw addresses and phone numbers out of persistent state, logs, errors, and references.

Register the adapter by supplying it to `BetaCredits(repository, settings, provider=adapter)`
through the FastAPI `get_beta_credits` dependency at trusted app startup. The default
dependency intentionally registers no live verifier. A verifier must establish control
of both channels, enforce expiry and replay protections, and fail closed on vendor errors.
Do not accept client-supplied verified flags, email-only grants, or phone-only grants.

TODO before real verification:

- Select and verify a vendor's API, pricing, terms, delivery behavior, and US availability.
- Reject or review disposable email domains and VoIP/temporary phone numbers. Format
  normalization alone does not address those abuse risks.
- Define identity-hash retention, deletion, salt rotation, and incident procedures without
  allowing deleted identities to regain a second grant.
- Add edge-level throttling for malformed and unauthenticated traffic and monitor audit denials.
- Validate Clerk sign-in, claim, exhaustion, refund recovery, and waitlist flows in Comet.

## Validation and unchanged inventory

Automated tests use temporary SQLite databases, fake authenticated subjects, mocked costs,
and mocked provider transport. They cover identity reuse, one-channel denial, cap/wave
boundaries, rate limits, concurrency, migration, ledger consistency, spend, and refunds.
Studio node tests drive the verification/claim component and exact public messages.
The final offline checks passed on 2026-10-09:

- Python unittest discovery ran 1,745 tests with 47 skipped, including 46 new beta tests.
- Studio node tests passed all 39 cases, including 15 beta cases.
- Ruff, `scripts/ci_check.py`, and the Studio TypeScript check passed.
- CI used a local wheelhouse with `PIP_NO_INDEX=1`; provider transports were mocked or
  dry run. The temporary Studio `node_modules` symlink was removed after typechecking.

Browser E2E is blocked in this environment because Comet is unavailable. The blocked report
is recorded under ignored `.renderhaus/e2e/`; automated checks do not substitute for it.

No models, Gateway tools, provider contracts, licences, prices, or training eligibility
decisions change here. There is no verification vendor price to cite. Pricing and licence
verification are TODO for a future real adapter. Inventory remains 16 providers, 115 tools,
and 25 agent skills, with 173 active and 45 skipped routing fixture rows.

No routing rows are activated by this branch. Existing skips remain:

| Rows | Reason |
| --- | --- |
| 29 | Delivery, loudness, and deliverable QC are pending `feat/remotion-delivery-qc`. |
| 10 | Subject-aware aspect layouts are pending `feat/remotion-aspect-ratio-variants`. |
| 3 | `cutaway_record` is pending `feat/product-demo-capture`. |
| 2 | LUT and multicam semantics remain unverified outside the ad-matrix branch. |
| 1 | HyperFrames overlays are pending `feat/hyperframes-overlays`. |

The scoped Deep Agents audit and implementation decisions are recorded in
[beta-credits-decisions.tsv](beta-credits-decisions.tsv). Installed `deepagents==0.7.23`
signatures were inspected locally. The native graph, role tools, skills, planning,
checkpointing, middleware, streaming, and cost-bearing interrupts stay in place. The
wallet boundary changes their debit/refund enforcement. Independent native review found
the billing bypass and returned-result refund cases; external model review was skipped
to honor the offline requirement.
