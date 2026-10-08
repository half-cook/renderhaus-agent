---
name: storyboard-shots
description: Turn a storyboard into consistent shots using still-first image-to-video generation.
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___get_video_task Fal___image_to_video Seedance___get_video_task Seedance___image_to_video Seedream___image_to_image
---

# Storyboard shots

Read read_studio_context. Ask planner for shot durations, framing, product continuity, and
one concise action per shot. Save the storyboard to a project file.
Search x_amz_bedrock_agentcore_search for Seedream text_to_image/image_to_image.
Use call_media_tool to create one cheap keyframe per shot. Reuse the approved product reference
through Seedream___image_to_image. Preview these stills and apply requested corrections before
video. Read [image to video](../i2v/SKILL.md). Animate approved still asset handles with
Fal___image_to_video using first_frame_url, then poll Fal___get_video_task using saved job IDs.
For an explicit Seedance request, use Seedance___image_to_video with image_path_or_url and
poll Seedance___get_video_task. Apply the shared policy for any premium provider step-up.
Reuse successful shots. Read final-assembly to assemble the resulting clips, not the previews.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
