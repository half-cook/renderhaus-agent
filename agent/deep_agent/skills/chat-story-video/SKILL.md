---
name: chat-story-video
description: Render fictional text-message conversation shorts from a messages array or CSV with verbatim bubbles, typing beats, reactions, safe-zone scrolling and sound cues. Validate each script and reuse the first-render approval gate for batches. Real footage edits and per-market ad copy swaps use their existing skills.
metadata:
  remotion_backend: configured
  remotion_features: chat_story audio_mix canvas encoding ad_matrix
  include_tools: call_editor_tool
  routing_tools: remotion_render ffmpeg_tool ad_variant_matrix delivery_render deliverable_qc
  gateway_tools: Remotion___render_timeline Remotion___get_render_progress Remotion___render_ad_variants Ffmpeg___ffmpeg_tool Remotion___deliver_render Remotion___qc_deliverable
---

# Chat story video

Use this skill for fictional conversation shorts and one conversation video per script row.
Read `read_studio_context` and discover the exact tool schemas before dispatch.
The thread uses a deterministic composition. Never call a generative video model for it.
Use [conversational edit](../conversational-edit/SKILL.md) for existing talking-head footage,
[ad variant matrix](../remotion-ad-variant-matrix/SKILL.md) for per-market copy swaps on an ad,
and [motion graphics](../motion-graphics/SKILL.md) for a generic title or lower third.
Optional voiceover or separately generated audio belongs to [audio bed](../audio-bed/SKILL.md).

## Validate the script

Pass `chat_story` to `Remotion___render_timeline` through `call_editor_tool` for one script.
The payload contains `messages`, optional `contact`, `theme`, `aspect`, `dramatization`,
`music_ref`, `send_sound_ref`, `receive_sound_ref`, `sfx`, `holdMs` and `platformTargetMs`.
Use the discovered JSON schema. CSV and JSON text input must first become a validated
messages array. Batch rows can carry their own JSON or CSV script payload.

Each message has `from` and `text`. Optional columns are `typingMs`, `delayMs`, `status`
and `reaction`. `from` is `me` or `them`. Supply 1-40 messages with 1-500 characters each.
Timing values are finite numbers. `typingMs` is 0-10000 and `delayMs` is 0-30000.
Typing is received-only. Status is sent-only and is empty, `sent`, `delivered` or `read`.
Reactions are empty, `❤️`, `👍`, `😂`, `‼️` or `❓`.
The validator handles quoted CSV, emoji and ordinary right-to-left text. It rejects
duplicate fields, unknown columns, markup and unsafe controls.

Render supplied text verbatim, including punctuation and spaces. Never shorten, translate
or repair a message. If a message cannot fit the readable band, request approved replacement
text. Write a new script only when asked, then obtain script approval before rendering.
`contact.name` is an invented fictional label. `contact.avatar` is `initials` or `placeholder`.
Refuse photos, real-looking phone numbers and private-person impersonation.
If the validator flags possible brand or public-figure impersonation, request a fictional
replacement before rendering. A warning does not establish that a real identity is safe.
Set `dramatization=true` when the brief requests the on-screen disclosure.

## Theme and timing

Only `generic` is enabled by default. The neutral `slate` and `moss` presets are disabled
unless an operator sets `CHAT_STORY_LOOKALIKE_THEMES=on` after legal sign-off.
Use either preset only when the user explicitly requests a platform lookalike.
When the flag is off, explain that lookalike themes are not enabled and render `generic`.
Never include vendor logos, wordmarks, trademark labels or app icons in the output.
The agent cannot enable the flag or change the render backend.

The planner derives all frames from the validated messages. A received reply gets a
700-1500 ms typing beat by default, scaled to its text length. The default read gap is
600 ms. Bubbles pop on their planned frame. A reaction arrives about 400 ms later.
The thread ends with `holdMs`, which defaults to 2000 ms. Report the computed duration
and any warning that it exceeds `platformTargetMs`, which defaults to 60000 ms.
Sent bubbles align right and received bubbles align left. Only the last bubble in a
same-sender run has a tail. The header stays pinned and the newest bubble remains above
the bottom safe zone. Text wraps within 74% of the canvas width.
The default aspect is `9:16` at 1080x1920. `1:1` and `4:5` also use the existing aspect table.

Send and receive cues use the bubble frame. The local renderer can synthesize simple pop
tones. Supplied sound and music references must be safe paths inside the current job.
Audio uses the existing `audio_tracks` contract, with the music bed ducked under pops.
Do not download sound packs or bundle third-party SFX. Reuse approved audio assets when supplied.

Unsupported features refuse before media I/O. This composition runs on the local worker.
Lambda chat rendering is unavailable until the composition is deployed and verified there.
Report that refusal as an incomplete render. Keep `REMOTION_DRY_RUN` in force.
A dry-run payload is a preview, never an MP4.

## First render and batch

For a batch, use `Remotion___render_ad_variants` with `brief.mode="chat_story"`,
`master_asset=""`, the trusted current `job_id` and one `rows` record per script.
Each row has a unique `variant_key`, its own `chat_story` payload and an optional `aspect`.
The batch has 1-100 rows. Do not issue individual timeline calls
to bypass batch approval.

1. Call `stage="plan"`. Validate each row and report the returned counts, duration and cost
   estimate. Planning is free. One invalid row must not stop the valid rows.
2. Call `stage="render_first"` with the returned `plan_hash`. The host pauses with the
   first-render cost estimate, including in autonomous mode. Authorization belongs to
   the host. Never fabricate approval arguments or approval records.
3. Inspect the first bubble, midpoint and final stills from the existing still mechanism.
   Open and play the full first render. Compare visible text, sides, timing and scroll
   position against the supplied script. Retain visual review as pending until this happens.
4. After the user reviews the first render, request `stage="render_batch"` with the same
   `plan_hash`. The host pauses again with the batch cost estimate, including autonomously.
   Changed rows or settings require a new plan and first render.
5. Preserve the manifest with its input hash, each output SHA-256, status and reasons.
   Report rendered, blocked and failed rows separately. Never count a queued or dry-run
   item as a completed video.

`Ffmpeg___ffmpeg_tool` is the allow-listed fixed-operation tool. Use the `ffmpeg_tool`
alias through `call_editor_tool` for `probe`, `extract_frames`, `contact_sheet` and `sha256`.
Arguments are `op`, `job_id`, `input_path` and the discovered `params`. Never supply shell
commands or paths outside the current job.

## Finish and verify

Every render passes through [loudness QC](../remotion-loudness-qc/SKILL.md) and
[deliverable QC](../remotion-deliverable-qc/SKILL.md) before delivery.
Use [delivery render](../remotion-delivery-render/SKILL.md) to finish the approved local
file or batch manifest through `Remotion___deliver_render`. Reuse its final measurements.
`Remotion___qc_deliverable` inspects final files without changing them.
Only report delivery when the saved QC report passed and matches every output checksum.
Quote each reported failure verbatim. Technical QC does not approve framing or script pixels.
Keep incomplete visual review explicit. Describe the customer's result with neutral labels
and keep vendor names and service-fee language out of user-facing labels.

State the successful render's delivered width, height and `source_resolution`, including
its resolution warnings. A larger canvas resampled from 1280x720 must say
"upscaled from 1280x720; no added detail". The [upscale skill](../upscale/SKILL.md) uses
Topaz for actual enhancement under its existing approval rules.

## References

- Pattern only, independently reimplemented. [iart-ai/text-message-video-skills at 3a800e1e9b9635fa196a07b0143c80f7e9648558](https://github.com/iart-ai/text-message-video-skills/blob/3a800e1e9b9635fa196a07b0143c80f7e9648558/skills/text-message-animation/SKILL.md), read 2026-10-10. [MIT licence](https://github.com/iart-ai/text-message-video-skills/blob/3a800e1e9b9635fa196a07b0143c80f7e9648558/LICENSE). No upstream code, artwork, audio or fonts are included. Keep [NOTICE](NOTICE) with adapted instructions.
