---
name: edit-v2v
description: Edit existing footage through Wan VACE, Luma Modify, or Runway Aleph according to tier and required controls.
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
The edit ladder is Wan VACE for Draft, Luma Modify for Standard, and Runway Aleph for Premium.
Prefer Aleph for faithful plate or multi-shot edits unless Draft or confidential.
This is a routing preference, not a native multi-shot control. For Wan, supply `video_url`, the requested `edit_mode`, a priced model
and resolution, and explicit `num_frames`. Discover the free `Fal___list_fal_models` for limits.
For `inpainting`, provide exactly one of `mask_video_url` and `mask_image_url`.
For `outpainting`, enable at least one expansion side and optionally set `expand_ratio`.
For `reframe`, use `zoom_factor` or `trim_borders`; the prompt may be omitted.
For `depth` or `pose`, set `preprocess` as needed. `freeform` requires an explicit native
`task`; masked freeform also needs `task="inpainting"` and one mask.
Only send controls accepted by the selected route. Unknown prices remain visible; the existing
spending cap blocks unknown-cost submissions when enabled.

`runway_aleph_edit` maps to `Runway___video_to_video`. Use `model="aleph2"`,
`video_path_or_url`, `prompt`, and measured `video_duration_seconds` for a 2 through 30
second source. The Studio host measures the owned bytes before billing. A `runway://`
source upload cannot be measured for an Aleph Studio quote. Use owned Studio media,
a supported HTTPS source, or a supported data URI instead.
Optional guidance uses `reference_image_path_or_url` and `reference_seconds`.
Do not send an output duration or deprecated ratio to Aleph. Consult
`Runway___list_runway_models` for supported limits and retain required Runway attribution.
`luma_ray3_modify` maps to `Luma___modify_video` (model `ray-3.2`) for Standard edits or an explicit Luma request. Supply exactly one source, `video_path_or_url` (MP4) or
`source_generation_id`, plus its measured `source_duration_seconds` of 5 or 10; other lengths have
no published price and are refused. Optional `strength` must be a documented value.
Luma output rights follow its API terms (no training or evaluation datasets, restricted
redistribution), so Luma outputs are never training-eligible.

Submit once. Poll `Fal___get_video_task`, `Luma___get_video_task` or `Runway___get_runway_task` with the saved
`job_id` and `download=true`. Space Runway polls at least five seconds apart.
Keep successful unaffected clips. A poll failure never authorizes a replacement paid job.
Inspect the actual artifact and compare the changed region before accepting the edit.

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
