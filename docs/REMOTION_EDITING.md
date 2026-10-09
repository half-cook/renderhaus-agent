# Remotion retail ad variants

One brief and a table produce review renders with SKU, price, CTA, logo and legal overlays.
The matrix reuses the existing Remotion timeline builder and backend selector. The local
backend composes real files with ffmpeg. This branch adds no paid media provider or model.
Resolve is parked. The next branches add subject-aware aspect variants and delivery QC.

## Tools and architecture

`Remotion___render_ad_variants`, alias `ad_variant_matrix`, accepts these arguments:

| Argument | Contract |
| --- | --- |
| `stage` | `plan`, `render_first` or `render_batch` |
| `job_id` | ASCII ID selecting an existing job directory below `RENDERHAUS_MEDIA_DIR` |
| `brief` | Campaign and rendering/layout requirements, including locale legal requirements |
| `rows` | Complete array of 1-100 table rows, unchanged across stages |
| `master_asset` | Readable immutable video inside the job directory |
| `plan_hash` | Hash returned by `plan`, required for rendering and tied to content |
| `concurrency` | Integer 1-2, default 2 |

The public schema has no approval fields. The trusted Gateway executor owns approval state.
Studio local calls must use the authenticated execution's `job_id`; they cannot inspect
another job. The generic Studio invocation endpoint refuses both local workflow tools.
Stage approved files inside that owned job directory before using the Studio agent.
Plan documents use the same `document` and `renderConfig` contract as ordinary
`Remotion___render_timeline`. Each output calls that existing rendering code path internally.
No arbitrary JSX, script or composition source enters the matrix tool.

Required table columns are `variant_key`, `sku`, `price_text`, `cta_text`, `logo_asset`,
`legal_text`, `locale` and `aspect`. Optional columns are `product_asset`, `vo_asset`,
`start_s` and `end_s`. Aspects are `9:16`, `1:1`, `4:5` and `16:9`.
Required cells cannot be empty. Duplicate `(sku, locale, aspect)` tuples and unsafe
`variant_key` values are refused. `variant_key`, `sku` and `locale` are 1-40 ASCII letters,
digits, underscores or hyphens. Copy remains verbatim. Legal rules come from the table
and brief, never from a generated translation. The planner does not compute discounted prices.

Planning probes real media, checks logo alpha when required, measures text fit and checks
safe-zone geometry. It hashes the table, brief, assets and timeline documents. Replacing a
logo at the same path changes the plan hash. External asset URLs are refused. An operator
must stage approved source files before calling `plan`.

The brief accepts `campaign` (a 1-40 character ASCII identifier), `logo_alpha_required`
(boolean, default `true`), `legal_locales` (locale list), `legal_by_locale` (locale to verbatim
legal line), `fps`, `source_width`, `source_height`, `output_resolution` and `fit`.
FPS/source dimensions, when supplied, must match the measured flat master.
`output_resolution` uses the existing `source`, `720p`, `1080p`, `1440p` or `2160p` policy;
`fit` is `cover` or `contain`. Other brief fields, template source and shell code are refused.
Optional `start_s`/`end_s` select a finite range of at most 600 seconds inside the master.

## Sample review and approval

The manager and final-assembly role use this sequence:

1. `plan` validates and returns planned/blocked rows, document hashes, count, estimate and
   the plan hash. This stage is free. It writes no review render and cannot approve one.
2. `render_first` pauses for human approval with the count, aspects, cost and hash,
   including during autonomous runs. It renders the first SKU/locale group at each aspect
   represented for that group, then extracts frames near 5%, 50% and the end card.
3. A person inspects the sample frames and compares the price, CTA, SKU and legal line
   with the expected table strings. Sample spending approval does not establish visual acceptance.
4. `render_batch` pauses again. The trusted executor records approval for the matching
   first-render hash. Missing approval, a changed table/asset or a failed sample blocks the batch.
   Rows render with bounded concurrency. One failure does not stop the remaining rows.

The manifest records `variant_key`, `sku`, `locale`, `aspect`, composition/template ID,
`input_props_hash`, `file`, `sha256`, `duration_s`, `qc`, `ocr_match` and `approved_by`.
The stage report counts planned, rendered, blocked and failed variants. There are no blind retries.
Output files use generated/versioned safe names and never overwrite prior renders.
Probe dimensions/FPS/duration and hashes refer to actual completed MP4s.
Review images also have `output_path` records for Studio asset ingestion. Completion uses
the current batch, so a previous successful matrix cannot certify a new plan or sample.
The worker freezes hash-checked inputs before rendering and validates saved manifest
identities, confined artifact paths and hashes before reusing completed outputs.

There is no OCR engine or Tesseract dependency. Text fit and geometry are deterministic,
but pixel equality of copy remains unverified until a human or real vision pass compares
the extracted frames. `volume_stats` cannot certify LUFS or true peak. Delivery, loudness
and full per-output certification are unavailable until `feat/remotion-delivery-qc`.
Do not advertise these review renders as loudness-checked final deliverables yet.

## Flat masters and resolution

The timeline combines the locked master with editable overlays. A product, price or colour
baked into the master pixels cannot be swapped by this job. Supply a layered source or use
a separately approved generative edit for changes to baked content.

The branch uses the existing simple centre-crop/pad fit. It does not detect subjects or plan
per-shot reframe windows. The master FPS and bitrate preservation remain in effect. The
default canvas follows the existing source-resolution policy. Aspect fit may crop or
resample source pixels; explicit larger canvases also resample them.
State each delivered width and height, `source_resolution` and all resolution warnings.
For example, a 1920x1080 canvas resampled from 1280x720 is "upscaled from 1280x720; no added
detail". Native 1280x720 is 720p. The existing Topaz `upscale` skill provides actual enhancement
with its existing approval gate. Unknown source dimensions remain unknown.

Safe zones in `providers/remotion/ad_layouts.json` are placeholders to confirm per channel:

| Aspect | Top | Bottom | Left/right |
| --- | --- | --- | --- |
| `9:16` | 14% | 22% | 6% |
| `1:1` | 8% | 12% | 6% |
| `4:5` | 8% | 12% | 6% |
| `16:9` | 8% | 12% | 6% |

The source resolution policy can produce smaller canvases than the layout's maximum target.
Safe-zone geometry scales with the actual canvas. These margins are not certified platform specs.

## Backend support

| Capability | Local ffmpeg | Lambda |
| --- | --- | --- |
| Existing trims, fit, FPS/bitrate preservation and native canvas policy | Supported | Existing path retained |
| Text with allow-listed font, measured fit, box, colour, opacity and fades | Supported | New font/box props require compatible composition contract version |
| Image/video overlay scale, position, alpha, opacity and fades | Supported within validated contract | New box props require compatible composition contract version |
| Video grade, motion and rotation | Clear unsupported message | Existing composition capabilities |
| Matrix stages and artifact checks | Supported on worker owning job directory | Explicit refusal until that directory is accessible to its worker |
| Fixed `ffmpeg_tool` binary ops | Installed ffmpeg/ffprobe required | Refused on Gateway host without binaries; no binary is added to Lambda zip |
| `sha256`, `check_faststart` | Pure Python | Requires the actual job directory/files |

`REMOTION_OVERLAY_CONTRACT_VERSION` defaults to 1. Setting it to 2 declares that a compatible
Lambda composition and matching font package have been deployed separately. Do not set it
to bypass a refusal. This task makes no deployment or live Lambda call. Tests compare
canonical props and explicit refusals, rather than claiming deployed pixel parity.

Text uses system `DejaVuSans.ttf` and `DejaVuSans-Bold.ttf` through fixed IDs `dejavu-sans`
and `dejavu-sans-bold`. Pillow measures the same font files used by drawtext. The renderer
shrinks only within configured integer size bounds and returns `text_overflow` at the minimum.
Unsupported glyphs return a clear error. Text files and `expansion=none` keep percent sequences
and punctuation out of filter syntax. Caller-supplied font paths are refused.

## Fixed ffmpeg inspection

`Ffmpeg___ffmpeg_tool`, alias `ffmpeg_tool`, is a free editor/manager operation with
`op`, `job_id`, `input_path` and optional `params`. The op registry owns a fixed argv builder,
parameter validators, timeout and parser for each op. Adding an op means one registry entry
and its table-driven contract/real-binary tests. Callers cannot choose a shell, executable,
codec, filtergraph, raw argument list, input protocol or output path.
The provider's full JSON Schema uses a discriminator branch per op to enforce its bounds.
AgentCore's restricted schema dialect omits those branches and bounds; the same registry
enforces them again in code before any execution. The published descriptions retain each
operation's parameters and ranges.

| Op | Params | Result |
| --- | --- | --- |
| `probe` | `{}` | Streams, container, dimensions, duration, FPS and audio metadata |
| `extract_frames` | `times`, 1-20 finite seconds in 0-600; `width`, integer 16-1920 | PNG frames with generated names |
| `contact_sheet` | `every_s`, finite 0.1-600; `cols`/`rows`, integers 1-10; `width`/`height`, integers 16-640 | JPEG sheet, maximum 4096x4096 and 600-second sample window |
| `sha256` | `{}` | File hash and byte count, pure Python |
| `check_faststart` | `{}` | Atom order and whether `moov` precedes `mdat`, pure Python |
| `volume_stats` | `{}` | Mean and maximum sample volume; no LUFS or true-peak certification |

Defaults are `times=[0]` and `width=640` for frames. Contact-sheet defaults are `every_s=1`,
`cols=3`, `rows=1`, `width=320` and `height=180`.

Results have `op`, `ok`, `outputs[{path,sha256,bytes}]`, `metrics`, `warnings` and
`ffmpeg_version`. Failure logs expose only a bounded redacted tail. Missing binaries return
a structured failure. The host never passes credentials or signed URLs to ffmpeg.

Inputs are regular readable files below the selected job directory. Path traversal, URLs,
escaping symlinks, special files, Unicode name tricks, newlines and option-prefixed names
are refused. Input size is at most 128 MiB. Generated output names match ASCII-safe templates.
Each output is capped at 16 MiB and all outputs at 64 MiB. Commands use argv lists with
`shell=False`, job-directory cwd, a scrubbed environment, stdin disabled, protocol/format
allow-lists, bounded logs, hard timeouts and thread caps. `ffprobe` 7.1.5 has no `-nostdin`;
the process instead receives `stdin=DEVNULL`. There is no network or overwrite operation.

`FFMPEG_DRY_RUN` defaults to `true` and previews validated requests without creating media.
CI forces it to `true`. Real tests explicitly opt into the local binary path and use generated
lavfi media. No provider keys, paid API calls or new Python dependencies are needed.

## Cost and licence

Local media cost is $0. `REMOTION_LICENSE_RENDER_USD`, default `0.01`, adds an operator
allowance per render. This is an allowance for Automators, not an asserted local charge.
Six local renders therefore disclose $0 media plus $0.06 allowance. Sample/batch cards
disclose the count for their own stage as well as plan identity.

The Lambda estimate uses configurable memory, aggregate worker compute seconds and request
count. Defaults are 3008 MB, 120 aggregate worker seconds and 10 requests per render.
At x86 on-demand list rates of $0.0000166667/GB-second plus $0.20/million requests, the
compute estimate is about $0.005877 per render, plus the licence allowance. S3, network,
free tiers and discounts are excluded. These workload assumptions are placeholders, not a
measured Lambda render. `REMOTION_MATRIX_LAMBDA_RENDER_USD` can replace the per-render compute
estimate. Invalid configured estimates are refused. Source is
[AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/), read 2026-10-09.

The new configuration has no secrets:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `FFMPEG_DRY_RUN` | `true` | Validated preview for the free inspection tool |
| `REMOTION_LICENSE_RENDER_USD` | `0.01` | Operator licence allowance per render |
| `REMOTION_MATRIX_LAMBDA_MEMORY_MB` | `3008` | Estimated worker memory in MB |
| `REMOTION_MATRIX_LAMBDA_COMPUTE_SECONDS` | `120` | Aggregate worker seconds per render |
| `REMOTION_MATRIX_LAMBDA_REQUESTS` | `10` | Estimated requests per render |
| `REMOTION_MATRIX_LAMBDA_RENDER_USD` | Derived from the above | Optional compute USD estimate override |
| `REMOTION_OVERLAY_CONTRACT_VERSION` | `1` | Explicit compatible Lambda font/box contract declaration |

Existing `REMOTION_DRY_RUN`, `REMOTION_RENDER_BACKEND`, `RENDERHAUS_MEDIA_DIR` and render
timeout variables keep their roles. `scripts/sync_secrets.py` needs no new secret names.

Remotion's custom licence permits free use by individuals and teams of up to three people.
A Company License applies at four or more people operating the project. Automators costs
$0.01 per successful render with a $100/month minimum. Agencies aggregate collaborating
operators' headcounts. Clients receiving only MP4s do not add to that headcount. Whether our
local ffmpeg compositor's renders are metered under that licence remains UNVERIFIED.
Confirm with Remotion before scaling. Sources are
[Remotion licence FAQ](https://www.remotion.dev/docs/license/faq) and
[Remotion terms v5.0](https://www.remotion.dev/docs/terms), read 2026-10-09.

FFmpeg is LGPL/GPL depending on its build. The installed demo binary reports GNU GPL
version 2 or later (`ffmpeg -L`, checked 2026-10-09). This wrapper copies no FFmpeg code
and redistributes no binary. Source is [FFmpeg legal](https://ffmpeg.org/legal.html),
read 2026-10-09. DejaVu font changes are public-domain and the base fonts use the Bitstream
Vera licence, verified in [DejaVu licence](https://dejavu-fonts.github.io/License.html), read
2026-10-09. This branch introduces no model or weights. `training_eligible=false` for both
new tool IDs. Editing retains the input media's rights and does not grant training permission.
No AGPL, OpenMontage, guizang-product-video-skill or non-commercial code/weights are copied.

## Run the real local demo

Run these commands from the repository root with ffmpeg, ffprobe and the project `.venv`.
The generator creates a 1280x720, four-second, 24 FPS master with synthetic audio, three
alpha logos, product stills, a six-row CSV and a brief under `.renderhaus/demo/ad-demo/`.
It refuses to overwrite an existing job; use a different `--job-id` for another fixture.

```sh
.venv/bin/python scripts/make_ad_demo_assets.py --job-id ad-demo
.venv/bin/python scripts/run_ad_demo.py plan --job-id ad-demo
```

Inspect the blocked/planned rows, documents, safe zones and cost. Six local outputs have
$0 media cost and a $0.06 licence allowance at the default setting. Copy the exact returned
hash only after approving the plan. The following flag is an explicit operator approval
for the named stage; it is unavailable as an agent tool parameter.

```sh
AD_PLAN_HASH='paste-the-exact-reviewed-plan-hash'
.venv/bin/python scripts/run_ad_demo.py render_first --job-id ad-demo --approve-plan "$AD_PLAN_HASH"
```

Open every sample MP4 and each `review_frames`/contact-sheet artifact returned in the JSON.
Compare SKU, price, CTA and legal strings and inspect the output dimensions, FPS, duration
and resolution warnings. The first group contains SKU A in both `1:1` and `4:5`.
After accepting those samples, explicitly authorize the remaining four rows:

```sh
.venv/bin/python scripts/run_ad_demo.py render_batch --job-id ad-demo --approve-plan "$AD_PLAN_HASH"
```

Read the returned `manifest_path` and adjacent `report.json`; verify all six artifacts and
hashes, including the two first renders. A changed input changes the hash and requires a
new plan and review. Copy is not automatically OCR-certified. The driver selects the local
backend and sets `REMOTION_DRY_RUN=false` to render actual files. It makes no paid or Lambda
call. This explicit operator driver is separate from the default dry-run Gateway workflow.
For a faster fixture, generate a fresh job with `--size small`: 320x240, two seconds, 24 FPS.
CLI artifact checks do not establish Comet browser E2E; that validation remains blocked.

## Verification limits and next branches

Tests use generated media and real installed binaries for local artifacts. They also exercise
path/parameter attacks, text punctuation, overflow, table rules, stale hashes, approval branches,
backend refusal and props parity. Unit/CLI evidence is distinct from browser evidence.
Comet is unavailable in this environment, so Studio E2E is blocked and pending. No dry-run or
mock result is recorded as browser success. Lambda is not invoked or deployed.

On 2026-10-09, the operator CLI completed all six four-second demo renders at 24 FPS.
Three outputs are 720x720 and three are 720x900, each with `source_resolution=1280x720`.
All six hashes matched their manifest and all six decoded video and audio without errors.
The two first-aspect contact sheets visibly contained A, $9.99, Shop now and Terms apply.
The 720x900 outputs carry: "Video upscaled from 1280x720 to 720x900 with no added detail.
Use the Topaz upscale skill before assembly for added detail." No OCR certification is
recorded. Artifacts remain ignored under `.renderhaus/demo/ad-matrix-verification/`.

The final full suite ran 1,681 tests: 1,634 passed and 47 skipped. Ruff, dry-run CI/schema
packaging and Studio typecheck passed. The original allowance contention test intermittently
failed in earlier runs (two of five isolated repetitions), then passed in the final full run.
Its state code is unchanged; the five-attempt CAS retry limit remains an existing TODO.

The Studio typecheck passed using the temporary dependency link, which was removed.
The Remotion composition passed TypeScript syntax transpilation, but its full semantic
typecheck is UNVERIFIED because Remotion node dependencies are absent here. A built Python
wheel contains the layout JSON and imports it outside the source tree. Safe-zone presets,
the rough four-times-duration render-time estimate and Lambda workload estimates remain
placeholders to confirm; no deployed Lambda pixel parity is claimed.

`feat/remotion-aspect-ratio-variants` adds per-shot subject-aware crop/pad handling.
`feat/remotion-delivery-qc` adds delivery intents, loudness measurement/normalisation and
deliverable checks. Its three skills are not available in this branch. Matrix review files
cannot claim those checks until the real operations run and the actual artifacts open/play.

The routing fixture preserves RT-E001..RT-E079. Thirty-eight rows are active and forty-one
are deferred to named branches or unverified candidate semantics. Including the earlier
fixture, there are 218 rows, 173 active and 45 skipped. Current inventory is 16 providers,
115 Gateway tools and 25 packaged skills. No secrets are added.
