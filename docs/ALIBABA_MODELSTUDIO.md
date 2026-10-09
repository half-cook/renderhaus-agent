# Wan 3.0 edit and extend on Alibaba Model Studio

Wan 3.0 is the capability-map default for `v2v_edit` and `extend`. Both use the
direct Model Studio adapter. They have no exceptions or Luma interim. Explicit
Aleph, Luma, and Wan VACE requests retain their existing tools and disclosure.

**LIVE USE BLOCKED BY PREVIEW LICENSING.** The adapter is usable for dry-run contract
previews only. [Preview Product Terms §1.1](https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-beta-testing-terms),
read 2026-10-09, limit the service to internal testing, research, and evaluation.
General output-use permissions do not override this restriction. Commercial customer
rights require separate verification before any live path can be enabled.

## US availability and verification limits

The [Wan API reference](https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference)
documents `wan3.0-video`, an asynchronous video-synthesis API, and a US Virginia
workspace endpoint. Its edit and extension modes use reference video and prompt
intent. The [model page](https://www.alibabacloud.com/help/en/model-studio/wan3-0-video)
lists US prices. These sources were read 2026-10-09. Model Studio is the chosen host;
there is no fal edit or extend fallback.

**UNVERIFIED: video-synthesis POST on `https://dashscope-us.aliyuncs.com`.**
This remains the configured default at Satya's request. The supplied parent precheck
authenticated a task GET on that host, but submitted no generation. Its compatible-mode
model list is not evidence of video availability. This task makes no keyed GET or POST.
The [regions page](https://www.alibabacloud.com/help/en/model-studio/regions), read
2026-10-09, lists US DashScope domains as unsupported. Live submission on the legacy
US host is therefore blocked. Documented regional workspace hosts are configurable,
but preview licensing also blocks live use on those hosts.
Account entitlement, preview access, live synthesis, and output quality remain unverified.

## Configuration

| Variable | Default or meaning |
| --- | --- |
| `MODELSTUDIO_DRY_RUN` | `true`. `false` still cannot bypass preview licensing or host/model gates. |
| `DASHSCOPE_API_KEY` | Required only for live calls. Use env or the existing Secrets Manager application secret. |
| `DASHSCOPE_REGION` | `us-east-1` for US Virginia. `ap-southeast-1` selects Singapore. This is separate from the AWS deployment region. |
| `DASHSCOPE_BASE_URL` | Full host override. Otherwise the workspace ID determines the host; otherwise US defaults to `https://dashscope-us.aliyuncs.com`. |
| `DASHSCOPE_WORKSPACE_ID` | Derives `https://<id>.us-east-1.maas.aliyuncs.com` or `https://<id>.ap-southeast-1.maas.aliyuncs.com`. |
| `DASHSCOPE_MODEL` | `wan3.0-video`. Other configured IDs are UNVERIFIED previews, with unknown price and no live access. |
| `RENDERHAUS_MEDIA_DIR` | Existing managed media root for task metadata and downloaded video. |

An explicit base URL wins over a workspace ID. Its region must agree with the configured
region and key. The Singapore legacy host is `https://dashscope-intl.aliyuncs.com`;
it does not work with Satya's US key. Workspace host configuration is preferred for both
regions. The adapter rejects non-Alibaba hosts and malformed paths before authentication.
There is no automatic cross-region retry or paid POST retry.

`scripts/sync_secrets.py` accepts these names through its existing generic filter.
Gateway deployment forwards them from `providers/catalog.py`. No secret is added to a
schema, commit, log, output metadata, or Docker build argument.

## Gateway tools

| Gateway tool | Canonical ID | Key arguments |
| --- | --- | --- |
| `ModelStudio___edit_wan3_video` | `wan3_edit` | `video_url`, `prompt`, measured `source_duration_seconds`, measured `source_fps`. |
| `ModelStudio___extend_wan3_video` | `wan3_extend` | The same source fields, plus `direction` of forward, backward, or both. |
| `ModelStudio___get_task` | Free poll | Saved `job_id`; `download=true` saves the completed MP4. |

Submit tools accept `duration`, `resolution`, `aspect_ratio`, `audio`, `prompt_extend`,
`watermark`, `seed`, optional image and audio reference arrays, measured audio durations,
`real_face_refs`, and `likeness_consent`. Defaults are smart duration `-1`, 1080p,
adaptive ratio, native audio, prompt expansion, and no watermark. Typed boundary validation
runs through registry dispatch and direct provider calls before any request.

The supported source is one MP4 or MOV of 1 through 15 seconds at 16 fps or greater.
Optional references allow up to 10 images and 5 audio clips totaling at most 15 seconds.
Callers supply measured durations and frame rate. The adapter does not download inputs to
independently establish those measurements or validate every vendor pixel/file-size limit.
Vendor source limits are 100 MB per video and 240 through 4096 pixels per side.
The installed edit-v2v skill requires source inspection rather than invented metadata.

The [Wan guide](https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-guide),
read 2026-10-09, recommends `duration=-1` for edit source-length preservation. Extension
duration is the total output length. A 5-second source extended by 2 seconds uses `duration=7`.
Input plus output cannot exceed 30 seconds. Explicit extension output must exceed source length,
and extension uses adaptive ratio. Direction becomes prompt intent, never an API parameter.
The provider guarantees an edit or extension intent prefix in the submitted prompt.

Smart duration remains dry-run with an unknown quote. Any future permitted live call also requires an explicit
integer output duration. Actual usage is exposed by polling for comparison with the estimate;
automatic wallet settlement against vendor usage is not implemented. No generated artifact
is claimed from a dry-run or queued result.

## Pricing and approvals

Official list rates from the [model pricing page](https://www.alibabacloud.com/help/en/model-studio/wan3-0-video),
read 2026-10-09, are USD per billed video second.

| Region | 480p | 720p | 1080p |
| --- | --- | --- | --- |
| US Virginia | $0.041256 | $0.082513 | $0.165025 |
| Singapore | $0.05 | $0.10 | $0.20 |

Both input and output seconds count. Native audio has no surcharge. At US 1080p, the
5-second source and 7-second output example costs $1.9803 before Renderhaus fees.
Existing cent rounding and the platform fee yield $2.57 in the approval card.
Unknown durations/models stay unknown. Unsupported hosts never receive a live request.

Paid edit and extend tools pause with provider, model, selection reason, and estimated cost
in ordinary and autonomous Deep Agents runs. Native checkpointer/thread state and
`Command(resume=...)` retain approve/reject recovery. `APPROVAL_EXEMPT_TOOLS` and the
autonomous spending cap are unchanged. The existing premium approval switch still applies.

## Jobs, output, and licence

Submission uses `X-DashScope-Async: enable`. Polling reads the task endpoint once per call.
The host polls at least 15 seconds apart. PENDING and RUNNING stay incomplete; failed,
canceled, or unknown tasks require inspection. Output URLs expire after 24 hours. Download
uses an unauthenticated client and persists a cached MP4 with atomic file replacement.
Saved provenance carries the model, host/region, job mode, estimate, and training restriction.

The model has closed weights under proprietary `service-terms`. General terms allow
conditional output use, but the preview licence restricts this model to internal evaluation. [Alibaba product terms §4.48](https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-product-terms-of-service-v-3-8-0),
read 2026-10-09, require rights and consent for submitted personal material and restrict
using outputs to develop competing products or models. Renderhaus sets
`training_eligible=false` for both tools, polling, model policy, and outcome records.
Real-face or voice likeness references require explicit permission acknowledgement.
Product Terms §3.14 gives the [Preview Product Terms](https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-beta-testing-terms)
priority for preview products. §1.1 is a blocking customer-use restriction, so the adapter
has no environment flag to override it. Additional commercial rights or general availability
must be verified before changing that policy. Vendor no-training commitments do not grant
Renderhaus output-training rights.
No vendor code, model weights, AGPL code, or non-commercial implementation is copied.

## Validation

Provider HTTP and downloads use fakes. Tests cover request bodies, regional prices,
validation failures, dry-run isolation, status transitions, output persistence, default
routing, consent, and native autonomous approve/reject recovery. The starting suite had
852 tests and 40 skips. Final validation ran **893 tests, 850 passed and 43 skipped**.
Ruff, offline CI packaging/schema checks, and Studio TypeScript typecheck passed. The
temporary Studio dependency link was removed. The supplied Python venv was empty;
ignored local links expose existing deepagents 0.7.23 packages and Ruff without downloading.
This environment bootstrap is not committed or part of deployment. Details are in [decisions](alibaba-modelstudio-decisions.tsv).

Three existing fixture rows for `wan3_edit` and `wan3_extend` now name ModelStudio
instead of Luma. They were active through the interim and now remain skipped with the
preview licence blocker. No skipped row is activated. There are 81 active fixture rows and
41 skips, including the 38 unchanged provider or workflow dependencies. `modelstudio.routing.csv` was absent; the read-only capability-map
CSV was inspected and remains unchanged.

Comet browser E2E is **blocked**. This environment has no controllable Comet session, and
the task prohibits live provider requests. The blocked receipt is recorded under ignored
`.renderhaus/e2e/` with `scripts/browser_e2e_hook.py`. No browser success, live generation,
or artifact playback is claimed. No push, PR, or deployment is performed.
