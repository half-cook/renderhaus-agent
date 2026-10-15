# Animation grammar cards

Adapted and translated from alchaincyf (花叔 · 花生),
[huashu-art-motion d861767d180008d27675819932070a670a3ae43f](https://github.com/alchaincyf/huashu-art-motion/tree/d861767d180008d27675819932070a670a3ae43f/references),
read 2026-10-10. Sources: the upstream video-animation-grammar reference, eight grammar cards
and illustrated-presenter reference. Preserve the MIT notice below and
[licence](https://github.com/alchaincyf/huashu-art-motion/blob/d861767d180008d27675819932070a670a3ae43f/LICENSE).

The timings below are upstream design examples, not measured timings for the user's recording
or built-in tool capabilities. Align beats to actual audio and readable holds. Procedural
transforms, animated charts, marker paths, per-word kinetic type and character performances
require authored motion assets under the current render contract.

| Grammar | Frame and beat | Timing guidance | Review risk |
|---|---|---|---|
| Flat Concept Worlds | Flat deep-color world with a few accents; object metaphors explain scale and causality. Introduce one object, change its state on a sentence, then hold. | Upstream examples use roughly 4.6–6.7-second units. Fit the actual concept and recording. | Avoid an aimlessly glowing ball or decorative zoom unrelated to the claim. Use original illustrations. |
| Document Evidence | Layered paper collage, dark ink and a restrained accent. Reveal sourced documents for evidence, or stage an original cutout metaphor for the concept. Use flat fills, grain, rough edges, stacked shade pieces and consistent soft shadows. | Fit each beat to the recording or silent reading hold. Keep camera motion smooth; subtle label boil can hold two frames at 30 fps. Hard-cut when the takeaway changes. | Never fabricate evidence or pass a paper UI mockup off as a real screenshot. Keep text clear of focal props. Torn word tags, articulated cutouts and parallax require authored motion assets. |
| Whiteboard | One connected board, black plus an orange accent. Draw the argument in order, retain earlier objects, end with an overview. | A stroke can begin around half a second after its phrase; tune to the narration. | A marker must lead the stroke. Empty-board cuts break the argument; a pan over a finished diagram is not drawing. |
| Storytime | Original character reactions and a few comic props. Snap to an expressive pose, hold the joke, then act on the next beat. | A pose snap may take about 0.1 seconds and a comic beat about 0.9 seconds. | No endless breathing loop or ghosting morph dissolve. Stable anchors and purposeful pose changes. |
| Kinetic type | One dominant word or phrase; size contrast at least about 3:1. Reveal the stressed word at the spoken stress. | Entrances about 0.3–0.4 seconds, exits about 0.18 seconds, with a readable hold. | Avoid crowded slides and many simultaneous focal words. Plain captions do not implement kinetic typography. |
| Continuous Mathematical Objects | One mathematical object evolves continuously with stable semantic colors. Equations and transformations carry the explanation. | Transform over roughly 1–3 seconds, then hold around a second to inspect. | Do not invent formulas or sever object identity with unrelated cuts. Verify the mathematical relationship. |
| Product Presentation | One product, screenshot or information claim at a time. Restrained spring movement reveals hierarchy and then settles. | Explanatory screens often need 5–8 seconds. | Show the real product UI or clearly label a concept. Avoid ornamental glass and attractive fake evidence. |
| Finance chart | Establish axes and units, reveal sourced values, then add one annotation. Values settle when spoken. | A chart beat can span roughly 2.5–6 seconds; give labels enough time to read. | Preserve honest scales, units, dates and sources. Distinguish percent from percentage points; never reset data to zero for a transition. |
| Illustrated presenter | Original full-body and bust frames; vary layouts between side explanation, number, comparison, entering a chart and reaction. | Specify scene start, x position and scale. Stop any mouth movement during narration rests; use pose cuts with slight settling. | No automatic avatar or lip-sync inference. Avoid repetitive podium layouts, drifting anchors and ghosting crossfades. |

For a script, save each concept's audio interval, visual object, action, emphasized word and hold.
Choose one grammar per section. A named style supplies structure; it does not supply factual
content, brand assets, permission to use a person's likeness or a renderer template.

For a silent explainer with no named grammar, use
[knowledge-explainer](../../knowledge-explainer/SKILL.md). A plain requested narrated whiteboard
uses [whiteboard-explainer](../../whiteboard-explainer/SKILL.md). For this skill's supporting assets,
schema limits and final QC, follow [art-style-motion](../SKILL.md).

## Cut-paper explainer

This variant extends Document Evidence with a miniature paper world. Use real, rights-cleared
documents when proving a claim. Use original paper props for a visual analogy, and label
reconstructed UI as an illustration. A metaphor must not become invented product evidence.

The material, motion and authoring recipes below are adapted in our own words from sanat's
[papercut-explainer at 5a342bf855160379b4684e1c49f2e3faaecd5d0b](https://github.com/0xS4N4TG/papercut-explainer/tree/5a342bf855160379b4684e1c49f2e3faaecd5d0b),
read 2026-10-15. Sources are `style-guide.md`, `motion-principles.md` and `remotion-recipes.md`
in `skills/papercut-explainer/references`. The MIT notice for this adaptation follows below.
No upstream components, installer, voice pipeline, fonts, textures, audio or demo media ship here.

### Design the paper world

- Build a readable front or side silhouette from a few rigid shapes. Give each object a flat
  fill, fine grain, a slightly uneven edge and a soft contact shadow. Use separate darker
  underside pieces and lighter edge pieces for shading. Avoid gradient-filled plastic objects.
- Keep the same light direction across scenes, for example upper left with shadows down right.
  Separate background, far props, subject and foreground by overlap and value. Keep backgrounds
  dusty or desaturated; reserve stronger color for the subject, the takeaway and meaningful states.
- Put a short takeaway in a taped strip with heavy sans type. If speech captions were requested,
  use a softer bold serif on torn tags. The takeaway adds information rather than transcribing
  the voiceover. Use licensed fonts and original or authorized textures.
- Design around the requested aspect ratio and measured assets. For a requested vertical short,
  reserve a stable upper banner, a central stage and a caption band below the focal action.
  Leave space for platform controls at the bottom. Check the actual crop and longest text.
  Upstream 1080x1920 at 30 fps is a reference layout, not a forced export size or native-detail claim.

### Plan beats before animation

Save each beat's source claim, takeaway, prop, action, audio interval or silent hold, camera
purpose, cut and required authored asset in the shot list. Make the hook's promise visible,
show the mechanism changing a state, and close with the resulting answer. Use either one
coherent metaphor world or a fresh set when the takeaway changes. Do not add a sales CTA by default.

Reuse supplied narration. If new narration is requested, prepare it through the existing audio
skill before locking cues. Silent work uses reading and action holds without TTS or invented
word timestamps. Music and foley remain opt-in under the parent skill's audio policy.

For an authored animation, use these as starting points at 30 fps, then retime to the actual
recording and legibility. These are design examples, not measured Renderhaus performance.

- Keep world and camera movement continuous. Apply a small deterministic two-frame hold only
  to banner or label offsets, roughly 1-2 px at a 1080-pixel width. Do not shake the entire world.
- Use rigid translations, hinges and rotations for cutouts. A prop entrance can settle over
  6-9 frames with slight scale overshoot. A slide can take 8-12 frames. Add a short anticipation
  before the main action and let a hanging sign or accessory settle after the body stops.
- Let a stressed word cue one meaningful change, then allow comprehension. A signal may swap
  state immediately; an object transfer follows an arc. Keep ambient movement quieter than
  the main action and remove loops that distract from a reading hold.
- For requested word captions, show small phrase groups of one to three words with each tag
  arriving at its measured word onset. A 3-5-frame pop is a starting point. Seed each tag's
  small tilt so repeated renders agree. Clear the prior group before showing the next.
- Hard-cut at a new takeaway after a readable hold. Use a continuous pan only when it reveals
  a spatial or causal relationship. Reserve a tear, page turn or whip for a justified authored
  transition, rather than applying one to every scene.

### Authoring and review boundary

The existing timeline tool composes finished assets and supported motion presets. It cannot
run the upstream JSX recipes, custom paper filters, layered camera rigs, cutout acting,
stepped label boil or word-pop tags. For these effects, use a rights-cleared authored clip.
If that clip is missing, record the missing effect and return an incomplete storyboard or
preview. A still with a pan is not the completed paper animation. HyperFrames retains its
explicit-request gate and dry-run limitation.

If a separate authorized Remotion authoring task supplies those clips, derive animation from
the current frame and fps, use seeded randomness and measured audio cues, and keep persistent
captions and banners on the intended global timeline. CSS animation and wall-clock timers
cannot define repeatable render frames. Bake static material layers when practical instead
of filtering every prop on every frame. These are authoring directions, not Gateway arguments.

Inspect the opening, main action and final state at the requested crop. Check shadow direction,
layer seams, banner fit, caption timing, safe areas and readable holds. Watch the actual clip
and final artifact for distracting jitter or competing focal actions. Follow the parent skill's
saved final-QC, checksum and resolution reporting requirements before a delivery claim.

<!--
MIT License

Copyright (c) 2026 sanat

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
