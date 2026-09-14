# Browser verification after a feature or fix

The project uses Codex's documented `UserPromptSubmit` and `Stop` hooks in
[.codex/hooks.json](../.codex/hooks.json). The first records a source baseline and supplies
the workflow; the second requests a continuation when app code changed without browser
evidence. Codex performs the browser work using its current browser tools, so it can test
different features and hand authentication to the user. The Python hook itself does not
launch a second agent, log in, call providers, or pretend to automate every UI scenario.

## One-time activation

Open this repository in Codex and review/trust the two **Preparing browser validation** /
**Checking browser validation evidence** hooks in the hook manager (`/hooks` in the CLI).
New/changed non-managed hooks do not execute until trusted, and project configuration must
be trusted. Start or resume a task after installing the hook so its configuration is loaded.
Do not bypass trust or edit Codex's trust records. The repository's `AGENTS.md` applies the
same workflow while a newly added hook awaits activation.

Source: [official Codex hooks documentation](https://learn.chatgpt.com/docs/hooks).

## The required workflow

1. Define the changed user behavior and a short scenario that would catch the original bug.
   Run the appropriate focused tests, then start/restart the affected services.
   Backend: `.venv/bin/python -m server.app` (port 8000).
   Frontend: `cd studio && npm run dev` (localhost:5174). Keep the configured `localhost`
   hostname: Next middleware can self-proxy when bound explicitly to `127.0.0.1`.
2. Use **Perplexity Comet**, reusing its existing Renderhaus tab and session. Its browser
   extension can appear as `Chrome`; confirm it is Comet from the app/browser inventory.
   Do not silently substitute the in-app browser. Open/reuse `http://localhost:5174/`
   with the available browser tools. Inspect the actual
   page before clicking. HTTP status checks are useful setup checks, not E2E evidence.
3. If authentication is required, show the sign-in tab and ask the user to sign in there
   and reply when ready. Do not collect credentials, export cookies/storage state, bypass
   Clerk, or create a test-only auth shortcut. Record `waiting_login` and keep the task's
   validation pending. After the user returns, inspect the page to verify login succeeded.
4. Exercise the affected feature through the UI with the real backend. Test relevant
   approval/rejection/error behavior. Check the final visible result, browser errors, and
   relevant backend job/error state. Reload when persistence matters. For a generated
   artifact, open it and verify it renders or plays. A demo landing page is not the Studio.
5. Respect action/spending authorization. Use the smallest meaningful test. If a required
   provider action lacks authorization, explain the exact action needed, record `blocked`,
   and do not claim that a mock or partial check proves the live feature works.
6. If the test fails, fix it and repeat the affected browser flow against the restarted
   code. Record the final observations only after the test, not in anticipation of it.

## Record the result

Create an ignored JSON report, for example `.renderhaus/e2e/approval-flow.json`:

```json
{
  "status": "waiting_login",
  "scenario": "Verify Studio tool approval after a batched request",
  "url": "http://localhost:5174/sign-in",
  "steps": ["Opened the real app", "Clicked Sign in", "Asked the user to log in"],
  "expected": "An authenticated Studio session and a working approval flow",
  "observed": "Sign-in is required. The feature has not yet been tested.",
  "evidence": ["Browser accessibility observation: sign-in page"]
}
```

Run `python3 scripts/browser_e2e_hook.py record --report .renderhaus/e2e/approval-flow.json`.
The current task ID comes from `CODEX_THREAD_ID`; the injected hook context also supplies
an explicit `--session` command for other clients. Use `status` to inspect local gate state.
Use `require` to request browser verification explicitly when debugging existing behavior
without changing files. Reports and state stay under ignored `.renderhaus/e2e/`.

`passed` requires steps, expected/observed results, and evidence. Evidence may reference
screenshots, accessibility/DOM observations, UI-visible job IDs, or sanitized error logs.
Never store credentials, private browser storage, or signed media URL query strings.

The receipt is tied to the source contents: later app edits invalidate it. Existing dirty
files are baselined at the first prompt rather than forcing unrelated tests; documentation
and test-only edits do not trigger the gate. A login/blocker receipt permits a truthful
handoff but remains pending and is rechecked on the next user turn. A Stop continuation is
bounded to avoid an endless loop if tools are unavailable; it emits an incomplete-validation
warning and leaves the requirement pending. An explicit user request takes precedence.

This is an agent workflow gate with recorded observations, not an independent browser test
runner or a guarantee that a self-reported result is correct. The final answer must say which
flow was actually tested, its result, and any blocker. Never label a login handoff as a pass.
