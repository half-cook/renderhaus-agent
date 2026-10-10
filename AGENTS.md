# Completing features and fixes

After changing app behavior, validate the affected flow in the real running browser before
claiming completion. This includes backend-only changes that affect the Studio. Unit tests,
mock providers, HTTP health checks, and reading logs are supporting checks, not browser E2E.

Follow [docs/BROWSER_E2E.md](docs/BROWSER_E2E.md). Use the available browser tools to exercise
the specific feature or original reproduction through the UI with the real backend, inspect
the visible result and relevant errors, and record the outcome. Re-test after further fixes.

Use Perplexity **Comet** for browser validation, preferably its existing Renderhaus tab and
signed-in session. The browser extension may identify this Chromium browser as `Chrome`;
confirm it is Comet from the available app/browser state. Do not silently switch to the
in-app browser. If Comet cannot be controlled, ask for access and record the blocker.

If the browser needs authentication, open the sign-in page, show/hand off the tab, and ask the
user to log in and tell you when done. Continue independent work while waiting. Never request
passwords, OTPs, cookies, or tokens in chat, copy browser credentials, or disable authentication.
Record `waiting_login`, explicitly say E2E is pending, and resume verification after login.
Reuse an existing signed-in session when available; do not ask the user to log in again.

Choose a small scenario that covers the changed behavior, including its important failure or
approval branch. Honor the user's existing action and spending authorization. A blocked paid
or external action is an incomplete check, never a pass. Do not switch to mock mode to claim
real E2E success. For generated media, verify the actual artifact opens/plays; a job being
accepted or a progress message is not completion.

Keep evidence under ignored `.renderhaus/e2e/`, without credentials or signed URLs. Record
the steps, expected result, observed result, and browser evidence using
`python3 scripts/browser_e2e_hook.py record --report <report.json>`.
Only use `passed` after performing the browser actions and observing success. Use `blocked`
with the concrete reason when a dependency prevents completion. The final answer must state
what was tested and any incomplete validation, rather than asking the user to test the fix.

The project hooks reinforce this workflow when loaded and trusted. Follow these instructions
in the current task even if newly installed hooks are not active yet. Documentation-only and
test-only changes do not require unrelated browser tests. Explicit user instructions take
precedence, including requests to stop, skip a test, or avoid a particular action.

Satya chose `claude-sonnet-5-5` after Haiku 5.5 as the default Deep Agents
manager/planner and every subagent.

When summarizing an assembled video, state the successful render's delivered width and
height and source_resolution. Include its resolution warnings. A native 1280x720 export
is 720p. A 1920x1080 canvas resampled from it must say "upscaled from 1280x720; no added
detail". Mention the Topaz `upscale` skill for actual enhancement, with existing approval.
Unknown source dimensions remain unknown. Choosing a lower Wan resolution produces a
lower-resolution deliverable unless an upscale is requested; keep routing and cost defaults.

For delivery-render and deliverable-QC workflows, call an artifact finished or delivered
only when its saved QC report passed and still matches every output checksum. Otherwise
include each reported failure verbatim in the customer summary. Matrix technical checks
do not accept framing, captions, legal copy or prices; keep pending visual review explicit.
