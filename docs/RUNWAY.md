# Runway provider reference

Renderhaus uses the official Runway developer API at `https://api.dev.runwayml.com/v1`.
The adapter sends `Authorization: Bearer <RUNWAYML_API_SECRET>` and
`X-Runway-Version: 2024-11-06`. It uses HTTP through the existing `httpx` dependency.

The implementation follows the [API reference](https://docs.dev.runwayml.com/api/),
[model catalog](https://docs.dev.runwayml.com/guides/models/),
[input rules](https://docs.dev.runwayml.com/assets/inputs/),
[ephemeral uploads](https://docs.dev.runwayml.com/assets/uploads/), and
[published pricing](https://docs.dev.runwayml.com/guides/pricing/), checked on 2026-10-08.
The [changelog](https://docs.dev.runwayml.com/api-details/api_changelog/) identifies
`aleph2` as the current Aleph model and says `gen4_aleph` was retired on 2026-07-30.

## Gateway tools

The Gateway target is `Runway`, the provider ID is `runway`, and the Lambda function
is `renderhaus-runway-tools`. Gateway names have the prefix `Runway___`.

| Tool | Arguments | API endpoint |
| --- | --- | --- |
| `text_to_video` | `prompt`, `duration_seconds=5`, `ratio="1280:720"`, `model="gen4.5"`, optional `seed` | `POST /text_to_video` |
| `image_to_video` | `image_path_or_url`, `prompt`, the same video options | `POST /image_to_video` |
| `video_to_video` | `video_path_or_url`, `prompt`, required `video_duration_seconds`, optional `reference_image_path_or_url`, `reference_seconds=0`, `model="aleph2"`, optional `seed` | `POST /video_to_video` |
| `text_to_image` | `prompt`, `ratio="1280:720"`, `model="gen4_image"`, optional `seed` | `POST /text_to_image` |
| `image_to_image` | `image_path_or_url`, `prompt`, `ratio="1280:720"`, `model="gen4_image"`, optional `reference_images`, optional `seed` | `POST /text_to_image` |
| `get_runway_task` | `job_id`, `download=false` | `GET /tasks/{id}` |
| `list_runway_models` | none | Local documented catalog, no HTTP request |

`image_to_image` also supports `gen4_image_turbo`. Turbo requires image references,
so `text_to_image` does not accept it. `reference_images` contains at most two extra
objects with a required `uri` and an optional `tag`. Tags contain 3-16 lowercase
letters, digits, or underscores and start with a letter. Use `@tag` in the prompt.
The required primary image counts toward the three-reference limit.

Every creation tool returns a queued `job_id`. Poll the same ID at least five seconds
apart. `PENDING` and `THROTTLED` map to `queued`, `RUNNING` to `running`, and terminal
states to `succeeded`, `failed`, or `cancelled`. A failed task includes its provider
failure code without reflected prompt or credential contents. An HTTP error fails the call without resubmitting paid work.
A 404 remains an error because the documented response does not distinguish an
unknown task from a canceled or deleted task.

The list tool reports models supported by this adapter and its source/check date.
It does not check live account availability. The official API reference does not
document a general model-list endpoint, so the adapter does not invent `/models`.

## Input limits

Contracts validate arguments before HTTP, including in dry-run mode.
Prompts must be nonblank and no longer than 1,000 UTF-16 code units.
Seeds are integers from 0 through 4,294,967,295.

Gen-4.5 durations are integer seconds from 2 through 10. Text-to-video ratios are
`1280:720` and `720:1280`. Image-to-video also supports `1104:832`, `960:960`,
`832:1104`, and `1584:672`. The input guide additionally lists `672:1584`, but the
endpoint OpenAPI does not. The adapter follows the narrower endpoint enumeration.

Aleph 2.0 edits the source video's duration and dimensions, up to 1080p.
The source must be 2-30 seconds and at most 30 FPS. `video_duration_seconds` records
the actual source duration for the quote and reference timestamp bounds. It is not
sent as an output-duration parameter. One optional guidance image becomes an Aleph
`keyframes` entry at `reference_seconds`. The API supports up to five keyframes,
relative positions, edit ranges, and outpainting, but this adapter exposes one timed
reference image to cover the requested edit workflow.

Direct Gateway tools check declared duration and URI syntax. The Studio host uses
`ffprobe` to measure each live Aleph source before quoting or submitting it. It replaces
the supplied duration with the measured value and checks the duration, frame rate,
resolution, and reference timestamp. Install `ffprobe` on the Studio host.
HTTPS Aleph inputs are captured through a pinned public-address connection without
redirects. The host measures and submits those same bytes, preserving their MIME type.
Data URI and owned inputs also use their actual bytes. External `runway://` video
handles cannot be measured and are rejected by live Studio Aleph calls. Image tools
can use those handles. Dry-run does not fetch or probe remote media.

Runway still validates codec compatibility, image properties, and moderation.
Direct Gateway callers must supply measured duration themselves. Fractional-second
invoice rounding has not been checked against a live task; billing marks that
reconciliation as a TODO.

Images support these dimensions:

- The 720p tier uses `1280:720`, `720:1280`, `720:720`, `960:720`, `720:960`, and `1680:720`.
- The 1080p tier uses `1920:1080`, `1080:1920`, `1080:1080`, `1440:1080`, and `1080:1440`.

The OpenAPI also permits older dimensions, including `1360:768` and `1024:1024`.
Their exact pricing-tier mapping is unconfirmed in the official docs. This adapter
omits those dimensions rather than assigning an invented price.

Inputs can use HTTPS domain URLs, supported base64 data URIs, or existing `runway://`
ephemeral upload handles. Arbitrary local paths are rejected. HTTPS URLs are at most
2,048 characters, have no embedded credentials, and cannot use an IP hostname.
Runway requires HEAD support, valid Content-Type and Content-Length, and no redirects.
URL assets are limited to 16 MB for images and 32 MB for videos.

Supported image data MIME types are JPEG, PNG, and WebP. Video MIME types follow the
[input guide](https://docs.dev.runwayml.com/assets/inputs/#videos). Encoded image
and Aleph video data URIs are limited to 5 MiB, including the URI prefix. The general
input guide says 16 MB for video data URIs, but Aleph's endpoint OpenAPI says 5 MiB.
The smaller limit applies here. Existing ephemeral upload handles expire after
24 hours. Studio resolves owned asset handles within the caller's workspace and uses
their stored MIME type, including for extensionless files. Small inputs become data
URIs; larger inputs use Runway's official ephemeral upload endpoint and unauthenticated
multipart storage upload, up to 200 MiB. This avoids S3 GET signatures that cannot
satisfy Runway's HEAD requirement. The integration exposes no public upload tool.
Uploads require purchased Runway credits; the official upload guide does not state a
separate upload price. No generation is submitted if preparation or upload fails.

## Output storage and Studio

Successful polls return recognized `image_url` or `video_url` fields, including
multiple output entries. Runway output URLs expire within 24-48 hours. Studio
immediately ingests those bytes into its existing workspace-owned immutable media
storage and returns durable asset references. Studio persists task ownership in its
repository and accepts polls only from the workspace that submitted the task. The original URLs remain available
for the server to ingest even when a Lambda has downloaded its own local copy.

With `download=true`, the provider also writes complete image or MP4 files under
`RENDERHAUS_MEDIA_DIR`. Local task metadata helps same-process polling, but polling
also works without that metadata after a Lambda cold start. A dry-run result never
claims that a generated file exists.

The canvas quick-add menu exposes Runway video, image-to-video, Aleph edit, image,
and reference-image nodes. Each node has its own valid default model. Model and
ratio choices follow its Gateway contract. Runway nodes poll at five-second
intervals and carry source version IDs into completed asset registration.

Only default MP4 video and standard image outputs are exposed. ProRes, HDR, PNG
sequences, Gen-4 Turbo video, and other Runway-hosted providers are outside this adapter.

## Pricing and configuration

Published developer credits cost $0.01 each, before applicable taxes.
These rates were verified on 2026-10-08 against
[Runway pricing](https://docs.dev.runwayml.com/guides/pricing/):

| Model | Provider price |
| --- | --- |
| `gen4.5` | 12 credits, $0.12 per generated second |
| `aleph2` | 28 credits, $0.28 per second, with a 56-credit minimum |
| `gen4_image` | 5 credits, $0.05 per 720p image, or 8 credits, $0.08 per 1080p image |
| `gen4_image_turbo` | 2 credits, $0.02 per image |

Renderhaus applies its existing 30% platform fee with a one-cent minimum.
Polls and the model catalog cost zero. Dry-run generation calls also cost zero.
Aleph Studio quotes use the actual measured input duration and round fractional cents
up. Direct Gateway quotes require a truthful measured duration from the caller. Actual task costs are returned by Runway but are not reconciled to these quotes.
The existing billing system refunds immediate dispatch or ingestion failures.
It does not associate a later asynchronous task failure with the original debit.
This provider follows that existing behavior; terminal-failure reconciliation remains unverified.

Satya must add `RUNWAYML_API_SECRET` to the application Secrets Manager JSON or the
local environment. Leave `RUNWAY_DRY_RUN=true` until live generation is authorized.
Only explicit `RUNWAY_DRY_RUN=false` enables live HTTP calls. The existing
`scripts/sync_secrets.py` accepts these keys without a provider-specific change.
Gateway deployment copies catalog-listed keys into Lambda environment variables,
so syncing a secret alone does not update an already-deployed Lambda.

Runway-owned input preparation does not need the existing provider-input S3 bucket.
No new AWS credential or bucket secret is introduced here. The optional separate
AgentCore runtime lacks Studio's asset resolver and shared task ownership; Runway
generation there fails before a paid submission. Use local Studio agent execution
until that runtime has the authoritative asset and task context.

Regenerate the committed schema with:

```sh
.venv/bin/python scripts/generate_gateway_schemas.py --provider runway
```

## Licence and verification status

Runway's [terms](https://runway.com/terms-of-use) govern API integration, submitted
content, and outputs. Its [attribution guide](https://docs.dev.runwayml.com/usage/attribution/)
requires the applicable interface to show "Powered by Runway" with a Runway link.
Runway node inspectors include that attribution. These are hosted API models,
not redistributed model weights. Input rights, output rights, and account-specific
terms require review before release; this integration makes no licence guarantees.

Offline tests cover requests, contracts, auth headers, state mapping, error handling,
dry-run, local downloads, Gateway/Lambda dispatch, billing, and Studio media ingestion.
They make no network or paid provider calls.

Comet browser E2E is blocked in this environment because there is no controllable
Comet session or paid Runway key, and live calls are forbidden for this task.
No live generation, account access, actual provider media playback, moderation,
invoice reconciliation, or deployed Lambda/Gateway behavior has been verified.
