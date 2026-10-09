---
name: video-short
description: Plan a short film/ad using approved stills, capability-map shots, audio and Remotion assembly.
metadata:
  include_tools: call_media_tool call_audio_tool call_editor_tool
  routing_tools: gpt_image25_t2i wan3_t2v wan3_i2v seedance25_t2v seedance25_i2v remotion_render
  gateway_tools: OpenAI___generate_image OpenAI___edit_image
---

# Video short

Read the brief and Studio context. Save a short shot plan with one action per shot.
Read image-gen/still-then-video for visual approval, t2v/i2v for default/exception generation,
audio-bed for authorized sound, and final-assembly for the final MP4. Each selected capability
uses its declared interim while pending. Do not replace a failed shot with an unrelated provider.
Reuse accepted assets, preserve saved jobs and record explicit customer shot reviews.
Do not request multiple paid variants unless the brief requires them.

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
