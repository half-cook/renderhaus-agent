# fal Wan VACE provider

The `fal` Gateway target exposes Wan 2.1 VACE 14B and Wan 2.2 VACE Fun A14B.
The provider submits one queue request and returns a job handle. Each poll checks
status once and fetches a result only after completion. It never resubmits a job.
All contracts and pricing below were checked against public official pages on
2026-10-08. Live API behavior and account access have not been verified.

## Tools and arguments

Gateway names use the `Fal___` prefix. Local dispatch uses provider `fal` and the
unprefixed tool names below.

| Tool | Required arguments | Additional arguments |
| --- | --- | --- |
| `text_to_video` | `prompt` | Shared generation settings |
| `image_to_video` | `first_frame_url`, `prompt` | Shared settings, `last_frame_url` |
| `reference_to_video` | `ref_image_urls`, `prompt` | Shared settings, `first_frame_url`, `last_frame_url` |
| `video_to_video` | `video_url`; `prompt` except for reframe | Shared settings, `edit_mode`, `task`, masks, references, frames, control and geometry fields below |
| `get_video_task` | `job_id` | `download=false` |
| `list_fal_models` | None | None |

Shared settings are `model`, `num_frames=81`, `frames_per_second=16`,
`resolution="720p"`, `aspect_ratio="16:9"`, `negative_prompt`, and `seed`.
The default model is `fal-ai/wan-vace-14b`. The other model is
`fal-ai/wan-22-vace-fun-a14b`. Models select the family; `edit_mode` selects the
native route for video editing.

The documented frame count range is 81 through 241. Playback FPS ranges from 5
through 30. Resolution choices are `auto`, `240p`, `360p`, `480p`, `580p`, and
`720p`. Aspect ratios are `auto`, `16:9`, `1:1`, and `9:16`. Reference inputs are
lists of strings. fal publishes no reference-count limit on these API pages;
the adapter does not invent one. Subject consistency is a model capability,
not a guarantee that a reference will remain identical in every frame.

`video_to_video` accepts these endpoint-specific fields.

| `edit_mode` | Extra fields and requirements |
| --- | --- |
| `freeform` | Requires explicit `task` from `depth`, `pose`, `inpainting`, `outpainting`, `reframe`. Accepts `ref_image_urls`, first/last frames, `preprocess`, and one mask for `task="inpainting"`. Uses the family root endpoint. |
| `inpainting` | Requires one of `mask_video_url` or `mask_image_url`. Accepts references, first/last frames, and `preprocess`. |
| `outpainting` | Requires at least one of `expand_left`, `expand_right`, `expand_top`, `expand_bottom`. Accepts `expand_ratio` from 0 through 1, references, and first/last frames. |
| `reframe` | Accepts `zoom_factor`, `trim_borders`, and first/last frames. `prompt` may be omitted. References, masks, and `preprocess` are unsupported on this route. |
| `depth` | Default edit mode. Accepts references, first/last frames, and `preprocess`. |
| `pose` | Accepts references, first/last frames, and `preprocess`. |

First/last frames use `first_frame_url` and `last_frame_url`. References use
`ref_image_urls`. Omit fields that the selected endpoint does not support.
The adapter rejects both masks together because fal documents different mask
precedence on its freeform and inpainting pages.

The adapter sends `match_input_num_frames=false` and
`match_input_frames_per_second=false`, including for reframe. This keeps the
requested length and the billing quote independent of unknown source duration.
It leaves unexposed sampling and quality controls at fal's documented defaults.

## Endpoint sources

Text, image, and reference generation use the documented freeform inputs
`prompt`, `first_frame_url`, and `ref_image_urls`. Separate text/image/reference
VACE route IDs were not confirmed and are not invented by this adapter.

| Mode | Wan 2.1 API | Wan 2.2 API |
| --- | --- | --- |
| Freeform | [wan-vace-14b](https://fal.ai/models/fal-ai/wan-vace-14b/api) | [wan-22-vace-fun-a14b](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/api) |
| Inpainting | [inpainting](https://fal.ai/models/fal-ai/wan-vace-14b/inpainting/api) | [inpainting](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/inpainting/api) |
| Outpainting | [outpainting](https://fal.ai/models/fal-ai/wan-vace-14b/outpainting/api) | [outpainting](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/outpainting/api) |
| Reframe | [reframe](https://fal.ai/models/fal-ai/wan-vace-14b/reframe/api) | [reframe](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/reframe/api) |
| Depth | [depth](https://fal.ai/models/fal-ai/wan-vace-14b/depth/api) | [depth](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/depth/api) |
| Pose | [pose](https://fal.ai/models/fal-ai/wan-vace-14b/pose/api) | [pose](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/pose/api) |

## Queue, secrets, and persistence

The [official queue documentation](https://docs.fal.ai/model-apis/model-endpoints/queue)
defines submission to `https://queue.fal.run/<endpoint-id>` with
`Authorization: Key <FAL_KEY>`. The adapter uses the app-root status/result
routes implemented by the [official Python client](https://github.com/fal-ai/fal/blob/main/projects/fal_client/src/fal_client/client.py).
`IN_QUEUE` maps to `queued`, `IN_PROGRESS` to `running`, and a completed result
with `video.url` to `succeeded`. Completed errors map to `failed`. Unknown states,
authentication errors, rate limits, and malformed responses fail the tool call.
Result HTTP 400/422 responses map to failed jobs. No POST retries occur.

`FAL_DRY_RUN` defaults to `true`. Only the explicit value `false`, ignoring case,
enables HTTP. Dry runs make no queue or download requests and cost zero.
`list_fal_models` is a static documented catalog and never calls fal, even in
live mode. It does not establish account-level access.

Add `FAL_KEY` to the existing application Secrets Manager JSON or the local
process environment. Add `FAL_DRY_RUN=true` while preparing deployment.
The existing `scripts/sync_secrets.py` accepts both keys without modification;
the provider catalog includes them for Gateway Lambda environment injection.
Do not expose the key to Studio or put it in source control. No secrets were
added or synced as part of this branch.

Job handles contain `<endpoint-id>:<request-id>`. Poll with the entire handle,
including after a Lambda cold start. Completed results expose `video_url` for
the existing Studio managed-asset ingestion path. `download=true` also saves
the MP4 under `RENDERHAUS_MEDIA_DIR/video/`. Task metadata uses
`video/.tasks/fal/`. Each file name hashes the handle. Temporary downloads are
unique per call, and metadata replacements are atomic. A Lambda-local path is
not a durable Studio URL; the normalized `video_url` remains available.

## Published pricing

Prices are USD per video second, with **video seconds calculated as
`num_frames / 16`**. Requested playback FPS does not change this unit. Quotes
round provider cost to integer cents, then add the existing 30% platform fee
with its one-cent minimum. Polling and catalog calls are free.

| Endpoints | 480p | 580p | 720p | Official source, checked 2026-10-08 |
| --- | --- | --- | --- | --- |
| Wan 2.1 freeform and all five edit routes | $0.04 | $0.06 | $0.08 | [Wan VACE 14B](https://fal.ai/models/fal-ai/wan-vace-14b) and the corresponding route pages |
| Wan 2.2 inpainting, outpainting, reframe, depth | $0.05 | $0.075 | $0.10 | [inpainting](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/inpainting), [outpainting](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/outpainting), [reframe](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/reframe), [depth](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/depth) |

TODO: [Wan 2.2 freeform](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b)
has pending compute-second pricing, without a confirmed generation rate.
TODO: [Wan 2.2 pose](https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/pose)
shows a 720p billing message of $0.10 per video second, while the official page's
embedded `endpointBilling` metadata reports $0.15 per second. Both combinations
remain blocked for live submission pending clarification. Their contracts can
be inspected and exercised in dry run. `auto`, `240p`, and `360p` also lack
published rates and remain blocked for live submission. No rate is interpolated.

## Training eligibility and verification limits

The provider catalog, submit results, poll results, and task records carry
`training_eligible=true` and `weights_license="Apache-2.0"`. These fields mark
provider outputs eligible for the continuity-QC training flywheel. The existing
tool-result ledger retains them without an asset database migration.
Weight licence sources are the [official VACE repository](https://github.com/ali-vilab/VACE)
and [Alibaba-PAI model card](https://huggingface.co/alibaba-pai/Wan2.2-VACE-Fun-A14B).
fal's [hosted-service Terms of Service](https://fal.ai/legal/terms-of-service)
still apply. Weight licensing is not a replacement for those terms.

Offline HTTP tests cover validation, request shapes, authentication, state/error
mapping, cold starts, artifact persistence, concurrency, dry run, and billing.
CI forces `FAL_DRY_RUN=true`. The real fal API, output playback, and Comet Studio
flow remain unverified because this environment has no Comet session or paid
keys, and this task forbids live API calls.
