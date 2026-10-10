---
name: dialogue-edit
description: Change or remove words in existing single-speaker footage, preview only the edited spans re-spoken in the consented source voice, then generate sync-3 video.
metadata:
  include_tools: call_media_tool call_audio_tool
  routing_tools: sync3_lipsync eleven_v4_turbo
  gateway_tools: Sync___transcribe_video Sync___get_transcription Sync___create_dialogue_edit Sync___get_dialogue_edit Sync___create_dialogue_video Sync___get_video_task Sync___lipsync_video ElevenLabs___text_to_speech_convert
---

# Dialogue editing

Use this skill for a word correction, product name/price/date replacement or phrase removal
in existing footage. The canonical capability is `sync3_lipsync`; dialogue video is its
`Sync___create_dialogue_video` variant. It uses direct Sync, including when ordinary lipsync
uses fal. Follow explicit request, exception predicate, then default. Other providers have
no built word-edit endpoint; disclose that and refuse to substitute automatically.

Require one speaker and the whole source video, measured at most 600 seconds. Refuse
multi-speaker requests with a reason. Full re-dubs/translation use `lipsync`, new talking
shots use t2v/i2v, and silence/filler cuts use `conversational-edit`. Presenter length does
not select HeyGen for word edits. A confidentiality field does not affect routing.

Identify the speaker in `subjects` and obtain explicit permission for both the cloned
source voice and likeness. Set `consent_confirmed=true` only after acknowledgement.
Spending approval is separate from consent. Measure source duration/fps/dimensions rather
than guessing. The source must already be hosted on the verified Sync storage host
`assets.sync.so`; ask the operator to complete Sync's upload/register workflow for other
sources. This skill has no upload endpoint and must not fabricate a Sync URL.

1. Discover the exact schemas. Submit `Sync___transcribe_video` with `source_video_url`,
   `source_duration_seconds`, `speaker_count=1`, `subjects` and consent. Preserve
   `transcription_id`; poll `Sync___get_transcription`. Transcription has no generation
   credit charge. Do not use incomplete, windowed or multi-speaker transcripts.
2. Map requested edits to the returned word IDs. Changes are
   `{kind: "change", wordId, replacement, pronunciation?}`. Removals use
   `{kind: "remove", wordIds: [contiguous ids]}`. Use 1–100 operations. The adapter
   fetches and sends the immutable server transcript; never rewrite it or invent IDs.
3. Propose `Sync___create_dialogue_edit` through `call_media_tool`, with the source,
   transcription ID, edits, consent and a stable `action_id`. This creates the paid audio
   preview; there is no separate POST preview endpoint. Disclose direct Sync and the cost
   before approval, even in autonomous runs. Preview price is TODO/unknown until an
   operator-confirmed quote is configured. Optional `voice_id` reuses the returned source
   voice; `rerun_of_job_id` identifies a deliberate, separately approved rerun.
4. Preserve `dialogue_edit_id`, then poll `Sync___get_dialogue_edit`. Open/listen to
   `previewAudioUrl` and show the changed wording to the user. Only edited spans are
   re-spoken. `COMPLETED_PARTIAL` is partial: disclose it and require explicit acceptance
   before setting `accept_partial=true`. A dry preview has no playable audio.
5. After the user approves the preview, propose `Sync___create_dialogue_video` with
   `preview_reviewed=true`, measured `preview_duration_seconds`, `source_fps`, the same
   original source, edit ID, consent and a stable `idempotency_key`. Disclose the video
   cost and pause again, even autonomously. The provider sends `model=sync-3`, exactly
   one original video input and `dialogueEdit: {id}`. Never attach audio, segments,
   dub parameters or a source window. Both rollout flags must be enabled.
6. Preserve the opaque returned `job_id` and poll `Sync___get_video_task` with
   `download=true`. Open/play the saved MP4 and inspect audio, word timing and lip sync.
   Preview audio, queued jobs and dry results do not finish a video. Record customer
   visual review with `record_media_outcome`; approval to spend is not visual acceptance.

A `submission_unknown` preview means the response was lost after a possible charge.
Never auto-retry creation, change `action_id` to bypass it, or assume no charge. Check the
provider dashboard/status with the operator or ask the user. If an ID is recovered, use
the GET tool. A deliberate rerun requires reconciliation and a new approval. Generation
uses its saved Idempotency-Key; reuse that key to reconcile an ambiguous video submission.

HTTP 422 `dialogue_edit_retime_required` returns `requires_audio_fallback` and directs
the regular `Sync___lipsync_video` workflow. Disclose unavailable retiming, obtain independent
approved speech/audio (for example `ElevenLabs___text_to_speech_convert` through
`call_audio_tool`), and pause for its cost and the regular lip-sync cost. Exact source-voice
preservation is no longer guaranteed. Never use the dialogue preview as regular audio to
bypass rollout flags. `dialogue_edit_removal_too_large` includes `dialogueEditSection`:
shrink the removal with the user and approve a new preview. Other 422s require correction.

Keep `SYNC_DRY_RUN=true` unless the operator separately enables live use. Direct Sync
requires express written vendor authorization for competitor/customer integration terms,
recorded by `SYNC_DIRECT_AUTHORIZED`. Uploads may be reused for service improvement.
sync-3 is proprietary, under service terms, and `training_eligible=false`. No weights,
AGPL code or non-commercial code are added. See [contract and sources](../../../../docs/DIALOGUE_EDIT.md).
