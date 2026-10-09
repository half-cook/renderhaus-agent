# Wan 3 generation on fal

Wan 3.0 is the quality-first default for t2v, i2v and reference_video.
The three tools use the existing Fal Gateway target, queue client and poll tool.
`FAL_DRY_RUN` defaults to `true`. No live or paid provider request was made for this change.

## Tools and verified request contracts

All official sources below were read on **2026-10-09**.

| Canonical ID | Gateway tool | Official endpoint | Specific inputs |
| --- | --- | --- | --- |
| `wan3_t2v` | `Fal___generate_wan3_t2v` | `alibaba/wan-3.0/text-to-video` | Required `prompt`, 1 to 20,000 characters |
| `wan3_i2v` | `Fal___generate_wan3_i2v` | `alibaba/wan-3.0/image-to-video` | Required `start_image_url`, optional `end_image_url` and `prompt` |
| `wan3_r2v` | `Fal___generate_wan3_r2v` | `alibaba/wan-3.0/reference-to-video` | Optional `prompt`, `reference_image_urls`, `reference_video_urls`, `reference_audio_urls`, `file_url`, `web_url` |

Common native inputs are `resolution` with 480p, 720p or 1080p; `aspect_ratio` with
adaptive, 16:9, 4:3, 1:1, 3:4 or 9:16; integer `duration` from 2 to 30 seconds;
`audio`; `enable_prompt_expansion`; `enable_thinking`; `seed` from 0 to 2147483647;
and `enable_safety_checker`. Defaults follow fal: 1080p, adaptive, 5 seconds, audio on,
prompt expansion on, thinking off, safety checking on. Optional I2V/R2V prompts have
at most 20,000 characters. There is no documented `negative_prompt` input.
Multi-shot instructions belong in the prompt, not an invented boolean field.

R2V accepts up to 10 images, 5 videos and 5 audio references. Video references total at
most 15 seconds, with each video at least 16 fps. Audio references total at most 15 seconds.
`file_url` and `web_url` require `enable_thinking=true`. Web pages must be public.
These are reference-conditioning inputs. They do not promise duration-preserving edits
or video extension. Those use the built direct [Model Studio tools](ALIBABA_MODELSTUDIO.md).

The contracts require caller-measured `reference_video_durations`, `reference_video_fps`
and `reference_audio_durations` parallel to their URL lists. They check counts, positive
finite durations, total duration and minimum fps before submission. They do not fetch or
probe the supplied media. Measurement accuracy therefore depends on caller metadata;
fal still validates the actual files. These local fields never enter the fal request JSON.

The OpenAPI accepts `duration=null` for smart duration. Dry-run preserves that input.
Its quote is unknown. Live smart duration is blocked before submission until Studio can
reconcile billing against the actual generated duration. Use an explicit duration for live work.

Submit once and save the returned composite `job_id`. Poll `Fal___get_video_task` with
`download=true` for a completed MP4. A queued task or dry-run preview is incomplete media.
The common poll tool preserves the endpoint's non-training metadata.

Official schemas and OpenAPI are available from these pages:

- [T2V API](https://fal.ai/models/alibaba/wan-3.0/text-to-video/api) and [OpenAPI](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=alibaba/wan-3.0/text-to-video).
- [I2V API](https://fal.ai/models/alibaba/wan-3.0/image-to-video/api) and [OpenAPI](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=alibaba/wan-3.0/image-to-video).
- [R2V API](https://fal.ai/models/alibaba/wan-3.0/reference-to-video/api) and [OpenAPI](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=alibaba/wan-3.0/reference-to-video).

## Pricing, approvals and routing

[fal's Wan 3 page](https://fal.ai/wan-3) and the
[R2V pricing page](https://fal.ai/models/alibaba/wan-3.0/reference-to-video) publish
$0.05, $0.10 and $0.20 per output second at 480p, 720p and 1080p, respectively.
The [R2V schema](https://fal.ai/models/alibaba/wan-3.0/reference-to-video/api) explicitly
bills reference-video duration in addition to output duration. The quote applies the same
resolution rate to both. No distinct input-video rate, audio surcharge or image-reference
surcharge is published. No such extra rate is invented. Prices are list estimates, not invoices.

`server.billing_rates.wan3_price_cents` uses Decimal provider cents.
`cost_for` validates the exact contract, then applies the existing `_with_fee` platform fee.
For example, 10 output seconds plus 5 reference-video seconds at 1080p costs $3.00 provider
plus $0.90 platform fee. Dry-run billing is zero; approval disclosure still shows the list estimate.
Missing reference-video measurements and smart duration disclose unknown cost, never free cost.

All three tools pause for native approval with the estimate, including autonomous runs.
The existing spend cap and `APPROVAL_EXEMPT_TOOLS` are unchanged.
Selection stays explicit request, then named exception, then default. Seedance 2.5 remains
the `dialogue && !real_face_refs` exception. Its T2V, I2V and reference tools now run
Seedance 2.5 through fal US by default. BytePlus 1.5 remains an explicit optional model.
See [Seedance transport and policy](SEEDANCE_2_5.md). Real-face references force Wan.
The stored `project.confidential` field has no routing effect.
Luma, Seedream, Fish, Vidu, Kling generation, Runway generation and legacy VACE code remain.
`local_qc` stays the continuity-QC default.

## Licence and consent

All three endpoint models are **closed weights, commercial API via fal**.
The [Wan 3 page](https://fal.ai/wan-3) describes API-only availability and commercial use.
The model pages label commercial use. [fal's terms](https://fal.ai/legal/terms-of-service)
and [API supplemental terms](https://fal.ai/legal/api-services) govern hosted access.
Section 14(c) restricts using third-party model outputs to train competing models.
All Wan 3 results and model policies therefore set `training_eligible=false`.
This is distinct from the retained Apache Wan 2.x training path. No model weights or
third-party code are vendored, and no AGPL or non-commercial dependencies are introduced.

Section 6(d) requires rights and permissions for input media. Real-face I2V/R2V requests
must declare `real_face_refs=true` and `likeness_consent=true` after obtaining permission.
The shared executor also detects real-face intent in the prompt, preventing omission of the
flag from bypassing consent. The acknowledgement is local policy data, not a fal API field.
Approval disclosure states whether consent is acknowledged or still required.

**UNVERIFIED**: the research lead's Alibaba-specific real-person consent/verification flow.
The [Alibaba guide](https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-guide)
verifies first/last frames and multi-modal references, but the readable guide does not
contain the claimed consent flow. No claim of Alibaba identity verification is made.
Ordinary US fal access is inferred from its commercial listing and service terms;
model-specific geographic guarantees and account entitlement have not been tested.

## Configuration and validation limits

No new environment variable, secret or dry-run flag is required. Satya can use the existing
`FAL_KEY` in environment or the application Secrets Manager JSON and leave `FAL_DRY_RUN=true`.
`scripts/sync_secrets.py` already accepts both through its generic configuration filter.
Changing the dry-run flag is an operator action, never an agent tool argument.

Four Wan-specific routing fixtures are activated: first/last-frame morph, consenting CEO
photo, synthetic multi-shot references without dialogue, and real-actor video references.
Other provider-dependent skips remain documented in [the capability map](CAPABILITY_MAP.md).
`/workspace/rh-runs/inputs/wan3.routing.csv` is absent. The capability workbook is the routing input.

Validation uses fake chat models, fake Gateway calls and mocked fal HTTP. It checks schema
contracts, pricing, polling, consent, training provenance and approval/rejection behavior.
No live fal job, real provider quality, browser interaction or generated-media playback is claimed.
Comet browser E2E is **blocked**, as requested, because Comet control is unavailable here.
The blocked receipt is under ignored `.renderhaus/e2e/` and is recorded with the project hook.

Final offline checks on 2026-10-09 passed: Ruff over agent, lambdas, scripts, server and
providers; full unittest discovery with **852 tests, 40 skipped**; `scripts/ci_check.py`
including all 81 dry-run tools and the Lambda package; and Studio `tsc --noEmit -p .`.
The starting 815-test suite had 44 skips. This change adds 37 tests and activates four
routing fixtures. The remaining 38 routing skips name pending providers or workflows
in [the capability map](CAPABILITY_MAP.md); two unrelated test skips remain.

An additional offline Node smoke exercised the actual Studio store and graph invocation:
three Wan 3 nodes keep their native defaults without legacy VACE fields, the video rail
selects Wan 3, and image animation connects to `start_image_url`. API calls were replaced
with a fake and network fetch was forbidden. This is supporting validation, not browser E2E.
CI ran with an empty `RENDERHAUS_SECRETS_NAME`, every existing provider dry-run flag true,
and `PIP_NO_INDEX=1` using cached public wheels. No new dry-run flag exists.

The implementation changes the fal contract/API, common argument validation, tool registry,
Gateway schema, billing, routing/policy/executor, four existing skills, fixtures/tests,
Studio options/canvas defaults/labels, inventory checks and provider documentation.
The existing Lambda handler, Fal dispatch target and native approval callback need no
new target or separate poller. No secret values or read-only research files are committed.

## Changed files

| Area | Files |
| --- | --- |
| Provider and contracts | `providers/fal/wan3.py`, `providers/fal/api.py`, `providers/contracts.py`, `providers/registry.py` |
| Gateway and billing | `configs/gateway/fal.tools.json`, `server/billing_rates.py` |
| Agent routing and consent | `agent/deep_agent/routing.py`, `agent/deep_agent/routing_policy.json`, `agent/gateway_executor.py` |
| Existing skills | `agent/deep_agent/skills/t2v/SKILL.md`, `agent/deep_agent/skills/i2v/SKILL.md`, `agent/deep_agent/skills/still-then-video/SKILL.md`, `agent/deep_agent/skills/storyboard-shots/SKILL.md` |
| Studio | `server/studio_options.py`, `studio/components/canvas/StudioCanvas.tsx`, `studio/lib/canvas/model-labels.ts`, `studio/lib/canvas/store.ts`, `studio/lib/canvas/tool-registry.ts`, `studio/lib/canvas/types.ts` |
| Inventory and configuration | `scripts/ci_check.py`, `scripts/sync_secrets.py`, `.github/workflows/deploy.yml`, `Dockerfile.agentcore` |
| Documentation | `docs/FAL_WAN3_PROVIDER.md`, `docs/fal-wan3-decisions.tsv`, `docs/CAPABILITY_MAP.md`, `docs/SKILLS.md`, `docs/DEEP_AGENT.md` |
| Tests and fixtures | `tests/fixtures/skill_routing.json`, `tests/test_fal_wan3.py`, `tests/test_wan3_billing.py`, `tests/test_wan3_routing.py`, `tests/test_fal_provider.py`, `tests/test_capability_evidence.py`, `tests/test_capability_selection_edges.py`, `tests/test_deep_agent.py`, `tests/test_intent_graph.py`, `tests/test_provider_ladder.py`, `tests/test_skill_routing.py`, `tests/test_vidu_q4_routing.py` |
