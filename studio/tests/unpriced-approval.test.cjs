const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");

test("old square Tool approval / Estimate unavailable card is gone", () => {
  const dock = read("components/canvas/AgentDock.tsx");
  for (const dead of ["Tool approval", "Estimate unavailable", "agent-approval-reject", "agent-approval-approve", "needs a server estimate"]) {
    assert.ok(!dock.includes(dead), dead);
  }
  assert.ok(!read("app/globals.css").includes(".agent-approval-approve"));
  assert.match(dock, /pricingCardModel\(approval\)/);
});

test("pricing state shows a shimmer total and locks Approve", () => {
  const card = read("components/rh/ApprovalCard.tsx");
  assert.match(card, /Pricing this step…/);
  assert.match(card, /rh-shimmer/);
  assert.match(card, /model\.pricing === true \|\| model\.unpriceable === true/);
  assert.match(read("lib/rh/approval-model.ts"), /model\.pricing = true;\s*model\.approveEnabled = false;/);
});

test("up-to hold reads 'Up to $X · we’ll stop there' and unpriceable never enables Approve", () => {
  const card = read("components/rh/ApprovalCard.tsx");
  assert.match(card, /we’ll stop there/);
  const model = read("lib/rh/approval-model.ts");
  assert.match(model, /price_basis === "up_to"/);
  assert.match(model, /!insufficient && !model\.unpriceable/);
  assert.ok(!card.includes("does not mean free"));
});

test("pricing, up-to and unpriceable cards can always be declined with the quiet Not now", () => {
  const card = read("components/rh/ApprovalCard.tsx");
  assert.match(card, /model\.pricing \|\| model\.upTo \|\| model\.unpriceable \? \(\s*\/\/[^\n]*\n\s*<button[^>]*rh-btn-quiet[^>]*onClick=\{actions\.onNotNow\}>Not now/);
  assert.match(card, /UP_TO_FOOTNOTE = "We stop at this amount, you are never charged more\."/);
  assert.ok(!/30%|platform fee/i.test(card));
  assert.match(read("components/canvas/AgentDock.tsx"), /onNotNow: \(\) => onDecision\(approval, "reject", undefined, "not_now"\)/);
});
