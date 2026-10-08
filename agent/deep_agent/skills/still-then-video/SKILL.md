---
name: still-then-video
description: Lock a character or product look with a reviewed Seedream or Runway still before animating it.
metadata:
  include_tools: call_media_tool
  gateway_tools: Seedream___text_to_image Seedream___image_to_image Runway___text_to_image Runway___image_to_image Runway___get_runway_task Fal___image_to_video Fal___get_video_task Kling___image_to_video Kling___get_video_task Seedance___image_to_video Seedance___get_video_task
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
Once approved, read [image to video](../i2v/SKILL.md). Default to `Fal___image_to_video`
with `first_frame_url`. `wan_i2v`, `kling_i2v`, and `seedance_i2v` map to
`Fal___image_to_video`, `Kling___image_to_video`, and `Seedance___image_to_video`.
Kling and Seedance use `image_path_or_url`; select them for an explicit capability or
provider request. Preserve each job ID and poll the corresponding `Fal___get_video_task`,
`Kling___get_video_task`, or `Seedance___get_video_task` with `download=true`.
Check the actual clip against the approved still and reuse accepted shots.

Apply `agent/deep_agent/routing_policy.json` for provider, model, region, and licence gates.
Fal Wan VACE is the default video tier. Before a premium video submission to Kling or Runway,
show the estimate from `server.billing_rates.cost_for`, including its platform fee.
Treat unconfirmed pricing as unknown. Submit through the dispatch wrapper so the shared
approval policy can pause even an autonomous run. Never fabricate approval or bypass its gate.
Only policy-approved Wan results with `training_eligible=true` and `weights_license=Apache-2.0`
may enter the continuity training hook. Other providers' outputs are not training-eligible.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
