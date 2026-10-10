---
name: art-style-motion
description: Plan animated art shorts, named explainer grammars such as Kurzgesagt, Vox or 3b1b, and characters walking through painting worlds. Compose supplied or authored motion with Remotion by default; generic silent explainers use knowledge-explainer.
metadata:
  remotion_backend: configured
  remotion_features: clip_timing transitions fit_position scale motion titles captions audio_mix canvas encoding
  include_tools: call_editor_tool call_media_tool call_audio_tool
  routing_tools: remotion_render hyperframes_render gpt_image25_t2i eleven_v4_turbo elevenlabs_sfx_v2
  gateway_tools: Remotion___render_timeline Remotion___get_render_progress HyperFrames___render_composition OpenAI___generate_image ElevenLabs___text_to_speech_convert ElevenLabs___text_to_sound_effects_convert
---

# Art style motion

Method and cards adapted from alchaincyf (花叔 · 花生),
[huashu-art-motion at d861767d180008d27675819932070a670a3ae43f](https://github.com/alchaincyf/huashu-art-motion/tree/d861767d180008d27675819932070a670a3ae43f),
read 2026-10-10. Preserve the MIT notice below and
[upstream licence](https://github.com/alchaincyf/huashu-art-motion/blob/d861767d180008d27675819932070a670a3ae43f/LICENSE) with adapted text.
The upstream renderer, character artwork, demo media, fonts and stroke data are not included.

Use this skill when the user names an art style and asks for motion, names an explainer grammar,
or asks for a character to walk through painting worlds. Read [method](references/method.md),
then the relevant [style card](references/style-cards.md) or [grammar card](references/grammar-cards.md).
For an additional style such as ukiyo-e, build an original card from the user's references;
do not claim it is one of the upstream cards. Recreate a reference only within the supplied rights.

For a silent explainer with no named style, read [knowledge-explainer](../knowledge-explainer/SKILL.md).
Plain narrated whiteboard work uses [whiteboard-explainer](../whiteboard-explainer/SKILL.md).
Static art uses [image-gen](../image-gen/SKILL.md), existing-footage restyling uses
[edit-v2v](../edit-v2v/SKILL.md), and photoreal generated footage uses [t2v](../t2v/SKILL.md)
or [i2v](../i2v/SKILL.md). Adding foley to an existing clip uses [audio-bed](../audio-bed/SKILL.md).

## Design one frame

1. Identify the subject, aspect ratio, duration, supplied assets, named style and narration policy.
   Use one chosen direction; avoid generating paid alternatives without authorization.
2. Design one frame with a focal subject, medium-specific palette, texture, lighting and three
   to five scene elements. Treat reference images as composition/material guidance, not demo assets.
3. Assign motion to meaningful elements: a water reflection, brush-flow highlight, gold glint,
   character action or a concept changing state. A painting should live within the frame.
   A grammar-driven explainer should act on the spoken idea and then hold for comprehension.
4. Build a timed shot list. Reuse a supplied recording; otherwise prepare requested narration
   before locking scene durations. Silent means no TTS, speech or inferred presenter dialogue.
5. Write the palette, material rules, scene beats, asset provenance, character anchors and output
   geometry to project files. Keep this design separate from the executable tool arguments.

## Render within the actual contract

Follow `read_studio_context.intent_route`: explicit request, then exception, then default.
Use `remotion_render` through `Remotion___render_timeline` by default. Only a named HyperFrames
request selects `hyperframes_render` through `HyperFrames___render_composition`; generic HTML
does not. Respect its feature flag, availability and current dry-run-only implementation.
An explicit generated-video provider request takes precedence and uses the appropriate existing skill.
Price, tier and `project.confidential` do not choose the renderer or models.

Discover the exact Gateway schema before dispatch. The current Remotion tool accepts supplied
image/video assets, supported simple motion, text/caption overlays, audio tracks and output settings.
It does **not** accept arbitrary JSX, procedural scene code, upstream `draw`/`cast`/`cues`, or a
style/grammar card as executable input. HyperFrames is not a fallback for that limitation.
For brush-flow animation, geometric morphs, marker strokes, sprites or continuous world scrolling,
use a rights-cleared authored clip that already contains the required motion. If none is available,
record the missing animation/template as blocked and report an incomplete storyboard or preview.
Do not call a still-image pan an implementation of those effects.

Generate original character/key frames through `OpenAI___generate_image` (`gpt_image25_t2i`),
with `prompt`, `size`, `quality` and `background` from its schema. Request transparent background
when appropriate. The image model supplies the character; do not claim code drew the person.
Maintain foot/eye anchors, scale, outfit and palette across poses. A flat pose cut may be supported;
character acting or lip sync requires an authored asset or a separately requested performance skill.

Requested new voiceover uses `ElevenLabs___text_to_speech_convert` (`eleven_v4_turbo`): `text`,
an authorized `voice_id` and `model_id=eleven_v4_turbo`. Text-described event effects use
`ElevenLabs___text_to_sound_effects_convert` (`elevenlabs_sfx_v2`): `text`, `duration_seconds`,
`model_id=eleven_text_to_sound_v2` and optional `loop`/`prompt_influence`. Place each asset at its
visual event time. Do not generate music unless requested. For picture-conditioned audio or voice
discovery, read [audio-bed](../audio-bed/SKILL.md) and follow its capability selection.
Respect input rights and required consent for real people or voices; this skill grants no training rights.

Disclose provider/model, selection basis and estimated cost before each paid call. Preserve the
existing approval middleware and autonomous spend cap. All paid video pauses with a cost estimate
even in autonomous runs; unknown estimates stay unknown and require an operator quote before live use.
Never change dry-run flags. Submit once, retain the job ID and poll that job with
`Remotion___get_render_progress`; a dry-run or queued job is not generated media.

## Review and handoff

Inspect actual first/middle/last frames, event timing, character seams, safe areas, contrast and
text reading time. For long scrolls, inspect the world boundaries and gait continuity. Open/play
the actual artifact before claiming a successful render. Spending approval is not visual acceptance;
record customer acceptance/rejection with `record_media_outcome` and the saved call ID.

Use [final-assembly](../final-assembly/SKILL.md) and
[remotion-deliverable-qc](../remotion-deliverable-qc/SKILL.md) for final delivery. A finished claim
requires saved QC passing against every current output checksum. Report failures verbatim and keep
pending visual review explicit. Include the delivered width/height, `source_resolution` and every
resolution warning. A 1920×1080 canvas from 1280×720 is upscaled from 1280×720; no added detail.
Unknown source dimensions stay unknown. Actual enhancement uses [upscale](../upscale/SKILL.md)
with the existing approval flow. Deliver the MP4, shot list, used cards and any limitations;
offer [resolve-handoff](../resolve-handoff/SKILL.md) when an editable handoff is requested.

<!--
MIT License

Copyright (c) 2026 alchaincyf (花叔 · 花生)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
-->

The configured Remotion backend must support every requested feature. Unsupported features refuse before media I/O
or AWS submission. Crop/pad reframing requires local/worker; fitted font/box overlays require
Lambda overlay contract version 2 or local/worker. Use named motion presets; arbitrary render
keyframes, per-word kinetic typography and custom components remain unavailable.
