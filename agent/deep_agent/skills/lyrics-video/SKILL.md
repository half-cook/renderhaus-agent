---
name: lyrics-video
description: Make timed lyric/karaoke video from supplied music, or generate the song with Mureka first.
metadata:
  include_tools: call_audio_tool call_editor_tool
  routing_tools: mureka_lyrics_video mureka_v95
  gateway_tools: ElevenLabs___music_compose
---

# Lyrics video

Use `mureka_lyrics_video` for supplied music. Its provider is pending with no built lyrics-video
interim. When the user asks for a new song, select `mureka_v95` first; its declared current music
interim is ElevenLabs. Preparing a song does not create a lyrics video. Keep these two steps and
approvals distinct. Evidence of timing and playback remains pending until the video provider lands.
Mureka commercial/training terms need verification before enabling the future adapter.

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
