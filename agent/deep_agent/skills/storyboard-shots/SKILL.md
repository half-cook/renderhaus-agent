---
name: storyboard-shots
description: Turn approved storyboard frames into consistent shots with the capability map.
metadata:
  include_tools: call_media_tool
  routing_tools: gpt_image25_t2i gpt_image25_edit wan3_i2v wan3_r2v seedance25_i2v seedance25_r2v
  gateway_tools: Fal___generate_wan3_i2v Fal___generate_wan3_r2v Fal___get_video_task
---

# Storyboard shots

Read Studio context and save ordered shot durations, framing and product references.
Use image-gen for missing keyframes, preserving the approved product version. Review and pin
stills before animation. Use `Fal___generate_wan3_i2v` for a start frame or
`Fal___generate_wan3_r2v` for image/video/audio reference sets. Read i2v for limits and required
reference duration/fps metadata. Preserve the selected schema and poll `Fal___get_video_task`.
Real-face references force Wan and require `real_face_refs=true` and `likeness_consent=true`.
Synthetic dialogue uses the Seedance exception. Its reference-video tool remains pending.
Reuse accepted shots and read final-assembly to render the clips rather than still previews.

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
