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
  assert.match(landing, /Enter invite code/);
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

test("top-up UI is gated by the build flag and replaced by neutral copy", () => {
  assert.match(read("lib/launch.ts"), /NEXT_PUBLIC_TOPUPS_ENABLED === "true"/);
  const balance = read("components/canvas/AccountBalance.tsx");
  assert.match(balance, /topupsEnabled\(\) \?/);
  assert.match(balance, /TOPUPS_COMING_SOON/);
  const card = read("components/rh/BetaCreditCard.tsx");
  assert.match(card, /low && topupsEnabled\(\)/);
  assert.match(card, />Invite</);
});

test("over-credit approval card keeps Approve disabled and offers only an option that fits", () => {
  const card = read("components/rh/ApprovalCard.tsx");
  assert.match(card, /Approve stays off while the hard cap is more than your credit\. Top-ups are coming soon\./);
  assert.match(card, /cheaperOption\.capCents <= balance/);
  assert.match(card, /aria-disabled="true"[^>]*disabled>\s*<Lock/);
  assert.match(card, />Trim</);
  assert.match(card, />Keep as is</);
});
