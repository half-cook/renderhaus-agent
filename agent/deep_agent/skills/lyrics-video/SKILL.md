---
name: lyrics-video
description: Make timed lyric/karaoke video from supplied music, or generate the song with Mureka first.
metadata:
  include_tools: call_audio_tool call_editor_tool
  routing_tools: mureka_lyrics_video mureka_v95
  gateway_tools: Mureka___generate_song Mureka___generate_instrumental Mureka___get_music_task Mureka___generate_lyrics_video Mureka___get_video_task Mureka___list_mureka_models ElevenLabs___text_to_speech_convert ElevenLabs___music_compose
---

# Lyrics video

Use `mureka_lyrics_video`, mapped to `Mureka___generate_lyrics_video` on fal.
For a new song, first select `mureka_v95` through `Mureka___generate_song` (or
`Mureka___generate_instrumental` when requested). Submit once and poll
`Mureka___get_music_task` with `download=true`. Preserve the returned `song_id` and
timed `lyrics_sections`. Then submit the lyrics video using that completed `song_id`.
Music and video are separate calls, quotes and approvals. An explicit ElevenLabs music
request uses `ElevenLabs___music_compose`, but its audio must be uploaded/prepared before
Mureka video generation. Do not pass an audio URL as a song ID.

Supplied songs require a same-transport `song_id`, or an existing `upload_audio_id` with
purpose audio. Raw audio upload and lyric recognition are not wired: if the user supplies
only an audio file or ElevenLabs TTS output, prepare authorized speech with
`ElevenLabs___text_to_speech_convert` when asked, then explain that obtaining the Mureka
upload/recognized-lyrics ID remains blocked. Never fabricate IDs or claim this path completed.
Do not regenerate the user's supplied song to bypass that missing step.

Use the vendor's `layout_1` through `layout_7` and `aspect_ratio` (16:9, 9:16, 3:4 or 4:3).
Default 9:16; honor the requested aspect. `cover_url` cannot accompany layout_1.
Choose either paired 1-based `lyrics_start_row`/`lyrics_end_row`, or paired millisecond
`selection_start`/`selection_end`. The endpoint uses recognized/generated timed lyrics;
it does not accept arbitrary timed-row JSON or an audio URL plus a lyrics string.
Keep lyrics legible, respect safe areas, and use final assembly for additional overlays.

Always pause with a cost estimate before paid lyrics video, including autonomous runs and
when the global premium-video switch is off. Poll `Mureka___get_video_task` with
`download=true`, inspect the saved MP4 and check lyric timing and playback before delivery.
A queued job or dry-run preview is incomplete. MUREKA_DRY_RUN and FAL_DRY_RUN default true.
Paid API commercial usage is documented; outputs stay training_eligible=false because
commercial distribution rights do not grant model-training rights. Cloning/reference vocals
are outside this adapter; all source and likeness/voice rights must be authorized.

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
