# Launch motion technique cards

Read only the selected card when planning a cinematic product film. Use the customer's
approved visual direction, copy, data and assets. These are optional techniques, not a
requirement to animate every beat or replace an approved cut-based film.

## Plan and realize a technique

Keep the indexed shot recipe as the storyboard beat's `card_id`. Save technique notes
separately, for example in `launch-motion-plan.json`, keyed by the same beat name.
Record the technique ID, intended state change, event frames, supplied shot handle and
unresolved realization limits. Do not add this file's fields to the strict storyboard
or native render arguments. A technique ID is not searchable through the recipe tool.

The existing `remotion_render` timeline accepts media clips, text and supported motions.
It has no arbitrary shape, spring, cursor, masking or custom-component contract. Each
card below requires a real pre-rendered shot for its full realization today. When that
asset is missing, retain the requested action in the plan and report production pending.
Do not submit JSX, HTML, scripts or invented animation fields. Do not install the source's
browser capture pipeline or select another renderer. An accepted simplified treatment
must be described as a simplification, not a completed morph or spring interaction.

Use the declared fps for all event frames. Keep the existing aspect and source-resolution
policy. The reference's 60 fps, motion blur and soundtrack choices are not defaults here.

## one-shape-morph

Choose this card when one product action naturally becomes the next, such as a search
field expanding into a result card and then a detail panel.

- Keep one visible container through the sequence. Plan its position, size, corner radius
  and fill at each state. Preserve a recognizable edge or anchor while it changes.
- Give the departing text an earlier, shorter exit than the container's movement. Reveal
  the next content after the old content clears. A brief blur can soften the swap in a
  supplied shot, but never hide two competing text layers under the blur.
- Frame the important control and reserve a reading hold after each meaningful state.
  Move the camera only when the next state needs different framing.
- For a requested loop, compare the start and end geometry, content and cursor position.
  Check motion across the seam as well as still-frame similarity.

Realize the sequence as one supplied video clip. Keep internal changes inside that clip,
with native `motion: none`; do not split every state into a new visual and call its cuts
a continuous morph. Without that shot, report the missing asset. A dissolve between
stills does not establish shape continuity.

Inspect the frame before the change, its midpoint, the settled state and both sides of
any loop seam. Reject a disappearing container, a geometry jump, overlapping copy or a
final state that never becomes readable. Loop closure stays pending until the artifact
plays through the boundary without a visible or audible jump.

## spring-settle

Choose this card for a control that needs a clear destination and a small physical
response, such as a selected tab, toggle or expanding product panel.

- Describe the initial value, target value, event frame and required settled frame for
  each moving property. Use a deterministic response evaluated from the frame's time.
  Frame seeking must not depend on timers, CSS transitions or previous rendered frames.
- Prefer critical damping for text and camera framing. Use a restrained underdamped
  response only where a small overshoot communicates the interaction. Avoid repeated
  bouncing on copy and primary controls.
- Schedule the triggering event early enough to settle at the desired beat. Measure the
  settling interval for the chosen response; do not assume every spring takes the same
  fraction of a second. Keep a stable reading hold after it settles.
- A tab or toggle may stretch with different responses on its leading and trailing
  edges. Preserve positive width and stop the stretch at the settled control bounds.
- When a target changes during motion, preserve position and velocity at the event.
  A dragged control starts its release response from the actual release position.

The native timeline's linear zoom and pan do not provide spring physics. Require a
supplied shot with the intended response. Do not add `spring`, damping or stiffness
fields to a visual, or describe a linear zoom as a spring. Code patterns in the source
are reference material and do not install an executable composition here.

Inspect just before and after each event, the maximum overshoot and the reading hold.
For a supplied frame-computed composition, compare a direct seek with sequential playback
at the same frame. Report that determinism check as unavailable for an opaque MP4 rather
than inferring it from smooth playback. Reject jumps, jitter and unreadable residual motion.

## cursor-driven-reveal

Choose this card when showing the cause of a UI change matters, such as clicking a
feature, dragging a slider or opening a result. A decorative pointer is insufficient.

- Plan the cursor's approach, target, press frame, release frame and resulting UI state.
  The state changes at the demonstrated action, not before the pointer reaches the target.
- Keep the cursor in the same coordinate space as its target through camera movement.
  A small press-scale or click ring may clarify contact without covering the control.
- During a drag, derive the demonstrated value from the held pointer's position. At
  release, settle from that value rather than resetting to the original control state.
- Leave enough time to see the destination and read the result. Use a second cursor only
  when a handoff explains the product; distinguish ownership without adding brand copy.
- For a loop, inspect the cursor's location, pressed state and velocity across the seam.

Use actual supplied footage or a supplied animated shot. Live product capture remains
pending on `cutaway_record`; these cards add no browser-control or recording tool.
An illustrative UI must use approved content and be disclosed as a demonstration.
Do not present invented interactions, analytics or marketing claims as real product use.

Inspect the click at frame resolution and play each drag through release. Reject a
cursor that misses its control, a result that appears before its trigger, a value jump
at release, or a camera move that separates pointer and target.

## Sound timing and review

Use an actual measured beat grid tied to the chosen track and version before scheduling
musical accents. BPM alone is not a measured grid. Without that input, preserve the film's
timing plan but mark beat synchronization pending. The existing workflow adds no beat
detector or SFX synthesizer.

For an authorized supplied UI sound, align its measured attack or peak to the intended
event on the verified grid within one output frame. Record which landmark you measured.
Offset the audio clip by that landmark's position instead of assuming the sound peaks at
its file start. The resulting audio start must remain inside the plan. Use only supported
cue categories and keep SFX, music and VO as separate stem plans. Leave the SFX stem empty
and disclose it when no usable asset was supplied. Never acquire upstream sample audio.

Review the supplied shot at the planned event frames and in continuous playback. After
assembly, inspect the MP4 itself, listen to the mix, and follow the parent skill's loudness,
motion-carry and checksum-bound delivery QC. Reference-frame review and a validated plan
do not pass final visual acceptance. Keep all existing render and paid-media cost approvals.

## Source and rights

Adapted in original prose from the
[skill](https://github.com/AbubakrChan/product-launch-motion/blob/fc566955b073b62d13bd9f5a12b861d0a22cc781/SKILL.md)
and [technique reference](https://github.com/AbubakrChan/product-launch-motion/blob/fc566955b073b62d13bd9f5a12b861d0a22cc781/references/technique.md),
read 2026-10-15. The source's
[MIT licence](https://github.com/AbubakrChan/product-launch-motion/blob/fc566955b073b62d13bd9f5a12b861d0a22cc781/LICENSE)
covers its authored guidance. Its
[media notice](https://github.com/AbubakrChan/product-launch-motion/blob/fc566955b073b62d13bd9f5a12b861d0a22cc781/NOTICE)
excludes sample films, frames and third-party assets. See the retained
[copyright and permission notice](../NOTICE). No source runtime or media is included.
