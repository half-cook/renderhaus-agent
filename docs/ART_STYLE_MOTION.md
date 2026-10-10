# Art style motion

[The skill](../agent/deep_agent/skills/art-style-motion/SKILL.md) plans shorts in a named art
style, named animation grammars and characters walking through painting worlds. It adds
instructions and routing, using the existing image, audio and render tools. There are no
new provider adapters, Gateway tools, secrets, dry-run flags or Studio model labels.

## Selection and tool contracts

Explicit requests win, then a matching exception, then the quality-first default. Named art
or grammar briefs select this skill. A supported explicit generated-video provider keeps
its existing path and disclosure, including explicit-only Kling, Runway and Luma. Cost,
tier and project confidentiality do not select a model. Local continuity QC is unchanged.

| Routing ID | Existing Gateway tool | Key arguments |
|---|---|---|
| `remotion_render` | `Remotion___render_timeline` | `title`, `visuals` with asset kind/URL/duration; optional `audio_tracks`, `text_overlays`, `subtitles`, `aspect_ratio`, output settings |
| `hyperframes_render` | `HyperFrames___render_composition` | `html`, `duration_seconds`, `width`, `height`, `fps`; named HyperFrames only, gated dry-run-only preview |
| `gpt_image25_t2i` | `OpenAI___generate_image` | `prompt`; optional `size`, `quality`, `background`, `n`, `model=gpt-image-2.5-sunburst` |
| `eleven_v4_turbo` | `ElevenLabs___text_to_speech_convert` | `voice_id`, `text`, `model_id=eleven_v4_turbo`; optional output/voice settings |
| `elevenlabs_sfx_v2` | `ElevenLabs___text_to_sound_effects_convert` | `text`, `model_id=eleven_text_to_sound_v2`, `duration_seconds` (0.5–30); optional `loop`, `prompt_influence` |

Rendering defaults to Remotion; generic HTML is not the HyperFrames exception. Character
frames remain available even when a style brief includes narration. An explicit audio
provider is scoped to audio, so it cannot force the character-image provider. Supplied
voiceover is reused, silent work excludes speech, and music is not inferred.

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
Ukiyo-e is an additional user-reference style, not a nonexistent upstream card.

No Python renderer, runtime dependency, fonts, stroke data, character artwork, sprites or
demo media were ported. The upstream README excludes its character/demo assets from MIT
and labels them demo-only. No AGPL or non-commercial code/weights are added.

The current render tool composes assets with supported simple motion and overlays. It
does not execute arbitrary JSX, a style card, procedural brushwork, mathematical morphs,
marker paths, sprite rigs or continuous world scrolling. These require rights-cleared
authored clips or a future renderer/template implementation. Missing motion stays blocked;
a still pan is not a completed animated-painting treatment. HyperFrames remains validation
only. No rendered media or visual quality result is claimed by this offline implementation.

## Official verification and pricing

The relevant public pages were re-read **2026-10-10**. Existing billing entries retain their
original 2026-10-08/09 source dates; the new decision file records the actual re-read date.
No source date is backdated and no billing rates are changed in this skill-only addition.

| Component | Official ID/schema evidence | Price used or unresolved quote |
|---|---|---|
| GPT Image 2.5 | [Model](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst), [generation guide](https://developers.openai.com/api/docs/guides/image-generation), [Images generate API](https://developers.openai.com/api/reference/resources/images/methods/generate): `gpt-image-2.5-sunburst`, snapshot `gpt-image-2.5-sunburst-2026-09-08`, JSON Images generation | Official token rates: $5/M text input, $8/M image input, $30/M image output. Existing $0.20/image approval estimate is product-directed, **not an official flat tariff**; actual usage determines cost. Operator quote can override it. |
| Eleven v4 Turbo | [Models](https://elevenlabs.io/docs/overview/models), [TTS convert](https://elevenlabs.io/docs/api-reference/text-to-speech/convert): `eleven_v4_turbo`, POST `/v1/text-to-speech/{voice_id}` | [API pricing](https://elevenlabs.io/pricing/api): regular Turbo $0.04/1,000 characters; promotional $0.011/1,000 through 2026-10-12. Existing expiry logic and platform fee retained. |
| ElevenLabs SFX v2 | [SFX convert](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert): `eleven_text_to_sound_v2`, POST `/v1/sound-generation` | [API pricing](https://elevenlabs.io/pricing/api) publishes SFX from $0.12/minute; this does not establish the per-call metered quote. Existing estimate stays **unknown** pending operator configuration. |
| Remotion | Existing repo timeline schema; [licence](https://www.remotion.dev/docs/license), [licence FAQ](https://www.remotion.dev/docs/license/faq) | The applicable Automators licence lists $0.01/render with a $100 monthly minimum for teams requiring that licence. It is not an AWS compute quote. Existing render estimate remains **unknown/TODO**. |
| HyperFrames | Existing local tool; [Apache-2.0 licence](https://github.com/heygen-com/hyperframes/blob/main/LICENSE) | No live render implementation or paid price is introduced. Dry-run only. |

## Licence and training policy

| Model/component | Licence/source | Existing `training_eligible` decision |
|---|---|---|
| GPT Image 2.5 and snapshot | Closed weights; commercial API [Services Agreement](https://openai.com/policies/services-agreement/), input rights and applicable [usage policy](https://openai.com/policies/usage-policies/) | `false`: agreement 3.3(e) restricts competing AI training; no accepted continuity-training grant. Output ownership does not establish such a grant. |
| Eleven v4 Turbo | Closed commercial service under [ElevenLabs terms](https://elevenlabs.io/terms-of-use); paid-plan commercial use and authorized voice rights | `false`: no clear model-training permission verified. No voice cloning is added. |
| ElevenLabs SFX v2 | Commercial service under [ElevenLabs terms](https://elevenlabs.io/terms-of-use) and [API pricing](https://elevenlabs.io/pricing/api) | `false`: no explicit model-training grant verified. |
| Remotion render | [Remotion custom/commercial licence](https://www.remotion.dev/docs/license) plus existing in-house exporter policy | `false`: code/render permission does not grant rights over source media or model training. |
| HyperFrames | [Apache-2.0 code](https://github.com/heygen-com/hyperframes/blob/main/LICENSE) | `false`: code licence does not grant source-media rights. |
| huashu method/cards | MIT at the pinned revision above | Not a model; no routing training eligibility is added or changed. Demo assets are excluded. |

## Routing coverage and remaining checks

The packaged inventory is 32 skills, 16 providers and 120 Gateway tools. The routing fixture
has 243 retained rows: 238 active, five unchanged skips. RT-160 and RT-161 cover named art
and grammar routing. RT-162 asserts that a silent explainer without a named style stays in
knowledge-explainer. The input CSV has 148 data rows, no test IDs and no art-style cases;
these three prompts are task/draft reconstructions and are labeled as such in the fixture.
Exact workbook provenance remains pending the missing export. The unchanged skips are
one HyperFrames-overlay case (`feat/hyperframes-overlays`), three `cutaway_record` demo
cases (`feat/product-demo-capture`), and RT-E043's exact end-card OCR comparison
(`feat/remotion-ocr-verification`). No pending provider row was falsely activated.

Offline tests cover native loading of the skill/cards, explicit provider precedence,
quoted/negated style boundaries, static art, existing-footage editing, audio postprocessing,
supporting image/audio selection, HyperFrames gates and autonomous render rejection/resume.
These are deterministic routing/graph checks using fakes, not a scored model eval or live E2E.

Comet is unavailable in this environment. Browser E2E is **blocked**, including Studio
selection/disclosure, visible approval/rejection and artifact playback. Evidence belongs in
ignored `.renderhaus/e2e/` and is recorded through `scripts/browser_e2e_hook.py`. Public docs
verification does not validate provider responses or animation quality.

No new environment variables or secrets are required. Existing provider credentials and
cost-quote configuration remain operator responsibilities for a separately authorized live
run. Keep every dry-run flag enabled. See
[decisions](art-style-motion-decisions.tsv) for provenance and open production dependencies.

Validation on 2026-10-10 passed Ruff (`agent lambdas scripts server providers`), the
full unittest suite (2,084 tests, seven skips), `scripts/ci_check.py` with every provider
dry-run flag enabled and secrets lookup disabled, Gateway schema drift checks, Studio
`tsc --noEmit -p .`, and an offline wheel build/content/relative-link inspection. The
starting commit passed 2,069 tests with the same seven skips. The focused skill suite has
12 tests; routing/skill-contract verification has 255 tests with five fixture skips.
Native review found no remaining blocking issue after its reproduced cases were added.
The temporary Studio dependency symlink was removed. Browser E2E is still blocked.
