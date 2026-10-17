---
name: podcast-audiogram
description: Turn a podcast clip, existing voiceover or quote into a captioned audio-reactive waveform video with progress, speaker/show names and optional art in 9:16, 1:1, 4:5 or 16:9.
metadata:
  remotion_backend: configured
  remotion_features: named_templates audio_mix canvas encoding
  include_tools: call_editor_tool call_audio_tool call_media_tool
  gateway_tools: Remotion___render_timeline Remotion___get_render_progress Ffmpeg___ffmpeg_tool ElevenLabs___speech_to_text_convert ElevenLabs___speech_to_text_transcripts_get ElevenLabs___forced_alignment_create Remotion___qc_deliverable Remotion___deliver_render Remotion___motion_carry_probe
  routing_tools: remotion_render elevenlabs_stt ffmpeg_tool deliverable_qc delivery_render motion_carry_probe
---

# Podcast audiogram

## Preserve the recording and transcript

Discover `Ffmpeg___ffmpeg_tool` through `call_editor_tool`. Use its real `probe` and `trim`
operations on the owned job source. Keep source loudness until the loudness-QC step.
Never synthesize a replacement voice, clone the speaker or lip-sync a new performance.

If the source has a saved transcript ID, retrieve it with
`ElevenLabs___speech_to_text_transcripts_get` through `call_audio_tool`. If no usable timing
exists, discover `ElevenLabs___speech_to_text_convert`. The existing alias `elevenlabs_stt`
maps to that tool. Use the real source_ref in `file`, `model_id="scribe_v2"`,
`timestamps_granularity="word"`, `no_verbatim=false`, `webhook=false` and speaker labels when
needed. Paid transcription and forced alignment always pause with the host estimate,
including autonomous runs. An unconfigured quote is unknown. A dry-run has no transcript.

Keep words verbatim and preserve fillers unless the user asks to remove them. Provide
names, brands and jargon in `correction_terms`. Show flagged words for correction before
rendering. Caption-only filler removal does not cut those words from the recording.
Use relative seconds measured from the selected clip's beginning. Never infer measured
word timing from untimed prose. A supplied SRT can reuse its cue timing without a paid call.
Phrase-level SRT shows whole cues and reports pending active-word highlights. It does not
invent word alignment. If exact word highlighting is required and only text exists,
offer the existing `ElevenLabs___forced_alignment_create` with separate paid approval.

## Compose the first aspect

Discover `Remotion___render_timeline` through `call_editor_tool`. Send its bounded `template`
object with `name="podcast-audiogram"`, `duration_seconds`, `words` or `captions_srt`, and the
requested identity/art/color fields. Supply the original recording in `audio_tracks`
with volume 1 and no fades. Requested gain or fades belong in a separate approved delivery edit. Do not send JSX or source code.
The audiogram duration is at most 90 seconds. Caption groups contain 2-6 timed words when
the transcript permits, with the current word highlighted only during its measured interval.
Short transcripts can have fewer than two words. The progress bar reaches 100% on the last frame.

Use `waveform="bars"` or `"line"`, `bars=32` and `smoothing=0.65` unless the brief changes
them. Derive `amplitudes` from the same source range using the fixed `audio_envelope`
operation of `Ffmpeg___ffmpeg_tool` with `start_seconds`, `duration_seconds` and `fps`.
Pass its bounded per-frame 0-1 values to the template. Preserve the source checksum in
the job ledger. These are PCM amplitude bars/line, not frequency-spectrum FFT bars.
No live browser analyser, random waveform, or render-time audio analysis is supported.

Reuse the existing aspect/canvas handling for 9:16, 1:1, 4:5 and 16:9. Follow
[aspect variants](../remotion-aspect-ratio-variants/SKILL.md) after the first approved render.
Recompose the same template separately per aspect when a flat-master crop would cut its
labels, captions or waveform. Keep content inside the planner's conservative safe rectangle.
Platform UI geometry is UNVERIFIED and requires visible review on the intended platform.

The configured Remotion backend must support every requested feature. Unsupported features refuse before media I/O
or AWS submission. Submit one render under the existing compute/spending gate. Save its identifiers and poll
`Remotion___get_render_progress`. A dry-run or queued job is incomplete. Local rendering
supports these templates. Lambda refuses them until the operator deploys the matching
composition and sets `REMOTION_TEMPLATE_CONTRACT_VERSION=1`. Never change that flag yourself.

## Review and finish

From the first full MP4, use `Ffmpeg___ffmpeg_tool` with `extract_frames` at 10% and 60% of
its duration. Inspect caption text, measured active-word timing, waveform response, optional
art, identity labels and safe zones. Play the whole MP4 with sound. Present both stills and
the full video for customer visual approval before rendering other aspects. Spending
approval does not approve the visual result. Stop on rejection and revise the same source.

Run [loudness QC](../remotion-loudness-qc/SKILL.md) and
[deliverable QC](../remotion-deliverable-qc/SKILL.md) on every output. Follow
[delivery render](../remotion-delivery-render/SKILL.md) for an approved target's normalization.
Use only the existing named presets and fixed operations. Unknown platform loudness remains
pending. Do not call an artifact finished until its passing saved QC report matches every
output checksum. Report each failure verbatim. Visual and audio inspection remain separate
from technical QC. Deliver the manifest with measured dimensions, source_resolution and warnings.

No new model, provider, key or training right is introduced. Hosted transcripts, unknown
media and these template outputs remain ineligible for training under the existing policy.
Read [the contract and decisions](../../../../docs/PODCAST_AUDIOGRAM.md) for limitations.

## References

Pattern guidance from [iart-ai/youtube-video-skills audiogram](https://github.com/iart-ai/youtube-video-skills/blob/f3df381d65abe5078f5ed410bbc3ed72e7cb92bd/skills/audiogram/SKILL.md),
Copyright (c) 2026 iart.ai, [MIT licence](https://github.com/iart-ai/youtube-video-skills/blob/f3df381d65abe5078f5ed410bbc3ed72e7cb92bd/LICENSE), read 2026-10-10.
No upstream code, assets, scripts or dependency are copied.
Attribution is in [NOTICE](../../../../providers/remotion/NOTICE.md).
