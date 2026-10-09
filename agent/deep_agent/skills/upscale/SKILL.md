---
name: upscale
description: Finish a saved clip with Topaz Starlight upscale or Apollo/Chronos interpolation.
metadata:
  include_tools: call_media_tool
  routing_tools: topaz_upscale topaz_interpolate
---

# Finishing

Use `topaz_upscale` for upscaling and `topaz_interpolate` for frame interpolation. Topaz Starlight
Precise is the planned upscale default. Apollo is the interpolation default; select Chronos through
the same future tool only for simple linear-motion FPS conversion. Both aliases are provider-pending
with no built interim. A larger new generation does not upscale the supplied asset. SeedVR2/RIFE
are retired. Prices/model identifiers need official verification in feat/finishing-topaz.
Run continuity-QC on the input before any paid finishing job. Evidence is vendor-only; A/B is pending.

Follow `read_studio_context.intent_route`. Selection uses the explicit requested provider/model,
then a named exception, then the capability default. Cost estimates support approval and disclosure;
they never select a provider. Pending defaults use only the policy's declared interim tool.
Disclose provider, model, estimated cost and `default`, `exception: <reason>`, `explicit request`,
or `interim default until <provider> lands` before each dispatch. Unknown prices stay unknown.
All paid video pauses for approval even in autonomous runs when `premium_video_approval` is enabled.
Paid non-video retains the existing non-autonomous approval and autonomous spend cap.

Search Gateway for the selected built tool and use its exact schema through the matching role.
Pending aliases are routing identifiers, not Gateway endpoints. Never invent a tool or change a
DRY_RUN flag to satisfy a request. Submit once, preserve the returned job ID, and poll the same job.
A queued job or dry-run is incomplete media. Open/play the actual saved artifact before delivery.
Record explicit customer visual acceptance/rejection with `record_media_outcome` and the saved call ID.
A spending approval is not visual acceptance. Training eligibility follows provenance and the existing
Wan training hook; these routing instructions cannot grant training rights.
