---
name: storyboard-shots
description: Turn a storyboard into consistent shots using still-first image-to-video generation.
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___vidu_q4_i2v Fal___vidu_q4_r2v Fal___get_video_task Fal___image_to_video Seedance___get_video_task Seedance___image_to_video Seedream___image_to_image
---

# Storyboard shots

Read read_studio_context. Ask planner for shot durations, framing, product continuity, and
one concise action per shot. Save the storyboard to a project file.
Search x_amz_bedrock_agentcore_search for Seedream text_to_image/image_to_image.
Use call_media_tool to create one cheap keyframe per shot. Reuse the approved product reference
through Seedream___image_to_image. Preview these stills and apply requested corrections before
video. Read [image to video](../i2v/SKILL.md). Animate approved still asset handles with
the host-selected Standard route, usually Seedance___image_to_video with image_path_or_url,
then poll Seedance___get_video_task using saved job IDs. Draft uses Fal___image_to_video
with first_frame_url. Read product-images for still routing and confidentiality limits.
Preserve capability filters, disclose the choice and cost, and record explicit shot reviews.
Reuse successful shots. Read final-assembly to assemble the resulting clips, not the previews.

For a Vidu Q4 route, read [Vidu Q4](../vidu-q4/SKILL.md). Use
`Fal___vidu_q4_i2v` with `image_url` for a first frame, or `Fal___vidu_q4_r2v` with
`reference_image_urls` and optional `reference_audio_urls` for subject and voice references.
Use native `duration` (3 through 16), case-sensitive resolutions through `4K`, and
`audio=true` on R2V when sound is required. I2V audio is implicit. Q4 is Standard,
never confidential, and never training-eligible. Poll the saved `Fal___get_video_task` job.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
