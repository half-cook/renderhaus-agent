// Invite sign-up: only a real wrong code says "didn't match"; other failures get plain, provider-free text.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const load = require("./load-ts.cjs");
const m = load("lib/signup-errors.ts");
const api = (code) => ({ errors: [{ code, message: "x" }] });

test("wrong-code API errors map to wrong_code", () => {
  assert.equal(m.classifyConfirmError(api("form_code_incorrect")).kind, "wrong_code");
  assert.equal(m.classifyConfirmError(api("verification_failed")).kind, "wrong_code");
  assert.equal(m.classifyConfirmError(api("form_code_incorrect")).message, m.WRONG_CODE);
});

test("expired, captcha, too-many and unknown errors are not called a wrong code", () => {
  assert.equal(m.classifyConfirmError(api("verification_expired")).kind, "expired");
  assert.equal(m.classifyConfirmError(api("captcha_invalid")).kind, "captcha");
  assert.equal(m.classifyConfirmError(api("captcha_missing_token")).kind, "captcha");
  assert.equal(m.classifyConfirmError(api("too_many_requests")).kind, "too_many");
  assert.equal(m.classifyConfirmError(new Error("network")).kind, "other");
  assert.notEqual(m.classifyConfirmError(new Error("network")).message, m.WRONG_CODE);
});

test("missing_requirements says the email is confirmed and logs the missing fields", () => {
  const warned = [];
  const original = console.warn; console.warn = (...args) => warned.push(args);
  try {
    const failure = m.incompleteResult({ status: "missing_requirements", missingFields: ["password"] });
    assert.equal(failure.kind, "not_finished");
    assert.equal(failure.message, "Your email is confirmed, but sign-up isn’t finished. Try again in a minute.");
    assert.deepEqual(failure.missingFields, ["password"]);
    assert.deepEqual(warned[0][1].missingFields, ["password"]);
  } finally { console.warn = original; }
  assert.equal(m.incompleteResult({ status: "abandoned" }).kind, "other");
});

test("copy names no provider", () => {
  for (const key of ["WRONG_CODE", "EXPIRED_CODE", "NOT_FINISHED", "CAPTCHA", "TOO_MANY", "CONFIRM_FAILED"]) assert.ok(!/clerk|google|aws/i.test(m[key]), key);
});

test("InviteSignup no longer swallows every confirm error as a wrong code", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "components/beta/InviteSignup.tsx"), "utf8");
  assert.ok(!/catch \{ setWrong\(true\)/.test(src));
  assert.match(src, /if \(failure\.kind === "wrong_code"\) \{ setWrong\(true\)/);
  assert.match(src, /throw incompleteResult\(result\)/);
});
