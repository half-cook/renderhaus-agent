---
name: motion-graphics
description: Assemble lower thirds, captions, simple motion, and explainers using the built Remotion timeline contract.
metadata:
  include_tools: call_editor_tool call_media_tool
  gateway_tools: Remotion___render_timeline Remotion___get_render_progress Remotion___export_nle_timeline Seedream___text_to_image Seedream___image_to_image Runway___text_to_image Runway___image_to_image Runway___get_runway_task
---

# Motion graphics

Read `read_studio_context` and reuse existing assets. Search Gateway for Remotion's
exact `render_timeline` schema. `remotion_render` maps to `Remotion___render_timeline`
through `call_editor_tool`. Build its native `title`, `visuals`, `audio_tracks`,
`text_overlays`, `aspect_ratio`, and `fps` arguments. Do not send arbitrary JSX,
a composition source string, or an invented animation contract.

Each visual needs `kind`, `url`, and `duration_seconds`. Set timing with `start_seconds`
and `source_in_seconds`. Use supported `motion`, `scale`, position, `fit`, and transitions
for simple movement. Text overlays need `text`, `start_seconds`, and `duration_seconds`;
choose native position, color, size, weight, and fades. The built contract supports these
titles and motions; arbitrary per-word kinetic typography or custom components need a
future integration. Explain that limit for a brief requiring unsupported animation.

For a missing image asset, read [product images](../product-images/SKILL.md).
Use `call_media_tool` with `Seedream___text_to_image` or `Seedream___image_to_image`.
Explicit Gen-4 Image requests use `Runway___text_to_image` or `Runway___image_to_image`;
poll `Runway___get_runway_task` until completed and save the image before assembly.
Ideogram text-in-image and Recraft SVG generation are provider-pending. Do not promise
editable vector output from the built raster image tools.

Submit one render and preserve `render_id`, `bucket_name`, and `output_key` unchanged.
Poll `Remotion___get_render_progress` and inspect the completed MP4 before delivery.
For a file-based editor handoff, read [Resolve handoff](../resolve-handoff/SKILL.md)
and use `Remotion___export_nle_timeline`. Bake unsupported titles or effects before export.
Do not claim NLE export renders those effects automatically.

The external remotion-dev skills repository is optional reference material only.
No upstream skill content is vendored here, and no upstream licence grant is assumed.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
