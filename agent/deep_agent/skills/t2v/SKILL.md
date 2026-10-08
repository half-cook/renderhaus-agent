---
name: t2v
description: Generate a short clip from text using the capability, quality tier, and cost ladder for a built video provider (Kling, Runway, Seedance or Luma).
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___text_to_video Fal___get_video_task Fal___list_fal_models Kling___text_to_video Kling___omni_video Kling___get_video_task Kling___list_kling_models Runway___text_to_video Runway___get_runway_task Runway___list_runway_models Seedance___text_to_video Seedance___get_video_task Seedance___list_seedance_models Luma___text_to_video Luma___extend_video Luma___get_video_task Luma___list_luma_models
---

# Text to video

Read `read_studio_context` and confirm the requested duration, framing, and action.
Search `x_amz_bedrock_agentcore_search` for the selected provider and read its exact schema.
Use the host-selected `call_media_tool` route. Standard defaults to `Seedance___text_to_video`;
use `Fal___text_to_video` for Draft, previews, or a valid rejected-shot retry.
The seed aliases `wan_t2v`, `kling_t2v`, `runway_gen45_t2v`, and `seedance_t2v` map to
`Fal___text_to_video`, `Kling___text_to_video`, `Runway___text_to_video`, and
`Seedance___text_to_video` respectively.

For Wan, prefer `model="fal-ai/wan-vace-14b"` and set `num_frames`,
`frames_per_second`, `resolution`, and `aspect_ratio` explicitly. Supported frame counts
are 81 through 241. Use a confirmed priced resolution from the billing table.
Wan billing uses `num_frames / 16`, not the playback duration computed from FPS.
Consult the free `Fal___list_fal_models` when capabilities or model availability matter.

Use Kling when the brief requires its supported native audio, shot controls, or reference
features. Discover `Kling___list_kling_models` first when choosing capabilities.
Pass native `duration_seconds`, `aspect_ratio`, `resolution`, and `generate_audio` fields.
Explicit `shots` need `prompt` and `duration_seconds`, with their sum equal to the total.
Use `Kling___omni_video` for multiple references or existing elements. Retain actual element
IDs, types, and prompt identifiers. Never infer element IDs from image URLs.

Use `Runway___text_to_video` with `model="gen4.5"` for an explicit Gen-4.5 request.
Its integer duration is 2 through 10 seconds and its field is `ratio`, not `aspect_ratio`.
Use the free `Runway___list_runway_models` for supported constraints. Retain required
Runway attribution in applicable delivery interfaces. The catalog does not prove account access.
Use `Seedance___text_to_video` for Standard or an explicit Seedance request and discover its model with
`Seedance___list_seedance_models` when needed. Veo is a provider-pending draft.
Use `Luma___text_to_video` (`luma_ray3_t2v`, wire model `ray-3.2`) for an explicit Luma or Ray 3.2
request. Its `duration_seconds` is 5 or 10 and `resolution` is 360p, 540p, 720p or 1080p; 360p is
a lower-resolution setting, not the configured Draft provider. `Luma___extend_video` (`luma_ray3_extend`) continues a completed Luma
generation by its UUID with `direction` forward or backward; extend has no confirmed 360p price.
Consult the free `Luma___list_luma_models` for limits. Luma output rights follow its API terms (no training or evaluation datasets, restricted
redistribution), so Luma outputs are never training-eligible.


Submit once and preserve the entire returned `job_id`. Poll `Fal___get_video_task`,
`Kling___get_video_task`, `Runway___get_runway_task`, `Seedance___get_video_task`, or
`Luma___get_video_task` for the
selected provider with the saved ID and `download=true`. Space Runway polls at least five
seconds apart. Never submit again after a polling error or uncertain generation response.
A dry-run is terminal and produces no generated media. Verify the persisted clip opens and
plays before claiming usable footage. Read [final assembly](../final-assembly/SKILL.md)
when a final assembled MP4 is requested.

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
