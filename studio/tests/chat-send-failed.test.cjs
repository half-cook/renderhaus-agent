const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const load = require("./load-ts.cjs");
const f = load("lib/chat-failure.ts");
const dock = fs.readFileSync(path.join(__dirname, "../components/canvas/AgentDock.tsx"), "utf8");
const api = fs.readFileSync(path.join(__dirname, "../lib/api.ts"), "utf8");

test("first failure shows one quiet line with no codes or service names", () => {
  const turn = f.nextFailedTurn(null, "make a teaser");
  assert.deepEqual(turn, { prompt: "make a teaser", attempts: 1 });
  assert.deepEqual(f.failureLines(turn), ["Couldn't reach Renderhaus · nothing charged"]);
  assert.equal(f.SEND_FAILED_RETRY, "Try again");
  for (const line of f.failureLines(f.nextFailedTurn(turn, "make a teaser"))) assert.doesNotMatch(line, /\d{3}|bedrock|anthropic|openai|server|error/i);
});

test("a failed retry adds the reassurance line", () => {
  const again = f.nextFailedTurn(f.nextFailedTurn(null, "p"), "p");
  assert.equal(again.attempts, 2);
  assert.deepEqual(f.failureLines(again), ["Couldn't reach Renderhaus · nothing charged", "We're on it, your credit is untouched"]);
  assert.equal(f.nextFailedTurn(again, "other").attempts, 1);
});

test("5xx and network failures are marked unreachable; Try again resends the kept message", () => {
  assert.equal(f.isUnreachableStatus(503), true);
  assert.equal(f.isUnreachableStatus(402), false);
  assert.match(api, /unreachable: response\.status >= 500/);
  assert.match(api, /catch \{\s*return \{ status: "error", message: "Couldn't reach Renderhaus", unreachable: true \}/);
  assert.match(dock, /<UserMessage text=\{failedTurn\.prompt\} \/>/);
  assert.match(dock, /onClick=\{\(\) => void submit\(undefined, undefined, failedTurn\.prompt\)\}/);
  assert.match(dock, /role="alert"/);
  assert.match(dock, /!liveRun && !failedTurn && !changesDocument/);
});

test("a refused start (402 credit held) keeps the message and shows the server's plain reason", () => {
  const turn = f.nextFailedTurn(null, "space heist", "Most of your credit is held by runs waiting for your approval.");
  assert.deepEqual(f.failureLines(turn), ["Most of your credit is held by runs waiting for your approval."]);
  assert.match(dock, /refusal \? nextFailedTurn\(previous, prompt, refusal\)/);
  assert.match(dock, /\{failedTurn\.note \|\| SEND_FAILED_LINE\}/);
  assert.match(api, /detailMessage/);
});
