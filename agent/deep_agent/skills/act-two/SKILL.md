---
name: act-two
description: Transfer facial/upper-body acting with Runway Act-Two or full-body motion with Kling.
metadata:
  include_tools: call_media_tool
  routing_tools: runway_act_two kling_motion_control
---

# Performance transfer

Use `runway_act_two` for facial/upper-body acting. Use `kling_motion_control` for full-body motion,
whole-body motion or dance. Both endpoints remain pending; Gen-4.5/ordinary Kling generation is not
performance transfer and cannot serve as an interim. Require real performer consent. Chunk the
supplied driving clip into supported shots of at most 30 seconds. No neutral benchmark establishes
these picks; A/B evidence remains pending. Check pose, face and temporal continuity on the artifact.

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
