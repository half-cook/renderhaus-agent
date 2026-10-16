const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const dock = fs.readFileSync(path.join(__dirname, "../components/canvas/AgentDock.tsx"), "utf8");
const api = fs.readFileSync(path.join(__dirname, "../lib/api.ts"), "utf8");
const card = fs.readFileSync(path.join(__dirname, "../components/rh/ApprovalCard.tsx"), "utf8");

test("the agent dock wires Not now to the existing reject decline path", () => {
  assert.match(dock, /onNotNow:\s*\(\)\s*=>\s*onDecision\(approval,\s*"reject",\s*undefined,\s*"not_now"\)/);
  assert.match(dock, /NOT_NOW_LINE\s*=\s*"Paid step skipped · finishing your response\."/);
  assert.match(dock, /pausedNote && activeExecution\?\.jobId === pausedNote/);
  assert.doesNotMatch(dock, /nothing more will be charged/);
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

test("a run the user declined reads as a pause, not a failed delivery", () => {
  assert.match(dock, /state === "incomplete" && declined \? "Paused · you chose Not now"/);
  assert.match(dock, /const declined = !assets\.length && execution\.approvals\.some\(\(approval\) => approval\.decision === "reject"\)/);
});
