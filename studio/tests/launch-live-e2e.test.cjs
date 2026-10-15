// Regressions from the first recorded live e2e run (staging 0ea7f38).
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const read = (file) => fs.readFileSync(path.join(__dirname, "..", file), "utf8");

test("live priced cards show Not now whenever a decline action is wired (finding 4)", () => {
  const card = read("components/rh/ApprovalCard.tsx");
  assert.match(card, /\{actions\.onNotNow \|\| model\.pricing/);
  assert.match(read("components/canvas/AgentDock.tsx"), /onNotNow: \(\) => onDecision\(approval, "reject", undefined, "not_now"\)/);
});

test("no fee line: orchestration is described as work and carries no est./fee suffix (finding 3)", () => {
  for (const file of ["lib/rh/approval-model.ts", "components/rh/Ledger.tsx", "lib/rh/billing.ts", "lib/rh/fixtures.ts"]) {
    const src = read(file);
    assert.ok(!/Agent orchestration/.test(src), `${file} still says Agent orchestration`);
    assert.ok(!/· est\.`/.test(src), `${file} still appends est. to a line`);
    if (file !== "lib/rh/billing.ts") assert.ok(!/platform fee|service fee|markup/i.test(src), `${file} mentions a fee`); // billing.ts holds the client guard regex
  }
  assert.match(read("../server/run_budget.py"), /ORCHESTRATION_LABEL = "Planning and checks"/);
});

test("approve accessible name starts with the visible label (finding 8)", () => {
  const billing = read("lib/rh/billing.ts");
  assert.match(billing, /`Approve and run, up to /);
  assert.match(billing, /`Approve and run, estimated /);
  assert.ok(!/`Approve, (estimated|up to)/.test(billing));
  assert.match(read("components/rh/ApprovalCard.tsx"), /"Approve and run, locked while this step is priced"/);
});

test("an undelivered film never reads Delivered (finding 5)", () => {
  const dock = read("components/canvas/AgentDock.tsx");
  assert.match(dock, /execution\.errorType === "DeliverableIncomplete" \? "incomplete"/);
  assert.match(dock, /Incomplete · not delivered/);
});

test("layout: chat column clamps 360-440px, stage is 16:9, strip slim, body text >= 14px", () => {
  const css = read("app/revamp-v4.css");
  assert.match(css, /--rh-chat-w: clamp\(360px, 28vw, 440px\)/);
  assert.match(css, /\.rh-stage-frame \{[^}]*aspect-ratio: 16 \/ 9/);
  assert.match(css, /\.rh-strip \{[^}]*height: 52px/);
  assert.match(css, /\.rh-agent-conversation \{ font-size: 14px; \}/);
});
