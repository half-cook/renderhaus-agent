---
name: upscale
description: Preview, compare, and approve a saved clip before full upscale or frame interpolation.
metadata:
  include_tools: call_media_tool
  routing_tools: topaz_upscale topaz_interpolate
  gateway_tools: Topaz___upscale_video Topaz___interpolate_video Topaz___get_video_task Topaz___list_topaz_models
---

# Finishing

Use `Topaz___upscale_video` for upscaling a saved video. Starlight Precise 2.6 is the default.
Use `Topaz___interpolate_video` for frame interpolation. Apollo is the default. Use Chronos only
for plain linear-motion FPS conversion, or when explicitly requested. An explicit Apollo request
overrides the linear-motion exception. The fal model names are `Starlight Precise 2.6`, `Apollo`,
and `Chronos`. Direct API identifiers `slp-2.6`, `apo-8`, and `chr-2` normalize to those names.
A larger new generation does not upscale the supplied asset. SeedVR2 and RIFE remain retired.
Inspect the source before paid finishing. Provider quality claims require the preview comparison below.

Use the current `renderhaus-asset://` version handle. Supply measured duration, FPS, width,
and height when available. Native preparation measures missing values locally. Never guess
source measurements or submit incomplete arguments directly to the paid Gateway tool.
Upscale accepts either `target_resolution` of 1080p or 4K, or `upscale_factor` of 1 through 4.
Omitting both uses 2x. Preserve aspect ratio. Interpolate accepts either `target_fps` or
`fps_multiplier`. Omitting both uses 60 FPS. Interpolation preserves source dimensions.
`slowdown_factor` changes output duration, independently of the FPS multiplier.

## Preview and confirm

1. Call native `prepare_finishing_preview` with the selected Gateway `tool_name`, full-source
   `arguments`, and a representative `start_seconds`. `duration_seconds` defaults to 3 and
   the host caps the sample at 3. Choose faces, texture, or motion relevant to the request.
   Use an owned `renderhaus-asset://` source. The host measures it and saves an actual trimmed
   clip. The host supplies omitted source measurements and rejects conflicting supplied
   values. It returns `preview_id`, `preview_arguments`, and `full_arguments`.
2. Submit exactly `preview_arguments` to the selected Topaz tool through `call_media_tool`.
   The preview is paid processing and needs its own cost approval, even autonomously.
   Local trimming is free. Never shorten only the duration metadata on the full source URL.
3. Save the returned job ID. Poll `Topaz___get_video_task` with `download=true` until the
   processed sample is saved. A dry-run, queued job, failed job, or missing artifact cannot
   proceed to comparison. Do not resubmit an uncertain or existing job.
4. Call native `review_finishing_preview` with only `preview_id`. The host shows the saved
   original and enhanced clips side by side with linked playback and an A/B toggle. The
   customer can keep the original or accept the preview. This review authorizes no spending.
5. After review approval, submit exactly `full_arguments` through the same Topaz tool.
   The full job still pauses for its separate estimate and spending approval. A changed source,
   model, output size, frame rate, or processing setting requires a new preview and review.
   If `covers_full_source` is true, the approved sample already covers the whole source.
   Deliver that saved artifact without purchasing a duplicate full job.

The host binds review to the owned source, sample, settings, and artifact checksums. Never
replace review with a claimed chat approval, a fabricated preview ID, or a provider success
message. A rejection leaves the original intact and blocks the full request. Resume saved
preview state from `read_studio_context` before preparing another sample.
The latest sample for the full request controls review. A failed or rejected sample stays
closed for the same settings and range. Choose a new sample range or revised settings only
after the customer asks for another preview. Do not automatically retry it.

## Cost and delivery

Every paid Topaz call pauses for cost approval, including autonomous runs and when the global
premium-video switch is off. The host quotes measured output dimensions, duration, and FPS.
Published examples checked 2026-10-09 are $1.20 per 10 seconds at 1080p30 and $2.60 at 4K30.
Apollo and Chronos cost $0.30 for 10 seconds at 1080p30 converted to 60 FPS. These are provider
estimates before the existing Renderhaus fee. Unsupported dimensions/FPS and slow-motion pricing
remain unknown, and live submission is blocked until a verified quote exists. Never choose by cost.

Submit once, save the Topaz job handle, and poll `Topaz___get_video_task` with `download=true`.
Dry-run previews are not media, and queued jobs are incomplete. A standalone finishing request
can finish after the reviewed full-source MP4 opens and plays. A short sample cannot complete a
longer-source request. Captions, overlays, music, or assembly still
require Remotion. Finishing through the manual Studio invoke endpoint is blocked to preserve approval.
`Topaz___list_topaz_models` is a local documented catalog, not an account access check.

The workflow adapts the preview/compare/confirm pattern from
[topaz-video-skill](https://github.com/DreamLoveBetty/topaz-video-skill), MIT, read 2026-10-15.
No local Topaz application bridge is installed. Starlight on fal remains the default.
Use neutral customer labels such as "Enhancement preview" and "Full finish". Keep provider
and model identifiers in tool calls and provenance. Never display platform fees in UI copy.

Follow `read_studio_context.intent_route`. Selection uses the explicit requested provider/model,
then a named exception, then the capability default. Cost estimates support approval and disclosure;
they never select a provider. Pending defaults use only the policy's declared interim tool.
Disclose provider, model, estimated cost and `default`, `exception: <reason>`, `explicit request`,
or `interim default until <provider> lands` before each dispatch. Unknown prices stay unknown.
All paid video pauses for approval even in autonomous runs when `premium_video_approval` is enabled.
Topaz finishing always pauses independently of that switch.
Paid non-video retains the existing non-autonomous approval and autonomous spend cap.

Search Gateway for the selected built tool and use its exact schema through the matching role.
Pending aliases are routing identifiers, not Gateway endpoints. Never invent a tool or change a
DRY_RUN flag to satisfy a request. Submit once, preserve the returned job ID, and poll the same job.
A queued job or dry-run is incomplete media. Open/play the actual saved artifact before delivery.
Record explicit customer visual acceptance/rejection with `record_media_outcome` and the saved call ID.
A spending approval is not visual acceptance. Training eligibility follows provenance and the existing
Wan training hook; these routing instructions cannot grant training rights.

Topaz is a proprietary commercial API under fal service terms. Every output has
`training_eligible=false`, including visually accepted output. No Topaz weights are distributed.
Source media rights and required likeness/voice consents remain the customer's responsibility.

Official references read 2026-10-09:
- https://fal.ai/models/topaz/upscale/video/generative/api
- https://fal.ai/models/topaz/interpolate/video/api
- https://fal.ai/models/topaz/upscale/video/generative
- https://fal.ai/models/topaz/interpolate/video
- https://fal.ai/legal/terms-of-service
- https://fal.ai/legal/api-services
