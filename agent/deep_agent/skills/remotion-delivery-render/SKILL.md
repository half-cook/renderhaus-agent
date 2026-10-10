---
name: remotion-delivery-render
description: Finish an existing local render or approved matrix manifest with a named H.264/AAC delivery preset, versioned naming, loudness and technical QC evidence. Refuse unsupported codecs, public links, channel publishing and backend changes.
metadata:
  include_tools: call_editor_tool
  routing_tools: delivery_render deliverable_qc ffmpeg_tool remotion_render
  gateway_tools: Remotion___deliver_render Remotion___qc_deliverable Ffmpeg___ffmpeg_tool Remotion___render_timeline Remotion___get_render_progress
---

# Remotion delivery render

Use `delivery_render`, mapped to `Remotion___deliver_render`, for finishing a saved file.
Read `read_studio_context` and discover the exact Gateway schema through `call_editor_tool`.
This tool runs fixed FFmpeg operations on the local job host. It does not render a new
timeline. For a composition that still needs rendering, use
[final assembly](../final-assembly/SKILL.md), poll the same render to completion, then finish
its actual file here. An existing MP4 conversion uses this tool without another timeline render.

## Select the preset

The maintained table is `providers/remotion/delivery_presets.json`. These dimensions are
maximum canvases. Preserve measured source FPS, within 1 to 120, and avoid upscaling.
An explicit exact-size request belongs in the QC spec and must pass on the actual file.

| Preset | Maximum canvas | Loudness target | True peak |
|---|---|---|---|
| `social-vertical` | 1080x1920 | -14 LUFS | -1.5 dBTP |
| `social-feed` | 1080x1080 | -14 LUFS | -1.5 dBTP |
| `web-1080p` | 1920x1080 | -14 LUFS | -1.5 dBTP |
| `broadcast-proxy` | 1920x1080 | -23 LUFS | -1 dBTP |
| `review-proxy` | 960x540 | measured without normalisation | no target |
| `email-720p` | 1280x720 | -14 LUFS | -1.5 dBTP |
| `podcast-streaming` | 1920x1080 | -16 LUFS | -1.5 dBTP |

The presets use H.264 High, `yuv420p`, MP4 faststart and AAC at 48 kHz. Keep one or two
source channels. AAC is 192 kbit/s, except the review proxy at 96 kbit/s. Targeted presets
use LRA 11 and a 0.5 LU tolerance. These are placeholder delivery targets; confirm the destination channel specification. Broadcast proxy
checks programme loudness and cannot certify a broadcaster's full compliance spec or
dialogue-gated loudness. Use an explicit customer spec for additional constraints.

ProRes, DNx, H.265, 8K and caller-selected codecs are unsupported. Explain the unsupported
request before dispatch; do not substitute a codec, silently downscale, or change backends.

## Apply local finishing before delivery

Use `Ffmpeg___ffmpeg_tool` for these changes to staged job files. Discover its schema
and pass `op`, `job_id`, `input_path` and the documented `params`. These operations are
free and have no spending approval. Keep `FFMPEG_DRY_RUN` unchanged.

| Operation | Parameters | Result |
|---|---|---|
| `burn_subtitles` | `subtitle_path`; optional `subtitle_batch`, `font_id`, `font_size`, `colour`, `outline`, `margin` | Burn an existing SRT or restricted ASS into the video |
| `export_srt` | `cues` with `{start,end,text}` in seconds; optional `export_batch` | Write numbered UTF-8 cues with millisecond timestamps |
| `color_match_lut` | Optional `lut_path`, `intensity`, `grade_preset`, `brightness`, `contrast`, `saturation` | Apply a supplied `.cube` and a named bounded grade |
| `make_proxy` | `height` 480 or 540, `crf` 18 to 35, `proxy_preset` | Write an H.264 review preview with faststart, hash and probe evidence |

Subtitle and SRT batches contain at most four additional items, for five files per call.
Styles are shared across a subtitle batch. Fonts come from the fixed DejaVu system catalog;
font paths, embedded fonts and ASS override commands are unavailable. Text cues must be
ordered, non-overlapping and inside 0 to 600 seconds. `export_srt` requires a safe
`input_path` label but does not read that file or require a binary. It does not transcribe.

No LUT is bundled. Stage a rights-cleared `.cube` in the job, then use intensity 0 to 1.
The grade presets are `none`, `warm`, `cool` and `contrast`. Applying a supplied LUT does
not compute a match from reference footage. Review skin tones and actual frames yourself.

Proxy presets are `fast`, `veryfast` and `ultrafast`. Proxies preserve source cadence,
avoid upscaling and remain review artifacts. Existing named delivery proxy requests still
use `delivery_render`. Neither proxy success nor subtitle burning certifies editorial
content or final delivery QC. Follow the saved-file delivery workflow after finishing.
Use [audio cleanup](../remotion-loudness-qc/SKILL.md) before measuring or normalising audio.

All inputs and sidecars stay in the job directory. Invalid parameters fail explicitly.
A failed batch returns no successful outputs. Missing fonts, filters or binaries are
failures. The worker must own the files; a Lambda host without these dependencies cannot
perform binary operations. Never switch backends, use a pasted command or call Resolve.

## Finish the saved file

The Gateway tool accepts `job_id`, `input_path`, `manifest_path`, `preset`, `spec`,
`campaign`, `sku`, `locale`, `aspect` and `upload`. Use one staged input path or an approved
matrix manifest. The path is relative to the job directory. Files must be regular,
immutable job assets. Network URLs, symlinks and escaping paths are refused.
Inputs are bounded to 128 MiB and 600 seconds. Each output is bounded to 16 MiB.

1. Resolve the requested preset and keep the locked source, manifest and approval evidence.
   A matrix sample or batch still requires its existing approval gates. Spending approval
   does not approve framing or copy. Read [ad matrix](../remotion-ad-variant-matrix/SKILL.md)
   or [aspect variants](../remotion-aspect-ratio-variants/SKILL.md) when those stages are needed.
2. Call the tool on the completed input. It probes the file, applies the fixed H.264 preset,
   finishes AAC, performs programme loudness measurement and one normalisation when needed,
   then re-measures the final encoded audio. Reuse that returned evidence. Do not normalise
   the same finished output a second time because a workflow lists loudness separately.
3. Inspect the final [deliverable QC](../remotion-deliverable-qc/SKILL.md) result. A failed
   error check blocks a completed delivery. Preserve failed checks verbatim and name the
   render, mix, reframe or finishing step that needs correction. Re-test the corrected file.
4. Open and play the actual MP4. Report its versioned filename, hash, delivery manifest and
   QC report. A successful tool return, a dry-run or a queued render is incomplete evidence.

The existing local `Remotion___render_timeline` API produces fixed AAC audio. It cannot
request a PCM intermediate or arbitrary renderer options. A supplied PCM
intermediate can use the fixed `mux_aac` operation; do not invent an `audioCodec` field.
Lambda finishing is unverified and cannot read this local job directory. Return a clear
unsupported-backend result; never switch the configured renderer or a dry-run flag.

## Name and report the output

The tool allocates `<campaign>__<sku>__<locale>__<aspect>__v<n>.mp4` and returns
`manifest_path` and the QC evidence at `report_path`. Never overwrite a previous version or request
a custom output path. Keep safe campaign, SKU, locale and aspect values from the brief.
Include source/input hashes, preset, measured output dimensions, FPS, audio, tool versions,
loudness before/after, warnings and per-file failures in the review.

State the delivered width and height and the render's `source_resolution`. A standalone
file has unknown source provenance; its measured `input_resolution` does not establish the
resolution of original camera or generated media. Keep unknown dimensions unknown. Include
all resolution warnings. A native 1280x720 file is 720p. A resampled 1920x1080 canvas must
say "upscaled from 1280x720; no added detail". For actual enhancement use the
[Topaz upscale skill](../upscale/SKILL.md) with its existing cost approval.

This branch returns local artifacts. `upload=true`, S3 uploads, public links and direct
YouTube, Meta or TikTok account publishing are unsupported. Never imply that an upload
occurred or request account credentials. A later configured upload step must retain the QC gate.

## Hard rules

Local finishing and inspection are free. Keep the quality-first capability defaults,
confidential metadata and existing paid-generation approvals unchanged. Resolve remains
parked. Do not call a Resolve tool or skill. No free-form shell, filtergraph, `ffmpegOverride`,
executable override, pasted script or unlisted FFmpeg op is allowed. No model, weights,
training permission, third-party source code or binary redistribution is added here.

## Sources

The fixed implementation and Gateway schema define available behavior. [FFmpeg legal](https://ffmpeg.org/legal.html) documents build-dependent
licensing. Remotion render licensing remains covered by the existing
[ad matrix guide](../remotion-ad-variant-matrix/SKILL.md).
