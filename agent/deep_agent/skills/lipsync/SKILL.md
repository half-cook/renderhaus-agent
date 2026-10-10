---
name: lipsync
description: Revoice footage with consented sync-3 or make long multilingual presenters with HeyGen Avatar V.
metadata:
  include_tools: call_media_tool call_audio_tool
  routing_tools: sync3_lipsync heygen_avatar_v eleven_v4_turbo
  gateway_tools: Sync___lipsync_video Sync___get_video_task HeyGen___create_avatar_video HeyGen___get_video_status HeyGen___list_avatars HeyGen___list_voices ElevenLabs___text_to_speech_convert
---

# Lip sync

Use sync-3 for new audio on existing footage. Follow `read_studio_context.intent_route`:
For changing/removing specific spoken words while preserving the source voice, read
`/skills/dialogue-edit/SKILL.md`; its direct Sync preview and generation have separate approvals.
explicit request, then named exception, then capability default. New generated talking shots
use Seedance t2v/i2v. Presenters/digital twins over 30 seconds use HeyGen Avatar V,
unless the customer explicitly requests sync-3. Retired LivePortrait/LatentSync depend on
non-commercial InsightFace weights; never load them or silently substitute them.

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

Fal is the default transport (`fal-ai/sync-lipsync/v3`, shared FAL key). Direct Sync is optional
and requires written permission under Sync's competitor/integration terms, recorded by the
operator's authorization flag. Upload handling follows the selected host's terms; direct
Sync permits reuse for improvement and does not promise no training. No Sync result is
eligible for Renderhaus training. Follow the installed tool descriptions and host disclosure for the selected transport.

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


For the HeyGen exception, discover eligible digital-twin look IDs with `HeyGen___list_avatars`
and voice IDs with `HeyGen___list_voices`. Do not invent IDs or create a clone. The subject
must complete HeyGen's recorded consent flow separately. Identify every face and voice in
`subjects`; obtain explicit `consent_confirmed=true` and an opaque `consent_record_id` before
submission. Consent references contain no recording URLs, credentials or personal documents.
The live adapter verifies the look supports `avatar_v` and its group's `consent_status=accepted`.

Use `HeyGen___create_avatar_video` through `call_media_tool`. Supply an existing `avatar_id`
and either `script` plus `voice_id`, or public `audio_url`. `language` maps to the speech locale,
not video translation. `duration_seconds` is measured audio length or an honest script estimate.
It does not force render duration. Scripts allow up to 5,000 characters and one scene up to
1,800 seconds; audio inputs allow up to 600 seconds. Use `resolution=720p|1080p` and a supported
`aspect_ratio`. Avatar V supports digital twins, not photo-avatar creation in this adapter.

Disclose HeyGen direct, engine, selection basis, consent and the published cost estimate.
API PAYG Avatar V is $0.12/s as read 2026-10-09; the platform fee is added. Actual generated
seconds determine vendor billing. Enterprise quotes stay unknown. API credits are separate
from HeyGen app plans. Free Plan output commercial restrictions block live use unless the
operator records a paid API plan. Every generation pauses for approval, including autonomous
runs and a disabled general premium-video switch. Do not bypass approval with canvas invoke.
Non-enterprise uploads may train HeyGen unless the account opts out; enterprise data is excluded
under published vendor terms. Renderhaus marks all HeyGen outputs `training_eligible=false`.

Preserve the opaque `heygen:…` job ID and poll `HeyGen___get_video_status` with `download=true`.
A `submission_unknown` result requires operator reconciliation, never an automatic resubmit.
Dry-run previews never become live jobs when flags change. Completed saved MP4 output can finish
a standalone presenter request; captions, overlays or assembly still require rendering. Open/play
the actual MP4 before claiming delivery. See [HeyGen contract and sources](../../../../docs/HEYGEN.md).
