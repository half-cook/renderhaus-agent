---
name: image-gen
description: Generate or edit still images with GPT Image 2.5; specialize SVG and text-only edits.
metadata:
  include_tools: call_media_tool
  routing_tools: gpt_image25_t2i gpt_image25_edit recraft_v41_vector ideogram45_edit
  gateway_tools: Seedream___image_to_image Seedream___text_to_image
---

# Still images

Use `gpt_image25_t2i` for generation and `gpt_image25_edit` for editing. Both are pending;
the declared interims are `Seedream___text_to_image` and `Seedream___image_to_image`.
The image default size stays 2K. Its current Seedream price can be unknown; never quote a 1K price for 2K.
Use `recraft_v41_vector` only when editable SVG/vector output is required. Raster tools cannot serve
that pending exception. Use `ideogram45_edit` only for pixel-preserving text-only changes on an
existing image, such as correcting a typo while keeping the rest. That exception is thin evidence.

A named Ideogram request without an existing image to edit uses the GPT generation default,
including posters and typography. It cannot create a text-only edit input from nothing.
A supplied existing Ideogram asset for Remotion rendering does not request image generation.
Explicit Seedream or Runway image requests belong in named-provider with disclosure.

Reuse immutable references. Discover the selected schema. Seedream editing uses
`image_path_or_url`; do not generate a replacement for an approved reference without review.
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
DRY_RUN flag to satisfy a request. Submit once, preserve the returned job ID, and poll the same job.
A queued job or dry-run is incomplete media. Open/play the actual saved artifact before delivery.
Record explicit customer visual acceptance/rejection with `record_media_outcome` and the saved call ID.
A spending approval is not visual acceptance. Training eligibility follows provenance and the existing
Wan training hook; these routing instructions cannot grant training rights.
