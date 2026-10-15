# Local UI vector animation

Renderhaus authors Lottie JSON and dotLottie vector animations for app and website UI.
The agent writes a scene specification or supplies JSON. Local tools validate, save,
package and preview it without keys, model calls, network requests or charges.
MP4 and GIF are previews of the vector deliverable. A finished video composition still
uses motion-graphics and `remotion_render` under its existing approval rules.

## Tool contracts

| Routing ID and local function | Gateway name | Behavior |
| --- | --- | --- |
| `lottie_author` | `Lottie___lottie_author` | Create or patch a scene, save JSON and dotLottie, return hashes, byte sizes, timing and usage snippets. |
| `lottie_validate` | `Lottie___lottie_validate` | Read JSON or dotLottie and report structure, player warnings and preview gaps. |
| `lottie_preview_render` | `Lottie___lottie_preview_render` | Produce deterministic PNG review artifacts, a self-contained scrubber and requested MP4 or GIF previews. |

These are the draft's placeholder names implemented as real local tools. The provider
ID is `lottie`; Gateway names follow the repo's `Target___verb` convention. The editor
uses `call_editor_tool`. There are no canonical ID clashes. `recraft_v41_vector` already
maps to `Fal___recraft_text_to_vector`; this branch adds no image-generation adapter.

All requests use strict typed contracts and reject extra fields. Each requires the
trusted Studio `job_id`. Authoring from a new scene can create its directory under
`RENDERHAUS_MEDIA_DIR`; reads require an existing job. Traversal, URLs, unsafe names,
foreign job paths and symlink escapes refuse before file access. Outputs use exclusive
new names so revisions preserve earlier files. The direct `/api/studio/invoke` path
requires chat for these tools. Local discovery and execution stay on the owning worker.

`lottie_author` accepts exactly one source:

- `scene` is a typed declarative scene specification.
- `lottie` is supplied native Lottie JSON.
- `input_path` reads an existing in-job `.json` or `.lottie` file.
- `svg_path` reads an in-job SVG through the strict subset converter.

`patch` applies only to `lottie` or `input_path`. It recursively merges object fields
and replaces arrays; it does not execute JSON expressions or code. `name` is a safe
output slug, default `animation`. Both JSON and container are validated before writing.
No external assets are fetched or silently bundled. Studio also accepts an owned
`renderhaus-asset://version` handle for `svg_path` or `input_path`. Before provider
dispatch it uses the existing workspace-authorized resolver, validates the request,
reads bounded bytes and stages a new confined job file. It retains the original
asset-version provenance. Missing or denied resolvers refuse; raw outside-job paths
remain forbidden. This lets attached SVGs and owned vector-generator outputs enter
the workflow without weakening the tools' filesystem boundary.
Policy, discovery, schema and rejection checks run before copying owned inputs.
A missing or foreign asset returns a generic refusal without exposing its identifier.

A minimal scene looks like this:

```json
{
  "job_id": "current-studio-job",
  "scene": {
    "name": "Success state",
    "width": 256,
    "height": 256,
    "fps": 60,
    "frames": 90,
    "layers": [
      {
        "name": "Success badge",
        "shape": "ellipse",
        "position": [128, 128],
        "size": [112, 112],
        "fill": "#168B52",
        "animate": [{
          "property": "opacity",
          "keyframes": [
            {"frame": 0, "value": 0, "easing": "ease-in-out"},
            {"frame": 30, "value": 100}
          ]
        }]
      }
    ]
  }
}
```

The agent substitutes the actual job ID. Defaults are 256 by 256, 60 fps, 90 frames
and transparency. Layer names describe their meaning. Shapes are rectangles, ellipses
or native Bézier paths. Solid fill, stroke, position, scale, rotation, opacity and
stroke trim are supported. Named easing tokens are `linear`, `ease-in`, `ease-out`
and `ease-in-out`. Native Lottie `op` is exclusive.

## Validation and compatibility

The validator implements a bounded practical subset of Lottie validation. It checks
required document keys, finite dimensions and timing, known layer and shape types,
property/keyframe structure, ascending frame times, easing handles, frame ranges,
asset references and parent cycles. JSON files are bounded to 8 MiB; scenes and
recursive data have separate count and depth limits in `providers/lottie/contracts.py`
and `validation.py`. It does not claim full conformance to the evolving JSON schema.

Targets are `lottie-web`, `lottie-ios`, `lottie-android` and `dotlottie`. Compatibility
warnings distinguish expressions, effects, masks, blend modes and advanced features.
A structurally valid animation may still need visual review in each actual player.
`ok` means the structural check passed; an empty warning list is not player testing.

The local renderer supports a declared subset. Unknown or unsupported geometry,
styles, property features and layer behaviors return path-qualified `not_previewed`
reasons and refuse the whole preview. Features are never silently dropped. Image,
text, precomposition, expressions, effects, masks, mattes, gradients, repeaters, 3D,
slots and spatial keyframe interpolation are outside the local preview subset.
Supplied vector JSON can still be saved when structurally valid and self-contained;
preview refusal remains explicit. Fonts and brand artwork must be user-owned or licensed.

## SVG intake

The converter rejects scripts, event attributes, external and local references,
foreign objects, doctypes, entities and unsupported elements or attributes. It uses
no browser, CSS engine or network resolver. It supports simple `svg` and `g` structure,
solid paths, polylines, polygons, rectangles, circles and ellipses. SVG path commands
are limited to a single subpath using M, L, H, V, C, Q and Z, including relative forms.
Transforms, CSS, images, text, filters, gradients, clipping and compound subpaths
refuse with a precise error. Convert these deliberately to the supported geometry
or request the source vector that preserves the required appearance.

The viewBox origin and aspect are preserved. Stroke paths receive a timed trim
reveal with ease-in-out. Compare the settled result against the supplied SVG.
A refusal is preferable to deleting a meaningful part of the supplied asset.

## Preview artifacts

`lottie_preview_render` reads the saved animation, including revisions, rather than
rendering a separate approximation of the scene specification. Defaults request
both `mp4` and `gif`; `formats: []` requests only PNG and HTML artifacts. The size
limit is 512 pixels on the longest side. The tool bounds previews to 600 frames,
20 seconds, 40 million raster pixels and a bounded output budget. It never truncates
an animation to meet a limit. PNG frames are deterministic within the pinned runtime.

The PNG contact sheet and strip show sampled frames; the self-contained HTML preview
contains every frame and supports scrubbing and frame pinning without network assets.
Inspect the first frame, reveal, midpoint, settled frame, final frame and any loop seam.
PNG preserves alpha. The MP4 preview composites a contrast background; this does not
change JSON transparency. GIF has palette/transparency limits and 10 ms frame timing,
so it is supporting evidence rather than an exact 60 fps player. MP4 and GIF use the
fixed allow-listed `image_sequence_preview` operation through the existing bounded
FFmpeg executor. No caller-supplied command or filter is executed.

Missing FFmpeg or failed encoding leaves an explicit incomplete result, even when
PNG artifacts exist. PNG-only requests can complete without FFmpeg. Browser inspection
and actual target-player review are separate from offline encoding checks.

## Container and downloads

The `.lottie` packer writes a v1 `manifest.json` and `animations/<id>.json` in a
Deflate ZIP with fixed entry order, timestamps and permissions. It bounds archive
and expanded sizes, validates animation IDs and rejects external image assets. The reader
checks every member before reading, rejects traversal, absolute paths, backslashes,
symlinks, encryption, duplicates, extra entries and compression bombs, and never
extracts members to the filesystem. Pack/unpack preserves the native document, including inline precomposition assets.
The reader accepts optional v1 metadata such as generator, author and playback options
as inert data; the author creates a fresh minimal manifest when repackaging.

Author results return JSON and container byte sizes and checksums, width, height,
frame count, fps, duration, validation and web/iOS/Android usage examples. Download
URLs use the existing authenticated Studio media endpoint. PNG and MP4 preview
artifacts can also enter the existing media library. The HTML is self-contained
so opening a single downloaded file works without its neighboring directory.

Web, iOS and Android snippets returned by the tool are documentation only. They
assume the application has installed its player SDK and bundled or hosted the
returned file. This branch does not execute or certify those integrations.

## Routing and policy

Explicit Lottie, dotLottie, animation JSON and functional app/web UI animation choose
`lottie-animation`. RT-183 and RT-185 are active alongside ten positive and negative
routing cases. MP4 title cards and lower thirds retain motion-graphics. Generic logo
animation retains its existing route. A future logo-animation skill is not claimed
as installed or listed in this skill's tools. Raster-logo requests need a vector asset
before Lottie authoring. New vector artwork can use the existing image-gen skill.

Selection elsewhere stays explicit request, exception predicate, default. This branch
adds no tier, cost-based model choice, confidential routing or paid provider. Local
outputs do not grant training eligibility. No secret sync change is needed. The
runtime image packages the local Python tools, notice and FFmpeg. Installed Deep
Agents 0.7.23 signatures are the implementation contract.

## Sources and licence

The upstream source was inspected read-only at `3c72912fad543897f90045ed4d355813837927fc`.
Its prompt grounding, semantic scenes, transparent UI defaults and exact-frame review
pattern informed the adapted skill. No runtime, app, lockfile, demo media, fonts or
weights are vendored. The complete MIT notice is in [NOTICE](../providers/lottie/NOTICE).
There is no model ID, API endpoint or hosted price to verify for these local tools.
Local cost is zero; existing optional vector-generation prices are unchanged.

Official sources read 2026-10-14:

- [Upstream MIT licence](https://github.com/diffusionstudio/lottie/blob/3c72912fad543897f90045ed4d355813837927fc/LICENSE).
- [Lottie specification](https://lottie.github.io/lottie-spec/latest/) and
  [animated properties](https://lottie.github.io/lottie-spec/latest/specs/properties/).
  Native keyframes place outgoing and incoming interpolation handles on the segment
  start. The upstream prompt map's destination-handle wording is corrected in this implementation.
- [Official dotLottie v1 specification](https://dotlottie.io/spec/1.0/) defines the manifest,
  `animations/` paths and Deflate container.
- [Official FFmpeg image sequence documentation](https://ffmpeg.org/ffmpeg-formats.html#image2-1)
  and [FFmpeg licensing](https://ffmpeg.org/legal.html). The installed build's licence
  applies to preview encoding. No AGPL or non-commercial code or model weights are added.

Run the offline checks with `.venv/bin/python -m pytest -q tests/test_lottie*`, then
run the full pytest suite, Ruff, `scripts/ci_check.py` and Studio/Remotion TypeScript
checks. Browser E2E requires Perplexity Comet and a real signed-in Studio session.
Its result is recorded under ignored `.renderhaus/e2e/`, independently of offline tests.

The scene canvas is 16..2048 pixels per edge, with 1..120 fps, 1..3600 frames and at
most 120 seconds. A scene has at most 64 semantic layers, plus an optional background;
a native document permits at most 128 layers per composition. Native documents cap
100,000 JSON values, depth 32, 128 assets and 4,096 total keyframes. The container has
stricter bounds of 4 MiB, 20,000 values and depth 24. Inline precompositions remain
inside the native JSON; image assets and font files are not bundled.
An author request outside container bounds fails before either deliverable is saved.

The PNG renderer uses polygon rasterization without antialiasing, 24 subdivisions per
cubic segment and 96 points per ellipse. It accepts at most 64 layers, 20,000 values,
depth 24, 512 vertices per previewed path and one geometry per style group. A scene
outside those preview bounds remains explicitly unpreviewed. MP4 dimensions may be
padded by one pixel for even encoding dimensions. Native dimensions remain in
`metadata`; actual preview dimensions and encoding notes remain in `preview_metadata`.
Validation and previews return the checksum of the exact source bytes read, so a
caller can compare them with the author result. Frame PNGs stay in the job; the tool
returns the contact sheet, strip, self-contained HTML and encoded previews to keep the
chat and media library from receiving hundreds of duplicate frame assets.


## Design and verification record

The design compared native Lottie JSON with a separate internal scene graph. Native
JSON was selected because authoring, supplied documents, patches, packaging and preview
all operate on the same saved representation. A second graph would need a lossless
import/export layer and extra rules for unsupported features. The strict typed scene
contracts apply the Model the Domain principle. Real file roundtrips, pixel hashes,
FFprobe checks and editor dispatch apply Prove It Works.

The read-only capability map and workbook were reviewed before design. Explicit
session decisions override older map recommendations; this feature changes no
planning model, continuity judge, confidential policy or paid-provider selection.
Two optional pstack external architecture lanes could not launch because their CLI
executables were absent. No Claude or Grok model actually ran. The application keeps
its existing `claude-sonnet-5-5` defaults for its manager and subagents.

An independent `gpt-5.6-sol` review found inline-precomposition packaging, optional
manifest metadata, preview-report and negated-routing gaps. Regression tests reproduce
those cases, and the implementation now accepts inline vector precompositions and
inert metadata, reports those preview limits and honors format exclusions. Source
checksums come from the exact bytes parsed, before rendering. Ten module-narration
docstrings were removed after comment review; public contracts and the external
SVG paint-order comment remain.

A final staging review reproduced the real resolver's missing-asset `KeyError` and
copies left by rejected calls. Regression tests cover that failure and six rejection
gates. The editor now refuses missing assets cleanly and copies inputs only after
those gates pass. All 128 focused Lottie tests passed after these fixes.

Full-suite validation also exposed a repeatable local Lighthouse transport failure.
The SSE library retained a process-wide shutdown flag between local servers. A
real two-client regression failed before the driver switched to stateless JSON
responses, then passed. All 149 focused Lottie and Lighthouse tests passed together.
The driver's spend ledger and client discovery behavior retain their existing state.

The Lottie feature branch passed offline verification with 2,728 pytest tests, 8 skips and 4,452
subtests. Ruff, `scripts/ci_check.py`, Gateway schema checks and the exact Studio
and Remotion `tsc --noEmit -p .` commands passed. The combined staging inventory is 19 providers,
137 tools, 39 skills and 313 routing fixtures, with 307 active and 6 skipped.

After merging into staging, the full suite passed with 2,781 tests, 8 skips and
4,813 passing subtests. Ruff, `scripts/ci_check.py` and Studio `tsc --noEmit` passed.
Remotion compositions were unchanged by the merge.

Comet browser E2E and actual web, iOS, Android and dotLottie player visual checks remain
pending. This session exposed no Comet control and no local Comet process. Access was
requested and the blocker was recorded using the project's browser-evidence hook.
Local output inspection, format roundtrips and FFprobe are supporting evidence only.
