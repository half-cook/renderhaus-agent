# Seedance 2.5 provider reference

Seedance 2.5 is the synthetic-character dialogue exception for text, image and reference video.
Wan 3.0 remains the capability default. Seedance also supplies the declared edit and extend
interims while Wan's Model Studio preview licence blocks commercial use.

The adapter keeps the `Seedance` Gateway target and reuses fal's queue client and poll implementation.
There are no new provider targets or new dry-run flags. All documented source reads below are
2026-10-09. No authenticated provider request was made during this upgrade.

## Gateway tools

| Gateway name | Canonical ID | Main arguments |
| --- | --- | --- |
| `Seedance___text_to_video` | `seedance25_t2v` | `prompt`, `duration_seconds`, `aspect_ratio`, `resolution`, `generate_audio` |
| `Seedance___image_to_video` | `seedance25_i2v` | `image_path_or_url`, `prompt`, optional `end_image_path_or_url`, measured `source_aspect_ratio` |
| `Seedance___reference_to_video` | `seedance25_r2v` | `prompt`, `reference_image_urls`, `reference_video_urls`, `reference_audio_urls`, matching measured durations and video fps |
| `Seedance___edit_video` | `seedance25_edit` | `video_url`, `prompt`, measured `source_duration_seconds`, `source_fps`, `source_aspect_ratio` |
| `Seedance___extend_video` | `seedance25_extend` | Source fields above, `duration_seconds`, continuation intent in `prompt` |
| `Seedance___get_video_task` | Free poll | Saved `job_id`, `download`; delegates fal handles to the existing fal poll |
| `Seedance___list_seedance_models` | Free catalog | Offline supported model catalog |

Common generation controls include a configurable `model`, native audio enabled by default,
and `real_face_refs` plus `user_supplied_real_person_refs` as local refusal flags.
Seedance 2.5 supports 4-30 output seconds at 480p, 720p and 1080p. The selectable
BytePlus `seedance-1-5-pro-251215` supports only text/image video at 4-12 seconds.
Gateway schemas come from the handler signatures and central argument contracts.
Handlers also validate direct calls before dry-run preview or paid submission.

For reference requests, fal supports 30 images, 10 videos and 10 audio files, with 50 total files.
Videos and audio are each 1.8-30.2 seconds and each type totals at most 30.2 seconds.
Video frame rates are 24-60 fps. Local measured fields never enter the vendor request.
BytePlus uses its stricter documented 2-30 second reference limits.
Edit sources are 4-30 seconds; extension sources are 2-30 seconds.
Editing preserves approximate duration and source aspect.
The vendor can shorten an edit by about 0.4 seconds. Extension preserves source aspect.
Extension output seconds are an output request; the adapter does not promise concatenation
or that the output contains the entire original source. Artifact inspection remains required.
Requests to "extend by N seconds" are refused until appended-versus-combined semantics are
verified. Specify the desired generated output duration instead; generic extension remains available.

Fal request fields are `image_url`/`end_image_url` for image video and
`image_urls`/`video_urls`/`audio_urls` for references. The reference endpoint's `task` is
`reference`, `editing` or `extension`. Editing uses automatic duration and aspect ratio.
BytePlus uses `content` items with `first_frame`, `last_frame`, `reference_image`,
`reference_video` or `reference_audio` roles and `omni_reference_task_type` for edit/extend.
Its edit requests use `duration=-1` and `ratio=adaptive`.
Seedance 2.5 image generation also uses adaptive output aspect on both hosts. BytePlus 1.5
still accepts a fixed output ratio, which is used for its quote. The
[current BytePlus task schema](https://docs.byteplus.com/zh-CN/docs/modelark/create-video-generation-task-api?redirect=1)
confirms both this distinction and 1.5 support for 1080p.

Verified official model and schema sources are the
[fal text API](https://fal.ai/models/bytedance/seedance-2.5/text-to-video/api),
[fal image API](https://fal.ai/models/bytedance/seedance-2.5/image-to-video/api),
[fal reference API](https://fal.ai/models/bytedance/seedance-2.5/reference-to-video/api),
[fal US reference API](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video/api),
and [BytePlus task API](https://docs.byteplus.com/ja/docs/modelark/create-video-generation-task-api).
The [BytePlus 2.5 tutorial](https://docs.byteplus.com/zh-TW/docs/modelark/seedance-2-5)
documents editing and extension constraints. Public localized BytePlus pages are used where
the English renderer only returned a JavaScript shell.

## Transport and credentials

| Setting | Default | Meaning |
| --- | --- | --- |
| `SEEDANCE_TRANSPORT` | `fal` | `fal` or optional `byteplus` |
| `SEEDANCE_FAL_REGION` | `us` | US-hosted `/us/` endpoints or `global` endpoints |
| `SEEDANCE_MODEL` | `dreamina-seedance-2-5-260628` | Configurable model; unknown IDs remain UNVERIFIED and dry-run only |
| `SEEDANCE_DRY_RUN` | `true` | Blocks Seedance generation and polling network calls |
| `FAL_DRY_RUN` | `true` | Also blocks Seedance calls when transport is fal |
| `FAL_KEY` | Unset | Existing fal secret, reused by the Seedance Lambda |
| `BYTEPLUS_API_KEY` | Unset | Optional BytePlus secret; wins over existing `ARK_API_KEY` alias |
| `BYTEPLUS_BASE_URL` | `https://ark.ap-southeast.bytepluses.com/api/v3` | Optional direct host |
| `SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED` | `false` | Operator assertion of the required written platform authorization; never grants US availability |
| `RENDERHAUS_CUSTOMER_REGION` | Unset | BytePlus live use requires a known permitted non-US customer region; US or unknown regions are blocked |

Both Seedance and fal dry-run flags must be false for fal live work. Dry-created handles
stay previews after flags change. The job handle records its actual endpoint, so polling
uses the saved host even if the operator changes transport defaults later.

The [official availability list](https://docs.byteplus.com/en/docs/ModelArk/availability)
includes Canada and omits the US. It excludes Restricted Models and requires purchase-time
confirmation. BytePlus direct is not available to US customers or US end users.
Fal explicitly offers [US text](https://fal.ai/models/bytedance/seedance-2.5/us/text-to-video),
[US image](https://fal.ai/models/bytedance/seedance-2.5/us/image-to-video/api) and US reference
endpoints. The US default is a Renderhaus choice; no official requirement that every US
customer must use `/us/` instead of global was verified. Canada can use fal too.

Add configuration and secrets through environment variables or the existing Secrets Manager
bootstrap. `scripts/sync_secrets.py` accepts application keys without a provider allowlist.
Populate `FAL_KEY` for the default host. Add `BYTEPLUS_API_KEY` only for the optional authorized
non-US route. Keep values out of chat, tracked files and test reports. This task did not sync,
read or write credentials, push, deploy or call live provider APIs.

## Pricing and estimates

The following are list rates in USD per million video tokens, read 2026-10-09.

| Host/model | 480p/720p without video | 1080p without video | With video input |
| --- | --- | --- | --- |
| fal global Seedance 2.5 | 21.40 | 23.40 | Multiply the input-plus-output token cost by 0.6 |
| fal US Seedance 2.5 | 25.68 | 28.08 | Multiply the input-plus-output token cost by 0.6 |
| BytePlus Seedance 2.5 | 10.70 | 11.70 | 6.40 at 480p/720p; 7.00 at 1080p |
| BytePlus Seedance 1.5 Pro | 2.40 with audio; 1.20 silent | Same | References unsupported by this adapter |

Official pricing sources are the [fal global reference model](https://fal.ai/models/bytedance/seedance-2.5/reference-to-video),
[fal US reference model](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video),
and [BytePlus pricing](https://docs.byteplus.com/id/docs/modelark/model-pricing?redirect=1).
The US markup is 20%. No map lead or expired promotion overrides the verified host rate.

The documented estimated token formula is
`(input_video_seconds + output_video_seconds) * output_width * output_height * 24 / 1024`.
Image and audio references do not add input-video tokens. Output dimensions use the requested
resolution and known aspect ratio. Adaptive output needs measured `source_aspect_ratio` for
image/edit/extend quotes; absent measurements produce an unknown quote. Estimates include
Renderhaus's existing platform fee and round provider cents upward. BytePlus actual usage is
`usage.completion_tokens`, which can differ from the estimate. BytePlus video inputs also have
a documented minimum-token floor whose linked table was inaccessible. Those direct video-input
quotes are UNVERIFIED and remain unknown/dry-run until the floor can be implemented. These are estimates rather than
an invoice reconciliation guarantee. Runtime auto duration and unknown model pricing stay
unknown, never free. The autonomous cap remains unchanged.

## Licence, faces and approval

All Seedance models have closed weights and use proprietary hosted `service-terms`.
Fal's model pages mark the API for commercial use. The
[fal terms](https://fal.ai/legal/terms-of-service), section 14.3, restrict competing-model training.
`training_eligible=false` for both hosts and both models. No public terms were taken as a grant
for the Renderhaus continuity-training path.

The current [BytePlus service-specific terms](https://docs.byteplus.com/en/docs/legal/docs-service-specific-terms),
section 4.2.3, restrict API resale and integration into UGC/AI content-creation platforms.
BytePlus live use therefore needs written platform authorization and remains blocked without
`SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED=true`. An API key and spending approval cannot replace
that authorization. The current [general AI terms](https://docs.byteplus.com/en/docs/legal/AI-Services-terms)
and AUP govern outputs and rights. The applicability of a specific operator agreement remains
an operator/legal TODO. No AGPL or non-commercial model code or weights were added.

Seedance never receives references flagged as real-person images/video, even with consent.
The router sends generation to Wan with disclosure and requires Wan likeness consent.
Edit/extend refuse such references while Wan's preview restriction applies. Other retained
editors are explicit-only, so there is no unauthorized automatic substitute.
The [BytePlus real-person verification rules](https://docs.byteplus.com/en/docs/ModelArk/BytePlus_Real_Person_Verification_H5_and_API_Usage_Rules)
describe a separate authorized-asset flow; this adapter does not implement it.
Detection uses prompt, supplied policy flags and asset provenance. Image classification is not implemented.

BytePlus `watermark=true` requests the visible AI Generated mark and is the adapter default.
The vendor parameter's default is false; a universally mandatory true parameter was not proven.
Fal has no watermark argument, so the adapter sends none and cannot promise a visible mark.
Preserve vendor marks and required AI notices under the
[BytePlus acceptable use policy](https://docs.byteplus.com/en/docs/legal/acceptable_use_policy_byteplus_genai).
Spending approval is always required for paid video, including autonomous runs. Unknown cost
is disclosed as unknown. Approval exemptions and the autonomous spend cap are unchanged.

## Routing and validation limits

`capability_map.v2v_edit.default` and `.extend.default` remain `wan3_edit` and `wan3_extend`.
Their interims are `seedance25_edit` and `seedance25_extend`. Automatic selection consults the
Wan model's existing `live_enabled=false` commercial policy flag before model-specific setup.
Flipping that one flag restores Wan selection without changing the capability map. It does
not remove the unchanged Model Studio adapter's hard preview licence block or prove live
commercial access. That block remains exactly as it was.

Offline tests cover transport bodies, guards, reference limits, host-specific cost estimates,
licence-based selection in both states, gateway execution, autonomous approval/rejection and
saved-job polling with fakes. Comet E2E is blocked because Comet is unavailable in this environment.
No browser action, generated artifact or live provider access is claimed. Remaining verification
requires the real Studio/Comet session and separately authorized provider generation.

See [decisions](seedance-2-5-decisions.tsv) for evidence and unresolved limits.
