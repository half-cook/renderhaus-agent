---
name: audio-bed
description: Create narration, voice clones, music or SFX with capability defaults and text-only SFX exceptions.
metadata:
  include_tools: call_audio_tool
  routing_tools: eleven_v4_turbo voices_ivc_create mureka_v95 mirelo_v2a elevenlabs_sfx_v2
  gateway_tools: ElevenLabs___music_compose ElevenLabs___text_to_sound_effects_convert ElevenLabs___text_to_speech_convert ElevenLabs___voices_ivc_create
---

# Audio bed

Narration defaults to `eleven_v4_turbo`, mapped to `ElevenLabs___text_to_speech_convert`.
The operator verified `eleven_v4_turbo` through the model listing and a successful TTS HTTP call
on 2026-10-09. Official TTS documentation supports a configured `model_id` on the conversion
endpoint. `ELEVENLABS_DRY_RUN` controls dry-run behavior. This evidence does not verify other
model/endpoint combinations, including dialogue variants.
Use authorized `voice_id` and `text`; never infer a voice ID from its display name.
Voice cloning defaults to `voices_ivc_create`, mapped to `ElevenLabs___voices_ivc_create`.
Require speaker consent and rights to all samples; do not imply the IVC tool provides PVC.

Music defaults to pending `mureka_v95`. Its declared interim is `ElevenLabs___music_compose`
with `prompt` and `music_length_ms`. Disclose that ElevenLabs is temporary, or explicit-only by name.
Video-synchronized foley defaults to `mirelo_v2a`, pending with no interim. A text-only sound effect
uses the built `elevenlabs_sfx_v2` exception through `ElevenLabs___text_to_sound_effects_convert`.
Use native `text` and supported `duration_seconds`. Text-only SFX cannot synchronize to source picture.
For script-only lip sync, prepare authorized ElevenLabs speech, then follow the lipsync skill
for consented sync-3 on existing footage. Long HeyGen presenters and lyrics-video remain pending.
Speech alone is not a lipsync video.

Fish Audio is named-only. MMAudio is retired because its weights are non-commercial; ACE-Step is
retired from the quality-first map. Do not install or load their weights as a workaround.
Create a short speech sample before a long recording. Match approved audio to picture and preserve
successful handles. Use final-assembly for fades/timing/mixing instead of paid regeneration.

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
