# Art style motion

[The skill](../agent/deep_agent/skills/art-style-motion/SKILL.md) plans shorts in a named art
style, named animation grammars and characters walking through painting worlds. It adds
instructions and routing, using the existing image, audio and render tools. There are no
new provider adapters, Gateway tools, secrets, dry-run flags or Studio model labels.

## Cut-paper explainers

The [cut-paper recipe](../agent/deep_agent/skills/art-style-motion/references/grammar-cards.md#cut-paper-explainer)
covers layered shading, consistent shadows, muted backgrounds, takeaway banners, measured
speech cues or silent holds, smooth camera motion and subtle stepped labels. It distinguishes
sourced evidence from illustrated metaphor sets. It also describes deterministic frame-based
Remotion authoring for separately supplied clips. It is not an executable template. Custom
paper filters, articulated cutouts, parallax, label boil and word-pop captions still require
authored motion assets. Missing effects remain an incomplete storyboard or preview.

The source is [sanat's papercut-explainer](https://github.com/0xS4N4TG/papercut-explainer/tree/5a342bf855160379b4684e1c49f2e3faaecd5d0b),
read 2026-10-15. The official [MIT licence](https://github.com/0xS4N4TG/papercut-explainer/blob/5a342bf855160379b4684e1c49f2e3faaecd5d0b/LICENSE)
and [third-party exclusions](https://github.com/0xS4N4TG/papercut-explainer/blob/5a342bf855160379b4684e1c49f2e3faaecd5d0b/THIRD_PARTY.md)
were checked at that revision. Guidance from `style-guide.md`, `motion-principles.md` and
`remotion-recipes.md` is adapted in our own words. The full copyright and licence notice is
in the grammar reference, [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES) and
[third_party/papercut-explainer/LICENSE](../third_party/papercut-explainer/LICENSE), including
wheel licence metadata. No upstream runtime, code recipes, installer, voice system, media,
fonts, dependencies, AGPL code or non-commercial weights are imported.

This extension adds no model ID, endpoint, request schema, price, licence policy or training
grant. Existing capability selection, paid-video cost approval and spending caps apply.
The upstream vertical canvas is a design reference; output geometry follows the existing

## Selection and tool contracts

The existing schemas and typed provider contracts validate before submission. Image and
audio calls retain non-autonomous approval and the autonomous spend cap. Paid video retains
cost approval even when autonomous. Native deepagents 0.7.23 skill loading, interruption,
rejection/resume and outcome recording are reused without harness changes. Unknown quotes
remain unknown. The skill does not change `APPROVAL_EXEMPT_TOOLS` or spend limits.

## Port and executable limits

The wheel packages the skill and all three references, with the MIT licence and third-party
notices in its licence metadata. AgentCore copies the notices beside the source.

The method and cards are English adaptations of
[alchaincyf/huashu-art-motion at d861767d180008d27675819932070a670a3ae43f](https://github.com/alchaincyf/huashu-art-motion/tree/d861767d180008d27675819932070a670a3ae43f),
read 2026-10-10. The source is MIT. Each adapted file includes its copyright and full notice;
[third_party/huashu-art-motion/LICENSE](../third_party/huashu-art-motion/LICENSE) and
[THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES) preserve attribution. The 35 style cards omit
upstream number 07; the nine grammar cards include the illustrated-presenter method.
Ukiyo-e now has a descriptive catalog card. It remains separate from the 35 upstream art cards.

No Python renderer, runtime dependency, fonts, stroke data, character artwork, sprites or
demo media were ported. The upstream README excludes its character/demo assets from MIT
and labels them demo-only. No AGPL or non-commercial code/weights are added.

## Official verification and pricing

The relevant public pages were re-read **2026-10-10**. Existing billing entries retain their
original 2026-10-08/09 source dates; the new decision file records the actual re-read date.
No source date is backdated and no billing rates are changed in this skill-only addition.

## Licence and training policy

## Routing coverage and remaining checks

Comet is unavailable in this environment. Browser E2E is **blocked**, including Studio
selection/disclosure, visible approval/rejection and artifact playback. Evidence belongs in
ignored `.renderhaus/e2e/` and is recorded through `scripts/browser_e2e_hook.py`. Public docs
verification does not validate provider responses or animation quality.

No new environment variables or secrets are required. Existing provider credentials and
cost-quote configuration remain operator responsibilities for a separately authorized live
run. Keep every dry-run flag enabled. See

## Descriptive catalog

The existing skill now has 141 catalog entries from 98 specialized film-look prompts
and 43 general style guides. No exact duplicate source prompts or cross-set style names
were found. Related media stay separate because their palettes, materials, shot grammar,
and motion rules differ. The original styleboard tags are 77 2D, four 2.5D, and 17 3D.
The 43 guide tags are derivative interpretations of their documented technique, comprising
32 2D, four 2.5D, and seven 3D. These tags describe treatment, not delivered dimensions.

`read_studio_context.style_catalog` supplies safe selection and browse results from
[the index](../agent/deep_agent/skills/art-style-motion/references/catalog/index.json).
A neutral name, slug, or input alias wins over a default. A user-named existing art or
grammar card wins over an inferred catalog match. Unknown looks retain the original
card-building fallback. Browse returns descriptive names and summaries without generating
assets. The original 35 art and nine grammar cards now have descriptive display labels;
legacy names remain accepted as inputs.

The pure host lookup belongs in `agent/deep_agent/art_style_catalog.py`. It reads only
safe index fields and sanitized card tables. There is no new Gateway tool. The existing
planner has read-only skill access and no shell, so an unconnected Python helper would
not run. The host context is the existing bridge. Search is deterministic, limits results
to 1–20, rejects queries over 500 characters, and copies results to protect cached data.
Studio briefs are capped at 64,000 characters. Browse summaries cover all 141 entries.
Named style clauses after the topic remain explicit. Topics about using a material,
negated looks, and quoted titles do not select a style. Inferred looks match descriptive
names, aliases, and keywords; durations and generic planning terms cannot choose one.
Deliberate searches also use prompt and direction prose. Unsupported nonempty queries
return no matches.

All 141 catalog entries have recorded prompt or direction adaptations. The committed
[internal scan](../third_party/lemo-opuscar/BRAND_SCAN.json) records original and adapted
fields, source mappings, denied terms, and source occurrences. There are zero remaining
denied terms in the public index. The scan records 1,074 denied terms and 800 field
adaptations across all 141 entries. Ordinary movement and material words that collide
with short names use descriptive synonyms. The 302 example shots become reusable camera-direction
notes, with source durations explicitly labeled as examples. No demo plot, character,
film title, living artist, provider name, or service fee belongs in a card or generation
prompt. Brand-derived input aliases are private lookup metadata and never echoed.
Operational tool names and required provider/cost disclosures retain their existing contract.

Verbatim original text is stored outside the agent's skill filesystem in
[internal provenance](../third_party/lemo-opuscar/NOTICE.md). Each of 130 original text
files is an unmodified string with a SHA-256. Only the normalized index and MIT licence
ship as skill reference data. The attribution and licence also ship in wheel metadata.
No posters, frames, fonts, music, voice, video, subtitles, executables, or upstream
render tooling are imported. `_template` is excluded. Rebuild with
`.venv/bin/python scripts/import_art_style_catalog.py`; add `--check` to detect drift.

The source is MIT, copyright 2026 LemoLab, at
[revision e3cb16f63768c68693ff0e15171d6e755457cc32](https://github.com/lemomo-ai/lemo-opuscar/tree/e3cb16f63768c68693ff0e15171d6e755457cc32),
read 2026-10-10. The pinned MIT licence and source bytes were rechecked on 2026-10-14.
Original data, guides, and demo descriptions are internal provenance.
Neutral names, categories, aliases, keywords, prompts, direction notes, and guide dimension
tags are derivative metadata. The [MIT notice](../third_party/lemo-opuscar/LICENSE) is kept.
Mapping a named real film's look onto a user's topic can imply association or IP risk.
Prompts must stay descriptive of style. MIT text permission grants no rights to films,
characters, trademarks, music, likenesses, or third-party demo media.

No model, endpoint, provider, rate, model licence, training eligibility, key, or dry-run
flag is added or changed. No new price is used. The existing model policies in the table
above remain false for training eligibility. Unknown media estimates remain unknown
and existing approvals remain required. This catalog adds planning text, not a generative
video model or a procedural animation renderer.

Browser E2E is blocked because Comet is unavailable. Native graph tests use scripted
models and mocked Gateway services; they do not prove Studio UX or media quality.
No live calls or rendered-media claims are made.

## Catalog feature verification on 2026-10-14

Before the Lottie merge, the Python 3.11 run passed 2,491 pytest tests, with eight skips and 4,329 passing
subtests. The full unittest suite runs 2,499 tests, with the same eight skips. Ruff,
`scripts/ci_check.py` with secrets lookup disabled and every dry-run flag enabled, and
Studio `tsc --noEmit -p .` pass. The temporary Studio dependency link is removed.

The source byte comparison covers all 130 imported text files and the MIT licence.
The catalog rebuild has no drift. Every neutral catalog name selects its own card.
The built wheel matches the current lookup, routing, safe index, and licence bytes.
It excludes internal catalog source and scan data. Native review reproductions pass.
These checks are offline contracts and artifact checks, not a scored model eval.

Comet E2E is blocked, including Studio browsing/selection, visible approval/rejection,
and actual media playback. No live provider calls or generated media were evaluated.
External model-family review was skipped under the offline-only scope. No new tools,
models, prices, model licences, training eligibility, environment variables, secrets, or
dry-run flags are introduced.
