---
name: i2v
description: Animate a supplied start frame or reference set with Wan 3.0; use Seedance for synthetic dialogue.
metadata:
  include_tools: call_media_tool
  routing_tools: wan3_i2v wan3_r2v seedance25_i2v seedance25_r2v
  gateway_tools: Fal___generate_wan3_i2v Fal___generate_wan3_r2v Fal___get_video_task Seedance___get_video_task Seedance___image_to_video
---

# Image to video

Use `wan3_i2v` for a start frame and `wan3_r2v` for a reference set. Use the matching
`seedance25_i2v` or `seedance25_r2v` exception for dialogue without real-person references.
A supplied photo/video of a real person forces Wan and blocks both Seedance and Omni.
Set `real_face_refs=true` for real likeness and obtain `likeness_consent=true` before dispatch.
Preserve the approved immutable asset version. Spending approval cannot replace likeness consent.

Wan 3.0 uses `Fal___generate_wan3_i2v` for a required `start_image_url` and optional `end_image_url`.
Use `Fal___generate_wan3_r2v` for reference sets with up to ten `reference_image_urls`, five
`reference_video_urls` and five `reference_audio_urls`. Supply measured `reference_video_durations`,
`reference_video_fps` and `reference_audio_durations` alongside the matching references.
Total input video and audio durations are each at most 15 seconds; input video is at least 16 fps.
Missing input durations make the price unknown. Video inputs add billed input seconds to output cost.
Optional document `file_url` and webpage `web_url` inputs require `enable_thinking=true`.
Never invent these inputs or metadata.
Common native controls include `prompt`, `resolution`, `aspect_ratio`, `duration`, `audio`, `seed`,
`enable_thinking`, `enable_prompt_expansion` and `enable_safety_checker`. No negative prompt is supported.
Defaults are 1080p, adaptive aspect ratio, five seconds and audio enabled. Duration is 2-30 seconds.
Use prompt instructions for multi-shot generation; no multi_shot boolean is accepted.
Poll `Fal___get_video_task` with the saved job ID and `download=true`.
Synthetic-dialogue i2v uses the declared `Seedance___image_to_video` exception interim until 2.5 lands.
Seedance reference-to-video remains pending without an interim. Do not replace reference inputs with
a single frame to force a route.
Future Seedance 2.5 defaults to fal for US/Canada; current BytePlus 1.5 is an interim, not that host upgrade.
Omni and Vidu are A/B candidates only. An explicit Vidu request belongs in named-provider.

Discover native arguments. Wan uses `start_image_url`; Seedance uses `image_path_or_url`. Retain
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
