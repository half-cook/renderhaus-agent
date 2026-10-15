const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const dock = fs.readFileSync(path.join(__dirname, "../components/canvas/AgentDock.tsx"), "utf8");
const api = fs.readFileSync(path.join(__dirname, "../lib/api.ts"), "utf8");
const card = fs.readFileSync(path.join(__dirname, "../components/rh/ApprovalCard.tsx"), "utf8");

test("the agent dock wires Not now to the existing reject decline path", () => {
  assert.match(dock, /onNotNow:\s*\(\)\s*=>\s*onDecision\(approval,\s*"reject",\s*undefined,\s*"not_now"\)/);
  assert.match(dock, /NOT_NOW_LINE\s*=\s*"Paused · nothing charged · your credit is free to use\."/);
  assert.match(dock, /source === "not_now"[\s\S]*setPausedNote/);
  assert.match(api, /if \(source\) body\.message = source/);
  assert.match(api, /decision: "approve" \| "reject"/);
});

test("screen 49 Use this lowers the cap with no price on Approve", () => {
  assert.match(card, /Use this · lower the cap to \{formatCents\(lowered\)\}/);
  const over = card.slice(card.indexOf("function OverCredit"));
  assert.doesNotMatch(over, /Approve · est\./);
  assert.match(over, /<Lock[^/]*\/>Approve/);
});
