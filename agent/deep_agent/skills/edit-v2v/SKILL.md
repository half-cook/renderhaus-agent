---
name: edit-v2v
description: Edit or extend video with Seedance 2.5 while the Wan 3.0 default has a preview licence block.
metadata:
  include_tools: call_media_tool
  routing_tools: wan3_edit wan3_extend seedance25_edit seedance25_extend
  gateway_tools: Seedance___edit_video Seedance___extend_video Seedance___get_video_task Fal___get_video_task ModelStudio___edit_wan3_video ModelStudio___extend_wan3_video ModelStudio___get_task
---

# Edit existing video

The capability defaults remain `wan3_edit` and `wan3_extend`. While Wan's commercial policy
has `live_enabled=false`, select the declared `seedance25_edit` or `seedance25_extend` interim.
Use `Seedance___edit_video` or `Seedance___extend_video` through fal US. Follow the host route.
Disclose Wan's preview licence block, the Seedance interim, its host and cost before approval.
All paid video pauses even in autonomous runs. There is no automatic price or tier fallback.
Explicit Aleph, Luma or Wan VACE requests use [named provider](../named-provider/SKILL.md).
Trims, titles, captions, soundtrack and ordering use final-assembly.

For Seedance, supply `video_url`, `prompt`, measured `source_duration_seconds`, `source_fps`,
and `source_aspect_ratio`. Editing accepts sources from 4 through 30 seconds and preserves
approximately their duration. The vendor can shorten an edit by about 0.4 seconds.
The provider forces adaptive aspect ratio and automatic edit duration.
Extension accepts a source from 2 through 30 seconds and `duration_seconds` for requested
output seconds. Use clear continuation intent in the prompt. Never promise that the returned
clip includes the entire original. Inspect the artifact before final assembly.
Requests phrased as "extend by N seconds" are blocked because appended-versus-combined
length semantics are UNVERIFIED. Request a specific generated output duration instead.
Optional reference images and audio use the matching reference fields and measured metadata.
Never invent measurements. Source plus generated video seconds incur token charges.
An adaptive quote without source aspect is unknown. Do not equate unknown with free.
Never send real-person photos or video to Seedance, even when consent exists. Set
`real_face_refs=true` or `user_supplied_real_person_refs=true` when provenance indicates them.
The host refuses real-face editing/extension while Wan remains preview blocked because
all other allowed editors are explicit-only. Explain the reason; do not select another model.
Poll the saved fal handle with `Seedance___get_video_task` or `Fal___get_video_task` and
`download=true`. A dry-run or queued job is incomplete. Open/play the actual artifact.
Seedance uses proprietary commercial API terms, vendor AUP and watermark requirements.
Outputs are not training eligible.

For an explicit Model Studio preview, follow the constraints below. Changing routing
`live_enabled` after a licence review restores Wan selection; the existing adapter's hard
preview licence restriction still blocks live requests and must not be bypassed.

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
they never select a provider. Pending or commercially blocked defaults use only the policy's declared interim tool.
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
