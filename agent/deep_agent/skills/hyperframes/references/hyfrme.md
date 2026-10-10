<!--
Adapted from AksharP5/hyfrme at 26522a993082cd30ad5f404e4890d670c5c73bcb.
Copyright (c) 2026 Akshar Patel. MIT License.
Copyright (c) 2026 Remocn. MIT License.
Complete copyright and permission notices remain in third_party/hyfrme/LICENSE
and third_party/hyfrme/Remocn-LICENSE.
Modified by Renderhaus on 2026-10-09 for the existing gated, dry-run skill.
Source https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/skills/hyfrme/SKILL.md
Source https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/THIRD_PARTY_NOTICES.md
Source https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/registry/blocks/soft-blur-in/soft-blur-in.html
Source https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/registry/blocks/shared-axis-z/shared-axis-z.html
Source https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/registry/blocks/screen-lift/screen-lift.html
-->

# Adapt audited Hyfrme patterns

Use this recipe only when the customer explicitly names HyperFrames. A Hyfrme
pack name alone never selects HyperFrames. Remotion remains the default for
unnamed authored text motion, transitions, and device-card animations.
Read `read_studio_context` and honor its `intent_route`.
Report a blocked route without changing the renderer.

## Choose the smallest sample

Apply the upstream skill's smallest-component rule. Choose motion for the scene's
purpose, then preserve the supplied palette, approved copy, and reading time.
Use UI primitives for timed interface states, components for focused motion,
icons for status, and templates for complete scenes. Upstream registry types
`hyperframes:block`, `hyperframes:component`, and `hyperframes:example` distinguish
blocks, snippets, and projects. These types describe scope, not permission to install.
This adaptation packages three standalone blocks in the existing local catalog.

| Pack | Audited pattern | Packaged HTML |
| --- | --- | --- |
| `hyfrme-text-motion` | Soft Blur In. Fixed character spans rise 16 px, lose their blur, and hold a readable title. | [Text sample](../templates/hyfrme-text-motion.html) |
| `hyfrme-transitions` | Shared Axis Z. The Collect state enlarges as it fades, and Organize grows into place. The persistent label names the change. | [Transition sample](../templates/hyfrme-transitions.html) |
| `hyfrme-product-demo` | Screen Lift. A tilted planning panel lifts two rows, then settles them into place. All labels and task initials are invented. | [Product sample](../templates/hyfrme-product-demo.html) |

Read [the catalog](../templates/catalog.json) through the loaded skill filesystem.
Its data shape is `{pack_id: {html_file, arguments}}`. Read the selected entry's
`html_file` under `templates/` through the same filesystem. Copy `arguments` into
the editor call and add `html` containing the actual file contents. Do not send a
filename or a host path as HTML.

Each sample declares 1280 by 720, 30 fps, and six seconds. Keep the root and
argument envelope consistent after edits. Preserve unique IDs, the clip windows,
and one paused timeline registered under the root's exact composition ID.
Animate inner elements with explicit selector IDs and numeric times inside their
clip windows. The host supplies GSAP. The samples use no additional script,
font, image, avatar, brand mark, or media dependency. The product panel is an
illustrative interface, not a screenshot of the customer's product.
For a real product tour, use supplied source material or preserve the existing
specialized capture route. The sample does not capture a website or a product UI.

## Keep the audited boundary

Copy only these bundled, audited resources. Do not run Hyfrme or HyperFrames CLI
installers, install a catalog, fetch a third-party registry, or download assets.
Do not copy unverified packs or material with blocked, noncommercial, or AGPL terms.
Preserve the complete MIT notices with the adapted code.

The pinned [third-party notices](https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/THIRD_PARTY_NOTICES.md)
identify Paper Shaders under PolyForm Shield 1.0.0. The root MIT license is not
blanket permission for every file or dependency. This adaptation omits that shader
runtime, compiled React runtimes, fonts, photographs, and other third-party media.
The rewritten GSAP samples preserve the selected motion patterns and MIT notice chain.
MIT code licensing does not provide media or training authorization. Preserve
`training_eligible: false` and require separate rights for any future supplied media.

## Preview and report limits

Keep the existing defaults `HYPERFRAMES_ENABLED=false` and
`HYPERFRAMES_DRY_RUN=true`. When the explicitly requested tool is available,
discover `HyperFrames___render_composition` and use `call_editor_tool` with its
exact schema. Existing approval and spending-cap behavior remains unchanged.
The host reports compute cost as unknown. Do not turn an unknown quote into zero.

The dry-run preview validates input metadata only. It does not execute HTML,
seek GSAP, capture proof frames, or return generated media. A disabled tool or
unavailable live worker is a blocker. Keep the export incomplete.

Static structure and a GSAP test double can check IDs, bounded clip timing, and
timeline registration. Real GSAP seeking, layout, visual acceptance, and rendering
require a future isolated worker. Comet cannot be controlled in the current
environment, so browser E2E remains pending. Follow `docs/BROWSER_E2E.md` when
access becomes available. Inspect the start, state-change boundaries, midpoint,
and final frame. Test forward and backward seeks after edits, then open and play
the actual artifact before reporting a completed render.
