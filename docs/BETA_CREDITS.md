# Invite credits

Clerk authenticates the customer and confirms their email. The operator mints
single-use codes through `scripts/beta_invites.py`. `POST /api/beta/invite/check`
reserves a code; `POST /api/beta/invite/redeem` grants the configured credit only
after authentication and verified email. Redemption and the grant share one transaction.
Only code/identity hashes are stored. Retries cannot grant twice and the global cap applies.

The existing wallet, ledger, beta grant attribution, run holds, cost approval and
idempotent refunds remain authoritative. Closing beta admission does not erase balances.
No email/SMS demo verification, open-wave claim UI, waitlist or checkout is exposed.
Existing database records remain recoverable; the cleanup drops no user tables.

See [credit accounting](BILLING.md) and [browser verification](BROWSER_E2E.md).
