---
name: image-gen
description: Generate or edit still images with GPT Image 2.5; specialize SVG and text-only edits.
metadata:
  include_tools: call_media_tool
  routing_tools: gpt_image25_t2i gpt_image25_edit recraft_v41_vector ideogram45_edit
  gateway_tools: OpenAI___generate_image OpenAI___edit_image Fal___ideogram_edit Fal___recraft_text_to_vector Fal___get_video_task
---

# Still images

Use `OpenAI___generate_image` for `gpt_image25_t2i` and `OpenAI___edit_image` for
`gpt_image25_edit`. Both use GPT Image 2.5 Sunburst by default. Seedream stays explicit-only.
Generation takes `prompt`, `size` (default 2K), `aspect_ratio`, `quality`, `background`,
`output_format`, `n` and `moderation`. Editing additionally requires `image_path_or_url` and
accepts up to 15 `reference_image_urls` for character/product consistency and an optional
`mask_path_or_url` for the first image. Resolve immutable handles at dispatch, preserving order.
Omit `input_fidelity`: Sunburst support is UNVERIFIED. A mask must match the first image's
format and dimensions and have an alpha channel. Discover the actual Gateway schema.
The 2K square preset is 2048x2048 and falls within the vendor's experimental large-size range.
Pre-call token counts and dollar totals are UNVERIFIED: disclose cost as unknown. Paid images
pause unless autonomous, under the existing spending cap. Spending approval is not visual approval.
Calls return completed saved images synchronously. There is no OpenAI polling tool. Open and
review every returned artifact before using it for animation. Dry-run creates no artifact.
OpenAI outputs are `training_eligible=false`; API no-training defaults do not grant output training rights.

Use `recraft_v41_vector` only when editable SVG/vector output is required. Raster tools cannot serve
that exception. Use `ideogram45_edit` only for pixel-preserving text-only changes on an
existing image, such as correcting a typo while keeping the rest. That exception is thin evidence.

`Fal___ideogram_edit` takes `prompt`, `image_url`, optional `reference_image_urls` (four,
or three with a mask), `mask_url`, `edit_precision` (high by default), `image_size` (auto),
`quality` (medium), `num_images` (1–8) and optional `seed`. Mask black edits and white
preserves; dimensions must match the source. High precision or a mask requires auto size.
`Fal___recraft_text_to_vector` takes `prompt`, named `image_size` (square_hd), preferred
RGB `colors`, optional RGB `background_color` and `enable_safety_checker` (true).
Describe style in the prompt; this endpoint has no style parameter. Custom sizes are omitted.
Both submit asynchronously and reuse `Fal___get_video_task`. Preserve the full returned
job ID. Poll to completion, then open every persisted image; an accepted job is incomplete.
SVGs require image/svg+xml and are sanitized before storage, with active content removed.
Ideogram costs $0.008/$0.03/$0.06/$0.22 per image at very_low/low/medium/high;
Recraft costs $0.30 per SVG. Read official fal pages 2026-10-09. Quotes cover all outputs.
Paid images pause unless autonomous, under the unchanged spend cap. Both models are
commercial service-terms APIs and training_eligible=false. Require input rights/consent.
Log Ideogram text-edit outcomes with ab_arm=ideogram45_edit. Compare against GPT edits
only with separately authorized work; do not generate a second paid image automatically.

A named Ideogram request without an existing image to edit uses the GPT generation default,
including posters and typography. It cannot create a text-only edit input from nothing.
A supplied existing Ideogram asset for Remotion rendering does not request image generation.
Explicit Seedream or Runway image requests belong in named-provider with disclosure.

Require rights to supplied media and review real-person likeness consent before dispatch.
Nonconsensual uses that confuse authenticity are prohibited by the vendor.
Reuse immutable references. Discover the selected schema. Explicit image editing uses its native source field; do not generate a replacement for an approved reference without review.
Review the actual still before any animation. Image spending approval does not approve its visual look.

Follow `read_studio_context.intent_route`. Selection uses the explicit requested provider/model,
then a named exception, then the capability default. Cost estimates support approval and disclosure;
they never select a provider. Pending defaults use only the policy's declared interim tool.
Disclose provider, model, estimated cost and `default`, `exception: <reason>`, `explicit request`,
or `interim default until <provider> lands` before each dispatch. Unknown prices stay unknown.
All paid video pauses for approval even in autonomous runs when `premium_video_approval` is enabled.
Paid non-video retains the existing non-autonomous approval and autonomous spend cap.

Search Gateway for the selected built tool and use its exact schema through the matching role.
Pending aliases are routing identifiers, not Gateway endpoints. Never invent a tool or change a
DRY_RUN flag to satisfy a request. Submit once. Poll only asynchronous providers using the returned job ID.
A queued job or dry-run is incomplete media. Open/play the actual saved artifact before delivery.
Record explicit customer visual acceptance/rejection with `record_media_outcome` and the saved call ID.
A spending approval is not visual acceptance. Training eligibility follows provenance and the existing
Wan training hook; these routing instructions cannot grant training rights.
