# Mureka music and lyrics video

Mureka V9.5 is the music default. Instrumental beds use
`Mureka___generate_instrumental`; songs use `Mureka___generate_song`.
`mureka_v95` is the canonical ID for both. ElevenLabs music remains explicit-only.
`mureka_lyrics_video` selects `Mureka___generate_lyrics_video`.
Explicit requests precede exception predicates and defaults. Price, quality tiers and
`project.confidential` do not change that order. No existing provider was removed.

All three generation operations use fal. This preserves one asynchronous queue and
same-host song/upload IDs through song-to-video, and uses the existing US-accessible
host. Direct Mureka music plus fal video was considered, but cross-host song-ID
compatibility has not been verified. Direct song and instrumental APIs are documented;
this adapter deliberately does not implement a second transport.

## Tools and contracts

| Tool (prefix `Mureka___`) | Key arguments | Result |
| --- | --- | --- |
| `generate_song` | `lyrics` or `prompt`; optional `styles` (prompt-only), `gender` (lyrics-only), `model` | Saved music handle |
| `generate_instrumental` | Exactly one of `prompt` or existing `instrumental_id`; optional `model` | Saved music handle |
| `generate_lyrics_video` | Exactly one of `song_id` or `upload_audio_id`; `layout`, `aspect_ratio`, optional `background_id`, `cover_url`, `title`; paired lyric rows or millisecond range | Saved video handle |
| `get_music_task` | `job_id`, `download=false` | Queue state; completed `song_id`, `lyrics_sections`, duration in milliseconds, audio URL/path |
| `get_video_task` | `job_id`, `download=false` | Queue state and completed MP4 URL/path |
| `list_mureka_models` | None | Offline verified models/endpoints and policy |

Pydantic strict contracts validate before paid I/O and at Gateway dispatch.
Song lyrics are 1–5000 characters; song prompt is 1–2000; instrumental prompt is
1–1024. `styles` cannot accompany lyrics. Both music requests fix the vendor safety
checker to true. Cloning, vocal IDs and reference vocals are excluded.

Video supports `layout_1` through `layout_7` and 16:9, 9:16, 3:4, 4:3 (default 9:16).
A cover cannot accompany layout_1. Lyric row selection is paired, 1-based and ordered.
Time selection is paired, milliseconds, with end strictly after start. A requested
video duration requires a matching millisecond selection range; no default duration
is assumed. Rows and time
selection cannot be combined. The endpoint uses generated/recognized timed lyrics;
it does **not** accept a custom timed-lyrics array or arbitrary audio URL plus lyrics.

Generate once, preserve the handle and poll it. Polling never submits generation.
Music handles preserve operation and model across restarts/configuration changes.
Completed music preserves song IDs and vendor lyric timing for the video step.
`download=true` saves and validates the actual audio or MP4; a queued job or preview
never satisfies delivery. Audio metadata selects supported MP3/WAV/FLAC/OGG/M4A
extensions; unknown or contradictory formats are rejected. ffprobe validates the
actual container/audio stream; non-MP3 requires ffprobe. These formats are adapter
support, not a vendor guarantee. MP3 has a frame-parser fallback. Signed result URLs are not persisted in task metadata.

## Configuration and approval

`MUREKA_DRY_RUN=true` is the new default; `FAL_DRY_RUN=true` also independently prevents
live requests. Both must be false for verified live submission. `MUREKA_MODEL` defaults
to verified `mureka-9.5`. Other IDs are **UNVERIFIED**: configuration can preview them,
pricing stays unknown, and live generation is blocked. Endpoints are fixed verified IDs.
Dry-run handles remain previews after flags change. CI forces dry-run explicitly.

Use the existing `FAL_KEY` from environment or Secrets Manager. The provider catalog
wires these settings into Gateway Lambda environment and `scripts/sync_secrets.py`
already synchronizes nonempty settings without logging values. `MUREKA_API_KEY` is
not needed for this fal-only implementation. Never put credentials in code or docs.

Songs/instrumentals pause with a cost estimate unless autonomous. Lyrics video
always pauses with cost, including autonomous runs and when the global premium-video
approval switch is disabled. The native Deep Agents 0.7.23 `interrupt_on` middleware
handles approve/reject and checkpoint resume. `APPROVAL_EXEMPT_TOOLS` and the
existing autonomous spend-cap calculation are unchanged. Manual Studio invocation
of lyrics-video returns 409 and directs the user to chat approval.

## Official verification and prices

All sources below were read **2026-10-09**. Schemas were checked against the official
fal OpenAPI embedded in each API reference, including the exact V9.5 ID.

| Operation | Fixed endpoint | fal provider estimate |
| --- | --- | --- |
| Lyrics-to-song (prompt may add style) | `mureka/api/generate/song` | $0.225/request |
| Prompt-to-song | `mureka/api/generate/song` | $0.75/request |
| Instrumental | `mureka/api/generate/instrumental` | $0.225/request |
| Lyrics video | `mureka/api/generate/lyrics-video` | $0.15/video |

Sources: [song schema](https://fal.ai/models/mureka/api/generate/song/api),
[song pricing](https://fal.ai/models/mureka/api/generate/song),
[instrumental schema](https://fal.ai/models/mureka/api/generate/instrumental/api),
[instrumental pricing](https://fal.ai/models/mureka/api/generate/instrumental),
[video schema](https://fal.ai/models/mureka/api/generate/lyrics-video/api),
[video pricing](https://fal.ai/models/mureka/api/generate/lyrics-video), and
[fal queue documentation](https://docs.fal.ai/model-apis/model-endpoints/queue).
Provider cents retain Decimal precision; the existing billing system rounds the
provider charge upward to whole cents, then applies its 30% fee (rounded, minimum
one cent). Thus approval totals are $0.30, $0.97 and $0.19 respectively. Dry-run bills
zero but discloses the live estimate. Poll/catalog calls are free.

[Direct pricing](https://platform.mureka.ai/pricing) lists V9.5 lyrics song and
instrumental at $0.15 each, prompt song at $0.50. The direct API defaults to two
songs per request and bills each; these direct prices are not used for fal quotes.
Verified direct references:
[song](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html),
[prompt song](https://platform.mureka.ai/docs/api/operations/post-v1-song-easy-generate.html),
[instrumental](https://platform.mureka.ai/docs/api/operations/post-v1-instrumental-generate.html),
[lyrics](https://platform.mureka.ai/docs/api/operations/post-v1-lyrics-generate.html), and
[lyrics video](https://platform.mureka.ai/docs/api/operations/post-v1-lyrics-video-generate.html).

## Licence and incomplete paths

Both Mureka V9.5 and hosted lyrics-video use proprietary, closed weights under
`service-terms`. The [Mureka commercial-rights FAQ](https://platform.mureka.ai/docs/en/faq.html)
states paid API output has full usage and commercial authorization.
[fal terms](https://fal.ai/legal/terms-of-service) and
[API services terms](https://fal.ai/legal/api-services) govern the chosen host,
including source-media rights and required likeness/voice consent. No model code or
weights are vendored. No AGPL or non-commercial implementation was added.
`training_eligible=false` for both: commercial usage does not expressly authorize
output model training, and fal restricts competing-model training.

The official video schema accepts existing song/upload IDs. Automated upload,
recognition and upload-ID interoperability with the direct host remain **UNVERIFIED**
and are not implemented. A supplied raw audio file (including ElevenLabs music/TTS)
cannot yet complete this chain without a prepared fal-hosted Mureka upload ID and
recognized lyrics. The skill names this blocker instead of inventing an endpoint.
TTS still uses ElevenLabs when requested. Existing-ID supplied-song and generated
Mureka-song workflows are wired; external account access and live output remain untested.

Three previously skipped lyrics-video routing rows are active. The source map/workbooks
were not copied into the repo. The existing audio-bed and lyrics-video skills were extended.
Current inventory and routing totals are in [Skill routing](SKILLS.md#offline-routing-verification).

Browser E2E is **blocked**: Comet is unavailable in this environment, as specified by
the user. Real Studio approval, live song playback and lyric-video timing/playback
were not exercised. No paid/live API was called. Offline HTTP, routing, native
approval/resume, artifact-validation and inventory checks are supporting evidence.
See [decisions](mureka-decisions.tsv) and ignored `.renderhaus/e2e/` evidence.

## Routing fixture changes

Activated fixture rows (0-based indices retained by the test generator):

| Row | Scenario | Selected tool |
| --- | --- | --- |
| 63 | Karaoke lyrics video from this song | Mureka___generate_lyrics_video |
| 64 | Mureka vertical 9:16 lyrics video | Mureka___generate_lyrics_video |
| 118 | Karaoke style from my track | Mureka___generate_lyrics_video |

Rows 19 and 45 now select Mureka instrumentals; row 44 selects Mureka song.
Row 116 keeps song preparation then adds video. Row 65 keeps ElevenLabs narration
first, then adds the video step; the raw-file upload preparation remains incomplete.
Routing readiness proves tool selection, not a real artifact or completed raw-upload flow.

Current skip reasons are listed in [the capability map](CAPABILITY_MAP.md#skills-and-routing-fixtures).

## Offline validation

The final full suite ran 1205 tests with 25 skips (1180 passed), including 59 new
Mureka provider/integration checks. The routing fixture accounts for 23 of the
skips. Ruff, `scripts/ci_check.py`, Studio TypeScript checking and the 13-case
`studio/scripts/verify-mureka.cjs` readiness check passed. The temporary Studio
node_modules symlink was removed. No live API, push, PR or deployment occurred.
Current inventory and routing totals are in [Skill routing](SKILLS.md#offline-routing-verification).

For verification set `RENDERHAUS_SECRETS_NAME=""` and all provider dry-run flags
to true, including the new `MUREKA_DRY_RUN`. New configuration is
`MUREKA_MODEL=mureka-9.5`; the existing `FAL_KEY` is the only provider secret needed.
No direct Mureka secret is required. Non-MP3 validation requires ffprobe in the
provider runtime; it is not bundled by the Lambda zip builder.
