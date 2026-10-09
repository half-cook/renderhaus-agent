---
name: motion-graphics
description: Assemble lower thirds, captions, simple motion, and explainers using the built Remotion timeline contract.
metadata:
  include_tools: call_editor_tool call_media_tool
  gateway_tools: Remotion___render_timeline Remotion___get_render_progress Remotion___export_nle_timeline HyperFrames___render_composition
  routing_tools: remotion_render hyperframes_render
---

# Motion graphics

Remotion is the default renderer. For an explicit HyperFrames or HTML-template request, read
[HyperFrames](../hyperframes/SKILL.md) and follow the host's optional-tool route.

Read `read_studio_context` and reuse existing assets. Search Gateway for Remotion's
exact `render_timeline` schema. `remotion_render` maps to `Remotion___render_timeline`
through `call_editor_tool`. Build its native `title`, `visuals`, `audio_tracks`,
`text_overlays`, `aspect_ratio`, and `fps` arguments. Do not send arbitrary JSX,
a composition source string, or an invented animation contract.
Omit `output_resolution` unless the customer requests a resolution. Follow
[final assembly](../final-assembly/SKILL.md) for source-sized canvases and truthful delivery
dimensions, including warnings when clips are upscaled or source dimensions are unknown.

Each visual needs `kind`, `url`, and `duration_seconds`. Set timing with `start_seconds`
and `source_in_seconds`. Use supported `motion`, `scale`, position, `fit`, and transitions
for simple movement. Text overlays need `text`, `start_seconds`, and `duration_seconds`;
choose native position, color, size, weight, and fades. The built contract supports these
titles and motions; arbitrary per-word kinetic typography or custom components need a
future integration. Explain that limit for a brief requiring unsupported animation.

For missing image assets, read [still images](../image-gen/SKILL.md) and use the matching
default or specialist. Recraft vector output and Ideogram text-only edits use the built
image-gen exceptions. A supplied existing Ideogram asset needs no generation.
Do not promise SVG from a raster tool.

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
