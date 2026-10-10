# Remotion editing

One brief and a table produce real local ad variants with editable price, CTA, logo and
legal overlays. A finished master can also produce static aspect candidates with contact
sheets for human editorial review. The existing Remotion timeline path performs assembly.
Resolve is parked. Free local delivery finishing normalizes audio, names/version files and
checks every final file. Technical QC does not certify channel specifications or accept
editorial content; those reviews remain explicit.

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
Each matrix output receives a technical report. A failed check marks that variant failed;
intentional master freezes, black or silence are recorded as allowed source intervals.
Review intermediates still need final naming and loudness finishing. Delivery replaces the
manifest `qc` field with each final-file report and preserves the original source provenance.
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
| `volume_stats` | `{}` | Mean and sample peak |
| `frame_cadence` | `{}` | All decoded timestamps through 600s; frame count, nominal cadence and CFR deviations |
| `measure_loudness` | `I`: -30..-5 (default -14); `TP`: -9..0 (default -1.5); `LRA`: 1..20 (default 11) | Loudnorm pass-1 JSON plus ebur128 programme integrated LUFS, true peak and LRA |
| `loudnorm_mux_aac` | Same targets; required `measured_I`, `measured_TP`, `measured_LRA`, `measured_thresh`, `offset`; `bitrate_kbps`: integer 64..320 | Source measurements verified before two-pass linear loudnorm; video copy, 48kHz AAC, faststart; actual before/after and dynamic fallback flag |
| `mux_aac` | `bitrate_kbps`: integer 64..320 (default 192) | Video copy plus 48kHz AAC and faststart; refuses missing audio |
| `transcode_h264` | `intent`: one preset name below | Fixed H.264 High/yuv420p/AAC MP4 template; native FPS, no upscaling, bounded preset dimensions |
| `detect_black` | `d`: 0.1..5 (default 0.5); `pix_th`: 0..0.5 (default 0.1) | Black intervals, including head/tail and EOF closure |
| `detect_freeze` | `d`: 0.1..5 (default 0.5); `n`: 0..0.1 (default 0.001) | Freeze intervals |
| `detect_silence` | `d`: 0.1..5 (default 0.5); `noise`: -60..-20 dB (default -50) | Silence intervals |
| `ssim` | `reference_path`: confined existing master | First/last decoded-frame SSIM; incompatible dimensions/duration refused, no hidden resizing |

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

Verified offline on 2026-10-10. The executable table is
[`providers/remotion/capabilities.py`](../providers/remotion/capabilities.py).
`supported` means the local code renders the feature and the checked-in Lambda composition
accepts its payload. Lambda support remains **UNVERIFIED at runtime**. There are zero
`unsupported-but-silently-ignored` entries. Conditional limits are part of the contract.

| Feature ID | Local worker | Lambda, default contract | Limits |
| --- | --- | --- | --- |
| `identity` | supported | supported | Typed timeline parameters. |
| `clip_timing` | supported | supported | Typed timeline parameters. |
| `speed` | supported | supported | Video only; local source audio uses atempo. |
| `source_metadata` | supported | supported | Measured video metadata only. |
| `layers` | supported | supported | Ordered video/image tracks, later tracks composite above earlier ones. |
| `transitions` | supported | supported | cut, fade and dip_to_black use item fades; no overlap cross-dissolve. |
| `fit_position` | supported | supported | cover/contain on both; pad_blur requires local/worker. |
| `scale` | supported | supported | Static centre scale 0.1..4; box clips at its edges. |
| `rotation` | supported | supported | Centre rotation -360..360 degrees, clipped at viewport. |
| `motion` | supported | supported | none, linear zoom_in/zoom_out 8%, pan_left/pan_right +/-4% with 8% zoom. Arbitrary keyframes refused. |
| `grade` | supported | supported | none, neutral, warm; fixed media-only filters. CSS/ffmpeg color pixel parity UNVERIFIED. |
| `opacity_fades` | supported | supported | Typed timeline parameters. |
| `source_audio` | supported | supported | Typed timeline parameters. |
| `audio_mix` | supported | supported | Trim, delay, volume, fades and mix; clamped to visual end. |
| `titles` | supported | supported | Local fonts have weights 400/700, named/hex colors and fit guards. Other CSS colors/weights require Lambda. Legacy fonts/pixels UNVERIFIED. |
| `captions` | supported | supported | Output-timed literal burn-in text after all overlays; same local text restrictions as titles. |
| `srt_captions` | supported | supported | Inline numbered SRT, no file/URL, no styling or filter commands. |
| `fitted_overlays` | supported | refused-with-explicit-error | Lambda requires overlay contract version 2 with matching font assets; use local/worker until deployed. |
| `crop_reframe` | supported | refused-with-explicit-error | Lambda reframing is not deployed; use the local/worker backend for crop_box and pad_blur. |
| `canvas` | supported | supported | Source-native policy; explicit tiers report resampling with no added detail. |
| `encoding` | supported | supported | MP4/H.264, CFR, AAC when audio exists; no caller-selected codec or filtergraph. |
| `blurred_padding` | supported | refused-with-explicit-error | Lambda reframing is not deployed; use the local/worker backend for crop_box and pad_blur. |
| `css_text_styles` | refused-with-explicit-error | supported | Local supports hex/named colors and weights 400/700; other CSS styles require Lambda. |
| `arbitrary_keyframes` | refused-with-explicit-error | refused-with-explicit-error | Neither backend accepts arbitrary render keyframes. Use named motion presets on local or Lambda. |
| `nle_cuts_gaps` | supported | supported | In-house OTIO/FCPXML/EDL handoff; bake effects, text, transitions and retimes first. No AAF or Resolve API. |
| `transcript_edit` | supported | supported | Pure word-range edit preview, grade and captions compiled to render_timeline args; no media I/O. |
| `ad_matrix` | supported | refused-with-explicit-error | Owned local/worker job, unchanged plan hash and sample/batch approval; Lambda refuses. |
| `delivery_qc` | supported | refused-with-explicit-error | Owned local/worker files and binaries; Lambda refuses. No upload/publishing or arbitrary codecs. |
| `motion_carry_qc` | supported | refused-with-explicit-error | Local/worker binary QC only; keyframe boxes describe measurement, never render animation. |
| `progress` | supported | supported | Poll saved backend-specific render ID; no replacement render. |

`REMOTION_OVERLAY_CONTRACT_VERSION` defaults to 1. Version 2 declares a separately deployed
compatible font/box composition; it does not enable crop/pad fields. Tests explicitly select
version 2 for fitted-overlay payload checks. No deployment or live Lambda call occurred.

Local motion uses fixed linear expressions: zoom changes from 1 to 1.08 or back, and pans
move from +4% to -4% or back with 8% zoom. Scale and centre rotation clip inside the viewport.
Neutral/warm grades are fixed `eq`/color-matrix templates; color pixel equivalence with CSS
is **UNVERIFIED**. Arbitrary keyframe arrays, custom filters, LUTs and caller scripts are refused.
Titles and captions use literal text files with drawtext expansion disabled. `subtitles_srt`
accepts bounded inline numbered SRT and conflicts with nonempty `subtitles`; it accepts no
file/URL or styling commands. Text remains subject to measured fit and allowed fonts.
Legacy unfitted titles retain the existing 0.2-second fade default, including explicit zero;
fitted titles and captions preserve zero fades. This normalization is shared by both backends.

The agent dispatches ordinary renders on the configured backend. With `local`, owned Studio
asset handles resolve to local paths without publishing; with `lambda`, dispatch stays on
the Gateway. Unsupported features refuse before media I/O or AWS requests, including dry-run.
Raw local paths in agent requests must stay inside the trusted current job. Standalone local
renderer/NLE workflows keep their existing media-root contract.
Backend selection never silently falls back, starts a replacement render or disables dry-run.
Polling follows the saved render ID rather than the current backend setting. Existing native
approval policy, cost disclosure, exempt-tool set and autonomous spending cap remain in force.

The CI guard checks all nine Remotion tool IDs, every public render field, nested geometry
fields, allowed presets, backend disclosures and structured skill feature/backend claims.
Changing the schema or claiming an unsupported feature fails CI until the table and code agree.
Non-render workflow schemas are pinned in the capability module: a shape or description
change requires a capability review and updated workflow schema checksum.

`tests/test_remotion_parity.py` renders lavfi-generated media locally and captures the complete
mocked AWS invoke payload from the installed Remotion SDK. It checks MP4/H.264, dimensions,
FPS, duration within one frame, overlays, motion direction and audio envelopes. Existing NLE,
ad-matrix and deliverable-QC tests remain part of the full suite. Tests skip real-binary cases
cleanly if FFmpeg/FFprobe is absent. Lambda render/download/playback, deployed version 2,
font/layout pixel equality and audio/perceptual parity remain **UNVERIFIED**.

Fixed `Ffmpeg___ffmpeg_tool` operations retain their separate allow-list and local job contract.
No binary is added to the Gateway Lambda package. The timeline worker reuses bounded process
capture with a scrubbed environment, argv lists and `shell=False`; sources retain protocol,
host, path, byte, duration and thread limits. Output files are capped at 128 MiB.

## Delivery jobs and preset data

`Remotion___deliver_render` (`delivery_render`) and `Remotion___qc_deliverable`
(`deliverable_qc`) take `job_id`, exactly one `input_path` or `manifest_path`, `preset`
(default `social-feed`) and optional `spec`. Stage ordinary timeline output explicitly
inside the owned job first; neither job fetches a URL or another job's file. Manifests
contain 1-100 unique, checksum-matching entries and are at most 16 MiB. Reports share that
cap. Delivery also accepts safe ASCII `campaign`, `sku`, `locale`, supported `aspect`,
and `upload=false`. Upload=true is refused; this branch creates no S3/public link.

Presets live in `providers/remotion/delivery_presets.json`. They are **placeholders to
confirm per channel**, including dimensions, FPS bounds, loudness, file-size limits and
safe zones. They are not claims of broadcast or platform certification.

| Preset | Maximum width x height | LUFS / dBTP | Audio bitrate |
| --- | --- | --- | --- |
| `social-vertical` | 1080 x 1920 | -14 / -1.5 | 192k |
| `social-feed` | 1080 x 1080 | -14 / -1.5 | 192k |
| `web-1080p` | 1920 x 1080 | -14 / -1.5 | 192k |
| `broadcast-proxy` | 1920 x 1080 | -23 / -1 | 192k |
| `podcast-streaming` | 1920 x 1080 | -16 / -1.5 | 192k |
| `review-proxy` | 960 x 540 | No normalization target | 96k |
| `email-720p` | 1280 x 720 | -14 / -1.5 | 192k |

Every preset uses MP4/H.264 High/yuv420p, square pixels, preserved FPS within 1..120,
AAC at 48kHz with mono/stereo, faststart and a 16 MiB maximum file. Naming is
`<campaign>__<sku>__<locale>__<aspect>__v<n>.mp4`. Exclusive file creation selects a new
version and never overwrites. Compatible H.264 video is stream-copied while audio finishes;
otherwise a named fixed transcode downsizes within the preset, never upscales. Review
proxies use a lower fixed quality. Delivery retains delivered dimensions and known
`source_resolution`; unknown original dimensions remain unknown. Nominal "1080p" in a
preset name does not prove the actual output is 1080p.

Loudness targets accept `I`, `TP`, `LRA` and `tolerance_lu` (0.1..1, default 0.5) overrides.
Normalization rechecks pass-1 values against the source, refuses no-audio/inconsistent
measurements, attempts linear mode and reports dynamic fallback. The encoded AAC is
measured again before success. Programme loudness is measured; **dialogue gating is not
available**. Clips shorter than three seconds cannot receive target loudness certification.
See [loudnorm and ebur128](https://ffmpeg.org/ffmpeg-filters.html), read 2026-10-09.

The upstream [Remotion encoding table](https://www.remotion.dev/docs/encoding), read
2026-10-09, lists H.264 plus PCM-16 in MOV/MKV. This clone's local timeline renderer has
fixed AAC output and exposes no PCM render option. Real tests verify local system-ffmpeg
H.264/PCM-16 MOV inputs and their video-copy AAC finishing. This is not a new renderer PCM
option. Lambda PCM support is **UNVERIFIED**; no deployed Lambda call was made. ProRes
and arbitrary codec requests are explicitly refused by the delivery skill.

QC reports each check: container, codec/profile/pixel format, SAR, delivered dimensions,
FPS, decoded cadence/frame count, duration within one frame, audio presence/codec/layout/
sample rate, sample clipping, programme loudness/tolerance, true peak, silence, black/freeze
intervals, faststart, size, filename and checksum. It generates five review frames and a
contact sheet. Optional same-size master SSIM measures the first/last frames only. Caption,
price, legal-copy and editorial correctness require a planner vision pass on those frames;
`require_vision=true` fails pending review. Declared overlay geometry alone can be checked
against supplied safe-zone fractions. No OCR detector is added.

`spec` supports `expected_width`, `expected_height`, `expected_fps`,
`expected_duration_s`, `expected_sha256`, `expected_filename`, `master_path`,
`audio_channels`, `require_audio`, `require_vision`, target overrides, detector `noise`,
`black_d`, `freeze_d`, `silence_d`, `pix_th`, `n`, `allowed_black`, `allowed_freeze`,
`allowed_silence`, `overlay_boxes` and `safe_zone`. Allowed intervals are explicit
`{start_s,end_s}` spans; they never silently hide detections. An approved intermediate name
may be checked with `expected_filename`; final delivery always uses the naming convention.
Final QC validates actual artifacts, not source metadata or a successful encode response.

A failed check makes its file and manifest variant failed, preserving reasons in the report.
A current delivery workflow can be called finished/delivered only with a saved passing
report that still matches every output checksum, or with every failure disclosed verbatim.
The runner rejects incomplete/stale reports and previous video success overriding current
failed QC, including turn-limit recovery. Ordinary legacy assembly checks remain intact.
Editorial acceptance stays separate from technical QC and rendering authorization.

## Cost and licence

Local media cost is $0. Existing `REMOTION_LICENSE_RENDER_USD`, default `0.01`, adds an
operator allowance per render; this is not an asserted local-render charge. Five local
candidates disclose $0 media and $0.05 allowance. Sample/batch cards show their own counts.
Lambda matrix rendering remains refused. Its existing compute estimator uses configurable
workload assumptions with [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/),
read 2026-10-09 and rechecked 2026-10-10; no new price or paid provider is added here.

Remotion permits free use for individuals and teams of up to three. At four or more people
operating the project, a Company License applies. Automators costs $0.01 per successful
render with a $100/month minimum; free-licence automations do not pay per render. Whether
this local ffmpeg compositor is metered remains **UNVERIFIED**. Sources:
[Remotion licence FAQ](https://www.remotion.dev/docs/license/faq) and
[terms v5.0](https://www.remotion.dev/docs/terms), read 2026-10-09 and rechecked 2026-10-10.

FFmpeg is LGPL-2.1-or-later, or GPL-2.0-or-later when optional GPL components are enabled.
The installed demo binary reports GPL version 2 or later (`ffmpeg -L`). No FFmpeg code or
binary is copied or redistributed. See [FFmpeg legal](https://ffmpeg.org/legal.html), read
2026-10-09 and rechecked 2026-10-10. Text and demo logo labels use system DejaVu fonts: Bitstream Vera licence,
public-domain DejaVu changes and the included font licence conditions. See
[DejaVu licence](https://dejavu-fonts.github.io/License.html), read 2026-10-09 and rechecked 2026-10-10. Videos, tones,
logos and product stills are generated locally by the demo script; no external asset is used.
The ordinary Lambda billing entry retains its preexisting 8-cent operator placeholder;
actual per-render compute is **TODO/unknown**, not an official per-render price.
There are no new models or weights. Existing editing policies retain `training_eligible=false`;
source media rights are not training permission. No AGPL or non-commercial code/weights are copied.

No new environment variable, dependency or secret is required in this branch. Existing
`FFMPEG_DRY_RUN` and `REMOTION_DRY_RUN` default to `true`; CI forces both true. The explicit
operator driver selects local and opts into real rendering. Existing media-root, backend,
licence allowance, Lambda estimate and timeout variables retain their roles.

## Verification and remaining limits

2026-10-10 checks: the baseline passed 2,212 tests and the final suite passed 2,253
(7 skipped in each). The 54 focused overlay/parity/guard tests, full Ruff check,
`ci_check.py` and Studio `tsc --noEmit -p .` passed. No new dry-run flag or secret
was added. Studio used the specified shared dependency directory plus a temporary
overlay extracted from the local npm cache; its symlink was removed. Summarized
evidence is saved under ignored `.renderhaus/e2e/remotion-parity-checks.json`.

The real-binary tests cover two-pass loudness round trips, final AAC peaks, PCM MOV input,
no-audio refusal, injected black/freeze/silence/clipping, wrong dimensions/FPS/duration,
faststart atom order, source provenance, version contention, manifest hashes, finished-claim
guards, preset data, backend refusal and adversarial sandbox parameters. Tests call no
paid provider, Lambda or external media service. No model adapter or provider price was
added. The source model/capability map remains quality first.

Inventory is 16 providers, 128 Gateway tools, 34 packaged skills, and 251 retained routing
rows: 246 active and 5 skipped. This branch adds no tools, skills or routing rows. Of RT-E001..RT-E079, 78 are active. RT-E043 remains skipped
for exact OCR verification (`feat/remotion-ocr-verification`); four original dependency
rows remain skipped. LUT/multicam/ProRes candidates are active honest refusals, and all
Resolve-only rows are active negatives. Routing tests do not certify generated media.

Comet Studio E2E is **blocked**: no Comet control is available in this environment.
The blocker is recorded under ignored `.renderhaus/e2e/remotion-parity-browser.json`
through `scripts/browser_e2e_hook.py record`. Offline
binary checks cannot replace that browser validation. Deployed Lambda pixel parity and
PCM output, planner vision/OCR review, per-channel preset approval, local Remotion metering,
S3 upload and direct publishing remain unverified or unavailable. No deploy was attempted.

The 2026-10-09 real local demo produced fifteen retail outputs and five reframe outputs,
then finished and rechecked each final AAC/MP4 file at -13.97 LUFS with a maximum
-5.78 dBTP. Every source_resolution is 1280x720. Delivered native dimensions are
404x718 (9:16), 720x720 (1:1), 576x720 (4:5), 1280x720 (16:9), and 1278x536 (2.39:1).
The 1280x720 export is 720p; no output was upscaled. No resolution warning was reported.
The reports disclose placeholder presets, pending planner vision/editorial review, and
dynamic loudnorm fallback requiring mix review. Topaz's `upscale` skill can provide actual
enhancement with existing approval; it was not invoked in this offline demo. First-render
contact sheets were inspected, and final files were decoded with the real FFmpeg binary.
These checks do not establish browser playback or editorial acceptance.

The 2026-10-10 parity fixture under ignored `.renderhaus/e2e/remotion-parity/` renders
local grade/rotation, a title and inline SRT captions. The saved MP4 decoded video/audio
and its extracted frame was inspected. It is a test fixture at 320x180 with
`source_resolution=320x180`, no upscale and no resolution warnings; it is not a QC-certified
customer deliverable or a browser playback check. Lambda parity captures the full mocked
SDK invoke request only. See [decisions](remotion-local-lambda-parity-decisions.tsv).

## Run the real local customer demo

The generator creates a four-second master with synthetic audio, three alpha logos, three
product stills, a fifteen-row retail CSV, a five-row reframe CSV and briefs under
`.renderhaus/demo/<job-id>/`. Default master: native 1280x720, 24 FPS. `--size small` uses
640x360 for the same duration; `--size 1080p` uses 1920x1080. Existing jobs are refused.
The driver explicitly opts into the real local backend; all provider defaults remain dry-run.

```sh
.venv/bin/python scripts/make_ad_demo_assets.py --job-id delivery-demo --size 720p
.venv/bin/python scripts/run_ad_demo.py plan --job-id delivery-demo
```

Read the plan, dimensions, crop decisions and cost, then copy its exact reviewed hash.
Use `--mode reframe` on every plan/render command to process the flat master as five aspect
candidates without overlays. Retail mode includes all five aspects for each of three SKUs.

```sh
AD_PLAN_HASH='paste-the-exact-reviewed-plan-hash'
.venv/bin/python scripts/run_ad_demo.py render_first --job-id delivery-demo --approve-plan "$AD_PLAN_HASH"
```

Open every first-SKU MP4 and contact sheet; review framing, branding, legal copy and prices.
Then authorize the unchanged batch. Read its `manifest_path`; use that exact path below.

```sh
.venv/bin/python scripts/run_ad_demo.py render_batch --job-id delivery-demo --approve-plan "$AD_PLAN_HASH"
AD_MANIFEST='paste-the-completed-batch-manifest-path'
.venv/bin/python scripts/run_ad_demo.py deliver --job-id delivery-demo --manifest "$AD_MANIFEST" --preset web-1080p
.venv/bin/python scripts/run_ad_demo.py qc --job-id delivery-demo --manifest "$AD_MANIFEST" --preset web-1080p
```

`web-1080p` preserves these native aspect outputs and targets -14 LUFS, with the placeholder
-1.5 dBTP ceiling. Delivery writes named versions and checks every final AAC/MP4 file. The
last command rechecks the extended manifest and produces a saved pass/fail `report_path`.
Open/play the actual final files and inspect the report, contact sheets and warnings before
a customer summary. Say each delivered width/height, original `source_resolution` and
resolution warnings; disclose pending editorial review and every failed check verbatim.
No paid, Lambda, upload or posting call is made by these commands.
