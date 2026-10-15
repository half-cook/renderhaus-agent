# Local logo animation

A supplied PNG, JPEG or screenshot becomes an editable SVG before any motion is authored.
The user reviews the overlay strip and edge audit, then approves the exact SVG checksum.
The local renderer animates that approved geometry and lands on the same static mark.

`logo_vectorize` maps to `Logo___logo_vectorize` in the editor role. This is a free local
provider, without credentials, paid requests, external models or uploads. Its catalog
record has `local_only=true`. Gateway deployment excludes it and the Lambda handler
refuses it. Every call must use the authenticated Studio run's `job_id`. A logo-animation
template must use that same job and the local Remotion backend.

## Contract and artifact ownership

The tool accepts `op`, `job_id`, `input_path` and operation-specific `params`. Unknown
fields, traversal, URLs, external job paths and out-of-bounds inputs refuse before
processing. The source must already be staged inside its job directory. An unresolvable
Studio asset handle is a staging blocker. Processing never fetches a remote source.

| Operation | Input and result |
| --- | --- |
| `vectorize` | Decode a bounded raster, remove edge-connected background, quantize colors and fit editable geometry. Save `logo.svg`, `vector.json` and `overlay-strip.png`. |
| `audit` | Compare the saved SVG against its recorded source. Report silhouette IoU, smoothness metrics and review status. |
| `approve` | Require rights confirmation and the exact `params.sha256`. Native approval is mandatory, including autonomous runs. Save a signed receipt tied to the vector and manifest. |
| `choreograph` | Require the unchanged approved bundle. Save `motion_spec.md`, `motion_spec.json` and a self-contained `preview.html`. Return the bounded render template. |
| `final_frame` | Require the exact SVG path and returned template. Compare the saved final image or MP4 frame with the approved vector. Bind motion checks and the report to output, vector and motion-spec checksums. |
| `easing` | Compare observed progress samples with declared `enter`, `settle` or `linear` easing, timing and overshoot. |
| `continuity` | Inspect per-part position, scale and opacity samples for discontinuities. |

Approval is an authority boundary. The model cannot pass a human identity or approval
token in tool arguments. Only the shared executor enters the provider's approval context
after the existing native approval resume. Rejection executes no approval write. A new
source, changed SVG or changed review overlay invalidates the earlier review.
The receipt key lives only in the worker process. A worker restart requires a fresh
vector approval rather than accepting an unverifiable prior receipt.

## Geometry method and calibrated limits

The implementation uses the existing Pillow and NumPy dependencies. It has no tracer
binary or new tracing dependency. Edge-connected background removal preserves enclosed
negative space. Color reduction uses a small palette. The in-house contour fit simplifies
outlines and uses primitives or quadratic curves when they describe the shape. The SVG
parser accepts only the implementation's bounded geometry subset, with stable part IDs.
It rejects active content, text, images, links, external resources and unsupported attributes.

| Check | Limit |
| --- | --- |
| Raster bytes | At most 8 MiB. |
| Raster dimensions | At most 2048 pixels per side and 1,048,576 total pixels. Single-frame PNG or JPEG only. |
| Palette | 1 to 8 colors, default 4. |
| Editable structure | At most 32 parts and 256 segments. |
| Silhouette IoU | At least 0.88. |
| Long polyline smoothness | More than 24 line segments fails if no curves exist, or if segments no longer than 1.5 pixels exceed 25% of its line count. |
| Exact PNG final frame | Zero changed pixels and zero mean absolute error. |
| MP4 final frame | Mean absolute RGB error at most 1.5. At most 3% of pixels may differ by more than 16 in any RGB channel. |

The committed synthetic fixture manifest is `tests/fixtures/logo_animation/cases.json`.
Tests generate a rectangle, ellipse, ring and triangle. They cover opaque and transparent
backgrounds and enclosed negative space. Per-case IoU floors are 0.94 for the rectangle
and ellipse, 0.88 for the ring, and 0.90 for the triangle. Deliberately wrong geometry and
a jagged staircase provide negative cases. These cases calibrate acceptance of simple
marks. They are not a benchmark of arbitrary customer logos. The MP4 tolerance allows
encoder error while a changed final mark must fail. The real local rendering test also
checks a static clip with a correct closing frame so a final-frame-only shortcut fails.

This tracer is pragmatic. It cannot recover lost typography, unseen edges or intended
brand geometry from a poor screenshot. Photographic marks, gradients, fine text, complex
ribbons and self-intersections can exceed its palette or geometry budget. Smoothness and
IoU are both gates. Neither certifies semantic equivalence or grants visual acceptance.
Inspect the overlay and enlarged curves before approval. Request a cleaner source when
the simple fit cannot preserve the mark.

## Motion and delivery

The choreography contract records personality words, semantic part order, a timeline,
named easing tokens, a 1 to 3 second reveal and an optional preview idle loop. Bounded
styles are `reveal`, `splash`, `loader` and `idle-hover`. Part entrances overlap and finish
at opacity 1 with an identity transform. Fill-versus-stroke metadata and draw order are
structure hints. The current renderer implements fill-based scale, translation and opacity.
It has no general stroke skeleton, custom morph or ribbon draw-on implementation.

`settle` is smoothstep, `3t² - 2t³`. `enter` is cubic ease-out, `1 - (1-t)³`.
The easing probe requires ordered samples covering both endpoints, monotonic progress,
maximum token error 0.02 and overshoot no greater than 0.02. The continuity probe needs
at least three samples per part, advancing by at most 50 milliseconds. Position jumps
above `max(4 px, 0.4 × dt)` fail. Scale jumps above `max(0.08, 0.004 × dt)` fail. Opacity
jumps above `max(0.12, 0.006 × dt)` fail. Here `dt` is milliseconds between observations.
Declared-motion probes do not replace decoded motion checks or full playback.

The self-contained HTML has no remote requests and respects reduced motion. The
`logo-animation` named template uses `logo_job_id`, relative `logo_path`, approved
`svg_sha256`, `duration_seconds`, `style`, `personality`, `idle_loop` and `background_color`.
The local backend renders MP4. Lambda explicitly refuses the feature. Alpha ProRes 4444
and alpha WebM are unsupported. A future Lottie hand-off belongs to the sibling
`lottie-animation` skill. TODO add its real authoring tool after that branch is installed.

After rendering, run the saved-artifact final-frame and motion QA. Then run the existing
`remotion-deliverable-qc` workflow. The Studio completion boundary requires a saved passing
logo report whose checksum, MP4, approved SVG and motion specification still match.
It also requires the existing saved passing deliverable report for that same final MP4.
New render or finishing work invalidates earlier QA. Failure summaries retain each
reported failure verbatim. Customer visual review remains explicit.

Deliver `logo.svg`, the HTML preview, MP4 and `motion_spec.md`. State the successful
render's width, height, `source_resolution` and resolution warnings. A 1280x720 source
resampled to 1920x1080 must say "upscaled from 1280x720; no added detail". Actual
enhancement uses the existing `upscale` skill with its normal approval.

## Rights, licence and privacy

Users must confirm rights to animate third-party marks. User logos never enter committed
fixtures or training data. Files stay in the job directory or private project storage.
`training_eligible` is false. The local operation has no API price or model identifier to
verify. Existing render licensing and cost rules still apply to the renderer.

The method adapts ideas from [nolangz/pixel2motion](https://github.com/nolangz/pixel2motion)
at `e9faedb28930df0da2acf17da00c80730a78cfe8`, read 2026-10-14. Its
[MIT licence](https://github.com/nolangz/pixel2motion/blob/e9faedb28930df0da2acf17da00c80730a78cfe8/LICENSE)
permits commercial adaptation. Attribution and the complete notice are in
[the skill NOTICE](../agent/deep_agent/skills/logo-animation/NOTICE.md). No upstream
code, scripts, assets, binaries, weights or dependencies are copied. The upstream
HTML showcase and ribbon scripts are references only.

## Routing and validation limits

RT-184 is active with `logo_vectorize then remotion_render`. Its forbidden canonical
tools are `wan3_t2v`, `seedance25_t2v` and `gpt_image25_edit`. Four additional positive
and four negative cases cover splash, loader, reveal, idle, lower thirds, new logo design,
channel intros without a supplied logo and podcast audiograms. Execution groups keep
vector preparation and rendering sequential across the approval gate. Existing fixture
rows retain their choices. Current inventory is 19 providers, 135 Gateway tools, 39 skills,
310 routing rows, 304 active and 6 dependency skips.

UNVERIFIED items are customer-logo fidelity outside the synthetic calibration set,
customer visual acceptance, browser playback through Comet and deployed Studio behavior.
The current task forbids live or paid API calls. Offline tests and a local render provide
supporting evidence only. Browser evidence and concrete blockers belong under ignored
`.renderhaus/e2e/`, recorded through `scripts/browser_e2e_hook.py`. Alpha output and
Lottie authoring are unsupported by this branch.
