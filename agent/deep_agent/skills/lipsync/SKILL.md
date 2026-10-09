---
name: lipsync
description: Put new audio on existing footage with sync-3; use HeyGen Avatar V for long presenters.
metadata:
  include_tools: call_media_tool
  routing_tools: sync3_lipsync heygen_avatar_v
---

# Lip sync

Use `sync3_lipsync` for re-voicing/dubbing existing footage. Use `heygen_avatar_v` for presenter or
digital-twin videos over 30 seconds. Both providers are pending, with no built interim. Require consent
for real faces and voices. Speech creation alone cannot animate a face. Synthetic generated dialogue
belongs in t2v/i2v instead. Prepare user audio or authorized TTS before the pending video step.
Retired LivePortrait/LatentSync require non-commercial InsightFace weights; never load them.
Evidence is thin. Inspect lip timing and actual playback once the provider is built.

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
