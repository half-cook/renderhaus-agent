---
name: remotion-loudness-qc
description: Measure programme loudness and true peak on a saved local file, optionally apply one two-pass loudnorm AAC finish, and re-measure the encoded output. Keep mixing, dialogue-gated certification and paid audio generation in their existing workflows.
metadata:
  include_tools: call_editor_tool
  routing_tools: ffmpeg_tool
  gateway_tools: Ffmpeg___ffmpeg_tool
---

# Remotion loudness QC

Use the free `ffmpeg_tool` alias, `Ffmpeg___ffmpeg_tool`, through `call_editor_tool`.
Discover the exact schema. Arguments are `op`, `job_id`, `input_path` and `params`.
Measure the rendered file that the viewer hears. Composition settings and sample peaks
alone do not establish programme LUFS or true peak.

Choose a target from the user's spec or the maintained delivery preset. Without either,
request the destination channel or explicit target before normalising. Delivery defaults
are described in [delivery render](../remotion-delivery-render/SKILL.md). An EBU R128 check
uses -23 LUFS, a -1 dBTP maximum and a 0.5 LU tolerance. Social and web presets use -14
LUFS with -1.5 dBTP. Podcast streaming uses -16 LUFS with -1.5 dBTP.
These are programme measurements. Dialogue-gated loudness certification is unavailable.

## Measure, decide, finish and re-measure

1. Call `probe` on the job-relative file. Require an audio stream before checking a target
   that needs audio. A silent mix or non-finite integrated value cannot pass that target.
2. Call `measure_loudness` with numeric `I`, `TP` and `LRA` parameters. Their validated
   bounds are `I=-30..-5`, `TP=-9..0` and `LRA=1..20`. Inspect integrated LUFS, true peak,
   loudness range, threshold and target offset from the actual result.
3. For a report-only request, return those measurements and the pass/fail comparison
   without modifying the file. For an explicit normalisation or a delivery preset, finish
   once when the target or true peak fails. If the encoded file already meets both gates,
   leave the audio unchanged. A PCM intermediate still needs its single AAC mux.
4. Call `loudnorm_mux_aac` with the measured pass-one values in `measured_I`, `measured_TP`,
   `measured_LRA`, `measured_thresh` and `offset`, plus the numeric target `I`, `TP`, `LRA`
   and `bitrate_kbps`. The bitrate is 64 to 320 kbit/s. The fixed op copies video, encodes
   AAC at 48 kHz, and puts `moov` before `mdat`. Use `mux_aac` when no loudness target
   applies. Never send a filter string, raw arguments, codec or output filename.
5. Call `measure_loudness` on the returned AAC output with the same target. Require both
   integrated tolerance and the true-peak limit. `linear=true` may fall back to dynamic
   normalisation when gain or LRA is infeasible. Inspect the reported normalisation type
   and disclose that result. Never label the output linear merely because linear was requested.
6. Inspect `volume_stats` for sample clipping and the final delivery QC result. The sample
   peak does not replace true peak. A missed target or clipped output remains failed.
   Fix the upstream mix or report the trade-off; there is no arbitrary limiter op.

For clips shorter than three seconds, integrated loudness is unreliable. Report the measured
programme value with that warning and use sample/true peak for the meaningful short-clip
check. Do not certify integrated compliance from that sample. Keep one or two source channels
unless the approved delivery spec says otherwise.

"Normalise it twice" still follows one measure/finish/re-measure workflow. A second listed
workflow step reuses the integrated delivery result and does not apply gain again.
When the delivery wrapper already performed these stages, read its evidence through
the [delivery guide](../remotion-delivery-render/SKILL.md) instead of repeating the finish.

## Keep the mix and evidence separate

Quiet VO under loud music needs stem rebalancing. Use the saved VO and music assets with
[final assembly](../final-assembly/SKILL.md) timing and volume controls, then measure that
new render. Use [audio bed](../audio-bed/SKILL.md) only for separately requested audio
generation. Normalising the combined mix changes both stems and cannot repair their balance.

Report the target, before and after LUFS/LRA/true peak, sample peak, action taken,
normalisation type, final output path, hash, pass/fail and warnings. Preserve the final
AAC measurements in the QC report and delivery manifest. Open/play that actual file.
Do not claim loudness compliance from dry-run previews, a queued job or successful execution
without measurements. `FFMPEG_DRY_RUN` and `REMOTION_DRY_RUN` keep their existing behavior.

Files remain confined to the local job directory. No network fetch, escaping path, symlink,
free-form shell, pasted script, filtergraph or unlisted op is allowed. Fairlight and other
Resolve operations remain parked. Offer the fixed FFmpeg measure instead. Source rights,
confidential metadata, quality-first defaults and paid-generation approvals remain unchanged.

## Sources

The supplied loudness draft is `/workspace/research/renderhaus-skills/remotion-loudness-qc/SKILL.md`.
The fixed op schema defines the current contract. [FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)
describes two-pass programme loudness and [EBU R128](https://tech.ebu.ch/docs/r/r128.pdf)
defines the programme target. FFmpeg licensing depends on the installed build; this wrapper
adds no redistributed binary, model, weights or training rights.
