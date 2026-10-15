# Chat story video

The `chat-story-video` skill creates faceless fictional conversations from approved text.
It uses a procedural chat layer in the existing `RenderhausTimeline` composition. It never
calls a generative video model for the thread. Text stays verbatim; wrapping adds display
line breaks and never changes the message value.

## Existing tools, extended arguments

No Gateway tools, providers, paid model adapters or dispatch IDs were added. The inventory
is 18 providers, 134 tools and 38 skills. The existing contracts were extended:

| Tool | Chat arguments |
| --- | --- |
| `Remotion___render_timeline` (`remotion_render`) | `title`, `chat_story`, optional `fps` and `audio_tracks`; omit `visuals`, overlays and subtitles |
| `Remotion___render_ad_variants` (`ad_variant_matrix`) | `stage`, `job_id`, `brief={mode:chat_story,campaign,fps}`, `rows=[{variant_key,chat_story,aspect?}]`, `plan_hash`, `concurrency`; omit `master_asset` |
| `Remotion___get_render_progress` | Existing render ID and `bucket_name=local` |
| `Ffmpeg___ffmpeg_tool` | Existing probe, frame extraction, contact sheet, hashing and loudness operations |
| `Remotion___deliver_render`, `Remotion___qc_deliverable` | Existing job-relative input or manifest and delivery preset; `social-vertical` for portrait |

Typed JSON Schema validation runs before dispatch, and pure payload/planning validation
runs before dry-run or rendering. Neither path accepts JSX, HTML, executable code or raw
FFmpeg arguments. Shared executor approvals, trusted host authorization, autonomous spend
caps and exempt tools keep their existing behavior. Planning is free. Both matrix render
stages require a host approval and cost estimate, including autonomous runs. A sample
approval covers that render stage only; batch approval is a separate decision bound to the
unchanged plan hash. No approval fields are accepted from a model's tool arguments.

## Message contract

The pure loader accepts a JSON array or RFC-style quoted CSV. CSV must have unique `from`
and `text` columns; its other allowed columns are `typingMs,delayMs,status,reaction`.
The Gateway `chat_story.messages` field accepts the resulting array. The offline batch
driver can ingest CSV directly. Quoted commas, quotes, newlines, emoji and ordinary RTL
text survive normalization unchanged. Duplicate JSON keys and malformed CSV are refused.

| Field | Bound/default |
| --- | --- |
| Messages | 1–40; serialized message input at most 256 KiB |
| `from` | `me` or `them` |
| `text` | Nonempty plain text, at most 500 Unicode code points; whitespace preserved |
| `typingMs` | Finite 0–10000; received messages default to `clamp(len(text)*20,700,1500)`; sent messages must have zero |
| `delayMs` | Finite 0–30000; default 600 |
| `status` | Empty, `sent`, `delivered`, `read`; sent messages only |
| `reaction` | Empty or `❤️`, `👍`, `😂`, `‼️`, `❓` |
| `contact` | Fictional name, at most 40 code points, and `avatar=initials` or `placeholder`; default Friend/initials |
| `aspect` | `9:16` (1080×1920), `1:1` (1080×1080), `4:5` (1080×1350) |
| `theme` | `generic` by default; see legal gate below |
| `dramatization` | Boolean, false by default; adds a neutral on-screen tag |
| `sfx` | Boolean, true by default |
| `holdMs` | 500–10000, default 2000 |
| `platformTargetMs` | 1000–600000, default 60000; excess produces a warning |
| `music_ref`, `send_sound_ref`, `receive_sound_ref` | Optional supplied local audio references, at most 200 characters, confined by the executing host |

Timings exclude booleans, NaN and infinity. Unsupported fields/statuses/reactions are
refused. HTML tags, unsafe control characters, surrogate values and bidi override/isolate
controls are refused. Messages too tall for the safe band, and contact names that cannot
fit the bounded header font, are refused with an explanation; the renderer never shortens
or rewrites them. Non-emoji joining sequences and chains longer than three emoji joiners
are refused. The local worker also measures line width and refuses unsupported joined
glyphs instead of clipping them. Plain strings are rendered as text nodes in React.

## Timing and layout

`providers/remotion/chat_story.py` is the pure, deterministic planner. Each delay advances
the frame clock with ceiling rounding. Received typing comes next; then the bubble pops
over roughly 160 ms, followed by a 250 ms minimum settling gap. Sent receipts appear
300 ms after the last bubble of a sender run. Reactions appear 400 ms after their bubble.
The final duration includes the last settling gap and the requested hold. FPS is an integer
1–60 and total duration cannot exceed the existing 600-second worker bound.

Sent bubbles sit right and received bubbles left. Only the final bubble of a sender run
gets a tail. Width is at most 74% of the canvas. Wrapping prefers word boundaries and
preserves combining marks, emoji modifiers, joined emoji and paired flags. Unbroken long
words wrap between complete grapheme clusters. The conservative width allowance covers
the emoji font's advance. The newest bubble, receipt and reaction stay above a 360 px
portrait bottom safe band; square/feed uses 130 px. Scroll interpolation finishes on the
bubble's reveal frame. These safe zones are product placeholders, not certified platform
specifications. The plan includes every bubble frame/box, scroll offsets, duration, SFX
cues, warnings and review frames at the first settled bubble, midpoint and last frame.

## Themes and fiction safety

Only `generic` is enabled by default. Neutral `slate` and `moss` colour/shape presets are
registered behind `CHAT_STORY_LOOKALIKE_THEMES=on`; the default is `off`. Requests using
the input aliases `iMessage-style` or `WhatsApp-style` route here and fall back to generic
while off, with the explicit explanation that the requested lookalike appearance is not
enabled and legal sign-off is required. Branded-lookalike themes need legal sign-off before
shipping or enabling. Presets/assets/output labels contain no vendor logos, wordmarks,
trademark names or copied icons. Do not enable a preset without an explicit request.

The validator refuses real-looking phone numbers with at least seven decimal digits,
including common separators and non-ASCII decimal digits. It flags known named brands or
public figures used with impersonation cues, and known identities used as contacts. This
check ignores invisible format characters on a separate safety view, never changing copy.
The identity
heuristic is not an exhaustive identity detector. The skill requires resolving those
flags with approved fictional replacements before rendering. No private-person photos
are accepted: avatars are generated initials or a neutral placeholder. A requested
dramatization label remains optional and does not bypass these checks.

## Batch workflow

Each row is one script and one render. The bound is 1–50 rows, at most 2 MiB of batch
input, and concurrency 1–2. JSON rows use `{variant_key,chat_story,aspect?}`. CSV uses
`variant_key,messages` plus optional `contact,theme,aspect,music_ref`; the messages cell
contains a quoted JSON array or a quoted message CSV. Keys use 1–40 ASCII letters,
digits, underscores or hyphens. Invalid rows stay in the manifest with their input hash,
status and exact reasons while valid rows remain runnable.

1. Plan the whole immutable table; review the normalized props, warnings, cost and hash.
2. Approve `render_first` for that hash. It renders the first valid script and extracts
   three stills plus a contact sheet through the existing FFmpeg still operations.
3. Open the actual full MP4 and stills. Batch approval covers that unchanged sample and
   hash; renderer success does not certify visual, text or editorial acceptance.
4. Approve `render_batch` separately. Missing/failed samples, stale media hashes, changed
   plans, corrupt manifests or changed saved QC reports block reuse. Sources are frozen
   and hash checked. One later failure does not stop other rows. Attempts and failures
   persist; no blind retries occur on resume.
5. Use loudness finishing and deliverable QC on all successful files. The manifest keeps
   blocked/failed rows and each failure verbatim, so a partial batch never becomes an
   overall successful delivery. Each artifact has input/output SHA-256, dimensions,
   source resolution, technical QC and pending editorial status. Per-row declared read
   holds/silent gaps pass into final QC. Changed output checksums invalidate saved passes.

The CLI reuses this workflow rather than adding another render or approval implementation:

```sh
.venv/bin/python scripts/run_chat_story.py plan --job-id JOB --table scripts.csv
.venv/bin/python scripts/run_chat_story.py render_first --job-id JOB --table scripts.csv --approve-plan HASH
# Open the sample and stills before approving the remaining batch.
.venv/bin/python scripts/run_chat_story.py render_batch --job-id JOB --table scripts.csv --approve-plan HASH
```

These commands inherit `REMOTION_DRY_RUN=true` by default. Operators must explicitly
select the local worker and authorize real local rendering. Secrets are unnecessary.
Studio resolves direct chat audio references through its owned asset resolver or confines
them to the authenticated job; batch audio must be a regular supplied file inside its job.

## Audio, backends and evidence limits

The local worker synthesizes two 120 ms PCM tones in code, without a downloaded sound pack
or third-party SFX. Send/receive events start on the exact bubble frames using the existing
`audio_tracks` mixer. Supplied pops replace those tones. A supplied music bed uses existing
gain segments, reduced from 0.18 to 0.07 for 240 ms around each pop. Music is not generated,
downloaded or looped automatically. Supplied audio must cover its intended duration.
Default pop-only tracks declare their intentional silent gaps. Muted stories have no
loudness certification; require-audio targets need an audio-bearing mix.
Sparse pop-only mixes can fail a programme loudness target after normalization. The real
local test observed a -20.15 LUFS result against the social preset's -14 LUFS target,
along with a true-peak and silence failure. That candidate was retained as failed. An
original supplied music bed under a new approved test plan passed final QC; a renderer
must never relax its target or silence gate merely to declare delivery.

Both the native React layer and the local FFmpeg/Pillow worker consume the same validated
plan. `remotion/src/ChatStorySchema.ts` validates the native normalized payload and frame
plan with pinned Zod 3.25.76, without coercing or rewriting text. The runtime schema test
uses an exact Python-generated fixture, rejects 18 malformed inputs, and checks the
existing message-order and viewport guards. The existing local worker prepares frames
asynchronously before audio assembly.
Installed DejaVu Sans and Noto Color Emoji fonts are required; no font/assets were copied
from the pattern project. The native layer loads operator-staged local font files. Mixed
RTL text with embedded Latin runs around emoji is refused by the local renderer where
its font-run layout cannot preserve order safely. Ordinary RTL and supported emoji are
covered by tests; unsupported font scripts still need visual review.

**UNVERIFIED:** no live Lambda render or native browser/Comet playback was performed.
`providers/remotion/capabilities.py` declares chat local-only and refuses Lambda before
client creation or media work. This remains disabled on Lambda until its font staging,
native render, audio parity and output have been verified. Local technical checks cannot
accept framing, captions or legal/price copy. Browser E2E in Comet is blocked because this
environment cannot control Comet; local binary checks are supporting evidence only.

RT-180 and RT-181 are active. Six added negatives protect talking-head edits, per-market
ad matrices, lower thirds and unrelated briefs mentioning text messages. The fixture has
289 combined rows with podcast-audiogram: 283 active and six unchanged dependency skips. Selection stays explicit request,
exception predicate, default, without tiers or confidentiality-based routing. Existing
demoted providers remain available under their existing policies.
The skips are four capture/cutaway-record rows (`feat/product-demo-capture` pending), one
HyperFrames-overlay row (`feat/hyperframes-overlays` pending) and RT-E043 (exact end-card
OCR comparison unavailable). RT-176 is one of the four capture rows.

## Local verification

The real local sample exercised generic chrome, verbatim emoji/RTL copy, read receipts,
reactions, synthesized pops, a supplied original music bed, three review stills, the
first-render gate, two valid batch rows and one deliberately invalid row. FFprobe measured
two final H.264/AAC files at **1080×1920, 30 fps**, lasting **6.000 s** and **4.333 s**.
Final loudness was -14.03 and -14.01 LUFS. Their saved deliverable-QC report passed and
still matched both output checksums. `source_resolution` is unknown, not inferred from
the canvas. Resolution warning: "Original source_resolution is unknown; input dimensions
do not prove native source detail." The report also warns that the delivery preset is a
placeholder and that captions, legal copy, prices and editorial content need visual review.
The Comet receipt is **blocked**, and playback/Studio E2E remains pending.

The partial fixture retained its failure verbatim: "Messages must contain 1-40 records."
Two valid scripts rendered, but the whole partial delivery correctly remained failed.
An earlier pop-only candidate also remained failed; its saved failures were:

```text
loudness: Integrated -20.15 LUFS; target -14 +/- 0.5. Programme loudness; dialogue gating unavailable. Clips below 3s cannot be certified.
true_peak: True peak -1.49 dBTP; ceiling -1.5.
silence: Unexpected silence intervals [{'start_s': 1.068042, 'end_s': 2.113708, 'duration_s': 1.045666}]; allowed [{'start_s': 0.0, 'end_s': 0.9}, {'start_s': 1.02, 'end_s': 2.066666666666667}, {'start_s': 2.186666666666667, 'end_s': 4.333333333333333}].
```

Ignored evidence is under `.renderhaus/e2e/` and `.renderhaus/media/chat-verification-final/`;
the earlier failed pop-only experiment remains under `.renderhaus/media/chat-verification/`.
These technical observations do not certify a customer delivery or visual acceptance.

Final offline checks on 2026-10-10 passed: **2,536 full-suite tests, eight skips** (the
starting commit passed 2,448 tests with eight skips), 79 focused chat tests, Ruff,
`scripts/ci_check.py`, capability parity, and Studio TypeScript. The native runtime test
executes 21 cases with real Zod 3.25.76. Studio used a temporary module tree based on the
provided clone, supplemented by five missing dependencies from the existing staging
clone; all temporary repository links were removed. No dependencies were downloaded.
All full-suite and CI provider flags stayed dry-run with `RENDERHAUS_SECRETS_NAME=""`.
Only the separately authorized local FFmpeg verification used live local rendering.
Mocked deployment messages in unittest output are not AWS actions.

## Price, licences and provenance

No paid generation price, model ID, request endpoint, API adapter, model licence or training
eligibility was added. Rendering/QC remains `training_eligible=false`. Local compute is
quoted as $0 excluding operator compute; the existing configurable
`REMOTION_LICENSE_RENDER_USD` allowance defaults to $0.01 per render. It is an allowance,
not a verified charge. Remotion's official automator terms list $0.01/render with a
$100/month minimum for applicable licences; eligibility must be checked by the operator.
[Official licence FAQ](https://www.remotion.dev/docs/license/faq), re-read **2026-10-10**;
the existing billing entry retains its earlier **2026-10-09** read date. No date was backdated.

The pattern project was read as a MIT workflow reference, without copied code/assets or a
new dependency. Attribution and its MIT notice ship next to the skill. Sources read
2026-10-10: [pattern MIT licence](https://github.com/iart-ai/text-message-video-skills/blob/main/LICENSE),
[Remotion licence](https://www.remotion.dev/docs/license/faq),
[FFmpeg licensing](https://ffmpeg.org/legal.html),
[DejaVu font licence](https://dejavu-fonts.github.io/License.html),
[Noto emoji font OFL-1.1](https://github.com/googlefonts/noto-emoji/blob/main/LICENSE).
The new native validation dependency is [Zod 3.25.76](https://v3.zod.dev/), under the
[MIT licence](https://github.com/colinhacks/zod/blob/main/LICENSE), read 2026-10-10.
FFmpeg's actual LGPL/GPL obligations depend on the installed build; no binary is vendored.
These software/font licences do not confer model training rights. No AGPL or non-commercial
code/weights were added. Installed Deep Agents 0.7.23 signatures govern host integration;
no new graph, middleware, external eval provider or approval mechanism was introduced.

See [decisions](chat-story-video-decisions.tsv), [skill](../agent/deep_agent/skills/chat-story-video/SKILL.md),
[Remotion editing](REMOTION_EDITING.md) and [browser verification](BROWSER_E2E.md).
