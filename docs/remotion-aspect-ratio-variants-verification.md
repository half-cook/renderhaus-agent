# Aspect-ratio variants verification

Verified 2026-10-09 on `feat/remotion-aspect-ratio-variants`, based on `5c97ea8`.
The local artifact pipeline passed. Studio browser E2E remains blocked because Comet is
unavailable in this environment; no browser actions or browser pass are claimed.

## Implemented surface

No provider or Gateway tool was added. The existing `Ffmpeg___ffmpeg_tool` gains:

| Operation | Key arguments |
| --- | --- |
| `crop_plan_preview` | `source_width`, `source_height`, `aspect`; optional rotation, boxes, anchor, safe zone, explicit upscale |
| `reframe_crop` | `aspect`; optional subject/crop boxes, anchor, safe zone, `allow_upscale` |
| `reframe_pad_blur` | `size` as an aspect enum; optional safe zone and `allow_upscale` |
| `detect_scenes` | `T`, finite 0.1–0.6; default 0.3 |

`Remotion___render_ad_variants` accepts `brief.reframe_only=true` and minimal
`{variant_key,aspect}` rows, optional shots/cut times, validated boxes and safe margins.
It returns candidate MP4s with contact sheets and editorial review pending.
`Remotion___render_timeline` accepts `crop_box`, `pad_box`, `reframe_size`, `allow_upscale`
and `fit="pad_blur"` per visual. New fields and matrix jobs refuse Lambda before any AWS
request; existing Lambda timelines remain available. No live Lambda call was made.

## Real local artifacts

The deterministic generator produced a four-second `1920x1080` master with synthetic
modulated audio, alpha logos, product stills and CSV tables under
`.renderhaus/demo/aspect-final-1080p/`. The local CLI rendered five native master candidates,
fifteen retail candidates through sample/batch gates, and five explicit upscale candidates.
All 25 final MP4s fully decoded with video and audio; hashes matched, JPEG contact sheets
opened, duration was four seconds, FPS was 24 and SAR was `1:1`.
`source_resolution` was `1920x1080` for every output. The source is CFR; the cadence warning
regression uses injected mismatched metadata and does not claim a real VFR fixture.

| Aspect | Native delivered width × height | Explicit upscale delivered width × height |
| --- | --- | --- |
| 9:16 | 606 × 1076 | 1080 × 1920 |
| 1:1 | 1080 × 1080 | 1080 × 1080 |
| 4:5 | 864 × 1080 | 1080 × 1350 |
| 16:9 | 1920 × 1080 | 1920 × 1080 |
| 2.39:1 | 1920 × 804 | 1920 × 804 |

Native outputs had no resolution or cadence warnings. Explicit portrait and 4:5 outputs
were flagged as **upscaled from 1920x1080; no added detail**, with the existing Topaz
`upscale` skill recommended for enhancement under its existing approval. The other three
explicit outputs had no resolution warnings. Contact sheets remain editorial candidates;
no person has approved their final framing and no loudness/delivery certification is claimed.
The first retail portrait contact sheet was visually inspected: price, CTA and legal text
are visible inside the planned layout.

Ignored evidence: `.renderhaus/work/final-demo-evidence.json`, the CLI plan/render JSON
files and `.renderhaus/e2e/aspect-ratio-variants.json`. The Comet blocker was recorded with
`python3 scripts/browser_e2e_hook.py record --report .renderhaus/e2e/aspect-ratio-variants.json`.
No keys, credentials or signed URLs are stored in this evidence.

## Checks

- Ruff: passed for `agent lambdas scripts server providers`.
- Unit suite: **1762 tests, 38 skipped**, passed in 186.493 seconds.
- `scripts/ci_check.py`: passed, including regenerated Gateway schemas, dry-run tools and Lambda ZIP packaging.
- Studio `tsc --noEmit -p .`: passed using the shared node_modules link; the temporary link was removed.
- Independent native review: all six confirmed findings fixed and rechecked.
- Real binaries: geometry, fractional FPS/audio/SAR, rotations, padding foreground edges,
  scene cuts and metadata, concurrent outputs, parameter/path attacks and deadline tests passed.
- Backend parity: supported canonical document fields and unsupported Lambda refusals tested with fakes; no deployed pixel-parity claim.

All requested provider dry-run flags were true and `RENDERHAUS_SECRETS_NAME` was empty
for full tests/CI. Existing `FFMPEG_DRY_RUN=true` was included. No new flag, dependency,
environment variable or secret is required. Only the explicitly authorized local demo and
real-binary tests rendered files; no paid provider/model API, deployment, push or PR occurred.

## Routing and inventory

Activated nine rows, RT-E011–RT-E019, including aspect positives and outpainting/detector/
logo/Resolve negatives. Resolve-only rows stay active refusals with no Resolve tool.
Inventory: **16 providers, 115 Gateway tools, 26 skills; 218 routing rows, 182 active and
36 skipped**. The 79 editing workbook rows contain 47 active and 32 skipped.
Skipped rows: 30 delivery/loudness/QC cases, including RT-E046, await
`feat/remotion-delivery-qc`; two LUT/multicam cases have unverified semantics in that branch;
one HyperFrames overlay and three cutaway capture cases retain their existing provider blockers.

## Pricing, licences and open work

Local media price is $0, excluding operator compute. The existing $0.01/render Remotion
allowance remains a configurable estimate, not a verified charge for the local ffmpeg
compositor. Official Remotion FAQ/terms, read 2026-10-09, list free use up to three people
and Company Automators licensing at four or more: $0.01 per successful render, $100/month
minimum. Local metering is **UNVERIFIED**. Existing Lambda compute estimates retain their
workload assumptions; Lambda matrix execution remains refused.

- [Remotion licence FAQ](https://www.remotion.dev/docs/license/faq) and [terms](https://www.remotion.dev/docs/terms): custom commercial licence; existing editing policies retain `training_eligible=false`.
- [FFmpeg legal](https://ffmpeg.org/legal.html): LGPL 2.1+ base or GPL 2+ build; the installed 7.1.5 binary reports GPL 2+. No binary or upstream code is redistributed; `training_eligible=false`.
- [DejaVu licence](https://dejavu-fonts.github.io/License.html): Bitstream Vera base and public-domain changes; system fonts only, no font binary vendored.
- Demo video/audio/logos/product stills: generated locally, no outside asset. No new model or weights, consent requirement or training permission was introduced.

All licence URLs were read 2026-10-09. No AGPL, non-commercial code/weights or detector
dependency was added. Safe-zone presets remain placeholders to confirm per destination.
Comet E2E, local licence metering, VFR cadence, final human editorial approval and delivery/
loudness/QC remain open. Detectors are a later branch; this branch runs none.

## Implementation commits

- `50a8a26` — feat(ffmpeg): add bounded crop plans, reframing and scene detection
- `b89bbf2` — feat(remotion): render static crop windows and safe blurred padding locally
- `652d3c3` — feat(remotion): plan aspect matrices with static shots and editorial review sheets
- `40326a5` — feat: route static aspect variants and port editorial reframe skill
- `11dd836` — fix(remotion): refuse anamorphic reframe inputs and cover rounded crop canvases
- `7f47ed2` — fix(remotion): align crop source bounds and reject invalid measured frame rates
- `b3516e2` — docs: document aspect candidates and add five-aspect local demo
- `a756fdf` — fix(ffmpeg): validate measured frame rates and parse only scene records
- `2811b6e` — fix(remotion): align reframe estimates and native matrix expectations
- `0bd5f89` — fix(remotion): disclose cadence conversion in plans and manifests

The subsequent documentation commit records this verification and clarifies the static-op contact-sheet/SAR instructions.

## Changed files

- [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)
- [Dockerfile.agentcore](../Dockerfile.agentcore)
- [README.md](../README.md)
- [agent/deep_agent/routing.py](../agent/deep_agent/routing.py)
- [agent/deep_agent/routing_policy.json](../agent/deep_agent/routing_policy.json)
- [agent/deep_agent/skills/remotion-ad-variant-matrix/SKILL.md](../agent/deep_agent/skills/remotion-ad-variant-matrix/SKILL.md)
- [agent/deep_agent/skills/remotion-aspect-ratio-variants/SKILL.md](../agent/deep_agent/skills/remotion-aspect-ratio-variants/SKILL.md)
- [configs/gateway/ffmpeg.tools.json](../configs/gateway/ffmpeg.tools.json)
- [configs/gateway/remotion.tools.json](../configs/gateway/remotion.tools.json)
- [docs/DEEP_AGENT.md](../docs/DEEP_AGENT.md)
- [docs/REMOTION_EDITING.md](../docs/REMOTION_EDITING.md)
- [docs/SKILLS.md](../docs/SKILLS.md)
- [docs/remotion-aspect-ratio-variants-decisions.tsv](../docs/remotion-aspect-ratio-variants-decisions.tsv)
- [docs/remotion-aspect-ratio-variants-verification.md](../docs/remotion-aspect-ratio-variants-verification.md)
- [providers/contracts.py](../providers/contracts.py)
- [providers/ffmpeg/api.py](../providers/ffmpeg/api.py)
- [providers/ffmpeg/ops.py](../providers/ffmpeg/ops.py)
- [providers/ffmpeg/reframe.py](../providers/ffmpeg/reframe.py)
- [providers/remotion/ad_layouts.json](../providers/remotion/ad_layouts.json)
- [providers/remotion/ad_variants.py](../providers/remotion/ad_variants.py)
- [providers/remotion/api.py](../providers/remotion/api.py)
- [providers/remotion/local.py](../providers/remotion/local.py)
- [scripts/ci_check.py](../scripts/ci_check.py)
- [scripts/make_ad_demo_assets.py](../scripts/make_ad_demo_assets.py)
- [scripts/run_ad_demo.py](../scripts/run_ad_demo.py)
- [server/billing_rates.py](../server/billing_rates.py)
- [tests/fixtures/skill_routing.json](../tests/fixtures/skill_routing.json)
- [tests/test_ad_demo.py](../tests/test_ad_demo.py)
- [tests/test_ad_variant_matrix.py](../tests/test_ad_variant_matrix.py)
- [tests/test_reframe_matrix.py](../tests/test_reframe_matrix.py)
- [tests/test_reframe_ops.py](../tests/test_reframe_ops.py)
- [tests/test_reframe_plan.py](../tests/test_reframe_plan.py)
- [tests/test_reframe_timeline.py](../tests/test_reframe_timeline.py)
- [tests/test_remotion_editing_routing.py](../tests/test_remotion_editing_routing.py)
- [tests/test_skill_routing.py](../tests/test_skill_routing.py)
