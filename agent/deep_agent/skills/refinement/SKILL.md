---
name: refinement
description: Refine an existing image, video, audio asset, or assembled edit without repeating successful generation.
metadata:
  include_tools: call_media_tool call_audio_tool call_editor_tool
  gateway_tools: Fal___video_to_video Luma___modify_video Runway___video_to_video Seedream___image_to_image
---

# Refinement

Read read_studio_context and identify the exact referenced asset version and requested change.
Read the matching product-images, audio, or final-assembly skill. Search Gateway for the
specific edit tool and use its exact schema. Prefer Seedream___image_to_image for an image
change. Reuse all unaffected assets. Prefer a Remotion timeline change for trim, timing,
caption, ordering, or soundtrack changes. Read [edit existing video](../edit-v2v/SKILL.md) when visual content must change.
Follow the edit ladder: Fal___video_to_video for Draft, Luma___modify_video for Standard,
and Runway___video_to_video for Premium or faithful plate edits. Confidential stays Wan.
Record explicit customer review with record_media_outcome. Rejected shots retry only on
Wan with retained features; explain a blocked retry. Generate a replacement Standard
shot only when the requested change cannot use the retained clip. Use existing renderhaus-asset:// handles instead of paths or
invented URLs. Check saved provider jobs before retrying. Keep the original version available.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
