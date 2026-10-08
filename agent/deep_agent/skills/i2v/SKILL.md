---
name: i2v
description: Animate an approved still with Wan by default or an explicitly requested Kling, Seedance, or Runway model.
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___image_to_video Fal___reference_to_video Fal___get_video_task Kling___image_to_video Kling___get_video_task Seedance___image_to_video Seedance___get_video_task Runway___image_to_video Runway___get_runway_task Seedream___text_to_image Seedream___image_to_image
---

# Image to video

Read `read_studio_context` and identify the approved immutable image version.
If the still needs correction, read [product images](../product-images/SKILL.md) and use
`Seedream___image_to_image` before animation. `seedream_t2i` maps to `Seedream___text_to_image`.
Do not substitute a newly generated still for an approved version without review.

Search Gateway and use `call_media_tool` with its returned input schema.
`wan_i2v` maps to `Fal___image_to_video`, which requires `first_frame_url` and `prompt`.
Wan is the default. Prefer `model="fal-ai/wan-vace-14b"`, an explicit priced resolution,
and an explicit frame count. Use `last_frame_url` when the requested model supports an end
frame. For subject-reference guidance, use `Fal___reference_to_video` with nonempty
`ref_image_urls`. References guide consistency without guaranteeing identical subjects.

`kling_i2v` maps to `Kling___image_to_video`. `seedance_i2v` maps to
`Seedance___image_to_video`. Runway animation uses `Runway___image_to_video`.
These tools use `image_path_or_url` and `prompt`, unlike Wan's `first_frame_url`.
Kling's end-frame field is `end_image_path_or_url` and is model-dependent.
Runway uses `model="gen4.5"`, integer `duration_seconds` of 2 through 10, and `ratio`.
Choose a premium provider only for the brief's explicit capability or provider request.

Keep `renderhaus-asset://` version handles intact so Studio resolves them securely.
Do not send local paths, invented URLs, expired handles, or browser credentials.
Submit once and poll the saved ID with `Fal___get_video_task`, `Kling___get_video_task`,
`Seedance___get_video_task`, or `Runway___get_runway_task`, using `download=true`.
Space Runway polls at least five seconds apart. Reuse finished shots and preserve failed
job IDs. Read [continuity QC](../continuity-qc/SKILL.md) for shot comparisons.

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
