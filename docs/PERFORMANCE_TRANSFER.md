# Performance transfer

Performance transfer uses Runway Act-Two for facial and upper-body acting, with Kling 3 Pro
Motion Control on fal for full-body movement. Selection is explicit request, then exception,
then default. No tier, price ranking or project confidentiality rule changes selection.
The existing generation tools stay explicit-only. Their code is retained.

## Tools and contracts

| Gateway tool | Canonical ID | Inputs and controls | Poll |
| --- | --- | --- | --- |
| `Runway___act_two` | `runway_act_two` | `character_uri`, `performance_uri`, measured `performance_duration_seconds` 3-30, `subjects`, `consent_confirmed=true`; `character_type=image/video`, pixel `ratio`, `body_control`, `expression_intensity` 1-5, optional seed | `Runway___get_runway_task` |
| `Fal___kling_motion_control` | `kling_motion_control` | `image_url`, `video_url`, measured `performance_duration_seconds` 3-30, `subjects`, `consent_confirmed=true`; `character_orientation=video/image`, `keep_original_sound`, optional prompt | `Fal___get_video_task` |

Studio direct invocation refuses both tools with HTTP 409, directing users to the agent
workflow so consent and cost approval cannot be bypassed.

Strict Pydantic contracts run at direct-provider, Gateway and agent selection boundaries before
paid submission. Booleans do not satisfy numeric fields. Nonfinite numbers, unknown fields,
unsupported controls and missing consent fail before network access. Consent covers all real
faces, voices and bodies in the character and driving media. The acknowledgement is a caller
attestation, not identity verification. No vendor-specific recorded-consent endpoint was found
for either exposed API. Do not invent one or treat payment approval as performer consent.

Act-Two posts `model=act_two` to `POST /v1/character_performance`, with `character={type,uri}`,
`reference={type:video,uri}`, `ratio`, `bodyControl`, `expressionIntensity` and optional `seed`.
There is no duration field in the vendor body. The measured performance duration supports
validation and pricing. Supported ratios are 1280:720, 720:1280, 960:960, 1104:832, 832:1104 and
1584:672. The Help page describes 24 FPS output and gesture control for character images.
Character video retains its own body/camera movement; use `body_control=false` for video.

Fal posts to `fal-ai/kling-video/v3/pro/motion-control`. Video orientation supports 3-30s;
image orientation supports only 3-10s. Output shape is `video.url`. The adapter exposes no
facial element binding, standard mode or direct Kling API. Direct Kling Motion Control
endpoint, price and regional access remain **UNVERIFIED**. No direct Motion Control request
can be made through this branch.

Both tools always pause with a cost estimate in autonomous and interactive runs, even if
`RENDERHAUS_PREMIUM_VIDEO_APPROVAL=false`. Polling is free and never creates another paid job.
The approval description identifies subjects, consent, provider, model, selection reason and
price. Existing approval exemptions and the autonomous spending cap are unchanged.

## Long performances

The installed [act-two skill](../agent/deep_agent/skills/act-two/SKILL.md) owns the sequential
workflow. Supply known shot or silence boundaries and split the take into contiguous 3-30s
chunks. A whole source over 30s cannot be sent directly to Act-Two. Each `act_two` call can
prepare one segment from the original hosted source using `source_duration_seconds`,
`performance_start_seconds`, `performance_duration_seconds` and `boundary_kind=shot/silence`.
A segment must fit within the declared source. The adapter measures source duration with
ffprobe, trims with ffmpeg, verifies the actual segment length and publishes the MP4 as a Runway data URI or official ephemeral upload
before its paid request. Known boundaries are supplied by the operator or agent from source
metadata; automatic shot/silence detection is not implemented.

Process one approved chunk to completion before requesting the next. The executor blocks a
new chunk while an accepted Act-Two task is queued or running. Save offsets, durations, job
IDs and local outputs in an agent manifest, without signed URLs. After all chunks succeed,
assemble ordered `output_path` visuals with `Remotion___render_timeline` and cumulative
`start_seconds`. Poll `Remotion___get_render_progress` and inspect the final saved MP4.
The existing render path supports concatenation, so this adapter does not create a second
aggregate job/poll protocol or submit hidden paid children from a free poll.

Live segment preprocessing needs system ffmpeg/ffprobe and an exact source
host in `REMOTION_LOCAL_MEDIA_HOSTS`. Missing dependencies or mismatched measured lengths
refuse processing before paid submission. The existing downloader limits source bytes and
blocks private-address hosts and redirects. Runway upload/data URIs support short clips,
but cannot be locally segmented. Runway ephemeral uploads expire after 24 hours. GET-presigned S3 links do not support
Runway's required HEAD request and are not used for chunks. This branch adds no deployment.

## Official evidence, read 2026-10-09

| Contract | Source | Verified result |
| --- | --- | --- |
| Runway endpoint and request schema | [official API](https://docs.dev.runwayml.com/api/), [official SDK resource](https://github.com/runwayml/sdk-python/blob/main/src/runwayml/resources/character_performance.py), [official generated types](https://github.com/runwayml/sdk-python/blob/main/src/runwayml/types/character_performance_create_params.py) | `act_two`, image/video character, 3-30s reference, ratio and controls |
| Runway chunk publication | [inputs](https://docs.dev.runwayml.com/assets/inputs/), [uploads](https://docs.dev.runwayml.com/assets/uploads/) | HEAD required for HTTPS; reuse data URIs or 24-hour ephemeral uploads |
| Runway performance characteristics | [Act-Two Help](https://help.runwayml.com/hc/en-us/articles/42311337895827-Performance-Capture-with-Act-Two) | 30s cap, 24 FPS, gestures with images, same-pose guidance |
| Runway price | [developer pricing](https://docs.dev.runwayml.com/guides/pricing/) | 5 credits/s, $0.01/credit = $0.05/s, 3s minimum |
| Kling fal endpoint and request | [official fal API page](https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control/api) | Pro Motion Control schema and orientation limits |
| Kling fal price and commercial label | [official fal model page](https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control) | $0.168/s, commercial use, partner endpoint |
| Act-Two licence | [Runway Terms](https://runway.com/terms-of-use) | Proprietary service terms, commercial output allowed under terms; competing product/training restriction |
| Kling fal licence | [fal Terms](https://fal.ai/legal/terms-of-service), [API supplemental terms](https://fal.ai/legal/api-services) | Proprietary commercial hosted API, input rights/permissions required; no accepted output-training grant |

Both models have `license=service-terms`, `weights_license=closed-weights` and
`training_eligible=false` in provider and canonical model policies. The Runway Terms allow
vendor use of inputs/outputs for improving models. That is distinct from Renderhaus output
training rights. No non-commercial weights, AGPL code or third-party skill implementation
was copied. US access uses Runway direct and fal; account activation was not checked.

Published prices support approval quotes including the existing platform fee. For a 5s clip,
Runway is 25 provider cents / 33 total cents; fal Kling is 84 / 109. Dry-run dispatch charges
zero but the approval estimate retains the published price. Fractions round up provider cents
for estimates. Actual fractional charges, taxes, negotiated rates, preprocessing/upload/storage
and Remotion compute remain separate and require invoice reconciliation. No price was taken
from a third-party listing.

## Configuration and validation limits

No new dry-run flag, model env variable or secret is introduced. Existing `RUNWAY_DRY_RUN`
and `FAL_DRY_RUN` default true. Runway uses `RUNWAYML_API_SECRET`; Motion Control uses `FAL_KEY`.
Chunk preprocessing reuses `REMOTION_LOCAL_MEDIA_HOSTS`; provider deployment
configuration and `sync_secrets` retain these keys without printing values.

Seven routing rows are activated, giving 113 active of 129 retained rows, with 16 skipped.
The remaining rows depend on image specialists, Mirelo, cutaway capture, Gemini QC evaluation,
NLE import, HyperFrames overlays, or commercially blocked/unverified extension behavior. Exact reasons stay
in `tests/fixtures/skill_routing.json`. Provider/tool/skill inventory is 14/107/24.

Offline tests cover requests, consent failures, default/exception/explicit routing, native
Deep Agents approve/reject resume, no hidden poll submissions, real local segment trimming
and concatenation. Public docs were read; no paid provider or real planning-model API was
called. Comet is unavailable in this workspace. Browser E2E and live artifact quality remain
blocked, never passed. The ignored receipt is `.renderhaus/e2e/performance-transfer.json`.

See [decisions](perf-transfer-decisions.tsv) for the design and remaining TODOs.

## Recorded offline checks

On 2026-10-09, Ruff passed; the full unittest suite ran **1220 tests, 18 skipped**;
`ci_check.py` passed with all requested dry-run environment flags; and Studio `tsc --noEmit -p .`
passed. The temporary `node_modules` link was removed. Fifteen new performance tests include
mocked provider HTTP/queues, consent/duration failures, routing, autonomous approve/reject,
manual Studio approval bypass refusal, sequential chunk gating, upload preparation and an actual
40s local source split into two 20s clips with verified concat duration and red/blue visual order.
An existing concurrent billing test hit contention on the first full run, then passed both in
isolation and in the final full run; no unrelated billing logic was changed.

The seven activated fixtures comprise five Act-Two rows and two Kling Motion Control rows.
The sixteen remaining skipped rows are:

| Canonical/workflow ID | Rows | Reason |
| --- | ---: | --- |
| `mirelo_v2a` | 3 | Provider pending (`feat/sfx-mirelo`) |
| `recraft_v41_vector` | 4 | Provider pending (`feat/image-specialists`) |
| `ideogram45_edit` | 2 | Provider pending (`feat/image-specialists`) |
| `cutaway_record` | 3 | Capture provider pending (`feat/product-demo-capture`) |
| `gemini_vlm_judge` | 1 | VLM judge pending; local QC remains default |
| NLE import | 1 | FCPXML import pending; existing export is not import |
| HyperFrames overlays | 1 | Overlay behavior pending |
| `wan3_extend` | 1 | Wan preview licence blocks live; Seedance appended-versus-combined length unverified |

Short, unsegmented clip duration is a caller-measured contract input. These wrappers do not
probe remote short clips; only source segments are measured locally. Vendor billing based on
actual media duration and fractional rounding still needs authorized invoice reconciliation.
The direct Kling API remains UNVERIFIED and unexposed. Account/model access, live media quality,
known-boundary selection and deployed ffmpeg/upload readiness remain unverified. Browser E2E
is **blocked** because Comet is unavailable and live provider calls are prohibited in this task.

## Changed files

- Provider modules, contracts and registry: `providers/catalog.py`, `providers/contracts.py`, `providers/fal/api.py`, `providers/fal/motion.py`, `providers/registry.py`, `providers/runway/api.py`, `providers/runway/contracts.py`, `providers/runway/inputs.py`, `providers/runway/performance.py`, `providers/runway/segments.py`.
- Routing, approvals and skills: `agent/deep_agent/routing.py`, `agent/deep_agent/routing_policy.json`, `agent/deep_agent/runner.py`, `agent/deep_agent/skills/act-two/SKILL.md`, `agent/gateway_executor.py`.
- Generated Gateway schemas: `configs/gateway/fal.tools.json`, `configs/gateway/runway.tools.json`.
- Billing, input publication and Studio: `server/billing_rates.py`, `server/runway_inputs.py`, `server/studio.py`, `server/studio_options.py`.
- Studio model labels and tool definitions: `studio/lib/canvas/model-labels.ts`, `studio/lib/canvas/tool-registry.ts`.
- Provider, workflow and routing tests: `tests/fixtures/skill_routing.json`, `tests/test_fal_provider.py`, `tests/test_performance_transfer.py`, `tests/test_performance_workflow.py`, `tests/test_runway_inputs.py`, `tests/test_runway_provider.py`, `tests/test_skill_routing.py`.
- Provider and routing documentation: `docs/CAPABILITY_MAP.md`, `docs/DEEP_AGENT.md`, `docs/PERFORMANCE_TRANSFER.md`, `docs/SKILLS.md`, `docs/perf-transfer-decisions.tsv`, `docs/provider-ladder-decisions.tsv`, `docs/skills-drafts/act-two.md`, `docs/skills-drafts/runway.md`.
- CI and secret synchronization: `scripts/ci_check.py`, `scripts/sync_secrets.py`.
- Deployment inventory: `.github/workflows/deploy.yml`.
- Container inventory: `Dockerfile.agentcore`.
