---
name: final-assembly
description: Assemble existing assets into a final Remotion video and verify the rendered MP4 result.
metadata:
  include_tools: call_editor_tool
---

# Final assembly

Read read_studio_context and project shot plans. Reuse existing managed asset versions.
Search x_amz_bedrock_agentcore_search for Remotion render_timeline and get_render_progress.
Build the typed timeline according to the returned schema. Include ordered clips, precise
durations, audio, captions, and the requested aspect ratio. Call call_editor_tool with
Remotion___render_timeline once. Save render_id, bucket_name, and output_key unchanged.
Call Remotion___get_render_progress with those identifiers. The host polls the same render.
If waiting times out, preserve the ID and describe pending work. Never start a replacement
because a poll failed. Deliver a video only when a successful poll provides the final MP4.
Report a dry-run timeline as a preview and an incomplete export.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
