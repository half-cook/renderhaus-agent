---
name: video-short
description: Create a text-to-video ad or short with affordable still previews and a final MP4.
metadata:
  include_tools: call_media_tool call_audio_tool call_editor_tool
  gateway_tools: Fal___get_video_task Fal___image_to_video Fal___text_to_video Seedance___get_video_task Seedance___image_to_video Seedance___text_to_video Seedream___text_to_image
---

# Video short

Read the brief and read_studio_context. Use planner for a short shot plan when useful.
Search x_amz_bedrock_agentcore_search for Seedream text_to_image and Fal text_to_video.
Use call_media_tool with Seedream___text_to_image for a cheap direction preview first.
After the preview meets the brief and required approval, call Fal___text_to_video for
short clips. For a still-led scene, use Fal___image_to_video with first_frame_url instead.
Poll the returned job with Fal___get_video_task; reuse its exact ID. Read
[text to video](../t2v/SKILL.md) for native arguments and premium-provider approval.
For an explicit Seedance request, use Seedance___text_to_video or Seedance___image_to_video
and poll Seedance___get_video_task. Read the audio skill if sound is needed.
Read final-assembly and assemble clips through Remotion. Deliver only the successful MP4.
Avoid multiple video variants unless requested. Never replace a running job.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
