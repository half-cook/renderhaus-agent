---
name: t2v
description: Generate a short clip from text with Wan by default or an explicitly requested built video provider (Kling, Runway, Seedance or Luma).
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___text_to_video Fal___get_video_task Fal___list_fal_models Kling___text_to_video Kling___omni_video Kling___get_video_task Kling___list_kling_models Runway___text_to_video Runway___get_runway_task Runway___list_runway_models Seedance___text_to_video Seedance___get_video_task Seedance___list_seedance_models Luma___text_to_video Luma___extend_video Luma___get_video_task Luma___list_luma_models
---

# Text to video

Read `read_studio_context` and confirm the requested duration, framing, and action.
Search `x_amz_bedrock_agentcore_search` for the selected provider and read its exact schema.
Use `call_media_tool` with `Fal___text_to_video` for an ordinary text-only clip.
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
Use `Seedance___text_to_video` for an explicit Seedance request and discover its model with
`Seedance___list_seedance_models` when needed. Veo is a provider-pending draft.
Use `Luma___text_to_video` (`luma_ray3_t2v`, wire model `ray-3.2`) for an explicit Luma or Ray 3.2
request. Its `duration_seconds` is 5 or 10 and `resolution` is 360p, 540p, 720p or 1080p; 360p is
the cheap draft tier. `Luma___extend_video` (`luma_ray3_extend`) continues a completed Luma
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

Apply `agent/deep_agent/routing_policy.json` for provider, model, region, and licence gates.
Fal Wan VACE is the default video tier. Before a premium video submission to Kling, Runway or Luma,
show the estimate from `server.billing_rates.cost_for`, including its platform fee.
Treat unconfirmed pricing as unknown. Submit through the dispatch wrapper so the shared
approval policy can pause even an autonomous run. Never fabricate approval or bypass its gate.
Only policy-approved Wan results with `training_eligible=true` and `weights_license=Apache-2.0`
may enter the continuity training hook. Other providers' outputs are not training-eligible.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
