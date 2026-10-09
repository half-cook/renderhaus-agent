---
name: edit-v2v
description: Edit, restyle or extend existing video with Wan 3.0 and the declared interim while pending.
metadata:
  include_tools: call_media_tool
  routing_tools: wan3_edit wan3_extend
  gateway_tools: Luma___extend_video Luma___get_video_task Luma___list_luma_models Luma___modify_video
---

# Edit existing video

Use `wan3_edit` for generative edits and `wan3_extend` for extension. Neither has an exception.
Both Model Studio tools remain pending. The policy's declared interim preserves current behavior
through `Luma___modify_video` or `Luma___extend_video`; disclose that temporary selection.
For an explicit Aleph, Luma or Wan VACE request, read [named provider](../named-provider/SKILL.md).
For trims, titles, captions, soundtrack or ordering, use final-assembly rather than generative edits.

Keep the original asset version. Luma Modify accepts exactly one `video_path_or_url` or
`source_generation_id`, its measured `source_duration_seconds` of 5 or 10, and supported `strength`.
Other source lengths have no confirmed price and are refused. Luma Extend uses a completed
Luma generation UUID and `direction`, not an arbitrary uploaded clip. A missing eligible generation
is a blocker, not permission to create a new paid video first. Inspect `Luma___list_luma_models` when needed.

Poll `Luma___get_video_task` with the saved ID and `download=true`. Compare the changed region
and preserved motion. Luma outputs remain ineligible for training/evaluation datasets.

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
