# Podcast audiograms and channel templates

The [podcast-audiogram skill](../agent/deep_agent/skills/podcast-audiogram/SKILL.md) turns an
existing recording into a captioned waveform MP4. It preserves the source voice and gain,
shows measured amplitude bars or a line, highlights timed words, and includes progress,
speaker/show labels and optional cover art. The existing
[motion-graphics skill](../agent/deep_agent/skills/motion-graphics/SKILL.md) owns the channel
intro and end-screen templates. No provider or Gateway tool is added. An explicit renderer that lacks the named template
is blocked with disclosure; it is never silently replaced by the default.

## Existing tool mapping

RT-182's draft `transcribe_audio` placeholder maps to the built
`ElevenLabs___speech_to_text_convert`, workflow alias `elevenlabs_stt`. The second step is
`Remotion___render_timeline`, alias `remotion_render`. Speech-to-text accepts the existing
source reference in `file`, `model_id="scribe_v2"`, `timestamps_granularity="word"`,
`no_verbatim=false` and `webhook=false`; `diarize` can identify speakers. The committed
Gateway schema and existing provider enforce its arguments before any request.

The synchronous response is wrapped as
`{status: "succeeded", result: {text, language_code, language_probability, words}}`.
Each word record includes `text`, `start`, `end`, `type` and optional speaker/confidence
fields. Select `type="word"` records with measured non-null times, preserving their text.
Convert source times to seconds relative to the selected clip. Validate source-version
identity, order and bounds before composing. Spacing/audio-event tokens are not speech words.
The official [speech-to-text API](https://elevenlabs.io/docs/api-reference/speech-to-text/convert),
read 2026-10-10, verifies this model and word-timing path. No new transcription API is invented.

Prefer supplied words, exact-source-version indexed word records, or supplied SRT. A saved
transcription ID uses the existing `ElevenLabs___speech_to_text_transcripts_get` with
`transcription_id`. These reuse paths do not purchase transcription. Footage-memory's
`dialogue` events have millisecond phrase timing; they are usable for selection and text
review, but word highlights require actual word-timing attributes. See
[VideoIndex](VIDEO_INDEX.md). Conversational editing already uses this transcription path
and caches timings by source version; audiograms reuse those results. Sync's
`transcribe_video` is tied to its consented whole-video dialogue-edit workflow, so it is
not the standalone podcast-audio default.

An SRT with phrase cues shows supplied whole-cue captions. It reports that measured word
highlighting is missing rather than inventing alignment. If exact highlighting is needed
and only text is available, the existing `ElevenLabs___forced_alignment_create` accepts
`file` and `text` and returns timed words. It needs separate paid approval.

Paid transcription and forced alignment pause even in autonomous runs. The existing
executor quotes them and keeps its spend cap and `APPROVAL_EXEMPT_TOOLS` unchanged.
[API pricing](https://elevenlabs.io/pricing/api), read 2026-10-10, lists Scribe v2 at
$0.22 per audio hour, metered by audio minutes, with additional keyterm/edit charges.
The tool request has no verified measured-duration quote contract. **TODO:** configure
and validate the existing operator quote path; the current unconfigured per-call estimate
is **unknown**, not a fabricated total. Rendering retains the existing Remotion cost and
paid-video approval policy, including autonomous approval. No live call was used to verify
these workflows.

## Render contract

Use the existing `Remotion___render_timeline` with `visuals=[]`, one source `audio_tracks`
entry and a `template` object. The template owns its geometry; top-level `text_overlays`,
`subtitles` and `subtitles_srt` cannot be mixed with it. The audio track begins at output
second zero, spans exactly the template duration, and keeps volume 1 and zero fades.
`source_in_seconds` selects the original recording's range. Requested normalization belongs
in the later approved delivery step. No TTS, voice clone, re-voice or lip-sync is permitted.
Source references in `audio_tracks`, `cover_url` and `logo_url` reuse the owned Studio asset
resolver; raw local paths remain confined to the current job.

| Field | Contract |
| --- | --- |
| `name` | `podcast-audiogram`, `youtube-intro-sting` or `youtube-end-screen`. |
| `duration_seconds` | Audiogram 0.1–90 seconds; intro 3–5 seconds; end screen exactly 20 seconds. |
| `words` | Audiogram: 1–2000 `{text, start, end}` records, ordered, non-overlapping and inside the selected clip. Text is at most 80 characters per word. |
| `captions_srt` | Audiogram: bounded inline numbered SRT, mutually exclusive with `words`. Cue timing is preserved; no inferred word highlight. |
| `amplitudes` | Audiogram: exactly one finite 0–1 measured amplitude per output frame. |
| `waveform`, `bars`, `smoothing` | `bars` or `line`; 16–64 bars, default 32; smoothing 0–0.95, default 0.65. The envelope operation applies smoothing once. |
| `speaker_name`, `show_name` | Optional speaker up to 64 characters and show up to 96 characters. |
| `cover_url`, `logo_url` | Cover only for audiograms; logo only for channel templates. Optional existing art, no vendor logos. |
| `background_color`, `accent_color`, `text_color` | RGB hex colors; defaults `#101820`, `#f5b642`, `#ffffff`. |
| `remove_fillers` | Default false. With measured words and an explicit request, caption-only omission of `um`, `uh`, `erm`, `hmm`; recording unchanged. |
| `correction_terms` | Up to 100 names/jargon terms of at most 80 characters; returned flags require transcript review. |

Caption grouping is deterministic: consecutive groups contain up to six words; a final
one-word remainder borrows a word from the preceding group. Groups contain 2–6 words when
the transcript permits, and a one-word transcript stays one word. Text and punctuation
remain verbatim. Highlights appear only within each word's measured interval; gaps have no
active word. Configured names/jargon and likely proper-name/all-capital tokens are flagged
for correction; flags do not rewrite the transcript. Phrase SRT does not apply word-level
filler removal. The progress bar is bounded 0–1 and reaches one on the last output frame.

`Ffmpeg___ffmpeg_tool` adds the fixed `audio_envelope` operation, not a new tool. Use its
owned `job_id`, `input_path`, `start_seconds`, `duration_seconds` and integer `fps` (12–60).
It decodes the selected range to bounded 16-bit PCM, then reads per-frame RMS amplitudes
in Python with configured smoothing. Metrics include `amplitudes`, `duration_seconds`,
`fps`, `smoothing` and `source_sha256`. Pass measured values to the template and retain the
checksum with the source version. This is an audio-reactive amplitude visualization, not
an FFT spectrum or a browser live audio analyser. The same bounded plan feeds local and
Lambda rendering; neither renderer guesses audio energy.

## Aspects and review

Canvas selection uses the existing `choose_canvas` path. Audiograms support 9:16, 1:1,
4:5 and 16:9. Reuse the existing aspect-variant workflow after approving the first render;
recompose the template when cropping a flat master would remove its captions or identity.
The conservative safe rectangles below are normalized `{x, y, width, height}` in canvas
coordinates. They are Renderhaus buffers, **UNVERIFIED** as current platform UI guarantees.

| Aspect | Safe rectangle |
| --- | --- |
| 9:16 | `{0.08, 0.12, 0.76, 0.66}` |
| 1:1 | `{0.07, 0.07, 0.86, 0.84}` |
| 4:5 | `{0.08, 0.08, 0.80, 0.76}` |
| 16:9 | `{0.05, 0.07, 0.90, 0.86}` |

Within that rectangle the planner assigns art, identity, waveform, captions and progress
boxes. Tests require them to remain inside the safe rectangle. Long labels and caption fit
can refuse rendering; revise the copy/art layout rather than allowing clipped text.

Render one full first-aspect MP4 and poll its saved render ID. Extract stills at 10% and
60% with the existing ffmpeg `extract_frames` operation. Inspect both stills and play the
whole file with audio; obtain customer visual approval before extra aspects. Spending
approval is separate. Every output runs
[loudness QC](../agent/deep_agent/skills/remotion-loudness-qc/SKILL.md) and
[deliverable QC](../agent/deep_agent/skills/remotion-deliverable-qc/SKILL.md). An output is
finished only when its saved passing report matches all output checksums. Technical QC
leaves transcript, framing and platform visual review pending. Delivery reports measured
width, height, `source_resolution` and resolution warnings; audio-only source dimensions
remain unknown.

## Channel templates

`youtube-intro-sting` is a 3–5 second bounded logo/title sting inside motion-graphics, with
optional supplied source audio. `youtube-end-screen` is a 20-second 16:9 end-screen plate,
also inside motion-graphics. It reserves native element areas as data and places its logo,
show name and closing copy outside them. These templates reject audiogram words, SRT,
amplitudes and transcript-correction options. They do not publish or insert YouTube elements.

The end-screen reservations in `providers/remotion/templates.py` are normalized rectangles:

| Intended native element | x | y | width | height |
| --- | --- | --- | --- | --- |
| First video/playlist | 0.44 | 0.15 | 0.50 | 0.28 |
| Second video/playlist | 0.44 | 0.55 | 0.50 | 0.28 |
| Subscribe/channel | 0.05 | 0.36 | 0.25 | 0.44 |

Tests validate that the template's text/logo rectangles do not overlap these reservations.
The [official YouTube end-screen help](https://support.google.com/youtube/answer/6388789),
read 2026-10-10, confirms the last 5–20 seconds, a minimum 25-second uploaded video and up
to four elements for a standard 16:9 video. It describes editable positions/grid snapping
but does not publish fixed pixel rectangles. **UNVERIFIED:** these exact reservations are
Renderhaus layout choices, not official element geometry. Before shipping, re-verify the
current limits in official help and place actual elements in YouTube Studio to validate
positions and device visibility. Append the plate to a video of at least 25 seconds; the
20-second standalone plate cannot itself meet that upload minimum.

## Backend, licences and pending verification

Local rendering supports the named templates with real FFmpeg/FFprobe. The checked-in
Remotion composition consumes the same canonical plan. Lambda defaults to refusing named
templates before media I/O or AWS submission: `REMOTION_TEMPLATE_CONTRACT_VERSION=0`.
An operator can set version 1 only after deploying the checked matching composition;
template-contained art does not independently require overlay contract version 2.
No deployment, live Lambda render or hosted transcription took place. Cross-backend
pixel/perceptual equivalence remains **UNVERIFIED**. Dry-run defaults and flags are unchanged.

Scribe v2 uses [ElevenLabs service terms](https://elevenlabs.io/terms-of-use), read 2026-10-10;
recordings must have authorized input rights. Preserving an existing recording does not
create a cloned voice. No verified grant permitting model training from hosted transcripts
was found, so `training_eligible=false`. Existing Remotion licensing remains unchanged:
[official licence guidance](https://www.remotion.dev/docs/license), read 2026-10-10.
Templates introduce no model weights or new training entitlement. Existing Remotion output
policy remains ineligible for the training flywheel.

The MIT [youtube-video-skills](https://github.com/iart-ai/youtube-video-skills/blob/f3df381d65abe5078f5ed410bbc3ed72e7cb92bd/LICENSE)
was read as a pattern source, pinned to `f3df381d65abe5078f5ed410bbc3ed72e7cb92bd`.
No upstream code, scripts, dependency or assets are copied; adapted guidance is attributed
in [NOTICE](../providers/remotion/NOTICE.md). No AGPL or non-commercial material is introduced.

RT-182 and nine ownership/reuse cases are active: 281 retained rows, 275 active and the same
six dependency skips. A long-episode best-moment request starts in footage-memory;
talking-head captions remain conversational-edit, lower thirds remain motion-graphics,
and ad variants retain their matrix skill. User-facing product labels use “Podcast audiogram”,
“Channel intro” and “YouTube end screen”; provider and cost disclosure remains in the existing
approval messages. Comet browser E2E is **blocked** in this environment and cannot be claimed
as passed. See [decisions](podcast-audiogram-decisions.tsv).
