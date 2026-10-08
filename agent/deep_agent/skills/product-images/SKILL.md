---
name: product-images
description: Generate images or product shots, or edit a referenced still while preserving the product.
metadata:
  include_tools: call_media_tool
  gateway_tools: Runway___get_runway_task Runway___image_to_image Runway___text_to_image Seedream___image_to_image Seedream___text_to_image
---

# Product images

Read read_studio_context and locate product reference asset version handles.
Search x_amz_bedrock_agentcore_search for Seedream image generation or editing schemas.
For a new still, call_media_tool with Seedream___text_to_image. For a product reference or
refinement, use Seedream___image_to_image with the existing renderhaus-asset:// version.
Start with one inexpensive still using the requested aspect ratio. Inspect the returned
asset description and report the preview. Keep identity and packaging accurate. Generate
additional angles only when the brief needs them. Do not start paid video for an image request.

For an explicit Gen-4 Image request, use Runway___text_to_image with model="gen4_image",
or Runway___image_to_image with the source reference and prompt. Image Turbo requires
a source image and model="gen4_image_turbo" on the reference tool. Runway uses ratio.
Poll Runway___get_runway_task at least five seconds apart and save the completed image.
Use required Runway attribution in applicable interfaces. Do not treat a queued image as a still.
Seedream and Runway outputs are not continuity-training inputs.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
