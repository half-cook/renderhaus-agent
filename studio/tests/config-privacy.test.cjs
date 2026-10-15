const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
test("/api/config never returns provider or model names", () => {
  const src = fs.readFileSync(path.join(__dirname, "../../server/app.py"), "utf8");
  const start = src.indexOf('@app.get("/api/config")');
  const end = src.indexOf('@app.get("/api/health")', start);
  const body = src.slice(start, end);
  // Response keys must not expose model or provider names to the browser.
  assert.doesNotMatch(body, /"video_model"|"image_model"|"music_model"/);
  assert.match(body, /never name underlying providers or models/);
});
test("live invite form does not show a Sample tag", () => {
  const src = fs.readFileSync(path.join(__dirname, "../components/beta/InviteSignup.tsx"), "utf8");
  assert.doesNotMatch(src, /rh-sample|>Sample</);
});
