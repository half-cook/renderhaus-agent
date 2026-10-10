# Frame, motion and world design

Adapted and translated from alchaincyf (花叔 · 花生),
[huashu-art-motion d861767d180008d27675819932070a670a3ae43f](https://github.com/alchaincyf/huashu-art-motion/tree/d861767d180008d27675819932070a670a3ae43f),
read 2026-10-10. Sources include the upstream SKILL, first-frame, character-frame, art-medium,
long-scroll and animation-grammar references. Preserve the MIT notice below and
[licence](https://github.com/alchaincyf/huashu-art-motion/blob/d861767d180008d27675819932070a670a3ae43f/LICENSE). This is a planning method;
it does not add a procedural renderer to Renderhaus.

## A frame that can move

Start from the subject and the chosen medium. Define the focal silhouette, negative space,
three to five recognizable motifs and regional palettes. A Monet bridge needs its own contrast
against water; a Van Gogh floor should not inherit the sky's blue flow field. Do not add an
artist's name to a generic room and expect the style to read.

Give each motif a job: direct attention, reveal information, express material or support the
actor. Choose a principal action and a few secondary actions. Brushwork follows region-specific
directions; water changes a reflection; gold changes its specular highlight. Motion should belong
to the medium. Avoid a full-screen filter that boils every surface or continuous camera motion
that hides a static scene. For narrated graphics, change state on a phrase and rest afterward.

Plan layers separately: background, fixed texture, moving motif, character, foreground occlusion,
text and audio. Preserve textures between frames. For authored motion, derive state from frame/time
and fixed seeds so seeking and repeated renders agree. Cache static texture rather than rerandomizing
the canvas. These are requirements for the supplied authored asset, not Gateway arguments.

## Characters belong to the scene

Use an original supplied or generated character. Specify recurring identity details and separately
describe each required pose. Align feet, eyes, body scale and costume before compositing. Match
the scene through a medium treatment appropriate to the character layer; distressed plaster may
belong only on the background. Recheck occlusion at hands, props, sleeves and limb joints.

A small hard pose cut can express a reaction better than a ghosting crossfade. Do not move the
anchor when changing poses. For walking, preserve a coherent gait and ground contact. An image
frame is not a rig, animated character or lip-synced performance. Missing acting assets remain
an explicit production dependency.

## A long scroll is one continuous walk

Lay out one world per segment with a shared ground line and consistent actor scale. Move the
camera forward without restarting at each cut. Keep gait on global time; start interactions
relative to the world event so the actor does not reach before arriving. Change the world's
style at the boundary, using its material signature: mosaic tiles, ink diffusion, a paper cut
or a gold spiral. Keep the actor legible during the switch. Review the exact boundary frames.

Do not pretend independent still pans create continuous world scrolling. The existing tool needs
an authored video containing that behavior. Describe the desired worlds and blocked motion in
the shot list when such a clip is absent.

## Narration drives grammar

Break the script into concepts and mark phrase start, emphasized word, visual change and reading
hold. Prefer one state change per concept to a stream of decorative effects. Keep the meaningful
object continuous across transformations. Finish with enough time to read the final relationship.
Use the selected [grammar card](grammar-cards.md), not a universal transition preset.

Reuse a provided recording. If narration is requested, prepare it before fixing shot lengths.
Generate event SFX only for identified actions and position them on those actions. Silent briefs
stay silent. Music is a separate request. Exact transcript timings must come from the actual
recording; do not label guessed timings as measured.

## The storyboard and the render request

For each scene, save: duration, subject, card, regional palette, materials, layers, motion events,
character anchors, narration interval, SFX offset, asset source/rights and renderer support status.
Write desired procedural behavior in the plan. Translate only supported fields into the discovered
render schema. Never submit these planning fields as fabricated API parameters.

Review a representative still before committing to a full animation. Continue within existing
action/spending authorization; ask only for a missing creative decision or required approval.
Review first/middle/last and boundary frames, then play the saved artifact. A plan, mock, dry-run
or accepted job has no delivered-video status. Return the shot list and any blocked requirements
with the preview. Final delivery also follows [the parent skill's QC workflow](../SKILL.md).

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
