---
name: logo-animation
description: Animate a supplied raster logo as a reveal, sting, splash, loader or idle motion after local vector tracing and explicit approval of its geometry.
metadata:
  remotion_backend: local
  remotion_features: logo_animation named_templates canvas encoding
  include_tools: call_editor_tool
  gateway_tools: Logo___logo_vectorize Remotion___render_timeline Remotion___get_render_progress Remotion___qc_deliverable Ffmpeg___ffmpeg_tool
  routing_tools: logo_vectorize remotion_render deliverable_qc ffmpeg_tool
---

# Logo animation

Use this skill when a supplied logo needs motion. Keep generic titles, lower thirds and
channel intros without a supplied logo in [motion graphics](../motion-graphics/SKILL.md).
New logo design belongs to [image generation](../image-gen/SKILL.md) and its vector specialist.
Never recreate, improve or reinterpret an existing mark with an image or video model.

Read `read_studio_context` and discover the exact schemas before dispatch. All logo
processing uses `Logo___logo_vectorize` through `call_editor_tool`. Use its `op`
discriminator with the trusted current `job_id`, an in-job `input_path` and `params`.
For `vectorize`, use the attached asset's `renderhaus-asset://` version handle. The trusted
executor stages an owned raster inside this job. Direct calls require an existing local
path. If owned local staging is unavailable, report that dependency as blocked.
Never upload the raster, SVG or preview to another service. Never use customer marks
as training data or test fixtures. Outputs stay in the job directory or private project storage.

Ask the user to confirm that they own the logo or have permission to animate the
third-party mark. Set `params.rights_confirmed=true` only after that confirmation.
The local operations incur no provider charge. Keep vendor names, model names and
platform fees out of user-facing labels and narrative.

## Prepare and approve the vector

1. Run `op=vectorize` on the supplied PNG or JPEG. The tool bounds decoded size and
   palette, removes only edge-connected background, and traces smooth editable geometry.
2. Run `op=audit` on the returned `logo.svg`. Show the source/vector overlay strip,
   silhouette IoU and edge-smoothness report. Inspect negative space, letterforms,
   component spacing, silhouette and edge quality at enlarged scale. Numeric checks
   support this review. A failed geometry gate cannot proceed to approval.
3. Describe each semantic part as mark, wordmark or accent. Check fill versus stroke,
   stable group IDs and the suggested draw order. Automatic groups are geometry-derived
   hints. Confirm their meaning against the actual mark before choosing the order.
4. Call `op=approve` with the exact SVG checksum in `params.sha256` and the confirmed
   rights flag. The native approval card asks the user to approve this vector after
   reviewing the overlay and smoothness evidence. This pause applies in autonomous runs.
   Never claim to await approval without this call. A changed vector needs another audit
   and approval. A spending approval does not approve logo geometry.
   A worker restart invalidates its in-memory receipt signature and requires reapproval.

The final pose is the approved SVG at its recorded checksum, with every part at full
opacity and its original transform. Avoid a font substitution, redrawn letter, missing
counter or changed proportion. Complex typography, gradients, photographs, ribbon
self-intersections and tiny detail may exceed the local tracer. Report the limits and
request a better source or an approved clean vector rather than passing weak geometry.

## Choreograph the approved mark

Run `op=choreograph` against the approved SVG. Choose `style` from `reveal`, `splash`,
`loader` or `idle-hover`, a duration of 1 to 3 seconds, and a few `personality` words.
Use `idle_loop` only when requested. Save the resulting `motion_spec.md` and self-contained
HTML preview alongside the SVG. Keep the generated timeline as data and use the declared
easing tokens. Do not send arbitrary JSX or custom SVG animation code to the renderer.

Give the viewer one focal part at a time. Start with the mark, follow with the wordmark,
then settle the accents. Use a short preparatory beat, a clear main action and enough
settling time to read the final mark. Apply overlapping entrances and easing without
distorting letterforms or moving the final pose. Professional or restrained personalities
favor a small scale change and opacity. The bounded templates animate those properties.
They do not implement arbitrary morphing, ribbon fitting or a stroke draw-on renderer.
Use the same approved geometry for every preview. Reduced-motion preview shows the
finished static vector immediately.

The run exposes private SVG/overlay previews and authenticated file downloads. The HTML preview makes no external requests. Inspect its first frame, entrance, settle,
final pose and any loop seam. A loader or idle cycle must end at its starting state and
the exported sting must settle on the static vector. Never place vectorization, approval
and rendering in one parallel execution group.

## Render and verify

Use `Remotion___render_timeline` with `visuals=[]` and `template.name=logo-animation`.
Set `template.logo_job_id` to the current job, `logo_path` to the relative approved SVG,
and `svg_sha256` to its approved checksum. Preserve the choreography's `duration_seconds`,
`style`, `personality`, `idle_loop` and `background_color`. The configured backend must
be local. Lambda refuses this private-logo feature before submission.

Deliver MP4 first. Preserve the existing render approval and cost controls. Do not change
a dry-run flag to obtain media. Preserve `render_id` and poll the same render through
`Remotion___get_render_progress`. A preview, queued job or progress message is incomplete.
Open and play the saved MP4 before calling the animation finished.

Run these checks on the actual saved artifact and record their reports.

- Run `op=final_frame` to compare the final rendered frame with the approved static vector.
  A changed SVG checksum invalidates its approval and the final-frame result.
- Run `op=easing` on the declared easing tokens and durations. Require monotonic progress,
  bounded overshoot and valid timing. Constant-speed motion is limited to a requested spinner.
- Run `op=continuity` on the sampled part timeline. Inspect any position, scale or opacity
  jump, and check the first and last samples of loops. This probe checks declared motion.
  Watch the MP4 to detect raster artifacts and perceptual pops that data alone cannot certify.
- Read [deliverable QC](../remotion-deliverable-qc/SKILL.md) and use
  `Remotion___qc_deliverable` on the completed local MP4. A finished deliverable requires
  a saved passing QC report whose output checksums still match. Quote each failure verbatim.

Report delivered width, height, `source_resolution` and resolution warnings from the
successful render. A larger canvas does not add source detail. If a 1280x720 source is
resampled to 1920x1080, say "upscaled from 1280x720; no added detail". Actual enhancement
uses the existing [upscale skill](../upscale/SKILL.md) with its approval controls.
Technical checks leave customer visual review explicit.

Deliver the approved `logo.svg`, HTML preview, saved MP4 and `motion_spec.md` with the QA
evidence. Alpha ProRes 4444 and alpha WebM are unsupported by this template. Do not promise
them. Lottie is a hand-off to the sibling lottie-animation skill when installed.
TODO after that integration lands, add its real authoring tool to the hand-off metadata.
This skill has no dependency on an unbuilt Lottie tool.

## References

This method adapts [nolangz/pixel2motion](https://github.com/nolangz/pixel2motion/blob/e9faedb28930df0da2acf17da00c80730a78cfe8/SKILL.md),
by Nolan Lai, under its [MIT licence](https://github.com/nolangz/pixel2motion/blob/e9faedb28930df0da2acf17da00c80730a78cfe8/LICENSE),
read 2026-10-14. Its geometry-first review, semantic part planning, final-pose contract
and motion probes inform this local implementation. No upstream code, assets, binaries
or scripts are copied. See [NOTICE](NOTICE.md) and [limits and calibration](../../../../docs/LOGO_ANIMATION.md).
