---
name: i2v
description: Animate an approved still using the configured capability and tier ladder.
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___image_to_video Fal___reference_to_video Fal___get_video_task Kling___image_to_video Kling___get_video_task Seedance___image_to_video Seedance___get_video_task Runway___image_to_video Runway___get_runway_task Seedream___text_to_image Seedream___image_to_image Luma___image_to_video Luma___get_video_task Luma___list_luma_models
---

# Image to video

Read `read_studio_context` and identify the approved immutable image version.
If the still needs correction, read [product images](../product-images/SKILL.md) and use
`Seedream___image_to_image` before animation. `seedream_t2i` maps to `Seedream___text_to_image`.
Do not substitute a newly generated still for an approved version without review.

Search Gateway and use `call_media_tool` with its returned input schema.
`wan_i2v` maps to `Fal___image_to_video`, which requires `first_frame_url` and `prompt`.
Wan is the Draft provider. Prefer `model="fal-ai/wan-vace-14b"`, an explicit priced resolution,
and an explicit frame count. Use `last_frame_url` when the requested model supports an end
frame. For subject-reference guidance, use `Fal___reference_to_video` with nonempty
`ref_image_urls`. References guide consistency without guaranteeing identical subjects.

`kling_i2v` maps to `Kling___image_to_video`. `seedance_i2v` maps to
`Seedance___image_to_video`. Runway animation uses `Runway___image_to_video`.
These tools use `image_path_or_url` and `prompt`, unlike Wan's `first_frame_url`.
Kling's end-frame field is `end_image_path_or_url` and is model-dependent.
Runway uses `model="gen4.5"`, integer `duration_seconds` of 2 through 10, and `ratio`.
Follow the selected tier and required capabilities. Standard uses Seedance or Kling.

Keep `renderhaus-asset://` version handles intact so Studio resolves them securely.
Do not send local paths, invented URLs, expired handles, or browser credentials.
Submit once and poll the saved ID with `Fal___get_video_task`, `Kling___get_video_task`,
`Seedance___get_video_task`, or `Runway___get_runway_task`, using `download=true`.
Space Runway polls at least five seconds apart. Reuse finished shots and preserve failed
job IDs. Read [continuity QC](../continuity-qc/SKILL.md) for shot comparisons.

Use `Luma___image_to_video` (`luma_ray3_i2v`, model `ray-3.2`) for an explicit Luma request with a
start image, an end image, or both (`image_path_or_url`, `last_frame_path_or_url`). Luma anchor
clips are exactly 5 seconds. Poll `Luma___get_video_task` with the saved UUID and `download=true`.
Luma output rights follow its API terms (no training or evaluation datasets, restricted
redistribution), so Luma outputs are never training-eligible.

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

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
