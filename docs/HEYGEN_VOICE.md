# HeyGen Voice internal clone candidate

HeyGen Voice is proposed and inactive. ElevenLabs `voices_ivc_create` followed by
`eleven_v4_turbo` remains the clone default. `eleven_v4_turbo` remains the stock-voice
TTS default without a HeyGen exception. This branch builds consented instant cloning,
completed speech, project-scoped handles, the internal candidate gate, and mocked checks.
Live use is blocked. No provider request or key was needed during development.

## Tools and contracts

The existing HeyGen Gateway target exposes these additional tools.

| Routing ID | Gateway tool | Key arguments |
| --- | --- | --- |
| `heygen_voice_clone` | `HeyGen___voice_clone` | `reference_audio_url`, measured `reference_duration_seconds`, `reference_size_bytes`, `reference_format`, `name`, `subjects`, `consent_confirmed`, `consent_record_id`, `account_id`, `workspace_id`, `project_id` |
| `heygen_voice_tts` | `HeyGen___voice_tts` | saved `voice_id`, `text`, `language`, the same account/workspace/project scope, optional `model`, `expressiveness_boost` |
| Poll helper | `HeyGen___get_voice_status` | saved `voice_id` and the same scope |

Clone mode defaults to `instant`. `mode=professional` fails with an explicit out-of-scope
message. The adapter supports one public HTTPS MP3, WAV or OGG recording, up to 100 MiB.
Inline base64 and vendor asset IDs are outside this adapter's supported input subset.
Record the actual reference duration and bytes. Only the first 180 seconds are used.
The vendor requires URL fetching within 30 seconds and rejects silent recordings.

Require a named owner in `subjects`, `consent_confirmed=true`, and an opaque
`consent_record_id`. Recorded consent covers cloning, uploading the reference, and vendor
processing/data use. Spending approval is separate. Contracts reject invalid requests before
approval or provider I/O. The approval card identifies the owner, consent record, upload to
HeyGen on activation, possible vendor training, and the cost or unknown estimate.

Clone submission is `POST /v3/models/audio/voices`, with `mode`, `name`, `audio` containing
one URL item, optional `language`, `similarity`, and `remove_background_noise`.
The response is `202` with `data.voice_id`. Poll
`GET /v3/models/audio/voices/{voice_id}` once per tool call. Vendor states are `PENDING`,
`ACTIVE`, and `FAILED`. No polling loop or automatic resubmission is hidden in the tool.
A deterministic idempotency key scopes a submission to its reference, consent, and project.

Completed speech is `POST /v3/models/audio/tts`, with `model=heygen-voice-1`, `voice_id`,
`text`, `language`, and optional `expressiveness_boost`. This endpoint waits synchronously
and returns `data.audio_url` and `data.duration`; it has no TTS job poll.
Text is 1-5000 nonblank plain-text characters. Expression is 0.0-1.0, default 1.0.
Instant clones reject seed, speed, pitch and SSML. Both speech endpoints have a documented
30 requests/minute/member limit. SSE streaming is out of scope.

The completed artifact is a 44.1 kHz mono PCM16 WAV. Downloads enforce public hosts, no
redirects, bounded bytes/time, complete PCM data, and atomic local saving. Successful
`output_path` results use the ordinary Studio audio asset registrar. Dry-run speech saves a
deterministic one-second silent WAV marked `status=dry_run`, `placeholder=true`, and
`cost_usd=0`. It is not generated speech or a deliverable, and Studio does not register it
as completed media. The mock WAV was opened with Python's WAV reader; browser playback
remains untested.

Clone manifests are stored beneath `RENDERHAUS_MEDIA_DIR/audio/.voices/<scope hash>/`.
The scope includes authenticated account, workspace and project IDs. The host rejects
caller-supplied scope that differs from Studio identity. Poll and TTS require a saved
consented instant clone in that scope. Signed URL queries are excluded from saved manifests
and previews. Clones cannot cross projects or accounts. Dry handles remain previews after
configuration changes. Hosted durable project storage must be completed before live activation.

## Internal routing gate

`HEYGEN_VOICE_AB_GATE` accepts `off` or `internal`; every other value behaves as off.
It defaults to off. `HEYGEN_VOICE_AB_USERS` is a comma-separated allowlist of authenticated
Studio user IDs. Missing identity or an empty allowlist disables automatic candidate routing.
The host supplies identity separately from model tool arguments. An argument or setup note
cannot grant internal access.

Selection remains explicit request, then exception predicate, then default. An explicit
HeyGen Voice request can select a dry preview with the gate off. A named ElevenLabs request
always uses ElevenLabs, including during the internal A/B. Stock voices stay unchanged.
The `voice_clone` capability retains its ElevenLabs default and lists HeyGen as a gated
candidate. The separate `cloned_tts` capability holds the cloned-speech candidate without
modifying stock TTS exceptions. Outcome records label the candidate `heygen_voice_internal`.

With the internal gate enabled, clone requests use HeyGen then HeyGen speech. For scripts
that need text normalisation, cloned speech selects ElevenLabs. Combined clone/read requests
use ElevenLabs for both operations when the script has this weakness, preserving voice-ID
compatibility. HeyGen voice IDs cannot be sent to ElevenLabs.

`needs_text_normalisation` is a conservative deterministic predicate. It flags any digit
and common shorthand/honorifics, including phone numbers, dates, units, `Dr.`, `ASAP`, and
`3.5 GB`. Routing checks supplied `text`, quoted script text, or script text after a colon.
Recording duration in the surrounding instruction is not speech text. Already expanded
plain prose can take the candidate route. A `text_normalised` boolean alone cannot override
unexpanded text. No LLM normaliser or extra paid pre-pass is implemented.

RT-171, RT-172, and RT-173 are now active offline routing fixtures with explicit gate/user
setup. RT-171-OFF covers the unchanged default. Source status stays `proposed` for the
workbook rows; passing deterministic fixtures does not promote the model on quality.
The fixture has 224 rows, 188 active and 36 unchanged skips. Provider inventory remains 16,
Gateway tools increase from 115 to 118, and packaged skills remain 27.

## Official evidence read 2026-10-09

| Evidence | Result | Source |
| --- | --- | --- |
| Instant endpoint, fields, formats, sizes, first-three-minute behavior, asynchronous states | Verified in the instant guide. The generated reference OpenAPI still includes a professional-only mode enum despite documenting instant creation. The explicit instant guide defines this adapter's subset. | [Instant guide](https://developers.heygen.com/docs/voices/heygen-voice-instant-clone.md), [Clone reference](https://developers.heygen.com/reference/create-or-retrain-an-audio-voice.md) |
| TTS model, character limit, synchronous result, WAV encoding, instant-only controls | Verified. | [Speech guide](https://developers.heygen.com/docs/voices/heygen-voice-speech.md), [TTS reference](https://developers.heygen.com/reference/generate-model-speech.md) |
| Creation fee | Free during preview only. Non-promo creation fee is UNVERIFIED. | [Voice model guide](https://developers.heygen.com/docs/models/heygen-voice.md) |
| Non-promo character price and promotion | UNVERIFIED. API pricing redirects to an account dashboard. The public help table's Starfish rate is a different engine. | [API pricing](https://www.heygen.com/api-pricing), [API pricing help](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained) |
| Model licence | Closed weights; commercial API governed by HeyGen service terms. Paid-plan output rights are described in section 3. Free-plan commercial output is prohibited. API account/plan applicability needs confirmation before activation. | [Terms](https://www.heygen.com/terms) |
| Upload data use | Terms permit uploaded-content training; privacy describes inputs and an opt-out process. A Voice-specific no-training guarantee is UNVERIFIED. | [Terms](https://www.heygen.com/terms), [Privacy](https://www.heygen.com/privacy) |
| US customers | No US prohibition found in terms. US incorporation/processing supports general availability; Voice-specific account access is UNVERIFIED. Export restrictions still apply. | [Terms](https://www.heygen.com/terms), [Privacy](https://www.heygen.com/privacy) |
| Comparative evaluation | Public terms restrict benchmarking/comparative access. Obtain written permission or applicable negotiated terms before a live blind A/B. | [Terms](https://www.heygen.com/terms) |

Both model outputs have `training_eligible=false`. Commercial output use does not establish
a grant to train Renderhaus models. No AGPL or non-commercial upstream implementation or
weights were imported. The adapter uses the existing commercial API transport.

`HEYGEN_VOICE_LIST_USD_PER_MILLION` and `HEYGEN_VOICE_CLONE_LIST_USD` remain `None` in
billing. Unknown quotes stay unknown; dry-run billing is zero. Tests inject a hypothetical
list rate to verify `characters * list USD / 1,000,000`, independently of any promotion.
The proposal's $30, $15 and 50% promotion through October 31 are leads only and are not rates.
`live_blocker` prevents requests even with the dry flag false; there is no environment switch
to approve unverified prices, rights, or evaluation access. A future activation change must
replace the blocker only after its prerequisites are verified.

## Live-activation checklist

1. Obtain permission for comparative testing under HeyGen terms and confirm paid API plan
   output rights, Voice availability for US accounts, upload retention, and training opt-out.
2. Verify official non-promo instant character price and creation fee. Record source URLs
   and read dates. Add those rates and preserve list-price estimates through promotions.
3. Complete durable account/project voice manifests and output storage for hosted workers.
   Verify recovery/idempotency after uncertain submissions and interrupted downloads.
4. Use the same eight consented reference voices for both providers. Pair scripts and recording
   conditions. Randomize arm labels and presentation order, collect blind votes, and record
   identity, naturalness, intelligibility, pronunciation errors, latency, and failures.
5. Include abbreviation-heavy scripts with phone numbers, dates, units, honorifics, and
   shorthand. Measure the exception and expanded-text variant. The candidate must improve
   the intended cloned-voice quality without unacceptable pronunciation regressions. Review
   results internally before promotion; fixture passes are not blind votes.
6. Supply `HEYGEN_API_KEY` through the existing environment/Secrets Manager path. No new
   secret name is needed. Keep `HEYGEN_VOICE_DRY_RUN=true` until a separately reviewed
   activation change permits live use. Avatar `HEYGEN_DRY_RUN` is independent.
7. For the permitted internal trial, set `HEYGEN_VOICE_AB_GATE=internal`, allowlist actual
   user IDs in `HEYGEN_VOICE_AB_USERS`, keep `HEYGEN_VOICE_MODEL=heygen-voice-1`, and only
   then set `HEYGEN_VOICE_DRY_RUN=false`. Obtain normal paid-audio approval and spending
   authorization. These settings alone cannot clear this branch's code blocker.
8. Validate Studio approvals, rejection, account isolation, persisted clone reuse, and actual
   WAV playback through Comet with the real backend. Keep the gate off for customer routing
   until the internal trial has been reviewed. Setting the gate back to off restores default
   clone routing. Stock-voice TTS stays ElevenLabs throughout.

## Validation

Mocked contracts, transport, consent, ownership, routing, pricing math and native approval
checks are in `tests/test_heygen_voice.py`. Full verification commands and outcomes are
recorded in [the decisions file](heygen-voice-decisions.tsv).
Comet browser E2E is blocked because that browser cannot be controlled in this environment,
as specified by the user. Live provider checks and blind votes were not performed.
