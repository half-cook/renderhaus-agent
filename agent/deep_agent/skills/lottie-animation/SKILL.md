---
name: lottie-animation
description: Author Lottie JSON and dotLottie vector animations for app and web UI, loaders, onboarding and SVG reveals. Rendered video titles and explainers stay on motion-graphics.
metadata:
  include_tools: call_editor_tool
  routing_tools: lottie_author lottie_validate lottie_preview_render
  gateway_tools: Lottie___lottie_author Lottie___lottie_validate Lottie___lottie_preview_render
---

# UI vector animation

Use this skill for Lottie, dotLottie or animation JSON deliverables, and functional
animation for app or website UI. MP4 titles, lower thirds and explainers use
[motion-graphics](../motion-graphics/SKILL.md). A generic "animate our logo" request
does not choose this skill without an explicit Lottie, JSON or UI destination.
For a raster logo, obtain a vector version first; use a logo-animation skill only
if it is actually installed. Never treat a raster image as editable vector paths.

Ask for concrete assets before inventing a brand design. Request the SVG, a
screenshot, brand colours, final size, target platforms, state transition or real
data that matters to this brief. Fonts and brand assets must be user-owned or
licensed. For a new vector mark, [image-gen](../image-gen/SKILL.md) can use routing
ID `recraft_v41_vector` through its existing vector tool. That is a
separate paid action under its existing approval policy. These local tools do not
call models, buy assets or grant paid-generation permission.

Discover the exact schemas and call all three tools through `call_editor_tool`.
Use the trusted current Studio `job_id`. Pass an attached SVG's owned
`renderhaus-asset://version` handle as `svg_path`; Studio stages it through its
trusted asset resolver and retains provenance. Other local inputs must be inside
that job. Never invent a host path or copy an asset from another job. The author can
create its own job directory for a new scene.

## Author and revise

The agent writes the scene; `lottie_author` validates and serializes it. Supply
exactly one of `scene`, `lottie`, `input_path` or `svg_path`. `input_path` reads saved
JSON or dotLottie. With `lottie` or `input_path`, `patch` recursively merges object
fields and replaces arrays. Read the saved revision before patching; preserve the
prior file and use the new returned paths for subsequent work.

Default to 256 by 256 pixels, 60 fps, 90 frames and transparent output. Set a
background only when the brief needs one. Name layers for their meaning, such as
"Success check" or "Loading ring". Use the scene's named `linear`, `ease-in`,
`ease-out` or `ease-in-out` tokens on animation keyframes. Frame `op` is exclusive.
Choose small responsive motions, a readable settled state and enough hold time.
Keep loaders' endpoints aligned and inspect the seam. Stage repeated parts in
reading order instead of adding arbitrary delay or decoration.

Scene layers support rectangle, ellipse and Bézier path geometry, solid fills,
strokes, position, scale, rotation, opacity and stroke trim reveals. Author ordinary
Lottie JSON for more complex scenes, then inspect the validation and preview reports.
The [tool reference](../../../../docs/LOTTIE_ANIMATION.md) contains a concrete scene
example, bounds and the supported SVG subset. Unsupported SVG features fail with
an explicit error. Do not remove brand geometry or styling to make a refusal disappear.

## Validate and preview

Run `lottie_validate` on the returned JSON for `lottie-web`, `lottie-ios`,
`lottie-android` and `dotlottie`, or the brief's selected targets. Structural validity
does not certify playback on every platform. Report compatibility warnings,
expressions, effects, masks and blend-mode differences. Fix malformed references,
out-of-range frames or invalid keyframes before delivery.

Run `lottie_preview_render` on that exact saved file. It creates deterministic PNG
frames, a strip and contact sheet, a self-contained scrubbable HTML preview, and
requested MP4 and GIF previews through allow-listed local encoding. A preview is
supporting evidence; JSON and dotLottie remain the deliverables. MP4 preview pixels
may have a contrast background while the animation stays transparent.

If `not_previewed` is nonempty or the tool reports incomplete output, say exactly
which feature or dependency prevented preview. Never claim a full preview when
features were skipped. Simplify only with the customer's agreement when that changes
the requested appearance. No headless browser or external player is part of these tools.

Inspect frame zero, the early reveal, midpoint, settled frame and final frame.
Scrub meaningful transitions and play loops. Check small-size readability, clipping,
stroke caps, stacking and the settled SVG match. Revalidate and preview after edits.
The local rasterizer covers a declared subset; actual target-player visual review
remains explicit, particularly for advanced supplied JSON.

## Deliver

Link both returned `.json` and `.lottie` downloads. Include byte sizes, frame count,
fps, duration, width and height, compatibility notes and any incomplete preview.
Use the returned web, iOS and Android usage snippets as documented examples, not
executed integrations. Do not describe a preview MP4 as the requested finished video.
If the customer also wants a final video composition, use motion-graphics separately.

## Attribution

The grounding, small-scene workspace and pinned-frame review pattern adapt the MIT
[diffusionstudio/lottie guidance](https://github.com/diffusionstudio/lottie/tree/3c72912/skills/text-to-lottie),
read 2026-10-14. Renderhaus implements its own tools and bounded preview renderer.
The [NOTICE](../../../../providers/lottie/NOTICE) retains the origin, revision and MIT notice.
