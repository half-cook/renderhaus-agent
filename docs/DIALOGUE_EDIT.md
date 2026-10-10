# Sync dialogue editing

`dialogue-edit` changes/removes words in existing footage using the existing Sync provider.
It preserves canonical `sync3_lipsync` and model `sync-3`; dialogue generation is a Gateway
variant. Presenter length does not select HeyGen for word edits. Confidential projects
use the same routing. Full re-dubs, new talking shots and silence/filler edits retain their
existing skills. Capability defaults/exceptions are unchanged.

## Gateway contract

| Tool | Required arguments / behavior |
| --- | --- |
| `Sync___transcribe_video` | `source_video_url`, measured `source_duration_seconds`, `speaker_count=1`, `subjects`, `consent_confirmed=true`; POST `/v2/transcriptions` with `maxSourceSeconds=600`. |
| `Sync___get_transcription` | `transcription_id`; GET `/v2/transcriptions/{id}`; immutable word IDs/timestamps. |
| `Sync___create_dialogue_edit` | Source/consent fields, `transcription_id`, `edits`, stable `action_id`; POST `/v2/dialogue-edits` creates the preview. Optional `voice_id`, `rerun_of_job_id`. |
| `Sync___get_dialogue_edit` | `dialogue_edit_id`; GET `/v2/dialogue-edits/{id}`; preview audio/duration, partial state, slots and rollout flags. |
| `Sync___create_dialogue_video` | Source/consent fields, `dialogue_edit_id`, measured `source_fps`, `preview_duration_seconds`, `preview_reviewed=true`, stable `idempotency_key`; optional `accept_partial`, measured source dimensions. POST `/v2/generate` with sync-3, original video and `dialogueEdit: {id}`. |

Strict typed contracts run before paid requests. Only whole videos of at most 600 seconds
and one speaker are accepted. Window fields and unknown arguments are rejected. The adapter
rechecks fetched transcript speaker/window metadata, word IDs, non-overlap and contiguous
removals. It sends the unchanged server transcript rather than an agent-authored copy.
Changes use `{kind: "change", wordId, replacement, pronunciation?}`; removals use
`{kind: "remove", wordIds: [...]}`; 1–100 operations. Only edited spans are re-spoken in
the cloned source voice. The user must listen and approve before video generation.
Completed previews expose vendor `previewAudioUrl` and normalized `audio_url` so Studio
can ingest/play them. A usable partial preview is registered with its partial status.
Preview job IDs are recorded in tool events for recovery.
Partial completion requires explicit `accept_partial=true`. Measured preview duration
must match the fetched preview before generation.

Sync storage is required. Only the official example host `assets.sync.so` is verified and
allowed. External/local sources need the documented upload/register workflow outside this
skill. No automatic upload or invented storage URL is added; other Sync storage hosts are TODO.

## Approval, billing and configuration

Dialogue APIs use direct Sync even when ordinary lip sync uses `SYNC_TRANSPORT=fal`.
They reuse `SYNC_API_KEY`, `SYNC_DRY_RUN` (default true), `SYNC_DIRECT_AUTHORIZED` (default
false), the job store and existing video poll/download. No new provider, key or dry-run
flag is added. Optional new `SYNC_DIALOGUE_PREVIEW_COST_CENTS` is forwarded by the provider
catalog and accepted by `scripts/sync_secrets.py` through its generic config filter.

Transcription uses no generation credits; GETs are unbilled. Preview and video pause
separately with cost and voice/likeness consent, including autonomous runs and a disabled
general premium approval switch. Canvas invoke rejects both paid tools. Approval exemptions
and spending caps are unchanged. Unknown cost cannot pass a spend cap.

Official sources read **2026-10-10**, the actual verification date:

- [Sync pricing](https://sync.so/pricing): base legacy sync-3 **$0.00534/output frame**;
  also prints $0.13340/s at 25 fps. Dialogue quotes count output frames, round provider
  cents up and add the existing 30% platform fee. Ten seconds at 25 fps estimates
  $1.34 provider + $0.40 fee = **$1.74**.
- [Billing](https://sync.so/docs/product/billing) confirms output-frame billing.
  `SYNC_BILLING_PLAN=legacy_base` is required; credit/negotiated account rates are unknown.
  Subscription, storage, discounts and taxes are excluded. Ordinary lip-sync billing is retained.
- Preview-create rate is unpublished: **TODO/unknown** by default. Live preview is blocked
  without a positive integer operator-confirmed `SYNC_DIALOGUE_PREVIEW_COST_CENTS` quote.
  This configuration is an operator quote, not a published rate.

## Recovery and fallback

Preview POST has no documented idempotency support. Persist action/fingerprint before POST.
Timeouts, connection drops and successful responses without usable IDs return
`submission_unknown`, `next_action=check_status_or_ask_user`. Never auto-retry preview
creation. Replaying the action or identical edits under another action ID in the same Studio
session starts no duplicate. Reconcile the dashboard before a deliberate, separately approved
rerun. Idempotent GETs may retry. Video saves and reuses its supported Idempotency-Key.
The billed Gateway preserves uncertain preview state and its charge for operator
reconciliation, including structured errors or dropped Gateway responses. Confirmed
refusals follow the existing refund path; spend-cap behavior is unchanged.

422 `dialogue_edit_retime_required` returns `requires_audio_fallback`, disclosure and
`next_tool=Sync___lipsync_video`. Obtain independent approved speech/audio, approve its cost
and the regular Sync generation. Exact source-voice preservation is no longer guaranteed.
The guide forbids using preview audio as ordinary audio to bypass rollout. No unapproved
fallback is started. Removal-too-large exposes safe `dialogueEditSection` metadata for a
smaller, separately approved preview.

Poll accepted videos via `Sync___get_video_task` with `download=true`. Downloaded MP4 and
provenance must exist before completion. Preview audio, queued jobs and dry results cannot
finish a video. Open/play actual media and obtain visual review before customer delivery.

## Licence, evidence and TODOs

sync-3 is proprietary, `license=service-terms`, `weights_license=closed-weights`, and
`training_eligible=false`. [Sync terms](https://sync.so/terms), read 2026-10-10, require
upload rights and voice/likeness permission and restrict competitor/customer integration
without express written authorization. `SYNC_DIRECT_AUTHORIZED` records that authorization.
The upload-use grant includes service improvement; no clear output-training grant exists.
No weights, AGPL code or non-commercial code are added. Ordinary fal transport retains its
separate host terms. The [MIT MCP reference](https://github.com/synchronicity-labs/mcp-server/blob/main/LICENSE)
was consulted; no code copied or vendored.

Official API sources, each read 2026-10-10:

- [Dialogue guide](https://sync.so/docs/developer-guides/dialogue-editing)
- [Create transcription](https://sync.so/docs/api-reference/api/transcriptions-api/create)
  and [get transcription](https://sync.so/docs/api-reference/api/transcriptions-api/get)
- [Create preview](https://sync.so/docs/api-reference/api/dialogue-edits-api/create)
  and [get preview](https://sync.so/docs/api-reference/api/dialogue-edits-api/get)
- [Generate](https://sync.so/docs/api-reference/api/generate-api/create)
  and [idempotency](https://sync.so/docs/api-reference/guides/idempotency)
- [Upload/register](https://sync.so/docs/developer-guides/asset-uploads)
- [MCP reference repository](https://github.com/synchronicity-labs/mcp-server)

Supplied `.md` links returned 403; official extensionless pages verified the schemas. No added
model ID is unverified. Written authorization, account rollout/plan entitlement, actual
invoice rounding, preview price and additional storage hosts remain TODOs/unverified offline.

RT-157–RT-159 are active, authored from the brief/draft because those IDs and dialogue rows
were absent from both the starting fixture and supplied CSV. Five existing skips remain:
HyperFrames overlay (one, provider pending), product-demo capture (three, `cutaway_record`
provider pending), exact end-card OCR (one, semantics unverified). Inventory: 16 providers,
125 Gateway tools, 32 skills and 243 cases
(238 active, five skipped).

Tests use fake models and mocked HTTP without keys/live providers. Comet E2E is **blocked**:
browser control is unavailable here and the user requires offline work. Ignored
`.renderhaus/e2e/` records incomplete validation. See [decisions](dialogue-edit-decisions.tsv).

## Changed files

| Area | Files |
| --- | --- |
| Sync implementation | `providers/sync/dialogue.py`, `providers/sync/dialogue_contracts.py`, `providers/sync/api.py`, `providers/sync/contracts.py` |
| Gateway/provider wiring | `providers/contracts.py`, `providers/catalog.py`, `providers/registry.py`, `configs/gateway/sync.tools.json`, `scripts/sync_secrets.py` |
| Agent routing/approval/playback | `agent/deep_agent/routing.py`, `agent/deep_agent/routing_policy.json`, `agent/deep_agent/runner.py`, `agent/gateway_executor.py`, `agent/studio_agent_next.py` |
| Skills | `agent/deep_agent/skills/dialogue-edit/SKILL.md`, `agent/deep_agent/skills/lipsync/SKILL.md` |
| Billing/Studio | `server/billing_rates.py`, `server/studio.py` |
| Tests/inventory | `tests/test_dialogue_edit.py`, `tests/test_dialogue_edit_host.py`, `tests/test_skill_routing.py`, `tests/fixtures/skill_routing.json`, `scripts/ci_check.py`, `.github/workflows/deploy.yml`, `Dockerfile.agentcore` |
| Documentation | `docs/DIALOGUE_EDIT.md`, `docs/dialogue-edit-decisions.tsv`, `docs/SYNC.md`, `docs/SKILLS.md`, `docs/DEEP_AGENT.md` |

The existing Lambda dispatch, media role/DISPATCH_TARGETS, Sync secret, ordinary Sync
polling and Studio sync-3 labels are reused. No new canvas model choice is needed.

## Offline verification, 2026-10-10

Tests were committed failing before their implementation/fixes. Starting branch: 2,067
tests, seven existing skips, passed. Final full suite: **2,139 tests, seven skips, passed**.
Focused dialogue checks: **69 passed** (46 mocked provider HTTP/contract tests, 23 host
routing, billing, native approval/resume/rejection, recovery and artifact checks).

Required `.venv/bin/ruff check agent lambdas scripts server providers` passed. Required
`scripts/ci_check.py` passed with empty `RENDERHAUS_SECRETS_NAME` and all supplied dry-run
flags; it also forces existing Sync and other provider dry-run flags. Studio `tsc --noEmit
-p .` passed using the temporary node_modules symlink, which was removed. Schema drift
and whitespace checks passed. No new dry-run flag or secret; only optional quote config.

Comet remains blocked, recorded via `scripts/browser_e2e_hook.py record` in ignored
`.renderhaus/e2e/dialogue-edit-blocked.json`. No live provider, push, PR or deployment.
