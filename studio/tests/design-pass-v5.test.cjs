// Designer review v5 launch blockers.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const read = (file) => fs.readFileSync(path.join(__dirname, "..", file), "utf8");
const card = () => read("components/rh/ApprovalCard.tsx");

test("1: pricing locks Approve and always offers Not now, live path included", () => {
  assert.match(card(), /const locked = busy \|\| approveEnabled === false \|\| model\.pricing === true/);
  assert.match(card(), /\{actions\.onNotNow \|\| model\.pricing/);
  const dock = read("components/canvas/AgentDock.tsx");
  assert.match(dock, /model=\{pricingCardModel\(approval\)\}/);
  assert.match(dock, /approveEnabled=\{!model\.pricing &&/);
});

test("2: home credit label is just 'Beta credit'", () => {
  const home = read("app/(app)/home/page.tsx");
  assert.match(home, /return "Beta credit";/);
  assert.ok(!/Beta credit · wave/.test(home));
});

test("3: up-to over credit takes the 49 lower-cap path", () => {
  assert.match(card(), /const credit = model\.upTo\s*\? \(model\.lowerCapOptionCents != null/);
  assert.match(card(), /Use this · lower the cap to \{formatCents\(lowered\)\}/);
  assert.match(card(), /Same step, up to <b[^>]*>\{formatCents\(lowered\)\}<\/b> · we’ll stop there\./);
});

test("4: an up-to card has one amount (cap = total = warning)", () => {
  assert.match(card(), /export function oneUpToAmount/);
  assert.match(card(), /const model = oneUpToAmount\(input\);/);
  assert.match(read("components/rh/LaunchReviewV4.tsx"), /capCents: estimate, upTo: true/);
});

test("5: phones shrink the stage while a card waits so cost lines and cap options show", () => {
  assert.match(read("app/revamp-v4.css"), /:has\(\.rh-appr-pending\) \.rh-stage-frame \{ width: min\(100%, 220px\)/);
  assert.match(card(), /scrollIntoView\(\{ block: "start" \}\), 350/);
});

test("6: empty Studio keeps a slim placeholder strip, stage centred (no empty band)", () => {
  assert.match(read("components/canvas/StudioStage.tsx"), /rh-strip-placeholder/);
  assert.match(read("app/revamp-v4.css"), /\.rh-agent-workspace \.rh-stage \{ justify-content: center;/);
});

test("no provider, model or fee wording in the changed card copy", () => {
  assert.ok(!/platform fee|service fee|markup|Seedance|ElevenLabs|Wan 3/i.test(card()));
});

test("empty Studio welcome never slides under the saved line, and a no-shots fixture exists", () => {
  assert.match(read("app/revamp-v4.css"), /\.rh-agent-dock \.agent-empty \{ flex-shrink: 0; justify-content: safe center; padding-top: 16px; \}/);
  assert.match(read("design-shots/screens.ts"), /id: "m03-agent-no-shots"/);
});

test("an empty conversation opens at the welcome heading, not scrolled to the bottom", () => {
  assert.match(read("components/canvas/AgentDock.tsx"), /conversationExecutions\.length === 0 && !liveRun\) \{ transcript\.scrollTop = 0; return; \}/);
});

test("home stacks to one column on phones so the project grid is not squeezed to 0px", () => {
  assert.match(read("app/revamp-v4.css"), /@media \(max-width: 800px\) \{ \.rh-home-cols \{ grid-template-columns: minmax\(0, 1fr\); \}/);
});
