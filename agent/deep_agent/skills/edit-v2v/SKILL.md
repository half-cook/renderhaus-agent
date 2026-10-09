---
name: edit-v2v
description: Edit or extend existing video with Seedance 2.5 as the permanent default.
metadata:
  include_tools: call_media_tool
  routing_tools: seedance25_edit seedance25_extend
  gateway_tools: Seedance___edit_video Seedance___extend_video Seedance___get_video_task Fal___get_video_task
---

# Edit existing video

Seedance 2.5 is the permanent edit and extend default, chosen by Satya on 2026-10-09.
Use `seedance25_edit` or `seedance25_extend`, mapped to `Seedance___edit_video` and
`Seedance___extend_video` through fal US. There are no edit or extend exceptions or interims.
Disclose the default, host, model and estimated cost before approval.
All paid video pauses even in autonomous runs. Cost and tier never select a provider.
Explicit Wan 3.0, Model Studio, Aleph, Luma or Wan VACE requests use
[named provider](../named-provider/SKILL.md).
Trims, titles, captions, soundtrack and ordering use final-assembly.

For Seedance, supply `video_url`, `prompt`, measured `source_duration_seconds`, `source_fps`,
and `source_aspect_ratio`. Editing accepts sources from 4 through 30 seconds and preserves
approximately their duration. The vendor can shorten an edit by about 0.4 seconds.
The provider forces adaptive aspect ratio and automatic edit duration.
Extension accepts a measured source from 2 through 30 seconds and integer
`duration_seconds` from 4 through 30 for requested generated output seconds per call.
The source must be 24-60 fps. Resolution is 480p, 720p or 1080p; source aspect is preserved.
Use clear continuation intent in the prompt. Never promise that the returned
clip includes the entire original. Inspect the artifact before final assembly.
Requests phrased as "extend by N seconds" are blocked because appended-versus-combined
length semantics are UNVERIFIED. Request a specific generated output duration instead.
For example, "extend this clip to produce a 15-second output video" maps to
`duration_seconds=15`. Do not add or subtract source seconds. This wording describes the
vendor output request, not a promise that the final assembled timeline is 15 seconds.
Optional reference images and audio use the matching reference fields and measured metadata.
Never invent measurements. fal bills source plus requested output seconds using 24 fps and
the video-input discount.
BytePlus video-input cost remains unknown and dry-run because its minimum token floor is unverified.
An adaptive quote without source aspect is unknown. Do not equate unknown with free.
Never send real-person photos or video to Seedance, even when consent exists. Set
`real_face_refs=true` or `user_supplied_real_person_refs=true` when provenance indicates them.
The host refuses automatic real-face editing/extension. Other allowed editors require an
explicit request, and named Wan remains preview blocked. Explain the refusal; do not select
another model.
Poll the saved fal handle with `Seedance___get_video_task` or `Fal___get_video_task` and
`download=true`. A dry-run or queued job is incomplete. Open/play the actual artifact.
Seedance uses proprietary commercial API terms, vendor AUP and watermark requirements.
Outputs are not training eligible.

Explicit Wan 3.0 editing or extension uses [named provider](../named-provider/SKILL.md).
Alibaba preview terms permit internal testing only until GA. Live customer use remains blocked.

Follow `read_studio_context.intent_route`. Selection uses the explicit requested provider/model,
then a named exception, then the capability default. Cost estimates support approval and disclosure;
they never select a provider. Wan edit/extend remain named-only regardless of their licence flag.
Disclose provider, model, estimated cost and `default`, `exception: <reason>` or `explicit request`
before each dispatch. Unknown prices stay unknown.
All paid video pauses for approval even in autonomous runs when `premium_video_approval` is enabled.
Paid non-video retains the existing non-autonomous approval and autonomous spend cap.

Search Gateway for the selected built tool and use its exact schema through the matching role.
Pending aliases are routing identifiers, not Gateway endpoints. Never invent a tool or change a
DRY_RUN flag to satisfy a request. Submit once, preserve the returned job ID, and poll the same job.
A queued job or dry-run is incomplete media. Open/play the actual saved artifact before delivery.
Record explicit customer visual acceptance/rejection with `record_media_outcome` and the saved call ID.
A spending approval is not visual acceptance. Training eligibility follows provenance and the existing
Wan training hook; these routing instructions cannot grant training rights.

Official extension schema and pricing were read 2026-10-09.
See https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video/api,
https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video,
and https://docs.byteplus.com/en/docs/modelark/seedance-2-5.
Neither host's checked docs unequivocally say whether extension output includes the source
or contains only continuation. Keep the increment refusal and inspect the artifact.
