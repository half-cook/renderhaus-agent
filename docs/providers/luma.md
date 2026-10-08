# Luma video provider

Renderhaus exposes the direct official Luma API through the `Luma` Gateway target.
The [Dream Machine welcome page](https://docs.lumalabs.ai/docs/welcome) links to the current
[Luma API documentation](https://docs.agents.lumalabs.ai/).
The implementation uses `POST https://agents.lumalabs.ai/v1/generations` and
`GET https://agents.lumalabs.ai/v1/generations/{id}`. It does not use an aggregator.
Documentation and pricing were checked on 2026-10-08.

## Tools and supported settings

Gateway names have the `Luma___` prefix. Python dispatch uses provider `luma` and the names below.

| Tool | Arguments | Behavior |
| --- | --- | --- |
| `text_to_video` | `prompt`, `duration_seconds=5`, `aspect_ratio="16:9"`, `resolution="720p"`, `model="ray-3.2"` | Submit a new text-driven video. |
| `image_to_video` | `prompt`, `image_path_or_url=None`, `last_frame_path_or_url=None`, `duration_seconds=5`, `aspect_ratio="16:9"`, `resolution="720p"`, `model="ray-3.2"` | Use a start image, an end image, or both. At least one is required. |
| `extend_video` | `prompt`, `generation_id`, `direction="forward"`, `resolution="720p"`, `model="ray-3.2"` | Continue or prepend a completed generation belonging to the same Luma client. |
| `modify_video` | `prompt`, `source_duration_seconds`, `video_path_or_url=None`, `source_generation_id=None`, `resolution="720p"`, `strength=None`, `model="ray-3.2"` | Restyle or edit exactly one source MP4 video. |
| `get_video_task` | `job_id`, `download=True` | Poll once and persist completed media. |
| `list_luma_models` | None | Return the documented capability catalog without HTTP. It does not check account access. |

Prompts contain 1 to 6,000 characters. Model IDs are restricted to `ray-3.2`.
Text generation accepts 5s or 10s. Start/end image anchors accept only 5s.
Aspect ratios are `9:16`, `3:4`, `1:1`, `4:3`, `16:9`, and `21:9`.
Generation and Modify resolutions are `360p`, `540p`, `720p`, and `1080p`.
The `360p` draft tier is the cheaper preview option.
Extend supports `540p`, `720p`, and `1080p`, with directions `forward` or `backward`.
This integration exposes SDR output. HDR, EXR, reframe, looping, and multi-keyframe controls are outside this scope.

The [official migration guide](https://docs.agents.lumalabs.ai/guides/videos/migration/)
states that the current API has no separate Flash or Relaxed model ID.
Legacy identifiers are not accepted by the current endpoint.
Do not invent `ray-3.2-flash` or send legacy `ray-flash-2` to it.

The [create-generation reference](https://docs.agents.lumalabs.ai/api/resources/generations/methods/create/)
states that Modify output duration matches the source. The editing guide specifies that aspect ratio is preserved.
`source_duration_seconds` must be 5 or 10.
Renderhaus checks the MP4 movie header before the paid POST and rejects a quote that disagrees with the source.
Hosted inputs are downloaded with a 200 MB limit for this check. Local MP4 files use inline base64.
A prior generation must be completed and have a video output; Renderhaus inspects that output too.
Inputs with an unknown duration fail before submission.
Luma permits source videos up to 18s, but its published pricing does not define other duration tiers.
TODO: support other source lengths only after confirming their official billing rules. No per-second price is assumed.

Without `strength`, Modify sends `video.edit.auto_controls=true`.
With `strength`, it sends a manual preset. Accepted presets are `adhere_1`, `adhere_2`, `adhere_3`,
`flex_1`, `flex_2`, `flex_3`, `reimagine_1`, `reimagine_2`, and `reimagine_3`.
The [generation guide](https://docs.agents.lumalabs.ai/guides/videos/generation/) and
[editing guide](https://docs.agents.lumalabs.ai/guides/videos/editing/) define these limits and request shapes.
Remote image dimensions and hosted input availability remain provider-side checks.
Image inputs have a documented 50 MB limit and a maximum of 8,000 pixels per side.

## Submit, poll, and save

Submit returns `job_id` and `status`. Reuse that ID; do not resubmit a pending job.
The [get-generation reference](https://docs.agents.lumalabs.ai/api/resources/generations/methods/get/)
defines four states. Renderhaus maps `queued` to `queued`, `processing` to `running`,
`completed` to `succeeded`, and `failed` to `failed`.
Failure results retain `failure_code` and `failure_reason`.
HTTP failures and malformed responses produce errors. A completed response without a video is an error.
Paid POSTs have no automatic retries, because a lost response does not prove that submission failed.

`get_video_task(download=True)` writes the MP4 under `RENDERHAUS_MEDIA_DIR/video/luma/`.
Task metadata lives in that directory's `.tasks/` subdirectory.
Downloads use a temporary file and atomic replacement; repeated polls reuse a saved artifact.
Studio ingests it through the existing immutable asset-version path.
Luma output URLs expire after one hour. Download promptly; polling can return a fresh URL.
An accepted job or a `dry_run` result does not prove that playable media exists.

## Configuration and costs

`LUMA_API_KEY` is the bearer credential. Store a key for the current API in the existing
`renderhaus/app` Secrets Manager JSON or the server environment.
Luma's documentation calls this credential `LUMA_AGENTS_API_KEY`; Renderhaus deliberately uses
the requested `LUMA_API_KEY` name. Legacy Dream Machine key compatibility is unverified.
`LUMA_DRY_RUN` defaults to `true`. Only `false` enables provider traffic.
Dry mode validates arguments but does not read inputs, call HTTP, or create output files.
CI explicitly forces this flag to `true`.

The existing `scripts/sync_secrets.py` accepts these keys without an allowlist change.
The provider catalog supplies the same keys to Gateway deployment tooling.
No credential is stored in source, schemas, media metadata, or browser evidence.
Deployment and live calls require separate authorization and were not performed for this change.

`server/billing_rates.py` uses the following official API SDR prices in USD, checked on 2026-10-08.
The source is [Luma API pricing](https://docs.agents.lumalabs.ai/guides/pricing/).

| Resolution | Generate 5s | Generate 10s | Modify 5s | Modify 10s | Extend |
| --- | --- | --- | --- | --- | --- |
| `360p` | $0.06 | $0.18 | $0.54 | $1.08 | Not quoted |
| `540p` | $0.15 | $0.45 | $0.72 | $1.44 | $0.15 |
| `720p` | $0.30 | $0.90 | $1.08 | $2.16 | $0.30 |
| `1080p` | $1.20 | $3.60 | $2.16 | $4.32 | $1.20 |

Image anchor generation uses the 5s generation tier. Extend always bills one 5s block.
Renderhaus adds its existing 30% platform fee, with a one-cent minimum.
Dry runs, polls, and model listing have zero provider cost and zero platform fee.
Unsupported or unpriced requests fail instead of falling through to the generic price.

The [marketing API page](https://lumalabs.ai/api) lists different amounts for some video edits.
This implementation follows the detailed API pricing reference. Confirm the account invoice rates before rollout.
Luma warns that video rates can change. Provider refunds for asynchronous failures are not automatically
reconciled to Studio balances by the existing submit/poll billing path. A partial charge for
`budget_exhausted` must not be treated as a fully refunded job.

## Output rights and training restriction

The [API terms](https://lumalabs.ai/legal/api-terms-of-use), updated 2026-04-28,
supplement the applicable enterprise or individual terms and control conflicts.
They prohibit using API outputs in training, fine-tuning, or evaluation datasets.
They require AI-output disclosure and written permission for standalone resale or white-labeling.
Attribution applies when Luma requires it in writing or an order.
They also commit Luma not to train its models on API inputs or outputs.

The [enterprise terms](https://lumalabs.ai/legal/enterprise-terms-of-service), updated 2026-04-20,
leave input and output rights with the customer as between the parties, subject to the agreement.
They do not guarantee third-party rights or output uniqueness.
The [individual terms](https://lumalabs.ai/legal/terms-of-service), updated 2026-05-14,
condition commercial output use on an active paid subscription permitting that use.
This integration does not grant broader rights than the applicable agreement and order.

Every Luma result and task record has `training_eligible=false`.
Studio persists this marker on `asset_versions`, restores it from the database when saving canvas references,
and carries it through API and canvas representations.
Derived versions inherit false from any recorded restricted source version.
Legacy and other unclassified media have unknown eligibility, represented by `null`.
No training exporter exists in this repository. Future continuity-qc dataset code must require explicit
eligibility and exclude false or unknown values. Luma outputs are never eligible for that training workflow.

## Verification limits

Offline tests cover validation, wire requests, auth, state mapping, errors, dry runs, source inspection,
media persistence, schema parity, billing, and durable training restrictions.
No paid or live generation was called. Current-account model access, generated quality, provider asset
availability, actual invoice charges, and playable live outputs remain unverified.
Comet browser E2E is blocked because this workspace has no Comet session or paid key.
See [the browser workflow](../BROWSER_E2E.md) and ignored `.renderhaus/e2e/` evidence.
