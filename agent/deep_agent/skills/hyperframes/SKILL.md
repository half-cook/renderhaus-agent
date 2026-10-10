---
name: hyperframes
description: Author HTML motion compositions and preview inputs for explicitly named HyperFrames requests. Includes cinematic captions, tactile collage, and Hyfrme templates. Remotion remains the default renderer.
license: Apache-2.0
metadata:
  include_tools: call_editor_tool call_audio_tool
  gateway_tools: HyperFrames___render_composition ElevenLabs___text_to_speech_convert
  routing_tools: hyperframes_render
---

# HyperFrames

Adapted from [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes/tree/3aa68869f7d4cec8b37cdfcb9cd539389b63abed),
copyright 2026 HeyGen, Inc., licensed under Apache-2.0.
Modified by Renderhaus on 2026-10-08. This file consolidates selected guidance from
the upstream hyperframes, hyperframes-core, hyperframes-animation, hyperframes-creative,
hyperframes-cli, faceless-explainer, product-launch-video, embedded-captions, and
motion-graphics SKILL.md files. It replaces upstream shell, hosted API, installation,
publishing, and script-dispatch steps with the Renderhaus tool contract.
The distribution retains the complete LICENSE and the Renderhaus attribution NOTICE.

The cinematic-caption and tactile-collage recipes and templates adapt
[audrey-560/hyperframes-cinematic-caption](https://github.com/audrey-560/hyperframes-cinematic-caption/tree/6cdb01d74949cab379e048e9092709adbb3b203b)
and [audrey-560/hyperframes-tactile-collage](https://github.com/audrey-560/hyperframes-tactile-collage/tree/ef6a49f5a250e6b3b1a0839cafc7a2d43872e619).
Both are copyright 2026 Audrey, licensed under MIT, and modified by Renderhaus
on 2026-10-09. Their complete copyright and permission notices remain in
`third_party/hyperframes-cinematic-caption/LICENSE` and
`third_party/hyperframes-tactile-collage/LICENSE`. Those adapted resources retain
MIT licensing; this existing owning skill retains its Apache-2.0 attribution.

The [Hyfrme recipe](references/hyfrme.md) and three examples adapt selected
[AksharP5/hyfrme](https://github.com/AksharP5/hyfrme/tree/26522a993082cd30ad5f404e4890d670c5c73bcb)
patterns, copyright 2026 Akshar Patel, under MIT. Text and transition patterns
also retain Remocn's MIT attribution. Renderhaus modified these resources on
2026-10-09. Complete notices remain in `third_party/hyfrme/LICENSE` and
`third_party/hyfrme/Remocn-LICENSE`. The adapted resources use MIT.

## Select the workflow

Read `read_studio_context` and follow its `intent_route`. Use this skill when the
customer explicitly requests HyperFrames. Remotion remains the default for unnamed
motion graphics and existing Remotion brand kits. An enabled feature flag makes the
optional tool available; it does not change the default renderer.
If the route is blocked or the tool is absent, report the blocker. Do not silently
replace the customer's renderer, invent a Gateway target, or change environment flags.

This integration validates a composition input and returns dry-run metadata only.
It does not execute HTML, lint HyperFrames semantics, render proof frames, or create
a video. Live rendering is blocked until the host provisions an isolated renderer.
Caption compositing, managed-media embedding, and audio mixing need that future worker.

Choose a pattern from the supplied brief:

| Pattern | Planning guidance |
| --- | --- |
| Faceless explainer | Turn supplied notes, an article, or a changelog into a teaching sequence. Use typography, diagrams, and supplied data. Keep claims traceable to the source. No website capture or invented product screenshots. |
| Product launch | Preserve supplied brand colors, fonts, screenshots, and approved copy. Plan a hook, the product benefit, evidence, and a final call to action. A supplied screenshot is the source of truth for a site tour. Report missing source material. |
| Captions overlay | Use supplied transcript and measured word timings. Preserve the source footage. Default to a readable caption rail, with emphasis on a few words. Keep text inside safe areas and away from faces. Transcription, subject matting, and text behind a subject are unavailable. |
| Cinematic captions | Read [the cinematic recipe](references/cinematic-caption.md) before planning ordered support, hero, and CTA cues. Use supplied speech timings. Depth requires a future worker and a supplied clean, frame-locked matte. |
| Tactile paper collage | Read [the collage recipe](references/tactile-collage.md) before choosing a physical metaphor, full-frame or overlay mode, and a stable caption lane. Source footage and matte handling require the future worker. |
| Kinetic titles | Plan a short, unnarrated title, lower third, logo reveal, or numeric callout. Use the approved brand kit and supplied logo or data. Hold text long enough to read and leave a clear final frame. |
| Hyfrme component pack | Read [the Hyfrme recipe](references/hyfrme.md) for text reveals, shared-axis scene transitions, or a device card with raised UI rows. Choose one of the three catalog samples. The device card is illustrative UI, not website capture. |

For a pack, read [the template catalog](templates/catalog.json), then its
listed HTML file through the skill filesystem. Copy the entry's `arguments` and
add `html` containing the actual file contents. Templates are asset-free,
full-frame samples with invented copy and illustrative timings. They require
host-provided GSAP and create no source footage, subject matte, or proof frames.
Keep the envelope consistent with the root after changes. The catalog adds no
tool or top-level skill. Unnamed caption and collage animation requests stay on
Remotion even when HyperFrames is enabled.
The Hyfrme pack name alone also keeps the default renderer. Only an explicit
HyperFrames name opts into this skill. Requests to record a UI demo retain the
existing capture workflow and its pending dependency. The pack does not implement
capture, install the upstream catalog, or supply shader, font, or media runtimes.

## Plan and author

1. Preserve the brief, source text, approved asset versions, aspect ratio, and duration
   in project files. Use `write_todos` for a multi-scene task. Delegate focused planning
   or editing with a complete brief and saved file paths when useful.
2. Choose one palette and typography system. Give each scene one clear visual purpose.
   Record scene start, duration, copy, source, and intended motion in the storyboard.
3. Author a standalone HTML composition with its root directly in the body.
   Set `data-composition-id`, `data-width`, `data-height`, and a finite `data-duration`.
   Size the root with `width: 100%` and `height: 100%`. A top-level template hides the root.
4. Give timed layers stable IDs, `class="clip"`, `data-start`, and `data-duration`.
   Keep every layer inside the root's time window. For GSAP, register exactly one
   paused timeline at `window.__timelines["<composition-id>"]` after building it.
   The registry key must match the root composition ID.
5. Make animation seekable at any frame. Avoid render-time clocks, unseeded randomness,
   network-dependent state, and infinite repeats. Precompute layout before tweens.
   Use transform aliases for spatial motion. Avoid competing CSS transforms and GSAP
   transforms on one node. Animate a child for opacity or visibility transitions;
   the framework owns a clip's visibility.
6. Use only host-provided local dependencies in a future render project. Do not fetch
   fonts, scripts, browser binaries, catalog assets, or weights. The current preview
   tool does not resolve asset handles or supply GSAP. Missing dependencies remain
   explicit provisioning requirements, rather than proof of a renderable project.

If requested, discover `ElevenLabs___text_to_speech_convert` and use `call_audio_tool`
with the exact schema, authorized voice ID, and approved text. Preserve its result.
Speech generation follows the existing approval and spending gates. It does not make
the HyperFrames export complete. Do not call HeyGen TTS, avatars, music, or hosted renders.
If separately authorized assets are needed, use the `image-gen` skill and its
current discovered schemas. Asset generation does not complete a HyperFrames export.

## Preview through the editor

Discover `HyperFrames___render_composition` in `read_studio_context` and inspect its schema.
Use `call_editor_tool` with the exact discovered name and an arguments object containing
the composition HTML and the required output dimensions, duration, and frame rate.
Keep those values consistent with the HTML root. Do not supply shell commands or host paths.
The host gates discovery with `HYPERFRAMES_ENABLED`, which defaults off, and defaults
`HYPERFRAMES_DRY_RUN` to true. A non-autonomous call still pauses for approval.
The host reports compute cost as unknown. An autonomous spend cap can block that quote.

Return a dry-run result as an input preview with an incomplete export. A `not_run`
result is a blocker. Neither result is generated media or customer visual acceptance.
Never invent an MP4 URL, render ID, successful playback, or a cost of zero.

A future isolated worker must run HyperFrames checks, inspect proof frames and the
visible composition, render once, verify duration, and open/play the actual artifact.
Preserve any saved job ID during recovery. Re-check after edits. Until those steps
are implemented and observed, report rendering and visual verification as pending.
