---
name: i2v
description: Animate a supplied start frame or reference set with Wan 3.0; use Seedance for synthetic dialogue.
metadata:
  include_tools: call_media_tool
  routing_tools: wan3_i2v wan3_r2v seedance25_i2v seedance25_r2v
  gateway_tools: Seedance___get_video_task Seedance___image_to_video
---

# Image to video

Use `wan3_i2v` for a start frame and `wan3_r2v` for a reference set. Use the matching
`seedance25_i2v` or `seedance25_r2v` exception for dialogue without real-person references.
A supplied photo/video of a real person forces Wan and blocks both Seedance and Omni.
Require consent for real likeness and preserve the approved immutable asset version.

Wan 3.0 is pending. Start-frame generation uses only its declared interim
`Seedance___image_to_video`; synthetic-dialogue i2v uses that same current adapter until 2.5 lands.
Neither reference-to-video alias has a built interim. Real-face shots also remain pending because
the Seedance interim is prohibited. Do not replace reference inputs with a single frame to force a route.
Future Seedance 2.5 defaults to fal for US/Canada; current BytePlus 1.5 is an interim, not that host upgrade.
Omni and Vidu are A/B candidates only. An explicit Vidu request belongs in named-provider.

Discover native arguments. Seedance uses `image_path_or_url` and `prompt`; retain
`renderhaus-asset://` version handles for Studio to resolve. Do not send local paths or invented URLs.
Poll `Seedance___get_video_task` with the saved ID and `download=true`.
Inspect the actual result against the approved image and use continuity-qc for comparisons.

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
