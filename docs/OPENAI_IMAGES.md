# OpenAI Images provider

GPT Image 2.5 Sunburst is the still-image and image-edit default. Explicit requests take priority,
then capability exceptions, then the default. Seedream stays explicit-only. Recraft vector output
and Ideogram text-only edits remain pending `feat/image-specialists`. Project confidentiality does
not change selection. No price tiers select a model.

## Tools and inputs

| Gateway tool | Routing ID | Inputs |
| --- | --- | --- |
| `OpenAI___generate_image` | `gpt_image25_t2i` | Required `prompt`; optional `model`, `size`, `aspect_ratio`, `quality`, `background`, `output_format`, `output_compression`, `n`, `moderation` |
| `OpenAI___edit_image` | `gpt_image25_edit` | Generation inputs plus required `image_path_or_url`, optional `reference_image_urls` and `mask_path_or_url` |

The alias `gpt-image-2.5-sunburst` and snapshot `gpt-image-2.5-sunburst-2026-09-08` are verified.
Generation uses JSON POST `/v1/images/generations`. Editing uses JSON POST `/v1/images/edits`
with ordered `images` objects and an optional `mask` object. The primary image comes first,
followed by at most 15 references. Sources accept HTTPS URLs, PNG/JPEG/WebP data URLs,
immutable Renderhaus handles resolved at dispatch, or files under `RENDERHAUS_MEDIA_DIR`.
Local inputs are encoded in memory. Remote sources remain URLs; the provider validates their bytes.

Requests are validated by a strict Pydantic contract before paid dispatch. The prompt limit is
32000 characters and `n` is an integer from 1 through 10. Output is base64 and persists as local
images under `RENDERHAUS_MEDIA_DIR/images` locally, or in the existing `AWS_S3_BUCKET`
(`REMOTION_APP_BUCKET_NAME` fallback) with fetchable image URLs. Live Lambda calls require
that bucket before sending a paid request. The response includes a local `output_path` or an S3 `image_url`, all `images`,
usage when provided, and `actual_cost_usd` when usage detail is complete. These calls are
synchronous: no submit/poll tool is added. Failed or incomplete base64 responses publish no artifact.
HTTP errors omit raw provider messages. Each returned image needs visual review before animation.

The default `size=2K` maps by aspect ratio: `1:1` to `2048x2048`, `16:9` to `2560x1440`, and
`9:16` to `1440x2560`. Square 2K is in the documented experimental large-size range.
`1K`, `auto`, and custom dimensions are supported. Custom edges must be multiples of 16, at most
3840, with aspect ratios between 1:3 and 3:1 and pixel counts from 655360 to 8294400.

Quality accepts `low`, `medium`, `high` (default), `xhigh`, `max`, or `auto`. Background accepts
`auto`, `opaque`, or `transparent`; transparent output requires PNG or WebP. Formats are PNG
(default), JPEG, and WebP. Compression from 0 to 100 applies only to JPEG/WebP. Moderation is
`auto` (default) or `low`. `input_fidelity` support for Sunburst is **UNVERIFIED**, so the field is
omitted and rejected. Masks need an alpha channel and the first image's format and dimensions.
Mask guidance is not a promise of pixel-exact preservation.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | none | Reuses the shared OpenAI key through environment or Secrets Manager |
| `OPENAI_IMAGES_DRY_RUN` | `true` | No HTTP request, source read, artifact, or billed generation |
| `OPENAI_IMAGES_MODEL` | `gpt-image-2.5-sunburst` | Configurable model; unverified IDs remain dry-run only |
| `OPENAI_IMAGES_TOOL_COST_CENTS_JSON` | unset | Optional operator quote per output image, keyed by `generate_image` or `edit_image` |

The provider catalogue includes these variables for the existing `scripts/sync_secrets.py` path.
No separate image key is needed. Operator quotes are not official per-image prices; without one the $0.20 estimate below applies. Actual token usage is reported; wallet reconciliation to actual usage
remains TODO. API access and organization verification have not been tested.

## Pricing and approval

Official standard token rates, read **2026-10-09**, are $5/M text input, $8/M image input,
and $30/M image output. Complete observed usage is rated without Responses cached discounts.
Dry-run costs zero. OpenAI publishes only token rates and a calculator widget (pricing page and
image-generation guide, read **2026-10-09**), not a flat per-image price, so the approval card uses a
per-image **estimate of $0.20** (the product-directed list price; not a verified tariff) plus the 30 %
platform fee, i.e. **$0.26 per image** (`n` images multiply it). An operator quote in
`OPENAI_IMAGES_TOOL_COST_CENTS_JSON` replaces the $0.20 for its tool. Actual token usage is still
reported and rated at the token rates above; higher quality (`xhigh`/`max`) or large sizes can cost
more than the estimate. TODO: reconcile the wallet to observed usage.

Paid image calls pause unless autonomous. Existing exempt tools and the autonomous spend cap
are unchanged. Every paid video step still pauses, including autonomous runs. An unknown price
cannot satisfy a finite spend cap. Spending approval does not imply visual approval.

## Licence and provenance

Both verified model IDs use the proprietary OpenAI Services Agreement, with commercial API use
and customer output ownership subject to the agreement. No weights or third-party code are
included. `training_eligible=false` is a conservative pipeline decision: section 3.3(e) restricts
competing AI development from outputs with defined exceptions. Renderhaus has not established
that its training pipeline fits an exception. This is distinct from API inputs not being used for
OpenAI training by default. Vendor retention policies still apply.

Input rights are required. OpenAI usage policies prohibit using real likenesses without consent
in ways that confuse authenticity. The image skill requires consent review for such references.
Recraft and Ideogram have no live adapter here, so their licence and API checks remain pending.

## Sources and validation

All sources below were read on **2026-10-09**:

- [Sunburst model IDs and token rates](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst)
- [Generation API contract](https://developers.openai.com/api/reference/resources/images/methods/generate)
- [JSON multi-image edits and masks](https://developers.openai.com/api/reference/resources/images/methods/edit)
- [Image sizes and generation guidance](https://developers.openai.com/api/docs/guides/image-generation)
- [Official pricing](https://developers.openai.com/api/docs/pricing)
- [OpenAI Services Agreement](https://openai.com/policies/services-agreement/)
- [API data controls](https://developers.openai.com/api/docs/guides/your-data)
- [Usage policies and likeness consent](https://openai.com/policies/usage-policies/)
- [Supported countries, including the US](https://developers.openai.com/api/docs/supported-countries)

The adapter tests use mocked HTTP and no provider keys. Routing fixtures exercise built defaults,
explicit Seedream, pending specialists, and still-before-video sequencing. Deep Agents tests use
the installed 0.7.23 graph to check approval/resume and rejection without live dispatch.
The eight GPT readiness rows are active; the 38 existing dependency skips retain their reasons.
Inventory is 10 providers, 89 Gateway tools, and 24 skills.

Comet browser E2E is **blocked**: Comet cannot be controlled in this environment and the task
prohibits live provider calls. This is not a browser pass or evidence of live output. The ignored
`.renderhaus/e2e/openai-images-browser.json` report records the blocker through the project hook.
See [the decisions file](openai-images-decisions.tsv) for remaining TODOs.
