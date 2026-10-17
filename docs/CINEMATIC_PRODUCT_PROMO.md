# Cinematic product promo

`cinematic-product-promo` plans product launch films using 157 local shot recipes, a
supplied measured music-beat grid and separate SFX/music/VO tracks. Assembly uses the
existing `remotion_render` capability. The only new Gateway tool is
`ShotRecipes___shot_recipe_search` (canonical ID `shot_recipe_search`). It has no keys,
network calls, model calls, rendering operation, dry-run flag or spending approval.
Its billing entry is zero. Existing rendering, music and narration retain their
approval and cost controls, including autonomous paid-video approval.

## Launch motion techniques

The skill includes three optional
[technique cards](../agent/deep_agent/skills/cinematic-product-promo/references/launch-motion-techniques.md)
adapted from product-launch-motion. `one-shape-morph` preserves a container across UI
states, `spring-settle` specifies a restrained physical response, and
`cursor-driven-reveal` makes a visible interaction cause the next state. Each card
provides planning guidance, realization limits and artifact review criteria. Musical
accents use a supplied measured grid; sound cues account for the asset's measured peak
or attack. The workflow installs no beat detector or SFX synthesizer.

Product-film requests naming these techniques, or `product-launch-motion`, select
recipe search followed by `remotion_render`. Explicit provider and alternate-renderer
requests retain precedence. Generic website animation and physics explanations do not
select this skill. Routing is a production plan, not proof that a film can be rendered.

Technique IDs are separate from the 157 searchable shot-card IDs. Keep technique notes
in a project file keyed by storyboard beat name. Do not pass them as `card_id`, extra
storyboard fields or custom renderer arguments. The renderer cannot execute arbitrary
shape morphs, spring tracks or cursor events. Full realization requires an actual
supplied pre-rendered shot, assembled as one native visual with `motion: none`.
Preserve and disclose a missing shot before submission. A customer-approved simplified
treatment must be labeled as such. The default fps, source resolution and cost approvals
remain in force. The source's HTML/browser/FFmpeg pipeline is not installed.

The adapted prose comes from the source's
[skill](https://github.com/AbubakrChan/product-launch-motion/blob/fc566955b073b62d13bd9f5a12b861d0a22cc781/SKILL.md)
and [technique reference](https://github.com/AbubakrChan/product-launch-motion/blob/fc566955b073b62d13bd9f5a12b861d0a22cc781/references/technique.md),
read 2026-10-15. Its
[MIT licence](https://github.com/AbubakrChan/product-launch-motion/blob/fc566955b073b62d13bd9f5a12b861d0a22cc781/LICENSE)
permits adaptation of authored guidance. Its
[NOTICE](https://github.com/AbubakrChan/product-launch-motion/blob/fc566955b073b62d13bd9f5a12b861d0a22cc781/NOTICE)
excludes sample films, frames and third-party assets. The retained
[local notice](../agent/deep_agent/skills/cinematic-product-promo/NOTICE) contains the
full copyright and MIT permission notice. No source runtime, sample media, fonts, audio,
weights or new model/API integration is included. No additional billing entry, secret,
Gateway schema or model policy is needed. See

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

## Routing and verification

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
