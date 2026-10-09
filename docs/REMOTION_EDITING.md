# Remotion editing

One brief and a table produce real local ad variants with editable price, CTA, logo and
legal overlays. A finished master can also produce static aspect candidates with contact
sheets for human editorial review. The existing Remotion timeline path performs assembly.
Resolve is parked. Loudness and full deliverable certification remain pending
`feat/remotion-delivery-qc`; these review files must not be sold as certified deliverables.

## Tool contracts

`Remotion___render_ad_variants`, alias `ad_variant_matrix`, accepts these arguments:

| Argument | Contract |
| --- | --- |
| `stage` | `plan`, `render_first` or `render_batch` |
| `job_id` | ASCII ID for an existing directory below `RENDERHAUS_MEDIA_DIR` |
| `brief` | Campaign, layout and rendering requirements; `reframe_only=true` for a flat master without overlays |
| `rows` | Complete array of 1-100 immutable table rows across all stages |
| `master_asset` | Immutable regular video file inside that job directory |
| `plan_hash` | Exact content hash from `plan`, required for rendering |
| `concurrency` | Integer 1-2, default 2 |

Retail rows require `variant_key`, `sku`, `price_text`, `cta_text`, `logo_asset`, `legal_text`,
`locale` and `aspect`. Copy stays verbatim; the planner never computes discounts or translates
legal text. `product_asset`, `vo_asset`, `start_s` and `end_s` are optional. Minimal reframe
rows require only `variant_key` and `aspect` with `brief.reframe_only=true`. Their internal
SKU/locale are `master`/`und` and they add no retail overlays. IDs contain 1-40 ASCII letters,
digits, underscores or hyphens. Duplicate keys and `(sku, locale, aspect)` tuples are refused.
The selected source range is finite, inside the master and at most 600 seconds long.

Rows may also contain `subject_box`, `crop_box`, `anchor`, `safe_zone`, `allow_upscale`,
`shots` or `scene_times`. The brief can set shared box, anchor, safe-zone and upscale defaults.
Boxes use `{x,y,width,height}` in display-oriented source pixels. Crop coordinates and
sizes are even integers inside the displayed source. Subject boxes are validated geometry,
not a detector result verified by this code. Anchors are `center`, `top`, `bottom`, `left`
or `right`; a subject box supplies the centre when present. Safe-zone fractions accept
`top`, `bottom` and `side` within `0..0.49` and must leave at least 5% inner width and height.

A `shots` list has contiguous `{from_s,to_s}` spans covering the selected source range,
with optional per-shot `subject_box`, `crop_box` and `anchor`. Alternatively, `scene_times`
supplies increasing cut times in source seconds. At most 60 shots are accepted. Windows
remain static within each shot; there is no tracking, detector, slow pan or mid-shot jitter.
Planning makes one crop/pad decision per shot and composes that sequence through the existing
`Remotion___render_timeline` document path. `brief.fit="contain"` keeps the whole foreground
frame with blurred padding. Direct timeline visuals use `crop_box`, `pad_box`,
`reframe_size={width,height}` and `allow_upscale`; `fit="pad_blur"` uses the safe viewport
`pad_box`. Their normalized document names are `cropBox`, `padBox`, `reframeSize` and
`allowUpscale`. All primary clips share the same requested canvas.

The public schema contains no approval fields. The trusted host owns spending authorization.
Studio local tools bind `job_id` to the authenticated execution. The generic invocation
endpoint refuses these local workflow tools. An operator stages approved files in that
owned directory before planning. Neither matrix nor timeline accepts arbitrary JSX or scripts.

## Planning and review gates

1. `plan` probes actual media, validates rows and assets, measures overlay text fit, checks
   geometry and hashes the table, brief, files and resulting timeline documents. It returns
   planned/blocked rows, aspect count, decisions, cost estimate and plan hash without rendering.
2. `render_first` pauses with count, aspects, cost and hash, even in autonomous mode. It
   renders the first SKU/locale group at every represented aspect and returns actual MP4s,
   review frames and contact sheets. A sample spending approval does not accept its framing.
3. A person opens each artifact and reviews crop/pad decisions, burned-in legal and branding
   content, and expected overlay text. No automatic OCR or editorial acceptance is claimed.
4. `render_batch` pauses again for the unchanged hash and requires successful reviewed first
   renders. Changed files, stale hashes or sample failures block the batch. Rendering uses
   bounded concurrency; one failed row does not stop the other rows and there are no blind retries.

Every output has a per-aspect contact sheet. The result is a `candidate_set=true` with
`editorial_review="pending"`; a successful renderer cannot certify an editorial decision.
The manifest records identities, document hashes, file paths, hashes, duration and QC metadata.
Artifacts use generated/versioned names. Saved manifest paths, identities and hashes are
checked before reuse. The worker freezes hash-checked inputs before rendering. Studio asset
records include `output_path` for both videos and review images. Previous batches cannot
certify a new plan. Approval to render and human approval of the finished framing are separate.

## Crop plans and output resolution

`providers/ffmpeg/reframe.py` implements pure crop geometry. Source dimensions are supplied
before rotation; boxes are supplied after display rotation. Probe the rotation flag first,
then apply orientation once. A portrait phone clip must not be cropped as landscape and
rotated again. Without a subject box, the plan centres on the frame or requested edge anchor.
A subject box chooses the centre but must fit with its safe-zone margins. If it cannot fit,
the shot switches to blurred padding: fit the intact whole foreground over a blurred copy.
No YOLO, Ultralytics, MediaPipe, OpenCV or other detector is installed or invoked.

The target table contains these nominal maximum canvases:

| Aspect | Nominal size | Safe-zone top/bottom/side placeholders |
| --- | --- | --- |
| `9:16` | `1080x1920` | `0.14 / 0.22 / 0.06` |
| `1:1` | `1080x1080` | `0.08 / 0.12 / 0.06` |
| `4:5` | `1080x1350` | `0.08 / 0.12 / 0.06` |
| `16:9` | `1920x1080` | `0.08 / 0.12 / 0.06` |
| `2.39:1` | `1920x804` | `0.08 / 0.12 / 0.06` |

Safe zones are editable configuration in `providers/remotion/ad_layouts.json`, not certified
platform specifications. Confirm them for the destination and scale them with the actual
canvas. Odd dimensions round to even pixels; tiny sources warn when their aspect is approximate.

Native crops never upscale beyond the crop's available pixels by default. For example,
a centre crop of a `1920x1080` master to `9:16` uses a `606x1080` window
and delivers `606x1076` after even-pixel aspect rounding. To request exactly
`1080x1920`, set `allow_upscale=true`: the crop is resampled and adds no detail. The existing
output-resolution policy and FPS/bitrate preservation remain in effect. A native `1280x720`
export is 720p. A larger canvas resampled from that source must say "upscaled from 1280x720;
no added detail". State every delivered width and height, `source_resolution` and resolution
warning. The existing Topaz `upscale` skill provides actual enhancement with its existing
cost approval. Unknown source dimensions stay unknown.

Metadata FPS alone does not prove constant cadence. FFmpeg reframe operations preserve
frame timing; the timeline renderer uses the measured nominal FPS and produces CFR. Inspect
VFR metadata and disclose conversion/cadence warnings rather than claiming cadence preservation.
Reframe ops and new crop/pad timeline paths require a square-pixel source (SAR `1:1`); supply a
normalized square-pixel master if the source is anamorphic. No normalization op is available
here. Probe actual outputs for dimensions, SAR `1:1`, FPS, duration and audio. Rendering cannot
move a price, logo or legal line baked into the master; request an approved layered source
if framing would cut it off. Native authored timelines can rearrange their existing layers
for a new canvas instead of cropping a rendered composition. Arbitrary new templates remain unsupported.

## Fixed ffmpeg operations

`Ffmpeg___ffmpeg_tool`, alias `ffmpeg_tool`, is free and takes `op`, `job_id`, `input_path`
and optional `params`. An op registry owns each fixed argv builder, bounds, timeout and
parser. The full JSON Schema discriminates by op; AgentCore's restricted schema strips some
branches/bounds, so code validates the same contract before execution.

| Op | Params | Result |
| --- | --- | --- |
| `probe` | `{}` | Structured stream/container metadata, including dimensions, rotation, FPS, SAR and audio |
| `crop_plan_preview` | `source_width`/`source_height`: integers 2-16384; `aspect`; optional `rotation`, `subject_box`, `crop_box`, `anchor`, `safe_zone`, `allow_upscale` | Pure crop/pad window and output dimensions; no binary or file read |
| `reframe_crop` | `aspect`; optional `subject_box`, `crop_box`, `anchor`, `safe_zone`, `allow_upscale` | Static crop, or blurred-pad fallback if subject/safe zone cannot fit |
| `reframe_pad_blur` | `size` (aspect enum); optional `safe_zone`, `allow_upscale` | Whole foreground frame over a blurred copy |
| `detect_scenes` | `T`: finite `0.1..0.6`, default `0.3` | Bounded cut times and shots, at most 60 |
| `extract_frames` | `times`: 1-20 finite seconds in `0..600`; `width`: integer 16-1920 | Versioned PNG frames |
| `contact_sheet` | `every_s`: finite 0.1-600; `cols`/`rows`: integers 1-10; `width`/`height`: integers 16-640 | JPEG, maximum 4096x4096 and 600-second sample window |
| `sha256` | `{}` | File hash/bytes, pure Python |
| `check_faststart` | `{}` | MP4 atom order, pure Python |
| `volume_stats` | `{}` | Mean and sample peak; no LUFS or true-peak certification |

Preview defaults are 1920/1080 source dimensions and `9:16`; supply the measured dimensions
explicitly. Rotation is a finite multiple of 90 degrees in `-360..360`. Pure preview still
validates the input path lexically but does not require a file. Render ops probe the real
source; caller-supplied source dimensions are refused. Padding `size` uses the aspect enum,
not an arbitrary width/height pair. Crops scale with Lanczos and normalize SAR to `1:1`.
Scene detection uses fixed `select`/`showinfo`, bounds diagnostic output and rejects truncation.
See [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html), read 2026-10-09.

Results are structured `op`, `ok`, `outputs[{path,sha256,bytes}]`, `metrics`, `warnings` and
`ffmpeg_version`. Failure logs expose only a bounded redacted tail. Callers cannot select
shell commands, codecs, filtergraphs, executable paths, protocols or output paths. Unknown
operations are refused with the nearest available op.

Inputs are regular files confined inside a per-job directory. URLs, traversal, escaping
symlinks, special files, option-prefixed names, Unicode name tricks and newlines are refused.
Generated outputs never overwrite. Commands use argv lists with `shell=False`, job cwd,
a scrubbed environment, stdin disabled, protocol/format allow-lists, bounded logs, timeouts,
thread caps and output-size caps. No network is available. FFprobe 7.1.5 lacks `-nostdin`;
its stdin is `DEVNULL`. Installed FFmpeg/FFprobe are required for binary ops; missing binaries
return a clear structured failure. No binary is added to the Lambda zip.

## Backend contract

| Capability | Local worker | Lambda |
| --- | --- | --- |
| Existing timeline trims, ordinary fit, FPS/bitrate and native canvas policy | Supported | Existing path retained |
| Fitted text and positioned image/video overlays | Supported | Versioned font/box contract required |
| New per-item static crop windows or blurred-pad fit | Supported | Explicit refusal before source retrieval or AWS request |
| Matrix stages, including minimal reframe mode | Supported on host owning job directory | Explicit refusal before dry-run or AWS request |
| Fixed ffmpeg binary ops | Installed binaries and job directory required | Refused without binaries; no binary bundled |
| Pure crop preview | Supported without binary/input file | Requires only a validated job directory and request |
| Video grade, motion and rotation effects | Unsupported message | Existing composition capabilities |

`REMOTION_OVERLAY_CONTRACT_VERSION` defaults to 1. Version 2 declares a separately deployed
compatible font/box composition; it does not enable the new crop/pad fields. No deployment
or live Lambda call occurs here. Parity tests compare the canonical document and early
backend refusals; they do not claim deployed pixel parity. Render options must work on both
backends or be refused explicitly. Never silently switch backends or disable dry-run.

## Cost and licence

Local media cost is $0. Existing `REMOTION_LICENSE_RENDER_USD`, default `0.01`, adds an
operator allowance per render; this is not an asserted local-render charge. Five local
candidates disclose $0 media and $0.05 allowance. Sample/batch cards show their own counts.
Lambda matrix rendering remains refused. Its existing compute estimator uses configurable
workload assumptions with [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/),
read 2026-10-09; no new price or paid provider is added here.

Remotion permits free use for individuals and teams of up to three. At four or more people
operating the project, a Company License applies. Automators costs $0.01 per successful
render with a $100/month minimum; free-licence automations do not pay per render. Whether
this local ffmpeg compositor is metered remains **UNVERIFIED**. Sources:
[Remotion licence FAQ](https://www.remotion.dev/docs/license/faq) and
[terms v5.0](https://www.remotion.dev/docs/terms), read 2026-10-09.

FFmpeg is LGPL-2.1-or-later, or GPL-2.0-or-later when optional GPL components are enabled.
The installed demo binary reports GPL version 2 or later (`ffmpeg -L`). No FFmpeg code or
binary is copied or redistributed. See [FFmpeg legal](https://ffmpeg.org/legal.html), read
2026-10-09. Text and demo logo labels use system DejaVu fonts: Bitstream Vera licence,
public-domain DejaVu changes and the included font licence conditions. See
[DejaVu licence](https://dejavu-fonts.github.io/License.html), read 2026-10-09. Videos, tones,
logos and product stills are generated locally by the demo script; no external asset is used.
There are no new models or weights. Existing editing policies retain `training_eligible=false`;
source media rights are not training permission. No AGPL or non-commercial code/weights are copied.

No new environment variable, dependency or secret is required in this branch. Existing
`FFMPEG_DRY_RUN` and `REMOTION_DRY_RUN` default to `true`; CI forces both true. The explicit
operator driver selects local and opts into real rendering. Existing media-root, backend,
licence allowance, Lambda estimate and timeout variables retain their roles.

## Run the real local demo

The generator creates a short master with synthetic audio, three alpha logos, three product
stills, a fifteen-row retail CSV, and a five-row reframe CSV plus briefs under
`.renderhaus/demo/<job-id>/`. Default master: `1280x720`, four seconds, 24 FPS. Use `--size
1080p` for `1920x1080`, or `--size small` for a two-second `640x360` fixture. Existing jobs
are never overwritten.

```sh
.venv/bin/python scripts/make_ad_demo_assets.py --job-id aspect-demo --size 1080p
.venv/bin/python scripts/run_ad_demo.py plan --job-id aspect-demo --mode reframe
```

Inspect each crop/pad plan, native output dimensions and cost. Copy the exact plan hash only
after reviewing it. The driver requires operator approval for each rendering stage:

```sh
AD_PLAN_HASH='paste-the-exact-reviewed-plan-hash'
.venv/bin/python scripts/run_ad_demo.py render_first --job-id aspect-demo --mode reframe --approve-plan "$AD_PLAN_HASH"
```

Open all five MP4s and contact sheets. Compare framing, dimensions, audio, FPS, SAR and
warnings with the plan. Approve this candidate set editorially before authorizing the batch:

```sh
.venv/bin/python scripts/run_ad_demo.py render_batch --job-id aspect-demo --mode reframe --approve-plan "$AD_PLAN_HASH"
```

All rows belong to one master/locale group, so the first stage covers all five aspects;
the approved batch verifies and reuses those files. To request nominal table sizes, include
`--allow-upscale` in **every** stage and re-plan. A 1080p portrait output then requires and
reports resampling with no added detail. For retail overlays, omit `--mode reframe`; each of
three SKU groups has all five aspects. The driver makes no paid or Lambda calls.

## Verification limits

Tests use synthetic files and real installed binaries for geometry, scene cuts, output
sizes, SAR, timing, audio, path attacks, parameter bounds, stale plans and backend refusals.
Routing now activates RT-E011..RT-E019 alongside prior matrix and negative Resolve/shell
cases. Of 79 editing workbook rows, 47 are active and 32 are deferred; RT-E046 delivery
chaining remains deferred to `feat/remotion-delivery-qc`. Candidate LUT/multicam semantics
remain unverified. Total inventory is 16 providers, 115 Gateway tools, 26 packaged skills
and 218 routing rows (182 active, 36 deferred, including the original four dependency skips).

Comet is unavailable here, so real Studio browser E2E is blocked and pending. CLI/media
checks are supporting evidence, never a browser pass. No Lambda deployment, live Lambda
call or paid provider call is performed. Safe-zone presets, local licence metering and VFR
cadence require explicit review. A later detector branch may evaluate MediaPipe/OpenCV and
model licences; none is included now. Delivery, loudness and final QC await
`feat/remotion-delivery-qc`. See [decisions](remotion-aspect-ratio-variants-decisions.tsv).
