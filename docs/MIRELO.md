# Mirelo picture-synced SFX

`mirelo_v2a` remains the capability-map SFX default and maps to `Fal___mirelo_v2a`.
SFX 2.0 replaces 1.6 as the default. Explicit requests precede the text-only exception
and default. Confidential metadata does not change routing. ElevenLabs SFX remains
the text-only exception. No other provider defaults change.

## Verified endpoints and contracts

Official sources were read on **2026-10-15**. SFX 2.0 launched after the original
October 8 capability map, so its verification date cannot be October 8 or 9.

| Selection through `model` | Output | Duration | Role |
| --- | --- | --- | --- |
| `mirelo-ai/sfx2.0/video-to-audio` | Audio bed | 1-600 seconds | Default |
| `mirelo-ai/sfx2.0/video-to-video` | Muxed MP4 | 1-600 seconds | Explicit output selection; Studio video node |
| `mirelo-ai/sfx1.6/video-to-video` | Muxed MP4 | 1-60 seconds | Explicit legacy A/B selection |

The [2.0 audio schema](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx2.0/video-to-audio),
[2.0 video schema](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx2.0/video-to-video)
and [legacy schema](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx1.6/video-to-video)
verify these IDs and wire contracts. No ID or API remains UNVERIFIED for SFX 2.0.
Live transport, playback and output quality remain untested.

Both 2.0 endpoints accept authorized `video_url`, optional `text_prompt` up to 2000
characters, `negative_prompt` up to 1000, `preserve_speech` default true, `duration`,
`num_samples` from 1 through 4, and optional `seed`. Renderhaus defaults to one sample;
fal defaults to two. Match duration to measured footage. The vendor clamps to video
length and uses windows above 10 seconds. Sub-second video is unsupported.

Audio output supports WAV by default, MP3, AAC and FLAC. Optional bitrate applies only
to lossy formats. MP3 accepts the documented CBR values from 32 through 320 kbps;
AAC accepts 32 through 256. Video output rejects audio encoding controls. Legacy
rejects speech preservation, negative prompts and encoding controls before HTTP.
Never silently discard a requested control or fall back to the old version.

[Mirelo's announcement](https://mirelo.ai/blog/mirelo-sfx-2-0) describes a post-stitch
sound pass that removes unwanted music and generates coherent effects around dialogue.
Speech preservation regenerates speech; it does not promise identical original bytes.
Listen for altered words, timing, ducking, missing speech and artifacts.

Submit once, retain the returned job ID and poll the existing `Fal___get_video_task`.
The endpoint in the handle determines output kind, including saved 1.6 jobs. Audio
results expose `audios`, primary `audio_url` and a downloaded audio `output_path`.
Video results retain `videos`, primary `video_url` and MP4 `output_path`. All variants
are URL-validated before download; the primary artifact is saved once. Dry handles
remain dry even if configuration later changes.

Studio registers audio as audio, including AAC. An audio bed cannot complete a video
request. Save the bed, then render the picture with that bed and poll the matching
final render. A source-picture render from before SFX completion cannot satisfy this
check. Audio-only completion requires a saved current audio version. For a combined
soundtrack with preserved speech, mute the original soundtrack to avoid restoring
unwanted music or doubling speech. Play the final artifact before delivery.

## Pricing and approval

The [official audio pricing page](https://fal.ai/models/mirelo-ai/sfx2.0/video-to-audio)
and [video pricing page](https://fal.ai/models/mirelo-ai/sfx2.0/video-to-video), read
**2026-10-15**, specify $0.010 per output second per sample from October 14 through
December 13, 2026 inclusive. The standard $0.015 rate resumes December 14. Billing
uses UTC dates, multiplies seconds by samples before rounding, and retains existing
billing calculations. Two ten-second samples cost $0.20 during the promotion and
$0.30 at standard rate before the existing platform fee.

The [legacy price page](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video), re-read
**2026-10-15**, specifies $0.01 per second. Its multi-sample multiplier remains
**UNVERIFIED**. Legacy samples 2-4 have unknown estimates and remain dry-run-only.
Quotes use published rates even in dry-run; dry-run ledger charges stay zero.

Both output modes retain the existing costed approval pause, including autonomous
runs under the paid-video policy. No approval exemption, global approval switch or
autonomous spend cap changes. Direct Studio invocation still requires chat approval.
Customer UI uses Studio Sound labels and total costs. Provider/model details and fee
breakdowns stay in internal provenance and billing records.

## Licence and configuration

The commercial badges on the official model pages and [fal terms](https://fal.ai/legal/terms-of-service),
read **2026-10-15**, support a commercial hosted API with `service-terms` and closed
weights. Source rights and required real-face/voice permissions remain required.
No Mirelo-specific recorded-consent API field was verified. US access is inferred
from fal's service terms; no model-specific US guarantee is published. No express
output-training grant was verified, so every version has `training_eligible=false`.
No weights or upstream code are copied. MMAudio remains retired for NC weights.

Reuse `FAL_KEY` from environment or Secrets Manager and `FAL_DRY_RUN`, default true.
There are no new secrets, flags, providers, tools or skill directories. Existing
`sync_secrets.py`, dispatch roles, Lambda routing and dry-run CI cover this upgrade.
Inventory is 21 providers, 140 Gateway tools, 42 skills and 342 routing rows,
336 active. Six unrelated dependency rows retain their skips. RT-195 is active;
existing Mirelo rows were already active. Docker skill count remains 41.

## Validation limits and A/B follow-up

Offline tests use mocked HTTP and scripted Deep Agents 0.7.23 calls. They cover
payloads, invalid controls, all output modes, promotion boundaries, known 2.0 and
unknown legacy sample pricing, persistence, routing, native approval/resume/rejection,
wrong-job rejection and final assembly ordering. They are not browser evidence.

Comet E2E remains blocked because this session exposes no Comet control. Access was
requested and the ignored `.renderhaus/e2e/` report records the blocker. The task
prohibits live or paid API calls. No generated artifact or real synchronization was
verified here.

Keep A/B-first. The announcement's comparisons are vendor-run, with no independent
SFX arena. Use approved short clips with dialogue plus unwanted music, action cues
and cuts. Compare 2.0 against explicit 1.6 and the text-only exception on appropriate
material. Record model, job, blinded listening preference and `ab_arm` through the
existing outcome recorder. Approval is spending authorization, not quality acceptance.
No paid A/B or quality promotion claim is part of this branch.
