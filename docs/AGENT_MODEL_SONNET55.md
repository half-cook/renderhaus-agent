# Sonnet 5.5 branch handoff

This branch changes the Deep Agents default to `anthropic:claude-sonnet-5-5`,
preserves source fps and render quality, starts independent narration alongside
video, and supplies final cost details from persisted records. It also adds a
guarded [lighthouse operator driver](E2E_LIGHTHOUSE.md). The implementation uses
installed Deep Agents 0.7.23 and was developed with fake model/provider responses.

## Model and pricing

The public [Sonnet overview](https://platform.claude.com/docs/en/models/sonnet-5-5/overview),
[migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide),
[effort guide](https://platform.claude.com/docs/en/build-with-claude/effort) and
[pricing page](https://platform.claude.com/docs/en/about-claude/pricing) were read
2026-10-09. They verify the model ID, adaptive thinking, all five effort levels,
1M context and 128K maximum output. The integration omits manual thinking budgets,
sampling overrides, prefill and forced tool choice. The complete API contract and
links to thinking/tool-use documentation are in [DEEP_AGENT.md](DEEP_AGENT.md).

Sonnet list prices per million tokens are $2 input, $10 output, $2.50 five-minute
cache write, $4 one-hour cache write and $0.10 cache read. There is no Sonnet
long-context tier. The ledger distinguishes both cache durations. Retained Haiku
and Opus rates use the same official pricing source; global standard requests do
not apply Batch discounts or the US-only inference multiplier.

The driver's existing media estimates were rechecked against official pages on
2026-10-09: [Wan 3 on fal](https://fal.ai/wan-3) is $0.05/$0.10/$0.20 per second
at 480p/720p/1080p. [ElevenLabs API pricing](https://elevenlabs.io/pricing/api)
lists v4 Turbo at $0.011 per 1,000 characters through October 12, then $0.04.
The existing estimator retains that expiry and platform fees; local assembly
has no provider charge. Lambda compute remains unknown. These media rates
were not changed by this branch.

Manager/planner/general-purpose default to medium effort; media/audio/editor
default to low. Existing global and per-role model/effort overrides remain
available. The forwarding paths already support them. No new key or secret is
required; the selected Anthropic model uses the existing `ANTHROPIC_API_KEY`.
Live quality/latency calibration of these effort choices remains pending.

Claude Sonnet 5.5, and retained Claude Haiku/Opus token-price entries, use the
proprietary commercial API under [Anthropic Commercial Terms](https://www.anthropic.com/legal/commercial-terms),
read 2026-10-09. Planning outputs are treated as `training_eligible=false`;
commercial access does not imply permission for competing-model training.
Existing media-model licences, consent rules and training policies are unchanged.
The new metadata dependency is PyAV 14.2.0, BSD-3-Clause, whose selected wheels
bundle FFmpeg GPL-3.0-or-later. It adds no model weights, AGPL or non-commercial
code. [The assembly reference](LOCAL_ASSEMBLY.md) links the licence/build sources
and records redistribution obligations and the compatible Lambda wheel.
The optional live lighthouse path retains Wan 3's closed commercial service
licence under [fal terms](https://fal.ai/legal/terms-of-service) and Eleven v4
Turbo's service licence under [ElevenLabs terms](https://elevenlabs.io/terms-of-use)
and [use policy](https://elevenlabs.io/use-policy), read 2026-10-09. Both retain
`training_eligible=false`. Existing rights/likeness/speaker-consent requirements
remain in place. Alibaba's specific real-face consent flow and other ElevenLabs
v4 endpoint variants remain marked unverified in the existing provider references;
this branch does not activate them. ElevenLabs commercial use requires a paid plan.

## Tools, skills and routing

No Gateway tool or provider was added. Existing `Remotion___render_timeline`
accepts optional `fps` and positive-integer `video_bitrate`; visuals accept
measured `source_fps` and `source_bitrate`. The regenerated schema preserves the
tool's ID. Local and Lambda assembly share resolved frame-rate and quality
settings. [LOCAL_ASSEMBLY.md](LOCAL_ASSEMBLY.md) describes source measurement.

`audio-bed` and `final-assembly` now instruct parallel independent generation and
source-preserving assembly. The router emits execution groups without changing
capability selection. Explicit request, exception predicate, default remains the
selection order; paid approvals and the existing autonomous cap remain in place.
No confidential-project routing, price tiers or cheapest-provider selection was added.

The inventory remains 15 providers, 113 Gateway tools, 24 packaged skills and
137 capability fixture rows: 133 active, four skipped. No routing row was
activated by this branch. One skip needs HyperFrames overlays; three need
`cutaway_record` product-demo capture. Their existing named dependency reasons
remain. Count thresholds therefore stay unchanged.

The skipped rows are one `conversational-edit` → `hyperframes_render` case
(`feat/hyperframes-overlays`) and three `product-demo-video` → `cutaway_record`
cases (`feat/product-demo-capture`).

## Changed files

| Area | Files |
| --- | --- |
| Model configuration and usage | `AGENTS.md`, `agent/backend_config.py`, `agent/deep_agent/usage.py`, `scripts/sync_secrets.py`; model-config, Deep Agents and usage tests |
| Render quality | `providers/remotion/api.py`, `providers/remotion/local.py`, `providers/catalog.py`, `providers/contracts.py`, `providers/registry.py`, `configs/gateway/remotion.tools.json`; quality, provider, transcript and media-recovery tests |
| Parser packaging | `pyproject.toml`, `scripts/ci_check.py`, `scripts/deploy_gateway.py`, `scripts/deploy_media_updates.py`, `tests/test_deploy_gateway_package.py` |
| Orchestration and costs | `agent/deep_agent/routing.py`, `agent/deep_agent/runner.py`, `agent/deep_agent/costs.py`, `agent/gateway_executor.py`, audio-bed/final-assembly skills, `tests/test_deep_agent_execution.py` |
| Operator driver | `scripts/e2e_lighthouse.py`, `scripts/local_gateway.py`, `tests/test_e2e_lighthouse.py` |
| Documentation | `docs/DEEP_AGENT.md`, `docs/SKILLS.md`, `docs/LOCAL_ASSEMBLY.md`, `docs/E2E_LIGHTHOUSE.md`, this handoff and `docs/agent-model-sonnet55-decisions.tsv` |

Changed test files are `test_agent_model_config.py`, `test_deep_agent.py`,
`test_deep_agent_usage.py`, `test_deep_agent_execution.py`,
`test_deploy_gateway_package.py`, `test_e2e_lighthouse.py`,
`test_media_recovery.py`, `test_remotion_provider.py`, `test_remotion_quality.py`
and `test_transcript_edit.py`, all under `tests/`.

The decisions TSV records the source URLs, read date, observed failing tests,
verification results and unresolved browser check. It does not copy the
read-only source capability map or installed skills into this repository.

## Validation limits

Final required checks passed: Ruff across `agent lambdas scripts server providers`,
1,414 unit tests with six skips in 74.491 seconds, `scripts/ci_check.py` and the
Studio TypeScript check. The temporary `studio/node_modules` symlink was removed.
CI built a 62,744,529-byte arm64 ZIP, checked the parser pin/native module and
verified the expanded bundle fits Lambda's 250 MiB limit. The test suite adds
30 tests to the starting 1,384; routing dependency skips remain unchanged.

The generated 30 fps fixture exports at 30/1 and 593,506 b/s from a 566,061 b/s
source. Other checks cover fractional fps, explicit timeline fps, shared Lambda
parameters, TTS dispatch before video-poll completion, costs across approval
resumes, cap rejection, paid failures/cancellation and actual MP4 decoding.

No live Anthropic, provider or AWS call, deployment, push or PR was performed.
Comet is unavailable, so Studio browser E2E remains blocked and pending.
The ignored `.renderhaus/e2e/` receipt records that blocker using the project
hook. Offline checks do not establish live API access, perceptual quality,
model planning compliance or delivery through the browser.

No new environment variable, secret or dry-run flag is required. Existing
`REMOTION_LOCAL_MEDIA_HOSTS` is now forwarded to the Remotion Lambda for optional
additional trusted hosts. An operator deploying the larger ZIP must configure an
existing same-region `AWS_S3_BUCKET` or `REMOTION_APP_BUCKET_NAME`; live deployment
and AWS permissions were not tested. The driver defaults to plan-only and retains
all existing provider dry-run defaults.

## Commits before handoff

| Commit | Change |
| --- | --- |
| `0859f00` | Use Sonnet 5.5 for Deep Agents with verified token pricing |
| `13a0c13` | Preserve source frame rate and render quality across assembly backends |
| `383fdf6` | Start independent narration alongside video and report recorded media costs |
| `fa5f03a` | Add a capped lighthouse operator driver with offline safety checks |
| `b625974` | Measure remote render sources in Lambda and package the compatible parser |

The final documentation/receipt commit follows these commits. The branch remains
`feat/agent-model-sonnet55`; no push or PR was made.
