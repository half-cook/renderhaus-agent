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
| Kurzgesagt | Flat deep-color world with a few accents; object metaphors explain scale and causality. Introduce one object, change its state on a sentence, then hold. | Upstream examples use roughly 4.6–6.7-second units. Fit the actual concept and recording. | Avoid an aimlessly glowing ball or decorative zoom unrelated to the claim. Use original illustrations. |
| Vox | Real documents, recordings or screenshots on paper, black type and one red accent. Assemble evidence, highlight the exact line, move camera only to reveal context. | Cards often need 3–7 seconds; paper movement can be stepped at 12 fps while camera motion stays smooth. | Do not fabricate news evidence. Put text fully in frame before highlighting and allow reading time. |
| Whiteboard | One connected board, black plus an orange accent. Draw the argument in order, retain earlier objects, end with an overview. | A stroke can begin around half a second after its phrase; tune to the narration. | A marker must lead the stroke. Empty-board cuts break the argument; a pan over a finished diagram is not drawing. |
| Storytime | Original character reactions and a few comic props. Snap to an expressive pose, hold the joke, then act on the next beat. | A pose snap may take about 0.1 seconds and a comic beat about 0.9 seconds. | No endless breathing loop or ghosting morph dissolve. Stable anchors and purposeful pose changes. |
| Kinetic type | One dominant word or phrase; size contrast at least about 3:1. Reveal the stressed word at the spoken stress. | Entrances about 0.3–0.4 seconds, exits about 0.18 seconds, with a readable hold. | Avoid crowded slides and many simultaneous focal words. Plain captions do not implement kinetic typography. |
| 3Blue1Brown / 3b1b | One mathematical object evolves continuously with stable semantic colors. Equations and transformations carry the explanation. | Transform over roughly 1–3 seconds, then hold around a second to inspect. | Do not invent formulas or sever object identity with unrelated cuts. Verify the mathematical relationship. |
| Keynote | One product, screenshot or information claim at a time. Restrained spring movement reveals hierarchy and then settles. | Explanatory screens often need 5–8 seconds. | Show the real product UI or clearly label a concept. Avoid ornamental glass and attractive fake evidence. |
| Finance chart | Establish axes and units, reveal sourced values, then add one annotation. Values settle when spoken. | A chart beat can span roughly 2.5–6 seconds; give labels enough time to read. | Preserve honest scales, units, dates and sources. Distinguish percent from percentage points; never reset data to zero for a transition. |
| Illustrated presenter | Original full-body and bust frames; vary layouts between side explanation, number, comparison, entering a chart and reaction. | Specify scene start, x position and scale. Stop any mouth movement during narration rests; use pose cuts with slight settling. | No automatic avatar or lip-sync inference. Avoid repetitive podium layouts, drifting anchors and ghosting crossfades. |

For a script, save each concept's audio interval, visual object, action, emphasized word and hold.
Choose one grammar per section. A named style supplies structure; it does not supply factual
content, brand assets, permission to use a person's likeness or a renderer template.

For a silent explainer with no named grammar, use
[knowledge-explainer](../../knowledge-explainer/SKILL.md). A plain requested narrated whiteboard
uses [whiteboard-explainer](../../whiteboard-explainer/SKILL.md). For this skill's supporting assets,
schema limits and final QC, follow [art-style-motion](../SKILL.md).

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
