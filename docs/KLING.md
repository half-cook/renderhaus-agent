# Kling provider reference

Kling uses the official API directly. The Gateway target is `Kling`, backed by
`renderhaus-kling-tools`. It exposes asynchronous submission and polling tools.
`KLING_DRY_RUN` defaults to `true`. Only the explicit value `false` permits HTTP
requests. CI forces it to `true`.

## Tools

Gateway names have the `Kling___` prefix. The argument names below are the public
Renderhaus contract, translated into the official API format.

| Tool | Arguments |
| --- | --- |
| `text_to_video` | Required `prompt`. Optional `duration_seconds`, `aspect_ratio`, `resolution`, `model`, `generate_audio`, `multi_shot`, `shots`. |
| `image_to_video` | Required `image_path_or_url`, `prompt`. Optional `end_image_path_or_url`, `duration_seconds`, `resolution`, `model`, `generate_audio`, `multi_shot`, `shots`, `elements`. |
| `omni_video` | Required `prompt`. Optional `reference_images`, `elements`, `image_path_or_url`, `end_image_path_or_url`, `duration_seconds`, `aspect_ratio`, `resolution`, `generate_audio`, `multi_shot`, `shots`. |
| `get_video_task` | Required `job_id`. Optional `download`, default `false`. |
| `list_kling_models` | No arguments. Returns the documented model catalog without HTTP calls. Account activation is unverified. |

The normal defaults are 5 seconds, 720p, silent audio, and a single shot.
Text and Omni generation default to 16:9. Image generation derives its ratio from
the source image. The text and image tools select `KLING_MODEL`, defaulting to
`kling-3.0`. Omni uses `kling-3.0-omni`.

`shots` is an array of objects with `prompt` and `duration_seconds`. Each shot
lasts at least one second. One through six shots are supported, and their
combined duration must equal `duration_seconds`. Shot prompts have a 512-character
limit. Use `multi_shot=true` with explicit shots, or with a prompt that lets the
provider choose the shots. Current API requests serialize explicit shots as
`shot n, m, words;`. Legacy requests use `multi_prompt`.

`reference_images` contains image URLs or local image paths. `elements` contains
objects with `element_id`, `id`, and `element_type`. The type is
`multi_image_elements` or `video_character_elements`. It is local validation
metadata, omitted from the official request. Current prompts refer to images as
`@image_1` and elements as `@<id>`. Legacy prompts use the ordinal tokens
`<<<image_1>>>` and `<<<element_1>>>`; the current alias is not sent in legacy
requests. Obtain element IDs from Kling's
existing element library. Element creation is outside this integration.

## Authentication and endpoints

The [official authentication documentation](https://kling.ai/document-api/api/get-started/authentication)
distinguishes current and legacy API designs. Checked on 2026-10-08.

| Setting | Meaning |
| --- | --- |
| `KLING_API_STYLE=current` | Default. Uses `KLING_API_KEY` as a bearer key. |
| `KLING_API_STYLE=legacy` | Uses `KLING_ACCESS_KEY` and `KLING_SECRET_KEY` to sign an HS256 JWT for each request. The issuer is the access key, expiry is 30 minutes, and not-before is five seconds before the current time. |
| `KLING_BASE_URL` | Defaults to `https://api-singapore.klingai.com`, the documented domain for servers outside China. |
| `KLING_MODEL` | Defaults to `kling-3.0`. `kling-3.0-turbo` is supported by the current text and image APIs. |
| `KLING_DRY_RUN` | Defaults to `true`. Dry runs do not authenticate, submit, poll, download, or manufacture playable media. |

Credentials are read from environment variables, then the JSON secret selected
by `RENDERHAUS_SECRETS_ARN` or `RENDERHAUS_SECRETS_NAME`. Lambda deployment keeps
Kling credentials in Secrets Manager instead of copying them into Lambda
configuration. `scripts/sync_secrets.py` already syncs arbitrary application keys;
it needs no Kling-specific code. Do not store a precomputed JWT.

Current endpoints are `POST /text-to-video/kling-3.0`,
`POST /image-to-video/kling-3.0`, and `POST /omni-video/kling-3.0-omni`.
Turbo substitutes `kling-3.0-turbo` in the text or image endpoint.
Polling uses `GET /tasks` with `task_ids`.

Legacy endpoints are `POST /v1/videos/text2video`,
`POST /v1/videos/image2video`, and `POST /v1/videos/omni-video`.
The corresponding GET endpoint includes the task ID. Legacy model IDs are
`kling-v3` and `kling-v3-omni`. Public model IDs stay the same across API styles.
Turbo has no confirmed legacy endpoint.

The returned `job_id` encodes the API style and task kind. Pass it unchanged to
polling, even after a Lambda cold start. Polling maps provider states to
`queued`, `running`, `succeeded`, or `failed`.
With `download=true`, completed MP4s are saved beneath
`RENDERHAUS_MEDIA_DIR/video`. Studio registers the returned media through the
existing asset ingestion path. Official output URLs expire; persist successful
results promptly.

## Documented limits and deliberate omissions

Kling 3.0 and Omni accept 3 through 15 seconds and 720p, 1080p, or `4k`.
Text and Omni aspect ratios are 16:9, 9:16, or 1:1. Normal current prompts have
a 3072-character limit. Turbo image prompts have a 2500-character limit.

Current images must be JPEG or PNG, no larger than 50 MB. Legacy images have a
10 MB limit. Both formats require at least 300 pixels in each
dimension, with a ratio between 1:2.5 and 2.5:1. Remote image dimensions and bytes
are enforced by the provider; Renderhaus does not fetch remote inputs to inspect
them before submission.

Image-to-video accepts a start frame and an optional end frame, with up to three
elements. Omni accepts multiple image references and existing elements. Without
video-character elements, the combined reference image and multi-image element
limit is seven. With video-character elements, that combined limit is four,
and at most three video-character elements are supported. Frame-driven Omni
requests accept at most three elements.

Turbo supports only 720p and 1080p. Its current image schema exposes a first
frame, but no end frame, elements, or audio control. Undocumented request fields
are rejected. Its pricing table lists native audio, but default audio behavior
cannot be confirmed from the request reference. Billed Turbo requests remain
blocked pending that confirmation.

This integration covers video generation. It does not expose Omni image
editing, element creation, voice customization, motion control, reference-video
editing, callbacks, or blocking wait tools. No account entitlement or live
response has been verified.

Official request references are the [3.0 text API](https://kling.ai/document-api/api/video/3-0-omni/text-to-video),
[3.0 image API](https://kling.ai/document-api/api/video/3-0-omni/image-to-video),
[Omni API](https://kling.ai/document-api/api/video/3-0-omni/video-omni), and
[Turbo text API](https://kling.ai/document-api/api/video/3-0-turbo/text-to-video).
The respective `/legacy` pages document legacy request shapes.

## Published pricing

The [official API pricing table](https://kling.ai/document-api/pricing/base/video)
provides these USD list prices per second, checked on 2026-10-08.

| Model and audio | 720p | 1080p | 4K |
| --- | ---: | ---: | ---: |
| 3.0, silent | $0.084 | $0.112 | $0.42 |
| 3.0, native audio without voice control | $0.126 | $0.168 | $0.42 |
| Omni without reference video, silent | $0.084 | $0.112 | $0.42 |
| Omni without reference video, native audio | $0.112 | $0.14 | $0.42 |
| Turbo, native audio | $0.112 | $0.14 | Not listed |

Billing multiplies the applicable rate by the requested duration, rounds once
to integer provider cents, and adds Renderhaus's existing 30% platform fee with
a one-cent minimum. Polling and model discovery are free. Dry runs are free.
Turbo has a marked TODO because its audio behavior is unresolved. There is no
invented silent Turbo price or operator quote fallback. Account discounts and
actual invoices are unverified.

## Licence and validation status

The [API paid-service terms](https://kling.ai/document-api/guides/protocols/paid-service),
effective 2026-04-21, permit commercial use of generated content. Sections 6.3
and 6.4 condition ownership on lawful input rights and applicable law, and leave
infringement responsibility with the user. Sections 3.8 and 10.3 restrict key
sharing and licensing or reselling API access without written consent. Output
rights do not establish permission to resell the API service.

Offline tests mock HTTP and cover contracts, requests, authentication, polling,
errors, downloads, dry runs, and billing. Live API calls, account entitlements,
and playback remain unverified. Comet browser E2E is blocked in this environment
because there is no controllable session or paid provider credential. No paid
request is authorized for this task.
