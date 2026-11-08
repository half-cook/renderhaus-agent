# MVP verification — 8 November 2026

The real media pipeline passed. Authenticated Studio E2E is **pending user login**;
this report does not claim the whole product has passed browser E2E.

## Live acceptance artifact

`Keep the light` contains two newly generated four-second Seedance 2.5 shots, Fish
narration, two timed title overlays, a caption and fades. Actual Remotion Lambda
render `tskrk9nd9c` produced the final MP4. Keys came from `renderhaus/app` and were
never printed, written to source or committed.

| Check | Observed result |
| --- | --- |
| Generation | Two real `bytedance/seedance-2.5/us/text-to-video` submissions; no source retries |
| Voice | One real Fish `s2.1-pro-free` MP3 |
| Video | H.264, native 1280×720, 24 fps, 8.000 seconds |
| Audio | AAC; container duration 8.085333 seconds includes audio encoding padding |
| Source resolution | 1280×720; no upscaling; resolution warnings: none |
| Integrity | SHA-256 `11c1e614f1889e1be51421ea970ae12608f94c7d7ea6401177484929f06123bc` |
| Technical checks | Complete decode, audible narration, matching source frame rate, source lengths and geometry passed |
| Visual inspection | Sampled opening title/caption and ending title readable, with expected lighthouse shots |
| Playback | Comet showed the final MP4 playing at 0:05 / 0:08 with audio-playing state |

Local file: `.renderhaus/e2e/mvp-live/final.mp4`. Receipt, timeline, summary and sampled
frames remain beside it under the ignored directory. The video is intentionally not in Git.

## Bug caught only by the live call

The first assembly (`b1896ntgsp`) failed: `"videoBitrate" must be a string ending in
"K" or "M". Got a number: 3269290`. The Python SDK annotated an integer but forwarded it
unchanged to Lambda. The shared adapter now converts only at that boundary: 3269290 bps
becomes `3270K`, rounding upward while retaining internal integer quality calculations.

The corrected assembly reused both clips and the narration. Its failed predecessor is
archived in the receipt. There were two assembly attempts, one failed and one successful.
No shared production application, Gateway or secret was redeployed or changed.

## Reproducible checks

Install the existing CI test dependencies when needed:

```bash
uv pip install pip pytest pytest-asyncio 'moto[s3,dynamodb]' ruff
.venv/bin/python scripts/ci_check.py
.venv/bin/python -m pytest -q
cd studio && node --test tests/*.test.cjs
```

Provider schema/skill parity, dry dispatch for all registered providers, Lambda package
construction and Python lint passed. Studio's 253 Node tests passed. Studio production
build, Studio typecheck, Remotion typecheck and Remotion bundle completed. The latest
focused MVP/launcher/Remotion checks passed 20 tests and 37 subtests, including source
validation, non-silent narration, concurrent-run rejection and safe assembly recovery.

The complete dry Python run took 12 minutes 25 seconds: **2,669 passed, 42 failures
(including subtests), 17 skipped, 3,734 passing subtests**. The failures were corrected
and all affected files rechecked: routing 347 tests / 452 subtests; explicit-provider
approval fixtures 48 tests / 2 subtests; Remotion parity and quality 25 tests / 85 subtests.
These are overlapping rechecks, not additional unique tests to sum. A final cached-failure rerun also passed 16 tests. The full expensive
suite was not repeated after those corrections.

The skips were 15 Linux-only bubblewrap cases on this Mac, one missing Pillow libraqm
joined-emoji capability, and one intentionally unverified Seedance extension-semantics case.
No new skips or weakened safety assertions were introduced.

## Remaining verification

Comet opened the real Studio landing and sign-in page with the real backend. The normal
Clerk login is still required before testing editor node creation, approvals, persistence
and export through the UI. Evidence status is `waiting_login` in
`.renderhaus/e2e/studio-mvp.json`; direct media playback is a separate completed check.
Text-to-video is live-tested; other generation modes retain their regression coverage.

The Remotion CLI bundle completes with a Zod-version warning (installed 3.25.76 versus
recommended 4.4.3). No schema migration was needed for the successful existing Lambda
composition. Main was compared by source/history; it was not separately live-deployed.
