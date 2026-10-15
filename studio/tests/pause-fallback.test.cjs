const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { pathToFileURL } = require("node:url");
const load = require("./load-ts.cjs");

const studio = path.resolve(__dirname, "..");
const fallback = load("lib/rh/pause-fallback.ts");
const question = (over = {}) => ({
  kind: "question", callId: "q1", question: "Keep the 9:16 cut or make a new 16:9 shot?", reason: "cost_difference",
  allowFreeText: true,
  options: [
    { id: "keep", label: "Crop the current shot", description: "Free, slight loss at the edges", estimateCents: 0 },
    { id: "new", label: "Make a new wide shot", description: "Can't be undone for free", estimateCents: 173 },
  ],
  ...over,
});

test("cards stay off unless the flag is exactly true", () => {
  assert.equal(fallback.pauseCardsEnabled({}), false);
  assert.equal(fallback.pauseCardsEnabled({ NEXT_PUBLIC_RH_PAUSE_CARDS: "false" }), false);
  assert.equal(fallback.pauseCardsEnabled({ NEXT_PUBLIC_RH_PAUSE_CARDS: " TRUE " }), true);
});

test("question becomes a chat message with lettered options and estimated prices", () => {
  const model = fallback.questionChatModel(question());
  assert.equal(model.text, "Keep the 9:16 cut or make a new 16:9 shot?");
  assert.deepEqual(model.options.map((o) => [o.letter, o.price]), [["A", "est. $0.00"], ["B", "est. $1.73"]]);
  assert.match(model.placeholder, /Reply A, B or describe/);
  assert.match(model.footnote, /only costs a few cents of planning/);
});

test("options without a server price show no price instead of a made-up one", () => {
  const model = fallback.questionChatModel(question({ options: [{ id: "x", label: "Shorter", description: "" }] }));
  assert.equal(model.options[0].price, "");
});

test("typed replies map to options or free text", () => {
  const model = fallback.questionChatModel(question());
  for (const [reply, id] of [["A", "keep"], ["b", "new"], ["2", "new"], ["option a", "keep"], ["B.", "new"], ["make a new wide shot", "new"]]) {
    assert.deepEqual({ ...fallback.replyToAnswer(model, reply) }, { kind: "choice", option_id: id }, reply);
  }
  assert.deepEqual({ ...fallback.replyToAnswer(model, "use the logo version") }, { kind: "text", text: "use the logo version" });
  assert.ok("error" in fallback.replyToAnswer(model, "   "));
});

test("options-only questions reject free text with a plain hint, never a stuck form", () => {
  const model = fallback.questionChatModel(question({ allowFreeText: false }));
  assert.deepEqual({ ...fallback.replyToAnswer(model, "something else") }, { error: "Reply with A or B." });
  assert.equal(fallback.replyToAnswer(model, "C").error, "Reply with A or B.");
});

test("a question with no options still has a reply box", () => {
  const model = fallback.questionChatModel(question({ options: [], allowFreeText: false }));
  assert.equal(model.allowFreeText, true);
  assert.deepEqual({ ...fallback.replyToAnswer(model, "Use the blue one") }, { kind: "text", text: "Use the blue one" });
});

test("answered line names the pick and its estimate", () => {
  const q = question({ decision: "answer", answer: { kind: "choice", option_id: "new" } });
  assert.equal(fallback.answeredLine(q), "You picked Make a new wide shot · est. $1.73");
  assert.equal(fallback.answeredLine(question({ decision: "answer", answer: { kind: "text", text: "go" } })), "You replied: go");
});

test("a pause with nothing visible to answer gets a plain way out", () => {
  assert.match(fallback.stuckPauseMessage("awaiting_approval", [], false), /Stop the run/);
  assert.equal(fallback.stuckPauseMessage("awaiting_approval", [question()], false), null);
  assert.equal(fallback.stuckPauseMessage("awaiting_approval", [], true), null, "the cap card handles its own pause");
  assert.equal(fallback.stuckPauseMessage("running", [], false), null);
  assert.match(fallback.stuckPauseMessage("awaiting_approval", [question({ decision: "answer" })], false), /Stop the run/);
});

test("unknown question reasons still render instead of hiding the pause", () => {
  const src = fs.readFileSync(path.join(studio, "lib/api.ts"), "utf8");
  assert.doesNotMatch(src, /item\.reason !== "cost_difference" && item\.reason !== "irreversible_outcome"\) return \[\]/);
});

test("AgentDock uses the chat fallback unless the flag is on", () => {
  const src = fs.readFileSync(path.join(studio, "components/canvas/AgentDock.tsx"), "utf8");
  assert.match(src, /pauseCardsEnabled\(\) \? QuestionCard : PauseChatMessage/);
  assert.match(src, /stuckPauseMessage\(/);
});

test("fallback copy names no vendor, model or fee", async () => {
  const { findCopyLeaks } = await import(pathToFileURL(path.join(studio, "design-shots/copy-rules.mjs")).href);
  const model = fallback.questionChatModel(question());
  const texts = [model.footnote, model.placeholder, fallback.stuckPauseMessage("awaiting_approval", [], false),
    ...fs.readFileSync(path.join(studio, "components/rh/PauseChatMessage.tsx"), "utf8").match(/"[^"\n]{3,}"/g)];
  for (const text of texts) assert.deepEqual(findCopyLeaks(text), [], text);
});
