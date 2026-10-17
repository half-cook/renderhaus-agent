const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

test("landing and sign-up carry the invite-only copy and none of the open-wave copy", () => {
  const launch = read("lib/launch.ts");
  assert.match(launch, /Invite only · \$10 credit to start/);
  const landing = read("app/(marketing)/page.tsx");
  assert.match(landing, /Use your invite/);
  assert.match(landing, /\$10 credit · invite only/);
  assert.doesNotMatch(landing, /30%|[Pp]latform fee/);
  const signup = read("components/beta/InviteSignup.tsx");
  for (const source of [landing, signup]) {
    assert.doesNotMatch(source, /spots left|First 50|wave 1|Verify your phone|Claim your|platform fee/i);
  }
  assert.match(signup, /This code has already been used\. Each code works once\./);
  assert.match(signup, /We don’t recognise that code/);
});

test("the invite is burned only after the email code is confirmed", () => {
  const signup = read("components/beta/InviteSignup.tsx");
  const confirmAt = signup.indexOf("await auth.confirm(code)");
  const redeemAt = signup.indexOf("redeemInvite(invite)");
  assert.ok(confirmAt > 0 && redeemAt > confirmAt, "redeemInvite must run after auth.confirm");
  assert.doesNotMatch(signup.slice(0, confirmAt), /redeemInvite\(/);
});

test("credit UI exposes balances and no unavailable purchasing flow", () => {
  for (const file of ["lib/launch.ts", "components/canvas/AccountBalance.tsx", "components/rh/BetaCreditCard.tsx"]) {
    assert.doesNotMatch(read(file), /topupsEnabled|TOPUPS_COMING_SOON|createCheckout|createSubscription/);
  }
  assert.match(read("components/canvas/AccountBalance.tsx"), /Held for running steps/);
});

test("over-credit approval card keeps Approve disabled and offers only an option that fits", () => {
  const card = read("components/rh/ApprovalCard.tsx");
  assert.match(card, /Approve is off because this step.s hard cap is more than your credit\./);
  assert.match(card, /cheaperOption\.capCents <= balance/);
  assert.match(card, /<Lock[^/]*\/>Approve/);
  assert.match(card, />Use this/);
  assert.match(card, />Edit</);
  assert.match(card, />Not now</);
  assert.doesNotMatch(card.slice(card.indexOf("function OverCredit")), /Reject/);
  // Locked Approve never prints a price on the button.
  assert.doesNotMatch(card.slice(card.indexOf("function OverCredit")), /Approve · est\./);
  assert.match(card, />Trim</);
  assert.match(card, />Keep as is</);
});
