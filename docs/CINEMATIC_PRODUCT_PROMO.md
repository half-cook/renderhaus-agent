# Cinematic product promo

`cinematic-product-promo` plans product launch films using 157 local shot recipes, a
supplied measured music-beat grid and separate SFX/music/VO tracks. Assembly uses the
existing `remotion_render` capability. The only new Gateway tool is
`ShotRecipes___shot_recipe_search` (canonical ID `shot_recipe_search`). It has no keys,
network calls, model calls, rendering operation, dry-run flag or spending approval.
Its billing entry is zero. Existing rendering, music and narration retain their
approval and cost controls, including autonomous paid-video approval.

## Local contract

Search arguments: `mode=search` (default), optional `query` (512 characters), `card_id`
(indexed slug, 100 characters), `category`, `max_duration_s` (positive, at most 600),
`energy` (`low`, `medium`, `high`) and `limit` (integer 1–20, default 8). An exact ID
wins over query and filters. Unknown IDs return explicit errors and nearest IDs;
paths, coercible strings, booleans as numbers and unknown arguments are rejected.
Results have neutral ID, English summary, category, typical duration, energy, camera
move, easing, authored component hint and SFX cue. Exact lookup also parses intent,
animation notes, parameter table, sound timing, pitfalls and original timing prose.
Upstream implementation paths and brand names are removed from runtime recipe data.
Search uses English aliases plus original frontmatter, ranks lexically with stable
ID ties, and never executes card content.

Named-card aliases are separate from general search keywords; a generic request for
a product card does not select a named recipe. Quoted card selections are retained
while quoted headline copy stays copy. Examples: `ink press` selects `brand-ink-open`; `crane reveal` finds
`crane-rise-reveal`; `odometer` finds `odometer-digit-roll`. The original surface
metaphor filename `runway-ground-skim.md` has the neutral public ID `ground-skim`.
That mapping is private provenance; imported bytes and frontmatter remain unchanged.
A named card is fetched first and preserved with `selection: user_named` and a
`named_cards` entry for its beat. The worker blocks substitution and validation that
omits the requested assignment. Other beats may use other recipes after the named
recipe is fetched.

`mode=validate_storyboard` requires a storyboard object and excludes search filters.
It uses a strict pure Python contract: target duration and aspect, declared fps
(1–120, with native assembly limited to 12–60), sorted unique `beat_grid_s` (up to 2,000 points), 1–100 contiguous beats,
indexed IDs and separate `audio_stems: {sfx: [], music: [], vo: []}`. The payload is
bounded to 128 KiB. Each beat has `beat`, `card_id`, `start_s`, `duration_s`, optional
cue, `cut_snap`, selection and native timeline visual. Named-card assignments must
match both the beat and selection. Total duration must be within +/-5% of target;
interior cuts must land on frames and be within one frame of the supplied grid.
`snap_cut` is a fresh pure helper; equal-distance ties choose the earlier beat.
Validation does not mutate timing or assert that audio beats were detected.

The returned plan has native `render_args`, distinct `audio_stems`, independent
`stem_render_args`, -14 LUFS +/-1 target, and pending visual/media review. Every
visual is timed from its beat and has source audio muted. Supplied stem assets use
separate audio tracks, measured duration and original asset handles. Their timing
must remain inside the plan. Native timeline contracts reject unsupported fields.
Missing visuals allow timing validation but return `render_ready: false`; do not
submit such a plan. A distinct track plan is not evidence of saved stem files.

## Production limits

The existing renderer accepts supported timeline visuals and motions, not arbitrary
JSX, custom components, reference implementations or keyframes. Advanced camera,
masking and typography recipes need actual user-supplied pre-rendered shots or a
future renderer integration. `cutaway_record` remains provider pending, with no new
adapter or endpoint. Use supplied app footage or disclose the capture dependency.
The repository has no music-beat acquisition tool for this workflow; obtain a
measured grid tied to the real track and leave beat-sync verification pending when
it is unavailable. Existing `ffmpeg_tool`, loudness QC, delivery render and
motion-carry QC remain the measurement and finishing paths.

**SFX assets need Mixkit terms review before use.** Imported storyboard cues are
categories only: `transition`, `impact`, `riser`, `ui`, `text`, `data`, `ambience`,
`none`. Actual audio comes from a user-supplied library with usable rights, or the
SFX stem stays empty with a disclosed note. No upstream audio or preview media was
copied, downloaded or referenced by asset file. Music uses `mureka_v95` or a user
track; narration uses `eleven_v4_turbo` with approved copy and voice.

A completed film requires actual artifact playback, actual exported-stem checks,
output cut/beat measurements, integrated -14 LUFS +/-1 and a saved passing delivery
QC report matching every output checksum. Technical matrix checks do not accept
framing, captions, legal copy or prices. Report delivered dimensions,
`source_resolution` and resolution warnings; unknown source dimensions stay unknown.
A larger canvas from 1280x720 must say “upscaled from 1280x720; no added detail”.
Actual enhancement follows the existing `upscale` skill and approval.

## Provenance and rights

Source: [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft/tree/5ddbf521038b0a7accfb6dc1e0a9eb29c67277ab),
read locally 2026-10-10. Only the 157 Chinese shot-card Markdown files were imported
verbatim, with the original [Apache-2.0 licence](../providers/shot_recipes/LICENSE)
and [ATTRIBUTION](../providers/shot_recipes/ATTRIBUTION.md). Upstream has no NOTICE;
our [NOTICE](../providers/shot_recipes/NOTICE.md) records origin, revision and
unchanged status. The English index is Renderhaus-authored derivative metadata.
The attribution explicitly says the referenced source works were not licensed to
the upstream authors. The cards grant no rights to those source works, brand assets,
audio or previews. Reference implementation paths remain non-resolvable provenance
inside card text. No upstream code, TSX, demos, gallery, templates, workbench,
textures, package files or editor export was imported. No AGPL or non-commercial
code/weights were introduced.

The source has 24 strict-YAML errors caused by quoted phrases followed by plain
prose, and 91 cards have no `标签` field. We retain the original bytes and use a
bounded single-line scalar reader, with English keywords supplied by the authored
index. All 157 cards parse with that reader. `BRAND_SCAN.json` inventories source
names and strict-YAML defects. Integrity tests pin the entire source-card digest,
not merely checksums authored alongside the import. Cards total 581,094 bytes;
index/provenance add 185,409 bytes, for **766,503 bytes of packaged data**.
Lambda, agentcore and wheel packaging include the data and licence notices.

The local library is text data, not a model. `training_eligible=false` avoids implying
that card provenance grants source-media training rights. Existing music and speech
models retain `training_eligible=false`; their commercial service rights do not
provide an express training grant. Renderer output likewise gains no new training
permission. Customer assets require their own rights and any voice/likeness consent.

## Official-source checks

Public pages were re-read on **2026-10-10**; existing billing records dated
2026-10-08/09 are retained. This date is not backdated to the source map's read date.
No live API requests were made. All reused providers remain dry-run by default.

| Reused capability | Verified ID/schema and official price | Licence/source and training decision |
| --- | --- | --- |
| `mureka_v95` music bed | `mureka-9.5`, queue endpoint `mureka/api/generate/instrumental`; exactly one of prompt/reference, duration in milliseconds. [API schema](https://fal.ai/models/mureka/api/generate/instrumental/api), [pricing](https://fal.ai/models/mureka/api/generate/instrumental): $0.225 per instrumental request, before existing billing adjustments. | Closed weights, hosted commercial API. [Mureka FAQ](https://platform.mureka.ai/docs/en/faq.html), [host terms](https://fal.ai/legal/terms-of-service); training false, input rights/required consent, no new cloning or vocal-reference support. |
| `eleven_v4_turbo` narration | Official [model list](https://elevenlabs.io/docs/overview/models); [POST /v1/text-to-speech/:voice_id](https://elevenlabs.io/docs/api-reference/text-to-speech/convert), text/model ID/voice settings. [API pricing](https://elevenlabs.io/pricing/api): $0.011/1,000 characters through 2026-10-12, $0.04 thereafter; existing promotion expiry applies. | Closed commercial paid service, [terms](https://elevenlabs.io/terms-of-use); training false, approved voice and source rights, vendor-required consent remains applicable. |
| `remotion_render` assembly | Existing native timeline contract and schema parity checked offline. [Licence/pricing FAQ](https://www.remotion.dev/docs/license/faq): eligible free licence or Company automation licence ($0.01/render, $100 monthly minimum). [AWS compute pricing](https://aws.amazon.com/lambda/pricing/) varies with resources. Exact total per-film compute estimate remains **TODO/unknown**; the pre-existing 8-cent placeholder is not a newly verified official rate. | Proprietary source-available Remotion licence, commercial use subject to applicable plan; not a generation model, no new asset-training grant. |
| `cutaway_record` | No adapter/API verified or added; provider pending. | No new licence or training decision. |

## Routing and verification

RT-174 and RT-175 are active. RT-176 preserves `product-demo-video`, pending
`cutaway_record` then `remotion_render`, and forbidden recipe search. It stays
skipped under the existing capture convention; a direct active negative test checks
its routed skill and forbidden tool. Four additional fixture negatives retain lower
thirds, explicit alternate rendering, knowledge explainer and ad variants; direct
tests also protect art-style, explicit video-model and generic HTML-title requests.
Inventory: 17 providers, 129 Gateway tools, 35 skills, 263 routing rows (257 active,
6 skipped). The other five skipped rows retain their original pending reasons.

New tests cover byte integrity, all-card parsing, brand hygiene, deterministic search,
strict bounds, named cards, storyboard timing/audio plans, actual offline Deep Agents
0.7.23 dispatch, schema/registry parity, and archive/wheel contents. Public-source
verification and native offline review do not substitute for browser E2E. Native review found and fixed top-level renderer limits, malformed guard input,
quoted card selection, generic keyword ambiguity, late audio, missing spec routes
and neutral error labels. External
cross-model review lanes were not run under the offline-only instruction.

Comet browser E2E is **blocked**: Comet is unavailable in this environment, as stated
by the task. No browser actions or generated-media playback occurred, and no live
provider calls were authorized. The ignored report under `.renderhaus/e2e/` records
this dependency; browser E2E, playback, exported-stem QC and final-film loudness remain
pending. There are no new env vars, secrets or dry-run flags. `scripts/sync_secrets.py`
is unchanged because the new tool uses no keys.

Final offline verification (2026-10-10): **2,347 unittest tests passed, 8 skipped**;
26 focused recipe/runtime tests and 15 focused cinematic routing tests passed.
The routing fixture suite ran 275 tests, with 6 pending rows skipped. Ruff passed
on `agent lambdas scripts server providers`. `scripts/ci_check.py` passed with
`RENDERHAUS_SECRETS_NAME=""`, all requested dry-run flags true, and an offline pip
wheelhouse; it built a 25,782,269-byte Lambda archive. The final wheel's modules,
157 cards, index and provenance matched working-tree bytes. Studio `tsc --noEmit -p .`
passed with a temporary link to `/workspace/rh-staging/studio/node_modules`, removed
afterwards; the suggested `/workspace/rh-runway-aleph` tree lacked six required
packages. An offline shell simulation verified that a recipe-data-only edit selects
its Gateway target and rebuilds the runtime. No push, PR, deployment or paid/live
provider call occurred.
