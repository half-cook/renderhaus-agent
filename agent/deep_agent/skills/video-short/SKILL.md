---
name: video-short
description: Create a text-to-video ad or short with affordable still previews and a final MP4.
metadata:
  include_tools: call_media_tool call_audio_tool call_editor_tool
---

# Video short

Read the brief and read_studio_context. Use planner for a short shot plan when useful.
Search x_amz_bedrock_agentcore_search for Seedream text_to_image and Seedance text_to_video.
Use call_media_tool with Seedream___text_to_image for a cheap direction preview first.
After the preview meets the brief and required approval, call Seedance___text_to_video for
short clips. For a still-led scene, use Seedance___image_to_video instead. Poll the returned
job with Seedance___get_video_task; reuse its exact ID. Read the audio skill if sound is needed.
Read final-assembly and assemble clips through Remotion. Deliver only the successful MP4.
Avoid multiple video variants unless requested. Never replace a running job.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
