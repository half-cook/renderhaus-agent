---
name: remotion-ad-variant-matrix
description: Validate a retail table, compose price/CTA/logo/legal overlays on a locked master, render the first SKU at each aspect for human review, then render an approved batch with hashes and a manifest. Refuse arbitrary shell commands and parked Resolve operations.
metadata:
  include_tools: call_editor_tool
  routing_tools: ad_variant_matrix remotion_render ffmpeg_tool
  gateway_tools: Remotion___render_ad_variants Remotion___render_timeline Remotion___get_render_progress Ffmpeg___ffmpeg_tool
---

# Remotion ad variant matrix

Use this skill for a table of SKU, price, CTA, logo, legal copy, locale and aspect variants.
Use [motion graphics](../motion-graphics/SKILL.md) for new template design.
Read `read_studio_context`, reuse the locked master and discover the exact Gateway schema.
The `ad_variant_matrix` alias is `Remotion___render_ad_variants` through `call_editor_tool`.
It builds timeline documents and calls the existing `Remotion___render_timeline` code path.
Do not bypass the matrix gates by issuing individual timeline renders for a batch request.

## Table contract

The required columns are `variant_key`, `sku`, `price_text`, `cta_text`, `logo_asset`,
`legal_text`, `locale` and `aspect`. Optional columns are `product_asset`, `vo_asset`,
`start_s` and `end_s`. The allowed aspects are `9:16`, `1:1`, `4:5` and `16:9`.

Every required cell must contain a value. The table has 1-100 rows. Reject duplicate
`(sku, locale, aspect)` rows and duplicate `variant_key` values. `variant_key`, `sku` and
`locale` use 1-40 ASCII letters, digits, underscores or hyphens.
Price, CTA, legal copy and SKU names come verbatim from the table. Never compute a discount,
round a price, translate legal text or infer a currency format. Request approved replacement
text when copy is missing or too long. The brief's locale legal requirements cannot be
satisfied by another locale's copy.

Assets must be immutable regular files inside the job directory. External URLs, mutable
S3 references, escaping paths and symlinks are refused. An operator must stage approved
files in that directory before planning. Probe the media and require alpha on logos when
the brief expects it. The tool hashes the input content into the plan, so replacing an asset
or changing copy requires a new plan and a new approval. Preserve the master's measured FPS,
bitrate and source resolution unless the user requests a different output setting.

## Matrix stages

`Remotion___render_ad_variants` accepts `stage`, `job_id`, `brief`, `rows`, `master_asset`,
`plan_hash` and `concurrency` (integer 1-2). Discover the schema rather than inventing additional fields.
`stage` is `plan`, `render_first` or `render_batch`. Keep the same complete inputs across
stages. The host owns the approval record. Never send `approved`, `approved_by`, an OCR
match flag or another approval field as a tool argument.

1. Call `stage="plan"`. This stage is free and never renders. Inspect planned and blocked
   rows, document hashes, count, aspects, safe zones, estimated cost and estimated time.
   Stop on blocked rows. Correct the table or obtain an explicit instruction to drop a row,
   then plan again. Report the plan hash and the total estimate before rendering.
2. Call `stage="render_first"` with the returned `plan_hash`. The host pauses for human
   approval even in autonomous mode. The card states the count, aspects, cost and hash.
   This stage renders the first SKU/locale group at all table aspects belonging to it.
   Check deterministic text fit and safe-zone results. The tool extracts frames near 5%,
   50% and the end card and creates a contact sheet. Compare the price, CTA, legal line and
   SKU shown in the frames with the returned expected strings. Report concrete mismatches.
   There is no automatic OCR engine or Tesseract dependency. Do not claim exact visual
   text equality from successful rendering or geometry alone.
3. Show the frames, copy comparison and any warnings to a person. Wait for explicit
   approval of that first-variant plan hash. A spending approval authorizing the sample
   render does not establish visual acceptance of its result.
4. Call `stage="render_batch"` with the same hash and inputs. The host pauses again,
   including in autonomous mode, and records the approved sample hash. The batch refuses
   a missing or stale approved hash and refuses when first rendering failed. Respect the
   tool's bounded `concurrency`. One variant failure does not stop other rows. Read each
   failure and request corrected input rather than retrying blindly.
5. Inspect the actual output MP4s and the manifest. Verify dimensions, FPS, duration,
   text-fit/safe-zone results, checksums and per-row failures. Report planned, rendered,
   blocked and failed counts. Report `ocr_match` as unverified until a human or an actual
   vision comparison establishes it. Do not claim loudness or delivery certification.

`manifest.json` records `variant_key`, `sku`, `locale`, `aspect`, composition/template ID,
`input_props_hash`, `file`, `sha256`, `duration_s`, `qc`, `ocr_match` and `approved_by`.
Preserve native render warnings. State delivered width and height and `source_resolution`.
For a larger canvas resampled from 1280x720, say "upscaled from 1280x720; no added detail".
The [upscale skill](../upscale/SKILL.md) uses Topaz for actual enhancement with its existing
cost approval. Unknown source dimensions remain unknown.

## Flat-master mode and layouts

The tool composes the master with price, CTA, logo and legal overlays. Text or colours baked
into the master pixels cannot change. A baked product swap requires a layered source or a
separately approved generative edit. Do not promise that this overlay job changes those pixels.

The layout config is `providers/remotion/ad_layouts.json`. Its safe zones are placeholders
to confirm per destination. For `9:16`, top/bottom/side margins are 14%/22%/6%. The other
aspects use 8%/12%/6%. Text shrinks only between each field's configured minimum and maximum
font sizes. A field that cannot fit at the minimum fails with `text_overflow`.
This branch uses the render path's simple centre-crop/pad handling. It does not track subjects.

The local backend renders this matrix with real ffmpeg. The matrix tool explicitly refuses
the Lambda backend until a worker can access the same job directory. Ordinary timeline
rendering on Lambda remains available. A backend refusal is an incomplete render, never a
passing parity check. Do not switch backends silently or change a dry-run flag.

## Fixed media inspection

The free `ffmpeg_tool` alias maps to `Ffmpeg___ffmpeg_tool` through `call_editor_tool`.
Arguments are `op`, `job_id`, `input_path` and `params`. Use only the discovered parameters.
The available ops are `probe`, `extract_frames`, `contact_sheet`, `sha256`, `check_faststart`
and `volume_stats`. The tool runs on the machine owning the job directory. Binary operations
refuse a host without ffmpeg/ffprobe. It never fetches network media.
`extract_frames` accepts `params.times`, 1 to 20 finite seconds within 0 to 600, and
`params.width`, an integer within 16 to 1920. `contact_sheet` accepts `every_s`, 0.1 to 600,
`cols` and `rows`, integers within 1 to 10, and `width` and `height`, integers within 16 to
640. The other ops accept only empty `params`. Never invent an output filename or overwrite
flag. The tool generates version-safe names and reports output hashes.
`volume_stats` reports mean/sample peak. It does not certify LUFS or true peak.

## Not yet available

`remotion-aspect-ratio-variants` and subject-aware reframe ops arrive in
`feat/remotion-aspect-ratio-variants`. Delivery presets, two-pass loudness measurement and
normalisation, black/freeze detection, and per-output delivery certification arrive in
`feat/remotion-delivery-qc`. Its skills are `remotion-delivery-render`, `remotion-loudness-qc`
and `remotion-deliverable-qc`. Do not invoke those absent skills or their future ops.
The matrix outputs are review renders until those checks have actual evidence.

## Hard rules

- Resolve is parked by Satya, 2026-10-09. Magic Mask, node grading, Fairlight, ACES,
  PowerGrade, AAF conform, Neural Engine effects and `.drp` work are refused with a short
  reason and a supported alternative when one exists. Never call or edit a `resolve-*`
  skill or tool. Existing in-house NLE interchange remains a separate handoff operation.
- No free-form shell, arbitrary command line, caller-supplied filtergraph, codec, executable
  or unlisted op. Offer the nearest allow-listed op instead. Never run pasted scripts.
- Render options must work on both backends or return an explicit unsupported-backend
  refusal. No `ffmpegOverride`, network URLs in ffmpeg input paths, or machine-local props
  sent to Lambda. Use job-relative assets and deterministic documents.
- Paid generation pauses with a cost estimate. Matrix `render_first` and `render_batch`
  always pause for human approval even in autonomous mode. `plan` and ffmpeg inspection
  remain free. Never invent approval or bypass the existing autonomous spend cap.
- Never invent retail copy, clone a voice, or swap a real face here. Source rights and
  vendor consent requirements remain in force for any separately requested generation.
- No AGPL or non-commercial code/weights. No third-party source code or upstream skill
  text is copied into this implementation. Editing does not grant model-training rights.
- Verify actual files. A dry-run, queued job or successful command return is not a delivery.

## Licence and sources

Remotion's custom licence permits free use for individuals and teams of up to three people.
At four or more people operating the project, a Company License is required. Automators
is $0.01 per successful render with a $100/month minimum. The tool's per-render allowance
is configurable and is not a verified local-render charge. Local ffmpeg-compositor metering
remains unverified. See [Remotion licence FAQ](https://www.remotion.dev/docs/license/faq)
and [terms](https://www.remotion.dev/docs/terms), read 2026-10-09.
FFmpeg's build can be LGPL or GPL. The demo binary reports GNU GPL version 2 or later
(`ffmpeg -L`, checked 2026-10-09). The wrapper does not redistribute a binary.
See [FFmpeg legal](https://ffmpeg.org/legal.html), read 2026-10-09.
