---
name: refinement
description: Refine an existing image, video, audio asset, or assembled edit without repeating successful generation.
metadata:
  include_tools: call_media_tool call_audio_tool call_editor_tool
---

# Refinement

Read read_studio_context and identify the exact referenced asset version and requested change.
Read the matching product-images, audio, or final-assembly skill. Search Gateway for the
specific edit tool and use its exact schema. Prefer Seedream___image_to_image for an image
change. Reuse all unaffected assets. Prefer a Remotion timeline change for trim, timing,
caption, ordering, or soundtrack changes. Generate a replacement Seedance shot only if the
visual content must change. Use existing renderhaus-asset:// handles instead of paths or
invented URLs. Check saved provider jobs before retrying. Keep the original version available.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
