---
name: remotion-deliverable-qc
description: Check an actual local deliverable or matrix manifest against a named preset and structured spec, record technical pass/fail with detection and loudness evidence, and keep caption/identity vision review explicit. A failed QC gate blocks completion and upload.
metadata:
  include_tools: call_editor_tool
  routing_tools: deliverable_qc ffmpeg_tool
  gateway_tools: Remotion___qc_deliverable Ffmpeg___ffmpeg_tool
---

# Remotion deliverable QC

Use `deliverable_qc`, mapped to `Remotion___qc_deliverable`, through `call_editor_tool`.
Read `read_studio_context`, discover the Gateway schema, and inspect the actual saved file.
This tool reads local artifacts. It never generates, renders, uploads or changes a backend.
Identity consistency belongs to [continuity QC](../continuity-qc/SKILL.md).

The arguments are `job_id`, `input_path`, `manifest_path`, `preset` and `spec`. Use one
job-relative file or an approved matrix manifest. The maintained preset table is
`providers/remotion/delivery_presets.json`; read [delivery render](../remotion-delivery-render/SKILL.md)
for the preset IDs and the limits. A successful rendering return is a reason to run QC,
not evidence that QC passed.

## Load the spec and review allowances

Use the locked brief and matching manifest row. `spec` supports `expected_width`,
`expected_height`, `expected_fps`, `expected_duration_s`, `require_audio`, `master_path`,
`expected_sha256`, `expected_filename`, `audio_channels`, `overlay_boxes`, `safe_zone` and
`require_vision` according to the discovered schema. Targets use `I`, `TP`, `LRA` and
`tolerance_lu`. Detection thresholds use `black_d`, `freeze_d`, `silence_d`, `pix_th`, `n`
and `noise`. `allowed_black`, `allowed_freeze` and `allowed_silence` use finite
`{start_s,end_s}` intervals.
Only intentional fades, static holds and silence documented in the spec can pass an allowance.
Never excuse a detected issue after the fact because an end card might be static.

Exact dimensions and expected duration come from the requested deliverable and measured
render, not an assumed nominal canvas. Preserve native source size when a preset cap would
require upscaling. An explicit exact-size requirement must fail if the actual file misses it.
The measured `input_resolution` of a standalone file does not establish `source_resolution`
provenance. Keep unknown source dimensions unknown and preserve render resolution warnings.

## Inspect the technical result

The fixed wrapper runs the checks and returns the QC JSON at `report_path`. Each check has severity, pass/fail
and measured detail. Inspect its container/codec/profile/pixel format, delivered dimensions,
square-pixel SAR, frame rate and frame cadence, expected duration, audio presence, 48 kHz
AAC/channel count, sample clipping, programme loudness/true peak when specified, faststart,
black/freeze/silence intervals, naming and checksum. A preset alone does not justify an
assumed FPS or duration. Duration must meet the one-frame tolerance from the spec.

`frame_cadence` reads actual frame timestamps. Probe's average and nominal frame-rate labels
alone cannot establish CFR. If cadence cannot be verified, report that failed or pending check.
`ssim` compares matching first and last frames against `master_path` when supplied. Preserve
its measured result; it is informational evidence, not a continuity or exact-text test.

Review the contact sheet and extracted review frames. For a specific missed check, the
free `ffmpeg_tool`, `Ffmpeg___ffmpeg_tool`, accepts `op`, `job_id`, `input_path` and `params`.
The available technical ops are `probe`, `frame_cadence`, `volume_stats`, `measure_loudness`,
`detect_black`, `detect_freeze`, `detect_silence`, `check_faststart`, `extract_frames`,
`contact_sheet`, `ssim` and `sha256`. Discover each numeric parameter contract.
Use the [loudness guide](../remotion-loudness-qc/SKILL.md) for programme targets and re-measurement.
Do not normalise a file merely to inspect it.

## Keep visual review explicit

Safe-zone geometry checks supplied Remotion overlay boxes against the configured margins.
It does not locate text already burned into a flat master. Read
[aspect variants](../remotion-aspect-ratio-variants/SKILL.md) for the placeholder safe zones.
Inspect extracted frames for cropped subjects, clipped captions, logos, price and legal copy.
Record concrete findings per frame rather than "looks fine".

The local tool cannot perform vision review or deterministic OCR string comparison. Vision
remains a pending warning by default. If `require_vision=true`, the missing review is an
error and prevents a technical pass. Do not set a caller-supplied vision/OCR passed flag.
Never assert exact price, CTA, legal-line or SKU equality from successful rendering or box
geometry. Exact end-card OCR verification is deferred to `feat/remotion-ocr-verification`.
A separately performed planner vision review must report its evidence and limitations.

## Report failures before completion

A technical pass means no failing error checks in the actual QC report. It does not approve
framing, copy, rights or editorial choices. Matrix and aspect outputs retain their existing
human sample and editorial approval gates.

On failure, include every failed check verbatim, its measured detail and the corrective
step. Black/freeze detection can require a render or approved allowance correction; audio
can require upstream mixing or one loudness finish; a safe-zone failure needs reframing.
Run QC again on the corrected output. Never claim passed from a tool status alone or upload
a known failed deliverable. A blocked check, missing file, dry-run or pending visual requirement
is incomplete validation. Open/play the actual artifact before reporting completion.

Return the QC report, contact sheet, checksum, preset/spec, passed/failed counts, delivered
width and height, `source_resolution`, measured `input_resolution`, and all warnings.
For a resampled canvas, disclose the original measured source size and "no added detail".
Use [Topaz upscale](../upscale/SKILL.md) with its existing approval for actual enhancement.

## Hard rules

Files remain confined to the local job host. Escaping paths, symlinks, network inputs,
free-form shell, filtergraphs, scripts, executable overrides and unlisted ops are refused.
Resolve remains parked. Local QC is free and adds no model or weights. Keep confidential
metadata, source rights, training eligibility and the existing paid-generation approvals unchanged.

## Sources

The fixed implementation and Gateway schema define the current checks. [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html)
documents the detection and SSIM filters. This wrapper redistributes no binary or upstream code.
