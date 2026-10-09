---
name: edit-v2v
description: Edit, restyle or extend existing video with Wan 3.0 on US-first Alibaba Model Studio.
metadata:
  include_tools: call_media_tool
  routing_tools: wan3_edit wan3_extend
  gateway_tools: ModelStudio___edit_wan3_video ModelStudio___extend_wan3_video ModelStudio___get_task
---

# Edit existing video

Use `ModelStudio___edit_wan3_video` for edits and `ModelStudio___extend_wan3_video` for extension.
They bind `wan3_edit` and `wan3_extend`, with no exceptions or interim. Explicit Aleph, Luma
or Wan VACE requests use [named provider](../named-provider/SKILL.md).
Trims, titles, captions, soundtrack and ordering use final-assembly.

Keep the original asset version. Supply its `video_url` or Studio asset handle, a `prompt`,
measured `source_duration_seconds` from 1 through 15 and measured `source_fps` of at least 16.
Do not invent source measurements. The adapter supports one source video and optional
`reference_image_urls` and `reference_audio_urls`; each audio needs its matching measured
`reference_audio_durations`. References containing real faces or voices need
`real_face_refs=true` and `likeness_consent=true` for permission to use each likeness.

Resolution defaults to `1080p`, audio to true, and aspect ratio to `adaptive`.
Edit `duration=-1` requests source-length preservation. Extend `duration` is the TOTAL target
output length, not the added portion. For a 5-second source extended by 2 seconds, use
`duration=7`, billed as 5 input plus 7 output seconds. Use `direction` forward, backward or
both; it becomes prompt intent, not a vendor request field. Extension requires adaptive ratio.
Input plus output duration cannot exceed 30 seconds. Split longer inputs before submission.
Smart `duration=-1` has an unknown quote and stays dry-run until billing reconciliation exists.
Any future permitted live call requires an explicit integer output duration; extension must
exceed source length. Current preview licensing blocks all live customer use, including
workspace hosts. Explain the internal-evaluation restriction and stop; spending approval
and disabling dry-run cannot override it.

The host defaults to US Virginia prices. `DASHSCOPE_BASE_URL` defaults to the legacy US host,
whose synthesis POST is UNVERIFIED and blocked live. The documented US workspace host can
be configured by the operator. Never alter flags or host settings to bypass a blocked request.
Approval shows input plus total output cost, including the platform fee, even in autonomous runs.

Submit once, save the returned `job_id`, and poll `ModelStudio___get_task` with `download=true`
at least 15 seconds apart. A failed/expired/unknown task is a blocker, not authority to resubmit.
Download the actual MP4 before its 24-hour URL expires and inspect the edit and preserved motion.
Keep continuity-qc on `local_qc`. The model has closed weights, evaluation-only preview licensing and
`training_eligible=false`; customer visual acceptance does not grant training rights.

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
