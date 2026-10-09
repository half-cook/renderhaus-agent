---
name: remotion-aspect-ratio-variants
description: Reformat approved flat masters or existing Remotion timelines to aspect variants using static centre or safe-zone crops, optional planner-supplied subject boxes and blurred padding. Return candidate MP4s with contact sheets for human editorial approval. Refuse detectors, arbitrary commands and parked Resolve Smart Reframe.
metadata:
  include_tools: call_editor_tool
  routing_tools: ad_variant_matrix remotion_render ffmpeg_tool
  gateway_tools: Remotion___render_ad_variants Remotion___render_timeline Remotion___get_render_progress Ffmpeg___ffmpeg_tool
---

# Remotion aspect ratio variants

Use this skill for versions of an approved master in `9:16`, `1:1`, `4:5`, `16:9` or
`2.39:1`. Reframing is editorial: every output is a candidate, with a contact sheet for a
person to approve. Render spending approval does not establish editorial acceptance.
Read `read_studio_context` and discover the actual Gateway schema before each operation.

## Choose the source path

- Existing Remotion-native timeline: use `remotion_render` (`Remotion___render_timeline`)
  to rearrange the existing layers for the requested canvas. Preserve editable overlays
  instead of cropping a finished composition. Arbitrary JSX and new composition source
  are unsupported. New per-item crop windows and blurred-pad options are local-only and
  explicitly refused by Lambda; ordinary supported timelines keep their existing backend.
- Flat master, several aspects or shots: use `ad_variant_matrix`
  (`Remotion___render_ad_variants`) with `brief.reframe_only=true` and rows containing
  `variant_key` and `aspect`. It builds per-shot timeline items and renders through the
  existing Remotion path. No price, logo or CTA overlay is added in this mode.
- Flat master, one static crop: use `ffmpeg_tool` (`Ffmpeg___ffmpeg_tool`) with
  `op="reframe_crop"`; use `reframe_pad_blur` to retain the whole foreground frame.
- Copy, price and logo variants: read [ad variant matrix](../remotion-ad-variant-matrix/SKILL.md).
- Generating missing background pixels is a paid generative edit. Read
  [edit-v2v](../edit-v2v/SKILL.md), disclose the cost and obtain approval. Blurred padding
  uses existing pixels and is the free alternative.

## Plan static windows

1. Call `probe` with the job-relative master path. Read dimensions, rotation, FPS, duration
   and audio. Use display-oriented coordinates once; a rotation-tagged portrait phone
   clip must not be reframed a second time. VFR cadence cannot be preserved by the CFR
   timeline renderer; disclose the source cadence and conversion warning before rendering.
2. For a multi-shot master, call `detect_scenes` with `params.T` in `0.1..0.6` (default
   `0.3`). Review the bounded scene times. Scene detection finds cuts, never people.
3. Optionally sample frames with `extract_frames` and supply the planner's vision box as
   JSON `{x,y,width,height}` in display-oriented source pixels. Box validation proves
   geometry only. No detector runs and nobody is identified. Without a box, use the frame
   centre or the requested `anchor` (`center`, `top`, `bottom`, `left`, `right`).
4. Call pure `crop_plan_preview` with `source_width`, `source_height`, `aspect` and optional
   `rotation`, `subject_box`, `crop_box`, `anchor`, `safe_zone` and `allow_upscale`.
   `crop_box` uses even integer `x,y,width,height`. It must fit inside the display frame.
   `safe_zone` accepts `top`, `bottom` and `side` fractions in `0..0.49`.
   The planner clamps one static window per shot to the frame. If the subject and safe
   margins cannot fit, the decision is `pad_blur`, which retains the whole foreground.
   No pans, tracking or mid-shot crop changes are available.
5. In matrix rows, supply optional `subject_box`, `crop_box`, `anchor`, `safe_zone` and
   `allow_upscale`; shared defaults may be in the brief. Use either `scene_times` (cut
   seconds) or `shots` with contiguous `{from_s,to_s}` spans and optional per-shot boxes
   and anchors. Spans cover the selected `start_s..end_s` range and are capped at 60 shots.
   Keep the same complete rows and brief across all matrix stages.

## Render and inspect

The fixed render ops take `op`, `job_id`, `input_path` and `params`. `reframe_crop` takes
`aspect`; `reframe_pad_blur` takes the aspect enum as `size`. Cropping accepts validated `subject_box`, `crop_box`, `safe_zone`, `anchor` and
`allow_upscale`. Padding accepts only `size`, `safe_zone` and `allow_upscale`.
Actual source dimensions come from probing the file. Neither op accepts caller-supplied
source dimensions, arbitrary filters, codec strings, output paths or command arguments.
Outputs use generated versioned names. The tool runs on the host owning the job directory,
with ffmpeg installed, and never fetches network media. Pure preview needs no media file.

For matrix renders, call `plan`, then show the count, aspects, plan hash, crop/pad decisions
and cost. `render_first` pauses for approval even in autonomous mode. Inspect the first
MP4s and contact sheets before requesting `render_batch` approval for that same hash.
These stages retain the existing matrix gates and never invent an approval field.
Every output includes a contact sheet and `editorial_review="pending"`; the returned
`candidate_set=true` does not certify the framing. Present shots using padding and any
warnings for a person to approve. Check burned-in legal lines, price, logo and captions
at the beginning, middle and end. Request an approved clean/layered source if those pixels
cannot fit, rather than cropping them away. Clarify logo ownership before removing a mark.

Probe each completed file. Report delivered width and height, `source_resolution`, FPS,
audio, SAR `1:1`, crop/pad method and every resolution warning. Preserve the measured FPS
and bitrate policy. The nominal maximum targets are `1080x1920`, `1080x1080`, `1080x1350`,
`1920x1080` and `1920x804` respectively. By default, crops never upscale beyond available
source pixels. A `1920x1080` master therefore produces a smaller native portrait crop;
`1080x1920` requires explicit `allow_upscale=true` and must say "upscaled from 1920x1080;
no added detail". Use the [Topaz upscale skill](../upscale/SKILL.md) for actual enhancement
with its existing approval. Tiny sources use even-pixel rounding with a warning.

Safe-zone fractions are configuration in `providers/remotion/ad_layouts.json`, not certified
platform requirements. The `9:16` placeholders are top `0.14`, bottom `0.22`, side `0.06`.
Other presets use `0.08`, `0.12`, `0.06`. Confirm margins with the destination brief.

## Hard rules

Resolve is parked by Satya (2026-10-09). Refuse Resolve Smart Reframe and other Resolve-only
operations; call no `resolve-*` tool or skill. No free-form shell, pasted script, arbitrary
ffmpeg arguments, executable override, filtergraph, codec or unlisted op is allowed. Offer
the nearest fixed op. Options must work on both backends or return a clear unsupported-backend
refusal before any request. Do not switch backends or disable dry-run silently. Matrix and
new crop/pad timeline options are refused on Lambda; existing Lambda timelines remain usable.

No detector or detector dependency is available in this branch: no YOLO, Ultralytics,
MediaPipe or OpenCV. No GPL/AGPL detector, AGPL code or non-commercial code/weights is copied.
Optional planner vision boxes only choose crop centres; never identify people. Preserve
source rights and consent requirements. Paid generation always pauses with a cost estimate;
local ffmpeg ops are free and matrix sample/batch gates remain mandatory. Actual files and
human editorial review are required; queued jobs and dry-runs are not completed deliveries.

## Not yet available

Delivery presets, loudness measurement/normalisation and full deliverable QC belong to
`feat/remotion-delivery-qc`. Its three skills are absent here. Do not claim loudness-checked
or delivery-certified output. A later detector branch may evaluate MediaPipe/OpenCV and
model licences; no detector is installed or invoked in this branch.

## Licence

This branch adds no model or weights and grants no training rights. Local media cost is
$0. The existing configurable Remotion licence allowance is not a verified local charge.
Remotion is free for individuals and teams of up to three; Company Automators licensing
at four or more costs $0.01 per successful render with a $100/month minimum. Whether this
local ffmpeg compositor is metered remains UNVERIFIED. See [licence FAQ](https://www.remotion.dev/docs/license/faq)
and [terms](https://www.remotion.dev/docs/terms), read 2026-10-09. FFmpeg licence depends on
the installed build; see [FFmpeg legal](https://ffmpeg.org/legal.html), read 2026-10-09.
No binary or upstream code is redistributed. Demo media is generated locally.
