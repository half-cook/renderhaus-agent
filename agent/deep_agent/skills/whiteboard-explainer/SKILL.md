---
name: whiteboard-explainer
description: Plan a whiteboard explainer with requested voiceover, Remotion. Silent graphic explainers use knowledge-explainer.
metadata:
  remotion_backend: configured
  remotion_features: clip_timing transitions fit_position scale motion titles captions audio_mix canvas encoding
  include_tools: call_editor_tool call_audio_tool
  routing_tools: remotion_render eleven_v4_turbo
  gateway_tools: Remotion___get_render_progress Remotion___render_timeline ElevenLabs___text_to_speech_convert
---

# Whiteboard explainer

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

The configured Remotion backend must support every requested feature. Unsupported features refuse before media I/O
or AWS submission. Crop/pad reframing requires local/worker; fitted font/box overlays require
Lambda overlay contract version 2 or local/worker. Use named motion presets; arbitrary render
keyframes, per-word kinetic typography and custom components remain unavailable.
