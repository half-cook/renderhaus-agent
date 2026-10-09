---
name: refinement
description: Refine retained media or edits through capability defaults without repeating successful work.
metadata:
  include_tools: call_media_tool call_audio_tool call_editor_tool
  routing_tools: ideogram45_edit recraft_v41_vector gpt_image25_edit seedance25_edit seedance25_extend remotion_render
  gateway_tools: Seedance___extend_video Seedance___edit_video Seedance___get_video_task Fal___get_video_task OpenAI___generate_image OpenAI___edit_image Fal___ideogram_edit Fal___recraft_text_to_vector
---

# Refinement

Identify the exact source version and requested change. Reuse all unaffected assets and saved jobs.
Use image-gen for image changes, edit-v2v for generative footage changes, audio-bed for sound, and
final-assembly for trim/timing/caption/order changes. Choose the matching capability's default or
exception. Seedance 2.5 is the permanent footage-edit and extend default.
Explicit Wan 3.0 or demoted provider requests use named-provider with disclosure.
Wan edit/extend remain blocked for live customer use under Alibaba preview terms. Read edit-v2v
for measurements, billing and real-person refusal. Follow the host route and preserve its cost approval.
Keep the original version available and record explicit customer review. The existing registered
Wan training-retry path remains governed by its host provenance checks.

Follow `read_studio_context.intent_route`. Selection uses the explicit requested provider/model,
then a named exception, then the capability default. Cost estimates support approval and disclosure;
they never select a provider. Edit/extend have no interim or automatic provider fallback.
Disclose provider, model, estimated cost and `default`, `exception: <reason>` or `explicit request`
before each dispatch. Unknown prices stay unknown.
All paid video pauses for approval even in autonomous runs when `premium_video_approval` is enabled.
Paid non-video retains the existing non-autonomous approval and autonomous spend cap.

Search Gateway for the selected built tool and use its exact schema through the matching role.
Pending aliases are routing identifiers, not Gateway endpoints. Never invent a tool or change a
DRY_RUN flag to satisfy a request. Submit once, preserve the returned job ID, and poll the same job.
A queued job or dry-run is incomplete media. Open/play the actual saved artifact before delivery.
Record explicit customer visual acceptance/rejection with `record_media_outcome` and the saved call ID.
A spending approval is not visual acceptance. Training eligibility follows provenance and the existing
Wan training hook; these routing instructions cannot grant training rights.
