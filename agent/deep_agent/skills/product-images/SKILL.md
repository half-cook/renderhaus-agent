---
name: product-images
description: Generate images or product shots, or edit a referenced still while preserving the product.
metadata:
  include_tools: call_media_tool
---

# Product images

Read read_studio_context and locate product reference asset version handles.
Search x_amz_bedrock_agentcore_search for Seedream image generation or editing schemas.
For a new still, call_media_tool with Seedream___text_to_image. For a product reference or
refinement, use Seedream___image_to_image with the existing renderhaus-asset:// version.
Start with one inexpensive still using the requested aspect ratio. Inspect the returned
asset description and report the preview. Keep identity and packaging accurate. Generate
additional angles only when the brief needs them. Do not start paid video for an image request.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
