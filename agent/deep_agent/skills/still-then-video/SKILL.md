---
name: still-then-video
description: Review a still first, then animate the approved version through the capability map.
metadata:
  include_tools: call_media_tool
  routing_tools: gpt_image25_t2i gpt_image25_edit wan3_i2v seedance25_i2v
  gateway_tools: Fal___generate_wan3_i2v Fal___get_video_task Seedance___get_video_task Seedance___image_to_video
---

# Still before video

Generate the first look through `gpt_image25_t2i`; revise it through `gpt_image25_edit`.
Both image defaults are pending with no automatic interim. Explicit Seedream requests use
named-provider; otherwise disclose the pending image step and stop. Image specialists and exceptions
are documented in [still images](../image-gen/SKILL.md).
Show the completed still, obtain visual approval, and pin that immutable version before animation.
An existing approved character/frame can start at the animation step without generating another still.

Animate through `wan3_i2v` by default or `seedance25_i2v` for synthetic dialogue.
Wan uses `Fal___generate_wan3_i2v` with the approved version in `start_image_url` and saved-job
polling through `Fal___get_video_task`. Only the Seedance dialogue exception uses the current
`Seedance___image_to_video` interim while 2.5 remains pending.
Real-person references force Wan and require `real_face_refs=true` plus `likeness_consent=true`.
Read [image to video](../i2v/SKILL.md) for native inputs and saved-job polling.

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
