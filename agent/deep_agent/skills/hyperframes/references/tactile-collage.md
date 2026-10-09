<!--
Adapted from audrey-560/hyperframes-tactile-collage at
ef6a49f5a250e6b3b1a0839cafc7a2d43872e619, SKILL.md, references/*.md,
and assets/components/tactile-caption.html.
Copyright (c) 2026 Audrey. MIT License.
The complete copyright and permission notice is retained in
third_party/hyperframes-tactile-collage/LICENSE.
Modified by Renderhaus on 2026-10-09. Font installation, upstream runtime
workflows, inert top-level templates, and generated caption DOM are not carried over.
-->

# Plan tactile paper collage

Use this recipe within an explicit HyperFrames workflow. Unnamed collage animation
requests use `motion-graphics` and `remotion_render`. Preserve the story, timing,
approved copy, source footage, narration, and brand. The style does not authorize
new assets, a recut, transcription, matting, or audio generation.

## Choose one physical metaphor per beat

1. Write the beat's one sentence and identify the concrete noun or action.
2. Choose a paper object whose role explains that action.
3. Reserve the complete caption lane before placing the object.
4. Plan the strongest paused frame before motion.
5. Add one hero move and one supporting move. Keep the background quiet.
6. Preserve the same object when the next beat continues its meaning.

Use a taped note for a new concept, a dotted route for dependency, a file tag for
handoff, or a stamp for a verdict. Avoid unrelated stickers or a dense scrapbook
grid. Carry paper size, edge weight, shadow direction, and concept colors across
the sequence. Keep rotations small and purposeful, usually within five degrees.

Use warm paper, a lighter sheet, near-black ink, and no more than three semantic
accents per frame. Respect approved brand colors while preserving contrast roles.
Favor short editorial statements and operational labels. At a 1080 px short edge,
start with 54 px headlines, 28 px labels, and captions no smaller than 42 px.
The upstream font files and installers are excluded. Select only authorized
host-local faces and weights when the future worker is provisioned.

## Select the first usable layout

| Mode | Preconditions and placement |
| --- | --- |
| Behind subject | A future worker has supplied source footage and a clean, frame-locked matte. Put paper objects below the subject and captions above it. |
| Direct overlay | A future worker has intact supplied footage. Keep bounded paper objects in negative space that stays clear throughout the beat. |
| Full frame | No useful footage or matte exists, or the explanatory object needs the canvas. Keep one hero object and one supporting label or path. |

Never simulate a photographic subject or matte. A matte must match source timing,
frame rate, duration, dimensions, crop, and scale. Inspect moving hair, hands, and
shoulders at the beginning, midpoint, and end. Reject doubled edges or color shifts.
If no safe overlay region survives subject movement, use a full-frame beat instead
of chasing the subject with graphics.

Protect the face and mouth first, then gestures, held objects, source UI, logos,
captions, explanatory objects, and decorative texture. Move or remove lower-priority
elements first. Critical areas and caption lanes use output pixels.

| Format | Critical area | Caption lane | Maximum width |
| --- | --- | --- | --- |
| 1080 by 1920 | x=90 to 990, y=240 to 1520 | y=1190 to 1340 | 840 |
| 1920 by 1080 | x=96 to 1824, y=54 to 972 | y=810 to 955 | 1640 |
| 1080 by 1080 | x=72 to 1008, y=72 to 1008 | y=750 to 910 | 900 |

Scale these coordinates for other resolutions and apply stricter platform margins.
Include overshoot and shadows when planning the complete caption lane.

## Adapt the packaged sample

Read [the catalog](../templates/catalog.json) and
[the collage sample](../templates/tactile-collage.html). Invented sample copy describes
a thought becoming a shared idea. A taped note remains visible while a route draws
and a stamp lands. Three compact caption cues share the same reserved lane.
There is no source footage, face, matte, narration, or claim of verified media.

| Beat | Start | End | Physical cause and caption |
| --- | --- | --- | --- |
| Note placement | 0.4 | 2.7 | The note settles while the caption reads “Start with a thought”. |
| Direction | 2.8 | 5.0 | A short ink route draws while the caption reads “Give it a direction”. |
| Share | 5.2 | 7.8 | A restrained stamp lands while the caption reads “Make room to share”. |

The root is mounted directly in the body, replacing the upstream inert `<template>`.
Stable markup replaces dynamic word-group construction. Timed outer `clip` elements
own visibility and bounds. Inner wrappers receive opacity and transform tweens.
The SVG path receives a deterministic stroke tween. One paused host-provided GSAP
timeline registers at `window.__timelines["tactile-collage"]`.
No scripts, fonts, media, or weights are downloaded.

Pass the catalog's argument envelope and actual HTML contents to the existing
editor preview. Keep the root and envelope dimensions, duration, and frame rate
consistent after edits. For actual speech, replace sample timings with corrected
word timings, group by meaning or pause, and keep one or two lines visible at once.
Highlight at most one meaningful word per cue. Shorten a colliding phrase or move
its lane before reducing the caption below the size floor.

Preserve narration and mix any separately authorized local effects below it.
Use sparse paper placement, stamp, route, or handoff accents only when the action
justifies them. Silence remains a valid choice. The preview cannot mix audio.

## Record verification limits

Save each beat's timing, physical metaphor, layout mode, protected regions,
caption lane, source assets, and animated selectors in the project storyboard.
The sample's start times are illustrative and are not a measured transcript.

| Check | Current status |
| --- | --- |
| Bounded argument envelope | Available through the existing dry-run preview. |
| Mounted root, stable IDs, clip bounds, and registration | Checked offline by contract tests with a GSAP test double. |
| Real GSAP direct seeks, visual hierarchy, phone legibility, and collisions | PENDING. The host runtime and isolated renderer are unavailable. |
| Opening, transitions, densest frame, final frame, and contact sheet | PENDING. No browser snapshots are produced by preview. |
| Render, source preservation, audio mix, and artifact playback | PENDING. The tool creates no media artifact. |

Future visual review must inspect the beginning, midpoint, and end of every beat,
including overshoot and moving subjects. Re-test after edits and open the actual
artifact before recording a complete export.
