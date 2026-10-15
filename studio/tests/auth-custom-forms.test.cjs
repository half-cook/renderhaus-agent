const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");

test("sign-in and sign-up use the custom invite/email-code form, not prebuilt Clerk cards", () => {
  const signIn = read("app/sign-in/[[...sign-in]]/page.tsx");
  const signUp = read("app/sign-up/[[...sign-up]]/page.tsx");
  assert.match(signIn, /<InviteSignup mode="sign-in" \/>/);
  assert.match(signUp, /<InviteSignup \/>/);
  for (const page of [signIn, signUp]) assert.doesNotMatch(page, /<SignIn\b|<SignUp\b|AuthPanel/);
});

test("Google goes through the SSO callback and redeems the invite after sign-up", () => {
  const form = read("components/beta/InviteSignup.tsx");
  assert.match(form, /strategy: "oauth_google", redirectUrl: SSO_CALLBACK/);
  assert.match(form, /after="\/sign-up\?redeem=1"/);
  assert.match(form, /form_identifier_not_found/);
  assert.match(read("app/sso-callback/page.tsx"), /AuthenticateWithRedirectCallback/);
});

test("phone landing stacks steps, demo head and FAQ under 640px", () => {
  const css = read("app/revamp.css");
  const block = css.slice(css.indexOf("@media (max-width: 640px)"));
  assert.match(block, /\.rh-steps \{ grid-template-columns: 1fr;/);
  assert.match(block, /\.rh-faq \{ flex-direction: column;/);
  assert.match(block, /\.rh-demo-head \{ flex-direction: column;/);
});

test("Clerk captcha slot is rendered on both the sign-in shell and the invite sign-up flow", () => {
  const form = read("components/beta/InviteSignup.tsx");
  assert.match(form, /<div id="clerk-captcha"/);
  assert.equal((form.match(/<ClerkCaptcha \/>/g) || []).length, 2);
});

test("Google button and copy only appear when Google OAuth is enabled in Clerk", () => {
  const form = read("components/beta/InviteSignup.tsx");
  assert.match(form, /if \(!enabled\) return null;/);
  assert.match(form, /socialProviderStrategies\.includes\("oauth_google"\)/);
  assert.match(form, /"Sign in with a code sent to your email\."/);
  assert.match(read("app/revamp-v4.css"), /\.rh-form-v4 \.rh-step-body \{ margin-left: 0; \}/);
});

test("Google is full width and disabled Send code stays readable", () => {
  const css = read("app/revamp-v4.css");
  assert.match(css, /\.rh-form-v4 \.rh-btn-block\.rh-google \{ width: 100%;/);
  assert.match(css, /\.rh-form-v4 \.rh-btn-solid\[disabled\] \{ opacity: 1;[^}]*color: var\(--rh-fg-2\)/);
});

test("googleEnabled reads socialProviderStrategies from the loaded Clerk environment", () => {
  const form = read("components/beta/InviteSignup.tsx");
  assert.match(form, /__internal_environment \?\? host\.environment \?\? host\.__unstable__environment/);
  assert.match(form, /window as unknown as \{ Clerk\?: ClerkEnvHost \}/);
});

test("captcha sits inside the form card, not beside it", () => {
  const form = read("components/beta/InviteSignup.tsx");
  assert.doesNotMatch(form, /\{children\}<ClerkCaptcha \/>/);
  assert.match(form, /<ClerkCaptcha \/>\s*<p className="rh-form-fine">Already in\?/);
  assert.match(form, /<ClerkCaptcha \/>\s*<p className="rh-form-fine">New here\?/);
});
