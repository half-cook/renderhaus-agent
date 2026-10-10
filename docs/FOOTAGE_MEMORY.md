# Footage memory

Footage memory retrieves timestamped events from existing source footage. It adds five
`FootageMemory___` Gateway tools and one editor skill. All understanding backends are
mocked. No footage leaves the host, no API key is read, and no live model call is implemented.
Memory is retrieval evidence. A simulated answer or simulated verification is never proof
that a real segment contains the requested event.

## Tools and contracts

Every request requires `project_id`; `workspace_id` defaults to `local`. Source paths are
relative to a confined media job. IDs, paths, timestamps, collections and limits are parsed
with strict argument contracts before filesystem inspection or a backend invocation.
Absolute paths, URLs, traversal and escaping symlinks fail explicitly. Errors are fail-soft
payloads; a blocked operation is incomplete work.

| Gateway suffix | Key arguments | Behavior |
| --- | --- | --- |
| `footage_memory_status` | `job_id`, exactly one `path` or `folder`, optional `asset_version_id`, `question_count=1` | Local duration, frame rate, content hash, memory freshness and routing recommendation. |
| `footage_memory_build` | Source arguments, `depth="events"` or `"hierarchy"`, `window_s=30` (10–60), `stage="estimate"` or `"build"`, returned `plan_hash` for build | Estimate first. One backend call per new window; completed matching memory is reused. |
| `footage_memory_query` | `query`, optional asset-ID `scope`, `limit=10` (1–50) | Local deterministic retrieval. Hits include clip and hit IDs, seconds, speaker, snippet, kind, score, confidence and `verify_required=true`. |
| `footage_watch_answer` | `job_id`, `path`, `question`, optional `asset_version_id`, paired `t0_s`/`t1_s`, optional `verify_hit_id` | One short watch; verifying a hit requires a narrow window of at most 60 seconds from the same source version. Returns verified/refuted/ambiguous and refined timestamps. |
| `footage_clip_extract` | `job_id`, exactly one `hit_ids` or `windows=[{clip_id,t0_s,t1_s}]`, `handles_s=1` (0–10), `allow_unverified=false` | Local trimmed selects through fixed ffmpeg `trim`. Unverified hits and explicit windows refuse by default. |

Status, query and extraction are free local operations. Build and watch return the estimate
alongside the deterministic preview. Dry-run understanding does not prevent local inspection,
content hashing or an explicitly allowed local trim; it prevents all third-party analysis.
The extraction override is for callers inspecting uncertain material. The skill never sets
`allow_unverified=true`. Mock verification does not update an event's real verification state.
As a result, an offline simulated search cannot satisfy the skill's verified-select delivery.

Each footage source is bounded to 32 GiB. The fixed probe and trim operations use this
larger bound; other existing worker operations retain their 128 MiB bound. Folder ingestion is flat,
with at most 100 clips; nested directories are not traversed. A build supports at most 10,000
windows, each 10-60 seconds (30 by default). Each select is at most 600 seconds; the local
trim output is bounded to 16 MiB. Split larger inputs into smaller jobs and request a new
estimate rather than widening a limit. These limits are local safety bounds, not model limits.

The existing ffmpeg worker had no `trim` operation in this clone. This branch adds a bounded
trim operation to its allow-list, using the established job confinement and argv execution;
no shell, arbitrary filters or provider media generation are added. Lambda packaging does
not contain ffmpeg. Actual inspection and extraction need the host containing the job media
and installed binaries. Real selects are complete only when the saved clips open and play.

## Routing and approval

An existing current memory wins over another full watch. Without one, a single question on
less than 600 seconds watches directly; at 600 seconds or above, several questions, or any
folder of clips, build and query memory. More than 30 minutes always builds. Unknown duration
first proposes status and waits for its measured recommendation. Transcript filler/pause
cleanup remains `conversational-edit`; word replacement remains `dialogue-edit`; consistency
checks remain `continuity-qc` with `local_qc` as its default.

The build defaults to `stage="estimate"`. The estimate counts every window in assets without
completed matching memory, including all windows of an interrupted build. That count is
multiplied by `FOOTAGE_MEMORY_CALL_CENTS`, rounded upward to integer cents. An absent value
means unknown, labelled **UNVERIFIED**. A configured value remains an operator estimate,
not a published per-window price. The host binds approval to the returned plan hash, source
hashes/versions and current configuration. A changed plan needs another estimate. The tool
cannot grant itself approval. Long builds pause even in autonomous runs; a short watch keeps
the existing nonautonomous approval rule. Spend caps and approval exemptions are unchanged.

A retry may change window size. Incomplete memories remove obsolete windows, events and
search documents atomically; matching requested IDs survive. Future extension references
block deletion and roll it back. Completed memories are reused rather than repartitioned.
Identical clips in a folder share one build. Refreshing status after re-upload updates the
confined source pointer without discarding matching memory. Extraction uses a verified hit's
refined endpoints and handles, and rejects a changed source hash.

The tools store one per-project `video_index.sqlite3` with scoped assets, windows, events,
speakers, search documents and embeddings. The hierarchy derives from those same event
rows. There is no `<asset>.memory/` store and no parallel segment index.
See [Video index](VIDEO_INDEX.md) for schema, migrations, optional vector support and the
reserved segment-edit extension tables. Segment detection, masks, annotation features,
embeddings generation and live understanding remain out of scope.

## Backends, terms and pricing

The backend Protocol exposes `describe_window(window_media, prompt)` and
`answer(question, window_media)`. Structured outputs include timestamps, event kinds and
confidence. The registry contains deterministic `mock`, a `gemini` dry-run candidate reusing
`GEMINI_VLM_MODEL`, and disabled `qwen_omni`. The configured default for dry-run selection is
`gemini`; it is **not** a promoted understanding model. Setting dry-run false does not enable
live understanding.

Official sources re-read **2026-10-10**:

- [Google model index](https://ai.google.dev/gemini-api/docs/models) confirms `gemini-3.8-flash`.
  The dedicated model page was unavailable during this read; the index and video guide
  independently confirm the ID.
- [Video input guide](https://ai.google.dev/gemini-api/docs/video-understanding) documents
  the Interactions API video part (`type`, `uri`, `mime_type`), optional agentic processing,
  background submission and polling. This branch does not implement that live transport.
- [Official pricing](https://ai.google.dev/gemini-api/docs/pricing) lists $0.75/M input and
  $3.75/M output tokens including thinking through 2026-12-31, then $1.50/M and $7.50/M.
  No per-window rate is published: deriving a fixed footage call price remains **TODO**.
- [API terms](https://ai.google.dev/gemini-api/terms) govern the proprietary commercial
  service. Paid inputs/responses are not used to improve products; limited abuse logs remain.
  Competing-model training is prohibited. Set `training_eligible=false`.

Qwen Omni has no selected model ID or live transport here. Hosted model licence and price
remain **UNVERIFIED**. Alibaba Model Studio international terms must be checked for both
US and Canadian customers before any live use. The DASHSCOPE key on this box is US-region
only and must not be used for this candidate. The disabled registry entry rejects before
reading `DASHSCOPE_API_KEY` or making a call. Upstream's Apache licence covers its code and
workflow patterns; it does not grant rights to a hosted model or input footage.

Project settings use `allow_third_party_vlm` with an effective default of false. The host
reads the scoped settings file; a tool argument cannot change it. Stored confidentiality
does not affect quality-first model routing. The host denies future third-party analysis
for the existing Studio confidential-project flag even when local permission is enabled.
The footage-specific permission gate only
controls a future live third-party path, which this branch additionally blocks outright.
Every model, mock record and extracted select remains `training_eligible=false`.

## Offline A/B hook

`scripts/eval_footage_memory.py` and `providers.footage_memory.evaluation` score synthetic
held-out "find the moment" fixtures from `providers/footage_memory/fixtures.json`.
The fixture is generated in code; it contains no real footage or vendor data. Scoring matches
the same query and clip, accepts a returned start within two seconds of a label, and counts
each label at most once. Extra and duplicate predictions reduce precision; missed labels
reduce recall. JSON reports results per backend. External predictions can be scored offline.
These smoke scores test the evaluator and must not promote a default. The explicit
`footage_memory_ab` candidate gate requires a later real held-out comparison and reviewed
evidence before promotion.

## Configuration and provenance

| Setting | Default / requirement |
| --- | --- |
| `FOOTAGE_MEMORY_DRY_RUN` | `true`; host-enforced, separate from backend selection. |
| `FOOTAGE_MEMORY_BACKEND` | `gemini`; `mock` for offline tests; `qwen_omni` disabled. |
| `FOOTAGE_MEMORY_CALL_CENTS` | Empty/unknown; optional per-call estimate, always UNVERIFIED. |
| `RENDERHAUS_VIDEO_INDEX_ROOT` | `.renderhaus/projects`; scoped workspace/project storage. |
| `GEMINI_VLM_MODEL` | Existing shared `gemini-3.8-flash` configuration. |
| `RENDERHAUS_MEDIA_DIR` | Existing job media root. |

No new secret is needed. `scripts/sync_secrets.py` documents the configuration and adds no
key requirement. Tests never read `GEMINI_API_KEY` or `DASHSCOPE_API_KEY`.

Workflow ideas were adapted from
[Qwen-MM-Plugins at e469e92](https://github.com/QwenLM/Qwen-MM-Plugins/tree/e469e92dcd662ab0c4adc798fc50a094c832bfc0),
especially `omni-memory`, `video-memory`, window extraction, temporal merge and the derived
Root > SuperEvent > MacroEvent > Subgraph hierarchy. The read-only local clone and its
[Apache-2.0 licence](https://github.com/QwenLM/Qwen-MM-Plugins/blob/e469e92dcd662ab0c4adc798fc50a094c832bfc0/LICENSE)
were read on 2026-10-10. No source files were copied or vendored; the provider NOTICE records
pattern attribution. AGPL and non-commercial code/weights are not introduced.

Browser E2E is **blocked** because Comet is unavailable in this environment. Offline checks
cannot establish the Studio approval card or visible results. The browser record lives under
ignored `.renderhaus/e2e/`; no live provider work or paid API was attempted.
