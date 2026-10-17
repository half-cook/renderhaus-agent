const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-ts.cjs");
const { emptyWalletMessage } = load("lib/beta-credits.ts");

test("funded wallets have no empty-credit warning", () => {
  assert.equal(emptyWalletMessage({ balance_cents: 344 }), null);
});
test("empty wallets have no unavailable purchase or verification promise", () => {
  const message = emptyWalletMessage({ balance_cents: 0 });
  assert.equal(message, "You've used your beta credit.");
  assert.doesNotMatch(message, /top.?up|verify|coming soon/i);
});
