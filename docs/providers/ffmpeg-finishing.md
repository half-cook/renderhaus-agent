# Local FFmpeg finishing

The existing `Ffmpeg___ffmpeg_tool` gains five operations. The Gateway name, provider,
editor dispatch role, zero billing rate and approval behavior stay the same. Every op
uses `job_id`, `input_path` and `params`. `FFMPEG_DRY_RUN` defaults to `true`.
No new environment variable, secret, dependency, model or provider API is required.

| `op` | `params` | Bounds and defaults |
|---|---|---|
| `burn_subtitles` | `subtitle_path`, `subtitle_batch`, `font_id`, `font_size`, `colour`, `outline`, `margin` | Required job-local SRT or ASS. Batch adds 0 to 4 `{input_path,subtitle_path}` pairs. Fonts `dejavu_sans`, `dejavu_serif`, `dejavu_mono`; default sans. Size 12 to 96, default 36. Colour `#RRGGBB`, default white. Outline 0 to 5, default 2. Margin 0 to 200, default 24. |
| `export_srt` | `cues`, `export_batch` | Required 1 to 1,000 `{start,end,text}` cues. Seconds 0 to 600, at least one millisecond long after rounding, ordered and non-overlapping. Batch adds 0 to 4 `{cues}` items. |
| `color_match_lut` | `lut_path`, `intensity`, `grade_preset`, `brightness`, `contrast`, `saturation` | Optional `.cube`, intensity 0 to 1, default 1. Presets `none`, `warm`, `cool`, `contrast`. Brightness -0.2 to 0.2, contrast 0.5 to 1.5, saturation 0 to 2. Defaults 0, 1, 1. |
| `audio_cleanup` | `cleanup_preset`, `eq_preset`, `highpass_hz`, `denoise_db`, `compressor`, `compressor_threshold_db`, `compressor_ratio` | Cleanup `dialogue`, `gentle`, `music`; default dialogue. EQ `neutral`, `dialogue`, `warm`; default neutral. Highpass 20 to 300 Hz, default 80. Denoise 1 to 30 dB, default 12. Compressor defaults false; threshold -40 to -6 dB, default -18; ratio 1 to 8, default 2. |
| `make_proxy` | `height`, `crf`, `proxy_preset` | Height 480 or 540, default 540. CRF 18 to 35, default 28. Presets `fast`, `veryfast`, `ultrafast`; default veryfast. |

Example calls use the same job and source path:

```json
{"op":"burn_subtitles","job_id":"review-1","input_path":"master.mp4","params":{"subtitle_path":"captions.srt","font_size":24,"colour":"#FFFFFF"}}
{"op":"export_srt","job_id":"review-1","input_path":"captions","params":{"cues":[{"start":0.125,"end":1.75,"text":"Approved caption"}]}}
{"op":"color_match_lut","job_id":"review-1","input_path":"master.mp4","params":{"lut_path":"look.cube","intensity":0.5}}
{"op":"audio_cleanup","job_id":"review-1","input_path":"master.mp4","params":{"cleanup_preset":"dialogue","eq_preset":"dialogue"}}
{"op":"make_proxy","job_id":"review-1","input_path":"master.mp4","params":{"height":480,"crf":28}}
```

`export_srt` uses a lexical input label for the existing tool contract. It does not read
that file, invoke FFmpeg or generate a transcript. Outputs use generated names and hashes.
SRT text and ASS input are parsed into a restricted subtitle representation. Embedded
fonts, arbitrary font names, drawing commands and ASS override commands are refused.
Fonts are installed DejaVu files in the fixed system directory, never caller paths.
Burning uses ASS centisecond timing and refuses cues that collapse after rounding.

No licensed LUT is bundled. The caller supplies a rights-cleared job-local `.cube`.
The parser accepts bounded 3D cubes with size 2 to 33, exactly `size³` finite RGB triples
and valid domains. Test LUTs are generated in Python. `lut3d` applies the look; a fixed
blend interpolates between the original and graded pixels using `intensity`. No automatic
reference-frame matching or colour-management certification is provided.

Audio cleanup runs highpass, `afftdn`, a named EQ and an optional compressor. Listen to
the resulting file before approving the mix. The ordering is `audio_cleanup`, then
`measure_loudness` on its output, then `loudnorm_mux_aac` with those measurements, then
final-file loudness and delivery QC. Original-source measurements cannot normalize the
cleaned file. Audio-only cleanup creates a PCM intermediate; video cleanup preserves
video and finishes audio. It does not perform voice isolation or loudness normalization.

Proxies use H.264, bounded encoding settings, AAC when audio is present and MP4 faststart.
Their output names derive from the source and never overwrite. They avoid upscaling and
report actual dimensions, source resolution, cadence, SHA-256 and probe evidence. A proxy
is for review. Final delivery still requires the existing checksum-matching QC report.
Even-pixel fitting permits at most 1% aspect error; unrepresentable fits fail explicitly.
After finishing, QC must match the returned paths and checksums of every batch output,
including when the earlier delivery report belongs to a previous Studio turn.

The existing job confinement, ASCII paths, fixed argv, `shell=False`, scrubbed environment,
stdin refusal, timeout, thread and byte caps apply. Sidecars are validated before use and
temporary canonical files are removed. Batch failures remove partial outputs. Dry-run
checks arguments and lexical paths without reading media or writing files. Missing fonts,
filters, binaries and invalid media produce explicit failures. Binary ops require a local
worker with the job directory; no FFmpeg binary is bundled in the Lambda zip.

Local tool billing is $0 for every op. This is the repository's local-worker billing
policy, not a quoted vendor service price. Operator compute remains the operator's cost.
No paid model ID, endpoint, request schema or provider price is introduced.

FFmpeg is LGPL-2.1-or-later, with GPL components changing the build's licence. This task
uses the installed GPL build and redistributes no code or binary. DejaVu fonts retain
the Bitstream Vera font licence and public-domain DejaVu changes. No AGPL code,
non-commercial weights, model or licensed LUT is bundled. Existing `ffmpeg-local`
policies keep `training_eligible=false`; editing does not grant training rights in media.
Sources read 2026-10-10 are [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html),
[FFmpeg legal](https://ffmpeg.org/legal.html) and
[DejaVu licence](https://dejavu-fonts.github.io/License.html).

Comet Studio E2E is blocked because this environment has no Comet control. Real binary
tests validate local artifacts but do not establish browser playback, editorial acceptance
or deployed Lambda behavior. See [decisions](../remotion-resolve-gap-misc-decisions.tsv).
