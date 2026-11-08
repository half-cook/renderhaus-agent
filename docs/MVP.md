# End-to-end MVP

Branch: `codex/e2e-mvp`, based on staging `e8b0541`. Main `7d6c9fe` is an ancestor;
staging adds 617 commits (911 changed files). No broad merge or provider deletion is needed.

## Main versus staging

| Flow | Main | Staging / MVP |
| --- | --- | --- |
| fal generation | No general fal adapter | Validated queue submission, saved handles, polling |
| Seedance | BytePlus path | Seedance 2.5 via fal US, with BytePlus opt-in |
| Narration | Fish adapter exists; canvas prefers ElevenLabs | MVP defaults both agent narration and new canvas voice nodes to Fish |
| Assembly | Genuine Remotion Lambda | Same Lambda path plus a separate local FFmpeg backend; MVP acceptance uses Lambda |
| Completion | Older generation and canvas handling | Rejects dry runs or terminal jobs without saved media as completed outputs |
| Testing | Older backend suite | Expanded provider, approval, persistence, delivery and Studio contracts |

These are source comparisons. Fresh verification results are recorded separately below;
old regression fixtures and dry runs do not establish live success.

## Run

Requires AWS access to `renderhaus/app` in `us-east-1`, Python 3.11+, Node/npm,
FFmpeg/ffprobe, and the existing configured Remotion Lambda/site. No keys are printed
or committed. Authentication and per-step UI approvals remain enabled.

```bash
uv sync
npm ci --prefix studio
npm ci --prefix remotion
.venv/bin/python scripts/run_mvp.py
```

Open `http://localhost:5174` in Comet and sign in. The launcher starts the existing
Studio, API and loopback Gateway together. All providers are dry by default, even when
the shared secret contains live flags. Stop the launcher with Ctrl+C.

Restart with `scripts/run_mvp.py --live` only for real generation. This enables Seedance,
fal, Fish and Remotion; the remaining provider dry flags stay on. The launcher does not
change the shared secret or deploy over main/staging. It isolates the dev build directory
from production builds. Existing saved nodes keep their original provider identities.

## Reproduce the acceptance film

```bash
.venv/bin/python scripts/e2e_mvp.py --out .renderhaus/e2e/mvp-dry-new
.venv/bin/python scripts/e2e_mvp.py --out .renderhaus/e2e/mvp-live-new --live --secrets
```

The first command actually exercises the four adapters and validates an eight-second edit,
without contacting generation APIs or pretending to produce media. The second submits two
four-second silent Seedance shots and Fish narration, then assembles them with real Remotion
Lambda, timed titles, fades and subtitles. It downloads `final.mp4` and checks dimensions,
duration, source lengths, matching frame rate, H.264/AAC, audible narration and complete decode. This deterministic driver proves the media
pipeline, not agent decision-making or authenticated Studio E2E.

Each output directory holds `receipt.json`, `timeline.json` and `summary.json`. A process
lock prevents simultaneous runs from duplicating assembly. Keep the directory:
resume an interrupted live run with the same command plus `--resume`. Saved generation
handles are polled rather than resubmitted. An uncertain submission stops and requires
provider-history reconciliation; the driver will not duplicate it. Resume may start the
first assembly if none was submitted, but never regenerates missing source submissions.
Use a new output directory for a new paid generation.

After repairing a definitively failed assembly, add `--retry-assembly` to the live resume
command. It verifies that the saved render failed and archives its handle before starting
one replacement assembly. Running, successful or uncertain assemblies cannot be replaced.
The existing source clips and narration are reused.

## Verification and limits

Fresh dry-run dispatch, provider schemas, Lambda packaging, Python lint, Studio and Remotion
typechecks, and production builds were exercised during implementation. The acceptance
run's measured result and final test counts are recorded in `docs/MVP_VERIFICATION.md`.

Browser verification requires the normal signed-in Comet session. Pending login is not a
pass. Its exact status is recorded under ignored `.renderhaus/e2e/`, following `AGENTS.md`.

Specialized and legacy providers remain available for saved projects and explicit requests;
real-person references retain the existing consent-aware alternative route. They were not
removed because shared queue, schema and routing contracts depend on them. Generic new video,
animate and voice actions use Seedance and Fish. The existing Remotion bundle warns that its
Zod 3 dependency differs from the CLI's recommended Zod 4; unrelated schema migration is deferred.
Seedance image animation requires the measured source aspect ratio for a known-cost quote;
the existing Inspector exposes this control. Only text-to-video was exercised live here.
