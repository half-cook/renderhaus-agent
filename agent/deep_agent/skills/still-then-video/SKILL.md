---
name: still-then-video
description: Lock a character or product look with a reviewed Seedream or Runway still before animating it.
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___vidu_q4_i2v Fal___vidu_q4_r2v Seedream___text_to_image Seedream___image_to_image Runway___text_to_image Runway___image_to_image Runway___get_runway_task Fal___image_to_video Fal___get_video_task Kling___image_to_video Kling___get_video_task Seedance___image_to_video Seedance___get_video_task
---

# Still before video

Read `read_studio_context` and plan a short shot with one visual action.
Start with one inexpensive still and the requested aspect ratio.
`seedream_t2i` maps to `Seedream___text_to_image` through `call_media_tool`.
For continuity with a supplied product or character, use `Seedream___image_to_image`
with `image_path_or_url` set to the existing immutable asset handle.
For an explicit Gen-4 Image request, use `Runway___text_to_image` or
`Runway___image_to_image` with `model="gen4_image"`. Image Turbo requires a source image
and `model="gen4_image_turbo"` on the reference tool. Runway uses `ratio`.
Poll `Runway___get_runway_task` before presenting its image as a completed still.
Ideogram and Recraft assets are provider-pending. Explain the missing integration rather
than replacing a named provider without the user's direction.

Show the completed still for review and retain its approved immutable version.
If the user rejects the look, revise the still before any paid animation.
A generation spending approval does not establish that the visual look was approved.
Once approved, read [image to video](../i2v/SKILL.md). Use the host-selected Standard animation route, usually `Seedance___image_to_video`
with `image_path_or_url`. Draft uses `Fal___image_to_video` with `first_frame_url`. `wan_i2v`, `kling_i2v`, and `seedance_i2v` map to
`Fal___image_to_video`, `Kling___image_to_video`, and `Seedance___image_to_video`.
Kling and Seedance use `image_path_or_url`; the host filters capabilities and tier before cost. Preserve each job ID and poll the corresponding `Fal___get_video_task`,
`Kling___get_video_task`, or `Seedance___get_video_task` with `download=true`.
Check the actual clip against the approved still and reuse accepted shots.

Follow the host route from `read_studio_context`. The capability table and tiers in
`agent/deep_agent/routing_policy.json` filter required features before tier and cost.
Standard finished shots use Seedance or Kling. Draft and rejected-shot retries use Wan.
Premium generation uses enabled Kling or Runway Gen-4.5; Veo remains unavailable.
Confidential projects permit Wan only, including retries. Preserve every required feature.
If Wan cannot satisfy it, explain the refusal. There is no built Wan still-image tool.

Say which provider/model the route selects, its tier and filters, and its estimated cost.
Use the host estimate, including the existing fee. Unconfirmed prices stay unknown.
Discover the chosen schema and use its native controls; a route refusal is not approval.
Submit through the dispatch wrapper. Paid approval and the autonomous cap remain enforced;
Kling, Runway and Luma video pause even when autonomous under the existing premium policy.
Record explicit customer acceptance/rejection of a completed saved generation call with
`record_media_outcome`. A spending approval is not visual acceptance. On rejection, follow
its Wan retry route once, retain required features, and obtain any required spending approval.
Only registered, successful, accepted, non-dry-run Wan assets with approved Apache provenance
may enter continuity training. Hosted-provider outputs never become training inputs.

For a Vidu Q4 route, read [Vidu Q4](../vidu-q4/SKILL.md). Use
`Fal___vidu_q4_i2v` with `image_url` for a first frame, or `Fal___vidu_q4_r2v` with
`reference_image_urls` and optional `reference_audio_urls` for subject and voice references.
Use native `duration` (3 through 16), case-sensitive resolutions through `4K`, and
`audio=true` on R2V when sound is required. I2V audio is implicit. Q4 is Standard,
never confidential, and never training-eligible. Poll the saved `Fal___get_video_task` job.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
