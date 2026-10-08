---
name: audio
description: Create voiceover, music, speech, or sound effects with ElevenLabs or an available Fish Audio target.
metadata:
  include_tools: call_audio_tool
---

# Audio

Read read_studio_context and the planned durations. Search x_amz_bedrock_agentcore_search for
ElevenLabs speech, music, or sound effects, or Fish Audio speech. Use exact returned schemas.
Use call_audio_tool with ElevenLabs___text_to_speech_convert for narration,
ElevenLabs___music_compose for music, and ElevenLabs___text_to_sound_effects_convert for SFX.
If Gateway exposes FishAudio___generate_speech, use that for Fish Audio speech. If absent,
report its absence and use the available speech provider. Never invent a Gateway target.
Use a short sample before a long recording. Match duration to shots. Poll any asynchronous
job with its discovered status tool and saved ID. Reuse finished audio and avoid paid
regeneration for a timing change that Remotion can solve. Use only authorized voices.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
