---
name: t2v
description: Generate text-to-video shots using Wan 3.0 by default and Seedance for synthetic dialogue.
metadata:
  include_tools: call_media_tool
  routing_tools: wan3_t2v seedance25_t2v
  gateway_tools: Seedance___get_video_task Seedance___text_to_video
---

# Text to video

Use `wan3_t2v` by default. Use `seedance25_t2v` only for dialogue without real-person references.
Dialogue includes quoted speech, says, talking and speaking; a silent/no-dialogue request is not the exception.
Wan 3.0 and Seedance 2.5 remain provider-pending. Their declared current interim is
`Seedance___text_to_video`, pinned to the existing Seedance adapter. Disclose that interim explicitly.
The future Seedance 2.5 host defaults to fal for US and Canadian customers; BytePlus is optional.
Never claim the current BytePlus 1.5 adapter runs 2.5 or provides US availability.

A real-person photo/video reference forces Wan and prohibits the Seedance interim. Report the pending
Wan provider instead. Require consent for real likeness. Gemini Omni is an A/B candidate only.
Split a request over 30 seconds into separate shots or refuse a single-shot request with that limit.
The built interim can have a shorter limit; preserve its actual schema constraints.

For Kling, Runway, Luma, Vidu or Wan VACE by name, read [named provider](../named-provider/SKILL.md).
Retired Veo and HeyGen generative-video requests disclose retirement and offer the default.
Use native Seedance `prompt`, `duration_seconds`, `aspect_ratio` and `resolution` controls only when
its schema accepts them. Poll `Seedance___get_video_task` using the saved ID and `download=true`.
For a final assembled MP4, read [final assembly](../final-assembly/SKILL.md).

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
