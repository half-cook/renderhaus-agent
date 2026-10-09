# sync-3 lip sync

`sync3_lipsync` is the quality-first default for replacing speech on existing footage.
`Sync___lipsync_video` submits; `Sync___get_video_task` polls the returned `job_id`.
New generated talking shots use Seedance 2.5. Presenters/digital twins over 30 seconds
select pending HeyGen Avatar V unless the user explicitly requests Sync. Confidential
project metadata and price tiers have no effect on selection.

## Transport and terms

Fal is primary: its verified `fal-ai/sync-lipsync/v3` endpoint reuses the existing fal
queue and FAL key, advertises commercial use, and is available to US customers through
fal's API agreement. Direct Sync is a configurable alternative, with its own async
POST/GET generation API. Both use the verified `sync-3` model. Sources read **2026-10-09**:
[fal model](https://fal.ai/models/fal-ai/sync-lipsync/v3),
[fal API](https://fal.ai/models/fal-ai/sync-lipsync/v3/api),
[Sync model](https://sync.so/docs/models/sync-3),
[Sync API](https://sync.so/docs/api-reference/api/generate-api/create),
[Sync polling](https://sync.so/docs/api-reference/api/generate-api/get).

The model is a proprietary hosted service with `service-terms`, not an open-weight licence.
No vendor code or weights are copied. Fal permits incorporating its API into customer
solutions; input owners must have required rights and consents. Sync's direct terms restrict
competitive access, redistribution and certain integrations without express written permission.
Direct live requests are blocked unless `SYNC_DIRECT_AUTHORIZED=true` represents permission
already held by the operator. This flag cannot itself grant permission. Sources:
[fal terms](https://fal.ai/legal/terms-of-service), [Sync terms](https://sync.so/terms).

Every request identifies face and voice subjects with `subjects` and requires the literal
boolean `consent_confirmed=true`. This includes the replacement voice. The host refuses
missing consent before approval; the typed provider contract refuses it before paid work.
A spending approval is not likeness/voice consent. Synthetic subjects must also be identified
and their input rights acknowledged. ElevenLabs TTS and cloning retain their own consent gates.

LatentSync and LivePortrait remain retired. Explicit use requests are blocked rather than
loading their non-commercial InsightFace dependencies. InsightFace code is MIT, but its
provided training data and pretrained weights are for non-commercial research only.
Source read **2026-10-09**: [InsightFace licensing](https://github.com/deepinsight/insightface#license).

All Sync provenance has **`training_eligible=false`**. Commercial use does not grant training
rights. Sync's direct upload licence permits operation, improvement and advertising; no public
no-training promise was verified. Fal's API terms prohibit training/development use of client
content, including third-party providers except designated excluded or Pending Enterprise Ready
services. Verify the designation and contract before making any customer retention/no-training
promise. Source: [fal API data terms](https://fal.ai/legal/api-services),
[Sync User Content terms](https://sync.so/terms). ZDR is contract/enterprise dependent, not enabled
by this adapter. This task makes no claim about actual vendor training on an upload.

## Contract, pricing and approval

Required arguments: `video_url`, `audio_url`, measured `source_duration_seconds`, measured
`audio_duration_seconds`, measured `source_fps`, `subjects`, `consent_confirmed`.
Optional arguments: `sync_mode` (`cut_off`, `loop`, `bounce`, `silence`, `remap`), `model`,
`chunk_boundaries_seconds`, and optional paired measured `source_width`/`source_height`
(required by the host when a specific output resolution is requested). Unknown fields, invalid URLs, non-finite/non-positive timing,
ambiguous acknowledgement and unsafe chunk plans are rejected. Studio asset handles are
resolved by the existing host before dispatch. Unsupported model configuration remains
**UNVERIFIED**, dry-run only, with an unknown quote.

| Host | Verified usage rate | Billing basis |
| --- | --- | --- |
| fal | $8/minute | Result length; default `cut_off` uses the shorter input |
| Sync direct legacy Base | $0.133/s at 25 fps | Output frames, scaled by measured source fps |
| Sync direct credits/negotiated plans | TODO / unknown | Verify the account's current credit/rate contract |

Pricing read **2026-10-09**: [fal pricing](https://fal.ai/models/fal-ai/sync-lipsync/v3),
[Sync billing](https://sync.so/docs/product/billing). The existing platform fee is added.
Subscriptions, S3/storage, local concat compute and vendor rounding are excluded from this
usage estimate. `silence` uses the longer input; `loop`/`bounce`/`remap` use audio length.
Source: [Sync modes](https://sync.so/docs/developer-guides/sync-mode).
The documented rate is conditional on `SYNC_BILLING_PLAN=legacy_base`; other plans return
unknown. No promotional expiry is assumed.

Every Sync submission pauses with a host/model/cost/subject disclosure, including autonomous
runs and `RENDERHAUS_PREMIUM_VIDEO_APPROVAL=false`. Existing approval exemptions, free-tool
rules and the autonomous spend cap remain unchanged. A standalone revoice request can finish from a successfully downloaded Sync poll artifact.
Requests that add captions, overlays or assembly still require the existing renderer to finish.
Polling is free. Studio generation uses the agent workflow; the direct `/invoke` endpoint
refuses Sync submission so it cannot bypass cost approval. A standalone canvas generation
node is deferred until the canvas has an approval path. Model labels and tool discovery remain
available. Dry-run tools return
synthetic results and incur no paid request; they still exercise approval and consent.

## Duration and chunking

Sync's documented paid-plan single-input duration ceilings range from 60 seconds (Hobby)
to 1,800 seconds (Scale); free sync-3 is limited to 15 seconds. Fal's hard ceiling is
**UNVERIFIED** in its public model/API page. `SYNC_MAX_CHUNK_SECONDS=60` is a conservative
operational cap, not a vendor duration guarantee. Configure it to the authorized host/account
limit after verification; do not claim a higher plan allowance from the default.
Source: [Sync duration limits](https://sync.so/docs/models/lipsync).

For longer inputs supply measured silence/shot boundaries. Every resulting interval must fit
the cap. Chunking supports equal video/audio lengths with `cut_off` only; mismatched timing
and looping/remapping need a separate edit first. No arbitrary equal-width split is used.
Before paid submissions the adapter verifies ffmpeg/ffprobe, S3 and the existing approved
media-host download path, probes media, splits matching audio/video intervals and uploads
temporary parts. Polling preserves child job IDs, waits for all outputs and uses the existing
`server.projects.merge_video_paths` ffmpeg path to concatenate them. Partial submission failures
retain accepted job handles; do not blindly resubmit. A missing, non-video or truncated output is a failure, not success. Download validation checks
the MP4 container even where ffprobe is unavailable; it is not a playback or lip-timing check.

The existing concat path normalizes to **1280×720 at 24 fps**. The current Gateway Lambda zip does not include ffmpeg or the server concat module, so
hosted chunking refuses before paid work until those dependencies are supplied. Local
chunking can use the existing clone dependencies. Chunked lip-sync therefore has a
quality limitation compared with single-shot sync-3's advertised higher resolution. Use shorter
separate deliveries when preserving source resolution is required. Safe downloading currently
inherits Remotion's approved-host and file-size restrictions; configure exact hosts, never a
wildcard. No media download, ffmpeg execution or S3 upload occurs during dry-run.

Hosted finished media is published to the private S3 bucket. Polls return a fresh transient
URL; saved job metadata contains object keys and sanitized references, without signed URL
queries. A cold worker can recover the completed artifact without another generation.
Accepted provider handles remain available after local or remote persistence failures;
retaining a handle does not make an interrupted submission safe to repeat.

Direct webhooks are documented but not installed here; polling is the chosen completion path.
A future receiver must verify Sync's signature and keep its secret out of logs.
Source: [Sync webhooks](https://sync.so/docs/api-reference/guides/webhooks).

## Configuration

| Variable | Default / purpose |
| --- | --- |
| `SYNC_DRY_RUN` | `true`; new flag, also forced on by offline CI |
| `SYNC_TRANSPORT` | `fal`; alternate `direct` |
| `SYNC_MODEL` | `sync-3`; other IDs UNVERIFIED and blocked live |
| `SYNC_DIRECT_AUTHORIZED` | `false`; operator holds express written permission |
| `SYNC_MAX_CHUNK_SECONDS` | `60`; operational/account chunk cap |
| `SYNC_BILLING_PLAN` | `legacy_base`; unknown direct plans have unknown quotes |
| `SYNC_API_KEY` | New secret, only needed for authorized direct transport |
| `FAL_KEY`, `FAL_DRY_RUN` | Existing fal credential/guard; fal remains dry if either guard is true |
| `AWS_S3_BUCKET` | Existing private bucket; durable job manifests required for hosted live calls, plus chunk parts/results |
| `REMOTION_LOCAL_MEDIA_HOSTS` | Existing exact approved media download hosts |

Use environment/Secrets Manager only. `scripts/sync_secrets.py` includes Sync in the provider
catalog; no secret values are stored in source. Do not turn off guards in this task.
Deployment wiring is prepared locally, with no deployment, push or PR.

## Verification limits

Mocked HTTP tests cover consent/type validation, dry-run isolation, fal/direct schemas,
status/error polling, chunk preparation, partial failures and final output validation.
Routing tests cover confidential metadata, the generated-shot exception, long presenters,
host quotes and training refusal. Native Deep Agents tests exercise approval, fresh-worker
resume and rejection with a scripted model, using installed deepagents 0.7.23.
These checks do not prove a paid artifact or lip timing. Comet browser E2E is **blocked**:
the user reports Comet unavailable and prohibits paid/live requests. No browser actions or
live artifact playback are claimed. See [decisions](lipsync-sync3-decisions.tsv).

The 33 remaining fixture skips are listed with their exact reasons in the
[capability-map fixture table](CAPABILITY_MAP.md#skills-and-routing-fixtures). They include
32 pending-provider rows and one Seedance extension-semantics case; no Sync row stays pending.

## Final offline checks

On 2026-10-09 the final implementation passed:

- `.venv/bin/ruff check agent lambdas scripts server providers`.
- `.venv/bin/python -m unittest discover -s tests -q`: **1,070 run, 1,035 passed, 35 skipped**.
- `.venv/bin/python scripts/ci_check.py`: schema, inventory, dry-run dispatch/imports and Lambda packaging.
- `.venv/bin/python scripts/generate_gateway_schemas.py --check`: no schema drift.
- Studio `./node_modules/.bin/tsc --noEmit -p .`; the temporary dependency symlink was removed.

Tests and CI used `RENDERHAUS_SECRETS_NAME=""`, all requested provider dry-run flags, new
`SYNC_DRY_RUN=true`, and existing `OPENAI_IMAGES_DRY_RUN=true`/`MODELSTUDIO_DRY_RUN=true`.
No paid/live provider API was called. Native review independently checked 50 Sync provider,
62 fal and 18 host/approval tests, with no remaining important finding. The browser hook
recorded **blocked/pending** under ignored `.renderhaus/e2e/sync-browser.json`; supporting
checks do not replace Comet E2E. No real paid artifact playback or lip timing was verified.

Boundary Discipline placed consent and transport guards at host/provider boundaries. Model
the Domain supplied strict requests and recoverable job/chunk state. Sequence Verifiable
Units kept regression-test commits before implementation and verification before reporting.

## Changed files

43 files changed from the clone’s starting tip:

```text
.github/workflows/deploy.yml
Dockerfile.agentcore
agent/deep_agent/AGENTS.md
agent/deep_agent/routing.py
agent/deep_agent/routing_policy.json
agent/deep_agent/runner.py
agent/deep_agent/skills/audio-bed/SKILL.md
agent/deep_agent/skills/lipsync/SKILL.md
agent/gateway_executor.py
agent/studio_agent_next.py
configs/gateway/sync.tools.json
docs/CAPABILITY_MAP.md
docs/DEEP_AGENT.md
docs/SKILLS.md
docs/SYNC.md
docs/lipsync-sync3-decisions.tsv
docs/skills-drafts/lipsync.md
providers/catalog.py
providers/contracts.py
providers/fal/api.py
providers/registry.py
providers/sync/__init__.py
providers/sync/api.py
providers/sync/chunks.py
providers/sync/contracts.py
providers/sync/media.py
scripts/ci_check.py
scripts/sync_secrets.py
server/billing_rates.py
server/studio.py
server/studio_options.py
studio/lib/canvas/model-labels.ts
tests/fixtures/skill_routing.json
tests/fixtures/sync-video.mp4
tests/test_capability_evidence.py
tests/test_provider_ladder.py
tests/test_skill_routing.py
tests/test_sync.py
tests/test_sync_approval.py
tests/test_sync_constraints.py
tests/test_sync_delivery.py
tests/test_sync_studio.py
tests/test_sync_wiring.py
```
