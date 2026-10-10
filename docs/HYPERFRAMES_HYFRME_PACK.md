# HyperFrames Hyfrme pack

The existing `hyperframes` skill includes three asset-free examples adapted from
Hyfrme. Remotion remains the default renderer. A customer must name HyperFrames
to select its optional preview path. Saying Hyfrme alone does not select that
renderer. A request to record a UI demo still follows the pending Cutaway workflow.

## Pack resources

| Catalog entry | Example | Adapted pattern |
| --- | --- | --- |
| `hyfrme-text-motion` | [HTML](../agent/deep_agent/skills/hyperframes/templates/hyfrme-text-motion.html) | Explicit character reveals with opacity, vertical motion, and finite blur. |
| `hyfrme-transitions` | [HTML](../agent/deep_agent/skills/hyperframes/templates/hyfrme-transitions.html) | Scale and opacity change between two authored scene states. |
| `hyfrme-product-demo` | [HTML](../agent/deep_agent/skills/hyperframes/templates/hyfrme-product-demo.html) | A device card with raised UI rows and invented sample copy. |

Each sample declares a 1280 by 720 composition at 30 fps for six seconds.
These dimensions describe the input preview. No rendered deliverable exists.
The [recipe](../agent/deep_agent/skills/hyperframes/references/hyfrme.md) explains
selection and adaptation. The existing
[catalog](../agent/deep_agent/skills/hyperframes/templates/catalog.json) maps each
entry to its HTML filename and arguments. Read the files through the native
Deep Agents skill filesystem, then pass their actual HTML and catalog arguments
to `HyperFrames___render_composition` through `call_editor_tool`.

The required tool fields remain `html`, `duration_seconds`, `width`, `height`,
and `fps`. No provider, tool, template-ID argument, or top-level skill is added.
Installed `deepagents==0.7.23` already exposes nested resources through the
existing filesystem backend and `skills` configuration. No new framework,
middleware, manager model, editor role, or approval-resume configuration is needed.

Roots sit directly in the body. Clip windows fit the composition duration.
One paused GSAP timeline targets inner wrappers and registers under the root's
composition ID. Explicit timeline positions replace render-time clocks and
randomness. System fonts and static HTML replace fonts, media, React runtimes,
and upstream variable APIs. A future isolated worker must supply a local GSAP
runtime and verify real seeking. This adaptation does not claim upstream visual parity.

## Sources and licence scope

The following official repository sources were read on **2026-10-09**.

| Work | Pinned source | Licence |
| --- | --- | --- |
| Hyfrme recipe | [skills/hyfrme/SKILL.md](https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/skills/hyfrme/SKILL.md), [LICENSE](https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/LICENSE) | MIT, Copyright (c) 2026 Akshar Patel. |
| Text pattern | [soft-blur-in.html](https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/registry/blocks/soft-blur-in/soft-blur-in.html) | MIT with Remocn attribution. |
| Transition pattern | [shared-axis-z.html](https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/registry/blocks/shared-axis-z/shared-axis-z.html) | MIT with Remocn attribution. |
| Device-card pattern | [screen-lift.html](https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/registry/blocks/screen-lift/screen-lift.html) | Hyfrme MIT. Upstream photo and font assets are omitted. |
| Remocn attribution | [Hyfrme third-party notices](https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/THIRD_PARTY_NOTICES.md), [Remocn LICENSE](https://github.com/Remocn/remocn/blob/ea730a20b4ab09430ee7292aebc847c002375151/LICENSE) | MIT, Copyright (c) 2026 Remocn. |

Both complete MIT notices are included in `pyproject.toml` licence files.
The existing package-data globs already include the new HTML and recipe files.
Attribution headers identify the pinned sources and Renderhaus modifications.
Hyfrme's root MIT licence is not blanket permission for every registry asset.
The inspected [grain-gradient registry item](https://github.com/AksharP5/hyfrme/blob/26522a993082cd30ad5f404e4890d670c5c73bcb/registry/blocks/shader-grain-gradient/registry-item.json)
declares `MIT + PolyForm Shield 1.0.0`. That shader runtime is omitted rather than
relicensed as MIT. No AGPL or non-commercial code or weights are included.

These are authoring resources, not models. No model ID, API endpoint, paid rate,
or secret is added. `hyperframes_render` remains `training_eligible=false`.
Permissive code licences do not grant rights to customer media, faces, voices,
or continuity-training data.

## Pricing and validation limits

Local renderer pricing is **TODO**, with estimate **unknown**. No official hosted
price applies to these offline templates. Existing approval and spending limits
remain in place. `HYPERFRAMES_ENABLED` defaults false and
`HYPERFRAMES_DRY_RUN` defaults true. Live mode returns `not_run` until an isolated
renderer exists. A dry-run result contains only input metadata and cannot satisfy
delivery, QC, or artifact-playback checks.

Offline contracts cover packaged file access, bounded roots and clips, fake-GSAP
registration and targets, complete licence bytes, no remote dependencies, schema
validation, dry-run metadata, disabled/live refusal, and renderer selection with
both values of confidential metadata. Existing fake-model graph tests cover
approval, rejection, resumption, and unknown-cost spending caps. CI runs the pack
contracts under its existing HyperFrames preview check.

Six new active fixture rows cover named HyperFrames and default Remotion choices.
No previously skipped row becomes active. HyperFrames overlays, three Cutaway
capture rows, and exact end-card OCR retain their current dependency reasons.
The provider, Gateway-tool, and skill inventories remain 16, 117, and 30.
The routing fixture now contains 226 rows, with 221 active and five skipped.

Offline checks completed on **2026-10-09**:

- The unchanged starting commit passed 1,972 unittest tests with seven skips.
  The final full suite passed 1,982 tests with the same seven skips.
- All 22 pack contracts passed, including their invocation from the existing
  CI HyperFrames dry-run preview check. The fixture suite passed 236 tests with
  five skips; all original 220 fixture objects remain unchanged.
- The requested Ruff command, `scripts/ci_check.py`, and Studio TypeScript check
  passed. CI and unittest used an empty secrets name and all required dry-run
  flags. Package-index access was disabled and CI used cached wheels.
- An actual offline wheel contains nine nested HyperFrames resources, the
  owning skill, and both new MIT notices, each byte-identical to the checkout.
  The temporary Studio dependency link was removed.
- A fresh native Codex diff and comment review found no actionable issues.
  Claude/Grok review lanes were unavailable; this is native review coverage only.

No new environment variables, secrets, or dry-run flags are required. Logs and
the wheel comparison remain under ignored `.renderhaus/e2e/`.

Comet browser E2E is **blocked** because the user states Comet is unavailable and
no Comet-control tool is exposed. The ignored receipt records that blocker through
`scripts/browser_e2e_hook.py`. Real GSAP seeking, proof frames, visual review, and
artifact playback remain pending. Offline contracts do not establish those results.

See [all template packs](HYPERFRAMES_TEMPLATE_PACKS.md),
[third-party notices](THIRD_PARTY_NOTICES.md), and
[task decisions](hyperframes-hyfrme-decisions.tsv).
