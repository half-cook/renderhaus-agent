# Reference shot breakdown

`reference-shot-breakdown` analyzes the edit of one finished reference film. The local
`Reference___shot_breakdown` tool measures the timeline and exports review artifacts.
`Gemini___judge_shots` adds visual labels through the existing Gemini judge transport.
The stages use the existing Deep Agents editor and media roles and native approval.
No agent loop, graph or provider credential system is added.

## Local contract

`op="measure"` accepts the current `job_id`, a confined video `input_path`, and empty
`params`. Studio resolves owned asset-version handles inside that job. The worker
records source dimensions and duration, threshold-sweep cuts, exact shot intervals,
median consecutive-frame differences and paired contact sheets. Two-decimal durations
are display values. Full-precision cut deltas determine duration coverage and pace.

`op="report"` takes the saved measurement path and `params.labels`, plus the saved
`measurements_sha256`. Each label supplies one measured `shot_id`, shot size, category,
camera move, frame description and rhythm role. Label timing fields are rejected.
Source, measurement, sheet and player integrity are checked before export. Moving-camera
claims fail when measured motion is near zero. Insufficient motion remains unknown.
`camera_move` is a closed classification, including `static`, `push`, `pull`, `pan`,
`truck`, `track` and `unknown`. Compound descriptions belong in the frame description.
Every moving classification reaches the same pixel gate; free-text camera claims are rejected.
Subject movement with a static-camera label produces a hint, not a failed camera gate.

The local tool cannot make network or paid requests. `REFERENCE_SHOTS_DRY_RUN` defaults
to `true` and validates arguments without reading media. The worker requires installed
ffmpeg and ffprobe and is excluded from Lambda deployment with `local_only=True`.
Studio keeps reference-analysis conversations on its own host even when
`AGENTCORE_DEV_URL` selects a remote runtime for other requests. The checkpoint records
that host choice so approval resumes and follow-ups retain access to owned local evidence.
Maximum duration is 600 seconds and maximum shot count is 60. Bounded input, subprocess,
output and standalone-player limits fail explicitly rather than truncate a film.

Each analysis owns a unique job bundle. It exports `shots.json`, a CSV remake brief and
an HTML report with embedded player and contact sheets. The player highlights the measured
shot during playback and seeks on shot selection. Artifact downloads require the owning
authenticated workspace/execution and matching saved checksums. HTML is an attachment,
not executable content injected into Studio.

## Visual-review contract

`Gemini___judge_shots` accepts an owned `reference` object containing `job_id`,
`analysis_path` and `measurements_sha256`. The current worker verifies and encodes
the sheets after normal approval. Direct bounded `contact_sheet_b64` and ordered
`shot_ids` are also accepted, exclusively from the reference object. No original film
is submitted. `Gemini___get_task` reuses the asynchronous Interactions poll with
`rubric="reference_shots"` and the measured ordered IDs. Its default rubric remains
`continuity`, preserving existing calls.

The canonical `gemini_vlm_judge` routing ID already names the fixed continuity tool.
It remains unchanged. Auxiliary ID `gemini_shot_labels` names the separate shot-label
rubric on the same model/transport. `local_qc` remains the continuity default. Neither
project confidentiality nor stored quality tiers changes these selections.

`GEMINI_DRY_RUN` defaults true. Dry-run and failed reviews return `skipped` without labels.
Live submissions use existing normal non-video approval and autonomous spending caps.
All video-generation approval rules and `APPROVAL_EXEMPT_TOOLS` remain unchanged.
The background API stores the submitted sheets. Source rights and personal-data
permissions are required. Hosted terms grant no continuity-training eligibility.

Official model and API references re-read 2026-10-15:

- [Gemini 3.8 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) verifies the existing `gemini-3.8-flash` ID and image input.
- [Interactions API](https://ai.google.dev/api/interactions-api) verifies `/v1beta/interactions`, background submit, stored requests, image parts and JSON response schemas.
- [Official pricing](https://ai.google.dev/gemini-api/docs/pricing) lists $0.75 input and $3.75 output per million tokens through 2026-12-31, then $1.50 and $7.50. Existing dated `gemini_rates` handles expiry. Pre-call token usage is unknown. `GEMINI_TOOL_COST_CENTS_JSON` may supply an operator quote for `judge_shots`; no per-shot price is invented.
- [API terms](https://ai.google.dev/gemini-api/terms) govern hosted use. Model weights are closed and are not installed. Training eligibility remains false.
- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) and [legal information](https://ffmpeg.org/legal.html) describe the installed binary. Its LGPL or GPL licence depends on the build. No binary or upstream source is vendored.

## Verification limits

Tests use real local ffmpeg synthetic films with independently known cuts and mocked
judge transport. They exercise motion evidence, contact sheets, report artifacts,
invalid labels, camera gates, source integrity, approvals and authenticated downloads.
They do not establish real-footage label quality. No scored model eval, live judge call,
or paid generation is authorized in this task.

Caller-supplied labels remain `labels_provenance="unverified"`; mocked labels are
`simulated`. Export success and passing deterministic gates do not clear
`semantic_review_pending`. The feature does not attest a finished customer deliverable.
A future production semantic-acceptance path needs observed review provenance.

RT-186 and RT-187 were absent from this clone's fixture and available routing CSVs.
They were added from the supplied reference spec, with that origin recorded in each row.
Other skipped rows retain their existing dependency reasons.

Comet Studio browser E2E is pending access in this environment. The task receipt under
ignored `.renderhaus/e2e/` records the concrete blocker. Supporting tests are not browser E2E.

Workflow inspiration is attributed in the skill's NOTICE. No AGPL or non-commercial
source or weights are added. [The decision trail](reference-shot-breakdown-decisions.tsv)
records design choices, evidence and verification limits.
