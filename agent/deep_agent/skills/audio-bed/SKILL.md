---
name: audio-bed
description: Create narration, voice clones, music or SFX with capability defaults and text-only SFX exceptions.
metadata:
  include_tools: call_audio_tool call_media_tool
  routing_tools: eleven_v4_turbo voices_ivc_create mureka_v95 mirelo_v2a elevenlabs_sfx_v2
  gateway_tools: Fal___mirelo_v2a Fal___get_video_task Mureka___generate_song Mureka___generate_instrumental Mureka___get_music_task Mureka___list_mureka_models ElevenLabs___music_compose ElevenLabs___text_to_sound_effects_convert ElevenLabs___text_to_speech_convert ElevenLabs___voices_ivc_create
---

# Audio bed

Narration defaults to `eleven_v4_turbo`, mapped to `ElevenLabs___text_to_speech_convert`.
TTS accepts only priced `model_id` values `eleven_v4_turbo` and `eleven_v4` across conversion,
timestamps and HTTP streaming. Prefer `eleven_v4_turbo`; omit `model_id` to use the configured
`ELEVENLABS_TTS_MODEL` default, which is `eleven_v4_turbo` when unset. An unpriced model returns
a failed tool result naming allowed IDs before approval or provider access. Correct the model
from that list and discover the schema again if needed. An invalid configured default must
be corrected by the operator; never change provider configuration yourself.
The operator verified `eleven_v4_turbo` through the model listing and a successful TTS HTTP call
on 2026-10-09. Official TTS documentation supports a configured `model_id` on the conversion
endpoint. `ELEVENLABS_DRY_RUN` controls dry-run behavior. This evidence does not verify other
model/endpoint combinations, including dialogue variants.
Use authorized `voice_id` and `text`; never infer a voice ID from its display name.
For independent narration, look up the authorized voice and dispatch speech while the video
job is running. Launch audio and media tasks together or batch their generation calls before
a blocking video status check. Only final assembly waits for both completed artifacts.
Voice cloning defaults to `voices_ivc_create`, mapped to `ElevenLabs___voices_ivc_create`.
Require speaker consent and rights to all samples; do not imply the IVC tool provides PVC.

Music defaults to `mureka_v95` through Mureka V9.5 on fal. Use `Mureka___generate_instrumental`
for beds, instrumentals and requests without vocals; use `Mureka___generate_song` for songs.
Supply `lyrics` for lyrics-to-song or `prompt` for prompt-to-song; `prompt` with lyrics controls style.
`styles` is prompt-only and `gender` is lyrics-only. Discover the exact schema before dispatch.
Poll `Mureka___get_music_task` with the saved handle and `download=true`. Preserve `song_id`,
`duration_ms` and timed `lyrics_sections` for a later lyrics video. Dry-run creates no media.
`ElevenLabs___music_compose` remains explicit-only when requested by name.
Paid audio pauses unless autonomous; the existing spend cap still applies. Outputs have commercial
API usage rights but no verified training grant. MUREKA_DRY_RUN and FAL_DRY_RUN default true.
Video-synchronized foley defaults to `mirelo_v2a` through `Fal___mirelo_v2a` on fal.
The manager or media role uses `call_media_tool` for this video operation and `Fal___get_video_task`.
The audio role returns this step to the manager; it handles text-only SFX through `call_audio_tool`.
Use a silent, edited or assembled source clip. Generated Wan/Seedance shots already have native audio.
Supply `video_url` as authorized HTTPS media or a current Studio asset handle and match `duration`
to the measured clip length, 1-60 seconds. Above 10 seconds fal uses sliding-window generation.
Use optional `text_prompt` to describe sounds such as footsteps, impacts or ambience, not visual edits.
Renderhaus defaults `num_samples` to 1, while fal defaults to 2. Samples 2-4 are dry-run-only;
their billing is UNVERIFIED, so disclose cost unknown and never promise a live result.
Optional `seed` controls repeatability; -1 or null selects random generation.
The official endpoint returns videos with audio tracks, not a separate audio file.
Submit once after cost approval, save `job_id`, then poll with `download=true`.
The poll exposes all `videos` and the first variant as `video_url` and `output_path`.
Play the saved MP4 and check synchronization before delivery. A preview or queued job is incomplete.
FAL_DRY_RUN defaults true. Commercial fal API terms apply; outputs are not training eligible.
All paid Mirelo video pauses with cost even autonomous under the paid-video approval policy.
SFX evidence is thin. A/B Mirelo against ElevenLabs text-described SFX on the same clips before
relying on picture synchronization quality; obtain normal approvals for each paid comparison.
A text-only sound effect
uses the built `elevenlabs_sfx_v2` exception through `ElevenLabs___text_to_sound_effects_convert`.
Use native `text` and supported `duration_seconds`. Text-only SFX cannot synchronize to source picture.
For script-only lip sync, prepare authorized ElevenLabs speech, then follow the lipsync skill
for consented sync-3 on existing footage. Use the lyrics-video skill for Mureka lyric/karaoke videos. Long presenters use the HeyGen skill.
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
