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
