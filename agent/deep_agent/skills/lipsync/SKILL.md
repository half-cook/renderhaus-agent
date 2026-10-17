---
name: lipsync
description: Revoice supplied footage with consented sync-3 through fal.
metadata:
  include_tools: call_media_tool call_audio_tool
  routing_tools: sync3_lipsync eleven_v4_turbo
  gateway_tools: Sync___lipsync_video Sync___get_video_task ElevenLabs___text_to_speech_convert
---

# Lip sync

For sync-3, require footage before attempting lip sync. When the customer supplies only a script,
prepare authorized speech using `ElevenLabs___text_to_speech_convert` through `call_audio_tool`,
then use the resulting audio with the customer's footage through `call_media_tool`.
Discover exact schemas first. Obtain speaker/likeness permission before TTS or voice cloning;
never infer consent from a spending approval. Speech alone cannot animate a face.

Identify everyone whose face or voice appears in `subjects`, including the replacement speaker.
Obtain the customer's explicit acknowledgement and set `consent_confirmed=true` only then.
The host and typed provider contract refuse missing, false, or non-boolean acknowledgements.
Use measured `source_duration_seconds`, `audio_duration_seconds` and `source_fps`; never guess
values to obtain a quote. Pass `video_url`, `audio_url` and the documented `sync_mode`.
Default `cut_off` stops at the shorter input. Other modes change output length and cost.

Disclose transport, model, selection basis, subject consent and the server's cost estimate.
Every Sync submission pauses for approval, including autonomous runs and when the general
premium-video switch is off. Unknown prices remain unknown. Approval exemptions and the
existing autonomous spending cap are unchanged. Do not change dry-run settings.

Sync uses fal (`fal-ai/sync-lipsync/v3`, shared FAL key). Obtain source media rights and
required likeness and voice permissions. No Sync result is eligible for Renderhaus training.

For inputs beyond the configured chunk cap (60 seconds by default), supply measured silence
or shot timestamps in `chunk_boundaries_seconds`. Each interval must fit the cap. Chunking
supports equal-duration audio/video with `cut_off` only; split or retime mismatched sources
before submission. The adapter checks local ffmpeg/ffprobe, approved download hosts and S3,
splits both sources at the same times, submits each chunk and concatenates finished videos.
The existing merge path normalizes output to 1280×720 at 24 fps: disclose this limitation.
Fal's hard duration limit is UNVERIFIED; the operational cap is not a vendor guarantee.

Submit once, preserve the returned `job_id`, and poll `Sync___get_video_task` with that ID.
Keep partial chunk job IDs after a failure; do not blindly resubmit paid work. A queued job,
dry-run URL or mocked result is incomplete media. Open/play the actual saved artifact and
inspect lip timing, continuity and audio before delivery. Record explicit customer visual
acceptance/rejection with `record_media_outcome` and the saved call ID. Spending approval
is not visual acceptance.
