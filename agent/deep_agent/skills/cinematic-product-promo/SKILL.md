---
name: cinematic-product-promo
description: Plan cinematic product launch films with shot recipes, deliberate camera moves, beat-synced cuts and separate sound tracks.
metadata:
  remotion_backend: configured
  remotion_features: clip_timing transitions fit_position scale motion titles captions audio_mix canvas encoding
  include_tools: call_editor_tool call_audio_tool
  routing_tools: shot_recipe_search remotion_render cutaway_record eleven_v4_turbo mureka_v95 ffmpeg_tool delivery_render deliverable_qc motion_carry_probe
  gateway_tools: ShotRecipes___shot_recipe_search Remotion___render_timeline Remotion___get_render_progress ElevenLabs___text_to_speech_convert Mureka___generate_instrumental Mureka___generate_song Mureka___get_music_task Ffmpeg___ffmpeg_tool Remotion___deliver_render Remotion___qc_deliverable Remotion___motion_carry_probe
---

# Cinematic product promo

Use this skill for a product launch film, cinematic app promo or product trailer with
deliberate reveals and beat-synced cuts. A plain dashboard walkthrough stays on
[product demo](../product-demo-video/SKILL.md). Generic titles and lower thirds stay on
[motion graphics](../motion-graphics/SKILL.md). An explicitly requested alternate renderer
stays on [HyperFrames](../hyperframes/SKILL.md). Art grammar, knowledge explainers and
ad variants retain their own skills. A cinematic product brief does not request generative
text-to-video or a change of provider, frame rate or resolution.

## Select recipes and preserve named cards

Read `read_studio_context.intent_route`, the brief and current asset ledger. Search Gateway
for `ShotRecipes___shot_recipe_search` and use its discovered schema through
`call_editor_tool`. It searches 157 local recipe cards deterministically without network,
keys, model calls or spending approval. Supply a short `query`, optional `category`,
`max_duration_s`, `energy`, and `limit` up to 20. An exact `card_id` takes precedence over
the query and returns recipe details. Unknown IDs return an error and nearest IDs. Never
treat a filename or path as an ID.

A user-named card wins over an agent suggestion. Resolve its exact ID or clear English
alias, request that card's full recipe, and assign it to the requested beat. For example,
"ink press" selects `brand-ink-open` for a product reveal. Save
`named_cards: {reveal: brand-ink-open}` in the storyboard and `selection: user_named`
on that beat. Do not
replace it with a higher-ranked search result. If timing or rendering cannot realize it,
disclose the specific limit and retain the requested card in the plan.

Tool results contain neutral English summaries and recipe data. Use those summaries in
storyboards and labels. Third-party names inside imported cards and their provenance
are reference context only. Never repeat them in customer labels, descriptions or copy.
Component hints describe an idea; they do not install an executable component. The cards'
reference implementation paths are provenance text and do not resolve in this repository.

## Plan the film

1. Save the audience, product promise, feature list, exact approved copy, target duration,
   aspect and supplied assets. Build a beat sheet around a hook, product reveal, distinct
   feature demonstrations and a closing call to action. Each beat carries one idea and
   one primary card. A restrained opening can build through alternating action and quiet
   reading holds into the closing reveal. Budget those holds before allocating animation.
2. If the user supplies music, use its measured beat grid before choosing cut times. For
   new music, use the existing `mureka_v95` route or a user-supplied track. Read
   [audio bed](../audio-bed/SKILL.md) and keep its approval and spend controls. Measure
   or obtain actual beat times; a guessed BPM is not detected timing. Keep the grid's
   source asset/version in the ledger. Studio has no music-beat acquisition tool in this
   workflow. Without a supplied measured grid, report that missing timing dependency,
   mark beat-sync verification pending and do not claim a passing beat-synced film.
3. Search for suitable cards, then fetch every selected ID and read its recipe data.
   Preserve the card's settling time, continuous camera motion, easing and known pitfalls.
   Avoid using one conspicuous trick for every feature. Put stronger accents at selected
   musical moments and give dense text time to settle. Keep approved copy intact when
   adjusting timing. Show the neutral storyboard for approval before rendering unless
   the existing creative authorization already covers that review.
4. Save a storyboard JSON with `target_duration_s`, `aspect`, declared `fps`, supplied
   `beat_grid_s`, and `beats`. Each beat contains `beat`, valid `card_id`, `start_s`,
   `duration_s`, optional `sfx_cue`, and optional `cut_snap`. A beat's optional `visual`
   uses native timeline fields, with timing derived from the beat. Describe its supported
   `realization` honestly. Keep `audio_stems: {sfx: [], music: [], vo: []}` as separate
   stem/track plans. Never flatten them into a single source asset.
   Use only the cue categories allowed by the discovered schema and validator.
5. Call `ShotRecipes___shot_recipe_search` with `mode: validate_storyboard` and that
   storyboard before the render plan is handed to `remotion_render`. Every beat must
   name an indexed card; total duration must be within +/-5% of the target. Every cut
   must be within one frame of the supplied measured beat grid at the declared fps.
   Keep fractional seconds until conversion to the render frame grid. Repair each
   reported failure and repeat validation after timing, card or sound-plan changes.

## Assemble supported shots and separate sound tracks

Use the validator's `render_plan.render_args` as the native assembly arguments. Missing
visuals permit timing validation but return `render_ready: false`; they block rendering.
Keep `render_plan.audio_stems` and independent `stem_render_args` for separate exports.
Assembly defaults to `remotion_render` through `Remotion___render_timeline`. Read
[motion graphics](../motion-graphics/SKILL.md) and discover its exact schema. Translate
the validated plan into native `title`, `visuals`, `text_overlays`, `audio_tracks`,
`aspect_ratio` and delivery controls. The configured backend must support every requested
feature. Unsupported features refuse before media I/O. Use existing timeline motions and original implementation choices. Never send
JSX, custom components, reference paths or arbitrary keyframes to this tool. A recipe
requiring unsupported 2.5D camera movement, masking or typography needs a user-supplied
pre-rendered shot or a future renderer integration. Report that limit before submission.
Do not claim that card selection proves the animation was rendered.

For a live web app, `cutaway_record` remains provider pending. It has no Gateway endpoint.
Report that capture dependency or use actual user-supplied footage. Do not fabricate
screenshots, browser recordings or a capture tool. Keep its routing tests pending.

Voiceover uses the existing `eleven_v4_turbo` route with the approved script and voice.
Music uses `mureka_v95` or a user track. Paid steps retain their usual approval and cost
estimates. A recipe search or storyboard approval grants no permission for paid generation
or rendering. Keep all existing autonomous spending and paid-video approval controls.

SFX cues name categories only, such as `transition`, `impact`, `riser`, `ui`, `text` and
`data`. Actual SFX audio must come from a user-supplied asset library with usable rights.
Otherwise leave an empty SFX stem and disclose that no SFX asset was supplied. SFX assets
need Mixkit terms review before use. Do not bundle, copy, download or reference upstream
audio files or preview media. Separate SFX, music and VO stem plans remain present even
when a stem is empty. Use distinct native audio tracks for available assets. Preserve
their asset/version handles and independent render/stem plans for handoff. Do not claim
the renderer exported separate stem files until those actual files have been verified.

Align selected SFX attacks to the same verified cut grid. Place accents sparingly and
leave narration intelligible. After moving a beat or replacing audio, revalidate cue timing
and listen to the full output. Silence in an empty stem is an explicit production choice.

## Verify and deliver

Submit once through the existing approval flow, save the render ID and poll
`Remotion___get_render_progress`. Open and play the saved MP4 with sound. Inspect the
opening, each reveal, settled copy, both sides of cuts and the closing hold. Check that
the named card's action survived adaptation and that every approved feature appears.
Inspect actual SFX/music/VO stem files if the delivery requests them; a plan with distinct
tracks alone does not satisfy an exported-stem requirement.

Measure final loudness through [loudness QC](../remotion-loudness-qc/SKILL.md) and the
existing `ffmpeg_tool` operations. Require integrated -14 LUFS +/-1 for this film.
Use existing loudness and true-peak checks, then remeasure the final encoded artifact.
Compare rendered cut times with detected output-audio beats within one frame. If those
measurements are unavailable, report the unresolved check. Dry-run output is not a film.

Read [delivery render](../remotion-delivery-render/SKILL.md),
[deliverable QC](../remotion-deliverable-qc/SKILL.md) and
[motion carry QC](../motion-carry-qc/SKILL.md). Run the existing checks on the completed
owned local output. Call an artifact finished or delivered only when its saved QC report
passed and still matches every output checksum. Include each reported failure verbatim
otherwise. Keep framing, captions, legal copy and prices pending visual review until
inspected. A queued render, passed technical check or cost approval is not visual acceptance.

Report the delivered width, height, `source_resolution` and resolution warnings from the
successful render. A 1280x720 artifact is 720p. A larger canvas made from it must say
"upscaled from 1280x720; no added detail". Follow the existing
[upscale skill](../upscale/SKILL.md) for actual enhancement under existing approval.
Do not guess unknown source dimensions. Record explicit customer acceptance/rejection
with the saved call ID and `record_media_outcome`.

## Provenance and limits

The imported Chinese card text is unmodified Apache-2.0 data from
[video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft/tree/5ddbf52).
The English index and this workflow are separate Renderhaus-authored metadata and prose.
The imported licence, NOTICE and attribution preserve the origin. Attribution says source
works were not licensed to the upstream authors; recipe text grants no rights to those
works, brand assets, audio or preview media. No upstream code, TSX, textures, demos,
gallery media or editor export is installed. Renderer terms remain those of the existing
tools. Cards and validation do not grant training rights to customer source media.
