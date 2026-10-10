# Named Pixelcut and PixVerse video

Renderhaus supports two hosted fal endpoints through the existing `named-provider` skill.
Only an explicit Pixelcut or PixVerse/VibeMV instruction selects them. Quoted titles and
negated names are excluded. Generic product loops, spins, music videos and karaoke retain
the capability defaults. Neither endpoint is a capability default, exception or fallback.
`project.confidential` does not affect selection.

## Tools and contracts

| Canonical ID / Gateway tool | fal endpoint | Required arguments | Optional controls |
| --- | --- | --- | --- |
| `pixelcut_looping_video` / `Fal___pixelcut_looping_video` | `pixelcut/looping-video` | `image_url` (JPEG/PNG/WebP) | `prompt` ≤4000 characters; integer `duration` 5–15, default 5; `resolution` 480p/768p/1080p, default 1080p; `motion` subtle/spin, default subtle; `include_audio=false`; local `real_face_refs`, `likeness_consent` |
| `pixverse_vibemv` / `Fal___pixverse_vibemv` | `pixverse/music-video/vibemv` | `audio_url` (MP3/WAV); measured local `audio_duration_seconds` 10–360 | `image_url`; `style_image_url` paired with `style=Custom`; `music_style`; `style=Cinematic`; `aspect_ratio=16:9` (also 9:16, 1:1, 4:3, 3:4); `resolution=720p` (also 1080p); `lyrics` ≤5000 characters; `lip_sync_switch=false`; `enable_safety_checker=true`; local real face/voice flags and consent |

Gateway describes exact style and music-style enums from the official schemas. The adapter
rejects unsupported fields, types, ranges, enum values, nonfinite measurements and local-file
URLs before HTTP. HTTP(S), appropriate data URIs and Studio asset handles are supported;
handles must resolve before a live submit. Optional explicit `null` is omitted. Endpoints are
fixed, so neither tool accepts a `model` argument. Renderhaus requires a Custom reference and
rejects a style reference for other styles to avoid silently ignored controls.

`audio_duration_seconds` is a measured source field, never an output length control. It and
`real_face_refs`, `real_voice_refs`, `likeness_consent` are local fields and never sent to fal.
The host requires consent for inputs flagged as containing a real face or voice. Remote media
format, image dimensions and actual audio duration remain vendor-side validation; the local
adapter validates the declared measurement and does not probe or download inputs.

## Queue, approval and Studio

The adapters submit once to `https://queue.fal.run/<endpoint>` and reuse
`Fal___get_video_task(job_id, download=true)`. Shared polling retains endpoint/mode/licence
provenance, maps queued/running/failed states and saves the completed MP4 atomically. Queue
poll URLs use the fal application root (first two endpoint path segments), including
`pixverse/music-video`. Never resubmit merely to check status.

Both tools always interrupt with provider, model and cost, including autonomous runs and
when `RENDERHAUS_PREMIUM_VIDEO_APPROVAL=false`. Rejection never calls the provider. Existing
approval exemptions and spend caps are unchanged. Unnamed executor calls are blocked even
if a caller attempts to mark them approved. Direct Studio invocation returns 409 and directs
the request through the named-provider skill and approval flow.

Studio shows named-only model labels. These outputs stay asset nodes rather than acquiring
a rerunnable generic Wan VACE tool. Submission or a dry-run preview is incomplete media.
Play the saved artifact, inspect Pixelcut's loop seam or VibeMV's music/lyrics alignment,
and report its actual dimensions before delivery. Unknown source dimensions remain unknown.
Normal delivery-render workflows still require matching saved QC checksums and visual review.

## Prices and configuration

Official sources were actually read **2026-10-10**; this records the read date without
backdating to the brief's 2026-10-08/09 leads.

| Endpoint | Provider price | Official price and schema sources |
| --- | --- | --- |
| Pixelcut | $0.08/second at 480p; $0.16 at 768p; $0.32 at 1080p. Output seconds; audio and motion do not change price. | [Pricing](https://fal.ai/models/pixelcut/looping-video), [API](https://fal.ai/models/pixelcut/looping-video/api), [OpenAPI](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=pixelcut/looping-video) |
| PixVerse VibeMV | $0.06/second at 720p; $0.09 at 1080p. Input audio duration rounded up to whole seconds, minimum 10 seconds. | [Pricing](https://fal.ai/models/pixverse/music-video/vibemv), [API](https://fal.ai/models/pixverse/music-video/vibemv/api), [OpenAPI](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=pixverse/music-video/vibemv) |

Quotes use Decimal arithmetic plus the existing Renderhaus platform fee (currently 30%),
rounded to integer cents. A default 5-second 1080p Pixelcut request is $1.60 provider / $2.08
with fee. A 10.1-second VibeMV track at 1080p rounds to 11 billed seconds: $0.99 provider /
$1.29 with fee. Missing or invalid VibeMV measurements yield unknown cost and block dispatch.
Dry-run billing charges zero; approval disclosure retains the live list-price estimate.

Existing `FAL_DRY_RUN` defaults true and CI forces it true. Existing `FAL_KEY` comes from the
environment or the application's Secrets Manager object via `scripts/sync_secrets.py`.
There are **no new environment variables, secrets, dry-run flags or provider targets**.
Existing `RENDERHAUS_MEDIA_DIR` and hosted durable-storage settings apply to shared polling.
No provider call, credential access, deployment or account availability check was performed.

## Licence, consent and training

Both official endpoint cards advertise commercial use. These are closed hosted models;
Renderhaus records `license=service-terms`, `weights_license=closed-weights`, commercial use
permitted subject to input rights and provider terms, and `training_eligible=false` for both.
Sources read 2026-10-10:

- [fal Terms of Service](https://fal.ai/legal/terms-of-service): section 6(d) requires rights
  and consents for inputs; section 14.3 restricts third-party output use to train competing models.
- [API Services Agreement](https://fal.ai/legal/api-services): sections 2.3–2.4 describe
  third-party processing and fal's training exclusions; they do not grant a clear customer
  training licence for these outputs.
- [Acceptable Use Policy](https://fal.ai/legal/acceptable-use-policy): section 3.3 limits
  unauthorized likeness use and impersonation. No model-specific consent API was verified.

The conservative training decision survives forged output licence/training metadata. Input
music, lyrics, images and likenesses must be owned or licensed with all necessary consents.
No upstream code or weights were copied; no AGPL or noncommercial dependency was introduced.
fal remains the existing US-accessible host; public terms show no US exclusion for these
endpoints. Actual account access, region availability and live artifact quality are untested.

## Routing evidence and remaining work

Two active fixtures were added: “use Pixelcut looping video…” and “PixVerse VibeMV…”. No
matching provider-pending row existed to activate. Inventory is 16 providers, 119 Gateway
tools, 31 skills and 238 routing rows: 233 active, 5 still skipped. The skips retain their
dependency reasons: one HyperFrames overlay, three product-demo capture and one exact
end-card OCR case. Unnamed, quoted and negated requests are covered separately by regression
tests. Wan retry cannot replace an explicitly requested Pixelcut model after visual rejection.

Offline tests cover fake submit/poll/download, typed failures before HTTP, known and unknown
quotes, dry-run persistence, named-only enforcement and native deepagents 0.7.23 approval
pause/resume for both approve/reject decisions. The final full suite passed 2,030 tests (2,023 passed, 7 skipped), including 18 new focused
checks and two new routing fixture cases. The starting commit passed 2,010 tests (7 skipped).
Ruff, `scripts/ci_check.py`, generated fal schemas, Studio `tsc --noEmit -p .` and the offline
Studio artifact/label script passed. The temporary node_modules symlink was removed.
These checks do not establish playable real media.
Comet is unavailable in this environment and live provider calls are prohibited. Browser E2E
is **blocked**, including actual Pixelcut loop playback and VibeMV audio alignment/quality.
The ignored `.renderhaus/e2e/named-fal-video.json` records the blocker through the browser hook.

TODO: authorized Comet validation with a real backend, recorded cost approval/rejection,
saved artifact playback, measured dimensions and visual/music quality review. Model IDs,
schemas and listed prices are verified; model-specific consent APIs and live account/region
availability remain unverified. See [decisions](../named-provider-pixelcut-pixverse-decisions.tsv).
