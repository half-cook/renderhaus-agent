# Image specialists on fal

Ideogram 4.5 editing corrects text in an existing image. Recraft V4.1 Pro generates
editable SVGs. Both are exceptions to the existing GPT Image 2.5 Sunburst defaults,
with typed requests, async fal submission and the existing `Fal___get_video_task` poll.
They default to dry-run. No paid provider request or deployment was performed here.

| Routing ID | Gateway tool | Verified fal endpoint |
| --- | --- | --- |
| `ideogram45_edit` | `Fal___ideogram_edit` | `ideogram/v4.5/edit` |
| `recraft_v41_vector` | `Fal___recraft_text_to_vector` | `fal-ai/recraft/v4.1/pro/text-to-vector` |

Endpoint IDs, schemas, prices and terms below were read **2026-10-09** from official
pages. The Recraft endpoint corrects the map lead's missing `fal-ai/` prefix; canonical
IDs do not change. Neither endpoint is UNVERIFIED. Account access and output quality
remain untested. Fal is retained to reuse the existing US-accessible host, queue,
authentication and poll transport. The [Ideogram direct API overview](https://developer.ideogram.ai/ideogram-api/api-overview)
exposes the same precise edit use case; [Recraft direct API pricing](https://www.recraft.ai/pricing?tab=api)
also lists $0.30 for Pro Vector. Neither provides a clear reason to replace fal here.

## Contracts

[Ideogram API](https://fal.ai/models/ideogram/v4.5/edit/api): required `prompt` (1–10,000
characters) and `image_url`. Optional `reference_image_urls` allow four images, or three
with `mask_url`. Masks use black for edit and white for preserve; the vendor requires
matching source dimensions and both regions. `edit_precision` defaults to `high` for
unchanged-pixel restoration; `regular` permits redrawing/resizing. `image_size` defaults
to `auto`, required with a mask or high precision. `quality` is `very_low`, `low`, `medium`
(default) or `high`; `num_images` is 1–8 (default 1), with optional integer `seed`.
HTTPS references and authorized immutable Studio handles are accepted. Handles resolve
before live dispatch; unresolved handles cannot reach fal. Mask dimensions/pixels are
vendor checks; this adapter validates the URL, reference count and control combinations.

[Recraft API](https://fal.ai/models/fal-ai/recraft/v4.1/pro/text-to-vector/api): required
`prompt` (1–10,000 characters), optional named `image_size` (default `square_hd`),
`colors` (RGB objects with integer channels 0–255), optional RGB `background_color`,
and `enable_safety_checker` (default true). Style belongs in the prompt; this endpoint
has no separate `style`, `seed` or `num_images` field. Safety-checker changes require
vendor account authorization.

Both expose only named image-size presets. The vendor accepts custom dimensions, but
Gateway's current schema subset cannot represent a string/object union. Custom dimensions
and sync mode are omitted deliberately. Invalid and unknown fields fail before paid HTTP.
Poll with the full returned `job_id`; despite its legacy name, `get_video_task` handles
these image jobs too. A completed image poll persists every output even with `download=false`.

## Prices and approval

| Model | Official provider price | Source, read 2026-10-09 |
| --- | --- | --- |
| Ideogram 4.5 edit | $0.008 very_low, $0.03 low, $0.06 medium, $0.22 high per image; all variations billed | [fal model pricing](https://fal.ai/models/ideogram/v4.5/edit) |
| Recraft V4.1 Pro vector | $0.30 per image | [fal endpoint pricing](https://fal.ai/models/fal-ai/recraft/v4.1/pro/text-to-vector) |

Recraft's rate is exposed in the exact endpoint's public `publicEndpointBilling` metadata;
it is not the cheaper Flash rate elsewhere on the page. Quotes use Decimal provider rates
and the existing service fee. Fractional cents round up only after multiplying variations.
Dry-run billing is zero while approval disclosures show the published live estimate.
Paid images pause in non-autonomous runs; autonomous runs retain the unchanged spend cap.
Neither tool is approval-exempt. Premium paid-video behavior remains in place.

## Routing and quality evidence

Selection is explicit request, then exception, then default. `image_edit` uses Ideogram
for `text_only_edit` with an existing source. `still_image` uses Recraft for `vector_output`.
Generic edits, new posters and named Ideogram generation without an edit source retain
GPT Image. Mixed changes or negated text edits do not take the text-only exception.
An explicitly requested raster model cannot silently satisfy editable SVG output and is
blocked with disclosure. A confidential flag does not affect routing. Retired draft aliases
`ideogram_t2i` and `recraft_t2i` are not live Gateway names.

Pixel-preserving text editing has thin evidence. Actual Ideogram text-edit outcomes carry
`ab_arm=ideogram45_edit`; explicit GPT text-edit outcomes carry `ab_arm=gpt_image25_edit`.
This labels independently authorized work for comparison, without submitting another job.
Spending approval does not count as visual acceptance. The quality A/B remains TODO;
collect real customer-approved comparisons before treating unchanged pixels as guaranteed.

## Licensing and storage

Both are **closed-weights commercial service-terms APIs**, not licensed weights. Official
fal endpoint pages label commercial use; [fal Terms of Service](https://fal.ai/legal/terms-of-service),
read 2026-10-09, require input rights and consent under section 6(d), and restrict using
outputs to train competing third-party models under section 14.3. Thus both have
`training_eligible=false`. No model code or weights, AGPL code or non-commercial package
was copied. No additional vendor consent-confirmation request field was verified; users
must hold the necessary rights to supplied images and real-person likenesses.

Recraft result metadata and download HTTP headers must declare `image/svg+xml`.
Downloads are bounded to 20 MiB; invalid XML, entities, DTDs and non-SVG roots are rejected.
An allowlist preserves passive SVG geometry, text and local gradients/references, removing
scripts, events, styles, foreign objects, images, animations and external resources.
This can alter SVGs that depend on unsupported elements; review the actual saved vector.
Only sanitized bytes are persisted or returned. Studio also sanitizes local, uploaded,
remote and data-URL SVGs at the common asset-version boundary.

Local runs save images under `RENDERHAUS_MEDIA_DIR/images`. Lambda requires existing
`AWS_S3_BUCKET` or `REMOTION_APP_BUCKET_NAME` before live submission; the fal Lambda role
must have write/read access to `renderhaus-fal-images/`. S3 stores sanitized bytes with
correct content-type and returns a temporary asset URL. No vendor SVG URL is exposed as
an artifact. Studio registers durable versions and preserves training exclusion.

## Configuration and checks

Reuse existing `FAL_KEY` from environment/Secrets Manager and `FAL_DRY_RUN=true`.
No new secrets or dry-run flags. Existing bucket environment keys are now included in
fal's secret synchronization configuration; configure one for Lambda outputs.
There are 14 providers, 110 Gateway tools and 24 installed skills. Six fixture rows
(two Ideogram, four Recraft) activate, giving 122 active rows and seven skips of 129.
Remaining skips: HyperFrames overlays (1), cutaway capture (3), VLM judge (1), NLE import
(1), and unverified Seedance extension-length semantics (1).

Tests use mocked HTTP and scripted models with the installed Deep Agents 0.7.23 harness.
They cover dry-run, contracts, async result persistence, SVG sanitization, billing,
attached-image routing and native cost approval/reject/resume without double submission.
Comet E2E is **blocked**: the user states Comet is unavailable. No Studio browser actions,
live provider result rendering or visual quality pass is claimed. Record the blocker in
ignored `.renderhaus/e2e/` with `scripts/browser_e2e_hook.py record`. Live browser/artifact
validation and the Ideogram quality A/B remain pending under the no-paid-call restriction.

Final offline verification: **1,264 unittest tests run, 1,255 passed, nine skipped**
(baseline 1,240 run, 15 skipped). The 24 new specialist tests pass. Ruff, offline
`ci_check.py` with all dry-run flags, the Studio `tsc --noEmit -p .` check, and
`node studio/scripts/verify-image-specialists.cjs` pass. The temporary Studio
node_modules symlink was removed. Comet remains blocked, recorded under ignored
`.renderhaus/e2e/image-specialists.json`.

Pstack's Model the Domain principle led to strict endpoint-specific request models;
Type System Discipline keeps RGB objects and enum controls typed at the boundary.
Sequence Work into Verifiable Units led to tests-first and separate adapter, routing/Studio,
and evidence commits. Design/review lanes ran read-only while one owner serialized shared
registry, billing, policy and schema writes; the four throughput decisions are in the TSV.

## Changed files

- `.github/workflows/deploy.yml`
- `Dockerfile.agentcore`
- `agent/deep_agent/routing.py`
- `agent/deep_agent/routing_policy.json`
- `agent/deep_agent/runner.py`
- `agent/deep_agent/skills/image-gen/SKILL.md`
- `agent/deep_agent/skills/product-images/SKILL.md`
- `agent/deep_agent/skills/refinement/SKILL.md`
- `agent/gateway_executor.py`
- `agent/studio_agent_next.py`
- `configs/gateway/fal.tools.json`
- `docs/CAPABILITY_MAP.md`
- `docs/DEEP_AGENT.md`
- `docs/IMAGE_SPECIALISTS.md`
- `docs/SKILLS.md`
- `docs/image-specialists-decisions.tsv`
- `docs/provider-ladder-decisions.tsv`
- `docs/skills-drafts/ideogram.md`
- `docs/skills-drafts/recraft.md`
- `providers/catalog.py`
- `providers/contracts.py`
- `providers/fal/api.py`
- `providers/fal/images.py`
- `providers/registry.py`
- `providers/svg.py`
- `scripts/ci_check.py`
- `scripts/sync_secrets.py`
- `server/billing_rates.py`
- `server/studio.py`
- `server/studio_options.py`
- `server/studio_state.py`
- `studio/lib/canvas/model-labels.ts`
- `studio/lib/canvas/tool-registry.ts`
- `studio/scripts/verify-image-specialists.cjs`
- `tests/fixtures/skill_routing.json`
- `tests/test_capability_evidence.py`
- `tests/test_fal_provider.py`
- `tests/test_image_specialists.py`
- `tests/test_openai_images.py`
- `tests/test_skill_routing.py`
