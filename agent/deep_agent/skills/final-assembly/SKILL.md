---
name: final-assembly
description: Assemble existing assets into a Remotion video, verify the actual MP4 and require final delivery QC evidence before completion claims.
metadata:
  remotion_backend: configured
  remotion_features: clip_timing transitions fit_position scale motion titles captions srt_captions audio_mix canvas encoding
  include_tools: call_editor_tool
  gateway_tools: Remotion___export_nle_timeline Remotion___get_render_progress Remotion___render_timeline Remotion___render_ad_variants Ffmpeg___ffmpeg_tool Remotion___deliver_render Remotion___qc_deliverable
  routing_tools: remotion_render ad_variant_matrix ffmpeg_tool delivery_render deliverable_qc
---

# Final assembly

For a SKU/price/CTA/logo table, read [ad variant matrix](../remotion-ad-variant-matrix/SKILL.md).
Use Remotion___render_ad_variants with plan, render_first and render_batch stages.
Both render stages pause for human approval even in autonomous mode. Review the first
outputs before batch approval. Never bypass the sample hash gate with individual renders.
Ffmpeg___ffmpeg_tool supplies fixed free inspection operations on the local job directory.

Read read_studio_context and project shot plans. Reuse existing managed asset versions.
Search x_amz_bedrock_agentcore_search for Remotion render_timeline and get_render_progress.
Build the typed timeline according to the returned schema. Include ordered clips, precise
durations, audio, and the requested aspect ratio.
Omit `output_resolution` or use `source` by default. The renderer measures video dimensions
and uses the largest source short edge, capped at the aspect ratio's default canvas.
A 1280x720 source at 16:9 delivers 1280x720. Mixed 720p and 1080p sources use 1920x1080.
Images alone use the default canvas. If no video dimensions can be measured, keep the
default canvas with a warning. Mixed timelines use measured videos and warn about unknown
dimensions. Never infer source resolution from the requested provider setting.
Set `output_resolution` to `720p`, `1080p`, `1440p`, or `2160p` only for an explicit
customer resolution request. Larger canvases resample pixels and add no detail. For actual
video enhancement, read [upscale](../upscale/SKILL.md) and propose Topaz through its existing
cost approval. Choosing a lower Wan resolution produces a lower-resolution deliverable
unless the customer requests upscaling. Keep the capability defaults and cost policy.
Omit `fps` and `video_bitrate` unless the customer sets them. The renderer uses the primary
video's measured frame rate and preserves its quality. A cinematic brief alone does not set fps.
Lambda supports captions and motion effects. The local ffmpeg backend supports trims, fit,
fades, audio timing/volume/fades, allow-listed text fonts with fit guards, and positioned/scaled
overlays. Both backends accept fixed grade/motion presets and centre rotation. New font/box props need a
compatible Lambda composition version or return a clear refusal. Use durable URLs for Lambda;
for local assembly use provider-returned
plain `output_path` fields in visuals/audio_tracks, without a `file://` prefix. Call call_editor_tool with
Remotion___render_timeline once. Save render_id, bucket_name, and output_key unchanged.
Call Remotion___get_render_progress with those identifiers. The host polls the same render.
If waiting times out, preserve the ID and describe pending work. Never start a replacement
because a poll failed. A successful poll must provide the actual MP4 before finishing.
Report a dry-run timeline as a preview and an incomplete export.
For the saved local MP4, read [delivery render](../remotion-delivery-render/SKILL.md) for a
named delivery preset or [deliverable QC](../remotion-deliverable-qc/SKILL.md) for inspection.
Keep the requested source resolution and measured FPS. The local renderer emits fixed AAC;
its schema does not offer a PCM intermediate or arbitrary codec options. Do not re-render an
existing MP4 merely to finish its AAC/container. Reuse integrated loudness/QC evidence.
Open and play the actual completed artifact. Do not call it finished or delivered unless
an actual final QC report exists and passed. If QC fails or is missing, disclose failed or
pending checks verbatim and describe the artifact as incomplete. A technical pass does not
replace required human editorial review. Lambda finishing remains unverified; do not switch
backends or claim a local inspection of an unavailable remote artifact.
State the successful result's delivered `width` and `height` in the final summary and
Markdown. Include `source_resolution` and all resolution warnings. If `upscaled` is true,
say, for example, "1920x1080, upscaled from 1280x720; no added detail."
Never describe a native 720p delivery as 1080p or a resampled source as native 1080p.
If source dimensions could not be measured, disclose that uncertainty.

For an editor ZIP rather than a rendered video, read
[Resolve handoff](../resolve-handoff/SKILL.md) and use Remotion___export_nle_timeline.
A handoff ZIP does not satisfy final MP4 delivery.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.

The configured Remotion backend must support every requested feature. Unsupported features refuse before media I/O
or AWS submission. Crop/pad reframing requires local/worker; fitted font/box overlays require
Lambda overlay contract version 2 or local/worker. Use named motion presets; arbitrary render
keyframes, per-word kinetic typography and custom components remain unavailable.
For an existing caption transcript, `subtitles_srt` accepts bounded inline numbered SRT
instead of a `subtitles` list. Captions burn in as literal output-timed text; validate fit.
