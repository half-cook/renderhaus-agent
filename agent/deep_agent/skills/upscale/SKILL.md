---
name: upscale
description: Finish a saved clip with Topaz Starlight upscale or Apollo/Chronos interpolation.
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
Run continuity-QC on the input before any paid finishing job. Evidence is vendor-only; A/B is pending.

Read the source asset's measured duration, FPS, width, and height. Supply all four values with
`video_url`. Use the current renderhaus-asset version handle. Never guess source measurements.
Upscale accepts either `target_resolution` of 1080p or 4K, or `upscale_factor` of 1 through 4.
Omitting both uses 2x. Preserve aspect ratio. Interpolate accepts either `target_fps` or
`fps_multiplier`. Omitting both uses 60 FPS. Interpolation preserves source dimensions.
`slowdown_factor` changes output duration, independently of the FPS multiplier.

Every paid Topaz call pauses for cost approval, including autonomous runs and when the global
premium-video switch is off. The host quotes measured output dimensions, duration, and FPS.
Published examples checked 2026-10-09 are $1.20 per 10 seconds at 1080p30 and $2.60 at 4K30.
Apollo and Chronos cost $0.30 for 10 seconds at 1080p30 converted to 60 FPS. These are provider
estimates before the existing Renderhaus fee. Unsupported dimensions/FPS and slow-motion pricing
remain unknown, and live submission is blocked until a verified quote exists. Never choose by cost.

Submit once, save the Topaz job handle, and poll `Topaz___get_video_task` with `download=true`.
Dry-run previews are not media, and queued jobs are incomplete. A standalone finishing request
can finish after the actual saved MP4 opens and plays. Captions, overlays, music, or assembly still
require Remotion. Finishing through the manual Studio invoke endpoint is blocked to preserve approval.
`Topaz___list_topaz_models` is a local documented catalog, not an account access check.

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
