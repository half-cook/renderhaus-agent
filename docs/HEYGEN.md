# HeyGen Avatar V

HeyGen Avatar V is the lipsync exception for presenter or digital-twin videos longer than
30 seconds. Explicit user requests take precedence. Existing-footage dubbing stays on sync-3.
Project confidentiality has no effect on routing. Canonical ID: `heygen_avatar_v`.

The adapter uses the official HeyGen v3 API with `engine.type=avatar_v`. It supports existing
eligible digital-twin **look IDs**, not photo avatars. `fal`'s `heygen/avatar5/digital-twin`
engine is UNVERIFIED and is not a configured transport. No third-party code, binaries or
weights are copied. [heygen-com/heygen-cli](https://github.com/heygen-com/heygen-cli) is an
Apache-2.0 request-shape reference, not a dependency or a source of vendored code.

## Tools and arguments

| Gateway tool | Arguments | Result |
| --- | --- | --- |
| `HeyGen___create_avatar_video` | Required: `avatar_id`, `duration_seconds`, `subjects`, `consent_confirmed`, `consent_record_id`. Either `script` with `voice_id`, or `audio_url`. Optional: `language`, `resolution`, `aspect_ratio`, `motion_prompt`, `model`. | Opaque saved `job_id`; async generation or incomplete dry-run preview |
| `HeyGen___get_video_status` | `job_id`, optional `download=false` | One poll; `download=true` saves completed MP4 media |
| `HeyGen___list_avatars` | Optional `limit=20`, `next_token` | One page of digital-twin look IDs and eligibility metadata |
| `HeyGen___list_voices` | Optional `limit=20`, `next_token` | One page of voice IDs and language metadata |

`avatar_id` is a look ID, not its avatar group ID. Live submission checks
`GET /v3/avatars/looks/{look_id}` for `digital_twin`, completed status and `avatar_v` in
`supported_api_engines`. The referenced group must have accepted recorded consent.
`POST /v3/videos` submits once; `GET /v3/videos/{video_id}` polls asynchronously.
Voice, motion, resolution and aspect ratio pass through the documented v3 body.
`language` maps to `voice_settings.locale`; no translation, avatar-creation or voice-cloning
tool is introduced.

The typed contract rejects missing consent, ambiguous booleans, unknown fields, invalid IDs,
non-finite duration and conflicting script/audio inputs before provider I/O. Script input
requires an explicit voice ID. Scripts have a 5,000-character ceiling and scenes a
1,800-second ceiling. Audio is limited to 600 seconds; HeyGen additionally documents a 50 MB
WAV/MP3 input limit. Audio must be publicly accessible. The adapter accepts only 720p/1080p
and the documented `16:9`, `9:16`, `4:5`, `5:4`, `1:1`, `auto` aspect ratios.
`duration_seconds` is measured audio length or a script estimate, **not** a render-length
control. The actual generated length determines vendor billing.

Sources read **2026-10-09**: [Avatar V](https://developers.heygen.com/avatar-v),
[create video](https://developers.heygen.com/reference/create-video),
[get video](https://developers.heygen.com/reference/get-video),
[video workflow](https://developers.heygen.com/generate-avatar-video),
[usage limits](https://developers.heygen.com/docs/usage-limits).

## Consent, commercial use and training

Every real face and voice must be identified in `subjects`, with literal
`consent_confirmed=true` and an opaque `consent_record_id`. An approval to spend does not
establish likeness consent. The reference identifies a consent record held outside this
request; it contains no recording URL, credentials or identity document. HeyGen's hosted
recorded consent flow belongs to the subject and operator. The adapter does not create
avatars or consent sessions, upload consent recordings, clone voices or use the enterprise
consent bypass. Live use requires the avatar group's `consent_status=accepted`.
Source: [recorded consent](https://developers.heygen.com/docs/avatar-consent), read 2026-10-09.

Avatar V has proprietary closed weights, recorded as `service-terms` with
`weights_license=closed-weights`. Paid content may be used commercially under
[HeyGen terms](https://www.heygen.com/terms), read 2026-10-09. Free Plan outputs carry
non-commercial restrictions. Live generation fails closed until `HEYGEN_API_PLAN` records
`paid_self_serve` or `enterprise`; an environment flag cannot grant commercial rights.
The separate API entitlement must be verified by the operator, even when the app has a paid plan.

HeyGen's [privacy policy](https://www.heygen.com/privacy) and
[trust and safety policy](https://www.heygen.com/trust-and-safety), read 2026-10-09, permit
non-enterprise uploads to improve/train models, with an opt-out through the vendor.
Enterprise customer data is excluded under the published enterprise policy. This adapter
cannot verify an account opt-out or negotiated contract. It does not promise no training.
All Renderhaus HeyGen provenance is **`training_eligible=false`**: no model-specific training
grant is relied on, and the continuity flywheel accepts approved Apache Wan assets only.

## Pricing and approval

Official Avatar V Digital Twin API PAYG pricing is **$7.20/minute ($0.12/s)**, charged per
actual generated second. Source: [HeyGen API pricing explained](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained),
read **2026-10-09**. This supersedes the map's $0.0667/s lead. The requested
[developer pricing URL](https://developers.heygen.com/docs/pricing) was not accessible;
the official Help Center billing article is the verified source. No promotional rate or
expiry is assumed. Enterprise negotiated pricing is TODO / **unknown**, never zero.

The existing 30% platform fee is added. A 90-second self-serve estimate is $10.80 provider
cost plus $3.24 fee, or $14.04. Script duration is an estimate; final vendor usage may differ.
Subscription, storage and local download costs are excluded. Dry runs charge zero but still
disclose the published estimate. API credits are separate from HeyGen app subscriptions.

Every generation pauses for cost approval, including autonomous runs and a disabled general
premium-video switch. Approval exemptions and the autonomous spend cap are unchanged.
Direct Studio canvas invoke refuses submission; use the agent workflow. Read-only listing
and polling are free. A saved completed MP4 can finish a standalone presenter request;
captions, overlays or assembly still require the renderer.

## Configuration and job recovery

| Variable | Default or purpose |
| --- | --- |
| `HEYGEN_API_KEY` | Secret for the `x-api-key` header; env or Secrets Manager only |
| `HEYGEN_DRY_RUN` | `true`; no provider HTTP calls, no playable output |
| `HEYGEN_MODEL` | `avatar_v`; other engine IDs are UNVERIFIED and forced dry-run |
| `HEYGEN_API_PLAN` | `unknown`; live paid-plan entitlement guard |
| `AWS_S3_BUCKET` | Existing hosted manifest and media storage |

The secret synchronizer accepts the new key and configuration. CI forces
`HEYGEN_DRY_RUN=true`. Job manifests preserve engine, duration estimate, consent reference
and provider identity across workers. They exclude scripts, API keys and signed media URLs. Audio references strip query strings
and fragments before storage. Completed hosted artifacts receive fresh temporary S3 URLs
for Studio registration and playback; those signed URLs are never stored in job manifests. Dry-run handles remain previews after a configuration change.

The adapter records submission before POST and uses a stable `Idempotency-Key`. An ambiguous
response becomes `submission_unknown`; it requires operator reconciliation rather than an
automatic paid retry. Preserve the returned handle and any accepted vendor video ID after a
persistence error. Polling never submits generation. The provider download path validates and
saves actual media before reporting `downloaded=true`.

## Validation and open limits

Final checks: 1,104 unit tests run (1,071 passed, 33 skipped), Ruff, dry-run CI/schema/ZIP
packaging and Studio TypeScript typecheck passed. There are 25 provider tests and nine wiring
tests. The temporary Studio node_modules link was removed.

Provider tests use fake HTTP only. Integration tests exercise routing, consent rejection,
native approval and fresh-worker approve/reject resume, manual invoke rejection, billing,
training policy and standalone artifact delivery. No paid/live provider request was made.

**Browser E2E is blocked**: Comet is unavailable in this environment. The real Studio
approval, refusal and artifact playback flow has not been exercised. Mock tests are not a
browser pass. The ignored report under `.renderhaus/e2e/` records this blocker.

Live account engine entitlement, custom-voice consent records, enterprise price, actual billed
usage reconciliation and vendor output playback remain unverified. The voice acknowledgement
covers supplied real-person voices but cannot query vendor voice consent from this contract.
The operator must verify paid API rights and consent before enabling live use. See
[decisions](heygen-avatar-v-decisions.tsv).
