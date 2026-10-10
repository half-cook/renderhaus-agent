# HyperFrames template packs

The existing `hyperframes` skill includes cinematic-caption, tactile-collage, and
Hyfrme MIT recipe packs with five standalone example compositions.
Remotion remains the motion-graphics default.
An explicit HyperFrames request selects the optional preview tool when enabled.
Plain cinematic captions and animated paper-collage requests select Remotion.
An HTML template request without the HyperFrames name also keeps Remotion.
Supplying a photo for a collage animation keeps that motion-graphics route.
A request for a still poster for the video remains an image-generation request.

## Pack resources

| Pack | Resources | Adaptation |
| --- | --- | --- |
| Cinematic caption | [Recipe](../agent/deep_agent/skills/hyperframes/references/cinematic-caption.md), [HTML](../agent/deep_agent/skills/hyperframes/templates/cinematic-caption.html) | Semantic groups, spoken-order reveals, deliberate hero emphasis, neutral translucent type, compact CTA, and subject-clear placement. |
| Tactile collage | [Recipe](../agent/deep_agent/skills/hyperframes/references/tactile-collage.md), [HTML](../agent/deep_agent/skills/hyperframes/templates/tactile-collage.html) | Paper and ink roles, physical scene metaphors, restrained placed or stamped motion, safe caption areas, and full-frame fallback. |
| Hyfrme | [Recipe](../agent/deep_agent/skills/hyperframes/references/hyfrme.md), [pack details](HYPERFRAMES_HYFRME_PACK.md) | Three examples for text reveals, shared-axis transitions, and a device card with raised UI rows. |

The [catalog](../agent/deep_agent/skills/hyperframes/templates/catalog.json)
stores each HTML filename and its preview dimensions, duration, and frame rate.
Deep Agents reads these resources through `/skills/hyperframes/`. The catalog
is authoring data, not a new tool schema or a runtime loader.
The installed `deepagents==0.7.23` filesystem and skills middleware expose nested
resources without changing the manager, editor, or approval configuration.

The examples use invented sample copy and system font stacks. No source footage,
font files, model weights, upstream scripts, or new runtime dependency is bundled.
The caption example uses clear space rather than claiming a subject matte.
The collage example uses the full-frame mode. Approved brand assets and measured
timings take precedence when adapting an example to a project. Hyfrme's device
card uses invented UI and does not implement capture. Its recipe omits mixed-licence
shader runtimes. The Hyfrme pack name alone does not opt into HyperFrames.

## Preview an example

1. Read `/skills/hyperframes/SKILL.md` and the recipe for the selected pack.
2. Read `/skills/hyperframes/templates/catalog.json` and its selected HTML file.
3. Copy the entry's `arguments`. Add `html` containing the file's complete text.
4. Discover `HyperFrames___render_composition` and its current schema.
5. Pass the arguments through `call_editor_tool` under the existing approval rules.

The required fields remain `html`, `duration_seconds`, `width`, `height`, and
`fps`. The HTML root and catalog values agree. Composition roots sit directly in
the body. Timed clips have stable IDs and bounded windows. Animation targets
inner wrappers. Each example registers one paused GSAP timeline under the exact
composition ID. A future isolated worker must supply an approved local GSAP
runtime. The examples do not fetch scripts, fonts, media, or catalog assets.

`HYPERFRAMES_ENABLED` defaults false. `HYPERFRAMES_DRY_RUN` defaults true.
Disabled requests return a blocker without a Remotion substitution.
Setting dry-run false still returns `not_run` because no isolated renderer exists.
A successful dry-run returns input metadata only. It does not parse renderer
semantics, execute HTML, create proof frames, composite footage, mix audio, or
produce an MP4.

The non-autonomous preview retains its cost approval. Compute cost remains
**unknown**, with no invented zero rate. An autonomous run with a spending cap
cannot reserve an unknown quote. Paid dependencies retain their existing
approvals, including video approval in autonomous runs. No approval exemption,
spending cap, provider secret, or model policy changes in this task.

## Sources and licences

The following immutable upstream sources and their full LICENSE files were read
on **2026-10-09** before adaptation.

| Work | Revision and source | Licence |
| --- | --- | --- |
| audrey-560/hyperframes-cinematic-caption | [6cdb01d74949cab379e048e9092709adbb3b203b](https://github.com/audrey-560/hyperframes-cinematic-caption/tree/6cdb01d74949cab379e048e9092709adbb3b203b), [LICENSE](https://github.com/audrey-560/hyperframes-cinematic-caption/blob/6cdb01d74949cab379e048e9092709adbb3b203b/LICENSE) | MIT, Copyright (c) 2026 Audrey. |
| audrey-560/hyperframes-tactile-collage | [ef6a49f5a250e6b3b1a0839cafc7a2d43872e619](https://github.com/audrey-560/hyperframes-tactile-collage/tree/ef6a49f5a250e6b3b1a0839cafc7a2d43872e619), [LICENSE](https://github.com/audrey-560/hyperframes-tactile-collage/blob/ef6a49f5a250e6b3b1a0839cafc7a2d43872e619/LICENSE) | MIT, Copyright (c) 2026 Audrey. |
| Existing HyperFrames guidance | [heygen-com/hyperframes LICENSE at 3aa68869f7d4cec8b37cdfcb9cd539389b63abed](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/LICENSE), previously assessed 2026-10-08 | Apache-2.0, Copyright 2026 HeyGen, Inc. |

The caption and collage MIT copyright and permission notices remain in
`third_party/hyperframes-cinematic-caption/LICENSE` and
`third_party/hyperframes-tactile-collage/LICENSE`. Adapted files carry source and
modification attribution. Python distributions package the recipes, templates,
catalog, and licences. The AgentCore image already copies `agent/` and
`third_party/`. Current provider, Gateway tool, and skill counts are 16, 117, and 30.
The [Hyfrme pack assessment](HYPERFRAMES_HYFRME_PACK.md#sources-and-licence-scope)
records its pinned MIT attribution chain and omitted dependencies.

These licences permit commercial code adaptation. They do not grant rights to
customer media, faces, voices, or training data. `hyperframes_render` remains
`training_eligible=false`. No model, model ID, paid endpoint, price, or secret is
added. Local renderer pricing is TODO with estimate `unknown`.
No AGPL or non-commercial code or weights are copied. Upstream font installers,
bundled font data, transcription, segmentation, and hosted HeyGen calls are excluded.

## Verification limits

Offline contract tests parse the actual packaged examples and pass their complete
input envelopes through the real HyperFrames dry-run server. Routing checks cover
plain and explicit requests, enabled and disabled flags, and inert confidential
metadata. Existing fake-model graph tests cover preview approvals, rejection,
resumption, and the unknown-cost spending cap.

Caption/collage checks recorded before the Hyfrme adaptation on **2026-10-09**
passed: 1,371 unittest tests ran, with
1,365 passing and six skipped. This includes all 18 pack contracts. Ruff,
`scripts/ci_check.py`, and the requested Studio TypeScript check passed.
CI used the required dry-run flags, an empty secrets name, and cached wheels with
package-index access disabled. The temporary Studio dependency link was removed.
An actual wheel contains the five nested resources and both complete MIT notices,
each identical to the checkout bytes.

The caption/collage task added five active routing rows, including capability-map seed row 149.
Current inventory and routing totals are in [Skill routing](SKILLS.md#offline-routing-verification).
HyperFrames footage compositing and Cutaway capture remain pending. Ambiguous extension
length semantics and named Wan's preview licence retain their existing blocks. No skipped row is activated
by these template packs. The existing unnamed HTML-template row now uses Remotion.
Hyfrme adds six active renderer-selection examples and activates no dependency
skip. Its verification is recorded in [the Hyfrme assessment](HYPERFRAMES_HYFRME_PACK.md)
and [decisions](hyperframes-hyfrme-decisions.tsv).

These checks establish static structure and input-preview behavior. They do not
prove real GSAP seeking, caption contrast, subject clearance, visual quality, or
video playback. Recipe instructions keep proof frames and chronological contact
sheets pending until an isolated worker exists. Subject-aware depth additionally
needs a supplied clean matte locked to source timing, crop, and dimensions.
Without that input, the recipe uses clear space or the collage overlay/full-frame
fallback. Matting and transcription are not implemented by these packs.

Comet browser E2E is **blocked**. The user states Comet is unavailable, and no
Comet-control tool is exposed here. No substitute browser or fake success is used.
The blocked receipt is recorded under ignored `.renderhaus/e2e/` through
`scripts/browser_e2e_hook.py`. Real rendering and artifact playback remain pending.

See [the original renderer assessment](HYPERFRAMES_ASSESSMENT.md),
[third-party notices](THIRD_PARTY_NOTICES.md), and
[task decisions](hyperframes-caption-collage-decisions.tsv).
