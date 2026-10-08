---
name: edit-v2v
description: Edit existing footage with Wan VACE masks and controls, or an explicitly requested Luma Modify or Runway Aleph edit.
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___video_to_video Fal___get_video_task Fal___list_fal_models Runway___video_to_video Runway___get_runway_task Runway___list_runway_models Luma___modify_video Luma___get_video_task Luma___list_luma_models
---

# Edit existing video

Read `read_studio_context` and retain the original asset version.
For trimming, soundtrack, captions, or ordering, read [final assembly](../final-assembly/SKILL.md).
Use generative editing only when the visual content must change. Search Gateway for the
selected edit tool and inspect its native input schema before dispatch.

`wan_vace_edit` maps to `Fal___video_to_video` through `call_media_tool`.
Wan is the default edit tier. Supply `video_url`, the requested `edit_mode`, a priced model
and resolution, and explicit `num_frames`. Discover the free `Fal___list_fal_models` for limits.
For `inpainting`, provide exactly one of `mask_video_url` and `mask_image_url`.
For `outpainting`, enable at least one expansion side and optionally set `expand_ratio`.
For `reframe`, use `zoom_factor` or `trim_borders`; the prompt may be omitted.
For `depth` or `pose`, set `preprocess` as needed. `freeform` requires an explicit native
`task`; masked freeform also needs `task="inpainting"` and one mask.
Only send controls accepted by the selected route. An unknown billing combination is a blocker.

`runway_aleph_edit` maps to `Runway___video_to_video`. Use `model="aleph2"`,
`video_path_or_url`, `prompt`, and measured `video_duration_seconds` for a 2 through 30
second source. The Studio host measures the owned bytes before billing. A `runway://`
source upload cannot be measured for an Aleph Studio quote. Use owned Studio media,
a supported HTTPS source, or a supported data URI instead.
Optional guidance uses `reference_image_path_or_url` and `reference_seconds`.
Do not send an output duration or deprecated ratio to Aleph. Consult
`Runway___list_runway_models` for supported limits and retain required Runway attribution.
`luma_ray3_modify` maps to `Luma___modify_video` (model `ray-3.2`) for an explicit Luma request or a
look change that keeps the performance. Supply exactly one source, `video_path_or_url` (MP4) or
`source_generation_id`, plus its measured `source_duration_seconds` of 5 or 10; other lengths have
no published price and are refused. Optional `strength` must be a documented value.
Luma output rights follow its API terms (no training or evaluation datasets, restricted
redistribution), so Luma outputs are never training-eligible.

Submit once. Poll `Fal___get_video_task`, `Luma___get_video_task` or `Runway___get_runway_task` with the saved
`job_id` and `download=true`. Space Runway polls at least five seconds apart.
Keep successful unaffected clips. A poll failure never authorizes a replacement paid job.
Inspect the actual artifact and compare the changed region before accepting the edit.

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
