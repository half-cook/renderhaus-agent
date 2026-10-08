---
name: audio-bed
description: Add narration, music, or sound effects with built ElevenLabs tools or available Fish Audio speech.
metadata:
  include_tools: call_audio_tool
  gateway_tools: ElevenLabs___text_to_speech_convert ElevenLabs___music_compose ElevenLabs___text_to_sound_effects_convert FishAudio___generate_speech
---

# Audio bed

Read `read_studio_context` and the planned shot durations.
Search Gateway for the concrete operation and use `call_audio_tool` with the exact schema.
`elevenlabs_tts` maps to `ElevenLabs___text_to_speech_convert`. Use authorized `voice_id`
and `text`; do not infer a voice ID from its display name.
`fish_audio_tts` maps to `FishAudio___generate_speech` only when Gateway exposes that
conditional target. It requires `text` and optionally accepts `voice`, `output_format`,
and `model`. Fish Audio is not in the active provider catalog. Report an absent target
and use available speech only within the user's provider preferences.

For a generic music bed, use `ElevenLabs___music_compose` with `prompt` and
`music_length_ms`. For sound effects, use `ElevenLabs___text_to_sound_effects_convert`
with `text` and supported `duration_seconds`. MMAudio video-synchronized effects and
ACE-Step music are provider-pending drafts. Never reinterpret a named pending provider
as built ElevenLabs support. A separate video-to-audio model is not installed.

Create a short speech sample before a long recording. Match approved audio to picture.
Preserve successful audio handles and use [final assembly](../final-assembly/SKILL.md)
for fades, timing, and mixing rather than regenerating sound for an edit-only change.
Use authorized voices and input rights. Fish Audio API availability does not grant rights
to self-host Fish Speech weights. Audio-provider outputs are not continuity training inputs.
Report unconfirmed billing as unknown using `server.billing_rates.cost_for`.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
