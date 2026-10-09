# Topaz finishing

Topaz finishes existing video through fal. The capability IDs are `topaz_upscale` and
`topaz_interpolate`. Source media must exist before finishing. This adapter does not generate
replacement footage. Evidence for visual quality is thin and vendor supplied. A/B testing on
Renderhaus footage remains pending. `local_qc` remains the continuity-QC default.

## Tools and limits

| Gateway tool | Arguments and behavior |
| --- | --- |
| `Topaz___upscale_video` | Required `video_url`, measured `source_duration_seconds`, `source_fps`, `source_width`, `source_height`. `target_resolution` accepts 1080p or 4K, or `upscale_factor` accepts 1–4. Omit both for 2x. Default model is Starlight Precise 2.6. Optional `target_fps` is 16–60 and `softness` is 1–5. |
| `Topaz___interpolate_video` | Same source measurements. Supply `target_fps` of 16–120 or `fps_multiplier`; omit both for 60 FPS. Default model is Apollo. Chronos is the plain linear-motion FPS exception. Optional `slowdown_factor` is an integer from 1–8. Source dimensions are preserved. |
| `Topaz___get_video_task` | Poll the saved Topaz `job_id` once. `download=true` saves and validates the MP4. Never submits new work. |
| `Topaz___list_topaz_models` | Local documented catalog. No provider call and no claim of account access. |

Typed requests reject unsupported fields, contradictory controls, invalid measurements, source
videos over five minutes, and output beyond a 3840 by 2160 bounding box in either orientation.
`H264_output=true` defaults to a browser-compatible codec. fal's own default is H265.
Source asset handles are previews in direct dry-run calls. Studio resolves authorized handles
at its existing provider boundary before live submission. Unresolved handles cannot reach fal.

Explicit model requests precede the Chronos predicate and defaults. The shared executor checks
the submitted model, resolution, and FPS against the route. No tier or cheapest-price selection
exists. Stored `project.confidential` does not change selection. Demoted providers remain intact.

Every Topaz submit pauses with a cost estimate, including autonomous runs and when
`RENDERHAUS_PREMIUM_VIDEO_APPROVAL=false`. Approval exemptions and the autonomous spend cap
retain their existing behavior. Manual Studio invoke refuses Topaz submits and directs users
to the chat approval workflow. Polling and the local catalog are free.

A queued job and a dry-run preview are incomplete media. A standalone finishing request can
finish after a successful poll with a saved, valid MP4. Additional assembly, captions, graphics,
or music still require Remotion. Output provenance identifies Topaz and the selected model.
Job handles retain model identity across process restarts. Outputs never enter continuity training.

## Transport and configuration

fal is primary because the existing client supports asynchronous submit, status, result, and
artifact download. Its prices are in dollars. Both `TOPAZ_DRY_RUN` and `FAL_DRY_RUN` default
true. Live submission requires both false and `FAL_KEY` from the environment or the existing
Secrets Manager application secret. CI forces both flags true. No new secret is required.

Topaz direct is deferred rather than added as a second transport option. The
[official video quickstart](https://developer.topazlabs.com/getting-started/video-quickstart),
read 2026-10-09, uses `X-API-Key`, free `POST /video/` estimates, `PATCH /video/{id}/accept`,
presigned uploads with ETags, upload completion, and status-based download links. Implementing
and persisting this flow is substantial. It would require `TOPAZ_API_KEY` and a verified
account credit-to-dollar quote. No conversion is assumed or used here.

The installed Deep Agents 0.7.23 signature was inspected locally. Existing native interrupts,
checkpoints, and resume decisions remain the approval mechanism. No new orchestration framework
or provider SDK is introduced.

## Verified identifiers and pricing

All linked sources were read 2026-10-09. The actual fal request schemas are the
[upscale schema](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=topaz/upscale/video/generative)
and [interpolation schema](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=topaz/interpolate/video).
They verify the endpoints and model enum values used by the adapter.

| Model | fal model value | Topaz direct identifier and source |
| --- | --- | --- |
| Starlight Precise 2.6 | `Starlight Precise 2.6` | `slp-2.6`, [official model documentation](https://developer.topazlabs.com/video-models/starlight/starlight-precise-2.6) |
| Apollo | `Apollo` | `apo-8`, [official Apollo documentation](https://developer.topazlabs.com/video-models/frame-interpolation/apollo) |
| Chronos | `Chronos` | `chr-2`, [official Chronos documentation](https://developer.topazlabs.com/video-models/frame-interpolation/chronos) |

Direct identifiers normalize to fal names. They are not sent to fal as model values.
No requested model or endpoint remains UNVERIFIED. Live account access and behavior are untested.

The [official fal upscale pricing page](https://fal.ai/models/topaz/upscale/video/generative)
gives these Starlight examples before Renderhaus fees.

| Ten seconds of output | At 30 FPS | At 60 FPS |
| --- | --- | --- |
| Up to 1080p | $1.20 | $2.40 |
| 4K | $2.60 | $5.10 |

Duration scaling is a derived estimate from these examples, not invoice reconciliation.
Other output FPS and intermediate dimensions above 1080p remain TODO with an unknown estimate.
In particular, 4K60 uses its published example rather than doubling the rounded 4K30 price.

The [official fal interpolation pricing page](https://fal.ai/models/topaz/interpolate/video)
prices newly generated frames when slowdown is 1. Apollo and Chronos examples are $0.30 at
1080p and $0.60 at 4K for ten seconds converted from 30 to 60 FPS. The estimate derives
$0.001 and $0.002 per added frame from those examples. Slow-motion pricing remains unknown
because the page describes a separate full-output-duration calculation without its complete
formula. Unknown quotes permit dry-run previews but block live submission before any request.
The existing Renderhaus platform fee is disclosed separately by the billing calculation.

[Topaz credit pricing](https://developer.topazlabs.com/getting-started/model-pricing) and its
model pages verify credit-based direct billing. Those credits are not used for fal billing.

## Licence and input permissions

Each of Starlight Precise 2.6, Apollo, and Chronos uses proprietary closed weights through a
commercial hosted API. The [fal model cards](https://fal.ai/models/topaz/interpolate/video)
label commercial use. The [fal API Services terms](https://fal.ai/legal/api-services) license
customer integrations, and the [fal Terms of Service](https://fal.ai/legal/terms-of-service)
require input rights and applicable consents and restrict competing-model training.

Every model policy therefore records `license=service-terms`, `weights_license=closed-weights`,
and `training_eligible=false`. No unambiguous output-training grant was verified. Input media
rights and required real-face/voice permissions remain required under the host terms. No
Topaz-specific recorded-consent API flow was verified. No model weights, AGPL code, or
non-commercial implementation are copied or vendored.

## Validation and outstanding work

Offline tests cover typed arguments, exact request bodies, dry-run gates, queue states,
model identity after restart, artifact validity, routing precedence, pricing, cost disclosure,
and native approval rejection. No provider requests use real credentials.
Native approval acceptance also restores and dispatches the exact quoted request once.
Regression cases cover FPS multipliers and default scaling without changing quote controls.
Five Topaz routing fixture rows activate. Other pending and licence-blocked providers retain
accurate skips. The inventory is 13 providers, 99 Gateway tools, and 24 skills.

Final offline verification on 2026-10-09: 1,146 tests run, 1,118 passed, 28 skipped,
including 42 passing Topaz contract, lifecycle and wiring tests. Ruff, `scripts/ci_check.py`
(all providers forced dry-run), and the Studio TypeScript typecheck pass. The temporary
Studio dependency symlink was removed. Logs are under ignored `.renderhaus/e2e/topaz-*`.
There are 103 active routing fixtures and 26 dependency/semantics skips; the
[capability map](CAPABILITY_MAP.md#skills-and-routing-fixtures) lists their reasons.
The [decision record](topaz-decisions.tsv) records sources, read dates and limitations.

Comet browser E2E is blocked because Comet control is unavailable in this environment. No UI
flow or live artifact was observed, and mocks do not establish browser success. The requested
flow remains to approve or reject finishing in Studio and open/play its saved MP4. Paid/live
calls are also excluded by the user's offline authorization.

Outstanding work is real Comet E2E, account access verification, visual A/B comparison,
non-example upscale pricing, slow-motion pricing, invoice reconciliation, and an optional
direct adapter. The configuration remains dry-run until an operator deliberately enables it.
